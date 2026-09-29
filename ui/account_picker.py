"""Hộp thoại xem và tick tay danh sách tài khoản.

Màn chính giờ là bảng LOG chạy — thứ người dùng cần nhìn khi bấm CHẠY.
Danh sách tài khoản vẫn cần, nhưng chỉ để kiểm tra và tick tay khi muốn;
không phải thứ phải mở ra mỗi lần chạy. Vì vậy nó nằm trong hộp thoại
riêng, mở bằng nút "Danh sách tài khoản" ở thanh trên.

Có sẵn các nút chọn nhanh: chạy hết, không chọn, chỉ chọn còn phiên —
giống hành vi cũ, nên người dùng cũ không phải đổi thói quen.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
)

from core.models import AccountTableModel, HC_ALIVE, HEALTH_LABELS
from .delegates import AccountCellDelegate


class AccountPickerDialog(QDialog):
    """Xem / lọc / tick tay danh sách tài khoản."""

    def __init__(self, model: AccountTableModel, parent=None):
        super().__init__(parent)
        self.model = model
        # bản sao riêng để lọc tự do, không làm bận bảng chính
        self._picker = AccountTableModel(self)
        # 0 = không phân trang, hiện hết. Còn phân trang 25/trang thì
        # các dòng ngoài trang đầu không vẽ ra, quét chuột tới đó sẽ
        # không ăn dù dữ liệu đúng.
        self._picker.set_per_page(0)
        self._picker.load(list(model.accounts()))

        self.setWindowTitle("Danh sách tài khoản")
        self.resize(1000, 640)
        v = QVBoxLayout(self)
        v.setSpacing(6)

        # --- thanh lọc ---
        top = QHBoxLayout()
        top.setSpacing(4)
        self.in_search = QLineEdit()
        self.in_search.setPlaceholderText(
            "Lọc theo username, email, proxy, trạng thái…")
        self.in_search.setClearButtonEnabled(True)
        top.addWidget(self.in_search, 1)
        self.cb_filter = QComboBox()
        for k, lbl in AccountTableModel.FILTER_LABELS.items():
            self.cb_filter.addItem(lbl, k)
        top.addWidget(self.cb_filter)
        v.addLayout(top)

        # --- bảng ---
        self.table = QTableView()
        self.table.setModel(self._picker)
        # Ô tick và quét chuột nằm trong delegate dùng chung với bảng
        # chính — gắn vào đây để vẫn tick/kéo-quét được trong hộp thoại.
        self.delegate = AccountCellDelegate(self.table)
        self.table.setItemDelegate(self.delegate)
        self.delegate.attach_view(self.table)
        self.delegate.attach_sweep_filter(self.table.viewport())
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 400)
        self.table.setColumnWidth(1, 260)
        vh = self.table.verticalHeader()
        vh.setMinimumSectionSize(18)
        vh.setDefaultSectionSize(18)
        v.addWidget(self.table, 1)

        # --- chọn nhanh + số đã chọn ---
        row = QHBoxLayout()
        row.setSpacing(4)
        b_all = QPushButton("☑ Chọn tất cả")
        b_all.clicked.connect(lambda: self._bulk(True))
        b_none = QPushButton("☐ Bỏ chọn")
        b_none.clicked.connect(lambda: self._bulk(False))
        b_view = QPushButton("Chọn những dòng đang xem")
        b_view.clicked.connect(
            lambda: self._set_rows(self._picker.page_rows(), True))
        b_good = QPushButton("✔ Chỉ chọn còn phiên")
        b_good.clicked.connect(self._select_with_session)
        for b in (b_all, b_none, b_view, b_good):
            row.addWidget(b)
        self.lbl_n = QLabel("")
        row.addStretch(1)
        row.addWidget(self.lbl_n)
        v.addLayout(row)

        # --- đếm trạng thái sức khoẻ ---
        self.lbl_health = QLabel("")
        self.lbl_health.setProperty("role", "hint")
        self.lbl_health.setWordWrap(True)
        v.addWidget(self.lbl_health)

        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        box.button(QDialogButtonBox.StandardButton.Ok).setText(
            "Áp dụng")
        box.button(QDialogButtonBox.StandardButton.Ok).setObjectName(
            "primary")
        box.accepted.connect(self._apply)
        box.rejected.connect(self.reject)
        v.addWidget(box)

        # nối tín hiệu
        self.in_search.textChanged.connect(self._picker.set_query)
        self.cb_filter.currentIndexChanged.connect(
            lambda i: self._picker.set_filter(self.cb_filter.itemData(i)))
        self._picker.dataChanged.connect(lambda *_: self._refresh_n())
        self._picker.modelReset.connect(self._refresh_n)
        self._refresh_n()

    # ------------------------------------------------------------------ #
    def _set_rows(self, rows, checked: bool) -> None:
        for a in rows:
            a.selected = checked
        self._picker._refresh_page()

    def _bulk(self, checked: bool) -> None:
        if checked:
            self._set_rows(self._picker.filtered_accounts(), True)
        else:
            self._set_rows(list(self._picker.accounts()), False)

    def _select_with_session(self) -> None:
        for a in self._picker.accounts():
            a.selected = a.has_session()
        self._picker._refresh_page()

    def _refresh_n(self) -> None:
        m = self._picker
        self.lbl_n.setText(f"đã chọn {m.selected_count()}/{m.total}")
        counts: dict[str, int] = {}
        for a in m.accounts():
            counts[a.health] = counts.get(a.health, 0) + 1
        parts = [f"{HEALTH_LABELS.get(k, '?')}: {v}"
                 for k, v in sorted(counts.items(), key=lambda kv: -kv[1])]
        self.lbl_health.setText(" · ".join(parts) if parts else "")

    def _apply(self) -> None:
        """Chép cờ đã chọn về model chính rồi đóng."""
        sel = {id(a): a.selected for a in self._picker.accounts()}
        for a in self.model.accounts():
            if id(a) in sel:
                a.selected = sel[id(a)]
        self.model._refresh_page()
        self.accept()

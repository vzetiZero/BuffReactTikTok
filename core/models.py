"""Mô hình dữ liệu cho account + QAbstractTableModel cho bảng trên GUI.

Điểm quan trọng: mọi cập nhật từ worker thread đều đi qua `id` của account,
không đi qua chỉ số dòng (row index) — vì row index thay đổi khi sort/filter/insert.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor

# --- Custom roles để GUI / controller truyền dữ liệu kèm theo ---
ID_ROLE = Qt.ItemDataRole.UserRole + 1
CHECK_ROLE = Qt.ItemDataRole.UserRole + 2
# Số thứ tự toàn cục trong danh sách (không phải số dòng trên trang hiện tại)
NO_ROLE = Qt.ItemDataRole.UserRole + 3
HAS_SESSION_ROLE = Qt.ItemDataRole.UserRole + 4

# --- Trạng thái (dùng chung cho model và backend) ---
ST_IDLE = "Chờ"
ST_RUNNING = "Đang chạy"
ST_OK = "Thành công"
ST_FAIL = "Lỗi"
ST_SKIP = "Bỏ qua"
ST_DONE = "Hoàn tất"  # đăng nhập OK nhưng chưa bình luận (chỉ chế độ check)


_STATUS_COLORS = {
    ST_IDLE: QColor("#9aa4b2"),
    ST_RUNNING: QColor("#f5a623"),
    ST_OK: QColor("#2ecc71"),
    ST_FAIL: QColor("#e74c3c"),
    ST_SKIP: QColor("#7f8c8d"),
    ST_DONE: QColor("#3498db"),
}


_MISSING = object()


@dataclass(slots=True)
class Account:
    """Một tài khoản TikTok đọc từ file cookie."""

    id: str
    username: str
    email: str
    password: str
    ms_token: str
    device_id: str
    cookie: dict[str, str] = field(default_factory=dict)
    raw: str = ""

    # Trạng thái runtime (chỉ dùng khi chạy app, không serialize)
    selected: bool = True
    status: str = ST_IDLE
    note: str = ""
    comment_id: str = ""
    found: bool = False
    login_ok: bool = False

    # Proxy riêng (gán từ tab Cài đặt)
    proxy: str = ""              # URL curl_cffi dùng thật (có mật khẩu)
    proxy_label: str = ""        # dạng hiển thị, đã che mật khẩu

    def has_session(self) -> bool:
        """Cookie còn sống hay không — dựa vào các key bắt buộc của web login."""
        return "sessionid_ss" in self.cookie and "sid_tt" in self.cookie

    def expiry_hint(self) -> str:
        """Ngày hết hạn từ `sid_guard` = sid|ts|ttl|... (URL-encode bằng %7C)."""
        raw = self.cookie.get("sid_guard", "")
        parts = raw.replace("|", "%7C").split("%7C")
        if len(parts) >= 3 and parts[1].isdigit():
            import datetime

            ttl = int(parts[2]) if parts[2].isdigit() else 0
            end = int(parts[1]) + ttl
            return datetime.datetime.fromtimestamp(end).strftime("%Y-%m-%d")
        return ""


@dataclass(slots=True)
class TaskResult:
    """Kết quả trả về từ backend cho 1 account."""

    status: str
    note: str = ""
    comment_id: str = ""
    found: bool = False
    ok: bool = False
    code: int = -1


class AccountTableModel(QAbstractTableModel):
    """Bảng 2 cột đúng yêu cầu: A = thông tin tài khoản, B = trạng thái."""

    HEADERS = ["A · Tài khoản", "B · Trạng thái"]
    COL_ACCOUNT, COL_STATUS = 0, 1

    # --- bộ lọc nhanh (combo trên thanh tìm kiếm) ---
    F_ALL = "all"
    F_HAS_SESSION = "has_session"
    F_NO_SESSION = "no_session"
    F_SELECTED = "selected"
    F_UNSELECTED = "unselected"
    F_HAS_PROXY = "has_proxy"
    F_OK = "ok"
    F_FAIL = "fail"

    FILTER_LABELS = {
        F_ALL: "Tất cả",
        F_HAS_SESSION: "Còn phiên đăng nhập",
        F_NO_SESSION: "Thiếu phiên",
        F_SELECTED: "Đã tick",
        F_UNSELECTED: "Chưa tick",
        F_HAS_PROXY: "Đã gán proxy",
        F_OK: "Thành công",
        F_FAIL: "Bị lỗi",
    }

    STATUS_LABELS = {
        ST_IDLE: "Chờ",
        ST_RUNNING: "Đang chạy…",
        ST_OK: "✔ Thành công",
        ST_FAIL: "✖ Lỗi",
        ST_SKIP: "– Bỏ qua",
        ST_DONE: "● Hoàn tất",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[Account] = []     # toàn bộ tài khoản (nguồn chân lý)
        self._view: list[Account] = []     # sau khi lọc + sắp xếp
        self._page = 0                     # trang hiện tại, đánh số từ 0
        self._per_page = 25                # số dòng mỗi trang; 0 = không phân trang
        self._query = ""                   # từ khoá tìm kiếm
        self._filter = self.F_ALL
        self._sort_col = 0                 # 0 = STT, 1 = username
        self._sort_desc = False
        # cache chuỗi tìm kiếm, tránh lower() lặp lại mỗi lần lọc
        self._hay_cache: dict[str, str] = {}

    # ---- API cho controller ----
    def load(self, accounts: list[Account]) -> None:
        self.beginResetModel()
        self._rows = accounts
        self._page = 0
        self._hay_cache = {a.id: self._haystack(a) for a in accounts}
        self._rebuild_view()
        self.endResetModel()

    # ---- tìm kiếm / lọc / sắp xếp ---------------------------------- #
    @staticmethod
    def _haystack(a: Account) -> str:
        """Chuỗi dùng để tìm kiếm: gộp mọi thông tin hay tìm."""
        return " ".join((
            a.username, a.email, a.id, a.proxy_label, a.status, a.note,
        )).lower()

    def set_query(self, text: str) -> None:
        q = (text or "").strip().lower()
        if q == self._query:
            return
        self.beginResetModel()
        self._query = q
        self._page = 0
        self._rebuild_view()
        self.endResetModel()

    @property
    def query(self) -> str:
        return self._query

    def set_filter(self, key: str) -> None:
        if key == self._filter:
            return
        self.beginResetModel()
        self._filter = key
        self._page = 0
        self._rebuild_view()
        self.endResetModel()

    @property
    def filter(self) -> str:
        return self._filter

    def set_sort(self, col: int, desc: bool) -> None:
        if col == self._sort_col and desc == self._sort_desc:
            return
        self.beginResetModel()
        self._sort_col, self._sort_desc = col, desc
        self._page = 0
        self._rebuild_view()
        self.endResetModel()

    @property
    def sort_col(self) -> int:
        return self._sort_col

    @property
    def sort_desc(self) -> bool:
        return self._sort_desc

    def _matches(self, a: Account) -> bool:
        f = self._filter
        if f == self.F_HAS_SESSION and not a.has_session():
            return False
        if f == self.F_NO_SESSION and a.has_session():
            return False
        if f == self.F_SELECTED and not a.selected:
            return False
        if f == self.F_UNSELECTED and a.selected:
            return False
        if f == self.F_HAS_PROXY and not a.proxy:
            return False
        if f == self.F_OK and a.status not in (ST_OK, ST_DONE):
            return False
        if f == self.F_FAIL and a.status != ST_FAIL:
            return False
        if self._query:
            hay = self._hay_cache.get(a.id)
            if hay is None:
                hay = self._hay_cache[a.id] = self._haystack(a)
            # từ khoá có khoảng trắng -> phải khớp TẤT CẢ các từ
            for term in self._query.split():
                if term not in hay:
                    return False
        return True

    def _rebuild_view(self) -> None:
        """Tính lại danh sách hiển thị. Gọi trong begin/endResetModel."""
        view = [a for a in self._rows if self._matches(a)]
        col, desc = self._sort_col, self._sort_desc
        if col == 0:
            # sắp xếp theo số thứ tự gốc -> chính là thứ tự trong _rows
            order = {id(a): i for i, a in enumerate(self._rows)}
            view.sort(key=lambda a: order[id(a)], reverse=desc)
        else:
            key = (lambda a: a.username.lower()) if col == 1 \
                else (lambda a: (a.status, a.username.lower()))
            view.sort(key=key, reverse=desc)
        self._view = view

    def clear_search(self) -> None:
        self.beginResetModel()
        self._query = ""
        self._filter = self.F_ALL
        self._page = 0
        self._rebuild_view()
        self.endResetModel()

    # ---- phân trang ----
    @property
    def total(self) -> int:
        """Tổng số tài khoản đã nạp (không phụ thuộc bộ lọc)."""
        return len(self._rows)

    @property
    def view_count(self) -> int:
        """Số tài khoản khớp bộ lọc / tìm kiếm."""
        return len(self._view)

    @property
    def per_page(self) -> int:
        return self._per_page

    @property
    def page(self) -> int:
        return self._page

    @property
    def page_count(self) -> int:
        if self._per_page <= 0 or not self._view:
            return 1
        return (len(self._view) + self._per_page - 1) // self._per_page

    @property
    def page_first(self) -> int:
        """Số thứ tự đầu tiên của trang, tính trên tập đang lọc (1-based)."""
        return self._page * self._per_page + 1 if self._per_page else 1

    @property
    def page_last(self) -> int:
        if self._per_page <= 0:
            return len(self._view)
        return min((self._page + 1) * self._per_page, len(self._view))

    def set_per_page(self, n: int) -> None:
        if n == self._per_page:
            return
        self.beginResetModel()
        self._per_page = n
        self._page = 0
        self.endResetModel()

    def set_page(self, page: int) -> None:
        page = max(0, min(page, self.page_count - 1))
        if page == self._page:
            return
        self.beginResetModel()
        self._page = page
        self.endResetModel()

    def next_page(self) -> None:
        self.set_page(self._page + 1)

    def prev_page(self) -> None:
        self.set_page(self._page - 1)

    def first_page(self) -> None:
        self.set_page(0)

    def last_page(self) -> None:
        self.set_page(self.page_count - 1)

    def page_rows(self) -> list[Account]:
        if self._per_page <= 0:
            return list(self._view)
        start = self._page * self._per_page
        return self._view[start:start + self._per_page]

    def page_slice(self) -> tuple[int, int]:
        """Khoảng chỉ số [start, end) của trang trong tập đang lọc."""
        if self._per_page <= 0:
            return 0, len(self._view)
        start = self._page * self._per_page
        return start, min(start + self._per_page, len(self._view))

    def row_to_account(self, row: int) -> Account | None:
        """Đổi chỉ số dòng trên bảng -> tài khoản (đã qua lọc + phân trang)."""
        start, end = self.page_slice()
        i = start + row
        if 0 <= i < end and i < len(self._view):
            return self._view[i]
        return None

    def _view_index(self, acc: Account) -> int:
        """Vị trí của account trong tập đang lọc, -1 nếu đang bị ẩn."""
        for i, a in enumerate(self._view):
            if a is acc:
                return i
        return -1

    def accounts(self) -> list[Account]:
        return self._rows

    def by_id(self, acc_id: str) -> Account | None:
        for a in self._rows:
            if a.id == acc_id:
                return a
        return None

    def update_row(self, acc_id: str, **fields) -> None:
        """Được gọi từ GUI thread (slot của signal) — an toàn về thread.

        Chỉ phát `dataChanged` nếu dòng đó đang nằm trên trang hiện tại; nếu không
        thì sự thay đổi vẫn được ghi vào object, lần lật trang sau sẽ thấy.
        """
        acc = self.by_id(acc_id)
        if acc is None:
            return
        changed = False
        for key, value in fields.items():
            if getattr(acc, key, _MISSING) != value:
                setattr(acc, key, value)
                changed = True
        if not changed:
            return

        # dòng đang bị lọc bỏ hoặc ở trang khác: dữ liệu đã lưu trong object,
        # lần vẽ sau sẽ thấy — không phát tín hiệu để tránh vẽ sai chỗ
        vi = self._view_index(acc)
        if vi < 0:
            return
        start, end = self.page_slice()
        if not (start <= vi < end):
            return
        self.dataChanged.emit(
            self.index(vi - start, 0),
            self.index(vi - start, self.columnCount() - 1),
        )

    def reset_status(self) -> None:
        for a in self._rows:
            a.status, a.note, a.comment_id, a.found = ST_IDLE, "", "", False
            a.login_ok = False
        self._refresh_page()

    def _refresh_page(self) -> None:
        """Phát tín hiệu vẽ lại trang hiện tại."""
        n = self.rowCount()
        if n:
            last = self.columnCount() - 1
            self.dataChanged.emit(self.index(0, 0), self.index(n - 1, last))

    def _emit_col(self, col: int) -> None:
        n = self.rowCount()
        if n:
            self.dataChanged.emit(self.index(0, col), self.index(n - 1, col))

    def toggle_all(self, checked: bool) -> None:
        for a in self._rows:
            a.selected = checked
        self._emit_col(self.COL_ACCOUNT)

    def select_none(self) -> None:
        self.toggle_all(False)

    def toggle_page(self, checked: bool) -> None:
        """Chỉ tick/bỏ tick những dòng đang hiển thị trên trang này."""
        for a in self.page_rows():
            a.selected = checked
        self._emit_col(self.COL_ACCOUNT)

    def toggle_view(self, checked: bool) -> None:
        """Tick/bỏ tick MỌI tài khoản khớp bộ lọc — dùng khi lọc theo
        nhóm nhỏ (ví dụ "Thiếu phiên") thay vì cả danh sách hàng chục nghìn."""
        for a in self._view:
            a.selected = checked
        self._refresh_page()

    def select_all_with_session(self) -> None:
        for a in self._rows:
            a.selected = a.has_session()
        self._refresh_page()

    def filtered_accounts(self) -> list[Account]:
        """Tài khoản đang khớp lọc/tìm kiếm."""
        return list(self._view)

    def selected_accounts(self) -> list[Account]:
        """Danh sách được tick — KHÔNG giới hạn theo trang đang xem."""
        return [a for a in self._rows if a.selected]

    def selected_count(self) -> int:
        return sum(1 for a in self._rows if a.selected)

    # ---- QAbstractTableModel API ----
    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        start, end = self.page_slice()
        return max(0, end - start)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.HEADERS)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        acc = self.row_to_account(index.row())
        if acc is None:
            return None
        col = index.column()

        if role == ID_ROLE:
            return acc.id
        if role == CHECK_ROLE:
            return Qt.CheckState.Checked if acc.selected else Qt.CheckState.Unchecked
        # Số thứ tự trong tập đang lọc — liên tục qua các trang
        if role == NO_ROLE:
            return self.page_first + index.row()
        if role == HAS_SESSION_ROLE:
            return acc.has_session()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == self.COL_ACCOUNT:
                return self.account_line(acc)
            return self.STATUS_LABELS.get(acc.status, acc.status)

        if role == Qt.ItemDataRole.CheckStateRole and col == self.COL_ACCOUNT:
            return Qt.CheckState.Checked if acc.selected else Qt.CheckState.Unchecked

        if role == Qt.ItemDataRole.ForegroundRole and col == self.COL_STATUS:
            return _STATUS_COLORS.get(acc.status)

        if role == Qt.ItemDataRole.TextAlignmentRole and col == self.COL_ACCOUNT:
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        if role == Qt.ItemDataRole.ToolTipRole:
            if col == self.COL_STATUS:
                # chỉ trả về ghi chú; để rỗng thì dòng phụ không vẽ gì
                # (tránh lặp lại y hệt dòng trạng thái ở trên)
                return acc.note
            lines = [
                f"Username : {acc.username}",
                f"Email    : {acc.email}",
                f"User ID  : {acc.id}",
                f"Phiên    : {'còn phiên' if acc.has_session() else 'THIẾU sessionid_ss'}",
                f"Proxy    : {acc.proxy_label or acc.proxy or '(IP máy)'}",
            ]
            exp = acc.expiry_hint()
            if exp:
                lines.append(f"Hết hạn  : {exp}")
            if acc.note:
                lines.append(f"Kết quả  : {acc.note}")
            return "\n".join(lines)

        return None

    @staticmethod
    def account_line(acc: Account) -> str:
        flag = "" if acc.has_session() else "   ⚠ thiếu phiên"
        proxy = f"   ·   🌐 {acc.proxy_label}" if acc.proxy_label else ""
        return f"{acc.username}\n{acc.email}{proxy}{flag}"

    def setData(self, index: QModelIndex, value, role=Qt.ItemDataRole.EditRole):  # noqa: N802
        if role != Qt.ItemDataRole.CheckStateRole or index.column() != self.COL_ACCOUNT:
            return False
        acc = self.row_to_account(index.row())
        if acc is None:
            return False
        acc.selected = value == Qt.CheckState.Checked
        self.dataChanged.emit(index, index)
        return True

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        if self.row_to_account(index.row()) is None:
            return Qt.ItemFlag.NoItemFlags
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == self.COL_ACCOUNT:
            base |= Qt.ItemFlag.ItemIsUserCheckable
        return base

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientation == Qt.Orientation.Horizontal:
            if role == Qt.ItemDataRole.DisplayRole:
                return self.HEADERS[section]
            # mũi tên chỉ cột đang sắp xếp
            if role == Qt.ItemDataRole.ToolTipRole:
                return ("Bấm để sắp xếp theo cột này" if section in (0, 1) else None)
        return None

    def sort(self, column: int, order=Qt.SortOrder.AscendingOrder) -> None:  # noqa: A003
        self.set_sort(column, order == Qt.SortOrder.DescendingOrder)

"""Cửa sổ chính: bảng 2 cột A/B, form CID, log, điều khiển chạy/dừng."""

from __future__ import annotations

import datetime
import html
import threading
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QTimer, Slot
from PySide6.QtGui import QAction, QFont, QKeySequence, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTableView,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.backends import build_backend
from core.config import (
    MODE_CHECK,
    MODE_FIND_LIKE,
    MODE_LABELS,
    MODE_LIKE_CID,
    MODE_REPLY_CID,
    RunConfig,
)
from core.gui_bridge import init_bridge
from core.health import HealthChecker
from core.models import (
    HC_ALIVE,
    HC_CHECKING,
    HC_DEAD,
    HC_EXPIRED,
    HC_RISKY,
    HC_UNKNOWN,
    HEALTH_LABELS,
    ID_ROLE,
    ST_DONE,
    ST_FAIL,
    ST_OK,
    ST_SKIP,
    AccountTableModel,
)
from core.parser import load_accounts
from core.proxy import GatewayConfig, ProxyPool
from core.runner import RunController
from core.settings import (
    AppSettings,
    default_path,
    load_accounts_cache,
    save_accounts_cache,
)
from .delegates import AccountCellDelegate
from .detail_panel import DetailPanel
from .meter import ThroughputMeter
from .settings_tab import SettingsTab

# Tên script cài/chạy sidecar, đổi theo hệ điều hành. Trên macOS/Linux không
# chạy được file .bat, nên thông báo hướng dẫn phải trỏ đúng script.
import sys as _sys

IS_MAC = _sys.platform == "darwin"
SIGNER_SCRIPT = "signer.sh" if IS_MAC else "signer.bat"
SIGNER_HOW = (f"chmod +x {SIGNER_SCRIPT} && ./{SIGNER_SCRIPT}"
              if IS_MAC else f"{SIGNER_SCRIPT}")

LEVEL_COLOR = {
    "info": "#4a5a6e",
    "ok": "#1e9e5a",
    "err": "#e74c3c",
    "warn": "#e08b0a",
    "head": "#1a6fc4",
    "cid": "#7d3c98",
}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        init_bridge()
        self.setWindowTitle("TikTok Comment Manager — thả tim hàng loạt theo CID")
        # Mở to cửa sổ: 50 dòng gọn = 800px bảng, cộng ~200px giao diện xung
        # quanh thì cần ~1000px chiều cao — chỉ vừa khi chiếm hết màn hình.
        # Người dùng vẫn tự thu nhỏ lại được.
        self.showMaximized()

        self.settings = AppSettings.load()
        self.proxy_pool = ProxyPool(
            mode=self.settings.proxy_mode,
            gateway=GatewayConfig(
                template=self.settings.gw_template, host=self.settings.gw_host,
                port=self.settings.gw_port, user=self.settings.gw_user,
                password=self.settings.gw_pass, country=self.settings.gw_country,
                enabled=self.settings.gw_enabled,
            ),
        )
        if self.settings.proxy_text:
            self.proxy_pool.load(self.settings.proxy_text)

        self.model = AccountTableModel(self)
        self.accounts: list = []
        self.controller = RunController(
            lambda: build_backend(
                self.backend_kind.currentData(),
                proxy_pool=self.proxy_pool,
                rotate_on_block=self.settings.rotate_on_block,
            ),
            pool=self.proxy_pool,
            rotate_on_block=self.settings.rotate_on_block,
        )
        # Bộ kiểm tra sức khoẻ tài khoản (chuột phải → Kiểm tra trạng thái)
        self.checker = HealthChecker(self.settings, parent=self)
        self.checker._on_applied = self._apply_health
        self.checker.log.connect(self._on_log)
        self._progress: dict[str, int] = {}
        self._last_run = ""
        self._signer_ready = False
        # Hàng đợi cid: chạy xong cid này thì tự nhảy sang cid kế tiếp.
        self._cid_queue: list[str] = []
        self._cid_pos: int = -1
        self._queue_paused: bool = False
        self._dry_run: bool = False
        self._run_accounts: list = []

        self._build_ui()
        self._connect()

        self.controller.started.connect(self._on_started)
        self.controller.finished.connect(self._on_finished)
        self.controller.status.connect(self._on_status)
        self.controller.progress.connect(self._on_progress)
        self.controller.log.connect(self._on_log)
        # đồng hồ tốc độ: đếm theo task ĐÃ TRẢ VỀ, và theo kết quả
        self.controller.task_done.connect(self._on_task_done)

        # kiểm tra sức khoẻ tài khoản
        self.checker.checked.connect(self._on_health_progress)
        self.checker.all_done.connect(self._on_health_done)

        # nhịp 1 giây: cập nhật acc/s, ETA, biểu đồ; 5 giây hỏi sidecar
        self._meter_timer = QTimer(self)
        self._meter_timer.setInterval(1000)
        self._meter_timer.timeout.connect(self._on_meter_tick)
        self._meter_timer.start()
        self._signer_ticks = 0

        self._refresh_detail_task()
        # Khôi phục danh sách cid của phiên làm việc trước
        if self.settings.cid_list:
            self.in_cid.setPlainText(self.settings.cid_list)
        QTimer.singleShot(200, self._check_signer)
        QTimer.singleShot(400, self._after_start)

    # ------------------------------------------------------------------ #
    def _after_start(self) -> None:
        self._restore_accounts()
        if self.settings.proxy_auto_check and self.proxy_pool.has_any():
            self.tabs.setCurrentWidget(self.tab_settings)
            self.tab_settings._on_check()

    def _restore_accounts(self) -> None:
        """Mở app lần sau: tự nạp lại tài khoản đã lưu, khỏi bấm 'Nạp cookie'.

        Ưu tiên đọc lại FILE GỐC nếu vẫn còn, vì file đó luôn mới hơn bản nhớ.
        Chỉ khi file biến mất (đổi máy, xoá nhầm) mới dùng bản nhớ.
        """
        if not self.settings.remember_accounts:
            self._log("head", "Nhấn 'Nạp cookie' ở thanh công cụ để bắt đầu.", "head")
            return

        src = self.settings.last_cookie_file
        if src and Path(src).exists():
            try:
                accounts = load_accounts(src)
            except OSError as e:
                self._log("head", f"Không đọc được file đã lưu: {e}", "warn")
            else:
                if accounts:
                    self._apply_accounts(accounts, f"file {Path(src).name}")
                    self._log("head", "Đã tự nạp lại tài khoản từ lần trước.",
                              "head")
                    return
        cached = load_accounts_cache()
        if cached:
            self._apply_accounts(cached, "bộ nhớ của phiên trước")
            self._log("head",
                      f"Không thấy file cookie cũ — dùng {len(cached)} tài khoản "
                      f"đã lưu. Bấm 'Nạp cookie' để nạp file mới.", "head")
            return
        self._log("head", "Nhấn 'Nạp cookie' ở thanh công cụ để bắt đầu.", "head")

    # ------------------------------------------------------------------ #
    # Dựng giao diện
    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        # Tab 1: bảng tài khoản — chiếm TOÀN BỘ bề ngang
        self.tab_main = QWidget()
        self.tabs.addTab(self.tab_main, "  Quản lý  ")
        # Tab 2: tác vụ
        self.tab_task = QWidget()
        self.tabs.addTab(self.tab_task, "  Tác vụ  ")
        # Tab 3: chi tiết + nhật ký (tách ra để bảng không bị thu hẹp)
        self.tab_detail = QWidget()
        self.tabs.addTab(self.tab_detail, "  Chi tiết  ")
        # Tab 4: cài đặt
        self.tab_settings = SettingsTab(self.settings, self.proxy_pool)
        self.tabs.addTab(self.tab_settings, "  Cài đặt  ")
        root.addWidget(self.tabs, 1)

        self.lbl_info = QLabel("Chưa có dữ liệu")
        self.statusBar().addWidget(self.lbl_info, 1)
        self.lbl_signer = QLabel("sidecar: ?")
        self.lbl_signer.setToolTip(
            f"Tiến trình ký request TikTok (chạy bằng {SIGNER_SCRIPT})")
        self.statusBar().addPermanentWidget(self.lbl_signer)
        b_recheck = QPushButton("Kiểm tra lại")
        b_recheck.setObjectName("ghost")
        b_recheck.clicked.connect(self._check_signer)
        self.statusBar().addPermanentWidget(b_recheck)
        self.b_recheck = b_recheck
        self.pbar = QProgressBar()
        self.pbar.setFixedWidth(220)
        self.pbar.setTextVisible(False)
        self.statusBar().addPermanentWidget(self.pbar)
        self.setCentralWidget(central)

        self._build_account_tab(self.tab_main)
        self._build_task_tab(self.tab_task)
        self._build_detail_tab(self.tab_detail)

    # ------------------------------------------------------------------ #
    # Tab 1 — bảng tài khoản chiếm trọn bề ngang
    # ------------------------------------------------------------------ #
    def _build_account_tab(self, host: QWidget) -> None:
        v = QVBoxLayout(host)
        # Lề mỏng — mỗi px tiết kiệm ở đây đều tới bảng, để 50 dòng vừa
        # khít màn 1080p mà không phải cuộn.
        v.setContentsMargins(6, 5, 6, 5)
        v.setSpacing(5)
        v.addWidget(self._build_toolbar())
        v.addWidget(self._build_table(), 1)

    # ------------------------------------------------------------------ #
    # Tab 3 — thẻ bài viết, thẻ tài khoản, nhật ký
    # ------------------------------------------------------------------ #
    def _build_detail_tab(self, host: QWidget) -> None:
        v = QVBoxLayout(host)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(8)

        self.detail = DetailPanel()
        self.detail.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum
        )
        v.addWidget(self.detail)

        gb_log = self._build_log()
        v.addWidget(gb_log, 1)

    def _build_task_tab(self, host: QWidget) -> None:
        root = QHBoxLayout(host)
        root.setContentsMargins(12, 12, 12, 12)
        root.addWidget(self._build_task())
        root.addStretch(1)

    def _build_toolbar(self) -> QWidget:
        """Thanh công cụ kiểu admin: nhóm lệnh trái, hành động chính phải."""
        w = QFrame()
        w.setProperty("role", "card")
        h = QHBoxLayout(w)
        h.setContentsMargins(8, 6, 8, 6)
        h.setSpacing(6)

        self.btn_load = QPushButton("📂 Nạp cookie")
        self.btn_load.setToolTip("Đọc file cookie, 1 dòng = 1 tài khoản")
        self.btn_all = QPushButton("☑ Tick tất cả")
        self.btn_none = QPushButton("☐ Bỏ tick")
        self.btn_good = QPushButton("✔ Tick còn phiên")
        self.btn_page_on = QPushButton("Trang này +")
        self.btn_page_off = QPushButton("Trang này −")
        self.btn_page_on.setObjectName("ghost")
        self.btn_page_off.setObjectName("ghost")
        for b in (self.btn_load, self.btn_all, self.btn_none, self.btn_good):
            h.addWidget(b)

        sep = QLabel("│")
        sep.setStyleSheet("color:#c8d2dc;")
        h.addWidget(sep)
        h.addWidget(self.btn_page_on)
        h.addWidget(self.btn_page_off)

        h.addStretch(1)

        self.btn_check = QPushButton("Kiểm tra phiên")
        self.btn_log = QPushButton("☰ Nhật ký")
        self.btn_log.setObjectName("ghost")
        self.btn_log.setToolTip("Mở tab Chi tiết (thẻ bài viết, tài khoản, nhật ký)")
        self.btn_run = QPushButton("▶  CHẠY")
        self.btn_stop = QPushButton("■  DỪNG")
        self.btn_run.setObjectName("primary")
        self.btn_stop.setObjectName("danger")
        self.btn_stop.setEnabled(False)
        h.addWidget(self.btn_check)
        h.addWidget(self.btn_log)
        h.addWidget(self.btn_run)
        h.addWidget(self.btn_stop)

        # ô đo tốc độ — đặt giữa nhóm lệnh trái và nút hành động phải
        h.addSpacing(12)
        self.meter = ThroughputMeter()
        self.meter.setFixedWidth(330)
        h.addWidget(self.meter)
        h.addSpacing(12)
        return w

    # ------------------------------------------------------------------ #
    # Thanh phân trang theo số thứ tự
    # ------------------------------------------------------------------ #
    # ------------------------------------------------------------------ #
    # Tìm kiếm + lọc
    # ------------------------------------------------------------------ #
    def _build_search(self) -> QWidget:
        """Thanh tìm kiếm đặt TRÊN bảng — lọc ngay khi gõ, có trễ 250ms."""
        w = QFrame()
        w.setProperty("role", "card")
        h = QHBoxLayout(w)
        h.setContentsMargins(6, 3, 6, 3)
        h.setSpacing(6)

        self.in_search = QLineEdit()
        self.in_search.setFixedHeight(22)
        self.in_search.setPlaceholderText(
            "Tìm theo username, email, proxy, trạng thái, kết quả…   "
            "(nhiều từ = phải khớp tất cả)"
        )
        self.in_search.setClearButtonEnabled(True)
        h.addWidget(self.in_search, 1)

        lbl = QLabel("Lọc:")
        lbl.setProperty("role", "hint")
        h.addWidget(lbl)

        self.cb_filter = QComboBox()
        for key, label in AccountTableModel.FILTER_LABELS.items():
            self.cb_filter.addItem(label, key)
        self.cb_filter.setFixedWidth(160)
        h.addWidget(self.cb_filter)

        self.btn_filter_view = QPushButton("Tick kết quả lọc")
        self.btn_filter_view.setObjectName("ghost")
        self.btn_filter_view.setToolTip(
            "Tick mọi tài khoản đang khớp bộ lọc — nhanh hơn tick từng trang\n"
            "khi danh sách rất lớn."
        )
        h.addWidget(self.btn_filter_view)

        self.btn_search_clear = QPushButton("Xóa lọc")
        self.btn_search_clear.setObjectName("ghost")
        h.addWidget(self.btn_search_clear)
        return w

    def _wire_search(self) -> None:
        # trễ 250ms: gõ nhanh không làm nghẽn bảng với danh sách lớn
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(
            lambda: self.model.set_query(self.in_search.text())
        )
        self.in_search.textChanged.connect(lambda _: self._search_timer.start())
        self.in_search.returnPressed.connect(self._search_timer.stop)
        self.cb_filter.currentIndexChanged.connect(
            lambda: self.model.set_filter(self.cb_filter.currentData())
        )
        self.btn_search_clear.clicked.connect(self._clear_search)
        self.btn_filter_view.clicked.connect(self._tick_filtered)

        # phím tắt: Ctrl+F nhảy vào ô tìm, Esc xóa tìm kiếm
        for seq, fn in (
            ("Ctrl+F", lambda: (self.tabs.setCurrentWidget(self.tab_main),
                                self.in_search.setFocus(),
                                self.in_search.selectAll())),
            ("Esc", self._clear_search),
        ):
            act = QAction(self)
            act.setShortcut(QKeySequence(seq))
            act.triggered.connect(fn)
            self.addAction(act)

    def _clear_search(self) -> None:
        self._search_timer.stop()
        self.in_search.clear()
        self.cb_filter.setCurrentIndex(0)
        self.model.clear_search()

    def _tick_filtered(self) -> None:
        n = self.model.view_count
        self.model.toggle_view(True)
        self._refresh_picker()
        self._log("head", f"Đã tick {n} tài khoản khớp bộ lọc.", "ok")

    # ------------------------------------------------------------------ #
    def _build_pager(self) -> QWidget:
        w = QFrame()
        w.setProperty("role", "card")
        h = QHBoxLayout(w)
        h.setContentsMargins(6, 2, 6, 2)
        h.setSpacing(4)

        self.lbl_range = QLabel("")
        self.lbl_range.setStyleSheet("color:#5f6b7a;")
        h.addWidget(self.lbl_range)
        h.addSpacing(12)

        b = QPushButton("« Đầu")
        b.setObjectName("ghost")
        b.clicked.connect(self.model.first_page)
        h.addWidget(b)
        b = QPushButton("‹ Trước")
        b.setObjectName("ghost")
        b.clicked.connect(self.model.prev_page)
        h.addWidget(b)

        self.lbl_page = QLabel("Trang 1 / 1")
        self.lbl_page.setStyleSheet("font-weight:700;min-width:110px;")
        self.lbl_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h.addWidget(self.lbl_page)

        b = QPushButton("Sau ›")
        b.setObjectName("ghost")
        b.clicked.connect(self.model.next_page)
        h.addWidget(b)
        b = QPushButton("Cuối »")
        b.setObjectName("ghost")
        b.clicked.connect(self.model.last_page)
        h.addWidget(b)

        h.addSpacing(12)
        h.addWidget(QLabel("Số dòng/trang:"))
        self.cb_per_page = QComboBox()
        for n in (25, 50, 100, 250, 500, 1000, 5000, 0):
            self.cb_per_page.addItem("Tất cả" if n == 0 else str(n), n)
        # khôi phục lựa chọn của phiên trước, mặc định 50
        i_pp = self.cb_per_page.findData(self.settings.per_page or 50)
        self.cb_per_page.setCurrentIndex(i_pp if i_pp >= 0 else 1)
        # Phải áp cho model luôn: setCurrentIndex không phát tín hiệu, nếu
        # chỉ set ở đây thì model vẫn giữ 25 dòng/trang mặc định.
        self.model.set_per_page(int(self.cb_per_page.currentData() or 50))
        self.cb_per_page.setFixedWidth(90)
        self.cb_per_page.currentIndexChanged.connect(
            lambda: self._on_per_page_changed()
        )
        h.addWidget(self.cb_per_page)

        # nút bật/tắt dòng gọn — đổi được khi đang xem nhiều tài khoản
        self.btn_compact = QPushButton("Dòng gọn" if self._compact_rows
                                       else "Dòng cao")
        self.btn_compact.setObjectName("ghost")
        self.btn_compact.setToolTip(
            f"Dòng gọn: 1 dòng, {self.delegate.row_h()}px, "
            f"50 dòng = {self.delegate.row_h() * 50}px — vừa khít màn 1080p.\n"
            "Dòng cao: 2 dòng (username + email tách dòng), dễ đọc hơn "
            "nhưng chỉ ~16 dòng / trang."
        )
        self.btn_compact.clicked.connect(self._toggle_compact)
        h.addWidget(self.btn_compact)

        h.addStretch(1)
        self.lbl_pick = QLabel("")
        h.addWidget(self.lbl_pick)
        return w

    def _toggle_compact(self) -> None:
        self._compact_rows = not self._compact_rows
        self.delegate.compact = self._compact_rows
        self.settings.compact_rows = self._compact_rows
        self._apply_row_height()
        self.btn_compact.setText("Dòng gọn" if self._compact_rows else "Dòng cao")
        self.btn_compact.setToolTip(
            f"Dòng gọn: 1 dòng, {self.delegate.row_h()}px, "
            f"50 dòng = {self.delegate.row_h() * 50}px.\n"
            "Dòng cao: 2 dòng (username + email tách dòng), dễ đọc hơn "
            "nhưng chỉ ~16 dòng / trang."
        )
        self.model._refresh_page()
        self._refresh_pager()

    def _on_per_page_changed(self) -> None:
        n = self.cb_per_page.currentData()
        self.model.set_per_page(int(n))
        self.settings.per_page = int(n)
        self._refresh_pager()

    def _refresh_pager(self) -> None:
        m = self.model
        if m.total == 0:
            self.lbl_range.setText("Chưa có tài khoản")
            self.lbl_page.setText("Trang 0 / 0")
            self.lbl_pick.setText("đã tick 0")
            return
        # khi đang lọc, nói rõ đang xem bao nhiêu trong tổng số
        filtering = m.view_count != m.total
        if filtering:
            self.lbl_range.setText(
                f"Đang xem {m.page_first}–{m.page_last} / "
                f"{m.view_count} khớp lọc  (tổng {m.total})"
            )
        else:
            self.lbl_range.setText(
                f"Đang xem {m.page_first}–{m.page_last} / {m.total} tài khoản"
            )
        self.lbl_page.setText(f"Trang {m.page + 1} / {m.page_count}")
        sel = m.selected_count()
        on_page = sum(1 for a in m.page_rows() if a.selected)
        self.lbl_pick.setText(f"đã tick {sel}/{m.total}   ·   trang này {on_page}")
        self.lbl_info.setText(
            f"{m.total} tài khoản · {sel} được tick · "
            f"{sum(1 for a in m.accounts() if a.has_session())} còn phiên"
        )
        # đồng bộ nhãn lọc đang chọn
        if self.cb_filter.currentData() != m.filter:
            self.cb_filter.blockSignals(True)
            i = self.cb_filter.findData(m.filter)
            if i >= 0:
                self.cb_filter.setCurrentIndex(i)
            self.cb_filter.blockSignals(False)

    def _build_table(self) -> QWidget:
        box = QGroupBox("Danh sách tài khoản")
        v = QVBoxLayout(box)
        v.setSpacing(3)
        # Lề mỏng: mỗi px ở đây là 1px thêm cho bảng, mà bảng đang thiếu
        # chỗ để hiện đủ 50 dòng mà không phải cuộn.
        v.setContentsMargins(6, 4, 6, 4)
        v.addWidget(self._build_search())

        self.table = QTableView()
        self.table.setModel(self.model)
        # Chế độ gọn: 1 dòng / ô, cao 14px, vừa 50 dòng / trang.
        self._compact_rows = self.settings.compact_rows
        self.delegate = AccountCellDelegate(self.table, compact=self._compact_rows)
        self.table.setItemDelegate(self.delegate)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.table.verticalHeader().setVisible(False)
        self._apply_row_height()
        self.table.horizontalHeader().setHighlightSections(False)
        # Bấm tiêu đề cột để sắp xếp — TỰ điều khiển, không dùng
        # setSortingEnabled(True) của Qt: bật cái đó thì Qt tự sắp lại mỗi
        # lần dữ liệu đổi, làm hàng nhảy loạn đúng lúc người dùng đang theo dõi.
        self.table.setSortingEnabled(False)
        self.table.horizontalHeader().setSectionsClickable(True)
        self.table.horizontalHeader().setSortIndicatorShown(True)
        self.table.horizontalHeader().sectionClicked.connect(self._on_header_clicked)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        # A và B đặt bề rộng cố định; CỘT CUỐI tự nhận hết phần dư, nên KHÔNG
        # gọi setColumnWidth cho nó — lệnh đó bị `stretchLastSection` bỏ qua và
        # gây hiểu nhầm là đã đặt được. Cột C chứa nhãn sức khoẻ kèm chi tiết
        # nên cần chỗ rộng nhất, đặt C cuối là hợp lý.
        self.table.setColumnWidth(0, 470)
        self.table.setColumnWidth(1, 480)
        # Chuột phải -> menu kiểm tra trạng thái tài khoản
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_table_menu)
        v.addWidget(self.table, 1)
        v.addWidget(self._build_pager())
        return box

    def _apply_row_height(self) -> None:
        """Đặt chiều cao dòng thật sự.

        `minimumSectionSize` mặc định là 24px và nó chặn MỌI giá trị nhỏ
        hơn — kể cả `setDefaultSectionSize(14)`. Muốn dòng 14px thì phải hạ
        minimum xuống trước, nếu không bảng cứ vẽ 24px và 50 dòng không bao
        giờ vừa màn hình. Đây là bẫy rất dễ sót vì không có lỗi nào hiện ra.
        """
        vh = self.table.verticalHeader()
        h = self.delegate.row_h()
        vh.setMinimumSectionSize(h)
        vh.setDefaultSectionSize(h)
        # Các section đã tạo có thể đang giữ kích thước cũ.
        vh.resizeSection(0, h)

    # ------------------------------------------------------------------ #
    # Kiểm tra trạng thái tài khoản (chuột phải)
    # ------------------------------------------------------------------ #
    def _acc_under(self, pos: QPoint):
        """Tài khoản dưới con trỏ chuột, hoặc dòng đang chọn."""
        idx = self.table.indexAt(pos)
        if idx.isValid():
            acc = self.model.row_to_account(idx.row())
            if acc is not None:
                return acc
        return self.current_account()

    def _show_table_menu(self, pos: QPoint) -> None:
        acc = self._acc_under(pos)
        m = QMenu(self)
        running = self.checker.running

        def act(text, slot, enabled=True, tip=""):
            a = QAction(text, self)
            a.setEnabled(enabled)
            if tip:
                a.setToolTip(tip)
            a.triggered.connect(slot)
            m.addAction(a)
            return a

        if acc is not None:
            n_sel = len(self.table.selectionModel().selectedRows())
            act(f"Kiểm tra trạng thái: {acc.username}",
                lambda: self._start_health([acc]),
                not running and not self.controller.busy)
            m.addSeparator()
            act(f"Kiểm tra {n_sel} dòng đang chọn" if n_sel > 1
                else "Kiểm tra dòng đang chọn",
                self._check_selected,
                not running and not self.controller.busy)
            act("Kiểm tra cả trang này", self._check_page,
                not running and not self.controller.busy)
            act("Kiểm tra tất cả đã tick", self._check_ticked,
                not running and not self.controller.busy)
            act("Kiểm tra TOÀN BỘ danh sách", self._check_all,
                not running and not self.controller.busy)
            m.addSeparator()
            # Kiểm tra cục bộ: nhanh, không tốn request, không cần sidecar.
            # Phù hợp dọn file hàng nghìn tài khoản.
            act("Dọn nhanh (chỉ đọc cookie, không gọi mạng)",
                lambda: self._start_health(list(self.accounts), local_only=True),
                not running and not self.controller.busy)
            m.addSeparator()
            act("Bỏ tick những tài khoản đã die", self._untick_dead,
                not self.controller.busy)
            act("Xoá kết quả kiểm tra của trang này", self._clear_health_page,
                not running)
            m.addSeparator()
            act("Sao chép username", lambda: self._copy_acc(acc))
        else:
            a = QAction("Chưa có tài khoản nào", self)
            a.setEnabled(False)
            m.addAction(a)
        m.exec(self.table.viewport().mapToGlobal(pos))

    def _copy_acc(self, acc) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(acc.username)

    # ---- phạm vi kiểm tra ----
    def _check_selected(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            self._start_health([self.current_account()])
            return
        accs = [self.model.row_to_account(r.row()) for r in rows]
        self._start_health([a for a in accs if a is not None])

    def _check_page(self) -> None:
        self._start_health(self.model.page_rows())

    def _check_ticked(self) -> None:
        accs = self.model.selected_accounts()
        if not accs:
            QMessageBox.information(self, "Chưa tick",
                                    "Hãy tick ít nhất 1 tài khoản.")
            return
        self._start_health(accs)

    def _check_all(self) -> None:
        self._start_health(list(self.accounts))

    def _untick_dead(self) -> None:
        dead = [a for a in self.model.accounts()
                if a.health in (HC_DEAD, HC_EXPIRED) and a.selected]
        if not dead:
            QMessageBox.information(
                self, "Không có gì",
                "Chưa tài khoản nào bị đánh dấu die.\n"
                "Chuột phải → 'Kiểm tra trạng thái' trước đã.")
            return
        for a in dead:
            a.selected = False
        self.model._refresh_page()
        self._refresh_pager()
        self._log("status", f"Bỏ tick {len(dead)} tài khoản đã die.", "warn")

    def _clear_health_page(self) -> None:
        for a in self.model.page_rows():
            a.health, a.health_note, a.health_at = HC_UNKNOWN, "", 0.0
        self.model._refresh_page()
        self._refresh_pager()

    def _start_health(self, accounts: list, local_only: bool = False) -> None:
        accounts = [a for a in accounts if a is not None]
        if not accounts:
            return
        if self.checker.running:
            QMessageBox.information(self, "Đang kiểm tra",
                                    "Đang có phiên kiểm tra chạy, xong trước.")
            return
        if self.controller.busy:
            QMessageBox.information(self, "Đang chạy tác vụ",
                                    "Hãy đợi lượt chạy xong rồi kiểm tra.")
            return
        if not local_only and not self._signer_ready:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Question)
            box.setWindowTitle("Chưa có sidecar ký")
            box.setText(
                "Kiểm tra tài khoản CẦN sidecar ký để tạo chữ ký request.\n"
                "Nếu không có, chỉ kiểm tra được cookie cục bộ."
            )
            box.setInformativeText(
                "Kiểm tra cục bộ: đọc cookie trong file, không gọi mạng.\n"
                "  → bắt được tài khoản thiếu phiên / hết hạn ngày,\n"
                "    nhưng KHÔNG biết tài khoản đã bị TikTok thu hồi phiên.\n\n"
                f"Kiểm tra đầy đủ: cần {SIGNER_SCRIPT} đang chạy."
            )
            row = QMessageBox.StandardButton
            box.setStandardButtons(row.Yes | row.No | row.Cancel)
            box.button(row.Yes).setText("Chỉ kiểm tra cục bộ")
            box.button(row.No).setText("Mở hướng dẫn sidecar")
            r = box.exec()
            if r == row.No:
                self.tabs.setCurrentWidget(self.tab_settings)
                return
            if r != row.Yes:
                return
            local_only = True

        use_proxy = self.cb_pool.isChecked() and not local_only
        for a in accounts:
            a.health, a.health_note = HC_CHECKING, ""
        self.model._refresh_page()
        self._refresh_pager()
        self.checker.start(accounts, use_proxy=use_proxy, local_only=local_only)
        how = ("cục bộ, không gọi mạng" if local_only
               else ("qua proxy" if use_proxy else "IP máy"))
        self._log("status",
                  f"Kiểm tra {len(accounts)} tài khoản ({how})…", "head")

    # ---- nhận kết quả ----
    def _apply_health(self, acc_id: str, health: str, note: str, at: float) -> None:
        """Chạy trên GUI thread (queued) — nơi duy nhất chạm vào model."""
        self.model.update_row(acc_id, health=health, health_note=note,
                              health_at=at)

    @Slot(int, int)
    def _on_health_progress(self, done: int, total: int) -> None:
        c = self.model.health_counts()
        self.pbar.setValue(int(done * 100 / max(1, total)))
        self.lbl_stat.setText(
            f"kiểm tra {done}/{total}  ·  "
            f"sống {c.get(HC_ALIVE, 0)}  die {c.get(HC_DEAD, 0)}  "
            f"hết hạn {c.get(HC_EXPIRED, 0)}  "
            f"không rõ {c.get(HC_RISKY, 0)}"
        )

    @Slot()
    def _on_health_done(self) -> None:
        self.pbar.setValue(0)
        c = self.model.health_counts()
        n = self.model.total
        self.lbl_stat.setText(
            f"✔ sống {c.get(HC_ALIVE, 0)} · ✖ die {c.get(HC_DEAD, 0)} · "
            f"⌛ hết hạn {c.get(HC_EXPIRED, 0)} · ? không rõ {c.get(HC_RISKY, 0)}"
            f" · – chưa kiểm {c.get(HC_UNKNOWN, 0)}   (/{n})"
        )
        self._log(
            "status",
            f"Xong kiểm tra: sống {c.get(HC_ALIVE, 0)}, "
            f"die {c.get(HC_DEAD, 0)}, hết hạn {c.get(HC_EXPIRED, 0)}, "
            f"không rõ {c.get(HC_RISKY, 0)}.",
            "ok" if c.get(HC_ALIVE, 0) else "warn",
        )
        if c.get(HC_RISKY, 0):
            self._log(
                "status",
                f"{c[HC_RISKY]} tài khoản bị TikTok chặn request nên không "
                f"kết luận được. KHÔNG phải cookie chết. Thử lại sau, hoặc "
                f"bật proxy để đổi IP.",
                "warn",
            )
        self._refresh_pager()
        self._refresh_summary()

    def _build_task(self) -> QWidget:
        box = QGroupBox("Tác vụ")
        box.setMaximumWidth(520)
        v = QVBoxLayout(box)
        v.setContentsMargins(10, 14, 10, 12)
        v.setSpacing(10)

        # --- nhóm: đích ---
        # Cố tình TỐI GIẢN: chỉ cần cid. Mọi tham số khác (aweme_id, URL,
        # từ khoá, nội dung) đã bị bỏ vì endpoint /api/comment/digg/ chỉ
        # cần `cid` — và thêm tham số lạ làm hỏng chữ ký.
        gb_t = QGroupBox("Đích  (danh sách cid)")
        ft = QFormLayout(gb_t)
        ft.setContentsMargins(10, 6, 10, 10)
        ft.setHorizontalSpacing(8)
        ft.setVerticalSpacing(5)
        ft.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)

        self.cb_mode = QComboBox()
        for key, label in MODE_LABELS.items():
            self.cb_mode.addItem(label, key)
        self.cb_mode.setCurrentIndex(
            self.cb_mode.findData(MODE_LIKE_CID)
        )
        ft.addRow("Chế độ:", self.cb_mode)

        # Ô nhập nhiều cid: mỗi dòng 1 id, hoặc tách bằng dấu phẩy.
        self.in_cid = QTextEdit()
        self.in_cid.setPlaceholderText(
            "7690897576899658504\n7654223771003994898\n7700000000000000001"
        )
        self.in_cid.setFixedHeight(112)
        self.in_cid.setAcceptRichText(False)
        self.in_cid.setToolTip(
            "Mỗi dòng một cid (cũng chấp nhận phân tách bằng dấu phẩy).\n"
            "Hệ thống chạy xong cid này sẽ tự chuyển sang cid kế tiếp."
        )
        ft.addRow("Danh sách cid:", self.in_cid)

        # Hàng thông báo: bao nhiêu cid hợp lệ, đang ở cid nào.
        self.lbl_cid_stat = QLabel("")
        self.lbl_cid_stat.setProperty("role", "hint")
        self.lbl_cid_stat.setWordWrap(True)
        ft.addRow("", self.lbl_cid_stat)
        v.addWidget(gb_t)

        # --- nhóm: tốc độ ---
        gb_s = QGroupBox("Tốc độ  (nhiều luồng = nhanh hơn, cho đến khi chạm trần)")
        fs = QFormLayout(gb_s)
        fs.setContentsMargins(10, 6, 10, 10)
        fs.setHorizontalSpacing(8)
        fs.setVerticalSpacing(5)
        fs.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.sp_threads = QSpinBox()
        self.sp_threads.setRange(1, 200)
        self.sp_threads.setValue(10)
        self.sp_threads.setFixedWidth(92)
        self.sp_threads.setToolTip(
            "Tốc độ gần như tuyến tính theo số luồng.\n"
            "Nên để <= số nhân của CPU × 3."
        )
        fs.addRow("Số luồng:", self.sp_threads)

        # 2 spinbox cạnh nhau, nhãn "→" nằm GIỮA và cố định bề rộng
        delay = QWidget()
        dh = QHBoxLayout(delay)
        dh.setContentsMargins(0, 0, 0, 0)
        dh.setSpacing(4)
        self.sp_dmin = QDoubleSpinBox()
        self.sp_dmax = QDoubleSpinBox()
        for sp in (self.sp_dmin, self.sp_dmax):
            sp.setRange(0, 300)
            sp.setSingleStep(0.5)
            sp.setSuffix(" s")
            sp.setFixedWidth(92)
        self.sp_dmax.setValue(1.0)
        arr = QLabel("→")
        arr.setFixedWidth(14)
        arr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        arr.setProperty("role", "hint")
        dh.addWidget(self.sp_dmin)
        dh.addWidget(arr)
        dh.addWidget(self.sp_dmax)
        dh.addStretch(1)
        fs.addRow("Trễ ngẫu nhiên:", delay)

        self.sp_retry = QSpinBox()
        self.sp_retry.setRange(0, 5)
        self.sp_retry.setFixedWidth(92)
        self.sp_retry.setToolTip("Số lần thử lại khi lỗi hoặc bị chặn IP")
        fs.addRow("Thử lại:", self.sp_retry)

        self.cb_verify = QCheckBox("Đọc lại comment để xác minh số like")
        self.cb_verify.setChecked(True)
        self.cb_verify.setToolTip(
            "Tắt đi sẽ nhanh gấp đôi, nhưng không biết thả tim có thành công không"
        )
        fs.addRow("", self.cb_verify)
        v.addWidget(gb_s)

        # --- nhóm đường ra ---
        gp = QGroupBox("Đường ra  (proxy cho tài khoản chưa được gán ở tab Cài đặt)")
        gpv = QFormLayout(gp)
        gpv.setContentsMargins(10, 6, 10, 10)
        gpv.setHorizontalSpacing(8)
        gpv.setVerticalSpacing(5)
        gpv.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.cb_pool = QCheckBox("Dùng proxy gán ở tab Cài đặt")
        self.cb_pool.setChecked(True)
        self.cb_pool.setToolTip(
            "Tắt để chạy thẳng ra IP máy (nhanh hơn nhưng dễ bị TikTok nhận diện)."
        )
        gpv.addRow("Nguồn:", self.cb_pool)

        self.in_proxy = QLineEdit()
        self.in_proxy.setPlaceholderText(
            "để trống = dùng proxy hệ thống (nếu đã bật ở Cài đặt)"
        )
        gpv.addRow("Dự phòng:", self.in_proxy)

        self.lbl_proxy = QLabel("—")
        self.lbl_proxy.setProperty("role", "hint")
        self.lbl_proxy.setWordWrap(True)
        gpv.addRow("Tình trạng:", self.lbl_proxy)
        v.addWidget(gp)

        # --- nhóm lệnh ---
        gs = QGroupBox("Lệnh")
        gsv = QFormLayout(gs)
        gsv.setContentsMargins(10, 6, 10, 10)
        gsv.setHorizontalSpacing(8)
        gsv.setVerticalSpacing(5)
        gsv.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.in_signer = QLineEdit("http://127.0.0.1:8080")
        gsv.addRow("Sidecar ký:", self.in_signer)

        self.backend_kind = QComboBox()
        self.backend_kind.addItem("http (khuyên dùng — nhanh)", "http")
        self.backend_kind.addItem("mock (chỉ test giao diện)", "mock")
        gsv.addRow("Backend:", self.backend_kind)
        v.addWidget(gs)

        v.addStretch(1)

        h = QHBoxLayout()
        h.addStretch(1)
        self.btn_dry = QPushButton("Thử 1 tài khoản")
        self.btn_dry.setToolTip(
            "Chạy đúng 1 account để kiểm tra tham số trước khi chạy cả đàn"
        )
        self.btn_dry.clicked.connect(lambda: self.start_run(dry_run=True))
        h.addWidget(self.btn_dry)
        v.addLayout(h)
        return box

    def _build_log(self) -> QWidget:
        box = QGroupBox("Nhật ký")
        v = QVBoxLayout(box)
        v.setSpacing(4)
        self.log_edit = QPlainTextEdit()
        self.log_edit.setObjectName("log")
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumBlockCount(8000)
        # nhật ký luôn bám sát đáy vùng nhìn thấy
        self.log_edit.verticalScrollBar().setValue(999999)
        v.addWidget(self.log_edit, 1)
        h = QHBoxLayout()
        b = QPushButton("Xóa log")
        b.setObjectName("ghost")
        b.clicked.connect(self.log_edit.clear)
        h.addWidget(b)
        h.addStretch(1)
        self.lbl_stat = QLabel("")
        self.lbl_stat.setProperty("role", "hint")
        h.addWidget(self.lbl_stat)
        v.addLayout(h)
        return box

    # ------------------------------------------------------------------ #
    def _connect(self) -> None:
        self.btn_load.clicked.connect(self.on_load_file)
        self.btn_all.clicked.connect(lambda: self.model.toggle_all(True))
        self.btn_none.clicked.connect(self.model.select_none)
        self.btn_good.clicked.connect(self.model.select_all_with_session)
        self.btn_page_on.clicked.connect(lambda: self.model.toggle_page(True))
        self.btn_page_off.clicked.connect(lambda: self.model.toggle_page(False))
        self.btn_check.clicked.connect(lambda: self.start_run(mode=MODE_CHECK))
        self.btn_run.clicked.connect(self.start_run)
        self.btn_stop.clicked.connect(self.on_stop)
        self.btn_log.clicked.connect(
            lambda: self.tabs.setCurrentWidget(self.tab_detail)
        )
        self.in_cid.textChanged.connect(self._on_cid_text_changed)
        self.cb_pool.toggled.connect(self._refresh_proxy_label)
        self.tab_settings.log.connect(self._on_settings_log)
        self.tab_settings.proxies_ready.connect(self._on_proxies_ready)

        # bấm vào dòng -> panel chi tiết bên dưới cập nhật theo
        self.table.selectionModel().selectionChanged.connect(self._on_selection)
        self.cb_mode.currentIndexChanged.connect(self._refresh_detail_task)
        self._wire_search()

        # đổi trang -> cập nhật nhãn đếm
        self.model.modelReset.connect(self._on_model_reset)
        self.model.dataChanged.connect(lambda *_: self._refresh_picker())
        self._refresh_pager()

    # ------------------------------------------------------------------ #
    # ------------------------------------------------------------------ #
    # Panel chi tiết
    # ------------------------------------------------------------------ #
    def _on_model_reset(self) -> None:
        """Model vừa nạp lại / đổi trang -> vẽ lại thanh phân trang và thẻ chi tiết."""
        self._refresh_pager()
        if hasattr(self, "detail"):
            self.detail.set_account(self.current_account())
        if hasattr(self, "table"):
            self._update_sort_indicator()

    def _set_detail_tab_text(self) -> None:
        """Ghi số lỗi lên tiêu đề tab Chi tiết để thấy ngay từ tab Quản lý."""
        n = sum(1 for a in self.accounts if a.status == ST_FAIL)
        self.tabs.setTabText(
            2, f"  Chi tiết ({n} lỗi)  " if n else "  Chi tiết  "
        )

    def _on_selection(self, *_) -> None:
        """Đồng bộ thẻ tài khoản với dòng đang chọn trong bảng."""
        acc = self.current_account()
        self.detail.set_account(acc)

    def current_account(self):
        """Tài khoản của dòng đang chọn; nếu chưa chọn thì dòng đầu tiên."""
        rows = self.table.selectionModel().selectedRows()
        if rows:
            acc = self.model.row_to_account(rows[0].row())
            if acc is not None:
                return acc
        page = self.model.page_rows()
        return page[0] if page else None

    def _refresh_detail_task(self, *_):
        """Cập nhật thẻ 'tác vụ đang chọn' khi đổi chế độ / nhập cid."""
        if not hasattr(self, "detail"):
            return
        cfg = self._collect_cfg()
        self.detail.set_task(
            MODE_LABELS.get(cfg.mode, cfg.mode),
            cfg.cid, "", cfg.concurrency,
        )
        self.detail.set_video("", "", cfg.cid)

    # ------------------------------------------------------------------ #
    def _on_settings_log(self, message: str, level: str) -> None:
        self._log("cài đặt", message, level)

    def _on_proxies_ready(self, count: int) -> None:
        """Proxy vừa gán lại -> cập nhật cột A để thấy account nào dùng proxy nào."""
        self.model._refresh_page()
        self._refresh_pager()
        self._refresh_proxy_label()
        self._log(
            "cài đặt",
            f"Đã gán {count} proxy cho {sum(1 for a in self.accounts if a.proxy)} account.",
            "ok",
        )

    def _refresh_picker(self) -> None:
        m = self.model
        if m.total:
            self.lbl_pick.setText(
                f"đã tick {m.selected_count()}/{m.total}   ·   "
                f"trang này {sum(1 for a in m.page_rows() if a.selected)}"
            )
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        """Cập nhật thẻ TỔNG QUAN ở tab Chi tiết."""
        if not hasattr(self, "detail"):
            return
        rows = self.accounts
        self.detail.set_stats({
            "total": len(rows),
            "selected": sum(1 for a in rows if a.selected),
            "has_session": sum(1 for a in rows if a.has_session()),
            "proxied": sum(1 for a in rows if a.proxy),
            "ok": sum(1 for a in rows if a.status == ST_OK),
            "fail": sum(1 for a in rows if a.status == ST_FAIL),
            "last_run": self._last_run or "—",
        })

    def _refresh_proxy_label(self) -> None:
        pool = self.proxy_pool
        n = len(self.accounts)
        n_assigned = sum(1 for a in self.accounts if a.proxy)

        if not self.cb_pool.isChecked():
            self.lbl_proxy.setText("Đang bỏ qua proxy — chạy bằng IP máy.")
            return

        parts = []
        if pool.has_any():
            n_ok = sum(1 for p in pool.items if p.ok)
            n_total = len(pool.items)
            extra = f" · sống {n_ok}/{n_total}" if n_ok else ""
            parts.append(
                f"gán {n_assigned}/{n} account · chế độ {pool.mode}{extra}"
            )
        else:
            parts.append("chưa gán proxy nào")

        if n_assigned < n and self.settings.use_system_proxy:
            sysp = self.settings.system_proxy or "chưa phát hiện"
            parts.append(f"{n - n_assigned} account dùng proxy hệ thống ({sysp})")
        elif n_assigned < n:
            parts.append(f"{n - n_assigned} account dùng IP máy")
        self.lbl_proxy.setText(" · ".join(parts))

    # ------------------------------------------------------------------ #
    # Danh sách cid
    # ------------------------------------------------------------------ #
    @staticmethod
    def parse_cids(text: str) -> tuple[list[str], list[str]]:
        """Tách danh sách cid từ ô nhập.

        Chấp nhận mỗi dòng một id, hoặc nhiều id trên một dòng tách bằng
        dấu phẩy / khoảng trắng. Dòng bắt đầu bằng `#` là ghi chú, bỏ qua.

        Trả về `(danh sách hợp lệ, danh sách bỏ qua)`. Giữ thứ tự người
        dùng gõ và loại trùng — vì thứ tự chính là thứ tự sẽ chạy.
        """
        good: list[str] = []
        bad: list[str] = []
        seen: set[str] = set()
        for raw in (text or "").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            # tách theo dấu phẩy, chấm phẩy, tab, khoảng trắng
            for part in line.replace(";", ",").replace("\t", ",").replace(" ", ",").split(","):
                cid = part.strip()
                if not cid:
                    continue
                if not cid.isdigit() or not (15 <= len(cid) <= 25):
                    bad.append(cid)
                elif cid in seen:
                    continue          # trùng -> bỏ, không báo lỗi
                else:
                    seen.add(cid)
                    good.append(cid)
        return good, bad

    def cids(self) -> list[str]:
        """Danh sách cid hợp lệ, theo đúng thứ tự sẽ chạy."""
        return self.parse_cids(self.in_cid.toPlainText())[0]

    def _on_cid_text_changed(self) -> None:
        good, bad = self.parse_cids(self.in_cid.toPlainText())
        self._refresh_cid_label(good, bad, running=0)
        self._refresh_detail_task()

    def _refresh_cid_label(self, good=None, bad=None, running: int = 0) -> None:
        if good is None:
            good, bad = self.parse_cids(self.in_cid.toPlainText())
        parts = []
        if not good:
            parts.append("Chưa có cid nào — mỗi dòng một id")
        else:
            parts.append(f"{len(good)} cid hợp lệ")
            if running:
                parts.append(f"đang chạy cid {running}/{len(good)}")
        if bad:
            parts.append(f"{len(bad)} dòng bỏ qua (không phải số): "
                         + ", ".join(bad[:3])
                         + ("…" if len(bad) > 3 else ""))
        self.lbl_cid_stat.setText(" · ".join(parts))

    # ------------------------------------------------------------------ #
    @Slot()
    def _check_signer(self) -> None:
        from core.signer import Signer, SignerError

        self._signer_ready = False
        try:
            info = Signer(self.in_signer.text().strip()).health()
        except SignerError as e:
            self._signer_fail(e)
            return
        except Exception as e:
            self._signer_fail(f"{type(e).__name__}: {e}")
            return

        self._signer_ready = bool(info.get("ready"))
        if not self._signer_ready:
            self.lbl_signer.setText("sidecar: ĐANG KHỞI ĐỘNG")
            self.lbl_signer.setProperty("role", "warn")
            self._log(
                "signer",
                "Sidecar đã mở nhưng chưa sẵn sàng (đang tải trình duyệt lần "
                "đầu, có thể mất 30-60 giây). Chờ thêm rồi thử lại.",
                "warn",
            )
        else:
            self.lbl_signer.setText(
                f"sidecar ✓ {info.get('generationCount', 0)} chữ ký"
            )
            self.lbl_signer.setProperty("role", "hint")
            self._log("signer", "Sidecar ký sẵn sàng.", "ok")
        self._style_signer_label()

    def _signer_fail(self, err: str) -> None:
        self.lbl_signer.setText("sidecar: CHƯA CHẠY")
        self.lbl_signer.setProperty("role", "err")
        self._style_signer_label()
        self._log(
            "signer",
            "CHƯA CÓ SIDECAR KÝ → mọi request TikTok sẽ thất bại.\n"
            "  Nguyên nhân : tiến trình Node ký chưa chạy.\n"
            f"  Cách sửa   : chạy {SIGNER_HOW} (1 lần),\n"
            f"               GIỮ cửa sổ terminal đó mở,\n"
            f"               rồi bấm 'Kiểm tra lại' ở thanh dưới.\n"
            f"  Chi tiết   : {self._short_err(err)}",
            "err",
        )

    @staticmethod
    def _short_err(err) -> str:
        """Rút gọn thông báo lỗi dài của requests cho vừa một dòng."""
        txt = str(err)
        for junk in ("Max retries exceeded with url: /health (Caused by ",
                     "HTTPConnectionPool(host='127.0.0.1', port=8080): "):
            txt = txt.replace(junk, "")
        txt = txt.rstrip(")").rstrip(":")
        return txt[:88]

    def _style_signer_label(self) -> None:
        self.lbl_signer.style().unpolish(self.lbl_signer)
        self.lbl_signer.style().polish(self.lbl_signer)

    # ------------------------------------------------------------------ #
    def on_load_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn file cookie", str(Path.cwd()), "Text (*.txt *.csv);;All (*)"
        )
        if not path:
            path = str(Path.cwd() / "cokie.tik.txt")
            if not Path(path).exists():
                QMessageBox.warning(self, "Chưa có file", "Hãy chọn file cookie.")
                return
        try:
            accounts = load_accounts(path)
        except OSError as e:
            QMessageBox.critical(self, "Lỗi đọc file", str(e))
            return

        self._apply_accounts(accounts, f"file {Path(path).name}")
        # Ghi lại để lần sau mở app khỏi phải nạp lại.
        self.settings.last_cookie_file = str(path)
        if self.settings.remember_accounts:
            try:
                p = save_accounts_cache(accounts)
                self._log("head", f"Đã nhớ {len(accounts)} tài khoản: {p}", "head")
            except OSError as e:
                self._log("head", f"Không lưu được danh sách nhớ: {e}", "warn")

    def _apply_accounts(self, accounts: list, source: str) -> None:
        """Đưa danh sách tài khoản vào bảng + gán proxy + tick mặc định."""
        self.accounts = accounts
        self._progress.clear()
        self.pbar.setValue(0)

        # gán proxy cho các account mới nạp
        self.tab_settings.set_accounts(self.accounts)
        if self.settings.proxy_text or self.settings.gw_enabled:
            self.proxy_pool.assign(self.accounts)
        self.model.load(self.accounts)
        # tick mặc định: tài khoản còn phiên
        self.model.select_all_with_session()
        self._refresh_proxy_label()
        self._refresh_pager()
        self._set_detail_tab_text()
        self._log("head", f"Đã nạp {len(self.accounts)} tài khoản từ {source}", "head")
        n_no = 0
        for a in self.accounts:
            if not a.has_session():
                n_no += 1
        if n_no:
            # 1000 tài khoản hỏng phiên thì log sẽ ngập, nên gom thành 1 dòng
            self._log(
                "head",
                f"Cảnh báo: {n_no}/{len(self.accounts)} tài khoản thiếu "
                f"sessionid_ss — xem thẻ Chi tiết để biết tài khoản nào.",
                "warn",
            )

    # ------------------------------------------------------------------ #
    def _collect_cfg(self, cid: str = "") -> RunConfig:
        """ Gom tham số chạy. `cid` ghi đè để chạy tiếp cid kế tiếp. """
        return RunConfig(
            mode=self.cb_mode.currentData(),
            cid=cid or (self.cids()[0] if self.cids() else ""),
            aweme_id="",                # cố tình bỏ — xem _build_task
            video="",
            comment="",
            search_keyword="",
            target_text="",
            signer_url=self.in_signer.text().strip(),
            proxy=self._fallback_proxy(),
            use_proxy_pool=self.cb_pool.isChecked(),
            rotate_on_block=self.settings.rotate_on_block,
            region=self.settings.region,
            timezone=self.settings.timezone,
            language=self.settings.language,
            concurrency=self.sp_threads.value(),
            delay_min=self.sp_dmin.value(),
            delay_max=self.sp_dmax.value(),
            retries=self.sp_retry.value(),
            verify=self.cb_verify.isChecked(),
        )

    def _fallback_proxy(self) -> str:
        """Proxy dùng cho account CHƯA được gán proxy riêng.

        Thứ tự ưu tiên: ô nhập tay trong tab Tác vụ → proxy hệ thống (nếu bật).
        """
        manual = self.in_proxy.text().strip()
        if manual:
            return manual
        if self.settings.use_system_proxy:
            return self.settings.system_proxy.strip()
        return ""

    def _sync_from_settings_tab(self) -> None:
        """Lấy cấu hình chung từ tab Cài đặt (số luồng, trễ, retries, proxy)."""
        s = self.settings
        self.sp_threads.setValue(s.concurrency)
        self.sp_retry.setValue(s.retries)
        self.sp_dmin.setValue(s.delay_min)
        self.sp_dmax.setValue(s.delay_max)
        self.cb_verify.setChecked(s.verify)
        self.in_signer.setText(s.signer_url)
        self.controller._rotate = s.rotate_on_block

    def start_run(self, mode: str | None = None, dry_run: bool = False) -> None:
        if self.controller.busy:
            return
        if mode:
            i = self.cb_mode.findData(mode)
            if i >= 0:
                self.cb_mode.setCurrentIndex(i)

        self._sync_from_settings_tab()
        # Gom danh sách cid TRƯỚC, rồi chạy lần lượt từng cid.
        lst = self.cids()
        good, bad = self.parse_cids(self.in_cid.toPlainText())
        if self.cb_mode.currentData() == MODE_LIKE_CID and not good:
            QMessageBox.warning(
                self, "Thiếu cid",
                "Hãy nhập ít nhất một cid vào ô 'Danh sách cid'.\n"
                "Mỗi dòng một id, ví dụ:\n"
                "7690897576899658504\n7654223771003994898",
            )
            return
        if bad:
            self._log("cid", f"Bỏ qua {len(bad)} dòng không phải số: "
                             f"{', '.join(bad[:5])}", "warn")

        # luôn chạy MỌI tài khoản đã tick, không giới hạn theo bộ lọc đang xem
        accounts = self.model.selected_accounts()
        if dry_run:
            accounts = accounts[:1]
        if not accounts:
            QMessageBox.information(self, "Chưa chọn", "Hãy tick ít nhất 1 tài khoản.")
            return
        # Thử 1 tài khoản thì chỉ chạy cid đầu, không chạy cả danh sách.
        self._cid_queue = lst[:1] if dry_run else list(lst)
        self._cid_pos = -1
        self._dry_run = dry_run

        # Chặn sớm khi sidecar chưa chạy — nếu không, MỌI tài khoản sẽ đỏ
        # và người dùng tưởng cookie hỏng.
        if self.backend_kind.currentData() == "http" and not self._signer_ready:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Critical)
            box.setWindowTitle("Chưa có sidecar ký")
            box.setText(
                "Chưa kết nối được sidecar ký nên mọi request TikTok đều thất bại.\n\n"
                "Bấm CHẠY bây giờ sẽ khiến tất cả tài khoản báo lỗi."
            )
            box.setInformativeText(
                "Cách sửa:\n"
                f"  1. Mở terminal trong thư mục dự án, chạy:\n"
                f"       {SIGNER_HOW}\n"
                "     Nó sẽ tải tiktok-signature + Chromium, cần Internet.\n"
                "  2. GIỮ cửa sổ terminal đó mở — đó là tiến trình ký.\n"
                "  3. Quay lại đây, bấm nút 'Kiểm tra lại' ở thanh dưới.\n\n"
                "Muốn chỉ xem thao tác chạy thì chọn Backend = mock."
            )
            # QMessageBox dùng StandardButton CỦA NÓ, không phải của
            # QDialogButtonBox — trộn hai enum này sẽ vỡ ngay khi bấm CHẠY
            # mà sidecar chưa chạy.
            row = QMessageBox.StandardButton
            box.setStandardButtons(row.Ok)
            box.addButton(row.Cancel)
            box.button(row.Ok).setText("Mở hướng dẫn")
            if box.exec() == row.Ok:
                self.tabs.setCurrentWidget(self.tab_settings)
            return

        self._run_accounts = accounts
        self._start_next_cid()

    def _start_next_cid(self) -> None:
        """Chạy cid tiếp theo trong hàng đợi. Không làm gì nếu đã hết."""
        if self._cid_pos + 1 >= len(self._cid_queue):
            self._cid_queue = []
            return

        self._cid_pos += 1
        cid = self._cid_queue[self._cid_pos]
        accounts = self._run_accounts
        cfg = self._collect_cfg(cid)
        total = len(self._cid_queue)

        self.model.reset_status()
        self._progress.clear()
        self.pbar.setValue(0)
        self._set_running(True)
        self._refresh_cid_label(running=self._cid_pos + 1)
        self._refresh_detail_task()

        n = len(accounts)
        n_own = sum(1 for a in accounts if a.proxy) if cfg.use_proxy_pool else 0
        head = f"▶ cid {self._cid_pos + 1}/{total}: {cid}"
        if total > 1:
            head += f"   [{self._cid_pos + 2} cid chờ]"
        self._log("head", f"{head} · {n} account · {cfg.concurrency} luồng", "head")
        if not cfg.use_proxy_pool:
            self._log("head", "   đường ra: tất cả qua IP máy (tắt proxy)", "head")
        elif n_own == n:
            self._log("head", "   đường ra: tất cả qua proxy được gán", "head")
        else:
            rest = n - n_own
            via = (f"proxy hệ thống ({cfg.proxy})" if cfg.proxy else "IP máy")
            self._log(
                "head",
                f"   đường ra: {n_own} qua proxy gán, {rest} qua {via}",
                "head",
            )
        self.controller.start(accounts, cfg)

    def on_stop(self) -> None:
        if self.controller.busy:
            left = len(self._cid_queue) - self._cid_pos - 1
            tail = f" — bỏ {left} cid còn lại" if left > 0 else ""
            self._log("warn", f"Đang dừng — các luồng còn tối đa vài giây{tail}…",
                      "warn")
            self.controller.stop()
            self.btn_stop.setEnabled(False)
            # Dừng tay = bỏ hàng đợi. Không xoá ở đây vì _on_finished còn
            # phải chạy; nó sẽ thấy cờ này và không sang cid kế tiếp.
            self._queue_paused = True

    def _set_running(self, running: bool) -> None:
        for b in (self.btn_run, self.btn_check, self.btn_load,
                  self.btn_all, self.btn_none, self.btn_dry,
                  self.btn_good, self.btn_page_on, self.btn_page_off):
            b.setEnabled(not running)
        self.btn_stop.setEnabled(running)

    # ------------------------------------------------------------------ #
    # Slots nhận signal từ worker — luôn chạy trên GUI thread
    # ------------------------------------------------------------------ #
    @Slot(int)
    def _on_started(self, count: int) -> None:
        self.lbl_stat.setText(f"0/{count}")
        self.pbar.setValue(0)
        self.meter.start(count, self.sp_threads.value())

    @Slot(int)
    def _on_header_clicked(self, col: int) -> None:
        """Bấm tiêu đề: cùng cột thì đảo chiều, khác cột thì tăng dần."""
        cur, desc = self.model.sort_col, self.model.sort_desc
        self.model.set_sort(col, not desc if col == cur else False)
        self._update_sort_indicator()
        self._refresh_pager()

    def _update_sort_indicator(self) -> None:
        order = (Qt.SortOrder.DescendingOrder if self.model.sort_desc
                 else Qt.SortOrder.AscendingOrder)
        self.table.horizontalHeader().setSortIndicator(
            self.model.sort_col, order
        )

    # ------------------------------------------------------------------ #
    # Đồng hồ tốc độ
    # ------------------------------------------------------------------ #
    @Slot(str)
    def _on_task_done(self, acc_id: str) -> None:
        """Một task đã trả về. Dùng cho thanh tiến độ và đồng hồ."""
        acc = self.model.by_id(acc_id)
        ok = bool(acc) and acc.status in (ST_OK, ST_DONE)
        self.meter.add_done(ok)
        # thanh tiến độ = số đã xong / tổng — chạy đều, không nhảy vỡ
        total = self.meter._total or 1
        self.pbar.setValue(int(self.meter._done * 100 / total))
        self.lbl_stat.setText(f"{self.meter._done}/{self.meter._total}")

    @Slot()
    def _on_meter_tick(self) -> None:
        self.meter.tick()
        self._signer_ticks += 1
        if self._signer_ticks % 5 == 0:
            self._poll_signer_health()

    def _poll_signer_health(self) -> None:
        """Hỏi sidecar ở thread nền — hàng đợi cho biết nút thắt ở đâu."""
        from core.gui_bridge import call_on_gui
        from core.signer import Signer

        def work() -> None:
            try:
                info = Signer(self.in_signer.text().strip()).health(timeout=2.0)
            except Exception:
                call_on_gui(lambda: self.meter.set_signer(0, 0))
                return
            q = int(info.get("queueLength") or 0)
            s = int(info.get("generationCount") or 0)
            call_on_gui(lambda: self.meter.set_signer(q, s))

        threading.Thread(target=work, daemon=True).start()

    @Slot(str, str, str)
    def _on_status(self, acc_id: str, status: str, note: str) -> None:
        self.model.update_row(acc_id, status=status, note=note)
        # thẻ chi tiết đang hiển thị tài khoản này -> vẽ lại
        cur = self.current_account()
        if cur is not None and cur.id == acc_id:
            self.detail.set_account(cur)
        if status in (ST_OK, ST_DONE):
            self._log(acc_id, f"✔ {note or status}", "ok")
        elif status == ST_FAIL:
            self._log(acc_id, f"✖ {note}", "err")
            self._set_detail_tab_text()
        elif status == ST_SKIP:
            self._log(acc_id, f"– {note or status}", "warn")

    @Slot(str, int)
    def _on_progress(self, acc_id: str, pct: int) -> None:
        self._progress[acc_id] = pct
        total = len(self._progress) or 1
        self.pbar.setValue(sum(self._progress.values()) // total)

    @Slot(str, str)
    def _on_log(self, acc_id: str, message: str) -> None:
        self._log(acc_id, message, "info")

    @Slot()
    def _on_finished(self) -> None:
        rows = self.model.accounts()
        ok = sum(1 for a in rows if a.status == ST_OK)
        done = sum(1 for a in rows if a.status == ST_DONE)
        err = sum(1 for a in rows if a.status == ST_FAIL)
        skip = sum(1 for a in rows if a.status == ST_SKIP)
        self.pbar.setValue(100)
        self.meter.stop()
        self.lbl_stat.setText(f"✔ {ok} · ● {done} · ✖ {err} · – {skip}")
        self._last_run = (
            datetime.datetime.now().strftime("%H:%M:%S")
            + f"  ({self.meter._total} acc, {self.meter._threads} luồng, "
            + f"{self.meter._avg:.1f} acc/s)"
        )
        cid = self._cid_queue[self._cid_pos] if self._cid_queue else ""
        pos = self._cid_pos + 1
        total = len(self._cid_queue)
        self._log(
            "head",
            f"■ cid {pos}/{total} ({cid}) xong — thành công {ok}, hợp lệ {done}, "
            f"lỗi {err}, bỏ qua {skip}",
            "head",
        )
        self._refresh_pager()
        self._set_detail_tab_text()
        self._refresh_summary()

        # --- sang cid kế tiếp, trừ khi người dùng bấm DỪNG ---
        if self._queue_paused:
            left = total - pos
            self._log(
                "warn",
                f"Đã dừng theo yêu cầu. Còn {left} cid chưa chạy."
                if left else "Đã dừng theo yêu cầu.",
                "warn",
            )
            self._cid_queue = []
            self._queue_paused = False
            self._refresh_cid_label()
            self._set_running(False)
            return

        if pos < total:
            self._log("head", f"── chuyển sang cid tiếp theo ({pos + 1}/{total}) "
                              f"──", "head")
            self._start_next_cid()
            return

        # hết hàng đợi
        self._cid_queue = []
        self._log("head", f"■ ĐÃ XONG toàn bộ {total} cid.", "head")
        self._refresh_cid_label()
        self._set_running(False)

    # ------------------------------------------------------------------ #
    def _log(self, tag: str, message: str, level: str = "info") -> None:
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        color = LEVEL_COLOR.get(level, LEVEL_COLOR["info"])
        self.log_edit.appendHtml(
            f'<span style="color:#9aa6b4">{ts}</span> '
            f'<span style="color:#1a6fc4">[{html.escape(str(tag))[:22]}]</span> '
            f'<span style="color:{color}">{html.escape(str(message))}</span>'
        )
        self.log_edit.moveCursor(QTextCursor.MoveOperation.End)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.controller.busy:
            if QMessageBox.question(
                self, "Đang chạy", "Còn task đang chạy. Thoát hẳn?"
            ) != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.controller.stop()
            self.controller.wait(4000)

        # lưu cấu hình (kể cả mật khẩu proxy — file này tương đương bí mật)
        self.tab_settings._sync_to_settings()
        self.settings.last_cookie_file = str(
            self.settings.last_cookie_file or Path.cwd() / "cokie.tik.txt"
        )
        self.settings.cid_list = self.in_cid.toPlainText()
        self.settings.per_page = int(self.cb_per_page.currentData() or 50)
        self.settings.compact_rows = self._compact_rows
        try:
            p = self.settings.save()
            self._log("cài đặt", f"Đã lưu cấu hình: {p}", "ok")
        except OSError as e:
            self._log("cài đặt", f"Không lưu được cấu hình: {e}", "err")
        event.accept()

"""Cửa sổ chính: bảng 2 cột A/B, form CID, log, điều khiển chạy/dừng."""

from __future__ import annotations

import datetime
import html
import threading
from pathlib import Path

# QProcess nằm ở QtCore, KHÔNG phải QtWidgets — import sai sẽ vỡ ngay lúc
# khởi động app với ImportError.
from PySide6.QtCore import QPoint, QProcess, Qt, QTimer, Slot
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
    QRadioButton,
    QScrollArea,
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
from core.inflight import HTTP, REST, SIGN, TASK, tracker
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
    format_success_line,
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
from .account_picker import AccountPickerDialog
from .meter import ThroughputMeter
from .runlog import RunLogModel, ST_DONE as LG_DONE, ST_FAIL as LG_FAIL, ST_OK as LG_OK, ST_RUN as LG_RUN
from .settings_tab import SettingsTab

# Tên script cài/chạy sidecar, đổi theo hệ điều hành. Trên macOS/Linux không
# chạy được file .bat, nên thông báo hướng dẫn phải trỏ đúng script — VÀ
# đúng cả CÁCH mở: Windows bấm đúp được, macOS thì không (phải gõ trong
# Terminal). Bảo MacBook "mở terminal" là hướng dẫn Windows lọt sang.
import sys as _sys

IS_MAC = _sys.platform == "darwin"
IS_WINDOWS = _sys.platform == "win32"
SIGNER_SCRIPT = "signer.sh" if IS_MAC else "signer.bat"
SIGNER_HOW = (f"chmod +x {SIGNER_SCRIPT} && ./{SIGNER_SCRIPT}"
              if IS_MAC else f"{SIGNER_SCRIPT}")

if IS_MAC:
    SIGNER_STEP_RUN = f"chạy lệnh này trong Terminal: {SIGNER_HOW}"
    SIGNER_STEPS = (
        "  1. Mở Terminal, cd vào thư mục dự án, chạy:\n"
        f"       {SIGNER_HOW}\n"
        "     Nó sẽ tải tiktok-signature + Chromium, cần Internet.\n"
        "  2. GIỮ cửa sổ terminal đó mở — đó là tiến trình ký.\n"
    )
else:
    SIGNER_STEP_RUN = f"BẤM ĐÚP file {SIGNER_SCRIPT} trong thư mục dự án"
    SIGNER_STEPS = (
        f"  1. BẤM ĐÚP file {SIGNER_SCRIPT} trong thư mục dự án.\n"
        "     Cần Internet: nó sẽ tải tiktok-signature + Chromium.\n"
        "     Lần đầu mất vài phút, các lần sau sẽ nhanh hơn nhiều.\n"
        "  2. GIỮ cửa sổ đen mở — đó là tiến trình ký.\n"
    )

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
        # per_page = 0 = KHÔNG phân trang, hiện toàn bộ danh sách.
        # Trước đây chia 50 dòng 1 trang; với vài nghìn tài khoản thì
        # phải bấm « Trước / Sau » chỉ để xem hết — thừa thao tác.
        self.model.set_per_page(0)
        # dùng cho chiều cao dòng của bảng log
        self._compact_rows = self.settings.compact_rows
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
        # tiến trình sidecar do app tự bật
        self._signer_proc: QProcess | None = None
        self._signer_poll: QTimer | None = None
        self._signer_wait: int = 0
        self._signer_tail: list[str] = []   # vài dòng log gần nhất của sidecar

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

        # 4 lần/giây: đồng hồ "đang chờ" + thanh tiến độ liên mạch.
        # Tốc độ này đủ mượt để không bao giờ có cảm giác "đứng hẳn",
        # nhưng cũng đủ thưa để không tốn CPU khi chỉ cập nhật chuỗi y hệt.
        self._wait_text = ""
        self._wait_timer = QTimer(self)
        self._wait_timer.setInterval(250)
        self._wait_timer.timeout.connect(self._tick_wait)
        self._wait_timer.start()

        # Khôi phục danh sách cid của phiên làm việc trước
        if self.settings.cid_list:
            self.in_cid.setPlainText(self.settings.cid_list)
        QTimer.singleShot(200, self._check_signer)
        QTimer.singleShot(400, self._after_start)

    # ------------------------------------------------------------------ #
    def _after_start(self) -> None:
        # Khôi phục tham số tab Tác vụ TRƯỚC, để _restore_accounts và các
        # hàm sau thấy đúng giá trị người dùng đã chọn.
        self._restore_task_params()
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
        # Đã bỏ tab "Tác vụ" và "Chi tiết": cấu hình nằm sẵn bên phải
        # màn chính, nhật ký thành dải nhỏ dưới bảng log. Còn lại đúng
        # 2 tab: màn chính + cài đặt.
        # Tab 2: cài đặt
        self.tab_settings = SettingsTab(self.settings, self.proxy_pool)
        self.tabs.addTab(self.tab_settings, "  Cài đặt  ")
        root.addWidget(self.tabs, 1)

        self.lbl_info = QLabel("Chưa có dữ liệu")
        self.statusBar().addWidget(self.lbl_info, 1)
        # Đồng hồ "đang chờ" — cập nhật 4 lần/giây, luôn nói cho biết app
        # đang chờ cái gì. Không có nó thì mỗi lần luồng kẹt, log im lặng
        # và người dùng tưởng chương trình đã chết.
        self.lbl_wait = QLabel("")
        self.lbl_wait.setProperty("role", "hint")
        self.lbl_wait.setToolTip(
            "Đồng hồ 'đang chờ' (cập nhật 4 lần/giây):\n"
            "• N việc: số tài khoản đang được xử lý\n"
            "• chờ ký N: request đang đợi sidecar ký — nút thắt tầng 3\n"
            "• chờ TikTok N: request đang đợi TikTok trả lời — nút thắt mạng/IP\n"
            "• nghỉ N: luồng đang chờ thử lại hoặc trễ ngẫu nhiên\n"
            "• lâu nhất Ns: request cũ nhất đã chờ N giây\n"
            "  (≥5s là cam, ≥15s là đỏ — sắp chạm timeout 20-25s)"
        )
        self.lbl_wait.setVisible(False)
        self.statusBar().addPermanentWidget(self.lbl_wait)
        self.lbl_signer = QLabel("sidecar: ?")
        self.lbl_signer.setToolTip(
            f"Tiến trình ký request TikTok (chạy bằng {SIGNER_SCRIPT})")
        self.statusBar().addPermanentWidget(self.lbl_signer)
        # Bật sidecar ngay trong app — không cần tự mở terminal
        self.btn_signer = QPushButton("Bật sidecar")
        self.btn_signer.setObjectName("ghost")
        self.btn_signer.setToolTip(
            "Mở tiến trình Node ký TikTok.\n"
            "Tương đương chạy signer.bat / signer.sh ở cửa sổ khác,\n"
            "nhưng bấm ở đây thì app tự quản lý."
        )
        self.btn_signer.clicked.connect(self._start_signer)
        self.statusBar().addPermanentWidget(self.btn_signer)

        b_recheck = QPushButton("Kiểm tra lại")
        b_recheck.setObjectName("ghost")
        b_recheck.setToolTip(
            "Hỏi sidecar xem đã sẵn sàng chưa.\n"
            "Bấm sau khi bật sidecar, hoặc sau khi vừa cài xong."
        )
        b_recheck.clicked.connect(self._check_signer)
        self.statusBar().addPermanentWidget(b_recheck)
        self.b_recheck = b_recheck
        self.pbar = QProgressBar()
        self.pbar.setFixedWidth(220)
        self.pbar.setTextVisible(False)
        self.statusBar().addPermanentWidget(self.pbar)
        self.setCentralWidget(central)

        self._build_main_tab(self.tab_main)

    # ------------------------------------------------------------------ #
    # Tab 1 — bảng tài khoản chiếm trọn bề ngang
    # ------------------------------------------------------------------ #
    def _build_main_tab(self, host: QWidget) -> None:
        """Màn chính: LOG chạy bên trái, CẤU HÌNH bên phải.

        Không còn bảng danh sách tài khoản — nó là hàng trăm tới hàng
        nghìn dòng, ép người dùng cuộc mãi mới thấy dòng vừa chạy xong.
        Thứ cần nhìn lúc chạy là "tài khoản nào xong với cid nào", nên
        bảng log là thứ chính; cấu hình đứng bên cạnh để không phải
        chuyển qua lại giữa các tab.

        Tài khoản vẫn nạp từ file cookie như cũ, và vẫn chọn được số
        lượng / thứ tự / ngẫu nhiên ở nhóm "Số lượng tài khoản chạy".
        """
        h = QHBoxLayout(host)
        h.setContentsMargins(6, 5, 6, 5)
        h.setSpacing(8)

        # --- trái: log chạy ---
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(4)
        lv.addWidget(self._build_toolbar())
        lv.addWidget(self._build_pager())
        lv.addWidget(self._build_runlog(), 1)
        lv.addWidget(self._build_log())
        h.addWidget(left, 1)

        # --- phải: cấu hình tác vụ ---
        right = QScrollArea()
        right.setWidgetResizable(True)
        right.setFrameShape(QFrame.Shape.NoFrame)
        right.setMinimumWidth(330)
        right.setMaximumWidth(430)
        holder = QWidget()
        hv = QVBoxLayout(holder)
        hv.setContentsMargins(0, 0, 0, 0)
        hv.addWidget(self._build_task())
        hv.addStretch(1)
        right.setWidget(holder)
        h.addWidget(right)

    # ------------------------------------------------------------------ #
    # Tab 3 — thẻ bài viết, thẻ tài khoản, nhật ký
    # ------------------------------------------------------------------ #
    def _build_runlog(self) -> QWidget:
        """Bảng log chạy + thanh thống kê + ô danh sách cid đã xong."""
        box = QGroupBox("Nhật ký chạy")
        v = QVBoxLayout(box)
        v.setSpacing(4)
        v.setContentsMargins(6, 4, 6, 6)

        # --- thanh thống kê: xong / thành công / lỗi ---
        bar = QFrame()
        bar.setProperty("role", "card")
        hb = QHBoxLayout(bar)
        hb.setContentsMargins(8, 2, 8, 2)
        hb.setSpacing(10)
        self.lbl_run_stat = QLabel("Chưa chạy gì.")
        self.lbl_run_stat.setStyleSheet("font-weight:700;color:#1e9e5a;")
        hb.addWidget(self.lbl_run_stat)
        hb.addStretch(1)
        b_clear = QPushButton("Xoá log")
        b_clear.setObjectName("ghost")
        b_clear.setToolTip("Xoá toàn bộ bảng log và danh sách cid đã xong.")
        b_clear.clicked.connect(self._clear_runlog)
        hb.addWidget(b_clear)
        v.addWidget(bar)

        # --- bảng ---
        self.runlog = RunLogModel(self)
        self.tbl_run = QTableView()
        self.tbl_run.setModel(self.runlog)
        self.tbl_run.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_run.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_run.verticalHeader().setVisible(False)
        self.tbl_run.horizontalHeader().setHighlightSections(False)
        self.tbl_run.horizontalHeader().setStretchLastSection(True)
        # Chuột phải trên bảng log -> menu chạy / quản lý danh sách
        self.tbl_run.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.tbl_run.customContextMenuRequested.connect(
            self._show_table_menu)
        self.tbl_run.setColumnWidth(0, 190)   # STT + tài khoản
        self.tbl_run.setColumnWidth(1, 175)   # cid
        self.tbl_run.setColumnWidth(2, 300)   # log
        vh = self.tbl_run.verticalHeader()
        vh.setMinimumSectionSize(18)
        vh.setDefaultSectionSize(18)
        v.addWidget(self.tbl_run, 1)

        # --- danh sách cid đã hoàn thành ---
        gb_done = QGroupBox("CID đã hoàn thành")
        gd = QVBoxLayout(gb_done)
        gd.setContentsMargins(6, 4, 6, 6)
        gd.setSpacing(3)
        self.lbl_done_cid = QLabel("Chưa có cid nào hoàn thành.")
        self.lbl_done_cid.setProperty("role", "hint")
        self.lbl_done_cid.setWordWrap(True)
        gd.addWidget(self.lbl_done_cid)
        self.in_done_cid = QTextEdit()
        self.in_done_cid.setReadOnly(True)
        self.in_done_cid.setPlaceholderText(
            "Các cid đã chạy xong sẽ hiện ở đây,\nmỗi dòng một cid.")
        self.in_done_cid.setFixedHeight(84)
        self.in_done_cid.setAcceptRichText(False)
        gd.addWidget(self.in_done_cid)
        hcb = QHBoxLayout()
        hcb.setSpacing(4)
        b_copy = QPushButton("Sao chép tất cả cid đã xong")
        b_copy.setObjectName("ghost")
        b_copy.clicked.connect(self._copy_done_cids)
        hcb.addWidget(b_copy)
        b_n = QPushButton("Bỏ trống")
        b_n.setObjectName("ghost")
        b_n.setToolTip("Xoá danh sách cid đã xong, giữ nguyên bảng log.")
        b_n.clicked.connect(self._clear_done_cids)
        hcb.addWidget(b_n)
        hcb.addStretch(1)
        gd.addLayout(hcb)
        v.addWidget(gb_done)
        return box

    def _clear_runlog(self) -> None:
        self.runlog.reset()
        self.in_done_cid.clear()
        self.lbl_done_cid.setText("Chưa có cid nào hoàn thành.")
        self._refresh_run_stat()
        self.pbar.setValue(0)

    def _clear_done_cids(self) -> None:
        self.runlog.clear_done()
        self.in_done_cid.clear()
        self.lbl_done_cid.setText("Chưa có cid nào hoàn thành.")

    def _copy_done_cids(self) -> None:
        from PySide6.QtWidgets import QApplication
        cids = list(self.runlog.done_cids)
        if not cids:
            QMessageBox.information(
                self, "Chưa có cid nào xong",
                "Chưa có cid nào hoàn thành để sao chép.")
            return
        QApplication.clipboard().setText("\n".join(cids))
        self._log("cid", f"Đã sao chép {len(cids)} cid hoàn thành.", "ok")

    def _refresh_run_stat(self) -> None:
        """Cập nhật thanh thống kê + danh sách cid đã xong."""
        m = self.runlog
        self.lbl_run_stat.setText(m.stats_text())
        cids = m.done_cids
        if cids:
            self.lbl_done_cid.setText(
                f"{len(cids)} cid đã xong. Bấm 'Sao chép' để lấy danh sách.")
            if self.in_done_cid.toPlainText().split("\n") != cids:
                self.in_done_cid.setPlainText("\n".join(cids))
        else:
            self.lbl_done_cid.setText("Chưa có cid nào hoàn thành.")
            if self.in_done_cid.toPlainText():
                self.in_done_cid.clear()

    def _open_account_picker(self) -> None:
        """Mở hộp thoại xem / tick tay danh sách tài khoản."""
        if not self.accounts:
            QMessageBox.information(
                self, "Chưa nạp cookie",
                "Hãy bấm '📂 Nạp cookie' trước để có danh sách tài khoản.")
            return
        dlg = AccountPickerDialog(self.model, self)
        if dlg.exec():
            self._refresh_picker()
            self._refresh_pick_stat()
            self._log("head", f"Đã áp dụng chọn: "
                              f"{self.model.selected_count()} tài khoản.", "head")

    def _build_toolbar(self) -> QWidget:
        """Thanh công cụ kiểu admin: nhóm lệnh trái, hành động chính phải."""
        w = QFrame()
        w.setProperty("role", "card")
        h = QHBoxLayout(w)
        h.setContentsMargins(8, 6, 8, 6)
        h.setSpacing(6)

        self.btn_load = QPushButton("📂 Nạp cookie")
        self.btn_load.setToolTip("Đọc file cookie, 1 dòng = 1 tài khoản")
        h.addWidget(self.btn_load)

        # Không còn bảng danh sách tài khoản, nên không có ô tick để
        # bấm. Thay bằng nút xem trước danh sách — vẫn cần để biết đã
        # nạp được bao nhiêu, có bao nhiêu tài khoản còn phiên đăng nhập.
        self.btn_list = QPushButton("☰ Danh sách tài khoản")
        self.btn_list.setObjectName("ghost")
        self.btn_list.setToolTip(
            "Xem / tick tay danh sách tài khoản.\n"
            "Không bắt buộc — mặc định cứ chạy hết, dùng ô 'Số lượng tài "
            "khoản chạy' ở bên phải để giới hạn.")
        self.btn_list.clicked.connect(self._open_account_picker)
        h.addWidget(self.btn_list)

        h.addStretch(1)

        self.btn_check = QPushButton("Kiểm tra phiên")
        self.btn_run = QPushButton("▶  CHẠY")
        self.btn_stop = QPushButton("■  DỪNG")
        self.btn_run.setObjectName("primary")
        self.btn_stop.setObjectName("danger")
        self.btn_stop.setEnabled(False)
        h.addWidget(self.btn_check)
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
    def _tick_filtered(self) -> None:
        n = self.model.view_count
        self.model.toggle_view(True)
        self._refresh_picker()
        self._log("head", f"Đã tick {n} tài khoản khớp bộ lọc.", "ok")

    # ------------------------------------------------------------------ #
    def _build_pager(self) -> QWidget:
        """Thanh đếm tài khoản đã nạp (bảng tài khoản đã bỏ khỏi màn chính)."""
        w = QFrame()
        w.setProperty("role", "card")
        h = QHBoxLayout(w)
        h.setContentsMargins(8, 3, 8, 3)
        h.setSpacing(8)
        self.lbl_scanned = QLabel("Chưa quét")
        self.lbl_scanned.setStyleSheet("font-weight:700;color:#7ee787;")
        h.addWidget(self.lbl_scanned)
        self.lbl_range = QLabel("")
        self.lbl_range.setStyleSheet("color:#5f6b7a;")
        h.addWidget(self.lbl_range)
        h.addStretch(1)
        self.lbl_pick = QLabel("")
        h.addWidget(self.lbl_pick)
        return w

    def _on_per_page_changed(self) -> None:
        """Đã bỏ phân trang — giữ hàm để code cũ gọi được, không làm gì."""
        return

    def _refresh_pager(self) -> None:
        m = self.model
        sel = m.selected_count()
        if m.total == 0:
            self.lbl_scanned.setText("Chưa quét")
            self.lbl_range.setText("Chưa có tài khoản")
            self.lbl_pick.setText("")
        else:
            self.lbl_scanned.setText(
                f"✔ Đã quét {m.total:,} tài khoản".replace(",", "."))
            self.lbl_range.setText("")
            self.lbl_pick.setText(f"đã chọn {sel}/{m.total}")
        self._refresh_pick_stat()

    def _apply_row_height(self) -> None:
        """Đặt chiều cao dòng cho bảng log.

        `minimumSectionSize` mặc định 24px và nó chặn MỌI giá trị nhỏ
        hơn — kể cả `setDefaultSectionSize(14)`. Muốn dòng 14px phải hạ
        minimum xuống trước, nếu không bảng cứ vẽ 24px. Đây là bẫy rất
        dễ sót vì không có lỗi nào hiện ra.
        """
        if not hasattr(self, "tbl_run"):
            return
        vh = self.tbl_run.verticalHeader()
        h = 18
        vh.setMinimumSectionSize(h)
        vh.setDefaultSectionSize(h)
        if vh.count():
            vh.resizeSection(0, h)

    @staticmethod
    def _node_installed() -> bool:
        """Node.js có trong PATH không? (chạy ngoài, có timeout ngắn)"""
        import subprocess
        exe = "node"
        try:
            r = subprocess.run(
                [exe, "-v"], capture_output=True, text=True, timeout=5,
                creationflags=(subprocess.CREATE_NO_WINDOW
                               if IS_WINDOWS else 0),
            )
            return r.returncode == 0
        except (OSError, subprocess.SubprocessError):
            # Trên Windows `node` có thể nằm trong PATH nhưng là file .cmd
            # cần gọi qua shell; thử thêm bằng `where`/`which`.
            for probe in (("where", "node") if IS_WINDOWS else ("which", "node")):
                try:
                    r2 = subprocess.run(
                        list(probe), capture_output=True, text=True,
                        timeout=5,
                        creationflags=(subprocess.CREATE_NO_WINDOW
                                       if IS_WINDOWS else 0),
                    )
                    if r2.returncode == 0 and r2.stdout.strip():
                        return True
                except (OSError, subprocess.SubprocessError):
                    continue
            return False

    @staticmethod
    def _signer_dir_installed() -> bool:
        """Thư mục sidecar đã tải về chưa (tức đã chạy signer ít nhất 1 lần)."""
        return (Path.cwd() / "tiktok-signature" / "node_modules").is_dir()

    # ------------------------------------------------------------------ #
    # Tự bật sidecar ký
    # ------------------------------------------------------------------ #
    def _start_signer(self) -> None:
        """Mở tiến trình Node ký ngay từ trong app.

        Trước đây phải tự mở terminal rồi chạy signer — dễ quên, và trên
        Windows người dùng hay hiểu là đã xong khi thấy cửa sổ đen. Giờ app
        tự bật, có hộp thoại log riêng để thấy nó đang làm gì.
        """
        if self._signer_proc is not None:
            QMessageBox.information(
                self, "Sidecar đang chạy",
                "Sidecar ký đã được bật từ app này.\n"
                "Đợi tới khi thanh dưới hiện 'sidecar ✓' rồi bấm CHẠY.")
            return

        # ĐÃ CÓ SIDECAR CHẠY SẴN THÌ ĐỪNG BẬT CÁI THỨ HAI.
        # Rất hay xảy ra: người dùng đã mở signer.bat ở cửa sổ riêng, hoặc
        # bấm "Bật sidecar" lần trước mà tiến trình chưa kịp thoát. Cái
        # thứ hai không bind được cổng 8080 (đã bận) nên chết ngay, và app
        # báo "sidecar đã dừng" — rất dễ gây hiểu nhầm là app hỏng.
        from core.signer import Signer
        try:
            already = Signer(self.in_signer.text().strip()).health()
        except Exception:
            already = None
        if already and already.get("ready"):
            self._signer_ready = True
            self.lbl_signer.setText(
                f"sidecar ✓ {already.get('generationCount', 0)} chữ ký")
            self.lbl_signer.setProperty("role", "hint")
            self._style_signer_label()
            self._log("signer",
                      "Sidecar ký đã chạy sẵn (có thể do bạn mở "
                      f"{SIGNER_SCRIPT} ở cửa sổ khác) — dùng luôn, không "
                      "cần bật thêm. Bạn có thể bấm CHẠY ngay.", "ok")
            return

        script = SIGNER_SCRIPT
        path = Path.cwd() / script
        if not path.exists():
            QMessageBox.warning(
                self, "Thiếu script",
                f"Không thấy file {script} trong thư mục hiện tại:\n"
                f"{Path.cwd()}\n\n"
                "Bạn có thể đã chạy app từ chỗ khác. Hãy mở app bằng "
                f"{'start.sh' if IS_MAC else 'start.bat'} để nó dùng đúng "
                "thư mục dự án.")
            return
        if not self._node_installed():
            QMessageBox.warning(
                self, "Thiếu Node.js",
                "Chưa cài Node.js nên không bật được sidecar.\n\n"
                "Cài bản LTS tại https://nodejs.org/ rồi MỞ LẠI app "
                "(hoặc mở lại terminal) để nó nhận ra lệnh `node`.")
            return

        try:
            self._signer_proc = QProcess(self)
            if IS_MAC:
                self._signer_proc.setProgram("/bin/sh")
                self._signer_proc.setArguments([str(path)])
            else:
                # Chạy TRỰC TIẾP, KHÔNG qua lệnh `start`.
                #
                # `start` cần mở một cửa sổ console mới; trên máy bị giới
                # hạn (RAM ảo hạn chế, session xa, quyền hạn chế) nó lỗi
                # "Not enough memory resources are available to process this
                # command" rồi im lặng — nhìn như app bật được nhưng sidecar
                # không chạy. Chạy `cmd /c <bat>` không cần cửa sổ mới, lại
                # còn đọc được output của sidecar để đưa vào nhật ký.
                #
                # ĐỪNG tự thêm dấu nháy quanh path: Qt đã escape sẵn, thêm
                # nữa sẽ thành "...signer.bat\" và Windows báo "cannot find".
                self._signer_proc.setProgram("cmd")
                self._signer_proc.setArguments(["/c", str(path)])
            self._signer_proc.setWorkingDirectory(str(path.parent))
            self._signer_proc.readyReadStandardOutput.connect(
                self._signer_output)
            self._signer_proc.errorOccurred.connect(self._signer_error)
            self._signer_proc.finished.connect(
                lambda *_: self._signer_finished())
            self._signer_proc.start()
        except Exception as e:
            self._signer_proc = None
            QMessageBox.critical(
                self, "Không bật được sidecar",
                f"{type(e).__name__}: {e}")
            return

        self.lbl_signer.setText("sidecar: ĐANG BẬT…")
        self.lbl_signer.setProperty("role", "warn")
        self._style_signer_label()
        self._signer_tail.clear()
        self._log("signer",
                  f"Đang bật sidecar ký bằng {script}… "
                  f"Lần đầu phải tải Chromium nên có thể mất vài phút.", "head")
        # Sidecar cần 30-60 giây nạp trình duyệt; hỏi liên tục một lúc rồi bỏ.
        self._signer_wait = 0
        self._signer_poll = QTimer(self)
        self._signer_poll.setInterval(2000)
        self._signer_poll.timeout.connect(self._poll_after_start)
        self._signer_poll.start()

    @Slot()
    def _signer_output(self) -> None:
        # `cmd /c start` trả về NGAY (nó chỉ mở cửa sổ mới rồi thoát), nên
        # `finished` bắn trước khi sidecar kịp nạp. Vì vậy coi việc thoát
        # sớm là bình thường, không báo lỗi.
        if self._signer_proc is None:
            return
        try:
            data = bytes(self._signer_proc.readAllStandardOutput())
        except RuntimeError:
            return                      # tiến trình đã bị hủy khi đóng app
        for line in data.decode("utf-8", "replace").splitlines():
            line = line.strip()
            if line:
                self._signer_tail.append(line)
                # giữ vài dòng cuối: khi sidecar chết, đây là manh mối
                # duy nhất cho biết nó chết vì lý do gì
                if len(self._signer_tail) > 30:
                    del self._signer_tail[0]
                self._log("signer", line, "info")

    @Slot()
    def _signer_error(self, err) -> None:
        if self._signer_proc is None:
            return
        self._log("signer", f"Lỗi bật sidecar: {err}", "err")

    def _poll_after_start(self) -> None:
        """Sau khi bật sidecar, hỏi /health cho tới khi sẵn sàng."""
        if self._signer_poll is None:
            return
        self._signer_wait += 1
        from core.signer import Signer
        try:
            info = Signer(self.in_signer.text().strip()).health()
        except Exception:
            info = None
        if info and info.get("ready"):
            self._signer_poll.stop()
            self._signer_ready = True
            self.lbl_signer.setText(
                f"sidecar ✓ {info.get('generationCount', 0)} chữ ký")
            self.lbl_signer.setProperty("role", "hint")
            self._style_signer_label()
            self._log("signer", "Sidecar ký đã sẵn sàng.", "ok")
            return
        if self._signer_wait >= 45:          # ~90 giây
            self._signer_poll.stop()
            self._log("signer",
                      "Sidecar vẫn chưa sẵn sàng sau 90 giây. Nếu đây là lần "
                      "đầu, nó đang tải Chromium — cần Internet.", "warn")

    @Slot()
    def _signer_finished(self) -> None:
        # Sidecar chạy dạng tiến trình con của app, nên khi nó dừng (lỗi
        # node, đóng cửa sổ ký) thì `finished` mới bắn — và đó là lúc nên
        # báo người dùng biết.
        if self._signer_poll is not None:
            self._signer_poll.stop()
            self._signer_poll = None
        self._signer_proc = None
        if not self._signer_ready:
            self.lbl_signer.setText("sidecar: ĐÃ DỪNG")
            self.lbl_signer.setProperty("role", "err")
            self._style_signer_label()
            self._log(
                "signer",
                "Tiến trình sidecar đã thoát. Xem các dòng log phía trên để "
                "biết lý do (thường là thiếu Node.js, hoặc đang tải "
                "Chromium lần đầu nên bị gián đoạn).",
                "err",
            )
            # Đưa nguyên nhân lên nút bấm — log thì dễ lướt qua, và người
            # dùng không biết phải cuộn lên trên.
            hint = ""
            tail = "\n".join(self._signer_tail[-6:])
            if tail:
                hint = f"\n\nDòng cuối của sidecar:\n{tail}"
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Sidecar ký đã dừng")
            box.setText(
                "Tiến trình ký TikTok vừa thoát, nên mọi request sẽ thất "
                "bại." + hint
            )
            box.setInformativeText(
                "Cách xử lý:\n"
                f"  1. Mở tab Chi tiết, đọc dòng log bắt đầu bằng [signer].\n"
                f"  2. Bấm 'Bật sidecar' lần nữa.\n"
                "\n"
                "Nếu nó dừng ngay lập tức, thường là do:\n"
                "  • Cổng 8080 đã bị chiếm bởi một sidecar khác — đóng cửa\n"
                "    sổ terminal còn mở, hoặc tắt hẳn sidecar cũ rồi bật lại.\n"
                "  • Node.js chưa được nhận ra — cài xong phải MỞ LẠI app,\n"
                "    vì biến PATH của tiến trình đang chạy không tự cập nhật."
            )
            box.exec()

    @Slot()
    # ------------------------------------------------------------------ #
    # Kiểm tra trạng thái tài khoản (chuột phải)
    # ------------------------------------------------------------------ #
    def _show_table_menu(self, pos: QPoint) -> None:
        """Menu chuột phải TRÊN BẢNG LOG — nơi chạy và xem kết quả."""
        m = QMenu(self)
        running = self.checker.running
        idle = (not running) and (not self.controller.busy)
        n_tick = self.model.selected_count()

        def act(text, slot, enabled=True, tip=""):
            a = QAction(text, self)
            a.setEnabled(enabled)
            if tip:
                a.setToolTip(tip)
            a.triggered.connect(slot)
            m.addAction(a)
            return a

        # --- CHẠY: lối vào không phụ thuộc quét chuột có đẹp hay không ---
        head = QAction(f"▶  Chạy {n_tick} tài khoản đã chọn", self)
        head.setEnabled(bool(n_tick) and idle)
        head.setToolTip("Chạy ngay những tài khoản đang được chọn.\n"
                        "Tôn trọng ô 'Số lượng tài khoản chạy' ở bên phải.")
        head.triggered.connect(lambda: self.start_run())
        m.addAction(head)

        if n_tick:
            sub = QMenu(f"Chạy với {n_tick} tài khoản", self)
            m.addMenu(sub)
            sub.addAction("Chạy 1 tài khoản (thử nhanh)").triggered.connect(
                lambda: self.start_run(dry_run=True))
            sub.addSeparator()
            a = sub.addAction("Kiểm tra phiên (không thả tim)")
            a.setEnabled(idle)
            a.triggered.connect(lambda: self.start_run(mode=MODE_CHECK))
            sub.addSeparator()
            a = sub.addAction("Kiểm tra trạng thái tài khoản (cột Status)")
            a.setEnabled(idle)
            a.triggered.connect(self._check_ticked)
        m.addSeparator()

        # --- quản lý danh sách ---
        a = act("☰ Mở danh sách tài khoản để tick tay",
                self._open_account_picker, not self.controller.busy)
        act("☑ Chọn tất cả tài khoản",
            lambda: self.model.toggle_all(True), True)
        act("☐ Bỏ chọn", self.model.select_none, True)
        act("✔ Chỉ chọn còn phiên",
            self.model.select_all_with_session, True)
        m.addSeparator()
        act("Bỏ tick những tài khoản đã die", self._untick_dead,
            not self.controller.busy)
        m.addSeparator()
        a = act("⧉ Sao chép các cid đã hoàn thành", self._copy_done_cids,
                bool(self.runlog.done_cids))
        if a and not a.isEnabled():
            a.setToolTip("Chưa có cid nào hoàn thành.")
        act("✕ Xoá bảng log", self._clear_runlog, True)
        m.exec(self.tbl_run.viewport().mapToGlobal(pos))

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

    def _build_task(self) -> QWidget:
        box = QGroupBox("Tác vụ")
        box.setMaximumWidth(520)
        v = QVBoxLayout(box)
        v.setContentsMargins(10, 14, 10, 12)
        v.setSpacing(10)

        # --- nhóm: số lượng profile chạy ---
        # Người dùng tick hàng nghìn tài khoản nhưng chỉ muốn chạy thử
        # N cái để đo tốc độ thật. Không có ô này thì phải bỏ tick thủ
        # công, rất dễ sai số lượng.
        gb_n = QGroupBox("Số lượng tài khoản chạy")
        fn = QFormLayout(gb_n)
        fn.setContentsMargins(10, 6, 10, 10)
        fn.setHorizontalSpacing(8)
        fn.setVerticalSpacing(6)
        fn.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Ô số lượng + 2 radio cạnh nhau trong cùng một hàng
        row_n = QWidget()
        hn = QHBoxLayout(row_n)
        hn.setContentsMargins(0, 0, 0, 0)
        hn.setSpacing(6)

        self.sp_pick = QSpinBox()
        self.sp_pick.setRange(0, 1_000_000)
        self.sp_pick.setValue(0)
        self.sp_pick.setSpecialValueText("tất cả")
        self.sp_pick.setFixedWidth(96)
        self.sp_pick.setToolTip(
            "0 = chạy tất cả những tài khoản đã tick.\n"
            "Ví dụ 60 = chỉ chạy 60 tài khoản (xem nhóm bên dưới để chọn\n"
            "lấy ngẫu nhiên hay theo thứ tự)."
        )
        hn.addWidget(self.sp_pick)

        self.rb_pick_order = QRadioButton("Theo thứ tự")
        self.rb_pick_random = QRadioButton("Ngẫu nhiên")
        self.rb_pick_order.setChecked(True)
        self.rb_pick_order.setToolTip(
            "Lấy N tài khoản đầu theo thứ tự đang hiển thị trên bảng.\n"
            "Dùng khi muốn chạy lại đúng một lô cũ để so sánh."
        )
        self.rb_pick_random.setToolTip(
            "Bấm ngẫu nhiên N tài khoản, không trùng lặp trong một lần chọn.\n"
            "Dùng khi muốn mẫu đại diện, tránh luôn chạy đúng một đầu danh sách."
        )
        hn.addWidget(self.rb_pick_order)
        hn.addWidget(self.rb_pick_random)
        hn.addStretch(1)
        fn.addRow("Chạy:", row_n)

        # Dòng báo số thực tế sẽ chạy, cập nhật khi tick/bỏ tick/đổi số
        self.lbl_pick_stat = QLabel("")
        self.lbl_pick_stat.setProperty("role", "hint")
        self.lbl_pick_stat.setWordWrap(True)
        fn.addRow("", self.lbl_pick_stat)
        v.addWidget(gb_n)

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
        self.sp_threads.setRange(1, 500)
        # Nạp lại giá trị đã lưu, KHÔNG cứng 10. Trước đây setValue(10)
        # khiến người dùng đổi xong bấm CHẠY lại bị nhảy về 10 — và bản
        # ghi trong settings.json cũng không bao giờ được cập nhật.
        self.sp_threads.setValue(self.settings.concurrency)
        self.sp_threads.setFixedWidth(92)
        self.sp_threads.setToolTip(
            "Tốc độ gần như tuyến tính theo số luồng.\n"
            "Nên để <= số nhân của CPU × 3.\n"
            "Trần thật là sidecar (~360 tài khoản/phút), thêm luồng vượt\n"
            "trần chỉ tốn RAM mà không nhanh hơn — cần proxy xoay IP mới tăng."
        )
        fs.addRow("Số luồng:", self.sp_threads)

        # Gợi ý nhanh theo máy, tránh phải tự nhớ trần.
        self.lbl_thread_hint = QLabel("")
        self.lbl_thread_hint.setProperty("role", "hint")
        self.lbl_thread_hint.setWordWrap(True)
        fs.addRow("", self.lbl_thread_hint)

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
        """Dải nhật ký gọn ở đáy màn chính.

        Trước đây nhật ký nằm ở tab "Chi tiết" nguyên một khung lớn.
        Nay chỉ còn dải 4 dòng dưới bảng log — đủ để thấy lỗi và
        thông báo đầu phiên, mà không cần chuyển sang tab khác.
        """
        box = QFrame()
        box.setProperty("role", "card")
        v = QVBoxLayout(box)
        v.setContentsMargins(6, 3, 6, 3)
        v.setSpacing(2)

        self.log_edit = QPlainTextEdit()
        self.log_edit.setObjectName("log")
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumBlockCount(4000)
        self.log_edit.setFixedHeight(76)
        self.log_edit.verticalScrollBar().setValue(999999)
        v.addWidget(self.log_edit)

        h = QHBoxLayout()
        h.setSpacing(4)
        self.lbl_stat = QLabel("")
        self.lbl_stat.setProperty("role", "hint")
        h.addWidget(self.lbl_stat, 1)
        b = QPushButton("Xoá nhật ký")
        b.setObjectName("ghost")
        b.clicked.connect(self.log_edit.clear)
        h.addWidget(b)
        v.addLayout(h)
        return box

    def _connect(self) -> None:
        self.btn_load.clicked.connect(self.on_load_file)
        self.btn_check.clicked.connect(lambda: self.start_run(mode=MODE_CHECK))
        self.btn_run.clicked.connect(self.start_run)
        self.btn_stop.clicked.connect(self.on_stop)
        self.in_cid.textChanged.connect(self._on_cid_text_changed)
        self.cb_pool.toggled.connect(self._refresh_proxy_label)
        self.tab_settings.log.connect(self._on_settings_log)
        self.tab_settings.proxies_ready.connect(self._on_proxies_ready)


        # Ô "số lượng tài khoản chạy" — dòng báo số thực tế phải cập nhật
        # theo mọi thay đổi: tick/bỏ tick, đổi số, đổi radio.
        self.sp_pick.valueChanged.connect(lambda *_: self._refresh_pick_stat())
        self.rb_pick_order.toggled.connect(lambda *_: self._refresh_pick_stat())
        self.rb_pick_random.toggled.connect(lambda *_: self._refresh_pick_stat())

        # Mọi tham số chạy ở tab Tác vụ đều lưu NGAY khi đổi, không đợi
        # bấm CHẠY — nếu chỉ lưu lúc chạy thì đóng app ở giữa chừng thì
        # mất, và người dùng phải chạy thử mới biết đã lưu chưa.
        self.sp_threads.valueChanged.connect(self._on_threads_changed)
        self.sp_retry.valueChanged.connect(lambda v: self._save_param(
            "retries", v))
        self.sp_dmin.valueChanged.connect(lambda v: self._save_param(
            "delay_min", v))
        self.sp_dmax.valueChanged.connect(lambda v: self._save_param(
            "delay_max", v))
        self.cb_verify.toggled.connect(lambda v: self._save_param("verify", v))
        self.sp_pick.valueChanged.connect(lambda v: self._save_param(
            "pick_limit", v))
        self.rb_pick_random.toggled.connect(
            lambda v: self._save_param("pick_how", (
                AccountTableModel.PICK_RANDOM if v
                else AccountTableModel.PICK_ORDER)))
        self.cb_mode.currentIndexChanged.connect(
            lambda _i: self._save_param("mode", self.cb_mode.currentData()))
        self.in_signer.editingFinished.connect(
            lambda: self._save_param("signer_url", self.in_signer.text().strip()))
        self.backend_kind.currentIndexChanged.connect(
            lambda _i: self._save_param("backend_kind",
                                        self.backend_kind.currentData()))
        self._update_thread_hint(self.sp_threads.value())

        # đổi trang -> cập nhật nhãn đếm
        self.model.modelReset.connect(self._on_model_reset)
        self.model.dataChanged.connect(lambda *_: self._refresh_picker())
        self._refresh_pager()

    # ------------------------------------------------------------------ #
    # ------------------------------------------------------------------ #
    # Panel chi tiết
    # ------------------------------------------------------------------ #
    def _on_model_reset(self) -> None:
        """Model vừa nạp lại / đổi bộ lọc -> cập nhật lại số đã chọn."""
        self._refresh_pager()

    def _restore_task_params(self) -> None:
        """Đổi tham số ở tab Tác vụ → lần sau mở app vẫn giữ nguyên.

        Trước đây mọi ô đều về mặc định (10 luồng, 1 trễ, 1 retry…): sửa
        xong đóng app là mất trắng. Nay mỗi ô ghi vào settings ngay khi
        đổi (xem _connect), và hàm này đọc lại khi khởi động.
        """
        s = self.settings
        # blockSignals vì widget đã nối valueChanged -> _save_param; nếu
        # không, mỗi ô sẽ ghi lại settings một lần lúc khởi động.
        for widget, value, setter in (
            (self.sp_threads, s.concurrency, lambda w, v: w.setValue(v)),
            (self.sp_retry, s.retries, lambda w, v: w.setValue(v)),
            (self.sp_dmin, s.delay_min, lambda w, v: w.setValue(v)),
            (self.sp_dmax, s.delay_max, lambda w, v: w.setValue(v)),
            (self.cb_verify, s.verify, lambda w, v: w.setChecked(v)),
            (self.in_signer, s.signer_url,
             lambda w, v: w.setText(v or "http://127.0.0.1:8080")),
            (self.sp_pick, s.pick_limit, lambda w, v: w.setValue(v)),
        ):
            widget.blockSignals(True)
            try:
                setter(widget, value)
            finally:
                widget.blockSignals(False)

        # radio: 1 trong 2 luôn bật
        pick_random = (s.pick_how == AccountTableModel.PICK_RANDOM)
        for rb in (self.rb_pick_order, self.rb_pick_random):
            rb.blockSignals(True)
        self.rb_pick_random.setChecked(pick_random)
        self.rb_pick_order.setChecked(not pick_random)
        for rb in (self.rb_pick_order, self.rb_pick_random):
            rb.blockSignals(False)

        i = self.cb_mode.findData(s.mode)
        if i >= 0:
            self.cb_mode.setCurrentIndex(i)
        i = self.backend_kind.findData(s.backend_kind)
        if i >= 0:
            self.backend_kind.setCurrentIndex(i)

        self._update_thread_hint(self.sp_threads.value())
        self._refresh_pick_stat()

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
            # KHÔNG ghi "trang này N" nữa: đã bỏ phân trang nên "trang này"
            # luôn bằng tổng, chỉ làm nhãn rối mà không thêm thông tin gì.
            self.lbl_pick.setText(f"đã tick {m.selected_count()}/{m.total}")
        self._refresh_pick_stat()

    # ------------------------------------------------------------------ #
    # Chọn số lượng tài khoản chạy (ô số + 2 radio)
    # ------------------------------------------------------------------ #
    def _pick_how(self) -> str:
        """Cách lấy N tài khoản: theo thứ tự hay ngẫu nhiên."""
        return (
            AccountTableModel.PICK_RANDOM if self.rb_pick_random.isChecked()
            else AccountTableModel.PICK_ORDER
        )

    def _pick_limit(self) -> int:
        return self.sp_pick.value()

    def _refresh_pick_stat(self) -> None:
        """Báo chính xác số tài khoản SẼ chạy, để không phải tự đếm tay."""
        if not hasattr(self, "sp_pick"):
            return
        ticked = self.model.selected_count()
        limit = self.sp_pick.value()

        if not ticked:
            self.lbl_pick_stat.setText(
                "Chưa tick tài khoản nào — bấm '☑ Tick tất cả' ở thanh trên."
            )
            return
        if limit <= 0:
            self.lbl_pick_stat.setText(
                f"Sẽ chạy toàn bộ {ticked} tài khoản đã tick "
                f"(ô đang để 0 = không giới hạn)."
            )
            return
        if limit >= ticked:
            self.lbl_pick_stat.setText(
                f"Ô đang để {limit} nhưng mới chỉ tick {ticked} → "
                f"sẽ chạy hết {ticked}."
            )
            return
        how = AccountTableModel.PICK_LABELS[self._pick_how()]
        self.lbl_pick_stat.setText(
            f"Sẽ chạy {limit} tài khoản ({how.lower()}) trong "
            f"{ticked} tài khoản đã tick."
        )

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
        # Phân biệt "chưa cài Node.js" với "cài rồi nhưng chưa bật sidecar" —
        # hai lỗi này dễ bị nhầm làm một, nhưng cách sửa hoàn toàn khác nhau.
        if not self._node_installed():
            self.lbl_signer.setText("sidecar: THIẾU NODE.JS")
            cause = "máy này chưa cài Node.js (cần cho sidecar ký)"
        elif not self._signer_dir_installed():
            self.lbl_signer.setText("sidecar: CHƯA CÀI")
            cause = "chưa từng chạy signer — còn thiếu tiktok-signature"
        else:
            self.lbl_signer.setText("sidecar: CHƯA CHẠY")
            cause = "sidecar đã cài nhưng tiến trình đang không chạy"
        self.lbl_signer.setProperty("role", "err")
        self._style_signer_label()
        self._log(
            "signer",
            "CHƯA CÓ SIDECAR KÝ → mọi request TikTok sẽ thất bại.\n"
            f"  Nguyên nhân : {cause}.\n"
            f"  Cách sửa   : {SIGNER_STEP_RUN} (1 lần),\n"
            f"               GIỮ cửa sổ đó mở,\n"
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
        """Đồng bộ tham số chạy về settings.

        TRƯỚC đây hàm này ghi ĐÈ spinbox bằng giá trị trong settings, nên
        người dùng sửa "Số luồng" ở tab Tác vụ rồi bấm CHẠY sẽ bị nhảy
        về giá trị cũ — đúng cảm giác "sửa không được". Nay chiều là
        ngược lại: spinbox là nguồn, settings nhận theo.
        """
        s = self.settings
        s.concurrency = self.sp_threads.value()
        s.retries = self.sp_retry.value()
        s.delay_min = self.sp_dmin.value()
        s.delay_max = self.sp_dmax.value()
        s.verify = self.cb_verify.isChecked()
        s.signer_url = self.in_signer.text().strip()
        # giữ cho ô ẩn ở tab Cài đặt đồng bộ, phòng khi sau này bật lại
        self.tab_settings.sp_conc.setValue(s.concurrency)
        self.tab_settings.sp_retry.setValue(s.retries)
        self.tab_settings.sp_dmin.setValue(s.delay_min)
        self.tab_settings.sp_dmax.setValue(s.delay_max)
        self.tab_settings.cb_verify.setChecked(s.verify)
        self.controller._rotate = s.rotate_on_block
        self._save_settings_quiet()

    def _selected_accounts(self) -> list:
        """Các tài khoản của những dòng đang được chọn trên bảng."""
        out = []
        for i in self.table.selectionModel().selectedRows():
            a = self.model.row_to_account(i.row())
            if a is not None:
                out.append(a)
        return out

    def _save_settings_quiet(self) -> None:
        """Lưu cấu hình, không spam nhật ký.

        Gọi mỗi lần người dùng đổi tham số — nếu cứ ghi log "Đã lưu cấu
        hình" thì đổi 5 ô sẽ thành 5 dòng log rác. Chỉ báo lỗi thật.
        """
        try:
            self.settings.save()
        except OSError as e:
            self._log("cài đặt", f"Không lưu được cấu hình: {e}", "err")

    def _save_param(self, name: str, value) -> None:
        """Ghi một tham số vào settings rồi lưu. Không log gì khi thành công."""
        setattr(self.settings, name, value)
        # giữ các ô ẩn ở tab Cài đặt đồng bộ ngay, phòng khi app bị tắt
        # đột ngột (mất điện, kill tiến trình) — lúc đó closeEvent không
        # chạy và closeEvent chỉ là phương án dự phòng.
        if hasattr(self, "tab_settings"):
            mirror = {"retries": "sp_retry", "delay_min": "sp_dmin",
                      "delay_max": "sp_dmax", "verify": "cb_verify",
                      "signer_url": "in_signer"}.get(name)
            if mirror:
                w = getattr(self.tab_settings, mirror, None)
                if w is not None:
                    w.blockSignals(True)
                    try:
                        (w.setValue if name != "verify" and
                         name != "signer_url" else
                         (w.setChecked if name == "verify" else w.setText))(value)
                    finally:
                        w.blockSignals(False)
        self._save_settings_quiet()

    def _on_threads_changed(self, value: int) -> None:
        """Người dùng đổi số luồng -> lưu ngay để mở lại app còn giữ."""
        self.settings.concurrency = value
        # đồng bộ luôn ô ẩn của tab Cài đặt, không đợi tới lúc đóng app —
        # nếu không thì đóng app bằng cách tắt cửa sổ đột ngột sẽ mất.
        if hasattr(self, "tab_settings"):
            self.tab_settings.sp_conc.setValue(value)
        self._update_thread_hint(value)
        self._save_settings_quiet()

    def _suggest_threads(self) -> int:
        """Gợi ý số luồng theo CPU.

        Python không phải nút thắt (phân phối ~5.800 acc/s); nút thắt là
        sidecar. Nên gợi ý theo CPU nhưng có trần, tránh gợi ý 200 luồng
        trên máy có 4 nhân rồi người dùng tưởng app treo.
        """
        import os as _os
        try:
            cores = _os.cpu_count() or 4
        except Exception:
            cores = 4
        return max(4, min(50, cores * 3))

    def _update_thread_hint(self, value: int) -> None:
        sug = self._suggest_threads()
        if not hasattr(self, "lbl_thread_hint"):
            return
        if value > sug:
            self.lbl_thread_hint.setText(
                f"⚠ {value} luồng > gợi ý {sug} cho máy này. "
                f"Trần thật do sidecar, tăng thêm sẽ chậm hơn chứ không "
                f"nhanh hơn."
            )
        else:
            self.lbl_thread_hint.setText(
                f"Gợi ý cho máy này: {sug} luồng. Giá trị được nhớ, "
                f"mở lại app vẫn giữ."
            )

    def start_run(self, mode: str | None = None, dry_run: bool = False,
                  accounts: list | None = None) -> None:
        """Bắt đầu chạy.

        `accounts` cho phép chạy một danh sách cụ thể (dùng khi chuột
        phải → "Chạy riêng tài khoản này"), thay vì bắt buộc phải tick.
        Không truyền thì lấy những tài khoản đã tick như cũ.
        """
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

        # Lấy theo thứ tự đã tick, KHÔNG giới hạn theo bộ lọc/trang đang xem.
        if accounts is None:
            accounts = self.model.selected_accounts()
        else:
            accounts = [a for a in accounts if a is not None]
        if not accounts:
            QMessageBox.information(self, "Chưa chọn", "Hãy tick ít nhất 1 tài khoản.")
            return

        # Áp ô "số lượng tài khoản chạy": 0 = chạy hết những gì đã tick,
        # > 0 = chỉ lấy N cái theo radio đang chọn (ngẫu nhiên / thứ tự).
        n_ticked = len(accounts)
        limit = self._pick_limit()
        if not dry_run and limit > 0 and limit < n_ticked:
            accounts = self.model.pick_for_run(limit, self._pick_how())
            how = AccountTableModel.PICK_LABELS[self._pick_how()].lower()
            self._log("head", f"Chạy {len(accounts)}/{n_ticked} tài khoản "
                              f"({how}).", "head")
        if dry_run:
            accounts = accounts[:1]
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
            # Chẩn đoán nguyên nhân thật, đừng chỉ nói chung chung "chưa có
            # sidecar". Ba trường hợp rất khác nhau và cách sửa khác nhau:
            #   1. Chưa bao giờ cài  -> thiếu Node.js
            #   2. Đã cài nhưng chưa bật -> cần mở sidecar
            #   3. Đang khởi động -> chờ thêm
            if not self._node_installed():
                box.setIcon(QMessageBox.Icon.Critical)
                box.setText(
                    "Máy này CHƯA CÀI NODE.JS.\n\n"
                    "Sidecar ký cần Node.js. Chưa có nó thì mọi request TikTok "
                    "đều thất bại, dù bạn tick bao nhiêu tài khoản."
                )
                box.setInformativeText(
                    "Cách sửa:\n"
                    + (f"  1. Mở https://nodejs.org/ , tải bản .pkg và cài.\n"
                       "     Chọn bản LTS (Node 18 trở lên là đủ).\n"
                       "     Cài xong PHẢI đóng rồi mở lại cửa sổ Terminal,\n"
                       "     vì biến PATH cũ chỉ có tác dụng ở cửa sổ mới.\n"
                       if IS_MAC else
                       f"  1. Mở https://nodejs.org/ , tải bản .msi và cài.\n"
                       "     Chọn bản LTS (Node 18 trở lên là đủ).\n"
                       "     Sau khi cài, đóng mọi cửa sổ cmd/PowerShell đang\n"
                       "     mở rồi mở lại, vì biến PATH cũ chỉ có tác dụng ở\n"
                       "     cửa sổ mới.\n")
                    + f"  2. Sau đó {SIGNER_STEP_RUN}\n"
                    "  3. Quay lại app, bấm 'Kiểm tra lại' ở thanh dưới.\n\n"
                    "Chưa muốn cài Node? Chọn Backend = mock để xem thao tác chạy."
                )
            else:
                box.setText(
                    "Chưa kết nối được sidecar ký nên mọi request TikTok đều "
                    "thất bại.\n\n"
                    "Bấm CHẠY bây giờ sẽ khiến tất cả tài khoản báo lỗi."
                )
                box.setInformativeText(
                    "Cách sửa:\n"
                    + SIGNER_STEPS
                    + "  3. Quay lại đây, bấm nút 'Kiểm tra lại' ở thanh dưới.\n\n"
                    "Muốn chỉ xem thao tác chạy thì chọn Backend = mock."
                )
            # QMessageBox dùng StandardButton CỦA NÓ, không phải của
            # QDialogButtonBox — trộn hai enum này sẽ vỡ ngay khi bấm CHẠY
            # mà sidecar chưa chạy.
            row = QMessageBox.StandardButton
            # Nút "Bật ngay" là đường ngắn nhất: bấm là app tự mở tiến
            # trình Node, không phải tự đi tìm file .bat/.sh.
            can_start = self._node_installed()
            box.setStandardButtons(row.Ok)
            box.button(row.Ok).setText("Hướng dẫn")
            if can_start:
                btn_start = box.addButton("Bật sidecar ngay", row.AcceptRole)
                btn_start.setToolTip(
                    f"App sẽ tự chạy {SIGNER_SCRIPT} và tự hỏi khi nào xong.")
            else:
                box.setInformativeText(
                    box.informativeText()
                    + f"\n\n(Không có nút bật ngay vì máy chưa có Node.js. "
                      f"Cài xong hãy mở lại app.)")
            clicked = box.exec()
            if clicked == row.Ok:
                self.tabs.setCurrentWidget(self.tab_settings)
            elif can_start and box.clickedButton() is not None \
                    and box.clickedButton().text() == "Bật sidecar ngay":
                self._start_signer()
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
        # mở sẵn dòng log cho từng tài khoản, gắn cid này vào
        self._log_run_start(accounts, cid)
        self._set_running(True)
        self._refresh_cid_label(running=self._cid_pos + 1)

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
                  self.btn_dry, self.btn_list):
            b.setEnabled(not running)
        self.btn_stop.setEnabled(running)

    # ------------------------------------------------------------------ #
    # Slots nhận signal từ worker — luôn chạy trên GUI thread
    # ------------------------------------------------------------------ #
    @Slot(int)
    def _log_run_start(self, accounts: list, cid: str) -> None:
        """Mở sẵn một dòng log cho mỗi tài khoản sắp chạy.

        Làm TRƯỚC khi chạy để bảng log hiện đủ danh sách ngay, người
        dùng thấy "đang chạy cái gì" chứ không phải chờ tới khi có kết
        quả mới thấy dòng đầu tiên.
        """
        self.runlog.reset()
        self.in_done_cid.clear()
        for a in accounts:
            self.runlog.add(a.id, cid=cid,
                             name=getattr(a, "username", "") or a.id)
        self._refresh_run_stat()

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
        """Một task đã trả về. Dùng cho đồng hồ tốc độ + tiến độ liên mạch."""
        acc = self.model.by_id(acc_id)
        ok = bool(acc) and acc.status in (ST_OK, ST_DONE)
        self.meter.add_done(ok)
        # Task xong thì không còn "đang xử lý" nữa. `_progress` chỉ giữ các
        # task CHƯA xong, nhờ vậy thanh tiến độ gộp được % của task đang chạy
        # và không bao giờ đếm trùng. Nhãn số để đồng hồ 250ms lo — hai chỗ
        # cùng ghi thì chữ sẽ giật qua lại giữa hai dạng.
        self._progress.pop(acc_id, None)

    @Slot()
    def _on_meter_tick(self) -> None:
        self.meter.tick()
        self._signer_ticks += 1
        if self._signer_ticks % 5 == 0:
            self._poll_signer_health()

    # ------------------------------------------------------------------ #
    # Đồng hồ "đang chờ" — 4 lần/giây, chạy suốt từ lúc bấm CHẠY
    # ------------------------------------------------------------------ #
    def _tick_wait(self) -> None:
        """Cập nhật nhãn trạng thái + thanh tiến độ.

        Đây là chỗ làm cho việc chạy 1..750 "liên mạch": kể cả khi 80 luồng
        cùng kẹt network, mỗi 250ms vẫn có con số mới (số việc đang treo,
        đang chờ ký hay chờ TikTok, bao lâu) — người dùng thấy app đang CHỜ,
        chứ không phải app ĐÃ CHẾT.
        """
        snap = tracker.snapshot()
        n_task = snap.get(TASK, (0, 0.0))[0]
        n_sign, age_sign = snap.get(SIGN, (0, 0.0))
        n_http, age_http = snap.get(HTTP, (0, 0.0))
        n_rest, age_rest = snap.get(REST, (0, 0.0))
        oldest = max(age_sign, age_http, age_rest)

        parts: list[str] = []
        if n_task:
            parts.append(f"{n_task} việc")
        if n_sign:
            parts.append(f"chờ ký {n_sign}")
        if n_http:
            parts.append(f"chờ TikTok {n_http}")
        if n_rest:
            parts.append(f"nghỉ {n_rest}")
        if parts and oldest >= 1.0:
            parts.append(f"lâu nhất {oldest:.0f}s")
        text = " · ".join(parts)

        if text != self._wait_text:
            self._wait_text = text
            self.lbl_wait.setText(text)
            self.lbl_wait.setVisible(bool(text))

        role = ("err" if oldest >= 15 else "warn" if oldest >= 5 else "hint")
        if self.lbl_wait.property("role") != role:
            self.lbl_wait.setProperty("role", role)
            self.lbl_wait.style().unpolish(self.lbl_wait)
            self.lbl_wait.style().polish(self.lbl_wait)

        # Số đếm cũng phải LIÊN MẠCH: vừa xong bao nhiêu, vừa có bao nhiêu
        # việc đang xử lý — để từ 1 → 750 lúc nào cũng thấy có chuyển động.
        # Chỉ setText khi chữ THẬT SỰ đổi, tránh 4 lần/giây bắt widget vẽ lại
        # vô ích khi con số không đổi.
        if self.controller.busy and self.meter._total:
            txt = (f"{self.meter._done}/{self.meter._total}"
                   + (f" · {n_task} đang xử lý" if n_task else ""))
            if self.lbl_stat.text() != txt:
                self.lbl_stat.setText(txt)

        self._tick_pbar()

    def _tick_pbar(self) -> None:
        """Thanh tiến độ LIÊN MẠCH: đã xong + % của những task đang chạy.

        Trước đây thanh chỉ nhảy khi có task xong (lại còn 2 chỗ ghi tranh
        nhau), nên lúc mọi luồng cùng chờ network thì thanh đứng im — đúng
        cảm giác "chết hẳn". Giờ một chỗ duy nhất ghi, cộng cả % dở dang,
        nên thanh trôi liên tục trong lúc chờ.
        """
        if not self.controller.busy:
            return
        total = self.meter._total
        if not total:
            return
        partial = sum(self._progress.values()) / 100.0
        value = int((self.meter._done + partial) * 100 / total)
        self.pbar.setValue(max(0, min(100, value)))

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
    def _log_row(self, acc_id: str, *, note: str = "", status: str = "",
                 cid: str = "", ok: bool | None = None) -> None:
        """Ghi 1 dòng vào bảng log chạy (tạo dòng nếu chưa có).

        `acc_id` là id tài khoản — cùng khoá với signal của worker, nên
        luôn khớp đúng dòng. Dòng thường đã được tạo lúc bắt đầu chạy;
        hàm này tự tạo nếu thiếu, để không mất log khi tài khoản phát
        tín hiệu trước lúc kịp thêm dòng.
        """
        if not any(r.acc == acc_id for r in self.runlog._rows):
            self.runlog.add(acc_id, cid=cid, name=self._acc_label(acc_id))
        self.runlog.set_status(acc_id, status, note=note, ok=ok)
        self._refresh_run_stat()

    def _acc_label(self, acc_id: str) -> str:
        """Tên hiển thị của tài khoản: username nếu có, không thì id."""
        a = self.model.by_id(acc_id)
        return getattr(a, "username", "") or acc_id

    def _on_status(self, acc_id: str, status: str, note: str) -> None:
        self.model.update_row(acc_id, status=status, note=note)
        # thẻ chi tiết đang hiển thị tài khoản này -> vẽ lại
        if status in (ST_OK, ST_DONE):
            # Ưu tiên dòng gọn kiểu "2 TIM CMT <cid>" để copy đi dùng.
            # Không đọc được cid thì giữ note gốc, không mất thông tin.
            acc = self.model.by_id(acc_id)
            line = format_success_line(
                note,
                comment_id=getattr(acc, "comment_id", "") or "",
                like_after=getattr(acc, "like_after", None),
            )
            self._log(acc_id, line or f"✔ {note or status}", "ok")
            if line:
                # Ghi luôn vào cột B để nhìn bảng là biết đã thả tim cid nào
                self.model.update_row(acc_id, note=line)
            self._log_row(acc_id, note=line or note or status,
                          status=LG_OK, ok=True)
        elif status == ST_FAIL:
            self._log(acc_id, f"✖ {note}", "err")
            self._log_row(acc_id, note=note, status=LG_FAIL, ok=False)
        elif status == ST_SKIP:
            self._log(acc_id, f"– {note or status}", "warn")
            self._log_row(acc_id, note=note or status, status="Bỏ qua")
        else:   # ST_DONE: đăng nhập hợp lệ, chưa bình luận (chế độ check)
            self._log_row(acc_id, note=note or status, status=LG_DONE)

    @Slot(str, int)
    def _on_progress(self, acc_id: str, pct: int) -> None:
        # Chỉ GHI %, không vẽ — việc vẽ để đồng hồ 250ms lo. Trước đây hai
        # chỗ cùng ghi thanh tiến độ (nơi theo "xong/tổng", nơi theo "trung
        # bình %") nên thanh nhảy ngược nhau.
        self._progress[acc_id] = pct

    @Slot(str, str)
    def _on_log(self, acc_id: str, message: str) -> None:
        self._log(acc_id, message, "info")
        # ghi vào CỘT C của bảng log — đây là chỗ người dùng nhìn để
        # biết tài khoản đó đang làm gì (đăng nhập / tìm comment / thả tim)
        self.runlog.update(acc_id, note=message)
        self._refresh_run_stat()

    @Slot()
    def _on_finished(self) -> None:
        # Thống kê lấy từ BẢNG LOG, không phải danh sách tài khoản:
        # bảng log mới là thứ người dùng nhìn, số phải khớp với nó.
        m = self.runlog
        n_rows = m.row_count()
        ok = sum(1 for r in m._rows if r.status == LG_OK)
        done = sum(1 for r in m._rows if r.status == LG_DONE)
        err = sum(1 for r in m._rows if r.status == LG_FAIL)
        skip = n_rows - ok - done - err
        self._refresh_run_stat()
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
        # Dong bo o an cua tab Cai dat ve gia tri dang hien o tab Tac vu
        # TRUOC khi luu. Neu khong, _sync_to_settings() lay sp_conc cu
        # (mac dinh 10) roi ghi de moi thieu nguoi dung vua chinh — day
        # chinh la ly do "sua so luong khong duoc, mo lai ve 10".
        self._sync_from_settings_tab()
        self.tab_settings._sync_to_settings()
        self.settings.last_cookie_file = str(
            self.settings.last_cookie_file or Path.cwd() / "cokie.tik.txt"
        )
        self.settings.cid_list = self.in_cid.toPlainText()
        self.settings.per_page = 0          # 0 = không phân trang
        try:
            p = self.settings.save()
            self._log("cài đặt", f"Đã lưu cấu hình: {p}", "ok")
        except OSError as e:
            self._log("cài đặt", f"Không lưu được cấu hình: {e}", "err")

        # Dừng sidecar mà APP khởi động. Không đụng tới tiến trình mà
        # người dùng tự mở — cửa sổ terminal của họ vẫn phải còn nguyên.
        if self._signer_poll is not None:
            self._signer_poll.stop()
            self._signer_poll = None
        self._kill_signer()
        event.accept()

    def _kill_signer(self) -> None:
        """Dừng sidecar do app bật, gồm CẢ tiến trình con.

        `signer.bat` chạy `npm start`, mà npm lại gọi `node` — nên giết
        riêng tiến trình cmd sẽ để lại node mồ côi vẫn giữ cổng 8080; lần
        sau app báo "sidecar chưa chạy" trong khi thực tế nó vẫn chạy. Vì
        vậy phải giết theo CÂY tiến trình: `taskkill /T` trên Windows,
        theo nhóm tiến trình trên macOS.
        """
        proc, self._signer_proc = self._signer_proc, None
        if proc is None:
            return
        pid = int(proc.processId() or 0)
        if not pid:
            return
        try:
            if IS_WINDOWS:
                import subprocess
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True, timeout=8,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                import os
                import signal
                os.killpg(os.getpgid(pid), signal.SIGTERM)
        except Exception:
            pass

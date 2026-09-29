"""Tab 'Cài đặt': kho proxy, phân phối cho từng account, cấu hình chung."""

from __future__ import annotations

import threading

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal, Slot
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTableView,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.gui_bridge import call_on_gui
from core.proxy import (
    MODE_GATEWAY,
    MODE_LABELS,
    ProxyPool,
    check_many,
)
from core.settings import AppSettings

IDX = Qt.ItemDataRole.UserRole + 1


class ProxyTableModel(QAbstractTableModel):
    """Bảng proxy: bật/tắt, địa chỉ, IP thoát, quốc gia, độ trễ, số account."""

    changed = Signal()

    HEADERS = ["Dùng", "Proxy", "IP thoát", "Nước", "Trễ", "Số acc"]
    COL_ON, COL_ADDR, COL_IP, COL_CC, COL_MS, COL_USED = range(6)

    def __init__(self, pool: ProxyPool, parent=None):
        super().__init__(parent)
        self._pool = pool

    def reload(self) -> None:
        self.beginResetModel()
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._pool.items)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.HEADERS)

    def _at(self, row: int):
        items = self._pool.items
        return items[row] if 0 <= row < len(items) else None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        p = self._at(index.row())
        if p is None:
            return None
        col = index.column()

        if role == IDX:
            return index.row()

        if role == Qt.ItemDataRole.CheckStateRole and col == self.COL_ON:
            return Qt.CheckState.Checked if p.enabled else Qt.CheckState.Unchecked

        if role == Qt.ItemDataRole.DisplayRole:
            return [
                "", p.safe_url(), p.exit_ip or "—", p.country or "—",
                f"{p.latency_ms}ms" if p.latency_ms else "—", str(p.assigned),
            ][col]

        if role == Qt.ItemDataRole.ForegroundRole:
            if col == self.COL_ADDR and p.ok is False:
                return QColor("#c0392b")
            if col == self.COL_MS and p.latency_ms:
                good = p.latency_ms < 1200
                return QColor("#1e9e5a" if good else "#e08b0a")
            if col in (self.COL_IP, self.COL_CC) and not p.exit_ip:
                return QColor("#aab4c2")

        if role == Qt.ItemDataRole.ToolTipRole and col == self.COL_ADDR:
            if p.ok is None:
                return "Chưa kiểm tra"
            if p.ok:
                return f"✔ Sống · {p.latency_ms}ms\n{p.safe_url()}\nIP thoát: {p.exit_ip}"
            return f"✖ Lỗi: {p.err}"

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (self.COL_MS, self.COL_USED):
                return int(Qt.AlignmentFlag.AlignCenter)
            if col == self.COL_ADDR:
                return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return None

    def setData(self, index: QModelIndex, value, role=Qt.ItemDataRole.EditRole):  # noqa: N802
        if role != Qt.ItemDataRole.CheckStateRole or index.column() != self.COL_ON:
            return False
        p = self._at(index.row())
        if p is None:
            return False
        p.enabled = value == Qt.CheckState.Checked
        self.dataChanged.emit(index, index)
        self.changed.emit()
        return True

    def flags(self, index: QModelIndex):
        if not index.isValid() or self._at(index.row()) is None:
            return Qt.ItemFlag.NoItemFlags
        f = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == self.COL_ON:
            f |= Qt.ItemFlag.ItemIsUserCheckable
        return f

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return section + 1


class SettingsTab(QWidget):
    """Chỉ giao diện: đọc/ghi `AppSettings`, không tự chạy tác vụ mạng lâu."""

    log = Signal(str, str)          # message, level
    settings_changed = Signal()
    proxies_ready = Signal(int)     # số proxy sau khi phân phối

    def __init__(self, settings: AppSettings, pool: ProxyPool, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.pool = pool
        self._accounts: list = []
        self._checking = False

        self.model = ProxyTableModel(pool, self)
        self._build()
        self._sync_from_settings()
        self.model.changed.connect(self.settings_changed.emit)

    # ------------------------------------------------------------------ #
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(10)

        # ---- proxy ----
        t = QLabel("CÀI ĐẶT")
        t.setProperty("role", "h1")
        v.addWidget(t)
        d = QLabel(
            "Proxy cho từng tài khoản, cổng VPN Express và tham số chạy. "
            "Cấu hình tự lưu khi đóng app."
        )
        d.setProperty("role", "hint")
        d.setWordWrap(True)
        v.addWidget(d)

        sp = QSplitter(Qt.Orientation.Horizontal)
        sp.addWidget(self._build_source())
        sp.addWidget(self._build_gateway())
        sp.setStretchFactor(0, 1)
        sp.setStretchFactor(1, 1)
        sp.setChildrenCollapsible(False)
        v.addWidget(sp, 1)

        # ---- bảng proxy ----
        gb_list = QGroupBox("Proxy trong danh sách")
        gv = QVBoxLayout(gb_list)
        gv.setContentsMargins(10, 6, 10, 8)
        gv.setSpacing(4)
        self.lbl_pool = QLabel("")
        self.lbl_pool.setProperty("role", "hint")
        gv.addWidget(self.lbl_pool)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        # bỏ đường kẻ dọc mảnh, chỉ giữ đường ngang cho dễ đọc
        self.table.setShowGrid(False)
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self.table.setColumnWidth(0, 44)
        self.table.setColumnWidth(1, 320)
        self.table.setColumnWidth(2, 140)
        self.table.setColumnWidth(3, 90)
        self.table.setColumnWidth(4, 80)
        self.table.setColumnWidth(5, 90)
        # cột cuối bám mép phải, không tràn dài vô tận
        self.table.horizontalHeader().setSectionResizeMode(
            self.model.COL_USED, QHeaderView.ResizeMode.Fixed
        )
        self.table.verticalHeader().setDefaultSectionSize(22)
        gv.addWidget(self.table, 1)
        v.addWidget(gb_list, 1)

        # ---- proxy hệ thống + cấu hình chung (một khung, hai cột) ----
        v.addWidget(self._build_system_proxy())
        area.setWidget(inner)
        outer.addWidget(area)

    # ------------------------------------------------------------------ #
    def _build_system_proxy(self) -> QWidget:
        """Dùng IP của máy qua proxy hệ thống khi không gán proxy cho account.

        Xếp cạnh khung 'Cấu hình chung' để tiết kiệm chiều cao.
        """
        gb = QGroupBox("Proxy hệ thống  ·  Cấu hình chung")
        h = QHBoxLayout(gb)
        h.setContentsMargins(10, 6, 10, 8)
        h.setSpacing(12)

        f = QFormLayout()
        f.setContentsMargins(0, 0, 0, 0)
        f.setHorizontalSpacing(8)
        f.setVerticalSpacing(5)
        f.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.cb_sys = QCheckBox(
            "Khi tài khoản chưa được gán proxy nào, dùng proxy hệ thống của máy"
        )
        self.cb_sys.setToolTip(
            "Đọc từ Windows WinINET / macOS scutil / GNOME gsettings /\n"
            "biến môi trường HTTPS_PROXY. Để trống thì chạy IP máy."
        )
        f.addRow("", self.cb_sys)

        row = QWidget()
        rh = QHBoxLayout(row)
        rh.setContentsMargins(0, 0, 0, 0)
        rh.setSpacing(4)
        self.in_sys = QLineEdit()
        self.in_sys.setPlaceholderText("http://user:pass@host:port")
        rh.addWidget(self.in_sys, 1)
        b_detect = QPushButton("Phát hiện")
        b_detect.setToolTip("Đọc cấu hình proxy của hệ điều hành")
        b_detect.clicked.connect(self._on_detect_system)
        rh.addWidget(b_detect)
        f.addRow("Proxy:", row)

        self.lbl_sys = QLabel("")
        self.lbl_sys.setProperty("role", "hint")
        self.lbl_sys.setWordWrap(True)
        f.addRow("", self.lbl_sys)
        h.addLayout(f, 1)

        # cột phải: cấu hình chung (dựng trong hàm riêng cho dễ đọc)
        h.addWidget(self._general_fields(), 1)
        return gb

    def _general_fields(self) -> QWidget:
        """Nửa phải của khung dưới — không bọc GroupBox để tránh khung lồng nhau."""
        w = QWidget()
        f = QFormLayout(w)
        f.setContentsMargins(0, 0, 0, 0)
        f.setHorizontalSpacing(8)
        f.setVerticalSpacing(5)
        f.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # KHÔNG đặt "Số luồng" / "Thử lại" ở đây nữa: tab Tác vụ đã có,
        # và có 2 ô cùng tên là người dùng sửa xong bị ô kia ghi đè mà
        # không biết. Giá trị lấy từ tab Tác vụ khi lưu.
        # Ô cũ vẫn tồn tại (setValue/setValue trong _sync) để không phá
        # code đang đọc nó, nhưng không hiện ra giao diện.
        self.sp_conc = QSpinBox()
        self.sp_conc.setRange(1, 500)
        self.sp_conc.setVisible(False)
        self.sp_retry = QSpinBox()
        self.sp_retry.setRange(0, 10)
        self.sp_retry.setVisible(False)
        self.in_region = QLineEdit()
        f.addRow("Region:", self.in_region)
        self.in_tz = QLineEdit()
        self.in_tz.setToolTip("Múi giờ phải khớp cookie, ví dụ Asia/Bangkok")
        f.addRow("Múi giờ:", self.in_tz)
        self.in_lang = QLineEdit()
        self.in_lang.setPlaceholderText("trống = tự đoán (cookie VN → vi-VN)")
        self.in_lang.setToolTip(
            "Ngôn ngữ phải khớp tài khoản. Cookie có store-country-code=vn\n"
            "thì app tự dùng vi-VN. Điền tay chỉ khi biết chắc."
        )
        f.addRow("Ngôn ngữ:", self.in_lang)
        self.in_signer = QLineEdit()
        self.in_signer.setVisible(False)   # tab Tác vụ đã có
        f.addRow("Sidecar ký:", self.in_signer)

        # Trễ ngẫu nhiên + xác minh like: chỉ ở tab Tác vụ (tránh trùng).
        d = QWidget()
        dh = QHBoxLayout(d)
        dh.setContentsMargins(0, 0, 0, 0)
        dh.setSpacing(4)
        d.setVisible(False)
        self.sp_dmin = QDoubleSpinBox()
        self.sp_dmax = QDoubleSpinBox()
        for sp in (self.sp_dmin, self.sp_dmax):
            sp.setRange(0, 600)
            sp.setSingleStep(0.5)
            sp.setSuffix(" s")
            sp.setFixedWidth(82)
        arr = QLabel("→")
        arr.setFixedWidth(14)
        arr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        arr.setProperty("role", "hint")
        dh.addWidget(self.sp_dmin)
        dh.addWidget(arr)
        dh.addWidget(self.sp_dmax)
        dh.addStretch(1)
        f.addRow("Trễ ngẫu nhiên:", d)

        self.cb_verify = QCheckBox("Xác minh số like sau khi thả tim")
        self.cb_verify.setVisible(False)   # tab Tác vụ đã có
        f.addRow("", self.cb_verify)
        self.cb_rotate = QCheckBox("Tự đổi proxy khi bị chặn IP")
        self.cb_rotate.setToolTip(
            "Khi TikTok trả mã lỗi liên quan IP (8, 10202, 10221…) thì\n"
            "đổi sang proxy tiếp theo và thử lại."
        )
        f.addRow("", self.cb_rotate)
        self.cb_autochk = QCheckBox("Kiểm tra proxy lúc mở app")
        f.addRow("", self.cb_autochk)

        b_check = QPushButton("Kiểm tra toàn bộ proxy")
        b_check.clicked.connect(self._on_check)
        f.addRow("", b_check)
        return w

    @Slot()
    def _on_detect_system(self) -> None:
        from core.proxy import detect_system_proxy

        url, source = detect_system_proxy()
        if url:
            self.in_sys.setText(url)
            self.lbl_sys.setText(f"✔ Phát hiện từ {source}: {url}")
            self.log.emit(f"Proxy hệ thống ({source}): {url}", "ok")
        else:
            self.in_sys.clear()
            self.lbl_sys.setText(
                "Không phát hiện được proxy hệ thống (WinINET / scutil / "
                "gsettings / biến môi trường đều trống)."
            )
            self.log.emit("Không tìm thấy proxy hệ thống.", "warn")

    # ------------------------------------------------------------------ #
    def _build_source(self) -> QWidget:
        gb = QGroupBox("Nguồn proxy  (1 dòng = 1 proxy)")
        v = QVBoxLayout(gb)

        fmt = QLabel(
            "Định dạng nhận được:\n"
            "<code>ip:port</code> · <code>ip:port:user:pass</code> · "
            "<code>user:pass@ip:port</code> · <code>socks5://ip:port</code><br>"
            "Dòng bắt đầu bằng <code>#</code> sẽ bị bỏ qua."
        )
        fmt.setStyleSheet("color:#5f6b7a;font-size:11px;")
        fmt.setWordWrap(True)
        fmt.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(fmt)

        self.txt_proxy = QTextEdit()
        self.txt_proxy.setPlaceholderText(
            "1.2.3.4:8080\n1.2.3.4:8080:userA:passA\nuserB:passB@5.6.7.8:1080"
        )
        self.txt_proxy.setStyleSheet("font-family:Consolas,monospace;font-size:11px;")
        # không cho khung nguồn co giãn theo nội dung, giữ nguyên chiều cao
        self.txt_proxy.setSizePolicy(QSizePolicy.Policy.Expanding,
                                     QSizePolicy.Policy.Expanding)
        v.addWidget(self.txt_proxy, 1)

        h = QHBoxLayout()
        b1 = QPushButton("Lưu & phân phối")
        b1.setObjectName("primary")
        b1.clicked.connect(self._on_apply)
        b2 = QPushButton("Nạp từ file")
        b2.clicked.connect(self._on_import)
        b3 = QPushButton("Xoá tất cả")
        b3.setObjectName("ghost")
        b3.clicked.connect(self._on_clear)
        for b in (b1, b2, b3):
            h.addWidget(b)
        v.addLayout(h)

        self.cb_mode = QComboBox()
        for key, label in MODE_LABELS.items():
            self.cb_mode.addItem(label, key)
        self.cb_mode.currentIndexChanged.connect(self._on_mode_changed)
        v.addSpacing(4)
        lbl = QLabel("Cách gán proxy cho từng account")
        lbl.setProperty("role", "hint")
        v.addWidget(lbl)
        v.addWidget(self.cb_mode)
        return gb

    # ------------------------------------------------------------------ #
    def _build_gateway(self) -> QWidget:
        gb = QGroupBox("Cổng VPN Express  (xoay IP, 1 cổng cho mọi account)")
        v = QVBoxLayout(gb)

        self.cb_gw = QCheckBox("Dùng chế độ cổng (mỗi account 1 session riêng)")
        v.addWidget(self.cb_gw)

        f = QFormLayout()
        self.in_gw_host = QLineEdit()
        self.in_gw_host.setPlaceholderText("gate.vpnexpress.net")
        f.addRow("Host cổng:", self.in_gw_host)
        self.in_gw_port = QSpinBox()
        self.in_gw_port.setRange(1, 65535)
        f.addRow("Cổng:", self.in_gw_port)
        self.in_gw_user = QLineEdit()
        self.in_gw_user.setPlaceholderText("tên đăng nhập VPN Express")
        f.addRow("Username:", self.in_gw_user)
        self.in_gw_pass = QLineEdit()
        self.in_gw_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.in_gw_pass.setPlaceholderText("mật khẩu")
        f.addRow("Password:", self.in_gw_pass)
        self.in_gw_cc = QLineEdit()
        self.in_gw_cc.setMaxLength(8)
        f.addRow("Mã nước:", self.in_gw_cc)
        self.in_gw_tpl = QLineEdit()
        self.in_gw_tpl.setStyleSheet("font-family:Consolas,monospace;font-size:10px;")
        f.addRow("Mẫu URL:", self.in_gw_tpl)
        v.addLayout(f)

        hint = QLabel(
            "Mẫu URL dùng các biến: <b>{user}</b> <b>{pass}</b> <b>{host}</b> "
            "<b>{port}</b> <b>{country}</b> <b>{session}</b><br>"
            "Mỗi account được cấp một <b>session</b> khác nhau → mỗi account "
            "giữ một IP riêng, ổn định giữa các lần chạy.<br>"
            "Khi bị chặn IP, app sẽ cấp session mới cho account đó."
        )
        hint.setStyleSheet("color:#5f6b7a;font-size:11px;")
        hint.setWordWrap(True)
        v.addWidget(hint)
        v.addStretch(1)
        return gb

    # ------------------------------------------------------------------ #
    # ------------------------------------------------------------------ #
    def set_accounts(self, accounts: list) -> None:
        """Nạp danh sách account để biết đang gán proxy cho ai."""
        self._accounts = accounts

    # ---- đồng bộ 2 chiều ---------------------------------------------- #
    def _sync_from_settings(self) -> None:
        s = self.settings
        self.txt_proxy.setPlainText(s.proxy_text)
        i = self.cb_mode.findData(s.proxy_mode)
        self.cb_mode.setCurrentIndex(max(0, i))
        self.in_gw_host.setText(s.gw_host)
        self.in_gw_port.setValue(s.gw_port)
        self.in_gw_user.setText(s.gw_user)
        self.in_gw_pass.setText(s.gw_pass)
        self.in_gw_cc.setText(s.gw_country)
        self.in_gw_tpl.setText(s.gw_template)
        self.cb_gw.setChecked(s.gw_enabled)
        self.sp_conc.setValue(s.concurrency)
        self.sp_retry.setValue(s.retries)
        self.in_region.setText(s.region)
        self.in_tz.setText(s.timezone)
        self.in_lang.setText(s.language)
        self.in_signer.setText(s.signer_url)
        self.sp_dmin.setValue(s.delay_min)
        self.sp_dmax.setValue(s.delay_max)
        self.cb_verify.setChecked(s.verify)
        self.cb_rotate.setChecked(s.rotate_on_block)
        self.cb_autochk.setChecked(s.proxy_auto_check)
        self.cb_sys.setChecked(s.use_system_proxy)
        self.in_sys.setText(s.system_proxy)
        if s.system_proxy:
            self.lbl_sys.setText(f"✔ Đang dùng: {s.system_proxy}")
        else:
            self._on_detect_system()
        self._update_pool_label()

    def _sync_to_settings(self) -> None:
        s = self.settings
        s.proxy_text = self.txt_proxy.toPlainText()
        s.proxy_mode = self.cb_mode.currentData()
        s.gw_host = self.in_gw_host.text().strip()
        s.gw_port = self.in_gw_port.value()
        s.gw_user = self.in_gw_user.text().strip()
        s.gw_pass = self.in_gw_pass.text()
        s.gw_country = self.in_gw_cc.text().strip() or "vn"
        s.gw_template = self.in_gw_tpl.text().strip()
        s.gw_enabled = self.cb_gw.isChecked()
        s.concurrency = self.sp_conc.value()
        s.retries = self.sp_retry.value()
        s.region = self.in_region.text().strip() or "VN"
        s.timezone = self.in_tz.text().strip() or "Asia/Bangkok"
        s.language = self.in_lang.text().strip()
        s.signer_url = self.in_signer.text().strip()
        s.delay_min = self.sp_dmin.value()
        s.delay_max = self.sp_dmax.value()
        s.verify = self.cb_verify.isChecked()
        s.rotate_on_block = self.cb_rotate.isChecked()
        s.proxy_auto_check = self.cb_autochk.isChecked()
        s.use_system_proxy = self.cb_sys.isChecked()
        s.system_proxy = self.in_sys.text().strip()

    # ---- hành động ----------------------------------------------------- #
    @Slot()
    def _on_apply(self) -> None:
        self._sync_to_settings()
        # chế độ cổng không dùng danh sách dòng -> không xoá danh sách đã lưu
        is_gw = self.pool.mode == MODE_GATEWAY
        if not is_gw:
            n, bad = self.pool.load(self.settings.proxy_text)
        else:
            n, bad = self.pool.count(), []
        self.settings.apply_to_pool(self.pool)
        self.model.reload()
        self._update_pool_label()

        if bad:
            self.log.emit(
                f"{len(bad)} dòng không đọc được (bỏ qua): {bad[:3]}", "warn"
            )
        if n:
            st = self.pool.assign(self._accounts) if self._accounts else {"assigned": 0}
            self.log.emit(
                f"Đã nạp {n} proxy · chế độ {self.pool.mode} · "
                f"gán cho {st.get('assigned', 0)} account",
                "ok",
            )
            self.proxies_ready.emit(n)
        else:
            self.log.emit("Không có proxy nào đọc được.", "warn")
        self.settings_changed.emit()

    @Slot()
    def _on_clear(self) -> None:
        self.txt_proxy.clear()
        self.pool.clear()
        self.model.reload()
        self._update_pool_label()
        if self._accounts:
            self.pool.unassign(self._accounts)
        self.log.emit("Đã xoá toàn bộ proxy.", "info")
        self.settings_changed.emit()

    @Slot()
    def _on_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Nạp danh sách proxy", ".", "Text (*.txt *.list *.csv);;All (*)"
        )
        if not path:
            return
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        self.txt_proxy.setPlainText(text)
        self._on_apply()

    @Slot()
    def _on_mode_changed(self) -> None:
        is_gw = self.cb_mode.currentData() == MODE_GATEWAY
        self.cb_gw.setChecked(is_gw)
        self.txt_proxy.setEnabled(not is_gw)
        # cập nhật pool ngay để xem trạng thái khớp với lựa chọn
        self.pool.mode = self.cb_mode.currentData()
        self.pool.gateway.enabled = is_gw
        if is_gw:
            if not self.pool.gateway.user:
                self.log.emit(
                    "Chế độ cổng: mỗi account được cấp 1 session riêng. "
                    "Cần điền Username/Password của VPN Express rồi bấm "
                    "'Lưu & phân phối'.", "info",
                )
            else:
                st = self.pool.assign(self._accounts) if self._accounts else {}
                self.log.emit(
                    f"Chuyển sang cổng · đã cấp session cho "
                    f"{st.get('assigned', 0)} account", "ok",
                )
                self.proxies_ready.emit(self.pool.count())

    @Slot()
    def _on_check(self) -> None:
        if self._checking:
            return
        items = self.pool.enabled_items()
        if not items:
            self.log.emit("Chưa có proxy nào để kiểm tra.", "warn")
            return
        self._checking = True
        self._sync_to_settings()
        self.log.emit(f"Đang kiểm tra {len(items)} proxy...", "info")

        def work() -> None:
            def on_done(done, total, p):
                self._safe(lambda: self.model.reload())
                if p.ok:
                    self.log.emit(
                        f"[{done}/{total}] ✔ {p.label} · {p.exit_ip} "
                        f"{p.country} · {p.latency_ms}ms", "ok",
                    )
                else:
                    self.log.emit(
                        f"[{done}/{total}] ✖ {p.label} · {p.err[:70]}", "err",
                    )

            check_many(self.pool, workers=10,
                       timeout=self.settings.proxy_check_timeout, on_done=on_done)
            self._safe(self._check_done)

        threading.Thread(target=work, daemon=True).start()

    def _check_done(self) -> None:
        self._checking = False
        ok = sum(1 for p in self.pool.items if p.ok)
        tot = len(self.pool.items)
        self.log.emit(f"Kiểm tra xong: {ok}/{tot} proxy sống.", "ok")
        self._update_pool_label()

    # ---- tiện ích ------------------------------------------------------ #
    @staticmethod
    def _safe(fn) -> None:
        """Đưa callback từ thread nền về GUI thread rồi mới chạy."""
        call_on_gui(fn)

    def _update_pool_label(self) -> None:
        items = self.pool.items
        if not items:
            self.lbl_pool.setText("Chưa có proxy nào. Nhập ở ô bên trái rồi bấm 'Lưu & phân phối'.")
            return
        ok = sum(1 for p in items if p.ok)
        checked = sum(1 for p in items if p.ok is not None)
        txt = f"{len(items)} proxy · {len(self.pool.enabled_items())} đang bật"
        if checked:
            txt += f" · đã kiểm tra {checked}, sống {ok}"
        self.lbl_pool.setText(txt)

"""Đồng hồ tốc độ trực tiếp: acc/s, tiến độ, thời gian còn lại, biểu đồ.

Vì sao cần: tốc độ thật của một lượt chạy phụ thuộc mạng và sidecar ký, mỗi
lần mỗi khác. Không có đồng hồ thì người dùng chỉ biết "đang chạy" rồi đợi,
dễ tưởng treo. Có số liệu thì thấy rõ hệ thống đang đi và còn bao lâu.
"""

from __future__ import annotations

import time
from collections import deque

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QFrame, QSizePolicy, QWidget

from .style import FS_BASE, FS_SMALL, FS_TINY

OK_C = QColor("#1a8a4e")
RUN_C = QColor("#1e5eb8")
IDLE_C = QColor("#8a95a1")
WARN_C = QColor("#c77800")
GRID_C = QColor("#e8edf2")


def fmt_duration(seconds: float | None) -> str:
    """Định dạng thời gian ngắn gọn: 45s · 1m 02s · 1h 05m."""
    if seconds is None or seconds < 0:
        return "—"
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s"
    return f"{s // 3600}h {(s % 3600) // 60:02d}m"


class Sparkline(QWidget):
    """Biểu đồ cột nhỏ: số tài khoản hoàn thành mỗi giây."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(22)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._data: deque = deque(maxlen=40)

    def push(self, value: int) -> None:
        self._data.append(value)
        self.update()

    def clear(self) -> None:
        self._data.clear()
        self.update()

    def peak(self) -> int:
        return max(self._data) if self._data else 0

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = self.rect().adjusted(0, 2, 0, -1)

        # đường lưới
        p.setPen(QPen(GRID_C, 1))
        for i in (1, 2):
            y = r.top() + r.height() * i / 3
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))

        n = len(self._data)
        if not n:
            p.setPen(QPen(IDLE_C, 1))
            f = QFont()
            f.setPixelSize(FS_TINY)
            p.setFont(f)
            p.drawText(r, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       "chưa có dữ liệu")
            p.end()
            return

        peak = max(max(self._data), 1)
        w = r.width() / max(len(self._data), 1)
        bw = max(1.0, w - 1.5)
        for i, v in enumerate(self._data):
            h = (v / peak) * (r.height() - 1)
            x = r.left() + i * w
            # cột gần nhất đậm hơn -> mắt bám theo nhịp
            col = RUN_C if i >= n - 3 else QColor("#7fb0e0")
            p.fillRect(QRectF(x, r.bottom() - h, bw, h), col)
        p.end()


class ThroughputMeter(QFrame):
    """Ô đo: tốc độ, tiến độ, ETA, biểu đồ, và tình trạng nút thắt."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("role", "card")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        # 42px thay vì 52px: ô này nằm trên thanh công cụ, mỗi px giảm ở đây
        # là 1px thêm cho bảng — và bảng cần đủ chỗ cho 50 dòng.
        self.setFixedHeight(42)

        self._total = 0
        self._done = 0
        self._ok = 0
        self._fail = 0
        self._t0 = 0.0
        self._frozen = False
        self._stamps: deque = deque()      # mốc thời gian hoàn thành (giây)
        self._spark = Sparkline(self)
        self._rate = 0.0                   # acc/s cửa sổ trượt
        self._avg = 0.0
        self._eta: float | None = None
        self._threads = 0
        self._queue = 0                    # hàng đợi của sidecar ký
        self._sigs = 0                     # tổng chữ ký sidecar đã sinh
        self._live = False
        self._phase = 1

    # ------------------------------------------------------------------ #
    def _rate_display(self) -> tuple[str, QColor]:
        """Khi chạy dùng tốc độ cửa sổ trượt (phản ánh nhịp hiện tại);
        khi xong dùng tốc độ trung bình cả lượt (ổn định hơn vì lúc đó đã
        ngừng tăng, cửa sổ trượt sẽ rơi về 0 và nhìn như bị nghẽn)."""
        if not self._done:
            return "—", IDLE_C
        if self._frozen:
            return f"{self._avg:.1f}", OK_C
        if self._rate >= 0.05:
            return f"{self._rate:.1f}", RUN_C
        return f"{self._avg:.1f}", RUN_C

    # ---- vòng đời ----------------------------------------------------- #
    def start(self, total: int, threads: int) -> None:
        self._total = total
        self._done = self._ok = self._fail = 0
        self._t0 = time.perf_counter()
        self._frozen = False
        self._live = True
        self._threads = threads
        self._stamps.clear()
        self._spark.clear()
        self._rate = self._avg = 0.0
        self._eta = None
        self.update()

    def add_done(self, ok: bool = True) -> None:
        if self._frozen:
            return
        self._done += 1
        if ok:
            self._ok += 1
        else:
            self._fail += 1
        self._stamps.append(time.perf_counter())

    def stop(self) -> None:
        self._frozen = True
        self._live = False
        self.update()

    def set_signer(self, queue: int, sigs: int) -> None:
        self._queue = queue
        self._sigs = sigs
        self.update()

    # ---- cập nhật mỗi giây ------------------------------------------- #
    def tick(self) -> None:
        if self._frozen or not self._live:
            return
        now = time.perf_counter()
        window = 10.0
        while self._stamps and now - self._stamps[0] > window:
            self._stamps.popleft()
        self._rate = len(self._stamps) / window if self._stamps else 0.0

        elapsed = now - self._t0
        self._avg = self._done / elapsed if elapsed > 0 else 0.0

        left = self._total - self._done
        self._eta = (left / self._rate) if (left > 0 and self._rate > 0.01) else (
            0.0 if left <= 0 else None
        )
        self._spark.push(len(self._stamps))
        self.update()

    # ---- vẽ ----------------------------------------------------------- #
    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = self.rect()

        p.setPen(QPen(QColor("#d3dce6"), 1))
        p.setBrush(QColor("#ffffff"))
        p.drawRoundedRect(r.adjusted(0, 0, -1, -1), 3, 3)

        pad = 8
        x = r.left() + pad
        y = r.top() + 4
        right = r.right() - pad

        # --- tốc độ lớn ---
        rate_txt, rate_col = self._rate_display()
        f_rate = QFont()
        f_rate.setPixelSize(16)
        f_rate.setBold(True)
        p.setFont(f_rate)
        p.setPen(rate_col)
        p.drawText(
            QRectF(x, y - 2, 120, 20),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            rate_txt,
        )

        f_small = QFont()
        f_small.setPixelSize(FS_SMALL)
        p.setFont(f_small)
        p.setPen(QColor("#8a95a1"))
        p.drawText(
            QRectF(x + 58, y, 80, 16),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            "tài khoản/giây",
        )

        # --- đếm hoàn thành + chấm sống ---
        f_base = QFont()
        f_base.setPixelSize(FS_SMALL)
        p.setFont(f_base)
        p.setPen(QColor("#1e2530"))
        p.drawText(
            QRectF(x, y + 13, 150, 15),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            f"{self._done:,} / {self._total:,}",
        )
        if self._live:
            # chấm nhịp để thấy hệ thống còn hoạt động, không phải treo
            self._phase = (self._phase + 1) % 3
            shade = (RUN_C, QColor("#6f9fd8"), QColor("#b6d0ec"))[self._phase]
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(shade)
            p.drawEllipse(QPointF(x + 88, y + 20), 3, 3)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(RUN_C)
            p.drawText(
                QRectF(x + 96, y + 13, 40, 15),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                "CHẠY",
            )

        # --- ETA + luồng ---
        p.setPen(QColor("#54606e"))
        if self._eta is not None:
            eta_txt = f"còn {fmt_duration(self._eta)}"
        elif self._total and self._done >= self._total:
            eta_txt = "xong"
        else:
            eta_txt = "còn —"
        p.drawText(
            QRectF(x, y + 27, 240, 14),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            f"{eta_txt}   ·   {self._threads} luồng   ·   "
            f"✔{self._ok}  ✖{self._fail}",
        )

        # --- biểu đồ bên phải ---
        spark = self._spark
        if spark.parent() is not self:
            spark.setParent(self)
        w = min(150, max(70, int(r.width() * 0.34)))
        spark.setGeometry(
            right - w, r.top() + 6, w, r.height() - 12
        )
        spark.show()

        # --- cảnh báo nút thắt ---
        if self._queue >= 3:
            p.setFont(f_small)
            p.setPen(WARN_C)
            p.drawText(
                QRectF(right - 165, r.bottom() - 14, 165, 13),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                f"sidecar xếp hàng {self._queue} · nút thắt",
            )
        p.end()

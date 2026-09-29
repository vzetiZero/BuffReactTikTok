"""Panel chi tiết phía dưới bảng: thông tin tài khoản + thẻ bài viết.

Bố cục lấy cảm hứng từ bảng quản lý kiểu admin: bên trái là thẻ video/bài
viết đang nhắm tới, bên phải là thẻ tài khoản được chọn.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPolygon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.models import ST_DONE, ST_FAIL, ST_OK, Account
from core.parser import video_url

OK_C = QColor("#1a8a4e")
FAIL_C = QColor("#c62828")


class VideoThumb(QWidget):
    """Ẩn chụp màn hình bài viết, vẽ tay phần khung + nút play."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(140, 180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._title = ""
        self._play = False

    def set_content(self, title: str, has_play: bool) -> None:
        self._title = title or ""
        self._play = has_play
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = self.rect().adjusted(1, 1, -1, -1)
        p.setPen(QColor("#c6d2de"))
        p.setBrush(QColor("#1b2430"))
        p.drawRoundedRect(r, 4, 4)

        if self._play:
            cx, cy = r.center().x(), r.center().y()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 50))
            p.drawEllipse(QRect(cx - 26, cy - 26, 52, 52))
            p.setBrush(QColor("#ffffff"))
            p.drawPolygon(
                QPolygon([QPoint(cx - 8, cy - 15),
                          QPoint(cx - 8, cy + 15),
                          QPoint(cx + 16, cy)])
            )

        p.setPen(QColor("#9fb3c8"))
        p.drawText(
            r.adjusted(10, 10, -10, -10),
            int(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft
                | Qt.TextFlag.TextWordWrap),
            self._title or "Chưa chọn bài viết",
        )
        p.end()


class InfoRow(QWidget):
    """Một dòng nhãn / giá trị."""

    def __init__(self, key: str, value: str = "—", parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 1, 0, 1)
        h.setSpacing(8)
        self.k = QLabel(key)
        self.k.setProperty("role", "k")
        self.k.setMinimumWidth(104)
        self.k.setMaximumWidth(104)
        self.v = QLabel(value)
        self.v.setProperty("role", "v")
        self.v.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.v.setWordWrap(True)
        h.addWidget(self.k)
        h.addWidget(self.v, 1)

    def set(self, value: str, color: str = "", wrap: bool = False) -> None:
        self.v.setText(str(value) if value not in ("", None) else "—")
        self.v.setToolTip(self.v.text())
        # `Ignored` cho chiều ngang: nhãn co lại theo giá trị, không ép thẻ rộng
        self.v.setWordWrap(wrap)
        self.v.setSizePolicy(QSizePolicy.Policy.Ignored,
                             QSizePolicy.Policy.Preferred)
        if color:
            self.v.setStyleSheet(f"color:{color};")


class AccountCard(QFrame):
    """Thẻ tài khoản được chọn trong bảng."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("role", "card")
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(5)

        t = QLabel("TÀI KHOẢN")
        t.setProperty("role", "h1")
        v.addWidget(t)

        self.r_user = InfoRow("Username")
        self.r_mail = InfoRow("Email")
        self.r_id = InfoRow("User ID")
        self.r_state = InfoRow("Trạng thái")
        self.r_proxy = InfoRow("Proxy")
        self.r_exp = InfoRow("Hết hạn cookie")
        self.r_note = InfoRow("Kết quả")
        for r in (self.r_user, self.r_mail, self.r_id, self.r_state,
                  self.r_proxy, self.r_exp, self.r_note):
            v.addWidget(r)

        v.addSpacing(6)
        t2 = QLabel("TÁC VỤ ĐANG CHỌN")
        t2.setProperty("role", "h1")
        v.addWidget(t2)
        self.r_mode = InfoRow("Chế độ")
        self.r_cid = InfoRow("Comment ID")
        self.r_aweme = InfoRow("aweme_id")
        self.r_thread = InfoRow("Số luồng")
        for r in (self.r_mode, self.r_cid, self.r_aweme, self.r_thread):
            v.addWidget(r)
        v.addStretch(1)

        self.set_account(None)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

    def set_account(self, acc: Account | None) -> None:
        if acc is None:
            for r in (self.r_user, self.r_mail, self.r_id, self.r_state,
                      self.r_proxy, self.r_exp, self.r_note):
                r.set("—")
            return
        self.r_user.set(acc.username)
        self.r_mail.set(acc.email)
        self.r_id.set(acc.id)
        color = OK_C.value() if acc.status in (ST_OK, ST_DONE) else (
            FAIL_C.value() if acc.status == ST_FAIL else "#54606e"
        )
        self.r_state.set(acc.status, color)
        self.r_proxy.set(acc.proxy_label or "(chưa gán — dùng IP máy)")
        self.r_exp.set(acc.expiry_hint() or "—")
        # kết quả dài (vd "♥ cid=… · like 244 → 245") -> cho xuống dòng,
        # nếu không sẽ đẩy các dòng bên dưới xuống và làm thẻ méo mó
        # kết quả dài (vd "♥ cid=… · like 244 → 245") -> cắt gọn 1 dòng,
        # giá trị đầy đủ nằm trong tooltip
        note = acc.note or "—"
        self.r_note.set(self._ellipsis(note, 46), wrap=False)

    @staticmethod
    def _ellipsis(text: str, limit: int) -> str:
        t = (text or "").replace("\n", " ").strip()
        return t if len(t) <= limit else t[: limit - 1] + "…"

    def set_task(self, mode: str, cid: str, aweme: str, threads: int) -> None:
        self.r_mode.set(self._ellipsis(mode, 46))
        self.r_cid.set(cid or "—")
        self.r_aweme.set(aweme or "—")
        self.r_thread.set(f"{threads} luồng")


class SummaryCard(QFrame):
    """Thống kê toàn bộ danh sách + kết quả lượt chạy gần nhất."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("role", "card")
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(5)

        t = QLabel("TỔNG QUAN")
        t.setProperty("role", "h1")
        v.addWidget(t)

        self.r_total = InfoRow("Tổng tài khoản")
        self.r_pick = InfoRow("Đã tick")
        self.r_sess = InfoRow("Còn phiên")
        self.r_proxy = InfoRow("Có proxy riêng")
        self.r_ok = InfoRow("Thành công")
        self.r_fail = InfoRow("Bị lỗi")
        self.r_run = InfoRow("Lượt chạy")
        for r in (self.r_total, self.r_pick, self.r_sess, self.r_proxy,
                  self.r_ok, self.r_fail, self.r_run):
            v.addWidget(r)
        v.addStretch(1)
        self.set_stats({})

    def set_stats(self, s: dict) -> None:
        g = s.get
        self.r_total.set(str(g("total", 0)))
        self.r_pick.set(str(g("selected", 0)))
        self.r_sess.set(str(g("has_session", 0)))
        self.r_proxy.set(str(g("proxied", 0)))
        self.r_ok.set(str(g("ok", 0)), OK_C.value())
        n_fail = g("fail", 0)
        self.r_fail.set(str(n_fail), FAIL_C.value() if n_fail else "")
        self.r_run.set(g("last_run", "—"))


class DetailPanel(QWidget):
    """Toàn bộ vùng dưới: video + tài khoản + log."""

    log_msg = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        top = QWidget()
        h = QHBoxLayout(top)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        # --- cột trái: bài viết ---
        left = QFrame()
        left.setProperty("role", "card")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(12, 10, 12, 10)
        lv.setSpacing(8)
        t = QLabel("BÀI VIẾT ĐANG NHẮM TỚI")
        t.setProperty("role", "h1")
        lv.addWidget(t)
        self.thumb = VideoThumb()
        self.thumb.setSizePolicy(QSizePolicy.Policy.Expanding,
                                 QSizePolicy.Policy.Expanding)
        lv.addWidget(self.thumb, 1)
        self.lbl_url = QLabel("—")
        self.lbl_url.setProperty("role", "k")
        self.lbl_url.setWordWrap(True)
        lv.addWidget(self.lbl_url)
        # thẻ bài viết chỉ chiếm phần vừa đủ; dư chỗ để thẻ tài khoản
        left.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Expanding)
        left.setMinimumWidth(268)
        left.setMaximumWidth(300)
        h.addWidget(left)

        # --- cột phải: tài khoản ---
        # thẻ tài khoản: chiều ngang co giãn theo nội dung dài nhất,
        # trừ hao khoảng trống của thẻ bài viết
        self.card = AccountCard()
        self.card.setMinimumWidth(300)
        self.card.setSizePolicy(QSizePolicy.Policy.Expanding,
                                QSizePolicy.Policy.Maximum)
        h.addWidget(self.card, 3)

        # cột tổng quan: thống kê cả lượt chạy, tận dụng phần trống
        self.summary = SummaryCard()
        self.summary.setMinimumWidth(250)
        h.addWidget(self.summary, 2)

        root.addWidget(top, 1)

    def set_video(self, url: str, aweme: str, cid: str) -> None:
        if not url:
            self.thumb.set_content("Chưa nhập bài viết", False)
            self.lbl_url.setText("—")
            self.lbl_url.setToolTip("")
            return
        self.thumb.set_content(aweme or "", True)
        # nhãn bị cắt cụt khi thẻ hẹp -> đặt tooltip giữ đủ địa chỉ
        self.lbl_url.setText(url)
        self.lbl_url.setToolTip(url)

    def set_task(self, mode: str, cid: str, aweme: str, threads: int) -> None:
        self.card.set_task(mode, cid, aweme, threads)

    def set_account(self, acc: Account | None) -> None:
        self.card.set_account(acc)

    def set_stats(self, stats: dict) -> None:
        self.summary.set_stats(stats)

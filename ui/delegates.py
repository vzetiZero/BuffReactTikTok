"""Delegate vẽ 2 cột A/B: số thứ tự + ô tick + 2 dòng ở cột A,
trạng thái + ghi chú ở cột B.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionButton,
)

from core.models import (
    HAS_SESSION_ROLE,
    HC_ALIVE,
    HC_CHECKING,
    HC_DEAD,
    HC_EXPIRED,
    HC_RISKY,
    HC_UNKNOWN,
    HEALTH_ROLE,
    NO_ROLE,
    ST_DONE,
    ST_FAIL,
    ST_OK,
    ST_RUNNING,
    ST_SKIP,
    AccountTableModel,
)

NUM_W = 32      # bề ngang cột số thứ tự
BOX_W = 15
PAD = 3
# Chiều cao dòng.
#   14 → 1 dòng chữ, 50 dòng = 700px, VỪA KHÍT trên màn 1080p khi mở to
#         (đo thật: giao diện xung quanh ~230px, còn ~770px cho bảng).
#   44 → 2 dòng chữ (username + email tách dòng), dễ đọc, chỉ ~16 dòng/trang.
ROW_H = 14
ROW_H_TALL = 44
FS_MAIN = 8     # point — dòng chính
FS_SUB = 7      # point — email (chỉ dùng ở chế độ cao)
FS_NUM = 7      # point — số thứ tự

ACC_FG = QColor("#1f2d3d")
ACC_SUB = QColor("#6b7c93")
NUM_FG = QColor("#93a1b3")
NUM_BG = QColor("#eef2f7")
C_FAIL = QColor("#e74c3c")
C_OK = QColor("#1e9e5a")
C_RUN = QColor("#e08b0a")
C_SKIP = QColor("#8a94a6")
C_IDLE = QColor("#7a869a")
C_NOTE = QColor("#3b4a5f")
C_WARN = QColor("#d35400")

STATUS_COLOR = {
    ST_OK: C_OK,
    ST_DONE: C_OK,
    ST_FAIL: C_FAIL,
    ST_RUNNING: C_RUN,
    ST_SKIP: C_SKIP,
}

# Màu cột Status — xanh là dùng được, đỏ là chết, cam là hết hạn,
# vàng là "chưa biết" để không nhầm với chết.
C_H_ALIVE = QColor("#1e9e5a")
C_H_DEAD = QColor("#e74c3c")
C_H_EXPIRED = QColor("#d35400")
C_H_RISKY = QColor("#b8860b")
C_H_CHECK = QColor("#3d7dd8")
C_H_UNKNOWN = QColor("#9aa4b2")

HEALTH_COLORS = {
    HC_ALIVE: C_H_ALIVE,
    HC_DEAD: C_H_DEAD,
    HC_EXPIRED: C_H_EXPIRED,
    HC_RISKY: C_H_RISKY,
    HC_CHECKING: C_H_CHECK,
    HC_UNKNOWN: C_H_UNKNOWN,
}


class AccountCellDelegate(QStyledItemDelegate):
    """Vẽ tay: checkbox + username (đậm) + email (xám) trong cùng một ô.

    Hai mật độ:
      gọn (mặc định) — 1 dòng, cao 18px, vừa 50 dòng / trang. Username và
      email nằm CÙNG MỘT DÒNG (email xám sau username) nên vẫn thấy đủ
      thông tin mà vẫn nhỏ.
      cao            — 2 dòng, cao 44px, dễ đọc hơn khi cần.
    """

    def __init__(self, parent=None, compact: bool = True):
        super().__init__(parent)
        self.compact = compact

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        # `option` có thể là None khi Qt hỏi kích thước ngoài ngữ cảnh vẽ
        # (ví dụ resizeRowsToContents). Không chốt None vì sẽ vỡ ngay.
        w = option.rect.width() if option is not None else 200
        return QSize(w, self.row_h())

    def row_h(self) -> int:
        return ROW_H if self.compact else ROW_H_TALL

    @staticmethod
    def _text_area(rect: QRect, used_left: int) -> tuple[int, int]:
        """Trả (x, w) của vùng chữ trong ô.

        `used_left` = số px đã dùng từ mép trái của ô (ô tick, chấm tròn…),
        tính từ mép tráI của CHÍNH Ô — không phải toạ độ màn hình.

        Rất dễ sai ở đây: `rect.left()` là toạ độ tuyệt đối trên bảng. Nếu
        viết `w = rect.width() - rect.left() - ...` thì với cột 1, 2 (left
        = 520, 940…) w ra số ÂM, bị `max(20, …)` ép về 20px và mọi chữ hiện
        thành "...". Cột 0 (left = 0) thì vô hại nên lỗi này lọt qua im lặng
        khi bảng chỉ có 2 cột.
        """
        x = rect.left() + used_left
        w = max(20, rect.width() - used_left - PAD)
        return x, w

    # ------------------------------------------------------------------ #
    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._background(painter, option, index)
        col = index.column()
        if col == AccountTableModel.COL_ACCOUNT:
            self._paint_account(painter, option, index)
        elif col == AccountTableModel.COL_HEALTH:
            self._paint_health(painter, option, index)
        else:
            self._paint_status(painter, option, index)
        painter.restore()

    # ------------------------------------------------------------------ #
    def _paint_health(self, painter: QPainter, option, index) -> None:
        """Cột Status: chấm màu + nhãn ngắn.

        Vẽ bằng tay như 2 cột kia để giữ đúng 1 dòng ở chế độ gọn.
        """
        rect = option.rect
        health = index.data(HEALTH_ROLE)
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        color = HEALTH_COLORS.get(health, C_IDLE)
        h = rect.height()

        dot = 5 if self.compact else 7
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(
            QRect(rect.left() + PAD, rect.top() + (h - dot) // 2, dot, dot)
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)

        x, w = self._text_area(rect, PAD + dot + 5)

        f1 = QFont()
        f1.setPointSizeF(FS_MAIN)
        f1.setBold(True)
        fm1 = QFontMetrics(f1)
        note = index.data(Qt.ItemDataRole.ToolTipRole) or ""

        if self.compact:
            # 1 DÒNG: nhãn + chi tiết, nhãn bao giờ giữ nguyên (cắt chi tiết
            # trước) để luôn đọc được "Sống" / "Hết hạn" / "Die".
            label_w = fm1.horizontalAdvance(text)
            tail = note.strip() if note else ""
            f2 = QFont()
            f2.setPointSizeF(FS_SUB)
            fm2 = QFontMetrics(f2)
            tail_w = fm2.horizontalAdvance(tail) + 8 if tail else 0

            # Nếu cả hai không vừa, hy sinh chi tiết trước.
            if label_w + tail_w > w and label_w < w:
                tail_w = 0
            if label_w > w:
                text = fm1.elidedText(text, Qt.TextElideMode.ElideRight, w)
                label_w = w
                tail_w = 0

            painter.setFont(f1)
            painter.setPen(color)
            painter.drawText(
                QRect(x, rect.top(), label_w, h),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                text,
            )
            if tail and tail_w and label_w + 8 < w:
                painter.setFont(f2)
                painter.setPen(ACC_SUB)
                painter.drawText(
                    QRect(x + label_w + 8, rect.top(), w - label_w - 8, h),
                    int(Qt.AlignmentFlag.AlignLeft
                        | Qt.AlignmentFlag.AlignVCenter),
                    fm2.elidedText(tail, Qt.TextElideMode.ElideRight,
                                   w - label_w - 8),
                )
            return

        painter.setFont(f1)
        painter.setPen(color)
        painter.drawText(
            QRect(x, rect.top() + 3, w, 16),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            fm1.elidedText(text, Qt.TextElideMode.ElideRight, w),
        )
        if note:
            f2 = QFont()
            f2.setPointSizeF(FS_SUB)
            painter.setFont(f2)
            painter.setPen(C_NOTE)
            painter.drawText(
                QRect(x, rect.top() + 19, w, 16),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                QFontMetrics(f2).elidedText(note, Qt.TextElideMode.ElideRight, w),
            )

    # ------------------------------------------------------------------ #
    def _background(self, painter: QPainter, option, index) -> None:
        rect = option.rect
        if option.state & QStyle.StateFlag.State_Selected:
            bg = QColor("#d6e6f7")
        elif option.state & QStyle.StateFlag.State_MouseOver:
            bg = QColor("#f4f8fc")
        else:
            bg = QColor("#ffffff") if index.row() % 2 == 0 else QColor("#fafcfe")
        painter.fillRect(rect, bg)
        painter.setPen(QPen(QColor("#e3eaf2"), 1))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())

    # ------------------------------------------------------------------ #
    def _paint_account(self, painter: QPainter, option, index) -> None:
        rect = option.rect

        # --- số thứ tự (nền xám, cố định bề ngang để thẳng cột) ---
        painter.fillRect(QRect(rect.left(), rect.top(), NUM_W, rect.height()), NUM_BG)
        no = index.data(NO_ROLE)
        if no is not None:
            f = QFont()
            f.setPointSizeF(FS_NUM)
            f.setBold(True)
            painter.setFont(f)
            painter.setPen(NUM_FG)
            painter.drawText(
                QRect(rect.left(), rect.top(), NUM_W, rect.height()),
                int(Qt.AlignmentFlag.AlignCenter),
                str(no),
            )
        painter.setPen(QPen(QColor("#e3eaf2"), 1))
        painter.drawLine(
            QPoint(rect.left() + NUM_W, rect.top()),
            QPoint(rect.left() + NUM_W, rect.bottom()),
        )

        lines = (index.data(Qt.ItemDataRole.DisplayRole) or "").split("\n")
        name = lines[0] if lines else ""
        sub = lines[1] if len(lines) > 1 else ""
        ok_session = index.data(HAS_SESSION_ROLE) is not False

        # --- ô tick ---
        box = 11 if self.compact else 13
        checked = index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
        cb = QStyleOptionButton()
        cb.rect = QRect(
            rect.left() + NUM_W + PAD,
            rect.top() + (rect.height() - box) // 2,
            box, box,
        )
        cb.state = QStyle.StateFlag.State_Enabled
        cb.state |= QStyle.StateFlag.State_On if checked else QStyle.StateFlag.State_Off
        QApplication.style().drawControl(QStyle.ControlElement.CE_CheckBox, cb, painter)

        x, w = self._text_area(rect, NUM_W + PAD + BOX_W)
        h = rect.height()

        f1 = QFont()
        f1.setPointSizeF(FS_MAIN)
        f1.setBold(True)
        fm1 = QFontMetrics(f1)

        if self.compact:
            # 1 DÒNG: username đậm, email xám ngay sau, tự cắt bằng elide.
            # Vẽ username trước, đo bề rộng đã dùng, rồi mới vẽ email vào
            # khoảng còn lại — nếu vẽ cả hai bằng drawText(elide) chúng sẽ
            # đè lên nhau.
            name_w = fm1.horizontalAdvance(name)
            if name_w > w:
                name = fm1.elidedText(name, Qt.TextElideMode.ElideRight, w)
                name_w = w
            painter.setFont(f1)
            painter.setPen(ACC_FG if ok_session else C_WARN)
            painter.drawText(
                QRect(x, rect.top(), name_w, h),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                name,
            )
            if sub and name_w + 8 < w:
                f2 = QFont()
                f2.setPointSizeF(FS_SUB)
                painter.setFont(f2)
                painter.setPen(ACC_SUB)
                painter.drawText(
                    QRect(x + name_w + 8, rect.top(), w - name_w - 8, h),
                    int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                    QFontMetrics(f2).elidedText(sub, Qt.TextElideMode.ElideRight,
                                                w - name_w - 8),
                )
            return

        # 2 DÒNG: username trên, email dưới
        painter.setFont(f1)
        painter.setPen(ACC_FG)
        painter.drawText(
            QRect(x, rect.top() + 3, w, 16),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            fm1.elidedText(name, Qt.TextElideMode.ElideRight, w),
        )
        if sub:
            f2 = QFont()
            f2.setPointSizeF(FS_SUB)
            painter.setFont(f2)
            painter.setPen(ACC_SUB if ok_session else C_WARN)
            painter.drawText(
                QRect(x, rect.top() + 19, w, 16),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                QFontMetrics(f2).elidedText(sub, Qt.TextElideMode.ElideRight, w),
            )

    # ------------------------------------------------------------------ #
    def _paint_status(self, painter: QPainter, option, index) -> None:
        rect = option.rect
        status = index.data(Qt.ItemDataRole.DisplayRole) or ""
        note = index.data(Qt.ItemDataRole.ToolTipRole) or ""
        color = STATUS_COLOR.get(status, C_IDLE)

        painter.setPen(Qt.PenStyle.NoPen)
        dot = 5 if self.compact else 7
        top = rect.top() + (rect.height() - dot) // 2
        painter.setBrush(color)
        painter.drawEllipse(QRect(rect.left() + PAD, top, dot, dot))
        painter.setBrush(Qt.BrushStyle.NoBrush)

        x, w = self._text_area(rect, PAD + dot + 5)
        h = rect.height()

        f1 = QFont()
        f1.setPointSizeF(FS_MAIN)
        f1.setBold(True)
        fm1 = QFontMetrics(f1)

        if self.compact:
            # 1 DÒNG: trạng thái + ghi chú nối tiếp nhau.
            sw = fm1.horizontalAdvance(status)
            if sw > w:
                status = fm1.elidedText(status, Qt.TextElideMode.ElideRight, w)
                sw = w
            painter.setFont(f1)
            painter.setPen(color)
            painter.drawText(
                QRect(x, rect.top(), sw, h),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                status,
            )
            if note and sw + 8 < w:
                f2 = QFont()
                f2.setPointSizeF(FS_SUB)
                painter.setFont(f2)
                painter.setPen(C_NOTE)
                painter.drawText(
                    QRect(x + sw + 8, rect.top(), w - sw - 8, h),
                    int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                    QFontMetrics(f2).elidedText(note, Qt.TextElideMode.ElideRight,
                                                w - sw - 8),
                )
            return

        # 2 DÒNG
        painter.setFont(f1)
        painter.setPen(color)
        painter.drawText(
            QRect(x, rect.top() + 3, w, 16),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            fm1.elidedText(status, Qt.TextElideMode.ElideRight, w),
        )
        if note:
            f2 = QFont()
            f2.setPointSizeF(FS_SUB)
            painter.setFont(f2)
            painter.setPen(C_NOTE)
            painter.drawText(
                QRect(x, rect.top() + 19, w, 16),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                QFontMetrics(f2).elidedText(note, Qt.TextElideMode.ElideRight, w),
            )

    # ------------------------------------------------------------------ #
    def editorEvent(self, event, model, option, index) -> bool:  # noqa: N802
        """Bấm vào ô tick để bật/tắt tài khoản."""
        if index.column() != AccountTableModel.COL_ACCOUNT:
            return False
        if event.type() == QEvent.Type.MouseButtonRelease:
            cur = index.data(Qt.ItemDataRole.CheckStateRole)
            new = (Qt.CheckState.Unchecked
                   if cur == Qt.CheckState.Checked else Qt.CheckState.Checked)
            model.setData(index, new, Qt.ItemDataRole.CheckStateRole)
            return True
        if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseMove):
            return True
        return False

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
    NO_ROLE,
    ST_DONE,
    ST_FAIL,
    ST_OK,
    ST_RUNNING,
    ST_SKIP,
    AccountTableModel,
)

NUM_W = 38      # bề ngang cột số thứ tự
BOX_W = 22
PAD = 6
ROW_H = 44
FS_MAIN = 9     # point — dòng chính
FS_SUB = 8      # point — dòng phụ (email / ghi chú)
FS_NUM = 8      # point — số thứ tự

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


class AccountCellDelegate(QStyledItemDelegate):
    """Vẽ tay: checkbox + username (đậm) + email (xám) trong cùng một ô."""

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(option.rect.width(), ROW_H)

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._background(painter, option, index)
        if index.column() == AccountTableModel.COL_ACCOUNT:
            self._paint_account(painter, option, index)
        else:
            self._paint_status(painter, option, index)
        painter.restore()

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

        # --- ô tick ---
        checked = index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
        cb = QStyleOptionButton()
        cb.rect = QRect(
            rect.left() + NUM_W + PAD,
            rect.top() + (rect.height() - 13) // 2,
            13, 13,
        )
        cb.state = QStyle.StateFlag.State_Enabled
        cb.state |= QStyle.StateFlag.State_On if checked else QStyle.StateFlag.State_Off
        QApplication.style().drawControl(QStyle.ControlElement.CE_CheckBox, cb, painter)

        x = rect.left() + NUM_W + PAD + BOX_W
        w = max(20, rect.width() - x - PAD)

        f1 = QFont()
        f1.setPointSizeF(FS_MAIN)
        f1.setBold(True)
        painter.setFont(f1)
        painter.setPen(ACC_FG)
        painter.drawText(
            QRect(x, rect.top() + 3, w, 16),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            QFontMetrics(f1).elidedText(lines[0] if lines else "",
                                        Qt.TextElideMode.ElideRight, w),
        )

        if len(lines) > 1:
            f2 = QFont()
            f2.setPointSizeF(FS_SUB)
            painter.setFont(f2)
            ok_session = index.data(HAS_SESSION_ROLE) is not False
            painter.setPen(ACC_SUB if ok_session else C_WARN)
            painter.drawText(
                QRect(x, rect.top() + 19, w, 16),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                QFontMetrics(f2).elidedText(lines[1], Qt.TextElideMode.ElideRight, w),
            )

    # ------------------------------------------------------------------ #
    def _paint_status(self, painter: QPainter, option, index) -> None:
        rect = option.rect
        status = index.data(Qt.ItemDataRole.DisplayRole) or ""
        note = index.data(Qt.ItemDataRole.ToolTipRole) or ""
        color = STATUS_COLOR.get(status, C_IDLE)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(QRect(rect.left() + PAD, rect.top() + 8, 7, 7))
        painter.setBrush(Qt.BrushStyle.NoBrush)

        x = rect.left() + PAD + 16
        w = max(20, rect.width() - x - PAD)

        f1 = QFont()
        f1.setPointSizeF(FS_MAIN)
        f1.setBold(True)
        painter.setFont(f1)
        painter.setPen(color)
        painter.drawText(
            QRect(x, rect.top() + 3, w, 16),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            QFontMetrics(f1).elidedText(status, Qt.TextElideMode.ElideRight, w),
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

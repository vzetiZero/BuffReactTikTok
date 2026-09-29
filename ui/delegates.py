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
        # toạ độ bảng, do MainWindow đẩy vào qua sync_geometry() —
        # delegate tự vẽ nên không có sẵn rect của từng ô như view.
        self._view_origin = QPoint(0, 0)
        self._view_width = 200
        self._col_offset = None
        # trạng thái đang quét chuột: dòng bắt đầu, dòng hiện tại, và
        # trạng thái đang áp (tick hay bỏ tick). None = không quét.
        self._sweep_from: int | None = None
        self._sweep_to: int | None = None
        self._sweep_on = False
        self._sweep_model = None

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        # `option` có thể là None khi Qt hỏi kích thước ngoài ngữ cảnh vẽ
        # (ví dụ resizeRowsToContents). Không chốt None vì sẽ vỡ ngay.
        w = option.rect.width() if option is not None else 200
        return QSize(w, self.row_h())

    def row_h(self) -> int:
        return ROW_H if self.compact else ROW_H_TALL

    def box_rect(self, row: int, col: int) -> QRect:
        """Hình chữ nhật của Ô TICK ở cột A, tính cùng công thức với lúc vẽ.

        Tách riêng ra để hai nơi dùng CHUNG một nguồn: paint() vẽ, còn
        editorEvent() cần biết chuột có nằm trong ô hay không. Nếu mỗi
        bên tự tính, rất dễ lệch 1-2px và bấm vào ô mà không ăn.
        """
        rect = self._cell_rect(row, col)
        box = 11 if self.compact else 13
        return QRect(
            rect.left() + NUM_W + PAD,
            rect.top() + (rect.height() - box) // 2,
            box, box,
        )

    def _cell_rect(self, row: int, col: int) -> QRect:
        rect = QRect(
            self._view_origin.x(),
            self._view_origin.y() + row * self.row_h(),
            self._view_width,
            self.row_h(),
        )
        if col:
            rect.moveLeft(self._view_origin.x() + self._col_x(col))
        return rect

    def sync_geometry(self, origin: QPoint, width: int,
                      col_x: "callable | None" = None) -> None:
        """Cập nhật toạ độ bảng để box_rect() trả về đúng vị trí thật."""
        self._view_origin = QPoint(origin)
        self._view_width = width
        self._col_offset = col_x

    def _col_x(self, col: int) -> int:
        return self._col_offset(col) if self._col_offset else 0

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
        # Dùng CHUNG box_rect() với editorEvent() để bấm chuột trúng ô
        # vẽ ra, không lệch vài px.
        checked = index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
        cb = QStyleOptionButton()
        cb.rect = self.box_rect(index.row(), index.column())
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
        """O TICK o cot A: bam de bat/tat, KEO de quet hang loat.

        Ba vung phai phan biet, neu khong se nuot moi cu bam o cot A:

          1. o tick           -> bam: bat/tat 1 tai khoan
                                keo:  quet dai dong (tick/bo tick ca loat)
          2. phan chu, so STT -> chon dong; chuot phai phai mo duoc menu
          3. cot B, C          -> khong dung, tra False

        CANH BAO VE `MouseButtonRelease`: KHONG bao gio dua vao no.
        Do that: QTableView chi chuyen MouseButtonRelease xuong delegate
        khi bang tu nhan thao tac keo-chon. Ta tra True cho
        MouseButtonPress nen Qt giu release lai -- delegate khong he
        thay no. Ban cu cho release de ket thuc quet, nen sau mot lan
        quet trang thai "dang quet" con treo: chi can RE chuot qua o
        tick la dong khac bi tick/bo tick nham, thay vi bam dung 1 cai.
        Nay ket thuc quet do `end_sweep()`, goi tu event filter tren
        viewport -- noi nhan duoc release that.
        """
        if index.column() != AccountTableModel.COL_ACCOUNT:
            return False

        et = event.type()

        # Chuot phai / giua: KHONG dung -- de bang mo menu ngu canh.
        # Phai kiem ca ca MouseButtonPress, vi neu nuot press thi bang
        # khong bao hieu chuot phai va menu khong bao gio hien.
        if et in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick):
            if event.button() != Qt.MouseButton.LeftButton:
                return False
            if not self._in_box(event, index):
                return False
            # Bat dau quet: dao trang thai dong nay truoc. Keo se ap
            # DUNG trang thai vua dao cho moi dong quet qua -- giong
            # quet o trong Excel.
            want = not (index.data(Qt.ItemDataRole.CheckStateRole)
                        == Qt.CheckState.Checked)
            model.setData(index, Qt.CheckState.Checked if want
                          else Qt.CheckState.Unchecked,
                          Qt.ItemDataRole.CheckStateRole)
            self._sweep_from = index.row()
            self._sweep_to = index.row()
            self._sweep_on = want
            # giữ model lại cho eventFilter dùng khi thả chuột
            self._sweep_model = model
            return True

        if et == QEvent.Type.MouseMove:
            if self._sweep_from is None or self._sweep_to is None:
                return False
            row = self._row_at(event)
            if row is None or row == self._sweep_to:
                return True
            # Quet toi dau ap trang thai toi do. set_range_selected chi
            # ve lai vung vua doi nen quet nghin dong van muot.
            if hasattr(model, "set_range_selected"):
                model.set_range_selected(self._sweep_to, row, self._sweep_on)
            self._sweep_to = row
            return True

        return False

    def end_sweep(self) -> None:
        """Ket thuc quet -- goi tu event filter khi tha chuot trai."""
        self._sweep_from = None
        self._sweep_to = None
        self._sweep_on = False
        self._sweep_model = None

    @property
    def sweeping(self) -> bool:
        return self._sweep_from is not None

    def eventFilter(self, obj, event):  # noqa: N802
        """Bắt MouseButtonRelease để kết thúc quét.

        Gắn lên viewport của bảng. Delegate KHÔNG bao giờ thấy release
        (xem ghi chú ở editorEvent), nên phải bắt ở tầng cao hơn — nơi
        Qt vẫn gửi tới. Chỉ bắt để dọn trạng thái rồi trả về False,
        nên không chặn bất kỳ hành vi mặc định nào của QTableView
        (kể cả chuột phải và kéo chọn dải).

        Ngoài ra bắt cả việc thả chuột RA NGOÀI cửa sổ: khi đó
        viewport không nhận release, quét sẽ treo vĩnh viễn và mọi
        lần rê chuột sau đó đều đổi trạng thái nhầm.
        """
        if event.type() in (QEvent.Type.MouseButtonRelease,
                            QEvent.Type.UngrabMouse):
            if event.type() == QEvent.Type.MouseButtonRelease:
                if getattr(event, "button", None) and \
                        event.button() != Qt.MouseButton.LeftButton:
                    return super().eventFilter(obj, event)
            if self._sweep_from is not None:
                # Chuột vừa thả ở dòng nào đó; nếu dòng đó CHƯA được
                # quét tới (thả nhanh quá, không kịp có MouseMove) thì
                # áp nốt trạng thái cho nó — nếu không dòng cuối cùng
                # sẽ bị bỏ sót dù người dùng thấy mình vừa quét tới.
                try:
                    pos = event.position().toPoint()
                except AttributeError:
                    pos = event.pos()
                row = self._row_at(_FakePoint(pos))
                model = getattr(self, "_sweep_model", None)
                if row is not None and row != self._sweep_to and model \
                        and hasattr(model, "set_range_selected"):
                    model.set_range_selected(self._sweep_to or row, row,
                                             self._sweep_on)
                self.end_sweep()
        return super().eventFilter(obj, event)

    def attach_sweep_filter(self, viewport) -> None:
        viewport.installEventFilter(self)

    def _row_at(self, event) -> int | None:
        """Dòng đang chuột ở, tính theo Y trong viewport."""
        try:
            pos = event.position().toPoint()
        except AttributeError:
            pos = event.pos()      # Qt5 / QMouseEvent cũ
        if pos.y() < 0 or pos.x() < 0:
            return None
        return max(0, pos.y() // self.row_h())

    def _in_box(self, event, index) -> bool:
        """Chuột có nằm trong ô tick của dòng `index` không (nới lề 3px).

        Nới lề vì ô tick chỉ 11–13px — bấm sát mép mà trượt 1px là
        bấm trúng phần chữ, mà bấm phần chữ thì KHÔNG được tick.
        """
        try:
            pos = event.position().toPoint()
        except AttributeError:
            pos = event.pos()      # Qt5 / QMouseEvent cũ
        return self.box_rect(index.row(), index.column()).contains(
            pos, self.BOX_PAD)

    # nới lề bấm cho ô tick, px
    BOX_PAD = 3


class _FakePoint:
    """Bọc QPoint thành object có `position()`, y hệt QMouseEvent.

    `_row_at()` nhận sự kiện chuột; ở eventFilter ta chỉ có QPoint, nên
    bọc lại cho dùng chung một hàm thay vì viết lại phép tính.
    """

    __slots__ = ("_p",)

    def __init__(self, p: QPoint):
        self._p = p

    def position(self):
        from PySide6.QtCore import QPointF
        return QPointF(self._p)


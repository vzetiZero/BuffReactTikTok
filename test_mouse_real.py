"""Kiểm tra bằng QTest — mô phỏng chuột THẬT qua QTableView.

Vì sao cần file này: test cũ gọi thẳng `delegate.editorEvent(...)`, tức
bỏ qua hoàn toàn QTableView. Nhưng trong app thật, QTableView là nơi
quyết định có gửi sự kiện xuống delegate hay không — delegate trả True
hay False chỉ là một phần. Test cũ xanh nhưng app vẫn hỏng là vì vậy.

QTest.mousePress/mouseMove/mouseRelease đi đúng đường Qt đi thật:
viewport -> QTableView -> delegate.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PASS, FAIL = 0, 0


def check(label, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  OK   {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label}\n        got  {got!r}\n        want {want!r}")


def mk(n=40, session=True):
    from core.models import Account
    ck = {"sessionid_ss": "x", "sid_tt": "y"} if session else {}
    return [Account(id=f"acc{i:04d}", username=f"@user{i:03d}",
                    email=f"user{i:03d}@mail.com", password="p",
                    ms_token="", device_id="", cookie=ck)
            for i in range(n)]


def main():
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from core.models import ST_IDLE
    from ui.account_picker import AccountPickerDialog

    from core.models import AccountTableModel
    app = QApplication.instance() or QApplication([])
    # Bảng chính đã đổi thành bảng LOG; ô tick + quét chuột nay ở
    # hộp thoại danh sách tài khoản. Test nhắm đúng chỗ đó.
    m = AccountTableModel()
    m.load(mk(40))
    w = AccountPickerDialog(m)
    w.show()
    for _ in range(8):
        app.processEvents()

    table, del_ = w.table, w.delegate
    vp = table.viewport()
    vh = table.verticalHeader()
    row_h = vh.sectionSize(0) if vh.count() else del_.row_h()

    class _Opt:
        def __init__(self, r):
            from PySide6.QtCore import QRect
            self.rect = QRect(0, r * row_h, vp.width(), row_h)

    def box_pos(row):
        """Tâm ô tick dòng `row` trên màn hình (viewport coords)."""
        b = del_.box_rect(_Opt(row), m.index(row, 0))
        c = b.center()
        return QPoint(c.x(), c.y())

    def row_under(point):
        i = table.indexAt(point)
        return i.row() if i.isValid() and i.column() == 0 else None

    def pump(n=3):
        for _ in range(n):
            app.processEvents()

    def drag(r0, r1):
        """Nhấn ở ô dòng r0, kéo tới dòng r1, thả chuột (qua QTest thật)."""
        QTest.mousePress(vp, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, box_pos(r0))
        pump(1)
        for r in range(r0 + 1, r1 + 1):
            QTest.mouseMove(vp, box_pos(r))
            pump(1)
        QTest.mouseRelease(vp, Qt.MouseButton.LeftButton,
                           Qt.KeyboardModifier.NoModifier, box_pos(r1))
        pump(1)

    def state():
        return [r for r in range(40) if m.row_to_account(r)
                and m.row_to_account(r).selected]

    print("\n=== 1. Toa do o tick khop voi dong that ===")
    b = del_.box_rect(_Opt(0), m.index(0, 0))
    p0 = box_pos(0)
    print(f"     o tick tinh toan = {b.x()},{b.y()}   "
          f"-> viewport {p0.x()},{p0.y()}")
    hit = row_under(p0)
    check("bam vao toa do o tick se ra DUNG dong 0", hit, 0)
    hit5 = row_under(box_pos(5))
    check("bam vao o tick dong 5 se ra DUNG dong 5", hit5, 5)
    check("o tick cua dong 0 va dong 5 khac nhau", p0.y() != box_pos(5).y(), True)

    print("\n=== 2. Bam chuot that vao o tick = tick dung 1 dong ===")
    m.select_none()
    pump()
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, box_pos(2))
    pump()
    check("click o tick dong 2 -> tick 1 tai khoan", m.selected_count(), 1)
    check("dung dong 2", state(), [2])

    print("\n=== 3. Bam lai = bo tick ===")
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, box_pos(2))
    pump()
    check("click lai -> het tick", m.selected_count(), 0)

    print("\n=== 4. NHAN + KEO XUONG (quet) qua QTest that ===")
    m.select_none()
    pump()
    start, end = box_pos(3), box_pos(9)
    QTest.mousePress(vp, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, start)
    pump()
    check("bam (chua keo) -> chi tick dong 3", state(), [3])
    # Qt rut gon cac diem, phai buoc nhieu buoc
    for r in (4, 5, 6, 7, 8, 9):
        QTest.mouseMove(vp, box_pos(r))
        pump(1)
    check("keo den dong 9 -> tick het 3..9", state(), [3, 4, 5, 6, 7, 8, 9])
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier, end)
    pump()
    check("tha chuot xong van giu 3..9", state(), [3, 4, 5, 6, 7, 8, 9])
    check("quet da ket thuc (khong con o cheo)",
          del_._sweep_from, None)

    print("\n=== 5. Sau khi quet, BAM DON LE LAN NUA van tick duoc ===")
    # Day la loi nguoi dung bao: quet xong roi o tick khong con chon duoc.
    m.select_none()
    pump()
    QTest.mousePress(vp, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, box_pos(3))
    for r in (4, 5, 6, 7, 8, 9):
        QTest.mouseMove(vp, box_pos(r))
        pump(1)
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier, box_pos(9))
    pump()
    check("quet xong tick 3..9", state(), [3, 4, 5, 6, 7, 8, 9])
    # bam lai vao chinh o tick do
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, box_pos(5))
    pump()
    check("bam lai o tick giua vung vua quet -> BO TICK no",
          5 in state(), False)
    check("cac dong khac cua vung van tick", state(), [3, 4, 6, 7, 8, 9])

    print("\n=== 6. Bam o tick o tren (ngoai viewport) = khong tick nham ===")
    m.select_none()
    pump()
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, QPoint(4, -10))
    pump()
    check("bam tren man hinh (y am) khong tick gi", m.selected_count(), 0)

    print("\n=== 7. Bam vao PHAN CHU = chon dong, KHONG tick ===")
    m.select_none()
    pump()
    b0 = del_.box_rect(_Opt(0), m.index(0, 0))
    txt = QPoint(b0.x() + 200, box_pos(1).y())
    check("diem nay that su o phan chu (khong phai o tick)", row_under(txt), 1)
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, txt)
    pump()
    check("bam phan chu khong tick gi", m.selected_count(), 0)
    from PySide6.QtCore import QModelIndex
    check("nhung DONG DUOC CHON trong bang",
          table.selectionModel().isRowSelected(1, QModelIndex()), True)

    print("\n=== 8. Chuot phai KHONG duoc delegate nuot ===")
    # KHÔNG kiểm được việc menu có mở thật không: dưới nền offscreen,
    # QtContextMenuPolicy.CustomContextMenu không phát tín hiệu dù gửi
    # MouseButtonPress/Release bằng cả QTest lẫn sendEvent — đã đo thật,
    # cột B và C cũng không phát, tức là giới hạn môi trường chứ không
    # phải lỗi code. Việc delegate có nuột chuột phải hay không thì
    # test_mouse_select.py kiểm trực tiếp ở tầng editorEvent.
    m.select_none()
    pump()
    before = m.selected_count()
    QTest.mouseClick(vp, Qt.MouseButton.RightButton,
                     Qt.KeyboardModifier.NoModifier, box_pos(4))
    pump()
    check("chuot phai khong doi trang thai tick",
          m.selected_count(), before)
    check("chuot phai khong de lai trang thai quet",
          del_.sweeping, False)

    print("\n=== 9. Quet TOAN BO danh sach (0 -> 39) ===")
    m.select_none()
    pump()
    QTest.mousePress(vp, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, box_pos(0))
    last = None
    for r in range(1, 40):
        QTest.mouseMove(vp, box_pos(r))
        pump(1)
        last = r
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier, box_pos(last))
    pump()
    check("quet het 40 dong", m.selected_count(), 40)

    print("\n=== 10. Cac hinh thai con lai ===")
    m.select_none()
    pump()
    drag(0, 39)
    check("quet het 40 dong", m.selected_count(), 40)
    drag(0, 39)
    check("quet lai = bo tick het", m.selected_count(), 0)
    check("quet xong trang thai da tat", del_.sweeping, False)

    print("\n=== 11. Khu vuc chu khong bi quet lam doi ===")
    m.select_none()
    pump()
    drag(3, 9)
    check("quet 3..9 xong", m.selected_count(), 7)
    before = m.selected_count()
    # bam vao phan chu (khong phai o tick) -> khong doi tick
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, QPoint(300, box_pos(15).y()))
    pump()
    check("bam phan chu khong doi tick", m.selected_count(), before)

    print(f"\n{'=' * 58}\n  {PASS} pass, {FAIL} fail\n{'=' * 58}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

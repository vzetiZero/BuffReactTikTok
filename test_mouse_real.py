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
    from ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    w._restore_accounts = lambda: None
    w.resize(1500, 1000)
    w._apply_accounts(mk(40), "test")
    for _ in range(5):
        app.processEvents()
    w._sync_delegate_geometry()
    app.processEvents()

    m, table, del_ = w.model, w.table, w.delegate
    vp = table.viewport()

    def box_pos(row):
        """Toa do that cua o tick dong `row` tren MAN HINH (viewport coords)."""
        b = del_.box_rect(row, 0)
        c = b.center()
        idx = vp.mapFromGlobal(vp.mapToGlobal(c))
        return QPoint(idx.x(), idx.y())

    def row_under(point):
        i = table.indexAt(point)
        return i.row() if i.isValid() and i.column() == 0 else None

    def pump(n=3):
        for _ in range(n):
            app.processEvents()

    def state():
        return [r for r in range(40) if m.row_to_account(r)
                and m.row_to_account(r).selected]

    print("\n=== 1. Toa do o tick khop voi dong that ===")
    b = del_.box_rect(0, 0)
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
    b0 = del_.box_rect(0, 0)
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

    print("\n=== 10. Quet het xong, bam lai de BO TICK het ===")
    QTest.mousePress(vp, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, box_pos(0))
    for r in range(1, 40):
        QTest.mouseMove(vp, box_pos(r))
        pump(1)
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier, box_pos(39))
    pump()
    check("quet lai tren vung da tick -> bo tick het 40", m.selected_count(), 0)

    print("\n=== 11. Dung QTest: trang thai model va NHAN tren man hinh khop ===")
    # Loi nguoi dung thay: co dau tick tren moi dong nhung nhan lai bao 0.
    m.select_all_with_session()
    pump()
    check("tick het 764 (u) -> nhan tren man hinh phai la 40",
          m.selected_count(), 40)
    lbl = w.lbl_pick.text()
    check("nhan 'da tick' tren man hinh cung 40", "40" in lbl, True)
    check("nhan kiem tra chon dung so vung",
          w.lbl_pick_stat.text().count("40") >= 1, True)

    print("\n=== 12. Nhan duoc cap nhat ngay khi quet (khong tre) ===")
    m.select_none()
    pump()
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, box_pos(11))
    pump()
    check("tick 1 dong xong nhan 'da tick' doi ngay",
          w.lbl_pick.text(), "đã tick 1/40")

    m.select_none()
    pump()
    check("bo tick xong nhan doi ngay", w.lbl_pick.text(), "đã tick 0/40")
    # đã bỏ phân trang thì nhãn không được nhắc "trang này" nữa — nó
    # luôn bằng tổng nên chỉ gây rối.
    m.select_all_with_session()
    pump()
    check("nhan khong con nho 'trang nay'", w.lbl_pick.text(), "đã tick 40/40")

    print("\n=== 13. Trang thai 'Chờ' khong bi quet lam doi ===")
    m.select_none()
    for a in m.accounts():
        a.status = ST_IDLE
    m._refresh_page()
    pump()
    QTest.mousePress(vp, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, box_pos(0))
    for r in range(1, 10):
        QTest.mouseMove(vp, box_pos(r))
        pump(1)
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier, box_pos(9))
    pump()
    check("quet khong doi trang thai chay cua tai khoan",
          {a.status for a in m.accounts()}, {ST_IDLE})

    # ------------------------------------------------------------------ #
    # LỖI NGƯỜI DÙNG BÁO: "ô tích chọn lại không chọn được".
    #
    # Nguyên nhân thật (đo bằng spy trên editorEvent): QTableView KHÔNG
    # chuyển MouseButtonRelease xuống delegate khi delegate đã trả True
    # cho MouseButtonPress. Bản cũ chờ release để kết thúc quét → trạng
    # thái "đang quét" treo vĩnh viễn → chỉ cần RÊ chuột qua ô tick là
    # dòng khác bị đổi trạng thái, nên bấm không trúng ý.
    # ------------------------------------------------------------------ #
    print("\n=== 14. Sau khi quet, trang thai phai ket thuc that ===")
    m.select_none()
    pump()
    QTest.mousePress(vp, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, box_pos(2))
    for r in range(3, 8):
        QTest.mouseMove(vp, box_pos(r))
        pump(1)
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier, box_pos(7))
    pump()
    check("quet 2..7 xong", state(), [2, 3, 4, 5, 6, 7])
    check("trang thai quet da TAT sau khi tha chuot", del_.sweeping, False)
    check("_sweep_from da xoa", del_._sweep_from, None)
    check("_sweep_to da xoa", del_._sweep_to, None)

    print("\n=== 15. RE chuot qua o tick (khong nhan) = KHONG doi gi ===")
    # Biểu hiện trực tiếp của lỗi: rê qua mà dòng khác bị đổi.
    before = state()
    for r in (20, 30, 0):
        QTest.mouseMove(vp, box_pos(r))
        pump(2)
    check("re chuot khong lam doi trang thai tick nao", state(), before)

    print("\n=== 16. Bam don le sau khi quet = tick DUNG 1 tai khoan ===")
    before = state()
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, box_pos(20))
    pump()
    check("bam o tick dong 20 -> tick dong 20", 20 in state(), True)
    check("khong co dong nao khac bi doi",
          [r for r in state() if r not in before], [20])
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, box_pos(20))
    pump()
    check("bam lai -> bo tick dung 1 tai khoan", state(), before)

    print("\n=== 17. Quet nhieu lan lien tiep khong bi tre ===")
    for (a, b) in ((1, 5), (10, 14), (20, 25), (30, 35)):
        m.select_none()
        pump()
        QTest.mousePress(vp, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, box_pos(a))
        for r in range(a + 1, b + 1):
            QTest.mouseMove(vp, box_pos(r))
            pump(1)
        QTest.mouseRelease(vp, Qt.MouseButton.LeftButton,
                           Qt.KeyboardModifier.NoModifier, box_pos(b))
        pump()
        check(f"quet {a}..{b} dung khoang", state(), list(range(a, b + 1)))
        check(f"quet {a}..{b} ket thuc that", del_.sweeping, False)

    print(f"\n{'=' * 58}\n  {PASS} pass, {FAIL} fail\n{'=' * 58}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

"""Kiểm tra thao tác chuột ở TẦNG DELEGATE (gọi thẳng editorEvent).

Bổ sung cho test_mouse_real.py: file đó mô phỏng chuột qua QTest nên đi
đúng đường Qt đi thật (viewport -> QTableView -> delegate). File này gọi
thẳng `delegate.editorEvent()` để kiểm từng nhánh quyết định mà không
bị QTableView chen vào.

Yêu cầu: nhấn chuột trái vào ô tick ở cột A rồi KÉO để tick/bỏ tick cả
dải, giống quét ô trong Excel.

Kèm các trường hợp dễ vỡ:
  - bấm chuột phải / giữa phải KHÔNG bị delegate nuốt (để mở menu)
  - bấm vào phần chữ (không phải ô tick) phải chọn dòng, không tick

Chạy:  python test_mouse_select.py
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


def mk(n=20):
    from core.models import Account
    return [Account(id=f"acc{i:04d}", username=f"@user{i:03d}",
                    email=f"user{i:03d}@mail.com", password="p",
                    ms_token="", device_id="",
                    cookie={"sessionid_ss": "x", "sid_tt": "y"})
            for i in range(n)]


def main():
    from PySide6.QtCore import QEvent, QPoint, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    from core.models import AccountTableModel
    from ui.account_picker import AccountPickerDialog

    from core.models import AccountTableModel
    app = QApplication.instance() or QApplication([])
    # Ô tick + quét chuột nay nằm trong hộp thoại danh sách tài khoản
    # (bảng chính đã đổi thành bảng log chạy). Test nhắm đúng chỗ đó.
    m = AccountTableModel()
    m.load(mk(20))
    w = AccountPickerDialog(m)
    w.show()          # visualRect chỉ đúng khi widget đã hiển thị
    for _ in range(6):
        app.processEvents()

    table, del_ = w.table, w.delegate

    def send(kind, pos, row, button=Qt.MouseButton.LeftButton,
             at_btn=Qt.MouseButton.LeftButton, col=0):
        ev = QMouseEvent(kind, pos, table.viewport().mapToGlobal(pos),
                         button, at_btn, Qt.KeyboardModifier.NoModifier)
        return del_.editorEvent(ev, m, None, m.index(row, col))

    def opt_rect(row):
        """Rect của ô dòng `row`, giống hệt option.rect mà Qt dùng.

        `visualRect()` trả về rect rỗng dưới nền offscreen (giới hạn
        môi trường test, không phải lỗi app). Ở đây bảng KHÔNG cuộn,
        nên rect đúng là row * row_h — tự dựng cho khớp.
        """
        from PySide6.QtCore import QRect
        # Dùng chiều cao dòng THẬT của bảng, không phải row_h() của
        # delegate: hộp thoại đặt section 18px nên hai giá trị lệch nhau.
        vh = table.verticalHeader()
        h = vh.sectionSize(0) if vh.count() else del_.row_h()
        return QRect(0, row * h, table.viewport().width(), h)

    def box_at(row):
        idx = m.index(row, 0)

        class _Opt:
            rect = opt_rect(row)

        return del_.box_rect(_Opt(), idx).center()

    def click(row):
        """Bấm đơn lẻ: delegate xử lý ngay ở MouseButtonPress, rồi
        event filter trên viewport gọi end_sweep() khi thả chuột."""
        send(QEvent.Type.MouseButtonPress, box_at(row), row)
        del_.end_sweep()

    def drag(r0, r1):
        """Nhấn ở ô dòng r0, kéo tới dòng r1, thả chuột."""
        send(QEvent.Type.MouseButtonPress, box_at(r0), r0)
        send(QEvent.Type.MouseMove, box_at(r1), r1)
        del_.end_sweep()

    def ticked():
        return [r for r in range(20)
                if m.row_to_account(r) and m.row_to_account(r).selected]

    print("\n=== 1. Toa do o tick ===")
    box = del_.box_rect(type('O', (), {'rect': opt_rect(0)})(), m.index(0, 0))
    check("o tick nam trong cot A (x >= 0)", box.x() >= 0, True)
    check("o tick be rong hop ly", 0 < box.width() <= 30, True)
    check("o tick o ben phai so voi so thu tu, truoc phan chu",
          box.x() >= 30, True)
    check("o tick cua dong 0 va dong 19 khac nhau",
          box_at(0).y() != box_at(19).y(), True)
    print(f"     o tick = {box.x()},{box.y()} {box.width()}x{box.height()}")

    print("\n=== 2. Click don le vao o tick ===")
    m.select_none()
    app.processEvents()
    check("truoc khi click: chua tick gi", m.selected_count(), 0)
    h = send(QEvent.Type.MouseButtonPress, box.center(), 0)
    del_.end_sweep()
    check("click o tick duoc delegate xu ly", h, True)
    check("click o tick -> tick 1 tai khoan", m.selected_count(), 1)
    click(0)
    check("click lai o tick -> bo tick", m.selected_count(), 0)

    print("\n=== 3. Click vung chu = chon dong, KHONG tick ===")
    m.select_none()
    app.processEvents()
    txt = QPoint(box.right() + 60, box.center().y())
    h = send(QEvent.Type.MouseButtonPress, txt, 0)
    check("click vung chu khong doi tick", m.selected_count(), 0)
    check("click vung chu KHONG bi delegate nuot (chon duoc dong)", h, False)

    print("\n=== 4. Chuot phai = phai mo duoc menu ===")
    m.select_none()
    app.processEvents()
    h = send(QEvent.Type.MouseButtonPress, box.center(), 0,
             Qt.MouseButton.RightButton, Qt.MouseButton.RightButton)
    check("chuot phai tren o tick KHONG bi delegate xu ly", h, False)
    check("chuot phai khong doi trang thai tick", m.selected_count(), 0)
    check("chuot phai khong bat dau quet", del_.sweeping, False)
    for col in (1, 2):
        h = send(QEvent.Type.MouseButtonPress, QPoint(10, 5), 0,
                 Qt.MouseButton.RightButton, Qt.MouseButton.RightButton, col=col)
        check(f"chuot phai tren cot {col} khong bi delegate xu ly", h, False)

    print("\n=== 5. Nut giua = khong tick ===")
    m.select_none()
    app.processEvents()
    h = send(QEvent.Type.MouseButtonPress, box.center(), 0,
             Qt.MouseButton.MiddleButton, Qt.MouseButton.MiddleButton)
    check("nut giura khong bi delegate xu ly", h, False)
    check("nut giura khong bat dau quet", del_.sweeping, False)

    print("\n=== 6. Di chuot ma khong nhan = khong tick gi ===")
    m.select_none()
    app.processEvents()
    send(QEvent.Type.MouseMove, QPoint(2, box.center().y()), 0)
    check("di chuot khong tick gi", m.selected_count(), 0)
    check("di chuot khong bat dau quet", del_.sweeping, False)

    print("\n=== 7. QUET XUONG: bam dong 2 keo den dong 7 ===")
    m.select_none()
    app.processEvents()
    drag(2, 7)
    check("quet xuong tick ca 6 dong (2..7)", ticked(), [2, 3, 4, 5, 6, 7])

    print("\n=== 8. QUET LEN: bam dong 12 keo len dong 8 ===")
    m.select_none()
    app.processEvents()
    drag(12, 8)
    check("quet len tick ca 5 dong (8..12)", ticked(), [8, 9, 10, 11, 12])

    print("\n=== 9. Quet tren o DA TICK = bo tick ca lo ===")
    m.select_none()
    app.processEvents()
    m.row_to_account(10).selected = True
    m._refresh_page()
    app.processEvents()
    drag(10, 14)
    check("quet tren dong da tick -> bo tick ca lo", ticked(), [])

    print("\n=== 10. Quet qua dong khac trang thai ===")
    m.select_none()
    app.processEvents()
    m.row_to_account(12).selected = True
    m.row_to_account(13).selected = True
    m._refresh_page()
    app.processEvents()
    drag(10, 15)
    check("quet qua dong da tick giữ chung trang thai", ticked(),
          [10, 11, 12, 13, 14, 15])

    print("\n=== 11. Quet nhieu buoc (keo qua trung gian) ===")
    m.select_none()
    app.processEvents()
    send(QEvent.Type.MouseButtonPress, box_at(1), 1)
    for r in (2, 3, 4, 5):
        send(QEvent.Type.MouseMove, box_at(r), r)
    del_.end_sweep()
    check("keo qua nhieu dong = tick het 1..5", ticked(), [1, 2, 3, 4, 5])

    print("\n=== 12. Bam vao dong bat ky deu chay duoc ===")
    m.select_none()
    app.processEvents()
    for row in (0, 5, 19):
        click(row)
        app.processEvents()
        check(f"dong {row} tick duoc", m.row_to_account(row).selected, True)
        m.row_to_account(row).selected = False
    m._refresh_page()
    app.processEvents()

    print("\n=== 13. end_sweep() don sach ca 3 truong ===")
    send(QEvent.Type.MouseButtonPress, box_at(2), 2)
    check("dang quet", del_.sweeping, True)
    del_.end_sweep()
    check("sau end_sweep: khong con quet", del_.sweeping, False)
    check("_sweep_from = None", del_._sweep_from, None)
    check("_sweep_to = None", del_._sweep_to, None)
    check("_sweep_on = False", del_._sweep_on, False)

    print("\n=== 14. Sau khi quet, bam lai van tick DUNG 1 cai ===")
    m.select_none()
    app.processEvents()
    drag(2, 7)
    check("quet xong tick 2..7", ticked(), [2, 3, 4, 5, 6, 7])
    before = ticked()
    click(5)
    check("bam lai o tick giua vung vua quet -> chi bo tick no",
          ticked(), [r for r in before if r != 5])
    click(5)
    check("bam lai lan nua -> tick lai", ticked(), before)

    print("\n=== 15. set_range_selected — kiem tra truc tiep tren model ===")
    m.select_none()
    app.processEvents()
    check("tick 6 dong (3..8)", m.set_range_selected(3, 8, True), 6)
    check("tong so tick = 6", m.selected_count(), 6)
    check("tick lai vung da tick = 0 thay doi",
          m.set_range_selected(5, 6, True), 0)
    check("dao thu tu tham so va bo tick het",
          m.set_range_selected(8, 3, False), 6)
    check("con 0 tick", m.selected_count(), 0)
    check("khoang tran bien se cat theo phan hien",
          m.set_range_selected(-5, 100, True), 20)
    check("tick het 20 dong", m.selected_count(), 20)

    print("\n=== 16. Quet het danh sach ===")
    m.select_none()
    app.processEvents()
    drag(0, 19)
    check("quet tu dong 0 den 19 = tick het 20", m.selected_count(), 20)
    drag(0, 19)
    check("quet lai = bo tick het 20", m.selected_count(), 0)

    print(f"\n{'=' * 58}\n  {PASS} pass, {FAIL} fail\n{'=' * 58}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

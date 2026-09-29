"""Kiểm tra thao tác chuột trên bảng — quét hàng loạt ở cột A.

Yêu cầu: nhấn chuột trái vào ô tick ở cột A rồi KÉO xuống để tick/bỏ
tick cả dải, giống quét ô trong Excel — không phải bấm từng cái một.

Kèm các trường hợp dễ vỡ:
  - bấm chuột phải vào cột A phải mở được menu ngữ cảnh
  - bấm vào phần chữ (không phải ô tick) phải chọn dòng, không tick
  - kéo qua nhiều dòng phải đảo đúng chiều (kéo lên cũng đúng)

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
    from ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    w._restore_accounts = lambda: None
    w._apply_accounts(mk(20), "test")
    for _ in range(4):
        app.processEvents()
    w._sync_delegate_geometry()
    app.processEvents()

    m, table, del_ = w.model, w.table, w.delegate

    def send(kind, pos, row, button=Qt.MouseButton.LeftButton,
             at_btn=Qt.MouseButton.LeftButton, col=0):
        """Gửi sự kiện chuột tới delegate tại vị trí `pos` của dòng `row`."""
        ev = QMouseEvent(kind, pos, table.viewport().mapToGlobal(pos),
                         button, at_btn, Qt.KeyboardModifier.NoModifier)
        return del_.editorEvent(ev, m, None, m.index(row, col))

    def box_at(row):
        """Tâm ô tick của dòng `row`."""
        b = del_.box_rect(row, 0)
        return QPoint(b.center().x(), b.center().y())

    def drag(r0, r1):
        """Nhấn ở ô dòng r0 rồi kéo tới ô dòng r1."""
        send(QEvent.Type.MouseButtonPress, box_at(r0), r0)
        send(QEvent.Type.MouseMove, box_at(r1), r1)
        send(QEvent.Type.MouseButtonRelease, box_at(r1), r1)

    print("\n=== 1. Toa do o tick khop voi noi ve ===")
    b = del_.box_rect(0, 0)
    check("o tick nam ben trai cot A", b.x() >= 0, True)
    check("o tick be rong hop ly", 0 < b.width() <= 30, True)
    check("o tick nam trong viewport",
          b.x() + b.width() <= table.viewport().width(), True)
    print(f"     o tick dong 0 = {b.x()},{b.y()} {b.width()}x{b.height()}")

    print("\n=== 2. Bam don le vao o tick = tick 1 tai khoan ===")
    m.select_none()
    app.processEvents()
    send(QEvent.Type.MouseButtonPress, box_at(3), 3)
    h = send(QEvent.Type.MouseButtonRelease, box_at(3), 3)
    check("click o tick duoc xu ly", h, True)
    check("chi tick dung 1 tai khoan", m.selected_count(), 1)
    check("dung tai khoan muc tieu", m.row_to_account(3).selected, True)

    print("\n=== 3. Bam lai = bo tick ===")
    send(QEvent.Type.MouseButtonPress, box_at(3), 3)
    send(QEvent.Type.MouseButtonRelease, box_at(3), 3)
    check("click lai thi bo tick", m.selected_count(), 0)

    print("\n=== 4. QUET XUONG: bam dong 2 keo den dong 7 ===")
    m.select_none()
    app.processEvents()
    drag(2, 7)
    check("quet xuong tick ca 6 dong (2..7)", m.selected_count(), 6)
    ticked = [r for r in range(20) if m.row_to_account(r).selected]
    check("dung cac dong 2..7", ticked, [2, 3, 4, 5, 6, 7])

    print("\n=== 5. QUET LEN: bam dong 12 keo len dong 8 ===")
    m.select_none()
    app.processEvents()
    drag(12, 8)
    check("quet len tick ca 5 dong (8..12)", m.selected_count(), 5)
    ticked = [r for r in range(20) if m.row_to_account(r).selected]
    check("dung cac dong 8..12", ticked, [8, 9, 10, 11, 12])

    print("\n=== 6. Quet tren tai khoan DA tick = bo tick ca lo ===")
    # ô tick dòng 10 đang tick -> bấm vào sẽ đảo sang bỏ tick, kéo theo
    # phải bỏ tick tất cả dòng quét qua.
    m.select_none()
    app.processEvents()
    send(QEvent.Type.MouseButtonPress, box_at(10), 10)
    check("bam vao dong chua tick -> tick", m.row_to_account(10).selected, True)
    send(QEvent.Type.MouseButtonRelease, box_at(10), 10)
    m.select_none()
    app.processEvents()
    m.row_to_account(10).selected = True
    m._refresh_page()
    app.processEvents()
    drag(10, 14)
    check("quet tren dong da tick -> BO TICK ca lo",
          m.selected_count(), 0)
    check("khong con dong nao con tick",
          [r for r in range(20) if m.row_to_account(r).selected], [])

    print("\n=== 7. Quet qua dong da tick khac trang thai ===")
    # bắt đầu từ ô CHƯA tick -> áp 'tick' cho cả dải, kể cả dòng đã
    # tick sẵn ở giữa (vẫn tick, không đổi gì).
    m.select_none()
    app.processEvents()
    m.row_to_account(12).selected = True
    m.row_to_account(13).selected = True
    m._refresh_page()
    app.processEvents()
    drag(10, 15)
    check("quet qua dong da tick giữ chung trang thai",
          m.selected_count(), 6)

    print("\n=== 8. Quet nhieu buoc (keo qua trung gian) ===")
    m.select_none()
    app.processEvents()
    send(QEvent.Type.MouseButtonPress, box_at(1), 1)
    for r in (2, 3, 4, 5):
        send(QEvent.Type.MouseMove, box_at(r), r)
    send(QEvent.Type.MouseButtonRelease, box_at(5), 5)
    check("keo qua nhieu dong = tick het 1..5", m.selected_count(), 5)

    print("\n=== 9. Bam chuot phai vao cot A = PHAI mo menu ===")
    m.select_none()
    app.processEvents()
    send(QEvent.Type.MouseButtonPress, box_at(3), 3,
         Qt.MouseButton.RightButton, Qt.MouseButton.RightButton)
    h = send(QEvent.Type.MouseButtonRelease, box_at(3), 3,
             Qt.MouseButton.RightButton, Qt.MouseButton.RightButton)
    check("chuot phai tren o tick KHONG bi delegate nuot", h, False)
    check("chuot phai khong doi trang thai tick", m.selected_count(), 0)

    print("\n=== 10. Bam chuot phai tren cot B / C = phai mo menu ===")
    for col in (1, 2):
        send(QEvent.Type.MouseButtonPress, QPoint(10, 10),
             0, Qt.MouseButton.RightButton, Qt.MouseButton.RightButton, col=col)
        h = send(QEvent.Type.MouseButtonRelease, QPoint(10, 10),
                 0, Qt.MouseButton.RightButton, Qt.MouseButton.RightButton, col=col)
        check(f"chuot phai tren cot {col} khong bi nuot", h, False)

    print("\n=== 11. Bam vao PHAN CHU = chon dong, KHONG tick ===")
    m.select_none()
    app.processEvents()
    bb = del_.box_rect(0, 0)
    txt = QPoint(bb.right() + 60, bb.center().y())
    h = send(QEvent.Type.MouseButtonPress, txt, 0)
    h2 = send(QEvent.Type.MouseButtonRelease, txt, 0)
    check("bam phan chu khong bi delegate xu ly", h or h2, False)
    check("bam phan chu khong doi tick", m.selected_count(), 0)

    print("\n=== 12. Bam nut giua = khong tick ===")
    m.select_none()
    app.processEvents()
    send(QEvent.Type.MouseButtonPress, box_at(3), 3,
         Qt.MouseButton.MiddleButton, Qt.MouseButton.MiddleButton)
    h = send(QEvent.Type.MouseButtonRelease, box_at(3), 3,
             Qt.MouseButton.MiddleButton, Qt.MouseButton.MiddleButton)
    check("nut giura khong bi xu ly", h, False)
    check("nut giura khong doi tick", m.selected_count(), 0)

    print("\n=== 13. Di chuot ma khong nhan = khong tick gi ===")
    m.select_none()
    app.processEvents()
    h = send(QEvent.Type.MouseMove, QPoint(2, 10), 0)
    check("di chuot khong tick gi", m.selected_count(), 0)
    check("khong bat dau quet khi chi di chuot",
          del_._sweep_from, None)

    print("\n=== 14. set_range_selected — kiem tra truc tiep tren model ===")
    m.select_none()
    app.processEvents()
    n = m.set_range_selected(3, 8, True)
    check("tick 6 dong (3..8)", n, 6)
    check("tong so tick = 6", m.selected_count(), 6)
    n2 = m.set_range_selected(5, 6, True)
    check("tick lai vung da tick = 0 thay doi", n2, 0)
    n3 = m.set_range_selected(8, 3, False)
    check("dao thu tu tham so va bo tick het", n3, 6)
    check("con 0 tick", m.selected_count(), 0)
    n4 = m.set_range_selected(-5, 100, True)
    check("khoang tran bien se cat theo phan hien", n4, 20)
    check("tick het 20 dong", m.selected_count(), 20)

    print("\n=== 15. Quet xuong het danh sach ===")
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

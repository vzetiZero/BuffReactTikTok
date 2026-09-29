"""Kiểm tra 3 thay đổi vừa làm:

  1. Ô "số lượng tài khoản chạy" + 2 radio (ngẫu nhiên / theo thứ tự)
  2. Bỏ phân trang — bảng hiện toàn bộ, có ô đếm "đã quét"
  3. Dòng log thành công rút gọn thành "2 TIM CMT <cid>"

Chạy:  python test_select_and_log.py
"""

from __future__ import annotations

import os
import random
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


def mk(n, session=True, **kw):
    """Tạo n account giả.

    `session=True` (mặc định) cho cookie đủ 2 key bắt buộc, để
    `select_all_with_session()` thực sự tick được. Không có nó thì hàm
    đó tick 0 cái và test GUI báo số sai — dễ chẩn đoán nhầm là lỗi UI.
    """
    from core.models import Account
    cookie = {"sessionid_ss": "x", "sid_tt": "y"} if session else {}
    return [Account(id=f"acc{i:04d}", username=f"u{i}", email=f"e{i}@x",
                    password="p", ms_token="", device_id="",
                    cookie=cookie, **kw)
            for i in range(n)]


def main():
    from core.models import (
        AccountTableModel,
        format_success_line,
        LOG_OK_LABEL,
    )

    print("\n=== 1. pick_limited — chọn N theo thứ tự ===")
    rows = mk(100)
    out = AccountTableModel.pick_limited(rows, 60, AccountTableModel.PICK_ORDER)
    check("theo thu tu lay dung 60", len(out), 60)
    check("theo thu tu giu dung 60 tai khoan dau",
          [a.id for a in out], [a.id for a in rows[:60]])

    print("\n=== 2. pick_limited — chon N ngau nhien ===")
    rng = random.Random(42)
    out = AccountTableModel.pick_limited(
        rows, 60, AccountTableModel.PICK_RANDOM, rng)
    check("ngau nhien lay dung 60", len(out), 60)
    check("khong trung lap trong mot lan chon", len(set(a.id for a in out)), 60)
    check("mọi phần tử đều thuộc danh sách gốc",
          all(a in rows for a in out), True)
    # 60 cái đầu (theo thứ tự) không thể trùng khớp với 60 ngẫu nhiên
    # trong danh sách 100 — nếu trùng hết thì logic random không hoạt động
    same = set(a.id for a in out) == {a.id for a in rows[:60]}
    check("ngau nhien KHAC tach 60 dau", same, False)

    print("\n=== 3. pick_limited — bien edge ===")
    check("limit 0 = lay het", len(AccountTableModel.pick_limited(rows, 0)), 100)
    check("limit am = lay het", len(AccountTableModel.pick_limited(rows, -5)), 100)
    check("limit > so luong = lay het",
          len(AccountTableModel.pick_limited(rows, 9999)), 100)
    check("limit = 0 trong 0 tai khoan",
          AccountTableModel.pick_limited([], 5), [])
    check("limit = 5 trong 3 tai khoan = 3",
          len(AccountTableModel.pick_limited(mk(3), 5)), 3)
    check("khong sua list goc",
          AccountTableModel.pick_limited(rows, 10) is not rows, True)
    check("khong doi co selected",
          all(a.selected for a in AccountTableModel.pick_limited(rows, 10)), True)

    print("\n=== 4. pick_limited — cung seed cho ket qua lap lai ===")
    a1 = AccountTableModel.pick_limited(
        rows, 60, AccountTableModel.PICK_RANDOM, random.Random(7))
    a2 = AccountTableModel.pick_limited(
        rows, 60, AccountTableModel.PICK_RANDOM, random.Random(7))
    check("cung seed cho cung ket qua",
          [a.id for a in a1], [a.id for a in a2])

    print("\n=== 5. pick_for_run — chi xet tai khoan DA TICK ===")
    m = AccountTableModel()
    m.load(mk(50))
    m.select_none()
    for i, a in enumerate(m.accounts()):
        a.selected = (i % 2 == 0)      # tick 25 cái
    out = m.pick_for_run(10, AccountTableModel.PICK_ORDER)
    check("chi lay trong so da tick", len(out), 10)
    check("moi phan tu deu da tick", all(a.selected for a in out), True)
    check("khong lay tai khoan chua tick",
          all(i % 2 == 0 for i, a in enumerate(m.accounts()) if a in out), True)

    print("\n=== 6. pick_for_run — phai doc cac trang khac nhau ===")
    # Không phân trang nên _view chứa hết; tick thì cả danh sách, bất kể
    # đang lọc hay không. Lọc rồi vẫn phải lấy đúng những gì đã tick.
    m.set_filter(AccountTableModel.F_SELECTED)
    check("loc 'da tick' van thay 25", m.view_count, 25)
    out = m.pick_for_run(60, AccountTableModel.PICK_ORDER)
    check("pick > so tick thi tra ve het 25", len(out), 25)
    m.set_filter(AccountTableModel.F_ALL)
    check("bo loc xong van 25 da tick", m.selected_count(), 25)

    print("\n=== 7. Bo phan trang ===")
    m2 = AccountTableModel()
    m2.load(mk(120))
    m2.set_per_page(0)
    check("per_page = 0", m2.per_page, 0)
    check("hien toan bo 120 dong", m2.rowCount(), 120)
    check("chi 1 trang", m2.page_count, 1)
    check("page_rows tra ve het", len(m2.page_rows()), 120)
    check("page_slice phu het danh sach", m2.page_slice(), (0, 120))
    check("row 0 -> tai khoan dau", m2.row_to_account(0).id, "acc0000")
    check("row 119 -> tai khoan cuoi", m2.row_to_account(119).id, "acc0119")
    check("row 120 khong ton tai", m2.row_to_account(120), None)

    print("\n=== 8. format_success_line — dang 'N TIM CMT <cid>' ===")
    # đúng dạng người dùng yêu cầu: "2 TIM CMT 7602703562657022728"
    check("co like_after -> '2 TIM CMT <cid>'",
          format_success_line("♥ cid=7602703562657022728 · like 1 → 2",
                               like_after=2),
          "2 TIM CMT 7602703562657022728")
    check("cid 19 chu so",
          format_success_line("", comment_id="7602703562657022728",
                              like_after=2),
          "2 TIM CMT 7602703562657022728")
    check("tu boc cid tu note khi thieu comment_id",
          format_success_line("♥ cid=1234567890123456789 · like 0 → 5"),
          "5 TIM CMT 1234567890123456789")
    check("doc like tu note 'like 1 → 2'",
          format_success_line("♥ cid=1234567890123456789 · like 1 → 2"),
          "2 TIM CMT 1234567890123456789")
    check("doc like tu note 'like=7'",
          format_success_line("♥ cid=1234567890123456789 (like=7)"),
          "7 TIM CMT 1234567890123456789")
    check("doc like tu note 'like 3 → 4' co dau mui ten",
          format_success_line("♥ cid=1234567890123456789 · like 3 → 4"),
          "4 TIM CMT 1234567890123456789")
    check("khong co so like -> 'OK TIM CMT <cid>'",
          format_success_line("♥ cid=1234567890123456789 · API trả 0"),
          f"{LOG_OK_LABEL} TIM CMT 1234567890123456789")
    check("like = 0 van hien so 0",
          format_success_line("", comment_id="1234567890123456789",
                              like_after=0),
          "0 TIM CMT 1234567890123456789")

    print("\n=== 9. format_success_line — khong boc duoc cid thi tra '' ===")
    # Trả "" để caller giữ note gốc, thay vì in dòng rỗng hoặc mất cid.
    check("khong co cid -> chuoi rong", format_success_line("✔ xong"), "")
    check("note rong, khong cid -> chuoi rong", format_success_line(""), "")
    check("cid khong phai so -> bo qua (khong in rac)",
          format_success_line("✔ xong cid=abc"), "")

    print("\n=== 10. TaskResult / Account co truong moi ===")
    from core.models import TaskResult
    tr = TaskResult("Thành công", note="♥ cid=1", like_after=3)
    check("TaskResult.like_after", tr.like_after, 3)
    check("TaskResult.like_after mac dinh None",
          TaskResult("Lỗi").like_after, None)
    from core.models import Account
    check("Account.like_after mac dinh None",
          Account(id="a", username="", email="", password="",
                  ms_token="", device_id="").like_after, None)

    print("\n=== 11. GUI: bo nut phan trang, co o dem 'da quet' ===")
    from PySide6.QtWidgets import QApplication
    from ui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    for _ in range(3):
        app.processEvents()

    check("model khong phan trang", w.model.per_page, 0)
    check("khong con nut 'Trang nay +'", hasattr(w, "btn_page_on"), False)
    check("khong con nut 'Trang nay -'", hasattr(w, "btn_page_off"), False)
    check("khong con combo so dong/trang", hasattr(w, "cb_per_page"), False)
    check("co nhan so tai khoan da quet", hasattr(w, "lbl_scanned"), True)
    check("nhan rong khi chua nap file",
          w.lbl_scanned.text(), "Chưa quét")
    check("co nhan 'dang hien toan bo danh sach'",
          w.lbl_range.text(), "Chưa có tài khoản")

    print("\n=== 12. GUI: o so luong + 2 radio ===")
    check("co o nhap so luong", hasattr(w, "sp_pick"), True)
    check("mac dinh 0 = tat ca", w.sp_pick.value(), 0)
    check("specialValueText = 'tat ca'", w.sp_pick.specialValueText(), "tất cả")
    check("cho phep nhap den 1 trieu", w.sp_pick.maximum(), 1_000_000)
    check("co radio theo thu tu", hasattr(w, "rb_pick_order"), True)
    check("co radio ngau nhien", hasattr(w, "rb_pick_random"), True)
    check("mac dinh chon theo thu tu", w.rb_pick_order.isChecked(), True)
    check("radio ngau nhien khong bat mac dinh",
          w.rb_pick_random.isChecked(), False)
    check("_pick_how tra theo thu tu",
          w._pick_how(), AccountTableModel.PICK_ORDER)
    w.rb_pick_random.setChecked(True)
    app.processEvents()
    check("doi radio -> _pick_hoghi ngaunhien",
          w._pick_how(), AccountTableModel.PICK_RANDOM)
    check("2 radio loai trua nhau (chi 1 bat)",
          w.rb_pick_order.isChecked() + w.rb_pick_random.isChecked(), 1)

    print("\n=== 13. GUI: nhan so thuc te se chay ===")
    w.model.load(mk(100))
    w.model.select_all_with_session()
    w.sp_pick.setValue(60)
    app.processEvents()
    check("tick het + dat 60 -> bao se chay 60",
          "60 tài khoản" in w.lbl_pick_stat.text()
          and "ngẫu nhiên" in w.lbl_pick_stat.text(), True)

    w.rb_pick_order.setChecked(True)
    app.processEvents()
    check("doi sang theo thu tu -> nhan doi chu 'theo thu tu'",
          "theo thứ tự" in w.lbl_pick_stat.text(), True)

    w.sp_pick.setValue(0)
    app.processEvents()
    check("dat 0 -> bao chay toan bo 100",
          "toàn bộ 100" in w.lbl_pick_stat.text(), True)

    w.sp_pick.setValue(500)
    app.processEvents()
    check("dat 500 > 100 tick -> bao se chay het 100",
          "sẽ chạy hết 100" in w.lbl_pick_stat.text(), True)

    w.sp_pick.setValue(0)
    w.model.select_none()
    app.processEvents()
    check("bo tick het -> bao chua tick gi",
          "Chưa tick" in w.lbl_pick_stat.text(), True)

    print("\n=== 14. GUI: nhan 'da quet' cap nhat khi nap file ===")
    w.model.load(mk(1234))
    w._apply_accounts(mk(1234), "file test")
    for _ in range(3):
        app.processEvents()
    check("nhan so quet = 1.234 (dau cham ngan)",
          w.lbl_scanned.text(), "✔ Đã quét 1.234 tài khoản")
    check("no hoa so lon dung chuam",
          "1.234" in w.lbl_scanned.text(), True)
    check("bang hien toan bo 1234 dong", w.model.rowCount(), 1234)
    check("khong con nut phan trang trong _set_running",
          hasattr(w, "btn_page_on"), False)

    print("\n=== 15. GUI: khoi dong lai thi van khong phan trang ===")
    w2 = MainWindow()
    for _ in range(3):
        app.processEvents()
    check("MainWindow moi cung per_page = 0", w2.model.per_page, 0)

    print(f"\n{'=' * 58}\n  {PASS} pass, {FAIL} fail\n{'=' * 58}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

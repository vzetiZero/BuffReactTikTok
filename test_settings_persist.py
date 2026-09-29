"""Kiểm tra tham số chạy được LƯU lại — sửa rồi mở app phải còn nguyên.

Lỗi đã gặp: ô "Số luồng" sửa xong không ăn, mở lại app về 10.
Nguyên nhân thật: tab Cài đặt có MỘT ô số luồng nữa (ẩn đi sau này) và
`closeEvent` gọi `_sync_to_settings()` của tab đó — lấy giá trị cũ rồi
ghi đè lên thứ người dùng vừa chỉnh ở tab Tác vụ.

Test này dùng settings.json thật (đường dẫn config thật của user) và
tự khôi phục lại sau khi chạy, không phá cấu hình của bạn.

Chạy:  python test_settings_persist.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

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


def main():
    from PySide6.QtWidgets import QApplication
    from core.models import AccountTableModel
    from core.settings import default_path
    from ui.main_window import MainWindow

    path = default_path()
    backup = path.read_text(encoding="utf-8") if path.exists() else None
    print(f"     file cau hinh: {path}")

    def reset():
        """Đặt cấu hình về mặc định biết trước để test đo được."""
        d = json.loads(backup) if backup else {}
        d.update({"concurrency": 10, "retries": 1, "delay_min": 0.0,
                  "delay_max": 1.0, "pick_limit": 0, "pick_how": "order",
                  "mode": "like_cid", "verify": True})
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    def restore():
        if backup is not None:
            path.write_text(backup, encoding="utf-8")

    app = QApplication.instance() or QApplication([])

    def spin(ms=650):
        """Chạy hết các QTimer pending (app tự khôi phục sau ~400ms)."""
        t0 = time.time()
        while time.time() - t0 < ms / 1000:
            app.processEvents()
            time.sleep(0.02)

    try:
        print("\n=== 1. Mo app tu cau hinh mac dinh ===")
        reset()
        w1 = MainWindow()
        spin()
        check("so luong mac dinh la 10", w1.sp_threads.value(), 10)
        check("retry mac dinh la 1", w1.sp_retry.value(), 1)
        check("so luong trong settings cung 10", w1.settings.concurrency, 10)

        print("\n=== 2. Nguoi dung doi tham so ===")
        w1.sp_threads.setValue(15)
        w1.sp_retry.setValue(3)
        w1.sp_dmin.setValue(0.5)
        w1.sp_dmax.setValue(2.5)
        w1.sp_pick.setValue(60)
        w1.rb_pick_random.setChecked(True)
        spin(250)
        check("spinbox hien 15 luong", w1.sp_threads.value(), 15)
        check("settings.concurrency da doi ngay (khong can bam CHAY)",
              w1.settings.concurrency, 15)
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        check("da ghi xuong dia ngay khi doi", on_disk["concurrency"], 15)

        print("\n=== 3. Dong app (closeEvent) ===")
        w1.close()
        spin(200)
        del w1
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        check("closeEvent giu 15 luong", on_disk["concurrency"], 15)
        check("closeEvent giu 3 retry", on_disk["retries"], 3)
        check("closeEvent giu 0.5 do loi", on_disk["delay_min"], 0.5)
        check("closeEvent giu 2.5 do loi", on_disk["delay_max"], 2.5)
        check("closeEvent giu 60 profile", on_disk["pick_limit"], 60)
        check("closeEvent giu 'random'", on_disk["pick_how"], "random")

        print("\n=== 4. MO LAI APP — phai doc lai dung gia tri da luu ===")
        w2 = MainWindow()
        spin()
        check("so luong = 15", w2.sp_threads.value(), 15)
        check("retry = 3", w2.sp_retry.value(), 3)
        check("tre 0.5 - 2.5 s",
              (w2.sp_dmin.value(), w2.sp_dmax.value()), (0.5, 2.5))
        check("so profile = 60", w2.sp_pick.value(), 60)
        check("cach chon = random", w2._pick_how(),
              AccountTableModel.PICK_RANDOM)

        print("\n=== 5. Bat buoc: dong app khong duoc LAM mat gia tri ===")
        # Day la loi goc: closeEvent goi _sync_to_settings() cua tab Cai
        # dat, lay o so luong cu (mac dinh 10) roi ghi de.
        w3 = MainWindow()
        spin()
        w3.sp_threads.setValue(42)
        w3.sp_retry.setValue(5)
        spin(200)
        w3.close()
        spin(200)
        del w3
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        check("dong app giu 42 luong (khong nhay ve 10)",
              on_disk["concurrency"], 42)
        check("dong app giu 5 retry", on_disk["retries"], 5)

        w4 = MainWindow()
        spin()
        check("mo lai thay 42 luong", w4.sp_threads.value(), 42)
        check("mo lai thay 5 retry", w4.sp_retry.value(), 5)
        w4.close()
        spin(150)
        del w4

        print("\n=== 6. Khong co o SO LUONG trung lap o tab Cai dat ===")
        w5 = MainWindow()
        spin()
        # isVisibleTo() phu thuoc tab dang xem, nen phai chuyen sang tab
        # Cai dat truoc khi hoi — hoi o tab hien tai khong doi nghia gi.
        w5.tabs.setCurrentWidget(w5.tab_settings)
        w5.show()
        spin(150)
        check("tab Cai dat khong hien o so luong",
              w5.tab_settings.sp_conc.isVisible(), False)
        check("tab Cai dat khong hien o so luong (visibleTo)",
              w5.tab_settings.sp_conc.isVisibleTo(w5.tab_settings), False)
        check("tab Cai dat khong hien o so luong (visibleTo cua tab)",
              w5.tab_settings.sp_conc.isVisibleTo(w5.tabs), False)
        w5.tabs.setCurrentWidget(w5.tab_task)
        spin(150)
        check("tab Tác vụ THÌ hien o so luong",
              w5.sp_threads.isVisibleTo(w5), True)
        # và ô ẩn phải được đồng bộ theo ô đang hiện, ngay khi đổi
        w5.sp_threads.setValue(33)
        spin(200)
        check("o an cua tab Cai dat theo o dang hien",
              w5.tab_settings.sp_conc.value(), 33)
        w5.sp_retry.setValue(4)
        spin(200)
        check("o retry an cua tab Cai dat theo",
              w5.tab_settings.sp_retry.value(), 4)
        w5.close()
        spin(150)
        del w5

        print("\n=== 7. Goi y so luong theo may ===")
        w6 = MainWindow()
        spin()
        sug = w6._suggest_threads()
        check("goi y > 0", sug > 0, True)
        check("goi y khong vuot qua tran 50", sug <= 50, True)
        check("goi y it nhat 4", sug >= 4, True)
        w6.sp_threads.setValue(sug)
        spin(150)
        check("dat dung goi y thi khong canh bao",
              "⚠" in w6.lbl_thread_hint.text(), False)
        w6.sp_threads.setValue(500)
        spin(150)
        check("vuot tran thi co canh bao",
              "⚠" in w6.lbl_thread_hint.text(), True)
        w6.close()
        spin(150)
        del w6

    finally:
        restore()
        print(f"\n     da khoi phuc lai {path}")

    print(f"\n{'=' * 58}\n  {PASS} pass, {FAIL} fail\n{'=' * 58}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

"""Kiểm tra tham số chạy được LƯU lại — mở lại app phải còn nguyên.

Lỗi đã gặp: ô "Số luồng" sửa xong không ăn, mở lại app về 10.
Nguyên nhân thật: tab Cài đặt có MỘT ô số luồng nữa (ẩn đi sau này) và
`closeEvent` gọi `_sync_to_settings()` của tab đó — lấy giá trị cũ rồi
ghi đè lên thứ người dùng vừa chỉnh ở tab Tác vụ.

Từ nay các ô số luồng / trễ / số lần thử lại đã BỎ khỏi UI: app đọc
thẳng từ settings.json, nên test kiểm tra luồng đó — sửa settings thì
lần chạy kế phải dùng đúng giá trị đó, và đóng/mở lại app không mất.

Test này dùng settings.json thật (đường dẫn config thật của user) và
tự khôi phục lại sau khi chạy, không phá cấu hình của bạn.

Chạy:  python test_settings_persist.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Test dùng settings.json RIÊNG (thư mục tạm) — không đụng vào file thật
# của người dùng.
os.environ["APPDATA"] = os.path.join(
    tempfile.mkdtemp(prefix="tiktok_test_"), "TikTokManager")
os.environ["XDG_CONFIG_HOME"] = os.environ["APPDATA"]

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
                  "mode": "like_cid"})
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
        check("so luong mac dinh la 10", w1.settings.concurrency, 10)
        check("retry mac dinh la 1", w1.settings.retries, 1)
        cfg = w1._collect_cfg()
        check("app lay so luong tu settings", cfg.concurrency, 10)
        check("app lay so lan thu lai tu settings", cfg.retries, 1)
        check("app lay do loi tu settings",
              (cfg.delay_min, cfg.delay_max), (0.0, 1.0))

        print("\n=== 2. Tham so duoc ghi xuong dia ngay ===")
        w1.settings.concurrency = 15
        w1.settings.retries = 3
        w1.settings.delay_min = 0.5
        w1.settings.delay_max = 2.5
        w1._save_settings_quiet()
        w1.sp_pick.setValue(60)
        w1.rb_pick_random.setChecked(True)
        spin(250)
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
        cfg = w2._collect_cfg()
        check("so luong = 15", cfg.concurrency, 15)
        check("retry = 3", cfg.retries, 3)
        check("tre 0.5 - 2.5 s", (cfg.delay_min, cfg.delay_max), (0.5, 2.5))
        check("so profile = 60", w2.sp_pick.value(), 60)
        check("cach chon = random", w2._pick_how(),
              AccountTableModel.PICK_RANDOM)

        print("\n=== 5. Bat buoc: dong app khong duoc LAM mat gia tri ===")
        w3 = MainWindow()
        spin()
        w3.settings.concurrency = 42
        w3.settings.retries = 5
        w3._save_settings_quiet()
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
        cfg = w4._collect_cfg()
        check("mo lai thay 42 luong", cfg.concurrency, 42)
        check("mo lai thay 5 retry", cfg.retries, 5)
        w4.close()
        spin(150)
        del w4

        print("\n=== 6. Cac o da bi bo khoi UI ===")
        w5 = MainWindow()
        spin()
        for attr in ("sp_threads", "sp_retry", "sp_dmin", "sp_dmax",
                     "cb_verify", "cb_pool", "in_proxy", "in_signer",
                     "backend_kind", "btn_dry", "lbl_thread_hint"):
            check(f"khong con '{attr}'", hasattr(w5, attr), False)
        for attr in ("sp_conc", "sp_retry", "sp_dmin", "sp_dmax",
                     "cb_verify", "in_signer"):
            check(f"tab Cai dat khong con '{attr}'",
                  hasattr(w5.tab_settings, attr), False)
        # Hai tab "Tác vụ" và "Chi tiết" đã bị bỏ; chỉ còn màn chính
        # + Cài đặt. Kiểm tra đúng những gì còn tồn tại.
        check("tab 'Chi tiết' da bi bo", hasattr(w5, "tab_detail"), False)
        check("tab 'Tác vụ' da bi bo", hasattr(w5, "tab_task"), False)
        check("van con tab man chinh", hasattr(w5, "tab_main"), True)
        check("van con tab Cai dat", hasattr(w5, "tab_settings"), True)
        check("chi con 2 tab", w5.tabs.count(), 2)
        w5.close()
        spin(150)
        del w5

        print("\n=== 7. Gia tri da luu duoc dung khi chay ===")
        w6 = MainWindow()
        spin()
        check("so luong van la 42 (khong bi ghi de)", w6.settings.concurrency, 42)
        check("retry van la 5 (khong bi ghi de)", w6.settings.retries, 5)
        cfg = w6._collect_cfg()
        check("app van chay duoc (so luong >= 1)", cfg.concurrency >= 1, True)
        check("so lan thu lai khong am", cfg.retries >= 0, True)
        check("xac minh like luon bat", cfg.verify, True)
        check("backend luon la http", w6.settings.backend_kind, "http")
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

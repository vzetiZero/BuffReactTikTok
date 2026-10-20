"""Test nhớ đường dẫn file cookie — nạp xong thì lần sau khỏi nạp lại.

Ý do: trước đây đường dẫn chỉ được ghi vào RAM và chỉ lưu xuống đĩa khi
ĐÓNG app. App bị tắt đột ngột (crash / kill) là mất, lần sau phải bấm
'Nạp cookie' lại. Nay nạp file là lưu ngay đường dẫn xuống settings.json.

Chạy:  python test_cookie_path.py
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.settings import AppSettings, save_cookie_file_path

PASS, FAIL = 0, 0


def check(label, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  OK   {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label}\n        got  {got!r}\n        want {want!r}")


def main():
    tmp = Path(tempfile.mkdtemp())
    cfg = tmp / "settings.json"

    print("\n=== 1. luu duong dan vao file cau hinh ===")
    p = save_cookie_file_path("/tmp/accounts/cookie.txt", cfg)
    check("file cau hinh da tao", p.exists(), True)
    raw = json.loads(cfg.read_text(encoding="utf-8"))
    check("da ghi last_cookie_file", raw.get("last_cookie_file"),
          "/tmp/accounts/cookie.txt")

    print("\n=== 2. doc lai duoc tu AppSettings ===")
    s = AppSettings.load(cfg)
    check("last_cookie_file doc lai dung", s.last_cookie_file,
          "/tmp/accounts/cookie.txt")

    print("\n=== 3. khong lam hong cau hinh khac ===")
    raw["concurrency"] = 37
    raw["proxy_text"] = "http://1.2.3.4:8080"
    cfg.write_text(json.dumps(raw, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    save_cookie_file_path("/tmp/accounts/other.txt", cfg)
    raw2 = json.loads(cfg.read_text(encoding="utf-8"))
    check("concurrency giu nguyen", raw2.get("concurrency"), 37)
    check("proxy_text giu nguyen", raw2.get("proxy_text"), "http://1.2.3.4:8080")
    check("duong dan da doi", raw2.get("last_cookie_file"),
          "/tmp/accounts/other.txt")

    print("\n=== 4. file cau hinh chua co -> tao moi ===")
    fresh = tmp / "sub" / "settings.json"
    save_cookie_file_path("/tmp/x.txt", fresh)
    check("da tao file moi", fresh.exists(), True)
    check("noi dung dung",
          json.loads(fresh.read_text(encoding="utf-8")).get("last_cookie_file"),
          "/tmp/x.txt")

    print("\n=== 5. file cau hinh hong -> khong crash, van ghi duoc ===")
    bad = tmp / "bad.json"
    bad.write_text("{ khong phai json", encoding="utf-8")
    save_cookie_file_path("/tmp/y.txt", bad)
    check("file hong duoc ghi lai",
          json.loads(bad.read_text(encoding="utf-8")).get("last_cookie_file"),
          "/tmp/y.txt")

    print("\n=== 6. end-to-end: nap file -> dong app -> mo lai tu nap ===")
    e2e(tmp)

    print(f"\n{'='*50}\n  {PASS} pass, {FAIL} fail\n{'='*50}")
    return 1 if FAIL else 0


def e2e(tmp: Path) -> None:
    """Nạp file cookie trong GUI -> tắt app -> mở lại: tự nạp, khỏi bấm."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    cfg_dir = tmp / "appdata"
    os.environ["APPDATA"] = str(cfg_dir)
    os.environ["XDG_CONFIG_HOME"] = str(cfg_dir)

    from PySide6.QtWidgets import QApplication
    import ui.main_window as mw
    from core.settings import default_path

    cookie_file = tmp / "cookie.txt"
    cookie_file.write_text(
        "user123|@acc01|a@b.c|pass1|msToken1|dev1|alias|a=1; sessionid_ss=abc%3D%3D; sid_tt=sid1\n",
        encoding="utf-8",
    )

    class FakeDialog:
        @staticmethod
        def getOpenFileName(*_a, **_k):
            return str(cookie_file), ""

    mw.QFileDialog = FakeDialog

    app = QApplication.instance() or QApplication([])
    w = mw.MainWindow()
    w.on_load_file()
    check("nap duoc tai khoan", len(w.accounts), 1)

    cfg = default_path()
    check("da tao settings.json", cfg.exists(), True)
    raw = json.loads(cfg.read_text(encoding="utf-8"))
    check("duong dan da luu xuong dia", raw.get("last_cookie_file"),
          str(cookie_file))

    w.close()

    # Mở app lần 2: phải tự nạp từ đường dẫn đã lưu.
    w2 = mw.MainWindow()
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 1.0:
        app.processEvents()
        time.sleep(0.01)
    check("mo lai tu nap (khong can bam 'Nap cookie')", len(w2.accounts), 1)
    w2.close()


if __name__ == "__main__":
    sys.exit(main())

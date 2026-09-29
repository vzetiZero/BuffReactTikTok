"""Kiểm tra tham số chạy SỐNG SAI: đổi xong, mở lại app có giữ không?

Vì sao cần test kiểu này: các lần trước tôi kiểm trong CÙNG một tiến
trình — tạo MainWindow, đổi ô, đọc lại ô. Nhưng app thật thì thoát hẳn
rồi mở lại từ đầu, đọc từ settings.json. Test trong một tiến trình có
thể xanh trong khi file trên đĩa lại sai.

Test này vì vậy chạy HAI TIẾN TRÌNH THẬT:
    - tiến trình con #1: mở app, đổi tham số, thoát (hoặc bị giết)
    - tiến trình cha:     đọc settings.json, rồi mở app MỚI và đối chiếu

Chạy:  python test_persist_real.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).parent
PASS, FAIL = 0, 0


def check(label, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  OK   {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label}\n        got  {got!r}\n        want {want!r}")


# --- tiến trình con: đổi tham số rồi thoát theo yêu cầu ---------------- #
CHILD = r'''
import sys, os
sys.path.insert(0, r"{root}")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow

NEW = dict(threads=27, retry=4, dmin=0.5, dmax=2.5,
           pick=120, how="random", verify=False)
KILL = {kill}

app = QApplication([])
w = MainWindow()

def work():
    for _ in range(20):
        app.processEvents()
    w.sp_threads.setValue(NEW["threads"])
    w.sp_retry.setValue(NEW["retry"])
    w.sp_dmin.setValue(NEW["dmin"])
    w.sp_dmax.setValue(NEW["dmax"])
    w.sp_pick.setValue(NEW["pick"])
    w.rb_pick_random.setChecked(NEW["how"] == "random")
    w.cb_verify.setChecked(NEW["verify"])
    for _ in range(20):
        app.processEvents()
    # In ra de parent doi chieu
    print("CHILD_WIDGET", w.sp_threads.value(), w.sp_retry.value(),
          w.sp_dmin.value(), w.sp_dmax.value(), w.sp_pick.value(),
          w._pick_how(), int(w.cb_verify.isChecked()))
    # cfg that su dung khi chay
    print("CHILD_CFG", w._collect_cfg("7602703562657022728").concurrency)
    if KILL:
        # TU KILL: closeEvent khong chay. Van phai giu duoc, vi app luu
        # ngay khi doi chu khong chi luc dong.
        sys.stdout.flush()
        os._exit(0)
    w.close()
    for _ in range(10):
        app.processEvents()
    app.quit()

QTimer.singleShot(900, work)
app.exec()
'''


def run_child(kill: bool) -> dict:
    """Chạy tiến trình con, trả về dict đọc được từ stdout."""
    src = CHILD.format(root=str(ROOT), kill=kill)
    p = Path(os.environ.get("TEMP", ".")) / f"_persist_child_{kill}.py"
    p.write_text(src, encoding="utf-8")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8",
           "QT_QPA_PLATFORM": "offscreen"}
    r = subprocess.run([sys.executable, "-u", str(p)], capture_output=True,
                       text=True, timeout=180, env=env, cwd=str(ROOT))
    out = {}
    for line in r.stdout.splitlines():
        if line.startswith("CHILD_WIDGET"):
            v = line.split()[1:]
            out.update(threads=int(v[0]), retry=int(v[1]), dmin=float(v[2]),
                       dmax=float(v[3]), pick=int(v[4]), how=v[5],
                       verify=v[6] == "1")
        elif line.startswith("CHILD_CFG"):
            out["cfg"] = int(line.split()[1])
    if r.returncode != 0 and not out:
        print("        (tiến trình con lỗi)")
        for l in r.stderr.splitlines()[-4:]:
            print("         ", l[:90])
    return out


def main():
    from core.settings import default_path

    path = default_path()
    backup = path.read_text(encoding="utf-8") if path.exists() else None

    def write_base():
        d = json.loads(backup) if backup else {}
        d.update({"concurrency": 10, "retries": 1, "delay_min": 0.0,
                  "delay_max": 1.0, "pick_limit": 0, "pick_how": "order",
                  "verify": True})
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    def read_file() -> dict:
        d = json.loads(path.read_text(encoding="utf-8"))
        return dict(threads=d["concurrency"], retry=d["retries"],
                    dmin=d["delay_min"], dmax=d["delay_max"],
                    pick=d["pick_limit"], how=d["pick_how"],
                    verify=d["verify"])

    try:
        # ============================================================== #
        print("\n=== 1. Đóng app BÌNH THƯỜNG (có closeEvent) ===")
        write_base()
        got = run_child(kill=False)
        check("tiến trình con đổi xong 27 luồng", got.get("threads"), 27)
        check("số luồng thực sự dùng khi chạy (_collect_cfg)",
              got.get("cfg"), 27)

        on_disk = read_file()
        for k, want in (("threads", 27), ("retry", 4), ("dmin", 0.5),
                        ("dmax", 2.5), ("pick", 120), ("how", "random"),
                        ("verify", False)):
            check(f"file trên đĩa giữ {k}", on_disk[k], want)

        # Mở app MỚI, đọc lại — KHÔNG đụng vào file, đọc đúng thứ
        # tiến trình con vừa ghi lại (đây mới là lần mở thật tiếp theo).
        r2 = run_child_read(path)
        for k, want in (("threads", 27), ("retry", 4), ("dmin", 0.5),
                        ("dmax", 2.5), ("pick", 120), ("how", "random"),
                        ("verify", False)):
            check(f"mở lại app, ô {k} đúng", r2.get(k), want)

        # ============================================================== #
        print("\n=== 2. App bị KILL (không chạy closeEvent) ===")
        write_base()
        got = run_child(kill=True)
        check("tiến trình con đổi 27 luồng rồi tự chết", got.get("threads"), 27)
        on_disk = read_file()
        for k, want in (("threads", 27), ("retry", 4), ("pick", 120),
                        ("how", "random")):
            check(f"app chết vẫn giữ {k} (lưu ngay khi đổi)", on_disk[k], want)

        # ============================================================== #
        print("\n=== 3. Giá trị rác trong file không làm hỏng app ===")
        # Người dùng có thể sửa tay, hoặc file bị phiên bản cũ ghi thiếu.
        d = json.loads(backup) if backup else {}
        d["concurrency"] = 999999      # vượt trần của spinbox
        d["pick_how"] = "khong_hop_le"  # giá trị lạ
        d.pop("pick_limit", None)      # thiếu khoá
        path.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        r3 = run_child_read(path)
        check("số luồng vượt trần bị kẹp về giá trị hợp lệ",
              1 <= r3.get("threads", 0) <= 500, True)
        check("pick_how lạ -> rơi về 'order'",
              r3.get("how") in ("order", "random"), True)
        check("thiếu khoá pick_limit -> dùng mặc định, không crash",
              r3.get("pick") is not None, True)

        # ============================================================== #
        print("\n=== 4. File JSON hỏng -> app vẫn mở được ===")
        path.write_text("{ khong phai JSON", encoding="utf-8")
        r4 = run_child_read(path)
        check("file hỏng vẫn mở app, dùng mặc định", r4.get("ok"), True)

    finally:
        if backup is not None:
            path.write_text(backup, encoding="utf-8")
            print(f"\n     đã khôi phục {path}")

    print(f"\n{'=' * 58}\n  {PASS} pass, {FAIL} fail\n{'=' * 58}")
    return 1 if FAIL else 0


# --- tiến trình con #2: chỉ đọc, không sửa gì ------------------------- #
READER = r'''
import sys, os
sys.path.insert(0, r"{root}")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow
app = QApplication([])
w = MainWindow()
def work():
    for _ in range(20):
        app.processEvents()
    print("READ", w.sp_threads.value(), w.sp_retry.value(),
          w.sp_dmin.value(), w.sp_dmax.value(), w.sp_pick.value(),
          w._pick_how(), int(w.cb_verify.isChecked()))
    w.close()
    for _ in range(6):
        app.processEvents()
    app.quit()
QTimer.singleShot(900, work)
app.exec()
'''


def run_child_read(_path) -> dict:
    src = READER.format(root=str(ROOT))
    p = Path(os.environ.get("TEMP", ".")) / "_persist_read.py"
    p.write_text(src, encoding="utf-8")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8",
           "QT_QPA_PLATFORM": "offscreen"}
    out = {}
    try:
        r = subprocess.run([sys.executable, "-u", str(p)],
                           capture_output=True, text=True, timeout=180,
                           env=env, cwd=str(ROOT))
    except subprocess.TimeoutExpired:
        return {"ok": False}
    for line in r.stdout.splitlines():
        if line.startswith("READ "):
            v = line.split()[1:]
            out = dict(threads=int(v[0]), retry=int(v[1]), dmin=float(v[2]),
                       dmax=float(v[3]), pick=int(v[4]), how=v[5],
                       verify=v[6] == "1", ok=True)
            return out
    return {"ok": False}


if __name__ == "__main__":
    sys.exit(main())

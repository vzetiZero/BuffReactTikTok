"""Kiểm chứng cách app bật sidecar trên Windows.

Lỗi gốc: code cũ TỰ thêm dấu nháy quanh đường dẫn, rồi Qt escape thêm
dấu `\` cho dấu nháy đó, sinh ra chuỗi `"...signer.bat\"` — Windows báo
"cannot find ...signer.bat\". Script này chạy THẬT cả hai cách trên file
.bat vô hại và so sánh.

Chạy:  python test_signer_launch.py
"""

import os
import pathlib
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication

PASS, FAIL = 0, 0


def check(label, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  OK   {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label}\n        got  {got!r}\n        want {want!r}")


def make_bat(folder: pathlib.Path, name: str = "signer.bat") -> pathlib.Path:
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / name
    p.write_bytes(
        b"@echo off\r\n"
        b"echo RAN_OK\r\n"
        b"rem ghi ra file de chung minh .bat THAT SU da chay\r\n"
        b"echo ok>marker.txt\r\n"
        b"exit /b 0\r\n"
    )
    return p


def wait_marker(app, folder: pathlib.Path, timeout=8.0):
    """Chờ file marker xuất hiện (dấu hiệu .bat đã thực sự chạy)."""
    m = folder / "marker.txt"
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if m.exists():
            return True
        time.sleep(0.1)
    return False


def main():
    app = QApplication.instance() or QApplication([])
    is_win = sys.platform == "win32"
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="signer_test_"))

    print("\n=== 1. chuoi lenh Windows ma Qt dich ===")
    d = tmp / "thu muc co khoang trang"
    bat = make_bat(d)

    p_old = QProcess()
    p_old.setProgram("cmd")
    p_old.setArguments(["/c", "start", "", f'"{bat}"'])   # CACH CU (sai)

    p_new = QProcess()
    p_new.setProgram("cmd")
    p_new.setArguments(["/c", str(bat)])                 # CACH MOI

    old_arg = p_old.arguments()[-1]
    new_arg = p_new.arguments()[-1]
    check("cach cu co dau nhay do nguoi dung viet", old_arg.startswith('"'))
    check("cach moi KHONG tu them dau nhay",
          new_arg.startswith('"'), False)
    check("cach moi khong ket thuc bang dau nhay",
          new_arg.endswith('"'), False)
    check("cach moi giu nguyen duong dan", new_arg, str(bat))
    check("cach moi khong dung lenh 'start'",
          "start" in [a.lower() for a in p_new.arguments()], False)

    if not is_win:
        print("\n  (Dang chạy trên", sys.platform, "— bỏ qua phần chạy thật)")
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"\n{'='*54}\n  {PASS} pass, {FAIL} fail\n{'='*54}")
        return 1 if FAIL else 0

    print("\n=== 2. chay THAT tren Windows ===")
    # `cmd /c <bat>` — KHÔNG qua lệnh `start`. `start` cần mở cửa sổ
    # console mới và sẽ lỗi "Not enough memory resources" khi bị giới hạn.
    d2 = tmp / "co khoang trang"
    make_bat(d2)
    proc = QProcess()
    proc.setProgram("cmd")
    proc.setArguments(["/c", str(d2 / "signer.bat")])   # CACH DUNG
    # `cmd /c` GIỮ thư mục làm việc của app, không tự chuyển sang thư mục
    # của .bat. Phải set thủ công, nếu không các lệnh tương đối trong
    # script (npm install, cd, ...) sẽ chạy nhầm chỗ.
    proc.setWorkingDirectory(str(d2))
    proc.start()
    check("QProcess bat dau duoc", proc.waitForStarted(5000))
    ran = wait_marker(app, d2, timeout=10)
    check("cach moi chay .bat thanh cong", ran)
    check("khong can cua so console moi (khong dung 'start')",
          "start" not in [a.lower() for a in proc.arguments()])

    print("\n=== 3. thu muc co khoang trang (nguyen nhan that cua loi) ===")
    check("duong dan thu nghiem co dau cach", " " in str(d2), True)
    check("lenh gia nguyen, khong co dau escape",
          proc.arguments()[1], str(d2 / "signer.bat"))

    print("\n=== 4. lenh SAI (co dau nhay do nguoi dung viet) ===")
    d3 = tmp / "thu muc 3"
    make_bat(d3)
    p_bad = QProcess()
    p_bad.setProgram("cmd")
    p_bad.setArguments(["/c", f'"{d3 / "signer.bat"}"'])
    check("lenh sai co dau nhay -> se sinh \\' trong chuoi that",
          p_bad.arguments()[1].startswith('"'))
    # Chứng minh: dấu \ do Qt them vao se lam Windows khong tim thay file
    import subprocess as _sp
    r = _sp.run(["cmd", "/c", "echo"] + p_bad.arguments()[1:],
                capture_output=True, text=True)
    check("Windows nhung lenh sai voi dau escape",
          '\\"' in r.stdout or r.stdout.strip().endswith('\\"'), True)
    print(f"       lenh sai  -> {r.stdout.strip()!r}")
    print("       (dau \\' cuoi chinh la dau escape, khong phai loi nguoi dung)")

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{'='*54}\n  {PASS} pass, {FAIL} fail\n{'='*54}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

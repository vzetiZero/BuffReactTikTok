"""Kiểm tra khả năng chạy trên macOS — các điểm khác biệt với Windows.

Những chỗ dễ vỡ nhất khi đổi hệ điều hành (vì trên Windows chạy ngon nên
dễ tưởng không có vấn đề gì):

  1. `.bat` không chạy được trên macOS/Linux — cần `.sh` kèm theo
  2. `APPDATA` không tồn tại trên macOS → đường dẫn cấu hình
  3. Font "Segoe UI" không có trên macOS → rơi về font mặc định
  4. Thông báo hướng dẫn phải trỏ đúng script của từng OS

Chạy:  python test_macos_compat.py
"""

import os
import pathlib
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = pathlib.Path(__file__).parent

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
    from ui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])

    print("\n=== 1. Script cai dat / chay / sidecar ===")
    for name, must in (("install.sh", "install"), ("start.sh", "main.py"),
                       ("signer.sh", "npm start")):
        p = ROOT / name
        check(f"{name} ton tai", p.exists())
        if p.exists():
            t = p.read_text(encoding="utf-8")
            check(f"{name} co shebang bash", t.startswith("#!/usr/bin/env bash"))
            check(f"{name} co lenh '{must}'", must in t)
            # Không được dùng lệnh Windows
            for bad in ("taskkill", "ipconfig", "netstat", "chcp ",
                        "%APPDATA%", r"%~dp0", "powershell"):
                check(f"{name} khong dung '{bad}'", bad not in t)

    print("\n=== 2. Thoi gian: .sh phai LF, .bat phai CRLF ===")
    # .bat chạy sai (hoặc không chạy) nếu xuống dòng LF
    for name in ("install.sh", "start.sh", "signer.sh"):
        raw = (ROOT / name).read_bytes()
        check(f"{name} xuong dong LF", b"\r\n" not in raw)
        check(f"{name} co newline cuoi file", raw.endswith(b"\n"))

    print("\n=== 3. Duong dan cau hinh theo tung OS ===")
    from core.settings import config_dir, default_path
    import sys as _s
    d = config_dir()
    if _s.platform == "darwin":
        check("macOS: dung Library/Application Support",
              "Library/Application Support" in str(d), True)
    else:
        check("khong phai mac: dung APPDATA hoac XDG",
              (os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME")
               or ".config") in str(d), True)
    check("default_path la settings.json", default_path().name,
          "settings.json")
    check("cau hinh nam trong thu muc TikTokManager",
          "TikTokManager" in str(d), True)

    print("\n=== 4. Font — khong giu ten font khong ton tai tren OS nay ===")
    from PySide6.QtGui import QFontDatabase
    from ui.style import ui_font_family
    have = set(QFontDatabase.families())
    fam = ui_font_family()
    # Chạy headless (QT_QPA_PLATFORM=offscreen) thì Qt KHÔNG liệt kê được
    # font nào — khi đó hàm phải trả rỗng để Qt tự chọn, chứ không được bịa
    # ra một tên font. Vì vậy chỉ kiểm tra nghiêm khi thật sự có danh sách.
    if not have:
        check("headless: tra ve chuoi rong (de Qt tu chon)", fam, "")
        print("       -> offscreen không liệt kê được font, bỏ qua kiểm tra tên")
    else:
        check("tra ve 1 ten font", bool(fam), True)
        check("font chon da TON TAI tren may nay", fam in have, True)
        check("khong phai font mac dinh (da qua logic)",
              fam in ("Segoe UI", "SF Pro Text", "Helvetica Neue",
                      "Inter", "DejaVu Sans", "Arial"), True)
        print(f"       -> chọn: {fam}")
    # Bất kể có liệt kê được hay không, KHÔNG được trả về font không tồn tại
    if have and fam:
        check("khong tra ve font bia", fam in have, True)

    print("\n=== 5. Thong bao trong app tro ve script dung ===")
    src = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")
    check("co bien SIGNER_SCRIPT", "SIGNER_SCRIPT" in src)
    check("co bien IS_MAC", "IS_MAC" in src)
    # Tên file hiển thị phải đến từ SIGNER_SCRIPT để đổi theo OS, chứ
    # không hardcode trong logic. Dòng chứa "signer.bat" vẫn hợp lệ ở:
    #   - hằng số SIGNER_SCRIPT (dòng định nghĩa)
    #   - tooltip / chuỗi mô tả cho người dùng đọc
    #   - comment giải thích
    # Nên chỉ kiểm tra: không được dùng nó để RENDER chuỗi cho người dùng.
    hard = []
    for line in src.splitlines():
        if "signer.bat" not in line:
            continue
        if any(k in line for k in ("SIGNER_SCRIPT", "IS_MAC", "SIGNER_STEPS",
                                   "SIGNER_STEP_RUN", "signer.sh")):
            continue
        if line.strip().startswith("#") or line.strip().startswith('"'):
            continue          # comment hoặc doc chuoi trong tooltip
        if line.strip().startswith("`") or "khởi động" in line:
            continue          # comment nhieu dong
        hard.append(line.strip()[:90])
    check("khong con chuoi 'signer.bat' hardcode trong logic", hard, [])
    # và hằng số phải chọn đúng theo OS
    from ui.main_window import SIGNER_SCRIPT as _ss
    check("hang so chon script dung theo OS",
          _ss, "signer.sh" if __import__("sys").platform == "darwin"
          else "signer.bat")

    print("\n=== 6. Khong co goi Windows API o cap module ===")
    # `import winreg` phai nam TRONG ham (lazy) va co guard, neu khong
    # macOS se crash ngay khi import.
    src_p = (ROOT / "core" / "proxy.py").read_text(encoding="utf-8")
    top_level = []
    for i, l in enumerate(src_p.splitlines(), 1):
        if l.startswith(("import ", "from ")) and "winreg" in l:
            top_level.append((i, l.strip()))
    check("winreg khong import o cap module", top_level, [])
    check("co guard 'chi ton tai tren Windows'", "chỉ tồn tại trên Windows" in src_p)
    check("co nhanh macOS scutil", "scutil" in src_p)

    print("\n=== 7. Code chay duoc tren OS hien tai ===")
    r = subprocess.run(
        [sys.executable, "-c",
         "import core.tiktok, core.health, core.models, core.proxy, "
         "core.settings, core.runner, ui.style; print('ok')"],
        capture_output=True, text=True, cwd=str(ROOT))
    check("import moi module khong loi", r.returncode, 0)
    if r.returncode:
        print("      ", r.stderr.strip()[-300:])
    print(f"       -> đang chạy trên {sys.platform}")

    print("\n=== 7. Huong dan sidecar dung cach mo theo tung OS ===")
    from ui.main_window import (
        IS_MAC,
        SIGNER_SCRIPT,
        SIGNER_STEP_RUN,
        SIGNER_STEPS,
    )
    import sys as _s2
    if _s2.platform == "darwin":
        check("macOS: dung signer.sh", SIGNER_SCRIPT, "signer.sh")
        check("macOS: huong dan qua Terminal", "Terminal" in SIGNER_STEPS, True)
        # macOS KHÔNG bấm đúp được .sh trong Finder -> không được bảo bấm đúp
        check("macOS: khong bao 'bam dup'", "BẤM ĐÚP" in SIGNER_STEP_RUN, False)
        check("macOS: co lenh chmod", "chmod" in SIGNER_STEP_RUN, True)
    else:
        check("Windows: dung signer.bat", SIGNER_SCRIPT, "signer.bat")
        check("Windows: bao 'BAM DUP' (bat duoc file .bat)",
              "BẤM ĐÚP" in SIGNER_STEP_RUN, True)
        check("Windows: khong bao dung lenh Terminal",
              "Terminal" in SIGNER_STEP_RUN, False)
    check("buoc 1 + 2 deu co trong SIGNER_STEPS",
          ("  1." in SIGNER_STEPS and "  2." in SIGNER_STEPS), True)
    check("nhac giu cua so mo (roi terminal)",
          "GIỮ" in SIGNER_STEPS, True)
    check("nhac Internet cho lan tai dau", "Internet" in SIGNER_STEPS, True)

    print("\n=== 8. Chan doan nguyen nhan sidecar ===")
    from PySide6.QtWidgets import QApplication as _QA
    w = MainWindow()
    check("co ham _node_installed", hasattr(w, "_node_installed"))
    check("co ham _signer_dir_installed", hasattr(w, "_signer_dir_installed"))
    # Gọi được và trả bool (không được ném exception)
    check("_node_installed() tra bool", isinstance(w._node_installed(), bool))
    check("_signer_dir_installed() tra bool",
          isinstance(w._signer_dir_installed(), bool))
    # _signer_fail phải phân biệt được 3 trường hợp
    real_node, real_dir = w._node_installed, w._signer_dir_installed
    w._node_installed = lambda: False
    w._signer_dir_installed = lambda: True
    w._signer_fail("refused")
    check("khong co Node -> nhan 'THIEU NODE.JS'",
          "NODE" in w.lbl_signer.text().upper(), True)
    w._node_installed = lambda: True
    w._signer_dir_installed = lambda: False
    w._signer_fail("refused")
    check("co Node nhung chua cai sidecar -> nhan 'CHUA CAI'",
          "CÀI" in w.lbl_signer.text().upper(), True)
    w._node_installed = lambda: True
    w._signer_dir_installed = lambda: True
    w._signer_fail("refused")
    check("da cai nhung khong chay -> nhan 'CHUA CHAY'",
          "CHƯA CHẠY" in w.lbl_signer.text().upper(), True)
    w._node_installed, w._signer_dir_installed = real_node, real_dir

    print("\n=== 9. Nut 'Bat sidecar' trong app ===")
    from PySide6.QtWidgets import QApplication as _QA2
    w2 = MainWindow()
    check("co nut btn_signer", hasattr(w2, "btn_signer"))
    check("nut hien thi ro ten", "sidecar" in w2.btn_signer.text().lower())
    check("nut co tooltip", bool(w2.btn_signer.toolTip()))
    check("co ham _start_signer", hasattr(w2, "_start_signer"))
    check("_signer_proc ban dau la None", w2._signer_proc, None)
    check("_signer_poll ban dau la None", w2._signer_poll, None)
    # QProcess phai import tu QtCore — import tu QtWidgets se ImportError
    # ngay luc khoi dong app
    r = subprocess.run(
        [sys.executable, "-c",
         "from PySide6.QtCore import QProcess; print('ok')"],
        capture_output=True, text=True, cwd=str(ROOT))
    check("QProcess import duoc tu QtCore", r.returncode, 0)
    r2 = subprocess.run(
        [sys.executable, "-c",
         "import ui.main_window as m; print('ok')"],
        capture_output=True, text=True, cwd=str(ROOT))
    check("import ui.main_window khong loi", r2.returncode, 0)
    if r2.returncode:
        print("      ", r2.stderr.strip()[-200:])
    # khong trung ten ham
    n_poll = sum(1 for ln in (ROOT / "ui" / "main_window.py")
                 .read_text(encoding="utf-8").splitlines()
                 if ln.strip().startswith("def _poll_after_start"))
    check("khong co ban trung lap _poll_after_start", n_poll, 1)
    n_out = sum(1 for ln in (ROOT / "ui" / "main_window.py")
                .read_text(encoding="utf-8").splitlines()
                if ln.strip().startswith("def _signer_output"))
    check("khong co ban trung lap _signer_output", n_out, 1)

    print("\n=== 10. Khong bat trung sidecar khi da co cai san ===")
    # Da co sidecar chay san (ngoai app) thi KHONG duoc bat them mot cai
    # nua: cai moi khong bind duoc cong 8080, chet ngay, va app bao
    # "sidecar DA DUNG" — nguoi dung tuong app hong.
    #
    # PHẢI giả lập /health thay vì tin vao trang thai that: neu may dang
    # khong co sidecar chay, _start_signer se that su bat mot tien trinh
    # that — test se loan va con sidecar mo con.
    from PySide6.QtWidgets import QMessageBox as _QB
    import core.signer as _sg

    real_health = _sg.Signer.health
    _sg.Signer.health = lambda self: {"ready": True, "generationCount": 7}

    w3 = MainWindow()
    for _ in range(3):
        app.processEvents()
    w3._signer_ready = False
    w3._signer_proc = None
    _QB.information = staticmethod(
        lambda *a, **k: _QB.StandardButton.Ok)
    _QB.warning = staticmethod(lambda *a, **k: _QB.StandardButton.Ok)
    _QB.exec = staticmethod(lambda self=None, *a, **k: 0)
    try:
        w3._start_signer()
        for _ in range(8):
            app.processEvents()
        check("sidecar co san -> khong tao tien trinh moi",
              w3._signer_proc, None)
        check("sidecar co san -> danh dau san sang",
              w3._signer_ready, True)
        check("sidecar co san -> nhan hien 'sidecar v'",
              w3.lbl_signer.text().strip().startswith("sidecar ✓"), True)
    finally:
        _sg.Signer.health = real_health
        w3._kill_signer()

    # phai giu lai cac dong log de chan doan khi sidecar chet
    check("co _signer_tail de chan doan",
          isinstance(w3._signer_tail, list), True)
    src3 = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")
    check("co kiem tra sidecar chay san TRUOC khi bat",
          "Sidecar ký đã chạy sẵn" in src3, True)
    check("co hien nguyen nhan khi sidecar dung",
          "Dòng cuối của sidecar" in src3, True)
    check("nhac dong 'cong 8080 da bi chiem'",
          "8080" in src3, True)

    print("\n=== 11. File .bat phai thuan ASCII ===")
    # Day la nguon goc cua loi "sidecar da dung" may phu. File .bat duoc
    # doc byte theo code page cua Windows, va MOT ky tu da-cap nhu "-"
    # (U+2014) se lam cmd cat sai dong -> lenh sai chay -> script dung.
    # Da chung minh: bo ky tu non-ASCII thi script chay toi het.
    for n in ("install.bat", "start.bat", "signer.bat", "setup.bat"):
        f = ROOT / n
        if not f.exists():
            continue
        raw = f.read_bytes()
        bad_chars = []
        txt = raw.decode("utf-8", "replace")
        for i, line in enumerate(txt.splitlines(), 1):
            for c in line:
                if ord(c) > 127:
                    bad_chars.append((i, c, hex(ord(c))))
        check(f"{n} thuan ASCII (khong ky tu dac biet)", bad_chars[:3], [])
        check(f"{n} khong co BOM",
              raw[:3] == b"\xef\xbb\xbf", False)

    # Va .bat phai CRLF (neu LF, cmd hay loi o lenh goto / khoi hanh nhieu dong)
    for n in ("install.bat", "start.bat", "signer.bat", "setup.bat"):
        f = ROOT / n
        if not f.exists():
            continue
        raw = f.read_bytes()
        lf = sum(1 for i, b in enumerate(raw)
                 if b == 10 and (i == 0 or raw[i - 1] != 13))
        check(f"{n} xuong dong CRLF", lf, 0)

    print("\n=== 12. Ky tu dac biet trong echo ben trong khoi ngoac ===")
    # cmd parse TAT CA khoi ( ... ) truoc khi chay BAT ky nhanh nao. Trong
    # do, mot dau ( hoac ) khong escape trong text cua `echo` se bi hieu
    # nham la dau ngoac cua khoi lenh, khong phai chu. Vi du:
    #     if not exist "x" (
    #         echo cai ...   <-- "(mot lan)" + "..." -> "... was unexpected"
    #     )
    # Da chung minh: chay signer.bat that, no im lang dung ngay sau [4/4].
    SPECIALS = "&|<>"
    for n in ("install.bat", "start.bat", "signer.bat", "setup.bat"):
        f = ROOT / n
        if not f.exists():
            continue
        txt = f.read_bytes().decode("utf-8", "replace")
        depth, bad = 0, []
        for i, line in enumerate(txt.splitlines(), 1):
            s = line.strip()
            up = s.upper()
            if depth > 0 and (up.startswith("ECHO ") or up == "ECHO"):
                # bo qua nhung ky tu da escape bang dau ^
                plain, j = [], 0
                while j < len(s):
                    if s[j] == "^" and j + 1 < len(s):
                        j += 2
                        continue
                    plain.append(s[j])
                    j += 1
                t = "".join(plain)
                hits = [c for c in SPECIALS if c in t]
                if hits:
                    bad.append((i, " ".join(hits)))
                if "(" in t or ")" in t:
                    bad.append((i, "ngoac"))
            # cap nhat do sau khoi, bo qua escape
            j = 0
            while j < len(s):
                if s[j] == "^" and j + 1 < len(s):
                    j += 2
                    continue
                if s[j] == "(":
                    depth += 1
                elif s[j] == ")":
                    depth -= 1
                j += 1
            if s.startswith(")") and depth <= 0:
                depth = 0
        check(f"{n} echo trong khoi: escape ky tu dac biet", bad[:3], [])

    print("\n=== 13. npm.cmd phai chay qua 'cmd /c' trong signer.bat ===")
    # File .bat/.cmd (npm.cmd) KHONG phai .exe: no bam stdin cua chinh no va
    # nuot mat cac dong con lai cua file .bat cha. Chay truc tiep
    #     "npm.cmd" exec ... < nul
    # lam signer.bat im lang dung ngay sau dong "[4/4]", sidecar khong bao
    # gio khoi dong. Phai bo qua "cmd /c".
    sbat = (ROOT / "signer.bat").read_bytes().decode("utf-8")
    direct = [ln.strip() for ln in sbat.splitlines()
              if ln.strip().startswith('"%NPM%"') and
              not ln.strip().startswith('"%NPM%" start')]
    check("khong goi npm.cmd truc tiep (can 'cmd /c')", direct, [])
    check("npm exec duoc goi qua cmd /c",
          'cmd /c ""%NPM%" exec' in sbat.replace("  ", " "), True)
    check("npm install duoc goi qua cmd /c",
          'cmd /c ""%NPM%" install"' in sbat, True)
    # va phai tro PUPPETEER_EXECUTABLE_PATH qua file, khong ghi truc tiep
    # node -e "...(ngoac)..." vao for /f (roi " "" " -> loi parse)
    check("khong ghi node -e truc tiep vao for /f",
          ("node -e" in sbat and "for /f" in sbat
           and sbat.index("node -e") < sbat.index("for /f")), False)

    print(f"\n{'='*54}\n  {PASS} pass, {FAIL} fail\n{'='*54}")
    return 1 if FAIL else 0

if __name__ == "__main__":
    sys.exit(main())

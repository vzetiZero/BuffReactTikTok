"""Chụp màn hình app để kiểm tra bằng mắt — 50 dòng / trang, ô cid tối giản.

Chạy:  python shot_gui.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from core.config import MODE_LIKE_CID
from core.models import ST_DONE, ST_FAIL, ST_OK, ST_RUNNING, Account
from ui.main_window import MainWindow

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shot.png")


def build_accounts(n=137):
    """Tài khoản giả, trạng thái trộn lẫn để thấy rõ màu sắc."""
    out = []
    for i in range(n):
        a = Account(
            id=f"user{7000000000000 + i}",
            username=f"@K4a{'!@#$%^&*'[i % 8]}user{i:04d}",
            email=f"account.number{i:04d}@hotmail.com",
            password="x", ms_token="m", device_id="d",
            cookie={"sessionid_ss": "s", "sid_tt": "t"},
        )
        m = i % 9
        if m == 0:
            a.status, a.note = ST_OK, f"♥ cid=7654223771003994898 · like 1277 → 1278"
        elif m == 1:
            a.status, a.note = ST_FAIL, "API từ chối (code 10221): bị chặn bot"
        elif m == 2:
            a.status, a.note = ST_RUNNING, "Thả tim cid=7654223771003994898..."
        elif m == 3:
            a.status, a.note = ST_DONE, "Cookie hợp lệ"
        elif m == 4:
            a.status = ST_OK
            a.note = "♥ cid=7654223771003994898 · đã thả tim trước đó (like=88)"
        a.proxy = f"103.28.{i % 255}.{i % 200 + 1}:8080"
        a.proxy_label = f"103.28.{i % 255}.{i % 200 + 1}:8080"
        out.append(a)
    return out


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    # Chặn tự nạp lại tài khoản đã lưu, nếu không nó ghi đè dữ liệu demo.
    win._restore_accounts = lambda: None
    win.backend_kind.setCurrentIndex(win.backend_kind.findData("mock"))
    win._signer_ready = True

    win._apply_accounts(build_accounts(), "demo")
    win.in_cid.setPlainText(
        "7690897576899658504\n"
        "7654223771003994898\n"
        "7700000000000000001\n"
        "7700000000000000002"
    )
    win.cb_mode.setCurrentIndex(win.cb_mode.findData(MODE_LIKE_CID))
    win.in_search.setText("")
    win.tabs.setCurrentWidget(win.tab_main)
    # KHÔNG showMaximized: máy này scale 150% nên cửa sổ tối đa chỉ 720px
    # logic. Ép kích thước 1080p @100% để đo đúng 50 dòng.
    win.resize(1920, 1040)
    win.show()

    def grab():
        for _ in range(4):
            app.processEvents()
        ok = win.grab().save(OUT)
        print(f"da luu {OUT}  ({os.path.getsize(OUT)} bytes)"
              if ok else "LUU THAT BAI")
        print(f"cua so      : {win.width()} x {win.height()}")
        print(f"per page    : {win.model.per_page}  |  trang: {win.model.page_count}")
        print(f"row_h       : {win.delegate.row_h()}px x {win.model.per_page} "
              f"= {win.delegate.row_h() * win.model.per_page}px")
        print(f"viewport    : {win.table.viewport().height()}px")
        # chụp thêm tab Tác vụ để xem ô cid đã tối giản
        win.tabs.setCurrentWidget(win.tab_task)
        for _ in range(3):
            app.processEvents()
        ok2 = win.grab().save(OUT.replace(".png", "_task.png"))
        print(f"task tab    : {'OK' if ok2 else 'FAIL'}")
        print(f"cid label   : {win.lbl_cid_stat.text()}")
        win.close()
        app.quit()

    QTimer.singleShot(700, grab)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

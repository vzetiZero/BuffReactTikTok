"""TEST THẬT qua đúng đường đi của hàng đợi cid — gọi mạng thật, sidecar thật.

Dùng backend http thật, chạy MainWindow thật, để xác minh phần UI/hàng đợi
không làm hỏng request. Mỗi tài khoản thả tim cho TỪNG cid trong danh sách.

Chạy:  python test_live_queue.py <cid> [so_acc]
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from core.config import MODE_LIKE_CID
from core.parser import load_accounts
from ui.main_window import MainWindow

CIDS = (sys.argv[1] if len(sys.argv) > 1
        else "7654223771003994898\n7700000000000000001")
LIMIT = int(sys.argv[2]) if len(sys.argv) > 2 else 2


def wait_for(pred, timeout_ms=120000):
    loop = QEventLoop()
    st = {"n": 0}

    def tick():
        st["n"] += 1
        if pred() or st["n"] * 100 > timeout_ms:
            loop.quit()

    t = QTimer()
    t.timeout.connect(tick)
    t.start(100)
    loop.exec()
    return pred()


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win._restore_accounts = lambda: None
    win.backend_kind.setCurrentIndex(win.backend_kind.findData("http"))
    win._signer_ready = True
    # không hiện hộp thoại modal (offscreen không ai bấm được)
    QMessageBox.warning = staticmethod(
        lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.information = staticmethod(
        lambda *a, **k: QMessageBox.StandardButton.Ok)

    accounts = load_accounts("cokie.tik.txt")[:LIMIT]
    win._apply_accounts(accounts, "test that")
    win.in_cid.setPlainText(CIDS)
    win.cb_mode.setCurrentIndex(win.cb_mode.findData(MODE_LIKE_CID))
    win.sp_threads.setValue(max(1, len(accounts)))
    win.sp_dmin.setValue(0.0)
    win.sp_dmax.setValue(0.0)
    win.sp_retry.setValue(1)

    lst = win.cids()
    print(f"sidecar : {'OK' if win._signer_ready else 'KHONG'}")
    print(f"tai khoan: {len(accounts)}   cid: {lst}\n")

    seen = []
    real = win.controller.start
    win.controller.start = lambda a, c: (seen.append(c.cid), real(a, c))[1]

    t0 = time.time()
    win.start_run()
    done = wait_for(lambda: not win._cid_queue and not win.controller.busy)
    el = time.time() - t0

    print(f"\n  hang doi da chay: {seen}")
    print(f"  ket thuc dung han: {done}   ({el:.1f}s)\n")
    print("  ket qua tung tai khoan (giai tri cuoi cung):")
    for a in accounts:
        print(f"    {a.username:22} {a.status:14} {a.note}")
    print(f"\n  chay {len(seen)}/{len(lst)} cid  ·  "
          f"{len(seen) * len(accounts) / max(el, .1):.2f} acc/s")

    win.close()
    return 0 if (done and seen == lst) else 1


if __name__ == "__main__":
    sys.exit(main())

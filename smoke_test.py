"""Smoke test: chạy backend mock qua đúng QThreadPool như app thật, in kết quả."""

import sys
import time

from PySide6.QtCore import QCoreApplication, QTimer

from core.config import MODE_LIKE_CID, RunConfig
from core.parser import load_accounts
from core.runner import RunController

app = QCoreApplication(sys.argv)

accounts = load_accounts("cokie.tik.txt")
print(f"nap {len(accounts)} tai khoan")

ctrl = RunController(lambda: __import__(
    "core.backends.mock_backend", fromlist=["MockBackend"]).MockBackend())

t0 = time.perf_counter()
done = {"n": 0}


def on_status(aid, status, note):
    print(f"  [{status:9}] {aid}  {note}")


def on_log(aid, msg):
    print(f"      · {aid} {msg}")


def on_finished():
    dt = time.perf_counter() - t0
    print(f"XONG trong {dt:.2f}s  ({len(accounts)} account, 4 luong)")
    app.quit()


ctrl.status.connect(on_status)
ctrl.log.connect(on_log)
ctrl.finished.connect(on_finished)

QTimer.singleShot(0, lambda: ctrl.start(
    accounts,
    RunConfig(mode=MODE_LIKE_CID, cid="769047757775676167", concurrency=4),
))

sys.exit(app.exec())

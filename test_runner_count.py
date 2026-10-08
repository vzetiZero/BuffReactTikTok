"""Kiểm tra tính đúng của bộ đếm hoàn tất — chạy từng lô tuần tự.

Bắt bug thật: trước đây `finished` bắn khi activeThreadCount() về 0, tức là
khi task CUỐI CÙNG vẫn chưa kịp gửi signal về GUI thread. Hậu quả: bảng tổng
kết đếm thiếu vài dòng dù worker đã chạy xong.
"""

import sys
import time

from PySide6.QtCore import QCoreApplication, QTimer

from core.backends.mock_backend import MockBackend
from core.config import MODE_LIKE_CID, RunConfig
from core.models import Account
from core.runner import RunController

app = QCoreApplication(sys.argv)
TERMINAL = ("Chờ", "Đang chạy")     # trạng thái chưa kết thúc
plan = [(1, 12), (2, 16), (5, 20), (10, 24), (20, 30)]
idx = {"i": 0}
rows: list = []
# PHẢI giữ tham chiếu tới RunController đang chạy.
# `ctrl` trong run_batch() chỉ còn tham chiếu qua closure của QTimer.singleShot
# — sau khi timer bắn xong closure bị giải phóng, PySide6 hủy luôn QObject,
# kéo theo QThreadPool đang chạy -> test treo hoặc crash 0xC0000005.
# (Trong app thì không bị: MainWindow giữ self.controller suốt đời.)
LIVE: list = []


def mk(i):
    a = Account(id=f"id{i:04d}", username=f"user{i:04d}", email=f"u{i}@x.com",
                password="p", ms_token="m", device_id="d", cookie={})
    a.cookie["sessionid_ss"] = "s"
    a.cookie["sid_tt"] = "t"
    a.selected = True
    return a


def run_batch():
    threads, n = plan[idx["i"]]
    accs = [mk(i) for i in range(n)]
    ctrl = RunController(lambda: MockBackend(fail_rate=0.0, scale=0.94))
    LIVE.append(ctrl)                 # xem chú thích của LIVE ở trên
    st = {"t0": 0.0}
    cnt = {"done": 0, "status": 0}

    def on_start(_c):
        st["t0"] = time.perf_counter()

    def on_task_done(_i):
        cnt["done"] += 1

    def on_status(_i, s, _n):
        if s not in TERMINAL:
            cnt["status"] += 1

    def on_finished():
        dt = time.perf_counter() - st["t0"]
        good = cnt["done"] == n and cnt["status"] == n
        rows.append((threads, n, cnt["done"], cnt["status"], dt, good))
        print(f"{threads:>6} {n:>5} {cnt['done']:>6} {cnt['status']:>7} "
              f"{dt:>7.2f}s  {'OK' if good else 'SAI'}")
        idx["i"] += 1
        if idx["i"] < len(plan):
            QTimer.singleShot(0, run_batch)
        else:
            QTimer.singleShot(0, finish)

    ctrl.started.connect(on_start)
    ctrl.task_done.connect(on_task_done)
    ctrl.status.connect(on_status)
    ctrl.finished.connect(on_finished)
    QTimer.singleShot(0, lambda: ctrl.start(
        accs, RunConfig(mode=MODE_LIKE_CID, cid="7690897576899658504",
                        concurrency=threads, delay_min=0, delay_max=0)))


def finish():
    print("-" * 52)
    bad = [r for r in rows if not r[5]]
    print(f"{len(rows) - len(bad)}/{len(rows)} lot dung")
    sys.exit(1 if bad else 0)


print(f"\nKiem tra bo dem hoan tat · cid mau 7690897576899658504")
print(f"{'Luong':>6} {'So acc':>5} {'task_done':>9} {'status':>7} {'Thoi gian':>10}")
print("-" * 52)
QTimer.singleShot(0, run_batch)
QTimer.singleShot(120_000, lambda: (print("TIMEOUT"), sys.exit(1)))
sys.exit(app.exec())

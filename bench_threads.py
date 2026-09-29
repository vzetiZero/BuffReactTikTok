"""Đo tốc độ lớp đa luồng — KHÔNG gọi TikTok, KHÔNG cần sidecar.

Câu hỏi trả lời: 1 phút chạy được bao nhiêu tài khoản?

Chạy:  python bench_threads.py [chi_phi_moi_acc_giay]

Mỗi lô được chọn sao cho chạy ~8 giây, nhờ vậy số lượng đo đủ chính xác mà
tổng thời gian vẫn ngắn.
"""

import sys
import time

from PySide6.QtCore import QCoreApplication, QTimer

from core.backends.mock_backend import MockBackend
from core.config import MODE_LIKE_CID, RunConfig
from core.models import Account
from core.runner import RunController

app = QCoreApplication(sys.argv)

LAT = float(sys.argv[1]) if len(sys.argv) > 1 else 0.8
TARGET_SEC = 8.0
THREADS = [1, 2, 5, 10, 20, 40, 80]
CID = "7690897576899658504"

SCALE = LAT / 0.85 if LAT else 0.0   # mock ngủ 0.2-0.5s + 0.4s = 0.85s


def make(n):
    out = []
    for i in range(n):
        a = Account(id=f"id{i:06d}", username=f"user{i:06d}",
                    email=f"u{i}@x.com", password="p", ms_token="m",
                    device_id="d", cookie={})
        a.cookie["sessionid_ss"] = "s"
        a.cookie["sid_tt"] = "t"
        a.selected = True
        out.append(a)
    return out


def batch_size(threads: int) -> int:
    """Số tài khoản để lô chạy khoảng TARGET_SEC giây."""
    if LAT <= 0:
        return 2000
    return max(30, min(2000, int(threads * TARGET_SEC / LAT)))


results: list = []
idx = {"i": 0}
st: dict = {}


def run_batch(threads: int) -> None:
    n = batch_size(threads)
    ctrl = RunController(lambda: MockBackend(fail_rate=0.0, scale=SCALE))
    st["t0"] = 0.0
    st["n"] = n
    ctrl.started.connect(lambda _c: st.update(t0=time.perf_counter()))
    ctrl.finished.connect(on_finished)
    cfg = RunConfig(mode=MODE_LIKE_CID, cid=CID, concurrency=threads,
                    delay_min=0, delay_max=0)
    QTimer.singleShot(0, lambda: ctrl.start(make(n), cfg))


def on_finished() -> None:
    th = THREADS[idx["i"]]
    n = st["n"]
    dt = time.perf_counter() - st["t0"]
    rate = n / dt if dt else 0.0
    results.append((th, dt, rate, rate * 60, n))
    print(f"{th:>6} {n:>7} {dt:>9.2f} {rate:>9.0f} {rate * 60:>11.0f}")
    next_batch()


def next_batch() -> None:
    idx["i"] += 1
    if idx["i"] < len(THREADS):
        QTimer.singleShot(0, lambda: run_batch(THREADS[idx["i"]]))
    else:
        QTimer.singleShot(0, finish)


def finish() -> None:
    print("-" * 58)
    best = max(results, key=lambda r: r[2])
    print(f"Nhanh nhat : {best[0]} luong → {best[2]:.0f} acc/s "
          f"= {best[3]:.0f} acc/phút")
    print()
    print("GIOI HAN THUC TE (khong phai do benchmark):")
    print("  - sidecar ky ~12 chu ky/giay; 1 acc can ~2 chu ky")
    print("    → tran ~6 acc/s ≈ 360 acc/phút, dù cung luong Python.")
    print("  - thoi gian mang that + rate limit TikTok lam chay hon.")
    app.quit()


print(f"\nMo phong · chi phi {LAT:.2f}s/tai khoan · cid mau {CID}")
print("Khong goi TikTok, khong can sidecar.")
print(f"Moi lot chay ~{TARGET_SEC:.0f}s\n")
print(f"{'Luong':>6} {'So acc':>7} {'Tong (s)':>9} {'(acc/s)':>9} {'acc/phut':>11}")
print("-" * 58)
# chốt chặn: luôn thoát dù có treo, để không bị treo vô hạn
QTimer.singleShot(240_000, app.quit)
QTimer.singleShot(0, lambda: run_batch(THREADS[0]))
sys.exit(app.exec())

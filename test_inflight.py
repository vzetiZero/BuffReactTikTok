"""Kiểm tra đồng hồ "đang chờ" + bộ đếm liên mạch.

Chạy:  python test_inflight.py

Ba nhóm kiểm tra:
  1. Bộ đếm `core/inflight` — enter/leave/snapshot/clear, an toàn double-leave.
  2. Mọi request thật (ký / HTTP / nghỉ) đều đi qua bộ đếm.
  3. GUI: trong lúc chạy, nhãn "đang chờ" hiện + số đếm có "đang xử lý";
     khi xong thì thanh tiến độ = 100 và nhãn biến mất.
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# console Windows mac dinh cp1252 -> in dau tieng Viet la loi; dua ve utf-8
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PASS, FAIL = 0, 0


def check(label, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  OK   {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label}\n        got  {got!r}\n        want {want!r}")


def mk(n, session=True):
    from core.models import Account
    cookie = {"sessionid_ss": "x", "sid_tt": "y"} if session else {}
    return [Account(id=f"acc{i:04d}", username=f"u{i}", email=f"e{i}@x",
                    password="p", ms_token="", device_id="",
                    cookie=dict(cookie))
            for i in range(n)]


def test_tracker() -> None:
    from core.inflight import HTTP, REST, SIGN, TASK, InFlight

    print("\n=== 1. InFlight: enter / leave / snapshot ===")
    t = InFlight()
    check("rong -> snapshot rong", t.snapshot(), {})

    a, b = t.enter(TASK), t.enter(SIGN)
    snap = t.snapshot()
    check("dem 1 task", snap.get(TASK, (0,))[0], 1)
    check("dem 1 sign", snap.get(SIGN, (0,))[0], 1)
    check("khong co http", HTTP in snap, False)
    check("khong co rest", REST in snap, False)

    t.leave(a)
    check("leave xong -> task = 0", t.count(TASK), 0)
    check("sign van con", t.count(SIGN), 1)

    t.leave(b)
    t.leave(b)                       # double leave khong duoc loi
    check("double leave van an toan", t.count(SIGN), 0)

    tok = t.enter(TASK)
    time.sleep(0.05)
    age = t.snapshot()[TASK][1]
    check("oldest > 0.04s sau khi ngu 0.05s", age > 0.04, True)
    t.leave(tok)

    for kind in (TASK, SIGN, HTTP, REST):
        k = t.enter(kind)
        check(f"nhap duoc kind {kind}", t.count(kind), 1)
        t.leave(k)
    t.enter(TASK)
    t.clear()
    check("clear -> rong het", t.snapshot(), {})

    # Tracker dung chung cua app khong duoc ro ri so lieu lan truoc
    from core.inflight import tracker as g
    g.clear()
    check("tracker chung rong khi app moi mo", g.snapshot(), {})


def test_gauges_on_gui() -> None:
    print("\n=== 2. GUI: nhan 'dang cho' + bo dem lien mach ===")
    from PySide6.QtWidgets import QApplication
    from ui import style
    from ui.main_window import MainWindow
    from core.inflight import TASK, tracker

    app = QApplication.instance() or QApplication(sys.argv)
    style.apply(app)
    w = MainWindow()
    w.show()                          # co show thi isVisible() moi dung
    # cho cac timer khoi dong (khoang 400ms) chay truoc — neu khong,
    # no co the tu nạp lai danh sach tu bo nho phien truoc sau khi ta nap test
    t_boot = time.perf_counter()
    while time.perf_counter() - t_boot < 0.8:
        app.processEvents()
        time.sleep(0.01)

    w.settings.remember_accounts = False   # test khong duoc ghi vao bo nho that
    w._apply_accounts(mk(60), "test")
    w.model.select_all_with_session()
    w.backend_kind.setCurrentIndex(w.backend_kind.findData("mock"))
    w.sp_threads.setValue(12)
    w.sp_dmin.setValue(0.0)
    w.sp_dmax.setValue(0.0)
    w.in_cid.setPlainText("7690897576899658504")
    for _ in range(3):
        app.processEvents()

    check("nhan 'dang cho' an khi chua chay", w.lbl_wait.isVisible(), False)

    w.start_run(mode="like_cid")

    saw_label = saw_running = saw_pbar_moving = False
    max_task = 0
    samples = 0
    t0 = time.perf_counter()
    while w.controller.busy and time.perf_counter() - t0 < 90:
        app.processEvents()
        time.sleep(0.01)
        if time.perf_counter() - t0 < 0.05:
            continue
        samples += 1
        if w.lbl_wait.isVisible() and w.lbl_wait.text():
            saw_label = True
        if "đang xử lý" in (w.lbl_stat.text() or ""):
            saw_running = True
        if 0 < w.pbar.value() < 100:
            saw_pbar_moving = True
        max_task = max(max_task, tracker.count(TASK))
        if samples % 10 == 0:
            app.processEvents()

    # cho GUI xu ly nhung signal con lai
    t1 = time.perf_counter()
    while time.perf_counter() - t1 < 1.0:
        app.processEvents()
        time.sleep(0.01)

    check("co mau nhan 'dang cho' trong luc chay", saw_label, True)
    check("so dem co dong 'dang xu ly'", saw_running, True)
    check("thanh tien do co chay giua chung", saw_pbar_moving, True)
    check("trong luc chay van co task dang treo", max_task > 0, True)
    check("chay het 60 tai khoan", w.meter._done, 60)
    check("xong roi thanh tien do = 100", w.pbar.value(), 100)
    check("xong roi an nhan 'dang cho'", w.lbl_wait.isVisible(), False)
    check("khong con viec nao treo", tracker.count(TASK), 0)
    check("khong con request nao treo", tracker.snapshot().get("sign", (0,))[0], 0)


def test_tracker_in_real_request_path() -> None:
    """Moi request deu phai di qua bo dem — khong thi dong ho vo nghia."""
    print("\n=== 3. Duong request that co cham vao bo dem ===")
    import inspect
    from core import tiktok, runner

    src_tiktok = inspect.getsource(tiktok.TikTokClient._request)
    check("_request cham SIGN", "tracker.enter(SIGN)" in src_tiktok, True)
    check("_request cham HTTP", "tracker.enter(HTTP)" in src_tiktok, True)
    check("_request cham REST khi thu lai", "tracker.enter(REST)" in src_tiktok, True)

    src_run = inspect.getsource(runner.AccountTask.run)
    check("AccountTask.run cham TASK", "tracker.enter(TASK)" in src_run, True)

    from core.backends import http_backend
    src_http = inspect.getsource(http_backend.HttpBackend.run)
    check("trễ ngẫu nhiên duoc bao len dong ho",
          "tracker.enter(REST)" in src_http, True)


def main() -> int:
    test_tracker()
    test_tracker_in_real_request_path()
    test_gauges_on_gui()
    print(f"\n{'=' * 58}\n  {PASS} pass, {FAIL} fail\n{'=' * 58}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

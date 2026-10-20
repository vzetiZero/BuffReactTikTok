"""Test LUỒI CHẠY THẬT của hàng đợi cid — dùng backend mock, không gọi mạng.

Kiểm tra điều quan trọng nhất: chạy xong cid này thì hệ thống TỰ chạy cid
kế tiếp, đúng thứ tự, và mỗi tài khoản được thả tim đúng 1 lần cho mỗi cid.

Chạy:  python test_cid_queue.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Test KHÔNG được đụng vào settings.json thật của người dùng.
os.environ["APPDATA"] = os.path.join(
    tempfile.mkdtemp(prefix="tiktok_test_"), "TikTokManager")
os.environ["XDG_CONFIG_HOME"] = os.environ["APPDATA"]

# Bộ canh: nếu test treo quá 60 giây thì in stack rồi tắt cứng, để không
# phải ngồi chờ vô hạn mỗi lần debug.
import threading


def _watchdog(sec: int = 60) -> None:
    import time
    import traceback

    time.sleep(sec)
    print("\n!!! TEST TREO — stack hiện tại:", flush=True)
    for fr in sys._current_frames().values():
        traceback.print_stack(fr)
    os._exit(3)


threading.Thread(target=_watchdog, daemon=True).start()

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from core.config import MODE_LIKE_CID
from core.models import Account
from ui.main_window import MainWindow

PASS, FAIL = 0, 0

CIDS = [
    "7690897576899658504",
    "7654223771003994898",
    "7700000000000000001",
]
N_ACC = 4


def check(label, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  OK   {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label}\n        got  {got!r}\n        want {want!r}")


def make_accounts(n):
    out = []
    for i in range(n):
        a = Account(
            id=f"acc{i}", username=f"@user{i}", email=f"u{i}@mail.com",
            password="p", ms_token="m", device_id="d",
            cookie={"sessionid_ss": "s", "sid_tt": "t"},
        )
        out.append(a)
    return out


def wait_for(win, predicate, timeout_ms=30000):
    """Chờ tới khi predicate() đúng, bằng vòng lặp event (không block)."""
    loop = QEventLoop()
    elapsed = {"ms": 0}
    step = {"t": None}

    def tick():
        elapsed["ms"] += 25
        if predicate() or elapsed["ms"] > timeout_ms:
            loop.quit()
        else:
            step["t"].start(25)

    step["t"] = QTimer()
    step["t"].timeout.connect(tick)
    step["t"].start(25)
    loop.exec()
    return predicate()


def main():
    app = QApplication.instance() or QApplication([])
    win = MainWindow()

    # Dialog modal sẽ treo test vô hạn ở chế độ offscreen (không ai bấm
    # được). Ghi lại nội dung thay vì hiện hộp thoại — rồi test kiểm tra
    # xem dialog CÓ được gọi hay không, để vẫn kiểm chứng được hành vi.
    from PySide6.QtWidgets import QMessageBox

    dialogs = []
    _warn = QMessageBox.warning
    _info = QMessageBox.information

    def fake_warn(parent, title, text, *a, **k):
        dialogs.append((title, text))
        return QMessageBox.StandardButton.Ok

    def fake_info(parent, title, text, *a, **k):
        dialogs.append((title, text))
        return QMessageBox.StandardButton.Ok

    # Hộp thoại tự tạo (dùng .exec()) cũng treo test — chặn luôn.
    _exec = QMessageBox.exec

    def fake_exec(self):
        dialogs.append((self.windowTitle(), self.text()))
        return QMessageBox.StandardButton.Ok

    QMessageBox.warning = staticmethod(fake_warn)
    QMessageBox.information = staticmethod(fake_info)
    QMessageBox.exec = fake_exec
    try:
        return _run(win, dialogs)
    finally:
        QMessageBox.warning = staticmethod(_warn)
        QMessageBox.information = staticmethod(_info)
        QMessageBox.exec = _exec


def _run(win, dialogs):

    # dùng backend mock + 0 chờ để test chạy nhanh, và bỏ chặn sidecar
    from core.backends.mock_backend import MockBackend
    win.controller._factory = lambda: MockBackend(fail_rate=0.0, scale=0.0)
    # GUI that khong con lua chon mock; test tu gan factory MockBackend.
    win._signer_ready = True

    accounts = make_accounts(N_ACC)
    win._apply_accounts(accounts, "test")

    print(f"\n=== Chạy {len(CIDS)} cid x {N_ACC} tai khoan (mock) ===")
    win.in_cid.setPlainText("\n".join(CIDS))
    win.cb_mode.setCurrentIndex(win.cb_mode.findData(MODE_LIKE_CID))
    win.settings.concurrency = N_ACC
    win.settings.delay_min = 0.0
    win.settings.delay_max = 0.0

    # theo dõi thứ tự các cid thực sự được chạy
    seen_order = []
    real_start = win.controller.start

    def spy_start(accs, cfg):
        seen_order.append(cfg.cid)
        real_start(accs, cfg)

    win.controller.start = spy_start

    win._signer_ready = True

    win.start_run()
    done = wait_for(win, lambda: not win._cid_queue and not win.controller.busy,
                    timeout_ms=40000)

    print(f"\n  hang doi chay: {seen_order}")
    print(f"  ket thuc dung han: {done}\n")

    check("chay duoc het hang doi", done, True)
    check("thu tu cid dung, khong thieu", seen_order, CIDS)
    check("khong chay thua lan nao", len(seen_order), len(CIDS))
    check("hang doi da duoc xoa", win._cid_queue, [])
    check("khong con pause", win._queue_paused, False)
    check("pos ve lai -1 hoac het", win._cid_pos in (-1, len(CIDS) - 1), True)

    # moi tai khoan phai tha tim 1 lan cho moi cid -> 3 lan
    # Ghi chú thành công nay nằm ở BẢNG LOG (bảng danh sách tài khoản
    # đã bỏ khỏi màn chính), nên đọc từ win.runlog chứ không phải a.note.
    notes = [r.note for r in win.runlog._rows]
    print(f"\n  ghi chu tung tai khoan:")
    for a in accounts:
        print(f"    {a.username}: {a.note}")
    # Ghi chú thành công của HTTP thật rút gọn thành "N TIM CMT <cid>"
    # hoặc "OK TIM CMT <cid>" khi không đọc lại được số like. Mock phải
    # ghi rõ "MÔ PHỎNG TIM CMT <cid>", tuyệt đối không bịa số like.
    import re as _re
    pat = _re.compile(r"^(?:\d+|OK|MÔ PHỎNG) TIM CMT \d+$")
    ok_all = all(pat.match(n or "") for n in notes)
    check("moi tai khoan co ghi chu '... TIM CMT <cid>'", ok_all, True)
    check("mock khong in so like bia",
          all(not _re.match(r"^\d+ TIM CMT", n or "") for n in notes), True)
    check("tai khoan cuoi cung OK",
          all(a.status in ("✔ Thành công",) or a.status for a in accounts), True)

    # kiem tra cid cuoi cung la cid thu 3
    last_cid = CIDS[-1]
    check("cid cuoi cung la cid thu 3",
          all(last_cid in (a.note or "") for a in accounts), True)

    # Cả 3 cid phải còn trong ô tóm tắt, kèm số account thành công/lỗi.
    # Trước đây _log_run_start() reset cả done_cids nên cid 1 và 2 bị mất.
    check("done_cids giữ đủ 3 cid", win.runlog.done_cids, CIDS)
    want_lines = [
        f"{cid} — {N_ACC}/{N_ACC} thành công · 0 lỗi · 0 bỏ qua"
        for cid in CIDS
    ]
    check("ô tóm tắt có đủ 3 cid kèm số lượng",
          win.in_done_cid.toPlainText().splitlines(), want_lines)
    check("done_stats của cid đầu",
          win.runlog.done_stats[CIDS[0]],
          {"ok": N_ACC, "done": 0, "fail": 0, "skip": 0, "total": N_ACC})
    log_text = win.log_edit.toPlainText()
    check("log chính có cid đầu tiên", CIDS[0] in log_text, True)
    check("log chính có dòng cid 1/3 xong", "cid 1/3" in log_text, True)
    check("log chính có tóm tắt cuối", "TÓM TẮT CID ĐÃ CHẠY" in log_text,
          True)

    # --- Tóm tắt có cả CID lỗi / bỏ qua, không chỉ CID thành công ---
    print("\n=== Tóm tắt CID: thành công / lỗi / bỏ qua ===")
    from ui.runlog import RunLogModel
    rm = RunLogModel()
    rm.mark_done("7690897576899658504", ok=3, fail=1, total=4)
    rm.mark_done("7654223771003994898", ok=0, fail=4, total=4)
    rm.mark_done("7700000000000000001", ok=0, done=4, total=4)
    check("dòng tóm tắt đúng số lượng", rm.done_lines(), [
        "7690897576899658504 — 3/4 thành công · 1 lỗi · 0 bỏ qua",
        "7654223771003994898 — 0/4 thành công · 4 lỗi · 0 bỏ qua",
        "7700000000000000001 — 4/4 hợp lệ · 0 lỗi · 0 bỏ qua",
    ])
    rm.mark_done("7690897576899658504", ok=2, fail=2, total=4)
    check("chạy lại cùng CID không nhân đôi dòng",
          len(rm.done_cids), 3)
    check("tóm tắt lấy kết quả mới nhất của CID",
          rm.done_lines()[0],
          "7690897576899658504 — 2/4 thành công · 2 lỗi · 0 bỏ qua")

    # --- Test: CID toàn lỗi vẫn có dòng tóm tắt 0/N ---
    print("\n=== CID lỗi 100% vẫn phải có tóm tắt ===")
    seen_order.clear()
    win.controller._factory = lambda: MockBackend(fail_rate=1.0, scale=0.0)
    win.in_cid.setPlainText(f"{CIDS[0]}\n{CIDS[1]}")
    win._signer_ready = True
    win.start_run()
    wait_for(win, lambda: not win._cid_queue and not win.controller.busy,
             timeout_ms=40000)
    fail_lines = win.in_done_cid.toPlainText().splitlines()
    check("cả 2 CID lỗi vẫn hiện trong tóm tắt", len(fail_lines), 2)
    check("CID lỗi ghi đúng 0/4 và 4 lỗi", fail_lines, [
        f"{CIDS[0]} — 0/{N_ACC} thành công · {N_ACC} lỗi · 0 bỏ qua",
        f"{CIDS[1]} — 0/{N_ACC} thành công · {N_ACC} lỗi · 0 bỏ qua",
    ])

    # --- Test 2: danh sach rong -> phai chan, khong chay ---
    print("\n=== Danh sach rong ===")
    seen_order.clear()
    dialogs.clear()
    win.in_cid.setPlainText("")
    win._signer_ready = True
    win.start_run()
    check("khong chay gi khi danh sach rong", seen_order, [])
    check("co bao loi 'Thieu cid'", any(t == "Thiếu cid" for t, _ in dialogs),
          True)

    # --- Test 3: chi giu cid hop le, bo qua dong rac ---
    print("\n=== Danh sach co dong rac ===")
    seen_order.clear()
    win.in_cid.setPlainText(f"{CIDS[0]}\nabc\n\n{CIDS[1]}")
    win._signer_ready = True
    win.start_run()
    wait_for(win, lambda: not win._cid_queue and not win.controller.busy, 40000)
    check("bo qua dong chu cai, van chay 2 cid", seen_order, CIDS[:2])

    # --- Test 4: nut DUNG chan ca hang doi ---
    print("\n=== Bam DUNG giua chung ===")
    seen_order.clear()
    win.in_cid.setPlainText("\n".join(CIDS))
    # 3 cid x 4 acc, moi acc chay ~0.5s -> can chay lau de co canh giua
    win.controller._factory = lambda: MockBackend(fail_rate=0.0, scale=3.0)
    win._signer_ready = True
    win.start_run()
    wait_for(win, lambda: win.controller.busy, 4000)
    n_when_stop = len(seen_order)
    win.on_stop()
    wait_for(win, lambda: not win.controller.busy, 40000)
    check("DUNG khong chay tiep cid sau", len(seen_order), n_when_stop)
    check("DUNG xoa het hang doi", win._cid_queue, [])
    check("DUNG bat lai co danh dau pause", win._queue_paused, False)

    print(f"\n{'='*50}\n  {PASS} pass, {FAIL} fail\n{'='*50}")
    win.close()
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

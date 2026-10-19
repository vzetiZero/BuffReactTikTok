"""Demo/test 10 tài khoản cho 1 cid — chạy qua đúng QThreadPool của app.

Mặc định là MOCK: không gọi TikTok, không cần cookie thật, không cần sidecar.
Mục đích: kiểm tra hàng đợi, đa luồng, bộ đếm và định dạng kết quả.

Chạy demo an toàn:
    .venv\\Scripts\\python.exe demo_cid_10.py

Chạy thử toàn bộ đường HTTP nhưng KHÔNG gọi mạng (stub):
    .venv\\Scripts\\python.exe demo_cid_10.py --backend stub

Chạy thật (bắt buộc có cookie thật + sidecar Node):
    .venv\\Scripts\\python.exe demo_cid_10.py --live --backend http ^
        --file cokie.tik.txt --cid 7698352113629348629 ^
        --aweme-id 7690908625404955910

Lưu ý: `--live` là chốt an toàn. Không có nó thì backend http bị từ chối,
tránh vô tình thả tim thật khi chỉ muốn xem thử luồng chạy.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from core.backends.mock_backend import MockBackend
from core.config import MODE_LIKE_CID, RunConfig
from core.models import (
    ST_OK,
    Account,
    format_success_line,
)
from core.parser import load_accounts
from core.runner import RunController

DEFAULT_CID = "7698352113629348629"
# Điền aweme_id khi biết video chứa bình luận. Ví dụ request thật:
#   cid=7698352113629348629, aweme_id=7690908625404955910
# Để trống nếu chỉ có cid — endpoint digg vẫn chạy.
DEFAULT_AWEME = ""


def install_stub_tiktok() -> None:
    """Thay `TikTokClient._request` bằng phản hồi giả — không gọi mạng.

    Vẫn đi qua HttpBackend + TikTokClient thật, nên kiểm tra được:
      - kiểm tra login -> thả tim -> đọc lại số like (verify)
      - `cid` và `aweme_id` có được truyền đúng vào endpoint digg không
      - mã status_code / note / TaskResult
    Chỉ thay đúng lớp I/O cuối cùng; không sửa file production.
    """
    import threading
    from collections import defaultdict

    from core import tiktok as tk

    counts: dict[tuple[str, str], int] = defaultdict(int)
    calls: list[tuple[str, str, dict]] = []
    lock = threading.Lock()

    def fake_request(self, method, path, params, body, retries=2):
        cid = str(params.get("cid", ""))
        if path == tk.EP_COMMENT_LIST:
            # `comment_list` không mang cid trong params; lấy cid mà
            # `find_comment` đang tìm (được set trong fake_find bên dưới).
            cid = str(getattr(self, "_stub_target", ""))
        key = (self.account.username, cid)
        if path == tk.EP_USER_DETAIL:
            return {
                "status_code": 0,
                "data": {"userInfo": {"user": {
                    "nickname": self.account.username,
                    "id": self.account.id,
                }}},
            }
        if path == tk.EP_COMMENT_DIGG:
            with lock:
                counts[key] += 1
                calls.append((self.account.username, path, dict(params)))
            return {"status_code": 0, "statusCode": 0, "status_msg": ""}
        if path == tk.EP_COMMENT_LIST:
            with lock:
                n = counts[key]
            return {
                "status_code": 0,
                "data": {
                    "comments": [{
                        "cid": cid,
                        "digg_count": n,
                        "text": "stub comment",
                        "reply_comment_total": 0,
                    }],
                    "has_more": 0,
                    "cursor": 0,
                },
            }
        if path == tk.EP_COMMENT_REPLY:
            return {"status_code": 0, "data": {"comments": []}}
        return {"status_code": 0, "data": {}}

    # Giữ nguyên đường `find_comment` thật, chỉ ghi lại cid đang tìm để
    # fake `comment_list` trả đúng comment đó.
    original_find = tk.TikTokClient.find_comment

    def fake_find(self, aweme_id, comment_id, max_pages=2, only_replies=True):
        self._stub_target = str(comment_id)
        return original_find(self, aweme_id, comment_id, max_pages, only_replies)

    tk.TikTokClient._request = fake_request
    tk.TikTokClient.find_comment = fake_find
    tk._STUB_CALLS = calls  # type: ignore[attr-defined]


def make_demo_accounts(n: int) -> list[Account]:
    """10 account giả có đủ sessionid_ss/sid_tt để đi qua lớp kiểm tra cookie."""
    out: list[Account] = []
    for i in range(n):
        seed = f"demo-account-{i}"
        sid = hashlib.sha1(seed.encode()).hexdigest()
        cookie = {
            "sessionid": sid,
            "sessionid_ss": sid,
            "sid_tt": sid[:32],
            "tt_csrf_token": hashlib.md5(seed.encode()).hexdigest(),
            "s_v_web_id": f"verify_{sid[:16]}",
            "store-country-code": "vn",
            "msToken": hashlib.sha1((seed + "ms").encode()).hexdigest() * 2,
        }
        out.append(Account(
            id=hashlib.sha1(seed.encode()).hexdigest()[:10],
            username=f"demo_user_{i:02d}",
            email=f"demo{i:02d}@example.local",
            password="",
            ms_token=cookie["msToken"],
            device_id="",
            cookie=cookie,
            raw="(demo account)",
        ))
    return out


def wait_finished(controller: RunController, timeout_s: float = 60.0) -> bool:
    loop = QEventLoop()
    done = {"ok": False}

    def on_finished():
        done["ok"] = True
        loop.quit()

    controller.finished.connect(on_finished)
    t = QTimer()
    t.setSingleShot(True)
    t.timeout.connect(loop.quit)
    t.start(int(timeout_s * 1000))
    loop.exec()
    return done["ok"]


def main() -> int:
    ap = argparse.ArgumentParser(description="Demo 10 account × 1 cid")
    ap.add_argument("--cid", default=DEFAULT_CID,
                    help=f"cid cần thả tim (mặc định {DEFAULT_CID})")
    ap.add_argument("--aweme-id", default=DEFAULT_AWEME,
                    help=f"aweme_id/video id để xác minh số like (mặc định {DEFAULT_AWEME})")
    ap.add_argument("--video", default="",
                    help="URL video đầy đủ để làm Referer (tùy chọn, vd "
                         "https://www.tiktok.com/@user/video/7690908625404955910)")
    ap.add_argument("--file", default="cokie.tik.txt",
                    help="file cookie 8 trường (mặc định cokie.tik.txt)")
    ap.add_argument("--offset", type=int, default=0,
                    help="bỏ qua N account đầu (mặc định 0) — dùng để test lô khác")
    ap.add_argument("--limit", type=int, default=10, help="số account (mặc định 10)")
    ap.add_argument("--concurrency", type=int, default=10,
                    help="số luồng (mặc định 10)")
    ap.add_argument("--backend", choices=("mock", "stub", "http"), default="mock",
                    help="mock = giả lập; stub = HTTP thật nhưng mạng giả; "
                         "http = gọi TikTok thật (cần --live)")
    ap.add_argument("--live", action="store_true",
                    help="cho phép backend http gọi TikTok thật")
    ap.add_argument("--no-verify", action="store_true",
                    help="tắt đọc lại số like (nhanh hơn, chỉ dùng với --live)")
    ap.add_argument("--timeout", type=float, default=120.0,
                    help="thời gian chờ tối đa, giây")
    args = ap.parse_args()

    if not args.cid.isdigit() or not (15 <= len(args.cid) <= 25):
        print(f"CID không hợp lệ: {args.cid!r}")
        return 2
    if args.aweme_id and (not args.aweme_id.isdigit()
                          or not (15 <= len(args.aweme_id) <= 25)):
        print(f"aweme_id không hợp lệ: {args.aweme_id!r}")
        return 2
    if args.offset < 0:
        print("--offset phải >= 0")
        return 2

    app = QCoreApplication.instance() or QCoreApplication(sys.argv)

    # --- chọn danh sách account -------------------------------------
    if args.backend == "http":
        if not args.live:
            print("TỪ CHỐI: backend http cần cờ --live (tránh thả tim thật "
                  "khi chưa chủ động).\n"
                  "  Thêm --live nếu bạn thật sự muốn chạy thật.")
            return 2
        try:
            accounts = load_accounts(args.file)
        except OSError as e:
            print(f"Không đọc được file cookie '{args.file}': {e}")
            return 2
        if len(accounts) < args.offset + args.limit:
            print(f"File '{args.file}' chỉ có {len(accounts)} account, "
                  f"cần offset {args.offset} + {args.limit} account.")
            return 2
        accounts = accounts[args.offset:args.offset + args.limit]
        # kiểm tra sidecar trước khi chạy để không đỏ cả 10 account
        from core.signer import Signer
        signer = Signer("http://127.0.0.1:8080")
        if not signer.is_ready():
            print("Sidecar ký chưa sẵn sàng tại http://127.0.0.1:8080.\n"
                  "Bật signer.bat (hoặc nút 'Bật sidecar') rồi chạy lại.")
            return 2
    else:
        if os.path.exists(args.file):
            try:
                accounts = load_accounts(args.file)[
                    args.offset:args.offset + args.limit
                ]
            except OSError:
                accounts = []
        else:
            accounts = []
        if len(accounts) < args.limit:
            print(f"({args.backend}) Không đủ account trong '{args.file}' — "
                  f"dùng {args.limit} account giả lập.")
            accounts = make_demo_accounts(args.limit)

    cfg = RunConfig(
        mode=MODE_LIKE_CID,
        cid=args.cid,
        aweme_id=args.aweme_id,
        video=args.video,
        concurrency=max(1, args.concurrency),
        delay_min=0.0,
        delay_max=0.0,
        retries=1,
        verify=not args.no_verify,
        timeout=20.0,
    )

    if args.backend == "http":
        from core.backends.http_backend import HttpBackend
        factory = lambda: HttpBackend()  # noqa: E731
    elif args.backend == "stub":
        # Dùng HttpBackend thật nhưng thay lớp I/O cuối bằng phản hồi giả.
        install_stub_tiktok()
        from core.backends.http_backend import HttpBackend
        factory = lambda: HttpBackend()  # noqa: E731
    else:
        # scale=0 + fail_rate=0: kết quả tất định, chỉ đo luồng/queue.
        factory = lambda: MockBackend(fail_rate=0.0, scale=0.0)  # noqa: E731

    ctrl = RunController(factory)
    rows: dict[str, tuple[str, str, str]] = {}

    def on_status(aid: str, status: str, note: str) -> None:
        rows[aid] = (status, note, rows.get(aid, ("", "", ""))[2])

    def on_log(aid: str, msg: str) -> None:
        if aid in rows:
            s, n, last = rows[aid]
            rows[aid] = (s, n, msg)

    ctrl.status.connect(on_status)
    ctrl.log.connect(on_log)

    label = {
        "mock": "MÔ PHỎNG — không gọi TikTok",
        "stub": "HTTP THẬT + MẠNG GIẢ — không gọi TikTok",
        "http": "GỌI TIKTOK THẬT",
    }[args.backend]
    print("=" * 72)
    print(f"  backend  : {args.backend}  ({label})")
    print(f"  cid      : {args.cid}")
    print(f"  aweme_id : {args.aweme_id or '(không truyền)'}")
    print(f"  account  : {len(accounts)}   luồng: {cfg.concurrency}   "
          f"offset: {args.offset}")
    print("=" * 72)

    t0 = time.perf_counter()
    ctrl.start(accounts, cfg)
    finished = wait_finished(ctrl, args.timeout)
    elapsed = time.perf_counter() - t0

    print("\n  KẾT QUẢ TỪNG ACCOUNT")
    ok = 0
    for a in accounts:
        status, note, _ = rows.get(a.id, ("(không có tín hiệu)", "", ""))
        if status == ST_OK:
            ok += 1
            line = format_success_line(note, a.comment_id, a.like_after) or note
        else:
            line = note or status
        print(f"    {a.username:18} [{status:11}] {line}")

    print("\n" + "=" * 72)
    print(f"  {ok}/{len(accounts)} account thành công · {elapsed:.2f}s · "
          f"{len(accounts) / max(elapsed, 1e-6):.1f} acc/s")
    if args.backend == "mock":
        print("  Đây là kết quả MÔ PHỎNG. Muốn chạy thật, xem hướng dẫn ở đầu file.")
    elif args.backend == "stub":
        from core import tiktok as tk
        calls = getattr(tk, "_STUB_CALLS", [])
        digg = [c for c in calls if c[1] == tk.EP_COMMENT_DIGG]
        wrong_aweme = [c for c in digg if c[2].get("aweme_id") != args.aweme_id]
        wrong_cid = [c for c in digg if c[2].get("cid") != args.cid]
        print(f"  Stub đã nhận {len(digg)} request digg.")
        print(f"  cid đúng: {'OK' if not wrong_cid else 'SAI'} · "
              f"aweme_id đúng: {'OK' if not wrong_aweme else 'SAI'}")
        if wrong_cid or wrong_aweme:
            print("  ⚠ Có request digg mang sai cid/aweme_id.")
            return 1
    print("=" * 72)

    if not finished:
        print("  ⚠ HẾT THỜI GIAN CHỜ — bộ đếm không phát 'finished'.")
        return 1
    if ok != len(accounts):
        print("  ⚠ Có account không thành công — xem log phía trên.")
        return 1
    print("  ✔ PASS: đủ tín hiệu cho mọi account, hàng đợi kết thúc sạch.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

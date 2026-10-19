"""Test phanh rate limit của backend HTTP.

Chạy:  python test_rate_limit_guard.py

Không gọi TikTok. Kiểm tra:
  1. RateLimitGuard chỉ đếm lỗi mạng / mã IP, không đếm lỗi nghiệp vụ.
  2. Thành công làm sạch chuỗi lỗi; chạm ngưỡng thì giữ trạng thái đã chặn.
  3. HttpBackend bỏ qua task mới sau khi phanh bật (không tạo request).
  4. Mã 200034 ("đã thả tim rồi") là trạng thái đích, không phải lỗi, và
     dòng log không được in như một like mới.
"""

from __future__ import annotations

import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from core.backends.base import StopFlag
from core.backends.http_backend import HttpBackend
from core.backends.rate_limit import (
    RATE_LIMIT_CODE,
    RATE_LIMIT_TAG,
    RateLimitGuard,
)
from core.config import MODE_LIKE_CID, RunConfig
from core.models import ST_OK, ST_SKIP, Account, format_success_line

PASS, FAIL = 0, 0


def check(label, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  OK   {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label}\n        got  {got!r}\n        want {want!r}")


def make_account():
    return Account(
        id="acc-guard", username="guard", email="g@x.com", password="p",
        ms_token="", device_id="",
        cookie={"sessionid_ss": "s", "sid_tt": "t"},
    )


def test_guard():
    print("\n=== 1. RateLimitGuard ===")
    g = RateLimitGuard(threshold=2)
    check("lỗi nghiệp vụ không đếm (200013)", g.failure(200013), False)
    check("lỗi nghiệp vụ không đếm (2055)", g.failure(2055), False)
    check("code 0 không đếm", g.failure(0), False)
    check("chưa chạm ngưỡng", g.tripped, False)
    g.failure(-1)                       # lỗi mạng: đếm 1
    check("lỗi mạng thứ 1 chưa đủ", g.tripped, False)
    check("mã 8 chạm ngưỡng", g.failure(8), True)
    check("đã bật phanh", g.tripped, True)
    check("không trip lần 2", g.failure(-1), False)

    g2 = RateLimitGuard(threshold=2)
    g2.failure(-1)
    g2.success()                        # request thành công -> reset
    check("success xoá chuỗi lỗi", g2.failure(8), False)
    check("vẫn chưa trip sau success", g2.tripped, False)


def test_backend_skip():
    print("\n=== 2. HttpBackend skip sau khi phanh ===")
    b = HttpBackend()
    for _ in range(b._guard.threshold):
        b._guard.failure(8)
    check("guard đã bật", b._guard.tripped, True)

    calls = {"n": 0}

    def progress(*_a):
        calls["n"] += 1

    r = b.run(
        make_account(),
        RunConfig(mode=MODE_LIKE_CID, cid="7690897576899658504", verify=False),
        StopFlag(threading.Event()),
        progress,
    )
    check("task mới trả SKIP", r.status, ST_SKIP)
    check("note có nhãn rate limit", RATE_LIMIT_TAG in r.note, True)
    check("mã nội bộ", r.code, RATE_LIMIT_CODE)
    check("không gọi progress/không tạo client", calls["n"], 0)


def test_already_liked():
    print("\n=== 3. 200034 = đã thả tim trước đó ===")

    class FakeClient:
        def digg_comment(self, aweme, cid, digg=True):
            return {"status_code": 0, "statusCode": 200034}

    b = HttpBackend()
    cfg = RunConfig(mode=MODE_LIKE_CID, cid="7602703562657022728",
                    verify=False)
    r = b._like_cid("acc", FakeClient(), cfg, lambda *_a: None)
    check("trạng thái thành công", r.status, ST_OK)
    check("note nói rõ đã thả tim trước đó",
          "đã thả tim trước đó" in r.note.lower(), True)
    check("không bịa like_after", r.like_after, None)
    line = format_success_line(r.note, r.comment_id, r.like_after)
    check("dòng log không giả làm like mới", line,
          "ĐÃ TIM CMT 7602703562657022728")


def test_api_failure_trips():
    print("\n=== 4. Lỗi IP từ API chuyển thành phanh ===")

    class FakeClient:
        def digg_comment(self, aweme, cid, digg=True):
            return {"status_code": 10221, "status_msg": "blocked"}

    b = HttpBackend()
    b._guard.threshold = 1
    cfg = RunConfig(mode=MODE_LIKE_CID, cid="7602703562657022728",
                    verify=False)
    r = b._like_cid("acc", FakeClient(), cfg, lambda *_a: None)
    check("trả mã phanh nội bộ", r.code, RATE_LIMIT_CODE)
    check("note có nhãn rate limit", RATE_LIMIT_TAG in r.note, True)
    check("guard đã bật", b._guard.tripped, True)


if __name__ == "__main__":
    test_guard()
    test_backend_skip()
    test_already_liked()
    test_api_failure_trips()
    print(f"\n{'=' * 52}\n  {PASS} pass, {FAIL} fail\n{'=' * 52}")
    sys.exit(1 if FAIL else 0)

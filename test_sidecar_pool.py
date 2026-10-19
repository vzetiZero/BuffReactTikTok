"""Test SidecarPool: mỗi proxy một signer, không gọi Node/trình duyệt.

Chạy:  python test_sidecar_pool.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from core.proxy import parse_proxy
from core.sidecar_pool import (
    SidecarInstance,
    SidecarPool,
    SidecarPoolError,
)

PASS, FAIL = 0, 0


def check(label, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  OK   {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label}\n        got  {got!r}\n        want {want!r}")


class FakeSigner:
    def __init__(self, name):
        self.name = name


class FakePool(SidecarPool):
    """SidecarPool không mở sidecar thật; ghi lại proxy đã gọi."""

    def __init__(self, **kw):
        self.spawned: list[str] = []
        super().__init__(Path(tempfile.gettempdir()), node_exe="node", **kw)

    def _spawn(self, proxy_url, profile):
        self.spawned.append(proxy_url)
        return SidecarInstance(
            proxy_url=proxy_url,
            proxy_label=f"{profile.host}:{profile.port}",
            port=9000 + len(self.spawned),
            signer=FakeSigner(proxy_url),
        )


class FakeFailPool(FakePool):
    def _spawn(self, proxy_url, profile):
        self.spawned.append(proxy_url)
        raise SidecarPoolError("proxy giả lỗi")


def test_default_and_cache():
    print("\n=== 1. Không proxy -> signer mặc định; có proxy -> cache ===")
    pool = FakePool(default_signer_url="http://127.0.0.1:8080")
    try:
        d = pool.signer_for("")
        check("proxy rỗng trả signer mặc định",
              d is pool._default_signer)
        p1 = "http://user:pass@1.2.3.4:8080"
        s1 = pool.signer_for(p1)
        s2 = pool.signer_for(p1)
        check("cùng proxy trả cùng signer", s1 is s2)
        check("chỉ spawn 1 lần cho 1 proxy", len(pool.spawned), 1)
        p2 = "http://user:pass@5.6.7.8:1081"
        s3 = pool.signer_for(p2)
        check("proxy khác trả signer khác", s3 is not s1)
        check("đã spawn 2 proxy", len(pool.spawned), 2)
    finally:
        pool.shutdown()


def test_errors():
    print("\n=== 2. Proxy lỗi / quá giới hạn ===")
    pool = FakePool(default_signer_url="http://127.0.0.1:8080",
                    max_instances=1)
    try:
        pool.signer_for("http://u:p@1.2.3.4:8080")
        try:
            pool.signer_for("http://u:p@5.6.7.8:8081")
            got = "không lỗi"
        except SidecarPoolError as e:
            got = "SidecarPoolError" if "tối đa" in str(e) else str(e)
        check("vượt max_instances báo lỗi", got, "SidecarPoolError")

        pool2 = FakePool()
        try:
            pool2.signer_for("socks5://1.2.3.4:1080")
            got2 = "không lỗi"
        except SidecarPoolError as e:
            got2 = "socks" if "socks5" in str(e) else str(e)
        check("socks5 bị từ chối rõ ràng", got2, "socks")
        check("không cache proxy lỗi", pool2.count(), 0)
        pool2.shutdown()

        pool3 = FakeFailPool()
        try:
            p_fail = "http://u:p@9.9.9.9:9999"
            for _ in range(2):
                try:
                    pool3.signer_for(p_fail)
                except SidecarPoolError:
                    pass
            check("proxy lỗi chỉ thử spawn 1 lần", len(pool3.spawned), 1)
        finally:
            pool3.shutdown()
    finally:
        pool.shutdown()


def test_reset_and_mask():
    print("\n=== 3. reset xoá cache; che mật khẩu ===")
    pool = FakePool()
    try:
        p = "http://user:secret@1.2.3.4:8080"
        pool.signer_for(p)
        check("có 1 instance", pool.count(), 1)
        pool.reset()
        check("reset xoá instance", pool.count(), 0)
        pool.signer_for(p)
        check("gọi lại spawn lại", len(pool.spawned), 2)
        prof = parse_proxy(p)
        check("parse giữ đúng user", prof.username, "user")
        check("_mask không chứa mật khẩu",
              "secret" not in __import__("core.sidecar_pool", fromlist=["_mask"])._mask(p),
              True)
    finally:
        pool.shutdown()
        pool.shutdown()   # gọi lần 2 phải an toàn
    check("shutdown lặp lại an toàn", True)


def test_ram_guard():
    print("\n=== 4. RAM thấp -> không mở sidecar ===")
    import core.sidecar_pool as sp

    old = sp.available_ram_mb
    sp.available_ram_mb = lambda: 100
    pool = FakePool()
    try:
        try:
            pool.signer_for("http://u:p@7.7.7.7:8080")
            got = "không lỗi"
        except SidecarPoolError as e:
            got = "ram" if "RAM trống" in str(e) else str(e)
        check("RAM < ngưỡng bị chặn", got, "ram")
        check("không spawn khi RAM thấp", pool.spawned, [])
        check("RAM thấp không cache lỗi proxy", pool.count(), 0)
    finally:
        sp.available_ram_mb = old
        pool.shutdown()

    sp.available_ram_mb = lambda: 4096
    pool2 = FakePool()
    try:
        check("RAM đủ thì mở bình thường",
              bool(pool2.signer_for("http://u:p@8.8.8.8:8080")), True)
    finally:
        sp.available_ram_mb = old
        pool2.shutdown()

    check("đọc RAM thật trả số dương hoặc None",
          (sp.available_ram_mb() is None or sp.available_ram_mb() > 0), True)


def main():
    test_default_and_cache()
    test_errors()
    test_reset_and_mask()
    test_ram_guard()
    print(f"\n{PASS} pass, {FAIL} fail")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())

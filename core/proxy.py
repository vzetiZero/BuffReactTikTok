"""Quản lý proxy: parse, phân phối cho từng account, kiểm tra sống.

Hỗ trợ các định dạng proxy thông dụng, gồm cả của VPN Express:

    1.2.3.4:8080                              (IP:port)
    1.2.3.4:8080:user:pass                    (IP:port:user:pass)
    user:pass@1.2.3.4:8080                    (user:pass@IP:port)
    socks5://1.2.3.4:1080
    http://user:pass@1.2.3.4:8080
    # comment được bỏ qua

Ngoài ra có "cổng VPN Express" (gateway) — dùng MỘT địa chỉ cổng + username
nhiều account khác nhau, khác nhau ở `session` để mỗi account giữ một IP riêng:

    http://{user}-country-vn-session-{session}:{pass}@gate.vpnexpress.net:10000
"""

from __future__ import annotations

import hashlib
import os
import random
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import quote, unquote

# Mã lỗi của TikTok liên quan tới IP / chống bot -> nên đổi proxy
IP_BLOCK_CODES = {8, 10202, 10221, 10222, 10223, 10225, 350002}

# Địa chỉ dòng IP thoát ra ngoài (dùng để kiểm tra proxy)
IP_ECHO_APIS = [
    "https://ipinfo.io/json",
    "https://api.ip.sb/geoip",
    "https://ipapi.co/json",
]

MODE_ROUND_ROBIN = "round_robin"
MODE_RANDOM = "random"
MODE_FIXED = "fixed"
MODE_GATEWAY = "gateway"

MODE_LABELS = {
    MODE_ROUND_ROBIN: "Luân phiên (mỗi account 1 proxy, xoay vòng)",
    MODE_RANDOM: "Ngẫu nhiên mỗi lần chạy",
    MODE_FIXED: "Giữ nguyên proxy đã gán",
    MODE_GATEWAY: "Cổng VPN Express (session riêng từng account)",
}

_SCHEMES = {"http", "https", "socks5", "socks5h"}


@dataclass
class ProxyProfile:
    """Một proxy đã parse xong."""

    raw: str = ""
    scheme: str = "http"
    host: str = ""
    port: int = 0
    username: str = ""
    password: str = ""
    label: str = ""
    enabled: bool = True
    origin: str = "list"          # "list" | "gateway"

    # --- kết quả kiểm tra (runtime) ---
    ok: bool | None = None
    latency_ms: int = 0
    exit_ip: str = ""
    country: str = ""
    err: str = ""
    assigned: int = 0             # số account đang dùng
    checked_at: float = 0.0

    def __post_init__(self) -> None:
        if not self.label:
            self.label = f"{self.host}:{self.port}" if self.host else self.raw[:40]

    @property
    def auth(self) -> bool:
        return bool(self.username)

    def fingerprint(self) -> str:
        """Khoá nhận dạng nội bộ — dùng để so sánh 2 proxy có phải cùng IP hay không.

        Proxy chỉ đổi `password` (xoay dải rộng) thì vẫn là CÙNG một IP → không
        phải xem là "đã đổi proxy". Vì vậy bỏ qua hoàn toàn `username`/`password`.
        """
        return f"{self.scheme}://{self.host}:{self.port}"

    def to_url(self) -> str:
        """Dạng curl_cffi chấp nhận (ẩn mật khẩu khi hiển thị)."""
        if not self.host:
            return ""
        cred = ""
        if self.username:
            cred = f"{quote(self.username, safe='')}:{quote(self.password, safe='')}@"
        return f"{self.scheme}://{cred}{self.host}:{self.port}"

    def safe_url(self) -> str:
        """Dạng hiển thị — mật khẩu bị che."""
        if not self.username:
            return f"{self.scheme}://{self.host}:{self.port}"
        return f"{self.scheme}://{self.username}:***@{self.host}:{self.port}"

    def open_line(self) -> str:
        return (
            f"✔ {self.label} · {self.exit_ip or '?'} "
            f"{('· ' + self.country) if self.country else ''} · {self.latency_ms}ms"
            if self.ok
            else f"✖ {self.label} · {self.err[:60]}"
        )


# --------------------------------------------------------------------------- #
# Parse
# --------------------------------------------------------------------------- #
def parse_proxy(raw: str, origin: str = "list") -> ProxyProfile | None:
    """Đọc 1 dòng proxy. Trả None nếu dòng rác / ghi chú."""
    s = (raw or "").strip().strip("`").strip()
    if not s or s.startswith(("#", "//", ";")):
        return None

    scheme = "http"
    if "://" in s:
        scheme, _, s = s.partition("://")
        scheme = scheme.strip().lower()
        if scheme not in _SCHEMES:
            return None

    username = password = ""
    if "@" in s:
        cred, _, hostpart = s.rpartition("@")
        if ":" in cred:
            username, _, password = cred.partition(":")
        else:
            username = cred
        username, password = unquote(username), unquote(password)
        s = hostpart

    parts = [p.strip() for p in s.split(":") if p != ""]
    if len(parts) >= 4:
        host, port_s, username = parts[0], parts[1], parts[2]
        password = ":".join(parts[3:])
    elif len(parts) == 3:
        # socks5:host:port  hoặc  host:port:user
        if parts[0].lower() in ("socks5", "socks5h"):
            host, port_s = parts[1], parts[2]
        else:
            host, port_s = parts[0], parts[1]
            username = parts[2]
    elif len(parts) == 2:
        host, port_s = parts
    else:
        return None

    if not host:
        return None
    try:
        port = int(port_s)
    except ValueError:
        return None
    if not (0 < port < 65536):
        return None

    return ProxyProfile(
        raw=raw.strip(), scheme=scheme, host=host, port=port,
        username=username, password=password, origin=origin,
    )


def parse_block(text: str) -> tuple[list[ProxyProfile], list[str]]:
    """Parse cả khối nhiều dòng. Trả (danh sách proxy, danh sách dòng lỗi)."""
    good: list[ProxyProfile] = []
    bad: list[str] = []
    for line in (text or "").splitlines():
        p = parse_proxy(line)
        if p is None:
            if line.strip() and not line.strip().startswith(("#", "//", ";")):
                bad.append(line.strip()[:80])
        else:
            good.append(p)
    return good, bad


# --------------------------------------------------------------------------- #
# Cổng VPN Express
# --------------------------------------------------------------------------- #
@dataclass
class GatewayConfig:
    """Thông tin cổng xoay IP — kiểu VPN Express.

    Biến hỗ trợ trong mẫu URL: {user} {pass}/{password} {host} {port}
                              {country} {session} {account}
    """

    template: str = "http://{user}-country-{country}-session-{session}:{pass}@{host}:{port}"
    host: str = "gate.vpnexpress.net"
    port: int = 10000
    user: str = ""
    password: str = ""
    country: str = "vn"
    scheme: str = "http"
    enabled: bool = False

    def build(self, account_id: str, fresh: bool = False) -> ProxyProfile | None:
        if not self.user:
            return None
        if fresh:
            # session ngẫu nhiên -> IP khác so với lần trước
            session = hashlib.sha1(
                f"{account_id}|{time.time_ns()}|{random.random()}".encode()
            ).hexdigest()[:10]
        else:
            # session ổn định -> account giữ nguyên IP giữa các lần chạy
            session = hashlib.sha1(
                f"{account_id}|{self.host}|{self.user}".encode()
            ).hexdigest()[:10]
        tpl = (self.template or "").replace("{pass}", "{password}")
        try:
            raw = tpl.format(
                user=self.user, password=self.password, host=self.host,
                port=self.port, country=self.country, session=session,
                account=account_id,
            )
        except (KeyError, IndexError, ValueError):
            return None
        p = parse_proxy(raw, origin="gateway")
        if p:
            p.label = f"cổng·{self.country}·{session[:6]}"
        return p


# --------------------------------------------------------------------------- #
# Pool
# --------------------------------------------------------------------------- #
class ProxyPool:
    """Danh sách proxy + cách gán cho từng account."""

    def __init__(self, mode: str = MODE_ROUND_ROBIN, gateway: GatewayConfig | None = None):
        self.mode = mode
        self.gateway = gateway or GatewayConfig()
        self._items: list[ProxyProfile] = []
        self._by_account: dict[str, str] = {}     # account_id -> raw proxy
        self._cursor = 0
        self._lock = threading.RLock()

    # ---- danh sách ---------------------------------------------------- #
    @property
    def items(self) -> list[ProxyProfile]:
        with self._lock:
            return list(self._items)

    def load(self, text: str) -> tuple[int, list[str]]:
        items, bad = parse_block(text)
        with self._lock:
            self._items = items
            self._by_account.clear()
            self._cursor = 0
        return len(items), bad

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._by_account.clear()

    def enabled_items(self) -> list[ProxyProfile]:
        return [p for p in self.items if p.enabled]

    def count(self) -> int:
        return len(self.items)

    def usable_count(self) -> int:
        return len(self.enabled_items())

    # ---- gán ---------------------------------------------------------- #
    def assign(self, accounts: list, force: bool = True) -> dict[str, int]:
        """Gán proxy cho từng account. Trả thống kê theo chế độ."""
        stats = {"assigned": 0, "mode": self.mode, "gateway": 0}

        with self._lock:
            if not force:
                self._by_account = {
                    k: v for k, v in self._by_account.items() if v
                }
            else:
                self._by_account.clear()
            self._cursor = 0

        if self.mode == MODE_GATEWAY and self.gateway.enabled:
            for acc in accounts:
                p = self.gateway.build(acc.id)
                if p is None:
                    continue
                with self._lock:
                    self._by_account[acc.id] = p.to_url()
                acc.proxy = p.to_url()
                acc.proxy_label = p.label
                stats["assigned"] += 1
                stats["gateway"] += 1
            self._recount()
            return stats

        pool = self.enabled_items()
        if not pool:
            for acc in accounts:
                acc.proxy = ""
                acc.proxy_label = ""
            return stats

        for i, acc in enumerate(accounts):
            p = pool[i % len(pool)] if self.mode != MODE_RANDOM \
                else random.choice(pool)
            with self._lock:
                self._by_account[acc.id] = p.to_url()
            acc.proxy = p.to_url()
            acc.proxy_label = p.label
            stats["assigned"] += 1
        self._recount()
        return stats

    def unassign(self, accounts: list) -> None:
        with self._lock:
            for acc in accounts:
                self._by_account.pop(acc.id, None)
                acc.proxy = ""
                acc.proxy_label = ""
        self._recount()

    def _recount(self) -> None:
        used = set(self._by_account.values())
        for p in self.items:
            p.assigned = sum(1 for u in used if u == p.to_url())

    def mapping(self) -> dict[str, str]:
        with self._lock:
            return dict(self._by_account)

    # ---- dùng khi chạy ------------------------------------------------- #
    def url_for(self, account) -> str:
        return getattr(account, "proxy", "") or ""

    def rotate(self, account) -> str:
        """Đổi sang proxy khác cho account (dùng khi bị chặn IP)."""
        if self.mode == MODE_GATEWAY:
            # fresh=True -> session mới -> chắc chắn ra IP khác
            p = self.gateway.build(getattr(account, "id", ""), fresh=True)
            if p:
                account.proxy = p.to_url()
                account.proxy_label = p.label
                with self._lock:
                    self._by_account[account.id] = p.to_url()
                return account.proxy
            return self.url_for(account)

        pool = self.enabled_items()
        if not pool:
            return ""
        current = self.url_for(account)
        # chỉ coi là "đã đổi" khi khác cả IP, tránh vòng lặp vô tận với dải rộng
        cur_fp = ""
        for p in pool:
            if p.to_url() == current:
                cur_fp = p.fingerprint()
                break

        with self._lock:
            self._cursor += 1
            p = pool[self._cursor % len(pool)]
        tries = 0
        while p.fingerprint() == cur_fp and tries < len(pool):
            with self._lock:
                self._cursor += 1
                p = pool[self._cursor % len(pool)]
            tries += 1

        account.proxy = p.to_url()
        account.proxy_label = p.label
        with self._lock:
            self._by_account[account.id] = p.to_url()
        return account.proxy

    def has_any(self) -> bool:
        if self.mode == MODE_GATEWAY:
            return bool(self.gateway.user)
        return bool(self.enabled_items())


# --------------------------------------------------------------------------- #
# Proxy hệ thống
# --------------------------------------------------------------------------- #
def _from_winreg() -> tuple[str, str]:
    """Windows: đọc WinINET — cùng nguồn với trình duyệt đang dùng."""
    import winreg  # chỉ tồn tại trên Windows

    path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
            enable = int(winreg.QueryValueEx(k, "ProxyEnable")[0])
            raw = str(winreg.QueryValueEx(k, "ProxyServer")[0])
    except (OSError, FileNotFoundError, ImportError):
        return "", ""

    if not enable or not raw:
        return "", ""

    # dạng "http=1.2.3.4:8080;https=5.6.7.8:8443" hoặc "1.2.3.4:8080"
    picked = ""
    for part in raw.split(";"):
        key, _, val = part.partition("=")
        if key.lower() in ("https", "http"):
            picked = val.strip()
            break
    if not picked and "=" not in raw:
        picked = raw.strip()
    if not picked:
        return "", ""
    if "://" not in picked:
        picked = f"http://{picked}"
    return picked, "Windows (WinINET)"


def _from_scutil() -> tuple[str, str]:
    """macOS: `scutil --proxy` là nguồn chuẩn của Safari và Chrome."""
    import subprocess

    try:
        out = subprocess.run(
            ["scutil", "--proxy"], capture_output=True, text=True, timeout=5
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return "", ""
    host = port = ""
    for line in out.splitlines():
        k, _, v = line.partition(" : ")
        v = v.strip()
        if not v:
            continue
        if k == "ProxyAutoConfigEnableString":
            # PAC -> không dùng được vì cần chạy JS để tìm proxy hiện hành
            return "", ""
        if k == "HTTPSProxy":
            host = v
        elif k == "HTTPSPort":
            port = v
    if host and port:
        return f"http://{host}:{port}", "macOS (scutil)"
    return "", ""


def _from_gsettings() -> tuple[str, str]:
    """Linux/GNOME: `gsettings`."""
    import subprocess

    try:
        mode = subprocess.run(
            ["gsettings", "get", "org.gnome.system.proxy", "mode"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip().strip("'")
    except (OSError, subprocess.SubprocessError):
        return "", ""
    if mode != "manual":
        return "", ""
    host = port = ""
    for key, var in (("host", "host"), ("port", "port")):
        try:
            val = subprocess.run(
                ["gsettings", "get", "org.gnome.system.proxy.http", var],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip().strip("'")
        except (OSError, subprocess.SubprocessError):
            continue
        if key == "host":
            host = val
        else:
            port = val
    if host and port:
        return f"http://{host}:{port}", "GNOME (gsettings)"
    return "", ""


def _from_env() -> tuple[str, str]:
    """Biến môi trường — hoạt động trên cả 3 hệ điều hành."""
    for var in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy",
                "HTTP_PROXY", "http_proxy"):
        v = os.environ.get(var)
        if v and v.strip():
            v = v.strip()
            if "://" not in v:
                v = f"http://{v}"
            return v, f"biến môi trường {var.upper()}"
    return "", ""


def detect_system_proxy() -> tuple[str, str]:
    """Tìm proxy đang bật trên máy. Trả (url, nguồn); url rỗng nếu không có."""
    probes = (_from_winreg, _from_scutil, _from_gsettings, _from_env)
    for fn in probes:
        try:
            url, src = fn()
        except Exception:
            continue
        if url:
            return url, src
    return "", ""


# --------------------------------------------------------------------------- #
# Kiểm tra sống
# --------------------------------------------------------------------------- #
def check_one(proxy: ProxyProfile, timeout: float = 8.0,
              local_ip: str = "") -> ProxyProfile:
    """Kiểm tra 1 proxy: độ trễ + IP thoát + quốc gia."""
    t0 = time.perf_counter()
    try:
        from curl_cffi import requests as cf

        url = proxy.to_url()
        sess = cf.Session(impersonate="chrome", proxies={"http": url, "https": url},
                          verify=False)
        data = None
        for api in IP_ECHO_APIS:
            try:
                r = sess.get(api, timeout=timeout)
                if r.status_code == 200:
                    data = r.json()
                    break
            except Exception:
                continue
        if not data:
            raise RuntimeError("không đọc được IP thoát")
        sess.close()

        ip = str(data.get("ip") or data.get("query") or "")
        proxy.exit_ip = ip
        proxy.country = str(data.get("country") or data.get("country_code") or "")
        proxy.ok = bool(ip)
        if local_ip and ip == local_ip:
            proxy.ok = False
            proxy.err = "IP thoát trùng IP máy (proxy không hoạt động)"
        elif not proxy.ok:
            proxy.err = "không lấy được IP"
    except Exception as e:
        proxy.ok = False
        proxy.err = f"{type(e).__name__}: {str(e)[:80]}"
    proxy.latency_ms = int((time.perf_counter() - t0) * 1000)
    proxy.checked_at = time.time()
    return proxy


def my_ip(timeout: float = 6.0) -> str:
    """IP hiện tại của máy (không qua proxy) — để so sánh."""
    try:
        from curl_cffi import requests as cf

        sess = cf.Session(impersonate="chrome", verify=False)
        try:
            for api in IP_ECHO_APIS:
                try:
                    r = sess.get(api, timeout=timeout)
                    if r.status_code == 200:
                        return str(r.json().get("ip") or "")
                except Exception:
                    continue
        finally:
            sess.close()
    except Exception:
        pass
    return ""


def check_many(pool: ProxyPool, workers: int = 8, timeout: float = 8.0,
               on_done=None) -> int:
    """Kiểm tra song song toàn bộ proxy trong pool. Trả số đã kiểm tra."""
    items = pool.enabled_items()
    if not items:
        return 0
    local = my_ip()
    total = len(items)
    done = 0
    lock = threading.Lock()
    queue = list(items)
    queue_lock = threading.Lock()

    def worker() -> None:
        nonlocal done
        while True:
            with queue_lock:
                if not queue:
                    return
                p = queue.pop(0)
            check_one(p, timeout=timeout, local_ip=local)
            with lock:
                done += 1
                if on_done:
                    on_done(done, total, p)

    threads = [threading.Thread(target=worker, daemon=True)
               for _ in range(max(1, min(workers, total)))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return done

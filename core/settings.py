"""Lưu cấu hình ứng dụng (kể cả mật khẩu proxy) vào file JSON cục bộ."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .proxy import MODE_ROUND_ROBIN, GatewayConfig, ProxyPool


def default_path() -> Path:
    base = os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "TikTokManager" / "settings.json"


def accounts_cache_path() -> Path:
    """Nơi nhớ danh sách tài khoản đã nạp, để mở app lần sau khỏi nạp lại."""
    return default_path().parent / "accounts.json"


def save_accounts_cache(accounts: list, path: Path | None = None) -> Path:
    """Ghi lại tài khoản đã nạp.

    File này chứa cookie đầy đủ — tức tương đương MẬT KHẨU. Nó nằm trong
    thư mục cấu hình của người dùng, không nằm trong thư mục dự án, và
    `.gitignore` đã chặn. Tuy vậy coi nó như file bí mật: đừng copy đi
    đừng gửi cho ai.

    Chỉ lưu phần CẦN THIẾT để chạy lại. Bỏ các trường runtime (trạng thái,
    proxy) vì chúng thuộc về phiên làm việc, không thuộc tài khoản.
    """
    p = Path(path) if path else accounts_cache_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "id": a.id,
            "username": a.username,
            "email": a.email,
            "password": a.password,
            "ms_token": a.ms_token,
            "device_id": a.device_id,
            "cookie": a.cookie,
            "raw": a.raw,
        }
        for a in accounts
    ]
    p.write_text(
        json.dumps(rows, ensure_ascii=False), encoding="utf-8"
    )
    # Chỉ chính người dùng này được đọc (vô hiệu trên Windows)
    try:
        p.chmod(0o600)
    except OSError:
        pass
    return p


def load_accounts_cache(path: Path | None = None) -> list:
    """Đọc lại tài khoản đã lưu. Trả list rỗng nếu chưa có hoặc hỏng."""
    from .models import Account  # vòng tròn import: để trong hàm

    p = Path(path) if path else accounts_cache_path()
    if not p.exists():
        return []
    try:
        rows = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(rows, list):
        return []
    out: list[Account] = []
    for r in rows:
        if not isinstance(r, dict) or not r.get("username"):
            continue
        cookie = r.get("cookie")
        out.append(Account(
            id=str(r.get("id") or ""),
            username=str(r.get("username") or ""),
            email=str(r.get("email") or ""),
            password=str(r.get("password") or ""),
            ms_token=str(r.get("ms_token") or ""),
            device_id=str(r.get("device_id") or ""),
            cookie=cookie if isinstance(cookie, dict) else {},
            raw=str(r.get("raw") or ""),
        ))
    return out


@dataclass
class AppSettings:
    # --- proxy ---
    proxy_text: str = ""
    proxy_mode: str = MODE_ROUND_ROBIN
    proxy_auto_check: bool = False
    proxy_check_timeout: float = 8.0

    gw_template: str = GatewayConfig().template
    gw_host: str = GatewayConfig().host
    gw_port: int = GatewayConfig().port
    gw_user: str = ""
    gw_pass: str = ""
    gw_country: str = GatewayConfig().country
    gw_enabled: bool = False

    # --- chạy ---
    concurrency: int = 10
    delay_min: float = 0.0
    delay_max: float = 1.0
    retries: int = 1
    region: str = "VN"
    timezone: str = "Asia/Bangkok"
    language: str = ""            # để trống = tự đoán từ cookie
    signer_url: str = "http://127.0.0.1:8080"
    verify: bool = True
    rotate_on_block: bool = True
    check_timeout: float = 15.0     # thời gian chờ khi kiểm tra tài khoản

    # --- proxy hệ thống ---
    use_system_proxy: bool = True
    system_proxy: str = ""         # phát hiện tự động, có thể sửa tay

    # --- đường dẫn ---
    last_cookie_file: str = ""
    backend_kind: str = "http"
    remember_accounts: bool = True   # nhớ tài khoản đã nạp, mở lại khỏi nạp
    per_page: int = 50               # số dòng mỗi trang
    cid_list: str = ""               # danh sách cid đang làm việc (nhớ lại)
    compact_rows: bool = True        # dòng bảng gọn, 50 dòng / 1 trang

    # ------------------------------------------------------------------ #
    def apply_to_pool(self, pool: ProxyPool) -> None:
        pool.mode = self.proxy_mode
        pool.gateway = GatewayConfig(
            template=self.gw_template, host=self.gw_host, port=self.gw_port,
            user=self.gw_user, password=self.gw_pass, country=self.gw_country,
            scheme="http", enabled=self.gw_enabled,
        )
        if self.proxy_text:
            pool.load(self.proxy_text)

    def from_widgets(self, **kw) -> None:
        for k, v in kw.items():
            if hasattr(self, k):
                setattr(self, k, v)

    def save(self, path: Path | None = None) -> Path:
        p = Path(path) if path else default_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return p

    @classmethod
    def load(cls, path: Path | None = None) -> "AppSettings":
        p = Path(path) if path else default_path()
        if not p.exists():
            return cls()
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in raw.items() if k in known})

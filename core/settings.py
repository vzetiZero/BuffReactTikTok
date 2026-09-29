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

    # --- proxy hệ thống ---
    use_system_proxy: bool = True
    system_proxy: str = ""         # phát hiện tự động, có thể sửa tay

    # --- đường dẫn ---
    last_cookie_file: str = ""
    backend_kind: str = "http"

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

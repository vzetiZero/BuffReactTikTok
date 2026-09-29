"""Ký request TikTok (X-Bogus / X-Gnarly / msToken) qua một Node sidecar.

Vì sao cần sidecar: web TikTok bắt buộc mọi request API có chữ ký. Thuật toán
nằm trong `webmssdk` đã obfuscate (ChaCha-XOR + TLV). Thay vì port lại sang
Python (rủi ro vỡ mỗi lần TikTok đổi bản), ta gọi 1 tiến trình Node chạy sẵn
SDK thật — 1 tiến trình phục vụ cho MỌI luồng Python.

Đây là nút thắt duy nhất của hệ thống (~12 chữ ký/giây), nên:
  - Python đa luồng đẩy hết phần HTTP (nhanh, I/O bound)
  - Sidecar lo phần ký (chậm, CPU bound)
Muốn nhanh hơn nữa thì chạy 2-3 sidecar ở các cổng khác nhau.

Xem README.md mục "Cài sidecar ký".
"""

from __future__ import annotations

import threading

import requests


class SignerError(RuntimeError):
    pass


class Signer:
    """Client của tiktok-signature (carcabot/tiktok-signature)."""

    def __init__(self, base_url: str = "http://127.0.0.1:8080", timeout: float = 25.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._tls = threading.local()
        self._nav_lock = threading.Lock()
        self._navigator: dict | None = None

    # ------------------------------------------------------------------ #
    def _session(self) -> requests.Session:
        s = getattr(self._tls, "s", None)
        if s is None:
            s = requests.Session()
            s.mount("http://", requests.adapters.HTTPAdapter(pool_maxsize=32))
            self._tls.s = s
        return s

    # ------------------------------------------------------------------ #
    def health(self, timeout: float = 4.0) -> dict:
        try:
            r = self._session().get(f"{self.base_url}/health", timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            raise SignerError(f"không gọi được sidecar tại {self.base_url}: {e}") from e

    def is_ready(self) -> bool:
        try:
            return bool(self.health().get("ready"))
        except SignerError:
            return False

    def restart(self) -> None:
        try:
            self._session().get(f"{self.base_url}/restart", timeout=60)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    def sign(self, url: str) -> dict:
        """url chưa ký -> dict {signed_url, navigator, cookies, device_id}."""
        try:
            r = self._session().post(
                f"{self.base_url}/signature", json={"url": url}, timeout=self.timeout
            )
        except requests.RequestException as e:
            raise SignerError(f"lỗi gọi sidecar: {e}") from e

        if r.status_code != 200:
            raise SignerError(f"sidecar trả HTTP {r.status_code}: {r.text[:160]}")
        try:
            payload = r.json()
        except ValueError as e:
            raise SignerError(f"sidecar trả JSON sai: {r.text[:160]}") from e

        if payload.get("status") != "ok" or "data" not in payload:
            raise SignerError(str(payload)[:200])

        data = payload["data"]
        self._cache_navigator(data.get("navigator") or {})
        return data

    def _cache_navigator(self, nav: dict) -> None:
        if not nav:
            return
        with self._nav_lock:
            if self._navigator is None:
                self._navigator = dict(nav)

    def navigator(self) -> dict:
        with self._nav_lock:
            return dict(self._navigator) if self._navigator else {}

    def warmup(self) -> dict:
        """Gọi 1 lần để lấy fingerprint (bắt buộc, tránh lỗi 'url doesn't match').

        URL này chỉ để hỏi navigator, không dùng kết quả.
        """
        self.sign("https://www.tiktok.com/api/user/detail/?aid=1988&app_name=tiktok_web")
        return self.navigator()

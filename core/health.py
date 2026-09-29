"""Kiểm tra sức khoẻ tài khoản: cookie còn dùng được, đã die, hay hết hạn.

Vì sao cần cẩn thận
------------------
Đo thật cho thấy `/api/comment/digg/` trả `status_code: 0` **kể cả khi đã
xoá sạch `sessionid_ss`/`sid_tt`**. Endpoint thả tim không kiểm tra phiên, nên
KHÔNG THỂ dùng nó để kết luận tài khoản còn sống.

`/api/user/detail/` thì ngược lại: đang trả `statusCode: 10221` (phát hiện
bot) **cho cả cookie tốt lẫn cookie chết**, nên nó cũng không phân biệt được
trong lúc IP bị TikTok soi.

Vì vậy kết quả chia làm 5 mức, và `HC_RISKY` là mức "không biết" — cố tình
KHÔNG gán "chết" khi chỉ vì bị chặn, vì như vậy người dùng sẽ xoá nhầm mấy
tài khoản đang tốt.

    HC_EXPIRED  chắc chắn hết hạn  — đọc được từ sid_guard, không cần mạng
    HC_DEAD     chắc chắn hỏng     — TikTok nói rõ phiên không còn
    HC_ALIVE    chắc chắn còn      — TikTok trả về thông tin tài khoản
    HC_RISKY    không kết luận     — bị chặn bot / IP, KHÔNG phải do cookie
    HC_UNKNOWN  chưa kiểm tra
"""

from __future__ import annotations

import threading
import time

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, Slot

from .models import (
    HC_ALIVE,
    HC_DEAD,
    HC_EXPIRED,
    HC_RISKY,
    Account,
)

# Mã TikTok nói "phiên đăng nhập không còn hiệu lực" — tín hiệu CHẮC CHẮN
# cookie hỏng, khác hẳn với bị chặn.
DEAD_CODES = {200013, 200009}
# Bị chặn -> KHÔNG kết luận cookie chết được.
BLOCK_CODES = {10202, 10221, 10222, 8}


class HealthSignals(QObject):
    """Cầu nối thread-safe từ worker sang GUI."""

    result = Signal(str, str, str, float)   # acc_id, health, note, time


class HealthTask(QRunnable):
    """Kiểm tra 1 tài khoản."""

    def __init__(self, account: Account, sig: HealthSignals, region: str,
                 timezone: str, proxy: str, timeout: float = 15.0,
                 signer_url: str = "http://127.0.0.1:8080",
                 local_only: bool = False):
        super().__init__()
        self.account = account
        self.sig = sig
        self.region = region
        self.timezone = timezone
        self.proxy = proxy
        self.timeout = timeout
        self.signer_url = signer_url
        self.local_only = local_only
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        aid = self.account.id
        try:
            health, note = self._check()
        except Exception as e:
            health, note = HC_RISKY, f"{type(e).__name__}: {str(e)[:110]}"
        self.sig.result.emit(aid, health, note, time.time())

    def _check(self) -> tuple[str, str]:
        acc = self.account

        # --- 1. kiểm tra cục bộ, không tốn request ---
        if not acc.has_session():
            return HC_DEAD, "cookie thiếu sessionid_ss hoặc sid_tt"
        if acc.is_expired():
            return HC_EXPIRED, f"hết hạn {acc.expiry_hint()}"

        # Chế độ cục bộ: chỉ dựa vào cookie, không gọi mạng.
        # Dùng khi sidecar chưa chạy, hoặc khi người dùng chỉ muốn dọn file
        # nhanh. Kết quả là "có vẻ ổn", KHÔNG phải xác nhận từ server.
        if self.local_only:
            return HC_ALIVE, f"cookie ổn, hết hạn {acc.expiry_hint()} (chưa hỏi server)"

        # --- 2. hỏi TikTok ---
        from .signer import Signer, SignerError
        from .tiktok import TikTokClient, TikTokError

        try:
            client = TikTokClient(
                acc, Signer(self.signer_url), region=self.region,
                timezone=self.timezone, proxy=self.proxy,
                timeout=self.timeout, language="en",
            )
        except SignerError as e:
            return HC_RISKY, f"sidecar ký lỗi: {str(e)[:90]}"
        except Exception as e:
            return HC_RISKY, f"{type(e).__name__}: {str(e)[:90]}"

        try:
            r = client.user_detail(acc.username)
            if r.get("id"):
                nick = r.get("nickname") or "?"
                return HC_ALIVE, f"@{acc.username} → {nick} (id {r.get('id')})"
            return HC_ALIVE, f"@{acc.username} còn phiên"
        except TikTokError as e:
            code = e.code
            if code in DEAD_CODES:
                return HC_DEAD, f"TikTok trả {code}: {e}"
            if code in BLOCK_CODES:
                # BỊ CHẶN, KHÔNG PHẢI COOKIE CHẾT. Gán "die" ở đây là sai —
                # cùng một IP bị chặn thì MỌI tài khoản đều "chết" oan, và
                # người dùng sẽ xoá cả đàn tài khoản đang tốt.
                return HC_RISKY, f"TikTok chặn IP ({code}) — chưa kết luận được"
            return HC_RISKY, f"mã {code}: {e}"
        except Exception as e:
            return HC_RISKY, f"{type(e).__name__}: {str(e)[:110]}"
        finally:
            try:
                client.close()
            except Exception:
                pass


class HealthChecker(QObject):
    """Chạy kiểm tra nhiều tài khoản, cập nhật qua signal (không chạm GUI)."""

    checked = Signal(int, int)      # đã kiểm, tổng số
    all_done = Signal()
    log = Signal(str, str)

    POLL_MS = 80

    def __init__(self, settings, pool: QThreadPool | None = None, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._pool = pool or QThreadPool(self)
        self._pool.setMaxThreadCount(20)
        self._sig = HealthSignals()
        self._sig.result.connect(self._on_result)
        self._left = 0
        self._total = 0
        self._running = False
        self._lock = threading.Lock()

        self._timer = QTimer(self)
        self._timer.setInterval(self.POLL_MS)
        self._timer.timeout.connect(self._check_done)

    @property
    def running(self) -> bool:
        return self._running

    def start(self, accounts: list[Account], use_proxy: bool = True,
              local_only: bool = False) -> None:
        if self._running or not accounts:
            return
        s = self._settings
        with self._lock:
            self._left = len(accounts)
            self._total = len(accounts)
            self._running = True
        self._timer.start()
        for acc in accounts:
            proxy = ""
            if use_proxy:
                proxy = acc.proxy or getattr(s, "system_proxy", "")
            self._pool.start(HealthTask(
                acc, self._sig, s.region, s.timezone, proxy, s.check_timeout,
                s.signer_url, local_only,
            ))

    def stop(self) -> None:
        self._timer.stop()
        self._running = False

    @Slot(str, str, str, float)
    def _on_result(self, acc_id: str, health: str, note: str, at: float) -> None:
        """Chạy trên GUI thread.

        `_sig` được tạo trong GUI thread, nên kết nối tới slot này là queued
        và Qt tự chuyển về GUI thread — không cần `call_on_gui` nữa (dùng thêm
        sẽ thành hai chặng, vô nghĩa).

        Đây là nơi DUY NHẤT được phép chạm vào model: worker chỉ emit tín
        hiệu, không giữ tham chiếu tới bảng.
        """
        cb = self._on_applied
        if cb:
            cb(acc_id, health, note, at)
        with self._lock:
            self._left -= 1
        self.checked.emit(self._total - self._left, self._total)

    # MainWindow gắn callback này để cập nhật đúng model.
    _on_applied = None

    @Slot()
    def _check_done(self) -> None:
        with self._lock:
            done = self._left <= 0
        if not done or not self._running:
            return
        self._running = False
        self._timer.stop()
        self.all_done.emit()

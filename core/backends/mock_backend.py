"""Backend giả lập — dùng để test GUI + đa luồng mà không gọi TikTok."""

from __future__ import annotations

import hashlib
import random
import time

from ..config import MODE_CHECK, MODE_LIKE_CID, RunConfig
from ..models import ST_DONE, ST_FAIL, ST_OK, Account, TaskResult
from .base import Progress, StopFlag


def _mint(seed: str) -> int:
    return int(hashlib.sha1(seed.encode()).hexdigest()[:12], 16)


class MockBackend:
    name = "mock"

    def __init__(self, fail_rate: float = 0.15, scale: float = 1.0):
        """scale = hệ số nhân thời gian chờ (0 = tức thì, dùng để benchmark)."""
        self.fail_rate = fail_rate
        self.scale = scale

    def _nap(self, stop: StopFlag, seconds: float) -> bool:
        """Chờ; trả True nếu bị yêu cầu dừng."""
        return stop.wait(max(0.0, seconds) * self.scale)

    def run(self, account: Account, cfg: RunConfig, stop: StopFlag,
            progress: Progress) -> TaskResult:
        aid = account.id
        if not account.has_session():
            return TaskResult(ST_FAIL, "cookie thiếu sessionid_ss")

        progress(aid, "Đăng nhập (giả lập)...", 15)
        if self._nap(stop, random.uniform(0.2, 0.5)):
            return TaskResult(ST_FAIL, "đã dừng")

        if random.random() < self.fail_rate:
            return TaskResult(ST_FAIL, "phiên đăng nhập đã hết hạn")

        progress(aid, f"Đăng nhập OK — {account.username}", 30)
        if cfg.mode == MODE_CHECK:
            return TaskResult(ST_DONE, f"Cookie hợp lệ ({account.username})", ok=True)

        progress(aid, f"Thả tim cid={cfg.cid or '-'}...", 65)
        if self._nap(stop, 0.4):
            return TaskResult(ST_FAIL, "đã dừng")

        before = random.randint(10, 2000)
        cid = cfg.cid or str(7 * 10**18 + _mint(aid))
        note = f"♥ cid={cid} · like {before} → {before + 1}"
        progress(aid, note, 100)
        return TaskResult(
            ST_OK, note, comment_id=cid,
            found=cfg.mode == MODE_LIKE_CID, ok=True,
            like_after=before + 1,
        )

    def close_thread(self) -> None:
        pass

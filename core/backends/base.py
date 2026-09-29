"""Interface chung cho mọi backend xử lý 1 account."""

from __future__ import annotations

from typing import Callable, Protocol

from ..config import RunConfig
from ..models import Account, TaskResult

# progress(acc_id, message, percent)
Progress = Callable[[str, str, int], None]


class BaseBackend(Protocol):
    name: str

    def run(
        self,
        account: Account,
        cfg: RunConfig,
        stop: "StopFlag",
        progress: Progress,
    ) -> TaskResult:
        """Thực hiện 1 nhiệm vụ cho account. Không được chạm vào Qt widget."""

    def close_thread(self) -> None:
        """Dọn tài nguyên (browser) của luồng hiện tại. Gọi sau khi task xong."""


class StopFlag:
    """Wrapper mỏng quanh threading.Event để type rõ ràng."""

    def __init__(self, event):
        self._e = event

    def is_set(self) -> bool:
        return self._e.is_set()

    def wait(self, timeout: float) -> bool:
        return self._e.wait(timeout)

"""Đa luồng: QThreadPool + QRunnable, mọi kết quả đi ngược lại GUI bằng Signal.

Luồng kiến trúc
---------------
GUI thread : điều khiển, vẽ bảng, bấm nút
worker#N   : chạy backend cho account thứ N (tối đa `concurrency` luồng)
Signal     : nối bằng queued connection (mặc định) -> tự chuyển về GUI thread

Quy tắc bất di bất dịch: worker KHÔNG được gọi widget/model trực tiếp.
Chỉ emit signal. `MainWindow` là nơi duy nhất gọi `model.update_row()`.

Về `stop()`: cố tình KHÔNG dùng `QThreadPool.clear()`, vì task bị clear sẽ không
bao giờ phát tín hiệu hoàn tất -> treo bộ đếm. Thay vào đó mỗi runnable tự kiểm
tra `stop` ở đầu và phát `SKIP` ngay, nên luôn đúng-một-tín-hiệu-mỗi-task.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, Slot

from .backends.base import StopFlag
from .config import RunConfig
from .inflight import REST, TASK, tracker
from .models import ST_FAIL, ST_RUNNING, ST_SKIP, Account, TaskResult
from .proxy import IP_BLOCK_CODES


class Signals(QObject):
    """Cầu nối thread-safe giữa worker thread và GUI thread."""

    status = Signal(str, str, str)   # acc_id, status, note
    log = Signal(str, str)           # acc_id, message
    progress = Signal(str, int)     # acc_id, percent
    task_done = Signal(str)          # acc_id (task đã kết thúc thật)


class AccountTask(QRunnable):
    """Một task = một account."""

    def __init__(self, account, cfg, backend, signals, stop, pool=None,
                 rotate_on_block: bool = True, on_return=None):
        super().__init__()
        self.account = account
        self.cfg = cfg
        self.backend = backend
        self.sig = signals
        self.stop = stop
        self.pool = pool
        self.rotate_on_block = rotate_on_block
        # gọi ở CUỐI run(), trên chính thread worker, trước khi runnable trả về
        self.on_return = on_return
        self.setAutoDelete(True)

    # --- bridge: callback của backend -> Signal (queued) ------------- #
    def _progress(self, acc_id: str, msg: str, pct: int) -> None:
        self.sig.progress.emit(acc_id, max(0, min(100, int(pct))))
        if msg:
            self.sig.log.emit(acc_id, msg)

    @Slot()
    def run(self) -> None:
        # `task` = một tài khoản đang được xử lý. Đồng hồ "đang chờ" của GUI
        # đếm số này để thấy app còn sống ngay cả khi mọi luồng cùng kẹt.
        tok = tracker.enter(TASK)
        try:
            self._run()
        finally:
            tracker.leave(tok)
            # Báo "task đã trả về" ngay trên thread này. Nhờ vậy controller
            # không phải đoán bằng activeThreadCount() — thời điểm đó đã về 0
            # trước lúc signal của task cuối được giao tới GUI thread.
            if self.on_return:
                self.on_return(self.account.id)

    def _run(self) -> None:
        acc = self.account
        self.sig.status.emit(acc.id, ST_RUNNING, "")

        if self.stop.is_set():
            self.sig.status.emit(acc.id, ST_SKIP, "đã dừng trước khi chạy")
            self.sig.task_done.emit(acc.id)
            return

        result = TaskResult(ST_FAIL, "không chạy")
        attempts = max(1, self.cfg.retries + 1)
        for attempt in range(1, attempts + 1):
            if attempt > 1:
                # đổi proxy nếu lần trước bị chặn IP
                if (self.rotate_on_block and self.pool
                        and result.code in IP_BLOCK_CODES):
                    new = self.pool.rotate(acc)
                    if new:
                        self.sig.log.emit(
                            acc.id, f"Đổi proxy: {acc.proxy_label}", "warn"
                        )
                self.sig.log.emit(acc.id, f"thử lại {attempt}/{attempts}, nghỉ 3s...")
                tok = tracker.enter(REST)
                try:
                    stopped = self.stop.wait(3)
                finally:
                    tracker.leave(tok)
                if stopped:
                    break
            result = self.backend.run(
                acc, self.cfg, StopFlag(self.stop), self._progress
            )
            if result.ok or self.stop.is_set():
                break

        if self.stop.is_set() and not result.ok:
            result = TaskResult(ST_SKIP, "đã dừng")

        self.sig.progress.emit(acc.id, 100)
        # Lưu số like + cid để GUI in dòng "2 TIM CMT <cid>".
        # Ghi vào object Account (chỉ đọc) — runner chạy ở worker thread.
        if result.like_after is not None:
            acc.like_after = result.like_after
        if result.comment_id:
            acc.comment_id = result.comment_id
        self.sig.status.emit(acc.id, result.status, result.note)
        try:
            self.backend.close_thread()
        except Exception:
            pass
        self.sig.task_done.emit(acc.id)


class RunController(QObject):
    """Điều phối: chia task, đếm hoàn tất, dừng an toàn."""

    log = Signal(str, str)
    status = Signal(str, str, str)
    progress = Signal(str, int)
    started = Signal(int)   # số task được submit
    task_done = Signal(str)  # acc_id — một task đã kết thúc thật
    finished = Signal()

    # ms — đủ ngắn để "Xong" gần như tức thì, đủ dài để mọi signal kịp tới.
    # Nhờ có `_returned` đếm ở worker nên việc chờ thêm 60ms không ảnh hưởng
    # tính đúng, chỉ ảnh hưởng cảm giác tức thời.
    POLL_MS = 60

    def __init__(self, backend_factory, pool=None, rotate_on_block: bool = True,
                 parent=None):
        super().__init__(parent)
        self._factory = backend_factory
        self._proxy_pool = pool
        self._rotate = rotate_on_block
        self._pool = QThreadPool(self)
        self._sig = Signals(self)

        self._sig.log.connect(self.log)
        self._sig.status.connect(self.status)
        self._sig.progress.connect(self.progress)
        self._sig.task_done.connect(self._on_task_done)
        self._sig.task_done.connect(self.task_done)

        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._pending: set[str] = set()
        self._returned = 0          # số task đã THỰC SỰ trả về (đếm ở worker)
        self._total = 0
        self._running = False

        self._timer = QTimer(self)
        self._timer.setInterval(self.POLL_MS)
        self._timer.timeout.connect(self._check_pool_idle)

    @property
    def busy(self) -> bool:
        return self._running

    def start(self, accounts: list[Account], cfg: RunConfig) -> None:
        if self._running or not accounts:
            return
        self._stop.clear()
        backend = self._factory()
        self._pool.setMaxThreadCount(max(1, cfg.concurrency))

        with self._lock:
            self._pending = {a.id for a in accounts}
            self._returned = 0
            self._total = len(accounts)
            self._running = True

        self.started.emit(len(accounts))
        self._timer.start()
        for acc in accounts:
            self._pool.start(AccountTask(
                acc, cfg, backend, self._sig, self._stop,
                pool=self._proxy_pool, rotate_on_block=self._rotate,
                on_return=self._on_return,
            ))

    def stop(self) -> None:
        self._stop.set()

    def wait(self, msecs: int = -1) -> bool:
        return self._pool.waitForDone(msecs)

    # -------------------------------------------------------------- #
    def _on_return(self, acc_id: str) -> None:
        """Chạy trên WORKER thread ngay sau khi task kết thúc."""
        with self._lock:
            self._returned += 1

    @Slot(str)
    def _on_task_done(self, acc_id: str) -> None:
        with self._lock:
            self._pending.discard(acc_id)
        # KHÔNG kiểm tra xong tại đây. Hop tín hiệu này chỉ là hop thứ nhất;
        # các slot nối tiếp (ví dụ cập nhật đồng hồ tốc độ) chưa chạy. Gọi
        # _check_pool_idle ngay lúc này sẽ báo "Xong" trước khi bộ đếm đủ.
        # Việc quét để cho timer (POLL_MS) đảm nhiệm.

    @Slot()
    def _check_pool_idle(self) -> None:
        """Điều kiện XONG — cả hai đều phải đúng:

        1. `_returned == _total`: mọi task đã thực sự trả về. Đếm ngay trên
           worker nên chắc chắn; `activeThreadCount()` thì không, vì nó về 0
           *trước* khi signal của task cuối tới GUI thread.
        2. `_pending` rỗng: mọi signal đã được GUI thread xử lý, nên bảng đã
           hiển thị đủ kết quả trước khi báo "Xong".
        """
        with self._lock:
            done = self._returned >= self._total and not self._pending
        if not done or not self._running:
            return
        self._running = False
        self._timer.stop()
        self.finished.emit()

"""Theo dõi các việc ĐANG TREO — nguồn dữ liệu cho đồng hồ "đang chờ".

Vì sao cần
----------
Khi sidecar ký chậm hoặc TikTok giữ phản hồi, MỌI luồng cùng đứng yên và
nhật ký im lặng — người dùng tưởng app đã chết, bấm lại / đóng giữa chừng.
Thực ra hệ thống vẫn "đang chờ có chủ đích": 80 request đang kẹt ở bước ký,
hoặc 80 request đang chờ TikTok trả lời.

Bộ đếm này đủ rẻ để chạm vào mọi request (2 lần lock mỗi request — không
đáng kể so với network), nên GUI quét 4 lần/giây là biết ngay:
  - `task` : bao nhiêu tài khoản đang được xử lý (ở giữa một lần chạy)
  - `sign` : bao nhiêu request đang chờ sidecar ký  → nút thắt ở tầng 3
  - `http` : bao nhiêu request đang chờ TikTok      → nút thắt ở mạng/IP
  - `rest` : bao nhiêu luồng đang nghỉ chủ đích (trễ ngẫu nhiên / thử lại)

`snapshot()` trả về `kind -> (số lượng, giây chờ lâu nhất)` — cột "lâu nhất"
là thứ cho biết có thật sự bị giữ (≥ timeout 20-25s là sắp fail) hay chỉ là
độ trễ bình thường.

An toàn luồng: mọi thay đổi đều dưới một lock, giữ cực ngắn (chèn/xóa dict).
Worker chỉ gọi enter/leave; GUI chỉ gọi snapshot() — không chia sẻ object nào
khác giữa các luồng.
"""

from __future__ import annotations

import threading
import time

# --- các loại việc đang treo ---
TASK = "task"      # một tài khoản đang được xử lý
SIGN = "sign"      # chờ sidecar ký chữ ký
HTTP = "http"      # chờ TikTok trả lời HTTP
REST = "rest"      # nghỉ có chủ đích: trễ ngẫu nhiên / chờ thử lại

LABELS = {
    TASK: "việc đang chạy",
    SIGN: "chờ sidecar ký",
    HTTP: "chờ TikTok",
    REST: "nghỉ",
}


class InFlight:
    """Bộ đếm việc đang treo, an toàn cho nhiều luồng."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[int, tuple[str, float]] = {}
        self._seq = 0

    # ------------------------------------------------------------------ #
    def enter(self, kind: str) -> int:
        """Bắt đầu một việc. Trả token để `leave()` — luôn gọi trong finally."""
        with self._lock:
            self._seq += 1
            tok = self._seq
            self._items[tok] = (kind, time.perf_counter())
            return tok

    def leave(self, tok: int) -> None:
        """Kết thúc một việc. Không lỗi khi token đã bị gỡ (double leave)."""
        with self._lock:
            self._items.pop(tok, None)

    def clear(self) -> None:
        """Xóa sạch — dùng khi app vừa mở, tránh số của lần chạy trước sót."""
        with self._lock:
            self._items.clear()

    # ------------------------------------------------------------------ #
    def snapshot(self) -> dict[str, tuple[int, float]]:
        """`{kind: (số lượng, giây chờ lâu nhất)}` — chụp nguyên tử một lần."""
        now = time.perf_counter()
        buckets: dict[str, list[float]] = {}
        with self._lock:
            for kind, started in self._items.values():
                buckets.setdefault(kind, []).append(started)
        return {
            kind: (len(ts), now - min(ts))
            for kind, ts in buckets.items()
        }

    def count(self, kind: str) -> int:
        with self._lock:
            return sum(1 for k, _ in self._items.values() if k == kind)


# Một thể hiện dùng chung cho cả app (như `Signer`): worker enter/leave,
# GUI snapshot. Số nhỏ (≤ số luồng) nên lock không bao giờ thành nút thắt.
tracker = InFlight()

"""Phanh an toàn khi TikTok bắt đầu chặn IP / rate limit.

Một lô 200 account cùng thoát qua IP máy sẽ chạm hạn mức của TikTok sau
một lúc. Khi TikTok bắt đầu trả HTTP 200 với body rỗng (hoặc mã 8/10221),
gửi tiếp hàng trăm request chỉ làm IP bị chặn lâu hơn và làm log đỏ hàng
loạt. Guard này đếm các lỗi mạng/rate-limit *liên tiếp* trong một lần chạy
CID; chạm ngưỡng thì các task còn lại trả SKIP ngay, không tạo request mới.

Đây chỉ là phanh, KHÔNG phải cách vượt giới hạn IP. Muốn chạy nhiều CID
liên tiếp với 200 account mỗi CID, phải có proxy khác IP cho từng account
(hoặc chờ IP nguội).
"""

from __future__ import annotations

import threading

from ..proxy import IP_BLOCK_CODES

# Mã nội bộ — không phải mã TikTok. Dùng để runner biết "đừng thử lại".
RATE_LIMIT_CODE = -9
RATE_LIMIT_TAG = "TikTok chặn IP/rate limit"
RATE_LIMIT_STOP_NOTE = f"{RATE_LIMIT_TAG} — đã dừng lô"
RATE_LIMIT_SKIP_NOTE = f"{RATE_LIMIT_TAG} — bỏ qua, không gửi thêm"


class RateLimitGuard:
    """Đếm lỗi mạng/rate-limit liên tiếp trong một lần chạy CID."""

    def __init__(self, threshold: int = 20) -> None:
        self.threshold = max(1, int(threshold))
        self._lock = threading.Lock()
        self._streak = 0
        self._tripped = False

    @property
    def tripped(self) -> bool:
        with self._lock:
            return self._tripped

    def success(self) -> None:
        """Một request thật sự thành công -> chuỗi lỗi hiện tại chấm dứt."""
        with self._lock:
            self._streak = 0

    def failure(self, code: int) -> bool:
        """Ghi nhận một lỗi. Trả True nếu lần này vừa chạm ngưỡng.

        Chỉ lỗi mạng (mã âm) hoặc mã TikTok liên quan IP mới được đếm.
        Lỗi nghiệp vụ (CID sai, cookie hết hạn, đã thả tim rồi…) không
        làm dừng cả lô.
        """
        if code >= 0 and code not in IP_BLOCK_CODES:
            return False
        with self._lock:
            if self._tripped:
                return False
            self._streak += 1
            if self._streak >= self.threshold:
                self._tripped = True
                return True
        return False

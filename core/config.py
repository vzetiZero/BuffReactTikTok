"""Cấu hình cho 1 lần chạy."""

from __future__ import annotations

from dataclasses import dataclass, field

# --- chế độ tác vụ ---
MODE_LIKE_CID = "like_cid"      # thả tim 1 cid cho sẵn (nhanh nhất)
MODE_FIND_LIKE = "find_like"    # tự tìm reply theo từ khoá rồi thả tim
MODE_REPLY_CID = "reply_cid"    # trả lời 1 cid cho sẵn
MODE_CHECK = "check"            # chỉ kiểm tra cookie

MODE_LABELS = {
    MODE_LIKE_CID: "Thả tim theo CID (nhanh nhất)",
    MODE_FIND_LIKE: "Tìm reply theo từ khoá rồi thả tim",
    MODE_REPLY_CID: "Trả lời bình luận theo CID",
    MODE_CHECK: "Chỉ kiểm tra đăng nhập",
}


@dataclass(slots=True)
class RunConfig:
    # --- đích ---
    mode: str = MODE_LIKE_CID
    cid: str = ""                 # 769047757775676167
    aweme_id: str = ""            # id bài viết (nên có, giúp xác minh)
    video: str = ""               # URL hoặc aweme_id (dùng cho chế độ tìm kiếm)
    comment: str = ""             # nội dung (cho chế độ trả lời)
    search_keyword: str = ""      # từ khoá lọc reply
    target_text: str = ""         # đoạn text bắt buộc có trong reply
    min_likes: int = 0
    max_likes: int = 0

    # --- hệ thống ---
    signer_url: str = "http://127.0.0.1:8080"
    region: str = "VN"
    timezone: str = "Asia/Bangkok"
    language: str = "en"          # để trống = tự đoán từ cookie (`store-country-code`)
    proxy: str = ""               # proxy chung, khi account chưa được gán proxy riêng
    use_proxy_pool: bool = True   # False = bỏ qua pool, dùng IP máy
    rotate_on_block: bool = True  # đổi proxy khi bị chặn IP
    concurrency: int = 10
    delay_min: float = 0.0
    delay_max: float = 0.0
    retries: int = 1
    verify: bool = True           # đọc lại comment để xác nhận số like
    timeout: float = 20.0
    extra: dict = field(default_factory=dict)

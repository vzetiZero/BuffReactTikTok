"""Đọc file `user|user|mail|pass|msToken|deviceId|mail2|cookie`."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .models import Account

# File mẫu có 8 trường, nhưng để an toàn ta chỉ cắt 7 lần:
# phần còn lại (field thứ 8 trở đi) là cookie — vì cookie có thể chứa ký tự lạ.
_FIELDS = (
    "username_id",
    "username",
    "email",
    "password",
    "ms_token",
    "device_id",
    "email_alias",
    "cookie",
)

_VIDEO_ID_RE = re.compile(r"/video/(\d+)")


def parse_cookie_string(raw: str) -> dict[str, str]:
    """'a=1; b=2' -> {'a': '1', 'b': '2'}"""
    out: dict[str, str] = {}
    for chunk in raw.split(";"):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        key, _, value = chunk.partition("=")
        out[key.strip()] = value.strip()
    return out


def _account_id(username: str, cookie: dict[str, str]) -> str:
    seed = cookie.get("sessionid_ss") or cookie.get("sessionid") or username
    return hashlib.sha1(seed.encode("utf-8", "ignore")).hexdigest()[:10]


def parse_line(line: str, line_no: int) -> Account | None:
    line = line.strip().lstrip("\ufeff")
    if not line or line.startswith("#"):
        return None

    parts = line.split("|", len(_FIELDS) - 1)
    if len(parts) < 8:
        return None

    # Một số biến thể file bỏ trường đầu tiên, thử lùi 1 bước
    if "=" not in parts[-1]:
        parts = parts[1:]
        if len(parts) < 8:
            return None

    username = parts[1].strip()
    email = parts[2].strip()
    cookie = parse_cookie_string(parts[7])

    return Account(
        id=_account_id(username, cookie),
        username=username or email,
        email=email,
        password=parts[3].strip(),
        ms_token=parts[4].strip(),
        device_id=parts[5].strip(),
        cookie=cookie,
        raw=line,
    )


def load_accounts(path: str | Path) -> list[Account]:
    """Đọc toàn bộ file, bỏ dòng hỏng, tự sinh id nếu trùng."""
    path = Path(path)
    accounts: list[Account] = []
    seen: set[str] = set()

    text = path.read_text(encoding="utf-8", errors="replace")
    for line_no, line in enumerate(text.splitlines(), 1):
        acc = parse_line(line, line_no)
        if acc is None:
            continue
        if acc.id in seen:  # trùng cookie -> thêm hậu tố
            acc.id = f"{acc.id}{len(accounts):x}"
        seen.add(acc.id)
        accounts.append(acc)

    return accounts


def extract_aweme_id(video_url_or_id: str) -> str:
    """Lấy aweme_id từ URL video hoặc truyền thẳng id."""
    value = (video_url_or_id or "").strip()
    if value.isdigit():
        return value
    m = _VIDEO_ID_RE.search(value)
    if m:
        return m.group(1)
    # URL dạng ngắn: tiktok.com/t/ZTxxxx
    m = re.search(r"/t/([A-Za-z0-9]+)", value)
    if m:
        return m.group(1)
    return ""


def video_url(url_or_id: str) -> str:
    """Trả về URL tuyệt đối để Playwright mở."""
    value = (url_or_id or "").strip()
    if not value:
        return ""
    if value.isdigit():
        return f"https://www.tiktok.com/@/video/{value}"
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    return value

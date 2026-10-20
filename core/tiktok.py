"""Client API web của TikTok cho 1 tài khoản — qua curl_cffi (giả TLS Chrome).

Ba điều kiện để request không bị chặn:
  1. TLS fingerprint phải giống Chrome thật  -> dùng `curl_cffi` + `impersonate`.
  2. URL phải có chữ ký                    -> nhờ `Signer` (X-Bogus/X-Gnarly).
  3. Cookie phải khớp phiên                 -> cookie lấy từ file của bạn.

Không thỏa cả 3 thì TikTok trả `status_code` khác 0 hoặc HTML captcha.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import threading
import time
import urllib.parse
from typing import Any

from curl_cffi import requests as cf

from .inflight import HTTP, REST, SIGN, tracker
from .models import Account
from .proxy import proxy_url
from .signer import Signer, SignerError

# Endpoint (để ở đây để dễ đổi nếu TikTok đổi path)
EP_USER_DETAIL = "/api/user/detail/"
EP_COMMENT_LIST = "/api/comment/list/"
EP_COMMENT_REPLY = "/api/comment/list/reply/"
EP_COMMENT_DIGG = "/api/comment/digg/"          # <-- thả tim 1 comment (cid trong query)
EP_COMMENT_PUBLISH = "/api/comment/item/comment/publish/"
EP_COMMENT_PUBLISH_ASYNC = "/api/comment/item/comment/publish/async/"
EP_COMMENT_SEARCH = "/api/comment/search/item/"  # tùy chọn, có thể TikTok đã bỏ

# Mã lỗi TikTok hay gặp
ERR_MEANING = {
    0: "OK",
    3: "đường dẫn API sai",
    5: "thông số không hợp lệ (thiếu cid, sai kiểu digg_type…)",
    8: "bị giới hạn tần suất (rate limit)",
    2055: "bình luận không tồn tại — CID sai hoặc comment đã bị xoá",
    10202: "bị chặn bot / cần xác minh",
    10221: "bị chặn bot / cần xác minh",
    10222: "IP bị chặn",
    200001: "nội dung không hợp lệ",
    200002: "bình luận bị chặn (spam)",
    200004: "video không tồn tại",
    200005: "bình luận không tồn tại",
    200013: "chưa đăng nhập / phiên hết hạn",
    200016: "không thể bấm tim",
    200034: "đã bấm tim rồi",
    200015: "đã bình luận rồi",
    350002: "bạn đã bình luận quá nhiều",
}

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


# --------------------------------------------------------------------------- #
# Định vị comment — dùng CHUNG cho mọi account
# --------------------------------------------------------------------------- #
#
# Bối cảnh (vì sao phải có):
#
#   Xác minh thả tim cần biết 1 cid nằm ở đâu trong cây bình luận.
#   - Bình luận GỐC: đọc `/api/comment/list/` là xong -> 1 request.
#   - REPLY: phải biết cid CHA của nó, mà muốn biết thì phải quét từng
#     bình luận cha, mỗi cha 1 request `/api/comment/list/reply/`.
#     Một video có 20 bình luận có reply là 20 request cho MỘT lần xác minh.
#
#   Trước đây mỗi account tự quét lại từ đầu. 700 account cùng thả tim 1
#   reply = 700 × 20 = 14.000 request đi ra cùng 1 IP → TikTok chặn IP,
#   và account nào cũng không thả tim được (đúng triệu chứng: thả tim cho
#   comment gốc được, thả tim cho reply thì không tăng).
#
#   Nay: CHỈ 1 luồng quét thật, các luồng khác chờ rồi dùng kết quả.
#   Sau lần quét đầu, mỗi account chỉ còn 1 request xác minh.


class CommentLocator:
    """Nhớ vị trí của 1 cid trong cây bình luận, và chỉ cho quét 1 lần.

    Vị trí ghi dạng ("kind", "where"):
      ("top",   "<cursor>", "")  — bình luận gốc, nằm ở trang `cursor`
      ("reply", "<cid cha>", "<cursor trang reply>") — reply của bình luận cha
    """

    # Không tìm thấy thì nhớ "không có" một lúc lâu, để 700 account không
    # cùng quét lại 1 cid vô ích. Hết hạn thì cho quét lại (có thể lúc nãy
    # bình luận chưa hiện, giờ hiện rồi).
    MISS_TTL = 300.0

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: dict[tuple[str, str], tuple[str, str]] = {}
        self._locks: dict[tuple[str, str], threading.Lock] = {}
        self._miss: dict[tuple[str, str], float] = {}
        # tìm theo từ khoá -> cid (dùng cho chế độ "tìm reply theo từ khoá")
        self._search_hits: dict[tuple[str, str], str] = {}
        self._search_locks: dict[tuple[str, str], threading.Lock] = {}
        self._search_miss: dict[tuple[str, str], float] = {}

    # ------------------------------------------------------------------ #
    def resolve(self, aweme_id: str, cid: str, scan):
        """Trả vị trí của cid. `scan()` chỉ được gọi 1 lần cho mỗi cid.

        `scan()` trả ("kind", "where") hoặc None nếu không tìm thấy.
        """
        key = (str(aweme_id), str(cid))
        with self._lock:
            hit = self._hits.get(key)
            if hit is not None:
                return hit
            ts = self._miss.get(key)
            if ts is not None and (time.time() - ts) < self.MISS_TTL:
                return None
            lk = self._locks.setdefault(key, threading.Lock())
        with lk:
            with self._lock:
                hit = self._hits.get(key)
                if hit is not None:
                    return hit
                ts = self._miss.get(key)
                if ts is not None and (time.time() - ts) < self.MISS_TTL:
                    return None
            hit = scan()
            with self._lock:
                if hit is None:
                    self._miss[key] = time.time()
                else:
                    self._hits[key] = hit
            return hit

    def remember(self, aweme_id: str, cid: str, kind: str, where: str,
                 sub: str = "") -> None:
        """Ghi vị trí biết trước (dùng khi vừa quét xong)."""
        with self._lock:
            self._hits[(str(aweme_id), str(cid))] = (kind, str(where), str(sub))

    # ------------------------------------------------------------------ #
    def resolve_search(self, aweme_id: str, needle: str, scan) -> str:
        """Trả cid tìm được theo từ khoá. `scan()` chỉ chạy 1 lần."""
        key = (str(aweme_id), needle.strip().lower())
        with self._lock:
            hit = self._search_hits.get(key)
            if hit is not None:
                return hit
            ts = self._search_miss.get(key)
            if ts is not None and (time.time() - ts) < self.MISS_TTL:
                return ""
            lk = self._search_locks.setdefault(key, threading.Lock())
        with lk:
            with self._lock:
                hit = self._search_hits.get(key)
                if hit is not None:
                    return hit
                ts = self._search_miss.get(key)
                if ts is not None and (time.time() - ts) < self.MISS_TTL:
                    return ""
            cid = scan() or ""
            with self._lock:
                if cid:
                    self._search_hits[key] = cid
                else:
                    self._search_miss[key] = time.time()
            return cid


# Một bộ định vị cho CẢ ứng dụng (mọi account dùng chung).
LOCATOR = CommentLocator()

# Nhận dạng nền tảng, suy ra từ User-Agent của sidecar.
PLATFORMS = {
    "windows": ("windows", "Win32", "Windows NT 10.0; Win64; x64",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"),
    "mac": ("mac", "MacIntel", "Macintosh; Intel Mac OS X 10_15_7",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"),
}
_CHROME_RE = re.compile(r"Chrome/(\d+)")


def _chrome_version(ua: str) -> str:
    """Số hiệu Chrome trong UA — phải khớp `browser_version`."""
    m = _CHROME_RE.search(ua or "")
    return m.group(1) if m else "131.0.0.0"


def _os_family(ua: str) -> str:
    if "Windows" in ua:
        return "windows"
    if "Macintosh" in ua or "Mac OS" in ua:
        return "mac"
    if "Linux" in ua:
        return "linux"
    return "windows"


def _numeric_id(value: str) -> str:
    """Chỉ nhận ID dạng số bão hòa 15-25 chữ số; UUID bị loại."""
    v = urllib.parse.unquote((value or "")).strip()
    return v if v.isdigit() and 15 <= len(v) <= 25 else ""


def _derive_snowflake(seed: str) -> str:
    """Sinh một số 19 chữ số ỔN ĐỊNH từ seed (sessionid của account).

    Vì sao cần: `device_id` trên web là số bão hòa, nhưng file cookie hay lưu
    UUID ở cột `device_id`. Thiếu `device_id` (hoặc gửi UUID) thì TikTok trả
    HTTP 200 với BODY RỖNG — lỗi rất khó đoán vì không có mã lỗi nào.
    Sinh theo seed nên account nào cũng giữ nguyên ID qua các lần chạy, tránh
    bị coi là thiết bị mới mỗi lần.
    """
    h = hashlib.sha1(f"device|{seed}".encode()).hexdigest()
    return str(int(h[:15], 16) % 9_000_000_000_000_000 + 7_000_000_000_000_000_000)


def _impersonate_for(ua: str) -> str:
    """Chọn profile TLS của curl_cffi khớp với UA của sidecar.

    Rất quan trọng: sidecar ký bằng browser của chính nó (Safari/macOS theo
    mặc định). Nếu ta gửi UA Safari nhưng TLS lại là Chrome thì TikTok thấy
    ngay sự lệch và trả 200 với BODY RỖNG. Phải khớp cả hai.
    """
    u = ua or ""
    if "Chrome" in u or "Chromium" in u or "Edg/" in u:
        return "chrome"
    if "Firefox" in u:
        return "firefox"
    if "Safari" in u:
        return "safari"
    return "chrome"


def _has_replies(comment: dict) -> bool:
    """Bình luận này còn reply con hay không."""
    try:
        return int(comment.get("reply_comment_total") or 0) > 0
    except (TypeError, ValueError):
        return False


def _normalize_locale(value: str) -> tuple[str, str]:
    """'vi-VN' -> (ngôn ngữ dùng trong tham số, đường dẫn locale trên web)."""
    v = (value or "").strip() or "en-US"
    if v.lower() in ("en", "en-us", "en_us"):
        return "en", "en"
    if v.lower() == "vi-vn":
        return "vi-VN", "vi-VN"
    if "-" in v:
        return v, v
    return v, v


class TikTokError(RuntimeError):
    def __init__(self, message: str, code: int = -1, raw: Any = None):
        super().__init__(message)
        self.code = code
        self.raw = raw


def _code_of(js: dict) -> int:
    """Lấy mã lỗi của TikTok, chấp nhận CẢ hai kiểu tên.

    TikTok trả song song `status_code: 0` (luôn 0) và `statusCode: 10221`
    (mã thật). Chỉ đọc `status_code` sẽ tưởng mọi thứ thành công trong khi thực
    tế đã bị chặn — đây là bẫy rất dễ mắc.
    """
    for key in ("statusCode", "status_code"):
        v = js.get(key)
        if isinstance(v, int) and v != 0:
            return v
    v = js.get("status_code")
    return v if isinstance(v, int) else -1


def explain(code: int, msg: str = "") -> str:
    base = ERR_MEANING.get(code, "")
    return f"{base or 'lỗi không xác định'}" + (f" ({msg})" if msg else "")


class TikTokClient:
    """MỘT instance = MỘT tài khoản. Không chia sẻ giữa các thread."""

    def __init__(self, account: Account, signer: Signer, region: str = "VN",
                 timezone: str = "Asia/Bangkok", proxy: str = "",
                 timeout: float = 20.0, language: str = "en",
                 referer: str = ""):
        self.account = account
        self.signer = signer
        self.region = region
        self.timezone = timezone
        self.timeout = timeout
        self._ua = DEFAULT_UA
        self._lock = threading.RLock()
        self.language = language
        # Trang đang mở khi bấm like. Request thật gửi cả query `referer` và
        # header `Referer` bằng URL video, không phải trang chủ.
        self.referer = referer.strip()
        self.os, self.platform, self.platform_desc, _ = PLATFORMS["windows"]
        self.locale_path = "en"

        c = account.cookie
        # `verifyFp` chính là cookie `s_v_web_id` (dạng verify_xxx_yyy…)
        self.verify_fp = c.get("s_v_web_id", "")
        self.ms_token = account.ms_token or c.get("msToken", "")

        # `device_id` và `odinId` trên web là SỐ BÃO HÒA 19 chữ số. File cookie
        # hay lưu UUID ở cột `device_id`; gửi UUID (hay thiếu hẳn) thì TikTok
        # trả HTTP 200 với BODY RỖNG, không có mã lỗi để đoán. Nên: dùng số nếu
        # có, không thì suy ra ổn định từ sessionid.
        seed = c.get("sessionid_ss") or c.get("sessionid") or account.id
        self.device_id = (
            _numeric_id(account.device_id)
            or _numeric_id(c.get("device_id", ""))
            or _derive_snowflake(seed)
        )
        # `odin_tt` là hash hex chứ không phải odinId -> không dùng được
        self.odin_id = _numeric_id(c.get("odinId", ""))
        if not self.odin_id:
            self.odin_id = _derive_snowflake("odin|" + seed)

        # Ngôn ngữ: ưu tiên cấu hình, không thì đoán từ cookie
        if not language or language == "en":
            lang = self._locale_from_cookie(c) or language
            self.language, self.locale_path = _normalize_locale(lang)

        self._sess = None                  # tạo LƯỜI, sau khi biết UA
        self._impersonate = ""
        self._proxies = None
        if proxy:
            # PHẢI chuẩn hoá qua proxy_url(): chuỗi "IP:port:user:pass"
            # (kiểu VPN Express) đưa thẳng vào curl sẽ lỗi "Unsupported
            # proxy syntax" và mọi request đều chết.
            p = proxy_url(proxy)
            if p:
                self._proxies = {"http": p, "https": p}
        self._sync_fingerprint()
        self._ensure_session()

    # ------------------------------------------------------------------ #
    @property
    def sess(self):
        """Session HTTP — tự tạo lần đầu và tự tạo lại nếu UA đổi."""
        return self._ensure_session()

    def _ensure_session(self):
        want = _impersonate_for(self._ua)
        if self._sess is not None and want == self._impersonate:
            return self._sess
        if self._sess is not None:
            try:
                self._sess.close()
            except Exception:
                pass
        self._impersonate = want
        self._sess = cf.Session(
            impersonate=want,
            proxies=self._proxies,
            verify=False,
        )
        self._load_cookies()
        return self._sess

    @staticmethod
    def _locale_from_cookie(c: dict[str, str]) -> str:
        """Cookie `store-country-code` cho biết tài khoản ở nước nào."""
        cc = (c.get("store-country-code") or "").lower()
        return {"vn": "vi-VN", "us": "en-US", "id": "id-ID",
                "ph": "en-US", "th": "th-TH"}.get(cc, "")

    def _load_cookies(self) -> None:
        s = self._sess
        if s is None:
            return
        s.cookies.set("msToken", self.ms_token, domain=".tiktok.com", path="/")
        for name, value in self.account.cookie.items():
            if name == "msToken":
                continue
            s.cookies.set(name, value, domain=".tiktok.com", path="/")

    def _sync_fingerprint(self) -> None:
        """Lấy fingerprint đã biết của sidecar (nếu có) để lần đầu khỏi lệch."""
        self._adopt_navigator(self.signer.navigator())

    def _adopt_navigator(self, nav: dict) -> None:
        """Áp fingerprint của sidecar: UA + hệ điều hành suy từ UA đó.

        `os`, `browser_platform`, `browser_version` phải cùng nhánh với UA,
        nếu không TikTok thấy ngay sự lệch (Ví dụ UA Mac nhưng os=windows).
        """
        if not nav:
            return
        ua = nav.get("user_agent") or ""
        if ua:
            self._ua = ua
        family = _os_family(self._ua)
        if family in PLATFORMS:
            self.os, self.platform, self.platform_desc, _ = PLATFORMS[family]
        # Ngôn ngữ: giữ vi-VN nếu cookie là tài khoản VN, kể cả khi sidecar
        # (chạy trên máy khác) báo en-US.
        if not self.verify_fp and nav.get("browser_language"):
            self.language, self.locale_path = _normalize_locale(
                nav["browser_language"]
            )
        # Sidecar có thể đổi UA sau khi refresh phiên (30 phút) -> session
        # phải dựng lại cho khớp, nếu không lại thành 200 + body rỗng.
        if self._sess is not None:
            self._ensure_session()
    @property
    def csrf(self) -> str:
        return self.account.cookie.get("tt_csrf_token", "")

    # ------------------------------------------------------------------ #
    def base_params(self, extra: dict | None = None) -> dict[str, str]:
        """Bộ tham số fingerprint — đối chiếu với request thật của trình duyệt.

        Bốn điều TikTok kiểm tra, thiếu một là fail:
          1. `os` + `browser_platform` phải khớp UA (windows ⇔ Win32)
          2. `browser_version` phải khớp UA (Chrome/150, Safari/18.6, …)
          3. `tz_name` + `region` phải khớp cookie (`store-country-code`, `store-idc`)
          4. Ngôn ngữ (`app_language`, `language`, `webcast_language`) phải đồng bộ
             với `browser_language` — dùng `vi-VN` nếu cookie là tài khoản VN.
        """
        nav = self.signer.navigator()
        ua = self._ua
        # `browser_version` trong request thật chính là UA bỏ tiền tố
        # "Mozilla/". Với Chrome thì trùng công thức cũ; với Safari (sidecar
        # mặc định) công thức Chrome/131 là SAI hoàn toàn.
        browser_version = ua.replace("Mozilla/", "", 1) if ua else ""
        if not browser_version:
            browser_version = (
                f"5.0 ({self.platform_desc}) AppleWebKit/537.36 "
                f"(KHTML, like Gecko) Chrome/{_chrome_version(ua)} Safari/537.36"
            )
        referer = self.referer or f"https://www.tiktok.com/{self.locale_path}/"
        p = {
            "aid": "1988",
            "app_language": self.language,
            "app_name": "tiktok_web",
            "browser_language": self.language,
            "browser_name": "Mozilla",
            "browser_online": "true",
            "browser_platform": self.platform,
            "browser_version": browser_version,
            "channel": "tiktok_web",
            "channel_id": "0",
            "cookie_enabled": "true",
            "data_collection_enabled": "true",
            "device_platform": "web_pc",
            "focus_state": "true",
            "from_page": "video",
            "history_len": "7",
            "is_fullscreen": "false",
            "is_page_visible": "true",
            "os": self.os,
            "priority_region": self.region,
            "referer": referer,
            "root_referer": "https://www.google.com/",
            "region": self.region,
            "screen_height": nav.get("screen_height", "1080"),
            "screen_width": nav.get("screen_width", "1920"),
            "tz_name": self.timezone,
            "user_is_login": "true",
            "webcast_language": self.language,
            "WebIdLastTime": str(int(time.time()) - random.randint(60, 4000)),
        }
        if self.device_id:
            p["device_id"] = self.device_id
        if self.odin_id:
            p["odinId"] = self.odin_id
        if self.verify_fp:
            p["verifyFp"] = self.verify_fp
        if self.ms_token:
            p["msToken"] = self.ms_token
        if extra:
            p.update({k: str(v) for k, v in extra.items() if v is not None})
        return p

    def _headers(self) -> dict[str, str]:
        lang = self.language or "en"
        base_lang = lang.split("-")[0]
        referer = self.referer or f"https://www.tiktok.com/{self.locale_path}/"
        h = {
            "User-Agent": self._ua,
            "Accept": "*/*",
            # Request thật của Chrome 150 có danh sách ngôn ngữ đầy đủ hơn
            # `vi-VN,en;q=0.9`; giữ đúng thứ tự ưu tiên của tài khoản.
            "Accept-Language": f"{lang},{base_lang};q=0.9,en-US;q=0.8,en;q=0.7",
            # Referer là chính trang video đang mở, không phải trang chủ.
            "Referer": referer,
            "Origin": "https://www.tiktok.com",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }
        # Client Hints: Chrome gửi kèm; Safari thì không. Phải khớp UA.
        if "Chrome/" in self._ua or "Chromium/" in self._ua:
            m = re.search(r"(?:Chrome|Chromium)/(\d+)", self._ua)
            if m:
                ver = m.group(1)
                brands = f'"Not;A=Brand";v="8", "Chromium";v="{ver}"'
                if "Chrome/" in self._ua:
                    brands += f', "Google Chrome";v="{ver}"'
                h["sec-ch-ua"] = brands
                h["sec-ch-ua-mobile"] = "?0"
                if "Windows" in self._ua:
                    h["sec-ch-ua-platform"] = '"Windows"'
                elif "Macintosh" in self._ua:
                    h["sec-ch-ua-platform"] = '"macOS"'
                else:
                    h["sec-ch-ua-platform"] = '"Linux"'
        if self.csrf:
            # tên header đúng TikTok dùng: `tt-csrf-token` (không phải x-csrf-token)
            h["tt-csrf-token"] = self.csrf
        return h

    # ------------------------------------------------------------------ #
    def _request(self, method: str, path: str, params: dict, body: dict | None,
                 retries: int = 2) -> dict:
        query = urllib.parse.urlencode(
            self.base_params(params), quote_via=urllib.parse.quote
        )
        raw_url = f"https://www.tiktok.com{path}?{query}"
        payload = json.dumps(body, separators=(",", ":")) if body is not None else ""
        data = payload.encode() if payload else None
        # Request like thật là POST với body rỗng nhưng vẫn có
        # `Content-Type: application/x-www-form-urlencoded` và Content-Length 0.
        # curl_cffi chỉ gửi Content-Length 0 khi data là bytes rỗng.
        empty_post = method.upper() == "POST" and data is None
        if empty_post:
            data = b""

        last: Exception | None = None
        for attempt in range(retries + 1):
            try:
                # hai bước này là hai nút thắt khác nhau, tách riêng để
                # đồng hồ "đang chờ" nói đúng: chờ KÝ hay chờ TIKTOK.
                tok = tracker.enter(SIGN)
                try:
                    signed = self.signer.sign(raw_url)
                finally:
                    tracker.leave(tok)
                url = signed["signed_url"]
                # PHẢI đồng bộ fingerprint TRƯỚC khi gửi: chữ ký vừa được
                # tạo bằng User-Agent của chính sidecar, nên request cũng phải
                # mang đúng UA đó. Lệch một ký tự là TikTok từ chối.
                self._adopt_navigator(signed.get("navigator") or {})
                headers = self._headers()
                if empty_post:
                    headers["Content-Type"] = "application/x-www-form-urlencoded"
                elif data is not None:
                    headers["Content-Type"] = "application/json"

                tok = tracker.enter(HTTP)
                try:
                    resp = self.sess.request(
                        method.upper(), url,
                        data=data, headers=headers, timeout=self.timeout,
                    )
                finally:
                    tracker.leave(tok)

                # sidecar có thể trả cookie/msToken mới -> đồng bộ lại
                self._absorb(signed)

                if resp.status_code == 429:
                    # Mã 8 = rate limit. Không thử lại ngay trong _request:
                    # để tầng AccountTask đổi proxy (nếu có) rồi thử lại.
                    raise TikTokError("HTTP 429 (rate limit)", 8)
                if resp.status_code >= 500:
                    raise TikTokError(f"HTTP {resp.status_code}", -resp.status_code)

                try:
                    js = resp.json()
                except ValueError:
                    txt = resp.text[:200]
                    if "captcha" in txt.lower() or "verify" in txt.lower():
                        raise TikTokError("bị chặn captcha/verify", 10202)
                    if not txt.strip():
                        # TikTok trả 200 + body rỗng khi IP bị chặn/rate
                        # limit. Đây là tín hiệu rất hay gặp khi chạy nhiều
                        # account cùng một IP; báo rõ thay vì "không phải
                        # JSON: " (log cũ trống trơn, rất khó hiểu).
                        raise TikTokError(
                            "TikTok trả body rỗng — thường do IP bị chặn/"
                            "rate limit", 8, "",
                        )
                    raise TikTokError(f"phản hồi không phải JSON: {txt}", -1, resp.text[:400])

                code = _code_of(js)
                return js

            except (SignerError, TikTokError) as e:
                last = e
                if isinstance(e, SignerError):
                    break  # sidecar hỏng thì thử lại cũng vô ích
                if e.code in (8, 10202):
                    # Rate limit / captcha: thử lại ngay trên cùng IP/session
                    # gần như chắc chắn vẫn hỏng, còn làm request nặng thêm.
                    # Để AccountTask đổi proxy (nếu có) rồi thử lại.
                    break
                if attempt < retries:
                    # nghỉ trước khi thử lại — cũng phải báo lên đồng hồ,
                    # nếu không người dùng thấy "đứng im" mà không biết vì sao
                    tok = tracker.enter(REST)
                    try:
                        time.sleep(0.6 * (attempt + 1) + random.random() * 0.3)
                    finally:
                        tracker.leave(tok)
        raise last or TikTokError("thất bại không rõ lý do")

    def _absorb(self, signed: dict) -> None:
        """Nạp cookie mà sidecar trả về (ttwid, msToken, csrftoken…)."""
        raw = signed.get("cookies") or ""
        if not isinstance(raw, str):
            return
        for item in raw.split(";"):
            item = item.strip()
            if not item or "=" not in item:
                continue
            name, _, val = item.partition("=")
            name, val = name.strip(), val.strip()
            if not name or not val:
                continue
            self.sess.cookies.set(name, val, domain=".tiktok.com", path="/")
            if name == "msToken" and val != self.ms_token:
                with self._lock:
                    self.ms_token = val
            if name == "tt_csrf_token":
                self.account.cookie["tt_csrf_token"] = val

    # ------------------------------------------------------------------ #
    # API cụ thể
    # ------------------------------------------------------------------ #
    def user_detail(self, unique_id: str) -> dict:
        """Kiểm tra cookie có đăng nhập được không. Trả về userInfo."""
        r = self._request("GET", EP_USER_DETAIL, {"uniqueId": unique_id}, None)
        code = _code_of(r)
        if code != 0:
            raise TikTokError(
                f"{explain(code, r.get('status_msg', ''))} (code {code})", code, r
            )
        info = (r.get("data") or {}).get("userInfo") or r.get("userInfo") or {}
        if not info.get("user"):
            raise TikTokError(
                "TikTok trả về nhưng không có dữ liệu người dùng — có thể "
                "tài khoản bị chặn bot hoặc cookie đã hết hạn",
                code or 10221, r,
            )
        return info["user"]

    def comment_list(self, aweme_id: str, cursor: int = 0, count: int = 20) -> dict:
        r = self._request(
            "GET", EP_COMMENT_LIST,
            {"aweme_id": aweme_id, "cursor": cursor, "count": count, "item_type": 0},
            None,
        )
        # TikTok trả `comments` NGAY Ở CẤP NGOÀI (cùng status_code, cursor,
        # has_more), không bọc trong `data`. Code cũ chỉ lấy `r["data"]` nên
        # luôn nhận {} và mọi bước verify đọc số like đều thất bại. Vẫn giữ
        # nhánh `data` để tương thích nếu TikTok đổi cấu trúc.
        return r.get("data") or r

    def comment_replies(self, aweme_id: str, comment_id: str, cursor: int = 0,
                        count: int = 20) -> dict:
        r = self._request(
            "GET", EP_COMMENT_REPLY,
            # Endpoint này nhận `comment_id`, KHÔNG phải `item_id`. Gửi sai
            # tên -> TikTok trả status_code=5 (thông số không hợp lệ).
            {"aweme_id": aweme_id, "comment_id": comment_id, "cursor": cursor,
             "count": count, "item_type": 0},
            None,
        )
        return r.get("data") or r

    def digg_comment(self, aweme_id: str, comment_id: str, digg: bool = True) -> dict:
        """Thả tim / bỏ tim 1 bình luận.

        `POST /api/comment/digg/` — `cid` nằm ở QUERY STRING, `digg_type`:
        1 = thả tim, 0 = bỏ tim. Không gửi body (request thật cũng vậy).

        `aweme_id` là TUỲ CHỌN. Khi trống, tham số bị LOAI KHỎI query chứ
        không gửi `aweme_id=` rỗng — TikTok coi chuỗi rỗng là giá trị sai
        và từ chối request. Nhờ vậy chạy được khi người dùng chỉ có `cid`.

        Không thêm tham số lạ, vì chữ ký băm cả query string.
        """
        params = {
            "cid": str(comment_id),
            "digg_type": 1 if digg else 0,
        }
        if aweme_id:
            params["aweme_id"] = str(aweme_id)
        return self._request("POST", EP_COMMENT_DIGG, params, None)

    def like_cid(self, comment_id: str, aweme_id: str = "") -> dict:
        """Luồng rút gọn: chỉ cần cid (và aweme_id nếu có)."""
        return self.digg_comment(aweme_id, comment_id, digg=True)

    def find_comment(self, aweme_id: str, comment_id: str,
                     max_pages: int = 2, only_replies: bool = True) -> dict | None:
        """Định vị 1 cid trong bình luận, để đọc `digg_count` xác minh.

        Dùng chung bộ định vị (`LOCATOR`) nên lần đầu phải quét, còn các
        account sau chỉ tốn 1 request. Xem `CommentLocator` để hiểu vì sao
        phải chia sẻ kết quả quét giữa các account.
        """
        return self.comment_state(aweme_id, comment_id, max_pages)

    # ------------------------------------------------------------------ #
    def _scan_for_cid(self, aweme_id: str, cid: str,
                      max_pages: int = 2) -> tuple[dict | None,
                                                 tuple[str, str, str] | None]:
        """Quét cây bình luận tìm cid — chỉ chạy 1 lần cho mỗi cid.

        Trả (item, vị trí). Vị trí = ("top", "<cursor>", "") nếu cid là bình
        luận gốc, ("reply", "<cid cha>", "<cursor trang reply>") nếu là reply.
        """
        target = str(cid)
        cursor = 0
        for _ in range(max_pages):
            data = self.comment_list(aweme_id, cursor=cursor, count=50)
            items = data.get("comments") or []
            for c in items:
                if str(c.get("cid")) == target:
                    return c, ("top", str(cursor), "")
                # TikTok trả kèm vài reply đầu của mỗi bình luận ngay
                # trong payload -> thấy là khỏi gọi thêm request.
                for rep in c.get("reply_comment") or []:
                    if str(rep.get("cid")) == target:
                        return rep, ("reply", str(c.get("cid")), "0")
            for c in items:
                if not _has_replies(c):
                    continue
                rep, rep_cursor = self._find_in_replies(
                    aweme_id, str(c.get("cid")), target)
                if rep is not None:
                    return rep, ("reply", str(c.get("cid")), str(rep_cursor))
            if not data.get("has_more") or not items:
                break
            cursor = data.get("cursor", cursor + len(items))
        return None, None

    def _find_in_replies(self, aweme_id: str, parent_cid: str, target: str,
                         max_reply_pages: int = 4) -> tuple[dict | None, int]:
        """Quét các trang reply của 1 bình luận cha.

        Một bình luận có thể có hàng trăm reply (chia nhiều trang). Reply
        nằm ở trang 2 trở đi sẽ không thấy nếu chỉ đọc trang đầu.
        """
        cursor = 0
        for _ in range(max_reply_pages):
            try:
                data = self.comment_replies(aweme_id, parent_cid, cursor, 50)
            except TikTokError:
                return None, cursor
            reps = data.get("comments") or []
            for rep in reps:
                if str(rep.get("cid")) == target:
                    return rep, cursor
            if not data.get("has_more") or not reps:
                break
            cursor = data.get("cursor", cursor + len(reps))
        return None, cursor

    def comment_state(self, aweme_id: str, comment_id: str,
                      max_pages: int = 2, fresh: bool = False) -> dict | None:
        """Đọc trạng thái 1 cid (`user_digged` + `digg_count`) — RẺ nhất có thể.

        Lần đầu phải quét để biết cid nằm ở đâu; kết quả được nhớ dùng
        chung cho mọi account, nên từ account thứ 2 trở đi chỉ tốn ĐÚNG
        1 request. Trước đây mỗi account tự quét lại từ đầu, với reply
        là hàng chục request — đủ để TikTok chặn IP và không account nào
        thả tim được.

        `fresh=True`: đổi tham số `count` để URL khác đi. Nếu TikTok cache
        payload của `/api/comment/list/reply/` theo URL (mọi account dùng
        chung 1 URL vì cookie không nằm trong URL) thì đọc lại sẽ thấy
        trạng thái CŨ — `user_digged=0` dù tim đã lên.
        """
        scanned: dict = {}

        def scan():
            item, hit = self._scan_for_cid(aweme_id, comment_id, max_pages)
            if hit is not None:
                scanned["item"] = item
            return hit

        hit = LOCATOR.resolve(aweme_id, comment_id, scan)
        if hit is None:
            return None
        # Chính lượt này quét thì dùng luôn item tìm được (tiết kiệm 1
        # request); account sau thì đọc đúng chỗ đã biết (1 request).
        if "item" in scanned and not fresh:
            return scanned["item"]
        kind, where, sub = hit
        count = 50 + (1 if fresh else 0)
        try:
            if kind == "reply":
                data = self.comment_replies(aweme_id, where, int(sub or 0), count)
            else:
                data = self.comment_list(aweme_id, cursor=int(where), count=count)
        except TikTokError:
            return None
        for it in data.get("comments") or []:
            if str(it.get("cid")) == str(comment_id):
                return it
        return None
        # Chính lượt này quét thì dùng luôn item tìm được (tiết kiệm 1
        # request); account sau thì đọc đúng chỗ đã biết (1 request).
        if "item" in scanned:
            return scanned["item"]
        kind, where = hit
        try:
            if kind == "reply":
                data = self.comment_replies(aweme_id, where, 0, 50)
            else:
                data = self.comment_list(aweme_id, cursor=int(where), count=50)
        except TikTokError:
            return None
        for it in data.get("comments") or []:
            if str(it.get("cid")) == str(comment_id):
                return it
        return None

    def search_comment(self, aweme_id: str, needle: str,
                       max_pages: int = 4) -> dict | None:
        """Quét bình luận cấp 1 và các reply để tìm comment chứa `needle`.

        Kết quả tìm được nhớ dùng chung: mọi account đều tìm CÙNG một
        comment, quét lại 700 lần là tự tạo hàng nghìn request vô ích.
        """
        low = needle.strip().lower()
        cid = LOCATOR.resolve_search(
            aweme_id, low,
            lambda: self._scan_for_needle(aweme_id, low, max_pages),
        )
        if not cid:
            return None
        item = self.comment_state(aweme_id, cid, max_pages)
        return item if item else {"cid": cid}

    def _scan_for_needle(self, aweme_id: str, low: str,
                         max_pages: int = 4) -> str:
        """Quét tìm comment chứa `low`; trả cid + nhớ vị trí để đọc lại."""
        cursor = 0
        for _page in range(max_pages):
            data = self.comment_list(aweme_id, cursor=cursor, count=50)
            items = data.get("comments") or []
            for c in items:
                if low in (c.get("text") or "").lower():
                    LOCATOR.remember(aweme_id, str(c.get("cid")), "top",
                                     str(cursor), "")
                    return str(c.get("cid"))
                if not _has_replies(c):
                    continue
                try:
                    rdata = self.comment_replies(aweme_id, str(c.get("cid")),
                                                 0, 50)
                except TikTokError:
                    continue
                for rep in rdata.get("comments") or []:
                    if low in (rep.get("text") or "").lower():
                        LOCATOR.remember(aweme_id, str(rep.get("cid")),
                                         "reply", str(c.get("cid")), "0")
                        return str(rep.get("cid"))
            if not data.get("has_more") or not items:
                break
            cursor = data.get("cursor", cursor + len(items))
        return ""

    def publish_comment(self, aweme_id: str, text: str,
                        parent_cid: str = "") -> dict:
        body = {"aid": 1988, "aweme_id": str(aweme_id), "text": text, "type": 0}
        if parent_cid:
            body["comment_id"] = str(parent_cid)
        r = self._request("POST", EP_COMMENT_PUBLISH, {"aweme_id": aweme_id}, body)
        if r.get("status_code") == 0:
            return r
        # endpoint mới hơn
        r2 = self._request("POST", EP_COMMENT_PUBLISH_ASYNC,
                           {"aweme_id": aweme_id}, body)
        return r2 if r2.get("status_code") == 0 else r

    # ------------------------------------------------------------------ #
    def debug_url(self, path: str, params: dict, sign: bool = True) -> str:
        """Trả về URL đầy đủ (đã ký nếu `sign=True`) — để đối chiếu với DevTools."""
        query = urllib.parse.urlencode(
            self.base_params(params), quote_via=urllib.parse.quote
        )
        raw = f"https://www.tiktok.com{path}?{query}"
        if not sign:
            return raw
        return self.signer.sign(raw).get("signed_url", raw)

    def debug_headers(self) -> dict[str, str]:
        return self._headers()

    def close(self) -> None:
        try:
            self.sess.close()
        except Exception:
            pass

"""Backend HTTP: mỗi account 1 session curl_cffi riêng, chạy song song.

Một account = 1 thread của QThreadPool = 1 `TikTokClient`. Không có tài nguyên
dùng chung nào ngoài `Signer` (sidecar Node) -> tốc độ scale gần tuyến tính
theo số luồng.
"""

from __future__ import annotations

import random
import time

from ..config import (
    MODE_CHECK,
    MODE_FIND_LIKE,
    MODE_LIKE_CID,
    MODE_REPLY_CID,
    RunConfig,
)
from ..models import ST_DONE, ST_FAIL, ST_OK, Account, TaskResult
from ..parser import extract_aweme_id
from ..proxy import IP_BLOCK_CODES
from ..signer import Signer, SignerError
from ..tiktok import TikTokClient, TikTokError, _code_of, explain
from .base import Progress, StopFlag


class HttpBackend:
    name = "http"

    def __init__(self, pool=None, rotate_on_block: bool = True) -> None:
        self.signer = Signer()
        self.pool = pool
        self.rotate_on_block = rotate_on_block

    # ------------------------------------------------------------------ #
    def run(self, account: Account, cfg: RunConfig, stop: StopFlag,
            progress: Progress) -> TaskResult:
        aid = account.id
        if not account.has_session():
            return TaskResult(ST_FAIL, "cookie thiếu sessionid_ss/sid_tt")

        client = None
        try:
            # proxy riêng của account, không có thì dùng proxy chung
            proxy = "" if not cfg.use_proxy_pool else (account.proxy or cfg.proxy)
            progress(aid, f"Kết nối{' qua proxy' if proxy else ' (IP máy)'}...", 5)
            client = TikTokClient(
                account, self.signer,
                region=cfg.region, timezone=cfg.timezone,
                proxy=proxy, timeout=cfg.timeout,
                language=cfg.language or "en",
            )

            # --- 1. xác nhận đăng nhập ------------------------------- #
            # BƯỚC NÀY KHÔNG ĐƯỢC CHẶN LƯỚT CHẠY.
            # Đo thật: /api/user/detail/ bị TikTok trả 10221 (phát hiện bot)
            # trong khi /api/comment/digg/ vẫn trả status_code=0 bình thường.
            # Nếu để lỗi ở đây làm fail cả task thì không bao giờ thả tim
            # được, dù request thả tim hoàn toàn có thể chạy.
            # Vì vậy: lỗi ở bước kiểm tra -> ghi nhận và vẫn thử thả tim.
            # Lỗi ở chính thao tác thả tim mới là kết quả thật.
            nickname = account.username
            try:
                progress(aid, "Kiểm tra phiên đăng nhập...", 15)
                user = client.user_detail(account.username)
                nickname = user.get("nickname") or account.username
                progress(aid, f"Đăng nhập OK — {nickname}", 30)
            except TikTokError as e:
                progress(aid, f"Kiểm tra phiên bị từ chối ({e.code}) — "
                              f"vẫn thử thả tim", 22)
                if cfg.mode == MODE_CHECK:
                    # chế độ chỉ kiểm tra: không kiểm tra được thì báo thật
                    return TaskResult(
                        ST_FAIL, f"Kiểm tra phiên thất bại: {e}", code=e.code,
                    )

            if cfg.mode == MODE_CHECK:
                return TaskResult(ST_DONE, f"Cookie hợp lệ ({nickname})", ok=True)

            if stop.is_set():
                return TaskResult(ST_FAIL, "đã dừng")
            if cfg.delay_max > 0 and stop.wait(
                random.uniform(cfg.delay_min, cfg.delay_max)
            ):
                return TaskResult(ST_FAIL, "đã dừng")

            # --- 2. chạy tác vụ --------------------------------------- #
            if cfg.mode == MODE_LIKE_CID:
                return self._like_cid(aid, client, cfg, progress)
            if cfg.mode == MODE_REPLY_CID:
                return self._reply_cid(aid, client, cfg, progress)
            if cfg.mode == MODE_FIND_LIKE:
                return self._find_like(aid, client, cfg, progress)
            return TaskResult(ST_FAIL, f"chế độ lạ: {cfg.mode}")

        except SignerError as e:
            return TaskResult(ST_FAIL, f"sidecar ký lỗi: {str(e)[:140]}")
        except TikTokError as e:
            # bị chặn IP -> báo để tầng trên đổi proxy rồi thử lại
            if e.code in IP_BLOCK_CODES:
                return TaskResult(
                    ST_FAIL, f"BỊ CHẶN IP ({e.code}) — sẽ đổi proxy thử lại", code=e.code,
                )
            return TaskResult(ST_FAIL, f"{str(e)[:180]}", code=e.code)
        except Exception as e:
            return TaskResult(ST_FAIL, f"{type(e).__name__}: {str(e)[:180]}")
        finally:
            if client is not None:
                client.close()

    # ------------------------------------------------------------------ #
    # Chế độ 1: thả tim 1 cid cho sẵn — nhanh nhất (1 request)
    # ------------------------------------------------------------------ #
    def _like_cid(self, aid, client: TikTokClient, cfg: RunConfig,
                  progress: Progress) -> TaskResult:
        cid = cfg.cid.strip()
        if not cid.isdigit() or len(cid) < 10:
            return TaskResult(ST_FAIL, "CID phải là chuỗi số 18-19 ký tự")

        aweme = cfg.aweme_id.strip() or extract_aweme_id(cfg.video)
        progress(aid, f"Thả tim cid={cid}...", 60)

        before = self._digg_count(client, aweme, cid) if (cfg.verify and aweme) else None

        res = client.digg_comment(aweme, cid, digg=True)
        code = _code_of(res)

        if code == 0:
            note = f"♥ cid={cid}"
            like_after: int | None = None
            if cfg.verify and aweme:
                after = self._digg_count(client, aweme, cid)
                if before is not None and after is not None:
                    like_after = after
                    if after > before:
                        note += f" · like {before} → {after}"
                    elif after == before:
                        note += f" · đã thả tim trước đó (like={after})"
                    else:
                        note += f" · ⚠ chưa thấy tăng (like={after})"
                else:
                    note += " · không đọc lại được số like"
            else:
                note += " · API trả status_code=0"
            progress(aid, note, 100)
            return TaskResult(ST_OK, note, comment_id=cid, found=True, ok=True,
                              like_after=like_after)

        msg = explain(code, res.get("status_msg", ""))
        return TaskResult(ST_FAIL, f"API từ chối: {msg}", code=code)

    def _digg_count(self, client: TikTokClient, aweme: str, cid: str) -> int | None:
        try:
            item = client.find_comment(aweme, cid, max_pages=2)
        except TikTokError:
            return None
        if not item:
            return None
        return item.get("digg_count")

    # ------------------------------------------------------------------ #
    # Chế độ 2: trả lời 1 cid
    # ------------------------------------------------------------------ #
    def _reply_cid(self, aid, client, cfg: RunConfig, progress) -> TaskResult:
        cid, aweme = cfg.cid.strip(), (cfg.aweme_id.strip() or extract_aweme_id(cfg.video))
        if not cfg.comment.strip():
            return TaskResult(ST_FAIL, "chưa nhập nội dung trả lời")
        if not cid.isdigit():
            return TaskResult(ST_FAIL, "CID không hợp lệ")

        progress(aid, f"Trả lời cid={cid}...", 60)
        res = client.publish_comment(aweme, cfg.comment, parent_cid=cid)
        code = _code_of(res)
        if code == 0:
            new_cid = str((res.get("data") or {}).get("cid", ""))
            note = f"✓ đã trả lời cid={cid}" + (f" → cid mới {new_cid}" if new_cid else "")
            progress(aid, note, 100)
            return TaskResult(ST_OK, note, comment_id=new_cid or cid, found=True, ok=True)
        return TaskResult(ST_FAIL, f"API từ chối: {explain(code, res.get('status_msg', ''))}",
                          code=code)

    # ------------------------------------------------------------------ #
    # Chế độ 3: tự tìm reply theo từ khoá rồi thả tim (nhiều request hơn)
    # ------------------------------------------------------------------ #
    def _find_like(self, aid, client, cfg: RunConfig, progress) -> TaskResult:
        aweme = cfg.aweme_id.strip() or extract_aweme_id(cfg.video)
        if not aweme:
            return TaskResult(ST_FAIL, "cần URL/aweme_id của bài viết")
        needle = (cfg.target_text or cfg.search_keyword).strip().lower()
        if not needle:
            return TaskResult(ST_FAIL, "cần từ khoá/nội dung để tìm reply")

        progress(aid, f"Quét bình luận của {aweme}...", 40)
        hit = client.search_comment(aweme, needle, max_pages=cfg.extra.get("pages", 4))
        if not hit:
            return TaskResult(ST_FAIL, f"không tìm thấy reply chứa '{needle}'")

        cid = str(hit.get("cid"))
        likes = hit.get("digg_count", 0)
        progress(aid, f"Tìm thấy cid={cid} ({likes} like) → thả tim", 70)

        res = client.digg_comment(aweme, cid, digg=True)
        code = _code_of(res)
        if code == 0:
            note = f"♥ cid={cid} ({likes} → {likes + 1} like)"
            progress(aid, note, 100)
            return TaskResult(ST_OK, note, comment_id=cid, found=True, ok=True,
                              like_after=likes + 1)
        return TaskResult(
            ST_FAIL,
            f"API từ chối (code {code}): "
            f"{explain(code, res.get('status_msg', ''))}",
        )

    # ------------------------------------------------------------------ #
    def close_thread(self) -> None:
        pass

"""DIAGNOS: tại sao thả tim cho REPLY không tăng số like?

⚠ Script này GỌI MẠNG THẬT (nhiều request) — chạy nhiều lần liên tiếp sẽ
bị TikTok chặn IP (body rỗng) và mất ~30-60 phút mới hết. Chạy 1 lần rồi
để nghỉ.

So sánh 2 thứ trên CÙNG một phiên, CÙNG một video:
  1. thả tim cho 1 comment GỐC  (cây cấp 1)
  2. thả tim cho 1 REPLY        (cây cấp 2)

Sau mỗi lần thả tim, đọc lại `user_digged` / `digg_count` để biết thật
không. Nếu format hiện tại không dính, thử lần lượt các biến thể request
(giống cách timT làm) cho tới khi cái nào dính.

Chạy:  python test_reply_like.py [aweme_id]
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.parser import load_accounts
from core.proxy import parse_proxy
from core.settings import AppSettings
from core.signer import Signer
from core.tiktok import EP_COMMENT_DIGG, TikTokClient

# Video dùng để thử (video lấy từ DevTools của project)
DEFAULT_AWEME = "7690908625404955910"

# aweme_id dùng để ĐỌC LẠI trạng thái (luôn có, kể cả khi thử thả tim
# không kèm aweme_id — đó mới là biến thể đáng ngờ).
READ_AWEME = DEFAULT_AWEME


def hr(title: str) -> None:
    print("\n" + "=" * 68)
    print(title)
    print("=" * 68)


def build_client(proxy: str = "") -> TikTokClient:
    s = AppSettings.load()
    accs = load_accounts(s.last_cookie_file or "cokie.tik.txt")
    acc = next((a for a in accs if a.has_session()), accs[0])
    px = proxy or s.system_proxy
    proxies = None
    if px:
        prof = parse_proxy(px)
        if prof:
            user = f"{prof.username}:{prof.password}@" if prof.username else ""
            proxies = {"http": f"http://{user}{prof.host}:{prof.port}",
                       "https": f"http://{user}{prof.host}:{prof.port}"}
            print(f"  proxy : {prof.host}:{prof.port} "
                  f"(user={prof.username or '-'})")
    print(f"  acc   : {acc.username}")
    client = TikTokClient(
        acc, Signer(timeout=90), region=s.region, timezone=s.timezone,
        language=s.language,
        referer=f"https://www.tiktok.com/@x/video/{DEFAULT_AWEME}",
    )
    if proxies:
        client._proxies = proxies
        client._ensure_session()
    return client


def find_video(client: TikTokClient) -> str:
    """Tìm 1 video có bình luận CÓ REPLY (để thử cả 2 loại)."""
    for aweme in (sys.argv[1] if len(sys.argv) > 1 else DEFAULT_AWEME,):
        try:
            data = client.comment_list(aweme, cursor=0, count=50)
        except Exception as e:
            print(f"  video {aweme}: lỗi {e}")
            continue
        items = data.get("comments") or []
        with_reply = [c for c in items
                      if int(c.get("reply_comment_total") or 0) > 0]
        print(f"  video {aweme}: {len(items)} comment cấp 1, "
              f"{len(with_reply)} có reply")
        if items:
            return aweme
    return ""


def pick_targets(client: TikTokClient, aweme: str, skip: set | None = None):
    """Trả về (comment_gốc, reply, parent) — cả hai chưa được account này thả tim."""
    skip = skip or set()
    cursor = 0
    top = None
    for _page in range(3):
        data = client.comment_list(aweme, cursor=cursor, count=50)
        items = data.get("comments") or []
        if top is None:
            top = next((c for c in items
                        if not int(c.get("reply_comment_total") or 0)
                        and int(c.get("user_digged") or 0) == 0
                        and str(c.get("cid")) not in skip), None)
        for c in items:
            if not int(c.get("reply_comment_total") or 0):
                continue
            try:
                rdata = client.comment_replies(aweme, str(c.get("cid")), 0, 50)
            except Exception:
                continue
            reps = rdata.get("comments") or []
            cand = next((r for r in reps
                         if int(r.get("user_digged") or 0) == 0
                         and str(r.get("cid")) not in skip), None)
            if cand:
                return top, cand, c
        if not data.get("has_more") or not items:
            break
        cursor = data.get("cursor", cursor + len(items))
    return top, None, None


def read_state(client: TikTokClient, aweme: str, cid: str, parent_cid: str):
    """Đọc lại user_digged + digg_count của 1 cid (cấp 1 hoặc reply)."""
    try:
        data = client.comment_list(aweme, cursor=0, count=50)
        for c in data.get("comments") or []:
            if str(c.get("cid")) == str(cid):
                return c
            if parent_cid and str(c.get("cid")) == str(parent_cid):
                rdata = client.comment_replies(aweme, str(c.get("cid")), 0, 20)
                for r in rdata.get("comments") or []:
                    if str(r.get("cid")) == str(cid):
                        return r
    except Exception as e:
        print(f"  [read_state lỗi] {e}")
    return None


def dig_raw(client: TikTokClient, aweme: str, cid: str, *,
            extra: dict | None = None, drop_ms_token: bool = False,
            referer_param: str | None = None, history_len: str | None = None,
            body: bool = False, referer_header: str = "") -> dict:
    """Gửi POST /api/comment/digg/ với tham số kiểm soát được."""
    params = client.base_params({"cid": str(cid), "digg_type": 1})
    if aweme:
        params["aweme_id"] = str(aweme)
    if extra:
        params.update(extra)
    if drop_ms_token:
        params.pop("msToken", None)
    if referer_param is not None:
        params["referer"] = referer_param
    if history_len is not None:
        params["history_len"] = history_len
    params.pop("root_referer", None) if extra is None else None

    query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    raw_url = f"https://www.tiktok.com{EP_COMMENT_DIGG}?{query}"
    signed = client.signer.sign(raw_url)
    url = signed["signed_url"]
    client._adopt_navigator(signed.get("navigator") or {})
    headers = client._headers()
    if referer_header:
        headers["Referer"] = referer_header
    headers["Content-Type"] = "application/x-www-form-urlencoded"
    if body:
        resp = client.sess.request("POST", url, data=query.encode(),
                                   headers=headers, timeout=30)
    else:
        resp = client.sess.request("POST", url, data=b"",
                                   headers=headers, timeout=30)
    try:
        return resp.json()
    except ValueError:
        return {"status_code": -1, "raw": resp.text[:200]}


def try_variant(name: str, client, aweme, cid, parent_cid, **kw) -> bool:
    """Thử 1 biến thể; trả về True nếu tim dính (user_digged=1)."""
    print(f"\n  → thử: {name}")
    try:
        res = dig_raw(client, aweme, cid, **kw)
    except Exception as e:
        print(f"     lỗi: {type(e).__name__}: {e}")
        return False
    code = res.get("status_code")
    print(f"     status_code={code} msg={res.get('status_msg', '')[:60]!r}")
    time.sleep(1.5)
    after = read_state(client, READ_AWEME, cid, parent_cid)
    dug = (after or {}).get("user_digged")
    likes = (after or {}).get("digg_count")
    print(f"     sau khi thả: user_digged={dug} digg_count={likes}")
    return dug == 1


def main() -> int:
    global READ_AWEME
    hr("1. CHUẨN BỊ")
    client = build_client()
    aweme = find_video(client)
    if not aweme:
        print("Không tìm được video nào có bình luận.")
        return 1
    READ_AWEME = aweme
    client.referer = f"https://www.tiktok.com/@x/video/{aweme}"

    top, reply, parent = pick_targets(client, aweme)
    hr("2. MỐC ĐO")
    if top:
        print(f"  comment GỐC : cid={top.get('cid')} "
              f"like={top.get('digg_count')} digged={top.get('user_digged')}")
    if reply:
        print(f"  REPLY        : cid={reply.get('cid')} "
              f"reply_id={reply.get('reply_id')} like={reply.get('digg_count')} "
              f"digged={reply.get('user_digged')}")
        print(f"  parent       : cid={parent.get('cid')} "
              f"like={parent.get('digg_count')}")
    if not reply:
        print("Không tìm được reply nào chưa thả tim.")
        return 1

    hr("3. THỬ THẢ TIM COMMENT GỐC (mốc so sánh)")
    if top:
        try_variant("format hiện tại của app", client, aweme, top["cid"], "",
                    referer_header=client.referer)
    else:
        print("  (không có comment gốc để so sánh)")

    hr("4. THỬ THẢ TIM REPLY — các biến thể")
    rc = str(reply["cid"])
    pc = str(parent.get("cid"))
    rid = str(reply.get("reply_id") or "")
    print(f"  reply cid={rc}  parent cid={pc}  reply_id={rid}")

    variants = [
        ("A. format hiện tại của app (cid + aweme_id + digg_type)",
         {}),
        ("B. + reply_id của reply",
         {"extra": {"reply_id": rid}}),
        ("C. + reply_id & parent cid",
         {"extra": {"reply_id": rid, "comment_id": pc}}),
        ("D. bỏ msToken khỏi query (giống timT)",
         {"drop_ms_token": True}),
        ("E. referer rỗng trong query (giống timT)",
         {"referer_param": ""}),
        ("F. history_len=3 (giống timT)",
         {"history_len": "3"}),
        ("G. gửi tham số trong BODY thay vì query",
         {"body": True}),
        ("H. đủ A+B+D+E",
         {"extra": {"reply_id": rid}, "drop_ms_token": True,
          "referer_param": ""}),
    ]
    for name, kw in variants:
        if try_variant(name, client, aweme, rc, pc,
                       referer_header=client.referer, **kw):
            print(f"\n  ==> DÍNH với biến thể: {name}")
            print(f"  ==> tham số gợi ý: {json.dumps(kw, ensure_ascii=False)}")
            break

    hr("5. THỬ KHÔNG CÓ aweme_id (đúng lúc user KHÔNG dán Video URL)")
    used = {rc, str(top.get("cid")) if top else ""}
    top2, reply2, parent2 = pick_targets(client, aweme, skip=used)
    if top2:
        tc = str(top2.get("cid"))
        ok = try_variant("comment GỐC, KHÔNG aweme_id", client, "", tc, "",
                         referer_header=client.referer)
        used.add(tc)
    if reply2:
        rc2 = str(reply2.get("cid"))
        pc2 = str(parent2.get("cid"))
        ok2 = try_variant("REPLY, KHÔNG aweme_id", client, "", rc2, pc2,
                          referer_header=client.referer)
        print("\n  ==> KẾT LUẬN:")
        print(f"      comment gốc không aweme_id : {'DÍNH' if ok else 'KHÔNG dính'}")
        print(f"      reply      không aweme_id : {'DÍNH' if ok2 else 'KHÔNG dính'}")

    hr("6. CHẠY ĐÚNG LUỒNG CỦA APP (HttpBackend._like_cid)")
    app_path(client, aweme)

    hr("7. NHIỀU ACCOUNT CÙNG LÚC (giống app chạy lô) — đo số request")
    multi_account(client, aweme)
    return 0


def multi_account(client: TikTokClient, aweme: str, n: int = 8) -> None:
    """Chạy N account cùng lúc qua đúng luồng app, đếm số request gửi đi.

    Đây là chỗ dễ vỡ: mỗi account tự quét cây bình luận để xác minh thì
    1 reply tốn hàng chục request -> TikTok chặn IP -> không account nào
    thả tim được.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from core.backends.base import StopFlag
    from core.backends.http_backend import HttpBackend
    from core.config import MODE_LIKE_CID, RunConfig
    from core.parser import load_accounts
    from core.settings import AppSettings

    s = AppSettings.load()
    accs = [a for a in load_accounts(s.last_cookie_file or "cokie.tik.txt")
            if a.has_session()][:n]
    print(f"  dùng {len(accs)} account")

    counter = {"n": 0}
    orig = TikTokClient._request

    def counting(self, *a, **kw):
        counter["n"] += 1
        return orig(self, *a, **kw)

    TikTokClient._request = counting

    lvl2, lvl3 = find_deep_replies(client, aweme)
    targets = []
    if lvl2:
        targets.append(("REPLY cấp 2", lvl2[0]))
    if lvl3:
        targets.append(("REPLY cấp 3", lvl3[0]))
    top, _r, _p = pick_targets(client, aweme)
    if top:
        targets.append(("comment GỐC", top))

    try:
        for label, item in targets:
            counter["n"] = 0
            cfg = RunConfig(
                mode=MODE_LIKE_CID, cid=str(item.get("cid")), aweme_id=aweme,
                video=f"https://www.tiktok.com/@x/video/{aweme}",
                signer_url=s.signer_url, region=s.region, timezone=s.timezone,
                language=s.language, proxy=s.system_proxy,
                use_proxy_pool=False, verify=True, retries=1,
            )
            backend = HttpBackend(pool=None, rotate_on_block=False)

            def work(acc):
                res = backend.run(acc, cfg, StopFlag(threading.Event()),
                                   lambda *a: None)
                return res.note

            t0 = time.time()
            with ThreadPoolExecutor(max_workers=len(accs)) as ex:
                notes = list(ex.map(work, accs))
            dt = time.time() - t0
            ok = sum(1 for x in notes if "xác minh" in x)
            print(f"\n  [{label}] cid={item.get('cid')} "
                  f"({len(accs)} account, {dt:.1f}s)")
            print(f"     tổng request gửi đi : {counter['n']} "
                  f"({counter['n'] / max(1, len(accs)):.1f}/account)")
            print(f"     xác minh thành công  : {ok}/{len(accs)}")
            for note in notes[:6]:
                print(f"       - {note}")
    finally:
        TikTokClient._request = orig


def find_deep_replies(client: TikTokClient, aweme: str):
    """Tìm reply cấp 2 và reply cấp 3 (trả lời reply) chưa được thả tim."""
    data = client.comment_list(aweme, cursor=0, count=50)
    items = data.get("comments") or []
    lvl2 = None
    lvl3 = None
    for c in items:
        if not int(c.get("reply_comment_total") or 0):
            continue
        try:
            rdata = client.comment_replies(aweme, str(c.get("cid")), 0, 50)
        except Exception:
            continue
        reps = rdata.get("comments") or []
        for rep in reps:
            if int(rep.get("user_digged") or 0) == 0 and lvl2 is None:
                lvl2 = (rep, c)
            if int(rep.get("reply_comment_total") or 0) > 0:
                try:
                    r2 = client.comment_replies(aweme, str(rep.get("cid")),
                                                0, 50)
                except Exception:
                    continue
                for rep3 in r2.get("comments") or []:
                    if int(rep3.get("user_digged") or 0) == 0:
                        lvl3 = (rep3, rep, c)
                        break
        if lvl2 and lvl3:
            break
    return lvl2, lvl3


def app_path(client: TikTokClient, aweme: str) -> None:
    """Chạy y hệt app: HttpBackend.run() với mode like_cid + verify."""
    import threading

    from core.backends.base import StopFlag
    from core.backends.http_backend import HttpBackend
    from core.config import MODE_LIKE_CID, RunConfig
    from core.parser import load_accounts
    from core.settings import AppSettings

    s = AppSettings.load()
    accs = load_accounts(s.last_cookie_file or "cokie.tik.txt")
    backend = HttpBackend(pool=None, rotate_on_block=False)

    lvl2, lvl3 = find_deep_replies(client, aweme)
    targets = []
    if lvl2:
        targets.append(("REPLY cấp 2", lvl2[0], lvl2[1]))
    if lvl3:
        targets.append(("REPLY cấp 3 (trả lời reply)", lvl3[0], lvl3[2]))

    for label, item, parent in targets:
        acc = next((a for a in accs if a.has_session()), accs[0])
        cfg = RunConfig(
            mode=MODE_LIKE_CID, cid=str(item.get("cid")), aweme_id=aweme,
            video=f"https://www.tiktok.com/@x/video/{aweme}",
            signer_url=s.signer_url, region=s.region, timezone=s.timezone,
            language=s.language, proxy=s.system_proxy,
            use_proxy_pool=False, verify=True, retries=1,
        )

        def prog(aid, msg, pct):
            pass

        res = backend.run(acc, cfg, StopFlag(threading.Event()), prog)
        print(f"  [{label}] cid={item.get('cid')} "
              f"trước: like={item.get('digg_count')} "
              f"digged={item.get('user_digged')}")
        print(f"  [{label}] → status={res.status} note={res.note!r}")
        time.sleep(1)
        after = read_state(client, aweme, str(item.get("cid")),
                           str(parent.get("cid")) if parent else "")
        print(f"  [{label}] sau (đọc lại): like={(after or {}).get('digg_count')} "
              f"digged={(after or {}).get('user_digged')}")
        print(f"  [{label}] find_comment() thấy không: "
              f"{_find_via_app(client, aweme, item.get('cid'))}")
        print()


def _find_via_app(client: TikTokClient, aweme: str, cid) -> str:
    """Dùng đúng hàm của app để định vị cid (xem có tìm thấy không)."""
    try:
        item = client.find_comment(aweme, str(cid), max_pages=2)
    except Exception as e:
        return f"LỖI {e}"
    if item is None:
        return "KHÔNG tìm thấy"
    return (f"cid={item.get('cid')} like={item.get('digg_count')} "
            f"digged={item.get('user_digged')}")


if __name__ == "__main__":
    sys.exit(main())

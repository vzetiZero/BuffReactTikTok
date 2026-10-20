"""Bộ định vị comment dùng chung — mỗi account chỉ tốn 1 request xác minh.

Vì sao cần: xác minh thả tim phải biết cid nằm ở đâu trong cây bình luận.
Với bình luận GỐC thì 1 request là xong, nhưng với REPLY thì phải quét từng
bình luận cha (mỗi cha 1 request `/api/comment/list/reply/`).

Trước đây mỗi account tự quét lại từ đầu: 700 account x 20 bình luận cha
= 14.000 request ra cùng 1 IP → TikTok chặn IP → thả tim reply không dính,
còn thả tim comment gốc thì vẫn được (vì chỉ tốn 1 request).

Test này dùng client GIẢ nên không gọi mạng.

Chạy:  python test_comment_locator.py
"""

from __future__ import annotations

import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.tiktok import LOCATOR, TikTokClient

PASS, FAIL = 0, 0


def check(label, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  OK   {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label}\n        got  {got!r}\n        want {want!r}")


class FakeClient(TikTokClient):
    """Client giả: cây bình luận giả, đếm số request."""

    def __init__(self, tree):
        self._tree = tree          # {cid_top: [cid_reply, ...]}
        self.calls = []            # mỗi lần gọi: ("list", cursor) | ("reply", cid)

    def comment_list(self, aweme_id, cursor=0, count=20):
        self.calls.append(("list", cursor))
        items = []
        for cid, replies in self._tree.items():
            items.append({
                "cid": cid,
                "text": f"top {cid}",
                "reply_comment_total": len(replies),
                "user_digged": 0,
                "digg_count": 1,
            })
        return {"comments": items, "has_more": False, "cursor": cursor + 50}

    def comment_replies(self, aweme_id, comment_id, cursor=0, count=20):
        self.calls.append(("reply", comment_id))
        replies = self._tree.get(comment_id, [])
        return {"comments": [
            {"cid": r, "text": f"reply {r}", "user_digged": 0, "digg_count": 0,
             "reply_comment_total": 0}
            for r in replies
        ], "has_more": False}

def main():
    # cây bình luận: 5 bình luận gốc, mỗi cái có 3 reply
    tree = {f"top{i}": [f"top{i}-r{j}" for j in range(3)]
            for i in range(5)}

    print("\n=== 1. comment GOC: moi account chi 1 request ===")
    LOCATOR._hits.clear()
    LOCATOR._miss.clear()
    c = FakeClient(tree)
    item = c.comment_state("aw1", "top0")
    check("tim thay comment goc", (item or {}).get("cid"), "top0")
    check("quet dung 1 lan (list)", len(c.calls), 1)
    c.calls.clear()
    for _ in range(10):
        c.comment_state("aw1", "top0")
    check("10 account sau: 1 request moi account", len(c.calls), 10)

    print("\n=== 2. REPLY: quet 1 lan, cac account sau chi 1 request ===")
    LOCATOR._hits.clear()
    LOCATOR._miss.clear()
    c = FakeClient(tree)
    # reply nam o binh luan cha thu 5 -> phai quet qua 5 binh luan co reply
    item = c.comment_state("aw2", "top4-r2")
    check("tim thay reply", (item or {}).get("cid"), "top4-r2")
    n_scan = len(c.calls)
    check("quet ton tai reply ton tai 5 binh luan cha", n_scan, 6)
    check("khong quet lai lan 2",
          sum(1 for x in c.calls if x[0] == "reply"), 5)
    c.calls.clear()
    for _ in range(10):
        it = c.comment_state("aw2", "top4-r2")
    check("10 account sau: chi 1 request moi account", len(c.calls), 10)
    check("van tim thay reply sau khi dung cache",
          (it or {}).get("cid"), "top4-r2")

    print("\n=== 3. REPLY: nhieu account cung quet 1 luc -> chi 1 lan quet ===")
    LOCATOR._hits.clear()
    LOCATOR._miss.clear()
    clients = [FakeClient(tree) for _ in range(8)]
    barrier = threading.Barrier(len(clients))
    out: list = []

    def work(cl):
        barrier.wait()
        out.append(cl.comment_state("aw3", "top3-r1"))

    threads = [threading.Thread(target=work, args=(cl,)) for cl in clients]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    total = sum(len(cl.calls) for cl in clients)
    # 1 lan quet: 1 list + 4 reply list = 5 request, + 8 account x 1 = 13
    check("tong request cua 8 account <= 13", total <= 13, True)
    check("khong phai moi account quet lai", total <= 5 + len(clients), True)
    check("moi account deu tim thay reply",
          sum(1 for x in out if x and x.get("cid") == "top3-r1"),
          len(clients))

    print("\n=== 4. cid khong ton tai: chi quet 1 lan (khong quet lai 700 lan) ===")
    LOCATOR._hits.clear()
    LOCATOR._miss.clear()
    c = FakeClient(tree)
    check("khong tim thay", c.comment_state("aw4", "khong-co-that"), None)
    n1 = len(c.calls)
    c.calls.clear()
    for _ in range(10):
        c.comment_state("aw4", "khong-co-that")
    check("quet 1 lan xong, 10 account sau khong quet lai", len(c.calls), 0)
    check("lan quet dau tien co quet that", n1 > 0, True)

    print(f"\n{'=' * 58}\n  {PASS} pass, {FAIL} fail\n{'=' * 58}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

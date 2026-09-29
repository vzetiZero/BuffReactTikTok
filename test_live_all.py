"""TEST THẬT — 7 tài khoản trong file cookie, thả tim 1 bình luận theo CID.

Chạy:  python test_live_all.py <cid> [so_acc]
"""

import sys
import time
from concurrent.futures import ThreadPoolExecutor

from core.parser import load_accounts
from core.signer import Signer
from core.tiktok import TikTokClient, TikTokError, _code_of, explain

CID = sys.argv[1] if len(sys.argv) > 1 else "7654223771003994898"
LIMIT = int(sys.argv[2]) if len(sys.argv) > 2 else 0

signer = Signer("http://127.0.0.1:8080")
print(f"sidecar : {'OK' if signer.is_ready() else 'KHONG'}")
if not signer.is_ready():
    sys.exit(1)

accs = load_accounts("cokie.tik.txt")
if LIMIT:
    accs = accs[:LIMIT]
print(f"tai khoan: {len(accs)}   cid: {CID}\n")


def one(acc):
    c = TikTokClient(acc, signer, region="VN", timezone="Asia/Bangkok")
    t = time.time()
    try:
        r = c.digg_comment("", CID, digg=True)
        code = _code_of(r)
        return (acc.username, code, explain(code, r.get("status_msg", "")),
                time.time() - t)
    except TikTokError as e:
        return (acc.username, e.code, str(e), time.time() - t)
    except Exception as e:
        return (acc.username, -1, f"{type(e).__name__}: {str(e)[:90]}",
                time.time() - t)


start = time.time()
with ThreadPoolExecutor(max_workers=len(accs)) as pool:
    rows = list(pool.map(one, accs))
el = time.time() - start

for name, code, msg, dur in rows:
    print(f"  {name:22} code={code:<7} {dur:5.1f}s  {msg}")

good = sum(1 for r in rows if r[1] == 0)
print(f"\nket qua: {good}/{len(rows)} thanh cong   "
      f"({el:.1f}s, {len(rows)/max(el, .1):.2f} acc/s)")

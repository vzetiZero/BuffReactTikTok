"""TEST THẬT 1 tài khoản — chỉ có cid, không có aweme_id.

Mục đích: xác minh xem `POST /api/comment/digg/` có chạy được khi thiếu
`aweme_id` hay không, và cookie của bạn còn sống hay không.

Chạy:  python test_live_one.py <cid>
"""

import sys

from core.parser import load_accounts
from core.signer import Signer
from core.tiktok import TikTokClient, TikTokError, explain

CID = sys.argv[1] if len(sys.argv) > 1 else "7690897576899658504"

signer = Signer("http://127.0.0.1:8080")
print("sidecar:", "OK" if signer.is_ready() else "KHONG")
if not signer.is_ready():
    sys.exit(1)
print("navigator UA:", signer.navigator().get("user_agent", "?"))

accs = load_accounts("cokie.tik.txt")
acc = accs[0]
print(f"\ntai khoan: {acc.username}  ({acc.email})")
print(f"cid      : {CID}")
print(f"aweme_id : (KHONG truyen)\n")

c = TikTokClient(acc, signer, region="VN", timezone="Asia/Bangkok", language="")
print(f"language : {c.language}   os: {c.os}/{c.platform}")
print(f"verifyFp : {'co' if c.verify_fp else 'khong'}")
print(f"msToken  : {c.ms_token[:28]}…\n")

# --- 1. kiem tra dang nhap ---
print("[1] GET /api/user/detail/  — kiem tra cookie con song?")
try:
    u = c.user_detail(acc.username)
    print(f"    OK — nickname: {u.get('nickname')}  id: {u.get('id')}")
    logged = True
except TikTokError as e:
    print(f"    LOI code={e.code}: {e}")
    print(f"    → {explain(e.code)}")
    logged = False

# --- 2. tha tim ---
if logged:
    print("\n[2] POST /api/comment/digg/  — chi truyen cid, KHONG co aweme_id")
    try:
        r = c.digg_comment("", CID, digg=True)
        code = r.get("status_code")
        msg = r.get("status_msg", "")
        print(f"    status_code = {code}   status_msg = '{msg}'")
        data = r.get("data")
        if data:
            print(f"    data = {str(data)[:200]}")
        if code == 0:
            print("    => THANH CONG")
        else:
            print(f"    => {explain(code, msg)}")
    except TikTokError as e:
        print(f"    LOI code={e.code}: {e}")
        print(f"    → {explain(e.code)}")
    except Exception as e:
        print(f"    LOI {type(e).__name__}: {str(e)[:200]}")

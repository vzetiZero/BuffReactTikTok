"""Sinh URL digg giống hệt request thật trong DevTools, để đối chiếu từng tham số.

Chạy: python test_digg_url.py
"""

import sys
import urllib.parse

from core.parser import load_accounts
from core.signer import Signer
from core.tiktok import EP_COMMENT_DIGG, TikTokClient

# ---- request thật bạn gửi (lấy từ DevTools) ----
REAL = {
    "WebIdLastTime": "1790676569", "aid": "1988", "app_language": "vi-VN",
    "app_name": "tiktok_web", "aweme_id": "7690231603343265042",
    "browser_language": "vi-VN", "browser_name": "Mozilla",
    "browser_online": "true", "browser_platform": "Win32",
    "browser_version": "5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36",
    "channel": "tiktok_web", "channel_id": "0",
    "cid": "7690897576899658504", "cookie_enabled": "true",
    "data_collection_enabled": "true", "device_id": "7690897284192421396",
    "device_platform": "web_pc", "digg_type": "1", "focus_state": "true",
    "from_page": "video", "history_len": "8", "is_fullscreen": "false",
    "is_page_visible": "true", "odinId": "7603950839691281425",
    "os": "windows", "priority_region": "VN",
    "referer": "https://www.tiktok.com/vi-VN/",
    "region": "VN", "root_referer": "https://www.google.com/",
    "screen_height": "1080", "screen_width": "1920",
    "tz_name": "Asia/Bangkok", "user_is_login": "true",
    "verifyFp": "verify_mumimhg1_yVf135qS_kIam_4PZO_8yA4_5tgKJIOqbkKe",
    "webcast_language": "vi-VN",
}
# tham số do sidecar sinh / biến thiên theo phien -> không so sanh gia tri
SIGNING = {"X-Bogus", "X-Gnarly", "X-Dynosaur", "msToken"}
# gia tri doi lap theo phien -> khong so sanh
VOLATILE = {"WebIdLastTime"}
# so phu thuoc may cua nguoi dung (UA cua sidecar) -> khong so sanh gia tri
ENV_DEPENDENT = {"browser_version", "browser_platform", "os", "screen_height",
                 "screen_width", "device_id", "odinId", "verifyFp", "WebIdLastTime",
                 "aweme_id", "cid"}

fail = 0


def section(t):
    print(f"\n{t}\n{'-' * len(t)}")


section("1. Client co lay dung tham so tu cookie khong?")
accs = load_accounts("cokie.tik.txt")
acc = accs[0]
client = TikTokClient(acc, Signer(), region="VN", timezone="Asia/Bangkok",
                      language="")
c = client
print(f"  store-country-code : {acc.cookie.get('store-country-code')}")
print(f"  -> language        : {c.language}   (mong doi vi-VN)")
print(f"  -> locale_path     : {c.locale_path}")
print(f"  -> verifyFp        : {'OK' if c.verify_fp else 'THIEU'}")
print(f"  -> device_id       : {c.device_id or '(bo qua — file luu UUID)'}")
print(f"  -> odinId          : {c.odin_id or '(bo qua — khong co trong cookie)'}")
if c.language != "vi-VN":
    fail += 1
    print("  !! language sai")
if not c.verify_fp:
    fail += 1
    print("  !! thieu verifyFp")

section("2. URL ta sinh co khop request that khong?")
mine = c.base_params({
    "aweme_id": "7690231603343265042",
    "cid": "7690897576899658504",
    "digg_type": 1,
})
mine_keys = set(mine)
real_keys = set(REAL) | SIGNING

# Thiếu nhưng chấp nhận được: chữ ký (sidecar tự thêm sau), device_id/odinId
# (file cookie không có nên app cố tình bỏ trống thay vì gửi giá trị sai).
EXPECTED_MISSING = SIGNING | {"device_id", "odinId"}

print(f"  tham so thieu (khong phai loi):")
for k in sorted(real_keys - mine_keys):
    if k in EXPECTED_MISSING:
        print(f"    - {k:14} (OK — {k in SIGNING and 'sidecar se them' or 'file khong co, bo qua'})")
    else:
        fail += 1
        print(f"    - {k:14} !! THIEU THAT")
print(f"  tham so thua:")
for k in sorted(mine_keys - real_keys):
    fail += 1
    print(f"    + {k:14} !! THUA")

print("\n  so sanh gia tri:")
for k in sorted(mine_keys & real_keys):
    if k in SIGNING or k in VOLATILE or k in ENV_DEPENDENT:
        print(f"    --  {k:26} (phu thuoc may/sidecar, bo qua so sanh)")
        continue
    if k in mine and k in REAL:
        same = mine[k] == REAL[k]
        mark = "OK " if same else "SAI"
        if not same:
            fail += 1
        print(f"    {mark} {k:26} ta={mine[k][:38]:38} that={REAL[k][:38]}")

section("3. Header CSRF dung ten chua?")
h = c.debug_headers()
print(f"  tt-csrf-token : {'co' if 'tt-csrf-token' in h else 'THIEU'}")
print(f"  x-csrf-token  : {'co' if 'x-csrf-token' in h else 'khong ( dung )'}")
print(f"  Referer       : {h.get('Referer')}")
print(f"  Accept-Language: {h.get('Accept-Language')}")
if "tt-csrf-token" not in h:
    fail += 1

section("4. URL day du (chua ky)")
print("  " + c.debug_url(EP_COMMENT_DIGG, {
    "aweme_id": "7690231603343265042",
    "cid": "7690897576899658504",
    "digg_type": 1,
}, sign=False)[:300] + " …")

section("5. Chu ky do sidecar sinh (X-Gnarly / X-Dynosaur / X-Bogus)")
print("  Cac tham so nay KHONG the tu viet tay — sidecar lo phan nay.")
print("  Request that cua ban co ca 3:")
print("    X-Bogus   = 1              (gia tri de, chi la co so tao ky)")
print("    X-Gnarly  = MCeokLHWFSX1…  (chu ky that su)")
print("    X-Dynosaur= M8ln-splcyYy…  (chu ky phu)")
print("  -> app lay signed_url tu sidecar, khong tu dich cac chu ky nay.")

print(f"\n{'=' * 50}")
print(f"  {'HOP LE' if not fail else f'{fail} KHAC BIET'}")
print("=" * 50)
sys.exit(1 if fail else 0)

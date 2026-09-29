"""Test nhớ tài khoản — lưu rồi đọc lại được nguyên vẹn.

Chạy:  python test_account_cache.py
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.models import Account
from core.settings import load_accounts_cache, save_accounts_cache

PASS, FAIL = 0, 0


def check(label, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  OK   {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label}\n        got  {got!r}\n        want {want!r}")


def sample():
    return [
        Account(
            id="user6617320695474", username="@K4a#3GrifKiG",
            email="deisekei6362@hotmail.com", password="ble2KdTant",
            ms_token="M.C545_SN1.0.U.MsaArtifacts.1234",
            device_id="7690897284192421396",
            cookie={
                "sessionid_ss": "abc%3D%3D", "sid_tt": "sid-gu%7C1234567890",
                "msToken": "M.C545", "ttwid": "1%7Cttwid-value",
                "store-country-code": "vn", "tiêu đề có dấu": "giá trị",
            },
            raw="user6617320695474|@K4a#3GrifKiG|...",
            # các trường runtime KHÔNG được lưu:
            selected=False, status="✔ Thành công", note="♥ cid=123",
            proxy="http://1.2.3.4:8080", proxy_label="1.2.3.4:8080",
        ),
        Account(
            id="user7687686216592", username="@K4a@1RGPVntUbD",
            email="oriaalena1277@hotmail.com", password="ment1J3vHw",
            ms_token="M.C535_BAY", device_id="",
            cookie={"sessionid_ss": "x", "sid_tt": "y"},
        ),
    ]


def main():
    tmp = Path(tempfile.mkdtemp())
    cache = tmp / "accounts.json"

    print("\n=== 1. luu va doc lai ===")
    src = sample()
    p = save_accounts_cache(src, cache)
    check("file da tao", p.exists(), True)
    back = load_accounts_cache(cache)
    check("so tai khoan khop", len(back), len(src))

    print("\n=== 2. truong bat buoc giu nguyen ===")
    for i, (a, b) in enumerate(zip(src, back)):
        check(f"acc{i} id", b.id, a.id)
        check(f"acc{i} username", b.username, a.username)
        check(f"acc{i} email", b.email, a.email)
        check(f"acc{i} password", b.password, a.password)
        check(f"acc{i} ms_token", b.ms_token, a.ms_token)
        check(f"acc{i} device_id", b.device_id, a.device_id)
        check(f"acc{i} cookie", b.cookie, a.cookie)
        check(f"acc{i} raw", b.raw, a.raw)

    print("\n=== 3. tieng Viet trong cookie khong hong ===")
    check("khoa co dau giu nguyen", back[0].cookie.get("tiêu đề có dấu"),
          "giá trị")

    print("\n=== 4. truong runtime phai reset ===")
    b0 = back[0]
    check("status ve 'Cho'", b0.status, "Chờ")
    check("note rong", b0.note, "")
    check("proxy rong", b0.proxy, "")
    check("selected = True (mac dinh tick)", b0.selected, True)
    check("comment_id rong", b0.comment_id, "")

    print("\n=== 5. has_session() dung sau khi doc lai ===")
    check("acc0 con phien", back[0].has_session(), True)
    check("acc1 con phien", back[1].has_session(), True)

    print("\n=== 6. truong hop rac ===")
    check("file khong ton tai -> rong", load_accounts_cache(tmp / "no.json"), [])

    (tmp / "bad.json").write_text("{ khong phai json", encoding="utf-8")
    check("file hong -> rong, khong vong", load_accounts_cache(tmp / "bad.json"),
          [])

    (tmp / "notlist.json").write_text('{"a": 1}', encoding="utf-8")
    check("khong phai danh sach -> rong",
          load_accounts_cache(tmp / "notlist.json"), [])

    (tmp / "rows.json").write_text(
        '[{"username": "@ok"}, {"email": "khong co username"}, 42, "x"]',
        encoding="utf-8",
    )
    rows = load_accounts_cache(tmp / "rows.json")
    check("bo qua dong hong, giu dong dung", len(rows), 1)
    check("dong dung giu username", rows[0].username, "@ok")

    print("\n=== 7. danh sach rong ===")
    save_accounts_cache([], tmp / "empty.json")
    check("luu rong -> doc ra rong", load_accounts_cache(tmp / "empty.json"), [])

    print("\n=== 8. ghi de file da co ===")
    save_accounts_cache(sample()[:1], cache)
    check("ghi de thanh 1 tai khoan", len(load_accounts_cache(cache)), 1)

    print(f"\n{'='*50}\n  {PASS} pass, {FAIL} fail\n{'='*50}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

"""Test lớp proxy: parse các định dạng, phân phối, xoay vòng, gateway."""

import sys

from core.parser import load_accounts
from core.proxy import (
    MODE_GATEWAY,
    MODE_RANDOM,
    MODE_ROUND_ROBIN,
    GatewayConfig,
    ProxyPool,
    check_many,
    parse_proxy,
)

ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {name}")
    else:
        fail += 1
        print(f"  FAIL  {name}  {extra}")


print("\n=== 1. Parse cac dinh dang ===")
cases = [
    ("1.2.3.4:8080", dict(host="1.2.3.4", port=8080)),
    ("1.2.3.4:8080:userA:passA", dict(host="1.2.3.4", port=8080,
                                      username="userA", password="passA")),
    ("userB:passB@5.6.7.8:1080", dict(host="5.6.7.8", port=1080,
                                      username="userB", password="passB")),
    ("socks5://9.9.9.9:1080", dict(host="9.9.9.9", port=1080, scheme="socks5")),
    ("http://u:p@1.1.1.1:3128", dict(host="1.1.1.1", port=3128, scheme="http")),
]
for raw, want in cases:
    p = parse_proxy(raw)
    got = p.__dict__ if p else {}
    good = p and all(got.get(k) == v for k, v in want.items())
    check(f"parse {raw[:34]:34}", good,
          "" if good else f"-> {want} vs {got}")

check("dong comment bi bo qua", parse_proxy("# note") is None)
check("dong rac bi bo qua", parse_proxy("khong phai proxy") is None)
check("port sai bi bo qua", parse_proxy("1.2.3.4:99999") is None)
p = parse_proxy("1.2.3.4:8080:user:pass:with:colons")
check("mat khau chua dau :", p and p.password == "pass:with:colons",
      p.password if p else "")
check("mat khau duoc che khi hien thi",
      parse_proxy("1.2.3.4:8080:user:secret").safe_url().count("secret") == 0)

print("\n=== 2. Phan phoi round-robin ===")
accs = load_accounts("cokie.tik.txt")
pool = ProxyPool()
n, bad = pool.load("1.1.1.1:1001\n1.1.1.2:1002\n1.1.1.3:1003")
check("doc 3 proxy", n == 3 and not bad, f"n={n} bad={bad}")
pool.mode = MODE_ROUND_ROBIN
pool.assign(accs)
hosts = [a.proxy for a in accs]
check("7 account -> 3 proxy xoay vong",
      len(set(hosts)) == 3 and all(h for h in hosts), hosts)
check("account thu 4 dung lai proxy 1",
      accs[3].proxy == accs[0].proxy, f"{accs[3].proxy} vs {accs[0].proxy}")
check("moi proxy gan it nhat 1 account",
      all(p.assigned >= 1 for p in pool.items),
      [p.assigned for p in pool.items])

print("\n=== 3. Xoay vong khi bi chan IP ===")
before = accs[0].proxy
after = pool.rotate(accs[0])
check("account doi duoc proxy", before != after, f"{before} -> {after}")
check("proxy moi lay tu trong pool", after in [p.to_url() for p in pool.items])

print("\n=== 4. Proxy bi tat se khong duoc gan ===")
pool.items[0].enabled = False
st = pool.assign(accs)
check("proxy tat bi bo qua",
      pool.items[0].to_url() not in [a.proxy for a in accs],
      pool.items[0].to_url())
pool.items[0].enabled = True

print("\n=== 5. Cong VPN Express (session rieng tung account) ===")
gw = GatewayConfig(host="gate.vpnexpress.net", port=10000,
                   user="tenDangNhap", password="matKhau", country="vn",
                   enabled=True)
gpool = ProxyPool(mode=MODE_GATEWAY, gateway=gw)
gpool.assign(accs)
print(f"    URL mau: {accs[0].proxy[:78]}")
check("URL co country vn", "-country-vn-" in accs[0].proxy, accs[0].proxy)
check("URL co session rieng", "-session-" in accs[0].proxy, accs[0].proxy)
check("URL co mat khau", ":matKhau@" in accs[0].proxy, accs[0].proxy)
sessions = {a.proxy.split("-session-")[1].split(":")[0] for a in accs}
check("7 account -> 7 session khac nhau", len(sessions) == len(accs), sessions)
check("mat khau khong lo trong label", "matKhau" not in accs[0].proxy_label)

print("\n=== 6. Xoay session khi bi chan ===")
old = accs[0].proxy
new = gpool.rotate(accs[0])
check("doi session thanh cong", old != new, f"{old[:60]} -> {new[:60]}")

print("\n=== 7. Gateway thieu thong tin ===")
empty = GatewayConfig(user="")
check("khong co username -> tra None", empty.build("acc1") is None)

print("\n=== 8. Luu / tai cau hinh ===")
from core.settings import AppSettings
s = AppSettings(proxy_text="1.1.1.1:1001", proxy_mode=MODE_RANDOM,
                gw_user="u", gw_pass="p")
p2 = s.save("C:/Users/Administrator/AppData/Local/Temp/opencode/tk_test.json")
s2 = AppSettings.load(p2)
check("settings ghi/doi doc khop",
      s2.proxy_text == s.proxy_text and s2.gw_pass == "p" and s2.proxy_mode == MODE_RANDOM)
import os
os.remove(p2)

print(f"\n{'='*46}\n  {ok} PASS / {fail} FAIL\n{'='*46}")
sys.exit(1 if fail else 0)

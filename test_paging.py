"""Test phân trang theo số thứ tự + phát hiện proxy hệ thống."""

import sys

from PySide6.QtCore import QCoreApplication

from core.models import NO_ROLE, ST_OK, Account, AccountTableModel
from core.proxy import detect_system_proxy

app = QCoreApplication(sys.argv)

ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {name}")
    else:
        fail += 1
        print(f"  FAIL  {name}  {extra}")


def make(n):
    out = []
    for i in range(n):
        a = Account(id=f"id{i:03d}", username=f"user{i}", email=f"u{i}@x.com",
                    password="p", ms_token="m", device_id="d", cookie={})
        a.cookie["sessionid_ss"] = "s"
        a.cookie["sid_tt"] = "t"
        a.selected = i % 3 != 0        # 2/3 được tick
        out.append(a)
    return out


print("\n=== 1. Phan trang co so ===")
m = AccountTableModel()
m.load(make(100))
m.set_per_page(25)
check("100 account / 25 = 4 trang", m.page_count == 4, m.page_count)
check("trang 1: dong 1-25", (m.page_first, m.page_last) == (1, 25),
      (m.page_first, m.page_last))
m.set_page(1)
check("trang 2: dong 26-50", (m.page_first, m.page_last) == (26, 50),
      (m.page_first, m.page_last))
m.set_page(3)
check("trang 4: dong 76-100", (m.page_first, m.page_last) == (76, 100),
      (m.page_first, m.page_last))
m.last_page()
check("last_page -> trang cuoi", m.page == 3, m.page)
m.set_page(99)
check("vuot trang cuoi -> keo ve", m.page == 3, m.page)
m.set_page(-5)
check("am -> keo ve dau", m.page == 0, m.page)

print("\n=== 2. So thu tu khong reset khi doi trang ===")
from PySide6.QtCore import Qt

nos = []
for p in range(m.page_count):
    m.set_page(p)
    for r in range(m.rowCount()):
        nos.append(m.index(r, 0).data(NO_ROLE))
check("so thu tu tu 1..100 khong trung", nos == list(range(1, 101)),
      f"dau={nos[:3]} cuoi={nos[-3:]} len={len(nos)}")
check("khong co so thu tu None", all(x is not None for x in nos))

print("\n=== 3. rowCount theo trang ===")
m.set_per_page(25)
m.set_page(0)
check("trang dau 25 dong", m.rowCount() == 25, m.rowCount())
m.load(make(30))
m.set_per_page(25)
m.set_page(0)
check("30 account -> trang 1 = 25", m.rowCount() == 25, m.rowCount())
m.set_page(1)
check("trang 2 = 5 dong", m.rowCount() == 5, m.rowCount())
m.set_per_page(0)
check("per_page=0 -> tat ca 30 dong", m.rowCount() == 30, m.rowCount())
check("per_page=0 -> 1 trang", m.page_count == 1, m.page_count)

print("\n=== 4. Tick khong gioi han theo trang ===")
m.load(make(100))
m.set_per_page(25)
m.set_page(0)
sel_before = m.selected_count()
sel_page = sum(1 for a in m.page_rows() if a.selected)
m.toggle_page(False)
sel = m.selected_count()
# chỉ những dòng ĐANG TICK trên trang 1 mới bị bỏ; các trang khác giữ nguyên
check(f"bỏ tick trang 1: {sel_before} - {sel_page} = {sel_before - sel_page}",
      sel == sel_before - sel_page, f"{sel_before} {sel_page} {sel}")
m.set_page(3)
check("trang 4 khong bi doi", sum(1 for a in m.page_rows() if a.selected) == 16,
      sum(1 for a in m.page_rows() if a.selected))
m.select_all_with_session()
check("tick còn phiên -> het 100", m.selected_count() == 100, m.selected_count())
m.select_none()
check("bỏ tick het -> 0", m.selected_count() == 0, m.selected_count())
m.toggle_all(True)
check("tick tat ca -> 100", m.selected_count() == 100, m.selected_count())

print("\n=== 5. update_row o trang khong khong lam hong ===")
m.set_page(0)
m.update_row("id050", status=ST_OK, note="x")
m.set_page(0)
acc = m.by_id("id050")
check("id050 o trang 3 nhin thay update",
      acc.status == ST_OK and acc.note == "x", f"{acc.status} {acc.note}")
n_before = m.rowCount()
m.update_row("id050", status=ST_OK, note="x")     # lap lai, khong doi
check("rowCount khong doi", m.rowCount() == n_before, m.rowCount())
m.update_row("khong-ton-tai", status=ST_OK)
check("id la khong bo qua, khong crash", True)

print("\n=== 6. Phat hien proxy he thong ===")
url, src = detect_system_proxy()
print(f"    -> {url or '(khong co)'}   [{src or '-'}]")
check("tra ve 2 gia tri", isinstance(url, str) and isinstance(src, str))
if url:
    check("co scheme", "://" in url, url)

print(f"\n{'=' * 46}\n  {ok} PASS / {fail} FAIL\n{'=' * 46}")
sys.exit(1 if fail else 0)

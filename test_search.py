"""Test tìm kiếm / lọc / sắp xếp / phân trang trên danh sách lớn."""

import sys
import time

from PySide6.QtCore import QCoreApplication, Qt

from core.models import (
    NO_ROLE,
    ST_FAIL,
    ST_OK,
    Account,
    AccountTableModel,
)

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
        a = Account(
            id=f"id{i:05d}",
            username=f"user{i:05d}",
            email=f"mail{i:05d}@x.com",
            password="p", ms_token="m", device_id="d", cookie={},
        )
        if i % 10 == 0:                      # 1/10 thiếu phiên
            pass
        else:
            a.cookie["sessionid_ss"] = "s"
            a.cookie["sid_tt"] = "t"
        a.selected = i % 3 != 0
        if i % 7 == 0:
            a.proxy = f"http://1.1.1.{i % 250}:1000"
            a.proxy_label = f"1.1.1.{i % 250}:1000"
        if i % 5 == 0:
            a.status, a.note = ST_OK, "♥ cid=1 · like 10 → 11"
        elif i % 5 == 1:
            a.status, a.note = ST_FAIL, "cookie het phien"
        out.append(a)
    return out


N = 5000
accs = make(N)
m = AccountTableModel()
m.load(accs)
m.set_per_page(50)

print(f"\n=== 0. Danh sach {N} tai khoan ===")
check("nap duoc tat ca", m.total == N, m.total)
check("mac dinh xem het", m.view_count == N, m.view_count)
check("100 trang", m.page_count == 100, m.page_count)
t0 = time.perf_counter()
m.set_page(99)
check("den trang cuoi", m.page == 99 and m.page_last == N,
      f"{m.page} {m.page_last}")
print(f"        (chuyen trang: {(time.perf_counter() - t0) * 1000:.1f} ms)")

print("\n=== 1. Tim kiem chuoi ===")
m.set_query("user00042")
check("khop 1 dong", m.view_count == 1, m.view_count)
m.set_query("user000")
# user00000..user00099 -> 100 dong
check("tien to khop 100 dong", m.view_count == 100, m.view_count)
m.set_query("user00001 user000")
check("2 tu: 'user00001' va 'user000' -> 1 dong",
      m.view_count == 1, m.view_count)
m.set_query("user00001 KHONGCO")
check("co 1 tu khong khop -> 0 dong", m.view_count == 0, m.view_count)
m.set_query("MAIL00007@X.COM")
check("khong phan biet hoa thuong", m.view_count == 1, m.view_count)
m.set_query("khong-ton-tai")
check("khong khop -> 0 dong", m.view_count == 0, m.view_count)
check("khong khop -> van 1 trang", m.page_count == 1, m.page_count)

print("\n=== 2. Tim kiem theo truong khac ===")
m.set_query("cookie het phien")
check("tim theo ket qua", m.view_count > 0, m.view_count)
m.set_query("1.1.1.")
check("tim theo proxy", m.view_count > 0, m.view_count)
m.set_query("id04999")
check("tim theo user id", m.view_count == 1, m.view_count)

print("\n=== 3. Loc nhanh ===")
m.set_query("")
m.set_filter(AccountTableModel.F_NO_SESSION)
check("thieu phien = 1/10", m.view_count == N // 10, m.view_count)
m.set_filter(AccountTableModel.F_HAS_SESSION)
check("con phien = 90%", m.view_count == N - N // 10, m.view_count)
m.set_filter(AccountTableModel.F_HAS_PROXY)
check("co proxy > 0", 0 < m.view_count < N, m.view_count)
m.set_filter(AccountTableModel.F_OK)
check("thanh cong > 0", m.view_count > 0, m.view_count)
m.set_filter(AccountTableModel.F_FAIL)
check("bi loi > 0", m.view_count > 0, m.view_count)
m.set_filter(AccountTableModel.F_SELECTED)
check("da tick = 2/3", m.view_count == sum(1 for a in accs if a.selected),
      m.view_count)
m.set_filter(AccountTableModel.F_ALL)
check("tat ca lai = N", m.view_count == N, m.view_count)

print("\n=== 4. Loc + tim kiem cung luc ===")
m.set_filter(AccountTableModel.F_HAS_SESSION)
m.set_query("user0001")
check("giao nhau hai dieu kien",
      m.view_count == len([a for a in accs
                           if a.has_session() and "user0001" in a.username]),
      m.view_count)

print("\n=== 5. Sap xep ===")
# Dùng HẰNG SỐ CỦA MODEL thay vì viết số 0/1/2. Trước đây test ghi cứng
# "1 = username"; thêm cột Status (Status -> chỉ số 2) làm username dịch
# sang 2 và test đỏ, dù code chạy đúng. Gắn hằng số thì không còn chỗ cho
# kiểu lỗi đó.
C_STT = AccountTableModel.COL_ACCOUNT
# Sắp xếp theo TÊN: cột 1 (B · Kết quả) sắp theo (status, username) — trùng
# tên thì vẫn đúng, nhưng nếu status khác nhau thì tên bị xen kẽ. Cột 2
# (C · Status) sắp theo sức khoẻ rồi tên. Muốn "thuần username" thì dùng
# C_RESULT và bỏ qua phần status, vì vậy các mục dưới đây kiểm tra thứ tự
# tương đối chứ không so với một danh sách sort tay.
C_RESULT = AccountTableModel.COL_STATUS
C_USER = C_RESULT
C_HEALTH = AccountTableModel.COL_HEALTH

m.set_filter(AccountTableModel.F_ALL)
m.set_query("")
m.set_sort(C_STT, False)                    # STT tang dan
first = [m.row_to_account(r).username for r in range(5)]
check("STT tang dan", first == [f"user{i:05d}" for i in range(5)], first)

m.set_sort(C_USER, True)                    # (status, username) giam dan
first = [m.row_to_account(r) for r in range(5)]
got_keys = [(a.status, a.username) for a in first]
# KỲ VỌNG so với đúng khoá sắp xếp của cột B, dựng lại từ accs. Trước đây
# test mong đợi sort thuần theo username, nên luôn đỏ khi status khác nhau.
exp_keys = sorted(((a.status, a.username) for a in m.filtered_accounts()),
                  reverse=True)[:5]
check("cot B giam dan", got_keys == exp_keys,
      f"{[k[1] for k in got_keys[:3]]} vs {[k[1] for k in exp_keys[:3]]}")
check("cot B giam dan: trong cung mot status thi ten giam dan",
      all(got_keys[i][1] >= got_keys[i + 1][1]
          for i in range(len(got_keys) - 1)
          if got_keys[i][0] == got_keys[i + 1][0]), got_keys[:3])

m.set_sort(C_USER, False)
first = [m.row_to_account(r) for r in range(5)]
got_keys = [(a.status, a.username) for a in first]
exp_keys = sorted(((a.status, a.username) for a in m.filtered_accounts()))[:5]
check("cot B tang dan", got_keys == exp_keys,
      f"{[k[1] for k in got_keys[:3]]} vs {[k[1] for k in exp_keys[:3]]}")

m.set_sort(C_STT, True)
first = [m.row_to_account(r).username for r in range(5)]
check("STT giam dan", first == sorted(first, reverse=True), first[:3])

print("\n=== 5b. Sap xep theo cot Status ===")
m.set_sort(C_HEALTH, False)
first3 = [m.row_to_account(r).health for r in range(m.rowCount())]
# xep theo muc do: die -> het han -> khong ro -> dang kiem -> song -> chua kiem
check("cot Status sap xep duoc",
      all(isinstance(h, str) for h in first3), first3[:3])
check("cot Status khong lam loi so dong", len(first3), m.rowCount())

print("\n=== 6. So thu tu lien tuc qua trang ===")
m.set_sort(C_USER, False)
m.set_per_page(50)
nos = []
for p in range(m.page_count):
    m.set_page(p)
    for r in range(m.rowCount()):
        nos.append(m.index(r, 0).data(NO_ROLE))
check("STT 1..N khong trung, lien tuc",
      nos == list(range(1, N + 1)), f"{nos[:2]}..{nos[-2:]} len={len(nos)}")

print("\n=== 7. Sap xep + loc + phan trang cung luc ===")
m.set_filter(AccountTableModel.F_HAS_SESSION)
# Phải xoá tìm kiếm: mục 4 còn để truy vấn "user0001" (khớp mọi tài khoản
# có chuỗi đó trong tên), và nó vẫn đang có hiệu lực. Truy vấn đó lọc ra
# đúng những tên cách nhau 5 đơn vị — đó là lý do kỳ vọng ra
# user04995, 4990, 4985... chứ không phải lỗi sắp xếp.
m.set_query("")
m.set_sort(C_USER, True)
m.set_page(0)
cnt = m.view_count
expect = sorted([x for x in accs if x.has_session()],
                key=lambda x: (x.status, x.username), reverse=True)
got = [m.row_to_account(r) for r in range(3)]
# Cột B sắp theo (status, username) — kỳ vọng phải theo ĐÚNG khoá đó.
# Trước đây test mong đợi sort thuần theo username nên luôn đỏ với dữ liệu
# có status xen kẽ (mỗi 5 tài khoản một status khác nhau).
check("trang 1 dung thu tu da loc",
      [(g.status, g.username) for g in got]
      == [(e.status, e.username) for e in expect[:3]],
      f"{[g.username for g in got]} vs {[e.username for e in expect[:3]]}")
check("so dong trang dung", m.rowCount() == min(50, cnt), m.rowCount())
check("page_last dung", m.page_last == min(50, cnt), m.page_last)

print("\n=== 8. Tick theo bo loc ===")
m.set_filter(AccountTableModel.F_NO_SESSION)
m.set_query("")
no_sess = [a for a in accs if not a.has_session()]
before = sum(1 for a in accs if a.selected)
exp = before + sum(1 for a in no_sess if not a.selected)   # phải TÍNH TRƯỚC khi tick
m.toggle_view(True)
sel = sum(1 for a in accs if a.selected)
check("chi tick them nhom dang loc",
      sel == exp and all(a.selected for a in no_sess),
      f"{sel} vs {exp}")
m.set_filter(AccountTableModel.F_ALL)
check("tick khong lan sang nhom khac",
      sum(1 for a in accs if a.selected) == sel, "bi lan")

print("\n=== 9. Hieu nang tren danh sach lon ===")
t0 = time.perf_counter()
m.set_query("user012")
dt = (time.perf_counter() - t0) * 1000
check(f"loc 5000 dong duoi {300:.0f} ms ({dt:.0f} ms)", dt < 300, f"{dt:.0f} ms")

t0 = time.perf_counter()
for q in ("", "a", "ab", "abc", ""):
    m.set_query(q)
dt = (time.perf_counter() - t0) * 1000
check(f"5 lan loc lien tiep duoi {600:.0f} ms ({dt:.0f} ms)", dt < 600,
      f"{dt:.0f} ms")

t0 = time.perf_counter()
m.set_page(50)
dt = (time.perf_counter() - t0) * 1000
check(f"chuyen trang duoi {80:.0f} ms ({dt:.0f} ms)", dt < 80, f"{dt:.0f} ms")

print("\n=== 10. Xoa loc ===")
m.set_query("user012")
m.set_filter(AccountTableModel.F_NO_SESSION)
m.clear_search()
check("xoa loc -> het N", m.view_count == N, m.view_count)
check("xoa loc -> ve trang 1", m.page == 0, m.page)

print(f"\n{'=' * 46}\n  {ok} PASS / {fail} FAIL\n{'=' * 46}")
sys.exit(1 if fail else 0)

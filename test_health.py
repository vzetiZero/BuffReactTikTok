"""Test cột Status + phân loại sức khoẻ tài khoản — không gọi mạng thật.

Kiểm tra phần logic: phân loại HC_*, cột mới trong model, sắp xếp, lọc,
và cách phân biệt "cookie chết" với "bị chặn IP" (điểm dễ làm sai nhất —
gán nhầm "die" cho cả danh sách khi IP bị chặn).

Chạy:  python test_health.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from core.health import BLOCK_CODES, DEAD_CODES
from core.models import (
    HC_ALIVE,
    HC_CHECKING,
    HC_DEAD,
    HC_EXPIRED,
    HC_RISKY,
    HC_UNKNOWN,
    HEALTH_LABELS,
    HEALTH_ROLE,
    Account,
    AccountTableModel,
)

PASS, FAIL = 0, 0


def check(label, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  OK   {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label}\n        got  {got!r}\n        want {want!r}")


def acc(i, session=True, expired=False, health=HC_UNKNOWN):
    sid = f"sid{i:03d}aaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    # sid_guard = sid | issued | ttl  (URL-encode '|' thành %7C)
    import time
    now = int(time.time())
    if expired:
        guard = f"{sid}%7C{now - 1000}%7C100%7CS"      # đã hết hạn
    else:
        guard = f"{sid}%7C{now}%7C15552000%7CS"        # còn ~180 ngày
    c = {"ttwid": "1%7Cabc%7Csig", "msToken": "M.1"}
    if session:
        c["sessionid_ss"] = sid
        c["sid_tt"] = sid
        c["sid_guard"] = guard
    return Account(
        id=f"a{i:03d}", username=f"@user{i:03d}",
        email=f"user{i}@mail.com", password="p", ms_token="M.1",
        device_id="d", cookie=c,
        health=health, health_note="ghi chu thu", health_at=1756000000.0,
    )


def main():
    app = QApplication.instance() or QApplication([])

    print("\n=== 1. cot moi trong model ===")
    m = AccountTableModel()
    check("3 cot", m.columnCount(), 3)
    check("ten cot", list(AccountTableModel.HEADERS),
          ["A · Tài khoản", "B · Kết quả", "C · Status"])
    check("chi so cot", (m.COL_ACCOUNT, m.COL_STATUS, m.COL_HEALTH), (0, 1, 2))

    print("\n=== 2. expiry tinh tu sid_guard ===")
    a_live = acc(1)
    a_dead = acc(2, expired=True)
    check("con phien -> het han 2030+", a_live.is_expired(), False)
    check("het han -> True", a_dead.is_expired(), True)
    check("het han -> co ngay", bool(a_dead.expiry_hint()), True)
    check("khong co sid_guard -> khong do duoc", acc(3, session=False).expiry_ts(), 0)
    check("khong co sid_guard -> is_expired False",
          acc(3, session=False).is_expired(), False)

    print("\n=== 3. hieu luc phan biet 'die' va 'bi chan' ===")
    # day la diem quan trong nhat: KHONG duoc gan HC_DEAD khi chi bi chan
    check("200013 la DIE (het phien)", 200013 in DEAD_CODES, True)
    check("10221 KHONG phai DIE", 10221 in DEAD_CODES, False)
    check("10221 la BLOCK", 10221 in BLOCK_CODES, True)
    check("10202 la BLOCK", 10202 in BLOCK_CODES, True)
    check("8 la BLOCK (rate limit)", 8 in BLOCK_CODES, True)
    check("DEAD va BLOCK khong giao nhau", bool(DEAD_CODES & BLOCK_CODES), False)

    print("\n=== 4. nhan va data cua cot Status ===")
    m.load([a_live, a_dead])
    m.set_per_page(0)
    m.update_row("a001", health=HC_ALIVE, health_note="sống")
    m.update_row("a002", health=HC_DEAD, health_note="chết")
    i0, i1 = m.index(0, 2), m.index(1, 2)
    check("o 0 hien nhan", m.data(i0, Qt.ItemDataRole.DisplayRole),
          HEALTH_LABELS[HC_ALIVE])
    check("o 1 hien nhan", m.data(i1, Qt.ItemDataRole.DisplayRole),
          HEALTH_LABELS[HC_DEAD])
    check("HEALTH_ROLE tra ve ma", m.data(i0, HEALTH_ROLE), HC_ALIVE)
    check("HEALTH_ROLE o 1", m.data(i1, HEALTH_ROLE), HC_DEAD)
    tip = m.data(i1, Qt.ItemDataRole.ToolTipRole)
    check("tooltip co nhan", "chết" in tip, True)
    # ghi chú do update_row ghi đè, nên phải là "chết" chứ không phải
    # "ghi chu thu" ban đầu — đây là hành vi ĐÚNG.
    check("tooltip co ghi chu moi nhat", "Chi tiết" in tip and "chết" in tip,
          True)
    check("tooltip huong dan chuot phai",
          "Chuột phải" in tip, True)

    print("\n=== 5. cot B van chay dung ===")
    b0 = m.data(m.index(0, 1), Qt.ItemDataRole.DisplayRole)
    check("cot B = nhan ket qua cu", b0, AccountTableModel.STATUS_LABELS["Chờ"])

    print("\n=== 6. loc theo Status ===")
    m2 = AccountTableModel()
    m2.load([acc(i, health=(HC_ALIVE if i % 2 else HC_DEAD)) for i in range(10)])
    m2.set_per_page(0)
    m2.set_filter(AccountTableModel.F_ALIVE)
    check("loc 'con song' -> 5", m2.view_count, 5)
    m2.set_filter(AccountTableModel.F_DEAD)
    check("loc 'da die' -> 5", m2.view_count, 5)
    m2.set_filter(AccountTableModel.F_ALL)
    check("loc 'tat ca' -> 10", m2.view_count, 10)

    print("\n=== 7. sap xep theo Status: chet len dau ===")
    m2.set_sort(2, desc=False)      # tang danh theo muc do
    first = m2.page_rows()[0]
    check("dong dau la 'die'", first.health, HC_DEAD)
    m2.set_sort(2, desc=True)
    check("giam danh: song o dau",
          m2.page_rows()[0].health, HC_ALIVE)

    print("\n=== 8. dem + reset ===")
    m2.set_sort(0, desc=False)
    c = m2.health_counts()
    check("dem alive", c.get(HC_ALIVE), 5)
    check("dem dead", c.get(HC_DEAD), 5)
    m2.reset_health()
    check("reset -> tat ca unknown", m2.health_counts().get(HC_UNKNOWN), 10)

    print("\n=== 9. nhan ' dang kiem tra ' ===")
    m2.update_row("a000", health=HC_CHECKING)
    check("dang kiem tra", m2.by_id("a000").health, HC_CHECKING)
    check("nhan co nhan", HEALTH_LABELS[HC_CHECKING], "Đang kiểm…")
    check("o co nhan cho tung mau",
          all(v for v in HEALTH_LABELS.values()), True)

    print("\n=== 10. khong doi cot A/B khi them cot C ===")
    m3 = AccountTableModel()
    a = acc(7, health=HC_ALIVE)
    a.selected = True
    m3.load([a])
    m3.set_per_page(0)
    line = m3.data(m3.index(0, 0), Qt.ItemDataRole.DisplayRole)
    check("cot A van co username", "@user007" in line, True)
    check("cot A van co email", "user7@mail.com" in line, True)
    check("checkState cot A", m3.data(m3.index(0, 0),
                                      Qt.ItemDataRole.CheckStateRole),
          Qt.CheckState.Checked)

    print("\n=== 11. phan loai cuc bo (khong goi mang) ===")
    # Dung HealthTask truc tiep voi local_only -> khong can sidecar/mang.
    from core.health import HealthTask, HealthSignals
    sig = HealthSignals()

    def local(a):
        t = HealthTask(a, sig, "VN", "Asia/Bangkok", "", 1.0, local_only=True)
        t.run()
        return None

    got = {}
    sig.result.connect(lambda i, h, n, t: got.__setitem__(i, h))
    for a in (acc(11, health=HC_UNKNOWN), acc(12, session=False),
              acc(13, expired=True)):
        local(a)
    check("cookie day du -> alive", got.get("a011"), HC_ALIVE)
    check("thieu phien -> dead", got.get("a012"), HC_DEAD)
    check("het han -> expired", got.get("a013"), HC_EXPIRED)

    print(f"\n{'='*50}\n  {PASS} pass, {FAIL} fail\n{'='*50}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

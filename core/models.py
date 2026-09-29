"""Mô hình dữ liệu cho account + QAbstractTableModel cho bảng trên GUI.

Điểm quan trọng: mọi cập nhật từ worker thread đều đi qua `id` của account,
không đi qua chỉ số dòng (row index) — vì row index thay đổi khi sort/filter/insert.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor

# --- Custom roles để GUI / controller truyền dữ liệu kèm theo ---
ID_ROLE = Qt.ItemDataRole.UserRole + 1
CHECK_ROLE = Qt.ItemDataRole.UserRole + 2
# Số thứ tự toàn cục trong danh sách (không phải số dòng trên trang hiện tại)
NO_ROLE = Qt.ItemDataRole.UserRole + 3
HAS_SESSION_ROLE = Qt.ItemDataRole.UserRole + 4
# Mức sức khoẻ tài khoản (HC_*), để delegate vẽ cột Status
HEALTH_ROLE = Qt.ItemDataRole.UserRole + 5

# --- Trạng thái (dùng chung cho model và backend) ---
ST_IDLE = "Chờ"
ST_RUNNING = "Đang chạy"
ST_OK = "Thành công"
ST_FAIL = "Lỗi"
ST_SKIP = "Bỏ qua"
ST_DONE = "Hoàn tất"  # đăng nhập OK nhưng chưa bình luận (chỉ chế độ check)

# --- Sức khoẻ tài khoản (cột Status) ---
# Tách khỏi ST_* vì ý nghĩa khác: ST_* là kết quả LẦN CHẠY vừa rồi,
# HC_* là tình trạng tài khoản có dùng được hay không.
HC_UNKNOWN = "unknown"    # chưa kiểm tra
HC_CHECKING = "checking"  # đang kiểm tra
HC_ALIVE = "alive"        # cookie còn dùng được
HC_DEAD = "dead"          # chắc chắn hỏng
HC_EXPIRED = "expired"    # hết hạn theo sid_guard
HC_RISKY = "risky"        # không kết luận được (bị chặn bot / IP)

HEALTH_LABELS = {
    HC_UNKNOWN: "Chưa kiểm",
    HC_CHECKING: "Đang kiểm…",
    HC_ALIVE: "● Sống",
    HC_DEAD: "✖ Die",
    HC_EXPIRED: "⌛ Hết hạn",
    HC_RISKY: "? Không rõ",
}


_STATUS_COLORS = {
    ST_IDLE: QColor("#9aa4b2"),
    ST_RUNNING: QColor("#f5a623"),
    ST_OK: QColor("#2ecc71"),
    ST_FAIL: QColor("#e74c3c"),
    ST_SKIP: QColor("#7f8c8d"),
    ST_DONE: QColor("#3498db"),
}


_MISSING = object()


@dataclass(slots=True)
class Account:
    """Một tài khoản TikTok đọc từ file cookie."""

    id: str
    username: str
    email: str
    password: str
    ms_token: str
    device_id: str
    cookie: dict[str, str] = field(default_factory=dict)
    raw: str = ""

    # Trạng thái runtime (chỉ dùng khi chạy app, không serialize)
    selected: bool = True
    status: str = ST_IDLE
    note: str = ""
    comment_id: str = ""
    found: bool = False
    login_ok: bool = False

    # Sức khoẻ tài khoản (cột Status) — kết quả của lần kiểm tra gần nhất
    health: str = HC_UNKNOWN
    health_note: str = ""
    health_at: float = 0.0        # mốc thời gian (time.time())

    # Proxy riêng (gán từ tab Cài đặt)
    proxy: str = ""              # URL curl_cffi dùng thật (có mật khẩu)
    proxy_label: str = ""        # dạng hiển thị, đã che mật khẩu

    # Số like đọc lại được sau khi thả tim — dùng in dòng log
    # "2 TIM CMT <cid>". None = chưa biết (tắt verify / chưa chạy).
    like_after: int | None = None

    def has_session(self) -> bool:
        """Cookie còn sống hay không — dựa vào các key bắt buộc của web login."""
        return "sessionid_ss" in self.cookie and "sid_tt" in self.cookie

    def expiry_hint(self) -> str:
        """Ngày hết hạn từ `sid_guard` = sid|ts|ttl|... (URL-encode bằng %7C)."""
        end = self.expiry_ts()
        return datetime.datetime.fromtimestamp(end).strftime("%Y-%m-%d") if end else ""

    def expiry_ts(self) -> int:
        """Mốc hết hạn (unix timestamp) của phiên, 0 nếu đọc không được."""
        raw = self.cookie.get("sid_guard", "")
        parts = raw.replace("|", "%7C").split("%7C")
        if len(parts) >= 3 and parts[1].isdigit():
            ttl = int(parts[2]) if parts[2].isdigit() else 0
            return int(parts[1]) + ttl
        return 0

    def is_expired(self) -> bool:
        """Phiên đã hết hạn theo đồng hồ của cookie chưa.

        Đây là kiểm tra SỐ BẰNG CHỨNG CỤC BỘ, không cần gọi mạng — nhưng
        TikTok có thể thu hồi phiên sớm hơn mốc ghi trong cookie (đổi mật
        khẩu, đăng xuất ở nơi khác, ban hành vì lạm dụng). Vì vậy đây chỉ là
        một trong các tín hiệu, không phải kết luận cuối.
        """
        end = self.expiry_ts()
        return bool(end) and end < datetime.datetime.now().timestamp()


@dataclass(slots=True)
class TaskResult:
    """Kết quả trả về từ backend cho 1 account."""

    status: str
    note: str = ""
    comment_id: str = ""
    found: bool = False
    ok: bool = False
    code: int = -1
    # Số like đọc lại được SAU khi thả tim (chế độ verify). None = không
    # đọc được (tắt verify, hoặc API không trả về). Dùng để in dòng log
    # dạng "2 TIM CMT <cid>" thay vì parse lại từ note.
    like_after: int | None = None


# --- Định dạng dòng log thành công ----------------------------------- #
# Người dùng muốn dạng gọn để copy đi dùng, ví dụ:
#     2 TIM CMT 7602703562657022728
# = "<số like> TIM CMT <cid>". Số like lấy từ phần verify đọc lại comment;
# nếu backend không đọc được (tắt verify) thì in "OK" cho rõ là đã thành
# công nhưng không biết số like.
LOG_OK_LABEL = "OK"


def format_success_line(
    note: str,
    comment_id: str = "",
    like_after: int | None = None,
) -> str:
    """Rút gọn note thành công thành 1 dòng kiểu '2 TIM CMT <cid>'.

    `note` là chuỗi backend sinh ra, ví dụ
        "♥ cid=7602703562657022728 · like 1 → 2"
    Hàm cố bóc cid và số like cuối cùng từ note. Trả về "" nếu không
    đọc được cid — lúc đó caller giữ nguyên note gốc để không mất
    thông tin.
    """
    import re

    cid = comment_id or ""
    if not cid:
        m = re.search(r"cid=(\d+)", note or "")
        if m:
            cid = m.group(1)
    if not cid:
        return ""

    n = like_after
    if n is None and note:
        # "like 1 → 2" hoặc "like=2" hoặc "(like=2)"
        m = re.search(r"like\s*=?\s*(\d+)\s*(?:→|->)\s*(\d+)", note)
        if m:
            n = int(m.group(2))
        else:
            m = re.search(r"like\s*=?\s*(\d+)", note)
            if m:
                n = int(m.group(1))

    head = f"{n} " if n is not None else f"{LOG_OK_LABEL} "
    return f"{head}TIM CMT {cid}"


class AccountTableModel(QAbstractTableModel):
    """Bảng 3 cột: A = tài khoản, B = trạng thái lần chạy, C = sức khoẻ."""

    HEADERS = ["A · Tài khoản", "B · Kết quả", "C · Status"]
    COL_ACCOUNT, COL_STATUS, COL_HEALTH = 0, 1, 2

    # --- bộ lọc nhanh (combo trên thanh tìm kiếm) ---
    F_ALL = "all"
    F_HAS_SESSION = "has_session"
    F_NO_SESSION = "no_session"
    F_SELECTED = "selected"
    F_UNSELECTED = "unselected"
    F_HAS_PROXY = "has_proxy"
    F_OK = "ok"
    F_FAIL = "fail"
    F_ALIVE = "alive"
    F_DEAD = "dead"

    FILTER_LABELS = {
        F_ALL: "Tất cả",
        F_HAS_SESSION: "Còn phiên đăng nhập",
        F_NO_SESSION: "Thiếu phiên",
        F_SELECTED: "Đã tick",
        F_UNSELECTED: "Chưa tick",
        F_HAS_PROXY: "Đã gán proxy",
        F_OK: "Thành công",
        F_FAIL: "Bị lỗi",
        F_ALIVE: "Status: còn sống",
        F_DEAD: "Status: đã die",
    }

    STATUS_LABELS = {
        ST_IDLE: "Chờ",
        ST_RUNNING: "Đang chạy…",
        ST_OK: "✔ Thành công",
        ST_FAIL: "✖ Lỗi",
        ST_SKIP: "– Bỏ qua",
        ST_DONE: "● Hoàn tất",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[Account] = []     # toàn bộ tài khoản (nguồn chân lý)
        self._view: list[Account] = []     # sau khi lọc + sắp xếp
        self._page = 0                     # trang hiện tại, đánh số từ 0
        self._per_page = 25                # số dòng mỗi trang; 0 = không phân trang
        self._query = ""                   # từ khoá tìm kiếm
        self._filter = self.F_ALL
        self._sort_col = 0                 # 0 = STT, 1 = username
        self._sort_desc = False
        # cache chuỗi tìm kiếm, tránh lower() lặp lại mỗi lần lọc
        self._hay_cache: dict[str, str] = {}

    # ---- API cho controller ----
    def load(self, accounts: list[Account]) -> None:
        self.beginResetModel()
        self._rows = accounts
        self._page = 0
        self._hay_cache = {a.id: self._haystack(a) for a in accounts}
        self._rebuild_view()
        self.endResetModel()

    # ---- tìm kiếm / lọc / sắp xếp ---------------------------------- #
    @staticmethod
    def _haystack(a: Account) -> str:
        """Chuỗi dùng để tìm kiếm: gộp mọi thông tin hay tìm."""
        return " ".join((
            a.username, a.email, a.id, a.proxy_label, a.status, a.note,
        )).lower()

    def set_query(self, text: str) -> None:
        q = (text or "").strip().lower()
        if q == self._query:
            return
        self.beginResetModel()
        self._query = q
        self._page = 0
        self._rebuild_view()
        self.endResetModel()

    @property
    def query(self) -> str:
        return self._query

    def set_filter(self, key: str) -> None:
        if key == self._filter:
            return
        self.beginResetModel()
        self._filter = key
        self._page = 0
        self._rebuild_view()
        self.endResetModel()

    @property
    def filter(self) -> str:
        return self._filter

    def set_sort(self, col: int, desc: bool) -> None:
        if col == self._sort_col and desc == self._sort_desc:
            return
        self.beginResetModel()
        self._sort_col, self._sort_desc = col, desc
        self._page = 0
        self._rebuild_view()
        self.endResetModel()

    @property
    def sort_col(self) -> int:
        return self._sort_col

    @property
    def sort_desc(self) -> bool:
        return self._sort_desc

    def _matches(self, a: Account) -> bool:
        f = self._filter
        if f == self.F_HAS_SESSION and not a.has_session():
            return False
        if f == self.F_NO_SESSION and a.has_session():
            return False
        if f == self.F_SELECTED and not a.selected:
            return False
        if f == self.F_UNSELECTED and a.selected:
            return False
        if f == self.F_HAS_PROXY and not a.proxy:
            return False
        if f == self.F_OK and a.status not in (ST_OK, ST_DONE):
            return False
        if f == self.F_FAIL and a.status != ST_FAIL:
            return False
        if f == self.F_ALIVE and a.health != HC_ALIVE:
            return False
        if f == self.F_DEAD and a.health not in (HC_DEAD, HC_EXPIRED):
            return False
        if self._query:
            hay = self._hay_cache.get(a.id)
            if hay is None:
                hay = self._hay_cache[a.id] = self._haystack(a)
            # từ khoá có khoảng trắng -> phải khớp TẤT CẢ các từ
            for term in self._query.split():
                if term not in hay:
                    return False
        return True

    def _rebuild_view(self) -> None:
        """Tính lại danh sách hiển thị. Gọi trong begin/endResetModel."""
        view = [a for a in self._rows if self._matches(a)]
        col, desc = self._sort_col, self._sort_desc
        if col == 0:
            # sắp xếp theo số thứ tự gốc -> chính là thứ tự trong _rows
            order = {id(a): i for i, a in enumerate(self._rows)}
            view.sort(key=lambda a: order[id(a)], reverse=desc)
        elif col == 1:
            view.sort(key=lambda a: (a.status, a.username.lower()),
                      reverse=desc)
        else:
            # cột 3 (sức khoẻ): nhóm theo mức độ "dùng được" để các tài
            # khoản chết dồn lên đầu, thay vì sắp theo chữ cái.
            rank = {HC_DEAD: 0, HC_EXPIRED: 1, HC_RISKY: 2, HC_CHECKING: 3,
                    HC_ALIVE: 4, HC_UNKNOWN: 5}
            view.sort(key=lambda a: (rank.get(a.health, 9),
                                     a.username.lower()), reverse=desc)
        self._view = view

    def clear_search(self) -> None:
        self.beginResetModel()
        self._query = ""
        self._filter = self.F_ALL
        self._page = 0
        self._rebuild_view()
        self.endResetModel()

    # ---- phân trang ----
    @property
    def total(self) -> int:
        """Tổng số tài khoản đã nạp (không phụ thuộc bộ lọc)."""
        return len(self._rows)

    @property
    def view_count(self) -> int:
        """Số tài khoản khớp bộ lọc / tìm kiếm."""
        return len(self._view)

    @property
    def per_page(self) -> int:
        return self._per_page

    @property
    def page(self) -> int:
        return self._page

    @property
    def page_count(self) -> int:
        if self._per_page <= 0 or not self._view:
            return 1
        return (len(self._view) + self._per_page - 1) // self._per_page

    @property
    def page_first(self) -> int:
        """Số thứ tự đầu tiên của trang, tính trên tập đang lọc (1-based)."""
        return self._page * self._per_page + 1 if self._per_page else 1

    @property
    def page_last(self) -> int:
        if self._per_page <= 0:
            return len(self._view)
        return min((self._page + 1) * self._per_page, len(self._view))

    def set_per_page(self, n: int) -> None:
        if n == self._per_page:
            return
        self.beginResetModel()
        self._per_page = n
        self._page = 0
        self.endResetModel()

    def set_page(self, page: int) -> None:
        page = max(0, min(page, self.page_count - 1))
        if page == self._page:
            return
        self.beginResetModel()
        self._page = page
        self.endResetModel()

    def next_page(self) -> None:
        self.set_page(self._page + 1)

    def prev_page(self) -> None:
        self.set_page(self._page - 1)

    def first_page(self) -> None:
        self.set_page(0)

    def last_page(self) -> None:
        self.set_page(self.page_count - 1)

    def page_rows(self) -> list[Account]:
        if self._per_page <= 0:
            return list(self._view)
        start = self._page * self._per_page
        return self._view[start:start + self._per_page]

    def page_slice(self) -> tuple[int, int]:
        """Khoảng chỉ số [start, end) của trang trong tập đang lọc."""
        if self._per_page <= 0:
            return 0, len(self._view)
        start = self._page * self._per_page
        return start, min(start + self._per_page, len(self._view))

    def row_to_account(self, row: int) -> Account | None:
        """Đổi chỉ số dòng trên bảng -> tài khoản (đã qua lọc + phân trang)."""
        start, end = self.page_slice()
        i = start + row
        if 0 <= i < end and i < len(self._view):
            return self._view[i]
        return None

    def _view_index(self, acc: Account) -> int:
        """Vị trí của account trong tập đang lọc, -1 nếu đang bị ẩn."""
        for i, a in enumerate(self._view):
            if a is acc:
                return i
        return -1

    def accounts(self) -> list[Account]:
        return self._rows

    def by_id(self, acc_id: str) -> Account | None:
        for a in self._rows:
            if a.id == acc_id:
                return a
        return None

    def update_row(self, acc_id: str, **fields) -> None:
        """Được gọi từ GUI thread (slot của signal) — an toàn về thread.

        Chỉ phát `dataChanged` nếu dòng đó đang nằm trên trang hiện tại; nếu không
        thì sự thay đổi vẫn được ghi vào object, lần lật trang sau sẽ thấy.
        """
        acc = self.by_id(acc_id)
        if acc is None:
            return
        changed = False
        for key, value in fields.items():
            if getattr(acc, key, _MISSING) != value:
                setattr(acc, key, value)
                changed = True
        if not changed:
            return

        # dòng đang bị lọc bỏ hoặc ở trang khác: dữ liệu đã lưu trong object,
        # lần vẽ sau sẽ thấy — không phát tín hiệu để tránh vẽ sai chỗ
        vi = self._view_index(acc)
        if vi < 0:
            return
        start, end = self.page_slice()
        if not (start <= vi < end):
            return
        self.dataChanged.emit(
            self.index(vi - start, 0),
            self.index(vi - start, self.columnCount() - 1),
        )

    def reset_status(self) -> None:
        for a in self._rows:
            a.status, a.note, a.comment_id, a.found = ST_IDLE, "", "", False
            a.login_ok = False
        self._refresh_page()

    def _refresh_page(self) -> None:
        """Phát tín hiệu vẽ lại trang hiện tại."""
        n = self.rowCount()
        if n:
            last = self.columnCount() - 1
            self.dataChanged.emit(self.index(0, 0), self.index(n - 1, last))

    def _emit_col(self, col: int) -> None:
        n = self.rowCount()
        if n:
            self.dataChanged.emit(self.index(0, col), self.index(n - 1, col))

    def toggle_all(self, checked: bool) -> None:
        for a in self._rows:
            a.selected = checked
        self._emit_col(self.COL_ACCOUNT)

    def select_none(self) -> None:
        self.toggle_all(False)

    def toggle_page(self, checked: bool) -> None:
        """Chỉ tick/bỏ tick những dòng đang hiển thị trên trang này."""
        for a in self.page_rows():
            a.selected = checked
        self._emit_col(self.COL_ACCOUNT)

    def toggle_view(self, checked: bool) -> None:
        """Tick/bỏ tick MỌI tài khoản khớp bộ lọc — dùng khi lọc theo
        nhóm nhỏ (ví dụ "Thiếu phiên") thay vì cả danh sách hàng chục nghìn."""
        for a in self._view:
            a.selected = checked
        self._refresh_page()

    def select_all_with_session(self) -> None:
        for a in self._rows:
            a.selected = a.has_session()
        self._refresh_page()

    def filtered_accounts(self) -> list[Account]:
        """Tài khoản đang khớp lọc/tìm kiếm."""
        return list(self._view)

    def selected_accounts(self) -> list[Account]:
        """Danh sách được tick — KHÔNG giới hạn theo trang đang xem."""
        return [a for a in self._rows if a.selected]

    def selected_count(self) -> int:
        return sum(1 for a in self._rows if a.selected)

    # ---- giới hạn số lượng tài khoản được chạy ------------------------ #
    # Người dùng tick 5.000 tài khoản nhưng chỉ muốn chạy thử 60 cái để
    # đo tốc độ thật. Hai cách chọn:
    #   PICK_RANDOM  - bấm ngẫu nhiên, không lo trùng lặp giữa các lần
    #   PICK_ORDER   - lấy đúng N cái đầu theo thứ tự đang hiển thị
    # Số 0 nghĩa là "không giới hạn" (chạy hết những gì đã tick).
    PICK_RANDOM = "random"
    PICK_ORDER = "order"
    PICK_LABELS = {
        PICK_RANDOM: "Ngẫu nhiên",
        PICK_ORDER: "Theo thứ tự",
    }

    @classmethod
    def pick_limited(
        cls,
        accounts: list[Account],
        limit: int,
        how: str = PICK_RANDOM,
        rng: "random.Random | None" = None,
    ) -> list[Account]:
        """Lấy tối đa `limit` tài khoản theo cách chọn.

        Không sửa list gốc và không đụng cờ `selected` — caller tự quyết
        định có tick lại trên bảng hay không.

        `limit <= 0` hoặc >= len(accounts) thì trả về nguyên list.
        """
        import random as _random

        if limit <= 0 or limit >= len(accounts):
            return list(accounts)
        if how == cls.PICK_ORDER:
            return list(accounts[:limit])
        r = rng or _random
        # sample chọn k-distinct, không trùng lặp — khác shuffle() cắt đuôi
        return r.sample(list(accounts), limit)

    def pick_for_run(
        self,
        limit: int,
        how: str = PICK_RANDOM,
        rng: "random.Random | None" = None,
    ) -> list[Account]:
        """Phiên bản gắn với model: chỉ xét những tài khoản ĐÃ TICK.

        Dùng `selected_accounts()` chứ không dùng cả `_view`, vì người dùng
        có thể tick rồi mới đổi bộ lọc — vẫn phải chạy đúng những cái đã
        tick, không phụ thuộc đang nhìn trang nào.
        """
        return self.pick_limited(self.selected_accounts(), limit, how, rng)

    def health_counts(self) -> dict[str, int]:
        """Đếm số tài khoản theo mức sức khoẻ, để hiện ở thanh dưới."""
        out: dict[str, int] = {}
        for a in self._rows:
            out[a.health] = out.get(a.health, 0) + 1
        return out

    def reset_health(self) -> None:
        for a in self._rows:
            a.health, a.health_note, a.health_at = HC_UNKNOWN, "", 0.0
        self._refresh_page()

    # ---- QAbstractTableModel API ----
    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        start, end = self.page_slice()
        return max(0, end - start)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.HEADERS)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        acc = self.row_to_account(index.row())
        if acc is None:
            return None
        col = index.column()

        if role == ID_ROLE:
            return acc.id
        if role == CHECK_ROLE:
            return Qt.CheckState.Checked if acc.selected else Qt.CheckState.Unchecked
        # Số thứ tự trong tập đang lọc — liên tục qua các trang
        if role == NO_ROLE:
            return self.page_first + index.row()
        if role == HAS_SESSION_ROLE:
            return acc.has_session()
        if role == HEALTH_ROLE:
            return acc.health

        if role == Qt.ItemDataRole.DisplayRole:
            if col == self.COL_ACCOUNT:
                return self.account_line(acc)
            if col == self.COL_HEALTH:
                return HEALTH_LABELS.get(acc.health, "?")
            return self.STATUS_LABELS.get(acc.status, acc.status)

        if role == Qt.ItemDataRole.CheckStateRole and col == self.COL_ACCOUNT:
            return Qt.CheckState.Checked if acc.selected else Qt.CheckState.Unchecked

        if role == Qt.ItemDataRole.ForegroundRole and col == self.COL_STATUS:
            return _STATUS_COLORS.get(acc.status)

        if role == Qt.ItemDataRole.TextAlignmentRole and col == self.COL_ACCOUNT:
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        if role == Qt.ItemDataRole.ToolTipRole:
            if col == self.COL_HEALTH:
                lines = [f"Sức khoẻ: {HEALTH_LABELS.get(acc.health, '?')}"]
                if acc.health_note:
                    lines.append(f"Chi tiết : {acc.health_note}")
                if acc.health_at:
                    lines.append(
                        "Kiểm tra  : "
                        + datetime.datetime.fromtimestamp(
                            acc.health_at).strftime("%H:%M:%S")
                    )
                lines.append("")
                lines.append("Chuột phải vào dòng này → 'Kiểm tra trạng thái'")
                return "\n".join(lines)
            if col == self.COL_STATUS:
                # chỉ trả về ghi chú; để rỗng thì dòng phụ không vẽ gì
                # (tránh lặp lại y hệt dòng trạng thái ở trên)
                return acc.note
            lines = [
                f"Username : {acc.username}",
                f"Email    : {acc.email}",
                f"User ID  : {acc.id}",
                f"Phiên    : {'còn phiên' if acc.has_session() else 'THIẾU sessionid_ss'}",
                f"Proxy    : {acc.proxy_label or acc.proxy or '(IP máy)'}",
            ]
            exp = acc.expiry_hint()
            if exp:
                lines.append(f"Hết hạn  : {exp}")
            if acc.note:
                lines.append(f"Kết quả  : {acc.note}")
            return "\n".join(lines)

        return None

    @staticmethod
    def account_line(acc: Account) -> str:
        flag = "" if acc.has_session() else "   ⚠ thiếu phiên"
        proxy = f"   ·   🌐 {acc.proxy_label}" if acc.proxy_label else ""
        return f"{acc.username}\n{acc.email}{proxy}{flag}"

    def setData(self, index: QModelIndex, value, role=Qt.ItemDataRole.EditRole):  # noqa: N802
        if role != Qt.ItemDataRole.CheckStateRole or index.column() != self.COL_ACCOUNT:
            return False
        acc = self.row_to_account(index.row())
        if acc is None:
            return False
        acc.selected = value == Qt.CheckState.Checked
        self.dataChanged.emit(index, index)
        return True

    def set_range_selected(self, r0: int, r1: int, checked: bool) -> int:
        """Tick/bỏ tick một DẢI dòng liên tiếp — dùng cho thao tác quét chuột.

        `r0`/`r1` là chỉ số dòng trên bảng (đã qua lọc), thứ tự không
        quan trọng. Trả về số tài khoản THỰC SỰ đổi trạng thái, để
        lần quét sau không báo nhầm là đã đổi khi không có gì đổi.

        Vẽ lại bằng một lần `dataChanged` cho cả khoảng thay vì mỗi
        dòng một lần — quét 3.000 dòng sẽ nhanh hơn hẳn.
        """
        if r0 > r1:
            r0, r1 = r1, r0
        start, end = self.page_slice()
        # cắt theo vùng đang hiện — row index ngoài trang này vô nghĩa
        lo, hi = max(r0, start - start), min(r1, end - start - 1)
        if lo > hi:
            return 0
        n = 0
        for row in range(lo, hi + 1):
            acc = self._view[start + row]
            if acc.selected != checked:
                acc.selected = checked
                n += 1
        if n:
            self.dataChanged.emit(self.index(lo, self.COL_ACCOUNT),
                                  self.index(hi, self.COL_ACCOUNT))
        return n

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        if self.row_to_account(index.row()) is None:
            return Qt.ItemFlag.NoItemFlags
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == self.COL_ACCOUNT:
            base |= Qt.ItemFlag.ItemIsUserCheckable
        return base

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientation == Qt.Orientation.Horizontal:
            if role == Qt.ItemDataRole.DisplayRole:
                return self.HEADERS[section]
            if role == Qt.ItemDataRole.ToolTipRole:
                if section == self.COL_HEALTH:
                    return ("Sức khoẻ tài khoản.\n"
                            "Chuột phải vào một dòng → 'Kiểm tra trạng thái'.\n"
                            "Bấm tiêu đề để gom tài khoản chết lên đầu.")
                return "Bấm để sắp xếp theo cột này"
        return None

    def sort(self, column: int, order=Qt.SortOrder.AscendingOrder) -> None:  # noqa: A003
        self.set_sort(column, order == Qt.SortOrder.DescendingOrder)

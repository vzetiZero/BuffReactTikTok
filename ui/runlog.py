"""Bảng LOG chạy — thay thế bảng danh sách tài khoản ở màn chính.

Vì sao tách riêng: bảng tài khoản có vài trăm tới vài nghìn dòng, nhưng
thứ người dùng cần nhìn khi đang chạy chỉ là "tài khoản nào vừa xong,
với cid nào, kết quả ra gì". Đó là một luồng dữ liệu khác hẳn, không
nên chung một bảng — nếu chung thì phải cuộn hàng nghìn dòng mới tìm
thấy dòng vừa chạy xong.

Mỗi dòng = 1 lần chạy 1 tài khoản với 1 cid:
    A · STT + tài khoản
    B · cid đang xử lý
    C · log tìm comment
    D · trạng thái
"""

from __future__ import annotations

import datetime

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor

# --- trạng thái dùng chung với core.models ---
ST_WAIT = "Chờ"
ST_RUN = "Đang chạy"
ST_OK = "Thành công"
ST_FAIL = "Lỗi"
ST_SKIP = "Bỏ qua"
ST_DONE = "Hoàn tất"

LOG_READY = 100

C_OK = QColor("#1e9e5a")
C_FAIL = QColor("#e74c3c")
C_RUN = QColor("#e08b0a")
C_SKIP = QColor("#8a94a6")
C_IDLE = QColor("#7a869a")
C_ACC = QColor("#1f2d3d")
C_CID = QColor("#3d5a80")
C_NOTE = QColor("#3b4a5f")
C_NUM = QColor("#93a1b3")
C_HEAD = QColor("#1f2d3d")

COL_A, COL_CID, COL_LOG, COL_ST = 0, 1, 2, 3


class RunRow:
    """Một dòng log: 1 tài khoản chạy với 1 cid."""

    # `acc` là ID (khoá ổn định, signal gửi id); `name` là username để
    # hiển thị. Tách hai thứ vì trước đây lưu username trong `acc` thì
    # các signal (vốn gửi id) không khớp dòng nào -> thống kê ra 0.
    __slots__ = ("no", "acc", "name", "cid", "note", "status", "at", "ok")

    def __init__(self, no: int, acc: str, cid: str = "", name: str = ""):
        self.no = no
        self.acc = acc
        self.name = name or acc
        self.cid = cid
        self.note = ""
        self.status = ST_WAIT
        self.at = 0.0
        self.ok = False


class RunLogModel(QAbstractTableModel):
    """Model của bảng log chạy. Chỉ giữ N dòng gần nhất để nhẹ."""

    HEADERS = ["A · Tài khoản", "B · CID", "C · Nhật ký", "D · Kết quả"]

    def __init__(self, parent=None, max_rows: int = 4000):
        super().__init__(parent)
        self._rows: list[RunRow] = []
        self._max_rows = max_rows
        # các cid đã chạy xong, giữ thứ tự — dùng cho ô "cid đã xong"
        self.done_cids: list[str] = []
        self.n_ok = 0
        self.n_fail = 0

    # ------------------------------------------------------------------ #
    def reset(self) -> None:
        self.beginResetModel()
        self._rows.clear()
        self.done_cids.clear()
        self.n_ok = 0
        self.n_fail = 0
        self.endResetModel()

    def clear_done(self) -> None:
        self.done_cids.clear()

    def add(self, acc: str, cid: str = "", name: str = "") -> RunRow:
        """Thêm một dòng cho tài khoản sắp chạy."""
        row = RunRow(len(self._rows) + 1, acc, cid, name)
        at = len(self._rows)
        self.beginInsertRows(QModelIndex(), at, at)
        self._rows.append(row)
        self.endInsertRows()
        # giới hạn bộ nhớ: bỏ dòng cũ nhất khi vượt quá ngưỡng
        if len(self._rows) > self._max_rows:
            self.beginRemoveRows(QModelIndex(), 0, 0)
            self._rows.pop(0)
            self.endRemoveRows()
            self._renumber()
        return row

    def _renumber(self) -> None:
        for i, r in enumerate(self._rows, 1):
            r.no = i
        if self._rows:
            self.dataChanged.emit(self.index(0, COL_A),
                                  self.index(len(self._rows) - 1, COL_A))

    def update(self, acc: str, *, note: str = "", status: str = "",
               cid: str = "", ok: bool | None = None) -> RunRow | None:
        """Cập nhật dòng của tài khoản `acc` (dòng cuối cùng của nó)."""
        target = None
        for r in reversed(self._rows):
            if r.acc == acc:
                target = r
                break
        if target is None:
            return None
        changed = False
        if cid and cid != target.cid:
            target.cid = cid
            changed = True
        if note and note != target.note:
            target.note = note
            changed = True
        if status and status != target.status:
            target.status = status
            changed = True
        if ok is not None:
            target.ok = ok
        if changed or ok is not None:
            target.at = datetime.datetime.now().timestamp()
            n = len(self._rows) - 1 - self._rows[::-1].index(target)
            self.dataChanged.emit(self.index(n, 0), self.index(n, 3))
        return target

    def set_status(self, acc: str, status: str, note: str = "",
                   ok: bool | None = None) -> RunRow | None:
        r = self.update(acc, note=note, status=status, ok=ok)
        if r and r.status in (ST_OK, ST_DONE) and r.cid:
            if r.cid not in self.done_cids:
                self.done_cids.append(r.cid)
            if r.status == ST_OK:
                self.n_ok += 1
        elif r and r.status == ST_FAIL:
            self.n_fail += 1
        return r

    # ------------------------------------------------------------------ #
    def row_count(self) -> int:
        return len(self._rows)

    def stats_text(self) -> str:
        n = len(self._rows)
        if not n:
            return "Chưa chạy gì."
        done = len(self.done_cids)
        return (f"xong {done}/{n}  ·  thành công {self.n_ok}  ·  "
                f"lỗi {self.n_fail}")

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.HEADERS)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        r = self._rows[index.row()]
        c = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if c == COL_A:
                return f"{r.no}.  {r.name}"
            if c == COL_CID:
                return r.cid
            if c == COL_LOG:
                return r.note
            if c == COL_ST:
                return r.status

        if role == Qt.ItemDataRole.ForegroundRole:
            if c == COL_A:
                return C_ACC
            if c == COL_CID:
                return C_CID
            if c == COL_LOG:
                return C_NOTE
            if c == COL_ST:
                return {ST_OK: C_OK, ST_DONE: C_OK, ST_FAIL: C_FAIL,
                        ST_RUN: C_RUN, ST_SKIP: C_SKIP}.get(r.status, C_IDLE)

        if role == Qt.ItemDataRole.ToolTipRole and c == COL_LOG:
            return r.note or "(chưa có log)"

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if c == COL_CID:
                return int(Qt.AlignmentFlag.AlignLeft
                           | Qt.AlignmentFlag.AlignVCenter)
        return None

    def headerData(self, section, orientation,  # noqa: N802
                   role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return str(section + 1)

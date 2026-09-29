"""Test vùng vẽ chữ trong ô — bắt lỗi 'mọi chữ hiện thành ...'.

Lỗi này rất dễ sót: `rect.left()` là toạ độ TUYỆT ĐỐI trên bảng, nên
`w = rect.width() - rect.left() - ...` ra số âm với mọi cột trừ cột 0.
Khi bảng chỉ có 2 cột thì cột 0 che giấu lỗi; thêm cột thứ 3 là lộ.

Chạy:  python test_delegate_width.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication

from ui.delegates import AccountCellDelegate

PASS, FAIL = 0, 0


def check(label, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  OK   {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label}\n        got  {got!r}\n        want {want!r}")


def main():
    app = QApplication.instance() or QApplication([])
    d = AccountCellDelegate()

    # Bề rộng cột thật của bảng 3 cột: A=520, B=420, C=952
    widths = [520, 420, 952]
    used = [54, 13, 13]        # tick+ô vuông | chấm tròn | chấm tròn

    print("\n=== 1. cot 0 (left=0) — toi truong hop co chay duoc ===")
    r = QRect(0, 0, 520, 14)
    x, w = d._text_area(r, 54)
    check("cot 0 x", x, 54)
    check("cot 0 w", w, 520 - 54 - 3)

    print("\n=== 2. cot 1 (left=520) — truoc day ra w am ===")
    r = QRect(520, 0, 420, 14)
    x, w = d._text_area(r, 13)
    check("cot 1 x", x, 533)
    check("cot 1 w > 0", w > 0, True)
    check("cot 1 w dung bang do rong con lai", w, 420 - 13 - 3)

    print("\n=== 3. cot 2 (left=940) ===")
    r = QRect(940, 0, 952, 14)
    x, w = d._text_area(r, 13)
    check("cot 2 x", x, 953)
    check("cot 2 w > 0", w > 0, True)
    check("cot 2 w dung", w, 952 - 13 - 3)

    print("\n=== 4. vung ve PHAI nam trong cot (khong tran sang cot sau) ===")
    left = 0
    for i, wd in enumerate(widths):
        r = QRect(left, 0, wd, 14)
        x, w = d._text_area(r, used[i])
        check(f"cot {i}: vung ve trong {left}..{left+wd}",
              (x >= left and x + w <= left + wd), True)
        left += wd

    print("\n=== 5. cot rat hep van phai ve duoc it chu ===")
    r = QRect(1500, 0, 20, 14)
    x, w = d._text_area(r, 13)
    check("w toi thieu 20", w, 20)
    check("khong am", w > 0, True)

    print("\n=== 6. ca hai mat do deu dung cung cong thuc ===")
    d2 = AccountCellDelegate(compact=False)
    for i, (left, wd) in enumerate(((0, 520), (520, 420), (940, 952))):
        r = QRect(left, 0, wd, 44)
        x, w = d2._text_area(r, used[i])
        check(f"che do cao, cot {i} w > 0", w > 0, True)
        check(f"che do cao, cot {i} w dung", w, wd - used[i] - 3)

    print(f"\n{'='*50}\n  {PASS} pass, {FAIL} fail\n{'='*50}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

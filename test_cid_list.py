"""Test phân tích danh sách cid — không cần GUI, không cần mạng.

Chạy:  python test_cid_list.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow

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
    win = MainWindow()
    p = MainWindow.parse_cids  # staticmethod, gọi không cần self

    print("\n=== 1. một cid mỗi dòng ===")
    check("1 dòng",
          p("7690897576899658504"),
          (["7690897576899658504"], []))
    check("3 dòng",
          p("7690897576899658504\n7654223771003994898\n7700000000000000001"),
          (["7690897576899658504", "7654223771003994898", "7700000000000000001"], []))

    print("\n=== 2. dấu phẩy / khoảng trắng / chấm phẩy / tab ===")
    check("phân tách bởi phẩy",
          p("1111111111111111111,2222222222222222222"),
          (["1111111111111111111", "2222222222222222222"], []))
    check("phân tách bởi khoảng trắng",
          p("1111111111111111111 2222222222222222222"),
          (["1111111111111111111", "2222222222222222222"], []))
    check("phân tách bởi chấm phẩy",
          p("1111111111111111111;2222222222222222222"),
          (["1111111111111111111", "2222222222222222222"], []))
    check("phân tách bởi tab",
          p("1111111111111111111\t2222222222222222222"),
          (["1111111111111111111", "2222222222222222222"], []))
    check("hỗn hợp + dòng trống",
          p("1111111111111111111,\n\n  2222222222222222222  ,,\n"),
          (["1111111111111111111", "2222222222222222222"], []))

    print("\n=== 3. dòng rác / ghi chú ===")
    check("dòng # là ghi chú",
          p("# danh sách cid\n1111111111111111111"),
          (["1111111111111111111"], []))
    check("chữ cái -> bỏ qua",
          p("1111111111111111111\nabc"),
          (["1111111111111111111"], ["abc"]))
    check("số quá ngắn -> bỏ qua",
          p("123\n1111111111111111111"),
          (["1111111111111111111"], ["123"]))
    check("số quá dài -> bỏ qua",
          p("1" * 30 + "\n1111111111111111111"),
          (["1111111111111111111"], ["1" * 30]))
    check("rỗng -> không có cid", p(""), ([], []))
    check("toàn rác -> không có cid", p("abc\nxyz"), ([], ["abc", "xyz"]))
    check("chỉ khoảng trắng", p("   \n\n  "), ([], []))

    print("\n=== 4. trùng lặp — giữ đúng thứ tự, chạy 1 lần ===")
    check("trùng nhau bị loại",
          p("1111111111111111111\n2222222222222222222\n1111111111111111111"),
          (["1111111111111111111", "2222222222222222222"], []))
    check("thứ tự giữ nguyên (không sort)",
          p("3333333333333333333\n1111111111111111111"),
          (["3333333333333333333", "1111111111111111111"], []))

    print("\n=== 5. giá trị mặc định của widget ===")
    win.in_cid.setPlainText("7690897576899658504\n7654223771003994898")
    check("cids() đọc từ ô nhập", win.cids(),
          ["7690897576899658504", "7654223771003994898"])
    win.in_cid.setPlainText("")
    check("ô trống -> danh sách rỗng", win.cids(), [])

    print("\n=== 6. hàng đợi chuyển cid ===")
    win.in_cid.setPlainText("1111111111111111111\n2222222222222222222")
    lst = win.cids()
    check("hàng đợi dựng đúng", lst,
          ["1111111111111111111", "2222222222222222222"])
    check("pos ban đầu = -1", win._cid_pos, -1)

    print(f"\n{'='*50}\n  {PASS} pass, {FAIL} fail\n{'='*50}")
    win.close()
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

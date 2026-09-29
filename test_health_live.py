"""Chạy thật bộ kiểm tra sức khoẻ trên tài khoản thật — sidecar thật, mạng thật.

Mục đích: xác minh phân loại HC_* hoạt động đúng ngoài đời, và xem TikTok
thực sự trả gì cho cookie tốt / cookie đã xoá phiên.

Chạy:  python test_health_live.py [so_acc]
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from core.health import HealthChecker
from core.models import HC_ALIVE, HC_DEAD, HC_EXPIRED, HC_RISKY, HC_UNKNOWN
from core.parser import load_accounts
from core.settings import AppSettings

N = int(sys.argv[1]) if len(sys.argv) > 1 else 3


def main():
    app = QApplication(sys.argv)
    QMessageBox.warning = staticmethod(
        lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.information = staticmethod(
        lambda *a, **k: QMessageBox.StandardButton.Ok)

    settings = AppSettings.load()
    accounts = load_accounts("cokie.tik.txt")[:N]

    # thêm 2 tài khoản giả để thấy phân loại "chết" / "hết hạn" chạy đúng
    import copy
    no_sess = copy.deepcopy(accounts[0])
    no_sess.id = "gia-thieu-phien"
    no_sess.username = "@gia-thieu-phien"
    no_sess.cookie = dict(accounts[0].cookie)
    no_sess.cookie.pop("sessionid_ss", None)
    no_sess.cookie.pop("sid_tt", None)
    all_list = list(accounts) + [no_sess]

    print(f"sidecar : {'OK' if __import__('core.signer', fromlist=['Signer']).Signer(settings.signer_url).is_ready() else 'KHONG'}")
    print(f"tai khoan: {len(all_list)}  "
          f"({len(accounts)} that + 1 tieu de phien)\n")

    checker = HealthChecker(settings)
    results = {}

    def applied(acc_id, health, note, at):
        results[acc_id] = (health, note)

    checker._on_applied = applied
    checker.start(all_list, use_proxy=False)

    loop = QEventLoop()
    checker.all_done.connect(loop.quit)
    t = QTimer()
    t.setSingleShot(True)
    t.timeout.connect(loop.quit)      # chặn treo
    t.start(120000)
    loop.exec()

    print(f"{'tai khoan':24} {'sức khoẻ':14} ghi chú")
    print("-" * 78)
    by_id = {a.id: a for a in all_list}
    for acc in all_list:
        h, note = results.get(acc.id, (HC_UNKNOWN, "(khong co ket qua)"))
        print(f"{acc.username:24} {h:14} {note[:46]}")

    print()
    n_alive = sum(1 for v in results.values() if v[0] == HC_ALIVE)
    n_dead = sum(1 for v in results.values() if v[0] == HC_DEAD)
    n_risk = sum(1 for v in results.values() if v[0] == HC_RISKY)
    print(f"sống {n_alive} · die {n_dead} · không rõ {n_risk}")
    if n_risk:
        print("→ TikTok đang chặn request từ IP này (10221). Đó KHÔNG phải "
              "cookie chết,\n  nên cột Status hiện 'không rõ' thay vì 'die' — "
              "đúng như thiết kế.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

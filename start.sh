#!/usr/bin/env bash
# Chạy ứng dụng — bản macOS / Linux (tương đương start.bat).
#
#   ./start.sh
#
set -uo pipefail
cd "$(dirname "$0")"

# ---- dùng .venv nếu có, không thì Python hệ thống ----
if [ -x ".venv/bin/python" ]; then
    PY=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PY="python3"
elif command -v python >/dev/null 2>&1; then
    PY="python"
else
    echo "[LỖI] Không tìm thấy Python. Hãy chạy ./install.sh trước."
    exit 1
fi

# ---- kiểm tra thư viện ----
if ! "$PY" -c "import PySide6, curl_cffi" >/dev/null 2>&1; then
    echo "[LỖI] Thiếu thư viện. Đang chạy ./install.sh ..."
    ./install.sh
    exit 0
fi

# ---- kiểm tra sidecar ký (chỉ cảnh báo, không chặn) ----
if ! "$PY" -c "import sys; from core.signer import Signer; sys.exit(0 if Signer().is_ready() else 1)" >/dev/null 2>&1; then
    echo "[CẢNH BÁO] Không kết nối được sidecar ký trên cổng 8080."
    echo "           Ứng dụng vẫn chạy, nhưng sẽ báo lỗi khi bấm CHẠY."
    echo "           Chạy ./signer.sh ở một cửa sổ terminal khác."
    sleep 4
fi

echo "Đang khởi động..."
exec "$PY" main.py

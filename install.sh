#!/usr/bin/env bash
# Cài thư viện Python — bản macOS / Linux (tương đương install.bat).
#
#   chmod +x install.sh && ./install.sh
#
set -euo pipefail
cd "$(dirname "$0")"

echo
echo "=========================================================="
echo "  CÀI ĐẶT THƯ VIỆN - TikTok Comment Manager"
echo "=========================================================="
echo

# ---- 1. Python ----
PY=""
for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
done
if [ -z "$PY" ]; then
    echo "[LỖI] Không tìm thấy Python."
    echo "  Cài Python 3.9+ : https://www.python.org/downloads/"
    echo "  macOS:  brew install python   (hoặc cài bản .pkg từ trang chủ)"
    exit 1
fi
echo "[1/4] Python: $($PY --version 2>&1)"

if ! "$PY" -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)"; then
    echo "[LỖI] Cần Python 3.9 trở lên."
    exit 1
fi

# ---- 2. môi trường ảo ----
if [ -x ".venv/bin/python" ]; then
    echo "[2/4] Đã có .venv, dùng luôn."
else
    echo "[2/4] Tạo môi trường ảo .venv ..."
    "$PY" -m venv .venv
fi
VPY=".venv/bin/python"

# ---- 3. nâng pip ----
echo "[3/4] Nâng cấp pip ..."
"$VPY" -m pip install --upgrade pip --quiet --disable-pip-version-check \
    || echo "  [Cảnh báo] Không nâng được pip, vẫn tiếp tục."

# ---- 4. thư viện ----
echo "[4/4] Cài thư viện từ requirements.txt ..."
# curl_cffi có sẵn wheel cho macOS arm64 (Apple Silicon) — không cần build.
if ! "$VPY" -m pip install -r requirements.txt --disable-pip-version-check; then
    echo
    echo "[LỖI] Cài đặt thất bại."
    echo "  Thử tay:  .venv/bin/python -m pip install -r requirements.txt"
    exit 1
fi

echo
echo "=========================================================="
echo "  CÀI ĐẶT THÀNH CÔNG"
echo "=========================================================="
echo
echo "  Chạy ứng dụng :  ./start.sh"
echo "  Cài sidecar ký :  ./signer.sh   (cần Node.js)"
echo
echo "  Gợi ý cho MacBook: bấm 'Dòng cao' ở thanh phân trang nếu"
echo "  muốn dòng 2 dòng dễ đọc hơn. Màn 14\" chỉ cao ~980px logic"
echo "  nên 50 dòng gọn sẽ phải cuộn."
echo

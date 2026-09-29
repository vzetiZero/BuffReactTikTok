#!/usr/bin/env bash
# Cài TikTok Comment Manager trong một lần — macOS / Linux.
#
#   chmod +x setup.sh && ./setup.sh
#
# Script này kiểm tra Python, kiểm tra Node.js, cài thư viện Python,
# cài sidecar ký + Chromium, rồi nhắc các bước còn lại.
set -uo pipefail
cd "$(dirname "$0")"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
warn() { printf '  \033[33m%s\033[0m\n' "$*"; }
die()  { printf '  \033[31m%s\033[0m\n' "$*"; }

say "============================================================"
say "  CÀI ĐẦY ĐỦ MỘT LẦN - TikTok Comment Manager"
say "============================================================"
printf '\n  Script này sẽ:\n'
printf '    1. Kiểm tra Python\n'
printf '    2. Kiểm tra Node.js          (bắt buộc)\n'
printf '    3. Cài thư viện Python\n'
printf '    4. Cài sidecar ký + Chromium  (bắt buộc, cần Internet)\n'
printf '    5. Kiểm tra file cookie\n'
printf '\n  Lưu ý: cần Internet ở bước 4. Tải Chromium mất vài phút.\n'
printf '\n'
read -r -p "Nhấn Enter để bắt đầu..." _

# ---- 1. Python ----
say "[1/5] Kiểm tra Python ..."
PY=""
for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
    die "[LỖI] Không tìm thấy Python."
    printf '\n  Cài Python 3.9+ : https://www.python.org/downloads/\n'
    printf '  macOS có thể dùng:  brew install python\n'
    exit 1
fi
if ! "$PY" -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)"; then
    die "[LỖI] Cần Python 3.9 trở lên."
    exit 1
fi
printf '        %s\n' "$("$PY" --version 2>&1)"

# ---- 2. Node.js ----
say "[2/5] Kiểm tra Node.js ..."
if ! command -v node >/dev/null 2>&1; then
    die "[LỖI] CHƯA CÀI NODE.JS."
    printf '\n  Node.js là BẮT BUỘC — sidecar ký chạy bằng Node.\n\n'
    printf '  macOS :  brew install node\n'
    printf '  hoặc tải bản .pkg LTS tại https://nodejs.org/\n\n'
    printf '  Sau khi cài, ĐÓNG rồi MỞ LẠI terminal rồi chạy lại script này.\n'
    exit 1
fi
printf '        node %s   npm %s\n' "$(node -v)" "$(npm -v 2>/dev/null || echo '?')"

# ---- 3. thư viện Python ----
say "[3/5] Cài thư viện Python ..."
if [ ! -x ".venv/bin/python" ]; then
    printf '        Tạo môi trường ảo .venv ...\n'
    "$PY" -m venv .venv || { die "[LỖI] Không tạo được .venv"; exit 1; }
fi
VPY=".venv/bin/python"
"$VPY" -m pip install --upgrade pip --quiet --disable-pip-version-check || true
if ! "$VPY" -m pip install -r requirements.txt --disable-pip-version-check; then
    die "[LỖI] Cài thư viện thất bại."
    printf '  Thử tay: .venv/bin/python -m pip install -r requirements.txt\n'
    exit 1
fi
printf '        OK\n'

# ---- 4. sidecar ký ----
say "[4/5] Cài sidecar ký + Chromium ..."
if [ ! -d "tiktok-signature/node_modules" ]; then
    chmod +x signer.sh 2>/dev/null || true
    ./signer.sh
    if [ ! -d "tiktok-signature/node_modules" ]; then
        die "[LỖI] Sidecar cài thất bại."
        exit 1
    fi
else
    warn "Đã có sẵn, bỏ qua (sidecar vẫn phải BẬT khi chạy app)."
fi

# ---- 5. file cookie ----
say "[5/5] Kiểm tra file cookie ..."
if [ ! -f "cokie.tik.txt" ]; then
    warn "Chưa có file cokie.tik.txt trong thư mục này."
    printf '\n  File này KHÔNG được git clone về — nó chứa cookie đăng nhập\n'
    printf '  (tương đương mật khẩu) nên cố chủ đình không đưa lên git.\n\n'
    printf '  Hãy copy file cookie của bạn vào đây, tên đúng: cokie.tik.txt\n'
    printf '  Định dạng: mỗi dòng 1 tài khoản, 8 trường tách bằng dấu |\n'
else
    printf '        Đã có cokie.tik.txt (~%s dòng)\n' "$(wc -l < cokie.tik.txt | tr -d ' ')"
fi

say "============================================================"
say "  CÀI XONG"
say "============================================================"
cat <<'EOF'

  BƯỚC TIẾP THEO:

  1. BẬT sidecar ký:  ./signer.sh
     (giữ cửa sổ terminal đó mở, chờ tới khi báo sẵn sàng)

  2. Mở app:          ./start.sh

  3. Trong app: bấm "Nạp cookie" → chọn cokie.tik.txt
     (lần sau app tự nhớ, không cần nạp lại)

  4. Bấm "Kiểm tra lại" ở thanh dưới — phải hiện "sidecar OK"

  5. Dán danh sách cid vào ô "Danh sách cid" ở tab "Tác vụ",
     tick tài khoản, đặt số luồng, bấm CHẠY.

EOF
read -r -p "Nhấn Enter để thoát..." _

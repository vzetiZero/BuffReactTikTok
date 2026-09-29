#!/usr/bin/env bash
# Sidecar ký TikTok — bản macOS / Linux (tương đương signer.bat).
#
#   chmod +x signer.sh && ./signer.sh
#
# Đây là tiến trình Node chạy RIÊNG, dùng để "ký" URL TikTok.
# App PySide gọi nó qua cổng 8080. GIỮ cửa sổ terminal này mở.
#
set -euo pipefail
cd "$(dirname "$0")"

DIR="$PWD/tiktok-signature"
PORT=8080
REPO="https://github.com/carcabot/tiktok-signature.git"

echo
echo "=========================================================="
echo "  SIDECAR KÝ REQUEST - tiktok-signature"
echo "=========================================================="
echo
echo "  Đây là tiến trình Node chạy riêng, dùng để ký URL TikTok."
echo "  App PySide sẽ gọi nó qua cổng $PORT."
echo

# ---- 0. đã chạy chưa? ----
if curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    echo "[OK] Sidecar đã chạy sẵn trên cổng $PORT."
else
    echo "[1/4] Chưa có gì trên cổng $PORT — cần cài đặt."
    echo

    # ---- 1. node / npm ----
    if ! command -v node >/dev/null 2>&1; then
        echo "[LỖI] Không tìm thấy Node.js."
        echo "  macOS : brew install node"
        echo "  hoặc tải bản .pkg tại https://nodejs.org/"
        exit 1
    fi
    if ! command -v npm >/dev/null 2>&1; then
        echo "[LỖI] Có node nhưng thiếu npm. Cài lại Node.js từ nodejs.org"
        exit 1
    fi
    echo "[1/4] node: $(node -v)   npm: $(npm -v)"

    # ---- 2. tải repo ----
    if [ -d "$DIR" ]; then
        echo "[2/4] Thư mục đã có, bỏ qua tải."
    else
        echo "[2/4] Tải tiktok-signature ..."
        if ! command -v git >/dev/null 2>&1; then
            echo "[LỖI] Cần Git để tải. Cài tại https://git-scm.com/"
            exit 1
        fi
        git clone --depth 1 "$REPO" "$DIR"
    fi

    # ---- 3. cài dependency + Chromium ----
    cd "$DIR"
    if [ ! -d "node_modules" ]; then
        echo "[3/4] Cài thư viện Node (một lần duy nhất, cần Internet) ..."
        npm install
    else
        echo "[3/4] Thư viện đã có, bỏ qua."
    fi

    # ---- 4. Chromium cho Puppeteer ----
    # QUAN TRỌNG (macOS): server.mjs của tiktok-signature trả về đường dẫn
    # CỨNG "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome".
    # Nếu máy không cài Google Chrome đúng chỗ đó, Puppeteer sẽ không tìm
    # được trình duyệt và sidecar không khởi động được. Vì vậy bước này tải
    # sẵn một bản Chrome của riêng Puppeteer rồi chỉ đường dẫn cho nó qua
    # biến PUPPETEER_EXECUTABLE_PATH (đây là biến mà server đọc ĐẦU TIÊN).
    echo "[4/4] Tải Chromium cho Puppeteer ..."
    npx --yes puppeteer browsers install chrome || \
        echo "  [Cảnh báo] Không tải được Chrome qua Puppeteer."

    if [ ! -f ".env" ] && [ -f ".env.example" ]; then
        cp .env.example .env
        echo "      Đã tạo .env từ .env.example"
    fi
fi

cd "$DIR"

# ---- trỏ Puppeteer về đúng bản Chrome đã tải ----
CHROME_PATH="$(node -e 'import("puppeteer").then(m=>console.log(m.default.executablePath()))' 2>/dev/null || true)"
if [ -n "$CHROME_PATH" ] && [ -x "$CHROME_PATH" ]; then
    export PUPPETEER_EXECUTABLE_PATH="$CHROME_PATH"
    echo
    echo "  Dùng trình duyệt: $CHROME_PATH"
elif [ -f "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]; then
    export PUPPETEER_EXECUTABLE_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    echo "  Dùng Google Chrome đã cài trên máy."
else
    echo
    echo "  [CẢNH BÁO] Không tìm thấy Chrome. Sidecar có thể không khởi động."
fi

echo
echo "=========================================================="
echo "  Khởi động sidecar trên cổng $PORT ..."
echo "  GIỮ cửa sổ terminal này mở. Ctrl+C để dừng."
echo "=========================================================="
echo
exec npm start

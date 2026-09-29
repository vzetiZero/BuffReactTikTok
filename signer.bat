@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
title Sidecar ky TikTok (tiktok-signature)

cd /d "%~dp0"
set "DIR=%CD%\tiktok-signature"
set "PORT=8080"
set "REPO=https://github.com/carcabot/tiktok-signature.git"

echo.
echo ==========================================================
echo   SIDECAR KY REQUEST  ·  tiktok-signature
echo ==========================================================
echo.
echo   Day la tien trinh Node chay rieng, dung de "ky" URL TikTok.
echo   App PySide se goi no qua cong %PORT%.
echo.

REM ---- 0. dang chay chua? ----
for /f "tokens=2" %%v in ('curl -s http://127.0.0.1:%PORT%/health 2^>nul') do set "H=%%v"
if not "%H%"=="" (
    echo [OK] Sidecar da chay san tren cong %PORT%.
    goto :open
)
echo [1/4] Chua co gi tren cong %PORT% - can cai dat.
echo.

REM ---- 1. tim npm (thuong di kem node) ----
set "NPM="
where npm >nul 2>&1 && set "NPM=npm"
if not defined NPM (
    if exist "C:\Program Files\nodejs\npm.cmd" set "NPM=C:\Program Files\nodejs\npm.cmd"
)
if not defined NPM (
    if exist "%APPDATA%\npm\npm.cmd" set "NPM=%APPDATA%\npm\npm.cmd"
)
if not defined NPM (
    echo [LOI] Khong tim thay npm.
    echo       Cai Node.js tai https://nodejs.org/  ^(co kem npm^)
    echo.
    pause
    exit /b 1
)
echo [1/4] npm: %NPM%

REM ---- 2. node co chua? ----
where node >nul 2>&1
if errorlevel 1 (
    echo [LOI] Khong tim thay Node.js. Cai tai https://nodejs.org/
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('node -v') do echo       node: %%v

REM ---- 3. tai repo ----
if exist "%DIR%" (
    echo [2/4] Thu muc da co, bo qua tai.
) else (
    echo [2/4] Tai tiktok-signature ...
    where git >nul 2>&1
    if errorlevel 1 (
        echo [LOI] Can Git de tai. Cai tai https://git-scm.com/
        pause
        exit /b 1
    )
    git clone --depth 1 "%REPO%" "%DIR%"
    if errorlevel 1 (
        echo [LOI] Tai that bai.
        pause
        exit /b 1
    )
)

REM ---- 4. cai dependency + chromium ----
pushd "%DIR%"
if not exist "node_modules" (
    echo [3/4] Cai thu vien Node (mot lan duy nhat, can Internet) ...
    "%NPM%" install
    if errorlevel 1 ( popd & echo [LOI] npm install that bai. & pause & exit /b 1 )
) else (
    echo [3/4] Thu vien da co, bo qua.
)

REM ---- 4. Chromium cho Puppeteer ----
REM server.mjs CHI doc PUPPETEER_EXECUTABLE_PATH truoc, roi moi thu tu tim
REM theo mac dinh. Tren macOS no tra ve duong dan CUNG
REM "/Applications/Google Chrome.app/..." — neu may khong cai Chrome o
REM dung cho do, sidecar se KHONG khoi dong duoc. Tai san mot ban Chrome
REM cua Puppeteer va chi danh dung ban do.
echo [4/4] Tai Chromium cho Puppeteer ...
"%NPM%" exec --yes puppeteer browsers install chrome
if not exist ".env" if exist ".env.example" (
    copy ".env.example" ".env" >nul
    echo       Da tao .env tu .env.example
)
popd

:open
cd /d "%DIR%"

REM ---- tro Puppeteer ve dung ban Chrome da tai ----
for /f "usebackq delims=" %%p in (`node -e "import('puppeteer').then(m=>console.log(m.default.executablePath()))" 2^>nul`) do set "CHROME_PATH=%%p"
if defined CHROME_PATH (
    if exist "!CHROME_PATH!" (
        set "PUPPETEER_EXECUTABLE_PATH=!CHROME_PATH!"
        echo   Dung trinh duyet: !CHROME_PATH!
    )
)
echo.
echo ==========================================================
echo   Khoi dong sidecar tren cong %PORT%...
echo   GIU cua so nay mo. Bam Ctrl+C de dung.
echo ==========================================================
echo.
"%NPM%" start
endlocal

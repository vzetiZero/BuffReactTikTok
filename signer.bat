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
echo   SIDECAR KY REQUEST  -  tiktok-signature
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
REM PHAI lay npm.cmd, KHONG PHAI "npm". Tren may co cai "npm" khong duoi
REM la script bash cho cygwin/mingw; goi no se bao MODULE_NOT_FOUND.
REM Do la file .bat nen dung duong dan day du + dau nhay cho an toan.
set "NPM="
for /f "usebackq delims=" %%f in (`where npm.cmd 2^>nul`) do (
    if not defined NPM set "NPM=%%f"
)
if not defined NPM (
    if exist "C:\Program Files\nodejs\npm.cmd" set "NPM=C:\Program Files\nodejs\npm.cmd"
)
if not defined NPM (
    if exist "%APPDATA%\npm\npm.cmd" set "NPM=%APPDATA%\npm\npm.cmd"
)
if not defined NPM set "NPM=npm"
if not defined NPM (
    echo [LOI] Khong tim thay npm.
    echo       Cai Node.js tai https://nodejs.org/  ^(co kem npm^)
    echo.
    pause
    exit /b 1
)
for %%n in ("%NPM%") do echo [1/4] npm: %%~nfn

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
    echo [3/4] Cai thu vien Node ^(mot lan duy nhat, can Internet^) ...
    cmd /c ""%NPM%" install"
    if errorlevel 1 ( popd & echo [LOI] npm install that bai. & pause & exit /b 1 )
) else (
    echo [3/4] Thu vien da co, bo qua.
)

REM ---- 4. Chromium cho Puppeteer ----
REM server.mjs CHI doc PUPPETEER_EXECUTABLE_PATH truoc, roi moi thu tu tim
REM theo mac dinh. Tren macOS no tra ve duong dan CUNG
REM "/Applications/Google Chrome.app/..." - neu may khong cai Chrome o
REM dung cho do, sidecar se KHONG khoi dong duoc. Tai san mot ban Chrome
REM cua Puppeteer va chi danh dung ban do.
echo [4/4] Tai Chromium cho Puppeteer ...
REM PHAI chay qua "cmd /c" + "< nul".
REM - npm.cmd la file .bat, KHONG phai .exe: no bam stdin cua chinh no
REM   va nuot mat cac dong con lai cua signer.bat -> script im lang
REM   dung ngay sau dong [4/4], sidecar khong bao gio khoi dong.
REM - "< nul" de npm khong cho nhap lieu.
cmd /c ""%NPM%" exec --yes puppeteer browsers install chrome < nul"
if not exist ".env" if exist ".env.example" (
    copy ".env.example" ".env" >nul
    echo       Da tao .env tu .env.example
)
popd

:open
cd /d "%DIR%"

REM ---- tro Puppeteer ve dung ban Chrome da tai ----
REM KHONG ghi truc tiep node -e "...(ngoac)..." vao for /f: danh nhay
REM long cung dau nhay voi dau backtick se lam cmd bao loi
REM '""' is not recognized. Ghi script ra file roi doc ket qua.
set "PROBE=%TEMP%\pptr_path.cjs"
> "%PROBE%" echo try { const p = require('puppeteer'); process.stdout.write(p.executablePath()); } catch (e) { }
node "%PROBE%" > "%TEMP%\pptr_path.txt" 2>nul
set "CHROME_PATH="
if exist "%TEMP%\pptr_path.txt" set /p CHROME_PATH=<"%TEMP%\pptr_path.txt"
if defined CHROME_PATH (
    if exist "!CHROME_PATH!" (
        set "PUPPETEER_EXECUTABLE_PATH=!CHROME_PATH!"
        echo   Dung trinh duyet: !CHROME_PATH!
    )
)
del "%PROBE%" "%TEMP%\pptr_path.txt" >nul 2>&1
echo.
echo ==========================================================
echo   Khoi dong sidecar tren cong %PORT%...
echo   GIU cua so nay mo. Bam Ctrl+C de dung.
echo ==========================================================
echo.
"%NPM%" start
endlocal

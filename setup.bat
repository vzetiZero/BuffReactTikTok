@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
title Cai TikTok Comment Manager - tu dong

cd /d "%~dp0"

echo.
echo ==============================================================
echo   CAI DAY DU MOT LAN - TikTok Comment Manager
echo ==============================================================
echo.
echo   Script nay se:
echo     1. Kiem tra Python
echo     2. Kiem tra Node.js          (bat buoc)
echo     3. Cai thu vien Python
echo     4. Cai sidecar ky + Chromium  (bat buoc, can Internet)
echo     5. Kiem tra file cookie
echo.
echo   Luu y: can Internet o buoc 2 va 4.
echo   Dien tich trong buoc 4 mat vai phut.
echo.
pause

REM ---- 1. Python ----
echo.
echo [1/5] Kiem tra Python ...
set "PY="
for %%c in (python py) do (
    if not defined PY (
        %%c --version >nul 2>&1 && set "PY=%%c"
    )
)
if not defined PY (
    echo   [LOI] Khong tim thay Python.
    echo.
    echo   Cai Python 3.9+ tai https://www.python.org/downloads/
    echo   NHO chon "Add Python to PATH" khi cai.
    echo.
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('%PY% --version 2^>^&1') do echo        %%v
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)"
if errorlevel 1 (
    echo   [LOI] Can Python 3.9 tro len.
    pause
    exit /b 1
)

REM ---- 2. Node.js ----
echo.
echo [2/5] Kiem tra Node.js ...
where node >nul 2>&1
if errorlevel 1 (
    echo   [LOI] CHUA CAI NODE.JS.
    echo.
    echo   Node.js la BAT BUOC - sidecar ky chay bang Node.
    echo.
    echo   1. Mo https://nodejs.org/
    echo   2. Tai ban .msi ban LTS ^(Node 18 tro len^)
    echo   3. Cai dat mac dinh
    echo   4. DONG moi cua so cmd nay, mo lai roi chay lai script nay
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('node -v') do echo        node %%v

REM ---- 3. thu vien Python ----
echo.
echo [3/5] Cai thu vien Python ...
if not exist ".venv\Scripts\python.exe" (
    echo        Tao moi truong ao .venv ...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo   [LOI] Khong tao duoc .venv
        pause
        exit /b 1
    )
)
set "VPY=.venv\Scripts\python.exe"
"%VPY%" -m pip install --upgrade pip --quiet --disable-pip-version-check
"%VPY%" -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 (
    echo   [LOI] Cai thu vien that bai.
    echo   Thu: .venv\Scripts\python -m pip install -r requirements.txt
    pause
    exit /b 1
)
echo        OK

REM ---- 4. sidecar ky ----
echo.
echo [4/5] Cai sidecar ky + Chromium ...
if not exist "tiktok-signature\node_modules" (
    call signer.bat
    if errorlevel 1 (
        echo   [LOI] Sidecar cai that bai.
        pause
        exit /b 1
    )
) else (
    echo        Da co san, bo qua ^(sidecar van phai BAT khi chay app^).
)

REM ---- 5. file cookie ----
echo.
echo [5/5] Kiem tra file cookie ...
if not exist "cokie.tik.txt" (
    echo   [CANH BAO] Chua co file cokie.tik.txt trong thu muc nay.
    echo.
    echo   File nay KHONG duoc git clone ve - no chua cookie dang nhap
    echo   (tuong duong mat khau) nen co chu dinh de khong lot ra cong
    echo   khai bao.
    echo.
    echo   Hay copy file cookie cua ban vao day, ten dung: cokie.tik.txt
    echo   Dinh dang: moi dong 1 tai khoan, 8 truong tach bang dau |
    echo.
) else (
    for /f %%n in ('type cokie.tik.txt ^| find /c /v ""') do set "NLINES=%%n"
    echo        Da co cokie.tik.txt ^(~!NLINES! dong^)
)

echo.
echo ==============================================================
echo   CAI XONG
echo ==============================================================
echo.
echo   BUOC TIEP THEO:
echo.
echo   1. BAT sidecar ky: bam dup  signer.bat
echo      ^(GUI cua so den lai o lai cho den khi no bao sanh^)
echo.
echo   2. Mo app: chay  start.bat
echo.
echo   3. Trong app: bam "Nap cookie" - chon cokie.tik.txt
echo      ^(lan sau app tu nho, khong can nap lai^)
echo.
echo   4. Bam "Kiem tra lai" o thanh duoi - phai hien "sidecar OK"
echo.
echo   5. Dan danh sach cid vao o "Danh sach cid" o tab "Tac vu",
echo      tick tai khoan, dat so luong, bam CHAY.
echo.
pause
endlocal

@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
title Cai dat TikTok Comment Manager

cd /d "%~dp0"

echo.
echo ==========================================================
echo   CAI DAT THU VIEN - TikTok Comment Manager
echo ==========================================================
echo.

REM ---- 1. Python ----
where python >nul 2>&1
if errorlevel 1 (
    echo [LOI] Khong tim thay Python.
    echo.
    echo   Cai Python 3.10+ tai: https://www.python.org/downloads/
    echo   NHO TICH "Add Python to PATH" khi cai.
    echo.
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo [1/4] Python: !PYVER!

python -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)"
if errorlevel 1 (
    echo [LOI] Can Python 3.9 tro len. Ban co !PYVER!
    pause
    exit /b 1
)

REM ---- 2. Tao moi truong ao (khong bat buoc) ----
if exist ".venv\Scripts\python.exe" goto :run_install

echo [2/4] Tao moi truong ao .venv ...
python -m venv .venv
if errorlevel 1 (
    echo [LOI] Khong tao duoc .venv
    pause
    exit /b 1
)

:run_install
set "PY=.venv\Scripts\python.exe"

REM ---- 3. Nang cap pip ----
echo [3/4] Nang cap pip ...
"%PY%" -m pip install --upgrade pip --quiet --disable-pip-version-check
if errorlevel 1 (
    echo [CAnh bao] Khong nang cap duoc pip, van tiep tuc.
)

REM ---- 4. Cai thu vien ----
echo [4/4] Cai thu vien tu requirements.txt ...
"%PY%" -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 (
    echo.
    echo [LOI] Cai dat that bai.
    echo   Thu cai thu cong:  .venv\Scripts\python -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

echo.
echo ==========================================================
echo   CAI DAT THANH CONG
echo ==========================================================
echo.
echo   Chay ung dung bang:  start.bat
echo.
echo   Luu y: TikTok yeu cau mot "sidecar ky" chay rieng.
echo   Doc README.md muc "Can sidecar ky request" de cai Node.
echo.
pause
endlocal

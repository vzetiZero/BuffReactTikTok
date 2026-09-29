@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul 2>&1
title TikTok Comment Manager

cd /d "%~dp0"

REM ---- dung .venv neu co, neu khong thi dung python he thong ----
if exist ".venv\Scripts\pythonw.exe" (
    set "PY=.venv\Scripts\pythonw.exe"
    set "PYC=.venv\Scripts\python.exe"
) else (
    where pythonw >nul 2>&1
    if errorlevel 1 (
        echo [LOI] Khong tim thay Python. Hay chay install.bat truoc.
        pause
        exit /b 1
    )
    set "PY=pythonw.exe"
    set "PYC=python"
)

REM ---- kiem tra thu vien da dung chua ----
"%PYC%" -c "import PySide6, curl_cffi, requests" >nul 2>&1
if errorlevel 1 (
    echo [LOI] Thieu thu vien. Dang chay install.bat ...
    echo.
    call install.bat
    exit /b 0
)

REM ---- kiem tra sidecar ky (khong chan, chi canh bao) ----
"%PYC%" -c "import sys; from core.signer import Signer; sys.exit(0 if Signer().is_ready() else 1)" >nul 2>&1
if errorlevel 1 (
    echo [CANH BAO] Khong ket noi duoc sidecar ky tren cong 8080.
    echo            Ung dung van chay duoc, nhung se bao loi khi bam CHAY.
    echo            Xem README.md - muc "Can sidecar ky request".
    echo.
    timeout /t 4 >nul
)

echo Dang khoi dong...
start "" "%PY%" main.py
endlocal

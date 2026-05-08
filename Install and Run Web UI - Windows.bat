@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title LuckyD Code - Web UI
cd /d "%~dp0"

cls
echo.
echo   LuckyD Code - Web UI
echo   ---------------------------------------------
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo   [ERROR] Python not found. Run the main launcher first.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\activate.bat" (
    echo   [INFO] Running first-time setup...
    call "Install and Run - Windows.bat"
    exit /b
)

call .venv\Scripts\activate.bat >nul 2>&1

if not exist ".env" (
    echo   [ERROR] No .env file found. Run the main launcher first to set up your API key.
    pause
    exit /b 1
)

echo   Starting Web UI at http://localhost:8000
echo   Opening browser in 3 seconds...
echo   Press Ctrl+C to stop the server.
echo.

REM Open browser after a short delay (runs in background)
start /b cmd /c "timeout /t 3 /nobreak >nul && start "" http://localhost:8000"

REM Run server in foreground so Ctrl+C stops it cleanly
python main.py --web --host 127.0.0.1

echo.
echo   Web UI stopped. Press any key to close.
pause >nul
endlocal

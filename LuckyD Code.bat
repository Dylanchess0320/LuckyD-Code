@echo off
title LuckyD Code
cd /d "%~dp0"

REM Force UTF-8 code page so Unicode box-drawing & Rich output work
chcp 65001 >nul 2>&1

REM Activate virtual environment
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat >nul
)

cls
echo.
echo   +==========================================+
echo   |          LuckyD Code  v1.2.2            |
echo   |    AI Coding Assistant                  |
echo   +==========================================+
echo.
echo   Commands:
echo     luckyD         - Launch REPL (terminal)
echo     luckyD --web   - Launch Web UI
echo     luckyD --help  - See all options
echo.
echo   Starting REPL...
echo.

python main.py %*

echo.
echo   Done. Press any key to exit.
pause >nul

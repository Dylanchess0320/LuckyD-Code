@echo off
setlocal EnableDelayedExpansion
title LuckyD Code
cd /d "%~dp0.."

REM Force UTF-8 code page so Unicode box-drawing & Rich output work
chcp 65001 >nul 2>&1

cls
echo.
echo   ================================================
echo    LuckyD Code  v1.3.4
echo    AI coding assistant powered by DeepSeek API
echo   ================================================
echo.

REM --- Python check ---
python --version >nul 2>&1
if errorlevel 1 (
    echo   [ERROR] Python not found.
    echo           Download from https://python.org
    echo           Make sure to check "Add Python to PATH" during install.
    echo.
    pause
    exit /b 1
)

REM --- Create venv if missing ---
if not exist ".venv\Scripts\activate.bat" (
    echo   [1/3] Creating virtual environment...
    python -m venv .venv
)

call .venv\Scripts\activate.bat >nul 2>&1

REM --- Desktop launcher (created once) ---
for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do set "DESKTOP_DIR=%%D"
if not exist "%DESKTOP_DIR%\LuckyD Code.bat" (
    (
        echo @echo off
        echo cd /d "%~dp0"
        echo call "%~dp0Install and Run - Windows.bat"
    ) > "%DESKTOP_DIR%\LuckyD Code.bat"
    echo   Desktop launcher created on Desktop.
)

REM --- Marker-file check: skip pip on repeat launches ---
set NEEDS_INSTALL=0
if not exist ".venv\.last_install" set NEEDS_INSTALL=1
if exist "pyproject.toml" if exist ".venv\.last_install" (
    for /f %%A in ('powershell -NoProfile -Command "(Get-Item pyproject.toml).LastWriteTime -gt (Get-Item .venv\.last_install).LastWriteTime"') do (
        if /i "%%A"=="True" set NEEDS_INSTALL=1
    )
)

if "%NEEDS_INSTALL%"=="1" (
    echo   [2/3] Installing dependencies ^(first run or update, ~1 min^)...
    echo         Upgrading pip...
    python -m pip install --upgrade pip >nul 2>&1
    echo         Installing packages...
    pip install -e .
    if errorlevel 1 (
        echo.
        echo   [ERROR] Installation failed. See error above.
        echo          Common fixes:
        echo          - Check your internet connection
        echo          - If you see "error: Microsoft Visual C++", install:
        echo            https://visualstudio.microsoft.com/visual-cpp-build-tools/
        echo          - For tiktoken/aiofiles: try "pip install tiktoken aiofiles" first
        echo            or use pre-built wheels from https://pypi.org
        echo          - Make sure Python 3.10+ is installed
        pause
        exit /b 1
    )
    pip install "pytest-asyncio>=0.21.0" >nul 2>&1
    type nul > ".venv\.last_install"
    echo   [2/3] Done.
)

REM --- Optional extras (browser, RAG, game gen) - only install once ---
if not exist ".venv\.last_optional_install" (
    pip install -e ".[browser,rag,game]" >nul 2>&1
    type nul > ".venv\.last_optional_install"
    pip show playwright >nul 2>&1
    if not errorlevel 1 (
        echo         Installing Chromium browser for Playwright ^(~150 MB^)...
        .venv\Scripts\playwright install chromium >nul 2>&1
    )
)

REM --- .env setup ---
if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
    ) else (
        echo DEEPSEEK_API_KEY=sk-your-deepseek-key-here > .env
    )
    echo.
    echo   [3/3] No API key found.
    echo         Get a free key at: https://platform.deepseek.com/api_keys
    echo.
    set /p "USER_KEY=  Paste your DeepSeek API key here (starts with sk-): "
    if not "!USER_KEY!"=="" (
        powershell -NoProfile -Command "(Get-Content .env) -replace 'DEEPSEEK_API_KEY=.*', ('DEEPSEEK_API_KEY=' + '!USER_KEY!') | Set-Content .env"
        echo   API key saved.
    )
)

REM --- API key check ---
set KEY_OK=0
for /f "tokens=1,* delims==" %%a in (.env) do (
    if /i "%%a"=="DEEPSEEK_API_KEY" (
        if not "%%b"=="" (
            echo %%b | findstr /c:"your-key" >nul 2>&1
            if errorlevel 1 set KEY_OK=1
        )
    )
)
if "%KEY_OK%"=="0" (
    echo   [WARN] No API key detected in .env
    echo          Edit .env and set: DEEPSEEK_API_KEY=sk-xxxxxxxxxx
    echo          Get a key at: https://platform.deepseek.com/api_keys
    echo.
    pause
)

REM --- Launch ---
cls
python main.py %*

echo.
echo   Session ended. Press any key to close.
pause >nul
endlocal

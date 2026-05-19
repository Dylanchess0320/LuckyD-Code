@echo off
setlocal EnableDelayedExpansion
title LuckyD Code
cd /d "%~dp0.."
chcp 65001 >nul 2>&1

cls
echo.
echo   ================================================
echo    LuckyD Code  v1.3.4
echo    AI coding assistant powered by DeepSeek API
echo   ================================================
echo.

REM -------------------------------------------------------
REM  Pre-flight checks
REM -------------------------------------------------------
echo   Checking prerequisites...
echo.

python --version >nul 2>&1
if errorlevel 1 goto :no_python
for /f "tokens=2" %%v in ('python --version 2^>^&1') do echo   [OK] Python %%v
goto :check_pip

:no_python
echo   [X] Python not found.
echo       Download from https://python.org
echo       Check "Add Python to PATH" during install.
echo.
pause
exit /b 1

:check_pip
pip --version >nul 2>&1
if not errorlevel 1 (
    echo   [OK] pip
) else (
    echo   [!!] pip missing - run: python -m ensurepip
)

git --version >nul 2>&1
if not errorlevel 1 (
    echo   [OK] Git
) else (
    echo   [--] Git not found (optional)
)
echo.

REM -------------------------------------------------------
REM  Mode selection
REM -------------------------------------------------------
set LAUNCH_CLI=0
set LAUNCH_WEB=0

if /i "%~1"=="--web"  set LAUNCH_WEB=1
if /i "%~1"=="-w"     set LAUNCH_WEB=1
if /i "%~1"=="--both" goto :set_both
if /i "%~1"=="-b"     goto :set_both

if "%LAUNCH_WEB%"=="1" goto :install
if "%LAUNCH_CLI%"=="1" goto :install

echo   Which mode would you like?
echo.
echo     [1]  Terminal CLI   (recommended)
echo     [2]  Web UI         (browser at localhost:8000)
echo     [3]  Both
echo.
set /p "CHOICE=  Your choice [1]: "
if "%CHOICE%"=="" set CHOICE=1
if "%CHOICE%"=="1" goto :mode_cli
if "%CHOICE%"=="2" goto :mode_web
if "%CHOICE%"=="3" goto :set_both
goto :mode_cli

:set_both
set LAUNCH_CLI=1
set LAUNCH_WEB=1
goto :install

:mode_cli
set LAUNCH_CLI=1
goto :install

:mode_web
set LAUNCH_WEB=1
goto :install

:install
echo.

REM -------------------------------------------------------
REM  Create venv if missing
REM -------------------------------------------------------
if exist ".venv\Scripts\activate.bat" goto :venv_done
echo   [1/3] Creating virtual environment...
python -m venv .venv
if errorlevel 1 (
    echo.
    echo   [X] Failed to create virtual environment.
    pause
    exit /b 1
)

:venv_done
call .venv\Scripts\activate.bat >nul 2>&1

REM -------------------------------------------------------
REM  Desktop launcher (created once)
REM -------------------------------------------------------
for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do set "DESKTOP_DIR=%%D"
if not exist "%DESKTOP_DIR%\LuckyD Code.bat" (
    echo @echo off > "%DESKTOP_DIR%\LuckyD Code.bat"
    echo cd /d "%~dp0" >> "%DESKTOP_DIR%\LuckyD Code.bat"
    echo call "%~dp0Install and Run - Windows.bat" >> "%DESKTOP_DIR%\LuckyD Code.bat"
    echo   Desktop launcher created.
)

REM -------------------------------------------------------
REM  Check if install is needed
REM -------------------------------------------------------
set NEEDS_INSTALL=0

if not exist ".venv\.last_install" (
    set NEEDS_INSTALL=1
    goto :check_install_done
)

if not exist "pyproject.toml" goto :check_install_done

for /f %%A in ('powershell -NoProfile -Command "(Get-Item pyproject.toml).LastWriteTime -gt (Get-Item .venv\.last_install).LastWriteTime"') do set NEWER=%%A
if /i "%NEWER%"=="True" set NEEDS_INSTALL=1

:check_install_done

if "%NEEDS_INSTALL%"=="0" goto :install_done

echo   [2/3] Installing dependencies (first run or update, ~1 min)...
echo         Upgrading pip...
python -m pip install --upgrade pip >nul 2>&1
echo         Installing packages...
pip install -e .
if errorlevel 1 (
    echo.
    echo   [X] Installation failed. See the error above.
    echo.
    echo       Common fixes:
    echo         - Check your internet connection
    echo         - Missing C++ build tools -- install from:
    echo           https://visualstudio.microsoft.com/visual-cpp-build-tools/
    echo         - Try manually: pip install tiktoken aiofiles
    echo         - Open an issue:
    echo           https://github.com/luckydcode/luckyd-code/issues
    echo.
    pause
    exit /b 1
)
pip install "pytest-asyncio>=0.21.0" >nul 2>&1
type nul > ".venv\.last_install"
echo   [2/3] Done.

:install_done

REM -------------------------------------------------------
REM  Optional extras (browser, RAG, game) - only once
REM -------------------------------------------------------
if exist ".venv\.last_optional_install" goto :optional_done
pip install -e ".[browser,rag,game]" >nul 2>&1
type nul > ".venv\.last_optional_install"
pip show playwright >nul 2>&1
if not errorlevel 1 (
    echo         Installing Chromium for Playwright (~150 MB)...
    .venv\Scripts\playwright install chromium >nul 2>&1
)
:optional_done

REM -------------------------------------------------------
REM  .env / API key setup
REM -------------------------------------------------------
if exist ".env" goto :env_check

if exist ".env.example" (
    copy ".env.example" ".env" >nul
) else (
    echo DEEPSEEK_API_KEY=sk-your-deepseek-key-here > .env
)
echo.
echo   [3/3] No API key found.
echo         Get a free key at: https://platform.deepseek.com/api_keys
echo.
set /p "USER_KEY=  Paste your DeepSeek API key (starts with sk-): "
if "%USER_KEY%"=="" goto :env_check
powershell -NoProfile -Command "(Get-Content .env) -replace 'DEEPSEEK_API_KEY=.*', ('DEEPSEEK_API_KEY=' + '%USER_KEY%') | Set-Content .env"
echo   API key saved.

:env_check
set KEY_OK=0
for /f "tokens=1,* delims==" %%a in (.env) do (
    if /i "%%a"=="DEEPSEEK_API_KEY" (
        if not "%%b"=="" (
            echo %%b | findstr /c:"your-key" >nul 2>&1
            if errorlevel 1 set KEY_OK=1
        )
    )
)
if "%KEY_OK%"=="1" goto :key_ok
echo.
echo   [!] No API key detected in .env
echo       Edit .env and set DEEPSEEK_API_KEY=sk-xxxxxxxxxx
echo       Get a key at: https://platform.deepseek.com/api_keys
echo.
pause

:key_ok

REM -------------------------------------------------------
REM  Success card (first install only)
REM -------------------------------------------------------
if "%NEEDS_INSTALL%"=="0" goto :launch

echo.
echo   +--------------------------------------------------+
echo   ^|  LuckyD Code v1.3.4 installed successfully!    ^|
echo   ^|                                                  ^|
echo   ^|  Double-click this script to pick a mode       ^|
echo   ^|  Or run with: --web   (Web UI)                 ^|
echo   ^|               --both  (Web UI + CLI)           ^|
echo   ^|                                                  ^|
echo   ^|  Tip: type /help inside the CLI                ^|
echo   +--------------------------------------------------+
echo.
timeout /t 4 /nobreak >nul 2>&1

:launch
cls

REM -------------------------------------------------------
REM  Launch
REM -------------------------------------------------------
if "%LAUNCH_CLI%"=="1" goto :check_both
if "%LAUNCH_WEB%"=="1" goto :do_web
python main.py %*
goto :done

:check_both
if "%LAUNCH_WEB%"=="1" goto :do_both

REM  CLI only
python main.py
goto :done

:do_both
echo   Opening Web UI in a new window...
start "LuckyD Code - Web UI" cmd /k ""%~f0" --web"
echo   Launching CLI...
echo.
python main.py
goto :done

:do_web
echo   Starting Web UI at http://localhost:8000
echo   Opening browser in 3 seconds...
echo   Press Ctrl+C to stop.
echo.
start /b cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:8000"
python main.py --web --host 127.0.0.1
goto :done

:done
echo.
echo   Session ended. Press any key to close.
pause >nul
endlocal

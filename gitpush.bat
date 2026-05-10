@echo off
title LuckyD Code - Git Push
cd /d "%~dp0"

REM ── Default commit message ──
set "MSG=%~1"
if "%MSG%"=="" set "MSG=update"

echo.
echo   ╔══════════════════════════════════════════╗
echo   ║       LuckyD Code - Git Push             ║
echo   ╚══════════════════════════════════════════╝
echo.

echo   [1/3] Staging all changes...
git add -A
if %errorlevel% neq 0 (
    echo   ERROR: git add failed
    pause >nul
    exit /b 1
)

echo   [2/3] Committing: "%MSG%"
git commit -m "%MSG%"
if %errorlevel% neq 0 (
    echo   Nothing to commit, or commit failed.
)

echo   [3/3] Pushing to origin/main...
git push origin main
if %errorlevel% neq 0 (
    echo   ERROR: git push failed
    echo   Try: git pull --rebase origin main
    pause >nul
    exit /b 1
)

echo.
echo   Done - pushed successfully!
echo.
pause >nul

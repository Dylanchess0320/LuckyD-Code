@echo off
title LuckyD Code — Coverage Runner
cd /d "C:\Users\dylan\Desktop\LuckyD Code"

:: ── Activate venv ────────────────────────────────────────────────────────────
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
) else (
    echo [WARN] No virtualenv found, using system Python.
)

:: ── Install ALL dependencies (app + test) ────────────────────────────────────
echo Installing all dependencies from requirements.txt...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt
if errorlevel 1 (
    echo [ERROR] pip install failed.
    pause
    exit /b 1
)
echo Dependencies OK.
echo.

:: ── Run ONLY the new gap tests first (quick smoke check) ─────────────────────
echo ============================================================
echo  Step 1 of 2 — New gap tests (gaps_1 / gaps_2 / gaps_3 / gaps_final)
echo ============================================================
python -m pytest ^
    tests/test_coverage_gaps_1.py ^
    tests/test_coverage_gaps_2.py ^
    tests/test_coverage_gaps_3.py ^
    tests/test_coverage_gaps_final.py ^
    -v --tb=short --no-cov
echo.

:: ── Full suite with coverage ──────────────────────────────────────────────────
echo ============================================================
echo  Step 2 of 2 — Full suite + coverage report
echo ============================================================
python -m pytest --cov=luckyd_code --cov-report=term-missing --cov-report=html -q --tb=line
echo.
echo Done. Open htmlcov\index.html to see the updated report.
pause

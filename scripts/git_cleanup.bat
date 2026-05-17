@echo off
REM Run this script once to clean up junk files from git tracking and disk.
REM After running, commit the result.

REM Remove Windows NUL device artifact from git tracking
REM 'nul' is a reserved device name in cmd.exe so del won't work on it directly.
REM We must use the \\?\ long-path prefix to bypass the device-name reservation.
git rm --cached nul 2>nul
cmd /c "del /f /q "\\.\%CD%\nul" 2>nul"
powershell -NoProfile -Command "Remove-Item -LiteralPath '.\nul' -Force -ErrorAction SilentlyContinue"

REM Remove old test file (renamed to test_router_context_analytics_sandbox.py)
git rm --cached tests\test_coverage_final_push.py 2>nul
del /f /q tests\test_coverage_final_push.py 2>nul

REM Remove generated/temp files from git tracking
git rm --cached ceiling_run.txt 2>nul
git rm --cached cov_out.txt 2>nul
git rm --cached _del_nul.py 2>nul
git rm --cached gitpush.bat 2>nul

echo.
echo Done. Review with: git status
echo Then commit: git commit -m "chore: remove OS artifacts and rename test file"

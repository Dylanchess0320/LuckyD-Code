@echo off
cd /d "%~dp0"
echo ============================================
echo   Git Push - LuckyD Code
echo   Target: github.com/Dylanchess0320/LuckyD-Code
echo ============================================
echo.
set /p COMMIT_MSG="Enter commit message: "
echo.
echo Adding all changes...
git add .
echo Committing...
git commit -m "%COMMIT_MSG%"
echo.
echo Pushing to GitHub...
git push origin main
echo.
echo Done!
pause

@echo off
rem ============================================================
rem  Fabio Decision Gym V4 - one-click launcher
rem  Double-click this file to start V4 API + frontend.
rem  Optional args: -DataRoot "D:\path" -EventDb "D:\path" -SkipInstall
rem ============================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\start-decision-gym.ps1" %*
set "EXITCODE=%ERRORLEVEL%"
echo.
echo Program exited (exit code: %EXITCODE%)
pause
exit /b %EXITCODE%

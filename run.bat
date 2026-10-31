@echo off
setlocal
cd /d "%~dp0"

rem The bootstrap handles: locate directory, find/install Python, create venv,
rem install dependencies, self-check, then launch the app.
chcp 65001 >nul
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass ^
  -File "%~dp0bootstrap.ps1" %*

if errorlevel 1 (
  echo.
  echo SnapAnswer failed to start. See the error above.
  pause
)
endlocal

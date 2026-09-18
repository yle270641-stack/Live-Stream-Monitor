@echo off
setlocal
cd /d "%~dp0"

if not exist "%~dp0.venv\Scripts\python.exe" (
  echo Project venv (.venv) not found. Create it first:
  echo   py -3.14 -m venv .venv
  pause
  exit /b 1
)

echo Installing the browser automation dependency...
"%~dp0.venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error
"%~dp0.venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error
"%~dp0.venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 goto :error

echo.
echo Setup complete. Next, double-click ????.bat and scan the QR code.
pause
exit /b 0

:error
echo.
echo Setup failed. Check the message above and confirm internet access.
pause
exit /b 1

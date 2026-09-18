@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 goto no_python

echo Installing dependencies...
python -m pip install --upgrade pip
if errorlevel 1 goto failed
python -m pip install -r requirements.txt
if errorlevel 1 goto failed
python -m playwright install chromium
if errorlevel 1 goto failed

echo Setup complete. Run login_douyin.bat next.
pause
exit /b 0

:no_python
echo Python was not found in PATH.
goto failed

:failed
echo Setup failed. Check the error above.
pause
exit /b 1

@echo off
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\python.exe" goto missing
if exist "%~dp0.venv\Scripts\pythonw.exe" start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0scripts\status_window.py"
if not exist "%~dp0.venv\Scripts\pythonw.exe" start "" "%~dp0.venv\Scripts\python.exe" "%~dp0scripts\status_window.py"
exit /b 0
:missing
echo Missing .venv. Run install_dependencies.bat first.
pause
exit /b 1

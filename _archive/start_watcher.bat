@echo off
cd /d "%~dp0"
if not exist "%~dp0config\anchors.json" goto missing
if not exist "%~dp0.venv\Scripts\python.exe" goto missingvenv
if exist "%~dp0.venv\Scripts\pythonw.exe" start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0scripts\status_window.py"
"%~dp0.venv\Scripts\python.exe" "%~dp0scripts\watcher.py" --daemon >> "%~dp0logs\watcher_console.log" 2>&1
pause
exit /b 0
:missing
echo Missing config\anchors.json
pause
exit /b 1
:missingvenv
echo Missing .venv. Run install_dependencies.bat first.
pause
exit /b 1

@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist "config\anchors.json" (
  echo Missing config\anchors.json. Copy config\anchors.example.json and configure it first.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo Missing Python environment. Run Toolbox first.
  pause
  exit /b 1
)
if not exist logs mkdir logs
if exist "logs\watcher_console.log" (
  for %%A in ("logs\watcher_console.log") do if %%~zA GTR 5242880 (
    if exist "logs\watcher_console.old.log" del /f /q "logs\watcher_console.old.log"
    move /y "logs\watcher_console.log" "logs\watcher_console.old.log" >nul
  )
)
echo Starting live watcher. Keep this window open. Log: logs\watcher_console.log
if exist ".venv\Scripts\pythonw.exe" start "Live monitor status" ".venv\Scripts\pythonw.exe" "scripts\status_window.py"
:run
".venv\Scripts\python.exe" scripts\watcher.py --daemon >> logs\watcher_console.log 2>&1
set RC=%errorlevel%
if "%RC%"=="0" goto end
echo [%date% %time%] watcher exited with code %RC%; restarting in 10 seconds. >> logs\watcher_console.log
timeout /t 10 /nobreak >nul
goto run
:end
echo Watcher stopped. See logs\state.json for details.
pause

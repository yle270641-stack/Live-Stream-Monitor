@echo off
setlocal
cd /d "%~dp0"

if not exist "config\anchors.json" (
  echo Missing config\anchors.json. Copy config\anchors.example.json and configure it first.
  pause
  exit /b 1
)

if not exist logs mkdir logs
rem --- Log rotation: archive console log larger than 5MB so it never grows unbounded ---
if exist "logs\watcher_console.log" (
  for %%A in ("logs\watcher_console.log") do if %%~zA GTR 5242880 (
    if exist "logs\watcher_console.old.log" del /f /q "logs\watcher_console.old.log"
    move /y "logs\watcher_console.log" "logs\watcher_console.old.log" >nul
  )
)

echo Starting live watcher. Keep this window open while monitoring is needed.
echo Logs are written to logs\watcher_console.log
echo If the watcher crashes it auto-restarts in 10s; press Ctrl+C or close this window to stop.
if exist "%~dp0.venv\Scripts\pythonw.exe" start "Live monitor status" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0scripts\status_window.py"

:run
"%~dp0.venv\Scripts\python.exe" scripts\watcher.py --daemon >> logs\watcher_console.log 2>&1
set RC=%errorlevel%
rem --- Clean exit (Ctrl+C / single-instance / normal stop) does not restart ---
if "%RC%"=="0" goto end
echo [%date% %time%] watcher crashed (exit %RC%), auto-restart in 10s ... >> logs\watcher_console.log
timeout /t 10 /nobreak >nul
goto run

:end
echo.
echo The watcher stopped normally. See logs\state.json and console output for details.
pause

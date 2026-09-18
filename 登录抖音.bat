@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Missing Python environment. Run Toolbox first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" scripts\douyin_login.py
if errorlevel 1 pause

@echo off
setlocal
cd /d "%~dp0"
"%~dp0.venv\Scripts\python.exe" scripts\douyin_login.py
if errorlevel 1 pause

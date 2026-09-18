@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\toolbox.ps1"
exit /b %errorlevel%

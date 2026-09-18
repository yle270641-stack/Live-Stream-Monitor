@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

:menu
cls
echo ========================================
echo   Finance Live Watcher - Toolbox
echo ========================================
echo   1. Create environment and install dependencies
echo   2. Install NVIDIA CUDA Python libraries
echo   3. Log in to Douyin
echo   4. Open status window
echo   5. Validate configuration
echo   6. Exit
echo ========================================
set /p choice=Select [1-6]:
if "%choice%"=="1" goto install
if "%choice%"=="2" goto cuda
if "%choice%"=="3" goto login
if "%choice%"=="4" goto status
if "%choice%"=="5" goto validate
if "%choice%"=="6" exit /b 0
goto menu

:install
if not exist ".venv\Scripts\python.exe" (
  py -3.12 -m venv .venv 2>nul || py -3.11 -m venv .venv 2>nul || python -m venv .venv
)
if not exist ".venv\Scripts\python.exe" goto python_error
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto install_error
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto install_error
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 goto install_error
if not exist "config\anchors.json" copy /y "config\anchors.example.json" "config\anchors.json" >nul
if not exist ".env" copy /y ".env.example" ".env" >nul
echo Installation completed.
echo Edit config\anchors.json, then select Validate configuration.
pause
goto menu

:python_error
echo Python 3.11 or 3.12 was not found. Install Python and try again.
pause
goto menu
:install_error
echo Installation failed. Review the error above and retry.
pause
goto menu
:cuda
if not exist ".venv\Scripts\python.exe" goto python_error
".venv\Scripts\python.exe" -m pip install --upgrade "nvidia-cublas-cu12>=12" "nvidia-cudnn-cu12>=9"
if errorlevel 1 goto install_error
echo CUDA libraries installed. Update the Whisper settings in .env.
pause
goto menu
:login
if not exist ".venv\Scripts\python.exe" goto python_error
".venv\Scripts\python.exe" scripts\douyin_login.py
if errorlevel 1 pause
goto menu
:status
if not exist ".venv\Scripts\python.exe" goto python_error
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" "scripts\status_window.py"
) else (
  start "" ".venv\Scripts\python.exe" "scripts\status_window.py"
)
goto menu
:validate
if not exist ".venv\Scripts\python.exe" goto python_error
".venv\Scripts\python.exe" scripts\check_config.py
pause
goto menu

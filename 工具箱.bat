@echo off
setlocal
cd /d "%~dp0"

:menu
cls
echo ========================================
echo   财经直播监控 - 工具箱
echo ========================================
echo   1. 安装依赖（Python 包 + Playwright 浏览器）
echo   2. 安装 CUDA 依赖（NVIDIA GPU 可选，加速转写）
echo   3. 登录抖音（扫码登录，登录过期时用）
echo   4. 查看监控状态（打开状态浮窗）
echo   5. 退出
echo ========================================
set /p choice=请选择 [1-5]: 

if "%choice%"=="1" goto install
if "%choice%"=="2" goto cuda
if "%choice%"=="3" goto login
if "%choice%"=="4" goto status
if "%choice%"=="5" exit /b 0
goto menu

:install
echo.
echo === 安装依赖 ===
if not exist ".venv\Scripts\python.exe" (
  echo 未找到 .venv。请先在项目根目录执行：py -3.14 -m venv .venv
  pause
  goto menu
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto install_error
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto install_error
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 goto install_error
echo.
echo 依赖安装完成。接下来可以运行"登录抖音"。
pause
goto menu

:install_error
echo.
echo 安装失败，请检查上方错误信息和网络连接。
pause
goto menu

:cuda
echo.
echo === 安装 CUDA 依赖 ===
if not exist ".venv\Scripts\python.exe" (
  echo 未找到 .venv，请先安装依赖。
  pause
  goto menu
)
".venv\Scripts\python.exe" -m pip install --upgrade "nvidia-cublas-cu12>=12" "nvidia-cudnn-cu12>=9"
if errorlevel 1 (
  echo CUDA 依赖安装失败，请检查网络连接。
  pause
  goto menu
)
echo.
echo CUDA 依赖安装完成。
pause
goto menu

:login
echo.
echo === 登录抖音 ===
if not exist ".venv\Scripts\python.exe" (
  echo 未找到 .venv，请先安装依赖。
  pause
  goto menu
)
".venv\Scripts\python.exe" scripts\douyin_login.py
if errorlevel 1 pause
goto menu

:status
echo.
echo === 打开监控状态浮窗 ===
if not exist ".venv\Scripts\python.exe" (
  echo 未找到 .venv，请先安装依赖。
  pause
  goto menu
)
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" "scripts\status_window.py"
) else (
  start "" ".venv\Scripts\python.exe" "scripts\status_window.py"
)
echo 状态浮窗已打开。
timeout /t 2 >nul
goto menu

@echo off
setlocal
cd /d "%~dp0"
echo Installing NVIDIA CUDA runtime libraries for faster-whisper...
"%~dp0.venv\Scripts\python.exe" -m pip install --upgrade "nvidia-cublas-cu12>=12" "nvidia-cudnn-cu12>=9"
if errorlevel 1 goto failed
echo CUDA runtime installation complete.
pause
exit /b 0
:failed
echo CUDA runtime installation failed. Check your network connection.
pause
exit /b 1

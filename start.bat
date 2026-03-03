@echo off
chcp 65001 >nul
echo 正在启动文件管理系统...
cd /d %~dp0

REM 优先使用 file-manager conda 环境的 Python
set PYTHON=%USERPROFILE%\.conda\envs\file-manager\python.exe
if not exist "%PYTHON%" set PYTHON=python

"%PYTHON%" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
pause

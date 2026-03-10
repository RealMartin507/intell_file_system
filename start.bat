@echo off
chcp 65001 >nul

:: 检测是否已有管理员权限
net session >nul 2>&1
if %errorlevel% == 0 goto :run

:: 未提权 —— 弹出 UAC 请求管理员权限（MFT 扫描和 USN 监控需要）
echo 正在请求管理员权限以启用 MFT 快速扫描和 USN 实时监控...
powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b

:run
echo 正在以管理员权限启动文件管理系统...
cd /d %~dp0

REM 优先使用 file-manager conda 环境的 Python
set PYTHON=%USERPROFILE%\.conda\envs\file-manager\python.exe
if not exist "%PYTHON%" set PYTHON=python

"%PYTHON%" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
pause

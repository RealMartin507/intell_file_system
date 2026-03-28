@echo off
chcp 65001 >nul

:: 检测是否已有管理员权限
net session >nul 2>&1
if %errorlevel% == 0 goto :run

:: 未提权 —— 弹出 UAC 请求管理员权限（拒绝则以普通权限继续运行，使用常规扫描模式）
echo 正在请求管理员权限以启用 MFT 快速扫描...
echo （点击"否"可跳过，以普通权限运行常规扫描模式）
powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs -ErrorAction Stop" 2>nul
if %errorlevel% == 0 exit /b
echo 未获得管理员权限，以普通权限启动（使用常规 scandir 模式）...

:run
echo 正在启动文件管理系统...
cd /d %~dp0

REM 优先使用 file-manager conda 环境的 Python
set PYTHON=%USERPROFILE%\.conda\envs\file-manager\python.exe
if not exist "%PYTHON%" set PYTHON=python

"%PYTHON%" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
pause

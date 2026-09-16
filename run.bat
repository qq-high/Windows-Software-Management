@echo off
chcp 65001 >nul
title Windows 系统优化管家 - 开发模式

REM 开发期运行脚本：自动用管理员权限启动
cd /d "%~dp0"

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo 错误：未检测到 Python，请先安装 Python 3.10 或更高版本
    echo 下载地址：https://www.python.org/downloads/
    pause
    exit /b 1
)

REM 检查依赖
python -c "import PySide6, qfluentwidgets, psutil, send2trash" >nul 2>&1
if errorlevel 1 (
    echo 正在安装依赖...
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
)

REM 以管理员权限启动
echo 正在以管理员权限启动...
powershell -Command "Start-Process python -ArgumentList 'main.py' -Verb RunAs -WorkingDirectory '%cd%'"
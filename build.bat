@echo off
chcp 65001 >nul
title Windows 系统优化管家 - 打包

setlocal enabledelayedexpansion

cd /d "%~dp0"

echo ===========================================
echo   Windows 系统优化管家 - 打包脚本
echo ===========================================
echo.

REM 1. 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo 错误：未检测到 Python
    pause
    exit /b 1
)

REM 2. 升级 pip
echo [1/5] 升级 pip...
python -m pip install --upgrade pip
echo.

REM 3. 安装依赖
echo [2/5] 安装依赖...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo 错误：安装依赖失败
    pause
    exit /b 1
)
echo.

REM 4. 安装 PyInstaller
echo [3/5] 安装 PyInstaller...
python -m pip install pyinstaller
echo.

REM 5. 清理旧产物
echo [4/5] 清理旧产物...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist "Windows系统优化管家.spec" del /q "Windows系统优化管家.spec"
echo.

REM 6. 开始打包
echo [5/5] 开始打包（可能需要几分钟）...
echo.

pyinstaller ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --name "Windows系统优化管家" ^
    --icon NONE ^
    --add-data "app/resources;app/resources" ^
    --collect-all PySide6-Fluent-Widgets ^
    --hidden-import wmi ^
    --hidden-import win32api ^
    --hidden-import win32com ^
    --hidden-import win32com.client ^
    --hidden-import win32security ^
    --hidden-import win32evtlog ^
    --hidden-import win32process ^
    --hidden-import win32service ^
    --uac-admin ^
    main.py

if errorlevel 1 (
    echo.
    echo 错误：打包失败
    pause
    exit /b 1
)

echo.
echo ===========================================
echo   打包完成！
echo   产物位置: dist\Windows系统优化管家.exe
echo ===========================================
echo.
pause
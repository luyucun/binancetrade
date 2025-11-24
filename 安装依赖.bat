@echo off
chcp 65001 >nul
title 安装系统依赖
color 0B

echo ================================================================================
echo.
echo                   安装 Binance 交易系统依赖
echo.
echo ================================================================================
echo.

if not exist requirements_v2.txt (
    echo [错误] 未找到 requirements_v2.txt 文件
    echo 请确保在正确的目录下运行此脚本
    echo.
    pause
    exit /b 1
)

echo [执行中] 正在安装依赖包...
echo.

py -m pip install --upgrade pip
py -m pip install -r requirements_v2.txt

if errorlevel 1 (
    echo.
    echo [错误] 依赖安装失败！
    echo 请检查：
    echo 1. Python是否已安装（需要Python 3.8+）
    echo 2. 网络连接是否正常
    echo 3. pip是否可用
    echo.
    pause
    exit /b 1
)

echo.
echo ================================================================================
echo [成功] 所有依赖已安装完成！
echo ================================================================================
echo.
echo 现在你可以：
echo   1. 双击 "启动模拟交易.bat" 进行测试
echo   2. 双击 "启动实盘交易.bat" 开始实盘（请谨慎！）
echo.
pause

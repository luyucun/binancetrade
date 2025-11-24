@echo off
chcp 65001 >nul
title Binance自动化交易系统 - 调试模式
color 0B

echo ================================================================================
echo.
echo                   Binance 自动化交易系统 v2.0
echo                        调试模式
echo.
echo ================================================================================
echo.
echo  模式说明:
echo  - 此模式用于开发和调试
echo  - 会显示详细的DEBUG级别日志
echo  - 不会使用真实资金（模拟交易）
echo.
echo ================================================================================
echo.
echo [启动中] 正在启动调试模式...
echo.

py run_trading_system.py debug

if errorlevel 1 (
    echo.
    echo [错误] 系统启动失败！
    echo 请检查：
    echo 1. Python是否已安装
    echo 2. 依赖包是否已安装 ^(pip install -r requirements_v2.txt^)
    echo 3. 配置文件是否正确
    echo.
    pause
    exit /b 1
)

echo.
echo [已停止] 调试模式已停止运行
echo.
pause

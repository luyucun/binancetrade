@echo off
chcp 65001 >nul
title Binance自动化交易系统 - 模拟模式
color 0A

echo ================================================================================
echo.
echo                   Binance 自动化交易系统 v2.0
echo                        模拟交易模式
echo.
echo ================================================================================
echo.
echo  模式说明:
echo  - 此模式仅模拟交易，不会使用真实资金
echo  - 用于测试策略和熟悉系统
echo  - 推荐首次使用者运行此模式至少24小时
echo.
echo ================================================================================
echo.
echo [启动中] 正在启动模拟交易系统...
echo.

py run_trading_system.py paper

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
echo [已停止] 模拟交易系统已停止运行
echo.
pause

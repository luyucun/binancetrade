@echo off
chcp 65001 >nul
title Binance自动化交易系统 - 实盘模式
color 0C

echo ================================================================================
echo.
echo                   Binance 自动化交易系统 v2.0
echo                        实盘交易模式
echo.
echo ================================================================================
echo.
echo  警告: 此模式将使用真实资金进行交易！
echo  =====================================================
echo.
echo  请在启动前确认以下事项：
echo.
echo  [1] 已更换API密钥并设置IP白名单
echo  [2] 已完成至少24小时模拟交易测试
echo  [3] 期货账户余额充足（建议≥100 USDT）
echo  [4] 已充分理解止损止盈机制
echo  [5] 已阅读完整风险警告
echo.
echo ================================================================================
echo.
pause

echo.
echo [启动中] 正在启动实盘交易系统...
echo.

py run_trading_system.py real

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
echo [已停止] 实盘交易系统已停止运行
echo.
pause

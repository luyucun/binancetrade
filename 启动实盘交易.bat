@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ==========================================
echo   Binance 自动化交易系统 v2.0 - 实盘模式
echo ==========================================
echo.
echo ⚠️  警告: 将在实盘交易模式下运行！
echo ⚠️  这将使用真实资金进行交易！
echo ⚠️  请确保你已经充分理解风险！
echo.

REM 显示3秒警告
timeout /t 3 /nobreak

echo.
set /p confirm="请输入 'YES' 确认启动实盘交易 (如需取消请直接关闭窗口): "

if /i "!confirm!"=="YES" (
    echo.
    echo 启动实盘交易...
    echo.
    py "D:\binancetrade\binancetrade\run_trading_system.py" real
) else (
    echo.
    echo 已取消实盘交易启动
    echo.
    pause
)

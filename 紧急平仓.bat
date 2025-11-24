@echo off
chcp 65001 >nul
title 紧急平仓 - 危险操作
color 4F

echo ================================================================================
echo.
echo                          紧急平仓工具
echo.
echo ================================================================================
echo.
echo  警告: 此操作将立即平掉所有活跃持仓！
echo  ================================================
echo.
echo  请确认你真的需要执行此操作
echo  这是一个不可逆的操作！
echo.
echo ================================================================================
echo.

set /p confirm="确认要平掉所有持仓吗？(输入 YES 确认): "

if not "%confirm%"=="YES" (
    echo.
    echo [已取消] 紧急平仓操作已取消
    echo.
    pause
    exit /b 0
)

echo.
echo [执行中] 正在平掉所有持仓...
echo.

py emergency_close_positions.py

if errorlevel 1 (
    echo.
    echo [错误] 平仓操作失败！
    echo 请手动登录Binance平台进行平仓
    echo.
    pause
    exit /b 1
)

echo.
echo [完成] 所有持仓已平掉
echo.
pause

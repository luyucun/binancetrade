@echo off
chcp 65001 >nul
title 查看交易日志
color 0F

echo ================================================================================
echo.
echo                      查看交易日志
echo.
echo ================================================================================
echo.

if not exist trading_engine.log (
    echo [警告] 未找到日志文件 trading_engine.log
    echo 系统可能还未启动过
    echo.
    pause
    exit /b 1
)

echo [提示] 正在打开日志文件...
echo.
echo 按 Ctrl+F 可以搜索关键字：
echo   - ERROR    : 查找错误
echo   - WARNING  : 查找警告
echo   - 入场成功  : 查找成功入场的交易
echo   - 平仓     : 查找平仓记录
echo.
timeout /t 2 >nul

notepad trading_engine.log

echo.
pause

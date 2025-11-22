#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
启动交易系统脚本

使用方法：
    python run_trading_system.py [模式]

模式选项：
    paper    - 模拟交易模式（推荐首先运行此模式）
    real     - 实盘交易模式（需谨慎！）
    debug    - 调试模式（显示详细日志）
"""

import asyncio
import sys
import os
import logging
from trading_engine_v2 import TradingEngine, EngineConfig

# 修复Windows终端Unicode编码问题
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    os.system('chcp 65001 >nul 2>&1')


def main():
    """主函数"""

    # 解析命令行参数 - 默认实盘模式
    mode = sys.argv[1] if len(sys.argv) > 1 else "real"

    # 配置日志 - 🔧 临时启用DEBUG
    logging.basicConfig(
        level=logging.DEBUG,  # 改为DEBUG看详细日志
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('trading_engine.log', encoding='utf-8')
        ]
    )

    logger = logging.getLogger(__name__)

    # 显示启动信息
    print("=" * 80)
    print("Binance 自动化交易系统 v2.0")
    print("=" * 80)
    print(f"启动模式: {mode.upper()}")
    print("=" * 80)

    # 创建引擎配置
    if mode == "real":
        # 实盘交易模式
        print("[警告] 将在实盘交易模式下运行！")
        print("[警告] 这将使用真实资金进行交易！")
        print("[警告] 请确保你已经充分理解风险！")

        confirmation = input("请输入 'YES' 确认启动实盘交易: ")
        if confirmation != "YES":
            print("已取消实盘交易启动")
            return

        config = EngineConfig(
            debug_mode=False,
            paper_trading=False,
            log_level="DEBUG"  # 🔧 临时改为DEBUG诊断，稳定后改回INFO
        )
        logger.warning("=" * 80)
        logger.warning("实盘交易模式已启动！")
        logger.warning("=" * 80)

    elif mode == "debug":
        # 调试模式
        config = EngineConfig(
            debug_mode=True,
            paper_trading=True,
            log_level="DEBUG"
        )
        logger.info("调试模式已启动，将运行模拟交易")

    else:
        # 默认模拟交易模式
        config = EngineConfig(
            debug_mode=False,
            paper_trading=True,
            log_level="INFO"
        )
        logger.info("模拟交易模式已启动")

    # 创建引擎
    engine = TradingEngine(config)

    # 启动引擎
    engine.start()

    # 运行主循环
    try:
        # 🔧 Windows平台需要特殊处理Ctrl+C
        if sys.platform == 'win32':
            # Windows: 使用ProactorEventLoop并手动处理信号
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            def signal_handler():
                """处理Ctrl+C信号"""
                logger.info("\n收到中断信号(Ctrl+C)，正在安全关闭...")
                engine.stop()
                loop.stop()

            # 注册Ctrl+C处理器
            try:
                import signal
                signal.signal(signal.SIGINT, lambda s, f: signal_handler())

                # 运行主循环
                loop.run_until_complete(engine.main_loop(interval_seconds=10))
            except KeyboardInterrupt:
                logger.info("\n收到中断信号，正在关闭...")
                engine.stop()
            finally:
                loop.close()
        else:
            # Linux/Mac: 直接使用asyncio.run
            asyncio.run(engine.main_loop(interval_seconds=10))

    except KeyboardInterrupt:
        logger.info("\n收到中断信号，正在关闭...")
        engine.stop()
    except Exception as e:
        logger.error(f"系统错误: {e}", exc_info=True)
        engine.stop()
    finally:
        # 🔧 确保显示退出信息
        print("\n" + "="*80)
        print("交易引擎已安全停止")
        print("="*80)

        # 显示会话统计
        try:
            print(f"本次会话统计:")
            print(f"  • 信号生成: {engine.stats.get('total_signals_generated', 0)} 个")
            print(f"  • 信号执行: {engine.stats.get('signals_executed', 0)} 个")
            print(f"  • 活跃持仓: {len(engine.risk_manager.active_positions)} 个")
        except:
            pass

        print("\n按任意键退出...")
        try:
            input()
        except:
            pass


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
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
import logging
from trading_engine_v2 import TradingEngine, EngineConfig


def main():
    """主函数"""

    # 解析命令行参数
    mode = sys.argv[1] if len(sys.argv) > 1 else "paper"

    # 配置日志
    logging.basicConfig(
        level=logging.DEBUG if mode == "debug" else logging.INFO,
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
        print("⚠️  警告: 将在实盘交易模式下运行！")
        print("⚠️  这将使用真实资金进行交易！")
        print("⚠️  请确保你已经充分理解风险！")

        confirmation = input("请输入 'YES' 确认启动实盘交易: ")
        if confirmation != "YES":
            print("已取消实盘交易启动")
            return

        config = EngineConfig(
            debug_mode=False,
            paper_trading=False,
            log_level="INFO"
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
        asyncio.run(engine.main_loop(interval_seconds=10))
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在关闭...")
        engine.stop()
    except Exception as e:
        logger.error(f"系统错误: {e}", exc_info=True)
        engine.stop()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
快速启动实盘交易（无二次确认）
仅用于已经充分了解风险的用户
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

    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('trading_engine.log', encoding='utf-8')
        ]
    )

    logger = logging.getLogger(__name__)

    print("=" * 80)
    print("Binance 实盘交易系统 - 快速启动")
    print("=" * 80)
    print("[警告] 实盘交易模式，使用真实资金！")
    print("=" * 80)

    # 简单确认
    confirmation = input("\n输入 'START' 启动交易: ")
    if confirmation != "START":
        print("已取消")
        return

    # 创建引擎
    logger.info("创建交易引擎...")
    engine = TradingEngine(EngineConfig(
        debug_mode=False,
        paper_trading=False,
        log_level="INFO"
    ))

    # 启动引擎（跳过内部确认）
    engine.state = engine.state  # 确保state已初始化
    engine.start_time = None

    # 直接设置为RUNNING状态
    from trading_engine_v2 import EngineState
    engine.state = EngineState.RUNNING
    engine.start_time = None

    logger.info("=" * 80)
    logger.info("交易引擎启动")
    logger.info("模式: 实盘交易")
    logger.info("=" * 80)

    # 配置Binance账户
    if engine.binance_client:
        logger.info("正在配置Binance账户参数...")
        try:
            if engine.binance_client.set_position_mode(dual_side_position=True):
                logger.info("✓ 双向持仓模式(Hedge)已设置")
        except Exception as e:
            logger.error(f"设置双向持仓模式失败: {e}")

    logger.info("引擎启动完成")

    print("\n" + "=" * 80)
    print("系统已启动，开始交易...")
    print("按 Ctrl+C 停止")
    print("=" * 80 + "\n")

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

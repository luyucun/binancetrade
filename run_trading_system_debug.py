#!/usr/bin/env python3
"""
启动交易系统脚本 - 改进版本（错误时暂停显示）

使用方法：
    python run_trading_system_debug.py [模式]

模式选项：
    paper    - 模拟交易模式（推荐首先运行此模式）
    real     - 实盘交易模式（需谨慎！）
    debug    - 调试模式（显示详细日志）
"""

import asyncio
import sys
import logging
import traceback
import os

# 设置Windows控制台编码为UTF-8
if sys.platform == 'win32':
    os.system('chcp 65001 >nul')


def main():
    """主函数"""
    try:
        # 导入必要的模块
        from trading_engine_v2 import TradingEngine, EngineConfig

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
            # 实盘交易模式 - 需要检查配置
            from config_v2 import API_CONFIG

            # 检查是否需要显式mainnet确认
            if API_CONFIG.get('require_explicit_mainnet_confirmation', True) and not API_CONFIG.get('testnet', True):
                print("警告: 将在MAINNET实盘交易模式下运行！")
                print("警告: 这将使用真实资金进行交易！")
                print("警告: 当前使用的是MAINNET正式环境，不是测试网！")
                print("警告: 请确保你已经充分理解风险！")
                print("")

                # 第一次确认
                confirmation1 = input("请输入 'YES' 确认你理解这是MAINNET实盘交易: ")
                if confirmation1 != "YES":
                    print("已取消实盘交易启动")
                    return

                # 第二次确认
                print("\n再次确认：你确定要在MAINNET正式环境交易吗？")
                confirmation2 = input("请再次输入 'YES' 最终确认: ")
                if confirmation2 != "YES":
                    print("已取消实盘交易启动")
                    return

                logger.warning("用户已双重确认MAINNET实盘交易")
            else:
                print("警告: 将在实盘交易模式下运行！")
                print("警告: 这将使用真实资金进行交易！")
                print("警告: 请确保你已经充分理解风险！")

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
        print("\n正在初始化交易引擎...")
        engine = TradingEngine(config)
        print("[OK] 交易引擎初始化成功\n")

        # 启动引擎
        engine.start()

        # 运行主循环
        print("按 Ctrl + C 可以停止系统\n")
        asyncio.run(engine.main_loop(interval_seconds=10))

    except KeyboardInterrupt:
        print("\n\n收到中断信号，正在关闭...")
        if 'engine' in locals():
            engine.stop()

    except Exception as e:
        print("\n" + "=" * 80)
        print("错误: 系统出错！")
        print("=" * 80)
        print(f"\n错误类型: {type(e).__name__}")
        print(f"错误信息: {e}\n")
        print("完整错误信息:")
        print("-" * 80)
        traceback.print_exc()
        print("-" * 80)

        print("\n按任意键退出...")
        try:
            input()
        except:
            pass


if __name__ == "__main__":
    main()

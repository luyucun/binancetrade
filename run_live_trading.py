"""
🚨 实盘交易启动脚本 (run_live_trading.py)
专门用于实盘交易的安全启动脚本
"""

import asyncio
import logging
import sys
from datetime import datetime

# 导入优化后的模块
from trading_engine_v2 import TradingEngine, EngineConfig
from config_v2 import API_CONFIG

logger = logging.getLogger(__name__)


def display_live_trading_warning():
    """显示实盘交易警告"""
    print("🚨" * 20)
    print("🚨 实盘交易模式 - 风险警告 🚨")
    print("🚨" * 20)
    print()
    print("⚠️  您即将启动实盘交易模式!")
    print("⚠️  这将使用您的真实资金进行自动交易!")
    print()
    print("📋 启动前检查清单:")
    print("   ✅ 1. 我已充分测试了交易策略")
    print("   ✅ 2. 我理解可能面临的亏损风险")
    print("   ✅ 3. 我已设置合理的风险参数")
    print("   ✅ 4. 我的账户有足够的保证金")
    print("   ✅ 5. 我准备好密切监控交易")
    print()
    print("🔧 当前风险参数:")
    print(f"   • 最大日亏损限制: 5 USDT")
    print(f"   • 单笔仓位大小: 12 USDT")
    print(f"   • 最大持仓数量: 6个")
    print(f"   • 每小时交易限制: 5笔")
    print()
    print("🌐 网络环境:")
    print(f"   • API环境: {'测试网' if API_CONFIG.get('testnet') else '主网(实盘)'}")
    print(f"   • API Key: {API_CONFIG['binance_key'][:10]}...{API_CONFIG['binance_key'][-10:]}")
    print()
    print("🚨" * 20)


async def run_live_trading():
    """运行实盘交易"""

    # 显示警告
    display_live_trading_warning()

    # 三重确认
    try:
        print("\n🔐 三重安全确认:")

        # 第一重确认
        confirm1 = input("1️⃣ 请输入 'LIVE' 确认启动实盘交易: ").strip()
        if confirm1 != 'LIVE':
            print("❌ 第一重确认失败，取消启动")
            return

        # 第二重确认
        confirm2 = input("2️⃣ 请输入 'TRADE' 确认使用真实资金: ").strip()
        if confirm2 != 'TRADE':
            print("❌ 第二重确认失败，取消启动")
            return

        # 第三重确认
        confirm3 = input("3️⃣ 请输入 'CONFIRM' 进行最终确认: ").strip()
        if confirm3 != 'CONFIRM':
            print("❌ 最终确认失败，取消启动")
            return

        print("\n✅ 三重确认通过，准备启动实盘交易引擎...")

    except KeyboardInterrupt:
        print("\n❌ 用户取消启动")
        return

    # 设置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(f'live_trading_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
            logging.StreamHandler()
        ]
    )

    print("\n🚀 启动实盘交易引擎...")
    print("优化功能:")
    print("  ✅ 并发K线数据获取")
    print("  ✅ 批量价格获取")
    print("  ✅ 连接池优化")
    print("  ✅ 实时风险控制")
    print("  ✅ 智能重试机制")

    # 创建实盘交易引擎
    engine = TradingEngine(EngineConfig(
        debug_mode=False,         # 实盘关闭调试模式
        paper_trading=False,      # 🚨 实盘交易模式
        log_level="INFO"
    ))

    try:
        engine.start()
        print(f"\n🚀 实盘交易引擎已启动 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("\n📊 实盘交易监控:")
        print("   • 按 Ctrl+C 安全停止交易")
        print("   • 监控日志以了解交易状态")
        print("   • 定期检查账户余额")

        # 运行主循环
        await engine.main_loop(interval_seconds=10)

    except KeyboardInterrupt:
        print("\n⏹️ 收到停止信号，正在安全关闭交易引擎...")
        try:
            # 安全停止，确保所有持仓得到处理
            print("📋 正在检查活跃持仓...")
            if hasattr(engine.risk_manager, 'active_positions') and engine.risk_manager.active_positions:
                active_count = len(engine.risk_manager.active_positions)
                print(f"⚠️ 发现 {active_count} 个活跃持仓")
                print("💡 建议: 手动管理这些持仓或等待自动止损/止盈")

                for symbol, position in engine.risk_manager.active_positions.items():
                    pnl = getattr(position, 'floating_pnl_usdt', 0)
                    print(f"   • {symbol}: {pnl:+.2f} USDT")

            engine.stop()
            print("✅ 交易引擎已安全停止")

        except Exception as e:
            print(f"⚠️ 停止过程中出现异常: {e}")

    except Exception as e:
        print(f"\n❌ 运行时错误: {e}")
        logger.error(f"实盘交易运行错误: {e}", exc_info=True)
        print("🆘 建议立即检查账户状态!")

    finally:
        print(f"\n📊 交易会话结束 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # 显示会话统计
        if 'engine' in locals():
            try:
                print("📈 会话统计:")
                print(f"   • 信号生成: {engine.stats.get('total_signals_generated', 0)} 个")
                print(f"   • 信号执行: {engine.stats.get('signals_executed', 0)} 个")
                print(f"   • 持仓平仓: {engine.stats.get('positions_closed', 0)} 个")
                print(f"   • 总盈亏: {engine.stats.get('total_profit_loss', 0):+.2f} USDT")
            except Exception as e:
                print(f"⚠️ 无法显示统计信息: {e}")


if __name__ == "__main__":
    print("🚨 实盘交易启动器")
    print("=" * 50)

    # 最后的退出机会
    print("💡 提示: 如果您不确定是否要启动实盘交易，请按 Ctrl+C 退出")

    try:
        input("\n按 Enter 键继续，或按 Ctrl+C 退出...")
        asyncio.run(run_live_trading())
    except KeyboardInterrupt:
        print("\n👋 已取消启动，交易引擎未启动")
    except Exception as e:
        print(f"\n💥 启动异常: {e}")
        logging.error(f"启动异常: {e}", exc_info=True)
"""
🚀 性能优化版交易引擎启动脚本 (run_optimized_trading.py)

展示所有性能优化的效果：
1. 并发K线获取
2. 批量价格获取
3. 连接池优化
4. WebSocket实时数据流（可选）
"""

import asyncio
import logging
import sys
from datetime import datetime

# 导入优化后的模块
from trading_engine_v2 import TradingEngine, EngineConfig
from websocket_integration_plan import WebSocketTradingEngine

logger = logging.getLogger(__name__)


async def run_optimized_trading():
    """运行性能优化版交易引擎"""
    print("=" * 80)
    print("🚀 性能优化版交易引擎")
    print("=" * 80)

    # 选择运行模式
    print("请选择运行模式:")
    print("1. HTTP优化版 (并发K线 + 批量价格 + 连接池)")
    print("2. WebSocket增强版 (实时数据流)")
    print("3. 性能对比测试")

    try:
        choice = input("请输入选择 (1-3): ").strip()
    except KeyboardInterrupt:
        print("\n用户取消操作")
        return

    if choice == "1":
        await run_http_optimized()
    elif choice == "2":
        await run_websocket_enhanced()
    elif choice == "3":
        await run_performance_comparison()
    else:
        print("无效选择，默认运行HTTP优化版")
        await run_http_optimized()


async def run_http_optimized():
    """运行HTTP优化版"""
    print("\n🔧 启动HTTP优化版交易引擎...")
    print("优化功能:")
    print("  ✅ 并发K线数据获取")
    print("  ✅ 批量价格获取")
    print("  ✅ 连接池优化")
    print("  ✅ 智能重试机制")

    engine = TradingEngine(EngineConfig(
        debug_mode=False,  # 🚨 实盘模式关闭debug
        paper_trading=False,  # 🚨 实盘交易模式
        log_level="INFO"
    ))

    try:
        engine.start()
        print(f"\n🚀 引擎已启动 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # 运行主循环
        await engine.main_loop(interval_seconds=10)

    except KeyboardInterrupt:
        print("\n⏹️ 用户中断，正在关闭...")
    except Exception as e:
        print(f"\n❌ 运行时错误: {e}")
        logger.error(f"HTTP优化版运行错误: {e}", exc_info=True)
    finally:
        engine.stop()
        print("✅ 引擎已停止")


async def run_websocket_enhanced():
    """运行WebSocket增强版"""
    print("\n🌐 启动WebSocket增强版交易引擎...")
    print("增强功能:")
    print("  ✅ 实时价格流")
    print("  ✅ 实时K线流")
    print("  ✅ 零延迟数据访问")
    print("  ✅ 自动降级到HTTP")
    print("  ✅ 连接状态监控")

    engine = WebSocketTradingEngine(
        config=EngineConfig(
            debug_mode=False,  # 🚨 实盘模式关闭debug
            paper_trading=False,  # 🚨 实盘交易模式
            log_level="INFO"
        ),
        enable_websocket=True
    )

    try:
        await engine.start_enhanced()
        print(f"\n🚀 WebSocket引擎已启动 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # 等待WebSocket连接稳定
        await asyncio.sleep(3)

        # 显示连接状态
        if engine.market_data_manager:
            status = engine.market_data_manager.get_connection_status()
            data_stats = engine.market_data_manager.get_data_stats()

            print("\n📊 WebSocket连接状态:")
            print(f"  价格流: {'✅ 已连接' if status['price_stream'] else '❌ 未连接'}")
            print(f"  K线流: {'✅ 已连接' if status['kline_stream'] else '❌ 未连接'}")
            print(f"  订阅币种: {data_stats['subscribed_symbols']} 个")
            print(f"  缓存价格: {data_stats['cached_prices']} 个")

        # 运行WebSocket增强版主循环
        iteration = 0
        while engine.state.value == "RUNNING":
            iteration += 1
            print(f"\n🔄 执行第 {iteration} 轮扫描...")

            await engine._scan_signals_websocket_enhanced()
            await engine._monitor_positions()

            # 定期显示性能统计
            if iteration % 5 == 0:
                stats = engine.get_performance_stats()
                print("\n📈 性能统计:")
                print(f"  WebSocket请求: {stats.get('ws_requests', 0)}")
                print(f"  HTTP请求: {stats.get('http_requests', 0)}")
                print(f"  响应时间 - WebSocket: {stats.get('avg_ws_response_time', 0)*1000:.1f}ms")
                print(f"  响应时间 - HTTP: {stats.get('avg_http_response_time', 0)*1000:.1f}ms")

            await asyncio.sleep(10)

    except KeyboardInterrupt:
        print("\n⏹️ 用户中断，正在关闭...")
    except Exception as e:
        print(f"\n❌ 运行时错误: {e}")
        logger.error(f"WebSocket增强版运行错误: {e}", exc_info=True)
    finally:
        await engine.stop_enhanced()
        print("✅ WebSocket引擎已停止")


async def run_performance_comparison():
    """运行性能对比测试"""
    print("\n⚡ 性能对比测试")
    print("将对比以下版本的性能:")
    print("  1. HTTP优化版 (并发 + 批量 + 连接池)")
    print("  2. WebSocket增强版 (实时数据流)")

    results = {}

    # 测试HTTP优化版
    print("\n🔧 测试HTTP优化版...")
    start_time = datetime.now()

    http_engine = TradingEngine(EngineConfig(
        debug_mode=False,
        paper_trading=True,
        log_level="WARNING"
    ))

    try:
        http_engine.start()

        # 执行3轮信号扫描
        for i in range(3):
            print(f"  HTTP优化版 - 第 {i+1}/3 轮...")
            await http_engine._scan_signals()

        http_time = (datetime.now() - start_time).total_seconds()
        results['http_optimized'] = {
            'time': http_time,
            'avg_per_scan': http_time / 3,
            'signals_generated': http_engine.stats['total_signals_generated']
        }

    except Exception as e:
        print(f"HTTP优化版测试失败: {e}")
        results['http_optimized'] = {'time': 0, 'error': str(e)}
    finally:
        http_engine.stop()

    # 测试WebSocket增强版
    print("\n🌐 测试WebSocket增强版...")
    start_time = datetime.now()

    ws_engine = WebSocketTradingEngine(
        config=EngineConfig(
            debug_mode=False,
            paper_trading=True,
            log_level="WARNING"
        ),
        enable_websocket=True
    )

    try:
        await ws_engine.start_enhanced()

        # 等待WebSocket连接稳定
        await asyncio.sleep(5)

        # 执行3轮信号扫描
        for i in range(3):
            print(f"  WebSocket增强版 - 第 {i+1}/3 轮...")
            await ws_engine._scan_signals_websocket_enhanced()

        ws_time = (datetime.now() - start_time).total_seconds() - 5  # 减去等待时间
        performance_stats = ws_engine.get_performance_stats()

        results['websocket_enhanced'] = {
            'time': ws_time,
            'avg_per_scan': ws_time / 3,
            'signals_generated': ws_engine.stats['total_signals_generated'],
            'ws_requests': performance_stats.get('ws_requests', 0),
            'http_requests': performance_stats.get('http_requests', 0),
            'avg_ws_response': performance_stats.get('avg_ws_response_time', 0) * 1000,
            'avg_http_response': performance_stats.get('avg_http_response_time', 0) * 1000
        }

    except Exception as e:
        print(f"WebSocket增强版测试失败: {e}")
        results['websocket_enhanced'] = {'time': 0, 'error': str(e)}
    finally:
        await ws_engine.stop_enhanced()

    # 输出对比结果
    print("\n" + "=" * 60)
    print("📊 性能对比结果")
    print("=" * 60)

    if 'error' not in results.get('http_optimized', {}):
        http_res = results['http_optimized']
        print(f"HTTP优化版:")
        print(f"  总耗时: {http_res['time']:.2f}s")
        print(f"  平均每轮: {http_res['avg_per_scan']:.2f}s")
        print(f"  生成信号: {http_res['signals_generated']} 个")

    if 'error' not in results.get('websocket_enhanced', {}):
        ws_res = results['websocket_enhanced']
        print(f"\nWebSocket增强版:")
        print(f"  总耗时: {ws_res['time']:.2f}s")
        print(f"  平均每轮: {ws_res['avg_per_scan']:.2f}s")
        print(f"  生成信号: {ws_res['signals_generated']} 个")
        print(f"  WebSocket请求: {ws_res['ws_requests']} 次")
        print(f"  HTTP请求: {ws_res['http_requests']} 次")
        print(f"  WebSocket响应时间: {ws_res['avg_ws_response']:.1f}ms")
        print(f"  HTTP响应时间: {ws_res['avg_http_response']:.1f}ms")

    # 计算性能提升
    if 'error' not in results.get('http_optimized', {}) and 'error' not in results.get('websocket_enhanced', {}):
        http_time = results['http_optimized']['avg_per_scan']
        ws_time = results['websocket_enhanced']['avg_per_scan']

        if http_time > 0:
            improvement = ((http_time - ws_time) / http_time) * 100
            print(f"\n🚀 性能提升: {improvement:+.1f}%")

            if improvement > 0:
                print("  ✅ WebSocket版本更快！")
            else:
                print("  ⚠️ HTTP版本仍然更快，可能需要调优WebSocket")

    print("=" * 60)


if __name__ == "__main__":
    # 设置日志（精简版：减少无用输出）
    logging.basicConfig(
        level=logging.INFO,  # 只保留INFO级别以上
        format='%(asctime)s - %(levelname)s - %(message)s',  # 简化格式，移除模块名
        handlers=[
            logging.StreamHandler(),  # 控制台输出
            logging.FileHandler('trading_engine.log', encoding='utf-8')  # 文件输出
        ]
    )

    # 运行优化版交易引擎
    try:
        asyncio.run(run_optimized_trading())
    except KeyboardInterrupt:
        print("\n👋 程序已退出")
    except Exception as e:
        print(f"\n💥 程序异常退出: {e}")
        logger.error(f"主程序异常: {e}", exc_info=True)
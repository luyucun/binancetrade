#!/usr/bin/env python3
"""
调试启动问题的测试脚本
"""

import sys
import traceback
import logging

# 设置编码
import codecs
sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())

def test_imports():
    """测试各个模块的导入"""
    print("开始测试模块导入...")

    try:
        print("1. 测试 config_v2...")
        import config_v2
        print("OK config_v2 导入成功")
    except Exception as e:
        print(f"ERROR config_v2 导入失败: {e}")
        traceback.print_exc()
        return False

    try:
        print("2. 测试 trading_logger_v2...")
        import trading_logger_v2
        print("OK trading_logger_v2 导入成功")
    except Exception as e:
        print(f"ERROR trading_logger_v2 导入失败: {e}")
        traceback.print_exc()
        return False

    try:
        print("3. 测试 network_monitor...")
        import network_monitor
        print("OK network_monitor 导入成功")
    except Exception as e:
        print(f"ERROR network_monitor 导入失败: {e}")
        traceback.print_exc()
        return False

    try:
        print("4. 测试 binance_client_v2...")
        import binance_client_v2
        print("OK binance_client_v2 导入成功")
    except Exception as e:
        print(f"ERROR binance_client_v2 导入失败: {e}")
        traceback.print_exc()
        return False

    try:
        print("5. 测试 risk_manager_v2...")
        import risk_manager_v2
        print("OK risk_manager_v2 导入成功")
    except Exception as e:
        print(f"ERROR risk_manager_v2 导入失败: {e}")
        traceback.print_exc()
        return False

    try:
        print("6. 测试 position_monitor_v2...")
        import position_monitor_v2
        print("OK position_monitor_v2 导入成功")
    except Exception as e:
        print(f"ERROR position_monitor_v2 导入失败: {e}")
        traceback.print_exc()
        return False

    try:
        print("7. 测试 trading_engine_v2...")
        import trading_engine_v2
        print("OK trading_engine_v2 导入成功")
    except Exception as e:
        print(f"ERROR trading_engine_v2 导入失败: {e}")
        traceback.print_exc()
        return False

    return True

def test_engine_creation():
    """测试引擎创建"""
    print("\n开始测试引擎创建...")

    try:
        from trading_engine_v2 import TradingEngine, EngineConfig

        print("1. 创建配置...")
        config = EngineConfig(
            debug_mode=True,
            paper_trading=True,
            log_level="INFO"
        )
        print("OK 配置创建成功")

        print("2. 创建引擎...")
        engine = TradingEngine(config)
        print("OK 引擎创建成功")

        return True
    except Exception as e:
        print(f"ERROR 引擎创建失败: {e}")
        traceback.print_exc()
        return False

def main():
    print("=" * 60)
    print("交易系统启动问题诊断工具")
    print("=" * 60)

    # 测试导入
    if not test_imports():
        print("\nERROR 模块导入阶段失败，请检查相关依赖")
        return

    print("\nSUCCESS 所有模块导入成功")

    # 测试引擎创建
    if not test_engine_creation():
        print("\nERROR 引擎创建阶段失败")
        return

    print("\nSUCCESS 引擎创建成功")
    print("\nALL TESTS PASSED 所有测试通过，系统应该可以正常启动")

if __name__ == "__main__":
    main()
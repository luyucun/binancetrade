#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
紧急平仓脚本 - 清理所有活跃持仓
⚠️ 警告：这将平仓你在Binance期货账户的所有USDT永续合约持仓！
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from binance_client_v2 import BinanceClientV2
from config_v2 import API_CONFIG

def emergency_close_all():
    """紧急平仓所有持仓"""

    print("=" * 80)
    print("⚠️  紧急平仓工具")
    print("=" * 80)
    print()
    print("本工具将平仓你在Binance期货账户中的所有USDT永续合约持仓！")
    print()

    # 初始化客户端
    print("[1/4] 初始化Binance客户端...")
    client = BinanceClientV2(
        api_key=API_CONFIG['binance_key'],
        api_secret=API_CONFIG['binance_secret'],
        testnet=False
    )
    print("✓ 客户端初始化成功")

    # 获取当前持仓
    print("\n[2/4] 获取当前持仓...")
    positions = client.get_positions()

    if not positions:
        print("✓ 没有发现活跃持仓，账户清洁！")
        return

    print(f"✓ 发现 {len(positions)} 个活跃持仓：")
    print()

    for i, pos in enumerate(positions, 1):
        profit_str = f"{pos['unrealized_profit']:+.4f} USDT ({pos['unrealized_profit_pct']:+.2f}%)"
        print(f"  {i}. {pos['symbol']}")
        print(f"     方向: {pos['side']}")
        print(f"     数量: {abs(pos['quantity'])}")
        print(f"     入场价: {pos['entry_price']:.6f}")
        print(f"     当前价: {pos['mark_price']:.6f}")
        print(f"     浮动盈亏: {profit_str}")
        print()

    # 确认
    print("-" * 80)
    print("⚠️  警告：即将平仓以上所有持仓！")
    print("-" * 80)
    confirmation = input("请输入 'YES' 确认平仓，或按Enter取消: ")

    if confirmation != "YES":
        print("\n✓ 已取消平仓操作")
        return

    # 执行平仓
    print("\n[3/4] 执行平仓操作...")
    success_count = 0
    fail_count = 0

    for pos in positions:
        symbol = pos['symbol']
        quantity = abs(pos['quantity'])

        # 确定平仓方向（持仓是多就卖出，持仓是空就买入）
        side = 'SELL' if pos['side'] == 'LONG' else 'BUY'

        print(f"\n  平仓 {symbol} ({side} {quantity})...")

        try:
            order = client.place_market_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                reduce_only=True
            )

            if order:
                print(f"  ✓ {symbol} 平仓成功 (订单ID: {order['order_id']})")
                success_count += 1
            else:
                print(f"  ✗ {symbol} 平仓失败")
                fail_count += 1

        except Exception as e:
            print(f"  ✗ {symbol} 平仓异常: {e}")
            fail_count += 1

    # 汇总
    print("\n" + "=" * 80)
    print("[4/4] 平仓汇总")
    print("=" * 80)
    print(f"总持仓数: {len(positions)}")
    print(f"成功平仓: {success_count}")
    print(f"失败: {fail_count}")
    print()

    if fail_count > 0:
        print("⚠️  部分持仓平仓失败，请检查日志并手动处理")
    else:
        print("✓ 所有持仓已成功平仓！")

    print("=" * 80)


if __name__ == "__main__":
    try:
        emergency_close_all()
    except KeyboardInterrupt:
        print("\n\n✗ 操作被用户中断")
    except Exception as e:
        print(f"\n\n✗ 发生错误: {e}")
        import traceback
        traceback.print_exc()

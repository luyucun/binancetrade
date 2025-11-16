#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
查看持仓详细信息 - 包括保证金、名义价值等
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from binance_client_v2 import BinanceClientV2
from config_v2 import API_CONFIG

def check_positions_detail():
    """查看持仓详细信息"""

    print("=" * 80)
    print("持仓详细信息")
    print("=" * 80)
    print()

    # 初始化客户端
    client = BinanceClientV2(
        api_key=API_CONFIG['binance_key'],
        api_secret=API_CONFIG['binance_secret'],
        testnet=False
    )

    # 获取持仓
    positions = client.get_positions()

    if not positions:
        print("✓ 没有活跃持仓")
        return

    print(f"发现 {len(positions)} 个活跃持仓：")
    print()

    for i, pos in enumerate(positions, 1):
        symbol = pos['symbol']
        quantity = abs(pos['quantity'])
        entry_price = pos['entry_price']
        mark_price = pos['mark_price']

        # 计算各种金额
        entry_value = quantity * entry_price  # 入场时的名义价值
        current_value = quantity * mark_price  # 当前名义价值
        unrealized_pnl = pos['unrealized_profit']

        # 获取杠杆信息
        leverage = pos.get('leverage', 'N/A')

        # 计算保证金（名义价值 / 杠杆）
        if leverage != 'N/A':
            margin = current_value / float(leverage)
        else:
            margin = current_value

        print(f"{i}. {symbol}")
        print(f"   方向: {pos['side']}")
        print(f"   数量: {quantity}")
        print(f"   杠杆: {leverage}x")
        print(f"   入场价: {entry_price:.6f}")
        print(f"   当前价: {mark_price:.6f}")
        print(f"   入场名义价值: {entry_value:.2f} USDT")
        print(f"   当前名义价值: {current_value:.2f} USDT")
        print(f"   保证金: {margin:.2f} USDT")
        print(f"   浮动盈亏: {unrealized_pnl:+.4f} USDT ({pos['unrealized_profit_pct']:+.2f}%)")
        print()

    print("=" * 80)
    print("说明:")
    print("  - 名义价值(Notional Value) = 数量 × 价格")
    print("  - 保证金(Margin) = 名义价值 ÷ 杠杆")
    print("  - 如果杠杆=1x, 则保证金 = 名义价值")
    print("=" * 80)

if __name__ == "__main__":
    try:
        check_positions_detail()
    except Exception as e:
        print(f"\n✗ 发生错误: {e}")
        import traceback
        traceback.print_exc()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试精度调整功能"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from binance_client_v2 import BinanceClientV2
from config_v2 import API_CONFIG

client = BinanceClientV2(
    api_key=API_CONFIG['binance_key'],
    api_secret=API_CONFIG['binance_secret'],
    testnet=False
)

print("=" * 80)
print("测试精度调整功能")
print("=" * 80)

# 测试几个之前失败的币种
test_symbols = [
    ('DOGEUSDT', 40.732368),
    ('MEMEUSDT', 5838.847801),
    ('KITEUSDT', 129.607128),
]

for symbol, quantity in test_symbols:
    print(f"\n{symbol}:")
    print(f"  原始数量: {quantity}")

    # 获取币种信息
    info = client.get_symbol_info(symbol)
    if info:
        print(f"  状态: {info['status']}")
        print(f"  最小数量: {info['min_qty']}")
        print(f"  步长: {info['step_size']}")

        # 调整数量
        adjusted = client.adjust_quantity(symbol, quantity)
        if adjusted:
            print(f"  ✓ 调整后数量: {adjusted}")
        else:
            print(f"  ✗ 调整失败")
    else:
        print(f"  ✗ 无法获取币种信息")

print("\n" + "=" * 80)

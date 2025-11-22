#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试交易量过滤修复是否生效"""

import sys
import io

# 设置输出编码为UTF-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from binance_client_v2 import BinanceClientV2
from config_v2 import API_CONFIG, SELECTION_CONFIG

def main():
    print('='*80)
    print('交易量过滤测试')
    print('='*80)
    print(f'配置: top_n_by_volume = {SELECTION_CONFIG["top_n_by_volume"]}')
    print(f'配置: min_24h_volume = {SELECTION_CONFIG["min_24h_volume"]/1e6:.0f}M USDT')
    print('='*80)
    print()

    client = BinanceClientV2(
        api_key=API_CONFIG['binance_key'],
        api_secret=API_CONFIG['binance_secret'],
        testnet=False
    )

    # 调用修复后的方法
    coins = client.get_top_coins_by_volume(
        limit=SELECTION_CONFIG['top_n_by_volume'],
        min_volume_usdt=SELECTION_CONFIG['min_24h_volume']
    )

    print(f'\n✓ 成功获取 {len(coins)} 个币种\n')
    print('='*80)
    print('币种列表（24小时交易量 USDT）:')
    print('='*80)

    # 统计
    all_satisfy = True
    min_volume_threshold = SELECTION_CONFIG['min_24h_volume']

    for i, coin in enumerate(coins, 1):
        symbol = coin['symbol']
        volume = coin['volume_24h']
        volume_m = volume / 1e6

        # 检查是否满足条件
        status = '✓' if volume >= min_volume_threshold else '✗'
        if volume < min_volume_threshold:
            all_satisfy = False
            print(f'{status} #{i:2d} {symbol:20s} {volume_m:>10.2f}M  ⚠️ 不满足条件！')
        else:
            print(f'{status} #{i:2d} {symbol:20s} {volume_m:>10.2f}M')

    print()
    print('='*80)
    print('验证结果:')
    print('='*80)

    if all_satisfy:
        print('✓ 所有币种的24小时交易量均 ≥ 50M USDT')
        print('✓ Bug已修复！')
    else:
        print('✗ 仍有币种不满足条件')
        print('✗ Bug未完全修复')

    print()
    print('统计信息:')
    print(f'  返回币种数: {len(coins)}')
    print(f'  最小交易量: {min(coin["volume_24h"] for coin in coins)/1e6:.2f}M USDT')
    print(f'  最大交易量: {max(coin["volume_24h"] for coin in coins)/1e6:.2f}M USDT')
    print(f'  平均交易量: {sum(coin["volume_24h"] for coin in coins)/len(coins)/1e6:.2f}M USDT')

if __name__ == '__main__':
    main()

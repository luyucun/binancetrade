#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""检查币种在交易量排行榜中的位置"""

import sys
import io

# 设置输出编码为UTF-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from binance_client_v2 import BinanceClientV2
from config_v2 import API_CONFIG

def main():
    client = BinanceClientV2(
        api_key=API_CONFIG['binance_key'],
        api_secret=API_CONFIG['binance_secret'],
        testnet=False
    )

    coins = client.get_top_coins_by_volume(60)

    # 今天交易的币种
    target_symbols = {
        'XPLUSDT': 'Mixed',
        'LINEAUSDT': 'Loss',
        'KITEUSDT': 'Profit',
        'ROSEUSDT': 'Loss',
        'PENGUUSDT': 'Loss',
        'TUTUSDT': 'Loss',
        'BROCCOLI714USDT': 'Loss',
        'ADAUSDT': 'Loss',
        'PLUMEUSDT': 'Loss',
        'WLFIUSDT': 'Loss',
        'ENAUSDT': 'Profit'
    }

    print('='*80)
    print('Volume Ranking Analysis')
    print('='*80)

    found_symbols = {}

    for i, coin in enumerate(coins, 1):
        symbol = coin['symbol']
        if symbol in target_symbols:
            status = target_symbols[symbol]
            volume_m = coin['volume_24h'] / 1e6
            print(f'#{i:2d} {symbol:20s} {status:10s} Volume: {volume_m:>8.2f}M USDT')
            found_symbols[symbol] = i

    print('\n' + '='*80)
    print('Statistical Analysis:')
    print('='*80)

    profitable = []
    losing = []

    for symbol, status in target_symbols.items():
        if symbol in found_symbols:
            rank = found_symbols[symbol]
            if status == 'Profit':
                profitable.append((symbol, rank))
            elif status == 'Loss':
                losing.append((symbol, rank))

    if profitable:
        avg_rank_profit = sum(r for _, r in profitable) / len(profitable)
        print(f'Profitable trades: {len(profitable)}')
        print(f'Average ranking: #{avg_rank_profit:.1f}')
        print(f'Rankings: {[r for _, r in profitable]}')

    if losing:
        avg_rank_loss = sum(r for _, r in losing) / len(losing)
        print(f'\nLosing trades: {len(losing)}')
        print(f'Average ranking: #{avg_rank_loss:.1f}')
        print(f'Rankings: {[r for _, r in losing]}')

    # 检查未找到的币种
    not_found = [s for s in target_symbols if s not in found_symbols]
    if not_found:
        print(f'\nNot in Top60: {not_found}')

if __name__ == '__main__':
    main()

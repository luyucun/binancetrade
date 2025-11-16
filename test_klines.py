#!/usr/bin/env python3
"""测试K线数量"""
from binance_client_v2 import BinanceClientV2
from config_v2 import API_CONFIG

client = BinanceClientV2(
    api_key=API_CONFIG['binance_key'],
    api_secret=API_CONFIG['binance_secret'],
    testnet=False
)

# 测试几个币种
symbols = ['BTCUSDT', 'ETHUSDT', 'DOGEUSDT']

for symbol in symbols:
    print(f"\n{symbol}:")
    for interval in ['3m', '5m', '15m']:
        klines = client.get_klines(symbol, interval, 50)
        print(f"  {interval}: 请求50根, 实际返回 {len(klines) if klines else 0} 根")

"""
🔧 测试无效交易对过滤功能
"""

import asyncio
import logging
from binance_client_v2 import BinanceClientV2
from config_v2 import API_CONFIG

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

async def test_invalid_symbol_filtering():
    """测试无效交易对过滤功能"""
    print("🔧 测试无效交易对过滤功能...")

    try:
        # 初始化客户端
        client = BinanceClientV2(
            api_key=API_CONFIG['binance_key'],
            api_secret=API_CONFIG['binance_secret'],
            testnet=API_CONFIG.get('testnet', False)
        )

        # 获取有效的期货交易对
        print("\\n1. 获取有效期货交易对...")
        valid_symbols = client.get_valid_futures_symbols()
        print(f"✅ 获取到 {len(valid_symbols)} 个有效期货交易对")

        # 测试一些已知的无效交易对
        test_symbols = [
            'HYPEUSDT',      # 无效
            'PIEVERSEUSDT',  # 无效
            'FARTCOINUSDT',  # 无效
            'BTCUSDT',       # 有效
            'ETHUSDT',       # 有效
            'SOONUSDT',      # 无效
        ]

        print("\\n2. 测试交易对有效性检查...")
        for symbol in test_symbols:
            is_valid = symbol in valid_symbols
            status = "✅ 有效" if is_valid else "❌ 无效"
            print(f"  {symbol:15s}: {status}")

        # 测试K线获取（应该不再有Invalid symbol错误）
        print("\\n3. 测试有效交易对的K线获取...")
        valid_test_symbols = [s for s in test_symbols if s in valid_symbols]

        for symbol in valid_test_symbols[:3]:  # 只测试前3个
            try:
                klines = client.get_klines(symbol, '3m', 5)
                print(f"✅ {symbol}: 获取K线成功，{len(klines)}根")
            except Exception as e:
                print(f"❌ {symbol}: K线获取失败 - {e}")

        print("\\n4. 过滤效果统计...")
        invalid_count = len([s for s in test_symbols if s not in valid_symbols])
        valid_count = len([s for s in test_symbols if s in valid_symbols])
        print(f"  测试币种总数: {len(test_symbols)}")
        print(f"  有效期货交易对: {valid_count}")
        print(f"  已过滤无效交易对: {invalid_count}")

        print("\\n🎉 无效交易对过滤测试完成！")

    except Exception as e:
        print(f"💥 测试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_invalid_symbol_filtering())
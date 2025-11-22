"""
🔍 调试无效交易对过滤问题
"""

import asyncio
import logging
from binance_client_v2 import BinanceClientV2
from config_v2 import API_CONFIG

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

async def debug_symbol_filtering():
    """调试交易对过滤问题"""
    print("🔍 调试无效交易对过滤问题...")

    try:
        # 初始化客户端
        print("\\n1. 初始化Binance客户端...")
        client = BinanceClientV2(
            api_key=API_CONFIG['binance_key'],
            api_secret=API_CONFIG['binance_secret'],
            testnet=API_CONFIG.get('testnet', False)
        )
        print("✅ 客户端初始化成功")

        # 检查API调用方式
        print("\\n2. 检查期货交易所信息API...")
        try:
            exchange_info = client.client.futures_exchange_info()
            total_symbols = len(exchange_info.get('symbols', []))
            print(f"✅ 成功获取期货交易所信息，共 {total_symbols} 个交易对")

            # 检查前几个交易对
            symbols = exchange_info.get('symbols', [])[:5]
            for symbol in symbols:
                print(f"   {symbol['symbol']}: {symbol['status']}")

        except Exception as e:
            print(f"❌ 获取期货交易所信息失败: {e}")
            return

        # 测试我们的方法
        print("\\n3. 测试get_valid_futures_symbols方法...")
        try:
            valid_symbols = client.get_valid_futures_symbols()
            print(f"✅ 获取到 {len(valid_symbols)} 个有效期货交易对")

            # 检查问题币种是否在列表中
            problem_symbols = ['HYPEUSDT', 'PIEVERSEUSDT', 'SOONUSDT', 'BEATUSDT', 'FARTCOINUSDT', 'CROSSUSDT']
            print("\\n4. 检查问题币种:")
            for symbol in problem_symbols:
                is_valid = symbol in valid_symbols
                status = "✅ 有效" if is_valid else "❌ 无效"
                print(f"   {symbol:15s}: {status}")

                # 如果显示有效但实际无效，这就是问题所在
                if is_valid:
                    print(f"⚠️  警告: {symbol} 在有效列表中但实际无效!")

        except Exception as e:
            print(f"❌ 方法调用失败: {e}")
            import traceback
            traceback.print_exc()

        # 测试获取候选币种
        print("\\n5. 测试币种获取和过滤流程...")
        try:
            # 模拟 _fetch_candidate_coins
            coins_data = client.get_top_coins_by_volume(limit=10, min_volume_usdt=50000000)
            print(f"✅ 获取到 {len(coins_data)} 个候选币种")

            for coin in coins_data[:5]:
                symbol = coin['symbol']
                is_in_valid_list = symbol in valid_symbols if valid_symbols else False
                print(f"   {symbol:15s}: {'✅ 在有效列表' if is_in_valid_list else '❌ 不在有效列表'}")

        except Exception as e:
            print(f"❌ 币种获取测试失败: {e}")

        print("\\n🎯 调试完成!")

    except Exception as e:
        print(f"💥 调试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(debug_symbol_filtering())
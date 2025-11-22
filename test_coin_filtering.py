"""
🔍 简化测试：检查币种过滤逻辑
"""

import logging
from binance_client_v2 import BinanceClientV2
from coin_selector import CoinSelector
from config_v2 import API_CONFIG

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def test_coin_filtering():
    """测试币种过滤逻辑"""
    print("🔍 测试币种过滤逻辑...")

    try:
        # 1. 初始化客户端
        print("\\n1. 初始化客户端...")
        client = BinanceClientV2(
            api_key=API_CONFIG['binance_key'],
            api_secret=API_CONFIG['binance_secret'],
            testnet=API_CONFIG.get('testnet', False)
        )

        # 2. 获取有效期货交易对
        print("\\n2. 获取有效期货交易对...")
        valid_symbols = client.get_valid_futures_symbols()
        print(f"✅ 获取到 {len(valid_symbols)} 个有效期货交易对")

        # 3. 检查已知问题币种
        problem_symbols = ['HYPEUSDT', 'PIEVERSEUSDT', 'SOONUSDT', 'BEATUSDT', 'FARTCOINUSDT', 'CROSSUSDT']
        print("\\n3. 检查已知问题币种:")

        valid_futures_symbols_set = set(valid_symbols)
        for symbol in problem_symbols:
            is_in_futures = symbol in valid_futures_symbols_set
            print(f"   {symbol:15s}: {'✅ 在期货列表中' if is_in_futures else '❌ 不在期货列表中'}")

            if is_in_futures:
                print(f"⚠️  这就是问题! {symbol} 不应该在期货有效列表中")

        # 4. 获取候选币种
        print("\\n4. 获取候选币种...")
        all_coins = []
        try:
            coins_data = client.get_top_coins_by_volume(limit=60, min_volume_usdt=50000000)

            from coin_selector import CoinInfo
            for coin_data in coins_data:
                all_coins.append(CoinInfo(
                    symbol=coin_data['symbol'],
                    current_price=coin_data['price'],
                    change_24h=coin_data['change_24h'],
                    volume_24h=coin_data['volume_24h'],
                    current_volume=coin_data['volume'],
                    is_usdt_pair=True
                ))

            print(f"✅ 获取到 {len(all_coins)} 个候选币种")

            # 检查候选币种中是否包含问题币种
            candidate_symbols = [coin.symbol for coin in all_coins]
            print("\\n5. 检查候选币种中是否包含问题币种:")
            for symbol in problem_symbols:
                is_in_candidates = symbol in candidate_symbols
                print(f"   {symbol:15s}: {'⚠️ 在候选列表中' if is_in_candidates else '✅ 不在候选列表中'}")

        except Exception as e:
            print(f"❌ 获取候选币种失败: {e}")

        # 5. 测试币种选择器
        print("\\n6. 测试币种选择器...")
        try:
            selector = CoinSelector()
            selected_coins = selector.select_coins(all_coins)
            selected_symbols = [coin.symbol for coin in selected_coins]

            print(f"✅ 币种选择器选出 {len(selected_coins)} 个币种")

            # 检查选出的币种中是否有问题币种
            print("\\n7. 检查选出的币种中是否有问题币种:")
            for symbol in problem_symbols:
                is_selected = symbol in selected_symbols
                print(f"   {symbol:15s}: {'⚠️ 被选中' if is_selected else '✅ 未被选中'}")

        except Exception as e:
            print(f"❌ 币种选择器测试失败: {e}")

        print("\\n🎯 测试完成!")

    except Exception as e:
        print(f"💥 测试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_coin_filtering()
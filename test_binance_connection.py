"""
Binance连接诊断工具
用于检测和解决API连接问题
"""

import sys
from binance.client import Client
from binance.exceptions import BinanceAPIException
from config_v2 import API_CONFIG

def test_binance_connection():
    """测试Binance API连接"""
    print("=" * 60)
    print("Binance API 连接诊断工具")
    print("=" * 60)

    # 显示配置信息
    print(f"\n当前配置:")
    print(f"  Testnet模式: {API_CONFIG.get('testnet', False)}")
    print(f"  实盘交易: {not API_CONFIG.get('paper_trading', True)}")
    print(f"  API Key: {API_CONFIG['binance_key'][:10]}...{API_CONFIG['binance_key'][-10:]}")

    try:
        # 尝试初始化客户端
        print(f"\n正在连接Binance API...")

        # 🔧 配置代理支持
        requests_params = {'timeout': 30}
        if API_CONFIG.get('use_proxy', False):
            proxy_config = API_CONFIG.get('proxy', {})
            requests_params['proxies'] = proxy_config
            print(f"[OK] Using SOCKS5 proxy: {proxy_config.get('https', 'N/A')}")
        else:
            print("[OK] No proxy, direct connection to Binance")

        # 如果是测试网
        if API_CONFIG.get('testnet', False):
            print("使用测试网模式...")
            client = Client(
                API_CONFIG['binance_key'],
                API_CONFIG['binance_secret'],
                testnet=True,
                requests_params=requests_params
            )
            # 测试网使用不同的base URL
            client.API_URL = 'https://testnet.binancefuture.com'
        else:
            print("使用主网模式...")
            client = Client(
                API_CONFIG['binance_key'],
                API_CONFIG['binance_secret'],
                requests_params=requests_params
            )

        # 测试连接
        print("测试API连接...")
        server_time = client.get_server_time()
        print(f"✓ 成功连接到Binance!")
        print(f"  服务器时间: {server_time}")

        # 测试账户访问
        print("\n测试账户访问...")
        account = client.futures_account()
        print(f"✓ 账户访问成功!")
        print(f"  账户余额 (USDT): {float(account['totalWalletBalance']):.2f} USDT")

        # 测试期货市场数据
        print("\n测试市场数据访问...")
        ticker = client.futures_ticker(symbol='BTCUSDT')
        print(f"✓ 市场数据访问成功!")
        print(f"  BTC价格: ${float(ticker['lastPrice']):.2f}")

        print("\n" + "=" * 60)
        print("✓ 所有测试通过! Binance API连接正常")
        print("=" * 60)
        return True

    except BinanceAPIException as e:
        print(f"\n❌ Binance API错误:")
        print(f"  错误代码: {e.code}")
        print(f"  错误消息: {e.message}")

        # 提供解决方案
        print("\n" + "=" * 60)
        print("问题诊断和解决方案:")
        print("=" * 60)

        if "restricted location" in str(e.message).lower():
            print("\n⚠️ 地区限制问题:")
            print("  你的IP地址在Binance限制地区列表中")
            print("\n解决方案:")
            print("  1. 使用VPN连接到支持的地区 (推荐: 日本、新加坡、香港)")
            print("  2. 或者使用Binance测试网 (testnet=True)")
            print("  3. 检查是否有代理设置")

        elif e.code == -2015:
            print("\n⚠️ API密钥权限不足:")
            print("  请确保API密钥有期货交易权限")

        elif e.code == -1021:
            print("\n⚠️ 时间戳不同步:")
            print("  请同步系统时间")

        else:
            print(f"\n未知错误: {e.message}")

        return False

    except Exception as e:
        print(f"\n❌ 未知错误: {e}")
        print(f"  错误类型: {type(e).__name__}")
        return False


def suggest_vpn_config():
    """建议VPN配置"""
    print("\n" + "=" * 60)
    print("VPN配置建议")
    print("=" * 60)
    print("""
如果你需要使用VPN访问Binance:

1. 推荐VPN服务:
   - NordVPN
   - ExpressVPN
   - Surfshark

2. 推荐连接地区:
   - 日本 (JP)
   - 新加坡 (SG)
   - 香港 (HK)

3. 配置步骤:
   a) 连接VPN到推荐地区
   b) 确认IP地址已更改
   c) 重新运行此诊断脚本
   d) 如果成功，再启动交易程序

4. 在Python中使用代理 (可选):
   在 binance_client_v2.py 中添加代理设置:

   client = Client(
       api_key,
       api_secret,
       {'proxies': {
           'http': 'http://127.0.0.1:7890',
           'https': 'http://127.0.0.1:7890'
       }}
   )
""")


if __name__ == "__main__":
    success = test_binance_connection()

    if not success:
        suggest_vpn_config()
        sys.exit(1)
    else:
        sys.exit(0)

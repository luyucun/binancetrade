"""
简单24小时交易查看器 (simple_24h_check.py)
不依赖外部库，直接使用Binance客户端
"""

import sys
import os
import json
from datetime import datetime, timedelta

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def safe_import():
    """安全导入，处理依赖问题"""
    try:
        from binance_client_v2 import BinanceClientV2
        from config_v2 import API_CONFIG
        return BinanceClientV2, API_CONFIG
    except ImportError as e:
        print(f"❌ 导入失败: {e}")
        print("请检查以下文件是否存在:")
        print("- binance_client_v2.py")
        print("- config_v2.py")
        return None, None
    except Exception as e:
        print(f"❌ 初始化失败: {e}")
        return None, None

def simple_24h_check():
    """简单的24小时交易检查"""
    print("🚀 启动24小时交易查看器...")

    # 安全导入
    BinanceClientV2, API_CONFIG = safe_import()
    if not BinanceClientV2 or not API_CONFIG:
        input("按Enter键退出...")
        return

    try:
        print("📡 连接Binance...")

        # 创建客户端
        client = BinanceClientV2(
            api_key=API_CONFIG['binance_key'],
            api_secret=API_CONFIG['binance_secret'],
            testnet=API_CONFIG.get('testnet', False)
        )

        print("✅ 连接成功!")

        # 计算24小时时间范围
        now = datetime.now()
        start_time = now - timedelta(hours=24)

        print(f"📅 查询时间: {start_time.strftime('%Y-%m-%d %H:%M')} 到 {now.strftime('%Y-%m-%d %H:%M')}")

        # 获取交易记录
        print("📊 正在获取交易记录...")

        trades = client.client.futures_account_trades(
            startTime=int(start_time.timestamp() * 1000),
            endTime=int(now.timestamp() * 1000),
            limit=1000
        )

        print(f"✅ 获取到 {len(trades)} 条交易记录")

        if not trades:
            print("📭 最近24小时没有交易记录")
        else:
            display_simple_summary(trades)

        # 获取当前持仓
        print("\n📊 正在获取当前持仓...")
        try:
            positions = client.get_positions()
            if positions:
                display_positions(positions)
            else:
                print("📭 当前无持仓")
        except Exception as e:
            print(f"⚠️ 获取持仓失败: {e}")

    except Exception as e:
        print(f"❌ 操作失败: {e}")
        print(f"错误类型: {type(e).__name__}")

        # 显示详细错误信息
        import traceback
        print("\n🔍 详细错误信息:")
        traceback.print_exc()

    # 防止闪退
    print(f"\n{'='*50}")
    print("查询完成!")
    input("按Enter键退出...")

def display_simple_summary(trades):
    """显示简单的交易汇总"""
    print(f"\n📈 24小时交易汇总:")
    print("-" * 60)

    # 按币种统计
    symbol_stats = {}
    total_fee = 0.0
    total_pnl = 0.0

    for trade in trades:
        symbol = trade['symbol']
        commission = abs(float(trade['commission']))
        realized_pnl = float(trade['realizedPnl'])

        if symbol not in symbol_stats:
            symbol_stats[symbol] = {
                'count': 0,
                'volume': 0.0,
                'fee': 0.0,
                'pnl': 0.0
            }

        symbol_stats[symbol]['count'] += 1
        symbol_stats[symbol]['volume'] += abs(float(trade['qty']))
        symbol_stats[symbol]['fee'] += commission
        symbol_stats[symbol]['pnl'] += realized_pnl

        total_fee += commission
        total_pnl += realized_pnl

    # 显示汇总
    print(f"{'币种':<12} {'次数':<6} {'总量':<12} {'盈亏':<10} {'手续费':<8}")
    print("-" * 60)

    for symbol, stats in sorted(symbol_stats.items()):
        print(f"{symbol:<12} {stats['count']:<6} {stats['volume']:<12.4f} "
              f"{stats['pnl']:+<10.2f} {stats['fee']:<8.4f}")

    print("-" * 60)
    print(f"总计: {len(trades)} 笔交易, 盈亏: {total_pnl:+.2f} USDT, 手续费: {total_fee:.4f} USDT")

    # 显示最近几笔交易
    print(f"\n📋 最近10笔交易:")
    recent_trades = sorted(trades, key=lambda x: x['time'], reverse=True)[:10]

    for trade in recent_trades:
        trade_time = datetime.fromtimestamp(trade['time'] / 1000)
        side = "买" if trade['buyer'] else "卖"
        qty = float(trade['qty'])
        price = float(trade['price'])

        print(f"{trade_time.strftime('%m-%d %H:%M')} {trade['symbol']:<10} "
              f"{side} {abs(qty):<10.4f} @ {price:<10.4f}")

def display_positions(positions):
    """显示当前持仓"""
    print(f"\n📊 当前持仓 ({len(positions)} 个):")
    print("-" * 70)
    print(f"{'币种':<12} {'方向':<4} {'数量':<12} {'入场价':<10} {'盈亏':<10}")
    print("-" * 70)

    total_unrealized = 0.0
    for pos in positions:
        side = "多" if pos['side'] == 'LONG' else "空"
        print(f"{pos['symbol']:<12} {side:<4} {abs(pos['quantity']):<12.6f} "
              f"{pos['entry_price']:<10.4f} {pos['unrealized_profit']:+<10.2f}")
        total_unrealized += pos['unrealized_profit']

    print("-" * 70)
    print(f"总未实现盈亏: {total_unrealized:+.2f} USDT")

def test_connection():
    """测试连接"""
    print("🔧 测试Binance连接...")

    BinanceClientV2, API_CONFIG = safe_import()
    if not BinanceClientV2 or not API_CONFIG:
        return False

    try:
        client = BinanceClientV2(
            api_key=API_CONFIG['binance_key'],
            api_secret=API_CONFIG['binance_secret'],
            testnet=API_CONFIG.get('testnet', False)
        )

        # 测试API连接
        server_time = client.client.get_server_time()
        print(f"✅ 连接成功! 服务器时间: {datetime.fromtimestamp(server_time['serverTime']/1000)}")
        return True

    except Exception as e:
        print(f"❌ 连接失败: {e}")
        return False

if __name__ == "__main__":
    print("🚀 24小时交易查看器启动中...")
    print("="*50)

    # 先测试连接
    if test_connection():
        simple_24h_check()
    else:
        print("❌ 无法连接到Binance，请检查配置")
        input("按Enter键退出...")
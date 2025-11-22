"""
24小时交易记录查看器 (check_24h_trades.py)
简化版本，专门用于查看最近24小时的交易情况
"""

import sys
import json
from datetime import datetime, timedelta
from binance_client_v2 import BinanceClientV2
from config_v2 import API_CONFIG

def get_24h_trades():
    """获取最近24小时的交易记录"""
    print("🔍 获取最近24小时交易记录...")

    try:
        # 初始化客户端
        client = BinanceClientV2(
            api_key=API_CONFIG['binance_key'],
            api_secret=API_CONFIG['binance_secret'],
            testnet=API_CONFIG.get('testnet', False)
        )

        # 设置24小时时间范围
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=24)

        print(f"📅 时间范围: {start_time.strftime('%Y-%m-%d %H:%M')} 到 {end_time.strftime('%Y-%m-%d %H:%M')}")

        # 获取期货交易记录
        trades = client.client.futures_account_trades(
            startTime=int(start_time.timestamp() * 1000),
            endTime=int(end_time.timestamp() * 1000),
            limit=1000
        )

        if not trades:
            print("❌ 未找到交易记录")
            return

        print(f"✅ 找到 {len(trades)} 条交易记录")
        print("\n" + "="*80)
        print("📊 最近24小时交易记录")
        print("="*80)

        # 按交易对分组
        trades_by_symbol = {}
        total_commission = 0.0
        total_realized_pnl = 0.0

        for trade in trades:
            symbol = trade['symbol']
            if symbol not in trades_by_symbol:
                trades_by_symbol[symbol] = {
                    'trades': [],
                    'total_qty': 0.0,
                    'total_commission': 0.0,
                    'total_realized_pnl': 0.0
                }

            trades_by_symbol[symbol]['trades'].append(trade)
            trades_by_symbol[symbol]['total_qty'] += abs(float(trade['qty']))
            trades_by_symbol[symbol]['total_commission'] += abs(float(trade['commission']))
            trades_by_symbol[symbol]['total_realized_pnl'] += float(trade['realizedPnl'])

            total_commission += abs(float(trade['commission']))
            total_realized_pnl += float(trade['realizedPnl'])

        # 显示按币种汇总
        print(f"{'币种':<15} {'交易次数':<8} {'总数量':<15} {'已实现盈亏':<15} {'手续费':<10}")
        print("-" * 80)

        for symbol, data in sorted(trades_by_symbol.items()):
            print(f"{symbol:<15} {len(data['trades']):<8} {data['total_qty']:<15.6f} {data['total_realized_pnl']:+<15.2f} {data['total_commission']:<10.4f}")

        print("-" * 80)
        print(f"{'总计':<15} {len(trades):<8} {'':<15} {total_realized_pnl:+<15.2f} {total_commission:<10.4f}")

        # 显示详细交易记录
        print(f"\n📋 详细交易记录:")
        print("-" * 100)
        print(f"{'时间':<17} {'币种':<12} {'方向':<4} {'数量':<15} {'价格':<12} {'盈亏':<12} {'手续费':<8}")
        print("-" * 100)

        # 按时间排序显示
        all_trades_sorted = sorted(trades, key=lambda x: x['time'], reverse=True)

        for trade in all_trades_sorted:
            trade_time = datetime.fromtimestamp(trade['time'] / 1000)
            side = "买入" if trade['buyer'] else "卖出"
            qty = float(trade['qty'])
            price = float(trade['price'])
            realized_pnl = float(trade['realizedPnl'])
            commission = float(trade['commission'])

            print(f"{trade_time.strftime('%m-%d %H:%M:%S'):<17} "
                  f"{trade['symbol']:<12} "
                  f"{side:<4} "
                  f"{qty:<15.6f} "
                  f"{price:<12.4f} "
                  f"{realized_pnl:+<12.2f} "
                  f"{commission:<8.4f}")

        # 保存到文件
        filename = f"trades_24h_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(trades, f, indent=2, ensure_ascii=False)

        print(f"\n💾 详细数据已保存到: {filename}")

        # 简单统计
        buy_trades = [t for t in trades if t['buyer']]
        sell_trades = [t for t in trades if not t['buyer']]

        print(f"\n📈 24小时交易统计:")
        print(f"- 总交易次数: {len(trades)}")
        print(f"- 买入次数: {len(buy_trades)}")
        print(f"- 卖出次数: {len(sell_trades)}")
        print(f"- 交易币种: {len(trades_by_symbol)}")
        print(f"- 总手续费: {total_commission:.4f} USDT")
        print(f"- 已实现盈亏: {total_realized_pnl:+.2f} USDT")

        return trades

    except Exception as e:
        print(f"❌ 获取交易记录失败: {e}")
        import traceback
        traceback.print_exc()
        return None

def get_current_positions():
    """获取当前持仓"""
    print("\n🔍 获取当前持仓...")

    try:
        client = BinanceClientV2(
            api_key=API_CONFIG['binance_key'],
            api_secret=API_CONFIG['binance_secret'],
            testnet=API_CONFIG.get('testnet', False)
        )

        positions = client.get_positions()

        if not positions:
            print("✅ 当前无持仓")
            return

        print(f"📊 当前持仓 ({len(positions)} 个):")
        print("-" * 80)
        print(f"{'币种':<15} {'方向':<6} {'数量':<15} {'入场价':<12} {'标记价':<12} {'盈亏(USDT)':<12}")
        print("-" * 80)

        total_unrealized_pnl = 0.0

        for pos in positions:
            side = "多头" if pos['side'] == 'LONG' else "空头"
            print(f"{pos['symbol']:<15} "
                  f"{side:<6} "
                  f"{abs(pos['quantity']):<15.6f} "
                  f"{pos['entry_price']:<12.4f} "
                  f"{pos['mark_price']:<12.4f} "
                  f"{pos['unrealized_profit']:+<12.2f}")

            total_unrealized_pnl += pos['unrealized_profit']

        print("-" * 80)
        print(f"{'总计':<53} {total_unrealized_pnl:+<12.2f}")

    except Exception as e:
        print(f"❌ 获取持仓失败: {e}")

def show_account_summary():
    """显示账户摘要"""
    print("\n🔍 获取账户信息...")

    try:
        client = BinanceClientV2(
            api_key=API_CONFIG['binance_key'],
            api_secret=API_CONFIG['binance_secret'],
            testnet=API_CONFIG.get('testnet', False)
        )

        # 获取账户信息
        account_info = client.client.futures_account()

        total_wallet_balance = float(account_info['totalWalletBalance'])
        total_unrealized_pnl = float(account_info['totalUnrealizedProfit'])
        total_margin_balance = float(account_info['totalMarginBalance'])
        available_balance = float(account_info['availableBalance'])

        print(f"💰 账户摘要:")
        print(f"- 钱包余额: {total_wallet_balance:.2f} USDT")
        print(f"- 未实现盈亏: {total_unrealized_pnl:+.2f} USDT")
        print(f"- 保证金余额: {total_margin_balance:.2f} USDT")
        print(f"- 可用余额: {available_balance:.2f} USDT")

    except Exception as e:
        print(f"❌ 获取账户信息失败: {e}")

def main():
    """主函数"""
    print("=" * 50)
    print("📊 24小时交易记录查看器")
    print("=" * 50)

    # 获取24小时交易记录
    trades = get_24h_trades()

    # 获取当前持仓
    get_current_positions()

    # 显示账户摘要
    show_account_summary()

    print(f"\n✅ 查询完成!")

    # 等待用户输入，避免闪退
    try:
        input("\n按Enter键退出...")
    except:
        pass

if __name__ == "__main__":
    main()
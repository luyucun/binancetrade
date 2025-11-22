"""
快速交易数据分析脚本 (quick_analysis.py)
用于快速分析最近的交易表现
"""

import sys
from datetime import datetime, timedelta
from trading_data_analyzer import TradingDataAnalyzer

def quick_analysis(days: int = 7, export_csv: bool = True, show_plot: bool = True):
    """
    快速分析最近几天的交易数据

    Args:
        days: 分析最近几天的数据
        export_csv: 是否导出CSV文件
        show_plot: 是否显示图表
    """
    print(f"🔍 开始分析最近 {days} 天的交易数据...")

    analyzer = TradingDataAnalyzer()

    # 设置时间范围
    end_time = datetime.now()
    start_time = end_time - timedelta(days=days)

    print(f"📅 分析时间: {start_time.strftime('%Y-%m-%d %H:%M')} 到 {end_time.strftime('%Y-%m-%d %H:%M')}")

    # 从多个数据源获取交易记录
    all_trades = []

    # 1. 从Binance API获取
    print("📡 从Binance API获取交易记录...")
    try:
        api_trades = analyzer.fetch_historical_trades(start_time, end_time)
        all_trades.extend(api_trades)
        print(f"✓ API获取: {len(api_trades)} 条记录")
    except Exception as e:
        print(f"✗ API获取失败: {e}")

    # 2. 从日志文件获取
    log_files = ["trading_engine.log", "logs/trading.log", "trading.log"]
    for log_file in log_files:
        try:
            print(f"📄 从日志文件获取: {log_file}")
            log_trades = analyzer.load_from_logs(log_file, start_time, end_time)
            all_trades.extend(log_trades)
            print(f"✓ 日志获取: {len(log_trades)} 条记录")
            break
        except Exception as e:
            continue

    if not all_trades:
        print("❌ 未找到任何交易记录")
        return

    print(f"\n📊 总共分析 {len(all_trades)} 个交易记录")

    # 计算统计数据
    stats = analyzer.calculate_statistics(all_trades)

    # 显示关键统计
    print("\n" + "="*50)
    print("📈 关键统计数据")
    print("="*50)
    print(f"总交易次数: {stats.total_trades}")
    print(f"胜率: {stats.win_rate:.1f}% ({stats.winning_trades}胜 {stats.losing_trades}负)")
    print(f"总盈亏: {stats.total_profit_usdt:+.2f} USDT")
    print(f"平均每笔: {stats.avg_profit_per_trade:+.2f} USDT")
    print(f"最大盈利: {stats.max_profit:+.2f} USDT")
    print(f"最大亏损: {stats.max_loss:+.2f} USDT")
    print(f"盈利因子: {stats.profit_factor:.2f}")
    print(f"平均持仓: {stats.avg_hold_time_minutes:.1f} 分钟")
    if stats.best_symbol:
        print(f"最佳币种: {stats.best_symbol}")
    if stats.worst_symbol:
        print(f"最差币种: {stats.worst_symbol}")

    # 显示最近几笔交易
    print(f"\n📋 最近 5 笔交易:")
    recent_trades = sorted([t for t in all_trades if t.exit_time],
                          key=lambda x: x.exit_time, reverse=True)[:5]

    for i, trade in enumerate(recent_trades, 1):
        profit_str = f"{trade.profit_loss_usdt:+.2f}" if trade.profit_loss_usdt else "进行中"
        duration_str = f"{trade.hold_duration_minutes:.0f}分钟" if trade.hold_duration_minutes else "N/A"
        print(f"{i}. {trade.symbol} {trade.side} | {profit_str} USDT | {duration_str}")

    # 导出文件
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if export_csv:
        csv_filename = f"trading_analysis_{timestamp}.csv"
        analyzer.export_to_csv(all_trades, csv_filename)
        print(f"\n📁 CSV已导出: {csv_filename}")

    # 生成报告
    report_filename = f"trading_report_{timestamp}.md"
    analyzer.generate_report(all_trades, report_filename)
    print(f"📁 报告已生成: {report_filename}")

    # 显示图表
    if show_plot:
        try:
            plot_filename = f"trading_chart_{timestamp}.png"
            analyzer.plot_performance(all_trades, plot_filename)
            print(f"📁 图表已保存: {plot_filename}")
        except Exception as e:
            print(f"⚠️ 图表生成失败: {e}")

    print(f"\n✅ 分析完成!")

def analyze_symbol_performance(symbol: str, days: int = 30):
    """分析特定币种的表现"""
    print(f"🔍 分析 {symbol} 最近 {days} 天的表现...")

    analyzer = TradingDataAnalyzer()
    end_time = datetime.now()
    start_time = end_time - timedelta(days=days)

    # 获取指定币种的交易
    all_trades = analyzer.fetch_historical_trades(start_time, end_time, [symbol])

    if not all_trades:
        print(f"❌ 未找到 {symbol} 的交易记录")
        return

    print(f"📊 找到 {len(all_trades)} 个 {symbol} 交易记录")

    # 计算统计
    stats = analyzer.calculate_statistics(all_trades)

    print(f"""
{symbol} 交易表现:
- 交易次数: {stats.total_trades}
- 胜率: {stats.win_rate:.1f}%
- 总盈亏: {stats.total_profit_usdt:+.2f} USDT
- 平均每笔: {stats.avg_profit_per_trade:+.2f} USDT
- 盈利因子: {stats.profit_factor:.2f}
""")

    # 显示所有交易
    for i, trade in enumerate(all_trades, 1):
        profit_str = f"{trade.profit_loss_usdt:+.2f} USDT" if trade.profit_loss_usdt else "进行中"
        duration = f"{trade.hold_duration_minutes:.0f}分钟" if trade.hold_duration_minutes else "进行中"
        entry_time = trade.entry_time.strftime('%m-%d %H:%M') if trade.entry_time else "N/A"
        exit_time = trade.exit_time.strftime('%m-%d %H:%M') if trade.exit_time else "进行中"

        print(f"{i}. {entry_time} → {exit_time} | {profit_str} | {duration}")

def show_daily_summary(days: int = 7):
    """显示每日交易汇总"""
    print(f"📅 显示最近 {days} 天的每日交易汇总...")

    analyzer = TradingDataAnalyzer()
    end_time = datetime.now()
    start_time = end_time - timedelta(days=days)

    # 获取所有交易
    all_trades = analyzer.fetch_historical_trades(start_time, end_time)

    if not all_trades:
        print("❌ 未找到交易记录")
        return

    # 按日期分组
    daily_trades = {}
    for trade in all_trades:
        if trade.exit_time:
            date_key = trade.exit_time.strftime('%Y-%m-%d')
            if date_key not in daily_trades:
                daily_trades[date_key] = []
            daily_trades[date_key].append(trade)

    print(f"\n📊 每日交易汇总:")
    print("-" * 60)

    total_profit = 0
    for date in sorted(daily_trades.keys(), reverse=True):
        trades = daily_trades[date]
        daily_profit = sum([t.profit_loss_usdt for t in trades if t.profit_loss_usdt])
        wins = len([t for t in trades if t.profit_loss_usdt and t.profit_loss_usdt > 0])
        total_profit += daily_profit

        print(f"{date}: {len(trades)}笔 | {wins}胜{len(trades)-wins}负 | {daily_profit:+.2f} USDT")

    print("-" * 60)
    print(f"总计: {total_profit:+.2f} USDT")

def main():
    """主函数"""
    if len(sys.argv) == 1:
        # 默认快速分析
        quick_analysis()

    elif len(sys.argv) >= 2:
        command = sys.argv[1].lower()

        if command == "quick":
            days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
            quick_analysis(days)

        elif command == "symbol":
            if len(sys.argv) < 3:
                print("用法: python quick_analysis.py symbol BTCUSDT [days]")
                return
            symbol = sys.argv[2].upper()
            days = int(sys.argv[3]) if len(sys.argv) > 3 else 30
            analyze_symbol_performance(symbol, days)

        elif command == "daily":
            days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
            show_daily_summary(days)

        else:
            print("""
使用方法:
  python quick_analysis.py                    # 快速分析最近7天
  python quick_analysis.py quick [days]       # 分析最近N天
  python quick_analysis.py symbol BTCUSDT [days]  # 分析特定币种
  python quick_analysis.py daily [days]       # 每日汇总
""")

if __name__ == "__main__":
    main()
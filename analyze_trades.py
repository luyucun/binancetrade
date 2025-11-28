#!/usr/bin/env python3
"""
分析已完成交易的详细统计
从日志中提取完整交易记录并进行分析
"""

import re
from collections import defaultdict, Counter
from datetime import datetime

def parse_trading_log():
    """解析交易日志，提取所有交易记录"""

    # 读取日志文件
    log_file = "trading_engine.log"

    trades = []
    signals = []

    with open(log_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # 提取所有信号生成记录
    signal_pattern = r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}).*?(\w+): 生成信号.*?评分: (\d+)'
    for match in re.finditer(signal_pattern, content):
        timestamp = match.group(1)
        symbol = match.group(2)
        score = int(match.group(3))
        signals.append({
            'timestamp': timestamp,
            'symbol': symbol,
            'score': score
        })

    # 提取所有P&L记录（最终盈亏）
    pnl_pattern = r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}).*?(\w+): (?:STOP_LOSS|TAKE_PROFIT.*?) - P&L: ([+-]\d+\.\d+) USDT \(([+-]\d+\.\d+)%\)'

    for match in re.finditer(pnl_pattern, content):
        timestamp = match.group(1)
        symbol = match.group(2)
        pnl_usdt = float(match.group(3))
        pnl_pct = float(match.group(4))

        # 只记录实际的平仓盈亏，过滤掉重复的stage记录
        if "STOP_LOSS" in match.group(0) and "TAKE_PROFIT" not in match.group(0):
            trades.append({
                'timestamp': timestamp,
                'symbol': symbol,
                'pnl_usdt': pnl_usdt,
                'pnl_pct': pnl_pct,
                'exit_type': 'STOP_LOSS'
            })

    return signals, trades

def analyze_trades():
    """分析交易数据"""

    signals, trades = parse_trading_log()

    print("=" * 80)
    print("📊 自动化交易系统详细分析报告")
    print("=" * 80)

    # 1. 信号分析
    print("\n🎯 信号生成分析:")
    score_dist = Counter(signal['score'] for signal in signals)
    total_signals = len(signals)

    print(f"总信号生成: {total_signals} 个")
    print("评分分布:")
    for score in sorted(score_dist.keys()):
        count = score_dist[score]
        pct = count / total_signals * 100
        print(f"  {score}分: {count} 个 ({pct:.1f}%)")

    signals_7_plus = sum(count for score, count in score_dist.items() if score >= 7)
    print(f"≥7分信号: {signals_7_plus} 个 ({signals_7_plus/total_signals*100:.1f}%)")

    # 2. 交易执行分析
    print(f"\n💼 交易执行分析:")
    total_trades = len(trades)
    print(f"总执行交易: {total_trades} 笔")

    if total_trades > 0:
        execution_rate = total_trades / signals_7_plus * 100 if signals_7_plus > 0 else 0
        print(f"信号执行率: {execution_rate:.1f}% ({total_trades}/{signals_7_plus})")

        # 3. 盈亏分析
        print(f"\n📈 盈亏详细分析:")

        profitable_trades = [t for t in trades if t['pnl_usdt'] > 0]
        losing_trades = [t for t in trades if t['pnl_usdt'] < 0]
        breakeven_trades = [t for t in trades if t['pnl_usdt'] == 0]

        win_rate = len(profitable_trades) / total_trades * 100 if total_trades > 0 else 0

        print(f"胜率: {win_rate:.1f}% ({len(profitable_trades)}/{total_trades})")
        print(f"平局: {len(breakeven_trades)} 笔")
        print(f"败率: {100-win_rate:.1f}% ({len(losing_trades)}/{total_trades})")

        # 总盈亏
        total_pnl = sum(t['pnl_usdt'] for t in trades)
        avg_pnl = total_pnl / total_trades

        print(f"\n💰 盈亏统计:")
        print(f"总盈亏: {total_pnl:+.2f} USDT")
        print(f"平均每笔: {avg_pnl:+.3f} USDT")

        if profitable_trades:
            avg_win = sum(t['pnl_usdt'] for t in profitable_trades) / len(profitable_trades)
            max_win = max(t['pnl_usdt'] for t in profitable_trades)
            print(f"平均盈利: +{avg_win:.3f} USDT")
            print(f"最大盈利: +{max_win:.3f} USDT")

        if losing_trades:
            avg_loss = sum(t['pnl_usdt'] for t in losing_trades) / len(losing_trades)
            max_loss = min(t['pnl_usdt'] for t in losing_trades)
            print(f"平均亏损: {avg_loss:.3f} USDT")
            print(f"最大亏损: {max_loss:.3f} USDT")

            # 盈亏比
            if avg_loss < 0:
                profit_loss_ratio = abs(avg_win / avg_loss) if profitable_trades else 0
                print(f"盈亏比: {profit_loss_ratio:.2f}:1")

        # 4. 币种分析
        print(f"\n🏆 币种表现分析:")
        symbol_stats = defaultdict(lambda: {'trades': 0, 'pnl': 0, 'wins': 0})

        for trade in trades:
            symbol = trade['symbol']
            symbol_stats[symbol]['trades'] += 1
            symbol_stats[symbol]['pnl'] += trade['pnl_usdt']
            if trade['pnl_usdt'] > 0:
                symbol_stats[symbol]['wins'] += 1

        # 按总盈亏排序
        sorted_symbols = sorted(symbol_stats.items(), key=lambda x: x[1]['pnl'], reverse=True)

        print("表现最好的币种:")
        for symbol, stats in sorted_symbols[:10]:
            win_rate = stats['wins'] / stats['trades'] * 100 if stats['trades'] > 0 else 0
            print(f"  {symbol}: {stats['pnl']:+.3f} USDT ({stats['trades']}笔, 胜率{win_rate:.0f}%)")

        if len(sorted_symbols) > 10:
            print("\n表现最差的币种:")
            for symbol, stats in sorted_symbols[-5:]:
                win_rate = stats['wins'] / stats['trades'] * 100 if stats['trades'] > 0 else 0
                print(f"  {symbol}: {stats['pnl']:+.3f} USDT ({stats['trades']}笔, 胜率{win_rate:.0f}%)")

        # 5. 亏损原因分析
        print(f"\n⚠️  亏损原因分析:")
        print(f"亏损交易详情:")
        for trade in losing_trades:
            print(f"  {trade['symbol']}: {trade['pnl_usdt']:.3f} USDT ({trade['pnl_pct']:+.2f}%) - {trade['timestamp'][:16]}")

        # 分析亏损模式
        loss_symbols = [t['symbol'] for t in losing_trades]
        loss_symbol_count = Counter(loss_symbols)

        print(f"\n亏损次数最多的币种:")
        for symbol, count in loss_symbol_count.most_common(5):
            total_trades_symbol = symbol_stats[symbol]['trades']
            loss_rate = count / total_trades_symbol * 100
            print(f"  {symbol}: {count}次亏损 / {total_trades_symbol}次交易 ({loss_rate:.0f}%亏损率)")

if __name__ == "__main__":
    try:
        analyze_trades()
    except FileNotFoundError:
        print("错误: 找不到 trading_engine.log 文件")
    except Exception as e:
        print(f"分析过程中出现错误: {e}")
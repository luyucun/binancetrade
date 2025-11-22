"""
日志24小时交易分析器 (log_24h_analyzer.py)
直接从日志文件分析最近24小时的交易记录，无需API
"""

import re
import os
from datetime import datetime, timedelta
from collections import defaultdict

def find_log_files():
    """查找可能的日志文件"""
    possible_files = [
        "trading_engine.log",
        "logs/trading_engine.log",
        "logs/trading.log",
        "trading.log"
    ]

    found_files = []
    for file_path in possible_files:
        if os.path.exists(file_path):
            found_files.append(file_path)

    return found_files

def parse_timestamp(log_line):
    """解析日志时间戳"""
    try:
        # 格式: 2025-11-20 09:54:46,730
        timestamp_str = log_line.split(' - ')[0]
        return datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S,%f')
    except:
        return None

def analyze_24h_trades_from_logs():
    """从日志分析24小时交易记录"""
    print("🔍 从日志文件分析最近24小时交易记录...")

    # 查找日志文件
    log_files = find_log_files()
    if not log_files:
        print("❌ 未找到日志文件")
        print("请确保以下文件之一存在:")
        print("- trading_engine.log")
        print("- logs/trading_engine.log")
        print("- logs/trading.log")
        print("- trading.log")
        return

    print(f"✅ 找到日志文件: {log_files}")

    # 设置24小时时间范围
    now = datetime.now()
    start_time = now - timedelta(hours=24)

    print(f"📅 分析时间范围: {start_time.strftime('%Y-%m-%d %H:%M')} 到 {now.strftime('%Y-%m-%d %H:%M')}")

    entries = []  # 入场记录
    exits = []    # 出场记录
    signals = []  # 信号记录

    for log_file in log_files:
        print(f"\n📄 分析日志文件: {log_file}")

        try:
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                for line_num, line in enumerate(f, 1):
                    # 解析时间戳
                    log_time = parse_timestamp(line)
                    if not log_time or log_time < start_time:
                        continue

                    # 解析入场信号
                    if "✓ 入场成功:" in line:
                        entry_match = re.search(r"✓ 入场成功: (\w+) 仓位大小: ([\d.]+) USDT", line)
                        if entry_match:
                            entries.append({
                                'time': log_time,
                                'symbol': entry_match.group(1),
                                'amount': float(entry_match.group(2)),
                                'line': line_num
                            })

                    # 解析出场信号
                    elif "✓ 出场成功:" in line and "盈亏:" in line:
                        exit_match = re.search(r"✓ 出场成功: (\w+).*?盈亏: ([-+]?[\d.]+) USDT", line)
                        if exit_match:
                            exits.append({
                                'time': log_time,
                                'symbol': exit_match.group(1),
                                'pnl': float(exit_match.group(2)),
                                'line': line_num
                            })

                    # 解析紧急平仓
                    elif "🚨" in line and "紧急平仓完成" in line:
                        emergency_match = re.search(r"(\w+): \[.*?\] 紧急平仓完成.*?盈亏: ([-+]?[\d.]+) USDT", line)
                        if emergency_match:
                            exits.append({
                                'time': log_time,
                                'symbol': emergency_match.group(1),
                                'pnl': float(emergency_match.group(2)),
                                'line': line_num,
                                'type': 'emergency'
                            })

                    # 解析信号生成
                    elif "生成信号" in line and "评分:" in line:
                        signal_match = re.search(r"(\w+): 生成信号 (\w+).*?\(评分: (\d+)\)", line)
                        if signal_match:
                            signals.append({
                                'time': log_time,
                                'symbol': signal_match.group(1),
                                'direction': signal_match.group(2),
                                'score': int(signal_match.group(3)),
                                'line': line_num
                            })

        except Exception as e:
            print(f"⚠️ 读取日志文件失败: {e}")
            continue

    # 显示分析结果
    display_log_analysis(entries, exits, signals, start_time, now)

def display_log_analysis(entries, exits, signals, start_time, end_time):
    """显示日志分析结果"""
    print(f"\n" + "="*80)
    print("📊 24小时交易分析结果")
    print("="*80)

    # 入场统计
    print(f"\n🚀 入场记录 ({len(entries)} 次):")
    if entries:
        print(f"{'时间':<17} {'币种':<12} {'仓位金额':<10}")
        print("-" * 45)

        entry_by_symbol = defaultdict(list)
        total_entry_amount = 0

        for entry in sorted(entries, key=lambda x: x['time'], reverse=True):
            print(f"{entry['time'].strftime('%m-%d %H:%M:%S'):<17} "
                  f"{entry['symbol']:<12} "
                  f"{entry['amount']:<10.2f}")

            entry_by_symbol[entry['symbol']].append(entry)
            total_entry_amount += entry['amount']

        print(f"\n入场汇总: {len(entry_by_symbol)} 个币种, 总金额: {total_entry_amount:.2f} USDT")

    # 出场统计
    print(f"\n📤 出场记录 ({len(exits)} 次):")
    if exits:
        print(f"{'时间':<17} {'币种':<12} {'盈亏':<10} {'类型':<8}")
        print("-" * 50)

        exit_by_symbol = defaultdict(list)
        total_pnl = 0
        emergency_exits = 0

        for exit in sorted(exits, key=lambda x: x['time'], reverse=True):
            exit_type = exit.get('type', 'normal')
            if exit_type == 'emergency':
                emergency_exits += 1

            print(f"{exit['time'].strftime('%m-%d %H:%M:%S'):<17} "
                  f"{exit['symbol']:<12} "
                  f"{exit['pnl']:+<10.2f} "
                  f"{exit_type:<8}")

            exit_by_symbol[exit['symbol']].append(exit)
            total_pnl += exit['pnl']

        wins = len([e for e in exits if e['pnl'] > 0])
        losses = len(exits) - wins
        win_rate = wins / len(exits) * 100 if exits else 0

        print(f"\n出场汇总:")
        print(f"- 总盈亏: {total_pnl:+.2f} USDT")
        print(f"- 胜率: {win_rate:.1f}% ({wins}胜 {losses}负)")
        print(f"- 紧急平仓: {emergency_exits} 次")

    # 信号统计
    print(f"\n🎯 信号生成 ({len(signals)} 次):")
    if signals:
        signal_stats = defaultdict(int)
        direction_stats = defaultdict(int)
        score_stats = defaultdict(int)

        for signal in signals:
            signal_stats[signal['symbol']] += 1
            direction_stats[signal['direction']] += 1
            score_stats[signal['score']] += 1

        print(f"- 总信号数: {len(signals)}")
        print(f"- 多头信号: {direction_stats.get('BULLISH', 0)}")
        print(f"- 空头信号: {direction_stats.get('BEARISH', 0)}")
        print(f"- 平均评分: {sum(s['score'] for s in signals) / len(signals):.1f}")

    # 交易配对分析
    print(f"\n🔄 交易配对分析:")
    analyze_trade_pairs(entries, exits)

    # 活跃币种统计
    print(f"\n📈 活跃币种 (最近24小时):")
    all_symbols = set()
    all_symbols.update(e['symbol'] for e in entries)
    all_symbols.update(e['symbol'] for e in exits)
    all_symbols.update(s['symbol'] for s in signals)

    if all_symbols:
        symbol_activity = {}
        for symbol in all_symbols:
            entry_count = len([e for e in entries if e['symbol'] == symbol])
            exit_count = len([e for e in exits if e['symbol'] == symbol])
            signal_count = len([s for s in signals if s['symbol'] == symbol])
            symbol_pnl = sum([e['pnl'] for e in exits if e['symbol'] == symbol])

            symbol_activity[symbol] = {
                'entries': entry_count,
                'exits': exit_count,
                'signals': signal_count,
                'pnl': symbol_pnl
            }

        print(f"{'币种':<12} {'入场':<6} {'出场':<6} {'信号':<6} {'盈亏':<10}")
        print("-" * 45)

        for symbol in sorted(symbol_activity.keys()):
            activity = symbol_activity[symbol]
            print(f"{symbol:<12} {activity['entries']:<6} {activity['exits']:<6} "
                  f"{activity['signals']:<6} {activity['pnl']:+<10.2f}")

def analyze_trade_pairs(entries, exits):
    """分析入场出场配对"""
    # 简化版本：按币种统计
    entry_count = defaultdict(int)
    exit_count = defaultdict(int)

    for entry in entries:
        entry_count[entry['symbol']] += 1

    for exit in exits:
        exit_count[exit['symbol']] += 1

    all_symbols = set(entry_count.keys()) | set(exit_count.keys())

    if all_symbols:
        print(f"{'币种':<12} {'入场次数':<8} {'出场次数':<8} {'状态':<10}")
        print("-" * 45)

        open_positions = 0
        for symbol in sorted(all_symbols):
            entries = entry_count[symbol]
            exits = exit_count[symbol]
            status = "已平仓" if entries == exits else f"持仓中({entries-exits})" if entries > exits else "异常"

            if entries > exits:
                open_positions += entries - exits

            print(f"{symbol:<12} {entries:<8} {exits:<8} {status:<10}")

        print(f"\n当前可能的开仓数量: {open_positions}")

def main():
    """主函数"""
    print("=" * 60)
    print("📊 24小时日志交易分析器")
    print("=" * 60)
    print("从交易引擎日志文件分析最近24小时的交易活动")
    print()

    try:
        analyze_24h_trades_from_logs()
    except Exception as e:
        print(f"❌ 分析失败: {e}")
        import traceback
        traceback.print_exc()

    print(f"\n✅ 分析完成!")

    # 防止闪退
    try:
        input("\n按Enter键退出...")
    except:
        pass

if __name__ == "__main__":
    main()
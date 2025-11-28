#!/usr/bin/env python3
"""手动计算真实的盈亏"""

# 从日志中提取的所有止损平仓亏损记录
losses = [
    -0.02,  # MEMEUSDT
    -0.00,  # RSRUSDT
    -0.02,  # MEMEUSDT (重复)
    -0.00,  # USDCUSDT
    -0.07,  # PUMPUSDT
    -0.07,  # TURBOUSDT
    -0.15,  # GPSUSDT
    -0.07,  # PUMPUSDT
    -0.05,  # LINEAUSDT
    -0.00,  # XVGUSDT
    -0.04,  # TLMUSDT
    -0.06,  # PENGUUSDT
    -0.07,  # TURBOUSDT
    -0.06,  # RSRUSDT
    -0.19,  # TNSRUSDT ⚠️ 最大亏损
    -0.07,  # XPLUSDT
    -0.09,  # HEMIUSDT
    -0.00,  # USDCUSDT
    -0.05,  # LINEAUSDT
    -0.08,  # FUNUSDT
    -0.01,  # PENGUUSDT
    -0.02,  # MEMEUSDT
    -0.13,  # ACTUSDT
    -0.01,  # TRXUSDT
    -0.04,  # RSRUSDT
    -0.05,  # HFTUSDT
    -0.00,  # XRPUSDT
    -0.00,  # XRPUSDT (重复)
    -0.05,  # ZKUSDT
    -0.14,  # VTHOUSDT
    -0.06,  # REZUSDT
    -0.02,  # FUNUSDT
    -0.02,  # FUNUSDT (重复)
    -0.02,  # PUMPUSDT
    -0.02,  # PUMPUSDT (重复)
    -0.00,  # PENGUUSDT
    -0.00,  # PENGUUSDT (重复)
    -0.00,  # USDCUSDT
    -0.04,  # XVGUSDT
    -0.06,  # STRKUSDT
    -0.04,  # PUMPUSDT
    -0.07,  # GPSUSDT
    -0.03,  # REZUSDT
    -0.00,  # USDCUSDT
    -0.04,  # MAVUSDT
    -0.01,  # TRXUSDT
    -0.05,  # HEMIUSDT
    -0.07,  # ONEUSDT
    -0.07,  # REZUSDT
    -0.04,  # WLFIUSDT
    -0.11,  # TNSRUSDT
    -0.03,  # HBARUSDT
    -0.02,  # DOGEUSDT
    -0.05,  # TURBOUSDT (最后时段)
    -0.08,  # STRKUSDT (最后时段)
    -0.02,  # MEMEUSDT (最后时段)
]

# 计算总亏损
total_loss = sum(losses)
count_loss = len(losses)
avg_loss = total_loss / count_loss

print("=" * 80)
print("⚠️  实际亏损统计")
print("=" * 80)
print(f"亏损交易数: {count_loss} 笔")
print(f"总亏损: {total_loss:.2f} USDT")
print(f"平均亏损: {avg_loss:.3f} USDT")
print(f"最大单笔亏损: {min(losses):.2f} USDT")
print()

# 止盈交易数（从之前统计）
profit_trades_count = 73

# 如果日志显示总盈亏+5.27，那么总盈利应该是
if total_loss < 0:  # 确保亏损是负数
    # 总盈亏 = 总盈利 + 总亏损
    # 5.27 = 总盈利 + (-X)
    # 总盈利 = 5.27 - 亏损
    estimated_total_profit = 5.27 - total_loss

    print("=" * 80)
    print("📊 推算盈利数据 (基于会话统计+5.27 USDT)")
    print("=" * 80)
    print(f"推算总盈利: +{estimated_total_profit:.2f} USDT")
    print(f"盈利交易数: {profit_trades_count} 笔")
    if profit_trades_count > 0:
        avg_profit = estimated_total_profit / profit_trades_count
        print(f"平均盈利: +{avg_profit:.3f} USDT")
    print()

    # 总体统计
    total_trades = count_loss + profit_trades_count
    win_rate = (profit_trades_count / total_trades * 100) if total_trades > 0 else 0

    print("=" * 80)
    print("🎯 总体统计")
    print("=" * 80)
    print(f"总交易数: {total_trades} 笔")
    print(f"盈利交易: {profit_trades_count} 笔")
    print(f"亏损交易: {count_loss} 笔")
    print(f"胜率: {win_rate:.1f}%")
    print(f"总盈亏: +5.27 USDT (日志统计)")
    print()

    if profit_trades_count > 0 and count_loss > 0:
        profit_loss_ratio = avg_profit / abs(avg_loss)
        print(f"盈亏比: {profit_loss_ratio:.2f}:1")
    print()

print("=" * 80)
print("⚠️  重要提示")
print("=" * 80)
print("1. 日志中的P&L可能不包含交易手续费")
print("2. 实际账户盈亏 = 日志盈亏 - 手续费")
print("3. Binance期货合约手续费:")
print("   - Maker: 0.02% (做市商)")
print("   - Taker: 0.05% (吃单)")
print("4. 如果全部是Taker订单，估算手续费:")
total_volume = total_trades * 10  # 每笔10 USDT
estimated_fees = total_volume * 0.0005 * 2  # 开仓+平仓
print(f"   总交易量: {total_volume:.0f} USDT")
print(f"   估算手续费: -{estimated_fees:.2f} USDT")
print(f"   扣除手续费后净盈亏: {5.27 - estimated_fees:+.2f} USDT")
print("=" * 80)

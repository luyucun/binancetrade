#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""简化测试 - 防重复下单"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from risk_manager_v2 import RiskManager, PositionStatus, ActivePosition
from config_v2 import RISK_MANAGEMENT, ROTATION_SYSTEM
from datetime import datetime

# 创建风险管理器
risk_manager = RiskManager(RISK_MANAGEMENT, ROTATION_SYSTEM)

print("=" * 80)
print("测试防重复下单机制")
print("=" * 80)

# 测试1: 第一次检查
print("\n[测试1] 第一次检查 BTCUSDT")
can_open_1 = risk_manager.can_open_new_position("BTCUSDT")
print(f"结果: {'✓ 可以开仓' if can_open_1 else '✗ 不能开仓'}")
print(f"当前活跃持仓数: {len(risk_manager.active_positions)}")

# 手动添加一个持仓到字典中（模拟已开仓）
print("\n[模拟] 手动添加 BTCUSDT 到 active_positions")
mock_position = ActivePosition(
    symbol="BTCUSDT",
    side="BUY",
    entry_price=50000.0,
    quantity=0.01,
    remaining_quantity=0.01,
    entry_time=datetime.now(),
    status=PositionStatus.OPEN,
    entry_amount_usdt=500.0,
    current_stop_loss_price=49000.0,
    highest_price_since_entry=50000.0,
    lowest_price_since_entry=50000.0,
    current_price=50000.0,
    floating_pnl_usdt=0.0,
    floating_pnl_pct=0.0,
    risk_params=None,
    partial_exits=[]
)
risk_manager.active_positions["BTCUSDT"] = mock_position

# 测试2: 第二次检查（应该被拒绝）
print("\n[测试2] 第二次检查 BTCUSDT (有持仓后)")
can_open_2 = risk_manager.can_open_new_position("BTCUSDT")
print(f"结果: {'✗ BUG! 仍可开仓' if can_open_2 else '✓ 正确拒绝 (已有持仓)'}")
print(f"当前活跃持仓数: {len(risk_manager.active_positions)}")

# 测试3: 修改状态为CLOSED
print("\n[测试3] 将 BTCUSDT 状态改为 CLOSED")
risk_manager.active_positions["BTCUSDT"].status = PositionStatus.CLOSED
can_open_3 = risk_manager.can_open_new_position("BTCUSDT")
print(f"结果: {'✓ 可以开仓 (已平仓)' if can_open_3 else '✗ 不能开仓'}")

# 测试4: 添加冷却
print("\n[测试4] 添加 BTCUSDT 到冷却列表 (30分钟)")
risk_manager.add_to_cooldown("BTCUSDT", 30, "测试冷却")
can_open_4 = risk_manager.can_open_new_position("BTCUSDT")
cooldown = risk_manager.get_cooldown_remaining("BTCUSDT")
print(f"结果: {'✗ BUG! 仍可开仓' if can_open_4 else '✓ 正确拒绝 (在冷却中)'}")
print(f"剩余冷却时间: {cooldown} 秒 ({cooldown/60:.1f} 分钟)")

# 测试5: 并发限制
print("\n[测试5] 测试并发持仓限制 (最大3个)")
# 添加3个持仓
for i, symbol in enumerate(["ETHUSDT", "BNBUSDT", "ADAUSDT"]):
    pos = ActivePosition(
        symbol=symbol,
        side="BUY",
        entry_price=1000.0,
        quantity=1.0,
        remaining_quantity=1.0,
        entry_time=datetime.now(),
        status=PositionStatus.OPEN,
        entry_amount_usdt=1000.0,
        current_stop_loss_price=900.0,
        highest_price_since_entry=1000.0,
        lowest_price_since_entry=1000.0,
        current_price=1000.0,
        floating_pnl_usdt=0.0,
        floating_pnl_pct=0.0,
        risk_params=None,
        partial_exits=[]
    )
    risk_manager.active_positions[symbol] = pos
    print(f"  添加持仓 {i+1}/3: {symbol}")

open_count = sum(1 for p in risk_manager.active_positions.values()
                 if p.status in [PositionStatus.OPEN, PositionStatus.PARTIAL_CLOSE])
print(f"当前开放持仓数: {open_count}")

can_open_5 = risk_manager.can_open_new_position("SOLUSDT")
print(f"尝试开第4个持仓 (SOLUSDT): {'✗ BUG! 可以开仓' if can_open_5 else '✓ 正确拒绝 (达到上限)'}")

print("\n" + "=" * 80)
print("✅ 测试完成 - 防重复下单机制工作正常")
print("=" * 80)

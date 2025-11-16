#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试是否会重复下单"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from risk_manager_v2 import RiskManager, PositionStatus
from config_v2 import RISK_MANAGEMENT, ROTATION_SYSTEM

# 创建风险管理器
risk_manager = RiskManager(RISK_MANAGEMENT, ROTATION_SYSTEM)

print("=" * 80)
print("测试防重复下单机制")
print("=" * 80)

# 测试1: 第一次开仓
print("\n[测试1] 第一次尝试开仓 BTCUSDT")
can_open_1 = risk_manager.can_open_new_position("BTCUSDT")
print(f"结果: {'✓ 可以开仓' if can_open_1 else '✗ 不能开仓'}")

# 模拟开仓
if can_open_1:
    position = risk_manager.add_position(
        symbol="BTCUSDT",
        side="BUY",
        entry_price=50000.0,
        quantity=0.01,
        entry_amount_usdt=500.0,
        initial_stop_loss_price=49000.0,
        take_profit_price=52000.0,
        atr=500.0
    )
    print(f"✓ 开仓成功: {position.symbol} @ {position.entry_price}")

# 测试2: 第二次尝试开仓同一个币种
print("\n[测试2] 第二次尝试开仓 BTCUSDT (应该被拒绝)")
can_open_2 = risk_manager.can_open_new_position("BTCUSDT")
print(f"结果: {'✗ 意外！仍然可以开仓 (BUG!)' if can_open_2 else '✓ 正确拒绝重复开仓'}")

# 测试3: 查看持仓状态
print("\n[测试3] 当前持仓状态")
if "BTCUSDT" in risk_manager.active_positions:
    pos = risk_manager.active_positions["BTCUSDT"]
    print(f"BTCUSDT: status={pos.status.value}, quantity={pos.quantity}")

# 测试4: 模拟平仓后再次尝试
print("\n[测试4] 平仓后立即尝试开仓 (应该在冷却中)")
if "BTCUSDT" in risk_manager.active_positions:
    risk_manager.active_positions["BTCUSDT"].status = PositionStatus.CLOSED
    # 添加冷却
    risk_manager.add_to_cooldown("BTCUSDT", 30, "测试冷却")

can_open_3 = risk_manager.can_open_new_position("BTCUSDT")
print(f"结果: {'✗ 意外！可以开仓 (BUG!)' if can_open_3 else '✓ 正确拒绝 (在冷却中)'}")

cooldown_remaining = risk_manager.get_cooldown_remaining("BTCUSDT")
print(f"剩余冷却时间: {cooldown_remaining} 秒")

print("\n" + "=" * 80)
print("测试完成")
print("=" * 80)

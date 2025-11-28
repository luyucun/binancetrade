"""
持仓监控模块 (position_monitor_v2.py)
负责实时监控持仓的止损、止盈、追踪等
"""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass

from risk_manager_v2 import RiskManager, ActivePosition, PositionStatus


logger = logging.getLogger(__name__)


@dataclass
class MonitoringEvent:
    """监控事件"""
    timestamp: datetime
    event_type: str  # "STOP_LOSS", "TAKE_PROFIT_STAGE1", etc.
    symbol: str
    exit_price: float
    exit_quantity: float
    profit_loss_usdt: float
    profit_loss_pct: float
    details: str


class PositionMonitor:
    """持仓监控器"""

    def __init__(self, risk_manager: RiskManager):
        """
        初始化持仓监控器

        Args:
            risk_manager: 风险管理器实例
        """
        self.risk_manager = risk_manager
        self.monitoring_events: List[MonitoringEvent] = []
        self.last_check_time: Dict[str, datetime] = {}

    # ==================== 主要监控方法 ====================
    def monitor_all_positions(
        self,
        current_prices: Dict[str, float],
        atr_values: Dict[str, float]
    ) -> Tuple[List[str], List[MonitoringEvent]]:
        """
        监控所有活跃持仓

        Args:
            current_prices: {symbol: price}
            atr_values: {symbol: atr}

        Returns:
            (需要平仓的币种列表, 监控事件列表)
        """
        symbols_to_close = []
        events = []

        for symbol, position in list(self.risk_manager.active_positions.items()):
            # 跳过已平仓的头寸
            if position.status == PositionStatus.CLOSED:
                continue

            # 获取当前价格和ATR
            if symbol not in current_prices or symbol not in atr_values:
                continue

            current_price = current_prices[symbol]
            atr = atr_values[symbol]

            # 更新持仓信息
            should_close, update_events = self.risk_manager.update_position(
                symbol, current_price, atr
            )

            # 检查是否启用了追踪止损(stage3触发)
            stage3_triggered = any(e['stage'] == 3 for e in position.partial_exits)
            if stage3_triggered and position.risk_params.trailing_stop_enabled:
                trailing_triggered = self.update_trailing_stop(
                    position, current_price, atr,
                    position.risk_params.trailing_stop_distance_atr
                )
                if trailing_triggered:
                    should_close = True
                    update_events.append("触发追踪止损")

            # 处理监控事件
            for event_desc in update_events:
                logger.info(f"{symbol}: {event_desc}")
                events.append(self._create_monitoring_event(
                    symbol, position, current_price, event_desc
                ))

            # 如果需要平仓
            if should_close:
                symbols_to_close.append(symbol)
                logger.warning(f"{symbol}: 触发平仓事件")

        return symbols_to_close, events

    # ==================== 持仓时间检查 ====================
    def _check_max_hold_time(
        self,
        position: ActivePosition,
        max_minutes: int = 90
    ) -> bool:
        """
        检查持仓时间是否超过限制

        注意：按你的要求，每次平仓后重新计时
        所以我们检查的是从entry_time或最后一次partial_exit_time到现在

        Args:
            position: 持仓对象
            max_minutes: 最大持仓时间(分钟)

        Returns:
            是否超时
        """
        # 获取参考时间点
        if position.partial_exits:
            # 最后一次平仓的时间
            reference_time = position.partial_exits[-1]['time']
        else:
            # 开仓时间
            reference_time = position.entry_time

        elapsed_minutes = (datetime.now() - reference_time).total_seconds() / 60
        return elapsed_minutes > max_minutes

    # ==================== 保本机制 ====================
    def check_breakeven_move(
        self,
        position: ActivePosition,
        current_price: float,
        atr: float
    ) -> bool:
        """
        检查并执行保本机制

        当浮动利润达到0.5×ATR时，将止损抬升到开仓价+0.1%

        Args:
            position: 持仓对象
            current_price: 当前价格
            atr: ATR值

        Returns:
            是否执行了保本机制
        """
        breakeven_trigger = 0.5 * atr  # 0.5×ATR
        breakeven_stop_distance = 0.001  # 0.1%

        if position.side == 'BUY':
            floating_profit = (current_price - position.entry_price) * position.remaining_quantity
            if floating_profit >= breakeven_trigger:
                # 计算新止损
                new_stop = position.entry_price * (1 + breakeven_stop_distance)
                if new_stop > position.current_stop_loss_price:
                    position.current_stop_loss_price = new_stop
                    logger.info(
                        f"{position.symbol}: 触发保本机制，止损抬升到 {new_stop:.4f}"
                    )
                    return True

        else:  # SELL
            floating_profit = (position.entry_price - current_price) * position.remaining_quantity
            if floating_profit >= breakeven_trigger:
                # 计算新止损
                new_stop = position.entry_price * (1 - breakeven_stop_distance)
                if new_stop < position.current_stop_loss_price:
                    position.current_stop_loss_price = new_stop
                    logger.info(
                        f"{position.symbol}: 触发保本机制，止损抬升到 {new_stop:.4f}"
                    )
                    return True

        return False

    # ==================== 追踪止损 ====================
    def update_trailing_stop(
        self,
        position: ActivePosition,
        current_price: float,
        atr: float,
        trailing_atr_multiplier: float = 1.0
    ) -> bool:
        """
        更新追踪止损

        Args:
            position: 持仓对象
            current_price: 当前价格
            atr: ATR值
            trailing_atr_multiplier: 追踪止损倍数

        Returns:
            是否触发了追踪止损
        """
        trailing_stop_distance = atr * trailing_atr_multiplier

        if position.side == 'BUY':
            # 只在价格上升时更新止损
            if current_price > position.highest_price_since_entry:
                position.highest_price_since_entry = current_price

            # 更新止损到highest - trailing_distance
            new_stop = position.highest_price_since_entry - trailing_stop_distance
            if new_stop > position.current_stop_loss_price:
                position.current_stop_loss_price = new_stop
                logger.debug(
                    f"{position.symbol}: 更新追踪止损到 {new_stop:.4f}"
                )

            # 检查是否触发止损
            if current_price <= position.current_stop_loss_price:
                return True

        else:  # SELL
            # 只在价格下降时更新止损
            if current_price < position.lowest_price_since_entry:
                position.lowest_price_since_entry = current_price

            # 更新止损到lowest + trailing_distance
            new_stop = position.lowest_price_since_entry + trailing_stop_distance
            if new_stop < position.current_stop_loss_price:
                position.current_stop_loss_price = new_stop
                logger.debug(
                    f"{position.symbol}: 更新追踪止损到 {new_stop:.4f}"
                )

            # 检查是否触发止损
            if current_price >= position.current_stop_loss_price:
                return True

        return False

    # ==================== 早期止损缓冲 ====================
    def check_early_stop_loss_buffer(
        self,
        position: ActivePosition,
        current_price: float,
        min_hold_minutes: int = 8,
        early_stop_buffer_pct: float = 0.03
    ) -> bool:
        """
        检查是否在最小持仓时间内且损失超过缓冲百分比

        在这种情况下，即使达到止损价也不立即止损，
        给策略一些"缓冲"时间进行调整

        Args:
            position: 持仓对象
            current_price: 当前价格
            min_hold_minutes: 最小持仓时间(分钟)
            early_stop_buffer_pct: 早期止损缓冲百分比

        Returns:
            是否在缓冲期内
        """
        # 计算持仓时长
        elapsed_minutes = (datetime.now() - position.entry_time).total_seconds() / 60

        if elapsed_minutes < min_hold_minutes:
            # 在最小持仓时间内
            if position.side == 'BUY':
                loss_pct = (position.entry_price - current_price) / position.entry_price
                if loss_pct < early_stop_buffer_pct:
                    # 损失在缓冲范围内，不止损
                    return True

            else:  # SELL
                loss_pct = (current_price - position.entry_price) / position.entry_price
                if loss_pct < early_stop_buffer_pct:
                    # 损失在缓冲范围内，不止损
                    return True

        return False

    # ==================== 风险调整 ====================
    def should_reduce_positions(
        self,
        market_health_score: float = 0.5
    ) -> bool:
        """
        根据市场状况判断是否应该减少持仓

        Args:
            market_health_score: 市场健康度评分(0-1)

        Returns:
            是否应该减少持仓
        """
        # 如果市场健康度太低，应该减少持仓
        return market_health_score < 0.3

    # ==================== 事件记录 ====================
    def _create_monitoring_event(
        self,
        symbol: str,
        position: ActivePosition,
        current_price: float,
        event_desc: str
    ) -> MonitoringEvent:
        """
        创建监控事件记录

        Args:
            symbol: 币种
            position: 持仓对象
            current_price: 当前价格
            event_desc: 事件描述

        Returns:
            监控事件对象
        """
        # 从描述推断事件类型和对应数量
        exit_quantity = position.remaining_quantity  # 默认使用剩余数量

        if "止损" in event_desc:
            event_type = "STOP_LOSS"
            # 止损是全部平仓，使用remaining_quantity
        elif "Stage 1" in event_desc:
            event_type = "TAKE_PROFIT_STAGE1"
            # 查找Stage1的实际平仓数量
            for partial_exit in position.partial_exits:
                if partial_exit['stage'] == 1:
                    exit_quantity = partial_exit['quantity']
                    break
        elif "Stage 2" in event_desc:
            event_type = "TAKE_PROFIT_STAGE2"
            # 查找Stage2的实际平仓数量
            for partial_exit in position.partial_exits:
                if partial_exit['stage'] == 2:
                    exit_quantity = partial_exit['quantity']
                    break
        elif "Stage 3" in event_desc:
            event_type = "TAKE_PROFIT_STAGE3"
            # Stage3现在是0数量(只启用追踪止损)
            for partial_exit in position.partial_exits:
                if partial_exit['stage'] == 3:
                    exit_quantity = partial_exit['quantity']  # 应为0
                    break
        else:
            event_type = "OTHER"

        return MonitoringEvent(
            timestamp=datetime.now(),
            event_type=event_type,
            symbol=symbol,
            exit_price=current_price,
            exit_quantity=exit_quantity,  # 使用实际平仓数量
            profit_loss_usdt=position.floating_pnl_usdt,
            profit_loss_pct=position.floating_pnl_pct,
            details=event_desc
        )

    def get_monitoring_summary(self) -> Dict:
        """获取监控摘要"""
        open_positions = [p for p in self.risk_manager.active_positions.values()
                         if p.status in [PositionStatus.OPEN, PositionStatus.PARTIAL_CLOSE]]

        total_floating_pnl = sum(p.floating_pnl_usdt for p in open_positions)
        total_events = len(self.monitoring_events)

        return {
            'monitored_positions': len(open_positions),
            'total_floating_pnl': total_floating_pnl,
            'total_events': total_events,
            'last_event': self.monitoring_events[-1] if self.monitoring_events else None
        }


# ==================== 测试函数 ====================
if __name__ == "__main__":
    print("持仓监控模块已创建")

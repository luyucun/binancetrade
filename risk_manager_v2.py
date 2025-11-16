"""
风险管理模块 (risk_manager_v2.py)
用于管理仓位大小、止损止盈、风险监控等
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import logging
import json
from datetime import datetime, timedelta
from pathlib import Path

from config_v2 import RISK_MANAGEMENT, ROTATION_SYSTEM


logger = logging.getLogger(__name__)


class PositionStatus(Enum):
    """持仓状态"""
    OPEN = "OPEN"
    PARTIAL_CLOSE = "PARTIAL_CLOSE"
    CLOSED = "CLOSED"


@dataclass
class StageExitLevel:
    """分阶段平仓级别"""
    stage: int  # 阶段1、2、3
    trigger_profit_atr_multiplier: float  # 触发利润倍数
    close_percentage: float  # 平仓比例
    stop_loss_action: str  # 止损操作（保本、抬升等）


@dataclass
class RiskParameters:
    """风险参数"""
    position_size_usdt: float  # 仓位大小(USDT)
    initial_stop_loss_price: float  # 初始止损价
    trailing_stop_enabled: bool  # 是否启用追踪止损
    trailing_stop_distance_atr: float  # 追踪止损距离(ATR倍数)
    stage_exits: List[StageExitLevel]  # 分阶段平仓


@dataclass
class ActivePosition:
    """活跃持仓"""
    symbol: str
    side: str  # BUY 或 SELL
    entry_time: datetime
    entry_price: float
    quantity: float
    entry_amount_usdt: float

    # 风险参数
    risk_params: RiskParameters

    # 当前状态
    status: PositionStatus = PositionStatus.OPEN
    current_price: float = 0.0
    floating_pnl_usdt: float = 0.0
    floating_pnl_pct: float = 0.0

    # 分阶段平仓记录
    partial_exits: List[Dict] = None  # [{'stage': 1, 'time': ..., 'qty': ..., 'price': ...}]
    remaining_quantity: float = 0.0

    # 止损追踪
    current_stop_loss_price: float = 0.0
    highest_price_since_entry: float = 0.0
    lowest_price_since_entry: float = 0.0

    def __post_init__(self):
        if self.partial_exits is None:
            self.partial_exits = []
        self.remaining_quantity = self.quantity
        self.current_stop_loss_price = self.risk_params.initial_stop_loss_price
        self.highest_price_since_entry = self.entry_price
        self.lowest_price_since_entry = self.entry_price


class RiskManager:
    """风险管理器"""

    def __init__(self, config=RISK_MANAGEMENT, rotation_config=ROTATION_SYSTEM):
        """初始化风险管理器"""
        self.config = config
        self.rotation_config = rotation_config
        self.active_positions: Dict[str, ActivePosition] = {}
        self.cooldown_symbols: Dict[str, datetime] = {}  # 冷却的币种
        self.total_account_usdt = 1000.0  # 假设账户初始资金
        self.max_concurrent_positions = rotation_config['symbol_rotation']['max_concurrent_positions']

        # 连续亏损追踪
        self.recent_losses: Dict[str, List[datetime]] = {}  # {symbol: [loss_time1, loss_time2, ...]}
        self.consecutive_loss_threshold = 3  # 连续亏损阈值

    # ==================== 仓位管理 ====================
    def calculate_position_size(
        self,
        entry_price: float,
        stop_loss_price: float,
        signal_score: int = 5,
        confidence: float = 0.7,
        correlation_penalty: float = 1.0
    ) -> float:
        """
        根据风险回报比计算仓位大小

        Args:
            entry_price: 入场价格
            stop_loss_price: 止损价格
            signal_score: 信号评分(5-12分)
            confidence: 信心度
            correlation_penalty: 相关性惩罚系数(0.5-1.0, 相关性高时降低)

        Returns:
            仓位大小(USDT)
        """
        base_amount = self.config['position_sizing']['base_amount']
        leverage = self.config['position_sizing']['leverage']
        max_position_ratio = self.config['position_sizing']['max_position_ratio']
        min_notional = self.config['position_sizing'].get('min_notional', 5.0)

        # 基础仓位
        position_size = base_amount * leverage

        # 根据评分采用分段倍率调整 (V2.0需求)
        if signal_score <= 7:
            score_multiplier = 0.5  # 50%基础仓位
        elif signal_score <= 10:
            score_multiplier = 1.0  # 100%标准仓位
        else:  # 11-12分
            score_multiplier = 1.5  # 150%增强仓位

        position_size *= score_multiplier

        # 根据信心度调整
        position_size *= confidence

        # 应用相关性惩罚
        position_size *= correlation_penalty

        # 确保满足最小notional要求
        if position_size < min_notional:
            logger.warning(f"仓位大小 {position_size:.2f} USDT < 最小值 {min_notional} USDT，调整到最小值")
            position_size = min_notional

        # 检查仓位比例限制
        max_single_position = self.total_account_usdt * max_position_ratio
        position_size = min(position_size, max_single_position)

        # 检查总风险暴露，超出时按比例缩放
        current_total_exposure = sum(p.entry_amount_usdt for p in self.active_positions.values())
        max_total_exposure = self.total_account_usdt * self.config['position_sizing']['max_total_exposure']
        remaining_capacity = max(0, max_total_exposure - current_total_exposure)

        if position_size > remaining_capacity:
            if remaining_capacity > 0:
                # 超出总敞口，按比例缩放
                logger.warning(f"总风险暴露接近上限，仓位从 {position_size:.2f} 缩减至 {remaining_capacity:.2f} USDT")
                position_size = remaining_capacity
            else:
                logger.warning("总风险暴露已达上限，无法开新仓")
                return 0.0

        return position_size

    # ==================== 止损止盈管理 ====================
    def create_risk_parameters(
        self,
        entry_price: float,
        atr: float,
        direction: str,
        position_size_usdt: float
    ) -> RiskParameters:
        """
        创建风险参数

        Args:
            entry_price: 入场价格
            atr: 平均真实波幅
            direction: 方向(BUY/SELL)
            position_size_usdt: 仓位大小

        Returns:
            风险参数对象
        """
        # 初始止损
        initial_stop_multiplier = self.config['stop_loss']['initial_atr_multiplier']
        if direction == 'BUY':
            initial_stop_loss = entry_price - (atr * initial_stop_multiplier)
        else:
            initial_stop_loss = entry_price + (atr * initial_stop_multiplier)

        # 确保止损在最小/最大范围内
        min_stop_pct = self.config['stop_loss']['min_stop_pct']
        max_stop_pct = self.config['stop_loss']['max_stop_pct']

        actual_stop_distance = abs(entry_price - initial_stop_loss) / entry_price * 100
        actual_stop_distance = max(min_stop_pct, min(actual_stop_distance, max_stop_pct))

        if direction == 'BUY':
            initial_stop_loss = entry_price * (1 - actual_stop_distance / 100)
        else:
            initial_stop_loss = entry_price * (1 + actual_stop_distance / 100)

        # 分阶段平仓
        tp_config = self.config['take_profit']
        stage_exits = []

        stage_exit_1 = StageExitLevel(
            stage=1,
            trigger_profit_atr_multiplier=tp_config['stage1']['trigger'],
            close_percentage=tp_config['stage1']['close_pct'],
            stop_loss_action="move_to_breakeven"
        )
        stage_exits.append(stage_exit_1)

        stage_exit_2 = StageExitLevel(
            stage=2,
            trigger_profit_atr_multiplier=tp_config['stage2']['trigger'],
            close_percentage=tp_config['stage2']['close_pct'],
            stop_loss_action="move_to_breakeven_plus"
        )
        stage_exits.append(stage_exit_2)

        stage_exit_3 = StageExitLevel(
            stage=3,
            trigger_profit_atr_multiplier=tp_config['stage3']['trigger'],
            close_percentage=0.0,  # Stage3不创建部分平仓记录,只启用追踪止损
            stop_loss_action="trailing_stop"
        )
        stage_exits.append(stage_exit_3)

        return RiskParameters(
            position_size_usdt=position_size_usdt,
            initial_stop_loss_price=initial_stop_loss,
            trailing_stop_enabled=tp_config['stage3']['trailing_stop'],
            trailing_stop_distance_atr=tp_config['stage3']['trailing_atr_multiplier'],
            stage_exits=stage_exits
        )

    # ==================== 持仓监控 ====================
    def add_position(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        quantity: float,
        risk_params: RiskParameters
    ) -> ActivePosition:
        """
        添加活跃持仓

        Args:
            symbol: 币种
            side: 方向(BUY/SELL)
            entry_price: 入场价格
            quantity: 数量
            risk_params: 风险参数

        Returns:
            活跃持仓对象
        """
        position = ActivePosition(
            symbol=symbol,
            side=side,
            entry_time=datetime.now(),
            entry_price=entry_price,
            quantity=quantity,
            entry_amount_usdt=entry_price * quantity,
            risk_params=risk_params,
            current_stop_loss_price=risk_params.initial_stop_loss_price
        )

        self.active_positions[symbol] = position
        logger.info(f"添加持仓: {symbol} {side} @ {entry_price:.4f} x {quantity:.6f}")
        return position

    def update_position(
        self,
        symbol: str,
        current_price: float,
        atr: float
    ) -> Tuple[bool, List[str]]:
        """
        更新持仓信息并检查止损/止盈

        Args:
            symbol: 币种
            current_price: 当前价格
            atr: ATR值

        Returns:
            (是否需要平仓, 事件列表)
        """
        if symbol not in self.active_positions:
            return False, []

        position = self.active_positions[symbol]
        events = []

        # 更新当前价格
        position.current_price = current_price

        # 更新高低价
        if position.side == 'BUY':
            position.highest_price_since_entry = max(position.highest_price_since_entry, current_price)
            position.lowest_price_since_entry = min(position.lowest_price_since_entry, current_price)
        else:
            position.highest_price_since_entry = max(position.highest_price_since_entry, current_price)
            position.lowest_price_since_entry = min(position.lowest_price_since_entry, current_price)

        # 计算浮动P&L
        if position.side == 'BUY':
            position.floating_pnl_usdt = (current_price - position.entry_price) * position.remaining_quantity
            position.floating_pnl_pct = (current_price - position.entry_price) / position.entry_price
        else:
            position.floating_pnl_usdt = (position.entry_price - current_price) * position.remaining_quantity
            position.floating_pnl_pct = (position.entry_price - current_price) / position.entry_price

        # 检查保本触发 (0.5×ATR，优先级高于stage止盈)
        breakeven_trigger_atr = self.config['stop_loss'].get('breakeven_trigger', 0.5)
        profit_atr_distance = abs(current_price - position.entry_price)
        if profit_atr_distance >= breakeven_trigger_atr * atr:
            # 触发保本机制：抬升止损到入场价(保本)
            if position.side == 'BUY':
                new_breakeven_stop = position.entry_price  # 改为入场价保本
                if new_breakeven_stop > position.current_stop_loss_price:
                    position.current_stop_loss_price = new_breakeven_stop
                    events.append(f"触发保本机制(0.5×ATR): 止损抬升至入场价 {new_breakeven_stop:.4f}(保本)")
            else:  # SELL
                new_breakeven_stop = position.entry_price  # 改为入场价保本
                if new_breakeven_stop < position.current_stop_loss_price:
                    position.current_stop_loss_price = new_breakeven_stop
                    events.append(f"触发保本机制(0.5×ATR): 止损抬升至入场价 {new_breakeven_stop:.4f}(保本)")

        # 检查止损
        should_stop_loss = False
        if position.side == 'BUY':
            if current_price <= position.current_stop_loss_price:
                should_stop_loss = True
                events.append(f"触发止损: {current_price:.4f} <= {position.current_stop_loss_price:.4f}")
        else:
            if current_price >= position.current_stop_loss_price:
                should_stop_loss = True
                events.append(f"触发止损: {current_price:.4f} >= {position.current_stop_loss_price:.4f}")

        if should_stop_loss:
            return True, events

        # 检查分阶段止盈
        for stage_exit in position.risk_params.stage_exits:
            profit_atr = atr * stage_exit.trigger_profit_atr_multiplier

            if position.side == 'BUY':
                tp_price = position.entry_price + profit_atr
                if current_price >= tp_price and stage_exit.stage not in [e['stage'] for e in position.partial_exits]:
                    # Stage3 特殊处理: 只启用追踪止损, 不创建部分平仓
                    if stage_exit.stage == 3:
                        # 标记 Stage3 已触发 (用于追踪止损检查)
                        position.partial_exits.append({
                            'stage': 3,
                            'time': datetime.now(),
                            'quantity': 0.0,  # 不平仓
                            'price': current_price,
                            'profit_pct': (current_price - position.entry_price) / position.entry_price,
                            'executed': True  # 立即标记为已执行(因为不需要下单)
                        })
                        events.append(f"Stage 3 触发: 启用追踪止损 (距离1.0×ATR)")
                    else:
                        # Stage 1/2: 计算需要平仓的数量
                        close_qty = position.remaining_quantity * stage_exit.close_percentage

                        # 记录待执行的部分平仓
                        position.partial_exits.append({
                            'stage': stage_exit.stage,
                            'time': datetime.now(),
                            'quantity': close_qty,
                            'price': current_price,
                            'profit_pct': (current_price - position.entry_price) / position.entry_price,
                            'executed': False  # 标记为未执行，等待实际下单
                        })

                        events.append(f"Stage {stage_exit.stage} 止盈触发: 需要平仓 {stage_exit.close_percentage*100:.0f}% (数量: {close_qty:.6f})")

                    # 更新止损（立即生效）
                    if stage_exit.stop_loss_action == "move_to_breakeven":
                        position.current_stop_loss_price = position.entry_price
                        events.append(f"抬升止损到开仓价: {position.entry_price:.4f}")
                    elif stage_exit.stop_loss_action == "move_to_breakeven_plus":
                        # 保本+ : 入场价 + 0.1×ATR
                        breakeven_plus = position.entry_price + 0.1 * atr
                        position.current_stop_loss_price = breakeven_plus
                        events.append(f"抬升止损到保本+(入场+0.1×ATR): {breakeven_plus:.4f}")

                    # 注意：不在这里减少remaining_quantity
                    # 等待实际订单执行成功后再减少

            else:  # SELL
                tp_price = position.entry_price - profit_atr
                if current_price <= tp_price and stage_exit.stage not in [e['stage'] for e in position.partial_exits]:
                    # Stage3 特殊处理: 只启用追踪止损, 不创建部分平仓
                    if stage_exit.stage == 3:
                        # 标记 Stage3 已触发 (用于追踪止损检查)
                        position.partial_exits.append({
                            'stage': 3,
                            'time': datetime.now(),
                            'quantity': 0.0,  # 不平仓
                            'price': current_price,
                            'profit_pct': (position.entry_price - current_price) / position.entry_price,
                            'executed': True  # 立即标记为已执行(因为不需要下单)
                        })
                        events.append(f"Stage 3 触发: 启用追踪止损 (距离1.0×ATR)")
                    else:
                        # Stage 1/2: 计算需要平仓的数量
                        close_qty = position.remaining_quantity * stage_exit.close_percentage

                        # 记录待执行的部分平仓
                        position.partial_exits.append({
                            'stage': stage_exit.stage,
                            'time': datetime.now(),
                            'quantity': close_qty,
                            'price': current_price,
                            'profit_pct': (position.entry_price - current_price) / position.entry_price,
                            'executed': False  # 标记为未执行，等待实际下单
                        })

                        events.append(f"Stage {stage_exit.stage} 止盈触发: 需要平仓 {stage_exit.close_percentage*100:.0f}% (数量: {close_qty:.6f})")

                    # 更新止损（立即生效）
                    if stage_exit.stop_loss_action == "move_to_breakeven":
                        position.current_stop_loss_price = position.entry_price
                        events.append(f"抬升止损到开仓价: {position.entry_price:.4f}")
                    elif stage_exit.stop_loss_action == "move_to_breakeven_plus":
                        # 保本+ : 入场价 - 0.1×ATR
                        breakeven_plus = position.entry_price - 0.1 * atr
                        position.current_stop_loss_price = breakeven_plus
                        events.append(f"抬升止损到保本+(入场-0.1×ATR): {breakeven_plus:.4f}")

                    # 注意：不在这里减少remaining_quantity
                    # 等待实际订单执行成功后再减少

        # 检查是否全部平仓
        if position.remaining_quantity <= 0:
            position.status = PositionStatus.CLOSED
            return True, events

        return False, events

    # ==================== 冷却管理 ====================
    def add_to_cooldown(
        self,
        symbol: str,
        cooldown_minutes: int,
        reason: str
    ):
        """
        添加币种到冷却列表

        Args:
            symbol: 币种
            cooldown_minutes: 冷却时长(分钟)
            reason: 冷却原因
        """
        cooldown_until = datetime.now() + timedelta(minutes=cooldown_minutes)
        self.cooldown_symbols[symbol] = cooldown_until
        logger.info(f"{symbol} 已加入冷却列表({cooldown_minutes}分钟): {reason}")

    def add_loss_record(self, symbol: str):
        """
        记录亏损并检查是否需要触发连续亏损冷却

        Args:
            symbol: 币种

        Returns:
            是否触发了连续亏损冷却
        """
        now = datetime.now()

        # 初始化symbol的亏损记录
        if symbol not in self.recent_losses:
            self.recent_losses[symbol] = []

        # 添加本次亏损时间
        self.recent_losses[symbol].append(now)

        # 清理30天前的旧记录
        cutoff_time = now - timedelta(days=30)
        self.recent_losses[symbol] = [
            loss_time for loss_time in self.recent_losses[symbol]
            if loss_time > cutoff_time
        ]

        # 检查最近3次交易是否都是亏损
        recent_count = len(self.recent_losses[symbol])
        if recent_count >= self.consecutive_loss_threshold:
            # 检查最近3次是否在较短时间内（如24小时）
            recent_losses = sorted(self.recent_losses[symbol])[-self.consecutive_loss_threshold:]
            time_span = (recent_losses[-1] - recent_losses[0]).total_seconds() / 3600  # 小时

            if time_span <= 24:  # 24小时内连续3次亏损
                cooldown_minutes = self.rotation_config['cooldown_periods']['after_multiple_losses']
                self.add_to_cooldown(symbol, cooldown_minutes, f"连续{self.consecutive_loss_threshold}次亏损")
                logger.warning(f"{symbol}: 24小时内连续{self.consecutive_loss_threshold}次亏损，冷却{cooldown_minutes}分钟")
                return True

        return False

    def add_take_profit_cooldown(self, symbol: str):
        """
        止盈后添加冷却

        Args:
            symbol: 币种
        """
        cooldown_minutes = self.rotation_config['cooldown_periods']['after_take_profit']
        self.add_to_cooldown(symbol, cooldown_minutes, "止盈后冷却")

    def is_in_cooldown(self, symbol: str) -> bool:
        """检查币种是否在冷却中"""
        if symbol not in self.cooldown_symbols:
            return False

        if datetime.now() >= self.cooldown_symbols[symbol]:
            del self.cooldown_symbols[symbol]
            return False

        return True

    def get_cooldown_remaining(self, symbol: str) -> int:
        """获取剩余冷却时间(秒)"""
        if symbol not in self.cooldown_symbols:
            return 0

        remaining = self.cooldown_symbols[symbol] - datetime.now()
        return max(0, int(remaining.total_seconds()))

    # ==================== 持仓限制检查 ====================
    def can_open_new_position(self, symbol: str) -> bool:
        """
        检查是否可以开仓新头寸

        Returns:
            是否可以开仓
        """
        # 检查该币种是否已有活跃头寸
        if symbol in self.active_positions:
            position = self.active_positions[symbol]
            # 只有CLOSED状态的头寸才不阻止新开仓
            if position.status != PositionStatus.CLOSED:
                return False

        # 检查是否在冷却中
        if self.is_in_cooldown(symbol):
            return False

        # 检查并发头寸限制 - 改进: 只计算真正的活跃头寸
        open_positions = 0
        now = datetime.now()

        for p in self.active_positions.values():
            if p.status == PositionStatus.CLOSED:
                # 已平仓的头寸检查是否已经过了足够的时间
                # 如果平仓时间太近，不立即删除（保留用于数据追踪）
                continue
            if p.status in [PositionStatus.OPEN, PositionStatus.PARTIAL_CLOSE]:
                open_positions += 1

        if open_positions >= self.max_concurrent_positions:
            logger.debug(f"达到最大并发头寸限制({self.max_concurrent_positions}), 当前活跃头寸: {open_positions}")
            return False

        return True

    # ==================== 统计和报告 ====================
    def get_position_summary(self) -> Dict:
        """获取持仓摘要"""
        open_positions = [p for p in self.active_positions.values()
                         if p.status in [PositionStatus.OPEN, PositionStatus.PARTIAL_CLOSE]]

        total_floating_pnl = sum(p.floating_pnl_usdt for p in open_positions)
        total_entry_amount = sum(p.entry_amount_usdt for p in open_positions)

        return {
            'total_positions': len(self.active_positions),
            'open_positions': len(open_positions),
            'cooldown_symbols': len(self.cooldown_symbols),
            'total_floating_pnl_usdt': total_floating_pnl,
            'total_entry_amount_usdt': total_entry_amount,
            'total_floating_pnl_pct': total_floating_pnl / total_entry_amount if total_entry_amount > 0 else 0
        }


# ==================== 测试函数 ====================
if __name__ == "__main__":
    print("风险管理模块已创建")

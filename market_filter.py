"""
市场过滤模块 (market_filter.py)
用于检查BTC状态、市场健康度、时间过滤等市场级别的条件
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum
from indicators import IndicatorResult
from config_v2 import MARKET_FILTERS


class MarketHealth(Enum):
    """市场健康度"""
    EXCELLENT = "EXCELLENT"  # 非常好
    GOOD = "GOOD"             # 好
    MODERATE = "MODERATE"     # 中等
    POOR = "POOR"             # 差
    CRITICAL = "CRITICAL"     # 严重


@dataclass
class MarketFilterResult:
    """市场过滤结果"""
    can_trade: bool  # 是否可以交易
    health: MarketHealth  # 市场健康度
    btc_status: str  # BTC状态
    market_conditions: Dict[str, bool]  # 各项条件的满足情况
    warnings: List[str]  # 警告信息
    recommendations: List[str]  # 建议


class MarketFilter:
    """市场过滤器"""

    def __init__(self, config=MARKET_FILTERS):
        """初始化市场过滤器"""
        self.config = config

    # ==================== BTC状态检查 ====================
    def check_btc_condition(
        self,
        btc_indicators_1m: IndicatorResult,
        btc_indicators_15m: IndicatorResult,
        target_direction: str = "LONG",
        btc_1m_klines: List[Dict] = None
    ) -> Tuple[bool, str, List[str]]:
        """
        检查BTC市场状态

        Args:
            btc_indicators_1m: BTC 1分钟指标
            btc_indicators_15m: BTC 15分钟指标
            target_direction: 目标方向 ("LONG" 或 "SHORT")
            btc_1m_klines: BTC 1分钟K线数据（用于计算1m波动率）

        Returns:
            (是否满足条件, BTC状态描述, 原因列表)
        """
        reasons = []
        conditions_met = 0

        # 检查BTC 1分钟波动率≤2%
        if btc_1m_klines and len(btc_1m_klines) >= 2:
            # 计算最近1分钟的波动率（最高-最低）/开盘
            last_kline = btc_1m_klines[-1]
            volatility_1m = (last_kline['high'] - last_kline['low']) / last_kline['open']

            max_1m_volatility = self.config['btc_condition']['max_1m_volatility']
            if volatility_1m <= max_1m_volatility:
                conditions_met += 1
                reasons.append(f"✓ BTC 1m波动率({volatility_1m*100:.2f}%) <= {max_1m_volatility*100}%")
            else:
                reasons.append(f"✗ BTC 1m波动率({volatility_1m*100:.2f}%) > {max_1m_volatility*100}% (市场过于波动)")
        else:
            # 无1m K线数据，使用ATR近似
            if btc_indicators_1m and btc_indicators_1m.atr:
                atr_volatility = btc_indicators_1m.atr / ((btc_indicators_1m.ema_21 + btc_indicators_1m.ema_50) / 2)
                max_1m_volatility = self.config['btc_condition']['max_1m_volatility']
                if atr_volatility <= max_1m_volatility:
                    conditions_met += 1
                    reasons.append(f"✓ BTC 1m波动(ATR近似{atr_volatility*100:.2f}%) <= {max_1m_volatility*100}%")
                else:
                    reasons.append(f"✗ BTC 1m波动(ATR近似{atr_volatility*100:.2f}%) > {max_1m_volatility*100}%")
            else:
                reasons.append("○ BTC 1m波动率数据不可用，跳过检查")

        # 检查BTC 15分钟RSI范围
        rsi_min, rsi_max = self.config['btc_condition']['rsi_15m_range']
        if rsi_min <= btc_indicators_15m.rsi <= rsi_max:
            conditions_met += 1
            reasons.append(f"✓ BTC 15m RSI({btc_indicators_15m.rsi:.2f}) 在{rsi_min}-{rsi_max}范围内")
        else:
            reasons.append(f"✗ BTC 15m RSI({btc_indicators_15m.rsi:.2f}) 超出{rsi_min}-{rsi_max}范围")

        # 根据趋势一致性模式检查
        trend_alignment_mode = self.config['btc_condition']['trend_alignment']

        # 确定BTC的趋势
        btc_trend = "BULLISH" if btc_indicators_15m.ema_21 > btc_indicators_15m.ema_50 else "BEARISH"

        # 🔧 如果目标方向是 BOTH（双向交易），直接视为参考模式
        if target_direction == "BOTH":
            reasons.append(f"○ BTC趋势({btc_trend})作为参考，允许双向交易")
            conditions_met += 1

        elif trend_alignment_mode == "strict":
            # 严格模式：BTC必须与我们的方向一致
            if (target_direction == "LONG" and btc_trend == "BULLISH") or \
               (target_direction == "SHORT" and btc_trend == "BEARISH"):
                conditions_met += 1
                reasons.append(f"✓ BTC趋势({btc_trend})与目标方向({target_direction})一致")
            else:
                reasons.append(f"✗ BTC趋势({btc_trend})与目标方向({target_direction})不一致")

        elif trend_alignment_mode == "non_reverse":
            # 非反向模式：BTC不能与我们的方向相反
            if not ((target_direction == "LONG" and btc_trend == "BEARISH") or \
                    (target_direction == "SHORT" and btc_trend == "BULLISH")):
                conditions_met += 1
                reasons.append(f"✓ BTC趋势({btc_trend})不与目标方向({target_direction})相反")
            else:
                reasons.append(f"✗ BTC趋势({btc_trend})与目标方向({target_direction})相反")

        else:  # reference_only
            # 参考模式：只作为参考，不强制要求
            reasons.append(f"○ BTC趋势({btc_trend})作为参考，不强制要求")
            conditions_met += 1

        btc_status = f"BTC: {btc_trend} (RSI: {btc_indicators_15m.rsi:.2f})"

        return conditions_met >= 2, btc_status, reasons

    # ==================== 市场健康度检查 ====================
    def check_market_health(
        self,
        current_volume: float,
        avg_volume_24h: float,
        current_volatility: float,
        avg_volatility_24h: float,
        fear_greed_index: float = 50.0
    ) -> Tuple[MarketHealth, List[str]]:
        """
        检查市场整体健康度

        Args:
            current_volume: 当前成交量
            avg_volume_24h: 24小时平均成交量
            current_volatility: 当前波动率
            avg_volatility_24h: 24小时平均波动率
            fear_greed_index: 恐惧贪婪指数 (0-100)

        Returns:
            (市场健康度, 原因列表)
        """
        reasons = []
        health_score = 0

        # 检查恐惧贪婪指数
        fg_threshold = self.config['market_health']['fear_greed_threshold']
        if fear_greed_index > fg_threshold:
            health_score += 1
            reasons.append(f"✓ 恐惧贪婪指数({fear_greed_index:.1f}) > {fg_threshold}")
        else:
            reasons.append(f"✗ 恐惧贪婪指数({fear_greed_index:.1f}) <= {fg_threshold} (市场过度恐慌)")

        # 检查成交量下降
        volume_decline_threshold = self.config['market_health']['volume_decline_threshold']
        if avg_volume_24h > 0:
            volume_decline_ratio = current_volume / avg_volume_24h
            if volume_decline_ratio > volume_decline_threshold:
                health_score += 1
                reasons.append(f"✓ 当前成交量/平均成交量({volume_decline_ratio:.2f}) > {volume_decline_threshold}")
            else:
                reasons.append(f"✗ 成交量下降({volume_decline_ratio:.2f}) (可能流动性不足)")
        else:
            health_score += 1
            reasons.append("○ 无法获取成交量数据，跳过检查")

        # 检查波动率飙升
        volatility_spike_threshold = self.config['market_health']['volatility_spike_threshold']
        if avg_volatility_24h > 0:
            volatility_spike_ratio = current_volatility / avg_volatility_24h
            if volatility_spike_ratio < volatility_spike_threshold:
                health_score += 1
                reasons.append(f"✓ 波动率飙升({volatility_spike_ratio:.2f}x) < {volatility_spike_threshold}x")
            else:
                reasons.append(f"✗ 波动率飙升({volatility_spike_ratio:.2f}x) >= {volatility_spike_threshold}x (风险过高)")
        else:
            health_score += 1
            reasons.append("○ 无法获取波动率数据，跳过检查")

        # 根据得分判断健康度
        if health_score >= 3:
            health = MarketHealth.EXCELLENT
        elif health_score == 2:
            health = MarketHealth.GOOD
        elif health_score == 1:
            health = MarketHealth.MODERATE
        else:
            health = MarketHealth.POOR

        return health, reasons

    # ==================== 时间过滤 ====================
    def check_time_filters(
        self,
        current_time: Optional[datetime] = None,
        is_weekend: Optional[bool] = None
    ) -> Tuple[bool, List[str]]:
        """
        检查时间相关的过滤条件

        Args:
            current_time: 当前时间（默认为系统时间）
            is_weekend: 是否周末

        Returns:
            (是否符合条件, 原因列表)
        """
        if current_time is None:
            current_time = datetime.now()

        if is_weekend is None:
            is_weekend = current_time.weekday() >= 5  # 周五 >= 5，周六和周日为5和6

        reasons = []
        can_trade = True

        # 获取配置
        avoid_high_impact = self.config['time_filters']['avoid_high_impact_events']
        session_preference = self.config['time_filters']['session_preference']
        reduce_on_weekend = self.config['time_filters']['weekend_reduce_exposure']

        # 检查周末
        if is_weekend:
            if reduce_on_weekend:
                reasons.append("⚠ 周末时段，建议降低风险暴露")
                # 周末可以交易但风险更高，不影响can_trade，但在外部可以降低仓位
            else:
                reasons.append("○ 周末时段，正常交易")
        else:
            reasons.append("✓ 工作日时段")

        # 检查时段偏好（简化版）
        hour = current_time.hour
        if session_preference == "asian_european":
            # 亚洲(0-8) 和 欧洲(7-16) 时段较好
            if hour in range(0, 9) or hour in range(7, 17):
                reasons.append(f"✓ 当前时间({hour}:00)在亚欧活跃时段")
            else:
                reasons.append(f"⚠ 当前时间({hour}:00)不在亚欧活跃时段")

        # 避免高影响事件（这里只是模拟）
        if avoid_high_impact:
            # 实际应该从经济日历获取
            high_impact_hours = []  # 应该从配置或API获取
            if hour in high_impact_hours:
                reasons.append(f"✗ 当前时间({hour}:00)可能有重大经济事件")
                can_trade = False
            else:
                reasons.append("✓ 当前时间没有已知的高影响事件")

        return can_trade, reasons

    # ==================== 综合市场过滤 ====================
    def apply_market_filters(
        self,
        btc_indicators_1m: Optional[IndicatorResult] = None,
        btc_indicators_15m: Optional[IndicatorResult] = None,
        btc_1m_klines: List[Dict] = None,
        target_direction: str = "LONG",
        current_volume: float = 0.0,
        avg_volume_24h: float = 1.0,
        current_volatility: float = 0.0,
        avg_volatility_24h: float = 1.0,
        fear_greed_index: float = 50.0,
        current_time: Optional[datetime] = None,
        is_weekend: Optional[bool] = None
    ) -> MarketFilterResult:
        """
        应用所有市场过滤条件

        Args:
            btc_indicators_1m: BTC 1分钟指标
            btc_indicators_15m: BTC 15分钟指标
            btc_1m_klines: BTC 1分钟K线数据(用于计算1m波动率)
            target_direction: 目标交易方向
            current_volume: 当前成交量
            avg_volume_24h: 24小时平均成交量
            current_volatility: 当前波动率
            avg_volatility_24h: 24小时平均波动率
            fear_greed_index: 恐惧贪婪指数
            current_time: 当前时间
            is_weekend: 是否周末

        Returns:
            市场过滤结果
        """
        warnings = []
        recommendations = []
        market_conditions = {}

        # 1. 检查BTC条件(传入1m klines)
        btc_ok = True
        btc_status = "Unknown"
        btc_reasons = []

        if btc_indicators_1m and btc_indicators_15m:
            btc_ok, btc_status, btc_reasons = self.check_btc_condition(
                btc_indicators_1m,
                btc_indicators_15m,
                target_direction,
                btc_1m_klines  # 传入1m K线数据
            )
            warnings.extend([r for r in btc_reasons if "✗" in r])
        else:
            warnings.append("⚠ 无法获取BTC数据")
            btc_status = "Data Unavailable"

        market_conditions['btc_aligned'] = btc_ok

        # 2. 检查市场健康度
        market_health, health_reasons = self.check_market_health(
            current_volume,
            avg_volume_24h,
            current_volatility,
            avg_volatility_24h,
            fear_greed_index
        )

        market_health_ok = market_health in [MarketHealth.EXCELLENT, MarketHealth.GOOD]
        market_conditions['market_health_ok'] = market_health_ok

        if not market_health_ok:
            warnings.extend([r for r in health_reasons if "✗" in r])

        if market_health == MarketHealth.CRITICAL:
            warnings.append("🚨 市场处于严重不健康状态，建议停止交易")
        elif market_health == MarketHealth.POOR:
            recommendations.append("建议降低交易频率和仓位")

        # 3. 检查时间过滤
        time_ok, time_reasons = self.check_time_filters(current_time, is_weekend)
        market_conditions['time_filters_ok'] = time_ok

        if not time_ok:
            warnings.extend([r for r in time_reasons if "✗" in r])

        if any("⚠" in r for r in time_reasons):
            recommendations.extend([r for r in time_reasons if "⚠" in r])

        # 综合判断是否可以交易
        can_trade = btc_ok and market_health_ok and time_ok

        return MarketFilterResult(
            can_trade=can_trade,
            health=market_health,
            btc_status=btc_status,
            market_conditions=market_conditions,
            warnings=warnings,
            recommendations=recommendations
        )

    # ==================== 风险调整建议 ====================
    def get_risk_adjustment(
        self,
        market_health: MarketHealth,
        is_weekend: bool
    ) -> Dict[str, float]:
        """
        根据市场条件获取风险调整系数

        Args:
            market_health: 市场健康度
            is_weekend: 是否周末

        Returns:
            调整系数字典
        """
        # 基础系数
        position_size_multiplier = 1.0
        leverage_multiplier = 1.0
        check_interval_multiplier = 1.0

        # 根据市场健康度调整
        if market_health == MarketHealth.EXCELLENT:
            position_size_multiplier = 1.2
            leverage_multiplier = 1.0
        elif market_health == MarketHealth.GOOD:
            position_size_multiplier = 1.0
            leverage_multiplier = 1.0
        elif market_health == MarketHealth.MODERATE:
            position_size_multiplier = 0.8
            leverage_multiplier = 0.8
            check_interval_multiplier = 0.8  # 更频繁的检查
        elif market_health == MarketHealth.POOR:
            position_size_multiplier = 0.5
            leverage_multiplier = 0.5
            check_interval_multiplier = 0.5
        else:  # CRITICAL
            position_size_multiplier = 0.1
            leverage_multiplier = 0.1
            check_interval_multiplier = 0.3

        # 周末风险调整
        if self.config['time_filters']['weekend_reduce_exposure']:
            if is_weekend:
                position_size_multiplier *= 0.7
                leverage_multiplier *= 0.7

        return {
            'position_size': position_size_multiplier,
            'leverage': leverage_multiplier,
            'check_interval': check_interval_multiplier
        }


# ==================== 测试函数 ====================
if __name__ == "__main__":
    from datetime import datetime, timedelta

    print("=" * 80)
    print("市场过滤模块测试")
    print("=" * 80)

    filter = MarketFilter()

    # 生成测试指标
    btc_ind_1m = IndicatorResult(
        ema_21=45000, ema_50=44000, macd=100, macd_signal=80, macd_histogram=20,
        rsi=55, atr=200, bb_upper=45500, bb_middle=45000, bb_lower=44500,
        ema_slope=50, price_to_ema=1.005, rsi_strength="NEUTRAL"
    )

    btc_ind_15m = IndicatorResult(
        ema_21=45050, ema_50=44900, macd=150, macd_signal=100, macd_histogram=50,
        rsi=60, atr=300, bb_upper=45600, bb_middle=45000, bb_lower=44400,
        ema_slope=100, price_to_ema=1.008, rsi_strength="NEUTRAL"
    )

    # 测试1: BTC状态检查
    print("\n[测试1] BTC状态检查")
    print("-" * 80)
    btc_ok, btc_status, reasons = filter.check_btc_condition(
        btc_ind_1m, btc_ind_15m, "LONG"
    )
    print(f"BTC符合条件: {btc_ok}")
    print(f"BTC状态: {btc_status}")
    for reason in reasons:
        print(f"  {reason}")

    # 测试2: 市场健康度
    print("\n[测试2] 市场健康度检查")
    print("-" * 80)
    health, health_reasons = filter.check_market_health(
        current_volume=1000000,
        avg_volume_24h=900000,
        current_volatility=0.015,
        avg_volatility_24h=0.01,
        fear_greed_index=60
    )
    print(f"市场健康度: {health.value}")
    for reason in health_reasons:
        print(f"  {reason}")

    # 测试3: 时间过滤
    print("\n[测试3] 时间过滤检查")
    print("-" * 80)
    current_time = datetime.now()
    time_ok, time_reasons = filter.check_time_filters(current_time)
    print(f"时间符合条件: {time_ok}")
    for reason in time_reasons:
        print(f"  {reason}")

    # 测试4: 综合过滤
    print("\n[测试4] 综合市场过滤")
    print("-" * 80)
    result = filter.apply_market_filters(
        btc_indicators_1m=btc_ind_1m,
        btc_indicators_15m=btc_ind_15m,
        target_direction="LONG",
        current_volume=1000000,
        avg_volume_24h=900000,
        current_volatility=0.015,
        avg_volatility_24h=0.01,
        fear_greed_index=60,
        current_time=current_time
    )
    print(f"可以交易: {result.can_trade}")
    print(f"市场健康度: {result.health.value}")
    print(f"警告: {len(result.warnings)}")
    for warning in result.warnings:
        print(f"  {warning}")
    print(f"建议: {len(result.recommendations)}")
    for rec in result.recommendations:
        print(f"  {rec}")

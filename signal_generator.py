"""
信号生成和评分系统 (signal_generator.py)
根据趋势、动量、风险回报等多个维度生成交易信号并评分
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import logging
from datetime import datetime

from indicators import IndicatorCalculator, IndicatorResult
from trend_analyzer import TrendAnalyzer, TrendAnalysis, TrendDirection
from config_v2 import SCORING_SYSTEM, ENTRY_RULES, RISK_MANAGEMENT, INDICATOR_CONFIG


logger = logging.getLogger(__name__)


class SignalType(Enum):
    """信号类型"""
    BREAKOUT = "BREAKOUT"      # 突破入场
    PULLBACK = "PULLBACK"      # 回调入场
    MOMENTUM = "MOMENTUM"      # 动量入场
    NO_SIGNAL = "NO_SIGNAL"   # 无信号


class RiskLevel(Enum):
    """风险等级"""
    LOW = "LOW"               # 低风险
    MEDIUM = "MEDIUM"         # 中等风险
    HIGH = "HIGH"             # 高风险
    CRITICAL = "CRITICAL"     # 严重风险


@dataclass
class SignalScore:
    """信号评分"""
    # 趋势强度评分
    trend_score: int = 0
    # 动量评分
    momentum_score: int = 0
    # 风险回报评分
    risk_reward_score: int = 0
    # 总得分
    total_score: int = 0
    # 各个因素的详细评分
    detail_scores: Dict[str, int] = field(default_factory=dict)


@dataclass
class TradingSignal:
    """交易信号"""
    symbol: str
    timestamp: datetime
    signal_type: SignalType
    direction: TrendDirection  # LONG 或 SHORT
    entry_price: float

    # 评分相关
    score: SignalScore
    confidence: float  # 0-1，信心度
    risk_level: RiskLevel

    # 风险管理参数
    stop_loss_price: float
    take_profit_levels: List[float]  # 分阶段止盈价格
    position_size_usdt: float

    # 额外信息
    reasons: List[str] = field(default_factory=list)
    indicators_3m: Optional[IndicatorResult] = None
    indicators_5m: Optional[IndicatorResult] = None
    indicators_15m: Optional[IndicatorResult] = None


class SignalScorer:
    """信号评分器"""

    def __init__(self, config=SCORING_SYSTEM):
        """初始化评分器"""
        self.config = config
        self.trend_strength_weights = config['trend_strength']
        self.momentum_weights = config['momentum']
        self.risk_reward_weights = config['risk_reward']
        self.thresholds = config['thresholds']

    def calculate_trend_strength_score(
        self,
        trend_analysis: TrendAnalysis
    ) -> Tuple[int, List[str]]:
        """
        计算趋势强度得分

        Args:
            trend_analysis: 趋势分析结果

        Returns:
            (得分, 原因列表)
        """
        score = 0
        reasons = []

        # 多时间框架对齐（+2分）
        total_conditions = (trend_analysis.primary_tf_score +
                          trend_analysis.confirmation_tf_score +
                          trend_analysis.trend_tf_score)

        if total_conditions >= 6:
            score += self.trend_strength_weights['multi_tf_alignment']
            reasons.append(f"✓ 多时间框架对齐 ({total_conditions}/7条件满足) +{self.trend_strength_weights['multi_tf_alignment']}分")
        else:
            reasons.append(f"✗ 多时间框架对齐 ({total_conditions}/7条件满足) +0分")

        # EMA斜率陡峭（+1分）
        # 这需要传入EMA斜率数据
        # 简化版本：根据主时间框架得分判断
        if trend_analysis.primary_tf_score >= 2:
            score += self.trend_strength_weights['ema_slope_steep']
            reasons.append(f"✓ EMA趋势明确 +{self.trend_strength_weights['ema_slope_steep']}分")

        # 价格突破关键位（+1分）
        if trend_analysis.confidence >= 0.7:
            score += self.trend_strength_weights['price_above_key_levels']
            reasons.append(f"✓ 价格突破关键位 (信心度{trend_analysis.confidence:.0%}) +{self.trend_strength_weights['price_above_key_levels']}分")

        return score, reasons

    def calculate_momentum_score(
        self,
        indicators_3m: IndicatorResult,
        indicators_5m: IndicatorResult,
        direction: TrendDirection,
        volume_ratio_3m: float = None
    ) -> Tuple[int, List[str]]:
        """
        计算动量得分

        Args:
            indicators_3m: 3分钟指标
            indicators_5m: 5分钟指标
            direction: 趋势方向
            volume_ratio_3m: 3m真实volume ratio（当前/近20根均量）

        Returns:
            (得分, 原因列表)
        """
        score = 0
        reasons = []

        # RSI与趋势一致（+1分）
        if direction == TrendDirection.BULLISH:
            if 40 <= indicators_3m.rsi <= 70:
                score += self.momentum_weights['rsi_trend_aligned']
                reasons.append(f"✓ RSI({indicators_3m.rsi:.1f})与多头趋势一致 +{self.momentum_weights['rsi_trend_aligned']}分")
            else:
                reasons.append(f"✗ RSI({indicators_3m.rsi:.1f})不在最优范围 +0分")
        else:  # BEARISH
            if 30 <= indicators_3m.rsi <= 60:
                score += self.momentum_weights['rsi_trend_aligned']
                reasons.append(f"✓ RSI({indicators_3m.rsi:.1f})与空头趋势一致 +{self.momentum_weights['rsi_trend_aligned']}分")
            else:
                reasons.append(f"✗ RSI({indicators_3m.rsi:.1f})不在最优范围 +0分")

        # MACD柱状图上升（+1分）
        if direction == TrendDirection.BULLISH:
            if indicators_5m.macd_histogram > 0:
                score += self.momentum_weights['macd_histogram_rising']
                reasons.append(f"✓ MACD柱状图({indicators_5m.macd_histogram:.6f})为正(上升) +{self.momentum_weights['macd_histogram_rising']}分")
            else:
                reasons.append(f"✗ MACD柱状图({indicators_5m.macd_histogram:.6f})为负 +0分")
        else:  # BEARISH
            if indicators_5m.macd_histogram < 0:
                score += self.momentum_weights['macd_histogram_rising']
                reasons.append(f"✓ MACD柱状图({indicators_5m.macd_histogram:.6f})为负(下降) +{self.momentum_weights['macd_histogram_rising']}分")
            else:
                reasons.append(f"✗ MACD柱状图({indicators_5m.macd_histogram:.6f})为正 +0分")

        # 成交量放大（+2分）- 使用真实volume ratio
        if volume_ratio_3m is not None:
            # 使用真实的3m volume ratio
            if volume_ratio_3m > 1.5:  # 优秀：>1.5倍
                score += self.momentum_weights['volume_increasing']
                reasons.append(f"✓ 成交量放大{volume_ratio_3m:.2f}倍(优秀) +{self.momentum_weights['volume_increasing']}分")
            elif volume_ratio_3m > 1.2:  # 合格：>1.2倍
                score += self.momentum_weights['volume_increasing']
                reasons.append(f"✓ 成交量放大{volume_ratio_3m:.2f}倍 +{self.momentum_weights['volume_increasing']}分")
            else:
                reasons.append(f"✗ 成交量放大不足({volume_ratio_3m:.2f}倍) +0分")
        else:
            # 降级：使用MACD柱体强度近似
            if abs(indicators_5m.macd_histogram) > 0.001:
                score += self.momentum_weights['volume_increasing']
                reasons.append(f"✓ 成交量放大信号(MACD近似) +{self.momentum_weights['volume_increasing']}分")
            else:
                reasons.append(f"✗ 成交量放大不足 +0分")

        return score, reasons

    def calculate_risk_reward_score(
        self,
        atr: float,
        current_price: float,
        entry_price: float,
        stop_loss_price: float,
        direction: TrendDirection
    ) -> Tuple[int, List[str]]:
        """
        计算风险回报得分

        Args:
            atr: 平均真实波幅
            current_price: 当前价格
            entry_price: 入场价格
            stop_loss_price: 止损价格
            direction: 方向

        Returns:
            (得分, 原因列表)
        """
        score = 0
        reasons = []

        # ATR在最优范围（+1分）
        atr_pct = (atr / entry_price) * 100
        if 0.4 <= atr_pct <= 3.0:
            score += self.risk_reward_weights['atr_optimal_range']
            reasons.append(f"✓ ATR{atr_pct:.2f}%在最优范围 +{self.risk_reward_weights['atr_optimal_range']}分")
        else:
            reasons.append(f"✗ ATR{atr_pct:.2f}%超出范围 +0分")

        # 明确支撑阻力（+1分）
        risk_distance = abs(entry_price - stop_loss_price)
        risk_pct = (risk_distance / entry_price) * 100

        if 0.4 <= risk_pct <= 3.0:
            score += self.risk_reward_weights['clear_support_resistance']
            reasons.append(f"✓ 明确支撑阻力(风险{risk_pct:.2f}%) +{self.risk_reward_weights['clear_support_resistance']}分")
        else:
            reasons.append(f"✗ 支撑阻力不清晰(风险{risk_pct:.2f}%) +0分")

        # 市场结构突破（+2分）
        # 简化版本：如果入场价格超出ATR范围，认为是结构突破
        if abs(current_price - entry_price) / current_price > 0.001:
            score += self.risk_reward_weights['market_structure_break']
            reasons.append(f"✓ 市场结构突破 +{self.risk_reward_weights['market_structure_break']}分")
        else:
            reasons.append(f"✗ 市场结构突破不明显 +0分")

        return score, reasons

    def generate_score(
        self,
        trend_analysis: TrendAnalysis,
        indicators_3m: IndicatorResult,
        indicators_5m: IndicatorResult,
        atr: float,
        current_price: float,
        entry_price: float,
        stop_loss_price: float,
        volume_ratio_3m: float = None
    ) -> SignalScore:
        """
        生成综合评分

        Args:
            trend_analysis: 趋势分析结果
            indicators_3m: 3分钟指标
            indicators_5m: 5分钟指标
            atr: 平均真实波幅
            current_price: 当前价格
            entry_price: 入场价格
            stop_loss_price: 止损价格
            volume_ratio_3m: 3m真实volume ratio

        Returns:
            信号评分对象
        """
        # 计算各维度得分
        trend_score, trend_reasons = self.calculate_trend_strength_score(trend_analysis)
        momentum_score, momentum_reasons = self.calculate_momentum_score(
            indicators_3m, indicators_5m, trend_analysis.direction, volume_ratio_3m
        )
        risk_reward_score, risk_reward_reasons = self.calculate_risk_reward_score(
            atr, current_price, entry_price, stop_loss_price, trend_analysis.direction
        )

        # 总得分
        total_score = trend_score + momentum_score + risk_reward_score

        # 保存详细评分
        detail_scores = {
            'trend_strength': trend_score,
            'momentum': momentum_score,
            'risk_reward': risk_reward_score
        }

        return SignalScore(
            trend_score=trend_score,
            momentum_score=momentum_score,
            risk_reward_score=risk_reward_score,
            total_score=total_score,
            detail_scores=detail_scores
        )


class SignalGenerator:
    """信号生成器"""

    def __init__(self, scorer=None):
        """初始化信号生成器"""
        self.scorer = scorer or SignalScorer()
        self.trend_analyzer = TrendAnalyzer()
        self.indicator_calc = IndicatorCalculator()

    def generate_signal(
        self,
        symbol: str,
        klines_3m: List[Dict],
        klines_5m: List[Dict],
        klines_15m: List[Dict],
        current_price: float,
        position_size_usdt: float,
        volume_ratio_3m: float = None,
        min_score_override: int = None
    ) -> Optional[TradingSignal]:
        """
        生成交易信号

        Args:
            symbol: 币种符号
            klines_3m: 3分钟K线数据
            klines_5m: 5分钟K线数据
            klines_15m: 15分钟K线数据
            current_price: 当前价格
            position_size_usdt: 仓位大小(USDT)
            volume_ratio_3m: 3m真实volume ratio（可选）
            min_score_override: 动态评分门槛（可选，用于市场状态调整）

        Returns:
            交易信号对象，如果信号不满足条件则返回None
        """
        try:
            # 1. 验证K线数据充足
            if not self._validate_klines(klines_3m, klines_5m, klines_15m):
                logger.debug(f"{symbol}: K线数据不足")
                return None

            # 2. 计算指标
            indicators_3m = self._calculate_indicators_from_klines(klines_3m)
            indicators_5m = self._calculate_indicators_from_klines(klines_5m)
            indicators_15m = self._calculate_indicators_from_klines(klines_15m)

            if not all([indicators_3m, indicators_5m, indicators_15m]):
                logger.debug(f"{symbol}: 无法计算指标")
                return None

            # 3. 趋势分析
            trend_analysis = self.trend_analyzer.analyze_trend(
                indicators_3m, indicators_5m, indicators_15m, current_price
            )

            # 4. 检查最低信心度 - 提高到60%
            if trend_analysis.confidence < 0.6:
                logger.debug(f"{symbol}: 趋势信心度不足({trend_analysis.confidence:.0%} < 60%)")
                return None

            # 5. 计算风险管理参数
            atr = indicators_3m.atr
            stop_loss_price, take_profit_levels = self._calculate_risk_params(
                current_price, atr, trend_analysis.direction
            )

            # 5.5. 检查入场规则（突破/回调）
            signal_type, entry_reasons = self.check_entry_rules(
                klines_3m, indicators_3m, indicators_5m,
                current_price, trend_analysis.direction, volume_ratio_3m
            )

            # 6. 评分（传递volume_ratio）
            signal_score = self.scorer.generate_score(
                trend_analysis, indicators_3m, indicators_5m,
                atr, current_price, current_price, stop_loss_price,
                volume_ratio_3m
            )

            # 7. 检查最低评分（支持动态门槛）
            min_score = min_score_override if min_score_override is not None else self.scorer.thresholds['minimum_score']
            if signal_score.total_score < min_score:
                logger.debug(f"{symbol}: 评分不足({signal_score.total_score}/{min_score})")
                return None

            # 8. 确定风险等级
            risk_level = self._determine_risk_level(atr, current_price)

            # 9. 计算信心度
            confidence = min(signal_score.total_score / self.scorer.thresholds['maximum_position_size'], 1.0)

            # 10. 生成信号
            signal = TradingSignal(
                symbol=symbol,
                timestamp=datetime.now(),
                signal_type=signal_type,  # 使用检查后的入场类型
                direction=trend_analysis.direction,
                entry_price=current_price,
                score=signal_score,
                confidence=confidence,
                risk_level=risk_level,
                stop_loss_price=stop_loss_price,
                take_profit_levels=take_profit_levels,
                position_size_usdt=position_size_usdt,
                indicators_3m=indicators_3m,
                indicators_5m=indicators_5m,
                indicators_15m=indicators_15m
            )

            # 添加原因
            signal.reasons = trend_analysis.reasons.copy()
            signal.reasons.extend(entry_reasons)  # 添加入场规则原因
            signal.reasons.extend([
                f"评分: {signal_score.total_score}分 (趋势{signal_score.trend_score}+动量{signal_score.momentum_score}+风险回报{signal_score.risk_reward_score})",
                f"信心度: {confidence:.0%}",
                f"止损: {stop_loss_price:.4f}, TP: {take_profit_levels}"
            ])

            logger.info(f"{symbol}: 生成信号 {signal.direction.value} [{signal_type.value}] (评分: {signal_score.total_score})")
            return signal

        except Exception as e:
            logger.error(f"{symbol}: 信号生成失败 - {e}")
            return None

    def check_entry_rules(
        self,
        klines_3m: List[Dict],
        indicators_3m: IndicatorResult,
        indicators_5m: IndicatorResult,
        current_price: float,
        direction: TrendDirection,
        volume_ratio_3m: float = None
    ) -> Tuple[SignalType, List[str]]:
        """
        检查入场规则

        Args:
            klines_3m: 3分钟K线数据
            indicators_3m: 3分钟指标
            indicators_5m: 5分钟指标
            current_price: 当前价格
            direction: 趋势方向
            volume_ratio_3m: 3m成交量比率

        Returns:
            (入场类型, 原因列表)
        """
        from config_v2 import ENTRY_RULES

        reasons = []
        signal_type = SignalType.NO_SIGNAL

        # 检查突破入场
        breakout_triggered, breakout_reasons = self._check_breakout_entry(
            klines_3m, current_price, direction, volume_ratio_3m
        )
        reasons.extend(breakout_reasons)

        # 检查回调入场
        pullback_triggered, pullback_reasons = self._check_pullback_entry(
            indicators_3m, indicators_5m, current_price, direction
        )
        reasons.extend(pullback_reasons)

        # 优先级：突破 > 回调
        if breakout_triggered:
            signal_type = SignalType.BREAKOUT
            reasons.append("✓ 突破入场条件满足")
        elif pullback_triggered:
            signal_type = SignalType.PULLBACK
            reasons.append("✓ 回调入场条件满足")
        else:
            signal_type = SignalType.MOMENTUM  # 降级为动量入场
            reasons.append("○ 使用动量入场（突破/回调条件未满足）")

        return signal_type, reasons

    def _check_breakout_entry(
        self,
        klines_3m: List[Dict],
        current_price: float,
        direction: TrendDirection,
        volume_ratio_3m: float = None
    ) -> Tuple[bool, List[str]]:
        """检查突破入场条件"""
        from config_v2 import ENTRY_RULES

        breakout_config = ENTRY_RULES['breakout']
        lookback = breakout_config['lookback_period']  # 10周期
        volume_boost = breakout_config['volume_boost']  # 1.3倍

        reasons = []

        if len(klines_3m) < lookback + 2:
            reasons.append("✗ K线数据不足，无法检查突破")
            return False, reasons

        # 计算10周期高点/低点
        lookback_prices = [float(k['close']) for k in klines_3m[-(lookback+2):-2]]
        recent_high = max([float(k['high']) for k in klines_3m[-(lookback+2):-2]])
        recent_low = min([float(k['low']) for k in klines_3m[-(lookback+2):-2]])

        # 检查价格突破
        price_breakout = False
        if direction == TrendDirection.BULLISH:
            if current_price > recent_high:
                price_breakout = True
                reasons.append(f"✓ 价格({current_price:.4f}) > 10周期高点({recent_high:.4f})")
            else:
                reasons.append(f"✗ 价格未突破10周期高点")
        else:  # BEARISH
            if current_price < recent_low:
                price_breakout = True
                reasons.append(f"✓ 价格({current_price:.4f}) < 10周期低点({recent_low:.4f})")
            else:
                reasons.append(f"✗ 价格未突破10周期低点")

        # 检查成交量放大
        volume_confirmed = False
        if volume_ratio_3m is not None:
            if volume_ratio_3m >= volume_boost:
                volume_confirmed = True
                reasons.append(f"✓ 成交量放大({volume_ratio_3m:.2f}) >= {volume_boost}倍")
            else:
                reasons.append(f"✗ 成交量放大不足({volume_ratio_3m:.2f}) < {volume_boost}倍")
        else:
            # 无真实成交量数据，降低要求
            volume_confirmed = True
            reasons.append("○ 无成交量数据，跳过成交量检查")

        return price_breakout and volume_confirmed, reasons

    def _check_pullback_entry(
        self,
        indicators_3m: IndicatorResult,
        indicators_5m: IndicatorResult,
        current_price: float,
        direction: TrendDirection
    ) -> Tuple[bool, List[str]]:
        """检查回调入场条件"""
        from config_v2 import ENTRY_RULES

        pullback_config = ENTRY_RULES['pullback']
        rsi_range = pullback_config['rsi_range']  # [35, 65]
        price_to_ema_range = [0.995, 1.005]  # V2.0需求：±0.5%区间

        reasons = []
        conditions_met = 0

        # 检查RSI范围
        if rsi_range[0] <= indicators_3m.rsi <= rsi_range[1]:
            conditions_met += 1
            reasons.append(f"✓ RSI({indicators_3m.rsi:.1f}) 在{rsi_range}范围内")
        else:
            reasons.append(f"✗ RSI({indicators_3m.rsi:.1f}) 超出{rsi_range}范围")

        # 检查价格回调到EMA区间
        price_to_ema = current_price / indicators_3m.ema_21
        if price_to_ema_range[0] <= price_to_ema <= price_to_ema_range[1]:
            conditions_met += 1
            reasons.append(f"✓ 价格/EMA21({price_to_ema:.4f}) 在[{price_to_ema_range[0]},{price_to_ema_range[1]}]区间")
        else:
            reasons.append(f"✗ 价格/EMA21({price_to_ema:.4f}) 超出区间")

        # 检查MACD histogram改善
        if direction == TrendDirection.BULLISH:
            if indicators_5m.macd_histogram > 0:
                conditions_met += 1
                reasons.append(f"✓ MACD柱状图({indicators_5m.macd_histogram:.6f}) > 0 (改善)")
            else:
                reasons.append(f"✗ MACD柱状图未改善")
        else:  # BEARISH
            if indicators_5m.macd_histogram < 0:
                conditions_met += 1
                reasons.append(f"✓ MACD柱状图({indicators_5m.macd_histogram:.6f}) < 0 (改善)")
            else:
                reasons.append(f"✗ MACD柱状图未改善")

        # 需要至少2个条件满足
        return conditions_met >= 2, reasons

    # ==================== 辅助方法 ====================
    @staticmethod
    def _validate_klines(klines_3m, klines_5m, klines_15m) -> bool:
        """
        验证K线数据充足 - 按TIMEFRAME_CONFIG要求校验

        3m需要50根（2.5小时）
        5m需要20根（1.6小时）
        15m需要10根（2.5小时）
        """
        from config_v2 import TIMEFRAME_CONFIG

        data_reqs = TIMEFRAME_CONFIG['data_requirements']

        return (len(klines_3m) >= data_reqs['3m'] and
                len(klines_5m) >= data_reqs['5m'] and
                len(klines_15m) >= data_reqs['15m'])

    def _calculate_indicators_from_klines(self, klines: List[Dict]) -> Optional[IndicatorResult]:
        """从K线数据计算指标"""
        if not klines:
            return None

        closes = [float(k['close']) for k in klines]
        highs = [float(k['high']) for k in klines]
        lows = [float(k['low']) for k in klines]
        volumes = [float(k['volume']) for k in klines]

        return self.indicator_calc.calculate_all_indicators(closes, highs, lows, volumes)

    @staticmethod
    def _calculate_risk_params(
        entry_price: float,
        atr: float,
        direction: TrendDirection
    ) -> Tuple[float, List[float]]:
        """
        计算风险管理参数

        Returns:
            (止损价格, 分阶段止盈价格列表)
        """
        # 初始止损基于ATR
        initial_stop_multiplier = RISK_MANAGEMENT['stop_loss']['initial_atr_multiplier']
        atr_stop_distance = atr * initial_stop_multiplier

        # 计算百分比止损距离
        min_stop_pct = RISK_MANAGEMENT['stop_loss']['min_stop_pct'] / 100.0  # 0.4% -> 0.004
        max_stop_pct = RISK_MANAGEMENT['stop_loss']['max_stop_pct'] / 100.0  # 3.0% -> 0.03

        min_stop_distance = entry_price * min_stop_pct
        max_stop_distance = entry_price * max_stop_pct

        # 取ATR和最小止损的较大值，但不超过最大止损
        stop_distance = max(atr_stop_distance, min_stop_distance)
        stop_distance = min(stop_distance, max_stop_distance)

        # 计算实际止损价
        stop_loss_price = entry_price - stop_distance if direction == TrendDirection.BULLISH \
                         else entry_price + stop_distance

        # 分阶段止盈
        tp_config = RISK_MANAGEMENT['take_profit']
        tp_levels = []

        for stage_key in ['stage1', 'stage2', 'stage3']:
            stage = tp_config[stage_key]
            trigger = stage['trigger']
            tp_price = entry_price + (atr * trigger) if direction == TrendDirection.BULLISH \
                      else entry_price - (atr * trigger)
            tp_levels.append(tp_price)

        return stop_loss_price, tp_levels

    @staticmethod
    def _determine_risk_level(atr: float, price: float) -> RiskLevel:
        """确定风险等级"""
        atr_pct = (atr / price) * 100

        if atr_pct < 0.4:
            return RiskLevel.LOW
        elif atr_pct < 1.0:
            return RiskLevel.MEDIUM
        elif atr_pct < 3.0:
            return RiskLevel.HIGH
        else:
            return RiskLevel.CRITICAL


# ==================== 测试函数 ====================
if __name__ == "__main__":
    print("信号生成模块已创建，可用于生成交易信号")

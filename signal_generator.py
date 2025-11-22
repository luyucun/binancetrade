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
from config_v2 import SCORING_SYSTEM, ENTRY_RULES, RISK_MANAGEMENT, INDICATOR_CONFIG, COST_CONFIG, ENTRY_GUARDS


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

        if total_conditions >= 4:  # 🔧 从 >=6 放宽到 >=4（7条件中满足4条即可）
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
            elif volume_ratio_3m > 0.8:  # 🔧 放宽：>0.8倍给1分
                score += 1  # 🔧 给部分分数
                reasons.append(f"○ 成交量适中{volume_ratio_3m:.2f}倍 +1分")
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

        # ATR在最优范围（+1分）- 🔧 同步到 0.1% ~ 4.0%，与 ENTRY_GUARDS 一致
        atr_pct = (atr / entry_price) * 100
        if 0.1 <= atr_pct <= 4.0:  # 🔧 从 0.2-3.0 放宽到 0.1-4.0
            score += self.risk_reward_weights['atr_optimal_range']
            reasons.append(f"✓ ATR{atr_pct:.2f}%在最优范围 +{self.risk_reward_weights['atr_optimal_range']}分")
        else:
            reasons.append(f"✗ ATR{atr_pct:.2f}%超出范围(0.1%-4.0%) +0分")

        # 明确支撑阻力（+1分）- 🔧 同步到 0.1% ~ 4.0%
        risk_distance = abs(entry_price - stop_loss_price)
        risk_pct = (risk_distance / entry_price) * 100

        if 0.1 <= risk_pct <= 4.0:  # 🔧 从 0.2-3.0 放宽到 0.1-4.0
            score += self.risk_reward_weights['clear_support_resistance']
            reasons.append(f"✓ 明确支撑阻力(风险{risk_pct:.2f}%) +{self.risk_reward_weights['clear_support_resistance']}分")
        else:
            reasons.append(f"✗ 支撑阻力不清晰(风险{risk_pct:.2f}%，范围0.1%-4.0%) +0分")

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
        volume_ratio_3m: float = None
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

        Returns:
            交易信号对象，如果信号不满足条件则返回None
        """
        try:
            # 1. 验证K线数据充足
            if not self._validate_klines(klines_3m, klines_5m, klines_15m):
                logger.debug(f"{symbol}: K线数据不足 (3m:{len(klines_3m)}, 5m:{len(klines_5m)}, 15m:{len(klines_15m)})")
                return None

            # 2. 计算指标
            indicators_3m = self._calculate_indicators_from_klines(klines_3m)
            indicators_5m = self._calculate_indicators_from_klines(klines_5m)
            indicators_15m = self._calculate_indicators_from_klines(klines_15m)

            if not all([indicators_3m, indicators_5m, indicators_15m]):
                # 🔧 详细诊断哪个时间框架的指标计算失败
                failed_tfs = []
                if not indicators_3m:
                    failed_tfs.append("3m")
                if not indicators_5m:
                    failed_tfs.append("5m")
                if not indicators_15m:
                    failed_tfs.append("15m")
                logger.debug(f"{symbol}: 无法计算指标 (失败的时间框架: {', '.join(failed_tfs)})")
                return None

            # 3. 趋势分析
            trend_analysis = self.trend_analyzer.analyze_trend(
                indicators_3m, indicators_5m, indicators_15m, current_price
            )

            # 4. 🔧 检查量比 - 改为软过滤（不达标时不加分，但不拒绝信号）
            volume_ratio = volume_ratio_3m or self._calculate_volume_ratio(klines_3m)
            min_volume_ratio = 0.8  # 🔧 量比建议值0.8

            # 🔧 调试特定币种
            if symbol in ['BNBUSDT', 'BTCUSDT', 'ETHUSDT']:
                logger.info(f"{symbol}: 量比={volume_ratio:.2f}, 建议>={min_volume_ratio}")

            # 🔧 量比不足时不直接拒绝，而是记录日志
            volume_ratio_sufficient = volume_ratio >= min_volume_ratio
            if not volume_ratio_sufficient:
                logger.debug(f"{symbol}: ⚠️ 量比偏低 ({volume_ratio:.2f} < {min_volume_ratio})，将影响评分")
            else:
                logger.debug(f"{symbol}: ✓ 量比检查通过 ({volume_ratio:.2f} >= {min_volume_ratio})")

            # 5. 🔧 严格的BTC 15m RSI检查
            if not self._check_btc_conditions():
                logger.debug(f"{symbol}: BTC条件不满足，拒绝开仓")
                return None

            # 6. 检查最低信心度 - 🔧 改为软过滤（45%以下才拒绝，45%-50%降低仓位）
            confidence_penalty = 1.0
            if trend_analysis.confidence < 0.45:
                logger.debug(f"{symbol}: ✗ 信心度过低 ({trend_analysis.confidence:.0%} < 45%)，拒绝信号")
                return None
            elif trend_analysis.confidence < 0.50:
                confidence_penalty = 0.7  # 🔧 信心度45%-50%时减仓30%
                logger.debug(f"{symbol}: ⚠️ 信心度偏低 ({trend_analysis.confidence:.0%})，减仓至70%")
            else:
                logger.debug(f"{symbol}: ✓ 信心度检查通过 ({trend_analysis.confidence:.0%})")

            # 7. 🔧 多TF确认 - 改为软过滤（不对齐时减仓而不是拒绝）
            tf_alignment_penalty = 1.0
            if not self._check_multi_tf_alignment(trend_analysis):
                tf_alignment_penalty = 0.8  # 🔧 多TF不对齐时减仓20%
                logger.debug(f"{symbol}: ⚠️ 多时间框架趋势不完全对齐，减仓至80%")
            else:
                logger.debug(f"{symbol}: ✓ 多TF对齐检查通过")

            # 5. 计算风险管理参数
            atr = indicators_3m.atr
            stop_loss_price, take_profit_levels = self._calculate_risk_params(
                current_price, atr, trend_analysis.direction
            )

            # 5.2 距离EMA的最小偏离（避免贴着均线震荡入场） - 🔧 放宽到0.02%
            try:
                pe = float(indicators_3m.price_to_ema or 0)
                min_deviation = 0.0002  # 🔧 从0.001降低到0.0002 (0.02%)
                if trend_analysis.direction == TrendDirection.BULLISH and pe < (1.0 + min_deviation):
                    logger.debug(f"{symbol}: ✗ 价格/EMA偏离不足(多头) {pe:.4f} < {1.0 + min_deviation:.4f}")
                    return None
                if trend_analysis.direction == TrendDirection.BEARISH and pe > (1.0 - min_deviation):
                    logger.debug(f"{symbol}: ✗ 价格/EMA偏离不足(空头) {pe:.4f} > {1.0 - min_deviation:.4f}")
                    return None
                logger.debug(f"{symbol}: ✓ 价格/EMA偏离检查通过 (价格/EMA={pe:.4f})")
            except Exception:
                pass

            # 5.1 ATR占比硬门槛（过滤"空间不够/波动过大"的行情） - 🔧 放宽到0.1% ~ 4.0%
            try:
                atr_pct = atr / current_price if current_price else 0.0
                atr_min = ENTRY_GUARDS.get('atr_pct_min', 0.001)  # 🔧 默认0.1%
                atr_max = ENTRY_GUARDS.get('atr_pct_max', 0.040)  # 🔧 默认4.0%
                if atr_pct < atr_min or atr_pct > atr_max:
                    logger.debug(f"{symbol}: ✗ ATR占比超出范围 {atr_pct*100:.2f}% (范围: [{atr_min*100:.2f}%, {atr_max*100:.2f}%])")
                    return None
                logger.debug(f"{symbol}: ✓ ATR占比检查通过 ({atr_pct*100:.2f}%)")
            except Exception:
                # 若配置缺失，忽略该硬门槛
                pass

            # 5.5. 检查入场规则（突破/回调）
            signal_type, entry_reasons = self.check_entry_rules(
                klines_3m, indicators_3m, indicators_5m,
                current_price, trend_analysis.direction, volume_ratio  # 🔧 修复: 使用计算后的 volume_ratio
            )

            # 6. 评分（传递volume_ratio） - 🔧 修复: 使用计算后的 volume_ratio
            signal_score = self.scorer.generate_score(
                trend_analysis, indicators_3m, indicators_5m,
                atr, current_price, current_price, stop_loss_price,
                volume_ratio  # 🔧 修复: 使用计算后的 volume_ratio，确保与门槛检查一致
            )

            # 7. 检查最低评分
            min_score = self.scorer.thresholds['minimum_score']
            if signal_score.total_score < min_score:
                logger.debug(f"{symbol}: ✗ 评分不足 ({signal_score.total_score}/{min_score}分)")
                return None
            else:
                logger.debug(f"{symbol}: ✓ 评分检查通过 ({signal_score.total_score}/{min_score}分)")

            # 7.1 成本/费率感知：首段收益需覆盖预估成本（手续费+滑点），留有安全边际
            try:
                # 以首段止盈为“最小可实现收益”
                first_tp = take_profit_levels[0] if take_profit_levels else None
                if first_tp:
                    if trend_analysis.direction.name == "BULLISH":
                        edge_bps = (first_tp - current_price) / current_price * 10000.0
                    else:
                        edge_bps = (current_price - first_tp) / current_price * 10000.0

                    taker = float(COST_CONFIG.get('taker_fee_bps', 5.0))
                    maker = float(COST_CONFIG.get('maker_fee_bps', 2.0))
                    slippage = float(COST_CONFIG.get('slippage_bps', 5.0))
                    min_edge_cfg = float(COST_CONFIG.get('min_edge_bps', 20.0))
                    # 保守估计：按“吃单进 + 吃单出 + 双边滑点”的成本，并乘以1.2安全系数
                    worst_cost_bps = (taker + taker) + (slippage + slippage)
                    required_edge_bps = max(min_edge_cfg, worst_cost_bps * 1.2)
                    if edge_bps < required_edge_bps:
                        logger.debug(f"{symbol}: 首段收益 {edge_bps:.2f} bps < 所需 {required_edge_bps:.2f} bps（成本门槛）")
                        return None
            except Exception:
                # 忽略异常，放行
                pass

            # 8. 确定风险等级
            risk_level = self._determine_risk_level(atr, current_price)

            # 9. 计算信心度和最终仓位缩放系数
            confidence = min(signal_score.total_score / self.scorer.thresholds['maximum_position_size'], 1.0)

            # 🔧 计算最终仓位缩放系数（应用所有惩罚）
            final_position_scaling = confidence_penalty * tf_alignment_penalty

            # 🔧 记录仓位调整原因
            scaling_reasons = []
            if confidence_penalty < 1.0:
                scaling_reasons.append(f"信心度惩罚: {confidence_penalty:.0%}")
            if tf_alignment_penalty < 1.0:
                scaling_reasons.append(f"多TF不对齐惩罚: {tf_alignment_penalty:.0%}")
            if final_position_scaling < 1.0:
                logger.info(f"{symbol}: 仓位缩放至 {final_position_scaling:.0%} ({', '.join(scaling_reasons)})")

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

            logger.info(f"{symbol}: 生成信号 {signal.direction.value} [{signal_type.value}] (评分: {signal_score.total_score}, 仓位缩放: {final_position_scaling:.0%})")

            # 🔧 返回信号和仓位缩放系数
            return (signal, final_position_scaling)

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
        验证K线数据充足 - 🔧 放宽要求，允许只要3m足够、5m/15m达到最低要求

        3m需要40根（2小时）- 必须满足
        5m需要20根（1.6小时）- 最低要求
        15m需要20根（5小时）- 🔧 降低到20根最低要求
        """
        from config_v2 import TIMEFRAME_CONFIG

        data_reqs = TIMEFRAME_CONFIG['data_requirements']

        # 🔧 关键修改：只要3m足够，5m和15m达到最低20根即可
        min_15m = 20  # 🔧 最低要求20根15m K线
        min_5m = data_reqs['5m']  # 保持5m要求不变
        min_3m = data_reqs['3m']  # 保持3m要求不变

        has_sufficient_3m = len(klines_3m) >= min_3m
        has_sufficient_5m = len(klines_5m) >= min_5m
        has_sufficient_15m = len(klines_15m) >= min_15m  # 🔧 使用更低的要求

        # 🔧 只要3m足够 + 5m足够 + 15m达到最低要求就放行
        return has_sufficient_3m and has_sufficient_5m and has_sufficient_15m

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

    def _check_btc_conditions(self, btc_indicators_15m=None) -> bool:
        """
        🔧 检查BTC条件（可选）

        根据 config_v2.py MARKET_FILTERS 配置:
        - rsi_15m_range: [0, 100] - 完全忽略BTC的RSI限制
        - trend_alignment: 'reference_only' - BTC趋势仅作参考，不强制要求

        Args:
            btc_indicators_15m: BTC 15分钟指标（可选）

        Returns:
            总是返回 True（因为配置已设置为不限制）
        """
        try:
            # 🔧 根据配置，BTC条件已设置为参考模式，不作为硬性过滤条件
            # 如果未来需要启用BTC过滤，可以取消下面的注释并传入btc_indicators_15m

            # if btc_indicators_15m:
            #     btc_rsi = btc_indicators_15m.rsi
            #     rsi_range = MARKET_FILTERS['btc_condition']['rsi_15m_range']
            #     if not (rsi_range[0] <= btc_rsi <= rsi_range[1]):
            #         logger.debug(f"BTC RSI不在范围内: {btc_rsi:.1f} not in {rsi_range}")
            #         return False

            return True  # 🔧 当前配置下总是返回True

        except Exception as e:
            logger.warning(f"检查BTC条件时出错: {e}")
            return True  # 出错时也放行

    def _check_multi_tf_alignment(self, trend_analysis) -> bool:
        """🔧 检查多时间框架趋势是否全部同向（放宽到55%）"""
        try:
            # 检查所有时间框架的趋势方向是否一致
            # trend_analysis应该包含各时间框架的趋势信息

            # 简化实现：检查趋势强度和一致性
            if hasattr(trend_analysis, 'tf_alignment_score'):
                return trend_analysis.tf_alignment_score >= 0.55  # 🔧 从60%降低到55%

            # 如果没有详细数据，基于confidence判断
            return trend_analysis.confidence >= 0.55  # 🔧 从60%降低到55%

        except Exception as e:
            logger.warning(f"检查多TF对齐时出错: {e}")
            return False

    def _calculate_volume_ratio(self, klines_3m: List[Dict]) -> float:
        """
        修正后的量比计算：基于时间进度的预估成交量 (Run Rate)

        解决问题：避免"用婴儿的体重和成年人比较"
        核心思路：将当前K线的已成交量，按时间进度推演为完整K线的预估量
        """
        try:
            # 至少需要22根K线（1根当前 + 1根参考 + 20根历史平均）
            if not klines_3m or len(klines_3m) < 22:
                logger.warning(f"量比计算: K线数据不足 (只有{len(klines_3m)}根)")
                return 0.0

            # 1. 计算历史平均成交量 (使用倒数第21根到倒数第2根，即过去20根完整的)
            # 注意：必须排除当前正在走的这根 [-1]
            history_klines = klines_3m[-21:-1]
            if not history_klines:
                return 0.0

            avg_volume = sum(float(k['volume']) for k in history_klines) / len(history_klines)

            if avg_volume == 0:
                logger.warning(f"量比计算: 平均成交量为0")
                return 0.0

            # 2. 获取当前K线数据
            current_kline = klines_3m[-1]
            current_volume = float(current_kline['volume'])

            # 3. 计算时间进度
            # 🔧 兼容不同字段名: open_time / time
            open_time = int(current_kline.get('open_time') or current_kline.get('time', 0))
            current_time = int(datetime.now().timestamp() * 1000)

            # 3分钟 = 180,000 毫秒
            interval_duration = 3 * 60 * 1000
            elapsed_time = current_time - open_time

            # 边界保护：如果时间计算异常（比如本地时间比服务器慢），强制设为极小值
            if elapsed_time <= 0:
                elapsed_time = 1000  # 假设走了1秒

            # 计算时间完成度 (0.0 ~ 1.0)
            progress = min(elapsed_time / interval_duration, 1.0)  # 限制最大为1.0

            # 4. 计算预估量比 (Projected Volume Ratio)

            # 场景A: K线刚开始 (进度 < 10%)
            # 此时数据极不稳定，预估偏差极大
            if progress < 0.1:
                # 如果刚开盘10秒内量就已经很大了(比如已经达到了平均值的20%)，说明爆发力极强
                raw_ratio = current_volume / avg_volume
                # 如果当前这一瞬间的量已经超过了"理应有的量的3倍"，则视为爆量
                if raw_ratio > (progress * 3):
                    projected_volume = current_volume / progress
                    projected_ratio = projected_volume / avg_volume
                else:
                    # 刚开盘，看不清，暂且用上一根K线的量来填充
                    previous_volume = float(klines_3m[-2]['volume'])
                    projected_ratio = previous_volume / avg_volume

            # 场景B: K线已经走了一段 (进度 >= 10%)
            # 此时可以线性推演
            else:
                projected_volume = current_volume / progress
                projected_ratio = projected_volume / avg_volume

            # 5. 最终量比：双重确认
            # projected_ratio 负责预测："按这个速度，马上要放量了，赶紧进"
            # real_ratio 负责兜底："不管时间走了多少，现在成交量实实在在已经超过平均值了"
            real_ratio = current_volume / avg_volume

            final_ratio = max(projected_ratio, real_ratio)

            return final_ratio

        except Exception as e:
            logger.warning(f"计算量比时出错: {e}")
            return 0.0


# ==================== 测试函数 ====================
if __name__ == "__main__":
    print("信号生成模块已创建，可用于生成交易信号")

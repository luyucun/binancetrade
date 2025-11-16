"""
趋势分析模块 (trend_analyzer.py)
用于分析多时间框架的趋势，判断市场是多头、空头还是震荡
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
from indicators import IndicatorCalculator, IndicatorResult
from config_v2 import TREND_RULES, INDICATOR_CONFIG


class TrendDirection(Enum):
    """趋势方向"""
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class TrendStrength(Enum):
    """趋势强度"""
    VERY_STRONG = "VERY_STRONG"  # 4/4条件满足
    STRONG = "STRONG"              # 3/4条件满足
    MODERATE = "MODERATE"          # 2/4条件满足
    WEAK = "WEAK"                  # 1/4条件满足
    NO_TREND = "NO_TREND"         # 0/4条件满足


@dataclass
class TrendAnalysis:
    """趋势分析结果"""
    direction: TrendDirection
    strength: TrendStrength
    primary_tf_score: int  # 3m级别匹配条件数
    confirmation_tf_score: int  # 5m级别匹配条件数
    trend_tf_score: int  # 15m级别匹配条件数
    reasons: List[str]  # 分析原因
    confidence: float  # 信心度 0-1


class TrendAnalyzer:
    """趋势分析器"""

    def __init__(self, config=TREND_RULES):
        """初始化趋势分析器"""
        self.config = config
        self.indicator_calc = IndicatorCalculator()

    # ==================== 多头趋势检查 ====================
    def check_bullish_trend(
        self,
        indicators_3m: IndicatorResult,
        indicators_5m: IndicatorResult,
        indicators_15m: IndicatorResult,
        current_price: float
    ) -> TrendAnalysis:
        """
        检查多头趋势条件

        Args:
            indicators_3m: 3分钟指标结果
            indicators_5m: 5分钟指标结果
            indicators_15m: 15分钟指标结果
            current_price: 当前价格

        Returns:
            趋势分析结果
        """
        reasons = []
        primary_tf_score = 0
        confirmation_tf_score = 0
        trend_tf_score = 0

        # ========== 3分钟级别检查 ==========
        # EMA20 > EMA50
        if indicators_3m.ema_21 > indicators_3m.ema_50:
            primary_tf_score += 1
            reasons.append("✓ 3m: EMA21 > EMA50 (上升趋势)")
        else:
            reasons.append("✗ 3m: EMA21 <= EMA50")

        # 价格 > EMA21
        if current_price > indicators_3m.ema_21:
            primary_tf_score += 1
            reasons.append(f"✓ 3m: 价格({current_price:.4f}) > EMA21({indicators_3m.ema_21:.4f})")
        else:
            reasons.append(f"✗ 3m: 价格 <= EMA21")

        # RSI 在 40-70 之间
        if 40 <= indicators_3m.rsi <= 70:
            primary_tf_score += 1
            reasons.append(f"✓ 3m: RSI({indicators_3m.rsi:.2f}) 在40-70范围内")
        else:
            reasons.append(f"✗ 3m: RSI({indicators_3m.rsi:.2f}) 超出范围")

        # ========== 5分钟级别检查 ==========
        # MACD > 0
        if indicators_5m.macd > 0:
            confirmation_tf_score += 1
            reasons.append(f"✓ 5m: MACD({indicators_5m.macd:.6f}) > 0")
        else:
            reasons.append(f"✗ 5m: MACD <= 0")

        # MACD斜率为正（MACD值增大）
        if indicators_5m.macd_histogram > 0:
            confirmation_tf_score += 1
            reasons.append(f"✓ 5m: MACD柱状图({indicators_5m.macd_histogram:.6f}) > 0 (斜率为正)")
        else:
            reasons.append(f"✗ 5m: MACD柱状图 <= 0")

        # 价格突破10周期高点 (增强版: 用ema_slope作为替代)
        # 注: 完整的突破检查需要传入完整的K线数据，这里用EMA斜率作为指示
        if hasattr(indicators_5m, 'ema_slope') and indicators_5m.ema_slope > 0:
            confirmation_tf_score += 1
            reasons.append(f"✓ 5m: 价格动量向上 (EMA斜率为正)")
        else:
            reasons.append(f"✗ 5m: 价格动量不够强")

        # ========== 15分钟级别检查 ==========
        # EMA20 > EMA50（主要趋势向上）
        if indicators_15m.ema_21 > indicators_15m.ema_50:
            trend_tf_score += 1
            reasons.append("✓ 15m: EMA21 > EMA50 (主要趋势向上)")
        else:
            reasons.append("✗ 15m: EMA21 <= EMA50")

        # 计算总体强度和信心
        total_score = primary_tf_score + confirmation_tf_score + trend_tf_score
        strength = self._get_trend_strength(total_score)
        confidence = total_score / 7.0  # 最多7个条件

        return TrendAnalysis(
            direction=TrendDirection.BULLISH,
            strength=strength,
            primary_tf_score=primary_tf_score,
            confirmation_tf_score=confirmation_tf_score,
            trend_tf_score=trend_tf_score,
            reasons=reasons,
            confidence=confidence
        )

    # ==================== 空头趋势检查 ====================
    def check_bearish_trend(
        self,
        indicators_3m: IndicatorResult,
        indicators_5m: IndicatorResult,
        indicators_15m: IndicatorResult,
        current_price: float
    ) -> TrendAnalysis:
        """
        检查空头趋势条件

        Args:
            indicators_3m: 3分钟指标结果
            indicators_5m: 5分钟指标结果
            indicators_15m: 15分钟指标结果
            current_price: 当前价格

        Returns:
            趋势分析结果
        """
        reasons = []
        primary_tf_score = 0
        confirmation_tf_score = 0
        trend_tf_score = 0

        # ========== 3分钟级别检查 ==========
        # EMA20 < EMA50
        if indicators_3m.ema_21 < indicators_3m.ema_50:
            primary_tf_score += 1
            reasons.append("✓ 3m: EMA21 < EMA50 (下降趋势)")
        else:
            reasons.append("✗ 3m: EMA21 >= EMA50")

        # 价格 < EMA21
        if current_price < indicators_3m.ema_21:
            primary_tf_score += 1
            reasons.append(f"✓ 3m: 价格({current_price:.4f}) < EMA21({indicators_3m.ema_21:.4f})")
        else:
            reasons.append(f"✗ 3m: 价格 >= EMA21")

        # RSI 在 30-60 之间
        if 30 <= indicators_3m.rsi <= 60:
            primary_tf_score += 1
            reasons.append(f"✓ 3m: RSI({indicators_3m.rsi:.2f}) 在30-60范围内")
        else:
            reasons.append(f"✗ 3m: RSI({indicators_3m.rsi:.2f}) 超出范围")

        # ========== 5分钟级别检查 ==========
        # MACD < 0
        if indicators_5m.macd < 0:
            confirmation_tf_score += 1
            reasons.append(f"✓ 5m: MACD({indicators_5m.macd:.6f}) < 0")
        else:
            reasons.append(f"✗ 5m: MACD >= 0")

        # MACD斜率为负（MACD值减小）
        if indicators_5m.macd_histogram < 0:
            confirmation_tf_score += 1
            reasons.append(f"✓ 5m: MACD柱状图({indicators_5m.macd_histogram:.6f}) < 0 (斜率为负)")
        else:
            reasons.append(f"✗ 5m: MACD柱状图 >= 0")

        # 价格突破10周期低点 (增强版: 用ema_slope作为替代)
        # 注: 完整的突破检查需要传入完整的K线数据，这里用EMA斜率作为指示
        if hasattr(indicators_5m, 'ema_slope') and indicators_5m.ema_slope < 0:
            confirmation_tf_score += 1
            reasons.append(f"✓ 5m: 价格动量向下 (EMA斜率为负)")
        else:
            reasons.append(f"✗ 5m: 价格动量不够弱")

        # ========== 15分钟级别检查 ==========
        # EMA20 < EMA50（主要趋势向下）
        if indicators_15m.ema_21 < indicators_15m.ema_50:
            trend_tf_score += 1
            reasons.append("✓ 15m: EMA21 < EMA50 (主要趋势向下)")
        else:
            reasons.append("✗ 15m: EMA21 >= EMA50")

        # 计算总体强度和信心
        total_score = primary_tf_score + confirmation_tf_score + trend_tf_score
        strength = self._get_trend_strength(total_score)
        confidence = total_score / 7.0  # 最多7个条件

        return TrendAnalysis(
            direction=TrendDirection.BEARISH,
            strength=strength,
            primary_tf_score=primary_tf_score,
            confirmation_tf_score=confirmation_tf_score,
            trend_tf_score=trend_tf_score,
            reasons=reasons,
            confidence=confidence
        )

    # ==================== 趋势判断 ====================
    def analyze_trend(
        self,
        indicators_3m: IndicatorResult,
        indicators_5m: IndicatorResult,
        indicators_15m: IndicatorResult,
        current_price: float
    ) -> TrendAnalysis:
        """
        综合分析趋势

        Args:
            indicators_3m: 3分钟指标
            indicators_5m: 5分钟指标
            indicators_15m: 15分钟指标
            current_price: 当前价格

        Returns:
            趋势分析结果
        """
        # 先检查15分钟大趋势（做整体过滤）
        main_trend_strength = 0
        if indicators_15m.ema_21 > indicators_15m.ema_50:
            main_trend_direction = TrendDirection.BULLISH
            main_trend_strength = 1
        elif indicators_15m.ema_21 < indicators_15m.ema_50:
            main_trend_direction = TrendDirection.BEARISH
            main_trend_strength = 1
        else:
            main_trend_direction = TrendDirection.NEUTRAL
            main_trend_strength = 0

        # 检查3分钟级别，倾向于与15分钟大趋势一致
        if main_trend_direction == TrendDirection.BULLISH:
            trend_analysis = self.check_bullish_trend(
                indicators_3m, indicators_5m, indicators_15m, current_price
            )
        elif main_trend_direction == TrendDirection.BEARISH:
            trend_analysis = self.check_bearish_trend(
                indicators_3m, indicators_5m, indicators_15m, current_price
            )
        else:
            # 中立，则分别检查两种情况，取较强的那个
            bullish = self.check_bullish_trend(
                indicators_3m, indicators_5m, indicators_15m, current_price
            )
            bearish = self.check_bearish_trend(
                indicators_3m, indicators_5m, indicators_15m, current_price
            )

            if bullish.confidence > bearish.confidence:
                trend_analysis = bullish
            elif bearish.confidence > bullish.confidence:
                trend_analysis = bearish
            else:
                # 信心度相同，返回中立
                trend_analysis = TrendAnalysis(
                    direction=TrendDirection.NEUTRAL,
                    strength=TrendStrength.NO_TREND,
                    primary_tf_score=0,
                    confirmation_tf_score=0,
                    trend_tf_score=0,
                    reasons=["市场中立，多空力量均衡"],
                    confidence=0.0
                )

        return trend_analysis

    # ==================== 支撑和阻力 ====================
    @staticmethod
    def find_support_resistance(
        prices: List[float],
        lookback: int = 20
    ) -> Tuple[float, float]:
        """
        查找支撑位和阻力位

        Args:
            prices: 价格列表
            lookback: 回看周期

        Returns:
            (支撑位, 阻力位)
        """
        if len(prices) < lookback:
            lookback = len(prices)

        recent_prices = prices[-lookback:]
        support = min(recent_prices)
        resistance = max(recent_prices)

        return support, resistance

    # ==================== 市场结构 ====================
    @staticmethod
    def check_market_structure_break(
        prices: List[float],
        direction: TrendDirection,
        lookback: int = 10
    ) -> bool:
        """
        检查是否突破了市场结构

        Args:
            prices: 价格列表
            direction: 趋势方向
            lookback: 回看周期

        Returns:
            是否突破
        """
        if len(prices) < lookback + 1:
            return False

        current_price = prices[-1]
        recent_high = max(prices[-lookback:-1])
        recent_low = min(prices[-lookback:-1])

        if direction == TrendDirection.BULLISH:
            return current_price > recent_high
        else:  # BEARISH
            return current_price < recent_low

    # ==================== 辅助方法 ====================
    @staticmethod
    def _get_trend_strength(score: int) -> TrendStrength:
        """
        根据条件匹配数获取趋势强度

        Args:
            score: 匹配条件数（0-7）

        Returns:
            趋势强度
        """
        if score >= 6:
            return TrendStrength.VERY_STRONG
        elif score >= 5:
            return TrendStrength.STRONG
        elif score >= 3:
            return TrendStrength.MODERATE
        elif score >= 1:
            return TrendStrength.WEAK
        else:
            return TrendStrength.NO_TREND

    @staticmethod
    def is_valid_trend(trend: TrendAnalysis) -> bool:
        """
        判断趋势是否有效（信心度>=0.5）

        Args:
            trend: 趋势分析结果

        Returns:
            是否有效
        """
        return trend.confidence >= 0.5 and trend.direction != TrendDirection.NEUTRAL


# ==================== 测试函数 ====================
if __name__ == "__main__":
    from datetime import datetime

    # 生成测试数据
    import random

    def generate_test_indicators():
        """生成测试指标数据"""
        return IndicatorResult(
            ema_21=100.5 + random.uniform(-1, 1),
            ema_50=100.0 + random.uniform(-0.5, 0.5),
            macd=0.1 + random.uniform(-0.05, 0.05),
            macd_signal=0.0 + random.uniform(-0.03, 0.03),
            macd_histogram=0.05 + random.uniform(-0.02, 0.02),
            rsi=55 + random.uniform(-10, 10),
            atr=0.5 + random.uniform(-0.1, 0.1),
            bb_upper=102 + random.uniform(-0.5, 0.5),
            bb_middle=100 + random.uniform(-0.5, 0.5),
            bb_lower=98 + random.uniform(-0.5, 0.5),
            ema_slope=0.1 + random.uniform(-0.05, 0.05),
            price_to_ema=1.005 + random.uniform(-0.005, 0.005),
            rsi_strength="NEUTRAL"
        )

    analyzer = TrendAnalyzer()

    print("=" * 60)
    print("趋势分析测试")
    print("=" * 60)

    # 测试多头趋势
    print("\n[测试1] 多头趋势分析")
    print("-" * 60)
    ind_3m = generate_test_indicators()
    ind_5m = generate_test_indicators()
    ind_15m = generate_test_indicators()
    current_price = 101.0

    result = analyzer.analyze_trend(ind_3m, ind_5m, ind_15m, current_price)

    print(f"趋势方向: {result.direction.value}")
    print(f"趋势强度: {result.strength.value}")
    print(f"信心度: {result.confidence:.2%}")
    print(f"3m评分: {result.primary_tf_score}/3")
    print(f"5m评分: {result.confirmation_tf_score}/2")
    print(f"15m评分: {result.trend_tf_score}/1")
    print("\n分析原因:")
    for reason in result.reasons:
        print(f"  {reason}")

    # 测试市场结构
    print("\n[测试2] 市场结构突破")
    print("-" * 60)
    prices = [100 + i * 0.1 for i in range(50)]
    is_break = analyzer.check_market_structure_break(prices, TrendDirection.BULLISH, 10)
    print(f"是否突破多头市场结构: {is_break}")

    # 测试支撑阻力
    print("\n[测试3] 支撑和阻力位")
    print("-" * 60)
    support, resistance = analyzer.find_support_resistance(prices, 20)
    print(f"支撑位: {support:.2f}")
    print(f"阻力位: {resistance:.2f}")

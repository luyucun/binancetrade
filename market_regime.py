"""
市场状态判断模块 (market_regime.py)
根据BTC波动率和趋势判断当前市场状态，动态调整交易参数
"""

from typing import Dict, Optional, Tuple
from enum import Enum
from dataclasses import dataclass
import logging
from datetime import datetime, timedelta

from config_v2 import MARKET_REGIME_CONFIG
from indicators import IndicatorResult


logger = logging.getLogger(__name__)


class MarketRegime(Enum):
    """市场状态枚举"""
    HIGH_VOL = "HIGH_VOL"   # 高波动市场
    LOW_VOL = "LOW_VOL"     # 低波动市场
    NORMAL = "NORMAL"       # 正常市场


@dataclass
class RegimeAnalysis:
    """市场状态分析结果"""
    regime: MarketRegime
    volatility_ratio: float     # 波动率比率 (ATR/Price)
    btc_trend: str              # BTC趋势方向 ('UP', 'DOWN', 'SIDEWAYS')
    confidence: float           # 判断置信度 (0-1)
    params: Dict                # 对应参数
    reasons: list               # 判断原因


class MarketRegimeDetector:
    """市场状态检测器"""

    def __init__(self, config=MARKET_REGIME_CONFIG):
        """初始化检测器"""
        self.config = config
        self.volatility_thresholds = config['volatility_thresholds']
        self.regime_params = config['regime_params']

        # 状态缓存（避免频繁切换）
        self.current_regime = MarketRegime.NORMAL
        self.last_update_time = None
        self.regime_stable_count = 0  # 连续相同状态计数
        self.min_stable_count = 3     # 至少连续3次相同才切换

    def detect_regime(
        self,
        btc_indicators: IndicatorResult,
        btc_price: float
    ) -> RegimeAnalysis:
        """
        检测当前市场状态

        Args:
            btc_indicators: BTC的指标数据
            btc_price: BTC当前价格

        Returns:
            RegimeAnalysis: 市场状态分析结果
        """
        reasons = []

        # 1. 计算波动率比率
        volatility_ratio = btc_indicators.atr / btc_price
        reasons.append(f"BTC波动率: {volatility_ratio:.4f} ({volatility_ratio*100:.2f}%)")

        # 2. 判断原始状态
        high_vol_threshold = self.volatility_thresholds['high_vol']
        low_vol_threshold = self.volatility_thresholds['low_vol']

        if volatility_ratio > high_vol_threshold:
            raw_regime = MarketRegime.HIGH_VOL
            reasons.append(f"✓ 高波动: {volatility_ratio:.4f} > {high_vol_threshold}")
        elif volatility_ratio < low_vol_threshold:
            raw_regime = MarketRegime.LOW_VOL
            reasons.append(f"✓ 低波动: {volatility_ratio:.4f} < {low_vol_threshold}")
        else:
            raw_regime = MarketRegime.NORMAL
            reasons.append(f"○ 正常波动: {low_vol_threshold} <= {volatility_ratio:.4f} <= {high_vol_threshold}")

        # 3. 判断BTC趋势
        btc_trend = self._detect_btc_trend(btc_indicators, btc_price)
        reasons.append(f"BTC趋势: {btc_trend}")

        # 4. 状态平滑（避免频繁切换）
        final_regime = self._smooth_regime(raw_regime)

        # 5. 计算置信度
        confidence = self._calculate_confidence(volatility_ratio, btc_trend)

        # 6. 获取对应参数
        params = self.regime_params.get(final_regime.value, {})

        return RegimeAnalysis(
            regime=final_regime,
            volatility_ratio=volatility_ratio,
            btc_trend=btc_trend,
            confidence=confidence,
            params=params,
            reasons=reasons
        )

    def _detect_btc_trend(self, indicators: IndicatorResult, price: float) -> str:
        """
        检测BTC趋势方向

        Returns:
            'UP', 'DOWN', 'SIDEWAYS'
        """
        # 使用EMA和RSI判断趋势
        ema_trend_up = price > indicators.ema_21 > indicators.ema_50
        ema_trend_down = price < indicators.ema_21 < indicators.ema_50

        rsi = indicators.rsi

        if ema_trend_up and rsi > 50:
            return 'UP'
        elif ema_trend_down and rsi < 50:
            return 'DOWN'
        else:
            return 'SIDEWAYS'

    def _smooth_regime(self, raw_regime: MarketRegime) -> MarketRegime:
        """
        平滑状态切换，避免频繁变化

        Args:
            raw_regime: 原始检测状态

        Returns:
            平滑后的状态
        """
        if raw_regime == self.current_regime:
            self.regime_stable_count += 1
        else:
            self.regime_stable_count = 1

        # 只有连续min_stable_count次相同才切换
        if self.regime_stable_count >= self.min_stable_count:
            if raw_regime != self.current_regime:
                logger.info(f"市场状态切换: {self.current_regime.value} -> {raw_regime.value}")
                self.current_regime = raw_regime

        return self.current_regime

    def _calculate_confidence(self, volatility_ratio: float, btc_trend: str) -> float:
        """
        计算状态判断的置信度

        Returns:
            0-1的置信度
        """
        confidence = 0.5  # 基础置信度

        high_vol = self.volatility_thresholds['high_vol']
        low_vol = self.volatility_thresholds['low_vol']

        # 波动率越极端，置信度越高
        if volatility_ratio > high_vol * 1.5:
            confidence += 0.3  # 非常高波动
        elif volatility_ratio > high_vol:
            confidence += 0.2
        elif volatility_ratio < low_vol * 0.5:
            confidence += 0.3  # 非常低波动
        elif volatility_ratio < low_vol:
            confidence += 0.2

        # BTC趋势明确时增加置信度
        if btc_trend in ['UP', 'DOWN']:
            confidence += 0.1

        return min(confidence, 1.0)

    def get_adjusted_params(self, base_config: Dict) -> Dict:
        """
        根据当前市场状态获取调整后的参数

        Args:
            base_config: 基础配置

        Returns:
            调整后的配置
        """
        regime_params = self.regime_params.get(self.current_regime.value, {})

        adjusted = base_config.copy()

        # 调整最低评分
        if 'min_score' in regime_params:
            adjusted['min_score'] = regime_params['min_score']

        # 调整止损倍率
        if 'stop_loss_mult' in regime_params:
            adjusted['stop_loss_mult'] = regime_params['stop_loss_mult']

        # 调整最大持仓数
        if 'max_positions' in regime_params:
            adjusted['max_positions'] = regime_params['max_positions']

        # 调整仓位倍率
        if 'position_size_mult' in regime_params:
            adjusted['position_size_mult'] = regime_params['position_size_mult']

        return adjusted

    def get_min_score(self) -> int:
        """获取当前状态下的最低评分要求"""
        params = self.regime_params.get(self.current_regime.value, {})
        return params.get('min_score', 8)

    def get_max_positions(self) -> int:
        """获取当前状态下的最大持仓数"""
        params = self.regime_params.get(self.current_regime.value, {})
        return params.get('max_positions', 5)

    def should_reduce_exposure(self) -> bool:
        """是否应该降低风险暴露"""
        return self.current_regime == MarketRegime.HIGH_VOL


# ==================== 测试函数 ====================
if __name__ == "__main__":
    print("市场状态检测模块已创建")

    # 模拟测试
    from dataclasses import dataclass

    @dataclass
    class MockIndicator:
        atr: float = 500.0
        rsi: float = 55.0
        ema_21: float = 95000.0
        ema_50: float = 94000.0

    detector = MarketRegimeDetector()

    # 测试高波动
    high_vol_ind = MockIndicator(atr=2000.0)  # ATR很高
    result = detector.detect_regime(high_vol_ind, 96000.0)
    print(f"高波动测试: {result.regime.value}, 置信度: {result.confidence:.2f}")

    # 测试低波动
    low_vol_ind = MockIndicator(atr=200.0)  # ATR很低
    result = detector.detect_regime(low_vol_ind, 96000.0)
    print(f"低波动测试: {result.regime.value}, 置信度: {result.confidence:.2f}")

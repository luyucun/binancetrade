"""
技术指标计算模块 (indicators.py)
用于计算所有的技术指标：EMA、MACD、RSI、ATR、布林线等
"""

import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from config_v2 import INDICATOR_CONFIG


@dataclass
class IndicatorResult:
    """指标计算结果"""
    ema_21: float
    ema_50: float
    macd: float
    macd_signal: float
    macd_histogram: float
    rsi: float
    atr: float
    bb_upper: float
    bb_middle: float
    bb_lower: float

    # 派生指标
    ema_slope: float  # EMA斜率
    price_to_ema: float  # 价格与EMA的比率
    rsi_strength: str  # RSI强度标签


class IndicatorCalculator:
    """技术指标计算器"""

    def __init__(self, config=INDICATOR_CONFIG):
        """初始化指标计算器"""
        self.config = config
        self.ema_short = config['ema']['short_period']
        self.ema_long = config['ema']['long_period']
        self.macd_fast = config['macd']['fast_period']
        self.macd_slow = config['macd']['slow_period']
        self.macd_signal = config['macd']['signal_period']
        self.rsi_period = config['rsi']['period']
        self.atr_period = config['atr']['period']
        self.bb_period = config['bb']['period']
        self.bb_std_dev = config['bb']['std_dev']

    # ==================== EMA 计算 ====================
    @staticmethod
    def calculate_ema(prices: List[float], period: int) -> List[float]:
        """
        计算指数移动平均线 (EMA)

        Args:
            prices: 价格列表
            period: 周期

        Returns:
            EMA值列表
        """
        if len(prices) < period:
            return [None] * len(prices)

        ema_values = []
        multiplier = 2 / (period + 1)

        # 简单移动平均线作为第一个EMA值
        sma = np.mean(prices[:period])
        ema_values.append(sma)

        # 计算后续EMA
        for i in range(period, len(prices)):
            ema = prices[i] * multiplier + ema_values[-1] * (1 - multiplier)
            ema_values.append(ema)

        # 填充前面的None值
        return [None] * (period - 1) + ema_values

    # ==================== MACD 计算 ====================
    @staticmethod
    def calculate_macd(
        prices: List[float],
        fast: int = 12,
        slow: int = 26,
        signal: int = 9
    ) -> Tuple[List[float], List[float], List[float]]:
        """
        计算MACD指标

        Args:
            prices: 价格列表
            fast: 快速周期
            slow: 慢速周期
            signal: 信号线周期

        Returns:
            (MACD线, 信号线, 柱状图)
        """
        ema_fast = IndicatorCalculator.calculate_ema(prices, fast)
        ema_slow = IndicatorCalculator.calculate_ema(prices, slow)

        # 计算MACD线
        macd_line = [
            f - s if f is not None and s is not None else None
            for f, s in zip(ema_fast, ema_slow)
        ]

        # 计算信号线（MACD的EMA）
        macd_values = [v for v in macd_line if v is not None]
        signal_line = [None] * len(macd_line)

        if len(macd_values) >= signal:
            signal_values = IndicatorCalculator.calculate_ema(macd_values, signal)
            # 填充到原始长度
            idx = slow - 1
            for sv in signal_values:
                if idx < len(signal_line):
                    signal_line[idx] = sv
                    idx += 1

        # 计算柱状图（MACD - 信号线）
        histogram = [
            m - s if m is not None and s is not None else None
            for m, s in zip(macd_line, signal_line)
        ]

        return macd_line, signal_line, histogram

    # ==================== RSI 计算 ====================
    @staticmethod
    def calculate_rsi(prices: List[float], period: int = 14) -> List[float]:
        """
        计算相对强度指数 (RSI)

        Args:
            prices: 价格列表
            period: 周期（默认14）

        Returns:
            RSI值列表
        """
        if len(prices) < period + 1:
            return [None] * len(prices)

        # 计算价格变化
        deltas = []
        for i in range(1, len(prices)):
            deltas.append(prices[i] - prices[i - 1])

        # 分离上升和下跌
        gains = [d if d > 0 else 0 for d in deltas]
        losses = [-d if d < 0 else 0 for d in deltas]

        rsi_values = [None] * len(prices)

        # 计算第一个RSI（简单平均）
        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])

        if avg_loss == 0:
            rs = 100 if avg_gain > 0 else 0
        else:
            rs = 100 - (100 / (1 + avg_gain / avg_loss))

        rsi_values[period] = rs

        # 计算后续RSI（平滑平均）
        for i in range(period + 1, len(prices)):
            avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period

            if avg_loss == 0:
                rs = 100 if avg_gain > 0 else 0
            else:
                rs = 100 - (100 / (1 + avg_gain / avg_loss))

            rsi_values[i] = rs

        return rsi_values

    # ==================== ATR 计算 ====================
    @staticmethod
    def calculate_atr(
        highs: List[float],
        lows: List[float],
        closes: List[float],
        period: int = 14
    ) -> List[float]:
        """
        计算平均真实波幅 (ATR)

        Args:
            highs: 最高价列表
            lows: 最低价列表
            closes: 收盘价列表
            period: 周期（默认14）

        Returns:
            ATR值列表
        """
        if len(highs) < period or len(lows) < period or len(closes) < period:
            return [None] * len(closes)

        # 计算True Range
        tr_values = []
        for i in range(len(closes)):
            if i == 0:
                tr = highs[i] - lows[i]
            else:
                tr = max(
                    highs[i] - lows[i],
                    abs(highs[i] - closes[i - 1]),
                    abs(lows[i] - closes[i - 1])
                )
            tr_values.append(tr)

        # 计算ATR
        atr_values = [None] * len(closes)

        # 第一个ATR是简单平均
        atr = np.mean(tr_values[:period])
        atr_values[period - 1] = atr

        # 后续ATR使用平滑平均
        for i in range(period, len(closes)):
            atr = (atr * (period - 1) + tr_values[i]) / period
            atr_values[i] = atr

        return atr_values

    # ==================== 布林线计算 ====================
    @staticmethod
    def calculate_bollinger_bands(
        prices: List[float],
        period: int = 20,
        std_dev: float = 2.0
    ) -> Tuple[List[float], List[float], List[float]]:
        """
        计算布林线 (Bollinger Bands)

        Args:
            prices: 价格列表
            period: 周期（默认20）
            std_dev: 标准差倍数（默认2）

        Returns:
            (上轨, 中线, 下轨)
        """
        if len(prices) < period:
            return [None] * len(prices), [None] * len(prices), [None] * len(prices)

        middle_band = []
        upper_band = []
        lower_band = []

        for i in range(len(prices)):
            if i < period - 1:
                middle_band.append(None)
                upper_band.append(None)
                lower_band.append(None)
            else:
                # 计算简单移动平均（中线）
                sma = np.mean(prices[i - period + 1:i + 1])
                middle_band.append(sma)

                # 计算标准差
                std = np.std(prices[i - period + 1:i + 1])

                # 计算上下轨
                upper_band.append(sma + std_dev * std)
                lower_band.append(sma - std_dev * std)

        return upper_band, middle_band, lower_band

    # ==================== 高级指标 ====================
    @staticmethod
    def calculate_ema_slope(
        ema_values: List[float],
        period: int = 3
    ) -> List[float]:
        """
        计算EMA斜率（用于判断EMA上升/下降速度）

        Args:
            ema_values: EMA值列表
            period: 用于计算斜率的周期

        Returns:
            斜率列表
        """
        slopes = [None] * len(ema_values)

        for i in range(period, len(ema_values)):
            if ema_values[i] is not None and ema_values[i - period] is not None:
                slope = (ema_values[i] - ema_values[i - period]) / period
                slopes[i] = slope

        return slopes

    @staticmethod
    def calculate_macd_slope(
        macd_values: List[float],
        period: int = 2
    ) -> List[float]:
        """
        计算MACD斜率（判断MACD上升/下降速度）

        Args:
            macd_values: MACD值列表
            period: 用于计算斜率的周期

        Returns:
            斜率列表
        """
        slopes = [None] * len(macd_values)

        for i in range(period, len(macd_values)):
            if macd_values[i] is not None and macd_values[i - period] is not None:
                slope = macd_values[i] - macd_values[i - period]
                slopes[i] = slope

        return slopes

    @staticmethod
    def get_recent_high(prices: List[float], lookback: int = 10) -> float:
        """获取最近N根K线的最高价"""
        if len(prices) < lookback:
            return max(prices) if prices else 0
        return max(prices[-lookback:])

    @staticmethod
    def get_recent_low(prices: List[float], lookback: int = 10) -> float:
        """获取最近N根K线的最低价"""
        if len(prices) < lookback:
            return min(prices) if prices else 0
        return min(prices[-lookback:])

    # ==================== 综合指标计算 ====================
    def calculate_all_indicators(
        self,
        closes: List[float],
        highs: List[float],
        lows: List[float],
        volumes: List[float],
        min_periods: int = None
    ) -> Optional[IndicatorResult]:
        """
        计算所有指标

        Args:
            closes: 收盘价列表
            highs: 最高价列表
            lows: 最低价列表
            volumes: 成交量列表
            min_periods: 最小周期数，默认使用ema_long(50)

        Returns:
            指标结果对象
        """
        # 使用较小的最小周期要求，只要能计算出基础指标即可
        min_required = min_periods if min_periods else max(self.ema_long, self.macd_slow + self.macd_signal)

        # 改进: 放宽要求，只要有基础的数据就尝试计算
        if not closes or len(closes) < 20:  # 至少20根K线
            return None

        try:
            # 计算EMA
            ema_21_list = self.calculate_ema(closes, self.ema_short)
            ema_50_list = self.calculate_ema(closes, self.ema_long)

            ema_21 = ema_21_list[-1] if ema_21_list[-1] is not None else closes[-1]
            ema_50 = ema_50_list[-1] if ema_50_list[-1] is not None else closes[-1]

            # 计算MACD
            macd_line, signal_line, histogram = self.calculate_macd(
                closes,
                self.macd_fast,
                self.macd_slow,
                self.macd_signal
            )

            macd = macd_line[-1] if macd_line[-1] is not None else 0
            macd_sig = signal_line[-1] if signal_line[-1] is not None else 0
            macd_hist = histogram[-1] if histogram[-1] is not None else 0

            # 计算RSI
            rsi_list = self.calculate_rsi(closes, self.rsi_period)
            rsi = rsi_list[-1] if rsi_list[-1] is not None else 50

            # 计算ATR
            atr_list = self.calculate_atr(highs, lows, closes, self.atr_period)
            atr = atr_list[-1] if atr_list[-1] is not None else (closes[-1] * 0.01)  # 默认1%

            # 计算布林线
            bb_upper, bb_middle, bb_lower = self.calculate_bollinger_bands(
                closes,
                self.bb_period,
                self.bb_std_dev
            )

            # 计算派生指标
            ema_slope = (ema_21 - ema_21_list[-2]) if ema_21_list[-2] is not None else 0
            price_to_ema = closes[-1] / ema_21 if ema_21 else 0

            # RSI强度标签
            if rsi >= 70:
                rsi_strength = "OVERBOUGHT"
            elif rsi <= 30:
                rsi_strength = "OVERSOLD"
            elif rsi >= 60:
                rsi_strength = "STRONG"
            elif rsi <= 40:
                rsi_strength = "WEAK"
            else:
                rsi_strength = "NEUTRAL"

            return IndicatorResult(
                ema_21=ema_21,
                ema_50=ema_50,
                macd=macd,
                macd_signal=macd_sig,
                macd_histogram=macd_hist,
                rsi=rsi,
                atr=atr,
                bb_upper=bb_upper[-1],
                bb_middle=bb_middle[-1],
                bb_lower=bb_lower[-1],
                ema_slope=ema_slope,
                price_to_ema=price_to_ema,
                rsi_strength=rsi_strength
            )

        except Exception as e:
            # 🔧 使用logging而不是print
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"计算指标时出错 (数据点数: {len(closes)}): {e}")
            return None


# ==================== 测试函数 ====================
if __name__ == "__main__":
    # 生成测试数据
    import random

    base_price = 100.0
    closes = []
    for _ in range(100):
        change = random.uniform(-0.5, 0.5)
        base_price += change
        closes.append(max(base_price, 1))

    highs = [c + random.uniform(0, 1) for c in closes]
    lows = [c - random.uniform(0, 1) for c in closes]
    volumes = [random.uniform(1000, 5000) for _ in closes]

    # 计算指标
    calculator = IndicatorCalculator()
    result = calculator.calculate_all_indicators(closes, highs, lows, volumes)

    if result:
        print(f"EMA21: {result.ema_21:.2f}")
        print(f"EMA50: {result.ema_50:.2f}")
        print(f"MACD: {result.macd:.4f}")
        print(f"RSI: {result.rsi:.2f}")
        print(f"ATR: {result.atr:.4f}")
        print(f"RSI Strength: {result.rsi_strength}")

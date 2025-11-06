"""
ATR基础动态止损/止盈管理模块

功能：
- 基于ATR波动性计算动态止损/止盈
- 支持分批止盈（快速获利 + Trailing Stop）
- 自适应不同币种的波动性
"""

import logging
from typing import Dict, Optional, Tuple
import statistics

logger = logging.getLogger(__name__)


class ATRBasedRiskManager:
    """基于ATR的风险管理系统"""

    # ATR系数配置 - 优化版本
    INITIAL_STOP_LOSS_MULTIPLIER = 0.8      # 初始止损: 0.8 × ATR (从1.0降到0.8 收紧止损)
    FIRST_PROFIT_TARGET = 1.5               # 第一止盈: 1.5 × ATR (从1.0升到1.5 扩大止盈)
    FIRST_PROFIT_PERCENTAGE = 0.4           # 第一止盈时平仓40% (剩余60%)
    TRAILING_STOP_MULTIPLIER = 1.0          # Trailing Stop: 1.0 × ATR (提高到1.0保护利润)

    # 最小/最大值限制（防止极端情况）
    MIN_STOP_LOSS_PCT = 0.2                 # 最小止损0.2%
    MAX_STOP_LOSS_PCT = 2.0                 # 最大止损2.0%
    MIN_TAKE_PROFIT_PCT = 0.3               # 最小止盈0.3%
    MAX_TAKE_PROFIT_PCT = 5.0               # 最大止盈5.0%

    @staticmethod
    def calculate_atr(klines: list, period: int = 14) -> float:
        """计算ATR（平均真实波幅）"""
        if not klines or len(klines) < period:
            return 0.0

        try:
            true_ranges = []

            for i in range(len(klines) - period, len(klines)):
                if i < 0:
                    continue

                current = klines[i]
                high = float(current.get('high', 0))
                low = float(current.get('low', 0))
                close = float(current.get('close', 0))

                if i > 0:
                    prev_close = float(klines[i - 1].get('close', 0))
                else:
                    prev_close = low

                tr = max(
                    high - low,
                    abs(high - prev_close),
                    abs(low - prev_close)
                )
                true_ranges.append(tr)

            atr = statistics.mean(true_ranges) if true_ranges else 0.0
            return atr

        except Exception as e:
            logger.error(f"计算ATR失败: {e}")
            return 0.0

    @staticmethod
    def calculate_risk_levels(
        entry_price: float,
        klines: list,
        side: str = 'BUY'
    ) -> Dict:
        """
        基于ATR计算风险等级和止损/止盈价格

        返回：
        {
            'atr': float,                    # ATR值
            'atr_pct': float,                # ATR百分比
            'stop_loss_price': float,        # 止损价格
            'stop_loss_pct': float,          # 止损百分比
            'first_profit_price': float,     # 第一止盈价格（40%）
            'first_profit_pct': float,       # 第一止盈百分比
            'first_profit_quantity_pct': float,  # 第一止盈平仓百分比
            'trailing_stop_price': float,    # 追踪止损价格（剩余60%）
            'trailing_stop_pct': float,      # 追踪止损百分比
            'risk_level': str,               # 风险等级: LOW/MEDIUM/HIGH
        }
        """
        try:
            # 计算ATR
            atr = ATRBasedRiskManager.calculate_atr(klines, 14)
            if atr == 0:
                logger.warning(f"无法计算ATR，使用默认配置")
                atr = entry_price * 0.005  # 默认0.5%

            # ATR百分比
            atr_pct = (atr / entry_price) * 100

            # 计算止损价格
            if side == 'BUY':
                # 做多: 止损在下方
                stop_loss_price = entry_price - (ATRBasedRiskManager.INITIAL_STOP_LOSS_MULTIPLIER * atr)
                stop_loss_pct = ((entry_price - stop_loss_price) / entry_price) * 100

                # 第一止盈价格 (40%止盈)
                first_profit_price = entry_price + (ATRBasedRiskManager.FIRST_PROFIT_TARGET * atr)
                first_profit_pct = ((first_profit_price - entry_price) / entry_price) * 100

                # 追踪止损价格 (剩余60%, 使用较小的ATR倍数)
                trailing_stop_price = entry_price + (ATRBasedRiskManager.TRAILING_STOP_MULTIPLIER * atr)
                trailing_stop_pct = ((trailing_stop_price - entry_price) / entry_price) * 100

            else:  # SELL
                # 做空: 止损在上方
                stop_loss_price = entry_price + (ATRBasedRiskManager.INITIAL_STOP_LOSS_MULTIPLIER * atr)
                stop_loss_pct = ((stop_loss_price - entry_price) / entry_price) * 100

                # 第一止盈价格 (40%止盈)
                first_profit_price = entry_price - (ATRBasedRiskManager.FIRST_PROFIT_TARGET * atr)
                first_profit_pct = ((entry_price - first_profit_price) / entry_price) * 100

                # 追踪止损价格 (剩余60%)
                trailing_stop_price = entry_price - (ATRBasedRiskManager.TRAILING_STOP_MULTIPLIER * atr)
                trailing_stop_pct = ((entry_price - trailing_stop_price) / entry_price) * 100

            # 限制范围
            stop_loss_pct = max(
                min(stop_loss_pct, ATRBasedRiskManager.MAX_STOP_LOSS_PCT),
                ATRBasedRiskManager.MIN_STOP_LOSS_PCT
            )

            first_profit_pct = max(
                min(first_profit_pct, ATRBasedRiskManager.MAX_TAKE_PROFIT_PCT),
                ATRBasedRiskManager.MIN_TAKE_PROFIT_PCT
            )

            # 判断风险等级
            if atr_pct < 0.5:
                risk_level = "LOW"      # 低波动
            elif atr_pct < 1.0:
                risk_level = "MEDIUM"   # 中波动
            else:
                risk_level = "HIGH"     # 高波动

            result = {
                'atr': atr,
                'atr_pct': atr_pct,
                'stop_loss_price': stop_loss_price,
                'stop_loss_pct': stop_loss_pct,
                'first_profit_price': first_profit_price,
                'first_profit_pct': first_profit_pct,
                'first_profit_quantity_pct': ATRBasedRiskManager.FIRST_PROFIT_PERCENTAGE,
                'trailing_stop_price': trailing_stop_price,
                'trailing_stop_pct': trailing_stop_pct,
                'risk_level': risk_level,
            }

            logger.info(
                f"【ATR风险计算】entry={entry_price:.2f}, side={side}\n"
                f"  ATR={atr:.4f} ({atr_pct:.2f}%) → 风险等级: {risk_level}\n"
                f"  止损: {stop_loss_price:.4f} ({stop_loss_pct:.2f}%)\n"
                f"  第一止盈: {first_profit_price:.4f} ({first_profit_pct:.2f}%) - 平仓40%\n"
                f"  追踪止损: {trailing_stop_price:.4f} ({trailing_stop_pct:.2f}%) - 剩余60%"
            )

            return result

        except Exception as e:
            logger.error(f"计算风险等级失败: {e}")
            return {
                'atr': 0,
                'atr_pct': 0,
                'stop_loss_price': entry_price * 0.995,
                'stop_loss_pct': 0.5,
                'first_profit_price': entry_price * 1.01,
                'first_profit_pct': 1.0,
                'first_profit_quantity_pct': 0.4,
                'trailing_stop_price': entry_price * 1.006,
                'trailing_stop_pct': 0.6,
                'risk_level': 'MEDIUM',
            }

    @staticmethod
    def check_first_profit_hit(
        current_price: float,
        entry_price: float,
        first_profit_price: float,
        side: str = 'BUY'
    ) -> bool:
        """
        检查是否达到第一止盈点（快速获利）

        返回: 是否达到第一止盈
        """
        if side == 'BUY':
            # 做多: 当前价 >= 第一止盈价
            return current_price >= first_profit_price
        else:  # SELL
            # 做空: 当前价 <= 第一止盈价
            return current_price <= first_profit_price

    @staticmethod
    def check_trailing_stop_hit(
        current_price: float,
        entry_price: float,
        trailing_stop_price: float,
        side: str = 'BUY'
    ) -> bool:
        """
        检查Trailing Stop是否被触发

        返回: 是否触发Trailing Stop
        """
        if side == 'BUY':
            # 做多: 当前价 <= Trailing Stop价
            return current_price <= trailing_stop_price
        else:  # SELL
            # 做空: 当前价 >= Trailing Stop价
            return current_price >= trailing_stop_price

    @staticmethod
    def update_trailing_stop(
        current_price: float,
        entry_price: float,
        first_profit_price: float,
        old_trailing_stop_price: float,
        side: str = 'BUY'
    ) -> Tuple[float, bool]:
        """
        更新Trailing Stop（随行情上升而提升止损价）

        返回: (新的trailing_stop_price, 是否更新)
        """
        if side == 'BUY':
            # 做多: 如果当前价高于第一止盈，可以提升Trailing Stop
            if current_price >= first_profit_price:
                # 计算ATR（简化: 使用价格差）
                price_above_entry = current_price - entry_price
                new_trailing_stop = current_price - (0.6 * price_above_entry)

                # 只有当新的Trailing Stop高于旧的才更新
                if new_trailing_stop > old_trailing_stop_price:
                    logger.info(
                        f"【更新Trailing Stop】做多\n"
                        f"  当前价: {current_price:.4f}\n"
                        f"  旧止损: {old_trailing_stop_price:.4f}\n"
                        f"  新止损: {new_trailing_stop:.4f}"
                    )
                    return new_trailing_stop, True

        else:  # SELL
            # 做空: 如果当前价低于第一止盈，可以降低Trailing Stop
            if current_price <= first_profit_price:
                price_below_entry = entry_price - current_price
                new_trailing_stop = current_price + (0.6 * price_below_entry)

                # 只有当新的Trailing Stop低于旧的才更新
                if new_trailing_stop < old_trailing_stop_price:
                    logger.info(
                        f"【更新Trailing Stop】做空\n"
                        f"  当前价: {current_price:.4f}\n"
                        f"  旧止损: {old_trailing_stop_price:.4f}\n"
                        f"  新止损: {new_trailing_stop:.4f}"
                    )
                    return new_trailing_stop, True

        return old_trailing_stop_price, False


# 使用示例
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # 模拟K线数据
    test_klines = [
        {'high': 50100, 'low': 49900, 'close': 50000},
        {'high': 50200, 'low': 50000, 'close': 50100},
        {'high': 50300, 'low': 50100, 'close': 50200},
    ]

    # 计算风险等级
    risk_levels = ATRBasedRiskManager.calculate_risk_levels(50000, test_klines, 'BUY')
    print(f"ATR: {risk_levels['atr']:.4f}")
    print(f"止损: {risk_levels['stop_loss_price']:.4f} ({risk_levels['stop_loss_pct']:.2f}%)")
    print(f"第一止盈: {risk_levels['first_profit_price']:.4f} ({risk_levels['first_profit_pct']:.2f}%)")
    print(f"追踪止损: {risk_levels['trailing_stop_price']:.4f}")
    print(f"风险等级: {risk_levels['risk_level']}")

"""
选币策略模块 (coin_selector.py)
用于从币种池中筛选符合条件的交易币种
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import json
import logging
from config_v2 import SELECTION_CONFIG, TIMEFRAME_CONFIG


logger = logging.getLogger(__name__)


@dataclass
class CoinInfo:
    """币种信息"""
    symbol: str
    current_price: float
    change_24h: float
    volume_24h: float
    current_volume: float
    is_usdt_pair: bool


class CoinSelector:
    """币种选择器"""

    def __init__(self, config=SELECTION_CONFIG):
        """初始化币种选择器"""
        self.config = config
        self.selected_coins = set()
        self.excluded_coins = set()
        self.last_update_time = None

    # ==================== 基础过滤 ====================
    def _check_daily_change_with_exceptions(
        self,
        symbol: str,
        daily_change: float,
        two_hour_change: float = None
    ) -> Tuple[bool, float, str]:
        """
        检查24h涨跌幅，包含例外规则

        Args:
            symbol: 币种符号
            daily_change: 24h涨跌幅（小数，如0.15=15%）
            two_hour_change: 2h涨跌幅（小数，可选）

        Returns:
            (是否通过, 仓位系数, 原因)
        """
        max_change = self.config['max_24h_change'] / 100.0  # 15% -> 0.15

        # 标准规则：绝对值≤15%
        if abs(daily_change) <= max_change:
            return True, 1.0, "24h涨跌幅在正常范围"

        # 例外1：深跌反弹（24h<-15% 但 2h>8%）
        if two_hour_change is not None:
            if daily_change < -max_change and two_hour_change > 0.08:
                # 允许交易，但仓位减半
                return True, 0.5, "深跌反弹：24h大跌但2h强劲反弹，仓位减半"

        # 例外2：极端拉升（24h>20% 且 2h>5%）
        if two_hour_change is not None:
            if daily_change > 0.20 and two_hour_change > 0.05:
                # 完全排除，避免追高
                return False, 0.0, "极端拉升：回调风险高，排除"

        # 其他超限情况一律排除
        return False, 0.0, f"24h涨跌幅({daily_change*100:.1f}%) 超出±{max_change*100:.0f}%"

    def _is_valid_coin(self, coin_info: CoinInfo) -> Tuple[bool, str]:
        """
        检查币种是否符合基础条件

        Args:
            coin_info: 币种信息

        Returns:
            (是否有效, 原因)
        """
        # 检查交易对类型
        if not coin_info.is_usdt_pair:
            return False, "不是USDT交易对"

        # 检查最小价格
        if coin_info.current_price < self.config['min_price']:
            return False, f"价格({coin_info.current_price}) < 最小价格({self.config['min_price']})"

        # 检查24小时交易量
        if coin_info.volume_24h < self.config['min_24h_volume']:
            return False, f"24h成交量({coin_info.volume_24h:.0f}) < 最小值({self.config['min_24h_volume']:.0f})"

        # 检查24小时涨跌幅（简化版，不带例外）
        # 例外规则需要2h数据，在外层单独处理
        daily_change = coin_info.change_24h / 100.0  # 转为小数
        max_change = self.config['max_24h_change'] / 100.0
        if abs(daily_change) > max_change:
            return False, f"24h涨跌幅({coin_info.change_24h:.2f}%) > {self.config['max_24h_change']}%"

        # 检查排除列表（杠杆代币等）
        for pattern in self.config['exclude_patterns']:
            if pattern in coin_info.symbol:
                return False, f"符合排除规则: {pattern}"

        return True, "符合条件"

    # ==================== 成交量排名选择 ====================
    def select_by_volume_rank(
        self,
        coins: List[CoinInfo]
    ) -> List[CoinInfo]:
        """
        按24小时成交量排名选择币种

        Args:
            coins: 币种列表

        Returns:
            选中的币种列表
        """
        selected = []
        excluded = []

        # 首先按基础条件过滤
        valid_coins = []
        for coin in coins:
            is_valid, reason = self._is_valid_coin(coin)
            if is_valid:
                valid_coins.append(coin)
            else:
                excluded.append((coin.symbol, reason))

        # 按24小时成交量排序
        valid_coins.sort(key=lambda x: x.volume_24h, reverse=True)

        # 取前N个
        top_n = self.config['top_n_by_volume']
        selected = valid_coins[:top_n]

        logger.info(f"成交量排名选择: 从{len(coins)}个币中筛选出{len(selected)}个")
        if excluded:
            logger.debug(f"排除的币种: {len(excluded)}")
            for symbol, reason in excluded[:5]:
                logger.debug(f"  {symbol}: {reason}")

        return selected

    # ==================== 活跃度检查 ====================
    def _check_activity(self, coin_info: CoinInfo) -> bool:
        """
        检查币种当前的活跃度（成交量是否放大）

        Args:
            coin_info: 币种信息

        Returns:
            是否活跃
        """
        if coin_info.volume_24h == 0:
            return False

        # 简化版本：检查当前成交量是否超过某个阈值
        # 使用24h均量近似（真实口径需要3m K线数据）
        volume_ratio = coin_info.current_volume / (coin_info.volume_24h / 24)

        threshold = self.config['volume_ratio_threshold']
        return volume_ratio > threshold

    def calculate_volume_ratio_from_klines(
        self,
        klines_3m: List[Dict],
        lookback: int = 20
    ) -> float:
        """
        从3m K线计算真实的volume ratio

        Args:
            klines_3m: 3分钟K线数据
            lookback: 回看周期（默认20根）

        Returns:
            volume ratio (当前成交量/近20根均量)
        """
        if not klines_3m or len(klines_3m) < lookback + 1:
            return 0.0

        # 当前3m成交量
        current_volume = float(klines_3m[-1]['volume'])

        # 近20根3m K线的均量（不包括当前）
        recent_volumes = [float(k['volume']) for k in klines_3m[-(lookback+1):-1]]
        avg_volume = sum(recent_volumes) / len(recent_volumes)

        if avg_volume == 0:
            return 0.0

        return current_volume / avg_volume

    # ==================== 综合选币 ====================
    def select_coins(
        self,
        all_coins: List[CoinInfo],
        max_coins: Optional[int] = None
    ) -> List[CoinInfo]:
        """
        综合选币

        Args:
            all_coins: 所有币种列表
            max_coins: 最多选多少个币种

        Returns:
            选中的币种列表
        """
        if max_coins is None:
            max_coins = self.config['top_n_by_volume']

        # 1. 按成交量排名选出前60个
        candidates = self.select_by_volume_rank(all_coins)

        # 2. 现在所有的币种都在候选列表中
        # 实际交易时，会根据信号逐个检查和入场
        # 这里返回候选列表
        self.selected_coins = {coin.symbol for coin in candidates}

        logger.info(f"币种选择完成: 共{len(candidates)}个候选币种")

        return candidates

    # ==================== 冷却管理相关 ====================
    def add_to_cooldown(self, symbol: str):
        """添加币种到冷却列表（简化，实际由CooldownManager管理）"""
        logger.info(f"{symbol} 已添加到冷却列表")

    def remove_from_cooldown(self, symbol: str):
        """从冷却列表移除币种"""
        logger.info(f"{symbol} 已从冷却列表移除")

    def is_in_cooldown(self, symbol: str) -> bool:
        """检查币种是否在冷却中（简化，实际由CooldownManager管理）"""
        return False

    # ==================== 统计和报告 ====================
    def get_selection_summary(self) -> Dict:
        """获取选币摘要"""
        return {
            'total_selected': len(self.selected_coins),
            'excluded_count': len(self.excluded_coins),
            'last_update': self.last_update_time,
            'selected_coins': list(self.selected_coins)
        }


# ==================== 币种过滤器 ====================
class CoinFilter:
    """币种过滤器 - 用于实时过滤不符合条件的币种"""

    @staticmethod
    def filter_by_price_range(
        coins: List[CoinInfo],
        min_price: float,
        max_price: float
    ) -> List[CoinInfo]:
        """按价格范围过滤"""
        return [c for c in coins if min_price <= c.current_price <= max_price]

    @staticmethod
    def filter_by_volume(
        coins: List[CoinInfo],
        min_volume: float
    ) -> List[CoinInfo]:
        """按成交量过滤"""
        return [c for c in coins if c.volume_24h >= min_volume]

    @staticmethod
    def filter_by_change_range(
        coins: List[CoinInfo],
        min_change: float,
        max_change: float
    ) -> List[CoinInfo]:
        """按涨跌幅过滤"""
        return [c for c in coins if min_change <= c.change_24h <= max_change]

    @staticmethod
    def filter_active_coins(
        coins: List[CoinInfo],
        volume_ratio_threshold: float = 1.2
    ) -> List[CoinInfo]:
        """过滤活跃币种（当前成交量相对较高）"""
        active_coins = []
        for coin in coins:
            if coin.volume_24h > 0:
                # 简化计算：当前体积 / 平均体积
                avg_hourly_volume = coin.volume_24h / 24
                ratio = coin.current_volume / avg_hourly_volume if avg_hourly_volume > 0 else 0
                if ratio > volume_ratio_threshold:
                    active_coins.append(coin)
        return active_coins


# ==================== 测试函数 ====================
if __name__ == "__main__":
    import random
    from datetime import datetime

    print("=" * 80)
    print("币种选择模块测试")
    print("=" * 80)

    # 生成测试数据
    def generate_test_coins(count: int = 100) -> List[CoinInfo]:
        """生成测试币种数据"""
        symbols = [
            f"BTC", f"ETH", f"BNB", f"XRP", f"ADA", f"SOL", f"DOGE", f"DOT",
            f"AVAX", f"MATIC", f"LINK", f"UNI", f"AAVE", f"ATOM", f"ICP",
            f"BCH", f"LTC", f"XLM", f"VET", f"TRX", f"EOS", f"NEO", f"XMR",
            f"DASH", f"ZEC", f"USDC", f"BUSD", f"USDT", f"DAI", f"TUSD",
        ]

        coins = []
        for i in range(count):
            if i < len(symbols):
                symbol = symbols[i] + "USDT"
            else:
                symbol = f"COIN{i}USDT"

            coins.append(CoinInfo(
                symbol=symbol,
                current_price=random.uniform(0.001, 100000),
                change_24h=random.uniform(-15, 15),
                volume_24h=random.uniform(5000000, 100000000),
                current_volume=random.uniform(10000, 500000),
                is_usdt_pair=True
            ))

        return coins

    selector = CoinSelector()
    filter = CoinFilter()

    # 测试1: 基础过滤
    print("\n[测试1] 基础过滤")
    print("-" * 80)
    test_coin_valid = CoinInfo(
        symbol="BTCUSDT",
        current_price=45000,
        change_24h=5.0,
        volume_24h=10000000,
        current_volume=100000,
        is_usdt_pair=True
    )
    is_valid, reason = selector._is_valid_coin(test_coin_valid)
    print(f"BTCUSDT 有效: {is_valid} ({reason})")

    test_coin_invalid = CoinInfo(
        symbol="BTCUSDT",
        current_price=45000,
        change_24h=20.0,  # 超过15%
        volume_24h=10000000,
        current_volume=100000,
        is_usdt_pair=True
    )
    is_valid, reason = selector._is_valid_coin(test_coin_invalid)
    print(f"BTCUSDT (20%涨幅) 有效: {is_valid} ({reason})")

    # 测试2: 成交量排名选择
    print("\n[测试2] 成交量排名选择")
    print("-" * 80)
    all_coins = generate_test_coins(100)
    selected = selector.select_by_volume_rank(all_coins)
    print(f"从{len(all_coins)}个币种中选出{len(selected)}个")
    print("前10个选中的币种:")
    for i, coin in enumerate(selected[:10], 1):
        print(f"  {i}. {coin.symbol:15s} - 成交量: ${coin.volume_24h/1e6:.2f}M")

    # 测试3: 综合选币
    print("\n[测试3] 综合选币")
    print("-" * 80)
    result = selector.select_coins(all_coins, max_coins=30)
    summary = selector.get_selection_summary()
    print(f"选中币种数: {summary['total_selected']}")
    print(f"排除币种数: {summary['excluded_count']}")

    # 测试4: 过滤器
    print("\n[测试4] 币种过滤器")
    print("-" * 80)
    price_filtered = filter.filter_by_price_range(all_coins, 1000, 50000)
    print(f"价格在1000-50000之间: {len(price_filtered)}个")

    volume_filtered = filter.filter_by_volume(all_coins, 5000000)
    print(f"成交量>500万: {len(volume_filtered)}个")

    change_filtered = filter.filter_by_change_range(all_coins, -10, 10)
    print(f"涨跌幅在-10~10之间: {len(change_filtered)}个")

    active_filtered = filter.filter_active_coins(all_coins, 1.2)
    print(f"当前活跃币种(成交量1.2倍以上): {len(active_filtered)}个")

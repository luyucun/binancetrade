"""
🚀 WebSocket集成方案 (websocket_integration_plan.py)

这个文件展示了如何将WebSocket市场数据管理器集成到现有的交易引擎中。

实施步骤：
1. 渐进式集成（不破坏现有功能）
2. 性能对比测试
3. 完全切换到WebSocket
"""

import asyncio
import logging
from typing import Dict, List, Optional
from datetime import datetime

from market_data_manager import MarketDataManager
from trading_engine_v2 import TradingEngine

logger = logging.getLogger(__name__)


class WebSocketTradingEngine(TradingEngine):
    """
    🚀 增强版交易引擎 - 集成WebSocket实时数据

    在原有TradingEngine基础上增加WebSocket支持：
    - 保留原有HTTP API作为备份
    - 优先使用WebSocket实时数据
    - 自动降级到HTTP轮询
    """

    def __init__(self, config=None, enable_websocket: bool = True):
        """
        初始化WebSocket增强版交易引擎

        Args:
            config: 引擎配置
            enable_websocket: 是否启用WebSocket（可用于A/B测试）
        """
        super().__init__(config)

        self.enable_websocket = enable_websocket
        self.market_data_manager: Optional[MarketDataManager] = None
        self._ws_enabled = False
        self._performance_stats = {
            'ws_requests': 0,
            'http_requests': 0,
            'ws_failures': 0,
            'avg_ws_response_time': 0.0,
            'avg_http_response_time': 0.0
        }

        if enable_websocket:
            logger.info("初始化WebSocket市场数据管理器...")
            self.market_data_manager = MarketDataManager(
                testnet=self.binance_client.testnet if self.binance_client else False
            )

    # ==================== WebSocket生命周期管理 ====================
    async def start_websocket(self, initial_symbols: List[str] = None):
        """
        启动WebSocket连接

        Args:
            initial_symbols: 初始订阅的币种列表
        """
        if not self.enable_websocket or not self.market_data_manager:
            logger.info("WebSocket未启用，跳过连接")
            return

        try:
            # 获取初始币种列表
            if not initial_symbols:
                initial_symbols = await self._get_initial_symbols()

            await self.market_data_manager.start(initial_symbols)
            self._ws_enabled = True

            logger.info(f"✓ WebSocket已启动，订阅 {len(initial_symbols)} 个币种")

            # 设置数据回调
            self.market_data_manager.add_price_callback(self._on_price_update)
            self.market_data_manager.add_kline_callback(self._on_kline_update)

        except Exception as e:
            logger.error(f"WebSocket启动失败: {e}")
            self._ws_enabled = False

    async def stop_websocket(self):
        """停止WebSocket连接"""
        if self.market_data_manager:
            await self.market_data_manager.stop()
            self._ws_enabled = False
            logger.info("WebSocket已停止")

    async def _get_initial_symbols(self) -> List[str]:
        """获取初始订阅币种列表"""
        try:
            # 获取当前热门币种
            coins = self._fetch_candidate_coins()
            symbols = [coin.symbol for coin in coins[:30]]  # 前30个币种
            symbols.append('BTCUSDT')  # 确保包含BTC
            return list(set(symbols))
        except Exception as e:
            logger.warning(f"获取初始币种列表失败: {e}")
            return ['BTCUSDT', 'ETHUSDT']  # 默认币种

    # ==================== 数据回调处理 ====================
    async def _on_price_update(self, data):
        """价格更新回调"""
        # 可以在这里实现实时价格预警、止损触发等逻辑
        pass

    async def _on_kline_update(self, data):
        """K线更新回调"""
        # 可以在这里实现实时信号检测逻辑
        pass

    # ==================== 优化的数据获取方法 ====================
    def _get_current_price_optimized(self, symbol: str) -> Optional[float]:
        """
        🚀 优化版价格获取 - WebSocket优先，HTTP降级

        Args:
            symbol: 币种符号

        Returns:
            当前价格
        """
        start_time = datetime.now()

        try:
            # 优先使用WebSocket数据
            if self._ws_enabled and self.market_data_manager:
                price = self.market_data_manager.get_current_price(symbol)
                if price:
                    response_time = (datetime.now() - start_time).total_seconds()
                    self._update_performance_stats('ws', response_time, success=True)
                    logger.debug(f"{symbol}: WebSocket价格 {price:.4f} (耗时 {response_time*1000:.1f}ms)")
                    return price

                # WebSocket数据不可用，记录失败
                self._update_performance_stats('ws', 0, success=False)

        except Exception as e:
            logger.debug(f"{symbol}: WebSocket价格获取失败: {e}")
            self._update_performance_stats('ws', 0, success=False)

        # 降级到HTTP API
        try:
            price = self._get_current_price(symbol)  # 调用原有方法
            response_time = (datetime.now() - start_time).total_seconds()
            self._update_performance_stats('http', response_time, success=True)
            logger.debug(f"{symbol}: HTTP价格 {price:.4f} (耗时 {response_time*1000:.1f}ms)")
            return price

        except Exception as e:
            logger.warning(f"{symbol}: HTTP价格获取也失败: {e}")
            return None

    def _fetch_klines_optimized(self, symbol: str, interval: str, limit: int) -> List[Dict]:
        """
        🚀 优化版K线获取 - WebSocket优先，HTTP降级

        Args:
            symbol: 币种符号
            interval: 时间周期
            limit: 获取数量

        Returns:
            K线数据列表
        """
        start_time = datetime.now()

        try:
            # 优先使用WebSocket数据
            if self._ws_enabled and self.market_data_manager:
                klines = self.market_data_manager.get_klines(symbol, interval, limit)
                if klines and len(klines) >= min(10, limit // 2):  # 确保有足够的数据
                    response_time = (datetime.now() - start_time).total_seconds()
                    self._update_performance_stats('ws', response_time, success=True)
                    logger.debug(f"{symbol}: WebSocket K线 {len(klines)}根 (耗时 {response_time*1000:.1f}ms)")
                    return klines

        except Exception as e:
            logger.debug(f"{symbol}: WebSocket K线获取失败: {e}")

        # 降级到HTTP API
        try:
            klines = self._fetch_klines(symbol, interval, limit)  # 调用原有方法
            response_time = (datetime.now() - start_time).total_seconds()
            self._update_performance_stats('http', response_time, success=True)
            logger.debug(f"{symbol}: HTTP K线 {len(klines)}根 (耗时 {response_time*1000:.1f}ms)")
            return klines

        except Exception as e:
            logger.warning(f"{symbol}: HTTP K线获取也失败: {e}")
            return []

    def get_all_prices_optimized(self) -> Dict[str, float]:
        """
        🚀 批量价格获取 - WebSocket版本

        Returns:
            {symbol: price} 字典
        """
        start_time = datetime.now()

        try:
            # 优先使用WebSocket数据
            if self._ws_enabled and self.market_data_manager:
                prices = self.market_data_manager.get_all_prices()
                if prices:
                    response_time = (datetime.now() - start_time).total_seconds()
                    self._update_performance_stats('ws', response_time, success=True)
                    logger.debug(f"WebSocket批量价格 {len(prices)}个 (耗时 {response_time*1000:.1f}ms)")
                    return prices

        except Exception as e:
            logger.debug(f"WebSocket批量价格获取失败: {e}")

        # 降级到HTTP API
        try:
            if self.binance_client:
                prices = self.binance_client.get_all_symbol_ticker_price()
                response_time = (datetime.now() - start_time).total_seconds()
                self._update_performance_stats('http', response_time, success=True)
                logger.debug(f"HTTP批量价格 {len(prices)}个 (耗时 {response_time*1000:.1f}ms)")
                return prices

        except Exception as e:
            logger.warning(f"HTTP批量价格获取也失败: {e}")

        return {}

    # ==================== 性能统计 ====================
    def _update_performance_stats(self, method: str, response_time: float, success: bool = True):
        """更新性能统计"""
        if method == 'ws':
            self._performance_stats['ws_requests'] += 1
            if not success:
                self._performance_stats['ws_failures'] += 1
            else:
                # 计算移动平均响应时间
                current_avg = self._performance_stats['avg_ws_response_time']
                total_requests = self._performance_stats['ws_requests']
                self._performance_stats['avg_ws_response_time'] = (current_avg * (total_requests - 1) + response_time) / total_requests

        elif method == 'http':
            self._performance_stats['http_requests'] += 1
            current_avg = self._performance_stats['avg_http_response_time']
            total_requests = self._performance_stats['http_requests']
            self._performance_stats['avg_http_response_time'] = (current_avg * (total_requests - 1) + response_time) / total_requests

    def get_performance_stats(self) -> Dict:
        """获取性能统计报告"""
        stats = self._performance_stats.copy()

        # 计算失败率
        if stats['ws_requests'] > 0:
            stats['ws_failure_rate'] = stats['ws_failures'] / stats['ws_requests']
        else:
            stats['ws_failure_rate'] = 0.0

        # 计算性能提升
        if stats['avg_http_response_time'] > 0:
            stats['performance_improvement'] = (
                stats['avg_http_response_time'] - stats['avg_ws_response_time']
            ) / stats['avg_http_response_time']
        else:
            stats['performance_improvement'] = 0.0

        # WebSocket连接状态
        if self.market_data_manager:
            stats['websocket_status'] = self.market_data_manager.get_connection_status()
            stats['data_stats'] = self.market_data_manager.get_data_stats()

        return stats

    # ==================== 重写的主要方法 ====================
    async def _scan_signals_websocket_enhanced(self):
        """
        🚀 WebSocket增强版信号扫描

        使用WebSocket实时数据，大幅提升扫描速度
        """
        logger.debug("开始WebSocket增强版信号扫描...")

        try:
            # 0. 检查限流和日亏停开条件
            if not self._can_open_new_entry():
                return

            # 1. 获取币种列表（可使用WebSocket实时数据辅助筛选）
            all_coins = self._fetch_candidate_coins()
            if not all_coins:
                logger.warning("无法获取币种列表")
                return

            # 动态添加新币种到WebSocket订阅
            current_symbols = {coin.symbol for coin in all_coins}
            if self.market_data_manager:
                for symbol in current_symbols:
                    self.market_data_manager.subscribe_symbol(symbol)

            logger.debug(f"获取到 {len(all_coins)} 个候选币种")

            # 2. 筛选币种
            selected_coins = self.coin_selector.select_coins(all_coins)
            logger.debug(f"筛选后 {len(selected_coins)} 个币种")

            # 3. 获取BTC和市场数据用于过滤
            btc_indicators_1m, btc_indicators_15m, btc_1m_klines = self._fetch_btc_indicators()
            market_data = self._fetch_market_data()

            # 4. 应用市场过滤
            filter_result = self.market_filter.apply_market_filters(
                btc_indicators_1m=btc_indicators_1m,
                btc_indicators_15m=btc_indicators_15m,
                btc_1m_klines=btc_1m_klines,
                target_direction="LONG",
                current_volume=market_data.get('current_volume', 0),
                avg_volume_24h=market_data.get('avg_volume_24h', 1),
                current_volatility=market_data.get('current_volatility', 0),
                avg_volatility_24h=market_data.get('avg_volatility_24h', 1),
                fear_greed_index=market_data.get('fear_greed_index', 50)
            )

            if not filter_result.can_trade:
                logger.warning(f"市场过滤不通过: {filter_result.warnings}")
                return

            logger.info(f"市场状态: {filter_result.health.value} | BTC: {filter_result.btc_status}")

            # 5. 🚀 WebSocket增强版并发信号处理
            tasks = []
            valid_coins = []

            for coin in selected_coins:
                if not self.risk_manager.can_open_new_position(coin.symbol):
                    logger.debug(f"{coin.symbol}: 已有头寸或在冷却中，跳过")
                    continue

                valid_coins.append(coin)
                # 使用WebSocket优化版的处理方法
                tasks.append(self._process_single_coin_websocket(coin))

            logger.info(f"开始WebSocket增强版并发处理 {len(valid_coins)} 个币种...")

            # 并发处理（WebSocket版本应该更快）
            start_time = datetime.now()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            processing_time = (datetime.now() - start_time).total_seconds()

            # 处理结果
            signals_generated = 0
            signals_executed = 0

            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.warning(f"{valid_coins[i].symbol}: 处理时出错: {result}")
                    continue

                if result is None:
                    continue

                signal, position_scaling = result
                if signal:
                    signals_generated += 1
                    logger.info(f"生成信号: {signal.symbol} {signal.direction.value} 评分={signal.score.total_score}")

                    if await self._execute_entry(signal, position_scaling=position_scaling):
                        signals_executed += 1

            self.stats['total_signals_generated'] += signals_generated
            self.stats['signals_executed'] += signals_executed

            logger.info(
                f"WebSocket信号扫描完成: 生成{signals_generated}个信号, 执行{signals_executed}个, "
                f"并发处理耗时 {processing_time:.3f}s"
            )
            self.last_signal_scan = datetime.now()

        except Exception as e:
            logger.error(f"WebSocket信号扫描出错: {e}", exc_info=True)

    async def _process_single_coin_websocket(self, coin):
        """
        🚀 WebSocket版单币种处理（更快的数据获取）

        Args:
            coin: 币种信息

        Returns:
            Tuple[TradingSignal, float] 或 None
        """
        try:
            start_time = datetime.now()

            # 🔥 使用WebSocket优化的K线获取
            klines_3m_task = asyncio.create_task(asyncio.to_thread(
                self._fetch_klines_optimized, coin.symbol, '3m', 50
            ))
            klines_5m_task = asyncio.create_task(asyncio.to_thread(
                self._fetch_klines_optimized, coin.symbol, '5m', 50
            ))
            klines_15m_task = asyncio.create_task(asyncio.to_thread(
                self._fetch_klines_optimized, coin.symbol, '15m', 50
            ))

            # 并发获取所有K线数据
            klines_3m, klines_5m, klines_15m = await asyncio.gather(
                klines_3m_task, klines_5m_task, klines_15m_task
            )

            fetch_time = (datetime.now() - start_time).total_seconds()
            logger.debug(f"{coin.symbol}: WebSocket K线获取完成，耗时 {fetch_time:.3f}s")

            if not all([klines_3m, klines_5m, klines_15m]):
                logger.debug(f"{coin.symbol}: K线数据不足，跳过")
                return None

            # 后续处理逻辑与原版相同...
            two_hour_change = self._calculate_two_hour_change(klines_3m)

            can_trade, position_scaling, reason = self.coin_selector._check_daily_change_with_exceptions(
                coin.symbol, coin.change_24h / 100.0, two_hour_change
            )

            if not can_trade:
                logger.debug(f"{coin.symbol}: {reason}")
                return None

            volume_ratio_3m = self.coin_selector.calculate_volume_ratio_from_klines(
                klines_3m, lookback=20
            )

            signal = self.signal_generator.generate_signal(
                symbol=coin.symbol,
                klines_3m=klines_3m,
                klines_5m=klines_5m,
                klines_15m=klines_15m,
                current_price=coin.current_price,
                position_size_usdt=100.0,
                volume_ratio_3m=volume_ratio_3m
            )

            if signal:
                return (signal, position_scaling)

            return None

        except Exception as e:
            logger.error(f"{coin.symbol}: WebSocket处理时出错: {e}", exc_info=True)
            return None

    # ==================== 新的启动流程 ====================
    async def start_enhanced(self):
        """增强版启动流程 - 包含WebSocket初始化"""
        # 调用原有启动逻辑
        self.start()

        # 启动WebSocket（如果启用）
        if self.enable_websocket:
            await self.start_websocket()

        logger.info("WebSocket增强版交易引擎启动完成")

    async def stop_enhanced(self):
        """增强版停止流程 - 包含WebSocket清理"""
        # 停止WebSocket
        if self.enable_websocket:
            await self.stop_websocket()

        # 调用原有停止逻辑
        self.stop()

        # 输出性能统计
        stats = self.get_performance_stats()
        logger.info("=" * 60)
        logger.info("WebSocket性能统计报告:")
        logger.info(f"  WebSocket请求: {stats.get('ws_requests', 0)}")
        logger.info(f"  HTTP请求: {stats.get('http_requests', 0)}")
        logger.info(f"  WebSocket失败率: {stats.get('ws_failure_rate', 0):.2%}")
        logger.info(f"  平均响应时间 - WebSocket: {stats.get('avg_ws_response_time', 0)*1000:.1f}ms")
        logger.info(f"  平均响应时间 - HTTP: {stats.get('avg_http_response_time', 0)*1000:.1f}ms")
        logger.info(f"  性能提升: {stats.get('performance_improvement', 0):.2%}")
        logger.info("=" * 60)


# ==================== 使用示例 ====================
async def main_websocket():
    """WebSocket增强版交易引擎启动示例"""
    from config_v2 import EngineConfig

    # 创建WebSocket增强版引擎
    engine = WebSocketTradingEngine(
        config=EngineConfig(
            debug_mode=True,
            paper_trading=True,
            log_level="INFO"
        ),
        enable_websocket=True  # 启用WebSocket
    )

    try:
        # 启动增强版引擎
        await engine.start_enhanced()

        # 运行主循环（使用WebSocket增强版扫描）
        while engine.state.value == "RUNNING":
            await engine._scan_signals_websocket_enhanced()
            await engine._monitor_positions()
            await asyncio.sleep(10)

    except KeyboardInterrupt:
        logger.info("收到中断信号...")
    finally:
        await engine.stop_enhanced()


if __name__ == "__main__":
    asyncio.run(main_websocket())
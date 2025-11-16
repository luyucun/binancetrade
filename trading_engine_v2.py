"""
主交易引擎 (trading_engine_v2.py)
系统的核心，协调所有模块完成完整的交易流程
"""

import logging
import json
import asyncio
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from enum import Enum

from config_v2 import (
    TIMEFRAME_CONFIG, SELECTION_CONFIG, SYSTEM_CONFIG,
    EXECUTION_SYSTEM, DATA_CONFIG, API_CONFIG, RISK_MANAGEMENT,
    ROTATION_SYSTEM
)
from coin_selector import CoinSelector, CoinInfo
from indicators import IndicatorCalculator
from trend_analyzer import TrendAnalyzer
from market_filter import MarketFilter
from signal_generator import SignalGenerator, TradingSignal
from risk_manager_v2 import RiskManager
from position_monitor_v2 import PositionMonitor, MonitoringEvent
from binance_client_v2 import BinanceClientV2


logger = logging.getLogger(__name__)


class EngineState(Enum):
    """引擎状态"""
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"


@dataclass
class EngineConfig:
    """引擎配置"""
    debug_mode: bool = False
    paper_trading: bool = True  # 模拟交易
    log_level: str = "INFO"
    max_retries: int = 3


class TradingEngine:
    """主交易引擎"""

    def __init__(self, config: Optional[EngineConfig] = None):
        """
        初始化交易引擎

        Args:
            config: 引擎配置
        """
        self.config = config or EngineConfig()
        self._setup_logging()

        # 初始化各个模块
        self.coin_selector = CoinSelector()
        self.indicator_calc = IndicatorCalculator()
        self.trend_analyzer = TrendAnalyzer()
        self.market_filter = MarketFilter()
        self.signal_generator = SignalGenerator()
        self.risk_manager = RiskManager()
        self.position_monitor = PositionMonitor(self.risk_manager)

        # 初始化Binance客户端
        try:
            self.binance_client = BinanceClientV2(
                api_key=API_CONFIG['binance_key'],
                api_secret=API_CONFIG['binance_secret'],
                testnet=API_CONFIG.get('testnet', False)
            )
            logger.info("Binance客户端已初始化")
        except Exception as e:
            logger.error(f"Binance客户端初始化失败: {e}")
            self.binance_client = None

        # 状态管理
        self.state = EngineState.IDLE
        self.start_time = None
        self.last_signal_scan = None
        self.last_position_check = None

        # 统计数据
        self.stats = {
            'total_signals_generated': 0,
            'signals_executed': 0,
            'positions_closed': 0,
            'total_profit_loss': 0.0,
            'win_rate': 0.0,
        }

        logger.info("交易引擎初始化完成")

    def _setup_logging(self):
        """设置日志"""
        logging.basicConfig(
            level=getattr(logging, self.config.log_level),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

    # ==================== 引擎生命周期 ====================
    def start(self):
        """启动引擎"""
        if self.state == EngineState.RUNNING:
            logger.warning("引擎已在运行中")
            return

        self.state = EngineState.RUNNING
        self.start_time = datetime.now()
        logger.info("=" * 80)
        logger.info("交易引擎启动")
        logger.info(f"模式: {'模拟交易' if self.config.paper_trading else '实盘交易'}")
        logger.info(f"调试模式: {self.config.debug_mode}")
        logger.info("=" * 80)

        # 设置Binance账户参数
        if self.binance_client and not self.config.paper_trading:
            logger.info("正在配置Binance账户参数...")

            # 设置双向持仓模式(Hedge模式)
            try:
                if self.binance_client.set_position_mode(dual_side_position=True):
                    logger.info("✓ 双向持仓模式(Hedge)已设置")
                else:
                    logger.warning("⚠ 双向持仓模式设置失败，可能影响交易")
            except Exception as e:
                logger.error(f"设置双向持仓模式失败: {e}")

        logger.info("引擎启动完成")


    def pause(self):
        """暂停引擎"""
        self.state = EngineState.PAUSED
        logger.info("交易引擎已暂停")

    def resume(self):
        """继续运行"""
        if self.state == EngineState.PAUSED:
            self.state = EngineState.RUNNING
            logger.info("交易引擎恢复运行")

    def stop(self):
        """停止引擎"""
        self.state = EngineState.STOPPED
        logger.info("=" * 80)
        logger.info("交易引擎停止")
        logger.info(self._get_session_summary())
        logger.info("=" * 80)

    # ==================== 主交易循环 ====================
    async def main_loop(self, interval_seconds: int = 10):
        """
        主交易循环

        Args:
            interval_seconds: 循环间隔(秒)
        """
        if self.state != EngineState.RUNNING:
            logger.warning("引擎未在运行状态")
            return

        try:
            while self.state == EngineState.RUNNING:
                logger.debug(f"[{datetime.now().strftime('%H:%M:%S')}] 执行主循环")

                # 步骤1: 扫描信号
                await self._scan_signals()

                # 步骤2: 监控持仓
                await self._monitor_positions()

                # 步骤3: 输出统计
                self._log_statistics()

                # 等待下一个循环
                await asyncio.sleep(interval_seconds)

        except KeyboardInterrupt:
            logger.info("收到中断信号，正在关闭...")
            self.stop()
        except Exception as e:
            logger.error(f"主循环出错: {e}", exc_info=True)
            self.stop()

    # ==================== 信号扫描 ====================
    async def _scan_signals(self):
        """
        扫描交易信号

        流程:
        1. 获取币种列表
        2. 过滤市场条件
        3. 对每个币种检查信号
        4. 生成信号并执行入场
        """
        logger.debug("开始扫描交易信号...")

        try:
            # 1. 获取币种列表
            # 注: 实际应该从Binance API获取
            all_coins = self._fetch_candidate_coins()
            if not all_coins:
                logger.warning("无法获取币种列表")
                return

            logger.debug(f"获取{len(all_coins)}个候选币种")

            # 2. 筛选币种
            selected_coins = self.coin_selector.select_coins(all_coins)
            logger.debug(f"筛选出{len(selected_coins)}个候选币种进行监控")

            # 3. 获取BTC和市场数据用于过滤
            btc_indicators_1m, btc_indicators_15m, btc_1m_klines = self._fetch_btc_indicators()
            market_data = self._fetch_market_data()

            # 4. 应用市场过滤(传入btc_1m_klines用于计算1m波动率)
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

            logger.info(f"市场状态: {filter_result.health.value}")

            # 5. 对每个币种检查信号
            signals_generated = 0
            signals_executed = 0

            for coin in selected_coins:
                # 检查是否已有头寸或在冷却中
                if not self.risk_manager.can_open_new_position(coin.symbol):
                    logger.debug(f"{coin.symbol}: 已有头寸或在冷却中，跳过")
                    continue

                # 获取该币种的K线数据
                # 注意: indicators需要至少50根K线才能计算EMA50
                klines_3m = self._fetch_klines(coin.symbol, '3m', 50)
                klines_5m = self._fetch_klines(coin.symbol, '5m', 50)
                klines_15m = self._fetch_klines(coin.symbol, '15m', 50)

                if not all([klines_3m, klines_5m, klines_15m]):
                    logger.debug(f"{coin.symbol}: K线数据不足，跳过")
                    continue

                # 计算2h涨跌幅用于24h涨跌幅例外规则检查 (使用3m K线)
                two_hour_change = self._calculate_two_hour_change(klines_3m)

                # 应用24h涨跌幅例外规则
                can_trade, position_scaling, reason = self.coin_selector._check_daily_change_with_exceptions(
                    coin.symbol,
                    coin.change_24h / 100.0,  # 转换为小数
                    two_hour_change
                )

                if not can_trade:
                    logger.debug(f"{coin.symbol}: {reason}, 跳过")
                    continue

                if position_scaling < 1.0:
                    logger.info(f"{coin.symbol}: {reason}, 仓位缩放至 {position_scaling*100:.0f}%")

                # 计算3m真实量比 (当前/近20根均量)
                volume_ratio_3m = self.coin_selector.calculate_volume_ratio_from_klines(
                    klines_3m, lookback=20
                )

                # 生成信号
                signal = self.signal_generator.generate_signal(
                    symbol=coin.symbol,
                    klines_3m=klines_3m,
                    klines_5m=klines_5m,
                    klines_15m=klines_15m,
                    current_price=coin.current_price,
                    position_size_usdt=100.0,  # 基础仓位
                    volume_ratio_3m=volume_ratio_3m  # 传入真实的3m量比
                )

                if signal:
                    signals_generated += 1
                    logger.info(f"✓ {coin.symbol}: 生成信号 (评分: {signal.score.total_score}, 信心度: {signal.confidence:.0%})")

                    # 执行入场(传递position_scaling作为correlation_penalty)
                    if await self._execute_entry(signal, position_scaling=position_scaling):
                        signals_executed += 1

            self.stats['total_signals_generated'] += signals_generated
            self.stats['signals_executed'] += signals_executed

            logger.info(f"信号扫描完成: 生成{signals_generated}个信号，执行{signals_executed}个入场")
            self.last_signal_scan = datetime.now()

        except Exception as e:
            logger.error(f"信号扫描出错: {e}", exc_info=True)

    # ==================== 持仓监控 ====================
    async def _monitor_positions(self):
        """
        监控所有活跃持仓

        流程:
        1. 获取所有持仓的当前价格
        2. 计算ATR并检查止损/止盈
        3. 执行平仓操作
        4. 记录监控事件
        """
        logger.debug("开始监控持仓...")

        try:
            if not self.risk_manager.active_positions:
                logger.debug("无活跃持仓")
                return

            # 获取当前价格和ATR - 改进: 增强容错能力
            current_prices = {}
            atr_values = {}
            failed_symbols = []

            for symbol in list(self.risk_manager.active_positions.keys()):
                price = self._get_current_price(symbol)
                atr = self._get_atr(symbol)

                if price and atr:
                    current_prices[symbol] = price
                    atr_values[symbol] = atr
                else:
                    if not price:
                        logger.warning(f"{symbol}: 无法获取价格，跳过本次监控")
                    if not atr:
                        logger.warning(f"{symbol}: 无法获取ATR，跳过本次监控")
                    failed_symbols.append(symbol)

            if not current_prices:
                logger.warning(f"无法获取任何币种的价格数据，有{len(failed_symbols)}个币种失败")
                # 改进: 即使无法获取数据也不直接返回，在下次循环重试
                return

            # 记录可以监控的和无法监控的
            logger.debug(f"本次监控{len(current_prices)}个持仓，{len(failed_symbols)}个持仓失败")

            # 监控所有持仓
            symbols_to_close, events = self.position_monitor.monitor_all_positions(
                current_prices, atr_values
            )

            # 处理需要平仓的头寸
            for symbol in symbols_to_close:
                await self._execute_exit(symbol, current_prices.get(symbol, 0))
                self.stats['positions_closed'] += 1

            # 处理分阶段止盈 - 执行部分平仓
            for symbol in list(self.risk_manager.active_positions.keys()):
                position = self.risk_manager.active_positions[symbol]

                # 检查是否有未执行的部分平仓
                for partial_exit in position.partial_exits:
                    if not partial_exit.get('executed', False) and partial_exit['quantity'] > 0:
                        # 执行部分平仓订单
                        success = await self._execute_partial_exit(
                            symbol,
                            partial_exit['quantity'],
                            partial_exit['price'],
                            partial_exit['stage']
                        )

                        if success:
                            # 标记为已执行
                            partial_exit['executed'] = True
                            # 减少剩余数量
                            position.remaining_quantity -= partial_exit['quantity']
                            position.remaining_quantity = max(0, position.remaining_quantity)

                            logger.info(f"✓ {symbol}: Stage {partial_exit['stage']} 部分平仓成功 ({partial_exit['quantity']:.6f}), 剩余 {position.remaining_quantity:.6f}")

                            # 如果剩余数量≈0，立即触发全部平仓
                            if position.remaining_quantity < 0.001:
                                if symbol not in symbols_to_close:
                                    symbols_to_close.append(symbol)
                                    logger.info(f"{symbol}: 剩余数量已≈0, 立即触发全部平仓")
                        else:
                            logger.warning(f"✗ {symbol}: Stage {partial_exit['stage']} 部分平仓失败")

            # 再次处理需要平仓的头寸（包括剩余数量≈0的）
            for symbol in symbols_to_close:
                if symbol not in current_prices:
                    logger.warning(f"{symbol}: 无当前价格数据，跳过平仓")
                    continue
                await self._execute_exit(symbol, current_prices.get(symbol, 0))
                self.stats['positions_closed'] += 1

            # 记录事件
            for event in events:
                logger.info(f"{event.symbol}: {event.event_type} - P&L: {event.profit_loss_usdt:+.2f} USDT ({event.profit_loss_pct:+.2%})")
                self.stats['total_profit_loss'] += event.profit_loss_usdt

            self.last_position_check = datetime.now()

        except Exception as e:
            logger.error(f"持仓监控出错: {e}", exc_info=True)

    # ==================== 入场执行 ====================
    async def _execute_entry(self, signal: TradingSignal, position_scaling: float = 1.0) -> bool:
        """
        执行入场

        Args:
            signal: 交易信号
            position_scaling: 仓位缩放系数(用于24h涨跌幅例外规则等)

        Returns:
            是否成功执行
        """
        try:
            logger.info(f"执行入场: {signal.symbol} {signal.direction.value} @ {signal.entry_price:.4f}")

            # 计算仓位大小(将position_scaling作为correlation_penalty传入)
            position_size = self.risk_manager.calculate_position_size(
                entry_price=signal.entry_price,
                stop_loss_price=signal.stop_loss_price,
                signal_score=signal.score.total_score,
                confidence=signal.confidence,
                correlation_penalty=position_scaling  # 使用position_scaling作为correlation_penalty
            )

            # 创建风险参数
            risk_params = self.risk_manager.create_risk_parameters(
                entry_price=signal.entry_price,
                atr=signal.indicators_3m.atr,
                direction="BUY" if signal.direction.value == "BULLISH" else "SELL",
                position_size_usdt=position_size
            )

            # 计算交易数量
            quantity = position_size / signal.entry_price

            # 检查模拟交易模式
            if self.config.paper_trading:
                logger.info(f"[模拟交易] 执行入场订单: {signal.symbol} x {quantity:.6f} @ {signal.entry_price:.4f}")
            else:
                # 实盘交易
                if not self.binance_client:
                    logger.error(f"Binance客户端未初始化，无法执行实盘交易")
                    return False

                side = 'BUY' if signal.direction.value == 'BULLISH' else 'SELL'
                position_side = 'LONG' if signal.direction.value == 'BULLISH' else 'SHORT'

                logger.warning(f"[实盘交易] 执行入场订单: {signal.symbol} {side} x {quantity:.6f} (positionSide: {position_side})")

                # 设置全仓保证金模式
                try:
                    if self.binance_client.set_margin_type(signal.symbol, 'CROSSED'):
                        logger.debug(f"✓ {signal.symbol}: 全仓保证金模式已设置")
                except Exception as e:
                    logger.warning(f"设置全仓保证金失败: {e} (可能已是目标模式)")

                # 设置杠杆
                try:
                    leverage = RISK_MANAGEMENT['position_sizing']['leverage']
                    self.binance_client.set_leverage(
                        signal.symbol,
                        leverage
                    )
                except Exception as e:
                    logger.warning(f"设置杠杆失败: {e}")

                # 下达市价单 (Hedge模式需指定positionSide)
                order = self.binance_client.place_market_order(
                    symbol=signal.symbol,
                    side=side,
                    quantity=quantity,
                    position_side=position_side
                )

                if not order:
                    logger.error(f"入场订单失败: {signal.symbol}")
                    return False

                logger.info(f"✓ 入场成功: {signal.symbol} 订单ID: {order['order_id']}")

            # 添加到活跃持仓
            position = self.risk_manager.add_position(
                symbol=signal.symbol,
                side="BUY" if signal.direction.value == "BULLISH" else "SELL",
                entry_price=signal.entry_price,
                quantity=quantity,
                risk_params=risk_params
            )

            logger.info(f"✓ 入场成功: {signal.symbol} 仓位大小: {position_size:.2f} USDT")
            return True

        except Exception as e:
            logger.error(f"入场失败: {signal.symbol} - {e}", exc_info=True)
            return False

    # ==================== 部分平仓执行 ====================
    async def _execute_partial_exit(
        self,
        symbol: str,
        quantity: float,
        exit_price: float,
        stage: int
    ) -> bool:
        """
        执行部分平仓

        Args:
            symbol: 币种
            quantity: 平仓数量
            exit_price: 平仓价格
            stage: Stage编号

        Returns:
            是否成功
        """
        try:
            if symbol not in self.risk_manager.active_positions:
                logger.warning(f"{symbol}: 未找到活跃持仓")
                return False

            position = self.risk_manager.active_positions[symbol]

            logger.info(f"执行部分平仓: {symbol} Stage {stage} x {quantity:.6f} @ {exit_price:.4f}")

            if self.config.paper_trading:
                logger.info(f"[模拟交易] 执行Stage {stage}部分平仓")
                return True  # 模拟交易直接返回成功
            else:
                # 实盘交易
                if not self.binance_client:
                    logger.error(f"Binance客户端未初始化，无法执行实盘交易")
                    return False

                side = 'SELL' if position.side == 'BUY' else 'BUY'
                position_side = 'LONG' if position.side == 'BUY' else 'SHORT'

                logger.warning(f"[实盘交易] 执行部分平仓订单: {symbol} {side} x {quantity:.6f} (positionSide: {position_side})")

                order = self.binance_client.place_market_order(
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    reduce_only=True,
                    position_side=position_side
                )

                if not order:
                    logger.error(f"部分平仓订单失败: {symbol} Stage {stage}")
                    return False

                logger.info(f"✓ Stage {stage} 部分平仓成功: {symbol} 订单ID: {order['order_id']}")
                return True

        except Exception as e:
            logger.error(f"部分平仓异常: {symbol} Stage {stage} - {e}", exc_info=True)
            return False

    # ==================== 出场执行 ====================
    async def _execute_exit(self, symbol: str, exit_price: float) -> bool:
        """
        执行出场

        Args:
            symbol: 币种
            exit_price: 出场价格

        Returns:
            是否成功执行
        """
        try:
            if symbol not in self.risk_manager.active_positions:
                logger.warning(f"{symbol}: 未找到活跃持仓")
                return False

            position = self.risk_manager.active_positions[symbol]

            # 如果remaining_quantity≈0,说明已经通过部分平仓完全平完了
            # 只需要标记状态,不需要下单
            if position.remaining_quantity < 0.001:
                logger.info(f"{symbol}: 剩余数量≈0,无需下单,直接标记为已平仓")
                # 标记持仓为已平仓
                from risk_manager_v2 import PositionStatus
                position.status = PositionStatus.CLOSED
                position.current_price = exit_price

                # 计算总盈亏（使用原始数量）
                profit_loss = (exit_price - position.entry_price) * position.quantity
                if position.side == 'SELL':
                    profit_loss = -profit_loss

                logger.info(f"✓ {symbol}: 标记已平仓,总盈亏: {profit_loss:+.2f} USDT")

                # 根据表现添加冷却（使用ROTATION_SYSTEM配置）
                if profit_loss >= 0:
                    # 止盈：冷却10分钟
                    cooldown_minutes = ROTATION_SYSTEM['cooldown_periods']['after_take_profit']
                    self.risk_manager.add_take_profit_cooldown(symbol)
                    logger.info(f"{symbol}: 止盈后冷却{cooldown_minutes}分钟")
                else:
                    # 止损：冷却30分钟，并检查连续亏损
                    cooldown_minutes = ROTATION_SYSTEM['cooldown_periods']['after_stop_loss']
                    self.risk_manager.add_to_cooldown(
                        symbol,
                        cooldown_minutes=cooldown_minutes,
                        reason=f"止损平仓 (亏损{abs(profit_loss):.2f}USDT)"
                    )

                    # 检查连续亏损（可能触发60分钟长冷却）
                    triggered_long_cooldown = self.risk_manager.add_loss_record(symbol)
                    if triggered_long_cooldown:
                        logger.warning(f"{symbol}: 连续亏损，已触发{ROTATION_SYSTEM['cooldown_periods']['after_multiple_losses']}分钟冷却")

                return True

            # 否则，使用remaining_quantity下单
            close_quantity = position.remaining_quantity

            logger.info(f"执行出场: {symbol} x {close_quantity:.6f} @ {exit_price:.4f} (剩余: {position.remaining_quantity:.6f})")

            if self.config.paper_trading:
                logger.info(f"[模拟交易] 执行出场订单")
            else:
                # 实盘交易
                if not self.binance_client:
                    logger.error(f"Binance客户端未初始化，无法执行实盘交易")
                    return False

                side = 'SELL' if position.side == 'BUY' else 'BUY'
                position_side = 'LONG' if position.side == 'BUY' else 'SHORT'

                logger.warning(f"[实盘交易] 执行出场订单: {symbol} {side} x {close_quantity:.6f} (positionSide: {position_side})")

                order = self.binance_client.place_market_order(
                    symbol=symbol,
                    side=side,
                    quantity=close_quantity,  # 使用原始数量
                    reduce_only=True,
                    position_side=position_side
                )

                if not order:
                    logger.error(f"出场订单失败: {symbol}")
                    return False

                logger.info(f"✓ 出场成功: {symbol} 订单ID: {order['order_id']}")

            # 标记持仓为已平仓
            from risk_manager_v2 import PositionStatus
            position.status = PositionStatus.CLOSED
            position.current_price = exit_price

            # 更新统计数据 - 使用原始数量计算总盈亏
            profit_loss = (exit_price - position.entry_price) * position.quantity
            if position.side == 'SELL':
                profit_loss = -profit_loss

            logger.info(f"✓ 出场成功: {symbol} 盈亏: {profit_loss:+.2f} USDT")

            # 根据表现添加冷却（使用ROTATION_SYSTEM配置）
            if profit_loss >= 0:
                # 止盈：冷却10分钟
                cooldown_minutes = ROTATION_SYSTEM['cooldown_periods']['after_take_profit']
                self.risk_manager.add_take_profit_cooldown(symbol)
                logger.info(f"{symbol}: 止盈后冷却{cooldown_minutes}分钟")
            else:
                # 止损：冷却30分钟，并检查连续亏损
                cooldown_minutes = ROTATION_SYSTEM['cooldown_periods']['after_stop_loss']
                self.risk_manager.add_to_cooldown(
                    symbol,
                    cooldown_minutes=cooldown_minutes,
                    reason=f"止损平仓 (亏损{abs(profit_loss):.2f}USDT)"
                )

                # 检查连续亏损（可能触发60分钟长冷却）
                triggered_long_cooldown = self.risk_manager.add_loss_record(symbol)
                if triggered_long_cooldown:
                    logger.warning(f"{symbol}: 连续亏损，已触发{ROTATION_SYSTEM['cooldown_periods']['after_multiple_losses']}分钟冷却")

            return True

        except Exception as e:
            logger.error(f"出场失败: {symbol} - {e}", exc_info=True)
            return False

    # ==================== 数据获取（API集成） ====================
    def _fetch_candidate_coins(self) -> List[CoinInfo]:
        """获取候选币种列表"""
        if not self.binance_client:
            logger.warning("Binance客户端未初始化")
            return []

        try:
            coins_data = self.binance_client.get_top_coins_by_volume(
                SELECTION_CONFIG['top_n_by_volume']
            )
            coins = []

            for coin_data in coins_data:
                coins.append(CoinInfo(
                    symbol=coin_data['symbol'],
                    current_price=coin_data['price'],
                    change_24h=coin_data['change_24h'],
                    volume_24h=coin_data['volume_24h'],
                    current_volume=coin_data['volume'],
                    is_usdt_pair=True
                ))

            logger.debug(f"从Binance获取{len(coins)}个候选币种")
            return coins
        except Exception as e:
            logger.error(f"获取币种列表失败: {e}")
            return []

    def _fetch_btc_indicators(self) -> Tuple:
        """获取BTC指标"""
        if not self.binance_client:
            return None, None, None

        try:
            # 获取1分钟和15分钟的BTC K线
            klines_1m_data = self.binance_client.get_klines('BTCUSDT', '1m', 100)
            klines_15m_data = self.binance_client.get_klines('BTCUSDT', '15m', 100)

            if not klines_1m_data or not klines_15m_data:
                return None, None, None

            # 计算1分钟指标
            closes_1m = [k['close'] for k in klines_1m_data]
            highs_1m = [k['high'] for k in klines_1m_data]
            lows_1m = [k['low'] for k in klines_1m_data]
            volumes_1m = [k['volume'] for k in klines_1m_data]

            indicators_1m = self.indicator_calc.calculate_all_indicators(
                closes_1m, highs_1m, lows_1m, volumes_1m
            )

            # 计算15分钟指标
            closes_15m = [k['close'] for k in klines_15m_data]
            highs_15m = [k['high'] for k in klines_15m_data]
            lows_15m = [k['low'] for k in klines_15m_data]
            volumes_15m = [k['volume'] for k in klines_15m_data]

            indicators_15m = self.indicator_calc.calculate_all_indicators(
                closes_15m, highs_15m, lows_15m, volumes_15m
            )

            # 返回indicators和1m K线数据(用于计算1m波动率)
            return indicators_1m, indicators_15m, klines_1m_data

        except Exception as e:
            logger.error(f"获取BTC指标失败: {e}")
            return None, None, None

    def _fetch_market_data(self) -> Dict:
        """获取市场数据"""
        if not self.binance_client:
            return {
                'current_volume': 0,
                'avg_volume_24h': 1,
                'current_volatility': 0,
                'avg_volatility_24h': 1,
                'fear_greed_index': 50
            }

        try:
            # 获取BTC数据作为市场参考
            btc_ticker = self.binance_client.get_ticker('BTCUSDT')
            if btc_ticker:
                return {
                    'current_volume': btc_ticker.get('volume_24h', 0),
                    'avg_volume_24h': btc_ticker.get('volume_24h', 1),
                    'current_volatility': abs(btc_ticker.get('change_24h', 0)) / 100,
                    'avg_volatility_24h': abs(btc_ticker.get('change_24h', 0)) / 100,
                    'fear_greed_index': 50  # 默认中立
                }
        except Exception as e:
            logger.warning(f"获取市场数据失败: {e}")

        return {
            'current_volume': 0,
            'avg_volume_24h': 1,
            'current_volatility': 0,
            'avg_volatility_24h': 1,
            'fear_greed_index': 50
        }

    def _fetch_klines(self, symbol: str, interval: str, limit: int) -> List[Dict]:
        """获取K线数据"""
        if not self.binance_client:
            return []

        try:
            klines = self.binance_client.get_klines(symbol, interval, limit)
            logger.debug(f"获取{symbol} {interval} {len(klines)}根K线")
            return klines
        except Exception as e:
            logger.warning(f"获取K线失败 {symbol} {interval}: {e}")
            return []

    def _get_current_price(self, symbol: str) -> Optional[float]:
        """获取当前价格"""
        if not self.binance_client:
            return None

        try:
            ticker = self.binance_client.get_ticker(symbol)
            if ticker:
                return ticker['price']
            return None
        except Exception as e:
            logger.warning(f"获取价格失败 {symbol}: {e}")
            return None

    def _get_atr(self, symbol: str) -> Optional[float]:
        """计算ATR"""
        if not self.binance_client:
            return None

        try:
            klines = self.binance_client.get_klines(symbol, '3m', 30)
            if not klines:
                return None

            closes = [k['close'] for k in klines]
            highs = [k['high'] for k in klines]
            lows = [k['low'] for k in klines]
            volumes = [k['volume'] for k in klines]

            indicators = self.indicator_calc.calculate_all_indicators(
                closes, highs, lows, volumes
            )

            return indicators.atr if indicators else None

        except Exception as e:
            logger.warning(f"计算ATR失败 {symbol}: {e}")
            return None

    def _calculate_two_hour_change(self, klines_3m: List[Dict]) -> Optional[float]:
        """
        计算近2小时涨跌幅

        Args:
            klines_3m: 3分钟K线数据

        Returns:
            2小时涨跌幅(小数形式,如0.08=8%), 若数据不足返回None
        """
        # 2小时 = 40根3分钟K线
        required_bars = 40

        if len(klines_3m) < required_bars:
            logger.debug("K线数据不足40根,无法计算2h涨跌幅")
            return None

        # 2小时前的开盘价
        open_2h_ago = klines_3m[-required_bars]['open']
        # 当前收盘价
        current_close = klines_3m[-1]['close']

        # 计算涨跌幅
        change_2h = (current_close - open_2h_ago) / open_2h_ago

        return change_2h

    # ==================== 统计和报告 ====================
    def _log_statistics(self):
        """输出统计信息"""
        position_summary = self.risk_manager.get_position_summary()

        logger.debug(
            f"[统计] 活跃持仓: {position_summary['open_positions']}, "
            f"浮动P&L: {position_summary['total_floating_pnl_usdt']:+.2f} USDT"
        )

    def _get_session_summary(self) -> str:
        """获取会话摘要"""
        duration = datetime.now() - self.start_time if self.start_time else timedelta(0)
        hours = duration.total_seconds() / 3600

        return (
            f"\n会话摘要:\n"
            f"  运行时间: {hours:.1f} 小时\n"
            f"  信号生成: {self.stats['total_signals_generated']}\n"
            f"  信号执行: {self.stats['signals_executed']}\n"
            f"  持仓平仓: {self.stats['positions_closed']}\n"
            f"  总盈亏: {self.stats['total_profit_loss']:+.2f} USDT"
        )


# ==================== 启动函数 ====================
async def main():
    """主函数"""
    # 创建引擎
    engine = TradingEngine(EngineConfig(
        debug_mode=True,
        paper_trading=True,
        log_level="INFO"
    ))

    # 启动引擎
    engine.start()

    # 运行主循环
    try:
        await engine.main_loop(interval_seconds=10)
    except KeyboardInterrupt:
        engine.stop()


if __name__ == "__main__":
    # Python 3.10+
    asyncio.run(main())
    # 或使用asyncio.get_event_loop()
    # loop = asyncio.get_event_loop()
    # loop.run_until_complete(main())

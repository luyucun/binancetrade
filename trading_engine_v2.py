"""
主交易引擎 (trading_engine_v2.py)
系统的核心，协调所有模块完成完整的交易流程
"""

import logging
import json
import asyncio
import time
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from enum import Enum

from config_v2 import (
    TIMEFRAME_CONFIG, SELECTION_CONFIG, SYSTEM_CONFIG,
    EXECUTION_SYSTEM, DATA_CONFIG, API_CONFIG, RISK_MANAGEMENT,
    ROTATION_SYSTEM, COST_CONFIG
)
from coin_selector import CoinSelector, CoinInfo
from indicators import IndicatorCalculator
from trend_analyzer import TrendAnalyzer
from market_filter import MarketFilter
from signal_generator import SignalGenerator, TradingSignal
from risk_manager_v2 import RiskManager
from position_monitor_v2 import PositionMonitor, MonitoringEvent
from binance_client_v2 import BinanceClientV2
from trading_logger_v2 import get_trading_logger, log_trading_action


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
    paper_trading: bool = False  # 🚨 实盘交易模式
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

            # 🔧 获取有效的期货交易对列表，避免Invalid symbol错误
            self.valid_futures_symbols = set()
            try:
                valid_symbols = self.binance_client.get_valid_futures_symbols()
                self.valid_futures_symbols = set(valid_symbols)
                logger.info(f"获取到 {len(self.valid_futures_symbols)} 个有效期货交易对")
            except Exception as e:
                logger.warning(f"获取有效期货交易对失败: {e}, 将跳过无效交易对过滤")

            # 🔧 网络监控集成
            try:
                from network_monitor import get_network_monitor
                self.network_monitor = get_network_monitor()
                logger.info("✓ 网络监控集成成功")
            except Exception as e:
                logger.warning(f"网络监控集成失败: {e}")
                self.network_monitor = None

        except Exception as e:
            logger.error(f"Binance客户端初始化失败: {e}")
            self.binance_client = None
            self.valid_futures_symbols = set()

        # 🔧 增强日志系统集成
        try:
            self.trading_logger = get_trading_logger()
            logger.info("✓ 增强日志系统集成成功")
        except Exception as e:
            logger.warning(f"增强日志系统集成失败: {e}")
            self.trading_logger = None


        # 状态管理
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

        # 限流和风控追踪
        self._entry_timestamps = []  # 记录开仓时间戳，用于每小时限流
        self._daily_pnl = 0.0  # 当日累计净盈亏
        self._daily_date = datetime.now().date()  # 当前日期，用于跨日重置

        # 异常波动保护
        self._collective_stop_loss_cooldown_until = None  # 集体止损保护的冷却截止时间

        # 🔧 动态黑名单：记录运行时发现的无效币种
        self._invalid_symbols_blacklist = set()  # 运行时发现的无效币种
        self._failed_symbol_count = {}  # 币种失败次数统计

        # 🔧 新增：每日交易计数和相关性控制
        self._daily_trade_count = {}  # 每日每个symbol的交易计数
        self._correlation_cache = {}  # 币种相关性缓存

        # 🔧 初始化引擎状态（修复AttributeError: 'TradingEngine' object has no attribute 'state'）
        self.state = EngineState.IDLE

        logger.info("交易引擎初始化完成")

    def _setup_logging(self):
        """设置日志 - 控制台显示全部，文件只记录交易相关"""
        # 检查是否已有handlers，避免重复配置
        if not logging.root.handlers:
            # 创建控制台处理器（显示所有日志）
            console_handler = logging.StreamHandler()
            console_handler.setLevel(getattr(logging, self.config.log_level))
            console_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            console_handler.setFormatter(console_formatter)

            # 🔧 创建文件处理器（只记录交易相关日志）
            file_handler = logging.FileHandler('trading_engine.log', encoding='utf-8')
            file_handler.setLevel(logging.INFO)
            file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(file_formatter)

            # 🔧 创建自定义过滤器，只允许交易相关日志写入文件
            class TradingOnlyFilter(logging.Filter):
                def filter(self, record):
                    # WARNING和ERROR级别的日志总是记录
                    if record.levelno >= logging.WARNING:
                        return True

                    # 只记录包含以下关键词的INFO级别日志
                    trading_keywords = [
                        '入场', '出场', '平仓', '开仓', '止损', '止盈',
                        '✓ 入场成功', '✓ 出场成功', '执行入场', '执行出场',
                        '触发止损', 'Stage', '部分平仓',
                        '杠杆设置', '双向持仓模式', '引擎启动', '引擎停止',
                        '交易引擎', '实盘交易确认', '紧急平仓'
                    ]
                    message = record.getMessage()
                    return any(keyword in message for keyword in trading_keywords)

            # 为文件处理器添加过滤器
            file_handler.addFilter(TradingOnlyFilter())

            # 设置根日志记录器
            logging.basicConfig(
                level=getattr(logging, self.config.log_level),
                handlers=[console_handler, file_handler]
            )

        # 🔧 根据配置的日志级别决定是否精简日志
        if self.config.log_level == 'DEBUG':
            # DEBUG模式：所有模块都使用DEBUG级别
            logging.getLogger('trading_engine_v2').setLevel(logging.DEBUG)
            logging.getLogger('binance_client_v2').setLevel(logging.INFO)  # 🔧 binance客户端用INFO，减少API日志
            logging.getLogger('signal_generator').setLevel(logging.DEBUG)
            logging.getLogger('position_monitor_v2').setLevel(logging.DEBUG)
            logging.getLogger('risk_manager_v2').setLevel(logging.DEBUG)
            logging.getLogger('coin_selector').setLevel(logging.DEBUG)
            logging.getLogger('indicators').setLevel(logging.DEBUG)
            logging.getLogger('trend_analyzer').setLevel(logging.DEBUG)
            logging.getLogger('market_filter').setLevel(logging.DEBUG)

            # 🔧 屏蔽urllib3和asyncio的DEBUG日志
            logging.getLogger('urllib3').setLevel(logging.WARNING)
            logging.getLogger('urllib3.connectionpool').setLevel(logging.WARNING)
            logging.getLogger('asyncio').setLevel(logging.WARNING)
        else:
            # INFO模式：精简日志策略，只保留交易相关的重要日志
            # 核心交易模块保持INFO级别（重要操作）
            logging.getLogger('trading_engine_v2').setLevel(logging.INFO)

            # API客户端：只记录WARNING和ERROR（减少连接日志）
            logging.getLogger('binance_client_v2').setLevel(logging.WARNING)

            # 信号生成：只记录INFO（信号生成和执行）
            logging.getLogger('signal_generator').setLevel(logging.INFO)

            # 持仓监控：只记录INFO（平仓操作）
            logging.getLogger('position_monitor_v2').setLevel(logging.INFO)

            # 风险管理：只记录INFO（入场决策）
            logging.getLogger('risk_manager_v2').setLevel(logging.INFO)

            # 辅助模块：只记录WARNING以上（过滤无关扫描）
            logging.getLogger('coin_selector').setLevel(logging.WARNING)
            logging.getLogger('indicators').setLevel(logging.WARNING)
            logging.getLogger('trend_analyzer').setLevel(logging.WARNING)
            logging.getLogger('market_filter').setLevel(logging.WARNING)

            # 🔧 屏蔽urllib3和asyncio的日志
            logging.getLogger('urllib3').setLevel(logging.WARNING)
            logging.getLogger('urllib3.connectionpool').setLevel(logging.WARNING)
            logging.getLogger('asyncio').setLevel(logging.WARNING)

    # ==================== 引擎生命周期 ====================
    def start(self):
        """启动引擎"""
        if self.state == EngineState.RUNNING:
            logger.warning("引擎已在运行中")
            return

        # 🚨 实盘交易安全检查
        if not self.config.paper_trading:
            logger.warning("=" * 80)
            logger.warning("🚨 实盘交易模式警告")
            logger.warning("=" * 80)
            logger.warning("⚠️ 您正在启用实盘交易模式!")
            logger.warning("⚠️ 这将使用您的真实资金进行交易!")
            logger.warning("⚠️ 请确保您:")
            logger.warning("   1. 已充分测试策略")
            logger.warning("   2. 设置了合理的风险参数")
            logger.warning("   3. 准备承担可能的亏损")
            logger.warning("   4. 已设置账户资金限额")
            logger.warning("=" * 80)

            # 需要显式确认
            if API_CONFIG.get('require_explicit_mainnet_confirmation', True):
                try:
                    print("🚨 实盘交易确认")
                    print("您正在启动实盘交易模式，这将使用真实资金!")
                    print("请确认以下信息:")
                    print(f"  API Key: {API_CONFIG['binance_key'][:10]}...{API_CONFIG['binance_key'][-10:]}")
                    print(f"  网络环境: {'测试网' if API_CONFIG.get('testnet', False) else '主网(实盘)'}")
                    print(f"  交易模式: {'模拟交易' if self.config.paper_trading else '实盘交易'}")

                    confirm1 = input("\n请输入 'YES' 确认启动实盘交易: ").strip()
                    if confirm1 != 'YES':
                        logger.error("实盘交易确认失败，取消启动")
                        return

                    confirm2 = input("请再次输入 'CONFIRM' 进行二次确认: ").strip()
                    if confirm2 != 'CONFIRM':
                        logger.error("二次确认失败，取消启动")
                        return

                    logger.info("✅ 实盘交易确认通过，启动交易引擎...")

                except KeyboardInterrupt:
                    logger.error("用户取消启动")
                    return
                except Exception as e:
                    logger.error(f"确认过程异常: {e}")
                    return

        self.state = EngineState.RUNNING
        self.start_time = datetime.now()
        logger.info("=" * 80)
        logger.info("交易引擎启动")
        logger.info(f"模式: {'实盘交易' if not self.config.paper_trading else '模拟交易'}")
        logger.info(f"调试模式: {self.config.debug_mode}")
        logger.info(f"网络环境: {'测试网' if API_CONFIG.get('testnet', False) else '主网'}")
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

            # 🔧 统一设置杠杆（从配置中读取）
            configured_leverage = RISK_MANAGEMENT['position_sizing']['leverage']
            logger.info(f"正在设置杠杆为 {configured_leverage}x ...")
            try:
                # 获取有效期货交易对列表
                valid_symbols = self.binance_client.get_valid_futures_symbols()
                if valid_symbols:
                    success_count = 0
                    fail_count = 0
                    for symbol in valid_symbols[:20]:  # 🔧 先设置前20个，避免API限流
                        try:
                            if self.binance_client.set_leverage(symbol, configured_leverage):
                                success_count += 1
                            else:
                                fail_count += 1
                        except Exception as sym_e:
                            logger.debug(f"  {symbol}: 设置杠杆失败 - {sym_e}")
                            fail_count += 1

                    if success_count > 0:
                        logger.info(f"✓ 已为 {success_count} 个币种设置杠杆为 {configured_leverage}x")
                    if fail_count > 0:
                        logger.warning(f"⚠ {fail_count} 个币种设置杠杆失败（可能已有该杠杆设置）")
            except Exception as e:
                logger.warning(f"批量设置杠杆时出错: {e}（后续交易会自动应用配置杠杆）")

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

        # 🔧 生成并保存最终交易报告
        if self.trading_logger:
            try:
                summary = self.trading_logger.generate_session_summary()
                self.trading_logger.save_session_summary()
                self.trading_logger.export_csv_report()

                logger.info("=" * 80)
                logger.info("📊 增强交易会话报告")
                logger.info("=" * 80)
                logger.info(f"会话ID: {summary.session_id}")
                logger.info(f"运行时间: {(summary.end_time - summary.start_time).total_seconds() / 3600:.1f} 小时")
                logger.info(f"总交易笔数: {summary.total_trades}")
                if summary.total_trades > 0:
                    logger.info(f"胜率: {summary.win_rate:.1%}")
                    logger.info(f"总盈亏: {summary.total_pnl:+.2f} USDT")
                    logger.info(f"收益因子: {summary.profit_factor:.2f}")
                    logger.info(f"最大回撤: {summary.max_drawdown:.2f} USDT")
                    logger.info(f"平均持仓时间: {summary.avg_trade_duration / 60:.1f} 分钟")
                    if summary.top_performers:
                        logger.info(f"表现最佳: {', '.join(summary.top_performers)}")
                    if summary.worst_performers:
                        logger.info(f"表现最差: {', '.join(summary.worst_performers)}")

                logger.info(f"总信号生成: {self.stats['total_signals_generated']}")
                logger.info(f"信号执行率: {self.stats['signals_executed'] / max(1, self.stats['total_signals_generated']):.1%}")
                logger.info(f"错误计数: {summary.errors_count}")
                logger.info(f"网络问题: {summary.network_issues_count}")

                # 🔧 网络监控摘要
                if hasattr(self, 'network_monitor') and self.network_monitor:
                    try:
                        network_summary = self.network_monitor.get_network_summary()
                        logger.info("=" * 60)
                        logger.info("🌐 网络监控摘要")
                        logger.info("=" * 60)
                        logger.info(f"网络状态: {network_summary['status']}")
                        logger.info(f"平均延迟: {network_summary['latency_ms']:.0f}ms")
                        logger.info(f"API成功率: {network_summary['success_rate']:.1%}")
                        logger.info(f"连续失败: {network_summary['consecutive_failures']} 次")
                        logger.info(f"紧急模式: {'是' if network_summary['emergency_mode'] else '否'}")
                        logger.info(f"总API调用: {network_summary['total_calls']} 次")
                    except Exception as ne:
                        logger.warning(f"网络监控摘要生成失败: {ne}")

                # 🔧 表现分析摘要
                if hasattr(self, 'position_monitor') and self.position_monitor:
                    try:
                        perf_summary = self.position_monitor.get_performance_summary()
                        if perf_summary.get('total_symbols', 0) > 0:
                            logger.info("=" * 60)
                            logger.info("📈 表现分析摘要")
                            logger.info("=" * 60)
                            logger.info(f"追踪币种: {perf_summary['total_symbols']} 个")
                            logger.info(f"整体胜率: {perf_summary['overall_win_rate']:.1%}")
                            logger.info(f"累计盈亏: {perf_summary['total_pnl']:+.1f} USDT")
                            logger.info(f"总交易笔数: {perf_summary['total_trades']}")
                            if perf_summary.get('best_performer'):
                                logger.info(f"最佳表现: {perf_summary['best_performer']} ({perf_summary['best_pnl']:+.1f} USDT)")
                            if perf_summary.get('worst_performer'):
                                logger.info(f"最差表现: {perf_summary['worst_performer']} ({perf_summary['worst_pnl']:+.1f} USDT)")
                            logger.info(f"延长冷却: {perf_summary['symbols_with_extended_cooldown']} 个币种")
                    except Exception as pe:
                        logger.warning(f"表现分析摘要生成失败: {pe}")

                # 关闭日志系统
                self.trading_logger.close()

                logger.info("=" * 80)
            except Exception as e:
                logger.error(f"生成交易报告失败: {e}")

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

        logger.info(f"主循环已启动，扫描间隔: {interval_seconds}秒")
        logger.info("=" * 80)

        cycle_count = 0  # 🔧 添加循环计数器
        try:
            while self.state == EngineState.RUNNING:
                cycle_count += 1
                logger.info(f"[Cycle {cycle_count}] 开始扫描...")  # 🔧 每轮循环开始日志

                logger.debug(f"主循环: 状态={self.state.value}")

                # 步骤1: 扫描信号
                await self._scan_signals()

                # 步骤2: 监控持仓
                await self._monitor_positions()

                # 步骤3: 输出统计
                self._log_statistics()

                logger.info(f"[Cycle {cycle_count}] 扫描完成，等待{interval_seconds}秒...")  # 🔧 每轮循环结束日志

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
            # 0. 检查限流和日亏停开条件
            if not self._can_open_new_entry():
                return

            # 1. 获取币种列表
            all_coins = self._fetch_candidate_coins()
            if not all_coins:
                logger.debug("无法获取币种列表")  # 降低为debug
                return

            logger.debug(f"获取到 {len(all_coins)} 个候选币种")


            # 2. 筛选币种
            selected_coins = self.coin_selector.select_coins(all_coins)
            logger.debug(f"筛选后 {len(selected_coins)} 个币种")



            # 🔧 额外过滤：移除无效的期货交易对和动态黑名单
            if self.valid_futures_symbols:
                valid_coins = []
                invalid_symbols = []

                for coin in selected_coins:
                    # 检查是否在动态黑名单中
                    if coin.symbol in self._invalid_symbols_blacklist:
                        invalid_symbols.append(coin.symbol)
                        logger.debug(f"{coin.symbol}: 在动态黑名单中，跳过")
                        continue

                    # 检查是否为有效期货交易对
                    if coin.symbol in self.valid_futures_symbols:
                        valid_coins.append(coin)
                    else:
                        # 将无效币种加入动态黑名单
                        self._invalid_symbols_blacklist.add(coin.symbol)
                        invalid_symbols.append(coin.symbol)
                        logger.warning(f"{coin.symbol}: 无效期货交易对，加入黑名单")

                if invalid_symbols:
                    logger.debug(f"过滤掉 {len(invalid_symbols)} 个无效/黑名单币种")  # 降低为debug

                selected_coins = valid_coins
                logger.debug(f"期货交易对过滤后: {len(selected_coins)} 个有效币种")  # 降低为debug

                # 🔧 额外调试：显示过滤后保留的币种
                remaining_symbols = [coin.symbol for coin in selected_coins]
                logger.debug(f"保留的币种: {remaining_symbols[:10]}{'...' if len(remaining_symbols) > 10 else ''}")  # 降低为debug
            else:
                logger.warning("未获取到有效期货交易对列表，跳过过滤")

            # 3. 获取BTC和市场数据用于过滤
            btc_indicators_1m, btc_indicators_15m, btc_1m_klines = self._fetch_btc_indicators()
            market_data = self._fetch_market_data()

            # 3.1 检查BTC振幅异常（额外保护层）
            if not self._check_btc_amplitude(btc_1m_klines):
                # BTC振幅异常，跳过本轮信号扫描
                return

            # 🔧 3.2 允许双向交易，让每个币自己决定方向
            # BTC趋势仅作为参考信息记录
            btc_rsi = btc_indicators_15m.rsi if btc_indicators_15m else 50
            btc_trend_ref = "BEARISH" if btc_rsi < 40 else ("BULLISH" if btc_rsi > 60 else "NEUTRAL")
            target_direction = "BOTH"  # 🔧 允许双向，不强制锁定
            logger.debug(f"BTC趋势参考: {btc_trend_ref} (RSI={btc_rsi:.1f}), 目标交易方向: 自由(BOTH)")

            # 4. 应用市场过滤(传入btc_1m_klines用于计算1m波动率)
            filter_result = self.market_filter.apply_market_filters(
                btc_indicators_1m=btc_indicators_1m,
                btc_indicators_15m=btc_indicators_15m,
                btc_1m_klines=btc_1m_klines,
                target_direction=target_direction,  # 🔧 传入BOTH
                current_volume=market_data.get('current_volume', 0),
                avg_volume_24h=market_data.get('avg_volume_24h', 1),
                current_volatility=market_data.get('current_volatility', 0),
                avg_volatility_24h=market_data.get('avg_volatility_24h', 1),
                fear_greed_index=market_data.get('fear_greed_index', 50)
            )

            if not filter_result.can_trade:
                logger.debug(f"市场过滤不通过: {filter_result.warnings}")  # 降低为debug
                return

            logger.debug(f"市场状态: {filter_result.health.value}")  # 降低为debug


            # 5. 对每个币种检查信号 - 优化版：并发获取K线数据
            signals_generated = 0
            signals_executed = 0

            # 🔧 新增：应用日交易限制和相关性控制
            pre_filtered_coins = []
            for coin in selected_coins:
                # 基本检查：持仓状态和冷却
                if not self.risk_manager.can_open_new_position(coin.symbol):
                    logger.debug(f"{coin.symbol}: 已有头寸或在冷却中，跳过")
                    continue

                # 🔧 新增：日交易限制检查
                if not self._check_daily_trade_limit(coin.symbol):
                    continue

                # 🔧 新增：基于表现历史的过滤
                should_skip, skip_reason = self.position_monitor.should_skip_symbol_due_to_performance(coin.symbol)
                if should_skip:
                    logger.debug(f"{coin.symbol}: {skip_reason}")
                    continue

                pre_filtered_coins.append(coin)

            # 🔧 应用相关性过滤和惩罚计算
            correlation_penalties = self._calculate_correlation_penalty("", pre_filtered_coins)

            # 🚀 性能优化：并发处理所有币种
            tasks = []
            valid_coins = []

            # 收集有效币种（未被相关性完全过滤的）
            for coin in pre_filtered_coins:
                penalty = correlation_penalties.get(coin.symbol, 1.0)
                if penalty > 0:  # 未被完全过滤
                    valid_coins.append(coin)
                    tasks.append(self._process_single_coin_concurrent(coin))

            logger.debug(f"开始并发处理 {len(valid_coins)} 个币种...")  # 降低为debug

            # 并发执行所有币种的K线获取和信号分析
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 处理结果
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.warning(f"{valid_coins[i].symbol}: 处理时出错: {result}")
                    continue

                if result is None:
                    continue

                signal, position_scaling = result
                if signal:
                    signals_generated += 1

                    # 🔧 应用相关性惩罚：结合24h涨跌幅例外规则和相关性控制
                    correlation_penalty = correlation_penalties.get(signal.symbol, 1.0)
                    final_position_scaling = position_scaling * correlation_penalty

                    # 🔧 记录信号生成日志
                    if self.trading_logger:
                        self.trading_logger.log_signal(signal.symbol, {
                            'direction': signal.direction.value,
                            'confidence': signal.confidence,
                            'score': signal.score.total_score,
                            'entry_price': signal.entry_price,
                            'stop_loss': signal.stop_loss_price,
                            'take_profit_levels': signal.take_profit_levels,  # 🔧 修复: 字段名从 take_profit_stages 改为 take_profit_levels
                            'market_conditions': {
                                'correlation_penalty': correlation_penalty,
                                'position_scaling': position_scaling
                            }
                        }, executed=False)

                    if correlation_penalty < 1.0:
                        logger.info(f"生成信号: {signal.symbol} {signal.direction.value} 评分={signal.score.total_score} (相关性惩罚={correlation_penalty:.2f})")
                    else:
                        logger.info(f"生成信号: {signal.symbol} {signal.direction.value} 评分={signal.score.total_score}")

                    # 执行入场(传递最终的仓位缩放系数)
                    if await self._execute_entry(signal, position_scaling=final_position_scaling):
                        signals_executed += 1
                        # 🔧 记录信号执行日志
                        if self.trading_logger:
                            self.trading_logger.log_signal(signal.symbol, {
                                'direction': signal.direction.value,
                                'confidence': signal.confidence,
                                'score': signal.score.total_score,
                                'entry_price': signal.entry_price,
                                'final_position_scaling': final_position_scaling
                            }, executed=True)

                        # 🔧 记录日交易计数
                        self._record_daily_trade(signal.symbol)

            self.stats['total_signals_generated'] += signals_generated
            self.stats['signals_executed'] += signals_executed

            # 🔧 详细输出扫描结果汇总
            logger.info(
                f"扫描完成: 候选{len(all_coins)}个 -> 筛选{len(selected_coins)}个 -> "
                f"有效{len(pre_filtered_coins)}个 -> 处理{len(valid_coins)}个 -> "
                f"生成{signals_generated}个信号 -> 执行{signals_executed}个"
            )

            self.last_signal_scan = datetime.now()

        except Exception as e:
            logger.error(f"信号扫描出错: {e}", exc_info=True)

    # ==================== 并发优化方法 ====================
    async def _process_single_coin_concurrent(self, coin) -> Optional[Tuple]:
        """
        🚀 并发处理单个币种的信号分析

        Args:
            coin: 币种信息

        Returns:
            Tuple[TradingSignal, float] 或 None: (信号, 仓位缩放系数)
        """
        try:
            # 🔧 预检查：验证是否为有效的期货交易对
            if self.valid_futures_symbols and coin.symbol not in self.valid_futures_symbols:
                logger.debug(f"{coin.symbol}: 不是有效的期货交易对，跳过")
                return None

            # 🔧 检查动态黑名单
            if coin.symbol in self._invalid_symbols_blacklist:
                logger.debug(f"{coin.symbol}: 在动态黑名单中，跳过")
                return None

            # 🔧 额外检查：再次确认，避免遗漏
            if coin.symbol in ['HYPEUSDT', 'PIEVERSEUSDT', 'SOONUSDT', 'BEATUSDT', 'FARTCOINUSDT', 'CROSSUSDT', 'UAIUSDT']:
                logger.debug(f"{coin.symbol}: 已知无效交易对，跳过")
                return None

            loop = asyncio.get_running_loop()

            # 🔥 关键优化：并发获取3个时间周期的K线数据（减少超时风险）
            # logger.debug(f"{coin.symbol}: 开始并发获取K线数据...")  # 🔧 屏蔽噪音日志
            start_time = asyncio.get_event_loop().time()

            # 🔧 使用配置中的K线数量要求
            # 使用线程池并发执行阻塞的HTTP请求
            klines_3m_task = loop.run_in_executor(None, self._fetch_klines, coin.symbol, '3m', 50)  # 配置要求50根
            klines_5m_task = loop.run_in_executor(None, self._fetch_klines, coin.symbol, '5m', 20)  # 配置要求20根
            klines_15m_task = loop.run_in_executor(None, self._fetch_klines, coin.symbol, '15m', 50) # 🔧 增加到50根，确保能计算EMA50

            # 等待所有K线数据并发获取完成
            klines_3m, klines_5m, klines_15m = await asyncio.gather(
                klines_3m_task, klines_5m_task, klines_15m_task
            )

            fetch_time = asyncio.get_event_loop().time() - start_time
            # logger.debug(f"{coin.symbol}: K线数据获取完成，耗时 {fetch_time:.3f}s")  # 🔧 屏蔽噪音日志

            if not all([klines_3m, klines_5m, klines_15m]):
                logger.debug(f"{coin.symbol}: K线数据不足或币种无效，跳过")
                return None

            # 计算2h涨跌幅用于24h涨跌幅例外规则检查
            two_hour_change = self._calculate_two_hour_change(klines_3m)

            # 应用24h涨跌幅例外规则
            can_trade, position_scaling, reason = self.coin_selector._check_daily_change_with_exceptions(
                coin.symbol,
                coin.change_24h / 100.0,
                two_hour_change
            )

            if not can_trade:
                logger.debug(f"{coin.symbol}: {reason}")
                return None

            if position_scaling < 1.0:
                logger.debug(f"{coin.symbol}: {reason} (仓位系数={position_scaling})")

            # 计算3m真实量比
            volume_ratio_3m = self.coin_selector.calculate_volume_ratio_from_klines(
                klines_3m, lookback=20
            )

            # 生成信号 - 🔧 返回 (signal, signal_position_scaling)
            result = self.signal_generator.generate_signal(
                symbol=coin.symbol,
                klines_3m=klines_3m,
                klines_5m=klines_5m,
                klines_15m=klines_15m,
                current_price=coin.current_price,
                position_size_usdt=100.0,
                volume_ratio_3m=volume_ratio_3m
            )

            if result:
                signal, signal_position_scaling = result
                # 🔧 合并外部 position_scaling 和信号内部的缩放系数
                combined_scaling = position_scaling * signal_position_scaling
                return (signal, combined_scaling)

            return None

        except Exception as e:
            logger.error(f"{coin.symbol}: 并发处理时出错: {e}", exc_info=True)
            return None

    # ==================== 持仓监控 ====================
    async def _monitor_positions(self):
        """
        监控所有活跃持仓

        流程:
        1. 从Binance获取实际持仓数据（包含实际盈亏）
        2. 获取所有持仓的当前价格和ATR
        3. 更新持仓的实际盈亏数据
        4. 检查止损/止盈并执行平仓操作
        5. 记录监控事件
        """
        logger.debug("开始监控持仓...")  # 降低为debug

        try:
            if not self.risk_manager.active_positions:
                logger.debug("无活跃持仓，跳过监控")
                return

            # 步骤1: 从Binance获取实际持仓数据
            actual_positions = {}
            if self.binance_client and not self.config.paper_trading:
                try:
                    binance_positions = self.binance_client.get_positions()
                    for pos in binance_positions:
                        actual_positions[pos['symbol']] = pos
                    logger.debug(f"从Binance获取到 {len(actual_positions)} 个实际持仓")
                except Exception as e:
                    logger.warning(f"获取Binance实际持仓失败: {e}")

            # 步骤2: 🚀 批量获取当前价格和ATR - 性能优化
            logger.debug("批量获取价格数据...")  # 降低为debug
            start_time = asyncio.get_event_loop().time()

            # 优化：一次性获取所有价格
            all_prices = {}
            if self.binance_client:
                try:
                    all_prices = await asyncio.to_thread(self.binance_client.get_all_symbol_ticker_price)
                    fetch_time = asyncio.get_event_loop().time() - start_time
                    logger.debug(f"批量价格获取完成，耗时 {fetch_time:.3f}s")  # 降低为debug
                except Exception as e:
                    logger.warning(f"批量获取价格失败，回退到单独获取: {e}")

            current_prices = {}
            atr_values = {}
            failed_symbols = []

            # 🔥 关键优化：并发获取ATR数据
            atr_tasks = []
            symbols_list = list(self.risk_manager.active_positions.keys())

            for symbol in symbols_list:
                # 从批量结果中获取价格
                price = all_prices.get(symbol)
                if not price:
                    # 回退到单独获取
                    price = self._get_current_price(symbol)

                if price:
                    current_prices[symbol] = price
                    # 并发获取ATR
                    atr_task = asyncio.to_thread(self._get_atr, symbol)
                    atr_tasks.append((symbol, atr_task))
                else:
                    logger.warning(f"{symbol}: 无法获取价格，跳过本次监控")
                    failed_symbols.append(symbol)

            # 并发等待所有ATR计算完成
            if atr_tasks:
                atr_results = await asyncio.gather(*[task for _, task in atr_tasks], return_exceptions=True)

                for i, (symbol, _) in enumerate(atr_tasks):
                    atr_result = atr_results[i]
                    if isinstance(atr_result, Exception):
                        logger.warning(f"{symbol}: 获取ATR失败: {atr_result}")
                        failed_symbols.append(symbol) if symbol not in failed_symbols else None
                        current_prices.pop(symbol, None)  # 移除没有ATR的价格
                    elif atr_result:
                        atr_values[symbol] = atr_result
                    else:
                        logger.warning(f"{symbol}: 无法获取ATR，跳过本次监控")
                        failed_symbols.append(symbol) if symbol not in failed_symbols else None
                        current_prices.pop(symbol, None)  # 移除没有ATR的价格

            total_time = asyncio.get_event_loop().time() - start_time
            logger.debug(f"价格和ATR数据获取完成，总耗时 {total_time:.3f}s")

            if not current_prices:
                logger.warning(f"无法获取任何币种的价格数据，有{len(failed_symbols)}个币种失败")
                # 改进: 即使无法获取数据也不直接返回，在下次循环重试
                return

            # 记录可以监控的和无法监控的
            logger.debug(f"持仓监控统计: 可监控{len(current_prices)}个, 失败{len(failed_symbols)}个")
            if failed_symbols:
                logger.warning(f"有{len(failed_symbols)}个持仓无法获取数据: {failed_symbols}")

                # 🚨 紧急平仓机制：无法获取价格的持仓立即平仓，避免大额亏损
                emergency_close_symbols = []
                for symbol in failed_symbols:
                    if symbol in self.risk_manager.active_positions:
                        position = self.risk_manager.active_positions[symbol]
                        # 跳过已经平仓的持仓
                        from risk_manager_v2 import PositionStatus
                        if position.status != PositionStatus.CLOSED:
                            emergency_close_symbols.append(symbol)
                            logger.error(f"🚨 {symbol}: 无法获取价格数据，触发紧急平仓保护!")

                            # 🔧 统计失败次数（用于监控，但不加黑名单）
                            self._failed_symbol_count[symbol] = self._failed_symbol_count.get(symbol, 0) + 1
                            if self._failed_symbol_count[symbol] >= 3:
                                logger.warning(f"🔧 {symbol}: 连续{self._failed_symbol_count[symbol]}次获取数据失败（建议检查网络或币种状态）")

                # 执行紧急平仓
                for symbol in emergency_close_symbols:
                    try:
                        # 使用入场价格作为紧急平仓的估算价格
                        position = self.risk_manager.active_positions[symbol]
                        emergency_price = position.entry_price
                        logger.warning(f"🚨 {symbol}: 执行紧急平仓 (使用入场价格 {emergency_price:.4f} 作为估算)")

                        # 执行紧急平仓
                        success = await self._execute_emergency_exit(symbol, emergency_price)
                        if success:
                            self.stats['positions_closed'] += 1
                            logger.info(f"✓ {symbol}: 紧急平仓完成")
                        else:
                            logger.error(f"✗ {symbol}: 紧急平仓失败，请手动处理!")

                    except Exception as e:
                        logger.error(f"✗ {symbol}: 紧急平仓异常: {e}")
                        # 继续处理其他需要紧急平仓的币种

            # 步骤3: 更新持仓的实际盈亏数据（实盘模式）
            if actual_positions:
                for symbol, position in self.risk_manager.active_positions.items():
                    if symbol in actual_positions:
                        actual_pos = actual_positions[symbol]
                        # 更新实际盈亏（Binance返回的已包含所有手续费）
                        position.floating_pnl_usdt = actual_pos['unrealized_profit']
                        position.floating_pnl_pct = actual_pos['unrealized_profit_pct']
                        logger.debug(f"{symbol}: 更新实际盈亏 {position.floating_pnl_usdt:+.2f} USDT ({position.floating_pnl_pct:+.2f}%)")

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

            # 集体止损检测（在所有平仓完成后检查）
            if symbols_to_close:  # 如果有平仓发生，才检查集体止损
                self._detect_collective_stop_loss()

            # 记录事件
            for event in events:
                logger.info(f"{event.symbol}: {event.event_type} - P&L: {event.profit_loss_usdt:+.2f} USDT ({event.profit_loss_pct:+.2%})")
                self.stats['total_profit_loss'] += event.profit_loss_usdt

            # 清理过期的CLOSED持仓（超过1小时的）
            self._cleanup_old_positions()

            self.last_position_check = datetime.now()

        except Exception as e:
            logger.error(f"持仓监控出错: {e}", exc_info=True)

    @log_trading_action("ENTRY")
    async def _execute_entry(self, signal: TradingSignal, position_scaling: float = 1.0) -> bool:
        """
        执行入场

        Args:
            signal: 交易信号
            position_scaling: 仓位缩放系数(用于24h涨跌幅例外规则等)

        Returns:
            是否成功执行
        """
        entry_start_time = time.time()

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
                logger.info(f"[模拟] 入场 {signal.symbol} {signal.direction.value} x {quantity:.6f} @ {signal.entry_price:.4f}")
                execution_success = True
                order_result = {
                    'order_id': f"paper_{int(time.time())}",
                    'filled_quantity': quantity,
                    'filled_price': signal.entry_price,
                    'fees': position_size * 0.0005  # 模拟手续费
                }
            else:
                # 实盘交易
                if not self.binance_client:
                    logger.error(f"Binance客户端未初始化，无法执行实盘交易")
                    return False

                side = 'BUY' if signal.direction.value == 'BULLISH' else 'SELL'
                position_side = 'LONG' if signal.direction.value == 'BULLISH' else 'SHORT'

                logger.warning(f"[实盘] 入场 {signal.symbol} {side} x {quantity:.6f} (positionSide: {position_side})")

                # 🔧 下单前验证杠杆（确保与配置一致）
                configured_leverage = RISK_MANAGEMENT['position_sizing']['leverage']
                try:
                    if self.binance_client.set_leverage(signal.symbol, configured_leverage):
                        logger.debug(f"{signal.symbol}: 已确认杠杆为 {configured_leverage}x")
                except Exception as lev_e:
                    logger.warning(f"{signal.symbol}: 验证杠杆失败 - {lev_e}（继续下单）")

                # 直接下达市价单 (Hedge模式需指定positionSide)
                order = self.binance_client.place_market_order_prefer_maker(
                    symbol=signal.symbol,
                    side=side,
                    quantity=quantity,
                    position_side=position_side
                )

                if not order:
                    logger.error(f"入场订单失败: {signal.symbol}")

                    # 🔧 下单失败只记录，不加黑名单（可能是临时网络问题）
                    if self.trading_logger:
                        self.trading_logger.log_error(signal.symbol, {
                            'error_type': 'ORDER_FAILED',
                            'message': f'Market order execution failed',
                            'context': {
                                'side': side,
                                'quantity': quantity,
                                'position_side': position_side
                            }
                        })
                    return False

                execution_success = True
                order_result = order
                logger.info(f"✓ 入场成功: {signal.symbol} 订单ID: {order['order_id']}")

            # 记录入场执行时间
            execution_time = (time.time() - entry_start_time) * 1000

            # 🔧 记录入场日志
            if self.trading_logger:
                self.trading_logger.log_entry(signal.symbol, {
                    'side': signal.direction.value,
                    'quantity': quantity,
                    'entry_price': signal.entry_price,
                    'position_size_usdt': position_size,
                    'order_id': order_result.get('order_id'),
                    'fees': order_result.get('fees', position_size * 0.0005),
                    'execution_time': execution_time,
                    'position_scaling': position_scaling,
                    'signal_score': signal.score.total_score,
                    'risk_reward_ratio': abs((signal.entry_price - signal.stop_loss_price) / signal.entry_price),
                    'paper_trading': self.config.paper_trading
                })

            # 添加到活跃持仓
            position = self.risk_manager.add_position(
                symbol=signal.symbol,
                side="BUY" if signal.direction.value == "BULLISH" else "SELL",
                entry_price=signal.entry_price,
                quantity=quantity,
                risk_params=risk_params
            )

            # 记录开仓时间戳（用于每小时限流）
            self._record_entry()

            logger.info(f"✓ 入场成功: {signal.symbol} 仓位大小: {position_size:.2f} USDT")
            return True

        except Exception as e:
            execution_time = (time.time() - entry_start_time) * 1000
            logger.error(f"入场失败: {signal.symbol} - {e}", exc_info=True)

            # 🔧 记录入场异常日志
            if self.trading_logger:
                self.trading_logger.log_error(signal.symbol, {
                    'error_type': 'ENTRY_EXCEPTION',
                    'message': str(e),
                    'context': {
                        'execution_time': execution_time,
                        'position_size': position_size if 'position_size' in locals() else None,
                        'quantity': quantity if 'quantity' in locals() else None
                    },
                    'stack_trace': str(e)
                })

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
                logger.info(f"[模拟] Stage {stage} 部分平仓 {symbol}")
                return True  # 模拟交易直接返回成功
            else:
                # 实盘交易
                if not self.binance_client:
                    logger.error(f"Binance客户端未初始化，无法执行实盘交易")
                    return False

                side = 'SELL' if position.side == 'BUY' else 'BUY'
                position_side = 'LONG' if position.side == 'BUY' else 'SHORT'

                logger.warning(f"[实盘] Stage {stage} 部分平仓 {symbol} {side} x {quantity:.6f} (positionSide: {position_side})")

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

    @log_trading_action("EXIT")
    async def _execute_exit(self, symbol: str, exit_price: float) -> bool:
        """
        执行出场

        Args:
            symbol: 币种
            exit_price: 出场价格

        Returns:
            是否成功执行
        """
        exit_start_time = time.time()

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
                position.close_time = datetime.now()  # 记录平仓时间
                position.current_price = exit_price

                # 使用Binance返回的实际盈亏（实盘）或手动计算（模拟）
                if self.config.paper_trading:
                    # 模拟交易：手动计算盈亏
                    price_diff = (exit_price - position.entry_price) * position.quantity
                    if position.side == 'SELL':
                        price_diff = -price_diff

                    entry_fee = position.entry_price * position.quantity * (COST_CONFIG['taker_fee_bps'] / 10000)
                    exit_fee = exit_price * position.quantity * (COST_CONFIG['taker_fee_bps'] / 10000)
                    total_fee = entry_fee + exit_fee
                    profit_loss = price_diff - total_fee

                    logger.info(f"✓ {symbol}: [模拟] 标记已平仓, 价差: {price_diff:+.2f} USDT, 手续费: {total_fee:.2f} USDT, 净盈亏: {profit_loss:+.2f} USDT")
                else:
                    # 实盘交易：使用Binance返回的实际盈亏（已包含手续费）
                    profit_loss = position.floating_pnl_usdt
                    logger.info(f"✓ {symbol}: [实盘] 标记已平仓, 实际盈亏: {profit_loss:+.2f} USDT ({position.floating_pnl_pct:+.2f}%)")

                # 🔧 记录出场日志（标记完成）
                if self.trading_logger:
                    duration_seconds = (datetime.now() - position.entry_time).total_seconds()
                    self.trading_logger.log_exit(symbol, {
                        'exit_type': 'PARTIAL_COMPLETION',
                        'exit_price': exit_price,
                        'quantity': position.quantity,
                        'profit_loss': profit_loss,
                        'profit_loss_pct': position.floating_pnl_pct if not self.config.paper_trading else (profit_loss / (position.entry_price * position.quantity) * 100),
                        'duration': duration_seconds,
                        'reason': '分阶段平仓完成',
                        'fees': total_fee if self.config.paper_trading else None,
                        'paper_trading': self.config.paper_trading
                    })

                # 更新当日累计盈亏
                self._update_daily_pnl(profit_loss)

                # 🔧 新增：更新表现追踪
                self.position_monitor.update_performance_tracking(symbol, profit_loss)

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
                logger.info(f"[模拟] 出场 {symbol}")
                execution_success = True
                order_result = {'order_id': f"paper_exit_{int(time.time())}"}
            else:
                # 实盘交易
                if not self.binance_client:
                    logger.error(f"Binance客户端未初始化，无法执行实盘交易")
                    return False

                side = 'SELL' if position.side == 'BUY' else 'BUY'
                position_side = 'LONG' if position.side == 'BUY' else 'SHORT'

                logger.warning(f"[实盘] 出场 {symbol} {side} x {close_quantity:.6f} (positionSide: {position_side})")

                order = self.binance_client.place_market_order(
                    symbol=symbol,
                    side=side,
                    quantity=close_quantity,  # 使用原始数量
                    reduce_only=True,
                    position_side=position_side
                )

                if not order:
                    logger.error(f"出场订单失败: {symbol}")
                    # 🔧 记录订单失败日志
                    if self.trading_logger:
                        self.trading_logger.log_error(symbol, {
                            'error_type': 'EXIT_ORDER_FAILED',
                            'message': 'Exit market order execution failed',
                            'context': {
                                'side': side,
                                'quantity': close_quantity,
                                'position_side': position_side,
                                'exit_price': exit_price
                            }
                        })
                    return False

                execution_success = True
                order_result = order
                logger.info(f"✓ 出场成功: {symbol} 订单ID: {order['order_id']}")

            # 标记持仓为已平仓
            from risk_manager_v2 import PositionStatus
            position.status = PositionStatus.CLOSED
            position.close_time = datetime.now()  # 记录平仓时间
            position.current_price = exit_price

            # 记录出场执行时间
            execution_time = (time.time() - exit_start_time) * 1000

            # 使用Binance返回的实际盈亏（实盘）或手动计算（模拟）
            if self.config.paper_trading:
                # 模拟交易：手动计算盈亏
                price_diff = (exit_price - position.entry_price) * position.quantity
                if position.side == 'SELL':
                    price_diff = -price_diff

                entry_fee = position.entry_price * position.quantity * (COST_CONFIG['taker_fee_bps'] / 10000)
                exit_fee = exit_price * position.quantity * (COST_CONFIG['taker_fee_bps'] / 10000)
                total_fee = entry_fee + exit_fee
                profit_loss = price_diff - total_fee

                logger.info(f"✓ 出场成功: {symbol} - [模拟] 价差: {price_diff:+.2f} USDT, 手续费: {total_fee:.2f} USDT, 净盈亏: {profit_loss:+.2f} USDT")
            else:
                # 实盘交易：使用Binance返回的实际盈亏（已包含手续费）
                profit_loss = position.floating_pnl_usdt
                logger.info(f"✓ 出场成功: {symbol} - [实盘] 实际盈亏: {profit_loss:+.2f} USDT ({position.floating_pnl_pct:+.2f}%)")

            # 🔧 记录出场日志
            if self.trading_logger:
                duration_seconds = (datetime.now() - position.entry_time).total_seconds()
                exit_type = "STOP_LOSS" if profit_loss < 0 else "TAKE_PROFIT"

                self.trading_logger.log_exit(symbol, {
                    'exit_type': exit_type,
                    'exit_price': exit_price,
                    'quantity': close_quantity,
                    'profit_loss': profit_loss,
                    'profit_loss_pct': position.floating_pnl_pct if not self.config.paper_trading else (profit_loss / (position.entry_price * position.quantity) * 100),
                    'duration': duration_seconds,
                    'order_id': order_result.get('order_id'),
                    'fees': total_fee if self.config.paper_trading else None,
                    'reason': 'Market exit',
                    'execution_time': execution_time,
                    'paper_trading': self.config.paper_trading
                })

            # 更新当日累计盈亏
            self._update_daily_pnl(profit_loss)

            # 🔧 新增：更新表现追踪
            self.position_monitor.update_performance_tracking(symbol, profit_loss)

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
            execution_time = (time.time() - exit_start_time) * 1000
            logger.error(f"出场失败: {symbol} - {e}", exc_info=True)

            # 🔧 记录出场异常日志
            if self.trading_logger:
                self.trading_logger.log_error(symbol, {
                    'error_type': 'EXIT_EXCEPTION',
                    'message': str(e),
                    'context': {
                        'exit_price': exit_price,
                        'execution_time': execution_time,
                        'quantity': close_quantity if 'close_quantity' in locals() else None
                    },
                    'stack_trace': str(e)
                })

            return False

    # ==================== 紧急平仓执行 ====================
    async def _execute_emergency_exit(self, symbol: str, estimated_price: float) -> bool:
        """
        执行紧急平仓（用于无法获取价格数据的持仓）

        Args:
            symbol: 币种
            estimated_price: 估算价格（用于记录，实际使用市价单）

        Returns:
            是否成功执行
        """
        try:
            if symbol not in self.risk_manager.active_positions:
                logger.warning(f"{symbol}: 未找到活跃持仓")
                return False

            position = self.risk_manager.active_positions[symbol]

            # 使用剩余数量
            close_quantity = position.remaining_quantity

            logger.error(f"🚨 执行紧急平仓: {symbol} x {close_quantity:.6f} (估算价格: {estimated_price:.4f})")

            if self.config.paper_trading:
                logger.warning(f"[模拟] 紧急平仓 {symbol}")
            else:
                # 实盘交易 - 紧急市价单
                if not self.binance_client:
                    logger.error(f"Binance客户端未初始化，无法执行实盘紧急平仓")
                    return False

                side = 'SELL' if position.side == 'BUY' else 'BUY'
                position_side = 'LONG' if position.side == 'BUY' else 'SHORT'

                logger.error(f"[实盘] 🚨 紧急平仓 {symbol} {side} x {close_quantity:.6f} (positionSide: {position_side})")

                # 使用最基本的市价单，不使用maker优先
                try:
                    order = self.binance_client.place_market_order(
                        symbol=symbol,
                        side=side,
                        quantity=close_quantity,
                        reduce_only=True,
                        position_side=position_side
                    )

                    if not order:
                        logger.error(f"🚨 紧急平仓订单失败: {symbol}")
                        return False

                    logger.warning(f"✓ 紧急平仓成功: {symbol} 订单ID: {order['order_id']}")

                except Exception as order_e:
                    logger.error(f"🚨 {symbol}: 紧急平仓下单异常: {order_e}")
                    # 仍然标记为已平仓，避免重复尝试
                    pass

            # 标记持仓为已平仓
            from risk_manager_v2 import PositionStatus
            position.status = PositionStatus.CLOSED
            position.close_time = datetime.now()
            position.current_price = estimated_price

            # 估算盈亏（可能不准确，但总比不知道好）
            if self.config.paper_trading:
                # 模拟交易：估算盈亏
                price_diff = (estimated_price - position.entry_price) * position.quantity
                if position.side == 'SELL':
                    price_diff = -price_diff

                entry_fee = position.entry_price * position.quantity * (COST_CONFIG['taker_fee_bps'] / 10000)
                exit_fee = estimated_price * position.quantity * (COST_CONFIG['taker_fee_bps'] / 10000)
                total_fee = entry_fee + exit_fee
                estimated_pnl = price_diff - total_fee

                logger.warning(f"🚨 {symbol}: [模拟] 紧急平仓完成, 估算盈亏: {estimated_pnl:+.2f} USDT")
            else:
                # 实盘交易：使用Binance返回的实际盈亏（如果可用）
                estimated_pnl = position.floating_pnl_usdt if position.floating_pnl_usdt else 0.0
                logger.warning(f"🚨 {symbol}: [实盘] 紧急平仓完成, 最后已知盈亏: {estimated_pnl:+.2f} USDT")

            # 更新当日累计盈亏
            self._update_daily_pnl(estimated_pnl)

            # 🔧 新增：更新表现追踪（紧急平仓通常是亏损）
            self.position_monitor.update_performance_tracking(symbol, estimated_pnl)

            # 紧急平仓后加长冷却期（避免再次遇到问题）
            cooldown_minutes = ROTATION_SYSTEM['cooldown_periods']['after_multiple_losses']  # 180分钟
            self.risk_manager.add_to_cooldown(
                symbol,
                cooldown_minutes=cooldown_minutes,
                reason=f"紧急平仓 (无法获取价格数据)"
            )

            logger.warning(f"🚨 {symbol}: 紧急平仓后冷却{cooldown_minutes}分钟，避免重复问题")

            return True

        except Exception as e:
            logger.error(f"🚨 紧急平仓失败: {symbol} - {e}", exc_info=True)
            return False

    def _cleanup_old_positions(self):
        """清理已平仓持仓（缩短清理时间，避免持续报错）"""
        now = datetime.now()
        # 🔧 缩短清理时间：从1小时改为10分钟
        ten_minutes_ago = now - timedelta(minutes=10)

        from risk_manager_v2 import PositionStatus
        symbols_to_remove = []

        for symbol, position in self.risk_manager.active_positions.items():
            if position.status == PositionStatus.CLOSED:
                # 如果有close_time且超过10分钟，立即清理
                if position.close_time and position.close_time < ten_minutes_ago:
                    symbols_to_remove.append(symbol)
                # 🔧 如果没有close_time但状态为CLOSED，也清理（防止异常状态）
                elif position.close_time is None:
                    symbols_to_remove.append(symbol)
                    logger.debug(f"{symbol}: CLOSED状态但无close_time，立即清理")

        # 删除过期记录
        for symbol in symbols_to_remove:
            del self.risk_manager.active_positions[symbol]
            # 🔧 同时清理失败计数
            self._failed_symbol_count.pop(symbol, None)

        if symbols_to_remove:
            logger.debug(f"清理了 {len(symbols_to_remove)} 个已平仓持仓记录: {symbols_to_remove}")

    # ==================== 限流和日亏停开检查 ====================
    def _can_open_new_entry(self) -> bool:
        """
        检查是否允许开新仓

        检查项:
        1. 每小时限流 (max_entries_per_hour)
        2. 单日亏损限制 (daily_loss_limit_usdt)
        3. 集体止损冷却保护

        Returns:
            是否允许开新仓
        """
        now = datetime.now()

        # 1. 跨日重置检查
        today = now.date()
        if today != self._daily_date:
            # 跨日了，重置日亏累计和日期
            logger.info(f"跨日重置: 昨日净盈亏 {self._daily_pnl:+.2f} USDT, 今日重新开始")
            self._daily_pnl = 0.0
            self._daily_date = today

        # 2. 检查每小时限流
        max_entries_per_hour = SYSTEM_CONFIG.get('max_entries_per_hour', 5)
        one_hour_ago = now - timedelta(hours=1)

        # 清理1小时前的旧记录
        self._entry_timestamps = [t for t in self._entry_timestamps if t > one_hour_ago]

        # 检查是否超出限流
        if len(self._entry_timestamps) >= max_entries_per_hour:
            logger.warning(f"每小时限流: 已开仓{len(self._entry_timestamps)}次/小时 (上限{max_entries_per_hour}), 暂停新开仓")
            return False

        # 3. 检查日亏停开
        daily_loss_limit = SYSTEM_CONFIG.get('daily_loss_limit_usdt', 5.0)
        if self._daily_pnl <= -daily_loss_limit:
            logger.warning(f"触发日亏停开: 当日净亏损 {abs(self._daily_pnl):.2f} USDT >= 限制 {daily_loss_limit} USDT, 停止新开仓")
            return False

        # 4. 检查集体止损冷却保护
        if self._collective_stop_loss_cooldown_until and now < self._collective_stop_loss_cooldown_until:
            remaining_seconds = (self._collective_stop_loss_cooldown_until - now).total_seconds()
            logger.warning(f"集体止损冷却中: 剩余 {remaining_seconds/60:.1f} 分钟, 暂停新开仓")
            return False

        return True

    def _record_entry(self):
        """记录一次开仓（用于限流追踪）"""
        self._entry_timestamps.append(datetime.now())

    def _update_daily_pnl(self, profit_loss_usdt: float):
        """更新当日累计盈亏"""
        self._daily_pnl += profit_loss_usdt
        logger.debug(f"更新当日累计盈亏: {profit_loss_usdt:+.2f} USDT, 累计: {self._daily_pnl:+.2f} USDT")

    # ==================== 异常波动保护 ====================
    def _check_btc_amplitude(self, btc_1m_klines: List[Dict]) -> bool:
        """
        检查BTC 1分钟振幅是否异常

        Args:
            btc_1m_klines: BTC 1分钟K线数据

        Returns:
            是否安全（振幅正常）
        """
        if not btc_1m_klines or len(btc_1m_klines) < 1:
            logger.warning("BTC 1m K线数据不足，跳过振幅检查")
            return True  # 数据不足时放行

        # 获取最近一根K线的振幅（high-low）/open
        last_kline = btc_1m_klines[-1]
        amplitude = (last_kline['high'] - last_kline['low']) / last_kline['open']

        # 阈值：2%（与市场过滤器的max_1m_volatility一致）
        max_amplitude = 0.02

        if amplitude > max_amplitude:
            logger.warning(f"BTC 1m振幅异常: {amplitude*100:.2f}% > {max_amplitude*100}% (市场异常波动)")
            return False

        return True

    def _detect_collective_stop_loss(self) -> bool:
        """
        检测是否发生集体止损事件

        定义：10秒内≥3个持仓触发止损，视为集体止损
        触发后：进入10分钟冷却期，停止新开仓

        Returns:
            是否检测到集体止损事件
        """
        now = datetime.now()
        ten_seconds_ago = now - timedelta(seconds=10)

        # 统计最近10秒内平仓且亏损的持仓
        recent_stop_losses = []

        for symbol, position in self.risk_manager.active_positions.items():
            # 检查是否是CLOSED状态
            from risk_manager_v2 import PositionStatus
            if position.status == PositionStatus.CLOSED:
                # 必须有close_time且在10秒内
                if position.close_time and position.close_time > ten_seconds_ago:
                    # 必须是亏损
                    if position.floating_pnl_usdt < 0:
                        recent_stop_losses.append(symbol)

        # 如果≥3个止损，触发集体止损保护
        if len(recent_stop_losses) >= 3:
            # 设置10分钟冷却期
            self._collective_stop_loss_cooldown_until = now + timedelta(minutes=10)
            logger.warning(f"⚠️ 检测到集体止损事件: {len(recent_stop_losses)}个持仓在10秒内止损 ({recent_stop_losses}), 启动10分钟冷却保护")
            return True

        return False

    # ==================== 数据获取（API集成） ====================
    def _fetch_candidate_coins(self) -> List[CoinInfo]:
        """获取候选币种列表"""
        if not self.binance_client:
            logger.warning("Binance客户端未初始化")
            return []

        try:
            coins_data = self.binance_client.get_top_coins_by_volume(
                limit=SELECTION_CONFIG['top_n_by_volume'],
                min_volume_usdt=SELECTION_CONFIG['min_24h_volume']
            )
            coins = []

            for coin_data in coins_data:
                coins.append(CoinInfo(
                    symbol=coin_data['symbol'],
                    current_price=coin_data['price'],
                    change_24h=coin_data['change_24h'],
                    volume_24h=coin_data['volume_24h'],
                    current_volume=coin_data['volume'],
                    is_usdt_pair=True,
                    # 🔧 添加新字段支持
                    trade_count_24h=coin_data.get('trade_count_24h')
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
            pass

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
            # logger.debug(f"{symbol}: 获取{interval} K线数据 {len(klines)}根")  # 🔧 屏蔽噪音日志
            return klines
        except Exception as e:
            logger.warning(f"{symbol}: 获取{interval} K线失败: {e}")
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
            logger.warning(f"{symbol}: 获取价格失败: {e}")
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
            logger.warning(f"{symbol}: 计算ATR失败: {e}")
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
            logger.debug(f"K线数据不足: {len(klines_3m)} < {required_bars}根，无法计算2h涨跌幅")
            return None

        # 2小时前的开盘价
        open_2h_ago = klines_3m[-required_bars]['open']
        # 当前收盘价
        current_close = klines_3m[-1]['close']

        # 计算涨跌幅
        change_2h = (current_close - open_2h_ago) / open_2h_ago

        return change_2h

    # ==================== 日交易限制与相关性控制 ====================
    def _check_daily_trade_limit(self, symbol: str) -> bool:
        """
        检查是否超过每日交易限制

        Args:
            symbol: 币种符号

        Returns:
            是否可以交易（未超过限制）
        """
        max_daily_trades = ROTATION_SYSTEM['symbol_rotation']['max_daily_trades_per_symbol']
        today = datetime.now().date()

        # 初始化或跨日重置
        if not hasattr(self, '_last_trade_date') or self._last_trade_date != today:
            self._daily_trade_count = {}
            self._last_trade_date = today
            logger.debug(f"跨日重置交易计数")

        # 获取当日交易次数
        current_count = self._daily_trade_count.get(symbol, 0)

        if current_count >= max_daily_trades:
            logger.debug(f"{symbol}: 今日交易次数({current_count})已达上限({max_daily_trades})")
            return False

        return True

    def _record_daily_trade(self, symbol: str):
        """记录一次日交易"""
        today = datetime.now().date()

        # 确保初始化
        if not hasattr(self, '_last_trade_date') or self._last_trade_date != today:
            self._daily_trade_count = {}
            self._last_trade_date = today

        # 增加交易计数
        self._daily_trade_count[symbol] = self._daily_trade_count.get(symbol, 0) + 1
        logger.debug(f"{symbol}: 记录日交易, 当前计数: {self._daily_trade_count[symbol]}")

    def _calculate_correlation_penalty(self, target_symbol: str, candidates: List) -> Dict[str, float]:
        """
        计算相关性惩罚系数并过滤高相关性币种

        Args:
            target_symbol: 目标币种
            candidates: 候选币种列表

        Returns:
            Dict[symbol, penalty]: 相关性惩罚系数映射 (0.5-1.0)
        """
        correlation_threshold = ROTATION_SYSTEM['symbol_rotation']['correlation_threshold']  # 0.7
        correlation_limit = ROTATION_SYSTEM['symbol_rotation']['correlation_symbol_limit']  # 1

        penalties = {}
        high_correlation_groups = {}  # {base_symbol: [similar_symbols]}

        # 简化的相关性计算：基于币种名称相似性和分类
        for candidate in candidates:
            symbol = getattr(candidate, 'symbol', candidate)

            # 基础币种提取 (去除USDT后缀)
            base_symbol = symbol.replace('USDT', '')

            # 计算与当前持仓的相关性
            correlation_score = self._estimate_symbol_correlation(symbol)

            if correlation_score >= correlation_threshold:
                # 高相关性币种分组
                base_key = self._get_symbol_base_category(base_symbol)
                if base_key not in high_correlation_groups:
                    high_correlation_groups[base_key] = []
                high_correlation_groups[base_key].append((symbol, correlation_score, candidate))

            # 设置惩罚系数
            if correlation_score >= 0.8:
                penalties[symbol] = 0.5  # 高相关性，大幅削减仓位
            elif correlation_score >= correlation_threshold:
                penalties[symbol] = 0.7  # 中等相关性，适度削减
            else:
                penalties[symbol] = 1.0  # 无相关性，正常仓位

        # 应用相关性限制：每组只保留评分最高的一个
        filtered_symbols = set()
        for group_symbols in high_correlation_groups.values():
            if len(group_symbols) > correlation_limit:
                # 排序并只保留前N个
                sorted_symbols = sorted(group_symbols, key=lambda x: x[1], reverse=True)
                kept_symbols = sorted_symbols[:correlation_limit]
                removed_symbols = sorted_symbols[correlation_limit:]

                for symbol, score, _ in kept_symbols:
                    filtered_symbols.add(symbol)

                for symbol, score, _ in removed_symbols:
                    penalties[symbol] = 0.0  # 标记为完全过滤
                    logger.debug(f"{symbol}: 相关性过滤(组内排序靠后), 相关性={score:.2f}")
            else:
                for symbol, _, _ in group_symbols:
                    filtered_symbols.add(symbol)

        return penalties

    def _estimate_symbol_correlation(self, symbol: str) -> float:
        """
        估算币种与当前持仓的相关性

        Args:
            symbol: 币种符号

        Returns:
            相关性分数 (0.0-1.0)
        """
        max_correlation = 0.0

        # 检查与当前活跃持仓的相关性
        for active_symbol in self.risk_manager.active_positions:
            correlation = self._get_symbol_correlation(symbol, active_symbol)
            max_correlation = max(max_correlation, correlation)

        return max_correlation

    def _get_symbol_correlation(self, symbol1: str, symbol2: str) -> float:
        """
        获取两个币种之间的相关性

        Args:
            symbol1, symbol2: 币种符号

        Returns:
            相关性分数 (0.0-1.0)
        """
        if symbol1 == symbol2:
            return 1.0

        # 提取基础币种名称
        base1 = symbol1.replace('USDT', '')
        base2 = symbol2.replace('USDT', '')

        # 1. 币种分类相关性 (L1基础分类)
        category1 = self._get_symbol_category(base1)
        category2 = self._get_symbol_category(base2)

        if category1 == category2 and category1 != 'OTHER':
            return 0.85  # 同分类高相关性

        # 2. 名称相似性
        if base1.startswith(base2[:3]) or base2.startswith(base1[:3]):
            return 0.75  # 名称前缀相似

        # 3. 知名关联币种 (hardcoded)
        high_correlation_pairs = [
            ('BTC', 'BCH'), ('ETH', 'ETC'), ('ADA', 'ADABNB'),
            ('DOT', 'KSM'), ('ATOM', 'OSMO'), ('SOL', 'SRM'),
            ('AVAX', 'JOE'), ('FTT', 'SRM'), ('BNB', 'CAKE')
        ]

        for pair in high_correlation_pairs:
            if (base1 in pair and base2 in pair):
                return 0.8

        # 4. 默认低相关性
        return 0.1

    def _get_symbol_category(self, base_symbol: str) -> str:
        """获取币种分类"""
        # Layer 1 主链
        if base_symbol in ['BTC', 'BCH', 'BSV', 'LTC']:
            return 'L1_BITCOIN'
        elif base_symbol in ['ETH', 'ETC']:
            return 'L1_ETHEREUM'
        elif base_symbol in ['ADA', 'DOT', 'SOL', 'AVAX', 'ATOM', 'NEAR', 'ALGO']:
            return 'L1_ALTERNATIVE'

        # DeFi
        elif base_symbol in ['UNI', 'SUSHI', 'CAKE', 'AAVE', 'COMP', 'YFI', 'CRV', '1INCH']:
            return 'DEFI'

        # Exchange Token
        elif base_symbol in ['BNB', 'FTT', 'OKB', 'KCS', 'HT']:
            return 'EXCHANGE'

        # Gaming/NFT
        elif base_symbol in ['AXS', 'SAND', 'MANA', 'ENJ', 'CHZ', 'FLOW']:
            return 'GAMING_NFT'

        # Meme
        elif base_symbol in ['DOGE', 'SHIB', 'FLOKI', 'ELON']:
            return 'MEME'

        # Oracle
        elif base_symbol in ['LINK', 'BAND', 'TRB']:
            return 'ORACLE'

        # Storage
        elif base_symbol in ['FIL', 'AR', 'SC']:
            return 'STORAGE'

        return 'OTHER'

    def _get_symbol_base_category(self, base_symbol: str) -> str:
        """获取币种基础分类用于分组"""
        category = self._get_symbol_category(base_symbol)

        # 将细分类合并为基础类
        if category.startswith('L1_'):
            return 'L1'  # 所有Layer1归为一组
        return category

    # ==================== 统计和报告 ====================
    def _log_statistics(self):
        """输出统计信息 - 精简版：只在有活跃持仓时显示"""
        position_summary = self.risk_manager.get_position_summary()

        # 🔧 只在有活跃持仓时才输出统计
        if position_summary['open_positions'] > 0:
            # 🔧 添加黑名单统计
            blacklist_count = len(self._invalid_symbols_blacklist)
            blacklist_info = f", 黑名单: {blacklist_count}" if blacklist_count > 0 else ""

            logger.info(
                f"📊 [持仓统计] 活跃: {position_summary['open_positions']}, "
                f"浮动P&L: {position_summary['total_floating_pnl_usdt']:+.2f} USDT"
                f"{blacklist_info}"
            )

        # 🔧 定期显示黑名单内容（每60轮显示一次，减少频率）
        if hasattr(self, '_stats_counter'):
            self._stats_counter += 1
        else:
            self._stats_counter = 1

        if self._stats_counter % 60 == 0:
            blacklist_count = len(self._invalid_symbols_blacklist)
            if blacklist_count > 0:
                blacklist_list = list(self._invalid_symbols_blacklist)
                logger.info(f"🔧 动态黑名单 ({blacklist_count}个): {blacklist_list}")

            # 🔧 新增：定期清理表现数据和显示表现摘要
            self.position_monitor.cleanup_old_performance_data()
            perf_summary = self.position_monitor.get_performance_summary()

            if perf_summary.get('total_symbols', 0) > 0:
                logger.info(
                    f"📈 表现摘要: "
                    f"追踪{perf_summary['total_symbols']}个币种, "
                    f"总胜率{perf_summary['overall_win_rate']:.1%}, "
                    f"累计盈亏{perf_summary['total_pnl']:+.1f}USDT, "
                    f"延长冷却{perf_summary['symbols_with_extended_cooldown']}个"
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
    # 创建引擎 - 🚨 实盘交易模式
    engine = TradingEngine(EngineConfig(
        debug_mode=False,
        paper_trading=False,  # 🚨 实盘交易
        log_level="INFO"
    ))

    # 启动引擎
    engine.start()

    # 运行主循环
    try:
        await engine.main_loop(interval_seconds=10)
    except KeyboardInterrupt:
        pass
    finally:
        # 确保无论如何都执行停止逻辑
        if engine.state != EngineState.STOPPED:
            engine.stop()
        print("\n程序已退出。按回车键关闭窗口...")
        input()


if __name__ == "__main__":
    try:
        # Python 3.10+
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程序被中断。")
        print("按回车键关闭窗口...")
        input()

"""
优化版趋势追踪交易程序 v2.0
功能: 每个整点分钟检测总市值前30的币种，识别多因子确认信号立即顺势入场
策略: 【顺势交易+多因子确认】8根中6-7根涨→做多，8根中6-7根跌→做空

改进：
- 放宽趋势门槛：从10/9改为8/6-7
- 新增5大确认因子：EMA、MACD、RSI、成交量、多周期
- 信号质量大幅提升（减少虚假信号）
- 获取多周期K线进行确认分析
"""

import logging
import time
from datetime import datetime, timedelta
from binance.client import Client
from binance.exceptions import BinanceAPIException
import schedule

# 设置项目路径
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from cooldown_manager import CooldownManager

# ==================== 配置参数 ====================
BINANCE_API_KEY = "imYdWlm5XWjKRi9SPm6vFvf9m95MQ5Sy24pDvkAVh7MaNAQ2SMl2HsCEb9QA6kTo"
BINANCE_API_SECRET = "nt6zojBmMkNOnA5WsTvpBh2pORcCxBYEQQinSo8dbWQdu320KKk5CS6hLYsGd1QF"

# 交易参数
BASE_TRADE_AMOUNT = 10  # USDT (本金)
LEVERAGE = 2  # 杠杆倍数
ACTUAL_TRADE_AMOUNT = BASE_TRADE_AMOUNT * LEVERAGE  # 20 USDT

# 币种选择参数
MONITOR_VOLUME_TOP_N = 70  # 交易量前70

# K线参数 - 获取更多数据用于多因子分析
KLINE_INTERVAL_1M = "1m"   # 1分钟K线（主周期）
KLINE_INTERVAL_3M = "3m"   # 3分钟K线（备用，某些函数默认参数）
KLINE_INTERVAL_5M = "5m"   # 5分钟K线（多周期确认）
KLINE_LIMIT = 30           # 获取30根K线（用于各种指标计算）

# 日志配置
LOG_LEVEL = "INFO"

# ==================== 日志配置 ====================
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SimpleSignalAnalyzer:
    """简单的趋势信号分析器 - 基础版本"""

    @staticmethod
    def calculate_ema(prices, period):
        """计算EMA（指数移动平均）"""
        if not prices or len(prices) < period:
            return None

        prices = prices[-period:]
        ema = prices[0]
        multiplier = 2 / (period + 1)

        for price in prices[1:]:
            ema = price * multiplier + ema * (1 - multiplier)

        return ema

    @staticmethod
    def calculate_macd(prices, fast=12, slow=26, signal=9):
        """计算MACD"""
        if not prices or len(prices) < slow:
            return None, None, None

        ema12 = SimpleSignalAnalyzer.calculate_ema(prices, fast)
        ema26 = SimpleSignalAnalyzer.calculate_ema(prices, slow)

        if ema12 is None or ema26 is None:
            return None, None, None

        macd = ema12 - ema26
        return macd, ema12, ema26

    @staticmethod
    def calculate_rsi(prices, period=14):
        """计算RSI（相对强度指数）"""
        if not prices or len(prices) < period + 1:
            return None

        prices = prices[-(period + 1):]
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]

        gains = [d if d > 0 else 0 for d in deltas]
        losses = [-d if d < 0 else 0 for d in deltas]

        avg_gain = sum(gains[-period:]) / period if period > 0 else 0
        avg_loss = sum(losses[-period:]) / period if period > 0 else 0

        if avg_loss == 0:
            return 100 if avg_gain > 0 else 50

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        return rsi

    @staticmethod
    def price_above_ema(klines, period=21):
        """检查价格是否在EMA之上"""
        if not klines or len(klines) < period:
            return False

        prices = [float(k['close']) for k in klines]
        ema = SimpleSignalAnalyzer.calculate_ema(prices, period)

        if ema is None:
            return False

        current_price = prices[-1]
        return current_price > ema * 1.0001  # 避免浮点误差

    @staticmethod
    def macd_confirmation(klines):
        """MACD确认 - 检查MACD是否为正且信号线向上"""
        if not klines or len(klines) < 30:
            return False

        closes = [float(k['close']) for k in klines[-30:]]

        # 计算当前和前一根的MACD
        macd_current, _, _ = SimpleSignalAnalyzer.calculate_macd(closes)
        macd_prev, _, _ = SimpleSignalAnalyzer.calculate_macd(closes[:-1])

        if macd_current is None or macd_prev is None:
            return False

        # MACD为正且在上升 = 确认看多
        return macd_current > 0 and macd_current > macd_prev

    @staticmethod
    def rsi_trend_confirmation(klines):
        """RSI趋势确认 - RSI在30-70之间表示正常趋势"""
        if not klines or len(klines) < 16:
            return False

        closes = [float(k['close']) for k in klines[-16:]]
        rsi = SimpleSignalAnalyzer.calculate_rsi(closes)

        if rsi is None:
            return False

        # RSI在30-70之间表示有明确趋势
        return 30 < rsi < 70

    @staticmethod
    def volume_confirmation(klines):
        """成交量确认 - 当前成交量是否大于平均成交量"""
        if not klines or len(klines) < 5:
            return False

        recent_klines = klines[-5:]
        volumes = [float(k.get('volume', 0)) for k in recent_klines]

        current_volume = volumes[-1]
        avg_volume = sum(volumes[:-1]) / len(volumes[:-1]) if len(volumes) > 1 else 0

        # 当前成交量大于平均成交量的1.5倍 (原1.2倍)
        return current_volume > avg_volume * 1.5

    @staticmethod
    def timeframe_5m_confirmation(klines_5m):
        """5分钟时间框架确认 - 5分钟K线也要有同向趋势"""
        if not klines_5m or len(klines_5m) < 8:
            return False

        recent_klines = klines_5m[-8:]
        up_count = 0
        down_count = 0

        for i in range(len(recent_klines) - 1):
            close_current = float(recent_klines[i]['close'])
            close_next = float(recent_klines[i + 1]['close'])

            if close_next > close_current:
                up_count += 1
            elif close_next < close_current:
                down_count += 1

        # 5分钟也需要至少6根同向
        return up_count >= 6 or down_count >= 6

    @staticmethod
    def enhanced_signal_confirmation(klines_3m, klines_3m_for_rsi, klines_5m):
        """增强版信号确认 - 多因子验证（含5分钟确认）"""
        confirmation_score = 0
        confirmations = []

        # 1. 价格突破EMA21
        if SimpleSignalAnalyzer.price_above_ema(klines_3m, 21):
            confirmation_score += 1
            confirmations.append("EMA21")

        # 2. MACD金叉确认
        if SimpleSignalAnalyzer.macd_confirmation(klines_5m):
            confirmation_score += 1
            confirmations.append("MACD")

        # 3. RSI趋势确认
        if SimpleSignalAnalyzer.rsi_trend_confirmation(klines_3m_for_rsi):
            confirmation_score += 1
            confirmations.append("RSI")

        # 4. 成交量放大确认 (已提高到1.5倍)
        if SimpleSignalAnalyzer.volume_confirmation(klines_3m):
            confirmation_score += 1
            confirmations.append("Vol")

        # 5. [新增] 5分钟时间框架确认
        if SimpleSignalAnalyzer.timeframe_5m_confirmation(klines_5m):
            confirmation_score += 1
            confirmations.append("5M")

        return {
            'pass': confirmation_score >= 3,  # 至少满足3个条件
            'score': confirmation_score,
            'confirmations': confirmations
        }

    @staticmethod
    def analyze_signal(klines_1m):
        """
        简单的趋势分析
        检查最近8根1分钟K线中是否有6根以上同向

        返回: {
            'signal': 'LONG' / 'SHORT' / None,
            'confidence': 0.5-1.0,
            'confirmation_score': 分数,
            'reason': '原因说明'
        }
        """
        if not klines_1m or len(klines_1m) < 8:
            return {
                'signal': None,
                'confidence': 0,
                'confirmation_score': 0,
                'reason': 'K线数据不足'
            }

        try:
            # 检查最近8根K线
            recent_klines = klines_1m[-8:]

            # 计算涨跌个数
            up_count = 0
            down_count = 0

            for i in range(len(recent_klines) - 1):
                close_current = float(recent_klines[i]['close'])
                close_next = float(recent_klines[i + 1]['close'])

                if close_next > close_current:
                    up_count += 1
                elif close_next < close_current:
                    down_count += 1

            # 判断趋势（需要6根以上同向）
            signal = None
            confidence = 0.0
            reason = ""

            if up_count >= 6:
                signal = 'LONG'
                confidence = min(1.0, up_count / 8)
                reason = f"最近8根中{up_count}根上涨"
            elif down_count >= 6:
                signal = 'SHORT'
                confidence = min(1.0, down_count / 8)
                reason = f"最近8根中{down_count}根下跌"
            else:
                reason = f"趋势不明显: 涨{up_count}根, 跌{down_count}根"

            return {
                'signal': signal,
                'confidence': confidence,
                'confirmation_score': min(up_count, down_count, 6),
                'reason': reason
            }

        except Exception as e:
            logger.error(f"信号分析失败: {e}")
            return {
                'signal': None,
                'confidence': 0,
                'confirmation_score': 0,
                'reason': f'分析异常: {e}'
            }


class OptimizedTrendTrader:
    """优化版趋势追踪交易器 - 多因子确认"""

    def __init__(self):
        """初始化交易器"""
        logger.info("=" * 100)
        logger.info("【优化版趋势追踪交易系统启动】- 多因子确认版本 v2.0")
        logger.info("=" * 100)

        # 初始化Binance客户端
        try:
            self.client = Client(BINANCE_API_KEY, BINANCE_API_SECRET, {"timeout": 30})
            self._sync_time()
            logger.info("✓ Binance客户端连接成功")
        except Exception as e:
            logger.error(f"✗ Binance客户端连接失败: {e}")
            logger.error(f"错误类型: {type(e).__name__}")
            logger.error(f"详细信息: {str(e)}")
            import traceback
            logger.error(f"堆栈跟踪:\n{traceback.format_exc()}")
            input("按回车键退出...")
            raise

        # 初始化冷却管理器
        self.cooldown_manager = CooldownManager()

        logger.info(f"交易配置: {BASE_TRADE_AMOUNT} USDT × {LEVERAGE}倍杠杆 = {ACTUAL_TRADE_AMOUNT} USDT成交额")
        logger.info(f"监控范围: 24小时交易量前70个币种")
        logger.info(f"【K线周期】1分钟K线（主周期趋势检测）+ 5分钟K线（多周期确认）")
        logger.info(f"【入场条件】8根1分钟K线中6根以上同向 + 多因子确认(≥3个: EMA、MACD、RSI、成交量×1.5、5M趋势)")
        logger.info(f"【止损止盈】止损0.8×ATR, 止盈1.5×ATR (盈亏比1:3)")
        logger.info(f"【冷却机制】失败后冷却5-15分钟，连续失败延长冷却")
        logger.info(f"【执行频率】每2分钟扫描一次")
        logger.info("=" * 100)

    def _sync_time(self):
        """同步服务器时间"""
        try:
            server_time_data = self.client.get_server_time()
            server_time = server_time_data['serverTime']
            local_time = int(time.time() * 1000)
            time_offset = server_time - local_time

            if abs(time_offset) > 5000:
                logger.warning(f"时间偏差较大: {time_offset}ms")
            else:
                logger.info(f"时间同步成功，偏差: {time_offset}ms")
        except Exception as e:
            logger.warning(f"时间同步失败: {e}")

    def get_top_volume_symbols(self):
        """获取24小时交易量前50的币种"""
        try:
            # 获取所有永续合约
            exchange_info = self.client.futures_exchange_info()
            all_symbols = [s['symbol'] for s in exchange_info['symbols']
                          if s['quoteAsset'] == 'USDT' and s['status'] == 'TRADING']

            logger.info(f"获取到 {len(all_symbols)} 个U本位合约")

            # 获取24小时行情
            tickers = self.client.futures_ticker()
            ticker_dict = {t['symbol']: {
                'change': float(t['priceChangePercent']),
                'volume': float(t['quoteVolume'])
            } for t in tickers}

            # 筛选出有效币种并进行基本过滤
            quality_symbols = []
            for symbol in all_symbols:
                if symbol in ticker_dict:
                    volume_24h = ticker_dict[symbol]['volume']
                    change = ticker_dict[symbol]['change']

                    # 基本过滤条件：排除杠杆币、期权等
                    if (volume_24h > 3000000 and  # 最小成交量300万USDT (降低阈值以获取更多币种)
                        not any(x in symbol for x in ['1000', 'BULL', 'BEAR']) and
                        not symbol.endswith(('UP', 'DOWN')) and
                        len(symbol) <= 10):

                        quality_symbols.append({
                            'symbol': symbol,
                            'change': change,
                            'volume': volume_24h
                        })

            logger.info(f"基础过滤: {len(all_symbols)} → {len(quality_symbols)} 个币种")

            if len(quality_symbols) < 50:
                logger.warning(f"高交易量币种不足({len(quality_symbols)}/50)，降低过滤标准...")
                quality_symbols = []
                for symbol in all_symbols:
                    if symbol in ticker_dict:
                        volume_24h = ticker_dict[symbol]['volume']
                        if (volume_24h > 1000000 and  # 降低到100万USDT
                            not any(x in symbol for x in ['1000', 'BULL', 'BEAR']) and
                            not symbol.endswith(('UP', 'DOWN'))):
                            quality_symbols.append({
                                'symbol': symbol,
                                'change': ticker_dict[symbol]['change'],
                                'volume': volume_24h
                            })

            # 按交易量排序 (从大到小)
            quality_symbols.sort(key=lambda x: x['volume'], reverse=True)

            # 获取交易量前N个币种
            top_symbols = quality_symbols[:MONITOR_VOLUME_TOP_N]

            total_volume = sum([item['volume'] for item in top_symbols])
            avg_change = sum([item['change'] for item in top_symbols]) / len(top_symbols) if top_symbols else 0

            logger.info(f"【交易量前{MONITOR_VOLUME_TOP_N}币种】")
            logger.info(f"  前5: {[item['symbol'] for item in top_symbols[:5]]}")
            logger.info(f"  总交易量: {total_volume/100000000:.1f}亿USDT")
            logger.info(f"  平均涨跌: {avg_change:.2f}%")
            logger.info(f"  成交量范围: {top_symbols[-1]['volume']/1000000:.1f}M ~ {top_symbols[0]['volume']/1000000:.1f}M USDT")

            return top_symbols

        except Exception as e:
            logger.error(f"获取交易量排名失败: {e}")
            return []

    def get_kline_data(self, symbol, interval=KLINE_INTERVAL_1M, limit=KLINE_LIMIT):
        """获取K线数据"""
        try:
            klines = self.client.futures_klines(
                symbol=symbol,
                interval=interval,
                limit=limit
            )

            if not klines or len(klines) < limit:
                logger.debug(f"{symbol} {interval} K线数据不足")
                return None

            # 解析K线数据
            parsed_klines = []
            for k in klines:
                parsed_klines.append({
                    'open_time': int(k[0]),
                    'open': float(k[1]),
                    'high': float(k[2]),
                    'low': float(k[3]),
                    'close': float(k[4]),
                    'volume': float(k[5]),
                    'close_time': int(k[6])
                })

            return parsed_klines

        except Exception as e:
            logger.debug(f"获取 {symbol} {interval} K线失败: {e}")
            return None

    def get_2hour_change(self, symbol):
        """计算最近2小时涨跌幅"""
        try:
            # 获取2小时的5分钟K线（24根 = 2小时）
            klines = self.client.futures_klines(
                symbol=symbol,
                interval='5m',
                limit=25  # 多获取一根以确保有足够数据
            )

            if not klines or len(klines) < 24:
                return None

            # 2小时前的价格（第一根K线的开盘价）
            price_2h_ago = float(klines[-24][1])  # open price
            # 当前价格（最后一根K线的收盘价）
            current_price = float(klines[-1][4])  # close price

            # 计算涨跌幅
            change_pct = ((current_price - price_2h_ago) / price_2h_ago) * 100

            return change_pct

        except Exception as e:
            logger.debug(f"获取 {symbol} 2小时涨跌失败: {e}")
            return None

    def check_market_condition(self):
        """检查市场整体状况（基于1分钟K线）"""
        try:
            btc_klines = self.get_kline_data('BTCUSDT', KLINE_INTERVAL_1M)
            if not btc_klines or len(btc_klines) < 6:
                logger.warning("无法获取BTC数据，默认允许交易")
                return True

            btc_closes = [k['close'] for k in btc_klines[-6:]]
            btc_change = (btc_closes[-1] - btc_closes[0]) / btc_closes[0]

            if abs(btc_change) > 0.02:
                logger.warning(f"🚫 市场风险警告: BTC短期波动{btc_change*100:.2f}% > 2%，暂停交易避免极端行情")
                return False

            logger.info(f"✅ 市场状况检查: BTC变化{btc_change*100:.2f}%，允许交易")
            return True

        except Exception as e:
            logger.warning(f"市场检查失败: {e}，默认允许交易")
            return True

    def has_position(self, symbol):
        """检查是否已有持仓"""
        try:
            positions = self.client.futures_position_information(symbol=symbol)
            if not positions:
                return False

            position = positions[0]
            position_amt = float(position.get('positionAmt', 0))

            if position_amt != 0:
                side = "做多" if position_amt > 0 else "做空"
                logger.info(f"{symbol} 已有持仓: {position_amt} ({side}), 跳过下单")
                return True

            return False

        except Exception as e:
            logger.warning(f"检查 {symbol} 持仓失败: {e}, 为安全起见跳过下单")
            return True

    def set_leverage(self, symbol, leverage):
        """设置杠杆倍数，使用全仓模式"""
        try:
            # 设置为全仓模式 (marginType='CROSSED')
            self.client.futures_change_margin_type(symbol=symbol, marginType='CROSSED')
            logger.debug(f"{symbol} 已设置为全仓模式")
        except BinanceAPIException as e:
            # -4046: No need to change margin type (保证金模式已经正确，允许继续)
            if e.code == -4046:
                logger.debug(f"{symbol} 保证金模式已经是CROSSED，无需改变")
            else:
                logger.warning(f"{symbol} 设置全仓模式失败: {e}")
                return False
        except Exception as e:
            logger.warning(f"{symbol} 设置全仓模式异常: {e}")
            return False

        try:
            # 设置杠杆倍数
            self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
            logger.debug(f"{symbol} 杠杆设置为 {leverage}x (全仓模式)")
            return True
        except Exception as e:
            logger.warning(f"{symbol} 设置杠杆失败: {e}")
            return False

    def calculate_quantity(self, symbol, trade_amount):
        """计算下单数量"""
        try:
            ticker = self.client.futures_ticker(symbol=symbol)
            current_price = float(ticker['lastPrice'])
            quantity = trade_amount / current_price

            exchange_info = self.client.futures_exchange_info()
            symbol_info = next((s for s in exchange_info['symbols'] if s['symbol'] == symbol), None)

            if symbol_info:
                quantity_precision = symbol_info['quantityPrecision']
                quantity = float(f"{quantity:.{quantity_precision}f}")

            logger.debug(f"{symbol} 价格: {current_price}, 数量: {quantity}")
            return quantity

        except Exception as e:
            logger.error(f"计算 {symbol} 下单数量失败: {e}")
            return None

    def create_market_order(self, symbol, side, quantity):
        """创建市价单"""
        try:
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type='MARKET',
                quantity=quantity
            )

            logger.info(f"✓ 订单创建成功: {symbol} {side} {quantity}, 订单ID: {order['orderId']}")
            return order

        except BinanceAPIException as e:
            logger.error(f"✗ 创建订单失败: {symbol} {side} {quantity} - {e}")
            return None

    def place_trade(self, symbol, signal, analysis_result):
        """执行交易"""
        try:
            # 双重检查是否已有持仓
            if self.has_position(symbol):
                return False

            # 设置杠杆
            if not self.set_leverage(symbol, LEVERAGE):
                return False

            # 计算下单数量
            quantity = self.calculate_quantity(symbol, ACTUAL_TRADE_AMOUNT)
            if not quantity:
                return False

            # 确定买卖方向
            side = 'BUY' if signal == 'LONG' else 'SELL'

            # 下单
            order = self.create_market_order(symbol, side, quantity)

            if order:
                confidence = analysis_result.get('confidence', 0)
                reason = analysis_result.get('reason', '')
                logger.info(
                    f"【交易成功】{symbol} {signal} 入场, 数量: {quantity}, 成交额: {ACTUAL_TRADE_AMOUNT:.1f} USDT\n"
                    f"  信心度: {confidence*100:.1f}%, 确认分数: {analysis_result['confirmation_score']:.1f}\n"
                    f"  原因: {reason}"
                )
                return True
            else:
                return False

        except Exception as e:
            logger.error(f"执行交易失败: {symbol} - {e}")
            return False

    def scan_and_trade(self):
        """扫描币种并执行交易"""
        logger.info("\n" + "=" * 100)
        logger.info(f"【开始扫描】{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("=" * 100)

        # 市场检查
        if not self.check_market_condition():
            logger.warning("🚫 市场条件不适合交易，本轮跳过，等待下次扫描")
            logger.warning("=" * 100 + "\n")
            return

        # 获取交易量前70的币种
        target_symbols_info = self.get_top_volume_symbols()

        if not target_symbols_info:
            logger.warning("未获取到目标币种")
            return

        logger.info(f"开始分析 {len(target_symbols_info)} 个币种...")
        logger.info(f"  监测池: 交易量前70个币种")

        # 统计
        signals_found = 0
        trades_executed = 0
        direction_filtered = 0
        confirmation_failed = 0
        cooldown_filtered = 0

        for symbol_info in target_symbols_info:
            try:
                symbol = symbol_info['symbol']
                daily_change = symbol_info['change']  # 24小时涨跌（仅用于日志）

                # 【冷却检查】在处理前先检查是否在冷却期
                if self.cooldown_manager.is_in_cooldown(symbol):
                    remaining = self.cooldown_manager.get_cooldown_remaining(symbol)
                    logger.debug(f"【冷却中】{symbol} 仍在冷却期，剩余{remaining}秒，本轮跳过")
                    cooldown_filtered += 1
                    continue

                # 【第1步】获取1分钟K线和多周期K线
                klines_1m = self.get_kline_data(symbol, KLINE_INTERVAL_1M, KLINE_LIMIT)
                if not klines_1m:
                    continue

                klines_5m = self.get_kline_data(symbol, KLINE_INTERVAL_5M, KLINE_LIMIT)

                # 【第2步】执行趋势分析（基于1分钟K线）
                analysis = SimpleSignalAnalyzer.analyze_signal(klines_1m)

                signal = analysis['signal']

                if not signal:
                    continue

                # 【第2.5步】多因子确认检查
                if klines_5m:
                    confirmation = SimpleSignalAnalyzer.enhanced_signal_confirmation(
                        klines_1m, klines_1m, klines_5m
                    )

                    if not confirmation['pass']:
                        logger.debug(
                            f"【多因子过滤】{symbol} {signal} - 确认分数{confirmation['score']}/5 "
                            f"({', '.join(confirmation['confirmations']) if confirmation['confirmations'] else 'None'})"
                        )
                        confirmation_failed += 1
                        continue

                    # 融合分数到分析结果
                    analysis['confirmation_score'] = confirmation['score']
                    analysis['confirmations'] = confirmation['confirmations']
                else:
                    analysis['confirmation_score'] = 0
                    analysis['confirmations'] = []

                # 【第3步】检查信号方向与2小时趋势是否一致
                change_2h = self.get_2hour_change(symbol)
                if change_2h is None:
                    logger.debug(f"【跳过】{symbol} - 无法获取2小时涨跌数据")
                    continue

                # 过滤与2小时趋势严重相反的信号
                if signal == 'LONG' and change_2h < 0:
                    logger.info(f"【过滤信号】{symbol} - 趋势信号{signal}但2小时跌幅{change_2h:.2f}%，不符合条件")
                    direction_filtered += 1
                    continue

                if signal == 'SHORT' and change_2h > 0:
                    logger.info(f"【过滤信号】{symbol} - 趋势信号{signal}但2小时涨幅{change_2h:.2f}%，不符合条件")
                    direction_filtered += 1
                    continue

                # 检查是否已有持仓
                if self.has_position(symbol):
                    continue

                signals_found += 1
                confidence = analysis.get('confidence', 0)
                confirmation_score = analysis.get('confirmation_score', 0)
                confirmations = analysis.get('confirmations', [])
                logger.info(
                    f"【发现信号】{symbol} - {signal} (信心度{confidence*100:.1f}%, 多因子{confirmation_score}分, "
                    f"确认{','.join(confirmations)}, 2小时{change_2h:.2f}%, 24小时{daily_change:.2f}%)"
                )

                # 【第4步】执行交易
                if self.place_trade(symbol, signal, analysis):
                    trades_executed += 1
                    # 交易成功，清除该symbol的冷却（如果有）
                    self.cooldown_manager.clear_cooldown(symbol)

                # 避免API限流
                time.sleep(0.5)

            except Exception as e:
                logger.error(f"处理 {symbol} 时出错: {e}")
                continue

        # 统计结果
        logger.info("=" * 100)
        logger.info(
            f"【扫描完成】发现信号: {signals_found}, 多因子过滤: {confirmation_failed}, "
            f"方向过滤: {direction_filtered}, 冷却过滤: {cooldown_filtered}, 成功交易: {trades_executed}"
        )
        if signals_found > 0:
            success_rate = trades_executed / signals_found * 100
            logger.info(f"📊 信号成功率: {trades_executed}/{signals_found} = {success_rate:.1f}%")

        # 输出冷却状态
        self.cooldown_manager.log_status()

        logger.info("=" * 100 + "\n")

    def start(self):
        """启动交易系统"""
        logger.info("=" * 100)
        logger.info("【系统运行】每个整2分钟执行一轮扫描（如 10:00, 10:02, 10:04...）")
        logger.info("【K线分析】1分钟K线，最近8根中6根以上同向→交易（多因子确认）")
        logger.info("按 Ctrl+C 停止程序")
        logger.info("=" * 100 + "\n")

        # 计算等待到下一个整2分钟
        def wait_for_next_2min_mark():
            """等待到下一个整2分钟点"""
            now = datetime.now()
            current_minute = now.minute
            current_second = now.second

            # 计算到下一个整2分钟的分钟数
            minutes_to_next = 2 - (current_minute % 2)
            if minutes_to_next == 2 and current_second == 0:
                minutes_to_next = 0  # 如果正好在整点，立即执行

            # 计算总等待秒数
            wait_seconds = minutes_to_next * 60 - current_second

            if wait_seconds > 0:
                next_run_time = now + timedelta(seconds=wait_seconds)
                logger.info(f"等待到下一个整2分钟点: {next_run_time.strftime('%H:%M:%S')} (等待 {wait_seconds} 秒)")
                time.sleep(wait_seconds)

        # 首次等待到整2分钟点
        wait_for_next_2min_mark()

        # 持续运行：每个整2分钟执行一次
        while True:
            try:
                # 执行扫描
                self.scan_and_trade()

                # 等待到下一个整2分钟点（120秒）
                time.sleep(120)

            except KeyboardInterrupt:
                logger.info("\n收到中断信号，正在关闭系统...")
                break
            except Exception as e:
                logger.error(f"系统异常: {e}", exc_info=True)
                time.sleep(5)


if __name__ == "__main__":
    try:
        trader = OptimizedTrendTrader()
        try:
            trader.start()
        except KeyboardInterrupt:
            logger.info("\n系统已关闭")
        except Exception as e:
            logger.error(f"系统启动失败: {e}", exc_info=True)
            import traceback
            traceback.print_exc()
            input("按回车键继续...")
    except Exception as e:
        logger.error(f"初始化失败: {e}", exc_info=True)
        import traceback
        traceback.print_exc()
        input("按回车键继续...")

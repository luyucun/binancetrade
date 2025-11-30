"""
Binance API集成模板 (binance_client_v2.py) - 优化版
主要优化：
1. 接口修正：使用 futures_ticker/futures_klines 替代现货接口
2. 精度计算：使用 Decimal 防止浮点精度丢失
3. 批量获取价格：增加 get_all_prices 方法，减少 API 调用
"""

from binance.client import Client as BinanceClient
from binance.exceptions import BinanceAPIException, BinanceOrderException
from typing import Dict, List, Optional, Tuple
import logging
import time
from decimal import Decimal, ROUND_DOWN

logger = logging.getLogger(__name__)


def retry_on_error(max_retries=3, delay=0.5, backoff=1.5):
    """重试装饰器，用于处理临时网络错误"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    error_msg = str(e)
                    # 只重试网络错误，不重试API错误
                    if isinstance(e, BinanceAPIException):
                        raise  # API错误直接抛出，不重试
                    if 'Connection' in error_msg or 'timeout' in error_msg.lower() or 'RemoteDisconnected' in error_msg:
                        if attempt < max_retries - 1:
                            wait_time = delay * (backoff ** attempt)
                            time.sleep(wait_time)
                            continue
                    raise
            raise last_error
        return wrapper
    return decorator


class BinanceClientV2:
    """Binance Futures API客户端包装 - 优化版"""

    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        """
        初始化客户端

        Args:
            api_key: API密钥
            api_secret: API秘钥
            testnet: 是否使用测试网
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.symbol_info_cache = {}  # 缓存交易规则
        self._price_cache = {}  # 价格缓存
        self._price_cache_time = 0  # 价格缓存时间
        self.retry_count = 3  # 重试次数
        self.retry_delay = 0.5  # 重试延迟（秒）

        try:
            self.client = BinanceClient(
                api_key=api_key,
                api_secret=api_secret,
                testnet=testnet,
                requests_params={'timeout': 10}  # 设置10秒超时
            )
            logger.info(f"Binance客户端已初始化 ({'测试网' if testnet else '实盘'})")
        except Exception as e:
            logger.error(f"Binance客户端初始化失败: {e}")
            raise

    # ==================== 币种和行情数据 (修正为合约接口) ====================
    def get_top_coins_by_volume(self, limit: int = 60) -> List[Dict]:
        """获取交易量前N的USDT合约币种"""
        try:
            # 1. 获取所有合约的24小时统计数据
            # 注意：使用 futures_ticker 而不是 get_ticker (现货)
            tickers = self.client.futures_ticker()

            # 2. 获取合约交易对信息(用于过滤状态)
            exchange_info = self.client.futures_exchange_info()
            trading_symbols = {
                s['symbol']: s['status']
                for s in exchange_info['symbols']
                if s['status'] == 'TRADING' and s.get('contractType') == 'PERPETUAL'  # 仅限永续合约
            }

            # 3. 筛选和排序
            usdt_coins = []
            for t in tickers:
                symbol = t.get('symbol', '')
                if symbol.endswith('USDT') and symbol in trading_symbols:
                    # 排除非标准币种 (如 BTCUSDT_210924 等交割合约)
                    if '_' in symbol:
                        continue

                    usdt_coins.append({
                        'symbol': symbol,
                        'price': float(t.get('lastPrice', 0)),
                        'change_24h': float(t.get('priceChangePercent', 0)),
                        'volume_24h': float(t.get('quoteVolume', 0)),  # 合约接口用 quoteVolume 表示成交额(USDT)
                        'volume': float(t.get('volume', 0))  # 基础币种成交量
                    })

            # 按成交额(USDT)排序
            sorted_coins = sorted(
                usdt_coins,
                key=lambda x: x['volume_24h'],
                reverse=True
            )[:limit]

            logger.info(f"获取了{len(sorted_coins)}个USDT币种")
            return sorted_coins

        except BinanceAPIException as e:
            logger.error(f"获取币种列表失败: {e}")
            return []
        except Exception as e:
            logger.error(f"获取币种列表异常: {e}")
            return []

    @retry_on_error(max_retries=3, delay=0.5)
    def get_klines(self, symbol: str, interval: str, limit: int = 500) -> List[Dict]:
        """获取合约K线数据（使用 futures_klines）"""
        try:
            # 使用 futures_klines 获取合约K线
            klines = self.client.futures_klines(
                symbol=symbol,
                interval=interval,
                limit=limit
            )

            result = []
            for k in klines:
                result.append({
                    'time': int(k[0]),
                    'open': float(k[1]),
                    'high': float(k[2]),
                    'low': float(k[3]),
                    'close': float(k[4]),
                    'volume': float(k[5]),  # 合约K线 index 5 是 Volume
                    'quote_volume': float(k[7])  # index 7 是 Quote Asset Volume
                })
            return result

        except BinanceAPIException as e:
            logger.error(f"获取K线失败 {symbol}: {e}")
            return []
        except Exception as e:
            logger.error(f"获取K线异常 {symbol}: {e}")
            return []

    def get_ticker(self, symbol: str) -> Optional[Dict]:
        """获取单个合约当前行情（使用 futures_symbol_ticker）"""
        try:
            ticker = self.client.futures_symbol_ticker(symbol=symbol)
            # futures_symbol_ticker 返回 {'symbol': '...', 'price': '...', 'time': ...}
            return {
                'symbol': ticker['symbol'],
                'price': float(ticker['price']),
                'change_24h': 0.0,  # 单一ticker接口不返回24h变化
                'volume_24h': 0.0,
            }
        except Exception as e:
            logger.warning(f"获取行情失败 {symbol}: {e}")
            return None

    @retry_on_error(max_retries=3, delay=0.5)
    def get_all_prices(self) -> Dict[str, float]:
        """
        一次性获取所有合约的最新价格（优化监控性能）

        Returns:
            {symbol: price} 的字典
        """
        try:
            tickers = self.client.futures_symbol_ticker()
            return {t['symbol']: float(t['price']) for t in tickers}
        except Exception as e:
            logger.error(f"批量获取价格失败: {e}")
            return {}

    # ==================== 期货交易 ====================
    def get_symbol_info(self, symbol: str) -> Optional[Dict]:
        """获取币种交易规则"""
        # 先检查缓存
        if symbol in self.symbol_info_cache:
            return self.symbol_info_cache[symbol]

        try:
            exchange_info = self.client.futures_exchange_info()
            for s in exchange_info['symbols']:
                if s['symbol'] == symbol:
                    info = {
                        'symbol': symbol,
                        'status': s['status'],  # TRADING, BREAK, etc.
                        'quantity_precision': s['quantityPrecision'],
                        'price_precision': s['pricePrecision'],
                        'min_qty': 0.0,
                        'max_qty': float('inf'),
                        'step_size': 1.0,
                        'min_notional': 5.0
                    }

                    # 提取LOT_SIZE规则
                    for f in s['filters']:
                        if f['filterType'] == 'LOT_SIZE':
                            info['min_qty'] = float(f['minQty'])
                            info['max_qty'] = float(f['maxQty'])
                            info['step_size'] = float(f['stepSize'])
                        elif f['filterType'] == 'MIN_NOTIONAL':
                            info['min_notional'] = float(f.get('notional', 5.0))

                    self.symbol_info_cache[symbol] = info
                    return info

            logger.warning(f"未找到币种信息: {symbol}")
            return None

        except Exception as e:
            logger.error(f"获取币种信息失败 {symbol}: {e}")
            return None

    def adjust_quantity(self, symbol: str, quantity: float) -> Optional[float]:
        """
        严格处理数量精度（使用 Decimal 防止浮点精度丢失）

        Args:
            symbol: 交易对
            quantity: 原始数量

        Returns:
            调整后的数量，失败返回 None
        """
        info = self.get_symbol_info(symbol)
        if not info:
            return None

        # 检查币种状态
        if info.get('status') != 'TRADING':
            logger.error(f"{symbol}: 币种状态不是TRADING ({info.get('status')})")
            return None

        try:
            # 使用 Decimal 进行高精度计算
            qty_d = Decimal(str(quantity))
            step_d = Decimal(str(info['step_size']))
            min_qty_d = Decimal(str(info['min_qty']))
            max_qty_d = Decimal(str(info['max_qty']))

            # 向下取整到step_size的倍数
            # Quantize logic: (qty // step) * step
            adjusted_d = (qty_d // step_d) * step_d

            if adjusted_d < min_qty_d:
                logger.warning(f"{symbol}: 调整后数量 {adjusted_d} < 最小值 {min_qty_d}")
                return None

            if adjusted_d > max_qty_d:
                logger.warning(f"{symbol}: 调整后数量 {adjusted_d} > 最大值 {max_qty_d}")
                return None

            adjusted_float = float(adjusted_d)
            logger.debug(f"{symbol}: 数量调整 {quantity} -> {adjusted_float} (step={info['step_size']})")
            return adjusted_float

        except Exception as e:
            logger.error(f"精度调整计算错误 {symbol}: {e}")
            return None

    def adjust_price(self, symbol: str, price: float) -> Optional[float]:
        """
        调整价格精度

        Args:
            symbol: 交易对
            price: 原始价格

        Returns:
            调整后的价格，失败返回 None
        """
        info = self.get_symbol_info(symbol)
        if not info:
            return None

        try:
            price_precision = info.get('price_precision', 8)
            adjusted = round(price, price_precision)
            logger.debug(f"{symbol}: 价格调整 {price} -> {adjusted} (precision={price_precision})")
            return adjusted
        except Exception as e:
            logger.error(f"价格精度调整错误 {symbol}: {e}")
            return None

    def set_leverage(self, symbol: str, leverage: int) -> bool:
        """设置杠杆倍数"""
        try:
            self.client.futures_change_leverage(
                symbol=symbol,
                leverage=leverage
            )
            logger.info(f"{symbol}: 杠杆已设置为 {leverage}x")
            return True
        except BinanceAPIException as e:
            logger.error(f"设置杠杆失败 {symbol}: {e}")
            return False
        except Exception as e:
            logger.error(f"设置杠杆异常 {symbol}: {e}")
            return False

    def set_position_mode(self, dual_side_position: bool = True) -> bool:
        """
        设置持仓模式（单向/双向）

        Args:
            dual_side_position: True=双向持仓(Hedge), False=单向持仓

        Returns:
            是否设置成功
        """
        try:
            # 检查当前模式
            position_info = self.client.futures_get_position_mode()
            current_mode = position_info.get('dualSidePosition', False)

            if current_mode == dual_side_position:
                logger.info(f"持仓模式已经是目标状态")
                return True

            self.client.futures_change_position_mode(
                dualSidePosition=dual_side_position
            )
            mode_str = "双向持仓(Hedge)" if dual_side_position else "单向持仓"
            logger.info(f"持仓模式已设置为: {mode_str}")
            return True
        except BinanceAPIException as e:
            # 如果已经是目标模式，会返回错误码-4059，视为成功
            if e.code == -4059:
                logger.info(f"持仓模式已经是目标状态")
                return True
            logger.error(f"设置持仓模式失败: {e}")
            return False
        except Exception as e:
            logger.error(f"设置持仓模式异常: {e}")
            return False

    def set_margin_type(self, symbol: str, margin_type: str = 'CROSSED') -> bool:
        """
        设置保证金模式

        Args:
            symbol: 交易对
            margin_type: 'CROSSED'=全仓, 'ISOLATED'=逐仓

        Returns:
            是否设置成功
        """
        try:
            self.client.futures_change_margin_type(
                symbol=symbol,
                marginType=margin_type
            )
            logger.info(f"{symbol}: 保证金模式已设置为 {margin_type}")
            return True
        except BinanceAPIException as e:
            # 如果已经是目标模式，会返回错误码-4046，视为成功
            if e.code == -4046:
                logger.info(f"{symbol}: 保证金模式已经是 {margin_type}")
                return True
            logger.error(f"设置保证金模式失败 {symbol}: {e}")
            return False
        except Exception as e:
            logger.error(f"设置保证金模式异常 {symbol}: {e}")
            return False

    def place_market_order(
        self,
        symbol: str,
        side: str,  # 'BUY' 或 'SELL'
        quantity: float,
        position_side: str = None,  # 'LONG' 或 'SHORT' (Hedge模式下必需)
        reduce_only: bool = False
    ) -> Optional[Dict]:
        """
        下达市价单 (支持Hedge模式)

        Args:
            symbol: 交易对
            side: 'BUY' 或 'SELL'
            quantity: 数量
            position_side: 'LONG' 或 'SHORT' (Hedge模式下必需)
            reduce_only: 是否仅减仓（非Hedge模式下使用）

        Returns:
            订单结果字典，失败返回 None
        """
        try:
            # 先调整数量精度
            adjusted_qty = self.adjust_quantity(symbol, quantity)
            if adjusted_qty is None:
                logger.error(f"{symbol}: 数量调整失败，无法下单")
                return None

            # 构建订单参数
            order_params = {
                'symbol': symbol,
                'side': side,
                'type': 'MARKET',
                'quantity': adjusted_qty
            }

            # 在Hedge模式下，必须指定positionSide
            if position_side:
                order_params['positionSide'] = position_side
            elif reduce_only:
                # 只在非Hedge模式下才使用reduceOnly
                order_params['reduceOnly'] = 'true'

            order = self.client.futures_create_order(**order_params)

            # 兼容处理时间戳字段
            timestamp = order.get('updateTime') or order.get('transactTime') or order.get('time', 0)

            result = {
                'order_id': order['orderId'],
                'symbol': order['symbol'],
                'side': order['side'],
                'quantity': float(order['origQty']),
                'filled': float(order['executedQty']),
                'status': order['status'],
                'timestamp': timestamp
            }

            logger.info(f"{symbol}: 市价单 {side} {adjusted_qty} @ 市价 (订单ID: {order['orderId']})")
            return result

        except BinanceOrderException as e:
            logger.error(f"下单被拒绝 {symbol}: {e}")
            return None
        except BinanceAPIException as e:
            logger.error(f"下单失败 {symbol}: {e}")
            return None
        except Exception as e:
            logger.error(f"下单异常 {symbol}: {e}")
            return None

    def cancel_order(self, symbol: str, order_id: int) -> bool:
        """取消订单"""
        try:
            self.client.futures_cancel_order(
                symbol=symbol,
                orderId=order_id
            )
            logger.info(f"{symbol}: 订单已取消 (订单ID: {order_id})")
            return True
        except BinanceAPIException as e:
            logger.error(f"取消订单失败: {e}")
            return False
        except Exception as e:
            logger.error(f"取消订单异常: {e}")
            return False

    # ==================== 持仓和账户 ====================
    @retry_on_error(max_retries=3, delay=0.5)
    def get_positions(self) -> List[Dict]:
        """获取当前持仓"""
        try:
            positions = self.client.futures_position_information()
            result = []

            for p in positions:
                pos_amt = float(p.get('positionAmt', 0))
                if pos_amt != 0:
                    notional = float(p.get('notional', 0))
                    unrealized_profit = float(p.get('unrealizedProfit', p.get('unRealizedProfit', 0)))

                    result.append({
                        'symbol': p['symbol'],
                        'quantity': abs(pos_amt),
                        'entry_price': float(p.get('entryPrice', 0)),
                        'mark_price': float(p.get('markPrice', 0)),
                        'side': 'LONG' if pos_amt > 0 else 'SHORT',
                        'position_side': p.get('positionSide', 'BOTH'),
                        'unrealized_profit': unrealized_profit,
                        'unrealized_profit_pct': (unrealized_profit / abs(notional) * 100) if notional != 0 else 0
                    })

            return result

        except BinanceAPIException as e:
            logger.error(f"获取持仓失败: {e}")
            return None  # 返回None而不是[]，让系统知道获取失败了
        except Exception as e:
            logger.error(f"获取持仓异常: {e}", exc_info=True)
            return None  # 返回None而不是[]

    def get_account_balance(self) -> Optional[float]:
        """获取账户总资产"""
        try:
            account = self.client.futures_account()
            balance = float(account['totalWalletBalance'])
            logger.info(f"账户余额: {balance:.2f} USDT")
            return balance
        except BinanceAPIException as e:
            logger.error(f"获取余额失败: {e}")
            return None
        except Exception as e:
            logger.error(f"获取余额异常: {e}")
            return None

    # ==================== 高级功能 ====================
    def set_stop_loss(
        self,
        symbol: str,
        quantity: float,
        stop_price: float,
        side: str = 'SELL',
        position_side: str = None
    ) -> Optional[int]:
        """设置止损单"""
        try:
            # 调整数量和价格精度
            adjusted_qty = self.adjust_quantity(symbol, quantity)
            adjusted_price = self.adjust_price(symbol, stop_price)

            if adjusted_qty is None or adjusted_price is None:
                logger.error(f"{symbol}: 止损单精度调整失败")
                return None

            order_params = {
                'symbol': symbol,
                'side': side,
                'type': 'STOP_MARKET',
                'quantity': adjusted_qty,
                'stopPrice': adjusted_price,
                'timeInForce': 'GTE_GTC'
            }

            if position_side:
                order_params['positionSide'] = position_side

            order = self.client.futures_create_order(**order_params)
            logger.info(f"{symbol}: 止损单已设置 @ {adjusted_price} qty={adjusted_qty} (订单ID: {order['orderId']})")
            return order['orderId']
        except BinanceAPIException as e:
            logger.error(f"设置止损失败 {symbol}: {e}")
            return None
        except Exception as e:
            logger.error(f"设置止损异常 {symbol}: {e}")
            return None

    def set_take_profit(
        self,
        symbol: str,
        quantity: float,
        stop_price: float,
        side: str = 'SELL',
        position_side: str = None
    ) -> Optional[int]:
        """设置止盈单"""
        try:
            # 调整数量和价格精度
            adjusted_qty = self.adjust_quantity(symbol, quantity)
            adjusted_price = self.adjust_price(symbol, stop_price)

            if adjusted_qty is None or adjusted_price is None:
                logger.error(f"{symbol}: 止盈单精度调整失败")
                return None

            order_params = {
                'symbol': symbol,
                'side': side,
                'type': 'TAKE_PROFIT_MARKET',
                'quantity': adjusted_qty,
                'stopPrice': adjusted_price,
                'timeInForce': 'GTE_GTC'
            }

            if position_side:
                order_params['positionSide'] = position_side

            order = self.client.futures_create_order(**order_params)
            logger.info(f"{symbol}: 止盈单已设置 @ {adjusted_price} qty={adjusted_qty} (订单ID: {order['orderId']})")
            return order['orderId']
        except BinanceAPIException as e:
            logger.error(f"设置止盈失败 {symbol}: {e}")
            return None
        except Exception as e:
            logger.error(f"设置止盈异常 {symbol}: {e}")
            return None

    def get_position_entry_time(self, symbol: str, side: str) -> Optional[float]:
        """
        获取持仓的开仓时间（通过查询最近成交记录推算）

        Args:
            symbol: 交易对
            side: 'LONG' 或 'SHORT'

        Returns:
            开仓时间戳(秒)，失败返回 None
        """
        try:
            # 获取最近的成交记录
            trades = self.client.futures_account_trades(symbol=symbol, limit=100)
            if not trades:
                return None

            # 按时间正序排列（从旧到新）
            trades.sort(key=lambda x: x['time'], reverse=False)

            # 确定开仓方向对应的买卖方向
            # LONG 持仓：买入开仓，卖出平仓
            # SHORT 持仓：卖出开仓，买入平仓
            open_side = 'BUY' if side == 'LONG' else 'SELL'

            # 追踪净持仓量，找到持仓从0变为非0的时间点
            net_qty = 0.0
            entry_time = None

            for trade in trades:
                trade_side = trade.get('side', '')
                position_side = trade.get('positionSide', 'BOTH')
                qty = float(trade.get('qty', 0))

                # 匹配持仓方向
                if position_side == side or position_side == 'BOTH':
                    if trade_side == open_side:
                        # 开仓交易
                        if net_qty == 0:
                            # 从零仓位开始建仓，记录开仓时间
                            entry_time = trade['time'] / 1000
                        net_qty += qty
                    else:
                        # 平仓交易
                        net_qty -= qty
                        if net_qty <= 0:
                            # 仓位已清零，重置开仓时间
                            net_qty = 0
                            entry_time = None

            return entry_time

        except Exception as e:
            logger.warning(f"获取开仓时间失败 {symbol}: {e}")
            return None

    # ==================== BTC数据 ====================
    def get_btc_indicators(self, interval: str = '15m', limit: int = 100) -> Optional[Tuple]:
        """获取BTC的K线数据用于分析（使用合约K线）"""
        try:
            klines = self.client.futures_klines(
                symbol='BTCUSDT',
                interval=interval,
                limit=limit
            )

            closes = [float(k[4]) for k in klines]
            highs = [float(k[2]) for k in klines]
            lows = [float(k[3]) for k in klines]
            volumes = [float(k[5]) for k in klines]

            return closes, highs, lows, volumes

        except BinanceAPIException as e:
            logger.error(f"获取BTC数据失败: {e}")
            return None
        except Exception as e:
            logger.error(f"获取BTC数据异常: {e}")
            return None

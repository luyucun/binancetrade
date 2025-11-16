"""
Binance API集成模板 (binance_client_v2.py)
实现与Binance API的实际连接，用于替换trading_engine_v2.py中的模拟方法

使用方式:
1. 在config_v2.py中设置API密钥
2. 在trading_engine_v2.py的__init__中添加:
   from binance_client_v2 import BinanceClientV2
   self.binance_client = BinanceClientV2(...)
3. 实现trading_engine_v2.py中的_fetch_*和_execute_*方法
"""

from binance.client import Client as BinanceClient
from binance.exceptions import BinanceAPIException, BinanceOrderException
from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class BinanceClientV2:
    """Binance API客户端包装 - 简化版实现"""

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

        try:
            self.client = BinanceClient(
                api_key=api_key,
                api_secret=api_secret,
                testnet=testnet
            )
            logger.info(f"Binance客户端已初始化 ({'测试网' if testnet else '实盘'})")
        except Exception as e:
            logger.error(f"Binance客户端初始化失败: {e}")
            raise

    # ==================== 币种和行情数据 ====================
    def get_top_coins_by_volume(self, limit: int = 60) -> List[Dict]:
        """获取交易量前N的USDT币种（仅TRADING状态）"""
        try:
            # 获取期货交易所信息以检查币种状态
            exchange_info = self.client.futures_exchange_info()
            trading_symbols = {
                s['symbol']: s['status']
                for s in exchange_info['symbols']
                if s['status'] == 'TRADING'
            }

            # 注意: get_ticker() 返回的是字典，需要转成列表
            tickers = self.client.get_ticker()

            # 如果返回的是单个字典，转换为列表
            if isinstance(tickers, dict):
                tickers = [tickers]

            # 只选择USDT对且状态为TRADING的币种
            usdt_coins = [
                t for t in tickers
                if t.get('symbol', '').endswith('USDT')
                and t.get('symbol', '') in trading_symbols
            ]

            # 按成交量排序
            sorted_coins = sorted(
                usdt_coins,
                key=lambda x: float(x.get('quoteAssetVolume', x.get('volume', 0))),
                reverse=True
            )[:limit]

            result = []
            for coin in sorted_coins:
                result.append({
                    'symbol': coin.get('symbol', 'UNKNOWN'),
                    'price': float(coin.get('lastPrice', coin.get('price', 0))),
                    'change_24h': float(coin.get('priceChangePercent', 0)),
                    'volume_24h': float(coin.get('quoteAssetVolume', coin.get('volume', 0))),
                    'volume': float(coin.get('volume', 0))
                })

            logger.info(f"获取了{len(result)}个USDT币种")
            return result

        except BinanceAPIException as e:
            logger.error(f"获取币种列表失败: {e}")
            return []
        except Exception as e:
            logger.error(f"获取币种列表异常: {e}")
            return []

    def get_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 500
    ) -> List[Dict]:
        """获取K线数据"""
        try:
            klines = self.client.get_klines(
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
                    'volume': float(k[7])
                })
            return result

        except BinanceAPIException as e:
            logger.error(f"获取K线失败 {symbol}: {e}")
            return []
        except Exception as e:
            logger.error(f"获取K线异常 {symbol}: {e}")
            return []

    def get_ticker(self, symbol: str) -> Optional[Dict]:
        """获取当前行情"""
        try:
            ticker = self.client.get_ticker(symbol=symbol)

            # 处理可能的字段名差异
            price = float(ticker.get('lastPrice') or ticker.get('price', 0))
            change_24h = float(ticker.get('priceChangePercent', 0))
            volume_24h = float(ticker.get('quoteAssetVolume', ticker.get('volume', 0)))

            return {
                'symbol': ticker.get('symbol', symbol),
                'price': price,
                'change_24h': change_24h,
                'volume_24h': volume_24h,
            }
        except BinanceAPIException as e:
            logger.warning(f"获取行情失败 {symbol}: {e}")
            return None
        except Exception as e:
            logger.warning(f"获取行情异常 {symbol}: {e}")
            return None

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
                    }

                    # 提取LOT_SIZE规则
                    for f in s['filters']:
                        if f['filterType'] == 'LOT_SIZE':
                            info['min_qty'] = float(f['minQty'])
                            info['max_qty'] = float(f['maxQty'])
                            info['step_size'] = float(f['stepSize'])
                        elif f['filterType'] == 'MIN_NOTIONAL':
                            info['min_notional'] = float(f['notional'])

                    self.symbol_info_cache[symbol] = info
                    return info

            logger.warning(f"未找到币种信息: {symbol}")
            return None

        except Exception as e:
            logger.error(f"获取币种信息失败 {symbol}: {e}")
            return None

    def adjust_quantity(self, symbol: str, quantity: float) -> Optional[float]:
        """根据交易规则调整数量精度"""
        info = self.get_symbol_info(symbol)
        if not info:
            return None

        # 检查币种状态
        if info.get('status') != 'TRADING':
            logger.error(f"{symbol}: 币种状态不是TRADING ({info.get('status')})")
            return None

        step_size = info.get('step_size', 1)
        min_qty = info.get('min_qty', 0)
        max_qty = info.get('max_qty', float('inf'))

        # 根据step_size调整精度
        # step_size决定了数量的最小变化单位
        from decimal import Decimal, ROUND_DOWN

        # 转换为Decimal进行精确计算
        quantity_decimal = Decimal(str(quantity))
        step_decimal = Decimal(str(step_size))

        # 向下取整到step_size的倍数
        adjusted = (quantity_decimal // step_decimal) * step_decimal
        adjusted_float = float(adjusted)

        # 检查范围
        if adjusted_float < min_qty:
            logger.warning(f"{symbol}: 调整后数量 {adjusted_float} < 最小值 {min_qty}")
            return None
        if adjusted_float > max_qty:
            logger.warning(f"{symbol}: 调整后数量 {adjusted_float} > 最大值 {max_qty}")
            return None

        logger.debug(f"{symbol}: 数量调整 {quantity} -> {adjusted_float} (step={step_size})")
        return adjusted_float

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
        reduce_only: bool = False,
        position_side: str = None  # 'LONG' 或 'SHORT' (Hedge模式下必需)
    ) -> Optional[Dict]:
        """下达市价单"""
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
            # 注意：在Hedge模式下，positionSide本身就隐含了是开仓还是平仓
            # 因此不需要也不能使用reduceOnly参数
            if position_side:
                order_params['positionSide'] = position_side
            else:
                # 只在非Hedge模式（单向持仓）下才使用reduceOnly
                if reduce_only:
                    order_params['reduceOnly'] = True

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
    def get_positions(self) -> List[Dict]:
        """获取当前持仓"""
        try:
            positions = self.client.futures_position_information()
            result = []

            for p in positions:
                if float(p['positionAmt']) != 0:
                    result.append({
                        'symbol': p['symbol'],
                        'quantity': float(p['positionAmt']),
                        'entry_price': float(p['entryPrice']),
                        'mark_price': float(p['markPrice']),
                        'side': 'LONG' if float(p['positionAmt']) > 0 else 'SHORT',
                        'unrealized_profit': float(p['unrealizedProfit']),
                        'unrealized_profit_pct': float(p['unrealizedProfit']) / (float(p['notional']) or 1) * 100
                    })

            return result

        except BinanceAPIException as e:
            logger.error(f"获取持仓失败: {e}")
            return []
        except Exception as e:
            logger.error(f"获取持仓异常: {e}")
            return []

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
        side: str = 'SELL'
    ) -> Optional[int]:
        """设置止损单"""
        try:
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type='STOP_MARKET',
                quantity=quantity,
                stopPrice=stop_price,
                timeInForce='GTE_GTC'
            )
            logger.info(f"{symbol}: 止损单已设置 @ {stop_price} (订单ID: {order['orderId']})")
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
        side: str = 'SELL'
    ) -> Optional[int]:
        """设置止盈单"""
        try:
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type='TAKE_PROFIT_MARKET',
                quantity=quantity,
                stopPrice=stop_price,
                timeInForce='GTE_GTC'
            )
            logger.info(f"{symbol}: 止盈单已设置 @ {stop_price} (订单ID: {order['orderId']})")
            return order['orderId']
        except BinanceAPIException as e:
            logger.error(f"设置止盈失败 {symbol}: {e}")
            return None
        except Exception as e:
            logger.error(f"设置止盈异常 {symbol}: {e}")
            return None

    # ==================== BTC数据 ====================
    def get_btc_indicators(self, interval: str = '15m', limit: int = 100) -> Optional[Tuple]:
        """获取BTC的K线数据用于分析"""
        try:
            klines = self.client.get_klines(
                symbol='BTCUSDT',
                interval=interval,
                limit=limit
            )

            closes = [float(k[4]) for k in klines]
            highs = [float(k[2]) for k in klines]
            lows = [float(k[3]) for k in klines]
            volumes = [float(k[7]) for k in klines]

            return closes, highs, lows, volumes

        except BinanceAPIException as e:
            logger.error(f"获取BTC数据失败: {e}")
            return None
        except Exception as e:
            logger.error(f"获取BTC数据异常: {e}")
            return None

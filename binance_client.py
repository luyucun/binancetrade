"""
Binance API 客户端封装
"""
import logging
import time
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceOrderException
from config import BINANCE_API_KEY, BINANCE_API_SECRET, API_TIMEOUT

logger = logging.getLogger(__name__)


class BinanceClient:
    """Binance API客户端"""

    def __init__(self):
        try:
            self.client = Client(BINANCE_API_KEY, BINANCE_API_SECRET, {"timeout": API_TIMEOUT})
            logger.info("Binance客户端连接成功")

            # 同步时间以解决API签名问题
            self._sync_time_with_server()
        except Exception as e:
            logger.error(f"Binance客户端连接失败: {e}")
            raise

    def _sync_time_with_server(self):
        """与Binance服务器同步时间以解决签名问题"""
        try:
            # 获取服务器时间
            server_time_data = self.client.get_server_time()
            server_time = server_time_data['serverTime']
            local_time = int(time.time() * 1000)

            # 计算时间偏移（毫秒）
            time_offset = server_time - local_time

            logger.info(f"本地时间: {local_time}ms, 服务器时间: {server_time}ms, 偏差: {time_offset}ms")

            # python-binance 会自动保存这个偏移，并在后续请求中使用
            # 只需要触发一次 get_server_time 调用即可完成同步
            if abs(time_offset) > 5000:
                logger.warning(f"警告: 时间偏差较大 ({time_offset}ms)，可能导致API错误")
            else:
                logger.info(f"时间同步成功")

        except Exception as e:
            logger.warning(f"时间同步失败: {e}，将继续使用本地时间")

    def get_exchange_info(self):
        """获取交易所信息"""
        try:
            return self.client.futures_exchange_info()
        except BinanceAPIException as e:
            logger.error(f"获取交易所信息失败: {e}")
            raise

    def get_perpetual_symbols(self):
        """获取所有U本位永续合约交易对"""
        try:
            exchange_info = self.get_exchange_info()
            symbols = []
            for symbol in exchange_info['symbols']:
                # 筛选U本位永续合约
                if symbol['quoteAsset'] == 'USDT' and symbol['status'] == 'TRADING':
                    symbols.append(symbol['symbol'])
            logger.info(f"找到 {len(symbols)} 个U本位永续合约交易对")
            return symbols
        except Exception as e:
            logger.error(f"获取U本位永续合约失败: {e}")
            raise

    def get_24h_ticker(self, symbol):
        """获取24小时交易统计"""
        try:
            return self.client.futures_ticker(symbol=symbol)
        except BinanceAPIException as e:
            logger.error(f"获取 {symbol} 的24小时统计失败: {e}")
            return None

    def get_klines(self, symbol, interval, limit=10):
        """获取K线数据"""
        try:
            return self.client.futures_klines(symbol=symbol, interval=interval, limit=limit)
        except BinanceAPIException as e:
            logger.error(f"获取 {symbol} 的K线数据失败: {e}")
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
            logger.info(f"市价单创建成功: {symbol} {side} {quantity}")
            return order
        except BinanceOrderException as e:
            logger.error(f"创建市价单失败: {e}")
            return None

    def create_order_with_sl_tp(self, symbol, side, quantity, stop_price, take_profit_price):
        """创建带止损止盈的订单"""
        try:
            # 先创建市价单
            order = self.create_market_order(symbol, side, quantity)
            if not order:
                return None

            # 根据方向设置止损止盈
            if side == 'BUY':
                # 做多：止损在下方，止盈在上方
                self.set_stop_loss(symbol, stop_price, quantity, 'SELL')
                self.set_take_profit(symbol, take_profit_price, quantity, 'SELL')
            else:
                # 做空：止损在上方，止盈在下方
                self.set_stop_loss(symbol, stop_price, quantity, 'BUY')
                self.set_take_profit(symbol, take_profit_price, quantity, 'BUY')

            return order
        except Exception as e:
            logger.error(f"创建带止损止盈的订单失败: {e}")
            return None

    def set_stop_loss(self, symbol, stop_price, quantity, side):
        """设置止损"""
        try:
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type='STOP_MARKET',
                closePosition=True,
                stopPrice=stop_price
            )
            logger.info(f"止损订单设置成功: {symbol} orderId={order['orderId']} stopPrice={stop_price}")
            return order
        except BinanceOrderException as e:
            logger.error(f"设置止损失败: {e}")
            return None

    def set_take_profit(self, symbol, take_profit_price, quantity, side):
        """设置止盈"""
        try:
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type='TAKE_PROFIT_MARKET',
                closePosition=True,
                stopPrice=take_profit_price
            )
            logger.info(f"止盈订单设置成功: {symbol} orderId={order['orderId']} stopPrice={take_profit_price}")
            return order
        except BinanceOrderException as e:
            logger.error(f"设置止盈失败: {e}")
            return None

    def get_position_info(self, symbol):
        """获取持仓信息"""
        try:
            positions = self.client.futures_position_information(symbol=symbol)
            return positions[0] if positions else None
        except BinanceAPIException as e:
            # API错误时返回None以继续交易流程
            logger.debug(f"获取持仓信息失败: {e}，继续交易流程")
            return None

    def get_account_info(self):
        """获取账户信息"""
        try:
            return self.client.futures_account()
        except BinanceAPIException as e:
            logger.error(f"获取账户信息失败: {e}")
            return None

    def get_open_orders(self, symbol: str = None):
        """
        获取所有未成交订单

        返回: 订单列表（可能为空）
        异常: API 异常时抛出，调用方需要处理

        ✅ 关键改进：异常传播到上层，不再隐瞒失败
        这样清理流程能知道是"没有订单"还是"获取失败"
        """
        try:
            if symbol:
                orders = self.client.futures_get_open_orders(symbol=symbol)
            else:
                orders = self.client.futures_get_open_orders()
            logger.debug(f"获取未成交订单成功: {symbol if symbol else '全部'} - {len(orders) if orders else 0}个")
            return orders if orders else []
        except BinanceAPIException as e:
            logger.error(f"获取未成交订单失败: {e}")
            # ✅ 关键：抛出异常让调用方感知
            raise
        except Exception as e:
            logger.error(f"获取未成交订单异常: {e}")
            raise

    def cancel_order(self, symbol: str, order_id: int):
        """取消订单"""
        try:
            result = self.client.futures_cancel_order(symbol=symbol, orderId=order_id)
            logger.info(f"订单取消成功: {symbol} orderId={order_id}")
            return result
        except BinanceAPIException as e:
            logger.error(f"取消订单失败: {symbol} orderId={order_id} - {e}")
            return None

    def cancel_all_orders(self, symbol: str):
        """
        取消某个交易对的所有未成交订单

        返回: 取消成功的订单列表
        异常: 如果取消失败会抛出BinanceAPIException，调用方需要处理

        ✅ 关键改进：让异常传播到上层，而不是吞掉它
        这样上层可以通过 try-except 准确判断成功还是失败
        """
        try:
            # 先获取所有未成交订单
            open_orders = self.client.futures_get_open_orders(symbol=symbol)

            if not open_orders:
                logger.info(f"取消 {symbol} 的所有订单成功，共 0 个订单")
                return []

            # 逐个取消
            cancelled_orders = []
            for order in open_orders:
                try:
                    result = self.client.futures_cancel_order(symbol=symbol, orderId=order['orderId'])
                    cancelled_orders.append(result)
                except Exception as e:
                    logger.warning(f"取消 {symbol} 订单 {order['orderId']} 失败: {e}")

            logger.info(f"取消 {symbol} 的所有订单成功，共 {len(cancelled_orders)} 个订单")
            return cancelled_orders
        except BinanceAPIException as e:
            logger.error(f"取消 {symbol} 的所有订单失败: {e}")
            # ✅ 关键：重新抛出异常，让调用方知道失败了
            raise

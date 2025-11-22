"""
🚀 市场数据管理器 (market_data_manager.py)
WebSocket实时数据流管理，替代HTTP轮询获取市场数据

核心功能：
1. 管理WebSocket连接（价格流和K线流）
2. 实时更新本地数据缓存
3. 提供零延迟的数据访问接口
4. 自动重连和异常处理
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional, Callable, Set
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from collections import defaultdict, deque
import websockets
from threading import Lock

from config_v2 import API_CONFIG

logger = logging.getLogger(__name__)


@dataclass
class TickerData:
    """实时价格数据"""
    symbol: str
    price: float
    timestamp: datetime
    volume_24h: float = 0.0
    change_24h: float = 0.0


@dataclass
class KlineData:
    """K线数据"""
    symbol: str
    interval: str
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_closed: bool  # 是否为已完成的K线


class MarketDataManager:
    """
    🚀 市场数据管理器 - WebSocket实时数据流

    替代原有的HTTP轮询方式，实现：
    - 实时价格订阅
    - 多时间周期K线订阅
    - 本地数据缓存
    - 零延迟数据访问
    """

    def __init__(self, testnet: bool = False):
        """
        初始化市场数据管理器

        Args:
            testnet: 是否使用测试网
        """
        self.testnet = testnet
        self.base_ws_url = "wss://stream.binance.com:9443/ws/" if not testnet else "wss://testnet.binance.vision/ws/"

        # 数据缓存
        self._prices: Dict[str, TickerData] = {}  # 实时价格
        self._klines: Dict[str, Dict[str, deque]] = defaultdict(lambda: defaultdict(lambda: deque(maxlen=100)))  # K线数据

        # 线程安全锁
        self._price_lock = Lock()
        self._kline_lock = Lock()

        # WebSocket连接管理
        self._price_ws: Optional[websockets.WebSocketServerProtocol] = None
        self._kline_main_ws = None  # 主要的K线连接（修复：避免URL过长）

        # 订阅管理
        self._subscribed_symbols: Set[str] = set()
        self._subscribed_intervals = ['1m', '3m', '5m', '15m']

        # 连接状态
        self._is_running = False
        self._reconnect_interval = 5  # 重连间隔(秒)

        # 回调函数
        self._price_callbacks: List[Callable] = []
        self._kline_callbacks: List[Callable] = []

        logger.info("市场数据管理器已初始化")

    async def start(self, symbols: List[str]):
        """
        启动WebSocket连接

        Args:
            symbols: 要订阅的币种列表 ['BTCUSDT', 'ETHUSDT', ...]
        """
        self._is_running = True
        self._subscribed_symbols = set(symbols)

        logger.info(f"启动市场数据管理器，订阅 {len(symbols)} 个币种")

        # 启动价格流和K线流
        await asyncio.gather(
            self._start_price_stream(),
            self._start_kline_stream(),
            return_exceptions=True
        )

    async def stop(self):
        """停止WebSocket连接"""
        self._is_running = False

        if self._price_ws:
            await self._price_ws.close()

        if self._kline_main_ws:
            await self._kline_main_ws.close()

        logger.info("市场数据管理器已停止")

    # ==================== WebSocket连接管理 ====================
    async def _start_price_stream(self):
        """启动实时价格流"""
        while self._is_running:
            try:
                # 构建价格流订阅URL (所有币种的ticker)
                stream_url = f"{self.base_ws_url}!ticker@arr"

                logger.info(f"连接价格流: {stream_url}")

                async with websockets.connect(stream_url) as ws:
                    self._price_ws = ws
                    logger.info("✓ 价格流连接成功")

                    async for message in ws:
                        if not self._is_running:
                            break

                        try:
                            data = json.loads(message)
                            await self._handle_price_message(data)
                        except Exception as e:
                            logger.warning(f"处理价格消息失败: {e}")

            except Exception as e:
                logger.error(f"价格流连接失败: {e}")
                if self._is_running:
                    logger.info(f"{self._reconnect_interval}秒后重连价格流...")
                    await asyncio.sleep(self._reconnect_interval)

    async def _start_kline_stream(self):
        """🔧 启动K线数据流 (修复版：使用 SUBSCRIBE 模式避免 URL 过长)"""
        while self._is_running:
            try:
                # 1. 连接 Combined Stream 基础端点
                # 注意：使用 /stream 而不是 /ws，这样返回的数据带 stream 名称，方便区分
                stream_url = "wss://stream.binance.com:9443/stream" if not self.testnet else "wss://testnet.binance.vision/stream"
                logger.info(f"连接K线流服务器: {stream_url}")

                async with websockets.connect(stream_url) as ws:
                    # 记录连接对象
                    self._kline_main_ws = ws

                    logger.info("✓ K线流服务器连接成功，开始发送订阅请求...")

                    # 2. 构建订阅参数列表
                    params = []
                    for symbol in self._subscribed_symbols:
                        for interval in self._subscribed_intervals:
                            params.append(f"{symbol.lower()}@kline_{interval}")

                    logger.info(f"准备订阅 {len(params)} 个数据流 ({len(self._subscribed_symbols)} 个币种 × {len(self._subscribed_intervals)} 个周期)")

                    # 3. 分批发送订阅请求 (Binance 建议每条消息不超过 1024 个流，稳妥起见每批 50 个)
                    batch_size = 50
                    for i in range(0, len(params), batch_size):
                        batch = params[i:i+batch_size]
                        payload = {
                            "method": "SUBSCRIBE",
                            "params": batch,
                            "id": i + 1
                        }
                        await ws.send(json.dumps(payload))
                        logger.info(f"✓ 已发送第 {i//batch_size + 1} 批订阅请求 ({len(batch)} 个流)")
                        # 稍微停顿，防止触发请求频次限制
                        await asyncio.sleep(0.3)

                    logger.info("📡 所有K线流订阅完成，开始监听数据...")

                    # 4. 监听消息
                    async for message in ws:
                        if not self._is_running:
                            break
                        try:
                            data = json.loads(message)
                            # Combined Stream 返回格式: {"stream": "...", "data": {...}}
                            # 需要适配处理逻辑
                            if 'data' in data:
                                await self._handle_kline_message(data['data'])
                            elif 'result' in data:
                                # 忽略订阅成功的响应消息 {"result": null, "id": ...}
                                logger.debug(f"收到订阅响应: {data}")
                            else:
                                logger.debug(f"收到未知消息格式: {data}")
                        except Exception as e:
                            logger.warning(f"处理K线消息失败: {e}")

            except Exception as e:
                logger.error(f"K线流连接失败: {e}")
                if self._is_running:
                    logger.info(f"{self._reconnect_interval}秒后重连K线流...")
                    await asyncio.sleep(self._reconnect_interval)

    # ==================== 消息处理 ====================
    async def _handle_price_message(self, data):
        """处理价格消息"""
        try:
            # Binance ticker数组格式
            if isinstance(data, list):
                with self._price_lock:
                    for ticker in data:
                        if ticker['s'] in self._subscribed_symbols:
                            self._prices[ticker['s']] = TickerData(
                                symbol=ticker['s'],
                                price=float(ticker['c']),  # 最新价格
                                timestamp=datetime.now(),
                                volume_24h=float(ticker['q']),  # 24h成交额
                                change_24h=float(ticker['P'])   # 24h涨跌幅
                            )

            # 触发价格回调
            for callback in self._price_callbacks:
                try:
                    await callback(data)
                except Exception as e:
                    logger.warning(f"价格回调执行失败: {e}")

        except Exception as e:
            logger.warning(f"处理价格消息异常: {e}")

    async def _handle_kline_message(self, data):
        """处理K线消息"""
        try:
            if 'k' in data:  # K线数据
                kline = data['k']
                symbol = kline['s']
                interval = kline['i']

                if symbol in self._subscribed_symbols:
                    kline_data = KlineData(
                        symbol=symbol,
                        interval=interval,
                        open_time=datetime.fromtimestamp(kline['t'] / 1000),
                        close_time=datetime.fromtimestamp(kline['T'] / 1000),
                        open=float(kline['o']),
                        high=float(kline['h']),
                        low=float(kline['l']),
                        close=float(kline['c']),
                        volume=float(kline['v']),
                        is_closed=kline['x']  # 是否已闭合
                    )

                    with self._kline_lock:
                        # 更新K线缓存
                        if kline_data.is_closed:
                            # 已闭合的K线，添加到历史数据
                            self._klines[symbol][interval].append(kline_data)
                        else:
                            # 未闭合的K线，更新最新数据
                            if self._klines[symbol][interval] and not self._klines[symbol][interval][-1].is_closed:
                                # 替换最后一个未闭合的K线
                                self._klines[symbol][interval][-1] = kline_data
                            else:
                                # 添加新的未闭合K线
                                self._klines[symbol][interval].append(kline_data)

            # 触发K线回调
            for callback in self._kline_callbacks:
                try:
                    await callback(data)
                except Exception as e:
                    logger.warning(f"K线回调执行失败: {e}")

        except Exception as e:
            logger.warning(f"处理K线消息异常: {e}")

    # ==================== 数据访问接口 ====================
    def get_current_price(self, symbol: str) -> Optional[float]:
        """
        🚀 零延迟获取当前价格

        Args:
            symbol: 币种符号

        Returns:
            当前价格，None表示数据不可用
        """
        with self._price_lock:
            ticker = self._prices.get(symbol)
            return ticker.price if ticker else None

    def get_all_prices(self) -> Dict[str, float]:
        """
        🚀 零延迟获取所有价格

        Returns:
            {symbol: price} 字典
        """
        with self._price_lock:
            return {symbol: ticker.price for symbol, ticker in self._prices.items()}

    def get_klines(self, symbol: str, interval: str, limit: int = 50) -> List[Dict]:
        """
        🚀 零延迟获取K线数据

        Args:
            symbol: 币种符号
            interval: 时间周期
            limit: 获取数量

        Returns:
            K线数据列表，格式兼容原有API
        """
        with self._kline_lock:
            klines = list(self._klines[symbol][interval])[-limit:]

            # 转换为原有格式
            result = []
            for kline in klines:
                result.append({
                    'open_time': int(kline.open_time.timestamp() * 1000),
                    'open': kline.open,
                    'high': kline.high,
                    'low': kline.low,
                    'close': kline.close,
                    'volume': kline.volume,
                    'close_time': int(kline.close_time.timestamp() * 1000),
                })

            return result

    def get_ticker_24h(self, symbol: str) -> Optional[Dict]:
        """获取24h行情数据"""
        with self._price_lock:
            ticker = self._prices.get(symbol)
            if ticker:
                return {
                    'symbol': ticker.symbol,
                    'price': ticker.price,
                    'volume_24h': ticker.volume_24h,
                    'change_24h': ticker.change_24h,
                    'timestamp': ticker.timestamp
                }
            return None

    # ==================== 订阅管理 ====================
    def subscribe_symbol(self, symbol: str):
        """添加币种订阅"""
        if symbol not in self._subscribed_symbols:
            self._subscribed_symbols.add(symbol)
            logger.info(f"添加币种订阅: {symbol}")

    def unsubscribe_symbol(self, symbol: str):
        """取消币种订阅"""
        if symbol in self._subscribed_symbols:
            self._subscribed_symbols.remove(symbol)
            logger.info(f"取消币种订阅: {symbol}")

    def add_price_callback(self, callback: Callable):
        """添加价格回调函数"""
        self._price_callbacks.append(callback)

    def add_kline_callback(self, callback: Callable):
        """添加K线回调函数"""
        self._kline_callbacks.append(callback)

    # ==================== 状态和统计 ====================
    def get_connection_status(self) -> Dict[str, bool]:
        """获取连接状态"""
        return {
            'price_stream': self._price_ws is not None and not self._price_ws.closed,
            'kline_stream': self._kline_main_ws is not None and not self._kline_main_ws.closed,
            'is_running': self._is_running
        }

    def get_data_stats(self) -> Dict:
        """获取数据统计"""
        with self._price_lock:
            price_count = len(self._prices)

        with self._kline_lock:
            kline_count = sum(len(intervals) for intervals in self._klines.values())

        return {
            'subscribed_symbols': len(self._subscribed_symbols),
            'cached_prices': price_count,
            'cached_klines': kline_count,
            'intervals': self._subscribed_intervals,
            'last_update': datetime.now()
        }
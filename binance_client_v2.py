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
from typing import Dict, List, Optional, Tuple, Callable, Any
import logging
import time
import random
import asyncio

from config_v2 import API_CONFIG
from network_monitor import get_network_monitor, NetworkStatus

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
        self.max_retries = API_CONFIG.get('max_retries', 3)
        self.timeout = API_CONFIG.get('timeout', 30)
        self.retry_base_delay = API_CONFIG.get('retry_base_delay', 0.5)
        self.retry_max_delay = API_CONFIG.get('retry_max_delay', 5.0)

        # 时间同步
        self.time_offset = 0  # 与服务器的时间偏移
        self.last_time_sync = 0  # 上次同步时间

        # 🔧 网络监控集成
        self.network_monitor = get_network_monitor()

        # 🔧 API调用统计
        self._api_call_stats = {
            'total_calls': 0,
            'failed_calls': 0,
            'last_reset_time': time.time()
        }

        # 🔧 降级模式配置
        self._degraded_mode = False
        self._max_concurrent_requests = 10
        self._current_concurrent_requests = 0
        self._request_semaphore = asyncio.Semaphore(self._max_concurrent_requests)

        try:
            # 🚀 简化的网络优化配置
            # 🔧 支持代理配置
            requests_params = {'timeout': self.timeout}

            # 如果配置了代理，添加代理参数
            if API_CONFIG.get('use_proxy', False):
                proxy_config = API_CONFIG.get('proxy', {})
                requests_params['proxies'] = proxy_config
                logger.info(f"使用代理连接Binance: {proxy_config.get('https', 'N/A')}")

            self.client = BinanceClient(
                api_key=api_key,
                api_secret=api_secret,
                testnet=testnet,
                requests_params=requests_params
            )

            # 🔧 启动时进行时钟校准
            self._sync_server_time()

            # 应用连接池优化（如果可能）
            try:
                import requests
                from urllib3.util.retry import Retry
                from requests.adapters import HTTPAdapter

                # 检查client是否有session属性（某些版本的python-binance有）
                if hasattr(self.client, 'session'):
                    # 配置重试策略
                    retry_strategy = Retry(
                        total=3,
                        backoff_factor=0.5,
                        status_forcelist=[429, 500, 502, 503, 504],
                        allowed_methods=["HEAD", "GET", "PUT", "DELETE", "OPTIONS", "TRACE", "POST"]
                    )

                    # 配置HTTP适配器，优化连接池
                    adapter = HTTPAdapter(
                        pool_connections=100,
                        pool_maxsize=100,
                        max_retries=retry_strategy
                    )

                    self.client.session.mount("http://", adapter)
                    self.client.session.mount("https://", adapter)
                    self.client.session.headers.update({
                        'Connection': 'keep-alive',
                        'User-Agent': 'binance-trading-bot/1.0'
                    })
                    logger.info("✓ Binance客户端已初始化（应用连接池优化）")
                else:
                    logger.info("✓ Binance客户端已初始化（使用默认连接配置）")
            except Exception as optimize_error:
                logger.warning(f"连接池优化失败，使用默认配置: {optimize_error}")
                logger.info("✓ Binance客户端已初始化（使用默认连接配置）")

            # 初始化时同步时间
            self._sync_server_time()

        except Exception as e:
            logger.error(f"Binance客户端初始化失败: {e}")
            raise

    def _execute_with_retry(
        self,
        func: Callable,
        *args,
        max_retries: Optional[int] = None,
        call_type: str = "normal",
        **kwargs
    ) -> Any:
        """
        带重试机制的API调用包装器（网络感知 + 指数退避 + 抖动）

        Args:
            func: 要执行的函数
            max_retries: 最大重试次数（None则使用默认值）
            call_type: 调用类型 ("essential", "normal", "optional")
            *args, **kwargs: 传递给func的参数

        Returns:
            函数执行结果
        """
        # 🔧 网络感知检查
        should_skip, skip_reason = self.network_monitor.should_skip_api_call(call_type)
        if should_skip:
            logger.debug(f"网络监控建议跳过API调用 {func.__name__}: {skip_reason}")
            if call_type == "optional":
                return None  # 可选调用直接返回None
            # 必要调用继续执行但使用更严格的参数

        # 🔧 动态调整参数
        max_retries = max_retries or self._get_adaptive_max_retries()
        dynamic_timeout = self.network_monitor.get_recommended_timeout(self.timeout)

        # 🔧 更新超时时间
        if hasattr(self.client, 'session') and hasattr(self.client.session, 'timeout'):
            # 临时调整session超时
            original_timeout = self.client.session.timeout
            self.client.session.timeout = dynamic_timeout

        last_exception = None
        self._api_call_stats['total_calls'] += 1

        for attempt in range(max_retries + 1):
            try:
                # 🔧 并发控制
                if self._degraded_mode:
                    # 降级模式下控制并发
                    if self._current_concurrent_requests >= self._max_concurrent_requests // 2:
                        time.sleep(0.1)  # 短暂等待

                self._current_concurrent_requests += 1
                start_time = time.time()

                try:
                    result = func(*args, **kwargs)

                    # 记录成功
                    call_duration = (time.time() - start_time) * 1000
                    self._record_api_success(call_duration)

                    return result

                finally:
                    self._current_concurrent_requests -= 1

            except (BinanceAPIException, Exception) as e:
                last_exception = e
                self._api_call_stats['failed_calls'] += 1

                # 🔧 网络错误分类处理
                error_type = self._classify_error(e)

                # 记录失败
                self._record_api_failure(str(e), error_type)

                # 检查是否应该重试
                is_retryable = self._is_retryable_error(e, error_type)

                if not is_retryable or attempt >= max_retries:
                    # 不可重试的错误或已达最大重试次数
                    logger.error(f"API调用失败 {func.__name__} (尝试{attempt+1}/{max_retries+1}): {e}")
                    raise

                # 🔧 智能退避策略
                delay = self._calculate_backoff_delay(attempt, error_type)

                logger.warning(f"API调用失败 {func.__name__} (尝试{attempt+1}/{max_retries+1}): {e}, {delay:.1f}秒后重试")
                time.sleep(delay)

                # 🔧 在重试前检查网络状态
                if error_type in ['network', 'timeout'] and attempt < max_retries:
                    # 如果是网络错误，快速检查网络状态
                    if self.network_monitor.metrics.status == NetworkStatus.DISCONNECTED:
                        logger.error(f"网络断连状态，停止重试 {func.__name__}")
                        break

        # 所有重试都失败
        raise last_exception

    def _get_adaptive_max_retries(self) -> int:
        """根据网络状态获取自适应的最大重试次数"""
        network_status = self.network_monitor.metrics.status

        if network_status == NetworkStatus.DISCONNECTED:
            return 1  # 断连时减少重试
        elif network_status == NetworkStatus.UNSTABLE:
            return max(1, self.max_retries // 2)  # 不稳定时适当减少
        elif network_status == NetworkStatus.DEGRADED:
            return self.max_retries  # 降级时使用默认值
        else:
            return self.max_retries  # 正常时使用默认值

    def _classify_error(self, error: Exception) -> str:
        """
        分类错误类型

        Returns:
            错误类型: "network", "timeout", "api_limit", "auth", "market", "other"
        """
        error_str = str(error).lower()

        # 网络相关错误
        if any(keyword in error_str for keyword in [
            'timeout', 'timed out', 'connection', 'network', 'unreachable',
            'connection reset', 'connection refused', 'name resolution failed'
        ]):
            return 'network'

        # 超时错误
        if 'timeout' in error_str or 'timed out' in error_str:
            return 'timeout'

        # API限流
        if isinstance(error, BinanceAPIException):
            if error.code in [-1003, -1015, 429]:
                return 'api_limit'
            elif error.code in [-1021, -1022]:  # 时间同步问题
                return 'time_sync'
            elif error.code in [-2010, -2011]:  # 认证问题
                return 'auth'
            elif error.code in [-1013, -1121]:  # 市场/交易相关
                return 'market'

        return 'other'

    def _is_retryable_error(self, error: Exception, error_type: str) -> bool:
        """判断错误是否可以重试"""

        # 网络和超时错误总是可以重试
        if error_type in ['network', 'timeout', 'api_limit', 'time_sync']:
            return True

        # 认证错误不重试
        if error_type == 'auth':
            return False

        # 市场错误根据具体情况判断
        if error_type == 'market':
            if isinstance(error, BinanceAPIException):
                # 无效交易对等不重试
                if error.code in [-1121, -1013]:
                    return False
                # 其他市场错误可以重试
                return True

        # 其他类型的BinanceAPIException可以重试
        if isinstance(error, BinanceAPIException):
            return True

        # 通用异常按内容判断
        error_str = str(error).lower()
        retryable_keywords = ['timeout', 'connection', 'temporary', 'server error']
        return any(keyword in error_str for keyword in retryable_keywords)

    def _calculate_backoff_delay(self, attempt: int, error_type: str) -> float:
        """
        计算退避延迟时间

        Args:
            attempt: 尝试次数（从0开始）
            error_type: 错误类型

        Returns:
            延迟时间（秒）
        """
        base_delay = self.retry_base_delay

        # 根据错误类型调整基础延迟
        if error_type == 'api_limit':
            base_delay = max(2.0, self.retry_base_delay * 4)  # API限流时延长等待
        elif error_type == 'network':
            base_delay = max(1.0, self.retry_base_delay * 2)  # 网络错误适当延长
        elif error_type == 'timeout':
            base_delay = max(0.5, self.retry_base_delay * 1.5)  # 超时错误略微延长

        # 指数退避
        exponential_delay = base_delay * (2 ** attempt)

        # 添加随机抖动（20%的变化）
        jitter = random.uniform(-0.2, 0.2) * exponential_delay

        # 限制最大延迟
        final_delay = min(exponential_delay + jitter, self.retry_max_delay)

        return max(0.1, final_delay)  # 确保最小延迟

    def _record_api_success(self, duration_ms: float):
        """记录API调用成功"""
        # 这里可以集成到网络监控中
        # 目前简单记录到内部统计
        pass

    def _record_api_failure(self, error_msg: str, error_type: str):
        """记录API调用失败"""
        # 🔧 网络错误时触发降级模式
        if error_type in ['network', 'timeout'] and not self._degraded_mode:
            failure_rate = self._api_call_stats['failed_calls'] / max(1, self._api_call_stats['total_calls'])
            if failure_rate > 0.3:  # 失败率超过30%时启用降级模式
                self._enable_degraded_mode()

    def _enable_degraded_mode(self):
        """启用降级模式"""
        if not self._degraded_mode:
            self._degraded_mode = True
            self._max_concurrent_requests = max(1, self._max_concurrent_requests // 2)
            logger.warning(f"🔧 启用降级模式: 限制并发请求数至{self._max_concurrent_requests}")

    def _disable_degraded_mode(self):
        """禁用降级模式"""
        if self._degraded_mode:
            self._degraded_mode = False
            self._max_concurrent_requests = 10  # 恢复默认值
            logger.info("✅ 禁用降级模式: 恢复正常并发请求数")

    def reset_api_stats(self):
        """重置API调用统计"""
        self._api_call_stats = {
            'total_calls': 0,
            'failed_calls': 0,
            'last_reset_time': time.time()
        }
        self._disable_degraded_mode()

    def get_api_stats(self) -> Dict:
        """获取API调用统计"""
        runtime = time.time() - self._api_call_stats['last_reset_time']
        total_calls = self._api_call_stats['total_calls']

        return {
            'total_calls': total_calls,
            'failed_calls': self._api_call_stats['failed_calls'],
            'success_rate': (total_calls - self._api_call_stats['failed_calls']) / max(1, total_calls),
            'calls_per_minute': total_calls / max(1, runtime / 60),
            'degraded_mode': self._degraded_mode,
            'max_concurrent': self._max_concurrent_requests,
            'current_concurrent': self._current_concurrent_requests
        }

    def _is_valid_futures_symbol(self, symbol: str) -> bool:
        """检查是否为有效的期货交易对"""
        try:
            # 如果没有缓存，先获取
            if not hasattr(self, '_valid_symbols_cache'):
                self._valid_symbols_cache = set(self.get_valid_futures_symbols())

            return symbol in self._valid_symbols_cache
        except Exception:
            # 如果获取失败，使用硬编码的黑名单过滤
            known_invalid_symbols = {
                'HYPEUSDT', 'PIEVERSEUSDT', 'SOONUSDT', 'BEATUSDT',
                'FARTCOINUSDT', 'CROSSUSDT', 'UAIUSDT'
            }
            return symbol not in known_invalid_symbols

    # ==================== 币种和行情数据 ====================
    def get_top_coins_by_volume(self, limit: int = 60, min_volume_usdt: float = 50000000) -> List[Dict]:
        """
        获取交易量前N的USDT币种（仅TRADING状态）

        Args:
            limit: 返回前N个币种（默认60）
            min_volume_usdt: 最小24小时交易量（USDT，默认5000万）

        Returns:
            满足条件的前N个币种列表
        """
        def _fetch():
            # 获取期货交易所信息以检查币种状态
            exchange_info = self.client.futures_exchange_info()
            trading_symbols = {
                s['symbol']: s['status']
                for s in exchange_info['symbols']
                if s['status'] == 'TRADING'
            }

            # 使用期货ticker数据（24小时统计数据）
            tickers = self.client.futures_ticker()

            # 如果返回的是单个字典，转换为列表
            if isinstance(tickers, dict):
                tickers = [tickers]

            # 只选择USDT对且状态为TRADING的币种
            usdt_coins = [
                t for t in tickers
                if t.get('symbol', '').endswith('USDT')
                and t.get('symbol', '') in trading_symbols
                and float(t.get('quoteVolume', 0)) > 0  # 确保有交易量
            ]

            # 处理并过滤交易量
            valid_coins = []
            for coin in usdt_coins:
                # 期货API返回的字段名是 'quoteVolume'（USDT成交量）
                quote_volume = coin.get('quoteVolume', 0)

                # 如果没有，尝试用price × volume计算
                if not quote_volume or quote_volume == 0:
                    price = float(coin.get('lastPrice', coin.get('weightedAvgPrice', 0)))
                    volume = float(coin.get('volume', 0))
                    if price > 0 and volume > 0:
                        quote_volume = price * volume
                        logger.debug(f"{coin.get('symbol')}: 使用price×volume计算交易量 = {quote_volume/1e6:.2f}M USDT")

                quote_volume_float = float(quote_volume)

                # 过滤：只保留交易量≥最小值的币种
                if quote_volume_float >= min_volume_usdt:
                    valid_coins.append({
                        'coin': coin,
                        'quote_volume': quote_volume_float
                    })

            # 按交易量排序（从高到低）
            valid_coins.sort(key=lambda x: x['quote_volume'], reverse=True)

            # 取前N个
            top_coins = valid_coins[:limit]

            logger.info(f"获取币种: 共{len(usdt_coins)}个USDT交易对, "
                       f"过滤后{len(valid_coins)}个满足≥{min_volume_usdt/1e6:.0f}M USDT, "
                       f"返回前{len(top_coins)}个")

            # 构建返回结果
            result = []
            for item in top_coins:
                coin = item['coin']
                result.append({
                    'symbol': coin.get('symbol', 'UNKNOWN'),
                    'price': float(coin.get('lastPrice', coin.get('weightedAvgPrice', 0))),
                    'change_24h': float(coin.get('priceChangePercent', 0)),
                    'volume_24h': item['quote_volume'],  # 使用验证过的USDT交易量（期货）
                    'volume': float(coin.get('volume', 0)),
                    # 🔧 新增：24小时交易笔数（用于过滤成交稀少的币种）
                    'trade_count_24h': int(coin.get('count', 0)) if coin.get('count') else None
                })

            return result

        try:
            return self._execute_with_retry(_fetch, call_type="normal")
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
        """获取期货K线数据 - 统一使用白名单过滤"""
        # 🔧 统一使用白名单过滤，任何未在白名单的符号直接跳过
        if not self._is_valid_futures_symbol(symbol):
            logger.debug(f"{symbol}: 不在期货白名单中，跳过K线获取")
            return []

        def _fetch():
            # 🔧 关键修复：使用期货API而不是现货API
            klines = self.client.futures_klines(
                symbol=symbol,
                interval=interval,
                limit=limit
            )

            result = []
            for k in klines:
                result.append({
                    'time': int(k[0]),
                    'open_time': int(k[0]),      # 🔧 添加 open_time 字段,用于量比计算
                    'close_time': int(k[6]),     # 🔧 添加 close_time 字段
                    'open': float(k[1]),
                    'high': float(k[2]),
                    'low': float(k[3]),
                    'close': float(k[4]),
                    'volume': float(k[7])  # 使用Quote Asset Volume (USDT成交额)，便于跨币种比较
                })
            return result

        try:
            return self._execute_with_retry(_fetch, call_type="optional")
        except BinanceAPIException as e:
            if e.code == -1121:  # Invalid symbol
                logger.warning(f"⚠️ {symbol}: 无效期货交易对")
                return []
            else:
                logger.error(f"获取K线失败 {symbol}: {e}")
                return []
        except Exception as e:
            logger.error(f"获取K线异常 {symbol}: {e}")
            return []

    def get_ticker(self, symbol: str) -> Optional[Dict]:
        """获取当前行情"""
        def _fetch():
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

        try:
            return self._execute_with_retry(_fetch, call_type="optional")
        except BinanceAPIException as e:
            logger.warning(f"获取行情失败 {symbol}: {e}")
            return None
        except Exception as e:
            logger.warning(f"获取行情异常 {symbol}: {e}")
            return None

    def get_valid_futures_symbols(self) -> List[str]:
        """
        🔧 获取有效的期货交易对列表

        Returns:
            有效的期货交易对符号列表
        """
        def _fetch():
            try:
                # 获取期货交易所信息
                exchange_info = self.client.futures_exchange_info()

                # 提取所有活跃的USDT交易对
                valid_symbols = []
                for symbol_info in exchange_info['symbols']:
                    symbol = symbol_info['symbol']
                    status = symbol_info['status']

                    # 只包含活跃的USDT交易对
                    if status == 'TRADING' and symbol.endswith('USDT'):
                        valid_symbols.append(symbol)

                logger.debug(f"获取到 {len(valid_symbols)} 个有效期货交易对")
                return valid_symbols

            except Exception as e:
                logger.error(f"获取期货交易所信息失败: {e}")
                # 返回一些常见的交易对作为备用
                return [
                    'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT', 'XRPUSDT',
                    'SOLUSDT', 'DOTUSDT', 'LINKUSDT', 'LTCUSDT', 'BCHUSDT'
                ]

        try:
            return self._execute_with_retry(_fetch, call_type="normal")
        except Exception as e:
            logger.error(f"获取有效期货交易对异常: {e}")
            return []

    def get_all_symbol_ticker_price(self) -> Dict[str, float]:
        """
        🚀 批量获取所有币种的当前价格 - 性能优化

        Returns:
            Dict[str, float]: {symbol: price} 格式的价格字典
        """
        def _fetch_all():
            # 使用Binance API的批量价格接口
            tickers = self.client.get_all_tickers()

            # 转换为字典格式，只包含USDT交易对
            price_dict = {}
            for ticker in tickers:
                symbol = ticker['symbol']
                if symbol.endswith('USDT'):
                    price_dict[symbol] = float(ticker['price'])

            logger.debug(f"批量获取到 {len(price_dict)} 个币种价格")
            return price_dict

        try:
            return self._execute_with_retry(_fetch_all, call_type="essential")
        except BinanceAPIException as e:
            logger.warning(f"批量获取价格失败: {e}")
            return {}
        except Exception as e:
            logger.error(f"批量获取价格异常: {e}")
            return {}

    # ==================== 期货交易 ====================
    def get_symbol_info(self, symbol: str) -> Optional[Dict]:
        """获取币种交易规则"""
        # 先检查缓存
        if symbol in self.symbol_info_cache:
            return self.symbol_info_cache[symbol]

        def _fetch_info():
            exchange_info = self.client.futures_exchange_info()
            for s in exchange_info['symbols']:
                if s['symbol'] == symbol:
                    info = {
                        'symbol': symbol,
                        'status': s['status'],  # TRADING, BREAK, etc.
                        'quantity_precision': s['quantityPrecision'],
                        'price_precision': s['pricePrecision'],
                    }

                    # 提取过滤规则
                    for f in s['filters']:
                        if f['filterType'] == 'LOT_SIZE':
                            info['min_qty'] = float(f['minQty'])
                            info['max_qty'] = float(f['maxQty'])
                            info['step_size'] = float(f['stepSize'])
                        elif f['filterType'] == 'PRICE_FILTER':
                            # 价格最小变动（用于限价挂单对齐tick）
                            info['tick_size'] = float(f.get('tickSize', 0))
                        elif f['filterType'] == 'MIN_NOTIONAL':
                            info['min_notional'] = float(f['notional'])

                    self.symbol_info_cache[symbol] = info
                    return info

            logger.warning(f"未找到币种信息: {symbol}")
            return None

        try:
            return self._execute_with_retry(_fetch_info, call_type="essential")
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

    def adjust_price(self, symbol: str, price: float) -> Optional[float]:
        """根据价格tick调整价格精度"""
        info = self.get_symbol_info(symbol)
        if not info:
            return None
        tick = float(info.get('tick_size') or 0)
        if tick <= 0:
            return float(price)

        from decimal import Decimal
        price_dec = Decimal(str(price))
        tick_dec = Decimal(str(tick))
        # 向下取整到tick的整数倍，确保不越价
        adjusted = (price_dec // tick_dec) * tick_dec
        return float(adjusted)

    def get_order_book_top(self, symbol: str) -> Optional[tuple]:
        """获取前一档盘口 (best_bid, best_ask)"""
        def _fetch_orderbook():
            ob = self.client.futures_order_book(symbol=symbol, limit=5)
            bids = ob.get('bids') or []
            asks = ob.get('asks') or []
            best_bid = float(bids[0][0]) if bids else None
            best_ask = float(asks[0][0]) if asks else None
            return best_bid, best_ask

        try:
            return self._execute_with_retry(_fetch_orderbook, call_type="essential")
        except Exception as e:
            logger.warning(f"{symbol}: 获取盘口失败: {e}")
            return None

    def set_leverage(self, symbol: str, leverage: int) -> bool:
        """设置杠杆倍数"""
        def _set_leverage():
            self.client.futures_change_leverage(
                symbol=symbol,
                leverage=leverage
            )
            logger.info(f"{symbol}: 杠杆已设置为 {leverage}x")
            return True

        try:
            return self._execute_with_retry(_set_leverage, call_type="essential")
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
        def _set_position_mode():
            try:
                self.client.futures_change_position_mode(
                    dualSidePosition=dual_side_position
                )
                mode_str = "双向持仓(Hedge)" if dual_side_position else "单向持仓"
                logger.info(f"持仓模式已设置为: {mode_str}")
                return True
            except BinanceAPIException as e:
                # 🔧 如果已经是目标模式，会返回错误码-4059，视为成功
                if e.code == -4059:
                    mode_str = "双向持仓(Hedge)" if dual_side_position else "单向持仓"
                    logger.info(f"持仓模式已经是: {mode_str}")
                    return True
                raise  # 其他错误继续抛出

        try:
            return self._execute_with_retry(_set_position_mode, call_type="essential")
        except BinanceAPIException as e:
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
        def _set_margin():
            self.client.futures_change_margin_type(
                symbol=symbol,
                marginType=margin_type
            )
            logger.info(f"{symbol}: 保证金模式已设置为 {margin_type}")
            return True

        try:
            return self._execute_with_retry(_set_margin, call_type="essential")
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
        """下达市价单 - 优化版：统一使用IOC，设置recvWindow=5000"""
        try:
            # 🔧 检查并重新同步时间
            self._check_time_sync()

            # 先调整数量精度
            adjusted_qty = self.adjust_quantity(symbol, quantity)
            if adjusted_qty is None:
                logger.error(f"{symbol}: 数量调整失败，无法下单")
                return None

            # 🔧 ReduceOnly前先检查持仓数量
            if reduce_only and position_side:
                max_qty = self._get_position_quantity(symbol, position_side)
                if max_qty is not None and adjusted_qty > max_qty:
                    logger.warning(f"{symbol}: 平仓数量 {adjusted_qty} 大于持仓 {max_qty}，截断为 {max_qty}")
                    adjusted_qty = max_qty
                    if adjusted_qty <= 0:
                        logger.warning(f"{symbol}: 截断后数量为0，跳过下单")
                        return None

            # 构建订单参数
            order_params = {
                'symbol': symbol,
                'side': side,
                'type': 'MARKET',
                'quantity': adjusted_qty,
                'recvWindow': 5000    # 🔧 设置5秒接收窗口
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
        def _cancel_order():
            self.client.futures_cancel_order(
                symbol=symbol,
                orderId=order_id
            )
            logger.info(f"{symbol}: 订单已取消 (订单ID: {order_id})")
            return True

        try:
            return self._execute_with_retry(_cancel_order, call_type="essential")
        except BinanceAPIException as e:
            logger.error(f"取消订单失败: {e}")
            return False
        except Exception as e:
            logger.error(f"取消订单异常: {e}")
            return False

    def get_order(self, symbol: str, order_id: int) -> Optional[Dict]:
        """获取订单状态"""
        def _fetch_order():
            o = self.client.futures_get_order(symbol=symbol, orderId=order_id)
            return {
                'order_id': o['orderId'],
                'status': o.get('status'),
                'origQty': float(o.get('origQty', 0)),
                'executedQty': float(o.get('executedQty', 0)),
                'avgPrice': float(o.get('avgPrice', 0) or 0),
                'side': o.get('side'),
                'type': o.get('type')
            }

        try:
            return self._execute_with_retry(_fetch_order, call_type="normal")
        except Exception as e:
            logger.warning(f"{symbol}: 获取订单失败: {e}")
            return None

    def _get_position_quantity(self, symbol: str, position_side: str) -> Optional[float]:
        """获取特定方向的持仓数量"""
        def _fetch_position():
            positions = self.client.futures_position_information(symbol=symbol)
            for pos in positions:
                if pos['positionSide'] == position_side:
                    return abs(float(pos['positionAmt']))
            return 0.0

        try:
            return self._execute_with_retry(_fetch_position, call_type="essential")
        except Exception as e:
            logger.warning(f"{symbol}: 获取持仓数量失败: {e}")
            return None

    def place_limit_maker_order(
        self,
        symbol: str,
        side: str,               # 'BUY' / 'SELL'
        quantity: float,
        position_side: str = None,  # 'LONG' / 'SHORT'
        price: Optional[float] = None
    ) -> Optional[Dict]:
        """
        下达限价挂单（Post-Only，timeInForce='GTX'）
        默认按盘口最优价（买：best_bid；卖：best_ask）并对齐tick
        """
        try:
            adjusted_qty = self.adjust_quantity(symbol, quantity)
            if adjusted_qty is None:
                logger.error(f"{symbol}: 数量调整失败，无法下挂单")
                return None

            use_price = price
            if use_price is None:
                top = self.get_order_book_top(symbol)
                if not top or (top[0] is None and top[1] is None):
                    logger.warning(f"{symbol}: 无法获取盘口，挂单失败")
                    return None
                best_bid, best_ask = top
                if side.upper() == 'BUY':
                    use_price = best_bid
                else:
                    use_price = best_ask

            adj_price = self.adjust_price(symbol, use_price)
            if adj_price is None:
                logger.error(f"{symbol}: 价格调整失败，无法下挂单")
                return None

            params = {
                'symbol': symbol,
                'side': side,
                'type': 'LIMIT',
                'timeInForce': 'GTX',   # Post-Only
                'quantity': adjusted_qty,
                'price': f"{adj_price:.8f}"
            }

            if position_side:
                params['positionSide'] = position_side

            order = self.client.futures_create_order(**params)
            timestamp = order.get('updateTime') or order.get('transactTime') or order.get('time', 0)
            result = {
                'order_id': order['orderId'],
                'symbol': order['symbol'],
                'side': order['side'],
                'quantity': float(order['origQty']),
                'filled': float(order.get('executedQty', 0) or 0),
                'status': order.get('status', ''),
                'price': float(order.get('price', adj_price)),
                'timestamp': timestamp
            }
            logger.info(f"{symbol}: 限价挂单 {side} {adjusted_qty} @ {adj_price} (订单ID: {order['orderId']})")
            return result
        except BinanceOrderException as e:
            logger.error(f"挂单被拒绝 {symbol}: {e}")
            return None
        except BinanceAPIException as e:
            logger.error(f"挂单失败 {symbol}: {e}")
            return None
        except Exception as e:
            logger.error(f"挂单异常 {symbol}: {e}")
            return None

    def place_market_order_prefer_maker(
        self,
        symbol: str,
        side: str,
        quantity: float,
        reduce_only: bool = False,
        position_side: str = None
    ) -> Optional[Dict]:
        """
        🔧 简化下单策略：统一使用市价单IOC模式
        原做市策略已移除，直接使用市价单确保成交
        """
        return self.place_market_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            reduce_only=reduce_only,
            position_side=position_side
        )

    # ==================== 持仓和账户 ====================
    def get_positions(self) -> List[Dict]:
        """获取当前持仓"""
        def _fetch_positions():
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
                        'unrealized_profit': float(p['unRealizedProfit']),
                        'unrealized_profit_pct': float(p['unRealizedProfit']) / (float(p['notional']) or 1) * 100
                    })

            return result

        try:
            return self._execute_with_retry(_fetch_positions, call_type="essential")
        except BinanceAPIException as e:
            logger.error(f"获取持仓失败: {e}")
            return []
        except Exception as e:
            logger.error(f"获取持仓异常: {e}")
            return []

    def get_account_balance(self) -> Optional[float]:
        """获取账户总资产"""
        def _fetch_balance():
            account = self.client.futures_account()
            balance = float(account['totalWalletBalance'])
            logger.info(f"账户余额: {balance:.2f} USDT")
            return balance

        try:
            return self._execute_with_retry(_fetch_balance, call_type="essential")
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

    # ==================== 时间同步 ====================
    def _sync_server_time(self):
        """同步期货服务器时间，解决-1021错误"""
        try:
            # 🔧 使用期货API获取服务器时间，更准确
            server_time_response = self.client.futures_time()
            server_time = server_time_response['serverTime']

            # 本地时间（毫秒）
            local_time = int(time.time() * 1000)

            # 计算偏移
            self.time_offset = server_time - local_time
            self.last_time_sync = local_time

            logger.info(f"期货时间同步完成: 偏移 {self.time_offset}ms")

        except Exception as e:
            logger.warning(f"期货时间同步失败，回退到现货API: {e}")
            try:
                # 回退到现货时间API
                server_time_response = self.client.get_server_time()
                server_time = server_time_response['serverTime']
                local_time = int(time.time() * 1000)
                self.time_offset = server_time - local_time
                self.last_time_sync = local_time
                logger.info(f"现货时间同步完成: 偏移 {self.time_offset}ms")
            except Exception as e2:
                logger.warning(f"时间同步完全失败: {e2}")
                self.time_offset = 0

    def _check_time_sync(self):
        """检查是否需要重新同步时间"""
        current_time = int(time.time() * 1000)

        # 每5分钟重新同步一次
        if current_time - self.last_time_sync > 5 * 60 * 1000:
            self._sync_server_time()

    def get_corrected_timestamp(self):
        """获取校正后的时间戳"""
        self._check_time_sync()
        return int(time.time() * 1000) + self.time_offset

"""
网络监控模块 (network_monitor.py)
负责监控网络连接状态，提供网络健康检测和恢复机制
"""

import logging
import asyncio
import time
import aiohttp
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

from config_v2 import API_CONFIG, SYSTEM_CONFIG


logger = logging.getLogger(__name__)


class NetworkStatus(Enum):
    """网络状态枚举"""
    HEALTHY = "HEALTHY"           # 健康
    DEGRADED = "DEGRADED"         # 降级
    UNSTABLE = "UNSTABLE"         # 不稳定
    DISCONNECTED = "DISCONNECTED" # 断连


@dataclass
class NetworkMetrics:
    """网络指标"""
    latency_ms: float = 0.0
    success_rate: float = 1.0
    consecutive_failures: int = 0
    last_success_time: Optional[datetime] = None
    last_failure_time: Optional[datetime] = None
    status: NetworkStatus = NetworkStatus.HEALTHY


class NetworkMonitor:
    """网络监控器"""

    def __init__(self):
        """初始化网络监控器"""
        self.metrics = NetworkMetrics()
        self.api_call_history: List[Dict] = []  # 记录API调用历史
        self.health_check_interval = 30  # 健康检查间隔(秒)
        self.last_health_check = None

        # 网络质量阈值
        self.latency_thresholds = {
            'healthy': 200,      # <200ms 健康
            'degraded': 1000,    # 200-1000ms 降级
            'unstable': 3000,    # 1000-3000ms 不稳定
            # >3000ms 视为断连
        }

        self.success_rate_thresholds = {
            'healthy': 0.95,     # >95% 健康
            'degraded': 0.85,    # 85-95% 降级
            'unstable': 0.7,     # 70-85% 不稳定
            # <70% 视为断连
        }

        # 降级策略配置
        self.degraded_strategies = {
            'reduce_concurrent_requests': True,
            'increase_timeout': True,
            'skip_non_essential_calls': True,
            'emergency_position_protection': False
        }

        # 断线保护配置
        self.disconnection_protection = {
            'max_disconnection_time': 300,  # 最大断线时间5分钟
            'emergency_close_positions': True,
            'disable_new_entries': True,
            'alert_user': True
        }

        self._session = None
        self._health_check_task = None
        self._emergency_mode = False

    async def start_monitoring(self):
        """启动网络监控"""
        logger.info("启动网络监控...")

        # 创建HTTP会话
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        self._session = aiohttp.ClientSession(timeout=timeout)

        # 启动健康检查任务
        self._health_check_task = asyncio.create_task(self._health_check_loop())

        # 初始健康检查
        await self._perform_health_check()

        logger.info(f"网络监控已启动，当前状态: {self.metrics.status.value}")

    async def stop_monitoring(self):
        """停止网络监控"""
        logger.info("停止网络监控...")

        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass

        if self._session:
            await self._session.close()

        logger.info("网络监控已停止")

    async def _health_check_loop(self):
        """健康检查循环"""
        while True:
            try:
                await asyncio.sleep(self.health_check_interval)
                await self._perform_health_check()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"健康检查循环异常: {e}")
                await asyncio.sleep(5)  # 短暂等待后继续

    async def _perform_health_check(self):
        """执行健康检查"""
        start_time = time.time()

        try:
            # 测试Binance API连通性
            url = "https://fapi.binance.com/fapi/v1/ping"
            async with self._session.get(url) as response:
                if response.status == 200:
                    latency = (time.time() - start_time) * 1000  # 转换为毫秒
                    await self._record_success(latency)
                else:
                    await self._record_failure(f"HTTP {response.status}")

        except asyncio.TimeoutError:
            await self._record_failure("Timeout")
        except Exception as e:
            await self._record_failure(str(e))

        # 更新网络状态
        self._update_network_status()

        self.last_health_check = datetime.now()

    async def _record_success(self, latency_ms: float):
        """记录成功的API调用"""
        self.metrics.latency_ms = latency_ms
        self.metrics.consecutive_failures = 0
        self.metrics.last_success_time = datetime.now()

        self.api_call_history.append({
            'timestamp': datetime.now(),
            'success': True,
            'latency_ms': latency_ms,
            'error': None
        })

        # 保持最近100条记录
        if len(self.api_call_history) > 100:
            self.api_call_history = self.api_call_history[-100:]

    async def _record_failure(self, error: str):
        """记录失败的API调用"""
        self.metrics.consecutive_failures += 1
        self.metrics.last_failure_time = datetime.now()

        self.api_call_history.append({
            'timestamp': datetime.now(),
            'success': False,
            'latency_ms': None,
            'error': error
        })

        # 保持最近100条记录
        if len(self.api_call_history) > 100:
            self.api_call_history = self.api_call_history[-100:]

        logger.warning(f"网络调用失败: {error}, 连续失败次数: {self.metrics.consecutive_failures}")

    def _update_network_status(self):
        """更新网络状态"""
        old_status = self.metrics.status

        # 计算最近50次调用的成功率
        recent_calls = self.api_call_history[-50:] if len(self.api_call_history) >= 50 else self.api_call_history

        if recent_calls:
            success_count = sum(1 for call in recent_calls if call['success'])
            self.metrics.success_rate = success_count / len(recent_calls)

        # 基于连续失败次数快速判断
        if self.metrics.consecutive_failures >= 10:
            self.metrics.status = NetworkStatus.DISCONNECTED
        elif self.metrics.consecutive_failures >= 5:
            self.metrics.status = NetworkStatus.UNSTABLE
        # 基于成功率判断
        elif self.metrics.success_rate >= self.success_rate_thresholds['healthy']:
            if self.metrics.latency_ms <= self.latency_thresholds['healthy']:
                self.metrics.status = NetworkStatus.HEALTHY
            elif self.metrics.latency_ms <= self.latency_thresholds['degraded']:
                self.metrics.status = NetworkStatus.DEGRADED
            else:
                self.metrics.status = NetworkStatus.UNSTABLE
        elif self.metrics.success_rate >= self.success_rate_thresholds['degraded']:
            self.metrics.status = NetworkStatus.DEGRADED
        elif self.metrics.success_rate >= self.success_rate_thresholds['unstable']:
            self.metrics.status = NetworkStatus.UNSTABLE
        else:
            self.metrics.status = NetworkStatus.DISCONNECTED

        # 状态变化时记录日志
        if old_status != self.metrics.status:
            logger.warning(
                f"网络状态变化: {old_status.value} -> {self.metrics.status.value} "
                f"(延迟: {self.metrics.latency_ms:.0f}ms, 成功率: {self.metrics.success_rate:.1%}, "
                f"连续失败: {self.metrics.consecutive_failures})"
            )

            # 触发状态变化处理
            asyncio.create_task(self._handle_status_change(old_status, self.metrics.status))

    async def _handle_status_change(self, old_status: NetworkStatus, new_status: NetworkStatus):
        """处理网络状态变化"""

        # 进入紧急模式
        if new_status == NetworkStatus.DISCONNECTED and old_status != NetworkStatus.DISCONNECTED:
            logger.error("🚨 网络断连，进入紧急模式")
            self._emergency_mode = True

            # 可以在这里触发紧急平仓等保护措施
            # 这需要与主交易引擎集成

        # 退出紧急模式
        elif old_status == NetworkStatus.DISCONNECTED and new_status in [NetworkStatus.HEALTHY, NetworkStatus.DEGRADED]:
            logger.info("✅ 网络恢复，退出紧急模式")
            self._emergency_mode = False

        # 网络降级
        elif new_status == NetworkStatus.DEGRADED and old_status == NetworkStatus.HEALTHY:
            logger.warning("⚠️ 网络降级，启用保护措施")

        # 网络恢复
        elif new_status == NetworkStatus.HEALTHY and old_status in [NetworkStatus.DEGRADED, NetworkStatus.UNSTABLE]:
            logger.info("✅ 网络恢复正常")

    def should_skip_api_call(self, call_type: str = "normal") -> Tuple[bool, str]:
        """
        判断是否应该跳过API调用

        Args:
            call_type: 调用类型 ("essential", "normal", "optional")

        Returns:
            (是否跳过, 跳过原因)
        """

        # 紧急模式：只允许必要调用
        if self._emergency_mode and call_type != "essential":
            return True, "紧急模式，跳过非必要调用"

        # 网络断连：跳过所有非必要调用
        if self.metrics.status == NetworkStatus.DISCONNECTED:
            if call_type != "essential":
                return True, f"网络断连({self.metrics.consecutive_failures}次连续失败)"

        # 网络不稳定：跳过可选调用
        elif self.metrics.status == NetworkStatus.UNSTABLE:
            if call_type == "optional":
                return True, f"网络不稳定(成功率{self.metrics.success_rate:.1%})"

        return False, ""

    def get_recommended_timeout(self, default_timeout: float = 30.0) -> float:
        """
        获取推荐的超时时间

        Args:
            default_timeout: 默认超时时间

        Returns:
            推荐的超时时间
        """

        if self.metrics.status == NetworkStatus.DISCONNECTED:
            return default_timeout * 3  # 断连时延长超时
        elif self.metrics.status == NetworkStatus.UNSTABLE:
            return default_timeout * 2  # 不稳定时适当延长
        elif self.metrics.status == NetworkStatus.DEGRADED:
            return default_timeout * 1.5  # 降级时略微延长
        else:
            return default_timeout  # 正常情况使用默认值

    def get_max_concurrent_requests(self, default_max: int = 10) -> int:
        """
        获取推荐的最大并发请求数

        Args:
            default_max: 默认最大并发数

        Returns:
            推荐的最大并发数
        """

        if self.metrics.status == NetworkStatus.DISCONNECTED:
            return 1  # 断连时串行执行
        elif self.metrics.status == NetworkStatus.UNSTABLE:
            return max(1, default_max // 3)  # 不稳定时大幅减少
        elif self.metrics.status == NetworkStatus.DEGRADED:
            return max(1, default_max // 2)  # 降级时适当减少
        else:
            return default_max  # 正常情况使用默认值

    def get_network_summary(self) -> Dict:
        """获取网络状态摘要"""

        recent_failures = [call for call in self.api_call_history[-20:] if not call['success']]

        return {
            'status': self.metrics.status.value,
            'latency_ms': self.metrics.latency_ms,
            'success_rate': self.metrics.success_rate,
            'consecutive_failures': self.metrics.consecutive_failures,
            'emergency_mode': self._emergency_mode,
            'last_success': self.metrics.last_success_time.strftime("%H:%M:%S") if self.metrics.last_success_time else "Never",
            'last_failure': self.metrics.last_failure_time.strftime("%H:%M:%S") if self.metrics.last_failure_time else "Never",
            'recent_errors': [call['error'] for call in recent_failures[-5:]],  # 最近5个错误
            'total_calls': len(self.api_call_history)
        }

    async def test_connection_recovery(self) -> bool:
        """
        测试连接恢复

        Returns:
            连接是否已恢复
        """

        try:
            # 执行快速连通性测试
            await self._perform_health_check()

            # 检查是否恢复到稳定状态
            return self.metrics.status in [NetworkStatus.HEALTHY, NetworkStatus.DEGRADED]

        except Exception as e:
            logger.error(f"连接恢复测试失败: {e}")
            return False

    def is_emergency_mode(self) -> bool:
        """检查是否处于紧急模式"""
        return self._emergency_mode

    def force_emergency_mode(self, enable: bool, reason: str = ""):
        """强制启用/禁用紧急模式"""
        if enable != self._emergency_mode:
            self._emergency_mode = enable
            mode_str = "启用" if enable else "禁用"
            logger.warning(f"🚨 强制{mode_str}紧急模式: {reason}")


# ==================== 单例实例 ====================
# 全局网络监控实例
_network_monitor_instance = None

def get_network_monitor() -> NetworkMonitor:
    """获取全局网络监控实例"""
    global _network_monitor_instance
    if _network_monitor_instance is None:
        _network_monitor_instance = NetworkMonitor()
    return _network_monitor_instance


# ==================== 装饰器 ====================
def network_aware_api_call(call_type: str = "normal"):
    """
    网络感知的API调用装饰器

    Args:
        call_type: 调用类型 ("essential", "normal", "optional")
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            monitor = get_network_monitor()

            # 检查是否应该跳过调用
            should_skip, reason = monitor.should_skip_api_call(call_type)
            if should_skip:
                logger.debug(f"跳过API调用 {func.__name__}: {reason}")
                return None

            # 调整超时时间
            if 'timeout' in kwargs:
                original_timeout = kwargs['timeout']
                kwargs['timeout'] = monitor.get_recommended_timeout(original_timeout)

            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                # 记录API调用失败（如果可能的话）
                logger.warning(f"API调用失败 {func.__name__}: {e}")
                raise

        return wrapper
    return decorator


# ==================== 测试函数 ====================
if __name__ == "__main__":
    async def test_network_monitor():
        """测试网络监控功能"""
        monitor = NetworkMonitor()

        print("启动网络监控测试...")
        await monitor.start_monitoring()

        # 等待几次健康检查
        await asyncio.sleep(10)

        print("网络状态摘要:")
        summary = monitor.get_network_summary()
        for key, value in summary.items():
            print(f"  {key}: {value}")

        await monitor.stop_monitoring()
        print("网络监控测试完成")

    asyncio.run(test_network_monitor())
"""
冷却与频率控制管理器

功能：
- 记录每个symbol的信号历史和失败情况
- 实现冷却机制（失败后5-15分钟不再发出信号）
- 避免连续重复的虚假信号（噪音）
- 动态调整冷却时间（失败越多，冷却越长）
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Optional
import json
from pathlib import Path

logger = logging.getLogger(__name__)


class CooldownManager:
    """冷却与频率控制管理器"""

    # 冷却时间配置（秒）
    BASE_COOLDOWN = 300          # 基础冷却：5分钟
    MAX_COOLDOWN = 900           # 最大冷却：15分钟
    ESCALATION_STEP = 120        # 每次失败增加：2分钟
    SEVERE_COOLDOWN = 43200      # 严重冷却：12小时（连续失败3次以上）

    # 触发条件
    FAILURE_THRESHOLD = 2        # 2次失败触发冷却升级
    SEVERE_FAILURE_COUNT = 3     # 连续3次失败触发严重冷却
    CLEAR_HISTORY_DAYS = 1       # 1天后清空失败历史

    def __init__(self, persistence_file: str = None):
        """
        初始化冷却管理器

        参数：
            persistence_file: 可选的持久化文件路径（用于保存冷却状态）
        """
        # 冷却状态追踪
        # {symbol: {'cooldown_until': datetime, 'failure_count': int, 'last_failure': datetime}}
        self.cooldown_map: Dict[str, Dict] = {}

        # 持久化文件
        self.persistence_file = persistence_file or Path(__file__).parent / 'cooldown_state.json'

        # 加载之前的状态
        self._load_state()

        logger.info("【冷却管理器初始化】")
        logger.info(f"  基础冷却: {self.BASE_COOLDOWN}秒 (5分钟)")
        logger.info(f"  最大冷却: {self.MAX_COOLDOWN}秒 (15分钟)")
        logger.info(f"  冷却升级: 每2分钟 (失败次数越多越严格)")
        logger.info(f"  严重冷却: {self.SEVERE_COOLDOWN}秒 (12小时，连续失败≥3次)")
        logger.info(f"  持久化: {self.persistence_file}")

    def _load_state(self):
        """从文件加载之前的冷却状态（仅加载有效期内的记录）"""
        try:
            if Path(self.persistence_file).exists():
                with open(self.persistence_file, 'r') as f:
                    data = json.load(f)
                    # 恢复状态
                    now = datetime.now()
                    valid_count = 0
                    filtered_reason = {}

                    for symbol, state in data.items():
                        try:
                            cooldown_until = datetime.fromisoformat(state['cooldown_until'])
                            failure_count = state.get('failure_count', 0)
                            last_failure = datetime.fromisoformat(state.get('last_failure', datetime.now().isoformat()))

                            # 【第1检查】冷却期是否已过期
                            if now >= cooldown_until:
                                filtered_reason[symbol] = "冷却已解除"
                                logger.debug(f"【过期过滤】{symbol} 冷却已解除")
                                continue

                            # 【第2检查】验证时间戳逻辑（last_failure不应该在未来）
                            if last_failure > now:
                                filtered_reason[symbol] = "时间戳异常"
                                logger.warning(
                                    f"【异常检测】{symbol} last_failure在未来({last_failure})，跳过"
                                )
                                continue

                            # 【第3检查】failure_count的合理性
                            if failure_count > 10 or failure_count < 0:
                                filtered_reason[symbol] = f"失败计数异常({failure_count})"
                                logger.warning(
                                    f"【异常检测】{symbol} failure_count={failure_count}异常，跳过该记录"
                                )
                                continue

                            # 【第4检查】last_failure距离现在是否太久（>1天则不加载）
                            time_since_failure = now - last_failure
                            if time_since_failure > timedelta(days=self.CLEAR_HISTORY_DAYS):
                                filtered_reason[symbol] = f"失败历史过期({time_since_failure.days}天)"
                                logger.debug(f"【过期过滤】{symbol} 失败历史过期")
                                continue

                            # 【第5检查】cooldown_until和last_failure的时间关系验证
                            expected_cooldown_time = last_failure + timedelta(seconds=self.BASE_COOLDOWN * (2 ** (failure_count - 1)))
                            time_diff = abs((cooldown_until - expected_cooldown_time).total_seconds())
                            # 允许±2分钟的偏差
                            if time_diff > 120 and failure_count > 0:
                                logger.warning(
                                    f"【时间验证】{symbol} 冷却时间逻辑异常 "
                                    f"(预期: {expected_cooldown_time}, 实际: {cooldown_until}), "
                                    f"为安全起见跳过该记录"
                                )
                                filtered_reason[symbol] = "冷却时间逻辑异常"
                                continue

                            # 所有检查都通过，才加载该记录
                            self.cooldown_map[symbol] = {
                                'cooldown_until': cooldown_until,
                                'failure_count': failure_count,
                                'last_failure': last_failure
                            }
                            valid_count += 1
                            logger.debug(f"【加载有效冷却】{symbol} failure_count={failure_count}, 剩余{int((cooldown_until-now).total_seconds())}秒")

                        except Exception as e:
                            logger.debug(f"【解析异常】{symbol}: {e}，跳过该记录")
                            filtered_reason[symbol] = f"解析异常: {e}"
                            continue

                    # 输出加载结果
                    total_records = len(data)
                    filtered_count = total_records - valid_count
                    logger.info(f"✓ 加载冷却状态: {valid_count}个有效symbol")
                    if filtered_count > 0:
                        logger.info(f"  过滤了{filtered_count}个无效记录:")
                        for symbol, reason in filtered_reason.items():
                            logger.info(f"    - {symbol}: {reason}")
        except Exception as e:
            logger.debug(f"无法加载冷却状态: {e}")
            self.cooldown_map = {}

    def _save_state(self):
        """保存冷却状态到文件"""
        try:
            data = {}
            now = datetime.now()

            # 在保存前先清理过期记录
            for symbol, state in list(self.cooldown_map.items()):
                # 跳过已过期的记录
                if now >= state['cooldown_until']:
                    del self.cooldown_map[symbol]
                    continue

                data[symbol] = {
                    'cooldown_until': state['cooldown_until'].isoformat(),
                    'failure_count': state['failure_count'],
                    'last_failure': state['last_failure'].isoformat()
                }

            with open(self.persistence_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.debug(f"保存冷却状态失败: {e}")

    def is_in_cooldown(self, symbol: str) -> bool:
        """
        检查symbol是否在冷却期内

        返回：
            True: 在冷却期，不应发出信号
            False: 冷却期已过，可以发出信号
        """
        if symbol not in self.cooldown_map:
            return False

        state = self.cooldown_map[symbol]
        now = datetime.now()

        # 检查是否冷却期已过
        if now >= state['cooldown_until']:
            logger.debug(f"【冷却解除】{symbol} 冷却期已过")
            # 清空该symbol的冷却状态
            del self.cooldown_map[symbol]
            self._save_state()
            return False

        return True

    def get_cooldown_remaining(self, symbol: str) -> Optional[int]:
        """
        获取symbol剩余冷却时间（秒）

        返回：
            None: 不在冷却期
            int: 剩余秒数
        """
        if symbol not in self.cooldown_map:
            return None

        now = datetime.now()
        cooldown_until = self.cooldown_map[symbol]['cooldown_until']

        if now >= cooldown_until:
            return None

        remaining = int((cooldown_until - now).total_seconds())
        return max(remaining, 0)

    def record_failure(self, symbol: str, reason: str = ""):
        """
        记录symbol的失败

        失败记录会导致：
        1. 增加失败计数
        2. 触发或延长冷却期
        3. 失败2次时冷却时间翻倍
        4. 失败3次以上时冷却12小时
        """
        now = datetime.now()

        if symbol not in self.cooldown_map:
            self.cooldown_map[symbol] = {
                'cooldown_until': now,
                'failure_count': 0,
                'last_failure': now
            }

        state = self.cooldown_map[symbol]

        # 检查是否需要清空历史（超过1天）
        if now - state['last_failure'] > timedelta(days=self.CLEAR_HISTORY_DAYS):
            state['failure_count'] = 0
            logger.debug(f"【失败历史清空】{symbol} (超过1天)")

        # 增加失败计数
        state['failure_count'] += 1
        state['last_failure'] = now

        # 计算冷却时间：根据失败次数
        if state['failure_count'] >= self.SEVERE_FAILURE_COUNT:
            # 连续失败3次以上 → 12小时冷却
            cooldown_seconds = self.SEVERE_COOLDOWN
            failure_level = "严重冷却（≥3次失败）"
        elif state['failure_count'] == 2:
            # 第2次失败 → 冷却时间翻倍
            cooldown_seconds = self.BASE_COOLDOWN * 2  # 10分钟
            failure_level = "加倍冷却（第2次失败）"
        else:
            # 第1次失败 → 基础冷却
            cooldown_seconds = self.BASE_COOLDOWN
            failure_level = "基础冷却（第1次失败）"

        # 更新冷却截止时间
        state['cooldown_until'] = now + timedelta(seconds=cooldown_seconds)

        logger.warning(
            f"【触发冷却】{symbol}\n"
            f"  原因: {reason}\n"
            f"  失败次数: {state['failure_count']}\n"
            f"  冷却级别: {failure_level}\n"
            f"  冷却时长: {cooldown_seconds}秒 ({cooldown_seconds/60:.1f}分钟)\n"
            f"  冷却截止: {state['cooldown_until'].strftime('%Y-%m-%d %H:%M:%S')}"
        )

        self._save_state()

    def clear_cooldown(self, symbol: str):
        """
        手动清除symbol的冷却状态（例如：确认交易成功）
        """
        if symbol in self.cooldown_map:
            del self.cooldown_map[symbol]
            logger.info(f"【手动清除冷却】{symbol}")
            self._save_state()

    def get_status(self, symbol: str) -> Dict:
        """获取symbol的详细状态"""
        if symbol not in self.cooldown_map:
            return {
                'symbol': symbol,
                'in_cooldown': False,
                'failure_count': 0,
                'cooldown_remaining': None
            }

        state = self.cooldown_map[symbol]
        remaining = self.get_cooldown_remaining(symbol)

        return {
            'symbol': symbol,
            'in_cooldown': remaining is not None,
            'failure_count': state['failure_count'],
            'cooldown_remaining': remaining,
            'cooldown_until': state['cooldown_until'].strftime('%H:%M:%S'),
            'last_failure': state['last_failure'].strftime('%H:%M:%S')
        }

    def get_all_status(self) -> Dict[str, Dict]:
        """获取所有symbols的状态"""
        status = {}
        for symbol in list(self.cooldown_map.keys()):
            # 自动清理已过期的冷却
            if not self.is_in_cooldown(symbol):
                continue
            status[symbol] = self.get_status(symbol)

        return status

    def log_status(self):
        """输出冷却状态日志"""
        status = self.get_all_status()

        if not status:
            logger.info("【冷却状态】无活跃冷却")
            return

        logger.info(f"【冷却状态】共{len(status)}个symbol在冷却中:")
        for symbol, info in sorted(status.items()):
            logger.info(
                f"  {symbol}: "
                f"失败×{info['failure_count']} "
                f"剩余{info['cooldown_remaining']}秒 "
                f"({info['cooldown_until']}解除)"
            )


# 使用示例和测试
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    # 创建管理器
    manager = CooldownManager()

    print("\n【测试1】初始化")
    print(f"BTCUSDT在冷却期: {manager.is_in_cooldown('BTCUSDT')}")

    print("\n【测试2】记录失败")
    manager.record_failure('BTCUSDT', '虚假信号')
    print(f"BTCUSDT在冷却期: {manager.is_in_cooldown('BTCUSDT')}")
    print(f"剩余冷却: {manager.get_cooldown_remaining('BTCUSDT')}秒")

    print("\n【测试3】连续失败（升级冷却）")
    manager.record_failure('BTCUSDT', '仍然虚假')
    print(f"剩余冷却: {manager.get_cooldown_remaining('BTCUSDT')}秒 (应该更长)")

    print("\n【测试4】查看状态")
    print(manager.get_status('BTCUSDT'))

    print("\n【测试5】清除冷却")
    manager.clear_cooldown('BTCUSDT')
    print(f"BTCUSDT在冷却期: {manager.is_in_cooldown('BTCUSDT')}")

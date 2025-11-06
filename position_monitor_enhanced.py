"""
增强版持仓监控程序 - ATR基础动态止损/止盈

功能：
1. 基于ATR计算每个币种的动态止损/止盈
2. 智能分批止盈（快速获利40% + Trailing Stop60%）
3. 自适应不同币种的波动性
4. 完整的持仓保护和风险管理

运行方式：
    python position_monitor_enhanced.py
"""

import logging
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Optional

# 设置项目路径
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from binance_client import BinanceClient
from atr_risk_manager import ATRBasedRiskManager
from cooldown_manager import CooldownManager

# ==================== 配置参数 ====================
# ATR模式开启（推荐）
ENABLE_ATR_MODE = True  # True: 使用ATR动态止损 | False: 使用静态百分比

# 备用静态配置（当ATR无法计算时）
FALLBACK_STOP_LOSS_PERCENTAGE = 0.008     # 0.8% 止损 (原0.4%)
FALLBACK_TAKE_PROFIT_PERCENTAGE = 0.025   # 2.5% 止盈 (原1.6%)
FALLBACK_BREAKEVEN_TRIGGER = 0.003        # 0.3% 保本触发

# 检查间隔
CHECK_INTERVAL = 10  # 秒

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class EnhancedPositionMonitor:
    """增强版持仓监控器 - ATR基础动态风险管理"""

    def __init__(self, check_interval: int = CHECK_INTERVAL):
        """初始化监控器"""
        logger.info("=" * 100)
        logger.info("【增强版持仓监控程序 v2.0】- ATR基础动态止损/止盈")
        logger.info("=" * 100)

        self.check_interval = check_interval
        self.running = False

        # 持仓信息追踪 {symbol: {position_info}}
        self.position_tracker = {}

        # 初始化核心模块
        try:
            self.binance_client = BinanceClient()
            self.cooldown_manager = CooldownManager()
            logger.info("✓ 核心模块初始化成功")
        except Exception as e:
            logger.error(f"✗ 核心模块初始化失败: {e}")
            logger.error(f"错误类型: {type(e).__name__}")
            logger.error(f"详细信息: {str(e)}")
            import traceback
            logger.error(f"堆栈跟踪:\n{traceback.format_exc()}")
            input("按回车键退出...")
            raise

        logger.info("=" * 100)
        logger.info(f"【配置信息】")
        logger.info(f"  模式: {'ATR动态模式' if ENABLE_ATR_MODE else '静态百分比模式'}")
        logger.info(f"  检查间隔: {self.check_interval}秒")

        if ENABLE_ATR_MODE:
            logger.info(f"  ATR初始止损: 1.0 × ATR")
            logger.info(f"  ATR第一止盈: 1.0 × ATR (平仓40%)")
            logger.info(f"  ATR追踪止损: 0.6 × ATR (剩余60%)")
        else:
            logger.info(f"  静态止损: {FALLBACK_STOP_LOSS_PERCENTAGE*100:.1f}%")
            logger.info(f"  静态止盈: {FALLBACK_TAKE_PROFIT_PERCENTAGE*100:.1f}%")

        logger.info(f"  【功能】分批止盈、自适应波动、Trailing Stop")
        logger.info("=" * 100)

    def get_klines_for_symbol(self, symbol: str, interval: str = '1m') -> Optional[list]:
        """获取币种的K线数据"""
        try:
            klines_data = self.binance_client.client.futures_klines(
                symbol=symbol,
                interval=interval,
                limit=30  # 获取30根K线用于ATR计算
            )

            if not klines_data:
                return None

            # 标准化K线数据
            klines = []
            for k in klines_data:
                klines.append({
                    'open': float(k[1]),
                    'high': float(k[2]),
                    'low': float(k[3]),
                    'close': float(k[4]),
                    'volume': float(k[7])
                })

            return klines

        except Exception as e:
            logger.debug(f"获取{symbol} K线失败: {e}")
            return None

    def calculate_risk_parameters(
        self,
        symbol: str,
        entry_price: float,
        side: str = 'BUY'
    ) -> Dict:
        """
        计算币种的风险参数（止损/止盈）
        优化版本：支持改进的盈亏比计算

        返回：
        {
            'stop_loss_price': float,
            'stop_loss_pct': float,
            'first_profit_price': float,
            'first_profit_pct': float,
            'trailing_stop_price': float,
            'trailing_stop_pct': float,
            'atr': float,
            'risk_level': str,
            'method': str,  # 'ATR' 或 'FALLBACK'
            'risk_reward_ratio': float  # 新增：盈亏比
        }
        """
        try:
            if not ENABLE_ATR_MODE:
                # 使用静态百分比
                if side == 'BUY':
                    stop_loss_price = entry_price * (1 - FALLBACK_STOP_LOSS_PERCENTAGE)
                    first_profit_price = entry_price * (1 + FALLBACK_TAKE_PROFIT_PERCENTAGE)
                    trailing_stop_price = entry_price * (1 + FALLBACK_STOP_LOSS_PERCENTAGE / 2)
                else:
                    stop_loss_price = entry_price * (1 + FALLBACK_STOP_LOSS_PERCENTAGE)
                    first_profit_price = entry_price * (1 - FALLBACK_TAKE_PROFIT_PERCENTAGE)
                    trailing_stop_price = entry_price * (1 - FALLBACK_STOP_LOSS_PERCENTAGE / 2)

                # 计算盈亏比
                stop_loss_distance = abs(entry_price - stop_loss_price)
                take_profit_distance = abs(first_profit_price - entry_price)
                risk_reward_ratio = take_profit_distance / stop_loss_distance if stop_loss_distance > 0 else 0

                return {
                    'stop_loss_price': stop_loss_price,
                    'stop_loss_pct': FALLBACK_STOP_LOSS_PERCENTAGE * 100,
                    'first_profit_price': first_profit_price,
                    'first_profit_pct': FALLBACK_TAKE_PROFIT_PERCENTAGE * 100,
                    'first_profit_quantity_pct': 0.4,
                    'trailing_stop_price': trailing_stop_price,
                    'trailing_stop_pct': (FALLBACK_STOP_LOSS_PERCENTAGE / 2) * 100,
                    'atr': 0,
                    'risk_level': 'STATIC',
                    'method': 'FALLBACK',
                    'risk_reward_ratio': risk_reward_ratio
                }

            # 获取K线数据
            klines = self.get_klines_for_symbol(symbol, '1m')
            if not klines or len(klines) < 14:
                logger.warning(f"{symbol} K线数据不足，使用备用方案")
                # 使用备用配置
                atr = entry_price * FALLBACK_STOP_LOSS_PERCENTAGE
            else:
                # 使用ATR计算
                atr = ATRBasedRiskManager.calculate_atr(klines, 14)

            if atr <= 0:
                atr = entry_price * FALLBACK_STOP_LOSS_PERCENTAGE

            # 计算风险参数
            risk_params = ATRBasedRiskManager.calculate_risk_levels(entry_price, klines or [], side)
            risk_params['method'] = 'ATR'

            # 计算盈亏比 (新增)
            stop_loss_distance = abs(entry_price - risk_params['stop_loss_price'])
            take_profit_distance = abs(risk_params['first_profit_price'] - entry_price)
            risk_reward_ratio = take_profit_distance / stop_loss_distance if stop_loss_distance > 0 else 0
            risk_params['risk_reward_ratio'] = risk_reward_ratio

            logger.info(
                f"【{symbol}风险参数】{side}\n"
                f"  入场价: {entry_price:.4f}\n"
                f"  ATR: {risk_params['atr']:.4f} ({risk_params['atr_pct']:.2f}%) → {risk_params['risk_level']}\n"
                f"  止损: {risk_params['stop_loss_price']:.4f} ({risk_params['stop_loss_pct']:.2f}%)\n"
                f"  一止: {risk_params['first_profit_price']:.4f} ({risk_params['first_profit_pct']:.2f}%) [平40%]\n"
                f"  追停: {risk_params['trailing_stop_price']:.4f} ({risk_params['trailing_stop_pct']:.2f}%) [追60%]\n"
                f"  盈亏比: {risk_reward_ratio:.2f}:1 (目标1:3)"
            )

            return risk_params

        except Exception as e:
            logger.error(f"计算风险参数失败: {e}")
            # 返回备用方案（不递归，防止堆栈溢出）
            if side == 'BUY':
                return {
                    'stop_loss_price': entry_price * (1 - FALLBACK_STOP_LOSS_PERCENTAGE),
                    'stop_loss_pct': FALLBACK_STOP_LOSS_PERCENTAGE * 100,
                    'first_profit_price': entry_price * (1 + FALLBACK_TAKE_PROFIT_PERCENTAGE),
                    'first_profit_pct': FALLBACK_TAKE_PROFIT_PERCENTAGE * 100,
                    'first_profit_quantity_pct': 0.4,
                    'trailing_stop_price': entry_price * (1 + FALLBACK_STOP_LOSS_PERCENTAGE / 2),
                    'trailing_stop_pct': (FALLBACK_STOP_LOSS_PERCENTAGE / 2) * 100,
                    'atr': 0,
                    'risk_level': 'ERROR',
                    'method': 'FALLBACK',
                    'risk_reward_ratio': FALLBACK_TAKE_PROFIT_PERCENTAGE / FALLBACK_STOP_LOSS_PERCENTAGE
                }
            else:
                return {
                    'stop_loss_price': entry_price * (1 + FALLBACK_STOP_LOSS_PERCENTAGE),
                    'stop_loss_pct': FALLBACK_STOP_LOSS_PERCENTAGE * 100,
                    'first_profit_price': entry_price * (1 - FALLBACK_TAKE_PROFIT_PERCENTAGE),
                    'first_profit_pct': FALLBACK_TAKE_PROFIT_PERCENTAGE * 100,
                    'first_profit_quantity_pct': 0.4,
                    'trailing_stop_price': entry_price * (1 - FALLBACK_STOP_LOSS_PERCENTAGE / 2),
                    'trailing_stop_pct': (FALLBACK_STOP_LOSS_PERCENTAGE / 2) * 100,
                    'atr': 0,
                    'risk_level': 'ERROR',
                    'method': 'FALLBACK',
                    'risk_reward_ratio': FALLBACK_TAKE_PROFIT_PERCENTAGE / FALLBACK_STOP_LOSS_PERCENTAGE
                }

    def check_stop_loss(
        self,
        symbol: str,
        current_price: float,
        entry_price: float,
        stop_loss_price: float,
        side: str = 'BUY'
    ) -> bool:
        """检查是否触发止损"""
        if side == 'BUY':
            triggered = current_price <= stop_loss_price
        else:
            triggered = current_price >= stop_loss_price

        if triggered:
            logger.warning(
                f"【止损触发】{symbol} {side}\n"
                f"  入场: {entry_price:.4f}, 当前: {current_price:.4f}, 止损线: {stop_loss_price:.4f}\n"
                f"  亏损: {abs((current_price - entry_price) / entry_price * 100):.2f}%"
            )

        return triggered

    def check_first_profit(
        self,
        symbol: str,
        current_price: float,
        entry_price: float,
        first_profit_price: float,
        side: str = 'BUY'
    ) -> bool:
        """检查是否达到第一止盈（快速获利点）"""
        if side == 'BUY':
            hit = current_price >= first_profit_price
        else:
            hit = current_price <= first_profit_price

        if hit:
            profit_pct = abs((current_price - entry_price) / entry_price * 100)
            logger.info(
                f"【第一止盈触发】{symbol} {side}\n"
                f"  入场: {entry_price:.4f}, 当前: {current_price:.4f}\n"
                f"  获利: {profit_pct:.2f}% (平仓40%持仓, 剩余60%跟踪)"
            )

        return hit

    def emergency_close_position(self, symbol: str, quantity: float, side: str = 'BUY'):
        """紧急平仓"""
        try:
            close_side = 'SELL' if side == 'BUY' else 'BUY'

            # 获取币种精度信息并格式化数量
            try:
                exchange_info = self.binance_client.client.futures_exchange_info()
                symbol_info = next((s for s in exchange_info['symbols'] if s['symbol'] == symbol), None)

                if symbol_info:
                    quantity_precision = symbol_info['quantityPrecision']
                    quantity = float(f"{quantity:.{quantity_precision}f}")
            except Exception as e:
                logger.warning(f"获取{symbol}精度失败: {e}")

            logger.warning(
                f"【紧急平仓】{symbol} {side}\n"
                f"  数量: {quantity}, 方向: {close_side}"
            )

            # 取消所有未成交订单
            try:
                self.binance_client.cancel_all_orders(symbol)
            except:
                pass

            # 市价平仓
            order = self.binance_client.client.futures_create_order(
                symbol=symbol,
                side=close_side,
                type='MARKET',
                quantity=quantity
            )

            logger.info(f"✓ 紧急平仓成功: {order['orderId']}")
            return True

        except Exception as e:
            logger.error(f"✗ 紧急平仓失败: {e}")
            return False

    def partial_close_position(
        self,
        symbol: str,
        quantity: float,
        percentage: float,
        side: str = 'BUY'
    ):
        """分批平仓（快速止盈）"""
        try:
            close_quantity = quantity * percentage
            close_side = 'SELL' if side == 'BUY' else 'BUY'

            # 获取当前价格计算订单金额
            try:
                ticker = self.binance_client.client.futures_ticker(symbol=symbol)
                current_price = float(ticker['lastPrice'])
            except:
                current_price = 0

            # 计算订单名义价值
            notional_value = close_quantity * current_price

            # Binance最小订单金额 = 5 USDT
            MIN_NOTIONAL = 5.0

            # 如果分批平仓金额 < 5 USDT，改为全仓平仓
            if notional_value < MIN_NOTIONAL:
                logger.warning(
                    f"【金额不足】{symbol} 分批平仓金额 {notional_value:.2f} USDT < {MIN_NOTIONAL} USDT\n"
                    f"  改为全仓平仓（100%）避免订单失败"
                )
                close_quantity = quantity
                percentage = 1.0

            # 获取币种精度信息
            try:
                exchange_info = self.binance_client.client.futures_exchange_info()
                symbol_info = next((s for s in exchange_info['symbols'] if s['symbol'] == symbol), None)

                if symbol_info:
                    quantity_precision = symbol_info['quantityPrecision']
                    # 根据精度规则格式化数量
                    close_quantity = float(f"{close_quantity:.{quantity_precision}f}")

                    # 如果格式化后为0，至少保留最小精度
                    if close_quantity == 0 and quantity_precision == 0:
                        close_quantity = 1.0
                    elif close_quantity == 0:
                        close_quantity = float(f"1e-{quantity_precision}")
            except Exception as e:
                logger.warning(f"获取{symbol}精度失败，使用原始数量: {e}")

            logger.info(
                f"【分批平仓】{symbol} {side}\n"
                f"  原数量: {quantity:.4f}\n"
                f"  平仓数: {close_quantity} ({percentage*100:.0f}%)\n"
                f"  保留数: {quantity-close_quantity} ({(1-percentage)*100:.0f}%)\n"
                f"  订单金额: {close_quantity * current_price:.2f} USDT"
            )

            # 市价平仓
            order = self.binance_client.client.futures_create_order(
                symbol=symbol,
                side=close_side,
                type='MARKET',
                quantity=close_quantity
            )

            logger.info(f"✓ 分批平仓成功: {order['orderId']}")
            return True

        except Exception as e:
            logger.error(f"✗ 分批平仓失败: {e}")
            return False

    def _run_check(self):
        """执行一次持仓监控检查"""
        try:
            check_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            logger.info(f"\n{'='*100}")
            logger.info(f"【执行检查】时间: {check_time}")
            logger.info(f"{'='*100}")

            # 获取所有持仓
            account_info = self.binance_client.get_account_info()
            positions = account_info.get('positions', [])

            # 筛选有效持仓
            active_positions = []
            for pos in positions:
                position_amt = float(pos.get('positionAmt', 0))
                if position_amt != 0:
                    active_positions.append(pos)

            logger.info(f"发现 {len(active_positions)} 个活跃持仓")

            # 检查每个持仓
            for pos in active_positions:
                symbol = pos['symbol']
                position_amt = float(pos['positionAmt'])
                entry_price = float(pos['entryPrice'])
                unrealized_profit = float(pos['unrealizedProfit'])

                # 获取当前价格（markPrice可能不存在，需要单独获取）
                try:
                    ticker = self.binance_client.client.futures_ticker(symbol=symbol)
                    current_price = float(ticker['lastPrice'])
                except:
                    # 如果API调用失败，尝试从pos中获取
                    current_price = float(pos.get('markPrice', pos.get('lastPrice', entry_price)))

                side = 'BUY' if position_amt > 0 else 'SELL'
                quantity = abs(position_amt)

                # 计算不含杠杆的盈利百分比
                profit_pct = abs((current_price - entry_price) / entry_price * 100)

                logger.info(
                    f"\n【检查持仓】{symbol} ({side})\n"
                    f"  数量: {quantity:.4f}, 入场: {entry_price:.4f}, 当前: {current_price:.4f}\n"
                    f"  浮盈亏: {unrealized_profit:.4f} USDT ({profit_pct:.2f}%)"
                )

                # 计算风险参数
                risk_params = self.calculate_risk_parameters(symbol, entry_price, side)

                # 检查1：止损
                if self.check_stop_loss(
                    symbol, current_price, entry_price,
                    risk_params['stop_loss_price'], side
                ):
                    # 止损触发 → 记录到冷却管理器
                    loss_pct = abs((current_price - entry_price) / entry_price * 100)
                    self.cooldown_manager.record_failure(
                        symbol,
                        f"止损触发，亏损{loss_pct:.2f}%"
                    )
                    self.emergency_close_position(symbol, quantity, side)
                    continue

                # 检查2：第一止盈
                if self.check_first_profit(
                    symbol, current_price, entry_price,
                    risk_params['first_profit_price'], side
                ):
                    # 分批平仓
                    self.partial_close_position(
                        symbol, quantity,
                        risk_params['first_profit_quantity_pct'],
                        side
                    )

                # 检查3：追踪止损
                if current_price >= risk_params['first_profit_price'] if side == 'BUY' else current_price <= risk_params['first_profit_price']:
                    # 仓位已盈利，保留的部分跟踪止损
                    remaining_qty = quantity * (1 - risk_params['first_profit_quantity_pct'])
                    logger.info(
                        f"【追踪止损】{symbol} (剩余数量: {remaining_qty:.4f})\n"
                        f"  追踪价位: {risk_params['trailing_stop_price']:.4f} ({risk_params['trailing_stop_pct']:.2f}%)"
                    )

            logger.info(f"{'='*100}")
            logger.info(f"【检查完成】时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info(f"{'='*100}")

        except Exception as e:
            logger.error(f"执行检查时发生异常: {e}")

    def start(self):
        """启动监控程序"""
        logger.info(f"\n{'='*100}")
        logger.info("【监控程序已启动】")
        logger.info(f"{'='*100}")
        logger.info("按 Ctrl+C 可停止程序\n")

        self.running = True

        try:
            while self.running:
                self._run_check()

                # 等待下一个检查时间
                next_check_time = datetime.now() + timedelta(seconds=self.check_interval)
                wait_seconds = (next_check_time - datetime.now()).total_seconds()

                if wait_seconds > 0:
                    logger.info(f"下一次检查: {next_check_time.strftime('%H:%M:%S')} (等待 {wait_seconds:.0f} 秒)")
                    time.sleep(min(5, wait_seconds))  # 分段睡眠以便响应中断

        except KeyboardInterrupt:
            logger.info("\n收到中断信号，正在停止...")
            self.stop()

    def stop(self):
        """停止监控程序"""
        logger.info(f"{'='*100}")
        logger.info("【监控程序已停止】")
        logger.info(f"{'='*100}")
        self.running = False


def main():
    """主函数"""
    print("""
╔════════════════════════════════════════════════════════════════╗
║       增强版持仓监控程序 v2.0 - ATR基础动态止损/止盈          ║
║                  Enhanced Position Monitor v2.0                ║
╚════════════════════════════════════════════════════════════════╝

核心功能:
  ✓ ATR动态止损/止盈 (自适应波动性)
  ✓ 智能分批止盈 (快速获利 + Trailing Stop)
  ✓ 每个币种独立计算风险参数
  ✓ 完整的持仓保护和风险管理

配置:
  - ATR模式: {}
  - 检查间隔: {}秒
  - K线周期: 1分钟 (ATR计算基础)

按 Ctrl+C 可停止程序
────────────────────────────────────────────────────────────────
""".format("启用 ✓" if ENABLE_ATR_MODE else "禁用", CHECK_INTERVAL))

    try:
        monitor = EnhancedPositionMonitor(check_interval=CHECK_INTERVAL)

        try:
            monitor.start()
        except KeyboardInterrupt:
            logger.info("\n程序被用户中断")
        except Exception as e:
            logger.error(f"程序运行异常: {e}", exc_info=True)
            import traceback
            traceback.print_exc()
            input("按回车键继续...")
    except Exception as e:
        logger.error(f"程序初始化失败: {e}", exc_info=True)
        import traceback
        print(f"\n【错误】程序初始化失败:")
        traceback.print_exc()
        input("按回车键继续...")


if __name__ == "__main__":
    main()

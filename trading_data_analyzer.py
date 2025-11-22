"""
历史交易数据分析工具 (trading_data_analyzer.py)
用于快速拉取和分析过去一段时间的所有入场离场信息
"""

import pandas as pd
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from pathlib import Path
import matplotlib.pyplot as plt
import seaborn as sns
from binance_client_v2 import BinanceClientV2
from config_v2 import API_CONFIG

logger = logging.getLogger(__name__)

@dataclass
class TradeRecord:
    """交易记录"""
    symbol: str
    entry_time: datetime
    exit_time: Optional[datetime]
    entry_price: float
    exit_price: Optional[float]
    quantity: float
    side: str  # LONG/SHORT
    entry_reason: str
    exit_reason: Optional[str]
    profit_loss_usdt: Optional[float]
    profit_loss_pct: Optional[float]
    hold_duration_minutes: Optional[float]
    max_profit_pct: Optional[float]
    max_drawdown_pct: Optional[float]
    signal_score: Optional[int]
    confidence: Optional[float]

@dataclass
class TradingStats:
    """交易统计"""
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_profit_usdt: float
    avg_profit_per_trade: float
    max_profit: float
    max_loss: float
    profit_factor: float
    avg_hold_time_minutes: float
    best_symbol: str
    worst_symbol: str

class TradingDataAnalyzer:
    """交易数据分析器"""

    def __init__(self):
        """初始化分析器"""
        self.binance_client = None
        try:
            self.binance_client = BinanceClientV2(
                api_key=API_CONFIG['binance_key'],
                api_secret=API_CONFIG['binance_secret'],
                testnet=API_CONFIG.get('testnet', False)
            )
            logger.info("Binance客户端初始化成功")
        except Exception as e:
            logger.error(f"Binance客户端初始化失败: {e}")

    def fetch_historical_trades(
        self,
        start_time: datetime,
        end_time: Optional[datetime] = None,
        symbols: Optional[List[str]] = None
    ) -> List[TradeRecord]:
        """
        从Binance获取历史交易记录

        Args:
            start_time: 开始时间
            end_time: 结束时间（默认为当前时间）
            symbols: 指定币种列表（默认获取所有）

        Returns:
            交易记录列表
        """
        if end_time is None:
            end_time = datetime.now()

        if not self.binance_client:
            logger.error("Binance客户端未初始化")
            return []

        logger.info(f"获取 {start_time} 到 {end_time} 的历史交易记录...")

        all_trades = []

        try:
            # 获取期货交易历史
            trades = self.binance_client.client.futures_account_trades(
                startTime=int(start_time.timestamp() * 1000),
                endTime=int(end_time.timestamp() * 1000),
                limit=1000
            )

            logger.info(f"获取到 {len(trades)} 条原始交易记录")

            # 按交易对分组处理
            trades_by_symbol = {}
            for trade in trades:
                symbol = trade['symbol']
                if symbols and symbol not in symbols:
                    continue

                if symbol not in trades_by_symbol:
                    trades_by_symbol[symbol] = []
                trades_by_symbol[symbol].append(trade)

            # 分析每个交易对的开平仓配对
            for symbol, symbol_trades in trades_by_symbol.items():
                trade_records = self._analyze_symbol_trades(symbol, symbol_trades)
                all_trades.extend(trade_records)

            logger.info(f"解析出 {len(all_trades)} 个完整交易记录")
            return all_trades

        except Exception as e:
            logger.error(f"获取历史交易失败: {e}")
            return []

    def _analyze_symbol_trades(self, symbol: str, trades: List[Dict]) -> List[TradeRecord]:
        """
        分析单个交易对的开平仓配对

        Args:
            symbol: 交易对
            trades: 交易列表

        Returns:
            交易记录列表
        """
        # 按时间排序
        trades.sort(key=lambda x: x['time'])

        records = []
        position = 0.0  # 当前仓位
        entry_price = 0.0
        entry_time = None
        entry_trades = []

        for trade in trades:
            qty = float(trade['qty'])
            price = float(trade['price'])
            is_buyer = trade['buyer']  # True=买入，False=卖出
            trade_time = datetime.fromtimestamp(trade['time'] / 1000)

            # 确定方向
            if is_buyer:
                new_position = position + qty
            else:
                new_position = position - qty

            # 检查是否为开仓
            if position == 0:
                # 开新仓
                position = new_position
                entry_price = price
                entry_time = trade_time
                entry_trades = [trade]

            elif (position > 0 and new_position > position) or (position < 0 and new_position < position):
                # 加仓
                entry_price = (entry_price * abs(position) + price * qty) / abs(new_position)
                position = new_position
                entry_trades.append(trade)

            elif (position > 0 and new_position < position) or (position < 0 and new_position > position):
                # 减仓或平仓
                if new_position == 0:
                    # 完全平仓
                    side = "LONG" if position > 0 else "SHORT"
                    profit_loss = self._calculate_pnl(entry_price, price, abs(position), side, entry_trades + [trade])

                    record = TradeRecord(
                        symbol=symbol,
                        entry_time=entry_time,
                        exit_time=trade_time,
                        entry_price=entry_price,
                        exit_price=price,
                        quantity=abs(position),
                        side=side,
                        entry_reason="API交易记录",
                        exit_reason="完全平仓",
                        profit_loss_usdt=profit_loss,
                        profit_loss_pct=(profit_loss / (entry_price * abs(position))) * 100,
                        hold_duration_minutes=(trade_time - entry_time).total_seconds() / 60,
                        signal_score=None,
                        confidence=None,
                        max_profit_pct=None,
                        max_drawdown_pct=None
                    )
                    records.append(record)
                    position = 0

                else:
                    # 部分平仓，继续持有
                    position = new_position

        return records

    def _calculate_pnl(self, entry_price: float, exit_price: float, quantity: float,
                       side: str, trades: List[Dict]) -> float:
        """计算盈亏（包含手续费）"""
        # 价差收益
        if side == "LONG":
            price_diff = (exit_price - entry_price) * quantity
        else:
            price_diff = (entry_price - exit_price) * quantity

        # 计算手续费
        total_fee = 0.0
        for trade in trades:
            total_fee += abs(float(trade['commission']))

        return price_diff - total_fee

    def load_from_logs(self, log_file: str, start_time: datetime, end_time: Optional[datetime] = None) -> List[TradeRecord]:
        """
        从交易引擎日志文件中解析交易记录

        Args:
            log_file: 日志文件路径
            start_time: 开始时间
            end_time: 结束时间

        Returns:
            交易记录列表
        """
        if end_time is None:
            end_time = datetime.now()

        logger.info(f"从日志文件解析交易记录: {log_file}")

        records = []
        current_positions = {}  # {symbol: entry_info}

        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    # 解析时间戳
                    if not line.strip():
                        continue

                    try:
                        timestamp_str = line.split(' - ')[0]
                        log_time = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S,%f')

                        if log_time < start_time or log_time > end_time:
                            continue

                    except:
                        continue

                    # 解析入场信号
                    if "✓ 入场成功:" in line:
                        entry_info = self._parse_entry_log(line, log_time)
                        if entry_info:
                            current_positions[entry_info['symbol']] = entry_info

                    # 解析出场信号
                    elif "✓ 出场成功:" in line or "✓ 紧急平仓完成" in line:
                        exit_info = self._parse_exit_log(line, log_time)
                        if exit_info and exit_info['symbol'] in current_positions:
                            entry_info = current_positions.pop(exit_info['symbol'])

                            record = TradeRecord(
                                symbol=entry_info['symbol'],
                                entry_time=entry_info['time'],
                                exit_time=exit_info['time'],
                                entry_price=entry_info['price'],
                                exit_price=exit_info['price'],
                                quantity=entry_info['quantity'],
                                side=entry_info['side'],
                                entry_reason=entry_info.get('reason', '日志记录'),
                                exit_reason=exit_info.get('reason', '日志记录'),
                                profit_loss_usdt=exit_info.get('profit_loss', 0.0),
                                profit_loss_pct=None,
                                hold_duration_minutes=(exit_info['time'] - entry_info['time']).total_seconds() / 60,
                                signal_score=entry_info.get('signal_score'),
                                confidence=entry_info.get('confidence'),
                                max_profit_pct=None,
                                max_drawdown_pct=None
                            )

                            # 计算盈亏百分比
                            if record.profit_loss_usdt and entry_info['price'] and entry_info['quantity']:
                                record.profit_loss_pct = (record.profit_loss_usdt / (entry_info['price'] * entry_info['quantity'])) * 100

                            records.append(record)

            logger.info(f"从日志解析出 {len(records)} 个交易记录")
            return records

        except Exception as e:
            logger.error(f"解析日志文件失败: {e}")
            return []

    def _parse_entry_log(self, line: str, log_time: datetime) -> Optional[Dict]:
        """解析入场日志"""
        try:
            # ✓ 入场成功: BTCUSDT 仓位大小: 12.50 USDT
            # [实盘] 入场 BTCUSDT BUY x 0.000139 (positionSide: LONG)
            if "仓位大小:" in line:
                parts = line.split()
                symbol = None
                for i, part in enumerate(parts):
                    if part.endswith("USDT:"):
                        symbol = part[:-1]
                        break

                return {
                    'symbol': symbol,
                    'time': log_time,
                    'price': 0.0,  # 需要从其他日志行获取
                    'quantity': 0.0,  # 需要从其他日志行获取
                    'side': 'UNKNOWN',
                    'reason': '入场成功'
                }
        except Exception as e:
            pass
        return None

    def _parse_exit_log(self, line: str, log_time: datetime) -> Optional[Dict]:
        """解析出场日志"""
        try:
            # ✓ 出场成功: BTCUSDT - [实盘] 实际盈亏: -2.50 USDT (-2.08%)
            if "出场成功:" in line and "盈亏:" in line:
                parts = line.split()
                symbol = None
                profit_loss = 0.0

                for i, part in enumerate(parts):
                    if part.endswith("USDT") and not part.endswith(":"):
                        if i > 0 and parts[i-1] in ["盈亏:", "实际盈亏:"]:
                            try:
                                profit_loss = float(part.replace("USDT", ""))
                            except:
                                pass
                    elif ":" in part and part.replace(":", "").endswith("USDT"):
                        symbol = part.replace(":", "")

                return {
                    'symbol': symbol,
                    'time': log_time,
                    'price': 0.0,  # 需要从其他信息推算
                    'reason': '出场成功',
                    'profit_loss': profit_loss
                }
        except Exception as e:
            pass
        return None

    def calculate_statistics(self, trades: List[TradeRecord]) -> TradingStats:
        """计算交易统计"""
        if not trades:
            return TradingStats(
                total_trades=0, winning_trades=0, losing_trades=0, win_rate=0.0,
                total_profit_usdt=0.0, avg_profit_per_trade=0.0, max_profit=0.0,
                max_loss=0.0, profit_factor=0.0, avg_hold_time_minutes=0.0,
                best_symbol="", worst_symbol=""
            )

        # 基础统计
        total_trades = len(trades)
        completed_trades = [t for t in trades if t.profit_loss_usdt is not None]
        winning_trades = len([t for t in completed_trades if t.profit_loss_usdt > 0])
        losing_trades = len([t for t in completed_trades if t.profit_loss_usdt < 0])

        win_rate = winning_trades / max(len(completed_trades), 1) * 100

        # 盈亏统计
        profits = [t.profit_loss_usdt for t in completed_trades if t.profit_loss_usdt is not None]
        total_profit = sum(profits) if profits else 0.0
        avg_profit = total_profit / max(len(profits), 1)
        max_profit = max(profits) if profits else 0.0
        max_loss = min(profits) if profits else 0.0

        # 盈利因子
        gross_profit = sum([p for p in profits if p > 0]) if profits else 0.0
        gross_loss = abs(sum([p for p in profits if p < 0])) if profits else 0.0
        profit_factor = gross_profit / max(gross_loss, 1.0)

        # 持仓时间
        durations = [t.hold_duration_minutes for t in trades if t.hold_duration_minutes is not None]
        avg_hold_time = sum(durations) / max(len(durations), 1) if durations else 0.0

        # 最佳/最差交易对
        symbol_profits = {}
        for trade in completed_trades:
            symbol = trade.symbol
            if symbol not in symbol_profits:
                symbol_profits[symbol] = 0.0
            symbol_profits[symbol] += trade.profit_loss_usdt

        best_symbol = max(symbol_profits, key=symbol_profits.get) if symbol_profits else ""
        worst_symbol = min(symbol_profits, key=symbol_profits.get) if symbol_profits else ""

        return TradingStats(
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            total_profit_usdt=total_profit,
            avg_profit_per_trade=avg_profit,
            max_profit=max_profit,
            max_loss=max_loss,
            profit_factor=profit_factor,
            avg_hold_time_minutes=avg_hold_time,
            best_symbol=best_symbol,
            worst_symbol=worst_symbol
        )

    def export_to_csv(self, trades: List[TradeRecord], filename: str):
        """导出到CSV文件"""
        if not trades:
            logger.warning("没有交易记录可导出")
            return

        # 转换为DataFrame
        data = []
        for trade in trades:
            trade_dict = asdict(trade)
            # 处理datetime对象
            if trade_dict['entry_time']:
                trade_dict['entry_time'] = trade_dict['entry_time'].isoformat()
            if trade_dict['exit_time']:
                trade_dict['exit_time'] = trade_dict['exit_time'].isoformat()
            data.append(trade_dict)

        df = pd.DataFrame(data)
        df.to_csv(filename, index=False, encoding='utf-8-sig')
        logger.info(f"交易记录已导出到: {filename}")

    def generate_report(self, trades: List[TradeRecord], output_file: str = None):
        """生成详细分析报告"""
        stats = self.calculate_statistics(trades)

        report = f"""
# 交易分析报告
生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 总体统计
- 总交易次数: {stats.total_trades}
- 盈利交易: {stats.winning_trades}
- 亏损交易: {stats.losing_trades}
- 胜率: {stats.win_rate:.2f}%
- 总盈亏: {stats.total_profit_usdt:+.2f} USDT
- 平均每笔盈亏: {stats.avg_profit_per_trade:+.2f} USDT
- 最大盈利: {stats.max_profit:+.2f} USDT
- 最大亏损: {stats.max_loss:+.2f} USDT
- 盈利因子: {stats.profit_factor:.2f}
- 平均持仓时间: {stats.avg_hold_time_minutes:.1f} 分钟

## 交易对表现
- 最佳表现: {stats.best_symbol}
- 最差表现: {stats.worst_symbol}

## 交易明细
"""

        # 添加详细交易记录
        for i, trade in enumerate(trades, 1):
            profit_str = f"{trade.profit_loss_usdt:+.2f} USDT" if trade.profit_loss_usdt else "未完成"
            duration_str = f"{trade.hold_duration_minutes:.1f}分钟" if trade.hold_duration_minutes else "进行中"

            report += f"""
{i}. {trade.symbol} - {trade.side}
   入场: {trade.entry_time.strftime('%m-%d %H:%M') if trade.entry_time else 'N/A'} @ {trade.entry_price:.4f}
   出场: {trade.exit_time.strftime('%m-%d %H:%M') if trade.exit_time else '进行中'} @ {trade.exit_price if trade.exit_price else '进行中'}
   盈亏: {profit_str}
   持仓: {duration_str}
"""

        if output_file:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(report)
            logger.info(f"分析报告已保存到: {output_file}")
        else:
            print(report)

    def plot_performance(self, trades: List[TradeRecord], save_path: str = None):
        """绘制交易表现图表"""
        if not trades:
            logger.warning("没有交易数据可绘制")
            return

        completed_trades = [t for t in trades if t.profit_loss_usdt is not None]
        if not completed_trades:
            logger.warning("没有完成的交易数据可绘制")
            return

        # 设置中文字体
        plt.rcParams['font.sans-serif'] = ['SimHei']
        plt.rcParams['axes.unicode_minus'] = False

        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(15, 12))

        # 1. 累计盈亏曲线
        cumulative_pnl = []
        running_total = 0
        for trade in completed_trades:
            running_total += trade.profit_loss_usdt
            cumulative_pnl.append(running_total)

        ax1.plot(cumulative_pnl, linewidth=2, color='blue')
        ax1.axhline(y=0, color='red', linestyle='--', alpha=0.5)
        ax1.set_title('累计盈亏曲线')
        ax1.set_xlabel('交易次数')
        ax1.set_ylabel('累计盈亏 (USDT)')
        ax1.grid(True, alpha=0.3)

        # 2. 盈亏分布直方图
        profits = [t.profit_loss_usdt for t in completed_trades]
        ax2.hist(profits, bins=20, alpha=0.7, color='green', edgecolor='black')
        ax2.axvline(x=0, color='red', linestyle='--', alpha=0.7)
        ax2.set_title('盈亏分布')
        ax2.set_xlabel('盈亏 (USDT)')
        ax2.set_ylabel('频次')

        # 3. 胜率统计
        wins = len([t for t in completed_trades if t.profit_loss_usdt > 0])
        losses = len(completed_trades) - wins
        ax3.pie([wins, losses], labels=['盈利', '亏损'], autopct='%1.1f%%',
                colors=['green', 'red'])
        ax3.set_title(f'胜率统计 (总计 {len(completed_trades)} 笔交易)')

        # 4. 持仓时间分布
        durations = [t.hold_duration_minutes for t in trades if t.hold_duration_minutes]
        if durations:
            ax4.hist(durations, bins=20, alpha=0.7, color='orange', edgecolor='black')
            ax4.set_title('持仓时间分布')
            ax4.set_xlabel('持仓时间 (分钟)')
            ax4.set_ylabel('频次')

        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            logger.info(f"图表已保存到: {save_path}")
        else:
            plt.show()


def main():
    """主函数 - 使用示例"""
    analyzer = TradingDataAnalyzer()

    # 设置分析时间范围
    end_time = datetime.now()
    start_time = end_time - timedelta(days=7)  # 最近7天

    print(f"分析时间范围: {start_time} 到 {end_time}")

    # 方式1: 从Binance API获取交易记录
    print("\n正在从Binance API获取交易记录...")
    trades_api = analyzer.fetch_historical_trades(start_time, end_time)

    # 方式2: 从日志文件解析交易记录
    log_file = "trading_engine.log"
    if Path(log_file).exists():
        print(f"\n正在从日志文件解析交易记录: {log_file}")
        trades_log = analyzer.load_from_logs(log_file, start_time, end_time)
    else:
        trades_log = []

    # 合并所有交易记录
    all_trades = trades_api + trades_log
    print(f"\n总共获取到 {len(all_trades)} 个交易记录")

    if all_trades:
        # 计算统计
        stats = analyzer.calculate_statistics(all_trades)

        # 生成报告
        print("\n生成分析报告...")
        analyzer.generate_report(all_trades, "trading_report.md")

        # 导出CSV
        analyzer.export_to_csv(all_trades, "trading_history.csv")

        # 绘制图表
        analyzer.plot_performance(all_trades, "trading_performance.png")

        print(f"""
分析完成！
- 交易记录: trading_history.csv
- 分析报告: trading_report.md
- 表现图表: trading_performance.png
        """)
    else:
        print("未找到交易记录")


if __name__ == "__main__":
    main()
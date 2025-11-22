"""
增强交易日志系统 (trading_logger_v2.py)
提供结构化日志记录、交易复盘分析和性能统计功能
"""

import logging
import json
import csv
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from pathlib import Path
import threading
from queue import Queue
import time

from config_v2 import DATA_CONFIG


@dataclass
class TradingLogEntry:
    """交易日志条目"""
    timestamp: datetime
    log_type: str  # "SIGNAL", "ENTRY", "EXIT", "ERROR", "PERFORMANCE"
    symbol: str
    event: str
    data: Dict[str, Any]
    session_id: str
    profit_loss: Optional[float] = None
    duration_seconds: Optional[float] = None


@dataclass
class SessionSummary:
    """会话摘要"""
    session_id: str
    start_time: datetime
    end_time: Optional[datetime]
    total_trades: int
    winning_trades: int
    losing_trades: int
    total_pnl: float
    win_rate: float
    profit_factor: float
    max_drawdown: float
    sharpe_ratio: Optional[float]
    avg_trade_duration: float
    top_performers: List[str]
    worst_performers: List[str]
    errors_count: int
    network_issues_count: int


class TradingLogger:
    """增强交易日志记录器"""

    def __init__(self):
        """初始化交易日志系统"""
        self.session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.session_start = datetime.now()

        # 创建日志目录
        self.log_dir = Path(DATA_CONFIG['logs_dir'])
        self.log_dir.mkdir(exist_ok=True, parents=True)

        # 日志文件路径
        self.trading_log_file = self.log_dir / f"trading_{self.session_id}.jsonl"
        self.summary_file = self.log_dir / f"summary_{self.session_id}.json"
        self.csv_file = self.log_dir / f"trades_{self.session_id}.csv"

        # 内存中的日志记录
        self.log_entries: List[TradingLogEntry] = []
        self.trade_records: List[Dict] = []

        # 异步日志写入
        self._log_queue = Queue()
        self._writer_thread = threading.Thread(target=self._log_writer_worker, daemon=True)
        self._writer_thread.start()

        # 统计数据
        self.session_stats = {
            'signals_generated': 0,
            'signals_executed': 0,
            'positions_opened': 0,
            'positions_closed': 0,
            'total_pnl': 0.0,
            'winning_trades': 0,
            'losing_trades': 0,
            'errors_count': 0,
            'network_issues': 0,
            'api_calls_total': 0,
            'api_calls_failed': 0
        }

        # 性能追踪
        self.performance_metrics = {
            'signal_to_execution_time': [],
            'order_fill_time': [],
            'position_hold_duration': [],
            'api_response_times': []
        }

        logger = logging.getLogger(__name__)
        logger.info(f"交易日志系统初始化 - Session ID: {self.session_id}")

    # ==================== 核心日志记录方法 ====================
    def log_signal(self, symbol: str, signal_data: Dict[str, Any], executed: bool = False):
        """记录信号生成日志"""
        entry = TradingLogEntry(
            timestamp=datetime.now(),
            log_type="SIGNAL",
            symbol=symbol,
            event="SIGNAL_GENERATED" if not executed else "SIGNAL_EXECUTED",
            data={
                'direction': signal_data.get('direction'),
                'confidence': signal_data.get('confidence'),
                'score': signal_data.get('score'),
                'entry_price': signal_data.get('entry_price'),
                'stop_loss': signal_data.get('stop_loss'),
                'take_profit_stages': signal_data.get('take_profit_stages'),
                'market_conditions': signal_data.get('market_conditions'),
                'executed': executed
            },
            session_id=self.session_id
        )

        self._add_log_entry(entry)

        # 更新统计
        self.session_stats['signals_generated'] += 1
        if executed:
            self.session_stats['signals_executed'] += 1

    def log_entry(self, symbol: str, entry_data: Dict[str, Any]):
        """记录入场日志"""
        entry = TradingLogEntry(
            timestamp=datetime.now(),
            log_type="ENTRY",
            symbol=symbol,
            event="POSITION_OPENED",
            data={
                'side': entry_data.get('side'),
                'quantity': entry_data.get('quantity'),
                'entry_price': entry_data.get('entry_price'),
                'position_size_usdt': entry_data.get('position_size_usdt'),
                'order_id': entry_data.get('order_id'),
                'fees': entry_data.get('fees'),
                'slippage': entry_data.get('slippage'),
                'execution_time': entry_data.get('execution_time')
            },
            session_id=self.session_id
        )

        self._add_log_entry(entry)
        self.session_stats['positions_opened'] += 1

        # 记录到交易记录
        self.trade_records.append({
            'symbol': symbol,
            'entry_time': datetime.now(),
            'side': entry_data.get('side'),
            'entry_price': entry_data.get('entry_price'),
            'quantity': entry_data.get('quantity'),
            'position_size_usdt': entry_data.get('position_size_usdt'),
            'status': 'OPEN'
        })

    def log_exit(self, symbol: str, exit_data: Dict[str, Any]):
        """记录出场日志"""
        entry = TradingLogEntry(
            timestamp=datetime.now(),
            log_type="EXIT",
            symbol=symbol,
            event="POSITION_CLOSED",
            data={
                'exit_type': exit_data.get('exit_type'),  # "STOP_LOSS", "TAKE_PROFIT", "TIME_STOP"
                'exit_price': exit_data.get('exit_price'),
                'quantity_closed': exit_data.get('quantity'),
                'profit_loss_usdt': exit_data.get('profit_loss'),
                'profit_loss_pct': exit_data.get('profit_loss_pct'),
                'hold_duration': exit_data.get('duration'),
                'order_id': exit_data.get('order_id'),
                'fees_total': exit_data.get('fees'),
                'reason': exit_data.get('reason')
            },
            session_id=self.session_id,
            profit_loss=exit_data.get('profit_loss'),
            duration_seconds=exit_data.get('duration')
        )

        self._add_log_entry(entry)
        self.session_stats['positions_closed'] += 1

        # 更新统计
        pnl = exit_data.get('profit_loss', 0)
        self.session_stats['total_pnl'] += pnl
        if pnl > 0:
            self.session_stats['winning_trades'] += 1
        else:
            self.session_stats['losing_trades'] += 1

        # 更新交易记录状态
        for record in reversed(self.trade_records):
            if record['symbol'] == symbol and record['status'] == 'OPEN':
                record.update({
                    'exit_time': datetime.now(),
                    'exit_price': exit_data.get('exit_price'),
                    'profit_loss': pnl,
                    'profit_loss_pct': exit_data.get('profit_loss_pct'),
                    'duration_seconds': exit_data.get('duration'),
                    'status': 'CLOSED',
                    'exit_reason': exit_data.get('reason')
                })
                break

    def log_error(self, symbol: str, error_data: Dict[str, Any]):
        """记录错误日志"""
        entry = TradingLogEntry(
            timestamp=datetime.now(),
            log_type="ERROR",
            symbol=symbol,
            event=error_data.get('error_type', 'UNKNOWN_ERROR'),
            data={
                'error_message': error_data.get('message'),
                'error_code': error_data.get('code'),
                'stack_trace': error_data.get('stack_trace'),
                'context': error_data.get('context'),
                'recovery_action': error_data.get('recovery_action')
            },
            session_id=self.session_id
        )

        self._add_log_entry(entry)
        self.session_stats['errors_count'] += 1

        # 特殊处理网络错误
        if 'network' in error_data.get('error_type', '').lower():
            self.session_stats['network_issues'] += 1

    def log_performance(self, metric_name: str, value: float, context: Dict[str, Any] = None):
        """记录性能指标"""
        entry = TradingLogEntry(
            timestamp=datetime.now(),
            log_type="PERFORMANCE",
            symbol="",
            event=f"METRIC_{metric_name.upper()}",
            data={
                'metric': metric_name,
                'value': value,
                'unit': context.get('unit', 'ms') if context else 'ms',
                'context': context or {}
            },
            session_id=self.session_id
        )

        self._add_log_entry(entry)

        # 添加到性能追踪
        if metric_name in self.performance_metrics:
            self.performance_metrics[metric_name].append(value)

    # ==================== 异步日志写入 ====================
    def _add_log_entry(self, entry: TradingLogEntry):
        """添加日志条目到队列"""
        self.log_entries.append(entry)
        self._log_queue.put(entry)

    def _log_writer_worker(self):
        """异步日志写入工作线程"""
        while True:
            try:
                entry = self._log_queue.get()
                if entry is None:  # 停止信号
                    break

                # 写入JSON Lines文件
                with open(self.trading_log_file, 'a', encoding='utf-8') as f:
                    log_dict = asdict(entry)
                    log_dict['timestamp'] = entry.timestamp.isoformat()
                    f.write(json.dumps(log_dict, ensure_ascii=False) + '\n')

                self._log_queue.task_done()

            except Exception as e:
                logging.getLogger(__name__).error(f"日志写入异常: {e}")

    # ==================== 分析和复盘功能 ====================
    def generate_session_summary(self) -> SessionSummary:
        """生成会话摘要"""
        total_trades = self.session_stats['winning_trades'] + self.session_stats['losing_trades']
        win_rate = self.session_stats['winning_trades'] / total_trades if total_trades > 0 else 0

        # 计算收益因子
        winning_pnl = sum(entry.profit_loss for entry in self.log_entries
                         if entry.log_type == "EXIT" and entry.profit_loss and entry.profit_loss > 0)
        losing_pnl = abs(sum(entry.profit_loss for entry in self.log_entries
                            if entry.log_type == "EXIT" and entry.profit_loss and entry.profit_loss < 0))

        profit_factor = winning_pnl / losing_pnl if losing_pnl > 0 else float('inf')

        # 计算最大回撤（简化版）
        cumulative_pnl = 0
        peak = 0
        max_drawdown = 0

        for entry in self.log_entries:
            if entry.log_type == "EXIT" and entry.profit_loss:
                cumulative_pnl += entry.profit_loss
                if cumulative_pnl > peak:
                    peak = cumulative_pnl
                drawdown = peak - cumulative_pnl
                if drawdown > max_drawdown:
                    max_drawdown = drawdown

        # 计算平均持仓时间
        hold_durations = [entry.duration_seconds for entry in self.log_entries
                         if entry.log_type == "EXIT" and entry.duration_seconds]
        avg_duration = sum(hold_durations) / len(hold_durations) if hold_durations else 0

        # 找出表现最好/最差的币种
        symbol_pnl = {}
        for record in self.trade_records:
            if record['status'] == 'CLOSED':
                symbol = record['symbol']
                pnl = record.get('profit_loss', 0)
                symbol_pnl[symbol] = symbol_pnl.get(symbol, 0) + pnl

        sorted_symbols = sorted(symbol_pnl.items(), key=lambda x: x[1], reverse=True)
        top_performers = [s[0] for s in sorted_symbols[:3]]
        worst_performers = [s[0] for s in sorted_symbols[-3:]]

        summary = SessionSummary(
            session_id=self.session_id,
            start_time=self.session_start,
            end_time=datetime.now(),
            total_trades=total_trades,
            winning_trades=self.session_stats['winning_trades'],
            losing_trades=self.session_stats['losing_trades'],
            total_pnl=self.session_stats['total_pnl'],
            win_rate=win_rate,
            profit_factor=profit_factor,
            max_drawdown=max_drawdown,
            sharpe_ratio=None,  # 需要更复杂的计算
            avg_trade_duration=avg_duration,
            top_performers=top_performers,
            worst_performers=worst_performers,
            errors_count=self.session_stats['errors_count'],
            network_issues_count=self.session_stats['network_issues']
        )

        return summary

    def export_csv_report(self):
        """导出CSV交易报告"""
        try:
            with open(self.csv_file, 'w', newline='', encoding='utf-8') as f:
                if not self.trade_records:
                    return

                fieldnames = list(self.trade_records[0].keys())
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(self.trade_records)

            logging.getLogger(__name__).info(f"CSV报告已导出: {self.csv_file}")

        except Exception as e:
            logging.getLogger(__name__).error(f"CSV导出失败: {e}")

    def get_symbol_analysis(self, symbol: str) -> Dict[str, Any]:
        """获取特定币种的分析报告"""
        symbol_trades = [r for r in self.trade_records if r['symbol'] == symbol]

        if not symbol_trades:
            return {'error': f'未找到 {symbol} 的交易记录'}

        closed_trades = [t for t in symbol_trades if t['status'] == 'CLOSED']

        if not closed_trades:
            return {'symbol': symbol, 'status': '有持仓但未平仓'}

        total_trades = len(closed_trades)
        winning_trades = len([t for t in closed_trades if t.get('profit_loss', 0) > 0])
        total_pnl = sum(t.get('profit_loss', 0) for t in closed_trades)

        win_rate = winning_trades / total_trades if total_trades > 0 else 0
        avg_pnl = total_pnl / total_trades if total_trades > 0 else 0

        durations = [t.get('duration_seconds', 0) for t in closed_trades if t.get('duration_seconds')]
        avg_duration = sum(durations) / len(durations) if durations else 0

        return {
            'symbol': symbol,
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': total_trades - winning_trades,
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'avg_pnl_per_trade': avg_pnl,
            'avg_duration_seconds': avg_duration,
            'avg_duration_minutes': avg_duration / 60 if avg_duration else 0
        }

    def get_hourly_performance(self) -> Dict[int, Dict[str, float]]:
        """获取按小时分组的表现分析"""
        hourly_stats = {}

        for entry in self.log_entries:
            if entry.log_type == "EXIT" and entry.profit_loss is not None:
                hour = entry.timestamp.hour
                if hour not in hourly_stats:
                    hourly_stats[hour] = {'trades': 0, 'pnl': 0.0, 'wins': 0}

                hourly_stats[hour]['trades'] += 1
                hourly_stats[hour]['pnl'] += entry.profit_loss
                if entry.profit_loss > 0:
                    hourly_stats[hour]['wins'] += 1

        # 计算胜率
        for hour_data in hourly_stats.values():
            hour_data['win_rate'] = hour_data['wins'] / hour_data['trades'] if hour_data['trades'] > 0 else 0

        return hourly_stats

    # ==================== 保存和加载 ====================
    def save_session_summary(self):
        """保存会话摘要到文件"""
        try:
            summary = self.generate_session_summary()
            summary_dict = asdict(summary)

            # 处理datetime序列化
            summary_dict['start_time'] = summary.start_time.isoformat()
            if summary.end_time:
                summary_dict['end_time'] = summary.end_time.isoformat()

            with open(self.summary_file, 'w', encoding='utf-8') as f:
                json.dump(summary_dict, f, ensure_ascii=False, indent=2)

            logging.getLogger(__name__).info(f"会话摘要已保存: {self.summary_file}")
            return summary

        except Exception as e:
            logging.getLogger(__name__).error(f"保存会话摘要失败: {e}")
            return None

    def close(self):
        """关闭日志系统并保存最终报告"""
        # 停止异步写入线程
        self._log_queue.put(None)
        self._writer_thread.join(timeout=5)

        # 生成最终报告
        summary = self.save_session_summary()
        self.export_csv_report()

        logger = logging.getLogger(__name__)
        logger.info("=" * 60)
        logger.info("交易会话完成")
        logger.info("=" * 60)

        if summary:
            logger.info(f"会话ID: {summary.session_id}")
            logger.info(f"运行时间: {(summary.end_time - summary.start_time).total_seconds() / 3600:.1f} 小时")
            logger.info(f"总交易笔数: {summary.total_trades}")
            logger.info(f"胜率: {summary.win_rate:.1%}")
            logger.info(f"总盈亏: {summary.total_pnl:+.2f} USDT")
            logger.info(f"收益因子: {summary.profit_factor:.2f}")
            logger.info(f"最大回撤: {summary.max_drawdown:.2f} USDT")
            logger.info(f"平均持仓时间: {summary.avg_trade_duration / 60:.1f} 分钟")
            if summary.top_performers:
                logger.info(f"表现最佳: {', '.join(summary.top_performers)}")
            if summary.worst_performers:
                logger.info(f"表现最差: {', '.join(summary.worst_performers)}")
            logger.info(f"错误计数: {summary.errors_count}")
            logger.info(f"网络问题: {summary.network_issues_count}")

        logger.info("=" * 60)


# ==================== 全局实例 ====================
_trading_logger_instance = None

def get_trading_logger() -> TradingLogger:
    """获取全局交易日志实例"""
    global _trading_logger_instance
    if _trading_logger_instance is None:
        _trading_logger_instance = TradingLogger()
    return _trading_logger_instance


# ==================== 装饰器支持 ====================
def log_trading_action(action_type: str):
    """交易动作日志装饰器"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            trading_logger = get_trading_logger()
            start_time = time.time()

            try:
                result = func(*args, **kwargs)

                # 记录执行时间
                execution_time = (time.time() - start_time) * 1000
                trading_logger.log_performance(
                    f"{action_type}_execution_time",
                    execution_time,
                    {'function': func.__name__, 'status': 'success'}
                )

                return result

            except Exception as e:
                execution_time = (time.time() - start_time) * 1000
                trading_logger.log_error("", {
                    'error_type': f'{action_type}_ERROR',
                    'message': str(e),
                    'context': {
                        'function': func.__name__,
                        'execution_time': execution_time
                    }
                })
                raise

        return wrapper
    return decorator


if __name__ == "__main__":
    # 测试代码
    logger = TradingLogger()

    # 模拟一些日志记录
    logger.log_signal("BTCUSDT", {
        'direction': 'BULLISH',
        'confidence': 0.85,
        'score': 11,
        'entry_price': 45000
    }, executed=True)

    logger.log_entry("BTCUSDT", {
        'side': 'BUY',
        'quantity': 0.001,
        'entry_price': 45000,
        'position_size_usdt': 45
    })

    time.sleep(2)

    logger.log_exit("BTCUSDT", {
        'exit_type': 'TAKE_PROFIT',
        'exit_price': 45500,
        'quantity': 0.001,
        'profit_loss': 0.5,
        'duration': 120
    })

    summary = logger.generate_session_summary()
    print(f"测试摘要: {summary.total_trades} 笔交易, 盈亏: {summary.total_pnl:.2f}")

    logger.close()
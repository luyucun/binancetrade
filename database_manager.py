"""
数据库管理模块 - 为可视化界面提供数据支持
用于在交易引擎和前端界面之间传递数据
"""

import sqlite3
import json
import pandas as pd
from datetime import datetime
import logging
import os

logger = logging.getLogger(__name__)


class DatabaseManager:
    """数据库管理器 - 处理交易数据的存储和读取"""

    def __init__(self, db_file="data/trading.db"):
        self.db_file = db_file

        # 确保data目录存在
        os.makedirs(os.path.dirname(db_file), exist_ok=True)

        self.init_db()
        logger.info(f"数据库管理器初始化完成: {db_file}")

    def init_db(self):
        """初始化数据库表结构"""
        conn = sqlite3.connect(self.db_file)
        c = conn.cursor()

        # 1. 活跃持仓表 (用于实时监控)
        c.execute('''CREATE TABLE IF NOT EXISTS active_positions
                     (symbol TEXT PRIMARY KEY,
                      side TEXT,
                      entry_price REAL,
                      current_price REAL,
                      quantity REAL,
                      pnl_usdt REAL,
                      pnl_pct REAL,
                      stop_loss REAL,
                      take_profit TEXT,
                      entry_time TEXT,
                      score INTEGER,
                      direction TEXT)''')

        # 2. 系统状态表 (用于显示扫描过程)
        c.execute('''CREATE TABLE IF NOT EXISTS system_status
                     (key TEXT PRIMARY KEY, value TEXT, update_time TEXT)''')

        # 3. 历史交易表 (用于分析)
        c.execute('''CREATE TABLE IF NOT EXISTS trade_history
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      symbol TEXT,
                      action TEXT,
                      price REAL,
                      quantity REAL,
                      time TEXT,
                      pnl REAL,
                      pnl_pct REAL,
                      reason TEXT)''')

        # 4. 扫描结果表 (记录每次扫描的币种过滤情况)
        c.execute('''CREATE TABLE IF NOT EXISTS scan_results
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      scan_time TEXT,
                      total_coins INTEGER,
                      filtered_coins INTEGER,
                      signals_generated INTEGER,
                      market_health TEXT)''')

        conn.commit()
        conn.close()
        logger.info("数据库表结构初始化完成")

    def update_positions(self, positions_dict):
        """
        更新活跃持仓表

        Args:
            positions_dict: 持仓字典 {symbol: Position对象}
        """
        try:
            conn = sqlite3.connect(self.db_file)
            c = conn.cursor()
            c.execute("DELETE FROM active_positions")  # 先清空，全量更新

            for symbol, pos in positions_dict.items():
                # 处理take_profit_levels
                tp_str = json.dumps(
                    pos.take_profit_levels if hasattr(pos, 'take_profit_levels') else []
                )

                # 提取各字段
                side = getattr(pos, 'side', 'UNKNOWN')
                entry_price = getattr(pos, 'entry_price', 0.0)
                current_price = getattr(pos, 'current_price', 0.0)
                quantity = getattr(pos, 'quantity', 0.0)
                pnl_usdt = getattr(pos, 'floating_pnl_usdt', 0.0)
                pnl_pct = getattr(pos, 'floating_pnl_pct', 0.0)
                stop_loss = getattr(pos, 'stop_loss_price', 0.0)
                entry_time = str(getattr(pos, 'entry_time', datetime.now()))

                # 提取信号分数
                score = 0
                if hasattr(pos, 'risk_params') and isinstance(pos.risk_params, dict):
                    score = pos.risk_params.get('signal_score', 0)

                # 提取方向
                direction = getattr(pos, 'direction', side)

                c.execute('''INSERT INTO active_positions VALUES
                             (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                          (symbol, side, entry_price, current_price,
                           quantity, pnl_usdt, pnl_pct,
                           stop_loss, tp_str, entry_time,
                           score, direction))

            conn.commit()
            conn.close()
            logger.debug(f"更新了 {len(positions_dict)} 个持仓到数据库")

        except Exception as e:
            logger.error(f"更新持仓数据库失败: {e}")

    def update_status(self, status_key, status_value):
        """
        更新系统状态

        Args:
            status_key: 状态键 (如 'scan_stage', 'market_health')
            status_value: 状态值
        """
        try:
            conn = sqlite3.connect(self.db_file)
            c = conn.cursor()
            c.execute("REPLACE INTO system_status VALUES (?, ?, ?)",
                      (status_key, str(status_value), str(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"更新系统状态失败: {e}")

    def add_trade_history(self, symbol, action, price, quantity, pnl=0.0, pnl_pct=0.0, reason=""):
        """
        添加交易历史记录

        Args:
            symbol: 币种
            action: 动作 ('OPEN_LONG', 'OPEN_SHORT', 'CLOSE', 'STOP_LOSS', 'TAKE_PROFIT')
            price: 价格
            quantity: 数量
            pnl: 盈亏金额
            pnl_pct: 盈亏百分比
            reason: 原因
        """
        try:
            conn = sqlite3.connect(self.db_file)
            c = conn.cursor()
            c.execute('''INSERT INTO trade_history
                         (symbol, action, price, quantity, time, pnl, pnl_pct, reason)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                      (symbol, action, price, quantity,
                       str(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                       pnl, pnl_pct, reason))
            conn.commit()
            conn.close()
            logger.info(f"记录交易历史: {symbol} {action} @ {price}")
        except Exception as e:
            logger.error(f"添加交易历史失败: {e}")

    def add_scan_result(self, total_coins, filtered_coins, signals_generated, market_health):
        """添加扫描结果记录"""
        try:
            conn = sqlite3.connect(self.db_file)
            c = conn.cursor()
            c.execute('''INSERT INTO scan_results
                         (scan_time, total_coins, filtered_coins, signals_generated, market_health)
                         VALUES (?, ?, ?, ?, ?)''',
                      (str(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                       total_coins, filtered_coins, signals_generated, market_health))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"添加扫描结果失败: {e}")

    # ==================== 前端读取接口 ====================

    def get_active_positions_df(self):
        """供前端读取：获取持仓DataFrame"""
        try:
            conn = sqlite3.connect(self.db_file)
            df = pd.read_sql_query("SELECT * FROM active_positions", conn)
            conn.close()
            return df
        except Exception as e:
            logger.error(f"读取持仓数据失败: {e}")
            return pd.DataFrame()

    def get_status(self, key):
        """
        供前端读取状态

        Returns:
            (value, update_time) 或 (None, None)
        """
        try:
            conn = sqlite3.connect(self.db_file)
            c = conn.cursor()
            c.execute("SELECT value, update_time FROM system_status WHERE key=?", (key,))
            res = c.fetchone()
            conn.close()
            return res if res else (None, None)
        except Exception as e:
            logger.error(f"读取系统状态失败: {e}")
            return (None, None)

    def get_trade_history_df(self, limit=100):
        """获取交易历史DataFrame"""
        try:
            conn = sqlite3.connect(self.db_file)
            df = pd.read_sql_query(
                f"SELECT * FROM trade_history ORDER BY id DESC LIMIT {limit}",
                conn
            )
            conn.close()
            return df
        except Exception as e:
            logger.error(f"读取交易历史失败: {e}")
            return pd.DataFrame()

    def get_scan_history_df(self, limit=50):
        """获取扫描历史DataFrame"""
        try:
            conn = sqlite3.connect(self.db_file)
            df = pd.read_sql_query(
                f"SELECT * FROM scan_results ORDER BY id DESC LIMIT {limit}",
                conn
            )
            conn.close()
            return df
        except Exception as e:
            logger.error(f"读取扫描历史失败: {e}")
            return pd.DataFrame()


# ==================== 测试函数 ====================
if __name__ == "__main__":
    # 测试数据库管理器
    logging.basicConfig(level=logging.INFO)

    db = DatabaseManager("data/trading_test.db")

    # 测试更新状态
    db.update_status("scan_stage", "Testing: Step 1")
    db.update_status("market_health", "EXCELLENT")
    db.update_status("last_scan_time", datetime.now().strftime("%H:%M:%S"))

    # 测试读取状态
    val, time = db.get_status("scan_stage")
    print(f"读取状态: {val} @ {time}")

    # 测试添加交易历史
    db.add_trade_history("BTCUSDT", "OPEN_LONG", 45000.0, 0.001, 0, 0, "测试开仓")

    # 读取交易历史
    history_df = db.get_trade_history_df()
    print("\n交易历史:")
    print(history_df)

    print("\n数据库管理器测试完成！")

import os
from pathlib import Path

# 基础交易配置
ENTRY_USDT = 20.0          # 固定开仓名义
ATR_PERIOD = 14
CHECK_INTERVAL = 10        # 主循环间隔(秒)
MIN_TREND_BARS = 5         # 检查K线根数（5根中4根同向）
MAX_POSITIONS = 5          # 最多持仓数
LEVERAGE = 1
HEDGE_MODE = True          # 使用双向持仓
MARGIN_TYPE = "CROSSED"

# 从旧配置读取API
try:
    from config_v2 import API_CONFIG
    API_KEY = API_CONFIG["binance_key"]
    API_SECRET = API_CONFIG["binance_secret"]
    TESTNET = API_CONFIG.get("testnet", False)
except Exception:
    API_KEY = os.getenv("BINANCE_KEY", "")
    API_SECRET = os.getenv("BINANCE_SECRET", "")
    TESTNET = False

# 日志文件 - 使用绝对路径保存在项目目录
_PROJECT_DIR = Path(__file__).resolve().parent
LOG_FILE = str(_PROJECT_DIR / "simple_trading.log")

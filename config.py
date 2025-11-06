# 交易配置参数 - 所有参数在此集中管理

# ==================== API配置 ====================
BINANCE_API_KEY = "imYdWlm5XWjKRi9SPm6vFvf9m95MQ5Sy24pDvkAVh7MaNAQ2SMl2HsCEb9QA6kTo"
BINANCE_API_SECRET = "nt6zojBmMkNOnA5WsTvpBh2pORcCxBYEQQinSo8dbWQdu320KKk5CS6hLYsGd1QF"

# ==================== 交易参数配置 ====================
# 基础交易金额（USDT，不含杠杆）
BASE_TRADE_AMOUNT = 2
# 杠杆倍数
LEVERAGE = 10
# 止盈止损波动百分比
STOP_LOSS_PERCENTAGE = 0.005  # 0.5% 浮亏时平仓（扫描过程中检测，不设定止损单）
TAKE_PROFIT_PERCENTAGE = 0.01  # 1% 止盈

# ==================== 保本移动配置 ====================
# 是否启用保本移动（当利润达到阈值时，把止损改为开仓价）
ENABLE_BREAKEVEN_MOVE = True
# 触发保本移动的利润阈值（0.3% = 当价格比开仓价高0.3%时触发）
BREAKEVEN_TRIGGER = 0.003  # 0.3%
# 保本移动后的止损距离（0.1% = 开仓价上方0.1%，确保不会被正常波动触发）
BREAKEVEN_STOP_DISTANCE = 0.001  # 0.1%

# 实际成交量 = BASE_TRADE_AMOUNT * LEVERAGE
ACTUAL_TRADE_AMOUNT = BASE_TRADE_AMOUNT * LEVERAGE  # 20 USDT

# 止盈止损收益率（基于杠杆计算）
TAKE_PROFIT_RATE = TAKE_PROFIT_PERCENTAGE * LEVERAGE  # 5%
STOP_LOSS_RATE = -STOP_LOSS_PERCENTAGE * LEVERAGE  # -5%

# ==================== 币种筛选参数 ====================
# 交易目标筛选方式
# 选项: "volume" (交易量) 或 "gainers_losers" (涨跌幅榜)
COIN_SELECTION_MODE = "gainers_losers"

# 涨跌幅榜模式下的配置
# 涨幅榜前N的币种
GAINERS_LIMIT = 10
# 跌幅榜前N的币种
LOSERS_LIMIT = 10
# 总共交易的币种数 = GAINERS_LIMIT + LOSERS_LIMIT
TOTAL_COINS = GAINERS_LIMIT + LOSERS_LIMIT  # 20个币种

# 交易量排名模式下的配置 (已废弃，保留兼容性)
# 日交易量排名前N的币种
TOP_VOLUME_LIMIT = 200

# 必须是U本位合约交易对
QUOTE_ASSET = "USDT"
TRADING_TYPE = "perpetual"  # 永续合约

# ==================== K线参数 ====================
# K线时间间隔
KLINE_INTERVAL = "1m"  # 1分钟
# 需要检查的K线根数（需要5根连续相同的K线）
REQUIRED_KLINES = 5

# ==================== 定时任务参数 ====================
# 每个整3分钟执行一次检查（单位：秒）
CHECK_INTERVAL = 180  # 3分钟
# 孤立订单清理间隔（单位：秒）
ORPHANED_CLEANUP_INTERVAL = 600  # 10分钟

# ==================== 性能优化参数 ====================
# 币种判断失败后，暂停检查的轮数（2轮 = 10分钟）
SKIP_ROUNDS_AFTER_FAIL = 2
# 并发检查币种数量
MAX_CONCURRENT_CHECKS = 5
# API请求超时时间
API_TIMEOUT = 30  # 秒

# ==================== 日志与监控参数 ====================
LOG_LEVEL = "INFO"
# 是否启用调试模式（调试模式不会真实下单）
DEBUG_MODE = False

# ==================== 策略选择参数 ====================
# 选择交易策略
# 选项: "v1"(多指标确认), "v2"(事件驱动), "v3"(配对交易), "original"(原始策略)
TRADING_STRATEGY = "v1"

# 凯利公式仓位管理
ENABLE_KELLY_SIZING = True  # 是否启用动态凯利公式仓位管理
KELLY_CONSERVATIVE_FACTOR = 0.25  # 凯利保守系数 (使用凯利值的25%-50%)

# 风险管理参数
ENABLE_RISK_MANAGEMENT = True  # 是否启用三层防线风险管理
MAX_DAILY_LOSS_PERCENT = 0.03  # 每日最大亏损比例 (3%)
MAX_SINGLE_TRADE_RISK_PERCENT = 0.005  # 单笔最大风险比例 (0.5%)
MAX_CONCURRENT_POSITIONS_LIMIT = 8  # 最大并发持仓数

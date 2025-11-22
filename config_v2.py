# ==========================================
# 新一代自动化交易系统 - 完整配置文件 (v2.0)
# ==========================================
# 基于多时间框架、多维度过滤的专业交易系统
# ==========================================

# ==================== 1. 选币策略配置 ====================
SELECTION_CONFIG = {
    'min_24h_volume': 80000000,     # 🔧 最小24小时交易量8000万USDT
    'max_24h_change': 50.0,         # 🔧 最大24小时涨跌幅±50%（放宽，允许波动大的币）
    'min_price': 0.000001,          # 🔧 最小价格0.000001（几乎不限制，允许低价币）
    'exclude_patterns': ['1000', 'BULL', 'BEAR', 'UP', 'DOWN'],  # 排除杠杆代币
    'top_n_by_volume': 70,          # 🔧 交易量前70的币种
    'volume_ratio_threshold': 1.3,  # 🔧 当前成交量/平均成交量 > 1.3（从2.0降低到1.3）

    # 🔧 新增：过滤上市未满72h的合约
    'min_listing_hours': 72,        # 最少上市72小时
    'min_trade_count_24h': 50000,   # 24h最少交易笔数，过滤成交稀少的币种
}

# ==================== 2. 多时间框架配置 ====================
TIMEFRAME_CONFIG = {
    'primary_tf': '3m',      # 主时间框架：3分钟（精准入场）
    'confirmation_tf': '5m', # 确认时间框架：5分钟（动量确认）
    'trend_tf': '15m',       # 趋势时间框架：15分钟（总体趋势）

    'data_requirements': {
        '3m': 40,   # 🔧 从50降到40根3分钟K线（2小时）
        '5m': 20,   # 需要20根5分钟K线（1.6小时）
        '15m': 30   # 🔧 从50降到30根15分钟K线（7.5小时），确保能计算EMA50
    }
}

# ==================== 3. 趋势判断配置 ====================
TREND_RULES = {
    # 多头条件
    'bullish': {
        'primary_tf': {
            'ema20_gt_ema50': True,           # EMA20 > EMA50
            'price_gt_ema21': True,           # 价格 > EMA21
            'rsi_range': [40, 70],            # RSI在40-70之间
        },
        'confirmation_tf': {
            'macd_positive': True,            # MACD > 0
            'macd_slope_positive': True,      # MACD斜率为正
            'price_gt_recent_high_10': True,  # 突破10周期高点
        },
        'trend_tf': {
            'ema20_gt_ema50': True,           # 15m级别EMA20 > EMA50
        }
    },
    # 空头条件
    'bearish': {
        'primary_tf': {
            'ema20_lt_ema50': True,           # EMA20 < EMA50
            'price_lt_ema21': True,           # 价格 < EMA21
            'rsi_range': [30, 60],            # RSI在30-60之间
        },
        'confirmation_tf': {
            'macd_negative': True,            # MACD < 0
            'macd_slope_negative': True,      # MACD斜率为负
            'price_lt_recent_low_10': True,   # 突破10周期低点
        },
        'trend_tf': {
            'ema20_lt_ema50': True,           # 15m级别EMA20 < EMA50
        }
    }
}

# ==================== 4. 入场信号规则 ====================
ENTRY_RULES = {
    # 突破入场（放宽条件）
    'breakout': {
        'lookback_period': 10,      # 回看10周期
        'confirmation_bars': 3,     # 需要3根确认K线
        'volume_boost': 1.3,        # 🔧 成交量放大30%（从1.6降低到1.3）
    },

    # 趋势回调入场
    'pullback': {
        'rsi_range': [35, 65],      # RSI在35-65之间
        'price_to_ema': 0.995,      # 价格回撤到EMA的99.5%
        'macd_histogram': 'improving'  # MACD柱状图改善
    },

    # 多重时间框架确认（更严格）
    'multi_tf_confirmation': {
        'required_score': 4,        # 需要4分确认分数（更严格）
        'factors': [
            'primary_tf_trend',     # 主时间框架趋势
            'confirmation_tf_momentum',  # 确认时间框架动量
            'volume_confirmation',  # 成交量确认
            'rsi_alignment',        # RSI方向一致
            'market_structure'      # 市场结构突破
        ]
    }
}

# ==================== 5. 风险管理规则 ====================
RISK_MANAGEMENT = {
    # 仓位管理
    'position_sizing': {
        'base_amount': 12,          # 基础仓位12 USDT (确保信心度50%时仍≥5)
        'leverage': 1,              # 1倍杠杆
        'max_position_ratio': 0.1,  # 单币种最大仓位10%
        'max_total_exposure': 0.3,  # 总风险暴露30%
        'min_notional': 5.5,        # 最小名义价值5.5 USDT (留余量)
    },

    # 动态止损
    'stop_loss': {
        'initial_atr_multiplier': 1.2,    # 初始止损1.2×ATR
        'volatility_adjustment': True,    # 根据波动率调整
        'min_stop_pct': 1.0,              # 🔧 最小止损1.0%（从0.6%提高到1.0%）
        'max_stop_pct': 8.0,              # 🔧 最大止损8.0%（从3.0%提高到8.0%，允许高波动币）
        'breakeven_trigger': 1.0,         # 🔧 盈利1.0×ATR时保本
        'high_volatility_multiplier': 1.5, # 🔧 高波动币种使用max(ATR*1.5, min_stop_pct)
    },

    # 分阶段止盈（更大利润期望）
    'take_profit': {
        'stage1': {
            'trigger': 0.8,         # 🔧 0.8×ATR触发（从1.0降低到0.8，更容易触发）
            'close_pct': 0.25,      # 平仓25%
            'move_stop_to_breakeven': True,
            'enable_trailing_stop': False  # Stage1不启用追踪止损
        },
        'stage2': {
            'trigger': 1.4,         # 🔧 1.4×ATR触发（从1.6降低到1.4）
            'close_pct': 0.35,      # 平仓35%
            'move_stop_to_breakeven_plus': True,
            'enable_trailing_stop': True   # Stage2后启动追踪止损
        },
        'stage3': {
            'trigger': 2.0,         # 🔧 2.0×ATR触发（从2.2降低到2.0）
            'trailing_stop': True,  # 启用追踪止损
            'trailing_atr_multiplier': 1.2  # 1.2×ATR追踪
        }
    }
}

# ==================== 6. 市场状态过滤 ====================
MARKET_FILTERS = {
    # BTC市场状态
    'btc_condition': {
        'max_1m_volatility': 0.030,     # 🔧 BTC 1分钟波动不超过3.0%（防止插针时开单）
        'rsi_15m_range': [0, 100],      # 🔧 完全忽略BTC的RSI限制
        'trend_alignment': 'reference_only' # 🔧 BTC趋势仅作参考，不强制要求
    },

    # 整体市场过滤
    'market_health': {
        'fear_greed_threshold': 30,     # 恐惧贪婪指数>30
        'volume_decline_threshold': 0.5, # 成交量下降不超过50%
        'volatility_spike_threshold': 2.0 # 波动率飙升不超过2倍
    },

    # 时间过滤
    'time_filters': {
        'avoid_high_impact_events': True, # 避开重大事件
        'session_preference': 'asian_european', # 偏好亚欧时段
        'weekend_reduce_exposure': True   # 周末降低风险暴露
    }
}

# ==================== 6.1 入场防抖（硬门槛） ====================
# 说明：
# - atr_pct_min/atr_pct_max 使用小数表示占比（例如 0.004 = 0.4%）
# - 用于过滤"波动太小没有空间覆盖成本"和"波动太大滑点与风险过高"的行情
ENTRY_GUARDS = {
    'atr_pct_min': 0.001,  # 🔧 0.1%（从0.2%降低到0.1%，进一步放宽门槛）
    'atr_pct_max': 0.040,  # 🔧 4.0%（从3.0%放宽到4.0%）
}

# ==================== 7. 信号评分系统 ====================
SCORING_SYSTEM = {
    'trend_strength': {
        'multi_tf_alignment': 2,    # 多时间框架对齐 +2分
        'ema_slope_steep': 1,       # EMA斜率陡峭 +1分
        'price_above_key_levels': 1 # 价格突破关键位 +1分
    },

    'momentum': {
        'rsi_trend_aligned': 1,     # RSI与趋势一致 +1分
        'macd_histogram_rising': 1, # MACD柱状图上升 +1分
        'volume_increasing': 2      # 成交量放大 +2分
    },

    'risk_reward': {
        'atr_optimal_range': 1,     # ATR在最优范围 +1分
        'clear_support_resistance': 1, # 明确支撑阻力 +1分
        'market_structure_break': 2  # 市场结构突破 +2分
    },

    'thresholds': {
        'minimum_score': 5,         # 🔧 最低得分从7降低到5（大幅放宽）
        'high_confidence': 7,       # 🔧 高信心得分从8降低到7
        'maximum_position_size': 12 # 最大仓位得分12分
    }
}

# ==================== 8. 冷却和轮动机制 ====================
ROTATION_SYSTEM = {
    'cooldown_periods': {
        'after_stop_loss': 90,      # 🔧 止损后冷却60-90分钟
        'after_take_profit': 10,    # 止盈后冷却10分钟
        'after_multiple_losses': 180 # 多次亏损后冷却180分钟（更长，从60提高到180）
    },

    'symbol_rotation': {
        'max_concurrent_positions': 6,  # 最大同时持仓6个（扩大持仓容量）
        'sector_diversification': True, # 板块分散
        'correlation_threshold': 0.7,   # 相关性阈值0.7
        'performance_review_interval': 24, # 每24小时评估表现
        # 🔧 新增：每日交易限制和相关性控制
        'max_daily_trades_per_symbol': 2,  # 同一标的日内最多2笔
        'correlation_symbol_limit': 1      # 相关性>0.7的候选只保留评分最高一个
    },

    'dynamic_adjustment': {
        'win_rate_adjustment': True,    # 根据胜率调整
        'market_volatility_adjustment': True, # 根据市场波动调整
        'position_sizing_adjustment': True   # 动态仓位调整
    }
}

# ==================== 9. 执行和监控 ====================
EXECUTION_SYSTEM = {
    'order_placement': {
        'order_type': 'MARKET',         # 市价单
        'slippage_control': True,       # 滑点控制
        'partial_fill_handling': True,  # 部分成交处理
        'timeout_seconds': 10,          # 订单超时10秒
        'maker_timeout_seconds': 2      # Maker订单等待时间（从3秒优化到2秒）
    },

    'position_monitoring': {
        'check_interval': 10,           # 每10秒检查一次
        'real_time_price_updates': True, # 实时价格更新
        'auto_adjust_stops': True,      # 自动调整止损
        'emergency_close_conditions': [ # 紧急平仓条件
            'network_issues',
            'exchange_maintenance',
            'extreme_volatility'
        ]
    },

    'performance_tracking': {
        'track_metrics': [
            'win_rate', 'profit_factor', 'sharpe_ratio',
            'max_drawdown', 'avg_trade_duration'
        ],
        'review_interval': 'daily',     # 每日回顾
        'adjust_strategy_based_on_performance': True # 基于表现调整策略
    }
}

# ==================== 10. 技术指标参数 ====================
INDICATOR_CONFIG = {
    'ema': {
        'short_period': 21,    # 短期EMA
        'long_period': 50,     # 长期EMA
    },
    'macd': {
        'fast_period': 12,
        'slow_period': 26,
        'signal_period': 9,
    },
    'rsi': {
        'period': 14,
        'overbought': 70,
        'oversold': 30,
    },
    'atr': {
        'period': 14,
    },
    'bb': {
        'period': 20,
        'std_dev': 2,
    }
}

# ==================== 11. API和系统配置 ====================
API_CONFIG = {
    'binance_key': 'imYdWlm5XWjKRi9SPm6vFvf9m95MQ5Sy24pDvkAVh7MaNAQ2SMl2HsCEb9QA6kTo',
    'binance_secret': 'nt6zojBmMkNOnA5WsTvpBh2pORcCxBYEQQinSo8dbWQdu320KKk5CS6hLYsGd1QF',
    'testnet': False,                     # ✅ 实盘模式: MAINNET
    'paper_trading': False,               # 🚨 实盘交易模式: 使用真实资金
    'require_explicit_mainnet_confirmation': True,  # 实盘需显式确认
    'timeout': 30,                        # API超时（秒）
    'max_retries': 5,                     # 最大重试次数（已优化）
    'retry_base_delay': 0.5,              # 重试基础延迟（秒）
    'retry_max_delay': 5.0,               # 重试最大延迟（秒）

    # 🔧 代理配置 (用于绕过地区限制)
    'use_proxy': True,                    # ⚠️ 开启代理访问Binance
    'proxy': {
        # Shadowsocks通常使用SOCKS5代理
        # 使用 socks5h:// 让代理进行DNS解析，避免本地DNS污染
        'http': 'socks5h://127.0.0.1:1080',   # SOCKS5代理 (Shadowsocks默认端口)
        'https': 'socks5h://127.0.0.1:1080',  # SOCKS5代理
    }
}

# ==================== 11.1 成本与费率配置（以bps为单位） ====================
# 说明：
# - bps = 基点 = 0.01%（例如 5 bps = 0.05%）
# - taker_fee_bps / maker_fee_bps 按你的实际费率设置
# - slippage_bps 为预估滑点（单边），用于入场"最小边际收益"判断
# - min_edge_bps 是最低要求的"首段收益空间"门槛
COST_CONFIG = {
    'maker_fee_bps': 2.0,   # 0.02%
    'taker_fee_bps': 5.0,   # 0.05%
    'slippage_bps': 2.0,    # 0.02%（单边预估滑点，调低以更贴近实际）
    'min_edge_bps': 12.0    # 🔧 从35.0降至12.0：首段只需覆盖基本手续费+微利，Stage2/3去赚大钱
}

SYSTEM_CONFIG = {
    'main_loop_interval': 10,            # 主循环间隔（秒）
    'kline_fetch_interval': 60,          # K线数据获取间隔（秒）
    'signal_check_interval': 60,         # 信号检查间隔（秒）
    'position_check_interval': 10,       # 持仓检查间隔（秒）
    'max_concurrent_tasks': 10,          # 最大并发任务数
    'log_level': 'DEBUG',                # 🔧 临时改为DEBUG，诊断问题后改回INFO
    'debug_mode': False,                 # 调试模式
    'max_entries_per_hour': 20,           # 每小时最大开仓次数
    'daily_loss_limit_usdt': 1000.0,     # 单日亏损限制（USDT），达到后停止新开仓
}

# ==================== 12. 数据存储配置 ====================
DATA_CONFIG = {
    'data_dir': './data',               # 数据目录
    'logs_dir': './logs',               # 日志目录
    'db_file': './data/trading.db',     # 数据库文件
    'backup_interval': 3600,            # 备份间隔（秒）
}

# ==================== 13. 告警和通知 ====================
NOTIFICATION_CONFIG = {
    'enable_notifications': True,        # 是否启用通知
    'notification_channels': [
        # 'email',    # 邮件
        # 'webhook',  # webhook
        'log'       # 日志
    ],
    'critical_events': [
        'order_failed',
        'position_liquidated',
        'api_error',
        'network_error'
    ]
}

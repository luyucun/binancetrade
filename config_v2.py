# ==========================================
# 新一代自动化交易系统 - 完整配置文件 (v2.0)
# ==========================================
# 基于多时间框架、多维度过滤的专业交易系统
# ==========================================

# ==================== 1. 选币策略配置 ====================
SELECTION_CONFIG = {
    'min_24h_volume': 5000000,      # 最小24小时交易量500万USDT
    'max_24h_change': 15.0,         # 最大24小时涨跌幅±15%
    'min_price': 0.001,             # 最小价格过滤
    'exclude_patterns': ['1000', 'BULL', 'BEAR', 'UP', 'DOWN'],  # 排除杠杆代币
    'top_n_by_volume': 60,          # 交易量前60的币种（持续监控）
    'volume_ratio_threshold': 1.2,  # 当前成交量/平均成交量 > 1.2
}

# ==================== 2. 多时间框架配置 ====================
TIMEFRAME_CONFIG = {
    'primary_tf': '3m',      # 主时间框架：3分钟（精准入场）
    'confirmation_tf': '5m', # 确认时间框架：5分钟（动量确认）
    'trend_tf': '15m',       # 趋势时间框架：15分钟（总体趋势）

    'data_requirements': {
        '3m': 50,   # 需要50根3分钟K线（2.5小时）
        '5m': 20,   # 需要20根5分钟K线（1.6小时）
        '15m': 10   # 需要10根15分钟K线（2.5小时）
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
    # 突破入场
    'breakout': {
        'lookback_period': 10,      # 回看10周期
        'confirmation_bars': 2,     # 需要2根确认K线
        'volume_boost': 1.3,        # 成交量放大30%
    },

    # 趋势回调入场
    'pullback': {
        'rsi_range': [35, 65],      # RSI在35-65之间
        'price_to_ema': 0.995,      # 价格回撤到EMA的99.5%
        'macd_histogram': 'improving'  # MACD柱状图改善
    },

    # 多重时间框架确认
    'multi_tf_confirmation': {
        'required_score': 3,        # 需要3分确认分数
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
        'min_stop_pct': 0.4,              # 最小止损0.4%（百分数表示，实际0.004）
        'max_stop_pct': 3.0,              # 最大止损3.0%（百分数表示，实际0.03）
        'breakeven_trigger': 0.5,         # 盈利0.5×ATR时保本
    },

    # 分阶段止盈
    'take_profit': {
        'stage1': {
            'trigger': 0.8,         # 0.8×ATR触发
            'close_pct': 0.4,       # 平仓40%
            'move_stop_to_breakeven': True
        },
        'stage2': {
            'trigger': 1.2,         # 1.2×ATR触发
            'close_pct': 0.3,       # 平仓30%
            'move_stop_to_breakeven_plus': True
        },
        'stage3': {
            'trigger': 1.8,         # 1.8×ATR触发
            'trailing_stop': True,  # 启用追踪止损
            'trailing_atr_multiplier': 1.0  # 1.0×ATR追踪
        }
    }
}

# ==================== 6. 市场状态过滤 ====================
MARKET_FILTERS = {
    # BTC市场状态
    'btc_condition': {
        'max_1m_volatility': 0.02,      # BTC 1分钟波动不超过2%
        'rsi_15m_range': [25, 75],      # BTC 15分钟RSI在25-75之间
        'trend_alignment': 'non_reverse'  # 非反向：不能与我们的交易方向相反
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
        'minimum_score': 7,         # 最低得分7分才入场 (从5提高到7)
        'high_confidence': 8,       # 高信心得分8分
        'maximum_position_size': 12 # 最大仓位得分12分
    }
}

# ==================== 8. 冷却和轮动机制 ====================
ROTATION_SYSTEM = {
    'cooldown_periods': {
        'after_stop_loss': 30,      # 止损后冷却30分钟
        'after_take_profit': 10,    # 止盈后冷却10分钟
        'after_multiple_losses': 60 # 多次亏损后冷却60分钟
    },

    'symbol_rotation': {
        'max_concurrent_positions': 3,  # 最大同时持仓3个
        'sector_diversification': True, # 板块分散
        'correlation_threshold': 0.7,   # 相关性阈值0.7
        'performance_review_interval': 24 # 每24小时评估表现
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
        'timeout_seconds': 10           # 订单超时10秒
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
    'testnet': False,                     # ⚠️ 实盘模式: 设置为False使用MAINNET
    'require_explicit_mainnet_confirmation': True,  # 实盘需显式确认
    'timeout': 30,                        # API超时（秒）
    'max_retries': 5,                    # 最大重试次数
}

SYSTEM_CONFIG = {
    'main_loop_interval': 10,            # 主循环间隔（秒）
    'kline_fetch_interval': 60,          # K线数据获取间隔（秒）
    'signal_check_interval': 60,         # 信号检查间隔（秒）
    'position_check_interval': 10,       # 持仓检查间隔（秒）
    'max_concurrent_tasks': 10,          # 最大并发任务数
    'log_level': 'INFO',                 # 日志级别
    'debug_mode': False,                 # 调试模式
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

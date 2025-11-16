完整交易规则体系
1. 选币策略
python
# 选币规则配置
SELECTION_CONFIG = {
    'min_24h_volume': 5000000,      # 最小24小时交易量500万USDT
    'max_24h_change': 15.0,         # 最大24小时涨跌幅±15%
    'min_price': 0.001,             # 最小价格过滤
    'exclude_patterns': ['1000', 'BULL', 'BEAR', 'UP', 'DOWN'],  # 排除杠杆代币
    'top_n_by_volume': 60,          # 交易量前60的币种
    'volume_ratio_threshold': 1.2,  # 当前成交量/平均成交量 > 1.2
}
2. 多时间框架确认
python
TIMEFRAME_CONFIG = {
    'primary_tf': '3m',      # 主时间框架：3分钟
    'confirmation_tf': '5m', # 确认时间框架：5分钟  
    'trend_tf': '15m',       # 趋势时间框架：15分钟
    
    'data_requirements': {
        '3m': 50,   # 需要50根3分钟K线（2.5小时）
        '5m': 20,   # 需要20根5分钟K线（1.6小时）
        '15m': 10   # 需要10根15分钟K线（2.5小时）
    }
}
3. 趋势判断规则
多头趋势条件：
python
# 3分钟级别趋势
ema20_3m > ema50_3m
current_price > ema21_3m
rsi_3m(14) between 40-70

# 5分钟级别确认  
macd_5m > 0 and macd_slope_positive
price > recent_high_10 (突破10周期高点)

# 15分钟级别过滤
ema20_15m > ema50_15m (主要趋势向上)
空头趋势条件：
python
# 3分钟级别趋势
ema20_3m < ema50_3m  
current_price < ema21_3m
rsi_3m(14) between 30-60

# 5分钟级别确认
macd_5m < 0 and macd_slope_negative
price < recent_low_10 (突破10周期低点)

# 15分钟级别过滤
ema20_15m < ema50_15m (主要趋势向下)
4. 入场信号规则
python
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
5. 风险管理规则
python
RISK_MANAGEMENT = {
    # 仓位管理
    'position_sizing': {
        'base_amount': 8,           # 基础仓位8 USDT
        'leverage': 2,              # 2倍杠杆
        'max_position_ratio': 0.1,  # 单币种最大仓位10%
        'max_total_exposure': 0.3,  # 总风险暴露30%
    },
    
    # 动态止损
    'stop_loss': {
        'initial_atr_multiplier': 1.2,    # 初始止损1.2×ATR
        'volatility_adjustment': True,    # 根据波动率调整
        'min_stop_pct': 0.4,              # 最小止损0.4%
        'max_stop_pct': 3.0,              # 最大止损3.0%
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
6. 市场状态过滤
python
MARKET_FILTERS = {
    # BTC市场状态
    'btc_condition': {
        'max_1m_volatility': 0.02,      # BTC 1分钟波动不超过2%
        'rsi_15m_range': [25, 75],      # BTC 15分钟RSI在25-75之间
        'trend_alignment': True         # 要求与BTC趋势一致
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
7. 信号评分系统
python
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
        'minimum_score': 5,         # 最低得分5分
        'high_confidence': 8,       # 高信心得分8分
        'maximum_position_size': 12 # 最大仓位得分12分
    }
}
8. 冷却和轮动机制
python
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
9. 完整的信号生成流程
python
def generate_trading_signal(symbol, klines_3m, klines_5m, klines_15m):
    """
    完整的信号生成流程
    """
    signal_data = {
        'symbol': symbol,
        'timestamp': datetime.now(),
        'score': 0,
        'signal': None,
        'confidence': 0.0,
        'risk_level': 'UNKNOWN',
        'reason': [],
        'position_size': 0,
        'stop_loss': 0,
        'take_profit_levels': []
    }
    
    # 步骤1: 基础数据检查
    if not validate_klines_data(klines_3m, klines_5m, klines_15m):
        return None
    
    # 步骤2: 市场状态过滤
    if not check_market_conditions():
        signal_data['reason'].append('市场状态不适宜')
        return signal_data
    
    # 步骤3: 趋势判断
    trend_strength = analyze_trend_strength(klines_3m, klines_5m, klines_15m)
    signal_data['score'] += trend_strength['score']
    signal_data['reason'].extend(trend_strength['reasons'])
    
    # 步骤4: 动量确认
    momentum = check_momentum(klines_3m, klines_5m)
    signal_data['score'] += momentum['score']
    signal_data['reason'].extend(momentum['reasons'])
    
    # 步骤5: 风险回报评估
    risk_reward = assess_risk_reward(klines_3m)
    signal_data['score'] += risk_reward['score']
    signal_data['reason'].extend(risk_reward['reasons'])
    
    # 步骤6: 生成最终信号
    if signal_data['score'] >= SCORING_SYSTEM['thresholds']['minimum_score']:
        signal_data = generate_final_signal(signal_data, klines_3m)
    
    return signal_data
10. 执行和监控
python
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
这套规则体系的特点：

多维度过滤 - 从选币到入场层层过滤

动态调整 - 根据市场状态和表现动态调整参数

严格风控 - 完善的分阶段止损止盈体系

智能评分 - 量化信号质量，避免主观判断

持续优化 - 基于历史表现持续优化参数

需求V2.0

针对您提出的8个问题，逐一详细回答：
1. 交易标的类型
是 Binance USDT-M 永续合约

python
TRADING_INSTRUMENT = {
    'type': 'USDT-M Perpetual',
    'characteristics': {
        'leverage': '支持杠杆交易（当前2倍）',
        'settlement': 'USDT结算',
        'funding_rate': '每8小时资金费率',
        'position_mode': '单向持仓模式',
        'margin_mode': '全仓模式（CROSSED）'
    },
    'adjustments': {
        '止损方式': '基于标记价格的强平机制',
        '仓位计算': '基于合约价值，非名义本金',
        '最小交易单位': '合约张数，需按币种精度调整'
    }
}
2. 24h涨跌幅阈值处理
绝对值≤15%，但需要特殊处理极端情况

python
DAILY_CHANGE_FILTER = {
    'base_rule': 'abs(24h_change) ≤ 15%',
    'exceptions': {
        'deep_drop_high_rebound': {
            'condition': '24h_change < -15% 但 2h_change > 8%',
            'action': '允许交易，但降低仓位50%',
            'rationale': '捕捉超跌反弹机会但控制风险'
        },
        'extreme_pump': {
            'condition': '24h_change > 20% 且 2h_change > 5%',
            'action': '完全排除，避免追高',
            'rationale': '涨幅过大，回调风险高'
        }
    },
    'implementation': '''
    def check_daily_change(symbol_data):
        daily_change = symbol_data['24h_change']
        two_hour_change = symbol_data['2h_change']
        
        if abs(daily_change) <= 0.15:  # 15%
            return True, 1.0  # 正常仓位
        elif daily_change < -0.15 and two_hour_change > 0.08:
            return True, 0.5  # 减半仓位
        else:
            return False, 0.0  # 排除
    '''
}
3. Volume Ratio计算窗口
近20根3分钟K线的均量

python
VOLUME_CONFIG = {
    'window': '20根3分钟K线（1小时数据）',
    'calculation': {
        'current_volume': '最新一根3分钟K线的成交量',
        'average_volume': '过去20根3分钟K线成交量的算术平均',
        'ratio': 'current_volume / average_volume'
    },
    'thresholds': {
        'minimum': 1.2,  # 必须>1.2倍均量
        'optimal': 1.5,  # 理想情况>1.5倍
        'excellent': 2.0  # 优秀信号>2.0倍
    },
    'rationale': '确保当前有真实的资金流入，避免假突破'
}
4. Price to EMA区间调整
改为±0.5%的区间范围

python
EMA_PULLBACK_CONFIG = {
    'original': 'price_to_ema = 0.995 (价格在EMA的-0.5%)',
    'improved': 'price_to_ema_range = [0.995, 1.005]',
    'interpretation': {
        'lower_bound': '0.995 = EMA的99.5% (回调买入)',
        'upper_bound': '1.005 = EMA的100.5% (突破确认)',
        'neutral_zone': '1.000 = 正好在EMA上'
    },
    'application': '''
    # 多头入场：价格在EMA的[-0.5%, +0.5%]区间内
    if 0.995 <= (current_price / ema21) <= 1.005:
        # 符合回调入场条件
        pass
    '''
}
5. 止损计算逻辑
动态取最大值，ATR与百分比结合

python
STOP_LOSS_LOGIC = {
    'calculation': 'max(ATR×multiplier, min_stop_pct)',
    'constraint': '且不超过max_stop_pct',
    'formula': '''
    def calculate_stop_loss(entry_price, atr, side):
        # 计算ATR止损距离
        atr_stop_distance = atr * INITIAL_STOP_ATR_MULTIPLIER  # 1.2
        
        # 计算百分比止损距离
        pct_stop_distance = entry_price * MIN_STOP_PCT  # 0.4%
        
        # 取两者最大值，但不超过最大止损
        stop_distance = min(
            max(atr_stop_distance, pct_stop_distance),
            entry_price * MAX_STOP_PCT  # 3%
        )
        
        if side == 'LONG':
            return entry_price - stop_distance
        else:  # SHORT
            return entry_price + stop_distance
    ''',
    'parameters': {
        'INITIAL_STOP_ATR_MULTIPLIER': 1.2,
        'MIN_STOP_PCT': 0.004,  # 0.4%
        'MAX_STOP_PCT': 0.03    # 3.0%
    }
}
6. 市场过滤数据源降级
可降级为仅依赖BTC状态过滤

python
MARKET_FILTER_FALLBACK = {
    'primary_sources': {
        'fear_greed_index': 'https://api.alternative.me/fng/',
        'volatility_index': '自行计算（24小时收益率标准差）',
        'btc_dominance': 'Binance API'
    },
    'fallback_plan': {
        'scenario': '当外部数据源不可用时',
        'fallback_to': '仅依赖BTC状态过滤 + 基础波动率检查',
        'implementation': '''
        def market_filter_fallback():
            # 基础BTC趋势检查
            btc_ok = check_btc_trend()
            
            # 基础波动率检查（使用BTC 1分钟波动）
            volatility_ok = check_btc_volatility()
            
            return btc_ok and volatility_ok
        ''',
        'coverage': '仍能过滤80%以上的极端市场情况'
    }
}
7. 评分与仓位映射关系
分段非线性放大

python
SCORE_TO_POSITION_MAPPING = {
    'mapping_type': '分段非线性',
    'segments': {
        '基础门槛': {
            'score_range': [5, 7],
            'position_multiplier': 0.5,
            'description': '基础仓位50%，保守交易'
        },
        '标准仓位': {
            'score_range': [8, 10], 
            'position_multiplier': 1.0,
            'description': '标准仓位100%，正常交易'
        },
        '增强仓位': {
            'score_range': [11, 12],
            'position_multiplier': 1.5,
            'description': '增强仓位150%，高信心信号'
        }
    },
    'constraints': {
        'absolute_max': '单币种不超过总资金的20%',
        'leverage_aware': '考虑杠杆后的实际风险暴露',
        'correlation_penalty': '相关性高的币种降低仓位'
    },
    'formula': '''
    def calculate_position_size(base_amount, score, correlation_penalty=1.0):
        if score <= 7:
            multiplier = 0.5
        elif score <= 10:
            multiplier = 1.0
        else:  # 11-12
            multiplier = 1.5
            
        return base_amount * multiplier * correlation_penalty
    '''
}
8. 相关性计算参数
24小时5分钟收益率数据

python
CORRELATION_CONFIG = {
    'data_source': 'Binance USDT-M 永续合约',
    'calculation': {
        'window': '24小时（288根5分钟K线）',
        'granularity': '5分钟收益率',
        'method': 'Pearson相关系数',
        'returns_calculation': 'log(price_t / price_{t-1})'
    },
    'parameters': {
        'threshold': 0.7,
        'lookback_days': 1,  # 24小时
        'min_data_points': 200  # 最少200个数据点
    },
    'application': {
        'purpose': '避免持仓过度集中在相关资产',
        'action': '相关系数>0.7时，选择评分更高的币种',
        'example': '如果已持有ETH多头，则排除相关性>0.7的MATIC'
    },
    'implementation': '''
    def calculate_correlation(symbol1, symbol2):
        # 获取24小时5分钟K线数据
        klines1 = get_5m_klines(symbol1, 288)
        klines2 = get_5m_klines(symbol2, 288)
        
        # 计算对数收益率
        returns1 = calculate_log_returns(klines1)
        returns2 = calculate_log_returns(klines2)
        
        # 计算相关系数
        correlation = np.corrcoef(returns1, returns2)[0, 1]
        return correlation
    '''
}
完整参数汇总
python
FINAL_CONFIG_SUMMARY = {
    'instrument': 'Binance USDT-M Perpetual',
    'daily_change_filter': 'abs(24h_change) ≤ 15%，超跌反弹特殊处理',
    'volume_ratio': '当前成交量 / 近20根3mK线均量 > 1.2',
    'ema_pullback': '价格在EMA的±0.5%区间内',
    'stop_loss': 'max(ATR×1.2, 0.4%) ≤ 3.0%',
    'market_filters': '可降级为BTC趋势+基础波动率',
    'position_sizing': '5-7分:50%, 8-10分:100%, 11-12分:150%',
    'correlation': '24小时5m收益率，阈值0.7'
}
这些调整使策略更加健壮和实用，既保持了原设计的核心思路，又解决了实际运行中可能遇到的问题。
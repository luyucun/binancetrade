# 🚀 Binance 自动化趋势交易系统

## 📋 项目结构

### **核心程序** (必须运行)
```
✓ optimized_trend_trader.py        入场引擎（每3分钟扫描70个币种，找信号入场）
✓ position_monitor_enhanced.py     风险管理（每10秒监控持仓，执行止盈止损）
```

### **核心模块** (被使用)
```
✓ binance_client.py                Binance API 客户端封装
✓ atr_risk_manager.py              ATR 动态止损/止盈计算
✓ cooldown_manager.py              冷却机制（防止虚假信号重复）
✓ config.py                        集中配置文件（API密钥、交易参数等）
```

### **工具程序** (可选)
```
✓ cleanup_cooldown.py              冷却状态诊断和清理工具
```

### **依赖文件**
```
✓ requirements.txt                 Python 依赖列表
```

---

## 🔧 快速开始

### 1. 安装依赖
```bash
pip install -r requirements.txt
```

### 2. 配置 API 密钥
编辑 `config.py`，填入你的 Binance API 密钥和密码

### 3. 启动交易系统
```bash
# 终端1: 启动入场引擎
python optimized_trend_trader.py

# 终端2: 启动风险管理（并行运行）
python position_monitor_enhanced.py
```

### 4. (可选) 诊断冷却状态
```bash
python cleanup_cooldown.py
```

---

## 📊 交易系统规则

### 入场条件 (3层过滤)
```
第1层: 趋势检测
  最近8根1分钟K线中6根同向 → 生成信号(LONG/SHORT)

第2层: 多因子确认 (需满足≥2个)
  ✓ EMA21 突破
  ✓ MACD 金叉
  ✓ RSI 趋势
  ✓ 成交量放大 (×1.5)
  ✓ 5分钟多周期同向

第3层: 方向验证
  信号与2小时趋势方向一致
```

### 风险管理 (ATR动态)
```
止损   = 入场价 - 0.8 × ATR
止盈1  = 入场价 + 1.5 × ATR   (平仓40%)
止盈2  = 入场价 + 1.0 × ATR   (追踪剩余60%)

目标盈亏比: 1:3
```

### 冷却机制
```
第1次失败 → 5分钟冷却
第2次失败 → 10分钟冷却
第3次失败 → 12小时严重冷却
```

---

## 🗂️ 已删除的废弃文件

✗ `trading_engine.py` - 被引入但从未使用（已删除）
✗ `kline_manager.py` - 被引入但从未使用（已删除）

---

## 🐛 常见问题

### Q: 某币种显示"失败×1000"怎么办？
A: 运行清理工具
```bash
python cleanup_cooldown.py
选择 "3. 完全重置（删除所有）"
然后重启两个程序
```

### Q: 如何修改交易参数？
A: 编辑 `config.py` 中的参数
```python
BASE_TRADE_AMOUNT = 10        # 本金(USDT)
LEVERAGE = 2                  # 杠杆倍数
MONITOR_VOLUME_TOP_N = 70     # 监控币种数
```

### Q: 如何验证系统正常运行？
A: 查看日志输出
```
✓ Binance客户端连接成功
✓ 冷却管理器初始化
【交易成功】XXX LONG 入场
```

---

## 📈 监控指标

| 项目 | 值 |
|------|-----|
| 扫描周期 | 每3分钟 |
| 监控周期 | 每10秒 |
| 监控币种 | 70个 |
| 基础杠杆 | 2x |
| 成交额 | 20 USDT |
| 止损倍数 | 0.8×ATR |
| 止盈倍数 | 1.5×ATR |

---

**最后更新**: 2025-11-05
**版本**: 2.0 (清理版)

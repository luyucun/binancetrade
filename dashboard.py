"""
Binance自动化交易系统 - 可视化监控面板
基于Streamlit构建的实时监控界面
"""

import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime
import json
import time

# 设置页面布局
st.set_page_config(
    page_title="Binance AI Trading Bot",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 自定义CSS样式
st.markdown("""
<style>
    .metric-card {
        background-color: #1E1E1E;
        border: 1px solid #333;
        padding: 15px;
        border-radius: 10px;
        text-align: center;
    }
    .bullish { color: #00C853; font-weight: bold; }
    .bearish { color: #FF3D00; font-weight: bold; }
    .stDataFrame { border: none; }
    .big-font {
        font-size: 24px !important;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

# ==================== 数据库连接函数 ====================
@st.cache_resource
def get_db_connection():
    """创建数据库连接（缓存）"""
    return sqlite3.connect('data/trading.db', check_same_thread=False)


def get_status(key):
    """从数据库获取系统状态"""
    try:
        conn = get_db_connection()
        df = pd.read_sql(f"SELECT value, update_time FROM system_status WHERE key='{key}'", conn)
        if not df.empty:
            return df.iloc[0]['value'], df.iloc[0]['update_time']
        return None, None
    except Exception as e:
        return None, None


def get_active_positions():
    """获取活跃持仓"""
    try:
        conn = get_db_connection()
        df = pd.read_sql("SELECT * FROM active_positions", conn)
        return df
    except Exception as e:
        st.error(f"读取持仓数据失败: {e}")
        return pd.DataFrame()


def get_trade_history(limit=50):
    """获取交易历史"""
    try:
        conn = get_db_connection()
        df = pd.read_sql(f"SELECT * FROM trade_history ORDER BY id DESC LIMIT {limit}", conn)
        return df
    except Exception as e:
        return pd.DataFrame()


def get_scan_history(limit=20):
    """获取扫描历史"""
    try:
        conn = get_db_connection()
        df = pd.read_sql(f"SELECT * FROM scan_results ORDER BY id DESC LIMIT {limit}", conn)
        return df
    except Exception as e:
        return pd.DataFrame()


# ==================== 侧边栏：控制与状态 ====================
with st.sidebar:
    st.title("🤖 交易控制台")
    st.markdown("---")

    # 自动刷新控制
    auto_refresh = st.checkbox("自动刷新", value=True)
    if auto_refresh:
        refresh_interval = st.slider("刷新间隔(秒)", 1, 10, 2)
        st.info(f"每{refresh_interval}秒自动刷新")
        time.sleep(refresh_interval)
        st.rerun()

    st.markdown("---")

    # 读取系统状态
    scan_stage, _ = get_status("scan_stage")
    market_health, _ = get_status("market_health")
    last_update, _ = get_status("last_scan_time")

    st.subheader("📊 系统状态")

    if last_update:
        st.success(f"✅ 最后扫描: {last_update}")
    else:
        st.warning("⏳ 等待引擎启动...")

    if scan_stage:
        st.text(f"状态: {scan_stage}")
    else:
        st.text("状态: Idle")

    # 市场健康度
    if market_health:
        if market_health == "EXCELLENT":
            st.success(f"🟢 市场: {market_health}")
        elif market_health == "CRITICAL":
            st.error(f"🔴 市场: {market_health}")
        else:
            st.warning(f"🟡 市场: {market_health}")

    st.markdown("---")

    # 日志查看器
    st.subheader("📄 最新日志")
    try:
        with open("trading_engine.log", "r", encoding='utf-8') as f:
            lines = f.readlines()[-15:]
            log_text = "".join(lines)
            st.text_area("", log_text, height=200, disabled=True)
    except:
        st.caption("日志文件未找到")


# ==================== 主界面 ====================
st.title("🚀 Binance 趋势动量交易监控系统")

# 1. 关键指标 KPI
col1, col2, col3, col4 = st.columns(4)

df_positions = get_active_positions()

if not df_positions.empty:
    total_pnl = df_positions['pnl_usdt'].sum()
    active_count = len(df_positions)
    win_count = len(df_positions[df_positions['pnl_usdt'] > 0])
    win_rate = (win_count / active_count * 100) if active_count > 0 else 0
else:
    total_pnl = 0.0
    active_count = 0
    win_rate = 0.0

# 假设初始资金1000 USDT（你可以从API获取真实余额）
wallet_balance = 1000.0 + total_pnl

with col1:
    st.metric("总权益 (Est.)", f"${wallet_balance:.2f}", delta=None)
with col2:
    delta_color = "normal" if total_pnl >= 0 else "inverse"
    st.metric("浮动盈亏", f"${total_pnl:.2f}", delta=f"{total_pnl:+.2f} USDT", delta_color=delta_color)
with col3:
    st.metric("活跃持仓数", f"{active_count}", delta=None)
with col4:
    st.metric("当前胜率", f"{win_rate:.1f}%", delta=None)

st.markdown("---")

# 2. 活跃持仓可视化表格
st.subheader("📊 活跃持仓监控")

if not df_positions.empty:
    # 格式化DataFrame
    display_df = df_positions[['symbol', 'side', 'entry_price', 'current_price',
                                 'pnl_usdt', 'pnl_pct', 'score', 'direction']].copy()

    # 格式化百分比
    display_df['pnl_pct'] = (display_df['pnl_pct'] * 100).round(2)

    # 使用streamlit dataframe的新特性
    st.dataframe(
        display_df,
        column_config={
            "symbol": st.column_config.TextColumn("币种", width="small"),
            "side": st.column_config.TextColumn("方向", width="small"),
            "entry_price": st.column_config.NumberColumn("入场价", format="%.6f"),
            "current_price": st.column_config.NumberColumn("现价", format="%.6f"),
            "pnl_usdt": st.column_config.NumberColumn("盈亏(U)", format="$%.2f"),
            "pnl_pct": st.column_config.NumberColumn("盈亏率(%)", format="%.2f%%"),
            "score": st.column_config.NumberColumn("得分", width="small"),
            "direction": st.column_config.TextColumn("趋势", width="small"),
        },
        use_container_width=True,
        hide_index=True
    )

    st.markdown("---")

    # 3. 详细诊断 - 选择币种查看
    st.subheader("🔍 深度诊断")

    col_select, col_chart = st.columns([1, 2])

    with col_select:
        selected_symbol = st.selectbox("选择币种", df_positions['symbol'].values)

    if selected_symbol:
        row = df_positions[df_positions['symbol'] == selected_symbol].iloc[0]

        d_col1, d_col2, d_col3 = st.columns(3)

        with d_col1:
            st.metric("入场价格", f"{row['entry_price']:.6f}")
            st.metric("当前价格", f"{row['current_price']:.6f}")

        with d_col2:
            st.metric("止损价格", f"{row['stop_loss']:.6f}")
            dist_sl = abs((row['current_price'] - row['stop_loss']) / row['current_price'] * 100)
            st.metric("距离止损", f"{dist_sl:.2f}%")

        with d_col3:
            # 解析take_profit
            try:
                tp_levels = json.loads(row['take_profit'])
                st.metric("止盈目标数", f"{len(tp_levels)} 阶")
                if tp_levels:
                    st.caption(f"TP1: {tp_levels[0]:.6f}")
            except:
                st.caption("无止盈数据")

        # 风险进度条
        st.write("#### 风险状态")
        risk_progress = min(max((row['pnl_pct'] + 2) / 5, 0.0), 1.0)
        st.progress(risk_progress)

else:
    st.info("💤 暂无活跃持仓，等待信号中...")

    # 显示扫描状态
    if scan_stage:
        st.code(f"系统状态: {scan_stage}")

st.markdown("---")

# 4. 交易历史
st.subheader("📜 交易历史")
df_history = get_trade_history(30)

if not df_history.empty:
    # 只显示关键列
    history_display = df_history[['time', 'symbol', 'action', 'price', 'pnl', 'pnl_pct', 'reason']].copy()

    # 格式化百分比
    history_display['pnl_pct'] = (history_display['pnl_pct'] * 100).round(2)

    st.dataframe(
        history_display,
        column_config={
            "time": "时间",
            "symbol": "币种",
            "action": "动作",
            "price": st.column_config.NumberColumn("价格", format="%.6f"),
            "pnl": st.column_config.NumberColumn("盈亏(U)", format="$%.2f"),
            "pnl_pct": st.column_config.NumberColumn("盈亏率(%)", format="%.2f%%"),
            "reason": "原因",
        },
        use_container_width=True,
        hide_index=True,
        height=300
    )
else:
    st.info("暂无交易历史")

st.markdown("---")

# 5. 扫描统计
st.subheader("📈 扫描统计")
df_scan = get_scan_history(10)

if not df_scan.empty:
    col_scan1, col_scan2 = st.columns(2)

    with col_scan1:
        st.write("##### 最近扫描")
        scan_display = df_scan[['scan_time', 'total_coins', 'filtered_coins', 'signals_generated', 'market_health']].copy()
        st.dataframe(scan_display, use_container_width=True, hide_index=True, height=250)

    with col_scan2:
        st.write("##### 信号生成趋势")
        # 简单的柱状图
        import plotly.express as px
        fig = px.bar(df_scan, x='scan_time', y='signals_generated',
                     title='信号生成数量',
                     labels={'signals_generated': '信号数', 'scan_time': '时间'})
        st.plotly_chart(fig, use_container_width=True)
else:
    st.info("暂无扫描数据")

# 页脚
st.markdown("---")
st.caption(f"🤖 Powered by Claude Code | 最后更新: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

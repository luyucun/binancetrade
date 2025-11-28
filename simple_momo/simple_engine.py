import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Set

from binance_client_v2 import BinanceClientV2
from simple_momo.simple_config import (
    ENTRY_USDT,
    ATR_PERIOD,
    CHECK_INTERVAL,
    MIN_TREND_BARS,
    MAX_POSITIONS,
    LEVERAGE,
    HEDGE_MODE,
    MARGIN_TYPE,
    API_KEY,
    API_SECRET,
    TESTNET,
    LOG_FILE,
)


logger = logging.getLogger(__name__)


@dataclass
class Position:
    symbol: str
    side: str          # "LONG"/"SHORT"
    entry_price: float
    qty: float
    stop: float
    take: float
    atr: float = 0.0   # 开仓时的ATR值，用于移动止损判断
    partial_closed: bool = False  # 是否已平仓50%
    stop_order_id: int = None  # 止损单ID
    take_order_id: int = None  # 止盈单ID


class SimpleMomoEngine:
    """
    极简趋势跟随 (优化版)：
    1. 策略: 15m定趋势 + 1m找爆发 (7/9同向)
    2. 过滤: RSI(14) 拒绝超买超卖
    3. 风控: 
       - 全局开仓冷却 5分钟 (防止并发一波流)
       - 单币种离场冷却 60分钟 (防止利润回吐)
       - 10秒心跳监控持仓 (保证止损敏锐度)
    """

    def __init__(self):
        self.client = BinanceClientV2(API_KEY, API_SECRET, testnet=TESTNET)
        self.positions: Dict[str, Position] = {}
        self.opening_symbols = set()  # 防止同一币种重复开仓
        self.cooldown_until: Dict[str, float] = {}  # 单币种冷却：symbol -> 冷却结束时间戳
        self.global_cooldown_until = 0.0  # 全局开仓冷却时间戳
        
        self._setup_exchange()
        self._setup_logging()
        self._sync_positions_from_exchange()  # 启动时同步交易所持仓
        
        logger.info(
            f"SimpleMomo 启动 | testnet={TESTNET} | 固定仓位={ENTRY_USDT}USDT | "
            f"止损=0.8ATR | 止盈=1.5ATR | RSI过滤=ON | 全局冷却=5min"
        )

    def _setup_exchange(self):
        try:
            if HEDGE_MODE:
                self.client.set_position_mode(True)
        except Exception as e:
            logger.warning(f"初始化持仓/保证金模式失败: {e}")

    def _setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )
        # 确保日志目录存在
        import os
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        
        fh = logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
        log = logging.getLogger("simple_trades")
        log.setLevel(logging.INFO)
        if not log.handlers:
            log.addHandler(fh)
            log.propagate = False
        self.trade_logger = log

    def _sync_positions_from_exchange(self):
        """启动时从交易所同步现有持仓到内存"""
        try:
            positions = self.client.get_positions()
            for pos in positions:
                symbol = pos['symbol']
                # 获取15分钟K线计算ATR用于估算止损止盈
                kl = self.fetch_klines_15m(symbol, limit=50)
                if not kl:
                    logger.warning(f"{symbol}: 无法获取15分钟K线数据，跳过同步")
                    continue

                atr_val = self.atr(kl)
                price = pos['mark_price']
                qty = pos['quantity']
                side = pos['side']

                # 估算止损止盈 (仅用于恢复内存状态，实际以交易所挂单为准)
                if atr_val > 0:
                    stop = price - 0.8 * atr_val if side == "LONG" else price + 0.8 * atr_val
                    take = price + 1.5 * atr_val if side == "LONG" else price - 1.5 * atr_val
                else:
                    stop = price * 0.99 if side == "LONG" else price * 1.01
                    take = price * 1.02 if side == "LONG" else price * 0.98

                self.positions[symbol] = Position(
                    symbol=symbol,
                    side=side,
                    entry_price=pos['entry_price'],
                    qty=qty,
                    stop=stop,
                    take=take,
                    atr=atr_val
                )
                logger.info(
                    f"[同步持仓] {symbol} | 方向:{side} | 入场:{pos['entry_price']:.4f} | "
                    f"数量:{qty:.6f} | 止损:{stop:.4f} | 止盈:{take:.4f}"
                )

            if positions:
                logger.info(f"已同步 {len(positions)} 个交易所持仓到内存")
            else:
                logger.info("交易所当前无持仓")
        except Exception as e:
            logger.error(f"同步持仓失败: {e}", exc_info=True)

    def get_top_volume_symbols(self) -> List[str]:
        """返回24小时交易量排行榜前50的USDT永续合约"""
        try:
            tickers = self.client.client.futures_ticker()
        except Exception as e:
            logger.warning(f"获取交易量排行榜失败: {e}")
            return []
        volumes = []
        for t in tickers:
            sym = t.get("symbol", "")
            if not sym.endswith("USDT") or "_" in sym:
                continue
            volume = float(t.get("quoteVolume", 0))  # 24小时成交额(USDT)
            volumes.append((sym, volume))
        volumes.sort(key=lambda x: x[1], reverse=True)
        top_symbols = [s for s, _ in volumes[:50]]
        return top_symbols

    def fetch_klines(self, symbol: str, limit: int = 50):
        return self.client.get_klines(symbol, "1m", limit)

    def fetch_klines_15m(self, symbol: str, limit: int = 20):
        """获取15分钟K线"""
        return self.client.get_klines(symbol, "15m", limit)

    def get_15m_trend(self, symbol: str) -> str:
        """
        判断15分钟K线的总趋势
        使用最近10根15分钟K线，比较收盘价和开盘价判断趋势
        返回 'UP'/'DOWN'/''
        """
        kl = self.fetch_klines_15m(symbol, limit=20)
        if not kl or len(kl) < 10:
            return ""

        # 取最近10根已完成的15分钟K线（不含当前未完成的）
        seg = kl[-11:-1] if len(kl) >= 11 else kl[:-1]
        if len(seg) < 5:
            return ""

        first_close = seg[0]["close"]
        last_close = seg[-1]["close"]
        up_count = sum(1 for k in seg if k["close"] > k["open"])
        down_count = len(seg) - up_count

        price_trend_up = last_close > first_close
        price_trend_down = last_close < first_close

        if price_trend_up and up_count > down_count:
            return "UP"
        if price_trend_down and down_count > up_count:
            return "DOWN"
        return ""

    def atr(self, klines) -> float:
        """简单ATR计算"""
        if len(klines) < ATR_PERIOD + 1:
            return 0.0
        trs = []
        prev_close = klines[-ATR_PERIOD - 1]["close"]
        for k in klines[-ATR_PERIOD:]:
            high, low, close = k["high"], k["low"], k["close"]
            trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
            prev_close = close
        return sum(trs) / len(trs)

    def calculate_rsi(self, klines, period=14) -> float:
        """简单计算最后一根K线的RSI"""
        if len(klines) < period + 1:
            return 50.0  # 数据不足返回中性

        closes = [x['close'] for x in klines]
        gains = []
        losses = []

        # 计算涨跌幅
        for i in range(1, len(closes)):
            change = closes[i] - closes[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))

        # 简单移动平均 (SMA) 算法
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period

        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def last_n_same_direction(self, klines, n: int) -> str:
        """返回'UP'/'DOWN'/'' 根据最近n根已完成K线的方向（不含当前K线），9根中7根同向即可"""
        if len(klines) < n + 1:
            return ""
        # 排除最后一根（当前未完成的K线），取之前的n根
        seg = klines[-(n + 1):-1]
        up_count = sum(1 for k in seg if k["close"] > k["open"])
        down_count = n - up_count
        
        if up_count >= 7:
            return "UP"
        if down_count >= 7:
            return "DOWN"
        return ""

    async def run(self):
        logger.info("开始主循环...")
        while True:
            try:
                await self.step()
            except Exception as e:
                logger.error(f"循环异常: {e}", exc_info=True)
            # 心跳间隔保持不变，确保监控敏锐
            await asyncio.sleep(CHECK_INTERVAL)

    def get_actual_positions_from_exchange(self):
        """从交易所获取实际持仓的币种集合，失败时返回None"""
        try:
            positions = self.client.get_positions()
            active_symbols = set()
            if positions:
                for pos in positions:
                    active_symbols.add(pos['symbol'])
            return active_symbols
        except Exception as e:
            logger.error(f"获取实际持仓失败: {e}")
            return None  # 关键修改：报错时返回 None，不要返回空集合

    async def step(self):
        # ---------------------------------------------------------
        # 1. 【最优先】监控已有持仓 (安全第一，必须每轮都跑)
        # ---------------------------------------------------------
        try:
            await self.monitor_positions()
        except Exception as e:
            logger.error(f"监控持仓异常: {e}")

        # ---------------------------------------------------------
        # 2. 检查全局开仓冷却 (防止连环开单)
        # ---------------------------------------------------------
        if time.time() < self.global_cooldown_until:
            # remaining = int(self.global_cooldown_until - time.time())
            # logger.debug(f"全局开仓冷却中，剩余 {remaining} 秒，暂停选币")
            return

        # ---------------------------------------------------------
        # 3. 获取候选币种并寻找机会
        # ---------------------------------------------------------
        candidates = self.get_top_volume_symbols()
        if not candidates:
            return

        # 获取交易所实际持仓，防止重复开仓
        actual_positions = self.get_actual_positions_from_exchange()

        # 如果获取失败（None），跳过本轮选币，避免误判
        if actual_positions is None:
            logger.warning("无法获取交易所持仓，跳过本轮选币")
            return

        # 简单的状态日志，每隔几轮打印一次也可以，这里为了清晰每次打印
        logger.info(
            f"Scanning | 候选: {len(candidates)} | 持仓: {len(self.positions)}/{MAX_POSITIONS} | 冷却中: {len([k for k,v in self.cooldown_until.items() if v > time.time()])}"
        )
        
        for sym in candidates:
            # --- 基础过滤 ---
            if sym in actual_positions:
                continue
            if sym in self.opening_symbols:
                continue
            if len(actual_positions) >= MAX_POSITIONS:
                break # 仓位已满，停止扫描

            # 检查单币种冷却 (无论是止盈还是止损后)
            if sym in self.cooldown_until and time.time() < self.cooldown_until[sym]:
                continue

            # --- K线获取 ---
            kl = self.fetch_klines(sym, limit=50)
            if not kl:
                continue

            # --- 核心策略: 趋势 + RSI ---
            dir_1m = self.last_n_same_direction(kl, MIN_TREND_BARS)
            if not dir_1m:
                continue

            rsi_val = self.calculate_rsi(kl)  
            
            # RSI 过滤 (防止追涨杀跌)
            if dir_1m == "UP" and rsi_val > 70:
                logger.debug(f"{sym}: 趋势UP但RSI({rsi_val:.1f})>70，跳过")
                continue
            if dir_1m == "DOWN" and rsi_val < 30:
                logger.debug(f"{sym}: 趋势DOWN但RSI({rsi_val:.1f})<30，跳过")
                continue

            # --- 趋势共振 ---
            kl_15m = self.fetch_klines_15m(sym, limit=50)
            if not kl_15m:
                continue
            trend_15m = self.get_15m_trend(sym)
            if dir_1m != trend_15m:
                continue

            # --- 准备开仓 ---
            atr_val = self.atr(kl_15m)
            if atr_val <= 0:
                continue
            
            price = kl[-1]["close"]
            side = "LONG" if dir_1m == "UP" else "SHORT"

            logger.info(f"⚡信号触发: {sym} | {side} | RSI:{rsi_val:.1f} | 15m:{trend_15m}")

            # 锁定全局冷却 300秒 (5分钟)
            self.global_cooldown_until = time.time() + 300
            
            self.opening_symbols.add(sym)
            try:
                await self.open_position(sym, side, price, atr_val)
                # 开仓成功后，直接跳出循环，本轮不再看其他币
                break 
            finally:
                self.opening_symbols.discard(sym)

    async def open_position(self, symbol: str, side: str, price: float, atr: float):
        qty = ENTRY_USDT / price
        stop = price - 0.8 * atr if side == "LONG" else price + 0.8 * atr
        take = price + 1.5 * atr if side == "LONG" else price - 1.5 * atr
        pos_side = "LONG" if side == "LONG" else "SHORT"
        close_side = "SELL" if side == "LONG" else "BUY"

        try:
            # 1. 设置杠杆
            self.client.set_margin_type(symbol, MARGIN_TYPE)
            self.client.set_leverage(symbol, LEVERAGE)

            # 2. 市价开仓
            order = self.client.place_market_order(
                symbol=symbol,
                side="BUY" if side == "LONG" else "SELL",
                quantity=qty,
                position_side=pos_side,
                reduce_only=False,
            )
            if not order:
                logger.error(f"{symbol}: 开仓下单失败")
                return

            # 获取实际成交量
            actual_qty = order.get('filled', qty)
            if actual_qty == 0:
                actual_qty = order.get('quantity', qty)

            # 3. 挂止损单
            stop_order_id = self.client.set_stop_loss(
                symbol=symbol,
                quantity=actual_qty,
                stop_price=stop,
                side=close_side,
                position_side=pos_side
            )

            # 4. 挂止盈单
            take_order_id = self.client.set_take_profit(
                symbol=symbol,
                quantity=actual_qty,
                stop_price=take,
                side=close_side,
                position_side=pos_side
            )

            # 5. 记录持仓
            self.positions[symbol] = Position(
                symbol=symbol, side=side, entry_price=price, qty=actual_qty, 
                stop=stop, take=take, atr=atr,
                stop_order_id=stop_order_id, take_order_id=take_order_id
            )
            
            log_msg = (f"[入场] {symbol} | 方向:{side} | 价格:{price:.4f} | "
                       f"RSI预估:安全 | 止损:{stop:.4f} | 止盈:{take:.4f}")
            self.trade_logger.info(log_msg)
            logger.info(log_msg)
            
        except Exception as e:
            logger.error(f"{symbol}: 开仓流程异常 {e}", exc_info=True)

    async def monitor_positions(self):
        """监控持仓状态，处理止盈止损离场后的逻辑"""
        if not self.positions:
            return

        prices = self.client.get_all_prices()
        actual_positions = self.get_actual_positions_from_exchange()

        # [新增] 如果获取失败（None），直接跳过本轮监控，保护内存持仓不被误删
        if actual_positions is None:
            logger.warning("无法获取交易所持仓，跳过本轮监控")
            return

        to_remove = []
        for sym, pos in list(self.positions.items()):
            # 情况A: 交易所持仓已消失 (止损/止盈单已触发)
            if sym not in actual_positions:
                current_price = prices.get(sym, 0)
                reason = "挂单触发"
                
                # 尝试推断是止盈还是止损
                if current_price:
                    if pos.side == "LONG":
                        is_profit = current_price > pos.entry_price
                    else:
                        is_profit = current_price < pos.entry_price
                    reason = "止盈" if is_profit else "止损"

                # 【关键逻辑】无论输赢，该币种冷却 1小时 (3600秒)
                self.cooldown_until[sym] = time.time() + 3600
                
                logger.info(f"{sym}: 仓位结束({reason}) -> 冷却1小时")
                self.trade_logger.info(f"[离场] {sym} | 原因:{reason} | 方向:{pos.side}")
                to_remove.append(sym)
                continue

            # 情况B: 持仓还在，检查是否需要兜底 (扫描模式)
            price = prices.get(sym)
            if not price:
                continue

            # 如果挂单ID丢失，或者价格已经明显越界但挂单没触（极端行情），强制市价平
            # 这里简化逻辑：只看价格是否越界
            hit_stop = price <= pos.stop if pos.side == "LONG" else price >= pos.stop
            hit_take = price >= pos.take if pos.side == "LONG" else price <= pos.take
            
            if hit_stop or hit_take:
                reason = "STOP(强平)" if hit_stop else "TAKE(强平)"
                
                # 同样设置冷却
                self.cooldown_until[sym] = time.time() + 3600
                logger.info(f"{sym}: 价格越界({reason}) -> 市价强平 -> 冷却1小时")
                
                await self.close_position_market(sym, pos, price, reason)
                to_remove.append(sym)
                continue

        for sym in to_remove:
            self.positions.pop(sym, None)

    async def close_position_market(self, symbol: str, pos: Position, price: float, reason: str):
        """市价平仓（兜底用）"""
        side = "SELL" if pos.side == "LONG" else "BUY"
        pos_side = "LONG" if pos.side == "LONG" else "SHORT"
        try:
            # 撤单
            if pos.stop_order_id:
                self.client.cancel_order(symbol, pos.stop_order_id)
            if pos.take_order_id:
                self.client.cancel_order(symbol, pos.take_order_id)

            # 市价平
            self.client.place_market_order(
                symbol=symbol,
                side=side,
                quantity=pos.qty,
                position_side=pos_side,
                reduce_only=False,
            )
            
            pnl = (price - pos.entry_price) * pos.qty
            if pos.side == "SHORT":
                pnl = -pnl
                
            self.trade_logger.info(
                f"[离场] {symbol} | 原因:{reason} | 盈亏:{pnl:+.4f}USDT"
            )
        except Exception as e:
            logger.error(f"{symbol}: 平仓异常 {e}", exc_info=True)
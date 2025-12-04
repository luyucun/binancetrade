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
    entry_time: float = 0.0  # 开仓时间戳
    partial_closed: bool = False  # 是否已平仓70% (第一档止盈)
    full_take_triggered: bool = False  # 是否触发全部平仓 (第二档止盈)
    breakeven_set: bool = False  # 是否已设置保本止损
    stop_order_id: int = None  # 止损单ID
    take_order_id: int = None  # 止盈单ID (第一档70%)
    take_order_id_2: int = None  # 止盈单ID (第二档30%)


class SimpleMomoEngine:
    """
    极简趋势跟随 (解锁版 V4 - 智能风控版):
    1. 策略: 15m定趋势 + 1m找爆发 (5根中4根同向)
    2. 过滤: RSI(14) 必须处于强势区 (45 < RSI < 75)
    3. 风控:
       - 超时清理: 持仓 > 1.5小时 (5400s) 强制平仓
       - 阶梯止损: 
         * 浮盈 > 0.8 ATR -> 保本
         * 浮盈 > 1.5 ATR -> 锁定0.5 ATR利润
       - 止损: 2.5 ATR
       - 止盈: 2.0 ATR(70%) + 2.5 ATR(30%)
    """

    def __init__(self):
        self.client = BinanceClientV2(API_KEY, API_SECRET, testnet=TESTNET)
        self.positions: Dict[str, Position] = {}
        self.opening_symbols = set()
        self.cooldown_until: Dict[str, float] = {}
        self.global_cooldown_until = 0.0
        
        # 亏损熔断记录
        self.last_loss_direction: Dict[str, str] = {}
        self.direction_block_until: Dict[str, float] = {}

        # BTC大势缓存
        self.btc_trend_cache = {"trend": "", "expire": 0}

        # RSI历史
        self.rsi_history: Dict[str, float] = {}

        self._setup_exchange()
        self._setup_logging()
        self._sync_positions_from_exchange()

        logger.info(
            f"SimpleMomo V4 (智能风控版) 启动 | 止损=2.5ATR | 超时清理=1.5h | "
            f"移动止损=开启"
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
        """从交易所同步现有持仓到内存"""
        try:
            positions = self.client.get_positions()
            if positions is None:
                logger.warning("启动同步持仓失败，API可能超时")
                return

            for pos in positions:
                symbol = pos['symbol']
                side = pos['side']

                kl = self.fetch_klines_15m(symbol, limit=50)
                if not kl:
                    logger.warning(f"[同步] {symbol}: K线获取失败，跳过")
                    continue

                atr_val = self.atr(kl)
                price = pos['mark_price']
                qty = pos['quantity']

                # 获取真实开仓时间
                entry_time = self.client.get_position_entry_time(symbol, side)
                if entry_time is None:
                    entry_time = time.time()
                    logger.warning(f"[同步] {symbol}: 无法获取开仓时间，使用当前时间")

                # 估算止损止盈（基于入场价）
                entry_price = pos['entry_price']
                
                # 同步时止损宽带维持 2.5 ATR
                if atr_val > 0:
                    stop = entry_price - 2.5 * atr_val if side == "LONG" else entry_price + 2.5 * atr_val
                    take = entry_price + 2.0 * atr_val if side == "LONG" else entry_price - 2.0 * atr_val
                else:
                    stop = entry_price * 0.95 if side == "LONG" else entry_price * 1.05
                    take = entry_price * 1.02 if side == "LONG" else entry_price * 0.98

                self.positions[symbol] = Position(
                    symbol=symbol,
                    side=side,
                    entry_price=entry_price,
                    qty=qty,
                    stop=stop,
                    take=take,
                    atr=atr_val,
                    entry_time=entry_time
                )

                holding_mins = (time.time() - entry_time) / 60
                logger.info(f"[同步持仓] {symbol} | 方向:{side} | 数量:{qty} | 已持仓:{holding_mins:.1f}分钟")

        except Exception as e:
            logger.error(f"同步持仓失败: {e}", exc_info=True)

    def get_top_volume_symbols(self) -> List[str]:
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
            volume = float(t.get("quoteVolume", 0))
            volumes.append((sym, volume))
        volumes.sort(key=lambda x: x[1], reverse=True)
        return [s for s, _ in volumes[:50]]

    def fetch_klines(self, symbol: str, limit: int = 50):
        return self.client.get_klines(symbol, "1m", limit)

    def fetch_klines_15m(self, symbol: str, limit: int = 20):
        return self.client.get_klines(symbol, "15m", limit)

    def get_15m_trend(self, symbol: str) -> str:
        kl = self.fetch_klines_15m(symbol, limit=20)
        if not kl or len(kl) < 10: return ""
        seg = kl[-11:-1] if len(kl) >= 11 else kl[:-1]
        if len(seg) < 5: return ""

        first_close = seg[0]["close"]
        last_close = seg[-1]["close"]
        up_count = sum(1 for k in seg if k["close"] > k["open"])
        down_count = len(seg) - up_count
        price_trend_up = last_close > first_close
        price_trend_down = last_close < first_close

        if price_trend_up and up_count > down_count: return "UP"
        if price_trend_down and down_count > up_count: return "DOWN"
        return ""

    def atr(self, klines) -> float:
        if len(klines) < ATR_PERIOD + 1: return 0.0
        trs = []
        prev_close = klines[-ATR_PERIOD - 1]["close"]
        for k in klines[-ATR_PERIOD:]:
            high, low, close = k["high"], k["low"], k["close"]
            trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
            prev_close = close
        return sum(trs) / len(trs)

    def calculate_rsi(self, klines, period=14) -> float:
        if len(klines) < period + 1: return 50.0
        closes = [x['close'] for x in klines]
        gains = []
        losses = []
        for i in range(1, len(closes)):
            change = closes[i] - closes[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        if avg_loss == 0: return 100.0 if avg_gain > 0 else 50.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def last_n_same_direction(self, klines, n: int) -> str:
        """5根中4根同向 (n应该在config设为5)"""
        if len(klines) < n + 1: return ""
        seg = klines[-(n + 1):-1]
        up_count = sum(1 for k in seg if k["close"] > k["open"])
        down_count = n - up_count
        threshold = 4 if n <= 6 else 7
        if up_count >= threshold: return "UP"
        if down_count >= threshold: return "DOWN"
        return ""

    # ==================== 大势过滤器 (已放宽) ====================
    def calculate_ema(self, closes: List[float], period: int) -> float:
        if len(closes) < period: return closes[-1] if closes else 0
        multiplier = 2 / (period + 1)
        ema = sum(closes[:period]) / period
        for price in closes[period:]:
            ema = (price - ema) * multiplier + ema
        return ema

    def get_btc_trend(self) -> str:
        now = time.time()
        if self.btc_trend_cache["expire"] > now and self.btc_trend_cache["trend"]:
            return self.btc_trend_cache["trend"]
        try:
            klines = self.client.get_klines("BTCUSDT", "1h", limit=200)
            if not klines or len(klines) < 145: return ""
            closes = [k['close'] for k in klines]
            ema144 = self.calculate_ema(closes, 144)
            trend = "UP" if closes[-1] > ema144 else "DOWN"
            self.btc_trend_cache = {"trend": trend, "expire": now + 300}
            return trend
        except Exception as e:
            return ""

    def check_trend_filter(self, symbol: str, side: str) -> tuple:
        btc_trend = self.get_btc_trend()
        if btc_trend:
            if side == "SHORT" and btc_trend == "UP":
                return True, f"注意:BTC大盘上涨中(>EMA144)，逆势做空"
            if side == "LONG" and btc_trend == "DOWN":
                return True, f"注意:BTC大盘下跌中(<EMA144)，逆势做多"
        return True, ""

    # ==================== 同向亏损熔断 ====================
    def check_direction_block(self, symbol: str, side: str) -> tuple:
        now = time.time()
        if symbol in self.direction_block_until:
            if now < self.direction_block_until[symbol]:
                last_loss = self.last_loss_direction.get(symbol, "")
                if last_loss == side:
                    remaining = int((self.direction_block_until[symbol] - now) / 60)
                    return False, f"{symbol}同向({side})亏损封锁中，剩余{remaining}分钟"
        return True, ""

    def record_loss(self, symbol: str, side: str):
        self.last_loss_direction[symbol] = side
        self.direction_block_until[symbol] = time.time() + 4 * 3600
        logger.info(f"[熔断] {symbol} {side}方向亏损，封锁该方向4小时")

    # ==================== RSI 趋势强度 ====================
    def check_rsi_reversal(self, symbol: str, klines, side: str) -> tuple:
        current_rsi = self.calculate_rsi(klines)
        self.rsi_history[symbol] = current_rsi

        if side == "LONG":
            if current_rsi < 45:
                return False, current_rsi, f"RSI({current_rsi:.1f})过弱(<45)，动能不足"
            if current_rsi > 75:
                return False, current_rsi, f"RSI({current_rsi:.1f})超买(>75)，风险过高"
            return True, current_rsi, ""

        if side == "SHORT":
            if current_rsi > 55:
                return False, current_rsi, f"RSI({current_rsi:.1f})过强(>55)，动能不足"
            if current_rsi < 25:
                return False, current_rsi, f"RSI({current_rsi:.1f})超卖(<25)，追空风险大"
            return True, current_rsi, ""

        return True, current_rsi, ""

    async def run(self):
        logger.info("开始主循环...")
        while True:
            try:
                await self.step()
            except Exception as e:
                logger.error(f"循环异常: {e}", exc_info=True)
            await asyncio.sleep(CHECK_INTERVAL)

    def get_actual_positions_from_exchange(self):
        try:
            positions = self.client.get_positions()
            active_symbols = set()
            if positions:
                for pos in positions: active_symbols.add(pos['symbol'])
            return active_symbols
        except Exception as e:
            logger.error(f"获取实际持仓失败: {e}")
            return None

    async def step(self):
        try:
            await self.monitor_positions()
        except Exception as e:
            logger.error(f"监控持仓异常: {e}")

        if time.time() < self.global_cooldown_until:
            return

        candidates = self.get_top_volume_symbols()
        if not candidates: return

        actual_positions = self.get_actual_positions_from_exchange()
        if actual_positions is None: return

        logger.info(
            f"Scanning | 候选: {len(candidates)} | 持仓: {len(actual_positions)}/{MAX_POSITIONS} (内存:{len(self.positions)}) | "
            f"冷却中: {len([k for k,v in self.cooldown_until.items() if v > time.time()])}"
        )

        for sym in candidates:
            if sym in actual_positions or sym in self.opening_symbols: continue
            if len(actual_positions) >= MAX_POSITIONS: break
            if sym in self.cooldown_until and time.time() < self.cooldown_until[sym]: continue

            kl = self.fetch_klines(sym, limit=50)
            if not kl: continue

            # 1. 趋势
            dir_1m = self.last_n_same_direction(kl, MIN_TREND_BARS)
            if not dir_1m: continue

            # 2. 共振
            kl_15m = self.fetch_klines_15m(sym, limit=50)
            if not kl_15m: continue
            trend_15m = self.get_15m_trend(sym)
            if dir_1m != trend_15m: continue

            side = "LONG" if dir_1m == "UP" else "SHORT"

            # 3. 过滤器
            trend_ok, trend_reason = self.check_trend_filter(sym, side)
            if not trend_ok: logger.info(f"大势提示: {trend_reason}")

            block_ok, block_reason = self.check_direction_block(sym, side)
            if not block_ok: continue

            rsi_ok, rsi_val, rsi_reason = self.check_rsi_reversal(sym, kl, side)
            if not rsi_ok: continue

            atr_val = self.atr(kl_15m)
            if atr_val <= 0: continue

            price = kl[-1]["close"]
            logger.info(f"⚡信号触发: {sym} | {side} | RSI:{rsi_val:.1f} | 15m:{trend_15m}")

            self.global_cooldown_until = time.time() + 300
            self.opening_symbols.add(sym)
            try:
                await self.open_position(sym, side, price, atr_val)
                break
            finally:
                self.opening_symbols.discard(sym)

    async def open_position(self, symbol: str, side: str, price: float, atr: float):
        qty = ENTRY_USDT / price
        
        # 止损保持 2.5 ATR
        stop = price - 2.5 * atr if side == "LONG" else price + 2.5 * atr
        
        take_1 = price + 2.0 * atr if side == "LONG" else price - 2.0 * atr
        take_2 = price + 2.5 * atr if side == "LONG" else price - 2.5 * atr
        pos_side = "LONG" if side == "LONG" else "SHORT"
        close_side = "SELL" if side == "LONG" else "BUY"

        try:
            self.client.set_margin_type(symbol, MARGIN_TYPE)
            self.client.set_leverage(symbol, LEVERAGE)

            order = self.client.place_market_order(
                symbol=symbol,
                side="BUY" if side == "LONG" else "SELL",
                quantity=qty,
                position_side=pos_side,
                reduce_only=False,
            )
            if not order: return

            actual_qty = order.get('filled', qty)
            if actual_qty == 0: actual_qty = order.get('quantity', qty)

            adjusted_total = self.client.adjust_quantity(symbol, actual_qty)
            if not adjusted_total:
                logger.error(f"{symbol}: 数量精度调整失败")
                return

            qty_take_1_raw = adjusted_total * 0.7
            qty_take_1 = self.client.adjust_quantity(symbol, qty_take_1_raw) or qty_take_1_raw
            qty_take_2 = adjusted_total - qty_take_1

            stop_order_id = self.client.set_stop_loss(
                symbol=symbol, quantity=adjusted_total, stop_price=stop, side=close_side, position_side=pos_side
            )
            take_order_id = self.client.set_take_profit(
                symbol=symbol, quantity=qty_take_1, stop_price=take_1, side=close_side, position_side=pos_side
            )
            take_order_id_2 = self.client.set_take_profit(
                symbol=symbol, quantity=qty_take_2, stop_price=take_2, side=close_side, position_side=pos_side
            )

            self.positions[symbol] = Position(
                symbol=symbol, side=side, entry_price=price, qty=adjusted_total,
                stop=stop, take=take_1, atr=atr,
                entry_time=time.time(),
                stop_order_id=stop_order_id, take_order_id=take_order_id,
                take_order_id_2=take_order_id_2
            )

            log_msg = (f"[入场] {symbol} | 方向:{side} | 价格:{price:.4f} | "
                       f"止损:{stop:.4f}(2.5ATR) | 止盈1:{take_1:.4f}")
            self.trade_logger.info(log_msg)
            logger.info(log_msg)

        except Exception as e:
            logger.error(f"{symbol}: 开仓流程异常 {e}", exc_info=True)

    async def monitor_positions(self):
        prices = self.client.get_all_prices()
        actual_positions = self.get_actual_positions_from_exchange()
        if actual_positions is None: return

        # 检查是否有遗漏的持仓需要同步
        if actual_positions and len(self.positions) < len(actual_positions):
            missing = actual_positions - set(self.positions.keys())
            if missing:
                logger.info(f"检测到未同步的持仓: {missing}，尝试同步...")
                self._sync_positions_from_exchange()

        if not self.positions: return

        to_remove = []
        for sym, pos in list(self.positions.items()):
            price = prices.get(sym, 0)
            
            # 1. 检查仓位是否已在交易所消失（止盈止损触发）
            if sym not in actual_positions:
                reason = "挂单触发"
                if price:
                    is_profit = price > pos.entry_price if pos.side == "LONG" else price < pos.entry_price
                    reason = "止盈" if is_profit else "止损"
                if "止损" in reason: self.record_loss(sym, pos.side)
                self.cooldown_until[sym] = time.time() + 3600
                logger.info(f"{sym}: 仓位结束({reason}) -> 冷却1小时")
                self.trade_logger.info(f"[离场] {sym} | 原因:{reason}")
                to_remove.append(sym)
                continue

            if not price: continue

            # 计算持仓时间和浮盈ATR
            holding_time = time.time() - pos.entry_time
            if pos.atr > 0:
                profit_atr = (price - pos.entry_price) / pos.atr if pos.side == "LONG" else (pos.entry_price - price) / pos.atr
            else:
                profit_atr = 0

            # ==================================================
            # 1. 超时强制清理 (1.5小时 = 5400秒)
            # ==================================================
            if holding_time > 5400:  
                reason = f"超时清理(持仓>1.5h)"
                logger.info(f"[超时] {sym}: 持仓过久，强制释放仓位 | 当前盈亏:{profit_atr:.2f}ATR")
                self.cooldown_until[sym] = time.time() + 1800 # 冷却30分钟
                await self.close_position_market(sym, pos, price, reason)
                to_remove.append(sym)
                continue

            # ==================================================
            # 2. 阶梯移动止损
            # ==================================================
            if pos.atr > 0:
                # 阶段 1: 基础保本 (浮盈 > 0.8 ATR -> 移至 入场价)
                if profit_atr >= 0.8 and not pos.breakeven_set:
                    new_stop = pos.entry_price * 1.001 if pos.side == "LONG" else pos.entry_price * 0.999
                    if self._update_stop_loss(sym, pos, new_stop):
                        pos.breakeven_set = True
                        logger.info(f"[移动止损] {sym}: 浮盈{profit_atr:.2f}ATR -> 止损移至保本")

                # 阶段 2: 利润锁定 (浮盈 > 1.5 ATR -> 移至 入场价 + 0.5 ATR)
                # 只有当止损还没移动到更优位置时才执行
                elif profit_atr >= 1.5:
                    lock_profit_price = pos.entry_price + (0.5 * pos.atr) if pos.side == "LONG" else pos.entry_price - (0.5 * pos.atr)
                    
                    # 检查新止损是否比旧止损更优
                    is_better = lock_profit_price > pos.stop if pos.side == "LONG" else lock_profit_price < pos.stop
                    
                    if is_better:
                        if self._update_stop_loss(sym, pos, lock_profit_price):
                            logger.info(f"[移动止损] {sym}: 浮盈{profit_atr:.2f}ATR -> 锁定0.5ATR利润")

            # 兜底
            hit_stop = price <= pos.stop if pos.side == "LONG" else price >= pos.stop
            take_2_price = pos.entry_price + 2.5 * pos.atr if pos.side == "LONG" else pos.entry_price - 2.5 * pos.atr
            hit_full_take = price >= take_2_price if pos.side == "LONG" else price <= take_2_price

            if hit_stop:
                reason = "STOP(强平)"
                if not pos.breakeven_set: self.record_loss(sym, pos.side)
                self.cooldown_until[sym] = time.time() + 3600
                await self.close_position_market(sym, pos, price, reason)
                to_remove.append(sym)
            elif hit_full_take:
                reason = "TAKE(全平)"
                self.cooldown_until[sym] = time.time() + 3600
                await self.close_position_market(sym, pos, price, reason)
                to_remove.append(sym)

        for sym in to_remove:
            self.positions.pop(sym, None)

    def _update_stop_loss(self, symbol: str, pos: Position, new_price: float) -> bool:
        """辅助函数：更新止损单"""
        try:
            if pos.stop_order_id:
                try:
                    self.client.cancel_order(symbol, pos.stop_order_id)
                except Exception:
                    pass
            
            close_side = "SELL" if pos.side == "LONG" else "BUY"
            pos_side_str = "LONG" if pos.side == "LONG" else "SHORT"
            
            new_id = self.client.set_stop_loss(
                symbol=symbol, quantity=pos.qty, stop_price=new_price, side=close_side, position_side=pos_side_str
            )
            
            if new_id:
                pos.stop_order_id = new_id
                pos.stop = new_price
                return True
            return False
        except Exception as e:
            logger.error(f"{symbol}: 更新止损失败 {e}")
            return False

    async def close_position_market(self, symbol: str, pos: Position, price: float, reason: str):
        side = "SELL" if pos.side == "LONG" else "BUY"
        pos_side = "LONG" if pos.side == "LONG" else "SHORT"
        try:
            # 先取消挂单
            if pos.stop_order_id:
                try:
                    self.client.cancel_order(symbol, pos.stop_order_id)
                except Exception:
                    pass
            if pos.take_order_id:
                try:
                    self.client.cancel_order(symbol, pos.take_order_id)
                except Exception:
                    pass
            if pos.take_order_id_2:
                try:
                    self.client.cancel_order(symbol, pos.take_order_id_2)
                except Exception:
                    pass

            # 市价平仓
            self.client.place_market_order(
                symbol=symbol, side=side, quantity=pos.qty, position_side=pos_side, reduce_only=False,
            )
            pnl = (price - pos.entry_price) * pos.qty
            if pos.side == "SHORT": pnl = -pnl
            self.trade_logger.info(f"[离场] {symbol} | 原因:{reason} | 盈亏:{pnl:+.4f}USDT")
        except Exception as e:
            logger.error(f"{symbol}: 平仓异常 {e}", exc_info=True)
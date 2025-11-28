"""
SimpleMomo 交易引擎 (带Web界面支持)
在原有引擎基础上添加Web通信功能
"""
import asyncio
import logging
import time
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

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
    atr: float = 0.0
    partial_closed: bool = False
    stop_order_id: int = None
    take_order_id: int = None
    current_price: float = 0.0  # 当前价格（用于UI显示）


class SimpleMomoEngineWithWeb:
    """
    带Web界面的交易引擎
    继承原有策略逻辑，增加与Web界面的通信
    """

    def __init__(self, web_state=None):
        self.client = BinanceClientV2(API_KEY, API_SECRET, testnet=TESTNET)
        self.positions: Dict[str, Position] = {}
        self.opening_symbols = set()
        self.cooldown_until: Dict[str, float] = {}
        self.global_cooldown_until = 0.0

        # Web状态对象（用于向UI推送数据）
        self.web_state = web_state
        self.is_paused = False  # 策略暂停标志

        self._setup_exchange()
        self._setup_logging()
        self._sync_positions_from_exchange()

        self._log("INFO", f"SimpleMomo 启动 | testnet={TESTNET} | 固定仓位={ENTRY_USDT}USDT")

        # 初始化余额
        self._update_balance()

    def _log(self, level: str, message: str):
        """统一日志方法，同时输出到文件和Web"""
        if level == "INFO":
            logger.info(message)
        elif level == "WARNING":
            logger.warning(message)
        elif level == "ERROR":
            logger.error(message)

        # 推送到Web
        if self.web_state:
            try:
                from simple_momo.web_server import add_log
                add_log(level, message)
            except Exception as e:
                logger.debug(f"推送日志到Web失败: {e}")

    def _update_web_state(self):
        """更新Web界面状态"""
        if not self.web_state:
            return

        try:
            # 更新持仓信息
            positions_dict = {}
            for sym, pos in self.positions.items():
                positions_dict[sym] = {
                    "symbol": pos.symbol,
                    "side": pos.side,
                    "entry_price": pos.entry_price,
                    "qty": pos.qty,
                    "stop": pos.stop,
                    "take": pos.take,
                    "current_price": pos.current_price,
                }

            from simple_momo.web_server import update_positions, update_cooldowns, set_running

            update_positions(positions_dict)

            # 更新冷却状态
            now = time.time()
            active_cooldowns = {k for k, v in self.cooldown_until.items() if v > now}
            global_remaining = max(0, int(self.global_cooldown_until - now))
            update_cooldowns(active_cooldowns, global_remaining)

            # 更新运行状态
            set_running(not self.is_paused)
        except Exception as e:
            logger.debug(f"Web状态更新失败: {e}")

    def _update_balance(self):
        """更新账户余额"""
        if not self.web_state:
            return
        try:
            balance = self.client.get_account_balance()
            if balance is not None:
                from simple_momo.web_server import update_balance
                update_balance(balance)
        except Exception as e:
            logger.warning(f"获取余额失败: {e}")

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
        """启动时从交易所同步现有持仓到内存"""
        try:
            positions = self.client.get_positions()
            for pos in positions:
                symbol = pos['symbol']
                kl = self.fetch_klines_15m(symbol, limit=50)
                if not kl:
                    self._log("WARNING", f"{symbol}: 无法获取15分钟K线数据，跳过同步")
                    continue

                atr_val = self.atr(kl)
                price = pos['mark_price']
                qty = pos['quantity']
                side = pos['side']

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
                    atr=atr_val,
                    current_price=price
                )
                self._log("INFO", f"[同步持仓] {symbol} | 方向:{side} | 入场:{pos['entry_price']:.4f}")

            if positions:
                self._log("INFO", f"已同步 {len(positions)} 个交易所持仓到内存")
            else:
                self._log("INFO", "交易所当前无持仓")

            self._update_web_state()
        except Exception as e:
            self._log("ERROR", f"同步持仓失败: {e}")

    def get_top_volume_symbols(self) -> List[str]:
        try:
            tickers = self.client.client.futures_ticker()
        except Exception as e:
            self._log("WARNING", f"获取交易量排行榜失败: {e}")
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
        if not kl or len(kl) < 10:
            return ""
        seg = kl[-11:-1] if len(kl) >= 11 else kl[:-1]
        if len(seg) < 5:
            return ""
        first_close = seg[0]["close"]
        last_close = seg[-1]["close"]
        up_count = sum(1 for k in seg if k["close"] > k["open"])
        down_count = len(seg) - up_count
        if last_close > first_close and up_count > down_count:
            return "UP"
        if last_close < first_close and down_count > up_count:
            return "DOWN"
        return ""

    def atr(self, klines) -> float:
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
        if len(klines) < period + 1:
            return 50.0
        closes = [x['close'] for x in klines]
        gains, losses = [], []
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
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def last_n_same_direction(self, klines, n: int) -> str:
        if len(klines) < n + 1:
            return ""
        seg = klines[-(n + 1):-1]
        up_count = sum(1 for k in seg if k["close"] > k["open"])
        down_count = n - up_count
        if up_count >= 7:
            return "UP"
        if down_count >= 7:
            return "DOWN"
        return ""

    def get_actual_positions_from_exchange(self):
        try:
            positions = self.client.get_positions()
            # 如果返回None，说明API调用失败了
            if positions is None:
                self._log("WARNING", "获取持仓失败（API超时），保护内存持仓不被删除")
                return None

            active_symbols = set()
            if positions:
                for pos in positions:
                    active_symbols.add(pos['symbol'])
            return active_symbols
        except Exception as e:
            self._log("ERROR", f"获取实际持仓异常: {e}")
            return None

    async def run(self):
        self._log("INFO", "开始主循环...")
        if self.web_state:
            from simple_momo.web_server import set_running
            set_running(True)

        while True:
            try:
                # 检查Web命令队列（高优先级）
                if self.web_state and self.web_state.command_queue:
                    cmd = self.web_state.command_queue.pop(0)
                    if cmd.get("action") == "pause":
                        self.is_paused = True
                        self._log("INFO", "收到暂停命令，立即暂停")
                    elif cmd.get("action") == "resume":
                        self.is_paused = False
                        self._log("INFO", "收到启动命令，立即启动")

                # 检查Web暂停状态
                if self.web_state:
                    from simple_momo.web_server import state as web_state
                    self.is_paused = not web_state.is_running

                if not self.is_paused:
                    await self.step()

                # 定期更新余额（每分钟）
                if int(time.time()) % 60 == 0:
                    self._update_balance()

            except Exception as e:
                self._log("ERROR", f"循环异常: {e}")

            await asyncio.sleep(CHECK_INTERVAL)

    async def step(self):
        # 1. 监控已有持仓
        try:
            await self.monitor_positions()
        except Exception as e:
            self._log("ERROR", f"监控持仓异常: {e}")

        # 2. 检查全局冷却
        if time.time() < self.global_cooldown_until:
            self._update_web_state()
            return

        # 3. 获取候选币种
        candidates = self.get_top_volume_symbols()
        if not candidates:
            return

        actual_positions = self.get_actual_positions_from_exchange()
        if actual_positions is None:
            self._log("WARNING", "无法获取交易所持仓，跳过本轮选币")
            return

        self._log("INFO",
            f"Scanning | 候选: {len(candidates)} | 持仓: {len(self.positions)}/{MAX_POSITIONS} | "
            f"冷却中: {len([k for k,v in self.cooldown_until.items() if v > time.time()])}"
        )

        for sym in candidates:
            if sym in actual_positions:
                continue
            if sym in self.opening_symbols:
                continue
            if len(actual_positions) >= MAX_POSITIONS:
                break

            if sym in self.cooldown_until and time.time() < self.cooldown_until[sym]:
                continue

            kl = self.fetch_klines(sym, limit=50)
            if not kl:
                continue

            dir_1m = self.last_n_same_direction(kl, MIN_TREND_BARS)
            if not dir_1m:
                continue

            rsi_val = self.calculate_rsi(kl)
            if dir_1m == "UP" and rsi_val > 70:
                continue
            if dir_1m == "DOWN" and rsi_val < 30:
                continue

            kl_15m = self.fetch_klines_15m(sym, limit=50)
            if not kl_15m:
                continue
            trend_15m = self.get_15m_trend(sym)
            if dir_1m != trend_15m:
                continue

            atr_val = self.atr(kl_15m)
            if atr_val <= 0:
                continue

            price = kl[-1]["close"]
            side = "LONG" if dir_1m == "UP" else "SHORT"

            self._log("INFO", f"⚡信号触发: {sym} | {side} | RSI:{rsi_val:.1f} | 15m:{trend_15m}")

            self.global_cooldown_until = time.time() + 300

            self.opening_symbols.add(sym)
            try:
                await self.open_position(sym, side, price, atr_val)
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
            self.client.set_margin_type(symbol, MARGIN_TYPE)
            self.client.set_leverage(symbol, LEVERAGE)

            order = self.client.place_market_order(
                symbol=symbol,
                side="BUY" if side == "LONG" else "SELL",
                quantity=qty,
                position_side=pos_side,
                reduce_only=False,
            )
            if not order:
                self._log("ERROR", f"{symbol}: 开仓下单失败")
                return

            actual_qty = order.get('filled', qty)
            if actual_qty == 0:
                actual_qty = order.get('quantity', qty)

            stop_order_id = self.client.set_stop_loss(
                symbol=symbol, quantity=actual_qty, stop_price=stop,
                side=close_side, position_side=pos_side
            )

            take_order_id = self.client.set_take_profit(
                symbol=symbol, quantity=actual_qty, stop_price=take,
                side=close_side, position_side=pos_side
            )

            self.positions[symbol] = Position(
                symbol=symbol, side=side, entry_price=price, qty=actual_qty,
                stop=stop, take=take, atr=atr,
                stop_order_id=stop_order_id, take_order_id=take_order_id,
                current_price=price
            )

            log_msg = f"[入场] {symbol} | 方向:{side} | 价格:{price:.4f} | 止损:{stop:.4f} | 止盈:{take:.4f}"
            self.trade_logger.info(log_msg)
            self._log("INFO", log_msg)

            self._update_web_state()
            self._update_balance()

        except Exception as e:
            self._log("ERROR", f"{symbol}: 开仓流程异常 {e}")

    async def monitor_positions(self):
        if not self.positions:
            self._update_web_state()
            return

        prices = self.client.get_all_prices()
        actual_positions = self.get_actual_positions_from_exchange()

        if actual_positions is None:
            self._log("WARNING", "无法获取交易所持仓，跳过本轮监控")
            return

        # 更新当前价格
        for sym, pos in self.positions.items():
            if sym in prices:
                pos.current_price = prices[sym]

        to_remove = []
        for sym, pos in list(self.positions.items()):
            if sym not in actual_positions:
                current_price = prices.get(sym, 0)
                reason = "挂单触发"
                is_win = False

                if current_price:
                    if pos.side == "LONG":
                        is_win = current_price > pos.entry_price
                    else:
                        is_win = current_price < pos.entry_price
                    reason = "止盈" if is_win else "止损"

                self.cooldown_until[sym] = time.time() + 3600

                self._log("INFO", f"{sym}: 仓位结束({reason}) -> 冷却1小时")
                self.trade_logger.info(f"[离场] {sym} | 原因:{reason} | 方向:{pos.side}")

                # 更新Web统计
                if self.web_state:
                    pnl = (current_price - pos.entry_price) * pos.qty
                    if pos.side == "SHORT":
                        pnl = -pnl
                    from simple_momo.web_server import update_trade_stats
                    update_trade_stats(pnl, is_win)

                to_remove.append(sym)
                continue

            price = prices.get(sym)
            if not price:
                continue

            hit_stop = price <= pos.stop if pos.side == "LONG" else price >= pos.stop
            hit_take = price >= pos.take if pos.side == "LONG" else price <= pos.take

            if hit_stop or hit_take:
                reason = "STOP(强平)" if hit_stop else "TAKE(强平)"
                is_win = hit_take

                self.cooldown_until[sym] = time.time() + 3600
                self._log("INFO", f"{sym}: 价格越界({reason}) -> 市价强平 -> 冷却1小时")

                await self.close_position_market(sym, pos, price, reason)

                # 更新Web统计
                if self.web_state:
                    pnl = (price - pos.entry_price) * pos.qty
                    if pos.side == "SHORT":
                        pnl = -pnl
                    from simple_momo.web_server import update_trade_stats
                    update_trade_stats(pnl, is_win)

                to_remove.append(sym)
                continue

        for sym in to_remove:
            self.positions.pop(sym, None)

        self._update_web_state()
        self._update_balance()

    async def close_position_market(self, symbol: str, pos: Position, price: float, reason: str):
        side = "SELL" if pos.side == "LONG" else "BUY"
        pos_side = "LONG" if pos.side == "LONG" else "SHORT"
        try:
            if pos.stop_order_id:
                self.client.cancel_order(symbol, pos.stop_order_id)
            if pos.take_order_id:
                self.client.cancel_order(symbol, pos.take_order_id)

            self.client.place_market_order(
                symbol=symbol, side=side, quantity=pos.qty,
                position_side=pos_side, reduce_only=False,
            )

            pnl = (price - pos.entry_price) * pos.qty
            if pos.side == "SHORT":
                pnl = -pnl

            self.trade_logger.info(f"[离场] {symbol} | 原因:{reason} | 盈亏:{pnl:+.4f}USDT")
        except Exception as e:
            self._log("ERROR", f"{symbol}: 平仓异常 {e}")

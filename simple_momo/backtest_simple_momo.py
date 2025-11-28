import argparse
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from binance_client_v2 import BinanceClientV2
from simple_momo import simple_config as cfg

MS_IN_MINUTE = 60_000
MS_IN_15M = 15 * MS_IN_MINUTE


def _format_ts(ms: int) -> str:
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M")


def calculate_rsi(klines: Sequence[Dict[str, float]], period: int = 14) -> float:
    if len(klines) < period + 1:
        return 50.0
    closes = [x["close"] for x in klines]
    gains: List[float] = []
    losses: List[float] = []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        if change > 0:
            gains.append(change)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(change))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def last_n_same_direction(klines: Sequence[Dict[str, float]], n: int) -> str:
    if len(klines) < n + 1:
        return ""
    seg = klines[-(n + 1) : -1]
    up_count = sum(1 for k in seg if k["close"] > k["open"])
    down_count = n - up_count
    if up_count >= 7:
        return "UP"
    if down_count >= 7:
        return "DOWN"
    return ""


def get_15m_trend(klines: Sequence[Dict[str, float]]) -> str:
    if not klines or len(klines) < 10:
        return ""
    seg = klines[-11:-1] if len(klines) >= 11 else klines[:-1]
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


def atr(klines: Sequence[Dict[str, float]], period: int) -> float:
    if len(klines) < period + 1:
        return 0.0
    trs: List[float] = []
    prev_close = klines[-period - 1]["close"]
    for k in klines[-period:]:
        high, low, close = k["high"], k["low"], k["close"]
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
        prev_close = close
    return sum(trs) / len(trs)


@dataclass
class PositionState:
    symbol: str
    side: str
    entry_price: float
    qty: float
    stop: float
    take: float
    atr: float
    entry_time: int


@dataclass
class TradeRecord:
    symbol: str
    side: str
    entry_time: int
    entry_price: float
    exit_time: int
    exit_price: float
    pnl: float
    reason: str


@dataclass
class SymbolState:
    bars_1m: List[Dict[str, float]]
    closed_15m: List[Dict[str, float]] = field(default_factory=list)
    current_15m: Optional[Dict[str, float]] = None
    next_idx: int = 0


class SimpleMomoBacktester:
    def __init__(
        self,
        client: BinanceClientV2,
        symbols: Optional[List[str]] = None,
        top_n: int = 20,
        days: int = 7,
        start_balance: float = 1000.0,
        warmup_days: float = 1.0,
    ) -> None:
        self.client = client
        self.days = days
        self.start_balance = start_balance
        self.balance = start_balance
        self.warmup_days = warmup_days
        self.symbols: List[str] = [s.upper() for s in symbols] if symbols else []
        self.top_n = top_n

        self.positions: Dict[str, PositionState] = {}
        self.cooldown_until: Dict[str, float] = {}
        self.global_cooldown_until: float = 0.0
        self.trades: List[TradeRecord] = []
        self.equity_curve: List[Tuple[float, float]] = []

        now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        self.end_ts_ms = now_ms
        self.start_ts_ms = now_ms - days * 24 * 60 * 60 * 1000
        self.warmup_start_ms = self.start_ts_ms - int(warmup_days * 24 * 60 * 60 * 1000)

        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
        self.log = logging.getLogger("backtest")

        self.symbol_states: Dict[str, SymbolState] = {}

    def run(self) -> None:
        self._load_symbols()
        self._fetch_data()

        timeline = self._build_time_grid()
        if not timeline:
            self.log.error("No data available for requested window.")
            return

        self.equity_curve.append((timeline[0] / 1000, self.balance))

        for ts in timeline:
            ts_sec = ts / 1000
            bars_this_time: Dict[str, Tuple[SymbolState, Dict[str, float]]] = {}

            for sym, state in self.symbol_states.items():
                if state.next_idx >= len(state.bars_1m):
                    continue
                bar = state.bars_1m[state.next_idx]
                if bar["time"] != ts:
                    continue

                state.next_idx += 1
                self._update_15m_state(state, bar)
                bars_this_time[sym] = (state, bar)
                self._monitor_position(sym, bar, ts_sec)

            if ts < self.start_ts_ms:
                continue

            if ts_sec < self.global_cooldown_until:
                continue

            self._try_open_positions(bars_this_time, ts_sec)

        self._close_all_positions()
        self._print_summary()

    def _load_symbols(self) -> None:
        if self.symbols:
            return
        coins = self.client.get_top_coins_by_volume(limit=self.top_n)
        self.symbols = [c["symbol"] for c in coins]
        self.log.info("Top symbols by 24h volume: %s", ", ".join(self.symbols))

    def _fetch_data(self) -> None:
        for sym in self.symbols:
            bars = self._fetch_klines_range(sym, "1m", self.warmup_start_ms, self.end_ts_ms)
            if not bars:
                self.log.warning("%s: missing data, skipping symbol.", sym)
                continue
            self.symbol_states[sym] = SymbolState(bars_1m=bars)
            self.log.info("%s: loaded %d x 1m bars.", sym, len(bars))

    def _fetch_klines_range(
        self, symbol: str, interval: str, start_ts: int, end_ts: int
    ) -> List[Dict[str, float]]:
        limit = 1500
        interval_ms = MS_IN_MINUTE if interval == "1m" else MS_IN_15M
        cursor = start_ts
        all_rows: List[Dict[str, float]] = []

        while cursor < end_ts:
            raw = self.client.client.futures_klines(
                symbol=symbol,
                interval=interval,
                startTime=cursor,
                endTime=end_ts,
                limit=limit,
            )
            if not raw:
                break
            for r in raw:
                all_rows.append(
                    {
                        "time": int(r[0]),
                        "open": float(r[1]),
                        "high": float(r[2]),
                        "low": float(r[3]),
                        "close": float(r[4]),
                        "volume": float(r[5]),
                    }
                )
            last_open = int(raw[-1][0])
            cursor = last_open + interval_ms
            if len(raw) < limit:
                break

        all_rows = [row for row in all_rows if row["time"] <= end_ts]
        all_rows.sort(key=lambda x: x["time"])
        return all_rows

    def _build_time_grid(self) -> List[int]:
        times = set()
        for state in self.symbol_states.values():
            for bar in state.bars_1m:
                times.add(bar["time"])
        return sorted(t for t in times if t <= self.end_ts_ms)

    def _update_15m_state(self, state: SymbolState, bar: Dict[str, float]) -> None:
        window_start = (bar["time"] // MS_IN_15M) * MS_IN_15M
        cur = state.current_15m
        if cur is None or cur["time"] != window_start:
            if cur:
                state.closed_15m.append(cur)
                if len(state.closed_15m) > 400:
                    state.closed_15m = state.closed_15m[-400:]
            cur = {
                "time": window_start,
                "open": bar["open"],
                "high": bar["high"],
                "low": bar["low"],
                "close": bar["close"],
                "volume": bar["volume"],
            }
        else:
            cur["high"] = max(cur["high"], bar["high"])
            cur["low"] = min(cur["low"], bar["low"])
            cur["close"] = bar["close"]
            cur["volume"] += bar["volume"]
        state.current_15m = cur

    def _current_15m_bars(self, state: SymbolState) -> List[Dict[str, float]]:
        bars = list(state.closed_15m[-80:]) if state.closed_15m else []
        if state.current_15m:
            bars.append(dict(state.current_15m))
        return bars

    def _monitor_position(self, symbol: str, bar: Dict[str, float], ts_sec: float) -> None:
        pos = self.positions.get(symbol)
        if not pos:
            return
        stop_hit = bar["low"] <= pos.stop if pos.side == "LONG" else bar["high"] >= pos.stop
        take_hit = bar["high"] >= pos.take if pos.side == "LONG" else bar["low"] <= pos.take
        if not stop_hit and not take_hit:
            return

        if stop_hit and take_hit:
            exit_price = pos.stop
            reason = "STOP (hit before TP assumed)"
        elif stop_hit:
            exit_price = pos.stop
            reason = "STOP"
        else:
            exit_price = pos.take
            reason = "TAKE"

        self._close_position(symbol, exit_price, ts_sec, reason)

    def _try_open_positions(
        self, bars_this_time: Dict[str, Tuple[SymbolState, Dict[str, float]]], ts_sec: float
    ) -> None:
        if len(self.positions) >= cfg.MAX_POSITIONS:
            return
        if not bars_this_time:
            return

        for sym in self.symbols:
            if sym not in bars_this_time:
                continue
            if sym in self.positions:
                continue
            if self.cooldown_until.get(sym, 0) > ts_sec:
                continue
            if len(self.positions) >= cfg.MAX_POSITIONS:
                break

            state, bar = bars_this_time[sym]
            kl_1m = state.bars_1m[: state.next_idx]
            kl_15m = self._current_15m_bars(state)

            dir_1m = last_n_same_direction(kl_1m, cfg.MIN_TREND_BARS)
            if not dir_1m:
                continue

            rsi_val = calculate_rsi(kl_1m)
            if dir_1m == "UP" and rsi_val > 70:
                continue
            if dir_1m == "DOWN" and rsi_val < 30:
                continue

            trend_15m = get_15m_trend(kl_15m)
            if dir_1m != trend_15m:
                continue

            atr_val = atr(kl_15m, cfg.ATR_PERIOD)
            if atr_val <= 0:
                continue

            price = bar["close"]
            side = "LONG" if dir_1m == "UP" else "SHORT"
            self._open_position(sym, side, price, atr_val, ts_sec)
            self.global_cooldown_until = ts_sec + 300
            break

    def _open_position(self, symbol: str, side: str, price: float, atr_val: float, ts_sec: float) -> None:
        qty = cfg.ENTRY_USDT / price
        stop = price - 0.8 * atr_val if side == "LONG" else price + 0.8 * atr_val
        take = price + 1.5 * atr_val if side == "LONG" else price - 1.5 * atr_val
        self.positions[symbol] = PositionState(
            symbol=symbol,
            side=side,
            entry_price=price,
            qty=qty,
            stop=stop,
            take=take,
            atr=atr_val,
            entry_time=int(ts_sec),
        )
        self.log.info(
            "[ENTRY] %s %s @ %.4f | stop=%.4f take=%.4f | ATR=%.4f RSI-safe",
            symbol,
            side,
            price,
            stop,
            take,
            atr_val,
        )

    def _close_position(self, symbol: str, exit_price: float, ts_sec: float, reason: str) -> None:
        pos = self.positions.pop(symbol, None)
        if not pos:
            return
        pnl = (exit_price - pos.entry_price) * pos.qty
        if pos.side == "SHORT":
            pnl = -pnl
        self.balance += pnl
        self.cooldown_until[symbol] = ts_sec + 3600
        self.trades.append(
            TradeRecord(
                symbol=symbol,
                side=pos.side,
                entry_time=pos.entry_time,
                entry_price=pos.entry_price,
                exit_time=int(ts_sec),
                exit_price=exit_price,
                pnl=pnl,
                reason=reason,
            )
        )
        self.equity_curve.append((ts_sec, self.balance))
        self.log.info(
            "[EXIT ] %s %s -> %.4f | pnl=%.4f | reason=%s",
            symbol,
            pos.side,
            exit_price,
            pnl,
            reason,
        )

    def _close_all_positions(self) -> None:
        for sym, pos in list(self.positions.items()):
            state = self.symbol_states.get(sym)
            if not state or state.next_idx == 0:
                continue
            bar = state.bars_1m[state.next_idx - 1]
            ts_sec = bar["time"] / 1000
            self._close_position(sym, bar["close"], ts_sec, "EOD")

    def _print_summary(self) -> None:
        total = len(self.trades)
        wins = sum(1 for t in self.trades if t.pnl > 0)
        total_pnl = sum(t.pnl for t in self.trades)
        win_rate = (wins / total * 100) if total else 0.0
        max_drawdown = self._max_drawdown()

        self.log.info("==== Backtest (last %d days) ====", self.days)
        self.log.info("Trades: %d | Wins: %d | Win rate: %.2f%%", total, wins, win_rate)
        self.log.info("PnL: %.4f USDT (start %.2f -> end %.2f)", total_pnl, self.start_balance, self.balance)
        self.log.info("Max drawdown: %.2f%%", max_drawdown * 100)

        for t in self.trades:
            self.log.info(
                "%s %s | %s -> %s | %.4f -> %.4f | pnl=%.4f | %s",
                t.symbol,
                t.side,
                _format_ts(t.entry_time * 1000),
                _format_ts(t.exit_time * 1000),
                t.entry_price,
                t.exit_price,
                t.pnl,
                t.reason,
            )

    def _max_drawdown(self) -> float:
        if not self.equity_curve:
            return 0.0
        peak = self.start_balance
        max_dd = 0.0
        for _, eq in self.equity_curve:
            peak = max(peak, eq)
            if peak == 0:
                continue
            dd = (eq - peak) / peak
            max_dd = min(max_dd, dd)
        return abs(max_dd)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest SimpleMomo strategy on the last N days.")
    parser.add_argument("--days", type=int, default=7, help="How many days to backtest (default: 7)")
    parser.add_argument("--symbols", nargs="+", help="Symbols to backtest (e.g. BTCUSDT ETHUSDT)")
    parser.add_argument("--top", type=int, default=20, help="If no symbols provided, pick top N by volume (default: 20)")
    parser.add_argument("--start-balance", type=float, default=1000.0, help="Starting balance for equity tracking")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    client = BinanceClientV2(cfg.API_KEY, cfg.API_SECRET, testnet=cfg.TESTNET)
    backtester = SimpleMomoBacktester(
        client=client,
        symbols=args.symbols,
        top_n=args.top,
        days=args.days,
        start_balance=args.start_balance,
    )
    backtester.run()


if __name__ == "__main__":
    main()

"""믹스 30분 봇 (owners 2026-10-25 night): the WOO X Pro SECOND account trades the 30-minute signal of the TradingView
indicator "추세 조건 OBV·클링거 + 매매 시그널" (TREND_MIX_CHOP_SIGNAL.pine, its signal part), with the formulas and rules
of the design notes the owners handed over (SIGNAL_30M_GUIDE.md, BOT_FORMULAS.md). Owners' choices on top of them: ONE
position at a time across the coins, coins SOL · ETH · XRP · BCH · ZEC · DOGE (LTC off), market orders, $50 to start.

    python -m paperbot.mixchop check   --config /etc/paperbot/mixchop.json   # reads only: specs, account, sizes now
    python -m paperbot.mixchop signals --config /etc/paperbot/mixchop.json   # recent colour changes, to compare with TV
    python -m paperbot.mixchop run     --config /etc/paperbot/mixchop.json   # the bot ("mode": "paper" or "mainnet")

Signal (every 30m close, closed Binance USDT-M bars only, as the TradingView chart the owners read):
- avgRsi = EMA3( 50 + 50 * (rS + cS + mS) / 3 ), rS = (RSI26 - 50) / 50, cS = zsq(ROC7, 100), mS = zsq(close - close[7],
  100), zsq(x, n) = tanh(x / stdev_n(x)) (0 when the deviation is 0 or not yet defined).
- the line: nScore = ((RSI26 - 50) / 50 + zsq(ROC9, 100) + zsq(close - close[10], 100)) / 3, nLine = its running sum,
  nSig = EMA9(nLine); gold = nLine > nSig. Long: gold on this bar and not on the one before (to cyan); short: the other way.
- long also needs the 30m avgRsi > 50 and the last CLOSED 1h bar's avgRsi > 50 - buffer; short: < 50 and < 50 + buffer
  (a 30m bar closing on the hour uses the 1h bar closing with it, a :30 close the one before). No late entries: a colour
  change whose RSI conditions fail is skipped until the next change.
- the stop distance ATR14(30m, the signal bar) x the coin's multiple must be shorter than price x (1 / leverage - 0.5 %),
  else the signal is skipped (liquidation guard).
Pine's own seeding is reproduced (RMA and EMA start from a simple average); with 1,500 bars of history the values agree
with TradingView's to the decimals (tests/test_mixchop.py checks the design's DOGE table).

Trade:
- size: a stop-out loses ``risk_pct`` (0.25 %) of the account equity: qty = equity x risk / stop distance, isolated at
  the coin's leverage (40x; ZEC 20x), floored to the contract step; under the minimum: skipped, never rounded up.
- entry: a market order right after the 30m close; the stop is the fill price -/+ the stop distance, placed at once as
  a resting close-only stop on WOO X Pro (last price). A stop that cannot be placed closes the position at market.
- ladder (ROE on the leverage, price-based like the indicator): best = the most favourable price since entry (30m
  highs / lows); at each 30m close that did not stop the position, when best is ``roe_act`` % ROE past the entry, the
  stop goes to entry + 10 % ROE, and one more step of (roe_act - 10) % ROE for each further step reached; it only ever
  moves the favourable way, and only at 30m closes. No exit on an opposite signal or on time: stop or ladder only.
- one position at a time over all coins; signals of one close compete by the coin order of the config.
- halts: the shared kill file or the bot's own stop file (no new entries; the open position keeps its stop and ladder;
  stop the service and close on WOO X Pro by hand to flatten), the equity floor (``equity_floor_frac`` of
  the starting equity: no new entries), any position on the account the bot does not know (no new entries, alert).
Restart: the state file holds the open position (coin, side, size, entry, stop, best, ladder step); at start it is
checked against WOO X Pro and the resting stop is placed again when missing. "paper" mode trades nothing: it fills at
the signal close and exits on the 30m bars as the indicator does (stop at the stop price, or the open when it gaps).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import signal as _signal
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Callable, Optional

import numpy as np
import pandas as pd

MIN30 = 30 * 60_000
H1 = 3_600_000
KST_MS = 9 * H1
BARS = 1500                     # history per request (Binance's maximum): enough for the EMA / RMA / sum to settle
SETTLE_S = 4.0                  # wait after a close before reading its bar
READ_TRIES = 12                 # ... and read again every 5 s while the bar is not there yet (1 minute)
POLL_S = 15.0                   # open position: how often WOO X Pro is asked whether it is still open
STOP_CHECK_S = 300.0            # ... and whether its stop is still resting
LOCK_ROE = 10.0                 # the first lock (the indicator's minimum take-profit, %)
MMR_PCT = 0.5                   # maintenance margin used by the liquidation guard (%)
# 30m settings of the design notes (BOT_FORMULAS.md 5): trend-bar buffer, stop ATR multiple, ladder start ROE, leverage
DEFAULT_COINS = {
    "SOLUSDT": {"h1_buf": 8.0, "sl_atr": 2.0, "roe_act": 150.0, "leverage": 40},
    "ETHUSDT": {"h1_buf": 8.5, "sl_atr": 1.5, "roe_act": 200.0, "leverage": 40},
    "XRPUSDT": {"h1_buf": 9.5, "sl_atr": 1.5, "roe_act": 200.0, "leverage": 40},
    "BCHUSDT": {"h1_buf": 3.0, "sl_atr": 2.0, "roe_act": 150.0, "leverage": 40},
    "ZECUSDT": {"h1_buf": 6.5, "sl_atr": 2.5, "roe_act": 100.0, "leverage": 20},
    "DOGEUSDT": {"h1_buf": 4.0, "sl_atr": 2.5, "roe_act": 100.0, "leverage": 40},
}
NAME = "믹스 30분 봇"
EXIT_KO = {"stop": "손절", "ladder": "계단 익절", "closed_while_down": "봇이 꺼진 사이 청산", "manual": "직접 청산",
           "protect": "손절을 못 걸어 바로 청산"}


class MixError(ValueError):
    """A configuration or state the bot refuses (Korean message)."""


# ====================================================================== indicators (Pine semantics)
def _seed_recursive(x: np.ndarray, n: int, alpha: float) -> np.ndarray:
    """Pine's ta.rma / ta.ema: NaN until n values exist, seeded with their simple average, then
    s = alpha * x + (1 - alpha) * s. ``x`` may start with NaN (they are skipped); later NaN keep the last value."""
    x = np.asarray(x, float)
    out = np.full(len(x), np.nan)
    ok = np.flatnonzero(np.isfinite(x))
    if len(ok) < n:
        return out
    f = ok[0]
    if not np.isfinite(x[f:f + n]).all():
        return out
    s = float(np.mean(x[f:f + n]))
    out[f + n - 1] = s
    for i in range(f + n, len(x)):
        v = x[i]
        if np.isfinite(v):
            s = alpha * v + (1.0 - alpha) * s
        out[i] = s
    return out


def rma(x, n: int) -> np.ndarray:
    return _seed_recursive(x, n, 1.0 / n)


def ema(x, n: int) -> np.ndarray:
    return _seed_recursive(x, n, 2.0 / (n + 1))


def rsi(close, n: int) -> np.ndarray:
    """Pine ta.rsi: Wilder's averages of the gains and losses; 100 when there is no loss, 0 when there is no gain."""
    c = np.asarray(close, float)
    ch = np.r_[np.nan, np.diff(c)]
    up = np.where(np.isfinite(ch), np.maximum(ch, 0.0), np.nan)
    dn = np.where(np.isfinite(ch), np.maximum(-ch, 0.0), np.nan)
    u, d = rma(up, n), rma(dn, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(d == 0, 100.0, np.where(u == 0, 0.0, 100.0 - 100.0 / (1.0 + u / d)))
    out[~(np.isfinite(u) & np.isfinite(d))] = np.nan
    return out


def stdev(x, n: int) -> np.ndarray:
    """Pine ta.stdev (population): NaN while the window holds a NaN."""
    return pd.Series(np.asarray(x, float)).rolling(n, min_periods=n).std(ddof=0).to_numpy()


def zsq(x, n: int) -> np.ndarray:
    """tanh(x / stdev_n(x)) with x / sd clipped to +-10; 0 when the deviation is 0 or undefined (Pine: na > 0 is
    false); NaN where x itself is undefined (the caller's nz makes it 0)."""
    x = np.asarray(x, float)
    sd = stdev(x, n)
    pos = np.isfinite(sd) & (sd > 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        z = np.tanh(np.clip(x / np.where(pos, sd, 1.0), -10, 10))
    out = np.where(pos, z, 0.0)
    out[~np.isfinite(x)] = np.nan
    return out


def roc(x, n: int) -> np.ndarray:
    x = np.asarray(x, float)
    prev = np.r_[np.full(n, np.nan), x[:-n]]
    with np.errstate(divide="ignore", invalid="ignore"):
        return 100.0 * (x - prev) / prev


def mom(x, n: int) -> np.ndarray:
    x = np.asarray(x, float)
    return x - np.r_[np.full(n, np.nan), x[:-n]]


def atr(high, low, close, n: int = 14) -> np.ndarray:
    h, l, c = (np.asarray(a, float) for a in (high, low, close))
    pc = np.r_[np.nan, c[:-1]]
    tr = np.where(np.isfinite(pc), np.maximum(h, pc) - np.minimum(l, pc), h - l)
    return rma(tr, n)


def _nz(x, d: float = 0.0) -> np.ndarray:
    x = np.asarray(x, float)
    return np.where(np.isfinite(x), x, d)


def avg_rsi(close) -> np.ndarray:
    """평균 RSI (BOT_FORMULAS 2-2): RSI 26, ROC 7, MOM 7, normalised over 100 bars, EMA 3."""
    c = np.asarray(close, float)
    rs = (_nz(rsi(c, 26), 50.0) - 50.0) / 50.0
    cs = _nz(zsq(roc(c, 7), 100))
    ms = _nz(zsq(mom(c, 7), 100))
    return ema(50.0 + 50.0 * (rs + cs + ms) / 3.0, 3)


def line_gold(close) -> np.ndarray:
    """보라 · 하늘색 선 (BOT_FORMULAS 2-3): True = cyan (golden, long side). The running sum's start does not matter
    once its EMA has settled."""
    c = np.asarray(close, float)
    score = ((_nz(rsi(c, 26), 50.0) - 50.0) / 50.0 + _nz(zsq(roc(c, 9), 100)) + _nz(zsq(mom(c, 10), 100))) / 3.0
    line = np.cumsum(score)
    sig = ema(line, 9)
    return np.where(np.isfinite(sig), line > sig, False)


# ====================================================================== the decision at one 30m close
@dataclass
class Coin:
    symbol: str
    h1_buf: float
    sl_atr: float
    roe_act: float
    leverage: int
    enabled: bool = True


def bars_frame(rows: list, tf_ms: int, upto_ms: int) -> pd.DataFrame:
    """Binance kline rows -> bars CLOSED by ``upto_ms`` (open + tf <= upto), oldest first, one row per open time."""
    if not rows:
        return pd.DataFrame(columns=["open_ms", "open", "high", "low", "close"])
    df = pd.DataFrame([[int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])] for r in rows],
                      columns=["open_ms", "open", "high", "low", "close"])
    df = df[df.open_ms + tf_ms <= upto_ms].drop_duplicates("open_ms", keep="last").sort_values("open_ms")
    return df.reset_index(drop=True)


def evaluate(coin: Coin, b30: pd.DataFrame, b1h: pd.DataFrame, close_ms: int) -> dict:
    """The design's decision on the 30m bar closing at ``close_ms`` (b30 / b1h: closed bars only). Returns the values
    (for the log and the comparison with TradingView) and ``side`` = 1 / -1 / 0 with ``why`` when 0."""
    out = {"symbol": coin.symbol, "close_ms": int(close_ms), "side": 0, "why": ""}
    if b30.empty or int(b30.open_ms.iloc[-1]) + MIN30 != close_ms:
        out["why"] = "30분봉이 아직 없음"
        return out
    if len(b30) < 300 or len(b1h) < 300:
        out["why"] = "지난 봉이 모자람"
        return out
    c = b30.close.to_numpy(float)
    g = line_gold(c)
    ar = avg_rsi(c)
    at = atr(b30.high.to_numpy(float), b30.low.to_numpy(float), c, 14)
    t_ar = avg_rsi(b1h.close.to_numpy(float))
    h_close = b1h.open_ms.to_numpy(np.int64) + H1
    j = int(np.searchsorted(h_close, close_ms, side="right")) - 1     # the last 1h bar closed by this 30m close
    if j < 0 or int(h_close[j]) != close_ms // H1 * H1:
        out["why"] = "1시간봉이 아직 없음"
        return out
    to_cyan, to_purp = bool(g[-1] and not g[-2]), bool((not g[-1]) and g[-2])
    are, art = float(ar[-1]), (float(t_ar[j]) if np.isfinite(t_ar[j]) else 50.0)
    px, a = float(c[-1]), float(at[-1])
    dist = a * coin.sl_atr
    liq_ok = dist < px * (1.0 / coin.leverage - MMR_PCT / 100.0)
    out.update({"close": px, "gold": bool(g[-1]), "to_cyan": to_cyan, "to_purple": to_purp, "avg_rsi_30m": round(are, 2),
                "avg_rsi_1h": round(art, 2), "trend_close_ms": int(h_close[j]), "atr": a,
                "stop_dist": dist, "stop_pct": round(dist / px * 100, 3), "liq_ok": bool(liq_ok)})
    if not (to_cyan or to_purp):
        out["why"] = "색 변화 없음"
        return out
    if not coin.enabled:
        out["why"] = "이 코인 꺼짐"
        return out
    want = 1 if to_cyan else -1
    ok_e = are > 50 if want > 0 else are < 50
    ok_t = art > 50 - coin.h1_buf if want > 0 else art < 50 + coin.h1_buf
    if not (ok_e and ok_t):
        out["why"] = ("30분 평균 RSI " if not ok_e else "") + ("1시간 평균 RSI " if not ok_t else "") + "조건 안 맞음"
        return out
    if not liq_ok:
        out["why"] = f"손절 폭 {dist / px * 100:.2f}%가 {coin.leverage}배 청산가보다 멂"
        return out
    out["side"] = want
    return out


def ladder_stop(side: int, entry: float, best: float, stop: float, roe_act: float, lev: float,
                lock_roe: float = LOCK_ROE) -> tuple[float, int]:
    """BOT_FORMULAS 3: (new stop, step) after a 30m close; the stop never moves the unfavourable way. step 0 = not yet
    locked; k + 1 = the lock k steps past the first."""
    lock_d = entry * lock_roe / 100.0 / lev
    act_d = entry * roe_act / 100.0 / lev
    step_d = act_d - lock_d
    gain = side * (best - entry)
    if step_d <= 0 or gain < act_d:
        return stop, 0
    k = int(math.floor((gain - act_d) / step_d + 1e-12))
    new = entry + side * (lock_d + k * step_d)
    if (side > 0 and new > stop) or (side < 0 and new < stop):
        return new, k + 1
    return stop, -1                                 # reached, but no better than the stop already there


# ====================================================================== config and state
@dataclass
class Config:
    mode: str                                   # "paper" | "mainnet"
    state: str                                  # the state file (JSON)
    log: str                                    # the decision / trade log (JSON lines)
    coins: list
    risk_pct: float = 0.25
    equity_floor_frac: float = 0.7
    start_equity: Optional[float] = None        # paper: the starting equity; mainnet: read at the first start
    kill_file: str = "/var/lib/paperbot/STOP"     # the shared emergency file (the executors close everything on it)
    own_stop_file: str = "/var/lib/paperbot/exec/mixchop.STOP"   # this bot only: no new entries
    max_notional_usd: float = 2000.0
    taker_fee: float = 0.00042                  # paper only (WOO X Pro's taker fee): charged on both sides
    telegram: bool = True
    binance_base: str = "https://fapi.binance.com"

    @property
    def symbols(self) -> list:
        return [c.symbol for c in self.coins]


def load_config(path: str) -> Config:
    with open(path) as f:
        raw = json.load(f)
    mode = raw.get("mode")
    if mode not in ("paper", "mainnet"):
        raise MixError(f"\"mode\"는 \"paper\" 또는 \"mainnet\"이어야 합니다(지금 {mode!r})")
    coins = []
    for sym, v in (raw.get("coins") or {}).items():
        if not sym.endswith("USDT"):
            raise MixError(f"코인 이름은 BTCUSDT 꼴이어야 합니다: {sym!r}")
        base = dict(DEFAULT_COINS.get(sym, {}))
        base.update({k: v[k] for k in ("h1_buf", "sl_atr", "roe_act", "leverage") if k in v})
        missing = [k for k in ("h1_buf", "sl_atr", "roe_act", "leverage") if k not in base]
        if missing:
            raise MixError(f"{sym}: 설정 {missing}이 없습니다")
        co = Coin(sym, float(base["h1_buf"]), float(base["sl_atr"]), float(base["roe_act"]), int(base["leverage"]),
                  bool(v.get("enabled", True)))
        if not (0 <= co.h1_buf <= 50 and 0.3 <= co.sl_atr <= 10 and LOCK_ROE < co.roe_act <= 1000 and 1 <= co.leverage <= 50):
            raise MixError(f"{sym}: 설정 값이 범위 밖입니다 {asdict(co)}")
        coins.append(co)
    if not coins:
        raise MixError("\"coins\"가 비어 있습니다")
    cfg = Config(mode=mode, state=raw.get("state") or "", log=raw.get("log") or "", coins=coins,
                 risk_pct=float(raw.get("risk_pct", 0.25)), equity_floor_frac=float(raw.get("equity_floor_frac", 0.7)),
                 start_equity=raw.get("start_equity"), kill_file=raw.get("kill_file", "/var/lib/paperbot/STOP"),
                 own_stop_file=raw.get("own_stop_file", "/var/lib/paperbot/exec/mixchop.STOP"),
                 max_notional_usd=float(raw.get("max_notional_usd", 2000.0)),
                 taker_fee=float(raw.get("taker_fee", 0.00042)), telegram=bool(raw.get("telegram", True)),
                 binance_base=raw.get("binance_base", "https://fapi.binance.com"))
    if not cfg.state or not cfg.log:
        raise MixError("\"state\"와 \"log\" 파일 경로가 필요합니다")
    if not (0 < cfg.risk_pct <= 5):
        raise MixError(f"\"risk_pct\"는 0 ~ 5(%) 사이여야 합니다(지금 {cfg.risk_pct})")
    if not (0 <= cfg.equity_floor_frac < 1):
        raise MixError("\"equity_floor_frac\"는 0 이상 1 미만이어야 합니다")
    if cfg.binance_base.rstrip("/") != "https://fapi.binance.com":
        raise MixError("신호 캔들은 바이낸스 USDT 선물(https://fapi.binance.com)에서만 읽습니다")
    return cfg


@dataclass
class Position:
    symbol: str
    side: int
    qty: float
    entry: float
    stop_dist: float
    stop: float
    best: float
    step: int
    opened_ms: int
    signal_close_ms: int
    signal_close: float
    last_bar_ms: int                            # the last 30m close already used for best / the ladder
    stop_id: Optional[str] = None
    equity_before: Optional[float] = None
    leverage: int = 40
    roe_act: float = 150.0

    def roe(self, px: float) -> float:
        return self.side * (px - self.entry) / self.entry * self.leverage * 100.0


def read_state(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def write_state(path: str, st: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def kst(ms: int) -> str:
    return time.strftime("%m/%d %H:%M", time.gmtime((int(ms) + KST_MS) / 1000))


def coin_ko(symbol: str) -> str:
    return symbol.replace("USDT", "")


# ====================================================================== brokers
class PaperBroker:
    """Trades nothing: fills at the signal close, exits on the 30m bars like the indicator (stop price, or the open
    when the bar opens past it), fees ``taker_fee`` on both sides."""
    live = False

    def __init__(self, equity: float, fee: float):
        self.eq = float(equity)
        self.fee = float(fee)
        self.pos: dict = {}                     # symbol -> signed qty

    def equity(self) -> float:
        return self.eq

    def foreign_positions(self, mine: Optional[str]) -> list:
        return []

    def setup(self, coins) -> list:
        return [(True, "모의: 거래소 설정 없음")]

    def spec(self, symbol: str) -> dict:
        return {"qty_step": 0.0, "min_qty": 0.0, "tick": 0.0, "min_notional": 0.0}

    def open(self, symbol: str, side: int, qty: float, ref: float, lev: int) -> tuple[float, float]:
        self.pos[symbol] = side * qty
        self.eq -= qty * ref * self.fee
        return ref, qty

    def place_stop(self, symbol: str, side: int, price: float, qty: float) -> Optional[str]:
        return "paper"

    def move_stop(self, symbol: str, side: int, price: float, qty: float, old_id) -> tuple[str, Optional[str]]:
        return "moved", "paper"

    def is_open(self, symbol: str) -> Optional[bool]:
        return symbol in self.pos

    def stop_ok(self, symbol: str, qty: float) -> bool:
        return True

    def close_market(self, symbol: str, side: int, qty: float) -> None:
        self.pos.pop(symbol, None)

    def paper_exit(self, p: Position, px: float) -> float:
        pnl = p.side * (px - p.entry) * p.qty - p.qty * px * self.fee
        self.eq += pnl
        self.pos.pop(p.symbol, None)
        return pnl


class WooBroker:
    """WOO X Pro, the second account (keys in its own root-only file). Every order and stop goes through
    paperbot/wooxpro.py's client and the shared stop protocol (place -> confirmed resting; move = new one confirmed,
    then the old one cancelled)."""
    live = True

    def __init__(self, client, coins):
        from . import testnet as TN
        self.c = client
        self.TN = TN
        self.coins = {c.symbol: c for c in coins}

    def equity(self) -> float:
        a = self.c.account()
        return float(a["totalMarginBalance"])

    def foreign_positions(self, mine: Optional[str]) -> list:
        """Every open position on the account except the bot's own (symbol, signed qty)."""
        out = []
        for p in self.c.positions():
            amt = float(p.get("positionAmt") or 0)
            if amt != 0 and p.get("symbol") != mine:
                out.append((p.get("symbol"), amt))
        return out

    def setup(self, coins) -> list:
        """One-way mode, then each coin isolated at its leverage (read back). Lines (ok, text)."""
        out = []
        self.c.one_way()
        out.append((True, "포지션 모드: 단방향"))
        for co in coins:
            try:
                self.c.leverage(co.symbol, co.leverage)
                out.append((True, f"{co.symbol}: 격리 {co.leverage}배"))
            except Exception as e:                       # a coin that cannot be set is not traded
                out.append((False, f"{co.symbol}: 레버리지를 못 맞춤 ({e})"))
        return out

    def spec(self, symbol: str) -> dict:
        return self.c.spec(symbol)

    def open(self, symbol: str, side: int, qty: float, ref: float, lev: int) -> tuple[float, float]:
        self.c.leverage(symbol, lev)
        o = self.c.market(symbol, "BUY" if side > 0 else "SELL", qty,
                          client_id=f"mx{uuid.uuid4().hex[:20]}")
        filled = float(o.get("executedQty") or 0)
        px = float(o.get("avgPrice") or 0)
        if filled <= 0 or px <= 0:                       # read the position: the order was accepted
            pos = self.c.position(symbol)
            filled = abs(float(pos.get("positionAmt") or 0))
            px = float(pos.get("entryPrice") or 0) or ref
        return px, filled

    def place_stop(self, symbol: str, side: int, price: float, qty: float) -> Optional[str]:
        sp = self.c.spec(symbol)
        trig = self.TN.round_stop(price, float(sp["tick"]), side)
        o = self.TN.place_stop(self.c, symbol, "SELL" if side > 0 else "BUY", trig, qty,
                               client_id=f"ms{uuid.uuid4().hex[:20]}")
        return str(o.get("algoId") or "")

    def move_stop(self, symbol: str, side: int, price: float, qty: float, old_id) -> tuple[str, Optional[str]]:
        sp = self.c.spec(symbol)
        trig = self.TN.round_stop(price, float(sp["tick"]), side)
        olds = [old_id] if old_id else [o.get("algoId") for o in self.TN.live_stops(self.c, symbol)]
        r = self.TN.move_stop(self.c, symbol, "SELL" if side > 0 else "BUY", trig, qty, olds,
                              client_id=f"ms{uuid.uuid4().hex[:20]}", close_id=f"mc{uuid.uuid4().hex[:20]}")
        if r.get("result") == "moved":
            new = r.get("stop") or {}
            return "moved", str(new.get("algoId") or "")
        return str(r.get("result") or "?"), None

    def is_open(self, symbol: str) -> Optional[bool]:
        amt = float(self.c.position(symbol)["positionAmt"])
        return amt != 0

    def stop_ok(self, symbol: str, qty: float) -> bool:
        amt = float(self.c.position(symbol)["positionAmt"])
        return any(self.TN.covers(o, amt) for o in self.TN.live_stops(self.c, symbol))

    def close_market(self, symbol: str, side: int, qty: float) -> None:
        self.c.market(symbol, "SELL" if side > 0 else "BUY", qty, reduce_only=True,
                      client_id=f"mc{uuid.uuid4().hex[:20]}")

    def cancel_stops(self, symbol: str) -> None:
        self.c.cancel_all_algo(symbol)


# ====================================================================== the bot
class Bot:
    def __init__(self, cfg: Config, broker, fetch: Callable[[str, str, int], list], clock_ms: Callable[[], int],
                 notify: Optional[Callable[[str, str], None]] = None, sleep: Callable[[float], None] = time.sleep):
        self.cfg, self.b, self.fetch, self.now, self.sleep = cfg, broker, fetch, clock_ms, sleep
        self.notify = notify or (lambda level, text: None)
        self.coins = {c.symbol: c for c in cfg.coins}
        st = read_state(cfg.state)
        self.pos: Optional[Position] = Position(**st["position"]) if st.get("position") else None
        self.start_equity = st.get("start_equity") or cfg.start_equity
        self.last_close_ms = int(st.get("last_close_ms") or 0)
        self.halt_reason = ""
        self.stop = False
        self._last_stop_check = 0.0
        self._flat_reads = 0

    # ---------------------------------------------------------------- persistence and log
    def save(self) -> None:
        write_state(self.cfg.state, {"position": asdict(self.pos) if self.pos else None, "start_equity": self.start_equity,
                                     "last_close_ms": self.last_close_ms, "saved_ms": self.now(), "mode": self.cfg.mode})

    def log(self, kind: str, **kv) -> None:
        row = {"ts": self.now(), "kind": kind, **kv}
        with open(self.cfg.log, "a") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=float) + "\n")

    def say(self, level: str, text: str) -> None:
        prefix = f"[{NAME}{' 모의' if not self.b.live else ''}] "
        try:
            self.notify(level, prefix + text)
        except Exception:
            pass

    # ---------------------------------------------------------------- bars
    def bars(self, symbol: str, close_ms: int) -> tuple[pd.DataFrame, pd.DataFrame]:
        b30 = bars_frame(self.fetch(symbol, "30m", BARS), MIN30, close_ms)
        b1h = bars_frame(self.fetch(symbol, "1h", BARS), H1, close_ms)
        return b30, b1h

    # ---------------------------------------------------------------- start
    def start(self) -> None:
        eq = self.b.equity()
        if not self.start_equity:
            self.start_equity = eq
        lines = self.b.setup(self.cfg.coins)
        bad = [t for ok, t in lines if not ok]
        for co in self.cfg.coins:
            if any(co.symbol in t for t in bad):
                co.enabled = False
        if self.pos is not None:
            self.reconcile_open()
        self.save()
        coins = " · ".join(f"{coin_ko(c.symbol)}{'' if c.enabled else '(꺼짐)'}" for c in self.cfg.coins)
        held = f"\n보유 중: {coin_ko(self.pos.symbol)} {'롱' if self.pos.side > 0 else '숏'} 손절 {self.pos.stop:.6g}" \
            if self.pos else ""
        self.say("INFO", f"▶️ 시작 · 잔고 ${eq:,.2f} (시작 잔고 ${self.start_equity:,.2f})\n코인 {coins}\n"
                         f"손절 1번 = 잔고의 {self.cfg.risk_pct}% · 한 번에 1포지션 · 30분봉 마감마다 판단{held}"
                 + ("".join(f"\n⚠ {t}" for t in bad)))
        self.log("start", equity=eq, start_equity=self.start_equity, setup=lines, position=asdict(self.pos) if self.pos else None)

    def reconcile_open(self) -> None:
        p = self.pos
        st = self.b.is_open(p.symbol)
        if st is False and (not self.b.live or self.confirm_flat(p.symbol)):
            self.finish(p, None, "closed_while_down")
            return
        if self.b.live and not self.b.stop_ok(p.symbol, p.qty):
            sid = self.b.place_stop(p.symbol, p.side, p.stop, p.qty)
            p.stop_id = sid
            self.say("WARN", f"⚠ 다시 켜면서 {coin_ko(p.symbol)} 손절이 없어 다시 걸었습니다 ({p.stop:.6g})")
            self.log("stop_replaced", symbol=p.symbol, stop=p.stop)

    # ---------------------------------------------------------------- every 30m close
    def on_close(self, close_ms: int) -> None:
        if self.pos is not None:
            self.manage(close_ms)
        self.halt_reason = self.halts()
        cands = []
        for co in self.cfg.coins:
            for attempt in range(3):
                try:
                    b30, b1h = self.bars(co.symbol, close_ms)
                    ev = evaluate(co, b30, b1h, close_ms)
                except Exception as e:
                    ev = {"symbol": co.symbol, "close_ms": close_ms, "side": 0, "why": f"캔들 읽기 실패: {e}"}
                if not (ev["why"].endswith("아직 없음") or ev["why"].startswith("캔들 읽기 실패")):
                    break
                self.sleep(3.0)
            if ev["why"].endswith("아직 없음") or ev["why"].startswith("캔들 읽기 실패"):
                self.log("bars_missing", **ev)
            if ev.get("to_cyan") or ev.get("to_purple") or ev["side"]:
                self.log("signal", **ev)
            if ev["side"]:
                cands.append((co, ev))
        self.last_close_ms = close_ms
        self.save()
        if not cands:
            return
        if self.pos is not None or self.halt_reason:
            for co, ev in cands:
                why = "보유 중" if self.pos is not None else self.halt_reason
                self.log("skip", symbol=co.symbol, side=ev["side"], why=why)
            return
        co, ev = cands[0]                               # the config's coin order decides between coins
        for other, oev in cands[1:]:
            self.log("skip", symbol=other.symbol, side=oev["side"], why=f"같은 봉에 {coin_ko(co.symbol)} 먼저")
        self.enter(co, ev)

    def halts(self) -> str:
        for f in (self.cfg.kill_file, self.cfg.own_stop_file):
            if f and os.path.exists(f):
                return f"정지 파일({f})"
        try:
            eq = self.b.equity()
        except Exception as e:
            return f"잔고를 못 읽음({e})"
        if self.start_equity and eq < self.start_equity * self.cfg.equity_floor_frac:
            return f"잔고 ${eq:,.2f}가 시작 잔고의 {self.cfg.equity_floor_frac:.0%} 아래"
        try:
            other = self.b.foreign_positions(self.pos.symbol if self.pos else None)
        except Exception as e:
            return f"포지션을 못 읽음({e})"
        if other:
            return "봇이 모르는 포지션: " + ", ".join(f"{s} {q:g}" for s, q in other)
        return ""

    # ---------------------------------------------------------------- entry
    def enter(self, co: Coin, ev: dict) -> None:
        sym, side = co.symbol, ev["side"]
        eq = self.b.equity()
        dist = float(ev["stop_dist"])
        risk = eq * self.cfg.risk_pct / 100.0
        qty = risk / dist
        ref = float(ev["close"])
        if qty * ref > self.cfg.max_notional_usd:
            qty = self.cfg.max_notional_usd / ref
        sp = self.b.spec(sym)
        if sp.get("qty_step"):
            qty = math.floor(qty / float(sp["qty_step"]) + 1e-9) * float(sp["qty_step"])
        need = max(float(sp.get("min_qty") or 0), float(sp.get("min_notional") or 0) / ref)
        if qty <= 0 or qty + 1e-12 < need:
            self.log("skip", symbol=sym, side=side, why="최소 주문보다 작음", qty=qty, need=need, equity=eq)
            self.say("WARN", f"⚠ {coin_ko(sym)} {'롱' if side > 0 else '숏'} 신호를 건너뜀: 크기 {qty:g}가 최소 {need:g}보다 작음 "
                             f"(손절 1번 ${risk:.3f}, 손절 폭 {ev['stop_pct']}%)")
            return
        try:
            fill, filled = self.b.open(sym, side, qty, ref, co.leverage)
        except Exception as e:
            self.log("entry_failed", symbol=sym, side=side, error=str(e))
            self.say("CRITICAL", f"🚨 {coin_ko(sym)} 진입 주문 실패: {e}\n포지션이 생겼는지 거래소에서 확인하세요")
            if self.b.live:
                try:
                    if self.b.is_open(sym):
                        self.protect_unknown(sym, side, ref, dist, co)
                except Exception:
                    pass
            return
        if filled <= 0:
            self.log("entry_none", symbol=sym, side=side)
            return
        stop = fill - side * dist
        p = Position(symbol=sym, side=side, qty=filled, entry=fill, stop_dist=dist, stop=stop, best=fill, step=0,
                     opened_ms=self.now(), signal_close_ms=int(ev["close_ms"]), signal_close=ref,
                     last_bar_ms=int(ev["close_ms"]), equity_before=eq, leverage=co.leverage, roe_act=co.roe_act)
        self.pos = p
        self.save()
        try:
            p.stop_id = self.b.place_stop(sym, side, stop, filled)
        except Exception as e:
            self.log("stop_failed", symbol=sym, error=str(e))
            self.say("CRITICAL", f"🚨 {coin_ko(sym)} 손절을 못 걸어 바로 시장가로 닫습니다: {e}")
            try:
                self.b.close_market(sym, side, filled)
            except Exception as e2:
                self.log("protect_close_failed", symbol=sym, error=str(e2))
            if self.b.is_open(sym) is False and (not self.b.live or self.confirm_flat(sym)):
                self.finish(p, None, "protect")
            else:                                       # still open: keep it; poll() places the stop again
                self._last_stop_check = 0.0
                self.say("CRITICAL", f"🚨 {coin_ko(sym)} 포지션이 아직 열려 있고 손절이 없습니다. 봇이 계속 손절을 다시 걸어 봅니다. "
                                     f"거래소에서 바로 확인하세요")
            return
        self.save()
        self.log("entry", **asdict(p), why=ev)
        lock_px = fill + side * fill * LOCK_ROE / 100 / co.leverage
        act_px = fill + side * fill * co.roe_act / 100 / co.leverage
        self.say("INFO", f"{'🟢' if side > 0 else '🔴'} {coin_ko(sym)} {'롱' if side > 0 else '숏'} 진입 {fill:.6g} ({co.leverage}배, "
                         f"{filled:g}개 ≈ ${filled * fill:,.2f})\n손절 {stop:.6g} (ROE −{dist / fill * co.leverage * 100:.1f}%, "
                         f"잔고의 {self.cfg.risk_pct}%)\n계단: {act_px:.6g}(ROE +{co.roe_act:.0f}%) 가면 손절을 {lock_px:.6g}"
                         f"(ROE +{LOCK_ROE:.0f}%)로\n근거: {'하늘색' if side > 0 else '보라색'}으로 바뀜 · 30분 평균 RSI "
                         f"{ev['avg_rsi_30m']} · 1시간 평균 RSI {ev['avg_rsi_1h']} ({kst(ev['close_ms'])} 봉)")

    def protect_unknown(self, sym: str, side: int, ref: float, dist: float, co: Coin) -> None:
        """An entry whose answer was lost but whose position exists: adopt it with the design's stop."""
        pos_amt = float(self.b.c.position(sym)["positionAmt"])
        qty = abs(pos_amt)
        entry = float(self.b.c.position(sym).get("entryPrice") or ref)
        s = 1 if pos_amt > 0 else -1
        p = Position(symbol=sym, side=s, qty=qty, entry=entry, stop_dist=dist, stop=entry - s * dist, best=entry, step=0,
                     opened_ms=self.now(), signal_close_ms=self.last_close_ms, signal_close=ref,
                     last_bar_ms=self.last_close_ms, leverage=co.leverage, roe_act=co.roe_act)
        self.pos = p
        p.stop_id = self.b.place_stop(sym, s, p.stop, qty)
        self.save()
        self.say("WARN", f"⚠ {coin_ko(sym)} 포지션을 찾아 손절 {p.stop:.6g}을 걸었습니다")

    # ---------------------------------------------------------------- the open position
    def manage(self, close_ms: int) -> None:
        """At a 30m close: is it still open; then best from the closed 30m bars since the last update, and the ladder."""
        p = self.pos
        if not self.b.live:
            self.paper_bars(close_ms)
            return
        try:
            if self.b.is_open(p.symbol) is False:
                if self.confirm_flat(p.symbol):
                    self.finish(p, None, "stop")
                    return
        except Exception as e:
            self.log("read_failed", symbol=p.symbol, error=str(e))
            return
        try:
            b30 = bars_frame(self.fetch(p.symbol, "30m", 50), MIN30, close_ms)
        except Exception as e:
            self.log("bars_failed", symbol=p.symbol, error=str(e))
            return
        new_bars = b30[b30.open_ms + MIN30 > p.last_bar_ms]
        if new_bars.empty:
            return
        if p.side > 0:
            p.best = max(p.best, float(new_bars.high.max()))
        else:
            p.best = min(p.best, float(new_bars.low.min()))
        p.last_bar_ms = int(new_bars.open_ms.iloc[-1]) + MIN30
        new, step = ladder_stop(p.side, p.entry, p.best, p.stop, p.roe_act, p.leverage)
        self.save()
        if step > 0 and new != p.stop:
            try:
                res, sid = self.b.move_stop(p.symbol, p.side, new, p.qty, p.stop_id)
            except Exception as e:
                self.log("move_failed", symbol=p.symbol, to=new, error=str(e))
                self.say("WARN", f"⚠ {coin_ko(p.symbol)} 계단 손절을 {new:.6g}로 못 옮김 (지금 손절 {p.stop:.6g} 그대로): {e}")
                return
            if res == "moved":
                old = p.stop
                p.stop, p.step, p.stop_id = new, step, sid
                self.save()
                self.log("ladder", symbol=p.symbol, old=old, new=new, step=step, best=p.best)
                self.say("INFO", f"🪜 {coin_ko(p.symbol)} 계단 {step}단계: 손절 {old:.6g} → {new:.6g} (ROE {p.roe(new):+.1f}%)")
            else:                                       # "closed" (price already past) / "triggered" (fired at once)
                self.log("ladder_closed", symbol=p.symbol, result=res, to=new)
                if self.b.is_open(p.symbol) is False and self.confirm_flat(p.symbol):
                    self.finish(p, None, "ladder")

    def paper_bars(self, close_ms: int) -> None:
        """Paper: the indicator's own exit on each closed 30m bar since the last one used."""
        p = self.pos
        b30 = bars_frame(self.fetch(p.symbol, "30m", 50), MIN30, close_ms)
        for _, bar in b30[b30.open_ms + MIN30 > p.last_bar_ms].iterrows():
            hit = bar.low <= p.stop if p.side > 0 else bar.high >= p.stop
            if hit:
                px = min(bar.open, p.stop) if p.side > 0 else max(bar.open, p.stop)
                self.finish(p, px, "ladder" if p.step > 0 else "stop")
                return
            p.best = max(p.best, bar.high) if p.side > 0 else min(p.best, bar.low)
            p.last_bar_ms = int(bar.open_ms) + MIN30
            new, step = ladder_stop(p.side, p.entry, p.best, p.stop, p.roe_act, p.leverage)
            if step > 0 and new != p.stop:
                self.log("ladder", symbol=p.symbol, old=p.stop, new=new, step=step, best=p.best)
                self.say("INFO", f"🪜 {coin_ko(p.symbol)} 계단 {step}단계: 손절 {p.stop:.6g} → {new:.6g}")
                p.stop, p.step = new, step
        self.save()

    def confirm_flat(self, symbol: str) -> bool:
        """Two readings a few seconds apart must both say flat (a single 0 is never trusted)."""
        self.sleep(3.0)
        return self.b.is_open(symbol) is False

    def poll(self) -> None:
        """Between closes (live): did the stop fire; is the stop still resting."""
        p = self.pos
        if p is None or not self.b.live:
            return
        try:
            if self.b.is_open(p.symbol) is False and self.confirm_flat(p.symbol):
                self.finish(p, None, "ladder" if p.step > 0 else "stop")
                return
            if time.monotonic() - self._last_stop_check > STOP_CHECK_S:
                self._last_stop_check = time.monotonic()
                if not self.b.stop_ok(p.symbol, p.qty):
                    p.stop_id = self.b.place_stop(p.symbol, p.side, p.stop, p.qty)
                    self.save()
                    self.say("WARN", f"⚠ {coin_ko(p.symbol)} 손절이 보이지 않아 다시 걸었습니다 ({p.stop:.6g})")
        except Exception as e:
            self.log("poll_failed", error=str(e))

    def finish(self, p: Position, px: Optional[float], why: str) -> None:
        """The position is closed: P&L (paper: the exit price; live: the equity change), log, message, clear."""
        if self.b.live:
            try:
                self.b.cancel_stops(p.symbol)
            except Exception as e:
                self.log("cancel_failed", symbol=p.symbol, error=str(e))
            try:
                eq = self.b.equity()
            except Exception:
                eq = None
            pnl = (eq - p.equity_before) if (eq is not None and p.equity_before is not None) else None
        else:
            pnl = self.b.paper_exit(p, px if px is not None else p.stop)
            eq = self.b.equity()
        roe = p.roe(px) if px is not None else (pnl / (p.qty * p.entry / p.leverage) * 100 if pnl is not None and p.qty else None)
        self.log("exit", symbol=p.symbol, side=p.side, why=why, price=px, pnl=pnl, equity=eq, step=p.step, entry=p.entry,
                 stop=p.stop, opened_ms=p.opened_ms)
        mark = "✅" if (pnl or 0) > 0 else "❌"
        self.say("INFO", f"{mark} {coin_ko(p.symbol)} {'롱' if p.side > 0 else '숏'} 청산 · {EXIT_KO.get(why, why)}"
                         + (f" {px:.6g}" if px is not None else "")
                         + (f"\n손익 ${pnl:+,.3f}" if pnl is not None else "") + (f" (ROE {roe:+.1f}%)" if roe is not None else "")
                         + (f"\n잔고 ${eq:,.2f}" if eq is not None else ""))
        self.pos = None
        self.save()

    # ---------------------------------------------------------------- loop
    def run(self) -> None:
        self.start()
        while not self.stop:
            now = self.now()
            nxt = (now // MIN30 + 1) * MIN30
            if self.last_close_ms and nxt - MIN30 > self.last_close_ms and now >= nxt - MIN30 + SETTLE_S * 1000 \
                    and now < nxt - MIN30 + 120_000:
                nxt = nxt - MIN30                       # a close not handled yet (just started): handle it now
            while not self.stop and self.now() < nxt + SETTLE_S * 1000:
                self.poll()
                self.sleep(min(POLL_S, max(0.5, (nxt + SETTLE_S * 1000 - self.now()) / 1000)))
            if self.stop:
                break
            for i in range(READ_TRIES):
                try:
                    self.on_close(nxt)
                    break
                except Exception as e:
                    self.log("close_failed", close_ms=nxt, error=str(e), attempt=i)
                    if i == READ_TRIES - 1:
                        self.say("WARN", f"⚠ {kst(nxt)} 봉 처리를 못 했습니다: {e}")
                    self.sleep(5.0)
        self.save()
        self.say("INFO", "⏹ 멈춤" + (f" · 보유 중 {coin_ko(self.pos.symbol)} (거래소 손절은 그대로 걸려 있음)" if self.pos else ""))


# ====================================================================== wiring
def binance_fetch(base: str):
    from .binance import BinanceREST, urllib_fetch
    rest = BinanceREST(base_url=base, fetch=lambda u, h: urllib_fetch(u, h, timeout=8.0), max_retries=2, backoff=1.0)
    return lambda symbol, tf, n: rest.klines(symbol, tf, limit=n)


def make_notify(cfg: Config):
    if not cfg.telegram or not os.environ.get("TELEGRAM_BOT_TOKEN") or not os.environ.get("TELEGRAM_CHAT_CRITICAL"):
        return lambda level, text: print(f"{level}: {text}", flush=True)
    from .notify import TelegramNotifier
    tg = TelegramNotifier()

    def send(level: str, text: str) -> None:
        print(f"{level}: {text}", flush=True)
        tg.send(level, text)
    return send


def live_broker(cfg: Config):
    """The WOO X Pro client of the second account, through the same key gates as the executor (keys from the
    environment: /etc/paperbot/executor-wooxpro2.env)."""
    from . import wooxpro as WX
    from .mainnet import MODE_MAINNET, check_permissions
    env = dict(os.environ)
    client, keycheck = WX.clients(MODE_MAINNET, env)
    WX.refuse_unless_allowed(MODE_MAINNET, client)
    WX.check_executor_keys(MODE_MAINNET, client, keycheck, env, None)
    perm = keycheck.api_restrictions()
    if perm is None:
        raise MixError("WOO X Pro 키로 선물 계정을 읽지 못했습니다")
    problems = check_permissions(perm)
    if problems:
        raise MixError("키 확인 실패: " + " / ".join(problems))
    client.sync_time()
    return WooBroker(client, cfg.coins)


def cmd_run(args) -> int:
    cfg = load_config(args.config)
    notify = make_notify(cfg)
    if cfg.mode == "mainnet":
        broker = live_broker(cfg)
        from .testnet import hide_process_memory
        hide_process_memory()
    else:
        st = read_state(cfg.state)
        broker = PaperBroker(float(st.get("paper_equity") or cfg.start_equity or 50.0), cfg.taker_fee)
    bot = Bot(cfg, broker, binance_fetch(cfg.binance_base), lambda: int(time.time() * 1000), notify)

    def _stop(*_):
        bot.stop = True
    _signal.signal(_signal.SIGTERM, _stop)
    _signal.signal(_signal.SIGINT, _stop)
    if not broker.live:                                  # paper equity survives restarts
        orig = bot.save

        def save_with_equity():
            orig()
            st = read_state(cfg.state)
            st["paper_equity"] = broker.equity()
            write_state(cfg.state, st)
        bot.save = save_with_equity
    bot.run()
    return 0


def cmd_signals(args) -> int:
    """The last colour changes of each coin with their values (Binance bars), to put next to TradingView."""
    cfg = load_config(args.config)
    fetch = binance_fetch(cfg.binance_base)
    now = int(time.time() * 1000)
    last_close = now // MIN30 * MIN30
    for co in cfg.coins:
        b30 = bars_frame(fetch(co.symbol, "30m", BARS), MIN30, last_close)
        b1h = bars_frame(fetch(co.symbol, "1h", BARS), H1, last_close)
        rows = []
        g = line_gold(b30.close.to_numpy(float))
        for i in range(len(b30) - 1, max(len(b30) - 400, 300), -1):
            if g[i] != g[i - 1]:
                ce = int(b30.open_ms.iloc[i]) + MIN30
                ev = evaluate(co, b30.iloc[:i + 1].reset_index(drop=True), b1h[b1h.open_ms + H1 <= ce].reset_index(drop=True), ce)
                rows.append(ev)
                if len(rows) >= args.n:
                    break
        print(f"== {co.symbol} (여유 {co.h1_buf} · 손절 ATR × {co.sl_atr} · ROE {co.roe_act:.0f} → 10 · {co.leverage}배"
              f"{'' if co.enabled else ' · 꺼짐'})")
        for ev in reversed(rows):
            what = "하늘(롱)" if ev.get("to_cyan") else "보라(숏)"
            res = ("롱 진입" if ev["side"] > 0 else "숏 진입") if ev["side"] else f"X ({ev['why']})"
            print(f"  {kst(ev['close_ms'])} KST 마감  {what}  종가 {ev.get('close', 0):.6g}  30분 평균RSI {ev.get('avg_rsi_30m')}"
                  f"  1시간 평균RSI {ev.get('avg_rsi_1h')}  손절폭 {ev.get('stop_pct')}%  → {res}")
    return 0


def cmd_check(args) -> int:
    """Reads only: WOO X Pro contract specs of the coins (public), and with keys the account, the position mode, the
    positions, and what a stop-out would size to now."""
    cfg = load_config(args.config)
    from . import wooxpro as WX
    pub = WX.public_client()
    fetch = binance_fetch(cfg.binance_base)
    eq = None
    if cfg.mode == "mainnet":
        b = live_broker(cfg)
        eq = b.equity()
        print(f"잔고(WOO X Pro 2): ${eq:,.2f} · 포지션 모드 {b.c.position_mode()}")
        for s, q in b.foreign_positions(None):
            print(f"  열린 포지션: {s} {q:g}")
    eq = eq or float(cfg.start_equity or 50.0)
    now = int(time.time() * 1000)
    for co in cfg.coins:
        try:
            sp = pub.spec(co.symbol)
        except Exception as e:
            print(f"✘ {co.symbol}: WOO X Pro 계약을 못 읽음 ({e})")
            continue
        b30 = bars_frame(fetch(co.symbol, "30m", 100), MIN30, now // MIN30 * MIN30)
        c = b30.close.to_numpy(float)
        a = float(atr(b30.high.to_numpy(float), b30.low.to_numpy(float), c, 14)[-1])
        dist = a * co.sl_atr
        qty = eq * cfg.risk_pct / 100 / dist
        step = float(sp["qty_step"])
        qty_f = math.floor(qty / step + 1e-9) * step
        ok = qty_f >= float(sp["min_qty"]) and qty_f * c[-1] >= float(sp.get("min_notional") or 0)
        print(f"{'✔' if ok else '✘'} {co.symbol}: 상태 {sp.get('status')}, 최대 {sp.get('max_leverage')}배, 1계약 {sp['contract_size']}, "
              f"최소 {sp['min_qty']:g}개 · 지금 손절 폭 {dist / c[-1] * 100:.2f}% → 크기 {qty_f:g}개 ≈ ${qty_f * c[-1]:,.2f} "
              f"(증거금 ${qty_f * c[-1] / co.leverage:,.2f}){'' if ok else ' → 최소 주문보다 작아 건너뜀'}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m paperbot.mixchop", description=NAME)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "check", "signals"):
        p = sub.add_parser(name)
        p.add_argument("--config", required=True)
        if name == "signals":
            p.add_argument("-n", type=int, default=6)
    args = ap.parse_args(argv)
    try:
        return {"run": cmd_run, "check": cmd_check, "signals": cmd_signals}[args.cmd](args)
    except MixError as e:
        print(f"멈춤: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

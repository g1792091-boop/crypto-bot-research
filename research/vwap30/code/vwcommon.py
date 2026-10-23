"""Shared parts of the VWAP-fail study (research/vwap30/PREREG.md): the 1m data (research/newlive's grid: fg1m + the
October daily files), the strategy's bars and signals on 15m / 30m / 1h / 4h, the entry-time features and the 1m paths
after each entry. Heavy outputs go to the session scratchpad (OUT), never into the repository.

Run with python3 -I (the data files are downloaded data: read as arrays only)."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
for _p in (REPO, os.path.join(REPO, "research", "newlive", "code"), os.path.join(REPO, "research", "trendbot", "fiveyear", "code")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
sys.path.append("/root/.local/lib/python3.11/site-packages")
import json, time
import numpy as np
import pandas as pd
import nlcommon as NL                                    # load_grid, DATA_END, COINS, T0, MIN (the newlive data form)
from paperbot.strategy_view_defs.DS_F6_VWAP_FAIL import view_DS_F6_VWAP_FAIL

COINS = list(NL.COINS)                                   # BTC ETH SOL DOGE LTC BCH (the priority order of ties)
T0, MIN, HOUR, DAY = NL.T0, NL.MIN, 3_600_000, 86_400_000
DATA_END = NL.DATA_END
TF_MIN = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
OUT = os.path.join(NL.FY.SCR, "vwap30_out")
os.makedirs(OUT, exist_ok=True)
JUDGE_DIR = NL.JUDGE
COST_RT = 2 * (0.0005 + 0.0002)                          # taker 0.05 % + slippage 0.02 % each side
HOLD_BARS = 96                                           # PREREG: the holding cap
KST = 9 * HOUR


def ms(s):
    return int(pd.Timestamp(s, tz="UTC").value // 10**6)


SEL = (ms("2020-03-01"), ms("2025-01-01"))
CONF = (ms("2025-01-01"), ms("2026-10-01"))
LIVE = (ms("2026-10-01"), DATA_END)
PERIODS = {"select": SEL, "confirm": CONF, "live": LIVE}

_GRID = {}


def grid(coin):
    """The 1m grid of a coin (cached per process): o h l c v fund (NaN before the coin's first bar)."""
    if coin not in _GRID:
        g = NL.load_grid(coin)
        _GRID[coin] = {k: g[k] for k in ("o", "h", "l", "c", "v", "fund")} | {"first": g["first"], "n": g["n"]}
    return _GRID[coin]


def bars(coin, tf):
    """Bars of tf on the UTC grid from T0: DataFrame ts (open, ms), open, high, low, close, volume; only whole bars after
    the coin's first minute."""
    g = grid(coin)
    k = TF_MIN[tf]
    n = g["n"] // k * k
    o = g["o"][:n:k]
    c = g["c"][k - 1:n:k]
    h = np.nanmax(g["h"][:n].reshape(-1, k), axis=1)
    lo = np.nanmin(g["l"][:n].reshape(-1, k), axis=1)
    v = np.nansum(g["v"][:n].reshape(-1, k), axis=1)
    ts = T0 + np.arange(n // k, dtype=np.int64) * k * MIN
    first_bar = -(-g["first"] // k)                     # the first whole bar
    sl = slice(first_bar, None)
    df = pd.DataFrame({"ts": ts[sl], "open": o[sl], "high": h[sl], "low": lo[sl], "close": c[sl], "volume": v[sl]})
    return df.reset_index(drop=True)


def ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()


def wilder(x, n):
    return pd.Series(x).ewm(alpha=1 / n, adjust=False).mean().to_numpy()


def atr_adx(df, n=14):
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    atr = wilder(tr, n)
    up, dn = h - np.r_[h[0], h[:-1]], np.r_[l[0], l[:-1]] - l
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    with np.errstate(all="ignore"):
        pdi = 100 * wilder(pdm, n) / atr
        mdi = 100 * wilder(mdm, n) / atr
        dx = 100 * np.abs(pdi - mdi) / (pdi + mdi)
    return atr, wilder(np.nan_to_num(dx), n)


def signals(coin, tf, df=None):
    """The strategy's signals on the coin's tf bars: DataFrame i (bar index), side, bar_close (ms)."""
    df = bars(coin, tf) if df is None else df
    v = view_DS_F6_VWAP_FAIL(df.assign(ts=pd.to_datetime(df.ts, unit="ms", utc=True)), tf)   # the view reads datetimes
    lo = np.logical_and.reduce([np.asarray(x, bool) for _, x in v["long"]])
    sh = np.logical_and.reduce([np.asarray(x, bool) for _, x in v["short"]])
    i = np.r_[np.flatnonzero(lo), np.flatnonzero(sh)]
    side = np.r_[np.ones(lo.sum(), int), -np.ones(sh.sum(), int)]
    o = np.argsort(i, kind="stable")
    i, side = i[o], side[o]
    return pd.DataFrame({"i": i, "side": side, "bar_close": df.ts.to_numpy()[i] + TF_MIN[tf] * MIN})

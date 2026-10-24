"""Shared data layer of the role-combination study (analysis/review1024/roles/data): paths, the extended 1m grid,
bars on the UTC grid, the period bounds.

The 1m grid = research/newlive's grid (research/vwap30/code/vwcommon.grid: Binance USDT-M 1m klines 2020-01-01 ..
2026-10-23 00:00 UTC, funding from the published files, October funding 0 because no monthly file exists yet)
EXTENDED with the rule bot's own 1m bars (export current/live_bars.csv, Binance USDT-M, 2026-10-23 00:00 .. 10-24
14:11 UTC; checked equal to the grid on the 24,805 overlapping minutes per coin: open/high/low identical, two minutes
differ in close/volume by < 4e-6 relative). Funding in the extension = 0 (as the grid's October).

Run every script of this folder from this folder without -I (pandas), e.g. ``python3 build_grid.py``. Exports are read
as data only (CSV / sqlite read-only); nothing from them is executed."""
import os
import sys
import json
import time
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
assert os.path.isfile(os.path.join(REPO, "paperbot", "trendjudge.py")), REPO
for _p in (os.path.join(REPO, "research", "friendroc", "code"), os.path.join(REPO, "research", "fullgrid"),
           os.path.join(REPO, "research", "vwap30", "code"), REPO):
    if _p not in sys.path:
        sys.path.insert(0, _p)
warnings.filterwarnings("ignore")
os.environ.setdefault("FULLGRID_MEMO_MB", "300")

import numpy as np
import pandas as pd

SCR = "/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/review1024_roles"
OUT = os.path.join(SCR, "data")                 # big outputs (never in the repository)
XD = os.path.join(SCR, "data_x")                 # export extracts (untrusted data, read only)
RULE = os.path.join(XD, "rule")
LIVE_BARS = os.path.join(RULE, "current__live_bars.csv")
MAP = os.path.join(HERE, "..", "map")
os.makedirs(OUT, exist_ok=True)

COINS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")
TFS = ("15m", "30m", "1h", "4h")
HTFS = ("1h", "4h", "1d")
TF_MIN = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}
MIN, HOUR, DAY = 60_000, 3_600_000, 86_400_000
KST = 9 * HOUR


def ms(s):
    return int(pd.Timestamp(s, tz="UTC").value // 10**6)


T0 = ms("2020-01-01")
GRID_END = 1792713600000                         # research grid end (exclusive): 2026-10-23 00:00 UTC
FIVE = (ms("2020-03-01"), GRID_END)              # 5-year table: bar close in [2020-03-01, 2026-10-23 00:00) UTC
FWD = (ms("2026-10-05 15:00"), ms("2026-10-24 15:00"))   # forward: 2026-10-06 00:00 .. 10-25 00:00 KST (bar close)
COST = 2 * (0.00042 + 0.0002)                    # WOO X Pro taker 0.042 % + slippage 0.02 %, each side (round trip)
PAYBACK = 2 * 0.9 * 0.00042                      # TetherMax: 90 % of the taker fee back, per round trip (NOT in COST)
FL, STEP, GAP = 0.10, 0.05, 0.02                 # the owners' ladder: +12 % net ROE locks +10 %, then every 5 %
# outcome variants of the grid: name -> (kind, leverage, net-ROE stop or ATR multiple)
VARIANTS = {
    "w35": ("walk3", 35.0, -0.50),               # owners' live exits: 35x, net ROE -50 % stop, the ladder
    "w30": ("walk3", 30.0, -0.50),
    "w35s20": ("walk3", 35.0, -0.20),
    "a2": ("atr", 30.0, 2.0),                    # house-like: 2 x ATR14 of the signal bar (per timeframe), 30x, ladder,
}                                                # no net-ROE cap (floor at -100 % net = the margin), no leverage downgrade
WHY = ("stop", "lock", "time", "open")           # exit reasons of the walks (3 = still open at the data end)
BLOCK = ("", "weekend", "macro", "us_open")      # frcore.blocked codes


def kst(t_ms):
    return pd.to_datetime(np.asarray(t_ms, np.int64) + KST, unit="ms")


# ====================================================================== the extended 1m grid
_G = {}


def _ext_arrays(coin):
    """The extension minutes GRID_END .. EXT_END of a coin from live_bars (cached npz in OUT/ext)."""
    p = os.path.join(OUT, "ext", f"{coin}.npz")
    if not os.path.exists(p):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        lb = pd.read_csv(LIVE_BARS, usecols=["ts", "symbol", "open", "high", "low", "close", "volume"])
        lb = lb[(lb.symbol == coin) & (lb.ts >= GRID_END)].sort_values("ts")
        assert len(lb) and lb.ts.iloc[0] == GRID_END, (coin, lb.ts.head(1).tolist())
        assert (np.diff(lb.ts.to_numpy()) == MIN).all(), f"{coin}: gap in live_bars after the grid end"
        np.savez(p, ts=lb.ts.to_numpy(np.int64), o=lb.open.to_numpy(float), h=lb.high.to_numpy(float),
                 l=lb.low.to_numpy(float), c=lb.close.to_numpy(float), v=lb.volume.to_numpy(float))
    z = np.load(p)
    return {k: z[k] for k in z.files}


def ext_end():
    """Exclusive end (ms) of the extended grid: the common last live_bars minute + 1 minute."""
    return min(int(_ext_arrays(c)["ts"][-1]) for c in COINS) + MIN


def grid(coin):
    """1m arrays o h l c v fund (float64) on the minute grid T0 .. ext_end(), first (first valid minute), n,
    n_grid (minutes of the research grid; the rest is the live_bars extension). Cached per process."""
    if coin not in _G:
        import vwcommon as VW
        assert VW.DATA_END == GRID_END and VW.T0 == T0, (VW.DATA_END, VW.T0)
        g = VW.grid(coin)
        x = _ext_arrays(coin)
        m = (ext_end() - GRID_END) // MIN
        out = {}
        for k in ("o", "h", "l", "c", "v"):
            out[k] = np.ascontiguousarray(np.r_[g[k], x[k][:m]], dtype=np.float64)
        out["fund"] = np.r_[g["fund"], np.zeros(m)]
        out["first"], out["n"], out["n_grid"] = int(g["first"]), len(out["c"]), int(g["n"])
        VW._GRID.pop(coin, None)
        _G[coin] = out
    return _G[coin]


def drop(coin):
    _G.pop(coin, None)


def bars(coin, tf):
    """Whole bars of tf on the UTC grid from T0 (as vwcommon.bars) over the extended grid: DataFrame ts (open, ms),
    open, high, low, close, volume. Only whole bars after the coin's first minute."""
    g = grid(coin)
    k = TF_MIN[tf]
    n = g["n"] // k * k
    o = g["o"][:n:k]
    c = g["c"][k - 1:n:k]
    h = np.nanmax(g["h"][:n].reshape(-1, k), axis=1)
    lo = np.nanmin(g["l"][:n].reshape(-1, k), axis=1)
    v = np.nansum(g["v"][:n].reshape(-1, k), axis=1)
    ts = T0 + np.arange(n // k, dtype=np.int64) * k * MIN
    first_bar = -(-g["first"] // k)
    sl = slice(first_bar, None)
    return pd.DataFrame({"ts": ts[sl], "open": o[sl], "high": h[sl], "low": lo[sl], "close": c[sl],
                         "volume": v[sl]}).reset_index(drop=True)


def as_chart(df, tf):
    """The bar frame as the strategy code wants it (ts as UTC datetimes, attrs tf)."""
    d = df.copy()
    d["ts"] = pd.to_datetime(d["ts"].to_numpy(np.int64), unit="ms", utc=True)
    d.attrs["tf"] = tf
    return d


def close_ms(df, tf):
    return df["ts"].to_numpy(np.int64) + TF_MIN[tf] * MIN


def last_closed(htf_close, t):
    """Index of the last higher bar with close <= t (-1 = none): no look-ahead (the bar closed at or before t)."""
    return np.searchsorted(htf_close, np.asarray(t, np.int64), side="right") - 1


# ====================================================================== the strategy code
_LIB = {}


def libs():
    """The locked indicator / strategy modules (as analysis/review1024/roles/map/measure_roles.py loads them)."""
    if not _LIB:
        import importlib.util
        from paperbot import sweepsig
        L = sweepsig.lib()
        spec = importlib.util.spec_from_file_location("fullgrid_run_rd", os.path.join(REPO, "research", "fullgrid", "run.py"))
        run = importlib.util.module_from_spec(spec)
        sys.modules["fullgrid_run_rd"] = run
        spec.loader.exec_module(run)
        sys.path.insert(0, os.path.join(REPO, "research", "search"))
        spec2 = importlib.util.spec_from_file_location("research_library_lib_rd",
                                                       os.path.join(REPO, "research", "library", "lib.py"))
        lib = importlib.util.module_from_spec(spec2)
        sys.modules["research_library_lib_rd"] = lib
        spec2.loader.exec_module(lib)
        from paperbot import trendjudge as TJ
        _LIB.update(fg=L.fg, pi=L.pi, run=run, lib=lib, TJ=TJ, L=L)
    return _LIB


def roles():
    return json.load(open(os.path.join(MAP, "roles.json")))


def save_npz(path, **arrs):
    tmp = path + ".tmp.npz"
    np.savez_compressed(tmp, **arrs)
    os.replace(tmp, path)


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)

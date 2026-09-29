"""Shared helpers for TASK A (constraint math).  IS bars only (< 2024-07-01)."""
import os
import numpy as np
import pandas as pd

IS_DIR = "/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/sweep/data/is"
OUT = "/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/sizing/math/out"
COINS = ["btcusd", "ethusd", "solusd", "xrpusd", "dogeusd", "ltcusd", "bchusd"]
TFS = ["5m", "15m", "30m", "1h", "4h", "1d"]
TF_MIN = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}
LEVS = [5, 10, 20, 25, 30, 40, 50]
MARGINS = [0.20, 0.25, 0.30, 0.40]
IS_END = pd.Timestamp("2024-07-01T00:00:00Z")

# Binance USDT-M model (as specified by the task)
MMR = 0.005          # maintenance margin rate, fraction of notional
TAKER = 0.0005       # per side
MAKER = 0.0002       # per side
SLIP = 0.0002        # per market fill
FUND_8H = 0.0001     # funding per 8h, always charged as a cost
C_MKT = TAKER + SLIP  # 0.07% per market fill
RT = 2 * C_MKT        # 0.14% realistic round trip
TP_ROE = 0.10         # user's take-profit: +10% ROE (gross, as Binance displays ROE)


def d_liq(L):
    """Adverse price move that triggers isolated-margin liquidation: ~1/L - MMR."""
    return 1.0 / L - MMR


def tp_dist(L):
    return TP_ROE / L


def load(sym, tf):
    p = os.path.join(IS_DIR, f"{sym}-{tf}.csv")
    df = pd.read_csv(p)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    assert df["ts"].max() < IS_END, (sym, tf)
    return df


def daily_offset_from_1h(sym, off_h):
    """Daily bars anchored at off_h:00 UTC, built from IS 1h bars; only full 24-bar bins kept."""
    h = load(sym, "1h")
    key = (h["ts"] - pd.Timedelta(hours=off_h)).dt.floor("1D") + pd.Timedelta(hours=off_h)
    g = h.groupby(key)
    d = pd.DataFrame({
        "open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
        "close": g["close"].last(), "volume": g["volume"].sum(), "n": g.size()})
    d = d[d["n"] == 24].drop(columns="n")
    d.index.name = "ts"
    d = d.reset_index()
    # keep only bins that end at or before IS_END
    d = d[d["ts"] + pd.Timedelta(days=1) <= IS_END].reset_index(drop=True)
    return d


def atr_wilder(df, n=14):
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    pc = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
    tr[0] = h[0] - l[0]
    atr = np.empty_like(tr)
    atr[:n - 1] = np.nan
    atr[n - 1] = tr[:n].mean()
    a = 1.0 / n
    for i in range(n, len(tr)):
        atr[i] = atr[i - 1] + a * (tr[i] - atr[i - 1])
    return atr / c


def build_sparse(high, low, K):
    n = len(high)
    mx = np.empty((K + 1, n))
    mn = np.empty((K + 1, n))
    mx[0] = high
    mn[0] = low
    for k in range(1, K + 1):
        s = 1 << (k - 1)
        mx[k] = mx[k - 1]
        mn[k] = mn[k - 1]
        if s < n:
            mx[k, :n - s] = np.maximum(mx[k - 1, :n - s], mx[k - 1, s:])
            mn[k, :n - s] = np.minimum(mn[k - 1, :n - s], mn[k - 1, s:])
    return mx, mn


def first_hit(mx, mn, e, limit, up, dn):
    """Smallest j in [e, limit) with high[j] >= up or low[j] <= dn; returns limit if none.
    Binary lifting over a sparse table: exact, vectorised over entries."""
    K = mx.shape[0] - 1
    n = mx.shape[1]
    pos = e.copy()
    for k in range(K, -1, -1):
        cand = pos + (1 << k)
        idx = np.minimum(pos, n - 1)
        ok = (cand <= limit) & (mx[k, idx] < up) & (mn[k, idx] > dn)
        pos = np.where(ok, cand, pos)
    return pos

"""Broad strategy search (research/search/PREREG_SEARCH.md): 13 entries x 3 timeframes x 5 exits.

    python3 research/search/search.py selftest
    SWEEP_DATA=<rebuilt sweep data> python3 research/search/search.py run <scratch_dir>

Uses the backtest session's locked engine (next-bar-open entry, ATR stop/target, stop first when
both are touched in one bar, 0.14% round trip, funding 0.01%/8h) and, for V3.9 / V4.5 / DOGE, its
locked signal code. Everything else is defined here.
"""

from __future__ import annotations

import json
import os
import sys
import time
import warnings

import numpy as np
import pandas as pd
from scipy.stats import norm

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
warnings.filterwarnings("ignore")

TFS = ("15m", "1h", "4h")
HTF = {"15m": "1h", "1h": "4h", "4h": "1d"}
MAX_HOLD = 48
SPLITS_IS, SPLITS_CONF = ("is",), ("oos", "final")
HALF = pd.Timestamp("2023-01-01", tz="UTC")
ENTRIES = ["E1_CONNORS", "E2_MTF_PULLBACK", "E3_V39_NOSPIKE", "E4_V45_NOWITH", "E5_DOGE_TREND",
           "E6_OBV_BREAK", "E7_BB_RANGE", "E8_SQUEEZE", "E9_EMA_CROSS", "E10_RSI_DIP",
           "E11_BIG_CONT", "E12_BIG_FADE", "E13_MOM28_PULL"]
EXITS = [("X1_SL1_TP2", "FIXED", 1.0, 2.0, 0.0), ("X2_SL15_TP3", "FIXED", 1.5, 3.0, 0.0),
         ("X3_SL1_TP3", "FIXED", 1.0, 3.0, 0.0), ("X4_SL2_TP1", "FIXED", 2.0, 1.0, 0.0),
         ("X5_TRAIL2", "TRAIL", 2.0, 0.0, 2.0)]
# Owners' base tier: 20% margin x 20x = 4x account exposure; isolated margin loss capped at 20%.
OWN_EXPO, OWN_MARGIN = 4.0, 0.20


def lib():
    from paperbot import sweepsig
    return sweepsig.lib()


# ------------------------------------------------------------------ helpers
def htf_series(L, df: pd.DataFrame, htf: str, fn) -> np.ndarray:
    """fn(htf_frame) -> array; value of the last HTF bar closed at or before each chart bar's close."""
    dh = L.resample_ohlcv(df, htf)
    vals = np.asarray(fn(dh), dtype=float)
    hclose = L.htf_close_ns(dh["ts"], htf)
    cclose = L._utc_ns(df["ts"]) + np.timedelta64(L.tf_minutes(df.attrs["tf"]), "m")
    j = np.searchsorted(hclose, cclose, side="right") - 1
    return np.where(j >= 0, vals[np.clip(j, 0, len(vals) - 1)], np.nan)


def entries(L, fg, pi, df: pd.DataFrame, tf: str, locked: dict) -> dict[str, np.ndarray]:
    """{entry: int8 array} +1 long / -1 short signal on the bar's close."""
    o, h, lo, c, v = (df[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
    atr = fg.atr(df, 14).to_numpy(float)
    n = len(c)
    out = {}

    def put(name, long, short):
        long = np.nan_to_num(np.asarray(long, float)) != 0
        short = (np.nan_to_num(np.asarray(short, float)) != 0) & ~long
        out[name] = long.astype(np.int8) - short.astype(np.int8)

    with np.errstate(invalid="ignore", divide="ignore"):
        sma200 = pi.pine_sma(c, 200)
        r2 = pi.pine_rsi(c, 2)
        put("E1_CONNORS", (c > sma200) & (r2 < 10), (c < sma200) & (r2 > 90))

        def st_dir(dh):
            _l, d = pi.exchange_supertrend(dh["high"].to_numpy(float), dh["low"].to_numpy(float),
                                           dh["close"].to_numpy(float), 14, 6.0)
            return d
        hdir = htf_series(L, df, HTF[tf], st_dir)
        k, d = pi.stoch_kd(c, h, lo, 14, 3, 3)
        put("E2_MTF_PULLBACK", (hdir == 1) & pi.crossover(k, d) & (k <= 30),
            (hdir == -1) & pi.crossunder(k, d) & (k >= 70))

        body = np.abs(c - o)
        bigbody4 = pd.Series(body).rolling(4).max().to_numpy() / atr
        v39 = locked["V39_ALL"]
        put("E3_V39_NOSPIKE", (v39 > 0) & (bigbody4 < 1.2), (v39 < 0) & (bigbody4 < 1.2))

        c100 = c - np.r_[np.full(100, np.nan), c[:-100]]
        v45 = locked["V45_AMB"]
        put("E4_V45_NOWITH", (v45 > 0) & ~(c100 / atr >= 3), (v45 < 0) & ~(-c100 / atr >= 3))

        dsma50 = htf_series(L, df, "1d", lambda dh: pi.pine_sma(dh["close"].to_numpy(float), 50))
        dclose = htf_series(L, df, "1d", lambda dh: dh["close"].to_numpy(float))
        put("E5_DOGE_TREND", (locked["DOGE_L"] > 0) & (dclose > dsma50), (locked["DOGE_S"] < 0) & (dclose < dsma50))

        ob = pi.obv(c, v)
        obma = pi.pine_sma(ob, 30)
        hh20, ll20 = pi.shift1(pi.pine_highest(h, 20)), pi.shift1(pi.pine_lowest(lo, 20))
        put("E6_OBV_BREAK", (c > hh20) & (ob > obma), (c < ll20) & (ob < obma))

        mid = pi.pine_sma(c, 20)
        sd = pd.Series(c).rolling(20).std(ddof=0).to_numpy()
        adx = pi.adx(h, lo, c, 14, 14)
        put("E7_BB_RANGE", (c < mid - 2 * sd) & (adx < 20), (c > mid + 2 * sd) & (adx < 20))

        e20 = pi.pine_ema(c, 20)
        sq = ((mid + 2 * sd) < (e20 + 1.5 * atr)) & ((mid - 2 * sd) > (e20 - 1.5 * atr))
        sq6 = pd.Series(sq.astype(float)).shift(1).rolling(6).min().to_numpy() == 1
        put("E8_SQUEEZE", sq6 & (c > mid + 2 * sd), sq6 & (c < mid - 2 * sd))

        e9, e21, e200 = pi.pine_ema(c, 9), pi.pine_ema(c, 21), pi.pine_ema(c, 200)
        put("E9_EMA_CROSS", pi.crossover(e9, e21) & (c > e200), pi.crossunder(e9, e21) & (c < e200))

        r14 = pi.pine_rsi(c, 14)
        put("E10_RSI_DIP", pi.crossunder(r14, np.full(n, 30.0)), pi.crossover(r14, np.full(n, 70.0)))

        sb = (c - o) / atr
        put("E11_BIG_CONT", sb >= 2, sb <= -2)
        put("E12_BIG_FADE", sb <= -2, sb >= 2)

        ret28 = htf_series(L, df, "1d", lambda dh: (dh["close"] / dh["close"].shift(28) - 1).to_numpy(float))
        put("E13_MOM28_PULL", (ret28 > 0) & (r2 < 10), (ret28 < 0) & (r2 > 90))
    return out


# ------------------------------------------------------------------ backtest
def run_split(L, fg, pi, tf: str, split: str, panel: dict | None = None) -> pd.DataFrame:
    panel = panel if panel is not None else L.load_panel(tf, split)
    for df in panel.values():
        df.attrs["tf"] = tf
    locked = L.compute_signals(panel, tf, ["V39_ALL", "V45_AMB", "DOGE_L", "DOGE_S"], strict=True)
    exits = [(name, L.ExitCfg(name=name, mode=mode, sl_atr=sl, tp_atr=tp if tp else 1e4, trail_atr=tr), MAX_HOLD)
             for name, mode, sl, tp, tr in EXITS]
    parts = []
    for coin, df in panel.items():
        lo_, hi_ = L.signal_window(df, tf, split, MAX_HOLD)
        if hi_ <= lo_:
            continue
        atr = fg.atr(df, 14).to_numpy(float)
        sig = entries(L, fg, pi, df, tf, {k: locked[k][coin] for k in locked})
        ts = pd.to_datetime(df["ts"], utc=True).to_numpy()
        for ename, arr in sig.items():
            for xname, cfg, mh in exits:
                t = L.run_backtest(df, atr, arr > 0, arr < 0, cfg, L._cost(tf, mh), lo_, hi_)
                if len(t):
                    t = t.assign(symbol=coin, entry=ename, exit=xname, tf=tf, split=split,
                                 entry_ts=ts[t["entry_idx"].to_numpy(int)], exit_ts=ts[t["exit_idx"].to_numpy(int)])
                    parts.append(t)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


# ------------------------------------------------------------------ statistics
def mean_test(y: np.ndarray, day: np.ndarray) -> tuple[float, float]:
    """One-sided p for mean > 0, standard error clustered by entry day."""
    n = len(y)
    m = y.mean()
    g = pd.Series(y - m).groupby(day).sum().to_numpy()
    se = np.sqrt((g ** 2).sum()) / n
    return float(m), float(norm.sf(m / se)) if se > 0 else 1.0


def bh(p: np.ndarray, q: float) -> np.ndarray:
    n = len(p)
    order = np.argsort(p)
    ok = p[order] <= q * np.arange(1, n + 1) / n
    k = np.max(np.flatnonzero(ok)) + 1 if ok.any() else 0
    out = np.zeros(n, bool)
    out[order[:k]] = True
    return out


def owners_book(t: pd.DataFrame) -> dict:
    """One position at a time across coins (owners' rule), base tier 4x exposure, isolated loss
    capped at the 20% margin. Returns final multiple and max drawdown of the account."""
    t = t.sort_values(["entry_ts", "symbol"])
    eq, peak, mdd, last_exit, k = 1.0, 1.0, 0.0, None, 0
    for et, xt, net in zip(t["entry_ts"].to_numpy(), t["exit_ts"].to_numpy(), t["net"].to_numpy()):
        if last_exit is not None and et < last_exit:
            continue
        eq *= 1 + max(OWN_EXPO * net, -OWN_MARGIN)
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
        last_exit, k = xt, k + 1
    return {"own_trades": k, "own_final_x": eq, "own_mdd_pct": 100 * mdd}


def coin_mdd(t: pd.DataFrame) -> float:
    out = []
    for _c, g in t.sort_values("entry_ts").groupby("symbol"):
        eq = np.cumprod(1 + g["net"].to_numpy())
        out.append((eq / np.maximum.accumulate(eq) - 1).min())
    return 100 * float(np.median(out)) if out else np.nan


def describe(t: pd.DataFrame, pre: str) -> dict:
    y = t["net"].to_numpy()
    w, lsum = y[y > 0], y[y <= 0]
    per = t.groupby("symbol")["net"].agg(["mean", "size"])
    per = per[per["size"] >= 10]
    d = {f"{pre}n": len(t), f"{pre}win_pct": 100 * (y > 0).mean() if len(y) else np.nan,
         f"{pre}avg_win_pct": 100 * w.mean() if len(w) else np.nan,
         f"{pre}avg_loss_pct": 100 * lsum.mean() if len(lsum) else np.nan,
         f"{pre}pf": w.sum() / -lsum.sum() if len(lsum) and lsum.sum() < 0 else np.nan,
         f"{pre}mean_pct": 100 * y.mean() if len(y) else np.nan,
         f"{pre}sum_pct": 100 * y.sum(), f"{pre}coins_pos": int((per["mean"] > 0).sum()),
         f"{pre}coins_n": len(per), f"{pre}coin_mdd_pct": coin_mdd(t) if len(t) else np.nan}
    d[f"{pre}rr"] = d[f"{pre}avg_win_pct"] / -d[f"{pre}avg_loss_pct"] if len(w) and len(lsum) else np.nan
    return d


def evaluate(all_t: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (tf, e, x), g in all_t.groupby(["tf", "entry", "exit"]):
        gi = g[g["split"].isin(SPLITS_IS)]
        gc = g[g["split"].isin(SPLITS_CONF)]
        r = {"tf": tf, "entry": e, "exit": x, **describe(gi, "is_"), **describe(gc, "cf_")}
        if len(gi) >= 100:
            day = pd.to_datetime(gi["entry_ts"], utc=True).dt.floor("D").to_numpy()
            _m, r["is_p"] = mean_test(gi["net"].to_numpy(), day)
        else:
            r["is_p"] = 1.0
        ets = pd.to_datetime(gi["entry_ts"], utc=True)
        r["is_half1_mean_pct"] = 100 * gi.loc[(ets < HALF).to_numpy(), "net"].mean()
        r["is_half2_mean_pct"] = 100 * gi.loc[(ets >= HALF).to_numpy(), "net"].mean()
        sl = g["sl_dist"].median()
        r["sl_dist_med_pct"] = 100 * sl
        # Highest leverage whose isolated liquidation (about 1/L - 0.5%) stays beyond the stop plus
        # the paper engine's buffer max(1.5 x stop, 0.2%) (the stop is 1-2 ATR; buffer ~3 ATR).
        need = sl + max(1.5 * sl, 0.002) + 0.005
        r["max_lev"] = int(min(125, np.floor(1 / need))) if need > 0 else np.nan
        r.update({f"is_{k}": v for k, v in owners_book(gi).items()})
        r.update({f"cf_{k}": v for k, v in owners_book(gc).items()})
        rows.append(r)
    t = pd.DataFrame(rows)
    t["bh_pass"] = bh(t["is_p"].to_numpy(), 0.10)
    t["is_ok"] = (t["bh_pass"] & (t["is_n"] >= 100) & (t["is_coins_pos"] >= 4) & (t["is_coins_pos"] > t["is_coins_n"] / 2)
                  & (t["is_half1_mean_pct"] > 0) & (t["is_half2_mean_pct"] > 0))
    t["cf_ok"] = (t["cf_mean_pct"] > 0) & (t["cf_pf"] > 1) & (t["cf_coins_pos"] >= 4)
    t["candidate"] = t["is_ok"] & t["cf_ok"]
    return t


def run(scratch: str) -> None:
    L = lib()
    import fg_indicators as fg
    import pine_indicators as pi
    os.makedirs(scratch, exist_ok=True)
    parts = []
    for tf in TFS:
        for split in (*SPLITS_IS, *SPLITS_CONF):
            t0 = time.time()
            t = run_split(L, fg, pi, tf, split)
            parts.append(t)
            print(f"{tf} {split}: {len(t)} trades, {time.time() - t0:.0f}s", flush=True)
    all_t = pd.concat(parts, ignore_index=True)
    all_t.to_pickle(os.path.join(scratch, "search_trades.pkl"))
    res = evaluate(all_t)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out, exist_ok=True)
    res.to_csv(os.path.join(out, "results.csv"), index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 300)
    cols = ["tf", "entry", "exit", "is_n", "is_win_pct", "is_rr", "is_pf", "is_mean_pct", "is_p", "is_coins_pos",
            "is_half1_mean_pct", "is_half2_mean_pct", "cf_n", "cf_win_pct", "cf_pf", "cf_mean_pct", "cf_coins_pos",
            "max_lev", "is_own_final_x", "cf_own_final_x", "bh_pass", "candidate"]
    print(res.sort_values("is_p")[cols].head(40).to_string())
    print("candidates:", int(res["candidate"].sum()), "bh_pass:", int(res["bh_pass"].sum()))


# ------------------------------------------------------------------ self-test (synthetic data only)
def selftest() -> None:
    L = lib()
    import fg_indicators as fg
    import pine_indicators as pi
    rng = np.random.default_rng(0)
    n = 6000
    ts = pd.date_range("2021-01-01", periods=n, freq="1h", tz="UTC")
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + rng.uniform(0, 0.004, n))
    lo = np.minimum(o, c) * (1 - rng.uniform(0, 0.004, n))
    df = pd.DataFrame({"ts": ts, "open": o, "high": h, "low": lo, "close": c, "volume": rng.uniform(1, 10, n)})
    df.attrs["tf"] = "1h"
    locked = L.compute_signals({"BTCUSD": df}, "1h", ["V39_ALL", "V45_AMB", "DOGE_L", "DOGE_S"], strict=True)
    sig = entries(L, fg, pi, df, "1h", {k: locked[k]["BTCUSD"] for k in locked})
    assert set(sig) == set(ENTRIES), set(ENTRIES) ^ set(sig)
    for k, a in sig.items():
        assert a.shape == (n,) and set(np.unique(a)) <= {-1, 0, 1}, k
    counts = {k: int(np.abs(a).sum()) for k, a in sig.items()}
    assert all(v > 0 for k, v in counts.items() if k not in ("E3_V39_NOSPIKE", "E4_V45_NOWITH", "E5_DOGE_TREND")), counts
    # Lookahead check: signals on bar t must not change when later bars are removed.
    cut = 4500
    df2 = df.iloc[:cut].copy()
    df2.attrs["tf"] = "1h"
    locked2 = L.compute_signals({"BTCUSD": df2}, "1h", ["V39_ALL", "V45_AMB", "DOGE_L", "DOGE_S"], strict=True)
    sig2 = entries(L, fg, pi, df2, "1h", {k: locked2[k]["BTCUSD"] for k in locked2})
    for k in sig:
        assert np.array_equal(sig[k][:cut - 1], sig2[k][:cut - 1]), f"lookahead in {k}"
    exits = [(name, L.ExitCfg(name=name, mode=mode, sl_atr=sl, tp_atr=tp if tp else 1e4, trail_atr=tr), MAX_HOLD)
             for name, mode, sl, tp, tr in EXITS]
    atr = fg.atr(df, 14).to_numpy(float)
    t = L.run_backtest(df, atr, sig["E1_CONNORS"] > 0, sig["E1_CONNORS"] < 0, exits[0][1], L._cost("1h", MAX_HOLD), 300, n - 60)
    assert len(t) > 10 and (t["exit_idx"] >= t["entry_idx"]).all()
    t = t.assign(symbol="BTCUSD", entry_ts=ts[t["entry_idx"]], exit_ts=ts[t["exit_idx"]])
    ob = owners_book(t)
    assert ob["own_trades"] == len(t)
    print("selftest ok", counts)


if __name__ == "__main__":
    if sys.argv[1] == "selftest":
        selftest()
    else:
        run(sys.argv[2])

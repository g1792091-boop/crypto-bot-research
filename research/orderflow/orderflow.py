"""Order-flow strategies (research/orderflow/PREREG_ORDERFLOW.md): funding, open interest, long/short
ratios, taker flow and premium index from the public Binance archive (data/orderflow/).

    python3 research/orderflow/orderflow.py selftest
    SWEEP_DATA=<rebuilt sweep data> python3 research/orderflow/orderflow.py run <scratch_dir>

Prices, engine, costs, exits and statistics are the same as research/search/search.py.
"""

from __future__ import annotations

import os
import sys
import time
import warnings

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research", "search"))
warnings.filterwarnings("ignore")

import search as SR  # noqa: E402  (engine wrapper, exits, statistics, owners' book)

DATA = os.path.join(ROOT, "data", "orderflow")
COIN_SYM = {"BTCUSD": "btc", "ETHUSD": "eth", "SOLUSD": "sol", "LTCUSD": "ltc", "BCHUSD": "bch",
            "DOGEUSD": "doge", "XRPUSD": "xrp"}
TFS = ("15m", "1h")
HOURS_30D, SETTLE_90D = 720, 270
METRIC_LAG = pd.Timedelta("5min")  # 5-minute metrics are used only 5 minutes after their stamp
ENTRIES = ["H1_FUNDING_FADE", "H2A_OI_UP_CONT", "H2B_OI_DOWN_FADE", "H3A_RETAIL_FADE", "H3B_TOP_VS_RETAIL",
           "H4_TAKER_CONT", "H5_PREMIUM_FADE"]


# ------------------------------------------------------------------ data
def _read(sym: str, name: str) -> pd.DataFrame:
    parts = sorted(f for f in os.listdir(DATA) if f.startswith(f"{sym}_{name}") and f.endswith(".csv.gz"))
    if not parts:
        return pd.DataFrame()
    return pd.concat([pd.read_csv(os.path.join(DATA, f)) for f in parts], ignore_index=True)


def _ts(x: pd.Series) -> pd.Series:
    """Binance archive times: epoch milliseconds, or text in the newer metrics files."""
    if pd.api.types.is_numeric_dtype(x):
        v = x.astype("int64")
        unit = "us" if v.median() > 1e14 else "ms"
        return pd.to_datetime(v, unit=unit, utc=True)
    return pd.to_datetime(x, utc=True)


def hourly_features(sym: str) -> pd.DataFrame:
    """Hourly feature table indexed by the hour's END (UTC). Every value is known at that time."""
    m = _read(sym, "metrics_5m")
    f = _read(sym, "funding")
    p = _read(sym, "premium_1h")
    out = {}
    if len(m):
        m["t"] = _ts(m["create_time"]) + METRIC_LAG
        m = m.sort_values("t").drop_duplicates("t", keep="last").set_index("t")
        cols = ["sum_open_interest_value", "count_long_short_ratio", "sum_toptrader_long_short_ratio",
                "sum_taker_long_short_vol_ratio"]
        m = m[cols].apply(pd.to_numeric, errors="coerce")
        # label each 5m value with the hour end at or after its availability time
        last = m.resample("1h", label="right", closed="right").last()
        taker = np.log(m["sum_taker_long_short_vol_ratio"].where(m["sum_taker_long_short_vol_ratio"] > 0))
        out["oi"] = last["sum_open_interest_value"]
        out["retail_ls"] = last["count_long_short_ratio"]
        out["top_ls"] = last["sum_toptrader_long_short_ratio"]
        out["taker_1h"] = taker.resample("1h", label="right", closed="right").mean()
    if len(f):
        f["t"] = _ts(f["calc_time"])
        f = f.sort_values("t").drop_duplicates("t", keep="last").set_index("t")
        rate = pd.to_numeric(f["last_funding_rate"], errors="coerce")
        rank = rate.rolling(SETTLE_90D, min_periods=90).rank(pct=True)
        settle = pd.DataFrame({"funding": rate, "funding_rank": rank})
        settle["settle_flag"] = 1.0
        h = settle.resample("1h", label="right", closed="right").last()
        out["funding"] = h["funding"]
        out["funding_rank"] = h["funding_rank"]
        out["funding_new"] = h["settle_flag"].fillna(0.0)
    if len(p):
        p["t"] = _ts(p["close_time"]).dt.ceil("1h")
        p = p.sort_values("t").drop_duplicates("t", keep="last").set_index("t")
        out["premium"] = pd.to_numeric(p["close"], errors="coerce")
    x = pd.DataFrame(out).sort_index()
    x = x[~x.index.duplicated(keep="last")]
    full = pd.date_range(x.index.min(), x.index.max(), freq="1h")
    x = x.reindex(full)
    for c in ("oi", "retail_ls", "top_ls", "funding", "funding_rank", "premium"):
        if c in x:
            x[c] = x[c].ffill(limit=3 if c != "funding" and c != "funding_rank" else 9)
    return x


def rolling_z(s: pd.Series, n: int) -> pd.Series:
    mu = s.rolling(n, min_periods=n // 2).mean().shift(1)
    sd = s.rolling(n, min_periods=n // 2).std().shift(1)
    return (s - mu) / sd


def rolling_rank(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n // 2).rank(pct=True)


def hourly_conditions(x: pd.DataFrame, close_1h: pd.Series) -> pd.DataFrame:
    """Long (+1) / short (-1) conditions on the hourly grid (index = hour end)."""
    c = pd.DataFrame(index=x.index)
    ret = close_1h.reindex(x.index).pct_change()
    zret = rolling_z(ret, HOURS_30D)
    # H1: the settlement just printed is in the top/bottom 5% of the last 90 days -> fade the crowd
    if "funding_rank" in x:
        new = x["funding_new"] > 0
        c["H1_FUNDING_FADE"] = np.where(new & (x["funding_rank"] >= 0.95) & (x["funding"] > 0.0001), -1,
                                        np.where(new & (x["funding_rank"] <= 0.05), 1, 0))
    if "oi" in x:
        doi = x["oi"].pct_change()
        zoi = rolling_z(doi, HOURS_30D)
        move = zret.abs() > 1
        c["H2A_OI_UP_CONT"] = np.where((zoi > 2) & move, np.sign(ret), 0)
        c["H2B_OI_DOWN_FADE"] = np.where((zoi < -2) & move, -np.sign(ret), 0)
        rr = rolling_rank(x["retail_ls"], HOURS_30D)
        c["H3A_RETAIL_FADE"] = np.where(rr >= 0.95, -1, np.where(rr <= 0.05, 1, 0))
        tr = rolling_rank(x["top_ls"], HOURS_30D)
        gap = tr - rr
        c["H3B_TOP_VS_RETAIL"] = np.where(gap >= 0.7, 1, np.where(gap <= -0.7, -1, 0))
        zt = rolling_z(x["taker_1h"], HOURS_30D)
        c["H4_TAKER_CONT"] = np.where(zt > 2.5, 1, np.where(zt < -2.5, -1, 0))
    if "premium" in x:
        pr = rolling_rank(x["premium"], HOURS_30D)
        c["H5_PREMIUM_FADE"] = np.where(pr >= 0.98, -1, np.where(pr <= 0.02, 1, 0))
    return c.fillna(0).astype(int)


def to_chart(L, df: pd.DataFrame, tf: str, cond: pd.DataFrame) -> dict[str, np.ndarray]:
    """Map hourly conditions to chart bars (value of the last hour ended at or before the bar's
    close) and keep only the onset bar (condition turns on or flips side)."""
    close_t = pd.to_datetime(df["ts"], utc=True) + pd.Timedelta(minutes=L.tf_minutes(tf))
    idx = cond.index
    j = np.searchsorted(idx.values, close_t.values, side="right") - 1
    valid = j >= 0
    out = {}
    for name in ENTRIES:
        if name not in cond:
            out[name] = np.zeros(len(df), np.int8)
            continue
        v = np.where(valid, cond[name].to_numpy()[np.clip(j, 0, len(idx) - 1)], 0)
        # stale features (hour older than 2h before the bar close) are not used
        age = close_t.values - idx.values[np.clip(j, 0, len(idx) - 1)]
        v = np.where(valid & (age <= np.timedelta64(2, "h")), v, 0)
        prev = np.r_[0, v[:-1]]
        out[name] = np.where((v != 0) & (v != prev), v, 0).astype(np.int8)
    return out


# ------------------------------------------------------------------ backtest
def run_split(L, fg, tf: str, split: str, feats: dict) -> pd.DataFrame:
    panel = L.load_panel(tf, split)
    exits = [(name, L.ExitCfg(name=name, mode=mode, sl_atr=sl, tp_atr=tp if tp else 1e4, trail_atr=tr), SR.MAX_HOLD)
             for name, mode, sl, tp, tr in SR.EXITS]
    parts = []
    for coin, df in panel.items():
        if coin not in feats:
            continue
        lo_, hi_ = L.signal_window(df, tf, split, SR.MAX_HOLD)
        if hi_ <= lo_:
            continue
        d1 = L.resample_ohlcv(df, "1h")
        close_1h = pd.Series(d1["close"].to_numpy(float), index=pd.to_datetime(d1["ts"], utc=True) + pd.Timedelta("1h"))
        cond = hourly_conditions(feats[coin], close_1h)
        sig = to_chart(L, df, tf, cond)
        atr = __import__("fg_indicators").atr(df, 14).to_numpy(float)
        ts = pd.to_datetime(df["ts"], utc=True).to_numpy()
        for ename, arr in sig.items():
            for xname, cfg, mh in exits:
                t = L.run_backtest(df, atr, arr > 0, arr < 0, cfg, L._cost(tf, mh), lo_, hi_)
                if len(t):
                    parts.append(t.assign(symbol=coin, entry=ename, exit=xname, tf=tf, split=split,
                                          entry_ts=ts[t["entry_idx"].to_numpy(int)],
                                          exit_ts=ts[t["exit_idx"].to_numpy(int)]))
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def run(scratch: str) -> None:
    L = SR.lib()
    import fg_indicators as fg
    os.makedirs(scratch, exist_ok=True)
    feats = {coin: hourly_features(sym) for coin, sym in COIN_SYM.items()}
    feats = {c: f for c, f in feats.items() if len(f)}
    parts = []
    for tf in TFS:
        for split in (*SR.SPLITS_IS, *SR.SPLITS_CONF):
            t0 = time.time()
            t = run_split(L, fg, tf, split, feats)
            parts.append(t)
            print(f"{tf} {split}: {len(t)} trades, {time.time() - t0:.0f}s", flush=True)
    all_t = pd.concat(parts, ignore_index=True)
    all_t.to_pickle(os.path.join(scratch, "orderflow_trades.pkl"))
    res = SR.evaluate(all_t)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out, exist_ok=True)
    res.to_csv(os.path.join(out, "results.csv"), index=False)
    pd.set_option("display.width", 260)
    cols = ["tf", "entry", "exit", "is_n", "is_win_pct", "is_rr", "is_pf", "is_mean_pct", "is_p", "is_coins_pos",
            "is_half1_mean_pct", "is_half2_mean_pct", "cf_n", "cf_win_pct", "cf_pf", "cf_mean_pct", "cf_coins_pos",
            "max_lev", "is_own_final_x", "cf_own_final_x", "bh_pass", "candidate"]
    print(res.sort_values("is_p")[cols].to_string())
    print("candidates:", int(res["candidate"].sum()), "bh_pass:", int(res["bh_pass"].sum()))


# ------------------------------------------------------------------ self-test (synthetic data only)
def selftest() -> None:
    rng = np.random.default_rng(1)
    idx = pd.date_range("2022-01-01 01:00", periods=3000, freq="1h", tz="UTC")
    x = pd.DataFrame({"oi": np.exp(np.cumsum(rng.normal(0, 0.01, 3000))) * 1e9,
                      "retail_ls": rng.uniform(0.5, 3, 3000), "top_ls": rng.uniform(0.5, 3, 3000),
                      "taker_1h": rng.normal(0, 0.1, 3000), "premium": rng.normal(0, 0.0005, 3000),
                      "funding": rng.normal(0.0001, 0.0002, 3000), "funding_rank": rng.uniform(0, 1, 3000),
                      "funding_new": (np.arange(3000) % 8 == 0).astype(float)}, index=idx)
    close = pd.Series(np.exp(np.cumsum(rng.normal(0, 0.005, 3000))) * 100, index=idx)
    c = hourly_conditions(x, close)
    assert set(c.columns) == set(ENTRIES), c.columns
    for k in ENTRIES:
        assert set(np.unique(c[k])) <= {-1, 0, 1} and (c[k] != 0).sum() > 0, k
    # no lookahead: conditions up to hour t do not change when later hours are removed
    c2 = hourly_conditions(x.iloc[:2000], close.iloc[:2000])
    assert c.iloc[:2000].equals(c2), "lookahead in hourly_conditions"
    L = SR.lib()
    ts = pd.date_range("2022-01-01", periods=12000, freq="15min", tz="UTC")
    df = pd.DataFrame({"ts": ts})
    sig = to_chart(L, df, "15m", c)
    for k, a in sig.items():
        on = np.flatnonzero(a)
        assert len(on) > 0, k
        # the hour used must have ended at or before the 15m bar's close
        bar_close = ts[on] + pd.Timedelta("15min")
        used = c.index[np.searchsorted(c.index.values, bar_close.values, side="right") - 1]
        assert (used <= bar_close).all()
    print("selftest ok", {k: int((a != 0).sum()) for k, a in sig.items()})


if __name__ == "__main__":
    if sys.argv[1] == "selftest":
        selftest()
    else:
        run(sys.argv[2])

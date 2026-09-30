"""Large strategy library with a three-window gauntlet (research/library/PREREG_LIBRARY.md).

    python3 research/library/lib.py selftest
    SWEEP_DATA=<rebuilt sweep data> python3 research/library/lib.py run <scratch_dir>

Windows: selection 2021-08..2024-06 (sweep 'is'), confirmation 2024-07..2026-09 (sweep 'oos'+'final'),
holdout 2020-01..2021-07 (data/pre2021, never used before). Engine, costs and exits: the backtest
session's locked engine, as in research/search/.
"""

from __future__ import annotations

import json
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

import search as SR  # noqa: E402

TFS = ("15m", "1h", "4h")
MAX_HOLD = 48
EXITS = [("X1_SL1_TP2", "FIXED", 1.0, 2.0, 0.0), ("X2_SL15_TP3", "FIXED", 1.5, 3.0, 0.0),
         ("X4_SL2_TP1", "FIXED", 2.0, 1.0, 0.0), ("X5_TRAIL2", "TRAIL", 2.0, 0.0, 2.0),
         ("X6_SL1_TP1", "FIXED", 1.0, 1.0, 0.0)]
PRE = (pd.Timestamp("2020-01-01", tz="UTC"), pd.Timestamp("2021-08-01", tz="UTC"))
PRE_COINS = {"BTCUSD": "btcusd", "ETHUSD": "ethusd", "SOLUSD": "solusd", "LTCUSD": "ltcusd",
             "BCHUSD": "bchusd", "DOGEUSD": "dogeusd", "XRPUSD": "xrpusd"}
TOP_K = 30


# ------------------------------------------------------------------ indicators
def _cross_up(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    return (a > b) & (np.r_[np.nan, a[:-1]] <= np.r_[np.nan, b[:-1]])


def _cross_dn(a, b):
    return _cross_up(b, a)


def _wma(x: pd.Series, n: int) -> pd.Series:
    w = np.arange(1, n + 1, dtype=float)
    return x.rolling(n).apply(lambda v: float(np.dot(v, w) / w.sum()), raw=True)


def _hma(x: pd.Series, n: int) -> pd.Series:
    return _wma(2 * _wma(x, n // 2) - _wma(x, n), int(np.sqrt(n)))


def entries(df: pd.DataFrame, fg, pi) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """{name: (long, short)} boolean arrays, signal known at the bar's close."""
    o, h, lo, c, v = (df[k].astype(float) for k in ("open", "high", "low", "close", "volume"))
    ca, ha, la = c.to_numpy(), h.to_numpy(), lo.to_numpy()
    E = {}
    with np.errstate(invalid="ignore", divide="ignore"):
        for f, s in ((9, 21), (20, 50), (50, 200)):
            a, b = pi.pine_ema(ca, f), pi.pine_ema(ca, s)
            E[f"T1_EMA{f}_{s}"] = (_cross_up(a, b), _cross_dn(a, b))
        for f, s in ((10, 30), (50, 200)):
            a, b = pi.pine_sma(ca, f), pi.pine_sma(ca, s)
            E[f"T2_SMA{f}_{s}"] = (_cross_up(a, b), _cross_dn(a, b))
        for f, s, g in ((12, 26, 9), (8, 21, 5)):
            m, sg, hist = pi.pine_macd(ca, f, s, g)
            E[f"T3_MACD{f}_{s}_{g}"] = (_cross_up(m, sg), _cross_dn(m, sg))
        m, sg, hist = pi.pine_macd(ca, 12, 26, 9)
        z = np.zeros(len(ca))
        E["T4_MACDHIST0"] = (_cross_up(hist, z), _cross_dn(hist, z))
        for n, mult in ((10, 2.0), (10, 3.0), (14, 4.0)):
            _l, d = pi.exchange_supertrend(ha, la, ca, n, mult)
            dp = np.r_[0, d[:-1]]
            E[f"T5_ST{n}_{mult:g}"] = ((d == 1) & (dp == -1), (d == -1) & (dp == 1))
        for n in (20, 55):
            hh, ll = pi.shift1(pi.pine_highest(ha, n)), pi.shift1(pi.pine_lowest(la, n))
            E[f"T6_DON{n}"] = (_cross_up(ca, hh), _cross_dn(ca, ll))
        up, mid, dn = fg.keltner_channel(df, 20, 10, 2.0)
        E["T7_KELT20_2"] = (_cross_up(ca, up.to_numpy()), _cross_dn(ca, dn.to_numpy()))
        _sar, sd = fg.parabolic_sar(df)
        sd = sd.to_numpy()
        sdp = np.r_[np.nan, sd[:-1]]
        E["T8_PSAR"] = ((sd == 1) & (sdp == -1), (sd == -1) & (sdp == 1))
        pdi, mdi, adx = fg.dmi_adx(df, 14, 14)
        strong = adx.to_numpy() > 25
        E["T9_DMI14_ADX25"] = (_cross_up(pdi.to_numpy(), mdi.to_numpy()) & strong,
                               _cross_dn(pdi.to_numpy(), mdi.to_numpy()) & strong)
        ten, kij, _sa, _sb = fg.ichimoku(df)
        E["T10_ICHI_TK"] = (_cross_up(ten.to_numpy(), kij.to_numpy()), _cross_dn(ten.to_numpy(), kij.to_numpy()))
        au, ad = fg.aroon(df, 25)
        E["T11_AROON25"] = (_cross_up(au.to_numpy(), ad.to_numpy()), _cross_dn(au.to_numpy(), ad.to_numpy()))
        for n in (21, 55):
            hm = _hma(c, n).to_numpy()
            sl = np.sign(np.r_[np.nan, np.diff(hm)])
            slp = np.r_[np.nan, sl[:-1]]
            E[f"T12_HMA{n}"] = ((sl > 0) & (slp < 0), (sl < 0) & (slp > 0))
        for n, lo_l, hi_l in ((14, 30, 70), (7, 20, 80)):
            r = pi.pine_rsi(ca, n)
            E[f"O1_RSI{n}_REV{lo_l}"] = (_cross_up(r, np.full(len(r), lo_l)), _cross_dn(r, np.full(len(r), hi_l)))
        r = pi.pine_rsi(ca, 14)
        E["O2_RSI14_X50"] = (_cross_up(r, np.full(len(r), 50.0)), _cross_dn(r, np.full(len(r), 50.0)))
        k, d = pi.stoch_kd(ca, ha, la, 14, 3, 3)
        E["O3_STOCH_ZONE"] = (_cross_up(k, d) & (k < 20), _cross_dn(k, d) & (k > 80))
        kr, dr = pi.stoch_rsi_kd(ca, 14, 14, 3, 3)
        E["O4_STOCHRSI_ZONE"] = (_cross_up(kr, dr) & (kr < 20), _cross_dn(kr, dr) & (kr > 80))
        cc = fg.cci(df, 20).to_numpy()
        E["O5_CCI20"] = (_cross_up(cc, np.full(len(cc), -100.0)), _cross_dn(cc, np.full(len(cc), 100.0)))
        wr = fg.williams_r(df, 14).to_numpy()
        E["O6_WR14"] = (_cross_up(wr, np.full(len(wr), -80.0)), _cross_dn(wr, np.full(len(wr), -20.0)))
        mf = fg.mfi(df, 14).to_numpy()
        E["O7_MFI14"] = (_cross_up(mf, np.full(len(mf), 20.0)), _cross_dn(mf, np.full(len(mf), 80.0)))
        for n in (9, 21):
            rc = fg.roc(c, n).to_numpy()
            E[f"O8_ROC{n}"] = (_cross_up(rc, z), _cross_dn(rc, z))
        cm = fg.cmo(c, 14).to_numpy()
        E["O9_CMO14"] = (_cross_up(cm, z), _cross_dn(cm, z))
        bu, bm, bl, _bw = fg.bollinger_bands(c, 20, 2.0)
        bu, bl = bu.to_numpy(), bl.to_numpy()
        E["V1_BB_BREAK"] = (_cross_up(ca, bu), _cross_dn(ca, bl))
        E["V2_BB_REVERT"] = (_cross_up(ca, bl), _cross_dn(ca, bu))
        ku, _km, kl = fg.keltner_channel(df, 20, 20, 1.5)
        sq = (bu < ku.to_numpy()) & (bl > kl.to_numpy())
        sq6 = pd.Series(sq.astype(float)).shift(1).rolling(6).min().to_numpy() == 1
        E["V3_SQUEEZE"] = (sq6 & (ca > bu), sq6 & (ca < bl))
        ob = pi.obv(ca, v.to_numpy())
        obm = pi.pine_sma(ob, 20)
        E["VO1_OBV_X_MA20"] = (_cross_up(ob, obm), _cross_dn(ob, obm))
        vs = v.to_numpy() > 3 * pi.shift1(pi.pine_sma(v.to_numpy(), 20))
        E["VO2_VOL_SPIKE"] = (vs & (ca > o.to_numpy()), vs & (ca < o.to_numpy()))
        op, cp = np.r_[np.nan, o.to_numpy()[:-1]], np.r_[np.nan, ca[:-1]]
        oa = o.to_numpy()
        E["C1_ENGULF"] = ((cp < op) & (ca > oa) & (ca >= op) & (oa <= cp), (cp > op) & (ca < oa) & (ca <= op) & (oa >= cp))
        body = np.abs(ca - oa)
        rng = ha - la
        low_wick = np.minimum(ca, oa) - la
        up_wick = ha - np.maximum(ca, oa)
        E["C2_HAMMER_STAR"] = ((low_wick >= 2 * body) & (up_wick <= 0.3 * rng) & (rng > 0),
                               (up_wick >= 2 * body) & (low_wick <= 0.3 * rng) & (rng > 0))
        hp, lp = np.r_[np.nan, ha[:-1]], np.r_[np.nan, la[:-1]]
        inside_prev = np.r_[False, (ha[1:] < ha[:-1]) & (la[1:] > la[:-1])]  # bar t-1 inside bar t-2
        hpp, lpp = np.r_[np.nan, np.nan, ha[:-2]], np.r_[np.nan, np.nan, la[:-2]]
        E["C3_INSIDE_BREAK"] = (inside_prev & (ca > hpp), inside_prev & (ca < lpp))
        up3 = pd.Series(ca > oa).rolling(3).sum().to_numpy() == 3
        dn3 = pd.Series(ca < oa).rolling(3).sum().to_numpy() == 3
        E["C4_THREE_SAME"] = (up3, dn3)
        e200 = pi.pine_ema(ca, 200)
    out = {}
    for name, (lg, sh) in E.items():
        lg = np.nan_to_num(np.asarray(lg, float)) != 0
        sh = (np.nan_to_num(np.asarray(sh, float)) != 0) & ~lg
        out[name] = (lg, sh)
        out[name + "+F200"] = (lg & (ca > e200), sh & (ca < e200))
    return out


# ------------------------------------------------------------------ data windows
def pre_panel(tf: str) -> dict[str, pd.DataFrame]:
    out = {}
    for coin, stem in PRE_COINS.items():
        p = os.path.join(ROOT, "data", "pre2021", f"{stem}-{tf}.csv.gz")
        if not os.path.exists(p):
            continue
        d = pd.read_csv(p)
        d["ts"] = pd.to_datetime(d["ts"], utc=True)
        d = d.sort_values("ts").drop_duplicates("ts").reset_index(drop=True)
        d = d[d["ts"] < PRE[1] + pd.Timedelta(days=10)].reset_index(drop=True)  # room for the last exits
        d.attrs["tf"] = tf
        out[coin] = d
    return out


def pre_window(L, df: pd.DataFrame, tf: str) -> tuple[int, int]:
    ts = df["ts"].values
    lo = max(int(np.searchsorted(ts, PRE[0].to_datetime64())), L.warmup_bars(tf))
    hi = int(np.searchsorted(ts, PRE[1].to_datetime64())) - (MAX_HOLD + 1)
    return lo, max(lo, hi)


def run_window(L, fg, pi, tf: str, split: str) -> pd.DataFrame:
    panel = pre_panel(tf) if split == "pre" else L.load_panel(tf, split)
    exits = [(name, L.ExitCfg(name=name, mode=mode, sl_atr=sl, tp_atr=tp if tp else 1e4, trail_atr=tr), MAX_HOLD)
             for name, mode, sl, tp, tr in EXITS]
    parts = []
    for coin, df in panel.items():
        df.attrs["tf"] = tf
        lo_, hi_ = pre_window(L, df, tf) if split == "pre" else L.signal_window(df, tf, split, MAX_HOLD)
        if hi_ <= lo_:
            continue
        atr = fg.atr(df, 14).to_numpy(float)
        ts = pd.to_datetime(df["ts"], utc=True).to_numpy()
        for ename, (lg, sh) in entries(df, fg, pi).items():
            for xname, cfg, mh in exits:
                t = L.run_backtest(df, atr, lg, sh, cfg, L._cost(tf, mh), lo_, hi_)
                if len(t):
                    parts.append(t.assign(symbol=coin, entry=ename, exit=xname, tf=tf, split=split,
                                          entry_ts=ts[t["entry_idx"].to_numpy(int)],
                                          exit_ts=ts[t["exit_idx"].to_numpy(int)]))
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


# ------------------------------------------------------------------ gauntlet
def stats_block(g: pd.DataFrame, pre: str) -> dict:
    d = SR.describe(g, pre)
    if len(g) >= 20:
        day = pd.to_datetime(g["entry_ts"], utc=True).dt.floor("D").to_numpy()
        _m, d[f"{pre}p"] = SR.mean_test(g["net"].to_numpy(), day)
    else:
        d[f"{pre}p"] = 1.0
    d.update({f"{pre}{k}": v for k, v in SR.owners_book(g).items()})
    return d


def gauntlet(all_t: pd.DataFrame) -> pd.DataFrame:
    rows = []
    half = pd.Timestamp("2023-01-01", tz="UTC")
    for (tf, e, x), g in all_t.groupby(["tf", "entry", "exit"]):
        gi = g[g["split"] == "is"]
        gc = g[g["split"].isin(["oos", "final"])]
        gp = g[g["split"] == "pre"]
        r = {"tf": tf, "entry": e, "exit": x, **stats_block(gi, "is_"), **stats_block(gc, "cf_"), **stats_block(gp, "pre_")}
        ets = pd.to_datetime(gi["entry_ts"], utc=True)
        r["is_half1_mean_pct"] = 100 * gi.loc[(ets < half).to_numpy(), "net"].mean()
        r["is_half2_mean_pct"] = 100 * gi.loc[(ets >= half).to_numpy(), "net"].mean()
        sl = g["sl_dist"].median()
        r["max_lev"] = int(min(125, np.floor(1 / (sl + max(1.5 * sl, 0.002) + 0.005)))) if sl > 0 else 0
        rows.append(r)
    t = pd.DataFrame(rows)
    t["stage1"] = ((t["is_n"] >= 100) & (t["is_mean_pct"] > 0) & (t["is_coins_pos"] >= 4)
                   & (t["is_coins_pos"] > t["is_coins_n"] / 2) & (t["is_half1_mean_pct"] > 0)
                   & (t["is_half2_mean_pct"] > 0))
    ranked = t[t["stage1"]].sort_values("is_p")
    k = min(TOP_K, len(ranked))
    t["stage1_top"] = t.index.isin(ranked.index[:k])
    t["stage2"] = t["stage1_top"] & (t["cf_mean_pct"] > 0) & (t["cf_pf"] > 1) & (t["cf_coins_pos"] >= 4) \
        & (t["cf_p"] < 0.05 / max(k, 1))
    t["stage3"] = t["stage2"] & (t["pre_mean_pct"] > 0) & (t["pre_pf"] > 1) & (t["pre_coins_pos"] >= 3) \
        & (t["pre_coins_pos"] > t["pre_coins_n"] / 2) & (t["pre_p"] < 0.05)
    t["x20_ok"] = (t["max_lev"] >= 20) & (t["is_own_final_x"] > 1) & (t["cf_own_final_x"] > 1) & (t["pre_own_final_x"] > 1)
    t["candidate_20x"] = t["stage3"] & t["x20_ok"]
    t.attrs["top_k"] = k
    return t


def run(scratch: str) -> None:
    L = SR.lib()
    import fg_indicators as fg
    import pine_indicators as pi
    os.makedirs(scratch, exist_ok=True)
    parts = []
    for tf in TFS:
        for split in ("is", "oos", "final", "pre"):
            t0 = time.time()
            t = run_window(L, fg, pi, tf, split)
            parts.append(t)
            print(f"{tf} {split}: {len(t)} trades, {time.time() - t0:.0f}s", flush=True)
    all_t = pd.concat(parts, ignore_index=True)
    all_t.to_pickle(os.path.join(scratch, "library_trades.pkl"))
    res = gauntlet(all_t)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out, exist_ok=True)
    res.to_csv(os.path.join(out, "results.csv"), index=False)
    summary = {"configs": len(res), "stage1": int(res["stage1"].sum()), "stage1_top": int(res["stage1_top"].sum()),
               "stage2": int(res["stage2"].sum()), "stage3": int(res["stage3"].sum()),
               "candidate_20x": int(res["candidate_20x"].sum())}
    with open(os.path.join(out, "summary.json"), "w") as fh:
        json.dump(summary, fh, indent=1)
    pd.set_option("display.width", 280)
    cols = ["tf", "entry", "exit", "is_n", "is_win_pct", "is_rr", "is_mean_pct", "is_p", "is_coins_pos", "cf_n",
            "cf_mean_pct", "cf_pf", "cf_p", "cf_coins_pos", "pre_n", "pre_mean_pct", "pre_pf", "pre_p", "pre_coins_pos",
            "max_lev", "stage2", "stage3", "candidate_20x"]
    print(res[res["stage1_top"]].sort_values("is_p")[cols].round(4).to_string())
    print(json.dumps(summary))


def selftest() -> None:
    L = SR.lib()
    import fg_indicators as fg
    import pine_indicators as pi
    rng = np.random.default_rng(3)
    n = 3000
    ts = pd.date_range("2021-01-01", periods=n, freq="1h", tz="UTC")
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    o = np.r_[c[0], c[:-1]]
    df = pd.DataFrame({"ts": ts, "open": o, "high": np.maximum(o, c) * (1 + rng.uniform(0, 0.012, n)),
                       "low": np.minimum(o, c) * (1 - rng.uniform(0, 0.012, n)), "close": c,
                       "volume": rng.lognormal(0, 1, n)})
    df.attrs["tf"] = "1h"
    e = entries(df, fg, pi)
    assert len(e) == 80, len(e)
    e2 = entries(df.iloc[:2500].copy(), fg, pi)
    for k in e:
        for side in (0, 1):
            assert np.array_equal(e[k][side][:2499], e2[k][side][:2499]), f"lookahead in {k}"
    silent = [k for k, (lg, sh) in e.items() if not (lg | sh).any() and not k.endswith("+F200")]
    assert not silent, silent
    print("selftest ok", len(e), "entries")


if __name__ == "__main__":
    selftest() if sys.argv[1] == "selftest" else run(sys.argv[2])

"""Loss-cause diagnosis of the 37 strategies (research/diagnosis/PREREG_DIAG.md).

    SWEEP_DATA=<rebuilt sweep data> python3 research/diagnosis/diag.py build <tf> <out_dir>
    python3 research/diagnosis/diag.py report <out_dir>

build: selection window only (split "is"), the locked signal code, ATR_SL2_TP3 trades
(1x, max 64 bars, 0.14% round trip + funding), entry-time features, post-trade facts,
and a random-entry baseline (5 seeds). report: the tests and fix candidates of the
pre-registration.
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
warnings.filterwarnings("ignore")

TFS = ("15m", "30m", "1h", "4h")
HTF = {"15m": "1h", "30m": "2h", "1h": "4h", "4h": "1d"}
H = 16
MIN_CELL, MIN_BIN, MIN_COIN_BIN, Q = 300, 100, 20, 0.10
HALF = pd.Timestamp("2023-01-01", tz="UTC")
FEATURES = ["F1_side", "F2_coin", "F3_trend_age", "F4_extension", "F5_runup", "F6_range_pos",
            "F7_htf", "F8_regime", "F9_vol_level", "F10_vol_change", "F11_session", "F12_weekend",
            "F13_btc", "F14_crowd"]
LABEL = {
    "F1_side": "방향", "F2_coin": "코인", "F3_trend_age": "추세 나이", "F4_extension": "추세 연장(EMA20 거리)",
    "F5_runup": "직전 상승폭", "F6_range_pos": "64봉 범위 안 위치", "F7_htf": "상위 봉 추세",
    "F8_regime": "추세/횡보", "F9_vol_level": "변동성 수준", "F10_vol_change": "변동성 변화",
    "F11_session": "시간대(KST)", "F12_weekend": "주말", "F13_btc": "BTC 방향", "F14_crowd": "신호 몰림"}


def lib():
    from paperbot import sweepsig
    return sweepsig.lib()


# ------------------------------------------------------------------ features
def _run_length(mask: np.ndarray) -> np.ndarray:
    out = np.zeros(len(mask), dtype=np.int64)
    run = 0
    for i, m in enumerate(mask):
        run = run + 1 if m else 0
        out[i] = run
    return out


def bar_features(L, fg, df: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Side-independent raw features per bar (known at the bar's close)."""
    c, h, lo = df["close"], df["high"], df["low"]
    atr = fg.atr(df, 14).astype(float)
    ema20 = c.ewm(span=20, adjust=False).mean()
    up = (c > ema20).to_numpy()
    f = pd.DataFrame(index=df.index)
    f["age_up"] = _run_length(up)
    f["age_dn"] = _run_length(~up)
    f["ext"] = (c - ema20) / atr
    f["runup"] = (c - c.shift(16)) / atr
    hi64, lo64 = h.rolling(64).max(), lo.rolling(64).min()
    f["pos"] = (c - lo64) / (hi64 - lo64)
    path = c.diff().abs().rolling(48).sum()
    f["er"] = (c - c.shift(48)).abs() / path
    f["vol_level"] = atr / atr.rolling(500, min_periods=100).median()
    f["vol_change"] = atr / atr.shift(20)
    # Higher timeframe EMA50 slope of the last HTF bar closed at this bar's close.
    htf = HTF[tf]
    dh = L.resample_ohlcv(df, htf)
    e50 = dh["close"].ewm(span=50, adjust=False).mean()
    slope = (e50 - e50.shift(5)).to_numpy()
    hclose = L.htf_close_ns(dh["ts"], htf)
    cclose = L._utc_ns(df["ts"]) + np.timedelta64(L.tf_minutes(tf), "m")
    j = np.searchsorted(hclose, cclose, side="right") - 1
    f["htf_slope"] = np.where(j >= 0, slope[np.clip(j, 0, len(slope) - 1)], np.nan)
    kst = pd.to_datetime(df["ts"], utc=True).dt.tz_convert("Asia/Seoul")
    f["kst_hour"] = kst.dt.hour.to_numpy()
    f["kst_weekend"] = (kst.dt.weekday >= 5).to_numpy()
    f["ret16"] = c / c.shift(16) - 1
    return f


def _session(hour: np.ndarray) -> np.ndarray:
    return np.select([(hour >= 9) & (hour < 16), (hour >= 16) & (hour < 22), (hour >= 5) & (hour < 9)],
                     ["asia", "europe", "dawn"], "us")


def bin_trades(t: pd.DataFrame, er_cuts: dict) -> pd.DataFrame:
    """Pre-registered bins; ``t`` has raw features at the signal bar and ``side``."""
    s = t["side"].to_numpy()
    age_with = np.where(s > 0, t["age_up"], t["age_dn"])
    out = pd.DataFrame(index=t.index)
    out["F1_side"] = np.where(s > 0, "long", "short")
    out["F2_coin"] = t["symbol"].to_numpy()
    out["F3_trend_age"] = np.select([age_with == 0, age_with <= 3, age_with <= 15],
                                    ["against", "1-3", "4-15"], "16+")
    ext = t["ext"].to_numpy() * s
    out["F4_extension"] = np.select([ext < 0, ext < 1, ext < 2.5], ["<0", "0-1", "1-2.5"], ">=2.5")
    ru = t["runup"].to_numpy() * s
    out["F5_runup"] = np.select([ru < -2, ru < 0, ru < 2, ru < 4], ["<-2", "-2-0", "0-2", "2-4"], ">=4")
    pos = np.where(s > 0, t["pos"], 1 - t["pos"])
    out["F6_range_pos"] = np.select([pos < 0.2, pos < 0.5, pos < 0.8], ["0-0.2", "0.2-0.5", "0.5-0.8"], "0.8-1")
    hs = np.sign(t["htf_slope"].to_numpy()) * s
    out["F7_htf"] = np.select([hs > 0, hs < 0], ["with", "against"], "flat")
    lo_c = t["symbol"].map(lambda x: er_cuts[x][0]).to_numpy()
    hi_c = t["symbol"].map(lambda x: er_cuts[x][1]).to_numpy()
    er = t["er"].to_numpy()
    out["F8_regime"] = np.select([er < lo_c, er < hi_c], ["chop", "mid"], "trend")
    vl = t["vol_level"].to_numpy()
    out["F9_vol_level"] = np.select([vl < 0.8, vl <= 1.25], ["<0.8", "0.8-1.25"], ">1.25")
    vc = t["vol_change"].to_numpy()
    out["F10_vol_change"] = np.select([vc < 0.9, vc <= 1.1], ["contract", "steady"], "expand")
    out["F11_session"] = _session(t["kst_hour"].to_numpy())
    out["F12_weekend"] = np.where(t["kst_weekend"].to_numpy(), "weekend", "weekday")
    bs = np.sign(t["btc_ret16"].to_numpy()) * s
    out["F13_btc"] = np.select([bs > 0, bs < 0], ["with", "against"], "flat")
    cr = t["crowd"].to_numpy()
    out["F14_crowd"] = np.select([cr == 0, cr <= 2], ["0", "1-2"], "3+")
    # Missing raw inputs (warm-up edges) become their own bin and are never tested.
    for col, raw in (("F4_extension", "ext"), ("F5_runup", "runup"), ("F6_range_pos", "pos"),
                     ("F8_regime", "er"), ("F9_vol_level", "vol_level"), ("F10_vol_change", "vol_change")):
        out.loc[t[raw].isna().to_numpy(), col] = "na"
    out.loc[t["htf_slope"].isna().to_numpy(), "F7_htf"] = "na"
    return out


# ------------------------------------------------------------------ build
def build(tf: str, out_dir: str, seeds: int = 5) -> None:
    L = lib()
    import fg_indicators as fg  # vendored, on sys.path after lib()
    t0 = time.time()
    panel = L.load_panel(tf, "is")
    ex = [e for e in L.exit_set(H) if e[0] == "ATR_SL2_TP3"]
    atrs = {c: fg.atr(df, 14).to_numpy(float) for c, df in panel.items()}
    windows = {}
    for c, df in panel.items():
        lo, hi = L.signal_window(df, tf, "is", 0)
        if hi - lo > 2 * L.EXIT_CAP_MULT * H + 4:
            windows[c] = (lo, hi)
    feats = {c: bar_features(L, fg, df, tf) for c, df in panel.items()}
    er_cuts = {c: tuple(np.nanquantile(f["er"].to_numpy(), [1 / 3, 2 / 3])) for c, f in feats.items()}
    btc = panel["BTCUSD"].set_index("ts")["close"]
    btc_ret = (btc / btc.shift(16) - 1)
    for c, df in panel.items():
        feats[c]["btc_ret16"] = btc_ret.reindex(df["ts"]).to_numpy()
    sigs = L.compute_signals(panel, tf, L.NAMES, strict=False)
    print(f"{tf}: signals {time.time() - t0:.0f}s", flush=True)
    crowd_long, crowd_short = {}, {}
    for c, df in panel.items():
        arrs = [sigs[n][c] for n in L.NAMES if c in sigs.get(n, {})]
        m = np.vstack(arrs)
        crowd_long[c], crowd_short[c] = (m > 0).sum(0), (m < 0).sum(0)

    def enrich(tr: pd.DataFrame, strategy: str) -> pd.DataFrame:
        rows = []
        for c, g in tr.groupby("symbol"):
            df, f = panel[c], feats[c]
            i = g["signal_idx"].to_numpy()
            x = f.iloc[i].reset_index(drop=True)
            x["symbol"] = c
            x["side"] = g["side"].to_numpy()
            x["net"] = g["net"].to_numpy()
            x["gross"] = g["gross"].to_numpy()
            x["reason"] = g["reason"].to_numpy()
            x["mfe"] = g["mfe"].to_numpy()
            x["hold"] = g["hold"].to_numpy()
            x["entry_ts"] = df["ts"].to_numpy()[g["entry_idx"].to_numpy()]
            same = np.where(g["side"].to_numpy() > 0, crowd_long[c][i], crowd_short[c][i])
            x["crowd"] = same - (1 if strategy != "RANDOM" else 0)
            # Stop too tight: after a stop, the 3 ATR target is reached within 64 bars.
            hi, lo_ = df["high"].to_numpy(), df["low"].to_numpy()
            ex_i, ep = g["exit_idx"].to_numpy(), g["entry_px"].to_numpy()
            tp = ep + g["side"].to_numpy() * 3 * atrs[c][i]
            hit = np.zeros(len(g), dtype=bool)
            for k in np.flatnonzero(g["reason"].to_numpy() == "SL"):
                a, b = ex_i[k] + 1, min(ex_i[k] + 65, len(df))
                if a < b:
                    hit[k] = (hi[a:b].max() >= tp[k]) if g["side"].iloc[k] > 0 else (lo_[a:b].min() <= tp[k])
            x["sl_then_tp"] = hit
            rows.append(x)
        out = pd.concat(rows, ignore_index=True)
        return pd.concat([out, bin_trades(out, er_cuts)], axis=1).assign(strategy=strategy, tf=tf)

    parts = []
    for name in L.NAMES:
        if name not in sigs or not sigs[name]:
            continue
        tr = L._run_exits_panel(panel, sigs[name], tf, "is", H, atrs, windows, 0, ex)["ATR_SL2_TP3"]
        if len(tr):
            parts.append(enrich(tr, name))
    strat = pd.concat(parts, ignore_index=True)
    mean_n = strat.groupby(["strategy", "symbol"]).size().mean()
    nbars = sum(hi - lo for lo, hi in windows.values()) / len(windows)
    rate = min(0.5, 1.3 * mean_n / nbars)
    rparts = []
    for s in range(seeds):
        rng = np.random.default_rng([s, 20260930])
        dsig = {c: np.where(rng.random(len(df)) < rate, rng.choice([-1, 1], len(df)), 0).astype(np.int8)
                for c, df in panel.items()}
        tr = L._run_exits_panel(panel, dsig, tf, "is", H, atrs, windows, 0, ex)["ATR_SL2_TP3"]
        rparts.append(enrich(tr, "RANDOM").assign(seed=s))
    rnd = pd.concat(rparts, ignore_index=True)
    os.makedirs(out_dir, exist_ok=True)
    strat.to_pickle(os.path.join(out_dir, f"trades_{tf}.pkl"))
    rnd.to_pickle(os.path.join(out_dir, f"random_{tf}.pkl"))
    print(f"{tf}: {len(strat)} strategy trades, {len(rnd)} random trades, {time.time() - t0:.0f}s", flush=True)


# ------------------------------------------------------------------ statistics
def diff_test(y: np.ndarray, b: np.ndarray, day: np.ndarray) -> tuple[float, float]:
    """Mean(y | b) - mean(y | not b) with standard error clustered by day."""
    n1, n0 = b.sum(), (~b).sum()
    d = y[b].mean() - y[~b].mean()
    x = b.astype(float)
    xc = x - x.mean()
    e = y - np.where(b, y[b].mean(), y[~b].mean())
    g = pd.Series(xc * e).groupby(day).sum().to_numpy()
    se = np.sqrt((g ** 2).sum()) / (xc ** 2).sum()
    return float(d), float(se)


def bh(p: np.ndarray, q: float) -> np.ndarray:
    n = len(p)
    order = np.argsort(p)
    thresh = q * (np.arange(1, n + 1) / n)
    passed = p[order] <= thresh
    k = np.max(np.flatnonzero(passed)) + 1 if passed.any() else 0
    out = np.zeros(n, dtype=bool)
    out[order[:k]] = True
    return out


def report(out_dir: str) -> dict:
    from math import erf, sqrt
    tests, cells, rand_rows, desc = [], [], [], []
    trades = {}
    for tf in TFS:
        p = os.path.join(out_dir, f"trades_{tf}.pkl")
        if not os.path.exists(p):
            continue
        T = pd.read_pickle(p)
        R = pd.read_pickle(os.path.join(out_dir, f"random_{tf}.pkl"))
        trades[tf] = T
        R["day"] = pd.to_datetime(R["entry_ts"]).dt.floor("D").astype("int64")
        for f in FEATURES:
            for v, g in R.groupby(f):
                if v == "na" or len(g) < MIN_BIN or len(R) - len(g) < MIN_BIN:
                    continue
                b = (R[f] == v).to_numpy()
                d, se = diff_test(R["net"].to_numpy(), b, R["day"].to_numpy())
                rand_rows.append(dict(tf=tf, feature=f, bin=v, share=b.mean(), d=d, se=se,
                                      mean_bin=R["net"][b].mean()))
        T["day"] = pd.to_datetime(T["entry_ts"]).dt.floor("D").astype("int64")
        T["late"] = pd.to_datetime(T["entry_ts"]) >= HALF
        for strat, C in T.groupby("strategy"):
            n = len(C)
            y = C["net"].to_numpy()
            cells.append(dict(tf=tf, strategy=strat, n=n, mean=y.mean(), win=(y > 0).mean(),
                              coins_pos=int((C.groupby("symbol")["net"].sum() > 0).sum()),
                              sl_share=(C["reason"] == "SL").mean(),
                              sl_then_tp=C.loc[C["reason"] == "SL", "sl_then_tp"].mean(),
                              mfe_capture=np.nanmean(np.where(C["mfe"] > 0, C["gross"] / C["mfe"], np.nan)),
                              eligible=n >= MIN_CELL))
            for f in FEATURES:
                share = C[f].value_counts(normalize=True)
                for v, sh in share.items():
                    desc.append(dict(tf=tf, strategy=strat, feature=f, bin=v, share=sh))
            if n < MIN_CELL:
                continue
            for f in FEATURES:
                for v in C[f].unique():
                    if v == "na":
                        continue
                    b = (C[f] == v).to_numpy()
                    if b.sum() < MIN_BIN or (~b).sum() < MIN_BIN:
                        continue
                    d, se = diff_test(y, b, C["day"].to_numpy())
                    z = d / se if se > 0 else 0.0
                    pval = 2 * (1 - 0.5 * (1 + erf(abs(z) / sqrt(2))))
                    neg_coins = elig = 0
                    for c, G in C.groupby("symbol"):
                        bb = (G[f] == v).to_numpy()
                        if bb.sum() >= MIN_COIN_BIN and (~bb).sum() >= MIN_COIN_BIN:
                            elig += 1
                            neg_coins += G["net"][bb].mean() < G["net"][~bb].mean()
                    halves = []
                    for late in (False, True):
                        G = C[C["late"] == late]
                        bb = (G[f] == v).to_numpy()
                        halves.append(G["net"][bb].mean() - G["net"][~bb].mean()
                                      if bb.sum() >= 30 and (~bb).sum() >= 30 else np.nan)
                    tests.append(dict(tf=tf, strategy=strat, feature=f, bin=v, n_bin=int(b.sum()),
                                      share=b.mean(), mean_bin=y[b].mean(), mean_rest=y[~b].mean(), d=d,
                                      se=se, p=pval, coins_eligible=elig, coins_worse=neg_coins,
                                      d_first=halves[0], d_second=halves[1]))
    tests = pd.DataFrame(tests)
    cells = pd.DataFrame(cells)
    rand = pd.DataFrame(rand_rows)
    desc = pd.DataFrame(desc)
    tests["fdr_pass"] = bh(tests["p"].to_numpy(), Q)
    tests["weak_spot"] = (tests["fdr_pass"] & (tests["d"] < 0) & (tests["coins_worse"] >= 4)
                          & (tests["coins_worse"] > tests["coins_eligible"] / 2)
                          & (tests["d_first"] < 0) & (tests["d_second"] < 0))
    tests["strength"] = (tests["fdr_pass"] & (tests["d"] > 0))
    tests = tests.merge(rand[["tf", "feature", "bin", "d", "mean_bin", "share"]].rename(
        columns={"d": "random_d", "mean_bin": "random_mean_bin", "share": "random_share"}),
        on=["tf", "feature", "bin"], how="left")
    # Fix candidates (section 5): exclude one weak spot, or all weak spots of the cell.
    cand = []
    for tf, T in trades.items():
        for (tf_, strat), W in tests[tests["weak_spot"] & (tests["tf"] == tf)].groupby(["tf", "strategy"]):
            C = T[T["strategy"] == strat]
            base = C["net"].mean()
            options = [[(r.feature, r.bin)] for r in W.itertuples()]
            if len(W) > 1:
                options.append([(r.feature, r.bin) for r in W.itertuples()])
            for excl in options:
                keep = np.ones(len(C), dtype=bool)
                for f, v in excl:
                    keep &= (C[f] != v).to_numpy()
                K = C[keep]
                if not len(K):
                    continue
                cand.append(dict(tf=tf, strategy=strat, exclude=" & ".join(f"{f}={v}" for f, v in excl),
                                 n_before=len(C), n_after=len(K), mean_before=base, mean_after=K["net"].mean(),
                                 improvement=K["net"].mean() - base,
                                 coins_pos_after=int((K.groupby("symbol")["net"].sum() > 0).sum()),
                                 bundle=len(excl) > 1))
    cand = pd.DataFrame(cand)
    if len(cand):
        cand["lockable"] = (cand["mean_after"] > 0) & (cand["n_after"] >= 100) & (cand["coins_pos_after"] >= 4)
        locked = cand[cand["lockable"]].sort_values("improvement", ascending=False).head(20)
    else:
        locked = cand
    for name, df in (("tests", tests), ("cells", cells), ("random_bins", rand), ("entry_shares", desc),
                     ("candidates", cand), ("locked", locked)):
        df.to_csv(os.path.join(out_dir, f"{name}.csv"), index=False)
    summary = {
        "tests": int(len(tests)), "fdr_pass": int(tests["fdr_pass"].sum()),
        "weak_spots": int(tests["weak_spot"].sum()), "strengths": int(tests["strength"].sum()),
        "cells_eligible": int(cells["eligible"].sum()), "candidates": int(len(cand)),
        "lockable": int(cand["lockable"].sum()) if len(cand) else 0, "locked": int(len(locked)),
    }
    json.dump(summary, open(os.path.join(out_dir, "summary.json"), "w"), indent=2)
    return summary


if __name__ == "__main__":
    if sys.argv[1] == "build":
        build(sys.argv[2], sys.argv[3])
    else:
        print(json.dumps(report(sys.argv[2]), indent=2))

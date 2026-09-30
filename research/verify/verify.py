"""Checks that the "0 pass" results are not a pipeline artefact (research/verify/PREREG_VERIFY.md).

    SWEEP_DATA=<rebuilt sweep data> python3 research/verify/verify.py run <scratch_dir>

V1/V2  positive and negative controls through the same engine and judging code
V3     information coefficients of every order-flow / price feature vs forward returns
V4     alignment: contemporaneous relations that must be strongly positive if timestamps line up
V5     independent re-simulation of one order-flow config without the locked engine
"""

from __future__ import annotations

import json
import os
import sys
import warnings

import numpy as np
import pandas as pd
from scipy import stats

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
for sub in ("research/search", "research/orderflow"):
    sys.path.insert(0, os.path.join(ROOT, sub))
warnings.filterwarnings("ignore")

import search as SR  # noqa: E402
import orderflow as OF  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
IS = (pd.Timestamp("2021-08-01", tz="UTC"), pd.Timestamp("2024-07-01", tz="UTC"))
CF = (pd.Timestamp("2024-07-01", tz="UTC"), pd.Timestamp("2026-09-30", tz="UTC"))
HORIZONS = (1, 4, 24)
CONTROL_Q = (0.50, 0.52, 0.55, 0.60)
CONTROL_RATE = 0.02
CONTROL_H = 4


# ------------------------------------------------------------------ V1 / V2
def controls(L) -> pd.DataFrame:
    import fg_indicators as fg
    x = SR.EXITS[1]  # X2: stop 1.5 ATR, target 3 ATR
    cfg = L.ExitCfg(name=x[0], mode=x[1], sl_atr=x[2], tp_atr=x[3], trail_atr=x[4])
    parts = []
    for split in (*SR.SPLITS_IS, *SR.SPLITS_CONF):
        panel = L.load_panel("1h", split)
        for k, (coin, df) in enumerate(panel.items()):
            lo, hi = L.signal_window(df, "1h", split, SR.MAX_HOLD)
            c = df["close"].to_numpy(float)
            fwd = np.r_[c[CONTROL_H:], np.full(CONTROL_H, np.nan)] / c - 1  # deliberately uses the future
            atr = fg.atr(df, 14).to_numpy(float)
            ts = pd.to_datetime(df["ts"], utc=True).to_numpy()
            for q in CONTROL_Q:
                rng = np.random.default_rng([int(q * 100), k, len(split)])
                on = rng.random(len(df)) < CONTROL_RATE
                right = rng.random(len(df)) < q
                side = np.where(right, np.sign(fwd), -np.sign(fwd))
                side = np.where(on & np.isfinite(fwd), side, 0)
                t = L.run_backtest(df, atr, side > 0, side < 0, cfg, L._cost("1h", SR.MAX_HOLD), lo, hi)
                if len(t):
                    parts.append(t.assign(symbol=coin, entry=f"CONTROL_q{int(q * 100)}", exit=x[0], tf="1h",
                                          split=split, entry_ts=ts[t["entry_idx"].to_numpy(int)],
                                          exit_ts=ts[t["exit_idx"].to_numpy(int)]))
    res = SR.evaluate(pd.concat(parts, ignore_index=True))
    return res


# ------------------------------------------------------------------ V3 / V4
def hourly_table(coin: str, sym: str, root: str) -> pd.DataFrame:
    d = pd.read_csv(os.path.join(root, "full", f"{coin.lower()}-1h.csv"))
    d["t"] = pd.to_datetime(d["ts"], utc=True) + pd.Timedelta("1h")  # hour end
    px = d.set_index("t")["close"].astype(float)
    x = OF.hourly_features(sym).reindex(px.index)
    f = pd.DataFrame(index=px.index)
    ret1 = px.pct_change()
    f["price_ret_1h"] = ret1
    f["price_ret_24h"] = px.pct_change(24)
    f["funding"] = x["funding"]
    f["funding_rank"] = x["funding_rank"]
    f["oi_change_z"] = OF.rolling_z(x["oi"].pct_change(), OF.HOURS_30D)
    f["oi_change_24h"] = x["oi"].pct_change(24)
    f["retail_rank"] = OF.rolling_rank(x["retail_ls"], OF.HOURS_30D)
    f["top_minus_retail"] = OF.rolling_rank(x["top_ls"], OF.HOURS_30D) - f["retail_rank"]
    f["taker_z"] = OF.rolling_z(x["taker_1h"], OF.HOURS_30D)
    f["premium_rank"] = OF.rolling_rank(x["premium"], OF.HOURS_30D)
    for h in HORIZONS:
        f[f"fwd_{h}h"] = px.shift(-h) / px - 1
    f["abs_ret_1h"] = ret1.abs()
    f["coin"] = coin
    return f


FEATURES = ["price_ret_1h", "price_ret_24h", "funding", "funding_rank", "oi_change_z", "oi_change_24h",
            "retail_rank", "top_minus_retail", "taker_z", "premium_rank"]


def monthly_ic(tab: pd.DataFrame, feat: str, target: str, win) -> tuple[float, float, int]:
    """Mean over months of the cross-coin average Spearman IC; t-test across months."""
    t = tab[(tab.index >= win[0]) & (tab.index < win[1])][[feat, target, "coin"]].dropna()
    if len(t) < 1000:
        return np.nan, np.nan, 0
    per = []
    for (m, _c), g in t.groupby([t.index.to_period("M"), "coin"]):
        if len(g) >= 100:
            per.append((m, stats.spearmanr(g[feat], g[target]).statistic))
    s = pd.DataFrame(per, columns=["m", "ic"]).groupby("m")["ic"].mean()
    if len(s) < 6:
        return np.nan, np.nan, len(s)
    tt = s.mean() / (s.std(ddof=1) / np.sqrt(len(s)))
    return float(s.mean()), float(2 * stats.t.sf(abs(tt), len(s) - 1)), len(s)


def decile_spread(tab: pd.DataFrame, feat: str, target: str, win) -> float:
    """Half the top-minus-bottom decile mean forward return (a one-side gross edge), per coin, averaged."""
    t = tab[(tab.index >= win[0]) & (tab.index < win[1])][[feat, target, "coin"]].dropna()
    out = []
    for _c, g in t.groupby("coin"):
        if len(g) < 1000:
            continue
        lo, hi = g[feat].quantile([0.1, 0.9])
        out.append((g.loc[g[feat] >= hi, target].mean() - g.loc[g[feat] <= lo, target].mean()) / 2)
    return float(np.mean(out)) if out else np.nan


def info_tests(root: str) -> tuple[pd.DataFrame, dict]:
    tab = pd.concat([hourly_table(c, s, root) for c, s in OF.COIN_SYM.items()])
    rows = []
    for feat in FEATURES:
        for h in HORIZONS:
            tgt = f"fwd_{h}h"
            r = {"feature": feat, "horizon_h": h}
            for name, win in (("is", IS), ("cf", CF)):
                ic, p, nm = monthly_ic(tab, feat, tgt, win)
                r.update({f"{name}_ic": ic, f"{name}_p": p, f"{name}_months": nm,
                          f"{name}_decile_edge_pct": 100 * decile_spread(tab, feat, tgt, win)})
            rows.append(r)
    t = pd.DataFrame(rows)
    ok = t["is_p"].notna().to_numpy()
    t["is_bh"] = False
    t.loc[ok, "is_bh"] = SR.bh(t.loc[ok, "is_p"].to_numpy(), 0.10)
    t["same_sign_cf"] = np.sign(t["is_ic"]) == np.sign(t["cf_ic"])
    t["beats_cost"] = (t["is_decile_edge_pct"].abs() > 0.14) & (t["cf_decile_edge_pct"].abs() > 0.14) & \
        (np.sign(t["is_decile_edge_pct"]) == np.sign(t["cf_decile_edge_pct"]))
    # V4: contemporaneous checks (same hour)
    align = {}
    for name, a, b in (("taker_z_vs_same_hour_return", "taker_z", "price_ret_1h"),
                       ("oi_change_z_vs_same_hour_abs_return", "oi_change_z", "abs_ret_1h")):
        ic, p, nm = monthly_ic(tab, a, b, (IS[0], CF[1]))
        align[name] = {"ic": ic, "p": p, "months": nm}
    return t, align


# ------------------------------------------------------------------ V5
def independent_sim(L, entry: str = "H3A_RETAIL_FADE", sl: float = 1.5, tp: float = 3.0) -> dict:
    """Plain re-simulation of one config on the selection window without the locked engine."""
    import fg_indicators as fg
    panel = L.load_panel("1h", "is")
    feats = {c: OF.hourly_features(s) for c, s in OF.COIN_SYM.items()}
    nets = []
    for coin, df in panel.items():
        lo, hi = L.signal_window(df, "1h", "is", SR.MAX_HOLD)
        d1 = L.resample_ohlcv(df, "1h")
        close_1h = pd.Series(d1["close"].to_numpy(float), index=pd.to_datetime(d1["ts"], utc=True) + pd.Timedelta("1h"))
        sig = OF.to_chart(L, df, "1h", OF.hourly_conditions(feats[coin], close_1h))[entry]
        o, h, l_, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        atr = fg.atr(df, 14).to_numpy(float)
        i, free = max(lo, L.warmup_bars("1h")), -1
        while i < hi:
            s = sig[i]
            if s == 0 or i < free or not np.isfinite(atr[i]):
                i += 1
                continue
            e = o[i + 1]
            stop, targ = e - s * sl * atr[i], e + s * tp * atr[i]
            exit_px, j = None, i + 1
            for j in range(i + 1, min(i + 1 + SR.MAX_HOLD, len(c))):
                hit_sl = l_[j] <= stop if s > 0 else h[j] >= stop
                hit_tp = h[j] >= targ if s > 0 else l_[j] <= targ
                if hit_sl:
                    exit_px = min(o[j], stop) if s > 0 else max(o[j], stop)
                    break
                if hit_tp:
                    exit_px = targ
                    break
            if exit_px is None:
                exit_px = c[j]
            gross = s * (exit_px / e - 1)
            hours = j - i
            nets.append(gross - 0.0014 - 0.0001 * hours / 8)
            free = j
            i += 1
    y = np.array(nets)
    return {"n": int(len(y)), "mean_pct": float(100 * y.mean()), "win_pct": float(100 * (y > 0).mean())}


def run(scratch: str) -> None:
    L = SR.lib()
    os.makedirs(OUT, exist_ok=True)
    root = os.environ["SWEEP_DATA"]
    ctrl = controls(L)
    ctrl.to_csv(os.path.join(OUT, "controls.csv"), index=False)
    print(ctrl[["entry", "is_n", "is_win_pct", "is_mean_pct", "is_p", "is_coins_pos", "cf_mean_pct", "cf_pf",
                "bh_pass", "candidate"]].round(4).to_string(), flush=True)
    info, align = info_tests(root)
    info.to_csv(os.path.join(OUT, "information.csv"), index=False)
    pd.set_option("display.width", 250)
    print(info.round(4).to_string(), flush=True)
    print(json.dumps(align, indent=1), flush=True)
    ind = independent_sim(L)
    of = pd.read_csv(os.path.join(ROOT, "research/orderflow/out/results.csv"))
    row = of[(of["tf"] == "1h") & (of["entry"] == "H3A_RETAIL_FADE") & (of["exit"] == "X2_SL15_TP3")].iloc[0]
    v5 = {"independent": ind, "engine": {"n": int(row["is_n"]), "mean_pct": float(row["is_mean_pct"]),
                                         "win_pct": float(row["is_win_pct"])}}
    print(json.dumps(v5, indent=1))
    with open(os.path.join(OUT, "alignment_and_resim.json"), "w") as fh:
        json.dump({"alignment": align, "resim": v5}, fh, indent=1)


if __name__ == "__main__":
    run(sys.argv[2])

"""Self-check (task deliverable 3) and code parity checks.

1. common.scan (with default arguments) == lens2_multi_tf_done/precompute.scan on random BTC / DOGE 15m entries.
2. The default S2_ST_ROC signal on the 15m series from 2021-01 (as the binance cache was built) equals the cache's
   s__S2_ST_ROC column (locked code), per coin, on the bars both hold.
3. Default S2_ST_ROC 15m, 6 coins, signal bars 2021-08-02 .. 2026-09-28 (the custom_values OOS weeks):
   a) this study's house exits on this study's per-period signals (SEARCH + TEST stage-2 lists);
   b) the same signals with the custom_values exit geometry (20x ladder for every signal, no liquidation, trades
      closed within 4,096 bars), to separate the exit-model difference from the signal difference;
   c) the signals of the continuous series from 2021-01 (the cache's) with the custom_values geometry.
   Known value: -0.1645 R over 94,310 trades (lens2_custom_values out_R2/cell_desc.csv).

    python3 -B research/st_custom/selfcheck.py
"""
import importlib.util
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import numpy as np  # noqa: E402
import s2_signals as S2  # noqa: E402

PRE = os.path.join(C.REPO, "analysis/rulebot_1007/pending_1007_night/lens2_multi_tf_done/precompute.py")
CACHE = os.path.join(C.SCR, "binance", "signals")
COINS6 = C.COINS[:6]
A, B = C.ts_ns("2021-08-02"), C.ts_ns("2026-09-28")
STRAT = "S2_ST_ROC"
DEF = C.combo_index(STRAT, C.DEFAULT_IDX[STRAT])


def load_pre():
    spec = importlib.util.spec_from_file_location("_pre_lens2", PRE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def parity_scan(out):
    P = load_pre()
    rng = np.random.default_rng(7)
    res = {}
    for coin in ("BTCUSD", "DOGEUSD"):
        b15 = C.load_bars(coin, "15m")
        O = np.load(os.path.join(C.OUTC_DIR, f"{coin}_15m.npz"))
        ok = np.flatnonzero(O["valid"])
        idx = np.sort(rng.choice(ok, 4000, replace=False))
        e = O["e"][idx].astype(np.int64)
        atr = O["atr"][idx]
        side = np.where(rng.random(len(idx)) < 0.5, 1, -1)
        lev, liq, _f = C.lev_liq(coin, side, atr / b15["o"][e])
        a = P.scan(b15, e, side, lev, liq, atr, 96, C.F_BAR15)
        b = C.scan(b15, e, side, lev, liq, C.K_STOP * atr, 96, C.F_BAR15)
        diff = {k: float(np.nanmax(np.abs(np.asarray(a[k], float) - np.asarray(b[k], float)))) for k in
                ("x", "R", "gross", "roe", "reason")}
        # and the stored stage-1 table (multi-pass) against precompute.scan with a long horizon on those rows
        R_tab = np.where(side > 0, O["R_0"][idx], O["R_1"][idx])
        done = a["done"]
        diff["stage1_vs_precompute_R_done_rows"] = float(np.nanmax(np.abs(R_tab[done] - a["R"][done])))
        res[coin] = diff
    out["scan_parity"] = res


def parity_cache(out):
    """Default S2 signal from the continuous 2021-01 series == the binance cache column."""
    res = {}
    for coin in COINS6:
        z = np.load(os.path.join(CACHE, f"sig_15m_{coin}.npz"))
        b = C.load_bars(coin, "15m")
        k0 = int(np.searchsorted(b["ts"], z["ts"][0]))
        df = C.frame(b, "15m", k0, len(b["ts"]))
        sig = C.combo_signal(STRAT, DEF, df, "15m")
        ts = b["ts"][k0:]
        common = np.intersect1d(ts, z["ts"])
        ia = np.searchsorted(ts, common)
        ib = np.searchsorted(z["ts"], common)
        ref = np.sign(z["s__S2_ST_ROC"][ib]).astype(np.int8)
        res[coin] = dict(bars_common=int(len(common)), bars_only_here=int(len(ts) - len(common)),
                         bars_only_cache=int(len(z["ts"]) - len(common)),
                         signal_mismatch=int((sig[ia] != ref).sum()), signals=int((ref != 0).sum()))
    out["cache_parity_default_S2_15m"] = res
    return res


def summary(R, G):
    R, G = np.asarray(R, float), np.asarray(G, float)
    return dict(trades=int(len(R)), mean_net_R=round(float(R.mean()), 4), mean_gross_R=round(float(G.mean()), 4),
                mean_cost_R=round(float((G - R).mean()), 4), win_rate=round(float((R > 0).mean()), 4))


def lens2_geometry(coin, gi, sd, bt, O):
    """custom_values exit: 20x ladder for every signal, no liquidation, 15m own bars, passes 64/512/4096,
    trades not closed within 4,096 bars dropped."""
    b15 = C.load_bars(coin, "15m")
    e = O["e"][gi].astype(np.int64)
    atr = O["atr"][gi]
    lev = np.full(len(gi), 20.0)
    liq = np.full(len(gi), 10.0)
    r = C.run_scan(b15, e, sd.astype(np.int64), lev, liq, C.K_STOP * atr, passes=(64, 512, 4096))
    keep = r["done"]
    return r["R"][keep], r["gross"][keep], int((~keep).sum())


def selfcheck(out):
    rows = {"this_study_house": ([], []), "lens2_geometry_same_signals": ([], []),
            "lens2_geometry_cache_signals": ([], [])}
    dropped = {"this_study_not_closed": 0, "lens2_not_within_4096": 0, "lens2_cache_not_within_4096": 0}
    per_coin = {}
    for coin in COINS6:
        bt = C.load_bars(coin, "15m")
        O = np.load(os.path.join(C.OUTC_DIR, f"{coin}_15m.npz"))
        O = {k: O[k] for k in O.files}
        gis, sds = [], []
        for per in ("SEARCH", "TEST"):
            codes, offs = C.load_signals(S2.sig_path(coin, "15m", per), STRAT)
            lo = int(np.load(S2.sig_path(coin, "15m", per))["lo"][0])
            cc = codes[offs[DEF]:offs[DEF + 1]]
            gis.append(lo + cc // 2)
            sds.append(np.where(cc % 2 == 1, 1, -1))
        gi = np.concatenate(gis)
        sd = np.concatenate(sds)
        t = bt["ts"][gi]
        m = (t >= A) & (t < B)
        gi, sd = gi[m], sd[m]
        si = np.where(sd > 0, 0, 1)
        R = np.where(si == 0, O["R_0"][gi], O["R_1"][gi])
        G = np.where(si == 0, O["gross_0"][gi], O["gross_1"][gi])
        rs = np.where(si == 0, O["reason_0"][gi], O["reason_1"][gi])
        ok = rs != 3
        dropped["this_study_not_closed"] += int((~ok).sum())
        rows["this_study_house"][0].append(R[ok])
        rows["this_study_house"][1].append(G[ok])
        R2, G2, nd = lens2_geometry(coin, gi, sd, bt, O)
        dropped["lens2_not_within_4096"] += nd
        rows["lens2_geometry_same_signals"][0].append(R2)
        rows["lens2_geometry_same_signals"][1].append(G2)
        # cache signals (continuous series from 2021-01)
        z = np.load(os.path.join(CACHE, f"sig_15m_{coin}.npz"))
        s = np.sign(z["s__S2_ST_ROC"])
        tz = z["ts"]
        mm = (s != 0) & (tz >= A) & (tz < B)
        gi_c = np.searchsorted(bt["ts"], tz[mm])
        okc = (gi_c < len(bt["ts"]))
        okc[okc] &= bt["ts"][gi_c[okc]] == tz[mm][okc]
        gi_c = gi_c[okc]
        sd_c = s[mm][okc].astype(np.int64)
        v = O["valid"][gi_c]
        R3, G3, nd3 = lens2_geometry(coin, gi_c[v], sd_c[v], bt, O)
        dropped["lens2_cache_not_within_4096"] += nd3
        rows["lens2_geometry_cache_signals"][0].append(R3)
        rows["lens2_geometry_cache_signals"][1].append(G3)
        per_coin[coin] = dict(this_study=summary(R[ok], G[ok]), lens2_geometry=summary(R2, G2),
                              lens2_cache=summary(R3, G3), signals_here=int(len(gi)), signals_cache=int(len(gi_c)),
                              feasible_share=float(np.where(si == 0, O["feas_0"][gi], O["feas_1"][gi]).mean()),
                              lev30_share=float((np.where(si == 0, O["lev_0"][gi], O["lev_1"][gi]) == 30).mean()))
    res = {k: summary(np.concatenate(a), np.concatenate(b)) for k, (a, b) in rows.items()}
    out["selfcheck"] = dict(window="signal bars 2021-08-02 .. 2026-09-28 (UTC), 6 coins, S2_ST_ROC default 15m",
                            known=dict(trades=94310, mean_net_R=-0.1645, mean_gross_R=0.0118, mean_cost_R=0.1764,
                                       source="lens2_custom_values_done/out_R2/cell_desc.csv"),
                            results=res, dropped=dropped, per_coin=per_coin)
    for k, v in res.items():
        C.log(k, v)
    C.log(dropped)


if __name__ == "__main__":
    out = {"prereg": C.check_prereg()}
    parity_scan(out)
    C.log(out["scan_parity"])
    C.log(parity_cache(out))
    selfcheck(out)
    C.save_json(os.path.join(C.OUT, "selfcheck.json"), out)

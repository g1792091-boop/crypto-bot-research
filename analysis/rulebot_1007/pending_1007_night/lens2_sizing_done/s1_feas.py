"""Q1: loss per stop-out (% of equity) and executability per leverage, sizing rule, tf, coin.

    python3 -I -B s1_feas.py <workdir> <fy36_dir> <replay_signals.csv> <out_dir>

Sources: 5y = every signal of the 36 locked strategies 2021-08-01..2026-09-30 (fy36_<tf>.pkl.gz, lens/fiveyear),
         5y_last30 = its last 30 days (2026-08-31..09-30), live = every SUBMITTED signal of the v3b + v4 runs
         (rb_analyze replay_signals.csv, kinds strategy + ds200, stop_frac and atr / ref_price as recorded).
"""
import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
sys.path.append("/root/.local/lib/python3.11/site-packages")
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import common as C  # noqa: E402

FY, RPS, OUT = sys.argv[2], sys.argv[3], sys.argv[4]
os.makedirs(OUT, exist_ok=True)
TFS = ("15m", "30m", "1h", "4h")
RISKS = (0.01, 0.02, 0.03, 0.05)


def load():
    fr = []
    for tf in TFS:
        d = pd.read_pickle(os.path.join(FY, f"fy36_{tf}.pkl.gz"))[["coin", "tf", "ts", "side", "stop_frac"]]
        d["coin"] = d["coin"].astype(str).map(C.coin_key)
        d["tf"] = tf
        d["a"] = C.atr_from_stop(d["stop_frac"], d["side"])
        d["src"] = "5y"
        fr.append(d)
        last = d[d.ts >= pd.Timestamp("2026-08-31").value].copy()
        last["src"] = "5y_last30"
        fr.append(last)
    rp = pd.read_csv(RPS)
    rp = rp[rp.kind.isin(["strategy", "ds200"]) & rp.timeframe.isin(TFS) & rp.stop_frac.notna()]
    lv = pd.DataFrame(dict(coin=rp.symbol.map(C.coin_key), tf=rp.timeframe, ts=rp.bar_close, side=rp.side,
                           stop_frac=rp.stop_frac, a=rp.atr / rp.ref_price, src="live"))
    fr.append(lv)
    return pd.concat(fr, ignore_index=True)


def stats(g, coin):
    side, d, a = g.side.to_numpy(), g.stop_frac.to_numpy(float), g.a.to_numpy(float)
    row = dict(n=len(g), stop_med=np.median(d), stop_p10=np.quantile(d, .1), stop_p90=np.quantile(d, .9))
    used_best = np.zeros(len(g)); used_norm = np.zeros(len(g)); loss_best = np.full(len(g), np.nan)
    loss_norm = np.full(len(g), np.nan)
    for L in (50, 40, 30, 20):          # walk-down as live quality_v1 (best 50,40 then normal 30,20)
        m = C.margin_rule(coin, side, d, a, L)
        sel = (used_best == 0) & m["ok"]
        used_best[sel] = L; loss_best[sel] = m["lossf"][sel]
        if L <= 30:
            sel = (used_norm == 0) & m["ok"]
            used_norm[sel] = L; loss_norm[sel] = m["lossf"][sel]
    for L in C.LEVS:
        m = C.margin_rule(coin, side, d, a, L)
        row[f"M{L}_ok"] = m["ok"].mean()
        row[f"M{L}_room_ok"] = m["room_ok"].mean()
        row[f"M{L}_br_ok"] = m["br_ok"].mean()
        row[f"M{L}_loss_ok"] = m["loss_ok"].mean()
        row[f"M{L}_loss_med"] = np.median(m["lossf"])
        row[f"M{L}_loss_p90"] = np.quantile(m["lossf"], .9)
        row[f"M{L}_liq_med"] = np.median(m["liq"])
        for r in RISKS:
            k = C.risk_rule(coin, side, d, a, L, r)
            row[f"R{int(r*100)}_{L}_ok"] = k["ok"].mean()
            if r == 0.02:
                row[f"R2_{L}_room_ok"] = k["room_ok"].mean()
                row[f"R2_{L}_margin_med"] = np.median(k["margin_frac"])
                row[f"R2_{L}_liq_med"] = np.median(k["liq"])
    # risk rule: highest leverage of 50,40,30,20 whose stop fits (r = 2%); share needing < 20x
    hi = np.zeros(len(g))
    for L in (20, 30, 40, 50):
        k = C.risk_rule(coin, side, d, a, L, 0.02)
        hi[k["ok"]] = L
    for L in (50, 40, 30, 20):
        row[f"R2_max{L}_share"] = (hi == L).mean()
    row["R2_none20_share"] = (hi == 0).mean()
    for L in (50, 40, 30, 20):
        row[f"Mbest_used{L}"] = (used_best == L).mean()
        if L <= 30:
            row[f"Mnorm_used{L}"] = (used_norm == L).mean()
    row["Mbest_rejected"] = (used_best == 0).mean()
    row["Mnorm_rejected"] = (used_norm == 0).mean()
    row["Mbest_loss_med"] = np.nanmedian(loss_best) if np.isfinite(loss_best).any() else np.nan
    row["Mnorm_loss_med"] = np.nanmedian(loss_norm) if np.isfinite(loss_norm).any() else np.nan
    row["Mnorm_loss_p90"] = np.nanquantile(loss_norm, .9) if np.isfinite(loss_norm).any() else np.nan
    return row


def main():
    df = load()
    rows = []
    for (src, tf, coin), g in df.groupby(["src", "tf", "coin"]):
        rows.append(dict(src=src, tf=tf, coin=coin, **stats(g, coin)))
    out = pd.DataFrame(rows)
    # pooled over coins: signal-weighted mean of the per-coin shares, medians recomputed approx by weighting
    pool = []
    for (src, tf), g in out.groupby(["src", "tf"]):
        w = g.n / g.n.sum()
        r = dict(src=src, tf=tf, coin="ALL", n=int(g.n.sum()))
        for c in g.columns[4:]:
            r[c] = float((g[c] * w).sum())
        sub = df[(df.src == src) & (df.tf == tf)]
        r["stop_med"] = sub.stop_frac.median()
        r["stop_p10"] = sub.stop_frac.quantile(.1)
        r["stop_p90"] = sub.stop_frac.quantile(.9)
        pool.append(r)
    out = pd.concat([pd.DataFrame(pool), out], ignore_index=True)
    out.to_csv(os.path.join(OUT, "s1_feasibility.csv"), index=False)
    # by year (5y), pooled coins
    df5 = df[df.src == "5y"].copy()
    df5["year"] = pd.to_datetime(df5.ts).dt.year
    yr = []
    for (tf, y, coin), g in df5.groupby(["tf", "year", "coin"]):
        s = stats(g, coin)
        yr.append(dict(tf=tf, year=y, coin=coin, **{k: s[k] for k in ("n", "stop_med", "M20_ok", "M30_ok", "M40_ok",
                                                                         "M50_ok", "M20_room_ok", "R2_20_ok",
                                                                         "R2_50_ok", "M30_loss_med", "R2_none20_share")}))
    yr = pd.DataFrame(yr)
    agg = yr.groupby(["tf", "year"]).apply(lambda g: pd.Series({c: np.average(g[c], weights=g.n) for c in yr.columns[3:]}
                                                              | {"n": g.n.sum()}), include_groups=False).reset_index()
    agg.to_csv(os.path.join(OUT, "s1_feasibility_by_year.csv"), index=False)
    cols = ["src", "tf", "coin", "n", "stop_med", "M20_ok", "M30_ok", "M40_ok", "M50_ok", "M20_loss_med", "M30_loss_med",
            "M40_loss_med", "M50_loss_med", "Mnorm_loss_med", "Mbest_rejected", "Mnorm_rejected", "R2_20_ok", "R2_30_ok",
            "R2_40_ok", "R2_50_ok", "R2_none20_share", "R2_50_margin_med"]
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    print(out[out.coin == "ALL"][cols].round(4).to_string(index=False))
    print(agg.round(3).to_string(index=False))


main()

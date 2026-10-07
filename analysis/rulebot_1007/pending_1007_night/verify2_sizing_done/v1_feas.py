"""Independent check of Z1/Z2/Z10: brackets from live liq prices, loss per stop-out, executability.

python3 -I -B v1_feas.py <export_dir> <out_real_dir> <fy36_dir> <out_dir>
Own implementation (does not import lens2/sizing/common.py). Repo read-only.
"""
import os
import re
import sys

sys.dont_write_bytecode = True
sys.path.append('/root/.local/lib/python3.11/site-packages')
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

EXP, OR, FY, OUT = sys.argv[1:5]
os.makedirs(OUT, exist_ok=True)
TAKER, SLIP, E0 = 0.0005, 0.0002, 5000.0
RUNS = ["run-20261005T014624Z", "run-20261005T183457Z", "current"]
res = {}

# ---------------------------------------------------------------- 1. brackets from live liq prices
tr = pd.concat([pd.read_csv(os.path.join(EXP, r, "trades.csv"), usecols=lambda c: c != "context").assign(run=r)
                for r in RUNS], ignore_index=True)
tr["coin"] = tr.symbol.str.replace("USDT", "")
tr["notional"] = tr.qty * tr.entry_price
# y = WB - side*Q*(EP-LP) = mmr*Q*LP - cum
tr["x"] = tr.qty * tr.liq_price
tr["y"] = tr.margin - tr.side * tr.qty * (tr.entry_price - tr.liq_price)
tr["mmr0"] = tr.y / tr.x
fit = []
for coin, g in tr[tr.liq_price > 0].groupby("coin"):
    # cluster by implied mmr (cum = 0) in tier 1; trades whose mmr0 deviates belong to higher tiers
    m1 = np.round(g.mmr0.min(), 5)
    t1 = g[np.abs(g.mmr0 - m1) < 1e-7]
    hi = g[np.abs(g.mmr0 - m1) >= 1e-7]
    row = dict(coin=coin, n=len(g), tier1_mmr=m1, tier1_n=len(t1), tier1_max_notional=t1.notional.max(),
               higher_min_notional=hi.notional.min() if len(hi) else np.nan, higher_n=len(hi))
    if len(hi) >= 3:
        # least squares y = mmr*x - cum on higher-tier trades; split if residual large
        A = np.c_[hi.x, -np.ones(len(hi))]
        sol, *_ = np.linalg.lstsq(A, hi.y, rcond=None)
        resid = hi.y - A @ sol
        row.update(t2_mmr=sol[0], t2_cum=sol[1], t2_maxabs_resid=np.abs(resid).max(),
                   t2_max_notional=hi.notional.max())
        if np.abs(resid).max() > 0.01:
            # two clusters: split at the notional gap that minimises residual
            best = None
            hs = hi.sort_values("notional")
            for k in range(3, len(hs) - 2):
                a, b = hs.iloc[:k], hs.iloc[k:]
                rr = []
                sols = []
                for part in (a, b):
                    AA = np.c_[part.x, -np.ones(len(part))]
                    s_, *_ = np.linalg.lstsq(AA, part.y, rcond=None)
                    rr.append(np.abs(part.y - AA @ s_).max())
                    sols.append(s_)
                if best is None or max(rr) < best[0]:
                    best = (max(rr), k, sols, a.notional.max(), b.notional.min())
            row.update(split_resid=best[0], t2_mmr=best[2][0][0], t2_cum=best[2][0][1], t2_upto=best[3],
                       t3_from=best[4], t3_mmr=best[2][1][0], t3_cum=best[2][1][1])
    fit.append(row)
fit = pd.DataFrame(fit)
fit.to_csv(os.path.join(OUT, "v1_brackets_fit.csv"), index=False)
print(fit.round(6).to_string(index=False))

# bracket max-leverage caps from rejection texts
cap = []
for r in RUNS:
    oc = pd.read_csv(os.path.join(EXP, r, "outcomes.csv"))
    col = [c for c in oc.columns if oc[c].astype(str).str.contains("bracket allows").any()]
    for c in col:
        s = oc[oc[c].astype(str).str.contains("bracket allows")]
        for sym, txt in zip(s.symbol if "symbol" in s else [""] * len(s), s[c].astype(str)):
            for m in re.finditer(r"(\w+)/(\d+)x: bracket allows (\d+)x", txt):
                cap.append(dict(run=r, symbol=sym, tier=m.group(1), lev=int(m.group(2)), allows=int(m.group(3))))
cap = pd.DataFrame(cap)
if len(cap):
    print(cap.groupby(["symbol", "lev", "allows"]).size().to_string())

# my bracket table (from the fit above; cross-checked against the printed fit, filled in by hand below)
BR = {}


def set_br(fitdf):
    for _, r in fitdf.iterrows():
        t = [(r.tier1_max_notional if np.isfinite(r.higher_min_notional) else 1e12, 50, r.tier1_mmr, 0.0)]
        BR[r.coin] = t
    return BR


# ---------------------------------------------------------------- 2. loss per stop-out: realised live SL exits
te = pd.read_csv(os.path.join(OR, "trades_enriched.csv"))
te = te[te.kind == "strategy"]
sl = te[te.exit_reason == "SL"].copy()
sl["loss_pct"] = -sl.pnl / sl.eq_before * 100
g = sl.groupby(["timeframe", "leverage"]).loss_pct.agg(["size", "median", "max"]).reset_index()
g = g[g["size"] >= 10]
g.to_csv(os.path.join(OUT, "v1_live_sl.csv"), index=False)
print(g.round(2).to_string(index=False))


# ---------------------------------------------------------------- 3. formula from stop distributions
def lpn(d):
    stop = 1 - d
    ex = stop * (1 - SLIP)
    return d + (stop - ex) + TAKER + ex * TAKER


def bracket(coin, n):
    tiers = BRK[coin]
    ml, mmr, cum = np.zeros_like(n), np.zeros_like(n), np.zeros_like(n)
    done = np.zeros(n.shape, bool)
    for capn, lev, m, c in tiers:
        s = (~done) & (n <= capn)
        ml[s], mmr[s], cum[s] = lev, m, c
        done |= s
    return ml, mmr, cum


def liqdist(side, n, margin, mmr, cum):
    # own derivation: fill=1, Q=n. LP = (WB + cum - side*Q)/(Q*mmr - side*Q). distance = side*(1-LP)
    lp = (margin + cum - side * n) / (n * mmr - side * n)
    lp = np.maximum(lp, 0)
    return side * (1 - lp)


def feas(coin, side, d, a, L, rule, r=0.02):
    n = (L * L / 100 * E0) if rule == "M" else r * E0 / lpn(d)
    n = np.broadcast_to(n, d.shape).astype(float)
    margin = n / L
    ml, mmr, cum = bracket(coin, n)
    lq = liqdist(side, n, margin, mmr, cum)
    buf = np.maximum(a, 0.002)
    ok = (ml >= L) & (lq - d >= buf) & (margin <= E0)
    lossf = n * lpn(d) / E0
    if rule == "M":
        ok &= lossf <= 0.15
    return ok, lq, lossf


fr = []
for tf in ("15m", "30m", "1h", "4h"):
    d = pd.read_pickle(os.path.join(FY, f"fy36_{tf}.pkl.gz"))[["coin", "ts", "side", "stop_frac", "v4n_lev",
                                                                  "tw_lev"]]
    d["coin"] = d.coin.astype(str).str.replace("USD", "")
    d["tf"] = tf
    # ATR / raw from fy36 definition stop_frac = (raw*slip + 2 atr)/(raw*(1+side*slip))
    d["a"] = (d.stop_frac.astype(float) * (1 + d.side * SLIP) - SLIP) / 2
    d["src"] = "5y"
    fr.append(d)
rp = pd.read_csv(os.path.join(OR, "replay_signals.csv"))
rp = rp[rp.kind.isin(["strategy", "ds200"]) & rp.timeframe.isin(["15m", "30m", "1h", "4h"])]
rp["a"] = rp.atr / rp.ref_price
# recompute stop_frac for EVERY submitted signal (incl. REJECTED_SIZING / UNRESOLVED): fill = ref*(1+side*slip)
fill = rp.ref_price * (1 + rp.side * SLIP)
rp["sf_all"] = (rp.ref_price * SLIP + 2 * rp.atr) / fill
chk = rp[rp.stop_frac.notna()]
print("live stop_frac recompute max abs diff", float(np.abs(chk.sf_all - chk.stop_frac).max()),
      "median rel", float(np.median(np.abs(chk.sf_all / chk.stop_frac - 1))))
lv = pd.DataFrame(dict(coin=rp.symbol.str.replace("USDT", ""), ts=rp.bar_close, side=rp.side, stop_frac=rp.sf_all,
                       tf=rp.timeframe, a=rp.a, src=np.where(rp.stop_frac.notna(), "live_traded", "live_other"),
                       status=rp.status))
fr.append(lv)
df = pd.concat(fr, ignore_index=True)
df = df[df.stop_frac.notna()]
res["df"] = df

BRK = {
    "BTC": [(1e12, 50, 0.004, 0.0)], "ETH": [(1e12, 50, 0.004, 0.0)],
    "SOL": [(50_000, 50, 0.005, 0.0), (1e12, 50, 0.0065, 75.0)],
    "DOGE": [(80_000, 50, 0.0065, 0.0), (1e12, 50, 0.01, 280.0)],
    "BCH": [(10_000, 50, 0.005, 0.0), (100_000, 50, 0.01, 50.0), (1e12, 40, 0.0125, 300.0)],
    "LTC": [(10_000, 50, 0.005, 0.0), (50_000, 50, 0.01, 50.0), (1e12, 40, 0.015, 300.0)],
}
if len(sys.argv) > 5:
    exec(open(sys.argv[5]).read())  # optional bracket override written after reading the fit

rows = []
for src_sel, name in ((["5y"], "5y"), (["live_traded"], "live_traded_only"), (["live_traded", "live_other"], "live_all")):
    for tf in ("15m", "30m", "1h", "4h"):
        s = df[df.src.isin(src_sel) & (df.tf == tf)]
        if not len(s):
            continue
        row = dict(src=name, tf=tf, n=len(s), stop_med=s.stop_frac.median())
        for L in (20, 30, 40, 50):
            okM = np.zeros(len(s), bool); okR = np.zeros(len(s), bool); lossM = np.zeros(len(s))
            liq_lt_stop = np.zeros(len(s), bool)
            for coin in s.coin.unique():
                m = (s.coin == coin).values
                sd, sa, ss = s.stop_frac.values[m].astype(float), s.a.values[m].astype(float), s.side.values[m]
                o, lq, lf = feas(coin, ss, sd, sa, L, "M")
                okM[m], lossM[m] = o, lf
                o2, lq2, _ = feas(coin, ss, sd, sa, L, "R")
                okR[m] = o2
                liq_lt_stop[m] = lq2 < sd
            row[f"M{L}_loss_med_pct"] = np.median(lossM) * 100
            row[f"M{L}_ok"] = okM.mean() * 100
            row[f"R2_{L}_ok"] = okR.mean() * 100
            row[f"R2_{L}_stop_beyond_liq"] = liq_lt_stop.mean() * 100
        if name == "5y":
            row["repo_v4n_sized"] = (s.v4n_lev > 0).mean() * 100
            row["repo_v4n_30x"] = (s.v4n_lev == 30).mean() * 100
        if name == "live_all":
            st = rp[rp.timeframe == tf].status.value_counts()
            row["live_status"] = " ".join(f"{k}:{v}" for k, v in st.items())
        rows.append(row)
out = pd.DataFrame(rows)
out.to_csv(os.path.join(OUT, "v1_feas.csv"), index=False)
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 50)
print(out.round(2).to_string(index=False))

# margin-rule walk 30->20 with my code vs repo v4n (example brackets!)
s = df[(df.src == "5y")]
for tf in ("15m", "4h"):
    q = s[s.tf == tf]
    print(tf, "repo v4n 30x", round((q.v4n_lev == 30).mean() * 100, 2), "20x", round((q.v4n_lev == 20).mean() * 100, 2))

# coin split, risk 2% at 50x, 5y 15m; and by year
q = s[s.tf == "15m"].copy()
okc = {}
for coin in q.coin.unique():
    m = q.coin == coin
    o, _, _ = feas(coin, q.side.values[m.values], q.stop_frac.values[m.values].astype(float), q.a.values[m.values], 50, "R")
    okc[coin] = round(o.mean() * 100, 1)
    o5, _, _ = feas(coin, q.side.values[m.values], q.stop_frac.values[m.values].astype(float), q.a.values[m.values], 50,
                    "R", r=0.05)
    okc[coin + "_r5"] = round(o5.mean() * 100, 1)
    oM, _, _ = feas(coin, q.side.values[m.values], q.stop_frac.values[m.values].astype(float), q.a.values[m.values], 50, "M")
    okc[coin + "_M50"] = round(oM.mean() * 100, 1)
print("15m 50x by coin", okc)
q["year"] = pd.to_datetime(q.ts).dt.year
ok50 = np.zeros(len(q), bool)
for coin in q.coin.unique():
    m = (q.coin == coin).values
    ok50[m] = feas(coin, q.side.values[m], q.stop_frac.values[m].astype(float), q.a.values[m], 50, "R")[0]
q["ok50"] = ok50
print("15m R2 50x by year", (q.groupby("year").ok50.mean() * 100).round(1).to_dict())
# 4h by coin at 20x (risk rule) 5y
q = s[s.tf == "4h"]
o4 = {}
for coin in q.coin.unique():
    m = (q.coin == coin).values
    o4[coin] = round(feas(coin, q.side.values[m], q.stop_frac.values[m].astype(float), q.a.values[m], 20, "R")[0].mean()
                     * 100, 1)
print("4h R2 20x by coin", o4)

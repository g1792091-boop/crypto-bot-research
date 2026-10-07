"""verify3: skipped-vs-entered selection, big-move hours, agreement, pooled OPP.
python3 -I v3ev.py <v3sig.csv> <export_dir>"""
import sys, site
sys.path.append(site.getusersitepackages())
sys.path.insert(0, "/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/lens/ai_upside/verify3")
import numpy as np, pandas as pd
from v3st_lib import ctest

MIN, H = 60_000, 3_600_000
TFM = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
RUN = {"v3b": "run-20261005T183457Z", "v4": "current"}
R = pd.read_csv(sys.argv[1])
R = R[R["base_st"].isin(["T", "U"])].copy()
R["cl"] = R["run"] + "|" + (R["bar_close"] // (np.maximum(R["timeframe"].map(TFM), 60) * MIN)).astype(str)
R["aid"] = R["strategy"] + "@" + R["timeframe"]
outs, sigl, bars = [], [], []
for r, n in RUN.items():
    o = pd.read_csv(f"{sys.argv[2]}/{n}/outcomes.csv", usecols=["account_id", "sig_ts", "symbol", "status", "reason"])
    o["run"] = r; outs.append(o)
    s = pd.read_csv(f"{sys.argv[2]}/{n}/signal_log.csv", usecols=["bar_close", "symbol", "side", "strategy", "timeframe", "status"])
    s["run"] = r; sigl.append(s)
    b = pd.read_csv(f"{sys.argv[2]}/{n}/live_bars.csv", usecols=["ts", "symbol", "open", "close"])
    b["run"] = r; bars.append(b)
O = pd.concat(outs).drop_duplicates(["run", "account_id", "sig_ts", "symbol"])
R["sig_ts"] = R["bar_close"] - 1
R = R.merge(O.rename(columns={"account_id": "aid"}), on=["run", "aid", "sig_ts", "symbol"], how="left")
print("== skipped(in position) vs entered, alone R (selection check)")
for (k, tf), g in R[R.kind.isin(["strategy", "ds200"]) & R.timeframe.isin(["15m", "30m", "1h"])].groupby(["kind", "timeframe"]):
    e = g[g.status == "ENTERED"].base_R; s = g[(g.status == "SKIPPED") & (g.reason == "in position")].base_R
    print(f"{k} {tf}: entered n={len(e)} {e.mean():+.3f} | skipped-in-pos n={len(s)} {s.mean():+.3f}  by run skipped:",
          g[(g.status == "SKIPPED") & (g.reason == "in position")].groupby("run").base_R.mean().round(3).to_dict())
print("== big-move hours (6-coin mean |1h return|, top decile per run)")
B = pd.concat(bars)
B["h"] = B.ts // H
hr = B.groupby(["run", "symbol", "h"]).agg(o=("open", "first"), c=("close", "last")).reset_index()
hr["ret"] = hr.c / hr.o - 1
hh = hr.groupby(["run", "h"]).ret.mean().reset_index()
hh["big"] = hh.groupby("run").ret.transform(lambda x: x.abs() >= x.abs().quantile(0.9))
big = set(map(tuple, hh[hh.big][["run", "h"]].to_numpy()))
print("big hours per run:", hh[hh.big].groupby("run").size().to_dict())
R["eh"] = (R.bar_close // H)
R["grp"] = np.where([(a, b) in big for a, b in zip(R.run, R.eh)], "in",
                    np.where([(a, b - 1) in big for a, b in zip(R.run, R.eh)], "after", "other"))
for k in ("strategy", "ds200"):
    g = R[R.kind == k]
    t = g.groupby(["run", "grp"]).agg(n=("base_R", "size"), R=("base_R", "mean"), ncl=("eh", "nunique")).round(3)
    print(k); print(t.to_string())
print("== agreement, AI-visible window [bc-15m, bc] (SUBMITTED signals of other accounts, same coin)")
SG = pd.concat(sigl)
SG = SG[SG.status == "SUBMITTED"]
SGd = {key: g for key, g in SG.groupby(["run", "symbol"])}
ns, no = [], []
for r in R[["run", "symbol", "bar_close", "side", "strategy", "timeframe"]].itertuples(index=False):
    g = SGd.get((r.run, r.symbol))
    m = (g.bar_close >= r.bar_close - 15 * MIN) & (g.bar_close <= r.bar_close) & ~((g.strategy == r.strategy) & (g.timeframe == r.timeframe))
    ns.append(int((m & (g.side == r.side)).sum())); no.append(int((m & (g.side != r.side)).sum()))
R["ns"], R["no"] = ns, no
R["ag"] = np.where((R.ns == 0) & (R.no == 0), "alone", np.where(R.ns > R.no, "agree", "conflict"))
for k, tf in (("strategy", "15m"), ("strategy", "30m"), ("strategy", "1h"), ("ds200", "15m")):
    g = R[(R.kind == k) & (R.timeframe == tf)]
    a, c = g[g.ag == "agree"], g[g.ag == "conflict"]
    x = pd.concat([a.assign(v=-1.0 * 0 + 0), c])
    d = c.base_R.mean() - a.base_R.mean()
    # cluster bootstrap of the difference
    cls = g.cl.unique(); rng = np.random.default_rng(3); bs = []
    gi = {cc: gg for cc, gg in g[g.ag.isin(["agree", "conflict"])].groupby("cl")}
    keys = list(gi)
    for _ in range(1000):
        s = pd.concat([gi[keys[j]] for j in rng.integers(0, len(keys), len(keys))])
        bs.append(s[s.ag == "conflict"].base_R.mean() - s[s.ag == "agree"].base_R.mean())
    byrun = {rr: round(gg[gg.ag == "conflict"].base_R.mean() - gg[gg.ag == "agree"].base_R.mean(), 3) for rr, gg in g.groupby("run")}
    print(f"{k} {tf}: agree n={len(a)} conflict n={len(c)} diff={d:+.3f} CI[{np.nanpercentile(bs,2.5):+.3f},{np.nanpercentile(bs,97.5):+.3f}] by run {byrun}")
print("== AIH-13 pooled non-random 15m OPP/OPPH")
g = R[R.kind.isin(["strategy", "ds200"]) & (R.timeframe == "15m")]
for r in ("OPP", "OPPH"):
    d = (g[f"{r}_R"] - g.base_R).to_numpy(); o, lo, hi, p, nc = ctest(d, g.cl.to_numpy())
    print(r, len(g), f"{o:+.3f} [{lo:+.3f},{hi:+.3f}] p={p:.3f}", (g[f"{r}_R"] - g.base_R).groupby(g.run).mean().round(3).to_dict())

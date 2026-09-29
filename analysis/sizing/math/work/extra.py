"""Part 3: (a) ATR-adaptive leverage compatibility, (b) TP-size sensitivity (TP > 10% ROE),
(c) 100-trade equity distribution per margin M (binomial on the empirical zero-edge classes),
(d) suspect-bar (bad print) sensitivity for the 5m bracket."""
import numpy as np
import pandas as pd
from scipy.stats import binom
import common
from common import *
import sim

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)
pd.set_option("display.max_rows", 400)

# (a) ATR-adaptive leverage: L_k = 1/(k*ATR% + MMR) keeps liquidation k ATRs away
rows = []
for tf in TFS:
    A = np.concatenate([(lambda a: a[~np.isnan(a)])(atr_wilder(load(s, tf))) for s in COINS])
    for k in (1, 2, 3):
        Lk = 1 / (k * A + MMR)
        rows.append(dict(tf=tf, k_atr=k, median_Lk=np.median(Lk), p10_Lk=np.quantile(Lk, .1),
                         share_Lk_ge20=np.mean(Lk >= 20), share_Lk_ge30=np.mean(Lk >= 30),
                         share_Lk_ge50=np.mean(Lk >= 50)))
    rows.append(dict(tf=tf, k_atr="tp20x>=0.5ATR", share_Lk_ge20=np.mean(tp_dist(20) >= 0.5 * A)))
ad = pd.DataFrame(rows)
ad.to_csv(f"{OUT}/adaptive_leverage_atr.csv", index=False)
print("(a) ATR-adaptive leverage\n", ad.round(3).to_string(index=False), "\n")

# (b) TP-size sensitivity on 5m bars, same 5m entries
en = pd.read_csv(f"{OUT}/entries_5m.csv.gz")
cap = int(90 * 1440 / 5)
K = int(np.ceil(np.log2(cap + 1)))
data = {}
for sym in COINS:
    df = load(sym, "5m")
    data[sym] = df


def run_on(data_map, tp_roe, levs):
    common.TP_ROE = tp_roe
    old = common.LEVS[:]
    sim.LEVS = levs
    recs, groups = None, []
    for sym in COINS:
        df = data_map[sym]
        o, h, l, c = (df[k].values.astype(float) for k in ["open", "high", "low", "close"])
        tsec = df["ts"].values.astype("datetime64[s]").astype(np.int64)
        mx, mn = build_sparse(h, l, K)
        e_ = en[en.sym == sym]
        idx = np.searchsorted(tsec, e_["ts"].values)
        assert np.all(tsec[idx] == e_["ts"].values)
        r = sim.run_block(o, h, l, c, tsec, mx, mn, idx.astype(np.int64), e_["dir"].values, cap, 5)
        if recs is None:
            recs = {k: {kk: [vv] for kk, vv in v.items()} for k, v in r.items()}
        else:
            for k, v in r.items():
                for kk, vv in v.items():
                    recs[k][kk].append(vv)
        groups.append(COINS.index(sym) * 100000 + tsec[idx] // (7 * 86400))
    recs = {k: {kk: np.concatenate(vv) for kk, vv in v.items()} for k, v in recs.items()}
    out = pd.DataFrame(sim.aggregate("5m", "5m", recs, np.concatenate(groups), 5))
    common.TP_ROE = 0.10
    sim.LEVS = old
    return out


tps = []
for tpr in (0.10, 0.20, 0.30, 0.50, 1.00):
    o_ = run_on(data, tpr, [20, 30, 50])
    o_["tp_roe"] = tpr
    tps.append(o_)
tp_df = pd.concat(tps, ignore_index=True)
tp_df.to_csv(f"{OUT}/tp_size_sensitivity_5m.csv", index=False)
cols = ["tp_roe", "L", "variant", "tp_pct", "stop_pct", "p0_brownian", "pTP_adv", "pLIQ_adv", "pSTOP_adv", "pTO_adv",
        "mean_hours", "EROE_adv", "EROE_se_adv", "Eeq_M20_adv", "pstar_adv", "dp_adv", "req_drift_pct_adv", "req_ann_ir_adv"]
print("(b) TP size sensitivity (5m paths)\n", tp_df[cols].round(4).to_string(index=False), "\n")

# (c) 100-trade equity distribution per M (binomial over empirical classes; liq variant, 5m row)
br = pd.read_csv(f"{OUT}/bracket_zero_edge.csv")
b5 = br[(br.tf == "5m") & (br.res == "5m")]
rows = []
N = 100
for var in ("liq", "stop0.5"):
    for L in LEVS:
        r = b5[(b5.L == L) & (b5.variant == var)].iloc[0]
        w, lo = r.winROE_adv, r.lossROE_adv
        for label, p in (("zero_edge", r.pTP_adv), ("arith_breakeven", r.pstar_adv)):
            for M in MARGINS:
                k = np.arange(N + 1)
                pk = binom.pmf(k, N, 1 - p)
                fin = (1 + M * w) ** (N - k) * (1 + M * lo) ** k
                order = np.argsort(fin)
                cdf = np.cumsum(pk[order])
                med = fin[order][np.searchsorted(cdf, 0.5)]
                plog = -np.log1p(M * lo) / (np.log1p(M * w) - np.log1p(M * lo))
                rows.append(dict(variant=var, L=L, scenario=label, p_win=p, M=M, win_roe=w, loss_roe=lo,
                                 mean_mult=float((pk * fin).sum()), median_mult=float(med),
                                 p_below_half=float(pk[fin < 0.5].sum()), p_below_tenth=float(pk[fin < 0.1].sum()),
                                 p_win_needed_log=plog))
eq = pd.DataFrame(rows)
eq.to_csv(f"{OUT}/equity_100trades.csv", index=False)
print("(c) 100 trades\n", eq.round(4).to_string(index=False), "\n")

# (d) suspect-bar sensitivity: neutralise IS suspect bars (flat bar at previous close) and rerun 5m bracket
s = pd.read_csv("/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/sweep/data/suspects.csv")
s["ts"] = pd.to_datetime(s["ts"], utc=True)
s = s[s["ts"] < IS_END]
clean = {}
nfix = 0
for sym in COINS:
    df = data[sym].copy()
    ts_s = set(s.loc[s.symbol == sym.upper(), "ts"])
    m = df["ts"].isin(ts_s).values
    idx = np.where(m)[0]
    idx = idx[idx > 0]
    pc = df["close"].values[idx - 1]
    for k in ["open", "high", "low", "close"]:
        df.loc[idx, k] = pc
    nfix += len(idx)
    clean[sym] = df
base = run_on(data, 0.10, [20, 30, 50])
fix = run_on(clean, 0.10, [20, 30, 50])
cmp_ = base[["L", "variant", "pTP_adv", "pLIQ_adv", "EROE_adv"]].merge(
    fix[["L", "variant", "pTP_adv", "pLIQ_adv", "EROE_adv"]], on=["L", "variant"], suffixes=("_raw", "_nosuspect"))
cmp_.to_csv(f"{OUT}/suspect_sensitivity_5m.csv", index=False)
print(f"(d) suspect bars neutralised: {nfix}\n", cmp_.round(5).to_string(index=False))

import os, sys, glob, pickle, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "..", "bt"))
from analyze import pooled, apply_rule
OUT = os.path.join(HERE, "out")
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 500); pd.set_option("display.max_columns", 40)

parts = [pickle.load(open(p, "rb")) for p in sorted(glob.glob(os.path.join(OUT, "parts_*.pkl")))]
FW = pd.concat([p["fw"] for p in parts]); GS = pd.concat([p["gstat"] for p in parts])
B = pd.concat([p["B"] for p in parts]); C = pd.concat([p["C"] for p in parts]); Dn = pd.concat([p["D"] for p in parts])
print("symbols:", sorted(FW.symbol.unique()))


def pooled_fwd(F):
    rows = []
    for s, g in F.groupby("strategy"):
        r = dict(strategy=s, group=g.group.iloc[0], signals=int(g.signals.sum()))
        N = g.signals.sum()
        for hz in (4, 16, 64):
            m = g[f"fwd{hz}_mean_pct"].to_numpy(); n = g.signals.to_numpy(); t = g[f"fwd{hz}_t"].to_numpy()
            ok = n > 2
            if N < 3:
                r[f"fwd{hz}"] = np.nan; r[f"t{hz}"] = np.nan; continue
            M = np.sum(n[ok] * m[ok]) / n[ok].sum()
            sd = np.where(ok, np.abs(m) * np.sqrt(n) / np.abs(np.where(t == 0, np.nan, t)), 0)
            var = (np.nansum((n[ok] - 1) * sd[ok] ** 2) + np.sum(n[ok] * (m[ok] - M) ** 2)) / (n[ok].sum() - 1)
            r[f"fwd{hz}"] = M; r[f"t{hz}"] = M / np.sqrt(var / n[ok].sum())
            r[f"pos_sym{hz}"] = int((g[f"fwd{hz}_mean_pct"] > 0).sum())
        rows.append(r)
    return pd.DataFrame(rows).sort_values("fwd16", ascending=False)


print("\n=== A. forward drift (gross, IS, 5 symbols pooled), un-gated and gated(<=0.6%) ===")
PF = pooled_fwd(FW)
print(PF.round(3).to_string(index=False))
PF.to_csv(os.path.join(OUT, "A_forward_pooled.csv"), index=False)

print("\n=== gate statistics (IS signals; structural-stop distance from signal close) ===")
G = GS.groupby(["strategy", "group"])[["signals", "nan_stop", "wrong_side", "le_046", "le_054", "le_060"]].sum()
G["share_le_060"] = G.le_060 / G.signals
med = GS.groupby("strategy").apply(lambda x: np.average(x.med_dist_pct.fillna(0), weights=x.signals) if x.signals.sum() else np.nan)
G["med_dist_pct(approx)"] = med.reindex(G.index.get_level_values(0)).to_numpy()
print(G.sort_values("share_le_060").round(3).to_string())
G.to_csv(os.path.join(OUT, "gate_stats.csv"))

cols = ["strategy", "exit", "trades", "wr", "pf", "exp_net_pct", "exp_gross_pct", "symbols_pos", "months_pos", "months", "eq_L50", "pass"]


def pr(T, title, fname, top=2):
    P = apply_rule(pooled(T)).sort_values("pf", ascending=False)
    grp = T.groupby("strategy")["group"].first()
    P["group"] = P.strategy.map(grp)
    print(f"\n=== {title}: PASS {int(P['pass'].sum())} of {len(P)} ; max PF {P.pf.max():.3f} ===")
    print(P[cols + ["group"]].groupby("strategy").head(top).round(3).to_string(index=False))
    P.to_csv(os.path.join(OUT, fname), index=False)
    return P


PB = pr(B[B.group != "tested"], "B. 13 stage-1 exits, NO gate, 12 new ports + variants", "B_pooled.csv")
# sanity: tested strategies vs delivered stage-1 pooled file
ref = pd.read_csv("/home/user/crypto-bot-research/results/pooled_IS_15m_all5.csv")
mine = apply_rule(pooled(B[B.group == "tested"]))
m = mine.merge(ref, on=["strategy", "exit"], suffixes=("_gap4", "_stage1"))
m["d_trades"] = m.trades_gap4 - m.trades_stage1; m["d_pf"] = m.pf_gap4 - m.pf_stage1
print("\n=== sanity: tested strategies via stops17 wrapper vs delivered pooled_IS_15m_all5.csv ===")
print(m[["strategy", "exit", "trades_gap4", "trades_stage1", "pf_gap4", "pf_stage1", "d_trades", "d_pf"]].round(4).to_string(index=False))
print("max |d_trades|", m.d_trades.abs().max(), "max |d_pf|", m.d_pf.abs().max(), "rows", len(m))

PC = pr(C, "C. 13 stage-1 exits WITH hard-cap gate (0 < stop dist <= 0.6%), all 31-set", "C_pooled.csv")
PD = pr(Dn, "D. native-lite engine (structural SL + cap + net-ROE lock + CONFIRM_2)", "D_pooled.csv", top=6)

print("\n=== D. exit reasons by config (all strategies) ===")
print(pd.crosstab(Dn.exit, Dn.reason).to_string())

print("\n=== D. live-positive ports: native, real vs FINGRAD cost ===")
lp = PD[PD.strategy.str.match(r"^(N11|N13|N19|N08)")].sort_values(["strategy", "exit"])
print(lp[["strategy", "exit", "trades", "wr", "pf", "exp_net_pct", "exp_gross_pct", "symbols_pos", "eq_L50", "pass"]].round(3).to_string(index=False))

# totals
print("\n=== combo counts ===")
for nm, P in (("B", PB), ("C", PC), ("D", PD)):
    print(nm, "combos", len(P), "pass", int(P["pass"].sum()), "PF>=1.0", int((P.pf >= 1.0).sum()),
          "PF>=1.2", int((P.pf >= 1.2).sum()), "PF>=1.2&n>=100", int(((P.pf >= 1.2) & (P.trades >= 100)).sum()))

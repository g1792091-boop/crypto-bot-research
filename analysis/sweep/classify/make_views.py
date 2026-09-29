"""Rebuild the descriptive views next to classification.csv from repo files only.

    python3 analysis/sweep/classify/make_views.py [--out DIR]

Inputs (relative to analysis/sweep/):
  combine/out/gate_all_is_applied.csv     selection (IS) gate table, per-coin columns
  holdout/out/gate_all_oos_applied.csv    confirmation (OOS) gate table
  holdout/out/gate_all_final_applied.csv  recent (FINAL) gate table
  classify/classification.csv             output of classify.py (read from --out if it exists there)

Outputs (this folder, or --out DIR):
  doge_coin_view.csv     every (strategy, tf, H) row: DOGEUSD-only n/fwd in IS, OOS, FINAL; common mu* and cost from IS
  hurdle_cells_fate.csv  class-2 cells whose shown IS ratio (fwd / mu* at best_H) is >= 1, followed into OOS and FINAL
                         (ratios are fwd / mu* of the same split; values rounded to 2 decimals)
  table_ko.md            strategy x timeframe table of classes (SWEEP_RESULTS_KO.md section 3)

Descriptive only. Nothing here changes a class or a judgement.
"""
import argparse, os
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
W = os.path.normpath(os.path.join(HERE, ".."))  # analysis/sweep
ap = argparse.ArgumentParser()
ap.add_argument("--out", default=HERE, help="output folder (default: this script's folder)")
OUT = ap.parse_args().out
os.makedirs(OUT, exist_ok=True)

key = ["strategy", "tf", "H"]
TF_ORDER = ["5m", "15m", "30m", "1h", "4h", "1d"]
IS = pd.read_csv(f"{W}/combine/out/gate_all_is_applied.csv")
OOS = pd.read_csv(f"{W}/holdout/out/gate_all_oos_applied.csv")
FIN = pd.read_csv(f"{W}/holdout/out/gate_all_final_applied.csv")
cpath = os.path.join(OUT, "classification.csv")
if not os.path.exists(cpath):
    cpath = os.path.join(HERE, "classification.csv")
C = pd.read_csv(cpath, dtype={"cls": str})

# 1) doge_coin_view.csv (row order = IS gate table order: strategy A-Z, tf 5m..1d, H)
dv = IS[key + ["n_DOGEUSD", "fwd_DOGEUSD", "mu_star", "cost_H"]]
dv = dv.merge(OOS[key + ["n_DOGEUSD", "fwd_DOGEUSD"]].rename(columns={"n_DOGEUSD": "n_oos", "fwd_DOGEUSD": "fwd_oos"}),
              on=key, how="left")
dv = dv.merge(FIN[key + ["n_DOGEUSD", "fwd_DOGEUSD"]].rename(columns={"n_DOGEUSD": "n_fin", "fwd_DOGEUSD": "fwd_fin"}),
              on=key, how="left")
dv.to_csv(os.path.join(OUT, "doge_coin_view.csv"), index=False)

# 2) hurdle_cells_fate.csv
C["ratio"] = C["best_fwd_pct"] / C["best_mu_pct"]
hc = C[(C["cls"] == "2") & (C["ratio"] >= 1)]
rows = []
for _, r in hc.iterrows():
    def pick(D):
        return D[(D.strategy == r.strategy) & (D.tf == r.tf) & (D.H == int(r.best_H))].iloc[0]
    i, o, f = pick(IS), pick(OOS), pick(FIN)
    rows.append(dict(strategy=r.strategy, tf=r.tf, H=int(r.best_H),
                     n_is=int(i.n), IS=round(i.fwd / i.mu_star, 2), z_is=round(i.z, 2), p_holm=round(i.p_holm, 2),
                     n_oos=int(o.n), OOS=round(o.fwd / o.mu_star, 2), z_oos=round(o.z, 2),
                     n_fin=int(f.n), FINAL=round(f.fwd / f.mu_star, 2), z_fin=round(f.z, 2)))
pd.DataFrame(rows).to_csv(os.path.join(OUT, "hurdle_cells_fate.csv"), index=False)

# 3) table_ko.md
# Row order = pre-registered strategy order as it appears in the OOS gate table
# (fingrad exact, fingrad approx, pine, v45, doge). * = approx=True, dagger = prev_examined=True.
# Cell: class 3 -> "③a"/"③b" (reason); class 2 -> "② ratio" (ratio = IS fwd / mu* at best_H, bold if >= 1).
order = list(dict.fromkeys(OOS["strategy"]))
cell = {}
for _, r in C.iterrows():
    if r.cls == "3":
        txt = "③" + r.reason[0]
    else:
        mark = "①" if r.cls == "1" else "②"
        txt = f"{mark} {r.ratio:+.2f}"
        if r.ratio >= 1:
            txt = f"**{txt}**"
    cell[(r.strategy, r.tf)] = txt
flags = C.groupby("strategy")[["approx", "prev"]].first()
lines = ["| 매매법 | " + " | ".join(TF_ORDER) + " |", "|---" * (len(TF_ORDER) + 1) + "|"]
for s in order:
    name = s + ("*" if flags.loc[s, "approx"] else "") + ("†" if flags.loc[s, "prev"] else "")
    lines.append(f"| {name} | " + " | ".join(cell[(s, tf)] for tf in TF_ORDER) + " |")
with open(os.path.join(OUT, "table_ko.md"), "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines))
print("wrote doge_coin_view.csv (%d rows), hurdle_cells_fate.csv (%d rows), table_ko.md (%d strategies) to %s"
      % (len(dv), len(rows), len(order), OUT))

"""Holdout agent -- DESCRIPTIVE ONLY (nothing was carried; PREREG 6 has nothing to confirm).
Runs sweep_lib.exits() unchanged on OOS and FINAL for
  (a) the 15 IS near-miss family cells (fwd >= mu*, failed Holm; listed in combine/carried.json as NOT carried)
  (b) the top-5 IS family cells by z (adds N20_EMA9_CHOP 5m H4/H16; 5m run observed-only, no null, for cost)
and evaluates a HYPOTHETICAL what-if: if the Combine agent's descriptive IS exit results had been fed to
select_exits (i.e. if the gate had been ignored), which combos would have been 'carried', and would
holdout_confirm have passed them on OOS?  This is NOT the pre-registered verdict.
usage: python3 exits_holdout.py <split> <tf> [<tf> ...]"""
import os, sys, time
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["SWEEP_DATA"] = os.path.join(HERE, "data")
sys.path.insert(0, os.path.join(HERE, "lib"))
import sweep_lib as L
S = os.path.dirname(HERE)
O = os.path.join(HERE, "out")
K = ["strategy", "tf", "H"]
split = sys.argv[1]
tfs = sys.argv[2:]
IS = pd.read_csv(os.path.join(S, "combine", "out", "gate_all_is_applied.csv"))
fam = IS[IS.in_family]
near = fam[fam.fwd >= fam.mu_star]
top5 = fam.sort_values("z", ascending=False).head(5)
cells = pd.concat([near.assign(why="IS near-miss (fwd>=mu*)"), top5.assign(why="IS top-5 by z (family)")])
cells = cells.groupby(K, as_index=False).agg(why=("why", " + ".join))
print(f"{split}: {len(cells)} cells", flush=True)
rows = []
for tf in tfs:
    cc = cells[cells.tf == tf]
    if cc.empty:
        continue
    panel = L.load_panel(tf, split)
    last = max(df["ts"].max() for df in panel.values())
    names = sorted(cc.strategy.unique())
    sigs = L.compute_signals(panel, tf, names)
    # check against the gate-run signal cache (same harness), where available
    import glob
    for f in glob.glob(os.path.join(O, f"signals_{split}_{tf}*.npz")):
        cache = L.load_signals(f)
        for n in names:
            if n in cache:
                bad = [c for c in panel if not np.array_equal(cache[n][c], sigs[n][c])]
                print(f"  cache check {os.path.basename(f)} {n}: {'OK' if not bad else 'MISMATCH ' + str(bad)}", flush=True)
    print(f"{split} {tf}: last bar {last}; strategies {names}", flush=True)
    for _, r in cc.iterrows():
        t0 = time.time()
        H = int(r.H)
        if tf == "5m":
            # observed only (no null): 5 exits, same engine/costs/windows as exits()
            atrs = {c: L.fg.atr(df, 14).to_numpy(float) for c, df in panel.items()}
            windows = {}
            for c, df in panel.items():
                lo, hi = L.signal_window(df, tf, split, 0)
                if hi - lo > 2 * L.EXIT_CAP_MULT * H + 4:
                    windows[c] = (lo, hi)
            obs = L._run_exits_panel(panel, sigs[r.strategy], tf, split, H, atrs, windows, 0, L.exit_set(H))
            ex = pd.DataFrame([dict(strategy=r.strategy, tf=tf, H=H, exit=k, split=split, **L.pooled_stats(v, panel),
                                    p_max=np.nan, B=0) for k, v in obs.items()])
            ex["exit_criteria_met_DESCRIPTIVE"] = False
        else:
            ex = L.exits(tf, r.strategy, H, panel, sigs, split=split, B=L.B_EXIT)
            ex = ex.rename(columns={"exit_pass": "exit_criteria_met_DESCRIPTIVE"})
        ex["why"] = r.why
        ex["carry_eligible"] = False
        rows.append(ex)
        print(f"  {split} {tf} {r.strategy} H{H} ({r.why}): {time.time() - t0:.0f}s", flush=True)
        print(ex[["exit", "trades", "pf", "exp_net", "sum_net", "symbols_pos", "months_pos", "months", "p_max",
                  "exit_criteria_met_DESCRIPTIVE"]].to_string(), flush=True)
if rows:
    pd.concat(rows, ignore_index=True).to_csv(os.path.join(O, f"exits_descriptive_{split}_{'_'.join(tfs)}.csv"), index=False)

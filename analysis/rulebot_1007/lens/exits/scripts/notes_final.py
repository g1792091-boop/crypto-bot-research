import site, sys, json
sys.dont_write_bytecode = True
us = site.getusersitepackages()
if us not in sys.path: sys.path.append(us)
import pandas as pd
D = pd.read_csv(sys.argv[1])
raw = {(x["strategy"], x["timeframe"]): x for x in json.load(open(sys.argv[2]))}
DUP = {("F11_RAID","15m"), ("F11_TSOUP","15m"), ("F13_RAID_PD","15m")}
out = []
order = {"15m":0,"30m":1,"1h":2,"4h":3}
D = D.sort_values(["tf","R_base"], key=lambda s: s.map(order) if s.name=="tf" else s, ascending=[True, False])
for _, r in D.iterrows():
    k = (f"{r.strategy} ({r.group})", r.tf)
    x = raw[k]
    ne, npos = int(r.n_exits), int(r.n_exits_pos)
    if npos == ne:
        note = f"Positive under all {ne} non-leverage exits (sign does not depend on the exit), but the house-exit CI includes 0; track, not proven."
    elif npos == 0:
        note = f"Negative under all {ne} exits, even the best in hindsight ({r.best_exit} {r.R_best_exit:+.2f}R): no exit or custom value rescues it."
    elif r.R_base > 0:
        note = f"Positive point estimate under the house exit but only {npos}/{ne} exits keep it > 0; the sign depends on the exit, so not robust."
    else:
        note = f"Negative under the house exit; > 0 only under {npos}/{ne} hindsight exits (best {r.best_exit}): choosing that exit would be in-sample overfitting."
    if r.n_v3b > 0 and r.R_base_v3b == r.R_base_v3b and r.R_base_v4 == r.R_base_v4 and (r.R_base_v3b > 0) != (r.R_base_v4 > 0):
        note += " v3b and v4 disagree in sign."
    if r.group == "ds200":
        note += " v4 only (1.5 days)."
    if (r.strategy, r.tf) in DUP:
        note += " Near-duplicate group F11_RAID / F11_TSOUP / F13_RAID_PD."
    if r.n < 40:
        note += " Small n."
    out.append({"strategy": x["strategy"], "timeframe": r.tf, "grade": r.grade, "numbers": x["numbers"], "note": note})
json.dump(out, open(sys.argv[3], "w"), indent=0)
print(len(out))

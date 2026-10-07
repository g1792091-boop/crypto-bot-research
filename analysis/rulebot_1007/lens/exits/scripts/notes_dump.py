import site, sys, json
sys.dont_write_bytecode = True
us = site.getusersitepackages()
if us not in sys.path: sys.path.append(us)
import pandas as pd, numpy as np
D = pd.read_csv(sys.argv[1])
order = {"15m":0,"30m":1,"1h":2,"4h":3}
D = D.sort_values(["tf","R_base"], key=lambda s: s.map(order) if s.name=="tf" else s, ascending=[True, False])
out = []
def f(x): return "nan" if x != x else f"{x:+.2f}"
for _, r in D.iterrows():
    runs = f"v3b {f(r.R_base_v3b)} (n {r.n_v3b}), v4 {f(r.R_base_v4)} (n {r.n_v4})" if r.n_v3b > 0 else f"v4 only (n {r.n_v4})"
    nums = (f"every-signal n {r.n}; house R {f(r.R_base)} [{f(r.lo_base)}, {f(r.hi_base)}] q {r.q_base:.2f}; {runs}; "
            f"geo20_bar {f(r['R_geo20_bar'])}, RL1_0.5_bar {f(r['R_RL1_0.5_bar'])}, tp1R {f(r.R_tp1R)}; best-in-hindsight {r.best_exit} {f(r.R_best_exit)}, exit spread {r.exit_spread_R:.2f}R, {r.n_exits_pos}/{r.n_exits} exits > 0")
    out.append({"strategy": f"{r.strategy} ({r.group})", "timeframe": r.tf, "grade": r.grade, "numbers": nums})
print(json.dumps(out[:3], indent=0))
print(list(D.columns))
json.dump(out, open(sys.argv[2], "w"))
print(len(out))

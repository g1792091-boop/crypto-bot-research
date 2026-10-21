"""Cross-check of engine5y against the earlier minute-by-minute replay (entryrate/code/simulate.py, which matched the
live engine on 7/1-10/20: 89 entries) with that replay's rules (TIME 4 bars, NYSE open +30 min only, the live macro file,
no funding) on 2026-06-28 .. 10-21; plus the array chase check against combo.chase_check on a sample.
Output: out/validate.json"""
import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine5y import *

OLD = f"{SCR}/entryrate/out"
v = variant(name="validate_old_rules", time_bars=4, us_open_pre=0, us_open_pause=30, macro="csv", funding=False,
            start=ms("2026-06-28"), end=ms("2026-10-21"))
T, cand, info = run(v)
oe = pd.read_csv(f"{OLD}/sim_main_entries.csv")
ot = pd.read_csv(f"{OLD}/sim_main_trades.csv")
mine = T.rename(columns={"entry_t": "t", "coin": "symbol"})
k = ["t", "label", "symbol", "side"]
m = oe.merge(mine[k + ["roe", "reason", "exit_t"]], on=k, how="outer", indicator=True)
ot2 = ot.rename(columns={"entry_time": "t"})[["t", "label", "symbol", "side", "roe", "reason", "exit_time"]]
mm = ot2.merge(mine[k + ["roe", "reason", "exit_t"]], on=k, how="inner", suffixes=("_old", "_new"))
mm["droe"] = (mm.roe_old - mm.roe_new).abs()
mm = mm[mm.reason_old != "OPEN_AT_END"]
W0, W1 = ms("2026-06-30 15:00"), ms("2026-10-20 15:00")
res = {"old_entries": int(len(oe)), "new_entries": int(len(T)), "same_entries": int((m._merge == "both").sum()),
       "only_old": m[m._merge == "left_only"][k].to_dict("records"), "only_new": m[m._merge == "right_only"][k].to_dict("records"),
       "kst_window_entries_new": int(((T.entry_t >= W0) & (T.entry_t < W1)).sum()),
       "same_reason": int((mm.reason_old == mm.reason_new).sum()), "compared_trades": int(len(mm)),
       "max_abs_roe_diff": float(mm.droe.max()) if len(mm) else None,
       "mean_roe_old": float(ot.roe.mean()), "mean_roe_new": float(T.roe.mean())}
# chase: array form vs combo.chase_check
mk = markets()
rng = np.random.default_rng(5)
n_ok = n = 0
for coin in COINS:
    M = mk[coin]
    for _ in range(300):
        t = int(rng.integers(ms("2021-01-01"), ms("2026-09-30")) // MIN * MIN)
        side = int(rng.choice([-1, 1]))
        price = float(M.o[M.i(t)]) * float(rng.uniform(0.97, 1.03))
        n += 1
        n_ok += int(M.chase(t, side, price) == M.chase_repo(t, side, price))
res["chase_array_vs_repo"] = {"n": n, "same": n_ok}
json.dump(res, open(f"{OUT}/validate.json", "w"), indent=1, default=str)
print(json.dumps({k_: v_ for k_, v_ in res.items() if k_ not in ("only_old", "only_new")}, indent=1))
print("only old", res["only_old"][:10])
print("only new", res["only_new"][:10])
print(mm[mm.droe > 1e-6].head(20).to_string())
print(mm[mm.reason_old != mm.reason_new].head(20).to_string())

"""Agreement of the full-series signals (out/signals5y.csv, computed from 2020 on) with the live bot's trailing-window
signals of the earlier replay (entryrate/out/signals.csv: sigservice.window_5m / config.DS_WINDOW_5M windows at every
bar close, 2026-06-28 .. 10-21) on bar closes 2026-07-01 00:00 .. 10-21 00:00 UTC. Output: out/signal_agreement.json"""
import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fycommon import *

TRAIL = f"{SCR}/entryrate/out/signals.csv"
A, B = ms("2026-07-01"), ms("2026-10-21")
k = ["bar_close", "tf", "member", "symbol", "side"]
t = pd.read_csv(TRAIL)
f = pd.read_csv(f"{OUT}/signals5y.csv")
t = t[(t.bar_close >= A) & (t.bar_close < B)]
f = f[(f.bar_close >= A) & (f.bar_close < B)]
m = t.merge(f, on=k, how="outer", indicator=True)
by = m.groupby(["tf", "member", "_merge"]).size().unstack(fill_value=0)
both = int((m._merge == "both").sum())
res = {"window_utc": ["2026-07-01", "2026-10-21"], "trailing_file": TRAIL, "trailing_sha256": sha256(TRAIL),
       "trailing_n": int(len(t)), "full_n": int(len(f)), "both": both,
       "only_trailing": int((m._merge == "left_only").sum()), "only_full": int((m._merge == "right_only").sum()),
       "agreement_pct": round(100.0 * both / max(1, len(m)), 3),
       "by_member": {f"{a}@{b}": {c: int(v) for c, v in r.items()} for (a, b), r in by.iterrows()}}
json.dump(res, open(f"{OUT}/signal_agreement.json", "w"), indent=1)
print(json.dumps({k_: v for k_, v in res.items() if k_ != "by_member"}, indent=1))
print(by.to_string())
print(m[m._merge != "both"].head(30).to_string())

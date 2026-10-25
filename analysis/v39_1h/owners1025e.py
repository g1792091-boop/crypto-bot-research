"""Owners 10-25 night, 20 days only (no 5-year): is the chosen ladder (15->13, then every +5 % the lock 3 % under) the
best of the 20 days, and would a wider take-profit range do better? The owners' plan otherwise unchanged (owners1025c:
40 % margin, BTC 40x / others 30x, stop 2.5 ATR, liquidation guard, 1h signals only, Toobit costs from $50).
Ladder = (first trigger, its lock, step, gap under each later trigger), net ROE; plus fixed take-profits."""
import itertools
import os
import sys

import pandas as pd

H = os.path.dirname(os.path.abspath(__file__))
import owners1025c as C  # noqa: E402  (argv: export, out)
from sim import Variant as V  # noqa: E402

_P = dict(lev_btc=40, lev_alt=30, frac=0.40, stop_atr=2.5)
sigs = C.signals(("1h",))
rows = []


def run(name, label, v):
    C.V = v
    out, ent = C.account(sigs)
    locks = sorted(round(100 * x) for x in ent["lock_roe"] if x == x and x > 0) if len(ent) else []
    rows.append({"variant": name, "label": label, **{k: out[k] for k in ("trades", "wins", "losses", "stops", "open",
                                                                         "final", "ret_pct", "dd_pct")},
                 "exit_locks": " ".join(map(str, locks))})


for trig, lockgap, step, gap in itertools.product((12, 15, 20, 25, 30, 40), (2, 3, 5), (5, 10), (2, 3, 5)):
    first = trig - lockgap
    name = f"L{trig}>{first} s{step} g{gap}"
    label = f"{trig}%→{first}%, 이후 {step}%마다 {gap}% 아래"
    run(name, label, V(name, label, first_lock=first / 100, gap=lockgap / 100, step=step / 100,
                       next_trigger=(trig + step) / 100, next_gap=gap / 100, **_P))
for tp in (10, 13, 15, 20, 25, 30, 40, 50):
    run(f"TP{tp}", f"고정 익절 +{tp}% (시장가)", V(f"TP{tp}", ladder=False, tp="ROE", tp_val=tp / 100, **_P))
R = pd.DataFrame(rows).sort_values("final", ascending=False).reset_index(drop=True)
R.insert(0, "rank", range(1, len(R) + 1))
R.to_csv(os.path.join(sys.argv[2], "ladder_grid.csv"), index=False)
pd.set_option("display.width", 250)
pd.set_option("display.max_colwidth", 60)
print(R.head(25).to_string(index=False))
print("chosen:", R[R["variant"] == "L15>13 s5 g3"].to_string(index=False, header=False))
print("rows", len(R), "chosen rank", int(R.loc[R["variant"] == "L15>13 s5 g3", "rank"].iloc[0]))

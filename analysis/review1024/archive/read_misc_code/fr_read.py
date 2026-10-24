# Read-only: confirm-period read of the friend combos (PREREG6) for every rule x tf x ATR exit.
# Nothing is written. Post-hoc read (not pre-registered); for the archive note only.
import os, sys
CODE = "/home/user/crypto-bot-research/research/vwap30/code"
sys.path.insert(0, CODE)
import vwfriend as F
from vwacct import metrics
from vwstages3 import Label, wd_mask
from vwcommon import PERIODS, ms
PERIODS["c2025"] = (ms("2025-01-01"), ms("2026-01-01"))
PERIODS["c2026"] = (ms("2026-01-01"), ms("2026-10-01"))
F.use("atr")
for rule in F.RULES:
    for tf in F.TFS6:
        lab = f"{rule}_at_{tf}"
        L = Label(lab)
        rows = []
        for e in F.ATR_EX:
            o = L.one(e["id"])
            m = wd_mask(o)
            s = metrics(o, m, 0, "select"); c = metrics(o, m, 0, "confirm")
            rows.append((e["id"], F.ex_name("atr", e["id"], lab), s, c))
        rows.sort(key=lambda r: -r[2]["growth"])
        npos_s = sum(r[2]["avgR"] > 0 for r in rows); npos_c = sum(r[3]["avgR"] > 0 for r in rows); both = sum((r[2]["avgR"] > 0) and (r[3]["avgR"] > 0) for r in rows)
        print(f"== {lab}: exits with R>0 select {npos_s}/{len(rows)}, confirm {npos_c}/{len(rows)}, both {both}")
        for r in rows[:3]:
            s, c = r[2], r[3]
            print(f"   {r[1]:<40} sel n{s['n']:5d} wd{s['per_weekday']:.2f} win{s['win']:.3f} R{s['avgR']:+.3f} | conf n{c['n']:4d} wd{c['per_weekday']:.2f} win{c['win']:.3f} R{c['avgR']:+.3f} g{c['growth']:+.2f}")

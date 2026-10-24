"""Verifier: independent day-block bootstrap of the 30-day goal path for the 39 taken trades (payback included) at 58 %
and 40 % margin, other seed. Run from this folder: python3 vgoal.py"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vacct as V
from vacct import *
O.CACHE = "/dev/shm/claude_verify_srsix"
D = O.load_all()
S = V.signals(D, "FWD")
lev = 30.0
k = np.where(S.side > 0, S.kL, S.kS)
tk = V.one_pos(S.e.to_numpy(), k)
roe = np.maximum(lev * np.where(S.side > 0, S.rL, S.rS)[tk] + lev * PAYBACK, -1)
day = (S.t.to_numpy()[tk] // DAY)
a, b = O.P["FWD"]
lo, hi = a // DAY, (min(b, ext_end()) - 1) // DAY
by = [roe[day == d] for d in range(lo, hi + 1)]
out = {"days": len(by), "trades": len(roe)}
r = np.random.default_rng(99)
for mg in (0.58, 0.40):
    hit = l50 = 0
    fin = []
    for _ in range(20000):
        eq, half, done = 1.0, False, False
        for di in r.integers(0, len(by), 30):
            for x in by[di]:
                eq *= 1 + mg * x
                if not done:
                    if eq >= 6: hit += 1; done = True
                    else:
                        if eq <= 0.5 and not half: l50 += 1; half = True
                        if eq <= 0.1: done = True
        fin.append(eq)
    out[f"m{mg}"] = {"p_x6": hit / 20000, "p_lose50_first": l50 / 20000, "median": float(np.median(fin))}
print(json.dumps(out, indent=1)); json.dump(out, open("vgoal.json", "w"), indent=1)

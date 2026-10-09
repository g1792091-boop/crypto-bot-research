"""Check on one whole series that the memoised indicator calls give exactly the locked param_defs signals for EVERY
grid combo (stage 2 also checks 3-4 combos per strategy on every series).

    python3 -B research/st_custom/verify_memo.py COIN TF PERIOD
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import numpy as np  # noqa: E402
import s2_signals as S2  # noqa: E402

coin, tf, per = sys.argv[1:4]
bt = C.load_bars(coin, tf)
lo, hi = S2.period_range(bt["ts"], per)
s0, s1 = max(0, lo - C.WARM), min(len(bt["ts"]), hi + C.SPILL)
df = C.frame(bt, tf, s0, s1)
res = {}
for strat in C.STRATS:
    C.memo_on(("v", coin, tf, per))
    memo = [C.combo_signal(strat, c, df, tf) for c in range(C.NCOMBO[strat])]
    C.memo_off()
    bad = [c for c in range(C.NCOMBO[strat]) if not np.array_equal(memo[c], C.combo_signal(strat, c, df, tf))]
    res[strat] = dict(combos=C.NCOMBO[strat], mismatches=len(bad), first_bad=bad[:5],
                      signals=int(sum(int(np.count_nonzero(m)) for m in memo)))
    C.log(strat, res[strat])
C.save_json(os.path.join(C.OUT, f"verify_memo_{coin}_{tf}_{per}.json"), dict(series=[coin, tf, per, s0, s1], **res))

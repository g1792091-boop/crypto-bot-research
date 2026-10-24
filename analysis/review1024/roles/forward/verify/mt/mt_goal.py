"""Independent 30-day day-block bootstrap for P4 a2 (margin 40 %): H2 days, all days, H1 days; plus a version with the
per-trade ROE shifted down by one standard error (what the goal odds look like if the true mean is 1 SE lower).
Run: python3 mt_goal.py"""
import json, os, sys
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/forward")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fw_lib import *  # noqa
from fw_combo import add_roe  # noqa
from mt_p4 import bot_trades  # noqa


def boot(x, d, lo, hi, margin=0.4, nb=20000, seed=11):
    nd = hi - lo + 1
    by = [x[d == lo + i] for i in range(nd)]
    rng = np.random.default_rng(seed)
    hit = l50 = l90 = 0
    fin = np.empty(nb)
    for b in range(nb):
        eq, half, done = 1.0, False, False
        for di in rng.integers(0, nd, 30):
            for r in by[di]:
                eq *= 1 + margin * r
                if not done:
                    if eq >= 6:
                        hit += 1; done = True
                    else:
                        if eq <= 0.5 and not half:
                            l50 += 1; half = True
                        if eq <= 0.1:
                            l90 += 1; done = True
        fin[b] = eq
    return {"p_x6": hit / nb, "p_l50": l50 / nb, "p_l90": l90 / nb, "median": float(np.median(fin)), "days": int(nd), "n": int(len(x))}


S = add_roe(load("sig"))
mem = json.load(open("/home/user/crypto-bot-research/deploy/combo.trend.json"))["members"]
mm = np.zeros(len(S), bool)
for it in mem:
    mm |= (S.name.to_numpy() == it["strategy"]) & (S.tf.to_numpy() == it["tf"])
X = S[mm & (S.tj_why_1022.to_numpy() == "")]
out = {}
for per in ("H2", "all", "H1"):
    T = bot_trades(X, "a2", per).sort_values("t")
    x = T.roe.to_numpy(); d = T.t.to_numpy(np.int64) // DAY
    a, b = PERIOD[per]
    lo, hi = a // DAY, (b - 1) // DAY
    out[per] = boot(x, d, lo, hi)
    se = x.std(ddof=1) / np.sqrt(len(x))
    out[per + "_minus1se"] = boot(np.maximum(x - se, -1), d, lo, hi)
    out[per + "_coinflip_mean"] = boot(np.maximum(x - (x.mean() + 0.0439), -1), d, lo, hi)   # shifted to the coin-flip null mean (-4.4 %)
    print(per, out[per], out[per + "_minus1se"], out[per + "_coinflip_mean"])
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "mt_goal.json"), "w"), indent=1)

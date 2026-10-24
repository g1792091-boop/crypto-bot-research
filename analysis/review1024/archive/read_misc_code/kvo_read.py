# Read-only post-hoc read: FR_KVO_at_1h (OBV/RSI26/MOM trend + Klinger cross) with trend exits. Writes nothing.
import os, sys
import numpy as np
CODE = "/home/user/crypto-bot-research/research/vwap30/code"
sys.path.insert(0, CODE)
import vwfriend as F
from vwacct import metrics, trades
from vwstages3 import Label, wd_mask, twin_p90
from vwcommon import PERIODS, ms, COINS
PERIODS["c2025"] = (ms("2025-01-01"), ms("2026-01-01"))
PERIODS["c2026"] = (ms("2026-01-01"), ms("2026-10-01"))
PERIODS["y2020"] = (ms("2020-03-01"), ms("2021-01-01"))
PERIODS["y2021"] = (ms("2021-01-01"), ms("2022-01-01"))
PERIODS["y2022"] = (ms("2022-01-01"), ms("2023-01-01"))
PERIODS["y2023"] = (ms("2023-01-01"), ms("2024-01-01"))
PERIODS["y2024"] = (ms("2024-01-01"), ms("2025-01-01"))
F.use("atr")
for lab in ("FR_KVO_at_1h", "FR_ROC_at_1h"):
    L = Label(lab)
    names = {e["id"]: F.ex_name("atr", e["id"], lab) for e in F.ATR_EX}
    for want in ("손절 3ATR · 익절 없음", "손절 2ATR · 익절 없음"):
        j = [k for k, v in names.items() if v == want][0]
        o = L.one(j); m = wd_mask(o)
        print(f"== {lab} | {want}")
        for per in ("y2020", "y2021", "y2022", "y2023", "y2024", "c2025", "c2026", "live"):
            x = metrics(o, m, 0, per)
            print(f"   {per}: n{x['n']:4d} win{x['win']:.3f} R{x['avgR']:+.3f} g{x['growth']:+.2f} maxdd{x.get('maxdd',0):+.2f}")
        c = metrics(o, m, 0, "confirm")
        p90, tw = twin_p90(o, m, "confirm", 1000, 20261029)
        print(f"   confirm g{c['growth']:+.2f}, twin p90 {p90:+.2f}, share of twins below {float((tw < c['growth']).mean()):.3f}")
        # concentration: top-5 trades share of confirm sum R
        a, b = PERIODS["confirm"]
        mm = m & (o.entry >= a) & (o.entry < b)
        idx, net, ext, D = trades(o, mm, 0, None)
        R = net / D
        srt = np.sort(R)[::-1]
        print(f"   confirm sumR {R.sum():+.1f}, top5 {srt[:5].round(1).tolist()} share {srt[:5].sum()/R.sum() if R.sum()>0 else float('nan'):.2f}, R excl top5 {(R.sum()-srt[:5].sum())/max(len(R)-5,1):+.3f}")
        coins = o.coin[idx]
        print("   per-coin confirm R:", {COINS[k]: round(float(R[coins == k].mean()), 3) for k in range(len(COINS)) if (coins == k).any()})

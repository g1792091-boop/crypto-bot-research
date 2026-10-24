"""Check: 30m signals at the top of the hour (judged on the 1h bar that contains them) vs at half past (1h bar closed
30 minutes earlier). python3 check_30m.py <scratch>"""
import sys
import numpy as np
import measure_roles as MR

scr = sys.argv[1]
E = MR.libs()
for coin in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
    raw = MR.load(scr, "30m", coin)
    df = MR.as_chart(raw, "30m")
    run = E["run"]
    sig = {n: run.core_module(n).signals(df, "30m") for n in ("V45_AMB", "N25_DST_CCI", "DOGE", "S6_EMA_DMI_ADX")}
    ds = run.ds_module()
    sig["F4_FAN"] = ds.signals(df, "30m", "F4_FAN", coin=coin[:-1])
    sig["F16_FIB382"] = ds.signals(df, "30m", "F16_FIB382", coin=coin[:-1])
    bc = raw["ts"].to_numpy(np.int64) + 30 * MR.MIN
    hc, hraw = MR.htf_dir(scr, coin, "1h")
    j = np.searchsorted(hc, bc, side="right") - 1
    hd = np.where(j >= 0, hraw[np.maximum(j, 0)], 0)
    jp = np.maximum(j - 1, 0)
    hd_prev = hraw[jp]                     # the 1h bar before (closed >= 30 min before the signal)
    top = (bc % 3_600_000) == 0
    inper = bc >= MR.P0
    for name, (lg, sh) in sig.items():
        lg = np.asarray(lg, bool) & inper
        sh = np.asarray(sh, bool) & inper & ~lg
        side = np.where(lg, 1, np.where(sh, -1, 0))
        out = []
        for lab, m in (("top", top), ("half", ~top)):
            i = np.flatnonzero((side != 0) & m)
            s, h, hp = side[i], hd[i], hd_prev[i]
            ag = (h == s).sum() / max(1, ((h == s) | (h == -s)).sum())
            agp = (hp == s).sum() / max(1, ((hp == s) | (hp == -s)).sum())
            out.append(f"{lab} n={len(i)} agree={ag:.2f} prev1h={agp:.2f}")
        print(coin, name, " | ".join(out))

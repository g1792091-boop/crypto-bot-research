"""Parity: my 15m-granularity house exit vs research/strategy_profiles/profiles._scan (own-tf bars).
python3 -I -B parity_check.py <core_sig_dir> <outc_dir> <tf> <coin>"""
import sys
sys.path[:0] = ['/root/.local/lib/python3.11/site-packages', '/home/user/crypto-bot-research',
                '/home/user/crypto-bot-research/research/strategy_profiles', '/home/user/crypto-bot-research/research/paper_rules']
import numpy as np
import profiles as P
core, outc, tf, coin = sys.argv[1:5]
z = np.load(f"{core}/sig_{tf}_{coin}.npz"); b = {k: z[k] for k in ("ts", "o", "h", "l", "c", "atr")}
o = np.load(f"{outc}/out_{tf}_{coin}.npz")
f = o["feasible"]
rng = np.random.default_rng(0)
sel = np.nonzero(f)[0]; sel = rng.choice(sel, min(3000, len(sel)), replace=False)
idx = o["i"][sel].astype(int); side = o["side"][sel].astype(int); lev = o["lev"][sel].astype(float)
fill = o["fill"][sel]
# liq frac recompute from the same sizer
import precompute as PC
sz = PC.sizer(coin)
liq = np.array([sz(int(s), float(a))[1] for s, a in zip(side, o["atr_frac"][sel])])
f_bar = P.RB.FUNDING_8H * {"15m":15,"30m":30,"1h":60,"4h":240}[tf] / 480
r = P._scan(b, idx, side, lev, liq, 1024 if tf=="15m" else 512, len(b["ts"]), f_bar)
mine = o["roe"][sel]
d = r["roe"] - mine
ok = r["done"]
print(tf, coin, "n", len(sel), "exact share (|d|<1e-6):", float((np.abs(d[ok]) < 1e-6).mean()),
      "mean roe own-tf", float(r["roe"][ok].mean()), "mine(15m)", float(mine[ok].mean()))
R_own = r["roe"] * fill / (lev * o["risk"][sel])
print("mean R own-tf", float(R_own[ok].mean()), "mine", float(o["R"][sel][ok].mean()))

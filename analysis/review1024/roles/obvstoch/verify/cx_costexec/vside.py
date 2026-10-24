"""Side split of OBV30@4h>SRSI_X@1h|a2 in the last 19 days vs every-1h-close baselines (same exit, same costs):
is the +2.7 % more than 'short anything in a falling market'? Also cost x2 and 1-minute delay per side. Writes vside.json."""
import os, sys, json
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/data")
import rolesdata as RD
from common import *
HERE = os.path.dirname(os.path.abspath(__file__))
R = pd.read_csv(os.path.join(HERE, "vcx_rows.csv.gz"))
a, b = ms("2026-10-05 15:00"), ms("2026-10-24 15:00")
F = R[(R.t >= a) & (R.t < b)].copy()
sd = F.side.to_numpy()
out = {}
for v in ("x1", "x2", "d1"):
    r = np.where(sd > 0, F[f"{v}_L_r"], F[f"{v}_S_r"]); w = np.where(sd > 0, F[f"{v}_L_w"], F[f"{v}_S_w"])
    for s, nm in ((1, "long"), (-1, "short")):
        m = (sd == s) & (w != 3) & np.isfinite(r)
        out[f"{v}_{nm}"] = {"n": int(m.sum()), "mean_roe": float(30 * r[m].mean())}
# baseline: every 1h close of the 6 coins in the window, a2 grid outcome, each side (cost x1)
base = {"long": [], "short": []}
for coin in COINS:
    G = RD._grid(coin)
    n1 = len(G["a2_1h_L_r"])
    j = np.arange(n1)
    t = T0 + (j + 1) * 60 * MIN
    m = (t >= a) & (t < b)
    for lab, nm in (("L", "long"), ("S", "short")):
        r = G[f"a2_1h_{lab}_r"][m]; w = G[f"a2_1h_{lab}_why"][m]
        base[nm].append(30 * r[(w != 3) & np.isfinite(r)])
    RD._GR.pop(coin, None)
for nm in base:
    x = np.concatenate(base[nm])
    out[f"every_1h_close_{nm}"] = {"n": int(len(x)), "mean_roe": float(x.mean())}
json.dump(out, open(os.path.join(HERE, "vside.json"), "w"), indent=1)
print(json.dumps(out, indent=1))

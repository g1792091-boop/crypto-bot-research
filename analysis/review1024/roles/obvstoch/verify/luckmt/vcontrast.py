"""Verifier: day-clustered z of (OBV x SRSI family dwa) minus (other-5-trends x SRSI dwa), and of OBV30-only, per period;
plus Holm / BH across the 9 trend x SRSI families of the dwa permutation p (from vfamily.csv)."""
import os, json
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
SHM = "/dev/shm/claude_verify_obvstoch"
V = pd.read_csv(os.path.join(HERE, "vcell.csv.gz"))
OBV = ("OBV20", "OBV30", "OBV50", "OBVSL10"); OTH = ("ST", "EMA21_52", "ICHI", "J3", "J3A"); SRSI = ("SRSI_KD", "SRSI_X")


def infl(Z, ix):
    SW, NW, SA, NA = (Z[k][ix] for k in ("SW", "NW", "SA", "NA"))
    nW, nA = NW.sum(1), NA.sum(1); ok = (nW > 0) & (nA > 0)
    SW, NW, SA, NA, nW, nA = SW[ok], NW[ok], SA[ok], NA[ok], nW[ok], nA[ok]
    mW, mA = SW.sum(1) / nW, SA.sum(1) / nA
    I = (SW - NW * mW[:, None]) / nW[:, None] - (SA - NA * mA[:, None]) / nA[:, None]
    return float((mW - mA).mean()), I.mean(0), (NW.sum(0) + NA.sum(0)) > 0


out = {}
for per in ("SEL", "CONF", "FIVE", "FWD", "PRE"):
    z = np.load(os.path.join(SHM, f"vday_{per}.npz"))
    Z = {k: z[k].astype(np.float64) for k in ("SW", "NW", "SA", "NA")}
    q = V[V.period == per].reset_index(drop=True)
    ia = np.where(q.trend.isin(OBV) & q.timing.isin(SRSI))[0]
    io = np.where(q.trend.isin(OTH) & q.timing.isin(SRSI))[0]
    ma, Ia, aa = infl(Z, ia); mo, Io, ao = infl(Z, io)
    act = aa | ao; G = act.sum(); v = (Ia - Io)[act]
    se = np.sqrt((v ** 2).sum() * G / (G - 1))
    out[per] = {"famA_dwa": ma, "other5_dwa": mo, "diff": ma - mo, "diff_se": float(se), "diff_z": float((ma - mo) / se)}
R = pd.read_csv(os.path.join(HERE, "vfamily.csv"))
fams = [f"{t}_SRSI" for t in ("OBV20", "OBV30", "OBV50", "OBVSL10", "ST", "EMA21_52", "ICHI", "J3", "J3A")]
for per in ("SEL", "CONF", "FIVE", "FWD"):
    r = R[(R.period == per) & (R.block_days == 1) & R.group.isin(fams)].set_index("group").loc[fams]
    p = r.dwa_perm_p.values; m = len(p); o = np.argsort(p)
    holm = np.maximum.accumulate(np.minimum(1, (m - np.arange(m)) * p[o])); h = np.empty(m); h[o] = holm
    bq = p[o] * m / (np.arange(m) + 1); bq = np.minimum.accumulate(bq[::-1])[::-1]; b = np.empty(m); b[o] = np.minimum(bq, 1)
    out[per]["nine_fams"] = {f: {"dwa_pct": round(float(r.loc[f, "dwa"]) * 100, 3), "perm_p": round(float(r.loc[f, "dwa_perm_p"]), 4),
                                  "holm": round(float(h[i]), 4), "bh_q": round(float(b[i]), 4)} for i, f in enumerate(fams)}
print(json.dumps(out, indent=1))
json.dump(out, open(os.path.join(HERE, "vcontrast.json"), "w"), indent=1)

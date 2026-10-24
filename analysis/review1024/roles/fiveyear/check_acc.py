"""Spot check of the accumulators against a direct computation with the data layer's loader (rolesdata):
the friend's own example (1h StochRSI entries, 4h OBV condition state) and a judge source, SEL period."""
import json
from fy_common import *

meta = json.load(open(os.path.join(SHM, "meta.json")))
A = np.load(os.path.join(SHM, "acc.npy"), mmap_mode="r")
AM = np.load(os.path.join(SHM, "accm.npy"), mmap_mode="r")
nsid = len(meta["sid_name"])
SRC = [tuple(x) for x in meta["src"]]
PAIRS_ = [tuple(x) for x in meta["pairs"]]
bad = 0
for name, tf, htf, kind, src in (("O4_STOCHRSI_ZONE", "1h", "4h", "c", "OBV_S"), ("F16_FIB382", "30m", "1h", "j", "DIR"),
                                 ("F9_OB", "4h", "1d", "l", "T1_EMA50_200")):
    sid = int(RD.names().set_index("name").sid[name])
    p = PAIRS_.index((tf, htf))
    s = SRC.index((kind, src))
    S = RD.signals(names=[name], tfs=[tf], period=(ms("2021-01-01"), ms("2024-01-01")))
    S = RD.add_outcomes(S, ["w35", "w30", "w35s20", "a2"])
    ok = np.ones(len(S), bool)
    for v in ("w35", "w30", "w35s20", "a2"):
        for sfx in ("", "_opp"):
            ok &= S[f"{v}{sfx}_why"].to_numpy() != 3
    S = S[ok]
    idx = RD.htf_index(S, htf)
    nb = np.zeros(len(S), np.int64)
    for ci, coin in enumerate(COINS):
        m = (S.coin == ci).to_numpy()
        nb[m] = RD._states(coin, htf)["nb"][np.clip(idx[m], 0, None)]
    S = S[(idx >= 1) & (nb >= 300)]
    if kind == "j":
        S = RD.add_judge(S, htf=htf, check=False, min_nb=0)
        st = S.tj_dir.to_numpy()
    else:
        S = RD.add_states(S, htf, [src], kind=kind, min_nb=0)
        st = S[f"{kind}{htf}_{src}"].to_numpy()
    c = st * S.side.to_numpy()
    X = np.asarray(A[p, s]).reshape(3, nsid, NB, K)[:, sid, 0:3].sum(1)        # [cond, K]
    XM = np.asarray(AM[p, s]).reshape(3, nsid, NMON, 3)[:, sid, 0:36].sum(1)
    for ci_, cv in ((0, -1), (1, 0), (2, 1)):
        q = S[c == cv]
        d = (len(q), q.w35_roe.sum(), q.w35_opp_roe.sum(), q.a2_roe.sum())
        a = (X[ci_, SI["n"]], X[ci_, SI["w35"]], X[ci_, SI["w35o"]], X[ci_, SI["a2"]])
        am = (XM[ci_, 0], XM[ci_, 1], XM[ci_, 2])
        okk = np.allclose(d, a, rtol=1e-9, atol=1e-6) and np.allclose(d[:3], am, rtol=1e-9, atol=1e-6)
        bad += not okk
        print(name, tf, htf, kind, src, "cond", cv, "direct", np.round(d, 4), "acc", np.round(a, 4), "OK" if okk else "DIFF")
print("mismatches", bad)

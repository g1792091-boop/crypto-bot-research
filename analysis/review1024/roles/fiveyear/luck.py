"""Trend luck vs skill, and the friend's own example.

luck_table.csv: for the main judges and the friend's mappings, per period, ALL entry-role signals pooled:
  mALL   every entry signal, no filter                     mW    signals on the trend side (with)
  mWo    the coin-flip twin of the with-signals (same entries, opposite side)
  lsW    long share of the with-signals                    mDrift  what a coin flip with the same long share earns
                                                                   (all-bar long / short means of the period, entry tf)
  mT     the trend source alone at EVERY bar of the entry timeframe (no entry strategy), lsT its long share
  timing_gain = mW - mT (what the entry adds to the trend);  dir_gain = mW - mALL (what the trend adds to the entry)
friend_example.csv: StochRSI (O4) entries on 15m / 30m / 1h / 4h with every mapping, OBV condition state, with /
  against / neutral / all and the coin-flip twins, per period.
    python3 luck.py"""
from fy_analyze import *


def main():
    D = pd.read_pickle(os.path.join(SHM, "cells.pkl"))
    meta, A, AM, B, B0, BARS = load()
    SRC = [tuple(x) for x in meta["src"]]
    E = D[D.role.isin(ENTRY_ROLES)]
    want = [("j", "DIR"), ("j", "V4OF4"), ("j", "DIR_ADX20"), ("c", "OBV_S"), ("c", "V39_ALL"), ("c", "T1_EMA50_200")]
    rows = []
    for (kind, src) in want:
        s = SRC.index((kind, src))
        for p, (etf, htf) in enumerate(PAIRS):
            q = E[(E.src == s) & (E.pair == p)]
            for per in ("SEL", "CONF", "LATE", "FWD"):
                nW, nALL = q[f"{per}_nW"].sum(), q[f"{per}_nALL"].sum()
                if nW <= 0:
                    continue
                w = lambda c, n: float((q[c].fillna(0) * q[n]).sum() / q[n].sum())
                rows.append({"source": f"{kind}:{src}", "etf": etf, "htf": htf, "friend_map": (etf, htf) in FRIEND_PAIRS,
                             "per": per, "nW": nW, "nALL": nALL, "mALL": w(f"{per}_mALL", f"{per}_nALL"),
                             "mW": w(f"{per}_mW", f"{per}_nW"), "mWo": w(f"{per}_mWo", f"{per}_nW"),
                             "lsW": w(f"{per}_lsW", f"{per}_nW"), "mDrift": w(f"{per}_mDrift", f"{per}_nW"),
                             "mT": q[f"{per}_mT"].iloc[0], "lsT": q[f"{per}_lsT"].iloc[0],
                             "barL": q[f"{per}_barL"].iloc[0], "barS": q[f"{per}_barS"].iloc[0]})
    L = pd.DataFrame(rows)
    L["dir_gain"] = L.mW - L.mALL
    L["timing_gain"] = L.mW - L.mT
    L["beyond_drift"] = L.mW - L.mDrift
    L.to_csv(os.path.join(HERE, "luck_table.csv"), index=False, float_format="%.5g")
    print(L[L.friend_map & L.source.isin(["j:DIR", "j:V4OF4", "c:OBV_S"])].round(4).to_string())

    sid = int(RD.names().set_index("name").sid["O4_STOCHRSI_ZONE"])
    rows = []
    for (kind, src) in [("c", "OBV_S"), ("j", "DIR"), ("j", "V4OF4")]:
        s = SRC.index((kind, src))
        for p, (etf, htf) in enumerate(PAIRS):
            r = D[(D.src == s) & (D.pair == p) & (D.sid == sid)]
            if not len(r):
                continue
            r = r.iloc[0]
            for per in ("SEL", "CONF", "LATE", "FWD"):
                rows.append({"source": f"{kind}:{src}", "entry": f"O4_STOCHRSI_ZONE@{etf}", "htf": htf, "per": per,
                             "nW": r[f"{per}_nW"], "mW": r[f"{per}_mW"], "mWo": r[f"{per}_mWo"], "nA": r[f"{per}_nA"],
                             "mA": r[f"{per}_mA"], "nALL": r[f"{per}_nALL"], "mALL": r[f"{per}_mALL"],
                             "a2W": r[f"{per}_a2W"], "s20W": r[f"{per}_s20W"], "w30W": r[f"{per}_w30W"],
                             "tW": r.get(f"{per}_tW", np.nan)})
    F = pd.DataFrame(rows)
    F.to_csv(os.path.join(HERE, "friend_example.csv"), index=False, float_format="%.5g")
    print(F[F.source == "c:OBV_S"].round(4).to_string())


if __name__ == "__main__":
    main()

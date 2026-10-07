"""Step 1: 5-year ENTRY-level overlap of the 23 strategies (every signal, 2021-08..2026-09, 6 coins).

    python3 -I -B overlap.py <sig23.npz> <out_dir>

For an ordered pair (A, B) and a window w (15m bars): share_AB(w) = fraction of A's signals (coin, side, entry bar)
that have a B signal with the same coin and side whose entry bar is within +-w. Computed
  * per timeframe (15m, 30m, 1h; both strategies' signals of that tf): same bar (w=0), within 1 bar of that tf,
    within 4 hours (w=16);
  * on each trader's CARD scope (all its entry tfs pooled, any tf of B): same 15m entry moment (w=0), within 1 hour
    (w=4), within 4 hours (w=16).
Chance level: the same share with B's signals shifted by +-7 days (672 15m bars; keeps each stream's rate and coin-side
mix, breaks the timing), averaged over the two shifts. lift = observed / chance.
Daily R correlation: Pearson correlation of the daily SUM of every-signal net R (and gross R) on the CARD scope,
calendar days 2021-08-01..2026-09-29 (days without signals = 0).
"""
import os
import sys

sys.path[:0] = ['/root/.local/lib/python3.11/site-packages', os.path.dirname(os.path.abspath(__file__))]
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import common5 as C  # noqa: E402

SHIFT = 672
GAP = 10_000_000


def codes(d, m):
    cs = d["coin"][m].astype(np.int64) * 2 + (d["side"][m] > 0)
    return np.unique(cs * GAP + d["e"][m].astype(np.int64))


def share(A, B, w):
    if not len(A) or not len(B):
        return np.nan
    j = np.searchsorted(B, A - w, side="left")
    ok = j < len(B)
    hit = np.zeros(len(A), bool)
    hit[ok] = B[j[ok]] <= A[ok] + w
    return hit.mean()


def chance(A, B, w):
    return 0.5 * (share(A, B + SHIFT, w) + share(A, B - SHIFT, w))


def main(path, out):
    os.makedirs(out, exist_ok=True)
    d = C.load(path)
    names = list(d["names"])
    S = C.ALL
    rows = []
    # per-timeframe codes
    per_tf = {}
    for t in (0, 1, 2):
        for s in S:
            m = (d["s"] == names.index(s)) & (d["tf"] == t)
            per_tf[(s, t)] = codes(d, m)
    card = {}
    for s in S:
        m = C.scope_mask(d, {s: C.CARD[s]})
        card[s] = codes(d, m)
    for a in S:
        for b in S:
            if a == b:
                continue
            r = dict(A=a, B=b)
            for t in (0, 1, 2):
                A, B = per_tf[(a, t)], per_tf[(b, t)]
                tn = C.TF_NAMES[t]
                for lab, w in (("bar", 0), ("1bar", int(C.TF_BARS15[t])), ("4h", 16)):
                    r[f"{tn}_{lab}"] = share(A, B, w)
                    r[f"{tn}_{lab}_chance"] = chance(A, B, w)
            A, B = card[a], card[b]
            for lab, w in (("same15", 0), ("1h", 4), ("4h", 16)):
                r[f"card_{lab}"] = share(A, B, w)
                r[f"card_{lab}_chance"] = chance(A, B, w)
            r["nA_card"] = len(A)
            rows.append(r)
        print(a, flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "pair_shares.csv"), index=False, float_format="%.4f")
    # daily R
    ts = d["ts15"]
    T0 = pd.Timestamp("2021-08-01").value
    day = ((ts[d["e"]] - T0) // (86400 * 10**9)).astype(int)
    ND = int((pd.Timestamp("2026-09-30").value - T0) // (86400 * 10**9))
    dr, dg, dn = {}, {}, {}
    for s in S:
        m = C.scope_mask(d, {s: C.CARD[s]}) & (day >= 0) & (day < ND)
        dr[s] = np.bincount(day[m], weights=d["R"][m].astype(float), minlength=ND)
        dg[s] = np.bincount(day[m], weights=d["gross"][m].astype(float), minlength=ND)
        dn[s] = np.bincount(day[m], minlength=ND)
    cr = pd.DataFrame(dr).corr()
    cg = pd.DataFrame(dg).corr()
    cn = pd.DataFrame(dn).corr()
    cr.to_csv(os.path.join(out, "daily_R_corr.csv"), float_format="%.3f")
    cg.to_csv(os.path.join(out, "daily_gross_corr.csv"), float_format="%.3f")
    cn.to_csv(os.path.join(out, "daily_count_corr.csv"), float_format="%.3f")
    # per-strategy signal rates on the card scope
    rate = pd.DataFrame([dict(strategy=s, card_signals=len(card[s]), per_day=len(card[s]) / ND,
                              n15=len(per_tf[(s, 0)]), n30=len(per_tf[(s, 1)]), n1h=len(per_tf[(s, 2)]))
                         for s in S])
    rate.to_csv(os.path.join(out, "rates.csv"), index=False, float_format="%.3f")
    print("days", ND)


if __name__ == "__main__":
    main(*sys.argv[1:3])

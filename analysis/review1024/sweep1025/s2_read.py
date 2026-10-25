"""Sweep 2 reading: real vs coin-flip counts, picks on the long record read on the forward 19 days (unseen), picks
on 2020-2025 read on 2026 Jan-Sep (unseen), and the configs good on every record. Writes out/top_*.csv."""
import os, sys
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); OUTD = os.path.join(HERE, "out")
M = np.load(os.path.join(OUTD, "meta.npz"))
FN, XN, CELLS, SETS = M["FN"], M["XN"], M["cells"], M["sets"]
MODES = np.array(["양방향", "숏만", "롱만"])


def load(run):
    R = np.load(os.path.join(OUTD, f"R_{run}.npy")).astype(np.float32)
    return R.reshape(-1, 13)


def frame(R):
    n, act, hit, pos, act6, hit6, pos6, slog, lf, l1, l2, fn, fwn = R.T
    return dict(n=n, act=act, hit=hit, pos=pos, act6=act6, hit6=hit6, pos6=pos6, slog=slog, fx=np.exp(lf),
                f1=np.exp(l1), f2=np.exp(l2), fn=fn, fwin=np.where(fn > 0, fwn / np.maximum(fn, 1), 0))


def index_of(k):
    c, f, m, x = np.unravel_index(k, (len(CELLS), len(FN), 3, len(XN)))
    return CELLS[c], SETS[c], FN[f], MODES[m], XN[x]


def counts(D):
    fwd_good = (D["fn"] >= 15) & (D["fx"] >= 5) & (D["f1"] >= 1.5) & (D["f2"] >= 1.5)
    rate = np.where(D["act"] > 0, D["hit"] / np.maximum(D["act"], 1), 0)
    out = {
        "19일 x5+ (두 반 x1.5+, 15거래+)": int(fwd_good.sum()),
        "2026 1~9월 x5 달 2개+": int(((D["act6"] >= 6) & (D["hit6"] >= 2)).sum()),
        "2026 1~9월 x5 달 3개+": int(((D["act6"] >= 6) & (D["hit6"] >= 3)).sum()),
        "2020~25 x5 달 비율 10%+ (활동 30달+)": int(((D["act"] >= 30) & (rate >= 0.10)).sum()),
        "19일 x5+ 그리고 2026 x5 달 1개+": int((fwd_good & (D["hit6"] >= 1)).sum()),
        "19일 x5+ 그리고 2026 x5 달 2개+": int((fwd_good & (D["hit6"] >= 2)).sum()),
        "19일 x5+ 그리고 2026 플러스 달 5개+": int((fwd_good & (D["pos6"] >= 5)).sum()),
        "19일 x5+ 그리고 2020~25 x5 달 비율 5%+": int((fwd_good & (D["act"] >= 30) & (rate >= 0.05)).sum()),
    }
    return out, fwd_good, rate


if __name__ == "__main__":
    pd.set_option("display.width", 260); pd.set_option("display.max_colwidth", 46)
    res = {}
    D = frame(load("real")); cr, fwd_good, rate = counts(D)
    nulls = [counts(frame(load(r)))[0] for r in ("null1", "null2")]
    print("== real vs coin-flip direction (2 runs)")
    for k in cr:
        print(f"  {k}: real {cr[k]}  | flip {nulls[0][k]} / {nulls[1][k]}")
    # pick on the long record (2020-03 .. 2026-09), read the forward 19 days (not used in the pick)
    tot_act = D["act"] + D["act6"]; tot_hit = D["hit"] + D["hit6"]
    score = np.where(tot_act >= 40, tot_hit / np.maximum(tot_act, 1), -1)
    o = np.argsort(-score)
    allf = D["fx"][D["fn"] >= 10]
    print("\n== picked by goal months 2020-03..2026-09 (x5 before -50% within a calendar month), read on the 19 days")
    print(f"  all configs with 10+ forward trades: median x{np.median(allf):.2f}, share >= x1 {np.mean(allf >= 1):.0%}, >= x5 {np.mean(allf >= 5):.1%}")
    for k in (10, 100, 1000, 10000):
        sel = o[:k]; sel = sel[D["fn"][sel] >= 10]
        print(f"  top {k}: goal-month rate {score[o[k-1]]:.2%}+; forward median x{np.median(D['fx'][sel]):.2f}, "
              f">= x1 {np.mean(D['fx'][sel] >= 1):.0%}, >= x5 {np.mean(D['fx'][sel] >= 5):.1%}")
    # pick on 2020-2025, read 2026 Jan-Sep
    s25 = np.where(D["act"] >= 30, rate, -1); o25 = np.argsort(-s25)
    base6 = D["hit6"][D["act6"] >= 6] / np.maximum(D["act6"][D["act6"] >= 6], 1)
    print("\n== picked by goal months 2020-2025, read on 2026 Jan-Sep (goal-month share)")
    print(f"  all configs active 6+ months in 2026: mean goal-month share {base6.mean():.2%}")
    for k in (10, 100, 1000, 10000):
        sel = o25[:k]; sel = sel[D["act6"][sel] >= 6]
        print(f"  top {k} (2020-25 rate {s25[o25[k-1]]:.2%}+): 2026 goal-month share {np.mean(D['hit6'][sel] / D['act6'][sel]):.2%}, "
              f"positive-month share {np.mean(D['pos6'][sel] / D['act6'][sel]):.2%}")
    # the configs good on every record
    good = fwd_good & (D["hit6"] >= 1) & (D["act6"] >= 6)
    k = np.flatnonzero(good)
    rows = []
    for j in k:
        c, s, f, m, x = index_of(j)
        rows.append(dict(cell=c, set=s, filt=f, mode=m, exit=x, fwd=D["fx"][j], h1=D["f1"][j], h2=D["f2"][j], fn=D["fn"][j],
                         fwin=D["fwin"][j], hit6=D["hit6"][j], pos6=D["pos6"][j], act6=D["act6"][j], hit=D["hit"][j],
                         act=D["act"][j], rate=rate[j], n=D["n"][j], k=j))
    T = pd.DataFrame(rows)
    if len(T):
        T["score"] = T.hit6 + T.hit / np.maximum(T.act, 1) * 9
        T = T.sort_values(["hit6", "pos6", "fwd"], ascending=False)
        T.to_csv(os.path.join(OUTD, "top_allrecords.csv"), index=False)
        print(f"\n== 19 days x5+ (both halves x1.5+) AND a x5 month in 2026: {len(T)} configs, {T.cell.nunique()} cells")
        print(T.drop(columns=["k"]).head(60).round(2).to_string())

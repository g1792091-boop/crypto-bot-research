"""Verifier (claim: checks make direction worse than coin flip; hold entries 38-39 %): re-derive from the trade files.
Run: python3 vck_repro.py <trades_dir>"""
import os, sys
import numpy as np, pandas as pd
TD = sys.argv[1]
DAY = 86_400_000
def ms(s): return int(pd.Timestamp(s, tz="UTC").value // 10**6)
A, B = ms("2024-01-01"), ms("2026-10-05 15:00")
V = ["B0","B1","B2","B3","B4","B5","B6","B7","B8","B9","B10","W0","W3"]
def boot(day, x, n=5000, seed=1):
    ud, inv = np.unique(day, return_inverse=True)
    s = np.bincount(inv, weights=x); c = np.bincount(inv)
    rng = np.random.default_rng(seed); pk = rng.integers(0, len(ud), (n, len(ud)))
    return s[pk].sum(1) / np.maximum(c[pk].sum(1), 1)
def bh(p):
    p = np.asarray(p, float); m = len(p); o = np.argsort(p)
    adj = np.minimum.accumulate((p[o] * m / np.arange(1, m + 1))[::-1])[::-1]
    q = np.empty(m); q[o] = np.minimum(adj, 1); return q
rows = []
for v in V:
    T = pd.read_csv(os.path.join(TD, f"trades_{v}.csv.gz"))
    P = T[(T.t >= A) & (T.t < B)]
    d = (P.tb_roe - P.tb_opp_roe).to_numpy()
    bs = boot(P.t.to_numpy() // DAY, d)
    bs2 = boot(P.t.to_numpy() // DAY, d, seed=11)          # another seed
    rec = dict(v=v, n=len(P), own=P.tb_roe.mean(), opp=P.tb_opp_roe.mean(), diff=d.mean(),
               p_opp_better=(bs >= 0).mean(), p_opp_better_s11=(bs2 >= 0).mean(),
               p_two=2 * min((bs >= 0).mean(), (bs <= 0).mean()))
    for pn in ("select", "confirm", "late", "fwd"):
        Q = T[T.period == pn]
        rec[f"{pn}_n"] = len(Q); rec[f"{pn}_gap"] = (Q.tb_roe - Q.tb_opp_roe).mean()
        rec[f"{pn}_hold"] = (Q.j_dir == 0).mean()
    rec["hold_share_5y"] = (T[T.period.isin(["select", "confirm", "late"])].j_dir == 0).mean()
    rec["hold_share_cl"] = (P.j_dir == 0).mean()
    rows.append(rec)
R = pd.DataFrame(rows)
R["q13_one"] = bh(R.p_opp_better.clip(lower=1/5000))
R["q13_two"] = bh(R.p_two.clip(lower=1/5000))
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 40)
print(R[["v","n","own","opp","diff","p_opp_better","p_opp_better_s11","p_two","q13_one","q13_two"]].to_string())
print(R[["v","select_gap","confirm_gap","late_gap","fwd_gap","select_hold","confirm_hold","late_hold","fwd_hold","hold_share_5y","hold_share_cl"]].to_string())

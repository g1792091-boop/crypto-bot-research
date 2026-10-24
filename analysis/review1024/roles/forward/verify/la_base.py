"""Look-ahead verifier, step 8: the 'follow the trend at every bar' baseline -- reproduce it from base.pkl and
hand-check a sample of its rows (judge of the last closed higher bar, w35 walk both sides) from the raw 1m bars."""
import sys
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/forward")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) if "os" in dir() else ".")
from fw_lib import *  # noqa
from la_handcheck import my_bars, my_walk
from paperbot import trendjudge as TJ

B = load("base")
bt = pd.read_csv(os.path.join(HERE, "baseline_trend.csv"))
for tf, h in (("15m", "1h"), ("30m", "1h"), ("1h", "4h"), ("4h", "1d")):
    m = (B.tf == tf).to_numpy()
    st = state(B, "Jdir", h)
    L, Sx = roe(B, "w35"), roe(B, "w35", True)
    fol = np.where(st > 0, L, np.where(st < 0, Sx, np.nan))
    row = bt[(bt.source == "Jdir") & (bt.tf == tf) & (bt.htf == h) & (bt.period == "all")]
    print(tf, h, "bars", int(m.sum()), "follow", round(np.nanmean(fol[m]) * 100, 2), "| csv", round(float(row.w35_follow.iloc[0]) * 100, 2),
          "| share up/down", round(float(np.mean(st[m] > 0)), 3), round(float(np.mean(st[m] < 0)), 3))
rng = np.random.default_rng(5)
idx = np.sort(rng.choice(np.flatnonzero(B.w35_why.to_numpy() != 3), 24, replace=False))
P = B.loc[idx]
ok = []
for ci, coin in enumerate(COINS):
    Q = P[P.coin == ci]
    if not len(Q):
        continue
    g = grid(coin)
    for _, r in Q.iterrows():
        h = AUTO[r.tf]
        hm = TF_MIN[h] * MIN
        t = int(r.t)
        need = (t + 10_000) - (t + 10_000) % hm - hm
        j = TJ.judge_frame(my_bars(g, TF_MIN[h], [need - k * hm for k in range(299, -1, -1)]), coin, h, TJ.TrendRules())
        e_idx = (t - T0) // MIN
        rl, kl, wl = my_walk(g, e_idx, 1)
        rs, ks, ws = my_walk(g, e_idx, -1)
        ok.append((j.dir == int(np.nan_to_num(r[f"J{h}_dir"])), abs(rl - r.w35_r) < 1e-6 and kl == r.w35_k,
                   abs(rs - r.w35_opp_r) < 1e-6 and ks == r.w35_opp_k, e_idx == r.e))
    drop(coin)
print("base hand-check rows", len(ok), "judge ok / long walk ok / short walk ok / entry minute ok:", np.mean(ok, axis=0))

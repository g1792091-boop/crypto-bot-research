"""Verifier 4: placebo judges with the right regime share but the wrong timing.
For each draw, each coin's judge series on each htf is circularly shifted inside the forward window by a random
offset of 2..17 days (same offset for the coin's 1h/4h/1d series), then the pooled with-minus-against gap (w35, auto
mapping, non-trend entries) is recomputed.  p = share of placebo gaps >= the real one.  Also: always-short and
always-long on the same signals, and the with-set vs the coin-flip twin.
Run without -I: python3 v4_placebo.py [n_draws]"""
import sys
import os
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/forward")
from fw_lib import *  # noqa
import json

HERE = os.path.dirname(os.path.abspath(__file__))
ND = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
S = load("sig")
S = S[S.role != "trend"].reset_index(drop=True)
side = S.side.to_numpy()
tf = S.tf.to_numpy()
t = S.t.to_numpy(np.int64)
coin = S.coin.to_numpy()
r = roe(S, "w35")
ro = roe(S, "w35", True)
fin = np.isfinite(r) & np.isfinite(ro)
STD = os.path.join(SCR, "data", "states")
A0, A1 = FWD_A, DATA_END
L = A1 - A0
# precompute per (coin, htf) the closes and j_dir
Z = {}
for ci, cn in enumerate(COINS):
    for h in HTFS:
        z = np.load(os.path.join(STD, f"{cn}_{h}.npz"))
        Z[(ci, h)] = (z["ts"] + TF_MIN[h] * MIN, np.nan_to_num(z["j_dir"]).astype(np.int8), z["nb"])


def judge_at(ci, h, tq):
    close, d, nb = Z[(ci, h)]
    idx = np.searchsorted(close, tq, side="right") - 1
    v = d[np.maximum(idx, 0)].copy()
    v[(idx < 0) | (nb[np.maximum(idx, 0)] < 120)] = 0
    return v


def align(offsets):
    a = np.zeros(len(S), np.int8)
    for t_, h_ in AUTO.items():
        for ci in range(len(COINS)):
            m = (tf == t_) & (coin == ci)
            if not m.any():
                continue
            tq = t[m]
            if offsets is not None:
                tq = A0 + (tq - A0 + offsets[ci]) % L
            a[m] = judge_at(ci, h_, tq)
    return a * side


def gap(a):
    w, g = fin & (a == 1), fin & (a == -1)
    return r[w].mean() - r[g].mean(), r[w].mean()


a_real = align(None)
real_gap, real_with = gap(a_real)
stored = np.zeros(len(S), np.int8)
for t_, h_ in AUTO.items():
    m = tf == t_
    stored[m] = (state(S, "Jdir", h_) * side)[m]
rng = np.random.default_rng(2026)
G = []
for i in range(ND):
    off = rng.integers(2 * DAY, 17 * DAY, len(COINS))
    G.append(gap(align(off)))
G = np.array(G)
short_r = np.where(side < 0, r, ro)
long_r = np.where(side > 0, r, ro)
out = {"match_stored_judge": float(np.mean(a_real == stored)), "real_gap": float(real_gap), "real_with": float(real_with),
       "placebo_mean_gap": float(G[:, 0].mean()), "placebo_q05": float(np.quantile(G[:, 0], 0.05)),
       "placebo_q95": float(np.quantile(G[:, 0], 0.95)), "p_gap": float(np.mean(G[:, 0] >= real_gap)),
       "placebo_mean_with": float(G[:, 1].mean()), "p_with": float(np.mean(G[:, 1] >= real_with)),
       "always_short_on_signals": float(np.mean(short_r[fin])), "always_long_on_signals": float(np.mean(long_r[fin])),
       "with_set_coinflip_twin": float(np.mean(ro[fin & (a_real == 1)])),
       "against_set_flipped_to_trend_side": float(np.mean(ro[fin & (a_real == -1)])),
       "n_draws": ND}
for per, (pa, pb) in PERIOD.items():
    mp = fin & (t >= pa) & (t < pb)
    out[f"always_short_{per}"] = float(np.mean(short_r[mp]))
    out[f"with_{per}"] = float(np.mean(r[mp & (a_real == 1)]))
print(json.dumps(out, indent=1))
json.dump(out, open(os.path.join(HERE, "v4_out.json"), "w"), indent=1)

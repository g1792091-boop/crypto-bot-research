"""Luck reads for the last 19 days (descriptive, PLAN.md section 4):
 (1) In every 19-day window of 2020-03 .. 2026-10-24, the best cell's mean ROE per trade (n >= 30 in that window), for
     all 1,080 cells and for the friend's own 160 (OBV x Stoch RSI): how often is the best at least as good as the best of
     the real last 19 days?
 (2) 'Pick the best of the last 19 days, trade it the next 19 days': the next-window mean of the window winner, over
     consecutive non-overlapping 19-day windows (what the owners' way of choosing by recent results earns).
 (3) The friend's literal cells L1 / L2: the spread of their 19-day means over all windows.
 (4) The market of the last 19 days: each coin's move, and the share of short signals.
Writes luck_windows.csv, luck_summary.json."""
import json
import oscore as O
from oscore import *

D = O.load_all()
a = ms("2020-03-01")
b = ext_end()
d0 = a // DAY
nd = int((b - 1) // DAY - d0 + 1)
CELLS = O.cells()
S = np.zeros((len(CELLS), nd))
N = np.zeros((len(CELLS), nd))
for i, (tf, htf, T, Ot, X) in enumerate(CELLS):
    R = O.rows(D, tf, htf, T, Ot, X, (a, b))
    di = R["day"].astype(np.int64) - d0
    S[i] = np.bincount(di, weights=R["roe"], minlength=nd)[:nd]
    N[i] = np.bincount(di, minlength=nd)[:nd]
ids = [O.cell_id(*c) for c in CELLS]
famA = np.array([(c[2] in O.OBV_TRENDS and c[3] in O.SRSI) for c in CELLS])
W = 19
cS = np.c_[np.zeros(len(CELLS)), np.cumsum(S, 1)]
cN = np.c_[np.zeros(len(CELLS)), np.cumsum(N, 1)]
starts = np.arange(0, nd - W + 1)
wS = cS[:, starts + W] - cS[:, starts]
wN = cN[:, starts + W] - cN[:, starts]
with np.errstate(invalid="ignore", divide="ignore"):
    wM = np.where(wN >= 30, wS / wN, np.nan)
fwd_start = int(ms("2026-10-06") // DAY - d0)            # last 19 UTC days: 10-06 .. 10-24
fwd_idx = int(np.flatnonzero(starts == fwd_start)[0]) if fwd_start in starts else len(starts) - 1
best_all = np.nanmax(wM, 0)
best_A = np.nanmax(wM[famA], 0)
obs_all, obs_A = best_all[fwd_idx], best_A[fwd_idx]
past = starts < fwd_start - W                            # windows that end before the last 19 days begin
out = {"windows": int(past.sum()), "obs_best_all_last19": float(obs_all), "obs_best_A_last19": float(obs_A),
       "obs_best_all_cell": ids[int(np.nanargmax(wM[:, fwd_idx]))],
       "obs_best_A_cell": np.array(ids)[famA][int(np.nanargmax(wM[famA, fwd_idx]))],
       "share_windows_best_all_ge_obs": float(np.mean(best_all[past] >= obs_all)),
       "share_windows_best_A_ge_obs": float(np.mean(best_A[past] >= obs_A)),
       "median_best_all": float(np.nanmedian(best_all[past])), "median_best_A": float(np.nanmedian(best_A[past]))}
# (2) pick the window winner, read the next window (non-overlapping consecutive windows)
nxt = []
for s0 in range(0, nd - 2 * W + 1, W):
    w1 = np.where(N[:, s0:s0 + W].sum(1) >= 30, S[:, s0:s0 + W].sum(1) / np.maximum(N[:, s0:s0 + W].sum(1), 1), np.nan)
    if np.all(np.isnan(w1)):
        continue
    for lab, mask in (("all", np.ones(len(CELLS), bool)), ("A", famA)):
        w1m = np.where(mask, w1, np.nan)
        k = int(np.nanargmax(w1m))
        n2 = N[k, s0 + W:s0 + 2 * W].sum()
        top5 = np.argsort(-np.nan_to_num(w1m, nan=-9))[:5]
        n2t = N[top5, s0 + W:s0 + 2 * W].sum()
        nxt.append({"start": int(s0), "family": lab, "cell": ids[k], "pick_mean": float(w1m[k]),
                    "next_mean": float(S[k, s0 + W:s0 + 2 * W].sum() / n2) if n2 else np.nan, "next_n": int(n2),
                    "top5_next_mean": float(S[top5, s0 + W:s0 + 2 * W].sum() / n2t) if n2t else np.nan})
NX = pd.DataFrame(nxt)
NX["start_day"] = pd.to_datetime((NX.start + d0) * DAY, unit="ms").dt.date
NX.to_csv("luck_windows.csv", index=False)
for lab in ("all", "A"):
    q = NX[NX.family == lab]
    out[f"pick_winner_{lab}_mean_pick"] = float(q.pick_mean.mean())
    out[f"pick_winner_{lab}_mean_next"] = float(q.next_mean.mean())
    out[f"pick_winner_{lab}_share_next_pos"] = float((q.next_mean > 0).mean())
    out[f"pick_top5_{lab}_mean_next"] = float(q.top5_next_mean.mean())
    out[f"pick_winner_{lab}_pairs"] = int(len(q))
# (3) friend literal cells over all 19-day windows
for lab, cell in (("L1", "OBV30@1h>SRSI_KD@30m|w35"), ("L2", "OBV30@4h>SRSI_KD@1h|w35")):
    k = ids.index(cell)
    m = wM[k][past]
    out[f"{lab}_19d_mean_median"] = float(np.nanmedian(m))
    out[f"{lab}_19d_share_pos"] = float(np.nanmean(m > 0))
    out[f"{lab}_19d_best"] = float(np.nanmax(m))
    out[f"{lab}_19d_last"] = float(wM[k][fwd_idx])
# (4) the market of the last 19 days
mk = {}
for coin in COINS:
    df = bars(coin, "1h")
    c = df.close.to_numpy()
    t = close_ms(df, "1h")
    i0 = np.searchsorted(t, ms("2026-10-05 15:00"))
    i1 = np.searchsorted(t, ms("2026-10-24 14:00"), side="right") - 1
    mk[coin] = float(c[i1] / c[i0] - 1)
    drop(coin)
out["market_move_last19"] = mk
json.dump(out, open("luck_summary.json", "w"), indent=1)
print(json.dumps(out, indent=1))

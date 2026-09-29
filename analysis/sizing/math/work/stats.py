"""Part 1: volatility / path statistics per TF (pooled over 7 coins, IS only),
liquidation & TP distances vs ATR, per-bar and H-bar adverse-excursion liquidation odds, fee drag."""
import json
import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view as swv
from common import *

HS = [1, 4, 16, 64]
rows, rows_coin, rows_mae, rows_bar = [], [], [], []
sig = {}
for tf in TFS:
    atr_all, mv = [], {H: [] for H in HS}
    mae = {H: [] for H in HS}          # max adverse excursion from entry at open[t] over bars t..t+H-1 (both dirs)
    mfe1 = []                          # favourable excursion within the entry bar (both dirs)
    lr1 = []
    for sym in COINS:
        df = load(sym, tf)
        o, h, l, c = (df[k].values for k in ["open", "high", "low", "close"])
        atr = atr_wilder(df)
        a = atr[~np.isnan(atr)]
        atr_all.append(a)
        rows_coin.append(dict(tf=tf, sym=sym, bars=len(df), atr14_med_pct=100 * np.median(a)))
        lr1.append(np.diff(np.log(c)))
        for H in HS:
            mv[H].append(np.abs(c[H:] / c[:-H] - 1))
            mn = swv(l, H).min(axis=1)
            mxx = swv(h, H).max(axis=1)
            oo = o[:len(mn)]
            mae[H].append(np.r_[1 - mn / oo, mxx / oo - 1])   # long MAE, short MAE
        mfe1.append(np.r_[h / o - 1, 1 - l / o])
    A = np.concatenate(atr_all)
    lr = np.concatenate(lr1)
    sig[tf] = float(np.std(lr))
    r = dict(tf=tf, n_bars=int(sum(len(x) + 1 for x in lr1)), atr14_med_pct=100 * np.median(A),
             atr14_p10_pct=100 * np.quantile(A, .1), atr14_p90_pct=100 * np.quantile(A, .9),
             sd_1bar_logret_pct=100 * sig[tf])
    for H in HS:
        m = np.concatenate(mv[H])
        r[f"absmove_H{H}_med_pct"] = 100 * np.median(m)
        r[f"absmove_H{H}_p90_pct"] = 100 * np.quantile(m, .9)
    rows.append(r)
    atr_med = np.median(A)
    M1 = np.concatenate(mfe1)
    for L in LEVS:
        dl, tp = d_liq(L), tp_dist(L)
        rb = dict(tf=tf, L=L, d_liq_pct=100 * dl, tp_pct=100 * tp,
                  tp_over_atr=tp / atr_med, liq_over_atr=dl / atr_med,
                  share_bars_atr_gt_dliq=float(np.mean(A > dl)),
                  share_bars_atr_gt_tp=float(np.mean(A > tp)),
                  p_entrybar_fav_exc_ge_tp=float(np.mean(M1 >= tp)))
        for H in HS:
            MA = np.concatenate(mae[H])
            rb[f"p_liq_hold{H}"] = float(np.mean(MA >= dl))
        rows_bar.append(rb)

st = pd.DataFrame(rows)
st.to_csv(f"{OUT}/tf_vol_stats.csv", index=False)
pd.DataFrame(rows_coin).to_csv(f"{OUT}/tf_atr_by_coin.csv", index=False)
bb = pd.DataFrame(rows_bar)
bb.to_csv(f"{OUT}/tf_L_distances.csv", index=False)
json.dump(sig, open(f"{OUT}/sd_1bar.json", "w"), indent=1)

# fee drag per round trip, % of equity
fd = []
for M in MARGINS:
    for L in LEVS:
        fd.append(dict(M=M, L=L, notional_x_equity=M * L, fee_drag_rt_pct_equity=100 * M * L * RT,
                       fee_drag_rt_pct_margin=100 * L * RT,
                       liq_loss_pct_equity=100 * M * (1 + L * C_MKT)))
pd.DataFrame(fd).to_csv(f"{OUT}/fee_drag.csv", index=False)

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)
print(st.round(3).to_string(index=False))
print()
print(bb.round(3).to_string(index=False))
print()
print(pd.DataFrame(fd).pivot(index="M", columns="L", values="fee_drag_rt_pct_equity").round(2))

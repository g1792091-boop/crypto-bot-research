"""참고 read for the owners' scale-up / stop rule (docs/vwap-bot-ko.md §6: "50번 승률 80% 이상이면 키우기, 71% 아래면
멈추기"): on the live bot's own 5-year paper trades (vwmonth2.paper_trades: deploy/combo.vwap.json, one position, A's
gates and exits, 2020-03 .. the data end), does a good or bad stretch of 50 trades say anything about the next 50?

For every point i (after 50 trades, before the last 50): the win rate of trades i-50 .. i-1 ("지난 50번") and of trades
i .. i+49 ("다음 50번": win rate, mean net ROE per trade at the trade's own leverage, and the compound result at margin
40 %). Grouped by the past win rate: under 71 %, 71-80 %, 80 % and over. The same on non-overlapping blocks of 50 (block
k -> block k+1: fewer, but each pair counted once). Also: past win rate at or above 75 / 80 / 85 / 88 / 90 % and past
net ROE sum above / below zero as the condition; how often a 50-trade stretch reaches 80 % / 92.5 % (37 of 40); the
break-even win rate from the average win and loss.

    python3 -I vwscale.py   -> research/vwap30/scale.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
import json
import numpy as np
from vwmonth2 import paper_trades, RES_DIR, DATA_END

N = 50
MARGIN = 0.4
BANDS = (("71% 미만", 0.0, 0.71), ("71~80%", 0.71, 0.80), ("80% 이상", 0.80, 1.01))


def summary(past, nxt_win, nxt_roe, nxt_mult):
    out = {}
    for name, lo, hi in BANDS:
        k = (past >= lo) & (past < hi)
        if not k.any():
            out[name] = {"n": 0}
            continue
        out[name] = {"n": int(k.sum()), "next_win": round(float(nxt_win[k].mean()), 4),
                     "next_roe_per_trade": round(float(nxt_roe[k].mean()), 5),
                     "next_mult_median": round(float(np.median(nxt_mult[k])), 4),
                     "next_up_share": round(float((nxt_mult[k] > 1).mean()), 4)}
    out["전체"] = {"n": int(len(past)), "next_win": round(float(nxt_win.mean()), 4),
                 "next_roe_per_trade": round(float(nxt_roe.mean()), 5),
                 "next_mult_median": round(float(np.median(nxt_mult)), 4),
                 "next_up_share": round(float((nxt_mult > 1).mean()), 4)}
    return out


def main():
    T = paper_trades()
    roe = (T.lev.to_numpy() * T.r.to_numpy())
    win = roe > 0
    n = len(T)
    c = np.r_[0, np.cumsum(win.astype(int))]
    lg = np.r_[0.0, np.cumsum(np.log(np.maximum(1 + MARGIN * roe, 1e-12)))]
    cr = np.r_[0.0, np.cumsum(roe)]
    i = np.arange(N, n - N + 1)
    past = (c[i] - c[i - N]) / N
    nxt_win = (c[i + N] - c[i]) / N
    nxt_roe = (cr[i + N] - cr[i]) / N
    nxt_mult = np.exp(lg[i + N] - lg[i])
    b = np.arange(N, n - N + 1, N)                      # non-overlapping blocks: [b-N, b) -> [b, b+N)
    bp, bw = (c[b] - c[b - N]) / N, (c[b + N] - c[b]) / N
    br, bm = (cr[b + N] - cr[b]) / N, np.exp(lg[b + N] - lg[b])
    all50 = (c[np.arange(N, n + 1)] - c[np.arange(0, n - N + 1)]) / N
    past_roe = (cr[i] - cr[i - N]) / N
    thr = {}
    for t in (0.75, 0.80, 0.85, 0.88, 0.90):             # "지난 50번 승률 t 이상" (overlapping), cumulative
        k = past >= t
        thr[f"승률 {t:.0%} 이상"] = {"n": int(k.sum()), "share": round(float(k.mean()), 4)} | (
            {"next_win": round(float(nxt_win[k].mean()), 4), "next_roe_per_trade": round(float(nxt_roe[k].mean()), 5),
             "next_mult_median": round(float(np.median(nxt_mult[k])), 4), "next_up_share": round(float((nxt_mult[k] > 1).mean()), 4)}
            if k.any() else {})
    for name, k in (("지난 50번 순ROE 합 플러스", past_roe > 0), ("지난 50번 순ROE 합 마이너스", past_roe <= 0)):
        thr[name] = {"n": int(k.sum()), "share": round(float(k.mean()), 4), "next_win": round(float(nxt_win[k].mean()), 4),
                     "next_roe_per_trade": round(float(nxt_roe[k].mean()), 5),
                     "next_mult_median": round(float(np.median(nxt_mult[k])), 4),
                     "next_up_share": round(float((nxt_mult[k] > 1).mean()), 4)}
    aw, al = roe[win].mean(), roe[~win].mean()
    out = {"data_end": DATA_END, "trades": int(n), "margin": MARGIN, "n": N,
           "win_rate": round(float(win.mean()), 4), "avg_win_roe": round(float(aw), 4), "avg_loss_roe": round(float(al), 4),
           "breakeven_win": round(float(-al / (aw - al)), 4),
           "stretches": {"count": int(len(all50)), "share_80_or_more": round(float((all50 >= 0.80).mean()), 4),
                         "share_925_or_more": round(float((all50 >= 0.925).mean()), 4),
                         "share_under_71": round(float((all50 < 0.71).mean()), 4)},
           "corr_past_next_win": round(float(np.corrcoef(past, nxt_win)[0, 1]), 4),
           "overlapping": summary(past, nxt_win, nxt_roe, nxt_mult), "thresholds": thr,
           "blocks": summary(bp, bw, br, bm)}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    json.dump(out, open(os.path.join(RES_DIR, "scale.json"), "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()

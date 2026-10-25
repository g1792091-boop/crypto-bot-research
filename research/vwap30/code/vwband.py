"""참고 read for the live checks' "운이냐 고장이냐" band (owners 10-25: "vwap 개선판봇 … 연구분석이나 손실 분석 … 전부 다
만들어줘"): on the live bot's own 5-year paper trades (vwmonth2.paper_trades: deploy/combo.vwap.json, one position, A's
gates and exits, 2020-03 .. the data end; the same 5,805 trades as scale.json), the distributions a live record is put
against (paperbot/vwapband.py reads the output; nothing here is a rule):

    win      the 5-year win rate (the binomial band's p) and, for stretches of n consecutive trades (every start), how
             many stretches had 0 .. n wins (the empirical band: it keeps the 5 years' good and bad spells together)
    streaks  every losing run (consecutive trades with net ROE <= 0) by its length, the longest, and how many runs
             reached k or more
    dd       for stretches of n consecutive trades started fresh (every start), the deepest drop of the account from its
             running peak (margin 40 % of the account per trade, compounding: g = 0.4 x net ROE), counted in 1 % bins
    pick17   the 17 days the bot was picked on (2026-10-05 19:30 UTC .. the data end; the rule bot's run): its trades,
             wins, longest losing run, result and deepest drop on the same account — the picked best period, not a
             yardstick

The per-trade sequence is kept in the scratchpad (OUT/band_trades.pkl), never in the repository.

    python3 -I vwband.py   -> research/vwap30/band.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
import json
import numpy as np
from vwmonth2 import paper_trades, RES_DIR, DATA_END, OUT, ms

MARGIN = 0.4
START17 = ms("2026-10-05T19:30")                     # the rule bot's run (vwlive19.START): the 17 days A+CMO was picked on
GRID = (2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50, 60, 70, 80, 100, 120, 150, 200, 250, 300, 400, 500)
DD_BINS = 100                                        # 1 % bins of the deepest drop (0 .. 100 %)


def runs(win: np.ndarray) -> list:
    """The lengths of the losing runs (consecutive False) in trade order."""
    out, k = [], 0
    for w in win:
        if w:
            if k:
                out.append(k)
            k = 0
        else:
            k += 1
    if k:
        out.append(k)
    return out


def deepest(lg: np.ndarray) -> float:
    """The deepest drop from the running peak of an account started at 1.0, from its log equity after each trade."""
    peak = np.maximum.accumulate(np.r_[0.0, lg])[1:]
    return float(1.0 - np.exp((lg - peak).min())) if len(lg) else 0.0


def main():
    path = os.path.join(OUT, "band_trades.pkl")
    if os.path.exists(path) and os.path.getmtime(path) > os.path.getmtime(os.path.abspath(__file__)):
        import pandas as pd
        T = pd.read_pickle(path)
    else:
        T = paper_trades()
        T.to_pickle(path)
    roe = T.lev.to_numpy() * T.r.to_numpy()
    win = roe > 0
    g = MARGIN * roe
    n = len(T)
    lgc = np.r_[0.0, np.cumsum(np.log(np.maximum(1 + g, 1e-12)))]
    c = np.r_[0, np.cumsum(win.astype(int))]
    aw, al = roe[win].mean(), roe[~win].mean()
    rl = runs(win)
    by_len = {str(k): int(sum(1 for x in rl if x == k)) for k in range(1, max(rl) + 1)}
    reach = {str(k): int(sum(1 for x in rl if x >= k)) for k in range(1, max(rl) + 1)}
    windows = {}
    for m in GRID:
        if m > n:
            break
        s = np.arange(0, n - m + 1)
        wins_hist = np.bincount((c[s + m] - c[s]).astype(int), minlength=m + 1)
        dds = np.empty(len(s))
        for i in s:
            lg = lgc[i + 1:i + m + 1] - lgc[i]
            peak = np.maximum.accumulate(np.r_[0.0, lg])[1:]
            dds[i] = 1.0 - np.exp((lg - peak).min())
        bins = np.bincount(np.minimum((dds * DD_BINS).astype(int), DD_BINS - 1), minlength=DD_BINS)
        windows[str(m)] = {"count": int(len(s)), "wins": [int(x) for x in wins_hist], "dd_bins": [int(x) for x in bins],
                           "dd_median": round(float(np.median(dds)), 4), "dd_p90": round(float(np.quantile(dds, 0.9)), 4),
                           "dd_p95": round(float(np.quantile(dds, 0.95)), 4), "dd_p99": round(float(np.quantile(dds, 0.99)), 4),
                           "dd_max": round(float(dds.max()), 4)}
        print(m, windows[str(m)]["dd_median"], windows[str(m)]["dd_p95"], flush=True)
    k17 = T.t.to_numpy() >= START17
    w17, g17 = win[k17], g[k17]
    lg17 = np.cumsum(np.log(1 + g17))
    pick17 = {"from_ms": START17, "to_ms": DATA_END, "n": int(k17.sum()), "wins": int(w17.sum()), "losses": int((~w17).sum()),
              "win_rate": round(float(w17.mean()), 4), "longest_losing_run": int(max(runs(w17) or [0])),
              "mult": round(float(np.exp(lg17[-1])), 4), "max_dd": round(deepest(lg17), 4)}
    out = {"data_end": DATA_END, "trades": int(n), "margin": MARGIN, "from_ms": int(T.t.min()), "to_ms": int(T.t.max()),
           "wins": int(win.sum()), "win_rate": round(float(win.mean()), 4), "avg_win_roe": round(float(aw), 4),
           "avg_loss_roe": round(float(al), 4), "breakeven_win": round(float(-al / (aw - al)), 4),
           "roe_per_trade": round(float(roe.mean()), 5), "whole_run_mult": float(np.exp(lgc[-1])),
           "whole_run_max_dd": round(deepest(lgc[1:]), 4),
           "streaks": {"runs": len(rl), "longest": int(max(rl)), "by_len": by_len, "reach": reach},
           "windows": windows, "dd_bins": DD_BINS, "pick17": pick17}
    print(json.dumps({k: v for k, v in out.items() if k != "windows"}, ensure_ascii=False, indent=1), flush=True)
    json.dump(out, open(os.path.join(RES_DIR, "band.json"), "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()

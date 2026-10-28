"""The friend bot as it runs (PLAN.md 1): both rules (the friend's first), the second rule as of 10-27 (Stoch RSI 14/11/4/6
cross + MOM(10)), stop ATR(14, 30m) x 3, net ROE ladder 10 -> 8 then every 5 %, its coins, leverage, margin 40 %, entry
blocks, fees, one position, through the bot's own code (research/mixchop_st: study.run_window), month windows
2021-10 .. 2026-09 from $50 (each month's last position followed to its exit). Same set-up as rule1027.py's NEW|both.
Writes every trade of every month: OUT/friend_trades.json.
    python3 -E -P analysis/gate1028/friend_trades.py --out OUT [--jobs 4]
Research code: nothing here trades."""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path[:0] = [os.path.join(REPO, "research", "mixchop_st")]
import numpy as np  # noqa: E402

import grid as Gd  # noqa: E402
S, R, M = Gd.S, Gd.R, Gd.M

NEW = (dict(rsi=14, stoch=11, k=4, d=6), 10)        # rule1027.VARIANTS["NEW"]
LADDER = (10, 8, 5)
NAME = "NEW|both"


def signals(co, a30, a1h, p, mom_len, lo, hi):
    """rule1027.signals: the second rule's crosses, kept when MOM(mom_len) of the 30m closes agrees with the side."""
    sig = S.new_signals(co, a30, a1h, p, lo, hi)
    ce = a30[:, 0].astype(np.int64) + M.MIN30
    m = M.mom(a30[:, 4], mom_len)
    keep = {}
    for t, e in sig.items():
        i = int(np.searchsorted(ce, t))
        if np.isfinite(m[i]) and m[i] * e["side"] > 0:
            e = dict(e)
            e["mom"] = round(float(m[i]), 6)
            keep[t] = e
    return keep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    cfg = M.load_config(R.CONFIG)
    coins = list(cfg.coins)
    a30 = {c.symbol: R.read_klines(R.DATA, c.symbol, "30m") for c in coins}
    a1h = {c.symbol: R.read_klines(R.DATA, c.symbol, "1h") for c in coins}
    mos = [m for m in R.months() if "2021-10" <= m <= "2026-09"]
    m1 = {c.symbol: S.read_1m(R.DATA, c.symbol, mos) for c in coins}
    friend, _ = S.friend_decisions(coins, a30, a1h, os.path.join(R.DATA, "npy", "friend_decisions_v2.pkl"))
    lo, hi = R.T0 - 2 * 86_400_000, R.T1 + 30 * 86_400_000
    p, ml = NEW
    new = {c.symbol: signals(c, a30[c.symbol], a1h[c.symbol], p, ml, lo, hi) for c in coins}
    S.G.update(coins=coins, bars30=a30, m1=m1)
    Gd.plan(coins, new, friend, [(NAME, "both", 3.0, 3.0, LADDER, None)])
    res = Gd.run_names([NAME], S.month_bounds(), a.jobs)[NAME]
    out = [{"t0": r["t0"], "end_eq": r["end_eq"], "trades": r["trades"]} for r in sorted(res, key=lambda r: r["t0"])]
    json.dump(out, open(os.path.join(a.out, "friend_trades.json"), "w"), ensure_ascii=False)
    st = Gd.split_stats(res)
    print("months", len(out), "trades", sum(len(r["trades"]) for r in out),
          "choose median", st["choose"]["median_x"], "check median", st["check"]["median_x"], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

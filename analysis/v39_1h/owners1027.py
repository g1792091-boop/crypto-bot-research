"""Owners 10-27: "고정익절 15%면 그럼 어떻게 되는건데?" (after "v3.9봇은 거의 하루에 1번 진입을 하니까 익절가를 20%로 잡은건데 좀
불안해가지고 익절가를 줄여야 하나 싶어서"). owners1025h.py's 30 days (the paper's 20 days + the 10 days before, not looked at
when the ladder was chosen) with the Toobit plan (40 % margin, BTC 40x / others 30x, stop 2.5 ATR, liquidation guard, Toobit
costs, $50, one position), the exit only changed: the ladder as it runs (20 -> 17, 25 -> 22, ...), the rule bot's ladder
(12 -> 10, then 5 % steps) and a fixed take-profit at net +10 / +15 / +20 % (closed at market: sim's maker fee = taker +
slippage, as owners1025c sets it). Only the account table of owners1025h (its later reads are not repeated).
Later the same day, "V 3.9 지금 확보선 순 17%로 바꾸면 어떻게 돼?": a fixed take-profit at net +17 % (the ladder's first lock) and the
ladder moved down to start there (17 -> 14, 22 -> 19, then 5 % steps) were added; the other rows are unchanged.

    python3 owners1027.py <export_dir> <out_dir> <bars_dir>     -> tp_thirty.csv, tp_thirty_trades.csv
"""
import os
import sys

import numpy as np
import pandas as pd

H = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, H)
import features as F  # noqa: E402
import owners1025c as C  # noqa: E402  (argv: export, out)
from sim import Variant as V  # noqa: E402

OUT, BARS = sys.argv[2], sys.argv[3]
DAY = 86_400_000
W = C.W
_P = dict(step=0.05, next_gap=0.03, stop_atr=2.5, lev_btc=40, lev_alt=30, frac=0.40)
LADDERS = {"B 20→17 (지금)": V("B", first_lock=0.17, gap=0.03, next_trigger=0.25, **_P),
           "L 12→10 (규칙봇 계단)": V("L", first_lock=0.10, gap=0.02, **_P),
           "F10 고정 +10%": V("F10", tp="ROE", tp_val=0.10, ladder=False, **_P),
           "F15 고정 +15%": V("F15", tp="ROE", tp_val=0.15, ladder=False, **_P),
           "F20 고정 +20%": V("F20", tp="ROE", tp_val=0.20, ladder=False, **_P),
           "F17 고정 +17%": V("F17", tp="ROE", tp_val=0.17, ladder=False, **_P),
           "B17 계단 17→14": V("B17", first_lock=0.14, gap=0.03, next_trigger=0.22, **_P)}

live = C.signals(("1h",))
t20 = min(d["bar_close"] for d in live) - 1                     # the paper record's first 1h signal close
END = W.end_ms
T30 = END - 30 * DAY

# ---- public 1m bars (and funding) before the export's first minute, put in front of the export's arrays
for sym, a in W.A.items():
    z = np.load(os.path.join(BARS, "1m", f"{sym}.npz"))
    k = z["ts"] < a["ts"][0]
    f5 = np.load(os.path.join(BARS, "5m", f"{sym}.npz"))
    fund = np.zeros(int(k.sum()))
    pos = {int(t): i for i, t in enumerate(z["ts"][k])}
    for t, r in zip(f5["ts"], f5["fund"]):
        if r != 0 and int(t) in pos:
            fund[pos[int(t)]] += r
    for key in ("o", "h", "l", "c", "mo", "mh", "ml", "mc"):
        a[key] = np.r_[z[key][k], a[key]]
    a["ts"] = np.r_[z["ts"][k], a["ts"]]
    a["fund"] = np.r_[fund, a["fund"]]
    a["src_live"] = np.r_[np.zeros(int(k.sum()), bool), a["src_live"]]

# ---- V3.9 1h signals made again from public bars
made = []
for sym in W.A:
    g = F.v39_signals(F.hourly(os.path.join(BARS, "5m"), sym))
    for r in g.itertuples(index=False):
        made.append({"symbol": sym, "bar_close": int(r.close_ms) + 1 if int(r.close_ms) % 1000 else int(r.close_ms),
                     "side": int(r.side), "atr": float(r.atr), "best": bool(r.best), "timeframe": "1h"})
M = pd.DataFrame(made)
# the close time convention: the live log's bar_close is the bar's close (open + 1h); v39_signals' close_ms the same
lv = pd.DataFrame([{"symbol": d["symbol"], "bar_close": d["bar_close"], "side": d["side"], "atr": d["atr"]} for d in live])
in20 = M[(M.bar_close >= t20) & (M.bar_close <= lv.bar_close.max())]
both = in20.merge(lv, on=["symbol", "bar_close", "side"], how="outer", indicator=True)
match = {"paper_signals": len(lv), "made_signals": len(in20), "same": int((both._merge == "both").sum()),
         "paper_only": int((both._merge == "right_only").sum()), "made_only": int((both._merge == "left_only").sum())}
print("20일 신호 대조:", match, flush=True)

prio = {s: k for k, s in enumerate(W.S.symbol_priority)}
before = []
for r in M[(M.bar_close >= T30) & (M.bar_close < t20)].itertuples(index=False):
    A = W.A[r.symbol]
    e = int(np.searchsorted(A["ts"], r.bar_close))
    if e >= len(A["ts"]):
        continue
    before.append({"sig_id": -1, "bar_close": int(r.bar_close), "timeframe": "1h", "symbol": r.symbol, "side": int(r.side),
                   "atr": float(r.atr), "ref_price": float(A["o"][e]), "best": bool(r.best)})
before.sort(key=lambda d: (d["bar_close"], prio.get(d["symbol"], 99)))
print(f"30일 시작 {C.L.kst(T30)} · 페이퍼 시작 {C.L.kst(t20)} · 끝 {C.L.kst(END)} · 앞 10일 신호 {len(before)}개", flush=True)

rows, trades = [], []
for name, v in LADDERS.items():
    C.V = v
    o10, e10 = C.account(before)                                # the 10 days before, from $50
    o20, _ = C.account(live)                                    # the paper's 20 days, from $50
    o30, e30 = C.account(before + live)                         # 30 days in one account, from $50
    rows.append({"ladder": name, **{f"d10_{k}": o10[k] for k in ("trades", "wins", "stops", "open", "final")},
                 **{f"d20_{k}": o20[k] for k in ("trades", "wins", "stops", "open", "final")},
                 **{f"d30_{k}": o30[k] for k in ("trades", "wins", "stops", "open", "final", "dd_pct", "worst_pct")}})
    print(rows[-1], flush=True)
    e30 = e30.assign(ladder=name)
    trades.append(e30[["ladder", "kst", "symbol", "side", "lev", "reason", "lock_roe", "roe", "pnl", "equity_before",
                       "equity_after"]])
pd.DataFrame(rows).to_csv(os.path.join(OUT, "tp_thirty.csv"), index=False)
pd.concat(trades).to_csv(os.path.join(OUT, "tp_thirty_trades.csv"), index=False)

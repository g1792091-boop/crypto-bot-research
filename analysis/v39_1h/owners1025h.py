"""Owners 10-25 night: "그럼 만약 30일까지 갔으면 수익 몇%였어?" The owners' final plan (40 % margin, BTC 40x / others 30x,
stop 2.5 ATR from the fill, ladder from 20 -> 17, liquidation guard, Toobit costs, $50, one position, 1h signals) over
the last 30 days: the 20 days of the paper record (its own signal log and live bars, as owners1025c) and the 10 days
before it, where V3.9's 1h signals are made again by the locked V3.9 code (features.v39_signals on 1h bars built from
public 5m bars) and traded on public 1m bars (fetch_bars.py minute; funding from the monthly funding files). Those 10
days were not looked at when the ladder was chosen, so they are a small unseen check of 15->13 / 20->17 / 25->22.
Also: how well the re-made signals match the paper's own in the 20 days.

    python3 owners1025h.py <export_dir> <out_dir> <bars_dir>     (bars_dir: fetch_bars.py --cache with 5m/ and 1m/)
Writes thirty_days.csv, thirty_days_trades.csv, thirty_days_before_alone.csv (and prints the margin-share and
entry-timing checks)."""
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
LADDERS = {"A 15→13": V("A", first_lock=0.13, gap=0.02, next_trigger=0.20, **_P),
           "B 20→17 (계획)": V("B", first_lock=0.17, gap=0.03, next_trigger=0.25, **_P),
           "C 25→22": V("C", first_lock=0.22, gap=0.03, next_trigger=0.30, **_P)}

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
pd.DataFrame(rows).to_csv(os.path.join(OUT, "thirty_days.csv"), index=False)
pd.concat(trades).to_csv(os.path.join(OUT, "thirty_days_trades.csv"), index=False)

# ---- the 10 days before, every signal alone (no one-position path): how far each went before its stop, and each ladder
COST = C.S[0] + C.S[1]
alone_rows = []
for d in before:
    sym = d["symbol"]
    A = W.A[sym]
    e = W.entry_index(sym, d["bar_close"])
    row = {"kst": C.L.kst(d["bar_close"]), "symbol": sym.replace("USDT", ""), "side": d["side"]}
    C.V = V("run", ladder=False, **_P)
    if C.beyond_liq(d):
        row["status"] = "guard"
        alone_rows.append(row)
        continue
    r = C.sim.run_one(C.S, C.br[sym], A, e, d["ref_price"], d["side"], d["atr"], d["best"], 50.0, C.specs[sym], C.V, sym)
    row["status"] = r["reason"]
    row["peak"] = round((d["side"] * (r["best_px"] - r["fill"]) / r["fill"] - 2 * COST) * r["lev"], 4)
    for name, v in LADDERS.items():
        q = C.sim.run_one(C.S, C.br[sym], A, e, d["ref_price"], d["side"], d["atr"], d["best"], 50.0, C.specs[sym], v, sym)
        row[name] = round(q["ret"], 4)
        row[name + " why"] = q["reason"]
    alone_rows.append(row)
AL = pd.DataFrame(alone_rows)
AL.to_csv(os.path.join(OUT, "thirty_days_before_alone.csv"), index=False)
ok = AL[AL.status.isin(["SL", "OPEN"])]
print("앞 10일 신호 따로:", len(AL), "개, 청산가 확인으로 건너뜀", int((AL.status == "guard").sum()))
print("  손절 전 최고 순ROE (손절로 끝난 것):", " ".join(f"{x:+.0%}" for x in sorted(ok[ok.status == "SL"].peak)))
print("  끝까지 손절 안 난 것:", " ".join(f"{x:+.0%}" for x in sorted(ok[ok.status == "OPEN"].peak)))
for name in LADDERS:
    x = ok[name]
    print(f"  {name}: 이익 {int((x > 0).sum())} · 손절 {int((ok[name + ' why'] == 'SL').sum())} · 신호당 평균 {100 * x.mean():+.2f}%")

# ---- 30 days in one account with a smaller margin share (ladder B), and the entry timings on the 10 days before
import entries as EN  # noqa: E402
import pandas as pd
print("== 증거금 비율 (계단 B, 30일 한 계좌)")
for fr in (0.4, 0.3, 0.2, 0.1):
    C.V = V("B", first_lock=0.17, gap=0.03, next_trigger=0.25, **{**_P, "frac": fr})
    o10, _ = C.account(before); o20, _ = C.account(live); o30, _ = C.account(before + live)
    print(f"  {fr:.0%}: 앞10일 ${o10['final']}  20일 ${o20['final']}  30일 ${o30['final']} (최대낙폭 {o30['dd_pct']}%, 손절 {o30['stops']})")
print("== 앞 10일, 진입 방법 (신호 따로, 계단 B)")
C.V = V("B", first_lock=0.17, gap=0.03, next_trigger=0.25, **_P)
for kind, p, lab in (("now", {}, "지금"), ("wait", {"min": 15}, "15분 기다림"), ("wait", {"min": 60}, "1시간 기다림"),
                     ("pullback", {"x": 0.5, "win": 240}, "0.5ATR 되돌림 4시간"), ("confirm", {"bar": 15, "win": 120}, "15분봉 확인")):
    rs = []
    for d in before:
        if C.beyond_liq(d):
            continue
        A = W.A[d["symbol"]]
        x = EN.entry(kind, p, A, d["bar_close"], d["side"], d["atr"], d["ref_price"], 60_000)
        if x is None:
            rs.append(("NONE", 0.0)); continue
        r = C.sim.run_one(C.S, C.br[d["symbol"]], A, x[0], x[1], d["side"], d["atr"], d["best"], 50.0, C.specs[d["symbol"]], C.V, d["symbol"])
        rs.append((r["reason"], r["ret"]))
    k = pd.DataFrame(rs, columns=["why", "ret"])
    print(f"  {lab}: 탄 것 {int((k.why != 'NONE').sum())} · 이익 {int((k.ret > 0).sum())} · 손절 {int((k.why == 'SL').sum())} · 신호당 {100 * k.ret.mean():+.2f}%")

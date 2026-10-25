"""Owners 10-25 night, 20 days only (no 5-year): "20일동안 제일 근접한 익절기준이 뭐야? ... 손절1번 난거 보완은 안하는건가?"
Every V3.9 1h signal of the 20 days taken alone (not only the 23 the one-position account took), the owners' plan
otherwise (40 % margin, BTC 40x / others 30x, liquidation guard, Toobit costs, from $50):
- how far each one went (net ROE) before its stop, with the stop at 2 / 2.5 / 3 ATR: the share that reaches +15, +20,
  +25, +30 %; the deepest move against (ATR) of the ones that came good;
- every ladder start (12 .. 40 %, lock 2 or 3 % under, then every +5 % the lock 3 % under) and fixed take-profits,
  stop 2.5 ATR: wins, stops, mean result a signal, and the same for the first and the second 10 days.
Writes all61_peaks.csv, all61_ladders.csv."""
import os
import sys

import numpy as np
import pandas as pd

H = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, H)
import owners1025c as C  # noqa: E402  (argv: export, out)
from sim import Variant as V  # noqa: E402

OUT = sys.argv[2]
_P = dict(lev_btc=40, lev_alt=30, frac=0.40)
sigs = C.signals(("1h",))
COST = C.S[0] + C.S[1]                      # taker + slippage, a side
MID = (C.W.start_ms + C.W.end_ms) // 2


def alone(d, v):
    sym = d["symbol"]
    A = C.W.A[sym]
    e = C.W.entry_index(sym, d["bar_close"])
    if e >= len(A["ts"]):
        return None
    C.V = v
    if C.beyond_liq(d):
        return {"status": "GUARD"}
    r = C.sim.run_one(C.S, C.br[sym], A, e, d["ref_price"], d["side"], d["atr"], d["best"], 50.0, C.specs[sym], v, sym)
    if r["reason"] == "REJECTED":
        return None
    r["status"] = "ENTERED"
    return r


# ---------------------------------------------------------------- how far each signal went before its stop
peaks = []
for d in sigs:
    row = {"kst": C.L.kst(d["bar_close"]), "symbol": d["symbol"].replace("USDT", ""), "side": d["side"],
           "half": 1 if d["bar_close"] < MID else 2}
    for k in (2.0, 2.5, 3.0):
        r = alone(d, V(f"run_s{k}", ladder=False, stop_atr=k, **_P))
        if r is None or r["status"] != "ENTERED":
            row[f"s{k:g}"] = "skip" if r is None else "guard"
            continue
        side, fill, lev = d["side"], r["fill"], r["lev"]
        row[f"s{k:g}"] = r["reason"]
        row[f"peak_s{k:g}"] = round((side * (r["best_px"] - fill) / fill - 2 * COST) * lev, 4)
        row[f"worst_atr_s{k:g}"] = round(side * (r["worst_px"] - fill) / d["atr"], 3)
    peaks.append(row)
P = pd.DataFrame(peaks)
P.to_csv(os.path.join(OUT, "all61_peaks.csv"), index=False)

print("signals", len(P))
for k in ("2", "2.5", "3"):
    ok = P[P[f"s{k}"].isin(["SL", "OPEN", "LIQ"])]
    pk = ok[f"peak_s{k}"]
    line = " ".join(f"+{t}%: {int((pk >= t / 100).sum())}" for t in (10, 13, 15, 20, 25, 30, 40, 50))
    print(f"stop {k} ATR: entered {len(ok)}, stopped {int((ok[f's{k}'] == 'SL').sum())}, still open {int((ok[f's{k}'] == 'OPEN').sum())}"
          f" | reached before the stop: {line}")
    never = ok[(ok[f"s{k}"] == "SL")].sort_values(f"peak_s{k}")
    print("   stopped, peak before the stop:", " ".join(f"{x:+.0%}" for x in never[f"peak_s{k}"]))

# ---------------------------------------------------------------- ladders and fixed take-profits, each signal alone
VARS = []
for trig in (12, 15, 17, 20, 22, 25, 27, 30, 35, 40):
    for lg in (2, 3):
        f = trig - lg
        VARS.append((f"L{trig}>{f}", f"{trig}%→{f}%, 이후 5%마다 3% 아래",
                     V(f"L{trig}>{f}", first_lock=f / 100, gap=lg / 100, step=0.05, next_trigger=(trig + 5) / 100,
                       next_gap=0.03, stop_atr=2.5, **_P)))
for tp in (13, 15, 20, 25, 30):
    VARS.append((f"TP{tp}", f"고정 익절 +{tp}%", V(f"TP{tp}", ladder=False, tp="ROE", tp_val=tp / 100, stop_atr=2.5, **_P)))
rows = []
for name, label, v in VARS:
    rs = []
    for d in sigs:
        r = alone(d, v)
        if r is None or r["status"] != "ENTERED":
            continue
        rs.append({"half": 1 if d["bar_close"] < MID else 2, "ret": r["ret"], "reason": r["reason"]})
    k = pd.DataFrame(rs)
    out = {"variant": name, "label": label, "n": len(k), "wins": int((k.ret > 0).sum()),
           "stops": int((k.reason == "SL").sum()), "open": int((k.reason == "OPEN").sum()),
           "mean_ret_pct": round(100 * k.ret.mean(), 2)}
    for h in (1, 2):
        g = k[k.half == h]
        out[f"h{h}_n"] = len(g)
        out[f"h{h}_stops"] = int((g.reason == "SL").sum())
        out[f"h{h}_mean_pct"] = round(100 * g.ret.mean(), 2)
    rows.append(out)
R = pd.DataFrame(rows)
R.to_csv(os.path.join(OUT, "all61_ladders.csv"), index=False)
pd.set_option("display.width", 250)
print(R.to_string(index=False))

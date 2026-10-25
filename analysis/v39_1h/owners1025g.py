"""Owners 10-25 night, 20 days only (no 5-year): "진입타점 보완은 건들면 안되겠지??" The market-order entry timings of
variants.ENTRY (wait, pullback, confirm; no limit orders) again, now with the owners' final plan (40 % margin, BTC 40x /
others 30x, stop 2.5 ATR from the fill, ladder 20->17, 25->22, 30->27 ..., liquidation guard, Toobit costs, $50, one
position, 1h signals): the one-position account, and every 1h signal taken alone (how many of them each timing
misses, wins, stops). Writes entry_plan.csv."""
import os
import sys

import pandas as pd

H = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, H)
import entries as EN  # noqa: E402
import owners1025c as C  # noqa: E402  (argv: export, out)
import variants as VR  # noqa: E402
from sim import Variant as V  # noqa: E402

OUT = sys.argv[2]
PLAN = V("plan_B", first_lock=0.17, gap=0.03, step=0.05, next_trigger=0.25, next_gap=0.03, stop_atr=2.5,
         lev_btc=40, lev_alt=30, frac=0.40)
C.V = PLAN
sigs = C.signals(("1h",))


def at(d, kind, p):
    """(bar index, raw price) of the entry, or None when the timing never came."""
    return EN.entry(kind, p, C.W.A[d["symbol"]], d["bar_close"], d["side"], d["atr"], d["ref_price"], 60_000)


def account(kind, p, eq0=50.0):
    """owners1025c.account with the entry timing: one position, a signal while busy skipped."""
    wallet, busy, rows = eq0, -1, []
    for d in sigs:
        sym = d["symbol"]
        A = C.W.A[sym]
        x = at(d, kind, p)
        if x is None:
            continue
        e, raw = x
        if int(A["ts"][e]) <= busy or C.beyond_liq(d):
            continue
        r = C.sim.run_one(C.S, C.br[sym], A, e, raw, d["side"], d["atr"], d["best"], wallet, C.specs[sym], PLAN, sym)
        if r["reason"] == "REJECTED":
            continue
        busy = int(A["ts"][int(r["j"])]) if r["reason"] != "OPEN" else 2 ** 62
        rows.append({"pnl": r["pnl"], "reason": r["reason"], "eb": wallet})
        wallet += r["pnl"]
    k = pd.DataFrame(rows)
    return {"acct_trades": len(k), "acct_wins": int((k.pnl > 0).sum()), "acct_stops": int((k.reason == "SL").sum()),
            "acct_open": int((k.reason == "OPEN").sum()), "acct_final": round(wallet, 2),
            "acct_worst_pct": round(100 * float((k.pnl / k.eb).min()), 1) if len(k) else 0.0}


def alone(kind, p):
    """Every 1h signal alone from $50: entered / never came, wins, stops, mean result a signal (0 when not entered)."""
    res = []
    for d in sigs:
        if C.beyond_liq(d):
            continue
        x = at(d, kind, p)
        if x is None:
            res.append({"status": "NONE", "ret": 0.0})
            continue
        e, raw = x
        sym = d["symbol"]
        r = C.sim.run_one(C.S, C.br[sym], C.W.A[sym], e, raw, d["side"], d["atr"], d["best"], 50.0, C.specs[sym], PLAN, sym)
        if r["reason"] == "REJECTED":
            res.append({"status": "NONE", "ret": 0.0})
            continue
        res.append({"status": r["reason"], "ret": r["ret"]})
    k = pd.DataFrame(res)
    ent = k[k.status != "NONE"]
    return {"sig_n": len(k), "sig_entered": len(ent), "sig_none": int((k.status == "NONE").sum()),
            "sig_wins": int((ent.ret > 0).sum()), "sig_stops": int((ent.status == "SL").sum()),
            "sig_mean_pct": round(100 * k.ret.mean(), 2)}


rows = []
for name, label, kind, p in VR.ENTRY:
    rows.append({"variant": name, "label": label, **account(kind, p), **alone(kind, p)})
    print(rows[-1], flush=True)
R = pd.DataFrame(rows)
R.to_csv(os.path.join(OUT, "entry_plan.csv"), index=False)
pd.set_option("display.width", 250)
print(R.drop(columns=["label"]).to_string(index=False))

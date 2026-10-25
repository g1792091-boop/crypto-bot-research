"""Owners 10-25 night, 20 days only (no 5-year): stop 2.5 ATR with the ladder 15->13, 20->17, 25->22, ... against the
fixed +15% take-profit, the owners' sizing (40% margin, BTC 40x / others 30x), Toobit costs from $50 and paper costs
from $5,000; and the same with an entry guard: no entry whose stop sits beyond the liquidation price."""
import json
import os
import sys
from dataclasses import replace

import pandas as pd

H = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, H)
sys.path.insert(0, os.path.dirname(os.path.dirname(H)))
import extras as E  # noqa: E402
import v39lib as L  # noqa: E402
import variants as VR  # noqa: E402

EXPORT, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)
W = L.Window(EXPORT)
P = {v.name: v for v in VR.PLAN}
rows = [("고정 익절 15% · 손절 2ATR", "p_roe15_s2"), ("고정 익절 15% · 손절 2.5ATR", "p_roe15_s2.5"),
        ("계단 15→13·20→17·25→22 · 손절 2.5ATR (제안)", "p_lad15_s2.5"), ("계단 15→13·20→17·25→22 · 손절 2ATR", "p_lad15_s2"),
        ("지금 계단 12→10 · 손절 2.5ATR", "p_ladder_s2.5"), ("지금 계단 12→10 · 손절 2ATR", "p_ladder")]


def guard_fn(v, mmr_of):
    """No entry when the stop (stop_atr x ATR from the fill) sits at or beyond the liquidation distance at the forced
    leverage (isolated: 1/leverage - maintenance margin rate of the first bracket)."""
    def fn(d):
        sym = d["symbol"]
        lev = v.lev_btc if sym == "BTCUSDT" else v.lev_alt
        fill = d["ref_price"]
        if v.stop_atr * d["atr"] / fill >= 1.0 / lev - mmr_of[sym]:
            return None
        return W.entry_index(sym, d["bar_close"]), d["ref_price"]
    return fn


S, br = L.kernel_vectors(W)
mmr = {s: float(br[s][0, 2]) for s in br}
out = []
for label, name in rows:
    v = P[name]
    for guard in (False, True):
        for cost, eq0 in (("toobit_slip3", 50.0), ("paper", 5000.0)):
            Sset = E.plan_settings(W, cost)
            if cost != "paper":
                # the executor closes a take-profit with a market order (no resting limit order): taker fee and slippage
                # on that exit, not the paper engine's maker fill at the level
                Sset = replace(Sset, maker_fee=Sset.taker_fee + Sset.slippage_frac)
            k = L.kernel_account(W, v, entry_fn=guard_fn(v, mmr) if guard else None, equity0=eq0,
                                 settings=Sset, specs=W.specs if cost == "paper" else E.plan_specs("A"))
            ent = k[k["status"] == "ENTERED"]
            eq = ent["equity_after"].to_numpy(float)
            r = ent["reason"].value_counts().to_dict()
            ret = ent["pnl"] / ent["equity_before"]
            out.append({"plan": label, "variant": name, "guard": guard, "cost": cost, "start": eq0,
                        "trades": int(len(ent)), "tp_or_lock": int(r.get("TP", 0) + r.get("LOCK", 0)), "sl": int(r.get("SL", 0)),
                        "liq": int(r.get("LIQ", 0)), "open": int(r.get("OPEN", 0)), "no_entry": int((k["status"] == "NO_ENTRY").sum()),
                        "final": float(eq[-1]) if len(eq) else eq0, "ret_pct": 100 * (float(eq[-1]) / eq0 - 1) if len(eq) else 0.0,
                        "dd_pct": 100 * L.max_drawdown(eq, eq0) if len(eq) else 0.0,
                        "worst_pct": 100 * float(ret.min()) if len(ret) else 0.0, "best_pct": 100 * float(ret.max()) if len(ret) else 0.0,
                        "mean_win_pct": 100 * float(ret[ent["pnl"] > 0].mean()) if (ent["pnl"] > 0).any() else 0.0,
                        "lock_roes": sorted(round(100 * x) for x in ent["lock_roe"] if x == x and x > 0)})
R = pd.DataFrame(out)
R.to_csv(os.path.join(OUT, "ladder_vs_tp.csv"), index=False)
pd.set_option("display.width", 250)
print(R.drop(columns=["lock_roes"]).round(2).to_string())
print(json.dumps({r["plan"] + ("|guard" if r["guard"] else ""): r["lock_roes"] for r in out if r["cost"] == "toobit_slip3"},
                 ensure_ascii=False))

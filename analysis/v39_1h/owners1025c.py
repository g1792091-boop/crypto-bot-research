"""Owners 10-25 night, 20 days only (no 5-year): more entries with ONE position. The owners' plan (40% margin,
BTC 40x / others 30x, stop 2.5 ATR, ladder 15->13, 20->17, 25->22, 30->27, ... net ROE, entry skipped when the stop
sits beyond liquidation), Toobit costs from $50, against:
- more V3.9 signals: the same strategy's 30m (and 4h, 15m) signals into the same one position;
- 갈아타기: a new signal while the position already holds a lock (>= +13 %) closes it at market and takes the new one.
"""
import json
import os
import sys
from dataclasses import replace

import numpy as np
import pandas as pd

H = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, H)
sys.path.insert(0, os.path.dirname(os.path.dirname(H)))
import extras as E  # noqa: E402
import sim  # noqa: E402
import v39lib as L  # noqa: E402
import variants as VR  # noqa: E402

EXPORT, OUT = sys.argv[1], sys.argv[2]
W = L.Window(EXPORT)
V = {v.name: v for v in VR.PLAN}["p_lad15_s2.5"]
Sset = E.plan_settings(W, "toobit_slip3")
Sset = replace(Sset, maker_fee=Sset.taker_fee + Sset.slippage_frac)
S, br = L.kernel_vectors(W, Sset)
specs = E.plan_specs("A")
MMR = {s: float(br[s][0, 2]) for s in br}
TF_PRIO = {"1h": 0, "30m": 1, "4h": 2, "15m": 3}


def signals(tfs):
    """V3.9's submitted signals of these timeframes (the rule bot's own signal log), in time order: at the same
    minute the 1h one first, then the 30m, then the coin order the bot uses."""
    from paperbot.daily3 import make_signal
    from paperbot.levrule import signal_group
    sig = pd.read_csv(os.path.join(EXPORT, "current", "signal_log.csv"), low_memory=False)
    s = sig[(sig["strategy"] == L.STRATEGY) & (sig["timeframe"].isin(tfs)) & (sig["status"] == "SUBMITTED")]
    ctx = {}
    ids = set(int(x) for x in s["id"])
    with open(os.path.join(EXPORT, "current", "signal_ctx.jsonl")) as fh:
        for line in fh:
            d = json.loads(line)
            if int(d.get("id", -1)) in ids:
                ctx[int(d["id"])] = d.get("ctx")
    out = []
    for r in s.itertuples(index=False):
        d = {"sig_id": int(r.id), "bar_close": int(r.bar_close), "timeframe": r.timeframe, "strategy": r.strategy,
             "symbol": r.symbol, "side": int(r.side), "atr": float(r.atr), "ref_price": float(r.ref_price),
             "ref_time": int(r.ref_time), "delay_ms": int(r.delay_ms)}
        c = ctx.get(int(r.id))
        d["data"] = {"ctx": c} if c else {}
        d["best"] = signal_group(make_signal(d))["group"] == "best"
        out.append(d)
    prio = {s_: k for k, s_ in enumerate(W.S.symbol_priority)}
    out.sort(key=lambda d: (d["bar_close"], TF_PRIO.get(d["timeframe"], 9), prio.get(d["symbol"], 99)))
    return out


def beyond_liq(d):
    lev = V.lev_btc if d["symbol"] == "BTCUSDT" else V.lev_alt
    return V.stop_atr * d["atr"] / d["ref_price"] >= 1.0 / lev - MMR[d["symbol"]]


def account(sigs, rotate_lock=None, eq0=50.0):
    wallet, cur, rows = eq0, None, []
    for d in sigs:
        sym = d["symbol"]
        A = W.A[sym]
        e = W.entry_index(sym, d["bar_close"])
        if e >= len(A["ts"]):
            continue
        t_fill = int(A["ts"][e])
        if cur is not None and t_fill <= cur["busy_until"]:
            if rotate_lock is None or t_fill == cur["t_fill"] or beyond_liq(d):
                continue
            # 갈아타기: the open position as of this minute; only one that already holds a lock is closed at market
            CA = W.A[cur["symbol"]]
            end = int(np.searchsorted(CA["ts"], t_fill))
            part = sim.run_one(S, br[cur["symbol"]], CA, cur["e"], cur["raw"], cur["side"], cur["atr"], cur["best"],
                               cur["wallet"], specs[cur["symbol"]], V, cur["symbol"], end=end)
            if part["reason"] != "OPEN" or not part["lock_roe"] >= rotate_lock - 1e-12:
                continue
            rows[-1].update(reason="ROTATE", pnl=part["pnl"], exit_ts=int(CA["ts"][end - 1]))
            wallet = cur["wallet"] + part["pnl"]
            rows[-1]["equity_after"] = wallet
            cur = None
        if beyond_liq(d):
            rows.append({"status": "GUARD", "tf": d["timeframe"]})
            continue
        r = sim.run_one(S, br[sym], A, e, d["ref_price"], d["side"], d["atr"], d["best"], wallet, specs[sym], V, sym)
        if r["reason"] == "REJECTED":
            continue
        r.update(status="ENTERED", symbol=sym, tf=d["timeframe"], side=d["side"], equity_before=wallet,
                 kst=L.kst(d["bar_close"]))
        cur = {"symbol": sym, "e": e, "raw": d["ref_price"], "side": d["side"], "atr": d["atr"], "best": d["best"],
               "wallet": wallet, "t_fill": t_fill,
               "busy_until": int(A["ts"][int(r["j"])]) if r["reason"] != "OPEN" else 2 ** 62}
        wallet += r["pnl"]
        r["equity_after"] = wallet
        rows.append(r)
    k = pd.DataFrame(rows)
    ent = k[k["status"] == "ENTERED"] if len(k) else k
    eq = ent["equity_after"].to_numpy(float)
    days = (W.end_ms - W.start_ms) / L.DAY
    rs = ent["reason"].value_counts().to_dict()
    return {"trades": int(len(ent)), "per_day": round(len(ent) / days, 2),
            "wins": int((ent["pnl"] > 0).sum()), "losses": int((ent["pnl"] <= 0).sum()),
            "stops": int(rs.get("SL", 0)), "liq": int(rs.get("LIQ", 0)), "rotated": int(rs.get("ROTATE", 0)),
            "open": int(rs.get("OPEN", 0)), "guard_skips": int((k["status"] == "GUARD").sum()) if len(k) else 0,
            "by_tf": {tf: f"{len(g)}번 {int((g['pnl'] > 0).sum())}승" for tf, g in ent.groupby("tf")},
            "final": round(float(eq[-1]), 2) if len(eq) else eq0,
            "ret_pct": round(100 * (float(eq[-1]) / eq0 - 1), 1) if len(eq) else 0.0,
            "dd_pct": round(100 * L.max_drawdown(eq, eq0), 1) if len(eq) else 0.0,
            "worst_pct": round(100 * float((ent["pnl"] / ent["equity_before"]).min()), 1) if len(ent) else 0.0}, ent


CASES = [("1시간만 (지금 계획)", ("1h",), None), ("1시간 + 30분", ("1h", "30m"), None),
         ("1시간 + 4시간", ("1h", "4h"), None), ("1시간 + 30분 + 4시간", ("1h", "30m", "4h"), None),
         ("1시간 + 15분", ("1h", "15m"), None),
         ("1시간만 + 갈아타기 (잠금 +13% 이상이면)", ("1h",), 0.13), ("1시간만 + 갈아타기 (잠금 +17% 이상이면)", ("1h",), 0.17),
         ("1시간 + 30분 + 갈아타기 (+13%)", ("1h", "30m"), 0.13)]
res = []
for label, tfs, rot in (CASES if __name__ == "__main__" else ()):
    sg = signals(tfs)
    out, ent = account(sg, rot)
    out = {"case": label, "signals": len(sg), **out}
    res.append(out)
    ent.drop(columns=[c for c in ent.columns if c in ("status",)]).to_csv(
        os.path.join(OUT, f"more_entries_{len(res)}.csv"), index=False)
    print(json.dumps(out, ensure_ascii=False))
if __name__ == "__main__":
    pd.DataFrame(res).to_csv(os.path.join(OUT, "more_entries.csv"), index=False)

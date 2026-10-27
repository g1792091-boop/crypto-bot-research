#!/usr/bin/env python3
"""V3.9 1h + the 4h-OBV direction filter (PLAN.md): signals, the arms, the random-drop twins, the verdict.

    python3 -E -P run.py --five FIVE5M/5m --new NEWV/5m --work OBVWORK --m1 M1/1m --export RULEBOT_EXPORT --out OUT

OBVWORK: analysis/obv1027/prep.py's work folder (its 5m arrays a5_<SYM>.npz are the trades' bars). Outputs in OUT:
arms.csv (arm x exit x period), alone.csv (per-signal means), months.csv, result.json (verdict, twins, signal check).
Research code: nothing here trades.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "analysis", "obv1027"))
import prep as PR  # noqa: E402  (bars, judges, closed-bar lookups of the OBV study)
import obvsim as O  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import features as F  # noqa: E402
import sim  # noqa: E402

H1, H4 = 3_600_000, 14_400_000
ARMS = {"A0": "V3.9 1시간 그대로", "A1": "4시간봉 OBV 같은 방향만", "A2": "1시간봉 OBV 같은 방향만",
        "A3": "4시간봉 추세판단 3표 같은 방향만"}
PERIODS = {"y2020": O.PERIODS["y2020"], "pick": O.PERIODS["pick"], "check": O.PERIODS["check"]}
RECENT = (O.ms("2026-09-27"), O.ms("2026-10-27"))
TWINS = 200
EXITS = {"TBX": (O.EXITS["T0"], "tb", 50.0, 1.0), "RBX": (O.RBX, "bin", 5000.0, 10.0)}


def log(*a):
    print(*a, flush=True)


def signals(five: str, new: str) -> pd.DataFrame:
    rows = []
    for s in O.SYMBOLS:
        z = PR.load(five, new, s)
        h1, h4 = PR.bars(z, H1), PR.bars(z, H4)
        g = F.v39_signals(h1)
        J1, J4 = PR.judges_of(h1), PR.judges_of(h4)
        t = g["close_ms"].to_numpy(np.int64)
        k1 = PR.at_closed(h1["close_ms"].to_numpy(np.int64), t)
        k4 = PR.at_closed(h4["close_ms"].to_numpy(np.int64), t)
        sd = g["side"].to_numpy(int)
        obv1, obv4 = PR.take(J1["OBV"], k1), PR.take(J4["OBV"], k4)
        up4, dn4 = PR.take(J4["up"], k4), PR.take(J4["down"], k4)
        rows.append(pd.DataFrame({"symbol": s, "close_ms": t, "side": sd, "atr": g["atr"].to_numpy(float),
                                  "best": g["best"].to_numpy(bool), "obv1h": obv1, "obv4h": obv4,
                                  "A0": True, "A1": obv4 * sd > 0, "A2": obv1 * sd > 0,
                                  "A3": np.where(sd > 0, up4 >= 3, dn4 >= 3)}))
        log(s, len(g), "V3.9 1h signals")
    G = pd.concat(rows, ignore_index=True)
    prio = {s: k for k, s in enumerate(O.SYMBOLS)}
    G["prio"] = G["symbol"].map(prio)
    return G.sort_values(["close_ms", "prio"]).reset_index(drop=True)


def signal_check(G: pd.DataFrame, export: str) -> dict:
    sig = pd.read_csv(os.path.join(export, "current", "signal_log.csv"), low_memory=False)
    s = sig[(sig["strategy"] == "V39_ALL") & (sig["timeframe"] == "1h") & (sig["status"] == "SUBMITTED")]
    lo, hi = int(s["bar_close"].min()), int(s["bar_close"].max())
    g = G[(G["close_ms"] >= lo) & (G["close_ms"] <= hi)]
    a = set(zip(s["symbol"], s["bar_close"].astype(np.int64), s["side"].astype(int)))
    b = set(zip(g["symbol"], g["close_ms"].astype(np.int64), g["side"].astype(int)))
    return {"bot": len(a), "study": len(b), "same": len(a & b), "bot_only": sorted(map(str, a - b))[:5],
            "study_only": sorted(map(str, b - a))[:5]}


def acct(B, G, mask, v, mode, start, bust):
    T = B.account(G[mask].reset_index(drop=True), v, mode, start, bust)
    return T, O.stats(T, start, bust)


def alone_means(B, G, v, mode, start) -> np.ndarray:
    Sv = B.Sv_bin if mode == "bin" else B.Sv_tb
    specs = B.specs_bin if mode == "bin" else B.specs_tb
    e_idx = B.entry_index(G)
    out = np.full(len(G), np.nan)
    for k, r in enumerate(G.itertuples(index=False)):
        A, e = B.A[r.symbol], int(e_idx[k])
        if e >= len(A["ts"]):
            continue
        raw = float(A["o"][e])
        if mode == "tb":
            lev = v.lev_btc if r.symbol == "BTCUSDT" else v.lev_alt
            if v.stop_atr * r.atr / raw >= 1.0 / lev - B.mmr[r.symbol]:
                continue
        res = sim.run_one(Sv, B.br[r.symbol], A, e, raw, int(r.side), float(r.atr), bool(r.best), start, specs[r.symbol],
                          v, r.symbol, bar_ms=B.bar_ms)
        if res["reason"] != "REJECTED":
            out[k] = res["roe"]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    for k in ("five", "new", "work", "m1", "export", "out"):
        ap.add_argument("--" + k, required=True)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    G = signals(a.five, a.new)
    G.to_csv(os.path.join(a.out, "signals.csv"), index=False)
    res = {"signal_check": signal_check(G, a.export)}
    log("signal check", res["signal_check"])
    B5 = O.Book.five(a.work)
    t = G["close_ms"].to_numpy(np.int64)
    rows, al_rows, month_rows = [], [], []
    for xname, (v, mode, start, bust) in EXITS.items():
        al = alone_means(B5, G, v, mode, start)
        for p, (lo, hi) in PERIODS.items():
            pm = (t >= lo) & (t < hi)
            for arm in ARMS:
                m = pm & G[arm].to_numpy(bool)
                _T, st = acct(B5, G, m, v, mode, start, bust)
                rows.append({"arm": arm, "exit": xname, "period": p, "signals": int(m.sum()), **st})
                x = al[m]
                al_rows.append({"arm": arm, "exit": xname, "period": p, "taken": int(np.isfinite(x).sum()),
                                "mean_roe": float(np.nanmean(x)) if np.isfinite(x).any() else np.nan,
                                "win": float(np.nanmean(x[np.isfinite(x)] > 0)) if np.isfinite(x).any() else np.nan})
        log("5y", xname)
    R = pd.DataFrame(rows)
    AL = pd.DataFrame(al_rows)
    # random-drop twins of A1 (Toobit plan), pick and check
    v, mode, start, bust = EXITS["TBX"]
    verdict = {}
    for p in ("pick", "check"):
        lo, hi = PERIODS[p]
        pm = (t >= lo) & (t < hi)
        idx = np.flatnonzero(pm)
        keep_n = int((pm & G["A1"].to_numpy(bool)).sum())
        xs = []
        for i in range(TWINS):
            rng = np.random.default_rng(271 + i)
            m = np.zeros(len(G), bool)
            m[rng.choice(idx, size=keep_n, replace=False)] = True
            _T, st = acct(B5, G, m, v, mode, start, bust)
            xs.append(st["x"])
        xs = np.array(xs)
        r0 = R[(R.arm == "A0") & (R.exit == "TBX") & (R.period == p)].iloc[0]
        r1 = R[(R.arm == "A1") & (R.exit == "TBX") & (R.period == p)].iloc[0]
        m0 = AL[(AL.arm == "A0") & (AL.exit == "TBX") & (AL.period == p)].iloc[0]
        m1 = AL[(AL.arm == "A1") & (AL.exit == "TBX") & (AL.period == p)].iloc[0]
        tests = {"x_above_A0": bool(r1["x"] > r0["x"]), "x_above_twin95": bool(r1["x"] > np.quantile(xs, 0.95)),
                 "alone_roe_above_A0": bool(m1["mean_roe"] > m0["mean_roe"]),
                 "grew_no_bust": bool(r1["x"] > 1 and not r1["bust"])}
        verdict[p] = {"keep_share": keep_n / max(1, len(idx)), "A0_x": float(r0["x"]), "A1_x": float(r1["x"]),
                      "twin_x_p50": float(np.median(xs)), "twin_x_p95": float(np.quantile(xs, 0.95)),
                      "twin_share_beaten": float((r1["x"] > xs).mean()), "A0_alone_roe": float(m0["mean_roe"]),
                      "A1_alone_roe": float(m1["mean_roe"]), "tests": tests}
        log("twins", p, verdict[p])
    helps = all(all(verdict[p]["tests"][k] for k in ("x_above_A0", "x_above_twin95", "alone_roe_above_A0"))
                for p in ("pick", "check"))
    usable = helps and all(verdict[p]["tests"]["grew_no_bust"] for p in ("pick", "check"))
    res.update(verdict=verdict, helps=helps, usable_live=usable)
    # goal months (2024-01 .. 2026-09), $50 fresh each month, Toobit plan
    lo, hi = PERIODS["check"]
    for arm in ARMS:
        for m0 in pd.date_range(pd.Timestamp(lo, unit="ms", tz="UTC"), pd.Timestamp(hi, unit="ms", tz="UTC"),
                                freq="MS")[:-1]:
            m1_ = m0 + pd.offsets.MonthBegin(1)
            mm = (t >= m0.value // 10**6) & (t < m1_.value // 10**6) & G[arm].to_numpy(bool)
            _T, st = acct(B5, G, mm, v, mode, start, bust)
            month_rows.append({"arm": arm, "month": m0.strftime("%Y-%m"), **st})
    M = pd.DataFrame(month_rows)
    # recent 30 days on 1m bars
    B1 = O.Book.minute(a.m1, a.work)
    rm = (t >= RECENT[0]) & (t < RECENT[1])
    rec = []
    for xname, (v_, mode_, start_, bust_) in EXITS.items():
        for arm in ARMS:
            m = rm & G[arm].to_numpy(bool)
            T, st = acct(B1, G, m, v_, mode_, start_, bust_)
            rec.append({"arm": arm, "exit": xname, "signals": int(m.sum()), **st,
                        "open_at_end": int((T["reason"] == "OPEN").sum()) if len(T) else 0})
            if arm in ("A0", "A1") and xname == "TBX":
                T.assign(entry=pd.to_datetime(T["entry_ts"] + 9 * H1, unit="ms")).to_csv(
                    os.path.join(a.out, f"recent_trades_{arm}.csv"), index=False)
    R.to_csv(os.path.join(a.out, "arms.csv"), index=False)
    AL.to_csv(os.path.join(a.out, "alone.csv"), index=False)
    M.to_csv(os.path.join(a.out, "months.csv"), index=False)
    pd.DataFrame(rec).to_csv(os.path.join(a.out, "recent.csv"), index=False)
    json.dump(res, open(os.path.join(a.out, "result.json"), "w"), ensure_ascii=False, indent=1, default=float)
    log("helps", helps, "usable", usable)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

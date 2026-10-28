#!/usr/bin/env python3
"""Toobit V3.9 1h with a signal light (PLAN.md): the rule bot's V39_ALL@1h paper over 2020-01 .. 2026-10-26 (rule-bot
exits, $5,000, refilled to $5,000 below $500), the light on its closed trades, the Toobit plan following the lit paper
entries, month accounts, one account per period, random-skip twins, the verdict.

    python3 -E -P analysis/gate1028/run_v39.py --five FIVE5M/5m --new NEWV/5m --work OBVWORK --out OUT

FIVE5M / NEWV / OBVWORK: analysis/obv1027's 5m bars and work folder (as analysis/v39obv1027). Outputs in OUT:
result.json, months.csv (exact month accounts), paper.csv (the paper's trades with each light).
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
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "analysis", "v39obv1027"))
import run as VR  # noqa: E402  (V3.9 1h signals from the 5m bars; obvsim and sim on the path)
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import gate as GT  # noqa: E402

O, sim = VR.O, VR.sim
TBX = O.EXITS["T0"]
REFILL, PAPER_START = 500.0, 5000.0
PERIODS = {"y2020": ("2020-01-01", "2021-01-01"), "pick": ("2021-01-01", "2024-01-01"),
           "check": ("2024-01-01", "2026-10-01"), "oct": ("2026-10-01", "2026-11-01")}


def log(*a):
    print(*a, flush=True)


def months(a: str, b: str) -> list:
    d = pd.date_range(pd.Timestamp(a, tz="UTC"), pd.Timestamp(b, tz="UTC"), freq="MS")
    return [(int(x.value // 10**6), int(y.value // 10**6)) for x, y in zip(d[:-1], d[1:])]


def paper(B, G: pd.DataFrame) -> pd.DataFrame:
    """The rule bot's account on every signal, one position; refilled to $5,000 when it ends below $500."""
    parts, i0 = [], 0
    close = G["close_ms"].to_numpy(np.int64)
    while i0 < len(G):
        T = B.account(G.iloc[i0:].reset_index(drop=True), O.RBX, "bin", PAPER_START, REFILL)
        if not len(T):
            break
        T = T.assign(k=T["k"] + i0)
        parts.append(T)
        if T["after"].iloc[-1] >= REFILL:
            break
        i0 = int(np.searchsorted(close, int(T["exit_ts"].iloc[-1]), side="right"))
        log("paper refilled at", pd.Timestamp(int(T["exit_ts"].iloc[-1]), unit="ms"))
    return pd.concat(parts, ignore_index=True)


def live_alone(B, G: pd.DataFrame, ks: np.ndarray) -> dict:
    """Each paper entry on the Toobit plan from $50: fill / exit time, wallet return, taken (liquidation guard, sizing)."""
    e_idx = B.entry_index(G)
    n = len(ks)
    fill, ex, ret, ok, roe = (np.zeros(n, np.int64), np.zeros(n, np.int64), np.zeros(n), np.zeros(n, bool),
                              np.full(n, np.nan))
    for i, k in enumerate(ks):
        r = G.iloc[int(k)]
        s, A, e = r.symbol, B.A[r.symbol], int(e_idx[int(k)])
        fill[i] = int(A["ts"][min(e, len(A["ts"]) - 1)])
        if e >= len(A["ts"]):
            continue
        raw = float(A["o"][e])
        lev = TBX.lev_btc if s == "BTCUSDT" else TBX.lev_alt
        if TBX.stop_atr * float(r.atr) / raw >= 1.0 / lev - B.mmr[s]:
            continue
        res = sim.run_one(B.Sv_tb, B.br[s], A, e, raw, int(r.side), float(r.atr), bool(r.best), GT.START, B.specs_tb[s],
                          TBX, s, bar_ms=B.bar_ms)
        if res["reason"] == "REJECTED":
            continue
        ok[i], ret[i], roe[i] = True, res["pnl"] / GT.START, res["roe"]
        ex[i] = int(A["ts"][int(res["j"])]) if res["reason"] != "OPEN" else 2 ** 62
    return {"fill": fill, "exit": ex, "ret": ret, "ok": ok, "roe": roe}


def exact(B, G: pd.DataFrame, ks: np.ndarray, mlist: list) -> tuple:
    """Month accounts on the Toobit plan through obvsim (each month from $50, $1 floor): multiples, trades."""
    close = G["close_ms"].to_numpy(np.int64)
    xs, trades = [], []
    for a, b in mlist:
        sel = ks[(close[ks] >= a) & (close[ks] < b)]
        T = B.account(G.iloc[np.sort(sel)].reset_index(drop=True), TBX, "tb", GT.START, GT.BUST) if len(sel) else None
        xs.append(float(T["after"].iloc[-1] / GT.START) if T is not None and len(T) else 1.0)
        if T is not None and len(T):
            trades.append(T)
    return np.array(xs), (pd.concat(trades, ignore_index=True) if trades else pd.DataFrame(columns=["roe"]))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    for k in ("five", "new", "work", "out"):
        ap.add_argument("--" + k, required=True)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    G = VR.signals(a.five, a.new)
    B = O.Book.five(a.work)
    P = paper(B, G)
    log("paper trades", len(P))
    ks = P["k"].to_numpy(np.int64)
    entry, exit_, proe = P["entry_ts"].to_numpy(np.int64), P["exit_ts"].to_numpy(np.int64), P["roe"].to_numpy(float)
    L = {g: GT.lights(exit_, proe, entry, rule) for g, rule in GT.RULES.items()}
    live = live_alone(B, G, ks)
    P.assign(symbol=G["symbol"].to_numpy()[ks], **{g: m for g, m in L.items()},
             live_ok=live["ok"], live_ret=live["ret"], live_roe=live["roe"], live_fill=live["fill"],
             live_exit=live["exit"]).to_csv(os.path.join(a.out, "paper.csv"),
                                                                                    index=False)
    res, mrows, per = {"paper_trades": int(len(P))}, [], {}
    for p, (pa, pb) in PERIODS.items():
        ml = months(pa, pb)
        lo, hi = ml[0][0], ml[-1][1]
        inp = (live["fill"] >= lo) & (live["fill"] < hi)
        d = {}
        for g in GT.RULES:
            xs, T = exact(B, G, ks[L[g]], ml)
            fx = GT.fast_months(ml, live["fill"], live["exit"], live["ret"], live["ok"], L[g])
            sel = np.sort(ks[L[g] & inp])
            W = B.account(G.iloc[sel].reset_index(drop=True), TBX, "tb", GT.START, GT.BUST) if len(sel) else None
            d[g] = {**GT.month_read(xs), "fast": GT.month_read(fx), "paper_entries": int(inp.sum()),
                    "followed": int((L[g] & inp).sum()), "share": round(float((L[g] & inp).sum() / max(1, inp.sum())), 3),
                    "trades": int(len(T)), "mean_roe": round(float(T["roe"].mean()), 4) if len(T) else None,
                    "win": round(float((T["roe"] > 0).mean()), 3) if len(T) else None,
                    "whole_x": round(float(W["after"].iloc[-1] / GT.START), 4) if W is not None and len(W) else 1.0,
                    "whole_bust": bool(W is not None and len(W) and W["after"].iloc[-1] < GT.BUST)}
            for (ma, _), x in zip(ml, xs):
                mrows.append({"arm": g, "period": p, "month": pd.Timestamp(ma, unit="ms").strftime("%Y-%m"), "x": round(x, 4)})
            log(p, g, json.dumps(d[g], ensure_ascii=False))
        if p in ("pick", "check"):
            for g in ("G1", "G2", "G3"):              # G1 judged (PLAN 5); G2 · G3 shown only
                tw = GT.twins(ml, live["fill"], live["exit"], live["ret"], live["ok"], inp, d[g]["followed"])
                d[g]["twins_half"] = {"p5": float(np.percentile(tw, 5)), "p50": float(np.median(tw)),
                                      "p95": float(np.percentile(tw, 95))}
                d[g]["twins_more_share"] = float((tw > d[g]["fast"]["half"]).mean())
                log(p, g, "twins", d[g]["twins_half"], "share with more half months", d[g]["twins_more_share"])
            d["twins_more_share"] = d["G1"]["twins_more_share"]
            per[p] = d
        res[p] = d
    res["verdict"] = GT.verdict(per)
    log("verdict", json.dumps(res["verdict"], ensure_ascii=False))
    pd.DataFrame(mrows).to_csv(os.path.join(a.out, "months.csv"), index=False)
    json.dump(res, open(os.path.join(a.out, "result.json"), "w"), ensure_ascii=False, indent=1, default=float)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

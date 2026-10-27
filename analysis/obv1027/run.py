#!/usr/bin/env python3
"""OBV 추세형 study (PLAN.md sections 6-8) on 5m bars: every cell x filter x exit account per period, the pre-registered
pick, the one check, coin-flip twins, month multiples, and the luck windows.

    python3 -E -P run.py --work WORK --out OUT

Outputs in OUT: arms.csv (every arm x period), alone.csv (every arm's per-signal means: each signal alone on a fresh
wallet, a read only), picks.json (the picks and the check verdict), months.csv, luck.json, compare.csv (PLAN 7).
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import obvsim as O  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import sim  # noqa: E402

MAIN = ("RB30", "RB1h", "CV30", "CV1h")
REF = ("RB4h", "CV4h")
FILTERS = ("F0", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11")
FLIPS = 200
MIN_PICK_TRADES = 100
TB_START, TB_BUST = 50.0, 1.0
BIN_START, BIN_BUST = 5000.0, 10.0


def log(*a):
    print(*a, flush=True)


def filters_of(cell: str) -> tuple:
    return tuple(f for f in FILTERS if not (cell.endswith("1h") and f == "F2"))


def in_period(G: pd.DataFrame, p: str) -> np.ndarray:
    a, b = O.PERIODS[p]
    t = G["close_ms"].to_numpy(np.int64)
    return (t >= a) & (t < b)


def run_arm(B, G, e_idx, mask, v, mode):
    start, bust = (TB_START, TB_BUST) if mode == "tb" else (BIN_START, BIN_BUST)
    g = G[mask]
    T = B.account(g.reset_index(drop=True), v, mode, start, bust, e_idx=e_idx[mask])
    return T, O.stats(T, start, bust)


def alone(B, G, e_idx, v, mode) -> pd.DataFrame:
    """Each signal alone on a fresh wallet (TBX: $50, liquidation guard; bin: $5,000): net ROE, wallet change."""
    Sv = B.Sv_bin if mode == "bin" else B.Sv_tb
    specs = B.specs_bin if mode == "bin" else B.specs_tb
    eq = TB_START if mode == "tb" else BIN_START
    out = np.full((len(G), 3), np.nan)
    sy, sd, at, be = (G["symbol"].to_numpy(), G["side"].to_numpy(int), G["atr"].to_numpy(float),
                      G["best"].to_numpy(bool))
    for k in range(len(G)):
        s, A, e = sy[k], B.A[sy[k]], int(e_idx[k])
        if e >= len(A["ts"]):
            continue
        raw = float(A["o"][e])
        if mode == "tb":
            lev = v.lev_btc if s == "BTCUSDT" else v.lev_alt
            if v.stop_atr * at[k] / raw >= 1.0 / lev - B.mmr[s]:
                out[k, 2] = 1
                continue
        r = sim.run_one(Sv, B.br[s], A, e, raw, int(sd[k]), float(at[k]), bool(be[k]), eq, specs[s], v, s,
                        bar_ms=B.bar_ms)
        if r["reason"] == "REJECTED":
            continue
        out[k, 0], out[k, 1], out[k, 2] = r["roe"], r["ret"], 0
    return pd.DataFrame(out, columns=["roe", "ret", "guard"])


def months(B, G, e_idx, mask, v, mode, period="check"):
    a, b = O.PERIODS[period]
    t = G["close_ms"].to_numpy(np.int64)
    rows = []
    for m0 in pd.date_range(pd.Timestamp(a, unit="ms", tz="UTC"), pd.Timestamp(b, unit="ms", tz="UTC"), freq="MS")[:-1]:
        m1 = m0 + pd.offsets.MonthBegin(1)
        mm = mask & (t >= m0.value // 10**6) & (t < m1.value // 10**6)
        _T, st = run_arm(B, G, e_idx, mm, v, mode)
        rows.append({"month": m0.strftime("%Y-%m"), **st})
    return pd.DataFrame(rows)


def flips(B, G, e_idx, mask, v, mode, n=FLIPS, seed=1027):
    start, bust = (TB_START, TB_BUST) if mode == "tb" else (BIN_START, BIN_BUST)
    g = G[mask].reset_index(drop=True)
    ei = e_idx[mask]
    xs, means = [], []
    for i in range(n):
        rng = np.random.default_rng(seed + i)
        side = rng.choice(np.array([-1, 1]), size=len(g))
        T = B.account(g, v, mode, start, bust, e_idx=ei, side=side)
        st = O.stats(T, start, bust)
        xs.append(st["x"])
        means.append(st["mean_roe"])
    return np.array(xs), np.array(means)


def luck(B, G, e_idx, v, mode, days=21):
    """21-day windows (start moved one day at a time) over 2021-01 .. 2026-10-01 with RBX: share of windows with a win
    rate >= 82 % and >= +50 %, and what the next 21 days did."""
    a, b = O.PERIODS["pick"][0], O.PERIODS["check"][1]
    t = G["close_ms"].to_numpy(np.int64)
    rows = []
    for w0 in range(a, b - days * O.DAY, O.DAY):
        w1 = w0 + days * O.DAY
        _T, st = run_arm(B, G, e_idx, (t >= w0) & (t < w1), v, mode)
        rows.append({"w0": w0, "n": st["n"], "win": st["win"], "x": st["x"]})
    W = pd.DataFrame(rows)
    W["hot"] = (W["win"] >= 0.82) & (W["x"] >= 1.5) & (W["n"] >= 20)
    nxt = W.set_index("w0")["x"]
    after = [nxt.get(w + days * O.DAY, np.nan) for w in W.loc[W["hot"], "w0"]]
    return W, {"windows": int(len(W)), "hot": int(W["hot"].sum()), "hot_share": float(W["hot"].mean()),
               "next_x_median": float(np.nanmedian(after)) if len(after) else None,
               "next_up_share": float(np.nanmean(np.array(after) > 1)) if len(after) else None,
               "all_x_median": float(W["x"].median()), "x_ge_1_5_share": float((W["x"] >= 1.5).mean()),
               "win_ge_82_share": float(((W["win"] >= 0.82) & (W["n"] >= 20)).mean())}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    B = O.Book.five(a.work)
    cells = pickle.load(open(os.path.join(a.work, "signals.pkl"), "rb"))["cells"]
    E = {c: B.entry_index(cells[c]) for c in cells}
    rows, al_rows = [], []
    # ---- PLAN 7: the comparison set-ups (no filter)
    for c in MAIN + REF:
        G = cells[c]
        setups = [("RBX", O.RBX, "bin")] + ([("CVX", O.CVX[c], "bin")] if c in O.CVX else []) + \
                 [("TBX", O.EXITS["T0"], "tb")]
        for xname, v, mode in setups:
            for p in O.PERIODS:
                _T, st = run_arm(B, G, E[c], in_period(G, p), v, mode)
                rows.append({"cell": c, "filter": "F0", "exit": xname, "period": p, **st})
            log("compare", c, xname)
    # ---- PLAN 4-6: every arm (TBX family), every period
    for c in MAIN + REF:
        G = cells[c]
        for xname, v in O.EXITS.items():
            al = alone(B, G, E[c], v, "tb")
            for f in filters_of(c):
                fm = G[f].to_numpy(bool)
                for p in O.PERIODS:
                    pm = in_period(G, p)
                    _T, st = run_arm(B, G, E[c], fm & pm, v, "tb")
                    rows.append({"cell": c, "filter": f, "exit": xname, "period": p, **st})
                    sel = fm & pm
                    x = al[sel]
                    al_rows.append({"cell": c, "filter": f, "exit": xname, "period": p, "signals": int(sel.sum()),
                                    "taken_alone": int(x["roe"].notna().sum()), "guard": int((x["guard"] == 1).sum()),
                                    "mean_roe": float(x["roe"].mean()), "mean_ret": float(x["ret"].mean()),
                                    "win": float((x["ret"] > 0).sum() / max(1, x["ret"].notna().sum()))})
            log("arms", c, xname)
    R = pd.DataFrame(rows)
    R.to_csv(os.path.join(a.out, "arms.csv"), index=False)
    pd.DataFrame(al_rows).to_csv(os.path.join(a.out, "alone.csv"), index=False)
    # ---- PLAN 6: pick (main cells only, TBX family, filters), then the one check
    arms = R[(R["exit"].isin(O.EXITS)) & (R["cell"].isin(MAIN))]
    pk = arms[arms["period"] == "pick"].copy()
    pk = pk[pk["n"] >= MIN_PICK_TRADES]
    picks = {}
    for c in MAIN:
        q = pk[pk["cell"] == c].sort_values(["x", "mean_roe"], ascending=False)
        if not len(q):
            picks[c] = None
            continue
        top = q.iloc[0]
        picks[c] = {"filter": top["filter"], "exit": top["exit"], "pick": top.to_dict(), "eligible": int(len(q))}
    lead = max((c for c in MAIN if picks[c]), key=lambda c: (picks[c]["pick"]["x"], picks[c]["pick"]["mean_roe"]),
               default=None)
    verdict, month_rows = {}, []
    for c in MAIN:
        G = cells[c]
        base_chk = arms[(arms["cell"] == c) & (arms["filter"] == "F0") & (arms["exit"] == "T0")
                        & (arms["period"] == "check")].iloc[0].to_dict()
        mb = months(B, G, E[c], np.ones(len(G), bool), O.EXITS["T0"], "tb")
        mb.insert(0, "arm", f"{c}|F0|T0")
        month_rows.append(mb)
        if not picks[c]:
            verdict[c] = {"picked": None, "base_check": base_chk}
            continue
        f, x = picks[c]["filter"], picks[c]["exit"]
        chk = arms[(arms["cell"] == c) & (arms["filter"] == f) & (arms["exit"] == x)
                   & (arms["period"] == "check")].iloc[0].to_dict()
        mask = G[f].to_numpy(bool) & in_period(G, "check")
        fx, fm_ = flips(B, G, E[c], mask, O.EXITS[x], "tb")
        p95 = float(np.quantile(fx, 0.95))
        tests = {"mean_roe_pos": bool(chk["mean_roe"] > 0), "grew_no_bust": bool(chk["x"] > 1 and not chk["bust"]),
                 "beats_flip95": bool(chk["x"] > p95), "beats_base": bool(chk["x"] > base_chk["x"])}
        verdict[c] = {"picked": f"{c}|{f}|{x}", "check": chk, "flip_x_p50": float(np.median(fx)), "flip_x_p95": p95,
                      "flip_mean_roe_p50": float(np.nanmedian(fm_)), "flip_share_beaten": float((chk["x"] > fx).mean()),
                      "tests": tests, "pass": all(tests.values()), "base_check": base_chk}
        mp = months(B, G, E[c], G[f].to_numpy(bool), O.EXITS[x], "tb")
        mp.insert(0, "arm", f"{c}|{f}|{x}")
        month_rows.append(mp)
        log("check", c, f, x, tests)
    M = pd.concat(month_rows, ignore_index=True)
    M.to_csv(os.path.join(a.out, "months.csv"), index=False)
    # ---- PLAN 8: luck windows of RB30 with the rule bot's exit
    W, lk = luck(B, cells["RB30"], E["RB30"], O.RBX, "bin")
    W.to_csv(os.path.join(a.out, "luck_windows.csv"), index=False)
    W1, lk1 = luck(B, cells["RB1h"], E["RB1h"], O.RBX, "bin")
    json.dump({"picks": picks, "lead": lead, "verdict": verdict, "luck_RB30": lk, "luck_RB1h": lk1},
              open(os.path.join(a.out, "picks.json"), "w"), ensure_ascii=False, indent=1, default=float)
    log("lead", lead, json.dumps({c: v.get("pass") for c, v in verdict.items()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

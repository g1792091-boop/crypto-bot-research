#!/usr/bin/env python3
"""V3.9 -> 투비트 (Toobit), the owners' live plan, 2021-01 .. 2026-10 on the public 5m bars, with the arms of PREREG.md.

The engine is analysis/v39_1h/sim.py ``trade`` (PaperEngine's rules on 1m or coarser bars, checked trade-for-trade there)
copied as ``trade_arm`` below with three additions: the arm hooks at the end of a bar (after its exit checks and lock
step), the stop measured from the own fill (the executor's rule; ``from_fill=False`` gives sim.trade's stop from the
reference price, used by the parity check), and the diagnostics of PREREG.md. Signals: analysis/v39_1h/features.v39_signals
on 1h bars built from the 5m bars (fiveyear.py's data path). The plan: owners1025g/h's PLAN (ladder 20->17, 25->22,
30->27, +5 / -3), stop 2.5 ATR, BTC 40x / others 30x, margin 40 %, Toobit taker 0.06 % + slippage 0.02 %, liquidation guard
(stop >= 1/lev - 0.5 % -> skip), US releases +-30 min -> skip, one position.

    python3 -I v39.py FIVE5M_DIR OUT_DIR [--parity]
FIVE5M_DIR: the folder of <SYM>.npz (ts o h l c v fund). Writes OUT_DIR/v39_trades_<arm>.csv and v39.json."""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import otcommon as CM  # noqa: E402  (puts the repository on sys.path)

V39 = os.path.join(CM.REPO, "analysis", "v39_1h")
sys.path.insert(0, V39)
from dataclasses import replace  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from numba import njit  # noqa: E402

import features as F  # noqa: E402
import sim  # noqa: E402
import v39lib as L  # noqa: E402
from extras import plan_specs  # noqa: E402
from fiveyear import exchange  # noqa: E402

TAKER, SLIP = 0.0006, 0.0002                      # Toobit taker + slippage per side (round trip 0.16 %)
LEV = {"BTCUSDT": 40}
LEV_ALT, FRAC, STOP_ATR, MMR_GUARD = 30, 0.40, 2.5, 0.005
LADDER = dict(first_lock=0.17, gap=0.03, step=0.05, next_trigger=0.25, next_gap=0.03)
EQ = 50.0
R_NONE, R_SL, R_LOCK, R_LIQ, R_OPEN, R_REJECT, R_TP, R_ARM, R_TIME, R_BE = 0, 1, 2, 3, 4, 5, 6, 7, 8, 9
REASON = {R_SL: "SL", R_LOCK: "LOCK", R_LIQ: "LIQ", R_OPEN: "OPEN", R_REJECT: "REJECTED", R_TP: "TP", R_ARM: "OPENCUT",
          R_TIME: "TIME", R_BE: "BE"}


def lev_of(sym: str) -> int:
    return LEV.get(sym, LEV_ALT)


@njit(cache=False)
def trade_arm(S, br, o, h, l, c, mo, mh, ml, fund, ny, win, e, end, raw, side, stop_dist, equity, qty_step, min_notional,
              force_lev, force_frac, first_lock, step, gap, next_trigger, next_gap, from_fill, arm, tbars):
    """sim.trade (forced sizing, ladder form 2, no take-profit, no trail) + the arm hooks. arm: 0 none, 1 A1 (close at
    an M if unlocked), 2 A2 (break-even stop at an M if net ROE > 0), 3 time (close at the end of bar e + tbars - 1 if
    unlocked), 6 A6 (A2 if net ROE > 0 else A1), 7 A7 (close at an M if unlocked and R <= -0.5). Returns sim.trade's tuple head (pnl, exit bar, reason, lev, margin, qty,
    fill, liq, stop0, best, worst, exit price, lock, at_open) + (touched, first M bar unlocked, net ROE there, open &
    unlocked at 4 h / 8 h / 12 h, bars held inside 09:30-11:00 NY, bars held)."""
    taker, slip, rt = S[0], S[1], S[5]
    fill = raw * (1 + side * slip)
    if from_fill:
        stop = fill - side * stop_dist * fill / raw
    else:
        stop = raw - side * stop_dist
    qty = sim._round_down(equity * force_frac * force_lev / fill, qty_step)
    if qty <= 0 or qty * fill < min_notional:
        return (0.0, e, R_REJECT, 0, 0.0, 0.0, fill, 0.0, stop, fill, fill, 0.0, -1.0, False,
                False, -1, 0.0, False, False, False, 0, 0, 0.0, 0.0, 0.0)
    lev = int(force_lev)
    margin = qty * fill / lev
    notional = qty * fill
    kb = sim._bracket(br, notional)
    liq = sim._liq(side, qty, fill, margin, br[kb, 2], br[kb, 3])
    stop0 = stop
    wallet = equity - notional * taker
    fpaid = 0.0
    mfe = fill
    mae = fill
    lock_roe = -1.0
    moved = False
    be_set = False
    touched = False
    first_m = -1
    roe_m = 0.0
    r_m = 0.0          # (d): progress in R, hours held and best-so-far share of the way to the first-lock trigger
    h_m = 0.0
    s_m = 0.0
    o4 = False
    o8 = False
    o12 = False
    inwin = 0
    for j in range(e, end):
        entry_bar = j == e
        if win[j]:
            inwin += 1
        if not entry_bar and fund[j] != 0.0:
            pay = side * qty * mo[j] * fund[j]
            wallet -= pay
            margin -= pay
            fpaid += pay
            liq = sim._liq(side, qty, fill, margin, br[kb, 2], br[kb, 3])
        if side > 0:
            if h[j] > mfe:
                mfe = h[j]
            if l[j] < mae:
                mae = l[j]
        else:
            if l[j] < mfe:
                mfe = l[j]
            if h[j] > mae:
                mae = h[j]
        price = -1.0
        liquidate = False
        at_open = False
        if not entry_bar:
            if (mo[j] - liq) * side <= 0:
                liquidate = True
                at_open = True
            elif (o[j] - stop) * side <= 0:
                price = o[j] * (1 - side * slip)
                at_open = True
        if not liquidate and price < 0:
            hit_stop = (l[j] <= stop) if side > 0 else (h[j] >= stop)
            hit_liq = (ml[j] <= liq) if side > 0 else (mh[j] >= liq)
            if hit_stop:
                price = stop * (1 - side * slip)
            elif hit_liq:
                liquidate = True
            elif not entry_bar:
                fr = fpaid / notional
                bst = lev * (side * (mfe / fill - 1.0) - rt - fr)
                ft = first_lock + gap
                if bst >= ft - 1e-12:
                    if bst >= next_trigger - 1e-12:
                        n = math.floor((bst - next_trigger) / step + 1e-9)
                        lk = next_trigger - next_gap + step * n
                    else:
                        lk = first_lock
                    if lock_roe < 0 or lk > lock_roe + 1e-12:
                        cand = fill * (1.0 + side * (lk / lev + rt + fr))
                        if side > 0:
                            stop = max(stop, cand)
                        else:
                            stop = min(stop, cand)
                        lock_roe = lk
                        moved = True
        reason = R_NONE
        if price < 0 and not liquidate:
            # ---- the end of bar j with the position still open: diagnostics and the arm hooks (PREREG.md)
            unlocked = lock_roe < 0
            fr = fpaid / notional
            nr = lev * (side * (c[j] / fill - 1.0) - rt - fr)
            if unlocked:
                if ny[j] and first_m < 0:
                    first_m = j
                    roe_m = nr
                    r_m = side * (c[j] - fill) / abs(fill - stop0)
                    h_m = (j - e + 1) * 5.0 / 60.0
                    trig = fill * (1.0 + side * ((first_lock + gap) / lev + rt + fr))
                    s_m = side * (mfe - fill) / (side * (trig - fill))
                if j == e + 47:
                    o4 = True
                if j == e + 95:
                    o8 = True
                if j == e + 143:
                    o12 = True
                act_close = False
                act_be = False
                if ny[j]:
                    if arm == 1:
                        act_close = True
                    elif arm == 2 and nr > 0:
                        act_be = True
                    elif arm == 6:
                        if nr > 0:
                            act_be = True
                        else:
                            act_close = True
                    elif arm == 7 and side * (c[j] - fill) / abs(fill - stop0) <= -0.5:   # A7 (addendum 3)
                        act_close = True
                if arm == 3 and j == e + tbars - 1:
                    act_close = True
                    reason = R_TIME
                if act_close:
                    price = c[j] * (1 - side * slip)
                    if reason == R_NONE:
                        reason = R_ARM
                    touched = True
                elif act_be:
                    cand = fill * (1.0 + side * (rt + fr))
                    if (cand - stop) * side > 0:
                        stop = cand
                        be_set = True
                        touched = True
        if price >= 0:
            gross = side * qty * (price - fill)
            if gross < -margin:
                liquidate = True
            else:
                wallet += gross - qty * price * taker
                if reason == R_NONE:
                    reason = R_LOCK if moved else (R_BE if be_set else R_SL)
                return (wallet - equity, j, reason, lev, margin, qty, fill, liq, stop0, mfe, mae, price, lock_roe,
                        at_open, touched, first_m, roe_m, o4, o8, o12, inwin, j - e + 1, r_m, h_m, s_m)
        if liquidate:
            wallet -= margin
            return (wallet - equity, j, R_LIQ, lev, margin, qty, fill, liq, stop0, mfe, mae, liq, lock_roe, at_open,
                    touched, first_m, roe_m, o4, o8, o12, inwin, j - e + 1, r_m, h_m, s_m)
    return (wallet - equity, end - 1, R_OPEN, lev, margin, qty, fill, liq, stop0, mfe, mae, -1.0, lock_roe, False,
            touched, first_m, roe_m, o4, o8, o12, inwin, end - e, r_m, h_m, s_m)


KEYS = ("pnl", "j", "reason", "lev", "margin", "qty", "fill", "liq", "stop0", "best_px", "worst_px", "exit_px", "lock_roe",
        "at_open", "touched", "first_m", "roe_at_M", "open_4h", "open_8h", "open_12h", "held_in_window", "held_bars",
        "R_at_M", "hours_at_M", "mfe_share_at_M")


class World:
    def __init__(self, five: str):
        from paperbot.config import v3_settings
        self.Sset = replace(v3_settings(), taker_fee=TAKER, slippage_frac=SLIP, maker_fee=TAKER + SLIP)
        self.Sv = sim.settings_vector(self.Sset)
        assert abs(self.Sv[5] - 2 * (TAKER + SLIP)) < 1e-15
        brs, _bin_specs = exchange()
        self.br = {s: sim.bracket_array(brs[s]) for s in L.SYMBOLS}
        self.specs = plan_specs("A")
        self.A, sigs = {}, []
        for s in L.SYMBOLS:
            z = F.load5(five, s)
            ts = z["ts"].astype(np.int64)
            self.A[s] = {"ts": ts, "o": z["o"], "h": z["h"], "l": z["l"], "c": z["c"], "mo": z["o"], "mh": z["h"],
                         "ml": z["l"], "fund": z["fund"], "ny": CM.open_flags(ts), "win": CM.window_flags(ts)}
            g = F.v39_signals(F.hourly(five, s))
            g.insert(0, "symbol", s)
            sigs.append(g)
        prio = {s: k for k, s in enumerate(self.Sset.symbol_priority)}
        G = pd.concat(sigs, ignore_index=True)
        G = G[G["close_ms"] >= CM.RUN_START - CM.HOUR]
        G["prio"] = G["symbol"].map(prio)
        self.G = G.sort_values(["close_ms", "prio"]).reset_index(drop=True)

    def one(self, s: str, e: int, raw: float, side: int, atr: float, arm: str = "A0", from_fill: bool = True,
            equity: float = EQ) -> dict:
        A = self.A[s]
        kind, hours = CM.ARMS[arm]
        lev = lev_of(s)
        res = trade_arm(self.Sv, self.br[s], A["o"], A["h"], A["l"], A["c"], A["mo"], A["mh"], A["ml"], A["fund"],
                        A["ny"], A["win"], int(e), len(A["ts"]), float(raw), int(side), float(STOP_ATR * atr),
                        float(equity), float(self.specs[s]["qty_step"]), float(self.specs[s]["min_notional"]),
                        int(lev), float(FRAC), LADDER["first_lock"], LADDER["step"], LADDER["gap"],
                        LADDER["next_trigger"], LADDER["next_gap"], bool(from_fill), CM.ARM_CODE[kind],
                        int(hours * 12))
        out = dict(zip(KEYS, res))
        out["reason"] = REASON.get(int(out["reason"]), "?")
        j = int(out["j"])
        if out["reason"] == "OPEN":            # still open at the data end: marked to the last close (market)
            px = float(A["c"][j]) * (1 - side * SLIP)
            out["pnl"] += side * out["qty"] * (px - out["fill"]) - out["qty"] * px * TAKER
            out["exit_px"] = px
        out["ret"] = out["pnl"] / equity
        out["exit_ts"] = int(A["ts"][j])
        return out


def macro_times() -> np.ndarray:
    """FOMC + NFP 2020-2026 (research/hunt/macro_calendar.json) and data/macro_events.csv (the 레인지 study's list)."""
    t = [int(e["t_ms"]) for e in json.load(open(os.path.join(CM.REPO, "research/hunt/macro_calendar.json")))["events"]]
    from paperbot import events as EV
    evs, _ = EV.parse(open(os.path.join(CM.REPO, "data/macro_events.csv")).read())
    t += [e.ts_ms for e in evs]
    return np.array(sorted(set(t)), dtype=np.int64)


def account(W: World, arm: str, macro: np.ndarray) -> pd.DataFrame:
    """One position over the six coins, signals in time order; each trade sized on $50 (ret = P&L / $50)."""
    busy, rows = -1, []
    for r in W.G.itertuples(index=False):
        A = W.A[r.symbol]
        e = int(np.searchsorted(A["ts"], int(r.close_ms)))
        if e >= len(A["ts"]):
            continue
        t_fill = int(A["ts"][e])
        if t_fill <= busy:
            continue
        k = np.searchsorted(macro, t_fill - 30 * CM.MIN, side="left")
        if k < len(macro) and macro[k] <= t_fill + 30 * CM.MIN:
            continue                                            # US release +-30 min: no entry
        raw = float(A["o"][e])
        lev = lev_of(r.symbol)
        if STOP_ATR * float(r.atr) / raw >= 1.0 / lev - MMR_GUARD:
            continue                                            # liquidation guard: skip, the next signal may enter
        res = W.one(r.symbol, e, raw, int(r.side), float(r.atr), arm)
        if res["reason"] == "REJECTED":
            continue
        busy = int(A["ts"][int(res["j"])]) if res["reason"] != "OPEN" else 2 ** 62
        locked = res["lock_roe"] >= 0
        kind = "LOCKED" if locked else ("SL" if res["reason"] in ("SL", "LIQ") else "OTHER")
        rows.append({"t": t_fill, "symbol": r.symbol, "side": int(r.side), "lev": int(res["lev"]),
                     "exit_ts": res["exit_ts"], "reason": res["reason"], "lock_roe": float(res["lock_roe"]),
                     "ret": float(res["ret"]), "touched": bool(res["touched"]), "locked": bool(locked), "kind": kind,
                     "open_at_M": res["first_m"] >= 0, "roe_at_M": float(res["roe_at_M"]),
                     "R_at_M": float(res["R_at_M"]), "hours_at_M": float(res["hours_at_M"]),
                     "mfe_share_at_M": float(res["mfe_share_at_M"]),
                     "open_4h": bool(res["open_4h"]), "open_8h": bool(res["open_8h"]), "open_12h": bool(res["open_12h"]),
                     "sl_in_window": bool(res["reason"] in ("SL", "LIQ") and A["win"][int(res["j"])]),
                     "held_in_window": int(res["held_in_window"]), "held_bars": int(res["held_bars"])})
    return pd.DataFrame(rows)


def parity(W: World) -> dict:
    """The copied kernel (no arm, stop from the reference price) vs analysis/v39_1h/sim.run_one, every signal alone."""
    v = sim.Variant("plan_B", stop_atr=STOP_ATR, lev_btc=40, lev_alt=LEV_ALT, frac=FRAC, **LADDER)
    n = bad = 0
    worst = 0.0
    for r in W.G.itertuples(index=False):
        A = W.A[r.symbol]
        e = int(np.searchsorted(A["ts"], int(r.close_ms)))
        if e >= len(A["ts"]):
            continue
        raw = float(A["o"][e])
        a = sim.run_one(W.Sv, W.br[r.symbol], A, e, raw, int(r.side), float(r.atr), bool(r.best), EQ,
                        W.specs[r.symbol], v, r.symbol, bar_ms=CM.FIVE)
        b = W.one(r.symbol, e, raw, int(r.side), float(r.atr), "A0", from_fill=False)
        n += 1
        d = abs(a["pnl"] - b["pnl"])
        worst = max(worst, d)
        if a["reason"] != b["reason"] or int(a["j"]) != int(b["j"]) or d > 1e-9:
            bad += 1
            if bad <= 5:
                print("parity diff", r.symbol, int(r.close_ms), a["reason"], b["reason"], a["j"], b["j"], a["pnl"],
                      b["pnl"], flush=True)
    return {"signals": n, "different": bad, "max_abs_pnl_diff": worst}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("five")
    ap.add_argument("out")
    ap.add_argument("--parity", action="store_true")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    t0 = time.time()
    W = World(a.five)
    print(f"signals {len(W.G)} ({time.time() - t0:.0f}s)", flush=True)
    if a.parity:
        p = parity(W)
        print("parity", p, flush=True)
        json.dump(p, open(os.path.join(a.out, "v39_parity.json"), "w"), indent=1)
        return 0 if p["different"] == 0 else 1
    macro = macro_times()
    res, diag = {}, None
    for arm in CM.ARMS:
        T = account(W, arm, macro)
        T.to_csv(os.path.join(a.out, f"v39_trades_{arm}.csv.gz"), index=False)
        res[arm] = {p: CM.period_metrics(T, p) for p in CM.PERIODS}
        if arm == "A0":
            diag = CM.by_period_diag(T)
            diag_d = CM.by_period_sideways(T)
        print(arm, {p: (d["trades"], round(d["median_month"], 4)) for p, d in res[arm].items()},
              f"{time.time() - t0:.0f}s", flush=True)
    out = {"bot": "V3.9 -> Toobit", "arms": res, "verdicts": CM.verdicts(res), "diagnostics_A0": diag, "sideways_A0": diag_d,
           "signals": int(len(W.G)), "data_end_utc": str(pd.Timestamp(int(W.A["BTCUSDT"]["ts"][-1]), unit="ms"))}
    json.dump(CM.jsonable(out), open(os.path.join(a.out, "v39.json"), "w"), indent=1, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

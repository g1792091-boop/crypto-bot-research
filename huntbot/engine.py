"""One account on the forward market, with research/hunt/hunt.py's own functions (the same calls as its
``run_signals``: system_signals -> bank_for -> build_cands -> simulate -> summarize), plus three reads that never change
a trade:

* ``simulate_hourly``: the same ``hunt.simulate`` call on a copy of the market whose month axis is cut into hours (and
  the large-group table repeated per hour). The engine marks equity at the end of each "month" of its axis, so this
  gives the marked equity of every hour; every trade, every daily mark and the final state are the same as with the
  calendar months (tests/test_huntbot_parity.py checks it), and the calendar-month figures are read back from the hours.
* ``probe_stops``: the stop in force for the next 5m bar of every open position. The engine does not return its
  state, so the same call runs once more on a copy of the market with one extra 5m bar per open coin right after the
  data (open = high = close = the last close, low = 0 for a long / high far above for a short): each open position exits
  there at its stop (or its liquidation price when that lies inside the stop), and the exit price is the stop.
* ``event_actions``: per entry event of the cell, what the system did (opened, gate, coin busy, six positions, ...).
"""

from __future__ import annotations

import copy
from typing import Optional

import numpy as np

from research.hunt import hunt as H

FIVE = H.FIVE
HOUR = 12                                   # 5m steps per hour


# ---------------------------------------------------------------- the engine call, hourly marks
def hourly_axis(mk) -> tuple:
    edges = np.arange(0, int(mk.T) + 1, HOUR, dtype=np.int64)
    mi = np.searchsorted(mk.month_t0, edges[:-1], "right") - 1
    return edges, np.ascontiguousarray(mk.large[mi])


def simulate_hourly(mk, bank, cands: dict, prm: np.ndarray) -> tuple:
    """(hourly raw, calendar-month raw): ``hunt.simulate`` on the hour axis, and the month figures read from it."""
    edges, large_h = hourly_axis(mk)
    mh = copy.copy(mk)
    mh.month_t0, mh.large = edges, large_h
    raw_h = H.simulate(mh, bank, cands, prm=prm)
    heq, hpos = raw_h[0], raw_h[1]
    m_end = np.asarray(mk.month_t0[1:], np.int64) // HOUR - 1
    month_eq = heq[m_end].copy()
    a = np.asarray(mk.month_t0[:-1], np.int64) // HOUR
    month_pos = np.asarray([int(hpos[x:y + 1].max()) if y >= x else 0 for x, y in zip(a, m_end)], np.int64)
    return raw_h, (month_eq, month_pos) + tuple(raw_h[2:])


def params_of(variant: dict) -> np.ndarray:
    return H.params(variant["r"], "base", variant["risk_cap"], H.START_WALLET, variant["b_div"])


# ---------------------------------------------------------------- stops in force (probe)
def probe_stops(mk, bank, cands: dict, prm: np.ndarray, raw: tuple, last_step: int) -> dict:
    """{record index: {"stop": price or None, "kind": "stop" | "liq" | "gap", "source": stop source}} for every
    position still open at the end of ``raw`` (one more ``hunt.simulate`` call, see the module text)."""
    rf, ri = raw[3], raw[4]
    if not len(ri):
        return {}
    open_idx = np.flatnonzero(ri[:, H.RI_REASON] == H.EX_END)
    if not len(open_idx):
        return {}
    tp = int(last_step) + 1
    side_of = {int(ri[i, H.RI_COIN]): int(ri[i, H.RI_SIDE]) for i in open_idx}
    last_px = {int(ri[i, H.RI_COIN]): float(rf[i, H.RF_XPX]) for i in open_idx}
    cols = {n: [] for n in ("t", "o", "h", "l", "c", "qv")}
    off, shift, ins = [0], np.zeros(mk.K, np.int64), 0
    for k in range(mk.K):
        a, b = int(mk.b_off[k]), int(mk.b_off[k + 1])
        shift[k] = ins
        for n, src in (("t", mk.b_t), ("o", mk.b_o), ("h", mk.b_h), ("l", mk.b_l), ("c", mk.b_c), ("qv", mk.b_qv)):
            cols[n].append(src[a:b])
        if k in side_of:
            p, s = last_px[k], side_of[k]
            if b > a and int(mk.b_t[b - 1]) >= tp:
                return {}
            qv = float(mk.b_qv[b - 1]) if b > a else 0.0
            for n, v in (("t", tp), ("o", p), ("h", p if s > 0 else p * 1e6), ("l", 0.0 if s > 0 else p), ("c", p),
                         ("qv", qv)):
                cols[n].append(np.asarray([v], np.int64 if n == "t" else np.float64))
            ins += 1
        off.append(off[-1] + (b - a) + (1 if k in side_of else 0))
    mp = copy.copy(mk)
    mp.b_off = np.asarray(off, np.int64)
    mp.b_t = np.concatenate(cols["t"]).astype(np.int64)
    mp.b_o, mp.b_h, mp.b_l, mp.b_c, mp.b_qv = (np.concatenate(cols[n]).astype(np.float64)
                                               for n in ("o", "h", "l", "c", "qv"))
    if tp >= mk.T:
        mt = np.asarray(mk.month_t0, np.int64).copy()
        mt[-1] = int(mk.T) + H.BARS_PER_DAY
        mp.month_t0 = mt
    cp = dict(cands)
    cp["bi"] = np.asarray(cands["bi"], np.int64) + shift[np.asarray(cands["coin"], np.int64)]
    rp = H.simulate(mp, bank, cp, prm=prm)
    rfp, rip = rp[3], rp[4]
    slip = float(prm[H.PR_SLIP])
    out = {}
    for i in open_idx:
        if i >= len(rip) or int(rip[i, H.RI_TOUT]) != tp:
            continue
        s = int(ri[i, H.RI_SIDE])
        reason = int(rip[i, H.RI_REASON])
        x = float(rfp[i, H.RF_XPX])
        src = H.STOP_SRC_NAMES[int(rip[i, H.RI_SRC])]
        if reason == H.EX_STOP:
            out[int(i)] = {"stop": x / (1.0 - s * slip), "kind": "stop", "source": src}
        elif reason == H.EX_LIQ:
            out[int(i)] = {"stop": x, "kind": "liq", "source": src}
        elif reason == H.EX_GAP:
            out[int(i)] = {"stop": None, "kind": "gap", "source": src}
    return out


# ---------------------------------------------------------------- records -> trades
def trades_of(mk, cands: dict, raw: tuple, prm: np.ndarray) -> list:
    rf, ri = raw[3], raw[4]
    slip = float(prm[H.PR_SLIP])
    out = []
    for i in range(len(ri)):
        k, side, ci = int(ri[i, H.RI_COIN]), int(ri[i, H.RI_SIDE]), int(ri[i, H.RI_CAND])
        reason = int(ri[i, H.RI_REASON])
        p0, d0, u = float(rf[i, H.RF_P0]), float(rf[i, H.RF_D0]), float(rf[i, H.RF_U])
        pnl = float(rf[i, H.RF_PNL])
        out.append({
            "i": i, "coin": mk.syms[k], "side": side, "pick_no": int(cands["src"][ci]),
            "signal_close_ms": int(cands["close"][ci]), "in_ms": int(mk.start + int(ri[i, H.RI_TIN]) * FIVE),
            "out_ms": int(mk.start + int(ri[i, H.RI_TOUT]) * FIVE), "open": reason == H.EX_END,
            "reason": H.EXIT_NAMES[reason], "stop_source": H.STOP_SRC_NAMES[int(ri[i, H.RI_SRC])],
            "p0": p0, "fill": p0 * (1.0 + side * slip), "d0": d0, "first_stop": p0 - side * d0,
            "q1": float(rf[i, H.RF_Q1]), "lev": int(rf[i, H.RF_LEV]), "u": u, "eq_entry": float(rf[i, H.RF_EQ]),
            "exit_px": float(rf[i, H.RF_XPX]), "adds": int(ri[i, H.RI_ADDS]), "adds_tried": int(ri[i, H.RI_TRIED]),
            "pnl": pnl, "price_pnl": float(rf[i, H.RF_PRICE]), "fees": float(rf[i, H.RF_FEES]),
            "funding": float(rf[i, H.RF_FUND]), "r_mult": pnl / u if u > 0 else None,
            "large": int(ri[i, H.RI_LARGE]), "cut": int(ri[i, H.RI_CUT])})
    return out


# ---------------------------------------------------------------- what the system did with each event
def blocked_reason(ri: np.ndarray, k: int, t: int, ci: int, bust_t: int) -> str:
    if bust_t >= 0 and t > bust_t:
        return "ACCOUNT_BUST"
    if not len(ri):
        return "SKIPPED_OTHER"
    tin, tout, cand, coin = ri[:, H.RI_TIN], ri[:, H.RI_TOUT], ri[:, H.RI_CAND], ri[:, H.RI_COIN]
    open_at = ((tin < t) & (tout >= t)) | ((tin == t) & (cand < ci))
    if (open_at & (coin == k)).any():
        return "BLOCKED_COIN_BUSY"
    if int(open_at.sum()) >= H.MAX_POS:
        return "BLOCKED_CAP_SIX"
    return "SKIPPED_OTHER"


def event_actions(mk, spec: dict, gate: str, cands: dict, raw: tuple, events: dict, since_ms: int) -> dict:
    """{(symbol, bar close ms, "LONG"/"SHORT"): action} for the cell's events with close >= since_ms in the period.
    ``events``: {symbol: (long close ms array, short close ms array)}."""
    ri = raw[4]
    bust_t = int(raw[10][1])
    opened = set(int(x) for x in ri[:, H.RI_CAND]) if len(ri) else set()
    cmap = {(int(cands["coin"][i]), int(cands["j"][i]), int(cands["side"][i])): i for i in range(len(cands["t"]))}
    lo = max(int(since_ms), int(mk.start))
    out = {}
    for k, sym in enumerate(mk.syms):
        ev = events.get(sym)
        if ev is None:
            continue
        lg_ms, sh_ms = (np.asarray(x, np.int64) for x in ev)
        if not len(lg_ms) and not len(sh_ms):
            continue
        ser = H.series(sym, spec["tf"])
        cm = ser.bars.close_ms
        g = H.gate_mask(ser, gate)
        both = set(np.intersect1d(lg_ms, sh_ms).tolist())
        for side, arr in ((1, lg_ms), (-1, sh_ms)):
            arr = arr[(arr >= lo) & (arr < mk.end)]
            for ms in arr.tolist():
                j = int(np.searchsorted(cm, ms))
                if j >= len(cm) or int(cm[j]) != ms:
                    act = "SKIPPED_OTHER"
                elif ms in both:
                    act = "BOTH_SIDES"
                elif not g[j]:
                    act = "BLOCKED_GATE"
                elif not (np.isfinite(ser.atr[j]) and ser.atr[j] > 0):
                    act = "NO_ATR"
                else:
                    ci = cmap.get((k, j, side))
                    if ci is None:
                        act = "PENDING_FILL"
                    elif ci in opened:
                        act = "OPENED"
                    else:
                        act = blocked_reason(ri, k, int(cands["t"][ci]), ci, bust_t)
                out[(sym, int(ms), "LONG" if side > 0 else "SHORT")] = act
    return out


# ---------------------------------------------------------------- one account
def run_account(mk, parts: list, variant: dict, last_step: int, want_probe: bool = True,
                want_hourly: bool = False, action_events: Optional[dict] = None, since_ms: Optional[int] = None) -> dict:
    """``parts``: [(spec, src)]. Returns the account's figures (money included; redaction is the snapshot's job)."""
    sigs = [(H.system_signals(mk, spec), src) for spec, src in parts]
    tfs = tuple(sorted({sig["tf"] for sig, _ in sigs}, key=H.TF_ORDER.index))
    bank = H.bank_for(mk, tfs)
    cands = H.build_cands(mk, bank, sigs)
    prm = params_of(variant)
    raw_h, raw = simulate_hourly(mk, bank, cands, prm)
    summ = H.summarize(mk, raw, detail=False, days=True)
    summ["candidates"] = int(len(cands["t"]))
    if len(sigs) == 1:
        summ["signal_counts"] = dict(sigs[0][0]["counts"])
    else:
        summ["signal_counts"] = {spec["id"]: dict(sig["counts"]) for (sig, _), (spec, _) in zip(sigs, parts)}
    trades = trades_of(mk, cands, raw, prm)
    if want_probe:
        stops = probe_stops(mk, bank, cands, prm, raw, last_step)
        for t in trades:
            if t["open"]:
                t["stop_now"] = stops.get(t["i"])
    n_hours = (int(last_step) + 1 + HOUR - 1) // HOUR
    out = {"summary": summ, "trades": trades, "equity_now": float(raw[10][4]),
           "bust_t": int(raw[10][1]), "months": list(mk.months)}
    if want_hourly:
        out["hourly"] = [round(float(x), 4) for x in raw_h[0][:max(0, n_hours)]]
    if action_events is not None and len(parts) == 1:
        spec = parts[0][0]
        out["actions"] = event_actions(mk, spec, spec["gate"], cands, raw, action_events,
                                       mk.start if since_ms is None else since_ms)
    return out

"""Trade management of the shadow league: how a virtual trade is entered, stopped, targeted, timed out and costed.

Copied word for word from the study's code (see vendor_manifest.json for the hashes of the originals):
  * exit_trade        research/reel5m/lib_reel5m.py (engine parity tested there): fixed stop-market, a target limit,
                      the stop first when one bar touches both, a time exit at the close of the 48th bar, fee 2 x taker,
                      slippage on market fills, funding pro rata.
  * simulate          lib_zoneflip.py ``simulate`` (one position per coin and timeframe: a signal on a bar up to the
                      previous trade's exit bar is skipped; entry at the next bar's open plus slippage; skipped when that
                      open is already beyond the stop or the target). Its only change: it calls exit_trade here.
  * exit_fixed_batch  lib_zoneflip.py: exit_trade for many trades at once with a fixed stop and target (the coin-flip
                      clones); tests check that it equals exit_trade bit for bit.
Costs are the study's (third_party/sweep/harness/sweep_lib.py: FEE_SIDE, SLIP_SIDE, FUNDING_8H, the bar length in
minutes): 0.05 % taker fee per side, 0.02 % slippage per market fill (not on the target limit), funding 0.01 % per
8 hours pro rata. ``Cost`` has the attribute names of the locked engine's CostCfg, which these functions read.

Only ``step_trade`` is new: the same exit_trade on the bars known so far, and whether the trade is already decided.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

FEE_SIDE = 0.0005           # taker fee per side (sweep_lib.FEE_SIDE)
SLIP_SIDE = 0.0002          # slippage per market fill (sweep_lib.SLIP_SIDE)
FUNDING_8H = 0.0001         # funding per 8 hours, charged to long and short (sweep_lib.FUNDING_8H)
TF_MINUTES = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
MAX_HOLD = 48               # bars, the entry bar included (all timeframes)


@dataclass(frozen=True)
class Cost:
    fee_side: float = FEE_SIDE
    slip_side: float = SLIP_SIDE
    funding_8h: float = FUNDING_8H
    bar_minutes: int = 15
    max_hold: int = MAX_HOLD


def cost_for(tf: str, max_hold: int = MAX_HOLD) -> Cost:
    """sweep_lib._cost(tf, max_hold) without the warm-up field."""
    return Cost(bar_minutes=TF_MINUTES[tf], max_hold=int(max_hold))


# ------------------------------------------------------------------ copied: research/reel5m/lib_reel5m.py
def exit_trade(side: int, e: int, entry: float, stop: float, tgt, o, h, l, c, cost, tp_through: float = 0.0) -> dict:
    """One trade entered at ``entry`` with bar ``e`` as the first bar at risk. ``stop``: fixed stop-market level.
    ``tgt``: scalar target or an array giving the resting limit level active during each bar (NaN = none).
    Same conventions and arithmetic as the locked engine's ``_simulate_one`` (FIXED): stop first when both are
    touched in one bar, stop fills at min(open, stop) less slippage, target at max(open, target) without slippage,
    time exit at the close of bar e+max_hold-1 less slippage, fee 2 x taker, funding pro rata.
    ``tp_through`` (sensitivity only, 0 = engine): the target counts as hit only when price trades that fraction
    through it; the fill is still max(open, target).
    Extra outputs (not in the engine): ``mae_held`` = adverse excursion while the position was actually open (on a
    stop exit the exit bar counts only down to the stop fill), used for the liquidation count; ``gross_raw`` = the
    price move before fee, slippage and funding (``gross`` keeps the engine meaning: after slippage)."""
    n = len(o)
    last = min(n - 1, e + cost.max_hold - 1)
    oo, hh, ll, cc = o[e:last + 1], h[e:last + 1], l[e:last + 1], c[e:last + 1]
    m = len(oo)
    adverse = ll if side > 0 else hh
    favour = hh if side > 0 else ll
    hit_sl = (adverse <= stop) if side > 0 else (adverse >= stop)
    tg = np.full(m, float(tgt)) if np.ndim(tgt) == 0 else np.asarray(tgt, float)[e:last + 1]
    thr = tg if tp_through == 0.0 else tg * (1.0 + side * tp_through)
    with np.errstate(invalid="ignore"):
        hit_tp = (favour >= thr) if side > 0 else (favour <= thr)
    any_hit = hit_sl | hit_tp
    if any_hit.any():
        j = int(np.argmax(any_hit))
        if hit_sl[j]:
            reason = "SL"
            fill = min(oo[j], stop) if side > 0 else max(oo[j], stop)
            exit_px = fill * (1.0 - side * cost.slip_side)
            raw_exit = fill
        else:
            reason = "TP"
            exit_px = max(oo[j], tg[j]) if side > 0 else min(oo[j], tg[j])
            raw_exit = exit_px
    else:
        j = m - 1
        reason = "TIME" if last < n - 1 else "EOD"
        exit_px = cc[j] * (1.0 - side * cost.slip_side)
        raw_exit = cc[j]
    hold = j + 1
    seg_adv, seg_fav = adverse[: j + 1], favour[: j + 1]
    mae = side * (seg_adv.min() / entry - 1.0) if side > 0 else side * (seg_adv.max() / entry - 1.0)
    mfe = side * (seg_fav.max() / entry - 1.0) if side > 0 else side * (seg_fav.min() / entry - 1.0)
    # held: on a stop exit the position is closed at the stop fill, the rest of that bar's wick is not carried
    held = np.r_[adverse[:j], raw_exit] if reason == "SL" else seg_adv
    mae_held = side * (held.min() / entry - 1.0) if side > 0 else side * (held.max() / entry - 1.0)
    gross = side * (exit_px / entry - 1.0)
    gross_raw = side * (raw_exit / (entry / (1.0 + side * cost.slip_side)) - 1.0)
    fee = 2.0 * cost.fee_side
    funding = cost.funding_8h * (hold * cost.bar_minutes / 480.0)
    net = gross - fee - funding
    return dict(side=side, entry_idx=e, exit_idx=e + j, entry_px=entry, exit_px=exit_px, gross=gross, fee=fee,
                funding=funding, net=net, mae=mae, mfe=mfe, reason=reason, hold=hold,
                sl_dist=side * (entry - stop) / entry, stop_px=stop, mae_held=mae_held, gross_raw=gross_raw)


# ------------------------------------------------------------------ copied: lib_zoneflip.py
def simulate(chosen: dict[int, dict], o, h, l, c, cost, lo: int, hi: int):
    """One position at a time (engine convention: signals on bars <= the previous exit bar are skipped). Entry at
    the next bar's open with slippage; skipped (flat again) if the open is already at / beyond the stop or the
    target. Returns (trades, counts)."""
    n = len(c)
    hi = min(hi, n - 1)
    trades, cnt = [], {"signals": 0, "taken": 0, "skip_entry": 0, "busy": 0}
    next_free = -1
    for r in sorted(k for k in chosen if lo <= k < hi):
        cnt["signals"] += 1
        if r <= next_free:
            cnt["busy"] += 1
            continue
        s = chosen[r]
        side, e = s["side"], r + 1
        entry = o[e] * (1.0 + side * cost.slip_side)
        if side * (entry - s["stop"]) <= 0 or side * (s["target"] - entry) <= 0:
            cnt["skip_entry"] += 1
            continue
        t = exit_trade(side, e, entry, s["stop"], s["target"], o, h, l, c, cost)
        t.update(signal_idx=r, break_idx=s["b"], n_touch=s["n_touch"], zone_lo=s["zlo"], zone_hi=s["zhi"],
                 tz_lo=s["tz_lo"], tz_hi=s["tz_hi"], target_px=s["target"], atr_sig=s["atr"],
                 tp_dist=side * (s["target"] - entry) / entry, risk_ref=s["risk"], reward_ref=s["reward"])
        trades.append(t)
        cnt["taken"] += 1
        next_free = t["exit_idx"]
    return trades, cnt


def exit_fixed_batch(side, e, entry, stop, tgt, o, h, l, c, cost, chunk: int = 20000) -> np.ndarray:
    """Vectorised ``R.exit_trade`` for fixed stop / target (coin flips): returns net per trade. Same order of
    float operations as exit_trade (tests check bit equality)."""
    side, e = np.asarray(side, np.int64), np.asarray(e, np.int64)
    entry, stop, tgt = (np.asarray(x, float) for x in (entry, stop, tgt))
    n, MH = len(o), cost.max_hold
    out = np.empty(len(e))
    ar = np.arange(MH)
    for s0 in range(0, len(e), chunk):
        sl = slice(s0, s0 + chunk)
        sd, ee, en, sp, tg = side[sl], e[sl], entry[sl], stop[sl], tgt[sl]
        last = np.minimum(n - 1, ee + MH - 1)
        idx = ee[:, None] + ar[None, :]
        valid = idx <= last[:, None]
        idx = np.minimum(idx, n - 1)
        lg = (sd > 0)[:, None]
        adverse = np.where(lg, l[idx], h[idx])
        favour = np.where(lg, h[idx], l[idx])
        hit_sl = np.where(lg, adverse <= sp[:, None], adverse >= sp[:, None]) & valid
        hit_tp = np.where(lg, favour >= tg[:, None], favour <= tg[:, None]) & valid
        anyh = hit_sl | hit_tp
        has = anyh.any(axis=1)
        j = np.where(has, anyh.argmax(axis=1), last - ee)
        rows = np.arange(len(ee))
        oj = o[idx[rows, j]]
        is_sl = has & hit_sl[rows, j]
        is_tp = has & ~is_sl
        sdf = sd.astype(float)
        fill_sl = np.where(sd > 0, np.minimum(oj, sp), np.maximum(oj, sp))
        px_sl = fill_sl * (1.0 - sdf * cost.slip_side)
        px_tp = np.where(sd > 0, np.maximum(oj, tg), np.minimum(oj, tg))
        px_t = c[idx[rows, j]] * (1.0 - sdf * cost.slip_side)
        exit_px = np.where(is_sl, px_sl, np.where(is_tp, px_tp, px_t))
        hold = j + 1
        gross = sdf * (exit_px / en - 1.0)
        fee = 2.0 * cost.fee_side
        funding = cost.funding_8h * (hold * cost.bar_minutes / 480.0)
        out[sl] = gross - fee - funding
    return out


# ------------------------------------------------------------------ new: a trade on the bars known so far
def step_trade(side: int, e: int, entry: float, stop: float, tgt: float, o, h, l, c, cost) -> tuple[bool, dict]:
    """exit_trade on the bars the arrays hold (they end at the latest closed bar). Returns (decided, trade):
    decided is True when a bar already hit the stop or the target, or when the 48th bar (e + max_hold - 1) is in the
    arrays; otherwise the trade is still running and ``trade`` describes the unfinished walk (reason 'EOD': never
    stored as a result). A decided trade is final: more bars appended later cannot change it, because exit_trade stops at
    the first hit and the time exit is the close of bar e + max_hold - 1."""
    t = exit_trade(side, e, entry, stop, tgt, o, h, l, c, cost)
    decided = t["reason"] in ("SL", "TP") or len(o) - 1 >= e + cost.max_hold - 1
    if decided and t["reason"] == "EOD":
        t["reason"] = "TIME"            # the arrays end exactly on the 48th bar: that is the time exit
    return decided, t

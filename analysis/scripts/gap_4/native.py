"""Native-lite FINGRAD exit model, bar level (15m), from the 31-set report's engine table
(doc_31set.txt lines 30-54):
  * entry gate: stop on the wrong side -> blocked; STRUCTURE_STOP_BEYOND_HARD_CAP -> blocked
    if the structural stop distance from the signal close exceeds `gate` (None = no gate)
  * initial stop = strategy's structural stop, trailing proposals applied favourably only
    (and only if on the correct side of the close), from the next bar
  * hard cap: net ROE <= -cap_roe at `lev` -> exit (price level derived with the cost model)
  * profit lock on NET ROE: peak >= +13 -> protect +10; peak >= +20 -> floor(peak/5)*5-5
    (peak through the PREVIOUS bar, same conservative convention as stage-1 LADDER)
  * CONFIRM_2: opposite signal (or strategy-specific exit) true on 2 consecutive closes and
    >= 2 bars held -> market exit at next open
  * same-bar priority: stop/cap/lock first
NOT modelled: 1m/5m confirmation of the structural stop, 0.25 s monitoring (bar OHLC used),
one-position-per-strategy across symbols, confidence ranking, noise-floor gate, spread gate.
Costs: stage-1 conventions (fee per side, slippage per market fill, funding per 8h)."""
from __future__ import annotations
import math
import numpy as np
import pandas as pd


def sim_native(df, sig, lo, hi, fee=0.0005, slip=0.0002, funding_8h=0.0001, bar_minutes=15,
               lev=50.0, cap_roe=30.0, gate=None, lock=True, use_opp=True, use_uex=True, use_trail=True,
               max_hold=1000, warmup=1000):
    o = df["open"].to_numpy(float); h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float); c = df["close"].to_numpy(float)
    n = len(o)
    L, S = sig["L"], sig["S"]
    rt = 2 * fee + 2 * slip            # net-ROE cost in price terms (entry slip is in the entry price
    rt_after_entry = 2 * fee + slip    # ... so only exit slip + 2 fees remain after entry)
    start = max(lo, warmup)
    idx = np.where((L | S)[start:hi])[0] + start
    rows = []
    next_free = -1
    blocked = dict(wrong_side=0, beyond_cap=0, nan_stop=0)
    for i in idx:
        if i <= next_free:
            continue
        if i + 1 >= n:
            break
        side = 1 if L[i] else -1
        stop = sig["stopL"][i] if side > 0 else sig["stopS"][i]
        if not np.isfinite(stop):
            blocked["nan_stop"] += 1; continue
        d = side * (c[i] - stop) / c[i]
        if d <= 0:
            blocked["wrong_side"] += 1; continue
        if gate is not None and d > gate:
            blocked["beyond_cap"] += 1; continue
        e = i + 1
        entry = o[e] * (1 + side * slip)
        cap_px = entry * (1 + side * (rt_after_entry - cap_roe / 100.0 / lev))
        opp = S if side > 0 else L
        uex = sig["exL"] if side > 0 else sig["exS"]
        tr = sig["trailL"] if side > 0 else sig["trailS"]
        peak = entry
        last = min(n - 1, e + max_hold - 1)
        reason = None; exit_px = None; j_exit = None
        mae_ext = entry; mfe_ext = entry
        for j in range(e, last + 1):
            # effective protective level for bar j (known before bar j)
            lvl = max(stop, cap_px) if side > 0 else min(stop, cap_px)
            why = "SL" if (stop >= cap_px if side > 0 else stop <= cap_px) else "CAP"
            if lock:
                proe = lev * (side * (peak / entry - 1.0) - rt_after_entry) * 100.0
                prot = None
                if proe >= 20.0:
                    prot = math.floor(proe / 5.0) * 5.0 - 5.0
                elif proe >= 13.0:
                    prot = 10.0
                if prot is not None:
                    lpx = entry * (1 + side * (prot / 100.0 / lev + rt_after_entry))
                    if (side > 0 and lpx > lvl) or (side < 0 and lpx < lvl):
                        lvl = lpx; why = "LOCK"
            adv = l[j] if side > 0 else h[j]
            fav = h[j] if side > 0 else l[j]
            if (side > 0 and adv <= lvl) or (side < 0 and adv >= lvl):
                fill = min(o[j], lvl) if side > 0 else max(o[j], lvl)
                exit_px = fill * (1 - side * slip); reason = why; j_exit = j
                mae_ext = min(mae_ext, adv) if side > 0 else max(mae_ext, adv)
                mfe_ext = max(mfe_ext, max(o[j], fill)) if side > 0 else min(mfe_ext, min(o[j], fill))
                break
            mae_ext = min(mae_ext, adv) if side > 0 else max(mae_ext, adv)
            mfe_ext = max(mfe_ext, fav) if side > 0 else min(mfe_ext, fav)
            peak = max(peak, fav) if side > 0 else min(peak, fav)
            # close of bar j: trailing update
            if use_trail and tr is not None and np.isfinite(tr[j]) and side * (c[j] - tr[j]) > 0:
                stop = max(stop, tr[j]) if side > 0 else min(stop, tr[j])
            held = j - e + 1
            if held >= 2 and j + 1 <= last:
                hit_opp = use_opp and bool(opp[j]) and bool(opp[j - 1])
                hit_uex = use_uex and uex is not None and bool(uex[j]) and bool(uex[j - 1])
                if hit_opp or hit_uex:
                    exit_px = o[j + 1] * (1 - side * slip); reason = "OPP" if hit_opp else "UEX"; j_exit = j + 1
                    mae_ext = min(mae_ext, o[j + 1]) if side > 0 else max(mae_ext, o[j + 1])
                    break
        if j_exit is None:
            j_exit = last
            exit_px = c[last] * (1 - side * slip); reason = "TIME" if last < n - 1 else "EOD"
        hold = j_exit - e + 1
        gross = side * (exit_px / entry - 1.0)
        fund = funding_8h * hold * bar_minutes / 480.0
        net = gross - 2 * fee - fund
        rows.append(dict(side=side, entry_idx=e, exit_idx=j_exit, entry_px=entry, exit_px=exit_px, gross=gross,
                         fee=2 * fee, funding=fund, net=net,
                         mae=side * (mae_ext / entry - 1.0), mfe=side * (mfe_ext / entry - 1.0),
                         reason=reason, hold=hold, sl_dist=d, signal_idx=int(i)))
        next_free = j_exit
    cols = ["side", "entry_idx", "exit_idx", "entry_px", "exit_px", "gross", "fee", "funding", "net", "mae", "mfe",
            "reason", "hold", "sl_dist", "signal_idx"]
    return (pd.DataFrame(rows) if rows else pd.DataFrame(columns=cols)), blocked

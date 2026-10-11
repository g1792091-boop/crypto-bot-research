"""Trend hunt, Phase-A reads (PREREG_HUNT_WIDE W 7; panel reads R1, R12 basics, R13 basics, R15; the owners'
continuous-account and leverage reads of 2026-10-11). They run inside the test step on the FIXED picks, after
picks.json exists. They are reported, never a pass: nothing here changes a pick, P0-P4, p, BH, a verdict, the 2군/3군
trigger or what goes to the paper bot, and no read chooses anything.

Layers
* Pure computation (no engine, no data): window lists, the two machines' caps, touch / give-back / days-to-touch of one
  window, the goal-board cell, Clopper-Pearson and moving-block bootstrap intervals, the control columns, the headline
  cell, the size fixed on select, the continuous-account reads (best 30-day run-up, geometric mean month, whole-period
  multiple, max drawdown, longest time under water), the rule-bot leverage unit and its wallet-risk table, signal rate
  and burst size, profit concentration, pick overlap and correlation, the paper lineup class and the D11 split. Every
  function takes arrays (an equity path, a trade list, event times) and is tested alone on synthetic paths
  (tests/test_hunt_reads_a.py).
* Engine glue (``window_market``, ``slice_signals``, ``record_from_raw``): builds one fresh-$1,000 window account on
  hunt.py's Market / Bank / simulate and turns the engine's raw tuple into a window record. hunt.py is imported
  read-only; this file never changes the engine or the tested decision path.

Equity path used for "touch": the finest marked path the engine returns. When the engine exports the first 5m step at
which each level is reached and the 5m peak (panel R1 ENGINE), touches are on 5m closes (``path_resolution`` = "5m");
otherwise they come from the daily marked path ``day_eq`` (the equity at each UTC day's last 5m close,
``path_resolution`` = "daily"), which can only miss an intraday touch, never invent one. Every record and cell carries
``path_resolution``.

D11: any row that contains a DeepSeek pick writes every money figure (multiples, shares, drawdowns, P&L, risk) only to
the private file; the repository output keeps labels and counts (``split_public_private``). R15 is counts only and is
public for every row.
"""

from __future__ import annotations

import datetime as dt
import math
from collections import deque

import numpy as np

from research.hunt import hunt as H

# ------------------------------------------------------------------ fixed numbers (panel R1, R12, R13, R15; owners)
GOAL_START = 1000.0                       # R1: fresh $1,000 per window
GOAL_BUST = 100.0                         # R1: bust = marked equity < $100 at any 5m close (= H.BUST_FRAC x $1,000)
GOAL_LEVELS = (2, 5, 10, 20, 30, 50, 100)
GOAL_RS = (0.005, 0.01, 0.02, 0.05, 0.10, 0.20)
GOAL_MODE_MIN_R = 0.05                    # machine B runs at r >= 5% only (PREREG_ALTPUMP 7)
GOAL_MODE_CAP_MAX = 0.60
ROLL_DAYS = 30
CAL_CTL_SEEDS = 1000                      # owners (c): calendar months pooled over seeds 1-1,000
ROLL_CTL_SEEDS = 100                      # rolling windows: seeds 1-100 ...
ROLL_CTL_SEEDS_SLOW = 50                  # ... 1-50 when one 30-day window run takes more than SLOW_WINDOW_S
SLOW_WINDOW_S = 0.03
CP_CONF = 0.95                            # calendar shares: exact Clopper-Pearson 95%
MBB_BLOCK, MBB_N, MBB_CONF = 30, 2000, 0.90   # rolling shares: moving blocks of 30 start days, 2,000 resamples, 90%
DIFF_CONF = 0.90                          # pick minus control: month-block bootstrap 90%
SIZE_FIX_BUST_MAX = 0.05                  # size fixed on select: cells with bust share <= 5%
HEADLINE = {"period": "test", "windows": "calendar", "machine": "B", "r": 0.05, "column": "touch", "level": 5}
INDEPENDENT_LINE = "overlapping windows: about 33 (test) / 36 (select) independent months"
ALTPUMP_SCALE_LINE = "altpump coin-flip goal-50x baseline: about 1% of months (for scale)"
RUNUP_DAYS = 30
LEV_LS = (20, 30, 40)                     # owners (f): '20배·30배·40배 경우'
LEV_BUF_MIN, LEV_BUF_ATR = 0.002, 1.0     # rule-bot check: stop inside liquidation by max(0.2%, 1 ATR)
CONC_TOP_POS, CONC_BIG_R = 0.10, 10.0     # R12: top 10% positions, positions >= 10R
TOP_MONTH_MAX = 0.50                      # owners (g): top month < 50% of the total log gain
JUDGE_CAPS = {"month_usd": 700.0, "month_stop_usd": 665.0, "day_usd": 45.0}   # placeholder caps, commit ca7a302
BURST_LEVELS = (10, 20, 30)
HOUR_MS = 3_600_000
DAY = H.DAY_MS
LINEUP = ("정식", "참고", "excluded")


def _f(x):
    """float or None (JSON-safe; NaN -> None)."""
    if x is None:
        return None
    x = float(x)
    return x if math.isfinite(x) else None


def _day(ms) -> str:
    return dt.datetime.fromtimestamp(int(ms) / 1000, dt.timezone.utc).strftime("%Y-%m-%d")


def _med(x):
    x = np.asarray(x, float)
    return _f(np.median(x)) if len(x) else None


# ------------------------------------------------------------------ R1 windows
def calendar_windows(start_ms: int, end_ms: int, first_ms: int | None = None) -> list:
    """UTC calendar months [m, m+1) inside [start, end); with ``first_ms`` only months that start at or after it
    (extra 2020: from the first day with a known 장세 label, full months only)."""
    ms = H.month_starts(int(start_ms), int(end_ms))
    out = [(int(a), int(b)) for a, b in zip(ms[:-1], ms[1:])]
    lo = int(start_ms) if first_ms is None else max(int(start_ms), int(first_ms))
    out = [w for w in out if w[0] >= lo]
    # a period that does not start on the 1st would give a partial first month: keep whole months only
    return [w for w in out if dt.datetime.fromtimestamp(w[0] / 1000, dt.timezone.utc).day == 1]


def rolling_windows(start_ms: int, end_ms: int, days: int = ROLL_DAYS, first_ms: int | None = None) -> list:
    """[d, d + days) for every UTC start day d >= start (or >= ``first_ms`` rounded up to a day) with d + days <= end:
    975 in test, 1,066 in select."""
    d = int(start_ms) if first_ms is None else max(int(start_ms), -(-int(first_ms) // DAY) * DAY)
    out = []
    while d + days * DAY <= int(end_ms):
        out.append((d, d + days * DAY))
        d += DAY
    return out


# ------------------------------------------------------------------ R1 machines
def goal_mode_caps(r: float) -> tuple:
    """PREREG_ALTPUMP 7, copied unchanged: total open risk <= min(4r, 60%), n_max = floor(cap / r)
    (5% -> 20%, 4; 10% -> 40%, 4; 20% -> 60%, 3)."""
    if r < GOAL_MODE_MIN_R - 1e-12:
        raise ValueError("goal-mode runs at r >= 5% only")
    cap = min(4.0 * r, GOAL_MODE_CAP_MAX)
    return cap, int(math.floor(cap / r + 1e-9))


def machine_spec(machine: str, r: float) -> dict:
    """The two R1 machines. A = as tested (H 7-8) with the W 7 scaling: total open-risk cap 4% x r / 0.5% and margin
    budget B = equity / 6 x r / 0.5% (identical to the tested machine at r = 0.5%), 6 positions, 20x. B = goal-mode
    (r >= 5%): caps of PREREG_ALTPUMP 7, B = equity / n_max, the coin's bracket maximum as the leverage cap, the
    bracket looked up at the first unit's notional, an add past that tier's cap skipped ('bracket')."""
    if machine == "A":
        s = r / H.R_BASE
        return {"machine": "A", "r": r, "risk_cap": H.RISK_CAP * s, "b_div": H.B_DIV / s, "max_pos": H.MAX_POS,
                "lev_max": H.LEV_MAX, "goal_brackets": False, "label": "as tested (W 7 scaling of cap and B)"}
    if machine == "B":
        cap, n = goal_mode_caps(r)
        return {"machine": "B", "r": r, "risk_cap": cap, "b_div": float(n), "max_pos": n,
                "lev_max": "bracket maximum (exchange30.json, fallback 20)", "goal_brackets": True,
                "label": "goal-mode machine, not the tested machine"}
    raise ValueError(f"machine {machine!r}")


def board_cells() -> list:
    """(machine, r) cells of the board: A at every r, B at r >= 5%."""
    return [("A", r) for r in GOAL_RS] + [("B", r) for r in GOAL_RS if r >= GOAL_MODE_MIN_R - 1e-12]


def rolling_control_seeds(seconds_per_window: float) -> int:
    """Pre-declared: rolling-window controls use seeds 1-100, or 1-50 when one 30-day window run (measured on
    synthetic bars before the run) takes more than 0.03 s."""
    return ROLL_CTL_SEEDS_SLOW if seconds_per_window > SLOW_WINDOW_S else ROLL_CTL_SEEDS


# ------------------------------------------------------------------ R1 one window
def touch_from_path(eq, start_eq: float = GOAL_START, levels=GOAL_LEVELS) -> tuple:
    """(peak, first index reaching each level or -1) of a marked equity path (values at step closes, no start
    point). Level x is reached when equity >= x x start."""
    eq = np.asarray(eq, float)
    peak = float(max(start_eq, eq.max())) if len(eq) else float(start_eq)
    first = []
    for x in levels:
        hit = np.flatnonzero(eq >= x * start_eq)
        first.append(int(hit[0]) if len(hit) else -1)
    return peak, np.asarray(first, np.int64)


def n_positions_for_share(pnl, gain: float, share: float = 0.8) -> int | None:
    """The smallest number of positions (largest net P&L first) whose summed P&L reaches ``share`` of ``gain``
    (None when the gain is not positive or the positions never reach it)."""
    if not gain > 0:
        return None
    p = np.sort(np.asarray(pnl, float))[::-1]
    cs = np.cumsum(p)
    hit = np.flatnonzero(cs >= share * gain - 1e-9 * abs(gain))
    return int(hit[0] + 1) if len(hit) else None


def window_record(start_eq: float, end_closed: float, end_marked: float, peak: float, touch_idx, step_ms: int,
                  bust: bool, pnl=None, levels=GOAL_LEVELS, resolution: str = "daily") -> dict:
    """One fresh-account window. ``end_closed``: positions open at the window end closed at the last 5m close with
    slippage and taker (headline); ``end_marked``: marked instead. ``touch_idx``: first step (0-based, at its close)
    reaching each level, -1 when never; days to a touch = (index + 1) x step / 1 day. Give-back = (peak - end) / peak
    on the closed end. ``pnl``: the window's positions' net P&L (for the 80%-of-gain count)."""
    touch_idx = np.asarray(touch_idx, np.int64)
    peak = max(float(peak), float(start_eq), float(end_marked), float(end_closed))
    m = float(end_closed) / start_eq
    rec = {"m_end": m, "m_marked": float(end_marked) / start_eq, "ln_m": math.log(max(m, 1e-12)),
           "peak_m": peak / start_eq, "bust": bool(bust), "resolution": resolution,
           "end_ge": [bool(m >= x - 1e-12) for x in levels], "touch": [bool(i >= 0) for i in touch_idx],
           "days_to": [((int(i) + 1) * step_ms / DAY) if i >= 0 else None for i in touch_idx],
           "give_back": (peak - float(end_closed)) / peak if peak > 0 else None}
    rec["n80"] = n_positions_for_share(pnl, float(end_closed) - start_eq) if (pnl is not None and m >= 5) else None
    rec["n_positions"] = None if pnl is None else int(len(pnl))
    return rec


def window_from_path(eq, step_ms: int, start_eq: float = GOAL_START, end_closed: float | None = None, pnl=None,
                     bust_level: float = GOAL_BUST, levels=GOAL_LEVELS, resolution: str | None = None) -> dict:
    """window_record from a marked path alone (tests, and the daily fallback). Bust = any value < $100."""
    eq = np.asarray(eq, float)
    peak, first = touch_from_path(eq, start_eq, levels)
    end_m = float(eq[-1]) if len(eq) else float(start_eq)
    res = resolution or ("5m" if step_ms == H.FIVE else "daily" if step_ms == DAY else f"{step_ms}ms")
    return window_record(start_eq, end_m if end_closed is None else end_closed, end_m, peak, first, step_ms,
                         bool(len(eq) and eq.min() < bust_level), pnl, levels, res)


# ------------------------------------------------------------------ intervals
def clopper_pearson(k: int, n: int, conf: float = CP_CONF) -> tuple:
    """Exact two-sided interval of a binomial share (0 of 33 -> upper 10.6%)."""
    from scipy.stats import beta
    if n <= 0:
        return (None, None)
    a = 1.0 - conf
    lo = 0.0 if k <= 0 else float(beta.ppf(a / 2, k, n - k + 1))
    hi = 1.0 if k >= n else float(beta.ppf(1 - a / 2, k + 1, n - k))
    return (lo, hi)


def block_indices(n: int, block: int, n_boot: int, seed: int) -> np.ndarray:
    """Moving-block bootstrap: (n_boot, n) indices made of ceil(n / b) blocks of b consecutive positions, block starts
    uniform on 0..n-b, cut to n. block = 1 is the plain (month) bootstrap."""
    b = max(1, min(int(block), n))
    nb = -(-n // b)
    rng = np.random.Generator(np.random.PCG64(seed))
    starts = rng.integers(0, n - b + 1, size=(n_boot, nb))
    return (starts[:, :, None] + np.arange(b)[None, None, :]).reshape(n_boot, nb * b)[:, :n]


def boot_ci(values, idx: np.ndarray, conf: float) -> tuple:
    """(low, high) of the mean of ``values`` over the bootstrap index rows."""
    v = np.asarray(values, float)
    if not len(v):
        return (None, None)
    means = v[idx].mean(axis=1)
    a = (1.0 - conf) / 2
    return (_f(np.quantile(means, a)), _f(np.quantile(means, 1 - a)))


def goal_seed(row_id: str, period: str, machine: str, r: float, *extra) -> int:
    """Seed parts ('hunt-wide', 'goalboard', row id, period, machine, r, ..., 'boot'), joined as hunt.seed_int."""
    return H.seed_int("hunt-wide", "goalboard", row_id, period, machine, float(r), *extra, "boot")


# ------------------------------------------------------------------ R1 one board cell
def _cols(recs: list, levels) -> dict:
    """Indicator columns of a list of window records (window order kept)."""
    out = {}
    for i, x in enumerate(levels):
        out[f"end_ge_x{x:g}"] = np.asarray([r["end_ge"][i] for r in recs], float)
        out[f"touch_x{x:g}"] = np.asarray([r["touch"][i] for r in recs], float)
    out["bust"] = np.asarray([r["bust"] for r in recs], float)
    return out


def board_cell(recs: list, windows: str, seed: int | None = None, levels=GOAL_LEVELS, eff: dict | None = None) -> dict:
    """R1 columns for one (row, period, window set, machine, r): shares of windows ending >= each level and touching
    each level, bust share, median / worst / best window multiple (closed end; marked shown too), mean ln multiple,
    median days to the first touch of x2 and x5, median give-back among windows that touched x5, median number of
    positions that made 80% of the gain among windows ending >= x5. Intervals: ``windows`` = "calendar" -> exact
    Clopper-Pearson 95%; "rolling" -> moving-block bootstrap 90% (blocks of 30 start days, 2,000 resamples, ``seed``)
    and the overlapping-windows line."""
    n = len(recs)
    out = {"windows": windows, "n_windows": n, "resolution": sorted({r["resolution"] for r in recs}) if n else []}
    if not n:
        return out
    m = np.asarray([r["m_end"] for r in recs])
    mm = np.asarray([r["m_marked"] for r in recs])
    cols = _cols(recs, levels)
    shares = {k: float(v.mean()) for k, v in cols.items()}
    out["shares"] = shares
    if windows == "calendar":
        out["ci"] = {k: clopper_pearson(int(round(v.sum())), n) for k, v in cols.items()}
        out["ci_kind"] = "Clopper-Pearson 95%"
    else:
        idx = block_indices(n, MBB_BLOCK, MBB_N, seed if seed is not None else 0)
        out["ci"] = {k: boot_ci(v, idx, MBB_CONF) for k, v in cols.items()}
        out["ci_kind"] = "moving-block bootstrap 90% (30 start days, 2,000 resamples)"
        out["note"] = INDEPENDENT_LINE
    i2, i5 = levels.index(2), levels.index(5)
    t5 = cols[f"touch_x{levels[i5]:g}"] > 0
    e5 = cols[f"end_ge_x{levels[i5]:g}"] > 0
    out.update({
        "median_m": _f(np.median(m)), "worst_m": _f(m.min()), "best_m": _f(m.max()),
        "mean_ln_m": _f(np.mean([r["ln_m"] for r in recs])),
        "marked": {"median_m": _f(np.median(mm)), "worst_m": _f(mm.min()), "best_m": _f(mm.max()),
                   "end_ge": {f"x{x:g}": float((mm >= x - 1e-12).mean()) for x in levels}},
        "median_days_to_x2": _med([r["days_to"][i2] for r in recs if r["days_to"][i2] is not None]),
        "median_days_to_x5": _med([r["days_to"][i5] for r in recs if r["days_to"][i5] is not None]),
        "median_give_back_touch_x5": _med([r["give_back"] for r, t in zip(recs, t5) if t
                                           and r["give_back"] is not None]),
        "median_positions_80pct_end_ge_x5": _med([r["n80"] for r, e in zip(recs, e5) if e and r["n80"] is not None]),
        "n_touch_x5": int(t5.sum()), "n_end_ge_x5": int(e5.sum()), "n_bust": int(cols["bust"].sum())})
    if eff is not None:
        out["effective_risk"] = eff
    return out


def control_columns(pick_recs: list, ctl_recs: list, windows: str, seed: int, levels=GOAL_LEVELS) -> dict:
    """Controls on the same board: ``ctl_recs`` = one list of window records per seed, each in the pick's window order.
    Per share column: the pick's share, the pooled control share, the 5-95% range of the per-seed shares, and
    pick minus control (per window: pick indicator - mean over seeds) with a bootstrap 90% CI (calendar: month blocks
    of 1; rolling: blocks of 30 start days)."""
    n = len(pick_recs)
    if not n or not ctl_recs:
        return {"n_seeds": len(ctl_recs), "n_windows": n}
    if any(len(c) != n for c in ctl_recs):
        raise ValueError("every control seed needs the pick's windows")
    pc = _cols(pick_recs, levels)
    cc = [_cols(c, levels) for c in ctl_recs]
    idx = block_indices(n, 1 if windows == "calendar" else MBB_BLOCK, MBB_N, seed)
    out = {"n_seeds": len(ctl_recs), "n_windows": n, "columns": {}}
    for k, v in pc.items():
        mat = np.vstack([c[k] for c in cc])            # (seeds, windows)
        per_seed = mat.mean(axis=1)
        d = v - mat.mean(axis=0)
        out["columns"][k] = {"pick": float(v.mean()), "control_pooled": float(mat.mean()),
                             "control_p5": _f(np.quantile(per_seed, 0.05)),
                             "control_p95": _f(np.quantile(per_seed, 0.95)),
                             "pick_minus_control": float(d.mean()), "ci90": boot_ci(d, idx, DIFF_CONF)}
    return out


def effective_risk(r: float, q1, d0, U, cut_bits, adds, lev, gross_max=None) -> dict:
    """Realised risk next to the nominal r, over the cell's positions: effective r = r x median(q1 x D0 / U), the p90
    of q1 x D0 / U, the share of first units cut (any, and by reason: liquidity, margin budget, free wallet), the
    share of positions filling add 1, 2 and 3, the median leverage, and the max gross notional / equity when the
    engine exports it (else None)."""
    q1, d0, U = (np.asarray(x, float) for x in (q1, d0, U))
    n = len(q1)
    if not n:
        return {"nominal_r": r, "n_positions": 0}
    ratio = q1 * d0 / np.where(U > 0, U, np.nan)
    cut = np.asarray(cut_bits, np.int64)
    adds = np.asarray(adds, np.int64)
    return {"nominal_r": r, "n_positions": int(n), "effective_r": _f(r * np.nanmedian(ratio)),
            "ratio_median": _f(np.nanmedian(ratio)), "ratio_p90": _f(np.nanquantile(ratio, 0.9)),
            "effective_r_p90": _f(r * np.nanquantile(ratio, 0.9)),
            "share_first_unit_cut": float((cut != 0).mean()),
            "share_first_unit_cut_by": {H.CUT_NAMES[i]: float(((cut >> i) & 1).mean())
                                        for i in range(len(H.CUT_NAMES))},
            "share_add_level": [float((adds >= a).mean()) for a in (1, 2, 3)],
            "median_leverage": _med(lev), "max_gross_notional_over_equity": _f(gross_max)}


def headline(board: dict) -> dict | None:
    """The headline cell named before the test: the share of test calendar months in which a fresh $1,000 at
    goal-mode r = 5% touched $5,000, with its interval, beside the (a) and (b) shares and the bust share.
    ``board`` = {(period, windows, machine, r): {"cell": board_cell, "controls": {"a": .., "b": ..}}}."""
    h = HEADLINE
    c = board.get((h["period"], h["windows"], h["machine"], h["r"]))
    if not c or not c["cell"].get("n_windows"):
        return None
    col = f"{h['column']}_x{h['level']:g}"
    cell = c["cell"]
    ctl = c.get("controls") or {}
    return {"what": "share of test calendar months where a fresh $1,000 at goal-mode r = 5% touched $5,000",
            "share": cell["shares"][col], "ci": cell["ci"][col], "bust_share": cell["shares"]["bust"],
            "n_windows": cell["n_windows"],
            "control_a": (ctl.get("a") or {}).get("columns", {}).get(col, {}).get("control_pooled"),
            "control_b": (ctl.get("b") or {}).get("columns", {}).get(col, {}).get("control_pooled")}


def size_fixed_on_select(select_calendar: dict) -> tuple | None:
    """Per row, named before the test: the (machine, r) cell with the highest mean ln(window multiple) over select
    calendar months among cells with bust share <= 5%; ties: lower r, then machine A before B. ``select_calendar`` =
    {(machine, r): board_cell}. Its test row is printed as 'size fixed before the test'."""
    ok = [(k, c) for k, c in select_calendar.items()
          if c.get("n_windows") and c["shares"]["bust"] <= SIZE_FIX_BUST_MAX + 1e-12 and c.get("mean_ln_m") is not None]
    if not ok:
        return None
    return min(ok, key=lambda kc: (-kc[1]["mean_ln_m"], kc[0][1], kc[0][0]))[0]


# ------------------------------------------------------------------ owners' continuous-account reads
def path_points(start_ms: int, start_eq: float, eq, step_ms: int) -> tuple:
    """(times, values) of a marked path with its start point: values at the close of each step after ``start_ms``."""
    eq = np.asarray(eq, float)
    t = int(start_ms) + np.arange(len(eq) + 1, dtype=np.int64) * int(step_ms)
    return t, np.r_[float(start_eq), eq]


def best_runup(t, eq, days: int = RUNUP_DAYS) -> dict:
    """Largest trough-to-peak run-up inside any ``days``-day window: max over j of eq[j] / min(eq[i]), i <= j,
    t[j] - t[i] <= days; with the trough and peak dates."""
    t = np.asarray(t, np.int64)
    eq = np.asarray(eq, float)
    if not len(eq):
        return {"multiple": None}
    w = days * DAY
    dq: deque = deque()                       # indices with increasing values: front = window minimum
    best, bi, bj = 1.0, 0, 0
    for j in range(len(eq)):
        while dq and eq[dq[-1]] >= eq[j]:
            dq.pop()
        dq.append(j)
        while t[j] - t[dq[0]] > w:
            dq.popleft()
        i = dq[0]
        if eq[i] > 0 and eq[j] / eq[i] > best:
            best, bi, bj = eq[j] / eq[i], i, j
    return {"multiple": float(best), "trough_ms": int(t[bi]), "peak_ms": int(t[bj]), "trough_day": _day(t[bi]),
            "peak_day": _day(t[bj]), "days": float((t[bj] - t[bi]) / DAY)}


def drawdown_recovery(t, eq) -> dict:
    """Max drawdown (peak to trough of the path) with its dates and the time it took to get back to that peak
    ("open" when the path ended first), and the longest stretch under water (from a peak to the first value back at
    or above it; the start counts as a peak; an unrecovered last stretch counts up to the path end, flagged open)."""
    t = np.asarray(t, np.int64)
    eq = np.asarray(eq, float)
    if not len(eq):
        return {}
    pk = np.maximum.accumulate(eq)
    dd = np.where(pk > 0, (pk - eq) / np.where(pk > 0, pk, 1.0), 0.0)
    j = int(np.argmax(dd))
    i = int(np.flatnonzero(eq[:j + 1] == pk[j])[0]) if dd[j] > 0 else j
    rec = np.flatnonzero(eq[j:] >= pk[j])
    if dd[j] > 0 and len(rec):
        r_ix, open_ = j + int(rec[0]), False
    else:
        r_ix, open_ = len(eq) - 1, dd[j] > 0
    out = {"max_dd": float(dd[j]), "dd_peak_day": _day(t[i]), "dd_trough_day": _day(t[j]),
           "dd_recover_days": float((t[r_ix] - t[i]) / DAY) if dd[j] > 0 else 0.0, "dd_recover_open": bool(open_),
           "dd_recover_day": None if open_ or dd[j] == 0 else _day(t[r_ix])}
    peak_v, peak_i, under = eq[0], 0, False
    longest, li, lj, lopen = 0.0, 0, 0, False
    for k in range(1, len(eq)):
        if eq[k] >= peak_v:
            if under and (t[k] - t[peak_i]) / DAY > longest:
                longest, li, lj, lopen = (t[k] - t[peak_i]) / DAY, peak_i, k, False
            peak_v, peak_i, under = eq[k], k, False
        else:
            under = True
    if under and (t[-1] - t[peak_i]) / DAY >= longest:
        longest, li, lj, lopen = (t[-1] - t[peak_i]) / DAY, peak_i, len(eq) - 1, True
    out.update({"longest_under_water_days": float(longest), "under_water_from": _day(t[li]),
                "under_water_to": _day(t[lj]), "under_water_open": bool(lopen)})
    return out


def continuous_reads(start_ms: int, start_eq: float, eq, step_ms: int, lnM, end_eq: float,
                     max_dd_5m: float | None = None) -> dict:
    """The owners' continuous-account reads of one run: best 30-day run-up and its dates, geometric mean monthly
    return exp(mean ln M) - 1, whole-period multiple, max drawdown (the engine's 5m figure when given; dates from the
    path) and the longest time to recover. Path resolution as R1."""
    t, v = path_points(start_ms, start_eq, eq, step_ms)
    lnM = np.asarray(lnM, float)
    out = {"resolution": "5m" if step_ms == H.FIVE else "daily" if step_ms == DAY else f"{step_ms}ms",
           "best_30d_runup": best_runup(t, v), "geo_mean_monthly_return": _f(np.expm1(lnM.mean())) if len(lnM) else None,
           "whole_period_multiple": float(end_eq) / start_eq}
    out.update(drawdown_recovery(t, v))
    out["max_dd_path"] = out.pop("max_dd", None)
    out["max_dd"] = _f(max_dd_5m) if max_dd_5m is not None else out["max_dd_path"]
    return out


# ------------------------------------------------------------------ owners' leverage read (rule-bot style sizing)
def _tier(notional: float, cap) -> int:
    """hunt.py's bracket convention: the first tier whose cap is above the notional (last tier otherwise)."""
    cap = np.asarray(cap, float)
    hit = np.flatnonzero(notional < cap)
    return int(hit[0]) if len(hit) else len(cap) - 1


def liq_price(side: int, Q: float, cost: float, margin: float, mmr: float, cum: float) -> float:
    """Binance isolated one-way (hunt.py _set_liq): long (cost - M - cum) / (Q (1 - mmr)); short mirror."""
    if side > 0:
        return (cost - margin - cum) / (Q * (1.0 - mmr))
    return (cost + margin + cum) / (Q * (1.0 + mmr))


def rulebot_unit(L: int, equity: float, free: float, P0: float, side: int, D0: float, atr: float, br: dict, k: int,
                 slip: float = H.COSTS["base"][1], taker: float = H.COSTS["base"][0]) -> dict:
    """The first unit of the leverage read: margin = L% of equity, notional = L x margin (L = 20 -> 4x equity,
    30 -> 9x, 40 -> 16x), isolated at L. Skipped (and counted, by reason) when the free wallet cannot pay margin plus
    taker ('free_wallet'), the notional is under the coin's minimum ('min_notional'), the bracket at that notional
    does not allow L ('bracket'), or the rule-bot check fails: the first stop P0 -/+ D0 must lie inside the
    liquidation price by at least max(0.2% of the fill, 1 ATR) ('liq_buffer'). ``br`` = hunt.load_brackets(); k = the
    coin's row."""
    fill = P0 * (1.0 + side * slip)
    margin = L / 100.0 * equity
    q = margin * L / fill
    notional = q * fill
    out = {"L": int(L), "ok": False, "reason": None, "q": q, "notional": notional, "margin": margin}
    if margin + taker * notional > free:
        out["reason"] = "free_wallet"
        return out
    if notional < float(br["min_notional"][k]):
        out["reason"] = "min_notional"
        return out
    b = _tier(notional, br["cap"][k][:int(br["n"][k])])
    if L > int(br["lev"][k][b]):
        out["reason"] = "bracket"
        return out
    liq = liq_price(side, q, notional, margin, float(br["mmr"][k][b]), float(br["cum"][k][b]))
    stop = P0 - side * D0
    buf = max(LEV_BUF_MIN * fill, LEV_BUF_ATR * atr)
    out.update({"liq": liq, "stop": stop, "buffer": buf, "tier": b})
    if (stop - liq) * side < buf:
        out["reason"] = "liq_buffer"
        return out
    out["ok"] = True
    out["wallet_risk_per_stop"] = q * D0 / equity
    return out


def stop_loss_frac(L: int, d0_over_p0, slip: float = H.COSTS["base"][1], taker: float = H.COSTS["base"][0]) -> dict:
    """Wallet share lost at the first stop for a rule-bot unit at L, price only (L x L% x D0/P0) and with costs
    (fill slippage, exit slippage, taker both ways), per signal."""
    d = np.asarray(d0_over_p0, float)
    notional_over_eq = L * L / 100.0
    q_over = notional_over_eq / (1.0 + slip)                 # q x P0 / equity
    fill, exitp = 1.0 + slip, (1.0 - d) * (1.0 - slip)       # in units of P0, long (a short loses d x slip more)
    with_costs = q_over * (fill - exitp) + taker * q_over * (fill + exitp)
    return {"price_only": q_over * d, "with_costs": with_costs}


def wallet_risk_table(d0_over_p0, Ls=LEV_LS) -> dict:
    """L -> the median (p10, p90) wallet risk per stop over the given D0 / P0 values (a pick's gated signals), price
    only and with costs, and the share of signals whose stop would cost more than the whole wallet."""
    d = np.asarray(d0_over_p0, float)
    d = d[np.isfinite(d) & (d > 0)]
    out = {}
    for L in Ls:
        s = stop_loss_frac(L, d)
        out[str(L)] = {"notional_over_equity": L * L / 100.0, "margin_over_equity": L / 100.0, "n": int(len(d)),
                       "median": _med(s["price_only"]), "median_with_costs": _med(s["with_costs"]),
                       "p10": _f(np.quantile(s["price_only"], 0.1)) if len(d) else None,
                       "p90": _f(np.quantile(s["price_only"], 0.9)) if len(d) else None,
                       "share_over_wallet": float((s["with_costs"] >= 1.0).mean()) if len(d) else None}
    return out


# ------------------------------------------------------------------ R15 signal rate and burst size (counts only)
def _stats(x) -> dict:
    x = np.asarray(x, float)
    if not len(x):
        return {"mean": None, "p50": None, "p95": None, "max": None}
    return {"mean": float(x.mean()), "p50": float(np.quantile(x, 0.5)), "p95": float(np.quantile(x, 0.95)),
            "max": float(x.max())}


def _month_year_counts(ms, start_ms: int, end_ms: int) -> tuple:
    ms = np.asarray(ms, np.int64)
    keys = [H.month_key(a) for a in H.month_starts(start_ms, end_ms)[:-1]]
    mk = ms.astype("datetime64[ms]").astype("datetime64[M]").astype(str)
    uk, cnt = np.unique(mk, return_counts=True)
    got = dict(zip(uk.tolist(), cnt.tolist()))
    by_m = {k: int(got.get(k, 0)) for k in keys}
    by_y: dict = {}
    for k, v in by_m.items():
        by_y[k[:4]] = by_y.get(k[:4], 0) + v
    return by_m, by_y


def signal_rate(close_ms, gated, start_ms: int, end_ms: int) -> dict:
    """R15 for one event set (one pick, or the union the paper bot would feed the judge): events per UTC day with
    gated (G) and gate-blocked (N) events counted separately (mean, p50, p95, max day; days with no event count as
    0); events at a single signal close (max, p99, over closes with at least one event) and the share of those closes
    with more than 10, 20 and 30 events; events per UTC hour (p99, max; every hour of the period); counts by month and
    by year. Counts only (D11-safe)."""
    c = np.asarray(close_ms, np.int64)
    g = np.asarray(gated, bool)
    keep = (c >= start_ms) & (c < end_ms)
    c, g = c[keep], g[keep]
    n_days = int((end_ms - start_ms) // DAY)
    n_hours = int((end_ms - start_ms) // HOUR_MS)
    d = (c - start_ms) // DAY
    out = {"events": int(len(c)), "gated": int(g.sum()), "gate_blocked": int((~g).sum()), "days": n_days}
    for name, m in (("all", np.ones(len(c), bool)), ("G", g), ("N", ~g)):
        out[f"per_day_{name}"] = _stats(np.bincount(d[m], minlength=n_days)[:n_days] if n_days else [])
    for name, m in (("all", np.ones(len(c), bool)), ("G", g)):
        _, per_close = np.unique(c[m], return_counts=True)
        out[f"per_close_{name}"] = {"closes_with_events": int(len(per_close)),
                                    "max": int(per_close.max()) if len(per_close) else 0,
                                    "p99": _f(np.quantile(per_close, 0.99)) if len(per_close) else None,
                                    **{f"share_closes_gt_{b}": float((per_close > b).mean()) if len(per_close)
                                       else None for b in BURST_LEVELS}}
    hours = np.bincount((c - start_ms) // HOUR_MS, minlength=n_hours)[:n_hours] if n_hours else np.zeros(0)
    out["per_hour_all"] = {"p99": _f(np.quantile(hours, 0.99)) if len(hours) else None,
                           "max": int(hours.max()) if len(hours) else 0}
    for name, m in (("G", g), ("N", ~g)):
        bm, by = _month_year_counts(c[m], start_ms, end_ms)
        out[f"by_month_{name}"], out[f"by_year_{name}"] = bm, by
    return out


def union_events(event_sets: list) -> dict:
    """Union of several picks' events (dicts with coin, side, close_ms, gated). ``total`` keeps every pick's event
    (one judge call per pick and event); ``distinct`` merges the same (coin, side, close) across picks, gated when any
    pick's event there is gated."""
    if not event_sets:
        z = np.zeros(0, np.int64)
        return {"total": {"close_ms": z, "gated": z.astype(bool)}, "distinct": {"close_ms": z, "gated": z.astype(bool)}}
    cat = {k: np.concatenate([np.asarray(e[k]) for e in event_sets]) for k in ("coin", "side", "close_ms", "gated")}
    key = np.stack([cat["close_ms"].astype(np.int64), cat["coin"].astype(np.int64), cat["side"].astype(np.int64)], 1)
    uk, inv = np.unique(key, axis=0, return_inverse=True)
    inv = np.asarray(inv).reshape(-1)
    g = np.zeros(len(uk), bool)
    np.logical_or.at(g, inv, cat["gated"].astype(bool))
    return {"total": {"close_ms": cat["close_ms"].astype(np.int64), "gated": cat["gated"].astype(bool)},
            "distinct": {"close_ms": uk[:, 0], "coin": uk[:, 1], "side": uk[:, 2], "gated": g}}


def taken_dropped(cand_ms, status, start_ms: int, end_ms: int, names=H.SKIP_NAMES) -> dict:
    """Candidates taken vs dropped, by reason (status 0 = taken, i + 1 = names[i]; -1 = not reached, e.g. after a
    bust), in total, by month and by year."""
    ms = np.asarray(cand_ms, np.int64)
    st = np.asarray(status, np.int64)
    labels = {0: "taken", -1: "not_reached", **{i + 1: n for i, n in enumerate(names)}}
    out = {"total": {labels[s]: int((st == s).sum()) for s in labels}}
    out["by_month"], out["by_year"] = {}, {}
    for s, lab in labels.items():
        bm, by = _month_year_counts(ms[st == s], start_ms, end_ms)
        out["by_month"][lab], out["by_year"][lab] = bm, by
    return out


def judge_budget(rate: dict, cost_per_call: float | None, which: str = "G", caps: dict = JUDGE_CAPS) -> dict:
    """Monthly and daily call counts x a per-call cost (a parameter), against the owners' placeholder caps
    ($700 a month, all calls stop at 95% = $665; $45 a day; commit ca7a302). ``which``: 'G' (gated events), or 'all'
    (gated and gate-blocked, when the judge is asked on both)."""
    bm = rate[f"by_month_{which}"] if which != "all" else {
        k: rate["by_month_G"][k] + rate["by_month_N"][k] for k in rate["by_month_G"]}
    per_day = rate[f"per_day_{which}"]
    months = np.asarray(list(bm.values()), float)
    out = {"calls_per_month": _stats(months), "calls_per_day": per_day, "cost_per_call": cost_per_call,
           "caps": caps}
    if cost_per_call is None:
        return out
    out.update({"usd_per_month_mean": _f(months.mean() * cost_per_call) if len(months) else None,
                "usd_per_month_max": _f(months.max() * cost_per_call) if len(months) else None,
                "usd_per_day_p95": _f(per_day["p95"] * cost_per_call) if per_day["p95"] is not None else None,
                "usd_per_day_max": _f(per_day["max"] * cost_per_call) if per_day["max"] is not None else None,
                "months_over_stop": int((months * cost_per_call > caps["month_stop_usd"]).sum()),
                "p95_day_over_cap": bool(per_day["p95"] is not None and
                                         per_day["p95"] * cost_per_call > caps["day_usd"])})
    return out


# ------------------------------------------------------------------ R12 basics: profit concentration
def concentration(pnl, U, lnM) -> dict:
    """Share of profit from the top 10% of positions (H 10: the ceil(10%) largest net P&L / all positive net P&L), from
    positions >= 10R (net P&L / U), and the top month's share of the total log gain (max ln M / sum ln M, defined
    when the sum is positive; also over the positive months only)."""
    pnl = np.asarray(pnl, float)
    U = np.asarray(U, float)
    lnM = np.asarray(lnM, float)
    gross = pnl[pnl > 0].sum()
    out = {"n_positions": int(len(pnl)), "top10pct_share_of_profit": None, "share_of_profit_ge_10R": None}
    if len(pnl) and gross > 0:
        top = np.sort(pnl)[::-1][:max(1, int(math.ceil(CONC_TOP_POS * len(pnl))))].sum()
        out["top10pct_share_of_profit"] = float(top / gross)
        big = (pnl / np.where(U > 0, U, np.nan)) >= CONC_BIG_R
        out["share_of_profit_ge_10R"] = float(pnl[big & (pnl > 0)].sum() / gross)
    tot = lnM.sum() if len(lnM) else 0.0
    pos = lnM[lnM > 0].sum() if len(lnM) else 0.0
    out["top_month_index"] = int(np.argmax(lnM)) if len(lnM) else None
    out["top_month_share_of_log_gain"] = _f(lnM.max() / tot) if len(lnM) and tot > 0 else None
    out["top_month_share_of_positive_log"] = _f(lnM.max() / pos) if len(lnM) and pos > 0 else None
    return out


# ------------------------------------------------------------------ R13 basics: pick overlap and correlation
def signal_overlap(a: dict, b: dict, window_ms: int) -> float | None:
    """Share of a's signals with a b signal on the same coin and side whose close lies within ``window_ms`` (one
    signal bar of the longer of the two timeframes)."""
    ca, cb = np.asarray(a["close_ms"], np.int64), np.asarray(b["close_ms"], np.int64)
    if not len(ca):
        return None
    hit = 0
    for k in np.unique(a["coin"]):
        for s in (1, -1):
            ma = (np.asarray(a["coin"]) == k) & (np.asarray(a["side"]) == s)
            tb = np.sort(cb[(np.asarray(b["coin"]) == k) & (np.asarray(b["side"]) == s)])
            if not ma.any() or not len(tb):
                continue
            ta = ca[ma]
            i = np.searchsorted(tb, ta)
            near = np.full(len(ta), np.inf)
            for j in (i - 1, i):
                ok = (j >= 0) & (j < len(tb))
                near[ok] = np.minimum(near[ok], np.abs(tb[j[ok]] - ta[ok]))
            hit += int((near <= window_ms).sum())
    return hit / len(ca)


def _in_market(tin, tout, T: int) -> np.ndarray:
    """Per 5m step of a run (0..T-1): at least one position open (entered at its fill bar tin, closed at tout; an
    open-at-end position counts through the last step)."""
    mark = np.zeros(T + 1, np.int64)
    for a, b in zip(np.asarray(tin, np.int64), np.asarray(tout, np.int64)):
        b = T - 1 if b < 0 else b
        mark[max(a, 0)] += 1
        mark[min(b, T - 1) + 1] -= 1
    return np.cumsum(mark)[:T] > 0


def time_overlap(a_iv: tuple, b_iv: tuple, T: int) -> float | None:
    """Share of a's time in the market (any position open) during which b also holds a position."""
    ia, ib = _in_market(*a_iv, T), _in_market(*b_iv, T)
    return float((ia & ib).sum() / ia.sum()) if ia.any() else None


def corr(x, y) -> float | None:
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) != len(y) or len(x) < 3 or x.std() == 0 or y.std() == 0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def overlap_matrix(rows: dict, T: int) -> dict:
    """R13 basics over the tested picks (and the v1 pick): ``rows`` = {id: {"events": {coin, side, close_ms},
    "tf_ms": int, "iv": (tin, tout), "lnM": [...]}}. Per ordered pair: signal overlap (within one bar of the longer
    timeframe), time-in-market overlap; per unordered pair: correlation of monthly ln M."""
    ids = list(rows)
    out = {"ids": ids, "signal_overlap": {}, "time_overlap": {}, "corr_monthly_lnM": {}}
    for a in ids:
        for b in ids:
            if a == b:
                continue
            w = max(rows[a]["tf_ms"], rows[b]["tf_ms"])
            out["signal_overlap"][f"{a}|{b}"] = signal_overlap(rows[a]["events"], rows[b]["events"], w)
            out["time_overlap"][f"{a}|{b}"] = time_overlap(rows[a]["iv"], rows[b]["iv"], T)
            if a < b:
                out["corr_monthly_lnM"][f"{a}|{b}"] = corr(rows[a]["lnM"], rows[b]["lnM"])
    return out


# ------------------------------------------------------------------ owners (g): paper lineup class
def lineup_class(passed: bool, base: dict, cost2: dict, mean_d_a: float | None, mean_d_b: float | None,
                 top_month_share: float | None) -> dict:
    """정식 = research PASS. 참고 = a tested pick with test mean monthly ln M > 0, median monthly multiple >= 1, beating
    both controls' means (mean d_m > 0 for (a) and for (b)), cost x2 mean ln M > 0, max drawdown < 50%, no bust and a
    top month under 50% of the total log gain. Everything else is excluded from the paper lineup."""
    conds = {"mean_lnM_gt_0": bool(base.get("mean_lnM", 0) > 0),
             "median_M_ge_1": bool(base.get("median_M", 0) >= 1.0),
             "beats_a": bool(mean_d_a is not None and mean_d_a > 0),
             "beats_b": bool(mean_d_b is not None and mean_d_b > 0),
             "cost2_mean_lnM_gt_0": bool(cost2.get("mean_lnM", 0) > 0),
             "max_dd_lt_50": bool(base.get("max_dd", 1.0) < H.DD_MAX),
             "no_bust": not bool(base.get("bust", True)),
             "top_month_lt_50": bool(top_month_share is not None and top_month_share < TOP_MONTH_MAX)}
    cls = LINEUP[0] if passed else LINEUP[1] if all(conds.values()) else LINEUP[2]
    return {"class": cls, "conditions": conds}


# ------------------------------------------------------------------ D11
PUBLIC_KEYS = {"id", "label", "role", "row", "machine", "r", "period", "windows", "n_windows", "n_positions",
               "n_seeds", "resolution", "note", "L", "family", "name", "strategy", "kind", "tf", "gate", "pick_no",
               "members", "events", "gated", "gate_blocked", "days", "skipped", "liquidations", "class"}


COUNT_DICTS = {"skipped", "skipped_entries", "add_skipped", "signal_counts", "skip_reasons"}   # {name: int} only
LABEL_FLOATS = {"r"}                                                                             # a size label


def redact(obj, ds: bool):
    """D11: for a row containing a DeepSeek pick keep only labels and counts (``PUBLIC_KEYS``, and the integer
    entries of ``COUNT_DICTS``, recursively); every money figure, shares included, stays out of the public copy. Rows
    without a DeepSeek pick pass unchanged."""
    if not ds:
        return obj
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in PUBLIC_KEYS and (not isinstance(v, (dict, list, tuple, float)) or k in LABEL_FLOATS):
                out[k] = v
            elif k in COUNT_DICTS and isinstance(v, dict):
                out[k] = {a: b for a, b in v.items() if isinstance(b, (int, np.integer)) and not isinstance(b, bool)}
            elif isinstance(v, dict):
                r = redact(v, True)
                if r:
                    out[k] = r
        return out
    return None


def split_public_private(rows: dict, ds_of: dict) -> tuple:
    """(public, private) of {row id: read}: the private copy is everything; the public copy redacts DeepSeek rows and
    marks them."""
    public = {}
    for rid, v in rows.items():
        if ds_of.get(rid):
            red = redact(v, True) or {}
            red["note"] = "DeepSeek row: figures in the private file (D11)"
            public[rid] = red
        else:
            public[rid] = v
    return public, rows

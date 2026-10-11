"""Trend hunt, Phase-A reads (PREREG_HUNT_WIDE W 7; panel reads R1, R12 basics, R13 basics, R15; the owners'
continuous-account and leverage reads of 2026-10-11). Called by hunt.py's reads hook (``run(ctx)``, interface api 1)
after test.json and the verdict are written, on the FIXED rows (tested picks, the v1 pick, the baskets). Reported,
never a pass: nothing here changes a pick, P0-P4, p, BH, a verdict, a batch, the lineup or what goes to the paper
bot; no read chooses anything; this file writes no file (the hook writes ``ctx["out"]`` and ``ctx["private"]``).

What it computes
* R1 goal board: per row, period (test = headline, select = "chosen here", extra 2020) and window set (UTC calendar
  months; rolling 30-day windows, one per UTC start day), a fresh $1,000 account per window on machine A (as tested,
  W 7 scaling of the open-risk cap and the margin budget) at r = 0.5/1/2/5/10/20% and machine B (goal-mode caps of
  PREREG_ALTPUMP 7) at r = 5/10/20%: shares of windows ending >= x2 .. x100 and touching each level (marked equity at
  any 5m close), bust share (< $100), median / worst / best window, days to the first x2 / x5, give-back, the
  positions that made 80% of the gain, realised-risk columns; Clopper-Pearson 95% (calendar) and moving-block
  bootstrap 90% (rolling); controls (a) and (b) on the same board (calendar: seeds 1-1,000 pooled; rolling: 1-100,
  or 1-50 when a window run takes > 0.03 s) with pick minus control and its block-bootstrap 90% CI; the headline cell
  and the size fixed on select.
* Leverage read (owners (f)): the same board with rule-bot sizing at L = 20 / 30 / 40 (margin L% of equity, notional
  L x margin, isolated, the engine's bracket rule) and the rule-bot check (the first stop inside the liquidation price
  by max(0.2%, 1 ATR), else the entry is skipped and counted); liquidations, skipped entries, the wallet risk per stop.
* Continuous-account reads (owners): best trough-to-peak run-up inside any 30 days and its dates, geometric mean
  monthly return, whole-period multiple, max drawdown and the longest time to recover, at r = 0.5% and 1% (the tested
  $5,000 accounts) and at the size fixed on select (fresh $1,000).
* R15 signal rate and burst size (counts), R12 basics (profit share of the top 10% positions, of positions >= 10R and
  of the top month), R13 basics (signal and time overlap of the picks, correlation of monthly ln M).

Equity path: every touch, peak and day count uses the 5m marked equity the engine returns (``path="5m"`` or its 5m
``peak``): ``resolution`` = "5m" throughout.

D11: every money figure of a row that contains a DeepSeek pick (and of every pair naming one) goes to
``ctx["private"]`` only; the public copy keeps labels and counts (``labels_counts``, ``ints_only``).

The pure functions (window lists, caps, one window, intervals, board cell, controls, continuous reads, leverage unit,
signal rate, concentration, overlap, D11) take arrays and are tested alone on synthetic paths
(tests/test_hunt_reads_a.py).
"""

from __future__ import annotations

import datetime as dt
import math
import sys
import time
from collections import deque

import numpy as np

from research.hunt import hunt as H

# ------------------------------------------------------------------ fixed numbers (panel R1, R12, R13, R15; owners)
GOAL_START = 1000.0                       # R1: fresh $1,000 per window
GOAL_BUST = 100.0                         # R1: bust = marked equity < $100 (= the engine's 10% of the start wallet)
GOAL_LEVELS = (2, 5, 10, 20, 30, 50, 100)
GOAL_RS = (0.005, 0.01, 0.02, 0.05, 0.10, 0.20)
GOAL_MODE_MIN_R = 0.05                    # machine B runs at r >= 5% only (PREREG_ALTPUMP 7)
GOAL_MODE_CAP_MAX = 0.60
GOAL_MODE_LEVMAX = 125                    # interface: the bracket's own maximum binds (fallback coins 20)
ROLL_DAYS = 30
READ_PERIODS = ("test", "select", "extra")
PERIOD_LABEL = {"test": "headline", "select": "chosen here", "extra": "extra 2020"}
CAL_CTL_SEEDS = 1000                      # owners (c): calendar months pooled over seeds 1-1,000
ROLL_CTL_SEEDS = 100                      # rolling windows: seeds 1-100 ...
ROLL_CTL_SEEDS_SLOW = 50                  # ... 1-50 when one 30-day window run takes more than SLOW_WINDOW_S
SLOW_WINDOW_S = 0.03
LEV_CTL_SEEDS = 100                       # leverage read: seeds 1-100 (rolling: also cut to 1-50 when slow)
CP_CONF = 0.95                            # calendar shares: exact Clopper-Pearson 95%
MBB_BLOCK, MBB_N, MBB_CONF = 30, 2000, 0.90   # rolling shares: moving blocks of 30 start days, 2,000 resamples, 90%
DIFF_CONF = 0.90                          # pick minus control: block bootstrap 90% (calendar: months; rolling: 30 days)
HEADLINE = {"period": "test", "windows": "calendar", "machine": "B", "r": 0.05, "column": "touch_x5"}
INDEPENDENT_LINE = "overlapping windows: about 33 (test) / 36 (select) independent months"
ALTPUMP_SCALE_LINE = "altpump coin-flip goal-50x baseline: about 1% of months (quoted for scale)"
RUNUP_DAYS = 30
CONT_RS = (0.005, 0.01)                   # continuous reads on the tested accounts ($5,000)
LEV_LS = (20, 30, 40)                     # owners (f): '20배·30배·40배 경우'
LEV_BUF_MIN, LEV_BUF_ATR = 0.002, 1.0     # rule-bot check: stop inside liquidation by max(0.2%, 1 ATR)
LEV_MAX_RUNS = 6                          # rule-bot check fixed point: at most 6 engine runs per window
CONC_TOP_POS, CONC_BIG_R = 0.10, 10.0     # R12: top 10% positions, positions >= 10R
JUDGE_CAPS = {"month_usd": 700.0, "month_stop_usd": 665.0, "day_usd": 45.0}   # placeholder caps, commit ca7a302
BURST_LEVELS = (10, 20, 30)
HOUR_MS = 3_600_000
DAY = H.DAY_MS
FIVE = H.FIVE
TASK_RUNS = 20_000                        # engine runs per worker task (control tasks)
ROLL_WIN_CHUNK = 100                      # rolling windows per worker task
EFF_EVERY = 30                            # rolling realised-risk columns: every 30th window (no overlap)

CHOICES = [
    "R1 touch / peak / days to a level: marked equity at every 5m close (engine path '5m' for the rows, the engine's "
    "5m peak for the controls); resolution '5m'.",
    "R1 machine A = H 7-8 with the W 7 scaling: open-risk cap 4% x r / 0.5% and margin budget B = equity / 6 x r / "
    "0.5% (both the tested values at r = 0.5%); machine B = PR_BRK_Q1, cap min(4r, 60%), n_max = PR_BDIV = "
    "floor(cap / r), PR_LEVMAX 125 (the coin's bracket maximum binds; fallback coins 20).",
    "R1 windows end with every open position closed at the last 5m close with slippage and taker (headline); the "
    "marked end is shown next to it.",
    "Controls on every board: the full-period draws of the pass (seed parts with r = 0.5%, W 6 / H 12), sliced per "
    "window (signal bar closing inside, fill bar inside); a basket's control = each member's draw with the same seed "
    "number in one wallet, src = pick number.",
    "Extra 2020 windows start on the first UTC day (rounded up) on which a universe coin has a known 장세 label on one "
    "of the row's timeframes; calendar months from the first month that starts on or after it.",
    "Rolling-share CI seed = seed_int(tag, 'goalboard', row, period, machine, r, 'boot'); pick-minus-control CI seed = "
    "seed_int(tag, 'goalboard', row, period, machine, r, windows, control, 'boot'); tag 'hunt-wide' / 'hunt'.",
    "Rolling realised-risk columns pool the positions of every 30th window (no overlap), so a position counts once.",
    "Size fixed on select: ctx['size_fixed_on_select'] over the select calendar-month cells of machines A and B.",
    "Leverage read: engine PR_FIXLEV = L (margin L% of equity at the previous close, notional L x margin; the engine "
    "lowers L to the bracket's maximum when L is not allowed at that notional), PR_NADDS 0 (the unit uses its whole "
    "margin budget, so no add would find margin), PR_CAP 100 (off), PR_MAXPOS floor(100 / L). The rule-bot check is "
    "applied here as a signal filter on the planned unit (before liquidity / wallet cuts) at the equity of the previous "
    "5m close, taken from the run's own 5m path and iterated to a fixed point (at most 6 runs; non-convergence counted).",
    "Continuous reads: r = 0.5% and 1% on the tested machine ($5,000, open positions marked at the period end), and "
    "the size fixed on select (fresh $1,000); 5m path.",
    "R15: gate-blocked (N) events = events on bars with a defined ATR14 and a fill bar that the row's gate blocks; "
    "per-close counts over closes with at least one event; per-hour counts over every hour of the period; quantiles "
    "of counts as observed values (inverted CDF); skips by reason are run totals (the engine counts skips, not per "
    "candidate); by month: candidates (fill month) and positions opened.",
    "R12 top month share = largest monthly ln M / sum of monthly ln M (defined when the sum is positive).",
    "R13: signal overlap = same coin and side within one bar of the longer timeframe; time overlap on 5m steps; "
    "monthly ln M correlation from the r = 0.5% continuous runs; tested picks and the v1 pick.",
]


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
    x = x[np.isfinite(x)]
    return _f(np.median(x)) if len(x) else None


def _qint(x, q):
    """Observed-value quantile (inverted CDF) of counts, as an int."""
    x = np.asarray(x)
    return int(np.quantile(x, q, method="inverted_cdf")) if len(x) else None


# ------------------------------------------------------------------ R1 windows
def calendar_windows(start_ms: int, end_ms: int, first_ms: int | None = None) -> list:
    """UTC calendar months [m, m+1) inside [start, end) that start on the 1st; with ``first_ms`` only months that
    start at or after it."""
    ms = H.month_starts(int(start_ms), int(end_ms))
    out = [(int(a), int(b)) for a, b in zip(ms[:-1], ms[1:])]
    lo = int(start_ms) if first_ms is None else max(int(start_ms), int(first_ms))
    return [w for w in out if w[0] >= lo and dt.datetime.fromtimestamp(w[0] / 1000, dt.timezone.utc).day == 1
            and H.month_starts(w[0], w[1])[-2] == w[0]]


def rolling_windows(start_ms: int, end_ms: int, days: int = ROLL_DAYS, first_ms: int | None = None) -> list:
    """[d, d + days) for every UTC start day d >= start (or >= ``first_ms`` rounded up to a day) with d + days <= end:
    975 in test, 1,066 in select."""
    d = int(start_ms) if first_ms is None else max(int(start_ms), -(-int(first_ms) // DAY) * DAY)
    out = []
    while d + days * DAY <= int(end_ms):
        out.append((d, d + days * DAY))
        d += DAY
    return out


# ------------------------------------------------------------------ R1 machines and cells
def goal_mode_caps(r: float) -> tuple:
    """PREREG_ALTPUMP 7, copied unchanged: total open risk <= min(4r, 60%), n_max = floor(cap / r)
    (5% -> 20%, 4; 10% -> 40%, 4; 20% -> 60%, 3)."""
    if r < GOAL_MODE_MIN_R - 1e-12:
        raise ValueError("goal-mode runs at r >= 5% only")
    cap = min(4.0 * r, GOAL_MODE_CAP_MAX)
    return cap, int(math.floor(cap / r + 1e-9))


def cell_overrides(machine: str, x) -> tuple:
    """(r, engine overrides) of a board cell: ("A", r), ("B", r) or ("L", leverage)."""
    if machine == "A":
        s = x / H.R_BASE
        return float(x), {"PR_CAP": H.RISK_CAP * s, "PR_BDIV": H.B_DIV / s}
    if machine == "B":
        cap, n = goal_mode_caps(x)
        return float(x), {"PR_BRK_Q1": 1, "PR_CAP": cap, "PR_MAXPOS": n, "PR_BDIV": float(n),
                          "PR_LEVMAX": GOAL_MODE_LEVMAX}
    if machine == "L":
        L = int(x)
        return H.R_BASE, {"PR_FIXLEV": L, "PR_NADDS": 0, "PR_CAP": 100.0, "PR_MAXPOS": 100 // L}
    raise ValueError(f"machine {machine!r}")


def machine_spec(machine: str, x) -> dict:
    """Readable description of a cell's machine (written next to every figure)."""
    r, ov = cell_overrides(machine, x)
    lab = {"A": "as tested (W 7 scaling of cap and B)", "B": "goal-mode machine, not the tested machine",
           "L": "rule-bot sizing (leverage read), not the tested machine"}[machine]
    return {"machine": machine, "r": r if machine != "L" else None, "L": int(x) if machine == "L" else None,
            "overrides": ov, "label": lab}


def board_cells() -> list:
    """(machine, r) cells of the R1 board: A at every r, B at r >= 5%."""
    return [("A", r) for r in GOAL_RS] + [("B", r) for r in GOAL_RS if r >= GOAL_MODE_MIN_R - 1e-12]


def lev_cells() -> list:
    return [("L", L) for L in LEV_LS]


def cell_key(machine: str, x) -> str:
    return f"L|{int(x)}x" if machine == "L" else f"{machine}|{x * 100:g}%"


def rolling_control_seeds(seconds_per_window: float) -> int:
    """Pre-declared: rolling-window controls use seeds 1-100, or 1-50 when one 30-day window run takes more than
    0.03 s."""
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


def bits_of(m_end: float, peak_m: float, bust: bool, levels=GOAL_LEVELS) -> int:
    """One window's indicators packed in an int: bit i = ends >= level i, bit len + i = touched level i, bit 2 len =
    bust."""
    b = 0
    n = len(levels)
    for i, x in enumerate(levels):
        if m_end >= x - 1e-12:
            b |= 1 << i
        if peak_m >= x - 1e-12:
            b |= 1 << (n + i)
    if bust:
        b |= 1 << (2 * n)
    return b


def cols_from_bits(bits, levels=GOAL_LEVELS) -> dict:
    """{column: float 0/1 array} of packed window indicators (last axis = windows)."""
    bits = np.asarray(bits, np.int64)
    n = len(levels)
    out = {}
    for i, x in enumerate(levels):
        out[f"end_ge_x{x:g}"] = ((bits >> i) & 1).astype(float)
        out[f"touch_x{x:g}"] = ((bits >> (n + i)) & 1).astype(float)
    out["bust"] = ((bits >> (2 * n)) & 1).astype(float)
    return out


def window_record(start_eq: float, end_closed: float, end_marked: float, peak: float, touch_idx, step_ms: int,
                  bust: bool, pnl=None, levels=GOAL_LEVELS, resolution: str = "5m") -> dict:
    """One fresh-account window. ``end_closed``: open positions closed at the last 5m close with slippage and taker
    (headline); ``end_marked``: marked instead. ``touch_idx``: first step (0-based, at its close) reaching each level,
    -1 when never; days to a touch = (index + 1) x step / 1 day. Give-back = (peak - end) / peak on the closed end.
    ``pnl``: the window's positions' net P&L (for the 80%-of-gain count)."""
    touch_idx = np.asarray(touch_idx, np.int64)
    peak = max(float(peak), float(start_eq), float(end_marked), float(end_closed))
    m = float(end_closed) / start_eq
    rec = {"m_end": m, "m_marked": float(end_marked) / start_eq, "peak_m": peak / start_eq, "bust": bool(bust),
           "resolution": resolution, "days_to": [((int(i) + 1) * step_ms / DAY) if i >= 0 else None
                                                 for i in touch_idx],
           "give_back": (peak - float(end_closed)) / peak if peak > 0 else None,
           "n80": n_positions_for_share(pnl, float(end_closed) - start_eq) if (pnl is not None and m >= 5) else None,
           "n_positions": None if pnl is None else int(len(pnl))}
    rec["bits"] = bits_of(rec["m_end"], rec["peak_m"], rec["bust"], levels)
    return rec


def window_from_path(eq, step_ms: int, start_eq: float = GOAL_START, end_closed: float | None = None, pnl=None,
                     bust_level: float = GOAL_BUST, levels=GOAL_LEVELS) -> dict:
    """window_record from a marked path alone (tests). Bust = any value < $100."""
    eq = np.asarray(eq, float)
    peak, first = touch_from_path(eq, start_eq, levels)
    end_m = float(eq[-1]) if len(eq) else float(start_eq)
    res = "5m" if step_ms == FIVE else "daily" if step_ms == DAY else f"{step_ms}ms"
    return window_record(start_eq, end_m if end_closed is None else end_closed, end_m, peak, first, step_ms,
                         bool(len(eq) and eq.min() < bust_level), pnl, levels, res)


def table_of(recs: list, levels=GOAL_LEVELS) -> dict:
    """Window records -> the column table ``board_cell`` reads (window order kept)."""
    i2, i5 = levels.index(2), levels.index(5)
    col = lambda k: np.asarray([np.nan if r[k] is None else r[k] for r in recs], float)  # noqa: E731
    return {"m_end": col("m_end"), "m_marked": col("m_marked"), "peak_m": col("peak_m"), "give_back": col("give_back"),
            "n80": col("n80"), "bits": np.asarray([r["bits"] for r in recs], np.int64),
            "days_x2": np.asarray([np.nan if r["days_to"][i2] is None else r["days_to"][i2] for r in recs], float),
            "days_x5": np.asarray([np.nan if r["days_to"][i5] is None else r["days_to"][i5] for r in recs], float),
            "resolution": sorted({r["resolution"] for r in recs})}


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


def goal_seed(tag: str, row_id: str, period: str, machine: str, x, *extra) -> int:
    """Seed parts (tag, 'goalboard', row id, period, machine, r or L, ..., 'boot'), joined as hunt.seed_int."""
    return H.seed_int(tag, "goalboard", row_id, period, machine, float(x), *extra, "boot")


# ------------------------------------------------------------------ R1 one board cell
def board_cell(tab, windows: str, seed: int | None = None, levels=GOAL_LEVELS, eff: dict | None = None) -> dict:
    """R1 columns of one (row, period, window set, machine, r) from a window table (``table_of``; a list of records
    is converted): shares of windows ending >= each level and touching each level, bust share, median / worst / best
    window multiple (closed end; marked shown too), mean ln multiple, median days to the first touch of x2 and x5,
    median give-back among windows that touched x5, median number of positions that made 80% of the gain among
    windows ending >= x5. Intervals: "calendar" -> exact Clopper-Pearson 95%; "rolling" -> moving-block bootstrap 90%
    (blocks of 30 start days, 2,000 resamples, ``seed``) and the overlapping-windows line."""
    if isinstance(tab, list):
        tab = table_of(tab, levels) if tab else {"m_end": np.zeros(0)}
    n = len(tab["m_end"])
    out = {"windows": windows, "n_windows": int(n), "resolution": tab.get("resolution", [])}
    if not n:
        return out
    m, mm = tab["m_end"], tab["m_marked"]
    cols = cols_from_bits(tab["bits"], levels)
    out["shares"] = {k: float(v.mean()) for k, v in cols.items()}
    if windows == "calendar":
        out["ci"] = {k: clopper_pearson(int(round(v.sum())), n) for k, v in cols.items()}
        out["ci_kind"] = "Clopper-Pearson 95%"
    else:
        idx = block_indices(n, MBB_BLOCK, MBB_N, seed if seed is not None else 0)
        out["ci"] = {k: boot_ci(v, idx, MBB_CONF) for k, v in cols.items()}
        out["ci_kind"] = "moving-block bootstrap 90% (30 start days, 2,000 resamples)"
        out["note"] = INDEPENDENT_LINE
    t5 = cols["touch_x5"] > 0
    e5 = cols["end_ge_x5"] > 0
    out.update({
        "median_m": _f(np.median(m)), "worst_m": _f(m.min()), "best_m": _f(m.max()),
        "mean_ln_m": _f(np.mean(np.log(np.maximum(m, 1e-12)))),
        "marked": {"median_m": _f(np.median(mm)), "worst_m": _f(mm.min()), "best_m": _f(mm.max()),
                   "end_ge": {f"x{x:g}": float((mm >= x - 1e-12).mean()) for x in levels}},
        "median_days_to_x2": _med(tab["days_x2"]), "median_days_to_x5": _med(tab["days_x5"]),
        "median_give_back_touch_x5": _med(tab["give_back"][t5]),
        "median_positions_80pct_end_ge_x5": _med(tab["n80"][e5]),
        "n_touch_x5": int(t5.sum()), "n_end_ge_x5": int(e5.sum()), "n_bust": int(cols["bust"].sum())})
    if eff is not None:
        out["effective_risk"] = eff
    return out


def control_columns(pick_bits, ctl_bits, windows: str, seed: int, levels=GOAL_LEVELS) -> dict:
    """Controls on the same board. ``pick_bits`` (windows,), ``ctl_bits`` (seeds, windows) in the pick's window
    order. Per share column: the pick's share, the pooled control share, the 5-95% range of the per-seed shares, and
    pick minus control (per window: pick indicator - mean over seeds) with a bootstrap 90% CI (calendar: blocks of one
    month; rolling: blocks of 30 start days)."""
    pick_bits = np.asarray(pick_bits, np.int64)
    ctl_bits = np.asarray(ctl_bits, np.int64)
    n = len(pick_bits)
    S = ctl_bits.shape[0] if ctl_bits.ndim == 2 else 0
    if not n or not S:
        return {"n_seeds": int(S), "n_windows": int(n)}
    if ctl_bits.shape[1] != n:
        raise ValueError("every control seed needs the pick's windows")
    pc, cc = cols_from_bits(pick_bits, levels), cols_from_bits(ctl_bits, levels)
    idx = block_indices(n, 1 if windows == "calendar" else MBB_BLOCK, MBB_N, seed)
    out = {"n_seeds": int(S), "n_windows": int(n), "columns": {}}
    for k, v in pc.items():
        mat = cc[k]
        per_seed = mat.mean(axis=1)
        d = v - mat.mean(axis=0)
        out["columns"][k] = {"pick": float(v.mean()), "control_pooled": float(mat.mean()),
                             "control_p5": _f(np.quantile(per_seed, 0.05)),
                             "control_p95": _f(np.quantile(per_seed, 0.95)),
                             "pick_minus_control": float(d.mean()), "ci90": boot_ci(d, idx, DIFF_CONF)}
    return out


def effective_risk(r: float, ratio, cut_bits, adds, lev, gross_max=None, brk_skips: int | None = None) -> dict:
    """Realised risk next to the nominal r over a cell's positions (``ratio`` = q1 x D0 / U per position): effective r
    = r x median(ratio), the p90 of the ratio, the share of first units cut (any, and by reason: liquidity, margin
    budget, free wallet), the share of positions filling add 1, 2 and 3, the median leverage, the max gross notional /
    equity when the engine exports it (else None), and machine B's adds skipped at the bracket tier."""
    ratio = np.asarray(ratio, float)
    n = len(ratio)
    if not n:
        return {"nominal_r": r, "n_positions": 0}
    cut = np.asarray(cut_bits, np.int64)
    adds = np.asarray(adds, np.int64)
    return {"nominal_r": r, "n_positions": int(n), "effective_r": _f(r * np.nanmedian(ratio)),
            "ratio_median": _f(np.nanmedian(ratio)), "ratio_p90": _f(np.nanquantile(ratio, 0.9)),
            "effective_r_p90": _f(r * np.nanquantile(ratio, 0.9)),
            "share_first_unit_cut": float((cut != 0).mean()),
            "share_first_unit_cut_by": {H.CUT_NAMES[i]: float(((cut >> i) & 1).mean())
                                        for i in range(len(H.CUT_NAMES))},
            "share_add_level": [float((adds >= a).mean()) for a in (1, 2, 3)],
            "median_leverage": _med(lev), "max_gross_notional_over_equity": _f(gross_max),
            "adds_skipped_bracket": brk_skips}


def headline_of(row_board: dict, spec: dict | None = None) -> dict | None:
    """The headline cell named before the test: per row, the share of test calendar months in which a fresh $1,000
    at goal-mode r = 5% touched $5,000, with its Clopper-Pearson interval, beside the (a) and (b) pooled shares (seeds
    1-1,000) and the bust share. ``row_board`` = {period: {windows: {cell key: {"cell", "controls"}}}}."""
    h = dict(HEADLINE)
    if spec:
        h.update({k: v for k, v in spec.items() if k in h})
    c = row_board.get(h["period"], {}).get(h["windows"], {}).get(cell_key(h["machine"], h["r"]))
    if not c or not c["cell"].get("n_windows"):
        return None
    col = h["column"]
    cell, ctl = c["cell"], c.get("controls") or {}
    cc = {x: (ctl.get(x) or {}).get("columns", {}).get(col, {}) for x in ("a", "b")}
    return {"what": "share of test calendar months where a fresh $1,000 at goal-mode r = 5% touched $5,000",
            "share": cell["shares"][col], "ci": cell["ci"][col], "bust_share": cell["shares"]["bust"],
            "n_windows": cell["n_windows"], "control_a": cc["a"].get("control_pooled"),
            "control_b": cc["b"].get("control_pooled"), "control_seeds": (ctl.get("a") or {}).get("n_seeds"),
            "scale": ALTPUMP_SCALE_LINE}


def size_fix_inputs(select_calendar: dict) -> list:
    """The interface's input list for ctx['size_fixed_on_select'] from {cell key: board_cell} of the select calendar
    months (machines A and B only)."""
    out = []
    for (machine, x) in board_cells():
        c = select_calendar.get(cell_key(machine, x))
        if c and c.get("n_windows"):
            out.append({"machine": machine, "r": float(x), "mean_ln_multiple": c["mean_ln_m"],
                        "bust_share": c["shares"]["bust"]})
    return out


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
    # longest stretch under water: vectorised over the running peak (a new peak = a value >= every earlier value)
    newpk = np.r_[True, eq[1:] >= pk[:-1]]
    starts = np.flatnonzero(newpk)                       # indices where the path is at a (weakly) new high
    gaps = np.diff(np.r_[starts, len(eq) - 1])           # steps from each high to the next high (or the end)
    span = np.r_[t[starts[1:]], t[-1]] - t[starts]
    last_open = len(eq) - 1 not in set(starts.tolist()) and starts[-1] < len(eq) - 1
    best = int(np.argmax(span)) if len(span) else 0
    lopen = bool(best == len(starts) - 1 and last_open)
    longest = float(span[best] / DAY) if len(span) and gaps[best] > 0 else 0.0
    lj = (starts[best + 1] if best + 1 < len(starts) else len(eq) - 1) if len(span) else 0
    out.update({"longest_under_water_days": longest, "under_water_from": _day(t[starts[best]]),
                "under_water_to": _day(t[lj]), "under_water_open": lopen})
    return out


def continuous_reads(start_ms: int, start_eq: float, eq, step_ms: int, lnM, end_eq: float,
                     max_dd_5m: float | None = None) -> dict:
    """The owners' continuous-account reads of one run: best 30-day run-up and its dates, geometric mean monthly
    return exp(mean ln M) - 1, whole-period multiple, max drawdown (the engine's 5m figure when given; dates from the
    path) and the longest time to recover."""
    t, v = path_points(start_ms, start_eq, eq, step_ms)
    lnM = np.asarray(lnM, float)
    out = {"resolution": "5m" if step_ms == FIVE else "daily" if step_ms == DAY else f"{step_ms}ms",
           "best_30d_runup": best_runup(t, v),
           "geo_mean_monthly_return": _f(np.expm1(lnM.mean())) if len(lnM) else None,
           "whole_period_multiple": float(end_eq) / start_eq}
    out.update(drawdown_recovery(t, v))
    out["max_dd_path"] = out.pop("max_dd", None)
    out["max_dd"] = _f(max_dd_5m) if max_dd_5m is not None else out["max_dd_path"]
    return out


# ------------------------------------------------------------------ owners' leverage read (rule-bot style sizing)
def _tier(notional: float, cap, n: int | None = None) -> int:
    """hunt.py's engine convention: the first tier whose cap is above the notional; -1 when above every tier."""
    cap = np.asarray(cap, float)[: (len(cap) if n is None else int(n))]
    hit = np.flatnonzero(notional < cap)
    return int(hit[0]) if len(hit) else -1


def liq_price(side: int, Q: float, cost: float, margin: float, mmr: float, cum: float) -> float:
    """Binance isolated one-way (hunt.py _set_liq): long (cost - M - cum) / (Q (1 - mmr)); short mirror."""
    if side > 0:
        return (cost - margin - cum) / (Q * (1.0 - mmr))
    return (cost + margin + cum) / (Q * (1.0 + mmr))


def effective_L(L: int, equity: float, br: dict, k: int) -> int:
    """The engine's fixed-leverage rule (R24): L, lowered to the bracket's maximum when L is not allowed at the
    notional L x L% x equity (repeated); 0 when the notional is above every tier."""
    n = int(br["n"][k])
    for _ in range(16):
        b = _tier((L / 100.0) * equity * L, br["cap"][k], n)
        if b < 0:
            return 0
        if L <= int(br["lev"][k][b]):
            return int(L)
        L = int(br["lev"][k][b])
    return int(L)


def rulebot_unit(L: int, equity: float, P0: float, side: int, D0: float, atr: float, br: dict, k: int,
                 slip: float = H.COSTS["base"][1]) -> dict:
    """The planned first unit of the leverage read and the rule-bot check: leverage = effective_L (the bracket's
    maximum when L is not allowed), margin = L% of equity, notional = L x margin (L = 20 -> 4x equity, 30 -> 9x,
    40 -> 16x), isolated; ok when the first stop P0 -/+ D0 lies inside the liquidation price by at least
    max(0.2% of the fill, 1 ATR). Reasons: 'bracket' (no tier holds the notional: the engine skips it as
    no_leverage), 'liq_buffer'. Cuts after the check (liquidity, free wallet) are the engine's."""
    Le = effective_L(L, equity, br, k)
    out = {"L": int(L), "L_eff": Le, "ok": False, "reason": None}
    if Le <= 0:
        out["reason"] = "bracket"
        return out
    fill = P0 * (1.0 + side * slip)
    margin = Le / 100.0 * equity
    q = margin * Le / fill
    cost = q * fill
    b = _tier(cost, br["cap"][k], int(br["n"][k]))
    b = int(br["n"][k]) - 1 if b < 0 else b
    liq = liq_price(side, q, cost, margin, float(br["mmr"][k][b]), float(br["cum"][k][b]))
    stop = P0 - side * D0
    buf = max(LEV_BUF_MIN * fill, LEV_BUF_ATR * atr)
    out.update({"q": q, "notional": cost, "margin": margin, "liq": liq, "stop": stop, "buffer": buf, "tier": b,
                "wallet_risk_per_stop": q * D0 / equity})
    if (stop - liq) * side < buf:
        out["reason"] = "liq_buffer"
        return out
    out["ok"] = True
    return out


def lev_check(L: int, equity, P0, side, D0, atr, k, br: dict) -> np.ndarray:
    """rulebot_unit(...)['ok'] or a bracket skip (left to the engine) for every signal (arrays)."""
    n = len(P0)
    ok = np.ones(n, bool)
    for i in range(n):
        if not (equity[i] > 0 and P0[i] > 0 and D0[i] > 0):
            continue                                       # the engine skips it ('bad_price')
        u = rulebot_unit(L, float(equity[i]), float(P0[i]), int(side[i]), float(D0[i]), float(atr[i]), br, int(k[i]))
        ok[i] = u["ok"] or u["reason"] == "bracket"
    return ok


def stop_loss_frac(L: int, d0_over_p0, slip: float = H.COSTS["base"][1], taker: float = H.COSTS["base"][0]) -> dict:
    """Wallet share lost at the first stop for a rule-bot unit at L (no bracket lowering): price only
    (L x L% x D0 / P0 / (1 + slip)) and with costs (fill and exit slippage, taker both ways), long."""
    d = np.asarray(d0_over_p0, float)
    q_over = (L * L / 100.0) / (1.0 + slip)              # q x P0 / equity
    fill, exitp = 1.0 + slip, (1.0 - d) * (1.0 - slip)   # in units of P0 (a short loses d x slip more)
    return {"price_only": q_over * d, "with_costs": q_over * (fill - exitp) + taker * q_over * (fill + exitp)}


def wallet_risk_table(d0_over_p0, Ls=LEV_LS) -> dict:
    """L -> the median (p10, p90) wallet risk per stop over the given D0 / P0 values (a row's gated signals), price
    only and with costs, and the share of signals whose stop would cost the whole wallet or more."""
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
    x = np.asarray(x)
    if not len(x):
        return {"mean": None, "p50": None, "p95": None, "max": None}
    return {"mean": float(x.mean()), "p50": _qint(x, 0.5), "p95": _qint(x, 0.95), "max": int(x.max())}


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
    """R15 for one event set (one row, or the union the paper bot would feed the judge): events per UTC day with
    gated (G) and gate-blocked (N) events counted separately (mean, p50, p95, max day; days with no event count as
    0); events at a single signal close (max, p99, over closes with at least one event) and the share of those closes
    with more than 10, 20 and 30 events; events per UTC hour (p99, max; every hour of the period); counts by month and
    by year."""
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
                                    "p99": _qint(per_close, 0.99),
                                    **{f"share_closes_gt_{b}": float((per_close > b).mean()) if len(per_close)
                                       else None for b in BURST_LEVELS},
                                    **{f"closes_gt_{b}": int((per_close > b).sum()) for b in BURST_LEVELS}}
    hours = np.bincount((c - start_ms) // HOUR_MS, minlength=n_hours)[:n_hours] if n_hours else np.zeros(0, int)
    out["per_hour_all"] = {"p99": _qint(hours, 0.99), "max": int(hours.max()) if len(hours) else 0}
    for name, m in (("G", g), ("N", ~g)):
        bm, by = _month_year_counts(c[m], start_ms, end_ms)
        out[f"by_month_{name}"], out[f"by_year_{name}"] = bm, by
    return out


def union_events(event_sets: list) -> dict:
    """Union of several rows' events (dicts with coin, side, close_ms, gated). ``total`` keeps every row's event (one
    judge call per pick and event); ``distinct`` merges the same (coin, side, close) across picks, gated when any
    pick's event there is gated."""
    z = np.zeros(0, np.int64)
    if not event_sets:
        return {"total": {"close_ms": z, "gated": z.astype(bool)},
                "distinct": {"close_ms": z, "coin": z, "side": z, "gated": z.astype(bool)}}
    cat = {k: np.concatenate([np.asarray(e[k]) for e in event_sets]) for k in ("coin", "side", "close_ms", "gated")}
    key = np.stack([cat["close_ms"].astype(np.int64), cat["coin"].astype(np.int64), cat["side"].astype(np.int64)], 1)
    if not len(key):
        return union_events([])
    uk, inv = np.unique(key, axis=0, return_inverse=True)
    inv = np.asarray(inv).reshape(-1)
    g = np.zeros(len(uk), bool)
    np.logical_or.at(g, inv, cat["gated"].astype(bool))
    return {"total": {"close_ms": cat["close_ms"].astype(np.int64), "gated": cat["gated"].astype(bool)},
            "distinct": {"close_ms": uk[:, 0], "coin": uk[:, 1], "side": uk[:, 2], "gated": g}}


def taken_by_month(cand_fill_ms, taken_ms, skipped: dict, start_ms: int, end_ms: int) -> dict:
    """Candidates (by fill month) and positions opened (by entry month), the dropped difference by month and year,
    and the run's skips by reason (totals)."""
    cm, cy = _month_year_counts(cand_fill_ms, start_ms, end_ms)
    tm, ty = _month_year_counts(taken_ms, start_ms, end_ms)
    return {"candidates_by_month": cm, "taken_by_month": tm,
            "dropped_by_month": {k: cm[k] - tm.get(k, 0) for k in cm},
            "candidates_by_year": cy, "taken_by_year": ty, "dropped_by_year": {k: cy[k] - ty.get(k, 0) for k in cy},
            "skipped_by_reason_total": {k: int(v) for k, v in (skipped or {}).items()},
            "candidates": int(sum(cm.values())), "taken": int(sum(tm.values()))}


def judge_budget(rate: dict, usd_per_call: float | None, which: str = "G", caps: dict = JUDGE_CAPS) -> dict:
    """Monthly and daily call counts x a per-call cost (a parameter), against the owners' placeholder caps ($700 a
    month, all calls stop at 95% = $665; $45 a day; commit ca7a302). ``which``: 'G' (gated events) or 'all'."""
    if which == "all":
        bm = {k: rate["by_month_G"][k] + rate["by_month_N"][k] for k in rate["by_month_G"]}
    else:
        bm = rate[f"by_month_{which}"]
    per_day = rate[f"per_day_{which}"]
    months = np.asarray(list(bm.values()), np.int64)
    out = {"which": which, "calls_per_month": _stats(months), "calls_per_day": per_day,
           "usd_per_call": usd_per_call, "caps": caps}
    if usd_per_call is None or not len(months):
        return out
    out.update({"usd_per_month_mean": _f(months.mean() * usd_per_call),
                "usd_per_month_max": _f(months.max() * usd_per_call),
                "usd_per_day_p95": _f(per_day["p95"] * usd_per_call) if per_day["p95"] is not None else None,
                "usd_per_day_max": _f(per_day["max"] * usd_per_call) if per_day["max"] is not None else None,
                "months_over_stop": int((months * usd_per_call > caps["month_stop_usd"]).sum()),
                "p95_day_over_cap": bool(per_day["p95"] is not None and
                                         per_day["p95"] * usd_per_call > caps["day_usd"])})
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
        with np.errstate(divide="ignore", invalid="ignore"):
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
    """Share of a's signals with a b signal on the same coin and side whose close lies within ``window_ms``."""
    ca, cb = np.asarray(a["close_ms"], np.int64), np.asarray(b["close_ms"], np.int64)
    if not len(ca):
        return None
    ka, kb = np.asarray(a["coin"]), np.asarray(b["coin"])
    sa, sb = np.asarray(a["side"]), np.asarray(b["side"])
    hit = 0
    for k in np.unique(ka):
        for s in (1, -1):
            ma = (ka == k) & (sa == s)
            tb = np.sort(cb[(kb == k) & (sb == s)])
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
    """Per 5m step of a run (0..T-1): at least one position open (entered at its fill step tin, closed at tout; a
    negative tout counts through the last step)."""
    mark = np.zeros(T + 1, np.int64)
    for a, b in zip(np.asarray(tin, np.int64), np.asarray(tout, np.int64)):
        b = T - 1 if b < 0 else b
        mark[min(max(a, 0), T)] += 1
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
    """R13 basics: ``rows`` = {id: {"events": {coin, side, close_ms}, "tf_ms": int, "iv": (tin, tout), "lnM": [..]}}.
    Per ordered pair: signal overlap (within one bar of the longer timeframe) and time-in-market overlap; per
    unordered pair: correlation of monthly ln M. Keys 'a|b'."""
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


# ------------------------------------------------------------------ D11
PUBLIC_KEYS = {"id", "row", "kind", "label", "role", "candidate", "machine", "windows", "period", "n_windows",
               "n_positions", "n_seeds", "resolution", "note", "L", "family", "name", "strategy", "tf", "gate",
               "pick_no", "batch", "members", "events", "gated", "gate_blocked", "days", "is_ds", "what", "lineup",
               "passed", "size_label"}
COUNT_DICTS = {"skipped", "skipped_entries", "signal_counts", "skipped_by_reason_total"}   # {name: int} only


def _plain(v) -> bool:
    if isinstance(v, (list, tuple)):
        return all(_plain(x) for x in v)
    return v is None or isinstance(v, (str, bool, int, np.integer)) and not isinstance(v, float)


def labels_counts(obj):
    """D11 public copy of a row that contains a DeepSeek pick: only ``PUBLIC_KEYS`` with label / count values (no
    float anywhere) and the integer entries of ``COUNT_DICTS``, recursively; every money figure, shares included,
    stays private."""
    if not isinstance(obj, dict):
        return None
    out = {}
    for k, v in obj.items():
        if k in PUBLIC_KEYS and _plain(v):
            out[k] = v
        elif k in COUNT_DICTS and isinstance(v, dict):
            out[k] = {a: int(b) for a, b in v.items() if isinstance(b, (int, np.integer)) and not isinstance(b, bool)}
        elif isinstance(v, dict):
            r = labels_counts(v)
            if r:
                out[k] = r
    return out


def ints_only(obj):
    """D11 public copy of a counts-only read (R15) of a row that contains a DeepSeek pick: every float dropped."""
    if isinstance(obj, dict):
        return {k: ints_only(v) for k, v in obj.items() if not isinstance(v, (float, np.floating))}
    if isinstance(obj, (list, tuple)):
        return [ints_only(v) for v in obj if not isinstance(v, (float, np.floating))]
    return obj


DS_NOTE = "DeepSeek row: figures in the private file (D11)"


def split_ds(section: dict, ds_of: dict, redact=labels_counts) -> tuple:
    """(public, private) of {row id: read}: DeepSeek rows go to private whole and to public redacted."""
    public, private = {}, {}
    for rid, v in section.items():
        if ds_of.get(rid):
            red = redact(v) or {}
            red["note"] = DS_NOTE
            public[rid], private[rid] = red, v
        else:
            public[rid] = v
    return public, private


# ------------------------------------------------------------------ engine glue (reads interface api 1)
_S: dict = {}          # state shared with forked workers: ctx, live module, parts, infos, windows, brackets


def _live(ctx: dict):
    """The hunt module that built ctx (``__main__`` when hunt.py runs as a script): its caches hold the data."""
    mod = ctx.get("hunt_module")
    if mod is None:
        mod = sys.modules.get(getattr(ctx.get("market"), "__module__", "") or "")
    return mod if mod is not None and hasattr(mod, "series") else H


def sig_info(live, syms: list, sig: dict) -> dict:
    """Per signal of a signal dict (tf k j side): signal close, fill time and reference price P0 (the open of the
    first 5m bar after the close), ATR14 of the signal bar and D0 = D0_MULT x ATR14."""
    k = np.asarray(sig["k"], np.int64)
    j = np.asarray(sig["j"], np.int64)
    n = len(k)
    close, fill = np.zeros(n, np.int64), np.full(n, -1, np.int64)
    P0, atr = np.full(n, np.nan), np.full(n, np.nan)
    for kk in np.unique(k):
        sel = k == kk
        sym = syms[int(kk)]
        ser = live.series(sym, sig["tf"])
        c = live._COINS[sym]
        jj = j[sel]
        fi = np.asarray(ser.bars.first5, np.int64)[jj]
        ok = fi < len(c.ts)
        fic = np.minimum(fi, max(len(c.ts) - 1, 0))
        close[sel] = np.asarray(ser.bars.close_ms, np.int64)[jj]
        fill[sel] = np.where(ok, np.asarray(c.ts, np.int64)[fic], -1)
        P0[sel] = np.where(ok, np.asarray(c.o, np.float64)[fic], np.nan)
        atr[sel] = np.asarray(ser.atr, np.float64)[jj]
    return {"close": close, "fill": fill, "P0": P0, "atr": atr, "d0": live.D0_MULT[sig["tf"]] * atr,
            "k": k, "side": np.asarray(sig["side"], np.int64)}


def _subset(sig: dict, m: np.ndarray) -> dict:
    return {"tf": sig["tf"], "k": np.asarray(sig["k"])[m], "j": np.asarray(sig["j"])[m],
            "side": np.asarray(sig["side"])[m]}


def _in_window(info: dict, a: int, b: int) -> np.ndarray:
    """Signals the window keeps: signal bar closing inside it and fill bar inside it (the run applies the same)."""
    return (info["close"] >= a) & (info["close"] < b) & (info["fill"] >= a) & (info["fill"] < b)


def _window_parts(parts: list, infos: list, a: int, b: int) -> tuple:
    masks = [_in_window(inf, a, b) for inf in infos]
    return [(_subset(sig, m), src) for (sig, src), m in zip(parts, masks)], masks


def _eprev(eqp, fill_ms, a: int, start: float) -> np.ndarray:
    """Marked equity at the 5m close before each fill (the engine's sizing equity); the start wallet at step 0."""
    t = (np.asarray(fill_ms, np.int64) - a) // FIVE
    out = np.full(len(t), float(start))
    eqp = np.asarray(eqp, float)
    ok = (t >= 1) & (t - 1 < len(eqp))
    out[ok] = eqp[t[ok] - 1]
    return out


def run_lev(run, parts: list, infos: list, a: int, b: int, L: int, br: dict, start: float = GOAL_START,
            path: str = "5m", **kw) -> dict:
    """One fresh-account window (or continuous run) at rule-bot leverage L with the rule-bot check as a signal filter:
    the planned unit is checked at the equity of the previous 5m close from the run's own 5m path, rerun until the
    kept set no longer changes (at most LEV_MAX_RUNS runs). Adds 'lev_buffer_skipped', 'lev_runs', 'lev_converged'."""
    r, ov = cell_overrides("L", L)
    wparts, masks = _window_parts(parts, infos, a, b)
    winfo = [{k: v[m] for k, v in inf.items()} for inf, m in zip(infos, masks)]
    keep = [lev_check(L, np.full(len(w["P0"]), start), w["P0"], w["side"], w["d0"], w["atr"], w["k"], br)
            for w in winfo]
    conv, res, runs = False, None, 0
    for runs in range(1, LEV_MAX_RUNS + 1):
        sub = [(_subset(sig, kp), src) for (sig, src), kp in zip(wparts, keep)]
        res = run(sub, a, b, r=r, start_wallet=start, overrides=ov, path="5m", **kw)
        E = [_eprev(res["equity_path"], w["fill"], a, start) for w in winfo]
        nk = [lev_check(L, e, w["P0"], w["side"], w["d0"], w["atr"], w["k"], br) for e, w in zip(E, winfo)]
        if all(np.array_equal(x, y) for x, y in zip(nk, keep)):
            conv = True
            break
        keep = nk
    res["lev_buffer_skipped"] = int(sum(int((~kp).sum()) for kp in keep))
    res["lev_runs"], res["lev_converged"] = runs, conv
    if path != "5m":
        res["equity_path"] = None
    return res


def _free_window(a: int, b: int) -> None:
    """Drop the window's cached market objects from the live module (memory only; decisions never read a cache that
    is not rebuilt identically)."""
    live = _S.get("live")
    if live is None:
        return
    tag = f":{a}:{b}:"
    for name in ("_MARKETS", "_BANKS", "_SIGS", "_POOLS"):
        d = getattr(live, name, None)
        if not isinstance(d, dict):
            continue
        for key in [x for x in d if (isinstance(x, tuple) and len(x) >= 2 and ((a in x and b in x) or
                    (isinstance(x[0], str) and tag in x[0])))]:
            d.pop(key, None)


def _run_cell(cell: tuple, parts: list, infos: list, a: int, b: int, path: str) -> dict:
    ctx = _S["ctx"]
    machine, x = cell
    if machine == "L":
        return run_lev(ctx["run"], parts, infos, a, b, int(x), _S["br"], GOAL_START, path=path, close_end=True)
    r, ov = cell_overrides(machine, x)
    wparts, _ = _window_parts(parts, infos, a, b)
    return ctx["run"](wparts, a, b, r=r, start_wallet=GOAL_START, overrides=ov, path=path, close_end=True)


def _pick_rec(res: dict, keep_pos: bool) -> dict:
    """Compact record of one row window (picks): the window_record fields, the bits, counts and (when ``keep_pos``)
    the per-position arrays of the realised-risk columns."""
    tr = res.get("trades") or {}
    pnl = np.asarray(tr.get("pnl", []), float)
    eqp = res.get("equity_path")
    _, first = touch_from_path(eqp if eqp is not None else [], GOAL_START)
    rec = window_record(GOAL_START, res["end"], res["end_marked"], res["peak"], first, FIVE, res["bust"], pnl)
    rec.pop("days_to")
    i2, i5 = GOAL_LEVELS.index(2), GOAL_LEVELS.index(5)
    rec["days_x2"] = (int(first[i2]) + 1) * FIVE / DAY if first[i2] >= 0 else None
    rec["days_x5"] = (int(first[i5]) + 1) * FIVE / DAY if first[i5] >= 0 else None
    reason = np.asarray(tr.get("reason_name", []))
    rec["liquidations"] = int((reason == "liquidation").sum()) if len(reason) else 0
    rec["skipped"] = {k: int(v) for k, v in (res.get("skipped") or {}).items()}
    rec["adds_skipped_bracket"] = int((res.get("adds_skipped") or {}).get("bracket", 0))
    if "lev_buffer_skipped" in res:
        rec["lev"] = {"buffer_skipped": res["lev_buffer_skipped"], "runs": res["lev_runs"],
                      "converged": res["lev_converged"]}
    if keep_pos and len(pnl):
        U = np.asarray(tr["U"], float)
        q1, d0 = np.asarray(tr["q1"], float), np.asarray(tr["D0"], float)
        eq = np.asarray(tr["eq_at_entry"], float)
        with np.errstate(divide="ignore", invalid="ignore"):
            rec["pos"] = {"ratio": (q1 * d0 / U).astype(np.float32), "cut": np.asarray(tr["cut"], np.int8),
                          "adds": np.asarray(tr["adds"], np.int8), "lev": np.asarray(tr["lev"], np.float32),
                          "risk_eq": (q1 * d0 / eq).astype(np.float32)}
    return rec


def _pick_task(task) -> tuple:
    """Worker: one row, period, window set and chunk of windows; every cell (A, B, L) once per window (path 5m)."""
    ri, period, kind, wis = task
    parts, infos = _S["parts"][(ri, period)], _S["infos"][(ri, period)]
    wins = _S["win"][(ri, period, kind)]
    out = {}
    for wi in wis:
        a, b = wins[wi]
        keep_pos = kind == "calendar" or wi % EFF_EVERY == 0
        for cell in _S["cells"]:
            out[(wi, cell)] = _pick_rec(_run_cell(cell, parts, infos, a, b, "5m"), keep_pos)
        _free_window(a, b)
    return ri, period, kind, out


def _ctl_task(task) -> tuple:
    """Worker: one row, period, window set, control, seed chunk, window chunk and cell group; packed window bits."""
    ri, period, kind, ctl, seeds, wis, group = task
    ctx = _S["ctx"]
    row = ctx["rows"][ri]
    cells = _S["cells_ab"] if group == "AB" else _S["cells_l"]
    syms = _S["syms"]
    parts_s, infos_s = {}, {}
    for s in seeds:
        ps = [(ctx["control_signals"](m, ctl, period, H.R_BASE, s), src) for m, src in zip(row["members"], row["src"])]
        parts_s[s] = ps
        infos_s[s] = [sig_info(_S["live"], syms, sig) for sig, _ in ps]
    out = {cell: np.zeros((len(seeds), len(wis)), np.int32) for cell in cells}
    wins = _S["win"][(ri, period, kind)]
    for wj, wi in enumerate(wis):
        a, b = wins[wi]
        for si, s in enumerate(seeds):
            for cell in cells:
                res = _run_cell(cell, parts_s[s], infos_s[s], a, b, "day")
                out[cell][si, wj] = bits_of(res["end"] / GOAL_START, res["peak"] / GOAL_START, res["bust"])
        _free_window(a, b)
    return ri, period, kind, ctl, tuple(seeds), tuple(wis), out


def _cont_task(task) -> tuple:
    """Worker: one continuous account of a row over a whole period (5m path)."""
    ri, period, which = task
    ctx = _S["ctx"]
    a, b = _S["periods"][period]
    parts = _S["parts"][(ri, period)]
    if which[0] == "r":
        start, r, ov = H.START_WALLET, which[1], None
    else:
        start = GOAL_START
        r, ov = cell_overrides(which[1], which[2])
    res = ctx["run"](parts, a, b, r=r, start_wallet=start, overrides=ov, path="5m", detail=True)
    m = res["metrics"]
    tr = res.get("trades") or {}
    out = {"continuous": continuous_reads(a, start, res["equity_path"], FIVE, m["lnM"], res["end"], m.get("max_dd")),
           "bust": bool(res["bust"]), "n_positions": int(m.get("n_positions", len(tr.get("pnl", []))))}
    if which == ("r", H.R_BASE):
        out["r12"] = concentration(tr.get("pnl", []), tr.get("U", []), m["lnM"])
        out["r12"]["top10pct_share_of_profit_engine"] = m.get("top10_share_of_profit")
        out["iv"] = (np.asarray(tr.get("t_in", []), np.int64), np.asarray(tr.get("t_out", []), np.int64))
        out["lnM"] = list(m["lnM"])
        out["T"] = int((b - a) // FIVE)
        out["taken_ms"] = a + np.asarray(tr.get("t_in", []), np.int64) * FIVE
        out["skipped"] = {k: int(v) for k, v in (res.get("skipped") or {}).items()}
    return ri, period, which, out


# ------------------------------------------------------------------ planning
def first_label_ms(live, syms: list, tfs, a: int, b: int) -> int | None:
    """The first signal-bar close in [a, b) at which some coin has a known 장세 label on one of ``tfs``."""
    best = None
    for tf in tfs:
        for s in syms:
            if s not in live._COINS or not len(live._COINS[s].ts):
                continue
            ser = live.series(s, tf)
            cm = np.asarray(ser.bars.close_ms, np.int64)
            ok = np.flatnonzero((np.asarray(ser.code) != live.UNKNOWN) & (cm >= a) & (cm < b))
            if len(ok):
                best = int(cm[ok[0]]) if best is None else min(best, int(cm[ok[0]]))
    return best


def _plan_windows(ctx: dict, live) -> dict:
    win = {}
    for ri, row in enumerate(ctx["rows"]):
        tfs = sorted({m["tf"] for m in row["members"]})
        for period in READ_PERIODS:
            a, b = _S["periods"][period]
            first = None
            if period == "extra":
                first = first_label_ms(live, _S["syms"], tfs, a, b)
                if first is None:
                    win[(ri, period, "calendar")], win[(ri, period, "rolling")] = [], []
                    continue
            win[(ri, period, "calendar")] = calendar_windows(a, b, first)
            win[(ri, period, "rolling")] = rolling_windows(a, b, first_ms=first)
    return win


def _chunks(seq, n: int) -> list:
    seq = list(seq)
    return [seq[i:i + n] for i in range(0, len(seq), max(1, n))]


def _measure_window_seconds(ctx: dict) -> float:
    """Seconds per 30-day control window run (timing only; the results are discarded): control (a) seed 1 of the
    first row, first rolling test window, machine A at r = 0.5%, median of 5 runs after one warm-up."""
    rows = ctx["rows"]
    if not rows:
        return 0.0
    row = rows[0]
    a, b = _S["periods"]["test"]
    a, b = a, a + ROLL_DAYS * DAY
    parts = [(ctx["control_signals"](m, "a", "test", H.R_BASE, 1), src) for m, src in zip(row["members"], row["src"])]
    infos = [sig_info(_S["live"], _S["syms"], sig) for sig, _ in parts]
    ts = []
    for i in range(6):
        t0 = time.perf_counter()
        _run_cell(("A", H.R_BASE), parts, infos, a, b, "day")
        if i:
            ts.append(time.perf_counter() - t0)
    _free_window(a, b)
    return float(np.median(ts))


def _row_id(row: dict) -> str:
    return row["row"]


def _ds_rows(ctx: dict) -> dict:
    return {_row_id(r): bool(r.get("is_ds") or any(ctx["is_ds"](m) for m in r["members"])) for r in ctx["rows"]}


def _row_meta(row: dict) -> dict:
    return {"row": row["row"], "kind": row["kind"], "label": row["label"], "candidate": bool(row.get("candidate")),
            "members": [m["id"] for m in row["members"]]}


# ------------------------------------------------------------------ the entry point
def run(ctx: dict) -> None:
    """Fill ctx['out'] (public) and ctx['private'] (D11 and money of DeepSeek rows). Writes no file."""
    t_all = time.time()
    live = _live(ctx)
    log = ctx.get("log") or (lambda m: print(m, flush=True))
    tag = H.SEED_TAG["wide" if ctx["study"] == "wide" else "v1"]
    rows = ctx["rows"]
    syms = list(ctx["syms"])
    _S.clear()
    _S.update(ctx=ctx, live=live, syms=syms, cells_ab=board_cells(), cells_l=lev_cells(),
              periods={p: (int(ctx["periods"][p][0]), int(ctx["periods"][p][1])) for p in READ_PERIODS})
    _S["cells"] = _S["cells_ab"] + _S["cells_l"]
    pmap, procs = ctx["pmap"], int(ctx.get("procs") or 1)
    ds_of = _ds_rows(ctx)
    mks = {p: ctx["market"](*_S["periods"][p]) for p in READ_PERIODS}
    _S["br"] = mks["test"].br
    parts, infos = {}, {}
    for ri, row in enumerate(rows):
        for p in READ_PERIODS:
            parts[(ri, p)] = [(ctx["signals"](m, mks[p]), src) for m, src in zip(row["members"], row["src"])]
            infos[(ri, p)] = [sig_info(live, syms, sig) for sig, _ in parts[(ri, p)]]
    _S.update(parts=parts, infos=infos)
    _S["win"] = _plan_windows(ctx, live)
    sec = ctx.get("window_seconds")
    measured = sec is None
    if sec is None:
        sec = _measure_window_seconds(ctx)
    n_roll = rolling_control_seeds(sec)
    n_lev_roll = min(LEV_CTL_SEEDS, n_roll)
    log(f"reads_a: {len(rows)} rows; one 30-day window run {sec:.4f}s -> rolling control seeds 1-{n_roll}")
    reads_line = (ctx.get("reads_pin") or {}).get("listed_before_test_json")

    # ---------------------------------------------------------------- R1 board and the leverage read: rows
    ptasks = []
    for (ri, p, kind), wins in _S["win"].items():
        for ch in _chunks(range(len(wins)), len(wins) if kind == "calendar" else ROLL_WIN_CHUNK):
            ptasks.append((ri, p, kind, tuple(ch)))
    precs: dict = {}
    for ri, p, kind, out in pmap(_pick_task, ptasks, procs, "reads_a R1 rows"):
        precs.setdefault((ri, p, kind), {}).update(out)
    # ---------------------------------------------------------------- controls
    ctasks = []
    for (ri, p, kind), wins in _S["win"].items():
        if not wins:
            continue
        wch = _chunks(range(len(wins)), len(wins) if kind == "calendar" else ROLL_WIN_CHUNK)
        for group, cells, n_s in (("AB", _S["cells_ab"], CAL_CTL_SEEDS if kind == "calendar" else n_roll),
                                  ("L", _S["cells_l"], LEV_CTL_SEEDS if kind == "calendar" else n_lev_roll)):
            for w in wch:
                per = max(1, TASK_RUNS // max(1, len(w) * len(cells) * (2 if group == "L" else 1)))
                for ctl in ("a", "b"):
                    for sch in _chunks(range(1, n_s + 1), per):
                        ctasks.append((ri, p, kind, ctl, tuple(sch), tuple(w), group))
    cbits: dict = {}
    for ri, p, kind, ctl, seeds, wis, out in pmap(_ctl_task, ctasks, procs, "reads_a R1 controls"):
        for cell, mat in out.items():
            d = cbits.setdefault((ri, p, kind, ctl, cell), {})
            for si, s in enumerate(seeds):
                row_ = d.setdefault(s, {})
                for wj, wi in enumerate(wis):
                    row_[wi] = int(mat[si, wj])
    log(f"reads_a: board runs done ({time.time() - t_all:.0f}s)")

    # ---------------------------------------------------------------- R1 / leverage tables per row
    board, lever = {}, {}
    for ri, row in enumerate(rows):
        rid = _row_id(row)
        rb, lb = {}, {}
        for p in READ_PERIODS:
            for kind in ("calendar", "rolling"):
                wins = _S["win"][(ri, p, kind)]
                n = len(wins)
                recs = precs.get((ri, p, kind), {})
                for cell in _S["cells"]:
                    machine, x = cell
                    ck = cell_key(machine, x)
                    rl = [recs[(wi, cell)] for wi in range(n)]
                    tab = _tab_compact(rl)
                    pos = [rr["pos"] for rr in rl if "pos" in rr]
                    cat = (lambda k: np.concatenate([q[k] for q in pos]) if pos else np.zeros(0))  # noqa: E731
                    eff = effective_risk(cell_overrides(machine, x)[0] if machine != "L" else None, cat("ratio"),
                                         cat("cut"), cat("adds"), cat("lev"),
                                         brk_skips=int(sum(rr["adds_skipped_bracket"] for rr in rl)))
                    seed = goal_seed(tag, rid, p, machine, x)
                    c = board_cell(tab, kind, seed, eff=eff)
                    c["machine"] = machine_spec(machine, x)
                    c["skipped"] = _sum_counts([rr["skipped"] for rr in rl])
                    c["liquidations"] = int(sum(rr["liquidations"] for rr in rl))
                    pick_bits = tab["bits"]
                    ctl = {}
                    for cn in ("a", "b"):
                        d = cbits.get((ri, p, kind, cn, cell), {})
                        if d and n:
                            mat = np.asarray([[d[s][wi] for wi in range(n)] for s in sorted(d)], np.int64)
                            ctl[cn] = control_columns(pick_bits, mat, kind,
                                                      goal_seed(tag, rid, p, machine, x, kind, cn))
                    entry = {"cell": c, "controls": ctl}
                    if machine == "L":
                        rk = np.concatenate([q["risk_eq"] for q in pos]) if pos else np.zeros(0)
                        lv = cat("lev")
                        entry["leverage"] = {
                            "L": int(x), "liquidations": c["liquidations"],
                            "rule_bot_check_skipped": int(sum(rr.get("lev", {}).get("buffer_skipped", 0)
                                                              for rr in rl)),
                            "engine_skipped": c["skipped"],
                            "fixed_point_not_converged": int(sum(1 for rr in rl
                                                                 if not rr.get("lev", {}).get("converged", True))),
                            "median_wallet_risk_per_stop": _med(rk), "median_leverage_used": _med(lv),
                            "share_leverage_lowered_by_bracket": _f((lv < int(x)).mean()) if len(lv) else None}
                        lb.setdefault(p, {}).setdefault(kind, {})[ck] = entry
                    else:
                        rb.setdefault(p, {}).setdefault(kind, {})[ck] = entry
        # labels: the size fixed on select, forward-only evidence, period labels
        fixed = None
        sel_cal = {k: v["cell"] for k, v in rb.get("select", {}).get("calendar", {}).items()}
        inputs = size_fix_inputs(sel_cal)
        if inputs:
            ch = ctx["size_fixed_on_select"](inputs)
            if ch:
                fixed = (ch["machine"], float(ch["r"]))
        for kind, cells in rb.get("test", {}).items():
            for ck, e in cells.items():
                e["size_label"] = ("size fixed before the test" if fixed and ck == cell_key(*fixed)
                                   else "forward-only evidence")
        for p in READ_PERIODS:
            for kind, cells in rb.get(p, {}).items():
                for e in cells.values():
                    e["period_label"] = PERIOD_LABEL[p]
        d0p = np.concatenate([inf["d0"] / inf["P0"] for inf in infos[(ri, "test")]]) if infos[(ri, "test")] \
            else np.zeros(0)
        board[rid] = {**_row_meta(row), "periods": rb, "headline": headline_of(rb, ctx.get("headline_cell")),
                      "size_fixed_on_select": None if fixed is None else {
                          "cell": cell_key(*fixed),
                          "test": rb.get("test", {}).get("calendar", {}).get(cell_key(*fixed))}}
        lever[rid] = {**_row_meta(row), "periods": lb, "wallet_risk_table_test_signals": wallet_risk_table(d0p)}
        _S.setdefault("fixed", {})[ri] = fixed

    # ---------------------------------------------------------------- continuous accounts (+ R12, R13, R15 inputs)
    ctasks2 = []
    for ri in range(len(rows)):
        for p in READ_PERIODS:
            if not any(len(sig["k"]) for sig, _ in parts[(ri, p)]) and p == "extra":
                pass
            for r in CONT_RS:
                ctasks2.append((ri, p, ("r", r)))
            fx = _S["fixed"].get(ri)
            if fx is not None:
                ctasks2.append((ri, p, ("fixed", fx[0], fx[1])))
    cres = {}
    for ri, p, which, out in pmap(_cont_task, ctasks2, procs, "reads_a continuous"):
        cres[(ri, p, which)] = out
    cont, r12 = {}, {}
    for ri, row in enumerate(rows):
        rid = _row_id(row)
        c = {}
        for p in READ_PERIODS:
            for r in CONT_RS:
                x = cres.get((ri, p, ("r", r)))
                if x:
                    c.setdefault(p, {})[f"r={r * 100:g}% ($5,000, tested machine)"] = {
                        **x["continuous"], "bust": x["bust"], "n_positions": x["n_positions"]}
            fx = _S["fixed"].get(ri)
            if fx is not None:
                x = cres.get((ri, p, ("fixed", fx[0], fx[1])))
                if x:
                    c.setdefault(p, {})[f"size fixed on select {cell_key(*fx)} (fresh $1,000)"] = {
                        **x["continuous"], "bust": x["bust"], "n_positions": x["n_positions"]}
        cont[rid] = {**_row_meta(row), "periods": c}
        r12[rid] = {**_row_meta(row), "periods": {p: cres[(ri, p, ("r", H.R_BASE))]["r12"] for p in ("select", "test")
                                                   if (ri, p, ("r", H.R_BASE)) in cres}}

    # ---------------------------------------------------------------- R15 and R13 (pick and v1 rows)
    single = [(ri, row) for ri, row in enumerate(rows) if row["kind"] in ("pick", "v1")]
    r15, r13_rows = {}, {p: {} for p in ("select", "test")}
    union_sets = {p: {"public": [], "all": []} for p in ("select", "test")}
    usd = ctx.get("judge_usd_per_call")
    for ri, row in single:
        rid = _row_id(row)
        spec = row["members"][0]
        r15[rid] = {**_row_meta(row)}
        for p in ("select", "test"):
            a, b = _S["periods"][p]
            ev = row_events(live, mks[p], spec)
            rate = signal_rate(ev["close_ms"], ev["gated"], a, b)
            sig, _ = parts[(ri, p)][0]
            rate["gated_matches_signals"] = bool(int(ev["gated"].sum()) == len(sig["k"]))
            x = cres.get((ri, p, ("r", H.R_BASE)), {})
            inf = infos[(ri, p)][0]
            rate["taken_dropped"] = taken_by_month(inf["fill"], x.get("taken_ms", []), x.get("skipped"), a, b)
            r15[rid][p] = rate
            union_sets[p]["all"].append(ev)
            if not ds_of[rid]:
                union_sets[p]["public"].append(ev)
            r13_rows[p][rid] = {"events": {"coin": sig["k"], "side": sig["side"], "close_ms": inf["close"]},
                                "tf_ms": H.TF_MS[spec["tf"]], "iv": x.get("iv", ([], [])), "lnM": x.get("lnM", [])}
    unions = {}
    for p in ("select", "test"):
        a, b = _S["periods"][p]
        for which in ("public", "all"):
            u = union_events(union_sets[p][which])
            ut = signal_rate(u["total"]["close_ms"], u["total"]["gated"], a, b)
            ud = signal_rate(u["distinct"]["close_ms"], u["distinct"]["gated"], a, b)
            unions.setdefault(which, {})[p] = {
                "one_call_per_pick_event": ut, "one_call_per_distinct_event": ud,
                "judge_budget_G": judge_budget(ut, usd, "G"), "judge_budget_all": judge_budget(ut, usd, "all")}
    r13 = {}
    for p in ("select", "test"):
        a, b = _S["periods"][p]
        r13[p] = overlap_matrix(r13_rows[p], int((b - a) // FIVE)) if r13_rows[p] else {}

    # ---------------------------------------------------------------- D11 split and output
    priv = ctx["private"]
    out = ctx["out"]
    pub_board, priv_board = split_ds(board, ds_of)
    pub_lev, priv_lev = split_ds(lever, ds_of)
    pub_cont, priv_cont = split_ds(cont, ds_of)
    pub_r12, priv_r12 = split_ds(r12, ds_of)
    pub_r15, priv_r15 = split_ds(r15, ds_of, ints_only)
    ds_ids = {_row_id(r) for r in rows if ds_of[_row_id(r)]}
    pub_r13, priv_r13 = {}, {}
    for p, m in r13.items():
        pub_r13[p], priv_r13[p] = {"ids": m.get("ids", [])}, {}
        for sec_ in ("signal_overlap", "time_overlap", "corr_monthly_lnM"):
            for pair, v in (m.get(sec_) or {}).items():
                a_, b_ = pair.split("|", 1) if pair.count("|") == 1 else _split_pair(pair, m.get("ids", []))
                tgt = priv_r13 if (a_ in ds_ids or b_ in ds_ids) else pub_r13
                tgt[p].setdefault(sec_, {})[pair] = v
    any_ds = bool(ds_ids)
    pub_union = {"without_deepseek_rows": unions.get("public"),
                 "all_rows": ints_only(unions.get("all")) if any_ds else unions.get("all")}
    out.update({
        "what": "Phase-A reads (W 7, panel R1 / R12 / R13 / R15, owners' continuous and leverage reads): reported, "
                "never a pass; computed after the verdict on the fixed rows",
        "api": 1, "module": "research/hunt/reads_a.py", "reads_pin": ctx.get("reads_pin"),
        "reads_line_before_test_json": reads_line, "choices": CHOICES,
        "resolution": "5m marked equity (touch, peak, days, drawdown, run-up)",
        "constants": {"start": GOAL_START, "bust_below": GOAL_BUST, "levels": list(GOAL_LEVELS), "r": list(GOAL_RS),
                      "goal_mode_min_r": GOAL_MODE_MIN_R, "leverage": list(LEV_LS), "calendar_control_seeds":
                      CAL_CTL_SEEDS, "rolling_control_seeds": n_roll, "leverage_control_seeds_calendar":
                      LEV_CTL_SEEDS, "leverage_control_seeds_rolling": n_lev_roll,
                      "window_run_seconds": round(sec, 5), "window_run_seconds_measured_here": measured,
                      "slow_window_s": SLOW_WINDOW_S, "mbb": [MBB_BLOCK, MBB_N, MBB_CONF], "cp_conf": CP_CONF},
        "notes": [INDEPENDENT_LINE, ALTPUMP_SCALE_LINE,
                  "The touch columns are descriptive and do not create a stop-at-target rule.",
                  "Any size read off the test board is forward-only evidence; the size fixed on select is labelled.",
                  "Every bracket table is a 2026 snapshot applied to 2020-2026 (H 7.3)."],
        "rows": [_row_meta(r) for r in rows],
        "r1_goal_board": pub_board, "leverage": pub_lev, "continuous": pub_cont, "r12_basics": pub_r12,
        "r13_basics": pub_r13, "r15_signal_rate": {"rows": pub_r15, "union": pub_union},
        "seconds": round(time.time() - t_all, 1)})
    priv.update({"what": "reads_a private part (D11): DeepSeek rows and pairs, all figures",
                 "r1_goal_board": priv_board, "leverage": priv_lev, "continuous": priv_cont, "r12_basics": priv_r12,
                 "r13_basics": priv_r13, "r15_signal_rate": {"rows": priv_r15,
                                                             "union_all_rows": unions.get("all")}})
    log(f"reads_a: done in {time.time() - t_all:.0f}s")


def _split_pair(pair: str, ids: list) -> tuple:
    """Split 'a|b' when the ids themselves contain '|' (row ids never do today)."""
    for a in ids:
        if pair.startswith(a + "|") and pair[len(a) + 1:] in ids:
            return a, pair[len(a) + 1:]
    return pair, ""


def _sum_counts(ds: list) -> dict:
    out: dict = {}
    for d in ds:
        for k, v in d.items():
            out[k] = out.get(k, 0) + int(v)
    return out


def _tab_compact(rl: list) -> dict:
    """board_cell table from compact row records (``_pick_rec``)."""
    col = lambda k: np.asarray([np.nan if r.get(k) is None else r[k] for r in rl], float)  # noqa: E731
    return {"m_end": col("m_end"), "m_marked": col("m_marked"), "peak_m": col("peak_m"), "give_back": col("give_back"),
            "n80": col("n80"), "days_x2": col("days_x2"), "days_x5": col("days_x5"),
            "bits": np.asarray([r["bits"] for r in rl], np.int64), "resolution": ["5m"] if rl else []}


def row_events(live, mk, spec: dict) -> dict:
    """Every event of one system in the market's period with a defined ATR14 and a fill bar: coin, side, signal
    close and whether the system's gate lets it through (G) or blocks it (N). Same cleaning as system_signals (both
    sides on one bar -> none)."""
    tf = spec["tf"]
    K, S, C, G = [], [], [], []
    for k, s in enumerate(mk.syms):
        ser = live.series(s, tf)
        lg, sh = live.cached_events(spec, s)
        cm = np.asarray(ser.bars.close_ms, np.int64)
        inper = (cm >= mk.start) & (cm < mk.end)
        both = lg & sh & inper
        lg, sh = lg & inper & ~both, sh & inper & ~both
        g = live.gate_mask(ser, spec["gate"])
        atr_ok = np.isfinite(ser.atr) & (ser.atr > 0)
        _, f_ok = live.fill_index(mk, k, ser)
        for side, ev in ((1, lg), (-1, sh)):
            jj = np.flatnonzero(ev & atr_ok & f_ok)
            K.append(np.full(len(jj), k, np.int64))
            S.append(np.full(len(jj), side, np.int64))
            C.append(cm[jj])
            G.append(np.asarray(g, bool)[jj])
    cat = lambda xs, d: np.concatenate(xs).astype(d) if xs else np.zeros(0, d)  # noqa: E731
    return {"coin": cat(K, np.int64), "side": cat(S, np.int64), "close_ms": cat(C, np.int64), "gated": cat(G, bool)}

"""Shared pieces of the Nasdaq-open / time-exit study (research/opentime, PREREG.md): the clock (09:25 New York bars,
the 09:30-11:00 window), the arms, the periods, the month multiples and the diagnostics.

Run every script of this folder with ``python3 -I`` (downloaded data are read as arrays only); this module puts the
repository and the user site on sys.path itself."""
from __future__ import annotations

import math
import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
for _p in (REPO, os.path.expanduser("~/.local/lib/python3.11/site-packages"), "/root/.local/lib/python3.11/site-packages"):
    if _p not in sys.path:
        (sys.path.insert(0, _p) if _p == REPO else sys.path.append(_p))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

NY = ZoneInfo("America/New_York")
UTC = timezone.utc
MIN, FIVE, HOUR, DAY = 60_000, 300_000, 3_600_000, 86_400_000
KST = 9 * HOUR

# arm name -> (kind, hours): kind "none" | "open_close" (A1) | "open_be" (A2) | "time" (A3-5) | "open_mix" (A6)
ARMS = {"A0": ("none", 0), "A1": ("open_close", 0), "A2": ("open_be", 0), "A3": ("time", 4), "A4": ("time", 8),
        "A5": ("time", 12), "A6": ("open_mix", 0)}
ARM_KO = {"A0": "지금 그대로", "A1": "개장 전 정리 (잠금 전이면 09:25봉 종가에 닫기)",
          "A2": "개장 전 본전 (이익이면 손절을 본전으로)", "A3": "시간 정리 4시간", "A4": "시간 정리 8시간",
          "A5": "시간 정리 12시간", "A6": "개장 전: 이익이면 본전, 손실이면 닫기"}
ARM_CODE = {"none": 0, "open_close": 1, "open_be": 2, "time": 3, "open_mix": 6}


def kst_ms(s: str) -> int:
    return int(pd.Timestamp(s, tz="Asia/Seoul").value // 1_000_000)


PERIODS = {"choose": ("2021-01", "2023-12"), "check": ("2024-01", "2026-09"), "recent": ("2026-10", "2026-10")}
RUN_START = kst_ms("2021-01-01 00:00")


def months_of(period: str) -> list[str]:
    a, b = PERIODS[period]
    return [str(p) for p in pd.period_range(a, b, freq="M")]


def kst_month(t_ms) -> np.ndarray:
    return pd.to_datetime(np.asarray(t_ms, np.int64) + KST, unit="ms").strftime("%Y-%m").to_numpy()


# ---------------------------------------------------------------------------- the clock
def nyse_holidays() -> frozenset:
    from paperbot.sessions import NYSE_HOLIDAYS
    return NYSE_HOLIDAYS


def open_moments(t0_ms: int, t1_ms: int) -> np.ndarray:
    """Open times (UTC ms) of every 09:25 New York 5-minute bar (Mon-Fri New York date, not a NYSE holiday of the repo's
    list) between t0 and t1: the bar whose CLOSE is the 09:30 cash open."""
    hol = nyse_holidays()
    d = datetime.fromtimestamp(t0_ms / 1000, UTC).astimezone(NY).date() - timedelta(days=1)
    end = datetime.fromtimestamp(t1_ms / 1000, UTC).astimezone(NY).date() + timedelta(days=1)
    out = []
    while d <= end:
        if d.weekday() < 5 and d.isoformat() not in hol:
            t = datetime(d.year, d.month, d.day, 9, 25, tzinfo=NY).astimezone(UTC)
            out.append(int(t.timestamp() * 1000))
        d += timedelta(days=1)
    a = np.array(out, np.int64)
    return a[(a >= t0_ms) & (a <= t1_ms)]


def open_flags(ts: np.ndarray) -> np.ndarray:
    """bool per 5-minute bar: the bar opens at 09:25 New York on a trading weekday (an M of PREREG.md)."""
    mo = open_moments(int(ts[0]), int(ts[-1]))
    return np.isin(ts, mo)


def window_flags(ts: np.ndarray, bar_ms: int = FIVE) -> np.ndarray:
    """bool per bar (open time ts): the bar opens inside 09:30-11:00 New York (90 min after the cash open)."""
    mo = open_moments(int(ts[0]) - DAY, int(ts[-1]) + DAY) + FIVE           # 09:30 instants
    i = np.searchsorted(mo, ts, side="right") - 1
    ok = i >= 0
    since = np.where(ok, ts - mo[np.maximum(i, 0)], -1)
    return ok & (since >= 0) & (since < 90 * MIN)


# ---------------------------------------------------------------------------- month multiples and period metrics
def period_metrics(T: pd.DataFrame, period: str) -> dict:
    """T: trades with columns t (entry ms), ret (net P&L / wallet before), touched (bool). Months: KST, fresh $50."""
    return month_metrics(T, months_of(period))


def month_metrics(T: pd.DataFrame, ms_: list) -> dict:
    """period_metrics over an explicit list of KST months."""
    mo = kst_month(T["t"].to_numpy(np.int64)) if len(T) else np.array([], object)
    sel = np.isin(mo, ms_)
    P = T[sel].copy()
    P["month"] = mo[sel]
    mult = {m: 1.0 for m in ms_}
    for m, g in P.groupby("month"):
        mult[m] = float(np.prod(1.0 + g["ret"].to_numpy(float)))
    v = np.array([mult[m] for m in ms_], float)
    r = P["ret"].to_numpy(float)
    return {"months": len(ms_), "trades": int(len(P)), "win_pct": 100 * float((r > 0).mean()) if len(r) else float("nan"),
            "mean_ret_pct": 100 * float(r.mean()) if len(r) else float("nan"),
            "median_month": float(np.median(v)), "months_up": int((v > 1.0).sum()), "worst_month": float(v.min()),
            "best_month": float(v.max()), "log_growth": float(np.log1p(np.maximum(r, -1 + 1e-12)).sum()),
            "touched": int(P["touched"].sum()) if "touched" in P else 0,
            "by_month": {m: round(mult[m], 5) for m in ms_}}


def beats(a: dict, b: dict) -> bool:
    """PREREG decision: a's median month multiple > b's; equal (1e-12) -> log growth."""
    if abs(a["median_month"] - b["median_month"]) > 1e-12:
        return a["median_month"] > b["median_month"]
    return a["log_growth"] > b["log_growth"]


def verdicts(res: dict) -> dict:
    """res: arm -> period -> metrics. An arm helps only if it beats A0 in both choose and check."""
    out = {}
    for arm, per in res.items():
        if arm == "A0":
            continue
        c = beats(per["choose"], res["A0"]["choose"])
        k = beats(per["check"], res["A0"]["check"])
        out[arm] = {"beats_A0_choose": c, "beats_A0_check": k, "helps": bool(c and k)}
    return out


# ---------------------------------------------------------------------------- diagnostics on A0
def diag_reach(D: pd.DataFrame, flag: str, roe_col: str | None = None) -> dict:
    """Among positions with D[flag] (open and unlocked at that moment): share that later reached the first lock, ended at
    the stop, other; next to all positions. D: columns locked (bool, reached the first lock / TP), kind ('SL' stop
    without lock, 'LOCKED', 'OTHER')."""
    def shares(g):
        n = len(g)
        if not n:
            return {"n": 0}
        return {"n": int(n), "later_locked_pct": 100 * float(g["locked"].mean()),
                "stopped_pct": 100 * float((g["kind"] == "SL").mean()),
                "other_pct": 100 * float((g["kind"] == "OTHER").mean()),
                "mean_ret_pct": 100 * float(g["ret"].mean())}
    sub = D[D[flag].astype(bool)]
    out = {"all": shares(D), "flagged": shares(sub)}
    if roe_col is not None and len(sub):
        out["flagged_in_profit"] = shares(sub[sub[roe_col] > 0])
        out["flagged_in_loss"] = shares(sub[sub[roe_col] <= 0])
    return out


def diag_losses(D: pd.DataFrame) -> dict:
    """(c): losing trades split by 'stop hit inside 09:30-11:00 New York' (column sl_in_window); exposure share."""
    L = D[D["ret"] < 0]
    w = L[L["sl_in_window"].astype(bool)]
    o = L[~L["sl_in_window"].astype(bool)]
    held = float(D["held_bars"].sum())
    return {"losses": int(len(L)), "stop_in_window": int(len(w)), "other": int(len(o)),
            "stop_in_window_pct": 100 * len(w) / max(len(L), 1),
            "loss_sum_in_window_pct_equity": 100 * float(w["ret"].sum()),
            "loss_sum_other_pct_equity": 100 * float(o["ret"].sum()),
            "loss_share_in_window_pct": 100 * float(w["ret"].sum() / L["ret"].sum()) if len(L) else float("nan"),
            "held_time_in_window_pct": 100 * float(D["held_in_window"].sum()) / held if held else float("nan"),
            "all_stops": int((D["kind"] == "SL").sum()),
            "all_stops_in_window": int(((D["kind"] == "SL") & D["sl_in_window"].astype(bool)).sum())}


def by_period_diag(D: pd.DataFrame) -> dict:
    """The diagnostics per period (choose / check / recent) and over all of them."""
    mo = kst_month(D["t"].to_numpy(np.int64))
    out = {}
    for p in ("choose", "check", "recent", "all"):
        g = D if p == "all" else D[np.isin(mo, months_of(p))]
        out[p] = {"open_at_M": diag_reach(g, "open_at_M", "roe_at_M"),
                  **{f"open_{h}h": diag_reach(g, f"open_{h}h") for h in (4, 8, 12)},
                  "losses": diag_losses(g)}
    return out


def jsonable(x):
    if isinstance(x, dict):
        return {str(k): jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [jsonable(v) for v in x]
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        return None if not math.isfinite(float(x)) else round(float(x), 6)
    if isinstance(x, np.bool_):
        return bool(x)
    return x


# ---------------------------------------------------------------------------- (d) what "횡보" looks like (PREREG addendum 2)
R_BINS = (("R <= -0.5", -np.inf, -0.5), ("-0.5 < R <= 0", -0.5, 0.0), ("0 < R <= 0.25", 0.0, 0.25),
          ("0.25 < R <= 0.5", 0.25, 0.5), ("R > 0.5", 0.5, np.inf))
H_BINS = (("< 2h", 0.0, 2.0), ("2-6h", 2.0, 6.0), ("6-12h", 6.0, 12.0), (">= 12h", 12.0, np.inf))
S_BINS = (("< 25%", -np.inf, 0.25), ("25-50%", 0.25, 0.5), ("50-75%", 0.5, 0.75), (">= 75%", 0.75, np.inf))
SMALL = 20


def _outcome(g: pd.DataFrame) -> dict:
    n = len(g)
    if not n:
        return {"n": 0, "small_sample": True}
    return {"n": int(n), "small_sample": bool(n < SMALL), "later_locked_pct": 100 * float(g["locked"].mean()),
            "stopped_pct": 100 * float((g["kind"] == "SL").mean()), "other_pct": 100 * float((g["kind"] == "OTHER").mean()),
            "mean_ret_pct": 100 * float(g["ret"].mean())}


def sideways(D: pd.DataFrame) -> dict:
    """(d) on the positions open and unlocked at their first M: R progress (left-open, right-closed bins), net sign,
    hours held (left-closed), best-so-far share of the way to the first-lock trigger (left-closed)."""
    g = D[D["open_at_M"].astype(bool)]
    out = {"all_unresolved_at_M": _outcome(g), "R": {}, "net_sign": {}, "hours": {}, "best_share": {}}
    r = g["R_at_M"].to_numpy(float)
    for name, a, b in R_BINS:
        out["R"][name] = _outcome(g[(r > a) & (r <= b)])
    out["net_sign"]["net ROE > 0"] = _outcome(g[g["roe_at_M"] > 0])
    out["net_sign"]["net ROE <= 0"] = _outcome(g[g["roe_at_M"] <= 0])
    hh = g["hours_at_M"].to_numpy(float)
    for name, a, b in H_BINS:
        out["hours"][name] = _outcome(g[(hh >= a) & (hh < b)])
    s = g["mfe_share_at_M"].to_numpy(float)
    for name, a, b in S_BINS:
        out["best_share"][name] = _outcome(g[(s >= a) & (s < b)])
    return out


def by_period_sideways(D: pd.DataFrame) -> dict:
    mo = kst_month(D["t"].to_numpy(np.int64))
    return {p: sideways(D if p == "all" else D[np.isin(mo, months_of(p))]) for p in ("choose", "check", "recent", "all")}

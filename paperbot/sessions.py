"""Weekday / weekend and trading-session breakdown of closed trades.

Times are the ENTRY time in Korea time (KST, UTC+9), since the owners read
results in KST. Sessions (KST, by entry hour):
    asia    09-16
    europe  16-22
    us      22-05 (next day)
    dawn    05-09
Weekend = Saturday and Sunday in KST.

Primary table: 2 (weekday/weekend) x 4 sessions = 8 cells. A cell with
fewer than ``min_n`` trades is marked "insufficient"; nothing is concluded
from it. The 7x24 heatmap is for description only (168 cells are far too
many to test).

Special windows, flagged per trade (entry within the window):
    funding    +-10 min around 00:00/08:00/16:00 UTC settlements
    us_open    +-60 min around 09:30 New York (weekdays, DST aware)
    macro      +-30 min around 08:30 New York (weekdays; the usual US
               data release time; not a calendar of actual releases)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence
from zoneinfo import ZoneInfo

from .models import TradeRecord

KST = ZoneInfo("Asia/Seoul")
NY = ZoneInfo("America/New_York")
SESSIONS = ("asia", "europe", "us", "dawn")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def session_of(hour_kst: int) -> str:
    if 9 <= hour_kst < 16:
        return "asia"
    if 16 <= hour_kst < 22:
        return "europe"
    if 5 <= hour_kst < 9:
        return "dawn"
    return "us"


def _near_ny(dt_utc: datetime, hh: int, mm: int, minutes: int) -> bool:
    local = dt_utc.astimezone(NY)
    if local.weekday() >= 5:
        return False
    anchor = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return abs((local - anchor).total_seconds()) <= minutes * 60


def time_features(ts_ms: int) -> dict:
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    k = dt.astimezone(KST)
    windows = []
    # Funding: nearest 8h settlement in UTC.
    sec = dt.hour * 3600 + dt.minute * 60 + dt.second
    off = sec % (8 * 3600)
    if min(off, 8 * 3600 - off) <= 600:
        windows.append("funding")
    if _near_ny(dt, 9, 30, 60):
        windows.append("us_open")
    if _near_ny(dt, 8, 30, 30):
        windows.append("macro")
    return {"kst_weekday": WEEKDAYS[k.weekday()], "kst_hour": k.hour,
            "weekend": k.weekday() >= 5, "session": session_of(k.hour),
            "windows": windows}


def _cell(trades: list[TradeRecord], min_n: int) -> dict:
    n = len(trades)
    if not n:
        return {"n": 0, "status": f"insufficient (n<{min_n})"}
    rs = []
    for t in trades:
        d = abs(t.entry_price - t.stop_price) * t.qty
        if d > 0:
            rs.append(t.pnl / d)
    eq_ret = [t.pnl / (t.equity_after - t.pnl) for t in trades if t.equity_after - t.pnl > 0]
    return {
        "n": n,
        "win_rate": sum(t.pnl > 0 for t in trades) / n,
        "mean_r": sum(rs) / len(rs) if rs else None,
        "mean_ret": sum(eq_ret) / len(eq_ret) if eq_ret else None,
        "pnl": sum(t.pnl for t in trades),
        "liquidations": sum(t.exit_reason == "LIQ" for t in trades),
        "status": "ok" if n >= min_n else f"insufficient (n<{min_n})",
    }


def session_report(trades: Sequence[TradeRecord], min_n: int = 30,
                   by: Optional[str] = None) -> dict:
    """``by``: optional TradeRecord attribute (e.g. "strategy_id", "symbol")
    to split the primary table by."""
    feats = [(t, time_features(t.entry_time)) for t in trades]
    primary = []
    for wk in (False, True):
        for ses in SESSIONS:
            sel = [t for t, f in feats if f["weekend"] == wk and f["session"] == ses]
            primary.append({"day": "weekend" if wk else "weekday", "session": ses,
                            **_cell(sel, min_n)})
    windows = []
    for w in ("funding", "us_open", "macro"):
        inside = [t for t, f in feats if w in f["windows"]]
        outside = [t for t, f in feats if w not in f["windows"]]
        windows.append({"window": w, "inside": _cell(inside, min_n),
                        "outside": _cell(outside, min_n)})
    weekday = [{"weekday": d, **_cell([t for t, f in feats if f["kst_weekday"] == d], min_n)}
               for d in WEEKDAYS]
    heat = {d: [None] * 24 for d in WEEKDAYS}
    for d in WEEKDAYS:
        for h in range(24):
            sel = [t for t, f in feats if f["kst_weekday"] == d and f["kst_hour"] == h]
            if sel:
                heat[d][h] = {"n": len(sel), "pnl": sum(t.pnl for t in sel)}
    out = {"trades": len(trades), "timezone": "Asia/Seoul (entry time)",
           "primary": primary, "weekday": weekday, "windows": windows,
           "heatmap_note": "description only; not tested", "heatmap": heat}
    if by:
        groups: dict[str, list[TradeRecord]] = {}
        for t in trades:
            groups.setdefault(str(getattr(t, by)), []).append(t)
        out["by"] = by
        out["split"] = {g: session_report(ts, min_n)["primary"] for g, ts in sorted(groups.items())}
    return out


def kst(ts_ms: int) -> str:
    return (datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).astimezone(KST)
            .strftime("%Y-%m-%d %H:%M KST"))


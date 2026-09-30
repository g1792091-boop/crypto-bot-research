"""Loss cards: what a losing trade looked like, built by code at every close (no AI).

A card joins the stored trade (trades.data in paper3.db), the chart situation on the
signal bar (``ctx`` from sigservice.chart_context), the best and worst point during
the trade, fixed descriptive tags, and, once the nightly check has run, what a 1.5,
2.5 or 3 ATR stop would have done (daily3 ``stop*`` shadows).

``tag_stats`` compares how often each tag appears in a strategy's losses and in its
winning trades; a tag much more common in losses is what the strategy's specialist
looks at first. The tags are fixed here and are descriptions, not rules to trade on.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Iterable, Optional

from .aggregate import TF_MS
from .ladder import net_roe

REGIME_KO = {"trend_up": "상승 추세", "trend_down": "하락 추세", "box": "박스권", "chop": "방향 없는 횡보",
             "unknown": "뚜렷하지 않음"}
REASON_KO = {"SL": "손절", "LIQ": "강제청산", "LOCK": "익절 잠금", "TP": "익절", "HALT": "정지", "END": "종료"}
FIRST_LOCK = 0.12
STOP_VARIANTS = (1.5, 2.5, 3.0)

# (tag, test on the card fields). Descriptions only; fixed before any paper result.
TAGS = (
    ("강제청산", lambda c: c["reason"] == "LIQ"),
    ("수익 났다가 손절", lambda c: c["reason"] == "SL" and c["best_roe"] is not None and c["best_roe"] >= 0.05),
    ("진입 직후 바로 손절", lambda c: c["reason"] == "SL" and c["hold_bars"] is not None and c["hold_bars"] <= 1
     and (c["best_roe"] or 0) < 0.02),
    ("추세 반대 진입", lambda c: _against(c["side"], c["ctx"].get("regime"))),
    ("상위 봉 추세 반대", lambda c: _against(c["side"], c["ctx"].get("htf_regime"))),
    ("횡보장 진입", lambda c: c["ctx"].get("regime") in ("chop", "box")),
    ("추세 약함 (ADX 20 미만)", lambda c: c["ctx"].get("adx") is not None and c["ctx"]["adx"] < 20),
    ("DI 방향 반대", lambda c: None not in (c["ctx"].get("di_plus"), c["ctx"].get("di_minus"))
     and (c["ctx"]["di_plus"] - c["ctx"]["di_minus"]) * c["side"] < 0),
    ("많이 오른/내린 뒤 추격", lambda c: c["ctx"].get("ema20_dist_atr") is not None
     and c["ctx"]["ema20_dist_atr"] * c["side"] >= 2.0),
    ("최근 범위 끝에서 진입", lambda c: c["ctx"].get("range_pct") is not None
     and ((c["side"] > 0 and c["ctx"]["range_pct"] >= 0.9) or (c["side"] < 0 and c["ctx"]["range_pct"] <= 0.1))),
)


def _against(side: int, regime: Optional[str]) -> bool:
    return (side > 0 and regime == "trend_down") or (side < 0 and regime == "trend_up")


def card(account_id: str, t: dict, round_trip: float, variants: Optional[dict] = None,
         names_ko: Optional[dict] = None) -> dict:
    """One trade (a stored ``trades.data`` dict) as a card. Works for any trade; the
    dashboard shows losses."""
    side, lev, entry = int(t["side"]), float(t["leverage"]), float(t["entry_price"])
    tf = t.get("timeframe")
    hold_ms = t["exit_time"] - t["entry_time"]
    ctx = dict(t.get("context") or {})
    best = t.get("mfe_price")
    worst = t.get("mae_price")
    c = {
        "account_id": account_id, "strategy": t["strategy_id"],
        "name_ko": (names_ko or {}).get(t["strategy_id"], t["strategy_id"]),
        "timeframe": tf, "symbol": t["symbol"], "side": side, "side_ko": "롱" if side > 0 else "숏",
        "leverage": int(lev), "entry_time": t["entry_time"], "exit_time": t["exit_time"],
        "entry_price": entry, "exit_price": t["exit_price"], "reason": t["exit_reason"],
        "reason_ko": REASON_KO.get(t["exit_reason"], t["exit_reason"]), "roe": t["roe"], "pnl": t["pnl"],
        "hold_min": hold_ms / 60_000, "hold_bars": hold_ms / TF_MS[tf] if tf in TF_MS else None,
        "best_roe": net_roe(side, entry, best, lev, round_trip) if best else None,
        "worst_roe": net_roe(side, entry, worst, lev, round_trip) if worst else None,
        "ctx": ctx, "regime_ko": REGIME_KO.get(ctx.get("regime"), None),
        "htf_regime_ko": REGIME_KO.get(ctx.get("htf_regime"), None),
        "signal_bar_close": t["signal_ts"] + 1,
    }
    c["touched_first_lock"] = c["best_roe"] is not None and c["best_roe"] >= FIRST_LOCK
    c["tags"] = [name for name, test in TAGS if _safe(test, c)]
    c["if_stop"] = variants or {}
    return c


def _safe(test, c) -> bool:
    try:
        return bool(test(c))
    except (TypeError, KeyError):
        return False


def tag_stats(cards: Iterable[dict]) -> list[dict]:
    """Per tag: share among losing trades vs among winning trades (same strategy/period)."""
    cards = list(cards)
    losses = [c for c in cards if c["pnl"] < 0]
    wins = [c for c in cards if c["pnl"] > 0]
    out = []
    for name, _ in TAGS:
        nl = sum(name in c["tags"] for c in losses)
        nw = sum(name in c["tags"] for c in wins)
        out.append({"tag": name, "losses": nl, "loss_share": nl / len(losses) if losses else None,
                    "wins": nw, "win_share": nw / len(wins) if wins else None})
    out.sort(key=lambda r: -((r["loss_share"] or 0) - (r["win_share"] or 0)))
    return out


def stop_variants(daily_conn: Optional[sqlite3.Connection], account_id: str, symbol: str,
                  bar_close: int) -> dict:
    """{"1.5": {"roe", "exit_reason", "resolved"}, ...} from daily3 shadows, if computed."""
    if daily_conn is None:
        return {}
    out = {}
    for k in STOP_VARIANTS:
        r = daily_conn.execute("SELECT roe, exit_reason, resolved FROM shadows WHERE key = ?",
                               (f"stop{k}|{account_id}|{symbol}|{bar_close}",)).fetchone()
        if r is not None:
            out[str(k)] = {"roe": r[0], "exit_reason": r[1], "resolved": bool(r[2])}
    return out


def cards_from_db(conn: sqlite3.Connection, round_trip: float, strategy: Optional[str] = None,
                  timeframe: Optional[str] = None, losses_only: bool = True, since_ms: int = 0,
                  limit: int = 200, daily_conn: Optional[sqlite3.Connection] = None,
                  names_ko: Optional[dict] = None) -> list[dict]:
    q = "SELECT account_id, data FROM trades WHERE exit_time >= ?"
    args: list = [since_ms]
    if losses_only:
        q += " AND pnl < 0"
    esc = lambda x: x.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")  # noqa: E731
    if strategy:
        q += " AND account_id LIKE ? ESCAPE '\\'"
        args.append(f"{esc(strategy)}@%")
    if timeframe:
        q += " AND account_id LIKE ? ESCAPE '\\'"
        args.append(f"%@{esc(timeframe)}")
    q += " ORDER BY id DESC LIMIT ?"
    args.append(min(max(limit, 1), 2000))
    out = []
    for aid, data in conn.execute(q, args):
        t = json.loads(data)
        v = stop_variants(daily_conn, aid, t["symbol"], t["signal_ts"] + 1)
        out.append(card(aid, t, round_trip, v, names_ko))
    return out

"""Why an entry got its leverage under the restarted run's rule B (docs/paper-v3-rules-change-1.md section 6): the
signal's group (좋은 자리 / 보통), its entry-quality score, the leverage it entered at and the higher candidates the
sizing tried first and why each failed. Read-only and descriptive; not a trading file (sizing never imports it).

Where the facts come from (nothing new is recorded for this):
- the group: the trade's / position's ``tier`` ("best" / "normal": sizing.size_position names the decision by the
  signal's group under "quality_v1"); when missing, levrule.signal_group on the stored signal, which is what the
  sizing itself called;
- the score: levrule.signal_group on the stored signal (the strength in ``meta["ctx"]``, the frozen
  paperbot/quality_edges.json) - for a closed trade the signal's ctx is ``TradeRecord.context``; a coin flip has
  no score (its group is a seeded draw with probability p_best);
- the rejected candidates: the ENTERED outcome's ``detail.downgrades`` (engine._try_enter records
  ``SizeDecision.reasons``: one line per candidate that failed, "<group>/<lev>x: <why>", in the order tried).

``explain`` turns those into {"group", "group_ko", "score", "source", "leverage", "tried", "rejected", "short_ko"};
``short_ko`` is one line, e.g. "50배 불가: 손절 손실 > 자금 15% · 40배 불가: 손절 손실 > 자금 15% → 30배".
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any, Iterable, Optional

GROUP_KO = {"best": "좋은 자리", "normal": "보통"}
# sizing.size_position's reason lines -> (code, Korean)
REASONS = (("min_size", "below minimum order size", "최소 주문 크기 미달"),
           ("bracket", "bracket allows", "거래소 구간 한도"),
           ("liq", "too close to liq", "손절이 청산가에 너무 가까움"),
           ("loss_cap", "of equity", "손절 손실 > 자금 15%"))
REASON_KO = {c: ko for c, _m, ko in REASONS}
REASON_KO["other"] = "기타"
_TAG = re.compile(r"^\s*([A-Za-z_]+)/(\d+)x:\s*(.*)$")
MAX_REASONS = 8


def reason_code(text: str) -> str:
    """'loss_cap' / 'liq' / 'bracket' / 'min_size' / 'other' of one sizing reason line."""
    t = str(text or "")
    for code, marker, _ko in REASONS:
        if marker in t:
            return code
    return "other"


def parse_downgrades(lines: Any) -> list[dict]:
    """[{"lev", "group", "code", "ko"}] of the candidates the sizing rejected, in the order tried."""
    out = []
    for x in (lines if isinstance(lines, list) else [])[:MAX_REASONS]:
        m = _TAG.match(str(x))
        if not m:
            continue
        code = reason_code(m.group(3))
        out.append({"lev": int(m.group(2)), "group": m.group(1), "code": code, "ko": REASON_KO[code]})
    return out


def _chain(group: str) -> list[int]:
    """The leverages the rule tries for a group, in order (config.v3_settings().tier_chain)."""
    from .config import v3_settings
    try:
        return [lev for _t, lev in v3_settings().tier_chain(group)]
    except ValueError:
        return []


def _signal_info(sig: Optional[dict]) -> dict:
    if not isinstance(sig, dict):
        return {}
    from .levrule import signal_group
    return signal_group(sig)


def explain(tier: Any, leverage: Any, downgrades: Any = None, signal: Optional[dict] = None) -> dict:
    """The why of one entry. ``tier``: the trade's / position's group ("best" / "normal", else taken from
    ``signal``); ``leverage``: what it entered at; ``downgrades``: the ENTERED outcome's reason lines (None when
    the outcome was not found); ``signal``: the stored signal dict (strategy_id, timeframe, symbol, ts, meta)."""
    info = _signal_info(signal)
    group = tier if tier in GROUP_KO else info.get("group")
    lev = int(leverage) if isinstance(leverage, (int, float)) and not isinstance(leverage, bool) else None
    chain = _chain(group) if group in GROUP_KO else []
    rejected = parse_downgrades(downgrades) if downgrades is not None else []
    out: dict = {"group": group, "group_ko": GROUP_KO.get(group, "모름"), "leverage": lev,
                 "score": None if info.get("score") is None else round(float(info["score"]), 2),
                 "source": info.get("source"), "tried": chain[: chain.index(lev) + 1] if lev in chain else chain,
                 "rejected": rejected, "known": downgrades is not None}
    if info.get("source") == "coin_flip":
        out["p_best"] = info.get("p_best")
    if info.get("source") == "quality" and info.get("reason"):
        out["no_score"] = info["reason"]
    out["short_ko"] = short_ko(out)
    return out


def short_ko(w: dict) -> str:
    """'50배 불가: 손절 손실 > 자금 15% · 40배 불가: ... → 30배', or '첫 후보 50배 그대로', or what is not known."""
    lev = w.get("leverage")
    if lev is None:
        return ""
    rej = [r for r in w.get("rejected") or [] if lev is None or r["lev"] > lev]
    if rej:
        return " · ".join(f"{r['lev']}배 불가: {r['ko']}" for r in rej) + f" → {lev}배"
    tried = w.get("tried") or []
    if tried and tried[0] == lev:
        return f"첫 후보 {lev}배 그대로"
    if not w.get("known"):
        return f"{lev}배 (위 단계가 안 된 이유 기록 못 찾음)"
    return f"{lev}배"


def first_reason_ko(downgrades: Any, leverage: Any) -> str:
    """The Telegram form: every rejected higher candidate, highest first, '50배 불가: 거래소 구간 한도 · 40배 불가:
    손절 손실 > 자금 15% → 30배' (name kept from the first-reason version); '' when nothing was rejected or not known."""
    try:
        lev = int(leverage)
    except (TypeError, ValueError):
        return ""
    rej = [r for r in parse_downgrades(downgrades) if r["lev"] > lev] if downgrades is not None else []
    return " · ".join(f"{r['lev']}배 불가: {r['ko']}" for r in rej) + f" → {lev}배" if rej else ""


def signal_of_trade(d: dict) -> dict:
    """The signal a closed trade came from, as levrule.signal_group reads it (trades.data has its ctx)."""
    return {"strategy_id": d.get("strategy_id"), "timeframe": d.get("timeframe"), "symbol": d.get("symbol"),
            "ts": d.get("signal_ts") or 0, "meta": {"ctx": d.get("context") or {}}}


def entered_outcomes(conn: sqlite3.Connection, account_id: str, limit: int = 2000) -> dict:
    """{(signal ts, symbol): downgrades} of one account's ENTERED outcomes (newest ``limit``; read-only)."""
    out: dict = {}
    try:
        rows = conn.execute("SELECT data FROM outcomes WHERE account_id = ? AND status = 'ENTERED' "
                            "ORDER BY step_ts DESC LIMIT ?", (account_id, int(limit))).fetchall()
    except sqlite3.Error:
        return out
    for (data,) in rows:
        try:
            d = json.loads(data)
            sig = d.get("signal") or {}
            key = (int(sig.get("ts")), str(sig.get("symbol")))
        except (TypeError, ValueError, AttributeError):
            continue
        out.setdefault(key, (d.get("detail") or {}).get("downgrades") or [])
    return out


def latest_entered(conn: sqlite3.Connection, account_id: str, symbol: str, signal_ts: Optional[int] = None):
    """The downgrades of the account's ENTERED outcome for this signal (or its newest one on ``symbol``); None
    when not found."""
    try:
        rows = conn.execute("SELECT data FROM outcomes WHERE account_id = ? AND status = 'ENTERED' AND symbol = ? "
                            "ORDER BY step_ts DESC LIMIT 5", (account_id, symbol)).fetchall()
    except sqlite3.Error:
        return None
    for (data,) in rows:
        try:
            d = json.loads(data)
        except (TypeError, ValueError):
            continue
        sig = d.get("signal") or {}
        if signal_ts is None or int(sig.get("ts") or -1) == int(signal_ts):
            return (d.get("detail") or {}).get("downgrades") or []
    return None


def for_trade(d: dict, outcomes: Optional[dict] = None) -> dict:
    """``explain`` of one closed trade (trades.data); ``outcomes``: ``entered_outcomes`` of its account."""
    key = (int(d.get("signal_ts") or 0), str(d.get("symbol")))
    dg = outcomes.get(key) if outcomes is not None else None
    return explain(d.get("tier"), d.get("leverage"), dg, signal_of_trade(d))


def for_position(conn: Optional[sqlite3.Connection], account_id: str, p: dict) -> dict:
    """``explain`` of an open position (the engine snapshot's position dict, which holds its signal)."""
    sig = p.get("signal") if isinstance(p.get("signal"), dict) else None
    dg = None
    if conn is not None:
        dg = latest_entered(conn, account_id, p.get("symbol"), (sig or {}).get("ts"))
    return explain(p.get("tier"), p.get("leverage"), dg, sig)


def compact(w: dict) -> dict:
    """The few fields the dashboard shows."""
    return {k: w.get(k) for k in ("group", "group_ko", "score", "source", "leverage", "short_ko", "p_best", "no_score")
            if w.get(k) is not None}


def mix(rows: Iterable[dict]) -> dict:
    """{"by_leverage": {lev: n}, "why_lower": {lev: {code: n}}} of entries (rows with "leverage" and "rejected"):
    for each leverage below a group's first candidate, how often each reason stopped the first candidate."""
    by: dict = {}
    why: dict = {}
    for w in rows:
        lev = w.get("leverage")
        if lev is None:
            continue
        by[lev] = by.get(lev, 0) + 1
        rej = [r for r in w.get("rejected") or [] if r["lev"] > lev]
        if rej:
            c = rej[0]["code"]
            why.setdefault(lev, {})[c] = why.setdefault(lev, {}).get(c, 0) + 1
        elif (w.get("tried") or [lev])[0] != lev:
            why.setdefault(lev, {})["unknown"] = why.setdefault(lev, {}).get("unknown", 0) + 1
    return {"by_leverage": {str(k): v for k, v in sorted(by.items(), key=lambda kv: -kv[0])},
            "why_lower": {str(k): v for k, v in sorted(why.items(), key=lambda kv: -kv[0])}}

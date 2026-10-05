"""그림자 비교 additions (분석 › 그림자 비교 and the strategy page; ana8B). Read-only, descriptive, no verdict.

1. ``limit_entry``: the '지정가 진입' block of /api/analysis/shadows. The nightly check (paperbot/daily3.py
   ``shadows``) writes one kind 'limit' row per signal: a resting limit order 0.25 ATR better than the reference price,
   good for one bar, run alone on the account's own engine; a filled one pays the maker fee and no entry slippage
   (its ``roe`` is that net ROE). The same signal's market entry is the kind 'base' row of the trade the account
   really took (obsshadows.trade_shadows; same key tail ``<account>|<symbol>|<bar close>``). Per group (기존 36 /
   딥시크 / 5분 단타), since the run start: signals, fill rate, the filled limit shadows' mean net ROE next to the
   same signals' base, and the share and the base result of the signals a limit order would have missed.
   ROE (ratios) and counts only: no money. DeepSeek is counted only (owners' D11: its P&L stays in its own group
   view; CONTRACT.md §1): its cell keeps the counts and shares (``COUNT_KEYS``), never an ROE.

2. ``strategy_view``: /api/analysis/shadows?strategy=<name>: that strategy's rows of
   riskreward.shadow_summary(strategies=[name]) (``sh["strategies"][name]``, the same cells as the pooled view) and
   its 5-year leverage x stop-width cells of research/levstop (agents.levstop.load, already used by the pooled
   view's 5-year lines) for the live timeframes, the 30x and 50x arms. Only the 36 core strategies have both.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Optional

LIMIT_GROUPS = ("core", "ds200", "reel")
COUNTED_ONLY = ("ds200",)          # owners' D11: DeepSeek is counted here, its P&L (ROE too) only in its own group view
COUNT_KEYS = ("signals", "filled", "fill_rate", "filled_resolved", "not_entered", "open", "paired",
              "paired_better_share", "missed", "missed_share", "missed_traded", "small")
GROUP_KO = {"core": "기존 36", "ds200": "딥시크", "reel": "5분 단타"}
SMALL_N = 10                        # riskreward.SMALL_N: fewer paired signals are marked small
LIVE_TFS = ("15m", "30m", "1h", "4h")
LEVSTOP_ARMS = ("30|1.5", "30|2.0", "30|2.5", "30|3.0", "50|1.5", "50|2.0", "50|2.5", "50|3.0")
LEVSTOP_KEYS = ("trades", "mean_roe", "mean_eq", "win_rate", "liq_share")
LIMIT_NOTE = ("밤 점검이 신호마다 '기준 가격보다 0.25 ATR 유리한 지정가를 한 봉 동안 걸어 뒀다면'을 따로 계산한 기록 "
              "(체결되면 메이커 수수료, 진입 미끄러짐 없음). 같은 신호의 실제 시장가 진입(base)과 ROE로 나란히 봄. "
              "놓침 = 지정가가 닿지 않은 신호, 그 결과 = 그 신호의 실제 시장가 거래 ROE. 설명용, 판정 아님")


def _utc_day(ms: int) -> str:
    import datetime as _dt
    return _dt.datetime.fromtimestamp(int(ms) / 1000, _dt.timezone.utc).strftime("%Y-%m-%d")


def _mean(xs: list) -> Optional[float]:
    return round(sum(xs) / len(xs), 5) if xs else None


def _groups(paper_ro: Optional[sqlite3.Connection]) -> dict:
    """account id -> group (accounts.GROUP_OF_KIND by kind); {} when paper3.db cannot be read."""
    if paper_ro is None:
        return {}
    from ...accounts import GROUP_OF_KIND
    try:
        return {a: GROUP_OF_KIND.get(k, "other") for a, k in paper_ro.execute("SELECT account_id, kind FROM accounts")}
    except sqlite3.Error:
        return {}


def limit_cell(rows: list[tuple], base: dict) -> dict:
    """rows: (key tail, filled, roe, resolved) of one group's limit shadows; base: key tail -> base ROE (resolved)."""
    n = len(rows)
    if not n:
        return {"signals": 0, "small": True}
    filled = [r for r in rows if r[1]]
    open_ = sum(1 for r in rows if not r[3])
    done = [r for r in filled if r[3] and r[2] is not None]
    pairs = [(r[2], base[r[0]]) for r in done if r[0] in base]
    missed = [r for r in rows if not r[1] and r[3]]
    missed_base = [base[r[0]] for r in missed if r[0] in base]
    out = {"signals": n, "filled": len(filled), "fill_rate": round(len(filled) / n, 4),
           "filled_mean_roe": _mean([r[2] for r in done]), "filled_resolved": len(done),
           "not_entered": sum(1 for r in filled if r[3] and r[2] is None), "open": open_,
           "paired": len(pairs), "paired_limit_roe": _mean([p[0] for p in pairs]),
           "paired_base_roe": _mean([p[1] for p in pairs]),
           "paired_diff_roe": (_mean([p[0] - p[1] for p in pairs]) if pairs else None),
           "paired_better_share": (round(sum(1 for a, b in pairs if a > b + 1e-12) / len(pairs), 3) if pairs else None),
           "missed": len(missed), "missed_share": round(len(missed) / n, 4),
           "missed_traded": len(missed_base), "missed_base_roe": _mean(missed_base),
           "missed_base_win_share": (round(sum(1 for x in missed_base if x > 0) / len(missed_base), 3)
                                     if missed_base else None)}
    if len(pairs) < SMALL_N:
        out["small"] = True
    return out


def limit_entry(daily_ro: Optional[sqlite3.Connection], paper_ro: Optional[sqlite3.Connection], since_ms: int,
                until_ms: int) -> dict:
    """The '지정가 진입' block: per group (LIMIT_GROUPS) ``limit_cell`` over the limit shadows of the run so far."""
    out: dict = {"title": "지정가 진입", "note": LIMIT_NOTE, "group_ko": GROUP_KO, "order": list(LIMIT_GROUPS),
                 "groups": {g: {"signals": 0, "small": True} for g in LIMIT_GROUPS}, "signals": 0}
    if daily_ro is None:
        out["error"] = "daily3.db 없음"
        return out
    gmap = _groups(paper_ro)
    lo, hi = _utc_day(since_ms) if since_ms else "0000-00-00", _utc_day(max(until_ms - 1, 0))
    try:
        got = daily_ro.execute("SELECT key, kind, account_id, filled, roe, resolved FROM shadows "
                               "WHERE day >= ? AND day <= ? AND kind IN ('limit', 'base')", (lo, hi)).fetchall()
    except sqlite3.Error as exc:
        out["error"] = f"daily3.db shadows를 읽지 못함: {type(exc).__name__}"
        return out
    base: dict = {}
    per: dict = {g: [] for g in LIMIT_GROUPS}
    for key, kind, aid, filled, roe, resolved in got:
        tail = str(key).split("|", 1)[-1]
        if kind == "base":
            if resolved and roe is not None:
                base[tail] = float(roe)
            continue
        g = gmap.get(aid) if gmap else None
        if g in per:
            per[g].append((tail, int(filled or 0), None if roe is None else float(roe), int(resolved or 0)))
    out["groups"] = {g: limit_cell(rs, base) for g, rs in per.items()}
    for g in COUNTED_ONLY:
        out["groups"][g] = {**{k: v for k, v in out["groups"][g].items() if k in COUNT_KEYS}, "counted_only": True}
    out["signals"] = sum(len(rs) for rs in per.values())
    out["days"] = [lo, hi]
    return out


# ---------------------------------------------------------------- one strategy (?strategy=)
def levstop_cells(strategy: str, doc: Any = None) -> dict:
    """The 5-year leverage x stop-width cells of one strategy for the live timeframes (30x and 50x arms)."""
    from ...agents import levstop as LS
    doc = LS.load() if doc is None else doc
    if not isinstance(doc, dict):
        return {"error": "5년 레버리지·손절 비교 결과 파일 없음 (research/levstop/out/levstop.json)"}
    cols = list(doc.get("columns") or [])
    idx = {k: cols.index(k) for k in (*LEVSTOP_KEYS, "bust_p1", "bust_p2") if k in cols}
    cells = doc.get("cells") or {}
    by_tf: dict = {}
    for tf in LIVE_TFS:
        c = cells.get(f"{strategy}|{tf}")
        if not isinstance(c, dict):
            continue
        row = {}
        for arm in LEVSTOP_ARMS:
            v = c.get(arm)
            if not isinstance(v, list):
                continue
            cell = {k: v[i] for k, i in idx.items() if i < len(v)}
            busts = [cell.pop(k) for k in ("bust_p1", "bust_p2") if k in cell]
            cell["busts"] = sum(1 for b in busts if b)
            cell["periods"] = len(busts)
            row[arm] = cell
        if row:
            by_tf[tf] = row
    return {"arms": list(LEVSTOP_ARMS), "by_tf": by_tf, "current_arm": doc.get("current_arm"),
            "generated": doc.get("generated"), "source": "research/levstop (PREREG_LEVSTOP.md, out/levstop.json)",
            "note": ("5년(2021-08~2026-09) 코드 계산. 배수 고정: 모든 신호가 그 배수로 들어감. 평균은 신호마다 따로, "
                     "파산은 기간마다 $5,000 계좌 하나(기간 2개). 설명용, 판정 아님")}


def strategy_view(paper_db: str, daily_db: Optional[str], now_ms: int, strategy: str) -> dict:
    """One core strategy's shadow rows (the pooled view's groups and keys) and its 5-year levstop cells."""
    from ...agents import riskreward as RR
    from ..analysis import SHADOW_GROUPS, SHADOW_KEYS, _close, ro_connect
    c = ro_connect(paper_db)
    d = ro_connect(daily_db)
    try:
        start = 0
        known = False
        if c is not None:
            try:
                from ...checkpoint import run_facts
                start = run_facts(c).get("start_ts") or 0
                known = c.execute("SELECT 1 FROM accounts WHERE kind = 'strategy' AND strategy = ? LIMIT 1",
                                  (strategy,)).fetchone() is not None
            except sqlite3.Error:
                start = 0
        # only a known core strategy is read: shadow_summary without paper3.db would group by the account id alone
        # (DeepSeek rows included), and an unknown name should not cost a full shadows scan
        sh = (RR.shadow_summary(d, c, int(start), int(now_ms), strategies=[strategy]) if d is not None and known
              else {"error": "daily3.db 없음"} if d is None
              else {"error": "paper3.db 없음"} if c is None else {})
    finally:
        _close(c, d)
    cells = ((sh.get("strategies") or {}).get(strategy) or {}) if isinstance(sh, dict) else {}
    ko = {**RR.SHADOW_KO, **RR.SHADOW_KO3, **RR.SHADOW_KO4, **RR.SHADOW_KO_M4}
    groups = []
    for key, title, variants in SHADOW_GROUPS:
        rows = [{"variant": v, "ko": ko.get(v, v), **{k: (cells.get(v) or {"trades": 0}).get(k) for k in SHADOW_KEYS
                                                     if k in (cells.get(v) or {"trades": 0})}} for v in variants]
        groups.append({"key": key, "title": title, "rows": rows})
    out = {"strategy": strategy, "core": known, "label": RR.SHADOW_LABEL, "since": int(start or 0),
           "base": cells.get("base") or {"trades": 0}, "groups": groups, "levstop": levstop_cells(strategy),
           "small_n": RR.SMALL_N,
           "note": ("밤 점검이 이 매매법 계좌(모든 봉)의 끝난 거래를 규칙 하나만 바꿔 다시 돌린 기록. 차이 = 그림자 평균 − 같은 "
                    "거래 base 평균(자금 대비). 10건 미만은 작음. 설명용, 판정 아님: 30일 규칙은 바뀌지 않음")}
    if isinstance(sh, dict) and sh.get("error"):
        out["error"] = sh["error"]
    return out

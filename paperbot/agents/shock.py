"""Shock test (가격 충격 시험, owners approved 2026-10-04): what an instantaneous price move would do to the paper
accounts' OPEN positions right now. Code only, read-only on paper3.db (the engines' state, ``state`` 'accounts',
as the dashboard reads open positions; the newest ``live_bars`` close per coin as the price now). The staff read
these numbers; nothing here trades or changes an account, and it is not a verdict.

The move: every coin (one at a time) and all coins together jump by -20 / -10 / -5 / +5 / +10 / +20% between two
prices (a gap), and the engine's own exit rules are applied at the shocked price, in the engine's order
(engine.PaperEngine.step at a bar open):
1. liquidation first: the mark price at or past the position's liquidation price (``liq_price``, computed by
   margin.liquidation_price when the position opened and when funding moved its margin) -> the whole isolated
   margin is lost (engine._liquidate);
2. else the stop (or the profit lock's stop): the price at or past it -> the stop fills at the SHOCKED price, not
   at the stop (gap-through-stop), with the engine's slippage and taker fee; a loss beyond the margin is a
   liquidation (engine._close);
3. else the position stays open and its unrealised P&L moves with the price.
Mark price = last price at the shock (one price per coin). Change = the account's equity after (wallet + any
unrealised P&L) minus its equity now (wallet + unrealised P&L at the price now). An account whose wallet ends
below the engine's bust line (config.v3_settings().bust_below) is counted as busted by the shock.

- ``positions``  the open positions of the strategy accounts (kind 'strategy': the 144) with the price now.
- ``run``        every scenario: positions hit, liquidated, stopped, still open, the total change ($), the share
                 of the 144 accounts' equity lost, the accounts busted, the worst accounts.
- ``packet`` / ``compact`` / ``dash_view``  the Friday risk packet, the risk officer's daily view, the dashboard.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Optional

SHOCKS = (-0.20, -0.10, -0.05, 0.05, 0.10, 0.20)
ALL = "ALL"
LABEL = "설명용, 판정 아님"
WORST = 5


def _f(x: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return v if v == v else default


def _r(x: Optional[float], n: int = 2) -> Optional[float]:
    return None if x is None else round(float(x), n)


def _settings() -> dict:
    from ..config import v3_settings
    s = v3_settings()
    return {"taker_fee": float(s.taker_fee), "slippage_frac": float(s.slippage_frac), "bust_below": float(s.bust_below)}


def _engines(paper_ro: sqlite3.Connection) -> tuple[Optional[int], dict]:
    try:
        r = paper_ro.execute("SELECT ts, data FROM state WHERE k = 'accounts'").fetchone()
        return (int(r[0]), (json.loads(r[1]) or {}).get("engines", {})) if r else (None, {})
    except (sqlite3.Error, TypeError, ValueError):
        return None, {}


def prices_now(paper_ro: sqlite3.Connection, engines: dict, symbols: set) -> dict:
    """{symbol: (price, source)}: the newest live_bars close (LAST), else the newest mark an engine saw, else
    None (the positions of that coin then use their entry price)."""
    out: dict = {}
    try:
        for sym, close, ts in paper_ro.execute(
                "SELECT b.symbol, b.close, b.ts FROM live_bars b JOIN (SELECT symbol, MAX(ts) AS t FROM live_bars "
                "GROUP BY symbol) m ON m.symbol = b.symbol AND m.t = b.ts"):
            if sym in symbols and _f(close):
                out[sym] = (float(close), "live_bars")
    except sqlite3.Error:
        pass
    for sym in symbols - set(out):
        marks = [_f((e.get("last_mark") or {}).get(sym)) for e in engines.values() if isinstance(e, dict)]
        marks = [m for m in marks if m]
        if marks:
            out[sym] = (max(set(marks), key=marks.count), "engine_mark")
    return out


def positions(paper_ro: Optional[sqlite3.Connection], kinds: tuple = ("strategy",)) -> dict:
    """{"ts", "positions": [...], "equity_total", "accounts", "prices"}: every open position of the accounts of
    ``kinds`` with its account's wallet, and the total equity (wallet + unrealised) of all those accounts."""
    if paper_ro is None:
        return {"error": "paper3.db 없음"}
    try:
        meta = {a: (s, tf) for a, s, tf in paper_ro.execute(
            f"SELECT account_id, strategy, timeframe FROM accounts WHERE kind IN ({','.join('?' * len(kinds))})", kinds)}
    except sqlite3.Error as exc:
        return {"error": f"paper3.db를 읽지 못함: {type(exc).__name__}"}
    ts, eng = _engines(paper_ro)
    raw = []
    for aid, e in eng.items():
        if aid not in meta or not isinstance(e, dict) or e.get("bust"):
            continue
        p = e.get("position")
        if not isinstance(p, dict) or not p.get("symbol"):
            continue
        raw.append((aid, e, p))
    px = prices_now(paper_ro, eng, {p["symbol"] for _a, _e, p in raw})
    out = []
    for aid, e, p in raw:
        side = 1 if _f(p.get("side"), 0) > 0 else -1
        entry = _f(p.get("entry_price"), 0.0)
        price, src = px.get(p["symbol"], (entry, "entry"))
        out.append({"account": aid, "strategy": meta[aid][0], "timeframe": meta[aid][1], "symbol": p["symbol"],
                    "side": side, "qty": _f(p.get("qty"), 0.0), "entry": entry, "margin": _f(p.get("margin"), 0.0),
                    "stop": _f(p.get("stop_price")), "liq": _f(p.get("liq_price")), "lock_roe": p.get("lock_roe"),
                    "leverage": p.get("leverage"), "wallet": _f(e.get("wallet"), 0.0), "price": price,
                    "price_source": src})
    eq_total = 0.0
    for aid in meta:
        e = eng.get(aid) or {}
        w = _f(e.get("wallet"))
        if w is None:
            continue
        p = e.get("position") if not e.get("bust") else None
        if isinstance(p, dict) and p.get("symbol"):
            side = 1 if _f(p.get("side"), 0) > 0 else -1
            price = px.get(p["symbol"], (_f(p.get("entry_price"), 0.0), ""))[0]
            w += side * _f(p.get("qty"), 0.0) * (price - _f(p.get("entry_price"), 0.0))
        eq_total += w
    return {"ts": ts, "positions": out, "equity_total": eq_total, "accounts": len(meta),
            "prices": {s: {"price": v[0], "source": v[1]} for s, v in sorted(px.items())}}


def apply(pos: dict, shock: float, s: dict) -> dict:
    """One position under an instantaneous move of ``shock`` (0.10 = +10%) from its price now, by the engine's
    rules at a gapped bar open (module docstring). Returns the outcome and the account's equity change."""
    side, qty, entry, margin = pos["side"], pos["qty"], pos["entry"], pos["margin"]
    ref = pos["price"]
    P = ref * (1.0 + shock)
    eq_before = pos["wallet"] + side * qty * (ref - entry)
    liq, stop = pos.get("liq"), pos.get("stop")
    out = "open"
    if liq is not None and (P - liq) * side <= 0:
        wallet = pos["wallet"] - margin
        eq_after, out = wallet, "liquidated"
    elif stop is not None and (P - stop) * side <= 0:
        fill = P * (1.0 - side * s["slippage_frac"])
        gross = side * qty * (fill - entry)
        if gross < -margin:
            wallet, out = pos["wallet"] - margin, "liquidated"
        else:
            wallet, out = pos["wallet"] + gross - qty * fill * s["taker_fee"], "stopped"
        eq_after = wallet
    else:
        wallet = pos["wallet"]
        eq_after = wallet + side * qty * (P - entry)
    return {"outcome": out, "change": eq_after - eq_before, "equity_before": eq_before, "equity_after": eq_after,
            "busted": out != "open" and wallet < s["bust_below"]}


def run(book: dict, shocks=SHOCKS, s: Optional[dict] = None, worst: int = WORST) -> list[dict]:
    """Every scenario (each coin with a position, then all coins together) x ``shocks``."""
    s = s or _settings()
    pos = book.get("positions") or []
    total = float(book.get("equity_total") or 0.0)
    coins = sorted({p["symbol"] for p in pos})
    rows = []
    for coin in coins + [ALL]:
        hit = [p for p in pos if coin == ALL or p["symbol"] == coin]
        for sh in shocks:
            res = [(p, apply(p, sh, s)) for p in hit]
            change = sum(r["change"] for _p, r in res)
            by_acct: dict = {}
            for p, r in res:
                by_acct[p["account"]] = by_acct.get(p["account"], 0.0) + r["change"]
            bad = sorted(((a, c) for a, c in by_acct.items() if c < 0), key=lambda x: x[1])[:worst]
            rows.append({"coin": coin.replace("USDT", "") if coin != ALL else ALL, "shock": sh,
                         "positions": len(hit),
                         "liquidated": sum(1 for _p, r in res if r["outcome"] == "liquidated"),
                         "stopped": sum(1 for _p, r in res if r["outcome"] == "stopped"),
                         "open": sum(1 for _p, r in res if r["outcome"] == "open"),
                         "change_usd": _r(change), "loss_usd": _r(sum(min(0.0, r["change"]) for _p, r in res)),
                         "share_of_equity": _r(change / total, 4) if total > 0 else None,
                         "busted": sum(1 for _p, r in res if r["busted"]),
                         "worst": [{"account": a, "change_usd": _r(c)} for a, c in bad]})
    return rows


def exposure(book: dict) -> dict:
    """Per coin: longs, shorts, their margin and notional at the price now (the 144's open positions)."""
    out: dict = {}
    for p in book.get("positions") or []:
        e = out.setdefault(p["symbol"].replace("USDT", ""), {"long": 0, "short": 0, "margin": 0.0, "notional": 0.0})
        e["long" if p["side"] > 0 else "short"] += 1
        e["margin"] += p["margin"]
        e["notional"] += p["qty"] * p["price"]
    return {k: {**v, "margin": _r(v["margin"]), "notional": _r(v["notional"])} for k, v in sorted(out.items())}


TABLE_COLUMNS = ("positions", "liquidated", "stopped", "change_usd", "share_of_equity", "busted")
HOW_TO_READ = ("가격이 한 번에 shock(0.10 = +10%)만큼 뛰거나 떨어졌다고 보고(사이 가격 없음), 엔진 규칙을 그 가격에 그대로 적용: 먼저 "
               "청산가에 닿으면 강제청산(증거금 전부 잃음), 아니면 손절·잠금선을 지나간 포지션은 손절가가 아니라 충격 뒤 가격에 "
               "체결(갭, 슬리피지·수수료 포함), 나머지는 열린 채 평가 손익만 바뀜. coin = 그 코인만 움직임, ALL = 모든 코인이 "
               "같이 움직임. table.<코인>.<충격> = columns 순서의 숫자(positions = 영향받는 포지션 수, liquidated = 강제청산, stopped = 손절·잠금 체결). change_usd = 계좌들의 평가 자금 변화 합($, 음수 = 손실), loss_usd = 손실 난 포지션만의 합, "
               "share_of_equity = 매매법 계좌 144개 평가 자금 합 대비 비율(-0.01 = -1%), busted = 충격으로 파산선 아래로 간 계좌. "
               "가격은 지금 시세(live_bars 마지막 종가), 마크 가격 = 마지막 체결가로 가정")


def packet(paper_ro: Optional[sqlite3.Connection], worst: int = WORST) -> dict:
    """The Friday risk packet's section: exposure, every scenario (``table``: coin -> shock -> the numbers in
    ``columns`` order), the worst accounts of the all-coin ±20% moves."""
    book = positions(paper_ro)
    if book.get("error"):
        return {"error": book["error"], "label": LABEL}
    rows = run(book, worst=worst)
    table: dict = {}
    for r in rows:
        table.setdefault(r["coin"], {})[f"{r['shock']:+.0%}"] = [r[k] for k in TABLE_COLUMNS]
    out = {"label": LABEL, "as_of": book["ts"], "open_positions": len(book["positions"]),
           "equity_total": _r(book["equity_total"]), "exposure": exposure(book),
           "table": table, "columns": list(TABLE_COLUMNS),
           "worst_accounts": {f"{ALL} {r['shock']:+.0%}": r["worst"] for r in rows
                              if r["coin"] == ALL and abs(r["shock"]) >= 0.2},
           "how_to_read": HOW_TO_READ,
           "note": "코드 계산(설명용, 판정 아님). 실제 급변에서는 가격이 여러 번에 나눠 움직이고 마크·마지막 가격이 다를 수 있음"}
    if not book["positions"]:
        out["note"] = "지금 열린 포지션이 없음: 충격을 받을 것이 없음. " + out["note"]
    return out


def compact(paper_ro: Optional[sqlite3.Connection]) -> dict:
    """The risk officer's daily view: open positions per coin and the all-coin ±10% / ±20% moves, and the
    worst single scenario."""
    book = positions(paper_ro)
    if book.get("error"):
        return {"error": book["error"], "label": LABEL}
    rows = run(book, worst=3)
    allc = {f"{r['shock']:+.0%}": {k: r[k] for k in ("liquidated", "stopped", "change_usd", "share_of_equity",
                                                     "busted")}
            for r in rows if r["coin"] == ALL and abs(r["shock"]) >= 0.1}
    worst = min(rows, key=lambda r: r["change_usd"] or 0.0) if rows else None
    return {"open_positions": len(book["positions"]), "exposure": exposure(book), "all_coins": allc,
            "worst_scenario": None if worst is None else {k: worst[k] for k in ("coin", "shock", "liquidated",
                                                                                 "stopped", "change_usd")},
            "note": ("코드 계산: 지금 열린 포지션에 가격이 한 번에 ±10%·±20% 움직이면(갭: 손절은 충격 뒤 가격에 체결, 청산가를 "
                     "지나면 강제청산) 계좌 144개 평가 자금이 얼마나 바뀌는지(share_of_equity, -0.01 = -1%). 설명용, 판정 아님")}


def dash_view(paper_ro: sqlite3.Connection) -> dict:
    """The dashboard's table: one row per scenario (coin x shock) with the counts and dollars, the prices used."""
    book = positions(paper_ro)
    if book.get("error"):
        return {"error": book["error"]}
    return {"as_of": book["ts"], "open_positions": len(book["positions"]), "equity_total": _r(book["equity_total"]),
            "prices": book["prices"], "exposure": exposure(book), "rows": run(book), "shocks": list(SHOCKS),
            "how_to_read": HOW_TO_READ, "label": LABEL}

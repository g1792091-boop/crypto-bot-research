"""Wins against losses, and the best against the worst strategies (owners' choice 2026-10-03). Code only.

- ``win_loss_compare(cards)``: the closed trades of one strategy (cards.card dicts, wins and losses) split by coin,
  side, timeframe, entry session (Korea time), weekday/weekend and market regime at entry: trades, wins, losses,
  win rate and P&L per group, plus how wins and losses were held. The staff read where losses gather and wins do
  not; groups under ``min_n`` trades are marked as too small to mean anything.
- ``ranking(conn, ...)``: the strategies ranked by the P&L of their four timeframe accounts (5m removed 2026-10-04) (wallet against the
  starting equity), the top and bottom ``k`` with their own comparison, against the coin-flip accounts.

Descriptive only: nothing here changes an account. A strategy's 30-day verdict is the checkpoint's (coin flips x
2,000), not this ranking.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Iterable, Optional

from ..config import V3_TRADE_TFS
from ..sessions import session_of

SESSION_KO = {"asia": "아시아장(09-16)", "europe": "유럽장(16-22)", "us": "미국장(22-05)", "dawn": "새벽(05-09)"}
KST_MS = 9 * 3_600_000


def _kst(ms: int) -> tuple[int, int]:
    """(hour, weekday 0=Mon) in Korea time."""
    import datetime as dt
    d = dt.datetime.fromtimestamp((ms + KST_MS) / 1000, dt.timezone.utc)
    return d.hour, d.weekday()


def _cell(cs: list[dict], min_n: int) -> dict:
    n = len(cs)
    w = sum(1 for c in cs if c["pnl"] > 0)
    out = {"trades": n, "wins": w, "losses": sum(1 for c in cs if c["pnl"] < 0),
           "win_rate": round(w / n, 3) if n else None, "pnl": round(sum(c["pnl"] for c in cs), 2)}
    if n < min_n:
        out["small"] = True
    return out


def win_loss_compare(cards: Iterable[dict], min_n: int = 10) -> dict:
    cs = [c for c in cards if c.get("pnl") is not None]
    if not cs:
        return {"trades": 0}
    keys = {
        "by_coin": lambda c: c["symbol"].replace("USDT", ""),
        "by_side": lambda c: c.get("side_ko") or ("롱" if c.get("side", 0) > 0 else "숏"),
        "by_timeframe": lambda c: c.get("timeframe") or "?",
        "by_session": lambda c: SESSION_KO[session_of(_kst(c["entry_time"])[0])],
        "by_weekday": lambda c: "주말" if _kst(c["entry_time"])[1] >= 5 else "평일",
        "by_regime": lambda c: c.get("regime_ko") or "모름",
    }
    out: dict = {"trades": len(cs), "all": _cell(cs, min_n)}
    for name, key in keys.items():
        groups: dict = {}
        for c in cs:
            try:
                groups.setdefault(key(c), []).append(c)
            except (KeyError, TypeError, ValueError):
                continue
        out[name] = {k: _cell(v, min_n) for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1]))}
    wins = [c for c in cs if c["pnl"] > 0]
    losses = [c for c in cs if c["pnl"] < 0]

    def avg(xs):
        xs = [x for x in xs if x is not None]
        return round(sum(xs) / len(xs), 3) if xs else None
    out["held"] = {"win_hold_min": avg([c.get("hold_min") for c in wins]),
                   "loss_hold_min": avg([c.get("hold_min") for c in losses]),
                   "loss_best_roe": avg([c.get("best_roe") for c in losses]),
                   "losses_that_touched_first_lock": sum(1 for c in losses if c.get("touched_first_lock")),
                   "win_exit_reasons": _count(c.get("reason_ko") for c in wins),
                   "loss_exit_reasons": _count(c.get("reason_ko") for c in losses)}
    out["note"] = (f"코드 집계. 거래 {min_n}건 미만 칸(small)은 우연일 수 있어 결론 없이 가설로만. "
                   "이긴 거래와 진 거래가 갈리는 칸을 찾되, 한 칸만 보고 규칙을 바꾸자고 하지 않음")
    return out


def _count(xs) -> dict:
    out: dict = {}
    for x in xs:
        if x:
            out[x] = out.get(x, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def wallets(conn: sqlite3.Connection) -> dict:
    """{account_id: (kind, strategy, timeframe, wallet or None, bust)} from accounts + the runner's snapshot."""
    r = conn.execute("SELECT data FROM state WHERE k = 'accounts'").fetchone()
    eng = (json.loads(r[0]) or {}).get("engines", {}) if r else {}
    out = {}
    for aid, kind, strat, tf in conn.execute("SELECT account_id, kind, strategy, timeframe FROM accounts"):
        e = eng.get(aid) or {}
        out[aid] = (kind, strat, tf, e.get("wallet"), bool(e.get("bust")))
    return out


def ranking(conn: sqlite3.Connection, initial: float, round_trip: float, k: int = 3, min_n: int = 10,
            names_ko: Optional[dict] = None, cards_fn=None) -> dict:
    """Top and bottom ``k`` strategies by the summed P&L of their accounts (wallet - initial), with each one's
    win/loss comparison and tag differences, and the coin-flip accounts for scale."""
    from ..cards import cards_from_db, tag_stats
    cards_fn = cards_fn or (lambda s: cards_from_db(conn, round_trip, strategy=s, losses_only=False, limit=2000,
                                                    kinds=("strategy",)))
    w = wallets(conn)
    per: dict = {}
    flips = []
    for aid, (kind, strat, tf, wal, bust) in w.items():
        wal = initial if wal is None else float(wal)
        if kind == "random":
            flips.append({"account": aid, "timeframe": tf, "pnl": round(wal - initial, 2), "bust": bust})
            continue
        if kind != "strategy":
            continue
        s = per.setdefault(strat, {"strategy": strat, "name_ko": (names_ko or {}).get(strat, strat), "pnl": 0.0,
                                   "accounts": {}, "busts": 0})
        s["pnl"] += wal - initial
        s["accounts"][tf] = round(wal - initial, 2)
        s["busts"] += int(bust)
    # every closed trade of each strategy's own accounts (the compare tables use at most the latest 2000)
    try:
        closed = {s: {"trades": int(n), "wins": int(w or 0), "losses": int(lo or 0),
                      "win_rate": round((w or 0) / n, 3) if n else None}
                  for s, n, w, lo in conn.execute(
                      "SELECT a.strategy, COUNT(*), SUM(t.pnl > 0), SUM(t.pnl < 0) FROM trades t JOIN accounts a "
                      "ON a.account_id = t.account_id WHERE a.kind = 'strategy' GROUP BY a.strategy")}
    except sqlite3.Error:                       # no trades table yet: the compare tables' counts stand in
        closed = {}
    for s in per.values():
        if s["strategy"] in closed:
            s["closed"] = closed[s["strategy"]]
    rows = sorted(per.values(), key=lambda r: -r["pnl"])
    for r in rows:
        # the sum is over the strategy's timeframe accounts (4): per account it compares with one coin flip
        r["pnl_per_account"] = round(r["pnl"] / max(1, len(r["accounts"])), 2)
        r["pnl"] = round(r["pnl"], 2)
    pick = rows[:k] + [r for r in rows[-k:] if r not in rows[:k]][::-1]
    out = []
    for r in pick:
        cs = cards_fn(r["strategy"])
        tags = [t for t in tag_stats(cs) if (t["wins"] or t["losses"])]
        out.append({**r, "rank": rows.index(r) + 1, "of": len(rows), "group": "상위" if r in rows[:k] else "하위",
                    "compare": win_loss_compare(cs, min_n),
                    "best_trade": _trade(max(cs, key=lambda c: c["pnl"])) if cs else None,
                    "worst_trade": _trade(min(cs, key=lambda c: c["pnl"])) if cs else None,
                    "tags": [{"tag": t["tag"], "wins": t["wins"], "losses": t["losses"],
                              "win_share": None if t["win_share"] is None else round(t["win_share"], 3),
                              "loss_share": None if t["loss_share"] is None else round(t["loss_share"], 3)}
                             for t in tags[:6]]})
    flips.sort(key=lambda f: -f["pnl"])
    mean = round(sum(f["pnl"] for f in flips) / len(flips), 2) if flips else None
    return {"strategies": len(rows), "picked": out,
            "coin_flips": {"best": flips[:3], "worst": flips[-3:][::-1], "mean_pnl": mean,
                           "accounts_per_strategy": len(V3_TRADE_TFS),
                           "mean_pnl_per_strategy": None if mean is None else round(mean * len(V3_TRADE_TFS), 2)},
            "note": "순위는 4개 봉 계좌 손익 합계(코드 집계), pnl_per_account는 그 계좌당 평균. 동전 봇 mean_pnl은 계좌 "
                    "하나의 평균이라 pnl_per_account와 비교함(mean_pnl_per_strategy = 매매법 하나의 봉 계좌 4개 합으로 친 값). 30일 판정은 체크포인트"
                    "(동전 봇 2,000개 비교)가 함. 거래 30건 미만이면 상위·하위 모두 운일 수 있음"}


def _trade(c: dict) -> dict:
    return {"account": c["account_id"], "coin": c["symbol"].replace("USDT", ""), "side": c.get("side_ko"),
            "pnl": round(c["pnl"], 2), "roe": round(c["roe"], 4), "reason": c.get("reason_ko"),
            "regime": c.get("regime_ko"), "tags": c.get("tags")}

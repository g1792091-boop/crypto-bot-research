"""Losing streaks in context (분석 › 손익비·위험, ana8B): is a run of N losses in a row unusual at this win rate?

Read-only on paper3.db (trades, accounts). For each group (기존 36 / 딥시크 / 5분 단타 / 추가 계좌) and each of its
accounts since the run start: the longest losing run and the run going on now (survival.losing_streak: a loss is
P&L <= 0, in exit order), the account's own win rate, and the chance that n trades at that win rate hold a losing
run at least that long somewhere: P(L_n >= k), L_n = the longest run of losses in n independent trades that each lose
with probability q = 1 - win rate.

The formula (Schilling, M. F. (1990), "The Longest Run of Heads", The College Mathematics Journal 21(3), 196-207;
Feller, An Introduction to Probability Theory, vol. 1, ch. XIII.7): with A_n(k) = P(no losing run of k in n trades),
A_n(k) = 1 for n < k, and for n >= k

    A_n(k) = sum_{j=0}^{k-1} q^j * p * A_{n-j-1}(k)      (j losses, then the first win; p = 1 - q)

and P(L_n >= k) = 1 - A_n(k). That is the same as walking a chain over "losses in a row now" 0..k-1 with k absorbing; ``p_longest_run_ge`` does the
chain exactly (n * k steps). The trades of one account are treated as independent with one fixed win rate: a real
strategy's losses can cluster, so the number is a yardstick, not a test. With many accounts some long run is
expected somewhere: ``any_account`` is 1 - prod(1 - P_i) over the group's accounts (each with its own n and win rate).

The coin flips' longest runs are the band: min / median / max over the coin-flip accounts with trades (the 15m-4h flips
for 기존 36 / 딥시크 / 추가 계좌, the 5m flips for the 5분 단타, which run its exits). DeepSeek rows carry no
account id (group level only, CONTRACT.md §1.3). Counts and rates only: no money for any group (DeepSeek is counted;
CONTRACT.md §1). Meaningful from ``MIN_TRADES`` closed trades per account.
"""
from __future__ import annotations

import sqlite3
from statistics import median
from typing import Optional

GROUPS = ("core", "ds200", "reel", "extra")
GROUP_KO = {"core": "기존 36", "ds200": "딥시크", "reel": "5분 단타", "extra": "추가 계좌"}
MIN_TRADES = 20                      # agents/survival.MIN_TRADES
TOP = 3                              # accounts listed per group (longest runs first)
UNNAMED = ("ds200",)                 # groups shown without account names (DeepSeek: group level only)
CITE = ("Schilling (1990) 'The Longest Run of Heads', College Math. J. 21(3):196-207 · Feller 1권 XIII.7: "
        "n번 중 연속 k번 이상 질 확률을 '지금 몇 번 연속 졌나' 상태로 정확히 계산")


def p_longest_run_ge(n: int, q: float, k: int) -> float:
    """P(the longest run of losses in n independent trades, each a loss with probability q, is >= k). Exact."""
    n, k = int(n), int(k)
    if k <= 0:
        return 1.0
    if n < k or q <= 0.0:
        return 0.0
    if q >= 1.0:
        return 1.0
    p = 1.0 - q
    state = [0.0] * k                # state[j]: probability of j losses in a row now and no run of k yet
    state[0] = 1.0
    hit = 0.0
    for _ in range(n):
        nxt = [0.0] * k
        nxt[0] = p * sum(state)
        for j in range(k - 1):
            nxt[j + 1] = state[j] * q
        hit += state[k - 1] * q
        state = nxt
    return min(1.0, max(0.0, hit))


def runs(pnls: list) -> dict:
    """{"n", "wins", "longest", "now"} of one account's P&L list in exit order (loss: P&L <= 0)."""
    best = cur = wins = 0
    for x in pnls:
        if x is not None and x <= 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
            wins += 1
    return {"n": len(pnls), "wins": wins, "longest": best, "now": cur}


def _acct_row(aid: str, r: dict) -> dict:
    n = r["n"]
    wr = r["wins"] / n if n else None
    q = 1.0 - wr if wr is not None else None
    out = {"account_id": aid, "trades": n, "win_rate": None if wr is None else round(wr, 4),
           "longest": r["longest"], "now": r["now"], "small": n < MIN_TRADES}
    if q is not None:
        out["p_longest"] = round(p_longest_run_ge(n, q, r["longest"]), 4) if r["longest"] else None
        out["p_now"] = round(p_longest_run_ge(n, q, r["now"]), 4) if r["now"] else None
    return out


def band(vals: list) -> Optional[dict]:
    if not vals:
        return None
    return {"accounts": len(vals), "min": min(vals), "median": median(vals), "max": max(vals)}


def streak_context(paper_db: str, now_ms: int) -> dict:
    """Per group: accounts, the longest runs (top ``TOP`` by longest, then by chance), the longest run now, the chance
    of a run that long somewhere in any of the group's accounts, and the coin flips' band. Never raises."""
    from ..analysis import _close, ro_connect
    out: dict = {"groups": {}, "order": list(GROUPS), "group_ko": GROUP_KO, "min_trades": MIN_TRADES, "cite": CITE,
                 "label": "설명용, 판정 아님",
                 "note": ("같은 승률이면 거래가 많을수록 긴 연패가 자연스럽게 나옵니다. 확률 = 이 계좌의 거래 수와 승률에서 "
                          "그만큼 긴 연패가 한 번이라도 나올 확률 (거래마다 독립이라고 보고 계산). 계좌가 많으면 어딘가에서 "
                          "긴 연패가 나오는 것도 자연스러움. 동전 봇의 가장 긴 연패가 비교 기준")}
    c = ro_connect(paper_db)
    if c is None:
        out["error"] = "paper3.db 없음"
        return out
    try:
        from ...accounts import GROUP_OF_KIND
        try:
            from ...checkpoint import run_facts
            start = int(run_facts(c).get("start_ts") or 0)
        except (sqlite3.Error, ValueError, TypeError):
            start = 0
        acc = {a: (GROUP_OF_KIND.get(k, "other"), tf) for a, k, tf in
               c.execute("SELECT account_id, kind, timeframe FROM accounts")}
        pn: dict = {}
        for aid, pnl in c.execute("SELECT account_id, pnl FROM trades WHERE exit_time >= ? "
                                  "ORDER BY account_id, exit_time, id", (start,)):
            pn.setdefault(aid, []).append(pnl)
    except sqlite3.Error as exc:
        out["error"] = f"paper3.db를 읽지 못함: {type(exc).__name__}"
        return out
    finally:
        _close(c)
    flips = {"5m": [], "other": []}
    per: dict = {g: [] for g in GROUPS}
    for aid, xs in pn.items():
        g, tf = acc.get(aid, ("other", ""))
        r = runs(xs)
        if g == "flip":
            flips["5m" if tf == "5m" else "other"].append(r["longest"])
        elif g in per:
            per[g].append(_acct_row(aid, r))
    for g in GROUPS:
        rows = per[g]
        total = sum(1 for a, (gg, _tf) in acc.items() if gg == g)
        cell: dict = {"accounts": total, "with_trades": len(rows), "trades": sum(r["trades"] for r in rows),
                      "enough": sum(1 for r in rows if not r["small"]),
                      "flip_band": band(flips["5m" if g == "reel" else "other"]),
                      "flip_band_ko": "5분 동전 봇" if g == "reel" else "15분~4시간 동전 봇"}
        if rows:
            top = sorted(rows, key=lambda r: (-r["longest"], r.get("p_longest") if r.get("p_longest") is not None else 1))
            cell["top"] = top[:TOP]
            now = max(rows, key=lambda r: (r["now"], -(r.get("p_now") or 1)))
            cell["now"] = now if now["now"] else None
            k = top[0]["longest"]
            if k:
                miss = 1.0
                for r in rows:
                    if r["win_rate"] is not None:
                        miss *= 1.0 - p_longest_run_ge(r["trades"], 1.0 - r["win_rate"], k)
                cell["any_account"] = {"k": k, "p": round(1.0 - miss, 4)}
            if g in UNNAMED:
                # DeepSeek: group level only (CONTRACT.md §1.3, owners' D11: no per-account pick); one unnamed row
                cell["top"] = [{**r, "account_id": None} for r in cell["top"][:1]]
                if cell["now"]:
                    cell["now"] = {**cell["now"], "account_id": None}
                cell["unnamed"] = True
        out["groups"][g] = cell
    out["flip_accounts"] = len(flips["other"]) + len(flips["5m"])
    return out

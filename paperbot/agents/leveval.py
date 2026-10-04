"""The pre-registered evaluation of leverage rule B (docs/levrule-eval.md, hashed): do 좋은 자리 ("best") entries do
better than 보통 ("normal") entries per unit of exposure? Code only, read-only on paper3.db; the same numbers go to
the Thursday 손익비 회의 (``rr.levrule``), the Friday 위험 회의 (``survival.levrule``, compact), the 30-day checkpoint
meeting (``readiness.levrule``), each strategy specialist (one line) and the dashboard's '좋은 자리 vs 보통' card.

Method (the document's sections 2-4, nothing else):
- per closed trade r = pnl / (margin x leverage) (= ROE / leverage = P&L on equity / (leverage x margin share): return
  per unit notional, net of fees, slippage and funding); group = the trade's ``tier`` ("best" / "normal");
- window: trades ENTERED in [run start, day-30 checkpoint) and closed before it (checkpoint.run_facts /
  checkpoint_ts); strategy accounts and coin-flip accounts, never the extras;
- cell = one account (strategy x timeframe, or coin flip x timeframe); eligible when both groups have >= 10 trades;
  d = mean r(best) - mean r(normal); D_s = mean d over the eligible strategy cells, D_c the same over the coin flips,
  DiD = D_s - D_c;
- week-block bootstrap (7-day blocks of entry time from the start, resampled with replacement, all accounts of a
  block together), 10,000 draws, seed 20261004; one-sided p = (#{D* <= 0} + 1) / (B + 1), a draw with nothing left
  to compute counts as <= 0;
- decision at day 30: KEEP rule B for the next 30 days only if D_s > 0 with p_s <= 0.10 AND D_s > D_c (no coin-flip
  baseline -> not met); otherwise the next window is fixed 20x / 20% for every signal.

Before day 30 everything is an interim number (``status`` "interim", "30일 판정 전 결론 없음").
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Optional

import numpy as np

DOC = "docs/levrule-eval.md"
MIN_TRADES = 10
ALPHA = 0.10
N_BOOT = 10_000
SEED = 20261004
BLOCK_DAYS = 7
DAY_MS = 86_400_000
GROUPS = ("best", "normal")
GROUP_KO = {"best": "좋은 자리", "normal": "보통"}
KINDS = ("strategy", "random")
LEVERAGES = (50, 40, 30, 20)
BEFORE_KO = "30일 판정 전 결론 없음"
LABEL = "미리 정한 방법(docs/levrule-eval.md)으로만 평가"
DECISION_KO = {"keep": "규칙 B 유지(다음 30일)", "fixed20": "다음 창은 모든 신호 20배·증거금 20% 고정"}
NOTE = ("r = 손익 ÷ (증거금 × 레버리지) = 노출 1단위당 수익(수수료·펀딩 뺀 순). 칸 = 계좌(매매법 × 봉), 두 묶음 모두 "
        "10건 이상인 칸만. D_s = 매매법 칸 평균(좋은 자리 − 보통), D_c = 동전 봇의 같은 차이, 주 단위 블록 부트스트랩 "
        "10,000번 한쪽 p. 판정(30일): D_s > 0 이고 p_s ≤ 0.10 이고 D_s > D_c면 규칙 B 유지, 아니면 다음 창 20배·20% 고정. "
        "B는 이 방법으로만 평가하고, 창 중간에는 아무것도 바꾸지 않음")


def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _r(x: Optional[float], n: int = 6) -> Optional[float]:
    return None if x is None else round(float(x), n)


def _mean(xs) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


# ---------------------------------------------------------------- the window
def window(paper_ro: sqlite3.Connection, now_ms: int) -> dict:
    """{"start", "until" (the day-30 checkpoint), "to" (min(now, until)), "decided" (now >= until)} of the run in
    paper3.db; start None when no account exists yet."""
    from ..checkpoint import checkpoint_ts, run_facts
    try:
        start = run_facts(paper_ro).get("start_ts")
    except (sqlite3.Error, TypeError, ValueError):
        start = None
    if start is None:
        return {"start": None, "until": None, "to": int(now_ms), "decided": False}
    until = checkpoint_ts(int(start), 1)
    return {"start": int(start), "until": until, "to": min(int(now_ms), until), "decided": int(now_ms) >= until}


# ---------------------------------------------------------------- reading trades
def trade_rows(paper_ro: sqlite3.Connection, since: int, until: int, kinds: tuple = KINDS,
               strategies: Optional[list] = None) -> list[dict]:
    """The closed trades entered in [since, until) and closed before ``until`` on accounts of ``kinds``: one dict
    per trade {kind, account, strategy, tf, group, lev, r, roe, eq, win, entry, signal_ts, symbol}. A trade without
    a group (not "best" / "normal": before rule B) or without margin / leverage is left out."""
    ks = list(kinds)
    sql = ("SELECT a.kind, a.account_id, a.strategy, a.timeframe, t.pnl, t.roe, t.leverage, t.equity_after, "
           "t.entry_time, t.data FROM trades t JOIN accounts a ON a.account_id = t.account_id "
           f"WHERE a.kind IN ({','.join('?' * len(ks))}) AND t.entry_time >= ? AND t.entry_time < ? AND t.exit_time < ?")
    args: list = [*ks, int(since), int(until), int(until)]
    if strategies:
        sql += f" AND a.strategy IN ({','.join('?' * len(strategies))})"
        args += list(strategies)
    out = []
    for kind, aid, strat, tf, pnl, roe, lev, eq_after, entry, data in paper_ro.execute(sql + " ORDER BY t.id", args):
        try:
            d = json.loads(data)
        except (TypeError, ValueError):
            continue
        group = d.get("tier") if isinstance(d, dict) else None
        margin, lev, pnl = _f((d or {}).get("margin")), _f(lev), _f(pnl)
        if group not in GROUPS or not margin or not lev or pnl is None:
            continue
        eq_before = (_f(eq_after) or 0.0) - pnl
        out.append({"kind": kind, "account": aid, "strategy": strat, "tf": tf, "group": group,
                    "lev": int(round(lev)), "r": pnl / (margin * lev), "roe": _f(roe),
                    "eq": pnl / eq_before if eq_before > 0 else None, "win": pnl > 0, "entry": int(entry),
                    "signal_ts": d.get("signal_ts"), "symbol": d.get("symbol")})
    return out


# ---------------------------------------------------------------- the contrast and the bootstrap
def _cells(rows: list[dict], kind: str) -> dict:
    """{account: {"best": [r], "normal": [r]}} of one kind."""
    out: dict = {}
    for t in rows:
        if t["kind"] == kind:
            out.setdefault(t["account"], {g: [] for g in GROUPS})[t["group"]].append(t)
    return out


def eligible(cells: dict, min_n: int = MIN_TRADES) -> list[str]:
    return sorted(a for a, c in cells.items() if all(len(c[g]) >= min_n for g in GROUPS))


def contrast(cells: dict, keep: list[str]) -> Optional[float]:
    """Mean over the ``keep`` cells of mean r(best) - mean r(normal); None without a cell."""
    ds = [_mean(t["r"] for t in cells[a]["best"]) - _mean(t["r"] for t in cells[a]["normal"]) for a in keep]
    return sum(ds) / len(ds) if ds else None


def _block_sums(rows: list[dict], kind: str, keep: list[str], start: int) -> tuple:
    """(sums, counts) arrays [blocks, cells, 2] of r for the eligible cells of one kind."""
    idx = {a: i for i, a in enumerate(keep)}
    nb = 1 + max((max(0, (t["entry"] - start) // (BLOCK_DAYS * DAY_MS)) for t in rows), default=0)
    s = np.zeros((nb, max(1, len(keep)), 2))
    n = np.zeros((nb, max(1, len(keep)), 2))
    for t in rows:
        if t["kind"] != kind or t["account"] not in idx:
            continue
        b = max(0, (t["entry"] - start) // (BLOCK_DAYS * DAY_MS))
        g = GROUPS.index(t["group"])
        s[b, idx[t["account"]], g] += t["r"]
        n[b, idx[t["account"]], g] += 1
    return s, n


def _boot_contrast(w: np.ndarray, s: np.ndarray, n: np.ndarray, ncells: int) -> np.ndarray:
    """D* per draw: ``w`` [B, blocks] block multiplicities."""
    if not ncells:
        return np.full(w.shape[0], np.nan)
    S = np.tensordot(w, s, axes=(1, 0))[:, :ncells, :]          # [B, cells, 2]
    N = np.tensordot(w, n, axes=(1, 0))[:, :ncells, :]
    with np.errstate(invalid="ignore", divide="ignore"):
        m = S / N
        d = m[:, :, 0] - m[:, :, 1]                               # nan where a group has no trade in the draw
        ok = ~np.isnan(d)
        cnt = ok.sum(axis=1)
        tot = np.where(ok, d, 0.0).sum(axis=1)
        return np.where(cnt > 0, tot / np.maximum(cnt, 1), np.nan)


def p_one_sided(draws: np.ndarray) -> Optional[float]:
    """(#{D* <= 0 or not computable} + 1) / (B + 1)."""
    if draws is None or not len(draws):
        return None
    bad = int(np.sum(~(draws > 0)))
    return (bad + 1) / (len(draws) + 1)


def bootstrap(rows: list[dict], keep_s: list[str], keep_c: list[str], start: int, n_boot: int = N_BOOT,
              seed: int = SEED) -> dict:
    """p_s, p_did (and p_c) by the week-block bootstrap; the same block draws for strategies and coin flips."""
    ss, ns = _block_sums(rows, "strategy", keep_s, start)
    sc, nc = _block_sums(rows, "random", keep_c, start)
    nb = max(ss.shape[0], sc.shape[0])
    if ss.shape[0] < nb:
        ss, ns = (np.concatenate([a, np.zeros((nb - a.shape[0],) + a.shape[1:])]) for a in (ss, ns))
    if sc.shape[0] < nb:
        sc, nc = (np.concatenate([a, np.zeros((nb - a.shape[0],) + a.shape[1:])]) for a in (sc, nc))
    rng = np.random.default_rng(seed)
    w = rng.multinomial(nb, np.full(nb, 1.0 / nb), size=n_boot).astype(float)       # [B, blocks]
    ds = _boot_contrast(w, ss, ns, len(keep_s))
    dc = _boot_contrast(w, sc, nc, len(keep_c))
    did = ds - dc
    return {"blocks": int(nb), "n_boot": int(n_boot), "seed": int(seed), "p_s": p_one_sided(ds) if keep_s else None,
            "p_c": p_one_sided(dc) if keep_c else None, "p_did": p_one_sided(did) if keep_s and keep_c else None}


def decide(d_s: Optional[float], p_s: Optional[float], d_c: Optional[float]) -> dict:
    """The document's section 4: {"keep": bool, "a": bool, "b": bool, "decision": "keep" | "fixed20"}."""
    a = d_s is not None and d_s > 0 and p_s is not None and p_s <= ALPHA
    b = d_s is not None and d_c is not None and d_s > d_c
    keep = bool(a and b)
    return {"a": bool(a), "b": bool(b), "keep": keep, "decision": "keep" if keep else "fixed20"}


# ---------------------------------------------------------------- group summaries
def group_stats(rows: list[dict]) -> dict:
    """trades, win rate, mean ROE, mean P&L on equity, mean r (return per unit exposure)."""
    n = len(rows)
    if not n:
        return {"trades": 0}
    out = {"trades": n, "win_rate": _r(sum(1 for t in rows if t["win"]) / n, 4),
           "mean_roe": _r(_mean(t["roe"] for t in rows), 5), "mean_eq": _r(_mean(t["eq"] for t in rows), 6),
           "mean_r": _r(_mean(t["r"] for t in rows), 7)}
    if n < MIN_TRADES:
        out["small"] = True
    return out


def by_leverage(rows: list[dict]) -> dict:
    """{lev: [trades, mean r]} of one group's trades."""
    out = {}
    for lev in sorted({t["lev"] for t in rows}, reverse=True):
        xs = [t["r"] for t in rows if t["lev"] == lev]
        out[str(lev)] = [len(xs), _r(_mean(xs), 7)]
    return out


def reweighted(flips: list[dict], mix_rows: list[dict]) -> dict:
    """The coin flips of one group at the strategy group's leverage mix: sum over leverages of (the strategies' share
    at that leverage) x (the coin flips' mean r / mean eq there); leverages the coin flips never used are left out and
    the shares renormalised (``coverage`` = the strategies' share that could be matched)."""
    tot = len(mix_rows)
    if not tot:
        return {"coverage": None}
    shares = {}
    for t in mix_rows:
        shares[t["lev"]] = shares.get(t["lev"], 0) + 1 / tot
    acc_r = acc_e = cov = 0.0
    for lev, sh in shares.items():
        xs = [t for t in flips if t["lev"] == lev]
        if not xs:
            continue
        mr, me = _mean(t["r"] for t in xs), _mean(t["eq"] for t in xs)
        acc_r += sh * mr
        acc_e += sh * (me or 0.0)
        cov += sh
    if cov <= 0:
        return {"coverage": 0.0}
    return {"mean_r": _r(acc_r / cov, 7), "mean_eq": _r(acc_e / cov, 6), "coverage": _r(cov, 3)}


def leverage_mix(paper_ro: sqlite3.Connection, rows: list[dict]) -> dict:
    """For the strategy accounts' trades of each group: how many entered at 50 / 40 / 30 / 20x and, for the ones
    below their group's first candidate, which reason stopped it (levwhy: the ENTERED outcomes' downgrades)."""
    from .. import levwhy as LW
    out = {}
    accts = sorted({t["account"] for t in rows if t["kind"] == "strategy"})
    oc = {a: LW.entered_outcomes(paper_ro, a) for a in accts}
    for g in GROUPS:
        ws = []
        for t in rows:
            if t["kind"] != "strategy" or t["group"] != g:
                continue
            dg = (oc.get(t["account"]) or {}).get((int(t.get("signal_ts") or 0), str(t.get("symbol"))))
            ws.append(LW.explain(g, t["lev"], dg))
        out[g] = LW.mix(ws)
    return out


# ---------------------------------------------------------------- the evaluation
def levrule_eval(paper_ro: Optional[sqlite3.Connection], since: Optional[int] = None, until: Optional[int] = None,
                 now_ms: Optional[int] = None, n_boot: int = N_BOOT, mix: bool = True) -> dict:
    """The full evaluation (docs/levrule-eval.md). ``since`` / ``until`` default to the run start and the day-30
    checkpoint; with ``now_ms`` before that checkpoint the window ends at now and the result is interim."""
    import time as _t
    if paper_ro is None:
        return {"error": "paper3.db 없음", "label": LABEL, "doc": DOC}
    now = int(_t.time() * 1000) if now_ms is None else int(now_ms)
    try:
        win = window(paper_ro, now)
    except sqlite3.Error as exc:
        return {"error": f"paper3.db를 읽지 못함: {type(exc).__name__}", "label": LABEL, "doc": DOC}
    start = win["start"] if since is None else int(since)
    cp = win["until"] if until is None else int(until)
    if start is None or cp is None:
        return {"status": "no_run", "status_ko": "아직 계좌 없음", "label": LABEL, "doc": DOC, "note": NOTE}
    to = min(now, cp)
    decided = now >= cp
    try:
        rows = trade_rows(paper_ro, start, to)
    except sqlite3.Error as exc:
        return {"error": f"paper3.db를 읽지 못함: {type(exc).__name__}", "label": LABEL, "doc": DOC}
    cs, cc = _cells(rows, "strategy"), _cells(rows, "random")
    ks, kc = eligible(cs), eligible(cc)
    d_s, d_c = contrast(cs, ks), contrast(cc, kc)
    boot = bootstrap(rows, ks, kc, start, n_boot) if (ks or kc) else {"p_s": None, "p_c": None, "p_did": None,
                                                                      "n_boot": n_boot, "seed": SEED}
    dec = decide(d_s, boot.get("p_s"), d_c)
    strat = [t for t in rows if t["kind"] == "strategy"]
    flips = [t for t in rows if t["kind"] == "random"]
    groups = {}
    for g in GROUPS:
        sg = [t for t in strat if t["group"] == g]
        fg = [t for t in flips if t["group"] == g]
        groups[g] = {"strategy": group_stats(sg), "coin_flips": group_stats(fg),
                     "strategy_by_leverage": by_leverage(sg), "coin_flips_by_leverage": by_leverage(fg),
                     "coin_flips_at_strategy_mix": reweighted(fg, sg)}
    out = {"label": LABEL, "doc": DOC, "status": "decided" if decided else "interim",
           "status_ko": ("30일 판정: " + DECISION_KO[dec["decision"]]) if decided else BEFORE_KO,
           "window": {"start": start, "until": cp, "to": to},
           "trades": {"strategy": len(strat), "coin_flips": len(flips)},
           "cells": {"strategy_eligible": len(ks), "strategy_total": len(cs), "coin_flips_eligible": len(kc),
                     "coin_flips_total": len(cc), "min_trades": MIN_TRADES},
           "d_s": _r(d_s, 7), "d_c": _r(d_c, 7), "did": _r(None if d_s is None or d_c is None else d_s - d_c, 7),
           "p_s": _r(boot.get("p_s"), 4), "p_c": _r(boot.get("p_c"), 4), "p_did": _r(boot.get("p_did"), 4),
           "boot": {k: boot.get(k) for k in ("blocks", "n_boot", "seed") if k in boot},
           "conditions": {"a_best_beats_normal": dec["a"], "b_beats_coin_flips": dec["b"], "alpha": ALPHA},
           "groups": groups,
           "cell_rows": {a: [len(cs[a]["best"]), len(cs[a]["normal"]),
                             _r(_mean(t["r"] for t in cs[a]["best"]) - _mean(t["r"] for t in cs[a]["normal"]), 7)]
                         for a in ks},
           "cell_columns": ["best_trades", "normal_trades", "d(좋은 자리 − 보통, r)"],
           "note": NOTE}
    if decided:
        out["decision"] = dec["decision"]
        out["decision_ko"] = DECISION_KO[dec["decision"]]
    if mix:
        try:
            out["leverage_mix"] = leverage_mix(paper_ro, rows)
        except sqlite3.Error as exc:
            out["leverage_mix"] = {"error": f"진입 기록을 읽지 못함: {type(exc).__name__}"}
    return out


# ---------------------------------------------------------------- packets
def compact(ev: dict) -> dict:
    """The Friday risk meeting's ``levrule`` (a few numbers)."""
    if ev.get("error") or ev.get("status") == "no_run":
        return {k: ev.get(k) for k in ("error", "status", "status_ko", "doc") if ev.get(k) is not None}
    g = ev.get("groups") or {}
    out = {"status": ev["status"], "status_ko": ev["status_ko"], "doc": DOC,
           "trades": [((g.get("best") or {}).get("strategy") or {}).get("trades", 0),
                      ((g.get("normal") or {}).get("strategy") or {}).get("trades", 0)],
           "mean_r": [((g.get("best") or {}).get("strategy") or {}).get("mean_r"),
                      ((g.get("normal") or {}).get("strategy") or {}).get("mean_r")],
           "d_s": ev.get("d_s"), "p_s": ev.get("p_s"), "d_c": ev.get("d_c"),
           "eligible_cells": [ev["cells"]["strategy_eligible"], ev["cells"]["coin_flips_eligible"]],
           "columns": "trades·mean_r = [좋은 자리, 보통], eligible_cells = [매매법, 동전 봇]"}
    if ev.get("decision"):
        out["decision"] = ev["decision"]
        out["decision_ko"] = ev["decision_ko"]
    return out


def rr_section(ev: dict) -> dict:
    """The Thursday rr meeting's ``levrule``: everything but the per-cell rows (kept to the 12 largest cells)."""
    if ev.get("error") or ev.get("status") == "no_run":
        return compact(ev)
    out = {k: v for k, v in ev.items() if k not in ("cell_rows", "window")}
    rows = sorted((ev.get("cell_rows") or {}).items(), key=lambda kv: -(kv[1][0] + kv[1][1]))[:12]
    out["cell_rows"] = dict(rows)
    return out


def meeting_section(ev: dict) -> dict:
    """The 30-day checkpoint meeting's ``levrule``: the decision (or interim status) with its numbers."""
    out = compact(ev)
    if ev.get("conditions"):
        out["conditions"] = ev["conditions"]
        out["p_did"] = ev.get("p_did")
        out["did"] = ev.get("did")
    out["note"] = NOTE
    return out


def strategy_line(paper_ro: Optional[sqlite3.Connection], strategy: str, now_ms: int) -> str:
    """One line for a strategy specialist: its own accounts' 좋은 자리 vs 보통 so far (r per trade), and the status."""
    if paper_ro is None:
        return ""
    try:
        win = window(paper_ro, now_ms)
        if win["start"] is None:
            return ""
        rows = trade_rows(paper_ro, win["start"], win["to"], kinds=("strategy",), strategies=[strategy])
    except sqlite3.Error:
        return ""
    b = [t["r"] for t in rows if t["group"] == "best"]
    n = [t["r"] for t in rows if t["group"] == "normal"]

    def part(name, xs):
        m = _mean(xs)
        return f"{name} {len(xs)}건" + ("" if m is None else f" 노출당 {m * 100:+.3f}%")
    status = "30일 판정 결과는 rr·체크포인트 회의" if win["decided"] else BEFORE_KO
    return f"{part('좋은 자리', b)} · {part('보통', n)} ({status}, docs/levrule-eval.md로만 평가)"


def dash_view(paper_ro: Optional[sqlite3.Connection], now_ms: int) -> dict:
    """The dashboard card '좋은 자리 vs 보통'."""
    ev = levrule_eval(paper_ro, now_ms=now_ms)
    if ev.get("error") or ev.get("status") == "no_run":
        return ev
    from ..levwhy import REASON_KO
    ev = dict(ev)
    ev["reason_ko"] = {**REASON_KO, "unknown": "기록 못 찾음"}
    ev["cell_rows"] = dict(sorted((ev.get("cell_rows") or {}).items())[:200])
    return ev

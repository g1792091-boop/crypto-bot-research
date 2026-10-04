"""Portfolio synergy (조합 시너지, owners approved 2026-10-04): would running several strategies together have been
smoother than each alone, and is the best-looking combination more than what a search finds by chance? Code only,
read-only on paper3.db (closed trades; agents/digest._closed) and paperbot/overlap.py (same-time positions). The
staff read the numbers; nothing here trades or changes an account, and it is not a verdict.

- ``daily``       the KST-day P&L of every strategy (the sum of its timeframe accounts), every strategy account and
                  every coin-flip account, from the run start to now (days without a closed trade = 0).
- ``search``      equal-weight combinations of 2-5 units (each unit keeps its own starting capital; the combined
                  curve is the sum): every pair and triple, then a beam (the ``BEAM`` best of k-1 extended by one
                  unit) for 4 and 5. Score = total P&L / max drawdown of the combined curve ($; the drawdown floored
                  at ``DD_FLOOR`` of the capital so a curve that never fell does not score infinity).
- multiple-testing guard: the SAME search run (a) ``SHUFFLES`` times on day-shuffled P&L (each strategy's days
                  permuted on their own: its total stays, its timing against the others is broken) and (b) on the
                  15 coin-flip accounts. The real best score's rank among the shuffled bests (``rank_p`` = (shuffled
                  bests >= real + 1) / (runs + 1)) says whether the combination's smoothness is more than the search
                  finding something by chance.
- diversification ratio: the members' own max drawdowns ($) added up / the combination's max drawdown ($) (1 =
                  no spreading of risk, 2 = half the drawdown of the parts; None with ``combined_never_fell`` when
                  the combination never went under its peak).
- correlation clusters: daily P&L correlation >= 0.7 (agents/meetings.corr_clusters, as the Tuesday packet's).
- 'same bet twice': account pairs of different strategies that hold the same coin and side most of the time
                  (overlap.report: ``same_of_busy`` >= ``SAME_BET_BUSY``, or hourly-return correlation >=
                  ``SAME_BET_CORR``), and the top combinations that contain such a pair.
- ``packet`` (the Tuesday combo packet's ``synergy``), ``dash_view`` (dashboard-ready).

Runtime, measured on a synthetic 30-day paper3.db (180 strategy + 15 coin-flip accounts, ~29,000 closed trades):
one search of the 36 strategies ~35 ms; the packet ~0.7 s without the shuffles and ~2.4 s with ``SHUFFLES`` = 50
(the overlap report on top when there are equity samples). The account level (180 units) is slower (~0.4 s a
search): the dashboard view uses fewer shuffles.
"""

from __future__ import annotations

import itertools
import math
import sqlite3
import time
from typing import Any, Optional

import numpy as np

DAY_MS = 86_400_000
KMIN, KMAX = 2, 5
BEAM = 200                 # best combinations of size k-1 extended to size k (k >= 4 or when C(n, k) is large)
EXHAUSTIVE = 20_000        # every combination when C(n, k) is at most this
DD_FLOOR = 0.005           # drawdown floor: 0.5% of the combination's capital
SHUFFLES = 50
SEED = 20261004
TOP = 5
SMALL_DAYS = 14            # fewer days: small sample
SAME_BET_BUSY = 0.5
SAME_BET_CORR = 0.8
LABEL = "설명용, 판정 아님"


def _f(x: Any) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return v if v == v else 0.0


def _r(x: Optional[float], n: int = 4) -> Optional[float]:
    return None if x is None or not math.isfinite(float(x)) else round(float(x), n)


# ---------------------------------------------------------------- daily P&L
def daily(paper_ro: sqlite3.Connection, now_ms: int, kinds: tuple = ("strategy", "random")) -> dict:
    """{"days": [KST days], "strategies": {s: vec}, "accounts": {aid: vec}, "flips": {aid: vec},
    "n_accounts": {s: accounts}, "initial"}: closed-trade P&L by KST exit day since the run start."""
    from .digest import _closed, initial_equity
    from .meetings import _kst_day
    from .triggers import run_start
    start = run_start(paper_ro) or now_ms
    rows = _closed(paper_ro, start, now_ms, kinds=kinds)
    d0 = _kst_day(start)
    days = []
    t = start
    while True:
        k = _kst_day(t)
        if k > _kst_day(now_ms):
            break
        if not days or days[-1] != k:
            days.append(k)
        t += DAY_MS
    if not days or days[0] != d0:
        days.insert(0, d0)
    idx = {k: i for i, k in enumerate(days)}
    D = len(days)
    strat: dict = {}
    acct: dict = {}
    flips: dict = {}
    members: dict = {}
    for aid, kind, s, _tf, d in rows:
        i = idx.get(_kst_day(int(_f(d.get("exit_time")))))
        if i is None:
            continue
        p = _f(d.get("pnl"))
        if kind == "random":
            flips.setdefault(aid, np.zeros(D))[i] += p
            continue
        strat.setdefault(s, np.zeros(D))[i] += p
        acct.setdefault(aid, np.zeros(D))[i] += p
    try:
        for aid, kind, s in paper_ro.execute("SELECT account_id, kind, strategy FROM accounts"):
            if kind == "strategy":
                members.setdefault(s, set()).add(aid)
                strat.setdefault(s, np.zeros(D))
                acct.setdefault(aid, np.zeros(D))
            elif kind == "random" and "random" in kinds:
                flips.setdefault(aid, np.zeros(D))
    except sqlite3.Error:
        pass
    return {"days": days, "strategies": strat, "accounts": acct, "flips": flips,
            "n_accounts": {s: len(v) for s, v in members.items()}, "initial": float(initial_equity(paper_ro))}


# ---------------------------------------------------------------- scoring and search
def curve_numbers(pnl: np.ndarray, cap: np.ndarray) -> tuple:
    """Rows of daily P&L ``pnl`` (c, D) with starting capital ``cap`` (c,): (total, max drawdown $, max drawdown
    as a share of the peak, score)."""
    eq = cap[:, None] + np.cumsum(pnl, axis=1)
    peak = np.maximum(np.maximum.accumulate(eq, axis=1), cap[:, None])
    dd = peak - eq
    dd_usd = np.maximum(dd.max(axis=1), 0.0)
    dd_pct = np.where(peak > 0, dd / np.where(peak > 0, peak, 1.0), 0.0).max(axis=1)
    total = eq[:, -1] - cap
    score = total / np.maximum(dd_usd, DD_FLOOR * cap)
    return total, dd_usd, dd_pct, score


def _score(U: np.ndarray, cap: np.ndarray, combos: np.ndarray, chunk: int = 20_000) -> np.ndarray:
    out = np.empty(len(combos))
    for a in range(0, len(combos), chunk):
        c = combos[a:a + chunk]
        out[a:a + len(c)] = curve_numbers(U[c].sum(axis=1), cap[c].sum(axis=1))[3]
    return out


def search(U: np.ndarray, cap: np.ndarray, kmin: int = KMIN, kmax: int = KMAX, beam: int = BEAM,
           keep: int = TOP) -> list[tuple]:
    """The ``keep`` best equal-weight combinations of ``kmin``..``kmax`` units by score: [(score, combo tuple)].
    Every combination while C(n, k) <= EXHAUSTIVE, else the ``beam`` best of size k-1 extended by one unit."""
    n = len(U)
    best: list = []
    prev: Optional[np.ndarray] = None
    for k in range(kmin, min(kmax, n) + 1):
        if math.comb(n, k) <= EXHAUSTIVE or prev is None:
            if math.comb(n, k) > 50 * EXHAUSTIVE:
                break
            combos = np.array(list(itertools.combinations(range(n), k)), dtype=np.int64)
        else:
            ext = {tuple(sorted((*c, j))) for c in prev.tolist() for j in range(n) if j not in c}
            if not ext:
                break
            combos = np.array(sorted(ext), dtype=np.int64)
        sc = _score(U, cap, combos)
        order = np.argsort(-sc, kind="stable")
        prev = combos[order[:beam]]
        best += [(float(sc[i]), tuple(int(x) for x in combos[i])) for i in order[:keep]]
    best.sort(key=lambda x: (-x[0], x[1]))
    return best[:keep]


def best_score(U: np.ndarray, cap: np.ndarray, **kw) -> Optional[float]:
    b = search(U, cap, keep=1, **kw)
    return b[0][0] if b else None


def shuffled_bests(U: np.ndarray, cap: np.ndarray, runs: int = SHUFFLES, seed: int = SEED, **kw) -> np.ndarray:
    """The best score of the same search on ``runs`` day-shuffled copies (each unit's days permuted on their own)."""
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(runs):
        V = rng.permuted(U, axis=1)
        b = best_score(V, cap, **kw)
        if b is not None:
            out.append(b)
    return np.asarray(out)


def diversification(U: np.ndarray, cap: np.ndarray, combo: tuple) -> Optional[float]:
    """The members' own max drawdowns ($) added up / the combination's max drawdown ($). None when the
    combination never fell (``combined_never_fell`` in the rows) or no member ever fell."""
    c = list(combo)
    own = curve_numbers(U[c], cap[c])[1].sum()
    comb = curve_numbers(U[c].sum(axis=0)[None, :], np.array([cap[c].sum()]))[1][0]
    return float(own / comb) if comb > 0 and own > 0 else None


def same_bets(paper_ro: sqlite3.Connection, days: float = 7, end: Optional[int] = None) -> dict:
    """{frozenset(strategy a, strategy b): detail} for account pairs of different strategies that hold the same
    coin and side most of the time (overlap.report, read-only)."""
    from .. import overlap as OV
    try:
        rep = OV.report(paper_ro, days=days, end=end, top_pairs=300)
    except Exception as exc:  # noqa: BLE001  (a description never stops a packet)
        return {"error": type(exc).__name__}
    out: dict = {}
    for p in ((rep.get("pairs") or {}).get("top") or []):
        a, b = p.get("a") or {}, p.get("b") or {}
        sa, sb = a.get("strategy"), b.get("strategy")
        if not sa or not sb or sa == sb:
            continue
        busy, corr = p.get("same_of_busy"), p.get("corr")
        if (busy is not None and busy >= SAME_BET_BUSY) or (corr is not None and corr >= SAME_BET_CORR):
            key = frozenset((sa, sb))
            cur = out.get(key)
            if cur is None or (busy or 0) > (cur.get("same_of_busy") or 0):
                out[key] = {"accounts": [a.get("account_id"), b.get("account_id")], "same_of_busy": _r(busy, 3),
                            "corr": _r(corr, 3)}
    return out


def _clusters(units: list, M: np.ndarray, names: dict, cluster_r: float = 0.7) -> list:
    from .meetings import corr_clusters
    ok = M.std(axis=1) > 0
    pairs = []
    if ok.sum() >= 2 and M.shape[1] >= 3:
        C = np.corrcoef(M[ok])
        live = [u for u, o in zip(units, ok) if o]
        for i in range(len(live)):
            for j in range(i + 1, len(live)):
                pairs.append((float(C[i, j]), live[i], live[j]))
    return [[names.get(s, s) for s in g] for g in corr_clusters(units, pairs, cluster_r)]


# ---------------------------------------------------------------- packets
def analyse(paper_ro: Optional[sqlite3.Connection], now_ms: int, level: str = "strategy", shuffles: int = SHUFFLES,
            names_ko: Optional[dict] = None, top: int = TOP, overlap_days: float = 7, seed: int = SEED) -> dict:
    """Everything: the top combinations with their numbers, the shuffled-day and coin-flip comparisons, the
    diversification ratios, the clusters and the same-bet pairs. ``level``: 'strategy' (36 units, each the sum of
    its timeframe accounts) or 'account' (every strategy account)."""
    if paper_ro is None:
        return {"error": "paper3.db 없음", "label": LABEL}
    t0 = time.perf_counter()
    if names_ko is None:
        from .roster3 import STRATEGY_KO
        names_ko = dict(STRATEGY_KO)
    try:
        d = daily(paper_ro, now_ms)
    except sqlite3.Error as exc:
        return {"error": f"paper3.db를 읽지 못함: {type(exc).__name__}", "label": LABEL}
    src = d["strategies"] if level == "strategy" else d["accounts"]
    units = sorted(src)
    D = len(d["days"])
    out: dict = {"label": LABEL, "level": level, "days": D, "units": len(units)}
    if D < SMALL_DAYS:
        out["small"] = True
    if len(units) < KMIN:
        out["note"] = "조합할 매매법이 2개 미만"
        return out
    U = np.vstack([src[u] for u in units])
    per = (lambda u: d["n_accounts"].get(u, 1)) if level == "strategy" else (lambda u: 1)
    cap = np.array([d["initial"] * max(1, per(u)) for u in units], dtype=float)
    best = search(U, cap, keep=top)
    real = best[0][0] if best else None
    sb = same_bets(paper_ro, overlap_days)
    sb_err = sb.pop("error", None) if isinstance(sb, dict) and "error" in sb else None
    strat_of = (lambda u: u) if level == "strategy" else (lambda u: str(u).split("@")[0])

    def label(u: str) -> str:
        if level == "strategy":
            return names_ko.get(u, u)
        s, _, tf = str(u).partition("@")
        return f"{names_ko.get(s, s)}@{tf}"
    rows = []
    for sc, combo in best:
        c = list(combo)
        total, ddu, ddp, _s = curve_numbers(U[c].sum(axis=0)[None, :], np.array([cap[c].sum()]))
        members = [units[i] for i in c]
        flagged = []
        for a, b in itertools.combinations(members, 2):
            hit = sb.get(frozenset((strat_of(a), strat_of(b)))) if sb else None
            if hit:
                flagged.append({"pair": [label(a), label(b)], **hit})
        rows.append({"units": members, "names": [label(u) for u in members], "k": len(c),
                     "return_pct": _r(total[0] / cap[c].sum()), "max_dd_pct": _r(ddp[0]), "max_dd_usd": _r(ddu[0], 2),
                     "score": _r(sc, 3), "div_ratio": _r(diversification(U, cap, combo), 3),
                     **({"combined_never_fell": True} if ddu[0] <= 0 else {}),
                     **({"same_bet": flagged} if flagged else {})})
    out["top"] = rows
    null = shuffled_bests(U, cap, runs=shuffles, seed=seed) if shuffles else np.zeros(0)
    if len(null) and real is not None:
        out["shuffled_days"] = {"runs": int(len(null)), "real_best": _r(real, 3),
                                "null_best_median": _r(float(np.median(null)), 3),
                                "null_best_p90": _r(float(np.quantile(null, 0.9)), 3),
                                "rank_p": _r(float((np.sum(null >= real - 1e-12) + 1) / (len(null) + 1)), 3),
                                "real_beats_share": _r(float(np.mean(null < real)), 3)}
    flips = sorted(d["flips"])
    if len(flips) >= KMIN:
        F = np.vstack([d["flips"][a] for a in flips])
        fb = search(F, np.full(len(flips), d["initial"]), keep=1)
        if fb:
            out["coin_flips"] = {"units": len(flips), "best_score": _r(fb[0][0], 3),
                                 "best": [flips[i] for i in fb[0][1]],
                                 "note": (f"동전 봇 계좌 {len(flips)}개(계좌 하나씩)로 같은 탐색: 비교 기준일 뿐 조건이 같지 않음"
                                          "(후보 수가 다르고, 매매법은 봉 계좌 5개의 합)")}
    out["same_bet_pairs"] = ([{"strategies": [names_ko.get(s, s) for s in sorted(k)], **v}
                              for k, v in sorted(sb.items(), key=lambda kv: -(kv[1].get("same_of_busy") or 0))][:8]
                             if sb else [])
    if sb_err:
        out["same_bet_error"] = sb_err
    out["clusters"] = _clusters(units, U, {u: label(u) for u in units})[:8]
    out["runtime_s"] = round(time.perf_counter() - t0, 3)
    return out


HOW_TO_READ = ("top = 매매법 2~5개를 똑같은 크기(각자 시작 자금 그대로)로 같이 돌렸다면의 합친 자금 곡선 중 점수(총손익 ÷ 최대 낙폭 $)가 "
               "높은 순. return_pct = 합친 자금 대비 총손익(0.01 = 1%), max_dd_pct = 최고점 대비 가장 깊은 낙폭, div_ratio = "
               "구성 매매법 각자의 최대 낙폭 합 ÷ 합친 곡선의 최대 낙폭(1이면 위험이 안 나뉨, 2면 절반, 합친 곡선이 한 번도 내려가지 않았으면 None과 combined_never_fell). shuffled_days = 같은 탐색을 "
               "매매법마다 날짜를 섞은 자료로 여러 번 돌렸을 때의 최고 점수: rank_p가 크면(예: 0.3) 진짜 최고 조합도 '많이 찾아보면 "
               "우연히 나오는 정도'. coin_flips = 동전 봇 계좌로 같은 탐색. same_bet = 같은 코인·같은 방향을 대부분 같이 들고 있던 "
               "계좌 쌍(사실상 같은 베팅 두 번). small = 날 수가 적어 우연이 큼")


def packet(paper_ro: Optional[sqlite3.Connection], now_ms: int, names_ko: Optional[dict] = None,
           shuffles: int = SHUFFLES) -> dict:
    """The Tuesday combo packet's ``synergy`` (compact: the top 5, the null comparisons, the same-bet pairs; the
    clusters are the packet's own ``combo.correlation.clusters``)."""
    a = analyse(paper_ro, now_ms, names_ko=names_ko, shuffles=shuffles)
    if a.get("error"):
        return a
    out = {k: a[k] for k in ("label", "days", "units", "top", "shuffled_days", "coin_flips", "same_bet_pairs",
                             "small", "note", "same_bet_error", "runtime_s") if k in a}
    for r in out.get("top") or []:
        r.pop("units", None)
        r.pop("max_dd_usd", None)
    out["same_bet_pairs"] = (out.get("same_bet_pairs") or [])[:5]
    out["clusters_in"] = "combo.correlation.clusters"
    out["how_to_read"] = HOW_TO_READ
    out["note_all"] = ("코드 계산(설명용, 판정 아님). 실험 시작부터의 하루(한국 시간) 손익. 최고 조합은 수만 개 중 고른 것이라 "
                       "shuffled_days와 비교해야 함. 30일 판정은 체크포인트가 함, 계좌를 묶거나 바꾸지 않음")
    return out


def dash_view(paper_ro: sqlite3.Connection, now_ms: int, level: str = "strategy", shuffles: int = 20) -> dict:
    """Dashboard-ready: the same analysis (fewer shuffles by default), with the clusters."""
    a = analyse(paper_ro, now_ms, level=level, shuffles=shuffles)
    if not a.get("error"):
        a["how_to_read"] = HOW_TO_READ
    return a

"""조합 시너지 보강 (ana-syn): four more descriptive cards under 분석 › 조합 시너지, for the 36 locked strategies ("기존 36",
kind 'strategy' on the core timeframes 15m-4h) with their coin flips (kind 'random' on the same timeframes) as the
baseline line. Read-only on paper3.db; nothing trades, nothing is written, nothing here is a verdict.

    GET /api/v4/synplus

- ``coloss``  같이 망하는 날. The KST-day P&L of agents/synergy.daily (a strategy = the sum of its timeframe accounts, as
              the 조합 시너지 view). For every pair of strategies over the days either one lost (P&L < 0):
              ``co_loss`` = days both lost / days either lost; ``cover`` = days one lost while the other made money
              (P&L > 0) / days either lost; ``bad_ab`` = on a's worst days (the ceil(WORST_SHARE x days) lowest days
              of a that were losses) the share on which b lost too, and ``bad_ba`` the other way. Listed: the pairs
              that fall together most (co_loss) and the ones that cover each other best (cover), among pairs with at
              least ``MIN_PAIR_DAYS`` losing days between them; the medians over those pairs; the same medians for the
              coin-flip accounts (one account each: not the same conditions). Needs ``MIN_DAYS_COLOSS`` KST days.
- ``agree``   같이 들어간 진입 (신호 합의). Every closed trade of the 36 since the run start: how many OTHER strategies
              (distinct names, any timeframe) entered the same coin on the same side within that trade's own bar
              length (|entry - entry'| <= bar), counting closed trades and the positions open now; and whether a
              position of the 36 on the other side of that coin was open at the entry (entry' <= entry < exit').
              Buckets 혼자 (0 others) / 2개 같이 (1) / 3개 이상 (2+), and 반대 방향 있음 / 없음 (a cross-cut, each
              trade is in one of the first three and in one of the last two) -> trades, win share, mean net ROE,
              mean P&L on equity (pnl / equity before the trade, agents/leveval's ``eq``). The coin flips: the same
              buckets for each closed coin-flip trade, counted against the 36's entries (how many of the 36 were
              there at a random entry). 봉 합의: the same strategy's other timeframe accounts already holding the
              same coin and side at the entry (entry' <= entry < exit'; for a coin flip its own seed's other
              timeframes). Shown from ``MIN_AGREE_TRADES`` closed trades of the 36.
- ``walk``    다음 기간에도 통할까 (walk-forward). The days split in two halves (first = days[:D//2]). The best combination
              of the first half by agents/synergy.search (the same 2-5 equal-weight search and score: total P&L / max
              drawdown) chosen on the first half's columns only; its score on the second half alone (a fresh curve
              from the starting capital) next to the median and the 75th percentile of EVERY 2-5 combination's
              second-half score, and the share of combinations it beat. The coin-flip accounts the same way. Needs
              ``MIN_DAYS_WALK`` KST days.
- ``one_account`` 한 계좌로 합치면. The top ``TOP_COMBOS`` combinations of the whole period (agents/synergy.search: the
              조합 시너지 view's own top list) put in one account: the share of the time the combination held any
              position during which two of its accounts held the same coin in opposite directions (they cancel out:
              both pay fees and funding), and the peak margin in use at the same time (sum of the open positions'
              starting margin) against one account's starting capital. Closed trades plus the positions open now.
              The 12 core coin-flip accounts merged the same way are the baseline line. Shown once the 조합 시너지
              view shows its top list (dash/analysis.py SYNERGY_MIN_TRADES).

Cost: one background computation (dash/analysis.Heavy, shared with the other heavy analysis views: one at a time),
cached ``TTL_S``; a first request answers ``{"pending": true}`` after ``WAIT_S`` and the card asks again.
"""
from __future__ import annotations

import bisect
import itertools
import json
import math
import sqlite3
import time
from typing import Any, Optional

import numpy as np

TTL_S = 900
WAIT_S = 3.0
LABEL = "설명용, 판정 아님"
MIN_DAYS_COLOSS = 14
MIN_DAYS_WALK = 20
WORST_SHARE = 0.2
MIN_PAIR_DAYS = 5
TOP_PAIRS = 5
MIN_AGREE_TRADES = 30
SMALL_N = 20
TOP_COMBOS = 3
KMIN, KMAX = 2, 5
CHUNK = 20_000
BAR_MS = {"5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000}
CORE, FLIP = "strategy", "random"
AGREE_KEYS = ("alone", "two", "three_plus")
OPP_KEYS = ("opposite", "no_opposite")
TF_KEYS = ("tf_none", "tf_one", "tf_two_plus")


def _r(x: Any, n: int = 4) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, n) if math.isfinite(v) else None


def _med(xs: list) -> Optional[float]:
    v = [x for x in xs if x is not None]
    return float(np.median(v)) if v else None


# ---------------------------------------------------------------- 같이 망하는 날
def pair_counts(M: np.ndarray, worst_share: float = WORST_SHARE) -> dict:
    """Day counts for every pair of the rows of ``M`` (units x days of P&L): ``both`` / ``either`` lost, ``cover``
    (one lost while the other made money, both ways), ``bad_n`` (each unit's worst days that were losses: the
    ceil(worst_share x days) lowest, ties by day order) and ``bad_hit[i, j]`` (of i's worst days, those j lost)."""
    n, D = M.shape
    L = (M < 0).astype(np.int64)
    W = (M > 0).astype(np.int64)
    both = L @ L.T
    nl = L.sum(axis=1)
    either = nl[:, None] + nl[None, :] - both
    cov = L @ W.T
    k = max(1, math.ceil(worst_share * D)) if D else 0
    bad = np.zeros((n, D), dtype=np.int64)
    if k and n:
        low = np.argsort(M, axis=1, kind="stable")[:, :k]
        bad[np.arange(n)[:, None], low] = 1
        bad &= L
    return {"both": both, "either": either, "cover": cov + cov.T, "bad_n": bad.sum(axis=1), "bad_hit": bad @ L.T,
            "worst_days": k}


def pair_rows(units: list, M: np.ndarray, min_days: int = MIN_PAIR_DAYS) -> tuple[list, int]:
    """One row per pair with at least ``min_days`` days either lost: (rows, worst-day count)."""
    t = pair_counts(M)
    out = []
    for i, j in itertools.combinations(range(len(units)), 2):
        e = int(t["either"][i, j])
        if e < min_days:
            continue
        bi, bj = int(t["bad_n"][i]), int(t["bad_n"][j])
        ab = t["bad_hit"][i, j] / bi if bi else None
        ba = t["bad_hit"][j, i] / bj if bj else None
        bad = [x for x in (ab, ba) if x is not None]
        out.append({"a": units[i], "b": units[j], "either_days": e, "both_days": int(t["both"][i, j]),
                    "cover_days": int(t["cover"][i, j]), "co_loss": int(t["both"][i, j]) / e,
                    "cover": int(t["cover"][i, j]) / e, "bad_ab": ab, "bad_ba": ba,
                    "bad": sum(bad) / len(bad) if bad else None})
    return out, t["worst_days"]


def _pair_out(r: dict, names: dict) -> dict:
    return {"units": [r["a"], r["b"]], "names": [names.get(r["a"], r["a"]), names.get(r["b"], r["b"])],
            "either_days": r["either_days"], "both_days": r["both_days"], "cover_days": r["cover_days"],
            "co_loss": _r(r["co_loss"], 3), "cover": _r(r["cover"], 3), "bad_ab": _r(r["bad_ab"], 3),
            "bad_ba": _r(r["bad_ba"], 3)}


def _medians(rows: list) -> dict:
    return {"co_loss": _r(_med([r["co_loss"] for r in rows]), 3), "cover": _r(_med([r["cover"] for r in rows]), 3),
            "bad": _r(_med([r["bad"] for r in rows]), 3)}


def coloss(units: list, M: np.ndarray, flip_units: list, F: Optional[np.ndarray], names: dict,
           need_days: int = MIN_DAYS_COLOSS) -> dict:
    D = int(M.shape[1]) if M.ndim == 2 else 0
    out: dict = {"days": D, "need_days": need_days, "min_pair_days": MIN_PAIR_DAYS, "worst_share": WORST_SHARE}
    if D < need_days or len(units) < 2:
        out["waiting"] = True
        return out
    rows, k = pair_rows(units, M)
    out.update({"worst_days": k, "pairs": len(rows), "units": len(units), "median": _medians(rows)})
    together = sorted(rows, key=lambda r: (-r["co_loss"], -(r["bad"] or 0), -r["either_days"], r["a"], r["b"]))
    covers = sorted(rows, key=lambda r: (-r["cover"], r["co_loss"], -r["either_days"], r["a"], r["b"]))
    out["together"] = [_pair_out(r, names) for r in together[:TOP_PAIRS]]
    out["cover_best"] = [_pair_out(r, names) for r in covers[:TOP_PAIRS]]
    if F is not None and len(flip_units) >= 2:
        frows, _k = pair_rows(flip_units, F)
        out["coin_flips"] = {"units": len(flip_units), "pairs": len(frows), "median": _medians(frows)}
    return out


# ---------------------------------------------------------------- 다음 기간에도 통할까 (walk-forward)
def all_scores(U: np.ndarray, cap: np.ndarray, kmin: int = KMIN, kmax: int = KMAX) -> np.ndarray:
    """The synergy score (agents/synergy.curve_numbers) of every equal-weight combination of kmin..kmax rows."""
    from ...agents.synergy import _score
    n = len(U)
    out = []
    for k in range(kmin, min(kmax, n) + 1):
        it = itertools.combinations(range(n), k)
        while True:
            block = np.array(list(itertools.islice(it, CHUNK * 5)), dtype=np.int64)
            if not len(block):
                break
            out.append(_score(U, cap, block.reshape(-1, k), chunk=CHUNK))
    return np.concatenate(out) if out else np.zeros(0)


def walk_once(U: np.ndarray, cap: np.ndarray, h: int) -> Optional[dict]:
    """First half = columns [:h] (the choice), second half = [h:] (the check): the first half's best combination
    (agents/synergy.search on the first half only), its first- and second-half scores, and every combination's
    second-half scores (median, 75th percentile, the share the choice beat)."""
    from ...agents import synergy as SY
    if len(U) < KMIN:
        return None
    first, second = U[:, :h], U[:, h:]
    best = SY.search(first, cap, keep=1)
    if not best:
        return None
    s1, combo = best[0]
    c = list(combo)
    s2 = float(SY.curve_numbers(second[c].sum(axis=0)[None, :], np.array([cap[c].sum()]))[3][0])
    pop = all_scores(second, cap)
    return {"combo": c, "first_score": _r(s1, 3), "second_score": _r(s2, 3), "combos": int(len(pop)),
            "second_median": _r(float(np.median(pop)), 3) if len(pop) else None,
            "second_p75": _r(float(np.quantile(pop, 0.75)), 3) if len(pop) else None,
            "beat_share": _r(float(np.mean(pop < s2 - 1e-12)), 3) if len(pop) else None}


def walk(units: list, U: np.ndarray, cap: np.ndarray, days: list, flip_units: list, F: Optional[np.ndarray],
         fcap: Optional[np.ndarray], names: dict, need_days: int = MIN_DAYS_WALK) -> dict:
    D = len(days)
    out: dict = {"days": D, "need_days": need_days}
    if D < need_days or len(units) < KMIN:
        out["waiting"] = True
        return out
    h = D // 2
    out["first"] = {"from": days[0], "to": days[h - 1], "days": h}
    out["second"] = {"from": days[h], "to": days[-1], "days": D - h}
    w = walk_once(U, cap, h)
    if w:
        out["strategies"] = {**{k: v for k, v in w.items() if k != "combo"},
                             "units": [units[i] for i in w["combo"]], "names": [names.get(units[i], units[i])
                                                                                 for i in w["combo"]]}
    if F is not None and len(flip_units) >= KMIN:
        f = walk_once(F, fcap, h)
        if f:
            out["coin_flips"] = {**{k: v for k, v in f.items() if k != "combo"}, "units_n": len(flip_units),
                                 "units": [flip_units[i] for i in f["combo"]]}
    return out


# ---------------------------------------------------------------- reading trades and open positions
def _trades(c: sqlite3.Connection, since_ms: int, tfs: tuple) -> list[dict]:
    """The closed trades of the 36 and their coin flips on ``tfs`` with exit at or after ``since_ms``."""
    base = ("SELECT t.account_id, a.kind, a.strategy, a.timeframe, t.symbol, t.entry_time, t.exit_time, t.pnl, "
            "t.roe, t.equity_after, {x} FROM trades t JOIN accounts a ON a.account_id = t.account_id WHERE a.kind IN "
            f"('{CORE}', '{FLIP}') AND a.timeframe IN ({','.join('?' * len(tfs))}) AND t.exit_time >= ? "
            "ORDER BY t.entry_time, t.id")
    args = (*tfs, int(since_ms))
    try:
        got = [(*r[:10], r[10], r[11]) for r in c.execute(
            base.format(x="json_extract(t.data, '$.side'), json_extract(t.data, '$.margin')"), args)]
    except sqlite3.OperationalError:          # no JSON1 in this SQLite: parse in Python
        got = []
        for r in c.execute(base.format(x="t.data"), args):
            try:
                d = json.loads(r[10]) or {}
            except (TypeError, ValueError):
                d = {}
            got.append((*r[:10], d.get("side"), d.get("margin")))
    out = []
    for aid, kind, strat, tf, sym, et, xt, pnl, roe, eqa, side, margin in got:
        try:
            side = int(side or 0)
        except (TypeError, ValueError):
            side = 0
        if side not in (1, -1) or pnl is None:
            continue
        out.append({"account": aid, "kind": kind, "strategy": strat, "tf": tf, "symbol": sym, "entry": int(et),
                    "exit": int(xt), "pnl": float(pnl), "roe": None if roe is None else float(roe),
                    "eq_after": None if eqa is None else float(eqa), "side": side,
                    "margin": float(margin) if isinstance(margin, (int, float)) else 0.0})
    return out


def _open_positions(c: sqlite3.Connection, accts: dict, now_ms: int) -> list[dict]:
    """The positions open now (state 'accounts', the runner's snapshot) of the accounts in ``accts``
    {account: (kind, strategy, tf)} as intervals ending now."""
    try:
        r = c.execute("SELECT data FROM state WHERE k = 'accounts'").fetchone()
        eng = (json.loads(r[0]) or {}).get("engines", {}) if r else {}
    except (sqlite3.Error, TypeError, ValueError, AttributeError):
        eng = {}
    out = []
    for aid, e in (eng or {}).items():
        p = (e or {}).get("position") if isinstance(e, dict) else None
        meta = accts.get(aid)
        if not p or meta is None or p.get("entry_time") is None:
            continue
        try:
            side = int(p.get("side") or 0)
            et = int(p["entry_time"])
        except (TypeError, ValueError):
            continue
        if side not in (1, -1) or et > now_ms:
            continue
        m = p.get("margin_initial", p.get("margin"))
        out.append({"account": aid, "kind": meta[0], "strategy": meta[1], "tf": meta[2], "symbol": p.get("symbol"),
                    "entry": et, "exit": int(now_ms) + 1, "side": side,
                    "margin": float(m) if isinstance(m, (int, float)) else 0.0, "open": True})
    return out


# ---------------------------------------------------------------- 같이 들어간 진입 (신호 합의)
def cell(rows: list) -> dict:
    """trades, win share, mean net ROE, mean P&L on equity (pnl / equity before the trade) of closed trades."""
    n = len(rows)
    if not n:
        return {"trades": 0}
    roe = [r["roe"] for r in rows if r.get("roe") is not None]
    eq = [r["pnl"] / (r["eq_after"] - r["pnl"]) for r in rows
          if r.get("eq_after") is not None and r["eq_after"] - r["pnl"] > 0]
    out = {"trades": n, "win_rate": _r(sum(1 for r in rows if r["pnl"] > 0) / n),
           "mean_roe": _r(sum(roe) / len(roe)) if roe else None, "mean_eq": _r(sum(eq) / len(eq), 5) if eq else None}
    if n < SMALL_N:
        out["small"] = True
    return out


class _Book:
    """The 36's entries and holdings per (coin, side), for the agreement counts."""

    def __init__(self, intervals: list):
        self.ent: dict = {}
        self.hold: dict = {}
        for iv in intervals:
            k = (iv["symbol"], iv["side"])
            self.ent.setdefault(k, []).append((iv["entry"], iv["strategy"]))
            self.hold.setdefault(k, []).append((iv["entry"], iv["exit"]))
        self.times: dict = {}
        self.pmax: dict = {}
        for k in self.ent:
            self.ent[k].sort()
            self.times[k] = [t for t, _s in self.ent[k]]
            h = sorted(self.hold[k])
            self.hold[k] = [t for t, _x in h]
            pm, best = [], -1
            for _t, x in h:
                best = max(best, x)
                pm.append(best)
            self.pmax[k] = pm

    def others(self, symbol: str, side: int, t: int, window: int, own: Optional[str]) -> int:
        """Distinct strategies (not ``own``) with an entry on (symbol, side) within ``window`` ms of ``t``."""
        k = (symbol, side)
        ts = self.times.get(k)
        if not ts:
            return 0
        lo, hi = bisect.bisect_left(ts, t - window), bisect.bisect_right(ts, t + window)
        return len({s for _t, s in self.ent[k][lo:hi] if s != own})

    def held(self, symbol: str, side: int, t: int) -> bool:
        """Some position on (symbol, side) open at ``t`` (entry <= t < exit)."""
        k = (symbol, side)
        hs = self.hold.get(k)
        if not hs:
            return False
        i = bisect.bisect_right(hs, t)
        return i > 0 and self.pmax[k][i - 1] > t


def tf_agree(intervals: list) -> dict:
    """{(strategy, symbol, side): [(entry, exit, account)]} for the 봉 합의 count."""
    out: dict = {}
    for iv in intervals:
        out.setdefault((iv["strategy"], iv["symbol"], iv["side"]), []).append((iv["entry"], iv["exit"], iv["account"]))
    return out


def tf_count(idx: dict, r: dict) -> int:
    """The same strategy's (or coin-flip seed's) OTHER accounts holding r's coin and side at r's entry."""
    e = r["entry"]
    return len({a for en, ex, a in idx.get((r["strategy"], r["symbol"], r["side"]), ())
                if a != r["account"] and en <= e < ex})


def agreement(rows: list, opens: list, need: int = MIN_AGREE_TRADES) -> dict:
    core = [r for r in rows if r["kind"] == CORE]
    flips = [r for r in rows if r["kind"] == FLIP]
    out: dict = {"trades": len(core), "flip_trades": len(flips), "need_trades": need, "small_n": SMALL_N}
    if len(core) < need:
        out["waiting"] = True
        return out
    core_iv = core + [o for o in opens if o["kind"] == CORE]
    book = _Book(core_iv)
    tfi = tf_agree(core_iv + flips + [o for o in opens if o["kind"] == FLIP])

    def tag(r: dict, own: Optional[str]) -> tuple:
        k = book.others(r["symbol"], r["side"], r["entry"], BAR_MS.get(r["tf"], 900_000), own)
        a = AGREE_KEYS[min(k, 2)]
        o = OPP_KEYS[0] if book.held(r["symbol"], -r["side"], r["entry"]) else OPP_KEYS[1]
        t = TF_KEYS[min(tf_count(tfi, r), 2)]
        return a, o, t

    bk: dict = {k: {"s": [], "f": []} for k in (*AGREE_KEYS, *OPP_KEYS, *TF_KEYS)}
    for r in core:
        for k in tag(r, r["strategy"]):
            bk[k]["s"].append(r)
    for r in flips:
        for k in tag(r, None):
            bk[k]["f"].append(r)
    nc, nf = len(core), len(flips)
    out["buckets"] = {k: {"strategies": cell(v["s"]), "coin_flips": cell(v["f"]),
                          "share": _r(len(v["s"]) / nc, 3), "flip_share": _r(len(v["f"]) / nf, 3) if nf else None}
                      for k, v in bk.items()}
    out["all"] = {"strategies": cell(core), "coin_flips": cell(flips)}
    out["open_now"] = sum(1 for o in opens if o["kind"] == CORE)
    return out


# ---------------------------------------------------------------- 한 계좌로 합치면
def merged(intervals: list, start: int, now: int) -> dict:
    """The intervals of several accounts in one account: hours with any position, hours with the same coin held
    long and short at once, and the peak sum of open margin (exits before entries at the same instant)."""
    ev = []
    for iv in intervals:
        a, b = max(int(iv["entry"]), start), min(int(iv["exit"]), now)
        if b <= a:
            continue
        ev.append((a, 1, iv))
        ev.append((b, 0, iv))
    ev.sort(key=lambda x: (x[0], x[1]))
    long_n: dict = {}
    short_n: dict = {}
    clash = 0
    n_open = 0
    margin = 0.0
    peak, peak_ts = 0.0, None
    busy = cancel = 0
    prev = None
    for t, kind, iv in ev:
        if prev is not None and t > prev:
            if n_open:
                busy += t - prev
            if clash:
                cancel += t - prev
        prev = t
        sym, side = iv["symbol"], iv["side"]
        side_n = long_n if side > 0 else short_n
        other = short_n if side > 0 else long_n
        before = side_n.get(sym, 0) > 0 and other.get(sym, 0) > 0
        side_n[sym] = side_n.get(sym, 0) + (1 if kind else -1)
        after = side_n[sym] > 0 and other.get(sym, 0) > 0
        clash += int(after) - int(before)
        n_open += 1 if kind else -1
        margin += iv["margin"] if kind else -iv["margin"]
        if kind and margin > peak + 1e-9:
            peak, peak_ts = margin, t
    return {"busy_hours": _r(busy / 3_600_000, 1), "cancel_hours": _r(cancel / 3_600_000, 1),
            "cancel_share": _r(cancel / busy, 3) if busy else None, "peak_margin": _r(peak, 2), "peak_ts": peak_ts}


def one_account(combos: list, intervals: list, accounts_of: dict, initial: float, start: int, now: int,
                names: dict, flip_accounts: list) -> dict:
    out: dict = {"initial": _r(initial, 2), "combos": []}
    for combo in combos:
        accts = sorted(a for s in combo for a in accounts_of.get(s, ()))
        mine = [iv for iv in intervals if iv["kind"] == CORE and iv["strategy"] in set(combo)]
        m = merged(mine, start, now)
        out["combos"].append({"units": list(combo), "names": [names.get(s, s) for s in combo],
                              "accounts": len(accts), "capital": _r(initial * len(accts), 2), **m,
                              "peak_x_one": _r(m["peak_margin"] / initial, 2) if initial else None})
    if flip_accounts:
        fl = [iv for iv in intervals if iv["kind"] == FLIP]
        m = merged(fl, start, now)
        out["coin_flips"] = {"accounts": len(flip_accounts), "capital": _r(initial * len(flip_accounts), 2), **m,
                             "peak_x_one": _r(m["peak_margin"] / initial, 2) if initial else None}
    return out


# ---------------------------------------------------------------- the view
def view(paper_db: str, now_ms: int) -> dict:
    """Everything above for the dashboard (never raises on a missing file: ``error``)."""
    from ...agents import synergy as SY
    from ...agents.roster3 import STRATEGY_KO
    from ...agents.triggers import run_start
    from ...config import V3_TRADE_TFS
    from ..analysis import SYNERGY_MIN_TRADES, _close, ro_connect
    t0 = time.perf_counter()
    out: dict = {"label": LABEL, "group": "core", "computed_for": int(now_ms)}
    c = ro_connect(paper_db)
    if c is None:
        out["error"] = "paper3.db 없음"
        return out
    try:
        d = SY.daily(c, now_ms)
        start = int(run_start(c) or now_ms)
        accts = {r[0]: (r[1], r[2], r[3]) for r in c.execute(
            "SELECT account_id, kind, strategy, timeframe FROM accounts WHERE kind IN (?, ?) AND timeframe IN (%s)"
            % ",".join("?" * len(V3_TRADE_TFS)), (CORE, FLIP, *V3_TRADE_TFS))}
        rows = _trades(c, start, V3_TRADE_TFS)
        opens = _open_positions(c, accts, now_ms)
    except sqlite3.Error as exc:
        out["error"] = f"paper3.db를 읽지 못함: {type(exc).__name__}"
        return out
    finally:
        _close(c)
    names = dict(STRATEGY_KO)
    units = sorted(d["strategies"])
    flip_units = sorted(d["flips"])
    D = len(d["days"])
    U = np.vstack([d["strategies"][u] for u in units]) if units else np.zeros((0, D))
    cap = np.array([d["initial"] * max(1, d["n_accounts"].get(u, 1)) for u in units], dtype=float)
    F = np.vstack([d["flips"][a] for a in flip_units]) if flip_units else None
    fcap = np.full(len(flip_units), d["initial"]) if flip_units else None
    out["days"] = D
    out["since"] = start
    out["coloss"] = coloss(units, U, flip_units, F, names)
    out["agree"] = agreement(rows, opens)
    out["walk"] = walk(units, U, cap, d["days"], flip_units, F, fcap, names)
    # 한 계좌로 합치면: only once the 조합 시너지 view shows its own top list (the same gate as dash/analysis.py)
    core_accts = [a for a, m in accts.items() if m[0] == CORE]
    n_tr = sum(1 for r in rows if r["kind"] == CORE)
    avg = n_tr / len(core_accts) if core_accts else 0.0
    top = SY.search(U, cap, keep=TOP_COMBOS) if len(units) >= KMIN else []
    oa: dict = {"need_avg_trades": SYNERGY_MIN_TRADES, "avg_trades": _r(avg, 2), "top": TOP_COMBOS}
    if not core_accts or avg < SYNERGY_MIN_TRADES or not any(s for s, _c in top):
        oa["waiting"] = True
    else:
        accounts_of: dict = {}
        for a, (kind, s, _tf) in accts.items():
            if kind == CORE:
                accounts_of.setdefault(s, []).append(a)
        oa.update(one_account([[units[i] for i in combo] for _s, combo in top], rows + opens, accounts_of,
                              float(d["initial"]), start, int(now_ms), names,
                              [a for a, m in accts.items() if m[0] == FLIP]))
    out["one_account"] = oa
    out["runtime_s"] = round(time.perf_counter() - t0, 3)
    return out


def register(app, ctx) -> dict:
    from ..analysis import Heavy
    heavy = getattr(app.state, "analysis", None)
    if not isinstance(heavy, Heavy):         # registered without the analysis routes (tests): its own one-at-a-time
        heavy = Heavy()

    @app.get("/api/v4/synplus")
    def get_synplus():
        """조합 시너지 보강 (같이 망하는 날, 신호 합의, 다음 기간, 한 계좌로); background + cached ``TTL_S``."""
        return heavy.get("synplus", TTL_S, lambda: view(ctx.db, int(time.time() * 1000)), wait_s=WAIT_S)

    return {"routes": ["/api/v4/synplus"]}

"""한 달 시뮬 (league.json key ``monthsim``): the owners' "luck calculator" for the owner-exit candidate league.

The question: "if the record so far went on for a month, what could $1,000 become, and does a coin flip get as far?" The five-year studies found
no direction skill, so this block exists to make luck and skill VISIBLE, not to promise anything. Read-only, exploratory, decides nothing.

For each of the four kinds -fq (실전 후보), -fqc (its coin-flip twin), -ld (대조) and -ldc (its coin twin):

1. **Daily series.** One account's realised daily return = that UTC day's closed-trade P&L / the wallet before the day (start wallet
   ``equity0`` + the P&L of all earlier days); a day without a close is 0. The kind's basket return of a day = the plain mean over the kind's
   accounts that have at least one closed trade (all accounts start with the same wallet, so equal weight is the same as equal money).
   Only whole UTC days from the league start up to the last COMPLETE day count: today's open day and open positions are left out.
2. **Resample days, not trades.** The days (zeros included) are drawn with replacement, ``N_BOOT`` times, into ``HORIZON`` = 30-day compounded
   paths of the basket. The 5/25/50/75/95 percentiles of the final multiple, ``p_x2`` / ``p_x4`` (final >= 2 / >= 4), ``p_below_half``
   (final < 0.5) and ``p_loss`` (final < 1) come from those paths. A real kind and its coin twin use the SAME day draws (the seed is the real
   kind's), so their difference is paired. Days are treated as independent, which they are not: the honest range is wider than the one shown.
3. **Too little data: no numbers.** With fewer than ``MIN_DAYS`` distinct days that had a close, or fewer than ``MIN_TRADES`` closed trades in
   the kind, the entry has ``status: "few"`` and the counts, never a percentile.
4. **Edge against the coin.** ``edge_vs_coin`` of a real kind: median(real) - median(coin) as multiples, with the 90% interval of a day-cluster
   bootstrap (the observed days are resampled, then a short path simulation of both kinds on those SAME days gives the difference of medians),
   plus the share of the coin's simulated months that reach the real kind's median.
5. **Single account.** ``single_account`` is NOT a simulation: it is the cross-section of the accounts' own observed multiples scaled to 30 days
   (ln multiple x 30 / days), as 5/50/95 percentiles with n: how far apart single picks end up.

DeepSeek money (D11): without ``ds_money`` a DeepSeek account is in no figure (counts included), as in summary.decision_views.
Pure functions: no clock (the day count comes from ``now_ms``), no network, seeds from sha256 of constant strings: the same data always gives the
same numbers.
"""

from __future__ import annotations

import hashlib
import math
from typing import Iterable, Optional

import numpy as np

from .exits import start_equity

DAY = 86_400_000
HORIZON = 30                          # the simulated month, in days
N_BOOT = 2000                         # simulated months per kind
MIN_DAYS = 7                          # fewer distinct days with a close: no numbers
MIN_TRADES = 30                       # fewer closed trades in the kind: no numbers
GOAL = 4.0                            # the owners' goal: x4 a month
PCTS = (5, 25, 50, 75, 95)
PCT_KEYS = ("p05", "p25", "p50", "p75", "p95")
CI = 0.90                             # the interval of the edge against the coin
EDGE_OUTER = 600                      # resamples of the observed days for that interval ...
EDGE_INNER = 300                      # ... and simulated months on each of them
EDGE_CHUNK = 100
SEED_ROOT = "monthsim-v1"
EPS = 1e-9
# (pair id, the real kind, its coin-flip twin): the lineup suffixes this block is about, in this order
PAIRS = (("live", "-fq", "-fqc"), ("control", "-ld", "-ldc"))
WANTED = tuple(s for _p, real, coin in PAIRS for s in (real, coin))
PAIR_OF = {s: (p, real, coin) for p, real, coin in PAIRS for s in (real, coin)}
GROUP_KO = {"live": "실전 후보", "control": "대조"}
FEW_FIELDS = ("percentiles", "p_x2", "p_x4", "p_below_half", "p_loss", "linear_multiple", "single_account")


def _seed(*parts) -> int:
    """summary._seed: the first 8 hex digits of the sha256 of the parts joined by '|'."""
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


def _shown(a: dict, ds_money: bool) -> bool:
    """summary._shown (D11): every core account, a DeepSeek one only with ``ds_money``."""
    return a.get("kind") != "ds" or bool(ds_money)


def _fin(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _r(x, nd: int = 4) -> Optional[float]:
    v = _fin(x)
    return None if v is None else round(v, nd)


def _nan(x) -> float:
    v = _fin(x)
    return float("nan") if v is None else v


def _cols(trades: Optional[Iterable[dict]]) -> tuple:
    """(UTC day number, P&L) arrays of an account's closed trades that have a finite exit time and P&L."""
    ts = list(trades or [])
    try:
        ex = np.array([t.get("exit_time") for t in ts], dtype=float)
        pn = np.array([t.get("pnl") for t in ts], dtype=float)
    except (TypeError, ValueError):                       # a hand-made trade with a string where a number belongs
        ex = np.array([_nan(t.get("exit_time")) for t in ts], dtype=float)
        pn = np.array([_nan(t.get("pnl")) for t in ts], dtype=float)
    ok = np.isfinite(ex) & np.isfinite(pn)
    return np.floor(ex[ok] / DAY).astype(np.int64), pn[ok]


def _account_days(day: np.ndarray, pnl: np.ndarray, d0: int, D: int, equity0: float) -> tuple:
    """(daily return per window day, closed trades in the window, bool per window day with a close) of one account: the day's P&L over the
    wallet before the day (the start wallet plus every earlier P&L); 0 on a day without a close and once the wallet is gone."""
    before = float(pnl[day < d0].sum()) if len(day) else 0.0
    m = (day >= d0) & (day < d0 + D)
    n = int(m.sum())
    if not n:
        return np.zeros(D), 0, np.zeros(D, dtype=bool)
    daily = np.bincount(day[m] - d0, weights=pnl[m], minlength=D)
    seen = np.bincount(day[m] - d0, minlength=D) > 0
    wallet = equity0 + before + np.cumsum(daily) - daily          # the wallet at the start of each day
    r = np.where(wallet > 0, daily / np.where(wallet > 0, wallet, 1.0), 0.0)
    return np.maximum(r, -1.0), n, seen


def _logs(r: np.ndarray) -> np.ndarray:
    """ln(1 + r) of daily returns; a day that lost everything is a very large loss, not minus infinity."""
    return np.log1p(np.maximum(r, -1.0 + EPS))


def _finals(L: np.ndarray, idx: np.ndarray) -> np.ndarray:
    """The final multiples of the paths ``idx`` (days of the window, shape (paths, HORIZON)) of the log series ``L``."""
    return np.exp(np.clip(L[idx].sum(axis=1), -50.0, 50.0))


def _pcts(x: np.ndarray) -> dict:
    return {k: _r(v) for k, v in zip(PCT_KEYS, np.percentile(x, PCTS))}


def _edge(Lr: np.ndarray, Lc: np.ndarray, D: int, seed: int, fr: np.ndarray, fc: np.ndarray) -> dict:
    """The real kind against its coin twin. ``fr`` / ``fc``: their final multiples on the SAME ``N_BOOT`` day draws."""
    med_r, med_c = float(np.median(fr)), float(np.median(fc))
    rng = np.random.default_rng(seed)
    out = np.empty(EDGE_OUTER)
    for lo in range(0, EDGE_OUTER, EDGE_CHUNK):
        c = min(EDGE_CHUNK, EDGE_OUTER - lo)
        pool = rng.integers(0, D, size=(c, D))                                  # one resample of the observed days ...
        pick = rng.integers(0, D, size=(c, EDGE_INNER, HORIZON))                # ... a month of positions in that resample
        day = pool[np.arange(c)[:, None, None], pick]
        a = np.exp(np.clip(Lr[day].sum(axis=2), -50.0, 50.0))
        b = np.exp(np.clip(Lc[day].sum(axis=2), -50.0, 50.0))                   # the same days for both kinds: a paired difference
        out[lo:lo + c] = np.median(a, axis=1) - np.median(b, axis=1)
    lo, hi = np.percentile(out, [50 * (1 - CI), 100 - 50 * (1 - CI)])
    return {"status": "ok", "real_median": _r(med_r), "coin_median": _r(med_c), "diff": _r(med_r - med_c), "lo": _r(lo), "hi": _r(hi),
            "ci_level": CI, "zero_in_interval": bool(lo <= 0 <= hi), "coin_reaches_real_median": _r(float((fc >= med_r).mean())),
            "p_real_beats_coin": _r(float((fr > fc).mean())), "outer": EDGE_OUTER, "inner": EDGE_INNER}


def _single(R: np.ndarray, D: int) -> dict:
    """How far apart single accounts end: each account's observed ln multiple scaled to HORIZON days, across the accounts (no simulation)."""
    m = np.exp(np.clip(_logs(R).sum(axis=1) * (HORIZON / D), -30.0, 30.0))
    p5, p50, p95 = np.percentile(m, [5, 50, 95])
    return {"n": int(len(m)), "p05": _r(p5), "p50": _r(p50), "p95": _r(p95), "min": _r(m.min()), "max": _r(m.max()), "days": D}


def few_text(days: int, trades: int) -> str:
    return f"아직 자료가 모자랍니다 ({days}일, {trades}건 · {MIN_DAYS}일 · {MIN_TRADES}건부터)"


def notes_ko() -> list:
    """The honest limits, shown on the screen as they are."""
    return [
        "하루하루가 서로 독립이라고 보고 섞습니다. 실제 시장은 며칠씩 한 방향으로 이어지므로, 실제로 나올 범위는 여기 보이는 범위보다 넓을 수 있습니다.",
        "계좌 여러 개를 같은 비중으로 섞은 값이라, 계좌(후보) 하나만 쓸 때보다 범위가 좁습니다. ‘단일 후보’ 줄은 후보마다 지금 성적이 서로 얼마나 다른지 보여 줍니다 (앞으로의 운은 들어 있지 않습니다).",
        "닫힌 거래만 셉니다. 아직 열려 있는 포지션과 오늘(진행 중인 날)은 넣지 않았습니다.",
        f"날 수가 적으면 범위가 매우 넓고 쉽게 틀립니다. 거래가 있던 날이 {MIN_DAYS}일보다 적거나 거래가 {MIN_TRADES}건보다 적으면 계산하지 않습니다.",
        "지금까지의 날들을 무작위로 다시 섞어 본 결과이지, 앞으로의 약속이나 예측이 아닙니다.",
    ]


def _mult(x: float) -> str:
    return f"{x:.2f}배" if x < 10 else f"{x:.1f}배"


def _headline(kinds: list, equity0: float) -> str:
    """One sentence: counts and the median only, never a promise. It is about the first kind (실전 후보, else 대조) the lineup has."""
    by = {k["suffix"]: k for k in kinds}
    for pid, real, coin in PAIRS:
        k = by[real]
        if k["status"] == "none":
            continue
        name = GROUP_KO[pid]
        if k["status"] == "few":
            return f"{name}는 {k['few_ko']}"
        m = k["percentiles"]["p50"]
        t = f"{name} {k['days']}일 · {k['n_trades']:,}건: 한 달({HORIZON}일) 이어진다고 해 본 중앙값은 {_mult(m)} (${equity0:,.0f} → ${equity0 * m:,.0f})"
        if by[coin]["status"] == "ok":
            t += f", 동전 짝은 {_mult(by[coin]['percentiles']['p50'])}"
        return t + "입니다."
    return "아직 자료가 없습니다."


def monthsim_views(book: dict, accts: list, lineup: Optional[list], start_ms: Optional[int], now_ms: Optional[int], ds_money: bool = False,
                   equity0: Optional[float] = None) -> dict:
    """The 한 달 시뮬 block (league.json key ``monthsim``), JSON-safe:

    {"horizon_days": 30, "boot": 2000, "goal_multiple": 4.0, "min_days": 7, "min_trades": 30, "ci_level": 0.9, "equity0", "start_ms",
     "through_ms" (the end of the last complete UTC day counted), "window_days", "ds_in_stats", "headline_ko", "note_ko": [...], "kinds": [...]}

    ``kinds``: four entries in the order -fq, -fqc, -ld, -ldc: {suffix, role, label_ko, short_ko, pair ("live" | "control"), is_coin, twin (the
    suffix of the real kind's coin twin / the coin's real kind), status ("ok" | "few" | "none": the kind is not in the lineup), days (distinct
    days with a close), window_days, n_accounts, n_trades, need {days, trades}, few_ko, observed_multiple (the basket's compounded multiple so
    far), linear_multiple (1 + the average daily gain x 30; None unless ok), percentiles {p05, p25, p50, p75, p95} (final multiple of 30 days),
    p_x2, p_x4, p_below_half, p_loss, single_account {n, p05, p50, p95, min, max, days}, edge_vs_coin (real kinds: {status, real_median,
    coin_median, diff, lo, hi, ci_level, zero_in_interval, coin_reaches_real_median, p_real_beats_coin}; None on a coin kind)}. A kind with
    status "few" has the counts and observed_multiple and nothing else (no percentile, no probability).

    ``start_ms`` / ``now_ms``: the league start and the engine's processed time. The window is the UTC days from the start's day to the last
    COMPLETE day before ``now_ms``; without them it is the first and the last day with a trade of these kinds."""
    eq0 = _fin(equity0)
    eq0 = float(start_equity()) if eq0 is None or eq0 <= 0 else eq0
    lu = [k for k in lineup or [] if isinstance(k, dict) and k.get("role") and k.get("suffix")]
    meta = {k["suffix"]: k for k in lu}
    suffix_of = {k["role"]: k["suffix"] for k in lu}
    ids: dict = {s: [] for s in WANTED}
    for a in accts or []:
        s = suffix_of.get(a.get("role"))
        if s in ids and a.get("id") is not None and _shown(a, ds_money):
            ids[s].append(a["id"])
    book = book or {}
    cols = {s: [_cols(book.get(i)) for i in ids[s]] for s in WANTED}
    # the window of whole UTC days
    have = [d for lst in cols.values() for d, _p in lst if len(d)]
    st, nw = _fin(start_ms), _fin(now_ms)
    d0 = int(st // DAY) if st is not None else (min(int(d.min()) for d in have) if have else 0)
    d1 = int(nw // DAY) - 1 if nw is not None else (max(int(d.max()) for d in have) if have else d0 - 1)
    D = max(0, d1 - d0 + 1)
    # per kind: the accounts' daily returns
    calc: dict = {}
    for s in WANTED:
        rs, n_tr, seen = [], 0, np.zeros(D, dtype=bool)
        for day, pnl in cols[s]:
            if not D:
                break
            r, n, sn = _account_days(day, pnl, d0, D, eq0)
            if n:
                rs.append(r)
                n_tr += n
                seen |= sn
        R = np.vstack(rs) if rs else np.zeros((0, D))
        calc[s] = {"R": R, "n_trades": n_tr, "days": int(seen.sum()), "L": _logs(R.mean(axis=0)) if len(R) else np.zeros(D)}
    paths: dict = {}
    for _pid, real, coin in PAIRS:
        ok = [s for s in (real, coin) if calc[s]["days"] >= MIN_DAYS and calc[s]["n_trades"] >= MIN_TRADES]
        if ok:                                                    # one set of day draws per pair, from the real kind's name
            idx = np.random.default_rng(_seed(SEED_ROOT, real)).integers(0, D, size=(N_BOOT, HORIZON))
            for s in ok:
                paths[s] = _finals(calc[s]["L"], idx)
    kinds = []
    for s in WANTED:
        pid, real, coin = PAIR_OF[s]
        k, c = meta.get(s), calc[s]
        e = {"suffix": s, "role": k["role"] if k else s[1:], "label_ko": k.get("label_ko") if k else None, "short_ko": k.get("short_ko") if k else None,
             "pair": pid, "is_coin": s == coin, "twin": coin if s == real else real, "status": "ok", "days": c["days"], "window_days": D,
             "n_accounts": int(len(c["R"])), "n_trades": c["n_trades"], "need": {"days": MIN_DAYS, "trades": MIN_TRADES}, "few_ko": None,
             "observed_multiple": _r(float(np.prod(1.0 + np.maximum(c["R"].mean(axis=0), -1.0)))) if len(c["R"]) else None,
             **{f: None for f in FEW_FIELDS}, "edge_vs_coin": None}
        if k is None or not ids[s]:
            e.update(status="none", few_ko="이 종류의 계좌가 이 리그에 없습니다")
        elif s not in paths:
            e.update(status="few", few_ko=few_text(c["days"], c["n_trades"]))
        else:
            f = paths[s]
            obs = e["observed_multiple"] or 0.0
            e.update(percentiles=_pcts(f), p_x2=_r(float((f >= 2.0).mean())), p_x4=_r(float((f >= GOAL).mean())),
                     p_below_half=_r(float((f < 0.5).mean())), p_loss=_r(float((f < 1.0).mean())),
                     linear_multiple=_r(max(0.0, 1.0 + (obs - 1.0) * HORIZON / D)), single_account=_single(c["R"], D))
        kinds.append(e)
    by = {e["suffix"]: e for e in kinds}
    for _pid, real, coin in PAIRS:
        r, t = by[real], by[coin]
        if r["status"] == "ok" and t["status"] == "ok":
            r["edge_vs_coin"] = _edge(calc[real]["L"], calc[coin]["L"], D, _seed(SEED_ROOT, "edge", real), paths[real], paths[coin])
        else:
            r["edge_vs_coin"] = {"status": "none" if "none" in (r["status"], t["status"]) else "few"}
    return {"horizon_days": HORIZON, "boot": N_BOOT, "goal_multiple": GOAL, "min_days": MIN_DAYS, "min_trades": MIN_TRADES, "ci_level": CI,
            "equity0": eq0, "start_ms": None if st is None else int(st), "through_ms": (d0 + D) * DAY if D else None, "window_days": D,
            "ds_in_stats": bool(ds_money), "headline_ko": _headline(kinds, eq0), "note_ko": notes_ko(), "kinds": kinds}

"""후보 리그 watch summary for the dashboard (research/fullgrid/WATCH_PREREG.md 2-3): the pools, the checkpoint
conditions as they stand now, weekly sums and per-strategy pools, from every closed trade of every account.

Unit (WATCH_PREREG 2): P&L per closed trade as a fraction of the wallet before it; a pool's mean is the mean over all
closed trades of its accounts (not the mean of the accounts' means). Weeks are UTC weeks from Monday. The C2 preview p
is the study's one-sided week-block bootstrap (research/fullgrid/run.py boot_mean_p, 2,000 resamples, seed
sha256("watch|<pool>|<UTC date>")); it is shown as 참고 only: the checkpoint numbers are the ones computed on the
checkpoint day (WATCH_PREREG 5).

DeepSeek money stays hidden unless ``ds_money`` (D11): its pools keep trade counts, wins and the yes / no of every
condition, never a mean, a sum or a p value.
"""

from __future__ import annotations

import datetime
import hashlib
import heapq
import json
import sqlite3
from typing import Iterable, Optional

import numpy as np

from .exits import start_equity

EQUITY = start_equity()               # the accounts' start wallet (exits.start_equity: CANDLEAGUE_EQUITY, else 5000)
ROLES = ("cand", "quarter", "exitonly", "base", "flip")
POOLS = ("core", "ds")
POOL_MIN_TRADES = 300                 # WATCH_PREREG 3.4
MIN_WEEKS_P = 4                       # the preview p is shown from four UTC weeks of trades
N_BOOT = 2000
WEEK = 7 * 86_400_000
MONDAY0 = 4 * 86_400_000              # 1970-01-05 was a Monday: UTC weeks start there
UTC = datetime.timezone.utc
# WATCH_PREREG 3: C1 one month after the start, C2 two months, C3 again a month later if C2 did not pass. The league
# started on 2026-10-11 (installed about 12:00 KST, research/fullgrid/DEVIATIONS.md; since 2026-10-12 its record starts
# at that install time), so the dates stay 11/11, 12/11 and 1/11.
CHECKPOINTS = (
    {"id": "C1", "date": "2026-11-11", "ko": "1차 점검", "after": "시작 후 한 달",
     "what": "멈출지 보기: 후보 평균이 기본값과 동전 둘 다보다 나쁘면 그 묶음을 멈춤"},
    {"id": "C2", "date": "2026-12-11", "ko": "2차 점검", "after": "시작 후 두 달",
     "what": "통과 보기: 평균 > 0 (운 검사 p < 0.05) · 기본값보다 · 동전보다 나음 · 거래 300번 이상"},
    {"id": "C3", "date": "2027-01-11", "ko": "3차 점검", "after": "시작 후 석 달",
     "what": "2차에서 통과 못 한 묶음만 한 번 더 (같은 기준)"},
)


def day_ms(date: str) -> int:
    d = datetime.datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=UTC)
    return int(d.timestamp() * 1000)


def week_of(ms: int) -> int:
    """The UTC Monday 00:00 (ms) of the week holding ``ms``."""
    return (int(ms) - MONDAY0) // WEEK * WEEK + MONDAY0


def returns(trades: Iterable[dict]) -> list[tuple[int, float]]:
    """(exit ms, P&L / wallet before) per closed trade, the trades in exit order from the $5,000 start."""
    eq, out = EQUITY, []
    for t in trades:
        p = float(t["pnl"])
        out.append((int(t["exit_time"]), p / eq if eq > 0 else 0.0))
        eq += p
    return out


def splits(trades: Iterable[dict], show_money: bool) -> dict:
    """One account's closed trades split by side and by coin: {"long": {n, wins, mean}, "short": ..., "coins": {coin: ...}}
    (mean in the league's unit; None when money is hidden). Shows whether a result rests on one side or one coin."""
    eq, rows = EQUITY, []
    for t in trades:
        p = float(t["pnl"])
        rows.append((int(t.get("side") or 0), str(t.get("symbol") or "").replace("USDT", ""), p / eq if eq > 0 else 0.0))
        eq += p

    def agg(xs):
        return {"n": len(xs), "wins": sum(r > 0 for r in xs),
                "mean": (sum(xs) / len(xs)) if xs and show_money else None}
    coins = sorted({c for _, c, _ in rows})
    return {"long": agg([r for sd, _, r in rows if sd > 0]), "short": agg([r for sd, _, r in rows if sd < 0]),
            "coins": {c: agg([r for _, cc, r in rows if cc == c]) for c in coins}}


TF_MS = {"15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000}


def _entries(trades: Iterable[dict]) -> list[tuple[int, str, int, float]]:
    """(entry ms, symbol, side, P&L / wallet before) per closed trade, sorted by entry."""
    eq, out = EQUITY, []
    for t in trades:
        p = float(t["pnl"])
        out.append((int(t.get("entry_time") or 0), str(t.get("symbol") or ""), int(t.get("side") or 0),
                    p / eq if eq > 0 else 0.0))
        eq += p
    return sorted(out)


def paired_lists(cand: Iterable[dict], exitonly: Iterable[dict], tf_ms: int) -> tuple[list, list, list]:
    """A 후보 account against its 청산만 바꾼 기본값 (the same exit on the default numbers): the results of the trades
    both took (same coin and side, entered within one bar of each other), of the trades only the custom numbers took,
    and of the trades only the default numbers took (the ones the custom numbers left out)."""
    a, b = _entries(cand), _entries(exitonly)
    used = [False] * len(b)
    both, only_a = [], []
    j0 = 0
    for ta, sa, da, ra in a:
        while j0 < len(b) and b[j0][0] < ta - tf_ms:
            j0 += 1
        hit = None
        for j in range(j0, len(b)):
            if b[j][0] > ta + tf_ms:
                break
            if not used[j] and b[j][1] == sa and b[j][2] == da:
                hit = j
                break
        if hit is None:
            only_a.append(ra)
        else:
            used[hit] = True
            both.append(ra)
    return both, only_a, [b[j][3] for j in range(len(b)) if not used[j]]


def r_marks(t: dict) -> tuple[Optional[float], Optional[float]]:
    """(best, worst) of one closed trade in R = |entry - first stop|: how far the price went its way (mfe_price) and
    against it (mae_price) while it was open; (None, None) when a price is missing (hidden or not recorded)."""
    try:
        e, s0, fav, adv, side = (float(t[k]) for k in ("entry_price", "stop_initial", "mfe_price", "mae_price", "side"))
    except (KeyError, TypeError, ValueError):
        return None, None
    r = abs(e - s0)
    if not (r > 0 and all(map(np.isfinite, (e, fav, adv)))):
        return None, None
    d = 1.0 if side > 0 else -1.0
    return max(0.0, d * (fav - e) / r), max(0.0, d * (e - adv) / r)


def _median(xs: list) -> Optional[float]:
    xs = sorted(xs)
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


def shape(trades: Iterable[dict], show_money: bool) -> dict:
    """What a strategy's trades look like (the 진입 차트 section line): how they ended (exit reason counts), the median
    hold, the losers that had first gone +1R its way (gave it back), the winners that had first gone 0.5R against (came
    back; both out of the trades whose R is known: r_n, r_wins), and the median best / worst in R. Counts stay when money
    is hidden; the R medians go with the prices."""
    n, wins, reasons, holds, gave, came, bests, worsts, r_n, r_wins = 0, 0, {}, [], 0, 0, [], [], 0, 0
    for t in trades:
        n += 1
        won = float(t.get("pnl") or 0) > 0
        wins += won
        why = str(t.get("exit_reason") or "?")
        reasons[why] = reasons.get(why, 0) + 1
        if t.get("entry_time") is not None and t.get("exit_time") is not None:
            holds.append(int(t["exit_time"]) - int(t["entry_time"]))
        best, worst = r_marks(t)
        if best is None:
            continue
        r_n += 1
        r_wins += won
        gave += (not won) and best >= 1.0
        came += won and worst >= 0.5
        bests.append(best)
        worsts.append(worst)
    return {"n": n, "wins": wins, "reasons": reasons, "hold_med_ms": _median(holds), "r_n": r_n, "r_wins": r_wins,
            "gave_back": gave, "came_back": came,
            "best_med": _median(bests) if show_money else None, "worst_med": _median(worsts) if show_money else None}


def _agg(xs: list, show_money: bool) -> dict:
    return {"n": len(xs), "wins": sum(r > 0 for r in xs), "mean": (sum(xs) / len(xs)) if xs and show_money else None}


def _seed(*parts) -> int:
    """research/fullgrid/run.py _seed."""
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


def boot_mean_p(week: np.ndarray, x: np.ndarray, n_boot: int, seed: int) -> Optional[float]:
    """research/fullgrid/run.py boot_mean_p: one-sided p that the mean per trade is <= 0, whole weeks resampled."""
    x = np.asarray(x, float)
    if not len(x):
        return None
    weeks, inv = np.unique(np.asarray(week), return_inverse=True)
    W = len(weeks)
    s, c = np.bincount(inv, x, W), np.bincount(inv, None, W)
    rng = np.random.default_rng(seed)
    bad, done = 0, 0
    while done < n_boot:
        m = min(10_000, n_boot - done)
        pick = rng.integers(0, W, size=(m, W))
        with np.errstate(invalid="ignore", divide="ignore"):
            mean = s[pick].sum(1) / c[pick].sum(1)
        bad += int((~(mean > 0)).sum())
        done += m
    return (1 + bad) / (n_boot + 1)


def _stats(rets: list[tuple[int, float]]) -> dict:
    x = [r for _, r in rets]
    return {"n": len(x), "wins": sum(r > 0 for r in x), "mean": (sum(x) / len(x)) if x else None}


def _weekly(rets: list[tuple[int, float]]) -> dict:
    out: dict[int, list] = {}
    for t, r in rets:
        w = out.setdefault(week_of(t), [0, 0, 0.0])
        w[0] += 1
        w[1] += r > 0
        w[2] += r
    return out


def roles_of(accts: list[dict]) -> tuple:
    """ROLES, then any other role the league's accounts have, in the order they first appear (the owner-exit league's kinds, the
    exit study's rule roles): every pool lists them all, so a screen that iterates the league's own roles finds each one."""
    extra = []
    for a in accts:
        r = a.get("role")
        if r not in ROLES and r not in extra:
            extra.append(r)
    return ROLES + tuple(extra)


def hold_of(trades: Iterable[dict]) -> dict:
    """Hold hours of closed trades: {n, median_h, share_gt8, share_gt18} (counts and hours only, so a DeepSeek pool keeps them, D11)."""
    h = sorted((int(t["exit_time"]) - int(t["entry_time"])) / 3_600_000.0 for t in trades
               if t.get("entry_time") is not None and t.get("exit_time") is not None)
    if not h:
        return {"n": 0, "median_h": None, "share_gt8": None, "share_gt18": None}
    return {"n": len(h), "median_h": round(_median(h), 3), "share_gt8": round(sum(x > 8 for x in h) / len(h), 4),
            "share_gt18": round(sum(x > 18 for x in h) / len(h), 4)}


def _pool(rets_by_role: dict, pool: str, now_ms: int, show_money: bool, roles: tuple = ROLES,
          week_roles: tuple = ("cand", "base", "flip")) -> dict:
    st = {role: _stats(rets_by_role.get(role, [])) for role in roles}
    cand, base, flip = st["cand"]["mean"], st["base"]["mean"], st["flip"]["mean"]
    have = cand is not None and base is not None and flip is not None
    c1_stop = (cand < base and cand < flip) if have else None
    weeks = _weekly(rets_by_role.get("cand", []))
    p = None
    if len(weeks) >= MIN_WEEKS_P:
        rr = rets_by_role["cand"]
        p = boot_mean_p(np.array([week_of(t) for t, _ in rr]), np.array([r for _, r in rr]), N_BOOT,
                        _seed("watch", pool, datetime.datetime.fromtimestamp(now_ms / 1000, UTC).strftime("%Y-%m-%d")))
    c2 = {"positive": None if cand is None else cand > 0,
          "beats_base": None if cand is None or base is None else cand > base,
          "beats_flip": None if cand is None or flip is None else cand > flip,
          "enough": st["cand"]["n"] >= POOL_MIN_TRADES,
          "p_ok": None if p is None else p < 0.05, "weeks": len(weeks)}
    c2["all"] = bool(all(c2[k] for k in ("positive", "beats_base", "beats_flip", "enough", "p_ok")))
    week_rows = []
    by_role_weeks = {role: _weekly(rets_by_role.get(role, [])) for role in week_roles}
    for w in sorted(set().union(*[set(v) for v in by_role_weeks.values()])):
        row = {"week_ms": w}
        for role, wk in by_role_weeks.items():
            n, wins, s = wk.get(w, [0, 0, 0.0])
            row[role] = {"n": n, "wins": wins, "sum": s if show_money else None,
                         "up": None if not n else s > 0}
        week_rows.append(row)
    if show_money:
        c2["p"] = p
    else:
        for role in roles:
            st[role]["mean"] = None
    return {"roles": st, "c1_stop": c1_stop, "c2": c2, "weeks": week_rows, "money": show_money}


def watch_summary(accts: list[dict], book: dict, now_ms: int, ds_money: bool = False) -> dict:
    """The dashboard's 점검 진행 data. ``book``: {account id: closed trades in exit order (dicts with exit_time, pnl)}.
    The owner-exit league (accounts with ``ox``, rulex.owner_accounts) has no 기본값 or 동전 accounts, so WATCH_PREREG's checkpoints
    do not apply to it: its ``checkpoints`` list is empty and ``owner`` is True; every pool lists every role of the league with its
    trades' hold hours (``hold``)."""
    rets = {a["id"]: returns(book.get(a["id"], [])) for a in accts}
    roles = roles_of(accts)
    owner = any(a.get("ox") for a in accts)
    present = {a["role"] for a in accts}
    week_roles = tuple(r for r in roles if r in present) if owner else ("cand", "base", "flip")
    pools, strategies = {}, {}
    for pool in POOLS:
        mine = [a for a in accts if a["kind"] == pool]
        by_role = {role: [r for a in mine if a["role"] == role for r in rets[a["id"]]] for role in roles}
        for v in by_role.values():
            v.sort()
        show = pool == "core" or ds_money
        pools[pool] = {"accounts": len(mine), "picks": sum(a["role"] == "cand" for a in mine),
                       **_pool(by_role, pool, now_ms, show, roles, week_roles),
                       "hold": {role: hold_of([t for a in mine if a["role"] == role for t in book.get(a["id"], [])]) for role in roles}}
        for name in sorted({a["name"] for a in mine}):
            per = {role: sorted(r for a in mine if a["name"] == name and a["role"] == role for r in rets[a["id"]])
                   for role in ROLES}
            s = {role: _stats(per[role]) for role in ("cand", "base", "flip")}
            cm, bm, fm = s["cand"]["mean"], s["base"]["mean"], s["flip"]["mean"]
            row = {"kind": pool, "tfs": sorted({a["tf"] for a in mine if a["name"] == name and a["role"] == "cand"},
                                              key=lambda t: ("15m", "30m", "1h", "4h").index(t)),
                   "n": s["cand"]["n"], "wins": s["cand"]["wins"], "enough": s["cand"]["n"] >= POOL_MIN_TRADES,
                   "positive": None if cm is None else cm > 0,
                   "beats_base": None if cm is None or bm is None else cm > bm,
                   "beats_flip": None if cm is None or fm is None else cm > fm,
                   "base_n": s["base"]["n"], "flip_n": s["flip"]["n"]}
            if show:
                row.update(mean=cm, base_mean=bm, flip_mean=fm)
            row["shape"] = shape([t for a in mine if a["name"] == name and a["role"] == "cand"
                                  for t in book.get(a["id"], [])], show)
            strategies[name] = row
    picks, pooled_pairs = {}, {pool: ([], [], []) for pool in POOLS}
    ids = {a["id"] for a in accts}
    for a in accts:
        if a["role"] == "cand":
            show = a["kind"] == "core" or ds_money
            picks[a["id"]] = splits(book.get(a["id"], []), show)
            picks[a["id"]]["shape"] = shape(book.get(a["id"], []), show)
            if f"{a['id']}-x" in ids:        # what the custom numbers added and left out (the same exit on both sides)
                lists = paired_lists(book.get(a["id"], []), book.get(f"{a['id']}-x", []), TF_MS.get(a["tf"], 3_600_000))
                picks[a["id"]]["paired"] = {k: _agg(x, show) for k, x in zip(("both", "cand_only", "default_only"), lists)}
                for acc, x in zip(pooled_pairs[a["kind"]], lists):
                    acc.extend(x)
    for pool in POOLS:
        show = pool == "core" or ds_money
        # the pool's long / short split over every cand account (each trade's own wallet-before unit)
        both = {"long": [], "short": []}
        for a in accts:
            if a["kind"] != pool or a["role"] != "cand":
                continue
            eq = EQUITY
            for t in book.get(a["id"], []):
                p = float(t["pnl"])
                both["long" if int(t.get("side") or 0) > 0 else "short"].append(p / eq if eq > 0 else 0.0)
                eq += p
        def wallet_dd(aid):
            eq = peak = EQUITY
            dd = 0.0
            for t in book.get(aid, []):
                eq += float(t["pnl"])
                peak = max(peak, eq)
                dd = max(dd, 1 - eq / peak if peak > 0 else 0.0)
            return eq, dd
        size = {}
        for role in ("cand", "quarter"):
            wd = [wallet_dd(a["id"]) for a in accts if a["kind"] == pool and a["role"] == role]
            dds = sorted(d for _, d in wd)
            size[role] = {"accounts": len(wd), "wallet_sum": sum(w for w, _ in wd) if show and wd else None,
                          "dd_median": (dds[len(dds) // 2] if len(dds) % 2 else (dds[len(dds) // 2 - 1] + dds[len(dds) // 2]) / 2)
                          if show and dds else None, "dd_max": max(dds) if show and dds else None}
        pools[pool]["size"] = size
        pools[pool]["sides"] = {k: {"n": len(v), "wins": sum(r > 0 for r in v), "mean": (sum(v) / len(v)) if v and show else None}
                                for k, v in both.items()}
        pools[pool]["paired"] = {k: _agg(x, show) for k, x in zip(("both", "cand_only", "default_only"), pooled_pairs[pool])}
    checkpoints = []
    for c in () if owner else CHECKPOINTS:
        ms = day_ms(c["date"])
        checkpoints.append({**c, "ms": ms, "days_left": (ms - now_ms) / 86_400_000})
    return {"checkpoints": checkpoints, "pools": pools, "strategies": strategies, "picks": picks,
            "min_trades": POOL_MIN_TRADES, "min_weeks_p": MIN_WEEKS_P, "owner": owner, "roles": list(roles)}


# ---------------------------------------------------------------- dashboard reads (dash.py /api/insight, /api/race)
# The dashboard computes these from the snapshot's trades.json (each account's newest LAST_TRADES trades and its whole
# equity line). The engine never calls them; watch_summary above is unchanged by them.
LAST_TRADES = 200                     # runner.LAST_TRADES: trades.json keeps each account's newest 200 trades
HOUR_MS = 3_600_000


def longest_run_p(n: int, q: Optional[float], run: int) -> Optional[float]:
    """P(``run`` or more losses in a row somewhere in ``n`` independent trades that each lose with probability q):
    1 - a_n, a_k = P(no such run in k trades) = 1 for k < run, 1 - q^run for k = run, and a_{k-1} - (1 - q) q^run
    a_{k-run-1} after (the first such run ends at trade k). None without a trade, a run or a rate."""
    if not n or n <= 0 or not run or run <= 0 or q is None or not 0.0 <= q <= 1.0:
        return None
    if run > n:
        return 0.0
    qr = q ** run
    a = [1.0] * (n + 1)
    a[run] = 1.0 - qr
    for k in range(run + 1, n + 1):
        a[k] = a[k - 1] - (1.0 - q) * qr * a[k - run - 1]
    return min(1.0, max(0.0, 1.0 - a[n]))


def run_quantile(n: int, q: Optional[float], prob: float) -> Optional[int]:
    """The longest losing run that ``n`` trades losing with probability q stay at or under with probability ``prob``
    (0.5: the usual longest run; 0.9: nine times in ten no longer). None without a trade or a rate."""
    if not n or n <= 0 or q is None:
        return None
    run = 0
    while run < n and (longest_run_p(n, q, run + 1) or 0.0) > 1.0 - prob:
        run += 1
    return run


def losing_runs(wins: Iterable[bool]) -> tuple[int, int]:
    """(longest, current) run of losses of trades in time order (oldest first)."""
    best = cur = 0
    for w in wins:
        cur = 0 if w else cur + 1
        best = max(best, cur)
    return best, cur


def won(t: dict) -> bool:
    """A closed trade's win: its P&L above 0, or the win label a trade without money keeps (DeepSeek money hidden)."""
    p = t.get("pnl")
    return float(p) > 0 if p is not None else bool(t.get("win"))


def cost_of(t: dict) -> Optional[float]:
    """Fees + funding of one closed trade in USDT (paid > 0). The margin is qty x entry / leverage, so the price move
    times the leverage is the ROE before costs (a liquidation's is -100%: it loses the margin); the costs are that
    minus the trade's net ROE, times its margin (P&L / ROE). None when a number is missing or the ROE is 0."""
    try:
        pnl, roe, lev = float(t["pnl"]), float(t["roe"]), float(t["leverage"])
        e, x, side = float(t["entry_price"]), float(t["exit_price"]), int(t["side"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (abs(roe) > 1e-12 and e > 0 and lev > 0 and np.isfinite(pnl) and np.isfinite(roe)):
        return None
    gross = -1.0 if t.get("exit_reason") == "LIQ" else side * (x / e - 1.0) * lev
    return (gross - roe) * (pnl / roe)


def account_insight(trades: Optional[list], total: Optional[int] = None, hidden: bool = False) -> dict:
    """One account's closed trades as the 계좌 자세히 '왜 이 성적인가' card and the 연패 lines read them. ``trades``: the
    snapshot's newest-first list (at most LAST_TRADES); ``total``: the account's real trade count (``capped`` when the
    list holds fewer); ``hidden``: the account's money must not leave the server (dash.ds_hidden): then only counts,
    exit reasons, wins and losing runs (labels), never P&L, costs or leverage.

    Keys: n, total, capped, wins, losses, reasons {SL: n, ...}, streak {max, cur, p, usual, rare} (p: the chance of a
    run as long as ``max`` at this win rate and n; usual / rare: the longest run half / nine in ten of such accounts stay
    at or under), hidden; with money: lev {"30": n, ...}, reason_pnl, avg_win, avg_loss (> 0), breakeven (the win rate the
    average win and loss need to break even), net, costs, gross (net + costs, over the cost_n trades whose costs are
    known), cost_n, big (the three largest losses), big_share (their share of all losses)."""
    rows = [t for t in (trades or []) if isinstance(t, dict)][::-1]                  # oldest first
    n = len(rows)
    wl = [won(t) for t in rows]
    wins = sum(wl)
    reasons: dict = {}
    for t in rows:
        r = str(t.get("exit_reason") or "?")
        reasons[r] = reasons.get(r, 0) + 1
    longest, cur = losing_runs(wl)
    q = (n - wins) / n if n else None
    streak = {"max": longest, "cur": cur, "p": longest_run_p(n, q, longest) if longest else None,
              "usual": run_quantile(n, q, 0.5), "rare": run_quantile(n, q, 0.9)}
    tot = int(total) if total is not None else n
    out = {"n": n, "total": max(tot, n), "capped": tot > n, "wins": wins, "losses": n - wins, "reasons": reasons,
           "streak": streak, "hidden": bool(hidden)}
    if hidden:
        out.update(lev=None, reason_pnl=None, avg_win=None, avg_loss=None, breakeven=None, net=None, costs=None,
                   gross=None, cost_n=0, big=None, big_share=None)
        return out
    lev: dict = {}
    rpnl: dict = {}
    gains, falls, net, costs, cost_n = [], [], 0.0, 0.0, 0
    for t in rows:
        if t.get("leverage"):
            k = str(int(t["leverage"]))
            lev[k] = lev.get(k, 0) + 1
        if t.get("pnl") is None:
            continue
        p = float(t["pnl"])
        r = str(t.get("exit_reason") or "?")
        rpnl[r] = rpnl.get(r, 0.0) + p
        net += p
        if p > 0:
            gains.append(p)
        elif p < 0:
            falls.append(p)
        c = cost_of(t)
        if c is not None:
            costs += c
            cost_n += 1
    avg_win = sum(gains) / len(gains) if gains else None
    avg_loss = -sum(falls) / len(falls) if falls else None
    big = sorted((t for t in rows if t.get("pnl") is not None and float(t["pnl"]) < 0), key=lambda t: float(t["pnl"]))[:3]
    keep = ("symbol", "side", "entry_time", "exit_time", "exit_reason", "leverage", "pnl", "roe")
    out.update(lev=lev, reason_pnl={k: round(v, 2) for k, v in rpnl.items()}, avg_win=avg_win, avg_loss=avg_loss,
               breakeven=avg_loss / (avg_win + avg_loss) if avg_win and avg_loss else None, net=round(net, 2),
               costs=round(costs, 2) if cost_n else None, gross=round(net + costs, 2) if cost_n else None, cost_n=cost_n,
               big=[{k: t.get(k) for k in keep} for t in big],
               big_share=(sum(float(t["pnl"]) for t in big) / sum(falls)) if falls else None)
    return out


def _pct(xs: list, q: float) -> float:
    """The q-th percentile (0..100) of a non-empty list, numpy's linear rule."""
    return float(np.percentile(np.asarray(xs, float), q))


def race(accts: list[dict], book: dict, start_ms: int, end_ms: int, max_points: int = 300) -> dict:
    """묶음 레이스: per pool (core / ds) and role, the median wallet of its accounts at each step from the start to
    ``end_ms`` (hourly; wider steps when the span holds more than max_points hours), from the complete equity lines
    of trades.json (the wallet after each closed trade; open positions are not counted). The 동전 accounts also carry
    their 25th and 75th percentiles (the spread of single 동전 accounts: a reference band, not a luck range for a
    median). An account without an equity line (DeepSeek money hidden) is left out; a pool with none carries money
    False and no lines."""
    import bisect
    start, end = int(start_ms), max(int(start_ms), int(end_ms))
    step = HOUR_MS * max(1, -(-(end - start) // HOUR_MS // max(1, max_points)))
    grid = list(range(start, end, step)) + [end]
    pools = {}
    every = roles_of(accts)                     # ROLES, then the owner-exit league's own kinds
    for pool in POOLS:
        roles = {}
        for role in every:
            lines = []
            for a in accts:
                if a.get("kind") != pool or a.get("role") != role:
                    continue
                eq = ((book or {}).get(a.get("id")) or {}).get("equity")
                if not eq:
                    continue
                ts = [int(p[0]) for p in eq]
                ws = [float(p[1]) for p in eq]
                lines.append((ts, ws))
            if not lines:
                continue
            cols = []
            for t in grid:
                vals = []
                for ts, ws in lines:
                    i = bisect.bisect_right(ts, t) - 1
                    vals.append(ws[i] if i >= 0 else EQUITY)
                cols.append(vals)
            row = {"n": len(lines), "median": [round(_pct(v, 50), 2) for v in cols]}
            if role == "flip":
                row["p25"] = [round(_pct(v, 25), 2) for v in cols]
                row["p75"] = [round(_pct(v, 75), 2) for v in cols]
            roles[role] = row
        pools[pool] = {"money": bool(roles), "roles": roles}
    return {"t": grid, "step_ms": step, "start_ms": start, "end_ms": end, "pools": pools}


# ---------------------------------------------------------------- the owner-exit league's kinds, pairs and events
# Three more keys of league.json (runner.write_snapshots, only when the league has a lineup, rulex.lineup): ``kinds`` (one scoreboard row per
# account kind), ``pairs`` (a main account's trade against the control account's trade on the same signal) and ``events`` (what the rules
# did). Pure functions of the accounts, the closed-trade book ({account id: trades in exit order}) and the account rows; the DeepSeek money
# rule (D11) is applied here once: a ROE, money or return figure counts DeepSeek accounts only with ``ds_money``.
CONTROL = "-ld"                       # the control account of a pick is <pick id>-ld (the old fixed-stop ladder)
REASONS = ("SL", "LOCK", "RULE", "TP", "LIQ")
SAME_DIFF = 0.0005                    # |main ROE - control ROE| under this (0.05 points of margin) is 'same'
PICK_MIN_TRADES = 5                   # best_pick / worst_pick: picks with at least this many closed trades
PAIRS_RECENT = 60
EVENTS_MAX = 200
MINUTE = 60_000
GROUP_PREFIX = (("메인", "main"), ("대조", "control"))      # the lineup labels' first word; any other label is a research account


def kind_group(label_ko) -> str:
    """"main" | "control" | "research" of a lineup kind by its Korean label's first word (메인 / 대조 / neither)."""
    s = str(label_ko or "").lstrip()
    for prefix, group in GROUP_PREFIX:
        if s.startswith(prefix):
            return group
    return "research"


def narrowed_keys(conn) -> set:
    """{(account, entry_time, exit_time)} of the stored trades whose entry context says the stop was narrowed (``rx_narrowed``, set by
    rulex.RuleUserLadder._narrow_stop). runner.closed_trades keeps no context, so the snapshot reads these few rows from the trades
    table (a plain text search first, then the exact key); empty when the table cannot be read."""
    out = set()
    try:
        for aid, d in conn.execute("SELECT account, data FROM trades WHERE instr(data, 'rx_narrowed') > 0"):
            try:
                t = json.loads(d)
                if (t.get("context") or {}).get("rx_narrowed"):
                    out.add((aid, t.get("entry_time"), t.get("exit_time")))
            except (ValueError, AttributeError):
                continue
    except sqlite3.Error:
        return set()
    return out


def _shown(a: dict, ds_money: bool) -> bool:
    """Whether this account's ROE / money may be added to a figure: every core account, a DeepSeek one only with ``ds_money`` (D11)."""
    return a.get("kind") != "ds" or bool(ds_money)


def _tkey(t: dict) -> tuple:
    """What makes two accounts' trades the same decision: coin, side and entry minute (one position at a time per account)."""
    return t.get("symbol"), t.get("side"), t.get("entry_time")


def _mean(xs: list) -> Optional[float]:
    return sum(xs) / len(xs) if xs else None


def kinds_summary(lineup: list, accts: list, book: dict, rows: list, start_ms: Optional[int], end_ms: Optional[int],
                  ds_money: bool = False, narrowed=None, equity0: Optional[float] = None) -> list:
    """One scoreboard dict per account kind of ``lineup`` (rulex.lineup), in its order:
    {role, suffix, label_ko, short_ko, group, accounts, picks, trades, wins, win_rate, avg_win_roe, avg_loss_roe, payoff, mean_roe,
    median_hold_h, trades_per_day, reasons, reason_mean_roe, narrowed_n, open_now, wallet_return_pct, max_dd_mean, best_pick,
    worst_pick, best_pick_roe, worst_pick_roe, ds_in_roe}.

    ``book``: {account id: closed trades in exit order} (runner.closed_trades); ``rows``: runner.account_rows (the wallet, the closed-trade
    drawdown and the open position); ``end_ms``: the time the trades are counted to (the engine's processed time); ``narrowed``:
    narrowed_keys; ``equity0``: the start wallet (default EQUITY). ``group`` is "main" | "control" | "research" (kind_group); ``picks`` the
    distinct picks with at least one closed trade; a win is a trade with P&L above 0; ROE is the trade's net ROE on margin; fractions, not
    percent (0.1 = 10%, the codebase's ``*_pct`` unit); ``payoff`` = avg_win_roe / |avg_loss_roe|; ``avg_loss_roe`` is negative (trades
    with P&L of exactly 0 are in neither average); ``median_hold_h`` entry to exit in hours; ``trades_per_day`` = trades / days between
    start and end (None before one day); ``reasons`` counts the exit reasons SL, LOCK, RULE, TP, LIQ (another reason is in ``trades`` only);
    ``narrowed_n`` the trades whose stop was narrowed; ``open_now`` the accounts holding a position;
    ``wallet_return_pct`` the mean over the kind's accounts of wallet / start wallet - 1 and ``max_dd_mean`` the mean closed-trade drawdown
    (None without such an account); ``best_pick`` / ``worst_pick`` the pick ids with the highest / lowest mean ROE among those with at
    least PICK_MIN_TRADES closed trades (``*_roe`` that mean).

    DeepSeek money (D11): these fields count DeepSeek accounts and trades ALWAYS: accounts, picks, trades, wins, win_rate, reasons,
    median_hold_h, trades_per_day, narrowed_n, open_now. These carry ROE / money / returns and so leave DeepSeek out (core accounts only)
    unless ``ds_money``: avg_win_roe, avg_loss_roe, payoff, mean_roe, reason_mean_roe, wallet_return_pct, max_dd_mean, best_pick,
    worst_pick, best_pick_roe, worst_pick_roe. ``ds_in_roe`` says which (``ds_money``). The mean of a reason (or a whole average) with no
    trade to average is None."""
    eq0 = EQUITY if equity0 is None else float(equity0)
    narrowed = narrowed or ()
    by_row = {r.get("id"): r for r in rows or []}
    mine: dict = {}
    for a in accts:
        mine.setdefault(a.get("role"), []).append(a)
    days = (end_ms - start_ms) / 86_400_000 if start_ms is not None and end_ms is not None else 0.0
    out = []
    for k in lineup or []:
        n = wins = narrowed_n = open_now = 0
        reasons = dict.fromkeys(REASONS, 0)
        r_roe: dict = {r: [] for r in REASONS}
        gains, falls, every, holds, ret, dds = [], [], [], [], [], []
        picks, pick_roe = set(), {}
        group = mine.get(k["role"], [])
        for a in group:
            aid = a["id"]
            row = by_row.get(aid) or {}
            show = _shown(a, ds_money)
            if row.get("open"):
                open_now += 1
            if show:
                if row.get("wallet") is not None:
                    ret.append(float(row["wallet"]) / eq0 - 1.0 if eq0 > 0 else 0.0)
                if row.get("max_dd") is not None:
                    dds.append(float(row["max_dd"]))
            trades = book.get(aid) or []
            if trades:
                picks.add(a.get("pick") or aid)
            for t in trades:
                n += 1
                wins += won(t)
                why = t.get("exit_reason")
                en, ex = t.get("entry_time"), t.get("exit_time")
                if en is not None and ex is not None:
                    holds.append((int(ex) - int(en)) / HOUR_MS)
                narrowed_n += (aid, en, ex) in narrowed
                if why in reasons:
                    reasons[why] += 1
                roe = t.get("roe")
                if not show or roe is None:
                    continue
                roe = float(roe)
                every.append(roe)
                if why in r_roe:
                    r_roe[why].append(roe)
                p = t.get("pnl")
                sign = float(p) if p is not None else roe
                if sign > 0:
                    gains.append(roe)
                elif sign < 0:
                    falls.append(roe)
                s = pick_roe.setdefault(a.get("pick") or aid, [0.0, 0])
                s[0] += roe
                s[1] += 1
        avg_win, avg_loss = _mean(gains), _mean(falls)
        ranked = {p: s[0] / s[1] for p, s in pick_roe.items() if s[1] >= PICK_MIN_TRADES}
        best = max(ranked, key=lambda p: (ranked[p], p)) if ranked else None
        worst = min(ranked, key=lambda p: (ranked[p], p)) if ranked else None
        out.append({
            "role": k["role"], "suffix": k.get("suffix"), "label_ko": k.get("label_ko"), "short_ko": k.get("short_ko"),
            "group": kind_group(k.get("label_ko")), "accounts": len(group), "picks": len(picks), "trades": n, "wins": wins,
            "win_rate": wins / n if n else None, "avg_win_roe": avg_win, "avg_loss_roe": avg_loss,
            "payoff": avg_win / abs(avg_loss) if avg_win is not None and avg_loss else None, "mean_roe": _mean(every),
            "median_hold_h": round(_median(holds), 3) if holds else None, "trades_per_day": n / days if days >= 1 else None,
            "reasons": reasons, "reason_mean_roe": {r: _mean(v) for r, v in r_roe.items()}, "narrowed_n": narrowed_n,
            "open_now": open_now, "wallet_return_pct": _mean(ret), "max_dd_mean": _mean(dds),
            "best_pick": best, "worst_pick": worst, "best_pick_roe": ranked[best] if best else None,
            "worst_pick_roe": ranked[worst] if worst else None, "ds_in_roe": bool(ds_money)})
    return out


def _main_roles(lineup: Optional[list]) -> list:
    return [k["role"] for k in lineup or [] if kind_group(k.get("label_ko")) == "main"]


def pairs_summary(lineup: list, accts: list, book: dict, ds_money: bool = False, equity0: Optional[float] = None) -> dict:
    """The main accounts against the control, trade by trade: {"control": "-ld", "by_role": {main role: {n, n_shown, better, worse, same,
    mean_diff_roe, sum_diff_pct_of_wallet, pct_better}}, "recent": [newest PAIRS_RECENT pairs]}.

    A pair is a trade of a main-group account (kind_group "main") and the trade of the control account <pick>-ld with the same coin, side and
    entry time (both closed); one control trade serves every main account of the pick. diff = main ROE - control ROE; better when diff >=
    SAME_DIFF, worse when diff <= -SAME_DIFF, else same. ``mean_diff_roe`` is the mean diff; ``sum_diff_pct_of_wallet`` the sum over the pairs
    of (main P&L / main wallet before the trade) - (control P&L / control wallet before it), the league's unit (returns); ``pct_better`` =
    better / n_shown (a fraction). ``recent`` is newest first by the main trade's exit time: {pick, name, tf, kind, symbol, side, entry_time,
    exit_time, role, a_reason, a_roe, b_reason, b_roe, diff_roe} (a = main, b = control).

    DeepSeek money (D11): ``n`` counts every pair. ``n_shown`` counts the pairs whose ROE is shown: core pairs, and DeepSeek pairs only with
    ``ds_money``; better, worse, same, mean_diff_roe, sum_diff_pct_of_wallet and pct_better are over those only (all None when n_shown is 0).
    A DeepSeek pair in ``recent`` keeps its reasons but has a_roe, b_roe and diff_roe None unless ``ds_money``."""
    eq0 = EQUITY if equity0 is None else float(equity0)
    roles = _main_roles(lineup)
    ids = {a["id"] for a in accts}
    ctl: dict = {}

    def control_of(cid: str) -> dict:
        m = ctl.get(cid)
        if m is None:                                    # {entry key: (trade, P&L / wallet before)} of one control account
            m, eq = {}, eq0
            for t in book.get(cid) or []:
                p = float(t.get("pnl") or 0.0)
                m.setdefault(_tkey(t), (t, p / eq if eq > 0 else 0.0))
                eq += p
            ctl[cid] = m
        return m

    stat = {r: [0, 0, 0, 0, 0, 0.0, 0.0] for r in roles}        # n, shown, better, worse, same, sum diff ROE, sum diff of wallet share
    found = []
    for a in accts:
        st = stat.get(a.get("role"))
        cid = f"{a.get('pick')}{CONTROL}"
        if st is None or cid not in ids or not book.get(a["id"]):
            continue
        cm = control_of(cid)
        show, eq = _shown(a, ds_money), eq0
        for t in book[a["id"]]:
            p = float(t.get("pnl") or 0.0)
            ret = p / eq if eq > 0 else 0.0
            eq += p
            hit = cm.get(_tkey(t))
            if hit is None:
                continue
            c, cret = hit
            st[0] += 1
            diff = None
            if show and t.get("roe") is not None and c.get("roe") is not None:
                diff = float(t["roe"]) - float(c["roe"])
                st[1] += 1
                if diff >= SAME_DIFF:
                    st[2] += 1
                elif diff <= -SAME_DIFF:
                    st[3] += 1
                else:
                    st[4] += 1
                st[5] += diff
                st[6] += ret - cret
            found.append((t.get("exit_time") or 0, a["id"], t.get("entry_time") or 0, a, t, c, diff))
    by_role = {}
    for r in roles:
        n, m, b, w, s, d, rs = stat[r]
        by_role[r] = {"n": n, "n_shown": m, "better": b if m else None, "worse": w if m else None, "same": s if m else None,
                      "mean_diff_roe": d / m if m else None, "sum_diff_pct_of_wallet": rs if m else None,
                      "pct_better": b / m if m else None}
    recent = []
    for ex, _aid, en, a, t, c, diff in heapq.nlargest(PAIRS_RECENT, found, key=lambda x: x[:3]):
        show = diff is not None
        recent.append({"pick": a.get("pick"), "name": a.get("name"), "tf": a.get("tf"), "kind": a.get("kind"), "symbol": t.get("symbol"),
                       "side": t.get("side"), "entry_time": t.get("entry_time"), "exit_time": t.get("exit_time"), "role": a.get("role"),
                       "a_reason": t.get("exit_reason"), "a_roe": t.get("roe") if show else None,
                       "b_reason": c.get("exit_reason"), "b_roe": c.get("roe") if show else None, "diff_roe": diff})
    return {"control": CONTROL, "by_role": by_role, "recent": recent}


def events_summary(lineup: list, accts: list, book: dict, narrowed=None, rows: Optional[list] = None, ds_money: bool = False) -> list:
    """The newest EVENTS_MAX rule-driven events of the main accounts, newest first: {time, account, pick, role, name, tf, kind, side,
    symbol, event, roe, hold_h, control_roe}. One row per trade, ``time`` its exit time; ``event`` is the first that applies:

    * "switch": the account's role is "sw" and its next trade starts in the same minute the trade ended, on the opposite side (the next
      trade may still be open: ``rows``' open position, runner.account_rows, counts as the next trade);
    * "narrowed": the trade's stop was narrowed (``narrowed``: narrowed_keys);
    * "rule_exit": the trade ended by a rule (exit reason RULE).

    ``control_roe``: the ROE of the pick's control (<pick>-ld) trade with the same coin, side and entry time, else None. ``hold_h``: hours
    from entry to exit. DeepSeek money (D11): roe and control_roe are None for a DeepSeek account unless ``ds_money`` (hold, side and coin
    are not money)."""
    main = set(_main_roles(lineup))
    narrowed = narrowed or ()
    opens = {r.get("id"): r["open"] for r in rows or [] if r.get("open")}
    found = []
    for a in accts:
        if a.get("role") not in main:
            continue
        aid, trades, sw = a["id"], book.get(a["id"]) or [], a["role"] == "sw"
        for i, t in enumerate(trades):
            ev = None
            ex = t.get("exit_time")
            if sw and ex is not None and t.get("side"):
                if i + 1 < len(trades):                          # the next trade, or the position still open (not yet a closed trade)
                    nxt = (trades[i + 1].get("side"), trades[i + 1].get("entry_time"))
                else:
                    o = opens.get(aid) or {}
                    nxt = (o.get("side"), o.get("since"))
                if nxt[0] == -t["side"] and nxt[1] is not None and int(nxt[1]) // MINUTE == int(ex) // MINUTE:
                    ev = "switch"
            if ev is None and (aid, t.get("entry_time"), ex) in narrowed:
                ev = "narrowed"
            if ev is None and t.get("exit_reason") == "RULE":
                ev = "rule_exit"
            if ev is not None:
                found.append((ex or 0, aid, t.get("entry_time") or 0, a, t, ev))
    ctl: dict = {}
    out = []
    for ex, aid, _en, a, t, ev in heapq.nlargest(EVENTS_MAX, found, key=lambda x: x[:3]):
        show = _shown(a, ds_money)
        cid = f"{a.get('pick')}{CONTROL}"
        if cid not in ctl:
            ctl[cid] = {}
            for c in book.get(cid) or []:
                ctl[cid].setdefault(_tkey(c), c.get("roe"))
        hold = (int(t["exit_time"]) - int(t["entry_time"])) / HOUR_MS if t.get("entry_time") is not None and t.get("exit_time") is not None else None
        out.append({"time": t.get("exit_time"), "account": aid, "pick": a.get("pick"), "role": a.get("role"), "name": a.get("name"),
                    "tf": a.get("tf"), "kind": a.get("kind"), "side": t.get("side"), "symbol": t.get("symbol"), "event": ev,
                    "roe": t.get("roe") if show else None, "hold_h": None if hold is None else round(hold, 3),
                    "control_roe": ctl[cid].get(_tkey(t)) if show else None})
    return out


def owner_views(lineup: list, accts: list, book: dict, rows: list, start_ms: Optional[int], end_ms: Optional[int], ds_money: bool = False,
                narrowed=None, equity0: Optional[float] = None) -> dict:
    """{"kinds", "pairs", "events"}: the three keys runner.write_snapshots adds to league.json in the owner-exit league."""
    return {"kinds": kinds_summary(lineup, accts, book, rows, start_ms, end_ms, ds_money, narrowed, equity0),
            "pairs": pairs_summary(lineup, accts, book, ds_money, equity0),
            "events": events_summary(lineup, accts, book, narrowed, rows, ds_money)}

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
from typing import Iterable, Optional

import numpy as np

EQUITY = 5000.0
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


def _pool(rets_by_role: dict, pool: str, now_ms: int, show_money: bool) -> dict:
    st = {role: _stats(rets_by_role.get(role, [])) for role in ROLES}
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
    by_role_weeks = {role: _weekly(rets_by_role.get(role, [])) for role in ("cand", "base", "flip")}
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
        for role in ROLES:
            st[role]["mean"] = None
    return {"roles": st, "c1_stop": c1_stop, "c2": c2, "weeks": week_rows, "money": show_money}


def watch_summary(accts: list[dict], book: dict, now_ms: int, ds_money: bool = False) -> dict:
    """The dashboard's 점검 진행 data. ``book``: {account id: closed trades in exit order (dicts with exit_time, pnl)}."""
    rets = {a["id"]: returns(book.get(a["id"], [])) for a in accts}
    pools, strategies = {}, {}
    for pool in POOLS:
        mine = [a for a in accts if a["kind"] == pool]
        by_role = {role: [r for a in mine if a["role"] == role for r in rets[a["id"]]] for role in ROLES}
        for v in by_role.values():
            v.sort()
        show = pool == "core" or ds_money
        pools[pool] = {"accounts": len(mine), "picks": sum(a["role"] == "cand" for a in mine),
                       **_pool(by_role, pool, now_ms, show)}
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
    for c in CHECKPOINTS:
        ms = day_ms(c["date"])
        checkpoints.append({**c, "ms": ms, "days_left": (ms - now_ms) / 86_400_000})
    return {"checkpoints": checkpoints, "pools": pools, "strategies": strategies, "picks": picks,
            "min_trades": POOL_MIN_TRADES, "min_weeks_p": MIN_WEEKS_P}

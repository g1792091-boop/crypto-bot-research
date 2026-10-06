"""조합 성과 (#/combo): "매매법끼리 합쳤을 때 성과가 어떻게 되나" from the paper v4 records. Read-only over paper3.db
(Data.conn: mode=ro): nothing is written, nothing trades, no account is merged or changed. Descriptive ('설명용, 판정 아님').

    GET /api/v4/combo/units      the picker: the 36 locked strategies (a unit = its 4 timeframe accounts summed) and
                                 their 144 accounts (a unit = one strategy@timeframe), the reel (optional: its own exits
                                 on 5m, compared with the three 5m coin flips), each with trades and the realized return;
                                 the one line on why DeepSeek is not in it (owners' D10 / D11: DeepSeek money only on the
                                 DeepSeek group screens; analysis.no_money)
    GET /api/v4/combo?u=S1,S2@1h&w=eq|custom|invvol|rp&p=50,50
                                 one combination of 2-8 units: the combined curve (each member gets weight x the summed
                                 starting capital and keeps its own trades: its P&L scales with its share, as a smaller or
                                 bigger wallet would trade the same signals), the members' own curves, the same number of
                                 same-timeframe coin-flip accounts combined the same way (the grey baseline, 참고), the
                                 numbers (return, P&L, max drawdown, worst day, trades, win rate, average trade, profit
                                 factor, payoff, winning days, daily volatility, Sharpe-like / Sortino-like (DAILY, not
                                 annualised), Calmar-like, time under water, recovery), each member's contribution and the
                                 combination without it (leave-one-out), the correlation inside it (daily P&L with the
                                 number of days; hourly as the early basis), 'same bet' details of member pairs
                                 (paperbot/overlap.py, 7-day window) and the diversification ratio (members' own max
                                 drawdown $ added up / the combination's)
    GET /api/v4/combo/corr?level=strategy|account&tf=1h&basis=day|hour
                                 전체 상관 지도: the 36 x 36 correlation (strategy level, or one timeframe's accounts), the
                                 top together-moving and most-opposite pairs, and the 계좌 겹침 pairs.top table
    GET /api/v4/combo/rules?kind=both|filter|vote|tf&a=S@1h&b=S2@4h&m=..&k=2&s=S|all&lo=1h&hi=4h
                                 합친 규칙 실험: a merged rule measured as ONE rule on recorded entries (each member keeps
                                 its own exits; entries are only filtered: an approximation), next to A alone and to the
                                 coin flips (alone and with the same filter)

Basis (one per answer, stated in ``basis_ko``): the curve and its max drawdown are mark-to-market from the 5-minute
``equity`` samples (open positions valued at the mark, what accounts.AccountBook writes) whenever every member has
them, else the closed-trade balance (realized). The daily numbers are the change of that curve between Korea-time
midnights (today's day still going on is included and marked). Trade numbers are closed trades.

Cost: one cache (``Book``) keeps the original accounts' 5-minute samples, closed trades and (for the rules) the signal
log in memory and reads only the new rows on each refresh (by time / id); the answers are computed in the background
(analysis.Heavy: one at a time, a request waits at most ``WAIT_S`` then answers ``pending``) and kept ``TTL_S``.
"""
from __future__ import annotations

import bisect
import contextlib
import itertools
import json
import math
import os
import sqlite3
import threading
import time
from typing import Optional

import numpy as np
from fastapi import HTTPException

from ...config import REEL_NAME, V3_TRADE_TFS
from . import combo_calc as K

DAY_MS = K.DAY_MS
HOUR_MS = K.HOUR_MS
TF_MS = {"5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000}
CORE_TFS = tuple(V3_TRADE_TFS)
KMIN, KMAX = 2, 8
SMALL_TRADES = 30            # checkpoint.MIN_TRADES: under it '아직 판단하기 이릅니다'
SMALL_DAYS = 7
RULE_SMALL = 20              # a merged rule's row under this many trades: '표본 적음'
MIN_DAY_CORR = 3             # daily correlation from this many days
MIN_HOUR_CORR = 24           # hourly correlation from this many hours (a full day)
OVERLAP_DAYS = 7             # 'same bet' window (overlap.report's default, /api/overlap?days=7)
OVERLAP_TTL_S = 600
TTL_S = 90                   # a combination / rule answer is reused this long
ACCOUNTS_TTL_S = 30
CORR_TTL_S = 600
WAIT_S = 2.5
CURVE_POINTS = 600
TOP_PAIRS = 8
LABEL = "설명용, 판정 아님"
INITIAL = 5000.0
DS_NOTE = ("딥시크 171개 계좌는 돈 숫자를 딥시크 묶음 화면에서만 보여 드리기로 해서(D10·D11) 조합에 넣지 않습니다. "
           "딥시크는 그 화면에서 개수와 비율로 봅니다.")
REEL_NOTE = ("릴스(5분 단타)는 넣을 수 있지만 자기 청산 규칙으로 5분봉에서만 돕니다: 비교 동전 봇은 5분봉 동전 봇이고, "
             "계좌 겹침(같은 베팅) 계산에는 들어가지 않습니다.")
APPROX_KO = ("각 구성원의 기록된 진입과 자기 청산을 그대로 쓰고 진입만 거른 근사입니다. 걸러진 거래 대신 들어갔을 다른 진입은 "
             "청산 기록이 없어 셀 수 없습니다.")
WEIGHT_KO = K.WEIGHT_KO
IN_SAMPLE_KO = ("이 비중은 지금까지의 기록 전체에서 잰 변동으로 정해 처음부터 썼습니다. 처음에는 몰랐을 정보를 쓴 셈이라 곡선이 "
                "실제보다 조금 좋아 보일 수 있습니다.")
FLIP_MONEY_KO = ("동전 봇 줄은 계좌 수가 달라(봉마다 3개) 손익 합을 나란히 놓지 않고 승률과 평균 순 ROE로만 비교합니다.")
# 5년 기준 tab: another builder's screen module; the page imports it only when it is there (no 404 for a missing
# file)
FIVE_Y_JS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "v4", "screens",
                         "combo-5y.js")


def _f(x, d: float = 0.0) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return d
    return v if math.isfinite(v) else d


def names_ko() -> dict:
    from ... import groups as G
    from ...agents.roster3 import STRATEGY_KO
    out = dict(STRATEGY_KO)
    out[REEL_NAME] = G.label_ko(REEL_NAME) or REEL_NAME
    return out


def tf_ko(tf: str) -> str:
    return {"5m": "5분", "15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간"}.get(tf, tf)


# ---------------------------------------------------------------- the cache
class Book:
    """The original accounts' records in memory (the 36's accounts, the coin flips, the reel), read incrementally:
    5-minute equity samples by time, closed trades by id, the signal log by id (only when a rule asks)."""

    def __init__(self, data):
        self.data = data
        self.lock = threading.RLock()
        self.reset(None)

    def reset(self, start: Optional[int]) -> None:
        """Forget every record (a new run). ``acc`` is kept: the request threads read it to check a request (it is
        replaced, never changed in place, by ``refresh_accounts``)."""
        self.start = start
        self.initial = INITIAL
        if not hasattr(self, "acc"):
            self.acc: dict = {}         # aid -> {"s", "tf", "kind"}
        self.eq: dict = {}              # aid -> (ts int64 array, equity float64 array)
        self.eq_last = 0
        self.tr: dict = {}              # aid -> list of trade dicts in exit order
        self.tr_last = 0
        self.sig: dict = {}             # (strategy, tf, symbol) -> ([bar_close], [side]) sorted by bar_close
        self.sig_last = 0
        self.sig_rows = 0
        self.overlap = None             # (monotonic time, payload)
        self.version = 0

    @contextlib.contextmanager
    def _conn(self):
        c = self.data.conn()
        try:
            yield c
        finally:
            c.close()

    @staticmethod
    def _read_accounts(c) -> dict:
        acc = {}
        for aid, s, tf, kind in c.execute("SELECT account_id, strategy, timeframe, kind FROM accounts "
                                          "WHERE kind IN ('strategy', 'random', 'reel')"):
            if kind == "strategy" and tf not in CORE_TFS:
                continue
            acc[aid] = {"s": s, "tf": tf, "kind": kind}
        return acc

    def refresh_accounts(self) -> dict:
        """The accounts table only (a few hundred rows): what a request needs to be checked on its own thread, without
        waiting for the records. Reused for ACCOUNTS_TTL_S."""
        hit = getattr(self, "_acc_at", 0.0)
        if self.acc and time.monotonic() - hit < ACCOUNTS_TTL_S:
            return self.acc
        with self._conn() as c:
            self.acc = self._read_accounts(c)
        self._acc_at = time.monotonic()
        return self.acc

    def refresh(self, now_ms: Optional[int] = None) -> None:
        from ...agents.digest import initial_equity
        from ...agents.triggers import run_start
        with self.lock, self._conn() as c:
            start = run_start(c)
            if start != self.start:
                self.reset(start)
            self.initial = float(initial_equity(c))
            acc = self._read_accounts(c)
            self.acc = acc
            self._acc_at = time.monotonic()
            ids = sorted(acc)
            if not ids:
                return
            ph = ",".join("?" * len(ids))
            if not self.eq_last:
                from ...agents.survival import _equity
                got = _equity(c, ids, int(start or 0))
                self.eq = {a: v for a, v in got.items()}
                self.eq_last = max((int(v[0][-1]) for v in got.values() if len(v[0])), default=0)
            else:
                new: dict = {}
                for aid, t, e in c.execute(f"SELECT account_id, ts, equity FROM equity WHERE account_id IN ({ph}) "
                                           "AND ts > ? ORDER BY ts", [*ids, self.eq_last]):
                    new.setdefault(aid, ([], []))
                    new[aid][0].append(int(t))
                    new[aid][1].append(float(e))
                for aid, (t, e) in new.items():
                    old = self.eq.get(aid)
                    tt, ee = np.asarray(t, dtype=np.int64), np.asarray(e, dtype=np.float64)
                    self.eq[aid] = (tt, ee) if old is None else (np.concatenate([old[0], tt]), np.concatenate([old[1], ee]))
                    self.eq_last = max(self.eq_last, int(tt[-1]))
            for i, aid, sym, entry, exit_t, pnl, roe, eqa, data in c.execute(
                    "SELECT id, account_id, symbol, entry_time, exit_time, pnl, roe, equity_after, data FROM trades "
                    "WHERE id > ? ORDER BY id", (self.tr_last,)):
                self.tr_last = max(self.tr_last, int(i))
                if aid not in acc:
                    continue
                try:
                    d = json.loads(data) if data else {}
                except (TypeError, ValueError):
                    d = {}
                d = d if isinstance(d, dict) else {}
                sig = d.get("signal_ts")
                rec = {"id": int(i), "sym": sym, "side": int(_f(d.get("side"), 0)) or 1, "entry": int(entry),
                       "bar": int(sig) + 1 if isinstance(sig, (int, float)) and sig > 0 else int(entry),
                       "exit": int(exit_t), "pnl": _f(pnl), "roe": _f(roe), "eq": _f(eqa)}
                lst = self.tr.setdefault(aid, [])
                if lst and rec["exit"] < lst[-1]["exit"]:
                    k = bisect.bisect_right([x["exit"] for x in lst], rec["exit"])
                    lst.insert(k, rec)
                else:
                    lst.append(rec)
            self.version += 1

    def refresh_signals(self) -> None:
        """The signal log of the 36, the coin flips and the reel (every computed signal, whatever happened to it: an
        account that was busy logs it too). Read by id; the DeepSeek rows are skipped."""
        names = {v["s"] for v in self.acc.values()}
        with self.lock, self._conn() as c:
            touched = set()
            for i, bar, tf, s, sym, side in c.execute(
                    "SELECT id, bar_close, timeframe, strategy, symbol, side FROM signal_log WHERE id > ? ORDER BY id",
                    (self.sig_last,)):
                self.sig_last = max(self.sig_last, int(i))
                if s not in names or not side:
                    continue
                key = (s, tf, sym)
                lst = self.sig.setdefault(key, ([], []))
                lst[0].append(int(bar))
                lst[1].append(1 if side > 0 else -1)
                touched.add(key)
                self.sig_rows += 1
            for key in touched:                         # keep each list in time order (ids follow time only roughly)
                b, sd = self.sig[key]
                if any(b[j] > b[j + 1] for j in range(len(b) - 1)):
                    order = sorted(range(len(b)), key=lambda j: b[j])
                    self.sig[key] = ([b[j] for j in order], [sd[j] for j in order])

    def held(self, aids) -> list:
        """(symbol, lo, hi): bar-close windows of the entries ``aids`` hold or wait on now (state 'accounts': the open
        position and the pending signals). Their signals were taken, not skipped, though no closed trade row exists
        yet. A position without its signal time covers the bar before its entry."""
        out: list = []
        try:
            with self._conn() as c:
                row = c.execute("SELECT data FROM state WHERE k = 'accounts'").fetchone()
            eng = (json.loads(row[0]) or {}).get("engines", {}) if row else {}
        except (sqlite3.Error, TypeError, ValueError, AttributeError):
            return out
        for a in aids:
            e = eng.get(a) if isinstance(eng, dict) else None
            if not isinstance(e, dict):
                continue
            bar = TF_MS.get(str(a).split("@", 1)[-1], HOUR_MS)
            p = e.get("position")
            if isinstance(p, dict) and p.get("symbol"):
                sig = p.get("signal") if isinstance(p.get("signal"), dict) else {}
                ts = sig.get("ts")
                if isinstance(ts, (int, float)) and ts > 0:
                    out.append((p["symbol"], int(ts) + 1, int(ts) + 1))
                elif isinstance(p.get("entry_time"), (int, float)):
                    out.append((p["symbol"], int(p["entry_time"]) - bar, int(p["entry_time"])))
            for q in e.get("pending") or []:
                if isinstance(q, dict) and q.get("symbol") and isinstance(q.get("ts"), (int, float)):
                    out.append((q["symbol"], int(q["ts"]) + 1, int(q["ts"]) + 1))
        return out

    # ---------------------------------------------------------------- reading the cache
    def strategies(self) -> list:
        from ...agents.roster3 import STRATEGY_KO
        order = {s: i for i, s in enumerate(STRATEGY_KO)}
        names = sorted({v["s"] for v in self.acc.values() if v["kind"] == "strategy"}, key=lambda s: (order.get(s, 999), s))
        return names

    def accounts_of(self, strategy: str, kind: str = "strategy") -> list:
        tf_i = {tf: i for i, tf in enumerate(("5m",) + CORE_TFS)}
        return sorted((a for a, v in self.acc.items() if v["s"] == strategy and v["kind"] == kind),
                      key=lambda a: tf_i.get(self.acc[a]["tf"], 9))

    def flips(self, tf: str) -> list:
        return sorted(a for a, v in self.acc.items() if v["kind"] == "random" and v["tf"] == tf)

    def trades(self, aids) -> list:
        out = []
        for a in aids:
            out.extend(self.tr.get(a, []))
        out.sort(key=lambda x: (x["exit"], x["id"]))
        return out

    def has_equity(self, aids) -> bool:
        return all(a in self.eq and len(self.eq[a][0]) for a in aids)

    def unit_curve(self, aids, now: int, mark: bool) -> tuple[np.ndarray, np.ndarray]:
        """The summed curve of ``aids`` with the start in front: mark-to-market (5-minute samples at the times every
        account has one) or the closed-trade balance (at every exit and now)."""
        cap = self.initial * len(aids)
        start = int(self.start or now)
        if mark:
            common = None
            for a in aids:
                t = self.eq[a][0]
                t = t[(t > start) & (t <= now)]
                common = t if common is None else np.intersect1d(common, t, assume_unique=True)
            common = np.zeros(0, dtype=np.int64) if common is None else common
            tot = np.zeros(len(common))
            for a in aids:
                t, e = self.eq[a]
                tot += e[np.searchsorted(t, common)]
            return np.r_[start, common].astype(np.int64), np.r_[cap, tot]
        tr = [x for x in self.trades(aids) if x["exit"] <= now]
        ts = [start] + [x["exit"] for x in tr] + [int(now)]
        vals = np.r_[0.0, np.cumsum([x["pnl"] for x in tr]) if tr else np.zeros(0)]
        vals = np.r_[vals, vals[-1]] + cap
        return np.asarray(ts, dtype=np.int64), vals

    def signals_of(self, strategy: str, tfs, symbol: str) -> tuple[list, list]:
        bars, sides = [], []
        for tf in tfs:
            b, s = self.sig.get((strategy, tf, symbol), ([], []))
            bars.extend(b)
            sides.extend(s)
        if len(tfs) > 1 and bars:
            order = sorted(range(len(bars)), key=lambda j: bars[j])
            bars, sides = [bars[j] for j in order], [sides[j] for j in order]
        return bars, sides


# ---------------------------------------------------------------- units
class Unit:
    __slots__ = ("key", "kind", "strategy", "tf", "aids", "group", "name_ko")

    def __init__(self, key, kind, strategy, tf, aids, group, name_ko):
        self.key, self.kind, self.strategy, self.tf, self.aids = key, kind, strategy, tf, aids
        self.group, self.name_ko = group, name_ko

    @property
    def tfs(self) -> list:
        return [k.split("@", 1)[1] for k in self.aids]

    def as_dict(self) -> dict:
        return {"key": self.key, "kind": self.kind, "strategy": self.strategy, "tf": self.tf, "accounts": list(self.aids),
                "group": self.group, "name_ko": self.name_ko}


def parse_units(book: Book, text: Optional[str], kmin: int = KMIN, kmax: int = KMAX) -> list:
    """'S1,S2@1h,REEL_H1' -> [Unit] (400 with a Korean message for anything else: DeepSeek, coin flips, unknown names,
    a strategy together with one of its own accounts, fewer than kmin or more than kmax)."""
    keys = [x.strip() for x in str(text or "").split(",") if x.strip()]
    seen, units = set(), []
    names = names_ko()
    for key in keys:
        if key in seen:
            continue
        seen.add(key)
        if len(key) > 80:
            raise HTTPException(400, "이름이 너무 깁니다")
        if "@" in key:
            v = book.acc.get(key)
            if v is None or v["kind"] not in ("strategy", "reel"):
                raise HTTPException(400, _why_not(book, key))
            grp = "reel" if v["kind"] == "reel" else "core"
            units.append(Unit(key, "account", v["s"], v["tf"], [key], grp,
                              f"{names.get(v['s'], v['s'])} · {tf_ko(v['tf'])}"))
        else:
            kind = "reel" if key == REEL_NAME else "strategy"
            aids = book.accounts_of(key, kind)
            if not aids:
                raise HTTPException(400, _why_not(book, key))
            units.append(Unit(key, "strategy" if kind == "strategy" else "account", key, None if kind == "strategy" else "5m",
                              aids, "reel" if kind == "reel" else "core", names.get(key, key)))
    every = [a for u in units for a in u.aids]
    if len(every) != len(set(every)):
        raise HTTPException(400, "같은 계좌가 두 번 들어갔습니다 (매매법 전체와 그 매매법의 봉 계좌를 같이 고를 수 없음)")
    if len(units) < kmin:
        raise HTTPException(400, f"{kmin}개 이상 골라 주세요")
    if len(units) > kmax:
        raise HTTPException(400, f"{kmax}개까지 고를 수 있습니다")
    return units


def _why_not(book: Book, key: str) -> str:
    s = key.split("@", 1)[0]
    if s.startswith("RANDOM_"):
        return "동전 봇은 조합에 넣지 않습니다 (회색 비교선으로 따로 나옵니다)"
    from ...config import DS200_FAMILY
    if s in DS200_FAMILY:
        return "딥시크 계좌는 조합에 넣지 않습니다 (돈 숫자는 딥시크 화면에서만)"
    return f"모르는 매매법·계좌입니다: {key}"


# ---------------------------------------------------------------- the numbers of one combination
def _common(curves: list) -> np.ndarray:
    t = None
    for ts, _e in curves:
        t = ts if t is None else np.intersect1d(t, ts, assume_unique=True)
    return np.zeros(0, dtype=np.int64) if t is None else t


def _on(ts: np.ndarray, e: np.ndarray, grid: np.ndarray) -> np.ndarray:
    """``e`` carried forward onto ``grid`` (the value at or before each grid time; the first value before it)."""
    k = np.searchsorted(ts, grid, side="right") - 1
    return e[np.clip(k, 0, len(e) - 1)]


def _hour_rets(book: Book, units: list, now: int, mark: bool) -> list:
    if not mark:
        return [np.zeros(0) for _ in units]
    hs = [K.at_hours(*book.unit_curve(u.aids, now, True)) for u in units]
    common = _common(hs)
    return [K.returns(_on(t, e, common)) for t, e in hs]


def combination(book: Book, units: list, method: str, custom, now: int, overlap: Optional[dict]) -> dict:
    mark = all(book.has_equity(u.aids) for u in units)
    start = int(book.start or now)
    caps = np.array([book.initial * len(u.aids) for u in units])
    cap = float(caps.sum())
    raw = [book.unit_curve(u.aids, now, mark) for u in units]
    grid = np.unique(np.concatenate([t for t, _e in raw])) if not mark else _common(raw)
    E = np.vstack([_on(t, e, grid) for t, e in raw])            # (k, T) each unit's summed equity
    hr = _hour_rets(book, units, now, mark)
    wt = K.weights(method, hr, custom)
    w = np.asarray(wt["w"])
    f = cap * w / caps                                          # scale of each unit's P&L
    comb = (f[:, None] * E).sum(axis=0)
    cn = K.curve_numbers(grid, comb, cap)
    daily = K.day_ends(grid, comb, start, now, cap)
    dn = K.daily_numbers(daily, cn["ret"], cn["mdd_pct"])
    trades = []
    per_unit_tr = []
    for u, fi in zip(units, f):
        tr = [x for x in book.trades(u.aids) if x["exit"] <= now]
        per_unit_tr.append(tr)
        trades.extend((x["exit"], x["id"], x["pnl"] * fi) for x in tr)
    trades.sort()
    tn = K.trade_numbers([p for _e, _i, p in trades])

    members = []
    for i, u in enumerate(units):
        own = K.curve_numbers(grid, E[i], caps[i])
        tn_i = K.trade_numbers([x["pnl"] for x in per_unit_tr[i]])
        pnl_scaled = float(f[i] * (E[i][-1] - caps[i])) if len(grid) else 0.0
        members.append({**u.as_dict(), "cap": K.r(caps[i], 2), "weight": K.r(w[i], 4), "scale": K.r(f[i], 4),
                        "ret": own["ret"], "pnl": K.r(pnl_scaled, 2), "mdd_pct": own["mdd_pct"],
                        "mdd_usd_scaled": K.r(f[i] * (own["mdd_usd"] or 0.0), 2), "trades": tn_i["trades"],
                        "wins": tn_i["wins"], "win_rate": tn_i["win_rate"],
                        "vol": (wt.get("vol") or [None] * len(units))[i],
                        "risk_share": (wt.get("risk_share") or [None] * len(units))[i]})
    tot_pnl = cn["pnl"] or 0.0
    for m in members:
        m["share"] = (K.r(m["pnl"] / tot_pnl, 4) or 0.0) if abs(tot_pnl) > 0.005 else None

    # the leave-one-out combinations: the same weighting among the others
    loo = []
    if len(units) >= 2:
        for i in range(len(units)):
            keep = [j for j in range(len(units)) if j != i]
            sub_custom = [custom[j] for j in keep] if method == "custom" and custom and len(custom) == len(units) else None
            sw = np.asarray(K.weights(method, [hr[j] for j in keep], sub_custom)["w"])
            scap = float(caps[keep].sum())
            sc = ((scap * sw / caps[keep])[:, None] * E[keep]).sum(axis=0)
            sn = K.curve_numbers(grid, sc, scap)
            sd = K.daily_numbers(K.day_ends(grid, sc, start, now, scap), sn["ret"], sn["mdd_pct"])
            loo.append({"key": units[i].key, "ret": sn["ret"], "mdd_pct": sn["mdd_pct"], "sharpe_like": sd["sharpe_like"],
                        "d_ret": K.r((sn["ret"] or 0) - (cn["ret"] or 0)) if sn["ret"] is not None and cn["ret"] is not None else None,
                        "d_mdd": K.r((sn["mdd_pct"] or 0) - (cn["mdd_pct"] or 0))})

    # the coin-flip baseline: the same number of same-timeframe coin-flip accounts, scaled the same way
    flips = baseline(book, units, f, caps, cap, now, mark, grid)

    # correlation inside the combination: daily P&L (the basis), hourly changes (early)
    dmat = np.vstack([np.asarray(K.day_ends(grid, E[i], start, now, caps[i])["pnl"]) for i in range(len(units))])
    day_m, day_n = K.corr(dmat, MIN_DAY_CORR)
    if mark:
        hs = [K.at_hours(grid, E[i]) for i in range(len(units))]
        hm = np.vstack([np.diff(e) for _t, e in hs]) if hs and len(hs[0][1]) > 1 else np.zeros((len(units), 0))
    else:
        hm = np.zeros((len(units), 0))
    hour_m, hour_n = K.corr(hm, MIN_HOUR_CORR)

    own_dd = sum(m["mdd_usd_scaled"] or 0.0 for m in members)
    comb_dd = cn["mdd_usd"] or 0.0
    div = K.r(own_dd / comb_dd, 3) if comb_dd > 0.005 and own_dd > 0 else None
    div_note = (None if div is not None else "합친 곡선이 한 번도 고점 아래로 내려가지 않았습니다" if comb_dd <= 0.005
                else "구성원 누구도 아직 내려간 적이 없습니다")

    idx = K.thin_index(len(grid), [i for i in (_idx(grid, cn["mdd_trough_ts"]), _idx(grid, cn["mdd_peak_ts"])) if i is not None],
                       CURVE_POINTS)
    curve = {"t": grid[idx].tolist(), "combined": [K.r(v / cap - 1) for v in comb[idx]],
             "members": [[K.r(v / caps[i] - 1) for v in E[i][idx]] for i in range(len(units))],
             "flips": [K.r(v) for v in np.asarray(flips["path"])[idx]] if flips.get("path") is not None else None,
             "step_min": K.r((grid[-1] - grid[0]) / max(1, len(idx) - 1) / 60_000, 1) if len(grid) > 1 else None,
             "points": int(len(grid)), "thinned": bool(len(idx) < len(grid))}
    flips.pop("path", None)
    days_run = (now - start) / DAY_MS
    early = tn["trades"] < SMALL_TRADES or days_run < SMALL_DAYS
    return {
        "label": LABEL, "units": members, "k": len(units), "capital": K.r(cap, 2), "start": start, "now": int(now),
        "run_days": K.r(days_run, 3),
        "method": {"asked": method, "used": wt["used"], "asked_ko": WEIGHT_KO.get(method, method),
                   "used_ko": WEIGHT_KO.get(wt["used"], wt["used"]), "note": wt["note"], "points": wt["points"],
                   # inverse volatility / equal risk are measured on the whole record and applied from the start: the
                   # curve uses what was only known later (in-sample), which the page says
                   "in_sample": wt["used"] in ("invvol", "rp"),
                   "in_sample_ko": (IN_SAMPLE_KO if wt["used"] in ("invvol", "rp") else None)},
        "basis": "mark" if mark else "closed",
        "basis_ko": ("5분마다 기록한 자본 (열린 포지션은 그때 시세로 평가, 수수료·펀딩 포함)" if mark
                     else "닫힌 거래 기준 잔고 (5분 자본 기록이 아직 없어 거래가 끝날 때만 움직임)"),
        "mdd_basis_ko": ("최대 낙폭 = 위 곡선의 고점 대비 가장 깊은 하락 (5분 기록, 열린 포지션 포함)" if mark
                         else "최대 낙폭 = 닫힌 거래 기준 잔고의 고점 대비 가장 깊은 하락"),
        "curve": curve,
        "stats": {**{k: cn[k] for k in ("ret", "pnl", "mdd_pct", "mdd_usd", "mdd_peak_ts", "mdd_trough_ts", "recovered",
                                       "recovery_days", "under_water_share", "longest_under_water_days", "days_since_peak")},
                  **{k: dn[k] for k in ("days", "partial_last", "partial_day", "worst_day", "best_day", "win_days", "win_days_n", "daily_vol",
                                       "sharpe_like", "sortino_like", "calmar_like", "ratio_min_days")},
                  **tn},
        "flips": flips,
        "loo": loo,
        "corr": {"day": {"n": day_n, "m": day_m, "min": MIN_DAY_CORR}, "hour": {"n": hour_n, "m": hour_m, "min": MIN_HOUR_CORR},
                 "day_basis_ko": "하루 손익 = 한국 시간 자정마다 자본의 변화", "hour_basis_ko": "1시간마다 자본의 변화 (초반 참고용)"},
        "same_bet": same_bet(units, overlap),
        "div_ratio": div, "div_note": div_note, "div_basis_ko": "구성원 각자의 최대 낙폭($, 비중 반영) 합 ÷ 합친 곡선의 최대 낙폭($)",
        "small": {"trades": tn["trades"], "need": SMALL_TRADES, "days": K.r(days_run, 2), "need_days": SMALL_DAYS, "early": early,
                  "words": f"거래 {tn['trades']:,}건 · 아직 판단하기 이릅니다" if early else f"거래 {tn['trades']:,}건"},
        "ds_note": DS_NOTE, "reel_note": REEL_NOTE if any(u.group == "reel" for u in units) else None,
    }


def _idx(grid: np.ndarray, ts) -> Optional[int]:
    if ts is None or not len(grid):
        return None
    return int(min(len(grid) - 1, np.searchsorted(grid, ts)))


def baseline(book: Book, units: list, f: np.ndarray, caps: np.ndarray, cap: float, now: int, mark: bool,
             grid: np.ndarray) -> dict:
    """The same number of coin-flip accounts on the members' timeframes (RANDOM_1, 2, 3 in turn per timeframe; reused
    when a timeframe has more members than coin flips), each scaled like the member it stands in for. Return path
    (share of the summed capital), max drawdown and trades; no dollar amounts (a reference line, 참고)."""
    turn: dict = {}
    reused = 0
    picked = []
    for u in units:
        mine = []
        for a in u.aids:
            tf = a.split("@", 1)[1]
            pool = book.flips(tf)
            if not pool:
                return {"available": False, "note": f"{tf_ko(tf)}봉 동전 봇이 없어 비교선을 그리지 않습니다", "path": None}
            n = turn.get(tf, 0)
            if n >= len(pool):
                reused += 1
            mine.append(pool[n % len(pool)])
            turn[tf] = n + 1
        picked.append(mine)
    if mark and not all(book.has_equity(p) for p in picked):
        mark = False
    tot = np.zeros(len(grid))
    tr = []
    for i, p in enumerate(picked):
        t, e = book.unit_curve(p, now, mark)
        tot += f[i] * _on(t, e, grid)
        tr.extend(x["pnl"] for x in book.trades(p) if x["exit"] <= now)
    cn = K.curve_numbers(grid, tot, cap)
    tn = K.trade_numbers(tr)
    n_acc = sum(len(p) for p in picked)
    return {"available": True, "accounts": n_acc, "picked": [list(p) for p in picked], "reused": reused,
            "ret": cn["ret"], "mdd_pct": cn["mdd_pct"], "trades": tn["trades"], "win_rate": tn["win_rate"],
            "note": (f"동전 봇은 봉마다 3개뿐이라 {reused}개를 다시 썼습니다" if reused else None),
            "path": (tot / cap - 1) if len(grid) else None}


# ---------------------------------------------------------------- same bet (paperbot/overlap.py)
def overlap_snapshot(book: Book, now: Optional[int] = None) -> dict:
    """Pair matrices of the 7-day window (overlap.load_window + similarity: the 계좌 겹침 definitions), cached."""
    hit = book.overlap
    if hit is not None and time.monotonic() - hit[0] < OVERLAP_TTL_S and now is None:
        return hit[1]
    from ... import overlap as OV
    with book._conn() as c:
        w = OV.load_window(c, days=OVERLAP_DAYS, end=None)
    if w is None:
        snap = {"ready": False, "ids": {}, "rules": dict(OV.RULES), "note": "아직 자본 기록이 없습니다"}
    else:
        sim = OV.similarity(w)
        excl = w.excluded()
        S = np.flatnonzero(~excl)
        iu = np.triu_indices(len(S), 1)
        ok, cr = sim["sufficient"][np.ix_(S, S)][iu], sim["corr"][np.ix_(S, S)][iu]
        order = np.argsort(-np.where(ok, cr, -np.inf))[:20]
        top = []
        for q in order:                                   # the same rule as overlap.report's pairs.top
            if not ok[q]:
                break
            a, b = S[iu[0][q]], S[iu[1][q]]
            top.append({"a": w.ids[a], "b": w.ids[b], "corr": K.r(sim["corr"][a, b], 3),
                        "same_time": K.r(sim["same_time"][a, b], 3), "same_of_busy": K.r(sim["same_of_busy"][a, b], 3),
                        "common_days": K.r(sim["common_days"][a, b], 2)})
        span = [(w.last[j] - w.first[j]) * OV.STEP_MS / DAY_MS if w.first[j] >= 0 else 0.0 for j in S]
        # how close the closest pair is to the two thresholds (both accounts' trades: the smaller one counts)
        tr_s = np.asarray(w.trades)[S]
        pair_trades = int(np.minimum(tr_s[iu[0]], tr_s[iu[1]]).max()) if len(iu[0]) else 0
        cd = sim["common_days"][np.ix_(S, S)][iu]
        pair_days = float(np.nanmax(cd)) if len(cd) and np.isfinite(cd).any() else 0.0
        snap = {"ready": True, "ids": {a: j for j, a in enumerate(w.ids)}, "sim": sim, "trades": w.trades.tolist(),
                "first": w.first, "last": w.last, "rules": dict(OV.RULES), "top": top,
                "pairs": int(len(ok)), "sufficient": int(ok.sum()), "max_days": K.r(max(span) if span else 0.0, 2),
                "max_trades": int(max((w.trades[j] for j in S), default=0)), "pair_trades": pair_trades,
                "pair_days": K.r(pair_days, 2), "window": {"start": int(w.start), "end": int(w.end)}}
    book.overlap = (time.monotonic(), snap)
    return snap


def same_bet(units: list, snap: Optional[dict]) -> dict:
    out = {"window_days": OVERLAP_DAYS, "pairs": [], "ready": bool(snap and snap.get("ready"))}
    if not snap:
        return out
    rules = snap.get("rules") or {}
    out["rules"] = {"min_days": rules.get("min_days"), "min_trades": rules.get("min_trades")}
    if not snap.get("ready"):
        out["note"] = snap.get("note")
        return out
    ids, sim, trades = snap["ids"], snap["sim"], snap["trades"]
    for ua, ub in itertools.combinations(units, 2):
        best = None
        for a in ua.aids:
            for b in ub.aids:
                i, j = ids.get(a), ids.get(b)
                if i is None or j is None:
                    continue
                sb = sim["same_of_busy"][i, j]
                key = -1.0 if not np.isfinite(sb) else float(sb)
                if best is None or key > best[0]:
                    best = (key, a, b, i, j)
        row = {"a": ua.key, "b": ub.key}
        if best is None:
            row["missing"] = True                         # the reel (not in the overlap window)
        else:
            _k, a, b, i, j = best
            why = []
            if sim["common_days"][i, j] < (rules.get("min_days") or 7) - 1e-9:
                why.append("days")
            if trades[i] < (rules.get("min_trades") or 20) or trades[j] < (rules.get("min_trades") or 20):
                why.append("trades")
            row.update(accounts=[a, b], same_of_busy=K.r(sim["same_of_busy"][i, j], 3),
                       same_time=K.r(sim["same_time"][i, j], 3), corr=K.r(sim["corr"][i, j], 3),
                       common_days=K.r(sim["common_days"][i, j], 2), sufficient=bool(sim["sufficient"][i, j]),
                       why=why, trades=[int(trades[i]), int(trades[j])])
        out["pairs"].append(row)
    return out


# ---------------------------------------------------------------- the 36 x 36 map
def corr_map(book: Book, level: str, tf: Optional[str], basis: str, now: int, snap: Optional[dict]) -> dict:
    strategies = book.strategies()
    names = names_ko()
    if level == "account":
        tf = tf if tf in CORE_TFS else "1h"
        units = [(f"{s}@{tf}", [f"{s}@{tf}"]) for s in strategies if f"{s}@{tf}" in book.acc]
    else:
        level, tf = "strategy", None
        units = [(s, book.accounts_of(s)) for s in strategies]
    mark = all(book.has_equity(a) for _k, a in units) if units else False
    start = int(book.start or now)
    if basis == "hour" and mark:
        hs = [K.at_hours(*book.unit_curve(a, now, True)) for _k, a in units]
        common = _common(hs)
        M = np.vstack([np.diff(_on(t, e, common)) for t, e in hs]) if len(common) > 1 else np.zeros((len(units), 0))
        need = MIN_HOUR_CORR
    else:
        basis = "day"
        rows = []
        for _k, a in units:
            t, e = book.unit_curve(a, now, mark)
            rows.append(K.day_ends(t, e, start, now, book.initial * len(a))["pnl"])
        M = np.asarray(rows, dtype=np.float64) if rows else np.zeros((0, 0))
        need = MIN_DAY_CORR
    m, n = K.corr(M, need)
    keys = [k for k, _a in units]
    pairs = [(m[i][j], keys[i], keys[j]) for i in range(len(keys)) for j in range(i + 1, len(keys)) if m[i][j] is not None]
    ready = n >= need and bool(pairs)
    top = [{"a": a, "b": b, "r": v} for v, a, b in sorted(pairs, key=lambda x: (-x[0], x[1], x[2]))[:TOP_PAIRS]] if ready else []
    hedge = [{"a": a, "b": b, "r": v} for v, a, b in sorted(pairs, key=lambda x: (x[0], x[1], x[2])) if v < 0][:TOP_PAIRS] if ready else []
    trades = {k: sum(len(book.tr.get(x, [])) for x in a) for k, a in units}
    ov = {"window_days": OVERLAP_DAYS, "ready": bool(snap and snap.get("ready"))}
    if snap:
        rules = snap.get("rules") or {}
        ov.update(min_days=rules.get("min_days"), min_trades=rules.get("min_trades"), group_corr=rules.get("group_corr"))
        if snap.get("ready"):
            pick = lambda a: (book.acc.get(a) or {}).get("kind") == "strategy"  # noqa: E731  (an extra account: no)
            ov.update(top=[{**p, "pickable": pick(p["a"]) and pick(p["b"])} for p in snap["top"]], pairs=snap["pairs"],
                      sufficient=snap["sufficient"], max_days=snap["max_days"], max_trades=snap["max_trades"],
                      pair_days=snap.get("pair_days"), pair_trades=snap.get("pair_trades"))
    return {"label": LABEL, "level": level, "tf": tf, "basis": basis, "n": n, "need": need, "ready": ready,
            "basis_ko": ("하루 손익 (한국 시간 자정마다 자본의 변화" + (", 열린 포지션 포함)" if mark else ", 닫힌 거래 기준)")
                         if basis == "day" else "1시간마다 자본의 변화 (열린 포지션 포함, 초반 참고용)"),
            "units": [{"key": k, "name_ko": (names.get(k.split("@")[0], k.split("@")[0]) + (f" · {tf_ko(tf)}" if tf else "")),
                       "trades": trades[k]} for k in keys],
            "m": m, "top": top, "hedge": hedge, "overlap": ov, "start": start, "now": int(now),
            "early": (now - start) / DAY_MS < SMALL_DAYS, "early_days": SMALL_DAYS,
            "run_days": K.r((now - start) / DAY_MS, 3), "ds_note": DS_NOTE}


# ---------------------------------------------------------------- merged rules
RULE_KO = {"both": "A와 B가 같이 신호 줄 때만", "filter": "A에 B를 거르개로", "vote": "N개 중 K개 이상 같은 방향",
           "tf": "같은 매매법 봉 합의"}


def _rows_stats(label_ko: str, rid: str, trs: list, money: bool = True) -> dict:
    n = len(trs)
    wins = sum(1 for x in trs if x["pnl"] > 0)
    return {"id": rid, "label_ko": label_ko, "trades": n, "wins": wins, "win_rate": K.r(wins / n, 4) if n else None,
            "mean_roe": K.r(sum(x["roe"] for x in trs) / n, 4) if n else None,
            "pnl": K.r(sum(x["pnl"] for x in trs), 2) if money else None, "small": n < RULE_SMALL}


def _agrees(book: Book, strategy: str, tfs, sym: str, side: int, lo: int, hi: int) -> bool:
    """A signal of ``strategy`` on ``tfs`` for ``sym`` with ``side`` whose bar closed in (lo, hi]."""
    bars, sides = book.signals_of(strategy, tfs, sym)
    k = bisect.bisect_right(bars, hi) - 1
    while k >= 0 and bars[k] > lo:
        if sides[k] == side:
            return True
        k -= 1
    return False


def _latest(book: Book, strategy: str, tfs, sym: str, at: int) -> int:
    """The side of the latest signal of ``strategy`` on ``sym`` at or before ``at`` (0 = none yet)."""
    bars, sides = book.signals_of(strategy, tfs, sym)
    k = bisect.bisect_right(bars, at) - 1
    return sides[k] if k >= 0 else 0


def _parse_member(book: Book, key: str) -> Unit:
    return parse_units(book, key, kmin=1, kmax=1)[0]


def _busy_signals(book: Book, unit: Unit, passes, now: int) -> int:
    """Signals of ``unit`` (signal log, bar closed by ``now``) that never became one of its trades (the account was
    busy, or the signal came late / without a price) and that pass the rule: entries the merged rule would have wanted,
    with no exit to measure. The entry it holds or waits on now is not one of them (taken, not closed yet)."""
    taken = {(x["sym"], x["bar"]) for x in book.trades(unit.aids)}
    held = book.held(unit.aids)
    n = 0
    for (s, tf, sym), (bars, sides) in list(book.sig.items()):
        if s != unit.strategy or tf not in unit.tfs:
            continue
        for b, sd in zip(bars, sides):
            if b > now or (sym, b) in taken or any(hs == sym and lo <= b <= hi for hs, lo, hi in held):
                continue
            if passes(sym, sd, b, tf):
                n += 1
    return n


def check_rules(book: Book, q: dict) -> dict:
    """Every 400 a rule request can get, from the accounts alone (the request thread runs it): {kind, a, b, members,
    k, lo, hi, s} parsed."""
    kind = q.get("kind") or "both"
    if kind not in RULE_KO:
        raise HTTPException(400, "kind는 both · filter · vote · tf 중 하나입니다")
    out: dict = {"kind": kind}
    if kind in ("both", "filter"):
        a = _parse_member(book, q.get("a") or "")
        if a.kind != "account":
            raise HTTPException(400, "A는 봉 계좌 하나여야 합니다 (예: S1_EMA_RSI_CHOP@1h)")
        b = _parse_member(book, q.get("b") or "")
        if set(a.aids) & set(b.aids):
            raise HTTPException(400, "A와 B는 서로 다른 계좌여야 합니다")
        out.update(a=a, b=b)
    elif kind == "vote":
        members = parse_units(book, q.get("m") or "", kmin=2, kmax=6)
        try:
            kk = int(q.get("k") or 2)
        except (TypeError, ValueError):
            kk = 0
        if not 1 <= kk <= len(members):
            raise HTTPException(400, f"K는 1부터 {len(members)} 사이입니다")
        out.update(members=members, k=kk)
    else:
        lo, hi = q.get("lo") or "1h", q.get("hi") or "4h"
        if lo not in CORE_TFS or hi not in CORE_TFS or CORE_TFS.index(hi) <= CORE_TFS.index(lo):
            raise HTTPException(400, "봉 합의는 짧은 봉(lo)과 더 긴 봉(hi)을 고릅니다 (예: lo=1h, hi=4h)")
        st = q.get("s") or "all"
        if st != "all" and (book.acc.get(f"{st}@{lo}") or {}).get("kind") != "strategy":
            raise HTTPException(400, _why_not(book, st))
        out.update(lo=lo, hi=hi, s=st)
    return out


def rules(book: Book, q: dict, now: int) -> dict:
    c = check_rules(book, q)
    kind = c["kind"]
    out = {"label": LABEL, "kind": kind, "kind_ko": RULE_KO[kind], "approx_ko": APPROX_KO, "now": int(now),
           "start": book.start, "run_days": K.r((now - int(book.start or now)) / DAY_MS, 3),
           "signals_ko": ("B 쪽은 신호 기록(계산된 신호를 모두 남긴 표: 계좌가 다른 거래 중이라 못 들어간 신호도 남음)을 써서 "
                          "B가 바빠서 놓친 진입도 같은 방향으로 셉니다."),
           "signal_rows": book.sig_rows, "small_n": RULE_SMALL, "flip_money_ko": FLIP_MONEY_KO}
    if kind in ("both", "filter"):
        a, b = c["a"], c["b"]
        bar = TF_MS.get(a.tf, HOUR_MS)
        if kind == "both":
            def passes(sym, side, t, _tf=None):
                return _agrees(book, b.strategy, b.tfs, sym, side, t - bar, t)
            out["window_ko"] = (f"B의 같은 코인·같은 방향 신호가 A가 들어가기 전 A 봉 하나 길이({tf_ko(a.tf)}) 안에 "
                                "(같은 시각 포함) 있었을 때만")
        else:
            def passes(sym, side, t, _tf=None):
                return _latest(book, b.strategy, b.tfs, sym, t) == side
            out["window_ko"] = "A가 들어갈 때 그 코인에 대한 B의 가장 최근 신호가 같은 방향일 때만 (B가 그 코인에 신호를 낸 적이 없으면 거름)"
        out.update(a=a.as_dict(), b=b.as_dict())
        _rule_rows(book, out, [a], passes, a.tfs, now)
        out["busy_passed"] = _busy_signals(book, a, passes, now)
        return out
    if kind == "vote":
        members, kk = c["members"], c["k"]
        # a member that is a whole strategy votes when any of its timeframes agrees, each signal alive one of its
        # own bars (a 15m signal 15 minutes, a 4h signal 4 hours)
        voters = [(m.strategy, [(tf, TF_MS.get(tf, HOUR_MS)) for tf in m.tfs]) for m in members]

        def votes(sym, side, t, skip=None):
            return sum(1 for i, (s, tfb) in enumerate(voters)
                       if i != skip and any(_agrees(book, s, [tf], sym, side, t - bar, t) for tf, bar in tfb))
        out.update(members=[m.as_dict() for m in members], k=kk,
                   window_ko=("구성원마다 자기 봉 하나 길이 동안 그 방향 신호가 살아 있다고 보고, 들어가는 순간 같은 코인·같은 방향인 "
                              f"구성원이 {kk}개 이상일 때만 (같은 코인·방향이 이미 열려 있으면 겹친 진입은 하나로 셈)"))
        every, kept, dup = [], [], 0
        for i, m in enumerate(members):
            for x in book.trades(m.aids):
                if x["exit"] > now:
                    continue
                every.append(x)
                if votes(x["sym"], x["side"], x["bar"], skip=i) + 1 >= kk:
                    kept.append(x)
        kept.sort(key=lambda x: (x["entry"], x["id"]))
        open_until: dict = {}
        rule = []
        for x in kept:
            key = (x["sym"], x["side"])
            if open_until.get(key, -1) > x["entry"]:
                dup += 1
                continue
            open_until[key] = x["exit"]
            rule.append(x)
        flips = [x for tf in sorted({tf for m in members for tf in m.tfs}) for x in book.trades(book.flips(tf)) if x["exit"] <= now]
        fk = [x for x in flips if votes(x["sym"], x["side"], x["bar"]) >= max(1, kk - 1)]
        ids = {x["id"] for x in rule}
        out["rows"] = [_rows_stats(f"합친 규칙 ({len(members)}개 중 {kk}개 이상)", "rule", rule),
                       _rows_stats("구성원 거래 전부 (거르기 전)", "alone", every),
                       _rows_stats("걸러진 거래", "dropped", [x for x in every if x["id"] not in ids]),
                       _rows_stats(f"동전 봇 + 같은 투표 (구성원 {max(1, kk - 1)}개 이상 같은 방향)", "flip_rule", fk, money=False),
                       _rows_stats("동전 봇 전부", "flip_all", flips, money=False)]
        out["duplicates"] = dup
        return out
    # kind == "tf": the same strategy's higher timeframe as the filter of its lower one
    lo, hi, s = c["lo"], c["hi"], c["s"]
    strategies = book.strategies() if s == "all" else [s]
    out.update(lo=lo, hi=hi, s=s, window_ko=(f"{tf_ko(lo)}봉 계좌가 들어갈 때 같은 매매법 {tf_ko(hi)}봉의 그 코인 가장 최근 신호가 "
                                            "같은 방향일 때만"))
    names = names_ko()
    alone, kept, per = [], [], []
    for st in strategies:
        aid = f"{st}@{lo}"
        mine = [x for x in book.trades([aid]) if x["exit"] <= now]
        ok = [x for x in mine if _latest(book, st, [hi], x["sym"], x["bar"]) == x["side"]]
        alone.extend(mine)
        kept.extend(ok)
        if s == "all":
            per.append({"strategy": st, "name_ko": names.get(st, st), "rule": _rows_stats("합의", "rule", ok),
                        "alone": _rows_stats("혼자", "alone", mine)})
    ids = {x["id"] for x in kept}
    flips = [x for x in book.trades(book.flips(lo)) if x["exit"] <= now]
    rows = [_rows_stats(f"합친 규칙 ({tf_ko(lo)} + {tf_ko(hi)} 합의)", "rule", kept),
            _rows_stats(f"{tf_ko(lo)}봉 혼자", "alone", alone),
            _rows_stats("걸러진 거래", "dropped", [x for x in alone if x["id"] not in ids])]
    if s != "all":
        rows.append(_rows_stats(f"동전 봇 + 같은 거르개 ({tf_ko(hi)} 신호)", "flip_rule",
                                [x for x in flips if _latest(book, s, [hi], x["sym"], x["bar"]) == x["side"]], money=False))
    rows.append(_rows_stats(f"{tf_ko(lo)}봉 동전 봇 전부", "flip_all", flips, money=False))
    out["rows"] = rows
    if s == "all":
        out["per_strategy"] = per
    else:
        a = Unit(f"{s}@{lo}", "account", s, lo, [f"{s}@{lo}"], "core", f"{names.get(s, s)} · {tf_ko(lo)}")
        out["busy_passed"] = _busy_signals(book, a, lambda sym, side, t, _tf=None: _latest(book, s, [hi], sym, t) == side, now)
    return out


def _rule_rows(book: Book, out: dict, units: list, passes, tfs, now: int) -> None:
    every = [x for u in units for x in book.trades(u.aids) if x["exit"] <= now]
    kept = [x for x in every if passes(x["sym"], x["side"], x["bar"])]
    ids = {x["id"] for x in kept}
    flips = [x for tf in tfs for x in book.trades(book.flips(tf)) if x["exit"] <= now]
    out["rows"] = [_rows_stats("합친 규칙", "rule", kept), _rows_stats("A 혼자", "alone", every),
                   _rows_stats("걸러진 거래", "dropped", [x for x in every if x["id"] not in ids]),
                   _rows_stats("동전 봇 + 같은 거르개", "flip_rule", [x for x in flips if passes(x["sym"], x["side"], x["bar"])],
                               money=False),
                   _rows_stats("동전 봇 전부", "flip_all", flips, money=False)]


# ---------------------------------------------------------------- the picker
def units_view(book: Book, board: dict, now: int) -> dict:
    names = names_ko()
    init = float(board.get("initial") or book.initial or INITIAL)
    rows = {a.get("account_id"): a for a in board.get("accounts") or []}

    def acct(aid):
        a = rows.get(aid) or {}
        w = a.get("wallet")
        n = int(a.get("trades") or 0)
        return {"id": aid, "tf": aid.split("@", 1)[1], "trades": n, "wins": int(a.get("wins") or 0),
                "ret": K.r(float(w) / init - 1) if w is not None and init > 0 else None, "bust": bool(a.get("bust"))}
    strategies = []
    for s in book.strategies():
        accts = [acct(a) for a in book.accounts_of(s)]
        wsum = sum((a["ret"] or 0.0) + 1 for a in accts if a["ret"] is not None)
        n_w = sum(1 for a in accts if a["ret"] is not None)
        strategies.append({"id": s, "name_ko": names.get(s, s), "accounts": accts, "trades": sum(a["trades"] for a in accts),
                           "ret": K.r(wsum / n_w - 1) if n_w else None})
    reel = book.accounts_of(REEL_NAME, "reel")
    flips = {}
    for v in book.acc.values():
        if v["kind"] == "random":
            flips[v["tf"]] = flips.get(v["tf"], 0) + 1
    start = int(book.start or now)
    return {"label": LABEL, "strategies": strategies,
            "reel": {"id": REEL_NAME, "name_ko": names.get(REEL_NAME, REEL_NAME), "accounts": [acct(a) for a in reel],
                     "note": REEL_NOTE} if reel else None,
            "flips": flips, "tfs": list(CORE_TFS), "initial": init, "start": start, "now": int(now),
            "run_days": K.r((now - start) / DAY_MS, 3), "kmin": KMIN, "kmax": KMAX, "ds_note": DS_NOTE,
            "methods": [{"id": k, "ko": v} for k, v in WEIGHT_KO.items()],
            "five_year_view": os.path.exists(FIVE_Y_JS),
            "basis_ko": "수익률 = 닫힌 거래 기준 잔고 (매매법 = 봉 계좌 4개를 더한 잔고)"}


# ---------------------------------------------------------------- routes
def custom_of(p: Optional[str], units: list) -> Optional[list]:
    """'50,30,20' -> [50.0, 30.0, 20.0] for 직접 % (400 unless one number per unit, none negative, sum above 0)."""
    if p is None:
        return None
    try:
        cs = [float(x) for x in str(p).split(",") if x.strip() != ""]
    except ValueError:
        raise HTTPException(400, "직접 %는 숫자를 쉼표로 이어 주세요 (예: 50,30,20)")
    if len(cs) != len(units) or any(x < 0 or not math.isfinite(x) for x in cs) or sum(cs) <= 0:
        raise HTTPException(400, "직접 %는 구성원 수만큼, 0 이상, 합이 0보다 커야 합니다")
    return cs


class Combo:
    def __init__(self, data, heavy=None):
        from ..analysis import Heavy
        self.data = data
        self.book = Book(data)
        self.heavy = heavy or Heavy(wait_s=WAIT_S)

    def _fresh(self, now: Optional[int] = None) -> int:
        self.book.refresh()
        return int(time.time() * 1000) if now is None else int(now)

    def combo(self, u: str, w: str = "eq", p: Optional[str] = None, now: Optional[int] = None) -> dict:
        n = self._fresh(now)
        units = parse_units(self.book, u)
        method = w if w in WEIGHT_KO else "eq"
        custom = custom_of(p, units) if method == "custom" else None
        try:
            snap = overlap_snapshot(self.book, now)
        except Exception as exc:  # noqa: BLE001  (the same-bet card says so; the rest stands)
            snap = {"ready": False, "rules": {}, "note": f"계좌 겹침을 계산하지 못함: {type(exc).__name__}"}
        return combination(self.book, units, method, custom, n, snap)

    def corr(self, level: str = "strategy", tf: Optional[str] = None, basis: str = "day", now: Optional[int] = None) -> dict:
        n = self._fresh(now)
        try:
            snap = overlap_snapshot(self.book, now)
        except Exception:  # noqa: BLE001
            snap = None
        return corr_map(self.book, level, tf, basis, n, snap)

    def rules(self, q: dict, now: Optional[int] = None) -> dict:
        n = self._fresh(now)
        self.book.refresh_signals()
        return rules(self.book, q, n)

    def units(self, now: Optional[int] = None) -> dict:
        """The picker: the accounts table and the dashboard's cached board only (cheap, on the request thread)."""
        self.book.refresh_accounts()
        if self.book.start is None:
            from ...agents.triggers import run_start
            with self.book._conn() as c:
                self.book.start = run_start(c)
        return units_view(self.book, self.data.board(), int(time.time() * 1000) if now is None else int(now))


def register(app, ctx) -> Combo:
    combo = Combo(ctx.data)

    def guard(fn):
        try:
            return fn()
        except sqlite3.Error as exc:
            raise HTTPException(503, f"paper3.db를 읽지 못함: {type(exc).__name__}")

    def checked(key: str, ttl: float, fn, check):
        """Check the request on the request thread (a 400 is a 400), compute in the background (Heavy)."""
        guard(check)
        out = combo.heavy.get(key, ttl, lambda: guard(fn))
        if isinstance(out, dict) and out.get("error") and "detail" not in out:
            out = {**out, "label": LABEL}
        return out

    @app.get("/api/v4/combo/units")
    def get_combo_units():
        """조합 성과 › 고르기: the 36 strategies, their accounts and the reel with trades and returns (cheap)."""
        return guard(combo.units)

    @app.get("/api/v4/combo")
    def get_combo(u: str = "", w: str = "eq", p: Optional[str] = None):
        """One combination of 2-8 units (background, cached TTL_S)."""
        keys = ",".join(x.strip() for x in u.split(",") if x.strip())[:800]
        key = f"combo:{keys}:{w}:{p or ''}"

        def check():
            combo.book.refresh_accounts()
            custom_of(p if w == "custom" else None, parse_units(combo.book, keys))
        return checked(key, TTL_S, lambda: combo.combo(keys, w, p), check)

    @app.get("/api/v4/combo/corr")
    def get_combo_corr(level: str = "strategy", tf: Optional[str] = None, basis: str = "day"):
        """전체 상관 지도 (background, cached CORR_TTL_S)."""
        lv = "account" if level == "account" else "strategy"
        t = tf if tf in CORE_TFS else ("1h" if lv == "account" else None)
        b = "hour" if basis == "hour" else "day"
        return combo.heavy.get(f"combo-corr:{lv}:{t}:{b}", CORR_TTL_S, lambda: guard(lambda: combo.corr(lv, t, b)))

    @app.get("/api/v4/combo/rules")
    def get_combo_rules(kind: str = "both", a: Optional[str] = None, b: Optional[str] = None, m: Optional[str] = None,
                        k: Optional[int] = None, s: Optional[str] = None, lo: Optional[str] = None, hi: Optional[str] = None):
        """합친 규칙 실험 (background, cached TTL_S)."""
        q = {"kind": kind, "a": a, "b": b, "m": m, "k": k, "s": s, "lo": lo, "hi": hi}
        q = {x: (str(v)[:400] if v is not None else None) for x, v in q.items()}
        key = "combo-rules:" + "|".join(f"{x}={q[x] or ''}" for x in sorted(q))

        def check():
            combo.book.refresh_accounts()
            check_rules(combo.book, q)
        return checked(key, TTL_S, lambda: combo.rules(q), check)

    return combo

"""매매법 × 봉 지도 + 매매법 프로필 카드 (dash/more, read-only views over paper3.db; nothing is ever written).

    GET /api/v4/grid?days=30|7                 every original account's cell in one small answer: the window return
                                               (realized wallet now / realized wallet at the window start), closed
                                               trades and wins in the window, bust, open position, and for the 36 and
                                               the reel the difference from the median coin flip of the SAME timeframe
                                               (the reel: its three 5m flips). DeepSeek gets no per-account
                                               comparison (CONTRACT honesty rule 3): its cells carry vs = null.
    GET /api/v4/grid/sparks?days=30|7          per strategy (the 36, DeepSeek 44, the reel) the summed realized balance
                                               of its own timeframe accounts at 41 points over the window (the
                                               strategies list's small curves).
    GET /api/v4/grid/y5                        the 5-year past test per strategy x timeframe (fill-strat: the map's
                                               '5년 시험' colour, so it is coloured on day 1): the 36's per-trade ROE on
                                               margin from their 5-year cards (unit "roe"), DeepSeek's and the reel's
                                               net price % per trade with no leverage (unit "1x"), win rate, trades
                                               per day. The same rows the strategy page's 5-year card and 5년 시험 vs
                                               지금 show (more/vs5y.five_year); research files only, cached 1 hour.
    GET /api/v4/grid/profile/<key>?days=30|7   the profile card. key = an account id ("S5_DONCHIAN_MFI@15m"): its
                                               balance path (as a return from the window start, 91 points), the same
                                               timeframe coin flips' median path (not for DeepSeek or a coin flip), max
                                               drawdown, win rate, trades, the coin-flip difference. key = a strategy
                                               name: the same for each of its timeframe accounts plus the combined
                                               balance path.

Numbers: the window is the last 7 or 30 days, cut at the run's start (the first 30 days of a run are "since the
start"). The return is realized (closed trades: fees, funding and slippage are already in each trade's equity_after),
the same wallet the board shows. Max drawdown is the engine's own (mark price, open positions included) when the
window covers the whole run, else from the 5-minute equity samples inside the window. Groups and families come from
paperbot/groups.py (the single source).

Cost: the closed trades of the last 32 days are kept per account in compact arrays and read incrementally by trade id
(the first call reads them once, every later call only the new rows); the board comes from Data.board() (cached by the
dashboard); every answer is reused for 60 s. All reads go through the read-only connection (Data.conn: mode=ro).
"""
from __future__ import annotations

import bisect
import contextlib
import math
import sqlite3
import statistics
import threading
import time
from array import array
from typing import Optional

from fastapi import HTTPException

from ... import groups as G
from ...accounts import ORIGINAL_KINDS
from ...config import V4_GROUPS

DAY_MS = 86_400_000
DAYS = (7, 30)              # the profile card's 7일 / 30일 (the grid and the list use the same windows)
TTL_S = 60.0                # every answer is reused for this long
MIN_COLOR = 10              # under this many closed trades in the window a cell is grey: too few to colour
SMALL = 30                  # checkpoint.MIN_TRADES: under it '표본 적음' (a test ties the two)
SPARK_POINTS = 40           # the strategies list's curves (41 points)
PROFILE_POINTS = 90         # the profile card's curve (91 points)
STRAT_KINDS = ("strategy", "ds200", "reel")      # a strategy's own accounts (copies follow another rule)
HORIZON_MS = 32 * DAY_MS    # closed trades kept in memory (the 30-day window plus a margin)
CACHE_MAX = 256
TF_ORDER = ("5m", "15m", "30m", "1h", "4h")
Y5_TTL_S = 3600.0           # the 5-year rows come from research files that change only with a deploy


def window(days, now: int, start: Optional[int]) -> tuple[int, int, bool]:
    """(days, from_ms, covers_run): the last ``days`` days (7 or 30, else 30) cut at the run's start."""
    try:
        d = int(days)
    except (TypeError, ValueError):
        d = 30
    d = d if d in DAYS else 30
    lo = int(now) - d * DAY_MS
    if start is None:
        return d, lo, True
    return d, max(lo, int(start)), lo <= int(start)


def _median(xs) -> Optional[float]:
    v = [x for x in xs if x is not None and math.isfinite(x)]
    return statistics.median(v) if v else None


def _r(x, n: int = 6):
    return None if x is None or not math.isfinite(x) else round(float(x), n)


def _ret(w: Optional[float], w0: Optional[float]) -> Optional[float]:
    return None if w is None or not w0 or w0 <= 0 else w / w0 - 1


def _points(frm: int, now: int, n: int) -> list[int]:
    """n + 1 times from the window start to now."""
    span = max(1, now - frm)
    return [frm + span * i // n for i in range(n + 1)]


class Trades:
    """The closed trades of the last HORIZON_MS per account (exit time, equity after, won or not) in exit-time order,
    read incrementally by trade id: the first refresh finds the first id inside the horizon with a binary search on
    the primary key (ids grow with time), every later refresh reads only the rows after the last id it saw."""

    def __init__(self):
        self.lock = threading.Lock()
        self.last_id = 0
        self.by: dict = {}              # account -> (exit times array q, equity after array d, won array b)

    @staticmethod
    def _first_id(c, since: int) -> Optional[int]:
        lo, hi = c.execute("SELECT MIN(id), MAX(id) FROM trades").fetchone()
        if hi is None:
            return None
        while lo < hi:
            mid = (lo + hi) // 2
            r = c.execute("SELECT exit_time FROM trades WHERE id >= ? ORDER BY id LIMIT 1", (mid,)).fetchone()
            if r is None or r[0] >= since:
                hi = mid
            else:
                lo = mid + 1
        return lo

    def refresh(self, c, now: int) -> None:
        with self.lock:
            mx = c.execute("SELECT MAX(id) FROM trades").fetchone()[0] or 0
            if mx < self.last_id:                       # a new database (a new run): start over
                self.last_id, self.by = 0, {}
            if not self.last_id:
                # a day of margin: exit times follow ids only roughly
                first = self._first_id(c, now - HORIZON_MS - DAY_MS)
                if first is None:
                    return
                self.last_id = first - 1
            for i, aid, t, e, pnl in c.execute("SELECT id, account_id, exit_time, equity_after, pnl FROM trades "
                                               "WHERE id > ? ORDER BY id", (self.last_id,)):
                self.last_id = i
                rec = self.by.get(aid)
                if rec is None:
                    rec = self.by[aid] = (array("q"), array("d"), array("b"))
                ts, eq, won = rec
                k = len(ts) if not ts or t >= ts[-1] else bisect.bisect_right(ts, t)   # out of order: rare
                ts.insert(k, int(t))
                eq.insert(k, float(e))
                won.insert(k, 1 if pnl > 0 else 0)
            cut = now - HORIZON_MS
            for rec in self.by.values():                # drop what fell out of the horizon
                k = bisect.bisect_left(rec[0], cut)
                if k > 0:
                    for arr in rec:
                        del arr[:k]

    def since(self, aid: str, frm: int) -> tuple[int, int, Optional[float]]:
        """(trades, wins, balance after the last kept trade before frm or None) for exit_time >= frm."""
        rec = self.by.get(aid)
        if not rec:
            return 0, 0, None
        ts, eq, won = rec
        k = bisect.bisect_left(ts, frm)
        return len(ts) - k, sum(won[k:]), (eq[k - 1] if k else None)

    def path(self, aid: str, frm: int, w0: float, points: list[int], w_now: float) -> list[float]:
        """The realized balance at each point (carried forward) from w0 at frm; the last point is the wallet now."""
        rec = self.by.get(aid)
        if not rec:
            return [w0] * (len(points) - 1) + [w_now]
        ts, eq, _won = rec
        out, cur, j = [], w0, bisect.bisect_left(ts, frm)
        for t in points[:-1]:
            while j < len(ts) and ts[j] <= t:
                cur = eq[j]
                j += 1
            out.append(cur)
        out.append(w_now)
        return out


class Grid:
    """The three answers, cached (TTL_S). ``data`` is dash.app.Data (board() and the read-only conn())."""

    def __init__(self, data):
        self.data = data
        self.trades = Trades()
        self._cache: dict = {}
        self._lock = threading.RLock()      # re-entrant: a profile / sparks answer asks for the cached grid inside it

    # ---------------------------------------------------------------- cache
    def _hit(self, key, fn, now_ms: Optional[int]):
        if now_ms is not None:                       # tests pass their own clock: no cache
            return fn(now_ms)
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < TTL_S:
            return hit[1]
        with self._lock:
            hit = self._cache.get(key)
            if hit and time.monotonic() - hit[0] < TTL_S:
                return hit[1]
            val = fn(int(time.time() * 1000))
            if len(self._cache) > CACHE_MAX:
                self._cache.clear()
            self._cache[key] = (time.monotonic(), val)
            return val

    def _conn(self):
        return contextlib.closing(self.data.conn())

    # ---------------------------------------------------------------- the board's original accounts
    def _originals(self) -> tuple[list[dict], float, Optional[int], dict]:
        b = self.data.board()
        init = float(b.get("initial") or 5000.0)
        rows = [a for a in b.get("accounts") or [] if a.get("kind") in ORIGINAL_KINDS]
        starts = [a.get("created_ts") for a in rows if a.get("created_ts") is not None]
        return rows, init, (min(starts) if starts else None), b.get("strategy_ko") or {}

    @staticmethod
    def _w0(c, a: dict, frm: int, covers: bool, init: float, before: Optional[float]) -> float:
        """The realized wallet at the window start: the start wallet when the window covers the run or the account
        started inside it, else the balance after its last trade before the window (from memory when that trade is
        in the horizon, else one index seek; the start wallet when it never traded)."""
        created = a.get("created_ts")
        if covers or (created is not None and created >= frm):
            return init
        if before is not None:
            return before
        r = c.execute("SELECT equity_after FROM trades WHERE account_id = ? AND exit_time < ? "
                      "ORDER BY exit_time DESC LIMIT 1", (a["account_id"], frm)).fetchone()
        return float(r[0]) if r else init

    @staticmethod
    def _mdd(c, a: dict, frm: int, covers: bool) -> Optional[float]:
        """Max drawdown in the window: the engine's own when the window covers the run, else from the 5-minute equity
        samples (mark price, open positions included) with the peak starting at the window start."""
        if covers:
            m = a.get("max_drawdown")
            return float(m) if m is not None and math.isfinite(m) else None
        peak, mdd, seen = None, 0.0, False
        for (eq,) in c.execute("SELECT equity FROM equity WHERE account_id = ? AND ts >= ? ORDER BY ts",
                               (a["account_id"], frm)):
            seen = True
            if peak is None or eq > peak:
                peak = eq
            elif peak > 0:
                mdd = max(mdd, 1 - eq / peak)
        return mdd if seen else None

    # ---------------------------------------------------------------- /api/v4/grid
    def grid(self, days=30, now_ms: Optional[int] = None) -> dict:
        d = window(days, 0, None)[0]
        return self._hit(("grid", d), lambda now: self._grid(d, now), now_ms)

    def _grid(self, days: int, now: int) -> dict:
        rows, init, start, _names = self._originals()
        d, frm, covers = window(days, now, start)
        cells = []
        with self._conn() as c:
            self.trades.refresh(c, now)
            for a in rows:
                w = a.get("wallet")
                w = init if w is None else float(w)
                n, wins, before = self.trades.since(a["account_id"], frm)
                if covers:                                   # the whole run: the board's own counts
                    n, wins = int(a.get("trades") or 0), int(a.get("wins") or 0)
                w0 = self._w0(c, a, frm, covers, init, before)
                g = G.group_of(a)
                cells.append({"id": a["account_id"], "s": a.get("strategy"), "tf": a.get("timeframe"), "g": g,
                              "fam": G.family_of(a),
                              "role": G.role_of(a.get("strategy")) if g in ("ds200", "reel") else None,
                              "w0": _r(w0, 2), "w": _r(w, 2), "ret": _r(_ret(w, w0)), "n": n, "win": wins,
                              "bust": bool(a.get("bust")), "open": bool(a.get("position")),
                              "mdd": _r(a.get("max_drawdown"), 4) if covers else None})
        flips: dict = {}
        for x in cells:
            if x["g"] == "flip":
                f = flips.setdefault(x["tf"], {"ids": [], "rets": []})
                f["ids"].append(x["id"])
                f["rets"].append(x["ret"])
        flips = {tf: {"median": _r(_median(f["rets"])), "n": len(f["ids"]), "ids": f["ids"]} for tf, f in flips.items()}
        for x in cells:
            # the coin-flip difference: the 36 and the reel only (DeepSeek: reference at group level only; a coin flip
            # is the yardstick itself)
            m = (flips.get(x["tf"]) or {}).get("median") if x["g"] in ("core", "reel") else None
            x["vs"] = _r(x["ret"] - m) if m is not None and x["ret"] is not None else None
        return {"days": d, "from": frm, "now": now, "start": start, "covers_run": covers, "initial": init,
                "min_color": MIN_COLOR, "small_n": SMALL,
                "tfs": {g: list(V4_GROUPS[g]["tfs"]) for g in ("core", "ds200", "reel", "flip") if g in V4_GROUPS},
                "judged": {g: list(V4_GROUPS[g]["judged"]) for g in ("core", "ds200", "reel") if g in V4_GROUPS},
                "flips": flips, "families": dict(G.DS_FAMILY_KO),
                "roles": [{"key": k, "ko": ko, "families": list(fams), "defs": G.role_members(k)}
                          for k, ko, fams, _x in G.V4_ROLES],
                "cells": cells,
                "basis_ko": "닫힌 거래 기준 잔고 (수수료·펀딩·슬리피지 포함) · 동전 봇은 같은 봉끼리 · 참고"}

    # ---------------------------------------------------------------- /api/v4/grid/sparks
    def sparks(self, days=30, now_ms: Optional[int] = None) -> dict:
        d = window(days, 0, None)[0]
        if now_ms is not None:
            return self._sparks(self._grid(d, now_ms))
        return self._hit(("sparks", d), lambda _now: self._sparks(self.grid(d)), None)

    def _sparks(self, g: dict) -> dict:
        frm, now = g["from"], g["now"]
        pts = _points(frm, now, SPARK_POINTS)
        kinds = {a["account_id"]: a.get("kind") for a in self._originals()[0]}
        out: dict = {}
        for x in g["cells"]:
            if kinds.get(x["id"]) not in STRAT_KINDS:
                continue
            p = self.trades.path(x["id"], frm, x["w0"] or 0.0, pts, x["w"] or 0.0)
            e = out.setdefault(x["s"], {"n": 0, "w0": 0.0, "v": [0.0] * len(pts)})
            e["n"] += 1
            e["w0"] += x["w0"] or 0.0
            e["v"] = [u + v for u, v in zip(e["v"], p)]
        for e in out.values():
            e["w"] = round(e["v"][-1], 2)
            e["ret"] = _r(_ret(e["v"][-1], e["w0"]))
            e["w0"] = round(e["w0"], 2)
            e["v"] = [round(v, 1) for v in e["v"]]
        return {"days": g["days"], "from": frm, "now": now, "start": g["start"], "covers_run": g["covers_run"],
                "initial": g["initial"], "t": pts, "strategies": out, "basis_ko": "봉 계좌들을 더한 닫힌 거래 기준 잔고"}

    # ---------------------------------------------------------------- /api/v4/grid/y5
    def y5(self) -> dict:
        """{strategies: {name: {unit, group, tfs: {tf: {roe, win, per_day}}}}} for every strategy on the grid (one call
        of vs5y.five_year per strategy; an unreadable research file gives that strategy no row, never a 500)."""
        hit = self._cache.get(("y5",))
        if hit and time.monotonic() - hit[0] < Y5_TTL_S:
            return hit[1]
        from .vs5y import five_year
        names = sorted({(x["s"], x["g"]) for x in self.grid(30)["cells"] if x["g"] in ("core", "ds200", "reel")})
        out: dict = {}
        for name, grp in names:
            try:
                unit, rows, _meta = five_year(name)
            except Exception:  # noqa: BLE001  (a changed research file: no 5-year row for it)
                unit, rows = None, {}
            if not unit or not rows:
                continue
            out[name] = {"unit": unit, "group": grp,
                         "tfs": {tf: {"roe": _r(r.get("roe")), "win": _r(r.get("win"), 4), "per_day": _r(r.get("per_day"), 3)}
                                 for tf, r in rows.items()}}
        val = {"strategies": out, "computed_at": int(time.time() * 1000),
               "basis_ko": "5년 과거 시험 · 거래 한 건의 평균 결과 (기존 36: 증거금 대비 ROE, 딥시크·릴스: 레버리지 없이 가격 %) · 참고"}
        with self._lock:
            self._cache[("y5",)] = (time.monotonic(), val)
        return val

    # ---------------------------------------------------------------- /api/v4/grid/profile/<key>
    def profile(self, key: str, days=30, now_ms: Optional[int] = None) -> dict:
        """The card of one account or one strategy, from the grid's own cells (the same numbers and the same clock as
        the grid answer it was computed with)."""
        d = window(days, 0, None)[0]
        if now_ms is not None:
            return self._profile(str(key), self._grid(d, now_ms))
        return self._hit(("profile", str(key), d), lambda _now: self._profile(str(key), self.grid(d)), None)

    def _profile(self, key: str, g: dict) -> dict:
        cells = {x["id"]: x for x in g["cells"]}
        rows, _init, _start, names = self._originals()
        by_id = {a["account_id"]: a for a in rows}
        frm, now = g["from"], g["now"]
        pts = _points(frm, now, PROFILE_POINTS)
        base = {"days": g["days"], "from": frm, "now": now, "start": g["start"], "covers_run": g["covers_run"],
                "initial": g["initial"], "t": pts, "min_color": MIN_COLOR, "small_n": SMALL}
        if "@" in key:
            x = cells.get(key)
            if x is None or key not in by_id:
                raise KeyError(key)
            with self._conn() as c:
                return {**base, "kind": "account", **self._one(c, by_id[key], x, g, pts, names, full=True)}
        mine = [x for x in g["cells"] if x["s"] == key and (by_id.get(x["id"]) or {}).get("kind") in STRAT_KINDS]
        if not mine:
            raise KeyError(key)
        mine.sort(key=lambda x: TF_ORDER.index(x["tf"]) if x["tf"] in TF_ORDER else 9)
        with self._conn() as c:
            accts = [self._one(c, by_id[x["id"]], x, g, pts, names, full=False) for x in mine]
        paths = [self.trades.path(x["id"], frm, x["w0"] or 0.0, pts, x["w"] or 0.0) for x in mine]
        w0 = sum(x["w0"] or 0.0 for x in mine)
        comb = [sum(p[i] for p in paths) for i in range(len(pts))]
        n = sum(x["n"] for x in mine)
        wins = sum(x["win"] for x in mine)
        mdds = [a["mdd"] for a in accts if a["mdd"] is not None]
        fam, role = mine[0]["fam"], mine[0]["role"]
        return {**base, "kind": "strategy", "strategy": key, "group": mine[0]["g"], "family": fam,
                "family_ko": G.DS_FAMILY_KO.get(fam) if fam else None, "role": role,
                "role_ko": G.ROLE_KO.get(role) if role else None,
                "name_ko": names.get(key) or G.label_ko(key, mine[0]["tf"]),
                "accounts": accts,
                "combined": {"w0": _r(w0, 2), "w": _r(comb[-1], 2), "ret": _r(_ret(comb[-1], w0)), "trades": n,
                             "wins": wins, "win_rate": _r(wins / n, 4) if n else None,
                             "mdd_max": _r(max(mdds), 4) if mdds else None,
                             "above": sum(1 for a in accts if a["vs"] is not None and a["vs"] > 0),
                             "below": sum(1 for a in accts if a["vs"] is not None and a["vs"] < 0),
                             "vs_n": sum(1 for a in accts if a["vs"] is not None)},
                "spark": {"v": [_r(_ret(v, w0)) for v in comb]}}

    def _one(self, c, a: dict, x: dict, g: dict, pts: list, names: dict, full: bool) -> dict:
        """One account's card numbers (the grid's own cell numbers + drawdown, curve and the comparison)."""
        grp, frm = x["g"], g["from"]
        out = {"id": x["id"], "strategy": x["s"], "tf": x["tf"], "group": grp, "family": x["fam"],
               "w0": x["w0"], "w": x["w"], "ret": x["ret"], "trades": x["n"], "wins": x["win"],
               "win_rate": _r(x["win"] / x["n"], 4) if x["n"] else None, "bust": x["bust"], "open": x["open"],
               "mdd": _r(self._mdd(c, a, frm, g["covers_run"]), 4), "vs": x["vs"], "small_sample": x["n"] < SMALL,
               "grey": x["n"] < MIN_COLOR}
        if not full:
            return out
        flip = g["flips"].get(x["tf"]) or {}
        mine = self.trades.path(x["id"], frm, x["w0"] or 0.0, pts, x["w"] or 0.0)
        spark = {"v": [_r(_ret(v, x["w0"])) for v in mine], "flip": None}
        if grp in ("core", "reel") and flip.get("ids"):
            cells = {y["id"]: y for y in g["cells"]}
            fp = [[_ret(v, cells[f]["w0"]) for v in self.trades.path(f, frm, cells[f]["w0"] or 0.0, pts, cells[f]["w"] or 0.0)]
                  for f in flip["ids"]]
            spark["flip"] = [_r(_median([p[i] for p in fp])) for i in range(len(pts))]
        out.update(spark=spark, name_ko=names.get(x["s"]) or G.label_ko(x["s"], x["tf"]),
                   family_ko=G.DS_FAMILY_KO.get(x["fam"]) if x["fam"] else None,
                   role=x["role"], role_ko=G.ROLE_KO.get(x["role"]) if x["role"] else None)
        if grp in ("core", "reel"):
            out["vs_basis"] = {"tf": x["tf"], "n": flip.get("n", 0), "median_ret": flip.get("median"),
                               "ids": flip.get("ids", [])}
        elif grp == "ds200":
            # DeepSeek: no per-account comparison; the group's own median on this timeframe and the coin flips' median
            # on it, both group level ('참고')
            same = [y["ret"] for y in g["cells"] if y["g"] == "ds200" and y["tf"] == x["tf"]]
            out["ds_group"] = {"tf": x["tf"], "n": len(same), "median_ret": _r(_median(same)),
                               "flip_median_ret": flip.get("median"), "flip_n": flip.get("n", 0)}
        elif grp == "flip":
            out["baseline"] = True
        return out


def register(app, ctx) -> Grid:
    grid = Grid(ctx.data)

    def guard(fn):
        try:
            return fn()
        except sqlite3.Error as exc:
            raise HTTPException(503, f"paper3.db를 읽지 못함: {type(exc).__name__}")

    @app.get("/api/v4/grid")
    def get_grid(days: int = 30):
        """매매법 × 봉 지도: every original account's cell for the last 7 / 30 days (60 s cache)."""
        return guard(lambda: grid.grid(days))

    @app.get("/api/v4/grid/sparks")
    def get_grid_sparks(days: int = 30):
        """The strategies list's small curves: each strategy's summed realized balance (60 s cache)."""
        return guard(lambda: grid.sparks(days))

    @app.get("/api/v4/grid/y5")
    def get_grid_y5():
        """The 5-year past test per strategy x timeframe (research files only, 1 hour cache)."""
        return guard(grid.y5)

    @app.get("/api/v4/grid/profile/{key}")
    def get_grid_profile(key: str, days: int = 30):
        """The profile card of one account (id with '@') or one strategy (its timeframe accounts) (60 s cache)."""
        try:
            return guard(lambda: grid.profile(key, days))
        except KeyError:
            raise HTTPException(404, "그런 계좌나 매매법이 없습니다")

    return grid

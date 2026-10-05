"""흐름 (홈 › 흐름): the group race and the profit calendar, read-only over paper3.db.

    GET /api/v4/flow/race?step=auto|300000|900000|3600000|14400000|86400000
        Each group's median balance over the run (core = the 36, ds200 = DeepSeek 44, reel = the 5m reel, flip = all
        15 coin flips; flip5m = the reel's three 5m flips, its own comparison) at the end of every step, with the
        middle 50 % of the coin flips (band lo / hi = their 25th / 75th percentile) as the baseline. step "auto": 5
        minutes while the run is under 2 days old, 15 minutes under 7 days (the bot writes equity every 5 minutes, so
        day 1 is a real moving race, never a flat line of 1-2 hourly points), then one hour while it is at most 40
        days old, then 4 hours, then one day past 160 days. The first point is the
        run start (every account at the starting balance), the last one is now.
    GET /api/v4/flow/calendar?season=k
        One entry per Korea-time (KST) day of a season (season k ends on the KST day of the (k+1)-th verdict, so the
        first one runs from the start day through the verdict day; default: the current season): per group the median balance at the day's end, its change against the previous day's end,
        how many accounts ended the day higher / lower, closed trades / wins / P&L / liquidations of that day, busts
        that day, and the best and worst account of the day (by the day's change, accounts bust before the day left
        out).

Source and rules (honest by construction):
- Balance = the ``equity`` table (the bot writes every original account's equity every 5 minutes: wallet plus the
  open position at the mark price). Each account's last value in each hour is carried forward while it has none,
  exactly like /api/v4/curves (Data.curves); a day's end is the last value at or before 00:00 KST of the next day.
  Cost at day-30 scale (331 accounts, 2.9M equity rows): the first read ~1.2 s once per process (one primary-key seek
  per account and hour end), then ~20-40 ms per refresh.
- Groups come from paperbot/groups.py (group_of by kind); only the original kinds (accounts.ORIGINAL_KINDS) count:
  copies and new-lab accounts start later and are not part of the race.
- Busts: an account's first closed trade that left its wallet below the bust line (config bust_below), the same test
  the engine makes after every exit.
- Days: Korea time; a past day without a single equity row is "empty" (no record), never a made-up zero.
- Incremental: finished hours are kept in memory (per-group summaries; one per-account vector per finished day), only
  rows newer than the last finished hour are read again, trades are read once by id. Answers are cached (race 60 s,
  calendar 120 s). Nothing is written anywhere.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from typing import Optional

HOUR = 3_600_000
DAY = 86_400_000
KST_MS = 9 * HOUR                    # Korea time: UTC+9, no daylight saving
SETTLE_MS = 15 * 60_000              # an hour is kept once it ended this long ago (late equity rows are in by then)
MIN = 60_000
FINE_STEPS = (5 * MIN, 15 * MIN)     # the young run's steps (auto_step): read straight from equity, cached per step
RACE_STEPS = FINE_STEPS + (HOUR, 4 * HOUR, DAY)
RACE_TTL_S = 60.0
CAL_TTL_S = 120.0
CHUNK_HOURS = 24 * 31               # a long run's first read goes a month at a time (bounded memory, < 999 params)
SYNC_MIN_S = 20.0                    # two answers within this many seconds share one database read
GROUP_KEYS = ("core", "ds200", "reel", "flip")
SERIES = GROUP_KEYS + ("flip5m",)
BUSTS_MAX = 400                      # race answer: at most this many bust marks


def kst_day(ts: int) -> int:
    """The Korea-time day number of an epoch-ms time (days since 1970-01-01 KST)."""
    return (int(ts) + KST_MS) // DAY


def kst_day_start(kd: int) -> int:
    """00:00 KST of day number kd, as epoch ms."""
    return kd * DAY - KST_MS


def day_label(kd: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(kd * 86_400))


def weekday(kd: int) -> int:
    """0 = Monday .. 6 = Sunday (1970-01-01 was a Thursday)."""
    return (kd + 3) % 7


def quantile(xs: list, q: float) -> Optional[float]:
    """Linear-interpolated quantile of a SORTED list (numpy's default method)."""
    n = len(xs)
    if not n:
        return None
    pos = q * (n - 1)
    i = int(pos)
    if i + 1 >= n:
        return xs[-1]
    return xs[i] + (xs[i + 1] - xs[i]) * (pos - i)


def _r(v: Optional[float], d: int = 2) -> Optional[float]:
    return None if v is None else round(float(v), d)


def auto_step(start: int, now: int) -> int:
    """The race's step by run age: 5 minutes under 2 days, 15 minutes under 7 days, then 1 hour (40 days), 4 hours
    (160 days), one day. A young run has only a handful of hourly points, but 5-minute equity rows exist from the start."""
    days = (now - start) / DAY
    if days < 2:
        return 5 * MIN
    if days < 7:
        return 15 * MIN
    return HOUR if days <= 40 else 4 * HOUR if days <= 160 else DAY


class Flow:
    """The incremental reader behind both routes (one per app)."""

    def __init__(self, data, now_fn=None):
        self.data = data
        self.now_fn = now_fn or (lambda: int(time.time() * 1000))
        self.lock = threading.Lock()
        self.st: Optional[dict] = None
        self.synced_at = 0.0
        self.cache: dict = {}
        self.fine: dict = {}            # step -> the finished fine steps' summaries (5 / 15 minutes, a young run only)

    # ------------------------------------------------------------ reading
    def _bust_below(self, c) -> float:
        from ...config import v3_settings
        try:
            return float(v3_settings().bust_below)
        except Exception:  # noqa: BLE001  (the rule set never fails to build; a fallback keeps the page up)
            return 10.0

    def _fresh_state(self, c, now: int) -> Optional[dict]:
        import numpy as np
        from ...accounts import ORIGINAL_KINDS
        from ... import groups as G
        from ...config import REEL_TF
        q = ",".join("?" * len(ORIGINAL_KINDS))
        rows = c.execute(f"SELECT account_id, kind, timeframe, created_ts FROM accounts WHERE kind IN ({q}) "
                         "ORDER BY rowid", ORIGINAL_KINDS).fetchall()
        if not rows:
            return None
        start = min(int(r[3]) for r in rows)
        ids = tuple(r[0] for r in rows)
        members: dict = {k: [] for k in SERIES}
        grp = []
        for i, (aid, kind, tf, _c) in enumerate(rows):
            g = G.group_of({"kind": kind})
            grp.append(g)
            if g in members:
                members[g].append(i)
            if kind == "random" and tf == REEL_TF:
                members["flip5m"].append(i)
        initial = float(self.data.initial())
        first = {k: initial if members[k] else None for k in SERIES}
        return {"start": start, "ids": ids, "idx": {a: i for i, a in enumerate(ids)}, "grp": grp, "members": members,
                "initial": initial, "bust_below": self._bust_below(c),
                "done_b": start // HOUR - 1,                    # rows with ts > (done_b + 1) * HOUR are not read yet
                "last": np.full(len(ids), initial),
                # hourly summaries of the finished hours; the first point is the start itself (everyone at initial)
                "pts": {"t": [start], **{k: [first[k]] for k in SERIES}, "lo": [first["flip"]], "hi": [first["flip"]]},
                "day_end": {}, "rows_day": {},
                "trade_id": 0, "agg": {}, "bust": {}, "bust_day": {},
                "tmp": None}

    def _summaries(self, st: dict, F) -> dict:
        """Per-row group medians (and the coin flips' 25th / 75th percentile) of an hours x accounts matrix."""
        import numpy as np
        out = {}
        for k in SERIES:
            idxs = st["members"][k]
            if not idxs:
                out[k] = [None] * len(F)
                continue
            if k == "flip":
                q = np.quantile(F[:, idxs], [0.25, 0.5, 0.75], axis=1)       # linear, like quantile() below
                out["lo"], out[k], out["hi"] = q[0].tolist(), q[1].tolist(), q[2].tolist()
            else:
                out[k] = np.median(F[:, idxs], axis=1).tolist()
        for k in ("lo", "hi"):
            out.setdefault(k, [None] * len(F))
        return out

    def sync(self, force: bool = False) -> Optional[dict]:
        """Read what is new since the last call (at most once per SYNC_MIN_S unless forced); returns the state."""
        with self.lock:
            if not force and self.st is not None and time.monotonic() - self.synced_at < SYNC_MIN_S:
                return self.st
            now = int(self.now_fn())
            with self.data.conn() as c:
                st = self.st
                fresh = self._fresh_state(c, now)
                if fresh is None:
                    self.st, self.synced_at = None, time.monotonic()
                    return None
                if st is None or st["start"] != fresh["start"] or st["ids"] != fresh["ids"]:
                    st = fresh                                  # a new run (or the first call)
                self._read_equity(c, st, now)
                self._read_trades(c, st)
            self.st, self.synced_at = st, time.monotonic()
            return st

    def _hours(self, c, st: dict, last, b0: int, b1: int):
        """Hours b0..b1 (hour b holds rows with ts in (b*H, (b+1)*H]: a row at exactly 13:00 is the balance at 13:00,
        the end of the 12:00 hour) as an hours x accounts matrix of each account's LAST row in the hour, carried forward
        from ``last``; and the number of accounts with a row in each hour. The bot writes equity at whole 5-minute
        marks, so an hour's last row is normally the one at its end: those are read by an indexed range per account;
        only hours without that row (the running hour, an outage) are read in full for that account."""
        import numpy as np
        nb, n = b1 - b0 + 1, len(st["ids"])
        M = np.full((nb, n), np.nan)
        ends = [(b0 + j + 1) * HOUR for j in range(nb)]
        q = "SELECT ts, equity FROM equity WHERE account_id = ? AND ts IN (%s)" % ",".join("?" * nb)
        for i, aid in enumerate(st["ids"]):
            rows = c.execute(q, (aid, *ends)).fetchall()            # one primary-key seek per hour end
            for ts, eq in rows:
                M[ts // HOUR - 1 - b0, i] = eq
            if len(rows) == nb:
                continue
            miss = np.flatnonzero(np.isnan(M[:, i]))
            # contiguous runs of hours without an end-of-hour row: one small grouped read each
            runs = np.split(miss, np.flatnonzero(np.diff(miss) != 1) + 1)
            for r in runs:
                if not len(r):
                    continue
                for b, eq, _ts in c.execute("SELECT (ts - 1) / ? AS b, equity, MAX(ts) FROM equity WHERE account_id = ? "
                                            "AND ts > ? AND ts <= ? GROUP BY b",
                                            (HOUR, aid, (b0 + int(r[0])) * HOUR, (b0 + int(r[-1]) + 1) * HOUR)):
                    M[int(b) - b0, i] = eq
        got = (~np.isnan(M)).sum(axis=1)
        # carry forward: each empty cell takes the account's previous value (row 0 of P is ``last``, never empty)
        P = np.vstack([np.asarray(last, dtype=float)[None, :], M])
        pick = np.where(np.isnan(P), 0, np.arange(nb + 1)[:, None])
        np.maximum.accumulate(pick, axis=0, out=pick)
        return P[pick, np.arange(n)][1:], got

    def _read_equity(self, c, st: dict, now: int) -> None:
        cur_b = (now - 1) // HOUR
        settled_b = (now - SETTLE_MS) // HOUR - 1
        pts = st["pts"]

        def put(F, got, b0: int, dst: dict, day_end: dict, rows_day: dict, now_t: Optional[int]) -> None:
            sm = self._summaries(st, F)
            for j in range(len(F)):
                end = (b0 + j + 1) * HOUR
                dst["t"].append(now_t if (now_t is not None and j == len(F) - 1) else end)
                for k in SERIES + ("lo", "hi"):
                    dst[k].append(sm[k][j])
                kd = kst_day(end - 1)
                rows_day[kd] = rows_day.get(kd, 0) + int(got[j])
                if (end + KST_MS) % DAY == 0:                 # 00:00 KST: the end of day kd
                    day_end[kd] = F[j].copy()
        b = st["done_b"] + 1
        while b <= settled_b:                                   # finished hours, kept (in chunks: bounded memory)
            e = min(settled_b, b + CHUNK_HOURS - 1)
            F, got = self._hours(c, st, st["last"], b, e)
            put(F, got, b, pts, st["day_end"], st["rows_day"], None)
            st["last"], st["done_b"] = F[-1].copy(), e
            b = e + 1
        tmp = {"pts": {"t": [], **{k: [] for k in SERIES}, "lo": [], "hi": []}, "day_end": {}, "rows_day": {},
               "now_vec": st["last"], "now": now}
        if st["done_b"] + 1 <= cur_b:                           # the running hours: computed every time, never kept
            F, got = self._hours(c, st, st["last"], st["done_b"] + 1, cur_b)
            put(F, got, st["done_b"] + 1, tmp["pts"], tmp["day_end"], tmp["rows_day"], now)
            tmp["now_vec"] = F[-1]
        st["tmp"] = tmp

    def _read_trades(self, c, st: dict) -> None:
        idx, grp, bb = st["idx"], st["grp"], st["bust_below"]
        top = st["trade_id"]
        for tid, aid, ext, pnl, reason, eq_after in c.execute(
                "SELECT id, account_id, exit_time, pnl, exit_reason, equity_after FROM trades WHERE id > ? ORDER BY id",
                (st["trade_id"],)):
            top = max(top, int(tid))
            i = idx.get(aid)
            if i is None:                                      # copies / new-lab accounts: not in the race
                continue
            g = grp[i]
            kd = kst_day(ext - 1)                              # an exit at 00:00 sharp closes the day before
            a = st["agg"].setdefault((g, kd), [0, 0, 0.0, 0])
            a[0] += 1
            a[1] += pnl > 0
            a[2] += float(pnl)
            a[3] += reason == "LIQ"
            if eq_after < bb and aid not in st["bust"]:
                st["bust"][aid] = int(ext)
                st["bust_day"][(g, kd)] = st["bust_day"].get((g, kd), 0) + 1
        st["trade_id"] = top

    # ------------------------------------------------------------ answers
    def _cached(self, key, ttl: float, make):
        hit = self.cache.get(key)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1]
        v = make()
        if len(self.cache) > 16:                             # a few steps and seasons at most; never grows unbounded
            self.cache.clear()
        self.cache[key] = (time.monotonic(), v)
        return v

    @staticmethod
    def _next_verdict(start: int, now: int) -> tuple[int, int]:
        from ...checkpoint import checkpoint_ts
        k = 1
        while checkpoint_ts(start, k) <= now:
            k += 1
        return k, checkpoint_ts(start, k)

    def race(self, step: str = "auto") -> dict:
        try:
            want = int(step)
        except (TypeError, ValueError):
            want = 0
        want = min(RACE_STEPS, key=lambda x: abs(x - want)) if want > 0 else 0

        def make() -> dict:
            st = self.sync()
            if st is None:
                return {"ready": False, "keys": list(GROUP_KEYS), "t": [], "median": {}, "band": {"lo": [], "hi": []},
                        "busts": [], "n": {}}
            stp = want or auto_step(st["start"], st["tmp"]["now"])
            if stp < HOUR and st["tmp"]["now"] - st["start"] >= 7 * DAY:
                stp = HOUR                              # a fine step only while the run is young (bounded reads)
            if stp < HOUR:
                return self._race(st, stp, self._fine_pts(st, stp))
            return self._race(st, stp)
        return self._cached(("race", want), RACE_TTL_S, make)

    def _fine_pts(self, st: dict, stp: int) -> tuple:
        """A young run's race at a 5- or 15-minute step: each account's last equity row in each step (carried forward
        while it has none), summarized like the hours. Finished steps are kept per step; only newer rows are read
        (one indexed range read per account). Only a run under 7 days old is drawn this fine (race() falls back to 1 hour)."""
        import numpy as np
        now = st["tmp"]["now"]
        with self.lock:
            fs = self.fine.get(stp)
            if fs is None or fs["start"] != st["start"] or fs["ids"] != st["ids"]:
                fs = {"start": st["start"], "ids": st["ids"], "done_b": st["start"] // stp - 1,
                      "last": np.full(len(st["ids"]), st["initial"]),
                      "pts": {k: [v[0]] for k, v in st["pts"].items()}}
                self.fine[stp] = fs
            cur_b, settled_b = (now - 1) // stp, (now - SETTLE_MS) // stp - 1

            def put(F, b0: int, dst: dict, now_t: Optional[int]) -> None:
                sm = self._summaries(st, F)
                for j in range(len(F)):
                    dst["t"].append(now_t if (now_t is not None and j == len(F) - 1) else (b0 + j + 1) * stp)
                    for k in SERIES + ("lo", "hi"):
                        dst[k].append(sm[k][j])
            tmp = {k: [] for k in fs["pts"]}
            with self.data.conn() as c:
                if fs["done_b"] + 1 <= settled_b:
                    F = self._steps(c, st, fs["last"], fs["done_b"] + 1, settled_b, stp)
                    put(F, fs["done_b"] + 1, fs["pts"], None)
                    fs["last"], fs["done_b"] = F[-1].copy(), settled_b
                if fs["done_b"] + 1 <= cur_b:
                    F = self._steps(c, st, fs["last"], fs["done_b"] + 1, cur_b, stp)
                    put(F, fs["done_b"] + 1, tmp, now)
            return fs["pts"], tmp

    @staticmethod
    def _steps(c, st: dict, last, b0: int, b1: int, stp: int):
        """Steps b0..b1 of ``stp`` ms (step b holds rows with ts in (b*stp, (b+1)*stp]) as a steps x accounts matrix of
        each account's last row in the step, carried forward from ``last`` (the hours' rule at a finer step)."""
        import numpy as np
        nb, n = b1 - b0 + 1, len(st["ids"])
        M = np.full((nb, n), np.nan)
        for i, aid in enumerate(st["ids"]):
            for b, eq, _ts in c.execute("SELECT (ts - 1) / ? AS b, equity, MAX(ts) FROM equity WHERE account_id = ? "
                                        "AND ts > ? AND ts <= ? GROUP BY b", (stp, aid, b0 * stp, (b1 + 1) * stp)):
                if b0 <= int(b) <= b1:
                    M[int(b) - b0, i] = eq
        P = np.vstack([np.asarray(last, dtype=float)[None, :], M])
        pick = np.where(np.isnan(P), 0, np.arange(nb + 1)[:, None])
        np.maximum.accumulate(pick, axis=0, out=pick)
        return P[pick, np.arange(n)][1:]

    def _race(self, st: dict, stp: int, fine: Optional[tuple] = None) -> dict:
        tmp = st["tmp"]
        now = tmp["now"]
        P, T = fine if fine is not None else (st["pts"], tmp["pts"])
        ts = P["t"] + T["t"]
        keep = [j for j, t in enumerate(ts) if j == 0 or j == len(ts) - 1 or (t + KST_MS) % stp == 0]

        def col(k: str) -> list:
            xs = P[k] + T[k]
            return [_r(xs[j]) for j in keep]
        k, nxt = self._next_verdict(st["start"], now)
        busts = sorted((t, st["grp"][st["idx"][a]]) for a, t in st["bust"].items())[-BUSTS_MAX:]
        return {"ready": True, "initial": st["initial"], "start": st["start"], "now": now, "step": stp,
                "next_verdict": nxt, "verdict_k": k, "keys": list(GROUP_KEYS),
                "n": {g: len(st["members"][g]) for g in SERIES},
                "t": [ts[j] for j in keep], "median": {g: col(g) for g in SERIES},
                "band": {"lo": col("lo"), "hi": col("hi")},
                "busts": [[t, g] for t, g in busts],
                "source": "equity", "settled_to": (st["done_b"] + 1) * HOUR}

    @staticmethod
    def seasons(start: int, today: int) -> list[tuple[int, int, int]]:
        """[(first KST day, last KST day, verdict ts)] of every season up to the one holding ``today``. Season k ends
        on the KST day of the (k+1)-th verdict (checkpoint.checkpoint_ts: 00:00 UTC = 09:00 KST, so the first season
        holds 31 KST days: the start day through the verdict day); the next one starts the day after."""
        from ...checkpoint import checkpoint_ts
        out, first, k = [], kst_day(start), 1
        while True:
            cp = checkpoint_ts(start, k)
            out.append((first, kst_day(cp), cp))
            if today <= kst_day(cp) or k > 400:
                return out
            first, k = kst_day(cp) + 1, k + 1

    def calendar(self, season: Optional[int] = None) -> dict:
        def make() -> dict:
            st = self.sync()
            if st is None:
                return {"ready": False, "season": 0, "seasons": 0, "days": []}
            ss = self.seasons(st["start"], kst_day(st["tmp"]["now"]))
            s = len(ss) - 1 if season is None else max(0, min(int(season), len(ss) - 1))
            return self._calendar(st, s, ss)
        return self._cached(("cal", season), CAL_TTL_S, make)

    @staticmethod
    def _vec_end(st: dict, kd: int, today: int):
        if kd == today:
            return st["tmp"]["now_vec"]
        v = st["day_end"].get(kd)
        return st["tmp"]["day_end"].get(kd) if v is None else v

    def _calendar(self, st: dict, s: int, ss: list) -> dict:
        tmp = st["tmp"]
        now = tmp["now"]
        d0, today = kst_day(st["start"]), kst_day(now)
        first, last, verdict = ss[s]
        init_vec = [st["initial"]] * len(st["ids"])
        bb = st["bust_below"]
        days = []
        for kd in range(first, last + 1):
            e = {"d": day_label(kd), "ts": kst_day_start(kd), "i": kd - d0, "dow": weekday(kd)}
            if kd == kst_day(verdict):
                e["verdict"] = verdict
            if kd > today:
                e["state"] = "future"
                days.append(e)
                continue
            rows = st["rows_day"].get(kd, 0) + tmp["rows_day"].get(kd, 0)
            end = self._vec_end(st, kd, today)
            beg = init_vec if kd == d0 else self._vec_end(st, kd - 1, today)
            if end is None or beg is None or (rows == 0 and kd != today):
                e["state"] = "empty"                            # no equity row that day: no record, never a zero
                days.append(e)
                continue
            e["state"] = "today" if kd == today else "done"
            e["g"] = {g: self._day_group(st, g, beg, end, kd, bb) for g in GROUP_KEYS if st["members"][g]}
            f5 = st["members"]["flip5m"]
            if f5:
                ms, me = quantile(sorted(beg[i] for i in f5), .5), quantile(sorted(end[i] for i in f5), .5)
                e["f5"] = {"med": _r(me), "chg": _r(me / ms - 1, 6) if ms and ms > 0 else None, "n": len(f5)}
            days.append(e)
        return {"ready": True, "initial": st["initial"], "start": st["start"], "now": now, "today": day_label(today),
                "season": s, "seasons": len(ss), "verdict_ts": verdict, "keys": list(GROUP_KEYS),
                "n": {g: len(st["members"][g]) for g in GROUP_KEYS}, "n_flip5m": len(st["members"]["flip5m"]),
                "bust_below": bb, "days": days}

    def _day_group(self, st: dict, g: str, beg, end, kd: int, bb: float) -> dict:
        idxs = st["members"][g]
        ms = quantile(sorted(beg[i] for i in idxs), .5)
        me = quantile(sorted(end[i] for i in idxs), .5)
        up = down = 0
        best = worst = None
        for i in idxs:
            a, b = beg[i], end[i]
            if a < bb:                                         # bust before the day began: nothing left to move
                continue
            r = float(b / a - 1)
            if r > 1e-9:
                up += 1
            elif r < -1e-9:
                down += 1
            if best is None or r > best[0]:
                best = (r, i, b)
            if worst is None or r < worst[0]:
                worst = (r, i, b)
        n, w, pnl, liq = st["agg"].get((g, kd), (0, 0, 0.0, 0))
        out = {"med": _r(me), "chg": _r(me / ms - 1, 6) if ms and ms > 0 else None, "up": up, "down": down,
               "trades": n, "wins": w, "pnl": _r(pnl), "liq": liq, "busts": st["bust_day"].get((g, kd), 0)}
        if best is not None:
            out["best"] = {"id": st["ids"][best[1]], "chg": _r(best[0], 6), "eq": _r(best[2])}
            out["worst"] = {"id": st["ids"][worst[1]], "chg": _r(worst[0], 6), "eq": _r(worst[2])}
        return out


def register(app, ctx):
    from fastapi import HTTPException
    from ..app import json_finite
    flow = Flow(ctx.data)

    @app.get("/api/v4/flow/race")
    def flow_race(step: str = "auto"):
        """Each group's median balance over the run with the coin flips' middle 50 % (Flow.race; 60 s cache)."""
        try:
            return json_finite(flow.race(step))
        except sqlite3.Error as exc:
            raise HTTPException(503, f"paper3.db를 읽지 못함: {type(exc).__name__}")

    @app.get("/api/v4/flow/calendar")
    def flow_calendar(season: Optional[int] = None):
        """One entry per KST day of a 30-day season: group medians, the day's change, trades, busts (120 s cache)."""
        try:
            return json_finite(flow.calendar(season))
        except sqlite3.Error as exc:
            raise HTTPException(503, f"paper3.db를 읽지 못함: {type(exc).__name__}")

    return flow

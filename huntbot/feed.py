"""huntbot-feed: Binance USD-M public bars into store.db, every 5 minutes, for the coins of the hunt universe that
still trade.

    python -m huntbot feed run                      the service: a pass shortly after every 5m close, forever
    python -m huntbot feed once                     one pass (everything missing since the newest stored bar)
    python -m huntbot feed backfill                 the history from the warm-up start (resumable)
    python -m huntbot feed import-npz DIR [--from YYYY-MM-DD]
                                                    bars / marks / funding from a coins30-format folder
                                                    (``research.hunt.data_hunt download`` output) into the store
    python -m huntbot feed coin-reset SYMBOL        undo a coin end the feed set (the coin is polled again)
    python -m huntbot feed status                   the mark, the coins, the last log lines

A pass (``Feed.cycle``): exchange status (hourly, see below), the next funding time of every coin (premiumIndex), then
per coin the closed 5m klines and mark-price klines after its newest stored bar (a kline counts as closed once its
close time is ``SETTLE_MS`` behind the clock, as paperbot/feed.py), new funding rates and the open interest. Every
coin is committed on its own (a pass that fails half way keeps what it stored; a rollback also forgets the cached
newest bar per coin, so nothing rolled back is skipped later). The first pass is the history download from the
warm-up start (30-40 minutes on a fresh server): it prints progress lines and can be stopped and restarted at any
time. Then the completeness mark ``complete_ms``: the runner processes the bars with open < complete_ms, so it is the
newest 5m boundary that every trading coin has reached, held back before a funding time whose rate has not arrived yet
(the hunt charges funding after the bar ending at its time, PREREG_HUNT 7.6) and never moved back. A coin that brings
no new bar for ``MAX_WAIT_MS`` (exchange maintenance) or a funding rate that does not come in that time stops holding
the mark; such a row arriving later is a late row (logged; the runner reloads that coin, and a closed trade that
changes because of it is recorded as changed, runner.py ``record_trades``).

The first mark is set only once every trading coin's history is complete: its first stored bar is the warm-up start
or the exchange has nothing earlier (``check_history``). Every hour the stored bars of every coin are checked for holes
(``repair_gaps``); a hole is fetched again (at most ``GAP_TRIES`` times: Binance's own gaps stay).

Coin end (PREREG_HUNT 3: a coin that stops trading ends at its last 5m bar with volume). One exchangeInfo read never
ends a coin: a body without BTCUSDT trading or with far fewer symbols than the last good read is ignored, and a coin is
ended only after its status has read non-TRADING on ``END_READS`` hourly reads in a row spanning ``END_SPAN_MS`` with no
new 5m bar in that time (it is polled all the while). A coin end the feed set is undone when the coin reads TRADING
again within ``REVIVE_MS``; later only by hand (``feed coin-reset SYMBOL``).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Optional

import numpy as np

from . import config as CFG
from .binance import BinanceDown, BinanceError, Client
from .store import Store

FIVE = CFG.FIVE
SETTLE_MS = 10_000              # a kline is final once its close time is this far behind the clock
MAX_WAIT_MS = 10 * 60_000       # a coin without its next bar (or a due funding rate) holds the mark at most this long
EXCHANGE_EVERY_MS = 3_600_000
END_READS = 4                   # non-TRADING exchangeInfo reads in a row before a coin end ...
END_SPAN_MS = 3 * 3_600_000     # ... spanning at least this long, with no new 5m bar since the first of them
REVIVE_MS = 24 * 3_600_000      # a coin end the feed set is undone when the coin trades again within this time
GAP_TRIES = 3                   # a hole in the stored bars is fetched again at most this many times
GAPS_PER_PASS = 20
PAGE = 1000                     # klines per request when catching up (weight 5)
LIVE_PAGE = 99                  # klines per request in steady state (weight 1)
FUND_TOL_MS = 60_000


def _grid(ms: int) -> int:
    """A funding time on the 5m grid, as research/hunt/hunt.py Market does."""
    return ((int(ms) + 30_000) // FIVE) * FIVE


class Feed:
    def __init__(self, store: Store, client: Client, universe: list, warmup_ms: int, clock=time.time,
                 log=print, settle_ms: int = SETTLE_MS, max_wait_ms: int = MAX_WAIT_MS):
        self.store, self.client, self.universe = store, client, list(universe)
        self.warmup_ms, self.clock, self.out = int(warmup_ms), clock, log
        self.settle_ms, self.max_wait_ms = settle_ms, max_wait_ms
        self.last_exchange_ms = 0

    def now_ms(self) -> int:
        return int(self.clock() * 1000)

    # ------------------------------------------------------------ exchange status, coin ends
    def _body_problem(self, st: dict) -> Optional[str]:
        """Why an exchangeInfo body is not believed (None = fine): no symbols, BTCUSDT missing or not trading (when it
        is in the universe), or far fewer symbols than the last good read."""
        if not st:
            return "no symbols"
        if "BTCUSDT" in self.universe and (st.get("BTCUSDT") or {}).get("status") != "TRADING":
            return "BTCUSDT missing or not TRADING"
        last = self.store.get("exchange_n")
        if last and len(st) < 0.5 * int(last):
            return f"{len(st)} symbols (last good read {last})"
        return None

    def refresh_exchange(self, force: bool = False) -> dict:
        now = self.now_ms()
        if not force and now - self.last_exchange_ms < EXCHANGE_EVERY_MS:
            return {}
        info = self.client.exchange_info()
        st = {s.get("symbol"): s for s in (info.get("symbols") or []) if isinstance(s, dict)} \
            if isinstance(info, dict) else {}
        self.last_exchange_ms = now
        bad = self._body_problem(st)
        if bad:
            self.store.log("warn", f"exchangeInfo ignored: {bad}")
            self.out(f"{CFG.TAG} exchangeInfo ignored ({bad}): coin status unchanged")
            self.store.commit()
            return {}
        self.store.put("exchange_n", len(st))
        known = self.store.coins()
        off = dict(self.store.get("off", {}) or {})
        ended_at = dict(self.store.get("ended_at", {}) or {})
        for sym in self.universe:
            s = st.get(sym) or {}
            status = s.get("status") or "MISSING"
            ok = status == "TRADING" and s.get("contractType", "PERPETUAL") == "PERPETUAL"
            c = known.get(sym) or {}
            was, end = c.get("trading"), c.get("end_ms")
            self.store.set_coin(sym, status=status)
            if end is not None:                             # ended earlier
                if ok and sym in ended_at and now - int(ended_at[sym]) <= REVIVE_MS:
                    self.store.set_coin(sym, trading=1, end_ms=None, note=f"trading again ({status}): coin end undone")
                    ended_at.pop(sym, None)
                    self.store.log("warn", f"{sym} trades again: its coin end {CFG.ms_str(end)} is undone")
                    self.out(f"{CFG.TAG} {sym} trades again: coin end undone")
                elif ok:
                    self.store.set_coin(sym, note="trading again after a coin end: not re-added "
                                                  "(python -m huntbot feed coin-reset " + sym + ")")
                continue
            if ok:
                if off.pop(sym, None) is not None:
                    self.store.log("info", f"{sym} reads TRADING again")
                self.store.set_coin(sym, trading=1, note=None)
                continue
            if was != 1:                                    # never seen trading: not polled
                self.store.set_coin(sym, trading=0)
                continue
            last = self.store.max_open(sym)
            o = off.get(sym)
            if o is None or (last is not None and o.get("bar") is not None and last > int(o["bar"])):
                o = {"since": now, "reads": 0, "bar": last}      # first read off, or bars still came: count again
            o["reads"] = int(o["reads"]) + 1
            o["status"] = status
            off[sym] = o
            if o["reads"] >= END_READS and now - int(o["since"]) >= END_SPAN_MS:
                end = self.store.conn.execute("SELECT MAX(open_ms) FROM bars_5m WHERE symbol = ? AND qv > 0",
                                              (sym,)).fetchone()[0]
                self.store.set_coin(sym, trading=0, end_ms=end, note=f"stopped trading ({status})")
                off.pop(sym, None)
                ended_at[sym] = now
                self.store.log("warn", f"{sym} stopped trading ({status}, {o['reads']} reads since "
                                       f"{CFG.ms_str(o['since'])}); coin end {CFG.ms_str(end)}")
                self.out(f"{CFG.TAG} {sym} stopped trading ({status}); coin end {CFG.ms_str(end)} UTC")
            else:
                self.store.set_coin(sym, note=f"status {status} ({o['reads']} read(s) since "
                                              f"{CFG.ms_str(o['since'])} UTC; still polled)")
        self.store.put("off", off)
        self.store.put("ended_at", ended_at)
        self.store.commit()
        return st

    def coin_reset(self, sym: str) -> dict:
        """Undo a coin end (by hand): the coin is polled again from its newest stored bar."""
        c = self.store.coins().get(sym)
        if c is None:
            raise KeyError(f"{sym} is not in the store")
        self.store.set_coin(sym, trading=1, end_ms=None, note="coin end undone by hand (coin-reset)")
        for k in ("off", "ended_at"):
            d = dict(self.store.get(k, {}) or {})
            d.pop(sym, None)
            self.store.put(k, d)
        self.store.log("warn", f"{sym}: coin end undone by hand (was {CFG.ms_str(c.get('end_ms'))})")
        self.store.commit()
        return self.store.coins()[sym]

    def trading(self) -> list:
        c = self.store.coins()
        return [s for s in self.universe if (c.get(s) or {}).get("trading") == 1 and not (c.get(s) or {}).get("end_ms")]

    # ------------------------------------------------------------ bars
    def _closed(self, rows: list, now: int) -> list:
        return [r for r in rows if isinstance(r, list) and len(r) >= 7 and int(r[6]) + self.settle_ms < now]

    def poll_bars(self, sym: str, now: Optional[int] = None, progress: bool = False) -> int:
        now = self.now_ms() if now is None else now
        last = self.store.max_open(sym)
        start = self.warmup_ms if last is None else last + FIVE
        got = 0
        while start + FIVE + self.settle_ms < now:
            limit = LIVE_PAGE if (now - start) // FIVE < LIVE_PAGE else PAGE
            rows = self._closed(self.client.klines(sym, start, limit), now)
            rows = [r for r in rows if int(r[0]) >= start and int(r[0]) % FIVE == 0]
            if not rows:
                break
            new, _late = self.store.insert_bars(sym, [(int(r[0]), r[1], r[2], r[3], r[4], r[5], r[7]) for r in rows])
            got += new
            start = int(rows[-1][0]) + FIVE
            if progress and got and got % 20_000 < len(rows):
                self.out(f"{CFG.TAG}   {sym}: {got:,} bars ({CFG.ms_str(start)} UTC)")
            if len(rows) < limit - 1:
                break
        if got:
            self.store.set_coin(sym, last_bar_ms=self.store.max_open(sym))
        return got

    def fill_span(self, sym: str, a: int, b: int, now: Optional[int] = None) -> int:
        """Fetch the coin's closed 5m bars with a <= open < b (a hole, or the history before the first stored bar)."""
        now = self.now_ms() if now is None else now
        start, got = int(a), 0
        while start < b and start + FIVE + self.settle_ms < now:
            rows = self._closed(self.client.klines(sym, start, PAGE), now)
            rows = [r for r in rows if start <= int(r[0]) < b and int(r[0]) % FIVE == 0]
            if not rows:
                break
            new, _late = self.store.insert_bars(sym, [(int(r[0]), r[1], r[2], r[3], r[4], r[5], r[7]) for r in rows])
            got += new
            start = int(rows[-1][0]) + FIVE
        return got

    def check_history(self, sym: str) -> bool:
        """The coin's history is complete from the warm-up start (or from its listing). A missing head (bars before
        the first stored one that the exchange has) is fetched first."""
        ok = set(self.store.get("history_ok", []) or [])
        if sym in ok:
            return True
        first = self.store.first_open(sym)
        if first is None:
            return False
        if first > self.warmup_ms:
            rows = self._closed(self.client.klines(sym, self.warmup_ms, 1), self.now_ms())
            ex_first = int(rows[0][0]) if rows else None
            if ex_first is not None and ex_first < first:
                n = self.fill_span(sym, ex_first, first)
                self.store.log("warn", f"{sym}: {n} history bar(s) before {CFG.ms_str(first)} were missing; fetched")
                self.out(f"{CFG.TAG} {sym}: {n:,} missing history bars fetched (before {CFG.ms_str(first)} UTC)")
                if (self.store.first_open(sym) or first) > ex_first:
                    return False
        ok.add(sym)
        self.store.put("history_ok", sorted(ok))
        return True

    def repair_gaps(self, sym: str) -> dict:
        """Holes inside the coin's stored bars (from the warm-up start): each fetched again, at most GAP_TRIES times
        (a hole Binance itself has stays after that)."""
        tried = dict(self.store.get("gaps_tried", {}) or {})
        found = filled = 0
        for a, b in self.store.gaps(sym, self.warmup_ms)[:GAPS_PER_PASS]:
            key = f"{sym}:{a}:{b}"
            if int(tried.get(key, 0)) >= GAP_TRIES:
                continue
            found += 1
            n = self.fill_span(sym, a, b)
            filled += n
            tried[key] = int(tried.get(key, 0)) + 1
            if n:
                self.store.log("warn", f"{sym}: hole {CFG.ms_str(a)}..{CFG.ms_str(b)} UTC: {n} bar(s) fetched again")
        self.store.put("gaps_tried", tried)
        return {"holes": found, "bars": filled}

    def poll_marks(self, sym: str, now: Optional[int] = None) -> int:
        now = self.now_ms() if now is None else now
        row = self.store.conn.execute("SELECT MAX(open_ms) FROM mark_5m WHERE symbol = ?", (sym,)).fetchone()
        start = self.warmup_ms if not row or row[0] is None else int(row[0]) + FIVE
        got = 0
        while start + FIVE + self.settle_ms < now:
            limit = LIVE_PAGE if (now - start) // FIVE < LIVE_PAGE else PAGE
            rows = self._closed(self.client.klines(sym, start, limit, mark=True), now)
            rows = [r for r in rows if int(r[0]) >= start and int(r[0]) % FIVE == 0]
            if not rows:
                break
            got += self.store.insert_marks(sym, [(int(r[0]), r[1], r[2], r[3], r[4]) for r in rows])
            start = int(rows[-1][0]) + FIVE
            if len(rows) < limit - 1:
                break
        return got

    # ------------------------------------------------------------ funding, open interest
    def poll_funding(self, sym: str, now: Optional[int] = None) -> int:
        now = self.now_ms() if now is None else now
        row = self.store.conn.execute("SELECT MAX(calc_ms) FROM funding WHERE symbol = ?", (sym,)).fetchone()
        start = self.warmup_ms if not row or row[0] is None else int(row[0]) + 1
        got = 0
        for _ in range(100):
            rows = self.client.funding_rates(sym, start, 1000)
            rows = [r for r in rows if isinstance(r, dict) and r.get("fundingTime") is not None
                    and int(r["fundingTime"]) >= start and int(r["fundingTime"]) <= now]
            if not rows:
                break
            got += self.store.insert_funding(sym, [(int(r["fundingTime"]), float(r["fundingRate"])) for r in rows])
            start = max(int(r["fundingTime"]) for r in rows) + 1
            if len(rows) < 1000:
                break
        c = self.store.coins().get(sym) or {}
        exp = c.get("expect_funding_ms")
        if exp is not None:
            have = self.store.conn.execute("SELECT COUNT(*) FROM funding WHERE symbol = ? AND calc_ms >= ?",
                                           (sym, int(exp) - FUND_TOL_MS)).fetchone()[0]
            if have:
                self.store.set_coin(sym, expect_funding_ms=None)
        return got

    def poll_premium(self, now: Optional[int] = None) -> None:
        """Next funding time of every coin; a funding time that has passed is expected until its rate is stored."""
        now = self.now_ms() if now is None else now
        rows = self.client.premium_index()
        pm = {r.get("symbol"): r for r in rows if isinstance(r, dict)} if isinstance(rows, list) else {}
        coins = self.store.coins()
        for sym in self.trading():
            nxt = (pm.get(sym) or {}).get("nextFundingTime")
            if nxt is None:
                continue
            nxt = int(nxt)
            prev = (coins.get(sym) or {}).get("next_funding_ms")
            if prev is not None and prev < nxt and prev <= now:
                have = self.store.conn.execute(
                    "SELECT COUNT(*) FROM funding WHERE symbol = ? AND calc_ms BETWEEN ? AND ?",
                    (sym, prev - FUND_TOL_MS, prev + FUND_TOL_MS)).fetchone()[0]
                if not have:
                    self.store.set_coin(sym, expect_funding_ms=prev)
            self.store.set_coin(sym, next_funding_ms=nxt)

    def poll_oi(self, sym: str) -> None:
        d = self.client.open_interest(sym)
        if isinstance(d, dict) and d.get("openInterest") is not None and d.get("time") is not None:
            self.store.insert_oi(sym, int(d["time"]), float(d["openInterest"]))

    # ------------------------------------------------------------ the completeness mark
    def compute_complete(self, now: Optional[int] = None) -> Optional[int]:
        now = self.now_ms() if now is None else now
        wall = (now - self.settle_ms) // FIVE * FIVE
        ends, stalled = [], []
        coins = self.store.coins()
        prev = self.store.complete_ms()
        hist = set(self.store.get("history_ok", []) or [])
        for sym in self.trading():
            last = self.store.max_open(sym)
            if prev is None and (last is None or sym not in hist):
                return None                                     # the first download is not finished: no mark yet
            if last is None:
                continue
            end = last + FIVE
            # its next bar has been due for MAX_WAIT_MS: it stops holding the mark (only once a mark exists: while the
            # first download runs, a coin whose history is still coming holds the mark back, so the runner never
            # starts on a part of the coins)
            if prev is not None and wall - end - FIVE >= self.max_wait_ms:
                stalled.append(sym)
                continue
            ends.append(end)
        if not ends:
            return self.store.complete_ms()
        comp = min(min(ends), wall)
        for sym in self.trading():
            exp = (coins.get(sym) or {}).get("expect_funding_ms")
            if exp is not None and now - int(exp) < self.max_wait_ms:
                comp = min(comp, _grid(exp) - FIVE)
        if prev is not None:
            comp = max(comp, int(prev))
        self.store.put("complete_ms", int(comp))
        self.store.put("stalled", stalled)
        return comp

    # ------------------------------------------------------------ passes
    def cycle(self, with_oi: bool = True) -> dict:
        t0 = time.monotonic()
        now = self.now_ms()
        errors = []
        hourly = now - self.last_exchange_ms >= EXCHANGE_EVERY_MS
        try:
            self.refresh_exchange()
        except BinanceError as e:
            errors.append(f"exchangeInfo: {e}")
        try:
            self.poll_premium(now)
            self.store.commit()
        except BinanceError as e:
            errors.append(f"premiumIndex: {e}")
        bars = 0
        syms = self.trading()
        repairs = {}
        for i, sym in enumerate(syms, 1):
            last = self.store.max_open(sym)
            far = (now - (self.warmup_ms if last is None else last)) > CFG.DAY     # the history download (or a long stop)
            if far:
                self.out(f"{CFG.TAG} feed: {i}/{len(syms)} {sym} from "
                         f"{CFG.ms_str(self.warmup_ms if last is None else last + FIVE)} UTC")
            try:
                bars += self.poll_bars(sym, now, progress=far)
                self.poll_marks(sym, now)
                self.poll_funding(sym, now)
                if with_oi:
                    self.poll_oi(sym)
                self.check_history(sym)
                if hourly:
                    r = self.repair_gaps(sym)
                    if r["holes"]:
                        repairs[sym] = r
                self.store.heartbeat("feed", {"pass": "running", "coin": sym, "done": i, "of": len(syms)})
                self.store.commit()                     # each coin on its own: a later failure keeps this one
            except BinanceDown as e:
                self._keep_or_rollback()
                errors.append(f"{sym}: {e}")
                break                                   # Binance down: the rest of the pass is not tried
            except Exception as e:  # noqa: BLE001  one coin's bad answer never stops the others
                self._keep_or_rollback()
                errors.append(f"{sym}: {type(e).__name__}: {e}"[:300])
        comp = self.compute_complete(self.now_ms())
        for e in errors:
            self.store.log("error", e)
        info = {"bars": bars, "complete_ms": comp, "errors": errors[:5], "seconds": round(time.monotonic() - t0, 2),
                "requests": self.client.requests, "weight": self.client.used_weight}
        if repairs:
            info["holes"] = repairs
        self.store.heartbeat("feed", info)
        self.store.commit()
        return info

    def _keep_or_rollback(self) -> None:
        """After a coin failed half way: keep the rows it stored (every row is a closed bar), or roll back and forget
        the cached newest bars when even that commit fails."""
        try:
            self.store.commit()
        except Exception:  # noqa: BLE001
            self.store.rollback()

    def backfill(self) -> dict:
        self.refresh_exchange(force=True)
        out = {}
        syms = self.trading()
        self.out(f"{CFG.TAG} backfill from {CFG.ms_str(self.warmup_ms)} UTC for {len(syms)} trading coins "
                 f"(of {len(self.universe)})")
        for i, sym in enumerate(syms, 1):
            t0 = time.monotonic()
            n = self.poll_bars(sym, progress=True)
            m = self.poll_marks(sym)
            f = self.poll_funding(sym)
            self.check_history(sym)
            self.repair_gaps(sym)
            self.store.commit()
            out[sym] = {"bars": n, "marks": m, "funding": f}
            self.out(f"{CFG.TAG} {i}/{len(syms)} {sym}: {n:,} bars, {m:,} mark bars, {f:,} funding "
                     f"({time.monotonic() - t0:.0f}s)")
        self.poll_premium()
        self.compute_complete()
        self.store.commit()
        return out

    def run_forever(self, sleep=time.sleep) -> None:
        self.out(f"{CFG.TAG} feed: {len(self.universe)} coins in the universe, warm-up from "
                 f"{CFG.ms_str(self.warmup_ms)} UTC")
        first = True
        while True:
            now = self.now_ms()
            if not first:                                       # the first pass at once (it is the history download)
                nxt = (now // FIVE + 1) * FIVE + self.settle_ms + 1_000
                sleep(max(1.0, (nxt - now) / 1000))
            first = False
            try:
                info = self.cycle()
                if info["errors"]:
                    self.out(f"{CFG.TAG} feed: {len(info['errors'])} error(s): {info['errors'][0]}")
            except Exception as e:  # noqa: BLE001  the feed never dies on one bad pass
                self.out(f"{CFG.TAG} feed pass failed: {type(e).__name__}: {e}")
                try:
                    self.store.rollback()                       # also forgets the cached newest bars (no hole)
                    self.store.log("error", f"pass failed: {type(e).__name__}: {e}")
                    self.store.commit()
                except Exception:  # noqa: BLE001
                    pass


def import_npz(store: Store, src: str, universe: list, from_ms: int, log=print) -> dict:
    """Bars, mark bars and funding of a coins30-format folder (<src>/5m/<SYM>.npz, <src>/funding/<SYM>.npz) with
    open >= from_ms into the store (INSERT OR IGNORE: rows already stored stay)."""
    out = {}
    for sym in universe:
        p5 = os.path.join(src, "5m", f"{sym}.npz")
        if not os.path.exists(p5):
            continue
        with np.load(p5) as z:
            ts = np.asarray(z["ts"], np.int64)
            keep = ts >= from_ms
            cols = [np.asarray(z[k], np.float64)[keep] for k in ("o", "h", "l", "c", "v", "qv")]
            marks = [np.asarray(z[k], np.float64)[keep] for k in ("mo", "mh", "ml", "mc")] if "mo" in z else None
        ts = ts[keep]
        n, _ = store.insert_bars(sym, zip(ts.tolist(), *[c.tolist() for c in cols]))
        m = 0
        if marks is not None:
            ok = np.isfinite(marks[0])
            m = store.insert_marks(sym, zip(ts[ok].tolist(), *[c[ok].tolist() for c in marks]))
        f = 0
        pf = os.path.join(src, "funding", f"{sym}.npz")
        if os.path.exists(pf):
            with np.load(pf) as z:
                fts = np.asarray(z["ts"], np.int64)
                rate = np.asarray(z["rate"], np.float64)
            k = fts >= from_ms
            f = store.insert_funding(sym, zip(fts[k].tolist(), rate[k].tolist()))
        store.set_coin(sym, last_bar_ms=store.max_open(sym))
        store.commit()
        out[sym] = {"bars": n, "marks": m, "funding": f}
        log(f"{CFG.TAG} import {sym}: {n:,} bars, {m:,} mark bars, {f:,} funding")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m huntbot feed", description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=("run", "once", "backfill", "import-npz", "status", "coin-reset"))
    ap.add_argument("src", nargs="?")
    ap.add_argument("--from", dest="from_", default=None)
    a = ap.parse_args(argv)
    uni = CFG.load_universe()
    store = Store(CFG.path("store.db"))
    if a.cmd == "coin-reset":
        if not a.src or a.src not in uni["symbols"]:
            ap.error("coin-reset needs a symbol of the universe (e.g. XRPUSDT)")
        c = Feed(store, None, uni["symbols"], CFG.warmup_start_ms()).coin_reset(a.src)
        print(f"{a.src}: polled again (trading={c['trading']}, coin end {CFG.ms_str(c['end_ms'])}); "
              "the runner replays it from 10/01 at its next cycle")
        return 0
    if a.cmd == "status":
        comp = store.complete_ms()
        print(f"complete {CFG.ms_str(comp)} UTC; coins {len(store.coins())}; log:")
        for r in store.recent_log(10):
            print(f"  {CFG.ms_str(r['ts_ms'])} {r['level']} {r['msg']}")
        return 0
    if a.cmd == "import-npz":
        if not a.src:
            ap.error("import-npz needs the folder")
        frm = CFG.day_ms(a.from_) if a.from_ else CFG.warmup_start_ms()
        import_npz(store, a.src, uni["symbols"], frm)
        return 0
    feed = Feed(store, Client(), uni["symbols"], CFG.warmup_start_ms(), log=lambda m: print(m, flush=True))
    if a.cmd == "backfill":
        feed.backfill()
        print(f"{CFG.TAG} backfill done; complete {CFG.ms_str(store.complete_ms())} UTC", flush=True)
        return 0
    if a.cmd == "once":
        feed.refresh_exchange(force=True)
        print(feed.cycle(), flush=True)
        return 0
    feed.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())

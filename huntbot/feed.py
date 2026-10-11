"""huntbot-feed: Binance USD-M public bars into store.db, every 5 minutes, for the coins of the hunt universe that
still trade.

    python -m huntbot feed run                      the service: a pass shortly after every 5m close, forever
    python -m huntbot feed once                     one pass (everything missing since the newest stored bar)
    python -m huntbot feed backfill                 the history from the warm-up start (install; resumable)
    python -m huntbot feed import-npz DIR [--from YYYY-MM-DD]
                                                    bars / marks / funding from a coins30-format folder
                                                    (``research.hunt.data_hunt download`` output) into the store

A pass (``Feed.cycle``): exchange status (hourly: a coin whose status leaves TRADING gets its coin end = its last 5m
bar with volume, PREREG_HUNT 3), the next funding time of every coin (premiumIndex), then per trading coin the closed
5m klines and mark-price klines after its newest stored bar (a kline counts as closed once its close time is
``SETTLE_MS`` behind the clock, as paperbot/feed.py), new funding rates and the open interest. Then the completeness
mark ``complete_ms``: the runner processes the bars with open < complete_ms, so it is the newest 5m boundary that every
trading coin has reached, held back before a funding time whose rate has not arrived yet (the hunt charges funding
after the bar ending at its time, PREREG_HUNT 7.6) and never moved back. A coin that brings no new bar for
``MAX_WAIT_MS`` (exchange maintenance) or a funding rate that does not come in that time stops holding the mark; such a
row arriving later is a late row (logged; the runner reloads that coin).
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
    def refresh_exchange(self, force: bool = False) -> dict:
        now = self.now_ms()
        if not force and now - self.last_exchange_ms < EXCHANGE_EVERY_MS:
            return {}
        info = self.client.exchange_info()
        st = {s.get("symbol"): s for s in info.get("symbols", []) if isinstance(s, dict)}
        known = self.store.coins()
        for sym in self.universe:
            s = st.get(sym) or {}
            status = s.get("status") or "MISSING"
            trading = int(status == "TRADING" and s.get("contractType", "PERPETUAL") == "PERPETUAL")
            was = known.get(sym, {}).get("trading")
            self.store.set_coin(sym, status=status, trading=trading)
            if was == 1 and not trading:
                end = self.store.conn.execute("SELECT MAX(open_ms) FROM bars_5m WHERE symbol = ? AND qv > 0",
                                              (sym,)).fetchone()[0]
                self.store.set_coin(sym, end_ms=end, note=f"stopped trading ({status})")
                self.store.log("warn", f"{sym} stopped trading ({status}); coin end {CFG.ms_str(end)}")
                self.out(f"{CFG.TAG} {sym} stopped trading ({status}); coin end {CFG.ms_str(end)} UTC")
            elif trading and was == 0 and known.get(sym, {}).get("end_ms"):
                self.store.set_coin(sym, note=f"trading again after a coin end ({status}): not re-added")
        self.last_exchange_ms = now
        self.store.commit()
        return st

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
                self.out(f"  {sym}: {got:,} bars ({CFG.ms_str(start)})")
            if len(rows) < limit - 1:
                break
        if got:
            self.store.set_coin(sym, last_bar_ms=self.store.max_open(sym))
        return got

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
        for sym in self.trading():
            last = self.store.max_open(sym)
            if last is None:
                continue
            end = last + FIVE
            if wall - end > self.max_wait_ms:
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
        prev = self.store.complete_ms()
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
        try:
            self.refresh_exchange()
        except BinanceError as e:
            errors.append(f"exchangeInfo: {e}")
        try:
            self.poll_premium(now)
        except BinanceError as e:
            errors.append(f"premiumIndex: {e}")
        bars = 0
        for sym in self.trading():
            try:
                bars += self.poll_bars(sym, now)
                self.poll_marks(sym, now)
                self.poll_funding(sym, now)
                if with_oi:
                    self.poll_oi(sym)
            except BinanceDown as e:
                errors.append(f"{sym}: {e}")
                break                                   # Binance down: the rest of the pass is not tried
            except BinanceError as e:
                errors.append(f"{sym}: {e}")
        comp = self.compute_complete(self.now_ms())
        for e in errors:
            self.store.log("error", e)
        info = {"bars": bars, "complete_ms": comp, "errors": errors[:5], "seconds": round(time.monotonic() - t0, 2),
                "requests": self.client.requests, "weight": self.client.used_weight}
        self.store.heartbeat("feed", info)
        self.store.commit()
        return info

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
        while True:
            now = self.now_ms()
            nxt = (now // FIVE + 1) * FIVE + self.settle_ms + 1_000
            sleep(max(1.0, (nxt - now) / 1000))
            try:
                info = self.cycle()
                if info["errors"]:
                    self.out(f"{CFG.TAG} feed: {len(info['errors'])} error(s): {info['errors'][0]}")
            except Exception as e:  # noqa: BLE001  the feed never dies on one bad pass
                self.out(f"{CFG.TAG} feed pass failed: {type(e).__name__}: {e}")
                try:
                    self.store.conn.rollback()
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
    ap.add_argument("cmd", choices=("run", "once", "backfill", "import-npz", "status"))
    ap.add_argument("src", nargs="?")
    ap.add_argument("--from", dest="from_", default=None)
    a = ap.parse_args(argv)
    uni = CFG.load_universe()
    store = Store(CFG.path("store.db"))
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

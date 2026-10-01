"""Paper v3 live runner: 195 accounts on live Binance data (docs/paper-v3-rules.md).

    python -m paperbot.live3 run --db paper3.db [--brackets FILE | --allow-example-brackets]
    python -m paperbot.live3 status --db paper3.db

Every poll: closed 1m bars (last and mark price, funding) for the six coins and
XRP -> every account's engine steps (entries, stops, profit locks, funding) ->
5m bars -> at each 5m boundary the signal service computes the timeframes that
close there and submits the signals; they fill on the next step at the price
read right after the computation.

Restart: the account states, the last processed minute and the pending signals
are in the store. On start the runner reloads them, rebuilds the 5m history
from Binance and replays the minutes it missed. Signals from those minutes are
logged as LATE and not traded (a live bot would have missed them too).

Extra accounts (copies and new strategies started from approved proposals,
paperbot/extras.py and docs/extra-accounts.md) run in the same book. The only
hook is ``post_boundary(boundary, submitted, timed_out)``, called after the 195's
work at a boundary has been committed; it guards itself, and a last fence here
rolls back its writes and keeps the 195 running. Only one runner may write a
database at a time (a lock file next to it).

No orders are ever sent; the Binance key, if set, must be read-only.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import time
from typing import Callable, Optional

from .accounts import AccountBook, hold_others
from .aggregate import TF_MS, Aggregator
from .binance import BinanceError, BinanceREST, RegionBlocked
from .config import V3_SYMBOLS, v3_settings
from .feed import LiveFeed
from .fillcost import LIMIT as FILL_DEPTH, FillProbe
from . import sweepsig
from .health import DeadMan, sd_notify
from .live import _notifier, _rest, load_brackets
from .notify import CRITICAL, INFO, WARN, Digest, Notifier
from .runinfo import change_text, changes, run_record
from .sigservice import SignalTimeout
from .store3 import Store3

MIN = 60_000
FIVE = TF_MS["5m"]
RECORD_ONLY = ("XRPUSDT",)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RANDOM_RATES = os.path.join(ROOT, "research", "paper_rules", "out", "summary.json")


def account_defs(strategies, tfs, seeds=(1, 2, 3)) -> list[dict]:
    defs = [{"strategy": s, "timeframe": tf, "kind": "strategy"} for tf in tfs for s in strategies]
    defs += [{"strategy": f"RANDOM_{k}", "timeframe": tf, "kind": "random"} for tf in tfs for k in seeds]
    return defs


def random_rates(path: str = RANDOM_RATES) -> dict:
    with open(path) as fh:
        return json.load(fh)["random_rate"]


def book_prices(rest: BinanceREST, symbols) -> dict:
    want = set(symbols)
    out = {}
    for t in rest.book_tickers():
        if t["symbol"] in want:
            out[t["symbol"]] = (float(t["bidPrice"]), float(t["askPrice"]))
    return out


def fetch_5m(rest: BinanceREST, symbol: str, start: int, end: int, pause: float = 0.2) -> list[tuple]:
    """Closed 5m bars with open time in [start, end), oldest first."""
    rows, t = [], start
    while t < end:
        got = rest.klines(symbol, "5m", start_time=t, limit=1500)
        got = [r for r in got if int(r[0]) < end]
        if not got:
            break
        rows += [(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])) for r in got]
        t = int(got[-1][0]) + FIVE
        if len(got) < 1500:
            break
        time.sleep(pause)
    return rows


class Runner3:
    def __init__(self, book: AccountBook, service, store: Store3, notifier: Notifier,
                 trade_symbols, now_ms: Callable[[], int], prices: Callable[[], dict],
                 skip_before: Optional[int] = None, deadman: Optional[DeadMan] = None,
                 digest: Optional[Digest] = None, fills: Optional[FillProbe] = None):
        self.book = book
        self.service = service
        self.store = store
        self.notifier = notifier
        self.trade_symbols = list(trade_symbols)
        self.now_ms = now_ms
        self.prices = prices
        self.skip_before = skip_before  # minutes already processed before a restart
        self.agg = Aggregator(["5m"])
        self.steps = 0
        self.deadman = deadman
        self.digest = digest
        self.signal_timeouts = 0
        self.fills = fills  # order-book cost of each entry / exit (records only, never a fill)
        # extras (paperbot/extras.py): called after the 195's boundary commit as
        # post_boundary(boundary: int, submitted: list[tuple[str, Signal]], timed_out: bool)
        self.post_boundary = None
        self.post_boundary_errors = 0

    def process(self, steps) -> None:
        for ts, bars, funding in steps:
            if self.skip_before is None or ts >= self.skip_before:
                tb = {s: bars[s] for s in self.trade_symbols if s in bars}
                if tb:
                    snap = self.fills.before(self.book.engines) if self.fills else None
                    self.book.step(ts, tb, funding)
                    if snap is not None:
                        self._fill_costs(ts, snap, tb)
            for b in bars.values():
                for tf, b5 in self.agg.add(b):
                    self.service.add_5m(b5)
            boundary = ts + MIN
            if boundary % FIVE == 0:
                self._signals(boundary)
                sd_notify("WATCHDOG=1")  # a long catch-up after a restart is progress, not a hang
            self.steps += 1
        now = self.now_ms()
        self.store.put_state("heartbeat", now, {"steps": self.steps, "last_step": self.book.last_ts})
        self._health(now)
        self.store.commit()

    def _fill_costs(self, ts: int, snap: dict, bars: dict) -> None:
        try:
            rows = self.fills.after(ts, self.book.engines, snap, bars, self.now_ms())
            if rows:
                self.store.fill_costs(rows)
        except Exception as exc:  # noqa: BLE001  (a record only: the bot goes on)
            self.fills.errors += 1
            self.store.alert(self.now_ms(), WARN, f"fill cost record failed: {type(exc).__name__}: {exc}"[:300])

    def _health(self, now: int) -> None:
        last = self.book.last_ts
        ping = self.deadman.beat(now, last) if self.deadman else None
        if self.digest is not None:
            self.digest.flush(now)
        self.store.put_state("health", now, {
            "last_bar": last, "lag_ms": None if last is None else now - (last + MIN),
            "signal_timeouts": self.signal_timeouts,
            "pool_restarts": getattr(self.service, "pool_restarts", 0),
            "fill_cost_errors": None if self.fills is None else self.fills.errors,
            "deadman": None if self.deadman is None else {
                "last_ping": self.deadman.last_ping, "failures": self.deadman.failures, "sent": ping},
            "digest_pending": 0 if self.digest is None else len(self.digest.items)})

    def _signals(self, boundary: int) -> None:
        if not self.service.complete(boundary):
            self.store.alert(self.now_ms(), WARN, f"5m history incomplete at {boundary}; signals skipped")
            return
        due = self.service.due(boundary)
        submitted, timed_out = [], False
        for k, tf in enumerate(due):
            try:
                rows, subs, reports = self.service.compute(boundary, tf, self.now_ms, self.prices)
            except SignalTimeout as exc:
                self.signal_timeouts += 1
                timed_out = True
                text = f"{exc}; signals skipped at {boundary} for {', '.join(due[k:])}"
                self.store.alert(self.now_ms(), WARN, text)
                self.notifier.send(WARN, text)
                break
            self.store.log_signals(rows)
            for r in reports:
                for e in r.get("errors", []):
                    self.store.alert(self.now_ms(), WARN, f"signal error {tf} {r['symbol']}: {e}")
            for aid, sig in subs:
                if aid in self.book.engines and (self.skip_before is None or boundary >= self.skip_before):
                    self.book.submit(aid, sig)
                    submitted.append((aid, sig))
        if self.book.last_ts is not None:
            self.book.save(self.book.last_ts)
        if self.post_boundary is not None:
            try:
                self.post_boundary(boundary, submitted, timed_out)
            except Exception as exc:  # noqa: BLE001  the hook guards itself; this is the last fence for the 195
                self.store.conn.rollback()          # the 195's boundary was committed just before: only hook writes go
                self.post_boundary_errors += 1
                if self.post_boundary_errors >= 3:
                    self.post_boundary = None       # stop calling a hook that keeps failing
                text = f"[extra] boundary hook failed ({type(exc).__name__}: {exc})"[:300]
                self.store.alert(self.now_ms(), CRITICAL, text)
                self.store.commit()
                self.notifier.send(CRITICAL, text)


def single_runner_lock(db: str):
    """Hold an exclusive lock on ``<db>.lock`` for this process's life, so two runners never write the same
    paper3.db. Exits with a clear message when another runner holds it."""
    fh = open(db + ".lock", "a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        raise SystemExit(f"another live runner already holds {db}.lock; only one runner may write {db}")
    return fh


def cmd_run(args) -> int:
    from .sigservice import TRADE_TFS, SignalService, strategy_names
    notifier = _notifier()
    rest = _rest()
    syms = list(V3_SYMBOLS)
    over = {}
    if rest.api_key and rest.api_secret:
        rates = [float(rest.commission_rate(s)["takerCommissionRate"]) for s in syms]
        over["taker_fee"] = max(rates)
    settings = v3_settings(**over)
    brackets, src = load_brackets(rest, syms, args.brackets, args.allow_example_brackets)
    specs = rest.exchange_info(syms)
    store = Store3(args.db)
    lock = single_runner_lock(args.db)  # noqa: F841  (held until the process ends)
    digest = Digest(notifier)
    book = AccountBook(settings, brackets, store, notifier, specs, digest=digest)
    service = SignalService(syms, RECORD_ONLY, random_rates(), procs=args.procs)
    ext, make_of = None, hold_others          # hold_others: extras held at their saved state, the 195 normal
    try:
        from .extras import Extras
        ext = Extras.start(store, notifier, args.db, settings)
        make_of = ext.make_of
    except Exception as exc:  # noqa: BLE001  extras code broken: the 195 run, every extra is held
        text = f"[extra] extras code failed to load: {type(exc).__name__}: {exc}"[:300]
        store.alert(int(time.time() * 1000), CRITICAL, text)
        notifier.send(CRITICAL, text)
    restored = book.load(make_of=make_of)
    if restored:
        prev = store.get_state("run")
        before = float(prev[1].get("initial_equity", 1000.0)) if prev else 1000.0
        if before != settings.initial_equity:
            raise SystemExit(f"this database's accounts started with ${before:,.0f}, the rules now start "
                             f"them with ${settings.initial_equity:,.0f}. Start with a new --db file.")
    now = rest.server_time()
    if restored and book.last_ts is not None:
        resume = book.last_ts + MIN
        start = resume - resume % FIVE
    else:
        book.open_accounts(account_defs(strategy_names(service.lib), TRADE_TFS), now)
        resume = None
        start = now - now % FIVE
    hist_from = start - max(service.windows.values()) * FIVE - FIVE
    for s in service.symbols:
        service.bootstrap(s, fetch_5m(rest, s, hist_from, start))
        sd_notify("WATCHDOG=1")  # bootstrap takes minutes; tell systemd it is progressing
    rec = run_record(settings, brackets, src, sys.argv, signal_lock=sweepsig.verify())
    ch = changes(store.last_run(), rec)
    rec["changes"] = [c["key"] for c in ch]
    store.add_run(now, rec)
    text = change_text(ch)
    if text:
        level = WARN if any(c["trading"] for c in ch) else INFO
        store.alert(now, level, text)
        notifier.send(level, text)
    store.put_state("run", now, {"settings": settings.version, "taker_fee": settings.taker_fee,
                                 "initial_equity": settings.initial_equity, "commit": rec["commit"], "dirty": rec["dirty"],
                                 "brackets": src, "accounts": len(book.engines), "restored": restored,
                                 "resume_from": resume, "feed_start": start})
    store.commit()
    notifier.send(INFO, f"paper v3 {'resumed' if restored else 'started'}: {len(book.engines)} accounts, "
                        f"brackets: {src}, taker fee {settings.taker_fee:.4%}")
    feed = LiveFeed(rest, syms + list(RECORD_ONLY), start_time=start,
                    on_event=lambda lvl, txt: (store.alert(int(time.time() * 1000), lvl, txt),
                                               notifier.send(lvl, txt) if lvl != INFO else None))
    runner = Runner3(book, service, store, notifier, syms, lambda: int(time.time() * 1000) + feed.skew_ms,
                     lambda: book_prices(rest, syms), skip_before=resume,
                     deadman=DeadMan(os.environ.get("DEADMAN_URL")), digest=digest,
                     fills=FillProbe(lambda s: rest.depth(s, FILL_DEPTH), settings.slippage_frac, FILL_DEPTH))
    if ext is not None:
        try:
            ext.bind(runner)                  # new-strategy sources, code pins, post_boundary
        except Exception as exc:  # noqa: BLE001  extras stay without signals (their engines still step)
            text = f"[extra] extras could not start: {type(exc).__name__}: {exc}"[:300]
            store.alert(int(time.time() * 1000), CRITICAL, text)
            store.commit()
            notifier.send(CRITICAL, text)
    sd_notify("READY=1")
    try:
        while args.max_polls is None or args.max_polls > 0:
            sd_notify("WATCHDOG=1")
            try:
                runner.process(feed.poll())
            except RegionBlocked as exc:
                notifier.send(CRITICAL, f"Binance blocked this server: {exc}")
                raise
            except BinanceError as exc:
                store.alert(int(time.time() * 1000), WARN, f"data error, retrying: {exc}")
            if args.max_polls is not None:
                args.max_polls -= 1
            time.sleep(args.poll)
    finally:
        digest.flush(int(time.time() * 1000), force=True)
        service.close()
        store.close()
    return 0


def cmd_status(args) -> int:
    import sqlite3
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    st = conn.execute("SELECT ts, data FROM state WHERE k = 'accounts'").fetchone()
    hb = conn.execute("SELECT ts, data FROM state WHERE k = 'heartbeat'").fetchone()
    if st is None:
        print("no state yet")
        return 1
    data = json.loads(st[1])
    eng = data["engines"]
    bust = sum(1 for e in eng.values() if e.get("bust"))
    open_pos = sum(1 for e in eng.values() if e.get("position"))
    top = sorted(eng.items(), key=lambda kv: -kv[1]["wallet"])[:10]
    print(f"accounts {len(eng)}, open positions {open_pos}, bust {bust}, "
          f"heartbeat {hb[0] if hb else None}")
    for aid, e in top:
        print(f"  {aid:28s} wallet {e['wallet']:10.2f} trades {e['n_trades']}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--db", default="paper3.db")
    r.add_argument("--brackets")
    r.add_argument("--allow-example-brackets", action="store_true")
    r.add_argument("--procs", type=int, default=4)
    r.add_argument("--poll", type=float, default=5.0)
    r.add_argument("--max-polls", type=int)
    s = sub.add_parser("status")
    s.add_argument("--db", default="paper3.db")
    args = ap.parse_args(argv)
    return cmd_run(args) if args.cmd == "run" else cmd_status(args)


if __name__ == "__main__":
    sys.exit(main())

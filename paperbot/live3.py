"""Paper v3 live runner: the original accounts (config.V3_ACCOUNTS = 156: 36 strategies and 3 coin-flip
accounts on each of 15m, 30m, 1h and 4h) on live Binance data (docs/paper-v3-rules.md; 5m removed on
2026-10-04, docs/paper-v3-rules-change-1.md).

    python -m paperbot.live3 run --db paper3.db [--brackets FILE | --allow-example-brackets]
    python -m paperbot.live3 status --db paper3.db

Every poll: closed 1m bars (last and mark price, funding) for the six coins and
XRP -> every account's engine steps (entries, stops, profit locks, funding) ->
5m bars (the internal base bars, not a traded timeframe) -> at each 5m boundary
the signal service computes the traded timeframes that close there (none at a
boundary that is not a 15m close) and submits the signals; they fill on the next
step at the price read right after the computation.

Restart: the account states, the last processed minute and the pending signals
are in the store. On start the runner reloads them, rebuilds the 5m history
from Binance and replays the minutes it missed. Signals from those minutes are
logged as LATE and not traded (a live bot would have missed them too).

Extra accounts (copies and new strategies started from approved proposals,
paperbot/extras.py and docs/extra-accounts.md) run in the same book. The hooks
are ``post_boundary(boundary, submitted, timed_out)``, called after the originals'
work at a boundary has been committed (it guards itself, and a last fence here
rolls back its writes and keeps the originals running), and ``post_batch(now)`` at the
end of a poll (the extras' Telegram messages). Before a boundary's compute the
extras cost the originals nothing but their engines' step: they fetch no order book
(fill costs) and send no message. Only one runner may write a database at a
time (a lock on the database file itself).

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

from .accounts import ORIGINAL_KINDS, AccountBook, hold_others
from .aggregate import TF_MS, Aggregator
from .binance import BinanceError, BinanceREST, RegionBlocked
from .config import V3_RANDOM_SEEDS, V3_SYMBOLS, v3_settings
from .feed import LiveFeed
from .fillcost import LIMIT as FILL_DEPTH, FillProbe
from . import sweepsig
from .health import DeadMan, sd_notify
from .live import _notifier, _rest, load_brackets
from .notify import CRITICAL, INFO, WARN, Digest, Notifier, Router
from .runinfo import change_text, changes, run_record
from .sigservice import SignalTimeout
from .store3 import Store3
from .strengthwatch import StrengthWatch

MIN = 60_000
FIVE = TF_MS["5m"]
RECORD_ONLY = ("XRPUSDT",)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RANDOM_RATES = os.path.join(ROOT, "research", "paper_rules", "out", "summary.json")


def account_defs(strategies, tfs, seeds=V3_RANDOM_SEEDS) -> list[dict]:
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
        # extras (paperbot/extras.py): called after the originals' boundary commit as
        # post_boundary(boundary: int, submitted: list[tuple[str, Signal]], timed_out: bool)
        self.post_boundary = None
        self.post_boundary_errors = 0
        # extras: called as post_batch(now_ms) at the end of process(), after every boundary of the batch and the
        # commit (their Telegram messages wait until then, so they never delay an originals' compute of the batch)
        self.post_batch = None
        # watches only (never changes a signal or its size): a strategy signal of a cell with quality edges whose
        # strength score failed is sized "normal" by the rule; this writes an alert row and rings (hourly per cause).
        # Only under the quality_v1 rule (the old tier walk never reads the strength)
        rule = getattr(getattr(book, "s", None), "leverage_rule", None)
        self.strength = StrengthWatch(store, notifier, now_ms) if rule == "quality_v1" else None

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
        if self.post_batch is not None:
            try:
                self.post_batch(now)
            except Exception:  # noqa: BLE001  the extras' messages only; never stops the originals
                pass

    def _fill_costs(self, ts: int, snap: dict, bars: dict) -> None:
        """Order-book cost records of the step. Only the original accounts' events fetch a book (a REST call
        made before this boundary's signal compute); an extra account's event reuses a book fetched for them in
        this step, else it is recorded as 'skipped', so the extras never move the originals' ref_time / delay_ms."""
        try:
            now = self.now_ms()
            orig, others = {}, {}
            for aid, e in self.book.engines.items():
                kind = (self.book.meta.get(aid) or {}).get("kind")
                (orig if kind in ORIGINAL_KINDS else others)[aid] = e
            books: dict = {}
            rows = self.fills.after(ts, orig, snap, bars, now, books=books)
            if others:
                try:
                    rows = rows + self.fills.after(ts, others, snap, bars, now, books=books, fetch=False)
                except Exception:  # noqa: BLE001  (an extra's record only)
                    self.fills.errors += 1
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
            "strength_failures": None if self.strength is None else dict(self.strength.total),
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
        if submitted and self.strength is not None:
            try:
                self.strength.observe(boundary, submitted)
            except Exception:  # noqa: BLE001  an observer: never stops the originals
                pass
        if self.book.last_ts is not None:
            self.book.save(self.book.last_ts)
        if self.post_boundary is not None:
            try:
                self.post_boundary(boundary, submitted, timed_out)
            except Exception as exc:  # noqa: BLE001  the hook guards itself; this is the last fence for the originals
                self.store.conn.rollback()          # the originals' boundary was committed just before: only hook writes go
                self.post_boundary_errors += 1
                if self.post_boundary_errors >= 3:
                    self.post_boundary = None       # stop calling a hook that keeps failing
                text = f"[extra] boundary hook failed ({type(exc).__name__}: {exc})"[:300]
                self.store.alert(self.now_ms(), CRITICAL, text)
                self.store.commit()
                self.notifier.send(CRITICAL, text)


def start_extras(store: Store3, notifier: Notifier, db: str, settings):
    """(extras runtime or None, make_of for book.load). The extras code is imported inside a guard: if it is
    broken the originals run as always and every extra is held at its saved state (``hold_others``)."""
    try:
        from .extras import Extras
        ext = Extras.start(store, notifier, db, settings)
        return ext, ext.make_of
    except Exception as exc:  # noqa: BLE001  extras code broken: the originals run, every extra is held
        text = f"[extra] extras code failed to load: {type(exc).__name__}: {exc}"[:300]
        store.alert(int(time.time() * 1000), CRITICAL, text)
        notifier.send(CRITICAL, text)
        return None, hold_others


def bind_extras(ext, runner: "Runner3", store: Store3, notifier: Notifier) -> None:
    """Attach the extras to the runner (new-strategy sources, code pins, the hook); a failure leaves the extras
    without signals (their engines still step) and never stops the originals."""
    if ext is None:
        return
    try:
        ext.bind(runner)
    except Exception as exc:  # noqa: BLE001
        text = f"[extra] extras could not start: {type(exc).__name__}: {exc}"[:300]
        store.alert(int(time.time() * 1000), CRITICAL, text)
        store.commit()
        notifier.send(CRITICAL, text)
        # the extras' engines still step and hold their CRITICAL lines (liquidations, faults) in the outbox:
        # keep sending them at the end of each poll even though the extras never started
        flush = getattr(ext, "flush_outbox", None)
        if callable(flush) and runner.post_batch is None:
            def _flush_only(_now: int) -> None:
                try:
                    flush()
                except Exception:  # noqa: BLE001
                    pass
            runner.post_batch = _flush_only


def single_runner_lock(db: str):
    """Hold an exclusive ``flock`` on the database file itself for this process's life, so two runners never
    write the same paper3.db, however its path is spelled (a symlink, a hard link, a bind mount, a relative
    path: one inode, one lock). Exits with a clear message when another runner holds it.

    SQLite locks with POSIX (fcntl) locks, which are independent of flock. Closing any descriptor of the
    database file drops this process's POSIX locks on it, so the returned handle stays open until the process
    ends (cmd_run keeps it; the store is closed first)."""
    fh = os.fdopen(os.open(db, os.O_RDONLY | os.O_CREAT, 0o644), "rb")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()                      # this process exits right away
        raise SystemExit(f"another live runner already holds {os.path.realpath(db)}; only one runner may write it")
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
    # noisy lines (1m gaps, clock skew, repeated signal timeouts) go to the hourly digest (notify.Router)
    notifier = Router(notifier, digest)
    book = AccountBook(settings, brackets, store, notifier, specs, digest=digest)
    service = SignalService(syms, RECORD_ONLY, random_rates(), procs=args.procs)
    ext, make_of = start_extras(store, notifier, args.db, settings)
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
    bind_extras(ext, runner, store, notifier)
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

"""Paper live runner: the original accounts on live Binance data. Paper v4 (docs/paper-v4-rules.md; config.V4_GROUPS,
config.V4_ACCOUNTS = 331): the core group (the 36 locked strategies on 15m, 30m, 1h and 4h; 5m removed for them on
2026-10-04, docs/paper-v3-rules-change-1.md), the DeepSeek-200 definitions (39 x 4 + 5 x 3), the reel REEL_H1 on 5m
and the coin flips RANDOM_1..3 on 5m, 15m, 30m, 1h and 4h.

    python -m paperbot.live3 run --db paper3.db [--brackets FILE | --allow-example-brackets] [--no-extras] [--no-telegram]
    python -m paperbot.live3 status --db paper3.db

Every poll: closed 1m bars (last and mark price, funding) for the six coins and
XRP -> every account's engine steps (entries, stops, profit locks, funding) ->
5m bars (the internal base bars) -> at each 5m boundary, after the last 1m bar of
that 5m bar: first the 5m path (the reel and the 5m coin flips, in this process),
then the core timeframes that close there (the locked Pool map; their signals are
submitted at once), then the DeepSeek timeframes (a second Pool map with its own
timeout). Signals fill on the next step at the price read right after their
computation. Nothing the 5m path or the DeepSeek map does can stop the core
group's submits (each has its own fence and error class); the DeepSeek map never
delays them, the 5m path costs them its compute time (about 0.1-0.8 s, sigservice).

The v4 groups' alerts use sigservice's frozen texts (``DS_TIMEOUT_TEXT`` and the rest); their counters are
health "ds_timeouts", "ds_errors", "reel_errors" (never "signal_timeouts", the core group's). The DeepSeek job's
answer at every DeepSeek boundary is recorded in state "dsrun:<UTC day>" (``Runner3._ds_record``) for
paperbot/dscheck.py.

Start: the database must be this run's (``check_database``: a new file, or one whose
run version is config.V4_VERSION and whose original accounts are exactly
config.v4_account_defs); anything else is refused with a message. The DeepSeek and
reel pins are checked once (``SignalService.verify_groups``): a failing group starts
refused (its signals stop, one CRITICAL line) and every other group runs.

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
time (a lock on the database file itself). ``--no-extras`` (staging) starts no
extras runtime (any extra account is held); ``--no-telegram`` (staging) prints the
messages instead of sending them.

No orders are ever sent; the Binance key, if set, must be read-only.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import sys
import time
from typing import Callable, Optional

from .accounts import GROUP_OF_KIND, ORIGINAL_KINDS, AccountBook, hold_others
from .aggregate import TF_MS, Aggregator
from .binance import BinanceError, BinanceREST, RegionBlocked
from .config import (DS200_TFS, DS_WINDOW_5M, FIVE_M_MAX_DELAY_MS, REEL_WINDOW_5M, V3_RANDOM_SEEDS, V3_SYMBOLS,
                     V4_FLIP5M, V4_GROUPS, V4_VERSION, v3_settings, v4_account_defs)
from .feed import LiveFeed
from .fillcost import LIMIT as FILL_DEPTH, FillProbe
from . import sweepsig
from .health import DeadMan, sd_notify
from .live import _notifier, _rest, load_brackets
from .notify import CRITICAL, INFO, WARN, ConsoleNotifier, Digest, Notifier, Router
from .runinfo import change_text, changes, run_record
from .sigservice import (DS_ERROR_TEXT, DS_FAILED_TEXT, DS_TIMEOUT_TEXT, REEL_ERROR_TEXT, REEL_FAILED_TEXT,
                         REFUSED_TEXT, DsTimeout, SignalTimeout, one_line)
from .store3 import Store3
from .strengthwatch import StrengthWatch

MIN = 60_000
FIVE = TF_MS["5m"]
DAY = 86_400_000
# paper3.db state key of the DeepSeek job's record of a UTC day (``Runner3._ds_record``; read by paperbot/dscheck.py):
# "dsrun:<YYYY-MM-DD>", the day of the bar that closes at the boundary (bar_close in (day 00:00, next day 00:00]).
DS_RUN_KEY = "dsrun:"
RECORD_ONLY = ("XRPUSDT",)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RANDOM_RATES = os.path.join(ROOT, "research", "paper_rules", "out", "summary.json")


def account_defs(strategies, tfs, seeds=V3_RANDOM_SEEDS) -> list[dict]:
    """The v3 account set (the core group and its coin flips on ``tfs``); the v4 runner opens ``v4_defs``."""
    defs = [{"strategy": s, "timeframe": tf, "kind": "strategy"} for tf in tfs for s in strategies]
    defs += [{"strategy": f"RANDOM_{k}", "timeframe": tf, "kind": "random"} for tf in tfs for k in seeds]
    return defs


def v4_defs(core_names) -> list[dict]:
    """Every original account of the paper v4 run (config.v4_account_defs: strategy, timeframe, kind and data
    {group, family, exits}); the first 156 are ``account_defs(core_names, V3_TRADE_TFS)`` in the same order."""
    return v4_account_defs(core_names)


def service_options() -> dict:
    """The SignalService switches of the paper v4 run: the DeepSeek timeframes, the 5m path (reel + 5m coin flips at
    config.V4_FLIP5M) and its max delay (owners' D16)."""
    return {"ds_tfs": DS200_TFS, "five_m": True, "flip5m": dict(V4_FLIP5M), "max_delay_ms_5m": FIVE_M_MAX_DELAY_MS}


def _data(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        d = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _shape(defs) -> dict:
    return {d.get("account_id") or f"{d['strategy']}@{d['timeframe']}":
            (d["kind"], _data(d.get("data")).get("group"), _data(d.get("data")).get("exits")) for d in defs}


def check_database(store: Store3, want: list[dict], version: str) -> None:
    """Refuse (SystemExit with the reason) a database that is not this run's: its last run's rule version is not
    ``version``, an original account was created under another version, or its original accounts (id, kind, group,
    exit rule) are not exactly ``want``. A new database (no original account, no run) passes."""
    prev = store.get_state("run")
    if prev is not None and prev[1].get("settings") != version:
        raise SystemExit(f"this database was run under {prev[1].get('settings')!r}, the runner is {version!r}: "
                         "start with a new --db file (the reset script archives the old one)")
    rows = [a for a in store.accounts() if a.get("kind") in ORIGINAL_KINDS]
    if not rows:
        return
    other = sorted({a.get("settings_version") for a in rows} - {version}, key=str)
    if other:
        raise SystemExit(f"this database holds original accounts of {other}, the runner is {version!r}: "
                         "start with a new --db file")
    have, need = _shape(rows), _shape(want)
    if have != need:
        missing = sorted(set(need) - set(have))
        extra = sorted(set(have) - set(need))
        diff = sorted(a for a in set(have) & set(need) if have[a] != need[a])
        raise SystemExit(f"this database's original accounts differ from the run's {len(need)}: "
                         f"{len(missing)} missing {missing[:5]}, {len(extra)} not in the run {extra[:5]}, "
                         f"{len(diff)} with another kind / group / exit rule {diff[:5]}. Start with a new --db file.")


def check_book(book: AccountBook, want: list[dict]) -> None:
    """After the accounts are opened or loaded: the book's original accounts are exactly ``want``."""
    have = {aid for aid, m in book.meta.items() if (m or {}).get("kind") in ORIGINAL_KINDS}
    need = set(_shape(want))
    if have != need:
        raise SystemExit(f"the book holds {len(have)} original accounts, the run has {len(need)} "
                         f"(missing {sorted(need - have)[:5]}, extra {sorted(have - need)[:5]})")


def check_history(service) -> None:
    """The 5m history the service keeps covers every window that reads it: the DeepSeek windows, the reel window and
    the new-strategy (extras) windows (newlab_live.NEWLAB_WINDOW_5M; skipped when that code cannot be imported)."""
    need = [DS_WINDOW_5M[tf] for tf in getattr(service, "ds_tfs", ())]
    if getattr(service, "five_m", False):
        need.append(REEL_WINDOW_5M)
    try:
        from .newlab_live import NEWLAB_WINDOW_5M
        need += list(NEWLAB_WINDOW_5M.values())
    except Exception:  # noqa: BLE001  the extras' own check (newlab_live.register) still refuses a too-long window
        pass
    lens = [h.maxlen for h in service.hist.values()]
    have = min(lens) if lens else 0
    if need and (have is None or have < max(need)):
        raise SystemExit(f"signal history keeps {have} 5m bars, the windows need {max(need)}")


def group_split(book: AccountBook) -> dict:
    """{group: original accounts} of the book in config.V4_GROUPS order, then "extra" for every other account."""
    out = {g: 0 for g in V4_GROUPS}
    for m in book.meta.values():
        g = GROUP_OF_KIND.get((m or {}).get("kind"), "extra")
        g = g if g in out else "extra"
        out[g] = out.get(g, 0) + 1
    return {g: n for g, n in out.items() if n or g in V4_GROUPS}


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
        self.ds_timeouts = 0        # DeepSeek map timeouts (never counted in signal_timeouts, the core group's)
        self.ds_errors = 0          # DeepSeek error lines (one coin's job) and DeepSeek path failures
        self.reel_errors = 0        # 5m path error lines (one coin's reel / flip computation) and 5m path failures
        self.group_errors = 0       # failures caught by the v4 groups' fences (5m path, DeepSeek)
        self.ds_last: dict = {}     # DeepSeek timeframe -> last boundary its job answered
        self.reel_last = None       # last 5m boundary the 5m path ran
        self._failed_sent: set = set()      # groups whose path failure was sent to Telegram (the first of a run)
        self._dsrun = None          # (state key, record) of the DeepSeek job's record of the current day
        self.ds_record_errors = 0
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
            "ds_timeouts": self.ds_timeouts, "ds_errors": self.ds_errors, "reel_errors": self.reel_errors,
            "group_errors": self.group_errors, "ds_last": dict(self.ds_last), "reel_last": self.reel_last,
            "ds_record_errors": self.ds_record_errors,
            "groups_refused": dict(getattr(self.service, "refused", None) or {}),
            "pool_restarts": getattr(self.service, "pool_restarts", 0),
            "fill_cost_errors": None if self.fills is None else self.fills.errors,
            "strength_failures": None if self.strength is None else dict(self.strength.total),
            "deadman": None if self.deadman is None else {
                "last_ping": self.deadman.last_ping, "failures": self.deadman.failures, "sent": ping},
            "digest_pending": 0 if self.digest is None else len(self.digest.items)})

    def _signals(self, boundary: int) -> None:
        if not self.service.complete(boundary):
            self.store.alert(self.now_ms(), WARN, f"5m history incomplete at {boundary}; signals skipped")
            due_ds = getattr(self.service, "due_ds", None)
            for tf in (due_ds(boundary) if due_ds is not None else []):
                self._ds_record(boundary, tf, "incomplete")
            return
        due = self.service.due(boundary)
        submitted, timed_out = [], False
        self._five_m(boundary, submitted)          # paper v4: the reel and the 5m coin flips first (in-process)
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
        # paper v4: after every core submit. A DeepSeek timeout is counted and alerted there but is NOT the extras'
        # ``timed_out`` (that is the core map's SignalTimeout only): DeepSeek never changes another group's trading (D8)
        self._deepseek(boundary, submitted)
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

    # ------------------------------------------------------------ paper v4 groups (fenced: never stop the core)
    def _take(self, boundary: int, tf: str, rows, subs, reports, submitted: list, label: str) -> None:
        """Log a v4 group's rows and errors (sigservice's frozen DS_ERROR_TEXT / REEL_ERROR_TEXT) and submit its
        signals (as the core loop does for its own)."""
        self.store.log_signals(rows)
        text = DS_ERROR_TEXT if label == "ds200" else REEL_ERROR_TEXT
        for r in reports:
            for e in r.get("errors", []):
                if label == "ds200":
                    self.ds_errors += 1
                else:
                    self.reel_errors += 1
                self.store.alert(self.now_ms(), WARN, text.format(tf=tf, symbol=r.get("symbol"), error=one_line(e)))
        for aid, sig in subs:
            if aid in self.book.engines and (self.skip_before is None or boundary >= self.skip_before):
                self.book.submit(aid, sig)
                submitted.append((aid, sig))

    def _refusals(self) -> None:
        pop = getattr(self.service, "pop_refusals", None)
        for group, why in (pop() if pop is not None else []):
            text = REFUSED_TEXT.format(group=group, why=one_line(why))
            self.store.alert(self.now_ms(), CRITICAL, text)
            self.notifier.send(CRITICAL, text)

    def _group_failed(self, group: str, boundary: int, exc: Exception) -> None:
        """A v4 group's path failed at ``boundary`` (caught by its fence): one WARN alert (sigservice's frozen
        DS_FAILED_TEXT / REEL_FAILED_TEXT); the first of each group in a run also goes to Telegram."""
        self.group_errors += 1
        if group == "ds200":
            self.ds_errors += 1
        else:
            self.reel_errors += 1
        text = (DS_FAILED_TEXT if group == "ds200" else REEL_FAILED_TEXT).format(
            boundary=boundary, error=one_line(f"{type(exc).__name__}: {exc}", 200))
        self.store.alert(self.now_ms(), WARN, text)
        if group not in self._failed_sent:
            self._failed_sent.add(group)
            try:
                self.notifier.send(WARN, text)
            except Exception:  # noqa: BLE001  the alerts table has it
                pass

    def _ds_record(self, boundary: int, tf: str, status: str, reports=()) -> None:
        """The DeepSeek job's record of ``boundary`` for ``tf`` in paper3.db state ``DS_RUN_KEY + <UTC day>``
        (paperbot/dscheck.py reads it: an absent signal_log row is "no signal" only on a coin the job answered for).
        {"v": 1, "day": "YYYY-MM-DD", "tfs": {tf: {"<boundary>": {"s": status, "ok": [symbols], "no": {symbol:
        why}, "err": {symbol: errors}}}}}; status "ran" (the job answered: "ok" = the coins it computed, every fired
        definition of them is a signal_log row, whatever its status; "no" = the coins it did not compute, with the
        reason; "err", only when there is one = the problems a computed coin reported, e.g. "F14_SMT: no BTC bars":
        that definition may be missing on that coin), "timeout" (the
        DeepSeek map timed out at this boundary, DS_TIMEOUT_TEXT), "refused" (the group's code is refused), "failed"
        (the DeepSeek path failed, DS_FAILED_TEXT), "incomplete" (the 5m history was incomplete: no signal of any group
        at this boundary). A boundary missing from the record was not reached by the runner (stopped, or the extras'
        catch-up). A record only: a failure is counted (health "ds_record_errors") and never stops anything."""
        try:
            day = time.strftime("%Y-%m-%d", time.gmtime((int(boundary) - 1) // 1000))
            key = DS_RUN_KEY + day
            if self._dsrun is None or self._dsrun[0] != key:
                prev = self.store.get_state(key)
                data = prev[1] if prev is not None and isinstance(prev[1], dict) else {}
                if data.get("v") != 1 or not isinstance(data.get("tfs"), dict):
                    data = {"v": 1, "day": day, "tfs": {}}
                self._dsrun = (key, data)
            data = self._dsrun[1]
            entry: dict = {"s": status}
            if status == "ran":
                coins = set(self.trade_symbols)
                entry["ok"] = sorted(r["symbol"] for r in reports if r.get("ready") and r.get("symbol") in coins)
                entry["no"] = {r["symbol"]: one_line(r.get("why") or "; ".join(r.get("errors") or []) or "not ready",
                                                     160)
                               for r in reports if not r.get("ready") and r.get("symbol") in coins}
                err = {r["symbol"]: one_line("; ".join(str(e) for e in r["errors"]), 300)
                       for r in reports if r.get("ready") and r.get("symbol") in coins and r.get("errors")}
                if err:
                    entry["err"] = err
            data["tfs"].setdefault(tf, {})[str(int(boundary))] = entry
            self.store.put_state(key, self.now_ms(), data)
        except Exception:  # noqa: BLE001  a record only
            self.ds_record_errors += 1

    def _five_m(self, boundary: int, submitted: list) -> None:
        """The 5m path (``SignalService.compute_5m``) at a 5m boundary; a service without one (v3, tests) skips it."""
        fn = getattr(self.service, "compute_5m", None)
        if fn is None or not self.service.due_5m(boundary):
            return
        try:
            rows, subs, reports = fn(boundary, self.now_ms, self.prices)
            self._take(boundary, "5m", rows, subs, reports, submitted, "reel")
            self.reel_last = boundary
        except Exception as exc:  # noqa: BLE001  the core group's compute follows regardless
            self._group_failed("reel", boundary, exc)
        self._refusals()

    def _deepseek(self, boundary: int, submitted: list) -> bool:
        """The DeepSeek timeframes due at ``boundary`` (``SignalService.compute_ds``), after every core submit.
        Returns True when the DeepSeek map timed out (the rest of its timeframes at this boundary are skipped)."""
        fn = getattr(self.service, "compute_ds", None)
        if fn is None:
            return False
        due = self.service.due_ds(boundary)
        out = False
        for k, tf in enumerate(due):
            try:
                rows, subs, reports = fn(boundary, tf, self.now_ms, self.prices)
                self._take(boundary, tf, rows, subs, reports, submitted, "ds200")
            except DsTimeout:
                self.ds_timeouts += 1
                out = True
                text = DS_TIMEOUT_TEXT.format(secs=f"{float(getattr(self.service, 'ds_timeout_s', 0)):.0f}",
                                              boundary=boundary, tfs=", ".join(due[k:]))
                self.store.alert(self.now_ms(), WARN, text)
                for t in due[k:]:
                    self._ds_record(boundary, t, "timeout")
                self.notifier.send(WARN, text)
                break
            except Exception as exc:  # noqa: BLE001
                self._group_failed("ds200", boundary, exc)
                for t in due[k:]:
                    self._ds_record(boundary, t, "failed")
                break
            if "ds200" in (getattr(self.service, "refused", None) or {}):
                self._ds_record(boundary, tf, "refused")
            else:
                self._ds_record(boundary, tf, "ran", reports)
                self.ds_last[tf] = boundary
        self._refusals()
        return out


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


class StopFlag:
    """A stop request set from a signal handler. No lock is taken in the handler (``threading.Event.set`` takes one,
    and a SIGTERM landing while the main thread holds it inside ``Event.wait`` would deadlock the process)."""

    def __init__(self) -> None:
        self._set = False

    def set(self) -> None:
        self._set = True

    def is_set(self) -> bool:
        return self._set

    def wait(self, timeout: float, slice_s: float = 0.25) -> bool:
        """Sleep up to ``timeout`` seconds in short slices; return early (True) once set."""
        end = time.monotonic() + max(0.0, float(timeout))
        while not self._set:
            left = end - time.monotonic()
            if left <= 0:
                break
            time.sleep(min(slice_s, left))
        return self._set


def stop_on_sigterm() -> tuple[StopFlag, Callable[[], None]]:
    """(stop flag, restore). SIGTERM (systemctl stop / restart, install.sh, a reboot) sets the flag: cmd_run ends
    the poll it is in (a batch of minutes is never cut in the middle: store.close commits, and a half-processed batch
    must not be committed) and leaves through its ``finally``, so the hourly digest's pending lines (busts,
    drawdowns, gaps) are sent. Without this the default action killed the process and those lines were lost. A
    batch longer than the unit's TimeoutStopSec ends in systemd's SIGKILL: the crash case a restart already
    handles. A signal worker forked after this keeps SIGTERM's default action (it ends at once), because
    ``Pool.terminate`` after a signal timeout relies on it. systemd must therefore signal the MAIN process only
    (KillMode=mixed in deploy/paperbot-live3.service): a worker killed by SIGTERM while holding the pool's queue
    lock would hang ``Pool.close/join`` in the ``finally``. The main process closes the pool; anything left after
    it exits gets SIGKILL."""
    stop = StopFlag()
    pid = os.getpid()

    def on_term(signum, frame):  # noqa: ARG001
        if os.getpid() != pid:                    # a forked worker inherited this handler: keep the default
            signal.signal(signum, signal.SIG_DFL)  # action (Pool.terminate after a signal timeout must kill it)
            os.kill(os.getpid(), signum)
            return
        stop.set()

    try:
        prev = signal.signal(signal.SIGTERM, on_term)
    except ValueError:                            # not the main thread (tests): nothing to install
        return stop, lambda: None
    return stop, lambda: signal.signal(signal.SIGTERM, prev)


def cmd_run(args) -> int:
    from .sigservice import SignalService, strategy_names
    notifier = ConsoleNotifier() if getattr(args, "no_telegram", False) else _notifier()
    rest = _rest()
    syms = list(V3_SYMBOLS)
    over = {}
    if rest.api_key and rest.api_secret:
        rates = [float(rest.commission_rate(s)["takerCommissionRate"]) for s in syms]
        over["taker_fee"] = max(rates)
    settings = v3_settings(**over)
    if settings.version != V4_VERSION:
        raise SystemExit(f"the rules say {settings.version!r}, this runner runs {V4_VERSION!r}")
    brackets, src = load_brackets(rest, syms, args.brackets, args.allow_example_brackets)
    specs = rest.exchange_info(syms)
    store = Store3(args.db)
    lock = single_runner_lock(args.db)  # noqa: F841  (held until the process ends)
    digest = Digest(notifier)
    # noisy lines (1m gaps, clock skew, repeated signal timeouts) go to the hourly digest (notify.Router)
    notifier = Router(notifier, digest)
    book = AccountBook(settings, brackets, store, notifier, specs, digest=digest)
    service = SignalService(syms, RECORD_ONLY, random_rates(), procs=args.procs, **service_options())
    check_history(service)
    want = v4_defs(strategy_names(service.lib))
    check_database(store, want, settings.version)       # before anything is loaded or written
    group_locks = service.verify_groups()               # DeepSeek / reel pins: a failing group starts refused
    if getattr(args, "no_extras", False):
        ext, make_of = None, hold_others
    else:
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
        book.open_accounts(want, now)
        resume = None
        start = now - now % FIVE
    check_book(book, want)
    hist_from = start - service.keep * FIVE - FIVE
    for s in service.symbols:
        service.bootstrap(s, fetch_5m(rest, s, hist_from, start))
        sd_notify("WATCHDOG=1")  # bootstrap takes minutes; tell systemd it is progressing
    rec = run_record(settings, brackets, src, sys.argv, signal_lock=sweepsig.verify(), group_locks=group_locks)
    ch = changes(store.last_run(), rec)
    rec["changes"] = [c["key"] for c in ch]
    store.add_run(now, rec)
    text = change_text(ch)
    if text:
        level = WARN if any(c["trading"] for c in ch) else INFO
        store.alert(now, level, text)
        notifier.send(level, text)
    split = group_split(book)
    store.put_state("run", now, {"settings": settings.version, "taker_fee": settings.taker_fee,
                                 "initial_equity": settings.initial_equity, "commit": rec["commit"], "dirty": rec["dirty"],
                                 "brackets": src, "accounts": len(book.engines), "restored": restored,
                                 "resume_from": resume, "feed_start": start, "groups": split,
                                 "groups_refused": dict(service.refused),
                                 "extras": "off (--no-extras)" if getattr(args, "no_extras", False) else "on"})
    store.commit()
    for group, why in service.pop_refusals():           # one CRITICAL line per refused group
        text = REFUSED_TEXT.format(group=group, why=one_line(why))
        store.alert(now, CRITICAL, text)
        notifier.send(CRITICAL, text)
    store.commit()
    run_name = settings.version.replace("paper-v", "paper v")
    notifier.send(INFO, f"{run_name} {'resumed' if restored else 'started'}: {len(book.engines)} accounts "
                        f"({', '.join(f'{g} {n}' for g, n in split.items())}), "
                        f"brackets: {src}, taker fee {settings.taker_fee:.4%}")
    feed = LiveFeed(rest, syms + list(RECORD_ONLY), start_time=start,
                    on_event=lambda lvl, txt: (store.alert(int(time.time() * 1000), lvl, txt),
                                               notifier.send(lvl, txt) if lvl != INFO else None))
    runner = Runner3(book, service, store, notifier, syms, lambda: int(time.time() * 1000) + feed.skew_ms,
                     lambda: book_prices(rest, syms), skip_before=resume,
                     deadman=DeadMan(os.environ.get("DEADMAN_URL")), digest=digest,
                     fills=FillProbe(lambda s: rest.depth(s, FILL_DEPTH), settings.slippage_frac, FILL_DEPTH))
    bind_extras(ext, runner, store, notifier)
    stop, restore = stop_on_sigterm()
    sd_notify("READY=1")
    try:
        while (args.max_polls is None or args.max_polls > 0) and not stop.is_set():
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
            stop.wait(args.poll)                  # returns at once on SIGTERM
    finally:
        restore()
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
    r.add_argument("--no-extras", action="store_true",
                   help="staging: start no extras runtime (any extra account is held at its saved state)")
    r.add_argument("--no-telegram", action="store_true",
                   help="staging: print the messages instead of sending them to Telegram")
    s = sub.add_parser("status")
    s.add_argument("--db", default="paper3.db")
    args = ap.parse_args(argv)
    return cmd_run(args) if args.cmd == "run" else cmd_status(args)


if __name__ == "__main__":
    sys.exit(main())

"""Run the paper engine on live Binance data.

    python -m paperbot.live check
        Connection test for the server: clock, symbol specs, one kline and
        funding row per symbol, and (with an API key) leverage brackets.

    python -m paperbot.live run --ledger paper.db [--brackets brackets.json]
                                [--max-steps N] [--poll 5]
        Poll closed 1m bars, step the engine, feed strategies, submit their
        signals for the next bar.

Order within one 1m bar t:
    engine.step(bars at t)       fills signals from bar t-1, exits, funding
    strategies see bar t closed  (and any higher-timeframe bar closing at t)
    engine.submit(signals)       they fill at bar t+1's open
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from dataclasses import replace
from typing import Optional, Sequence

from .aggregate import Aggregator
from .binance import BinanceError, BinanceREST, RegionBlocked
from .config import Settings
from .context import HTF, entry_context
from .engine import PaperEngine
from .feed import LiveFeed
from .ledger import BarStore, Ledger
from .margin import Brackets
from .notify import CRITICAL, INFO, WARN, ConsoleNotifier, Notifier, TelegramNotifier
from .policy import RecommendedPolicy, RecommendedSettings, RiskGuards
from .strategy import Strategy, StrategyRunner


class LiveRunner:
    """Drives one or more books (engines) with the same bars and signals."""

    def __init__(self, feed: LiveFeed, engine, strategies: Sequence[Strategy],
                 notifier: Notifier, bar_store: Optional[BarStore] = None):
        self.feed = feed
        self.engines: list[PaperEngine] = list(engine) if isinstance(engine, (list, tuple)) else [engine]
        self.engine = self.engines[0]
        self.runner = StrategyRunner(strategies)
        self.styles = {s.strategy_id: getattr(s, "style", "") for s in strategies}
        tfs = {s.timeframe for s in strategies} | {"1m"}
        # Higher timeframes are built too, for the entry context (regime, HTF box).
        tfs |= {HTF[tf] for tf in tfs if HTF.get(tf)}
        self.agg = Aggregator(tfs)
        self.notifier = notifier
        self.bar_store = bar_store
        self.steps = 0

    def _with_context(self, sig):
        """Attach the chart situation at the signal (confirmed bars only)."""
        hist = self.runner.history
        tf_bars = [b for b in hist.get((sig.symbol, sig.timeframe), []) if not b.partial]
        htf = HTF.get(sig.timeframe)
        htf_bars = [b for b in hist.get((sig.symbol, htf), [])
                    if not b.partial and b.close_time <= sig.ts] if htf else []
        ctx = entry_context(sig.timeframe, tf_bars, htf_bars)
        meta = dict(sig.meta)
        meta.setdefault("ctx", ctx)
        meta.setdefault("style", self.styles.get(sig.strategy_id, ""))
        return replace(sig, meta=meta)

    def process(self, steps) -> None:
        for _t, bars, funding in steps:
            for eng in self.engines:
                eng.step(bars, funding or None)
            if self.bar_store is not None and bars:
                self.bar_store.add(bars.values())
            for sym in sorted(bars):
                for tf, bar in self.agg.add(bars[sym]):
                    if bar.partial:
                        self.notifier.send(WARN, f"{sym} {tf} bar at {bar.open_time} "
                                                 f"is incomplete; no signals from it")
                        self.runner.history.setdefault((sym, tf), []).append(bar)
                        continue
                    for sig in self.runner.on_closed_bar(tf, bar):
                        sig = self._with_context(sig)
                        for eng in self.engines:
                            eng.submit(sig)
            self.steps += 1

    def run(self, poll_seconds: float = 5.0, max_steps: Optional[int] = None) -> None:
        while max_steps is None or self.steps < max_steps:
            try:
                self.process(self.feed.poll())
            except RegionBlocked as exc:
                self.notifier.send(CRITICAL, f"Binance blocked this server: {exc}")
                raise
            except BinanceError as exc:
                self.notifier.send(WARN, f"data error, retrying: {exc}")
            time.sleep(poll_seconds)


def _notifier() -> Notifier:
    if os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_CRITICAL"):
        return TelegramNotifier()
    return ConsoleNotifier()


def _rest() -> BinanceREST:
    return BinanceREST(api_key=os.environ.get("BINANCE_API_KEY"),
                       api_secret=os.environ.get("BINANCE_API_SECRET"))


def load_brackets(rest: BinanceREST, symbols, path: Optional[str],
                  allow_example: bool) -> tuple[dict[str, Brackets], str]:
    if path:
        with open(path) as fh:
            payload = json.load(fh)
        src = f"file {path}"
    elif rest.api_key and rest.api_secret:
        payload = rest.leverage_brackets()
        src = "Binance leverageBracket (live)"
    elif allow_example:
        return {s: Brackets.example() for s in symbols}, "EXAMPLE TABLE (not exchange data)"
    else:
        raise SystemExit("No leverage brackets: pass --brackets FILE, set "
                         "BINANCE_API_KEY/BINANCE_API_SECRET (read-only key), or "
                         "--allow-example-brackets for a dry run.")
    by_sym = {p["symbol"]: Brackets.from_binance(p) for p in payload}
    missing = set(symbols) - by_sym.keys()
    if missing:
        raise SystemExit(f"brackets missing for {sorted(missing)}")
    return {s: by_sym[s] for s in symbols}, src


def cmd_check(settings: Settings) -> int:
    rest = _rest()
    ok = True

    def line(status: str, text: str) -> None:
        print(f"[{status}] {text}")

    try:
        st = rest.server_time()
        skew = st - int(time.time() * 1000)
        line("OK" if abs(skew) < 1000 else "WARN", f"server time, local clock skew {skew} ms")
        specs = rest.exchange_info(settings.symbols)
        for s, sp in specs.items():
            line("OK" if sp["status"] == "TRADING" else "WARN",
                 f"{s} {sp['contract_type']} status={sp['status']} step={sp['qty_step']} "
                 f"tick={sp['tick_size']} min_notional={sp['min_notional']}")
        for s in settings.symbols:
            k = rest.klines(s, "1m", limit=2)
            m = rest.mark_klines(s, "1m", limit=2)
            f = rest.funding_rates(s, limit=1)
            line("OK", f"{s} last close {k[-1][4]} mark close {m[-1][4]} "
                       f"funding {f[-1]['fundingRate'] if f else 'n/a'}")
    except RegionBlocked as exc:
        line("FAIL", str(exc))
        line("HINT", "Pick a server region Binance serves (not US); see docs/paperbot.md")
        return 2
    except BinanceError as exc:
        line("FAIL", str(exc))
        return 1
    if rest.api_key:
        try:
            br = rest.leverage_brackets()
            got = {p["symbol"]: p["brackets"][0] for p in br if p["symbol"] in settings.symbols}
            for s in settings.symbols:
                b0 = got.get(s)
                line("OK" if b0 else "FAIL",
                     f"{s} bracket 1: max {b0['initialLeverage']}x up to {b0['notionalCap']} "
                     f"MMR {b0['maintMarginRatio']}" if b0 else f"{s} no bracket")
                ok &= bool(b0) and b0["initialLeverage"] >= settings.max_leverage
        except BinanceError as exc:
            line("FAIL", f"leverage brackets: {exc}")
            ok = False
    else:
        line("SKIP", "leverage brackets need BINANCE_API_KEY/SECRET (read-only)")
    return 0 if ok else 1


def cmd_run(settings: Settings, args) -> int:
    notifier = _notifier()
    rest = _rest()
    brackets, src = load_brackets(rest, settings.symbols, args.brackets,
                                  args.allow_example_brackets)
    specs = rest.exchange_info(settings.symbols)
    run_id = args.run_id or uuid.uuid4().hex[:12]
    engines, ledgers = make_books(settings, brackets, specs, notifier, args.ledger,
                                  run_id, args.equity_every, args.books.split(","))
    feed = LiveFeed(rest, settings.symbols, on_event=notifier.send)
    strategies: list[Strategy] = []  # strategies plug in here once validated
    notifier.send(INFO, f"paper run {run_id} started; books: {args.books}; "
                        f"brackets: {src}; strategies: {len(strategies)}")
    store = BarStore(args.ledger)
    runner = LiveRunner(feed, engines, strategies, notifier, bar_store=store)
    try:
        runner.run(poll_seconds=args.poll, max_steps=args.max_steps)
    finally:
        store.close()
        for led in ledgers:
            led.close()
        print(json.dumps([e.summary() for e in engines], indent=2))
    return 0


def make_books(settings: Settings, brackets, specs, notifier, ledger_path: Optional[str],
               run_id: str, equity_every: int = 1, books=("owner", "recommended"),
               rec: RecommendedSettings = RecommendedSettings()):
    """Build the requested books. Each gets its own ledger run id
    (``<run_id>-<book>``) in the same database."""
    engines, ledgers = [], []
    for book in books:
        kw = {}
        if book == "recommended":
            kw = {"policy": RecommendedPolicy(settings, rec), "guards": RiskGuards(rec)}
        elif book != "owner":
            raise SystemExit(f"unknown book {book!r}")
        cb = {}
        if ledger_path:
            led = Ledger(ledger_path, f"{run_id}-{book}",
                         settings.version if book == "owner" else rec.version,
                         equity_every=equity_every)
            ledgers.append(led)
            cb = {"on_trade": led.trade, "on_outcome": led.outcome, "on_equity": led.equity}
        engines.append(PaperEngine(settings, brackets, notifier=notifier, symbol_specs=specs,
                                   book=book, **kw, **cb))
    return engines, ledgers


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    r = sub.add_parser("run")
    r.add_argument("--ledger", default="paper.db")
    r.add_argument("--brackets")
    r.add_argument("--allow-example-brackets", action="store_true")
    r.add_argument("--run-id")
    r.add_argument("--poll", type=float, default=5.0)
    r.add_argument("--max-steps", type=int)
    r.add_argument("--equity-every", type=int, default=1)
    r.add_argument("--books", default="owner,recommended",
                   help="comma list of books to run side by side")
    args = ap.parse_args(argv)
    settings = Settings()
    if args.cmd == "check":
        return cmd_check(settings)
    return cmd_run(settings, args)


if __name__ == "__main__":
    sys.exit(main())

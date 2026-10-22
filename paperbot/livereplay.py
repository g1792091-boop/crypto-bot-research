"""The combined paper bot replayed over one day, for the live daily check (paperbot/livecheck.py, "대조").

    from paperbot.livereplay import BinanceMarket, replay_day
    res = replay_day(cfg_raw, BinanceMarket(), w0, w1, live_bars=..., seed=...)

It runs paperbot/combo.py itself (``ComboRunner`` and ``ComboEngine``, never a copy of their rules) minute by minute
over [w0, w1) in a temporary folder, as the live process ran it:
- the 1m bars it steps on are written one minute at a time into a temporary paper3.db (``Store3.live_bars``), which
  the runner reads like the real one; by default the very bars the live paper bot stepped on (the rule bot's
  ``live_bars`` rows in /var/lib/paperbot/paper3.db, with the time each minute was handled: the simulated clock
  follows it, so a minute the live process got late is late here too); without them, Binance 1m klines and mark-price
  klines, each minute handled 5 seconds after its close;
- everything the live bot asks Binance for (5m history of the custom signals, the research rules' 1m / 1h / 4h
  klines, funding, 5-minute open interest) is fetched once for the whole window and its warm-up (about 125 days of 5m
  bars, 7 days of 1m bars, 62 days of 1h and 167 days of 4h bars) and served bar by bar, closed bars only, through the
  same callbacks the live bot passes to the runner; the reference price of a signal is the open of the minute after
  its bar (the live bot reads the order book a few seconds into that minute);
- the accounts start from the live bot's own 09:00 KST snapshot of that day (``day:<UTC date>`` in its database, the
  state before the 00:00 UTC step: wallet, position, pending signals) when there is one, else flat at the initial
  equity. Research "break" entries still waiting at 09:00 are not in that snapshot (paperbot/livecheck.py names the
  differences they cause).
After w1 it goes on only while the account holds a position entered before w1 (at most ``tail_ms``, never past
``now - 2 min``), so a trade entered late in the day is compared with its exit when the exit is known.

Binance is reached through ``BinanceMarket`` (paperbot/binance.py ``BinanceREST``, public endpoints; the read-only key
of live.env only for the leverage brackets, as the live bot): paced, paginated, 1m and 5m bars cached in a small
SQLite file between nights. Tests and offline replays pass their own ``Market``. Any failure to read the market raises
``MarketDown`` (the morning message says so). No order, no exchange account, no write outside the temporary folder
and the cache.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import time
from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol

import numpy as np

MIN = 60_000
FIVE = 300_000
H1 = 3_600_000
H4 = 14_400_000
DAY = 86_400_000
IV_MS = {"1m": MIN, "5m": FIVE, "30m": 6 * FIVE, "1h": H1, "4h": H4, "1d": DAY}
TREND_30M_BARS = 600                     # the trend bot's 30m entry bars fetched before the window (trendjudge.KEEP + room)
TREND_1D_BARS = 520                      # its daily bars (a 4h entry's judgment since 10-22: trendjudge.FETCH + room)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXCHANGE_FILE = os.path.join(ROOT, "research", "fullgrid", "exchange.json")
CACHE_IV = ("1m", "5m")                  # intervals kept in the cache between nights
CACHE_KEEP_MS = 10 * DAY                 # bars older than a request's start minus this are dropped from the cache
LIVE_COVER = 0.9                         # live_bars must hold this share of the window's minutes to be the source


class MarketDown(RuntimeError):
    """The market data could not be read (Binance unreachable, blocked, refusing)."""


class Market(Protocol):
    def klines(self, symbol: str, interval: str, start: int, end: int) -> list: ...      # [open, o, h, l, c, v]
    def mark_klines(self, symbol: str, start: int, end: int) -> list: ...                # 1m [open, o, h, l, c]
    def funding(self, symbol: str, start: int, end: int) -> list: ...                    # [(ms, rate)]
    def oi(self, symbol: str, start: int, end: int) -> list: ...                         # [(ms, open interest)]
    def specs(self, symbols) -> dict: ...
    def brackets(self, cfg) -> tuple: ...                                                # ({symbol: Brackets}, source)


# ====================================================================== Binance
class KlineCache:
    """Closed klines kept between nights (1m and 5m: the warm-up overlaps from one day to the next)."""

    def __init__(self, path: str):
        self.conn = sqlite3.connect(path, timeout=10)
        self.conn.execute("CREATE TABLE IF NOT EXISTS k (symbol TEXT NOT NULL, iv TEXT NOT NULL, t INTEGER NOT NULL, "
                          "o REAL, h REAL, l REAL, c REAL, v REAL, PRIMARY KEY (symbol, iv, t)) WITHOUT ROWID")
        self.conn.commit()

    def get(self, symbol: str, iv: str, start: int, end: int) -> list:
        return [list(r) for r in self.conn.execute(
            "SELECT t, o, h, l, c, v FROM k WHERE symbol = ? AND iv = ? AND t >= ? AND t < ? ORDER BY t",
            (symbol, iv, int(start), int(end)))]

    def put(self, symbol: str, iv: str, rows: list) -> None:
        self.conn.executemany("INSERT OR REPLACE INTO k VALUES (?,?,?,?,?,?,?,?)",
                              [(symbol, iv, int(r[0]), *[float(x) for x in r[1:6]]) for r in rows])
        self.conn.commit()

    def prune(self, symbol: str, iv: str, before: int) -> None:
        self.conn.execute("DELETE FROM k WHERE symbol = ? AND iv = ? AND t < ?", (symbol, iv, int(before)))
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


def missing_runs(have: list, start: int, end: int, ms: int) -> list:
    """[(a, b)] runs of bar open times in [start, end) not in ``have`` (sorted open times)."""
    got = set(int(t) for t in have)
    out, a = [], None
    t = int(start) - int(start) % ms if int(start) % ms else int(start)
    if t < start:
        t += ms
    while t < end:
        if t not in got:
            a = t if a is None else a
        elif a is not None:
            out.append((a, t))
            a = None
        t += ms
    if a is not None:
        out.append((a, int(end)))
    return out


class BinanceMarket:
    """Binance USD-M public market data through paperbot/binance.py (the live bot's client). ``rest``: a BinanceREST
    (default: the one live.env describes, so the leverage brackets come from the same read-only key as the live bot's);
    ``cache``: a KlineCache path for 1m / 5m bars (None: no cache)."""

    def __init__(self, rest=None, cache: Optional[str] = None, pause: float = 0.4,
                 now_ms: Callable[[], int] = lambda: int(time.time() * 1000), sleep: Callable = time.sleep):
        from .binance import BinanceREST
        self.rest = rest if rest is not None else BinanceREST(
            api_key=os.environ.get("BINANCE_API_KEY"), api_secret=os.environ.get("BINANCE_API_SECRET"),
            max_retries=2, backoff=1.0)
        self.cache = KlineCache(cache) if cache else None
        self.pause, self.now_ms, self.sleep = pause, now_ms, sleep
        self.calls = 0

    def _call(self, fn, *a, **kw):
        from .binance import BinanceError
        if self.calls:
            self.sleep(self.pause)                       # paced: the live bots share this server's request limits
        self.calls += 1
        try:
            return fn(*a, **kw)
        except (BinanceError, OSError, ValueError) as exc:
            raise MarketDown(f"{type(exc).__name__}: {exc}"[:300]) from None

    def _fetch(self, symbol: str, iv: str, start: int, end: int) -> list:
        ms, out, t = IV_MS[iv], [], int(start)
        now = self.now_ms()
        while t < end:
            got = self._call(self.rest.klines, symbol, iv, start_time=t, limit=1500)
            got = [r for r in got if int(r[0]) < end and int(r[0]) + ms <= now]
            if not got:
                break
            out += [[int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])] for r in got]
            nxt = int(got[-1][0]) + ms
            if nxt <= t or len(got) < 1000:
                break
            t = nxt
        return out

    def klines(self, symbol: str, interval: str, start: int, end: int) -> list:
        if self.cache is None or interval not in CACHE_IV:
            return self._fetch(symbol, interval, start, end)
        ms = IV_MS[interval]
        end_closed = min(int(end), self.now_ms() - 60_000 - ms + 1)       # only bars closed a minute ago are kept
        have = self.cache.get(symbol, interval, start, end_closed)
        for a, b in missing_runs([r[0] for r in have], start, end_closed, ms):
            rows = self._fetch(symbol, interval, a, b)
            if rows:
                self.cache.put(symbol, interval, rows)
        rows = self.cache.get(symbol, interval, start, end_closed)
        self.cache.prune(symbol, interval, int(start) - CACHE_KEEP_MS)      # a night's warm-up and ten days more
        if end_closed < end:
            rows += self._fetch(symbol, interval, max(int(start), end_closed), int(end))
        return rows

    def mark_klines(self, symbol: str, start: int, end: int) -> list:
        out, t, now = [], int(start), self.now_ms()
        while t < end:
            got = self._call(self.rest.mark_klines, symbol, "1m", start_time=t, limit=1500)
            got = [r for r in got if int(r[0]) < end and int(r[0]) + MIN <= now]
            if not got:
                break
            out += [[int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])] for r in got]
            nxt = int(got[-1][0]) + MIN
            if nxt <= t or len(got) < 1000:
                break
            t = nxt
        return out

    def funding(self, symbol: str, start: int, end: int) -> list:
        out, t = [], int(start)
        while t < end:
            got = self._call(self.rest.funding_rates, symbol, start_time=t, limit=1000)
            got = [r for r in got if int(r["fundingTime"]) < end]
            if not got:
                break
            out += [(int(r["fundingTime"]), float(r["fundingRate"])) for r in got]
            nxt = int(got[-1]["fundingTime"]) + 1
            if nxt <= t or len(got) < 1000:
                break
            t = nxt
        return out

    def oi(self, symbol: str, start: int, end: int) -> list:
        out, t = [], int(start)
        while t < end:
            got = self._call(self.rest.flow_stats, "oi", symbol, "5m", start_time=t, end_time=int(end), limit=500)
            got = sorted(got, key=lambda r: int(r["timestamp"]))
            got = [r for r in got if t <= int(r["timestamp"]) < end]
            if not got:
                break
            out += [(int(r["timestamp"]), float(r["sumOpenInterest"])) for r in got]
            nxt = int(got[-1]["timestamp"]) + 1
            if nxt <= t or len(got) < 500:
                break
            t = nxt
        return out

    def specs(self, symbols) -> dict:
        return self._call(self.rest.exchange_info, list(symbols))

    def brackets(self, cfg) -> tuple:
        """The live bot's own way (combo._brackets: the config's file, else Binance with the read-only key); without a
        key or when that fails, the repository's saved table (research/fullgrid/exchange.json)."""
        from . import combo as C
        try:
            return C._brackets(cfg, self.rest)
        except (SystemExit, Exception) as exc:  # noqa: BLE001  the saved table, said in the report
            b, src = file_brackets(cfg.symbols)
            return b, f"{src} ({type(exc).__name__}: {exc})"[:200]

    def close(self) -> None:
        if self.cache is not None:
            self.cache.close()


def file_brackets(symbols, path: str = EXCHANGE_FILE) -> tuple:
    from .margin import Brackets
    with open(path) as fh:
        payload = json.load(fh)["brackets"]
    by = {p["symbol"]: Brackets.from_binance(p) for p in payload}
    return {s: by[s] for s in symbols}, f"file {path}"


def file_specs(symbols, path: str = EXCHANGE_FILE) -> dict:
    with open(path) as fh:
        specs = json.load(fh).get("specs", {})
    return {s: dict(specs.get(s, {})) for s in symbols}


# ====================================================================== the replay
@dataclass
class ReplayResult:
    w0: int
    w1: int
    end: int                                   # the last stepped minute's close
    source: str                                # "live" (the rule bot's live_bars) | "binance"
    seeded: bool                               # started from the live bot's 09:00 snapshot
    signals: list = field(default_factory=list)      # {bar_close, strategy, symbol, side, status, why}
    trades: list = field(default_factory=list)       # COMBO@mix trades (closed), entry in the window or carried in
    open_position: Optional[dict] = None             # COMBO@mix position at the end
    outcomes: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    minutes: int = 0
    complete: bool = True                      # False: stopped by the time budget before w1
    elapsed_s: float = 0.0
    calls: int = 0
    brackets: str = ""                         # where the leverage brackets came from

    def to_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)


class _Clock:
    def __init__(self, now: int):
        self.now = int(now)

    def __call__(self) -> int:
        return self.now


class _Series:
    """One coin's bars of one interval as arrays (open time, o, h, l, c, v), served closed-only by the clock."""

    def __init__(self, rows: list, ms: int):
        a = np.array(rows, dtype=float) if rows else np.zeros((0, 6))
        if a.ndim == 2 and a.shape[1] == 5:
            a = np.hstack([a, np.full((len(a), 1), np.nan)])
        self.t = a[:, 0].astype(np.int64) if len(a) else np.zeros(0, np.int64)
        self.a = a
        self.ms = ms

    def rows(self, start: int, end: int, now: int, width: int = 5) -> list:
        i0 = int(np.searchsorted(self.t, int(start)))
        i1 = int(np.searchsorted(self.t, min(int(end), int(now) - self.ms + 1)))
        return [[int(self.t[i])] + [float(x) for x in self.a[i, 1:width]] for i in range(i0, max(i0, i1))]

    def at(self, t: int) -> Optional[np.ndarray]:
        i = int(np.searchsorted(self.t, int(t)))
        return self.a[i] if i < len(self.t) and int(self.t[i]) == int(t) else None


class _Fund:
    """Funding rates paid on the minute that holds the funding time (the live FundingFeed pays a rate on the first step
    after it reads it, at most 10 minutes later: same rate, same position, a few minutes apart)."""

    def __init__(self, rates: dict):
        self.rates = rates                      # minute -> {symbol: rate}

    def poll(self, now: int) -> None:
        pass

    def take(self, ts: int) -> dict:
        out = {}
        for t in [k for k in self.rates if k <= ts]:
            out.update(self.rates.pop(t))
        return out


def replay_day(cfg_raw: dict, market: Market, w0: int, w1: int, *, live_bars: Optional[dict] = None,
               seed: Optional[dict] = None, taker_fee: Optional[float] = None, tail_ms: int = 12 * H1,
               now_ms: Optional[int] = None, deadline_s: Optional[float] = None, workdir: Optional[str] = None,
               log: Optional[Callable[[str], None]] = None) -> ReplayResult:
    """Replay the combined bot over [w0, w1) (module docstring). ``cfg_raw``: the live bot's config (combo.json or the
    ``combo_run`` record); ``live_bars``: {minute: [live_bars row dicts]} of the rule bot (None or too few: Binance);
    ``seed``: the ``day:<date>`` snapshot ({"engines": {...}}) taken at w0, with the trend bot (``"trend"`` in the config,
    paperbot/trendbot.py) also ``"trend_history"``: {"since": the live bot's first start, "trades": its COMBO@mix trades
    (TradeRecord dicts) closed before w0} so its pauses (member, coin, daily loss) start as the live ones did. Raises
    MarketDown when the market cannot be read; any other error is a bug (raised)."""
    from . import combo as C
    from . import rmember as RM
    from .engine import restore_engine
    from .notify import NullNotifier
    from .store3 import Store3

    t_start = time.time()
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    say = log or (lambda s: None)
    w0, w1 = int(w0), int(w1)
    data_end = min(w1 + int(tail_ms), now_ms - 2 * MIN)
    data_end -= data_end % MIN
    data_end = max(data_end, min(w1 + MIN, now_ms - now_ms % MIN))
    tmp = tempfile.mkdtemp(prefix="livereplay_", dir=workdir)
    res = ReplayResult(w0=w0, w1=w1, end=w0, source="binance", seeded=False)
    store = paper = None
    try:
        raw = {k: v for k, v in dict(cfg_raw).items()}
        raw.update(paper_db=os.path.join(tmp, "paper3.db"), db=os.path.join(tmp, "combo.db"), telegram=False)
        cfg = C.ComboConfig.from_dict(raw)
        members = C.resolve_members(cfg.members, cfg.picks_file)
        syms = list(cfg.symbols)
        settings = C.settings_of(cfg, **({} if taker_fee is None else {"taker_fee": float(taker_fee)}))
        brackets, res.brackets = market.brackets(cfg)
        try:
            specs = market.specs(syms)
        except MarketDown:
            raise
        except Exception as exc:  # noqa: BLE001  the saved table
            specs = file_specs(syms)
            res.notes.append(f"코인 규격: 저장된 표 사용({type(exc).__name__})")
        custom = C.CustomSignals(members, syms) if any(m.custom for m in members) else None
        keep5 = custom.keep if custom is not None else 0

        # ---- market data, fetched once
        say(f"fetching market data {len(syms)} coins")
        m1, m5, h1, h4, fund, oi, mark, m30, d1 = {}, {}, {}, {}, {}, {}, {}, {}, {}
        lo1 = w0 - RM.RData.KEEP_1M * MIN - 2 * H1
        trend = cfg.trend is not None
        for s in syms:
            m1[s] = _Series(market.klines(s, "1m", lo1, data_end), MIN)
            if trend:
                m30[s] = _Series(market.klines(s, "30m", w0 - TREND_30M_BARS * IV_MS["30m"], data_end), IV_MS["30m"])
                if any(m.tf == "4h" for m in members):
                    d1[s] = _Series(market.klines(s, "1d", w0 - TREND_1D_BARS * DAY, data_end), DAY)
            if keep5:
                m5[s] = _Series(market.klines(s, "5m", w0 - keep5 * FIVE, data_end), FIVE)
            h1[s] = _Series(market.klines(s, "1h", w0 - (RM.RData.FETCH["1h"] + 2) * H1, data_end), H1)
            h4[s] = _Series(market.klines(s, "4h", w0 - (RM.RData.FETCH["4h"] + 2) * H4, data_end), H4)
            fund[s] = sorted(market.funding(s, w0 - 3 * DAY - H4, data_end))
            try:
                oi[s] = sorted(market.oi(s, w0 - DAY - 3 * H1, data_end))
            except MarketDown as exc:   # the live bot reads open interest only at an entry, and copes without it
                oi[s] = None
                res.errors.append(f"{s} open interest: {exc}")
        source = "binance"
        steps: dict = {}
        if live_bars:
            inside = sum(1 for t in live_bars if w0 <= t < w1)
            if inside >= LIVE_COVER * ((w1 - w0) // MIN):
                source = "live"
                steps = {t: rows for t, rows in live_bars.items() if w0 <= t < data_end}
            else:
                res.notes.append(f"규칙봇 1분봉이 {inside}/{(w1 - w0) // MIN}분만 있어 바이낸스 1분봉으로 대조")
        if source == "binance":
            for s in syms:
                mark[s] = _Series([r + [np.nan] for r in market.mark_klines(s, w0, data_end)], MIN)
            for t in range(w0, data_end, MIN):
                rows = []
                for s in syms:
                    b, mk = m1[s].at(t), mark[s].at(t)
                    if b is None:
                        continue
                    rows.append(dict(ts=t, symbol=s, open=float(b[1]), high=float(b[2]), low=float(b[3]),
                                     close=float(b[4]), volume=float(b[5]),
                                     mark_open=None if mk is None else float(mk[1]),
                                     mark_high=None if mk is None else float(mk[2]),
                                     mark_low=None if mk is None else float(mk[3]),
                                     mark_close=None if mk is None else float(mk[4]),
                                     close_time=t + MIN - 1, processed_at=t + MIN + 5_000))
                if rows:
                    steps[t] = rows
        res.source = source
        res.calls = int(getattr(market, "calls", 0) or 0)

        # ---- the live bot's callbacks, served from the fetched data by the simulated clock
        clock = _Clock(w0 + 5_000)

        def klines(symbol, interval, start, end):
            ser = {"1m": m1, "1h": h1, "4h": h4, "5m": m5}[interval].get(symbol)
            return [] if ser is None else ser.rows(start, end, clock.now)

        def funding_cb(symbol, start):
            return [(t, r) for t, r in fund.get(symbol, []) if int(start) <= t <= clock.now]

        def oi_cb(symbol, start, end):
            rows = oi.get(symbol)
            if rows is None:
                raise MarketDown(f"{symbol} open interest unavailable")
            return [(t, v) for t, v in rows if int(start) <= t < min(int(end), clock.now + 1)]

        def fetch_5m(symbol, start, end):
            ser = m5.get(symbol)
            if ser is None:
                return []
            end = min(int(end), clock.now - clock.now % FIVE)
            return ser.rows(start, end, clock.now, width=6)

        def prices():
            t = clock.now - clock.now % MIN
            out = {}
            for s in syms:
                b = m1[s].at(t)
                if b is not None:
                    out[s] = (float(b[1]), float(b[1]))
            return out

        rates: dict = {}
        for s in syms:
            for t, r in fund[s]:
                if t >= w0:
                    rates.setdefault(t - t % MIN, {})[s] = r

        btc = None
        if any(m.needs_btc for m in members):
            btc = C.BtcTrend(lambda: [[r[0], r[1], r[2], r[3], r[4]] for r in h4["BTCUSDT"].rows(
                0, clock.now + H4, clock.now + H4)], clock)
        rdata = RM.RData(syms, klines, funding_cb, oi_cb) if any(m.research for m in members) else None

        # ---- the accounts
        paper = Store3(cfg.paper_db)
        paper.commit()
        store = Store3(cfg.db)
        book = C.build_book(cfg, settings, brackets, store, NullNotifier(), specs)
        if seed and isinstance(seed.get("engines"), dict):
            for aid, st in seed["engines"].items():
                if aid in book.engines:
                    restore_engine(book.engines[aid], st)
            res.seeded = True
        extra, runner_cls = {}, C.ComboRunner
        if trend:                                # 추세판단 봇: its judge on the same closed bars, served by the clock
            from .trendbot import TrendRunner
            from .trendjudge import Judge, Klines, TrendRules
            series = {"30m": m30, "1h": h1, "4h": h4, "1d": d1}

            def jfetch(symbol, tf, limit):
                ser = series[tf].get(symbol)
                return [] if ser is None else ser.rows(0, clock.now + 1, clock.now, width=6)[-int(limit):]
            runner_cls = TrendRunner
            extra["judge"] = Judge(Klines(jfetch, clock), TrendRules.from_dict(cfg.trend))
            hist = (seed or {}).get("trend_history") if isinstance(seed, dict) else None
            for t in (hist or {}).get("trades") or []:
                try:
                    store.conn.execute(
                        "INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, "
                        "equity_after, data) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (C.ACCOUNT, t["symbol"], int(t["entry_time"]), int(t["exit_time"]), t["exit_reason"],
                         int(t["leverage"]), float(t["pnl"]), float(t["roe"]), float(t["equity_after"]), json.dumps(t)))
                except (KeyError, TypeError, ValueError):
                    continue
            store.commit()
        runner = runner_cls(cfg, members, book, store, NullNotifier(), custom, clock, prices, _Fund(rates),
                            fetch_5m=fetch_5m if keep5 else None, btc=btc, rdata=rdata, **extra)
        if trend:
            hist = (seed or {}).get("trend_history") if isinstance(seed, dict) else None
            if hist and hist.get("since") is not None:
                runner.since = int(hist["since"])
        runner.cursor = 0
        book.last_ts = w0 - MIN
        if custom is not None:
            custom.fill_gaps(fetch_5m, w0)
        acct = book.engines[C.ACCOUNT]
        say(f"replay {source} from {w0} to {w1} (data to {data_end}), seeded={res.seeded}")
        last = w0 - MIN
        for t in range(w0, data_end, MIN):
            if t > w1:            # minute w1 itself is stepped: the entry minute of the signals closing at w1
                p = acct.position
                if p is None or int(p.entry_time) >= w1:
                    break
            if deadline_s is not None and time.time() - t_start > deadline_s:
                res.complete = t >= w1
                res.notes.append(f"시간 제한({deadline_s / 60:.0f}분)으로 "
                                 f"{time.strftime('%H:%M', time.gmtime(t / 1000 + 9 * 3600))}까지만 다시 돌림")
                break
            rows = steps.get(t)
            if not rows:
                continue
            paper.live_bars(rows)
            paper.commit()
            clock.now = max(int(t) + MIN + 1_000, max(int(r.get("processed_at") or 0) for r in rows) + 1_000)
            runner.poll()
            last = t
            res.minutes += 1
            if (t - w0) % (6 * H1) == 0:
                say(f"replay {time.strftime('%m-%d %H:%M', time.gmtime(t / 1000 + 9 * 3600))} KST "
                    f"trades {len(acct.trades)} elapsed {time.time() - t_start:.0f}s")
        res.end = last + MIN
        if custom is not None and custom.errors:
            res.errors += custom.errors[:20]
        res.errors += [str(a[0]) for a in store.conn.execute(          # the runner's own warnings (not the accounts')
            "SELECT text FROM alerts WHERE level != 'INFO' AND (text LIKE '[combo]%' OR text LIKE '[합친 봇%') "
            "ORDER BY ts LIMIT 20")]
        res.signals = signals_of(store.conn, w0, w1)
        res.outcomes = outcomes_of(store.conn, C.ACCOUNT)
        # (the trend bot's history before w0 is in the same table: only the trades that closed in the replay count)
        res.trades = trades_of(store.conn, C.ACCOUNT, res.outcomes, since=w0 if cfg.trend is not None else None)
        p = acct.position
        if p is not None:
            res.open_position = {"entry_time": int(p.entry_time), "symbol": p.symbol, "side": int(p.side),
                                 "strategy": p.signal.strategy_id, "tf": p.signal.timeframe,
                                 "member": p.signal.meta.get("member"), "entry_price": float(p.entry_price),
                                 "stop": float(p.stop_price)}
        if not res.seeded:
            res.notes.append("그날 09:00 상태 기록이 없어 빈 계좌로 시작")
    finally:
        for s in (store, paper):
            if s is not None:
                try:
                    s.conn.close()
                except sqlite3.Error:
                    pass
        shutil.rmtree(tmp, ignore_errors=True)
    res.elapsed_s = round(time.time() - t_start, 1)
    return res


# ====================================================================== records of a paper database (live or replay)
def signals_of(conn, w0: int, w1: int) -> list:
    """signal_log rows with the bar closing in (w0, w1]: the boundaries the day's minutes compute."""
    out = []
    for bc, tf, strat, sym, side, status, data in conn.execute(
            "SELECT bar_close, timeframe, strategy, symbol, side, status, data FROM signal_log "
            "WHERE bar_close > ? AND bar_close <= ? ORDER BY bar_close, id", (int(w0), int(w1))):
        try:
            d = json.loads(data or "{}")
        except ValueError:
            d = {}
        out.append({"bar_close": int(bc), "tf": tf, "strategy": strat, "symbol": sym, "side": int(side),
                    "status": status, "why": d.get("why", ""), "name": d.get("strategy") or strat.split("@")[0]})
    return out


def outcomes_of(conn, account: str) -> list:
    out = []
    for ts, status, reason, sym, data in conn.execute(
            "SELECT step_ts, status, reason, symbol, data FROM outcomes WHERE account_id = ? ORDER BY id", (account,)):
        try:
            sig = json.loads(data)["signal"]
        except (ValueError, KeyError, TypeError):
            sig = {}
        meta = sig.get("meta") or {}
        out.append({"ts": int(ts), "status": status, "reason": reason, "symbol": sym, "side": sig.get("side"),
                    "member": meta.get("member"), "strategy": sig.get("strategy_id"), "tf": sig.get("timeframe"),
                    "bar_close": (int(sig["ts"]) + 1) if sig.get("ts") is not None else None})
    return out


def trades_of(conn, account: str, outcomes: Optional[list] = None, since: Optional[int] = None) -> list:
    ent = {(o["ts"], o["symbol"]): o.get("member") for o in (outcomes or []) if o["status"] == "ENTERED"}
    q = "SELECT data FROM trades WHERE account_id = ?" + (" AND exit_time >= ?" if since is not None else "") + \
        " ORDER BY entry_time"
    out = []
    for (data,) in conn.execute(q, (account,) + ((int(since),) if since is not None else ())):
        t = json.loads(data)
        out.append({"entry_time": int(t["entry_time"]), "exit_time": int(t["exit_time"]), "symbol": t["symbol"],
                    "side": int(t["side"]), "strategy": t["strategy_id"], "tf": t["timeframe"],
                    "member": ent.get((int(t["entry_time"]), t["symbol"])), "reason": t["exit_reason"],
                    "roe": float(t["roe"]), "pnl": float(t["pnl"]), "entry_price": float(t["entry_price"]),
                    "exit_price": float(t["exit_price"]), "fees": float(t.get("fees") or 0.0),
                    "funding": float(t.get("funding") or 0.0), "qty": float(t.get("qty") or 0.0)})
    return out

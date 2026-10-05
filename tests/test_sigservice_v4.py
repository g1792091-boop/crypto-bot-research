"""Paper v4 signal service and runner (plan P4): the core group's rows byte-identical to v3, the 5m path (reel + 5m
coin flips), the DeepSeek map with its own timeout and error class, and cmd_run's database checks."""

import dataclasses
import json
import os
import re
import warnings
from collections import deque

import numpy as np
import pandas as pd
import pytest

from paperbot import Bar, Brackets, Signal
from paperbot import config as C
from paperbot import sigservice as SS
from paperbot.accounts import AccountBook, HeldEngine
from paperbot.live3 import Runner3
from paperbot.notify import ListNotifier
from paperbot.store3 import Store3

MIN = 60_000
FIVE = 300_000
DAY = 86_400_000
S = C.v3_settings()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLDEN = os.path.join(ROOT, "tests", "data", "v3_locked_signals.json")

# ------------------------------------------------------------------ golden: the v3 rows of the core group
# The inputs below are the exact inputs the golden file was captured with (scratch script, sigservice.py and live3.py
# unedited at HEAD 5bc7e5f). Do not change them, and never regenerate the file.
GOLD_TRADE = ("BTCUSDT", "ETHUSDT")
GOLD_RECORD = ("XRPUSDT",)
GOLD_N = 117_000                        # more 5m bars than the service keeps (deque maxlen 116,064)
GOLD_D = 20_000 * DAY                   # a 1d boundary: 15m, 30m, 1h, 4h and 1d all close here
GOLD_RATES = {"5m": 1.0, "15m": 0.6, "30m": 0.6, "1h": 0.6, "4h": 0.6}


def gold_bars(symbol, n=GOLD_N, end=GOLD_D):
    seed = {"BTCUSDT": 11, "ETHUSDT": 12, "XRPUSDT": 13, "SOLUSDT": 14}[symbol]
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.003, n) + 0.00002 * np.sin(np.arange(n) / 900)))
    o = np.r_[c[0], c[:-1]]
    w = np.abs(rng.normal(0, 0.0015, (2, n)))
    h = np.maximum(o, c) * (1 + w[0])
    lo = np.minimum(o, c) * (1 - w[1])
    v = rng.uniform(1, 9, n)
    ts = end - FIVE * np.arange(n, 0, -1, dtype=np.int64)
    return np.column_stack([ts.astype(float), o, h, lo, c, v])


def gold_plan():
    D = GOLD_D
    return [(D, "15m", 9_000, GOLD_TRADE), (D, "30m", 9_500, GOLD_TRADE), (D, "1h", 10_000, ("BTCUSDT",)),
            (D, "4h", 200_000, GOLD_TRADE), (D, "1d", 11_000, GOLD_TRADE),
            (D + 1_800_000, "15m", 8_000, GOLD_TRADE), (D + 1_800_000, "30m", 8_500, GOLD_TRADE)]


def gold_extra(symbol, upto):
    rng = np.random.default_rng({"BTCUSDT": 21, "ETHUSDT": 22, "XRPUSDT": 23}[symbol])
    last = gold_bars(symbol)[-1]
    k = (upto - GOLD_D) // FIVE
    c = last[4] * np.exp(np.cumsum(rng.normal(0, 0.003, k)))
    o = np.r_[last[4], c[:-1]]
    h = np.maximum(o, c) * 1.001
    lo = np.minimum(o, c) * 0.999
    ts = GOLD_D + FIVE * np.arange(k, dtype=np.int64)
    return np.column_stack([ts.astype(float), o, h, lo, c, np.full(k, 3.0)])


def gold_price(symbol):
    return {"BTCUSDT": (100.01, 100.03), "ETHUSDT": (99.97, 99.99)}[symbol]


def run_gold(service):
    for s in GOLD_TRADE + GOLD_RECORD:
        rows = gold_bars(s)
        service.bootstrap(s, [tuple(r) for r in rows[:-50]])
        for r in rows[-50:]:
            service.add_5m(Bar(s, int(r[0]), int(r[0]) + FIVE - 1, r[1], r[2], r[3], r[4], volume=r[5]))
    out = []
    fed = GOLD_D
    for boundary, tf, off, priced in gold_plan():
        if boundary > fed:
            for s in GOLD_TRADE + GOLD_RECORD:
                for r in gold_extra(s, boundary):
                    service.add_5m(Bar(s, int(r[0]), int(r[0]) + FIVE - 1, r[1], r[2], r[3], r[4], volume=r[5]))
            fed = boundary
        assert service.complete(boundary)
        rows, subs, reports = service.compute(boundary, tf, lambda: boundary + off,
                                              lambda: {s: gold_price(s) for s in priced})
        out.append({"boundary": boundary, "tf": tf,
                    "rows": rows, "subs": [[aid, dataclasses.asdict(sig)] for aid, sig in subs],
                    "reports": [{k: r.get(k) for k in ("symbol", "tf", "ready", "why", "bar_open", "close", "atr",
                                                       "sides", "errors")} for r in reports]})
    return out


def canon(obj):
    return json.dumps(obj, sort_keys=True, default=repr, ensure_ascii=False)


def test_core_rows_byte_identical_to_v3_with_every_v4_group_switched_on():
    """The 36 locked strategies and the 12 core coin flips: the same inputs give the same signal_log rows, Signals and
    worker reports, byte for byte, as the v3 service before the v4 edit (statuses SUBMITTED, LATE, NO_PRICE and
    RECORD all present; 1d and XRP record-only), with the DeepSeek and 5m groups switched on as cmd_run does."""
    with open(GOLDEN) as fh:
        gold = json.load(fh)
    assert gold["sigservice_unedited"] is True and len(gold["canon"]) == len(gold_plan())
    from paperbot.live3 import service_options
    svc = SS.SignalService(GOLD_TRADE, GOLD_RECORD, dict(GOLD_RATES), procs=1, **service_options())
    assert svc.keep == 116_064 and svc.due(GOLD_D) == ["15m", "30m", "1h", "4h", "1d"]
    got = [canon(x) for x in run_gold(svc)]
    statuses = {r["status"] for x in got for r in json.loads(x)["rows"]}
    assert statuses == {"SUBMITTED", "LATE", "NO_PRICE", "RECORD"}
    for k, (a, b) in enumerate(zip(got, gold["canon"])):
        assert a == b, gold_plan()[k]


# ------------------------------------------------------------------ fakes
class FakeLib:
    NAMES = ["A", "B", "DOGE_L", "DOGE_S"]

    @staticmethod
    def tf_minutes(tf):
        return {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}[tf]

    @staticmethod
    def warmup_bars(tf):
        return 10


class NoPool:
    """A pool that must never be used."""
    def __getattr__(self, name):
        raise AssertionError(f"the Pool was used ({name})")


def levels(bar_open, close=100.0, stop=99.0, up=101.0):
    return {"side": 1, "bar_open": bar_open, "atr14": 0.5, "swing_low": stop + 0.025, "stop": stop, "up_band": up,
            "closes": [close] * 19}


class FakeReel:
    """reelsig's interface: the reel fires on the coins in ``fire``."""
    class ReelError(Exception):
        pass

    class ReelUnavailable(ReelError):
        pass

    def __init__(self, fire=("BTCUSDT",), unavailable=False, raise_on=()):
        self.fire, self.unavailable, self.raise_on, self.calls = set(fire), unavailable, set(raise_on), []

    def _sym(self, df):
        return df.attrs.get("sym")

    def signal(self, df):
        self.calls.append(("signal", len(df)))
        if self.unavailable:
            raise self.ReelUnavailable("pin mismatch")
        c = float(df["close"].iloc[-1])
        if c in self.raise_on:
            raise self.ReelError("boom")
        return levels(int(df["ts"].iloc[-1]), c) if c in self.fire else None

    def flip_levels(self, df):
        self.calls.append(("flip", len(df)))
        return levels(int(df["ts"].iloc[-1]), float(df["close"].iloc[-1]), stop=98.0)


SYMS = tuple(C.V3_SYMBOLS)
PRICE = {s: 100.0 + k for k, s in enumerate(SYMS)}     # one close per coin, so the fake reel can tell them apart


def fill_hist(svc, end, n, syms=SYMS):
    """``n`` flat 5m bars per coin, the last one closing at ``end``."""
    for s in syms:
        p = PRICE.get(s, 50.0)
        svc.bootstrap(s, [(end - FIVE * (n - i), p, p, p, p, 1.0) for i in range(n)])


def one_min(ts, syms=SYMS):
    return {s: Bar(s, ts, ts + MIN - 1, PRICE[s], PRICE[s], PRICE[s], PRICE[s], volume=1.0) for s in syms}


def book_of(tmp_path, defs, name="v4.db"):
    store = Store3(str(tmp_path / name))
    book = AccountBook(S, {s: Brackets.example() for s in SYMS}, store, ListNotifier())
    book.open_accounts(defs, 0)
    return store, book


def five_m_defs():
    return [d for d in C.v4_account_defs([f"c{k}" for k in range(36)]) if d["timeframe"] == "5m"]


def svc_5m(**kw):
    opts = dict(lib=FakeLib(), procs=4, pool=NoPool(), trade_tfs=C.V3_TRADE_TFS, record_tfs=("1d",),
                ds_tfs=C.DS200_TFS, five_m=True, flip5m={"rate": 1.0, "long_only": True})
    opts.update(kw)
    return SS.SignalService(SYMS, (), {"15m": 0.0}, **opts)


B15 = 1_800_000_900_000          # a 15m boundary that is not a 30m one
assert B15 % 900_000 == 0 and B15 % 1_800_000


# ------------------------------------------------------------------ the 5m path
def test_a_5m_only_boundary_never_calls_the_pool_and_logs_only_the_5m_accounts(tmp_path):
    svc = svc_5m()
    reel = svc._mods["reel"] = FakeReel(fire=(PRICE["BTCUSDT"],))
    fill_hist(svc, B15, C.REEL_WINDOW_5M)
    store, book = book_of(tmp_path, five_m_defs() + [{"strategy": "A", "timeframe": "15m", "kind": "strategy"}])
    hook = []
    run = Runner3(book, svc, store, ListNotifier(), SYMS, lambda: B15 + FIVE + 9_000,
                  lambda: {s: (PRICE[s] - 0.01, PRICE[s] + 0.01) for s in SYMS})
    run.post_boundary = lambda b, sub, to: hook.append((b, sorted(a for a, _ in sub), to))
    run.process([(B15 + k * MIN, one_min(B15 + k * MIN), {}) for k in range(4)])
    assert reel.calls == [] and store.conn.execute("SELECT COUNT(*) FROM signal_log").fetchone()[0] == 0
    run.process([(B15 + 4 * MIN, one_min(B15 + 4 * MIN), {})])      # the 5m bar's last 1m bar: now it fires
    assert svc.due(B15 + FIVE) == [] and svc.due_ds(B15 + FIVE) == [] and svc.due_5m(B15 + FIVE)
    rows = store.conn.execute("SELECT timeframe, strategy, symbol, side, status, data FROM signal_log").fetchall()
    assert {r[0] for r in rows} == {"5m"} and {r[1] for r in rows} == {"REEL_H1", "RANDOM_1", "RANDOM_2", "RANDOM_3"}
    assert [r[2] for r in rows if r[1] == "REEL_H1"] == ["BTCUSDT"] and {r[3] for r in rows} == {1}
    assert {r[4] for r in rows} == {"SUBMITTED"} and len(rows) == 1 + 3 * len(SYMS)
    data = {(r[1], r[2]): json.loads(r[5]) for r in rows}
    d = data[("REEL_H1", "BTCUSDT")]
    assert d["group"] == "reel" and d["exits"] == "reel" and d["reel"]["stop"] == 99.0 and d["reel"]["up_band"] == 101.0
    assert data[("RANDOM_2", "ETHUSDT")]["group"] == "flip" and data[("RANDOM_2", "ETHUSDT")]["reel"]["stop"] == 98.0
    # every SUBMITTED row is submitted (the engine takes the first and records the others SKIPPED)
    assert len(hook) == 1 and hook[0][0] == B15 + FIVE and hook[0][2] is False
    sub = hook[0][1]
    assert sub.count("REEL_H1@5m") == 1 and all(sub.count(f"RANDOM_{k}@5m") == len(SYMS) for k in (1, 2, 3))
    from paperbot.reel_engine import signal_problem
    pend = book.engines["REEL_H1@5m"].pending
    assert len(pend) == 1 and signal_problem(pend[0]) is None and pend[0].ts + 1 == B15 + FIVE
    assert pend[0].stop_price == 99.0 and pend[0].tp_price == 101.0 and "stop_dist" not in pend[0].meta
    run.process([(B15 + 5 * MIN, one_min(B15 + 5 * MIN), {})])      # the entry fills at the reference ask
    p = book.engines["REEL_H1@5m"].position
    assert p is not None and p.stop_price == 99.0 and p.tp_price == 101.0
    assert p.entry_price == pytest.approx((PRICE["BTCUSDT"] + 0.01) * (1 + S.slippage_frac))


def test_a_missing_last_minute_skips_the_5m_signals(tmp_path):
    svc = svc_5m()
    reel = svc._mods["reel"] = FakeReel(fire=(PRICE["BTCUSDT"],))
    fill_hist(svc, B15, C.REEL_WINDOW_5M)
    store, book = book_of(tmp_path, five_m_defs())
    run = Runner3(book, svc, store, ListNotifier(), SYMS, lambda: B15 + FIVE + 9_000, lambda: {})
    steps = [(B15 + k * MIN, one_min(B15 + k * MIN), {}) for k in range(5)]
    del steps[4][1]["SOLUSDT"]                                       # SOL's last 1m bar of the 5m bar never came
    run.process(steps)
    assert reel.calls == [] and store.conn.execute("SELECT COUNT(*) FROM signal_log").fetchone()[0] == 0
    assert any("5m history incomplete" in t for (t,) in store.conn.execute("SELECT text FROM alerts"))


def test_5m_statuses_late_no_price_and_long_only_flips():
    svc = svc_5m(flip5m=dict(C.V4_FLIP5M))
    svc._mods["reel"] = FakeReel(fire=(PRICE["BTCUSDT"], PRICE["ETHUSDT"]))
    fill_hist(svc, B15, C.REEL_WINDOW_5M)
    b = B15
    rows, subs, rep = svc.compute_5m(b, lambda: b + 61_000, lambda: {"BTCUSDT": (99.0, 100.01)})
    reel = [r for r in rows if r["strategy"] == "REEL_H1"]
    assert {r["status"] for r in reel} == {"LATE"} and subs == []             # 61 s > FIVE_M_MAX_DELAY_MS
    rows, subs, rep = svc.compute_5m(b, lambda: b + 59_000, lambda: {"BTCUSDT": (99.0, 100.01)})
    st = {r["symbol"]: r["status"] for r in rows if r["strategy"] == "REEL_H1"}
    assert st == {"BTCUSDT": "SUBMITTED", "ETHUSDT": "NO_PRICE"} and [a for a, _ in subs][:1] == ["REEL_H1@5m"]
    (aid, sig), = [x for x in subs if x[0] == "REEL_H1@5m"]
    assert sig.meta["ref_price"] == 100.01 and sig.atr == 0.5 and sig.timeframe == "5m" and sig.side == 1
    assert set(sig.meta["reel"]) == {"stop", "swing_low", "atr14", "up_band", "bar_open", "closes"}
    # the flips: long only, the same draw stream as the core flips ([seed, 5, coin, bar minutes])
    for k, sym in enumerate(SYMS):
        for seed in C.V3_RANDOM_SEEDS:
            fire = np.random.default_rng([seed, 5, k, b // MIN]).random() < C.V4_FLIP5M["rate"]
            assert (f"RANDOM_{seed}", sym) in {(r["strategy"], r["symbol"]) for r in rows} or not fire
    with pytest.raises(ValueError):
        svc_5m(flip5m={"rate": 0.5, "long_only": False})
    with pytest.raises(ValueError):
        SS.SignalService(SYMS, (), {}, lib=FakeLib(), procs=1, trade_tfs=("5m", "15m"))


def test_5m_flip_rate_over_many_bars_matches_config():
    svc = svc_5m(flip5m=dict(C.V4_FLIP5M))
    n = 0
    for i in range(4000):
        for sym in SYMS:
            n += len(svc._random_5m(B15 + i * FIVE, sym))
    rate = n / (4000 * len(SYMS) * 3)
    assert abs(rate - C.V4_FLIP5M["rate"]) < 0.003 and C.V4_FLIP5M["long_only"] is True


def test_reel_refused_and_reel_errors_stay_in_the_5m_group(tmp_path):
    svc = svc_5m()
    svc._mods["reel"] = FakeReel(unavailable=True)
    b5 = B15 + FIVE                                                  # a 5m-only boundary
    fill_hist(svc, b5, C.REEL_WINDOW_5M)
    store, book = book_of(tmp_path, five_m_defs())
    note = ListNotifier()
    run = Runner3(book, svc, store, note, SYMS, lambda: b5 + 9_000, lambda: {})
    run._signals(b5)
    run._signals(b5)
    assert svc.refused == {"reel": "ReelUnavailable: pin mismatch"}
    crit = [t for lvl, t in note.messages if lvl == "CRITICAL"]
    assert len(crit) == 1 and crit[0].startswith("[reel] signal code refused")
    assert store.conn.execute("SELECT COUNT(*) FROM signal_log").fetchone()[0] == 0
    # a ReelError on one coin costs only that coin's reel signal
    svc2 = svc_5m()
    svc2._mods["reel"] = FakeReel(fire=(PRICE["BTCUSDT"],), raise_on=(PRICE["ETHUSDT"],))
    fill_hist(svc2, B15, C.REEL_WINDOW_5M)
    rows, subs, rep = svc2.compute_5m(B15, lambda: B15 + 9_000, lambda: {s: (1.0, PRICE[s]) for s in SYMS})
    assert [r["symbol"] for r in rows if r["strategy"] == "REEL_H1"] == ["BTCUSDT"]
    assert [e for r in rep for e in r["errors"]] == ["reel ReelError: boom"]
    # an unexpected exception inside compute_5m is fenced by the runner: the core group's compute still runs
    svc3 = svc_5m()
    svc3.compute_5m = lambda *a: (_ for _ in ()).throw(RuntimeError("bug"))
    core = []
    svc3.compute = lambda b, tf, now, bk: (core.append(tf), ([], [], []))[1]
    svc3._ds_map = lambda jobs: []
    svc3._mods["ds200"] = FakeDs()
    fill_hist(svc3, B15, 30)
    run3 = Runner3(book, svc3, store, ListNotifier(), SYMS, lambda: B15 + 9_000, lambda: {})
    run3._signals(B15)
    assert core == ["15m"] and run3.group_errors == 1 and run3.reel_errors == 1 and run3.ds_errors == 0
    failed = [t for (t,) in store.conn.execute("SELECT text FROM alerts") if t.startswith("[reel] 5m signals")]
    assert failed == [f"[reel] 5m signals (reel and 5m coin flips) failed at {B15} (RuntimeError: bug); "
                      "the other groups run on"] and re.match(SS.REEL_FAILED_RE, failed[0])


def test_warm_up_and_wrong_bar_give_no_5m_rows():
    svc = svc_5m()
    svc._mods["reel"] = FakeReel(fire=tuple(PRICE.values()))
    fill_hist(svc, B15, C.REEL_WINDOW_5M - 1)
    rows, subs, rep = svc.compute_5m(B15, lambda: B15 + 9_000, lambda: {})
    assert rows == [] and all(r["why"].startswith("warm-up") for r in rep)
    svc = svc_5m()
    svc._mods["reel"] = FakeReel(fire=tuple(PRICE.values()))
    fill_hist(svc, B15 - FIVE, C.REEL_WINDOW_5M)
    rows, subs, rep = svc.compute_5m(B15, lambda: B15 + 9_000, lambda: {})
    assert rows == [] and all("expected" in r["why"] for r in rep)
    assert svc.compute_5m(B15 + 60_000, lambda: 0, lambda: {}) == ([], [], [])     # not a 5m boundary


def test_no_core_or_deepseek_name_is_ever_due_on_5m():
    svc = svc_5m()
    seen_core, seen_ds = set(), set()
    for k in range(288):
        b = DAY * 20_000 + k * FIVE
        seen_core |= set(svc.due(b))
        seen_ds |= set(svc.due_ds(b))
        assert svc.due_5m(b)
    assert "5m" not in seen_core | seen_ds and seen_ds == set(C.DS200_TFS)
    assert {tf: len(v) for tf, v in svc.ds_names.items()} == {"15m": 44, "30m": 44, "1h": 44, "4h": 39}
    assert not {n for v in svc.ds_names.values() for n in v} & {"REEL_H1", "RANDOM_1"}
    v3 = SS.SignalService(SYMS, (), {"5m": 1.0}, lib=FakeLib(), procs=1)
    assert not v3.due_5m(B15) and v3.due_ds(B15) == [] and v3.groups_on() == []
    assert v3.compute_5m(B15, lambda: 0, lambda: {}) == ([], [], [])
    assert v3.compute_ds(B15, "15m", lambda: 0, lambda: {}) == ([], [], [])


# ------------------------------------------------------------------ the reel end to end on real code
def _series(seed, n, end):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.001, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.001, n)))
    ts = end - FIVE * np.arange(n, 0, -1, dtype=np.int64)
    return pd.DataFrame({"ts": ts, "open": o, "high": h, "low": lo, "close": c})


def test_real_reel_signal_reaches_the_reel_engine(tmp_path):
    """reelsig (pinned lib_reel5m) on the service's history -> the REEL_H1 row and Signal -> ReelEngine enters with
    the signal's stop and first target. The signal bar is one lib_reel5m's own machine finds on the series."""
    from paperbot import reelsig
    from paperbot.reel_engine import signal_problem
    R = reelsig._load()
    n, end = 6_200, B15 + 2 * FIVE * 3 + FIVE        # end is not a 15m boundary
    frames = {s: _series(k, n, end) for k, s in enumerate(SYMS)}
    fr = frames["BTCUSDT"].assign(ts=pd.to_datetime(frames["BTCUSDT"]["ts"], unit="ms", utc=True))
    fr.attrs["tf"] = "5m"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        P = R.Prep(R.indicators(fr), *reelsig.H1_SETTINGS)
        _, sigs, _ = R.simulate(P, reelsig._NO_COST, 0, n, "open", False)
    cand = [int(x["signal_idx"]) for x in sigs if 5_000 <= int(x["signal_idx"]) < n - 2]
    s = next(i for i in cand if (int(frames["BTCUSDT"]["ts"].iloc[i]) + FIVE) % 900_000)   # a 5m-only boundary
    want = reelsig.signal(frames["BTCUSDT"].iloc[:s + 1])
    assert want is not None and want["bar_open"] == int(frames["BTCUSDT"]["ts"].iloc[s])
    svc = SS.SignalService(SYMS, (), {}, lib=FakeLib(), procs=1, trade_tfs=(), record_tfs=(), five_m=True,
                           flip5m=dict(C.V4_FLIP5M))
    assert svc.verify_groups()["reel"]["lib_reel5m.py"] == reelsig.PIN_LIB_REEL5M
    for sym, df in frames.items():
        svc.bootstrap(sym, [tuple(r) + (1.0,) for r in df.iloc[:s].itertuples(index=False)])
    store, book = book_of(tmp_path, five_m_defs())
    bar_s = {sym: df.iloc[s] for sym, df in frames.items()}
    t0 = int(bar_s["BTCUSDT"]["ts"])
    ask = float(bar_s["BTCUSDT"]["close"]) * 1.0001
    run = Runner3(book, svc, store, ListNotifier(), SYMS, lambda: t0 + FIVE + 9_000,
                  lambda: {sym: (float(b["close"]) * 0.9999, float(b["close"]) * 1.0001) for sym, b in bar_s.items()})

    def minute(k, flat=False):
        out = {}
        for sym, b in bar_s.items():
            o, h, lo, c = (float(b["close"]),) * 4 if (flat or k) else (b["open"], b["high"], b["low"], b["close"])
            out[sym] = Bar(sym, t0 + k * MIN, t0 + (k + 1) * MIN - 1, float(o), float(h), float(lo), float(c),
                           volume=1.0)
        return out
    run.process([(t0 + k * MIN, minute(k), {}) for k in range(5)])
    rows = store.conn.execute("SELECT strategy, symbol, status, atr, data FROM signal_log WHERE strategy = 'REEL_H1'"
                              " AND symbol = 'BTCUSDT'").fetchall()
    assert len(rows) == 1 and rows[0][2] == "SUBMITTED" and rows[0][3] == want["atr14"]
    basis = json.loads(rows[0][4])["reel"]
    assert basis == {k: want[k] for k in ("stop", "swing_low", "atr14", "up_band", "bar_open", "closes")}
    sig = list(book.engines["REEL_H1@5m"].pending)
    assert "BTCUSDT" in {x.symbol for x in sig} and all(signal_problem(x) is None for x in sig)
    run.process([(t0 + 5 * MIN, minute(5, flat=True), {})])
    out = store.conn.execute("SELECT status, reason, symbol FROM outcomes WHERE account_id = 'REEL_H1@5m'").fetchall()
    assert out and "REJECTED" not in {o[0] for o in out} and out[0][0] == "ENTERED"
    p = book.engines["REEL_H1@5m"].position
    lv = {x.symbol: x for x in sig}
    first = lv[out[0][2]]
    assert p.symbol == out[0][2] and p.stop_price == first.stop_price and p.tp_price == first.tp_price
    if out[0][2] == "BTCUSDT":
        assert p.stop_price == want["stop"] and p.tp_price == want["up_band"]
        assert p.entry_price == pytest.approx(ask * (1 + S.slippage_frac))


# ------------------------------------------------------------------ DeepSeek
class FakeDs:
    BTC_TF_BARS = 100

    class DsError(Exception):
        pass

    class DsUnavailable(DsError):
        pass

    def __init__(self, sides=None, raise_=None):
        self.sides, self.raise_, self.jobs = sides or {}, raise_, []
        self.notes = {}                      # symbol -> the problems a computed (ready) coin reports

    def defs_for(self, tf):
        return SS.ds_names(tf)

    def verify(self):
        return {"lib_c.py": "x"}

    def ds_job(self, job):
        self.jobs.append(job)
        if self.raise_ is not None:
            raise self.raise_
        sym, tf, boundary = job[:3]
        return {"symbol": sym, "tf": tf, "ready": True, "bar_open": boundary - SS.TF_MS[tf], "close": 1.0,
                "atr": 0.5, "sides": dict(self.sides.get(sym, {})), "errors": list(self.notes.get(sym, []))}


@pytest.fixture
def fake_ds(monkeypatch):
    """Route the service's DeepSeek module (and the worker ``ds_last``) to a fake (a forked Pool worker inherits it)."""
    import sys

    def install(ds):
        monkeypatch.setitem(sys.modules, "paperbot._fake_dssig", ds)
        monkeypatch.setitem(SS.GROUP_MODULES, "ds200", "._fake_dssig")
        return ds
    return install


def svc_ds(**kw):
    opts = dict(lib=FakeLib(), procs=1, trade_tfs=C.V3_TRADE_TFS, record_tfs=(), ds_tfs=C.DS200_TFS)
    opts.update(kw)
    return SS.SignalService(SYMS, (), {"15m": 0.0}, **opts)


def test_deepseek_rows_and_signals(fake_ds):
    ds = fake_ds(FakeDs({"BTCUSDT": {"F9_FVG": 1, "F1_RSI_DIV": -1}, "ETHUSDT": {"F15_ASIA_BRK": 1}}))
    svc = svc_ds()
    fill_hist(svc, B15, 50)
    rows, subs, rep = svc.compute_ds(B15, "15m", lambda: B15 + 30_000,
                                     lambda: {"BTCUSDT": (99.0, 101.0), "ETHUSDT": (98.0, 102.0)})
    assert [(r["strategy"], r["symbol"], r["side"], r["status"]) for r in rows] == [
        ("F1_RSI_DIV", "BTCUSDT", -1, "SUBMITTED"), ("F9_FVG", "BTCUSDT", 1, "SUBMITTED"),
        ("F15_ASIA_BRK", "ETHUSDT", 1, "SUBMITTED")]                        # PREREG order per coin
    assert all(r["data"]["group"] == "ds200" and r["timeframe"] == "15m" for r in rows)
    sig = dict(subs)["F1_RSI_DIV@15m"]
    assert sig.meta["stop_dist"] == 2.0 * 0.5 and sig.meta["ref_price"] == 99.0 and sig.tier == "best"
    assert sig.stop_price == 0.0 and sig.tp_price is None and sig.ts == B15 - 1
    from paperbot import levrule
    assert levrule.signal_group(sig)["group"] == "normal"                   # no strength definitions: always normal
    # every coin's job carries its own window; XRP-like record symbols are never sent; BTC gets no BTC context
    assert [j[0] for j in ds.jobs] == list(SYMS) and ds.jobs[0][9] is None and ds.jobs[1][9] is not None
    rows, subs, _ = svc.compute_ds(B15, "15m", lambda: B15 + 181_000, lambda: {"BTCUSDT": (99.0, 101.0)})
    assert {r["status"] for r in rows} == {"LATE"} and subs == []
    rows, subs, _ = svc.compute_ds(B15, "15m", lambda: B15 + 1_000, lambda: {})
    assert {r["status"] for r in rows} == {"NO_PRICE"}
    assert svc.compute_ds(B15, "5m", lambda: 0, lambda: {}) == ([], [], [])
    # 4h: only the 39 four-hour definitions are read, the five session definitions never
    ds.sides = {"BTCUSDT": {"F15_ASIA_BRK": 1, "F15_ORB": 1}}
    b4 = B15 - B15 % 14_400_000
    fill_hist(svc, b4, 50)
    rows, _, _ = svc.compute_ds(b4, "4h", lambda: b4 + 1_000, lambda: {"BTCUSDT": (99.0, 101.0)})
    assert [r["strategy"] for r in rows] == ["F15_ORB"]


def test_deepseek_errors_and_refusal_stay_in_the_group(fake_ds, tmp_path):
    ds = fake_ds(FakeDs(raise_=FakeDs.DsError("lib_c broke")))
    svc = svc_ds()
    fill_hist(svc, B15, 50)
    rows, subs, rep = svc.compute_ds(B15, "15m", lambda: B15, lambda: {})
    assert rows == [] and subs == [] and all(r["errors"] == ["DsError: lib_c broke"] for r in rep[:len(SYMS)])
    assert svc.refused == {}
    ds.raise_ = FakeDs.DsUnavailable("pin mismatch")
    note = ListNotifier()
    store, book = book_of(tmp_path, [{"strategy": "F9_FVG", "timeframe": "15m", "kind": "ds200"}])
    run = Runner3(book, svc, store, note, SYMS, lambda: B15 + 1_000, lambda: {})
    svc.compute = lambda b, tf, now, bk: ([], [], [])
    run._signals(B15)
    run._signals(B15)
    assert svc.refused["ds200"].startswith("DsUnavailable: pin mismatch")
    assert [lvl for lvl, t in note.messages if "signal code refused" in t] == ["CRITICAL"]
    n = len(ds.jobs)
    assert svc.compute_ds(B15, "15m", lambda: B15, lambda: {}) == ([], [], []) and len(ds.jobs) == n   # no more jobs


def _sleepy(job):
    import time
    time.sleep(5)
    return {}


@pytest.mark.skipif(os.cpu_count() is None or os.cpu_count() < 2, reason="needs processes")
def test_deepseek_timeout_after_the_core_submits(tmp_path, monkeypatch, fake_ds):
    """A hung DeepSeek worker: the core group's signals of the boundary are SUBMITTED (before the DeepSeek map
    starts), the DeepSeek map gives up after its own timeout with its own error class and message, the pool is
    replaced and the extras' hook is told the boundary timed out."""
    fake_ds(FakeDs())
    monkeypatch.setattr(SS, "ds_last", _sleepy)
    svc = SS.SignalService(SYMS, (), {}, lib=FakeLib(), procs=2, trade_tfs=C.V3_TRADE_TFS, record_tfs=(),
                           ds_tfs=C.DS200_TFS, ds_timeout_s=0.5)
    fill_hist(svc, B15, 50)
    svc._jobs = lambda b, tf: []
    svc._map = lambda jobs: [{"symbol": "BTCUSDT", "tf": "15m", "ready": True, "close": 100.0, "atr": 1.0,
                              "sides": {"A": 1}, "errors": []}]
    store, book = book_of(tmp_path, [{"strategy": "A", "timeframe": "15m", "kind": "strategy"},
                                     {"strategy": "F9_FVG", "timeframe": "15m", "kind": "ds200"}])
    note = ListNotifier()
    hook = []
    run = Runner3(book, svc, store, note, SYMS, lambda: B15 + 2_000, lambda: {"BTCUSDT": (99.0, 101.0)})
    run.post_boundary = lambda b, sub, to: hook.append(([a for a, _ in sub], to))
    try:
        run._signals(B15)
    finally:
        svc.close()
    assert hook == [(["A@15m"], True)] and len(book.engines["A@15m"].pending) == 1
    assert store.conn.execute("SELECT strategy, status FROM signal_log").fetchall() == [("A", "SUBMITTED")]
    assert run.ds_timeouts == 1 and svc.ds_timeouts == 1 and svc.pool_restarts == 1 and run.signal_timeouts == 0
    warn = [t for lvl, t in note.messages if lvl == "WARN"]
    assert warn == [f"[ds200] DeepSeek signal workers timed out after 0s; DeepSeek signals skipped at {B15} for 15m"]
    assert re.match(SS.DS_TIMEOUT_RE, warn[0]) and "did not answer within" not in warn[0]
    run._health(B15 + 5_000)
    h = store.get_state("health")[1]
    assert h["ds_timeouts"] == 1 and h["signal_timeouts"] == 0 and h["ds_last"] == {}
    assert ds_record(store, B15)["15m"][str(B15)] == {"s": "timeout"}


def test_deepseek_unexpected_failure_is_fenced(tmp_path, fake_ds):
    fake_ds(FakeDs())
    svc = svc_ds()
    fill_hist(svc, B15, 50)
    svc._jobs = lambda b, tf: []
    svc._map = lambda jobs: [{"symbol": "BTCUSDT", "tf": "15m", "ready": True, "close": 100.0, "atr": 1.0,
                              "sides": {"A": 1}, "errors": []}]
    svc.compute_ds = lambda *a: (_ for _ in ()).throw(KeyError("bug"))
    store, book = book_of(tmp_path, [{"strategy": "A", "timeframe": "15m", "kind": "strategy"}])
    run = Runner3(book, svc, store, ListNotifier(), SYMS, lambda: B15 + 2_000, lambda: {"BTCUSDT": (99.0, 101.0)})
    run._signals(B15)
    assert len(book.engines["A@15m"].pending) == 1 and run.group_errors == 1


def test_deepseek_btc_context_is_the_full_windows_f14_bars(fake_ds):
    """The job's BTC arrays are trimmed to the last (BTC_TF_BARS + 2) chart bars' worth of 5m bars; what dssig reads
    from them (5m bars closed by the boundary, opened at or after max(coin window start, boundary - BTC_TF_BARS
    bars)) equals what it reads from the whole window, also with a gap in BTC's bars."""
    from paperbot import dssig
    fake_ds(FakeDs())
    svc = SS.SignalService(("BTCUSDT", "ETHUSDT"), (), {}, lib=FakeLib(), procs=1, trade_tfs=(), record_tfs=(),
                           ds_tfs=C.DS200_TFS)
    b = B15 - B15 % 14_400_000
    n = C.DS_WINDOW_5M["4h"] + 500
    fill_hist(svc, b, n, ("ETHUSDT",))
    btc = [(b - FIVE * (n - i), 1.0 + i, 2.0 + i, 0.5 + i, 1.5 + i, 1.0) for i in range(n)]
    del btc[-700:-650]                                                       # a gap inside the F14 range
    svc.bootstrap("BTCUSDT", btc)
    svc._module("ds200")
    for tf in C.DS200_TFS:
        bb = b                                                               # a 4h boundary: every DS timeframe's
        jobs = {j[0]: j for j in svc._ds_jobs(bb, tf)}
        eth = jobs["ETHUSDT"]
        assert len(eth[3]) == C.DS_WINDOW_5M[tf] and jobs["BTCUSDT"][9] is None
        full = np.array(list(svc.hist["BTCUSDT"])[-C.DS_WINDOW_5M[tf]:], dtype=float)
        full = (full[:, 0].astype(np.int64),) + tuple(full[:, k] for k in range(1, 6))
        span = SS.TF_MS[tf]
        since = max(int(eth[3][0]), bb - dssig.BTC_TF_BARS * span)
        a, z = dssig._closed(eth[9], bb, since=since), dssig._closed(full, bb, since=since)
        assert all(np.array_equal(x, y) for x, y in zip(a, z)) and len(a[0]) >= dssig.BTC_TF_BARS * span // FIVE - 50


def test_real_deepseek_job_through_the_service_equals_dssig():
    """The wiring on the real pinned lib_c (15m, two coins): compute_ds gives exactly the sides dssig.ds_job gives on
    the coin's window with BTC's whole window as context."""
    from paperbot import dssig
    svc = SS.SignalService(("BTCUSDT", "ETHUSDT"), (), {}, lib=FakeLib(), procs=1, trade_tfs=(), record_tfs=(),
                           ds_tfs=("15m",))
    assert "lib_c.py" in svc.verify_groups()["ds200"] and svc.refused == {}
    n = C.DS_WINDOW_5M["15m"] + 20
    arr = {}
    for k, sym in enumerate(("BTCUSDT", "ETHUSDT")):
        df = _series(40 + k, n, B15)
        arr[sym] = np.column_stack([df["ts"].to_numpy(float), df[["open", "high", "low", "close"]].to_numpy(),
                                    np.full(n, 2.0)])
        svc.bootstrap(sym, [tuple(r) for r in arr[sym]])
    rows, subs, rep = svc.compute_ds(B15, "15m", lambda: B15 + 5_000, lambda: {"BTCUSDT": (1.0, 2.0),
                                                                               "ETHUSDT": (1.0, 2.0)})
    w = C.DS_WINDOW_5M["15m"]
    cols = {s: (a[-w:, 0].astype(np.int64),) + tuple(a[-w:, k] for k in range(1, 6)) for s, a in arr.items()}
    for sym in ("BTCUSDT", "ETHUSDT"):
        direct = dssig.ds_job((sym, "15m", B15) + cols[sym] + (None if sym == "BTCUSDT" else cols["BTCUSDT"],))
        got = {r["strategy"]: r["side"] for r in rows if r["symbol"] == sym}
        assert direct["ready"] and got == direct["sides"], sym
        r = next(x for x in rep if x.get("symbol") == sym)
        assert r["sides"] == direct["sides"] and r["atr"] == direct["atr"]


# ------------------------------------------------------------------ cmd_run: the database checks and the start
class CmdFakeRest:
    api_key = api_secret = None

    def server_time(self):
        return B15 + 7 * MIN

    def exchange_info(self, syms):
        return {s: {"qty_step": 0.001, "min_notional": 5.0} for s in syms}

    def klines(self, *a, **k):
        return []


class CmdFakeService:
    made = []
    refuse = None

    def __init__(self, symbols, record_only, rates, procs=4, **kw):
        self.symbols = list(symbols) + list(record_only)
        self.kw, self.lib, self.windows = kw, None, {"15m": 10}
        self.ds_tfs, self.five_m = tuple(kw.get("ds_tfs", ())), bool(kw.get("five_m"))
        self.keep = 120_000
        self.hist = {s: deque(maxlen=self.keep) for s in self.symbols}
        self.refused, self._q = {}, []
        CmdFakeService.made.append(self)

    def verify_groups(self):
        out = {"ds200": {"lib_c.py": "x"}, "reel": {"lib_reel5m.py": "y"}}
        if self.refuse:
            self.refused[self.refuse] = "pin mismatch"
            self._q.append((self.refuse, "pin mismatch"))
            out[self.refuse] = {"refused": "pin mismatch"}
        return out

    def pop_refusals(self):
        q, self._q = self._q, []
        return q

    def bootstrap(self, s, rows):
        pass

    def close(self):
        pass


CORE36 = [f"S{k:02d}" for k in range(36)]


@pytest.fixture
def cmd(monkeypatch):
    import paperbot.live3 as L3
    sent = []

    class Note(ListNotifier):
        def send(self, level, text):
            sent.append((level, text))

    calls = {"extras": 0}

    def extras(*a):
        calls["extras"] += 1
        from paperbot.accounts import hold_others
        return None, hold_others
    monkeypatch.setattr(L3, "_rest", CmdFakeRest)
    monkeypatch.setattr(L3, "_notifier", Note)
    monkeypatch.setattr(L3, "start_extras", extras)
    monkeypatch.setattr(L3, "LiveFeed", lambda *a, **k: type("Feed", (), {"skew_ms": 0, "poll": lambda self: []})())
    monkeypatch.delenv("DEADMAN_URL", raising=False)
    monkeypatch.setattr(SS, "SignalService", CmdFakeService)
    monkeypatch.setattr(SS, "strategy_names", lambda lib: list(CORE36))
    CmdFakeService.made, CmdFakeService.refuse = [], None

    def run(db, *extra):
        return L3.main(["run", "--db", str(db), "--allow-example-brackets", "--max-polls", "0", *extra])
    run.sent, run.calls = sent, calls
    return run


def test_cmd_run_opens_the_331_accounts_and_resumes(tmp_path, cmd):
    from paperbot.reel_engine import ReelEngine
    db = tmp_path / "paper.db"
    assert cmd(db) == 0
    svc = CmdFakeService.made[-1]
    assert svc.kw["ds_tfs"] == C.DS200_TFS and svc.kw["five_m"] is True and svc.kw["flip5m"] == C.V4_FLIP5M
    assert svc.kw["max_delay_ms_5m"] == C.FIVE_M_MAX_DELAY_MS == 60_000
    banner = [t for lvl, t in cmd.sent if " accounts (" in t]
    assert banner == [f"paper v4 started: 331 accounts (core 144, ds200 171, reel 1, flip 15), brackets: "
                      f"{banner[0].split('brackets: ')[1].split(', taker')[0]}, taker fee {S.taker_fee:.4%}"]
    from paperbot.notify import ko
    assert "331" in ko(banner[0]) and "모의 v4" in ko(banner[0])
    st = Store3(str(db))
    rows = st.accounts()
    assert len(rows) == C.V4_ACCOUNTS == 331 and {r["settings_version"] for r in rows} == {"paper-v4"}
    assert sorted(r["account_id"] for r in rows if r["timeframe"] == "5m") == \
        ["RANDOM_1@5m", "RANDOM_2@5m", "RANDOM_3@5m", "REEL_H1@5m"]
    run = st.get_state("run")[1]
    assert run["settings"] == "paper-v4" and run["groups"] == {"core": 144, "ds200": 171, "reel": 1, "flip": 15}
    assert st.last_run()["group_locks"] == {"ds200": {"lib_c.py": "x"}, "reel": {"lib_reel5m.py": "y"}}
    # a saved state, then a restart: resumed, nothing held, the reel and the 5m flips on their engine
    book2 = AccountBook(S, {s: Brackets.example() for s in SYMS}, st, ListNotifier())
    book2.open_accounts(C.v4_account_defs(CORE36), 0)
    book2.last_ts = B15 + 6 * MIN
    book2.save(B15 + 6 * MIN)
    st.close()
    cmd.sent.clear()
    assert cmd(db) == 0
    assert [t for lvl, t in cmd.sent if " accounts (" in t][0].startswith("paper v4 resumed: 331 accounts (core 144")
    st = Store3(str(db))
    book3 = AccountBook(S, {s: Brackets.example() for s in SYMS}, st, ListNotifier())
    assert book3.load()
    assert not [a for a, e in book3.engines.items() if isinstance(e, HeldEngine)]
    assert type(book3.engines["REEL_H1@5m"]) is ReelEngine and type(book3.engines["RANDOM_1@5m"]) is ReelEngine
    assert st.get_state("run")[1]["resume_from"] == B15 + 7 * MIN
    st.close()


def test_cmd_run_refuses_a_v3_database(tmp_path, cmd):
    from paperbot.live3 import account_defs
    db = tmp_path / "v3.db"
    st = Store3(str(db))
    v3 = C.v3_settings(version="paper-v3")
    book = AccountBook(v3, {s: Brackets.example() for s in SYMS}, st, ListNotifier())
    book.open_accounts(account_defs(CORE36, C.V3_TRADE_TFS), 0)
    book.save(B15)
    st.put_state("run", 0, {"settings": "paper-v3", "initial_equity": 5000.0})
    st.commit()
    st.close()
    with pytest.raises(SystemExit, match="paper-v3"):
        cmd(db)
    st = Store3(str(db))
    assert len(st.accounts()) == 156 and st.get_state("run")[1]["settings"] == "paper-v3"    # untouched
    st.close()


def test_cmd_run_refuses_a_database_with_another_account_set(tmp_path, cmd):
    db = tmp_path / "x.db"
    st = Store3(str(db))
    book = AccountBook(S, {s: Brackets.example() for s in SYMS}, st, ListNotifier())
    defs = C.v4_account_defs(CORE36)
    book.open_accounts([d for d in defs if d["strategy"] != "F9_FVG"], 0)              # four DeepSeek accounts short
    st.close()
    with pytest.raises(SystemExit, match="4 missing"):
        cmd(db)
    db2 = tmp_path / "y.db"
    st = Store3(str(db2))
    book = AccountBook(S, {s: Brackets.example() for s in SYMS}, st, ListNotifier())
    flip5 = [dict(d, data={**d["data"], "exits": "house"}) if d["timeframe"] == "5m" and d["kind"] == "random"
             else d for d in defs]                                                    # 5m flips without the reel exits
    book.open_accounts(flip5, 0)
    st.close()
    with pytest.raises(SystemExit, match="3 with another kind / group / exit rule"):
        cmd(db2)


def test_cmd_run_a_refused_group_starts_with_one_critical_line(tmp_path, cmd):
    CmdFakeService.refuse = "reel"
    assert cmd(tmp_path / "r.db") == 0
    crit = [t for lvl, t in cmd.sent if lvl == "CRITICAL"]
    assert crit == ["[reel] signal code refused, this group's signals stop (the other groups run on): pin mismatch"]
    st = Store3(str(tmp_path / "r.db"))
    assert st.get_state("run")[1]["groups_refused"] == {"reel": "pin mismatch"}
    assert st.last_run()["group_locks"]["reel"] == {"refused": "pin mismatch"}
    assert len(st.accounts()) == 331                                                   # every account still opens
    st.close()


def test_cmd_run_staging_flags(tmp_path, cmd, monkeypatch, capsys):
    import paperbot.live3 as L3
    monkeypatch.setattr(L3, "_notifier", lambda: (_ for _ in ()).throw(AssertionError("telegram used")))
    assert cmd(tmp_path / "s.db", "--no-extras", "--no-telegram") == 0
    assert cmd.calls["extras"] == 0 and "paper v4 started: 331 accounts" in capsys.readouterr().err
    st = Store3(str(tmp_path / "s.db"))
    assert st.get_state("run")[1]["extras"] == "off (--no-extras)"
    st.close()


def test_history_check_and_options():
    from paperbot.live3 import check_history, service_options
    from paperbot.newlab_live import NEWLAB_WINDOW_5M
    svc = SS.SignalService(SYMS, ("XRPUSDT",), {}, procs=1, **service_options())
    assert svc.keep >= max(max(C.DS_WINDOW_5M.values()), max(NEWLAB_WINDOW_5M.values()), C.REEL_WINDOW_5M)
    check_history(svc)
    small = SS.SignalService(SYMS, (), {}, lib=FakeLib(), procs=1, trade_tfs=("15m",), record_tfs=(),
                             five_m=True)
    with pytest.raises(SystemExit, match="signal history keeps"):
        check_history(small)


# ------------------------------------------------------------------ restart: open, trade, save, rebuild
class GroupsService:
    """A service with the three paths: the reel fires at the first 5m-only boundary, DeepSeek F9_FVG at the first 15m
    boundary (after the core map, which gives nothing)."""

    def __init__(self, t0):
        self.t0, self.last, self.calls = t0, {}, []

    def add_5m(self, b):
        self.last[b.symbol] = b.open_time + FIVE

    def complete(self, boundary):
        return all(self.last.get(s) == boundary for s in SYMS)

    def due(self, boundary):
        return ["15m"] if boundary % 900_000 == 0 else []

    def due_5m(self, boundary):
        return True

    def due_ds(self, boundary):
        return ["15m"] if boundary % 900_000 == 0 else []

    def compute(self, boundary, tf, now_ms, book):
        self.calls.append(("core", boundary))
        return [], [], []

    def compute_5m(self, boundary, now_ms, book):
        self.calls.append(("5m", boundary))
        if boundary != self.t0 + FIVE:
            return [], [], []
        p = PRICE["BTCUSDT"]
        lv = levels(boundary - FIVE, p, stop=p - 1.0, up=p + 1.0)
        sig = Signal(ts=boundary - 1, symbol="BTCUSDT", timeframe="5m", strategy_id="REEL_H1", side=1,
                     stop_price=lv["stop"], tier="best", tp_price=lv["up_band"], atr=lv["atr14"],
                     meta={"ref_price": p + 0.01, "ref_time": now_ms(), "delay_ms": 9_000, "account": "REEL_H1@5m",
                           "ctx": {}, "reel": {k: lv[k] for k in ("stop", "swing_low", "atr14", "up_band", "closes")}})
        return [], [("REEL_H1@5m", sig)], []

    def compute_ds(self, boundary, tf, now_ms, book):
        self.calls.append(("ds", boundary))
        p = PRICE["ETHUSDT"]
        sig = Signal(ts=boundary - 1, symbol="ETHUSDT", timeframe="15m", strategy_id="F9_FVG", side=1, stop_price=0.0,
                     tier="best", atr=0.2, meta={"stop_dist": 0.4, "ref_price": p + 0.01, "ref_time": now_ms(),
                                                 "delay_ms": 9_000, "account": "F9_FVG@15m", "ctx": {}})
        return [], [("F9_FVG@15m", sig)], []


def test_restart_rebuilds_every_v4_engine_with_its_position(tmp_path):
    from paperbot.engine import PaperEngine
    from paperbot.live3 import start_extras, v4_defs
    from paperbot.reel_engine import STATE_KEY, ReelEngine
    db = tmp_path / "rs.db"
    store = Store3(str(db))
    book = AccountBook(S, {s: Brackets.example() for s in SYMS}, store, ListNotifier())
    book.open_accounts(v4_defs(CORE36), 0)
    t0 = B15 + 900_000 - 2 * FIVE                         # t0 + 5m: 5m only; t0 + 10m: a 15m boundary
    svc = GroupsService(t0)
    run = Runner3(book, svc, store, ListNotifier(), SYMS, lambda: t0 + 9_000, lambda: {})
    run.process([(t0 + k * MIN, one_min(t0 + k * MIN), {}) for k in range(12)])
    assert ("5m", t0 + FIVE) in svc.calls and svc.calls.index(("core", t0 + 2 * FIVE)) < \
        svc.calls.index(("ds", t0 + 2 * FIVE))            # DeepSeek after the core map
    assert svc.calls.index(("5m", t0 + 2 * FIVE)) < svc.calls.index(("core", t0 + 2 * FIVE))   # 5m path first
    reel, ds = book.engines["REEL_H1@5m"], book.engines["F9_FVG@15m"]
    assert reel.position is not None and reel.position.signal.meta[STATE_KEY]["bucket"] == t0 + 2 * FIVE
    assert ds.position is not None and ds.position.stop_price == pytest.approx(PRICE["ETHUSDT"] + 0.01 - 0.4)
    store.close()
    store = Store3(str(db))
    note = ListNotifier()
    ext, make_of = start_extras(store, note, str(db), S)
    book2 = AccountBook(S, {s: Brackets.example() for s in SYMS}, store, note)
    assert book2.load(make_of=make_of)
    assert len(book2.engines) == 331 and not [a for a, e in book2.engines.items() if isinstance(e, HeldEngine)]
    assert type(book2.engines["REEL_H1@5m"]) is ReelEngine and type(book2.engines["F9_FVG@15m"]) is PaperEngine
    r2 = book2.engines["REEL_H1@5m"].position
    assert r2 is not None and r2.tp_price == reel.position.tp_price and r2.stop_price == reel.position.stop_price
    assert r2.signal.meta[STATE_KEY] == reel.position.signal.meta[STATE_KEY]
    assert book2.engines["F9_FVG@15m"].position.entry_price == ds.position.entry_price
    for aid in ("S00@15m", "F15_ORB@4h", "RANDOM_1@5m", "RANDOM_2@1h"):
        e = book2.engines[aid]
        n = len(e.pending)
        tf = aid.split("@")[1]
        e.submit(Signal(ts=t0, symbol="SOLUSDT", timeframe=tf, strategy_id=aid.split("@")[0], side=1,
                        stop_price=0.0, meta={"stop_dist": 1.0}))
        assert len(e.pending) == n + 1, aid
    assert not [m for m in note.messages if m[0] == "CRITICAL"]


# ------------------------------------------------------------------ G27: the v4 groups' frozen alert texts
def test_v4_alert_texts_are_frozen_and_never_read_as_the_core_groups():
    """The exact texts (sigservice.py is frozen at day 0; notify.Router, agents/triggers, dscheck and the dashboards
    match them), each matched by its own pattern only, and none of them read as a core-group line: no "did not answer
    within" (triggers.INCIDENT_ALERTS signal_timeout, a substring), no core timeout / error prefix (notify._TIMEOUT,
    the dashboards' regexes), no "[id@tf] " account prefix (the digest's per-account lines)."""
    from paperbot import notify
    texts = {
        "DS_TIMEOUT": (SS.DS_TIMEOUT_TEXT.format(secs="60", boundary=B15, tfs="15m, 30m"),
                       f"[ds200] DeepSeek signal workers timed out after 60s; DeepSeek signals skipped at {B15} "
                       "for 15m, 30m"),
        "DS_ERROR": (SS.DS_ERROR_TEXT.format(tf="1h", symbol="SOLUSDT", error="DsError: lib_c broke"),
                     "[ds200] DeepSeek signal error 1h SOLUSDT: DsError: lib_c broke"),
        "DS_FAILED": (SS.DS_FAILED_TEXT.format(boundary=B15, error="KeyError: 'x'"),
                      f"[ds200] DeepSeek signals failed at {B15} (KeyError: 'x'); the other groups run on"),
        "REEL_ERROR": (SS.REEL_ERROR_TEXT.format(tf="5m", symbol="BTCUSDT", error="reel ReelError: boom"),
                       "[reel] 5m signal error 5m BTCUSDT: reel ReelError: boom"),
        "REEL_FAILED": (SS.REEL_FAILED_TEXT.format(boundary=B15, error="RuntimeError: bug"),
                        f"[reel] 5m signals (reel and 5m coin flips) failed at {B15} (RuntimeError: bug); "
                        "the other groups run on"),
        "REFUSED": (SS.REFUSED_TEXT.format(group="ds200", why="DsUnavailable: pin mismatch"),
                    "[ds200] signal code refused, this group's signals stop (the other groups run on): "
                    "DsUnavailable: pin mismatch"),
    }
    pats = {k: getattr(SS, f"{k}_RE") for k in texts}
    for k, (got, want) in texts.items():
        assert got == want, k
        assert [j for j, p in pats.items() if re.match(p, got)] == [k], k
        assert "did not answer within" not in got and not got.startswith(("signal workers", "signal error"))
        assert notify._TIMEOUT.match(got) is None and notify.count_only_group(got) is None
    assert re.match(pats["DS_TIMEOUT"], texts["DS_TIMEOUT"][0]).groups() == ("60", str(B15), "15m, 30m")
    # an error part with newlines and any length stays on one line, so the anchored patterns still match
    long = SS.DS_FAILED_TEXT.format(boundary=B15, error=SS.one_line("ValueError: a\nb\tc " + "x" * 500, 200))
    assert re.match(pats["DS_FAILED"], long) and "\n" not in long


# ------------------------------------------------------------------ G10: the v4 rows carry the chart context
def test_deepseek_rows_carry_the_chart_context_a_core_row_gets(fake_ds, monkeypatch):
    """A DeepSeek row (and its Signal) carries the chart context of its coin's signal bar and the S/R marks of its
    side: exactly what a core row of the same coin, timeframe, bar and side carries (the core worker
    ``compute_last`` on the core job ``_jobs`` builds, older bars for the 4h levels included), without strength
    numbers, on every DeepSeek timeframe; each row and Signal holds its own copy; a coin without a DeepSeek signal
    costs no description."""
    fake_ds(FakeDs({"BTCUSDT": {"F9_FVG": 1, "F17_Z": -1}, "ETHUSDT": {"F1_RSI_DIV": -1}}))
    lib = SS._lib()
    syms = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    svc = SS.SignalService(syms, (), {}, lib=FakeLib(), procs=1, trade_tfs=(), record_tfs=(), ds_tfs=C.DS200_TFS)
    core_svc = SS.SignalService(syms, (), {}, lib=lib, procs=1, trade_tfs=C.V3_TRADE_TFS, record_tfs=(),
                                ds_tfs=C.DS200_TFS)
    b = B15 - B15 % 14_400_000                                   # a 4h boundary: every DeepSeek timeframe is due
    n = SS._marks_window(lib, "4h") + 500                        # more than the 4h levels read
    assert n > SS.window_5m(lib, "4h")
    for k, sym in enumerate(syms):
        df = _series(60 + k, n, b)
        rows = [tuple(r) + (1.0 + (i % 7),) for i, r in enumerate(df.itertuples(index=False))]
        svc.bootstrap(sym, rows)
        core_svc.bootstrap(sym, rows)
    fired = {}
    monkeypatch.setattr(lib, "compute_signals", lambda frames, tf, names, strict=False:
                        {names[0]: {s: np.array([1], dtype=np.int8) for s in frames}})   # every core coin fires
    from paperbot import levrule
    for tf in C.DS200_TFS:
        rows, subs, rep = svc.compute_ds(b, tf, lambda: b + 5_000, lambda: {s: (99.0, 101.0) for s in syms})
        assert {r["symbol"] for r in rows} == {"BTCUSDT", "ETHUSDT"}
        sol = next(r for r in rep if r["symbol"] == "SOLUSDT")
        assert "ctx" not in sol and "marks" not in sol                                   # no signal: no description
        jobs = {j[0]: j for j in core_svc._jobs(b, tf)}
        for sym in ("BTCUSDT", "ETHUSDT"):
            core = SS.compute_last(jobs[sym])
            assert core["ready"] and core["ctx"].get("regime") and core["ctx"]["tf"] == tf and "adx" in core["ctx"]
            assert "error" not in core["marks"]["sr"]
            mine = [r for r in rows if r["symbol"] == sym]
            for r in mine:
                want = SS.attach(core["ctx"], core["marks"], r["strategy"], r["side"])  # the core row's ctx, this side
                assert "strength" not in want and want["sr"] == core["marks"]["sr"][str(r["side"])]
                assert r["data"]["ctx"] == want and "ctx_error" not in r["data"] and r["data"]["group"] == "ds200"
                sig = dict(subs)[f"{r['strategy']}@{tf}"]
                assert sig.meta["ctx"] == want and sig.meta["ctx"] is not r["data"]["ctx"]
                assert levrule.signal_group(sig)["group"] == "normal"
                fired[(tf, r["strategy"])] = True
            if len(mine) > 1:
                assert mine[0]["data"]["ctx"] is not mine[1]["data"]["ctx"]
                assert mine[0]["data"]["ctx"]["sr"] != mine[1]["data"]["ctx"]["sr"]      # long and short sides
    assert len(fired) == 3 * len(C.DS200_TFS)


def test_deepseek_context_failure_never_blocks_the_signal(fake_ds, monkeypatch):
    """A failing chart context or S/R computation leaves the signal and the other description intact."""
    from paperbot import entry_marks
    fake_ds(FakeDs({"BTCUSDT": {"F9_FVG": 1}}))
    svc = svc_ds()
    fill_hist(svc, B15, 50)
    with monkeypatch.context() as mp:
        mp.setattr(SS, "chart_context", lambda *a, **k: (_ for _ in ()).throw(ValueError("ctx\nbroke")))
        rows, subs, rep = svc.compute_ds(B15, "15m", lambda: B15 + 1_000, lambda: {"BTCUSDT": (99.0, 101.0)})
    assert [(r["strategy"], r["status"]) for r in rows] == [("F9_FVG", "SUBMITTED")] and len(subs) == 1
    assert rows[0]["data"]["ctx_error"] == "ValueError: ctx broke" and rep[0]["errors"] == []
    assert set(rows[0]["data"]["ctx"]) == {"sr"} and subs[0][1].meta["ctx"] == rows[0]["data"]["ctx"]
    with monkeypatch.context() as mp:
        mp.setattr(entry_marks, "marks", lambda *a, **k: (_ for _ in ()).throw(KeyError("sr")))
        rows, subs, rep = svc.compute_ds(B15, "15m", lambda: B15 + 1_000, lambda: {"BTCUSDT": (99.0, 101.0)})
    assert [(r["strategy"], r["status"]) for r in rows] == [("F9_FVG", "SUBMITTED")] and len(subs) == 1
    ctx = rows[0]["data"]["ctx"]
    assert ctx["marks_error"] == "KeyError: 'sr'" and "sr" not in ctx and ctx["tf"] == "15m"
    assert "ctx_error" not in rows[0]["data"]


def test_5m_rows_carry_the_chart_context(tmp_path):
    """The reel's and the 5m coin flips' rows and Signals carry the chart context of the 5m signal bar (chart_context
    on the reel window's 5m bars, higher timeframe 30m) and its long side's S/R marks (the own-exit loss cards read
    them); a service whose library cannot describe the chart still trades, without the chart context and with the
    error."""
    from paperbot.entry_marks import marks
    from paperbot.reel_engine import signal_problem
    lib = SS._lib()
    n = C.REEL_WINDOW_5M + 40
    frames = {s: _series(80 + k, n, B15) for k, s in enumerate(SYMS)}
    fire = float(frames["BTCUSDT"]["close"].iloc[-1])
    for real in (True, False):
        svc = svc_5m(lib=lib if real else FakeLib(), flip5m={"rate": 1.0, "long_only": True})
        svc._mods["reel"] = FakeReel(fire=(fire,))
        for sym, df in frames.items():
            svc.bootstrap(sym, [tuple(r) + (2.0,) for r in df.itertuples(index=False)])
        rows, subs, rep = svc.compute_5m(B15, lambda: B15 + 9_000, lambda: {s: (1.0, 2.0) for s in SYMS})
        assert len(rows) == 1 + 3 * len(SYMS) and {r["status"] for r in rows} == {"SUBMITTED"} and len(subs) == len(rows)
        for sym, df in frames.items():
            w = df.iloc[-C.REEL_WINDOW_5M:]
            df5 = pd.DataFrame({"ts": pd.to_datetime(w["ts"].to_numpy(np.int64), unit="ms", utc=True),
                                "open": w["open"].to_numpy(float), "high": w["high"].to_numpy(float),
                                "low": w["low"].to_numpy(float), "close": w["close"].to_numpy(float),
                                "volume": np.full(len(w), 2.0)})
            mine = [r for r in rows if r["symbol"] == sym]
            assert mine
            if real:
                want = SS.chart_context(lib, sym, df5, df5, "5m")
                assert want["tf"] == "5m" and want["htf"] == "30m" and want.get("regime") and "adx" in want
                sr = marks(df5, "5m", {})["sr"]
                assert "error" not in sr and set(sr["1"]) >= {"floor_px", "breakout", "support_before_stop"}
                want = {**want, "sr": sr["1"]}
                assert all(r["data"]["ctx"] == want and "ctx_error" not in r["data"] for r in mine)
            else:                                                # no chart context; the S/R marks need no library
                assert all("regime" not in r["data"]["ctx"] and r["data"]["ctx_error"] for r in mine)
        for aid, sig in subs:
            row = next(r for r in rows if f"{r['strategy']}@5m" == aid and r["symbol"] == sig.symbol)
            assert sig.meta["ctx"] == row["data"]["ctx"] and sig.meta["ctx"] is not row["data"]["ctx"]
            assert signal_problem(sig) is None


# ------------------------------------------------------------------ the DeepSeek job's record (dscheck)
def ds_record(store, boundary):
    from paperbot.live3 import DS_RUN_KEY
    import time as _t
    got = store.get_state(DS_RUN_KEY + _t.strftime("%Y-%m-%d", _t.gmtime((boundary - 1) // 1000)))
    assert got is not None and got[1]["v"] == 1
    return got[1]["tfs"]


def test_the_deepseek_job_is_recorded_per_boundary_for_dscheck(tmp_path, fake_ds):
    """Per DeepSeek boundary and timeframe: "ran" with the coins the job answered for (so a missing signal_log row of
    such a coin means "no signal") and the others with their reason, "refused", "failed", "incomplete"; one state row
    per UTC day of the bar close (a 00:00 boundary closes the previous day's last bar); a restart adds to the day's
    record; the counters and the frozen error text."""
    from paperbot.live3 import DS_RUN_KEY
    ds = fake_ds(FakeDs({"BTCUSDT": {"F9_FVG": 1}}))
    svc = svc_ds()
    D0 = 20_000 * DAY                                            # 00:00 UTC: every DeepSeek timeframe closes here
    fill_hist(svc, D0, 50)
    svc.compute = lambda b, tf, now, bk: ([], [], [])
    store, book = book_of(tmp_path, [{"strategy": "F9_FVG", "timeframe": "15m", "kind": "ds200"}])
    note = ListNotifier()
    run = Runner3(book, svc, store, note, SYMS, lambda: D0 + 1_000, lambda: {})
    run._signals(D0)
    rec = ds_record(store, D0)
    assert set(rec) == set(C.DS200_TFS)
    assert all(rec[tf] == {str(D0): {"s": "ran", "ok": sorted(SYMS), "no": {}}} for tf in C.DS200_TFS)
    assert store.get_state(DS_RUN_KEY + "2024-10-03") is not None                 # D0 = 2024-10-04 00:00 UTC
    assert store.get_state(DS_RUN_KEY + "2024-10-04") is None                     # its bars close the 3rd
    rows = store.conn.execute("SELECT bar_close, timeframe, strategy, symbol, side FROM signal_log").fetchall()
    assert sorted(rows) == sorted((D0, tf, "F9_FVG", "BTCUSDT", 1) for tf in C.DS200_TFS)
    # one coin's job fails: its reason is recorded, the error line has the frozen text, the counter moves
    b1 = D0 + 900_000
    fill_hist(svc, b1, 50)
    ds.raise_ = FakeDs.DsError("lib_c\nbroke")
    run._signals(b1)
    rec = ds_record(store, b1)
    assert rec["15m"][str(b1)] == {"s": "ran", "ok": [], "no": {s: "DeepSeek error" for s in SYMS}}
    errs = [t for (t,) in store.conn.execute("SELECT text FROM alerts WHERE text LIKE '[ds200]%'")]
    assert errs[0] == "[ds200] DeepSeek signal error 15m BTCUSDT: DsError: lib_c broke" and len(errs) == len(SYMS)
    assert run.ds_errors == len(SYMS) and run.reel_errors == 0 and run.signal_timeouts == 0
    assert ds_record(store, D0)["15m"] == {str(D0): {"s": "ran", "ok": sorted(SYMS), "no": {}}}   # another day
    # the history is incomplete at a boundary: recorded, no job
    b2 = D0 + 2 * 900_000
    n_jobs = len(ds.jobs)
    run._signals(b2)
    assert ds_record(store, b2)["15m"][str(b2)] == {"s": "incomplete"} and len(ds.jobs) == n_jobs
    # a restart: the day's record is read back and added to
    run2 = Runner3(book, svc, store, note, SYMS, lambda: b2 + 1_000, lambda: {})
    fill_hist(svc, b2 + 900_000, 50)
    ds.raise_ = FakeDs.DsUnavailable("pin mismatch")
    run2._signals(b2 + 900_000)
    rec = ds_record(store, b2 + 900_000)
    assert rec["15m"][str(b2 + 900_000)] == {"s": "refused"} and rec["15m"][str(b1)]["s"] == "ran"
    assert [t for lvl, t in note.messages if lvl == "CRITICAL"][0].startswith("[ds200] signal code refused")
    # the DeepSeek path itself fails: "failed" for the timeframes it did not reach, the first failure rings once
    svc2 = svc_ds()
    fill_hist(svc2, D0 + DAY, 50)
    svc2.compute = lambda b, tf, now, bk: ([], [], [])
    svc2.compute_ds = lambda *a: (_ for _ in ()).throw(KeyError("bug"))
    note3 = ListNotifier()
    run3 = Runner3(book, svc2, store, note3, SYMS, lambda: D0 + DAY + 1_000, lambda: {})
    run3._signals(D0 + DAY)
    run3._signals(D0 + DAY)
    rec = ds_record(store, D0 + DAY)                             # the same UTC day as b1, b2 (00:00 closes it)
    assert {tf: rec[tf][str(D0 + DAY)] for tf in C.DS200_TFS} == {tf: {"s": "failed"} for tf in C.DS200_TFS}
    assert rec["15m"][str(b2)] == {"s": "incomplete"} and rec["30m"][str(b2)] == {"s": "incomplete"}
    assert [t for lvl, t in note3.messages] == [f"[ds200] DeepSeek signals failed at {D0 + DAY} (KeyError: 'bug'); "
                                                "the other groups run on"]
    assert run3.group_errors == 2 and run3.ds_errors == 2
    run3._health(D0 + DAY + 2_000)
    h = store.get_state("health")[1]
    assert h["ds_errors"] == 2 and h["reel_errors"] == 0 and h["ds_record_errors"] == 0
    run._health(D0 + DAY + 3_000)
    assert store.get_state("health")[1]["ds_last"] == {tf: D0 for tf in C.DS200_TFS} | {"15m": b1}


def test_the_deepseek_record_keeps_the_problems_of_a_computed_coin(tmp_path, fake_ds):
    """A coin the job computed but that reported a problem (dssig: F14_SMT lost without BTC's bars) is "ok" (its other
    definitions are complete) and its problem is in "err", so dscheck can tell a lost F14_SMT from a missing row;
    the problem is also one DS_ERROR_TEXT line (counted in "ds_errors", never in "signal_timeouts")."""
    ds = fake_ds(FakeDs({"BTCUSDT": {"F9_FVG": 1}}))
    ds.notes = {"ETHUSDT": ["F14_SMT: no BTC bars"]}
    svc = svc_ds()
    fill_hist(svc, B15, 50)
    svc.compute = lambda b, tf, now, bk: ([], [], [])
    store, book = book_of(tmp_path, [{"strategy": "F9_FVG", "timeframe": "15m", "kind": "ds200"}])
    run = Runner3(book, svc, store, ListNotifier(), SYMS, lambda: B15 + 1_000, lambda: {})
    run._signals(B15)
    assert ds_record(store, B15) == {"15m": {str(B15): {"s": "ran", "ok": sorted(SYMS), "no": {},
                                                       "err": {"ETHUSDT": "F14_SMT: no BTC bars"}}}}
    errs = [t for (t,) in store.conn.execute("SELECT text FROM alerts WHERE text LIKE '[ds200]%'")]
    assert errs == ["[ds200] DeepSeek signal error 15m ETHUSDT: F14_SMT: no BTC bars"]
    assert re.match(SS.DS_ERROR_RE, errs[0]).groups() == ("15m", "ETHUSDT", "F14_SMT: no BTC bars")
    assert run.ds_errors == 1 and run.signal_timeouts == 0 and run.ds_timeouts == 0

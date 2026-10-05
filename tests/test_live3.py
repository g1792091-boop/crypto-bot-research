from paperbot import Bar, Brackets, Signal
from paperbot.accounts import AccountBook
from paperbot.config import (V3_ACCOUNTS, V3_JUDGED_TFS, V3_Q1_MAIN_FAMILY, V3_RANDOM_SEEDS, V3_STRATEGIES,
                             V3_SYMBOLS, V3_TRADE_TFS, v3_settings)
from paperbot.live3 import Runner3, account_defs
from paperbot.sigservice import TRADE_TFS
from paperbot.store3 import Store3

MIN = 60_000
FIVE = 300_000
S = v3_settings()


class FakeService:
    """Emits one long signal for account S@5m at a chosen 5m boundary."""

    def __init__(self, fire_at):
        self.fire_at = fire_at
        self.last = {}
        self.computed = []

    def add_5m(self, b):
        self.last[b.symbol] = b.open_time + FIVE

    def complete(self, boundary):
        return all(self.last.get(s) == boundary for s in V3_SYMBOLS)

    def due(self, boundary):
        return ["5m"]

    def compute(self, boundary, tf, now_ms, book):
        self.computed.append(boundary)
        if boundary != self.fire_at:
            return [], [], []
        ref = book()["BTCUSDT"][1]
        sig = Signal(ts=boundary - 1, symbol="BTCUSDT", timeframe="5m", strategy_id="S", side=1,
                     stop_price=0.0, tier="best", atr=0.2,
                     meta={"stop_dist": 0.4, "ref_price": ref, "ref_time": now_ms()})
        row = {"bar_close": boundary, "timeframe": tf, "strategy": "S", "symbol": "BTCUSDT", "side": 1,
               "atr": 0.2, "ref_price": ref, "ref_time": now_ms(), "delay_ms": 1000, "status": "SUBMITTED"}
        return [row], [("S@5m", sig)], []


def steps(lo, hi):
    out = []
    for i in range(lo, hi):
        bars = {s: Bar(s, i * MIN, i * MIN + MIN - 1, 100.0, 100.05, 99.95, 100.0, volume=1.0)
                for s in V3_SYMBOLS}
        out.append((i * MIN, bars, {}))
    return out


def make(tmp_path, name, fire_at, skip_before=None):
    store = Store3(str(tmp_path / name))
    book = AccountBook(S, {s: Brackets.example() for s in V3_SYMBOLS}, store)
    if not book.load():
        book.open_accounts([{"strategy": "S", "timeframe": "5m", "kind": "strategy"}], 0)
    svc = FakeService(fire_at)
    run = Runner3(book, svc, store, None, V3_SYMBOLS, lambda: 12345,
                  lambda: {"BTCUSDT": (100.1, 100.2)}, skip_before=skip_before)
    return store, book, svc, run


def test_signal_fills_next_minute_at_reference_ask(tmp_path):
    store, book, svc, run = make(tmp_path, "a.db", fire_at=10 * MIN)
    run.process(steps(0, 12))
    p = book.engines["S@5m"].position
    assert p is not None and p.entry_time == 10 * MIN
    assert p.entry_price == 100.2 * (1 + S.slippage_frac)
    assert svc.computed == [5 * MIN, 10 * MIN]
    assert store.conn.execute("SELECT status FROM signal_log").fetchall() == [("SUBMITTED",)]


def test_restart_replays_missed_minutes_without_trading_them(tmp_path):
    store, book, svc, run = make(tmp_path, "b.db", fire_at=None)
    run.process(steps(0, 7))          # processed through minute 6, then the process dies
    store.close()
    store, book, svc, run = make(tmp_path, "b.db", fire_at=10 * MIN, skip_before=7 * MIN)
    assert book.last_ts == 6 * MIN
    run.process(steps(5, 12))         # the feed restarts at the 5m boundary before the gap
    p = book.engines["S@5m"].position
    assert p is not None and p.entry_time == 10 * MIN


def test_account_defs_count():
    defs = account_defs([f"s{k}" for k in range(36)], TRADE_TFS)
    assert len(defs) == V3_ACCOUNTS == 156 and sum(d["kind"] == "random" for d in defs) == 12
    assert len({(d["strategy"], d["timeframe"]) for d in defs}) == len(defs)


def test_no_5m_accounts():
    """5m was removed with the restart of 2026-10-04 (docs/paper-v3-rules-change-1.md): no 5m strategy or
    coin-flip account is created; 5m stays only the signal service's internal base bar."""
    assert TRADE_TFS == V3_TRADE_TFS == ("15m", "30m", "1h", "4h") and "5m" not in TRADE_TFS
    assert V3_JUDGED_TFS == ("15m", "30m", "1h") and V3_Q1_MAIN_FAMILY == 108 == V3_STRATEGIES * 3
    defs = account_defs([f"s{k}" for k in range(V3_STRATEGIES)], TRADE_TFS)
    assert not [d for d in defs if d["timeframe"] == "5m"]
    assert {d["timeframe"] for d in defs} == set(V3_TRADE_TFS)
    assert len(defs) == V3_ACCOUNTS == (V3_STRATEGIES + len(V3_RANDOM_SEEDS)) * len(V3_TRADE_TFS)


def test_live_account_set_from_the_locked_library(tmp_path):
    """The core group cmd_run opens: the locked library's 36 strategies on the core timeframes, nothing on 5m; the
    whole paper v4 set (live3.v4_defs) adds DeepSeek, the reel and the 5m coin flips, and only those two names on 5m."""
    from paperbot import sweepsig
    from paperbot.config import V4_ACCOUNTS, V4_GROUP_ACCOUNTS
    from paperbot.live3 import check_book, group_split, v4_defs
    from paperbot.sigservice import strategy_names
    names = strategy_names(sweepsig.lib())
    assert len(names) == V3_STRATEGIES
    store = Store3(str(tmp_path / "a.db"))
    book = AccountBook(S, {s: Brackets.example() for s in V3_SYMBOLS}, store, None, {})
    book.open_accounts(account_defs(names, TRADE_TFS), 0)
    assert len(book.engines) == V3_ACCOUNTS
    assert not [a for a in book.engines if a.endswith("@5m")]
    tfs = [r[0] for r in store.conn.execute("SELECT timeframe FROM accounts")]
    assert len(tfs) == V3_ACCOUNTS and "5m" not in tfs
    want = v4_defs(names)
    assert want[:V3_ACCOUNTS] == [dict(d, data=want[k]["data"]) for k, d in enumerate(account_defs(names, TRADE_TFS))]
    store = Store3(str(tmp_path / "v4.db"))
    book = AccountBook(S, {s: Brackets.example() for s in V3_SYMBOLS}, store, None, {})
    book.open_accounts(want, 0)
    check_book(book, want)
    assert len(book.engines) == V4_ACCOUNTS == 331 and group_split(book) == V4_GROUP_ACCOUNTS
    assert sorted(a for a in book.engines if a.endswith("@5m")) == ["RANDOM_1@5m", "RANDOM_2@5m", "RANDOM_3@5m",
                                                                    "REEL_H1@5m"]


# ---------------------------------------------------------------------------- the extras hook (paperbot/extras.py)
def test_runner_without_hook_identical(tmp_path):
    store, book, svc, run = make(tmp_path, "n.db", fire_at=10 * MIN)
    assert run.post_boundary is None and run.post_boundary_errors == 0
    run.process(steps(0, 12))
    calls = []
    store2, book2, svc2, run2 = make(tmp_path, "m.db", fire_at=10 * MIN)
    run2.post_boundary = lambda b, sub, to: calls.append((b, [a for a, _ in sub], to))
    run2.process(steps(0, 12))
    q = "SELECT account_id, status, step_ts FROM outcomes ORDER BY id"
    assert store.conn.execute(q).fetchall() == store2.conn.execute(q).fetchall()
    assert book.engines["S@5m"].position.entry_price == book2.engines["S@5m"].position.entry_price
    assert calls == [(5 * MIN, [], False), (10 * MIN, ["S@5m"], False)]


def test_hook_after_save_and_signature(tmp_path):
    import inspect
    from paperbot.extras import Extras
    assert list(inspect.signature(Extras.post_boundary).parameters) == ["self", "boundary", "submitted", "timed_out"]
    store, book, svc, run = make(tmp_path, "h.db", fire_at=10 * MIN)
    seen = []

    def hook(boundary, submitted, timed_out):
        # the 195's boundary is already committed: their pending submits are in the saved state
        assert not store.conn.in_transaction
        st = store.get_state("accounts")[1]["engines"]["S@5m"]
        seen.append((boundary, len(st["pending"]), [type(s).__name__ for _, s in submitted], timed_out))
    run.post_boundary = hook
    run.process(steps(0, 12))
    assert seen == [(5 * MIN, 0, [], False), (10 * MIN, 1, ["Signal"], False)]


def test_fence_rolls_back_and_disables(tmp_path):
    from paperbot.notify import ListNotifier
    store, book, svc, run = make(tmp_path, "f.db", fire_at=10 * MIN)
    run.notifier = ListNotifier()
    calls = []

    def bad(boundary, submitted, timed_out):
        calls.append(boundary)
        store.alert(1, "INFO", "[extra] written by the hook before it failed")
        raise RuntimeError("hook bug")
    run.post_boundary = bad
    run.process(steps(0, 21))
    texts = [r[0] for r in store.conn.execute("SELECT text FROM alerts")]
    assert "[extra] written by the hook before it failed" not in texts            # rolled back
    assert sum(t.startswith("[extra] boundary hook failed (RuntimeError: hook bug)") for t in texts) == 3
    assert calls == [5 * MIN, 10 * MIN, 15 * MIN] and run.post_boundary is None   # disabled after 3 failures
    assert [m[0] for m in run.notifier.messages] == ["CRITICAL"] * 3
    p = book.engines["S@5m"].position                                            # the 195 went on
    assert p is not None and p.entry_time == 10 * MIN
    assert store.conn.execute("SELECT COUNT(*) FROM signal_log").fetchone()[0] == 1


def test_single_runner_lock(tmp_path):
    import pytest
    from paperbot.live3 import single_runner_lock
    db = str(tmp_path / "p.db")
    fh = single_runner_lock(db)
    with pytest.raises(SystemExit, match="another live runner"):
        single_runner_lock(db)
    fh.close()
    single_runner_lock(db).close()                             # free again once the first runner is gone


def test_single_runner_lock_holds_for_every_spelling_of_the_database(tmp_path):
    """The lock is on the database file itself: a symlink, a hard link or a relative spelling of the same
    paper3.db cannot start a second runner (a '<db>.lock' next to each spelling could)."""
    import os
    import pytest
    from paperbot.live3 import single_runner_lock
    (tmp_path / "data").mkdir()
    (tmp_path / "alias").mkdir()
    db = str(tmp_path / "data" / "paper3.db")
    Store3(db).close()
    os.symlink(db, str(tmp_path / "alias" / "paper3.db"))
    os.link(db, str(tmp_path / "alias" / "hard.db"))
    fh = single_runner_lock(db)
    for other in (str(tmp_path / "alias" / "paper3.db"), str(tmp_path / "alias" / "hard.db"),
                  os.path.relpath(db), str(tmp_path / "data" / ".." / "data" / "paper3.db")):
        with pytest.raises(SystemExit, match="another live runner"):
            single_runner_lock(other)
    fh.close()
    single_runner_lock(str(tmp_path / "alias" / "hard.db")).close()
    st = Store3(db)                                 # the database itself is untouched by the lock
    assert st.conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0
    st.close()


def test_extras_import_failure_holds_extras(tmp_path, monkeypatch):
    import sys
    from paperbot.accounts import HeldEngine, hold_others
    from paperbot.live3 import start_extras
    from paperbot.notify import ListNotifier
    store = Store3(str(tmp_path / "e.db"))
    book = AccountBook(S, {s: Brackets.example() for s in V3_SYMBOLS}, store)
    book.open_accounts([{"strategy": "S", "timeframe": "5m", "kind": "strategy"},
                        {"strategy": "S", "timeframe": "5m", "kind": "copy", "account_id": "S@5m~c1",
                         "parent": "S@5m", "data": {"v": 1}}], 0)
    book.save(0)
    store.close()
    monkeypatch.setitem(sys.modules, "paperbot.extras", None)                      # import paperbot.extras raises
    store = Store3(str(tmp_path / "e.db"))
    note = ListNotifier()
    ext, make_of = start_extras(store, note, str(tmp_path / "e.db"), S)
    assert ext is None and make_of is hold_others
    book = AccountBook(S, {s: Brackets.example() for s in V3_SYMBOLS}, store)
    assert book.load(make_of=make_of)
    assert type(book.engines["S@5m~c1"]) is HeldEngine and type(book.engines["S@5m"]).__name__ == "PaperEngine"
    assert note.messages[0][0] == "CRITICAL" and "extras code failed to load" in note.messages[0][1]


def test_signal_service_never_computes_5m():
    """5m bars stay the internal base bars (history, completeness check, the boundary cadence), but no 5m signal
    is computed: at a boundary that is not a 15m close nothing is due, so no 5m coin-flip draw happens either."""
    from paperbot.sigservice import FIVE, SignalService

    class Lib:
        NAMES = ["A", "DOGE_L", "DOGE_S"]

        @staticmethod
        def tf_minutes(tf):
            return {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}[tf]

        @staticmethod
        def warmup_bars(tf):
            return 10

    svc = SignalService(V3_SYMBOLS, (), {"5m": 1.0, "15m": 0.0}, lib=Lib(), procs=1)
    assert svc.trade_tfs == V3_TRADE_TFS and "5m" not in svc.windows and FIVE == 5 * MIN
    day = 86_400_000
    assert svc.due(day + FIVE) == [] and svc.due(day + 2 * FIVE) == []          # 5m-only boundaries: nothing
    assert svc.due(day + 3 * FIVE) == ["15m"] and svc.due(day) == ["15m", "30m", "1h", "4h", "1d"]
    # the rate file still holds a 5m rate (research output): it is never reached, 5m is never due
    assert not [tf for k in range(288) for tf in svc.due(day + k * FIVE) if tf == "5m"]
    assert not svc.due_5m(day + FIVE)                                            # the 5m path is off unless asked
    # paper v4: the 5m accounts run on their own path (compute_5m), never as a core timeframe (no 36 on 5m, no
    # draw from the core rate file's 5m rate)
    from paperbot.live3 import service_options
    v4 = SignalService(V3_SYMBOLS, (), {"5m": 1.0, "15m": 0.0}, lib=Lib(), procs=1, **service_options())
    assert v4.trade_tfs == V3_TRADE_TFS and "5m" not in v4.windows and "5m" not in v4.ds_tfs
    assert not [tf for k in range(288) for tf in v4.due(day + k * FIVE) + v4.due_ds(day + k * FIVE) if tf == "5m"]
    assert all(v4.due_5m(day + k * FIVE) for k in range(288)) and not v4.due_5m(day + MIN)


# ---------------------------------------------------------------- SIGTERM (review 3c M-1)
_SIGTERM_CHILD = r'''
import json, os, sys, time
sys.path.insert(0, sys.argv[1])
import paperbot.live3 as L3
import paperbot.sigservice as SS

out, db, ready = sys.argv[2], sys.argv[3], sys.argv[4]


class FileNotifier:
    def send(self, level, text):
        with open(out, "a") as fh:
            fh.write(json.dumps([level, text], ensure_ascii=False) + "\n")
        return True


class FakeRest:
    api_key = api_secret = None

    def server_time(self):
        return int(time.time() * 1000)

    def exchange_info(self, syms):
        return {s: {"qty_step": 0.001, "min_notional": 5.0} for s in syms}

    def klines(self, *a, **k):
        return []


class FakeService:
    def __init__(self, symbols, record_only, rates, procs=4, **kw):
        self.symbols, self.windows, self.lib = list(symbols), {"15m": 10}, None
        self.keep, self.ds_tfs, self.five_m, self.refused = 10, (), False, {}
        from collections import deque
        self.hist = {s: deque(maxlen=120_000) for s in self.symbols}

    def verify_groups(self):
        return {}

    def pop_refusals(self):
        return []

    def bootstrap(self, s, rows):
        pass

    def close(self):
        pass


DIGESTS = []


class KeptDigest(L3.Digest):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        DIGESTS.append(self)


class FakeFeed:
    skew_ms = 0

    def __init__(self, *a, **k):
        self.n = 0

    def poll(self):
        self.n += 1
        if self.n == 2:     # after the first pass (its hourly flush set the digest's clock): a bust line waits
            DIGESTS[0].add("[S2_ST_ROC@1h] BUST: bust: equity 8.12 below 10.00")
            open(ready, "w").close()
        return []


L3._rest, L3._notifier, L3.LiveFeed, L3.Digest = FakeRest, FileNotifier, FakeFeed, KeptDigest
L3.start_extras = lambda *a: (None, None)
SS.SignalService, SS.strategy_names = FakeService, lambda lib: ["S2_ST_ROC"] + [f"X{k}" for k in range(35)]
sys.exit(L3.main(["run", "--db", db, "--allow-example-brackets", "--poll", "0.2"]))
'''


def test_sigterm_ends_the_run_cleanly_and_sends_the_pending_digest(tmp_path):
    """systemctl stop / restart send SIGTERM: the runner leaves its loop through ``finally`` (exit 0), so the hourly
    digest's pending lines (here a bust) are sent instead of being lost with the process."""
    import json
    import os
    import signal
    import subprocess
    import sys
    import time
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    child, out, ready = tmp_path / "child.py", tmp_path / "sent.jsonl", tmp_path / "ready"
    child.write_text(_SIGTERM_CHILD)
    p = subprocess.Popen([sys.executable, str(child), root, str(out), str(tmp_path / "paper3.db"), str(ready)],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.time() + 120
        while not ready.exists() and p.poll() is None and time.time() < deadline:
            time.sleep(0.05)
        assert ready.exists(), p.communicate(timeout=5)
        sent_before = out.read_text() if out.exists() else ""
        assert "BUST" not in sent_before and "파산" not in sent_before    # held for the hourly digest
        t0 = time.time()
        p.send_signal(signal.SIGTERM)
        so, se = p.communicate(timeout=30)
    finally:
        if p.poll() is None:
            p.kill()
    assert p.returncode == 0, (p.returncode, so, se)
    assert time.time() - t0 < 10
    lines = [json.loads(x) for x in out.read_text().splitlines()]
    assert any("파산 1" in text and "S2_ST_ROC@1h" in text for _, text in lines), lines
    import sqlite3
    c = sqlite3.connect(str(tmp_path / "paper3.db"))
    from paperbot.config import V4_ACCOUNTS
    assert c.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == V4_ACCOUNTS
    c.close()


def test_sigterm_handler_is_installed_only_on_the_main_thread_and_restored():
    import signal
    import threading
    from paperbot.live3 import stop_on_sigterm
    before = signal.getsignal(signal.SIGTERM)
    stop, restore = stop_on_sigterm()
    assert signal.getsignal(signal.SIGTERM) is not before and not stop.is_set()
    restore()
    assert signal.getsignal(signal.SIGTERM) is before
    got = []
    t = threading.Thread(target=lambda: got.append(stop_on_sigterm()))
    t.start()
    t.join()
    got[0][1]()                                          # a no-op restore off the main thread
    assert signal.getsignal(signal.SIGTERM) is before


def test_stop_flag_takes_no_lock_and_wait_returns_early_once_set():
    import threading
    import time as _t
    from paperbot.live3 import StopFlag
    f = StopFlag()
    assert not f.is_set() and f.wait(0.05) is False
    threading.Timer(0.1, f.set).start()
    t0 = _t.monotonic()
    assert f.wait(5.0) is True and _t.monotonic() - t0 < 1.0
    assert not hasattr(f, "_cond") and not hasattr(f, "_lock")     # nothing a signal handler could deadlock on


def test_live3_unit_signals_only_the_main_process():
    from pathlib import Path
    unit = (Path(__file__).resolve().parents[1] / "deploy" / "paperbot-live3.service").read_text()
    assert "\nKillMode=mixed\n" in unit


def _sleep_forever(_):
    import time as _t
    _t.sleep(60)


def test_pool_terminate_still_kills_workers_forked_after_the_sigterm_handler():
    import time as _t
    from multiprocessing import Pool
    from paperbot.live3 import stop_on_sigterm
    stop, restore = stop_on_sigterm()
    try:
        pool = Pool(2)
        pool.map_async(_sleep_forever, range(2))
        _t.sleep(0.5)
        t0 = _t.monotonic()
        pool.terminate()
        pool.join()
        assert _t.monotonic() - t0 < 10
        assert not stop.is_set()
    finally:
        restore()

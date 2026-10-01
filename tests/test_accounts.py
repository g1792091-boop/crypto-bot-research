import numpy as np

from paperbot import Bar, Brackets, Signal
from paperbot.accounts import AccountBook, account_id
from paperbot.config import v3_settings
from paperbot.store3 import Store3

MIN = 60_000
S = v3_settings()


def _bars(n, seed):
    rng = np.random.default_rng(seed)
    out = {}
    for k, sym in enumerate(S.symbols):
        c = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
        o = np.r_[100.0, c[:-1]]
        h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.001, n)))
        lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.001, n)))
        out[sym] = (o, h, lo, c)
    return out


def _step_bars(data, i):
    return {s: Bar(s, i * MIN, i * MIN + MIN - 1, *(float(x[i]) for x in v)) for s, v in data.items()}


def _signals(n, seed, accounts):
    rng = np.random.default_rng(seed)
    plan = {}
    for i in range(n):
        for aid in accounts:
            if rng.random() < 0.03:
                sym = S.symbols[int(rng.integers(len(S.symbols)))]
                side = 1 if rng.random() < 0.5 else -1
                plan.setdefault(i, []).append((aid, Signal(ts=i * MIN + MIN - 1, symbol=sym, timeframe="1m",
                                                           strategy_id=aid, side=side, stop_price=0.0,
                                                           tier="best", atr=0.2,
                                                           meta={"stop_dist": 0.4})))
    return plan


DEFS = [{"strategy": s, "timeframe": "15m", "kind": "strategy"} for s in ("A", "B", "C")]


def _run(store, data, plan, lo, hi, book=None):
    br = {s: Brackets.example() for s in S.symbols}
    if book is None:
        book = AccountBook(S, br, store)
        if not book.load():
            book.open_accounts(DEFS, 0)
    for i in range(lo, hi):
        book.step(i * MIN, _step_bars(data, i))
        for aid, sig in plan.get(i, []):
            book.submit(aid, sig)
        book.save(i * MIN)
    return book


def test_restart_continues_identically(tmp_path):
    n = 3000
    data = _bars(n, 1)
    ids = [account_id(d["strategy"], d["timeframe"]) for d in DEFS]
    plan = _signals(n, 2, ids)

    one = Store3(str(tmp_path / "one.db"))
    _run(one, data, plan, 0, n)

    two = Store3(str(tmp_path / "two.db"))
    _run(two, data, plan, 0, 1234)
    two.close()                         # crash / restart here
    two = Store3(str(tmp_path / "two.db"))
    _run(two, data, plan, 1234, n)

    q = "SELECT account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl FROM trades ORDER BY id"
    a, b = one.conn.execute(q).fetchall(), two.conn.execute(q).fetchall()
    assert len(a) > 30
    assert a == b
    st1, st2 = one.get_state("accounts")[1], two.get_state("accounts")[1]
    for aid in ids:
        assert st1["engines"][aid]["wallet"] == st2["engines"][aid]["wallet"]


def test_accounts_are_independent(tmp_path):
    store = Store3(str(tmp_path / "s.db"))
    br = {s: Brackets.example() for s in S.symbols}
    book = AccountBook(S, br, store)
    book.open_accounts(DEFS, 0)
    flat = (np.full(10, 100.0), np.full(10, 100.05), np.full(10, 99.95), np.full(10, 100.0))
    data = {sym: flat for sym in S.symbols}
    book.step(0, _step_bars(data, 0))
    book.submit("A@15m", Signal(ts=MIN - 1, symbol="BTCUSDT", timeframe="15m", strategy_id="A", side=1,
                                stop_price=0.0, tier="best", atr=0.2, meta={"stop_dist": 0.4}))
    book.step(MIN, _step_bars(data, 1))
    board = {r["account_id"]: r for r in book.board()}
    assert board["A@15m"]["position"] is not None
    assert board["B@15m"]["position"] is None and board["C@15m"]["position"] is None


# ---------------------------------------------------------------------------- extras (paperbot/extras.py)
def test_make_default_settings_identity(tmp_path):
    from paperbot.engine import PaperEngine
    store = Store3(str(tmp_path / "d.db"))
    book = AccountBook(S, {s: Brackets.example() for s in S.symbols}, store)
    book.open_accounts(DEFS, 0)
    for aid, e in book.engines.items():
        assert type(e) is PaperEngine and e.s is book.s
    store.close()
    store = Store3(str(tmp_path / "d.db"))
    book = AccountBook(S, {s: Brackets.example() for s in S.symbols}, store)
    calls = []
    book.load(make_of=lambda row: calls.append(row["account_id"]))    # None for every row: the defaults
    assert calls == ["A@15m", "B@15m", "C@15m"]
    assert all(type(e) is PaperEngine and e.s is book.s for e in book.engines.values())


def test_add_extra_appends_and_refuses_existing(tmp_path):
    import dataclasses
    import pytest
    from paperbot.accounts import HeldEngine
    store = Store3(str(tmp_path / "x.db"))
    book = AccountBook(S, {s: Brackets.example() for s in S.symbols}, store)
    book.open_accounts(DEFS, 0)
    s2 = dataclasses.replace(S, ladder_first_lock=0.2)
    e = book.add_extra({"account_id": "A@15m~c1", "strategy": "A", "timeframe": "15m", "kind": "copy",
                        "parent": "A@15m", "data": {"v": 1}}, created_ts=300_000, settings=s2)
    assert list(book.engines)[-1] == "A@15m~c1" and e.s is s2 and e.wallet == S.initial_equity
    assert book.meta["A@15m~c1"] == {"strategy": "A", "timeframe": "15m", "kind": "copy"}
    row = [a for a in store.accounts() if a["account_id"] == "A@15m~c1"][0]
    assert (row["created_ts"], row["parent"], row["kind"]) == (300_000, "A@15m", "copy")
    with pytest.raises(ValueError):
        book.add_extra({"account_id": "A@15m~c1", "strategy": "A", "timeframe": "15m", "kind": "copy"}, 1)
    book.remove("A@15m~c1")
    with pytest.raises(ValueError):                           # the row is still there (same transaction)
        book.add_extra({"account_id": "A@15m~c1", "strategy": "A", "timeframe": "15m", "kind": "copy"}, 1)
    store.conn.rollback()                                     # nothing was committed by add_extra
    assert [a["account_id"] for a in store.accounts()] == ["A@15m", "B@15m", "C@15m"]
    assert book.add_extra({"account_id": "N@15m~c2", "strategy": "N", "timeframe": "15m", "kind": "copy"}, 1,
                          cls=HeldEngine).__class__ is HeldEngine


def test_load_make_of_and_exception_holds(tmp_path):
    import dataclasses
    from paperbot.accounts import HeldEngine, hold_others
    from paperbot.engine import PaperEngine
    store = Store3(str(tmp_path / "l.db"))
    book = AccountBook(S, {s: Brackets.example() for s in S.symbols}, store)
    book.open_accounts(DEFS + [{"strategy": "A", "timeframe": "15m", "kind": "copy", "account_id": "A@15m~c1",
                                "parent": "A@15m"},
                               {"strategy": "NL1", "timeframe": "15m", "kind": "newlab"}], 0)
    book.save(0)
    store.close()
    s2 = dataclasses.replace(S, ladder_first_lock=0.3)

    def make_of(row):
        if row["kind"] == "copy":
            return {"settings": s2}
        if row["kind"] == "newlab":
            raise RuntimeError("broken")
        return None
    store = Store3(str(tmp_path / "l.db"))
    book = AccountBook(S, {s: Brackets.example() for s in S.symbols}, store)
    assert book.load(make_of=make_of)
    assert book.engines["A@15m~c1"].s is s2 and type(book.engines["NL1@15m"]) is HeldEngine
    assert all(type(book.engines[a]) is PaperEngine and book.engines[a].s is book.s for a in ("A@15m", "B@15m"))
    assert hold_others({"kind": "strategy"}) is None and hold_others({"kind": "random"}) is None
    assert hold_others({"kind": "copy"}) == {"cls": HeldEngine}


def test_held_engine_keeps_state(tmp_path):
    from paperbot.accounts import HeldEngine
    from paperbot.engine import engine_state
    store = Store3(str(tmp_path / "h.db"))
    br = {s: Brackets.example() for s in S.symbols}
    book = AccountBook(S, br, store)
    book.open_accounts([{"strategy": "A", "timeframe": "15m", "kind": "strategy"}], 0)
    data = _bars(50, 4)
    book.step(0, _step_bars(data, 0))
    book.submit("A@15m", Signal(ts=MIN - 1, symbol="BTCUSDT", timeframe="15m", strategy_id="A", side=1,
                                stop_price=0.0, tier="best", atr=0.2, meta={"stop_dist": 0.4}))
    book.step(MIN, _step_bars(data, 1))
    book.save(MIN)
    saved = store.get_state("accounts")[1]["engines"]["A@15m"]
    assert saved["position"] is not None
    store.close()
    store = Store3(str(tmp_path / "h.db"))
    book = AccountBook(S, br, store)
    book.load(make_of=lambda row: {"cls": HeldEngine})
    e = book.engines["A@15m"]
    for i in range(2, 40):
        book.step(i * MIN, _step_bars(data, i))
        book.submit("A@15m", Signal(ts=i * MIN + MIN - 1, symbol="ETHUSDT", timeframe="15m", strategy_id="A",
                                    side=-1, stop_price=0.0, tier="best", atr=0.2, meta={"stop_dist": 0.4}))
    st = engine_state(e)
    assert {k: v for k, v in st.items() if k != "n_trades"} == {k: v for k, v in saved.items() if k != "n_trades"}
    assert store.get_state("accounts")[1]["engines"]["A@15m"]["position"] == saved["position"]
    assert e.pending == [] and not e.trades

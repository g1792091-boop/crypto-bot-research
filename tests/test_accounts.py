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

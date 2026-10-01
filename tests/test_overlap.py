"""paperbot/overlap.py: read-only overlap analysis of the paper v3 accounts, and /api/overlap."""

import time

import numpy as np
import pytest

from paperbot import overlap
from paperbot.models import TradeRecord
from paperbot.store3 import Store3

STEP = overlap.STEP_MS
HOUR = 3_600_000
DAY = 86_400_000
T0 = 1_780_012_800_000            # a UTC midnight
DAYS = 8
N_PTS = DAYS * DAY // STEP + 1
TS = T0 + np.arange(N_PTS) * STEP
END = int(TS[-1])


def _rec(aid, symbol, side, t0, t1, pnl):
    return TradeRecord(strategy_id=aid.split("@")[0], symbol=symbol, timeframe="15m", side=side, signal_ts=t0,
                       entry_time=t0, entry_price=100.0, exit_time=t1, exit_price=100.0, exit_reason="SL", qty=1.0,
                       leverage=5, tier="best", margin=100.0, stop_price=99.0, tp_price=0.0, liq_price=80.0,
                       fees=0.1, funding=0.0, pnl=pnl, roe=pnl / 100, price_move=0.0, mae_price=0.0,
                       mfe_price=0.0, equity_after=5000.0, score=0.0)


def _schedule(offset_ms, period_ms=2 * HOUR, hold_ms=HOUR, start=T0, end=END):
    """(entry, exit) every ``period_ms``, holding ``hold_ms``."""
    out, t = [], start + offset_ms
    while t + hold_ms <= end:
        out.append((t, t + hold_ms))
        t += period_ms
    return out


def _path(sched, rng, start=T0):
    """Equity that moves only while a position is open."""
    r = np.zeros(N_PTS)
    for t0, t1 in sched:
        i0, i1 = (t0 - T0) // STEP, (t1 - T0) // STEP
        r[i0 + 1:i1 + 1] = rng.normal(0, 0.004, i1 - i0)
    eq = 5000 * np.cumprod(1 + r)
    eq[TS < start] = np.nan
    return eq


def _write(store, aid, kind, symbol, side, sched, eq, created=T0):
    store.add_account(aid, aid.split("@")[0], aid.split("@")[1], kind, created, "v")
    for t0, t1 in sched:
        store.trade(aid, _rec(aid, symbol, side, t0, t1, 1.0))
    for t, v in zip(TS, eq):
        if not np.isnan(v):
            store.equity(aid, int(t), float(v), 0.0)


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    """A@15m and B@15m: same BTC long trades, identical equity (one bet).
    C@15m: ETH short at other times, its own equity, an open SOL short in the state.
    D@15m: identical to A but only 5 trades (insufficient). E@15m: identical to A but only
    the last 3 days (insufficient). RANDOM_1@15m: coin-flip with A's path (reference only)."""
    path = str(tmp_path_factory.mktemp("ov") / "paper3.db")
    st = Store3(path)
    rng = np.random.default_rng(7)
    sa = _schedule(0)
    ea = _path(sa, rng)
    sc = _schedule(HOUR + 30 * 60_000, hold_ms=20 * 60_000)
    ec = _path(sc, np.random.default_rng(99))
    _write(st, "A@15m", "strategy", "BTCUSDT", 1, sa, ea)
    _write(st, "B@15m", "strategy", "BTCUSDT", 1, sa, ea.copy())
    _write(st, "C@15m", "strategy", "ETHUSDT", -1, sc, ec)
    _write(st, "D@15m", "strategy", "BTCUSDT", 1, sa[-5:], ea.copy())
    late = T0 + (DAYS - 3) * DAY
    e_eq = ea.copy()
    e_eq[TS < late] = np.nan
    _write(st, "E@15m", "strategy", "BTCUSDT", 1, [s for s in sa if s[0] >= late], e_eq, created=late)
    _write(st, "RANDOM_1@15m", "random", "BTCUSDT", 1, sa, ea.copy())
    st.put_state("accounts", END, {"engines": {"C@15m": {"position": {
        "symbol": "SOLUSDT", "side": -1, "entry_time": END - HOUR, "entry_price": 1.0}}}})
    st.close()
    return path


@pytest.fixture(scope="module")
def rep(db):
    c = overlap.open_ro(db)
    try:
        return overlap.report(c, days=7)
    finally:
        c.close()


def _ids(group):
    return {a["account_id"] for a in group["accounts"]}


def test_identical_accounts_form_a_group_independent_does_not(rep):
    assert rep["window"]["end"] == END and rep["window"]["start"] == END - 7 * DAY
    assert [_ids(g) for g in rep["groups"]] == [{"A@15m", "B@15m"}]
    g = rep["groups"][0]
    assert g["min_corr"] == pytest.approx(1.0) and g["same_of_busy_mean"] == pytest.approx(1.0)
    cmb = g["combined"]
    # the same bet twice: adding them up spreads nothing
    assert cmb["dd_ratio"] == pytest.approx(1.0) and cmb["worst_day_ratio"] == pytest.approx(1.0)
    assert cmb["max_dd"] > 0 and cmb["days"] == 7
    top = rep["pairs"]["top"][0]
    assert {top["a"]["account_id"], top["b"]["account_id"]} == {"A@15m", "B@15m"}
    assert top["same_time"] == pytest.approx(0.5, abs=0.01)          # in a position half the time
    others = [p for p in rep["pairs"]["top"] if "C@15m" in (p["a"]["account_id"], p["b"]["account_id"])]
    assert others and all(abs(p["corr"]) < 0.3 and p["same_time"] == 0 for p in others)


def test_insufficient_data_is_marked_and_never_grouped(rep):
    bad = {r["account_id"]: r["missing"] for r in rep["insufficient"]}
    assert bad == {"D@15m": ["trades"], "E@15m": ["days"]}
    assert rep["accounts"] == {"strategy": 5, "random": 1, "copy": 0, "strategy_enough_data": 3}
    assert rep["copies"] == []
    assert rep["pairs"]["strategy_pairs"] == 10 and rep["pairs"]["sufficient"] == 3
    assert rep["pairs"]["insufficient"] == 7
    assert rep["rules"]["min_days"] == 7 and rep["rules"]["min_trades"] == 20 and rep["rules"]["group_corr"] == 0.7


def test_coin_flip_accounts_are_only_a_reference(rep):
    assert all("RANDOM_1@15m" not in _ids(g) for g in rep["groups"])
    ref = rep["pairs"]["random_reference"]["random_vs_strategy"]
    assert ref["pairs"] == 3 and ref["max"] == pytest.approx(1.0)          # same path as A and B, not grouped


def test_exposure_counts_at_a_known_moment(db, rep):
    c = overlap.open_ro(db)
    try:
        w = overlap.load_window(c, 7)
    finally:
        c.close()
    ex = overlap.exposure(w)
    t = int(np.searchsorted(w.ts, T0 + 4 * DAY + 10 * 60_000))     # inside an A/B/D/E BTC long, C flat
    k = w.code("BTCUSDT", 1)
    held = {w.ids[j] for j in np.flatnonzero(w.pos[t] == k)}
    assert held == {"A@15m", "B@15m", "RANDOM_1@15m"}                # E starts on day 5, D trades only at the end
    tk = {x["ts"]: x for x in ex["top"] if x["symbol"] == "BTCUSDT"}
    # the busiest moment: A, B, E and D's last trades together; the coin-flip account is not counted
    assert ex["max"]["count"] == 4 and ex["max"]["symbol"] == "BTCUSDT" and ex["max"]["side"] == 1
    m = rep["exposure"]["top"][0]
    assert m["count"] == 4 and set(m["accounts"]) == {"A@15m", "B@15m", "D@15m", "E@15m"}
    assert m["strategies"] == 4 and tk and m["minutes"] == 60            # D's 1-hour trade
    assert ex["holding_max"] == 4
    # open position from the state snapshot: C's SOL short counts at the last point
    assert w.pos[-1, w.ids.index("C@15m")] == w.code("SOLUSDT", -1)
    sol = [r for r in ex["by_symbol"] if r["symbol"] == "SOLUSDT"]
    assert sol and sol[0]["side"] == -1 and sol[0]["max"] == 1
    assert sum(b["share"] for b in ex["distribution"]) == pytest.approx(1.0)
    # moments of one coin+side are at least an hour apart
    btc = sorted(x["ts"] for x in ex["top"] if x["symbol"] == "BTCUSDT" and x["side"] == 1)
    assert all(b - a >= HOUR for a, b in zip(btc, btc[1:]))


def test_no_equity_gives_an_empty_report(tmp_path):
    p = str(tmp_path / "empty.db")
    Store3(p).close()
    c = overlap.open_ro(p)
    try:
        r = overlap.report(c, 7)
    finally:
        c.close()
    assert r["window"] is None and r["groups"] == []


def test_pairwise_corr_matches_pandas_pairwise_complete():
    pd = pytest.importorskip("pandas")
    rng = np.random.default_rng(3)
    x = rng.normal(size=(300, 6))
    x[:, 1] = x[:, 0] * 2 + rng.normal(scale=0.1, size=300)
    x[rng.random(x.shape) < 0.15] = np.nan
    x[:, 5] = 1.0                                              # constant: no correlation
    c, n = overlap.pairwise_corr(x)
    ref = pd.DataFrame(x).corr(min_periods=3).to_numpy()
    fin = np.isfinite(ref)
    assert np.allclose(c[fin], ref[fin], atol=1e-9)
    assert np.isnan(c[:, 5]).all()
    assert n[0, 1] == (~np.isnan(x[:, 0]) & ~np.isnan(x[:, 1])).sum()


def test_complete_linkage_does_not_chain():
    sim = np.array([[1, .9, .3], [.9, 1, .9], [.3, .9, 1]])
    ok = np.ones((3, 3), bool)
    groups = overlap.complete_linkage(sim, ok, 0.7)
    assert len(groups) == 1 and len(groups[0]) == 2          # A-C is 0.3, so not all three
    assert overlap.complete_linkage(sim, np.zeros((3, 3), bool), 0.7) == []


def test_runs_fast_at_full_size():
    """195 accounts x 4 weeks of 5-minute points (the live run's shape), in memory."""
    rng = np.random.default_rng(0)
    T, N = 28 * DAY // STEP + 1, 195
    ts = T0 + np.arange(T, dtype=np.int64) * STEP
    eq = 5000 * np.cumprod(1 + rng.normal(0, 0.001, (T, N)), axis=0)
    pos = rng.integers(0, 13, (T, N)).astype(np.int16)
    pos = np.repeat(pos[::12], 12, axis=0)[:T]                  # positions last an hour
    is_random = np.zeros(N, bool)
    is_random[-15:] = True
    w = overlap.Window(int(ts[0]), int(ts[-1]), ts, [f"S{j}@15m" for j in range(N)],
                       [{"strategy": f"S{j}", "timeframe": "15m", "kind": "random" if is_random[j] else "strategy"}
                        for j in range(N)], eq, pos, [f"C{i}USDT" for i in range(6)], np.full(N, 50),
                       is_random, np.zeros(N, np.int64), np.full(N, T - 1))
    t = time.perf_counter()
    ex = overlap.exposure(w)
    sim = overlap.similarity(w)
    S = np.flatnonzero(~is_random)
    overlap.complete_linkage(sim["corr"][np.ix_(S, S)], sim["sufficient"][np.ix_(S, S)])
    took = time.perf_counter() - t
    assert ex["points"] == T and sim["sufficient"][np.ix_(S, S)].sum() == 180 * 179
    assert took < 30, took                                      # ~0.5 s on a quiet machine


# ---------------------------------------------------------------- endpoint
fastapi = pytest.importorskip("fastapi")


def test_endpoint_login_shape_and_cache(db):
    from fastapi.testclient import TestClient

    from paperbot.dash.app import create_app, hash_password
    app = create_app(db, hash_password("pw"), b"x" * 32)
    cl = TestClient(app)
    assert cl.get("/api/overlap").status_code == 401
    assert cl.post("/api/login", json={"password": "pw"}).status_code == 200
    r = cl.get("/api/overlap", params={"days": 7})
    assert r.status_code == 200
    d = r.json()
    assert set(d) >= {"window", "rules", "accounts", "exposure", "pairs", "groups", "insufficient", "computed_at"}
    assert [_ids(g) for g in d["groups"]] == [{"A@15m", "B@15m"}]
    assert {"ts", "symbol", "side", "count", "strategies", "accounts"} <= set(d["exposure"]["top"][0])
    assert {"max_dd", "avg_member_max_dd", "dd_ratio", "worst_day"} <= set(d["groups"][0]["combined"])
    assert cl.get("/api/overlap", params={"days": 7}).json()["computed_at"] == d["computed_at"]   # cached
    assert cl.get("/api/overlap", params={"days": 0}).json()["window"]["days"] == 1.0              # clamped

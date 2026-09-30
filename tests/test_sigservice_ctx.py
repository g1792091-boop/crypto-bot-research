import numpy as np
import pandas as pd

from paperbot.sigservice import SignalService, chart_context


def test_submitted_signals_carry_the_chart_context():
    svc = SignalService(["BTCUSDT"], [], random_rates={}, procs=1, trade_tfs=("1h",), record_tfs=())
    name = svc.names[0]
    ctx = {"regime": "trend_up", "adx": 31.0}
    fake = {"symbol": "BTCUSDT", "tf": "1h", "ready": True, "close": 100.0, "atr": 1.0,
            "sides": {name: 1}, "errors": [], "ctx": ctx}
    svc._jobs = lambda boundary, tf: []
    svc._map = lambda jobs: [fake]
    rows, subs, _ = svc.compute(3_600_000 * 10, "1h", lambda: 3_600_000 * 10 + 2000,
                                lambda: {"BTCUSDT": (99.9, 100.1)})
    assert rows[0]["status"] == "SUBMITTED" and rows[0]["data"]["ctx"] == ctx
    (aid, sig), = subs
    assert aid == f"{name}@1h" and sig.meta["ctx"] == ctx


def test_chart_context_on_synthetic_bars():
    from paperbot import sweepsig
    from paperbot.recorder import build_frames
    lib = sweepsig.lib()
    rng = np.random.default_rng(1)
    n = 12 * 24 * 40
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    o = np.r_[c[0], c[:-1]]
    df5 = pd.DataFrame({"ts": pd.to_datetime(np.arange(n) * 300_000, unit="ms", utc=True), "open": o,
                        "high": np.maximum(o, c) * 1.001, "low": np.minimum(o, c) * 0.999, "close": c,
                        "volume": 1.0})
    df = build_frames(lib, df5, ["1h"])["1h"]
    ctx = chart_context(lib, "BTCUSDT", df5, df, "1h")
    assert ctx["tf"] == "1h" and ctx["htf"] == "4h"
    assert ctx["regime"] in ("trend_up", "trend_down", "box", "chop", "unknown")
    assert ctx["htf_regime"] in ("trend_up", "trend_down", "box", "chop", "unknown")
    assert 0 <= ctx["adx"] <= 100 and ctx["di_plus"] >= 0


def test_doge_join_sides():
    from paperbot.sigservice import doge_join
    assert doge_join(1, 0) == 1 and doge_join(0, -1) == -1 and doge_join(1, -1) == 0 and doge_join(0, 0) == 0
    assert doge_join(np.array([1, 0, 1, 0]), np.array([0, -1, -1, 0])).tolist() == [1, -1, 0, 0]


def test_live_worker_trades_the_doge_short_rule_as_a_short():
    """Regression: DOGE_S is already -1 in the locked compute_signals; the account must go SHORT there
    (the old join DOGE_L - DOGE_S turned every short signal into a long)."""
    from paperbot import sweepsig
    from paperbot.recorder import build_frames
    from paperbot.sigservice import compute_last
    lib = sweepsig.lib()
    rng = np.random.default_rng(11)
    n = 12 * 24 * 60
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.0025, n)))
    o = np.r_[c[0], c[:-1]]
    ts = np.arange(n, dtype=np.int64) * 300_000
    df5 = pd.DataFrame({"ts": pd.to_datetime(ts, unit="ms", utc=True), "open": o, "high": np.maximum(o, c) * 1.001,
                        "low": np.minimum(o, c) * 0.999, "close": c, "volume": rng.uniform(1, 5, n)})
    df = build_frames(lib, df5, ["1h"])["1h"]
    raw = lib.compute_signals({"X": df}, "1h", ["DOGE_L", "DOGE_S"], strict=True)
    shorts = np.nonzero(raw["DOGE_S"]["X"] < 0)[0]
    longs = np.nonzero(raw["DOGE_L"]["X"] > 0)[0]
    assert len(shorts) and len(longs)
    for i, want in ((int(shorts[-1]), -1), (int(longs[-1]), 1)):
        end = (i + 1) * 12                      # 5m bars up to the close of 1h bar i
        job = ("DOGEUSDT", "1h", int(ts[end - 1]) + 300_000, ts[:end], o[:end], df5["high"].to_numpy()[:end],
               df5["low"].to_numpy()[:end], c[:end], df5["volume"].to_numpy()[:end])
        r = compute_last(job)
        assert r["ready"], r.get("why")
        assert r["sides"]["DOGE"] == want, (i, r["sides"]["DOGE"])

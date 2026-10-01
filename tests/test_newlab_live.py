"""New-strategy accounts' live signals (paperbot/newlab_live.py) and their rows, submits and code pin
(paperbot/extras.py phase 2)."""

import json
import os
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from paperbot import newlab_live as NLL
from paperbot import sweepsig
from paperbot.recorder import build_frames
from tests.extras_world import MIN, T0, World, newlab_spec

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIVE = 300_000
TF_MS = {"5m": 5 * MIN, "15m": 15 * MIN, "30m": 30 * MIN, "1h": 60 * MIN, "4h": 240 * MIN}
B5_CUTS = int(os.environ.get("EXTRAS_B5_CUTS", "16"))        # cut points per timeframe (the review ran ~1,500)


def _df5(n, seed=11, t0=1_600_000_000_000 - 1_600_000_000_000 % 86_400_000, halt=None):
    rng = np.random.default_rng(seed)
    ts = t0 + np.arange(n, dtype=np.int64) * FIVE
    r = rng.normal(0, 0.0025, n) + np.repeat(rng.normal(0, 0.0004, n // 2000 + 1), 2000)[:n]
    c = 30000 * np.exp(np.cumsum(r))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.001, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.001, n)))
    v = rng.lognormal(3, 1, n)
    if halt is not None:
        a, b = halt
        o[a:b] = h[a:b] = lo[a:b] = c[a:b] = c[a - 1]
        v[a:b] = 0.0
    return pd.DataFrame({"ts": pd.to_datetime(ts, unit="ms", utc=True), "open": o, "high": h, "low": lo,
                         "close": c, "volume": v})


def _rows(df5):
    return list(zip((df5["ts"].astype("int64") // 1_000_000).tolist(), df5["open"].tolist(), df5["high"].tolist(),
                    df5["low"].tolist(), df5["close"].tolist(), df5["volume"].tolist()))


# ============================================================================ windows and warm-up
def test_window_table_within_hist():
    from paperbot.sigservice import RECORD_TFS, TRADE_TFS, window_5m
    lib = sweepsig.lib()
    maxlen = max(window_5m(lib, tf) for tf in TRADE_TFS + RECORD_TFS)
    assert maxlen == 116_064
    for tf in NLL.TRADE_TFS:
        assert NLL.NEWLAB_WINDOW_5M[tf] <= maxlen
        bars = NLL.NEWLAB_WINDOW_5M[tf] // (TF_MS[tf] // FIVE)
        assert NLL.NEWLAB_MIN_BARS[tf] < bars
        # EMA200 on the timeframe's own bars: the seed's weight is negligible
        assert (1 - 2 / 201) ** (bars - 200) < 1e-9
    assert NLL.NEWLAB_MIN_BARS == {"5m": 5_900, "15m": 5_900, "30m": 7_900, "1h": 3_950, "4h": 2_350}


class _Svc:
    def __init__(self, maxlen=116_064, rows=None):
        from collections import deque
        self.trade_symbols = ["BTCUSDT"]
        self.hist = {"BTCUSDT": deque(rows or [], maxlen=maxlen)}

    def due(self, b):
        return [tf for tf in NLL.TRADE_TFS if b % TF_MS[tf] == 0]


def test_register_reports_not_ready():
    src = NLL.NewlabSignals(_Svc(maxlen=28_944))           # e.g. the 1d record timeframe dropped
    assert src.register("NL1@4h", "NL1", "4h", newlab_spec(6)) is not None
    assert "NL1@4h" not in src.specs
    assert src.register("NL2@1h", "NL2", "1h", newlab_spec(1)) is not None     # 48,000 > 28,944
    assert src.register("NL3@5m", "NL3", "5m", newlab_spec(0)) is None
    assert src.tfs() == ["5m"]


def test_min_bars_warmup():
    lib = sweepsig.lib()
    from paperbot.agents.newlab_signals import signals_for_frame
    df5 = _df5(300)
    b = int(df5["ts"].iloc[-1].value // 1_000_000) + FIVE
    out = NLL.compute_newlab(lib, signals_for_frame, "BTCUSDT", "5m", b, _rows(df5), [("NL1@5m", newlab_spec(0))],
                             min_bars=5_900)
    assert not out["ready"] and out["why"] == "warm-up: 300 bars"
    out = NLL.compute_newlab(lib, signals_for_frame, "BTCUSDT", "5m", b, _rows(df5), [("NL1@5m", newlab_spec(0))],
                             min_bars=100)
    assert out["ready"] and set(out["sides"]) == {"NL1@5m"}


def test_signal_at_bar_close_only():
    lib = sweepsig.lib()
    from paperbot.agents.newlab_signals import signals_for_frame
    df5 = _df5(2000)
    last = int(df5["ts"].iloc[-1].value // 1_000_000) + FIVE
    b = last - last % TF_MS["1h"]                            # the 1h bar closing at b ...
    rows = [r for r in _rows(df5) if r[0] < b - FIVE]        # ... misses its last 5m bar: not computed
    out = NLL.compute_newlab(lib, signals_for_frame, "BTCUSDT", "1h", b, rows, [("x", newlab_spec(1))], 10)
    assert not out["ready"] and "expected" in out["why"]
    rows = [r for r in _rows(df5) if r[0] < b]
    out = NLL.compute_newlab(lib, signals_for_frame, "BTCUSDT", "1h", b, rows, [("x", newlab_spec(1))], 10)
    assert out["ready"] and out["bar_open"] == b - TF_MS["1h"]


# ============================================================================ B5: trailing window == full history
def _b5_specs(tf):
    from paperbot.agents import newlab as NL
    g = __import__("paperbot.extras", fromlist=["NEWLAB_V1"]).NEWLAB_V1
    out = []
    for fam, (names, grid) in g["families"].items():
        out.append(NL.normalize_spec({"timeframe": tf, "entry": {"family": fam, "params": dict(zip(names, grid[-1]))},
                                      "direction": "both"}))
    fl = [{"kind": "trend_ema", "length": 200}, {"kind": "adx", "mode": "above", "level": 25},
          {"kind": "htf_trend", "length": 50}, {"kind": "vol_regime", "mode": "high", "lookback": 500},
          {"kind": "session", "window": "us"}]
    for f in fl:
        out.append(NL.normalize_spec({"timeframe": tf, "entry": {"family": "psar_flip"}, "filters": [f],
                                      "direction": "both"}))
    return out


@pytest.fixture(scope="module")
def long5():
    return _df5(NLL.NEWLAB_WINDOW_5M["4h"] + 9_000, seed=5)


@pytest.mark.parametrize("tf", NLL.TRADE_TFS)
def test_trailing_window_equals_full_history(long5, tf):
    from paperbot.agents.newlab_signals import signals_for_frame
    lib = sweepsig.lib()
    specs = _b5_specs(tf)
    full = build_frames(lib, long5, [tf])[tf]
    atr = lib.fg.atr(full, 14).to_numpy(float)
    sig_full = {i: signals_for_frame(sp, full, atr) for i, sp in enumerate(specs)}
    span = TF_MS[tf]
    fts = (full["ts"].astype("int64") // 1_000_000).to_numpy()
    t0 = int(long5["ts"].iloc[0].value // 1_000_000)
    win = NLL.NEWLAB_WINDOW_5M[tf]
    cand = np.nonzero(fts - t0 >= (win + 10) * FIVE)[0]
    rng = np.random.default_rng(1)
    hits = [i for i in cand if any(sig_full[k][i] for k in sig_full)]
    picks = sorted(set(rng.choice(cand, size=min(B5_CUTS // 2, len(cand)), replace=False).tolist())
                   | set(rng.choice(hits, size=min(B5_CUTS - B5_CUTS // 2, len(hits)), replace=False).tolist()))
    ts5 = (long5["ts"].astype("int64") // 1_000_000).to_numpy()
    mism, worst_htf = [], 0
    for i in picks:
        b = int(fts[i]) + span
        end = int(np.searchsorted(ts5, b))
        w = long5.iloc[max(0, end - win):end].reset_index(drop=True)
        df = NLL.lab_frame(lib, w, tf)
        assert int(df["ts"].iloc[-1].value // 1_000_000) + span == b
        a = lib.fg.atr(df, 14).to_numpy(float)
        for k, sp in enumerate(specs):
            s = int(signals_for_frame(sp, df, a)[-1])
            if s != int(sig_full[k][i]):
                if tf == "4h" and sp["filters"] and sp["filters"][0]["kind"] == "htf_trend":
                    worst_htf += 1                           # Q-4: daily EMA50 on 400 days (reported)
                    continue
                mism.append((int(fts[i]), sp["entry"]["family"], [f["kind"] for f in sp["filters"]], s,
                             int(sig_full[k][i])))
    assert mism == [], mism[:5]
    assert worst_htf <= max(1, len(picks) // 100)


# ============================================================================ zero-volume bars (lab cache rules)
def _lab_drop(df):
    keep = ~(df["volume"].to_numpy(float) <= 0)
    return df.loc[keep].reset_index(drop=True)


def test_zero_volume_rules_match_lab_cache():
    from paperbot.agents.newlab_signals import signals_for_frame
    lib = sweepsig.lib()
    n = 6_000
    df5 = _df5(n, seed=9, halt=(n - 400, n - 388))           # a one-hour flat zero-volume halt (12 5m bars)
    for tf in ("5m", "30m"):                                 # the lab: resample of the DROPPED 5m
        want = build_frames(lib, _lab_drop(df5), [tf])[tf]
        got = NLL.lab_frame(lib, df5, tf)
        pd.testing.assert_frame_equal(got.reset_index(drop=True), want.reset_index(drop=True))
    for tf in ("15m", "1h", "4h"):                           # native bars (= resample of all 5m), then dropped
        native = build_frames(lib, df5, [tf])[tf]
        want = _lab_drop(native)
        got = NLL.lab_frame(lib, df5, tf)
        pd.testing.assert_frame_equal(got.reset_index(drop=True), want.reset_index(drop=True))
        assert len(got) < len(native) if tf != "4h" else len(got) <= len(native)
    # the halt bars are gone from 5m and the volume families see the same series as the lab
    got5 = NLL.lab_frame(lib, df5, "5m")
    assert len(got5) == n - 12 and (got5["volume"] > 0).all()
    for fam in ("volume_spike", "obv_cross", "mfi_reversal"):
        sp = {"v": "newlab-v1", "timeframe": "5m", "entry": {"family": fam, "params": {}}, "filters": [],
              "direction": "both"}
        lab = _lab_drop(df5)
        assert (signals_for_frame(sp, got5) == signals_for_frame(sp, build_frames(lib, lab, ["5m"])["5m"])).all()


# ============================================================================ rows, statuses, submits (phase 2)
def _nl_world(tmp_path, i=0, **kw):
    w = World(tmp_path, hist=True, **kw)
    w.process(T0)
    w.newlab_proposal(i)
    w.run(T0 + MIN, T0 + 5 * MIN)
    aid = [a["account_id"] for a in w.extras_rows()][0]
    return w, aid


def _fake_result(w, aid, b, side=1, atr=0.3, sym="BTCUSDT", ctx=None):
    tf = aid.split("@")[1]
    return {"symbol": sym, "tf": tf, "ready": True, "why": None, "bars": 500, "bar_open": b - TF_MS[tf],
            "close": 100.0, "atr_last": atr, "sides": {aid: side}, "ctx": ctx if ctx is not None else {"regime": "box"},
            "errors": []}


def test_rows_and_submit_shape(tmp_path, monkeypatch):
    w, aid = _nl_world(tmp_path)
    b = T0 + 10 * MIN
    monkeypatch.setattr(w.ext.newlab, "compute", lambda B, due, dl: ([_fake_result(w, aid, B)], []))
    w.run(T0 + 5 * MIN, b)
    row = w.store.conn.execute("SELECT bar_close, timeframe, strategy, symbol, side, atr, ref_price, ref_time, "
                               "delay_ms, status, data FROM signal_log WHERE strategy = 'NL1'").fetchall()
    assert len(row) == 2                                        # boundaries T0+5m was the creation (no rows), 10m ...
    r = [x for x in row if x[0] == b][0]
    ask = w.prices()["BTCUSDT"][1]
    assert r[:10] == (b, "5m", "NL1", "BTCUSDT", 1, 0.3, ask, b + 1500, 1500, "SUBMITTED")
    d = json.loads(r[10])
    assert d["newlab"] == {"account_id": aid, "trial_id": 1, "spec_hash": w.ext.extras[aid].data["spec_hash"],
                           "bars": 500}
    assert d["ctx"] == {"regime": "box"} and d["bid"] < d["ask"]
    sig = w.book.engines[aid].pending[0]
    assert (sig.ts, sig.symbol, sig.timeframe, sig.strategy_id, sig.side, sig.stop_price, sig.tier, sig.atr) == \
        (b - 1, "BTCUSDT", "5m", "NL1", 1, 0.0, "best", 0.3)
    assert sig.meta == {"stop_dist": 0.6, "ref_price": ask, "ref_time": b + 1500, "delay_ms": 1500, "account": aid,
                        "ctx": {"regime": "box"}}
    w.close()


def test_fill_next_step_at_ref_plus_slippage_and_2atr_stop(tmp_path, monkeypatch):
    w, aid = _nl_world(tmp_path)
    b = T0 + 10 * MIN
    monkeypatch.setattr(w.ext.newlab, "compute", lambda B, due, dl: ([_fake_result(w, aid, B, side=-1)], []))
    w.run(T0 + 5 * MIN, b + MIN)
    p = w.book.engines[aid].position
    bid = w.prices()["BTCUSDT"][0]
    assert p is not None and p.entry_time == b and p.side == -1
    assert p.entry_price == pytest.approx(bid * (1 - w.book.s.slippage_frac))
    assert p.stop_initial == pytest.approx(bid + 2 * 0.3)
    out = w.store.conn.execute("SELECT status, step_ts FROM outcomes WHERE account_id = ?", (aid,)).fetchall()
    assert out[0] == ("ENTERED", b)
    w.close()


def test_late_no_price_no_atr_statuses(tmp_path, monkeypatch):
    w, aid = _nl_world(tmp_path)
    b = T0 + 10 * MIN
    w.run(T0 + 5 * MIN, b - MIN)
    calls = {"n": 0}

    def compute(B, due, dl):
        calls["n"] += 1
        return [_fake_result(w, aid, B, atr=None, sym="ETHUSDT"), _fake_result(w, aid, B)], []
    monkeypatch.setattr(w.ext.newlab, "compute", compute)
    monkeypatch.setattr(w.runner, "prices", lambda: {"BTCUSDT": (99.0, 101.0)})          # no ETH price
    w.process(b - MIN)
    st = dict(w.store.conn.execute("SELECT symbol, status FROM signal_log WHERE strategy = 'NL1' AND bar_close = ?",
                                   (b,)).fetchall())
    assert st == {"ETHUSDT": "NO_PRICE", "BTCUSDT": "SUBMITTED"}
    monkeypatch.setattr(w.runner, "prices", lambda: {"BTCUSDT": (99.0, 101.0), "ETHUSDT": (99.0, 101.0)})
    w.process(b)
    w.process(b + 3 * MIN)
    st = dict(w.store.conn.execute("SELECT symbol, status FROM signal_log WHERE strategy = 'NL1' AND bar_close = ?",
                                   (b + 5 * MIN,)).fetchall())
    assert st == {"ETHUSDT": "NO_ATR", "BTCUSDT": "SUBMITTED"}
    # a newlab compute that took long: the row is LATE (the hook entry was live)
    real = w.runner.now_ms

    def slow(B, due, dl):
        w.now += 200_000
        return [_fake_result(w, aid, B)], []
    monkeypatch.setattr(w.ext.newlab, "compute", slow)
    w.process(b + 8 * MIN)
    assert w.store.conn.execute("SELECT status FROM signal_log WHERE strategy = 'NL1' AND bar_close = ?",
                                (b + 10 * MIN,)).fetchone()[0] == "LATE"
    assert real is not None
    w.close()


def test_budget_deadline_skips(tmp_path):
    w, aid = _nl_world(tmp_path)
    w.ext.cfg.budget_s = 1e-9                              # the deadline passes before the first job
    w.run(T0 + 5 * MIN, T0 + 10 * MIN)
    h = w.state()["health"]
    assert h["budget_skips"] >= 6 and h["errors"] == 0
    assert any("시간 예산" in t for (t,) in w.store.conn.execute("SELECT text FROM alerts"))
    w.close()


def test_plain_types_only(tmp_path):
    from paperbot.agents.newlab_signals import signals_for_frame
    lib = sweepsig.lib()
    df5 = _df5(1500, seed=4)
    b = int(df5["ts"].iloc[-1].value // 1_000_000) + FIVE
    seen = 0
    for i in range(10):
        sp = newlab_spec(i)
        out = NLL.compute_newlab(lib, signals_for_frame, "BTCUSDT", sp["timeframe"], b - b % TF_MS[sp["timeframe"]],
                                 _rows(df5[(df5["ts"].astype("int64") // 1_000_000) < b - b % TF_MS[sp["timeframe"]]]),
                                 [("a", sp)], 10)
        json.dumps(out)                                     # no default=: plain types only
        for k, v in out["sides"].items():
            assert type(v) is int
        seen += out["ready"]
    assert seen >= 5
    # an np.int64 that slips into a signal is refused by plain_json (WARN, no submit)
    w, aid = _nl_world(tmp_path)
    w.ext.newlab.compute = lambda B, due, dl: ([_fake_result(w, aid, B, ctx={"x": np.int64(3)})], [])
    w.run(T0 + 5 * MIN, T0 + 10 * MIN)
    assert w.book.engines[aid].pending == [] and w.state()["health"]["errors"] == 0
    assert any("JSON" in t for (t,) in w.store.conn.execute("SELECT text FROM alerts WHERE text LIKE '[extra]%'"))
    w.close()


def test_pin_mismatch_suspends(tmp_path):
    w, aid = _nl_world(tmp_path)
    w.close()
    import sqlite3
    c = sqlite3.connect(os.path.join(str(tmp_path), "paper3.db"))
    d = json.loads(c.execute("SELECT data FROM accounts WHERE account_id = ?", (aid,)).fetchone()[0])
    d["code"]["newlab_signals"] = "0" * 64                   # the agents changed newlab_signals.py since
    c.execute("UPDATE accounts SET data = ? WHERE account_id = ?", (json.dumps(d), aid))
    c.commit()
    c.close()
    w = World(tmp_path, hist=True)
    x = w.ext.extras[aid]
    assert (x.status, x.code) == ("suspended", "code_changed") and aid not in w.ext.newlab.specs
    assert w.state()["accounts"][aid]["code"] == "code_changed"
    text = NLL.pin_text(w.ext.newlab.pin())
    w.close()
    # the owners accept the new code: resumed, recorded as that account's code_accepted event (once)
    cfg = tmp_path / "extras.json"
    cfg.write_text(json.dumps({"accept_code": {aid: text}, "observe_days": 21}))
    for _ in range(2):
        w = World(tmp_path, hist=True, config_path=str(cfg))
        x = w.ext.extras[aid]
        assert x.status == "active" and aid in w.ext.newlab.specs
        ev = [e["event"] for e in w.state()["events"] if e["account_id"] == aid]
        w.close()
    assert ev == ["created", "suspended", "code_accepted", "resumed"]


def test_lazy_import(tmp_path):
    code = f"""
import sys, json
from tests.extras_world import World, T0, MIN
w = World({str(tmp_path)!r})
w.process(T0)
w.copy_proposal()
w.run(T0 + MIN, T0 + 10 * MIN)
assert len(w.extras_rows()) == 1
print(json.dumps(sorted(m for m in ("paperbot.agents.newlab_signals", "scipy", "paperbot.newlab_live")
                        if m in sys.modules)))
"""
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    # newlab_live itself is imported by bind (a light module); newlab_signals and scipy are not
    assert json.loads(r.stdout.strip().splitlines()[-1]) == ["paperbot.newlab_live"]

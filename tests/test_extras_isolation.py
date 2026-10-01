"""Extras never stop the runner and never reach the original accounts (design 11.5).

Each case runs the same scripted market and signals twice through the real runner (tests/extras_world.py): once
without any extras code, once with a copy and a new-strategy account and the fault injected. The originals'
trades, outcomes, alerts and engine states must be identical, and the runner must keep going. The full
195-account proof on the synthetic feed is tests/test_extras_parity.py; the budget run uses the real
new-strategy code on full-length windows."""

import json
import os
import sqlite3
import sys
import time

import numpy as np
import pytest

from paperbot import extras as X
from paperbot.accounts import HeldEngine
from paperbot.engine import engine_state
from tests.extras_world import FIVE, HOUR, MIN, T0, World

ORIG = ("V45_AMB@15m", "V45_AMB@5m", "N17_KC_RSI@5m", "S2_ST_ROC@15m", "RANDOM_1@5m")
END = T0 + 3 * HOUR


def _px(i):
    rng = np.random.default_rng(42)
    return 100 * float(np.exp(np.cumsum(rng.normal(0, 0.002, 400))[i % 400]))


def _script(w):
    """Signals for some originals at their boundaries (deterministic)."""
    for k, b in enumerate(range(T0 + 5 * MIN, END, 5 * MIN)):
        ctx = {"regime": "trend_down" if k % 2 else "trend_up", "adx": 25.0}
        w.service.fire[(b, "5m")] = [("V45_AMB@5m", 1 if k % 2 else -1, "BTCUSDT", dict(ctx)),
                                     ("N17_KC_RSI@5m", -1, "ETHUSDT", dict(ctx))]
        if b % (15 * MIN) == 0:
            w.service.fire[(b, "15m")] = [("V45_AMB@15m", 1, "SOLUSDT", dict(ctx)),
                                          ("S2_ST_ROC@15m", -1, "BTCUSDT", dict(ctx))]


def _run(tmp, extras=True, fault=None, restart=False, restart_kw=None, **kw):
    w = World(tmp, hist=True, extras=extras, strategies=("V45_AMB", "N17_KC_RSI", "S2_ST_ROC"), tfs=("5m", "15m"),
              **kw)
    _script(w)
    w.process(T0)
    if extras:
        w.copy_proposal("V45_AMB", "15m", {"template": "stop_atr", "k": 2.5})
        w.newlab_proposal(0)
    if fault:
        fault(w, "before")
    t = T0 + MIN
    while t < END:
        if restart and t == T0 + HOUR:
            w.close()
            w = World(tmp, hist=True, extras=extras, strategies=("V45_AMB", "N17_KC_RSI", "S2_ST_ROC"),
                      tfs=("5m", "15m"), **dict(kw, **(restart_kw or {})))
            _script(w)
            if fault:
                fault(w, "restart")
        w.process(t, px=_px((t - T0) // MIN))
        if fault and t == T0 + 20 * MIN:
            fault(w, "mid")
        t += MIN
    return w


def _dump(w):
    c = w.store.conn
    out = {}
    for aid in ORIG:
        out[aid] = {
            "trades": c.execute("SELECT symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, equity_after, "
                                "data FROM trades WHERE account_id = ? ORDER BY id", (aid,)).fetchall(),
            "outcomes": c.execute("SELECT step_ts, status, reason, symbol, data FROM outcomes WHERE account_id = ? "
                                  "ORDER BY id", (aid,)).fetchall(),
            "alerts": c.execute("SELECT ts, level, text FROM alerts WHERE text LIKE ? ORDER BY rowid",
                                (f"[{aid}]%",)).fetchall(),
            "state": json.dumps(engine_state(w.book.engines[aid]), sort_keys=True),
            "signal_log": c.execute("SELECT bar_close, timeframe, symbol, side, status, data FROM signal_log WHERE "
                                    "strategy || '@' || timeframe = ? ORDER BY id", (aid,)).fetchall(),
        }
    return out


@pytest.fixture(scope="module")
def control(tmp_path_factory):
    w = _run(tmp_path_factory.mktemp("control"), extras=False)
    d = _dump(w)
    assert sum(len(v["trades"]) for v in d.values()) > 5 and sum(len(v["outcomes"]) for v in d.values()) > 20
    w.close()
    return d


def _check(control, w):
    got = _dump(w)
    for aid in ORIG:
        for k in control[aid]:
            assert got[aid][k] == control[aid][k], (aid, k)
    assert w.book.last_ts == END - MIN                              # the runner went on to the end


def _rewrite(w, aid, fn):
    c = sqlite3.connect(w.db)
    d = json.loads(c.execute("SELECT data FROM accounts WHERE account_id = ?", (aid,)).fetchone()[0])
    fn(d)
    c.execute("UPDATE accounts SET data = ? WHERE account_id = ?", (json.dumps(d), aid))
    c.commit()
    c.close()


def test_no_fault_extras_run(control, tmp_path):
    w = _run(tmp_path)
    assert {a["account_id"] for a in w.extras_rows()} == {"V45_AMB@15m~c1", "NL1@5m"}
    _check(control, w)
    assert w.store.conn.execute("SELECT COUNT(*) FROM outcomes WHERE account_id = 'V45_AMB@15m~c1'").fetchone()[0] > 0
    w.close()


def test_corrupt_spec_suspends(control, tmp_path):
    def fault(w, when):
        if when == "mid":
            w.store.commit()
            _rewrite(w, "NL1@5m", lambda d: d["spec"].update(direction="sideways"))
    w = _run(tmp_path, fault=fault, restart=True)
    assert w.ext.extras["NL1@5m"].status == "suspended" and w.ext.extras["NL1@5m"].code == "spec_invalid"
    assert isinstance(w.book.engines["NL1@5m"], X.GuardedEngine)              # it still steps (positions managed)
    assert not w.store.conn.execute("SELECT COUNT(*) FROM signal_log WHERE strategy = 'NL1' AND bar_close > ?",
                                    (T0 + HOUR,)).fetchone()[0]
    _check(control, w)
    w.close()


def test_corrupt_rule_holds(control, tmp_path):
    def fault(w, when):
        if when == "mid":
            w.store.commit()
            _rewrite(w, "V45_AMB@15m~c1", lambda d: d.update(rule={"template": "trail", "k": 1}))
    w = _run(tmp_path, fault=fault, restart=True)
    assert type(w.book.engines["V45_AMB@15m~c1"]) is HeldEngine
    assert w.state()["accounts"]["V45_AMB@15m~c1"]["status"] == "held"
    _check(control, w)
    w.close()


def test_grammar_version_change_has_no_effect_at_load(control, tmp_path, monkeypatch):
    def fault(w, when):
        if when == "mid":
            from paperbot.agents import newlab
            monkeypatch.setattr(newlab, "GRAMMAR_VERSION", "newlab-v2")
    w = _run(tmp_path, fault=fault, restart=True)
    assert w.ext.extras["NL1@5m"].status == "active"                       # the runtime's own frozen v1 table
    _check(control, w)
    w.close()


def test_agents_unimportable(control, tmp_path, monkeypatch):
    import paperbot.agents as pkg

    def fault(w, when):
        if when == "before":
            for m in ("actions", "labtests", "newlab"):
                monkeypatch.setitem(sys.modules, "paperbot.agents." + m, None)
                monkeypatch.delattr(pkg, m, raising=False)
    w = _run(tmp_path, fault=fault, restart=True)
    assert not w.extras_rows()
    assert {w.state()["refused"][p]["code"] for p in w.state()["refused"]} == {"gate_code_unavailable"}
    _check(control, w)
    w.close()


def test_shrunken_maxlen_not_ready(control, tmp_path):
    w = _run(tmp_path, restart=True, restart_kw={"maxlen": 50})          # the history kept shrank (a code change)
    assert "NL1@5m" not in w.ext.newlab.specs and w.ext.ready.get("NL1@5m")
    assert any("아직 신호를 계산하지 않음" in t for (t,) in w.store.conn.execute("SELECT text FROM alerts"))
    _check(control, w)
    w.close()


def test_changed_pin_suspends(control, tmp_path):
    def fault(w, when):
        if when == "mid":
            w.store.commit()
            _rewrite(w, "NL1@5m", lambda d: d["code"].update(context="0" * 64))
    w = _run(tmp_path, fault=fault, restart=True)
    assert (w.ext.extras["NL1@5m"].status, w.ext.extras["NL1@5m"].code) == ("suspended", "code_changed")
    _check(control, w)
    w.close()


def test_np_int64_in_copy_meta_refused(control, tmp_path, monkeypatch):
    real = X.derive

    def derive(rule, sig, aid):
        d = real(rule, sig, aid)
        if d is not None:
            d.meta["bad"] = np.int64(1)
        return d
    monkeypatch.setattr(X, "derive", derive)
    w = _run(tmp_path)
    assert w.book.engines["V45_AMB@15m~c1"].pending == [] and not w.store.conn.execute(
        "SELECT COUNT(*) FROM outcomes WHERE account_id = 'V45_AMB@15m~c1' AND status != 'FILTERED'").fetchone()[0]
    assert any("JSON" in t for (t,) in w.store.conn.execute("SELECT text FROM alerts WHERE text LIKE '[extra]%'"))
    _check(control, w)
    w.close()


def test_exception_in_guarded_step_holds(control, tmp_path):
    def fault(w, when):
        if when == "mid":
            e = w.book.engines["NL1@5m"]

            def boom(*a, **k):
                raise ZeroDivisionError("injected")
            e._mark_to_market = boom
    w = _run(tmp_path, fault=fault)
    e = w.book.engines["NL1@5m"]
    assert e.held and w.state()["accounts"]["NL1@5m"]["code"] == "fault"
    json.dumps(engine_state(e))
    assert any(m[0] == "CRITICAL" and "NL1@5m" in m[1] for m in w.notifier.messages)
    _check(control, w)
    w.close()


def test_exception_in_phase2_rolled_back_and_retried(control, tmp_path, monkeypatch):
    calls = {"n": 0}
    real = X.Extras.create

    def create(self, *a, **k):
        aid = real(self, *a, **k)
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("injected after add_extra")
        return aid
    monkeypatch.setattr(X.Extras, "create", create)
    w = _run(tmp_path)
    rows = w.extras_rows()
    assert {a["account_id"] for a in rows} == {"V45_AMB@15m~c1", "NL1@5m"}
    assert {a["created_ts"] for a in rows} == {T0 + 10 * MIN}                 # rolled back at 5m, created at 10m
    assert w.state()["health"]["errors"] == 1
    _check(control, w)
    w.close()


def test_hook_raising_past_its_guard(control, tmp_path, monkeypatch):
    def boom(self, *a, **k):
        raise RuntimeError("past the guard")
    monkeypatch.setattr(X.Extras, "_phase", boom)
    w = _run(tmp_path)
    assert w.runner.post_boundary is None and w.runner.post_boundary_errors == 3
    assert sum(1 for m in w.notifier.messages if m[0] == "CRITICAL" and "boundary hook failed" in m[1]) == 3
    _check(control, w)
    w.close()


# ============================================================================ the budget run (real newlab code)
def _budget_world(tmp, budget_s):
    from collections import deque
    from tests.extras_world import bootstrap
    w = World(tmp, hist=False, strategies=tuple(__import__("tests.extras_world", fromlist=["names36"]).names36()[:10]),
              tfs=("5m", "15m", "30m", "1h"))
    for s in w.service.hist:
        w.service.hist[s] = deque(maxlen=116_064)
    midnight = T0 + 86_400_000
    bootstrap(w.service, midnight - 5 * MIN, n=116_064)
    w.ext.newlab_factory = None                               # the real windows
    w.ext.cfg.budget_s = budget_s
    return w, midnight


@pytest.mark.parametrize("budget_s", [20.0, 0.05])
def test_budget_real_newlab_code_at_midnight(tmp_path, budget_s):
    """Ten new-strategy accounts (four on 4h) and ten copies; one 00:00 boundary where every timeframe is due."""
    w, midnight = _budget_world(tmp_path, budget_s)
    t = midnight - 11 * MIN
    w.now = t
    w.process(t)
    from paperbot.agents import newlab as NL
    specs = [("4h", "ema_cross", {"fast": 9, "slow": 21}), ("4h", "psar_flip", {}), ("4h", "rsi_cross50", {}),
             ("4h", "macd_hist_zero", {}), ("1h", "obv_cross", {}), ("30m", "bb_break", {}),
             ("15m", "supertrend_flip", {"length": 10, "mult": 3.0}), ("5m", "ema_cross", {"fast": 9, "slow": 21}),
             ("1h", "donchian_break", {"length": 55}), ("30m", "stoch_zone", {})]
    for tf, fam, p in specs:
        sp = NL.normalize_spec({"timeframe": tf, "entry": {"family": fam, "params": p}, "direction": "both"})
        from tests.extras_harness import add_newlab_proposal
        add_newlab_proposal(w.agents, w.inbox, sp, w.now)
    names = __import__("tests.extras_world", fromlist=["names36"]).names36()[:10]
    for k, s in enumerate(names):
        tf = ("5m", "15m", "30m", "1h")[k % 4]
        w.copy_proposal(s, tf, {"template": "stop_atr", "k": 2.5})
    w.run(t + MIN, midnight - 5 * MIN)                        # created at midnight - 5m
    assert len(w.extras_rows()) == 20, w.state()["refused"]
    t0 = time.monotonic()
    w.run(midnight - 5 * MIN, midnight)                       # the 00:00 boundary: 5m..4h due
    h = w.state()["health"]
    if budget_s >= 20:
        assert h["budget_skips"] == 0 and h["errors"] == 0
        assert h["phase2_ms"] < 20_000
        print(f"\nphase2 at 00:00 with 10 newlab + 10 copies: {h['phase2_ms']} ms (wall {time.monotonic() - t0:.1f}s)")
        assert h["newlab_jobs"] >= 6 * 5                      # every (coin, timeframe) job ran
    else:
        assert h["budget_skips"] > 0 and h["errors"] == 0
        assert any("시간 예산" in t for (t,) in w.store.conn.execute("SELECT text FROM alerts"))
    w.close()

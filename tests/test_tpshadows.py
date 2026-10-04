"""Fixed take-profit shadows (docs/observation-shadows-4.md, paperbot/obsshadows.py VARIANTS4): the take-profit exit
rules on synthetic 1m paths, the rows of the existing variants unchanged, the nightly report, and the numbers in the
Thursday packet (agents/riskreward.py: shadow_summary, tp_turns, tp_variants)."""

import hashlib
import json
import os
from dataclasses import asdict, replace

import numpy as np
import pytest

from paperbot import Bar
from paperbot.agents import riskreward as RR
from paperbot.config import V3_SYMBOLS, V3_TRADE_TFS
from paperbot.daily3 import _alone, make_signal
from paperbot.ladder import net_roe, roe_price
from paperbot.obsshadows import (CURVE_VARIANTS, MARGIN_FRAC, MARGIN_LEVERAGE4, TP_LADDER, TP_R, TP_VARIANTS, VARIANTS,
                                 VARIANTS3, VARIANTS4, NoTakeProfitPolicy, SameLeveragePolicy, curve_rows, curve_view,
                                 rule_margin_fracs, run_alone, run_alone_tp, summarize, symbol_steps, trade_shadows,
                                 variant_settings, write_curves)
from paperbot.sizing import size_position
from paperbot.store3 import Store3

from test_levstop import (ATR, BR, ENTRY, I0, REF, RT, ST, SYM, V45, _bar, _by_kind, _db, _flat, _row, _sh)
from test_rooms import DAY, MIN, S, World, kst

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R = 2 * ATR                                          # the initial stop distance (2 ATR) from the reference price
STOP = REF - R
SLIP, TAKER = ST.slippage_frac, ST.taker_fee
LEV = size_position(ST, ST.initial_equity, 1, ENTRY, STOP, "best", BR[SYM], atr=ATR).leverage


def tp_of(k):
    return REF + k * R


def _steps(*bars):
    """Flat 1m bars up to and including the entry bar I0, then the given (o, h, l, c[, mark low]) bars."""
    steps = _flat(I0 + 1)
    for j, b in enumerate(bars):
        ts = (I0 + 1 + j) * MIN
        o, h, lo, c = b[:4]
        bar = _bar(ts, o, h, lo, c)
        if len(b) > 4:                               # a mark-price low apart from the last price
            bar = Bar(SYM, ts, ts + MIN - 1, o, h, lo, c, o, h, b[4], c, volume=1.0)
        steps.append((ts, {SYM: bar}, {}))
    return symbol_steps(steps, SYM)


def _tp(v, ss, k=None, settings=None):
    s = settings or variant_settings(ST, v)
    pol = (SameLeveragePolicy if v in TP_LADDER else NoTakeProfitPolicy)(s, LEV)
    return run_alone_tp(s, BR, {}, make_signal(_row()), ss, I0, TP_R[v] if k is None else k, policy=pol)


# ---------------------------------------------------------------- pre-registration
def test_preregistration_4_hash_matches_and_earlier_docs_unchanged():
    for name in ("observation-shadows", "observation-shadows-2", "observation-shadows-3", "observation-shadows-4"):
        line = open(os.path.join(ROOT, "docs", f"{name}.sha256")).read().split()
        body = open(os.path.join(ROOT, "docs", f"{name}.md"), "rb").read()
        assert line[1] == f"docs/{name}.md" and hashlib.sha256(body).hexdigest() == line[0]
    doc = open(os.path.join(ROOT, "docs", "observation-shadows-4.md"), encoding="utf-8").read()
    for v in VARIANTS4:
        assert f"`{v}`" in doc
    assert "research/exitstyle" in doc and "30일째 체크포인트" in doc and "shadow_curves" in doc
    assert "qlev" not in doc                                  # the entry-strength leverage is the real rule (= base)


def test_variant_list_and_settings():
    assert TP_VARIANTS == ("tp1R", "tp1.5R", "tp2R", "tp3R", "ladder_cap2R")
    assert VARIANTS4 == TP_VARIANTS + ("lev20m20", "lev30m30", "lev40m40", "lev50m50")
    assert MARGIN_LEVERAGE4 == {"lev20m20": 20, "lev30m30": 30, "lev40m40": 40, "lev50m50": 50}
    for v, lev in MARGIN_LEVERAGE4.items():
        s = variant_settings(ST, v)
        assert [(t.name, t.margin_frac, t.leverages) for t in s.tiers] == [("best", lev / 100, (lev,))]
        assert rule_margin_fracs(s)[lev] == lev / 100 and s.max_loss_frac == ST.max_loss_frac
        assert s.liq_buffer_atr_mult == ST.liq_buffer_atr_mult and s.tp_mode == "ladder"
    # the existing lev30 / lev40 / lev50 keep the tier table's 30 / 40 / 40%
    assert [variant_settings(ST, v).tiers[0].margin_frac for v in ("lev30", "lev40", "lev50")] == [0.30, 0.40, 0.40]
    assert rule_margin_fracs(ST) == MARGIN_FRAC                  # the rule's shares (tier table of 2026-10-04)
    assert CURVE_VARIANTS == ("base", "lev10", "lev20", "lev30", "lev40", "lev50", *MARGIN_LEVERAGE4)
    assert TP_R == {"tp1R": 1.0, "tp1.5R": 1.5, "tp2R": 2.0, "tp3R": 3.0, "ladder_cap2R": 2.0}
    assert not set(VARIANTS4) & set(VARIANTS + VARIANTS3) and not set(VARIANTS4) & {"limit", "skipped", "TP"}
    for v in ("tp1R", "tp1.5R", "tp2R", "tp3R"):
        s = variant_settings(ST, v)
        assert s.tp_mode == "fixed" and s.ladder_first_lock == ST.ladder_first_lock and s.tiers == ST.tiers
    assert variant_settings(ST, "ladder_cap2R") is ST and ST.tp_mode == "ladder"
    assert LEV in MARGIN_FRAC and RR.SHADOW_VARIANTS4 == TP_VARIANTS and RR.SHADOW_MARGIN4 == tuple(MARGIN_LEVERAGE4)
    assert RR.MARGIN_FRAC == rule_margin_fracs(ST)


# ---------------------------------------------------------------- the take-profit exit rules
def test_take_profit_touch_exits_at_the_take_profit_with_taker_fee_and_slippage():
    # bar 1 reaches 2.25 R: 1R / 1.5R / 2R exit there at their own take-profit, 3R stays and is stopped on bar 2
    ss = _steps((ENTRY, tp_of(2.25), ENTRY - 0.01, tp_of(2.2)), (tp_of(2.2), tp_of(2.2), STOP - 0.1, STOP - 0.05))
    for v in ("tp1R", "tp1.5R", "tp2R"):
        tr, ok, tp = _tp(v, ss)
        assert ok and tr.exit_reason == "TP" and tp == pytest.approx(tp_of(TP_R[v]))
        assert tr.exit_price == pytest.approx(tp * (1 - SLIP)) and tr.exit_time == (I0 + 2) * MIN - 1
        assert tr.leverage == LEV and tr.margin == pytest.approx(ST.initial_equity * MARGIN_FRAC[LEV], rel=1e-6)
        assert tr.fees == pytest.approx(tr.qty * ENTRY * TAKER + tr.qty * tr.exit_price * TAKER)   # taker, not maker
        assert tr.roe > 0 and tr.lock_roe is None
    tr, ok, tp = _tp("tp3R", ss)
    assert ok and tr.exit_reason == "SL" and tr.exit_price == pytest.approx(STOP * (1 - SLIP)) and tr.roe < 0
    # a larger take-profit earns more when it is reached
    roes = [_tp(v, ss)[0].roe for v in ("tp1R", "tp1.5R", "tp2R")]
    assert roes == sorted(roes)


def test_stop_and_take_profit_on_the_same_bar_is_a_stop():
    ss = _steps((ENTRY, tp_of(2.5), STOP - 0.05, ENTRY))
    for v in ("tp1R", "tp2R", "ladder_cap2R"):
        tr, ok, _tp_px = _tp(v, ss)
        assert ok and tr.exit_reason == "SL" and tr.exit_price == pytest.approx(STOP * (1 - SLIP)) and tr.roe < 0


def test_a_gap_past_the_take_profit_fills_at_the_bar_open():
    ss = _steps((ENTRY, tp_of(1.2), ENTRY - 0.01, tp_of(1.1)),            # under 2R
                (tp_of(2.5), tp_of(2.6), tp_of(2.4), tp_of(2.5)))         # opens beyond 2R
    tr, ok, tp = _tp("tp2R", ss)
    assert ok and tr.exit_reason == "TP" and tr.exit_time == (I0 + 2) * MIN
    assert tr.exit_price == pytest.approx(tp_of(2.5) * (1 - SLIP)) and tr.exit_price > tp
    assert tr.fees == pytest.approx(tr.qty * ENTRY * TAKER + tr.qty * tr.exit_price * TAKER)
    tr1, _ok, tp1 = _tp("tp1R", ss)                                        # 1R was touched on bar 1, at 1R
    assert tr1.exit_time == (I0 + 2) * MIN - 1 and tr1.exit_price == pytest.approx(tp1 * (1 - SLIP))


def test_liquidation_comes_before_the_take_profit():
    # the mark price reaches liquidation while the last price stays above the stop and touches 2R
    liq = SameLeveragePolicy(ST, LEV).size(ST.initial_equity, replace(make_signal(_row()), stop_price=STOP), ENTRY,
                                           BR[SYM], {}).liq_price
    assert STOP > liq                                     # the rules keep the stop inside liquidation
    ss = _steps((ENTRY, tp_of(2.5), STOP + 0.05, tp_of(2.2), liq - 0.1))
    for v in ("tp2R", "ladder_cap2R"):
        tr, ok, _tp_px = _tp(v, ss)
        assert ok and tr.exit_reason == "LIQ" and tr.roe < -0.99
    # a gap beyond the take-profit while the mark opens beyond liquidation: the engine's liquidation
    steps = _flat(I0 + 1)
    ts = (I0 + 1) * MIN
    steps.append((ts, {SYM: Bar(SYM, ts, ts + MIN - 1, tp_of(2.5), tp_of(2.6), tp_of(2.4), tp_of(2.5),
                                liq - 0.1, liq, liq - 0.2, liq, volume=1.0)}, {}))
    tr, ok, _tp_px = _tp("tp2R", symbol_steps(steps, SYM))
    assert ok and tr.exit_reason == "LIQ"


def test_the_entry_bar_is_not_watched_for_the_take_profit():
    steps = _flat(I0)
    steps.append((I0 * MIN, {SYM: _bar(I0 * MIN, ENTRY, tp_of(2.5), ENTRY - 0.01, ENTRY)}, {}))   # entry bar
    steps.append(((I0 + 1) * MIN, {SYM: _bar((I0 + 1) * MIN, ENTRY, tp_of(1.5), STOP - 0.1, STOP - 0.1)}, {}))
    ss = symbol_steps(steps, SYM)
    tr, ok, _tp_px = _tp("tp2R", ss)
    assert ok and tr.exit_reason == "SL"                  # 2R only on the entry bar (part of it before the fill)
    tr, ok, _tp_px = _tp("tp1R", ss)
    assert ok and tr.exit_reason == "SL"                  # 1R on the next bar, but the stop on the same bar


def test_ladder_cap_exits_at_2r_and_a_lock_hit_on_that_bar_comes_first():
    lev_roe = lambda px: net_roe(1, ENTRY, px, LEV, RT)          # noqa: E731
    # bar 1 stays under the first trigger, bar 2 reaches 2R: ladder_cap2R takes 2R, the base locks and goes on
    low = ENTRY + 0.01
    assert lev_roe(tp_of(0.6)) < ST.ladder_first_lock + ST.ladder_trigger_gap
    ss = _steps((ENTRY, tp_of(0.6), low, tp_of(0.5)), (tp_of(0.5), tp_of(2.1), tp_of(0.45), tp_of(2.0)),
                (tp_of(2.0), tp_of(2.0), STOP - 0.1, STOP - 0.1))
    tr, ok, tp = _tp("ladder_cap2R", ss)
    assert ok and tr.exit_reason == "TP" and tr.exit_price == pytest.approx(tp_of(2.0) * (1 - SLIP))
    base, ok = run_alone(ST, BR, {}, make_signal(_row()), ss, I0, policy=SameLeveragePolicy(ST, LEV))
    assert ok and base.exit_reason == "LOCK" and base.exit_time > tr.exit_time
    # bar 1 arms a lock; bar 2 touches 2R but also the lock stop: LOCK, not TP
    hi = tp_of(1.8)
    lock = ST.ladder.lock_for(lev_roe(hi))
    assert lock is not None
    lock_px = roe_price(1, ENTRY, LEV, lock, RT, 0.0)
    ss = _steps((ENTRY, hi, ENTRY - 0.01, hi), (hi, tp_of(2.2), lock_px - 0.02, tp_of(2.1)))
    tr, ok, _tp_px = _tp("ladder_cap2R", ss)
    assert ok and tr.exit_reason == "LOCK" and tr.lock_roe == pytest.approx(lock)
    tr, ok, _tp_px = _tp("tp2R", ss)                          # no ladder: the 2 ATR stop is far, 2R is taken
    assert ok and tr.exit_reason == "TP"


def _walk(n=3000, seed=3, funding_every=7):
    rng = np.random.default_rng(seed)
    steps, px = [], REF
    for i in range(n):
        o = px
        c = o * np.exp(rng.normal(0, 0.0006))
        bar = Bar(SYM, i * MIN, i * MIN + MIN - 1, o, max(o, c) * 1.0003, min(o, c) * 0.9997, c,
                  o, max(o, c) * 1.0003, min(o, c) * 0.9997, c, volume=1.0)
        steps.append((i * MIN, {SYM: bar}, {SYM: 0.0003} if i % funding_every == 0 else {}))
        px = c
    return steps


def test_an_unreachable_take_profit_equals_the_engine_run_with_funding():
    funded = compared = 0
    for seed in range(1, 9):
        ss = symbol_steps(_walk(seed=seed), SYM)
        for side in (1, -1):
            sig = make_signal(dict(_row(side=side), ref_price=ss[I0][1][SYM].open))
            # the ladder (ladder_cap2R's settings) and no ladder (tp1R's), take-profit out of reach: the runner's
            # funding and exit order are exactly the engine's
            for v, pol in (("ladder_cap2R", SameLeveragePolicy), ("tp1R", NoTakeProfitPolicy)):
                s = variant_settings(ST, v)
                ref, ok = run_alone(s, BR, {}, sig, ss, I0, policy=pol(s, LEV))
                got, ok2, _tp_px = run_alone_tp(s, BR, {}, sig, ss, I0, 1e6, policy=pol(s, LEV))
                assert ok == ok2 and (got is None) == (ref is None)
                if ref is not None:
                    assert asdict(got) == asdict(ref)
                    funded += ref.funding != 0
                    compared += 1
    assert funded > 0 and compared >= 24


def test_funding_is_paid_while_held_and_not_on_the_bar_it_leaves():
    steps = _flat(I0 + 1)
    for j, b in enumerate(((ENTRY, ENTRY + 0.01, ENTRY - 0.01, ENTRY), (ENTRY, tp_of(1.1), ENTRY - 0.01, ENTRY))):
        ts = (I0 + 1 + j) * MIN
        steps.append((ts, {SYM: _bar(ts, *b)}, {SYM: 0.001}))
    tr, ok, _tp_px = _tp("tp1R", symbol_steps(steps, SYM))
    assert ok and tr.exit_reason == "TP"
    assert tr.funding == pytest.approx(tr.qty * ENTRY * 0.001)          # bar 1 only (marks at ENTRY)


# ---------------------------------------------------------------- trade_shadows rows and the summary
def test_trade_shadows_extra4_rows_and_summary(tmp_path):
    steps = _flat(I0 + 1)
    for j, b in enumerate(((ENTRY, tp_of(1.6), ENTRY - 0.01, tp_of(1.5)), (tp_of(1.5), tp_of(1.5), STOP - 0.1, STOP - 0.1))):
        ts = (I0 + 1 + j) * MIN
        steps.append((ts, {SYM: _bar(ts, *b)}, {}))
    steps += [((I0 + 3 + i) * MIN, {SYM: _bar((I0 + 3 + i) * MIN, 99.4, 99.5, 99.3, 99.4)}, {}) for i in range(5)]
    conn, actual = _db(tmp_path, _row(tf="4h"), steps)
    assert actual.leverage == LEV
    rows, info = trade_shadows(ST, BR, {}, conn, "d", 0, len(steps) * MIN, steps, make_signal, extra4=True)
    k = _by_kind(rows)
    assert len(rows) == len(VARIANTS) + len(VARIANTS4) and info["extra4"] is True and info["no_leverage4"] == 0
    assert "extra3" not in info
    assert [k[v]["exit_reason"] for v in TP_VARIANTS] == ["TP", "TP", "SL", "SL", "LOCK"]
    for v in TP_VARIANTS:
        d = json.loads(k[v]["data"])
        assert d["tp_r"] == TP_R[v] and d["same_leverage"] == LEV and d["leverage"] == LEV
        assert d["ladder"] is (v == "ladder_cap2R") and d["tp_price"] == pytest.approx(tp_of(TP_R[v]))
        assert d["pnl_equity"] == pytest.approx(k[v]["roe"] * MARGIN_FRAC[LEV]) and k[v]["timeframe"] == "4h"
    rep = summarize(rows, info)
    assert rep["tp1R"]["tp_exits"] == 1 and rep["tp2R"]["tp_exits"] == 0 and rep["tp1R"]["leverage_differs"] == 0
    assert rep["tp1R"]["base"]["paired"] == 1 and {"vs_base_pnl_equity", "better_than_base"} <= set(rep["tp1R"]["base"])
    assert rep["tp2R"]["base"]["worse_than_base"] == 1.0                         # stopped, the base locked profit
    assert set(VARIANTS4) <= set(rep) and not set(VARIANTS3) & set(rep)
    entered = 0
    for v, lev in MARGIN_LEVERAGE4.items():      # the rules' checks at lev x / lev %: entered or not entered
        ok = size_position(variant_settings(ST, v), ST.initial_equity, 1, ENTRY, STOP, "best", BR[SYM], atr=ATR).ok
        d = json.loads(k[v]["data"])
        assert d["margin_frac"] == lev / 100 and "tp_exits" not in rep[v]
        if ok:
            entered += 1
            assert d["leverage"] == lev and k[v]["exit_reason"] in ("LOCK", "SL") and rep[v]["base"]["paired"] == 1
            assert d["pnl_equity"] == pytest.approx(k[v]["roe"] * lev / 100)
        else:
            assert k[v]["roe"] is None and k[v]["resolved"] == 1 and rep[v]["rejected"] == 1
    assert entered >= 2
    # a trade at a leverage outside the tier table gets no take-profit rows (the margin rows do not depend on it)
    conn.execute("UPDATE trades SET data = json_set(data, '$.leverage', 25)")
    rows2, info2 = trade_shadows(ST, BR, {}, conn, "d", 0, len(steps) * MIN, steps, make_signal, extra4=True)
    assert info2["no_leverage4"] == 1 and not {r["kind"] for r in rows2} & set(TP_VARIANTS)
    assert {r["kind"] for r in rows2} >= set(MARGIN_LEVERAGE4)


def _random_day(tmp_path, n_trades=32, seed=11):
    """A synthetic day of trades on the run's timeframes only (15m / 30m / 1h / 4h; 5m is gone)."""
    rng = np.random.default_rng(seed)
    n = DAY // MIN + 3 * 60
    steps, px = [], {s: 100.0 for s in V3_SYMBOLS}
    for i in range(n):
        bars = {}
        for s in V3_SYMBOLS:
            o = px[s]
            c = o * np.exp(rng.normal(0, 0.0012))
            bars[s] = Bar(s, i * MIN, i * MIN + MIN - 1, o, max(o, c) * 1.0004, min(o, c) * 0.9996, c,
                          o, max(o, c) * 1.0004, min(o, c) * 0.9996, c, volume=1.0)
            px[s] = c
        steps.append((i * MIN, bars, {s: 0.0001 for s in V3_SYMBOLS} if i % 480 == 0 else {}))
    store = Store3(str(tmp_path / "p.db"))
    made = 0
    while made < n_trades:
        tf = V3_TRADE_TFS[made % len(V3_TRADE_TFS)]
        bc = int(rng.integers(1, n - 600)) * MIN
        s = V3_SYMBOLS[int(rng.integers(6))]
        row = {"bar_close": bc, "timeframe": tf, "strategy": f"X{made}", "symbol": s,
               "side": 1 if rng.random() < 0.5 else -1, "atr": float(rng.choice([0.1, 0.25, 0.6])),
               "ref_price": steps[bc // MIN][1][s].open, "ref_time": bc, "delay_ms": 0, "status": "SUBMITTED"}
        t, ok = _alone(ST, BR, {}, make_signal(row), steps, bc // MIN)
        if t is None or t.exit_time >= DAY:
            continue
        store.log_signals([row])
        store.trade(f"X{made}@{tf}", t)
        made += 1
    store.commit()
    return store, steps


def test_existing_variants_are_unchanged_by_the_take_profit_shadows(tmp_path):
    assert "5m" not in V3_TRADE_TFS
    store, steps = _random_day(tmp_path)
    old, info_old = trade_shadows(ST, BR, {}, store.conn, "d", 0, DAY, steps, make_signal, quality=True, extra3=True)
    new, info_new = trade_shadows(ST, BR, {}, store.conn, "d", 0, DAY, steps, make_signal, quality=True, extra3=True,
                                  extra4=True)
    n = info_new["closed"]
    assert n == 32 and len(new) == len(old) + n * len(VARIANTS4)
    assert [r for r in new if r["kind"] not in VARIANTS4] == old                  # byte-identical rows, same order
    rep_old, rep_new = summarize(old, info_old), summarize(new, info_new)
    for v in (*VARIANTS, *VARIANTS3, "quality"):
        assert rep_new[v] == rep_old[v]
    assert {k: x for k, x in info_new.items() if k not in ("extra4", "no_leverage4")} == info_old
    assert len({r["key"] for r in new}) == len(new)
    by_tf = {}
    for r in new:
        if r["kind"] in TP_R:
            by_tf.setdefault(r["timeframe"], set()).add(r["kind"])
            d = json.loads(r["data"])
            if r["roe"] is not None:
                assert d["leverage"] == d["actual_leverage"] == d["same_leverage"]
                if r["exit_reason"] == "TP":
                    tp = d["tp_price"]
                    assert r["roe"] > -0.5 and tp is not None
    assert set(by_tf) == set(V3_TRADE_TFS) and all(v == set(TP_VARIANTS) for v in by_tf.values())
    for r in new:
        if r["kind"] in MARGIN_LEVERAGE4 and r["roe"] is not None:
            d = json.loads(r["data"])
            assert d["leverage"] == MARGIN_LEVERAGE4[r["kind"]] and d["pnl_equity"] == pytest.approx(r["roe"] * d["margin_frac"])
    assert sum(rep_new[v]["tp_exits"] for v in TP_VARIANTS) > 0
    # more R, fewer take-profit exits
    tps = [rep_new[v]["tp_exits"] for v in ("tp1R", "tp1.5R", "tp2R", "tp3R")]
    assert tps == sorted(tps, reverse=True)


def test_nightly_report_has_the_take_profit_variants(tmp_path, monkeypatch):
    import sqlite3

    import paperbot.daily3 as D
    from test_daily3 import _live_day
    store, steps = _live_day(str(tmp_path / "p.db"))
    monkeypatch.setattr(D, "fetch_steps", lambda rest, syms, a, b: [s for s in steps if a <= s[0] < b])

    class Rest:
        def server_time(self):
            return DAY + 2 * MIN

    out = sqlite3.connect(str(tmp_path / "d.db"))
    out.executescript(D.SCHEMA)
    rep = D.run_day(store.conn, out, Rest(), ST, BR, {}, "1970-01-01")
    tv = rep["shadows"]["trade_variants"]
    closed = tv["closed"]
    kinds = dict(out.execute("SELECT kind, COUNT(*) FROM shadows GROUP BY kind").fetchall())
    assert tv["extra4"] is True and tv["no_leverage4"] == 0 and closed > 0
    for v in VARIANTS4:
        assert kinds[v] == closed and tv[v]["trades"] == closed and ("tp_exits" in tv[v]) == (v in TP_R)
        assert {"paired", "vs_base_pnl_equity", "better_than_base", "worse_than_base"} <= set(tv[v]["base"])
    for v in VARIANTS3:
        assert kinds[v] == closed                                                 # still there
    # the night's shadow equity curves
    cur = out.execute("SELECT account_id, variant, equity_end, bust_day, n_trades FROM shadow_curves").fetchall()
    assert rep["shadows"]["curves"]["rows"] == len(cur) > 0 and {c[1] for c in cur} <= set(CURVE_VARIANTS)
    assert {c[1] for c in cur} >= {"base", "lev10", "lev20m20"}
    assert sum(c[4] for c in cur if c[1] == "base") == tv["base"]["resolved"]
    view = curve_view(out)
    assert view["days"] == ["1970-01-01"] and view["by_variant"]["base"]["accounts"] == len({c[0] for c in cur})
    json.dumps(rep)


# ---------------------------------------------------------------- riskreward: summary, tp_turns, packet
@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def _seed_tp(world):
    a, b = f"{S}@15m", f"{V45}@1h"
    for bc, (base, t1, t2, cap) in enumerate(((-0.08, -0.02, 0.03, -0.07), (0.02, 0.01, 0.01, 0.02))):
        _sh(world, "base", a, bc, base * 2.5, base, reason="SL" if base < 0 else "LOCK")
        _sh(world, "tp1R", a, bc, t1 * 2.5, t1, reason="SL" if t1 < 0 else "TP")
        _sh(world, "tp2R", a, bc, t2 * 2.5, t2, reason="TP")
        _sh(world, "ladder_cap2R", a, bc, cap * 2.5, cap, reason="SL" if cap < 0 else "LOCK")
    _sh(world, "base", b, 9, 0.05, 0.02)
    _sh(world, "tp1R", b, 9, -0.025, -0.01, reason="SL")
    _sh(world, "tp3R", b, 9, None, None, resolved=0)
    _sh(world, "tp1.5R", b, 9, None, None)                                     # not entered
    world.daily.commit()


def test_shadow_summary_and_tp_turns(world):
    _seed_tp(world)
    now = kst(2026, 10, 8, 11, 0)
    sh = RR.shadow_summary(world.daily, world.paper(), now - 7 * DAY, now)
    c = sh["strategies"][S]
    assert c["base"]["mean_eq"] == pytest.approx(-0.03)
    assert c["tp2R"]["mean_eq"] == pytest.approx(0.02) and c["tp2R"]["vs_base_eq"] == pytest.approx(0.05)
    assert c["tp2R"]["tp"] == 2 and c["tp1R"]["tp"] == 1 and "tp" not in c["ladder_cap2R"]
    assert (c["tp2R"]["better_share"], c["tp2R"]["worse_share"], c["tp2R"]["small"]) == (0.5, 0.5, True)
    v = sh["strategies"][V45]
    assert v["tp3R"] == {"trades": 0, "open": 1} and v["tp1.5R"] == {"trades": 0, "not_entered": 1}
    assert v["tp1R"]["worse_share"] == 1.0 and "tp1R" in sh["all"]
    tt = RR.tp_turns(sh["strategies"])
    assert [x["strategy"] for x in tt["tp2R"]["turns_positive"]] == [S] and tt["tp2R"]["turns_negative"] == []
    assert tt["tp2R"]["still_negative_n"] == 0
    assert [x["strategy"] for x in tt["tp1R"]["turns_negative"]] == [V45]        # base +0.02, 1R -0.01
    assert tt["tp1R"]["turns_positive"] == [] and tt["tp1R"]["still_negative_n"] == 2
    assert tt["ladder_cap2R"] == {"turns_positive": [], "turns_negative": [], "still_negative_n": 1}
    assert "tp3R" not in tt and "tp1.5R" not in tt                               # nothing compared: left out
    row = RR.shadow_brief4(c)
    assert set(row) == {"tp1R", "tp2R", "ladder_cap2R"} and len(row["tp2R"]) == len(RR.SHADOW4_COLUMNS)
    assert row["tp2R"][6] == 2                                                   # take-profit exits
    assert RR.shadow_brief4(v) == {"tp1R": RR.shadow_brief4(v)["tp1R"]}          # open / not-entered only: left out
    # the earlier variants are not affected by the take-profit rows
    assert RR.stop_turns(sh["strategies"]) == RR.stop_turns({k: {x: y for x, y in cs.items() if x not in RR.TP_SHADOWS}
                                                             for k, cs in sh["strategies"].items()})


def test_rr_packet_carries_the_take_profit_shadows_and_stays_bounded(world):
    from test_riskreward import seed
    from test_rooms import QUIET
    seed(world)
    _seed_tp(world)
    a = f"{S}@15m"
    _sh(world, "stopw1.5", a, 1, 0.05, 0.02)
    _sh(world, "lev30", a, 1, 0.1, 0.03)
    _sh(world, "lev20m20", a, 0, -0.1, 0.01)
    _sh(world, "lev20m20", a, 1, 0.1, 0.02)
    _sh(world, "lev50m50", a, 1, None, None)                                    # not entered
    world.daily.commit()
    pk = RR.rr_packet(world.paper(), world.daily, QUIET)
    tv = pk["shadows"]["tp_variants"]
    assert tv["doc"] == "docs/observation-shadows-4.md" and set(tv["variants_ko"]) == set(TP_VARIANTS)
    assert "계단 잠금을 이기지 못함" in tv["five_year"] and "−1.415%" in tv["five_year"]
    assert set(tv["by_strategy_since_start"][S]) == {"tp1R", "tp2R", "ladder_cap2R"}
    assert [x["strategy"] for x in tv["tp_turns"]["since_start"]["tp2R"]["turns_positive"]] == [S]
    assert "tp2R" in pk["shadows"]["all_strategies"]["since_start"]
    assert "new_variants" in pk["shadows"] and "lower_leverage" in pk["shadows"]                # earlier ones kept
    mv = pk["shadows"]["margin_variants"]
    assert mv["doc"] == "docs/observation-shadows-4.md" and set(mv["variants_ko"]) == set(RR.SHADOW_MARGIN4)
    assert mv["by_strategy_since_start"][S]["lev50m50"][-1] == 1 and len(mv["by_strategy_since_start"][S]["lev50m50"]) == len(RR.SHADOW3_COLUMNS)
    assert [x["strategy"] for x in mv["margin_turns"]["since_start"]["lev20m20"]["turns_positive"]] == [S]
    assert "lev30m30" not in pk["shadows"]["all_strategies"]["7d"]                              # empty: left out
    # the earlier size tests (test_riskreward < 16,000, test_levstop < 17,000) are unchanged; with take-profit rows
    # and margin rows filled in both windows here the packet is about 19.6 KB
    assert len(json.dumps(pk, ensure_ascii=False)) < 20_500
    # 36 strategies with every take-profit variant: the per-strategy section stays bounded
    cell = {"trades": 25, "mean_eq": -0.012345, "base_mean_eq": -0.023456, "vs_base_eq": 0.011111,
            "better_share": 0.583, "worse_share": 0.25, "tp": 9, "liq": 1, "base_liq": 2}
    many = {f"N{i:02d}_LONG_NAME": {v: dict(cell) for v in RR.SHADOW_VARIANTS4} for i in range(36)}
    big = {k: RR.shadow_brief4(v) for k, v in many.items()}
    assert len(json.dumps(big, ensure_ascii=False)) < 13_000                      # 5 short rows x 36 at most
    tt = RR.tp_turns({k: {**{v: {**cell, "mean_eq": 0.01} for v in RR.SHADOW_VARIANTS4}} for k in many})
    assert len(json.dumps(tt, ensure_ascii=False)) < 20_000 and tt["tp1R"]["still_negative_n"] == 0


def test_meeting_prompt_and_docs_mention_the_take_profit_shadows():
    from paperbot.agents import rooms as RM
    p = open(os.path.join(os.path.dirname(RM.__file__), "prompts3", RM.MEETING_FILE["rr_review"]), encoding="utf-8").read()
    for s in ("rr.shadows.tp_variants", "tp_turns", "ladder_cap2R", "docs/observation-shadows-4.md", "five_year",
              "이기지 못했습니다"):
        assert s in p
    assert "rr.shadows.margin_variants" in p and "lev50m50" in p and "margin_turns" in p
    d = open(os.path.join(ROOT, "docs", "agent-rooms.md"), encoding="utf-8").read()
    assert "docs/observation-shadows-4.md" in d and "tp_turns" in d and "research/exitstyle" in d
    assert "margin_turns" in d and "shadow_curves" in d


# ---------------------------------------------------------------- margin = leverage %: the safety checks, no fallback
def test_margin_leverage_variants_skip_on_a_failed_check_without_fallback(tmp_path):
    # a 2% stop (ATR 1.0): 50x x 50% is 12.5x equity -> ~25% at the stop (> 15%) and the stop beyond liquidation;
    # 20x x 20% is 4x equity -> ~8.5%: entered
    row = _row(atr=1.0)
    steps = _flat(I0 + 1)
    steps.append(((I0 + 1) * MIN, {SYM: _bar((I0 + 1) * MIN, ENTRY, ENTRY, REF - 2.1, REF - 2.0)}, {}))
    steps += [((I0 + 2 + i) * MIN, {SYM: _bar((I0 + 2 + i) * MIN, 98.0, 98.1, 97.9, 98.0)}, {}) for i in range(3)]
    conn, actual = _db(tmp_path, row, steps)
    rows, info = trade_shadows(ST, BR, {}, conn, "d", 0, len(steps) * MIN, steps, make_signal, extra4=True)
    k = _by_kind(rows)
    for v, lev in MARGIN_LEVERAGE4.items():
        dec = size_position(variant_settings(ST, v), ST.initial_equity, 1, ENTRY, REF - 2.0, "best", BR[SYM], atr=1.0)
        if dec.ok:
            assert json.loads(k[v]["data"])["leverage"] == lev and k[v]["exit_reason"] == "SL"
            assert k[v]["roe"] * lev / 100 == pytest.approx(json.loads(k[v]["data"])["pnl_equity"])
        else:
            assert (k[v]["roe"], k[v]["resolved"], k[v]["exit_reason"]) == (None, 1, None)   # not entered, no fallback
            assert "leverage" not in json.loads(k[v]["data"])
    assert k["lev50m50"]["roe"] is None and k["lev20m20"]["roe"] is not None
    rep = summarize(rows, info)
    assert rep["lev50m50"]["rejected"] == 1 and rep["lev50m50"]["base"]["paired"] == 0
    # P&L on equity with the variant's own margin share (20%)
    assert rep["lev20m20"]["mean_pnl_equity"] == pytest.approx(k["lev20m20"]["roe"] * 0.20)


# ---------------------------------------------------------------- shadow equity curves
def _crow(kind, aid, n, eq, exit_time, resolved=1, entered=True):
    return {"key": f"{kind}|{aid}|BTCUSDT|{n}", "kind": kind, "account_id": aid, "resolved": resolved,
            "roe": (eq * 2.5 if entered else None), "data": json.dumps(
                {"pnl_equity": eq if entered else None, "exit_time": exit_time})}


def test_curve_math_compounds_in_exit_order_and_stops_at_a_bust():
    a, b = "A@15m", "B@1h"
    rows = [_crow("base", a, 1, 0.10, 300), _crow("base", a, 2, -0.50, 100),       # exit order: -50% then +10%
            _crow("lev50m50", a, 1, -0.6, 100), _crow("lev50m50", a, 2, -0.6, 200), _crow("lev50m50", a, 3, -0.99, 300),
            _crow("lev50m50", a, 4, 0.5, 400),                                       # after the bust: not applied
            _crow("lev10", a, 1, 0.2, 100, resolved=0), _crow("lev20", a, 1, None, 100, entered=False),
            _crow("tp2R", a, 1, 0.3, 100), _crow("stopw1.5", a, 1, 0.3, 100),         # not curve variants
            _crow("base", b, 9, 0.02, 50)]
    out = {(r[1], r[2]): r for r in curve_rows({}, "2026-10-06", rows)}
    assert set(out) == {(a, "base"), (a, "lev50m50"), (b, "base")}               # no row without an applied trade
    assert out[(a, "base")][3:] == (pytest.approx(5000 * 0.5 * 1.1), None, 2)
    eq = 5000 * 0.4 * 0.4 * 0.01                                                    # 8.0 < 10: bust on the 3rd
    assert out[(a, "lev50m50")][3:] == (pytest.approx(eq), "2026-10-06", 3)
    # the next night continues from the last row; a bust curve gets no more rows
    prev = {(x[1], x[2]): (x[3], x[4], x[5]) for x in out.values()}
    nxt = {(r[1], r[2]): r for r in curve_rows(prev, "2026-10-07", [_crow("base", a, 5, 0.1, 500),
                                                                        _crow("lev50m50", a, 5, 0.5, 500)])}
    assert set(nxt) == {(a, "base")} and nxt[(a, "base")][3:] == (pytest.approx(5000 * 0.55 * 1.1), None, 3)
    assert curve_rows({}, "d", [_crow("base", a, 1, -1.2, 1)])[0][3:] == (0.0, "d", 1)   # never below 0


def test_write_curves_appends_nightly_replaces_a_rerun_and_the_view(tmp_path):
    import sqlite3
    db = sqlite3.connect(str(tmp_path / "d.db"))
    a, b, r = "A@15m", "B@1h", "RANDOM_1@15m"
    assert curve_view(db) == {"variants": [], "days": [], "start": 5000.0, "bust_below": 10.0, "by_variant": {}}
    i1 = write_curves(db, "2026-10-05", [_crow("base", a, 1, 0.10, 1), _crow("lev50m50", a, 1, -0.999, 1),
                                         _crow("base", r, 1, 0.5, 1)])
    assert i1 == {"rows": 3, "busts": [[a, "lev50m50"]]}
    write_curves(db, "2026-10-06", [_crow("base", b, 1, -0.2, 2), _crow("base", a, 2, 0.2, 2)])
    write_curves(db, "2026-10-06", [_crow("base", b, 1, -0.2, 2), _crow("base", a, 2, 0.1, 2)])     # re-run
    got = db.execute("SELECT day, account_id, variant, equity_end, n_trades FROM shadow_curves ORDER BY day, account_id, "
                     "variant").fetchall()
    assert [g[:3] for g in got] == [("2026-10-05", a, "base"), ("2026-10-05", a, "lev50m50"),
                                    ("2026-10-05", r, "base"), ("2026-10-06", a, "base"), ("2026-10-06", b, "base")]
    assert got[3][3:] == (pytest.approx(5000 * 1.1 * 1.1), 2)
    v = curve_view(db)
    assert v["days"] == ["2026-10-05", "2026-10-06"] and v["variants"] == ["base", "lev50m50"]
    base = v["by_variant"]["base"]
    assert base["accounts"] == 2                                                    # the coin flip left out
    assert base["median"][0] == pytest.approx(5500.0)                              # B not started yet on the 5th
    assert base["median"][1] == pytest.approx((6050 + 4000) / 2) and base["mean"][1] == base["median"][1]
    lv = v["by_variant"]["lev50m50"]
    assert lv["busts"] == [1, 1] and lv["bust_accounts"] == [[a, "2026-10-05"]]
    assert lv["median"][1] == pytest.approx((5.0 + 5000.0) / 2)                     # B's lev50m50: still the start
    acc = curve_view(db, account=a)["account"]
    assert acc["curves"]["base"] == [pytest.approx(5500.0), pytest.approx(6050.0)]
    assert acc["curves"]["lev50m50"] == [pytest.approx(5.0), pytest.approx(5.0)] and acc["bust_day"]["lev50m50"] == "2026-10-05"
    assert acc["n_trades"] == {"base": 2, "lev50m50": 1}
    assert curve_view(db, account=b)["account"]["curves"]["base"] == [None, pytest.approx(4000.0)]
    assert curve_view(db, include_random=True)["by_variant"]["base"]["accounts"] == 3
    assert curve_view(db, accounts=[b])["by_variant"]["base"]["accounts"] == 1
    assert curve_view(db, account="NOPE@1h")["account"]["curves"] == {}
    json.dumps(v)

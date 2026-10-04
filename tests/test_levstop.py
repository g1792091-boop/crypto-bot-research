"""Fixed-leverage and stop-width shadows (docs/observation-shadows-3.md, paperbot/obsshadows.py VARIANTS3), the live
trades by leverage tier and the new shadow numbers in the Thursday packet (agents/riskreward.py), the 5-year leverage /
stop comparison (research/levstop) and its compact reader for the Friday packet (agents/levstop.py)."""

import hashlib
import json
import os
import sys

import numpy as np
import pytest

from paperbot import Bar, Brackets
from paperbot.agents import levstop as LS
from paperbot.agents import riskreward as RR
from paperbot.agents import rooms as RM
from paperbot.config import V3_OLD_TIER_WALK, V3_SYMBOLS, v3_settings
from paperbot.daily3 import _alone, make_signal
from paperbot.ladder import roe_price
from paperbot.margin import BracketTier
from paperbot.obsshadows import (FIXED_LEVERAGE3, MARGIN_FRAC, STOP_WIDTHS, VARIANTS, VARIANTS3, SameLeveragePolicy,
                                 pnl_equity, run_alone, stop_beyond_liq, summarize, symbol_steps, trade_shadows,
                                 variant_settings)
from paperbot.sizing import size_position
from paperbot.store3 import Store3

from test_new_meetings import bulk, tpol
from test_rooms import DAY, HOUR, MIN, S, QueueRunner, World, kst, team_answer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "research", "levstop"))
import levstop as LV  # noqa: E402

ST = v3_settings()
BR = {s: Brackets.example() for s in V3_SYMBOLS}
BR50 = {s: Brackets([BracketTier(10_000_000, 50, 0.004, 0.0)]) for s in V3_SYMBOLS}
# 50x and 40x not allowed at the sizes a $5,000 account's 40% x 50x / 40x need (100k / 80k notional); 30x is
BR30 = {s: Brackets([BracketTier(50_000, 50, 0.004, 0.0), BracketTier(10_000_000, 30, 0.01, 300.0)])
        for s in V3_SYMBOLS}
SYM = "BTCUSDT"
REF, ATR = 100.0, 0.2
I0 = 10
RT = ST.round_trip_cost
ENTRY = REF * (1 + ST.slippage_frac)
V45 = "V45_AMB"
FRI = kst(2026, 10, 9, 11, 5)
OUT_JSON = os.path.join(ROOT, "research", "levstop", "out", "levstop.json")


def _bar(ts, o, h, lo, c):
    return Bar(SYM, ts, ts + MIN - 1, o, h, lo, c, o, h, lo, c, volume=1.0)


def _flat(n, px=ENTRY, wiggle=0.0002):
    return [(i * MIN, {SYM: _bar(i * MIN, px, px * (1 + wiggle), px * (1 - wiggle), px)}, {}) for i in range(n)]


def _row(tf="15m", side=1, atr=ATR):
    return {"bar_close": I0 * MIN, "timeframe": tf, "strategy": "A", "symbol": SYM, "side": side, "atr": atr,
            "ref_price": REF, "ref_time": I0 * MIN + 1000, "delay_ms": 1000, "status": "SUBMITTED"}


def _db(tmp_path, row, steps, brackets=BR, settings=None):
    store = Store3(str(tmp_path / "p.db"))
    store.log_signals([row])
    t, ok = _alone(settings or ST, brackets, {}, make_signal(row), steps, I0)
    assert ok and t is not None
    store.trade(f"A@{row['timeframe']}", t)
    store.commit()
    return store.conn, t


def _by_kind(rows):
    return {r["kind"]: r for r in rows}


# ---------------------------------------------------------------- pre-registration
def test_preregistration_3_hash_matches_and_earlier_docs_unchanged():
    for name in ("observation-shadows", "observation-shadows-2", "observation-shadows-3", "observation-shadows-4"):
        line = open(os.path.join(ROOT, "docs", f"{name}.sha256")).read().split()
        body = open(os.path.join(ROOT, "docs", f"{name}.md"), "rb").read()
        assert line[1] == f"docs/{name}.md" and hashlib.sha256(body).hexdigest() == line[0]


def test_levstop_preregistration_hash_matches():
    line = open(os.path.join(ROOT, "research", "levstop", "PREREG_LEVSTOP.sha256")).read().split()
    body = open(os.path.join(ROOT, "research", "levstop", "PREREG_LEVSTOP.md"), "rb").read()
    assert line[1] == "PREREG_LEVSTOP.md" and hashlib.sha256(body).hexdigest() == line[0]


def test_new_variant_list_and_settings():
    from paperbot.agents.labtests import TEMPLATES
    assert VARIANTS == ("base", "lock15", "lock20", "lock30", "timestop", "lev10", "lev20")      # unchanged
    assert VARIANTS3 == ("lev30", "lev40", "lev50", "stopw1.5", "stopw2.5", "stopw3")
    assert tuple(STOP_WIDTHS.values()) == TEMPLATES["stop_atr"]["k"]
    assert {v: (t.margin_frac, t.leverages) for v in FIXED_LEVERAGE3 for t in variant_settings(ST, v).tiers} == {
        "lev30": (0.30, (30,)), "lev40": (0.40, (40,)), "lev50": (0.40, (50,))}
    for v in STOP_WIDTHS:
        assert variant_settings(ST, v) is ST
    # the rule's shares since the owners' 2026-10-04 change (margin = leverage %); lev50 above keeps its registered 40%
    assert MARGIN_FRAC == {50: 0.50, 40: 0.40, 30: 0.30, 20: 0.20, 10: 0.20}
    assert not set(VARIANTS3) & {"stop1.5", "stop2.5", "stop3.0"}            # daily3's loss-card stop rows


# ---------------------------------------------------------------- stop widths at the real trade's leverage
def test_stop_width_keeps_the_real_leverage_and_only_the_narrow_stop_is_hit(tmp_path):
    lev = size_position(ST, ST.initial_equity, 1, ENTRY, REF - 2 * ATR, "best", BR[SYM], atr=ATR).leverage
    p13 = roe_price(1, ENTRY, lev, 0.13, RT)
    steps = _flat(I0 + 1)
    steps.append(((I0 + 1) * MIN, {SYM: _bar((I0 + 1) * MIN, ENTRY, ENTRY, 99.65, ENTRY)}, {}))   # 1.75 ATR down
    steps.append(((I0 + 2) * MIN, {SYM: _bar((I0 + 2) * MIN, ENTRY, p13, ENTRY, p13)}, {}))       # arms 10%
    steps.append(((I0 + 3) * MIN, {SYM: _bar((I0 + 3) * MIN, p13, p13, 99.0, 99.1)}, {}))        # lock exit
    steps += [((I0 + 4 + i) * MIN, {SYM: _bar((I0 + 4 + i) * MIN, 99.1, 99.2, 99.0, 99.1)}, {}) for i in range(5)]
    conn, actual = _db(tmp_path, _row(), steps)
    assert actual.exit_reason == "LOCK" and actual.leverage == lev
    rows, info = trade_shadows(ST, BR, {}, conn, "d", 0, len(steps) * MIN, steps, make_signal, extra3=True)
    k = _by_kind(rows)
    assert len(rows) == len(VARIANTS) + len(VARIANTS3) and info["extra3"] is True and info["no_leverage"] == 0
    assert k["stopw1.5"]["exit_reason"] == "SL" and k["stopw1.5"]["roe"] < 0
    for v in ("stopw2.5", "stopw3"):
        assert k[v]["exit_reason"] == "LOCK" and k[v]["roe"] == pytest.approx(k["base"]["roe"], abs=1e-9)
    for v in STOP_WIDTHS:
        d = json.loads(k[v]["data"])
        assert d["leverage"] == lev and d["same_leverage"] == lev and d["stop_atr"] == STOP_WIDTHS[v]
        assert d["pnl_equity"] == pytest.approx(k[v]["roe"] * MARGIN_FRAC[lev]) and d["stop_beyond_liq"] is False
    rep = summarize(rows, info)
    assert rep["stopw1.5"]["base"]["worse_than_base"] == 1.0 and rep["stopw1.5"]["base"]["paired"] == 1
    assert rep["stopw2.5"]["base"]["better_than_base"] == 0.0 and rep["stopw2.5"]["base"]["worse_than_base"] == 0.0
    assert rep["stopw3"]["stop_beyond_liq"] == 0 and rep["lev30"]["trades"] == 1


def test_a_stop_beyond_the_liquidation_price_is_liquidated_not_stopped():
    row = _row(atr=1.0)                                   # 3 ATR = 3% away; at 50x liquidation is ~1.6% away
    steps = _flat(I0 + 1)
    steps.append(((I0 + 1) * MIN, {SYM: _bar((I0 + 1) * MIN, ENTRY, ENTRY, 98.0, 98.2)}, {}))
    ss = symbol_steps(steps, SYM)
    tr, ok = run_alone(ST, BR50, {}, make_signal(row, stop_atr=3.0), ss, I0, policy=SameLeveragePolicy(ST, 50))
    assert ok and tr.leverage == 50 and tr.exit_reason == "LIQ" and stop_beyond_liq(tr) is True
    assert tr.margin == pytest.approx(ST.initial_equity * 0.50, rel=1e-6)   # the rule's 50x share (50% since 2026-10-04)
    # the current rules would never have entered this at 50x (the stop must sit inside liquidation)
    rules = size_position(ST, ST.initial_equity, 1, ENTRY, REF - 3.0, "best", BR50[SYM], atr=1.0)
    assert not rules.ok or rules.leverage < 50
    # a bracket that refuses the leverage: not entered (no fallback)
    tr, ok = run_alone(ST, BR30, {}, make_signal(_row(), stop_atr=1.5), ss, I0, policy=SameLeveragePolicy(ST, 50))
    assert (tr, ok) == (None, True)


def test_fixed_leverage_30_40_50_margin_shares_and_refusals(tmp_path):
    # the old tier walk, so that the unscored real trade is 50x (quality_v1 would make it 'normal', <= 30x)
    ST = v3_settings(**V3_OLD_TIER_WALK)
    steps = _flat(I0 + 3)
    steps.append(((I0 + 3) * MIN, {SYM: _bar((I0 + 3) * MIN, 97.5, 97.6, 97.4, 97.5)}, {}))   # gap -2.5%
    conn, actual = _db(tmp_path, _row(), steps, brackets=BR50, settings=ST)
    assert actual.leverage == 50 and actual.exit_reason == "LIQ"
    rows, info = trade_shadows(ST, BR50, {}, conn, "d", 0, len(steps) * MIN, steps, make_signal, extra3=True)
    k = _by_kind(rows)
    d = {v: json.loads(k[v]["data"]) for v in FIXED_LEVERAGE3}
    assert [d[v]["leverage"] for v in ("lev30", "lev40", "lev50")] == [30, 40, 50]
    assert k["lev50"]["exit_reason"] == "LIQ" and k["lev40"]["exit_reason"] == "LIQ"
    assert k["lev30"]["exit_reason"] == "SL" and -0.80 < k["lev30"]["roe"] < -0.70        # ~ -2.5% x 30 + costs
    assert d["lev30"]["pnl_equity"] == pytest.approx(k["lev30"]["roe"] * 0.30)
    assert d["lev50"]["pnl_equity"] == pytest.approx(k["lev50"]["roe"] * 0.40)
    rep = summarize(rows, info)
    assert rep["lev30"]["liquidations"] == 0 and rep["lev50"]["liquidations"] == 1
    assert rep["lev30"]["base"]["better_than_base"] == 1.0
    # brackets that refuse 50x and 40x at those sizes: not entered, never a lower leverage
    rows2, _i = trade_shadows(ST, BR30, {}, conn, "d", 0, len(steps) * MIN, steps, make_signal, extra3=True)
    k2 = _by_kind(rows2)
    assert k2["lev50"]["roe"] is None and k2["lev50"]["resolved"] == 1
    assert k2["lev40"]["roe"] is None and json.loads(k2["lev30"]["data"])["leverage"] == 30
    assert summarize(rows2, _i)["lev50"]["rejected"] == 1


def _random_day(tmp_path, n_trades=40, seed=5):
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
        steps.append((i * MIN, bars, {}))
    store = Store3(str(tmp_path / "p.db"))
    made = 0
    tfs = ("5m", "15m", "30m", "1h", "4h")
    while made < n_trades:
        tf = tfs[made % 5]
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


def test_existing_variants_are_unchanged_by_the_new_ones(tmp_path):
    store, steps = _random_day(tmp_path)
    old, info_old = trade_shadows(ST, BR, {}, store.conn, "d", 0, DAY, steps, make_signal)
    new, info_new = trade_shadows(ST, BR, {}, store.conn, "d", 0, DAY, steps, make_signal, extra3=True)
    assert len(old) == 40 * len(VARIANTS) and len(new) == 40 * (len(VARIANTS) + len(VARIANTS3))
    assert [r for r in new if r["kind"] in VARIANTS] == old
    rep_old, rep_new = summarize(old, info_old), summarize(new, info_new)
    for v in VARIANTS:
        assert rep_new[v] == rep_old[v]
    assert set(VARIANTS3) <= set(rep_new) and not set(VARIANTS3) & set(rep_old)
    assert len({r["key"] for r in new}) == len(new)
    levs = {json.loads(r["data"])["actual_leverage"] for r in new}
    assert levs <= {50, 40, 30, 20} and info_new["no_leverage"] == 0
    # a stop width's leverage is always the real trade's
    for r in new:
        if r["kind"] in STOP_WIDTHS and r["roe"] is not None:
            d = json.loads(r["data"])
            assert d["leverage"] == d["actual_leverage"]


def test_nightly_report_has_the_new_variants(tmp_path, monkeypatch):
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
    for v in VARIANTS3:
        assert kinds[v] == closed and tv[v]["trades"] == closed
        assert {"paired", "vs_base_pnl_equity", "better_than_base", "worse_than_base"} <= set(tv[v]["base"])
    assert "stop_beyond_liq" in tv["stopw3"] and "stop_beyond_liq" not in tv["lev30"]
    assert {"stop1.5", "stopw1.5"} <= set(kinds)                      # the loss-card rows stay apart
    json.dumps(rep)


# ---------------------------------------------------------------- riskreward: tiers, new shadows, turns
def _trade(lev, roe, win=None, tf="15m", exit_="SL"):
    t = {"win": roe > 0 if win is None else win, "roe": roe, "eq": RR.pnl_equity(roe, lev), "exit": exit_,
         "mfe_roe": None, "mae": None, "mae_stop": None, "exit_time": 0, "lev": lev}
    return ("A", tf, t)


def test_tier_table_by_the_leverage_actually_used_and_its_confound_note():
    rows = [_trade(50, 0.10, exit_="LOCK"), _trade(50, 0.10, exit_="LOCK"), _trade(50, -0.40),
            _trade(20, 0.30, tf="1h", exit_="LOCK"), _trade(20, -0.20, tf="1h"), _trade(30, -1.0, exit_="LIQ"),
            ("A", "4h", {"win": False, "roe": -0.1, "eq": None, "exit": "SL", "mfe_roe": None, "exit_time": 0,
                         "lev": 25})]
    t = RR.tier_table(rows)
    b = t["by_leverage"]
    assert list(b) == ["50", "40", "30", "20"] and t["other_leverage"] == 1
    assert b["50"]["trades"] == 3 and b["50"]["win_rate"] == pytest.approx(2 / 3, abs=1e-4)
    assert b["50"]["mean_roe"] == pytest.approx(-0.2 / 3, abs=1e-4) and b["50"]["mean_eq"] == pytest.approx(-0.10 / 3, abs=1e-5)
    assert b["50"]["payoff"] == pytest.approx(0.25) and b["50"]["breakeven_win_rate"] == pytest.approx(0.8)
    assert b["40"] == {"trades": 0, "small": True} and b["30"]["liq"] == 1
    assert b["20"]["mean_eq"] == pytest.approx(0.01) and b["20"]["payoff"] == pytest.approx(1.5)
    assert t["by_tf"]["1h"] == {"20": [2, 0.5, 0.05, 0.01]} and list(t["by_tf"]["15m"]) == ["50", "30"]
    assert t["confounded"] is True and "손절 거리" in t["note"] and "교란" in t["note"] and "lev50" in t["note"]
    pk = RR.tier_packet({"7d": rows[:3], "since_start": rows})
    assert pk["7d"]["by_leverage"]["50"] == RR.tier_row(b["50"]) and len(pk["columns"]) == len(RR.tier_row(b["50"]))
    assert "by_tf" in pk["since_start"] and "by_tf" not in pk["7d"] and pk["since_start"]["other_leverage"] == 1


def _sh(world, kind, aid, bc, roe, eq, reason="LOCK", day="2026-10-06", resolved=1, **extra):
    world.daily.execute("INSERT INTO shadows VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (f"{kind}|{aid}|BTCUSDT|{bc}", day, kind, aid, "BTCUSDT", aid.split("@")[1], 1, None, roe,
                         None if roe is None else reason, resolved, json.dumps({"pnl_equity": eq, **extra})))


def test_shadow_summary_new_variants_leverage_and_stop_turns(world):
    a, b = f"{S}@15m", f"{V45}@1h"
    for bc, (base, l30, l50, s15, s3) in enumerate(((-0.08, 0.03, None, -0.02, 0.01), (0.02, 0.01, 0.02, 0.03, -0.01))):
        _sh(world, "base", a, bc, base * 2.5, base, reason="SL" if base < 0 else "LOCK")
        _sh(world, "lev30", a, bc, l30 / 0.3, l30)
        _sh(world, "lev50", a, bc, None if l50 is None else l50 / 0.4, l50)       # bc 0: not entered at 50x
        _sh(world, "stopw1.5", a, bc, s15 / 0.4, s15)
        _sh(world, "stopw3", a, bc, s3 / 0.4, s3, reason="LIQ" if s3 < 0 else "LOCK", stop_beyond_liq=s3 < 0)
    _sh(world, "base", b, 9, 0.05, 0.02)
    _sh(world, "stopw3", b, 9, -0.05, -0.02, reason="SL")
    _sh(world, "stopw2.5", b, 9, None, None, resolved=0)
    world.daily.commit()
    now = kst(2026, 10, 8, 11, 0)
    sh = RR.shadow_summary(world.daily, world.paper(), now - 7 * DAY, now)
    c = sh["strategies"][S]
    assert c["base"]["mean_eq"] == pytest.approx(-0.03)
    assert c["lev30"]["mean_eq"] == pytest.approx(0.02) and c["lev30"]["vs_base_eq"] == pytest.approx(0.05)
    assert c["lev50"]["trades"] == 1 and c["lev50"]["not_entered"] == 1 and c["lev50"]["base_mean_eq"] == pytest.approx(0.02)
    assert c["stopw3"]["stop_beyond_liq"] == 1 and c["stopw3"]["liq"] == 1 and "stop_beyond_liq" not in c["stopw1.5"]
    assert sh["strategies"][V45]["stopw2.5"] == {"trades": 0, "open": 1}
    lt = RR.leverage_turns(sh["strategies"])
    assert set(lt) == {"lev10", "lev20", "lev30", "lev40", "lev50"}
    assert [x["strategy"] for x in lt["lev30"]["turns_positive"]] == [S] and "turns_negative" not in lt["lev30"]
    assert lt["lev50"] == {"turns_positive": [], "still_negative": []}          # base of its one trade > 0
    st = RR.stop_turns(sh["strategies"])
    assert set(st) == {"stopw1.5", "stopw2.5", "stopw3"}
    assert [x["strategy"] for x in st["stopw1.5"]["turns_positive"]] == [S]       # 0.005 > 0 > -0.03
    assert [x["strategy"] for x in st["stopw3"]["turns_negative"]] == [V45]       # base +0.02, 3 ATR -0.02
    assert st["stopw3"]["still_negative"] == [S, V45] and st["stopw2.5"]["turns_negative"] == []
    row = RR.shadow_brief3(c)
    assert set(row) == {"lev30", "lev50", "stopw1.5", "stopw3"} and len(row["lev30"]) == len(RR.SHADOW3_COLUMNS)
    assert row["lev50"][-1] == 1                                                 # not entered


def test_rr_packet_carries_tiers_and_the_new_shadows_and_stays_bounded(world):
    from test_riskreward import seed
    seed(world)
    a = f"{S}@15m"
    _sh(world, "base", a, 1, -0.2, -0.08, reason="SL")
    _sh(world, "stopw1.5", a, 1, 0.05, 0.02)
    _sh(world, "lev30", a, 1, 0.1, 0.03)
    world.daily.commit()
    from test_rooms import QUIET
    pk = RR.rr_packet(world.paper(), world.daily, QUIET)
    t = pk["tiers"]
    assert t["confounded"] is True and set(t) >= {"7d", "since_start", "columns", "note"}
    assert t["since_start"]["by_leverage"]["50"][0] == 5 and t["since_start"]["by_leverage"]["30"][0] == 10
    nv = pk["shadows"]["new_variants"]
    assert nv["doc"] == "docs/observation-shadows-3.md" and set(nv["by_strategy_since_start"][S]) == {"stopw1.5", "lev30"}
    assert [x["strategy"] for x in nv["stop_turns"]["since_start"]["stopw1.5"]["turns_positive"]] == [S]
    assert [x["strategy"] for x in pk["shadows"]["lower_leverage"]["since_start"]["lev30"]["turns_positive"]] == [S]
    assert "stopw1.5" in pk["shadows"]["all_strategies"]["since_start"]
    assert len(json.dumps(pk, ensure_ascii=False)) < 17_000
    # 36 strategies with every new variant: the per-strategy section stays bounded
    cell = {"trades": 25, "mean_eq": -0.012345, "base_mean_eq": -0.023456, "vs_base_eq": 0.011111, "better_share": 0.583,
            "worse_share": 0.25, "liq": 1, "base_liq": 2, "not_entered": 3}
    many = {f"N{i:02d}_LONG_NAME": {v: dict(cell) for v in RR.SHADOW_VARIANTS3} for i in range(36)}
    big = {k: RR.shadow_brief3(v) for k, v in many.items()}
    assert len(json.dumps(big, ensure_ascii=False)) < 15_000                    # 6 short rows x 36 at most


def test_rr_review_meeting_packet_has_tiers_and_new_shadows(world):
    from test_riskreward import THU, seed
    bulk(world, 250, THU - HOUR)
    seed(world, THU - 30 * MIN)
    pol = RM.RoomsPolicy(triggers=tpol(enabled=("rr_review",), rr_review_hour_kst=11))
    lead = {"summary": ["a", "b", "c"], "human_actions": [], "watch_next": []}
    runner = QueueRunner({"exit_timing": [team_answer("x", "rr.tiers.since_start.by_leverage")],
                          "whatif": [team_answer("w")], "pnl_reviewer": [team_answer("p")], "team_lead": [lead]})
    out = RM.tick(world.paths["paper"], world.paths["daily"], world.paths["agents"], world.paths["inbox"], runner,
                  policy=pol, now_ms=THU, clock_ms=lambda: THU)
    assert [r["status"] for r in out["rounds"]] == ["done"]
    pk = runner.calls[0]["packet"]["rr"]
    assert pk["tiers"]["confounded"] is True and "new_variants" in pk["shadows"]
    sysp = runner.calls[0]["system"]
    assert "rr.tiers" in sysp and "교란" in sysp and "stopw1.5" in sysp and "stop_turns" in sysp


# ---------------------------------------------------------------- research/levstop: machinery on synthetic bars
def _atr(h, lo, c):
    pc = np.concatenate([[np.nan], c[:-1]])
    tr = np.nanmax(np.vstack([h - lo, np.abs(h - pc), np.abs(lo - pc)]), axis=0)
    out = np.full(len(tr), np.nan)
    a = float(np.mean(tr[:14]))
    out[13] = a
    for i in range(14, len(tr)):
        a += (tr[i] - a) / 14.0
        out[i] = a
    return out


def _synthetic_bars(n=3000, seed=1, vol=0.004, start="2021-09-01T00:00"):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, vol, n)))
    o = np.concatenate([[100.0], c[:-1]])
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, vol / 2, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, vol / 2, n)))
    t0 = np.datetime64(start, "ns").astype(np.int64)
    ts = t0 + np.arange(n, dtype=np.int64) * 3_600_000_000_000
    return {"ts": ts, "o": o, "h": h, "l": lo, "c": c, "atr": _atr(h, lo, c)}


def test_tiers_arm_equals_the_lab_outcomes_and_fixed_leverage_clips_the_stop_to_liquidation():
    from paperbot.agents import labtests as LT
    b = _synthetic_bars()
    rng = np.random.default_rng(2)
    sg = np.where(rng.random(len(b["ts"])) < 0.05, np.where(rng.random(len(b["ts"])) < 0.5, 1, -1), 0).astype(np.int8)
    ref = LT.signal_outcomes(b, sg, 100, len(b["ts"]), "1h", 2.0)
    o = LV.outcomes(b, ref["idx"], ref["side"], "1h", "tiers", 2.0)
    assert (o["done"] == ref["done"]).all() and np.allclose(o["roe"][ref["done"]], ref["roe"][ref["done"]])
    ref3 = LT.signal_outcomes(b, sg, 100, len(b["ts"]), "1h", 3.0)
    o3 = LV.outcomes(b, ref["idx"], ref["side"], "1h", "tiers", 3.0)
    assert np.allclose(o3["roe"][ref3["done"]], ref3["roe"][ref3["done"]])
    # 50x fixed with a 3 ATR stop on 0.4%-ATR bars: the stop lies beyond liquidation, every such exit is a
    # liquidation (-100%), and the rules' checks would have let almost none in
    f = LV.outcomes(b, ref["idx"], ref["side"], "1h", 50, 3.0)
    d = f["done"]
    assert d.all() and (f["lev"] == 50).all()
    assert np.all(f["roe"][f["reason"] == 2] == -1.0) and (f["reason"][d] == 2).any()
    assert (o["reason"][o["done"]] == 2).sum() == 0                              # the rules' 2 ATR: none
    assert np.all(f["roe"][d] >= -1.0) and f["rules_ok"].mean() < 0.2
    f10 = LV.outcomes(b, ref["idx"], ref["side"], "1h", 10, 1.5)
    assert (f10["reason"][f10["done"]] == 2).sum() == 0 and f10["rules_ok"].mean() > 0.9
    fs = LV.FixedSizer(50, 2.0)
    assert 0.01 < fs.liq_frac[1] < 0.02 and 0.01 < fs.liq_frac[-1] < 0.02


def test_account_one_position_at_a_time_and_bust():
    ts = np.array([0, 1, 2, 5, 5, 9], np.int64)
    coin = np.array([0, 0, 1, 2, 1, 0])
    ex = np.array([3, 2, 4, 7, 6, 10], np.int64)
    g = np.array([0.1, 0.5, 0.5, -0.5, 0.2, 0.1])
    bust, mult, n = LV.account(ts, coin, ex, g)
    # 0 (exit 3) -> skips 1, 2 -> ts 5: coin 1 before coin 2 -> (exit 6) -> 9
    assert (bust, n) == (False, 3) and mult == pytest.approx(1.1 * 1.2 * 1.1)
    bust, mult, n = LV.account(np.array([0, 1, 2]), np.zeros(3), np.array([1, 2, 3]), np.array([-0.4, -0.4, -0.4]))
    assert bust is False and n == 3
    g = np.full(30, -0.4)
    bust, mult, n = LV.account(np.arange(30), np.zeros(30), np.arange(30) + 1, g)
    assert bust is True and n < 30 and mult * LV.START < LV.BUST_BELOW
    assert LV.account(np.zeros(0), np.zeros(0), np.zeros(0), np.zeros(0)) == (False, 1.0, 0)


def test_benjamini_hochberg():
    assert LV.bh([0.001, 0.02, 0.03, 0.5, None], q=0.10) == [True, True, True, False, False]
    assert LV.bh([0.04, 0.5, 0.6], q=0.10) == [False, False, False]
    assert LV.bh([], q=0.1) == [] and LV.bh([None]) == [False]


def test_run_on_a_tiny_synthetic_cache(tmp_path):
    rng = np.random.default_rng(4)
    for ci, c in enumerate(LV.COINS[:2]):
        b = _synthetic_bars(n=26_500, seed=10 + ci, vol=0.003, start="2021-07-25T00:00")
        n = len(b["ts"])
        sig = {f"s__{s}": np.where(rng.random(n) < 0.01, np.where(rng.random(n) < 0.5, 1, -1), 0).astype(np.int8)
               for s in ("AAA", "BBB")}
        np.savez_compressed(tmp_path / f"sig_1h_{c}.npz", **b, **sig)
    out = tmp_path / "o.json"
    doc = LV.run(str(tmp_path), str(out), procs=1, n_boot=200, tfs=("1h",))
    assert doc["grid"].startswith("subset") and set(doc["cells"]) == {"AAA|1h", "BBB|1h"}
    row = doc["cells"]["AAA|1h"]
    assert set(row) == set(LV.arms()) and len(row) == 24 and all(len(r) == len(LV.COLUMNS) for r in row.values())
    ci = {c: i for i, c in enumerate(LV.COLUMNS)}
    cur = row["tiers|2.0"]
    assert cur[ci["trades"]] > 100 and cur[ci["rules_ok_share"]] is None and 0 < cur[ci["p_pos"]] <= 1
    assert row["10|2.0"][ci["rules_ok_share"]] is not None and row["10|2.0"][ci["trades"]] >= cur[ci["trades"]]
    s = doc["summary"]
    assert set(s["by_arm"]) == set(LV.arms()) and s["by_arm"]["tiers|2.0"]["cells"] == 2
    assert s["by_arm"]["tiers|2.0"]["accounts"] == 4 and s["lines_ko"]
    assert json.loads(out.read_text())["version"] == 1 and doc["data"]["checked"] is False


# ---------------------------------------------------------------- the committed result and the Friday reader
def test_committed_result_is_full_small_and_pre_registered():
    if not os.path.exists(OUT_JSON):
        pytest.skip("no committed result")
    assert os.path.getsize(OUT_JSON) < 2_000_000
    doc = json.load(open(OUT_JSON))
    line = open(os.path.join(ROOT, "research", "levstop", "PREREG_LEVSTOP.sha256")).read().split()
    assert doc["version"] == 1 and doc["prereg"]["sha256"] == line[0]
    assert doc["grid"].startswith("full") and len(doc["cells"]) == 180
    assert set(doc["summary"]["by_arm"]) == set(LV.arms())
    assert doc["data"]["main_identical_to_research"] is True and doc["runtime_s"]["total"] < 30 * 60


def test_reader_compact_cached_and_bounded(tmp_path):
    if os.path.exists(OUT_JSON):
        br = LS.brief()
        assert len(json.dumps(br, ensure_ascii=False, separators=(",", ":")).encode()) < 4000
        assert len(br["arms"]) == 24 and br["current_arm"] == "tiers|2.0" and br["lines_ko"]
        assert len(br["arms"]["50|2.0"]) == len(LS.COLUMNS) and len(br["arms"]["tiers|2.0"]) == len(LS.COLUMNS) - 1
        assert LS.load() is LS.load()                                             # cached
    assert "error" in LS.brief(str(tmp_path / "none.json"))
    # a synthetic result with long lines is trimmed under the limit
    arms = {a: {"sig_pos_bh": 0, "sig_neg_bh": 3, "cells_mean_positive": 10, "cells": 180, "pooled_mean_eq": -0.0123456,
                "busts": 100, "accounts": 360, **({} if a.startswith("tiers") else {"pooled_rules_ok_share": 0.5})}
            for a in LV.arms()}
    doc = {"version": 1, "current_arm": "tiers|2.0", "summary": {"by_arm": arms, "lines_ko": ["가" * 300] * 10,
           "by_arm_tf": {"tiers|2.0": {tf: {"sig_pos_bh": 0, "sig_neg_bh": 1, "pooled_mean_eq": -0.01, "busts": 20}
                                       for tf in LV.TFS}}}}
    p = tmp_path / "l.json"
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    br = LS.brief(str(p))
    assert len(json.dumps(br, ensure_ascii=False, separators=(",", ":")).encode()) < 4000 and len(br["arms"]) == 24
    p.write_text(json.dumps({**doc, "version": 2}), encoding="utf-8")
    assert "error" in LS.brief(str(p))                                            # another version: not read


def test_risk_review_packet_has_levstop_5y(world):
    from test_survival import FRI as FRIDAY
    bulk(world, 250, FRIDAY - HOUR, aid=f"{V45}@15m")
    pol = RM.RoomsPolicy(triggers=tpol(enabled=("risk_review",), risk_review_hour_kst=11))
    lead = {"summary": ["a", "b", "c"], "human_actions": [], "watch_next": []}
    runner = QueueRunner({"risk_officer": [team_answer("r", "survival.levstop_5y.arms")],
                          "validator": [team_answer("v")], "team_lead": [lead]})
    out = RM.tick(world.paths["paper"], world.paths["daily"], world.paths["agents"], world.paths["inbox"], runner,
                  policy=pol, now_ms=FRIDAY, clock_ms=lambda: FRIDAY)
    assert [r["status"] for r in out["rounds"]] == ["done"]
    lv = runner.calls[0]["packet"]["survival"]["levstop_5y"]
    if os.path.exists(OUT_JSON):
        assert len(lv["arms"]) == 24 and len(json.dumps(lv, ensure_ascii=False).encode()) < 4000
    else:
        assert "error" in lv
    sysp = runner.calls[0]["system"]
    assert "levstop_5y" in sysp and "tiers|2.0" in sysp


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)

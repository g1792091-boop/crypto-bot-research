"""The restarted paper v3 run's leverage rule (owners 2026-10-04, "B로 가자"; docs/paper-v3-rules-change-1.md section 6;
paperbot/levrule.py, config.V3_LEVERAGE_RULE = "quality_v1"): entry-quality 'best' signals try 50x / 50%, then
40x / 40% (then 30x / 30%, 20x / 20%); every other signal 30x / 30%, then 20x / 20%; margin = leverage %; coin flips
'best' with the frozen p_best per timeframe, the same in the checkpoint's bots."""

import inspect
import json
import os
import sys

import numpy as np
import pytest

from paperbot import Bar, Brackets, PaperEngine, Signal
from paperbot import checkpoint as ck
from paperbot import config as C
from paperbot import levrule as LR
from paperbot.config import (DEFAULT_TIERS, V3_OLD_TIER_WALK, V3_P_BEST, V3_SYMBOLS, V3_TRADE_TFS, Settings, Tier,
                             v3_settings)
from paperbot.margin import BracketTier
from paperbot.sizing import size_position

S = v3_settings()
E = S.initial_equity
SYM = "BTCUSDT"
BR50 = Brackets([BracketTier(10_000_000, 50, 0.004, 0.0)])
STRAT, TF = "N03_ADX_GC", "15m"          # 3 features with edges at 15m (tests/test_quality_shadow.py)
MIN = 60_000


def _strength(adx, lag, gap):
    feats = [("adx_excess", True, adx), ("cross_lag_bars", False, lag), ("ema_gap_atr", True, gap)]
    return {"side": 1, "features": [{"name": n, "higher_is_stronger": h, "value": v} for n, h, v in feats]}


BEST = _strength(10.0, 0, 1.0)          # quintiles 5, 5, 5
GOOD = _strength(1.5, 2, 0.05)          # 3, 2, 3 -> good
BASE = _strength(0.1, 5, 0.0)           # 1, 1, 1


def _size(d, group, settings=S, atr=None, br=BR50):
    """Long at 100 with the stop d (fraction) below; atr defaults to half the stop distance (a 2 ATR stop)."""
    stop = 100.0 * (1 - d)
    return size_position(settings, E, 1, 100.0, stop, group, br, atr=100.0 * d / 2 if atr is None else atr)


# ------------------------------------------------------------------ config
def test_v3_settings_use_quality_v1_with_margin_equal_to_leverage():
    assert C.V3_LEVERAGE_RULE == "quality_v1" and S.leverage_rule == "quality_v1" and S.best_falls_to_normal
    assert [(t.name, t.margin_frac, t.leverages) for t in S.tiers] == [
        ("best", 0.50, (50,)), ("best", 0.40, (40,)), ("normal", 0.30, (30,)), ("normal", 0.20, (20,))]
    for t in S.tiers:
        assert all(t.margin_frac == pytest.approx(lev / 100) for lev in t.leverages)     # margin = leverage %
    assert [lev for _, lev in S.tier_chain("best")] == [50, 40, 30, 20]
    assert [lev for _, lev in S.tier_chain("normal")] == [30, 20]
    strict = v3_settings(best_falls_to_normal=False)
    assert [lev for _, lev in strict.tier_chain("best")] == [50, 40]
    # the safety checks are the ones of the old rule
    assert (S.max_loss_frac, S.liq_buffer_atr_mult, S.liq_buffer_min_frac) == (0.15, 1.0, 0.002)
    assert (S.min_leverage, S.max_leverage, S.min_margin_frac, S.max_margin_frac) == (20, 50, 0.20, 0.50)


def test_old_tier_walk_is_still_available_and_unchanged():
    old = v3_settings(**V3_OLD_TIER_WALK)
    assert old.leverage_rule == "tier_walk" and old.tiers == DEFAULT_TIERS
    assert [(t.name, t.margin_frac, lev) for t, lev in old.tier_chain("best")] == [
        ("best", 0.40, 50), ("best", 0.40, 40), ("good", 0.30, 30), ("base", 0.20, 20)]
    assert Settings().leverage_rule == "tier_walk"           # research (rules_bt) keeps its own rule


def test_settings_validation():
    with pytest.raises(ValueError):
        v3_settings(leverage_rule="nope")
    with pytest.raises(ValueError):                         # quality_v1 needs both groups named
        v3_settings(tiers=(Tier("best", 0.5, (50,)),))
    with pytest.raises(ValueError):
        S.tier_chain("good")
    with pytest.raises(ValueError):                         # 50% margin is outside the old owner range
        Settings(leverage_rule="quality_v1", tiers=C.V3_QUALITY_TIERS)


def test_p_best_constants_are_frozen_and_documented():
    assert set(V3_P_BEST) == set(V3_TRADE_TFS)
    assert V3_P_BEST == {"15m": 0.2155, "30m": 0.2170, "1h": 0.2157, "4h": 0.2095}
    src = inspect.getsource(C)
    for s in ("Computed once on 2026-10-04", "231,908 / 1,075,951", "111,710 / 514,899", "46,973 / 217,799",
              "2,589 / 12,357", "quality_edges.json", "V3_BEST_FALLS_TO_NORMAL"):
        assert s in src, s
    for tf, (b, n) in {"15m": (231_908, 1_075_951), "30m": (111_710, 514_899), "1h": (46_973, 217_799),
                       "4h": (2_589, 12_357)}.items():
        assert V3_P_BEST[tf] == round(b / n, 4)
    doc = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs",
                            "paper-v3-rules-change-1.md"), encoding="utf-8").read()
    assert all(f"**{V3_P_BEST[tf]:.4f}**" in doc for tf in V3_P_BEST) and "B로 가자" in doc


# ------------------------------------------------------------------ the group of a signal
def test_scoring_matches_the_quality_shadow():
    from paperbot.obsshadows import quality_score as shadow_score
    rng = np.random.default_rng(1)
    cells = LR.edges()
    for key in list(cells)[:60]:
        strat, tf = key.split("|")
        for _ in range(5):
            st = {"features": [{"name": f, "value": (None if rng.random() < 0.1 else float(rng.normal(0, 3)))}
                               for f in cells[key]]}
            a, b = LR.quality_score(st, strat, tf), shadow_score(st, strat, tf)
            assert (a["score"], a["tier"], a["reason"]) == (b["score"], b["tier"], b["reason"])


@pytest.mark.parametrize("st,group,tier,reason", [
    (BEST, "best", "best", None), (GOOD, "normal", "good", None), (BASE, "normal", "base", None),
    (None, "normal", None, "no_strength"), ({"error": "boom"}, "normal", None, "strength_error"),
    (_strength(None, None, None), "normal", None, "no_values")])
def test_strategy_group_from_recorded_strength(st, group, tier, reason):
    sig = Signal(ts=MIN - 1, symbol=SYM, timeframe=TF, strategy_id=STRAT, side=1, stop_price=0.0, tier="best",
                 meta={"ctx": {} if st is None else {"strength": st}})
    g = LR.signal_group(sig)
    assert (g["group"], g["tier"], g["reason"], g["source"]) == (group, tier, reason, "quality")
    assert LR.requested_tier(S, sig) == group
    assert LR.requested_tier(v3_settings(**V3_OLD_TIER_WALK), sig) == "best"      # the old rule: the signal's tier


def test_strategies_without_edges_are_normal_and_errors_never_raise():
    # DOGE (DOGE_L + DOGE_S joined) has edges at 15m / 30m / 1h but not at 4h; a new-strategy account has none
    assert LR.edges().get("DOGE|15m") and not LR.edges().get("DOGE|4h")
    for strat, tf in (("DOGE", "4h"), ("N21_ST_RSI_ADX", "15m"), ("NL_SOMETHING", "1h")):
        sig = Signal(ts=MIN - 1, symbol=SYM, timeframe=tf, strategy_id=strat, side=1, stop_price=0.0,
                     meta={"ctx": {"strength": BEST}})
        assert LR.signal_group(sig)["group"] == "normal" and LR.signal_group(sig)["reason"] == "no_edges"
    bad = Signal(ts=MIN - 1, symbol=SYM, timeframe=TF, strategy_id=STRAT, side=1, stop_price=0.0,
                 meta={"ctx": {"strength": {"features": [{"name": "adx_excess", "value": object()}]}}})
    assert LR.signal_group(bad)["group"] == "normal"
    assert LR.signal_group({"strategy_id": STRAT, "timeframe": TF, "meta": "garbage"})["group"] == "normal"
    # a pending signal as paper3.db stores it (the executor's direct path)
    d = {"strategy_id": STRAT, "timeframe": TF, "symbol": SYM, "ts": MIN - 1, "tier": "best",
         "meta": {"ctx": {"strength": BEST}}}
    assert LR.requested_tier(S, d) == "best" and LR.requested_tier(S, {**d, "meta": {}}) == "normal"


def test_meta_lev_group_wins():
    sig = Signal(ts=MIN - 1, symbol=SYM, timeframe=TF, strategy_id="R", side=1, stop_price=0.0,
                 meta={"lev_group": "best"})
    assert LR.signal_group(sig) == {"group": "best", "source": "meta"}


def test_coin_flip_draw_is_deterministic_and_has_the_frozen_share():
    n = 20_000
    for tf in V3_TRADE_TFS:
        span = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}[tf] * MIN
        draws = np.array([LR.coin_flip_best(1, tf, SYM, 1_790_000_000_000 + k * span) for k in range(n)])
        p = V3_P_BEST[tf]
        assert abs(draws.mean() - p) < 4 * np.sqrt(p * (1 - p) / n), tf
    a = [LR.coin_flip_best(2, "15m", "ETHUSDT", 1_790_000_000_000 + k * 15 * MIN) for k in range(500)]
    assert a == [LR.coin_flip_best(2, "15m", "ETHUSDT", 1_790_000_000_000 + k * 15 * MIN) for k in range(500)]
    b = [LR.coin_flip_best(3, "15m", "ETHUSDT", 1_790_000_000_000 + k * 15 * MIN) for k in range(500)]
    c = [LR.coin_flip_best(2, "15m", "SOLUSDT", 1_790_000_000_000 + k * 15 * MIN) for k in range(500)]
    assert a != b and a != c                                 # seed and coin each give their own draws
    assert not any(LR.coin_flip_best(1, "15m", SYM, k * 15 * MIN, p=0.0) for k in range(200))
    assert all(LR.coin_flip_best(1, "15m", SYM, k * 15 * MIN, p=1.0) for k in range(200))
    # through a Signal: the account's seed, the signal bar's close (ts + 1)
    bc = 1_790_000_000_000 + 7 * 15 * MIN
    sig = Signal(ts=bc - 1, symbol=SYM, timeframe="15m", strategy_id="RANDOM_2", side=-1, stop_price=0.0,
                 meta={"ctx": {"strength": BEST}})                      # a strength would be ignored
    g = LR.signal_group(sig)
    assert g["source"] == "coin_flip" and g["p_best"] == V3_P_BEST["15m"]
    assert g["group"] == ("best" if LR.coin_flip_best(2, "15m", SYM, bc) else "normal")


def test_coin_flip_draw_is_independent_of_the_signal_draw():
    """sigservice._random draws fire / side from [seed, tf minutes, coin, bar minutes]; the group stream is salted."""
    from paperbot.aggregate import TF_MS
    rng = np.random.default_rng([1, TF_MS["15m"] // MIN, 0, 1_790_000_000_000 // MIN])
    fire, coin = rng.random(), rng.random()
    g = np.random.default_rng([LR.GROUP_SALT, 1, 15, 0, 1_790_000_000_000 // MIN]).random()
    assert g not in (fire, coin)


# ------------------------------------------------------------------ sizing per group
def test_best_group_50x_then_40x_then_falls_to_normal():
    d = _size(0.004, "best")
    assert d.ok and (d.tier, d.leverage) == ("best", 50) and d.margin == pytest.approx(E * 0.50)
    d = _size(0.006, "best")                                # 50x: stop loss over 15% of equity
    assert d.ok and (d.leverage, d.margin) == (40, pytest.approx(E * 0.40)) and len(d.reasons) == 1
    assert d.reasons[0].startswith("best/50x: stop loss")
    d = _size(0.012, "best")                                # 50x and 40x too big: 30x / 30%, still a 'best' signal
    assert d.ok and (d.tier, d.leverage, d.margin) == ("best", 30, pytest.approx(E * 0.30))
    strict = v3_settings(best_falls_to_normal=False)
    d = _size(0.012, "best", strict)                        # groups kept apart: not entered, both reasons recorded
    assert not d.ok and [r.split(":")[0] for r in d.reasons] == ["best/50x", "best/40x"]


def test_normal_group_never_above_30x():
    d = _size(0.004, "normal")                              # 50x would fit, the group starts at 30x
    assert d.ok and (d.tier, d.leverage, d.margin) == ("normal", 30, pytest.approx(E * 0.30)) and d.reasons == []
    d = _size(0.025, "normal")                              # 30x refused (liquidation buffer, loss) -> 20x / 20%
    assert d.ok and (d.leverage, d.margin) == (20, pytest.approx(E * 0.20))
    assert len(d.reasons) == 1 and d.reasons[0].startswith("normal/30x: ")
    d = _size(0.016, "normal", atr=0.1)                     # 30x: loss 9 x (1.6% + costs) > 15% -> 20x
    assert d.ok and d.leverage == 20 and d.reasons[0].startswith("normal/30x: stop loss")
    d = _size(0.04, "normal")                               # neither: not entered, both reasons
    assert not d.ok and [r.split(":")[0] for r in d.reasons] == ["normal/30x", "normal/20x"]


def test_liquidation_buffer_and_bracket_decide_within_the_group():
    d = _size(0.015, "normal", atr=1.6)                     # 30x: stop 1.5% vs liq ~2.9% away, buffer 1 ATR = 1.6%
    assert d.ok and d.leverage == 20 and "too close to liq" in d.reasons[0]
    br25 = Brackets([BracketTier(10_000_000, 25, 0.004, 0.0)])
    d = _size(0.004, "best", br=br25)                       # the exchange allows 25x: 50 / 40 / 30x refused
    assert d.ok and (d.tier, d.leverage) == ("best", 20)
    assert [r.split(":")[0] for r in d.reasons] == ["best/50x", "best/40x", "normal/30x"]
    assert all("bracket allows 25x" in r for r in d.reasons)


def test_engine_sizes_by_the_signal_group():
    def run(meta, strategy=STRAT):
        e = PaperEngine(S, {SYM: BR50})
        e.submit(Signal(ts=MIN - 1, symbol=SYM, timeframe=TF, strategy_id=strategy, side=1, stop_price=0.0,
                        atr=0.2, meta={"stop_dist": 0.4, **meta}))
        e.step({SYM: Bar(SYM, MIN, 2 * MIN - 1, 100.0, 100.01, 99.99, 100.0)})
        return e.position
    p = run({"ctx": {"strength": BEST}})
    assert (p.leverage, p.tier) == (50, "best") and p.margin == pytest.approx(E * 0.5, rel=1e-3)
    for st in (GOOD, BASE, None):
        p = run({"ctx": {"strength": st}} if st else {})
        assert (p.leverage, p.tier) == (30, "normal") and p.margin == pytest.approx(E * 0.3, rel=1e-3)
    bc = MIN
    want = 50 if LR.coin_flip_best(1, TF, SYM, bc) else 30
    assert run({}, "RANDOM_1").leverage == want


def test_copies_inherit_the_parents_group():
    from paperbot.extras import derive
    parent = Signal(ts=MIN - 1, symbol=SYM, timeframe=TF, strategy_id=STRAT, side=1, stop_price=0.0, atr=0.2,
                    meta={"stop_dist": 0.4, "ctx": {"strength": BEST}, "account": f"{STRAT}@{TF}"})
    for rule in ({"template": "stop_atr", "k": 1.5}, {"template": "lock_start", "first_lock": 0.15}):
        c = derive(rule, parent, f"{STRAT}@{TF}~c1")
        assert LR.signal_group(c)["group"] == "best"


def test_daily3_make_signal_carries_the_strength_for_replays():
    from paperbot.daily3 import make_signal
    row = {"bar_close": MIN, "timeframe": TF, "strategy": STRAT, "symbol": SYM, "side": 1, "atr": 0.2,
           "ref_price": 100.0, "ref_time": MIN + 1000, "delay_ms": 1000}
    assert LR.signal_group(make_signal(row))["group"] == "normal"                  # no data: no strength
    for data in (json.dumps({"ctx": {"strength": BEST}}), {"ctx": {"strength": BEST}}):
        assert LR.signal_group(make_signal({**row, "data": data}))["group"] == "best"
    assert LR.signal_group(make_signal({**row, "data": json.dumps({"ctx": {"strength": GOOD}})}))["group"] == "normal"


# ------------------------------------------------------------------ checkpoint bots: the same rule and mixture
def test_size_vec_matches_size_position_per_group():
    rng = np.random.default_rng(4)
    br = ck._BracketArrays.of(Brackets.example())
    n = 3000
    eq = rng.uniform(20, 60_000, n)
    side = rng.choice([-1.0, 1.0], n)
    fill = rng.uniform(0.1, 1000, n)
    atr = fill * rng.uniform(0.0005, 0.02, n)
    stop = fill - side * 2 * atr
    best = rng.random(n) < 0.3
    for s in (S, v3_settings(best_falls_to_normal=False)):
        got = ck.size_vec(s, eq, side, fill, stop, atr, br, 0.001, 5.0, best=best)
        levs = set()
        for i in range(n):
            d = size_position(s, eq[i], int(side[i]), fill[i], stop[i], "best" if best[i] else "normal",
                              Brackets.example(), atr=atr[i], qty_step=0.001, min_notional=5.0)
            assert d.ok == got["ok"][i], i
            if d.ok:
                levs.add((bool(best[i]), d.leverage))
                assert d.leverage == got["lev"][i] and d.margin == pytest.approx(got["margin"][i], rel=1e-12)
                assert d.qty == pytest.approx(got["qty"][i], rel=1e-12)
        assert not {lev for b, lev in levs if not b} & {40, 50}      # 'normal' never above 30x
        assert {lev for b, lev in levs if b} & {40, 50}


def test_simulate_bots_draws_the_frozen_share_and_the_rule():
    from test_checkpoint import BR, SPECS, T0, DAY, synth_minutes
    tf = "15m"
    lo, hi = T0 + 4 * DAY, T0 + 6 * DAY
    m = synth_minutes(T0, hi, seed=7, vol=0.0003)
    atr = ck.tf_atr(m, tf)
    rates = np.full(40, 0.05)
    seen = []

    def spy(p):
        real = ck.group_draws

        def make(rng, p_best):
            seen.append(p_best)
            return real(rng, p_best)
        return make
    orig = ck.group_draws
    try:
        ck.group_draws = spy(None)
        a = ck.simulate_bots(m, tf, lo, hi, rates, S, BR, SPECS, seed=[1, 2], atr=atr)
        b = ck.simulate_bots(m, tf, lo, hi, rates, S, BR, SPECS, seed=[1, 2], atr=atr, p_best=V3_P_BEST[tf])
    finally:
        ck.group_draws = orig
    assert seen == [V3_P_BEST[tf], V3_P_BEST[tf]]                          # default: the frozen share of the timeframe
    assert np.array_equal(a["equity"], b["equity"])
    # p_best 0 = every bot signal 'normal' = an explicit all-False draw; p_best 1 = all 'best'
    zero = ck.simulate_bots(m, tf, lo, hi, rates, S, BR, SPECS, seed=[1, 2], atr=atr, p_best=0.0)
    allf = ck.simulate_bots(m, tf, lo, hi, rates, S, BR, SPECS, seed=[1, 2], atr=atr,
                            group_draw=lambda ts, idx, C: np.zeros((len(idx), C), bool))
    one = ck.simulate_bots(m, tf, lo, hi, rates, S, BR, SPECS, seed=[1, 2], atr=atr, p_best=1.0)
    assert np.array_equal(zero["equity"], allf["equity"]) and not np.array_equal(zero["equity"], one["equity"])
    # the fire / side stream does not depend on the group draws: the same bots enter the same number of trades
    # when nobody is ever refused (wide brackets, quiet bars)
    assert zero["trades"].sum() > 0


def test_group_draw_frequency():
    rng = np.random.default_rng(9)
    d = ck.group_draws(rng, 0.2155)(0, np.arange(4000), 6)
    assert d.shape == (4000, 6) and abs(d.mean() - 0.2155) < 4 * np.sqrt(0.2155 * 0.7845 / d.size)


def test_run_tasks_passes_each_tasks_p_best(monkeypatch):
    got = []

    def fake(m, tf, lo, hi, rates, s, brackets, specs, seed=0, initial=None, stop_atr=2.0, p_best=None, **kw):
        got.append((tf, p_best))
        n = len(rates)
        return {"equity": np.full(n, 5000.0), "bust": np.zeros(n, bool), "trades": np.zeros(n)}
    monkeypatch.setattr(ck, "simulate_bots", fake)
    tasks = [ck.Task("A@15m", "1차", "15m", 0, 30 * 86_400_000, 5100.0, 0.01),
             ck.Task("NL1@1h", "1차", "1h", 0, 30 * 86_400_000, 5100.0, 0.01, cls="NL1@1h", p_best=0.0),
             ck.Task("A@15m~c1", "1차", "15m", 0, 30 * 86_400_000, 5100.0, 0.01, cls="A@15m~c1")]
    _, info = ck.run_tasks(tasks, lambda a, b: None, S, {}, {}, 10, 1, 5000.0)
    assert sorted(got) == sorted([("15m", None), ("1h", 0.0), ("15m", None)])
    assert sorted(r["p_best"] for r in info) == sorted([V3_P_BEST["15m"], 0.0, V3_P_BEST["15m"]])
    assert ck.has_quality_edges(STRAT, "15m") and not ck.has_quality_edges("NL1", "1h")


# ------------------------------------------------------------------ shadows and the P&L-on-equity shares
def test_shadows_under_the_new_rule(tmp_path):
    import test_quality_shadow as Q
    from paperbot.daily3 import make_signal
    from paperbot.obsshadows import FIXED_LEVERAGE, FIXED_LEVERAGE3, MARGIN_FRAC, pnl_equity, rule_margin_fracs, \
        trade_shadows, variant_settings
    assert MARGIN_FRAC[50] == 0.50 and rule_margin_fracs(S) == MARGIN_FRAC
    assert pnl_equity(-1.0, 50, rule_margin_fracs(S)) == -0.50
    for v in tuple(FIXED_LEVERAGE) + tuple(FIXED_LEVERAGE3):
        assert variant_settings(S, v).leverage_rule == "tier_walk"           # one tier, no fallback, any signal
    assert [variant_settings(S, v).tiers[0].margin_frac for v in FIXED_LEVERAGE3] == [0.30, 0.40, 0.40]
    for st, lev in ((Q.BEST, 50), (Q.GOOD, 30)):
        d = tmp_path / str(lev)
        d.mkdir()
        conn, steps = Q._db(d, st, Q.BR50)
        actual = json.loads(conn.execute("SELECT data FROM trades").fetchone()[0])
        assert actual["leverage"] == lev
        rows, info = trade_shadows(S, Q.BR50, {}, conn, "d", 0, len(steps) * MIN, steps, make_signal,
                                   quality=True, extra3=True)
        k = {r["kind"]: r for r in rows}
        base = json.loads(k["base"]["data"])
        assert base["leverage"] == lev and k["base"]["roe"] == pytest.approx(actual["roe"])   # base = the real trade
        assert base["pnl_equity"] == pytest.approx(actual["roe"] * lev / 100)
        assert base["actual_pnl_equity"] == pytest.approx(actual["roe"] * lev / 100)
        for v, want in (("lev10", 10), ("lev20", 20), ("lev30", 30), ("lev40", 40), ("lev50", 50)):
            assert json.loads(k[v]["data"])["leverage"] == want, v                 # 'normal' signals too
        assert json.loads(k["lev50"]["data"])["pnl_equity"] == pytest.approx(k["lev50"]["roe"] * 0.40)


def test_riskreward_shares():
    from paperbot.agents import riskreward as RR
    assert RR.MARGIN_FRAC == {50: 0.50, 40: 0.40, 30: 0.30, 20: 0.20, 10: 0.20}
    assert "진입 품질" in RR.TIER_NOTE and "교란" in RR.TIER_NOTE


# ------------------------------------------------------------------ research/power: the same mixture
def test_power_pool_uses_the_rule():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(root, "research", "power"))
    import power as PW
    import rules_bt as RB
    real = RB.size_position
    bars = PW.synth_bars()
    new = PW.build_pool(bars, "1h", 0.013, seeds=(1,), max_windows=3)
    assert RB.size_position is real                                           # restored
    old = PW.build_pool(bars, "1h", 0.013, seeds=(1,), max_windows=3, rule="tier_walk")
    assert new["trades"] > 30 and old["trades"] > 30
    assert set(np.round(old["mf"], 2)) <= {0.40, 0.30, 0.20} and set(np.round(new["mf"], 2)) <= {0.50, 0.40, 0.30, 0.20}
    # inside the block every rules_bt sizing is the quality_v1 chain of a drawn group (a stop where 50x fits)
    levs = []
    with PW.leverage_rule("quality_v1", "15m", 1):
        for _ in range(4000):
            d = RB.size_position(RB.SETTINGS, 1000.0, 1, 100.0, 99.6, "best", BR50, atr=0.2)
            levs.append((d.leverage, round(d.margin / 1000.0, 2)))
    assert RB.size_position is real and set(levs) == {(50, 0.50), (30, 0.30)}
    share = np.mean([lv == 50 for lv, _ in levs])
    assert abs(share - V3_P_BEST["15m"]) < 4 * np.sqrt(V3_P_BEST["15m"] * (1 - V3_P_BEST["15m"]) / 4000)
    assert PW.leverage_doc()["p_best"] == V3_P_BEST and PW.LEVERAGE_RULE == C.V3_LEVERAGE_RULE
    doc = json.load(open(os.path.join(root, "research", "power", "out", "power.json")))
    assert doc["leverage"]["rule"] == "quality_v1" and doc["leverage"]["p_best"] == V3_P_BEST


def test_symbols_cover_the_coin_keys():
    assert [LR._coin_key(s) for s in V3_SYMBOLS] == list(range(len(V3_SYMBOLS)))
    assert LR._coin_key("XRPUSDT") >= 100

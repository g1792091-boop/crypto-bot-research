"""The quality shadow (docs/observation-shadows-2.md): sizing tier requested by the signal's recorded
entry-strength score, mean period-1 quintile of the strategy's features."""

import bisect
import csv
import hashlib
import json
import math
import os

import numpy as np
import pytest

import paperbot.obsshadows as O
from paperbot import Bar, Brackets
from paperbot.config import V3_SYMBOLS, v3_settings
from paperbot.daily3 import _alone, make_signal
from paperbot.margin import BracketTier
from paperbot.obsshadows import (QUALITY, QUALITY_TIERS, VARIANTS, quality_edges, quality_score, quality_tier,
                                 quintile, signal_strength, summarize, trade_shadows)
from paperbot.store3 import Store3

MIN = 60_000
DAY = 86_400_000
S = v3_settings()
BR = {s: Brackets.example() for s in V3_SYMBOLS}
BR50 = {s: Brackets([BracketTier(10_000_000, 50, 0.004, 0.0)]) for s in V3_SYMBOLS}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(ROOT, "research", "entry_study", "out", "bc_B_quintiles.csv")
SYM = "BTCUSDT"
REF, ATR = 100.0, 0.2
I0 = 10
ENTRY = REF * (1 + S.slippage_frac)
STRAT, TF = "N03_ADX_GC", "15m"          # 3 features, one of them lower-is-stronger (cross_lag_bars)


# ------------------------------------------------------------------ frozen inputs
def test_preregistration_2_hash_matches_and_first_doc_unchanged():
    for name in ("observation-shadows", "observation-shadows-2"):
        line = open(os.path.join(ROOT, "docs", f"{name}.sha256")).read().split()
        body = open(os.path.join(ROOT, "docs", f"{name}.md"), "rb").read()
        assert line[1] == f"docs/{name}.md" and hashlib.sha256(body).hexdigest() == line[0]


def test_frozen_edges_equal_the_study_csv():
    meta = json.load(open(O.QUALITY_EDGES_PATH))
    assert meta["source"] == "research/entry_study/out/bc_B_quintiles.csv" and meta["period"] == 1
    assert meta["source_sha256"] == "c0e04ca17646714627dc521fc1862bfdd7d88b4cd013ceaba1ac0174dcc89d48"
    if not os.path.exists(CSV):
        pytest.skip("no study CSV (the frozen copy is used)")
    if hashlib.sha256(open(CSV, "rb").read()).hexdigest() != meta["source_sha256"]:
        pytest.skip("CSV rebuilt since the pre-registration (the frozen copy stays)")
    want: dict = {}
    for r in csv.DictReader(open(CSV)):
        if r["period"] == "1" and r["quintile"] in ("1", "2", "3", "4"):
            f = want.setdefault(f"{r['strategy']}|{r['tf']}", {}).setdefault(
                r["feature"], {"higher_is_stronger": r["higher_is_stronger"] == "True", "edges": []})
            f["edges"].append(float(r["edge_hi"]))
    assert quality_edges() == want
    assert len(want) == 166 and sum(len(v) for v in want.values()) == 473


# ------------------------------------------------------------------ quintiles
def test_quintile_higher_is_stronger_and_edge_values():
    e = [1.0, 2.0, 3.0, 4.0]
    assert [quintile(v, e, True) for v in (-5, 0.999, 1.0, 1.5, 2.0, 3.5, 4.0, 1e9)] == [1, 1, 2, 2, 3, 4, 5, 5]
    for bad in (None, float("nan"), float("inf"), -math.inf, "x", True):
        assert quintile(bad, e, True) is None


def test_quintile_lower_is_stronger_uses_the_signed_edges():
    # N03_ADX_GC 15m cross_lag_bars: lower = stronger, CSV edges are of -value: [-2, -1, -1, 0]
    e = quality_edges()[f"{STRAT}|{TF}"]["cross_lag_bars"]
    assert e == {"higher_is_stronger": False, "edges": [-2.0, -1.0, -1.0, 0.0]}
    q = {v: quintile(v, e["edges"], False) for v in (0, 1, 2, 3, 7)}
    assert q == {0: 5, 1: 4, 2: 2, 3: 1, 7: 1}          # a value on an edge goes up (study rule)


def test_flipped_equals_six_minus_raw_quintile_off_the_edges():
    rng = np.random.default_rng(0)
    for cell in list(quality_edges().values())[:40]:
        for f in cell.values():
            signed = f["edges"]
            raw = sorted(-x for x in signed)            # the same edges on the raw scale
            for v in rng.normal(0, 3 * (abs(signed[-1]) + 1), 50):
                if any(abs(v + x) < 1e-12 for x in signed):
                    continue
                q_raw = 1 + bisect.bisect_right(raw, v)
                assert quintile(v, signed, False) == 6 - q_raw
                assert quintile(v, signed, True) == 1 + int(np.searchsorted(signed, v, side="right"))


# ------------------------------------------------------------------ score and tier
def _strength(adx, lag, gap, side=1):
    feats = [("adx_excess", True, adx), ("cross_lag_bars", False, lag), ("ema_gap_atr", True, gap)]
    return {"side": side, "features": [{"name": n, "label_ko": n, "unit": "", "unit_ko": "",
                                        "higher_is_stronger": h, "value": v} for n, h, v in feats]}


BEST = _strength(10.0, 0, 1.0)          # 5, 5, 5
GOOD = _strength(1.5, 2, 0.05)          # 3, 2, 3 -> 2.67
BASE = _strength(0.1, 5, 0.0)           # 1, 1, 1


def test_tier_thresholds():
    assert [quality_tier(s) for s in (5, 4, 3.9999, 3, 2.0001, 2, 1)] == \
        ["best", "best", "good", "good", "good", "base", "base"]


def test_score_three_tiers_and_partial_values():
    b, g, s = (quality_score(x, STRAT, TF) for x in (BEST, GOOD, BASE))
    assert (b["score"], b["tier"], b["quintiles"]) == (5, "best", {"adx_excess": 5, "cross_lag_bars": 5,
                                                                    "ema_gap_atr": 5})
    assert g["score"] == pytest.approx(8 / 3) and g["tier"] == "good"
    assert (s["score"], s["tier"], s["reason"]) == (1, "base", None)
    # a feature without a value is left out of the mean: (5 + 3) / 2 = 4 -> best
    p = quality_score(_strength(10.0, None, 0.05), STRAT, TF)
    assert p["quintiles"] == {"adx_excess": 5, "ema_gap_atr": 3} and p["tier"] == "best"
    # exactly 2 -> base, exactly 4 -> best
    assert quality_score(_strength(10.0, 3, 0.0), STRAT, TF)["score"] == pytest.approx(7 / 3)
    assert quality_score(_strength(1.0, 2, None), STRAT, TF) == {
        "score": 2.0, "tier": "base", "quintiles": {"adx_excess": 2, "cross_lag_bars": 2}, "reason": None}


def test_missing_strength_is_not_scored():
    for st, why in ((None, "no_strength"), ({}, "no_strength"), ("x", "no_strength"),
                    ({"error": "ValueError: boom"}, "strength_error"),
                    (_strength(None, None, None), "no_values")):
        q = quality_score(st, STRAT, TF)
        assert (q["score"], q["tier"], q["reason"]) == (None, None, why)
    assert quality_score(BEST, "RANDOM_1", TF)["reason"] == "no_edges"
    assert quality_score(BEST, STRAT, "1d")["reason"] == "no_edges"
    assert signal_strength({"data": json.dumps({"ctx": {"strength": BEST}})}) == BEST
    assert signal_strength({"data": json.dumps({"ctx": {"sr": {}}})}) is None
    assert signal_strength({"data": "{}"}) is None and signal_strength({"data": None}) is None


# ------------------------------------------------------------------ the shadow run
def _bar(ts, o, h, lo, c):
    return Bar(SYM, ts, ts + MIN - 1, o, h, lo, c, o, h, lo, c, volume=1.0)


def _steps():
    """Flat, then a drop through the 2 ATR stop: every tier ends on SL."""
    st = [(i * MIN, {SYM: _bar(i * MIN, ENTRY, ENTRY * 1.0002, ENTRY * 0.9998, ENTRY)}, {}) for i in range(I0 + 5)]
    st.append(((I0 + 5) * MIN, {SYM: _bar((I0 + 5) * MIN, ENTRY, ENTRY, 99.0, 99.1)}, {}))
    return st


def _db(tmp_path, st, brackets):
    """paper3-like db with one signal (its ctx strength = ``st``, None = not recorded) and its actual trade."""
    store = Store3(str(tmp_path / "p.db"))
    steps = _steps()
    row = {"bar_close": I0 * MIN, "timeframe": TF, "strategy": STRAT, "symbol": SYM, "side": 1, "atr": ATR,
           "ref_price": REF, "ref_time": I0 * MIN + 1000, "delay_ms": 1000, "status": "SUBMITTED",
           "data": {"close": REF, "ctx": {} if st is None else {"strength": st}}}
    store.log_signals([row])
    t, ok = _alone(S, brackets, {}, make_signal(row), steps, I0)
    assert ok and t is not None
    store.trade(f"{STRAT}@{TF}", t)
    store.commit()
    return store.conn, steps


@pytest.mark.parametrize("st,tier,lev", [(BEST, "best", 50), (GOOD, "good", 30), (BASE, "base", 20)])
def test_quality_requests_the_scored_tier(tmp_path, st, tier, lev):
    conn, steps = _db(tmp_path, st, BR50)
    rows, info = trade_shadows(S, BR50, {}, conn, "d", 0, len(steps) * MIN, steps, make_signal, quality=True)
    assert info == {"closed": 1, "no_signal": 0, "no_steps": 0, "no_quality": 0, "no_quality_reasons": {}}
    k = {r["kind"]: r for r in rows}
    assert set(k) == set(VARIANTS) | {QUALITY}
    q, d = k[QUALITY], json.loads(k[QUALITY]["data"])
    assert q["key"] == f"quality|{STRAT}@{TF}|{SYM}|{I0 * MIN}" and q["exit_reason"] == "SL" and q["resolved"] == 1
    assert d["quality_tier"] == tier and d["leverage"] == lev and d["tier"] == tier
    assert d["pnl_equity"] == pytest.approx(q["roe"] * {50: 0.40, 30: 0.30, 20: 0.20}[lev])
    # the base (the live rule, quality_v1 since 2026-10-04): 'best' 50% x 50x, any other tier 'normal' 30% x 30x;
    # the quality shadow keeps its registered tier table (40% x 50x, 30% x 30x, 20% x 20x)
    base_lev = {"best": 50, "good": 30, "base": 30}[tier]
    assert json.loads(k["base"]["data"])["leverage"] == base_lev
    if lev == base_lev:
        assert q["roe"] == pytest.approx(k["base"]["roe"])
    else:
        assert q["roe"] > k["base"]["roe"]                   # the same stop costs less ROE at lower leverage
    rep = summarize(rows, info)[QUALITY]
    assert rep["tier_mix"] == {t: int(t == tier) for t in QUALITY_TIERS}
    assert rep["leverage_mix"] == {str(lev): 1}
    assert rep["by_tier"][tier]["resolved"] == 1 and rep["by_tier"][tier]["base"]["trades"] == 1
    assert rep["base"]["mean_pnl_equity"] == pytest.approx(json.loads(k["base"]["data"])["pnl_equity"])
    assert rep["no_quality"] == 0


def test_best_falls_back_by_the_normal_chain(tmp_path):
    # example brackets do not allow 50x on a $5,000 best tier: best steps down like the base shadow does
    conn, steps = _db(tmp_path, BEST, BR)
    rows, _ = trade_shadows(S, BR, {}, conn, "d", 0, len(steps) * MIN, steps, make_signal, quality=True)
    k = {r["kind"]: json.loads(r["data"]) for r in rows}
    assert k[QUALITY]["leverage"] == k["base"]["leverage"] < 50
    assert k[QUALITY]["quality_tier"] == "best"


def test_missing_strength_counts_no_quality_and_runs_nothing(tmp_path):
    conn, steps = _db(tmp_path, None, BR50)
    rows, info = trade_shadows(S, BR50, {}, conn, "d", 0, len(steps) * MIN, steps, make_signal, quality=True)
    assert info["no_quality"] == 1 and info["no_quality_reasons"] == {"no_strength": 1}
    assert {r["kind"] for r in rows} == set(VARIANTS)
    rep = summarize(rows, info)
    q = rep[QUALITY]
    assert q["trades"] == 0 and q["no_quality"] == 1 and q["tier_mix"] == {"best": 0, "good": 0, "base": 0}
    assert q["mean_roe"] is None and q["by_tier"]["best"]["base"]["mean_roe"] is None
    # without the flag nothing about quality appears (the 7 pre-registered variants only)
    rows2, info2 = trade_shadows(S, BR50, {}, conn, "d", 0, len(steps) * MIN, steps, make_signal)
    assert info2 == {"closed": 1, "no_signal": 0, "no_steps": 0} and QUALITY not in summarize(rows2, info2)


def test_report_keys_on_a_live_day(tmp_path, monkeypatch):
    """run_day end to end: strategy A gets a strength record (scored), B none (no_quality)."""
    import sqlite3

    import paperbot.daily3 as D
    from test_daily3 import _live_day
    store, steps = _live_day(str(tmp_path / "p.db"))
    monkeypatch.setattr(D, "fetch_steps", lambda rest, syms, a, b: [s for s in steps if a <= s[0] < b])
    monkeypatch.setattr(O, "_QUALITY_EDGES", {"A|15m": {"f": {"higher_is_stronger": True,
                                                              "edges": [0.2, 0.4, 0.6, 0.8]}}})
    rng = np.random.default_rng(1)
    for (i,) in store.conn.execute("SELECT id FROM signal_log WHERE strategy = 'A'").fetchall():
        st = {"side": 1, "features": [{"name": "f", "higher_is_stronger": True, "value": float(rng.random())}]}
        store.conn.execute("UPDATE signal_log SET data = ? WHERE id = ?", (json.dumps({"ctx": {"strength": st}}), i))
    store.commit()

    class Rest:
        def server_time(self):
            return DAY + 2 * MIN

    out = sqlite3.connect(str(tmp_path / "d.db"))
    out.executescript(D.SCHEMA)
    rep = D.run_day(store.conn, out, Rest(), S, BR, {}, "1970-01-01")
    tv = rep["shadows"]["trade_variants"]
    q = tv[QUALITY]
    closed_a = store.conn.execute("SELECT COUNT(*) FROM trades WHERE exit_time < ? AND account_id = 'A@15m'",
                                  (DAY,)).fetchone()[0]
    assert closed_a > 3
    assert q["trades"] == closed_a and q["no_quality"] == tv["closed"] - closed_a
    assert q["no_quality_reasons"] == {"no_strength": tv["closed"] - closed_a}
    assert set(q) == {"trades", "resolved", "rejected", "open_at_horizon", "mean_roe", "mean_pnl_equity",
                      "liquidations", "better_share", "worse_share", "actual", "base", "tier_mix", "leverage_mix",
                      "by_tier", "no_quality", "no_quality_reasons"}
    assert sum(q["tier_mix"].values()) == closed_a and set(q["by_tier"]) == set(QUALITY_TIERS)
    assert sum(q["leverage_mix"].values()) == q["resolved"]
    assert sum(q["by_tier"][t]["trades"] for t in QUALITY_TIERS) == closed_a
    for v in VARIANTS:
        assert tv[v]["trades"] == tv["closed"]
    kinds = dict(out.execute("SELECT kind, COUNT(*) FROM shadows GROUP BY kind").fetchall())
    assert kinds[QUALITY] == closed_a
    n = out.execute("SELECT COUNT(*) FROM shadows").fetchone()[0]
    assert n == len({r[0] for r in out.execute("SELECT key FROM shadows")})
    tiers = [json.loads(d)["quality_tier"] for (d,) in out.execute("SELECT data FROM shadows WHERE kind='quality'")]
    assert len(set(tiers)) >= 2
    json.dumps(rep)

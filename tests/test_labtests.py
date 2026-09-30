"""Lab tests (paperbot/agents/labtests.py) and the cache builder's parsing (labdata.py).

Everything runs on small synthetic caches written into tmp dirs; nothing touches the network.
"""

import io
import json
import os
import zipfile
from datetime import date

import numpy as np
import pandas as pd
import pytest

from paperbot import cards, sweepsig
from paperbot.agents import labdata as LD
from paperbot.agents import labtests as LT
from paperbot.ladder import LadderSpec

NAMES = ("AAA", "BBB")
COINS2 = ("BTCUSD", "ETHUSD")


def _ns(ts: pd.Series) -> np.ndarray:
    return ts.dt.tz_localize(None).to_numpy().astype("datetime64[ns]").astype(np.int64)


def _write_cache(d: str, tf: str, coin: str, start: str, n: int, seed: int, rate: float = 0.05) -> dict:
    L = sweepsig.lib()
    df = L.synth_ohlcv(n, tf, seed=seed, start=start)
    rng = np.random.default_rng(seed + 1000)
    arrs = dict(ts=_ns(df["ts"]), o=df["open"].to_numpy(float), h=df["high"].to_numpy(float),
                l=df["low"].to_numpy(float), c=df["close"].to_numpy(float),
                atr=L.fg.atr(df, 14).to_numpy(float))
    for nm in NAMES:
        fire = rng.random(n) < rate
        arrs[f"s__{nm}"] = np.where(fire, np.where(rng.random(n) < 0.5, 1, -1), 0).astype(np.int8)
    os.makedirs(d, exist_ok=True)
    np.savez_compressed(os.path.join(d, f"sig_{tf}_{coin}.npz"), **arrs)
    return arrs


@pytest.fixture(scope="module")
def cache(tmp_path_factory):
    """1h bars 2024-05-01 .. ~2024-09-04 (warm-up 720 bars, then periods 1 and 2) for two coins,
    plus a pre-2021 cache 2020-01-01 .. ~2020-04-14 (period 3)."""
    root = str(tmp_path_factory.mktemp("lab"))
    for k, coin in enumerate(COINS2):
        _write_cache(root, "1h", coin, "2024-05-01", 3000, seed=10 + k)
        _write_cache(os.path.join(root, "pre2021"), "1h", coin, "2020-01-01", 2500, seed=20 + k)
    return root


# ------------------------------------------------------------------ same numbers as profiles.py
def test_default_reproduces_profiles_py(cache):
    P = LT.profiles_module()
    L = sweepsig.lib()
    data = LT.LabData(cache, pre2021_dir="")          # main cache only
    for nm in NAMES:
        parts = []
        for coin in COINS2:
            _tf, _coin, out, days = P._job(("1h", coin, cache))
            parts.append(out[nm])
            b = data.bars("main", "1h", coin)
            lo, n_end = LT._source_range(L, b["ts"], "1h", [p for p in LT.PERIODS if p[3] == "main"])
            mine = LT.signal_outcomes(b, data.signal("main", "1h", coin, nm), lo, n_end, "1h")
            theirs = out[nm]
            assert len(mine["idx"]) == len(theirs["side"])
            np.testing.assert_array_equal(mine["side"], theirs["side"])
            np.testing.assert_array_equal(mine["lev"].astype(np.int16), theirs["lev"])
            np.testing.assert_allclose(mine["roe"].astype(np.float32), theirs["roe"], rtol=1e-6, atol=1e-7)
            np.testing.assert_array_equal(np.nan_to_num(mine["reason"], nan=-1),
                                          np.nan_to_num(theirs["reason"].astype(float), nan=-1))
        prof = P.summarise("1h", parts, days, L.tf_minutes("1h"))
        r = LT.run_test({"template": "timeframe_only", "strategy": nm, "timeframe": "1h"}, data)
        assert r["ok"], r
        per = r["timeframes"]["1h"]
        assert per["1"]["baseline"]["trades"] > 30 and per["2"]["baseline"]["trades"] > 30
        for pid, w in (("1", "is"), ("2", "cf")):
            assert abs(per[pid]["baseline"]["mean_roe"] - prof["mean_roe_by_window"][w]) < 1e-6
        assert per["3"]["available"] is False


def test_default_ladder_and_stop_parameters_change_nothing(cache):
    L = sweepsig.lib()
    data = LT.LabData(cache)
    b = data.bars("main", "1h", "BTCUSD")
    sg = data.signal("main", "1h", "BTCUSD", "AAA")
    lo, n_end = LT._source_range(L, b["ts"], "1h", [p for p in LT.PERIODS if p[3] == "main"])
    a = LT.signal_outcomes(b, sg, lo, n_end, "1h")
    c = LT.signal_outcomes(b, sg, lo, n_end, "1h", k_stop=2.0, ladder=LadderSpec(first_lock=0.10))
    np.testing.assert_array_equal(a["roe"], c["roe"])
    np.testing.assert_array_equal(a["reason"], c["reason"])


def _flat(n=400, px=100.0, atr=0.5):
    ts = (np.arange(n, dtype=np.int64) * 3600 + 1_720_000_000) * 1_000_000_000
    o = np.full(n, px)
    return dict(ts=ts, o=o.copy(), h=o + 0.1, l=o - 0.1, c=o.copy(), atr=np.full(n, atr))


def test_lock_start_moves_the_first_lock():
    """Long at ~100, best net ROE ~14.5% (arms the 10% lock, not a 20% one), then a fall through
    the 2 ATR stop: the default ladder exits at the 10% lock, first_lock 0.20 at the stop."""
    P = LT.profiles_module()
    RB = P.RB
    b = _flat()
    sg = np.zeros(400, np.int8)
    sg[310] = 1
    lev = P._sizer()(1, 0.5 / 100.0)[0]
    assert lev > 0
    fill = 100.0 * (1 + RB.SETTINGS.slippage_frac)
    f_bar = RB.FUNDING_8H * 60 / 480.0
    peak = fill * (1 + 0.145 / lev + RB.SETTINGS.round_trip_cost + f_bar * 9)
    for j in range(312, 320):
        b["h"][j] = 100.0 + (peak - 100.0) * (j - 311) / 8
        b["o"][j] = b["c"][j] = b["h"][j] - 0.01
        b["l"][j] = b["o"][j] - 0.02
    b["o"][320], b["h"][320], b["l"][320], b["c"][320] = peak - 0.01, peak, 98.0, 98.2
    base = LT.signal_outcomes(b, sg, 300, 400, "1h")
    var = LT.signal_outcomes(b, sg, 300, 400, "1h", ladder=LadderSpec(first_lock=0.20))
    assert base["reason"][0] == 1 and abs(base["roe"][0] - 0.10) < 0.02, base
    assert var["reason"][0] == 0 and var["roe"][0] < 0, var
    # a 3 ATR stop (98.5) is still above the low (98.0): stopped on the same bar, further away
    wide = LT.signal_outcomes(b, sg, 300, 400, "1h", k_stop=3.0, ladder=LadderSpec(first_lock=0.20))
    assert wide["reason"][0] == 0 and wide["held"][0] == var["held"][0]
    assert wide["roe"][0] / wide["lev"][0] < var["roe"][0] / var["lev"][0]


# ------------------------------------------------------------------ causal context and tags
def _df5(n, seed=1):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    o = np.r_[c[0], c[:-1]]
    t0 = pd.Timestamp("2023-11-15", tz="UTC").value // 1_000_000
    return pd.DataFrame({"ts": pd.to_datetime(t0 + np.arange(n) * 300_000, unit="ms", utc=True),
                         "open": o, "high": np.maximum(o, c) * 1.001, "low": np.minimum(o, c) * 0.999, "close": c,
                         "volume": 1.0})


def test_contexts_match_sigservice_chart_context():
    from paperbot.recorder import build_frames
    from paperbot.sigservice import chart_context
    lib = sweepsig.lib()
    df5 = _df5(12 * 24 * 40)
    df = build_frames(lib, df5, ["1h"])["1h"]
    b = {"ts": _ns(df["ts"]), "o": df["open"].to_numpy(float), "h": df["high"].to_numpy(float),
         "l": df["low"].to_numpy(float), "c": df["close"].to_numpy(float)}
    for i in (len(df) - 1, 700, 433):
        t_close = df["ts"].iloc[i] + pd.Timedelta(hours=1)
        live = chart_context(lib, "BTCUSDT", df5[df5["ts"] < t_close].reset_index(drop=True),
                             df.iloc[:i + 1].reset_index(drop=True), "1h")
        mine = LT.contexts_for(b, "1h", [i])[i]
        assert mine == live, (i, mine, live)


def test_skip_tags_are_the_cards_tags():
    assert set(LT.SKIP_TAGS) <= {name for name, _ in cards.TAGS}
    assert set(LT.TEMPLATES["skip_tag"]["tag"]) == set(LT.SKIP_TAGS)
    ctxs = [{"regime": "trend_down", "htf_regime": "trend_up", "adx": 15.0, "di_plus": 10.0, "di_minus": 20.0,
             "ema20_dist_atr": 2.5, "range_pct": 0.95},
            {"regime": "chop", "htf_regime": "box", "adx": None, "di_plus": None, "di_minus": None,
             "ema20_dist_atr": -2.5, "range_pct": 0.05},
            {"regime": "unknown"}, {}]
    for ctx in ctxs:
        for side in (1, -1):
            t = {"side": side, "leverage": 20, "entry_price": 100.0, "timeframe": "1h", "entry_time": 0,
                 "exit_time": 5 * 3_600_000, "context": ctx, "mfe_price": None, "mae_price": None,
                 "strategy_id": "AAA", "symbol": "BTCUSDT", "exit_price": 99.0, "exit_reason": "SL",
                 "roe": -0.2, "pnl": -10.0, "signal_ts": -1}
            from_card = set(cards.card("AAA@1h", t, 0.001)["tags"]) & set(LT.SKIP_TAGS)
            mine = {tag for tag in LT.SKIP_TAGS if LT.has_tag(tag, side, ctx)}
            assert mine == from_card, (ctx, side)
    assert LT.has_tag("추세 반대 진입", 1, ctxs[0]) and not LT.has_tag("추세 반대 진입", -1, ctxs[0])


def test_skip_tag_run_removes_exactly_the_tagged_trades(cache):
    data = LT.LabData(cache)
    counts = {}
    for tag in ("횡보장 진입", "추세 약함 (ADX 20 미만)"):
        r = LT.run_test({"template": "skip_tag", "strategy": "AAA", "timeframe": "1h", "tag": tag}, data, n_trials=2)
        assert r["ok"], r
        for pid in ("1", "2", "3"):
            row = r["periods"][pid]
            assert row["available"]
            assert row["variant"]["trades"] + row["skipped"] == row["baseline"]["trades"]
        counts[tag] = sum(r["periods"][p]["skipped"] for p in ("1", "2", "3"))
        json.dumps(r)
    assert counts["횡보장 진입"] > 0
    # recount one period by hand from the cached contexts
    L = sweepsig.lib()
    n_tag = 0
    for coin in COINS2:
        b = data.bars("main", "1h", coin)
        lo, n_end = LT._source_range(L, b["ts"], "1h", [p for p in LT.PERIODS if p[3] == "main"])
        o = data.outcomes("main", "1h", coin, "AAA", lo, n_end)
        m = o["done"] & (b["ts"][o["idx"]] < pd.Timestamp("2024-07-01").value)
        ctx = data.contexts("main", "1h", coin, o["idx"][m])
        n_tag += sum(LT.has_tag("횡보장 진입", s, ctx[int(i)]) for i, s in zip(o["idx"][m], o["side"][m]))
    r = LT.run_test({"template": "skip_tag", "strategy": "AAA", "timeframe": "1h", "tag": "횡보장 진입"}, data)
    assert r["periods"]["1"]["skipped"] == n_tag


def test_stop_and_lock_runs_report_all_periods(cache):
    data = LT.LabData(cache)
    assert data.pre2021_dir == os.path.join(cache, "pre2021")
    for spec in ({"template": "stop_atr", "strategy": "BBB", "timeframe": "1h", "k": 2.5},
                 {"template": "lock_start", "strategy": "BBB", "timeframe": "1h", "first_lock": 0.3}):
        r = LT.run_test(spec, data, n_trials=3)
        assert r["ok"] and r["data"]["pre2021"] is True
        assert set(r["periods"]) == {"1", "2", "3"}
        for row in r["periods"].values():
            assert row["available"] and row["baseline"]["trades"] > 0 and row["variant"]["trades"] > 0
            assert row["diff"] == pytest.approx(row["variant"]["mean_roe"] - row["baseline"]["mean_roe"])
            assert 0 < row["p"] <= 1 and row["weeks"] > 0
        assert r["gate"]["n_trials"] == 3 and r["gate"]["pass"] is False  # < 300 trades in period 1
        assert r["gate"]["checks"]["e"] is False
        assert "5년 시험" in r["summary_ko"] and "판정" in r["summary_ko"]
        for row in r["periods"].values():
            for arm in ("baseline", "variant"):
                x = row[arm]
                assert 20 <= x["mean_lev"] <= 50 and x["mean_ret_notional"] is not None
                assert x["mean_pnl_equity"] == pytest.approx(x["mean_roe"] * 0.4, rel=0.6)   # 40%/30%/20% margin
        if spec["template"] == "stop_atr":
            p1 = r["periods"]["1"]
            assert set(r["gate"]["checks"]) == set("abcdef") and "diff_notional" in p1 and 0 < p1["p_notional"] <= 1
            assert p1["diff_notional"] == pytest.approx(p1["variant"]["mean_ret_notional"]
                                                        - p1["baseline"]["mean_ret_notional"])
            assert "평균 레버리지" in r["summary_ko"]
        else:
            assert "diff_notional" not in r["periods"]["1"] and "평균 레버리지" not in r["summary_ko"]
        json.dumps(r)
    # the same request gives the same numbers (fixed bootstrap seed)
    a = LT.run_test({"template": "stop_atr", "strategy": "BBB", "timeframe": "1h", "k": 1.5}, data)
    b = LT.run_test({"k": 1.5, "timeframe": "1h", "strategy": "BBB", "template": "stop_atr"}, LT.LabData(cache))
    assert a["periods"] == b["periods"]


# ------------------------------------------------------------------ bootstrap
def test_week_of_starts_on_monday_utc():
    mon = pd.Timestamp("2024-07-01").value            # a Monday
    assert LT.week_of(np.array([mon]))[0] == LT.week_of(np.array([mon + 7 * 86_400_000_000_000 - 1]))[0]
    assert LT.week_of(np.array([mon - 1]))[0] == LT.week_of(np.array([mon]))[0] - 1


def test_block_bootstrap():
    rng = np.random.default_rng(0)
    ts = pd.Timestamp("2022-01-03").value + np.sort(rng.integers(0, 150 * 7 * 86_400_000_000_000, 3000))
    w = LT.week_of(ts)
    roe = rng.normal(-0.03, 0.3, 3000)
    same = LT.block_bootstrap(w, roe, w, roe, 2000, seed=1)
    assert same["diff"] == 0 and same["p"] == 1.0
    better = LT.block_bootstrap(w, roe, w, roe + 0.05, 2000, seed=1)
    assert better["diff"] == pytest.approx(0.05) and better["p"] == pytest.approx(1 / 2001)
    worse = LT.block_bootstrap(w, roe, w, roe - 0.05, 2000, seed=1)
    assert worse["p"] == 1.0
    noise = LT.block_bootstrap(w, roe, w, roe + rng.normal(0, 0.3, 3000), 2000, seed=1)
    assert 0.001 < noise["p"] < 0.999 and noise["weeks"] == len(np.unique(w))
    assert LT.block_bootstrap(w, roe, w[:0], roe[:0])["p"] is None


# ------------------------------------------------------------------ gate
def _result(d1=0.01, p1=0.001, d2=0.01, p2=0.01, m1=0.02, m2=0.01, n1=500, p3=None, n2=400, dn=(0.0002, 0.0001),
            template="stop_atr"):
    def row(d, p, m, n, dnot):
        return {"available": True, "baseline": {"trades": n, "mean_roe": m - d},
                "variant": {"trades": n, "mean_roe": m, "mean_pnl_equity": m * 0.3},
                "diff": d, "p": p, "diff_notional": dnot, "p_notional": 0.01}
    per = {"1": row(d1, p1, m1, n1, dn[0]), "2": row(d2, p2, m2, n2, dn[1]),
           "3": p3 if p3 is not None else {"available": False}}
    return {"ok": True, "template": template, "periods": per}


def test_gate_passes_only_when_every_check_passes():
    g = LT.gate(_result(), 1)
    assert g["pass"] is True and all(g["checks"].values()) and len(g["reasons"]) == 6
    assert len(LT.gate(_result(template="skip_tag"), 1)["reasons"]) == 5     # ⑥ is for stop_atr only
    assert any("0.05 ÷ 이 방의 시험 1번" in r for r in g["reasons"])
    assert LT.gate(_result(p1=0.02), 1)["pass"] is True
    assert LT.gate(_result(p1=0.02), 3)["pass"] is False           # Bonferroni: 0.05 / 3
    assert LT.gate(_result(p1=0.02), 3)["checks"]["a"] is False
    assert LT.gate(_result(p1=0.02), 0)["alpha_period1"] == 0.05
    assert LT.gate(_result(d1=-0.01), 1)["pass"] is False          # (a) worse
    assert LT.gate(_result(d2=-0.01), 1)["pass"] is False          # (b) other sign
    assert LT.gate(_result(p2=0.2), 1)["pass"] is False            # (b) not clear
    assert LT.gate(_result(m1=-0.001), 1)["pass"] is False         # (d) copy still loses
    assert LT.gate(_result(m2=0.0), 1)["pass"] is False            # (d)
    assert LT.gate(_result(n1=299), 1)["pass"] is False            # (e)
    p3_bad = {"available": True, "baseline": {"trades": 100}, "variant": {"trades": 100}, "diff": -0.001, "p": 0.6}
    assert LT.gate(_result(p3=p3_bad), 1)["checks"]["c"] is False  # (c) period 3 other sign
    p3_small = dict(p3_bad, baseline={"trades": 10}, variant={"trades": 10})
    assert LT.gate(_result(p3=p3_small), 1)["pass"] is True        # too few baseline trades: not judged
    # a variant that keeps almost nothing of 200 period-3 trades, and loses on it, is not replicated
    p3_gone = {"available": True, "baseline": {"trades": 200}, "variant": {"trades": 4, "mean_roe": -0.5},
               "diff": -0.48, "p": 0.99}
    g = LT.gate(_result(p3=p3_gone), 1)
    assert g["pass"] is False and g["checks"]["c"] is False and "4건뿐" in g["reasons"][2]
    p3_few_but_better = dict(p3_gone, variant={"trades": 4, "mean_roe": 0.1}, diff=0.12)
    assert LT.gate(_result(p3=p3_few_but_better), 1)["checks"]["c"] is False
    # period-2 "replication" on a handful of trades is not replication
    g = LT.gate(_result(n2=5), 1)
    assert g["pass"] is False and g["checks"]["b"] is False and "100건 이상" in g["reasons"][1]
    assert LT.gate(_result(n2=100), 1)["pass"] is True
    # stop_atr: an ROE gain that is only the lower leverage of a wider stop does not pass (⑥)
    g = LT.gate(_result(dn=(-0.00001, 0.0001)), 1)
    assert g["pass"] is False and g["checks"]["f"] is False and all(g["checks"][k] for k in "abcde")
    assert "레버리지" in g["reasons"][5]
    assert LT.gate(_result(dn=(0.0001, None)), 1)["pass"] is False
    assert LT.gate(_result(dn=(-1, -1), template="skip_tag"), 1)["pass"] is True    # other templates: no ⑥
    p3_ok = dict(p3_bad, diff=0.002)
    assert LT.gate(_result(p3=p3_ok), 1)["pass"] is True
    assert LT.gate({"ok": False}, 1)["pass"] is False
    assert LT.gate({**_result(), "template": "timeframe_only"}, 1)["pass"] is False
    none = _result()
    none["periods"]["2"]["p"] = None
    assert LT.gate(none, 1)["pass"] is False


def test_gate_check_d_needs_the_copy_to_make_money_on_equity():
    """ROE on margin can be > 0 while the P&L on equity (ROE x margin share: 40% at 50x/40x, 30% at 30x,
    20% at 20x) is < 0, e.g. many small 20x wins and two big 30x losses: a copy account would lose."""
    r = _result()
    r["periods"]["2"]["variant"]["mean_pnl_equity"] = -0.0005
    g = LT.gate(r, 1)
    assert g["pass"] is False and g["checks"]["d"] is False and all(g["checks"][k] for k in "abcef")
    assert "자산 대비 손익" in g["reasons"][3] and "-0.05%" in g["reasons"][3] and "미달" in g["reasons"][3]
    r = _result()
    r["periods"]["1"]["variant"]["mean_pnl_equity"] = -0.001
    assert LT.gate(r, 1)["checks"]["d"] is False
    # missing values fail closed (an old stored result without the equity column never passes)
    r = _result()
    del r["periods"]["1"]["variant"]["mean_pnl_equity"]
    g = LT.gate(r, 1)
    assert g["pass"] is False and g["checks"]["d"] is False and "없음" in g["reasons"][3]
    assert LT.gate(_result(), 1)["checks"]["d"] is True


# ------------------------------------------------------------------ requests
def test_normalize_spec():
    ok = LT.normalize_spec({"template": "stop_atr", "strategy": "AAA", "timeframe": "1h", "k": "2.5", "junk": 1})
    assert ok == {"template": "stop_atr", "strategy": "AAA", "timeframe": "1h", "k": 2.5}
    assert LT.normalize_spec({"template": "lock_start", "timeframe": "4h", "first_lock": 0.2}, strategy="AAA") == \
        {"template": "lock_start", "strategy": "AAA", "timeframe": "4h", "first_lock": 0.2}
    assert LT.normalize_spec({"template": "timeframe_only"}, strategy="AAA") == {"template": "timeframe_only",
                                                                                 "strategy": "AAA"}
    bad = [
        {"template": "rm -rf", "strategy": "AAA", "timeframe": "1h"},
        {"template": "stop_atr", "strategy": "AAA", "timeframe": "1h", "k": 2.0},     # the current rule
        {"template": "stop_atr", "strategy": "AAA", "timeframe": "1h", "k": True},
        {"template": "stop_atr", "strategy": "AAA", "k": 2.5},                        # no timeframe
        {"template": "stop_atr", "strategy": "AAA", "timeframe": "1d", "k": 2.5},
        {"template": "skip_tag", "strategy": "AAA", "timeframe": "1h", "tag": "강제청산"},  # not an entry tag
        {"template": "lock_start", "strategy": "A; DROP", "timeframe": "1h", "first_lock": 0.2},
        "stop_atr",
    ]
    bad += [{"template": ["stop_atr"], "strategy": "AAA", "timeframe": "1h", "k": 2.5},      # unhashable values
            {"template": {"x": 1}, "strategy": "AAA", "timeframe": "1h", "k": 2.5},
            {"template": "stop_atr", "strategy": "AAA", "timeframe": ["1h"], "k": 2.5},
            {"template": "stop_atr", "strategy": "AAA", "timeframe": "1h", "k": 10 ** 400},    # float overflow
            {"template": "skip_tag", "strategy": "AAA", "timeframe": "1h", "tag": ["횡보장 진입"]},
            {"template": "stop_atr", "strategy": ["AAA"], "timeframe": "1h", "k": 2.5}]
    for spec in bad:
        with pytest.raises(LT.SpecError):
            LT.normalize_spec(spec)
    with pytest.raises(LT.SpecError):
        LT.normalize_spec({"template": "stop_atr", "strategy": "BBB", "timeframe": "1h", "k": 2.5}, strategy="AAA")


def test_run_test_never_raises_for_bad_requests_or_missing_data(cache, tmp_path):
    r = LT.run_test({"template": "nope"}, LT.LabData(cache))
    assert r["ok"] is False and r["status"] == "bad_spec" and r["gate"]["pass"] is False
    r = LT.run_test({"template": "stop_atr", "strategy": "AAA", "timeframe": "1h", "k": 2.5}, None)
    assert r["ok"] is False and r["status"] == "no_data" and "자료" in r["error"]
    r = LT.run_test({"template": "stop_atr", "strategy": "AAA", "timeframe": "1h", "k": 2.5}, LT.LabData(str(tmp_path)))
    assert r["status"] == "no_data"
    r = LT.run_test({"template": "stop_atr", "strategy": "ZZZ", "timeframe": "1h", "k": 2.5}, LT.LabData(cache))
    assert r["status"] == "no_data" and "ZZZ" in r["error"]
    r = LT.run_test({"template": "stop_atr", "strategy": "AAA", "timeframe": "1h", "k": 2.5}, LT.LabData(cache),
                    strategy="BBB")
    assert r["status"] == "bad_spec"
    json.dumps(r)


def test_labdata_from_env(cache, monkeypatch):
    monkeypatch.setenv("LAB_DATA_DIR", cache)
    monkeypatch.delenv("LAB_PRE2021_DIR", raising=False)
    d = LT.LabData.from_env()
    assert d is not None and d.coins("main", "1h") == list(COINS2) and d.coins("main", "4h") == []
    assert d.strategies("1h") == list(NAMES)
    monkeypatch.setenv("LAB_DATA_DIR", "/nonexistent/lab")
    assert LT.LabData.from_env() is None


# ------------------------------------------------------------------ labdata (no network)
HEADER = "open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore\n"


def _rows(start_ms, n, step_ms, px=100.0, micro=False):
    out = []
    for k in range(n):
        t = start_ms + k * step_ms
        tt = t * 1000 if micro else t
        out.append(f"{tt},{px + k},{px + k + 1},{px + k - 1},{px + k + 0.5},{10 + k},{t + step_ms - 1},1,1,1,1,0")
    return "\n".join(out) + "\n"


def _zip(name, text):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name, text)
    return buf.getvalue()


def test_parse_kline_csv_with_and_without_header_and_microseconds():
    t0 = int(pd.Timestamp("2024-01-01", tz="UTC").value // 1_000_000)
    a = LD.parse_kline_csv(_rows(t0, 3, 3_600_000))
    b = LD.parse_kline_csv(HEADER + _rows(t0, 3, 3_600_000))
    c = LD.parse_kline_csv(HEADER + _rows(t0, 3, 3_600_000, micro=True))
    for df in (a, b, c):
        assert list(df.columns) == ["ts", "open", "high", "low", "close", "volume"]
        assert len(df) == 3 and df["ts"].iloc[0] == pd.Timestamp("2024-01-01", tz="UTC")
        assert df["ts"].iloc[2] == pd.Timestamp("2024-01-01 02:00", tz="UTC")
        assert df["close"].tolist() == [100.5, 101.5, 102.5] and df["volume"].iloc[1] == 11.0
    z = LD.parse_kline_zip(_zip("BTCUSDT-1h-2024-01.csv", HEADER + _rows(t0, 2, 3_600_000)))
    assert len(z) == 2 and z["high"].iloc[1] == 102.0


def test_urls_and_months():
    assert LD.symbol_of("BTCUSD") == "BTCUSDT"
    assert LD.monthly_url("BTCUSDT", "1h", "2024-01") == \
        "https://data.binance.vision/data/futures/um/monthly/klines/BTCUSDT/1h/BTCUSDT-1h-2024-01.zip"
    assert LD.daily_url("SOLUSDT", "5m", "2026-09-01").endswith("/daily/klines/SOLUSDT/5m/SOLUSDT-5m-2026-09-01.zip")
    assert LD.months_between("2023-11-15", "2024-02-01") == ["2023-11", "2023-12", "2024-01"]
    assert LD.months_between("2023-11-01", "2024-02-02") == ["2023-11", "2023-12", "2024-01", "2024-02"]


def test_load_klines_with_a_fake_archive(tmp_path):
    import hashlib
    sym, tf, step = "BTCUSDT", "1d", 86_400_000
    files = {}
    for month, days in (("2024-01", 31), ("2024-02", 29)):
        t0 = int(pd.Timestamp(month + "-01", tz="UTC").value // 1_000_000)
        blob = _zip(f"{sym}-{tf}-{month}.csv", HEADER + _rows(t0, days, step))
        url = LD.monthly_url(sym, tf, month)
        files[url] = blob
        files[url + ".CHECKSUM"] = f"{hashlib.sha256(blob).hexdigest()}  {sym}-{tf}-{month}.zip\n".encode()
    for day in ("2024-03-01", "2024-03-02"):          # March not published monthly yet
        t0 = int(pd.Timestamp(day, tz="UTC").value // 1_000_000)
        files[LD.daily_url(sym, tf, day)] = _zip(f"{sym}-{tf}-{day}.csv", _rows(t0, 1, step))
    calls = []

    def getter(url):
        calls.append(url)
        return files.get(url)

    df, notes = LD.load_klines(sym, tf, "2023-12-01", "2024-03-10", str(tmp_path / "k"), getter,
                               today=date(2024, 3, 3))
    assert notes["months"] == ["2024-01", "2024-02"] and notes["months_missing"] == ["2023-12"]
    assert notes["days"] == ["2024-03-01", "2024-03-02"]
    assert len(df) == 31 + 29 + 2 and df["ts"].is_monotonic_increasing and df["ts"].is_unique
    assert df["ts"].iloc[-1] == pd.Timestamp("2024-03-02", tz="UTC")
    # second load reads the download cache only
    calls.clear()
    df2, _ = LD.load_klines(sym, tf, "2024-01-01", "2024-03-01", str(tmp_path / "k"), getter, today=date(2024, 3, 3))
    assert len(df2) == 60 and calls == []
    # a corrupted download is refused
    bad = dict(files)
    bad[LD.monthly_url(sym, tf, "2024-01")] = files[LD.monthly_url(sym, tf, "2024-02")]
    with pytest.raises(RuntimeError, match="checksum"):
        LD.load_klines(sym, tf, "2024-01-01", "2024-02-01", None, bad.get, today=date(2024, 3, 3))


def test_build_one_writes_a_cache_the_lab_can_read(tmp_path):
    L = sweepsig.lib()
    df = L.synth_ohlcv(900, "4h", seed=5, start="2024-01-01")
    ms = (df["ts"].astype("int64") // 1_000_000).to_numpy()
    text = HEADER + "".join(f"{t},{o},{h},{lo},{c},{v},{t + 14_400_000 - 1},1,1,1,1,0\n" for t, o, h, lo, c, v in
                            zip(ms, df["open"], df["high"], df["low"], df["close"], df["volume"]))
    by_month = {}
    for line in text.splitlines()[1:]:
        m = pd.Timestamp(int(line.split(",")[0]), unit="ms").strftime("%Y-%m")
        by_month.setdefault(m, []).append(line)
    files = {LD.monthly_url("ETHUSDT", "4h", m): _zip("x.csv", "\n".join(rows) + "\n") for m, rows in by_month.items()}
    row = LD.build_one("4h", "ETHUSD", str(tmp_path), "2024-01-01", "2024-06-30", None, files.get, verify=False)
    assert row["bars"] == int((df["ts"] < pd.Timestamp("2024-06-30", tz="UTC")).sum()) and "error" not in row
    with np.load(tmp_path / "sig_4h_ETHUSD.npz") as z:
        keys = set(z.files)
        assert {"ts", "o", "h", "l", "c", "atr", "s__DOGE"} <= keys and "s__DOGE_L" not in keys
        assert z["ts"].dtype == np.int64 and z["s__DOGE"].dtype == np.int8
        assert len([k for k in keys if k.startswith("s__")]) == 36
    d = LT.LabData(str(tmp_path))
    assert d.coins("main", "4h") == ["ETHUSD"] and len(d.strategies("4h")) == 36

"""New-strategy lab (paperbot/agents/newlab.py, newlab_signals.py; docs/newlab-prereg.md).

Synthetic caches only (written into tmp dirs, same npz format as the lab caches); no network.
"""

import hashlib
import importlib.util
import os

import numpy as np
import pandas as pd
import pytest

from paperbot import sweepsig
from paperbot.agents import labtests as LT
from paperbot.agents import newlab as NL
from paperbot.agents import newlab_signals as NS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COINS3 = ("BTCUSD", "ETHUSD", "SOLUSD")


def _lib_module():
    name = "_newlab_test_library_lib"
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "research", "library", "lib.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _spec(fam="ema_cross", params=None, filters=None, direction="both", tf="1h"):
    if params is None:
        names, grid = NS.FAMILIES[fam][0], NS.FAMILIES[fam][1]
        params = dict(zip(names, grid[0]))
    return NL.normalize_spec({"timeframe": tf, "entry": {"family": fam, "params": params},
                              "filters": filters or [], "direction": direction})


# ------------------------------------------------------------------ prereg
def test_prereg_hash_matches():
    with open(os.path.join(ROOT, "docs", "newlab-prereg.sha256")) as fh:
        want, rel = fh.read().split()
    with open(os.path.join(ROOT, rel), "rb") as fh:
        assert hashlib.sha256(fh.read()).hexdigest() == want


# ------------------------------------------------------------------ grammar
def test_spec_canonical_form_and_hash():
    a = NL.normalize_spec({"timeframe": "1H", "entry": {"family": "SuperTrend_Flip", "params": {"length": 10, "mult": 3}},
                           "filters": [{"kind": "session", "window": "Europe"}, {"kind": "trend_ema", "length": 200.0}],
                           "direction": "Both", "name": "my idea", "idea": "trend after London open"})
    b = NL.normalize_spec({"timeframe": "1h", "entry": {"family": "supertrend_flip", "params": {"mult": 3.0, "length": 10}},
                           "filters": [{"kind": "trend_ema", "length": 200}, {"kind": "session", "window": "europe"}]})
    assert a == b
    assert a["direction"] == "both" and a["v"] == NL.GRAMMAR_VERSION
    assert [f["kind"] for f in a["filters"]] == ["session", "trend_ema"]
    assert a["entry"]["params"] == {"length": 10, "mult": 3.0}
    assert NL.spec_hash(a) == NL.spec_hash(b)
    assert NL.spec_hash({"timeframe": "1h", "entry": {"family": "supertrend_flip", "params": {"mult": 3, "length": 10}},
                         "filters": [{"kind": "session", "window": "europe"}, {"kind": "trend_ema", "length": 200}],
                         "direction": "both"}) == NL.spec_hash(a)
    c = dict(b, direction="long")
    assert NL.spec_hash(c) != NL.spec_hash(b)
    assert NL.spec_hash(_spec("supertrend_flip", {"length": 10, "mult": 2})) != NL.spec_hash(
        _spec("supertrend_flip", {"length": 10, "mult": 3}))
    assert NL.spec_notes({"name": "my idea", "idea": "x"}) == {"name": "my idea", "idea": "x"}
    assert "supertrend_flip" in NL.describe_ko(a) and "유럽" in NL.describe_ko(a)
    # JSON text is accepted; no-parameter families need no params
    assert NL.normalize_spec('{"timeframe": "4h", "entry": {"family": "psar_flip"}}')["entry"] == \
        {"family": "psar_flip", "params": {}}


@pytest.mark.parametrize("bad, words", [
    ("not json", "JSON"),
    ([1, 2], "JSON"),
    ({"timeframe": "2h", "entry": {"family": "psar_flip"}}, "timeframe"),
    ({"timeframe": "1h", "entry": {"family": "magic"}}, "없는 진입"),
    ({"timeframe": "1h", "entry": {"family": "ema_cross", "params": {"fast": 9, "slow": 50}}}, "조합"),
    ({"timeframe": "1h", "entry": {"family": "ema_cross", "params": {"fast": 9}}}, "모두"),
    ({"timeframe": "1h", "entry": {"family": "ema_cross", "params": {"fast": "9", "slow": 21}}}, "조합"),
    ({"timeframe": "1h", "entry": {"family": "ema_cross", "params": {"fast": True, "slow": 21}}}, "조합"),
    ({"timeframe": "1h", "entry": {"family": "psar_flip", "params": {"step": 0.02}}}, "값이 없"),
    ({"timeframe": "1h", "entry": {"family": "psar_flip"}, "stop_atr": 3}, "paper v3"),
    ({"timeframe": "1h", "entry": {"family": "psar_flip"}, "Leverage": 10}, "paper v3"),
    ({"timeframe": "1h", "entry": {"family": "psar_flip"}, "whatever": 1}, "모르는 칸"),
    ({"timeframe": "1h", "entry": {"family": "psar_flip"}, "direction": "up"}, "direction"),
    ({"timeframe": "1h", "entry": {"family": "psar_flip"},
      "filters": [{"kind": "adx", "mode": "above", "level": 20}, {"kind": "session", "window": "us"},
                  {"kind": "trend_ema", "length": 50}]}, "0~2"),
    ({"timeframe": "1h", "entry": {"family": "psar_flip"},
      "filters": [{"kind": "trend_ema", "length": 50}, {"kind": "trend_ema", "length": 200}]}, "두 번"),
    ({"timeframe": "1h", "entry": {"family": "psar_flip"}, "filters": [{"kind": "trend_ema", "length": 150}]}, "length"),
    ({"timeframe": "1h", "entry": {"family": "psar_flip"}, "filters": [{"kind": "adx", "level": 25}]}, "mode"),
    ({"timeframe": "1h", "entry": {"family": "psar_flip"}, "filters": [{"kind": "moon"}]}, "없는 필터"),
])
def test_spec_rejections(bad, words):
    with pytest.raises(NL.SpecError) as ei:
        NL.normalize_spec(bad)
    assert words in str(ei.value)


def test_grammar_size_and_help():
    assert sum(len(g[1]) for g in NS.FAMILIES.values()) == 40         # the library's 40 entries
    assert len(NS.FAMILIES) == 30
    txt = NL.grammar_help_ko()
    for fam in NS.FAMILIES:
        assert fam in txt
    for kind in NS.FILTERS:
        assert kind in txt
    # every grid value normalises to itself
    for fam, (names, grid, *_r) in NS.FAMILIES.items():
        for g in grid:
            assert _spec(fam, dict(zip(names, g)))["entry"]["params"] == dict(zip(names, g))


# ------------------------------------------------------------------ same signals as the library
LIB_NAMES = {
    ("ema_cross", (9, 21)): "T1_EMA9_21", ("ema_cross", (20, 50)): "T1_EMA20_50", ("ema_cross", (50, 200)): "T1_EMA50_200",
    ("sma_cross", (10, 30)): "T2_SMA10_30", ("sma_cross", (50, 200)): "T2_SMA50_200",
    ("macd_cross", (12, 26, 9)): "T3_MACD12_26_9", ("macd_cross", (8, 21, 5)): "T3_MACD8_21_5",
    ("macd_hist_zero", ()): "T4_MACDHIST0", ("supertrend_flip", (10, 2.0)): "T5_ST10_2",
    ("supertrend_flip", (10, 3.0)): "T5_ST10_3", ("supertrend_flip", (14, 4.0)): "T5_ST14_4",
    ("donchian_break", (20,)): "T6_DON20", ("donchian_break", (55,)): "T6_DON55", ("keltner_break", ()): "T7_KELT20_2",
    ("psar_flip", ()): "T8_PSAR", ("dmi_cross", ()): "T9_DMI14_ADX25", ("ichimoku_tk", ()): "T10_ICHI_TK",
    ("aroon_cross", ()): "T11_AROON25", ("hma_turn", (21,)): "T12_HMA21", ("hma_turn", (55,)): "T12_HMA55",
    ("rsi_reversal", (14, 30, 70)): "O1_RSI14_REV30", ("rsi_reversal", (7, 20, 80)): "O1_RSI7_REV20",
    ("rsi_cross50", ()): "O2_RSI14_X50", ("stoch_zone", ()): "O3_STOCH_ZONE", ("stochrsi_zone", ()): "O4_STOCHRSI_ZONE",
    ("cci_extreme", ()): "O5_CCI20", ("williams_r", ()): "O6_WR14", ("mfi_reversal", ()): "O7_MFI14",
    ("roc_zero", (9,)): "O8_ROC9", ("roc_zero", (21,)): "O8_ROC21", ("cmo_zero", ()): "O9_CMO14",
    ("bb_break", ()): "V1_BB_BREAK", ("bb_revert", ()): "V2_BB_REVERT", ("squeeze_break", ()): "V3_SQUEEZE",
    ("obv_cross", ()): "VO1_OBV_X_MA20", ("volume_spike", ()): "VO2_VOL_SPIKE", ("engulfing", ()): "C1_ENGULF",
    ("hammer_star", ()): "C2_HAMMER_STAR", ("inside_break", ()): "C3_INSIDE_BREAK", ("three_same", ()): "C4_THREE_SAME",
}


@pytest.fixture(scope="module")
def synth_df():
    L = sweepsig.lib()
    return L.synth_ohlcv(3000, "1h", seed=7, gaps=15)


def test_triggers_equal_library_entries(synth_df):
    L = sweepsig.lib()
    LB = _lib_module()
    E = LB.entries(synth_df, L.fg, L.pi)
    assert len(LIB_NAMES) == 40 and set(LIB_NAMES.values()) == {k for k in E if not k.endswith("+F200")}
    t_ns = synth_df["ts"].dt.tz_localize(None).to_numpy().astype("datetime64[ns]").astype(np.int64)
    for (fam, g), name in LIB_NAMES.items():
        names = NS.FAMILIES[fam][0]
        lg, sh = NS.trigger(fam, dict(zip(names, g)), synth_df)
        np.testing.assert_array_equal(lg, E[name][0], err_msg=name)
        np.testing.assert_array_equal(sh, E[name][1], err_msg=name)
        assert (lg | sh).any(), name
        # the library's "+F200" variant is trend_ema 200, both directions
        sp = _spec(fam, dict(zip(names, g)), [{"kind": "trend_ema", "length": 200}])
        sg = NS.signals(sp, t_ns, *(synth_df[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume")))
        np.testing.assert_array_equal(sg == 1, E[name + "+F200"][0], err_msg=name)
        np.testing.assert_array_equal(sg == -1, E[name + "+F200"][1], err_msg=name)


def test_fast_indicators_equal_vendor(synth_df):
    L = sweepsig.lib()
    fg, pi = L.fg, L.pi
    LB = _lib_module()
    df = synth_df
    h, lo, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    _sar, d = fg.parabolic_sar(df.iloc[:1500].reset_index(drop=True))
    np.testing.assert_array_equal(NS.psar_direction(h[:1500], lo[:1500], c[:1500]), d.to_numpy(float))
    np.testing.assert_allclose(NS.cci(df, 20), fg.cci(df, 20).to_numpy(float), rtol=1e-10, atol=1e-9)
    au, ad = fg.aroon(df, 25)
    a2, d2 = NS.aroon(h, lo, 25)
    np.testing.assert_array_equal(a2, au.to_numpy(float))
    np.testing.assert_array_equal(d2, ad.to_numpy(float))
    for n, m in ((10, 2.0), (14, 4.0)):
        np.testing.assert_array_equal(NS.supertrend_direction(h, lo, c, n, m), pi.exchange_supertrend(h, lo, c, n, m)[1])
    for n in (9, 21, 200):
        np.testing.assert_array_equal(NS.pine_ema(c, n), pi.pine_ema(c, n))
        np.testing.assert_array_equal(NS.pine_rma(c, n), pi.pine_rma(c, n))
    for n in (7, 14):
        np.testing.assert_array_equal(NS.pine_rsi(c, n), pi.pine_rsi(c, n))
    for a, b in zip(NS.pine_macd(c, 12, 26, 9), pi.pine_macd(c, 12, 26, 9)):
        np.testing.assert_array_equal(a, b)
    for a, b in zip(NS.stoch_rsi_kd(c, 14, 14, 3, 3), pi.stoch_rsi_kd(c, 14, 14, 3, 3)):
        np.testing.assert_array_equal(a, b)
    for n in (21, 55):
        np.testing.assert_allclose(NS.hma(c, n), LB._hma(df["close"], n).to_numpy(float), rtol=1e-12, atol=1e-10)
    # a missing value after the seed falls back to the vendor loop (its carry-forward)
    x = c.copy()
    x[500] = np.nan
    np.testing.assert_array_equal(NS.pine_ema(x, 20), pi.pine_ema(x, 20))


# ------------------------------------------------------------------ causality
ALL_FILTERS = [{"kind": "trend_ema", "length": 50}, {"kind": "adx", "mode": "above", "level": 20},
               {"kind": "adx", "mode": "below", "level": 25}, {"kind": "htf_trend", "length": 20},
               {"kind": "vol_regime", "mode": "high", "lookback": 100}, {"kind": "vol_regime", "mode": "low", "lookback": 100},
               {"kind": "session", "window": "asia"}]


def _arrays(df):
    t = df["ts"].dt.tz_localize(None).to_numpy().astype("datetime64[ns]").astype(np.int64)
    return (t,) + tuple(df[k].to_numpy(float).copy() for k in ("open", "high", "low", "close", "volume"))


@pytest.mark.parametrize("tf", ["1h", "4h"])
def test_changing_future_bars_never_changes_past_signals(tf):
    L = sweepsig.lib()
    df = L.synth_ohlcv(2400, tf, seed=11)
    t, o, h, lo, c, v = _arrays(df)
    m = 1700
    rng = np.random.default_rng(3)
    # a different future: new random path after bar m (prices, ranges and volume)
    k = np.exp(np.cumsum(rng.normal(0, 0.02, len(c) - m)))
    o2, h2, lo2, c2, v2 = o.copy(), h.copy(), lo.copy(), c.copy(), v.copy()
    for a in (o2, h2, lo2, c2):
        a[m:] = a[m:] * k * (1 + rng.uniform(-0.01, 0.01, len(c) - m))
    h2[m:] = np.maximum.reduce([h2[m:], o2[m:], c2[m:]]) * 1.003
    lo2[m:] = np.minimum.reduce([lo2[m:], o2[m:], c2[m:]]) * 0.997
    v2[m:] = v2[m:] * rng.lognormal(0, 1, len(c) - m)
    atr1 = L.fg.atr(NS.frame(o, h, lo, c, v), 14).to_numpy(float)
    atr2 = L.fg.atr(NS.frame(o2, h2, lo2, c2, v2), 14).to_numpy(float)
    np.testing.assert_array_equal(atr1[:m], atr2[:m])
    specs = [_spec(fam, dict(zip(names, g)), tf=tf) for fam, (names, grid, *_r) in NS.FAMILIES.items() for g in grid]
    specs += [_spec("ema_cross", {"fast": 9, "slow": 21}, [f], tf=tf) for f in ALL_FILTERS]
    specs += [_spec("bb_revert", None, [{"kind": "htf_trend", "length": 50}, {"kind": "vol_regime", "mode": "low",
                                                                               "lookback": 500}], "long", tf=tf)]
    fired = 0
    for sp in specs:
        a = NS.signals(sp, t, o, h, lo, c, v, atr1)
        b = NS.signals(sp, t, o2, h2, lo2, c2, v2, atr2)
        cut = NS.signals(sp, t[:m], o[:m], h[:m], lo[:m], c[:m], v[:m], atr1[:m])
        np.testing.assert_array_equal(a[:m], b[:m], err_msg=str(sp))
        np.testing.assert_array_equal(a[:m], cut, err_msg=str(sp))
        fired += int((a[:m] != 0).any())
    assert fired >= len(specs) - 2          # the check is not vacuous


def test_htf_filter_uses_only_closed_higher_bars():
    """1h bars, 4h trend: a bar sees the 4h bar that closed at or before its close, never the open one."""
    L = sweepsig.lib()
    df = L.synth_ohlcv(400, "1h", seed=2, start="2024-01-01")
    t = _arrays(df)[0]
    vals = NS.htf_values(t, NS.frame(*(df[k] for k in ("open", "high", "low", "close", "volume"))), "1h", "4h",
                         lambda d: d["close"].to_numpy(float))
    c = df["close"].to_numpy(float)
    hour = pd.to_datetime(t).hour
    for i in range(8, 40):
        # the 4h bar closing at the end of hour 3, 7, 11 ... is visible from that hour's bar on
        last_closed_end = i if hour[i] % 4 == 3 else i - (hour[i] % 4) - 1
        assert vals[i] == c[last_closed_end], i


def test_signals_for_frame_matches_cache_path(synth_df):
    sp = _spec("rsi_reversal", {"length": 14, "low": 30, "high": 70}, [{"kind": "session", "window": "us"}])
    t, o, h, lo, c, v = _arrays(synth_df)
    np.testing.assert_array_equal(NS.signals_for_frame(sp, synth_df), NS.signals(sp, t, o, h, lo, c, v))
    long_only = NL.normalize_spec(dict(sp, direction="long"))
    s = NS.signals_for_frame(long_only, synth_df)
    assert (s >= 0).all() and (s > 0).any()


# ------------------------------------------------------------------ synthetic lab caches
SIG = 0.006                        # per-4h-bar volatility: ATR ~0.7% of price, so trades get 20-50x


def _bars(start, end, seed, events=False, drift=0.0):
    rng = np.random.default_rng(seed)
    ts = pd.date_range(pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC"), freq="4h")
    n = len(ts)
    r = rng.normal(drift * SIG, SIG, n)
    v = rng.lognormal(0, 0.7, n)           # heavy enough that 3x volume spikes also happen by chance
    if events:                     # planted edge: a 10x volume up-candle, then a 6-bar rise
        e = 60
        while e < n - 10:
            r[e] = abs(r[e]) + 0.5 * SIG
            v[e] *= 10
            r[e + 1:e + 7] += 1.5 * SIG
            e += int(rng.integers(25, 45))
    c = 100 * np.exp(np.cumsum(r))
    o = np.r_[100.0, c[:-1]]
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.3 * SIG, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.3 * SIG, n)))
    df = pd.DataFrame({"open": o, "high": h, "low": lo, "close": c, "volume": v})
    atr = sweepsig.lib().fg.atr(df, 14).to_numpy(float)
    return dict(ts=ts.tz_localize(None).to_numpy().astype("datetime64[ns]").astype(np.int64), o=o, h=h, l=lo, c=c,
                v=v, atr=atr)


def _write(root, coins=COINS3, pre=True, **kw):
    for k, coin in enumerate(coins):
        np.savez_compressed(os.path.join(root, f"sig_4h_{coin}.npz"),
                            **_bars("2021-01-01", "2026-09-30 20:00", 100 + k, **kw))
        if pre:
            d = os.path.join(root, "pre2021")
            os.makedirs(d, exist_ok=True)
            np.savez_compressed(os.path.join(d, f"sig_4h_{coin}.npz"),
                                **_bars("2020-01-01", "2021-08-31 20:00", 200 + k, **kw))
    return root


@pytest.fixture(scope="module")
def planted(tmp_path_factory):
    root = _write(str(tmp_path_factory.mktemp("nl_planted")), events=True)
    data = LT.LabData(root)
    return NL.run_new_strategy({"timeframe": "4h", "entry": {"family": "volume_spike"}, "direction": "long"}, data, 0)


@pytest.fixture(scope="module")
def noise_dir(tmp_path_factory):
    return _write(str(tmp_path_factory.mktemp("nl_noise")))


def test_planted_edge_passes(planted):
    r = planted
    assert r["ok"] and r["status"] == "done" and NL.counts_as_test(r), r.get("error")
    P = r["periods"]
    assert P["1"]["trades"] >= 300 and P["2"]["trades"] >= 100 and P["3"]["trades"] >= 30
    assert P["1"]["mean_roe"] > 0.05 and P["1"]["p"] == pytest.approx(NL.P_FLOOR_P1)
    assert P["1"]["coinflip"]["trades"] >= 5 * P["1"]["trades"]
    assert P["1"]["coinflip"]["diff"] > 0 and P["1"]["coinflip"]["p"] < 0.05
    g = r["gate"]
    assert g["pass"], g["reasons"]
    assert all(g["checks"].values())
    assert "통과" in r["summary_ko"] and "#1" in r["summary_ko"]
    prop = NL.proposal_of(r)
    assert prop and prop["needs_owner_ok"] and prop["kind"] == "new_paper_account"
    assert prop["spec"] == r["spec"] and "OK" in prop["summary_ko"]
    row = NL.ledger_row(r)
    assert row["pass"] and row["counts_as_test"] and row["spec_hash"] == NL.spec_hash(r["spec"])
    assert row["periods"]["1"]["trades"] == P["1"]["trades"]


def test_noise_fails(noise_dir):
    data = LT.LabData(noise_dir)
    for spec in ({"timeframe": "4h", "entry": {"family": "volume_spike"}, "direction": "long"},
                 {"timeframe": "4h", "entry": {"family": "ema_cross", "params": {"fast": 9, "slow": 21}}},
                 {"timeframe": "4h", "entry": {"family": "rsi_reversal", "params": {"length": 7, "low": 20, "high": 80}},
                  "filters": [{"kind": "adx", "mode": "below", "level": 20}]}):
        r = NL.run_new_strategy(spec, data, 0)
        assert r["ok"], r.get("error")
        assert r["periods"]["1"]["trades"] >= 20, r["summary_ko"]        # the check is not vacuous
        assert not r["gate"]["pass"], r["summary_ko"]
        assert NL.proposal_of(r) is None


def test_run_is_deterministic(noise_dir):
    data = LT.LabData(noise_dir)
    s = {"timeframe": "4h", "entry": {"family": "bb_revert"}, "direction": "both"}
    a, b = NL.run_new_strategy(s, data, 3), NL.run_new_strategy(s, LT.LabData(noise_dir), 3)
    for pid in ("1", "2", "3"):
        for k in ("trades", "mean_roe", "p"):
            assert a["periods"][pid][k] == b["periods"][pid][k]
        assert a["periods"][pid]["coinflip"] == b["periods"][pid]["coinflip"]


def test_global_count_tightens_the_gate(planted):
    mp = NL.max_passable_n()
    assert mp == 4999 and NL.ALPHA / (mp + 1) > NL.P_FLOOR_P1 >= NL.ALPHA / (mp + 2)
    assert NL.gate(planted, 0)["pass"] and NL.gate(planted, mp)["pass"]
    late = NL.gate(planted, mp + 1)
    assert not late["pass"] and not late["checks"]["a"] and not late["can_pass_at_this_n"]
    assert "어떤 새 시험도 통과할 수 없습니다" in late["reasons"][0]
    assert NL.proposal_of(planted, n_tests_now=mp + 1) is None
    # a p of 0.001 passes while 0.05 / (n + 1) > 0.001, i.e. up to n = 48
    fake = _fake_result(p1=0.001)
    assert NL.gate(fake, 0)["pass"] and NL.gate(fake, 48)["pass"]
    assert not NL.gate(fake, 49)["pass"] and NL.gate(fake, 49)["alpha_period1"] == pytest.approx(0.001)
    assert [NL.gate(fake, n)["pass"] for n in (0, 10, 48, 49, 1000)] == [True, True, True, False, False]


def _fake_result(p1=0.0001, **over):
    def per(trades, mean, p, pnl, cf_diff=0.05, cf_p=0.001, coins_pos=4, coins_n=6, available=True):
        return {"available": available, "trades": trades, "mean_roe": mean, "p": p, "mean_pnl_equity": pnl,
                "coins_pos": coins_pos, "coins_n": coins_n, "coinflip": {"diff": cf_diff, "p": cf_p, "mean_roe": -0.05}}
    P = {"1": per(500, 0.05, p1, 0.01), "2": per(200, 0.04, 0.01, 0.008), "3": per(80, 0.02, 0.2, 0.004)}
    for k, v in over.items():
        pid, key = k.split("_", 1)
        if key == "available" and not v:
            P[pid] = {"available": False}
        elif key.startswith("cf_"):
            P[pid]["coinflip"][key[3:]] = v
        else:
            P[pid][key] = v
    return {"ok": True, "status": "done", "periods": P}


@pytest.mark.parametrize("over, check", [
    ({}, None),
    ({"1_mean_roe": -0.01}, "a"),
    ({"1_trades": 299}, "b"),
    ({"1_coins_pos": 3}, "b"),                     # 3 of 6 is not a majority
    ({"2_mean_roe": -0.001}, "c"),
    ({"2_p": 0.05}, "c"),
    ({"2_trades": 99}, "c"),
    ({"3_mean_roe": -0.001}, "d"),
    ({"3_trades": 29}, "d"),
    ({"1_mean_pnl_equity": -0.0001}, "e"),
    ({"2_mean_pnl_equity": None}, "e"),
    ({"1_cf_diff": -0.01}, "f"),
    ({"2_cf_p": 0.06}, "f"),
])
def test_gate_thresholds(over, check):
    g = NL.gate(_fake_result(**over), 0)
    if check is None:
        assert g["pass"] and len(g["reasons"]) == 6
    else:
        assert not g["pass"] and not g["checks"][check]
        assert all(v for k, v in g["checks"].items() if k != check)


def test_period3_without_data_is_skipped_not_failed():
    g = NL.gate(_fake_result(**{"3_available": False}), 0)
    assert g["pass"] and g["checks"]["d"] and "자료가 없어" in g["reasons"][3]


def test_no_pre2021_cache(tmp_path):
    root = _write(str(tmp_path), coins=("BTCUSD", "ETHUSD"), pre=False, events=True)
    r = NL.run_new_strategy({"timeframe": "4h", "entry": {"family": "volume_spike"}, "direction": "long"},
                            LT.LabData(root), 0)
    assert r["ok"] and r["periods"]["3"]["available"] is False
    assert r["gate"]["checks"]["d"] and "자료가 없어" in r["gate"]["reasons"][3]


def test_coinflip_draws_match_count_sides_and_bars():
    rng = np.random.default_rng(0)
    n = 3000
    b = {"ts": np.arange(n, dtype=np.int64), "o": np.full(n, 100.0), "atr": np.r_[np.full(50, np.nan), np.ones(n - 50)]}
    sg = np.zeros(n, np.int8)
    sg[rng.choice(np.arange(100, 2900), 120, replace=False)] = 1
    sg[rng.choice(np.nonzero(sg == 0)[0][100:], 40, replace=False)] = -1
    bounds = [(0, 1500), (1500, 3000)]
    for k in range(3):
        r = NL._coinflip_signals(np.random.default_rng(k), b, sg, 60, n, bounds)
        for s0, s1 in bounds:
            seg_s, seg_r = sg[max(s0, 60):min(s1, n - 1)], r[s0:s1]
            assert (seg_r == 1).sum() == (seg_s == 1).sum() and (seg_r == -1).sum() == (seg_s == -1).sum()
        assert not r[:60].any() and r[n - 1] == 0
    a = NL._coinflip_signals(np.random.default_rng(5), b, sg, 60, n, bounds)
    np.testing.assert_array_equal(a, NL._coinflip_signals(np.random.default_rng(5), b, sg, 60, n, bounds))
    assert not np.array_equal(a, sg)


def test_coinflip_catches_a_drift_only_strategy(tmp_path):
    """Strong steady up-drift: random long entries make money too. A long-only rule with no timing
    skill looks profitable but must not beat its own coin flip, so the gate fails on check (f)."""
    root = _write(str(tmp_path), drift=0.35)
    r = NL.run_new_strategy({"timeframe": "4h", "entry": {"family": "three_same"}, "direction": "long"},
                            LT.LabData(root), 0)
    P = r["periods"]
    assert P["1"]["mean_roe"] > 0 and P["2"]["mean_roe"] > 0
    assert P["1"]["coinflip"]["mean_roe"] > 0
    assert not r["gate"]["checks"]["f"] and not r["gate"]["pass"]


def test_bad_duplicate_and_missing_data_are_not_counted(noise_dir, tmp_path):
    data = LT.LabData(noise_dir)
    bad = NL.run_new_strategy({"timeframe": "4h", "entry": {"family": "psar_flip"}, "exit": "tp2"}, data, 7)
    assert bad["status"] == "bad_spec" and not NL.counts_as_test(bad) and not bad["gate"]["pass"]
    s = {"timeframe": "4h", "entry": {"family": "psar_flip"}}
    dup = NL.run_new_strategy(s, data, 7, tested_hashes={NL.spec_hash(s)})
    assert dup["status"] == "duplicate" and not NL.counts_as_test(dup) and dup["spec_hash"] == NL.spec_hash(s)
    none = NL.run_new_strategy(s, None, 7)
    assert none["status"] == "no_data" and not NL.counts_as_test(none)
    other_tf = NL.run_new_strategy(dict(s, timeframe="1h"), data, 7)
    assert other_tf["status"] == "no_data"
    # volume families need the cache's volume column
    nov = str(tmp_path)
    for coin in ("BTCUSD", "ETHUSD"):
        x = _bars("2021-01-01", "2023-01-01", 1)
        x.pop("v")
        np.savez_compressed(os.path.join(nov, f"sig_4h_{coin}.npz"), **x)
    r = NL.run_new_strategy({"timeframe": "4h", "entry": {"family": "obv_cross"}}, LT.LabData(nov), 0)
    assert r["status"] == "no_data" and "거래량" in r["error"]
    ok = NL.run_new_strategy(s, data, 7)
    assert ok["status"] == "done" and NL.counts_as_test(ok) and ok["test_number"] == 8
    assert "#8" in ok["summary_ko"]


def test_outcomes_are_the_lab_machinery(noise_dir):
    """The strategy arm equals labtests.signal_outcomes on the same signals (no second exit engine)."""
    data = LT.LabData(noise_dir)
    sp = _spec("bb_break", None, tf="4h")
    L = sweepsig.lib()
    total = 0
    for coin in COINS3:
        b = data.bars("main", "4h", coin)
        sg = NL.strategy_signals(sp, data, "main", coin)
        lo, n_end = LT._source_range(L, b["ts"], "4h", [p for p in LT.PERIODS if p[3] == "main"])
        o = LT.signal_outcomes(b, sg, lo, n_end, "4h")
        p1 = o["done"] & (b["ts"][o["idx"]] < pd.Timestamp("2024-07-01").value)
        total += int(p1.sum())
    r = NL.run_new_strategy(sp, data, 0)
    assert r["periods"]["1"]["trades"] == total

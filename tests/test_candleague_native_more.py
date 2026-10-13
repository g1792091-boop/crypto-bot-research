"""The owner-exit league's own structure for the 11 strategies the study's native-exit code does not cover (owners 2026-10-13):
candleague/native_more.py (N02_ST_KST, N04_ST_KLINGER, N07_ICHI_CMO, N12_ICHI_AO, N21_ST_RSI_ADX, N23_HA_ST) and
candleague/native_more_ds.py (F15_LON_BRK, F15_ORB, F3_BOS, F4_FAN, F6_VWAP_FAIL).

  * the arrays have the shape and the tri-state rules of research/exitflex/native.py (float64, 1 / 0 / NaN, all-NaN levels and targets),
  * hand-made bar worlds where a long's structure breaks and where it does not (shorts are the mirror),
  * nothing at bar i depends on a bar after i (the arrays on the bars up to i equal the arrays of the whole series, cut at several i),
  * the provider routes these 11 to the new files and the study's 16 to the study's files,
  * a league restarted in pieces gives the trades of one run (two of the strategies),
  * the account counts (49 picks: -fq -nv -tg and their twins and filters for every one) and the hash that restarts the league.
"""

from __future__ import annotations

import json
import os
import shutil
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import test_candleague_rulex as TR  # noqa: E402  (the league on synthetic bars)
from candleague import candidates as C  # noqa: E402
from candleague import league as L  # noqa: E402
from candleague import native_more as NM  # noqa: E402
from candleague import native_more_ds as ND  # noqa: E402
from candleague import rulex as RX  # noqa: E402
from candleague import runner as RN  # noqa: E402

CORE = ("N02_ST_KST", "N04_ST_KLINGER", "N07_ICHI_CMO", "N12_ICHI_AO", "N21_ST_RSI_ADX", "N23_HA_ST")
DS = ("F15_LON_BRK", "F15_ORB", "F3_BOS", "F4_FAN", "F6_VWAP_FAIL")
ALL = CORE + DS


# ---------------------------------------------------------------- bars
def world(closes, tf_min=15, start="2024-03-12", vol=100.0) -> pd.DataFrame:
    """Chart bars from closes: open = the previous close, wicks of different size (no ties between neighbouring bars)."""
    c = np.asarray(closes, float)
    n = len(c)
    o = np.r_[c[0], c[:-1]]
    r = np.random.default_rng(5)
    up_w, dn_w = r.uniform(3e-4, 9e-4, 20_000)[:n], r.uniform(3e-4, 9e-4, 20_000)[:n]          # the wicks of bar i do not depend on how many bars there are
    return pd.DataFrame({"ts": pd.date_range(start, periods=n, freq=f"{tf_min}min", tz="UTC"), "open": o,
                         "high": np.maximum(o, c) * (1 + up_w), "low": np.minimum(o, c) * (1 - dn_w),
                         "close": c, "volume": np.full(n, vol)})


def walk(n=1400, seed=3, tf_min=15) -> pd.DataFrame:
    r = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(r.normal(0, 0.004, n) + 0.0004 * np.sin(np.arange(n) / 150)))
    df = world(c, tf_min)
    df["volume"] = r.uniform(50, 150, n)
    return df


I = np.arange(300)
UP = 100 * np.exp(0.002 * I + 2e-5 * I ** 2)                                  # accelerating rise: every trend indicator says long
CRASH = np.r_[UP, UP[-1] * np.exp(-0.02 * np.arange(1, 41))]                   # ... and then 40 bars of -2%


def native(name, df, tf="15m", combo=None):
    if name in CORE:
        return NM.native_arrays(name, df, tf, combo)
    return ND.native_arrays(df, tf, name, combo or {}, None, "BTCUSD")


def comps(r, side):
    return [a for _k, a in r["comp_" + side]]


def tri_eq(a, b) -> bool:
    return np.array_equal(np.asarray(a, float), np.asarray(b, float), equal_nan=True)


# ---------------------------------------------------------------- the tables
def test_the_tables_name_the_eleven_and_the_covers_hold_all_27():
    assert NM.NAMES == CORE and ND.NAMES == DS
    assert RX.NATIVE_MORE == {"core": CORE, "ds": DS}
    assert set(RX.NATIVE_COVERS["core"]) == set(RX.NATIVE_STUDY["core"]) | set(CORE) and set(RX.NATIVE_COVERS["ds"]) == set(RX.NATIVE_STUDY["ds"]) | set(DS)
    assert len(RX.NATIVE_COVERS["core"]) + len(RX.NATIVE_COVERS["ds"]) == 27 == len(set(RX.NATIVE_COVERS["core"]) | set(RX.NATIVE_COVERS["ds"]))
    assert not set(RX.NATIVE_MORE["core"]) & set(RX.NATIVE_STUDY["core"]) and not set(RX.NATIVE_MORE["ds"]) & set(RX.NATIVE_STUDY["ds"])
    assert RX.NATIVE_MORE_FILES == ("native_more.py", "native_more_ds.py")
    assert not RX.native_levels_supported({"kind": "core", "name": "N02_ST_KST"}) and not RX.native_levels_supported({"kind": "ds", "name": "F3_BOS"})
    for n in CORE:
        assert RX.native_supported({"kind": "core", "name": n})
    for n in DS:
        assert RX.native_supported({"kind": "ds", "name": n})


# ---------------------------------------------------------------- shape and tri-state rules
@pytest.mark.parametrize("name", ALL)
def test_the_arrays_have_the_shape_and_the_tri_state_rules_of_the_study_code(name):
    df = walk()
    n = len(df)
    r = native(name, df)
    spec = (NM.SPEC if name in CORE else ND.SPEC)[name]
    assert set(r) == {"comp_long", "comp_short", "lvl_long", "lvl_short", "tgt_long", "tgt_short", "names_long", "names_short"}
    for side in ("long", "short"):
        assert tuple(k for k, _ in r["comp_" + side]) == tuple(k for k, _ in spec[side])
        assert len(r["names_" + side]) == len(r["comp_" + side]) <= RX.NC
        for kind, a in r["comp_" + side]:
            assert kind in ("state", "event") and a.dtype == np.float64 and a.shape == (n,)
            ok = a[~np.isnan(a)]
            assert set(np.unique(ok)) <= {0.0, 1.0} and len(ok) > n // 2          # a tri-state: 1, 0 or unknown
            assert (ok == 1.0).any() and (ok == 0.0).any(), (name, side, kind)    # a random walk both breaks and keeps the structure
    for k in ("lvl_long", "lvl_short", "tgt_long", "tgt_short"):
        assert r[k].shape == (n,) and np.isnan(r[k]).all()                          # no own stop or target level for these 11
    assert RX.normalize_native({k: r[k] for k in ("comp_long", "comp_short", "lvl_long", "lvl_short", "tgt_long", "tgt_short")}, n)["tri"]["l"]


def test_the_kinds_follow_the_description_of_each_strategy():
    kinds = {n: [k for k, _ in NM.SPEC[n]["long"]] for n in CORE}
    assert kinds == {"N02_ST_KST": ["state", "event"], "N04_ST_KLINGER": ["state", "event"], "N07_ICHI_CMO": ["state"] * 3, "N12_ICHI_AO": ["state"] * 3,
                     "N21_ST_RSI_ADX": ["state", "event"], "N23_HA_ST": ["state", "state"]}
    for n in DS:
        assert [k for k, _ in ND.SPEC[n]["long"]] == ["state"] == [k for k, _ in ND.SPEC[n]["short"]]
    for n in CORE:
        assert [k for k, _ in NM.SPEC[n]["short"]] == kinds[n]


def test_an_empty_frame_gives_empty_arrays_and_a_wrong_expect_is_refused():
    for name in ALL:
        df = world([100.0])[:0]
        r = native(name, df)
        assert all(len(a) == 0 for _k, a in r["comp_long"] + r["comp_short"]) and all(len(r[k]) == 0 for k in ("lvl_long", "tgt_short"))
    df = walk(400)
    n = len(df)
    with pytest.raises(AssertionError):
        NM.native_arrays("N02_ST_KST", df, "15m", {}, expect=(np.ones(n, bool), np.zeros(n, bool)))
    with pytest.raises(AssertionError):
        ND.native_arrays(df, "15m", "F4_FAN", {}, None, "BTCUSD", expect=(np.ones(n, bool), np.zeros(n, bool)))
    with pytest.raises(KeyError):
        NM.native_arrays("DOGE", df, "15m", {})
    with pytest.raises(ValueError):
        ND.native_arrays(df, "15m", "F5_BOX", {}, None, "BTCUSD")


def test_the_modules_own_entry_flags_are_what_expect_asserts():
    df = walk(1000)
    M = NM.strategy_module("N23_HA_ST")
    lo, sh = M.signals(df.reset_index(drop=True), "15m")
    NM.native_arrays("N23_HA_ST", df, "15m", {}, expect=(lo, sh))                                  # no raise
    D = ND.ds_module()
    lg, sg = D.signals(df, "15m", "F4_FAN", ctx=None, coin="BTCUSD", cache={})
    ND.native_arrays(df, "15m", "F4_FAN", {}, None, "BTCUSD", expect=(lg, sg))


# ---------------------------------------------------------------- hand-made bar worlds: core
@pytest.mark.parametrize("name", CORE)
def test_a_rising_world_keeps_the_longs_structure_and_a_crash_breaks_it(name):
    up, crash = native(name, world(UP)), native(name, world(CRASH))
    for kind, a in up["comp_long"]:
        if kind == "state":
            assert not (a[150:300] == 1.0).any(), name                                             # no state against a long in a smooth rise
    for kind, a in up["comp_short"]:
        if kind == "state":
            assert (a[150:300] == 1.0).any(), name                                                 # ... and the mirror: a short's structure IS broken there
    for (_k, a), (_k2, b) in zip(crash["comp_long"], up["comp_long"]):
        assert tri_eq(a[:300], b)                                                                  # the 40 bars of the crash do not change the bars before them
    states = [a[339] for k, a in crash["comp_long"] if k == "state"]
    assert states and all(x == 1.0 for x in states), name                                          # after a 40% fall every state of the long side is against it
    assert any((a[300:340] == 1.0).any() for k, a in crash["comp_long"] if k == "event") or all(k == "state" for k, _ in crash["comp_long"]), name
    for kind, a in crash["comp_short"]:
        if kind == "state":
            assert not (a[339] == 1.0), name                                                       # a falling world does not break a short


def test_the_state_components_are_the_current_direction_and_the_events_are_the_crossings():
    crash = world(CRASH)
    r = NM.native_arrays("N02_ST_KST", crash, "15m", {})
    M = NM.strategy_module("N02_ST_KST")
    p = M._resolve({})
    d = crash.reset_index(drop=True)
    _l, direction, _u, _lo = M.fg_fast.supertrend(d, p["st_atr_len"], p["st_mult"])
    dirn = direction.to_numpy()
    assert tri_eq(comps(r, "long")[0], np.where(np.isnan(dirn), np.nan, (dirn < 0).astype(float)))
    assert tri_eq(comps(r, "short")[0], np.where(np.isnan(dirn), np.nan, (dirn > 0).astype(float)))
    k, s = M.fg.kst(d["close"], p["kst_roc_lens"], M._KST_SMA, p["kst_signal_len"])
    below = np.asarray(M.cross_below(k, s), bool)
    ev = comps(r, "long")[1]
    assert (ev == 1.0).any() and np.array_equal(ev == 1.0, below & ~np.isnan(ev))                 # the event is true exactly at the bars of the crossing


def test_n21_the_rebound_failed_is_the_rsi_crossing_back_below_the_level_not_the_dip_itself_being_below():
    # a dip under 30, a rebound over 30, a second dip under 30
    c = np.r_[100.0 + 0.2 * (-1.0) ** np.arange(60), 100 * np.exp(-0.012 * np.arange(1, 30)), 70 * np.exp(0.03 * np.arange(1, 14)), 100 * np.exp(-0.03 * np.arange(1, 25))]
    r = NM.native_arrays("N21_ST_RSI_ADX", world(c), "15m", {})
    M = NM.strategy_module("N21_ST_RSI_ADX")
    rsi = M.fg.rsi(world(c)["close"], M.RSI_LEN).to_numpy()
    x = comps(r, "long")[1]
    first_below = 60 + int(np.argmax(rsi[60:] < 30))                                               # (the first bars of an RSI are not a dip)
    assert x[first_below] == 1.0                                                                  # the first dip under 30 is a cross below too (it is before any entry here)
    above = np.flatnonzero(rsi >= 30)
    above = above[above > first_below]
    again = [i for i in range(above[0], len(rsi)) if rsi[i] < 30 <= rsi[i - 1]]
    assert again and all(x[i] == 1.0 for i in again)
    inside = np.flatnonzero((rsi < 30) & (np.r_[np.nan, rsi[:-1]] < 30))
    assert len(inside) and all(x[i] == 0.0 for i in inside)                                       # staying under 30 is not a failed rebound
    short = comps(r, "short")[1]
    crossing_up = (rsi > 70) & (np.r_[np.nan, rsi[:-1]] <= 70)
    assert np.array_equal(short == 1.0, crossing_up & ~np.isnan(short))                           # the short side: the mirror around 100 - level
    levels = NM.native_arrays("N21_ST_RSI_ADX", world(c), "15m", {"rsi_level": 40.0})            # the pick's own level (custom number) is used
    assert not tri_eq(comps(levels, "long")[1], x)


def test_the_picks_own_combo_changes_the_arrays():
    df = walk(900)
    base = NM.native_arrays("N23_HA_ST", df, "15m", {})
    other = NM.native_arrays("N23_HA_ST", df, "15m", {"st_mult": 1.5})
    assert not tri_eq(comps(base, "long")[1], comps(other, "long")[1]) and tri_eq(comps(base, "long")[0], comps(other, "long")[0])
    base = NM.native_arrays("N07_ICHI_CMO", df, "15m", {})
    other = NM.native_arrays("N07_ICHI_CMO", df, "15m", {"cmo_len": 5})
    assert tri_eq(comps(base, "long")[0], comps(other, "long")[0]) and not tri_eq(comps(base, "long")[2], comps(other, "long")[2])
    base = NM.native_arrays("N12_ICHI_AO", df, "15m", {})
    other = NM.native_arrays("N12_ICHI_AO", df, "15m", {"ao_slow_len": 20})
    assert not tri_eq(comps(base, "long")[2], comps(other, "long")[2])
    base = NM.native_arrays("N04_ST_KLINGER", df, "15m", {})
    other = NM.native_arrays("N04_ST_KLINGER", df, "15m", {"kvo_lens": [10, 20]})
    assert not tri_eq(comps(base, "long")[1], comps(other, "long")[1])
    base = ND.native_arrays(df, "15m", "F4_FAN", {}, None, "BTCUSD")
    other = ND.native_arrays(df, "15m", "F4_FAN", {"fan_lens": [3, 5, 8, 13, 21]}, None, "BTCUSD")
    assert not tri_eq(comps(base, "long")[0], comps(other, "long")[0])


def test_a_rising_price_is_above_the_cloud_visible_at_each_bar_not_below_it():
    c = 100 * np.exp(0.003 * np.arange(200))                                                       # the cloud shown at bar i is the one computed 26 bars before
    r = NM.native_arrays("N07_ICHI_CMO", world(c), "15m", {})
    below_cloud, above_cloud = comps(r, "long")[1], comps(r, "short")[1]
    assert np.isnan(below_cloud[:77]).all() and np.isfinite(below_cloud[77:]).all()                # 52 bars of span B + 26 of displacement
    assert not (below_cloud == 1.0).any() and (above_cloud[100:] == 1.0).all()


# ---------------------------------------------------------------- hand-made bar worlds: DeepSeek five
def test_f4_the_shortest_ema_under_the_middle_one_breaks_the_fan():
    up, crash = native("F4_FAN", world(UP)), native("F4_FAN", world(CRASH))
    assert (comps(up, "short")[0][100:300] == 1.0).all() and (comps(up, "long")[0][100:300] == 0.0).all()
    assert comps(crash, "long")[0][339] == 1.0 and comps(crash, "short")[0][339] == 0.0
    D = ND.ds_module()
    em = [D._Series(world(CRASH), "15m", None, "BTCUSD", {}).ema(k) for k in (8, 21)]
    assert np.array_equal(comps(crash, "long")[0] == 1.0, em[0] < em[1])                           # the shortest (8) against the middle one of 8, 13, 21, 34, 55


def test_f6_close_under_the_days_vwap_breaks_a_long_and_the_first_bar_of_a_day_is_unknown():
    v = np.r_[np.linspace(100, 103, 60), np.linspace(103, 98, 36)]
    r = native("F6_VWAP_FAIL", world(np.tile(v, 3)))
    a, s = comps(r, "long")[0], comps(r, "short")[0]
    assert np.isnan(a[[0, 96, 192]]).all() and np.isnan(s[[0, 96, 192]]).all()
    assert (a[96 + 1:96 + 60] == 0.0).all() and (s[96 + 1:96 + 60] == 1.0).all()                    # rising above the VWAP of the day
    assert (a[96 + 90:192] == 1.0).all() and (s[96 + 90:192] == 0.0).all()                          # fallen under it
    assert np.isfinite(a[[1, 97, 193]]).all()


def test_f15_orb_closing_back_inside_the_opening_range_breaks_a_long():
    day = np.r_[np.full(2, 100.0), np.linspace(100.8, 102.5, 38), np.linspace(102.4, 100.0, 10), np.full(46, 100.0)]
    r = native("F15_ORB", world(np.tile(day, 3)))
    a, s = comps(r, "long")[0], comps(r, "short")[0]
    assert np.isnan(a[[0, 1, 96, 97, 192, 193]]).all()                                             # the opening bars make the range: no judgement inside them
    assert (a[96 + 2:96 + 48] == 0.0).all()                                                         # closes above the range's top
    assert (a[96 + 60:192] == 1.0).all() and (s[96 + 2:96 + 48] == 1.0).all()                       # back at 100 = inside the range; the short side: above the range's bottom
    assert (s[96 + 60:192] == 1.0).all()
    r2 = native("F15_ORB", world(np.tile(day, 3)), combo={"orb_bars": 4})                           # the pick's own number of bars
    assert np.isnan(comps(r2, "long")[0][[96, 97, 98, 99]]).all() and np.isfinite(comps(r2, "long")[0][100])


def test_f15_lon_brk_closing_back_inside_the_london_range_breaks_a_long():
    lon = np.r_[np.full(36, 100.0), np.linspace(100.2, 102.0, 24), np.linspace(101.5, 100.0, 12), np.full(24, 100.0)]
    r = native("F15_LON_BRK", world(np.tile(lon, 3)))
    a, s = comps(r, "long")[0], comps(r, "short")[0]
    base = 96                                                                                       # day 2; March 12 is EDT: 02:00-05:00 ET = 06:00-09:00 UTC = bars 24..35
    assert np.isnan(a[base + 16:base + 36]).all() and np.isnan(s[base + 16:base + 36]).all()      # a new ET day before 05:00 ET: its range is not there yet
    assert np.isfinite(a[base + 36]) and (a[base + 37:base + 60] == 0.0).all()                       # above the top of the range after the break
    assert (a[base + 72:base + 96] == 1.0).all() and (s[base + 37:base + 60] == 1.0).all()
    assert (a[:16] == 1.0).all() or np.isnan(a[:16]).all()                                          # the first evening: the block's range is not complete / not known


def test_f3_bos_a_close_under_the_last_confirmed_swing_low_breaks_a_long():
    z = [100.0]
    for _ in range(10):
        z += list(np.linspace(z[-1], z[-1] + 6, 9)[1:])
        z += list(np.linspace(z[-1], z[-1] - 3, 9)[1:])
    z += list(np.linspace(z[-1], z[-1] - 20, 14)[1:])
    df = world(z)
    r = native("F3_BOS", df)
    a = comps(r, "long")[0]
    assert np.isnan(a[:15]).all() and (a[30:-12] == 0.0).all() and (a[-6:] == 1.0).all()           # higher lows hold until the last fall
    D = ND.ds_module()
    S = D._Series(df, "15m", None, "BTCUSD", {}).S(3)
    assert np.array_equal(a == 1.0, np.asarray(df["close"]) < S["lo"])                              # the swing of the entry's own structure
    assert np.array_equal(comps(r, "short")[0] == 1.0, np.asarray(df["close"]) > S["hi"])
    r5 = native("F3_BOS", df, combo={"swing_k": 5})
    assert not tri_eq(comps(r5, "long")[0], a)


# ---------------------------------------------------------------- no look-ahead
@pytest.mark.parametrize("name", ALL)
def test_nothing_at_bar_i_depends_on_a_bar_after_i(name):
    df = walk(1200, seed=11)
    full = native(name, df)
    for cut in (260, 397, 640, 961, 1199):
        part = native(name, df.iloc[:cut + 1].reset_index(drop=True))
        for side in ("long", "short"):
            for (_k, fa), (_k2, pa) in zip(full["comp_" + side], part["comp_" + side]):
                assert tri_eq(fa[:cut + 1], pa), (name, side, cut)


@pytest.mark.parametrize("name", DS)
def test_nothing_after_i_matters_for_the_session_strategies_cut_inside_a_day(name):
    # cuts right at the bars where a day's range is complete (the first judged bar) and one bar before
    df = world(np.tile(np.r_[np.full(36, 100.0), np.linspace(100.2, 102.0, 24), np.linspace(101.5, 100.0, 12), np.full(24, 100.0)], 4))
    full = native(name, df)
    for cut in (96 + 35, 96 + 36, 96 + 37, 96 + 2, 96 + 3, 191, 192, 193, 250):
        part = native(name, df.iloc[:cut + 1].reset_index(drop=True))
        for side in ("long", "short"):
            for (_k, fa), (_k2, pa) in zip(full["comp_" + side], part["comp_" + side]):
                assert tri_eq(fa[:cut + 1], pa), (name, side, cut)


# ---------------------------------------------------------------- the provider
def test_the_production_provider_routes_the_eleven_to_the_new_files_and_the_study_s_sixteen_to_the_study():
    prov = RX.load_native_provider()
    df = walk(700)
    keys = ("comp_long", "comp_short", "lvl_long", "lvl_short", "tgt_long", "tgt_short")
    for name in ALL:
        kind = "core" if name in CORE else "ds"
        a = {"kind": kind, "name": name, "tf": "15m", "combo": {}}
        got = prov(a, "BTCUSDT", df, None, None, None, None)
        want = native(name, df)
        assert set(got) == set(keys)
        for side in ("comp_long", "comp_short"):
            assert [k for k, _ in got[side]] == [k for k, _ in want[side]]
            assert all(tri_eq(x, y) for (_k, x), (_l, y) in zip(got[side], want[side])), name
        n = RX.normalize_native(got, len(df))
        assert len(n["tri"]["l"]) == len(want["comp_long"])
    # a strategy of the study keeps its own file
    import importlib
    nat = importlib.import_module("native")
    got = prov({"kind": "core", "name": "OBV_S", "tf": "15m", "combo": {}}, "BTCUSDT", df, None, None, None, None)
    ref = nat.native_arrays("OBV_S", df, "15m", {})
    assert tri_eq(got["comp_long"][0][1], ref["comp_long"][0][1])


# ---------------------------------------------------------------- the accounts
def _owner():
    return C.load(os.path.join(ROOT, "candleague", "data", "candidates_owner.json"))


def _accounts():
    doc = json.load(open(os.path.join(ROOT, "candleague", "data", "rules_owner_exits.json")))
    cfg = RX.normalize_owner(doc)
    return _owner(), RX.owner_accounts(_owner(), cfg), cfg


def test_the_eleven_picks_get_the_structure_accounts_and_the_other_38_picks_keep_theirs():
    owner, accts, cfg = _accounts()
    kinds = ["-fq", "-nv", "-tg", "-fqc", "-fqt", "-fqv"]
    weak = [c for c in owner if c["source"].get("tier") == "weak"]
    assert len(owner) == 49 and len(weak) == 11 and {c["name"] for c in weak} == set(ALL)
    assert all(RX.native_supported(c) for c in owner) and sum(1 for c in owner if RX.native_levels_supported(c)) == 13
    ids = {a["id"] for a in accts}
    for c in weak:
        for k in kinds:
            assert c["id"] + k in ids, (c["id"], k)
        assert c["id"] + "-iv" not in ids and c["id"] + "-ot" not in ids                             # no own level or target for these 11
    assert len(accts) == 1384 == 1122 + 11 * 6 + 196 and len(ids) == len(accts)
    assert len(accts) - 66 - 196 == 1122
    by = {a["id"]: a for a in accts}
    for c in weak:
        assert by[c["id"] + "-fq"]["rule"]["id"] == "F11.a.d0.5" and by[c["id"] + "-nv"]["rule"]["id"] == "F11.a" and by[c["id"] + "-tg"]["tighten"] == 0.5
        assert by[c["id"] + "-fqc"]["coin"] is True and by[c["id"] + "-fqc"]["of"] == c["id"] + "-fq"
        assert by[c["id"] + "-fqt"]["gate"] == "g1" and by[c["id"] + "-fqv"]["gate"] == "g2"
    assert sum(1 for a in accts if a.get("coin")) == 49 + 49
    assert RX.check(owner, cfg) == []


def test_every_pick_check_passes_on_the_real_rules_and_the_rule_needs_the_structure_records():
    owner, accts, cfg = _accounts()
    for k in ("-fq", "-nv", "-tg"):
        group = [a for a in accts if a["id"].endswith(k)]
        assert len(group) == 49 and all(RX.rule_needs(a["rule"]) for a in group)


# ---------------------------------------------------------------- the hash that restarts the league
def test_the_native_hash_covers_the_two_new_files(tmp_path, monkeypatch):
    h0 = RX.native_hash()
    assert h0 != "absent"
    for f in RX.NATIVE_MORE_FILES:
        shutil.copy(os.path.join(ROOT, "candleague", f), tmp_path / f)
    monkeypatch.setattr(RX, "__file__", str(tmp_path / "rulex.py"))
    h1 = RX.native_hash()
    assert h1 == h0                                                                                 # same bytes, same hash
    for f in RX.NATIVE_MORE_FILES:
        p = tmp_path / f
        keep = p.read_bytes()
        p.write_bytes(keep + b"\n# changed\n")
        assert RX.native_hash() != h1, f
        p.write_bytes(keep)
        assert RX.native_hash() == h1
    (tmp_path / "native_more_ds.py").unlink()
    assert RX.native_hash() == "absent"


def test_a_changed_native_hash_changes_the_fingerprint_of_a_structure_account_of_the_eleven(monkeypatch):
    owner, accts, _cfg = _accounts()
    pick = next(c for c in owner if c["name"] == "N02_ST_KST")
    mine = [a for a in accts if a["pick"] == pick["id"] and a["id"].endswith(("-fq", "-nv", "-tg"))]
    assert len(mine) == 3
    monkeypatch.setattr(RX, "native_hash", lambda: "aaaa")
    f1 = RN.fingerprint(mine)
    monkeypatch.setattr(RX, "native_hash", lambda: "bbbb")
    assert RN.fingerprint(mine) != f1
    assert RN.fingerprint(accts) != "" and len(RN.fingerprint(accts)) > 8


# ---------------------------------------------------------------- the league restarted in pieces
def _cands(kind, name):
    return [{"id": f"{kind}-{name}-15m-1", "kind": kind, "name": name, "tf": "15m",
             "combo": {k: C._plain(v) for k, v in C.default_combo(kind, name).items()}, "exit": "tp1R|1", "source": {}}]


def _league(db, kind, cands):
    """A league on the test module's synthetic days with the F11 'strategy decides' rule on the pool of ``kind`` (the production provider)."""
    accts = RX.accounts(cands, RX.normalize_config({"pools": {kind: "F11.a"}}))
    return RN.League(RN.open_db(str(db)), accts, TR.TP.BRACKETS, TR.TP.SPECS, TR.LIB, TR.PS.FrameSource(TR.DATA), TR.TP._steps_from(TR.DATA),
                     TR.TP.SYMS, start_ms=TR.START, log=lambda s: None)


@pytest.mark.parametrize("kind,name", [("core", "N23_HA_ST"), ("ds", "F4_FAN")])
def test_a_league_restarted_in_pieces_gives_the_trades_of_one_run(tmp_path, monkeypatch, kind, name):
    monkeypatch.setattr(L, "Strategies", TR.StubStrategies)
    cands = _cands(kind, name)
    mk = lambda db: _league(db, kind, cands)  # noqa: E731
    full = mk(tmp_path / "f.db")
    full.advance(TR.START + 3 * TR.DAY)
    rows = TR._trades(full)
    rule_exits = [r for r in rows if r[3] == "RULE"]
    assert len(rows) > 10 and rule_exits, "the strategy's own structure never closed a position on the synthetic days"
    lg, t = mk(tmp_path / "g.db"), TR.START
    for step in (7, 3, 25, 1, 40, 13, 90, 5, 61, 2, 150):
        t += step * RN.FIVE
        lg.advance(t)
        lg = mk(tmp_path / "g.db")
        assert lg.restore_notes == [], (t, lg.restore_notes)
    lg.advance(TR.START + 3 * TR.DAY)
    assert TR._trades(lg) == rows

"""Reel 5m Bollinger + 200 MA test: PREREG hash, configuration count, look-ahead, engine parity, hand-built micro
examples for every rule. Synthetic data only, no network, no real bars.
"""
import hashlib
import importlib.util
import os
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RD = os.path.join(ROOT, "research", "reel5m")
sys.path.insert(0, RD)

spec = importlib.util.spec_from_file_location("lib_reel5m", os.path.join(RD, "lib_reel5m.py"))
R = importlib.util.module_from_spec(spec)
sys.modules["lib_reel5m"] = R
spec.loader.exec_module(R)

COST = R.env()["L"]._cost("5m", R.MAX_HOLD)
SLIP, FEE = COST.slip_side, COST.fee_side
NEUTRAL = (100.2, 100.6, 99.6, 100.0)          # small red bar well inside the band [90, 110]
HOLD = (92.0, 92.5, 91.5, 92.0)                # in-position bar: touches neither the stop (86.95) nor the band (110)


# ------------------------------------------------------------------ helpers
def ind_from(rows, upper=110.0, lower=90.0, mid=100.0, ma=95.0, atr=1.0, up_live=None, dn_live=None):
    """Hand-built indicator arrays: bands, middle line, MA, ATR (and the live-band levels) given directly."""
    a = np.array(rows, float)
    n = len(a)

    def f(v):
        return np.full(n, float(v)) if np.ndim(v) == 0 else np.asarray(v, float)
    ind = {"o": a[:, 0], "h": a[:, 1], "l": a[:, 2], "c": a[:, 3], "upper": f(upper), "mid": f(mid), "lower": f(lower),
           "SMA200": f(ma), "EMA200": f(ma), "atr": f(atr)}
    if up_live is not None:
        ind["up_live"], ind["dn_live"] = f(up_live), f(dn_live)
    return ind


def sim(ind, breach="CLOSE", sides="LONG", lo=0, hi=None, mode="open", trade=True, ma="SMA200", **kw):
    P = R.Prep(ind, ma, breach, sides)
    return R.simulate(P, COST, lo, len(ind["c"]) - 1 if hi is None else hi, mode, trade, **kw)


def sig_idx(ind, **kw):
    _t, sg, _s = sim(ind, trade=False, **kw)
    return [s["signal_idx"] for s in sg]


def base_rows(n_after=8):
    rows = [NEUTRAL] * 5                                   # 0-4
    rows += [(91.0, 91.5, 88.0, 89.0)]                     # 5  breach: close 89 < lower 90 (arms)
    rows += [(89.0, 89.5, 87.0, 87.5)]                     # 6  still below: new breach, low 87 (lowest)
    rows += [(87.5, 89.8, 87.2, 89.5)]                     # 7  green but closes below the band: not a signal (a breach)
    rows += [(89.5, 91.5, 89.0, 91.0)]                     # 8  green, closes inside: SIGNAL
    rows += [(91.3, 92.0, 90.5, 91.8)]                     # 9  entry bar, open 91.3
    rows += [HOLD] * n_after
    return rows


# ------------------------------------------------------------------ pre-registration and counts
def test_prereg_hash():
    with open(os.path.join(RD, "PREREG_REEL5M.sha256")) as fh:
        want, name = fh.read().split()
    assert name == "PREREG_REEL5M.md"
    with open(os.path.join(RD, name), "rb") as fh:
        got = hashlib.sha256(fh.read()).hexdigest()
    assert got == want, "PREREG changed after the hash was recorded: a change is a new pre-registration"
    assert R.check_prereg() == want


def test_runner_refuses_on_prereg_mismatch(tmp_path, monkeypatch):
    md = tmp_path / "PREREG_REEL5M.md"
    md.write_text("changed")
    sha = tmp_path / "PREREG_REEL5M.sha256"
    sha.write_text("0" * 64 + "  PREREG_REEL5M.md\n")
    monkeypatch.setattr(R, "PREREG", str(md))
    monkeypatch.setattr(R, "PREREG_SHA", str(sha))
    with pytest.raises(SystemExit, match="refusing"):
        R.run(str(tmp_path / "no_bars"), str(tmp_path / "no_pre"), str(tmp_path / "out"), 1, ("5m",), 10)
    assert not (tmp_path / "out").exists()
    sha.unlink()
    with pytest.raises(SystemExit, match="refusing"):
        R.check_prereg()


def test_config_count_and_prereg_consistency():
    cfg = R.config_list()
    assert len(cfg) == 40 and len(set(cfg)) == 40
    assert R.H1 == ("5m", "BB_SMA200_CLOSE_LONG", "SWING_BAND") and R.H1 in cfg
    assert {t for t, _e, _x in cfg} == set(R.TFS) == {"5m", "15m", "30m", "1h", "4h"}
    for tf in R.TFS:
        assert sum(1 for t, _e, _x in cfg if t == tf) == 8
    assert (R.WAIT, R.STOP_BUF_ATR, R.MAX_HOLD, R.BB_LEN, R.BB_K, R.MA_LEN) == (12, 0.05, 96, 20, 2.0, 200)
    assert (R.STOP_BUF_SENS, R.SLIP_SENS, R.TP_THROUGH_SENS) == (0.3, 0.0005, 0.0002)
    assert R.LIVE_K == pytest.approx(2 * np.sqrt(20 / 15)) and list(R.SENS) == [
        "close", "live_target", "buf03", "cost_a", "cost_b", "cost_c"]
    assert R.COINS == ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD")
    with open(os.path.join(RD, "PREREG_REEL5M.md"), encoding="utf-8") as fh:
        text = fh.read()
    assert "N = 5 × 2 × 2 × 2 = 40" in text
    for e in R.ENTRY_NAMES:
        assert e in text, e
    for s in ("SWING_BAND", "12봉", "0.05 × ATR14", "96봉", "2021-08-01", "2024-07-01", "2026-09-30", "2020-01-01", "q = 10%",
              "0.3 × ATR14", "2.309", "0.05%", "0.02%", "비용에 민감한 통과", "보조 후보(관찰)"):
        assert s in text, s
    # the library's split labels are what the gauntlet reads
    assert R.PERIODS == {"is": ("2021-08-01", "2024-07-01"), "oos": ("2024-07-01", "2026-09-30"), "pre": ("2020-01-01", "2021-08-01")}


# ------------------------------------------------------------------ indicators
def test_indicators_match_naive_definitions():
    df = R.synth(700, "5m", 4)
    ind = R.indicators(df)
    c = df["close"].to_numpy()
    for t in (19, 250, 699):
        w = c[t - 19:t + 1]
        assert np.isclose(ind["mid"][t], w.mean(), rtol=1e-12)
        sd = np.sqrt(((w - w.mean()) ** 2).mean())                    # population std, as TradingView ta.bb
        assert np.isclose(ind["upper"][t], w.mean() + 2 * sd, rtol=1e-10)
        assert np.isclose(ind["lower"][t], w.mean() - 2 * sd, rtol=1e-10)
    assert np.isnan(ind["mid"][18]) and np.isnan(ind["SMA200"][198])
    assert np.isclose(ind["SMA200"][450], c[251:451].mean(), rtol=1e-12)
    ema = c[:200].mean()                                                  # TradingView seed: SMA of the first 200
    assert np.isclose(ind["EMA200"][199], ema, rtol=1e-12)
    for t in range(200, 700):
        ema = 2 / 201 * c[t] + (1 - 2 / 201) * ema
    assert np.isclose(ind["EMA200"][699], ema, rtol=1e-10)
    assert np.isfinite(ind["atr"][14:]).all()


def test_live_band_touch_level_closed_form():
    """up_live[j] = the price at which bar j's close would sit exactly on bar j's own upper band (19 earlier closes)."""
    df = R.synth(700, "5m", 4)
    ind = R.indicators(df)
    c = df["close"].to_numpy()
    for j in (19, 251, 699):
        prev = c[j - 19:j]
        for lvl, sgn in ((ind["up_live"][j], 1), (ind["dn_live"][j], -1)):
            x = np.r_[prev, lvl]
            assert lvl == pytest.approx(x.mean() + sgn * 2 * x.std(), rel=1e-9)
            above = np.r_[prev, lvl + sgn * 1e-3]                       # a bit beyond: outside its own band
            assert sgn * (above[-1] - (above.mean() + sgn * 2 * above.std())) > 0
    assert np.isnan(ind["up_live"][18]) and np.isfinite(ind["up_live"][19])   # bar 19 has 19 earlier closes
    ok = np.isfinite(ind["up_live"]) & np.isfinite(ind["upper"])
    assert (ind["up_live"][1:][ok[1:]] >= ind["upper"][:-1][ok[1:]] - 1e-9).mean() > 0.6   # usually above UP[j-1]


@pytest.mark.parametrize("tf", ["5m", "4h"])
def test_indicators_are_prefix_invariant(tf):
    df = R.synth(1500, tf, 6)
    full = R.indicators(df)
    for k in (230, 777, 1499):
        part = R.indicators(df.iloc[:k].copy())
        for key, v in full.items():
            np.testing.assert_allclose(part[key], v[:k], rtol=1e-12, atol=0, err_msg=f"{key} at cut {k}")


# ------------------------------------------------------------------ look-ahead and determinism
@pytest.mark.parametrize("tf", ["5m", "15m", "30m", "1h", "4h"])
def test_no_lookahead_signals_and_trades(tf):
    R.lookahead_check(tf, n=2400)


@pytest.mark.parametrize("tf", ["5m", "15m", "30m", "1h", "4h"])
def test_no_lookahead_at_decision_time(tf):
    assert R.decision_lookahead_check(tf) == []


def test_decision_check_catches_a_one_bar_leak_that_lookahead_check_misses(monkeypatch):
    real = R.Prep.__init__

    def leaky(self, ind, *a):
        real(self, ind, *a)
        lo_ = np.asarray(self.L["l"])
        self.L["l"] = np.minimum(lo_, np.r_[lo_[1:], np.inf]).tolist()    # the stop sees the entry bar's low
    monkeypatch.setattr(R.Prep, "__init__", leaky)
    R.lookahead_check("5m", n=2400)                                     # the coarse check does not see it
    assert R.decision_lookahead_check("5m")


def test_lookahead_check_detects_a_leak(monkeypatch):
    real = R.indicators

    def leaky(df):
        out = real(df)
        for k in ("upper", "lower"):
            out[k] = np.r_[out[k][150:], np.full(150, np.nan)]           # bands from 150 bars in the future
        return out
    monkeypatch.setattr(R, "indicators", leaky)
    with pytest.raises(AssertionError, match="lookahead"):
        R.lookahead_check("5m", n=2400)


def test_determinism_and_one_position():
    df = R.synth(12000, "5m", 21, vol=0.0015)
    ind = R.indicators(df)
    for name in R.ENTRY_NAMES:
        P = R.Prep(ind, *R.parse_entry(name))
        a = R.simulate(P, COST, 300, len(df) - 100)
        b = R.simulate(R.Prep(R.indicators(df), *R.parse_entry(name)), COST, 300, len(df) - 100)
        assert a == b, name
        tr = a[0]
        assert len(tr) > 10, name
        for x, y in zip(tr[:-1], tr[1:]):
            assert y["arm_idx"] > x["exit_idx"] and y["signal_idx"] > x["exit_idx"]   # nothing armed while holding
        if name.endswith("_LONG"):
            assert all(x["side"] == 1 for x in tr)
        else:
            assert {x["side"] for x in tr} == {1, -1}


# ------------------------------------------------------------------ engine parity (cost model, fills, one position)
def test_exit_simulator_equals_locked_engine_on_fixed_stop_and_target():
    assert R.engine_parity_check() > 1000


def test_locked_engine_skips_a_signal_on_the_exit_bar():
    """PREREG 5.9: the engine's comment says a signal on the exit bar is allowed, its code skips it; we follow the code."""
    import dataclasses
    L = R.env()["L"]
    n = 60
    o = np.full(n, 100.0)
    df = pd.DataFrame({"open": o, "high": o + 0.5, "low": o - 0.5, "close": o})
    df.loc[9, "high"] = 103.0                                         # TP (2 ATR) on bar 9
    lg = np.zeros(n, bool)
    lg[[5, 9, 10]] = True                                              # 5: trade exiting on 9; 9: exit bar; 10: next
    cost = dataclasses.replace(L._cost("1h", 48), warmup=0)
    cfg = L.ExitCfg(name="x", mode="FIXED", sl_atr=1.0, tp_atr=2.0)
    t = L.run_backtest(df, np.ones(n), lg, np.zeros(n, bool), cfg, cost, 0, 50)
    assert list(t["signal_idx"]) == [5, 10] and t["exit_idx"].iloc[0] == 9


def test_cost_constants_are_the_library_engine_constants():
    L = R.env()["L"]
    assert (COST.fee_side, COST.slip_side, COST.funding_8h, COST.bar_minutes, COST.max_hold) == \
           (L.FEE_SIDE, L.SLIP_SIDE, L.FUNDING_8H, 5, 96) == (0.0005, 0.0002, 0.0001, 5, 96)


# ------------------------------------------------------------------ micro examples: entry rules
def test_breach_wait_green_close_inside_signal_and_trade():
    rows = base_rows()
    rows[12] = (92.0, 110.5, 91.8, 109.0)                  # 12: high reaches the band (110 = upper of bar 11): TP
    ind = ind_from(rows)
    assert sig_idx(ind) == [8]
    tr, sg, sk = sim(ind)
    assert sk == {"stop": 0, "target": 0, "atr": 0} and len(tr) == 1
    t = tr[0]
    assert (t["signal_idx"], t["arm_idx"], t["last_breach_idx"], t["entry_idx"]) == (8, 5, 7, 9)
    entry = 91.3 * (1 + SLIP)                              # next bar open plus slippage
    assert t["entry_px"] == entry
    assert t["stop_px"] == pytest.approx(87.0 - 0.05 * 1.0)  # lowest low of bars 5-8 minus 0.05 ATR
    assert (t["exit_idx"], t["reason"], t["exit_px"], t["hold"]) == (12, "TP", 110.0, 4)
    assert t["gross"] == pytest.approx(110.0 / entry - 1)
    assert t["net"] == pytest.approx(t["gross"] - 2 * FEE - 0.0001 * 4 * 5 / 480)
    assert t["sl_dist"] == pytest.approx((entry - 86.95) / entry)


def test_no_signal_for_red_inside_or_green_outside():
    rows = base_rows()
    rows[9] = HOLD                                         # (bar 9 of the base path is green inside: neutralise it)
    rows[8] = (91.5, 92.0, 89.0, 91.0)                     # red close inside
    assert sig_idx(ind_from(rows)) == []
    rows[8] = (89.5, 111.0, 89.0, 110.5)                   # green but closes above the upper band
    assert sig_idx(ind_from(rows)) == []
    rows[8] = (89.5, 91.5, 89.0, 89.5)                     # doji (close == open) inside: not green
    assert sig_idx(ind_from(rows)) == []


def test_setup_expires_twelve_bars_after_the_breach():
    green = (90.5, 92.0, 90.2, 91.5)
    rows = [NEUTRAL] * 5 + [(91.0, 91.5, 88.0, 89.0)] + [NEUTRAL] * 11 + [green] + [NEUTRAL] * 3   # green at 17 = 5 + 12
    assert sig_idx(ind_from(rows)) == [17]
    rows = [NEUTRAL] * 5 + [(91.0, 91.5, 88.0, 89.0)] + [NEUTRAL] * 12 + [green] + [NEUTRAL] * 3   # green at 18: expired
    assert sig_idx(ind_from(rows)) == []


def test_new_breach_restarts_the_clock_and_keeps_the_first_low():
    green = (90.5, 92.0, 90.2, 91.5)
    rows = ([NEUTRAL] * 5 + [(91.0, 91.5, 88.0, 89.0)] + [NEUTRAL] * 9          # breach at 5 (low 88)
            + [(91.0, 91.5, 89.0, 89.5)] + [NEUTRAL] * 11 + [green] + [HOLD] * 4)  # breach at 15 (low 89), green at 27
    ind = ind_from(rows)
    _t, sg, _s = sim(ind, trade=False)
    assert [(s["signal_idx"], s["arm_idx"], s["last_breach_idx"]) for s in sg] == [(27, 5, 15)]
    assert sg[0]["stop_px"] == pytest.approx(88.0 - 0.05)   # the low of the first breach bar, not of the second
    rows[15] = NEUTRAL                                      # without the second breach: expired at 17
    assert sig_idx(ind_from(rows)) == []


def test_filter_flip_cancels_and_breach_needs_filter_on():
    rows = base_rows()
    ma = np.full(len(rows), 95.0)
    ma[7] = 105.0                                          # middle band below the MA at bar 7: setup cancelled
    assert sig_idx(ind_from(rows, ma=ma)) == []
    ma = np.full(len(rows), 95.0)
    ma[8] = 105.0                                          # filter off on the signal bar itself
    assert sig_idx(ind_from(rows, ma=ma)) == []
    rows2 = [NEUTRAL] * 5 + [(91.0, 91.5, 88.0, 89.0), (89.5, 91.5, 89.0, 91.0)] + [HOLD] * 3
    assert sig_idx(ind_from(rows2)) == [6]
    ma = np.full(len(rows2), 95.0)
    ma[5] = 105.0                                          # breach while the filter is off: never armed
    assert sig_idx(ind_from(rows2, ma=ma)) == []
    mid = np.full(len(rows2), 95.0)                        # middle band == MA: filter off (strict)
    assert sig_idx(ind_from(rows2, mid=mid, ma=95.0)) == []


def test_wick_breach_arms_only_in_the_wick_variant():
    rows = [NEUTRAL] * 5 + [(91.0, 91.5, 89.0, 90.5)] + [(90.5, 92.0, 90.2, 91.5)] + [HOLD] * 3   # low 89 < 90, close inside
    assert sig_idx(ind_from(rows), breach="CLOSE") == []
    assert sig_idx(ind_from(rows), breach="WICK") == [6]
    rows[6] = (90.5, 92.0, 89.5, 91.5)                     # the signal bar itself wicks below: still the signal
    _t, sg, _s = sim(ind_from(rows), breach="WICK", trade=False)
    assert [s["signal_idx"] for s in sg] == [6] and sg[0]["stop_px"] == pytest.approx(89.0 - 0.05)
    rows[5] = (91.0, 91.5, 90.5, 91.0)                     # no wick below 90: nothing arms
    assert sig_idx(ind_from(rows), breach="WICK") == []


def test_window_start_and_end():
    rows = [NEUTRAL] * 5 + [(91.0, 91.5, 88.0, 89.0), (89.5, 91.5, 89.0, 91.0)] + [HOLD] * 3
    ind = ind_from(rows)
    assert sig_idx(ind, lo=5) == [6]
    assert sig_idx(ind, lo=6) == []                        # the breach before the window start is not used
    assert sig_idx(ind, hi=7) == [6] and sig_idx(ind, hi=6) == []   # signal bar must be < hi


# ------------------------------------------------------------------ micro examples: stop, target, hold
def test_stop_at_or_above_entry_is_skipped_and_machine_is_free_again():
    rows = base_rows(4)
    rows[9] = (86.5, 87.0, 86.0, 86.8)                     # opens below the stop 86.95: skip; closes below the band (breach)
    rows[10] = (86.8, 91.0, 86.5, 90.5)                    # green inside: new signal from the breach at 9
    rows[11] = (90.6, 91.0, 90.2, 90.8)                    # entry bar
    tr, sg, sk = sim(ind_from(rows))
    assert sk["stop"] == 1 and [s["signal_idx"] for s in sg] == [8, 10]
    assert len(tr) == 1 and (tr[0]["signal_idx"], tr[0]["arm_idx"], tr[0]["entry_idx"]) == (10, 9, 11)
    assert tr[0]["stop_px"] == pytest.approx(86.0 - 0.05)
    rows[9] = (86.95, 87.0, 86.9, 86.95)                   # opens at the stop level: with slippage the fill is above it
    tr, _sg, sk = sim(ind_from(rows))
    assert sk["stop"] == 0 and tr[0]["signal_idx"] == 8     # 86.95 x 1.0002 > 86.95: traded (and stopped at once)
    assert (tr[0]["exit_idx"], tr[0]["reason"]) == (9, "SL")


def test_entry_above_the_first_target_is_skipped():
    rows = base_rows(4)
    rows[9] = (110.5, 111.0, 109.0, 110.0)                 # gaps above the upper band of the signal bar
    tr, _sg, sk = sim(ind_from(rows))
    assert sk["target"] == 1 and not [t for t in tr if t["signal_idx"] == 8]


def test_target_is_previous_bars_upper_band():
    rows = base_rows(6)
    up = np.full(len(rows), 110.0)
    up[9], up[10], up[11] = 105.0, 103.0, 101.0
    rows[10] = (92.0, 104.0, 91.8, 103.5)                  # high 104 >= own band 103 but < previous bar's 105: no exit
    rows[11] = (100.0, 103.5, 99.0, 102.0)                 # high 103.5 >= previous bar's band 103: TP at 103
    tr, _sg, _sk = sim(ind_from(rows, upper=up))
    assert (tr[0]["exit_idx"], tr[0]["reason"], tr[0]["exit_px"]) == (11, "TP", 103.0)
    rows[11] = (103.2, 103.5, 99.0, 102.0)                 # opens above the resting limit: filled at the better open
    tr, _sg, _sk = sim(ind_from(rows, upper=up))
    assert (tr[0]["exit_idx"], tr[0]["reason"], tr[0]["exit_px"]) == (11, "TP", 103.2)


def test_same_bar_stop_and_target_takes_the_stop():
    rows = base_rows()
    rows[10] = (92.0, 111.0, 86.0, 95.0)                   # low 86 <= stop 86.95 and high 111 >= band 110
    tr, _sg, _sk = sim(ind_from(rows))
    assert (tr[0]["exit_idx"], tr[0]["reason"]) == (10, "SL")
    assert tr[0]["exit_px"] == pytest.approx(86.95 * (1 - SLIP))
    rows[10] = (86.0, 92.0, 85.0, 90.0)                    # gaps below the stop: filled at the open less slippage
    tr, _sg, _sk = sim(ind_from(rows))
    assert (tr[0]["reason"], tr[0]["exit_px"]) == ("SL", 86.0 * (1 - SLIP))


def test_max_hold_96_bars_exit_at_close():
    rows = base_rows(110)
    tr, _sg, _sk = sim(ind_from(rows))
    t = tr[0]
    assert (t["entry_idx"], t["exit_idx"], t["hold"], t["reason"]) == (9, 9 + 95, 96, "TIME")
    assert t["exit_px"] == 92.0 * (1 - SLIP)
    assert t["funding"] == pytest.approx(0.0001 * 96 * 5 / 480)
    tr, _sg, _sk = sim(ind_from(base_rows(40)))             # series ends first: end-of-data exit at the last close
    assert tr[0]["reason"] == "EOD" and tr[0]["exit_idx"] == len(base_rows(40)) - 1


def test_no_new_setup_while_in_a_position_and_exit_bar_does_not_arm():
    rows = base_rows(10)
    rows[10] = (91.8, 92.0, 88.0, 89.5)                    # breach while holding (low 88 > stop 86.95)
    rows[11] = (89.5, 91.5, 89.0, 91.0)                    # green inside while holding: ignored
    rows[14] = (95.0, 110.5, 87.5, 89.0)                   # TP at 110; the exit bar also closes below the band
    rows[15] = (89.0, 91.5, 88.8, 91.0)                    # green inside: not armed (exit bar is still "in position")
    rows[16] = (91.0, 91.2, 88.5, 89.0)                    # new breach after the exit: arms
    rows[17] = (89.0, 91.5, 88.9, 91.2)                    # green inside: signal
    tr, _sg, _sk = sim(ind_from(rows))
    assert len(tr) == 2
    assert (tr[0]["signal_idx"], tr[0]["arm_idx"], tr[0]["exit_idx"], tr[0]["reason"]) == (8, 5, 14, "TP")
    assert (tr[1]["signal_idx"], tr[1]["arm_idx"], tr[1]["entry_idx"]) == (17, 16, 18)
    assert tr[1]["stop_px"] == pytest.approx(88.5 - 0.05)
    assert sig_idx(ind_from(rows)) == [8, 11, 15, 17]      # without positions the bars held through are signals too


def test_entry_at_signal_close_sensitivity():
    rows = base_rows()
    rows[12] = (92.0, 110.5, 91.8, 109.0)
    tr, _sg, _sk = sim(ind_from(rows), mode="close")
    assert tr[0]["entry_idx"] == 9 and tr[0]["entry_px"] == 91.0 * (1 + SLIP) and tr[0]["exit_idx"] == 12


def test_stop_buffer_uses_the_signal_bars_atr():
    rows = base_rows()
    atr = np.full(len(rows), 1.0)
    atr[9:] = 20.0                                         # entry bar and later: very different ATR
    tr, _sg, _sk = sim(ind_from(rows, atr=atr))
    assert tr[0]["stop_px"] == pytest.approx(87.0 - 0.05 * 1.0)


def test_stop_includes_the_signal_bars_low():
    rows = base_rows()
    rows[8] = (89.5, 91.5, 86.5, 91.0)                     # the signal bar wicks to 86.5, below the earlier 87
    tr, _sg, _sk = sim(ind_from(rows))
    assert tr[0]["stop_px"] == pytest.approx(86.5 - 0.05)


def test_filter_is_read_up_to_the_signal_bar_only():
    rows = base_rows()
    ma = np.full(len(rows), 95.0)
    ma[9:] = 105.0                                         # filter turns off on the entry bar: the trade still happens
    tr, sg, _sk = sim(ind_from(rows, ma=ma))
    assert [s["signal_idx"] for s in sg] == [8] and tr[0]["entry_idx"] == 9


def test_first_target_is_the_signal_bars_upper_band():
    rows = base_rows()
    up = np.full(len(rows), 110.0)
    up[9:] = 91.0                                          # the entry bar's own band is below its open 91.3
    tr, _sg, sk = sim(ind_from(rows, upper=up))
    assert sk["target"] == 0 and tr[0]["entry_idx"] == 9   # the entry bar's target is up[8] = 110, not up[9]
    assert (tr[0]["exit_idx"], tr[0]["reason"], tr[0]["exit_px"]) == (10, "TP", 92.0)   # bar 10: limit up[9] = 91, opens 92


def test_trades_end_inside_their_period(monkeypatch):
    monkeypatch.setattr(R, "PERIODS", {"is": ("2021-02-01", "2021-03-15"), "oos": ("2021-03-15", "2021-04-20"),
                                       "pre": ("2020-02-01", "2020-04-15")})
    main = R.synth(32000, "5m", 40, start="2021-01-01", vol=0.0015)
    tr, _se, _sk = R.run_series(main, "5m", "BTCUSD", ["is", "oos"])
    end = tr["split"].map({k: pd.Timestamp(v[1]) for k, v in R.PERIODS.items()})
    assert (pd.to_datetime(tr["exit_ts"]) < end).all() and len(tr) > 50


# ------------------------------------------------------------------ sensitivities (reported, never judged)
def test_live_band_target_variant():
    rows = base_rows(6)
    upl = np.full(len(rows), 112.0)
    upl[11] = 104.0                                        # live touch level during bar 11
    rows[10] = (92.0, 109.0, 91.8, 108.0)                  # high 109: below both the live level 112 and the band 110
    rows[11] = (100.0, 104.5, 99.0, 103.0)                 # high 104.5 >= live level 104: TP at 104
    ind = ind_from(rows, up_live=upl, dn_live=np.full(len(rows), 88.0))
    tr, _sg, _sk = sim(ind, target="live")
    assert (tr[0]["exit_idx"], tr[0]["reason"], tr[0]["exit_px"]) == (11, "TP", 104.0)
    tr, _sg, _sk = sim(ind)                                # the test target (previous bar's band 110) is not touched
    assert tr[0]["reason"] != "TP" or tr[0]["exit_px"] == 110.0
    with pytest.raises(AssertionError):
        sim(ind_from(rows), target="live")                  # no live levels: refuses instead of guessing


def test_stop_buffer_and_cost_stress_variants():
    rows = base_rows()
    rows[12] = (92.0, 110.01, 91.8, 109.0)                 # touches 110 by 0.01 only (< 0.02% through)
    ind = ind_from(rows)
    P = R.Prep(ind, "SMA200", "CLOSE", "LONG")
    hi = len(rows) - 1
    base = R.simulate_sens(P, COST, 0, hi)[0][0]
    assert (base["reason"], base["exit_idx"], base["exit_px"]) == ("TP", 12, 110.0)
    buf = R.simulate_sens(P, COST, 0, hi, **R.SENS["buf03"])[0][0]
    assert buf["stop_px"] == pytest.approx(87.0 - 0.3)
    a = R.simulate_sens(P, COST, 0, hi, **R.SENS["cost_a"])[0][0]
    assert a["entry_px"] == 91.3 * (1 + 0.0005) and a["exit_px"] == 110.0      # limit target: no slippage
    b = R.simulate_sens(P, COST, 0, hi, **R.SENS["cost_b"])[0][0]
    assert b["reason"] != "TP" or b["exit_idx"] > 12      # a touch that does not trade 0.02% through is not filled
    rows[12] = (92.0, 110.03, 91.8, 109.0)                 # 0.027% through: filled at the limit
    b = R.simulate_sens(R.Prep(ind_from(rows), "SMA200", "CLOSE", "LONG"), COST, 0, hi, **R.SENS["cost_b"])[0][0]
    assert (b["reason"], b["exit_idx"], b["exit_px"]) == ("TP", 12, 110.0)
    # defaults equal the test: the sensitivity path with no settings is the same simulate call
    assert R.simulate_sens(P, COST, 0, hi)[0] == R.simulate(P, COST, 0, hi)[0]


def test_gross_raw_and_cost_split():
    rows = base_rows()
    rows[12] = (92.0, 110.5, 91.8, 109.0)
    t = sim(ind_from(rows))[0][0]
    assert t["gross_raw"] == pytest.approx(110.0 / 91.3 - 1)                   # before fee, slippage and funding
    assert t["gross"] == pytest.approx(110.0 / (91.3 * (1 + SLIP)) - 1)         # engine gross: after slippage
    rows[12] = (92.0, 92.5, 86.0, 90.0)                                         # stopped at 86.95
    t = sim(ind_from(rows))[0][0]
    assert t["reason"] == "SL" and t["gross_raw"] == pytest.approx(86.95 / 91.3 - 1)


# ------------------------------------------------------------------ mirrored short
def _mirror(rows):
    return [(200 - o, 200 - lo, 200 - h, 200 - c) for o, h, lo, c in rows]


def test_mirrored_short():
    rows = base_rows()
    rows[12] = (92.0, 110.5, 91.8, 109.0)
    mrows = _mirror(rows)                                   # bands 90/110 are symmetric around 100
    ind = ind_from(mrows, ma=105.0)                         # middle band 100 < MA 105: short filter on
    assert sim(ind, sides="LONG")[0] == []                  # long-only variant never shorts
    tr, sg, _sk = sim(ind, sides="BOTH")
    assert [s["side"] for s in sg] == [-1] and len(tr) == 1
    t = tr[0]
    entry = (200 - 91.3) * (1 - SLIP)
    assert (t["side"], t["signal_idx"], t["arm_idx"], t["entry_idx"], t["entry_px"]) == (-1, 8, 5, 9, entry)
    assert t["stop_px"] == pytest.approx(113.0 + 0.05)      # highest high of bars 5-8 plus 0.05 ATR
    assert (t["exit_idx"], t["reason"], t["exit_px"]) == (12, "TP", 90.0)   # lower band of the previous bar
    assert t["gross"] == pytest.approx(-(90.0 / entry - 1))
    # the long version of the same (unmirrored) path is identical in LONG and BOTH (short filter never on)
    ind_l = ind_from(rows)
    assert sim(ind_l, sides="LONG")[0] == sim(ind_l, sides="BOTH")[0]


def test_both_sides_filter_flip_hands_over_to_the_other_side():
    rows = [NEUTRAL] * 5 + [(91.0, 91.5, 88.0, 89.0)]       # 5 long breach (filter long)
    rows += [(109.0, 111.5, 108.8, 111.0)]                 # 6 filter flips short and the bar closes above the upper band
    rows += [(110.5, 110.8, 108.0, 108.5)]                 # 7 red, closes inside: short signal
    rows += [HOLD] * 3
    ma = np.full(len(rows), 95.0)
    ma[6:] = 105.0
    _t, sg, _s = sim(ind_from(rows, ma=ma), sides="BOTH", trade=False)
    assert [(s["signal_idx"], s["side"], s["arm_idx"]) for s in sg] == [(7, -1, 6)]


# ------------------------------------------------------------------ liquidation report
def test_liquidation_counts_per_leverage():
    mae = np.array([-0.01, -0.016, -0.03, -0.05])
    sl = np.array([0.005, 0.019, 0.03, 0.04])
    d = R.liq_stats(mae, sl)
    # liquidation distance 1/L - 0.5%: 20x 4.5%, 30x 2.83%, 40x 2.0%, 50x 1.5%
    assert (d["liq20_n"], d["liq30_n"], d["liq40_n"], d["liq50_n"]) == (1, 2, 2, 3)
    assert (d["slbeyond20_pct"], d["slbeyond30_pct"], d["slbeyond40_pct"], d["slbeyond50_pct"]) == (0.0, 50.0, 50.0, 75.0)
    assert d["sl_med_pct"] == pytest.approx(100 * np.median(sl))
    assert "maereach20_n" not in d and R.liq_stats(mae, sl, "", mae)["maereach50_n"] == 3


def _liq(t):
    return R.liq_stats(np.array([t["mae_held"]]), np.array([t["sl_dist"]]), "", np.array([t["mae"]]))


def test_liquidation_is_counted_only_before_the_stop_fill():
    o = np.array([100.0, 99.8, 99.0])
    h = np.array([100.3, 99.9, 99.5])
    lo_ = np.array([99.6, 97.0, 98.8])
    c = np.array([99.9, 98.0, 99.2])
    t = R.exit_trade(1, 0, 100.0, 99.0, 110.0, o, h, lo_, c, COST)   # stop 1% away, filled at 99 (no gap), wick to 97
    assert t["reason"] == "SL" and t["mae"] == pytest.approx(-0.03) and t["mae_held"] == pytest.approx(-0.01)
    d = _liq(t)
    assert (d["liq30_n"], d["liq40_n"], d["liq50_n"]) == (0, 0, 0)    # the stop fills before every liquidation level
    assert (d["maereach30_n"], d["maereach40_n"], d["maereach50_n"]) == (1, 1, 1)   # engine convention, for comparison
    o2 = o.copy()
    o2[1] = 97.6                                                       # gap: opens 2.4% down, through the stop
    t = R.exit_trade(1, 0, 100.0, 99.0, 110.0, o2, h, lo_, c, COST)
    assert t["mae_held"] == pytest.approx(-0.024)
    d = _liq(t)
    assert (d["liq20_n"], d["liq30_n"], d["liq40_n"], d["liq50_n"]) == (0, 0, 1, 1)
    # stop farther than the liquidation distance: price must cross the liquidation level first
    t = R.exit_trade(1, 0, 100.0, 97.5, 110.0, o, h, lo_, c, COST)   # stop 2.5%, 50x liq at 1.5%
    assert t["reason"] == "SL" and (_liq(t)["liq40_n"], _liq(t)["liq50_n"]) == (1, 1)
    # short mirror
    t = R.exit_trade(-1, 0, 100.0, 101.0, 90.0, 200 - o, 200 - lo_, 200 - h, 200 - c, COST)
    assert t["reason"] == "SL" and t["mae_held"] == pytest.approx(-0.01) and _liq(t)["liq50_n"] == 0


def test_liquidation_on_hand_built_bars():
    """Stats review example: stop 1.95% away, the exit bar opens above it and wicks 4% down: only 50x liquidates."""
    rows = base_rows(4)
    rows[10] = (90.0, 90.5, 87.0, 88.0)
    t = R.exit_trade(1, 9, 90.618, 88.85, 110.0, *(np.array(rows, float)[:, k] for k in range(4)), COST)
    assert t["reason"] == "SL" and t["sl_dist"] == pytest.approx(1 - 88.85 / 90.618)
    d = _liq(t)
    assert (d["liq30_n"], d["liq40_n"], d["liq50_n"]) == (0, 0, 1) and d["maereach30_n"] == 1


# ------------------------------------------------------------------ whole pipeline on synthetic series
def _pipeline(monkeypatch, mr, coins, seed0=40):
    monkeypatch.setattr(R, "PERIODS", {"is": ("2021-02-01", "2021-03-15"), "oos": ("2021-03-15", "2021-04-20"),
                                       "pre": ("2020-02-01", "2020-04-15")})
    tr, se, sk = [], [], []
    for i, coin in enumerate(coins):
        for tf, n, vol in (("5m", 32000, 0.0015), ("1h", 3200, 0.005)):
            main = R.synth(n, tf, seed0 + i, start="2021-01-01", vol=vol, mr=mr)
            pre = R.synth(n, tf, seed0 + 100 + i, start="2020-01-01", vol=vol, mr=mr)
            a = R.run_series(main, tf, coin, ["is", "oos"])
            b = R.run_series(pre, tf, coin, ["pre"])
            tr += [a[0], b[0]]
            se += [a[1], b[1]]
            sk += a[2] + b[2]
    tt = pd.concat(tr, ignore_index=True)
    ss = pd.concat(se, ignore_index=True)
    rows = []
    for tf in ("5m", "1h"):
        rows += R.extra_rows(tt[tt["tf"] == tf], ss[ss["tf"] == tf], [s for s in sk if s["tf"] == tf], 200)
    return tt, ss, R.finish(rows)


def test_pipeline_runs_end_to_end_and_reports(monkeypatch, tmp_path):
    tt, ss, t = _pipeline(monkeypatch, 0.0, R.COINS[:4])
    assert len(t) == 40 and t["is_h1"].sum() == 1
    assert set(tt["split"]) == {"is", "oos", "pre"} and set(tt["tf"]) == {"5m", "1h"}
    for col in ("net", "gross", "mae", "sl_dist", "r"):
        assert np.isfinite(tt[col].astype(float)).all(), col
    assert (tt["sl_dist"] > 0).all()
    for (_tf, _e, _s, _c), g in tt.groupby(["tf", "entry", "split", "symbol"]):
        g = g.sort_values("entry_ts")
        assert (g["arm_ts"].to_numpy()[1:] > g["exit_ts"].to_numpy()[:-1]).all()     # one position, no arming while held
    assert t["p12"].between(0, 1).all() and (t["candidate"] <= t["stage3"]).all()
    assert (t.loc[~t["tf"].isin(["5m", "1h"]), "n12"] == 0).all()                    # configs without data stay in N
    h1 = t[t["is_h1"]].iloc[0]
    assert h1["n12"] > 100 and "sens_close_mean12_pct" in t and h1["signals"] >= h1["n12"]
    assert h1["mean12_pct"] < 0                             # random walk: about minus the costs
    h1m = (tt["tf"] == "5m") & (tt["entry"] == R.H1[1])
    s = R.report(t, tt[h1m], ss[(ss["tf"] == "5m") & (ss["entry"] == R.H1[1])], str(tmp_path))
    assert s["configs"] == 40
    for f in ("results.csv", "near_miss.csv", "per_tf.csv", "per_variant.csv", "h1.json", "h1_trades.csv.gz",
              "h1_by_coin.csv", "h1_by_year.csv", "summary.json"):
        assert (tmp_path / f).exists(), f


def test_planted_mean_reversion_edge_passes_h1(monkeypatch):
    """Power check: on synthetic data with a planted mean-reverting component the H1 rule must pass."""
    _tt, _ss, t = _pipeline(monkeypatch, 4.0, R.COINS)
    h1 = t[t["is_h1"]].iloc[0]
    assert h1["mean12_pct"] > 0 and h1["pre_mean_pct"] > 0 and h1["p12"] < 0.05 and bool(h1["h1_pass"])

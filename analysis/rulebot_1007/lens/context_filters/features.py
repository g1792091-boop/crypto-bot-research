"""Pre-registered context buckets (written 2026-10-07 BEFORE any outcome-by-context number was computed).

Thresholds come from standard values (ADX 20/30) or from the outcome-blind pooled distribution of the feature
(peek_dist.py output: tertiles / round numbers), never from outcomes. Side-relative features are written from the
trade's point of view (s = +1 long, -1 short). The same file is imported by every analysis script.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ER_CUTS = {"15m": (0.055, 0.13), "30m": (0.065, 0.155), "1h": (0.065, 0.155)}
STOP_CUTS = {"15m": (0.50, 0.70), "30m": (0.74, 1.00), "1h": (1.0, 1.4)}

FEATURES = {
    # name: (description, buckets in order)
    "regime_s": ("own-tf regime, side-relative (trend_with = long in trend_up / short in trend_down)",
                 ["chop", "box", "mid", "trend_with", "trend_against"]),
    "htf_regime_s": ("higher-tf regime, side-relative", ["chop", "box", "mid", "trend_with", "trend_against"]),
    "er_t": ("efficiency ratio tertile (own tf, outcome-blind cuts)", ["low", "midER", "high"]),
    "adx_b": ("ADX14 <20 / 20-30 / >=30", ["lt20", "20to30", "ge30"]),
    "di_s": ("DI spread in trade direction (side*(DI+ - DI-) > 0)", ["with", "against"]),
    "ema_s": ("side * (close - EMA20)/ATR: < -0.5 fade/pullback, |x|<0.5 near, 0.5-1.5 with, >=1.5 extended",
              ["fade", "near", "with", "extended"]),
    "age_b": ("bars since close crossed EMA20: <=2 / 3-10 / >10", ["fresh", "mid", "old"]),
    "boxpos_s": ("position in the regime box from the trade's side (0 = cheapest edge): <0.2 / 0.2-0.8 / >0.8",
                 ["cheap_edge", "middle", "far_edge"]),
    "htfpos_s": ("same in the higher-tf box", ["cheap_edge", "middle", "far_edge"]),
    "rangepos_s": ("position in the N-bar high-low range from the trade's side", ["cheap_edge", "middle", "far_edge"]),
    "stop_t": ("2 ATR stop as % of price, tertile (cost share of the stop)", ["tight", "midstop", "wide"]),
    "room_b": ("S/R room ahead in ATR: <0.15 / 0.15-0.5 / >=0.5", ["blocked", "some", "open"]),
    "floor_b": ("S/R floor behind in ATR: <0.15 / 0.15-0.5 / >=0.5", ["near", "some", "far"]),
    "lbl": ("level_before_lock", ["yes", "no"]),
    "sbs": ("support_before_stop", ["yes", "no"]),
    "brk": ("signal bar broke a level in the trade direction", ["yes", "no"]),
    "session": ("KST hour of the bar close: asia 09-15, europe 16-21, us 22-03, late 04-08",
                ["asia", "europe", "us", "late"]),
    "coin": ("symbol", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT"]),
    "qtier": ("entry-quality tier from the recorded strength (levrule; core 36 only)", ["best", "good", "base"]),
    "consensus": ("signals of the same group, same coin/tf/bar/side: 1 / 2-3 / >=4", ["alone", "few", "many"]),
    "conflict": ("an opposite-side signal of the same group at the same coin/tf/bar", ["yes", "no"]),
    "side": ("direction (not a context: tracks the market's move in the run)", ["long", "short"]),
}
BINARY_ONE_TEST = {"di_s": "with", "lbl": "no", "sbs": "no", "brk": "yes", "conflict": "yes", "side": "long"}

# strategy-specific hypotheses (directional, written before results)
HYP = [
    # id, family, feature, bucket_hi, bucket_lo, expected sign of mean(hi) - mean(lo)
    ("H1_trend_highER", "trend", "er_t", "high", "low", +1),
    ("H2_revert_lowER", "revert", "er_t", "low", "high", +1),
    ("H3_revert_cheap_edge", "revert", "boxpos_s", "cheap_edge", "far_edge", +1),
    ("H4_trend_di_with", "trend", "di_s", "with", "against", +1),
    ("H5_trend_regime_with", "trend", "regime_s", "trend_with", "chop", +1),
    ("H6_revert_box_vs_chop", "revert", "regime_s", "box", "chop", +1),
    ("H7_all_tightstop_worse", "*", "stop_t", "wide", "tight", +1),   # positive control: cost share of the stop
]
PER_STRATEGY_FEATURES = [("er_t", "high", "low"), ("ema_s", "with", "fade"), ("boxpos_s", "cheap_edge", "far_edge")]


def _side_pos(pos, side):
    p = np.where(side > 0, pos, 1 - pos)
    return np.where(np.isnan(pos), np.nan, p)


def _cut3(x, lo, hi, names):
    out = np.where(x < lo, names[0], np.where(x < hi, names[1], names[2])).astype(object)
    out[np.isnan(x)] = None
    return out


def add_buckets(D: pd.DataFrame) -> pd.DataFrame:
    D = D.copy()
    s = D["side"].to_numpy()
    tf = D["timeframe"].to_numpy()

    def reg_s(col):
        r = D[col].astype(object).to_numpy()
        out = np.full(len(D), None, dtype=object)
        out[r == "chop"] = "chop"
        out[r == "box"] = "box"
        out[r == "unknown"] = "mid"
        out[(r == "trend_up") & (s > 0)] = "trend_with"
        out[(r == "trend_down") & (s < 0)] = "trend_with"
        out[(r == "trend_up") & (s < 0)] = "trend_against"
        out[(r == "trend_down") & (s > 0)] = "trend_against"
        return out

    D["regime_s"] = reg_s("regime")
    D["htf_regime_s"] = reg_s("htf_regime")
    er = D["er"].to_numpy(float)
    D["er_t"] = None
    D["stop_t"] = None
    for t, (a, b) in ER_CUTS.items():
        m = tf == t
        D.loc[m, "er_t"] = _cut3(er[m], a, b, ["low", "midER", "high"])
    sp = D["stop_pct"].to_numpy(float)
    for t, (a, b) in STOP_CUTS.items():
        m = tf == t
        D.loc[m, "stop_t"] = _cut3(sp[m], a, b, ["tight", "midstop", "wide"])
    D["adx_b"] = _cut3(D["adx"].to_numpy(float), 20, 30, ["lt20", "20to30", "ge30"])
    di = s * (D["di_plus"].to_numpy(float) - D["di_minus"].to_numpy(float))
    D["di_s"] = np.where(np.isnan(di), None, np.where(di > 0, "with", "against"))
    e = s * D["ema20_dist_atr"].to_numpy(float)
    D["ema_s"] = np.where(np.isnan(e), None, np.where(e < -0.5, "fade", np.where(e < 0.5, "near",
                                                                               np.where(e < 1.5, "with", "extended"))))
    D["age_b"] = _cut3(D["trend_age"].to_numpy(float), 2.5, 10.5, ["fresh", "mid", "old"])
    for src, dst in (("box_pos", "boxpos_s"), ("htf_box_pos", "htfpos_s"), ("range_pct", "rangepos_s")):
        p = _side_pos(D[src].to_numpy(float), s)
        D[dst] = _cut3(p, 0.2, 0.8, ["cheap_edge", "middle", "far_edge"])
    D["room_b"] = _cut3(D["sr_room"].to_numpy(float), 0.15, 0.5, ["blocked", "some", "open"])
    D["floor_b"] = _cut3(D["sr_floor"].to_numpy(float), 0.15, 0.5, ["near", "some", "far"])
    for src, dst in (("sr_level_before_lock", "lbl"), ("sr_support_before_stop", "sbs"), ("sr_breakout", "brk")):
        v = D[src].to_numpy(float)
        D[dst] = np.where(np.isnan(v), None, np.where(v > 0.5, "yes", "no"))
    h = D["kst_hour"].to_numpy()
    D["session"] = np.where((h >= 9) & (h <= 15), "asia", np.where((h >= 16) & (h <= 21), "europe",
                                                                 np.where((h >= 22) | (h <= 3), "us", "late")))
    D["coin"] = D["symbol"]
    D["qtier"] = np.where(D["kind"] == "strategy", D["q_tier"], None)
    n = D["n_same"].to_numpy()
    D["consensus"] = np.where(n <= 1, "alone", np.where(n <= 3, "few", "many"))
    D["conflict"] = np.where(D["n_opp"].to_numpy() > 0, "yes", "no")
    D["side_b"] = np.where(s > 0, "long", "short")
    D["side"] = D["side"].astype(int)
    D = D.rename(columns={"side_b": "side_bucket"})
    return D


def bucket_col(feature: str) -> str:
    return "side_bucket" if feature == "side" else feature


def contrasts():
    """[(feature, bucket)]: every bucket vs the rest; a binary feature once."""
    out = []
    for f, (_, bs) in FEATURES.items():
        if f in BINARY_ONE_TEST:
            out.append((f, BINARY_ONE_TEST[f]))
        else:
            out += [(f, b) for b in bs]
    return out

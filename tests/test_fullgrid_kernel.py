"""research/fullgrid/kernel.py must give the paper engine's trades exactly: the same signals replayed through
paperbot.engine.PaperEngine (v3_settings, as paperbot/paramshadow.py replays the live account) and through the numba
kernel, one trade alone and one account over two coins."""

from __future__ import annotations

import importlib.util
import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
pytest.importorskip("numba")

from paperbot.config import V3_STOP_ATR, v3_settings  # noqa: E402
from paperbot.engine import PaperEngine  # noqa: E402
from paperbot.margin import Brackets, BracketTier  # noqa: E402
from paperbot.models import Bar, Signal  # noqa: E402


def _load(name):
    spec = importlib.util.spec_from_file_location(f"fullgrid_{name}", os.path.join(ROOT, "research", "fullgrid", f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


K = _load("kernel")
MIN = 60_000
T0 = 1_704_067_200_000          # 2024-01-01 00:00 UTC
REASON = {"SL": K.R_SL, "LOCK": K.R_LOCK, "LIQ": K.R_LIQ}
WIDE = Brackets([BracketTier(300_000, 125, 0.004, 0.0), BracketTier(800_000, 100, 0.005, 300.0),
                 BracketTier(3_000_000, 50, 0.01, 4_300.0), BracketTier(1e12, 20, 0.025, 49_300.0)])
SPEC = {"qty_step": 0.001, "min_notional": 5.0}


def synth_1m(n, seed, price=40_000.0, drop=()):
    """1m bars with jumps (gaps through stops), mark spikes (liquidation without the stop) and 8 h funding."""
    rng = np.random.default_rng(seed)
    r = rng.normal(0, 0.0012, n)
    jump = rng.random(n) < 0.002
    r[jump] += rng.normal(0, 0.03, jump.sum())
    c = price * np.exp(np.cumsum(r))
    o = np.r_[price, c[:-1]] * np.exp(np.where(rng.random(n) < 0.003, rng.normal(0, 0.01, n), 0.0))
    hi = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.0008, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.0008, n)))
    mo = o * (1 + rng.normal(0, 0.0002, n))
    mh = np.maximum(hi * (1 + np.where(rng.random(n) < 0.002, 0.02, 0.0)), mo)
    ml = np.minimum(lo * (1 - np.where(rng.random(n) < 0.002, 0.02, 0.0)), mo)
    ts = T0 + np.arange(n, dtype=np.int64) * MIN
    fund = np.where((ts % (8 * 3_600_000)) == 0, rng.choice([-1, 1], n) * rng.uniform(1e-5, 2e-3, n), 0.0)
    keep = np.ones(n, bool)
    keep[list(drop)] = False
    d = dict(ts=ts, o=o, h=hi, l=lo, c=c, mo=mo, mh=mh, ml=ml, mc=c, fund=fund)
    return {k: v[keep] for k, v in d.items()}


def bars_at(data: dict, sym: str, j: int) -> Bar:
    t = int(data["ts"][j])
    return Bar(sym, t, t + MIN - 1, float(data["o"][j]), float(data["h"][j]), float(data["l"][j]), float(data["c"][j]),
               mark_open=float(data["mo"][j]), mark_high=float(data["mh"][j]), mark_low=float(data["ml"][j]),
               mark_close=float(data["mc"][j]))


def signal(sym, close, side, atr, best):
    return Signal(ts=int(close) - 1, symbol=sym, timeframe="15m", strategy_id="S2_ST_ROC", side=side, stop_price=0.0,
                  tier="best", atr=atr, meta={"stop_dist": V3_STOP_ATR * atr, "lev_group": "best" if best else "normal"})


def replay(datas: dict, sigs: list, brackets: dict, equity=None):
    """paramshadow.replay_day on the union of minutes: stamp ref price, step, then submit the signals whose bar closed."""
    s = v3_settings() if equity is None else v3_settings(initial_equity=equity)
    e = PaperEngine(s, brackets, symbol_specs={k: SPEC for k in datas})
    minutes = np.unique(np.concatenate([d["ts"] for d in datas.values()]))
    idx = {k: {int(t): j for j, t in enumerate(d["ts"])} for k, d in datas.items()}
    sigs = sorted(sigs, key=lambda x: x[1])
    k = 0
    for t in minutes:
        t = int(t)
        bars = {sym: bars_at(datas[sym], sym, idx[sym][t]) for sym in datas if t in idx[sym]}
        fund = {sym: float(datas[sym]["fund"][idx[sym][t]]) for sym in bars if datas[sym]["fund"][idx[sym][t]] != 0}
        for sig in e.pending:
            b = bars.get(sig.symbol)
            if b is not None and "ref_price" not in sig.meta:
                sig.meta["ref_price"] = float(b.open)
        e.step(bars, fund or None)
        while k < len(sigs) and sigs[k][1] <= t + MIN:
            sym, close, side, atr, best = sigs[k]
            e.submit(signal(sym, close, side, atr, best))
            k += 1
    return e


def kernel_alone(data, close, side, atr, best, br, equity=5000.0):
    S = K.settings_vector()
    pnl, ex, rs, lv = K.outcomes(S, K.bracket_arrays(br), data["ts"], data["o"], data["h"], data["l"], data["mo"],
                                 data["mh"], data["ml"], data["fund"], np.array([close], np.int64),
                                 np.array([atr]), np.array([best]), np.array([best]), equity, SPEC["qty_step"],
                                 SPEC["min_notional"], V3_STOP_ATR)
    k = 0 if side > 0 else 1
    return pnl[0, k], int(ex[0, k]), int(rs[0, k]), int(lv[0, k])


@pytest.mark.parametrize("br_name", ["wide", "example"])
def test_one_trade_matches_engine(br_name):
    br = WIDE if br_name == "wide" else Brackets.example()
    data = synth_1m(30_000, seed=7)
    rng = np.random.default_rng(11)
    seen = {}
    n = 0
    for _ in range(160):
        close = int(T0 + rng.integers(5, 1900) * 15 * MIN)
        side = int(rng.choice([1, -1]))
        atr = float(data["c"][(close - T0) // MIN] * rng.uniform(0.0008, 0.012))
        best = bool(rng.random() < 0.5)
        d, x, r, lev = kernel_alone(data, close, side, atr, best, br)
        e = replay({"BTCUSDT": data}, [("BTCUSDT", close, side, atr, best)], {"BTCUSDT": br})
        if r == K.R_REJECT:
            assert not e.trades and any(o.status == "REJECTED" for o in e.outcomes)
            seen["REJECTED"] = seen.get("REJECTED", 0) + 1
            continue
        if r == K.R_OPEN:
            assert not e.trades
            continue
        assert len(e.trades) == 1, (close, side, atr, best)
        t = e.trades[0]
        assert t.exit_time // MIN * MIN == int(data["ts"][x])
        assert REASON[t.exit_reason] == r
        assert t.leverage == lev
        assert abs(t.pnl / 5000.0 - d) < 1e-12, (t.pnl, d * 5000)
        assert abs(e.wallet - 5000.0 - d * 5000.0) < 1e-6
        seen[t.exit_reason] = seen.get(t.exit_reason, 0) + 1
        n += 1
    assert n >= 100
    assert seen.get("SL") and seen.get("LOCK"), seen
    if br_name == "wide":
        assert seen.get("LIQ"), seen       # the synthetic mark spikes and gaps do liquidate some


def test_missing_minutes_and_gap_fill():
    """A missing entry minute: the signal fills at the next minute the coin has (replay_day's rule)."""
    data = synth_1m(6_000, seed=3, drop=range(900, 905))
    close = T0 + 900 * MIN                         # the minutes 900..904 are missing
    for side in (1, -1):
        d, x, r, lev = kernel_alone(data, close, side, 200.0, False, WIDE)
        e = replay({"BTCUSDT": data}, [("BTCUSDT", close, side, 200.0, False)], {"BTCUSDT": WIDE})
        if r in (K.R_SL, K.R_LOCK, K.R_LIQ):
            t = e.trades[0]
            assert t.entry_time == T0 + 905 * MIN
            assert abs(t.pnl / 5000.0 - d) < 1e-12


def test_account_two_coins_matches_engine():
    a = synth_1m(40_000, seed=21, drop=range(5000, 5003))
    b = synth_1m(40_000, seed=22, price=2_000.0)
    datas = {"BTCUSDT": a, "ETHUSDT": b}
    br = {"BTCUSDT": WIDE, "ETHUSDT": WIDE}
    rng = np.random.default_rng(5)
    sigs = []
    for i in range(700):
        close = int(T0 + rng.integers(4, 2600) * 15 * MIN)
        sym = "BTCUSDT" if rng.random() < 0.5 else "ETHUSDT"
        d = datas[sym]
        j = min(np.searchsorted(d["ts"], close), len(d["ts"]) - 1)
        sigs.append((sym, close, int(rng.choice([1, -1])), float(d["c"][j] * rng.uniform(0.001, 0.01)),
                     bool(rng.random() < 0.3)))
    sigs = sorted(set(sigs), key=lambda s: (s[1], s[0] != "BTCUSDT"))
    e = replay(datas, sigs, br)
    # kernel: concatenated arrays, signals sorted by (entry minute, coin priority)
    syms = ["BTCUSDT", "ETHUSDT"]
    cat = {k: np.concatenate([datas[s][k] for s in syms]) for k in ("ts", "o", "h", "l", "mo", "mh", "ml", "fund")}
    starts = np.array([0, len(a["ts"])], np.int64)
    ends = np.array([len(a["ts"]), len(a["ts"]) + len(b["ts"])], np.int64)

    def entry_minute(s):
        d = datas[s[0]]
        j0 = np.searchsorted(d["ts"], s[1] - MIN)
        return int(d["ts"][j0 + 1]) if j0 + 1 < len(d["ts"]) else 2 ** 62
    order = sorted(sigs, key=lambda s: (entry_minute(s), syms.index(s[0])))
    st, pnl, ext, rs, lv, wallet = K.account(
        K.settings_vector(), np.stack([K.bracket_arrays(WIDE)] * 2), cat["ts"], cat["o"], cat["h"], cat["l"],
        cat["mo"], cat["mh"], cat["ml"], cat["fund"], starts, ends,
        np.array([syms.index(s[0]) for s in order], np.int64), np.array([s[1] for s in order], np.int64),
        np.array([s[2] for s in order], np.int64), np.array([s[3] for s in order]), np.array([s[4] for s in order]),
        np.array([SPEC["qty_step"]] * 2), np.array([SPEC["min_notional"]] * 2), V3_STOP_ATR)
    got = [(order[q][0], int(order[q][1]), int(ext[q] // MIN), round(float(pnl[q]), 6)) for q in np.flatnonzero(st == 1)
           if rs[q] != K.R_OPEN]
    want = [(t.symbol, int(t.signal_ts) + 1, int(t.exit_time // MIN), round(float(t.pnl), 6)) for t in e.trades]
    assert len(want) >= 40
    assert got == want
    assert abs(wallet - e.wallet) < 1e-6 or e.position is not None


def test_settings_vector_is_the_live_rule():
    S = K.settings_vector()
    s = v3_settings()
    assert S[0] == s.taker_fee and S[1] == s.slippage_frac and S[2] == s.max_loss_frac
    assert list(S[11:19]) == [0.5, 50, 0.4, 40, 0.3, 30, 0.2, 20]
    assert S[9] == 10.0 and S[10] == 5000.0

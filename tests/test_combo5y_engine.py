"""paperbot/dash/tools/combo5y.py against the real research engine on synthetic bars: the v4 sizing shim (each signal's
own leverage group reaches research/paper_rules/rules_bt.simulate through the (side, fill, atr) key, rules_bt itself
unchanged and restored), the dollar P&L per trade adding up to the account, the "normal" sizer of the merged rules, and
the trial keys (every family counted, MTF only from a lower to a higher timeframe)."""
from __future__ import annotations

import numpy as np
import pytest

from paperbot.dash.tools import combo5y as G
from paperbot.dash.tools import combo5y_core as K


class _Lib:
    @staticmethod
    def tf_minutes(tf):
        return {"15m": 15, "30m": 30, "1h": 60, "4h": 240}[tf]

    @staticmethod
    def warmup_bars(tf):
        return 0


def _bars(n=1200, seed=3, atr_frac=0.002):
    rng = np.random.default_rng(seed)
    RB = G._rb()
    out = {}
    for ci, c in enumerate(RB.COINS):
        ts = (np.arange(n, dtype=np.int64) * 900 + 1_630_000_000 + ci) * 1_000_000_000
        cl = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
        o = np.concatenate(([100.0], cl[:-1]))
        hi = np.maximum(o, cl) * (1 + np.abs(rng.normal(0, 0.001, n)))
        lo = np.minimum(o, cl) * (1 - np.abs(rng.normal(0, 0.001, n)))
        out[c] = dict(ts=ts, o=o, h=hi, l=lo, c=cl, atr=cl * atr_frac * (1 + 0.1 * rng.random(n)))
    return out


def _signals(bars, seed=5, p=0.02):
    rng = np.random.default_rng(seed)
    sg = {}
    for c, b in bars.items():
        n = len(b["ts"])
        x = np.where(rng.random(n) < p, np.where(rng.random(n) < 0.5, 1, -1), 0).astype(np.int8)
        x[-2:] = 0
        sg[c] = x
    return sg


def test_v4_sizing_reaches_rules_bt_with_each_signals_own_group():
    RB = G._rb()
    bars = _bars()
    sg = _signals(bars)
    book = G.GroupBook(RB.SETTINGS.slippage_frac)
    best_of = {}
    rng = np.random.default_rng(9)
    for c in RB.COINS:
        idx = np.flatnonzero(sg[c])
        best = rng.random(len(idx)) < 0.5
        book.add(bars[c], c, idx, sg[c][idx], best)
        best_of.update({(c, int(i)): bool(b) for i, b in zip(idx, best)})
    real_size, real_init = RB.size_position, RB.INITIAL
    bounds = {c: (50, len(bars[c]["ts"])) for c in RB.COINS}
    with G.v4_rules(RB, book):
        r = RB.simulate(bars, sg, bounds, 2.0, "15m", _Lib(), keep_trades=True)
    assert RB.size_position is real_size and RB.INITIAL == real_init          # rules_bt left as it was
    tt = r["trade_table"]
    assert len(tt) > 10 and book.miss == 0 and book.collide == 0
    levs_best, levs_normal = set(), set()
    for _, t in tt.iterrows():
        (levs_best if best_of[(RB.COINS[int(t["coin"])], int(t["i"]))] else levs_normal).add(int(t["lev"]))
    assert levs_normal and levs_normal <= {30, 20}                           # "normal": 30x / 30%, then 20x
    assert levs_best and max(levs_best) >= 40                                 # "best" tries 50x / 50% first
    # the dollar P&L of the trades adds up to the account (and starts from the v4 $5,000)
    pnl = K.trade_pnl(tt["R"].to_numpy(float), tt["margin_frac"].to_numpy(float), G.INITIAL)
    assert pnl.sum() == pytest.approx(r["final"] - G.INITIAL, rel=1e-9, abs=1e-6)


def test_shim_is_restored_after_an_error():
    RB = G._rb()
    real_size, real_init = RB.size_position, RB.INITIAL
    with pytest.raises(RuntimeError):
        with G.v4_rules(RB, lambda *a: "normal", initial=123.0):
            assert RB.INITIAL == 123.0
            raise RuntimeError("boom")
    assert RB.size_position is real_size and RB.INITIAL == real_init


def test_coin_flip_book_draws_with_levrule():
    from paperbot.levrule import coin_flip_best
    RB = G._rb()
    bars = _bars(n=300)
    sg = _signals(bars, p=0.05)
    book = G.GroupBook(RB.SETTINGS.slippage_frac, flip=(2, "15m"))
    c = RB.COINS[0]
    idx = np.flatnonzero(sg[c])
    book.add(bars[c], c, idx, sg[c][idx], None)
    i = int(idx[0])
    side = int(sg[c][i])
    fill = float(bars[c]["o"][i + 1] * (1 + side * RB.SETTINGS.slippage_frac))
    g = book(side, fill, float(bars[c]["atr"][i]))
    close = int(bars[c]["ts"][i] // 1_000_000) + K.TF_MS["15m"]
    assert g == ("best" if coin_flip_best(2, "15m", c + "T", close) else "normal")
    assert book("x", 1.0, 2.0) == "normal" and book.miss == 1               # unknown key: normal, counted


def test_normal_sizer():
    RB = G._rb()
    sz = G.normal_sizer(RB)
    lev, liq = sz(1, 0.002)
    assert lev == 30 and 0 < liq < 1 / 30
    assert sz(-1, 0.002)[0] == 30
    lev, liq = sz(1, 0.2)                     # a 40% stop cannot be sized at 20x or 30x
    assert lev == 0 and np.isnan(liq)


def test_trial_keys_count_every_family():
    names = [f"S{i}" for i in range(5)]
    keys = G.trial_keys(names)
    fam = {}
    for k in keys:
        fam[k.split("|")[0]] = fam.get(k.split("|")[0], 0) + 1
    assert fam["AND"] == 10 * len(G.AND_K) * len(G.TFS)
    assert fam["FILTER"] == 20 * len(G.FILTER_N) * len(G.TFS)
    assert fam["VOTE"] == len(G.VOTE_K) * len(G.TFS)
    assert fam["MTF"] == 5 * len(G.MTF_PAIRS) * len(G.MTF_AGE)
    order = {tf: i for i, tf in enumerate(G.TFS)}
    assert all(order[lo] < order[hi] for lo, hi in G.MTF_PAIRS)
    assert len(set(keys)) == len(keys)
    assert G._tfs_of("MTF|S1|15m|4h|state") == ("15m", "4h") and G._tfs_of("AND|S1|S2|0|1h") == ("1h",)

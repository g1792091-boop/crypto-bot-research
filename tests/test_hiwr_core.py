"""research/hiwr walk.py and acct.py against independent references (PREREG_HIWR.md 17.1 tests): the exit-event
tables against a plain per-minute loop written from section 7; the maker TP against kernel._trade with a TP_R limit
at the same price; the liquidation price against kernel._liq; the weekend mask at its boundaries; the stop-inside-TP
skip, the stop room and the bracket cut; the account's busy rule; the 1m mark-to-market drawdown on synthetic paths
(exit-minute rule, peak before the minute, realized <= mark-to-market, sizes fall as the drawdown rises); the week-block
bootstrap against a slow per-path loop. Synthetic prices only."""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
pytest.importorskip("numba")

from research.hiwr import acct as A  # noqa: E402
from research.hiwr import data as D  # noqa: E402
from research.hiwr import walk as W  # noqa: E402

R = D.fg_run()
K = W.K
MIN = 60_000
T0 = 1_609_459_200_000            # 2021-01-01 00:00 UTC (a Friday)
CX = A.exchange30()
BTC = CX["BTCUSDT"]
SAND = CX["SANDUSDT"]


def synth(n, seed, price=100.0, drop=(), gap_p=0.004, gap_sd=0.01, vol=0.0012, spike_p=0.003):
    """1m bars with jumps, gapped opens (through stops and take-profits), mark spikes (liquidation without the stop),
    8 h funding and optional missing minutes."""
    rng = np.random.default_rng(seed)
    r = rng.normal(0, vol, n)
    jump = rng.random(n) < 0.002
    r[jump] += rng.normal(0, 0.03, jump.sum())
    c = price * np.exp(np.cumsum(r))
    o = np.r_[price, c[:-1]] * np.exp(np.where(rng.random(n) < gap_p, rng.normal(0, gap_sd, n), 0.0))
    hi = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.0008, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.0008, n)))
    mo = o * (1 + rng.normal(0, 0.0002, n))
    mh = np.maximum(hi * (1 + np.where(rng.random(n) < spike_p, 0.025, 0.0)), mo)
    ml = np.minimum(lo * (1 - np.where(rng.random(n) < spike_p, 0.025, 0.0)), mo)
    ts = T0 + np.arange(n, dtype=np.int64) * MIN
    fund = np.where((ts % (8 * 3_600_000)) == 0, rng.choice([-1, 1], n) * rng.uniform(1e-5, 2e-3, n), 0.0)
    keep = np.ones(n, bool)
    keep[list(drop)] = False
    d = dict(ts=ts, o=o, h=hi, l=lo, c=c, v=np.ones(n), qv=c.copy(), mo=mo, mh=mh, ml=ml, mc=c, fund=fund)
    return {k: v[keep] for k, v in d.items()}


def tables(arr, tf="1h", coin_end=False, br=None, end_ms=None, warmup=30, cfgs=None):
    df, close = D.build_frame(arr, tf)
    atr = R._vendor_fg().atr(df, 14).to_numpy(float)
    end_ms = int(arr["ts"][-1]) + MIN if end_ms is None else end_ms
    T = W.build_tables(arr, close, atr, (T0, end_ms), coin_end, BTC["br"] if br is None else br, cfgs=cfgs,
                       warmup=warmup)
    return T, df, close, atr


# ------------------------------------------------------------------ an independent per-minute loop (section 7)
def ref_trade(a, e, end, coin_end, side, P0, Dst, t, fill, L, liq_d, cm=1, pierce=0.0):
    slip, tk, mk = 0.0002 * cm, 0.0005 * cm, 0.0002 * cm
    F = P0 * (1 + side * slip)
    S = P0 - side * Dst
    T = F * (1 + side * t)
    Tp = T * (1 + side * pierce)
    Lq = F * (1 - side * liq_d)
    paid = 0.0

    def done(kind, j, X, fee):
        g = side * (X / F - 1)
        if g < -1.0 / L:
            return "LIQ", j, -1.0 / L - tk - paid          # the margin, the entry fee and the funding paid (7.5)
        return kind, j, g - tk - fee * X / F - paid

    for j in range(e, end):
        if j > e:
            paid += side * a["mo"][j] * a["fund"][j] / F
            if side * (a["mo"][j] - Lq) <= 0:
                return "LIQ", j, -1.0 / L - tk - paid
            if side * (a["o"][j] - S) <= 0:
                return done("SL", j, a["o"][j] * (1 - side * slip), tk)
            if fill == 0 and side * (a["o"][j] - T) >= 0:
                return done("TP", j, a["o"][j] * (1 - side * slip), tk)
            if fill == 1 and side * (a["o"][j] - Tp) > 0:
                return done("TP", j, T, mk)
        if (a["l"][j] <= S) if side > 0 else (a["h"][j] >= S):
            return done("SL", j, S * (1 - side * slip), tk)
        if (a["ml"][j] <= Lq) if side > 0 else (a["mh"][j] >= Lq):
            return "LIQ", j, -1.0 / L - tk - paid
        if fill == 0 and ((a["h"][j] >= T) if side > 0 else (a["l"][j] <= T)):
            return done("TP", j, T * (1 - side * slip), tk)
        if fill == 1 and ((a["h"][j] > Tp) if side > 0 else (a["l"][j] < Tp)):
            return done("TP", j, T, mk)
    if coin_end:
        return done("END", end - 1, a["c"][end - 1] * (1 - side * slip), tk)
    return "OPEN", -1, float("nan")


KIND = {W.X_STOP: "SL", W.X_TP: "TP", W.X_LIQ: "LIQ", W.X_COIN_END: "END", W.X_OPEN: "OPEN"}


@pytest.mark.parametrize("coin_end", [False, True])
def test_walk_matches_an_independent_minute_loop(coin_end):
    a = synth(16_000, 3 if coin_end else 4, drop=range(5000, 5090), vol=0.0006, gap_sd=0.006)
    T, _df, _c, _atr = tables(a, "15m", coin_end=coin_end,
                              end_ms=int(a["ts"][-1]) + (MIN if coin_end else 10 * 86_400_000))
    cfgs = W.exit_configs()
    rng = np.random.default_rng(11)
    seen = {}
    n_cmp = 0
    for _ in range(3000):
        row = int(rng.integers(len(T.bars)))
        s = int(rng.integers(2))
        cfg = cfgs[int(rng.integers(len(cfgs)))]
        x = W.trade_list(T, [row], [s], cfg)
        e = int(T.ent[row])
        side = 1 if s == 0 else -1
        if e < 0:
            assert x["skip"][0] == 4
            continue
        P0 = a["o"][e]
        Dst = W.stop_distance(cfg["k"], T.atr[row], P0)
        F = P0 * (1 + side * W.SLIP)
        sd = side * (F - (P0 - side * Dst)) / F
        liq_d = T.liqd[s, cfg["Li"]]
        if sd + max(0.002, T.atr[row] / F) > liq_d:
            assert x["skip"][0] == 1
            seen["room"] = seen.get("room", 0) + 1
            continue
        if sd <= cfg["t"]:
            assert x["skip"][0] == 2
            seen["inside"] = seen.get("inside", 0) + 1
            continue
        for cm, key in ((1, "r"), (2, "r2")):
            kind, j, r = ref_trade(a, e, T.end, coin_end, side, P0, Dst, cfg["t"], cfg["fill"], cfg["L"], liq_d, cm)
            if cm == 1:
                seen[kind] = seen.get(kind, 0) + 1
                if kind == "OPEN":
                    assert x["skip"][0] == 3
                    break
                assert x["skip"][0] == 0
                assert KIND[int(x["kind"][0])] == kind
                assert int(x["code"][0]) // 8 == j
                assert x["exit_ms"][0] == a["ts"][j]
            if kind == "OPEN":
                assert np.isnan(x[key][0])
            else:
                assert abs(x[key][0] - r) < 1e-12, (cfg, cm, kind, x[key][0], r)
            n_cmp += 1
    assert n_cmp > 800
    for k in ("SL", "TP", "room", "inside"):
        assert seen.get(k, 0) > 0, seen
    assert seen.get("LIQ", 0) > 0, seen
    if coin_end:
        assert seen.get("END", 0) > 0, seen
    else:
        assert seen.get("OPEN", 0) > 0, seen


def test_pair_sums_equal_the_trade_lists():
    a = synth(12_000, 5)
    T, *_ = tables(a)
    cfgs = W.exit_configs()
    tt, tm, _ti = W.tp_sets(cfgs)
    ca = W.cfg_arrays(cfgs, tt, tm)
    rng = np.random.default_rng(2)
    rows = rng.integers(0, len(T.bars), 150)
    sides = rng.integers(0, 2, 150)
    S = W.pair_sums(T, rows, sides, ca)
    for ci in range(0, len(cfgs), 7):
        x = W.trade_list(T, rows, sides, cfgs[ci])
        ok = x["skip"] == 0
        assert S[ci, W.S_N] == ok.sum()
        assert abs(S[ci, W.S_SUM] - x["r"][ok].sum()) < 1e-12
        assert S[ci, W.S_WIN] == (x["r"][ok] > 0).sum()
        assert abs(S[ci, W.S_SUM2] - np.nansum(x["r2"][ok])) < 1e-12
        assert abs(S[ci, W.S_SUMR] - (x["r"][ok] / x["oneR"][ok]).sum()) < 1e-9
        assert S[ci, W.S_ROOM] == (x["skip"] == 1).sum() and S[ci, W.S_INSIDE] == (x["skip"] == 2).sum()
        assert S[ci, W.S_OPEN] == (x["skip"] == 3).sum()


def test_tp_prices_are_the_net_reading():
    cfgs = W.exit_configs()
    assert len(cfgs) == 162
    got = {(c["L"], c["step"], c["fill_name"]): round(c["t"] * 100, 6) for c in cfgs if c["k"] == 0}
    want = {30: ((0.44, 0.49, 0.54), (0.39, 0.44, 0.49)), 40: ((0.44, 0.4775, 0.515), (0.39, 0.4275, 0.465)),
            50: ((0.44, 0.47, 0.50), (0.39, 0.42, 0.45))}            # PREREG_HIWR 2.1 table
    for L, (tk_, mk_) in want.items():
        for st in range(3):
            assert got[(L, st, "taker")] == tk_[st] and got[(L, st, "maker")] == mk_[st]
    assert [c["t"] for c in W.exit_configs("gross") if c["k"] == 0 and c["fill"] == 0 and c["L"] == 30] == \
        [0.003, 0.0035, 0.004]
    assert W.exit_label(cfgs[1]) == "L30|TP0.39|1ATR|maker"
    order = [(c["Li"], c["step"], c["k"], c["fill"]) for c in cfgs]
    assert order == sorted(order)                                     # 10.5 tie order


# ------------------------------------------------------------------ the kernel
def test_maker_tp_matches_kernel_trade_with_a_limit_at_the_same_price():
    S = K.settings_vector()
    assert (S[0], S[1], S[19]) == (W.TAKER, W.SLIP, W.MAKER)
    a = synth(20_000, 8, gap_p=0.01, gap_sd=0.006)
    T, *_ = tables(a)
    br = BTC["br"]
    cfgs = [c for c in W.exit_configs() if c["fill"] == 1 and c["L"] == 30]
    n_same = n_gap = 0
    for row in range(len(T.bars)):
        e = int(T.ent[row])
        if e < 0:
            continue
        for s in (0, 1):
            side = 1 if s == 0 else -1
            for cfg in cfgs[::2]:
                raw = a["o"][e]
                dist = W.stop_distance(cfg["k"], T.atr[row], raw)
                F = raw * (1 + side * W.SLIP)
                tp = F * (1 + side * cfg["t"])
                tpv = (tp - raw) * side / dist
                d, xi, rs, lev = K._trade(S, br, a["o"], a["h"], a["l"], a["mo"], a["mh"], a["ml"], a["fund"], e,
                                          T.end, side, dist, T.atr[row], False, 5000.0, BTC["qty_step"],
                                          BTC["min_notional"], K.TP_R, tpv, False, 0.1, 0.05, 0.02, np.nan)
                if rs in (K.R_REJECT, K.R_OPEN, K.R_LIQ) or lev != 30:
                    continue
                ok, _lev, _m, qty, _liq = K._size(S, br, 5000.0, side, F, raw - side * dist, T.atr[row], False,
                                                  BTC["qty_step"], BTC["min_notional"])
                rk = d / (qty * F)
                x = W.trade_list(T, [row], [s], cfg)
                if x["skip"][0] != 0 or x["kind"][0] == W.X_LIQ:
                    continue                 # the kernel takes trades the study skips (its own buffer and tiers)
                assert int(x["code"][0]) // 8 == xi
                assert (x["kind"][0] == W.X_TP) == (rs == K.R_TP)
                ph = int(x["code"][0]) % 8
                if rs == K.R_TP and ph == W.PH_OPEN_TP:
                    # a minute that opens beyond T: the kernel fills at that open, hiwr at T (7.2)
                    n_gap += 1
                    Xk = a["o"][xi]
                    assert abs((rk - x["r"][0]) - (side - W.MAKER) * (Xk - tp) / F) < 1e-12
                    assert side * (Xk - tp) > 0
                else:
                    n_same += 1
                    assert abs(rk - x["r"][0]) < 1e-12
    assert n_same > 200 and n_gap > 0, (n_same, n_gap)


def test_liquidation_price_is_kernel_liq():
    for sym in ("BTCUSDT", "SOLUSDT", "TRBUSDT", "SANDUSDT", "TOMOUSDT"):
        br = CX[sym]["br"]
        d = W.first_tier_liqd(br)
        mmr = br[0, 2]
        for Li, L in enumerate(W.LEVS):
            if br[0, 1] < L:
                assert d[0, Li] == 0.0
                continue
            assert abs(d[0, Li] - (1 - (1 - 1 / L) / (1 - mmr))) < 1e-12
            assert abs(d[1, Li] - ((1 + 1 / L) / (1 + mmr) - 1)) < 1e-12
            for side, s in ((1, 0), (-1, 1)):
                for F, N in ((100.0, 1000.0), (0.3, 4000.0)):
                    lp = W.liq_price(side, F, N, L, br[0, 2], br[0, 3])
                    assert lp == K._liq(side, N / F, F, N / L, br[0, 2], br[0, 3])
                    assert abs(lp - F * (1 - side * d[s, Li])) < 1e-9 * F
    # PREREG 4 table (long, first tier): BTC 0.4% 2.95/2.11/1.61; TRB 1.5% 1.86/1.02/0.51
    assert [round(x * 100, 2) for x in W.first_tier_liqd(BTC["br"])[0]] == [2.95, 2.11, 1.61]
    assert [round(x * 100, 2) for x in W.first_tier_liqd(CX["TRBUSDT"]["br"])[0]] == [1.86, 1.02, 0.51]
    assert [round(x * 100, 2) for x in W.first_tier_liqd(SAND["br"])[0]] == [2.36, 1.52, 1.01]


def test_liquidation_fires_on_the_mark_low_at_the_level():
    n = 400
    ts = T0 + np.arange(n, dtype=np.int64) * MIN
    px = np.full(n, 100.0)
    a = dict(ts=ts, o=px.copy(), h=px * 1.0005, l=px * 0.9995, c=px.copy(), v=np.ones(n), mo=px.copy(),
             mh=px * 1.0005, ml=px * 0.9995, mc=px.copy(), fund=np.zeros(n))
    d = W.first_tier_liqd(BTC["br"])[0, 0]
    e = 200
    F = a["o"][e] * (1 + W.SLIP)
    lq = F * (1 - d)
    a["ml"][250] = lq * (1 + 1e-9)          # just above: nothing
    a["ml"][260] = lq                       # at the level: liquidation (kernel: <=)
    S = a["o"][e] - 5.0
    code, g = W.trade_one(a["o"], a["h"], a["l"], a["c"], a["mo"], a["mh"], a["ml"], e, n, False, 1.0, S, F * 1.01,
                          lq, W.SLIP, True, 0.0, F)
    assert code == 8 * 260 + W.PH_LIQ
    a["mo"][255] = lq                       # a mark open at the level comes first
    code, g = W.trade_one(a["o"], a["h"], a["l"], a["c"], a["mo"], a["mh"], a["ml"], e, n, False, 1.0, S, F * 1.01,
                          lq, W.SLIP, True, 0.0, F)
    assert code == 8 * 255 + W.PH_OPEN_LIQ


def test_funding_paid_before_a_liquidation_stays_paid():
    """7.5 / 7.6: funding is paid from the wallet while the position is open, so a liquidation loses the margin, the
    entry fee AND the funding already paid (before the fix the funding came back at the liquidation). The trade list,
    the account and the reads' plain loop agree."""
    from research.hiwr import reads as RD
    n = 400
    a = _flat_coin(n)
    a["fund"][[210, 220, 230]] = 0.003                       # three +0.3% events: a long pays 0.9% of notional
    F = 100.0 * (1 + W.SLIP)
    lq = F * (1 - W.first_tier_liqd(BTC["br"])[0, 0])
    a["ml"][250] = lq                                         # a mark wick through Lq; last price stays above the stop
    paid = 3 * 100.0 * 0.003 / F
    want = -1.0 / 30 - W.TAKER - paid
    T = W.Tables(a, np.array([a["ts"][200]]), np.array([0.1]), np.array([0]), int(a["ts"][-1]) + MIN, False,
                 W.first_tier_liqd(BTC["br"]), np.array([MAKER30["t"] + 0.0005]), np.array([MAKER30["t"]]))
    x = W.trade_list(T, [0], [0], MAKER30)
    assert x["skip"][0] == 0 and x["kind"][0] == W.X_LIQ and int(x["code"][0]) == 8 * 250 + W.PH_LIQ
    assert abs(x["r"][0] - want) < 1e-15
    res = A.account(A.Store.from_coins([a], [False]), _cand([(0, 200, 1, 1.0, 0.1)]), [BTC], MAKER30, 2.0,
                    (T0, T0 + n * MIN))
    assert res["kind"][0] == W.X_LIQ and abs(res["r"][0] - want) < 1e-15
    assert abs(res["final"] - (1000.0 + 2000.0 * want)) < 1e-9
    fc = np.cumsum(a["mo"] * a["fund"])
    assert abs(RD.outcome_r(fc, 200, 8 * 250 + 4, 0.0, 1.0, F, 30.0, True, W.TAKER, W.MAKER) - want) < 1e-15


# ------------------------------------------------------------------ candidates
@pytest.mark.parametrize("tf", ["15m", "30m", "1h", "4h"])
def test_weekend_mask_boundaries(tf):
    step = R.TF_MS[tf]
    sat = D.ms("2021-01-02")                # 00:00 UTC, a Saturday
    mon = D.ms("2021-01-04")                # 00:00 UTC, the Monday after
    closes = np.array([sat - step, sat, sat + step, mon - step, mon, mon + step], np.int64)
    assert list(W.weekend(closes)) == [False, True, True, True, False, False]
    # the same on bars built from 1m data over a full week
    n = 9 * 1440
    ts0 = sat - 3 * 86_400_000
    ts = ts0 + np.arange(n, dtype=np.int64) * MIN
    px = np.full(n, 100.0)
    df, close = D.build_frame(dict(ts=ts, o=px, h=px, l=px, c=px, v=np.ones(n)), tf)
    wk = W.weekend(close)
    assert wk[close == sat].all() and not wk[close == sat - step].any()
    assert not wk[close == mon].any() and wk[close == mon - step].all()
    assert wk.sum() == 2 * 86_400_000 // step
    kst = (close[wk] + 9 * 3_600_000 - W.MONDAY0) % W.WEEK      # KST Saturday 09:00 .. Monday 09:00
    assert ((kst >= 5 * 86_400_000 + 9 * 3_600_000) | (kst < 9 * 3_600_000)).all()


def test_stop_inside_tp_and_stop_room():
    """A calm 15m series (1 ATR often narrower than the TP) and a wild one (no stop room at 30x for 1 ATR): each
    candidate's skip is exactly the rule of 7.3 / 7.4 evaluated here from the tables' fill, stop distance and ATR."""
    seen = {1: 0, 2: 0, 0: 0}
    for arr, tf in ((synth(8000, 21, vol=0.0002, gap_p=0.0), "15m"), (synth(8000, 22, vol=0.004, gap_p=0.0), "15m")):
        T, *_ = tables(arr, tf)
        for cfg in [c for c in W.exit_configs() if c["k"] in (0, 4) and c["step"] == 2 and c["Li"] in (0, 2)]:
            rows = np.arange(len(T.bars))
            s = rows % 2
            x = W.trade_list(T, rows, s, cfg)
            sd = T.x[1]["sd"][rows, s, cfg["k"]]
            F = T.x[1]["F"][rows, s]
            room = sd + np.maximum(0.002, T.atr[rows] / F) <= T.liqd[s, cfg["Li"]]
            ok = T.ent[rows] >= 0
            assert (x["skip"][ok & ~room] == 1).all()
            assert (x["skip"][ok & room & (sd <= cfg["t"])] == 2).all()
            assert (x["skip"][ok & room & (sd > cfg["t"])] != 2).all() and (x["skip"][ok & room & (sd > cfg["t"])]
                                                                             != 1).all()
            for k in seen:
                seen[k] += int((x["skip"] == k).sum())
            # the price stops are never inside the TP (0.60% of P0 is about 0.62% from the fill > 0.54%)
            if cfg["k"] == 4:
                assert not (x["skip"] == 2).any()
    assert all(v > 0 for v in seen.values()), seen


def _flat_coin(n, price=100.0):
    ts = T0 + np.arange(n, dtype=np.int64) * MIN
    px = np.full(n, price)
    return dict(ts=ts, o=px.copy(), h=px * 1.0001, l=px * 0.9999, c=px.copy(), v=np.ones(n), mo=px.copy(),
                mh=px * 1.0001, ml=px * 0.9999, mc=px.copy(), fund=np.zeros(n))


def _cand(entries, store_coins=None):
    """entries: (coin, e, side, D, atr) -> candidates (segment = coin)."""
    c = np.array([x[0] for x in entries], np.int64)
    e = np.array([x[1] for x in entries], np.int64)
    side = np.array([x[2] for x in entries], np.int64)
    Dst = np.array([x[3] for x in entries], float)
    atr = np.array([x[4] for x in entries], float)
    fill = T0 + e * MIN
    return A.candidates(c, c, e, side, Dst, atr, fill)


MAKER30 = next(c for c in W.exit_configs() if c["L"] == 30 and c["step"] == 0 and c["k"] == 6 and c["fill"] == 1)


def test_bracket_cut_and_minimum_notional():
    a = _flat_coin(300)
    a["h"][120] = 101.0                       # TP of the trade entered at 100
    store = A.Store.from_coins([a], [False])
    cand = _cand([(0, 100, 1, 1.0, 0.1)])
    period = (T0, T0 + 300 * MIN)
    res = A.account(store, cand, [SAND], MAKER30, 25.0, period)       # 25 x $1,000 > SAND's 30x cap $10,000
    assert res["n"] == 1 and res["n_cut"] == 1 and res["N"][0] == 10_000.0
    assert abs(res["final"] - (1000.0 + 10_000.0 * res["r"][0])) < 1e-9
    assert res["counts"]["taken"] == 1
    res = A.account(store, cand, [SAND], MAKER30, 9.0, period)
    assert res["n_cut"] == 0 and res["N"][0] == 9000.0
    res = A.account(store, cand, [SAND], MAKER30, 0.004, period)       # $4 < SAND's $5 minimum
    assert res["n"] == 0 and res["counts"]["minimum notional"] == 1
    assert A.notional_cap(SAND["br"], 30) == 10_000 and A.notional_cap(CX["TRBUSDT"]["br"], 30) == 5_000
    assert A.notional_cap(BTC["br"], 50) == 12_000_000
    assert CX["TOMOUSDT"]["proxy"] and not SAND["proxy"]
    assert (CX["TOMOUSDT"]["br"] == SAND["br"]).all()


def test_stop_room_is_redone_at_the_bracket_of_the_notional():
    a = _flat_coin(300)
    store = A.Store.from_coins([a], [False])
    br = SAND["br"]
    F = 100.0 * (1 + W.SLIP)
    # a stop that fits at the first bracket (mmr 1%) but not at the second (mmr 1.5%, cum 25) at 30x
    lq1 = W.liq_price(1, F, 4000.0, 30, br[0, 2], br[0, 3])
    lq2 = W.liq_price(1, F, 9000.0, 30, br[1, 2], br[1, 3])
    assert lq2 > lq1
    room_needed = lambda D_: D_ + W.SLIP * 100.0 + max(0.002 * F, 0.1)   # noqa: E731
    D_ = (F - (lq1 + lq2) / 2) - W.SLIP * 100.0 - 0.2
    assert room_needed(D_) <= F - lq1 and room_needed(D_) > F - lq2
    cand = _cand([(0, 100, 1, D_, 0.1)])
    period = (T0, T0 + 300 * MIN)
    assert A.account(store, cand, [SAND], MAKER30, 4.0, period)["n"] == 1
    r2 = A.account(store, cand, [SAND], MAKER30, 9.0, period)
    assert r2["n"] == 0 and r2["counts"]["no stop room at N"] == 1


def test_busy_rule_and_ties():
    a0, a1 = _flat_coin(400), _flat_coin(400, 50.0)
    a0["h"][150] = 101.0                      # coin 0 long from 100 exits by TP at minute 150
    a1["l"][150] = 49.0                       # coin 1 short exits by TP at 150 as well
    store = A.Store.from_coins([a0, a1], [False, False])
    period = (T0, T0 + 400 * MIN)
    cand = _cand([(1, 100, 1, 1.0, 0.1), (0, 100, -1, 1.0, 0.1), (0, 100, 1, 1.0, 0.1),   # same fill minute
                  (1, 150, -1, 0.5, 0.05),       # fill minute == exit minute: busy
                  (1, 151, -1, 0.5, 0.05)])      # the minute after: taken
    res = A.account(store, cand, [BTC, BTC], MAKER30, 2.0, period)
    o = cand["order"]
    st = res["status"]
    assert list(cand["coin"][:3]) == [0, 0, 1] and list(cand["side"][:3]) == [1, -1, 1]
    assert list(st) == [A.A_TAKEN, A.A_BUSY, A.A_BUSY, A.A_BUSY, A.A_TAKEN]
    assert res["exit_ms"][0] == T0 + 150 * MIN and res["fill_ms"][1] == T0 + 151 * MIN
    assert sorted(o) == list(range(5))
    # on random data: every busy candidate fills inside a taken trade, taken trades never overlap
    a = synth(30_000, 9, vol=0.0006)
    b = synth(30_000, 10, price=50.0, vol=0.0006)
    Ts = [tables(x, "15m")[0] for x in (a, b)]
    cfg = next(c for c in W.exit_configs() if c["L"] == 30 and c["k"] == 0 and c["fill"] == 1 and c["step"] == 1)
    tls = [W.trade_list(T, np.arange(len(T.bars)), np.arange(len(T.bars)) % 2, cfg) for T in Ts]
    cand = A.candidates_from_tables(Ts, tls, cfg)
    res = A.account(A.Store.from_coins([a, b], [False, False]), cand, [BTC, BTC], cfg, 3.0,
                    (T0, int(a["ts"][-1]) + MIN))
    assert res["n"] > 10 and res["counts"]["busy"] > 0
    fills, exits = res["fill_ms"], res["exit_ms"]
    assert (fills[1:] > exits[:-1]).all()
    for q in np.flatnonzero(res["status"] == A.A_BUSY):
        fm = cand["fill_ms"][q]
        assert ((fills <= fm) & (fm <= exits)).any()


# ------------------------------------------------------------------ the drawdown (8.3)
def slow_account_dd(a, res, cand, cfg, w0=1000.0):
    """Max mark-to-market and realized DD of the account's taken trades from the minute bars, 8.3 written plainly;
    also each trade's marks (for the bootstrap reference)."""
    slip, tk = W.SLIP, W.TAKER
    P = Pr = w0
    wal = w0
    dd = ddr = 0.0
    marks = []
    for i, q in enumerate(res["taken"]):
        side = int(cand["side"][q])
        e = int(cand["e"][q])
        F = a["o"][e] * (1 + side * slip)
        N = res["N"][i]
        xj = int(np.searchsorted(a["ts"], res["exit_ms"][i]))
        ph = int(res["phase"][i])
        paid = 0.0
        mk = []
        for j in range(e, xj + 1):
            if j > e:
                paid += side * a["mo"][j] * a["fund"][j] / F
            last = j == xj
            if (not last) or ph in (5, 6, 7):
                X = (a["l"][j] if side > 0 else a["h"][j]) * (1 - side * slip)
                m = side * (X / F - 1) - tk - tk * X / F - paid
                dd = max(dd, 1 - (wal + N * m) / P)
                mk.append(("adv", m))
            if (not last) or ph == 7:
                X = a["c"][j] * (1 - side * slip)
                m = side * (X / F - 1) - tk - tk * X / F - paid
                P = max(P, wal + N * m)
                mk.append(("close", m))
        wal = wal + N * res["r"][i]
        dd = max(dd, 1 - wal / P)
        P = max(P, wal)
        Pr = max(Pr, wal)
        ddr = max(ddr, 1 - wal / Pr)
        marks.append(mk)
    return dd, ddr, marks


def _random_account(seed, f, cfg_pick=None):
    a = synth(40_000, seed, vol=0.0006, spike_p=0.0002)
    T, *_ = tables(a, "15m")
    cfgs = W.exit_configs()
    cfg = cfg_pick or next(c for c in cfgs if c["L"] == 30 and c["k"] == 1 and c["fill"] == 1 and c["step"] == 2)
    rows = np.arange(0, len(T.bars), 6)
    tl = W.trade_list(T, rows, (rows // 6) % 2, cfg)
    cand = A.candidates_from_tables([T], [tl], cfg)
    period = (T0, int(a["ts"][-1]) + MIN)
    store = A.Store.from_coins([a], [False])
    res = A.account(store, cand, [BTC], cfg, f, period)
    return a, T, cfg, cand, store, period, res


@pytest.mark.parametrize("seed,f", [(12, 1.0), (13, 2.0), (14, 3.0)])
def test_account_dd_matches_a_plain_minute_loop(seed, f):
    a, T, cfg, cand, store, period, res = _random_account(seed, f)
    assert res["n"] > 5 and not res["bust"]
    dd, ddr, _marks = slow_account_dd(a, res, cand, cfg)
    assert abs(dd - res["dd"]) < 1e-12 and abs(ddr - res["dd_real"]) < 1e-12
    assert res["dd_real"] <= res["dd"] + 1e-15
    assert abs(A.path_dd(res) - res["dd"]) < 1e-12           # the per-trade decomposition, in the account's order


def _one_trade_account(lows, highs, closes, opens=None, t_exit=None):
    """A long from minute 10 at 100 on a flat coin; minutes 10.. get the given bars."""
    n = 60
    a = _flat_coin(n)
    for i, (lo, hi, c) in enumerate(zip(lows, highs, closes)):
        j = 10 + i
        a["l"][j], a["h"][j], a["c"][j] = lo, hi, c
        a["ml"][j], a["mh"][j] = lo, hi
        if opens is not None and opens[i] is not None:
            a["o"][j] = a["mo"][j] = opens[i]
    store = A.Store.from_coins([a], [False])
    cand = _cand([(0, 10, 1, 1.0, 0.1)])
    res = A.account(store, cand, [BTC], MAKER30, 5.0, (T0, T0 + n * MIN))
    return a, res


def test_mtm_exit_minute_rule_and_peak_before_the_minute():
    F = 100.0 * (1 + W.SLIP)
    T = F * (1 + MAKER30["t"])
    N = 5000.0
    m = lambda X: (X * (1 - W.SLIP) / F - 1) - W.TAKER - W.TAKER * X * (1 - W.SLIP) / F   # noqa: E731
    E = lambda X: 1000.0 + N * m(X)                                                          # noqa: E731
    dd = lambda x, peak: 1 - x / peak                                                        # noqa: E731
    first_two = max(dd(E(99.9), 1000.0), dd(E(99.8), max(1000.0, E(100.0))))
    # TP filled inside minute 12, whose low (99.2) came first: it counts, against the closes before minute 12
    a1, r1 = _one_trade_account([99.9, 99.8, 99.2], [100.1, 100.35, T + 0.05], [100.0, 100.3, 100.3])
    assert r1["kind"][0] == W.X_TP and r1["phase"][0] == W.PH_TP
    assert E(100.3) > 1000.0
    want = max(first_two, dd(E(99.2), E(100.3)))
    assert abs(r1["dd"] - want) < 1e-12 and want == dd(E(99.2), E(100.3))
    # the same minute opening beyond T: an exit on the open, no mark of that minute
    a2, r2 = _one_trade_account([99.9, 99.8, 99.2], [100.1, 100.35, T + 0.05], [100.0, 100.3, 100.3],
                                opens=[None, None, T + 0.02])
    assert r2["phase"][0] == W.PH_OPEN_TP
    assert abs(r2["dd"] - first_two) < 1e-12 and r2["dd"] < r1["dd"]
    # a stop inside minute 12 whose low (95) is far below the stop (99): it counts at its fill only
    a3, r3 = _one_trade_account([99.9, 99.8, 95.0], [100.1, 100.35, 100.3], [100.0, 100.3, 96.0])
    assert r3["kind"][0] == W.X_STOP and r3["phase"][0] == W.PH_STOP
    wal = 1000.0 + N * r3["r"][0]
    assert abs(r3["dd"] - max(first_two, dd(wal, E(100.3)))) < 1e-12
    assert r3["dd"] < dd(E(95.0), E(100.3))
    # peak before the minute: minute 11 closes at a new high (100.3) after a dip to 99.5 inside it; the dip is
    # measured against the peak of the closes before minute 11, not against its own close
    a4, r4 = _one_trade_account([99.9, 99.5, 100.2], [100.1, 100.35, T + 0.05], [100.0, 100.3, 100.3])
    want = max(dd(E(99.9), 1000.0), dd(E(99.5), max(1000.0, E(100.0))), dd(E(100.2), E(100.3)))
    assert abs(r4["dd"] - want) < 1e-12
    assert r4["dd"] < dd(E(99.5), E(100.3))


def test_realized_dd_never_exceeds_mtm_dd():
    for seed in (15, 16):
        for f in (0.5, 2.0, 9.0):
            res = _random_account(seed, f)[-1]
            assert res["dd_real"] <= res["dd"] + 1e-15


def _fake_res(r, marks, f, fill_ms):
    """An account result of trades with per-notional results r and marks, all at fraction f."""
    n = len(r)
    u, d1, d2 = np.ones(n), np.full(n, np.inf), np.full(n, np.inf)
    for i, mk in enumerate(marks):
        M = 1.0
        for typ, m in mk:
            v = 1 + f * m
            if typ == "adv":
                d1[i] = min(d1[i], v)
                d2[i] = min(d2[i], v / M)
            else:
                M = max(M, v)
                u[i] = max(u[i], v)
    res = {"n": n, "r": np.asarray(r, float), "feff": np.full(n, f), "u": u, "d1": d1, "d2": d2,
           "fill_ms": np.asarray(fill_ms, np.int64), "w0": 1.0, "f": float(f), "bust": False}
    order = np.arange(n, dtype=np.int64)
    w = 1 + f * res["r"]
    res["dd"] = A._path_dd(order, w, u, d1, d2, A.BUST)
    wal = np.cumprod(w)
    peak = np.maximum.accumulate(np.r_[1.0, wal])[1:]
    res["dd_real"] = float(max(0.0, (1 - wal / peak).max()))
    res["worst_loss"] = float(max(0.0, (-f * res["r"]).max()))
    res["month_eq"] = np.array([wal[-1]])
    return res


def test_sizes_fall_as_the_drawdown_rises():
    rng = np.random.default_rng(4)
    n = 120
    period = (A.D.PERIODS["SEL"][0], A.D.PERIODS["SEL"][1])
    fill = np.sort(rng.integers(period[0], period[1] - 86_400_000, n))
    r = np.where(rng.random(n) < 0.82, 0.003, -0.011)
    marks = [[("adv", -0.004), ("close", 0.001), ("adv", min(0.0, x) - 0.001), ("close", x)] for x in r]
    draws = A.boot_draws(period, "test|pick", n_boot=300)
    base = A.sizes(lambda f: _fake_res(r, marks, f, fill), 0.30, 30, period, draws)
    worse_r = r.copy()
    worse_r[n // 2] = -0.03                    # one deeper loss
    worse_marks = [list(m) for m in marks]
    worse_marks[n // 2] = [("adv", -0.03)]
    worse = A.sizes(lambda f: _fake_res(worse_r, worse_marks, f, fill), 0.30, 30, period, draws)
    deeper = [list(m) for m in marks]
    deeper[n // 3] = [("adv", -0.12), ("close", r[n // 3])]       # a deeper open dip, same result
    dip = A.sizes(lambda f: _fake_res(r, deeper, f, fill), 0.30, 30, period, draws)
    for out in (worse, dip):
        assert out["f_path"]["f"] <= base["f_path"]["f"] and out["f_star"]["f"] <= base["f_star"]["f"]
    assert worse["f_path"]["f"] < base["f_path"]["f"] and dip["f_path"]["f"] < base["f_path"]["f"]
    for out, rr, mm in ((base, r, marks), (worse, worse_r, worse_marks), (dip, r, deeper)):
        assert out["f_star"]["f"] <= out["f_path"]["f"] <= 9.0
        assert out["f_path"]["dd"] <= 0.30 and out["f_star"]["boot_q95"] <= 0.30
        # every grid size up to f_path meets (i) and (ii); one step above breaks one of them (8.4)
        for k in range(1, int(round(out["f_path"]["f"] * 100)) + 1, 7):
            x = _fake_res(rr, mm, k / 100, fill)
            assert x["dd"] <= 0.30 and x["worst_loss"] <= 0.15
        up = _fake_res(rr, mm, out["f_path"]["f"] + 0.01, fill)
        assert up["dd"] > 0.30 or up["worst_loss"] > 0.15 or out["f_path"]["f"] >= 9.0
    # a tighter cap gives a smaller size
    tight = A.sizes(lambda f: _fake_res(r, marks, f, fill), 0.15, 30, period, draws)
    assert tight["f_path"]["f"] < base["f_path"]["f"] and tight["f_star"]["f"] <= base["f_star"]["f"]


def test_size_search_on_an_account():
    a, T, cfg, cand, store, period, res = _random_account(17, 1.0)
    draws = np.random.default_rng(3).integers(0, A.week_ids([], period)[1], (200, A.week_ids([], period)[1]))
    out = A.sizes(lambda f: A.account(store, cand, [BTC], cfg, f, period), 0.30, 30, period, draws)
    fp, fs = out["f_path"]["f"], out["f_star"]["f"]
    assert 0 < fs <= fp <= 9.0
    hi = A.account(store, cand, [BTC], cfg, fp + 0.01, period)
    assert fp >= 9.0 or hi["dd"] > 0.30 or hi["worst_loss"] > 0.15
    assert out["f_path"]["dd"] <= 0.30


def test_first_fail_scan_and_no_feasible_island_above_a_failure():
    """8.4: f_path is 0.01 below the FIRST failing grid size, never a feasible size above a failing one (a bisection
    returned 9.0 here, or a size inside an island)."""
    assert A.first_fail_scan(lambda k: k <= 300 or k > 500, 900) == 300
    assert A.first_fail_scan(lambda k: True, 900) == 900
    assert A.first_fail_scan(lambda k: False, 900) == 0
    rng = np.random.default_rng(4)
    n = 120
    period = (A.D.PERIODS["SEL"][0], A.D.PERIODS["SEL"][1])
    fill = np.sort(rng.integers(period[0], period[1] - 86_400_000, n))
    r = np.where(rng.random(n) < 0.85, 0.003, -0.006)
    marks = [[("adv", -0.002), ("close", x)] for x in r]
    draws = A.boot_draws(period, "test|island", n_boot=200)

    def run_at(f):                                 # a drawdown above the cap only on (3.00, 5.00]: an island above
        res = _fake_res(r, marks, f, fill)
        if 3.0 + 1e-9 < f <= 5.0 + 1e-9:
            res["dd"] = 0.5
        return res
    out = A.sizes(run_at, 0.30, 30, period, draws)
    assert out["f_path"]["f"] == 3.00 and run_at(9.0)["dd"] <= 0.30          # ok at the ceiling, failing below
    assert out["f_star"]["f"] <= 3.00
    # the same for (i'): a bootstrap failure, then a pass again, is the end of f*
    calls = []

    def boot_ok(k):
        calls.append(k)
        return k <= 120 or k > 200
    assert A.bootstrap_scan(boot_ok, {}, 300) == 120


def _hand_account(plan, d_btc=1.0, d_sand=2.1, gap=300):
    """A hand-built BTC + SAND account (synthetic): one long every ``gap`` minutes that wins (TP) or loses (stop)
    20 minutes after entry. At a larger f the SAND notional moves to its second bracket, whose stop room drops the
    SAND losses: the drawdown falls although f rises."""
    n = gap * (len(plan) + 2)
    a = [_flat_coin(n), _flat_coin(n)]
    ent = []
    for i, (c, wl) in enumerate(plan):
        e = gap * (i + 1)
        Dd = d_btc if c == 0 else d_sand
        if wl == "W":
            a[c]["h"][e + 20] = 101.0
        else:
            a[c]["l"][e + 20] = 100.0 - Dd - 0.5
        ent.append((c, e, 1, Dd, 0.1))
    c = np.array([x[0] for x in ent])
    e = np.array([x[1] for x in ent])
    cand = A.candidates(c, c, e, np.ones(len(ent), np.int64), np.array([x[3] for x in ent], float),
                        np.array([x[4] for x in ent], float), T0 + e * MIN)
    return A.Store.from_coins(a, [False, False]), cand, (T0, T0 + n * MIN)


def test_sizes_on_a_non_monotone_bracket_account():
    """The reviewers' case: ok on 0.01-3.03, fails on 3.04-3.97 (DD over the cap), ok again from 3.98 because SAND's
    losers get no stop room at its second bracket. f_path must be 3.03 (the old bisection returned 9.0)."""
    plan = [(0, "W")] * 30 + [(0, "L"), (1, "L"), (1, "L"), (1, "L"), (1, "L"), (0, "L")] + [(0, "W")] * 5
    store, cand, period = _hand_account(plan)
    run = lambda f: A.account(store, cand, [BTC, SAND], MAKER30, f, period)    # noqa: E731
    ok = [(lambda x: x["dd"] <= 0.30 and x["worst_loss"] <= 0.15)(run(k / 100)) for k in range(1, 901)]
    first_bad = ok.index(False) + 1
    assert any(ok[first_bad:])                                # a feasible island above the first failure
    nw = A.week_ids([], period)[1]
    draws = np.random.default_rng(1).integers(0, nw, (200, nw))
    out = A.sizes(run, 0.30, 30.0, period, draws)
    assert out["f_path"]["f"] == (first_bad - 1) / 100
    out2 = A.sizes(run, 0.30, 30.0, period, draws, scan=A.path_scanner(store, cand, [BTC, SAND], MAKER30, period))
    assert out2["f_path"]["f"] == out["f_path"]["f"] and out2["f_star"]["f"] == out["f_star"]["f"]
    assert all(ok[:first_bad - 1])
    assert out["f_star"]["f"] <= out["f_path"]["f"]


@pytest.mark.parametrize("seed", [24, 54, 31])
def test_bootstrap_scan_equals_the_plain_scan_on_capped_alt_accounts(seed):
    """f* by the run-and-bisect scan equals the plain scan of every grid size, on synthetic LTC / SAND / ADA accounts
    whose notional cap ($10,000) and brackets bind as f grows (cut trades: no shortcut there)."""
    syms = ["LTCUSDT", "SANDUSDT", "ADAUSDT"]
    coins = [synth(25_000, 300 + seed + i, price=(80.0, 0.8, 0.4)[i], vol=0.0005, spike_p=0.0) for i in range(3)]
    rng = np.random.default_rng(seed)
    L = (30, 40, 50)[seed % 3]
    cfg = next(c for c in W.exit_configs() if c["L"] == L and c["step"] == 0 and c["k"] == 6 and c["fill"] == 1)
    cand = []
    for _ in range(260):
        c = int(rng.integers(3))
        a = coins[c]
        e = int(rng.integers(1, len(a["ts"]) - 300))
        side = 1 if (a["c"][e + 120] > a["o"][e]) == (rng.random() < 0.8) else -1
        P0 = a["o"][e]
        cand.append((c, e, side, 0.01 * P0, P0 * rng.uniform(0.001, 0.003), int(a["ts"][e])))
    ca = A.candidates(*[[x[i] for x in cand] for i in (0, 0, 1, 2, 3, 4, 5)])
    store = A.Store.from_coins(coins, [False] * 3)
    cx = [CX[s] for s in syms]
    period = (T0, int(coins[0]["ts"][-1]) + MIN)
    nw = A.week_ids([], period)[1]
    draws = np.random.default_rng(seed).integers(0, nw, (300, nw))
    run = lambda f: A.account(store, ca, cx, cfg, f, period)    # noqa: E731
    scanner = A.path_scanner(store, ca, cx, cfg, period)
    for cap in (0.30, 0.15):
        fast = A.sizes(run, cap, float(L), period, draws, scan=scanner)
        plain = A.sizes(run, cap, float(L), period, draws)
        slow = A.sizes(run, cap, float(L), period, draws, exact_boot=True)
        for x in (fast, plain):
            assert x["f_path"]["f"] == slow["f_path"]["f"] and x["f_star"]["f"] == slow["f_star"]["f"]
            assert x["f_star"]["boot_q95"] == slow["f_star"]["boot_q95"]
        assert fast["scan"]["bootstraps"] == plain["scan"]["bootstraps"] <= slow["scan"]["bootstraps"]
        # the compiled scan's structure runs equal the Python structure() of each account
        kp, valid, same = scanner(cap, 0.15, int(L * L))
        assert kp == int(round(fast["f_path"]["f"] * 100))
        prev = None
        for k in range(1, kp + 1):
            sg = A.structure(run(k / 100))
            assert valid[k] == (sg is not None) and same[k] == (sg is not None and sg == prev)
            prev = sg
        kp = int(round(fast["f_path"]["f"] * 100))
        for k in range(1, kp + 1, 3):
            x = run(k / 100)
            assert x["dd"] <= cap and x["worst_loss"] <= 0.15


def test_structure_runs_share_one_monotone_drawdown():
    """Inside one structure (same taken trades, results and exits, nothing cut) every resampled path's DD is
    nondecreasing in f: the speed-up of the f* scan rests on it."""
    a, T, cfg, cand, store, period, _res = _random_account(21, 1.0)
    nw = A.week_ids([], period)[1]
    draws = np.random.default_rng(9).integers(0, nw, (200, nw))
    prev_sig, prev_dd, prev_res_dd = None, None, None
    seen = 0
    for k in range(50, 400, 5):
        res = A.account(store, cand, [BTC], cfg, k / 100, period)
        sig = A.structure(res)
        d = A.boot_dd(res, period, draws)
        if sig is not None and sig == prev_sig:
            assert (d >= prev_dd - 1e-12).all() and res["dd"] >= prev_res_dd - 1e-12
            seen += 1
        prev_sig, prev_dd, prev_res_dd = sig, d, res["dd"]
    assert seen > 10


# ------------------------------------------------------------------ the bootstrap (8.4)
def test_week_block_bootstrap_matches_a_slow_per_path_loop():
    a, T, cfg, cand, store, period, res = _random_account(18, 2.0)
    assert res["n"] > 10
    _dd, _ddr, marks = slow_account_dd(a, res, cand, cfg)
    wk, nw = A.week_ids(res["fill_ms"], period)
    assert nw >= 4
    draws = np.random.default_rng(5).integers(0, nw, (300, nw))
    fast = A.boot_dd(res, period, draws)
    slow = A.boot_dd_slow(res, period, draws, marks)
    assert np.abs(fast - slow).max() < 1e-12
    same = np.tile(np.arange(nw), (1, 1))                 # the identity draw is the account's own path
    assert abs(A.boot_dd(res, period, same)[0] - res["dd"]) < 1e-12


def test_sel_weeks_and_seeds():
    sel = D.PERIODS["SEL"]
    wk, nw = A.week_ids(np.array([sel[0], sel[1] - 1]), sel)
    assert nw == 157 and list(wk) == [0, 156]
    d1 = A.boot_draws(sel, "S4_BB_BBP|4h|0|L30|TP0.39|1ATR|maker", n_boot=50)
    d2 = A.boot_draws(sel, "S4_BB_BBP|4h|0|L30|TP0.39|1ATR|maker", n_boot=50)
    d3 = A.boot_draws(sel, "S4_BB_BBP|4h|0|L30|TP0.44|1ATR|maker", n_boot=50)
    assert d1.shape == (50, 157) and (d1 == d2).all() and not (d1 == d3).all()
    import hashlib
    seed = int.from_bytes(hashlib.sha256(b"hiwr|a|SEL|x|7").digest()[:8], "little")
    assert A.rng_for("a", "SEL", "x", 7).integers(0, 10 ** 9) == \
        np.random.Generator(np.random.PCG64(seed)).integers(0, 10 ** 9)


def test_monthly_returns():
    a, T, cfg, cand, store, period, res = _random_account(19, 3.0)
    mo = A.monthly(res)
    assert mo["months"] == len(res["bounds"]) and abs(mo["final_x"] - res["final"] / 1000.0) < 1e-12
    assert res["bounds"][-1] == period[1]
    sel = A.month_bounds(D.PERIODS["SEL"])
    assert len(sel) == 36 and sel[0] == D.ms("2021-02-01") and sel[-1] == D.ms("2024-01-01")


def test_coin_end_period_end_and_month_end_marks():
    jan31 = D.ms("2021-01-31")
    n = 2 * 1440
    ts = jan31 + np.arange(n, dtype=np.int64) * MIN
    px = np.full(n, 100.0)
    a = dict(ts=ts, o=px.copy(), h=px * 1.0001, l=px * 0.9999, c=px.copy(), v=np.ones(n), mo=px.copy(),
             mh=px * 1.0001, ml=px * 0.9999, mc=px.copy(), fund=np.zeros(n))
    a["c"][1439] = 100.2                     # the last close of January
    period = (D.ms("2021-01-01"), D.ms("2021-02-02"))
    cand = A.candidates([0], [0], [100], [1], [1.0], [0.5], [ts[100]])
    # the coin ends at its last bar: the trade closes there like a stop-market order
    res = A.account(A.Store.from_coins([a], [True]), cand, [BTC], MAKER30, 2.0, period)
    assert res["kind"][0] == W.X_COIN_END and res["exit_ms"][0] == ts[-1] and not res["open_at_end"]
    F = 100.0 * (1 + W.SLIP)
    X = 100.0 * (1 - W.SLIP)
    want_r = (X / F - 1) - W.TAKER - W.TAKER * X / F
    assert abs(res["r"][0] - want_r) < 1e-15
    # the month boundary inside the trade: equity marked at January's last close (a market exit there)
    Xj = 100.2 * (1 - W.SLIP)
    eq_jan = 1000.0 + 2000.0 * ((Xj / F - 1) - W.TAKER - W.TAKER * Xj / F)
    assert len(res["bounds"]) == 2 and res["bounds"][0] == D.ms("2021-02-01")
    assert abs(res["month_eq"][0] - eq_jan) < 1e-9 and abs(res["month_eq"][1] - res["final"]) < 1e-12
    mo = A.monthly(res)
    assert abs(mo["worst_M"] - min(eq_jan / 1000.0, res["final"] / eq_jan)) < 1e-12
    # not a coin end: open at the period end, marked at the last close and flagged; nothing after it is taken
    cand2 = A.candidates([0, 0], [0, 0], [100, 2000], [1, -1], [1.0, 1.0], [0.5, 0.5], [ts[100], ts[2000]])
    res = A.account(A.Store.from_coins([a], [False]), cand2, [BTC], MAKER30, 2.0, period)
    assert res["open_at_end"] and res["kind"][0] == W.X_OPEN and res["n"] == 1
    assert res["counts"]["busy"] == 1
    assert abs(res["final"] - (1000.0 + 2000.0 * want_r)) < 1e-9
    with pytest.raises(ValueError):
        A.account(A.Store.from_coins([a], [False]), cand2, [BTC], MAKER30, 2.0, (period[0], int(ts[-1])))

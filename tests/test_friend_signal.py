"""'친구 매매법' (owners 2026-10-24, paperbot/friendsig.py): the friend's EMA / RSI / ROC signal against an independent
plain-loop implementation of the brief's words, the higher-bar closing rule, the bars (closed only, 3d from daily bars on
the research grid from 2020-01-01), the two gates (4h ADX below 20, the signal bar's volume above 0.64 x the 20 before)
and their config problems. The research parity on the research's own bars: research/friendroc/frlive_parity.json."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from paperbot import combo as C
from paperbot import friendsig as FS

MIN = 60_000
M15, H1, H4, DAY = 15 * MIN, 60 * MIN, 240 * MIN, 1440 * MIN
T = FS.GRID_T0 + 2400 * DAY                        # 2026-07-28 00:00 UTC: a 4h / 1h / 15m boundary


# ---------------------------------------------------------------- an independent implementation (the brief's words)
def ema_loop(x, n):
    a, y, out = 2.0 / (n + 1), None, []
    for i, v in enumerate(x):
        y = v if y is None else (1 - a) * y + a * v
        out.append(y if i >= n - 1 else math.nan)
    return out


def rsi_loop(x, n):
    """Wilder's RSI: the averages from the first change, known from the n-th change on; no loss = 100, no gain = 0."""
    a, ag, al, out = 1.0 / n, None, None, [math.nan]
    for i in range(1, len(x)):
        d = x[i] - x[i - 1]
        g, lo = max(d, 0.0), max(-d, 0.0)
        ag = g if ag is None else (1 - a) * ag + a * g
        al = lo if al is None else (1 - a) * al + a * lo
        if i < n:
            out.append(math.nan)
        elif ag <= 1e-12 and al <= 1e-12:
            out.append(50.0)
        elif ag <= 1e-12:
            out.append(0.0)
        elif al <= 1e-12:
            out.append(100.0)
        else:
            out.append(100 - 100 / (1 + ag / al))
    return out


def roc_loop(x, n):
    return [math.nan if i < n else (x[i] / x[i - n] - 1) * 100 for i in range(len(x))]


def plain_side(c15, i, higher, bar_close, mode="roc_any"):
    """Long: EMA21 > EMA52, RSI26 > 50, ROC9 from <= 0 to > 0, and on the higher bars (the last closed one of each
    timeframe, 60 bars before it at least) "roc_any": ROC9 > 0 on either, "rsi_roc_all": RSI26 > 50 and ROC9 > 0 on
    both; short mirrored; 200 signal bars before at least."""
    if i < 200:
        return 0
    x = list(c15[:i + 1])
    e21, e52, rsi, roc = ema_loop(x, 21)[-1], ema_loop(x, 52)[-1], rsi_loop(x, 26)[-1], roc_loop(x, 9)
    hv, hr = [], []
    for tc, hc in higher:
        j = max([k for k in range(len(tc)) if tc[k] <= bar_close], default=-1)
        hv.append(roc_loop(list(hc[:j + 1]), 9)[-1] if j >= 60 else math.nan)
        hr.append(rsi_loop(list(hc[:j + 1]), 26)[-1] if j >= 60 else math.nan)
    if mode == "roc_any":
        h_up, h_dn = hv[0] > 0 or hv[1] > 0, hv[0] < 0 or hv[1] < 0
    else:
        h_up = all(r > 50 and v > 0 for r, v in zip(hr, hv))
        h_dn = all(r < 50 and v < 0 for r, v in zip(hr, hv))
    if e21 > e52 and rsi > 50 and roc[-2] <= 0 < roc[-1] and h_up:
        return 1
    if e21 < e52 and rsi < 50 and roc[-2] >= 0 > roc[-1] and h_dn:
        return -1
    return 0


def synth(n, seed):
    """15m closes with changing drifts (trends both ways and chop) and the 1h / 4h bars they make."""
    rng = np.random.default_rng(seed)
    drift = np.repeat(rng.normal(0, 0.0012, n // 120 + 1), 120)[:n]
    c = 100 * np.exp(np.cumsum(drift + rng.normal(0, 0.003, n)))
    t15 = T - (n - np.arange(n)) * M15 + M15            # bar closes, the last one at T
    out = {"15m": (t15, c)}
    for tf, k in (("1h", 4), ("4h", 16)):
        m = n // k
        out[tf] = (t15[n - m * k:][k - 1::k], c[n - m * k:][k - 1::k])   # a higher bar's close = its last 15m close
    return out


@pytest.mark.parametrize("mode", FS.HIGHER_MODES)
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_signal_equals_the_plain_implementation(seed, mode):
    S = synth(1400, seed)
    t15, c = S["15m"]
    sides = {}
    for i in range(1150, 1400):
        side, vals = FS.friend_signal(c[:i + 1], [S["1h"], S["4h"]], int(t15[i]), mode=mode)
        assert side == plain_side(c, i, [S["1h"], S["4h"]], int(t15[i]), mode), i
        assert vals["higher_mode"] == mode and (("rsi" in vals["higher"][0]) == (mode == "rsi_roc_all"))
        sides[side] = sides.get(side, 0) + 1
        if side:
            x = list(c[:i + 1])
            assert vals["e21"] == pytest.approx(ema_loop(x, 21)[-1], rel=1e-12)
            assert vals["rsi"] == pytest.approx(rsi_loop(x, 26)[-1], rel=1e-9)
            assert vals["roc_prev"] <= 0 < vals["roc"] if side > 0 else vals["roc_prev"] >= 0 > vals["roc"]
    assert sides.get(0, 0) > 100                         # most bars are no signal ...
    assert sides.get(1, 0) + sides.get(-1, 0) >= (3 if mode == "roc_any" else 1)   # ... and signals to compare


def test_1500_bars_give_the_full_history_values():
    """The live window (1500 closed bars) reads the same EMA / RSI as the whole series (the research's)."""
    S = synth(4000, 7)
    c = S["15m"][1]
    full = FS.indicators(c)
    part = FS.indicators(c[-FS.SIGNAL_BARS:])
    for k in ("e21", "e52", "rsi", "roc"):
        assert part[k][-1] == pytest.approx(full[k][-1], rel=1e-13, abs=1e-12)


def test_warm_up_needs_200_signal_bars_and_60_higher_bars():
    S = synth(1400, 2)
    t15, c = S["15m"]
    hi = [S["1h"], S["4h"]]
    i = next(i for i in range(1150, 1400) if FS.friend_signal(c[:i + 1], hi, int(t15[i]))[0])
    side = FS.friend_signal(c[:i + 1], hi, int(t15[i]))[0]
    # the signal bar as the 200th bar: the research's index 199 is not warm (WARM15 = 200)
    assert FS.friend_signal(c[i - 199:i + 1], hi, int(t15[i]))[0] == 0
    # 59 higher bars before the one read: unknown (WARMH = 60); 60 before it: read (ROC9 is exact, the same side)
    cut = lambda n: [(tc[tc <= t15[i]][-n:], hc[tc <= t15[i]][-n:]) for tc, hc in hi]     # noqa: E731
    s60, v60 = FS.friend_signal(c[:i + 1], cut(60), int(t15[i]))
    assert s60 == 0 and [h["roc"] for h in v60["higher"]] == [None, None]
    assert FS.friend_signal(c[:i + 1], cut(61), int(t15[i]))[0] == side


# ---------------------------------------------------------------- the higher-bar closing rule
def _up_case():
    """A 15m series whose last bar meets the long conditions on the signal bars (any higher bars permitting)."""
    for seed in range(1, 60):
        S = synth(1400, seed)
        t15, c = S["15m"]
        for i in range(1200, 1400):
            x = list(c[:i + 1])
            roc = roc_loop(x, 9)
            if (ema_loop(x, 21)[-1] > ema_loop(x, 52)[-1] and rsi_loop(x, 26)[-1] > 50 and roc[-2] <= 0 < roc[-1]
                    and int(t15[i]) % H1 == 0):
                return c[:i + 1], int(t15[i])
    raise AssertionError("no case")


def _higher(close_last, n, roc_at, ms):
    """n higher bars closing every ``ms`` up to ``close_last``: flat at 100 except the ones in roc_at {index: price}."""
    tc = close_last - (n - 1 - np.arange(n)) * ms
    hc = np.full(n, 100.0)
    for k, v in roc_at.items():
        hc[k] = v
    return tc, hc


def test_a_higher_bar_counts_when_it_closed_at_or_before_the_signal_bar_close():
    c, bc = _up_case()
    down4 = _higher(bc - H4 // 2, 80, {79: 99.0}, H4)                       # 4h: ROC9 < 0, never confirms a long
    # the 1h bar closing exactly at the signal bar's close is read
    h1 = _higher(bc, 80, {79: 101.0}, H1)
    assert FS.friend_signal(c, [h1, down4], bc)[0] == 1
    # a 1h bar closing after the signal bar (still forming at the signal) is never read, even when it is in the data
    h1b = _higher(bc + H1, 81, {79: 99.0, 80: 101.0}, H1)
    side, vals = FS.friend_signal(c, [h1b, down4], bc)
    assert side == 0 and vals["higher"][0]["close"] == bc and vals["higher"][0]["roc"] < 0
    # either higher timeframe confirms: the 4h alone
    up4 = _higher(bc - H4 // 2, 80, {79: 101.0}, H4)
    assert FS.friend_signal(c, [_higher(bc, 80, {79: 99.0}, H1), up4], bc)[0] == 1
    # neither: no signal
    assert FS.friend_signal(c, [_higher(bc, 80, {79: 99.0}, H1), down4], bc)[0] == 0


def test_rsi_roc_all_needs_rsi_and_roc_on_both_higher_bars():
    c, bc = _up_case()
    rise = {k: 100.0 + 0.1 * (k - 60) for k in range(60, 80)}
    up1 = _higher(bc, 80, rise, H1)                                  # rising: RSI26 > 50, ROC9 > 0
    up4 = _higher(bc - H4 // 2, 80, rise, H4)
    down4 = _higher(bc - H4 // 2, 80, {k: 100.0 - 0.1 * (k - 60) for k in range(60, 80)}, H4)
    side, vals = FS.friend_signal(c, [up1, up4], bc, mode="rsi_roc_all")
    assert side == 1 and all(h["rsi"] > 50 and h["roc"] > 0 for h in vals["higher"])
    assert FS.friend_signal(c, [up1, down4], bc, mode="rsi_roc_all")[0] == 0           # both, not either
    assert FS.friend_signal(c, [up1, down4], bc, mode="roc_any")[0] == 1
    # ROC9 > 0 but RSI26 < 50 on a higher bar (a long fall, then a small bounce over the last 9 bars): no long
    dip = {k: 100.0 - 0.5 * (k - 40) for k in range(40, 71)} | {k: 85.0 + 0.1 * (k - 70) for k in range(71, 80)}
    weak1 = _higher(bc, 80, dip, H1)
    side, vals = FS.friend_signal(c, [weak1, up4], bc, mode="rsi_roc_all")
    assert vals["higher"][0]["roc"] > 0 and vals["higher"][0]["rsi"] < 50 and side == 0
    with pytest.raises(ValueError):
        FS.friend_signal(c, [up1, up4], bc, mode="both")
    words = FS.signal_words({**vals, "tf": "15m", "higher_tf": ["1h", "4h"]})
    assert " · 1시간 RSI26 " in words and "·ROC9 +" in words


def test_last_open_and_the_3d_grid_from_2020():
    assert FS.last_open("15m", T) == T - M15 and FS.last_open("15m", T + 1) == T - M15
    assert FS.last_open("4h", T + 3 * H1) == T - H4
    assert FS.last_open("3d", FS.GRID_T0 + 3 * DAY) == FS.GRID_T0                      # 2020-01-01 .. 01-04
    assert FS.last_open("3d", FS.GRID_T0 + 5 * DAY) == FS.GRID_T0
    assert FS.last_open("3d", FS.GRID_T0 + 6 * DAY) == FS.GRID_T0 + 3 * DAY
    assert (FS.GRID_T0 % (3 * DAY)) != 0                    # not the epoch's 3-day grid: anchored on the research's
    assert FS.HIGHER == {"15m": ("1h", "4h"), "30m": ("1h", "4h"), "1h": ("4h", "1d"), "4h": ("1d", "3d")}


# ---------------------------------------------------------------- the bars
def _rows(n, end_open, ms, seed=3, vol=None):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
    o = np.r_[c[0], c[:-1]]
    h, lo = np.maximum(o, c) * 1.002, np.minimum(o, c) * 0.998
    v = rng.uniform(50, 150, n) if vol is None else np.asarray(vol, float)
    t = end_open - (n - 1 - np.arange(n)) * ms
    return [[int(t[i]), float(o[i]), float(h[i]), float(lo[i]), float(c[i]), float(v[i])] for i in range(n)]


class Feed:
    def __init__(self, rows: dict):
        self.rows, self.calls, self.fail = rows, [], False

    def __call__(self, symbol, tf, start, limit):
        self.calls.append((symbol, tf, start, limit))
        if self.fail:
            raise OSError("down")
        return [r for r in self.rows[tf] if r[0] >= start][:limit]


def test_bars_closed_only_and_the_forming_bar_never_used():
    feed = Feed({"15m": _rows(1601, T, M15)})             # the last row opens at T: still forming at T + 5 s
    now = [T + 5_000]
    kb = FS.KlineBars(feed, lambda: now[0])
    a = kb.closed("ETHUSDT", "15m", T, 1500)
    assert a is not None and int(a[-1, 0]) == T - M15 and len(a) == 1500 and a.shape[1] == 6
    assert feed.calls[0][2] == T - M15 - 1499 * M15        # one page from the first bar needed
    # the bar closing at T + 15m, asked 1 s after its close: not settled yet (SETTLE_MS), so not readable
    now[0] = T + M15 + 1_000
    assert kb.closed("ETHUSDT", "15m", T + M15, 1500) is None
    now[0] = T + M15 + FS.SETTLE_MS
    b = kb.closed("ETHUSDT", "15m", T + M15, 1500)
    assert int(b[-1, 0]) == T and feed.calls[-1][2] == T    # only the new bar asked for
    assert np.allclose(b[-1, 1:], feed.rows["15m"][-1][1:])  # the whole kline kept (open .. volume)


def test_3d_bars_from_daily_bars_on_the_research_grid():
    end = FS.GRID_T0 + 2400 * DAY                           # 2400 days after 2020-01-01: a 3d boundary
    days = _rows(402, end + DAY, DAY)                       # through the day opening at end + 1 day
    kb = FS.KlineBars(Feed({"1d": days}), lambda: end + 2 * DAY + 5_000)
    for t in (end, end + DAY + 5 * H1, end + 2 * DAY):      # the 3d bar from `end` has 1 or 2 of its days: not closed
        a = kb.closed("BTCUSDT", "3d", t, 100)
        assert int(a[-1, 0]) == FS.last_open("3d", t) == end - 3 * DAY
        assert ((a[:, 0].astype(np.int64) - FS.GRID_T0) % (3 * DAY) == 0).all() and len(a) == 100
        d = np.array([r for r in days if end - 3 * DAY <= r[0] < end])
        assert a[-1, 1] == d[0, 1] and a[-1, 2] == d[:, 2].max() and a[-1, 3] == d[:, 3].min()
        assert a[-1, 4] == d[-1, 4] and a[-1, 5] == pytest.approx(d[:, 5].sum())
    # daily bars missing a day of the last closed 3d bar: that 3d bar is not readable (never the one before it)
    kb2 = FS.KlineBars(Feed({"1d": [r for r in days if r[0] != end - 2 * DAY]}), lambda: end + 2 * DAY + 5_000)
    assert kb2.closed("BTCUSDT", "3d", end + DAY + 5 * H1, 100) is None


def test_signals_read_every_member_coin_and_wait_for_unreadable_bars():
    rows = {"15m": _rows(1700, T - M15, M15), "1h": _rows(300, T - H1, H1), "4h": _rows(1600, T - H4, H4)}
    now = [T + 5_000]
    kb = FS.KlineBars(Feed(rows), lambda: now[0])
    m = C.resolve_members([{"strategy": "FRIEND_ROC", "tf": "15m"}], core=[])[0]
    fs = FS.FriendSignals([m], ["BTCUSDT"], kb)
    assert fs.due(T) == [m] and fs.due(T + 5 * MIN) == []
    got, left = fs.compute(T)
    assert left == set()
    r = fs.read("15m", "BTCUSDT", T)
    want = FS.friend_signal(np.array(rows["15m"])[-1500:, 4], [
        (np.array(rows["1h"])[:, 0].astype(np.int64) + H1, np.array(rows["1h"])[:, 4]),
        (np.array(rows["4h"])[:, 0].astype(np.int64) + H4, np.array(rows["4h"])[:, 4])], T)
    assert r["side"] == want[0] and r["values"]["e21"] == want[1]["e21"]
    assert r["values"]["vol_ratio"] == pytest.approx(rows["15m"][-1][5] / np.mean([x[5] for x in rows["15m"][-21:-1]]))
    now[0] = T + M15 + 1_000                                 # the next close, asked before Binance settled it
    got, left = fs.compute(T + M15)
    assert got == [] and left == {(m.label, "BTCUSDT")}


# ---------------------------------------------------------------- the gates
def _gates(rows, now, **kw):
    kb = FS.KlineBars(Feed(rows), lambda: now[0])
    return FS.FriendGates(kw.get("adx"), kw.get("quiet"), kb), kb


def test_adx_gate_uses_the_trend_judge_adx_and_blocks_below_20():
    from paperbot.trendjudge import vote_arrays
    for seed, drift in ((5, 0.0), (6, 0.004)):
        rng = np.random.default_rng(seed)
        c = 100 * np.exp(np.cumsum(drift + rng.normal(0, 0.003, 2000)))
        o = np.r_[c[0], c[:-1]]
        rows4 = [[int(T - (1999 - i) * H4 - H4), float(o[i]), float(max(o[i], c[i]) * 1.002),
                  float(min(o[i], c[i]) * 0.998), float(c[i]), 100.0] for i in range(2000)]
        now = [T + MIN + 5_000]
        g, _kb = _gates({"4h": rows4}, now, adx=FS.ADX_DEFAULT)
        why, info = g.check("BTCUSDT", "15m", 1, T + 30 * MIN)        # a 15m close inside the 4h bar: the one before
        df = pd.DataFrame(rows4, columns=["t", "open", "high", "low", "close", "volume"])
        df["ts"] = pd.to_datetime(df.t, unit="ms")
        full = float(vote_arrays(df)["adx"][-1])                       # the judge files' 4h_adx (the whole history)
        assert info["adx"]["adx"] == pytest.approx(full, rel=1e-9) and info["adx"]["bar_close"] == T
        if full < 20:
            assert why == f"4시간 ADX 약함: {full:.1f} (20 미만)"
        else:
            assert why == "" and info["adx"]["text"] == f"4시간 ADX {full:.0f}"
    assert FS.adx_words("4h", math.nan) == "4시간 ADX 모름"


def test_adx_gate_unreadable_blocks_and_says_why():
    feed = Feed({"4h": _rows(1600, T - H4, H4)})
    feed.fail = True
    g = FS.FriendGates(FS.ADX_DEFAULT, None, FS.KlineBars(feed, lambda: T + 65_000))
    assert g.block("BTCUSDT", "15m", 1, T).startswith("4시간 ADX를 못 읽음(진입 안 함): BTCUSDT 4h 봉을 못 받음: OSError")


@pytest.mark.parametrize("last, why", [(0.64, ""), (0.6401, "거래량 많음: 신호 봉 0.64배 (앞 20봉 평균의 0.64배 넘음)"),
                                       (0.81, "거래량 많음: 신호 봉 0.81배 (앞 20봉 평균의 0.64배 넘음)"), (0.2, "")])
def test_quiet_gate_blocks_a_bar_above_064_times_the_20_before(last, why):
    vol = [100.0] * 40 + [last * 100.0]
    now = [T + MIN + 5_000]
    g, _ = _gates({"15m": _rows(41, T - M15, M15, vol=vol)}, now, quiet=FS.QUIET_DEFAULT)
    w, info = g.check("ETHUSDT", "15m", -1, T)
    assert w == why and info["quiet"]["ratio"] == pytest.approx(last)
    assert info["quiet"]["text"] == f"거래량 {last:.2f}배(앞 20봉 평균 대비)"


def test_quiet_gate_unknown_passes_nothing_traded_before_blocks_unreadable_blocks():
    now = [T + MIN + 5_000]
    g, _ = _gates({"15m": _rows(15, T - M15, M15)}, now, quiet={})            # fewer than 21 bars: unknown, passes
    assert g.check("ETHUSDT", "15m", 1, T)[0] == "" and math.isnan(FS.volume_ratio([1.0] * 15))
    g, _ = _gates({"15m": _rows(30, T - M15, M15, vol=[0.0] * 29 + [5.0])}, now, quiet={})
    assert g.check("ETHUSDT", "15m", 1, T)[0].startswith("거래량 많음")        # inf > 0.64, as the research's mask
    g, _ = _gates({"15m": _rows(30, T - 2 * M15, M15)}, now, quiet={})        # the signal bar itself is missing
    assert g.block("ETHUSDT", "15m", 1, T).startswith("거래량 판단에 쓸 15분봉을 못 읽음(진입 안 함)")


def test_both_gates_in_order_and_the_chain_with_the_vwap_gates():
    rows = {"15m": _rows(41, T - M15, M15, vol=[100.0] * 40 + [90.0]), "4h": _rows(1600, T - H4, H4)}
    now = [T + MIN + 5_000]
    g, _ = _gates(rows, now, adx={"min": 99}, quiet={})
    why, info = g.check("SOLUSDT", "15m", 1, T)
    assert why.startswith("4시간 ADX 약함") and "quiet" not in info               # the first reason blocks
    g2, _ = _gates(rows, now, adx={"min": 1}, quiet={})
    why, info = g2.check("SOLUSDT", "15m", 1, T)
    assert why.startswith("거래량 많음") and set(info) == {"adx", "quiet"}

    class Vote:
        def check(self, symbol, tf, side, bar_close):
            return "", {"vote": {"text": "4시간 상승(상승 3·하락 0·중립 1)"}}
    chain = FS.GateChain(Vote(), g2)
    why, info = chain.check("SOLUSDT", "15m", 1, T)
    assert why.startswith("거래량 많음") and set(info) == {"vote", "adx", "quiet"}
    assert C.gates_text(info) == "4시간 상승(상승 3·하락 0·중립 1) · " + info["adx"]["text"] + " · " + info["quiet"]["text"]


# ---------------------------------------------------------------- config
def test_gate_config_problems(tmp_path):
    from test_combo import cfg_of
    ok = cfg_of(tmp_path, members=[{"strategy": "FRIEND_ROC", "tf": "15m"}], adx_gate={"tf": "4h", "min": 20},
                quiet_gate={"bars": 20, "max_ratio": 0.64})
    assert ok.problems() == []
    bad = {"adx_gate": [{"tf": "15m"}, {"min": 0}, {"min": True}, {"tf": "4h", "x": 1}, "4h", {"min": 120}],
           "quiet_gate": [{"bars": 1}, {"bars": 20.0}, {"max_ratio": 0}, {"max_ratio": 11}, {"y": 2}, []]}
    for k, vals in bad.items():
        for v in vals:
            probs = cfg_of(tmp_path, members=[{"strategy": "FRIEND_ROC", "tf": "15m"}], **{k: v}).problems()
            assert any(k in p for p in probs), (k, v, probs)
    assert FS.adx_text(FS.ADX_DEFAULT) == "4시간 ADX(14)가 20 미만이면 진입 안 함(추세 약함)"
    assert FS.quiet_text(FS.QUIET_DEFAULT) == "신호 봉 거래량이 앞 20봉 평균의 0.64배보다 크면 진입 안 함(조용한 봉만)"
    assert C.FRIEND == FS.FRIEND and C.member_ko(FS.FRIEND) == FS.FRIEND_KO

"""paperbot/rmember.py, the research members of the combined bot (the 5-year search's settings, live):

- the settings parse (stop / entry / invert / filter / disp / off) and their refusals;
- the definitions equal the search's pandas code (scratchpad loop: tags2, regime, regime2, dispf, autosearch, ck3) on
  fixed arrays: EMA sign, ADX regime and its 5 levels, the 1h volatility rank, the 7-day position, the 24h open
  interest bucket, the swing and pct stops, the signal-bar displacement;
- RData on fake fetchers: the signal-time tags and the entry-minute dimensions, no bar after t is read;
- combo: a research member keeps its own numbers (even the defaults), the pct / swing / atr stops in the engine, the
  displacement and off checks at the entry minute, and the break entry (the minute after the break, or none)."""

import dataclasses
import json
import math

import numpy as np
import pandas as pd
import pytest

from paperbot import combo as C
from paperbot import rmember as RM
from paperbot.margin import BracketTier, Brackets
from paperbot.models import Bar, Signal
from paperbot.notify import ListNotifier
from paperbot.store3 import Store3

MIN = 60_000
H1 = 3_600_000
H4 = 14_400_000
T0 = 1_791_158_400_000                        # 2026-10-05 00:00 UTC (a Monday 09:00 KST)
BRK = Brackets([BracketTier(300_000, 125, 0.004, 0.0), BracketTier(800_000, 50, 0.005, 300.0)])


def _walk(n, seed, p0=100.0):
    r = np.random.default_rng(seed)
    c = p0 * np.exp(np.cumsum(r.normal(0, 0.01, n)))
    h = c * (1 + np.abs(r.normal(0, 0.004, n)))
    l = c * (1 - np.abs(r.normal(0, 0.004, n)))
    return h, l, c


# ---------------------------------------------------------------- settings
def test_parse_and_refusals():
    r = RM.parse_spec({"stop": ["swing", 10], "entry": "break", "invert": True, "filter": [["ctr4", 1], ["side", -1]],
                       "disp": ["body", 1.5], "off": [["hr", 3], ["reg5side", 5]], "cell": "x"}, "t")
    assert r.stop == ("swing", 10.0) and r.entry == "break" and r.invert and r.filter == (("ctr4", 1), ("side", -1))
    assert r.disp == ("body", 1.5) and r.off == frozenset({("hr", 3), ("reg5side", 5)})
    assert RM.parse_spec({"numbers": {}}, "t") is None
    for bad, text in [({"stop": ["roe", 1]}, "stop"), ({"stop": ["pct", 2], "entry": "later"}, "entry"),
                      ({"stop": ["pct", 2], "filter": [["nope", 1]]}, "filter"),
                      ({"stop": ["pct", 2], "off": [["hr", "3"]]}, "off"),
                      ({"stop": ["pct", 2], "disp": ["huge", 1]}, "disp"),
                      ({"stop": ["pct", 2], "invert": 1}, "invert")]:
        with pytest.raises(RM.RSpecError, match=text):
            RM.parse_spec(bad, "t")
    assert "끄기" in RM.describe(r) and "돌파" in RM.describe(r)


# ---------------------------------------------------------------- definitions = the search's pandas code
def test_ewm_ema_sign_and_regimes_equal_pandas():
    h, l, c = _walk(400, 1, 30000.0)
    x = np.r_[np.nan, np.nan, c[2:]]
    assert np.allclose(RM.ewm_mean(x, 0.1), pd.Series(x).ewm(alpha=0.1, adjust=False).mean().to_numpy(), equal_nan=True)
    e50 = pd.Series(c).ewm(span=50, adjust=False).mean()
    assert (RM.ema_sign(c) == np.sign(c - e50).to_numpy()).all()
    s = RM.ema_sign(c, cold=50)
    assert (s[:50] == 0).all() and (s[50:] == np.sign(c - e50).to_numpy()[50:]).all()
    # regime.series / regime2._btc5
    up = h - np.r_[h[0], h[:-1]]; dn = np.r_[l[0], l[:-1]] - l
    pdm = np.where((up > dn) & (up > 0), up, 0.0); mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = np.maximum.reduce([h - l, np.abs(h - np.r_[c[0], c[:-1]]), np.abs(l - np.r_[c[0], c[:-1]])])
    a = 1 / 14
    atr = pd.Series(tr).ewm(alpha=a, adjust=False).mean()
    pdi = 100 * pd.Series(pdm).ewm(alpha=a, adjust=False).mean() / atr
    mdi = 100 * pd.Series(mdm).ewm(alpha=a, adjust=False).mean() / atr
    adx = (100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)).ewm(alpha=a, adjust=False).mean().to_numpy()
    ema = e50.to_numpy()
    reg = np.where(adx < 20, 2, np.where(c > ema, 0, 1))
    upd = c > ema
    r5 = np.where(adx < 20, 4, np.where(upd, np.where(adx >= 30, 0, 1), np.where(adx >= 30, 2, 3)))
    g, g5 = RM.regimes(h, l, c)
    assert np.allclose(RM.adx14(h, l, c), adx, equal_nan=True) and (g == reg).all() and (g5 == r5).all()
    assert set(np.unique(g5)) >= {0, 1, 2, 3, 4} or len(np.unique(g5)) >= 3


def test_vol_rank_equals_pandas_rolling_rank():
    h, l, c = _walk(900, 2)
    s = pd.DataFrame({"h": h, "l": l, "c": c})
    pc = s.c.shift(1)
    tr = np.maximum(s.h - s.l, np.maximum((s.h - pc).abs(), (s.l - pc).abs()))
    atrp = (tr.ewm(alpha=1 / 14, adjust=False).mean() / s.c).to_numpy()
    want = pd.Series(atrp).rolling(500, min_periods=200).rank(pct=True).to_numpy()
    got = RM.vol_rank(h, l, c)
    assert np.allclose(got, want, equal_nan=True)


def test_position_oi_swing_pct_and_displacement():
    assert [RM.pos_bucket(c, 110.0, 100.0) for c in (111, 99, 101, 105, 109, 100, 110)] == [4, 0, 1, 2, 3, 1, 3]
    assert RM.pos_bucket(105.0, float("nan"), 100.0) == 2 and RM.pos_bucket(100.0, 100.0, 100.0) == 2
    mt = np.array([T0 - 86_400_000 - 300_000, T0 - 300_000], np.int64)
    assert RM.oi_bucket(mt, np.array([100.0, 106.0]), T0) == 2
    assert RM.oi_bucket(mt, np.array([100.0, 94.0]), T0) == 0
    assert RM.oi_bucket(mt, np.array([100.0, 101.0]), T0) == 1
    assert RM.oi_bucket(mt, np.array([100.0, 101.0]), T0 + 2 * H1) == 3      # last snapshot older than an hour
    assert RM.oi_bucket(mt[1:], np.array([101.0]), T0) == 3                   # nothing 24 hours before
    # autosearch swing: (px - lowest low) / px + 0.1 %, at least 0.3 %
    lows, highs = np.array([99.0, 98.0, 99.5]), np.array([101.0, 102.0, 100.5])
    assert abs(RM.swing_frac(lows, highs, 1, 100.0) - 0.021) < 1e-12
    assert abs(RM.swing_frac(lows, highs, -1, 100.0) - 0.021) < 1e-12
    assert RM.swing_frac(np.array([99.95]), np.array([100.1]), 1, 100.0) == 0.003
    # ck3.trade_pct: min(frac x fill, |fill - liq| - 0.2 % of fill)
    assert abs(RM.pct_stop(1, 100.0, 100.02, 0.01, 97.6) - (100.02 - 1.0002)) < 1e-9
    widest = (abs(100.02 - 97.6) - 0.002 * 100.02) * (1 - 1e-6)
    assert abs(RM.pct_stop(1, 100.0, 100.02, 0.05, 97.6) - (100.02 - widest)) < 1e-9
    assert RM.pct_stop(1, 100.0, 100.02, 0.05, 100.0) is None
    hs, ls = np.array([101.0, 103.0]), np.array([99.0, 100.0])                 # range 4 = 2 ATR of 2
    assert RM.disp_ok(("range", 2.0), 1, 2.0, hs, ls, 100.0, 102.0)
    assert not RM.disp_ok(("range", 2.5), 1, 2.0, hs, ls, 100.0, 102.0)
    assert RM.disp_ok(("small", 2.5), 1, 2.0, hs, ls, 100.0, 102.0)
    assert RM.disp_ok(("body", 1.0), 1, 2.0, hs, ls, 100.0, 102.0)             # body +2 = 1 ATR, long
    assert not RM.disp_ok(("body", 1.0), -1, 2.0, hs, ls, 100.0, 102.0)


def test_kst_session_and_weekday():
    assert RM.kst_dow(T0) == 0 and RM.kst_hour(T0) == 9 and RM.session_of(T0) == 0
    assert RM.session_of(T0 + 8 * H1) == 1 and RM.session_of(T0 + 13 * H1) == 2 and RM.session_of(T0 - 2 * H1) == 3
    assert RM.kst_dow(T0 + 5 * 86_400_000) == 5


# ---------------------------------------------------------------- RData on fake fetchers
class Feed:
    """1m bars of two coins for 9 days before T0 + 1 day; 1h / 4h bars from them; funding; open interest."""

    def __init__(self):
        n = 13 * 1440
        self.t0 = T0 - 11 * 86_400_000
        self.ts = self.t0 + MIN * np.arange(n)
        self.bars = {}
        for k, s in enumerate(("BTCUSDT", "ETHUSDT")):
            h, l, c = _walk(n, 10 + k, 60000.0 if k == 0 else 2500.0)
            o = np.r_[c[0], c[:-1]]
            self.bars[s] = (o, np.maximum(h, o), np.minimum(l, o), c)
        self.now = T0
        self.calls = []

    def klines(self, symbol, interval, start, end):
        self.calls.append((symbol, interval, start, end))
        o, h, l, c = self.bars[symbol]
        ms = {"1m": MIN, "1h": H1, "4h": H4}[interval]
        df = pd.DataFrame({"ts": self.ts, "o": o, "h": h, "l": l, "c": c})
        df = df[df.ts + MIN <= self.now]
        g = df.groupby(df.ts // ms)
        out = pd.DataFrame({"t": g.ts.first().index * ms, "o": g.o.first(), "h": g.h.max(), "l": g.l.min(), "c": g.c.last()})
        out = out[(out.t >= start) & (out.t < end) & (out.t + ms <= self.now)]
        return out[["t", "o", "h", "l", "c"]].to_numpy().tolist()

    def funding(self, symbol, start):
        return [(t, 0.0001 if symbol == "BTCUSDT" else -0.0002) for t in range(T0 - 3 * 86_400_000, self.now, 8 * H1)
                if t >= start]

    def oi(self, symbol, start, end):
        return [(t, 100.0 + (t - start) / 86_400_000 * 10) for t in range(start - start % 300_000, end, 300_000)
                if t <= self.now]


def test_rdata_tags_and_dims_match_the_search_and_never_read_ahead():
    f = Feed()
    rd = RM.RData(["BTCUSDT", "ETHUSDT"], f.klines, f.funding, f.oi)
    t = T0 + 5 * H1 + 15 * MIN                                     # a 15m bar close
    f.now = t + 5_000
    tags = rd.signal_tags("ETHUSDT", 1, t)
    # the search's pandas: ctr4, mom24, vol3, fund; BTC trend with the first 50 bars at 0
    b4 = pd.DataFrame(f.klines("ETHUSDT", "4h", t - 1000 * H4, t - t % H4), columns=["t", "o", "h", "l", "c"])
    s4 = np.sign(b4.c - b4.c.ewm(span=50, adjust=False).mean()).to_numpy()
    assert tags["ctr4"] == int(s4[-1] == 1)
    b1 = pd.DataFrame(f.klines("ETHUSDT", "1h", t - 1500 * H1, t - t % H1), columns=["t", "o", "h", "l", "c"])
    j1 = len(b1) - 1
    j0 = int(np.searchsorted((b1.t + H1).to_numpy(), t - 24 * H1, side="right")) - 1
    assert tags["mom24"] == int(np.sign(b1.c[j1] / b1.c[j0] - 1) == 1)
    assert tags["fund"] == 0 and rd.signal_tags("BTCUSDT", 1, t)["fund"] == 1
    assert tags["session"] == 0 and tags["weekend"] == 0
    # entry minute dims: the 7-day range ending an hour before, from 1m bars
    o, h, l, c = f.bars["ETHUSDT"]
    e = int(np.searchsorted(f.ts, t))
    hi = pd.Series(h).rolling(10080, min_periods=5000).max().shift(60).to_numpy()[e]
    lo = pd.Series(l).rolling(10080, min_periods=5000).min().shift(60).to_numpy()[e]
    d = rd.entry_dims("ETHUSDT", 1, t, float(o[e]), tags)
    assert d["pos"] == RM.pos_bucket(float(o[e]), hi, lo)
    assert d["hr"] == 14 and d["hb"] == 3 and d["dow"] == 0 and d["symside"] == 3 and d["oi24"] == 2
    assert d["regside"] == d["reg"] * 2 + 1 and d["posside"] == d["pos"] * 2 + 1
    assert all(int(c[3]) <= f.now for c in f.calls)                 # no fetch reaches past now


# ---------------------------------------------------------------- combo
def test_research_member_keeps_its_numbers_and_label():
    core = ["V39_ALL", "N03_ADX_GC"]
    d = C.default_numbers("core", "N03_ADX_GC")
    ms = C.resolve_members([{"strategy": "N03_ADX_GC", "tf": "15m", "numbers": d, "stop": ["atr", 3], "entry": "now"},
                            {"strategy": "N03_ADX_GC", "tf": "15m", "numbers": d, "stop": ["pct", 2], "off": [["hr", 1]]}],
                           core=core)
    assert all(m.custom and m.research is not None for m in ms)
    assert [m.label for m in ms] == [f"N03_ADX_GC@15m#1~{RM.spec_tag(ms[0].research)}",
                                     f"N03_ADX_GC@15m#2~{RM.spec_tag(ms[1].research)}"]
    assert RM.spec_tag(ms[0].research) != RM.spec_tag(ms[1].research)      # other settings, other label
    with pytest.raises(C.ComboError, match="numbers"):
        C.resolve_members([{"strategy": "N03_ADX_GC", "tf": "15m", "stop": ["atr", 3]}], core=core)
    with pytest.raises(C.ComboError, match="when"):
        C.resolve_members([{"strategy": "N03_ADX_GC", "tf": "15m", "numbers": d, "stop": ["atr", 3],
                            "when": {"side": "long"}}], core=core)


def test_open_interest_failure_refuses_members_that_switch_off_oi_buckets():
    r = RM.parse_spec({"stop": ["pct", 1], "off": [["oi24", 2]]}, "t")
    r0 = RM.parse_spec({"stop": ["pct", 1], "off": [["hr", 3]]}, "t")
    dims = {"oi24": 3, "oi_failed": True, "hr": 5}
    assert RM.off_hits(r, dims) == ["oi24=읽기 실패"] and RM.off_hits(r0, dims) == []
    assert RM.off_hits(r, {"oi24": 2, "oi_failed": False, "hr": 5}) == ["oi24=2"]


def test_failed_fetch_is_not_repeated_for_a_minute():
    calls = []

    def boom(*a):
        calls.append(a)
        raise OSError("down")
    rd = RM.RData(["BTCUSDT"], boom, boom, boom)
    for k in range(3):
        with pytest.raises(Exception):
            rd.bars("BTCUSDT", "4h", T0 + k * 1000)
    assert len(calls) == 1
    with pytest.raises(Exception):
        rd.bars("BTCUSDT", "4h", T0 + 61_000)
    assert len(calls) == 2


def _cfg(tmp_path, members=None):
    return C.ComboConfig.from_dict(dict(
        paper_db=str(tmp_path / "paper3.db"), db=str(tmp_path / "combo.db"), telegram=False, margin=0.4,
        members=members or [{"strategy": "V39_ALL", "tf": "15m"}], max_loss_frac=0.35, rank=["order"],
        ladder={"first_lock": 0.1, "step": 0.03, "trigger_gap": 0.01}))


def _sig(sym="BTCUSDT", side=1, ref=60000.0, atr=60.0, **meta):
    return Signal(ts=T0 - 1, symbol=sym, timeframe="15m", strategy_id="N03_ADX_GC", side=side, stop_price=0.0,
                  tier="best", score=3.0, atr=atr, meta={"ref_price": ref, "stop_dist": 2 * atr, "member_order": 1,
                                                          "member": "N03_ADX_GC@15m#1~x", **meta})


def test_engine_research_stops(tmp_path):
    cfg = _cfg(tmp_path)
    e = C.ComboEngine(C.settings_of(cfg), {"BTCUSDT": BRK, "ETHUSDT": BRK}, combo=cfg, symbol_specs={})
    bar = Bar("BTCUSDT", T0, T0 + MIN - 1, 60000.0, 60010.0, 59990.0, 60000.0)
    slip = e.s.slippage_frac
    fill = 60000.0 * (1 + slip)
    s, why = e._with_stop(_sig(rstop=["pct", 1.0]), bar)
    assert why is None and abs((60000.0 - s.meta["stop_dist"]) - (fill - 0.01 * fill)) < 1e-6
    assert s.meta["liq_buffer_atr"] == 0.0
    # 3% at 40x is past liquidation (~2.1%): pulled in to 0.2% of the fill inside it, the entry goes ahead
    s, why = e._with_stop(_sig(rstop=["pct", 3.0]), bar)
    room = C.liq_distance(1, fill, 40, 100.0 * 0.4 * 40, BRK) * fill
    want = fill - (room - 0.002 * fill) * (1 - 1e-6)
    assert why is None and abs((60000.0 - s.meta["stop_dist"]) - want) < 1e-6 and "pulled in" in s.meta["stop_rule"]
    e.wallet = 100.0
    assert e._try_enter(s, bar) and e.position is not None
    # swing: below the window's lowest low + 0.1 %
    e2 = C.ComboEngine(C.settings_of(cfg), {"BTCUSDT": BRK}, combo=cfg, symbol_specs={})
    s, why = e2._with_stop(_sig(rstop=["swing", 10], rswing={"lo": 59700.0, "hi": 60300.0}), bar)
    frac = (60000.0 - 59700.0) / 60000.0 + 0.001
    assert why is None and abs((60000.0 - s.meta["stop_dist"]) - (fill - frac * fill)) < 1e-6
    s, why = e2._with_stop(_sig(side=-1, rstop=["swing", 10], rswing={"lo": 59700.0, "hi": 60300.0}), bar)
    fill_s = 60000.0 * (1 - slip)
    assert why is None and abs((60000.0 + s.meta["stop_dist"]) - (fill_s + frac * fill_s)) < 1e-6
    # atr k: the house atr_fit with that k
    s, why = e2._with_stop(_sig(rstop=["atr", 4.0]), bar)
    assert why is None and abs(s.meta["stop_dist"] - 240.0) < 1e-9


class RWorld:
    """A paper3.db stepping one minute at a time and a combined bot with one research member, signals put by hand."""

    def __init__(self, tmp_path, spec):
        self.paper = Store3(str(tmp_path / "paper3.db"))
        self.feed = Feed()
        self.cfg = _cfg(tmp_path, [dict({"strategy": "N03_ADX_GC", "tf": "15m",
                                         "numbers": C.default_numbers("core", "N03_ADX_GC")}, **spec)])
        self.members = C.resolve_members(self.cfg.members, core=["N03_ADX_GC"])
        self.store = Store3(self.cfg.db)
        self.note = ListNotifier()
        br = {s: BRK for s in self.cfg.symbols}
        self.book = C.build_book(self.cfg, C.settings_of(self.cfg), br, self.store, self.note, {})
        self.rd = RM.RData(["BTCUSDT", "ETHUSDT"], self.feed.klines, self.feed.funding, self.feed.oi)
        self.run = C.ComboRunner(self.cfg, self.members, self.book, self.store, self.note, None,
                                 now_ms=lambda: self.feed.now, prices=self.prices, rdata=self.rd)
        self.run.cursor = 0
        self.book.last_ts = T0 - MIN

    def prices(self):
        t = self.feed.now - self.feed.now % MIN
        o = self.feed.bars["BTCUSDT"][0][int(np.searchsorted(self.feed.ts, t))]
        return {"BTCUSDT": (o, o)}

    def minute(self, t):
        rows = []
        for s in ("BTCUSDT", "ETHUSDT"):
            o, h, l, c = self.feed.bars[s]
            i = int(np.searchsorted(self.feed.ts, t))
            rows.append({"ts": t, "symbol": s, "open": o[i], "high": h[i], "low": l[i], "close": c[i], "volume": 1.0,
                         "mark_open": o[i], "mark_high": h[i], "mark_low": l[i], "mark_close": c[i],
                         "close_time": t + MIN - 1, "processed_at": t + MIN})
        self.paper.live_bars(rows)
        self.paper.commit()
        self.feed.now = t + MIN + 5_000
        self.run.poll()

    def signal(self, t, side=1):
        m = self.members[0]
        atr = float(self.feed.bars["BTCUSDT"][3][int(np.searchsorted(self.feed.ts, t)) - 1]) * 0.003
        sig = C.make_signal(self.cfg, m, t, "BTCUSDT", side, atr, None, self.feed.now, 0, {}, "custom")
        self.run._research_signal(m, sig, t)

    def statuses(self):
        return [r for r in self.store.conn.execute("SELECT bar_close, status, data FROM signal_log ORDER BY id")]


def test_runner_now_entry_and_off_bucket(tmp_path):
    w = RWorld(tmp_path, {"stop": ["pct", 1.0], "entry": "now"})
    t = T0 + 15 * MIN
    for k in range(15):
        w.minute(T0 + k * MIN)
    w.signal(t)
    w.minute(t)
    e = w.book.engines[C.ACCOUNT]
    assert e.position is not None and e.position.entry_time == t
    assert e.position.signal.meta["rdims"]["hr"] == 9
    # the same with hour 9 KST switched off: filtered at the entry minute, nothing entered
    w2 = RWorld(tmp_path / "b", {"stop": ["pct", 1.0], "entry": "now", "off": [["hr", 9]]}) \
        if (tmp_path / "b").mkdir() is None else None
    for k in range(15):
        w2.minute(T0 + k * MIN)
    w2.signal(t)
    w2.minute(t)
    assert w2.book.engines[C.ACCOUNT].position is None
    assert any(s == "FILTERED" and "hr=9" in _why(d) for _, s, d in w2.statuses())


def _why(d):
    return json.loads(d).get("why", "")


@pytest.mark.parametrize("broke", [True, False])
def test_runner_break_entry_waits_for_the_break(tmp_path, broke):
    w = RWorld(tmp_path, {"stop": ["pct", 1.0], "entry": "break"})
    t = T0 + 15 * MIN
    for k in range(15):
        w.minute(T0 + k * MIN)
    w.signal(t)
    assert len(w.run.breaks) == 1
    o, h, l, c = w.feed.bars["BTCUSDT"]
    i0 = int(np.searchsorted(w.feed.ts, t))
    level = h[i0 - 15:i0].max()
    h[i0:i0 + 15] = np.minimum(h[i0:i0 + 15], level)          # no minute beyond the signal bar's high ...
    if broke:
        h[i0 + 3] = level * 1.0005                              # ... but the 4th
    for k in range(i0, i0 + 17):
        w.minute(int(w.feed.ts[k]))
    e = w.book.engines[C.ACCOUNT]
    held = [x.entry_time for x in e.trades] + ([e.position.entry_time] if e.position else [])
    if broke:
        assert held == [int(w.feed.ts[i0 + 4])]                  # the open of the minute after the break
        assert any(s == "SUBMITTED" and "돌파 확인" in _why(d) for _, s, d in w.statuses())
    else:
        assert not held and any("돌파 없음" in _why(d) for _, s, d in w.statuses())
    assert not w.run.breaks

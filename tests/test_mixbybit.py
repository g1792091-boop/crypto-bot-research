"""바이비트 봇 (owners 2026-10-29): paperbot/friendtrend.py and the two friend rules of paperbot/mixchop.py on Bybit.

- the friend's trend: the owners' vote rule on every combination of four votes; the live code equals the research copy
  (analysis/rangefriend1029/friendtrend.py) on a long series; 1,500 bars read the same last values as a longer history;
- the OBV pane and the Stoch RSI pane against a bar-by-bar transcription of the Pine scripts' state lines; a hairline
  bar (the line on the wrong side of its signal while the state is kept) is light;
- the rules: a light -> dark turn / a ● on the right side of 50 enters only on the friend's trend of its side; 2
  sideways or 2-2 is no entry; the stop is ATR14 x 3 and the liquidation guard holds;
- the deploy configs (live and paper) load: Bybit, the name, 7 coins at 40x (ZEC 20x), stop ATR x 3, the net ladder
  10 -> 8 then 5 % steps every minute, margin 40 %, the pauses; wrong ones are refused;
- a whole live cycle on the fake Bybit exchange (tests/fakebybit.py): one-way mode and isolated margin at the start, the
  leverage read back, a market entry with a resting stop, the ladder moving it on 1m bars, the stop firing and the
  P&L from the balance; the liquidation room from Bybit's risk-limit tiers;
- one close: the rules' order on one coin, the coins' order between coins, the entry message names the rule."""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from paperbot import bybit as BY
from paperbot import friendtrend as FT
from paperbot import mixchop as M

sys.path.insert(0, os.path.dirname(__file__))
from fakebybit import FakeBybit  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "deploy" / "mixbybit.live.json"
PAPER = ROOT / "deploy" / "mixbybit.paper.json"
T0 = 1_800_000_000_000 - 1_800_000_000_000 % M.MIN30


def walk(n, seed=1, px=100.0, vol=0.004):
    """A random 30m price walk with volume: (open, high, low, close, volume)."""
    rng = np.random.default_rng(seed)
    c = px * np.exp(np.cumsum(rng.normal(0, vol, n)))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + rng.uniform(0, vol, n))
    lo = np.minimum(o, c) * (1 - rng.uniform(0, vol, n))
    return o, h, lo, c, rng.uniform(100, 1000, n)


def frame(n, seed=1, end_ms=T0, **kw):
    o, h, lo, c, v = walk(n, seed, **kw)
    t = end_ms - M.MIN30 * np.arange(n, 0, -1)
    return pd.DataFrame({"open_ms": t.astype(np.int64), "open": o, "high": h, "low": lo, "close": c, "volume": v})


# ---------------------------------------------------------------- the friend's trend
def test_the_vote_rule_on_every_combination():
    import itertools
    for vs in itertools.product((1, -1, 0), repeat=4):
        up, dn, side = vs.count(1), vs.count(-1), vs.count(0)
        want = 0 if side >= 2 else (1 if up >= 2 and up > dn else (-1 if dn >= 2 and dn > up else 0))
        got = int(FT.trend_of(*[np.array([x]) for x in vs])[0])
        assert got == want, vs
    # the owners' cases: two sideways, two up and two down
    assert FT.trend_of([1], [1], [0], [0])[0] == 0 and FT.trend_of([1], [1], [-1], [-1])[0] == 0
    assert FT.trend_of([1], [1], [0], [-1])[0] == 1 and FT.trend_of([-1], [1], [-1], [-1])[0] == -1


def test_the_live_code_equals_the_research_copy():
    sys.path.insert(0, str(ROOT / "analysis" / "rangefriend1029"))
    try:
        import friendtrend as research
    finally:
        sys.path.pop(0)
    o, h, lo, c, v = walk(3000, seed=7)
    a, b = research.votes(o, h, lo, c, v), FT.votes(o, h, lo, c, v)
    for k in ("line", "ema", "chop", "st", "trend"):
        assert (a[k][60:] == b[k][60:]).all(), k


def test_fifteen_hundred_bars_read_the_same_last_values():
    o, h, lo, c, v = walk(4000, seed=11)
    cut = slice(-1500, None)
    full, part = FT.votes(o, h, lo, c, v), FT.votes(o[cut], h[cut], lo[cut], c[cut], v[cut])
    for k in ("line", "ema", "chop", "st", "trend"):
        assert (full[k][-300:] == part[k][-300:]).all(), k
    P, Q = FT.obv_pane(h, lo, c, v), FT.obv_pane(h[cut], lo[cut], c[cut], v[cut])
    assert (P["cs"][-300:] == Q["cs"][-300:]).all() and (P["dark"][-300:] == Q["dark"][-300:]).all()
    S, U = FT.stoch_pane(c), FT.stoch_pane(c[cut])
    assert (S["xs"][-300:] == U["xs"][-300:]).all()
    assert np.allclose(S["k"][-300:], U["k"][-300:])


def test_the_obv_pane_follows_the_script_bar_by_bar():
    o, h, lo, c, v = walk(800, seed=3)
    P = FT.obv_pane(h, lo, c, v)
    line, sig = P["line"], P["sig"]
    ar = M.avg_rsi(c)
    trend = cs = 0
    prev_hist = None
    for i in range(len(c)):                    # the Pine lines, one bar at a time
        if np.isfinite(ar[i]):
            trend = 1 if ar[i] > 50 else (-1 if ar[i] < 50 else trend)
        gold = bool(np.isfinite(sig[i]) and line[i] > sig[i])
        cs = 1 if (trend == 1 and gold) else (-1 if (trend == -1 and not gold) else cs)
        assert P["cs"][i] == cs, i
        eps = max(abs(line[i]) * 1e-6, 1e-9)
        cond = (min(sig[i], line[i] - eps) if cs == 1 else max(sig[i], line[i] + eps) if cs == -1 else sig[i])
        hist = abs(line[i] - cond) if np.isfinite(cond) else None
        grew = hist is not None and prev_hist is not None and hist > prev_hist
        real = (cs == 1 and gold) or (cs == -1 and not gold and np.isfinite(sig[i]))
        assert bool(P["dark"][i]) == (grew and real), i
        prev_hist = hist
    # the turns: light -> dark on the same colour only
    cs_, dk = P["cs"], P["dark"]
    turns = [i for i in range(1, len(c)) if cs_[i] == cs_[i - 1] != 0 and dk[i] and not dk[i - 1]]
    assert turns
    for i in turns[:20]:
        assert FT.obv_turn(h[:i + 1], lo[:i + 1], c[:i + 1], v[:i + 1]) == cs_[i]
    assert FT.obv_turn(h[:turns[0]], lo[:turns[0]], c[:turns[0]], v[:turns[0]]) in (0, cs_[turns[0] - 1])


def test_a_hairline_bar_is_light():
    o, h, lo, c, v = walk(1500, seed=5)
    P = FT.obv_pane(h, lo, c, v)
    hair = ((P["cs"] == 1) & ~(P["line"] > P["sig"])) | ((P["cs"] == -1) & (P["line"] > P["sig"]))
    assert hair.any() and not P["dark"][hair].any()
    assert np.allclose(np.abs(P["hist"][hair & np.isfinite(P["sig"])]),
                       np.maximum(np.abs(P["line"][hair & np.isfinite(P["sig"])]) * 1e-6, 1e-9))


def test_the_stoch_pane_follows_the_script_bar_by_bar():
    o, h, lo, c, v = walk(800, seed=9)
    S = FT.stoch_pane(c)
    rx = M.rsi(c, 14)
    st = np.full(len(c), np.nan)
    for i in range(10, len(c)):
        w = rx[i - 10:i + 1]
        if np.isfinite(w).all() and w.max() != w.min():
            st[i] = 100 * (rx[i] - w.min()) / (w.max() - w.min())
    kr = np.nan_to_num(pd.Series(st).rolling(4, min_periods=4).mean().to_numpy(), nan=50.0)
    k = M.ema(kr, 3)
    d = np.nan_to_num(pd.Series(k).rolling(6, min_periods=6).mean().to_numpy(), nan=50.0)
    assert np.allclose(S["k"][10:], k[10:], equal_nan=True) and np.allclose(S["d"], d)
    xs = 0
    for i in range(len(c)):
        prev = xs
        if np.isfinite(k[i]):
            xs = 1 if k[i] - d[i] > 2 else (-1 if d[i] - k[i] > 2 else xs)
        assert S["xs"][i] == xs and S["gold"][i] == (xs == 1 and prev != 1) and S["dead"][i] == (xs == -1 and prev != -1)
    g = np.flatnonzero(S["gold"])
    i = int(g[-1])
    sg = FT.stoch_signal(c[:i + 1])
    assert sg["cross"] == "gold" and sg["side"] == (1 if S["k"][i] < 50 else 0)


# ---------------------------------------------------------------- the two rules
def _coin(lev=40, sl=3.0, sym="BTCUSDT"):
    return M.Coin(sym, 0.0, sl, 100.0, lev)


def _trend(t, **votes):
    d = {"line": t or 1, "ema": t or 1, "chop": t, "st": t}
    d.update(votes)
    return {"trend": t, **d, "ema_rsi": 55.0, "chop_zone": 2 * d["chop"]}


@pytest.mark.parametrize("rule", ["obv", "srsi"])
def test_a_signal_enters_only_with_the_friends_trend(monkeypatch, rule):
    b30 = frame(400, vol=0.002)                          # ATR x 3 inside 1/40 - 0.5 %
    ce = T0
    co = _coin()
    sig = {"side": 1, "cross": "gold", "k": 31.2, "d": 27.0}

    def run(turn, trend):
        monkeypatch.setattr(FT, "obv_state", lambda *a: {"turn": turn, "cs": turn or 1, "dark": bool(turn)})
        monkeypatch.setattr(FT, "stoch_signal", lambda c: {**sig, "side": turn,
                                                            "cross": "gold" if turn >= 0 else "dead"})
        monkeypatch.setattr(FT, "last_trend", lambda *a: trend)
        return M.evaluate_friend(rule, co, b30, ce)
    ev = run(1, _trend(1))
    assert ev["side"] == 1 and ev["rule"] == rule and ev["trend"] == 1 and ev["votes"]["chop"] == 1
    a = float(M.atr(b30.high, b30.low, b30.close, 14)[-1])
    assert ev["stop_dist"] == pytest.approx(3 * a) and ev["close"] == pytest.approx(b30.close.iloc[-1])
    ev = run(-1, _trend(-1))
    assert ev["side"] == -1
    ev = run(1, _trend(0, line=1, ema=1, chop=0, st=0))
    assert ev["side"] == 0 and ev["why"] == "친구 추세 진입 금지 (하늘·보라 선 상승 · EMA RSI 상승 · 찹존 횡보 · 슈퍼트렌드 횡보)"
    ev = run(1, _trend(-1, line=1))
    assert ev["side"] == 0 and ev["why"].startswith("친구 추세 하락 (하늘·보라 선 상승") and ev["why"].endswith("신호 롱와 반대")
    ev = run(0, _trend(1))
    assert ev["side"] == 0 and ev["why"] in ("OBV 연한색→진한색 없음", "스톡RSI 골든이 50선 위(K 31.2)")
    co.enabled = False
    assert run(1, _trend(1))["why"] == "이 코인 꺼짐"
    co.enabled = True
    far = _coin(sl=40.0)                                   # 40 x ATR: past 1/40 - 0.5 %
    monkeypatch.setattr(FT, "last_trend", lambda *a: _trend(1))
    ev = M.evaluate_friend(rule, far, b30, ce)
    assert ev["side"] == 0 and "청산가" in ev["why"]
    # bars: the closing one must be there, and 300 of them
    assert M.evaluate_friend(rule, co, b30, ce + M.MIN30)["why"] == "30분봉이 아직 없음"
    assert M.evaluate_friend(rule, co, b30.iloc[-200:].reset_index(drop=True), ce)["why"] == "지난 봉이 모자람"


def test_the_stoch_rule_needs_the_right_side_of_fifty():
    o, h, lo, c, v = walk(1500, seed=21)
    S = FT.stoch_pane(c)
    seen = set()
    for i in np.flatnonzero(S["gold"] | S["dead"])[-60:]:
        sg = FT.stoch_signal(c[:i + 1])
        k = S["k"][i]
        want = 1 if (S["gold"][i] and k < 50) else (-1 if (S["dead"][i] and k > 50) else 0)
        assert sg["side"] == want
        seen.add(want)
    assert seen == {1, -1, 0}


# ---------------------------------------------------------------- the configs
def test_the_deploy_configs():
    for path, mode in ((LIVE, "mainnet"), (PAPER, "paper")):
        cfg = M.load_config(str(path))
        assert cfg.mode == mode and cfg.exchange == "bybit" and cfg.name == "바이비트 봇"
        # owners 10-30: the OBV 50 line; 10-31 evening: the AC bar instead, no 50 line (tests/test_rules1031b.py);
        # 10-31 night: the trend bar's 종합 instead of the four votes, read on the 30m bar, the signal on 15m bars
        # (tests/test_rules1031c.py)
        assert cfg.rules == ("obvac",) and cfg.stop_atr == 3.0 and cfg.tf == "15m" and cfg.trend == "bar"
        assert cfg.trend_tf == "30m"
        # owners 10-31 evening: the friend bot's six coins (BTC, LTC out, XRP in; tests/test_rules1031b.py)
        assert cfg.symbols == ["SOLUSDT", "ETHUSDT", "XRPUSDT", "BCHUSDT", "ZECUSDT", "DOGEUSDT"]
        assert {c.symbol: c.leverage for c in cfg.coins} == {**{s: 40 for s in cfg.symbols}, "ZECUSDT": 20}
        assert all(c.sl_atr == 3.0 for c in cfg.coins)
        assert cfg.ladder == {"trigger": 10.0, "lock": 8.0, "step": 5.0} and cfg.ladder_every_s == 60
        assert cfg.margin_frac == 0.4 and cfg.taker_fee == 0.00044 and cfg.equity_floor_frac == 0
        assert cfg.no_weekend and cfg.us_open_pre_min == cfg.us_open_pause_min == cfg.macro_blackout_min == 30
    live, paper = M.load_config(str(LIVE)), M.load_config(str(PAPER))
    assert live.state != paper.state and live.own_stop_file != paper.own_stop_file and paper.start_equity == 100
    assert "/exec/" in live.state and not paper.telegram
    words = M.plan_words(live)
    assert "계단 순ROE +10%→+8%, +15%→+13%" in words and "매매법 OBV 진한색 + AC" in words and "손절 ATR 3배" in words
    # the friend bot's own config: WOO X Pro, the histogram's 0 cross on 15m bars (owners 10-31 night,
    # tests/test_rules1031c.py)
    old = M.load_config(str(ROOT / "deploy" / "mixchop.live.json"))
    assert old.exchange == "wooxpro" and old.name == "친구 15분 봇" and old.rules == ("h0x",) and old.tf == "15m"


def test_wrong_configs_are_refused(tmp_path):
    base = json.loads(LIVE.read_text(encoding="utf-8"))
    bad = {
        "exchange": ({"exchange": "binance"}, "exchange"),
        "no stop": ({"stop_atr": None}, "stop_atr"),
        "rule": ({"rules": ["obv", "macd"]}, "rules"),
        "name": ({"name": ""}, "name"),
        "lev": ({"coins": {"BTCUSDT": {"leverage": 75}}}, "범위 밖"),
    }
    for what, (over, words) in bad.items():
        p = tmp_path / f"{what}.json"
        p.write_text(json.dumps({**base, **over}), encoding="utf-8")
        with pytest.raises(M.MixError, match=words):
            M.load_config(str(p))


# ---------------------------------------------------------------- live on the fake Bybit exchange
class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def _cfg(tmp_path, **over):
    d = json.loads(LIVE.read_text(encoding="utf-8"))
    d.update(state=str(tmp_path / "state.json"), log=str(tmp_path / "log.jsonl"), kill_file=str(tmp_path / "STOP"),
             own_stop_file=str(tmp_path / "OWN.STOP"), coins={"BTCUSDT": {"leverage": 40}, "ETHUSDT": {"leverage": 40},
                                                             "SOLUSDT": {"leverage": 40}}, telegram=False,
             tf="30m", trend="four")              # (the 10-29 era of these tests; 10-31 night: tests/test_rules1031c.py)
    d.pop("trend_tf", None)
    d.update(over)
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    return M.load_config(str(p))


def _bybit(prices=None):
    fake = FakeBybit(prices=prices or {"BTCUSDT": 60000.0, "ETHUSDT": 2500.0, "SOLUSDT": 150.0}, wallet=100.0,
                     host="api.bybit.com")
    clock = Clock(T0)
    fake.clock = clock
    c = BY.BybitMainnetClient("k", "s", send=fake, clock_ms=clock, sleep=lambda s: None)
    return c, fake, clock


def test_a_live_cycle_on_bybit(tmp_path):
    cfg = _cfg(tmp_path)
    c, fake, clock = _bybit()
    broker = M.BybitBroker(c, cfg.coins)
    rows = {"1m": []}
    msgs = []
    bot = M.Bot(cfg, broker, lambda s, tf, n: rows.get(tf, []), clock, notify=lambda lv, t: msgs.append(t),
                sleep=lambda s: None)
    bot.start()
    assert fake.info["marginMode"] == "ISOLATED_MARGIN" and fake.lev["BTCUSDT"] == "40"
    assert all(co.enabled for co in cfg.coins) and msgs[0].startswith("[바이비트 봇] ▶️ 시작")
    px = 150.0
    ev = {"symbol": "SOLUSDT", "close_ms": T0, "side": 1, "why": "", "rule": "obv50", "close": px, "turn": 1, "trend": 1,
          "obv50": 41.0, "votes": {"line": 1, "ema": 1, "chop": 1, "st": 0}, "stop_dist": 1.5, "stop_pct": 1.0}
    bot.enter(bot.coins["SOLUSDT"], ev)
    p = bot.pos
    assert p is not None and p.leverage == 40 and p.side == 1
    assert p.qty == pytest.approx(100.0 * 0.4 * 40 / px, abs=0.1)          # margin 40 % of $100 at 40x, 0.1 steps
    (stop,) = fake.live_stops("SOLUSDT")
    assert float(stop["triggerPrice"]) == pytest.approx(p.entry - 1.5, abs=0.001)
    assert fake.covered("SOLUSDT")
    entry_msg = msgs[-1]
    assert "[바이비트 봇] 🟢 SOL 롱 진입" in entry_msg and "근거: OBV 연한 초록→진한 초록 · OBV 50선 아래(41.0)" in entry_msg
    assert "친구 추세 30분 상승 (하늘·보라 선 상승 · EMA RSI 상승 · 찹존 상승 · 슈퍼트렌드 횡보)" in entry_msg
    # the price runs past net ROE +10 % on the 1m bars: the stop goes to net ROE +8 % (new first, old cancelled)
    hi = p.entry * (1 + 0.10 / 40 + 2 * 0.00044) * 1.0005
    clock.t = T0 + 5 * M.MIN1
    fake.set_price("SOLUSDT", hi)
    rows["1m"] = [[T0 + k * M.MIN1, p.entry, hi if k == 3 else p.entry, p.entry, p.entry] for k in range(5)]
    bot.minute_update()
    lock = p.entry * (1 + 0.08 / 40 + 2 * 0.00044)
    (stop,) = fake.live_stops("SOLUSDT")
    assert bot.pos.step == 1 and float(stop["triggerPrice"]) == pytest.approx(lock, abs=0.002)
    assert any("🪜 SOL 계단 1단계" in m for m in msgs)
    # the price falls through it: Bybit fires the stop; the bot books the exit from the balance
    clock.t = T0 + 9 * M.MIN1
    fake.set_price("SOLUSDT", lock * 0.999)
    assert float(c.position("SOLUSDT")["positionAmt"]) == 0
    bot.poll()
    assert bot.pos is None and M.read_state(cfg.state)["position"] is None
    ex = [json.loads(x) for x in open(cfg.log, encoding="utf-8") if '"exit"' in x][-1]
    assert ex["why"] == "ladder" and ex["pnl"] > 0
    assert any("✅ SOL 롱 청산 · 계단 익절" in m for m in msgs)


def test_bybit_liquidation_room_from_its_risk_limits(tmp_path):
    cfg = _cfg(tmp_path)
    c, fake, _clock = _bybit()
    broker = M.BybitBroker(c, cfg.coins)
    tiers = c.risk_limits("BTCUSDT")
    room = broker.liq_room("BTCUSDT", 1000.0, 40)
    assert room == pytest.approx(1 / 40 - tiers[0]["mmr"] - M.LIQ_ROOM)
    assert broker.liq_room("BTCUSDT", 1e15, 40) == -1.0


def test_a_coin_bybit_cannot_set_is_not_traded(tmp_path):
    cfg = _cfg(tmp_path, coins={"BTCUSDT": {"leverage": 40}, "ZECUSDT": {"leverage": 20}})
    c, fake, clock = _bybit()
    msgs = []
    bot = M.Bot(cfg, M.BybitBroker(c, cfg.coins), lambda s, tf, n: [], clock, notify=lambda lv, t: msgs.append(t),
                sleep=lambda s: None)
    bot.start()
    assert bot.coins["BTCUSDT"].enabled and not bot.coins["ZECUSDT"].enabled
    assert "ZEC(꺼짐)" in msgs[0] and "⚠ ZECUSDT" in msgs[0]


# ---------------------------------------------------------------- one close (paper)
def test_one_close_rule_order_and_coin_order(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, mode="paper", start_equity=100, rules=["obv", "srsi"])        # (the 10-29 rules: two of them)
    rows30 = [[int(t), 1.0, 1.0, 1.0, 1.0, 1.0] for t in T0 - M.MIN30 * np.arange(400, -1, -1)]
    rows1h = [[int(t), 1.0, 1.0, 1.0, 1.0, 1.0] for t in T0 - M.H1 * np.arange(400, -1, -1)]
    calls = []

    def fake_eval(rule, co, b30, close_ms, *more):
        calls.append((rule, co.symbol))
        side = {("srsi", "ETHUSDT"): -1, ("obv", "SOLUSDT"): 1, ("srsi", "SOLUSDT"): 1}.get((rule, co.symbol), 0)
        return {"symbol": co.symbol, "close_ms": close_ms, "side": side, "why": "" if side else "없음", "rule": rule,
                "close": 10.0, "stop_dist": 0.1, "stop_pct": 1.0, "trend": side, "k": 30.0, "d": 25.0,
                "cross": "dead" if rule == "srsi" and side < 0 else "",
                "votes": {"line": side, "ema": side, "chop": side, "st": side}}
    monkeypatch.setattr(M, "evaluate_friend", fake_eval)
    msgs = []
    bot = M.Bot(cfg, M.PaperBroker(100.0, cfg.taker_fee), lambda s, tf, n: rows30 if tf == "30m" else rows1h,
                lambda: T0 + 5_000, notify=lambda lv, t: msgs.append(t), sleep=lambda s: None)
    bot.on_close(T0)
    assert calls == [(r, s) for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT") for r in ("obv", "srsi")]
    assert bot.pos is not None and bot.pos.symbol == "ETHUSDT" and bot.pos.side == -1      # ETH before SOL
    skips = [json.loads(x) for x in open(cfg.log, encoding="utf-8") if '"skip"' in x]
    assert skips[-1]["symbol"] == "SOLUSDT" and skips[-1]["why"] == "같은 봉에 ETH 먼저" and skips[-1]["rule"] == "obv"
    assert "근거(스톡RSI 50선): 스톡RSI 데드(K 30.0 / D 25.0, 50선 위)" in msgs[-1] and msgs[-1].startswith("[바이비트 봇 모의]")


def test_the_signals_listing(tmp_path):
    cfg = M.load_config(str(PAPER))
    b30 = frame(900, seed=4)
    for rule in ("obv", "srsi"):
        lines = M.friend_history(cfg.coins[0], b30, rule, 5)
        assert 1 <= len(lines) <= 5 and all("친구 추세" in x and "→" in x for x in lines)


def test_the_check_command_on_bybit(tmp_path, monkeypatch, capsys):
    """Reads only: Bybit's public contracts, the size now, a coin whose leverage Bybit does not allow, a stop too far."""
    import argparse
    b30 = frame(200, seed=8, vol=0.002)
    rows = [[int(t), o, h, lo, c, v] for t, o, h, lo, c, v in b30[["open_ms", "open", "high", "low", "close", "volume"]]
            .itertuples(index=False)]

    def spec(sym):
        return {"status": "Trading", "max_leverage": 12.5 if sym == "ZECUSDT" else 75.0, "min_qty": 0.001,
                "qty_step": 0.001, "min_notional": 5.0, "tick": 0.01}
    monkeypatch.setattr(M, "public_spec", lambda cfg: spec)
    monkeypatch.setattr(M, "binance_fetch", lambda base: lambda s, tf, n: rows[-n:])
    monkeypatch.setattr(M.time, "time", lambda: (T0 + 60_000) / 1000)
    assert M.cmd_check(argparse.Namespace(config=str(PAPER))) == 0
    out = capsys.readouterr().out.splitlines()
    assert "매매법·손절: OBV 진한색 + AC · 손절 ATR 3배(모든 코인) · 신호 15분봉 · 추세: 30분봉 추세 바 종합(6줄, 노랑이면 진입 안 함)" in out
    sol = next(x for x in out if x.startswith("✔ SOLUSDT"))
    assert "최대 75배" in sol and "(증거금 $40.00)" in sol               # 40 % of the paper's $100
    zec = next(x for x in out if "ZECUSDT" in x)
    assert zec.startswith("✘") and "설정 20배가 바이비트 최대보다 커서 이 코인은 꺼짐" in zec

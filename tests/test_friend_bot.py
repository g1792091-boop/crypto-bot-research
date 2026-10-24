"""'친구 매매법' paper bot (owners 2026-10-24, deploy/combo.friend.json, docs/friend-bot-ko.md): the config as the
brief says it and its problems, the member in the combined bot's runner (computed at its bar close, entered at the next
minute, one position, the same blocks, the gates' reasons recorded), the stop exactly at net ROE -75 % and never moved by
the liquidation buffer, the entry message's signal values, the loss review (its line and its row), and that the other
bots' configs load and say exactly what they said before (texts of commit eebb24a)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperbot import combo as C
from paperbot import friendsig as FS
from paperbot.events import Event
from paperbot.models import Bar, Position, Signal, TradeRecord

from test_combo import MIN, PX, SYMS, T0, World, cfg_of

ROOT = Path(__file__).resolve().parents[1]
M15 = 15 * MIN
FRIEND = [{"strategy": "FRIEND_ROC", "tf": "15m"}]
KW = dict(members=FRIEND, leverage={"BTCUSDT": 30, "default": 30}, margin=0.4, max_loss_frac=0.35,
          stop={"mode": "roe", "roe": 0.75, "net": True}, liq_buffer_atr=0.0,
          ladder={"first_lock": 0.20, "trigger_gap": 0.02, "step": 0.10}, rank=["order"], name="친구 매매법",
          no_weekend=True, macro_blackout_min=30, us_open_pause_min=30, us_open_pre_min=30, telegram=True)


def _deploy(name):
    return json.loads((ROOT / "deploy" / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- the config
def test_deploy_config_is_the_brief_and_valid():
    raw = _deploy("combo.friend.json")
    cfg = C.ComboConfig.from_dict(raw)
    assert cfg.problems() == []
    assert cfg.name == "친구 매매법" and cfg.members == FRIEND
    assert cfg.leverage == {"BTCUSDT": 30, "default": 30} and cfg.margin == 0.4 and cfg.initial_equity == 1000
    assert cfg.stop == {"mode": "roe", "roe": 0.75, "net": True} and cfg.stop_net
    assert cfg.ladder == {"first_lock": 0.20, "trigger_gap": 0.02, "step": 0.10} and cfg.rank == ("order",)
    assert cfg.no_weekend and cfg.macro_blackout_min == cfg.us_open_pause_min == cfg.us_open_pre_min == 30
    assert cfg.adx_gate == {"tf": "4h", "min": 20} and cfg.quiet_gate == {"bars": 20, "max_ratio": 0.64}
    assert cfg.max_hold_bars is None and cfg.telegram is True
    assert cfg.paper_db == _deploy("combo.vwap.json")["paper_db"] and cfg.db == "/var/lib/paperbot/combo/friend.db"
    # the choices that keep the paper equal to the research: one position, nothing else in the way
    assert cfg.vote_gate is None and cfg.vol_gate is None and cfg.early_exit is None and cfg.trend is None
    assert cfg.liq_buffer_atr == 0.0 and cfg.loss_cap == "shrink"
    assert 0.4 * 0.75 < cfg.max_loss_frac < 0.4               # a stop-out loses 30 % of the wallet: the cap never cuts it
    assert cfg.flip_twin is True                              # the coin-flip yardstick, its own account
    members = C.resolve_members(cfg.members, cfg.picks_file)
    assert [(m.kind, m.name, m.tf, m.label, m.custom) for m in members] == [("friend", "FRIEND_ROC", "15m",
                                                                            "FRIEND_ROC@15m", False)]
    assert C.friend_bot(cfg)
    text = C.start_text(cfg, members, 1000.0)
    assert text == ("[합친 봇 페이퍼 친구 매매법] 시작: 매매법 1개(친구 매매법(EMA·RSI·ROC) 15분), BTC 30배·나머지 30배, "
                    "증거금 잔고의 40%, 손절 순ROE -75%(수수료·슬리피지 포함: 30배 가격 2.36%), 계단 익절 순ROE 22%에서 "
                    "20% 잠금, 이후 10%씩, 빠른 청산 없음(고정 손절과 계단 익절만), 4시간 ADX(14)가 20 미만이면 진입 안 함"
                    "(추세 약함), 신호 봉 거래량이 앞 20봉 평균의 0.64배보다 크면 진입 안 함(조용한 봉만), 포지션 1개, "
                    "진입 쉼 주말·경제 발표 앞뒤 30분·나스닥 개장 앞 30분·뒤 30분, 지갑 $1,000.00")
    assert members[0].describe() == ("1. FRIEND_ROC 15분 - 친구 매매법(EMA·RSI·ROC): EMA21·EMA52·RSI26·ROC9, 상위 봉 "
                                     "1시간·4시간 중 하나라도 ROC9이 같은 쪽 (이 봇이 바이낸스 끝난 봉으로 계산)")
    assert members[0].higher == "roc_any"                     # the deploy file keeps today's rule (owners not picked)


def test_member_refusals_and_the_rule_bots_rows_never_read(tmp_path):
    for bad, text in [([{"strategy": "FRIEND_ROC", "tf": "15m", "numbers": {"x": 1}}], "숫자를 바꾸지"),
                      ([{"strategy": "FRIEND_ROC", "tf": "5m"}], "15m/30m/1h/4h"),
                      ([{"strategy": "FRIEND_ROC", "tf": "15m", "stop": ["pct", 1]}], "연구 설정")]:
        with pytest.raises(C.ComboError, match=text):
            C.resolve_members(bad, core=["V39_ALL"])
    ms = C.resolve_members([{"strategy": "FRIEND_ROC", "tf": tf} for tf in ("15m", "30m", "1h", "4h")], core=[])
    assert [m.kind for m in ms] == ["friend"] * 4
    w = World(tmp_path, members=FRIEND)
    w.signal("FRIEND_ROC", "BTCUSDT", 1, T0 + M15)          # a row with its name in the rule bot's log is not ours
    rows, _top = C.rule_rows(w.paper.conn, 0, w.members, set(SYMS))
    assert rows == []


def test_the_higher_bar_rule_is_a_member_option(tmp_path):
    """Owners 10-24 night: the friend's exact rule (RSI26 and ROC9 on both higher bars) as ``higher``: "rsi_roc_all";
    "roc_any" (either bar's ROC9) is the default and keeps the plain label."""
    assert C.FRIEND_HIGHER == FS.HIGHER_MODES
    a, b = C.resolve_members([{"strategy": "FRIEND_ROC", "tf": "15m"},
                              {"strategy": "FRIEND_ROC", "tf": "15m", "higher": "rsi_roc_all"}], core=[])
    assert (a.label, a.higher, b.label, b.higher) == ("FRIEND_ROC@15m", "roc_any", "FRIEND_ROC@15m~rsi_roc_all",
                                                      "rsi_roc_all")
    same = C.resolve_members([{"strategy": "FRIEND_ROC", "tf": "15m", "higher": "roc_any"}], core=[])[0]
    assert same.label == "FRIEND_ROC@15m"
    assert b.describe().endswith("상위 봉 1시간·4시간 둘 다 RSI26·ROC9이 같은 쪽 (이 봇이 바이낸스 끝난 봉으로 계산)")
    for bad, text in [([{"strategy": "FRIEND_ROC", "tf": "15m", "higher": "rsi_any"}], "roc_any, rsi_roc_all"),
                      ([{"strategy": "V39_ALL", "tf": "15m", "higher": "roc_any"}], "FRIEND_ROC에만"),
                      ([{"strategy": "FRIEND_ROC", "tf": "15m"},
                        {"strategy": "FRIEND_ROC", "tf": "15m", "higher": "roc_any"}], "두 번")]:
        with pytest.raises(C.ComboError, match=text):
            C.resolve_members(bad, core=["V39_ALL"])
    cfg = cfg_of(tmp_path, **{**KW, "members": [{"strategy": "FRIEND_ROC", "tf": "15m", "higher": "rsi_roc_all"}]})
    assert cfg.problems() == []
    assert "매매법 1개(친구 매매법(EMA·RSI·ROC) 15분 상위 봉 둘 다 RSI·ROC)" in C.start_text(
        cfg, C.resolve_members(cfg.members, core=[]), 1000.0)
    for name in ("combo.vwap.json", "combo.trend.json"):        # every other member: no such key
        c = C.ComboConfig.from_dict(_deploy(name))
        core = sorted({m["strategy"] for m in c.members})
        assert all(m.higher is None for m in C.resolve_members(c.members, c.picks_file, core=core))


def test_40x_with_a_net_minus_50_stop_is_valid_and_every_coin_enters():
    """The owners may pick 40x for every coin with a net ROE -50 % stop: valid, inside liquidation at the start size."""
    from paperbot.livereplay import file_brackets, file_specs
    raw = {**_deploy("combo.friend.json"), "telegram": False,
           "leverage": {"BTCUSDT": 40, "default": 40}, "stop": {"mode": "roe", "roe": 0.5, "net": True}}
    cfg = C.ComboConfig.from_dict(raw)
    assert cfg.problems() == [] and cfg.lev_of("DOGEUSDT") == 40
    assert C.stop_text(cfg) == "순ROE -50%(수수료·슬리피지 포함: 40배 가격 1.11%)"
    br, _ = file_brackets(list(SYMS))
    m = C.resolve_members(cfg.members, cfg.picks_file)[0]
    for sym in SYMS:
        for side in (1, -1):
            e = C.ComboEngine(C.settings_of(cfg), br, combo=cfg, symbol_specs=file_specs(list(SYMS)))
            px = PX[sym]
            e.submit(C.make_signal(cfg, m, T0, sym, side, px * 0.003, None, T0, 0, {}, "friend"))
            e.step({sym: Bar(sym, T0, T0 + MIN - 1, px, px, px, px)})
            p = e.position
            assert p is not None and p.leverage == 40, (sym, e.outcomes[-1])
            assert p.stop_price == pytest.approx(px * (1 - side * (0.5 / 40 - e.s.round_trip_cost)), rel=1e-12)
            assert (p.stop_price - p.liq_price) * side > 0.002 * p.entry_price      # inside liquidation, with room


def test_net_stop_minus_75_at_30x_is_valid_and_one_past_liquidation_is_not(tmp_path):
    assert cfg_of(tmp_path, **KW).problems() == []
    probs = cfg_of(tmp_path, **{**KW, "stop": {"mode": "roe", "roe": 0.95, "net": True}}).problems()
    assert any("강제청산 가격보다 멀어" in p for p in probs)
    for name in ("combo.trend.json", "combo.live15.json", "combo.live15-mexc.json", "combo.vwap.json"):
        assert C.ComboConfig.from_dict(_deploy(name)).problems() == []


def test_run_record_keeps_the_running_bots_keys_as_before():
    for name in ("combo.trend.json", "combo.vwap.json", "combo.live15.json"):
        cfg = C.ComboConfig.from_dict(_deploy(name))
        assert "adx_gate" not in C.run_config(cfg) and "quiet_gate" not in C.run_config(cfg)
    rc = C.run_config(C.ComboConfig.from_dict(_deploy("combo.friend.json")))
    assert rc["adx_gate"] == {"tf": "4h", "min": 20} and rc["quiet_gate"] == {"bars": 20, "max_ratio": 0.64}


# ---------------------------------------------------------------- the stop and the liquidation buffer
def _engine(equity):
    from paperbot.livereplay import file_brackets, file_specs
    cfg = C.ComboConfig.from_dict({**_deploy("combo.friend.json"), "paper_db": "-", "db": "-", "telegram": False,
                                   "initial_equity": equity})
    br, _ = file_brackets(list(SYMS))
    return cfg, C.ComboEngine(C.settings_of(cfg), br, combo=cfg, symbol_specs=file_specs(list(SYMS)))


@pytest.mark.parametrize("sym", SYMS)
@pytest.mark.parametrize("side", [1, -1])
def test_the_stop_is_net_minus_75_percent_and_every_coin_enters_at_the_start(sym, side):
    cfg, e = _engine(1000.0)
    m = C.resolve_members(cfg.members, cfg.picks_file)[0]
    px = PX[sym]
    sig = C.make_signal(cfg, m, T0, sym, side, px * 0.003, None, T0, 0, {}, "friend")
    e.submit(sig)
    e.step({sym: Bar(sym, T0, T0 + MIN - 1, px, px, px, px)})
    p = e.position
    assert p is not None, e.outcomes[-1]
    rt = e.s.round_trip_cost
    assert p.stop_price == pytest.approx(px * (1 - side * (0.75 / 30 - rt)), rel=1e-12)       # never moved
    assert p.leverage == 30 and p.margin == pytest.approx(400.0, rel=0.01)
    # a stop-out loses net ROE -75 %: 30 % of the wallet (fees and slippage of both sides inside)
    from paperbot.ladder import net_roe
    assert net_roe(side, p.entry_price, p.stop_price * (1 - side * e.s.slippage_frac), 30, 0.0) - 30 * 2 * e.s.taker_fee \
        == pytest.approx(-0.75, abs=0.002)


def test_a_stop_too_close_to_liquidation_is_refused_and_recorded_never_moved():
    """Binance's second LTC tier (maintenance 1 % above $50,000) puts the -75 % stop past the liquidation price of a
    large position: the entry is refused and said, as every combined bot's (the stop stays where the rule puts it)."""
    cfg, e = _engine(10_000.0)                       # $120,000 notional at 40 % x 30
    m = C.resolve_members(cfg.members, cfg.picks_file)[0]
    px = PX["LTCUSDT"]
    e.submit(C.make_signal(cfg, m, T0, "LTCUSDT", 1, px * 0.003, None, T0, 0, {}, "friend"))
    e.step({"LTCUSDT": Bar("LTCUSDT", T0, T0 + MIN - 1, px, px, px, px)})
    assert e.position is None
    out = e.outcomes[-1]
    assert out.status == "REJECTED" and out.reason == "sizing" and "too close to liq" in " ".join(out.detail["reasons"])


def test_the_runner_says_a_refusal_for_the_liquidation_price(tmp_path):
    from paperbot.livereplay import file_brackets
    B = T0 + M15
    w = _world(tmp_path, {B: [("LTCUSDT", 1)]}, initial_equity=10_000)
    for e in w.book.engines.values():
        e.brackets = file_brackets(list(SYMS))[0]                   # Binance's own brackets
    w.add_minutes(T0, 15)
    w.now = B + 5_000
    w.run.poll()
    w.add_minutes(B, 1)
    w.now = B + 65_000
    w.run.poll()
    assert w.engine().position is None
    msg = [t for _lv, t in w.note.messages if "진입 거절" in t]
    assert msg == ["[합친 봇 페이퍼 친구 매매법] 진입 거절(1번째): LTC - 손절 자리가 강제청산 가격에 너무 가까움(지금 크기의 "
                   "바이낸스 유지증거금 구간). 손절은 옮기지 않고 이 신호는 건너뜀"]


# ---------------------------------------------------------------- the member in the runner
VALS = {"bar_close": T0 + M15, "e21": 60010.5, "e52": 59980.25, "rsi": 55.31, "roc": 0.31, "roc_prev": -0.12,
        "higher": [{"close": T0, "roc": 0.84}, {"close": T0, "roc": -0.2}], "warm": True, "tf": "15m",
        "higher_tf": ["1h", "4h"], "vol_ratio": 0.41, "adx4h": 27.4, "close": 60000.0}


class StubFriend:
    """FriendSignals' face: ``plan`` {bar close: [(symbol, side)]}; ``unready`` {bar close: tries not readable yet}."""

    def __init__(self, member, plan, unready=None):
        self.m, self.plan, self.unready = member, plan, dict(unready or {})
        self.symbols = list(SYMS)
        self.errors: list = []
        self.bars = type("B", (), {"errors": []})()
        self.calls: list = []

    def due(self, b):
        return [self.m] if b % M15 == 0 else []

    def compute(self, b, want=None):
        self.calls.append(b)
        if self.unready.get(b, 0) > 0:
            self.unready[b] -= 1
            return [], set(want or ())
        got = [{"member": self.m, "symbol": s, "side": side, "atr": 100.0, "values": {**VALS, "bar_close": b},
                "ctx": {"close": PX[s]}} for s, side in self.plan.get(b, []) if want is None or (self.m.label, s) in want]
        return got, set()


class StubGates:
    def __init__(self, why=lambda s: ""):
        self.why, self.asked = why, []

    def check(self, symbol, tf, side, bar_close):
        self.asked.append((symbol, tf, side, bar_close))
        info = {"adx": {"tf": "4h", "adx": 27.4, "text": "4시간 ADX 27"},
                "quiet": {"tf": tf, "ratio": 0.41, "text": "거래량 0.41배(앞 20봉 평균 대비)"}}
        return self.why(symbol), info


def _world(tmp_path, plan, unready=None, gates=None, **kw):
    w = World(tmp_path, **{**KW, **kw})
    w.friend = StubFriend(w.members[0], plan, unready)
    w.run = C.ComboRunner(w.cfg, w.members, w.book, w.store, w.note, None, now_ms=lambda: w.now, prices=lambda: {},
                          gates=gates, friend=w.friend)
    w.now = T0 + 5_000
    w.run.poll()
    return w


def test_signal_at_the_bar_close_enters_at_the_next_minute_open(tmp_path):
    B = T0 + M15
    w = _world(tmp_path, {B: [("ETHUSDT", 1), ("BTCUSDT", 1)]}, gates=StubGates())
    w.add_minutes(T0, 15)
    w.now = B + 5_000
    w.run.poll()
    assert w.friend.calls == [B]                                   # read once, at the close
    rows = w.store.conn.execute("SELECT symbol, status, data FROM signal_log ORDER BY symbol").fetchall()
    assert [(r[0], r[1]) for r in rows] == [("BTCUSDT", "SUBMITTED"), ("ETHUSDT", "SUBMITTED")]
    assert json.loads(rows[0][2])["source"] == "friend"
    assert w.engine().position is None                             # the minute that opens at B is not there yet
    w.add_minutes(B, 1)
    w.now = B + 65_000
    w.run.poll()
    p = w.engine().position
    assert p.symbol == "BTCUSDT" and p.entry_time == B and p.leverage == 30          # ties: BTC before ETH
    assert p.entry_price == pytest.approx(PX["BTCUSDT"] * 1.0002)                   # the minute's open + slippage
    rt = w.engine().s.round_trip_cost
    assert p.stop_price == pytest.approx(PX["BTCUSDT"] * (1 - (0.75 / 30 - rt)))
    assert p.signal.meta["friend"]["adx4h"] == 27.4 and p.signal.meta["ctx"]["gates"]["adx"]["adx"] == 27.4
    outs = dict(w.store.conn.execute("SELECT status, reason FROM outcomes WHERE account_id = ?", (C.ACCOUNT,)).fetchall())
    assert outs == {"ENTERED": "ok", "SKIPPED": "lower score than entered signal"}
    text = C.entry_text(w.cfg, p)
    assert text.startswith("[합친 봇 페이퍼 친구 매매법] 진입 BTC 롱 · 친구 매매법(EMA·RSI·ROC) 15분 · 30배, 증거금 $")
    assert text.split("\n")[1] == ("신호 봉: 15분봉 10/05 09:00~09:15 KST · EMA21 60010.5 > EMA52 59980.2 · RSI26 55.3 · "
                                   "ROC9 -0.12 → +0.31 · 1시간 ROC9 +0.84 · 4시간 ROC9 -0.20 · 4시간 ADX 27 · 거래량 0.41배")
    assert text in [t for _lv, t in w.note.messages]


def test_a_close_waits_for_binance_to_settle_its_bar(tmp_path):
    B = T0 + M15
    w = _world(tmp_path, {B: [("SOLUSDT", -1)]}, unready={B: 1})
    w.add_minutes(T0, 15)
    w.now = B + 1_000                                              # before SETTLE_MS: not asked at all
    w.run.poll()
    assert w.friend.calls == [] and w.run.friend_wait
    w.now = B + 4_000                                              # asked: Binance does not have it yet
    w.run.poll()
    assert w.friend.calls == [B] and w.run.friend_wait
    w.now = B + 6_000                                              # asked again at the next poll (no new minute)
    w.run.poll()
    assert w.friend.calls == [B, B] and not w.run.friend_wait
    queue = w.store.get_state(C.STATE_KEY)[1]["queue"]              # saved with the state (a restart keeps it)
    assert [q["signal"]["meta"]["member"] for q in queue] == ["FRIEND_ROC@15m"]
    w.add_minutes(B, 1)
    w.now = B + 65_000
    w.run.poll()
    assert w.engine().position.symbol == "SOLUSDT" and w.engine().position.side == -1


def test_a_bar_never_readable_is_given_up_at_its_entry_minute_and_said(tmp_path):
    B = T0 + M15
    w = _world(tmp_path, {B: [("BTCUSDT", 1)]}, unready={B: 99})
    w.add_minutes(T0, 15)
    w.now = B + 5_000
    w.run.poll()
    w.add_minutes(B, 1)
    w.now = B + 65_000
    w.run.poll()
    assert w.engine().position is None and not w.run.friend_wait
    msg = [t for _lv, t in w.note.messages if "신호 봉을 못 읽어" in t]
    assert msg == ["[합친 봇 페이퍼 친구 매매법] 친구 매매법 신호 봉을 못 읽어 건너뜀(1번째): 10-05 09:15 KST BTC, ETH, SOL, "
                   "DOGE, LTC, BCH · 끝난 봉을 아직 못 받음"]


def test_catch_up_closes_are_not_read(tmp_path):
    B = T0 + M15
    w = _world(tmp_path, {B: [("BTCUSDT", 1)]})
    w.add_minutes(T0, 20)
    w.now = B + 200_000                                            # a restart's catch-up: the signal would be late
    w.run.poll()
    assert w.friend.calls == [] and w.engine().position is None


def test_blocks_and_gates_are_recorded_with_their_reason(tmp_path):
    sat = T0 + 5 * 86_400_000 - 9 * 3_600_000 + M15                  # Saturday 00:15 KST: the weekend block first
    w = _world(tmp_path, {}, gates=StubGates(lambda s: "4시간 ADX 약함: 17.3 (20 미만)" if s == "BTCUSDT" else
                                             ("거래량 많음: 신호 봉 0.81배 (앞 20봉 평균의 0.64배 넘음)" if s == "ETHUSDT" else "")))
    sig = C.make_signal(w.cfg, w.members[0], sat, "BTCUSDT", 1, 100.0, None, sat, 0, None, "friend")
    assert w.run._entry_block(sig, sat, sat, {}).startswith("주말") and w.run.gates.asked == []
    B = T0 + M15
    w.friend.plan = {B: [("BTCUSDT", 1), ("ETHUSDT", -1), ("SOLUSDT", 1)]}
    w.add_minutes(T0, 15)
    w.now = B + 5_000
    w.run.poll()
    w.add_minutes(B, 1)
    w.now = B + 65_000
    w.run.poll()
    assert w.engine().position.symbol == "SOLUSDT"
    rows = {r[0]: (r[1], json.loads(r[2])) for r in w.store.conn.execute("SELECT symbol, status, data FROM signal_log")}
    assert rows["BTCUSDT"][0] == rows["ETHUSDT"][0] == "FILTERED"
    assert rows["BTCUSDT"][1]["why"] == "4시간 ADX 약함: 17.3 (20 미만)" and rows["BTCUSDT"][1]["gates"]["adx"]["adx"] == 27.4
    assert C.gate_group(rows["BTCUSDT"][1]["why"]) == "ADX 약함" and C.gate_group(rows["ETHUSDT"][1]["why"]) == "거래량 많음"
    assert w.run.counts["FRIEND_ROC@15m"] == {"submitted": 1, "filtered": 2}


# ---------------------------------------------------------------- the loss review
def _trade(**kw):
    d = dict(strategy_id="FRIEND_ROC", symbol="ETHUSDT", timeframe="15m", side=1, signal_ts=1, entry_time=T0,
             entry_price=2500.0, exit_time=T0 + 312 * MIN, exit_price=2440.0, exit_reason="SL", qty=4.8, leverage=30,
             tier="combo", margin=400.0, stop_price=2440.6, tp_price=float("nan"), liq_price=2430.0, fees=6.0,
             funding=0.0, pnl=-300.0, roe=-0.75, price_move=-0.024, mae_price=2440.0, mfe_price=2527.5,
             equity_after=700.0, score=3.0,
             context={"friend": {"adx4h": 27.4, "vol_ratio": 0.41},
                      "entry": {"btc_open": 60000.0, "p24_side": 0.93, "macro_min": 190.0, "macro_kind": "CPI"}})
    d.update(kw)
    return TradeRecord(**d)


def test_loss_facts_and_line():
    f = FS.loss_facts(_trade(), 59280.0, 0.0014)
    assert f["btc_with_pct"] == pytest.approx(-1.2) and f["hours"] == pytest.approx(5.2)
    assert f["best_roe"] == pytest.approx(30 * (2527.5 / 2500 - 1 - 0.0014))
    assert FS.loss_line(f) == ("손실 이유 후보: BTC가 거래 동안 반대로 -1.2% · 손절 전 최고 +29% · 5.2시간 보유 · "
                               "4시간 ADX 27 · 거래량 0.41배 · 24시간 범위 끝에서 진입(0.93) · 소비자물가(CPI) 발표 "
                               "3.2시간 뒤 진입")
    f = FS.loss_facts(_trade(side=-1, context={}), 59280.0, 0.0014)     # values not known are left out
    assert FS.loss_line(f) == "손실 이유 후보: 손절 전 최고 -37% · 5.2시간 보유"
    f2 = FS.loss_facts(_trade(context={"entry": {"btc_open": 60000.0, "p24_side": 0.5, "macro_min": -45.0,
                                                 "macro_kind": "FOMC"}}, exit_reason="LIQ"), 60600.0, 0.0014)
    assert FS.loss_line(f2) == ("손실 이유 후보: BTC는 거래 방향으로 +1.0% · 청산 전 최고 +29% · 5.2시간 보유 · 24시간 범위 "
                                "0.50 위치에서 진입 · FOMC 금리 결정 발표 45분 전 진입")


def test_entry_facts_range_position_and_nearest_release():
    bc = T0 + 3 * 3_600_000                                          # the 24 hours before this hour
    hours = {bc // 3_600_000 - k: (110.0, 100.0) for k in range(1, 25)}
    ev = [Event(T0 - 600 * MIN, "CPI", ""), Event(T0 + 2 * 1440 * MIN, "NFP", "")]
    f = FS.entry_facts(hours, bc, 1, 109.0, 60000.0, bc, ev)
    assert f["p24"] == pytest.approx(0.9) and f["p24_side"] == pytest.approx(0.9)
    assert f["macro_kind"] == "CPI" and f["macro_min"] == pytest.approx(780.0)
    assert FS.entry_facts(hours, bc, -1, 109.0, None, bc, ev)["p24_side"] == pytest.approx(0.1)   # 1 = the chase end
    few = {k: v for k, v in list(hours.items())[:19]}                # fewer than 20 of the 24 hours: unknown
    assert FS.entry_facts(few, bc, 1, 109.0, None, bc, [])["p24_side"] is None


def test_a_losing_exit_gets_its_line_and_row_a_winning_one_neither(tmp_path):
    B = T0 + M15
    w = _world(tmp_path, {B: [("BTCUSDT", 1)]}, gates=StubGates())
    w.add_minutes(T0, 15)
    w.now = B + 5_000
    w.run.poll()
    w.add_minutes(B, 1)
    w.now = B + 65_000
    w.run.poll()
    assert w.engine().position is not None
    w.add_minutes(B + MIN, 3, move={"BTCUSDT": -0.01, "ETHUSDT": 0.002})   # BTC down 1 % a minute: the -75 % stop
    w.now = B + 4 * MIN + 5_000
    w.run.poll()
    t = w.engine().trades[-1]
    assert t.exit_reason == "SL" and t.roe < 0
    row = w.store.conn.execute("SELECT symbol, side, exit_reason, roe, btc_with_pct, best_roe, hours, adx4h, vol_ratio, "
                               "line FROM loss_review").fetchall()
    assert len(row) == 1 and row[0][:3] == ("BTCUSDT", 1, "SL") and row[0][4] < -2 and row[0][7] == 27.4
    assert row[0][8] == 0.41 and row[0][6] == pytest.approx((t.exit_time - t.entry_time) / 3_600_000)
    exits = [x for _lv, x in w.note.messages if " 청산 " in x]
    assert exits[-1].split("\n")[0].startswith("[합친 봇 페이퍼 친구 매매법] 청산 BTC 롱 · 친구 매매법(EMA·RSI·ROC) 15분 · 손절 · "
                                               "순ROE -7")
    assert exits[-1].split("\n")[1] == row[0][9] and row[0][9].startswith("손실 이유 후보: BTC가 거래 동안 반대로 -")
    status = FS.loss_status(w.store.conn, B + DAY_MS)
    assert status[0].startswith("손실 리뷰(지난 7일): 손실 1번 (시작부터 1번) · BTC가 반대로 감 1 ·")


DAY_MS = 86_400_000


def test_with_the_watchers_messages_only_the_loss_line_still_goes(tmp_path, monkeypatch):
    """PAPERBOT_COMBO_TRADE_MSGS=0 (live-telegram.env: the live watcher tells the trades): no raw entry / exit line from
    the paper bot, but a losing exit's loss review line still goes, on its own."""
    monkeypatch.setenv("PAPERBOT_COMBO_TRADE_MSGS", "0")
    B = T0 + M15
    w = _world(tmp_path, {B: [("BTCUSDT", 1)]}, gates=StubGates())
    w.add_minutes(T0, 15)
    w.now = B + 5_000
    w.run.poll()
    w.add_minutes(B, 1)
    w.now = B + 65_000
    w.run.poll()
    w.add_minutes(B + MIN, 3, move={"BTCUSDT": -0.01})
    w.now = B + 4 * MIN + 5_000
    w.run.poll()
    t = w.engine().trades[-1]
    sent = [x for _lv, x in w.note.messages if "진입" in x or "청산" in x or "손실 이유" in x]
    line = w.store.conn.execute("SELECT line FROM loss_review").fetchone()[0]
    assert sent == [f"[합친 봇 페이퍼 친구 매매법] BTC 롱 순ROE {t.roe:+.1%} · {line}"]


def test_a_winning_exit_has_no_loss_line(tmp_path):
    w = _world(tmp_path, {T0 + M15: [("ETHUSDT", 1)]})
    B = T0 + M15
    w.add_minutes(T0, 15)
    w.now = B + 5_000
    w.run.poll()
    w.add_minutes(B, 1)
    w.now = B + 65_000
    w.run.poll()
    w.add_minutes(B + MIN, 2, move={"ETHUSDT": 0.006})               # +1.2 %: best net ROE above 22 % -> lock 20 %
    w.add_minutes(B + 3 * MIN, 1, move={"ETHUSDT": -0.02})           # back down through the lock
    w.now = B + 4 * MIN + 5_000
    w.run.poll()
    t = w.engine().trades[-1]
    assert t.exit_reason == "LOCK" and t.roe > 0
    assert not w.store.conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'loss_review'").fetchone()
    assert not any("손실 이유 후보" in x for _lv, x in w.note.messages)


# ---------------------------------------------------------------- the other bots: as before
OLD = {   # the texts of commit eebb24a (before the friend bot), for the same trade and position
    "combo.vwap.json": {
        "exit_win": "[합친 봇 페이퍼 VWAP 개선판] 청산 ETH 롱 · VWAP 복귀 실패 30분 · 계단 익절 · 순ROE +20.6%, +$82.30, 지갑 $1,082.33",
        "exit_loss": "[합친 봇 페이퍼 VWAP 개선판] 청산 ETH 롱 · VWAP 복귀 실패 30분 · 손절 · 순ROE -74.9%, -$324.40, 지갑 $1,082.33",
        "entry_gates": "[합친 봇 페이퍼 VWAP 개선판] 진입 ETH 숏 · VWAP 복귀 실패 30분 · 30배, 증거금 $399.95, 손절 2600 (2 ATR) · "
                       "4시간 상승(상승 3·하락 0·중립 1) · 변동성 30분 ATR 0.45% (30일 80% 위치 0.62%)",
        "start": "[합친 봇 페이퍼 VWAP 개선판] 시작: 매매법 2개(VWAP 복귀 실패 30분 · CMO·샌드위치 캔들 1시간), BTC 30배·나머지 30배, "
                 "증거금 잔고의 40%, 손절 2 ATR, 계단 익절 순ROE 12%에서 10% 잠금, 이후 5%씩, 빠른 청산 없음(고정 손절과 계단 익절만), "
                 "4시간 추세 판단이 반대면 진입 안 함(4개 중 3개 반대; 보류는 진입), 변동성(ATR14%)이 지난 30일의 80% 위치보다 크면 "
                 "진입 안 함(상위 20% 금지), 보유 한도 96봉(30분 48시간 · 1시간 96시간), 넘으면 시장가 청산, 포지션 1개, 진입 쉼 "
                 "주말·경제 발표 앞뒤 30분·나스닥 개장 앞 30분·뒤 30분, 지갑 $1,234.50"},
    "combo.trend.json": {
        "exit_win": "[합친 봇 페이퍼 추세판단 봇] 청산 ETHUSDT 롱 N06_MACD_ORB 30분: 계단 익절, 순ROE +20.6%, +$82.30, 지갑 $1,082.33",
        "exit_loss": "[합친 봇 페이퍼 추세판단 봇] 청산 ETHUSDT 롱 N06_MACD_ORB 30분: 손절, 순ROE -74.9%, -$324.40, 지갑 $1,082.33",
        "entry_plain": "[합친 봇 페이퍼 추세판단 봇] 진입 ETHUSDT 숏 N06_MACD_ORB 30분 (N06_MACD_ORB@30m), 30배, 증거금 $399.95, "
                       "손절 2600 (순ROE -50%(수수료·슬리피지 포함), 30배), 점수 3.00",
        "stop": "순ROE -50%(수수료·슬리피지 포함: 40배 가격 1.11%, 30배 가격 1.53%)"},
    "combo.live-ac.json": {
        "exit_loss": "[합친 봇 페이퍼 A+C 합본] 청산 ETHUSDT 롱 F12_MSS_DISP 1시간: 손절, 순ROE -74.9%, -$324.40, 지갑 $1,082.33",
        "stop": "3 ATR(안 맞으면 강제청산 안쪽으로 당김)"},
}


def _old_trade(strat, tf, reason, roe, pnl):
    return TradeRecord(strategy_id=strat, symbol="ETHUSDT", timeframe=tf, side=1, signal_ts=1, entry_time=1791801900000,
                       entry_price=2544.23, exit_time=1791805500000, exit_price=2500.0, exit_reason=reason, qty=4.7,
                       leverage=30, tier="combo", margin=399.95, stop_price=2483.28, tp_price=float("nan"),
                       liq_price=2469.3, fees=5.0, funding=0.0, pnl=pnl, roe=roe, price_move=0.0, mae_price=2483.0,
                       mfe_price=2600.0, equity_after=1082.33, score=3.0, context={})


@pytest.mark.parametrize("name", sorted(OLD))
def test_the_other_bots_load_and_say_what_they_said(name):
    cfg = C.ComboConfig.from_dict(_deploy(name))
    assert cfg.problems() == [] and cfg.adx_gate is None and cfg.quiet_gate is None and not C.friend_bot(cfg)
    m0 = cfg.members[0]
    want = OLD[name]
    if "exit_win" in want:
        assert C.exit_text(cfg, _old_trade(m0["strategy"], m0["tf"], "LOCK", 0.2058, 82.3)) == want["exit_win"]
    assert C.exit_text(cfg, _old_trade(m0["strategy"], m0["tf"], "SL", -0.7494, -324.4)) == want["exit_loss"]
    if "stop" in want:
        assert C.stop_text(cfg) == want["stop"]
    gates = {"vote": {"text": "4시간 상승(상승 3·하락 0·중립 1)"}, "vol": {"text": "변동성 30분 ATR 0.45% (30일 80% 위치 0.62%)"}}
    for key, meta in (("entry_plain", {"stop_rule": "ROE -50% net at 30x"}), ("entry_gates", {"stop_rule": "2 x ATR", "gates": gates})):
        if key not in want:
            continue
        sig = Signal(ts=1, symbol="ETHUSDT", timeframe=m0["tf"], strategy_id=m0["strategy"], side=-1, stop_price=0.0,
                     tier="best", score=3.0, atr=1.0, meta={"member": f"{m0['strategy']}@{m0['tf']}", **meta})
        p = Position(signal=sig, symbol="ETHUSDT", side=-1, qty=4.7, entry_price=2544.23, entry_time=1791801900000,
                     leverage=30, tier="combo", margin=399.95, margin_initial=399.95, stop_price=2600.0,
                     tp_price=float("nan"), liq_price=2620.0, entry_fee=1.0)
        assert C.entry_text(cfg, p) == want[key]
    if "start" in want:
        members = C.resolve_members(cfg.members, cfg.picks_file)
        assert C.start_text(cfg, members, 1234.5) == want["start"]


def test_unit_and_install_never_start_it():
    unit = (ROOT / "deploy" / "paperbot-combo-friend.service").read_text(encoding="utf-8")
    vwap = (ROOT / "deploy" / "paperbot-combo-vwap.service").read_text(encoding="utf-8")
    assert "ExecStart=/opt/paperbot/venv/bin/python -m paperbot.combo run --config /etc/paperbot/combo-friend.json" in unit
    assert "ReadWritePaths=/var/lib/paperbot/combo\n" in unit and "OOMScoreAdjust=-500" in unit
    hidden = next(x for x in unit.splitlines() if x.startswith("InaccessiblePaths=")).split("=", 1)[1].split()
    assert "-/etc/paperbot/executor.env" in hidden and "-/etc/paperbot/executor-wooxpro2.env" in hidden
    assert set(next(x for x in vwap.splitlines() if x.startswith("InaccessiblePaths=")).split("=", 1)[1].split()) < set(hidden)
    for key in ("User=", "Group=", "EnvironmentFile=", "Type=", "WatchdogSec=", "MemoryMax=", "ProtectSystem="):
        assert [x for x in unit.splitlines() if x.startswith(key)] == [x for x in vwap.splitlines() if x.startswith(key)]
    inst = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    assert ('install -m 644 "$APP/deploy/paperbot-combo-friend.service" /etc/systemd/system/paperbot-combo-friend.service'
            in inst)
    assert "enable --now paperbot-combo-friend" not in inst and "start paperbot-combo-friend" not in inst
    lines = inst.splitlines()
    i = next(k for k, x in enumerate(lines) if x.startswith("UNITS="))
    assert lines[i + 2] == 'UNITS="$UNITS paperbot-combo-friend"'          # stopped for the code swap, started again
    import subprocess
    assert subprocess.run(["bash", "-n", str(ROOT / "deploy" / "install.sh")]).returncode == 0
    assert "combo/friend" in (ROOT / "deploy" / "paperbot-backup.sh").read_text(encoding="utf-8")

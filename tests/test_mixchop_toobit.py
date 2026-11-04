"""Owners 2026-11-03 ("Woo x pro2 거래소 아이디를 실수로 탈퇴해서 woo x pro2 친구봇 거래소를 투빗으로 해줘"): the 친구 15분 봇
(paperbot/mixchop.py, deploy/mixchop.*.json) trades Toobit: ``"exchange": "toobit"``, its broker ToobitBroker on the
Toobit client of paperbot/toobit.py (the executor's, against tests/faketoobit.py here: no network), the keys of the old
Toobit executor's file (/etc/paperbot/executor-toobit.env), its gates (mainnet only, the switch, the owners' statement).

- the deploy configs: Toobit, its taker fee, the friend bot's rule, coins, ladder;
- the broker: the start (one side per coin, isolated at each coin's leverage), an entry, the resting stop, a move, a
  close, the equity, the positions of the account;
- the bot on it: a 15m close -> a market order on the fake + a resting stop; the ladder on 1m bars moves that stop on
  the fake; the stop firing -> the bot sees the account flat and says the exit;
- the gates: no switch / no key / no statement -> refused before any request; the public specs; the unit's key file;
- the site's and the checks' words: 투비트."""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from faketoobit import FakeToobit  # noqa: E402
from paperbot import mixchop as M  # noqa: E402
from paperbot import toobit as TB  # noqa: E402
from paperbot.mainnet import FLAG, FLAG_VALUE  # noqa: E402
from tests.test_toobit import Clock, ticking  # noqa: E402

DEPLOY = ROOT / "deploy"
T0 = 1_800_000_000_000 - 1_800_000_000_000 % M.MIN30
BTC, BCH, DOGE = "BTCUSDT", "BCHUSDT", "DOGEUSDT"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    import socket

    def refuse(*a, **k):
        raise AssertionError("no network in tests")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def _client(fake, clock):
    fake.clock = clock
    return TB.ToobitClient("tk", "ts", send=fake, clock_ms=clock, sleep=ticking(clock))


def _cfg(tmp_path, **over) -> M.Config:
    d = json.loads((DEPLOY / "mixchop.live.json").read_text(encoding="utf-8"))
    d.update(state=str(tmp_path / "state.json"), log=str(tmp_path / "log.jsonl"), kill_file=str(tmp_path / "STOP"),
             own_stop_file=str(tmp_path / "OWN.STOP"), telegram=False, no_weekend=False, us_open_pre_min=0,
             us_open_pause_min=0, macro_blackout_min=0,
             coins={BTC: {"leverage": 40}, BCH: {"leverage": 40}, DOGE: {"leverage": 40}}, **over)
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    return M.load_config(str(p))


def test_the_deploy_configs_trade_toobit():
    for name, mode in (("mixchop.live.json", "mainnet"), ("mixchop.paper.json", "paper")):
        cfg = M.load_config(str(DEPLOY / name))
        assert (cfg.exchange, cfg.mode, cfg.name, M.EXCHANGES[cfg.exchange]) == ("toobit", mode, "친구 15분 봇", "투비트"), name
        # (owners 11-03 evening "친구봇도 obv로 하고 여기에는 종목을 비트 솔라나 zec만": the 레인지 봇's rule and coins)
        assert cfg.taker_fee == 0.0006 and cfg.rules == ("o4h",) and cfg.trend == "macd" and cfg.tf == "15m", name
        assert cfg.symbols == ["BTCUSDT", "SOLUSDT", "ZECUSDT"], name
        assert cfg.ladder == {"trigger": 10.0, "lock": 8.0, "step": 2.0} and cfg.ladder_basis == "gross", name
    unit = (DEPLOY / "paperbot-mixchop.service").read_text(encoding="utf-8")
    assert "EnvironmentFile=/etc/paperbot/executor-toobit.env\n" in unit and "executor-wooxpro2.env\n" not in unit
    assert "Conflicts=paperbot-executor-wooxpro2.service paperbot-executor-toobit.service\n" in unit
    from paperbot import livecheck as LC
    assert LC.REPLACED_BY["toobit"] == ("/etc/paperbot/mixchop.json", "paperbot-mixchop", "친구 15분 봇")
    # a wrong exchange is refused, the new one named
    with pytest.raises(M.MixError, match="toobit"):
        M.load_config(str(_write(DEPLOY / "mixchop.live.json", exchange="okx")))


def _write(src: Path, **over) -> Path:
    p = Path(os.environ.get("TMPDIR", "/tmp")) / f"mixtoobit-{os.getpid()}.json"
    p.write_text(json.dumps({**json.loads(src.read_text(encoding="utf-8")), **over}), encoding="utf-8")
    return p


def test_the_broker_on_the_fake():
    clock = Clock(T0)
    fake = FakeToobit(prices={BTC: 100.0, BCH: 300.0})
    c = _client(fake, clock)
    c.sync_time()
    coins = [M.Coin(BTC, 0.0, 3.0, 100.0, 40), M.Coin(BCH, 0.0, 3.0, 100.0, 40)]
    b = M.ToobitBroker(c, coins)
    lines = b.setup(coins)
    assert lines[0] == (True, "포지션: 한 코인 한쪽만 (주문마다 롱·숏 쪽을 붙여 보냄)")
    assert lines[1:] == [(True, "BTCUSDT: 격리 40배"), (True, "BCHUSDT: 격리 40배")]
    assert fake.levs[BTC] == {"leverage": 40, "marginType": "ISOLATED"}
    eq0 = b.equity()
    assert eq0 == pytest.approx(10_000.0) and b.liq_room(BTC, 1000.0, 40) is None
    # a long of 16 BTC at 100, its stop at 99 resting on the exchange
    fill, filled = b.open(BTC, 1, 16.0, 100.0, 40)
    assert (fill, filled) == (pytest.approx(100.0), pytest.approx(16.0)) and float(fake.amt(BTC)) == pytest.approx(16.0)
    sid = b.place_stop(BTC, 1, 99.0, 16.0)
    assert sid and b.stop_ok(BTC, 16.0) and b.is_open(BTC) is True and b.amount(BTC) == pytest.approx(16.0)
    assert [float(o["stopPrice"]) for o in fake.live_stops(BTC)] == [99.0]
    assert b.foreign_positions(None) == [(BTC, pytest.approx(16.0))] and b.foreign_positions(BTC) == []
    # a stop above the price is refused as already past (the protocol's "closed"; the bot closes then)
    assert b.move_stop(BTC, 1, 100.2, 16.0, sid)[0] == "closed" and [float(o["stopPrice"]) for o in fake.live_stops(BTC)] == [99.0]
    # the ladder moves it once the price is past: the new one rests, the old one is gone
    fake.set_price(BTC, 100.3)
    res, new = b.move_stop(BTC, 1, 100.2, 16.0, sid)
    assert res == "moved" and new and new != sid
    assert [float(o["stopPrice"]) for o in fake.live_stops(BTC)] == [100.2]
    # the stop fires: flat, nothing left resting once the bot cancels
    fake.set_price(BTC, 100.1)
    assert b.is_open(BTC) is False
    b.cancel_stops(BTC)
    assert fake.live_stops(BTC) == []
    # a short closed at market by the bot
    b.open(BCH, -1, 1.0, 300.0, 40)
    assert float(fake.amt(BCH)) == pytest.approx(-1.0)
    b.close_market(BCH, -1, 1.0)
    assert float(fake.amt(BCH)) == 0 and b.is_open(BCH) is False


def test_the_bot_enters_moves_and_exits_on_toobit(tmp_path, monkeypatch):
    clock = Clock(T0 + M.MIN15 + 5_000)
    fake = FakeToobit(prices={BTC: 100.0})
    c = _client(fake, clock)
    c.sync_time()
    cfg = _cfg(tmp_path)
    b = M.ToobitBroker(c, cfg.coins)
    ce = T0 + M.MIN15
    minute = []

    def fetch(sym, tf, n):
        if tf == "1m":
            return [r for r in minute if r[0] + M.MIN1 <= clock.t][-n:]
        step, last = (M.MIN15, ce) if tf == "15m" else (M.MIN30, T0)
        return [[int(t), 100.0, 100.0, 100.0, 100.0, 1.0] for t in last - step * np.arange(400, -1, -1)]

    def fake_eval(r, co, bars, close_ms, tf_ms=M.MIN30, trend="four", tb=None, trend_tf_ms=None, trend_both=False):
        assert trend_both is True                    # (the live config: the 15m 추세 MACD too, owners 11-04)
        side = 1 if co.symbol == BTC else 0
        return {"symbol": co.symbol, "close_ms": close_ms, "side": side, "rule": r, "close": 100.0, "stop_dist": 1.0,
                "stop_pct": 1.0, "trend": 1, "trend_mode": "macd", "tf": "15분", "trend_tf": "30분", "tmacd": 3.21,
                "tmacd_line": 5.0, "tyellow": False, "o4": -2.0, "o4_turn": side, "o4_col": 1 if side else 0,
                "why": "" if side else "OBV 히스토그램 전환 없음", "liq_ok": True}
    monkeypatch.setattr(M, "evaluate_friend", fake_eval)
    msgs = []
    bot = M.Bot(cfg, b, fetch, lambda: clock.t, notify=lambda lv, t: msgs.append(t), sleep=ticking(clock))
    bot.start()
    assert msgs[0].startswith("[친구 15분 봇] ▶️ 시작") and "코인 BTC · BCH · DOGE" in msgs[0]
    bot.on_close(ce)
    p = bot.pos
    assert p is not None and (p.symbol, p.side, p.leverage) == (BTC, 1, 40) and float(fake.amt(BTC)) == pytest.approx(p.qty)
    assert [float(o["stopPrice"]) for o in fake.live_stops(BTC)] == [pytest.approx(p.stop)]
    entry = next(m for m in msgs if "롱 진입" in m)
    assert "근거: OBV 히스토그램 0선 아래 양봉 전환(-2.00)" in entry and "거래소 ROE +10%" in entry      # (rule o4h since 11-03 evening)
    # the price climbs on 1m bars to exchange ROE +10.4 % (40x): the stop goes to +8 % on the exchange
    e = p.entry
    t = ce + M.MIN1
    for px in (e * 1.001, e * 1.0026):
        minute.append([t, px, px, px, px, 1.0])
        fake.set_price(BTC, px)
        t += M.MIN1
        clock.t = t + 2_000
        bot._last_minute_ms = 0
        bot.minute_update()
    assert bot.pos.step == 1 and bot.pos.stop == pytest.approx(e * (1 + 0.08 / 40), rel=1e-4)
    assert [float(o["stopPrice"]) for o in fake.live_stops(BTC)] == [pytest.approx(bot.pos.stop, rel=1e-4)]
    assert any("🪜 BTC 계단 1단계" in m and "거래소 ROE +8.0%" in m for m in msgs)
    # it falls through the stop: the exchange closes it, the bot sees flat and says the ladder exit
    fake.set_price(BTC, e * 1.0015)
    clock.t += 30_000
    bot.manage(T0 + M.MIN30)
    assert bot.pos is None and float(fake.amt(BTC)) == 0
    assert any("✅ BTC 롱 청산 · 계단 익절" in m for m in msgs)


def test_the_gates_refuse_before_any_request(monkeypatch, tmp_path):
    cfg = _cfg(tmp_path)
    for env, words in (({}, "실거래 스위치가 꺼져"),
                       ({FLAG: FLAG_VALUE}, "TOOBIT_LIVE_KEY / TOOBIT_LIVE_SECRET 가 비어"),
                       ({FLAG: FLAG_VALUE, "TOOBIT_LIVE_KEY": "k", "TOOBIT_LIVE_SECRET": "k"}, "같습니다")):
        monkeypatch.setattr(os, "environ", dict(env))
        with pytest.raises(TB.Refused, match=words):
            M.live_broker(cfg)
    # no owners' statement: refused before a request is sent (the key check reads, the client never orders)
    sent = []
    monkeypatch.setattr(os, "environ", {FLAG: FLAG_VALUE, "TOOBIT_LIVE_KEY": "k1", "TOOBIT_LIVE_SECRET": "s1"})
    monkeypatch.setattr(TB.ToobitClient, "req", lambda self, *a, **k: sent.append(a) or {})
    with pytest.raises(TB.Refused, match="TOOBIT_LIVE_KEY_CHECKED"):
        M.live_broker(cfg)
    assert sent == []


def test_the_public_specs(monkeypatch, tmp_path):
    """Paper sizes as live would: Toobit's public contract rows (no key, no private call)."""
    cfg = _cfg(tmp_path)
    fake = FakeToobit()
    fake.clock = Clock(T0)
    pub = TB.ToobitClient("", "", public_only=True, send=fake, clock_ms=fake.clock, sleep=lambda s: None)
    monkeypatch.setattr(TB, "public_client", lambda: pub)
    sp = M.public_spec(cfg)(BTC)
    assert sp["qty_step"] == pytest.approx(0.001) and sp["status"] == "Trading" and sp["max_leverage"] == 125


def test_the_words_say_toobit():
    from paperbot.dash.more import livemix as X
    from paperbot.dash.more import livepos as LP
    from paperbot import mixcheck as MC
    assert (X.MIX.exchange_ko, X.MIX.account_ko) == ("투비트", "투비트")
    assert LP.MIX_CARD["mix"]["name_ko"] == "투비트 · 친구봇" and LP.MIX_CARD["mix"]["app_ko"] == "투비트"
    w = MC.words_of({"bot": "mix", "live": {"conf": {"cfg": M.load_config(str(DEPLOY / "mixchop.live.json"))}}})
    assert w["ex"] == "투비트" and w["fee"] == 0.0006 and w["name"] == "친구 15분 봇"
    js = (ROOT / "paperbot" / "dash" / "static" / "v4" / "screens" / "livebots-mix.js").read_text(encoding="utf-8")
    assert 'account: "투비트", exchange: "투비트", key: "",\n  kick: "진짜 돈 · 투비트 계정"' in js
    routes = (ROOT / "paperbot" / "dash" / "static" / "v4" / "core" / "routes.js").read_text(encoding="utf-8")
    assert "OBV 히스토그램 전환 · 투비트 실거래와 모의" in routes and "WOO X Pro 2 실거래" not in routes

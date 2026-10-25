"""The executor's opt-in options of 10-25 night for the Toobit executor (owners: "증거금 40% BTC 40배 나머지 30배", then
"손절 2.5 ATR로 가고 15%되면 13%에 익절 20%되면 17%익절 25%되면 22%", "경제발표 30분전이랑 30분후는 그래도 위험하니까
진입금지"), on the fake Toobit (tests/faketoobit.py) with the real executor, as tests/test_toobit.py's World runs it:

- ``leverage_by_symbol``: each new entry at the config's leverage (BTC 40x, the others 30x) instead of the paper's, set on
  the exchange before the entry; with ``size_from: "equity"`` qty = equity x margin_frac x that leverage / price;
- ``take_profit_roe``: the whole position closed at market once the net ROE at the last price reaches it (implemented,
  not in the template), with or without a ladder; the paper's price exits leave it open, the others close it; a restart
  keeps the trade's own take-profit and finishes a close it had decided;
- ``stop_scale``: the first stop at the paper's distance x the scale from the live fill (long and short);
- ``liq_guard``: no entry whose stop sits at or beyond the estimated liquidation (a quiet missed signal);
- ``macro_block_min``: no new entry within ± that many minutes of a US release (data/macro_events.csv);
- every option absent: the executor as before; the config refusals; the words of check-config and preflight.
No network."""

from __future__ import annotations

import dataclasses
import json
import socket
from datetime import datetime, timezone

import pytest

from faketoobit import FakeToobit
from paperbot import events as EV
from paperbot import livecheck as LC
from paperbot import risk as R
from paperbot import toobit as TB
from paperbot.dash.more import livebots as L
from paperbot.executor import ExecConfig, ExecStore, Executor, main, preflight
from paperbot.ladder import roe_price
from paperbot.testnet import TestnetError, round_stop
from test_toobit import BTC, ETH, LIVE_ENV, ORDER, ROOT, World, calls

FIXED = {"BTCUSDT": 40, "*": 30}
RT = 2 * (0.0006 + 0.0002)                     # Toobit's own round trip (net_costs): 0.16 %
LADDER = {"first_lock": 0.13, "trigger_gap": 0.02, "step": 0.05, "next_trigger": 0.20, "next_gap": 0.03}
TEMPLATE = ROOT / "deploy" / "executor.live-toobit.json"
MIN = 60_000


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("a test tried to open a network connection")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def events(w, kind):
    return [(lv, text, json.loads(d)) for lv, text, d in w.store.conn.execute(
        "SELECT level, text, data FROM events WHERE kind = ? ORDER BY id", (kind,))]


def closed(w):
    reason, data = w.store.conn.execute("SELECT exit_reason, data FROM trades WHERE exit_ts IS NOT NULL").fetchone()
    return reason, json.loads(data)


def restart(w, **change):
    """The executor stopped and started again on the same database (the fake exchange keeps its state)."""
    w.store.close()
    if change:
        w.cfg = dataclasses.replace(w.cfg, **change)
    w.store = ExecStore(w.cfg.db)
    kw = dict(send=w.fake, clock_ms=w.clock, sleep=lambda s: None)
    w.client = TB.ToobitClient("tk", "ts", **kw)
    w.keycheck = TB.ToobitKeyCheckClient("tk", "ts", attested=True, **kw)
    w.ex = Executor(w.cfg, w.client, w.src, w.store, w.note, now_ms=w.clock, sleep=lambda s: None,
                    keycheck=w.keycheck, env=dict(LIVE_ENV))
    w.ex.start()
    return w.ex


def cfg_of(tmp_path, **kw):
    risk = R.RiskConfig(max_leverage=40, max_notional_usd=1_000.0, allowed_symbols=(BTC, ETH),
                        kill_file=str(tmp_path / "STOP"))
    return ExecConfig(account="V39_ALL@1h", paper_db="p", db=str(tmp_path / "e.db"), qty_scale=1.0, risk=risk,
                      exchange="toobit", mode="mainnet", budget_usd=50.0, **kw)


# ====================================================================== fixed leverage
@pytest.mark.parametrize("symbol,paper_lev,lev,qty", [(BTC, 20, 40, 8.0), (ETH, 20, 30, 6.0), (ETH, 50, 30, 6.0)])
def test_fixed_leverage_sizes_each_coin_from_the_balance_at_its_own_leverage(tmp_path, symbol, paper_lev, lev, qty):
    """$50 x 40 % = $20 margin: BTC at 40x and $100 -> 8 BTC, ETH at 30x -> 6 ETH, whatever the paper's leverage."""
    w = World(tmp_path, fake=FakeToobit(wallet=50.0), size_from="equity", margin_frac=0.4, leverage_by_symbol=FIXED)
    w.fake.levs[symbol]["leverage"] = 10                          # set again by the entry itself, before the order
    w.paper(stop=99.0, qty=5.0, lev=paper_lev, symbol=symbol)     # the paper's quantity and leverage are not used
    w.loop()
    t = w.ex.trade
    assert w.fake.amt(symbol) == pytest.approx(qty) and w.fake.levs[symbol]["leverage"] == lev
    assert (t["leverage"], t["paper_leverage"], t["leverage_from"]) == (lev, paper_lev, "config")
    assert w.stops(symbol) == [(99.0, qty)]                     # stop_from "ratio": the paper's 1 % from its own fill
    (_lv, text, _d), = events(w, "entry")
    assert f"{lev}배(설정의 고정 배수, 페이퍼 {paper_lev}배)" in text
    (_lv, _t, d), = events(w, "entry_check")
    assert (d["leverage"], d["paper_leverage"], d["leverage_from"]) == (lev, paper_lev, "config")


def test_fixed_leverage_with_the_papers_size_keeps_the_papers_quantity(tmp_path):
    w = World(tmp_path, leverage_by_symbol=FIXED)
    w.paper(stop=99.0, qty=5.0, lev=20)
    w.loop()
    assert w.fake.amt(BTC) == 5 and w.fake.levs[BTC]["leverage"] == 40 and w.ex.trade["leverage"] == 40


def test_without_the_options_the_entry_is_as_before(tmp_path):
    """No leverage_by_symbol, no stop_scale, no liq_guard, no macro_block_min: the paper's leverage, the paper's distance,
    the records without any new field (the other executors run this way)."""
    w = World(tmp_path, fake=FakeToobit(wallet=50.0), size_from="equity", margin_frac=0.4)
    w.paper(stop=98.7654, qty=5.0, lev=20)
    w.loop()
    t = w.ex.trade
    assert w.fake.amt(BTC) == pytest.approx(4.0) and w.fake.levs[BTC]["leverage"] == 20 and t["leverage"] == 20
    assert t["stop"] == round_stop(100.0 * 98.7654 / 100.0, 0.1, 1)
    for k in ("leverage_from", "own", "tp_hit", "exit_code"):
        assert k not in t
    (_lv, _t, d), = events(w, "entry_check")
    assert "paper_leverage" not in d and "leverage_from" not in d
    (_lv, text, d), = events(w, "start")
    for k in ("leverage_by_symbol", "take_profit_roe", "stop_scale", "liq_guard", "macro_block_min"):
        assert k not in d
    assert "배수:" not in text and "손절:" not in text and "경제 발표" not in text and "청산가 확인" not in text
    assert not events(w, "liq_skip") and not events(w, "macro_skip")


# ====================================================================== the config
@pytest.mark.parametrize("extra,word", [
    ({"leverage_by_symbol": {"BTCUSDT": 50, "*": 30}}, "50배가 최대 레버리지(risk.max_leverage) 40배보다 큽니다"),
    ({"leverage_by_symbol": {"BTCUSDT": 0, "*": 30}}, "BTCUSDT: 배수는 1 이상의 정수"),
    ({"leverage_by_symbol": {"BTCUSDT": 30.5, "*": 30}}, "BTCUSDT: 배수는 1 이상의 정수"),
    ({"leverage_by_symbol": {"BTCUSDT": True, "*": 30}}, "BTCUSDT: 배수는 1 이상의 정수"),
    ({"leverage_by_symbol": {"BTCUSDT": "40", "*": 30}}, "BTCUSDT: 배수는 1 이상의 정수"),
    ({"leverage_by_symbol": {"BTCUSDT": 40, "*": -1}}, "*: 배수는 1 이상의 정수"),
    ({"leverage_by_symbol": {"XRPUSDT": 30, "*": 30}}, "XRPUSDT: 거래 허용 코인(risk.allowed_symbols)이 아닙니다"),
    ({"leverage_by_symbol": {"btcusdt": 40, "*": 30}}, "btcusdt: 거래 허용 코인"),
    ({"leverage_by_symbol": {"BTCUSDT": 40}}, "ETHUSDT의 배수가 없습니다"),
    ({"leverage_by_symbol": {}}, "leverage_by_symbol은 {코인: 배수} 묶음"),
    ({"leverage_by_symbol": [40, 30]}, "leverage_by_symbol은 {코인: 배수} 묶음"),
    ({"take_profit_roe": 0.15}, "take_profit_roe(고정 익절)는 ladder_from \"own\""),
    ({"ladder_from": "own", "take_profit_roe": 0}, "take_profit_roe(고정 익절)는 0~1 사이"),
    ({"ladder_from": "own", "take_profit_roe": 1.5}, "take_profit_roe(고정 익절)는 0~1 사이"),
    ({"ladder_from": "own", "take_profit_roe": "0.15"}, "take_profit_roe(고정 익절)는 0~1 사이"),
    ({"ladder_from": "own", "take_profit_roe": True}, "take_profit_roe(고정 익절)는 0~1 사이"),
    ({"ladder_from": "own"}, "ladder_from \"own\"(거래소 기준 익절)은 ladder"),
    ({"ladder_from": "own", "ladder": LADDER, "stop_scale": 0.5}, "stop_scale은 페이퍼 손절 거리에 곱하는 배율로 0.5보다 크고"),
    ({"ladder_from": "own", "ladder": LADDER, "stop_scale": 3.5}, "stop_scale은 페이퍼 손절 거리에 곱하는 배율로 0.5보다 크고"),
    ({"ladder_from": "own", "ladder": LADDER, "stop_scale": True}, "stop_scale은 페이퍼 손절 거리에 곱하는 배율"),
    ({"ladder_from": "own", "ladder": LADDER, "stop_scale": "1.25"}, "stop_scale은 페이퍼 손절 거리에 곱하는 배율"),
    ({"ladder_from": "own", "ladder": LADDER, "stop_scale": 1.25, "stop_from": "price"}, "stop_scale은 stop_from \"ratio\""),
    ({"stop_scale": 1.25}, "stop_scale은 ladder_from \"own\""),
    ({"liq_guard": "yes"}, "liq_guard는 true"),
    ({"liq_guard": True, "liq_guard_mmr": 0.06}, "liq_guard_mmr은 유지증거금률로 0~0.05 사이"),
    ({"liq_guard": True, "liq_guard_mmr": True}, "liq_guard_mmr은 유지증거금률로 0~0.05 사이"),
    ({"liq_guard_mmr": 0.005}, "liq_guard_mmr은 liq_guard true일 때만"),
    ({"macro_block_min": 0}, "macro_block_min은 1~240분(정수)"),
    ({"macro_block_min": 241}, "macro_block_min은 1~240분(정수)"),
    ({"macro_block_min": 30.0}, "macro_block_min은 1~240분(정수)"),
    ({"macro_block_min": True}, "macro_block_min은 1~240분(정수)"),
])
def test_config_refusals(tmp_path, extra, word):
    probs = cfg_of(tmp_path, **extra).problems()
    assert any(word in p for p in probs), probs


@pytest.mark.parametrize("extra", [
    {"leverage_by_symbol": {"BTCUSDT": 40, "ETHUSDT": 30}},
    {"leverage_by_symbol": {"*": 25}},
    {"leverage_by_symbol": FIXED, "ladder_from": "own", "ladder": None, "take_profit_roe": 0.15},
    {"ladder_from": "own", "ladder": LADDER, "take_profit_roe": 0.25, "ladder_basis": "gross"},
    {"ladder_from": "own", "ladder": LADDER, "stop_scale": 3},
    {"ladder_from": "own", "ladder": LADDER, "stop_scale": 0.51},
    {"liq_guard": True},
    {"liq_guard": True, "liq_guard_mmr": 0},
    {"macro_block_min": 30},
    {"macro_block_min": 240},
])
def test_configs_accepted(tmp_path, extra):
    assert cfg_of(tmp_path, **extra).problems() == []


def test_the_template_is_accepted_and_said_in_words(tmp_path, capsys):
    raw = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    assert ExecConfig.from_dict(raw).problems() == []
    assert main(["check-config", "--config", str(TEMPLATE)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[-1] == "준비됨"
    for want in ("계단: 순ROE 15%에서 13% 잠금, 20%에서 17%, 25%에서 22%, 그 뒤 5%마다 (닿은 순ROE - 3%)",
                 "배수: BTC 40배, 나머지 30배 (페이퍼 배수 대신) - 진입 전에 거래소 배수를 이 값으로 맞춤",
                 "손절: 페이퍼 손절 거리(2 ATR) × 1.25 = 2.5 ATR, 자기 체결가 기준"):
        assert want in lines, lines
    assert any(ln.startswith("크기: 진입할 때마다 실거래 잔고의 40%를 증거금으로, 위 배수 줄의 배수") for ln in lines)
    assert any(ln.startswith("청산가 확인: 켜짐") and "(40배 약 2.00%, 30배 약 2.83%)" in ln for ln in lines)
    assert any(ln.startswith("경제 발표: 미국 CPI·FOMC·고용(NFP)·PCE 발표 앞뒤 30분에는 새 진입 안 함") for ln in lines)
    assert not any("고정 익절" in ln for ln in lines)                    # no fixed take-profit in the plan
    # the site's settings read the same file: the four rules as the owners say them
    c = L.read_config(str(TEMPLATE))
    ko = {x["key"]: x["ko"] for x in c["limits"]}
    assert ko["leverage_by_symbol"] == "배수 고정: BTC 40배 · 나머지 30배 (페이퍼 배수 대신)"
    assert ko["stop_scale"] == "손절: 페이퍼 손절 거리 × 1.25 (2 ATR → 2.5 ATR), 자기 체결가 기준"
    assert ko["macro_block_min"] == "미국 경제 발표(CPI·FOMC·NFP·PCE) 앞뒤 30분 새 진입 안 함"
    assert "liq_guard" in ko and "take_profit_roe" not in ko
    assert c["ladder_from"] == "own" and c["size_from"] == "equity"


def test_check_config_says_the_take_profit_alone(tmp_path, capsys):
    raw = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    raw.update(ladder=None, take_profit_roe=0.15)
    p = tmp_path / "c.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    assert main(["check-config", "--config", str(p)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("익절(고정 익절): 거래소 기준 - 이 실행기의 체결가, 이 거래소의 지금 가격")
    assert lines[1] == "익절: 순ROE +15%에서 시장가로 전부 닫음 (계단 없음)"
    assert any("자기 손절·고정 익절로 계속" in ln and "계단이 없어 자기 잠금이 생기지 않음" in ln for ln in lines)
    assert {x["key"]: x["ko"] for x in L.read_config(str(p))["limits"]}["take_profit_roe"] == \
        "익절: 순ROE +15%에서 시장가로 전부 닫음 (계단 없음)"


def test_preflight_and_the_start_record_say_the_options(tmp_path, monkeypatch):
    path = tmp_path / "macro_events.csv"
    path.write_text("ts_utc,kind,source_url\n", encoding="utf-8")           # no release ahead: a warning, not a failure
    monkeypatch.setattr(EV, "PATH", path)
    EV.reset()
    try:
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        plain = World(tmp_path / "a")
        base = []
        ok0 = preflight(plain.cfg, plain.client, plain.keycheck, out=base.append, env=dict(LIVE_ENV))
        w = World(tmp_path / "b", leverage_by_symbol=FIXED, ladder_from="own", ladder=LADDER, stop_scale=1.25,
                  liq_guard=True, macro_block_min=30)
        out = []
        ok = preflight(w.cfg, w.client, w.keycheck, out=out.append, env=dict(LIVE_ENV))
    finally:
        EV.reset()
    assert ok == ok0
    text = "\n".join(out)
    assert "[OK]   배수: BTC 40배, 나머지 30배 (페이퍼 배수 대신)" in text
    assert "[OK]   손절: 페이퍼 손절 거리(2 ATR) × 1.25 = 2.5 ATR, 자기 체결가 기준" in text
    assert "[OK]   청산가 확인: 켜짐" in text and "이 거래소 연결은 유지증거금률을 주지 않아 0.5%로 계산" in text
    assert "[OK]   경제 발표: 미국 CPI·FOMC·고용(NFP)·PCE 발표 앞뒤 30분에는 새 진입 안 함" in text
    assert "[주의] 일정 없음: 앞으로 30일 안에 경제 발표가 없습니다. data/macro_events.csv를 채우세요" in text
    assert len([ln for ln in out if ln.startswith("[FAIL]")]) == len([ln for ln in base if ln.startswith("[FAIL]")])
    (_lv, start, d), = events(w, "start")
    assert "배수: BTC 40배, 나머지 30배 (페이퍼 배수 대신)" in start and "손절: 페이퍼 손절 거리(2 ATR) × 1.25 = 2.5 ATR" in start
    assert "청산가 확인 켜짐" in start and "미국 경제 발표 앞뒤 30분 새 진입 안 함" in start
    assert (d["leverage_by_symbol"], d["stop_scale"], d["liq_guard"], d["liq_guard_mmr"], d["macro_block_min"]) == (
        FIXED, 1.25, True, 0.005, 30)


# ====================================================================== the fixed take-profit
def tp_world(tmp_path, **kw):
    return World(tmp_path, ladder_from="own", take_profit_roe=0.15, leverage_by_symbol=FIXED, **kw)


@pytest.mark.parametrize("side", [1, -1])
def test_the_take_profit_closes_it_all_at_15_net_never_at_14_9(tmp_path, side):
    w = tp_world(tmp_path)
    w.paper(stop=100.0 - side * 1.0, side=side)
    w.loop()
    t = w.ex.trade
    assert t["leverage"] == 40 and t["own"]["tp"] == 0.15 and w.fake.amt(BTC) == side * 5
    first = w.stops()
    for roe in (0.10, 0.149):
        w.fake.set_price(BTC, roe_price(side, 100.0, 40, roe, RT))
        w.loop()
        assert w.ex.trade is not None and w.fake.amt(BTC) == side * 5, roe
        assert w.stops() == first                                    # no ladder: the stop stays where it was
    px = roe_price(side, 100.0, 40, 0.15, RT)                        # 100.535 long, 99.465 short
    w.fake.set_price(BTC, px)
    w.loop()
    assert w.ex.trade is None and w.fake.amt(BTC) == 0 and not w.fake.live_stops(BTC)
    reason, d = closed(w)
    assert reason == "고정 익절 +15% 도달 → 시장가로 닫음"
    assert d["exit_code"] == "TP" and d["tp_hit"]["price"] == pytest.approx(px) and d["exit_ref"] == pytest.approx(px)
    assert d["tp_hit"]["roe"] == pytest.approx(0.15)
    (_lv, text, _d), = events(w, "own_tp")
    assert text.startswith("BTCUSDT 고정 익절 +15% 도달 (자기 체결가 기준): 체결 100") and "→ 시장가로 전부 닫습니다" in text
    # one stop (the entry's), no exchange trigger order for the take-profit, market orders only (no resting limit)
    assert len(w.fake.stop_bodies) == 1
    assert [b["side"] for b in w.fake.order_bodies] == (["BUY_OPEN", "SELL_CLOSE"] if side > 0 else
                                                         ["SELL_OPEN", "BUY_CLOSE"])
    assert all(b["priceType"] == "MARKET" for b in w.fake.order_bodies)
    assert not calls(w.fake, "GET", "/quote/v1/klines")                # no ladder: no candles read
    # the site reads it as 익절, the checks as its own exit (never compared with the paper's exit as slippage)
    assert L.live_exit(reason, d, side, 100.0) == "TP" and L.EXIT_KO["TP"] == "익절"
    ex = LC.ExecInfo(name="toobit", config="", unit="", db="", light_n=0, light_min=0.85, exchange="toobit",
                     ladder_from="own")
    et = {"exit_ts": 1, "exit_reason": reason, "data": json.dumps(d), "symbol": BTC, "side": side, "qty": 5,
          "entry_price": 100.0, "leverage": 40, "pnl": 0.75}
    assert LC.own_exit(ex, et)
    assert "고정 익절 +15% 도달 → 시장가로 닫음" in LC.own_exit_text(ex, et, None)


def test_the_take_profit_on_the_screen_roe_basis(tmp_path):
    w = tp_world(tmp_path, ladder_basis="gross")
    w.paper(stop=99.0)
    w.loop()
    w.fake.set_price(BTC, roe_price(1, 100.0, 40, 0.149, 0.0))
    w.loop()
    assert w.ex.trade is not None
    w.fake.set_price(BTC, roe_price(1, 100.0, 40, 0.15, 0.0))       # 100.375: +15 % on the screen, before fees
    w.loop()
    assert w.ex.trade is None and closed(w)[0] == "고정 익절 화면 +15% 도달 → 시장가로 닫음"


def test_the_take_profit_with_a_ladder_both_work(tmp_path):
    w = World(tmp_path, ladder_from="own", ladder=LADDER, take_profit_roe=0.18, leverage_by_symbol=FIXED)
    w.paper(stop=99.0)
    w.loop()
    w.fake.set_price(BTC, roe_price(1, 100.0, 40, 0.155, RT))      # the ladder's first lock: +13 %
    w.loop()
    lock = round_stop(roe_price(1, 100.0, 40, 0.13, RT), 0.1, 1)
    assert w.ex.trade["own"]["lock"] == pytest.approx(0.13) and w.stops() == [(lock, 5.0)]
    w.fake.set_price(BTC, roe_price(1, 100.0, 40, 0.18, RT))       # the take-profit: closed at market
    w.loop()
    assert w.ex.trade is None and closed(w)[0] == "고정 익절 +18% 도달 → 시장가로 닫음"


@pytest.mark.parametrize("reason,stays", [("SL", True), ("LOCK", True), ("TP", True), ("LIQ", True),
                                          ("REV", False), ("HALT", False), ("MANUAL", False)])
def test_paper_exits_with_the_take_profit_and_no_ladder(tmp_path, reason, stays):
    """The paper's price exits leave the live position on its own stop and take-profit; the others close it (REV too:
    without a ladder it never has a lock of its own)."""
    w = tp_world(tmp_path)
    w.paper(stop=99.0)
    w.loop()
    key = w.ex.trade["key"]
    w.src.exit_of = lambda k: ({"reason": reason, "exit_time": w.clock.t - 1_000, "exit_price": 99.0, "lock_roe": None}
                               if k == key else None)
    w.src.intent = None
    w.loop()
    if stays:
        assert w.ex.trade is not None and w.fake.amt(BTC) == 5 and w.ex.trade["paper_exit"]["action"] == "stay"
        assert w.stops() == [(99.0, 5.0)]
        w.fake.set_price(BTC, roe_price(1, 100.0, 40, 0.15, RT))
        w.loop()
        assert w.ex.trade is None and closed(w)[0] == "고정 익절 +15% 도달 → 시장가로 닫음"
    else:
        assert w.ex.trade is None and w.fake.amt(BTC) == 0
        assert closed(w)[0].startswith("paper 청산 → 거래소 포지션 닫기 (paper ")


def test_a_restart_while_open_keeps_the_trades_own_take_profit(tmp_path):
    w = tp_world(tmp_path)
    w.paper(stop=99.0)
    w.loop()
    restart(w, take_profit_roe=0.30)                       # the trade keeps the +15 % it started with
    assert w.ex.trade["own"]["tp"] == 0.15 and w.ex.trade["status"] == "open"
    w.fake.set_price(BTC, roe_price(1, 100.0, 40, 0.149, RT))
    w.loop()
    assert w.ex.trade is not None
    w.fake.set_price(BTC, roe_price(1, 100.0, 40, 0.15, RT))
    w.loop()
    assert w.ex.trade is None and closed(w)[0] == "고정 익절 +15% 도달 → 시장가로 닫음"


def test_a_take_profit_close_that_failed_is_finished_after_a_restart_whatever_the_price(tmp_path):
    w = tp_world(tmp_path)
    w.paper(stop=99.0)
    w.loop()
    w.fake.set_price(BTC, roe_price(1, 100.0, 40, 0.15, RT))
    w.fake.fail("POST", ORDER, ("err", 400, -3130, "order margin insufficient"))     # the close is refused once
    with pytest.raises(TestnetError):
        w.loop()
    t = w.ex.trade
    assert t["tp_hit"]["tp"] == 0.15 and w.fake.amt(BTC) == 5 and w.stops() == [(99.0, 5.0)]     # still protected
    restart(w)
    w.fake.set_price(BTC, 100.2)                            # back under the take-profit: the decision stands
    w.loop()
    assert w.ex.trade is None and w.fake.amt(BTC) == 0 and closed(w)[0] == "고정 익절 +15% 도달 → 시장가로 닫음"


# ====================================================================== the stop scale
@pytest.mark.parametrize("side", [1, -1])
def test_the_stop_scale_puts_the_first_stop_at_the_papers_distance_times_the_scale(tmp_path, side):
    """The paper's 2 % (2 ATR) x 1.25 = 2.5 % from the live fill 101: 98.475 long (rounded up to 98.5), 103.525 short
    (rounded down to 103.5); it stays there (the own ladder never pulls it back to the paper's distance)."""
    w = World(tmp_path, ladder_from="own", ladder=LADDER, stop_scale=1.25)
    w.fake.set_price(BTC, 101.0)
    w.paper(stop=100.0 - side * 2.0, side=side)
    w.loop()
    want = round_stop(101.0 * (1 - side * 0.025), 0.1, side)
    assert want == (98.5 if side > 0 else 103.5)
    assert w.ex.trade["stop"] == w.ex.trade["stop_initial"] == want and w.stops() == [(want, 5.0)]
    w.loop(3)
    assert w.stops() == [(want, 5.0)] and len(w.fake.stop_bodies) == 1


def test_without_the_stop_scale_the_stop_is_the_papers_distance(tmp_path):
    w = World(tmp_path, ladder_from="own", ladder=LADDER)
    w.fake.set_price(BTC, 101.0)
    w.paper(stop=98.0)
    w.loop()
    assert w.stops() == [(round_stop(101.0 * 98.0 / 100.0, 0.1, 1), 5.0)]


# ====================================================================== the liquidation guard
@pytest.mark.parametrize("symbol,dist,enters", [(BTC, 0.019, True), (BTC, 0.020, False), (BTC, 0.025, False),
                                                (ETH, 0.025, True), (ETH, 0.0285, False)])
def test_the_liq_guard_skips_an_entry_whose_stop_sits_beyond_the_liquidation(tmp_path, symbol, dist, enters):
    """1 / leverage - 0.5 %: BTC at 40x 2.00 %, ETH at 30x 2.83 %; a stop at or beyond it: no entry, no order, a quiet
    missed signal."""
    w = World(tmp_path, leverage_by_symbol=FIXED, liq_guard=True)
    w.paper(stop=100.0 * (1 - dist), symbol=symbol)
    w.loop(2)
    if enters:
        assert w.ex.trade is not None and w.fake.amt(symbol) != 0 and not events(w, "liq_skip")
        return
    assert w.ex.trade is None and w.fake.amt(symbol) == 0 and not w.fake.order_bodies and not w.fake.stop_bodies
    (lv, text, d), = events(w, "liq_skip")                          # recorded once (marked done)
    lev = 40 if symbol == BTC else 30
    assert lv == "INFO" and d["key"] == w.src.intent.key and d["mmr_from"] == "config" and d["mmr"] == 0.005
    assert text == (f"{symbol} 손절(2 ATR)이 강제청산 가격보다 멀어 이번 진입은 하지 않음 (배수 {lev}배, 손절 거리 "
                    f"{d['stop_frac']:.2%}, 청산 거리 약 {1 / lev - 0.005:.2%})")
    assert w.src.intent.key in w.ex.done and not [m for _lv, m in w.note.messages if "강제청산" in m]   # never an alarm
    # the checks and the site: a missed signal with its reason, not "did not follow"
    ex = LC.ExecInfo(name="toobit", config="", unit="", db=w.cfg.db, light_n=0, light_min=0.85, exchange="toobit")
    st = LC.entry_state(ex, LC.open_ro(w.cfg.db), w.src.intent.key, [], w.src.intent.entry_time, True)
    assert st == {"state": "skipped", "why_ko": "손절이 강제청산 가격보다 멀어 진입 안 함"}
    assert LC.entry_exec_line(ex, st, symbol).endswith("⏸ 손절이 강제청산 가격보다 멀어 진입 안 함")


def test_the_liq_guard_uses_the_exchanges_own_rate_when_the_client_gives_one(tmp_path):
    w = World(tmp_path, leverage_by_symbol=FIXED, liq_guard=True)
    w.client.maint_margin_ratio = lambda symbol, notional: 0.01       # 1 / 40 - 1 % = 1.5 %: a 1.9 % stop is beyond
    w.paper(stop=98.1)
    w.loop()
    (_lv, _text, d), = events(w, "liq_skip")
    assert d["mmr_from"] == "exchange" and d["mmr"] == 0.01 and w.fake.amt(BTC) == 0


def test_the_liq_guard_with_the_stop_scale_and_the_word_of_the_stop(tmp_path):
    """The template's pair: the paper's 2 ATR stop of 1.8 % x 1.25 = 2.25 % (97.75, rounded up to 97.8: 2.20 %) at 40x is
    beyond the 2 % liquidation."""
    w = World(tmp_path, leverage_by_symbol=FIXED, ladder_from="own", ladder=LADDER, stop_scale=1.25, liq_guard=True)
    w.paper(stop=98.2)
    w.loop()
    (_lv, text, _d), = events(w, "liq_skip")
    assert text.startswith("BTCUSDT 손절(2.5 ATR)이 강제청산 가격보다 멀어 이번 진입은 하지 않음 (배수 40배, 손절 거리 2.20%")


def test_the_site_says_why_the_entry_was_left_out(tmp_path):
    w = World(tmp_path, leverage_by_symbol=FIXED, liq_guard=True)
    w.clock.t += 2 * MIN                                              # the paper entry after the executor's start
    w.paper(stop=97.5)
    w.loop()
    pt = {"symbol": BTC, "entry_time": w.src.intent.entry_time}
    got = L.why_missed(L.read_exec(w.cfg.db, w.clock.t), pt, "V39_ALL@1h")
    assert (got["state"], got["why_kind"], got["why_ko"]) == ("missed", "liq_skip", "손절이 강제청산 가격보다 멀어 들어가지 않았어요")
    assert LC.planned_skip([(0, "entry_check", "x"), (0, "liq_skip", "y")]) == "손절이 강제청산 가격보다 멀어 진입 안 함"
    assert LC.planned_skip([(0, "macro_skip", "y")]) == "미국 경제 발표 앞뒤라 진입 안 함"
    assert LC.planned_skip([(0, "entry_refused", "y")]) is None


# ====================================================================== the US-release block
@pytest.fixture
def calendar(tmp_path, monkeypatch):
    path = tmp_path / "macro_events.csv"

    def put(*evs):
        lines = ["ts_utc,kind,source_url"] + [
            f"{datetime.fromtimestamp(ms / 1000, timezone.utc):%Y-%m-%dT%H:%M:%SZ},{kind},https://www.bls.gov/schedule/"
            for ms, kind in evs]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        EV.reset()
    monkeypatch.setattr(EV, "PATH", path)
    put()
    yield put
    EV.reset()


@pytest.mark.parametrize("minutes,enters", [(29, False), (-29, False), (30, False), (-30, False), (31, True),
                                            (-31, True)])
def test_no_new_entry_within_30_minutes_of_a_us_release(tmp_path, calendar, minutes, enters):
    """``minutes``: the release this long after (+) or before (-) the entry is sent; edges included."""
    w = World(tmp_path, macro_block_min=30)
    w.paper(stop=99.0)
    send = w.clock.t + 3_000                                          # World.loop moves the clock first
    calendar((send + minutes * MIN, "CPI"))
    w.loop()
    if enters:
        assert w.ex.trade is not None and w.fake.amt(BTC) == 5 and not events(w, "macro_skip")
        return
    assert w.ex.trade is None and w.fake.amt(BTC) == 0 and not w.fake.order_bodies
    w.loop(2)
    (lv, text, d), = events(w, "macro_skip")                          # once: marked done, never joined later
    kst = datetime.fromtimestamp((send + minutes * MIN) / 1000 + 9 * 3600, timezone.utc)
    assert lv == "INFO" and text == (f"BTCUSDT 미국 경제 발표(CPI {kst.month}/{kst.day} {kst:%H:%M}) 앞뒤 30분이라 이번 "
                                     "진입은 하지 않음")
    assert d["event"]["kind"] == "CPI" and d["minutes"] == 30 and not [m for _lv, m in w.note.messages if "경제 발표" in m]
    assert w.src.intent.key in w.ex.done and w.fake.amt(BTC) == 0
    ex = LC.ExecInfo(name="toobit", config="", unit="", db=w.cfg.db, light_n=0, light_min=0.85, exchange="toobit")
    st = LC.entry_state(ex, LC.open_ro(w.cfg.db), w.src.intent.key, [], w.src.intent.entry_time, True)
    assert st == {"state": "skipped", "why_ko": "미국 경제 발표 앞뒤라 진입 안 함"}


def test_the_release_block_never_touches_an_open_position(tmp_path, calendar):
    w = World(tmp_path, macro_block_min=30)
    w.paper(stop=99.0)
    w.loop()
    assert w.fake.amt(BTC) == 5
    calendar((w.clock.t + 5 * MIN, "FOMC"))                          # a release starts its window now
    w.loop(3)
    assert w.ex.trade is not None and w.fake.amt(BTC) == 5 and w.stops() == [(99.0, 5.0)]
    assert not events(w, "macro_skip")


def test_without_the_release_block_an_entry_at_the_release_is_made(tmp_path, calendar):
    w = World(tmp_path)
    w.paper(stop=99.0)
    calendar((w.clock.t + 3_000, "NFP"))
    w.loop()
    assert w.ex.trade is not None and w.fake.amt(BTC) == 5 and not events(w, "macro_skip")

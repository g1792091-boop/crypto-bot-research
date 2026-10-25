"""믹스 30분 봇 (paperbot/mixchop.py): the indicator against the design's DOGE table, the ladder, the one-position rule,
the paper exits and the WOO X Pro order path with a fake exchange (no network)."""
import json
import os

import numpy as np
import pandas as pd
import pytest

from paperbot import mixchop as M
from paperbot.testnet import TestnetError

DATA = os.path.join(os.path.dirname(__file__), "data")
KST = 9 * 3_600_000


def _ms(s: str) -> int:
    return int(pd.Timestamp(s, tz="UTC").value // 1_000_000)


def _fixture(tf: str) -> pd.DataFrame:
    return pd.read_csv(os.path.join(DATA, f"mixchop_doge_{tf}.csv.gz"))


# ---------------------------------------------------------------- the design's verification table (BOT_FORMULAS 7)
@pytest.mark.parametrize("kst_close,colour,close,ar30,ar1h,side", [
    ("2026-10-21 14:00", "purple", 0.08153, 33.8, 49.2, -1),
    ("2026-10-21 17:30", "cyan", 0.08191, 69.0, 47.6, 0),        # X: the 1h condition
    ("2026-10-22 07:30", "purple", 0.08242, 31.4, 60.2, 0),      # X
    ("2026-10-23 10:00", "cyan", 0.07902, 58.2, 54.0, 1),
    ("2026-10-24 01:30", "purple", 0.07988, 41.1, 50.6, -1),     # buffer 2: 50.6 < 52 passes
])
def test_doge_table(kst_close, colour, close, ar30, ar1h, side):
    b30, b1h = _fixture("30m"), _fixture("1h")
    ce = _ms(kst_close) - KST
    co = M.Coin("DOGEUSDT", h1_buf=2.0, sl_atr=2.5, roe_act=100, leverage=40)
    ev = M.evaluate(co, M.bars_frame(b30.values.tolist(), M.MIN30, ce), M.bars_frame(b1h.values.tolist(), M.H1, ce), ce)
    assert ev["to_cyan"] == (colour == "cyan") and ev["to_purple"] == (colour == "purple")
    assert ev["close"] == pytest.approx(close, abs=1e-6)
    assert ev["avg_rsi_30m"] == pytest.approx(ar30, abs=0.056)     # the table rounds to 0.1
    assert ev["avg_rsi_1h"] == pytest.approx(ar1h, abs=0.056)
    assert ev["side"] == side


def test_history_length_does_not_matter():
    """1,500 bars give the same colours and values as the whole fixture (the running sum's start cancels)."""
    c = _fixture("30m").close.to_numpy(float)
    g_all, g_1500 = M.line_gold(c), M.line_gold(c[-1500:])
    a_all, a_1500 = M.avg_rsi(c), M.avg_rsi(c[-1500:])
    assert (g_all[-300:] == g_1500[-300:]).all()
    assert np.nanmax(np.abs(a_all[-300:] - a_1500[-300:])) < 1e-6


def test_trend_bar_must_be_closed_and_present():
    b30, b1h = _fixture("30m"), _fixture("1h")
    ce = _ms("2026-10-23 10:00") - KST                       # on the hour: needs the 1h bar closing at the same time
    co = M.Coin("DOGEUSDT", 2.0, 2.5, 100, 40)
    short_1h = M.bars_frame(b1h.values.tolist(), M.H1, ce - M.H1)   # that 1h bar missing
    ev = M.evaluate(co, M.bars_frame(b30.values.tolist(), M.MIN30, ce), short_1h, ce)
    assert ev["side"] == 0 and ev["why"] == "1시간봉이 아직 없음"


def test_liquidation_guard_skips_far_stops():
    b30, b1h = _fixture("30m"), _fixture("1h")
    ce = _ms("2026-10-23 10:00") - KST
    co = M.Coin("DOGEUSDT", 2.0, 40.0, 100, 40)               # 40 x ATR: far past 1/40 - 0.5 %
    ev = M.evaluate(co, M.bars_frame(b30.values.tolist(), M.MIN30, ce), M.bars_frame(b1h.values.tolist(), M.H1, ce), ce)
    assert ev["side"] == 0 and "청산가" in ev["why"]


# ---------------------------------------------------------------- the ladder
def test_ladder_matches_the_design_example():
    # start ROE 150 -> lock 10, then every 140 % ROE more (SIGNAL_30M_GUIDE 4: ROE 290 % -> stop at ROE +150 %)
    entry, lev = 100.0, 40
    stop0 = entry - 1.0
    roe_px = lambda r: entry + entry * r / 100 / lev          # noqa: E731
    assert M.ladder_stop(1, entry, roe_px(149), stop0, 150, lev) == (stop0, 0)
    new, step = M.ladder_stop(1, entry, roe_px(150), stop0, 150, lev)
    assert new == pytest.approx(roe_px(10)) and step == 1
    new, step = M.ladder_stop(1, entry, roe_px(290), roe_px(10), 150, lev)
    assert new == pytest.approx(roe_px(150)) and step == 2
    # never backwards
    assert M.ladder_stop(1, entry, roe_px(200), roe_px(150), 150, lev) == (roe_px(150), -1)
    # short side mirrors
    new, step = M.ladder_stop(-1, entry, entry - entry * 1.5 / lev, entry + 1, 150, lev)
    assert new == pytest.approx(entry - entry * 0.1 / lev) and step == 1


# ---------------------------------------------------------------- the bot (paper)
def _cfg(tmp_path, mode="paper", coins=("SOLUSDT", "ETHUSDT")):
    raw = {"mode": mode, "state": str(tmp_path / "state.json"), "log": str(tmp_path / "log.jsonl"),
           "start_equity": 50.0, "kill_file": str(tmp_path / "STOP"), "own_stop_file": str(tmp_path / "MIX.STOP"),
           "telegram": False,
           "coins": {c: {} for c in coins}}
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps(raw))
    return M.load_config(str(p))


def _bars_rows(start_ms, n, px=100.0, step=0.0, hi=0.5, lo=0.5, tf=M.MIN30):
    rows = []
    for i in range(n):
        o = px + step * i
        rows.append([start_ms + i * tf, o, o + hi, o - lo, o + step])
    return rows


def test_config_defaults_and_refusals(tmp_path):
    cfg = _cfg(tmp_path, coins=("SOLUSDT", "ETHUSDT", "XRPUSDT", "BCHUSDT", "ZECUSDT", "DOGEUSDT"))
    zec = next(c for c in cfg.coins if c.symbol == "ZECUSDT")
    assert (zec.h1_buf, zec.sl_atr, zec.roe_act, zec.leverage) == (6.5, 2.5, 100, 20)
    assert cfg.symbols[0] == "SOLUSDT"                           # the order decides between coins
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"mode": "live", "state": "s", "log": "l", "coins": {"SOLUSDT": {}}}))
    with pytest.raises(M.MixError):
        M.load_config(str(bad))
    bad.write_text(json.dumps({"mode": "paper", "state": "s", "log": "l", "coins": {"LTCUSDT": {}}}))
    with pytest.raises(M.MixError):                              # no defaults for LTC: needs explicit numbers
        M.load_config(str(bad))


def test_one_position_and_coin_order(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    close = _ms("2026-10-26 01:00")
    fetch = lambda s, tf, n: _bars_rows(close - 400 * M.MIN30, 403) if tf == "30m" else []   # noqa: E731
    calls = []

    def fake_eval(co, b30, b1h, ce):
        calls.append(co.symbol)
        return {"symbol": co.symbol, "close_ms": ce, "side": 1, "why": "", "to_cyan": True, "close": 100.0,
                "stop_dist": 1.0, "stop_pct": 1.0, "avg_rsi_30m": 60, "avg_rsi_1h": 55}
    monkeypatch.setattr(M, "evaluate", fake_eval)
    broker = M.PaperBroker(50.0, 0.0)
    bot = M.Bot(cfg, broker, fetch, lambda: close + 5000, sleep=lambda s: None)
    bot.start()
    bot.on_close(close)
    assert bot.pos is not None and bot.pos.symbol == "SOLUSDT"       # SOL first in the config
    assert bot.pos.qty == pytest.approx(50.0 * 0.0025 / 1.0)        # 0.25 % of equity over the stop distance
    assert bot.pos.stop == pytest.approx(99.0)
    rows = [json.loads(x) for x in open(cfg.log)]
    assert any(r["kind"] == "skip" and r["symbol"] == "ETHUSDT" for r in rows)
    # the next close: a signal while holding is skipped ("보유 중")
    bot.on_close(close + M.MIN30)
    rows = [json.loads(x) for x in open(cfg.log)]
    assert any(r["kind"] == "skip" and r.get("why") == "보유 중" for r in rows)
    # restart with a new paper broker (as the service does): the position comes back and is NOT closed
    bot2 = M.Bot(cfg, M.PaperBroker(50.0, 0.0), fetch, lambda: close + M.MIN30 + 9000, sleep=lambda s: None)
    bot2.start()
    assert bot2.pos is not None and bot2.pos.symbol == "SOLUSDT" and bot2.pos.stop == pytest.approx(99.0)
    assert not any(json.loads(x)["kind"] == "exit" for x in open(cfg.log))


def test_close_must_be_final_at_binance(tmp_path, monkeypatch):
    """The local clock says the bar closed, but Binance has not opened the next one: the bar is not used."""
    cfg = _cfg(tmp_path, coins=("SOLUSDT",))
    close = _ms("2026-10-26 01:00")
    monkeypatch.setattr(M, "evaluate", lambda co, a, b, ce: {"symbol": co.symbol, "close_ms": ce, "side": 1, "why": "",
                                                             "to_cyan": True, "close": 100.0, "stop_dist": 1.0,
                                                             "stop_pct": 1.0, "avg_rsi_30m": 60, "avg_rsi_1h": 55})
    fetch = lambda s, tf, n: _bars_rows(close - 400 * M.MIN30, 400) if tf == "30m" else []   # noqa: E731
    bot = M.Bot(cfg, M.PaperBroker(50.0, 0.0), fetch, lambda: close + 5000, sleep=lambda s: None)
    bot.start()
    bot.on_close(close)
    rows = [json.loads(x) for x in open(cfg.log)]
    assert bot.pos is None and any(r["kind"] == "bars_missing" and "아직 없음" in r["why"] for r in rows)


def test_kill_file_and_equity_floor_stop_entries(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    close = _ms("2026-10-26 01:00")
    monkeypatch.setattr(M, "evaluate", lambda co, a, b, ce: {"symbol": co.symbol, "close_ms": ce, "side": -1, "why": "",
                                                             "to_purple": True, "close": 100.0, "stop_dist": 1.0,
                                                             "stop_pct": 1.0, "avg_rsi_30m": 40, "avg_rsi_1h": 45})
    broker = M.PaperBroker(50.0, 0.0)
    bot = M.Bot(cfg, broker, lambda s, tf, n: [], lambda: close, sleep=lambda s: None)
    bot.start()
    open(cfg.kill_file, "w").close()
    bot.on_close(close)
    assert bot.pos is None
    os.remove(cfg.kill_file)
    open(cfg.own_stop_file, "w").close()                          # the bot's own switch works the same way
    bot.on_close(close + M.MIN30)
    assert bot.pos is None and "정지 파일" in bot.halt_reason
    os.remove(cfg.own_stop_file)
    broker.eq = 30.0                                              # below 70 % of 50
    bot.on_close(close + 2 * M.MIN30)
    assert bot.pos is None and "시작 잔고" in bot.halt_reason


def test_paper_stop_ladder_and_exit(tmp_path):
    cfg = _cfg(tmp_path, coins=("SOLUSDT",))
    broker = M.PaperBroker(50.0, 0.0)
    t0 = _ms("2026-10-26 01:00")
    bars = {}
    bot = M.Bot(cfg, broker, lambda s, tf, n: bars["rows"], lambda: t0, sleep=lambda s: None)
    bot.start()
    co = bot.coins["SOLUSDT"]                                     # 40x, ladder from ROE 150
    ev = {"symbol": "SOLUSDT", "close_ms": t0, "side": 1, "why": "", "close": 100.0, "stop_dist": 1.0, "stop_pct": 1.0,
          "avg_rsi_30m": 60, "avg_rsi_1h": 55}
    bot.enter(co, ev)
    assert bot.pos.stop == pytest.approx(99.0)
    # next bar runs to ROE 150 % (price 103.75): the stop goes to ROE +10 % (100.25) at that close
    bars["rows"] = [[t0, 100.0, 103.8, 99.5, 103.5]]
    bot.manage(t0 + M.MIN30)
    assert bot.pos.stop == pytest.approx(100.25) and bot.pos.step == 1
    # next bar falls through the stop: exit at the stop price, a small win (ladder)
    bars["rows"] = [[t0, 100.0, 103.8, 99.5, 103.5], [t0 + M.MIN30, 103.0, 103.2, 100.0, 100.1]]
    bot.manage(t0 + 2 * M.MIN30)
    assert bot.pos is None
    ex = [json.loads(x) for x in open(cfg.log) if '"exit"' in x][-1]
    assert ex["why"] == "ladder" and ex["price"] == pytest.approx(100.25) and ex["pnl"] > 0


def test_paper_gap_exits_at_the_open(tmp_path):
    cfg = _cfg(tmp_path, coins=("SOLUSDT",))
    broker = M.PaperBroker(50.0, 0.0)
    t0 = _ms("2026-10-26 01:00")
    bars = {"rows": [[t0, 98.0, 98.5, 97.0, 97.5]]}               # opens below the 99 stop
    bot = M.Bot(cfg, broker, lambda s, tf, n: bars["rows"], lambda: t0, sleep=lambda s: None)
    bot.start()
    bot.enter(bot.coins["SOLUSDT"], {"symbol": "SOLUSDT", "close_ms": t0, "side": 1, "why": "", "close": 100.0,
                                    "stop_dist": 1.0, "stop_pct": 1.0, "avg_rsi_30m": 60, "avg_rsi_1h": 55})
    bot.manage(t0 + M.MIN30)
    ex = [json.loads(x) for x in open(cfg.log) if '"exit"' in x][-1]
    assert ex["why"] == "stop" and ex["price"] == pytest.approx(98.0)


# ---------------------------------------------------------------- WOO X Pro path (fake exchange)
class FakeWoo:
    def __init__(self, px=100.0, eq=50.0):
        self.px, self.eq = px, eq
        self.pos, self.entry, self.algos, self.n = {}, {}, {}, 0
        self.sleep = lambda s: None
        self.orders = []
        self.hide_reads = 0          # the position reads 0 this many times after an entry (a late fill)
        self.answer_frac = 1.0       # the order answer shows this part of the fill (a partial read-back)

    def account(self):
        return {"totalMarginBalance": str(self.eq)}

    def positions(self):
        return [{"symbol": s, "positionAmt": str(a)} for s, a in self.pos.items() if a]

    def position(self, s):
        if self.hide_reads > 0:
            self.hide_reads -= 1
            return {"symbol": s, "positionAmt": "0", "entryPrice": "0"}
        return {"symbol": s, "positionAmt": str(self.pos.get(s, 0.0)), "entryPrice": str(self.entry.get(s, 0.0))}

    def one_way(self):
        pass

    def leverage(self, s, lev):
        return {"symbol": s, "leverage": lev}

    def spec(self, s):
        return {"qty_step": 0.01, "min_qty": 0.01, "tick": 0.01, "min_notional": 5.0}

    def market(self, s, side, qty, reduce_only=False, client_id=None):
        self.orders.append((s, side, qty, reduce_only))
        if reduce_only:
            self.pos[s] = 0.0
        else:
            self.pos[s] = qty if side == "BUY" else -qty
            self.entry[s] = self.px
            if self.hide_reads:
                return {"executedQty": "0", "avgPrice": "0", "status": "NEW"}
        return {"executedQty": str(qty * self.answer_frac), "avgPrice": str(self.px), "status": "FILLED"}

    def stop_close(self, s, side, trigger, qty=None, client_id=None):
        if (side == "SELL" and trigger >= self.px) or (side == "BUY" and trigger <= self.px):
            raise TestnetError(400, -2021, "would trigger")
        self.n += 1
        a = {"algoId": str(self.n), "clientAlgoId": client_id, "symbol": s, "side": side, "orderType": "STOP_MARKET",
             "triggerPrice": trigger, "quantity": qty, "algoStatus": "NEW"}
        self.algos[a["algoId"]] = a
        return dict(a)

    def algo_order(self, algo_id=None, client_id=None):
        if algo_id in self.algos:
            return dict(self.algos[algo_id])
        raise TestnetError(400, -2013, "not found")

    def open_algo_orders(self, s):
        return [dict(a) for a in self.algos.values() if a["symbol"] == s and a["algoStatus"] == "NEW"]

    def cancel_algo(self, algo_id=None, client_id=None):
        self.algos[algo_id]["algoStatus"] = "CANCELED"

    def cancel_all_algo(self, s):
        for a in self.algos.values():
            if a["symbol"] == s:
                a["algoStatus"] = "CANCELED"

    def fire(self, s):
        self.pos[s] = 0.0
        for a in self.algos.values():
            if a["symbol"] == s and a["algoStatus"] == "NEW":
                a["algoStatus"] = "FINISHED"


def test_live_entry_places_a_resting_stop_and_moves_it(tmp_path):
    cfg = _cfg(tmp_path, mode="mainnet", coins=("SOLUSDT",))
    fake = FakeWoo()
    broker = M.WooBroker(fake, cfg.coins)
    t0 = _ms("2026-10-26 01:00")
    bars = {"rows": []}
    bot = M.Bot(cfg, broker, lambda s, tf, n: bars["rows"], lambda: t0, sleep=lambda s: None)
    bot.start()
    bot.enter(bot.coins["SOLUSDT"], {"symbol": "SOLUSDT", "close_ms": t0, "side": 1, "why": "", "close": 100.0,
                                    "stop_dist": 1.0, "stop_pct": 1.0, "avg_rsi_30m": 60, "avg_rsi_1h": 55})
    p = bot.pos
    assert p.qty == pytest.approx(0.12)                          # 0.125 / 1.0 floored to 0.01
    live = fake.open_algo_orders("SOLUSDT")
    assert len(live) == 1 and live[0]["triggerPrice"] == pytest.approx(99.0) and live[0]["side"] == "SELL"
    # the price runs to ROE 150 %: the stop moves to ROE +10 % (new one first, old one cancelled)
    fake.px = 103.6
    bars["rows"] = [[t0, 100.0, 103.8, 99.5, 103.6]]
    bot.manage(t0 + M.MIN30)
    live = fake.open_algo_orders("SOLUSDT")
    assert len(live) == 1 and live[0]["triggerPrice"] == pytest.approx(100.25) and bot.pos.step == 1
    # the stop fires: poll sees flat twice and finishes; leftover stops cancelled, state cleared
    fake.fire("SOLUSDT")
    fake.eq = 50.4
    bot.poll()
    assert bot.pos is None
    assert M.read_state(cfg.state)["position"] is None
    ex = [json.loads(x) for x in open(cfg.log) if '"exit"' in x][-1]
    assert ex["pnl"] == pytest.approx(0.4)


def test_live_restart_replaces_a_missing_stop(tmp_path):
    cfg = _cfg(tmp_path, mode="mainnet", coins=("SOLUSDT",))
    fake = FakeWoo()
    fake.pos["SOLUSDT"], fake.entry["SOLUSDT"] = 0.12, 100.0
    pos = M.Position(symbol="SOLUSDT", side=1, qty=0.12, entry=100.0, stop_dist=1.0, stop=99.0, best=100.0, step=0,
                     opened_ms=1, signal_close_ms=1, signal_close=100.0, last_bar_ms=1, equity_before=50.0)
    M.write_state(cfg.state, {"position": M.asdict(pos), "start_equity": 50.0, "last_close_ms": 1})
    bot = M.Bot(cfg, M.WooBroker(fake, cfg.coins), lambda s, tf, n: [], lambda: 2, sleep=lambda s: None)
    bot.start()
    live = fake.open_algo_orders("SOLUSDT")
    assert len(live) == 1 and live[0]["triggerPrice"] == pytest.approx(99.0)


def test_live_unknown_position_blocks_entries(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, mode="mainnet", coins=("SOLUSDT",))
    fake = FakeWoo()
    fake.pos["ETHUSDT"] = 0.5                                      # someone else's position on the account
    monkeypatch.setattr(M, "evaluate", lambda co, a, b, ce: {"symbol": co.symbol, "close_ms": ce, "side": 1, "why": "",
                                                             "to_cyan": True, "close": 100.0, "stop_dist": 1.0,
                                                             "stop_pct": 1.0, "avg_rsi_30m": 60, "avg_rsi_1h": 55})
    bot = M.Bot(cfg, M.WooBroker(fake, cfg.coins), lambda s, tf, n: [], lambda: 2, sleep=lambda s: None)
    bot.start()
    bot.on_close(_ms("2026-10-26 01:00"))
    assert bot.pos is None and "모르는 포지션" in bot.halt_reason and not fake.orders


def test_live_too_small_is_skipped_not_rounded_up(tmp_path):
    cfg = _cfg(tmp_path, mode="mainnet", coins=("SOLUSDT",))
    fake = FakeWoo(eq=1.0)                                          # 0.25 % of $1 = $0.0025 -> 0.0025 coins < 0.01
    bot = M.Bot(cfg, M.WooBroker(fake, cfg.coins), lambda s, tf, n: [], lambda: 2, sleep=lambda s: None)
    bot.start()
    bot.enter(bot.coins["SOLUSDT"], {"symbol": "SOLUSDT", "close_ms": 1, "side": 1, "why": "", "close": 100.0,
                                    "stop_dist": 1.0, "stop_pct": 1.0, "avg_rsi_30m": 60, "avg_rsi_1h": 55})
    assert bot.pos is None and not fake.orders


def test_stop_refused_closes_the_position(tmp_path):
    cfg = _cfg(tmp_path, mode="mainnet", coins=("SOLUSDT",))
    fake = FakeWoo()

    def refuse(*a, **k):
        raise TestnetError(400, -1, "refused")
    fake.stop_close = refuse
    bot = M.Bot(cfg, M.WooBroker(fake, cfg.coins), lambda s, tf, n: [], lambda: 2, sleep=lambda s: None)
    bot.start()
    bot.enter(bot.coins["SOLUSDT"], {"symbol": "SOLUSDT", "close_ms": 1, "side": 1, "why": "", "close": 100.0,
                                    "stop_dist": 1.0, "stop_pct": 1.0, "avg_rsi_30m": 60, "avg_rsi_1h": 55})
    assert fake.pos["SOLUSDT"] == 0.0 and bot.pos is None
    assert any(o[3] for o in fake.orders)                           # a reduce-only close was sent


def _enter(bot, sym="SOLUSDT", side=1, close=100.0, dist=1.0):
    bot.enter(bot.coins[sym], {"symbol": sym, "close_ms": 1, "side": side, "why": "", "close": close, "stop_dist": dist,
                               "stop_pct": 1.0, "avg_rsi_30m": 60, "avg_rsi_1h": 55})


def test_restart_with_the_price_past_the_stop_closes_at_market(tmp_path):
    """The stop went missing while the bot was down and the price is already past it: WOO X Pro refuses the stop,
    so the position is closed at market (never left without a stop)."""
    cfg = _cfg(tmp_path, mode="mainnet", coins=("SOLUSDT",))
    fake = FakeWoo()
    bot = M.Bot(cfg, M.WooBroker(fake, cfg.coins), lambda s, tf, n: [], lambda: 2, sleep=lambda s: None)
    bot.start()
    _enter(bot)
    fake.cancel_all_algo("SOLUSDT")
    fake.px = 98.5                                                # below the 99 stop
    bot2 = M.Bot(cfg, M.WooBroker(fake, cfg.coins), lambda s, tf, n: [], lambda: 3, sleep=lambda s: None)
    bot2.start()
    assert bot2.pos is None and fake.pos["SOLUSDT"] == 0.0
    assert fake.orders[-1][3] is True                             # the last order was the reduce-only close


def test_stop_missing_during_the_run_and_refused_closes(tmp_path):
    cfg = _cfg(tmp_path, mode="mainnet", coins=("SOLUSDT",))
    fake = FakeWoo()
    bot = M.Bot(cfg, M.WooBroker(fake, cfg.coins), lambda s, tf, n: [], lambda: 2, sleep=lambda s: None)
    bot.start()
    _enter(bot)
    fake.cancel_all_algo("SOLUSDT")

    def refuse(*a, **k):
        raise TestnetError(400, -1, "refused")
    fake.stop_close = refuse
    bot._last_stop_check = -1e9
    bot.poll()
    assert bot.pos is None and fake.pos["SOLUSDT"] == 0.0


def test_late_fill_is_found_and_protected(tmp_path):
    cfg = _cfg(tmp_path, mode="mainnet", coins=("SOLUSDT",))
    fake = FakeWoo()
    bot = M.Bot(cfg, M.WooBroker(fake, cfg.coins), lambda s, tf, n: [], lambda: 2, sleep=lambda s: None)
    bot.start()
    fake.hide_reads = 2                                           # the answer and the first reads show nothing
    _enter(bot)
    assert bot.pos is not None and bot.pos.qty == pytest.approx(0.12)
    live = fake.open_algo_orders("SOLUSDT")
    assert len(live) == 1 and live[0]["quantity"] == pytest.approx(0.12) and live[0]["triggerPrice"] == pytest.approx(99.0)


def test_partial_answer_uses_the_exchange_size(tmp_path):
    cfg = _cfg(tmp_path, mode="mainnet", coins=("SOLUSDT",))
    fake = FakeWoo()
    fake.answer_frac = 0.5
    bot = M.Bot(cfg, M.WooBroker(fake, cfg.coins), lambda s, tf, n: [], lambda: 2, sleep=lambda s: None)
    bot.start()
    _enter(bot)
    assert bot.pos.qty == pytest.approx(0.12)
    assert fake.open_algo_orders("SOLUSDT")[0]["quantity"] == pytest.approx(0.12)


def test_second_instance_is_refused(tmp_path):
    cfg = _cfg(tmp_path)
    path = tmp_path / "paper.json"
    path.write_text(json.dumps({"mode": "paper", "state": cfg.state, "log": cfg.log, "coins": {"SOLUSDT": {}},
                                "start_equity": 50, "telegram": False}))
    import fcntl
    held = open(cfg.state + ".lock", "a")
    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    assert M.main(["run", "--config", str(path)]) == 2


def test_mainnet_without_keys_exits_2(tmp_path, monkeypatch):
    for k in list(os.environ):
        if k.startswith("WOOXPRO") or k.startswith("PAPERBOT_LIVE"):
            monkeypatch.delenv(k, raising=False)
    cfg = _cfg(tmp_path)
    path = tmp_path / "live.json"
    path.write_text(json.dumps({"mode": "mainnet", "state": cfg.state, "log": cfg.log, "coins": {"SOLUSDT": {}},
                                "telegram": False}))
    assert M.main(["run", "--config", str(path)]) == 2


def test_entry_blocks_weekend_nasdaq_open_and_releases(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.no_weekend, cfg.us_open_pre_min, cfg.us_open_pause_min, cfg.macro_blackout_min = True, 30, 30, 30
    assert "주말" in M.entry_block(cfg, _ms("2026-10-24 15:00"))           # Sunday 00:00 KST
    assert "주말" in M.entry_block(cfg, _ms("2026-10-23 15:00"))           # Saturday 00:00 KST
    assert M.entry_block(cfg, _ms("2026-10-23 14:59")) == ""                # Friday 23:59 KST
    assert M.entry_block(cfg, _ms("2026-10-25 15:00")) == ""                # Monday 00:00 KST
    # Monday 10-26: New York on summer time, 09:30 open = 13:30 UTC; blocked 13:00 .. 13:59
    assert "나스닥" in M.entry_block(cfg, _ms("2026-10-26 13:00"))
    assert "나스닥" in M.entry_block(cfg, _ms("2026-10-26 13:59"))
    assert M.entry_block(cfg, _ms("2026-10-26 14:00")) == ""
    assert M.entry_block(cfg, _ms("2026-10-26 12:59")) == ""
    # after the change to winter time (11-02 Monday): the open is 14:30 UTC
    assert "나스닥" in M.entry_block(cfg, _ms("2026-11-02 14:05"))
    assert M.entry_block(cfg, _ms("2026-11-02 13:05")) == ""
    # CPI 2026-10-14 12:30 UTC (data/macro_events.csv): 12:00 .. 13:00 blocked
    assert "경제 발표" in M.entry_block(cfg, _ms("2026-10-14 12:05"))
    assert M.entry_block(cfg, _ms("2026-10-14 11:59")) == ""                # (13:00 .. 14:00 is the Nasdaq block)
    cfg.no_weekend, cfg.us_open_pre_min, cfg.us_open_pause_min, cfg.macro_blackout_min = False, 0, 0, 0
    assert M.entry_block(cfg, _ms("2026-10-24 15:00")) == ""                # all off: the friend's design


def test_entry_block_skips_the_signal(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, coins=("SOLUSDT",))
    cfg.no_weekend = True
    close = _ms("2026-10-24 15:00")                                         # Sunday KST
    monkeypatch.setattr(M, "evaluate", lambda co, a, b, ce: {"symbol": co.symbol, "close_ms": ce, "side": 1, "why": "",
                                                             "to_cyan": True, "close": 100.0, "stop_dist": 1.0,
                                                             "stop_pct": 1.0, "avg_rsi_30m": 60, "avg_rsi_1h": 55})
    fetch = lambda s, tf, n: _bars_rows(close - 400 * M.MIN30, 401) if tf == "30m" else []   # noqa: E731
    bot = M.Bot(cfg, M.PaperBroker(50.0, 0.0), fetch, lambda: close + 5000, sleep=lambda s: None)
    bot.start()
    bot.on_close(close)
    rows = [json.loads(x) for x in open(cfg.log)]
    assert bot.pos is None and any(r["kind"] == "skip" and "주말" in r["why"] for r in rows)


def test_stop_failure_with_a_disagreeing_read_is_not_treated_as_protected(tmp_path):
    """The stop is refused right after the fill and the position reads 0 once: the bot must not announce a protected
    entry; poll() keeps working on it (unprotected) until the exchange agrees."""
    cfg = _cfg(tmp_path, mode="mainnet", coins=("SOLUSDT",))
    fake = FakeWoo()
    msgs = []
    bot = M.Bot(cfg, M.WooBroker(fake, cfg.coins), lambda s, tf, n: [], lambda: 2, notify=lambda lv, t: msgs.append(t),
                sleep=lambda s: None)
    bot.start()
    orig = fake.stop_close

    def refuse_once(*a, **k):
        fake.stop_close = orig
        fake.hide_reads = 1                                       # the next position read shows 0
        raise TestnetError(400, -1, "refused")
    fake.stop_close = refuse_once
    _enter(bot)
    assert bot.pos is not None and bot._unprotected
    assert any("손절을 아직 확인하지 못했습니다" in m for m in msgs)            # the entry is told with the warning
    bot.poll()                                                    # reads agree now: the stop is placed
    assert not bot._unprotected and len(fake.open_algo_orders("SOLUSDT")) == 1


def test_unknown_position_is_told_once(tmp_path):
    cfg = _cfg(tmp_path, mode="mainnet", coins=("SOLUSDT",))
    fake = FakeWoo()
    fake.pos["ETHUSDT"] = 0.5
    msgs = []
    bot = M.Bot(cfg, M.WooBroker(fake, cfg.coins), lambda s, tf, n: [], lambda: 2, notify=lambda lv, t: msgs.append(t),
                sleep=lambda s: None)
    bot.start()
    for _ in range(3):
        bot.halts()
        bot.check_unknown()
    assert sum("모르는 포지션" in m for m in msgs) == 1

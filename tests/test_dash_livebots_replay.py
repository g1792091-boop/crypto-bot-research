"""실거래 › 다시보기 (D2; dash/more/livetape.py, screens/livebots-replay.js): one closed trade of the live setup replayed on
the 1-minute bars it was stepped on, the stop path and the ladder locks rebuilt with the engine's own functions.

The trades here are made by the real engine (paperbot/combo.py ComboEngine = PaperEngine with the combined bot's sizing,
stops and ladder; the config of tests/livebots_world.py: BTC 40x, the rest 30x, lock 10 % at 11 %, then 3 % steps) on
hand-made 1-minute bars, stored with the bots' own writers (Store3.trade / outcome / live_bars, ExecStore) into the
standard live world (tests/livebots_world.py). Then:
- PARITY: the stop the replay rebuilds for every minute, its locks and its exit equal the engine's own (long and short,
  two locks then out at the lock, out at the first stop, a gap through the stop, a lock on an entry bar filled at the
  open, none on one filled at the reference price, funding paid at 08:00 UTC, a 13-hour trade);
- 기록과 다름: a record changed by hand is shown as recorded and flagged with both values;
- 1분봉 없음 / 수집 전 / 못 읽음, the 5-minute bars of a long trade (made only of the minutes that exist), the executors'
  pairing (livebots.match: same coin and side, entry within 5 minutes) and the list, the route behind the login;
- the screen in node (the tiny DOM, tests/anasyn_dom.mjs) and static checks of its css and js.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import livebots_world as W  # noqa: E402
from paperbot import combo as C  # noqa: E402
from paperbot.executor import ExecStore  # noqa: E402
from paperbot.margin import BracketTier, Brackets  # noqa: E402
from paperbot.models import Bar, Signal  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402
from paperbot.dash.more import livebots as L  # noqa: E402
from paperbot.dash.more import livetape as R  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENS = os.path.join(ROOT, "paperbot", "dash", "static", "v4", "screens")
JS = os.path.join(SCREENS, "livebots-replay.js")
CSS = os.path.join(SCREENS, "livebots-replay.css")
MIN, H, DAY, T0, NOW = W.MIN, W.H, W.DAY, W.T0, W.NOW
SYMS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")
SPECS = {s: {"qty_step": 0.0001 if s == "BTCUSDT" else 0.001, "min_notional": 5.0, "tick_size": 0.01} for s in SYMS}
BRK = Brackets([BracketTier(300_000, 125, 0.004, 0.0), BracketTier(800_000, 50, 0.005, 300.0)])


# ================================================================ the engine-made trades
def combo_cfg(folder: str) -> C.ComboConfig:
    """The world's config (tests/livebots_world.py CONFIG: the shape of deploy/combo.live-ac.json) as the engine reads it."""
    d = {k: v for k, v in W.CONFIG.items()}
    return C.ComboConfig.from_dict({**d, "paper_db": os.path.join(folder, "paper3.db"), "db": os.path.join(folder, "live-ac.db"),
                                    "telegram": False})


def _rise(a, b, n):
    return [a + (b - a) * (i + 1) / n for i in range(n)]


def paths() -> dict:
    """The hand-made minutes of each trade: (coin, side, entry ms, reference price or None, ATR, [(o, h, l, c)], funding
    {minute ms: rate}). Prices are chosen around the ladder's levels (fill = reference x (1 ± 0.02 %), round trip 0.14 %)."""
    out = {}
    # A: BTC long 40x, filled at the reference price. The entry bar's high is past +11 % (no lock on that bar: part of it
    # may predate the fill), the next bar locks 10 % (the entry bar's high counts), then +14 % locks 13 %, then out there.
    out["A"] = ("BTCUSDT", 1, T0 + 7 * H + 5 * MIN, 60000.0, 60.0, [
        (60000, 60270, 59990, 60200), (60200, 60230, 60150, 60220), (60250, 60320, 60248, 60300), (60300, 60310, 60295, 60305),
        (60300, 60302, 60280, 60285)], {})
    # B: ETH short 30x filled at the bar open (no reference price): the entry bar itself locks 10 %, the next 13 % (a bar
    # that climbs two steps sets only the higher), then out at the 13 % lock
    out["B"] = ("ETHUSDT", -1, T0 + 8 * H + 30 * MIN, None, 2.5, [
        (2500, 2501, 2486, 2490), (2485, 2487, 2482, 2483), (2484, 2486, 2483, 2485)], {})
    # C: SOL long 30x, a loss: drifts down and touches the first stop
    out["C"] = ("SOLUSDT", 1, T0 + 8 * H + 40 * MIN, 150.0, 0.15, [
        (150, 150.1, 149.9, 150.0), (150.0, 150.05, 149.8, 149.85), (149.85, 149.9, 149.7, 149.75), (149.75, 149.8, 149.6, 149.65),
        (149.65, 149.7, 149.5, 149.52)], {})
    # D: LTC short 30x, a loss through a gap: the bar opens past the first stop (filled at that open)
    out["D"] = ("LTCUSDT", -1, T0 + 8 * H + 50 * MIN, 80.0, 0.08, [
        (80.0, 80.1, 79.95, 80.05), (80.05, 80.2, 80.0, 80.2), (80.3, 80.35, 80.25, 80.3)], {})
    # E: BTC long held over 08:00 UTC (funding paid at that minute's open), then locks 10 % and is stopped there
    flat = [(60000, 60010, 59990, 60000)] * 10                           # 07:50 .. 07:59
    up = [(c, c + 5, c - 5, c) for c in _rise(60000, 60275, 8)]          # 08:00 .. 08:07
    out["E"] = ("BTCUSDT", 1, T0 + 7 * H + 50 * MIN, 60000.0, 60.0, flat + up + [
        (60275, 60280, 60268, 60270), (60265, 60266, 60245, 60250)], {T0 + 8 * H: 0.0001})
    # F: BTC long held 13 hours (shown on 5-minute bars): locks 10 % in its third hour, sideways above the lock, then out
    rise = [(c, c + 3, c - 3, c) for c in _rise(60000, 60262, 120)]
    side = [(60262 + (5 if i % 2 else -5), 60270, 60250, 60262) for i in range(660)]
    out["F"] = ("BTCUSDT", 1, T0 - 20 * H, 60000.0, 60.0, [(60000, 60005, 59995, 60000)] * 10 + rise + side + [
        (60255, 60256, 60200, 60210)], {})
    return out


def run_engine(cfg, spec: tuple):
    """The real ComboEngine over the trade's minutes: (TradeRecord, ENTERED outcome, [(minute, stop after it, lock)])."""
    sym, side, t0, ref, atr, mins, fund = spec
    trades, outs, stops = [], [], []
    e = C.ComboEngine(C.settings_of(cfg), {s: BRK for s in SYMS}, combo=cfg, symbol_specs=SPECS, on_trade=trades.append,
                      on_outcome=outs.append)
    meta = {"member": "S2_ST_ROC@15m#1~abc123", "member_order": 1, "source": "custom"}
    if ref is not None:
        meta["ref_price"] = ref
    e.submit(Signal(ts=t0 - 1, symbol=sym, timeframe="15m", strategy_id="S2_ST_ROC", side=side, stop_price=0.0, tier="best",
                    score=3.0, atr=atr, meta=meta))
    for i, (o, hi, lo, c) in enumerate(mins):
        ts = t0 + i * MIN
        e.step({sym: Bar(sym, ts, ts + MIN - 1, float(o), float(hi), float(lo), float(c))}, {sym: fund[ts]} if ts in fund else None)
        if e.position is not None:
            stops.append((ts, e.position.stop_price, e.position.lock_roe))
        elif trades:
            stops.append((ts, None, None))
            break
    assert len(trades) == 1, (spec[:3], len(trades), [o.status + ":" + o.reason for o in outs])
    entered = [o for o in outs if o.status == "ENTERED"]
    return trades[0], entered[0], stops


def bar_rows(spec: tuple, rec) -> list:
    """The rule bot's live_bars rows of the trade: 40 flat minutes before (the shown 30 and more), its minutes, 40 after."""
    sym, side, t0, _ref, _atr, mins, _f = spec
    last = mins[-1][3]
    first = mins[0][0]
    tick = first * 0.0002

    def wig(base, k):                                 # a small deterministic wiggle (the market before and after)
        c = base + tick * (math.sin(k * 0.7) + 0.6 * math.sin(k * 1.9))
        o = base + tick * (math.sin((k - 1) * 0.7) + 0.6 * math.sin((k - 1) * 1.9))
        return o, max(o, c) + tick * 0.4, min(o, c) - tick * 0.4, c

    rows = []
    for k in range(40, 0, -1):
        o, hi, lo, c = wig(first, k) if k > 1 else (first, first, first, first)
        rows.append((t0 - k * MIN, o, hi, lo, c))
    for i, (o, hi, lo, c) in enumerate(mins):
        rows.append((t0 + i * MIN, o, hi, lo, c))
    x0 = rec.exit_time - rec.exit_time % MIN
    away = last - side * tick * 3                      # after the exit the price moves on (away from the last stop)
    for k in range(1, 41):
        rows.append((x0 + k * MIN, *wig(away, k)))
    return [{"ts": ts, "symbol": sym, "open": float(o), "high": float(hi), "low": float(lo), "close": float(c), "volume": 1.0,
             "close_time": ts + MIN - 1, "processed_at": ts + MIN} for ts, o, hi, lo, c in rows]


def live_trade(path: str, rec, lag_s: int = 15, entry=None, stop_final=None, pnl=None, fee=0.05, stop_initial=None) -> str:
    """An executor's trade following the paper trade ``rec`` (key = account | coin | the paper's entry ms), written by
    ExecStore's own methods; closed when the paper closed (+ lag) with its exchange stop and its own result."""
    st = ExecStore(path, lock=False)
    key = f"{W.ACCOUNT}|{rec.symbol}|{rec.entry_time}"
    ep = entry if entry is not None else rec.entry_price * (1 + rec.side * 0.0001)
    t = {"key": key, "symbol": rec.symbol, "side": rec.side, "qty": round(rec.qty * 0.1, 6), "leverage": rec.leverage,
         "entry_ts": rec.entry_time + lag_s * 1000, "entry_price": ep, "stop_initial": stop_initial if stop_initial is not None else rec.stop_initial,
         "mode": "mainnet", "entry_time": rec.entry_time, "paper_entry": rec.entry_price}
    st.trade_open(t)
    data = {**t, "stop": stop_final if stop_final is not None else rec.stop_price, "exit_ref": rec.exit_price}
    st.trade_close(key, rec.exit_time + lag_s * 1000, "paper 청산 → 거래소 포지션 닫기", pnl, data, "wallet")
    st.trade_costs(key, {"pnl": pnl, "realized": pnl + fee, "commission": fee, "funding": 0.0, "slippage": 0.01, "real_cost": fee + 0.01,
                         "assumed_cost": fee, "ok": True})
    st.close()
    return key


def replay_world(folder: str) -> dict:
    """The standard live world plus the engine-made trades A-F (ids in ``ids``), their bars in the rule bot's paper3.db,
    bybit following A (a win), C (a loss) and F; MEXC's own reason for not following A (its entry check)."""
    p = W.build_world(folder)
    cfg = combo_cfg(folder)
    rule = os.path.join(folder, "rule-paper3.db")
    made = {}
    s = Store3(p["paper"])
    bars = Store3(rule)
    for name, spec in paths().items():
        rec, out, stops = run_engine(cfg, spec)
        s.trade(W.ACCOUNT, rec)
        s.outcome(W.ACCOUNT, out)
        bars.live_bars(bar_rows(spec, rec))
        made[name] = (rec, stops, spec)
    s.conn.commit()
    ids = {}
    for name, (rec, _stops, _spec) in made.items():
        ids[name] = s.conn.execute("SELECT id FROM trades WHERE account_id = ? AND entry_time = ? AND symbol = ?",
                                   (W.ACCOUNT, rec.entry_time, rec.symbol)).fetchone()[0]
    s.close()
    bars.close()
    a, c, f = made["A"][0], made["C"][0], made["F"][0]
    live_trade(p["bybit_db"], a, pnl=1.07, stop_final=a.stop_price)
    live_trade(p["bybit_db"], c, pnl=-5.9, entry=c.entry_price * 1.0003)
    live_trade(p["bybit_db"], f, pnl=0.95)
    st = ExecStore(p["mexc_db"], lock=False)
    st.event(a.entry_time + 3_000, "WARN", "entry_check", "진입 검사(BTCUSDT): skip - 테스트", {"key": f"{W.ACCOUNT}|BTCUSDT|{a.entry_time}"})
    st.close()
    return {"p": p, "rule": rule, "more": {**L.paths_more({}), "rule_db": rule}, "made": made, "ids": ids, "cfg": cfg}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setenv("PAPERBOT_LIVE_COMBO_CONFIG", "/nonexistent/combo.json")
    L._cache.clear()
    R._one.clear()
    yield
    L._cache.clear()
    R._one.clear()


@pytest.fixture(scope="module")
def rw(tmp_path_factory):
    return replay_world(str(tmp_path_factory.mktemp("replay") / "w"))


def one(rw, name: str, **kw) -> dict:
    return R.build_one(rw["p"], rw["ids"][name], now_ms=NOW + 2 * DAY, more=kw.get("more", rw["more"]))


# ================================================================ parity with the engine
@pytest.mark.parametrize("name", ["A", "B", "C", "D", "E", "F"])
def test_parity_the_rebuilt_stop_path_and_exit_are_the_engines(rw, name):
    rec, stops, spec = rw["made"][name]
    d = one(rw, name)
    assert d["state"] == "ok" and d["bars"]["state"] == "ok"
    assert d["check"]["state"] == "same", d["check"]
    # every minute the engine stepped: the stop after it (in effect from the next minute) and the lock are the same numbers
    t = R.read_trade(rw["p"]["paper"], rw["ids"][name])["trade"]
    rules = R.rules_of(t, R.read_trade(rw["p"]["paper"], rw["ids"][name])["run"])
    rows = R.read_bars(rw["rule"], rec.symbol, rec.entry_time, rec.exit_time + MIN)["rows"]
    fund, _how = R.funding_steps(rec.entry_time, rec.exit_time, rec.funding, rec.qty * rec.entry_price)
    rb = R.rebuild(t, rows, rules, spec[3] is not None, fund)
    got = [(m[0], m[2], m[4] if m[2] is not None else None) for m in rb["minutes"]]
    assert got == stops, (name, got[:5], stops[:5])
    x = rb["exit"]
    assert (x["t"], x["price"], x["reason"]) == (rec.exit_time, rec.exit_price, rec.exit_reason)
    assert rb["lock"] == rec.lock_roe and rb["stop"] == rec.stop_price and rb["mfe"] == rec.mfe_price
    # and the answer's own numbers are the record's
    assert d["exit"]["rebuilt"]["t"] == rec.exit_time and d["exit"]["rebuilt"]["price"] == rec.exit_price
    assert d["exit"]["record"] == {"t": rec.exit_time, "price": rec.exit_price, "reason": rec.exit_reason,
                                   "reason_ko": L.EXIT_KO[rec.exit_reason]}
    locks = [(k["lock"], k["price"]) for k in d["locks"]]
    engine_locks = []
    for _ts, stop, lock in stops:
        if lock is not None and (not engine_locks or engine_locks[-1][0] != lock):
            engine_locks.append((lock, stop))
    assert locks == engine_locks
    assert d["rules"]["round_trip"] == C.settings_of(rw["cfg"]).round_trip_cost and d["rules"]["taker_from"] == "trade"


def test_parity_cases_are_what_they_say(rw):
    """The hand-made minutes really make the cases the parity test names (so a passing test means what it says)."""
    a, b, c, dd, e, f = (rw["made"][k][0] for k in "ABCDEF")
    assert a.side == 1 and a.leverage == 40 and a.exit_reason == "LOCK" and a.lock_roe == pytest.approx(0.13)
    assert b.side == -1 and b.leverage == 30 and b.exit_reason == "LOCK" and b.lock_roe == pytest.approx(0.13)
    assert c.exit_reason == "SL" and c.pnl < 0 and c.stop_price == c.stop_initial and c.exit_time % MIN == MIN - 1
    assert dd.side == -1 and dd.exit_reason == "SL" and dd.exit_time % MIN == 0          # through a gap: filled at the open
    assert e.funding > 0 and e.exit_reason == "LOCK" and f.exit_reason == "LOCK" and f.exit_time - f.entry_time > 12 * H
    da, db = one(rw, "A"), one(rw, "B")
    # A (reference-price fill): its entry bar reached +11 % but the lock came one bar later, from the entry bar's high
    assert da["rules"]["entry_bar"] == "ref" and da["rules"]["entry_bar_from"] == "outcome"
    assert [k["t"] - a.entry_time for k in da["locks"]] == [MIN, 2 * MIN]
    assert [(round(k["trigger"], 4), round(k["lock"], 4)) for k in da["locks"]] == [(0.11, 0.1), (0.14, 0.13)]
    assert da["path"][0][2] > 0.11 and da["path"][0][1] == a.stop_initial
    # the readout pairs the stop in force with the lock in force: the bar that arms 13 % still runs on the 10 % stop
    assert [(r[1], r[6]) for r in da["path"][1:4]] == [(a.stop_initial, None), (da["locks"][0]["price"], da["locks"][0]["lock"]),
                                                       (da["locks"][1]["price"], da["locks"][1]["lock"])]
    # B (filled at the open): the entry bar itself locks; the next bar climbs to 13 % directly
    assert db["rules"]["entry_bar"] == "open" and [k["t"] - b.entry_time for k in db["locks"]] == [0, MIN]
    assert [k["steps"] for k in db["locks"]] == [1, 1] and [k["steps"] for k in da["locks"]] == [1, 1]


def test_funding_is_put_at_the_funding_time_and_said(rw):
    e = rw["made"]["E"][0]
    d = one(rw, "E")
    assert d["rules"]["funding_how"] == "boundary" and d["rules"]["funding_steps"] == [[T0 + 8 * H, e.funding / (e.qty * e.entry_price)]]
    fr = {row[0]: row for row in d["path"]}
    assert fr[T0 + 7 * H + 59 * MIN][3] > fr[T0 + 8 * H][3] - 1          # the path runs on both sides of 08:00
    assert any("펀딩은 한 번 냈어요" in n for n in d["notes_ko"])
    assert R.funding_steps(T0, T0 + 30 * MIN, 0.0, 100.0) == ([], "none")
    steps, how = R.funding_steps(T0 + 7 * H, T0 + 17 * H, 2.0, 100.0)
    assert how == "split" and steps == [(T0 + 8 * H, 0.01), (T0 + 16 * H, 0.02)]
    assert R.funding_steps(T0 + 8 * H + MIN, T0 + 9 * H, 1.0, 100.0) == ([(T0 + 8 * H + 2 * MIN, 0.01)], "guess")


# ================================================================ the answer around it
def test_one_trade_window_entry_exit_and_executors(rw):
    a = rw["made"]["A"][0]
    d = one(rw, "A")
    b = d["bars"]
    e0, x0 = a.entry_time, a.exit_time - a.exit_time % MIN
    assert b["tf"] == "1m" and not b["stepped"] and b["from_ms"] == e0 - 30 * MIN and b["to_ms"] == x0 + 31 * MIN
    assert [r[0] for r in b["rows"]] == list(range(e0 - 30 * MIN, x0 + 31 * MIN, MIN)) and b["missing"] == 0
    tr = d["trade"]
    assert (tr["entry_price"], tr["stop_initial"], tr["leverage"], tr["margin"]) == (a.entry_price, a.stop_initial, 40, a.margin)
    assert tr["roe"] == a.roe and tr["win"] and tr["hold_ms"] == a.exit_time - a.entry_time and tr["reason_ko"] == "잠금 익절"
    assert d["stops"] == [[e0, a.stop_initial, None]] + [[k["at"], k["price"], k["lock"]] for k in d["locks"]]
    assert d["rules"]["ladder_ko"] == "순ROE 11%에서 10% 잠금, 그 뒤 3%씩" and d["final"] is True
    assert len(d["path"]) == (x0 - e0) // MIN + 1 and all(len(r) == 7 for r in d["path"])
    ex = {c["id"]: c for c in d["execs"]}
    by = ex["bybit"]
    assert by["state"] == "matched" and by["pnl"] == 1.07 and by["entry_ts"] == e0 + 15_000 and by["stop_final"] == a.stop_price
    assert by["exit_ref"] == a.exit_price and by["reason"] == "LOCK" and by["reason_ko"] == "잠금 익절" and by["locked"] is True
    assert by["roe"] == pytest.approx(1.07 / by["margin"]) and by["slip_vs_paper"] == pytest.approx(-0.0001, abs=1e-9)
    assert ex["mexc"]["state"] == "missed" and ex["mexc"]["why_kind"] == "entry_check" and "진입 검사" in ex["mexc"]["why_ko"]
    c = one(rw, "C")
    cb = {x["id"]: x for x in c["execs"]}["bybit"]
    assert cb["state"] == "matched" and cb["pnl"] == -5.9 and cb["reason"] == "SL" and not cb["locked"]
    assert {x["id"]: x for x in c["execs"]}["mexc"]["why_kind"] == "halted"         # MEXC halted at T0+8h
    assert not c["trade"]["win"] and c["trade"]["reason_ko"] == "손절" and c["check"]["state"] == "same"


def test_long_trade_is_shown_on_5m_bars_made_of_the_minutes_that_exist(rw, tmp_path):
    f = rw["made"]["F"][0]
    d = one(rw, "F")
    b = d["bars"]
    assert b["tf"] == "5m" and b["stepped"] and b["tf_ms"] == 5 * MIN and "12시간이 넘는 거래라 5분봉으로 보여요" in b["step_ko"]
    rows = R.read_bars(rw["rule"], "BTCUSDT", b["from_ms"], b["to_ms"])["rows"]
    want = R.bucket(rows, 5 * MIN)
    assert b["rows"] == [w[:5] for w in want] and all(r[0] % (5 * MIN) == 0 for r in b["rows"])
    k = b["rows"][10]
    mins = [r for r in rows if k[0] <= r["ts"] < k[0] + 5 * MIN]
    assert k[1:] == [mins[0]["open"], max(m["high"] for m in mins), min(m["low"] for m in mins), mins[-1]["close"]]
    assert d["check"]["state"] == "same" and len(d["locks"]) == 1 and d["locks"][0]["t"] % MIN == 0   # locks: 1-minute times
    assert all(r[0] % (5 * MIN) == 0 for r in d["path"]) and len(d["path"]) <= (f.exit_time - f.entry_time) // (5 * MIN) + 2
    # a 5-minute bar is only what exists: drop minutes, the bar keeps the rest and says how many are partial
    gap = R.bucket([r for r in rows if not (k[0] <= r["ts"] < k[0] + 3 * MIN)], 5 * MIN)
    g = next(x for x in gap if x[0] == k[0])
    assert g[5] == 2 and g[1] == mins[3]["open"]
    assert R.tier_of(12 * H) == ("1m", MIN) and R.tier_of(12 * H + 1) == ("5m", 5 * MIN) and R.tier_of(6 * DAY) == ("1h", H)


def test_record_changed_by_hand_is_shown_as_recorded_and_flagged(rw, tmp_path):
    """기록과 다름: the replay never hides a record that the bars do not give back; both values, the record shown."""
    p = dict(rw["p"])
    paper = str(tmp_path / "live-ac.db")
    shutil.copy(p["paper"], paper)
    p["paper"] = paper
    a = rw["made"]["A"][0]
    conn = sqlite3.connect(paper)
    tid = rw["ids"]["A"]
    d = json.loads(conn.execute("SELECT data FROM trades WHERE id = ?", (tid,)).fetchone()[0])
    d["exit_price"] = a.exit_price + 7.5
    d["exit_time"] = a.exit_time + 2 * MIN
    conn.execute("UPDATE trades SET data = ?, exit_time = ? WHERE id = ?", (json.dumps(d), a.exit_time + 2 * MIN, tid))
    conn.commit()
    conn.close()
    out = R.build_one(p, tid, now_ms=NOW + 2 * DAY, more=rw["more"])
    ck = out["check"]
    assert ck["state"] == "differs"
    items = {i["key"]: i for i in ck["items"]}
    assert set(items) == {"exit_time", "exit_price"}
    assert items["exit_time"]["record"] == a.exit_time + 2 * MIN and items["exit_time"]["rebuilt"] == a.exit_time
    assert items["exit_price"]["record"] == a.exit_price + 7.5 and items["exit_price"]["rebuilt"] == a.exit_price
    assert out["exit"]["record"]["price"] == a.exit_price + 7.5 and out["trade"]["exit_price"] == a.exit_price + 7.5   # shown as recorded
    assert out["exit"]["rebuilt"]["t"] == a.exit_time
    # a different last lock and a stop the bars never reach are flagged too
    conn = sqlite3.connect(paper)
    d["lock_roe"], d["exit_time"], d["exit_price"] = 0.16, a.exit_time, a.exit_price
    conn.execute("UPDATE trades SET data = ?, exit_time = ? WHERE id = ?", (json.dumps(d), a.exit_time, tid))
    conn.commit()
    conn.close()
    out = R.build_one(p, tid, now_ms=NOW + 2 * DAY, more=rw["more"])
    items = {i["key"]: i for i in out["check"]["items"]}
    assert set(items) == {"lock"} and items["lock"]["record"] == 0.16 and items["lock"]["rebuilt"] == pytest.approx(0.13)
    # a rebuilt path that does not end inside the window: the record's exit against nothing
    rows = R.read_bars(rw["rule"], "BTCUSDT", a.entry_time, a.exit_time + MIN)["rows"]
    t = R.read_trade(p["paper"], tid)["trade"]
    lifted = [{**r, **{k: max(r[k], a.stop_price + 1) for k in ("open", "high", "low", "close")}} for r in rows]
    rb = R.rebuild(t, lifted, R.rules_of(t, {"taker_fee": 0.0005, "config": W.CONFIG}), True, [])
    ck = R.compare(t, rb)
    assert rb["exit"] is None and ck["state"] == "differs" and ck["items"][0]["key"] == "exit" and ck["items"][0]["rebuilt"] is None


def test_no_bars_missing_file_unreadable_file(rw, tmp_path):
    t1 = R.read_trade(rw["p"]["paper"], 1)["trade"]
    assert t1["symbol"] == "BTCUSDT" and t1["entry_time"] == T0 + H                     # the world's t1: no bars for it
    d = R.build_one(rw["p"], 1, now_ms=NOW + DAY, more=rw["more"])
    assert d["state"] == "ok" and d["bars"]["state"] == "none" and d["bars"]["rows"] == [] and d["path"] == [] and d["locks"] == []
    assert d["bars"]["reason_ko"] == R.NO_BARS_KO and d["check"]["state"] == "unchecked" and d["exit"]["rebuilt"] is None
    assert d["trade"]["exit_price"] == 101.0 and d["exit"]["record"]["reason_ko"] == "잠금 익절"      # the record still shown
    d = R.build_one(rw["p"], 1, now_ms=NOW + DAY, more={**rw["more"], "rule_db": str(tmp_path / "nope.db")})
    assert d["bars"]["state"] == "missing" and d["bars"]["reason_ko"] == R.RULE_MISSING_KO and d["check"]["state"] == "unchecked"
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"this is not a database at all" * 100)
    d = R.build_one(rw["p"], rw["ids"]["A"], now_ms=NOW + DAY, more={**rw["more"], "rule_db": str(bad)})
    assert d["bars"]["state"] == "error" and d["bars"]["reason_ko"] and d["bars"]["rows"] == [] and d["check"]["state"] == "unchecked"
    assert d["final"] is False
    empty = str(tmp_path / "empty.db")
    sqlite3.connect(empty).execute("CREATE TABLE x (a)").connection.close()
    d = R.build_one(rw["p"], rw["ids"]["A"], now_ms=NOW + DAY, more={**rw["more"], "rule_db": empty})
    assert d["bars"]["state"] == "missing" and d["bars"]["reason_ko"] == R.RULE_NO_TABLE_KO
    assert R.build_one(rw["p"], 99999, now_ms=NOW, more=rw["more"]) is None                  # no such trade
    gone = R.build_one({**rw["p"], "paper": str(tmp_path / "no-paper.db")}, 1, now_ms=NOW, more=rw["more"])
    assert gone["state"] == "missing"


def test_the_list_newest_first_with_the_executors(rw):
    d = R.build_list(rw["p"], now_ms=NOW + DAY)
    assert d["state"] == "ok" and d["n"] == 12 and len(d["rows"]) == 12
    ex = [(r["exit_time"], r["id"]) for r in d["rows"]]
    assert ex == sorted(ex, reverse=True) and d["newest_id"] == d["rows"][0]["id"]
    by = {r["id"]: r for r in d["rows"]}
    a = by[rw["ids"]["A"]]
    assert (a["symbol"], a["side"], a["strategy_id"], a["timeframe"], a["reason_ko"], a["win"]) == ("BTCUSDT", 1, "S2_ST_ROC", "15m", "잠금 익절", True)
    cells = {c["id"]: c for c in a["execs"]}
    assert cells["bybit"]["state"] == "matched" and cells["bybit"]["pnl"] == 1.07 and cells["bybit"]["s"] == "B"
    assert cells["mexc"]["state"] == "missed" and "진입 검사" in cells["mexc"]["why_ko"]
    c = by[rw["ids"]["C"]]
    assert not c["win"] and c["reason_ko"] == "손절" and {x["id"]: x for x in c["execs"]}["bybit"]["pnl"] == -5.9
    page = R.build_list(rw["p"], now_ms=NOW + DAY, offset=10, limit=5)
    assert [r["id"] for r in page["rows"]] == [r["id"] for r in d["rows"][10:]] and page["offset"] == 10 and page["limit"] == 5
    assert R.build_list(rw["p"], now_ms=NOW, limit=10_000)["limit"] == R.LIST_MAX
    missing = R.build_list({**rw["p"], "paper": "/nonexistent/live-ac.db"}, now_ms=NOW)
    assert missing["state"] == "missing" and missing["rows"] == [] and missing["n"] == 0


def test_read_only_the_files_are_unchanged(rw):
    files = [rw["p"]["paper"], rw["p"]["bybit_db"], rw["p"]["mexc_db"], rw["rule"]]
    before = {f: open(f, "rb").read() for f in files}
    R.build_list(rw["p"], now_ms=NOW)
    R.build_one(rw["p"], rw["ids"]["B"], now_ms=NOW + DAY, more=rw["more"])
    assert {f: open(f, "rb").read() for f in files} == before


# ================================================================ the route
def test_route_behind_the_login_list_one_404_and_cache(rw, tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from paperbot.dash.app import create_app, hash_password
    from test_dash import SECRET, _store
    for k, v in W.env_of(rw["p"]).items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("PAPERBOT_LIVE_RULE_DB", rw["rule"])
    dbp = str(tmp_path / "paper3.db")
    _store(dbp).close()
    app = create_app(dbp, hash_password("pw pw pw pw"), SECRET, candles=lambda s, i, n: [])
    reg = R.register(app, SimpleNamespace())
    assert reg["routes"] == ["/api/v4/livebots/replay", "/api/v4/livebots/replay/{trade_id}"]
    c = TestClient(app)
    assert c.get("/api/v4/livebots/replay", follow_redirects=False).status_code in (401, 302, 307)
    assert c.post("/api/login", json={"password": "pw pw pw pw"}).status_code == 200
    d = c.get("/api/v4/livebots/replay?limit=3").json()
    assert d["state"] == "ok" and len(d["rows"]) == 3 and d["n"] == 12
    one_ = c.get(f"/api/v4/livebots/replay/{rw['ids']['A']}").json()
    assert one_["check"]["state"] == "same" and one_["final"] is True
    assert c.get("/api/v4/livebots/replay/99999").status_code == 404
    assert c.get("/api/v4/livebots/replay/abc").status_code == 422
    key = next(iter(R._one))
    assert R._one[key][0] - __import__("time").time() > 60                                   # a finished trade: the long cache


# ================================================================ the screen in node
def _node(body: str, data) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    dom = "file://" + os.path.join(ROOT, "tests", "anasyn_dom.mjs")
    script = (f"const D = await import('{dom}');\nconst X = await import('file://{JS}');\n"
              f"const d = {json.dumps(data)};\n{body}")
    r = subprocess.run([node, "--input-type=module"], input=script, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def _bad(text):
    return [w for w in ("null", "undefined", "NaN", "Infinity", "[object") if w in text]


def test_node_check():
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    r = subprocess.run([node, "--check", JS], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr


@pytest.fixture(scope="module")
def answers(rw):
    from paperbot.dash.app import json_finite
    out = {"list": json_finite(R.build_list(rw["p"], now_ms=NOW + DAY))}
    for k in "ABCDEF":
        out[k] = json_finite(one(rw, k))
    out["none"] = json_finite(R.build_one(rw["p"], 1, now_ms=NOW + DAY, more=rw["more"]))
    return out


def test_pure_functions(answers, rw):
    a = answers["A"]
    out = _node("""const a = d.A;
    const ev = X.eventsOf(a);
    const f0 = X.frameAt(a, a.bars.from_ms), fe = X.frameAt(a, a.trade.entry_time + 30000), fx = X.frameAt(a, a.bars.to_ms - 1);
    console.log(JSON.stringify({href: [X.replayHref(12), X.replayHref(null)], ids: [X.idFromHash("#/livebots/replay?id=34"), X.idFromHash("#/livebots/replay"),
      X.idFromHash("#/livebots/replay?id=abc"), X.idFromHash("#/livebots/replay?x=1&id=7")],
      pk: [X.pctNice(0.11), X.pctNice(0.13), X.pctNice(0.125), X.pctNice(null)],
      labels: a.locks.map((k) => X.lockLabel(k)), kinds: ev.map((e) => e.kind + (e.who ? ":" + e.who : "")), evko: ev.map((e) => e.ko),
      f0: [f0.phase, f0.roe], fe: [fe.phase, fe.stop === a.trade.stop_initial, fe.best > 0.11], fx: [fx.phase, fx.roe === a.trade.roe],
      speeds: X.SPEEDS.map((s) => s.label), res: X.resultOf(a), resC: X.resultOf(d.C), win: X.resultOf(a).tone, loss: X.resultOf(d.C).tone}));""", answers)
    assert out["href"] == ["#/livebots/replay?id=12", "#/livebots/replay"]
    assert out["ids"] == [34, None, None, 7]
    assert out["pk"] == ["11%", "13%", "12.5%", "—"]
    assert out["labels"] == ["+11% 도달 → 10% 잠금", "+14% 도달 → 13% 잠금"]
    assert out["kinds"][:2] == ["entry", "entry:bybit"] and out["kinds"][2:4] == ["lock", "lock"] and "exit" in out["kinds"]
    assert "exit:bybit" in out["kinds"] and not any(k.endswith(":mexc") for k in out["kinds"])
    assert out["f0"] == ["before", None] and out["fe"] == ["in", True, True] and out["fx"] == ["after", True]
    assert out["speeds"] == ["1×", "4×", "16×"]
    assert out["win"] == "up" and out["loss"] == "down" and out["res"]["big"].startswith("+") and out["resC"]["big"].startswith("−")


VIEW = """const calls = [];
const ctx = {params: {arg: "replay", query: d.__q || {}}, api: (p) => { calls.push(p);
    if (d.__fail) return Promise.reject(Object.assign(new Error("x"), {kind: "network", status: 0}));
    const m = p.match(/replay\\/(\\d+)$/); if (m) { const v = d.by[m[1]]; return v ? Promise.resolve(v) : Promise.reject(Object.assign(new Error("nf"), {status: 404})); }
    return Promise.resolve(d.list); },
  every() {}, watch() {}, alive: () => true, href: (n, a, q) => '#/' + n + (a ? '/' + a : ''), track() {}, listen() {}, timeout() {}};
globalThis.location = {hash: d.__hash || "#/livebots/replay"};
const v = X.replayView(ctx);
for (let i = 0; i < 6; i++) await new Promise((r) => setTimeout(r, 0));
const w = D.walk(v.el);
console.log(JSON.stringify({text: w.text.replace(/\\s+/g, " "), classes: w.classes, calls}));"""


def _view(answers, **kw):
    by = {str(answers[k]["id"]): answers[k] for k in "ABCDEF"}
    by[str(answers["none"]["id"])] = answers["none"]
    return _node(VIEW, {"list": answers["list"], "by": by, **kw})


def test_view_newest_trade_picker_chart_timeline_and_result(answers, rw):
    out = _view(answers)
    t, cls = out["text"], out["classes"]
    assert not _bad(t), _bad(t)
    newest = answers["list"]["rows"][0]
    assert out["calls"] == ["/api/v4/livebots/replay", f"/api/v4/livebots/replay/{newest['id']}"]       # the newest by default
    for words in ("거래 다시보기", "재생", "1×", "4×", "16×", "진입", "청산", "순ROE", "기록과 같음", "페이퍼(연습)", "바이비트", "MEXC",
                  "계단 익절: 순ROE 11%에서 10% 잠금, 그 뒤 3%씩"):
        assert words in t, words
    assert any("lbrp-res" in c.split() for c in cls)                                     # reduced motion: no autoplay, the end shown
    pills = [c for c in cls if c.split()[0] == "lbrp-wl"]
    assert pills and all(set(c.split()) & {"win", "loss"} for c in pills)


def test_view_trade_from_the_hash_locks_and_executors(answers, rw):
    a = answers["A"]
    out = _view(answers, __hash=f"#/livebots/replay?id={a['id']}")
    t = out["text"]
    assert out["calls"][1] == f"/api/v4/livebots/replay/{a['id']}" and not _bad(t)
    for words in ("+11% 도달 → 10% 잠금", "+14% 도달 → 13% 잠금", "잠금 익절", "BTC", "롱", "40배", "S2_ST_ROC", "15분",
                  "진입 검사", "+1.07"):
        assert words in t, words
    big = re.findall(r"lbrp-big\b[^\"]*", " ".join(out["classes"]))
    assert big


def test_view_loss_is_the_same_size_and_says_why(answers, rw):
    c = answers["C"]
    win = _view(answers, __hash=f"#/livebots/replay?id={answers['A']['id']}")
    loss = _view(answers, __hash=f"#/livebots/replay?id={c['id']}")
    assert "손절" in loss["text"] and "−5.90" in loss["text"] and not _bad(loss["text"])
    big = lambda o: sorted(x for x in o["classes"] if x.split()[0] == "lbrp-big")       # noqa: E731
    assert [x.replace(" up", "").replace(" down", "") for x in big(win)] == [x.replace(" up", "").replace(" down", "") for x in big(loss)]
    assert any("down" in x.split() for x in big(loss)) and any("up" in x.split() for x in big(win))


def test_view_differs_banner_no_bars_and_failures(answers, rw, tmp_path):
    a = json.loads(json.dumps(answers["A"]))
    a["check"] = {"state": "differs", "why_ko": None, "items": [
        {"key": "exit_time", "ko": "청산 시각", "record": a["trade"]["exit_time"] + 120000, "rebuilt": a["trade"]["exit_time"], "kind": "time"},
        {"key": "exit_price", "ko": "청산 가격", "record": 60300.5, "rebuilt": a["trade"]["exit_price"], "kind": "price"}]}
    answers2 = {**answers, "A": a}
    out = _view(answers2, __hash=f"#/livebots/replay?id={a['id']}")
    t = out["text"]
    assert "기록과 다름" in t and "청산 시각" in t and "기록 " in t and "다시 계산 " in t and "60,300.5" in t and not _bad(t)
    assert any("lbrp-differs" in c.split() for c in out["classes"])
    out = _view(answers, __hash="#/livebots/replay?id=1")
    t = out["text"]
    assert "1분봉 없음" in t and R.NO_BARS_KO in t and "잠금 익절" in t and "지어낸 봉은 그리지 않아요" in t and not _bad(t)
    f = _view(answers, __hash=f"#/livebots/replay?id={answers['F']['id']}")
    assert "12시간이 넘는 거래라 5분봉으로 보여요 (손절·잠금은 1분봉으로 다시 계산)" in f["text"] and not _bad(f["text"])
    missing = json.loads(json.dumps(answers["none"]))
    missing["bars"].update(state="missing", reason_ko=R.RULE_MISSING_KO)
    out = _view({**answers, "none": missing}, __hash="#/livebots/replay?id=1")
    assert "수집 전" in out["text"] and R.RULE_MISSING_KO in out["text"]
    err = json.loads(json.dumps(answers["none"]))
    err["bars"].update(state="error", reason_ko="기록 파일이 망가졌거나 데이터베이스 파일이 아니에요")
    out = _view({**answers, "none": err}, __hash="#/livebots/replay?id=1")
    assert "못 읽음" in out["text"] and "망가졌거나" in out["text"]
    out = _view(answers, __hash="#/livebots/replay?id=424242")
    assert "이 번호의 거래가 없어요" in out["text"]
    out = _view(answers, __fail=True)
    assert "서버에 닿지 못했습니다" in out["text"]
    empty = {**answers["list"], "rows": [], "n": 0, "newest_id": None}
    out = _node(VIEW, {"list": empty, "by": {}})
    assert "아직 닫힌 거래가 없어요" in out["text"] and out["calls"] == ["/api/v4/livebots/replay"]
    gone = {**answers["list"], "state": "missing", "reason_ko": "아직 파일이 없어요", "rows": [], "n": 0}
    out = _node(VIEW, {"list": gone, "by": {}})
    assert "수집 전" in out["text"]


# ================================================================ static checks
def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def test_css_and_js_static():
    src = re.sub(r"/\*.*?\*/", "", _read(CSS), flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", src) and not re.search(r"\b(rgba?|hsla?)\(\s*\d", src), "colour literal: use a token"
    for v in re.findall(r"font-size\s*:\s*([^;}]+)", src):
        assert "var(--t-" in v, v
    for v in re.findall(r"(?<![-\w])font\s*:\s*([^;}]+)", src):
        assert "var(--t-" in v, v
    assert "infinite" not in src and "@media (prefers-reduced-motion: reduce)" in src
    body = re.sub(r"@media[^{]*\{", "", src)
    for sel in re.findall(r"([^{}@;]+)\{", body):
        for part in sel.strip().split(","):
            assert ".lbrp" in part, part
    assert ".lbr-" not in src                                     # livebots-rank.css owns .lbr-*
    js = _read(JS)
    assert '"/api/v4/livebots/replay"' in js and "export function replayView" in js and "export function replayHref" in js
    code = re.sub(r"//[^\n]*", "", js)
    for bad in ("innerHTML", "insertAdjacentHTML", "outerHTML", "DOMParser", "eval(", "toLocaleString", "Intl.NumberFormat", "setInterval(",
                "localStorage."):
        assert bad not in code, bad
    assert "MAX_PX" in js and "devicePixelRatio" in js and "motion.reduced()" in js
    assert re.search(r"position:\s*\"absolute\"", js)                # the canvas is pinned inside its box (no resize feedback)


# ================================================================ the two-part ladder (owners 10/19: 11 % -> 10 %, 15 % -> 12 %, 20 % -> 17 %, ...)
TWO = {"first_lock": 0.10, "trigger_gap": 0.01, "step": 0.05, "next_trigger": 0.15, "next_gap": 0.03}


def test_two_part_ladder_rebuild_locks_12_at_15_then_out_at_the_lock():
    """A long that reaches +12 % net (lock 10 %), then +16 % (lock 12 %, armed at 15 %, not the old form's 13 %), then
    falls back through the 12 % lock: out there."""
    from paperbot.ladder import roe_price
    run = {"taker_fee": 0.0005, "config": {**W.CONFIG, "ladder": TWO}}
    e0 = T0 + 9 * H
    t = {"id": 1, "side": 1, "entry_price": 100.0, "entry_time": e0, "leverage": 10, "stop_initial": 95.0, "liq_price": 90.5,
         "qty": 1.0, "margin": 10.0, "exit_reason": "LOCK", "exit_time": e0 + 3 * MIN, "fees": None, "exit_price": None}
    rules = R.rules_of(t, run)
    assert rules["ladder"] == TWO and rules["spec"].two_part
    rt = rules["round_trip"]
    px = lambda roe: roe_price(1, 100.0, 10, roe, rt)                                             # noqa: E731

    def bar(i, o, hi, lo, c):
        ts = e0 + i * MIN
        return {"ts": ts, "open": o, "high": hi, "low": lo, "close": c, "m_open": o, "m_high": hi, "m_low": lo, "close_time": ts + MIN - 1}

    bars = [bar(0, 100.0, 100.2, 99.9, 100.1),                       # the entry bar: far from any trigger
            bar(1, 100.1, px(0.12), 100.05, px(0.115)),               # best +12 %: lock 10 % (armed at 11 %)
            bar(2, px(0.115), px(0.16), px(0.13), px(0.155)),         # best +16 %: lock 12 % (armed at 15 %)
            bar(3, px(0.15), px(0.151), px(0.10), px(0.105))]         # back through the 12 % lock: out at it
    rb = R.rebuild(t, bars, rules, False, [])
    locks = [(k["lock"], k["trigger"], k["steps"], k["best"]) for k in rb["locks"]]
    assert [round(x[0], 9) for x in locks] == [0.10, 0.12] and [round(x[1], 9) for x in locks] == [0.11, 0.15]
    assert [x[2] for x in locks] == [1, 1] and locks[1][3] == pytest.approx(0.16)
    assert rb["lock"] == pytest.approx(0.12) and rb["stop"] == pytest.approx(px(0.12))
    x = rb["exit"]
    assert x["reason"] == "LOCK" and x["how"] == "touch" and x["price"] == pytest.approx(px(0.12) * (1 - rules["slippage"]))
    assert x["t"] == e0 + 4 * MIN - 1
    # one fast bar from nothing to +16 %: only the 12 % lock is set, two steps climbed (10 % and 12 %)
    rb = R.rebuild(t, [bars[0], bar(1, 100.1, px(0.16), 100.05, px(0.155)), bars[3]], rules, False, [])
    assert [(round(k["lock"], 9), round(k["trigger"], 9), k["steps"]) for k in rb["locks"]] == [(0.12, 0.15, 2)]
    # the next steps: 20 % -> 17 %, 25 % -> 22 %
    assert [round(rules["spec"].lock_for(b), 9) for b in (0.11, 0.149, 0.15, 0.199, 0.20, 0.25, 0.30)] == [0.10, 0.10, 0.12, 0.12, 0.17, 0.22, 0.27]
    assert R.ladder_ko(rules["ladder"]) == "순ROE 11%에서 10% 잠금, 15%에서 12%, 20%에서 17%, 그 뒤 5%마다 (닿은 순ROE - 3%)"
    # the old form: the same answer as before (its ladder, words and lock records)
    old = R.rules_of(t, {"taker_fee": 0.0005, "config": W.CONFIG})
    assert old["ladder"] == {"first_lock": 0.1, "step": 0.03, "trigger_gap": 0.01} and not old["spec"].two_part
    assert R.ladder_ko(old["ladder"]) == "순ROE 11%에서 10% 잠금, 그 뒤 3%씩"
    rb = R.rebuild(t, [bars[0], bar(1, 100.1, px(0.16), 100.05, px(0.155)), bars[3]], old, False, [])
    assert [(k["lock"], k["trigger"], k["steps"]) for k in rb["locks"]] == [(0.1 + 0.03 * 1, (0.1 + 0.03 * 1) + 0.01, 2)]  # +16 %: 13 % at 14 %

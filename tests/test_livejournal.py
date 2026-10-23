"""실거래 › 기록 › 일지 (#/journal; GET /api/v4/livebots/journal, dash/more/livejournal.py; screens/livebots-journal.js,
livebots-journal.css).

On the 검토 tab's world (tests/test_livereview.py: a paper database written by the trend bot's own code, three trades
after their pullbacks with 감독 청산 (JUDGE, TIME) and a first lock, a signal the trend judge stopped, one the entry
checks stopped, one whose pullback never came, the coin-flip twin), a 바이비트 executor written by the executor's own
store (its fills against those trades, a skipped follow, a lock step, a halt, a start and a SIGTERM), and the 추세 차트
tab's synthetic Binance bars (tests/test_livetrendchart.py: no network):
- the answer: every kind in one order (newest first, the same minute in reading order), the signals in the bot's words
  (추세 판단에 걸림 · 점검 탈락 · 되돌림 안 옴 · 되돌림 옴 → 진입), the trades (진입 with the pullback and the judgment,
  감독 청산 with the bot's why, the twin flagged), the judgment changes (votes, ADX), the executor's rows (the gap to the
  paper's price, 신호등 빨강, 멈춤, the lock step), the starts; the count line; the links;
- the spans (24 h · 3 days · 7 days; judgment changes only for the last 72 hours, said so), the cap (signals and
  judgment changes cut first, oldest first, said so; trades / executors / safety kept);
- honest states: no file / garbage = missing / error with the executors' rows still there, another bot = off (trades,
  executors, the morning checks and the watcher's alarms; no signal, no judgment, no fetch), no judgment yet = missing;
  a count of what was not read is None;
- the pure parts: the signal outcomes (wait words, 한 포지션이라 못 탐, a pause that began during the wait, the pauses and
  the chase block), the judgment changes (못 읽음 skipped, 힘 약함 / 끝물 / 유지 확인 중), the cap;
- the view in node (the tiny DOM): the count line, the day lines, the rows and their links, the twin switch, the notes,
  the states; the pure helpers; static checks (node --check, tokens only, the ljr- prefix is this screen's alone) and the
  wiring (tab, menu, find, css, module, inventory, docs); the route on the live app."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import livebots_world as W  # noqa: E402
import test_livereview as RV  # noqa: E402
import test_livetrendchart as TCT  # noqa: E402
import test_trendbot as T  # noqa: E402
from paperbot import combo as C  # noqa: E402
from paperbot.dash.more import livebots as L  # noqa: E402
from paperbot.dash.more import livejournal as J  # noqa: E402
from paperbot.dash.more import livetrendchart as TC  # noqa: E402
from paperbot.executor import ExecStore  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
SCREENS = os.path.join(V4, "screens")
JS = os.path.join(SCREENS, "livebots-journal.js")
CSS = os.path.join(SCREENS, "livebots-journal.css")
MIN, HOUR, DAY = T.MIN, T.HOUR, 86_400_000
ACCOUNT = C.ACCOUNT


def _read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------- the world
def _bybit(folder, w, now):
    """바이비트 written by the executor's own store: the BTC long followed (filled 0.03 % worse than the paper, closed with
    the paper's 감독 청산), the ETH long not followed (신호등 빨강), a lock step, a halt, a start and a SIGTERM."""
    trades = {t["symbol"]: t for t in w.trades()}
    btc, eth = trades["BTCUSDT"], trades["ETHUSDT"]
    db = os.path.join(folder, "executor-bybit-live.db")
    st = ExecStore(db, lock=False)
    st.put_state("meta", T.T0, {"mode": "mainnet", "account": ACCOUNT, "since": T.T0, "exchange": "bybit", "live_since": T.T0})
    key = f"{ACCOUNT}|BTCUSDT|{btc['entry_time']}"
    live_in = round(btc["entry_price"] * 1.0003, 2)
    t = {"key": key, "symbol": "BTCUSDT", "side": 1, "qty": 0.002, "leverage": 40, "entry_ts": btc["entry_time"] + 15_000,
         "entry_price": live_in, "stop_initial": btc["entry_price"] * 0.99, "mode": "mainnet", "entry_time": btc["entry_time"],
         "paper_entry": btc["entry_price"], "exit_ref": btc["exit_price"]}
    st.trade_open(t)
    st.trade_close(key, btc["exit_time"] + 20_000, "paper 청산 → 거래소 포지션 닫기", -0.42, t, "wallet")
    st.event(T.T0 + 5_000, "INFO", "start", "시작: paper 계좌 COMBO@mix 따라 하기", {"paper_db": w.cfg.db})
    st.event(btc["entry_time"] + 15_000, "INFO", "entry", "진입 BTCUSDT 롱", {"key": key})
    st.event(btc["entry_time"] + 20 * MIN, "INFO", "stop", "BTCUSDT 잠금 올리기: 손절 59000 → 60000 (거래소 확인)", {})
    st.event(eth["entry_time"] + 10_000, "WARN", "light_red", "신호등 빨강: paper 최근 20번 중 15번 이김(75%, 기준 85%)",
             {"key": f"{ACCOUNT}|ETHUSDT|{eth['entry_time']}"})
    st.halt_log(now - 30 * MIN, "halt", "연속 손실 3번", planned=True)
    st.event(now - 30 * MIN, "CRITICAL", "halt", "거래를 멈춥니다(사람이 풀 때까지): 연속 손실 3번")
    st.event(now - 10 * MIN, "INFO", "sigterm", "끄라는 신호(SIGTERM)를 받아 하던 반복을 마치고 멈춥니다.")
    st.put_state("bot", now - 5_000, {"trade": None, "done": [], "mode": "mainnet", "account": ACCOUNT,
                                      "risk": {"halted": True, "halt_reason": "연속 손실 3번", "consecutive_losses": 3, "last_equity": 99.0}})
    st.commit()
    st.close()
    cfg = W.config(os.path.join(folder, "executor.json"), db, w.cfg.db, "bybit", 0.85, os.path.join(folder, "STOP"))
    return db, cfg


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    folder = tmp_path_factory.mktemp("journal")
    w, now = RV._world(folder)
    db, cfg = _bybit(str(folder), w, now)
    p = {"paper": w.cfg.db, "paper2": str(folder / "none2.db"), "bybit_db": db, "bybit_config": cfg,
         "mexc_db": str(folder / "none-mexc.db"), "mexc_config": str(folder / "none-mexc.json"),
         "flipster_db": str(folder / "none-flipster.db"), "flipster_config": str(folder / "none-flipster.json")}
    clock = {"t": now}
    fetch = TCT.Fetch(clock)
    b = TC.Bars(fetch, lambda: clock["t"])
    more = {"check_db": str(folder / "none-check.db"), "rule_db": w.cfg.paper_db}
    J.build(p, 24, now, more=more, b=b)                     # the first answers fetch the bars (six a time)
    J.build(p, 24, now, more=more, b=b)
    return {"w": w, "now": now, "p": p, "more": more, "b": b, "fetch": fetch, "clock": clock}


def _build(world, hours=24, **kw):
    return J.build(world["p"], hours, world["now"], more=world["more"], b=world["b"], **kw)


def _one(events, **want):
    got = [e for e in events if all(e.get(k) == v for k, v in want.items())]
    assert len(got) == 1, (want, got)
    return got[0]


# ---------------------------------------------------------------- the answer
def test_the_answer(world):
    w, now = world["w"], world["now"]
    d = _build(world)
    assert d["state"] == "ok" and d["reason_ko"] is None and d["hours"] == 24 and d["t0"] == now - 24 * HOUR
    assert d["name"] == "추세판단 봇" and d["since"] == T.T0 and d["capped"] is None
    ev = d["events"]
    # one order: newest first; the same minute in reading order (safety, executors, trades, signals, judgments)
    keys = [(-e["t"], J.ORDER[e["kind"]]) for e in ev]
    assert keys == sorted(keys) and len({e["id"] for e in ev}) == len(ev)
    assert {e["kind"] for e in ev} == {"trend", "signal", "trade", "exec", "safety"} and all(e["t"] >= d["t0"] for e in ev)
    for e in ev:
        assert e["text"] and "None" not in e["text"] and "nan" not in e["text"].lower(), e
    # the signals, in the bot's own words, each with what became of it
    sig = [e for e in ev if e["kind"] == "signal"]
    sol = _one(sig, symbol="SOLUSDT")
    assert (sol["sub"], sol["text"]) == ("judge", "SOL 숏 신호 · 추세 판단에 걸림") and sol["detail"].startswith("1시간 추세가 상승이라 숏 안 함")
    doge = _one(sig, symbol="DOGEUSDT")
    assert (doge["sub"], doge["text"]) == ("check", "DOGE 롱 신호 · 점검 탈락") and doge["detail"].startswith("30분 RSI 71 과열")
    ltc = _one(sig, symbol="LTCUSDT")
    assert (ltc["sub"], ltc["text"]) == ("nopull", "LTC 롱 신호 · 되돌림 안 옴 · 진입 없음") and ltc["detail"].startswith("되돌림 안 옴(")
    bch = _one(sig, symbol="BCHUSDT")
    entry_bch = next(t for t in w.trades() if t["symbol"] == "BCHUSDT")["entry_time"]
    assert (bch["sub"], bch["tone"], bch["entry_t"]) == ("entered", "good", entry_bch)
    assert bch["text"] == f"BCH 롱 신호 · 되돌림 옴 → {J.kst(entry_bch)} 진입" and bch["level"] is not None
    assert bch["strategy"] == "N08_ICHI_WR" and bch["tf"] == "30m" and bch["link"] == {"tab": "signals", "q": None}
    assert len(sig) == 6                                     # the pulled entries' own rows are counted with their signals
    # the paper trades: entries (after the pullback, on the judgment), exits in the Telegram words, the twin flagged
    tr = [e for e in ev if e["kind"] == "trade" and not e["twin"]]
    btc = next(t for t in w.trades() if t["symbol"] == "BTCUSDT")
    e_in = _one(tr, symbol="BTCUSDT", sub="entry")
    assert e_in["text"] == f"BTC 롱 진입 · 40배 @ {J.price_ko(btc['entry_price'])}" and e_in["t"] == btc["entry_time"]
    assert e_in["detail"].startswith("되돌림 진입 (") and "1시간 상승" in e_in["detail"]
    assert e_in["link"] == {"tab": "replay", "q": {"id": e_in["trade_id"]}}
    sup = _one(tr, symbol="BTCUSDT", sub="sup")
    assert sup["text"].startswith("BTC 롱 감독 청산(추세 뒤집힘) · 순ROE −") and sup["detail"].startswith("1시간 판단이 하락")
    assert sup["reason"] == "JUDGE" and sup["tone"] == "down" and sup["hold_ms"] == btc["exit_time"] - btc["entry_time"]
    assert _one(tr, symbol="ETHUSDT", sub="sup")["text"].startswith("ETH 롱 감독 청산(시간 정리)")
    lock = _one(tr, symbol="BCHUSDT", sub="exit")
    assert lock["text"].startswith("BCH 롱 계단 익절 · 순ROE +") and "잠금 +" in lock["detail"] and lock["tone"] == "up"
    twins = [e for e in ev if e.get("twin")]
    assert twins and all(e["kind"] == "trade" and e["acct"] == "flip" and e["link"] is None and e["text"].startswith("동전 쌍둥이 ")
                         for e in twins)
    assert all("되돌림" not in (e["detail"] or "") for e in twins)       # the twin's side is a coin's: not its pullback
    # the judgment changes: the 추세 차트 tab's recomputation, its link
    ch = [e for e in ev if e["kind"] == "trend"]
    assert ch and all(e["sub"] == "change" and e["frm"] != e["to"] and e["link"] == {"tab": "tchart", "q": {"sym": e["symbol"]}} for e in ch)
    assert all(re.match(r"^\w+ (1시간|4시간|일봉) 판단이 (상승|하락|보류)에서 (상승으로|하락으로|보류로) 바뀌었어요$", e["text"]) for e in ch)
    assert all(re.match(r"^상승 \d·하락 \d·중립 \d · ADX \d+ (오름|내림)", e["detail"]) and "진입이 이 판단을 봐요" in e["detail"] for e in ch)
    # 6 coins x (1h, 4h and, since 10/22, the daily bar the 4h entries read)
    assert d["judge"] == {"state": "ok", "covers_h": 72, "from": d["t0"], "read": 18, "of": 18, "pending": False, "note_ko": None,
                          "errors": [], "stale": False}
    # the executor: its fills against the paper's price, the follow it skipped, its lock step, its halt, its start
    ex = [e for e in ev if e["kind"] == "exec"]
    fin = _one(ex, sub="fill_in")
    assert fin["text"] == f"바이비트 BTC 롱 진입 체결 @ {J.price_ko(round(btc['entry_price'] * 1.0003, 2))}"
    assert fin["detail"].startswith("페이퍼 진입가보다 0.03") and "불리, 순ROE −1.2%p" in fin["detail"]
    assert fin["gap"] == pytest.approx(-0.0003, abs=2e-6) and fin["real"] is True and fin["link"] == {"tab": "trades", "q": {"acct": "bybit"}}
    fout = _one(ex, sub="fill_out")
    assert fout["text"] == "바이비트 BTC 롱 청산 · 감독 청산(추세 뒤집힘) · −$0.42" and fout["detail"].startswith("페이퍼 청산가와 같아요")
    assert "지갑 변화로 어림" in fout["detail"] and fout["tone"] == "down"
    skip = _one(ex, sub="skip")
    assert skip["text"] == "바이비트 · ETH 롱 페이퍼 진입을 안 따라갔어요" and skip["detail"].startswith("신호등 빨강이라 따라가지 않았어요 · 신호등 빨강:")
    assert skip["link"] == {"tab": "cost", "q": None}
    assert _one(ex, sub="lock")["text"] == "바이비트 BTC 손절 옮김 (잠금 단계)"
    halt = _one(ex, sub="halt")
    assert halt["text"] == "바이비트 멈춤 · 사람이 풀 때까지 새 진입 없음" and halt["tone"] == "bad" and halt["link"] == {"tab": "safety", "q": None}
    sf = [e for e in ev if e["kind"] == "safety"]
    assert {e["sub"] for e in sf} == {"start", "trend_start", "stop"}
    assert _one(sf, sub="trend_start")["text"] == "추세판단 봇이 처음 켜졌어요 · 규칙 고정 2주 시작"
    assert {e["text"] for e in sf if e["sub"] == "start"} == {"페이퍼 봇이 켜졌어요 (추세판단 봇)", "바이비트 실행기가 켜졌어요"}
    assert _one(sf, sub="stop")["text"] == "바이비트 실행기가 꺼졌어요 (끄라는 신호)"
    # the count line (the twin left out); what is not there says so
    c = d["counts"]
    paper = [t for t in w.trades()]
    assert (c["signals"], c["passed"], c["waits"], c["touched"], c["waiting"]) == (6, 4, 4, 3, 0)
    assert (c["entered"], c["closed"], c["changes"]) == (3, 3, len(ch)) and c["pnl"] == pytest.approx(sum(t["pnl"] for t in paper))
    srcs = d["sources"]
    assert srcs["paper"]["state"] == "ok" and srcs["checks"]["state"] == "missing"
    assert [(x["id"], x["state"]) for x in srcs["execs"]] == [("bybit", "ok"), ("mexc", "missing")]
    assert d["coins"] == list(J.COINS) and [k["id"] for k in d["kinds"]] == ["trend", "signal", "trade", "exec", "safety"]
    assert json.loads(json.dumps(d)) == d


def test_the_spans_and_how_far_the_judgments_go(world):
    now = world["now"]
    d1, d3, d7 = _build(world, 24), _build(world, 72), _build(world, 168)
    assert (d1["t0"], d3["t0"], d7["t0"]) == (now - 24 * HOUR, now - 72 * HOUR, now - 168 * HOUR)
    assert d1["judge"]["from"] == now - 24 * HOUR and d3["judge"]["from"] == d7["judge"]["from"] == now - 72 * HOUR
    assert d1["judge"]["note_ko"] is None and d3["judge"]["note_ko"] is None and d7["judge"]["note_ko"] == "판단 기록은 최근 72시간만"
    ch = lambda d: [e for e in d["events"] if e["kind"] == "trend"]      # noqa: E731
    assert len(ch(d3)) >= len(ch(d1)) and [e["id"] for e in ch(d3)] == [e["id"] for e in ch(d7)]
    assert all(e["t"] >= now - 72 * HOUR for e in ch(d7))
    # a later hour: the first trades fall out of the last 24 hours (their exits too); the counts follow
    later = world["now"] + 20 * HOUR
    world["clock"]["t"] = later
    try:
        for _ in range(3):
            d = J.build(world["p"], 24, later, more=world["more"], b=world["b"])
    finally:
        world["clock"]["t"] = world["now"]
    t0 = later - 24 * HOUR
    assert all(e["t"] >= t0 for e in d["events"])
    ins = [e for e in d["events"] if e["kind"] == "trade" and e["sub"] == "entry" and not e["twin"]]
    assert {e["symbol"] for e in ins} == {"BCHUSDT"} and d["counts"]["entered"] == 1
    # an unknown span is the first one (the route refuses it before)
    assert _build(world, 5)["hours"] == 24


def test_the_cap_cuts_signals_and_judgments_first(world, monkeypatch):
    full = _build(world)
    hi = [e for e in full["events"] if e["kind"] not in J.LOW]
    monkeypatch.setattr(J, "MAX_EVENTS", len(hi) + 3)
    d = _build(world)
    cp = d["capped"]
    assert len(d["events"]) == len(hi) + 3 and cp["total"] == len(full["events"]) and cp["cut"] == len(full["events"]) - len(hi) - 3
    assert [e["id"] for e in d["events"] if e["kind"] not in J.LOW] == [e["id"] for e in hi]          # all of them, in order
    low = [e for e in full["events"] if e["kind"] in J.LOW]
    assert [e["id"] for e in d["events"] if e["kind"] in J.LOW] == [e["id"] for e in low[:3]]       # the newest three
    assert cp["low_from"] == low[2]["t"] and cp["hi_from"] is None and cp["kinds"] == ["signal", "trend"]
    assert d["counts"] == full["counts"]                     # the counts are the whole span's
    # fewer rows allowed than the rest: no signal or judgment left, the oldest of the rest go too
    kept, cp = J.cap(full["events"], 4)
    assert [e["id"] for e in kept] == [e["id"] for e in hi[:4]] and cp["low_from"] is None and cp["hi_from"] == hi[3]["t"]
    assert J.cap(full["events"], 10_000) == (full["events"], None)


# ---------------------------------------------------------------- honest states
def test_another_bot_shows_trades_executors_and_checks_but_no_signal_or_judgment(tmp_path):
    p = W.build_world(str(tmp_path))
    m = W.live_checks(p, str(tmp_path))
    clock = {"t": W.NOW}
    fetch = TCT.Fetch(clock)
    b = TC.Bars(fetch, lambda: clock["t"])
    d = J.build(p, 24, W.NOW, more={"check_db": m["check_db"], "rule_db": "/nonexistent/r"}, b=b)
    assert d["state"] == "off" and d["reason_ko"] == J.OFF_KO and fetch.calls == [] and b.k.rows == {}
    c = d["counts"]
    assert all(c[k] is None for k in ("signals", "passed", "waits", "touched", "waiting", "changes"))
    assert (c["entered"], c["closed"]) == (7, 6) and c["pnl"] == pytest.approx(sum(x[4] for x in W.PAPER))
    assert d["judge"]["state"] == "off" and "추세판단 봇이 아니라" in d["judge"]["reason_ko"]
    kinds = {e["kind"] for e in d["events"]}
    assert kinds == {"trade", "exec", "safety"}
    subs = {(e["kind"], e["sub"]) for e in d["events"]}
    assert {("exec", "fill_in"), ("exec", "fill_out"), ("exec", "skip"), ("exec", "halt"), ("exec", "halt_cleared"), ("exec", "warn"),
            ("safety", "morning"), ("safety", "alarm"), ("safety", "start")} <= subs
    late = _one(d["events"], sub="skip", acct="mexc", symbol="LTCUSDT")
    assert late["text"] == "MEXC · LTC 숏 페이퍼 진입을 안 따라갔어요" and late["detail"].startswith("페이퍼 진입을 늦게 봐서 건너뛰었어요")
    gate = _one(d["events"], sub="skip", acct="mexc", symbol="SOLUSDT")
    assert gate["detail"].startswith("진입 검사에서 막혔어요")
    opened = _one(d["events"], kind="exec", sub="fill_in", acct="bybit", symbol="BTCUSDT", open=True)
    assert opened["open"] is True and opened["detail"].startswith("페이퍼 진입가보다 0.016% 불리, 순ROE −0.6%p") and opened["link"]["tab"] == "pos"
    alarm = next(e for e in d["events"] if e["sub"] == "alarm" and e["state"] == "cleared")
    assert alarm["text"].startswith("감시 알람 · ") and "에 풀림" in alarm["detail"]
    am = [e for e in d["events"] if e["sub"] == "morning"]
    assert any(e["text"] == "아침 점검 · 확인할 것 2개" and e["tone"] == "bad" for e in am)
    # the paper's open position is an entry of the span; the twin's trades are there, flagged
    assert _one(d["events"], kind="trade", sub="entry", symbol="BTCUSDT", twin=False, open=True)["link"] == {"tab": "pos", "q": None}
    assert any(e.get("twin") for e in d["events"])


def test_missing_garbage_and_no_judgment_yet(tmp_path):
    p = W.build_world(str(tmp_path))
    clock = {"t": W.NOW}
    fetch = TCT.Fetch(clock)
    b = TC.Bars(fetch, lambda: clock["t"])
    more = {"check_db": str(tmp_path / "none.db"), "rule_db": "/nonexistent/r"}
    gone = dict(p, paper=str(tmp_path / "gone.db"))
    d = J.build(gone, 24, W.NOW, more=more, b=b)
    assert d["state"] == "missing" and d["reason_ko"] == L.MISSING_KO and d["sources"]["paper"]["state"] == "missing"
    assert all(v is None for v in d["counts"].values())
    assert {e["kind"] for e in d["events"]} == {"exec", "safety"}           # the executors' own rows still show
    assert d["sources"]["checks"]["state"] == "missing"
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"this is not a database" * 100)
    d = J.build(dict(p, paper=str(bad)), 24, W.NOW, more=more, b=b)
    assert d["state"] == "error" and d["reason_ko"] == "기록 파일이 망가졌거나 데이터베이스 파일이 아니에요" and d["reason"]
    assert all(v is None for v in d["counts"].values())
    # the trend bot before its first judgment: missing with the reason, no judgment and no fetch
    s = Store3(str(tmp_path / "fresh.db"))
    s.put_state("combo_run", W.NOW - HOUR, {"config": {"name": "추세판단 봇", "trend": {}}})
    s.commit()
    s.close()
    d = J.build(dict(p, paper=str(tmp_path / "fresh.db")), 24, W.NOW, more=more, b=b)
    assert d["state"] == "missing" and "첫 판단" in d["reason_ko"] and d["judge"]["state"] == "missing" and d["counts"]["changes"] is None
    assert fetch.calls == [] and d["counts"]["entered"] == 0 and d["counts"]["signals"] == 0      # (read: none yet)
    assert any(e["sub"] == "trend_start" for e in d["events"])


# ---------------------------------------------------------------- the pure parts
def _row(rid, bc, tf, member, sym, side, status, why, **data):
    return (rid, bc, tf, member, sym, side, status, json.dumps({"why": why, "strategy": member.split("@")[0], **data}))


def test_signal_outcomes_in_the_bots_words():
    t = W.T0 + 2 * HOUR                                       # a bar close of 30m and 1h (11:00 KST)
    now = t + 5 * MIN
    rows = [
        _row(1, t, "30m", "N08_ICHI_WR@30m", "BTCUSDT", 1, "WAITING", "되돌림 기다림: 59955까지(0.25 ATR, 11:29까지) · 1시간 상승",
             trend={"level": 59955.0}),
        _row(2, t, "30m", "F3_BOS@30m", "ETHUSDT", 1, "BROKE", "되돌림 확인: 2496.25 닿음 → 다음 분에 진입"),
        _row(3, t + 3 * MIN, "30m", "F3_BOS@30m", "ETHUSDT", 1, "SUBMITTED", "되돌림 확인"),
        _row(4, t, "30m", "N08_ICHI_WR@30m", "SOLUSDT", -1, "BROKE", "되돌림 확인: 150.2 닿음 → 다음 분에 진입"),
        _row(5, t + 4 * MIN, "30m", "N08_ICHI_WR@30m", "SOLUSDT", -1, "FILTERED", "주말(한국 시간 토·일) 진입 안 함"),
        _row(6, t, "30m", "N05_PSAR_POC@30m", "BCHUSDT", 1, "BROKE", "되돌림 확인: 399.7 닿음 → 다음 분에 진입"),
        _row(7, t + 2 * MIN, "30m", "N05_PSAR_POC@30m", "BCHUSDT", 1, "SUBMITTED", "되돌림 확인"),
        _row(8, t, "1h", "S3_CMO_SANDWICH@1h", "DOGEUSDT", 1, "FILTERED", "추격 진입 막기: 24시간 고점 쪽 10% 안"),
        _row(9, t, "1h", "S3_CMO_SANDWICH@1h", "LTCUSDT", -1, "FILTERED", "주말(한국 시간 토·일) 진입 안 함"),
        _row(10, t, "1h", "F9_FVG@1h", "LTCUSDT", 1, "FILTERED", "경제 발표 앞뒤 30분: 소비자물가(CPI)"),
        _row(11, t, "1h", "F9_IFVG@1h", "LTCUSDT", 1, "FILTERED", "나스닥 개장 뒤 30분 진입 안 함"),
        _row(12, t, "30m", "F15_ORB@30m", "ETHUSDT", -1, "BROKE", "되돌림 확인: 2500 닿음 → 다음 분에 진입"),
    ]
    outs = {(t + 3 * MIN, "30m", "F3_BOS@30m", "ETHUSDT"): ("SKIPPED", "in position", t + 3 * MIN),
            (t + 2 * MIN, "30m", "N05_PSAR_POC@30m", "BCHUSDT"): ("ENTERED", "ok", t + 2 * MIN)}
    ev, c = J.signal_events(rows, outs, now)
    by = {e["id"]: e for e in ev}
    assert len(ev) == 9 and "s:3" not in by and "s:5" not in by and "s:7" not in by
    assert (by["s:1"]["sub"], by["s:1"]["text"]) == ("wait", "BTC 롱 신호 · 점검 통과 · 되돌림 기다리는 중")
    assert by["s:1"]["detail"] == "59,955까지 내려오면 진입 · 11:29까지 안 오면 진입 없음" and by["s:1"]["until"] == t + 29 * MIN
    assert (by["s:2"]["sub"], by["s:2"]["text"]) == ("one", "ETH 롱 신호 · 되돌림은 왔지만 한 포지션이라 못 탐")
    assert by["s:4"]["text"] == "SOL 숏 신호 · 되돌림은 왔지만 진입 안 함: 주말이라 막힘" and by["s:4"]["sub"] == "skip"
    assert by["s:6"]["text"] == "BCH 롱 신호 · 되돌림 옴 → 11:02 진입" and by["s:6"]["tone"] == "good"
    assert by["s:8"]["text"] == "DOGE 롱 신호 · 추격 막기에 걸림" and by["s:8"]["sub"] == "blocked"
    assert [by[f"s:{i}"]["text"].split(" · ")[1] for i in (9, 10, 11)] == ["주말이라 막힘", "경제 발표 앞뒤라 막힘", "나스닥 개장 뒤라 막힘"]
    assert by["s:12"]["text"] == "ETH 숏 신호 · 되돌림 옴 → 진입 확인 중" and by["s:12"]["sub"] == "wait"
    assert c == {"signals": 9, "passed": 5, "waits": 5, "touched": 4, "waiting": 1}
    # a wait whose deadline passed without the bot's restatement (the bot down): never called a live wait
    ev, c = J.signal_events(rows[:1], {}, t + 40 * MIN)
    assert ev[0]["text"] == "BTC 롱 신호 · 되돌림 기다림 · 결과 기록 전" and c["waiting"] == 0
    # a short's wait comes up to its level
    ev, _c = J.signal_events([_row(1, t, "30m", "N08_ICHI_WR@30m", "BTCUSDT", -1, "WAITING", "되돌림 기다림: …",
                                   trend={"level": 60100.0})], {}, now)
    assert ev[0]["detail"].startswith("60,100까지 올라오면 진입")


def test_judgment_changes():
    t = W.T0
    cell = lambda dt, kind, d, raw, up, dn, adx=25.0, prev=24.0: {"t": t + dt, "kind": kind, "dir": d, "raw": raw, "up": up, "dn": dn,    # noqa: E731
                                                                  "votes": [], "adx": adx, "adx_prev": prev}
    cells = [cell(-2 * HOUR, "up", 1, 1, 3, 0), {"t": t - HOUR, "kind": "na", "why": "봉이 모자람"},
             cell(0, "hold up", 0, 1, 3, 1, 26.0, 27.0), cell(HOUR, "down weak", -1, -1, 0, 3, 18.0, 17.0),
             cell(2 * HOUR, "down tired", -1, -1, 0, 4, 45.0, 47.0), cell(3 * HOUR, "up", 1, 1, 4, 0, 30.0, 28.0)]
    ev = J.changes_of("ETHUSDT", "1h", cells, t)
    assert [e["t"] for e in ev] == [t, t + HOUR, t + 3 * HOUR]
    assert ev[0]["text"] == "ETH 1시간 판단이 상승에서 보류로 바뀌었어요"
    assert ev[0]["detail"] == "상승 3·하락 1·중립 0 · ADX 26 내림 · 상승 유지 확인 중 · 30분 진입이 이 판단을 봐요"
    assert ev[1]["text"] == "ETH 1시간 판단이 보류에서 하락으로 바뀌었어요" and "힘 약함(ADX 20 미만)이라 진입은 안 받아요" in ev[1]["detail"]
    assert ev[1]["tone"] == "down" and ev[1]["weak"] and not ev[1]["tired"]
    assert ev[2]["text"] == "ETH 1시간 판단이 하락에서 상승으로 바뀌었어요" and ev[2]["tone"] == "up" and ev[2]["frm"] == -1
    # from later on: the change before is the baseline only; 4h cells say who reads them
    assert [e["t"] for e in J.changes_of("ETHUSDT", "1h", cells, t + 30 * MIN)] == [t + HOUR, t + 3 * HOUR]
    four = J.changes_of("BTCUSDT", "4h", [cell(0, "hold", 0, 0, 1, 1), cell(4 * HOUR, "down", -1, -1, 0, 3)], t)
    assert four[0]["detail"].endswith("1시간 진입이 이 판단을 봐요") and four[0]["id"] == f"j:BTCUSDT:4h:{t + 4 * HOUR}"
    assert J.changes_of("BTCUSDT", "1h", [{"t": t, "kind": "na"}], t) == []


def test_small_words():
    assert [J.price_ko(x) for x in (62010.0, 2496.25, 0.185421, None)] == ["62,010", "2,496.25", "0.185421", "—"]
    assert [J.pct_ko(x) for x in (0.123, -0.05, 0.0, None)] == ["+12.3%", "−5.0%", "0.0%", "—"]
    assert [J.money_ko(x) for x in (45.2, -0.42, None)] == ["+$45.20", "−$0.42", "—"]
    assert J._gap_words(None, 40, "진입") == "페이퍼 진입가와 견줄 수 없어요 (짝 거래 없음)"
    assert J._gap_words(0.0005, 30, "청산") == "페이퍼 청산가보다 0.050% 유리, 순ROE +1.5%p"
    assert J._gap_words(1e-7, 30, "진입") == "페이퍼 진입가와 같아요"
    assert J.kst(W.T0) == "09:00" and J.kst_dt(W.T0) == "10/19 09:00"


# ---------------------------------------------------------------- the view in node
def _node(body: str, data) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    dom = "file://" + os.path.join(ROOT, "tests", "anasyn_dom.mjs")
    now = (data or {}).get("now_ms") or W.NOW
    script = (f"Date.now = () => {int(now)};\nconst D = await import('{dom}');\nconst X = await import('file://{JS}');\n"
              f"const d = {json.dumps(data)};\n"
              "const tick = async () => { for (let i = 0; i < 3; i++) await new Promise((r) => setTimeout(r, 0)); };\n" + body)
    r = subprocess.run([node, "--input-type=module"], input=script, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


VIEW = """const every = [], asked = [];
const ctx = {api: (u) => { asked.push(u); return Promise.resolve(d); }, every(ms, fn) { every.push(ms); }, watch() {}, alive: () => true,
  href: (n, a, q) => '#/' + a + (q ? '?' + new URLSearchParams(q).toString() : '')};
const v = X.journalView(ctx);
await tick();
const w = D.walk(v.el);
const links = [];
const visit = (n) => { if (!n || !n.childNodes) return; if (n.tagName === 'A') links.push(n.attributes.href); n.childNodes.forEach(visit); };
visit(v.el);
const ev = d.events || [];
console.log(JSON.stringify({text: w.text.replace(/\\s+/g, " "), classes: w.classes, every, asked, links,
  all: X.filterEvents(ev, {kind: "all", coin: "", twin: false}).length, withTwin: X.filterEvents(ev, {kind: "all", coin: "", twin: true}).length,
  btcTrades: X.filterEvents(ev, {kind: "trade", coin: "BTCUSDT", twin: false}).map((e) => e.id),
  counts: X.kindCounts(ev, {coin: "", twin: false}), line: X.countLine(d), notes: X.notesOf(d), span: X.spanWords(d),
  days: [X.dayLabel(d.now_ms || 0, d.now_ms || 0), X.dayLabel((d.now_ms || 0) - 86400000, d.now_ms || 0), X.dayLabel(1792368000000, 1792540800000)],
  link: X.linkOf({link: {tab: "replay", q: {id: 3}}}, (n, a, q) => '#/' + a + '?id=' + q.id), nolink: X.linkOf({link: null}),
  tags: [X.moneyTag({kind: "trade"}), X.moneyTag({kind: "trade", twin: true}), X.moneyTag({kind: "exec", acct: "bybit", real: true}), X.moneyTag({kind: "signal"})],
  signed: [X.signed(12.3), X.signed(-4), X.signed(0), X.signed(null)]}));"""


@pytest.fixture(scope="module")
def answer(world):
    return json.loads(json.dumps(_build(world)))


def test_the_view(answer):
    out = _node(VIEW, answer)
    t, cls = out["text"], out["classes"]
    for bad in ("null", "undefined", "NaN", "[object"):
        assert bad not in t, bad
    for words in ("자리 비운 동안 있었던 일", "최근 24시간 · ", "24시간", "3일", "7일", "신호", "점검 통과", "되돌림 대기", "옴 3", "진입", "청산",
                  "판단 바뀜", "전체 ", "추세 ", "거래 ", "실행기 ", "안전 ", "모든 코인", "동전 쌍둥이도 보기", "일지", " · 오늘",
                  "페이퍼(연습)", "실거래", "BCH 롱 계단 익절 · 순ROE +", "N08_ICHI_WR 30분", "다시보기", "1–20 / ",
                  "페이퍼(연습) 손익은 진짜 돈이 아니에요", "바이비트 · WOO X Pro 줄의 손익만 진짜 돈", "WOO X Pro 실행기 기록: 아직 파일이 없어요"):
        assert words in t, words
    assert "동전 쌍둥이 BCH" not in t                     # the twin's rows only behind its switch
    assert out["every"] == [15000] and out["asked"] == ["/api/v4/livebots/journal?hours=24"]
    assert any(h.startswith("#/replay?id=") for h in out["links"]) and "#/safety" in out["links"]
    assert any("ljr-row k-trade t-up" in c for c in cls) and any("ljr-row k-trend" in c for c in cls) and "ljr-hero" in cls
    ev = answer["events"]
    assert out["all"] == len([e for e in ev if not e.get("twin")]) and out["withTwin"] == len(ev)
    assert out["btcTrades"] == [e["id"] for e in ev if e["kind"] == "trade" and e["symbol"] == "BTCUSDT" and not e["twin"]]
    k = out["counts"]
    assert k["all"] == out["all"] and k["signal"] == 6 and k["trade"] == len([e for e in ev if e["kind"] == "trade" and not e["twin"]])
    line = {x["id"]: x for x in out["line"]}
    assert [x["ko"] for x in out["line"]] == ["신호", "점검 통과", "되돌림 대기", "진입", "청산", "판단 바뀜"]
    assert (line["signals"]["v"], line["passed"]["v"], line["waits"]["v"], line["waits"]["sub"], line["entered"]["v"]) == ("6", "4", "4", "옴 3", "3")
    assert line["closed"]["v"] == "3" and line["closed"]["sub"].startswith("+$") and line["closed"]["tone"] == "up"
    assert line["changes"]["kind"] == "trend" and line["signals"]["kind"] == "signal" and line["closed"]["kind"] == "trade"
    assert out["notes"] == [{"text": "추세판단 봇이 켜지기 전 신호는 빼요 (추세판단 봇 시작 10/5 09:00)", "tone": "thin"}]
    assert "추세판단 봇이 켜지기 전 신호는 빼요" in t and out["span"].startswith("최근 24시간 · ") and out["span"].endswith("부터")
    assert out["days"][0].endswith(" · 오늘") and out["days"][1].endswith(" · 어제") and out["days"][2] == "10/19 (월)"
    assert out["link"] == {"href": "#/replay?id=3", "ko": "다시보기"} and out["nolink"] is None
    assert out["tags"] == [{"ko": "페이퍼(연습)", "cls": "thin"}, {"ko": "동전 쌍둥이 (참고)", "cls": "thin"}, {"ko": "실거래", "cls": "warn"}, None]
    assert out["signed"] == ["+$12.30", "−$4.00", "$0.00", "—"]


def test_the_view_states_and_notes(answer):
    off = {**answer, "state": "off", "reason_ko": J.OFF_KO,
           "counts": {**answer["counts"], **{k: None for k in ("signals", "passed", "waits", "touched", "waiting", "changes")}},
           "judge": {**answer["judge"], "state": "off"}, "events": [e for e in answer["events"] if e["kind"] in ("trade", "exec", "safety")]}
    out = _node(VIEW, off)
    assert "꺼짐" in out["text"] and "추세판단 봇이 아니에요" in out["text"]
    line = {x["id"]: x for x in out["line"]}
    assert line["signals"]["v"] == "—" and line["changes"]["v"] == "—" and "추세판단 봇이 아니라" in line["signals"]["title"]
    assert line["entered"]["v"] == "3" and "na" in " ".join(c for c in out["classes"] if "ljr-count" in c)
    assert "추세 —" in out["text"] and "신호 —" in out["text"] and "추세 0" not in out["text"] and "신호 0" not in out["text"]
    for bad in ("null", "undefined", "NaN"):
        assert bad not in out["text"], bad
    # judgments still loading, a long span's note, rows cut (the page asked for 24 hours: an answer of another span is
    # never drawn as this one)
    busy = {**answer, "judge": {**answer["judge"], "pending": True, "read": 6, "state": "pending", "note_ko": "판단 기록은 최근 72시간만"},
            "capped": {"total": 650, "kept": 400, "cut": 250, "kinds": ["signal", "trend"], "low_from": answer["now_ms"] - 50 * 3600000, "hi_from": None}}
    out = _node(VIEW, busy)
    t = out["text"]
    assert "판단 기록은 최근 72시간만 (그 전 판단 바뀜은 안 보여요)" in t and "추세 판단을 불러오는 중이에요 · 6/18" in t
    assert "기록이 많아 250개를 뺐어요 (전체 650개) · 신호·판단 바뀜은 " in t and "거래·실행기·안전은 모두 있어요" in t
    out = _node(VIEW, {**answer, "hours": 168, "t0": answer["now_ms"] - 168 * 3600000})
    assert out["span"].startswith("최근 7일 · ") and "BCH 롱" not in out["text"] and "신호 —" in out["text"]
    # an empty span says so, never a blank
    out = _node(VIEW, {**answer, "events": [], "coins": []})
    assert "이 기간에 기록된 일이 없어요" in out["text"]


# ---------------------------------------------------------------- static checks and the wiring
def test_static():
    node = shutil.which("node")
    if node is not None:
        r = subprocess.run([node, "--check", JS], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
    css = re.sub(r"/\*.*?\*/", "", _read(CSS), flags=re.S)
    js = _read(JS)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css) and not re.search(r"#[0-9a-fA-F]{6}\b", js)
    assert not re.search(r"font-size:\s*\d", css) and not re.search(r"font:\s*\d+\s+\d", css)
    for m in re.finditer(r"font(?:-size)?:\s*([^;]+);", css):
        assert "var(--t-" in m.group(1) or "var(--ts)" in m.group(1), m.group(0)
    assert not re.search(r"innerHTML|insertAdjacentHTML|outerHTML|toLocaleString|Intl\.NumberFormat|eval\(", js)
    # every class of this file is the screen's own (ljr-), and no other screen uses the prefix
    classes = set(re.findall(r"\.([a-zA-Z][\w-]*)", css))
    assert {c for c in classes if not c.startswith("ljr")} <= {"plist", "pp", "na", "up", "down", "warn", "twin", "none", "k-trend",
                                                           "k-signal", "k-trade", "k-exec", "k-safety", "t-up", "t-good", "t-down",
                                                           "t-bad", "t-thin"}
    for f in os.listdir(SCREENS):
        if f.endswith((".css", ".js")) and f not in ("livebots-journal.css", "livebots-journal.js"):
            assert "ljr-" not in _read(SCREENS, f), f
    assert '"/api/v4/livebots/journal"' in js and "export function journalView" in js


def test_the_wiring():
    from paperbot.livedash import app as LA
    assert "livejournal" in LA.MODULES
    js = _read(SCREENS, "livebots.js")
    assert 'import {journalView} from "./livebots-journal.js"' in js
    assert '{id: "journal", label: "일지", make: (ctx) => journalView(ctx), own: true}' in js
    assert js.index('{id: "missed"') > js.index('{id: "journal", label: "일지"') > js.index('{id: "chart"')
    assert js.index('{id: "journal"') < js.index('{id: "trades", label: "거래"')
    routes = _read(V4, "core", "routes.js")
    assert '{id: "rec", ko: "기록", screens: ["journal", "trades", ' in routes
    assert 'journal: {ko: "일지", group: "rec", title: "일지 (자리 비운 동안 있었던 일)"},' in routes and "journal: () => [" in routes
    assert "journal:" in _read(V4, "core", "search.js").split("export const LIVE_ALIAS")[1]
    assert '@import url("livebots-journal.css");' in _read(SCREENS, "livebots.css")
    inv = _read(V4, "INVENTORY.md")
    assert "livebots-journal.js" in inv and "/api/v4/livebots/journal" in inv
    assert "**일지**" in _read(ROOT, "docs", "livedash-ko.md").split("### 기록")[1].split("### 성적")[0]


def test_the_route_serves(world, monkeypatch):
    import fastapi
    from fastapi.testclient import TestClient
    p = world["p"]
    for k, (var, _d) in L.ENV.items():
        monkeypatch.setenv(var, p[k])
    monkeypatch.setenv("PAPERBOT_LIVE_CHECK_DB", world["more"]["check_db"])
    clock = {"t": world["now"]}
    fetch = TCT.Fetch(clock)
    monkeypatch.setattr(TC, "_bars", TC.Bars(fetch, lambda: clock["t"]))      # never Binance from a test
    L._cache.clear()
    app = fastapi.FastAPI()
    assert J.register(app, None) == {"routes": ["/api/v4/livebots/journal"]}
    c = TestClient(app)
    r = c.get("/api/v4/livebots/journal?hours=72")
    assert r.status_code == 200
    d = r.json()
    assert d["state"] == "ok" and d["hours"] == 72 and d["sources"]["execs"][0]["state"] == "ok"
    assert len(fetch.calls) <= TC.FETCH_PER_BUILD
    assert c.get("/api/v4/livebots/journal?hours=5").status_code == 400
    assert c.get("/api/v4/livebots/journal").json()["hours"] == 24
    L._cache.clear()

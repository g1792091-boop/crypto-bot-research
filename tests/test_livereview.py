"""실거래 › 검토 (#/review, "2주 검토" of the 추세판단 봇; GET /api/v4/livebots/trendreview, dash/more/livereview.py;
screens/livebots-review.js, livebots-review.css).

On a paper database written by the trend bot's own code (tests/test_trendbot.py's World: TrendRunner, a fake judge) with
three closed trades (추세 뒤집힘 JUDGE, 시간 정리 TIME, a first lock LOCK), each entered after its pullback, a signal the
trend judge stopped, one the entry checks stopped, one whose pullback never came, and the coin-flip twin's trades:
- the answer: the 2-week freeze (day N of 14, the review date), the record of both paper accounts and the luck words
  (표본 적음 under 20 trades, never "운 범위를 넘게" then), the days and the funnel, the cumulative lines, the split;
- the what-ifs (가상): each group's count and replayed results on the rule bot's 1m bars, the bot's own trades held the
  same way as the yardstick, the supervisor's exits held, the pulled entries at the signal's price and the entry price
  the pullback won; verdicts that never overclaim; the time budget (pending, continued from the memo); the rule bot's
  bars missing = 못 함 with the reason;
- honest states: no file = missing, another bot = off, no judgment yet = missing, garbage = error; the executors since the
  start from their own databases;
- the pure statistics (two_band, the paired sign count);
- the view in node (the tiny DOM): every block and its words, nothing printed as null / NaN, the states, the helpers;
- static checks (node --check, tokens only, the lrv- prefix is this screen's alone) and the wiring (tab, menu, find,
  css, module, docs)."""
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

import test_trendbot as T  # noqa: E402
from paperbot import combo as C  # noqa: E402
from paperbot.dash.more import livereview as LR  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
SCREENS = os.path.join(V4, "screens")
JS = os.path.join(SCREENS, "livebots-review.js")
CSS = os.path.join(SCREENS, "livebots-review.css")
MIN, HOUR, DAY = T.MIN, T.HOUR, 86_400_000


def _read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(autouse=True)
def _fresh():
    LR._memo.clear()
    yield
    LR._memo.clear()


def _setup(w, sym, tf="30m"):
    """The coin's higher bar up and its entry bar near the EMA20 (a short signal bar: the 0.25 ATR pullback)."""
    px = w.px[sym]
    htf = {"30m": "1h", "1h": "4h"}[tf]
    w.judge.j[(sym, htf)] = T.J(close=px, ema20=px * 0.999, atr=px * 0.005, tf=htf)
    w.judge.s[(sym, tf)] = T.S(ema20=px, atr=px * 0.003, rng=px * 0.001, tf=tf)


def _world(tmp_path):
    w = T.World(tmp_path)
    w.store.put_state("combo_run", T.T0, {"config": json.loads(json.dumps(C.dataclasses.asdict(w.cfg), default=str))})
    # 1. BTC long (N08 30m) after its pullback; the 1h judgment turns: 감독 청산 (추세 뒤집힘) at T0 + 1 h
    B, _p = T._enter_long(w)
    w.judge.j[("BTCUSDT", "1h")] = T.J(dir=-1, votes={"V39": -1, "S6": -1, "OBV": -1, "N12": 1})
    T._to(w, B + 3 * MIN, T.T0 + HOUR + MIN)
    w.judge.j[("BTCUSDT", "1h")] = T.J()
    for s in T.SYMS[1:]:
        _setup(w, s)
    # 2. ETH long (F3_BOS) after its pullback, no first lock in 4 bars: 감독 청산 (시간 정리); SOL short against the 1h
    #    trend (추세 판단), DOGE long at RSI 71 (진입 자리 검사)
    B2 = T.T0 + 90 * MIN
    T._to(w, T.T0 + HOUR + MIN, B2)
    w.signal("F3_BOS", "ETHUSDT", 1, B2)
    w.signal("N08_ICHI_WR", "SOLUSDT", -1, B2)
    w.judge.s[("DOGEUSDT", "30m")] = T.S(ema20=w.px["DOGEUSDT"], atr=w.px["DOGEUSDT"] * 0.003, rsi=71.0, rng=w.px["DOGEUSDT"] * 0.001)
    w.signal("N08_ICHI_WR", "DOGEUSDT", 1, B2)
    w.step(B2)
    w.step(B2 + MIN, move={"ETHUSDT": -0.001})
    E2 = B2 + 2 * MIN + 4 * 30 * MIN + 2 * MIN
    T._to(w, B2 + 2 * MIN, E2)
    # 3. LTC long (F3_BOS) while LTC only rises: 되돌림 안 옴
    B3 = T.T0 + 4 * HOUR + 30 * MIN
    T._to(w, E2, B3)
    _setup(w, "LTCUSDT")
    w.signal("F3_BOS", "LTCUSDT", 1, B3)
    T._to(w, B3, B3 + 31 * MIN, move={"LTCUSDT": 0.0003})
    # 4. BCH long (N08) after its pullback: runs past the first lock, comes back to it (LOCK)
    B4 = T.T0 + 5 * HOUR
    T._to(w, B3 + 31 * MIN, B4)
    _setup(w, "BCHUSDT")
    w.signal("N08_ICHI_WR", "BCHUSDT", 1, B4)
    w.step(B4)
    w.step(B4 + MIN, move={"BCHUSDT": -0.001})
    T._to(w, B4 + 2 * MIN, B4 + 12 * MIN, move={"BCHUSDT": 0.0012})
    T._to(w, B4 + 12 * MIN, B4 + 40 * MIN, move={"BCHUSDT": -0.0006})
    w.store.commit()
    return w, B4 + 41 * MIN


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    w, now = _world(tmp_path_factory.mktemp("review"))
    return {"w": w, "now": now, "p": {"paper": w.cfg.db}, "more": {"rule_db": w.cfg.paper_db}}


def _build(world, **kw):
    return LR.build(world["p"], world["now"], more=world["more"], **kw)


def test_the_answer(world):
    w, now = world["w"], world["now"]
    d = _build(world)
    assert d["state"] == "ok" and d["name"] == "추세판단 봇" and d["since"] == T.T0
    b = d["bot"]
    assert (b["day_n"], b["days"], b["until"], b["d_left"], b["done"]) == (1, 14, T.T0 + 14 * DAY, 14, False)
    # the record of both paper accounts since the start, the twin on the bot's own entries
    real, flip = d["record"]["real"], d["record"]["flip"]
    assert real["n"] == 3 and sorted(t["exit_reason"] for t in w.trades()) == ["JUDGE", "LOCK", "TIME"]
    assert (real["wins"], real["losses"]) == (1, 2) and real["small"] is True
    assert real["pnl"] == pytest.approx(sum(t["pnl"] for t in w.trades()))
    twin = [json.loads(x) for (x,) in w.store.conn.execute("SELECT data FROM trades WHERE account_id = ?", (C.FLIP_ACCOUNT,))]
    assert flip["n"] == len(twin) >= 2 and {t["entry_time"] for t in twin} <= {t["entry_time"] for t in w.trades()}
    luck = d["record"]["luck"]
    assert luck["state"] == "ok" and luck["ko"].startswith("표본 적음: 대부분 운이에요 (거래 3번)") and "넘게" not in luck["ko"]
    assert luck["band_rate"][0] <= flip["win_rate"] <= luck["band_rate"][1]
    # the funnel since the start and the day (one KST day)
    f = d["funnel"]
    assert (f["signals"], f["passed"], f["touched"], f["entered"]) == (6, 4, 3, 3)
    assert {x["id"]: x["n"] for x in f["blocked"]} == {"trend": 1, "spot": 1, "nopull": 1}
    (day,) = d["days"]
    assert day["d0"] == T.T0 - 9 * HOUR and day["today"] is True and (day["signals"], day["entered"], day["n"]) == (6, 3, 3)
    assert day["pnl"] == pytest.approx(real["pnl"]) and day["flip_n"] == flip["n"]
    # the cumulative lines end at the record
    assert d["curve"]["real"][0] == [T.T0, 0.0, 0.0] and d["curve"]["real"][-1][1] == pytest.approx(real["pnl"])
    assert d["curve"]["flip"][-1][2] == pytest.approx(flip["roe_sum"])
    # the split: every member of the config (one without a trade: no record, never a zero), roles, exits, sides
    sp = d["split"]
    assert [m["id"] for m in sp["member"]] == ["N08_ICHI_WR@30m", "F3_BOS@30m", "S3_CMO_SANDWICH@1h"]
    assert sp["member"][2]["n"] == 0 and sp["member"][2]["win_rate"] is None and sp["member"][2]["roe_sum"] is None
    assert {r["id"]: r["n"] for r in sp["role"]} == {"눌림": 2, "돌파": 1}
    assert {r["id"]: r["n"] for r in sp["exit"]} == {"LOCK": 1, "JUDGE": 1, "TIME": 1} and sp["exit"][0]["ko"] == "계단 익절"
    assert [r["id"] for r in sp["side"]] == [1] and [r["id"] for r in sp["tf"]] == ["30m"]
    assert {x["id"]: x["state"] for x in d["execs"]} == {"bybit": "missing", "mexc": "missing"}       # no executor files here
    assert now - T.T0 < DAY


def test_the_what_ifs(world):
    w = world["w"]
    d = _build(world)
    wi = d["whatif"]
    items = {x["id"]: x for x in wi["items"]}
    assert [x["id"] for x in wi["items"]] == ["trend", "spot", "nopull", "judge", "time", "pull"]
    assert wi["work"]["done"] > 0 and wi["work"]["pending"] == 0 and wi["rule_db"]["state"] == "ok"
    assert "가상" in wi["note_ko"] and "펀딩비" in wi["note_ko"]
    for it in wi["items"]:
        assert it["state"] == "ok" and "(가상)" in it["how_ko"] and it["rule_ko"]
    # a-c: the stopped signals, each replayed from its own price (the newest rows with the bot's own reason)
    for wid, sym, why in (("trend", "SOLUSDT", "1시간 추세가 상승이라 숏 안 함"), ("spot", "DOGEUSDT", "30분 RSI 71 과열"),
                          ("nopull", "LTCUSDT", "되돌림 안 옴")):
        it = items[wid]
        assert it["n"] == 1 and it["virt"]["n"] == 1 and it["virt"]["pending"] == 0, wid
        (row,) = it["rows"]
        assert row["symbol"] == sym and row["why"].startswith(why) and row["cf"]["state"] in ("won", "lost", "open"), row
        assert it["base"]["n"] == 3 and it["actual"]["n"] == 3 and it["actual"]["wins"] == 1
        assert it["verdict"]["kind"] == "small" and it["verdict"]["ko"].startswith("아직 판단 못 함")
    # the bot's own trades held the same way: the LOCK trade's replay is the trade itself
    assert items["trend"]["base"]["decided"] >= 1
    # d: the supervisor's exits held instead (one each), the real exit next to it
    for wid, reason in (("judge", "JUDGE"), ("time", "TIME")):
        it = items[wid]
        (row,) = it["rows"]
        t = next(x for x in w.trades() if x["exit_reason"] == reason)
        assert it["n"] == 1 and row["roe"] == pytest.approx(t["roe"]) and row["entry_time"] == t["entry_time"]
        assert row["why"] == t["context"]["exit_why"] and it["verdict"]["kind"] == "small"
        if row["cf"]["state"] in ("won", "lost"):
            assert row["delta"] == pytest.approx(t["roe"] - row["cf"]["roe"])
    # e: every trade came after its pullback; the price it won against the signal's price (real numbers)
    from paperbot.config import v3_settings
    slip = v3_settings().slippage_frac                    # the run names no taker fee here: the settings' slippage
    it = items["pull"]
    assert it["n"] == it["of"] == 3 and it["gain"]["n"] == 3
    for row in it["rows"]:
        t = next(x for x in w.trades() if x["entry_time"] == row["t"])
        assert row["entry_price"] == pytest.approx(t["entry_price"]) and row["sig_t"] < row["t"] <= row["sig_t"] + 30 * MIN
        fill = row["sig_price"] * (1 + t["side"] * slip)  # the signal's price with the slippage against, as a virtual entry
        assert row["gain"] == pytest.approx(t["side"] * (fill - t["entry_price"]) / t["entry_price"] * t["leverage"])
    btc = next(r for r in it["rows"] if r["symbol"] == "BTCUSDT")
    assert btc["sig_price"] == pytest.approx(T.PX["BTCUSDT"]) and btc["gain"] > 0       # bought 0.1 % lower than the signal
    # the second answer: every decided result from the memo
    d2 = _build(world)
    assert d2["whatif"]["work"]["memo"] > 0 and d2["whatif"]["work"]["done"] <= wi["work"]["done"]


def test_the_time_budget_and_missing_bars(world):
    d = _build(world, budget_s=0.0)                       # nothing replayed: everything pending, said so
    wi = d["whatif"]
    assert wi["work"]["done"] == 0 and wi["work"]["pending"] > 0
    assert all(x["virt"]["pending"] == 1 for x in wi["items"] if x["id"] in ("trend", "spot", "nopull"))
    assert next(x for x in wi["items"] if x["id"] == "pull")["at"]["pending"] == 3
    d = _build(world)                                     # the next ask finishes the work
    assert d["whatif"]["work"]["pending"] == 0
    LR._memo.clear()
    d = LR.build(world["p"], world["now"], more={"rule_db": str(world["w"].cfg.db) + ".none"})
    wi = d["whatif"]
    assert wi["rule_db"]["state"] == "missing"
    for it in wi["items"]:
        assert it["verdict"]["kind"] == "na" and it["verdict"]["ko"].startswith("못 함 · 규칙봇 1분봉 파일이 아직 없어요"), it["id"]
    assert not LR._memo                                   # an unreadable file is never kept as a result


def test_honest_states(tmp_path):
    assert LR.build({"paper": str(tmp_path / "none.db")})["state"] == "missing"
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"not a database at all" * 50)
    d = LR.build({"paper": str(bad)})
    assert d["state"] == "error" and d["reason_ko"] == "페이퍼 봇 기록을 읽지 못했어요" and d["reason"]
    s = Store3(str(tmp_path / "old.db"))
    s.put_state("combo_run", T.T0, {"config": {"name": "규칙봇 15", "trend": None}})
    s.commit()
    d = LR.build({"paper": str(tmp_path / "old.db")})
    assert d["state"] == "off" and "추세판단 봇이 아니에요" in d["reason_ko"] and "record" not in d
    s.put_state("combo_run", T.T0, {"config": {"name": "추세판단 봇", "trend": {}}})
    s.commit()
    d = LR.build({"paper": str(tmp_path / "old.db")})
    assert d["state"] == "missing" and "첫 판단" in d["reason_ko"]
    # no ladder in the config (a config this screen cannot replay): every what-if 못 함 with the reason, no table: 수집 전
    s.put_state("trend", T.T0, {"since": T.T0})
    s.commit()
    s.close()
    d = LR.build({"paper": str(tmp_path / "old.db")}, T.T0 + HOUR, more={"rule_db": str(tmp_path / "rule.db")})
    assert d["state"] == "ok" and d["record"]["real"]["n"] == 0 and d["record"]["luck"]["state"] == "none"
    for it in d["whatif"]["items"]:
        assert it["verdict"]["kind"] == "na" and it["state"] in ("missing", "error"), it


def test_the_executors_since_the_start(tmp_path):
    from paperbot.executor import ExecStore
    path = str(tmp_path / "exec.db")
    st = ExecStore(path, lock=False)
    st.put_state("bot", T.T0 + DAY, {"mode": "mainnet", "risk": {"last_equity": 101.0}})
    for k, (et, pnl) in enumerate(((T.T0 - HOUR, -3.0), (T.T0 + HOUR, 1.5), (T.T0 + 2 * HOUR, -0.5))):
        key = f"{C.ACCOUNT}|BTCUSDT|{et}"
        tr = {"key": key, "symbol": "BTCUSDT", "side": 1, "qty": 0.001, "leverage": 40, "entry_ts": et + 9000, "entry_price": 60000.0,
              "stop_initial": 59300.0, "mode": "mainnet", "entry_time": et, "paper_entry": 60000.0}
        st.trade_open(tr)
        st.trade_close(key, et + 30 * MIN, "paper 청산 → 거래소 포지션 닫기", pnl, tr, "fills")
    st.close()
    out = LR.exec_since({"bybit_db": path, "mexc_db": str(tmp_path / "none.db"), "bybit_config": str(tmp_path / "x.json"),
                         "mexc_config": str(tmp_path / "y.json")}, T.T0, T.T0 + DAY)
    by = {x["id"]: x for x in out}
    assert (by["bybit"]["state"], by["bybit"]["n"], by["bybit"]["wins"], by["bybit"]["real"]) == ("ok", 2, 1, True)
    assert by["bybit"]["pnl"] == pytest.approx(1.0) and by["bybit"]["balance"] == 101.0      # the trade before the start left out
    assert by["mexc"]["state"] == "missing" and by["mexc"]["reason_ko"]


def test_the_statistics():
    tb = LR.two_band(15, 20, 15, 20)
    assert tb["where"] == "inside" and tb["gap"] == 0 and tb["band"][0] < 0.75 < tb["band"][1]
    assert LR.two_band(38, 40, 20, 40)["where"] == "above" and LR.two_band(20, 40, 38, 40)["where"] == "below"
    assert LR.two_band(3, 4, 0, 0) is None
    # luck words: under 20 never more than 표본 적음; 20-39 with the gap beyond luck: says to look on
    r = lambda n, w: {"n": n, "wins": w, "win_rate": w / n, "roe_sum": 0.0}         # noqa: E731
    assert LR.luck_of(r(10, 10), r(10, 2))["ko"] == "표본 적음: 대부분 운이에요 (거래 10번) · 차이가 보여도 아직 믿기 어려워요"
    assert LR.luck_of(r(30, 29), r(30, 12))["ko"].startswith("진짜 방향이 동전보다 운 범위를 넘게 앞서요 (거래 30번")
    assert LR.luck_of(r(60, 40), r(60, 38))["ko"] == "동전과의 차이는 운으로도 생기는 크기예요"
    assert LR.luck_of(r(60, 20), r(60, 45))["where"] == "below"
    # the blocked side against the bot's trades (both noisy), and the paired sign count against a coin
    v = lambda n, w: {"n": n, "decided": n, "won": w, "win_rate": w / n}            # noqa: E731
    assert LR.verdict_blocked({"n": 0, "decided": 0, "won": 0}, v(30, 25))["kind"] == "none"
    assert LR.verdict_blocked(v(19, 5), v(30, 25))["kind"] == "small"
    assert LR.verdict_blocked(v(40, 20), v(10, 9))["kind"] == "small"                 # the bot's own trades too few
    assert LR.verdict_blocked(v(40, 20), v(40, 36))["kind"] == "helped"
    assert LR.verdict_blocked(v(40, 39), v(40, 30))["kind"] == "hurt"
    assert LR.verdict_blocked(v(40, 33), v(40, 34))["kind"] == "luck"
    assert LR.verdict_paired(0, 0, 0, 0.0, 0)["kind"] == "none" and LR.verdict_paired(0, 0, 0, 0.0, 2)["kind"] == "small"
    assert LR.verdict_paired(12, 3, 15, 0.4, 15)["kind"] == "small"
    assert LR.verdict_paired(18, 4, 22, 0.9, 22)["kind"] == "helped" and "+90.0%p" in LR.verdict_paired(18, 4, 22, 0.9, 22)["ko"]
    assert LR.verdict_paired(4, 18, 22, -0.9, 22)["kind"] == "hurt" and "−90.0%p" in LR.verdict_paired(4, 18, 22, -0.9, 22)["ko"]
    assert LR.verdict_paired(12, 10, 22, 0.1, 22)["kind"] == "luck"
    fz = LR.freeze_of(T.T0, T.T0 + 13 * DAY + HOUR)
    assert (fz["day_n"], fz["d_left"], fz["done"]) == (14, 1, False)
    fz = LR.freeze_of(T.T0, T.T0 + 15 * DAY)
    assert (fz["day_n"], fz["d_left"], fz["done"], fz["frac"]) == (14, 0, True, 1.0)


# ---------------------------------------------------------------- the view in node
def _node(body: str, data, summary=None) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    dom = "file://" + os.path.join(ROOT, "tests", "anasyn_dom.mjs")
    now = (data or {}).get("now_ms") or T.T0
    script = (f"Date.now = () => {int(now)};\nconst D = await import('{dom}');\nconst X = await import('file://{JS}');\n"
              f"const d = {json.dumps(data)};\nconst sum = {json.dumps(summary)};\n"
              "const tick = async () => { for (let i = 0; i < 3; i++) await new Promise((r) => setTimeout(r, 0)); };\n" + body)
    r = subprocess.run([node, "--input-type=module"], input=script, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


SUMMARY = {"accts": [{"id": "bybit", "kind": "live", "name_ko": "바이비트", "state": "ok", "balance": 101.5},
                     {"id": "paper", "kind": "paper", "state": "ok", "balance": 977.61}]}
VIEW = """const every = [];
const ctx = {api: () => Promise.resolve(d), every(ms, fn) { every.push(ms); }, watch() {}, alive: () => true,
  href: (n, a) => '#/' + a};
const v = X.reviewView(ctx, {get: () => sum});
await tick();
const w = D.walk(v.el);
const find = (n, c) => { if (!n || !n.childNodes) return null; if (String(n.className || "").split(" ").includes(c)) return n;
  for (const k of n.childNodes) { const f = find(k, c); if (f) return f; } return null; };
console.log(JSON.stringify({text: w.text.replace(/\\s+/g, " "), classes: w.classes, every,
  hidden: !!(find(v.el, "lrv-cards") || {}).hidden, head: X.headline(d), check: X.checklist(d),
  fz: [X.freezeView({until: 1, days: 14, day_n: 3, d_left: 12, frac: 0.2, done: false}), X.freezeView({until: 1, days: 14, done: true}), X.freezeView(null)],
  chips: ["helped", "hurt", "luck", "small", "none", "na", "zzz"].map(X.verdictChip),
  parts: X.funnelParts({signals: 10, passed: 4, touched: 3, entered: 2}, 20),
  curve: X.curvePaths({real: [[0, 0, 0], [50, 10, 0.1]], flip: [[0, 0, 0], [100, -5, -0.05]]}, 1, 100, 50, 100),
  nocurve: X.curvePaths({real: [], flip: []}, 1, 100, 50, 0),
  fmt: [X.pp(0.308), X.pp(-0.05), X.pp(null), X.signed(12.3), X.signed(-4), X.signed(null), X.dayKo(1791158400000)]}));"""


@pytest.fixture(scope="module")
def answer(world):
    LR._memo.clear()
    return json.loads(json.dumps(_build(world)))


def test_the_view(answer):
    out = _node(VIEW, answer, SUMMARY)
    t, cls = out["text"], out["classes"]
    for bad in ("null", "undefined", "NaN", "[object"):
        assert bad not in t, bad
    for words in (
            # the first block: the freeze ring, the headline, real vs coin with the luck words, the executors
            "일째 / 14일", "D-14", "10/19 (월) 검토 · 그때까지 규칙을 바꾸지 않아요", "새 규칙 1일째 · 거래 3번 · 표본 적음: 대부분 운",
            "새 규칙 시작 10/05 09:00", "진짜 방향", "동전 방향", "페이퍼(연습)", "같은 진입 · 방향만 동전", "첫 잠금까지 간 비율", "1승 2패",
            "순손익 (페이퍼)", "순ROE 합", "표본 적음: 대부분 운이에요 (거래 3번)", "운만으로도 생기는 차이", "바이비트 실거래", "수집 전",
            # 하루하루
            "하루하루", "신호", "검사 통과", "되돌림 닿음", "진입", "걸린 곳: 추세 판단", "10/05 (월)", "6 → 4 → 3 → 3", "누적 · 진짜 방향 vs 동전 방향",
            "순ROE 합", "손익 (USDT)",
            # 새 규칙이 도왔나? (가상)
            "새 규칙이 도왔나?", "가상", "추세 판단", "진입 자리 검사", "되돌림 기다림 (버린 신호)", "감독: 추세 뒤집힘 청산", "감독: 시간 정리",
            "되돌림 진입가", "아직 판단 못 함", "1개 신호가 걸림", "걸린 신호 (가상)", "봇이 탄 거래 (같은 방식 가상)", "봇 실제 (페이퍼): 3번",
            "이 규칙으로 닫음", "실제 (감독 청산)", "붙잡았다면 (가상)", "3번 되돌림으로 진입", "진입가 이득", "최근 1개 보기",
            "1시간 추세가 상승이라 숏 안 함", "추세 판단에 걸린 신호를 신호 가격에 들어갔다면 (가상)",
            # 나눠 보기, 검토 날 볼 것, the captions
            "나눠 보기", "역할", "매매법", "코인", "방향", "청산 이유", "진입 봉", "눌림", "돌파", "검토 날 볼 것", "거래가 충분한가요?",
            "진짜 방향이 동전 방향보다 나은가요?", "두 분이 정해요: 그대로 가기 · 한 가지만 바꾸기 · 멈추기", "규칙을 바꾸는 건 두 분의 결정이에요",
            "비용 탭에서 봐요 →", "페이퍼(연습) 손익은 진짜 돈이 아니에요", "바이비트 · WOO X Pro: 새 규칙 시작 뒤 들어간 거래만 셈"):
        assert words in t, words
    # the chip already says 아직 판단 못 함: the verdict line says why without repeating it
    assert "결정 난 가상 결과" in t and t.count("아직 판단 못 함 · 결정 난 가상 결과") == 0
    assert out["every"] == [15000] and out["hidden"] is False
    assert "lrv-hero" in cls and any("lrv-rule k-small" in c for c in cls) and any("lrv-seg-entered" in c for c in cls)
    assert out["head"] == "새 규칙 1일째 · 거래 3번 · 표본 적음: 대부분 운"
    ck = out["check"]
    assert [c["id"] for c in ck] == ["enough", "coin", "rules", "cost", "decide"] and ck[0]["tone"] == "warn"
    assert ck[3]["link"] == "cost" and "판단 미룸 6개" in ck[2]["now"]
    assert out["fz"][0]["big"] == "D-12" and out["fz"][0]["dayN"] == 3 and out["fz"][1]["big"] == "검토할 때예요" and out["fz"][2]["big"] == "—"
    assert [c["ko"] for c in out["chips"]] == ["도운 쪽", "손해 본 쪽", "운 범위 안", "아직 판단 못 함", "아직 없음", "못 함", "아직 판단 못 함"]
    assert [(p["k"], p["n"]) for p in out["parts"]] == [("entered", 2), ("touched", 1), ("passed", 1), ("stopped", 6)]
    assert sum(p["frac"] for p in out["parts"]) == pytest.approx(0.5)
    c = out["curve"]
    assert c["real"].startswith("M0.0 ") and c["flip"].endswith("H100.0") and c["lo"] < -5 and c["hi"] > 10 and out["nocurve"] is None
    assert out["fmt"] == ["+30.8%p", "−5.0%p", "—", "+$12.30", "−$4.00", "—", "10/05 (월)"]


def test_the_view_states_and_a_what_if_that_cannot_be_worked_out(answer):
    out = _node(VIEW, {"state": "off", "reason_ko": "지금 돌고 있는 페이퍼 봇은 추세판단 봇이 아니에요 (설정에 추세 판단이 없음)"})
    assert "꺼짐" in out["text"] and "추세판단 봇이 아니에요" in out["text"] and out["hidden"] is True
    out = _node(VIEW, {"state": "missing", "reason_ko": "추세판단 봇이 아직 첫 판단을 기록하지 않았어요 (켠 뒤 1~2분)"})
    assert "수집 전" in out["text"] and "첫 판단" in out["text"] and out["hidden"] is True
    assert out["head"] == "2주 검토 기록을 기다리는 중"
    d = json.loads(json.dumps(answer))
    d["whatif"]["items"][0] = {**d["whatif"]["items"][0], "state": "missing", "reason_ko": "신호 기록 표(signal_log)가 아직 없어요",
                               "verdict": {"kind": "na", "ko": "못 함 · 신호 기록 표(signal_log)가 아직 없어요"}, "rows": []}
    d["whatif"]["work"] = {"done": 0, "pending": 7, "memo": 0}
    out = _node(VIEW, d)
    assert "수집 전 · 신호 기록 표(signal_log)가 아직 없어요" in out["text"] and "못 함" in out["text"]
    assert "가상 결과를 계산하는 중이에요 · 7개 남음" in out["text"]
    for bad in ("null", "undefined", "NaN", "[object"):
        assert bad not in out["text"], bad


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
    # every class of this file is the screen's own (lrv-), and no other screen uses the prefix
    classes = set(re.findall(r"\.([a-zA-Z][\w-]*)", css))
    assert {c for c in classes if not c.startswith("lrv")} <= {"card", "lrv", "seg", "pp", "up", "down", "real", "flip", "done", "today",
                                                           "zero", "good", "warn", "bad", "na", "top", "bot", "above", "below",
                                                           "virt", "base", "s3", "helped", "hurt", "small", "none",
                                                           "k-helped", "k-hurt", "k-luck", "k-na", "on"}
    for f in os.listdir(SCREENS):
        if f.endswith(".css") and f != "livebots-review.css":
            assert "lrv-" not in _read(SCREENS, f), f
    assert '"/api/v4/livebots/trendreview"' in js and "export function reviewView" in js


def test_the_wiring():
    from paperbot.livedash import app as LA
    assert "livereview" in LA.MODULES
    js = _read(SCREENS, "livebots.js")
    assert 'import {reviewView} from "./livebots-review.js"' in js
    assert '{id: "review", label: "검토", make: (ctx, hub) => reviewView(ctx, hub), own: true}' in js
    assert js.index('{id: "missed"') < js.index('{id: "review", label: "검토"') < js.index('{id: "perf", label: "성적"')
    routes = _read(V4, "core", "routes.js")
    assert '{id: "perf", ko: "성적", screens: ["review", "perf", ' in routes
    assert 'review: {ko: "검토", group: "perf", title: "2주 검토 (추세판단 봇)"},' in routes and "review: () => SICON." in routes
    assert "review:" in _read(V4, "core", "search.js").split("export const LIVE_ALIAS")[1]
    assert '@import url("livebots-review.css");' in _read(SCREENS, "livebots.css")
    assert "livebots-review.js" in _read(V4, "INVENTORY.md") and "/api/v4/livebots/trendreview" in _read(V4, "INVENTORY.md")
    assert "**검토**" in _read(ROOT, "docs", "livedash-ko.md") and "검토" in _read(ROOT, "docs", "trend-bot-ko.md").split("## 6.")[1]


def test_the_route_serves(world, monkeypatch):
    import fastapi
    from fastapi.testclient import TestClient
    from paperbot.dash.more import livebots as L
    monkeypatch.setenv("PAPERBOT_LIVE_PAPER_DB", world["w"].cfg.db)
    monkeypatch.setenv("PAPERBOT_LIVE_RULE_DB", world["w"].cfg.paper_db)
    for k in ("PAPERBOT_LIVE_BYBIT_DB", "PAPERBOT_LIVE_MEXC_DB", "PAPERBOT_LIVE_BYBIT_CONFIG", "PAPERBOT_LIVE_MEXC_CONFIG"):
        monkeypatch.setenv(k, "/nonexistent/x")
    L._cache.clear()
    app = fastapi.FastAPI()
    assert LR.register(app, None) == {"routes": ["/api/v4/livebots/trendreview"]}
    r = TestClient(app).get("/api/v4/livebots/trendreview")
    assert r.status_code == 200
    d = r.json()
    assert d["state"] == "ok" and d["record"]["real"]["n"] == 3 and d["bot"]["day_n"] == 14     # (now: the real clock)
    L._cache.clear()

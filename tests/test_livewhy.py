"""실거래 › 진입 근거 (dash/more/livewhy.py, screens/livebots-why.js; owners 10/20 "진입하면 왜 진입했는지 어떤 근거로 진입했는지
대시보드에 보여?" → "응 만들어줘"): on the hand-made live world (tests/livebots_world.py) with the 규칙봇 15 config, its open BTC
long given the records a real entry leaves (the paper's ENTERED outcome, the bot's signal_log rows of that bar, the rule
bot's signal_log row with the chart ctx and its 1m bars):

- the signal: the setting (B group, entry mode, the −50 % net stop), the strategy, its timeframe, the signal bar, where the
  signal came from, the reference price → the fill, the score and that this bot ranks by the config's order
- the strategy's own conditions on the signal bar worked out again on the bars ``frames`` gives (cut at the signal bar),
  with the indicator values there; kept per signal bar; honest states without bars, without the signal bar, too old
- the chart from the rule bot's record in words (with / against the trade) and the entry-only loss-card marks
- the checks before the entry: weekend, macro (the nearest release), NYSE open, the B setting's chase test with its range
  places, one position at a time
- the other signals of the bar, the record before this entry, the 5-year numbers (main bot only)
- the position cards and the 거래 rows carry the reference (an executor: the paper entry it followed); the route on the
  live app; the panel in node
"""
import json
import os
import re
import shutil
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import livebots_world as W  # noqa: E402
from paperbot.dash import app as D  # noqa: E402
from paperbot.dash.more import livebots as L  # noqa: E402
from paperbot.dash.more import livepos as P  # noqa: E402
from paperbot.dash.more import livewhy as Y  # noqa: E402
from paperbot.livedash import app as LA  # noqa: E402
from paperbot.models import Signal, SignalOutcome  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402
from test_dash import SECRET  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
PW = "correct horse battery"
NOW, T0, H, MIN = W.NOW, W.T0, W.H, W.MIN
ENTRY = T0 + 9 * H                     # the open BTC long of the world: its signal bar (1h) closed at this minute
MEMBER = "S2_ST_ROC@1h#1~abc123"
CTX = {"tf": "1h", "htf": "4h", "regime": "trend_up", "htf_regime": "trend_down", "adx": 17.5, "di_plus": 28.0, "di_minus": 14.0,
       "ema20_dist_atr": 2.4, "trend_age": 9, "range_pct": 0.95, "sr": {"breakout": 1}}


def live15_config() -> dict:
    with open(os.path.join(ROOT, "deploy", "combo.live15.json"), encoding="utf-8") as fh:
        cfg = json.load(fh)
    cfg["members"][0] = {"strategy": "S2_ST_ROC", "tf": "1h", "no_chase": True}
    return cfg


def entry_records(paper_db: str, rule_db: str) -> None:
    """What a real entry leaves: the paper's ENTERED outcome and its signal_log rows of the bar (this signal and one that lost
    to it), the rule bot's signal_log row (chart ctx) and its 1m BTC bars of the 8 days before (the chase test)."""
    s = Store3(paper_db)
    s.put_state("combo_run", T0, {"version": "combo-v2", "taker_fee": 0.0005, "members": [], "config": live15_config()})
    sig = Signal(ts=ENTRY - 1, symbol="BTCUSDT", timeframe="1h", strategy_id="S2_ST_ROC", side=1, stop_price=0.0, tier="best", score=3.4,
                 atr=300.0, meta={"member": MEMBER, "member_order": 1, "source": "rule", "ref_price": 61990.0, "ref_time": ENTRY + 4000,
                                  "delay_ms": 4000, "score_raw": 3.4})
    s.outcome(W.ACCOUNT, SignalOutcome(sig, "ENTERED", "ok", ENTRY, {"fill": 62000.0, "leverage": 40, "margin": 387.5}))
    lost = Signal(ts=ENTRY - 1, symbol="ETHUSDT", timeframe="30m", strategy_id="OBV_S", side=-1, stop_price=0.0, tier="best", score=3.0,
                  atr=3.0, meta={"member": "OBV_S@30m#7", "member_order": 7, "source": "rule"})
    s.outcome(W.ACCOUNT, SignalOutcome(lost, "SKIPPED", "lower score than entered signal", ENTRY, {}))
    s.log_signals([{"bar_close": ENTRY, "timeframe": "1h", "strategy": MEMBER, "symbol": "BTCUSDT", "side": 1, "atr": 300.0,
                    "ref_price": 61990.0, "ref_time": ENTRY + 4000, "delay_ms": 4000, "status": "SUBMITTED", "data": {"source": "rule", "strategy": "S2_ST_ROC"}},
                   {"bar_close": ENTRY, "timeframe": "30m", "strategy": "OBV_S@30m#7", "symbol": "ETHUSDT", "side": -1, "atr": 3.0,
                    "ref_price": 2400.0, "ref_time": ENTRY + 4000, "delay_ms": 4000, "status": "SUBMITTED", "data": {"source": "rule", "strategy": "OBV_S"}},
                   {"bar_close": ENTRY, "timeframe": "30m", "strategy": "F15_ORB@30m#10", "symbol": "SOLUSDT", "side": 1, "atr": 1.0,
                    "ref_price": 150.0, "ref_time": ENTRY + 4000, "delay_ms": 4000, "status": "FILTERED",
                    "data": {"source": "rule", "strategy": "F15_ORB", "why": "추격 진입 막기: 롱인데 24시간 고점 쪽(95% 위치)"}}])
    s.close()
    r = Store3(rule_db)
    r.log_signals([{"bar_close": ENTRY, "timeframe": "1h", "strategy": "S2_ST_ROC", "symbol": "BTCUSDT", "side": 1, "atr": 300.0,
                    "ref_price": 61990.0, "ref_time": ENTRY + 4000, "delay_ms": 4000, "status": "SUBMITTED",
                    "data": {"close": 61980.0, "bid": 61985.0, "ask": 61990.0, "ctx": CTX}}])
    rows = []
    for k in range(ENTRY // H - 8 * 24, ENTRY // H):          # one bar per half hour: highs 62,500 (63,000 at times), lows 61,000 (60,000)
        for m in (0, 30):
            ts = k * H + m * MIN
            rows.append({"ts": ts, "symbol": "BTCUSDT", "open": 61500.0, "high": 63000.0 if k % 50 == 0 else 62500.0,
                         "low": 60000.0 if k % 40 == 0 else 61000.0, "close": 61500.0, "volume": 1.0, "close_time": ts + MIN - 1,
                         "processed_at": ts + MIN})
    r.live_bars(rows)
    r.close()


class Frames:
    """Binance's closed bars for the recheck (random walk, the newest bar closed before NOW); counts its calls."""
    def __init__(self, drop_signal_bar: bool = False):
        self.calls = []
        self.drop = drop_signal_bar

    def __call__(self, symbol, tf, n):
        self.calls.append((symbol, tf, n))
        span = {"15m": 900, "30m": 1800, "1h": 3600, "4h": 14400}[tf]
        end = (NOW // 1000 // span) * span
        rng = np.random.default_rng(7)
        c = 60000 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
        o = np.r_[c[0], c[:-1]]
        ts = [end - span * (n - i) for i in range(n)]
        df = pd.DataFrame({"ts": pd.to_datetime(ts, unit="s", utc=True), "open": o, "high": np.maximum(o, c) * 1.002,
                           "low": np.minimum(o, c) * 0.998, "close": c, "volume": 1.0})
        if self.drop:
            df = df[df["ts"] != pd.Timestamp(ENTRY - H, unit="ms", tz="UTC")].reset_index(drop=True)
        return df


@pytest.fixture(autouse=True)
def _fresh():
    L._cache.clear()
    Y._cond.clear()
    yield
    L._cache.clear()
    Y._cond.clear()


@pytest.fixture
def world(tmp_path, monkeypatch):
    folder = str(tmp_path / "w")
    p = W.build_world(folder)
    rule = os.path.join(folder, "rule-paper3.db")
    entry_records(p["paper"], rule)
    more = {"rule_db": rule, "combo_config": os.path.join(folder, "no-combo.json"), "combo2_config": os.path.join(folder, "no-combo2.json"),
            "check_db": os.path.join(folder, "no-check.db"), "improve_db": os.path.join(folder, "no-improve.db"), "shadow_dir": folder}
    for k, v in W.env_of(p).items():
        monkeypatch.setenv(k, v)
    for k, v in W.env_more_of(more).items():
        monkeypatch.setenv(k, v)
    return {**p, **more, "folder": folder}


def _why(world, frames=None, **kw):
    args = {"bot": "paper", "symbol": "BTCUSDT", "entry": ENTRY, **kw}
    return Y.build(L.paths(), L.paths_more(), args["bot"], args["symbol"], args["entry"], frames if frames is not None else Frames(), now_ms=NOW)


# ================================================================ the answer
def test_the_signal_the_setting_and_where_it_came_from(world):
    d = _why(world)
    assert d["state"] == "ok" and d["bot"] == "paper" and d["bot_ko"]
    s = d["signal"]
    assert (s["strategy"], s["tf"], s["side"], s["bar_close"], s["order"]) == ("S2_ST_ROC", "1h", 1, ENTRY, 1)
    assert s["ref_price"] == 61990.0 and s["fill"] == 62000.0 and s["leverage"] == 40 and s["delay_ms"] == 4000
    assert s["source"] == "rule" and "규칙봇 신호 그대로" in s["source_ko"]
    assert s["score"] == pytest.approx(3.4) and s["score_used"] is False          # 규칙봇 15 ranks by the config's order
    st = d["setting"]
    assert st["group"] == "B" and st["no_chase"] and st["entry_ko"] == "즉시" and "순ROE -50%" in st["stop"]["ko"]
    assert d["rule"]["state"] == "ok" and d["rule"]["ask"] == 61990.0


def test_the_conditions_are_worked_out_again_on_the_signal_bar_and_kept(world):
    f = Frames()
    d = _why(world, f)
    c = d["conditions"]
    assert c["state"] == "ok" and c["side"] == 1 and c["side_ko"] == "롱" and not c["inverted"]
    assert c["items"] and all(set(x) == {"name", "on"} for x in c["items"]) and c["n_on"] == sum(x["on"] for x in c["items"])
    assert c["all_on"] == all(x["on"] for x in c["items"])
    assert c["values"] and all(isinstance(v["value"], float) for v in c["values"]) and "다시 계산" in c["note_ko"]
    want = D.view_bars("1h", "S2_ST_ROC")
    assert f.calls == [("BTCUSDT", "1h", want + 1 + 3)] and c["bars"] == want      # the window ends at the signal bar (one bar since)
    # a closed bar never changes: the second answer does not fetch again
    L._cache.clear()
    assert _why(world, f)["conditions"] == c and len(f.calls) == 1


def test_the_recheck_says_why_when_it_cannot(world):
    assert _why(world, Frames(drop_signal_bar=True))["conditions"] == {"state": "none", "reason_ko": "받은 바이낸스 봉에 신호 봉이 없어요"}
    Y._cond.clear()
    gone = _why(world, lambda *a: None)["conditions"]
    assert gone["state"] == "error" and "바이낸스 봉을 받지 못했어요" in gone["reason_ko"]

    def boom(*a):
        raise OSError("refused")
    err = _why(world, boom)["conditions"]
    assert err["state"] == "error" and "refused" in err["reason"]
    old = Y.recheck(Frames(), "S2_ST_ROC", "1h", "BTCUSDT", ENTRY, 1, False, ENTRY + (Y.SINCE_MAX_BARS + 5) * H)
    assert old["state"] == "old"
    assert Y.recheck(Frames(), "NO_SUCH_STRATEGY", "1h", "BTCUSDT", ENTRY, 1, False, NOW)["state"] == "none"


def test_the_chart_in_words_with_and_against_the_trade(world):
    c = _why(world)["chart"]
    assert c["state"] == "ok" and "설명용" in c["note_ko"]
    by = {x["k"]: x for x in c["items"]}
    assert by["장세 (이 봉)"]["v"] == "상승 추세" and by["장세 (이 봉)"]["tone"] == "good"
    assert by["장세 (상위 4시간봉)"]["v"] == "하락 추세" and by["장세 (상위 4시간봉)"]["tone"] == "bad"
    assert by["ADX 14"]["tone"] == "bad" and "추세 약함" in by["ADX 14"]["ko"]
    assert by["DI+ / DI−"]["tone"] == "good" and by["EMA20에서 거리"]["tone"] == "bad" and by["최근 범위 안 위치"]["v"] == "95%"
    # the loss cards' marks an entry alone decides; never the ones that read the exit or the old ladder
    assert set(c["tags"]) == {"상위 봉 추세 반대", "추세 약함 (ADX 20 미만)", "많이 오른/내린 뒤 추격", "최근 범위 끝에서 진입", "돌파 진입"}
    assert "수익 났다가 손절" not in c["tags"] and "저항 바로 앞 진입" not in c["tags"]


def test_the_checks_before_the_entry_with_their_numbers(world):
    xs = {x["id"]: x for x in _why(world)["checks"]}
    assert list(xs) == ["weekend", "macro", "usopen", "chase", "one"]
    assert xs["weekend"]["ok"] and "월요일" in xs["weekend"]["ko"]
    assert xs["macro"]["ok"] and xs["macro"]["detail"]["kind_ko"] and abs(xs["macro"]["detail"]["gap_ms"]) > 30 * MIN
    assert xs["usopen"]["ok"] and xs["one"]["ok"]
    ch = xs["chase"]
    assert ch["ok"] is True and ch["detail"]["chase"] is False and ch["detail"]["price"] == 61990.0
    assert ch["detail"]["d24"]["place"] == pytest.approx((61990 - 60000) / 2500) and ch["detail"]["d24"]["hours"] == 24
    assert ch["detail"]["d7"]["place"] == pytest.approx((61990 - 60000) / 3000) and ch["detail"]["d7"]["hours"] == 168
    assert ch["detail"]["limits"] == {"h24_hi": 0.9, "h24_lo": 0.1, "d7_hi": 0.8, "d7_lo": 0.2}


def test_the_other_signals_of_the_bar_the_record_and_the_five_years(world):
    d = _why(world)
    rv = d["rivals"]
    assert rv["state"] == "ok" and len(rv["rows"]) == 2
    lost = next(r for r in rv["rows"] if r["strategy"] == "OBV_S")
    assert lost["cat"] == "lost" and lost["ko"] == "같은 때 다른 신호에 밀림" and lost["symbol"] == "ETHUSDT"
    chase = next(r for r in rv["rows"] if r["strategy"] == "F15_ORB")
    assert chase["cat"] == "chase" and "24시간 고점 쪽" in chase["why_ko"]
    rec = d["record"]
    # before T0 + 9 h: the world's six closed trades; setting 1 (S2_ST_ROC 1h) is t1 (+20), the strategy t1, t3, t5
    assert rec["all"]["n"] == 6 and rec["setting"]["n"] == 1 and rec["setting"]["pnl"] == 20.0 and rec["strategy"]["n"] == 3
    assert d["five_year"]["state"] in ("ok", "missing", "error")
    if d["five_year"]["state"] == "ok":
        assert "낙관적" in d["five_year"]["note_ko"]


def test_an_entry_without_its_record_and_the_second_bot(world):
    none = _why(world, entry=ENTRY + MIN)
    assert none["state"] == "none" and "ENTERED" in none["reason_ko"]
    gone = _why(world, bot="paper2")
    assert gone["state"] == "missing"


def test_rule_bot_records_missing_say_so(world, monkeypatch):
    monkeypatch.setenv("PAPERBOT_LIVE_RULE_DB", os.path.join(world["folder"], "no-rule.db"))
    d = _why(world)
    assert d["state"] == "ok" and d["chart"]["state"] == "missing" and d["rule"]["state"] == "missing"
    ch = next(x for x in d["checks"] if x["id"] == "chase")
    assert ch["ok"] is None and ch["detail"]["state"] == "missing"


# ================================================================ the references on the cards and the rows
def test_the_position_cards_and_the_trade_rows_carry_the_reference(world):
    d = P.build(L.paths(), L.paths_more(), NOW)
    cards = {c["id"]: c for c in d["cards"]}
    assert cards["paper"]["position"]["why"] == {"bot": "paper", "symbol": "BTCUSDT", "entry": ENTRY}
    pos = cards["bybit"]["position"]
    assert pos["paired"] and pos["why"] == {"bot": "paper", "symbol": "BTCUSDT", "entry": ENTRY}     # the paper entry it followed
    assert (cards["flip"].get("position") or {}).get("why") is None
    t = L.trade_rows(L.paths(), NOW)
    prow = t["accts"]["paper"]["rows"][0]
    assert prow["why"] == {"bot": "paper", "symbol": prow["symbol"], "entry": prow["entry_time"]}
    matched = [r for r in t["accts"]["bybit"]["rows"] if r["paper"]]
    assert matched and all(r["why"] == {"bot": "paper", "symbol": r["symbol"], "entry": r["paper"]["entry_time"]} for r in matched)
    assert all(r["why"] is None for r in t["accts"]["bybit"]["rows"] if not r["paper"])


# ================================================================ the route on the live app
def test_the_live_app_serves_it_read_only(world, tmp_path):
    f = Frames()
    app = LA.create_app(D.hash_password(PW), SECRET, candles=lambda *a, **k: [], ticker=lambda: {}, market=lambda: {}, frames=f,
                        liq_db=str(tmp_path / "no-liq.db"), inbox_db=str(tmp_path / "no-inbox.db"))
    c = TestClient(app)
    assert c.get(f"/api/v4/livebots/why?bot=paper&symbol=BTCUSDT&entry={ENTRY}").status_code == 401
    assert c.post("/api/login", json={"password": PW}).status_code == 200
    before = os.path.getmtime(world["paper"])
    r = c.get(f"/api/v4/livebots/why?bot=paper&symbol=BTCUSDT&entry={ENTRY}")
    assert r.status_code == 200 and r.json()["state"] == "ok" and r.json()["conditions"]["state"] in ("ok", "error")
    assert c.get(f"/api/v4/livebots/why?bot=nope&symbol=BTCUSDT&entry={ENTRY}").status_code == 400
    assert c.get(f"/api/v4/livebots/why?bot=paper&symbol=XYZUSDT&entry={ENTRY}").status_code == 400
    assert os.path.getmtime(world["paper"]) == before
    assert "livewhy" in app.state.more and "livewhy" in LA.MODULES


# ================================================================ the panel in node
def _render(call: str, data) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    dom = "file://" + os.path.join(ROOT, "tests", "anasyn_dom.mjs")
    script = (f"const D = await import('{dom}');\n"
              "if (!Node.prototype.after) Node.prototype.after = function () {};\n"
              f"const Y = await import('file://{V4}/screens/livebots-why.js'); const X = await import('file://{V4}/screens/livebots-pos.js');\n"
              f"const d = {json.dumps(data)};\nconst out = ({call});\n"
              "console.log(JSON.stringify(out && out.childNodes ? D.walk(out) : {json: out}));")
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    if "text" in out:
        out["text"] = re.sub(r"\s+", " ", out["text"])
    return out


def test_the_panel_in_node(world):
    d = json.loads(json.dumps(D.json_finite(_why(world))))
    t = _render("Y.whyBody(d)", d)["text"]
    for word in ("어떤 신호였나", "1번 설정", "B그룹 (추격 진입 막기)", "즉시 진입", "순ROE -50%", "규칙봇 신호 그대로", "61,990.0 → 62,000.0", "봉 마감 4초 뒤 신호", "봉 마감 신호 → 18:00 진입",
                 "설정 순서로 골라요", "매매법 조건 (신호 봉에서)", "그때 차트", "상승 추세", "진입 방향과 반대 추세", "추세 약함 (ADX 20 미만)",
                 "진입 전에 통과한 검사", "주말 아님", "가장 가까운 발표", "추격 진입 막기 통과", "24시간 범위 80% 위치", "7일 범위 66% 위치",
                 "포지션이 비어 있었어요", "같은 때 나온 다른 신호", "같은 때 다른 신호에 밀림", "이 진입 전까지 성적", "이 설정: 1번 1승 0패",
                 "가장 가까운 발표: 소비자물가(CPI)", "슈퍼트렌드 상승", "ROC 0 위"):
        assert word in t, (word, t)
    assert "null" not in t and "undefined" not in t and "NaN" not in t
    bad = dict(d, conditions={"state": "error", "reason_ko": "바이낸스 봉을 받지 못했어요 (잠시 뒤 다시)"})
    assert "못 읽음" in _render("Y.whyBody(d)", bad)["text"]
    gone = _render("Y.whyBody({state: 'none', reason_ko: '이 진입의 신호 기록(ENTERED)이 페이퍼 DB에 없어요'})", None)["text"]
    assert "수집 전" in gone and "ENTERED" in gone
    assert _render("Y.whyUrl({bot: 'paper', symbol: 'BTCUSDT', entry: 5})", None)["json"] == "/api/v4/livebots/why?bot=paper&symbol=BTCUSDT&entry=5"
    assert _render("Y.whyUrl(null)", None)["json"] is None
    # the cards get the button with the screen's api, the rows of the 거래 tab too
    cards = json.loads(json.dumps(D.json_finite(P.build(L.paths(), L.paths_more(), NOW))))
    with_api = _render("X.posCard(d.cards[0], {api: async () => ({})})", cards)["text"]
    assert "진입 근거 보기" in with_api
    i = [c["id"] for c in cards["cards"]].index("bybit")
    assert "진입 근거 보기 (따라간 페이퍼 진입)" in _render(f"X.posCard(d.cards[{i}], {{api: async () => ({{}})}})", cards)["text"]
    assert "진입 근거" not in _render("X.posCard(d.cards[0])", cards)["text"]
    with open(os.path.join(V4, "screens", "livebots-trades.js"), encoding="utf-8") as fh:
        js = fh.read()
    assert "whyBox(ctx.api, r.why," in js
    with open(os.path.join(V4, "screens", "livebots.css"), encoding="utf-8") as fh:
        assert '@import url("livebots-why.css");' in fh.read()

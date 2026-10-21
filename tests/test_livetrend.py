"""실거래 › 관제 (#/trend, the live site's first screen since owners 10/21 "대시보드 다시 만들어야겠네 야무지게 필요한부분들 전부다
포함해서"; GET /api/v4/livebots/trend, dash/more/livetrend.py; screens/livebots-trend.js, livebots-trend.css).

On a paper database written by the trend bot's own code (tests/test_trendbot.py's world: TrendRunner, a fake judge):
- the answer: every coin's 1h / 4h judgment (the state ``trend``), the waits, the pauses, the last 24 h of signals by what
  became of them with the bot's own reason (되돌림 기다림 / 되돌림 확인 / 진입 신호 / 추세 판단 / 진입 자리 / 쉬기), the
  supervisor's exits with their reason, the rules; the bot (its start, the 2-week rule freeze, the heartbeat), the pause in
  force now, today's signal funnel, the ten members, the trades and the record since the bot started, the open position
  with the supervisor's view (the TIME deadline, the higher bar's judgment now);
- honest states: no file = missing, another bot running there (no ``trend`` in its start record) = off, no judgment yet =
  missing with the reason; the route is in the live site's modules and 관제 is its first tab;
- the view in node (the tiny DOM, the clock set to the world's): the hero, the wallets from the site's summary, the
  position and its guards, the trend map with the four judges, the waits, the funnel, the members, the record, the
  trades, the signal chips and rows, the supervisor exits; 꺼짐 / 수집 전 with the cards hidden; the pure helpers; then
  static checks of the js and the css."""
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
from paperbot.dash.more import livebots as L  # noqa: E402
from paperbot.dash.more import livetrend as LT  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENS = os.path.join(ROOT, "paperbot", "dash", "static", "v4", "screens")
JS = os.path.join(SCREENS, "livebots-trend.js")
CSS = os.path.join(SCREENS, "livebots-trend.css")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _world(tmp_path):
    """The trend bot ran: one entry after its pullback, one signal against the trend, one waiting, a JUDGE exit."""
    w = T.World(tmp_path)
    w.store.put_state("combo_run", T.T0, {"config": json.loads(json.dumps(C.dataclasses.asdict(w.cfg), default=str))})
    B, p = T._enter_long(w)
    w.judge.j[("BTCUSDT", "1h")] = T.J(dir=-1, votes={"V39": -1, "S6": -1, "OBV": -1, "N12": 1})
    T._to(w, B + 3 * T.MIN, T.T0 + T.HOUR)
    w.judge.j[("ETHUSDT", "1h")] = T.J(close=2500.0, ema20=2498.0, atr=12.5)           # ETH's 1h is still up: waits
    w.judge.s[("ETHUSDT", "30m")] = T.S(ema20=2500.0, atr=7.5)
    w.signal("F3_BOS", "ETHUSDT", 1, T.T0 + T.HOUR)
    w.step(T.T0 + T.HOUR)                                 # BTC's 1h turned: the supervisor closes the long
    w.store.commit()
    return w


def test_the_answer(tmp_path):
    w = _world(tmp_path)
    now = T.T0 + T.HOUR + 2 * T.MIN
    d = LT.build({"paper": w.cfg.db}, now)
    assert d["state"] == "ok" and d["name"] == "추세판단 봇" and d["ts"] == T.T0 + T.HOUR
    assert set(d["coins"]) == set(T.SYMS) and d["coins"]["BTCUSDT"]["1h"]["dir"] == -1
    assert d["coins"]["ETHUSDT"]["1h"]["text"].startswith("1시간 상승")
    (wt,) = d["waits"]
    assert wt["member"] == "F3_BOS@30m" and wt["symbol"] == "ETHUSDT"
    cats = [r["cat"] for r in d["signals"]["rows"]]
    assert cats[0] == "pullback_wait" and "entered" in cats and "pulled" in cats
    assert d["signals"]["counts"]["entered"] == 1 and d["signals"]["counts"]["pullback_wait"] == 1
    pulled = next(r for r in d["signals"]["rows"] if r["cat"] == "pulled")
    assert pulled["cat_ko"] == "되돌림 확인 (진입 신호로 바뀜)" and pulled["why"].startswith("되돌림 확인: ")
    (s,) = d["sup"]
    assert s["reason"] == "JUDGE" and s["reason_ko"] == "감독 청산(추세 뒤집힘)" and s["why"].startswith("1시간 판단이 하락로")
    assert d["rules"] == T.RULES.describe()
    # the bot, the pause now, today's funnel, the members, the trades and the record since the start
    assert d["bot"]["since"] == T.T0 and d["bot"]["freeze_until"] == T.T0 + 14 * 86_400_000 and d["bot"]["stale"] is False
    assert d["pause"] == {"paused": False, "why": None, "ko": "쉬는 시간 아님"} and d["position"] is None
    f = d["funnel"]
    assert (f["signals"], f["passed"], f["touched"], f["entered"], f["blocked"]) == (2, 2, 1, 1, [])
    cfg_members = json.loads(json.dumps(C.dataclasses.asdict(w.cfg), default=str))["members"]
    assert [m["label"] for m in d["members"]] == [f"{m['strategy']}@{m['tf']}" for m in cfg_members]
    btc = next(m for m in d["members"] if m["strategy"] == "N08_ICHI_WR")
    assert (btc["role"], btc["today"], btc["trades"], btc["losses"], btc["last"]["exit_reason"]) == ("눌림", 1, 1, 1, "JUDGE")
    (t,) = d["trades"]
    assert t["reason"] == "JUDGE" and t["entry_judge"].startswith("1시간 상승") and t["entry_score"] is not None
    r = d["record"]
    assert (r["n"], r["wins"], r["losses"]) == (1, 0, 1) and r["by_exit"][0]["id"] == "JUDGE" and r["pnl"] < 0


def test_the_open_position_and_the_supervisor(tmp_path):
    """Before the first lock the supervisor watches the higher bar's judgment and the TIME deadline (entry + 4 bars)."""
    w = T.World(tmp_path)
    w.store.put_state("combo_run", T.T0, {"config": json.loads(json.dumps(C.dataclasses.asdict(w.cfg), default=str))})
    B, p = T._enter_long(w)
    w.store.commit()
    now = B + 5 * T.MIN
    d = LT.build({"paper": w.cfg.db}, now)
    pos = d["position"]
    assert (pos["symbol"], pos["side"], pos["strategy"], pos["tf"], pos["htf"], pos["role"]) == ("BTCUSDT", 1, "N08_ICHI_WR", "30m", "1h", "눌림")
    assert pos["deadline"] == pos["entry_time"] + 4 * 30 * T.MIN and pos["time_left_ms"] == pos["deadline"] - now
    assert pos["locked"] is False and pos["supervised"] is True and pos["judge_against"] is False and pos["judge_exit"] is True
    assert pos["judge"]["dir"] == 1 and pos["entry_judge"].startswith("1시간 상승")
    assert next(m for m in d["members"] if m["strategy"] == "N08_ICHI_WR")["trades"] == 0      # open, not a trade yet


def test_the_pause_now():
    cfg = {"no_weekend": True, "macro_blackout_min": None, "us_open_pause_min": None}
    sat = T.T0 + 5 * 86_400_000                                   # 2026-10-10 09:00 KST, a Saturday
    x = LT.pause_now(cfg, sat)
    assert x["paused"] is True and x["why"] == "weekend" and x["until"] == T.T0 + 7 * 86_400_000 - 9 * T.HOUR
    assert LT.pause_now(cfg, T.T0)["paused"] is False and LT.pause_now({}, sat)["paused"] is False


def test_honest_states(tmp_path):
    assert LT.build({"paper": str(tmp_path / "none.db")})["state"] == "missing"
    s = Store3(str(tmp_path / "old.db"))
    s.put_state("combo_run", T.T0, {"config": {"name": "규칙봇 15", "trend": None}})
    s.commit()
    d = LT.build({"paper": str(tmp_path / "old.db")})
    assert d["state"] == "off" and "추세판단 봇이 아니에요" in d["reason_ko"]
    s.put_state("combo_run", T.T0, {"config": {"name": "추세판단 봇", "trend": {}}})
    s.commit()
    d = LT.build({"paper": str(tmp_path / "old.db")})
    assert d["state"] == "missing" and "첫 판단" in d["reason_ko"]
    s.close()


@pytest.mark.parametrize("status,why,cat", [
    ("WAITING", "되돌림 기다림: 59955까지(0.25 ATR, 10-05 09:30까지) · 1시간 상승(…)", "pullback_wait"),
    ("WAITING", "돌파 확인 대기", "waiting"),
    ("BROKE", "되돌림 확인: 59955 닿음 → 다음 분에 진입", "pulled"),
    ("FILTERED", "되돌림 안 옴(10-05 10:00까지 59955에 안 닿음)", "nopull"),
    ("FILTERED", "1시간 추세가 상승이라 숏 안 함(상승 3·하락 0·중립 1)", "trend"),
    ("FILTERED", "4시간 추세 끝물(ADX 44, 40 넘고 꺾임)", "trend"),
    ("FILTERED", "돌파형은 추세 초입만(ADX 33, 초입은 30 미만이고 오를 때)", "spot"),
    ("FILTERED", "1시간 EMA20에서 3.3 ATR 위(너무 뻗음, 1.5 넘음)", "spot"),
    ("FILTERED", "30분 RSI 71 과열(롱은 70 미만)", "spot"),
    ("FILTERED", "추세 판단을 못 읽어 진입 안 함: BTCUSDT 1시간 끝난 봉을 아직 못 받음", "trend_unread"),
    ("FILTERED", "하루 손실 한도: 오늘(한국 시간) 계좌 -35%라 오늘은 진입 안 함(한도 -30%)", "daily"),
    ("FILTERED", "N08_ICHI_WR 30분 손실 2번 연속: 10-06 08:00까지 쉼", "member_pause"),
    ("FILTERED", "BTC 롱 손실 뒤 2시간 쉼(10-05 11:30까지)", "coin_pause"),
    ("FILTERED", "추격 진입 막기: 롱인데 24시간 고점 쪽(95% 위치)", "chase"),
    ("FILTERED", "주말(한국 시간 토·일) 진입 안 함", "weekend"),
])
def test_why_categories(status, why, cat):
    assert L.why_cat(status, why)[0] == cat


def test_the_route_is_in_the_live_site():
    from paperbot.livedash import app as LA
    assert "livetrend" in LA.MODULES
    js = _read(os.path.join(SCREENS, "livebots.js"))
    assert 'import {trendView} from "./livebots-trend.js"' in js
    assert '{id: "trend", label: "관제", make: (ctx, hub) => trendView(ctx, hub), own: true}' in js
    assert js.index('{id: "trend", label: "관제"') < js.index('{id: "hq", label: "한눈에"') < js.index('{id: "pos"')
    routes = _read(os.path.join(ROOT, "paperbot", "dash", "static", "v4", "core", "routes.js"))
    assert 'export const LIVE_START = "trend";' in routes and '"now", ko: "지금", screens: ["trend", "hq", "pos"' in routes
    assert 'trend: {ko: "관제", group: "now"' in routes and 'hq: {ko: "한눈에", group: "now"' in routes
    assert '@import url("livebots-trend.css");' in _read(os.path.join(SCREENS, "livebots.css"))


# ---------------------------------------------------------------- the view in node
def _node(body: str, data) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    dom = "file://" + os.path.join(ROOT, "tests", "anasyn_dom.mjs")
    now = (data or {}).get("now_ms") or T.T0
    script = (f"Date.now = () => {int(now)};\nconst D = await import('{dom}');\nconst X = await import('file://{JS}');\n"
              f"const d = {json.dumps(data)};\nconst sum = {json.dumps(SUMMARY)};\n"
              "const tick = async () => { for (let i = 0; i < 3; i++) await new Promise((r) => setTimeout(r, 0)); };\n"
              + body)
    r = subprocess.run([node, "--input-type=module"], input=script, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


# the site's summary (GET /api/v4/livebots) as screens/livebots.js hands it in: the two executors and the paper
SUMMARY = {"accts": [
    {"id": "bybit", "kind": "live", "name_ko": "바이비트", "state": "ok", "balance": 101.5, "today": {"pnl": -1.25, "trades": 1},
     "halted": False, "stale": False, "position": None},
    {"id": "mexc", "kind": "live", "name_ko": "WOO X Pro", "state": "error", "reason_ko": "실행기 기록을 못 읽었어요"},
    {"id": "paper", "kind": "paper", "name_ko": "페이퍼(연습)", "state": "ok", "balance": 977.61}]}

VIEW = """const every = [];
const ctx = {api: () => Promise.resolve(d), every(ms, fn) { every.push({ms, fn}); }, watch() {}, alive: () => true,
  href: (n, a) => '#/' + n, track() {}};
const v = X.trendView(ctx, {get: () => sum});
await tick();
const w = D.walk(v.el);
const find = (n, c) => { if (!n || !n.childNodes) return null; if (String(n.className || "").split(" ").includes(c)) return n;
  for (const k of n.childNodes) { const f = find(k, c); if (f) return f; } return null; };
const now = Date.now();
console.log(JSON.stringify({text: w.text.replace(/\\s+/g, " "), classes: w.classes, ms: every.map((x) => x.ms),
  hidden: !!(find(v.el, "ltr-cards") || {}).hidden, hero: X.heroOf(d, now),
  cell: X.judgeCell({dir: 0, raw: 1, votes: {V39: 1, S6: 1, OBV: 1, N12: 0}, adx: 25, adx_prev: 24, strong: true}),
  na: X.judgeCell({error: "BTCUSDT 1시간 끝난 봉을 아직 못 받음"}), marks: [X.voteMark(1), X.voteMark(-1), X.voteMark(0)],
  order: X.countsInOrder({nopull: 2, entered: 1, zzz: 3, trend: 0}),
  allows: [X.allows({dir: 1, strong: true}, "1h"), X.allows({dir: -1, strong: true, tired: true}, "4h"), X.allows({dir: 0}, "1h"),
    X.allows({error: "x"}, "4h"), X.allows({dir: -1, strong: false}, "1h")],
  adx: [X.adxMeter(12), X.adxMeter(30), X.adxMeter(90), X.adxMeter(null)],
  gap: [X.waitGap({side: 1, level: 99}, 100), X.waitGap({side: -1, level: 101}, 100), X.waitGap({side: 1, level: 101}, 100), X.waitGap({side: 1}, 100)],
  freeze: [X.freezeKo({freeze_until: now + 11.5 * 86400000}, now), X.freezeKo({freeze_until: now - 1}, now), X.freezeKo(null, now)],
  clock: [X.clock(3723000), X.clock(725000), X.clock(59001), X.clock(-5), X.clock(null)]}));"""


def test_the_view(tmp_path):
    w = _world(tmp_path)
    d = json.loads(json.dumps(LT.build({"paper": w.cfg.db}, T.T0 + T.HOUR + 2 * T.MIN)))
    out = _node(VIEW, d)
    t, cls = out["text"], out["classes"]
    for bad in ("null", "undefined", "NaN", "[object"):
        assert bad not in t, bad
    for words in (
            # the hero: a pullback is waited for; the freeze, the start, the judgment's age, the pause
            "되돌림 기다리는 신호 1개", "ETH 롱", "닿으면 진입", "규칙 고정 D-14", "새 규칙 시작", "판단 2분 전", "쉬는 시간 아님",
            # the wallets: real money from the summary (unread said so), the paper never as real money, the new bot's record
            "바이비트 실거래", "$101.50", "오늘 −$1.25 · 1번", "WOO X Pro", "실행기 기록을 못 읽었어요", "페이퍼(연습) 지갑", "진짜 돈 아님",
            "0승 1패",
            # the position (none) and the two live accounts
            "포지션 · 감독", "포지션 없음", "실거래 두 계좌",
            # the trend map
            "추세 지도", "1시간 → 30분 진입", "4시간 → 1시간 진입", "BTC", "하락", "상승", "V3.9", "EMA·DMI·ADX", "일목·AO",
            "ADX 25 오름", "30분 롱만",
            # the waits and the pauses
            "되돌림 기다리는 신호", "쉬는 매매법 · 코인", "BTC 롱 손실 뒤 2시간 쉼",
            # today's funnel, the record, the members, the trades
            "오늘 신호 흐름", "검사 통과", "되돌림 닿음", "걸린 신호가 없어요", "새 봇 성적", "승률", "감독: 추세 뒤집힘 1번",
            "매매법 10개", "눌림", "돌파", "30분 진입 · 1시간 추세", "1시간 진입 · 4시간 추세", "거래 없음", "최근 거래", "감독(추세)",
            "진입 때 1시간 상승",
            # the signals, the supervisor's exits, the rules
            "최근 24시간 신호", "진입 신호 1", "되돌림 기다림 1", "감독 청산", "감독 청산(추세 뒤집힘)", "1시간 판단이 하락로 바뀜",
            "규칙", "추세 판단: 30분 진입은 끝난 1시간봉", "2단계(준비 중)"):
        assert words in t, words
    assert "시작 $1,000" not in t and t.count("하루 손실 한도") == t.count("하루 손실 한도 없음") == 1   # owners 10/21 #10
    assert any("ltr-cell down" in c for c in cls) and any("ltr-cell up" in c for c in cls) and "ltr-hero wait" in cls
    assert out["ms"] == [15000, 1000] and out["hidden"] is False
    assert out["hero"]["cls"] == "wait" and out["hero"]["head"] == "되돌림 기다리는 신호 1개"
    assert out["cell"] == {"cls": "hold", "word": "보류 (상승 유지 확인 중)", "sub": "상승 3·하락 0 · ADX 25 오름"}
    assert out["na"]["word"] == "못 읽음" and out["marks"] == ["▲", "▼", "–"]
    assert out["order"] == [{"id": "entered", "n": 1}, {"id": "nopull", "n": 2}, {"id": "zzz", "n": 3}]
    assert [a["ko"] for a in out["allows"]] == ["30분 롱만", "1시간 쉼 · 끝물", "30분 쉼 · 보류", "1시간 쉼 · 판단 못 읽음",
                                               "30분 쉼 · 힘 약함"]
    assert [a["side"] for a in out["allows"]] == [1, 0, 0, 0, 0]
    assert [a["zone"] for a in out["adx"]] == ["weak", "ok", "hot", "na"] and out["adx"][2]["fill"] == 1 and out["adx"][1]["fill"] == 0.5
    assert out["gap"] == [pytest.approx(0.01), pytest.approx(0.01), 0, None]
    assert out["freeze"][0]["days"] == 12 and out["freeze"][0]["ko"].startswith("규칙 고정 D-12 · ")
    assert out["freeze"][1]["days"] == 0 and "검토할 때예요" in out["freeze"][1]["ko"] and out["freeze"][2]["days"] is None
    assert out["clock"] == ["1:02:03", "12:05", "1:00", "0:00", "—"]


def test_the_view_with_an_open_position(tmp_path):
    w = T.World(tmp_path)
    w.store.put_state("combo_run", T.T0, {"config": json.loads(json.dumps(C.dataclasses.asdict(w.cfg), default=str))})
    B, _p = T._enter_long(w)
    w.store.commit()
    d = json.loads(json.dumps(LT.build({"paper": w.cfg.db}, B + 5 * T.MIN)))
    out = _node(VIEW, d)
    t = out["text"]
    for bad in ("null", "undefined", "NaN", "[object"):
        assert bad not in t, bad
    assert out["hero"]["cls"] == "hold" and out["hero"]["head"] == "BTC 롱 보유 중" and "시간 정리까지 1:" in out["hero"]["sub"]
    for words in ("BTC 롱 보유 중", "진입", "손절선", "순ROE −50%", "진입 근거", "1시간 상승", "⏱ 시간 정리", "진입 봉 4개 안에 첫 잠금",
                  "🧭 1시간 추세", "같은 방향 유지 중", "↩ 빠른 청산", "같은 매매법이 반대 신호를 내면 바로 청산", "실거래 두 계좌",
                  "포지션 없음 (안 따라갔거나 이미 닫음)"):
        assert words in t, words


def test_the_view_off_and_missing():
    out = _node(VIEW, {"state": "off", "reason_ko": "지금 돌고 있는 페이퍼 봇은 추세판단 봇이 아니에요 (설정에 추세 판단이 없음)"})
    assert "꺼짐" in out["text"] and "추세판단 봇이 아니에요" in out["text"] and out["hidden"] is True
    assert out["hero"]["cls"] == "na"
    out = _node(VIEW, {"state": "missing", "reason_ko": "추세판단 봇이 아직 첫 판단을 기록하지 않았어요 (켠 뒤 1~2분)"})
    assert "수집 전" in out["text"] and "첫 판단" in out["text"] and out["hidden"] is True


def test_static():
    node = shutil.which("node")
    if node is not None:
        r = subprocess.run([node, "--check", JS], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
    css = re.sub(r"/\*.*?\*/", "", _read(CSS), flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css) and not re.search(r"font-size:\s*\d", css)
    assert '"/api/v4/livebots/trend"' in _read(JS) and "export function trendView" in _read(JS)

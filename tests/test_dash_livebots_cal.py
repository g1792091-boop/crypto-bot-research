"""실거래 › 일정 (#/livebots/cal; screens/livebots-cal.js, /api/v4/livebots/calendar = dash/more/livebots.py calendar).

The calendar answer is built on the hand-made live world (tests/livebots_world.py) with a fixed list of US releases (the real
data/macro_events.csv is never read here, so the tests do not move when the owners add dates), then the page's pure
functions run on it in node: the countdown and time words (Korea time), the pause now (worked out again every second
between two answers, windows that touch run on), the 7-day ribbon (windows cut to Korea-time days, label lanes, the past
part of today), the week in numbers, the file's coverage warning and the market tiles (a source that failed says
'못 받음', never a zero). The view is drawn in the tiny DOM (tests/anasyn_dom.mjs): the hero, the cards, the market line
when /api/market fails, the error box when the calendar fails. Static checks: tokens only in the css, every font size a
--t-* token, reduced motion, the route, no outside address written in the page, timers only through ctx.every.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from calendar import timegm

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import livebots_world as W  # noqa: E402
from paperbot import events as EV  # noqa: E402
from paperbot.dash.app import json_finite  # noqa: E402
from paperbot.dash.more import livebots as L  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
SCREENS = os.path.join(V4, "screens")
JS = os.path.join(SCREENS, "livebots-cal.js")
CSS = os.path.join(SCREENS, "livebots-cal.css")
MIN, H, DAY, KST = 60_000, 3_600_000, 86_400_000, 9 * 3_600_000


def kst(y, mo, d, hh=0, mi=0, ss=0):
    return timegm((y, mo, d, hh, mi, ss)) * 1000 - KST


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


FED = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
BEA = "https://www.bea.gov/news/schedule"
BLS = "https://www.bls.gov/schedule/news_release/empsit.htm"
CPI = "https://www.bls.gov/schedule/news_release/cpi.htm"
EVENTS = [EV.Event(kst(2026, 10, 14, 21, 30), "CPI", CPI),       # 15 days back: not on the page
          EV.Event(kst(2026, 10, 27, 21, 30), "CPI", CPI),       # 2 days back: dimmed
          EV.Event(kst(2026, 10, 29, 3, 0), "FOMC", FED),        # now (its pause 02:30~03:30)
          EV.Event(kst(2026, 10, 29, 21, 30), "PCE", BEA),       # the same day, the evening
          EV.Event(kst(2026, 11, 6, 22, 30), "NFP", BLS),
          EV.Event(kst(2026, 12, 23, 22, 30), "PCE", BEA)]       # the last registered date
NOW = kst(2026, 10, 29, 2, 50)                                   # Thursday, inside the FOMC pause


@pytest.fixture
def answer(tmp_path, monkeypatch):
    """calendar(p, now) on the live world with the fixed releases (the bot's config: 30 minutes, no weekend entries)."""
    p = W.build_world(str(tmp_path / "w"))
    monkeypatch.setenv("PAPERBOT_LIVE_COMBO_CONFIG", str(tmp_path / "none.json"))
    monkeypatch.setattr(EV, "all_events", lambda: list(EVENTS))
    probs = []
    monkeypatch.setattr(EV, "problems", lambda: list(probs))

    def make(now=NOW, problems=()):
        probs[:] = list(problems)
        return json_finite(L.calendar(p, now))
    return make


def _node(body: str, data=None) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    dom = "file://" + os.path.join(ROOT, "tests", "anasyn_dom.mjs")
    script = (f"const D = await import('{dom}');\n"
              f"const C = await import('file://{JS}');\n"
              f"const d = {json.dumps(data)};\n" + body)
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------- the answer the page reads
def test_the_answer_the_page_reads(answer):
    d = answer()
    assert d["rules"] == {"macro_blackout_min": 30, "no_weekend": True} and d["combo"]["state"] == "ok"
    assert d["now"]["paused"] is True and d["now"]["macro"]["kind"] == "FOMC" and d["now"]["pause_until"] == kst(2026, 10, 29, 3, 30)
    assert [(x["kind"], x["when"]) for x in d["items"]] == [("CPI", "past"), ("FOMC", "now"), ("PCE", "soon"), ("NFP", "later")]
    # the pause windows of the next 7 days, earliest first: today's two releases, then the weekend (NFP is 8 days away)
    assert [(s["why"], s.get("kind")) for s in d["spans"]] == [("macro", "FOMC"), ("macro", "PCE"), ("weekend", None)]
    assert d["spans"][2] == {"from": kst(2026, 10, 31), "to": kst(2026, 11, 2), "why": "weekend", "ko": "주말(토·일, 한국 시간)"}
    assert d["events"]["low"] is False and d["events"]["last_ms"] == kst(2026, 12, 23, 22, 30)
    assert answer(kst(2026, 11, 20, 20, 40))["events"]["low"] is True                 # 33 days left: under 45


# ---------------------------------------------------------------- pure functions in node
def test_time_words_korea_time():
    out = _node("""console.log(JSON.stringify({
      clock: [C.clockKo(3723000), C.clockKo(86400000 + 1000), C.clockKo(999), C.clockKo(0), C.clockKo(null)],
      parts: C.clockParts(90061000),
      dur: [C.durKo(30000), C.durKo(61 * 60000), C.durKo(60 * 60000), C.durKo(51 * 3600000), C.durKo(48 * 3600000), C.durKo(90 * 1000), C.durKo(undefined)],
      until: [C.untilKo(d.now + 3 * 3600000 + 12 * 60000, d.now), C.untilKo(d.now + 8 * 86400000, d.now), C.untilKo(d.now - 1, d.now), C.untilKo(d.now + 30 * 60000, d.now)],
      day: [C.dayKo(d.now), C.wdKo(d.sat), C.isWeekendDay(d.sat), C.isWeekendDay(d.now), C.relDay(d.now + 86400000, d.now), C.relDay(d.now, d.now)],
      range: [C.rangeKo(d.a, d.b), C.rangeKo(d.sat, d.mon), C.rangeKo(null, 1)],
      pause: [C.pauseKo({pause_from: d.a, pause_to: d.b, weekend: false}, {no_weekend: true}),
              C.pauseKo({pause_from: d.a, pause_to: d.b, weekend: true}, {no_weekend: true}),
              C.pauseKo({pause_from: d.a, pause_to: d.b, weekend: true}, {no_weekend: false}),
              C.pauseKo({pause_from: null, pause_to: null, weekend: false}, {no_weekend: true})],
      when: [C.whenAt({ts: d.now + 10 * 60000, pause_from: d.now - 20 * 60000, pause_to: d.now + 40 * 60000}, d.now),
             C.whenAt({ts: d.now + 5 * 3600000, pause_from: d.now + 4.5 * 3600000, pause_to: d.now + 5.5 * 3600000}, d.now),
             C.whenAt({ts: d.now + 30 * 3600000, pause_from: d.now + 29.5 * 3600000, pause_to: d.now + 30.5 * 3600000}, d.now),
             C.whenAt({ts: d.now - 3600000, pause_from: d.now - 5400000, pause_to: d.now - 1800000}, d.now)],
    }));""", {"now": NOW, "sat": kst(2026, 10, 31, 12), "mon": kst(2026, 11, 2), "a": kst(2026, 10, 29, 21), "b": kst(2026, 10, 29, 22)})
    assert out["clock"] == ["01:02:03", "1일 00:00:01", "00:00:01", "00:00:00", "—"]     # seconds rounded up: 0 only when over
    assert out["parts"] == {"d": 1, "h": 1, "m": 1, "s": 1}
    assert out["dur"] == ["30초", "1시간 1분", "1시간", "2일 3시간", "2일", "2분", "—"]
    assert out["until"] == ["3시간 12분 뒤", "D-8", "지남", "30분 뒤"]
    assert out["day"] == ["10/29 (목)", "토", True, False, "내일", "오늘"]
    assert out["range"] == ["10/29 (목) 21:00~22:00", "10/31 (토) 12:00 ~ 11/02 (월) 00:00", "—"]
    assert out["pause"] == ["21:00~22:00 진입 쉼", "주말이라 원래 쉼", "21:00~22:00 진입 쉼", "발표 앞뒤에 쉬지 않음 (봇 설정)"]
    assert out["when"] == ["now", "soon", "later", "past"]


def test_the_pause_now_worked_out_every_second(answer):
    d = answer()
    t = {"now": NOW, "open": kst(2026, 10, 29, 3, 31), "edge": kst(2026, 10, 29, 3, 30), "sat": kst(2026, 10, 31, 12), "pce": kst(2026, 10, 29, 21, 0)}
    out = _node(f"""const t = {json.dumps(t)};
    const pick = (x) => ({{paused: x.paused, until: x.until, from: x.from, ko: x.ko, said: x.said ?? null, after: x.after.length, next: x.next && [x.next.from, x.next.to, x.next.ko],
      progress: x.progress == null ? null : Math.round(x.progress * 1000) / 1000}});
    // a release right after the weekend: its window touches the weekend's end, so the pause runs on to its end
    const chain = {{...d, spans: [{{from: t.sat - 12 * 3600000, to: t.sat + 36 * 3600000, why: "weekend", ko: "주말"}},
      {{from: t.sat + 36 * 3600000, to: t.sat + 37 * 3600000, why: "macro", kind: "CPI", ko: "소비자물가(CPI) 앞뒤 30분"}}]}};
    console.log(JSON.stringify({{now: pick(C.stateAt(d, t.now)), open: pick(C.stateAt(d, t.open)), edge: pick(C.stateAt(d, t.edge)),
      sat: pick(C.stateAt(d, t.sat)), pce: pick(C.stateAt(d, t.pce)), chain: pick(C.stateAt(chain, t.sat)),
      merged: C.mergeSpans(chain.spans).map((m) => [m.from, m.to, m.parts.length]),
      old: pick(C.stateAt({{...d, spans: undefined}}, t.now)), last: C.lastPauseEnd(d, t.open)}}));""", d)
    fomc, pce = (kst(2026, 10, 29, 2, 30), kst(2026, 10, 29, 3, 30)), (kst(2026, 10, 29, 21), kst(2026, 10, 29, 22))
    assert out["now"]["paused"] and out["now"]["until"] == fomc[1] and out["now"]["from"] == fomc[0]
    assert out["now"]["ko"] == "FOMC 금리 결정 발표(03:00) 앞뒤 30분" and out["now"]["progress"] == pytest.approx(20 / 60, abs=1e-3)
    assert out["now"]["next"] == [pce[0], pce[1], "PCE 물가 발표 앞뒤 30분"]
    assert out["edge"]["paused"] is False and out["open"]["paused"] is False                # the window ends at 03:30
    assert out["open"]["next"][0] == pce[0] and out["last"] == fomc[1]
    assert out["open"]["progress"] == pytest.approx(1 / (17.5 * 60), abs=1e-3)             # 1 minute of the 17.5 hours to 21:00
    assert out["pce"]["paused"] and out["pce"]["until"] == pce[1]
    assert out["sat"] == {**out["sat"], "paused": True, "until": kst(2026, 11, 2), "ko": "주말(토요일 0시 ~ 월요일 0시, 한국 시간)"}
    assert out["chain"]["paused"] and out["chain"]["until"] == kst(2026, 11, 2, 1) and out["chain"]["after"] == 1
    assert out["merged"] == [[kst(2026, 10, 31), kst(2026, 11, 2, 1), 2]]
    # an answer without spans (an older server): the server's own now fields and words
    assert out["old"]["paused"] and out["old"]["until"] == fomc[1] and out["old"]["said"] == "FOMC 금리 결정 발표 앞뒤 30분이라 진입 쉬는 중"


def test_the_ribbon_rows_and_the_week(answer):
    d = answer()
    out = _node("""const rows = C.dayRows(d.spans, d.now_ms, 7);
    const cross = C.clipSpan({from: d.mid - 3600000, to: d.mid + 3600000, why: "macro", kind: "CPI"}, d.mid, d.mid + 86400000);
    const close = C.laneTags([{why: "macro", from: 1, l: 0.40, w: 0.04}, {why: "macro", from: 2, l: 0.45, w: 0.04}, {why: "macro", from: 3, l: 0.9, w: 0.04}]);
    console.log(JSON.stringify({rows: rows.map((r) => ({label: r.label, rel: r.rel, wk: r.weekend, full: r.full, pause: r.pauseMs, lanes: r.lanes, ko: C.rowKo(r),
        now: r.nowAt == null ? null : Math.round(r.nowAt * 10000) / 10000, blocks: r.blocks.map((b) => [b.why, b.kind, Math.round(b.l * 1e4) / 1e4, Math.round(b.w * 1e4) / 1e4, b.lane ?? null])})),
      cross: [cross.l, cross.w, cross.cutL, cross.cutR], lanes: close.map((b) => b.lane), none: C.clipSpan({from: 0, to: 10}, 20, 30),
      week: C.weekSummary(d.spans, d.now_ms, 7)}));""", {**d, "mid": kst(2026, 10, 30)})
    rows = out["rows"]
    assert [r["label"] for r in rows] == ["10/29 (목)", "10/30 (금)", "10/31 (토)", "11/01 (일)", "11/02 (월)", "11/03 (화)", "11/04 (수)"]
    assert [r["rel"] for r in rows[:3]] == ["오늘", "내일", None] and [r["wk"] for r in rows] == [False, False, True, True, False, False, False]
    today = rows[0]
    assert today["now"] == pytest.approx((2 * 60 + 50) / 1440, abs=1e-4) and all(r["now"] is None for r in rows[1:])
    assert today["blocks"] == [["macro", "FOMC", round(2.5 / 24, 4), round(1 / 24, 4), 0], ["macro", "PCE", round(21 / 24, 4), round(1 / 24, 4), 0]]
    assert today["pause"] == 2 * H and today["ko"] == "2시간 쉼 · 2번" and today["lanes"] == 1
    assert rows[2]["full"] and rows[2]["ko"] == "하루 종일 쉼" and rows[2]["blocks"] == [["weekend", None, 0, 1, None]]
    assert rows[1]["ko"] == "쉬는 시간 없음" and rows[1]["lanes"] == 0
    assert out["cross"] == [0, 1 / 24, True, False] and out["none"] is None
    assert out["lanes"] == [0, 1, 0]                                                        # two close labels never overlap
    w = out["week"]
    assert w["pauseMs"] == 40 * MIN + H + 2 * DAY and w["weekendMs"] == 2 * DAY and w["macroN"] == 2 and w["macroMs"] == 100 * MIN
    assert w["share"] == pytest.approx(w["pauseMs"] / (7 * DAY))


def test_coverage_warning_and_market_tiles(answer):
    d, low = answer(), answer(kst(2026, 11, 20, 20, 40))
    market = {"fng": {"now": {"value": 38, "label": "Fear", "label_ko": "공포"}, "stale": True},
              "global": {"btc_dom": 57.42, "eth_dom": 12.08, "total_mcap": 3.42e12, "mcap_chg_24h": -1.23},
              "indexes": [{"symbol": "^IXIC", "name": "나스닥", "price": 18342.12, "chg": 0.0078, "points": [[1, 18000], [2, 18342.12]]},
                          {"symbol": "^TNX", "name": "미국 10년 금리", "price": 4.123, "chg": -0.0065, "points": []},
                          {"symbol": "^GSPC", "name": "S&P 500", "error": "HTTPError"}]}
    out = _node(f"""const low = {json.dumps(low)}, m = {json.dumps(market)};
    console.log(JSON.stringify({{ok: C.coverageKo(d.events, d.now_ms), low: C.coverageKo(low.events, low.now_ms),
      none: C.coverageKo({{state: "ok", low: true, last_ms: null}}, d.now_ms), err: C.coverageKo({{state: "error", low: true}}, d.now_ms),
      mid: C.coverageKo({{state: "ok", low: true, last_ms: {kst(2027, 6, 30, 21, 30)}, low_days: 45}}, {kst(2027, 6, 1)}),
      tiles: C.marketTiles(m), empty: C.marketTiles(null), gone: C.marketTiles({{fng: {{error: "URLError"}}, global: {{error: "URLError"}}, indexes: []}})}}));""", d)
    assert out["ok"] is None
    assert out["low"] == "등록된 일정이 12월 23일 (수)까지예요 · 내년 일정을 넣어야 해요"
    assert out["mid"] == "등록된 일정이 6월 30일 (수)까지예요 · 다음 일정을 넣어야 해요"
    assert out["none"] == "등록된 경제 발표 일정이 없어요 · 일정을 넣어야 해요" and out["err"] is None
    t = {x["id"]: x for x in out["tiles"]}
    assert list(t) == ["fng", "dom", "mcap", "ix:^IXIC", "ix:^TNX", "ix:^GSPC"]
    assert (t["fng"]["v"], t["fng"]["sub"], t["fng"]["tone"], t["fng"]["stale"], t["fng"]["gauge"]) == ("38", "공포", "down", True, 0.38)
    assert t["dom"]["v"] == "57.4%" and t["dom"]["sub"] == "이더리움 12.1%"
    assert t["mcap"]["v"] == "3.42조 달러" and t["mcap"]["sub"] == "24시간 −1.23%" and t["mcap"]["tone"] == "down"
    assert t["ix:^IXIC"]["v"] == "18,342.12" and t["ix:^IXIC"]["sub"] == "+0.78%" and t["ix:^IXIC"]["points"] == [18000, 18342.12]
    assert t["ix:^TNX"]["v"] == "4.123%" and t["ix:^TNX"]["tone"] == "down"
    assert t["ix:^GSPC"] == {"id": "ix:^GSPC", "k": "S&P 500", "miss": True, "err": "HTTPError"}       # never a zero
    assert out["empty"] == [] and [x.get("miss") for x in out["gone"]] == [True, True, True]


# ---------------------------------------------------------------- the view in the tiny DOM
def _has(classes: str, name: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", classes) is not None


def _view(d, market, fail=None):
    body = f"""const market = {json.dumps(market)}, fail = {json.dumps(fail)};
    const ctx = {{alive: () => true, every() {{}}, track() {{}}, timeout() {{}}, listen() {{}}, on() {{}}, href: () => "#",
      api: async (path) => {{ if (fail && fail.includes(path)) {{ const e = new Error("x"); e.status = 500; throw e; }}
        return path === C.API ? d : market; }}}};
    const v = C.calView(ctx);
    await new Promise((r) => setTimeout(r, 30));
    const w = D.walk(v.el);
    console.log(JSON.stringify({{text: w.text.replace(/\\s+/g, " "), classes: w.classes.join(" ")}}));"""
    return _node(body, d)


def test_the_view_draws_the_hero_ribbon_cards_and_market(answer):
    d = answer()
    market = {"fng": {"now": {"value": 61, "label": "Greed", "label_ko": "탐욕"}}, "global": {"btc_dom": 57.4}, "indexes": []}
    out = _view(d, market)
    txt, cls = out["text"], out["classes"]
    assert "진입 쉬는 중" in txt and "FOMC 금리 결정 발표(03:00) 앞뒤 30분이라 새 진입을 쉬어요" in txt
    assert "다시 진입할 수 있을 때까지" in txt and "10/29 (목) 03:30에 다시 열려요" in txt and "00:40:00" in txt
    assert "다음 쉬는 시간" in txt and "PCE 물가 발표 앞뒤 30분" in txt and "10/29 (목) 21:00~22:00" in txt
    assert "봇이 스스로 지키는 규칙이에요." in txt and "거래소에 걸어 둔 손절 주문이 지켜요" in txt
    assert "주말 진입 안 함 · 토 0시 ~ 월 0시" in txt and "경제 발표 앞뒤 30분 진입 안 함" in txt
    assert "lbc-hero paused" in cls and "lbc-hero open" not in cls
    # the ribbon: 7 rows, today's two release blocks with their labels, the weekend striped, the now mark
    assert cls.count("lbc-row") == 7 and cls.count("lbc-blk macro") == 2 and cls.count("lbc-blk weekend") == 2 and "lbc-now" in cls
    assert "FOMC" in txt and "PCE" in txt and "하루 종일 쉼" in txt and "2시간 쉼 · 2번" in txt
    # the cards: the FOMC one now, PCE soon, NFP later, the past CPI dimmed under its own line
    assert "lbc-rel w-now k-fomc" in cls and "lbc-rel w-soon k-pce" in cls and "lbc-rel w-later k-nfp" in cls and "lbc-rel w-past k-cpi" in cls
    assert "지금 쉬는 중" in txt and "02:30~03:30 진입 쉼" in txt and "18시간 40분 뒤" in txt and "D-8" in txt and "지난 3일 · 1개" in txt
    assert "federalreserve.gov" in txt and "공식 일정" in txt
    # the market tiles and the honest news line; no coverage warning (55 days left)
    assert "공포·탐욕" in txt and "탐욕" in txt and "57.4%" in txt and not _has(cls, "lbc-cover")
    assert "뉴스는 아직 연결하지 않았어요 · 봇은 뉴스를 보지 않고 위 일정만 지켜요" in txt
    assert not re.search(r"\b(null|undefined|NaN)\b", txt)


def test_the_view_says_what_failed(answer):
    d = answer(kst(2026, 11, 20, 20, 40), problems=["line 17: bad ts_utc 'x'"])
    out = _view(d, None, fail=["/api/market"])
    txt = out["text"]
    assert "지금은 진입할 수 있는 시간" in txt and "lbc-hero open" in out["classes"]
    assert "등록된 일정이 12월 23일 (수)까지예요 · 내년 일정을 넣어야 해요" in txt and "line 17: bad ts_utc 'x'" in txt
    assert "시장 숫자를 못 읽었어요 (서버 오류 500) · 5분 뒤 다시 읽어요" in txt and not _has(out["classes"], "lbc-tile")   # one muted line, never 0
    out = _view(d, None, fail=["/api/v4/livebots/calendar"])
    assert "불러오지 못했습니다" in out["text"] and "errbox" in out["classes"]


# ---------------------------------------------------------------- static: tokens, type scale, motion, route, outside addresses, timers
def test_static_rules():
    css = re.sub(r"/\*.*?\*/", "", _read(CSS), flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css) and not re.search(r"\b(rgba?|hsla?)\(\s*\d", css)
    assert not re.search(r"font-size:\s*\d", css)
    for v in re.findall(r"font-size:\s*([^;}]+)", css):
        assert v.strip().startswith("var(--t-"), v
    for v in re.findall(r"(?<![-\w])font:\s*([^;}]+)", css):
        size = re.sub(r"^(?:(?:italic|normal|bold|\d00)\s+)*", "", v.strip())
        assert size.startswith(("var(--t-", "inherit")), v
    motion = css[css.index("prefers-reduced-motion"):]
    assert "animation: none" in motion and "lbc-flip" in motion and ".lbc-now::after" in motion
    for sel in re.findall(r"([^{}]+)\{", css):                          # every rule is this screen's own (prefix lbc-)
        sel = sel.strip()
        if sel.startswith("@") or re.fullmatch(r"[\d%,\s]+|from|to", sel):
            continue
        assert all(".lbc" in part for part in sel.split(",")), sel
    js = _read(JS)
    assert '"/api/v4/livebots/calendar"' in js and '"/api/market"' in js
    assert "https://" not in js and "http://" not in js                 # official links come from the server's file only
    assert 'target: "_blank", rel: "noopener"' in js
    assert "setInterval" not in js and "setTimeout" not in js           # timers only through ctx.every (the router stops them)
    assert re.search(r"ctx\.every\(REFRESH_MS,", js) and re.search(r"ctx\.every\(TICK_MS,", js) and "const REFRESH_MS = 60 * 1000;" in js
    assert "const TICK_MS = 1000;" in js and "serverNow()" in js
    assert re.findall(r'^import .* from "([^"]+)";', js, flags=re.M) == ["../core/pb.js", "./livebots-kit.js"]
    for bad in ("innerHTML", "insertAdjacentHTML", "toLocaleString", "Intl.NumberFormat", "localStorage"):
        assert bad not in js, bad
    assert '@import url("livebots-cal.css");' in _read(os.path.join(SCREENS, "livebots.css"))

"""실거래 › 순위 (#/livebots/rank; screens/livebots-rank.js on /api/v4/livebots/rank, dash/more/livebots.py rank()).

The page sorts; the server ranks nothing. Its pure functions run in node on real answers of hand-made worlds
(tests/livebots_world.py, every database made by the bots' own schema code):
- the rich world: 2 strategies in the config with paper trades (one holds the open position), 3 traded under an earlier
  config ("지금 설정 밖": listed last, never ranked)
- day 1 on the production config (deploy/combo.live-ac.json: 27 strategies, 95 settings): no trade yet, so the order is the
  5-year contribution and the page says so; no strategy gets a rank in 손익 / 승률 (never a 0 for what nobody has)
- a source that cannot be read: its numbers are unknown (못 읽음), never 0
Then the view itself in the tiny DOM (tests/anasyn_dom.mjs) and static checks of the css (tokens only, --t-* sizes, no
endless motion, reduced motion) and the js (the endpoint, no HTML parsing, no number formatting of its own).
"""
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

pytest.importorskip("fastapi")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import livebots_world as W  # noqa: E402
from paperbot.dash.app import json_finite  # noqa: E402
from paperbot.dash.more import livebots as L  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
SCREENS = os.path.join(V4, "screens")
JS = os.path.join(SCREENS, "livebots-rank.js")
CSS = os.path.join(SCREENS, "livebots-rank.css")
NOW = W.NOW


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PAPERBOT_LIVE_COMBO_CONFIG", "/nonexistent")      # the config the bot runs comes from its database
    L._cache.clear()
    yield
    L._cache.clear()


@pytest.fixture
def rich(tmp_path, monkeypatch):
    folder = str(tmp_path / "w")
    p = W.build_world(folder)
    for k, v in W.env_more_of(W.live_checks(p, folder, rich=True)).items():
        monkeypatch.setenv(k, v)
    return json_finite(L.rank(p, NOW))


PROD = json.loads(_read(os.path.join(ROOT, "deploy", "combo.live-ac.json")))


def _day1(folder: str) -> dict:
    """The live start: the paper database of the production config with no trade and no position, two filtered signals."""
    from paperbot.models import Signal  # noqa: F401  (the store's shapes)
    from paperbot.store3 import Store3
    p = W.build_world(folder)
    os.remove(p["paper"])
    s = Store3(p["paper"])
    s.add_account(W.ACCOUNT, "combo", "mix", "combo", W.T0, "combo-v2")
    first = PROD["members"][0]["strategy"]
    other = next(i for i, m in enumerate(PROD["members"]) if m["strategy"] != first)
    for k, t in ((0, NOW - W.H), (other, NOW - 2 * W.H)):                  # two strategies, one signal each
        m = PROD["members"][k]
        s.log_signals([{"bar_close": t, "timeframe": m["tf"], "strategy": f"{m['strategy']}@{m['tf']}#{k + 1}~prod", "symbol": "ETHUSDT",
                        "side": 1, "atr": 1.0, "ref_price": 100.0, "ref_time": t, "delay_ms": 800, "status": "FILTERED",
                        "data": {"source": "custom", "strategy": m["strategy"], "why": "끈 구간: hr=5"}}])
    s.put_state("accounts", NOW - W.MIN, {"last_ts": NOW - W.MIN, "engines": {W.ACCOUNT: {
        "wallet": 1000.0, "peak_equity": 1000.0, "max_drawdown": 0.0, "halted": False, "halt_reason": "", "bust": False, "warned": [],
        "last_mark": {}, "position": None, "pending": [], "n_trades": 0}}})
    cfg = {k: v for k, v in PROD.items() if k not in ("paper_db", "db", "telegram")}
    s.put_state("combo_run", W.T0, {"version": "combo-v2", "taker_fee": 0.0005, "members": [], "config": cfg})
    s.close()
    return p


@pytest.fixture
def day1(tmp_path):
    return json_finite(L.rank(_day1(str(tmp_path / "d1")), NOW))


def _node(body: str, data) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    dom = "file://" + os.path.join(ROOT, "tests", "anasyn_dom.mjs")
    script = (f"const D = await import('{dom}');\nconst R = await import('file://{JS}');\nconst {{fmt}} = await import('file://{V4}/core/pb.js');\n"
              f"const d = {json.dumps(data)};\n{body}")
    r = subprocess.run([node, "--input-type=module"], input=script, capture_output=True, text=True, timeout=60)     # stdin: big answers
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_node_check():
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    r = subprocess.run([node, "--check", JS], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr


# ---------------------------------------------------------------- the pure functions on the rich world
def test_rich_world_ranks_the_config_by_paper_pnl_and_lists_the_earlier_config_last(rich):
    rows = {r["strategy"]: r for r in rich["rows"]}
    assert rows["S2_ST_ROC"]["open"] and rows["S2_ST_ROC"]["paper"]["n"] == 3 and rows["N03_ADX_GC"]["paper"]["n"] == 17
    out = _node("""const ok = R.sources(d), at = (s) => R.rankRows(d.rows, s, ok);
    const ids = (res) => ({ranked: res.ranked.map((x) => [x.r.strategy, x.rank]), un: res.unranked.map((x) => x.r.strategy), out: res.out.map((x) => [x.r.strategy, x.rank])});
    const s2 = d.rows.find((r) => r.strategy === "S2_ST_ROC"), n03 = d.rows.find((r) => r.strategy === "N03_ADX_GC");
    console.log(JSON.stringify({pick: R.pickSort(null, d), pickWin: R.pickSort("win", d), bogus: R.pickSort("nope", d).sort,
      pnl: ids(at("pnl")), win: ids(at("win")), trades: ids(at("trades")), sig: ids(at("signals")), contrib: ids(at("contrib")),
      list: R.listOrder(at("pnl")).map((x) => x.r.strategy), decks: R.decks(at("pnl").ranked),
      big: R.bigOf(s2, "pnl", ok), bigWin: R.bigOf(s2, "win", ok), bigC: R.bigOf(s2, "contrib", ok), bigSig: R.bigOf(n03, "signals", ok),
      bars: R.barsOf(n03, ok), bars2: R.barsOf(s2, ok), counts: R.counts(d), why: R.whyLine(n03), why2: R.whyLine(s2),
      off: R.offGroups(s2.members[0].off), match: [R.matches(n03, "adx", fmt.stratKo), R.matches(n03, "추세", fmt.stratKo), R.matches(s2, "adx", fmt.stratKo)],
      same: R.sameKey(d) === R.sameKey({...d, now_ms: 1}), diff: R.sameKey(d) === R.sameKey({...d, n_settings: 4})}));""", rich)
    assert out["pick"] == {"sort": "pnl", "chosen": "pnl", "fallback": False, "traded": True, "note": None}
    assert out["pickWin"]["sort"] == "win" and out["bogus"] == "pnl"
    # 페이퍼 손익: −28.00 (S2_ST_ROC) above −36.60 (N03_ADX_GC); the three of the earlier config never ranked, by P&L
    assert out["pnl"]["ranked"] == [["S2_ST_ROC", 1], ["N03_ADX_GC", 2]] and out["pnl"]["un"] == []
    assert out["pnl"]["out"] == [["N08_ICHI_WR", None], ["F12_MSS_DISP", None], ["F4_FAN", None]]
    assert out["list"] == ["S2_ST_ROC", "N03_ADX_GC", "N08_ICHI_WR", "F12_MSS_DISP", "F4_FAN"]
    assert out["decks"]["all"] and len(out["decks"]["all"]) == 2 and out["decks"]["top"] is None      # 2 <= 10: one deck
    assert [x[0] for x in out["win"]["ranked"]] == ["S2_ST_ROC", "N03_ADX_GC"]                      # 2/3 = 67 % over 11/17 = 65 %
    assert [x[0] for x in out["trades"]["ranked"]] == ["N03_ADX_GC", "S2_ST_ROC"]                   # 17 over 3
    assert [x[0] for x in out["sig"]["ranked"]] == ["N03_ADX_GC", "S2_ST_ROC"]                      # 9 signals this week over 5
    # 5년 기여도: S2_ST_ROC has no line in the 5-year table -> no rank there (never 0)
    assert out["contrib"]["ranked"] == [["N03_ADX_GC", 1]] and out["contrib"]["un"] == ["S2_ST_ROC"]
    assert out["big"]["text"] == "−28.00" and out["big"]["unit"] == "USDT" and out["big"]["tone"] == "down" and out["big"]["sub"] == "3번 2승"
    assert out["bigWin"]["text"] == "67%" and out["bigWin"]["sub"] == "2/3승"
    assert out["bigC"]["text"] == "—" and out["bigC"]["f"] is None
    assert out["bigSig"]["text"] == "9" and out["bigSig"]["unit"] == "개" and "진입 3" in out["bigSig"]["sub"]
    assert [(b["id"], b["w"]) for b in out["bars"]] == [("fit", 95.2), ("honest", 83.6), ("now", 64.7)]
    assert [(b["id"], b["w"]) for b in out["bars2"]] == [("fit", None), ("honest", None), ("now", 66.7)]
    c = out["counts"]
    assert (c["strategies"], c["settings"], c["signaled"], c["traded"], c["out"]) == (2, 3, 2, 2, 3)
    assert c["perWeek"] == pytest.approx(rows["N03_ADX_GC"]["bt"]["per_week"])
    assert out["why"].startswith("추세형 · 5년 시험 868번 (1주 2.5번꼴)") and "(1위)" in out["why"] and "처음 보는 기간 승률 84%" in out["why"]
    assert out["why2"] is None
    assert out["off"] == [{"k": "시각", "v": ["05시"]}, {"k": "코인x방향", "v": ["DOGE 롱"]}, {"k": "요일", "v": ["목요일"]}]
    assert out["match"] == [True, True, False]
    assert out["same"] is True and out["diff"] is False


def test_a_source_not_read_is_unknown_never_zero(rich):
    bad = {**rich, "paper": {"state": "error", "reason_ko": "읽지 못했어요"}, "signals": {"state": "missing", "reason_ko": "아직 없어요"}}
    out = _node("""const ok = R.sources(d), s2 = d.rows.find((r) => r.strategy === "S2_ST_ROC");
    console.log(JSON.stringify({ok, v: ["pnl", "win", "trades", "signals"].map((s) => R.valueOf(s2, s, ok)), counts: R.counts(d),
      pick: R.pickSort(null, d), pickT: R.pickSort("trades", d), pickS: R.pickSort("signals", d), big: R.bigOf(s2, "pnl", ok, R.missWord(d.paper)),
      bigS: R.bigOf(s2, "signals", ok, R.missWord(d.signals)), bars: R.barsOf(s2, ok).map((b) => b.id), un: R.rankRows(d.rows, "pnl", ok).unranked.length}));""", bad)
    assert out["ok"] == {"paper": False, "signals": False, "ref": True, "card": True}
    assert out["v"] == [None, None, None, None]
    assert out["counts"]["traded"] is None and out["counts"]["signaled"] is None
    # no paper: the 5-year order, and the line says the paper could not be read (never "거래 전")
    assert out["pick"]["sort"] == "contrib" and out["pick"]["note"] == "페이퍼 기록을 못 읽어서 5년 시험 순서예요"
    assert out["pickT"]["fallback"] and out["pickT"]["note"] == "페이퍼 기록을 못 읽어서 5년 시험 순서예요"
    assert out["pickS"]["note"] == "신호 기록을 못 읽어서 5년 시험 순서예요"
    assert out["big"]["text"] == "—" and out["big"]["sub"] == "못 읽음" and out["bigS"]["sub"] == "수집 전"
    assert out["bars"] == ["fit", "honest"] and out["un"] == 2                                     # no "지금" bar, no rank


# ---------------------------------------------------------------- day 1 on the production config
def test_day1_orders_by_5_year_contribution_and_says_so(day1):
    assert day1["n_strategies"] == 27 and day1["n_settings"] == 95 and day1["open"] is None
    assert all(r["paper"]["n"] == 0 for r in day1["rows"]) and all(r["in_config"] for r in day1["rows"])
    out = _node("""const ok = R.sources(d), res = R.rankRows(d.rows, "contrib", ok), dk = R.decks(res.ranked);
    console.log(JSON.stringify({pick: R.pickSort(null, d), pickPnl: R.pickSort("pnl", d), pickT: R.pickSort("trades", d), pickS: R.pickSort("signals", d),
      pickF: R.pickSort("honest", d), btr: res.ranked.map((x) => x.r.bt_rank), ranks: res.ranked.map((x) => x.rank),
      top: dk.top.map((x) => x.rank), bottom: dk.bottom.map((x) => x.rank), pnl: R.rankRows(d.rows, "pnl", ok),
      big: d.rows.map((r) => R.bigOf(r, "pnl", ok).text), sub: R.bigOf(d.rows[0], "pnl", ok).sub, now: d.rows.map((r) => R.barsOf(r, ok).length),
      counts: R.counts(d), sig: R.rankRows(d.rows, "signals", ok).ranked.slice(0, 2).map((x) => [x.r.strategy, x.v])}));""", day1)
    assert out["pick"] == {"sort": "contrib", "chosen": "contrib", "fallback": False, "traded": False, "note": "아직 거래 전이라 5년 시험 순서예요"}
    assert out["pickPnl"]["sort"] == "contrib" and out["pickPnl"]["fallback"] and out["pickPnl"]["note"].startswith("아직 거래 전이라 5년 시험 순서예요")
    assert out["pickT"]["sort"] == "contrib" and out["pickT"]["fallback"]                     # 27 zeros rank nothing
    assert out["pickS"]["sort"] == "signals" and not out["pickS"]["fallback"]                 # two signals this week: a real order
    assert out["pickF"]["sort"] == "honest" and out["pickF"]["note"] is None
    assert out["btr"] == list(range(1, 28)) and out["ranks"] == list(range(1, 28))           # = the server's bt_rank
    assert out["top"] == [1, 2, 3, 4, 5] and out["bottom"] == [23, 24, 25, 26, 27]
    assert out["pnl"]["ranked"] == [] and len(out["pnl"]["unranked"]) == 27                  # no paper P&L rank before a trade
    assert set(out["big"]) == {"—"} and out["sub"] == "거래 전" and set(out["now"]) == {2}    # never "0.00", no "지금" bar
    c = out["counts"]
    assert (c["strategies"], c["settings"], c["signaled"], c["traded"], c["out"]) == (27, 95, 2, 0, 0)
    assert 0.3 < c["perWeek"] < 1.5                                                          # about once a week or less each
    assert [v for _s, v in out["sig"]] == [1, 1]


# ---------------------------------------------------------------- the view in the tiny DOM
VIEW = """const ctx = {api: () => (d && d.__fail ? Promise.reject(Object.assign(new Error("x"), {kind: "network", status: 0})) : Promise.resolve(d)),
  every() {}, watch() {}, alive: () => true, href: (n, a) => '#/' + n + (a ? '/' + a : ''), track() {}};
const v = R.boardView(ctx);
await new Promise((r) => setTimeout(r, 0)); await new Promise((r) => setTimeout(r, 0));
const w = D.walk(v.el);
const det = d && d.rows ? d.rows.map((r) => D.walk(R.rowDetail(r, d, ctx.href)).text.replace(/\\s+/g, " ")) : [];
console.log(JSON.stringify({text: w.text.replace(/\\s+/g, " "), classes: w.classes, det, hidden: v.el.childNodes.map((c) => !!c.hidden)}));"""


def _bad_words(text):
    return [w for w in ("null", "undefined", "NaN", "Infinity", "[object") if w in text]


def test_view_rich(rich):
    out = _node(VIEW, rich)
    t = out["text"]
    assert not _bad_words(t), _bad_words(t)
    cards = [c for c in out["classes"] if c.split()[0] == "lbr-card"]
    assert len(cards) == 2 and sum("lbr-hold" in c for c in cards) == 1                       # the holder's frame is lit
    for words in ("매매법 순위", "선수단", "지금 포지션", "S2_ST_ROC", "지금 들고 있음 · BTC 롱",            # (Korean names: the board, browser only) "전체 2개", "페이퍼 손익",
                  "지금 설정 밖", "표본 적음", "주의", "읽는 법", "맞춘 숫자", "처음 보는 기간", "대부분 운이에요", "연습 돈", "진짜 돈",
                  "모의 · 실제 시세", "실거래 · 거래소 실제 체결", "기준표가 페이퍼 봇의 지금 설정과 다름"):
        assert words in t, words
    det = {r["strategy"]: x for r, x in zip(rich["rows"], out["det"])}
    n03 = det["N03_ADX_GC"]
    assert "왜 이 매매법인가" in n03 and "추세형 · 5년 시험 868번" in n03 and "세팅 1개" in n03 and "방향 반대" in n03 and "돌파 확인" in n03
    assert "5년 승률 (맞춘 숫자)" in n03 and "처음 보는 기간" in n03 and "바이비트" in n03 and "16번 11승" in n03 and "MEXC" in n03
    assert "최근 7일" in n03 and "돌파 기다림" in n03 and "매매법 화면에서" in n03
    s2 = det["S2_ST_ROC"]
    assert "세팅 2개" in s2 and "끈 구간" in s2 and "시각 05시" in s2 and "5년 기준표에 이 매매법 줄이 없어요" in s2 and "지금 들고 있음" in s2
    assert "MEXC 따라간 거래 없음" in s2
    assert "지금 설정에는 이 매매법이 없어요" in det["F4_FAN"] and "매매법 화면에서" not in det["F4_FAN"]
    f12 = det["F12_MSS_DISP"]                                                                    # a DeepSeek code: its rule lines
    assert "왜 이 매매법인가" in f12 and any(line in f12 for line in re.findall(r'"([^"]{8,})"', _rule_lines("F12_MSS_DISP")))
    for x in out["det"]:
        assert not _bad_words(x), _bad_words(x)


def _rule_lines(code):
    src = _read(os.path.join(SCREENS, "strategies-defs.js"))
    m = re.search(rf"\b{code}: \{{fam: \"F\d+\", lines: \[(.*?)\]\}}", src)
    assert m, code
    return m.group(1)


def test_view_day1_never_shows_zero_money(day1):
    out = _node(VIEW, day1)
    t = out["text"]
    assert not _bad_words(t), _bad_words(t)
    assert "아직 거래 전이라 5년 시험 순서예요" in t and "상위 5" in t and "하위 5" in t and "23~27위" in t and "5년 기여도" in t
    assert "거래 전" in t and "없음" in t                                                        # no position: 없음
    assert not re.search(r"[+−]?0\.00 USDT", t)                                                 # no made-up zero money
    assert sum(c.split()[0] == "lbr-card" for c in out["classes"]) == 10
    assert sum(c.split()[0] == "lbr-player" for c in out["classes"]) == 27


def test_view_states_missing_combo_and_failed_load():
    gone = {"now_ms": NOW, "combo": {"state": "missing", "reason_ko": "합친 봇 설정이 아직 없어요 (봇의 DB에도, 설정 파일에도)"}}
    t = _node(VIEW, gone)["text"]
    assert "수집 전" in t and "합친 봇 설정이 아직 없어요" in t and "합친 봇 설정을 읽어야" in t and not _bad_words(t)
    out = _node(VIEW, {"__fail": True})
    assert "서버에 닿지 못했습니다" in out["text"] and "다시 시도" in out["text"]
    assert out["hidden"] == [False, True]                                       # a failed first load: the box only, the body hidden
    assert "lbr-card" not in " ".join(out["classes"])


# ---------------------------------------------------------------- static checks
def _css_rules(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"@keyframes[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", src)
    return src


def test_css_tokens_sizes_prefix_and_motion():
    raw = _read(CSS)
    src = re.sub(r"/\*.*?\*/", "", raw, flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", src), "colour literal: use a token"
    assert not re.search(r"\brgba?\(\s*\d", src) and not re.search(r"\bhsla?\(\s*\d", src), "colour literal: use a token"
    for v in re.findall(r"font-size\s*:\s*([^;}]+)", src):
        assert "var(--t-" in v, v
    for v in re.findall(r"(?<![-\w])font\s*:\s*([^;}]+)", src):
        assert "var(--t-" in v or v.strip() == "inherit", v
    assert "infinite" not in src                                           # no endless decoration (CONTRACT 5c)
    for n in re.findall(r"animation\s*:\s*[\w-]+\s+[^;]*?\b(\d+)\s*;", src):
        assert int(n) <= 3, n
    assert "@media (prefers-reduced-motion: reduce)" in src
    rm = src[src.index("@media (prefers-reduced-motion: reduce)"):]
    for cls in (".lbr-card.lbr-enter", ".lbr-card.lbr-hold::after", ".lbr-live::after"):
        assert cls in rm, cls
    # every rule is the screen's own (.lbr…), never a bare shared class
    body = re.sub(r"@media[^{]*\{", "", _css_rules(src))
    for sel in re.findall(r"([^{}@;]+)\{", body):
        sel = sel.strip()
        if not sel or sel.startswith("@") or sel in ("from", "to") or re.match(r"^[\d%, ]+$", sel):
            continue
        for part in sel.split(","):
            assert ".lbr" in part, part
    assert '@import url("livebots-rank.css")' in _read(os.path.join(SCREENS, "livebots.css"))


def test_js_endpoint_text_safety_and_formats():
    src = _read(JS)
    assert '"/api/v4/livebots/rank"' in src
    code = re.sub(r"//[^\n]*", "", src)
    for bad in ("innerHTML", "insertAdjacentHTML", "outerHTML", "DOMParser", "eval(", "toLocaleString", "Intl.NumberFormat", "toFixed(",
                "localStorage", "setInterval("):
        assert bad not in code, bad
    for ref in re.findall(r'from\s+"([^"]+)"', src):
        assert ref == "../core/pb.js" or re.match(r"^\./[\w-]+\.js$", ref), ref
    assert "export function rankView" in src and "export function boardView" in src
    lb = _read(os.path.join(SCREENS, "livebots.js"))
    assert 'import {rankView} from "./livebots-rank.js"' in lb and 'id: "rank"' in lb


def test_view_failed_refresh_keeps_the_last_answer_dimmed(rich):
    out = _node("""let fail = false, tick = null;
const ctx = {api: () => (fail ? Promise.reject(Object.assign(new Error("x"), {kind: "timeout", status: 0})) : Promise.resolve(d)),
  every(ms, fn) { tick = {ms, fn}; }, watch() {}, alive: () => true, href: (n, a) => '#/' + n + (a ? '/' + a : ''), track() {}};
const v = R.boardView(ctx);
await new Promise((r) => setTimeout(r, 0)); await new Promise((r) => setTimeout(r, 0));
const before = D.walk(v.el);
fail = true; tick.fn(); await new Promise((r) => setTimeout(r, 0)); await new Promise((r) => setTimeout(r, 0));
const after = D.walk(v.el);
fail = false; tick.fn(); await new Promise((r) => setTimeout(r, 0)); await new Promise((r) => setTimeout(r, 0));
const back = D.walk(v.el);
console.log(JSON.stringify({ms: tick.ms, before: before.classes.filter((c) => /is-stale/.test(c)).length,
  after: after.text.replace(/\\s+/g, " "), dim: after.classes.filter((c) => /lbr-body.*is-stale/.test(c)).length,
  cards: after.classes.filter((c) => c.split(" ")[0] === "lbr-card").length,
  back: back.classes.filter((c) => /is-stale/.test(c)).length, backText: back.text.includes("제때 답하지")}));""", rich)
    assert out["ms"] == 30000 and out["before"] == 0
    assert "서버가 제때 답하지 않았습니다" in out["after"] and "자료를 보여 드립니다" in out["after"]
    assert out["dim"] == 1 and out["cards"] == 2                                  # the last answer stays, dimmed
    assert out["back"] == 0 and out["backText"] is False                          # the next good answer clears both

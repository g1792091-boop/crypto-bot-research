"""fill-strat (owners 10/06: "화면들은 부족한 게 좀 있어 보여"): the 매매법 chart, list, 한눈 지도, 분석 and 다시보기 filled
with real information.

- /api/v4/grid/y5: the 5-year past test per strategy x timeframe (vs5y.five_year rows: the 36 in ROE on margin,
  DeepSeek / the reel at 1x), read-only, cached, a broken research file gives no row (never a 500);
- the strategy chart's words (v3 계좌 chart: '롱 30배', '익절 잠금 +15%', '손절 −22%', '시간 청산'; DeepSeek: the reason
  only, no money), every timeframe's trades on the coin with their timeframe tag, and the live forming bar (a price
  outside the bar's time never moves it);
- 방금 나온 신호: 진입 / 건너뜀 + why, and only really new ids slide in (none on the first answer);
- the list's open rows and their live ROE (at the mark, from derive.livePnl);
- 분석's waiting views: their real thresholds from the server's answer and the board's real trade counts;
- 다시보기: the newest closed trade plays on its own (never under reduced motion);
- wiring and the CSS rules (tokens only, font sizes only from the --t-* scale).
"""
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess

import pytest

fastapi = pytest.importorskip("fastapi")

from paperbot.dash.app import Data  # noqa: E402
from paperbot.dash.more import grid as GR  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
SCREENS = os.path.join(V4, "screens")

_spec = importlib.util.spec_from_file_location("_grid_fixture", os.path.join(ROOT, "tests", "test_dash_more_grid.py"))
GF = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(GF)


def _read(name):
    with open(os.path.join(SCREENS, name), encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def db(tmp_path):
    return GF.make_db(str(tmp_path / "paper3.db"))


# ---------------------------------------------------------------- /api/v4/grid/y5
def test_y5_rows_per_strategy_and_timeframe(db, monkeypatch):
    calls = []

    def five_year(name):
        calls.append(name)
        if name == "S5_DONCHIAN_MFI":
            return "roe", {"15m": {"per_day": 1.2, "roe": 0.031, "win": 0.41, "hold_h": 3, "lock": 0.2},
                           "4h": {"per_day": 0.1, "roe": -0.012, "win": 0.38, "hold_h": 20, "lock": 0.1}}, {}
        if name == "F9_FVG":
            return "1x", {"15m": {"per_day": 3.0, "roe": -0.0019, "win": 0.31, "hold_h": 2, "lock": None}}, {}
        if name == "F15_ASIA_BRK":
            raise ValueError("a changed research file")
        return None, {}, None

    monkeypatch.setattr("paperbot.dash.more.vs5y.five_year", five_year)
    g = GR.Grid(Data(db))
    d = g.y5()
    s = d["strategies"]
    assert s["S5_DONCHIAN_MFI"] == {"unit": "roe", "group": "core", "tfs": {
        "15m": {"roe": 0.031, "win": 0.41, "per_day": 1.2}, "4h": {"roe": -0.012, "win": 0.38, "per_day": 0.1}}}
    assert s["F9_FVG"]["unit"] == "1x" and s["F9_FVG"]["group"] == "ds200"
    assert "F15_ASIA_BRK" not in s and "REEL_H1" not in s          # a broken file / no card: no row, never a 500
    assert not any(n.startswith("RANDOM") for n in calls)           # coin flips and copies are not strategies here
    assert "참고" in d["basis_ko"] and "5년" in d["basis_ko"]
    n = len(calls)
    g.y5()
    assert len(calls) == n                                          # cached (research files change only with a deploy)


def test_y5_route_answers_and_never_writes(db):
    before = hashlib.sha256(open(db, "rb").read()).hexdigest()
    c = GF._client(db)
    r = c.get("/api/v4/grid/y5")
    assert r.status_code == 200
    d = r.json()
    assert set(d) >= {"strategies", "computed_at", "basis_ko"}
    for row in d["strategies"].values():                            # whatever the repo's research files hold
        assert row["unit"] in ("roe", "1x") and row["group"] in ("core", "ds200", "reel")
        for y in row["tfs"].values():
            assert set(y) == {"roe", "win", "per_day"}
    assert hashlib.sha256(open(db, "rb").read()).hexdigest() == before


# ---------------------------------------------------------------- the JS logic (node)
def _node(body: str) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    base = "file://" + SCREENS
    script = (f"const C = await import('{base}/strategies-chart.js'); const P = await import('{base}/strategies-panels.js');\n"
              f"const L = await import('{base}/strategies-list.js'); const A = await import('{base}/analysis.js');\n"
              f"const R = await import('{base}/replay.js'); const K = await import('{base}/grid-kit.js');\n" + body)
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_chart_words_like_the_v3_account_chart():
    out = _node("""console.log(JSON.stringify({
      e1: C.entryText({side: 1, leverage: 30, _tf: "1h"}, "1h"), e2: C.entryText({side: -1, leverage: 20, _tf: "15m"}, "1h"),
      x1: C.exitText({exit_reason: "LOCK", roe: 0.152, _tf: "1h"}, "1h"), x2: C.exitText({exit_reason: "SL", roe: -0.221, _tf: "1h"}, "1h"),
      x3: C.exitText({exit_reason: "TIME", roe: 0.04, _tf: "1h"}, "1h"), x4: C.exitText({exit_reason: "SL", roe: -0.22, _tf: "4h"}, "1h", true),
      pool: C.tradesOn({"1h": [{symbol: "BTCUSDT", id: 1}, {symbol: "ETHUSDT", id: 2}], "4h": [{symbol: "BTCUSDT", id: 3}]}, "BTCUSDT").map((t) => [t.id, t._tf])}));""")
    assert out["e1"] == "롱 30배" and out["e2"] == "숏 20배 · 15분"
    assert out["x1"] == "익절 잠금 +15%" and out["x2"] == "손절 −22%" and out["x3"] == "시간 청산"
    assert out["x4"] == "손절 · 4시간"                               # DeepSeek: no money in the label
    assert out["pool"] == [[1, "1h"], [3, "4h"]]


def test_live_bar_moves_only_inside_its_own_time():
    out = _node("""const last = {time: 3600, open: 10, high: 11, low: 9, close: 10.5};
      console.log(JSON.stringify({up: C.liveBar(last, 12, 3700, 3600), down: C.liveBar(last, 8.5, 3700, 3600),
        mid: C.liveBar(last, 10, 3700, 3600), after: C.liveBar(last, 12, 7200, 3600), before: C.liveBar(last, 12, 3000, 3600),
        bad: C.liveBar(last, "x", 3700, 3600), none: C.liveBar(null, 12, 3700, 3600)}));""")
    assert out["up"] == {"time": 3600, "open": 10, "high": 12, "low": 9, "close": 12}
    assert out["down"] == {"time": 3600, "open": 10, "high": 11, "low": 8.5, "close": 8.5}
    assert out["mid"]["high"] == 11 and out["mid"]["low"] == 9 and out["mid"]["close"] == 10
    assert out["after"] is None and out["before"] is None and out["bad"] is None and out["none"] is None


def test_signal_feed_words_and_new_rows():
    out = _node("""console.log(JSON.stringify({s: ["SUBMITTED", "RECORD", "LATE", "NO_PRICE", "WEIRD"].map((x) => P.sigState({status: x})),
      first: [...P.newIds(null, [{id: 1}, {id: 2}])], next: [...P.newIds(new Set([1, 2]), [{id: 3}, {id: 2}, {id: 1}])]}));""")
    assert out["s"][0] == {"ko": "진입", "tone": "accent", "why": ""}
    assert [x["ko"] for x in out["s"][1:]] == ["건너뜀"] * 4
    assert out["s"][1]["why"] == "기록만 하는 봉" and out["s"][2]["why"] == "늦게 와서" and out["s"][4]["why"] == "WEIRD"
    assert out["first"] == [] and out["next"] == [3]                # nothing slides in on opening the page


def test_open_rows_live_roe_at_the_mark():
    out = _node("""const board = {accounts: [
        {account_id: "A@1h", strategy: "A", kind: "strategy", timeframe: "1h", position: {symbol: "BTCUSDT", side: 1, qty: 0.5, entry: 100, margin: 25, leverage: 2}},
        {account_id: "A@4h", strategy: "A", kind: "strategy", timeframe: "4h", position: null},
        {account_id: "A_C1@1h", strategy: "A", kind: "copy", timeframe: "1h", position: {symbol: "BTCUSDT", side: 1, qty: 1, entry: 100, margin: 10, leverage: 10}}]};
      const ops = L.openOf(board, "A", (s) => (s === "BTCUSDT" ? 110 : null));
      const none = L.openOf(board, "A", () => null);
      console.log(JSON.stringify({n: ops.length, id: ops[0].a.account_id, roe: ops[0].roe, noMark: none[0].roe}));""")
    assert out["n"] == 1 and out["id"] == "A@1h"                    # its own accounts only (a copy follows another rule)
    assert abs(out["roe"] - 0.2) < 1e-9 and out["noMark"] is None    # 0.5 x (110 − 100) / 25


def test_analysis_waiting_views_show_real_thresholds():
    out = _node("""const acc = (k, n, tf) => ({account_id: k + "@" + tf, kind: k === "D" ? "ds200" : "strategy", trades: n, created_ts: 0});
      const board = {accounts: [acc("S", 8, "15m"), acc("S", 3, "1h"), acc("S", 25, "4h"), acc("D", 2, "15m")]};
      const day = 86400000;
      console.log(JSON.stringify({risk: A.waitBars("risk", {drawdown: {min_trades: 20}}, "core", board),
        riskDs: A.waitBars("risk", {}, "ds200", board), over: A.waitBars("overlap", {rules: {min_trades: 20, min_days: 7}}, "core", board, 2.5 * day),
        syn: A.waitBars("synergy", {waiting: true, min_trades: 5}, "core", board), none: A.waitBars("map", {}, "core", board),
        done: A.waitBars("risk", {}, "core", {accounts: [acc("S", 30, "1h")]})}));""")
    r = out["risk"][0]
    assert "계좌마다 거래 20건 필요" in r["label"] and r["words"] == "지금 가장 많은 계좌 25건 · 20건 넘은 기존 36 계좌 1/3"
    assert r["share"] == 1 and r["full"] is False
    assert out["riskDs"][0]["words"] == "지금 가장 많은 계좌 2건 · 20건 넘은 딥시크 계좌 0/1"
    assert [b["label"] for b in out["over"]][1] == "같이 쌓인 기록 7일 필요" and out["over"][1]["words"] == "지금 2.5일째"
    assert out["syn"][0]["words"].startswith("지금 계좌당 평균 12.0건")
    assert out["none"] is None and out["done"] is None              # every bar full: the view stands on its own


def test_replay_landing_picks_the_newest_closed_trade():
    out = _node("""console.log(JSON.stringify({a: R.latestOf([{id: 5, exit_time: 100}, {id: 9, exit_time: 300}, {id: 7, exit_time: 200}]).id,
      tie: R.latestOf([{id: 5, exit_time: 300}, {id: 9, exit_time: 300}]).id, none: R.latestOf([])}));""")
    assert out == {"a": 9, "tie": 9, "none": None}


def test_y5_colour_steps_by_unit():
    out = _node("""console.log(JSON.stringify({roe: [0.001, 0.01, 0.03, -0.07, 0.2].map((v) => K.y5Bin(v, "roe")),
      x1: [0.0001, 0.0005, -0.001, 0.002, 0.005].map((v) => K.y5Bin(v, "1x")), none: K.y5Bin(null, "roe")}));""")
    assert out["roe"] == [0, 1, 2, -3, 4] and out["x1"] == [0, 1, -2, 3, 4] and out["none"] is None


# ---------------------------------------------------------------- wiring and honesty in the page files
def test_wiring():
    det = _read("strategies-detail.js")
    assert "allTrades: v.trades, kind, onBar:" in det                # every timeframe's trades + the bar-close reload
    ch = _read("strategies-chart.js")
    assert 'ctx.store.watch("ticker"' in ch and "unTick()" in ch     # live from the shared ticker, stopped on dispose
    lst = _read("strategies-list.js")
    assert "signalFeed(ctx" in lst and "(min-width: 1280px)" in lst and "size: wide ? 40 : 10" in lst
    assert 'ui.assume("open")' in lst                                # the live ROE is unrealized: its caption
    assert 's.group === "ds"' in lst                                 # DeepSeek rows: the position only, no %
    gr = _read("grid.js")
    assert '{id: "y5", label: "5년 시험"}' in gr and '{id: "pos", label: "지금 포지션"}' in gr and "/api/v4/grid/y5" in gr
    assert "5년 과거 시험 · 참고" in gr
    an = _read("analysis.js")
    assert "waitCard(v.label, bars, y5)" in an
    rp = _read("replay.js")
    assert "autoplay: !motion.reduced()" in rp and "document.hidden" in rp


NEW_CSS_MARK = {"strategies.css": "fill-strat", "grid.css": "fill-strat", "analysis.css": "fill-strat"}


@pytest.mark.parametrize("name", sorted(NEW_CSS_MARK))
def test_new_css_uses_tokens_only(name):
    css = _read(name)
    part = css[css.index(NEW_CSS_MARK[name]):]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", part)
    for m in re.finditer(r"font-size:\s*([^;}]+)", part):
        assert re.fullmatch(r"var\(--t-(xs|sm|md|lg|xl|2xl|led)\)", m.group(1).strip()), m.group(0)
    assert "animation:" not in part                                  # no endless motion (CONTRACT honesty rule 1)

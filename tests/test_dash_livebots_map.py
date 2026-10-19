"""실거래 › 지도 and 비용, the page (screens/livebots-map.js, livebots-cost.js) on the hand-made live world
(tests/livebots_world.py): the server's answers (dash/more/livebots.py map_view, costs) go through the page's own pure
functions in node, and both views are drawn in node's tiny DOM (tests/anasyn_dom.mjs).

- 기대 범위 띠: the binomial quantiles the page works out itself are the server's (binom_quantiles), the bands at any trade
  count, inside / below / above the honest range (below its 5 % edge: warning, the drift alarm's line), the sentence per
  account, the step lines, the scales, the end labels pulled apart, the pointer's reading, the empty start (bands only);
- 어디서 벌고 어디서 잃나: a cut is coloured against its 5-year number from 10 trades on, grey before, none without a trade;
  the 24-hour ring and the Korea-time hand;
- 비용: slips in words (+ = in the trade's favour), tiles that never show 0 for what is unknown, the paired bars (paper
  scaled vs live, oldest first), the missed paper trades;
- both views: 수집 전 / 못 읽음, a failed refresh keeps the last answer dimmed with its age, the empty words;
- the files: tokens only (no hex), --t-* font sizes, their own class prefixes, the endpoints, no HTML parsing.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

import pytest

pytest.importorskip("fastapi")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import livebots_world as W  # noqa: E402
from paperbot.dash.app import json_finite  # noqa: E402
from paperbot.dash.more import livebots as L  # noqa: E402

V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
SCREENS = os.path.join(V4, "screens")
DOM = os.path.join(ROOT, "tests", "anasyn_dom.mjs")
NOW = W.NOW
H = W.H


def _read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    L._cache.clear()
    monkeypatch.setenv("PAPERBOT_LIVE_COMBO_CONFIG", "/nonexistent/combo.json")   # the run's own config (in the database)
    yield
    L._cache.clear()


@pytest.fixture
def rich(tmp_path, monkeypatch):
    p = W.build_world(str(tmp_path / "r"))
    m = W.live_checks(p, str(tmp_path / "r"), rich=True)
    for k, v in W.env_more_of(m).items():
        monkeypatch.setenv(k, v)
    return p


def _empty_world(folder: str) -> dict:
    """The production start: every file there, no closed trade yet."""
    from paperbot.executor import ExecStore
    from paperbot.store3 import Store3
    os.makedirs(folder, exist_ok=True)
    p = {k: os.path.join(folder, f) for k, f in (("paper", "live-ac.db"), ("bybit_db", "executor-bybit-live.db"),
                                                 ("mexc_db", "executor-mexc-live.db"), ("bybit_config", "executor.json"),
                                                 ("mexc_config", "executor-mexc.json"))}
    s3 = Store3(p["paper"])
    s3.add_account(W.ACCOUNT, "combo", "mix", "combo", W.T0, "combo-v2")
    s3.put_state("accounts", NOW - 60_000, {"last_ts": NOW - 60_000, "engines": {W.ACCOUNT: {
        "wallet": 1000.0, "peak_equity": 1000.0, "max_drawdown": 0.0, "halted": False, "halt_reason": "", "bust": False, "warned": [],
        "last_mark": {}, "position": None, "pending": [], "n_trades": 0}}})
    s3.close()
    for ex in ("bybit", "mexc"):
        st = ExecStore(p[f"{ex}_db"], lock=False)
        st.put_state("meta", W.T0, {"mode": "mainnet", "account": W.ACCOUNT, "since": W.T0, "exchange": ex, "live_since": W.T0})
        st.put_state("bot", NOW - 5_000, {"trade": None, "done": [], "loops": 10, "mode": "mainnet", "account": W.ACCOUNT,
                                          "risk": {"halted": False, "halt_reason": "", "consecutive_losses": 0, "last_equity": 100.0, "trades": 0}})
        st.close()
        W.config(p[f"{ex}_config"], p[f"{ex}_db"], p["paper"], ex, 0.85, os.path.join(folder, "STOP"))
    return p


def _node(tmp_path, body: str, **data) -> dict:
    """Runs body in node after the tiny DOM and both modules (M: the map, K: the cost); data: JSON the script reads as D_<k>."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    loads = []
    for k, v in data.items():
        f = tmp_path / f"{k}.json"
        f.write_text(json.dumps(json_finite(v), allow_nan=False, default=str), encoding="utf-8")
        loads.append(f"const D_{k} = JSON.parse(fs.readFileSync({json.dumps(str(f))}, 'utf8'));")
    script = (f"const D = await import('file://{DOM}'); const fs = await import('node:fs');\n"
              f"const M = await import('file://{SCREENS}/livebots-map.js'); const K = await import('file://{SCREENS}/livebots-cost.js');\n"
              + "\n".join(loads) + "\n"
              "const tick = () => new Promise((r) => setTimeout(r, 5));\n"
              "const texts = (n) => { const out = []; const go = (x) => { if (!x) return; if (x instanceof Text) { out.push(x.t); return; }"
              " (x.childNodes || []).forEach(go); }; go(n); return out.join(' ').replace(/\\s+/g, ' '); };\n"
              "const classes = (n) => { const out = []; const go = (x) => { if (!x || x instanceof Text) return;"
              " const c = x.className || (x.getAttribute && x.getAttribute('class')); if (c) out.push(String(c)); (x.childNodes || []).forEach(go); };"
              " go(n); return out.join(' '); };\n"
              "const mkCtx = (answers) => { const st = {calls: 0, every: null}; return {st, ctx: {params: {query: {}}, alive: () => true, track() {},"
              " listen() {}, on() {}, every(ms, fn) { st.every = fn; st.ms = ms; },"
              " api: async (path) => { st.path = path; const a = answers[Math.min(st.calls++, answers.length - 1)];"
              " if (a instanceof Error) throw a; return JSON.parse(JSON.stringify(a)); }}}; };\n"
              + body)
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=90)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


# ================================================================ the files
def test_the_files_keep_the_house_rules():
    for name, pre in (("livebots-map", "lbm-"), ("livebots-cost", "lbk-")):
        css = re.sub(r"/\*.*?\*/", "", _read(SCREENS, f"{name}.css"), flags=re.S)
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css), name                       # tokens only, both skins
        assert not re.search(r"font-size:\s*\d", css) and not re.search(r"font:\s*[^;]*\d+px", css), name
        assert "data-skin=\"classic\"" in css, name                                  # the glow is the AI skin's only
        # every rule is the screen's own: each selector names a class with the screen's prefix
        for sel in re.findall(r"(?:^|})\s*([^{}@]+?)\s*{", css):
            for part in sel.split(","):
                part = part.strip()
                if part and not part.startswith(("from", "to")) and not re.match(r"^\d", part):
                    assert re.search(r"\." + pre.rstrip("-") + r"(-|\b)", part), (name, part)
        js = _read(SCREENS, f"{name}.js")
        for bad in ("innerHTML", "insertAdjacentHTML", "outerHTML", "toLocaleString(", "Intl.NumberFormat", "eval(", "new Function"):
            assert bad not in js, (name, bad)
        assert not re.search(r"#[0-9a-fA-F]{6}\b", js), name
        assert set(re.findall(r'from "([^"]+)"', js)) == {"../core/pb.js", "./livebots-kit.js"}, name
        assert "const REFRESH_MS = 30 * 1000;" in js and "ctx.every(REFRESH_MS," in js, name
        assert "ui.staleNote(e, st.okAt" in js and "ui.dim(body, !!st.d)" in js and "ui.dim(body, false)" in js, name
        assert "sourceState(" in js, name
    assert '"/api/v4/livebots/map"' in _read(SCREENS, "livebots-map.js")
    assert '"/api/v4/livebots/costs"' in _read(SCREENS, "livebots-cost.js")
    css = _read(SCREENS, "livebots.css")
    assert '@import url("livebots-map.css");' in css and '@import url("livebots-cost.css");' in css
    tabs = _read(SCREENS, "livebots.js")
    assert '{id: "map", label: "지도", make: (ctx) => mapView(ctx), own: true}' in tabs
    assert '{id: "cost", label: "비용", make: (ctx) => costView(ctx), own: true}' in tabs


# ================================================================ 기대 범위 띠
def test_the_page_works_out_the_same_quantiles_as_the_server(tmp_path, rich):
    m = L.map_view(rich, NOW)
    b = m["band"]
    cases = [(n, p) for p in (0.7497, 0.9132, 0.5, 0.05) for n in (1, 2, 7, 20, 40, 68, 131, 500, 2000)]
    out = _node(tmp_path, f"""const cases = {json.dumps(cases)};
    const q = cases.map(([n, p]) => M.binomQ(n, p));
    const at = [5, 20, 48, 68].map((n) => M.bandAt(D_m.band, n));
    const far = M.bandAt(D_m.band, 500);
    console.log(JSON.stringify({{q, at, far, none: [M.binomQ(10, 0), M.binomQ(10, 1), M.binomQ(10, null)], zero: M.bandAt(D_m.band, 0)}}));""", m=m)
    assert out["q"] == [L.binom_quantiles(n, p) for n, p in cases]
    for n, got in zip((5, 20, 48, 68), out["at"]):
        i = b["ns"].index(n)
        assert got["honest"] == b["honest_band"][i] and got["fit"] == b["fit_band"][i] and got["be"] == pytest.approx(0.776 * n)
    assert out["far"]["honest"] == L.binom_quantiles(500, b["honest"]) and out["far"]["fit"] == L.binom_quantiles(500, b["fit"])
    assert out["none"] == [None, None, None] and out["zero"] == {"honest": [0, 0, 0], "fit": [0, 0, 0], "be": 0}


def test_each_account_in_one_sentence_against_the_honest_range(tmp_path, rich):
    m = L.map_view(rich, NOW)
    b = m["band"]
    i48 = b["ns"].index(48)
    p5, p95 = b["honest_band"][i48][0], b["honest_band"][i48][2]
    out = _node(tmp_path, f"""const b = D_m.band;
    const say = (id, acc) => M.acctSentence(id, acc, b);
    console.log(JSON.stringify({{
      paper: say("paper", b.accounts.paper), bybit: say("bybit", b.accounts.bybit), mexc: say("mexc", b.accounts.mexc),
      low: say("paper", {{n: 48, wins: {p5 - 1}, rate: {(p5 - 1) / 48}}}), edge: M.whereOf({{n: 48, wins: {p5}}}, b).where,
      high: say("bybit", {{n: 48, wins: {p95 + 1}}}), top: M.whereOf({{n: 48, wins: {p95}}}, b).where,
      none: say("mexc", {{n: 0, wins: 0, points: []}}), gone: say("paper", undefined),
      nob: M.acctSentence("paper", b.accounts.paper, {{...b, honest_band: null, honest: null}}),
    }}));""", m=m)
    assert b["accounts"]["paper"]["wins"] == 31 and p5 == 31                      # the rich paper sits right on the edge
    assert out["paper"] == {"text": "페이퍼 48번 중 31번 이김 (64.6%) · 현실 기대 범위 안", "tone": "", "where": "inside"}
    assert out["bybit"]["text"] == "바이비트 19번 중 12번 이김 (63.2%) · 현실 기대 범위 안"
    assert out["mexc"]["text"] == "MEXC 3번 중 3번 이김 (100.0%) · 현실 기대 범위 안"
    # one win fewer than the honest 5 % edge: the warning (the line the drift alarm uses), one more than the 95 %: above
    assert out["low"] == {"text": f"페이퍼 48번 중 {p5 - 1}번 이김 ({(p5 - 1) / 48 * 100:.1f}%) · 현실 기대 범위 아래", "tone": "warn", "where": "below"}
    assert out["edge"] == "inside" and out["top"] == "inside"
    assert out["high"]["where"] == "above" and out["high"]["text"].endswith("현실 기대 범위 위") and out["high"]["tone"] == "up"
    assert out["none"] == {"text": "MEXC 아직 닫힌 거래 없음", "tone": "none", "where": "none"} and out["gone"]["where"] == "none"
    assert out["nob"]["where"] == "unknown" and "범위" not in out["nob"]["text"]       # no honest band: no word about it


def test_band_geometry_step_lines_and_labels(tmp_path, rich):
    m = L.map_view(rich, NOW)
    out = _node(tmp_path, """const b = D_m.band;
    const g = M.bandGeom(b, 640, 300, ["paper", "bybit", "mexc"]);
    const nums = (d) => d.match(/-?[0-9.]+/g).map(Number);
    const r48 = M.readAt(b, 48), r3 = M.readAt(b, 3), r0 = M.readAt(b, 0);
    console.log(JSON.stringify({
      x0: g.X(0), xN: g.X(g.nMax), y0: g.Y(0), yTop: g.Y(g.yMax), nMax: g.nMax, yMax: g.yMax, pad: g.pad, xt: g.xt, yt: g.yt,
      lines: g.lines.map((l) => [l.id, l.d.slice(0, 1), [Number([...l.d.matchAll(/H(-?[0-9.]+)/g)].pop()[1]), Number([...l.d.matchAll(/V(-?[0-9.]+)/g)].pop()[1])]]),
      ends: g.ends,
      expect: g.ends.map((e) => [g.X(e.n), g.Y(e.wins)]),
      hon: [g.honest.area.endsWith("Z"), g.honest.mid.startsWith("M"), !!g.honest.low], fit: !!g.fit.area,
      be: g.be, beWant: g.Y(b.break_even * g.nMax), check: g.check, checkWant: g.X(40),
      step: M.stepPath([[1, 1], [2, 1], [3, 2]], (n) => n * 10, (w) => 100 - w * 10),
      r48, r3, r0,
    }));""", m=m)
    pad = out["pad"]
    assert out["x0"] == pad["l"] and out["xN"] == pytest.approx(640 - pad["r"]) and out["y0"] == pytest.approx(300 - pad["b"])
    assert out["yTop"] == pytest.approx(pad["t"]) and out["nMax"] == 68 and out["yMax"] >= 66      # the fitted p95 at 68 fits
    assert out["xt"][0] == 0 and out["yt"][0] == 0 and all(y <= out["yMax"] for y in out["yt"])
    assert [x[0] for x in out["lines"]] == ["paper", "bybit", "mexc"] and all(x[1] == "M" for x in out["lines"])
    for (_id, _m, (hx, vy)), (x, y) in zip(out["lines"], out["expect"]):          # each line ends at (its n, its wins)
        assert hx == pytest.approx(x, abs=0.06) and vy == pytest.approx(y, abs=0.06)
    ly = sorted(e["ly"] for e in out["ends"])
    assert all(b2 - a2 >= 16 - 1e-9 for a2, b2 in zip(ly, ly[1:]))               # labels pulled apart
    assert all(pad["t"] + 6 - 1e-9 <= e["ly"] <= 300 - pad["b"] - 4 + 1e-9 for e in out["ends"])
    assert {e["id"]: e["label"] for e in out["ends"]} == {"paper": "페이퍼 31/48", "bybit": "바이비트 12/19", "mexc": "MEXC 3/3"}
    assert out["hon"] == [True, True, True] and out["fit"]
    assert out["be"]["y2"] == pytest.approx(out["beWant"]) and out["check"] == pytest.approx(out["checkWant"])
    assert out["step"] == "M0.0,100.0H10.0V90.0H20.0H30.0V80.0"                  # a loss stays flat, a win steps up
    assert out["r48"]["accts"] == {"paper": 31, "bybit": None, "mexc": None} and out["r3"]["accts"]["mexc"] == 3
    assert out["r0"]["accts"] == {"paper": 0, "bybit": 0, "mexc": 0} and out["r48"]["honest"][0] == 31


def test_before_the_first_trade_only_the_bands_are_drawn(tmp_path):
    p = _empty_world(str(tmp_path / "e"))
    m = L.map_view(p, NOW)
    assert m["band"]["n_max"] == L.BAND_MIN_N and all(a["n"] == 0 for a in m["band"]["accounts"].values())
    out = _node(tmp_path, """const g = M.bandGeom(D_m.band, 640, 300);
    const {ctx} = mkCtx([D_m]); const v = M.mapView(ctx); await tick();
    console.log(JSON.stringify({lines: g.lines.length, ends: g.ends.length, nMax: g.nMax, text: texts(v.el)}));""", m=m)
    # (node has no layout: the chart is drawn at 640 px, where the words are one line; a phone splits them in two)
    assert out["lines"] == 0 and out["ends"] == 0 and out["nMax"] == 40
    t = out["text"]
    assert "거래가 쌓이면 여기에 선이 그려져요" in t and "페이퍼 아직 닫힌 거래 없음" in t and "바이비트 아직 닫힌 거래 없음" in t
    assert "40번째 거래" in t and "아직 없음" in t and not re.search(r"\b(null|undefined|NaN)\b", t)


# ================================================================ 어디서 벌고 어디서 잃나
def test_cuts_are_coloured_from_ten_trades_against_their_five_years(tmp_path, rich):
    m = L.map_view(rich, NOW)
    out = _node(tmp_path, """const b = D_m.band, by = (c, k) => D_m.cuts[c].find((r) => String(r.key) === k);
    const t = (c, k) => M.cellTone(by(c, k), b);
    const syn = (win, n = 30) => M.cellTone({n, win, bt_win: 0.91, honest: 0.7497}, b).tone;
    console.log(JSON.stringify({
      btc: t("coin", "BTCUSDT"), sol: t("coin", "SOLUSDT"), eth: t("coin", "ETHUSDT"), doge: t("coin", "DOGEUSDT"),
      hb2: t("hb", "2"), hb1: t("hb", "1"), short: t("side", "-1"),
      syn: [syn(0.95), syn(0.91), syn(0.85), syn(0.776), syn(0.76), syn(0.7497), syn(0.6), syn(0.99, 9)],
      min: M.MIN_N, none: M.cellTone(null, b), zero: M.cellTone({n: 0}, b),
    }));""", m=m)
    assert out["min"] == 10
    assert out["btc"]["tone"] == "bad" and out["btc"]["gap"] == pytest.approx(2 / 11 - 0.9064)   # 2 of 11 against 90.6 %
    assert out["sol"]["tone"] == "hi" and out["eth"]["tone"] == "bad" and out["short"]["tone"] == "bad"
    assert out["doge"]["tone"] == "small" and out["hb2"]["tone"] == "bad"                          # 1 trade: grey; 10: coloured
    assert out["hb1"] == {"tone": "none", "gap": None} and out["none"]["tone"] == "none" and out["zero"]["tone"] == "none"
    # as good as the 5 years / above break-even / at the realistic rate but under break-even / under it; under 10: grey
    assert out["syn"] == ["hi", "hi", "ok", "ok", "lo", "lo", "bad", "small"]


def test_the_ring_the_korea_time_hand_and_the_small_pieces(tmp_path):
    out = _node(tmp_path, """const nums = (d) => d.match(/-?[0-9.]+/g).map(Number);
    console.log(JSON.stringify({
      arc: nums(M.arcPath(100, 100, 50, 80, 0, 60)), big: M.arcPath(100, 100, 50, 80, 0, 270).includes(" 0 1 1 "),
      h0: M.kstHour(%d), b0: M.kstBlock(%d), b1: M.kstBlock(%d), h2: M.kstHour(%d), b2: M.kstBlock(%d),
      sp: M.spread([10, 12, 14], 16, 0, 100), sp2: M.spread([95, 99], 16, 0, 100), sp3: M.spread([50, 10], 16, 0, 100),
      st: [M.niceStep(66, 5), M.niceStep(40, 4), M.niceStep(3, 4), M.niceStep(900, 5)],
      lw: [M.labelW("MEXC 3/3"), M.labelW("페이퍼")],
      gauge: M.gaugeGeom({honest: [31, 36, 41], fit: [40, 44, 47], be: 37.2}, 48, 31), nog: M.gaugeGeom(null, 48, 31),
    }));""" % (W.T0, W.T0, NOW, W.T0 + 15 * H, W.T0 + 15 * H))
    a = out["arc"]
    assert a[:2] == [100, 20] and a[-2:] == [100, 50]                          # starts at 12 o'clock, outer then inner radius
    assert out["big"]
    assert out["h0"] == pytest.approx(9) and out["b0"] == 2 and out["b1"] == 4   # T0 = 09:00 KST, NOW = 19:00 KST
    assert out["h2"] == pytest.approx(0) and out["b2"] == 0                     # midnight KST: the first block
    assert out["sp"] == [10, 26, 42] and out["sp2"] == [84, 100] and out["sp3"] == [50, 10]
    assert out["st"] == [20, 10, 1, 200] and out["lw"] == [7 * 8, 36]
    g = out["gauge"]
    assert 0 <= g["h"][0] < g["be"] < g["h"][1] <= 1 and g["w"] == pytest.approx(g["h"][0]) and g["f"][1] <= 1
    assert out["nog"] is None


# ================================================================ 비용
def test_cost_math_never_shows_zero_for_the_unknown(tmp_path, rich):
    co = L.costs(rich, NOW)
    b = co["accts"]["bybit"]
    out = _node(tmp_path, """const a = D_co.accts.bybit;
    const items = K.pairBars(a.rows, 20), g = K.barGeom(items, 520, 150);
    console.log(JSON.stringify({
      slip: [K.slipWords(0.0005), K.slipWords(-0.0012), K.slipWords(0), K.slipWords(null), K.slipWords(0.000001)],
      pp: [K.pp(-0.042), K.pp(0.253), K.pp(null)],
      unknown: K.costTiles({}).map((t) => t.v), tiles: K.costTiles(a).map((t) => [t.id, t.v, t.sub]),
      items, sum: K.sumPairs(items), zero: g.zero, H: g.H, pad: g.pad, bars: g.bars.map((x) => [x.cx, x.p, x.l, x.paper, x.live]),
      missed: K.missedTotal(a), missed0: K.missedTotal({}), empty: K.EMPTY_KO,
      many: K.pairBars(Array.from({length: 30}, (_, i) => ({key: "k" + i, exit_time: 1000 - i, paper_scaled: i, pnl: i - 0.5}))).map((x) => x.key),
    }));""", co=co)
    assert out["slip"][0] == {"text": "+0.050%", "tone": "up", "ko": "페이퍼보다 유리"}
    assert out["slip"][1] == {"text": "−0.120%", "tone": "down", "ko": "페이퍼보다 불리"}
    assert out["slip"][2]["ko"] == "페이퍼와 같음" and out["slip"][2]["tone"] == "" and out["slip"][4]["ko"] == "페이퍼와 같음"
    assert out["slip"][3] == {"text": "—", "tone": "", "ko": "짝 맞춘 거래 없음"}
    assert out["pp"] == ["−4.2%p", "+25.3%p", "—"]
    assert out["unknown"] == ["—", "—", "체결 기록 전", "—", "—"]               # nothing known: never a 0
    tiles = {t[0]: t for t in out["tiles"]}
    assert tiles["fees"][1] == "1.40" and tiles["funding"][1] == "0.00" and tiles["slip"][2].endswith("+는 페이퍼보다 유리")
    matched = [r for r in b["rows"] if r["paper_scaled"] is not None and r["pnl"] is not None]
    assert [x["key"] for x in out["items"]] == [r["key"] for r in reversed(matched[:20])]     # oldest first, matched only
    assert out["sum"]["n"] == len(matched) and out["sum"]["diff"] == pytest.approx(sum(r["diff"] for r in matched))
    assert out["sum"]["paper"] == pytest.approx(sum(r["paper_scaled"] for r in matched))
    for cx, p, l_, paper, live in out["bars"]:                                    # paper left of the middle, live right
        assert p["x"] + p["w"] < cx < l_["x"] and p["h"] >= 1 and l_["h"] >= 1
        for bar, v in ((p, paper), (l_, live)):                                   # up from the zero line, or down from it
            if bar["h"] > 1:
                assert (bar["y"] == pytest.approx(out["zero"])) if v < 0 else (bar["y"] + bar["h"] == pytest.approx(out["zero"]))
    assert out["pad"]["t"] <= out["zero"] <= out["H"] - out["pad"]["b"]
    assert out["missed"] == sum(m["n"] for m in b["missed"]) == 2 and out["missed0"] == 0
    assert out["many"] == [f"k{i}" for i in range(19, -1, -1)] and out["empty"] == "실거래 거래가 아직 없어요 · 첫 거래가 닫히면 채워져요"


# ================================================================ both views, drawn in node
def test_the_views_draw_the_answers(tmp_path, rich):
    m, co = L.map_view(rich, NOW), L.costs(rich, NOW)
    out = _node(tmp_path, """const a = mkCtx([D_m]); const mv = M.mapView(a.ctx); await tick();
    const b = mkCtx([D_co]); const cv = K.costView(b.ctx); await tick();
    console.log(JSON.stringify({map: texts(mv.el), cost: texts(cv.el), mpath: a.st.path, cpath: b.st.path, ms: [a.st.ms, b.st.ms],
      mcls: classes(mv.el), ccls: classes(cv.el)}));""", m=m, co=co)
    assert out["mpath"] == "/api/v4/livebots/map" and out["cpath"] == "/api/v4/livebots/costs" and out["ms"] == [30000, 30000]
    t = out["map"]
    for want in ("페이퍼 48번 중 31번 이김 (64.6%) · 현실 기대 범위 안", "바이비트 19번 중 12번 이김 (63.2%)", "48번째 거래",
                 "현실 기대 범위 (처음 보는 2025-26 승률 75.0%", "5년 백테스트 범위 (맞춘 승률 91.3%", "본전선 (승률 77.6%)",
                 "경보선", "어디서 벌고 어디서 잃나", "장세", "코인", "시간대", "방향", "확실히 나쁨", "18.2%", "1,250번", "04~08시",
                 "롱 29번", "숏 19번", "숫자 읽는 법", "12~18번", "모의 · 실제 시세"):
        assert want in t, want
    assert not re.search(r"\b(null|undefined|NaN)\b", t)
    assert "lbm-row t-bad" in out["mcls"] and "lbm-row t-hi" in out["mcls"] and "lbm-row t-small" in out["mcls"]
    c = out["cost"]
    for want in ("실거래(진짜 돈)는 페이퍼(연습)보다 얼마나 덜 버나", "짝 맞춘 거래 17 / 19", "+1.31", "거래당 +0.08 USDT",
                 "실거래가 더 벌었어요", "−0.50", "실거래가 덜 벌었어요", "체결 기록 전이라 지갑 변화로 어림한 거래 1개", "코인별",
                 "따라가지 못한 페이퍼 거래", "그때 실행기가 멈춰 있었어요", "페이퍼 진입을 늦게 봐서 건너뛰었어요", "최근 실거래",
                 "−2.00≈", "체결 전", "1–10 / 19", "실거래 · 거래소 실제 체결"):
        assert want in c, want
    assert not re.search(r"\b(null|undefined|NaN)\b", c)


def test_empty_missing_and_a_failed_refresh(tmp_path):
    e = _empty_world(str(tmp_path / "e"))
    em, ec = L.map_view(e, NOW), L.costs(e, NOW)
    x = W.build_world(str(tmp_path / "x"))
    os.remove(x["paper"])
    os.remove(x["mexc_db"])
    xm, xc = L.map_view(x, NOW), L.costs(x, NOW)
    out = _node(tmp_path, """const run = async (V, answers) => { const c = mkCtx(answers); const v = V(c.ctx); await tick(); return {v, c}; };
    const ec = await run(K.costView, [D_ec]), xm = await run(M.mapView, [D_xm]), xc = await run(K.costView, [D_xc]);
    const fail = await run(K.costView, [new Error("down")]);
    // a good answer, then a failed refresh: the answer stays, dimmed, with its age
    const st = await run(M.mapView, [D_xm, Object.assign(new Error("down"), {kind: "network"})]);
    await st.c.st.every(); await tick();
    const st2 = await run(K.costView, [D_ec, Object.assign(new Error("down"), {kind: "timeout"}), D_ec]);
    await st2.c.st.every().catch(() => {}); await tick();
    const dimmed = classes(st2.v.el).includes("is-stale");
    await st2.c.st.every(); await tick();
    console.log(JSON.stringify({ec: texts(ec.v.el), xm: texts(xm.v.el), xc: texts(xc.v.el), fail: texts(fail.v.el),
      st: texts(st.v.el), stcls: classes(st.v.el), dimmed, back: classes(st2.v.el).includes("is-stale") || texts(st2.v.el).includes("자료를 보여 드립니다")}));""",
                ec=ec, xm=xm, xc=xc)
    assert out["ec"].count("실거래 거래가 아직 없어요") >= 3 and "첫 거래가 닫히면 채워져요" in out["ec"]   # both cards and the list
    assert "짝 맞춘 거래 0 / 0" in out["ec"] and "놓친 페이퍼 거래 없음" in out["ec"]
    assert "수집 전" in out["xm"] and "아직 파일이 없어요" in out["xm"] and "MEXC" in out["xm"]
    assert "수집 전" in out["xc"] and "MEXC 실행기 DB" in out["xc"] and "페이퍼 DB (짝 맞출 페이퍼 거래)" in out["xc"]
    assert "불러오지 못했습니다" in out["fail"]
    assert "서버에 닿지 못했습니다" in out["st"] and "자료를 보여 드립니다" in out["st"] and "is-stale" in out["stcls"]
    assert "수집 전" in out["st"]                                                  # the last answer is still on the page
    assert out["dimmed"] and not out["back"]                                       # dimmed while failing, clear once it answers
    for k in ("ec", "xm", "xc"):
        assert not re.search(r"\b(null|undefined|NaN)\b", out[k]), k

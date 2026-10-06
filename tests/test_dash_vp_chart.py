"""매물대 (volume profile) on the 차트 screen and the terminal chart (vp-chart, owners 10/06: "매수 물량 구간, 매도 물량 구간들도
중요하게 생각하는데"): a horizontal volume-by-price histogram, each price row split into 매수 (taker buy volume) and 매도
(volume - buy), the POC, the 70 % value area (VAH / VAL) and the bot's own 매물대 levels to compare with.

1. the server's candle rows carry the taker buy volume (kline field 9) as "buy"; older pages ignore the extra key;
2. the profile math (screens/chart-vp-calc.js, node): three tiny bars worked out by hand: the rows, the buy / sell split,
   the POC, the value area grown from the POC outwards (the bot's rule: the side with more volume, a tie goes up),
   VAH / VAL, and the honest cases (no buy key, no volume, a flat range);
3. the live throttle: the whole profile is rebuilt at most once a second;
4. the toggle: off by default on the 터미널 (the declutter), on for a PC window's 차트 screen, a device that saved its
   choices before this group existed starts with it off on the 터미널;
5. the bot's levels (/api/v4/vplevels, entry_marks kinds 51-53): the research function's own numbers, read-only, a failed
   load is a 503 (never "no levels"), the other timeframes say so.
"""
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _read(*p):
    with open(os.path.join(V4, *p), encoding="utf-8") as f:
        return f.read()


def _code(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(re.sub(r"(^|[^:\"'`])//.*$", r"\1", ln) for ln in src.splitlines())


def _node(body: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    scr = "file://" + os.path.join(V4, "screens")
    script = f"const C = await import('{scr}/chart-vp-calc.js');\n" + body
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------- 1. the candle rows carry "buy"
class _Resp:
    def __init__(self, rows):
        self.rows = rows

    def read(self):
        return json.dumps(self.rows).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _kline(t, o, h, l, c, v, buy):
    # Binance /fapi/v1/klines: open time, o, h, l, c, volume, close time, quote volume, trades, taker buy base volume,
    # taker buy quote volume, ignore
    return [t, str(o), str(h), str(l), str(c), str(v), t + 59_999, "123.4", 17, str(buy), "55.5", "0"]


def test_candle_rows_carry_the_taker_buy_volume(monkeypatch):
    import paperbot.dash.app as A
    rows = [_kline(1_700_000_000_000, 100, 102, 99, 101, 20.5, 15.25), _kline(1_700_000_060_000, 101, 103, 100, 102, 30, 10)]
    monkeypatch.setattr(A.urllib.request, "urlopen", lambda url, timeout=0: _Resp(rows))
    A._CANDLE_CACHE.clear()
    out = A.fetch_candles("BTCUSDT", "1m", 2)
    assert out[0] == {"time": 1_700_000_000, "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "volume": 20.5, "buy": 15.25}
    assert out[1]["buy"] == 10.0 and out[1]["volume"] == 30.0
    # a kline row without the taker fields (a fake, an older API): no "buy" key at all, never a made-up zero
    short = [[1_700_000_000_000, "1", "2", "0.5", "1.5", "7", 0]]
    monkeypatch.setattr(A.urllib.request, "urlopen", lambda url, timeout=0: _Resp(short))
    A._CANDLE_CACHE.clear()
    assert "buy" not in A.fetch_candles("ETHUSDT", "1m", 1)[0]
    A._CANDLE_CACHE.clear()


def test_the_candles_route_passes_the_buy_key_through(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from paperbot.dash.app import create_app, hash_password
    from test_dash import SECRET, _store
    db = str(tmp_path / "p.db")
    _store(db).close()
    rows = [{"time": 1, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 7.0, "buy": 3.0}]
    c = TestClient(create_app(db, hash_password("pw"), SECRET, candles=lambda s, i, n: rows))
    assert c.post("/api/login", json={"password": "pw"}).status_code == 200
    assert c.get("/api/candles", params={"symbol": "BTCUSDT", "interval": "1m", "limit": 2}).json() == rows


# ---------------------------------------------------------------- 2. the profile math (node)
THREE = "[{low: 100, high: 102, volume: 20, buy: 15}, {low: 101, high: 103, volume: 30, buy: 10}, {low: 102, high: 104, volume: 10, buy: 2}]"


def test_three_bars_by_hand_rows_split_poc_and_value_area():
    p = _node(f"""const p = C.buildProfile({THREE}, {{n: 4}}); console.log(JSON.stringify(p));""")
    # four rows 100-101, 101-102, 102-103, 103-104. Bar 1 (20, buy 15) is spread over 100-102: 10 in each of rows 0 and 1
    # (buy 7.5, sell 2.5 each); bar 2 (30, buy 10) over 101-103: 15 in rows 1 and 2 (buy 5, sell 10); bar 3 (10, buy 2) over
    # 102-104: 5 in rows 2 and 3 (buy 1, sell 4)
    assert p["ok"] and p["n"] == 4 and p["lo"] == 100 and p["hi"] == 104 and p["step"] == 1 and p["split"] is True
    assert p["tot"] == [10, 25, 20, 5] and p["total"] == 60 and p["bars"] == 3
    assert p["buy"] == [7.5, 12.5, 6, 1] and p["sell"] == [2.5, 12.5, 14, 4]
    assert p["buyTotal"] == 27 and p["sellTotal"] == 33 and p["buyRatio"] == pytest.approx(0.45)
    assert all(b + s == pytest.approx(t) for b, s, t in zip(p["buy"], p["sell"], p["tot"]))        # 매수 + 매도 = the row
    assert sum(p["tot"]) == pytest.approx(20 + 30 + 10)                                           # nothing lost, nothing added
    # POC: the fullest row (25, row 1), its middle 101.5
    assert p["poc"] == 1 and p["pocPrice"] == 101.5 and p["max"] == 25
    # 70 % of 60 = 42: from row 1 (25) the row above (20) beats the row below (10): 45 >= 42, so rows 1..2: VAL 101, VAH 103
    assert (p["vaLo"], p["vaHi"]) == (1, 2) and p["val"] == 101 and p["vah"] == 103


def test_value_area_grows_from_the_poc_one_row_at_a_time_and_a_tie_goes_up():
    out = _node("""
      const bar = (lo, hi, v) => ({low: lo, high: hi, volume: v, buy: v / 2});
      // rows of 10, 20, 10, 6 (total 46, 70 % = 32.2): from the POC (row 1) the rows above and below tie at 10: up wins
      // (30 < 32.2), then 6 above against 10 below: down (40): rows 0..2, VAL 100, VAH 103
      const a = C.buildProfile([bar(100, 101, 10), bar(101, 102, 20), bar(102, 103, 10), bar(103, 104, 6)], {n: 4});
      // a side that has run out is skipped: rows 40, 10, 10, 4 (total 64, 70 % = 44.8): the POC row 0 has no row below, so
      // only upwards: 40 + 10 = 50 >= 44.8, rows 0..1, VAL 100, VAH 102
      const b = C.buildProfile([bar(100, 101, 40), bar(101, 102, 10), bar(102, 103, 10), bar(103, 104, 4)], {n: 4});
      // a flat profile: the fullest row is the first (lowest) one, like the bot's sr.py
      const c = C.buildProfile([bar(100, 104, 40)], {n: 4});
      console.log(JSON.stringify({a: [a.poc, a.vaLo, a.vaHi, a.val, a.vah], b: [b.poc, b.vaLo, b.vaHi, b.val, b.vah], c: [c.poc, c.vaLo, c.vaHi],
        va: C.valueArea([5, 5, 5, 5], 0, 0.7), share: C.VA_SHARE}));""")
    assert out["a"] == [1, 0, 2, 100, 103] and out["b"] == [0, 0, 1, 100, 102] and out["c"] == [0, 0, 2] and out["va"] == {"lo": 0, "hi": 2}
    assert out["share"] == 0.7


def test_a_bar_without_range_goes_into_its_row_and_the_edges_stay_inside():
    p = _node("""const p = C.buildProfile([{low: 100, high: 100, volume: 8, buy: 3}, {low: 100, high: 104, volume: 4, buy: 4}], {n: 4});
      console.log(JSON.stringify(p));""")
    assert p["tot"] == [9, 1, 1, 1] and p["buy"] == [4, 1, 1, 1] and p["sell"] == [5, 0, 0, 0]
    assert p["hi"] == 104 and len(p["tot"]) == 4                         # a high on the top edge falls into the last row


def test_no_buy_key_is_a_total_only_never_a_made_up_split():
    out = _node("""
      const none = C.buildProfile([{low: 100, high: 102, volume: 20}, {low: 101, high: 103, volume: 30}], {n: 3});
      const mixed = C.buildProfile([{low: 100, high: 102, volume: 20, buy: 5}, {low: 101, high: 103, volume: 30}], {n: 3});
      const f = {price: (x) => x.toFixed(1), vol: (x) => x.toFixed(1)};
      console.log(JSON.stringify({none: [none.split, none.buy, none.sell, none.buyRatio, none.total], mixed: mixed.split, text: C.rowText(none, 1, f),
        info: C.rowInfo(none, 1)}));""")
    assert out["none"] == [False, None, None, None, 50] and out["mixed"] is False              # one bar without it: no split for any
    assert out["text"] == "가격 101.0~102.0 · 거래량 25.0 · 매수·매도 구분 자료 없음"
    assert out["info"]["buy"] is None and out["info"]["ratio"] is None


def test_hover_text_has_the_price_range_buy_sell_and_buy_ratio():
    out = _node(f"""const p = C.buildProfile({THREE}, {{n: 4}});
      const f = {{price: (x) => x.toFixed(1), vol: (x) => x.toFixed(1)}};
      console.log(JSON.stringify({{t: [0, 1, 2, 3].map((i) => C.rowText(p, i, f)), at: [99.9, 100, 101.5, 104, 104.1].map((x) => C.rowAt(p, x))}}));""")
    assert out["t"][1] == "가격 101.0~102.0 · 매수 12.5 · 매도 12.5 · 매수 비율 50%"
    assert out["t"][0] == "가격 100.0~101.0 · 매수 7.5 · 매도 2.5 · 매수 비율 75%"
    assert out["t"][3] == "가격 103.0~104.0 · 매수 1.0 · 매도 4.0 · 매수 비율 20%"
    assert out["at"] == [-1, 0, 1, 3, -1]


def test_degenerate_input_says_what_is_wrong():
    out = _node("""console.log(JSON.stringify({
      none: C.buildProfile([], {n: 4}).why, nan: C.buildProfile([{low: NaN, high: 1, volume: 1}], {n: 4}).why,
      novol: C.buildProfile([{low: 1, high: 2, volume: 0}, {low: 1, high: 2}], {n: 4}).why,
      flat: C.buildProfile([{low: 5, high: 5, volume: 3}], {n: 4}).why, nullv: C.buildProfile(null).why,
      neg: C.buildProfile([{low: 100, high: 102, volume: 10, buy: 99}], {n: 2}).buy,
      inverted: C.buildProfile([{low: 3, high: 2, volume: 9}], {n: 2}).why}));""")
    assert out == {"none": "nobars", "nan": "nobars", "novol": "novol", "flat": "flat", "nullv": "nobars", "neg": [5, 5], "inverted": "nobars"}      # a buy bigger than the volume is clamped to it


def test_row_count_adapts_to_the_pane_height():
    out = _node("""console.log(JSON.stringify({r: [520, 340, 300, 130, 60, 4000, 0, NaN].map((h) => C.rowCount(h)), min: C.ROWS_MIN, max: C.ROWS_MAX}));""")
    assert out["r"] == [62, 41, 36, 16, 10, 150, 40, 40]            # about one row per 7 px of the 84 % the price range fills
    assert out["min"] == 10 and out["max"] == 150
    assert out["r"][0] > out["r"][1] > out["r"][2] > out["r"][3]    # a taller pane gets more rows


def test_the_ranges_visible_today_and_a_week():
    out = _node("""
      const data = [...Array(10).keys()].map((i) => ({time: 1000 + i}));
      const now = 1791281135;                                         // 2026-10-06 19:25:35 KST
      console.log(JSON.stringify({
        ids: C.RANGES.map((r) => r.id), ko: C.RANGES.map((r) => r.ko),
        vis: [[2.4, 6.7], [-5, 3], [8.2, 40], [20, 30], [4, 4]].map(([a, b]) => C.sliceVisible(data, {from: a, to: b}).map((x) => x.time - 1000)),
        none: [C.sliceVisible([], {from: 0, to: 1}).length, C.sliceVisible(data, null).length, C.sliceVisible(data, {from: NaN, to: 3}).length],
        kst: C.kstDayStart(now), today: C.rangeSpec("today", now), week: C.rangeSpec("week", now), view: C.rangeSpec("view", now)}));""")
    assert out["ids"] == ["view", "today", "week"] and out["ko"] == ["보이는 구간", "오늘", "최근 7일"]
    # bar i shows when from - 0.5 <= i <= to + 0.5
    assert out["vis"] == [[2, 3, 4, 5, 6, 7], [0, 1, 2, 3], [8, 9], [], [4]]
    assert out["none"] == [0, 0, 0]
    midnight = out["kst"]
    assert midnight % 86400 == (86400 - 9 * 3600) % 86400 and 0 <= 1791281135 - midnight < 86400          # 00:00 Korea time of that day
    assert out["today"] == {"mode": "today", "interval": "5m", "limit": 300, "from": midnight}
    assert out["week"] == {"mode": "week", "interval": "15m", "limit": 700, "from": 1791281135 - 7 * 86400} and out["view"] is None
    assert 300 * 300 >= 86400 + 3600 and 700 * 900 >= 7 * 86400                                       # the asked bars cover the range


# ---------------------------------------------------------------- 3. the live throttle
def test_live_changes_rebuild_the_whole_profile_at_most_once_a_second():
    out = _node("""
      let t = 0, id = 0; const timers = new Map(), runs = [];
      const clock = {now: () => t, set: (f, ms) => { const k = ++id; timers.set(k, {f, at: t + ms}); return k; }, clear: (k) => timers.delete(k)};
      const g = C.throttle(() => runs.push(t), C.MIN_GAP_MS, clock);
      const advance = (to) => { for (;;) { const due = [...timers].filter(([, x]) => x.at <= to).sort((a, b) => a[1].at - b[1].at)[0]; if (!due) break; t = due[1].at; timers.delete(due[0]); due[1].f(); } t = to; };
      // a 5 s poll plus a relay trade ten times a second, for 12 s: 120 pokes
      for (let ms = 0; ms <= 12000; ms += 100) { advance(ms); g.poke(); }
      advance(14000);
      // a poke after a quiet spell runs at once
      const quiet = runs.length; g.poke(); const at = runs.length;
      const gaps = runs.slice(1).map((x, i) => x - runs[i]);
      // cancel drops a pending one; flush runs now
      g.poke(); const pend = g.pending; g.cancel();
      console.log(JSON.stringify({runs: runs.length, before: quiet, first: runs[0], gaps, minGap: Math.min(...gaps), immediate: at === quiet + 1, pend, after: g.pending, count: g.runs}));""")
    # 121 pokes in 12 s (every 100 ms): a run at 0 s and then one every second (the last, trailing one at 13 s), 14 in all
    assert out["first"] == 0 and out["minGap"] >= 1000 and out["before"] == 14 and out["count"] == out["runs"]
    assert out["immediate"] is True and out["pend"] is True and out["after"] is False
    one = _node("""
      let t = 0; const timers = []; const clock = {now: () => t, set: (f, ms) => { timers.push({f, at: t + ms}); return timers.length; }, clear: () => {}};
      let n = 0; const g = C.throttle(() => n++, 1000, clock);
      g.poke(); for (let i = 0; i < 500; i++) { t += 1; g.poke(); }
      console.log(JSON.stringify({n, timers: timers.length}));""")
    assert one == {"n": 1, "timers": 1}                            # 500 pokes inside the gap are one more run, not 500


def test_the_primitive_rebuilds_through_the_gate_only_for_live_changes():
    src = _code(_read("screens", "chart-vp.js"))
    assert "throttle(" in src and "MIN_GAP_MS" in src and "gate.poke()" in src
    # a pan, zoom, resize, range or coin change is `struct` (rebuilt at once); a new high / low / volume of the newest bar is `live`
    assert re.search(r"if \(sel\.struct !== st\.structSig\) \{[^}]*recompute\(sel\)", src)
    assert re.search(r"else if \(sel\.live !== st\.liveSig\) \{ st\.liveSig = sel\.live; gate\.poke\(\); \}", src)
    assert src.count("recompute(") == 3                           # the definition, the struct path, the gate's own run


# ---------------------------------------------------------------- 4. the toggle: off on the terminal, on for the 차트 screen
def test_the_toggle_defaults_and_the_saved_choices_of_an_older_device():
    out = _node("""console.log(JSON.stringify({
      term: [C.defaultOn("term", false), C.defaultOn("term", true)], chart: [C.defaultOn("chart", false), C.defaultOn("chart", true)],
      old: C.withVpDefault({v: 2, off: ["sr"], hide: [], smc: ["eq"]}, false), kept: C.withVpDefault({v: 2, off: ["sr", "vp"]}, false),
      on: C.withVpDefault({v: 2, off: ["sr"]}, true), nothing: [C.withVpDefault(null, false), C.withVpDefault({v: 2}, false), C.withVpDefault("x", false)]}));""")
    assert out["term"] == [False, False]                          # the terminal: never on by itself (the declutter)
    assert out["chart"] == [True, False]                          # the 차트 screen: on for a PC window, off on a phone
    assert out["old"] == {"v": 2, "off": ["sr", "vp"], "hide": [], "smc": ["eq"]}
    assert out["kept"] == {"v": 2, "off": ["sr", "vp"]} and out["on"] == {"v": 2, "off": ["sr"]}
    assert out["nothing"] == [None, {"v": 2}, "x"]


def test_the_screens_pass_the_default_and_list_the_group_in_the_line_menu():
    term = _code(_read("screens", "terminal-chart.js"))
    chart = _code(_read("screens", "chart.js"))
    assert 'groups: ["pos", "risk", "sr", "smc", "ev", "vol", "vp"]' in term and "defaults: {sr: false, vp: false}" in term
    assert 'vpPrepare("term", false)' in term and 'vpAttach({chart: C.chart, series, deck, wrap, box, ctx, key: "term"' in term
    assert 'groups: ["pos", "risk", "sr", "smc", "ev", "vol", "vp"]' in chart and 'vpPrepare("chart", !narrow())' in chart
    assert "{pos: false, risk: false, sr: false, smc: false, vp: false} : {vp: true}" in chart       # a phone: off; a PC window: on
    vp = _code(_read("screens", "chart-vp.js"))
    assert 'GROUP_KO.vp = "매물대"' in vp                         # the deck's '선' menu names the group
    assert "deck.onToggle(" in vp and 'deck.shown("vp")' in vp


def test_both_screens_load_the_style_and_it_uses_only_tokens():
    for name in ("chart.css", "terminal.css"):
        assert '@import url("chart-vp.css");' in _read("screens", name)
    css = _read("screens", "chart-vp.css")
    assert '.chart-card[data-view="tv"] > .vp-host { display: none; }' in css       # the 거래소 차트 tab shows only the exchange's page
    code = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", code) and not re.search(r"\brgba?\(", code)
    assert all(float(m) >= 12 for m in re.findall(r"font[^;{]*?(\d+(?:\.\d+)?)px", code))


def test_the_legend_states_the_approximation_and_the_page_never_builds_html_from_data():
    calc = _read("screens", "chart-vp-calc.js")
    assert "봉 자료로 나눈 근사치: 실제 체결 가격별 물량과 다를 수 있음" in calc
    vp = _read("screens", "chart-vp.js")
    assert "APPROX" in _code(vp) and "title: APPROX" in vp
    for bad in ("innerHTML", "insertAdjacentHTML", "outerHTML", "DOMParser", "eval(", "toLocaleString", "Intl.NumberFormat"):
        assert bad not in _code(vp) and bad not in _code(calc), bad
    # a failed load is said, never an empty profile: the range read, the bot's lines and the candles without a split
    assert "자료를 불러오지 못했습니다" in vp and "봇 기준선을 불러오지 못했습니다" in vp and "매수·매도 구분이 없습니다" in vp


# ---------------------------------------------------------------- 5. the bot's own 매물대 (read-only)
def _client(tmp_path, frames):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from paperbot.dash.app import create_app, hash_password
    from test_dash import SECRET, _store
    db = str(tmp_path / "p.db")
    _store(db).close()
    c = TestClient(create_app(db, hash_password("pw"), SECRET, frames=frames))
    assert c.post("/api/login", json={"password": "pw"}).status_code == 200
    return c


def _df(n=420):
    from paperbot import sweepsig
    return sweepsig.lib().synth_ohlcv(n, "5m", seed=5, start="2026-04-01")[["ts", "open", "high", "low", "close", "volume"]]


def test_the_bots_levels_are_the_research_functions_own_numbers(tmp_path):
    import numpy as np
    from paperbot import entry_marks
    df = _df()
    calls = []

    def frames(sym, tf, n):
        calls.append((sym, tf, n))
        return df.tail(n).reset_index(drop=True)

    c = _client(tmp_path, frames)
    r = c.get("/api/v4/vplevels", params={"symbol": "BTCUSDT", "tf": "15m"}).json()
    assert r["ready"] is True and r["tf"] == "15m" and r["symbol"] == "BTCUSDT" and r["bars"] == 200 and r["bins"] == 50 and r["share"] == 0.7
    assert [x["kind"] for x in r["levels"]] == [51, 52, 53] and [x["key"] for x in r["levels"]] == ["poc", "vah", "val"]
    assert [x["ko"] for x in r["levels"]] == ["매물 최다 가격", "매물대 위 끝", "매물대 아래 끝"]
    # the same function that records kinds 51 / 52 / 53 with every signal, on the last 200 closed bars
    sr = entry_marks.sr_module()
    last = df.tail(205).reset_index(drop=True)
    want = sr.volume_profile(np.asarray(last["high"], float), np.asarray(last["low"], float), np.asarray(last["close"], float),
                             np.asarray(last["volume"], float), np.array([len(last) - 1]))[0]
    assert [x["price"] for x in r["levels"]] == pytest.approx(list(want))
    poc, vah, val = (x["price"] for x in r["levels"])
    assert val < poc < vah or val <= poc <= vah
    assert calls == [("BTCUSDT", "15m", 205)]                                   # one small fetch (the cache answers the next call)
    assert c.get("/api/v4/vplevels", params={"symbol": "BTCUSDT", "tf": "15m"}).json() == r and len(calls) == 1
    assert r["bar"] == int(df["ts"].iloc[-1].value // 1_000_000) or r["bar"] == int(last["ts"].iloc[-1].value // 1_000_000)


def test_other_timeframes_and_symbols_and_failed_loads_say_so(tmp_path):
    df = _df()
    c = _client(tmp_path, lambda s, tf, n: df.tail(n).reset_index(drop=True))
    for tf in ("1m", "5m", "1d", "2h"):
        assert c.get("/api/v4/vplevels", params={"symbol": "BTCUSDT", "tf": tf}).json() == {"ready": False, "why": "tf"}   # the bot's four only
    assert c.get("/api/v4/vplevels", params={"symbol": "NOPE", "tf": "15m"}).status_code == 400
    # too few bars to compute: ready false with the reason, not zeros
    short = _client(tmp_path, lambda s, tf, n: df.tail(120).reset_index(drop=True))
    got = short.get("/api/v4/vplevels", params={"symbol": "ETHUSDT", "tf": "1h"}).json()
    assert got["ready"] is False and got["why"] == "bars" and "levels" not in got

    def broken(s, tf, n):
        raise OSError("binance unreachable")
    # a failed fetch is a 503 (the page says 불러오지 못했습니다), never an empty answer that would read as "no levels"
    assert _client(tmp_path, broken).get("/api/v4/vplevels", params={"symbol": "BTCUSDT", "tf": "15m"}).status_code == 503


def test_a_failed_refetch_returns_the_last_good_answer_marked_stale(monkeypatch):
    from paperbot.dash.more import vplevels as V
    df = _df()
    state = {"fail": False, "t": 1000.0}

    def frames(s, tf, n):
        if state["fail"]:
            raise OSError("down")
        return df.tail(n).reset_index(drop=True)

    bp = V.BotProfile(frames, ("15m",), clock=lambda: state["t"])
    first = bp.get("BTCUSDT", "15m")
    assert first["ready"] and "stale" not in first
    state["fail"] = True
    state["t"] += 10
    assert bp.get("BTCUSDT", "15m") == first                       # inside 30 s: the kept answer, no fetch
    state["t"] += 60
    again = bp.get("BTCUSDT", "15m")
    assert again["stale"] is True and again["levels"] == first["levels"]
    with pytest.raises(Exception):
        bp.get("ETHUSDT", "15m")                                   # never fetched: a 503, not an invented answer


def test_the_route_is_listed_and_the_page_asks_for_it():
    from paperbot.dash import more
    assert "vplevels" in more.MODULES
    vp = _read("screens", "chart-vp.js")
    assert "/api/v4/vplevels?symbol=" in vp
    src = open(os.path.join(ROOT, "paperbot", "dash", "more", "vplevels.py"), encoding="utf-8").read()
    assert "TIMEOUT_S" in src and "@app.get(\"/api/v4/vplevels\")" in src

"""The chart deck (owners 10/06, from the HelloQuant reference: "선이 너무 크고 투박하다 · 누르면 숨기게 · 차트가
비어 보인다 · 간지나게 · 번쩍임 많이 자주"): core/chartfx.js on the terminal chart and the 차트 screen.

- glow / ambient / flash are the AI skin's only (클래식 stays plain), motion follows real events only, never a timer;
- the flash scheduler (core/flash.js): rate limit per '번쩍임' mode, the biggest waiting event wins, stale events drop,
  reduced motion and 끄기 play nothing, 고래 / large liquidations hold longer (node);
- the ambient light (EMA 50): tone by the last close, a flip only on a real cross, strength modestly by distance (node);
- 프리미엄 지표 (core/smc.js) on synthetic candles: swings, BoS / CHoCH, order blocks, FVGs, BSL / SSL, the dealing
  range with OTE 0.62 / 0.79, trendlines, leg % (node);
- our position lines (screens/chart-lines.js): 1 px pills like '숏 30배 · 3개 · −2.5% · 잠금 · 손절', DeepSeek /
  coin flips counted without money (node), excluded from the autoscale, click-to-hide remembered per device;
- the candles API carries volume for the volume bars.
"""
import json
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")


def _read(*p):
    with open(os.path.join(V4, *p), encoding="utf-8") as f:
        return f.read()


def _code(src: str) -> str:
    """JS without // and /* */ comments (strings kept)."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(re.sub(r"(^|[^:\"'`])//.*$", r"\1", ln) for ln in src.splitlines())


def _node(body: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    core = "file://" + os.path.join(V4, "core")
    script = (f"const F = await import('{core}/flash.js'); const S = await import('{core}/smc.js');\n" + body)
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------- the flash scheduler
SCHED = """
const mk = (mode = "often", reduced = false) => {
  const st = {t: 0, timers: [], played: []};
  const s = F.flashScheduler({now: () => st.t, reduced: () => reduced, visible: () => true, mode: () => mode,
    setTimer: (fn, ms) => { const x = {fn, at: st.t + ms}; st.timers.push(x); return x; },
    clearTimer: (x) => { st.timers = st.timers.filter((y) => y !== x); },
    play: (ev, ms) => st.played.push({t: st.t, tone: ev.tone, k: ev.k, ms, why: ev.why})});
  const run = (t) => { st.t = t; for (const x of st.timers.filter((y) => y.at <= t)) { st.timers = st.timers.filter((y) => y !== x); x.fn(); } };
  return {s, st, run};
};
"""


def test_flash_often_plays_at_once_then_rate_limits_and_the_biggest_waiting_event_wins():
    out = _node(SCHED + """
      const A = mk("often");
      A.s.push({tone: "up", k: 0.4, why: "a"});            // t=0 plays now
      A.st.t = 200; A.s.push({tone: "down", k: 0.5, why: "b"});
      A.st.t = 300; A.s.push({tone: "up", k: 0.9, why: "c"});    // the biggest waiting one
      A.st.t = 400; A.s.push({tone: "down", k: 0.6, why: "d"});
      const waiting = A.s.pending().why;
      A.run(899); const before = A.st.played.length;
      A.run(900);                                           // the gap (0.9 s) ends: c plays, b and d are dropped
      A.run(5000);
      console.log(JSON.stringify({played: A.st.played, waiting, before}));""")
    assert out["waiting"] == "c" and out["before"] == 1
    assert [(p["t"], p["why"]) for p in out["played"]] == [(0, "a"), (900, "c")]
    small = out["played"][0]
    assert small["ms"] == 200 + 600 + 400                  # an ordinary big trade: a short hold


def test_flash_whale_holds_longer_and_blocks_the_next_one_until_its_hold_ends():
    out = _node(SCHED + """
      const A = mk("often");
      A.s.push(F.bigEvent({side: "buy", x: 9, w: 1}));     // 고래: k 1, ~1.5 s hold
      A.st.t = 1000; A.s.push(F.bigEvent({side: "sell", x: 1.2, w: 0}));
      A.run(1699); const mid = A.st.played.length;
      A.run(1700);
      console.log(JSON.stringify({played: A.st.played, mid}));""")
    assert out["mid"] == 1
    first, second = out["played"]
    assert first["tone"] == "up" and first["k"] == 1 and first["ms"] == 200 + 1500 + 400 and first["why"] == "고래 체결"
    assert second["t"] == 1700 and second["tone"] == "down" and second["k"] < 0.5


def test_flash_modes_reduced_motion_and_stale_events():
    out = _node(SCHED + """
      const N = mk("normal");
      const n1 = N.s.push(F.bigEvent({side: "buy", x: 3, w: 0}));          // 보통: an ordinary big trade is dropped
      const n2 = N.s.push(F.liqEvent({liquidated: "long", usd: 400000}));   // a large liquidation plays
      N.st.t = 1000; N.s.push(F.ownEvent());
      N.run(2400); const n_before = N.st.played.length; N.run(2500);         // 보통: 2.5 s apart
      const O = mk("off"); const o1 = O.s.push(F.ownEvent());
      const R = mk("often", true); const r1 = R.s.push(F.bigEvent({side: "buy", x: 9, w: 1}));
      const Q = mk("often"); Q.s.push(F.ownEvent()); Q.st.t = 100; Q.s.push(F.bigEvent({side: "sell", x: 2}));
      Q.st.timers[0].at = 5000; Q.run(5000);                                 // played late: stale (over 3 s), dropped
      console.log(JSON.stringify({n1, n2, n_before, normal: N.st.played, o1, off: O.st.played.length, r1,
        reduced: R.st.played.length, stale: Q.st.played.length, modes: F.FLASH_MODES.map((m) => [m.id, m.ko, m.gapMs])}));""")
    assert out["n1"] is False and out["n2"] is True and out["n_before"] == 1
    assert [p["tone"] for p in out["normal"]] == ["down", "accent"] and out["normal"][1]["t"] == 2500
    assert out["o1"] is False and out["off"] == 0
    assert out["r1"] is False and out["reduced"] == 0                     # prefers-reduced-motion: no flash at all
    assert out["stale"] == 1
    assert out["modes"][0][:2] == ["often", "자주"] and out["modes"][0][2] == 900
    assert out["modes"][1][:2] == ["normal", "보통"] and out["modes"][1][2] == 2500 and out["modes"][2][:2] == ["off", "끄기"]


def test_flash_event_tones_and_strengths():
    out = _node("""console.log(JSON.stringify({
      buy: F.bigEvent({side: "buy", x: 1}), sell: F.bigEvent({side: "sell", x: 3.5}), whale: F.bigEvent({side: "sell", x: 6, w: 1}),
      bad: F.bigEvent({side: "?", x: 3}), lg: F.liqEvent({liquidated: "long", usd: 20000}), sh: F.liqEvent({liquidated: "short", usd: 2e6}),
      own: F.ownEvent()}));""")
    assert out["buy"]["tone"] == "up" and out["sell"]["tone"] == "down" and out["bad"] is None
    assert out["buy"]["k"] < out["sell"]["k"] < out["whale"]["k"] == 1
    assert out["buy"]["big"] is False and out["whale"]["big"] is True
    assert out["lg"]["tone"] == "down" and out["sh"]["tone"] == "up"                # long liquidated = red, short = cyan
    assert out["lg"]["big"] is False and out["sh"]["big"] is True and out["sh"]["k"] > out["lg"]["k"]
    assert out["own"]["tone"] == "accent"


def test_flash_scheduler_never_runs_on_its_own():
    src = _code(_read("core", "flash.js"))
    assert "setInterval" not in src and "requestAnimationFrame" not in src
    # the one timer only plays an event that really arrived (inside push / due)
    assert src.count("setTimer(due") == 2


# ---------------------------------------------------------------- the ambient light
def test_ambient_tone_follows_the_50_bar_average_and_flips_only_on_a_real_cross():
    out = _node("""
      const bars = (cl) => cl.map((c, i) => ({time: i, open: c, high: c, low: c, close: c}));
      const up = Array.from({length: 80}, (_, i) => 100 + i * 0.1);
      const down = Array.from({length: 80}, (_, i) => 100 - i * 0.1);
      const a = F.ambient(bars(up)), b = F.ambient(bars(down));
      // a forming close hovering just under the average: an up tone stays (inside the 0.05 % band)
      const flat = Array.from({length: 80}, () => 100);
      const near = F.ambient(bars([...flat, 99.97]), "up"), cross = F.ambient(bars([...flat, 99.5]), "up");
      const far = F.ambient(bars([...up.slice(0, 79), 120]));
      console.log(JSON.stringify({a, b, near: near.tone, cross: cross.tone, fresh: F.ambient(bars([...flat, 99.97])).tone,
        short: F.ambient(bars([1, 2, 3])), kNear: a.k, kFar: far.k}));""")
    assert out["a"]["tone"] == "up" and out["b"]["tone"] == "down"
    assert out["near"] == "up" and out["cross"] == "down" and out["fresh"] == "down"
    assert out["short"] is None
    assert 0.55 <= out["kNear"] <= out["kFar"] <= 1


# ---------------------------------------------------------------- 프리미엄 지표 (SMC) on synthetic candles
SYN = """
// a downtrend (lower highs 95, 91), a rally that breaks the last lower high (CHoCH up), a higher high (BoS up) with an
// impulsive bar that leaves a fair value gap, then a pullback: straight legs of 6 bars between the waypoints
const way = [100, 90, 95, 85, 91, 80, 88, 84, 93, 89, 99, 95, 104, 100];
const path = [];
for (let w = 1; w < way.length; w++) for (let i = 1; i <= 6; i++) path.push(way[w - 1] + (way[w] - way[w - 1]) * i / 6);
path.splice(64, 0, path[63] + 4);                                     // the impulse inside the 95 -> 104 leg
for (let i = 64 + 1; i < path.length; i++) path[i] += 4;
const bars = path.map((c, i) => { const o = i ? path[i - 1] : 100; return {time: 1000 + i * 60, open: o, close: c,
  high: Math.max(o, c) + 0.1, low: Math.min(o, c) - 0.1}; });
"""


def test_smc_swings_structure_and_zones_on_synthetic_candles():
    out = _node(SYN + """
      const r = S.smcAll(bars);
      const piv = S.swings(bars, 3);
      // a pivot is higher / lower than the 3 bars on each side
      const okPiv = piv.every((q) => { for (let j = q.i - 3; j <= q.i + 3; j++) { if (j === q.i) continue;
        if (q.kind === "H" && bars[j].high > q.price) return false; if (q.kind === "L" && bars[j].low < q.price) return false; } return true; });
      const zzAlt = r.zz.every((q, i) => !i || q.kind !== r.zz[i - 1].kind);
      console.log(JSON.stringify({n: bars.length, okPiv, nPiv: piv.length, zzAlt, structure: r.structure, obs: r.obs, fvgs: r.fvgs,
        liq: r.liq, range: r.range, trend: r.trend, legs: r.legs, all: S.structure(bars, piv, 3).map((x) => [x.kind, x.dir]),
        gaps: S.fairValueGaps(bars, 0.5).filter((g) => g.dir > 0).map((g) => g.i),
        empty: S.smcAll(bars.slice(0, 10))}));""")
    assert out["okPiv"] and out["nPiv"] > 6 and out["zzAlt"]
    # the downtrend's breaks are BoS down; the first break up against it is a CHoCH; the next ones up are BoS
    assert out["all"] == [["BoS", -1], ["BoS", -1], ["CHoCH", 1], ["BoS", 1], ["BoS", 1]]
    assert 64 in out["gaps"]                                # the impulsive bar's fair value gap
    for s in out["structure"]:
        assert s["kind"] in ("BoS", "CHoCH") and s["dir"] in (1, -1) and s["from"] < s["to"]
    assert len(out["structure"]) <= 3 and len(out["fvgs"]) <= 2 and len(out["obs"]) <= 2
    assert out["fvgs"], "the impulsive bar leaves a gap"
    for g in out["fvgs"]:
        assert g["top"] > g["bot"]
    for o in out["obs"]:
        assert o["top"] > o["bot"] and o["alive"]
    for q in out["liq"]:
        assert q["kind"] in ("BSL", "SSL")
    rg = out["range"]
    assert rg and rg["hi"] > rg["eq"] > rg["lo"] and rg["eq"] == pytest.approx((rg["hi"] + rg["lo"]) / 2)
    lo_o, hi_o = sorted(rg["ote"])
    assert rg["lo"] < lo_o < hi_o < rg["hi"]
    span = rg["hi"] - rg["lo"]
    if rg["up"]:                                            # the last leg went up: OTE is the 62-79 % pullback
        assert rg["ote"][0] == pytest.approx(rg["hi"] - 0.62 * span) and rg["ote"][1] == pytest.approx(rg["hi"] - 0.79 * span)
    else:
        assert rg["ote"][0] == pytest.approx(rg["lo"] + 0.62 * span) and rg["ote"][1] == pytest.approx(rg["lo"] + 0.79 * span)
    assert 1 <= len(out["trend"]) <= 2 and len(out["legs"]) <= 5
    for g in out["legs"]:
        assert g["pct"] == pytest.approx((g["p2"] - g["p1"]) / g["p1"])
    assert out["empty"]["structure"] == [] and out["empty"]["range"] is None


def test_smc_fvg_and_liquidity_basics():
    out = _node("""
      const B = (o, h, l, c, i) => ({time: i, open: o, high: h, low: l, close: c});
      const gap = [B(10, 10.2, 9.9, 10.1, 0), B(10.1, 11, 10.1, 10.9, 1), B(10.9, 11.4, 10.6, 11.3, 2)];   // 10.2 < 10.6
      const filled = [...gap, B(11.3, 11.3, 10.1, 10.2, 3)];
      const piv = [{i: 1, price: 12, kind: "H"}, {i: 2, price: 9, kind: "L"}];
      const bars = [B(10, 10.5, 9.5, 10, 0), B(10, 12, 10, 11, 1), B(11, 11, 9, 9.5, 2), B(9.5, 11.5, 9.6, 11, 3)];
      console.log(JSON.stringify({open: S.fairValueGaps(gap), filled: S.fairValueGaps(filled), liq: S.liquidity(bars, piv)}));""")
    assert out["open"] == [{"dir": 1, "i": 1, "top": 10.6, "bot": 10.2}]
    assert out["filled"] == []
    assert out["liq"] == [{"kind": "BSL", "i": 1, "price": 12}, {"kind": "SSL", "i": 2, "price": 9}]


# ---------------------------------------------------------------- our position lines (node)
def test_position_pills_read_like_the_reference_and_deepseek_has_no_money():
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    scr = "file://" + os.path.join(V4, "screens")
    body = f"""const L = await import('{scr}/chart-lines.js');
      const pos = (side, entry, stop, lock) => ({{symbol: "BTCUSDT", side, qty: 1, entry, leverage: 30, margin: entry / 30, stop, lock_roe: lock}});
      const a = (id, kind, p) => ({{account_id: id, kind, timeframe: "15m", strategy: "S" + id, position: p}});
      const accts = [a("A@15m", "strategy", pos(-1, 100, 102, null)), a("B@15m", "strategy", pos(-1, 100.02, 101, 0.1)),
        a("C@15m", "strategy", pos(-1, 100.03, null, null)), a("D@15m", "ds200", pos(1, 90, 88, null))];
      const out = L.posLines(accts, 102.5, {{stops: 6}});
      console.log(JSON.stringify(out));"""
    r = subprocess.run([node, "--input-type=module", "-e", body], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    entries = [x for x in out if x["group"] == "pos"]
    risk = [x for x in out if x["group"] == "risk"]
    three = next(x for x in entries if x["price"] == 100)
    # '숏 30배 · 3개 · −2.5%' + chips 잠금 · 손절 (the group's unrealized ROE at the mark price)
    assert three["pill"]["text"].startswith("숏 30배 · 3개 · −") and three["tone"] == "down"
    assert [c["text"] for c in three["pill"]["chips"]] == ["잠금", "손절"]
    assert three["axis"] is True and three["dash"] == 0
    ds = next(x for x in entries if x["price"] == 90)
    assert ds["pill"]["text"] == "롱 30배" and ds["tone"] == "flat"               # DeepSeek: counted, no money
    assert "개수만" in ds["pill"]["title"]
    assert all(x["dash"] == 1 and x["axis"] is False and x["parent"] for x in risk)
    assert {x["label"] for x in risk} == {"잠금", "손절"}


# ---------------------------------------------------------------- the deck (source checks)
def test_deck_lines_are_thin_out_of_the_autoscale_and_click_to_hide_is_remembered():
    fx = _code(_read("core", "chartfx.js"))
    # drawn by series primitives: none of them offers autoscaleInfo, so the candles alone set the price range
    assert "autoscaleInfo" not in fx and "autoscaleInfo" not in _code(_read("core", "smcdraw.js"))
    assert "createPriceLine" not in _code(_read("screens", "terminal-chart.js")) and "createPriceLine" not in _code(_read("screens", "chart.js"))
    assert "c.lineWidth = lw;" in fx and "Math.max(1, Math.round(vr))" in fx                     # 1 device-independent px
    # pills: left edge, the --t-2xs size; a click (or ×) hides the line; per device through dom.js local (try/catch)
    css = _read("core", "chartfx.css")
    assert re.search(r"\.cfx-pill \{[^}]*left: 6px;[^}]*font: 600 var\(--t-2xs\)", css, re.S)
    assert 'onclick: () => hideLine(sp.id)' in fx and '"aria-label": "이 선 숨기기"' in fx
    assert "local.get(key" in fx and "local.set(key" in fx and "localStorage" not in fx
    # offset, then merged (+N), never overlapping; off-range lines become ▲ / ▼ edge markers with the price
    assert "PILL_H * 1.6" in fx and "`+${more.length}`" in fx
    assert 'paintEdge(edgeTop, above, "▲")' in fx and 'paintEdge(edgeBot, below, "▼")' in fx
    # the '선' menu groups and 모두 보기 / 모두 숨기기
    for w in ("포지션 선", "손절·잠금", "지지·저항", "프리미엄 지표", "경제지표", "거래량", "모두 보기", "모두 숨기기"):
        assert w in fx, w
    for scr in ("terminal-chart.js", "chart.js"):
        assert 'groups: ["pos", "risk", "sr", "smc", "ev", "vol"]' in _read("screens", scr), scr


def test_light_is_the_ai_skins_only_and_never_animates_on_a_timer():
    fx = _code(_read("core", "chartfx.js"))
    assert 'document.documentElement.dataset.skin !== "classic"' in fx
    assert "if (!o.ai() || !gv.bars.length) return;" in fx                   # candle glow
    assert "if (!st.ai) { under.dataset.amb" in fx                           # ambient
    assert "flash(ev) { if (st.ai) sched.push(ev); }" in fx                  # event flash
    assert "setInterval" not in fx
    css = _read("core", "chartfx.css")
    assert '.cfx[data-fx="plain"] .cfx-under { display: none; }' in css
    assert "transition: opacity 1.2s" in css and "infinite" not in css
    rm = css[css.index("@media (prefers-reduced-motion: reduce)"):]
    assert ".cfx-amb { transition: none; }" in rm and ".cfx-tag[data-hit] { animation: none; }" in rm
    # the legend in the chart header (the light chip's tooltip) and the '번쩍임' setting
    assert "빨간 빛 = 가격이 50봉 평균 아래 / 하늘색 = 위" in fx
    assert "하늘색 번쩍 = 큰 매수·숏 청산, 빨간 번쩍 = 큰 매도·롱 청산 (바이낸스 실제 체결)" in fx
    assert '"aria-label": "번쩍임"' in fx and 'FLASH_KEY = "chart-flash"' in fx
    # 클래식: the light tokens are transparent
    tok = _read("tokens.css")
    classic = tok[:tok.index(":root:not([data-skin=\"classic\"])")]
    for k in ("--amb-up", "--amb-down", "--flash-up", "--flash-down", "--depth-top"):
        assert re.search(re.escape(k) + r":\s*transparent;", classic), k


def test_flash_sources_are_real_events_only():
    term, feed, chart = _read("screens", "terminal.js"), _read("screens", "terminal-feed.js"), _read("screens", "chart.js")
    # the relay's new big rows of the coin on screen (never the first message: that is the past)
    assert "if (!m.first && m.big && Array.isArray(m.big.rows)) for (const r of m.big.rows) if (r && r.s === st.sym) chart.onBig(r);" in term
    assert "if (!m.first && m.big && Array.isArray(m.big.rows))" in chart and "deck.flash(bigEvent(r))" in chart
    # new market liquidations only (seen keys), our own fills
    assert "if (isNew) arrived.push(r);" in feed and "onNew(arrived)" in feed
    assert "if (st.liqSeen)" in chart and "deck.flash(liqEvent(r))" in chart
    assert "deck.flash(ownEvent())" in chart and "deck.flash(ownEvent())" in _read("screens", "terminal-chart.js")


def test_fonts_and_colours_are_tokens():
    for f in ("chartfx.js", "smcdraw.js", "smc.js", "flash.js"):
        src = _read("core", f)
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", _code(src)), f
        assert not re.search(r"\brgba?\(\s*\d", src), f
    fx = _read("core", "chartfx.js")
    assert '["fs", "--t-2xs"]' in fx and "const fontOf = (col, vr, w = 600) => `${w} ${col.fs * vr}px ${col.font}`;" in _read("core", "smcdraw.js")


def test_candles_api_carries_volume():
    app = open(os.path.join(ROOT, "paperbot", "dash", "app.py"), encoding="utf-8").read()
    assert '"close": float(k[4]), "volume": float(k[5])}' in app
    fx = _read("core", "chartfx.js")
    assert 'addHistogramSeries({priceScaleId: "cfxvol"' in fx and "scaleMargins: {top: 0.86, bottom: 0}" in fx

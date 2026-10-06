"""The chart deck (owners 10/06, from the HelloQuant reference: "선이 너무 크고 투박하다 · 누르면 숨기게 · 차트가
비어 보인다 · 간지나게 · 번쩍임 많이 자주"): core/chartfx.js on the terminal chart and the 차트 screen.

- glow / ambient / flash are the AI skin's only (클래식 stays plain), motion follows real events only, never a timer;
- the flash scheduler (core/flash.js): rate limit per '번쩍임' mode, the biggest waiting event wins, stale events drop,
  reduced motion and 끄기 play nothing, 고래 / large liquidations hold longer (node);
- the light (owners 10/06: the reference splits the pane): red Premium above the current dealing range's
  equilibrium, sky-blue Discount below (fallback: the middle of the visible high / low), following the price scale;
- the light BLINKS (owners 10/06 13:27 "나타났다가 안나타났다가 ... 깜박깜박", core/blink.js, node): a real relay event
  lights one half (sell -> the red top, buy -> the cyan bottom, a bigger bucket brighter and longer), the halves are
  independent and go dark between blinks, a soft decorative blink only after 2 s without an event, '조명 깜박 / 계속
  켜짐 / 끄기' per device, calm slow fades under reduced motion, nothing while the page is hidden;
- the page's ONE relay connection (core/ticks.js, node): every listener (sound, terminal, chart light) shares it, it
  closes while the page is hidden and when the last listener leaves, a late listener gets the kept large orders;
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
    script = (f"const F = await import('{core}/flash.js'); const S = await import('{core}/smc.js');\n"
              f"const BL = await import('{core}/blink.js'); const TK = await import('{core}/ticks.js');\n" + body)
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


# ---------------------------------------------------------------- the steady Premium / Discount light
def test_split_is_the_dealing_range_equilibrium_else_the_visible_middle():
    out = _node("""
      const B = (h, l) => ({open: (h + l) / 2, close: (h + l) / 2, high: h, low: l});
      const vis = [B(110, 100), B(130, 104), B(108, 90)];
      console.log(JSON.stringify({rng: S.splitOf({hi: 120, lo: 80, eq: 100}, vis), mid: S.splitOf(null, vis),
        flat: S.splitOf({hi: 5, lo: 5, eq: 5}, vis), none: S.splitOf(null, []),
        z: [S.zoneOf(101, 100), S.zoneOf(100, 100), S.zoneOf(99.9, 100)]}));""")
    assert out["rng"] == {"eq": 100, "hi": 120, "lo": 80, "src": "range"}
    assert out["mid"] == {"eq": 110, "hi": 130, "lo": 90, "src": "mid"}                # no range: the visible middle
    assert out["flat"]["src"] == "mid" and out["none"] is None
    assert out["z"] == ["premium", "premium", "discount"]


def test_split_light_red_above_cyan_below_follows_the_price_scale():
    fx = _code(_read("core", "chartfx.js"))
    place = fx[fx.index("function placeSplit()"):fx.index("const lineWords")]
    # the split price is the current dealing range's equilibrium (core/smc.js), placed with the series' own scale on
    # every redraw (pan / zoom / data); the range is recomputed only on a new closed bar
    assert "splitOf(st.range, vis)" in place and "series.priceToCoordinate(sp.eq)" in place
    assert 'under.style.setProperty("--split", Y + "px")' in place
    assert "placeSplit();" in fx[fx.index("function place()"):fx.index("function layoutPills()")]
    assert "if (isNew) computeSmc();" in fx and "st.range = r && r.range;" in fx
    assert "const need = shown(\"smc\") || st.ai;" in fx                      # the light works with the indicator off
    css = _read("core", "chartfx.css")
    red = re.search(r'\.cfx-amb\[data-tone="down"\] \{([^}]*)\}', css).group(1)
    cyan = re.search(r'\.cfx-amb\[data-tone="up"\] \{([^}]*)\}', css).group(1)
    assert "top: 0" in red and "height: calc(var(--split, 50%) + 24px)" in red and "linear-gradient(to bottom, var(--amb-down)" in red
    assert "top: calc(var(--split, 50%) - 24px)" in cyan and "bottom: 0" in cyan and "linear-gradient(to top, var(--amb-up)" in cyan
    assert "transparent)" in red and "transparent)" in cyan                     # each half feathers out past the seam
    assert '"Premium"' in fx and '"Discount"' in fx and ".cfx-zw" in css and "right: 64px" in css
    # with the AI light on, the indicator does not tint the halves a second time; the words are opt-in (owners 10/06
    # ~14:00, the calm default: 프리미엄 지표 ▾ › Premium·Discount 글자; tests/test_dash_declutter.py)
    assert 'words: P.has("words") && !st.ai, tint: !st.ai' in fx and "if (d.words) {" in _read("core", "smcdraw.js")
    assert '.cfx-under:not([data-words="1"]) > .cfx-zw { display: none; }' in css


# ---------------------------------------------------------------- the blinking halves (core/blink.js)
BLINK = """
const mk = (o = {}) => {
  const st = {t: 0, timers: [], log: [], src: [], vis: true, mode: o.mode || "blink", reduced: !!o.reduced};
  let seed = o.seed || 7;
  const rand = () => { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646; };
  const b = BL.blinker({now: () => st.t, rand, reduced: () => st.reduced, visible: () => st.vis, mode: () => st.mode,
    setTimer: (fn, ms) => { const x = {fn, at: st.t + ms}; st.timers.push(x); return x; },
    clearTimer: (x) => { st.timers = st.timers.filter((y) => y !== x); },
    apply: (half, k, ms, kind) => st.log.push({t: st.t, half, k: Math.round(k * 1000) / 1000, ms, kind}),
    onSrc: (s) => st.src.push([st.t, s])});
  const run = (until) => {
    for (;;) {
      st.timers.sort((a, z) => a.at - z.at);
      const x = st.timers[0];
      if (!x || x.at > until) break;
      st.timers.shift(); st.t = Math.max(st.t, x.at); x.fn();
    }
    st.t = until;
  };
  return {b, st, run};
};
// the blinks of one half from the log: [{on: t of the rise, k, off: t the fade started, dark: t it was dark}]
const blinks = (log, half) => {
  const out = []; let cur = null;
  for (const e of log.filter((x) => x.half === half)) {
    if (e.k > 0 && e.kind === "in") { if (!cur) { cur = {on: e.t, k: e.k}; out.push(cur); } else cur.k = Math.max(cur.k, e.k); }
    else if (e.k === 0 && cur) { cur.off = e.t; cur.dark = e.t + e.ms; cur = null; }
  }
  return out;
};
"""


def test_light_modes_steady_off_and_blink():
    out = _node(BLINK + """
      const SM = mk({mode: "steady"}); const s1 = SM.b.sync();
      const O = mk({mode: "off"}); const o1 = O.b.sync();
      const K = mk(); const k1 = K.b.sync();
      const before = K.st.log.filter((e) => e.k > 0).length, timers = K.st.timers.length;
      K.st.mode = "steady"; const k2 = K.b.sync();
      console.log(JSON.stringify({s1, steady: SM.st.log, sT: SM.st.timers.length, o1, off: O.st.log, oT: O.st.timers.length,
        k1, before, timers, k2, after: K.st.log.slice(-2), kT: K.st.timers.length,
        modes: BL.LIGHT_MODES.map((m) => [m.id, m.ko]), def: BL.DEFAULT_LIGHT, bad: BL.lightModeOf("x").id, steadyK: BL.STEADY_K}));""")
    assert out["modes"] == [["blink", "깜박"], ["steady", "계속 켜짐"], ["off", "끄기"]] and out["def"] == "blink" and out["bad"] == "blink"
    # 계속 켜짐: both halves at the old steady strength, no timer at all
    assert out["s1"] == "steady" and out["sT"] == 0 and {(e["half"], e["k"]) for e in out["steady"]} == {("top", 0.56), ("bottom", 0.56)}
    # 끄기: both dark, no timer
    assert out["o1"] == "off" and out["oT"] == 0 and all(e["k"] == 0 for e in out["off"])
    # 깜박: starts dark (nothing lights at once), one timer per half
    assert out["k1"] == "blink" and out["before"] == 0 and out["timers"] == 2
    # a switch to 계속 켜짐 stops the timers and shows both halves steady
    assert out["k2"] == "steady" and out["kT"] == 0 and all(e["k"] == 0.56 for e in out["after"])


def test_relay_event_maps_sell_to_the_red_top_buy_to_the_cyan_bottom_bigger_is_brighter_and_longer():
    out = _node(BLINK + """
      const R = (side, b, s = "BTCUSDT") => BL.relayBlink({s, side, b}, "BTCUSDT");
      const map = {sell: R("sell", 2), buy: R("buy", 2), mine: [1, 2, 3, 4].map((b) => R("buy", b)), other: [1, 2, 3, 4].map((b) => R("sell", b, "ETHUSDT")),
        bad: [R("up", 2), BL.relayBlink(null), R("buy", undefined), R("buy", 9)], nosym: BL.relayBlink({s: "ETHUSDT", side: "buy", b: 1}, null)};
      // the halves are independent: a sell lights only the top, a buy only the bottom
      const A = mk(); A.b.sync();
      A.st.t = 100; const r1 = A.b.real(R("sell", 4));
      A.st.t = 300; const r2 = A.b.real(R("buy", 1));
      A.run(4000);
      console.log(JSON.stringify({map, r1, r2, top: blinks(A.st.log, "top"), bot: blinks(A.st.log, "bottom"), log: A.st.log.filter((e) => e.k > 0)}));""")
    m = out["map"]
    assert m["sell"]["half"] == "top" and m["buy"]["half"] == "bottom"
    ks, holds = [x["k"] for x in m["mine"]], [x["hold"] for x in m["mine"]]
    assert ks == sorted(ks) and holds == sorted(holds) and len(set(ks)) == 4          # bigger bucket: brighter, longer
    assert m["mine"][3]["k"] == 1 and m["mine"][3]["hold"] == 1200                      # b 4: the strongest flash
    assert m["other"][0] is None                                                         # another coin's smallest: skipped
    assert all(o["k"] < x["k"] and o["hold"] < x["hold"] for o, x in zip(m["other"][1:], m["mine"][1:]))
    assert m["bad"][0] is None and m["bad"][1] is None and m["bad"][2]["b"] == 1 and m["bad"][3]["b"] == 4
    assert m["nosym"]["k"] == 0.55                                                       # no coin given: full strength
    assert out["r1"] is True and out["r2"] is True
    top, bot = out["top"], out["bot"]
    # b 4 sell: the top rises in 0.2 s at full strength, holds 1.2 s, fades in 0.4 s; the bottom blinks on its own
    assert top[0] == {"on": 100, "k": 1, "off": 100 + 200 + 1200, "dark": 100 + 200 + 1200 + 400}
    assert bot[0]["on"] == 300 and bot[0]["k"] == 0.55 and bot[0]["off"] == 300 + 200 + 400
    first = [e for e in out["log"] if e["t"] == 100][0]
    assert first == {"t": 100, "half": "top", "k": 1, "ms": 200, "kind": "in"}


def test_a_lit_half_goes_dark_before_the_next_real_blink_and_a_stronger_event_only_brightens_it():
    out = _node(BLINK + """
      const A = mk(); A.b.sync();
      const R = (b) => BL.relayBlink({s: "BTCUSDT", side: "sell", b}, "BTCUSDT");
      A.st.t = 0; A.b.real(R(1));                  // lights the top (0.55)
      A.st.t = 150; const up = A.b.real(R(3));     // stronger while lit: brighter at once, same end
      A.st.t = 300; const wait = A.b.real(R(2));   // weaker while lit: waits for the dark gap
      const pending = A.b.half("top").wait && A.b.half("top").wait.k;
      A.run(6000);
      // a sell every 100 ms for 10 s: the top still goes dark between blinks
      const C = mk(); C.b.sync();
      for (let t = 0; t < 10000; t += 100) { C.run(t); C.b.real(R(2)); }
      C.run(13000);
      // an event that waits longer than 1.5 s is dropped (not "now" any more)
      const D = mk(); D.b.sync();
      D.st.t = 0; D.b.real(R(4)); D.st.t = 50; D.b.real(R(1));       // waits behind a 1.8 s blink + the gap
      D.run(8000);
      console.log(JSON.stringify({up, wait, pending, A: blinks(A.st.log, "top"), raise: A.st.log.filter((e) => e.ms === 120),
        C: blinks(C.st.log, "top"), D: blinks(D.st.log, "top"), dark: [...BL.FAST.dark]}));""")
    assert out["up"] is True and out["wait"] is False and out["pending"] == 0.7
    assert out["raise"] == [{"t": 150, "half": "top", "k": 0.85, "ms": 120, "kind": "in"}]
    a = out["A"]
    assert a[0]["on"] == 0 and a[0]["off"] == 200 + 400                                 # the raise keeps the end
    assert a[1]["on"] >= a[0]["dark"] + out["dark"][0]                                    # then the waiting one, after the gap
    c = out["C"]
    assert len(c) >= 4
    for x, y in zip(c, c[1:]):
        assert y["on"] - x["dark"] >= out["dark"][0]                                      # dark between every two blinks
        assert x["off"] - x["on"] <= 200 + 1200                                           # never on for long
    assert len([x for x in out["D"] if x["k"] > 0.5]) == 1                                # the stale one never played
    assert all(x["k"] <= 0.45 for x in out["D"][1:])                                      # (later: the soft fallback)


def test_fallback_blinks_softly_and_irregularly_only_after_two_quiet_seconds():
    out = _node(BLINK + """
      const A = mk({seed: 11}); A.b.sync();
      A.run(30000);
      const B2 = mk({seed: 5}); B2.b.sync();
      // real events every 400 ms for 8 s (alternating sides): no decorative blink in between
      for (let t = 0; t < 8000; t += 400) { B2.run(t); B2.b.real(BL.relayBlink({s: "BTCUSDT", side: t % 800 ? "buy" : "sell", b: 2}, "BTCUSDT")); }
      B2.run(20000);
      console.log(JSON.stringify({top: blinks(A.st.log, "top"), bot: blinks(A.st.log, "bottom"), src: A.st.src,
        rtop: blinks(B2.st.log, "top"), rbot: blinks(B2.st.log, "bottom"), rsrc: B2.st.src, deco: BL.FAST.deco}));""")
    top, bot, deco = out["top"], out["bot"], out["deco"]
    assert len(top) >= 5 and len(bot) >= 5                                               # it never just sits there
    assert min(top[0]["on"], bot[0]["on"]) >= 2000                                        # not before 2 quiet seconds
    for x in top + bot:
        assert deco["k"][0] <= x["k"] <= deco["k"][1]                                     # soft (real ones go to 1)
        assert x["off"] - x["on"] <= 200 + deco["hold"][1] and "dark" in x               # and it always goes dark again
    ons = sorted([x["on"] for x in top] + [x["on"] for x in bot])
    gaps = {round(b - a) for a, b in zip(ons, ons[1:])}
    assert len(gaps) > 5                                                                   # irregular moments
    assert {x["on"] for x in top} != {x["on"] for x in bot}                               # the halves are independent
    assert out["src"][0][1] == "deco"
    # with real events coming, every blink is a real one (k 0.7 = b 2); the decorative ones start 2 s after the last
    real_end = 7600
    for x in out["rtop"] + out["rbot"]:
        assert x["k"] == 0.7 or x["on"] >= real_end + 2000, x
    assert any(x["on"] >= real_end + 2000 for x in out["rtop"] + out["rbot"])             # ... and come back after
    assert out["rsrc"][0][1] == "real" and out["rsrc"][-1][1] == "deco"


def test_hidden_page_pauses_every_timer_and_resumes_when_shown():
    out = _node(BLINK + """
      const A = mk(); A.b.sync();
      A.st.t = 10; A.b.real(BL.relayBlink({s: "BTCUSDT", side: "sell", b: 4}, "BTCUSDT"));
      A.st.t = 50; A.st.vis = false; const s1 = A.b.sync();
      const timers = A.st.timers.length, last = A.st.log.slice(-2);
      const n = A.st.log.length;
      A.st.t = 100; const r = A.b.real(BL.relayBlink({s: "BTCUSDT", side: "buy", b: 4}, "BTCUSDT"));
      A.run(20000);
      const quiet = A.st.log.length - n, timers2 = A.st.timers.length;
      A.st.vis = true; const s2 = A.b.sync();
      const timers3 = A.st.timers.length;
      A.run(30000);
      const back = blinks(A.st.log.slice(n), "top").concat(blinks(A.st.log.slice(n), "bottom")).map((x) => x.on).sort((a, b) => a - b);
      console.log(JSON.stringify({s1, timers, last, r, quiet, timers2, s2, timers3, back}));""")
    assert out["s1"] == "paused" and out["timers"] == 0                                   # hidden: no timer left
    assert all(e["k"] == 0 and e["ms"] == 0 for e in out["last"])                        # both halves dark at once
    assert out["r"] is False and out["quiet"] == 0 and out["timers2"] == 0               # nothing plays or waits
    assert out["s2"] == "blink" and out["timers3"] == 2
    assert out["back"] and out["back"][0] >= 20000 + 2000                                 # shown again: dark, then blinks


def test_reduced_motion_is_a_calm_slow_fade():
    out = _node(BLINK + """
      const A = mk({reduced: true}); A.b.sync();
      const R = (b) => BL.relayBlink({s: "BTCUSDT", side: "sell", b}, "BTCUSDT");
      A.st.t = 0; A.b.real(R(4));
      A.st.t = 300; const up = A.b.real(R(4));
      for (let t = 400; t < 20000; t += 300) { A.run(t); A.b.real(R(4)); }
      A.run(26000);
      const Q = mk({reduced: true, seed: 3}); Q.b.sync(); Q.run(40000);
      console.log(JSON.stringify({up, top: blinks(A.st.log, "top"), ins: A.st.log.filter((e) => e.k > 0).map((e) => e.ms),
        outs: A.st.log.filter((e) => e.k === 0 && e.ms).map((e) => e.ms), deco: blinks(Q.st.log, "top").concat(blinks(Q.st.log, "bottom")),
        calm: BL.CALM}));""")
    calm, top = out["calm"], out["top"]
    assert out["up"] is False                                                             # no quick brighten
    assert set(out["ins"]) == {calm["inMs"]} and calm["inMs"] >= 1000                   # slow rise
    assert set(out["outs"]) <= {calm["outMs"], 300} and calm["outMs"] >= 1500            # slow fade
    assert all(x["k"] <= calm["kMax"] for x in top)
    for x, y in zip(top, top[1:]):
        assert y["on"] - x["dark"] >= calm["dark"][0] >= 2500                             # seconds of dark between
    assert len(top) <= 6                                                                   # ~20 s of a flood: a few fades
    for x in out["deco"]:
        assert x["k"] <= calm["deco"]["k"][1]


def test_the_page_has_one_relay_connection_closed_while_hidden_and_after_the_last_listener():
    out = _node("""
      const made = [];
      globalThis.EventSource = class { constructor(u) { this.url = u; this.readyState = 0; this.closed = false; made.push(this); }
        close() { this.closed = true; this.readyState = 2; } };
      let visH = null;
      globalThis.document = {hidden: false, addEventListener(ev, fn) { if (ev === "visibilitychange") visH = fn; }};
      const out = {}, a = [], b = [], c = [];
      const offA = TK.listenTicks((m) => a.push(m)), offB = TK.listenTicks((m) => b.push(m));
      out.one = made.length; out.url = made[0].url;
      const big1 = {rows: [{t: 1, s: "BTCUSDT", side: "buy", usd: 2e5, p: 1}], buy: 2e5, sell: 0, min: {BTCUSDT: 150000}, whale_x: 4};
      made[0].onmessage({data: JSON.stringify({state: "live", ev: [], big: big1})});
      made[0].onmessage({data: JSON.stringify({state: "live", ev: [{s: "ETHUSDT", side: "sell", b: 3}],
        big: {rows: [{t: 2, s: "ETHUSDT", side: "sell", usd: 9e4, p: 2}], buy: 2e5, sell: 9e4}})});
      out.firsts = a.map((m) => m.first); out.b = b.length;
      const offC = TK.listenTicks((m) => c.push(m));                 // a late listener: a catch-up, no new connection
      await new Promise((r) => setTimeout(r, 0));
      out.c = c; out.stillOne = made.length;
      document.hidden = true; visH();
      out.hidden = {closed: made[0].closed, st: TK.ticksState(), n: made.length};
      document.hidden = false; visH();
      out.shown = made.length;
      offA(); offB(); out.twoOff = made[1].closed;
      offC(); out.allOff = made[1].closed; out.st = TK.ticksState();
      const offD = TK.listenTicks(() => {});
      made[2].readyState = 2; made[2].onerror();
      out.retry = {es: TK.hub.es === null, t: !!TK.hub.retryT, ms: TK.hub.retryMs};
      offD(); out.cleared = TK.hub.retryT; out.total = made.length;
      console.log(JSON.stringify(out));""")
    assert out["one"] == 1 and out["url"] == "/api/v4/ticks"                             # two listeners, one connection
    assert out["firsts"] == [True, False] and out["b"] == 2
    c = out["c"]
    assert out["stillOne"] == 1 and len(c) == 1 and c[0]["first"] is True and c[0]["ev"] == []
    assert [r["t"] for r in c[0]["big"]["rows"]] == [2, 1] and c[0]["big"]["min"] == {"BTCUSDT": 150000} and c[0]["big"]["sell"] == 90000
    assert out["hidden"] == {"closed": True, "st": "off", "n": 1}                         # hidden: closed
    assert out["shown"] == 2                                                              # shown: one new connection
    assert out["twoOff"] is False and out["allOff"] is True and out["st"] == "off"       # the last listener closes it
    assert out["retry"] == {"es": True, "t": True, "ms": 60000}                           # refused: asked again later
    assert out["cleared"] is None and out["total"] == 3


def test_every_relay_listener_uses_the_one_connection_and_the_light_listens_only_while_it_blinks():
    fx = _code(_read("core", "chartfx.js"))
    relay = fx[fx.index("function relaySync()"):fx.index("const radio = (label")]
    assert 'if (!m || m.state !== "live" || !Array.isArray(m.ev)) return;' in relay      # only a live relay's events
    assert "for (const ev of m.ev) blink.real(relayBlink(ev, sym));" in relay
    assert "relayOff = listenTicks(" in relay and "off();" in relay
    assert 'ctx.listen(document, "visibilitychange", () => blink.sync());' in fx          # hidden: the halves pause
    assert "blink.stop(); if (relayOff) { relayOff(); relayOff = null; }" in fx          # the screen left: all stops
    assert "function lightSync() { under.dataset.light = st.ai ? lmode : \"off\"; blink.sync(); relaySync(); paintLight(); }" in fx
    # one EventSource for the relay on the whole page: only core/ticks.js opens it (core/api.js has the board stream)
    v4 = os.path.join(V4)
    for d, _, files in os.walk(v4):
        for f in files:
            if not f.endswith(".js"):
                continue
            src = _code(open(os.path.join(d, f), encoding="utf-8").read())
            rel = os.path.relpath(os.path.join(d, f), v4)
            if "/api/v4/ticks" in src:
                assert rel == os.path.join("core", "ticks.js"), rel
            if "EventSource" in src:
                assert rel in (os.path.join("core", "ticks.js"), os.path.join("core", "api.js")), rel
    assert "listenTicks" in _read("core", "sound.js") and "listenTicks" in _read("screens", "terminal-live.js")


def test_light_button_stays_short_where_its_full_label_would_push_the_terminal_header_past_its_edge():
    # measured in a browser (1920 px window): the terminal's chart header fits '조명 깜박 · 번쩍임 자주 ▾' from 1700 px at
    # 글자 크기 보통 and from 1840 px at 크게; at 아주 크게 it never fits (it cut off 일 / 차트 화면 at 1920 px, which the old
    # 번쩍임 select did not), so there the button keeps the short '조명 깜박 ▾' (the flash setting stays in the menu)
    fx = _code(_read("core", "chartfx.js"))
    assert 'h("span", {class: "cfx-lf"}, " · 번쩍임 ", fNow)' in fx
    css = _read("core", "chartfx.css")
    assert "@media (max-width: 1699px) { .cfx-lbtn .cfx-lf { display: none; } }" in css
    assert '@media (max-width: 1839px) { html[data-text="lg"] .cfx-lbtn .cfx-lf { display: none; } }' in css
    assert 'html[data-text="xl"] .cfx-lbtn .cfx-lf { display: none; }' in css
    # phones: the menu is a sheet above the bottom tab bar (its own token, not a copied number)
    assert "bottom: calc(var(--bot-h) + 14px + env(safe-area-inset-bottom, 0px));" in css


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


def test_light_is_the_ai_skins_only_and_its_motion_is_the_blinkers():
    fx = _code(_read("core", "chartfx.js"))
    assert 'document.documentElement.dataset.skin !== "classic"' in fx
    assert "if (!o.ai() || !gv.bars.length) return;" in fx                   # candle glow
    assert 'if (!st.ai || !st.data.length) { under.dataset.split = ""; return; }' in fx    # the split light
    assert "flash(ev) { if (st.ai) sched.push(ev); }" in fx                  # event flash
    assert 'mode: () => (st.ai && !gone() ? lmode : "off")' in fx            # 클래식: the halves never blink
    assert "const want = st.ai && lmode === \"blink\" && !gone();" in fx     # ... and no relay listener for them
    # a deck built after its screen was left starts nothing (ctx.track would never clean it up)
    assert 'const gone = () => !!(ctx && typeof ctx.alive === "function" && !ctx.alive());' in fx
    assert "setInterval" not in fx and "setInterval" not in _code(_read("core", "blink.js"))
    assert "requestAnimationFrame" not in _code(_read("core", "blink.js"))
    # each blink is one CSS opacity transition on its own layer, set by the blinker's apply (no canvas work per blink)
    # (inline !important: the reduced-motion rule in components.css would turn the calm fade into an abrupt on / off)
    assert 'el.style.setProperty("transition", ms > 0 ? `opacity ${Math.round(ms)}ms ${kind === "in" ? "ease-out" : "ease-in"}` : "none", "important");' in fx
    assert "*, *::before, *::after { animation: none !important; transition: none !important;" in _read("components.css")
    assert "el.style.opacity = String(Math.round(k * 1000) / 1000);" in fx
    assert "const halfEl = {top: ambDn, bottom: ambUp};" in fx               # tone down = red = Premium top
    css = _read("core", "chartfx.css")
    css_code = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    assert '.cfx[data-fx="plain"] .cfx-under { display: none; }' in css
    assert "infinite" not in css and "transition" not in css_code and "@keyframes cfx-amb" not in css   # inline only
    assert ".cfx-under > .cfx-amb { opacity: 0; will-change: opacity; }" in css
    assert '.cfx-under:not([data-split="1"]) > .cfx-amb { visibility: hidden; }' in css
    assert '.cfx-under[data-light="off"] > .cfx-zw' in css                  # 끄기: the words go with the light
    rm = css[css.index("@media (prefers-reduced-motion: reduce)"):]
    assert ".cfx-tag[data-hit] { animation: none; }" in rm
    # the legend in the chart header (the light chip's tooltip) and the '조명 · 번쩍임' menu
    assert "위쪽 빨간 빛 = Premium (지금 범위의 중간값 위) / 아래쪽 하늘색 = Discount (중간값 아래)" in fx
    assert "하늘색 번쩍 = 큰 매수·숏 청산, 빨간 번쩍 = 큰 매도·롱 청산 (바이낸스 실제 체결)" in fx
    assert '"aria-label": "조명과 번쩍임"' in fx and 'FLASH_KEY = "chart-flash"' in fx and 'LIGHT_KEY = "chart-light"' in fx
    # per device: read through local, written through core/prefs.js setPref (it stores under the same key, then every listener
    # follows: this deck's onPref(LIGHT_KEY) -> lightSync, the other decks, the 설정 panel's 차트 조명 row)
    assert "local.get(LIGHT_KEY, DEFAULT_LIGHT)" in fx and "setPref(LIGHT_KEY, lightModeOf(id).id)" in fx
    assert "onPref(LIGHT_KEY, (v) => {" in fx and "lmode = lightModeOf(v).id;" in fx
    assert "setPref(FLASH_KEY, modeOf(id).id)" in fx and "onPref(FLASH_KEY, (v) => {" in fx
    assert 'role: "menuitemradio"' in fx and "(기본)" in fx
    # the decorative blink is named as such, with no number: the chip says what the light follows right now
    raw = _read("core", "chartfx.js")
    # (the relay may be live while nothing it sends is followed: another coin's smallest are skipped, so the words say
    # "nothing to follow", not "no trades")
    assert 'LIGHT_DECO = "조명 깜박: 지금은 따라갈 체결이 2초 넘게 없어 은은한 장식 깜박 (시장 자료 아님)"' in raw
    assert "7개 코인 중 이 코인이 가장 밝게" in raw.split("LIGHT_REAL = ")[1].split("\n")[0]
    assert "blink.src() === \"real\" ? LIGHT_REAL : blink.src() === \"deco\" ? LIGHT_DECO" in fx
    # the 차트 screen keeps the old name for the control (flashSel); the terminal's narrow header has the same items in
    # one '보기 ▾' menu (owners 10/06 ~14:00: every timeframe button visible); both hand the deck the coin on screen
    assert "deck.flashSel" in _code(_read("screens", "chart.js"))
    assert "put(fxSlot, deck.lightChip, deck.viewBtn, deck.menuBtn);" in _code(_read("screens", "terminal-chart.js"))
    for scr in ("terminal-chart.js", "chart.js"):
        assert "sym: () => st.sym" in _read("screens", scr), scr
    # 클래식: the light tokens are transparent
    tok = _read("tokens.css")
    classic = tok[:tok.index(":root:not([data-skin=\"classic\"])")]
    for k in ("--amb-up", "--amb-down", "--amb-up-seam", "--amb-down-seam", "--flash-up", "--flash-down", "--depth-top"):
        assert re.search(re.escape(k) + r":\s*transparent;", classic), k


def test_flash_sources_are_real_events_only():
    term, feed, chart = _read("screens", "terminal.js"), _read("screens", "terminal-feed.js"), _read("screens", "chart.js")
    # the relay's new big rows of the coin on screen (never the first message: that is the past)
    assert "if (!m.first && m.big && Array.isArray(m.big.rows)) for (const r of m.big.rows) if (r && r.s === st.sym) chart.onBig(r);" in term
    assert "if (!m.first && m.big && Array.isArray(m.big.rows))" in chart and "deck.flash(bigEvent(r))" in chart
    # new market liquidations only (seen keys), our own fills
    assert "if (isNew && mine) arrived.push(r);" in feed and "onNew(arrived)" in feed   # new rows of the chosen coin only
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

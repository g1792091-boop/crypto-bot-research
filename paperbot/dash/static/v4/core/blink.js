// The chart's Premium / Discount light, blinking (owners 10/06 13:27, like the stream they watch: "계속 뜨게 하는게
// 아니라 ... 나타났다가 안나타났다가 ... 깜박깜박하는 느낌"). The pane stays split at the dealing range's equilibrium
// (core/smc.js splitOf, core/chartfx.js placeSplit); each half lights up and goes dark on its own: rises ~0.2 s, holds
// 0.4-1.2 s, fades ~0.4 s, then stays dark for a while. The two halves are independent, so they alternate and sometimes
// overlap.
//   real      while the server's market-trade relay is live (/api/v4/ticks through core/ticks.js: real Binance taker
//             trades of the 7 coins, about one event a second), each event lights ONE half: more taker SELLS -> the
//             red Premium top, more taker BUYS -> the sky-blue Discount bottom. A bigger size bucket (b 1-4, the
//             server's rank among recent events) is brighter and holds longer; b 4 is the strongest. The coin on screen
//             counts at full strength; another coin's events are dimmer and shorter, its smallest (b 1) skipped.
//   fallback  no relay event for QUIET_MS (the relay is down / connecting, or the market is quiet): each half blinks
//             softly at irregular moments, the same way for both halves, so the light never just sits there and never
//             stays on. It is decoration, not market data: no label or number goes with it (the light chip's tooltip
//             says when the light is decorative).
//   modes     '조명' per device (core/chartfx.js): 깜박 (default) / 계속 켜짐 (the old steady light) / 끄기.
//   calm      prefers-reduced-motion: slow fades (1.4 s in, 1.8 s out), several seconds dark between, no quick change.
//   paused    a hidden page (or another mode): every timer stops, both halves go dark, nothing waits.
// The big-trade / liquidation / our-fill flashes (core/flash.js) stay on top of this as the strongest flashes.
// Pure scheduling (node-tested, tests/test_dash_glow.py): apply(half, opacity, ms, "in" | "out") paints; core/chartfx.js
// turns that into a CSS opacity transition on one of two absolutely positioned layers (no canvas work per blink).
// Each half holds at most one timer; there is no interval and no animation frame loop.

export const LIGHT_MODES = [{id: "blink", ko: "깜박"}, {id: "steady", ko: "계속 켜짐"}, {id: "off", ko: "끄기"}];
export const DEFAULT_LIGHT = "blink";
export const lightModeOf = (id) => LIGHT_MODES.find((m) => m.id === id) || LIGHT_MODES.find((m) => m.id === DEFAULT_LIGHT);
export const HALVES = ["top", "bottom"];          // top = the red Premium half, bottom = the sky-blue Discount half
export const QUIET_MS = 2000;                     // no real event this long: the soft decorative blink takes over
export const WAIT_MS = 1500;                      // a real event waiting for its half's dark gap longer than this is dropped
export const STEADY_K = 0.56;                     // 계속 켜짐: the old steady strength (the tokens are a strong blink's peak)
/** size bucket -> strength (0-1, the layer's opacity) and hold (ms) */
export const BUCKETS = {1: {k: 0.42, hold: 400}, 2: {k: 0.58, hold: 600}, 3: {k: 0.78, hold: 850}, 4: {k: 1, hold: 1200}};
export const OTHER_COIN = {k: 0.65, hold: 0.8};   // another coin's event (b 2-4): dimmer and shorter
/** the timing: FAST normally, CALM under prefers-reduced-motion. dark = the dark gap after a blink; deco = the fallback */
export const FAST = {inMs: 200, outMs: 400, dark: [350, 900], kMax: 1, deco: {k: [0.2, 0.4], hold: [350, 900], gap: [500, 2600]}};
export const CALM = {inMs: 1400, outMs: 1800, dark: [2600, 4200], kMax: 0.6, hold: [1200, 2200],
  deco: {k: [0.18, 0.34], hold: [1400, 2400], gap: [2600, 6000]}};
export const RAISE_MS = 120;                      // a stronger event while its half is lit: brighter at once, same end

/** A relay event {s, side, b} -> {half, k, hold} (null: not a buy / sell, or another coin's smallest). */
export function relayBlink(ev, sym) {
  if (!ev || (ev.side !== "buy" && ev.side !== "sell")) return null;
  const b = Math.min(4, Math.max(1, Math.round(Number(ev.b)) || 1));
  const mine = !sym || ev.s === sym;
  if (!mine && b < 2) return null;
  const B = BUCKETS[b];
  return {half: ev.side === "sell" ? "top" : "bottom", k: mine ? B.k : Math.round(B.k * OTHER_COIN.k * 1000) / 1000,
    hold: mine ? B.hold : Math.round(B.hold * OTHER_COIN.hold), b, mine};
}

/**
 * blinker({apply, mode, visible, reduced, now, rand, setTimer, clearTimer, onSrc}) -> {real(b), sync(), stop(), src(), half(name)}
 *   apply(half, k, ms, "in" | "out"): show one half at opacity k, reached over ms
 *   mode() -> "blink" | "steady" | "off" (read on every step: a changed setting applies with the next sync())
 *   onSrc("real" | "deco"): the light now follows real trades / is decorative (for the chip's tooltip)
 * real(b) lights b.half now when it is dark and its gap is over (a decorative blink on it gives way at once); while it
 * is lit a stronger event only brightens it; otherwise the strongest event waits (WAIT_MS at most) for the gap.
 * sync() applies the mode and the page's visibility: blink -> runs; steady -> both halves at STEADY_K; off / hidden ->
 * both dark, no timer. Call it after a mode or visibility change.
 */
export function blinker(o = {}) {
  const now = o.now || (() => Date.now());
  const rand = o.rand || Math.random;
  const reduced = o.reduced || (() => false);
  const visible = o.visible || (() => true);
  const mode = o.mode || (() => DEFAULT_LIGHT);
  const setTimer = o.setTimer || ((fn, ms) => setTimeout(fn, ms));
  const clearTimer = o.clearTimer || ((t) => clearTimeout(t));
  const paint = (h, k, ms, kind) => { try { o.apply(h.name, k, ms, kind); } catch (e) { /* a failed paint never stops the next */ } };
  const H = Object.fromEntries(HALVES.map((n) => [n, {name: n, phase: "dark", k: 0, deco: false, timer: null, wait: null, nextOk: 0}]));
  let lastReal = -Infinity, since = 0, running = false, src = null;
  const P = () => (reduced() ? CALM : FAST);
  const span = ([a, b]) => a + (b - a) * rand();
  const wanted = () => lightModeOf(mode()).id === "blink" && visible();
  const quiet = () => now() - lastReal >= QUIET_MS;
  function setSrc() {
    const s = quiet() ? "deco" : "real";
    if (s === src) return;
    src = s;
    if (o.onSrc) { try { o.onSrc(s); } catch (e) { /* the tooltip only */ } }
  }
  function arm(h, fn, ms) {
    if (h.timer) clearTimer(h.timer);
    h.timer = setTimer(() => { h.timer = null; fn(); }, Math.max(0, ms));
  }
  function light(h, b, deco) {
    const p = P();
    const k = deco ? b.k : Math.min(b.k, p.kMax);
    const hold = !deco && reduced() ? span(CALM.hold) : b.hold;
    h.phase = "on"; h.k = k; h.deco = !!deco; h.wait = deco ? h.wait : null;
    paint(h, k, p.inMs, "in");
    arm(h, () => fade(h), p.inMs + hold);
  }
  function fade(h) {
    const p = P();
    h.phase = "out";
    paint(h, 0, p.outMs, "out");
    arm(h, () => rest(h), p.outMs);
  }
  function rest(h) {
    h.phase = "dark"; h.k = 0; h.deco = false;
    h.nextOk = now() + span(P().dark);
    next(h);
  }
  /** (dark) the next thing for this half: a waiting real event after the gap, else the decorative blink when quiet. */
  function next(h) {
    if (!running || h.phase !== "dark") return;
    const t = now();
    if (h.wait && t - h.wait.at > WAIT_MS) h.wait = null;
    if (h.wait) {
      arm(h, () => {
        const w = h.wait;
        h.wait = null;
        if (w && running && now() - w.at <= WAIT_MS) light(h, w, false); else next(h);
      }, h.nextOk - t);
      return;
    }
    const at = Math.max(h.nextOk, lastReal + QUIET_MS, since + QUIET_MS) + span(P().deco.gap);
    arm(h, () => deco(h), at - t);
  }
  function deco(h) {
    if (!running || h.phase !== "dark") return;
    setSrc();
    if (!quiet()) { next(h); return; }
    const d = P().deco;
    light(h, {k: span(d.k), hold: span(d.hold)}, true);
  }
  function halt(k, ms) {
    for (const h of Object.values(H)) {
      if (h.timer) clearTimer(h.timer);
      h.timer = null; h.wait = null; h.phase = "dark"; h.k = 0; h.deco = false; h.nextOk = 0;
      paint(h, k, ms, "out");
    }
  }
  return {
    /** A real relay event mapped by relayBlink(). True when it lit (or brightened) its half now. */
    real(b) {
      if (!b || !HALVES.includes(b.half) || !(Number(b.k) > 0)) return false;
      const t = now();
      lastReal = t;
      if (!running) return false;
      setSrc();
      const h = H[b.half];
      const e = {k: Math.min(1, Number(b.k)), hold: Math.max(0, Number(b.hold) || 0), at: t};
      if ((h.phase === "dark" && t >= h.nextOk) || (h.phase === "on" && h.deco)) { light(h, e, false); return true; }
      if (h.phase === "on" && !reduced() && e.k > h.k + 0.05) { h.k = e.k; paint(h, e.k, RAISE_MS, "in"); return true; }
      if (!h.wait || e.k >= h.wait.k) h.wait = e;          // the strongest waits (a tie: the newer)
      if (h.phase === "dark") next(h);
      return false;
    },
    sync() {
      const m = lightModeOf(mode()).id;
      if (wanted()) {
        if (running) return "blink";
        running = true; since = now(); src = null;
        halt(0, 300);
        for (const h of Object.values(H)) next(h);
        return "blink";
      }
      running = false;
      if (m === "steady") { halt(STEADY_K, 300); return "steady"; }
      halt(0, m === "off" ? 300 : 0);
      return m === "off" ? "off" : "paused";
    },
    stop() { running = false; halt(0, 0); },
    src: () => src,
    half: (n) => H[n],
  };
}

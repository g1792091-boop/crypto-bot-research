// The chart's event light (owners 10/06, from the reference video measured frame by frame; "많이 자주"): a real
// market event of the coin on screen washes the whole chart pane once — rises ~0.2 s, holds (0.6 s for an ordinary big
// trade, ~1.5 s for a 고래 / a large liquidation), fades ~0.4 s — then the chart is plain again until the next real
// event. Cyan for a big taker BUY / a short liquidated, red for a big SELL / a long liquidated (Binance's real trades:
// the server relay and the liquidation recorder), the accent for our own bot's real fill. Pure scheduling here
// (node-tested, tests/test_dash_glow.py); the layer is core/chartfx.js, and so is the per-device setting '번쩍임'.
// HONESTY: only push() starts a flash and only a real event calls push(): no timer ever invents one. The single
// setTimeout below only plays an event that really arrived while the previous flash was still on screen.
// prefers-reduced-motion: no flash at all (the steady Premium / Discount light stays; it never moves by itself).

export const ENVELOPE = {inMs: 200, holdMs: 1500, holdSmallMs: 600, outMs: 400};
/** '번쩍임' per device: 자주 (default) every real big trade, at most one start per 0.9 s; 보통 only the big ones (고래, a
 *  large liquidation, our own fills), at most one per 2.5 s; 끄기 none (the ambient tint stays). */
export const FLASH_MODES = [{id: "often", ko: "자주", gapMs: 900, bigOnly: false}, {id: "normal", ko: "보통", gapMs: 2500, bigOnly: true},
  {id: "off", ko: "끄기", gapMs: Infinity, bigOnly: true}];
export const DEFAULT_FLASH = "often";
export const STALE_MS = 3000;        // a waiting event older than this is dropped (it is no longer "now")
export const BIG_LIQ_USD = 250000;   // a liquidation this large holds the full ~1.5 s (and passes 보통)

const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
export const modeOf = (id) => FLASH_MODES.find((m) => m.id === id) || FLASH_MODES.find((m) => m.id === DEFAULT_FLASH);
/** Total on-screen time of one flash (ms). */
export const flashMs = (ev) => ENVELOPE.inMs + (ev && ev.big ? ENVELOPE.holdMs : ENVELOPE.holdSmallMs) + ENVELOPE.outMs;

/** A relay row {side, x: notional / the coin's threshold, w: 1 for a 고래} -> a flash event. Every big row counts (a
 *  lighter flash); a 고래 is the strongest and holds the longest. */
export function bigEvent(r) {
  if (!r || (r.side !== "buy" && r.side !== "sell")) return null;
  const x = Math.max(1, Number(r.x) || 1);
  return {tone: r.side === "buy" ? "up" : "down", k: r.w ? 1 : clamp(0.35 + 0.13 * Math.log2(x), 0.35, 0.8), big: !!r.w,
    why: r.w ? "고래 체결" : "큰 체결"};
}
/** A market liquidation row {liquidated: "long" | "short", usd} -> an event (long liquidated = red, short = cyan). */
export function liqEvent(r) {
  const u = Number(r && r.usd) || 0;
  if (u <= 0 || (r.liquidated !== "long" && r.liquidated !== "short")) return null;
  return {tone: r.liquidated === "long" ? "down" : "up", k: clamp(0.35 + 0.22 * (Math.log10(u) - 4), 0.35, 1), big: u >= BIG_LIQ_USD,
    why: r.liquidated === "long" ? "롱 청산" : "숏 청산"};
}
/** Our own bot's real fill on this coin -> an accent flash (counts as big: it passes 보통). */
export const ownEvent = () => ({tone: "accent", k: 0.6, big: true, own: true, why: "우리 봇 체결"});

/**
 * flashScheduler({play, now, reduced, visible, mode, setTimer, clearTimer, staleMs}) -> {push(ev), pending(), cancel()}
 *   ev: {tone: "up" | "down" | "accent", k: 0..1, big, why}; play(ev, ms) shows it for ms in total.
 *   mode() -> "often" | "normal" | "off" (read on every push: a changed setting applies at once)
 * Rules: 끄기, reduced motion or a hidden page: nothing plays and nothing waits. 보통 drops events that are not big.
 * The first event plays at once; the next may start gapMs after the last start, and never inside a big flash's hold;
 * events in between wait (only the strongest is kept; a tie keeps the newer) and play when allowed, unless stale.
 */
export function flashScheduler(o = {}) {
  const now = o.now || (() => Date.now());
  const reduced = o.reduced || (() => false);
  const visible = o.visible || (() => true);
  const mode = o.mode || (() => DEFAULT_FLASH);
  const setTimer = o.setTimer || ((fn, ms) => setTimeout(fn, ms));
  const clearTimer = o.clearTimer || ((t) => clearTimeout(t));
  const stale = o.staleMs ?? STALE_MS;
  let last = -Infinity, lastBig = false, wait = null, timer = null;

  const nextAt = () => last + Math.max(modeOf(mode()).gapMs, lastBig ? ENVELOPE.inMs + ENVELOPE.holdMs : 0);
  const quiet = () => modeOf(mode()).id === "off" || reduced() || !visible();
  function fire(ev) {
    last = now(); lastBig = !!ev.big;
    try { o.play(ev, flashMs(ev)); } catch (e) { /* a failed paint never stops the next */ }
  }
  function due() {
    timer = null;
    const ev = wait;
    wait = null;
    if (!ev || quiet() || now() - ev.at > stale) return;
    if (modeOf(mode()).bigOnly && !ev.big) return;
    if (now() < nextAt()) { wait = ev; timer = setTimer(due, nextAt() - now()); return; }
    fire(ev);
  }
  return {
    push(ev) {
      if (!ev || !(ev.k > 0) || quiet()) return false;
      if (modeOf(mode()).bigOnly && !ev.big) return false;
      const t = now();
      const e = {tone: ev.tone === "up" || ev.tone === "down" ? ev.tone : "accent", k: clamp(Number(ev.k), 0.2, 1), big: !!ev.big,
        why: ev.why || "", at: t};
      if (t >= nextAt() && !wait) { fire(e); return true; }
      if (!wait || e.k >= wait.k) wait = e;                 // merge: the biggest wins (a tie: the newer)
      if (!timer) timer = setTimer(due, Math.max(0, nextAt() - t));
      return false;
    },
    pending: () => wait,
    cancel() { if (timer) clearTimer(timer); timer = null; wait = null; },
  };
}

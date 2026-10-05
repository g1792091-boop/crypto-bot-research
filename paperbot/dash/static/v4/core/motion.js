// Gentle motion, all of it off under prefers-reduced-motion (CSS kills animations; these helpers also skip the work).
// HONESTY: motion only follows real changes. countTo runs when a real number changed; slideIn marks a real new console
// line; popBubble a real new message; walkTo is for a real meeting start. Nothing here invents activity (no typing
// effect, no endless activity bar).
import {h} from "./dom.js";
import {num, pct} from "./fmt.js";

const RM = typeof matchMedia === "function" ? matchMedia("(prefers-reduced-motion: reduce)") : {matches: false};
export const reduced = () => !!RM.matches;
export const COUNT_MS = 600;

/** One-shot animation class (removed when it ends). */
export function play(el, cls) {
  if (!el || reduced()) return el;
  el.classList.remove(cls); void el.offsetWidth; el.classList.add(cls);
  const end = (e) => { if (e.target !== el) return; el.classList.remove(cls); el.removeEventListener("animationend", end); };
  el.addEventListener("animationend", end);
  return el;
}
/** Screen / tab content swap (~180 ms fade-slide). */
export const swap = (el) => play(el, "swap");
/** A real new console line: slides in and fades from the highlight colour. */
export const slideIn = (el) => play(el, "enter");
/** A real new bubble / message. */
export const popBubble = (el) => play(el, "pop");

/**
 * A number element that counts to its new value over ~600 ms when real data changes.
 * opts: {format: "money"|"pct"|"int"|"price"|fn, dec, sign, suffix, tone (adds up/down class)}.
 * The first paint is instant (nothing counts up from zero on load).
 */
export function countTo(el, to, opts = {}) {
  if (!el) return;
  const fmtFn = typeof opts.format === "function" ? opts.format
    : opts.format === "pct" ? (v) => pct(v, opts.dec ?? 1, opts.sign ?? true)
    : opts.format === "int" ? (v) => num(v, 0, !!opts.sign)
    : (v) => num(v, opts.dec ?? 2, !!opts.sign);
  // the colour follows the SHOWN text (fmt.num's zero test): −0.0003 shows as "0.0%" and must not be red
  const paint = (v) => {
    const s = fmtFn(v);
    el.textContent = s + (opts.suffix || "");
    if (opts.tone) {
      const zero = !/[1-9]/.test(s);
      el.classList.toggle("up", !zero && v > 0); el.classList.toggle("down", !zero && v < 0);
    }
  };
  if (to == null || Number.isNaN(Number(to))) { el.textContent = "—"; delete el.dataset.v; return; }
  const had = el.dataset.v != null && el.dataset.v !== "";
  const from = had ? parseFloat(el.dataset.v) : Number(to);
  el.dataset.v = String(to);
  cancelAnimationFrame(el._raf || 0);
  if (!had || reduced() || from === Number(to)) { paint(Number(to)); return; }
  const t0 = performance.now();
  const step = (t) => {
    const k = Math.min(1, (t - t0) / COUNT_MS), e = 1 - Math.pow(1 - k, 3);
    paint(from + (Number(to) - from) * e);
    if (k < 1) el._raf = requestAnimationFrame(step);
  };
  el._raf = requestAnimationFrame(step);
}

function onEnd(el, prop, fn, ms) {
  let done = false;
  const hnd = (e) => {
    if (e && (e.target !== el || e.propertyName !== prop)) return;
    if (done) return; done = true; el.removeEventListener("transitionend", hnd); fn();
  };
  el.addEventListener("transitionend", hnd);
  setTimeout(hnd, ms || 520);
}

/** Smooth expand / collapse of a region (animated height); returns the new state. */
export function expand(el, open) {
  if (!el) return false;
  const tok = (el._tok = (el._tok || 0) + 1);
  el.classList.add("region");
  if (reduced()) { el.hidden = !open; el.style.height = ""; return open; }
  if (open) {
    el.hidden = false;
    const hgt = el.scrollHeight; el.style.height = "0px"; void el.offsetHeight; el.style.height = hgt + "px";
    onEnd(el, "height", () => { if (el._tok === tok) el.style.height = ""; });
  } else {
    el.style.height = el.scrollHeight + "px"; void el.offsetHeight; el.style.height = "0px";
    onEnd(el, "height", () => { if (el._tok === tok) { el.hidden = true; el.style.height = ""; } });
  }
  return open;
}

/** A shimmer skeleton while loading (only while a request is really in flight). */
export function shimmer(lines = 3, block = false) {
  return h("div", {class: block ? "skel block" : "skel", "aria-busy": "true", "aria-label": "불러오는 중"},
    Array.from({length: lines}, () => h("i")));
}

/** A pixel figure walks from where it stood to (left, top) (percent or px strings); legs step while it moves.
 *  Call it only when a real meeting starts (office). */
export function walkTo(el, left, top) {
  if (!el) return;
  if (reduced()) { el.style.left = left; el.style.top = top; return; }
  el.classList.add("walk");
  el.style.left = left; el.style.top = top;
  setTimeout(() => el.classList.remove("walk"), 1400);
}

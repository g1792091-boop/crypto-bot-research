// Gentle motion, all of it off under prefers-reduced-motion (CSS kills animations; these helpers also skip the work).
// HONESTY: motion only follows real changes. countTo runs when a real number changed; slideIn marks a real new console
// line; popBubble a real new message; walkTo is for a real meeting start. Nothing here invents activity (no typing
// effect, no endless activity bar).
import {h} from "./dom.js";
import {num, pct} from "./fmt.js";

const RM = typeof matchMedia === "function" ? matchMedia("(prefers-reduced-motion: reduce)") : {matches: false};
export const reduced = () => !!RM.matches;
export const COUNT_MS = 600;
/** True while the page is on screen. One-shots are skipped while it is hidden (nobody sees them; phones save power). */
export const visible = () => typeof document === "undefined" || !document.hidden;
const still = () => reduced() || !visible();
const tokv = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const EASE = "cubic-bezier(.2, .7, .2, 1)";

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
 * opts: {format: "money"|"pct"|"int"|"price"|fn, dec, sign, suffix, tone (adds up/down class),
 *        flash: true (a gentle tint in the direction of the change) | "accent" (a neutral tint), only on a real change,
 *        glow: true (flashPrice: a teal / pink text glow in the direction of the change, only on a real change)}.
 * The first paint is instant (nothing counts up from zero on load); an unchanged value is left alone (no repaint, no
 * motion), and while the page is hidden the new value is painted at once.
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
  if (had && from === Number(to) && !el._raf && el.textContent === fmtFn(from) + (opts.suffix || "")) return;   // same again
  el.dataset.v = String(to);
  cancelAnimationFrame(el._raf || 0);
  el._raf = 0;
  if (had && from !== Number(to) && opts.flash) flash(el, opts.flash === "accent" ? null : Number(to) > from ? "up" : "down");
  if (had && from !== Number(to) && opts.glow) flashPrice(el, Number(to) > from ? "up" : "down");
  if (!had || still() || from === Number(to)) { paint(Number(to)); return; }
  const t0 = performance.now();
  const step = (t) => {
    const k = Math.min(1, (t - t0) / COUNT_MS), e = 1 - Math.pow(1 - k, 3);
    paint(from + (Number(to) - from) * e);
    el._raf = k < 1 ? requestAnimationFrame(step) : 0;
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

// ---------------------------------------------------------------- one-shots for real changes (v4 additions)
// All of them: skipped under prefers-reduced-motion and while the page is hidden; transform / opacity / background
// only (no layout change); 900 ms or less; never on a timer. Call them only when real data changed.

/** A gentle tint behind a value that REALLY changed (~900 ms, then back to its own background).
 *  tone: "up" | "down" (the meaning colours, soft) or null (the accent's flash). */
export function flash(el, tone) {
  if (!el || still() || typeof el.animate !== "function") return el;
  if (!el.isConnected) { requestAnimationFrame(() => { if (el.isConnected) flash(el, tone); }); return el; }   // drawn this frame
  try {
    if (el._flash) el._flash.cancel();
    const c = tokv(tone === "up" ? "--up-soft" : tone === "down" ? "--down-soft" : "--flash");
    const end = getComputedStyle(el).backgroundColor;
    el._flash = el.animate([{backgroundColor: c}, {backgroundColor: end}], {duration: 900, easing: "ease-out"});
  } catch (e) { /* an old browser: no tint */ }
  return el;
}

/** A mark that newly appeared (a rank change, a new caption) fades in and rises 3 px (360 ms). */
export function fadeIn(el, ms = 360) {
  if (!el || still() || typeof el.animate !== "function") return el;
  try { el.animate([{opacity: 0, transform: "translateY(3px)"}, {opacity: 1, transform: "none"}], {duration: ms, easing: EASE}); }
  catch (e) { /* no motion */ }
  return el;
}

/** A small chart that newly appeared draws itself left to right once (a clip wipe, 600 ms). */
export function drawIn(el, ms = 600) {
  if (!el || still() || typeof el.animate !== "function") return el;
  try { el.animate([{clipPath: "inset(0 100% 0 0)"}, {clipPath: "inset(0 0 0 0)"}], {duration: ms, easing: EASE}); }
  catch (e) { /* no motion */ }
  return el;
}

/** A soft one-time ring around a card or a row that changed in a way that matters (a position closed, a P&L that
 *  crossed zero). tone: "up" | "down" | null (accent). */
export function ring(el, tone) {
  if (!el || still() || typeof el.animate !== "function") return el;
  try {
    const c = tokv(tone === "up" ? "--up-line" : tone === "down" ? "--down-line" : "--accent-line");
    el.animate([{boxShadow: `0 0 0 0 ${c}`}, {boxShadow: "0 0 0 6px transparent"}], {duration: 900, easing: "ease-out"});
  } catch (e) { /* no motion */ }
  return el;
}

/** A real amount that just happened (a closed trade's +12.30 / −8.10 next to a total): a small chip rises 14 px from
 *  the anchor and fades (900 ms), then is removed. The anchor gets position: relative if it has none. At most one chip
 *  per anchor at a time (a burst of trades: the newest wins). tone: "up" | "down". */
export function floatChip(anchor, text, tone) {
  if (!anchor || still() || typeof anchor.animate !== "function") return null;
  if (getComputedStyle(anchor).position === "static") anchor.style.position = "relative";
  if (anchor._chip) anchor._chip.remove();
  const chip = h("span", {class: ["mo-chip", tone || ""], "aria-hidden": "true", style: {position: "absolute", right: "0", top: "-4px",
    padding: "1px 6px", borderRadius: "4px", font: "700 12px/1.4 var(--f-term)", whiteSpace: "nowrap", pointerEvents: "none",
    color: tone === "down" ? "var(--down)" : tone === "up" ? "var(--up)" : "var(--accent)",
    background: tone === "down" ? "var(--down-soft)" : tone === "up" ? "var(--up-soft)" : "var(--accent-soft)"}}, text);
  anchor.append(chip);
  anchor._chip = chip;
  const a = chip.animate([{opacity: 0, transform: "translateY(4px)"}, {opacity: 1, transform: "translateY(-6px)", offset: 0.25},
    {opacity: 0, transform: "translateY(-14px)"}], {duration: 900, easing: "ease-out"});
  a.onfinish = () => { chip.remove(); if (anchor._chip === chip) anchor._chip = null; };
  return chip;
}

/** One heartbeat (a new real heartbeat, a new event): the element scales up 25 % and back once (420 ms). */
export function beat(el) {
  if (!el || still() || typeof el.animate !== "function") return el;
  try { el.animate([{transform: "scale(1)"}, {transform: "scale(1.25)", offset: 0.35}, {transform: "scale(1)"}], {duration: 420, easing: "ease-out"}); }
  catch (e) { /* no motion */ }
  return el;
}

// ---------------------------------------------------------------- glow one-shots (wave 2: "간지나게 빛나고 움직이고")
// Same rules as above: only on a REAL change, skipped under reduced motion and while the page is hidden, one short
// Web Animation each (no loop, no timer). Colours are the skin's tokens: teal-mint for up, pink for down.

/** The header's live dot: one soft ring per real new heartbeat (core/shell.js; never on a timer). */
export function pulseLive(el) {
  if (!el || still() || typeof el.animate !== "function") return el;
  const dot = el.querySelector("i") || el;
  try {
    const c = tokv("--live-glow") || tokv("--up-line");
    dot.animate([{boxShadow: `0 0 0 0 ${c}`, transform: "scale(1)"}, {boxShadow: `0 0 0 6px transparent`, transform: "scale(1.18)", offset: 0.4},
      {boxShadow: "0 0 0 0 transparent", transform: "scale(1)"}], {duration: 900, easing: "ease-out"});
  } catch (e) { /* no motion */ }
  return el;
}

/** A price label whose value REALLY changed glows once in the direction of the move (teal up / pink down, ~700 ms):
 *  a text glow plus a faint tint behind it, like the reference's right-axis price tag. tone: "up" | "down". */
export function flashPrice(el, tone) {
  if (!el || !tone || still() || typeof el.animate !== "function") return el;
  if (!el.isConnected) { requestAnimationFrame(() => { if (el.isConnected) flashPrice(el, tone); }); return el; }
  try {
    if (el._fp) el._fp.cancel();
    const glow = tokv(tone === "up" ? "--up-glow" : "--down-glow"), soft = tokv(tone === "up" ? "--up-soft" : "--down-soft");
    const bg = getComputedStyle(el).backgroundColor;
    el._fp = el.animate([{textShadow: `0 0 10px ${glow}`, backgroundColor: soft}, {textShadow: "0 0 0 transparent", backgroundColor: bg}],
      {duration: 700, easing: "ease-out"});
  } catch (e) { /* an old browser: no glow */ }
  return el;
}

/**
 * Paint a live price and glow it when it REALLY moved: tickPrice(el, value, text?, key?) -> "up" | "down" | null.
 * The first paint and an unchanged value never glow (the value is kept on the element as data-pv); key names what
 * the label shows (the coin): a label switched to another coin repaints without a glow.
 */
export function tickPrice(el, value, text, key) {
  if (!el) return null;
  if (key != null && el.dataset.pk !== String(key)) { el.dataset.pk = String(key); delete el.dataset.pv; }
  const v = Number(value);
  const shown = text != null ? String(text) : (Number.isFinite(v) ? String(value) : "—");
  if (el.textContent !== shown) el.textContent = shown;
  if (!Number.isFinite(v)) { delete el.dataset.pv; return null; }
  const had = el.dataset.pv != null && el.dataset.pv !== "";
  const prev = had ? Number(el.dataset.pv) : v;
  el.dataset.pv = String(v);
  if (!had || prev === v) return null;
  const tone = v > prev ? "up" : "down";
  flashPrice(el, tone);
  return tone;
}

/** A real new fill / exit row in a feed: it slides down into place from the top with a brief glow in its colour
 *  (tone "up" | "down" | null = accent; a liquidation passes "down" and flashes pink once). ~600 ms. */
export function fillIn(el, tone) {
  if (!el || still() || typeof el.animate !== "function") return el;
  try {
    const c = tokv(tone === "up" ? "--up-soft" : tone === "down" ? "--down-soft" : "--flash");
    const line = tokv(tone === "up" ? "--up-line" : tone === "down" ? "--down-line" : "--accent-line");
    el.animate([{opacity: 0, transform: "translateY(-10px)", backgroundColor: c, boxShadow: `inset 2px 0 0 ${line}`},
      {opacity: 1, transform: "none", backgroundColor: c, boxShadow: `inset 2px 0 0 ${line}`, offset: 0.35},
      {opacity: 1, transform: "none", backgroundColor: "transparent", boxShadow: "inset 2px 0 0 transparent"}],
    {duration: 900, easing: EASE});
  } catch (e) { /* no motion */ }
  return el;
}

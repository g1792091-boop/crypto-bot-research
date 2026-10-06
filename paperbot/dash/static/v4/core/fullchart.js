// 차트 크게 보기 (owners 10/06: "클릭이 너무 많다"): every chart (터미널, 차트, 매매법, 계좌, 여러 차트의 칸) gets a
// '크게' button; the key "f" does the same for the chart under the mouse (else the biggest one on screen) and Esc (or
// the ✕, or "f" again) puts it back. The chart's own frame (its header with the interval buttons and the '선' menu, the
// chart, its legend) fills the window: CSS first (a fixed layer, core/fullchart.css; it works on every phone), and the
// browser's real full screen on top where the page may ask for it (a PC, Android). The chart follows by itself: every
// chart box is watched by a ResizeObserver (core/lwc.js makeChart, core/chartfx.js), so it is drawn again at the new
// size. A phone held upright gets a hint to turn it sideways (nothing is forced). Nothing here moves on a timer.
//   const fs = fullChart({ctx, label});  ... put fs (a button) in the chart's header ...  fs.bind(frame)
//   frame: the element that fills the screen; inside it, mark the part that should take the height data-fc-grow
//   (a flex column; nested containers on the way data-fc-col) — the terminal's panel needs no marks (it is a column).
import {h, s} from "./dom.js";

const items = new Set();          // {btn, frame, o}
let cur = null, hover = null;

const R = (x, y, w, hh) => s("rect", {x, y, width: w, height: hh});
const ICON_ON = () => [R(1, 1, 5, 2), R(1, 1, 2, 5), R(10, 1, 5, 2), R(13, 1, 2, 5), R(1, 10, 2, 5), R(1, 13, 5, 2), R(13, 10, 2, 5), R(10, 13, 5, 2)];
const ICON_OFF = () => [R(4, 1, 2, 5), R(1, 4, 5, 2), R(10, 1, 2, 5), R(10, 4, 5, 2), R(4, 10, 2, 5), R(1, 10, 5, 2), R(10, 10, 2, 5), R(10, 10, 5, 2)];
const icon = (on) => s("svg", {viewBox: "0 0 16 16", width: "14", height: "14", fill: "currentColor", "shape-rendering": "crispEdges", "aria-hidden": "true"},
  on ? ICON_OFF() : ICON_ON());

const live = (it) => !!it && !!it.frame && document.contains(it.frame);
const shown = (el) => { const r = el.getBoundingClientRect(); return r.width > 40 && r.height > 40 && r.bottom > 0 && r.top < innerHeight; };
/** The chart "f" acts on: the one under the mouse (or holding the focus), else the biggest one on screen. */
function pick() {
  if (live(hover) && shown(hover.frame)) return hover;
  let best = null, area = 0;
  for (const it of items) {
    if (!live(it)) continue;
    const r = it.frame.getBoundingClientRect();
    const a = Math.max(0, Math.min(r.bottom, innerHeight) - Math.max(r.top, 0)) * Math.max(0, Math.min(r.right, innerWidth) - Math.max(r.left, 0));
    if (a > area) { area = a; best = it; }
  }
  return best;
}

function paintBtn(it, on) {
  it.btn.setAttribute("aria-pressed", String(on));
  const t = on ? "작게" : "크게";
  it.btn.replaceChildren(icon(on), h("span", {class: "fc-bt"}, t));
  const lab = `${it.o.label || "차트"} ${on ? "원래 크기로 (Esc)" : "크게 보기 (단축키 f)"}`;
  it.btn.setAttribute("aria-label", lab); it.btn.title = lab;
}

function enter(it) {
  if (!live(it)) return false;
  if (cur && cur !== it) leave();
  cur = it;
  const f = it.frame;
  f.classList.add("fc-on");
  document.documentElement.classList.add("fc-lock");
  paintBtn(it, true);
  it.x = h("button", {type: "button", class: "fc-x", "aria-label": "크게 보기 닫기 (Esc)", title: "닫기 (Esc)", onclick: () => leave()}, "✕");
  it.hint = h("p", {class: "fc-hint", role: "note"}, h("span", {class: "fc-rot"}, "↻ 휴대폰을 가로로 돌리면 더 넓게 보입니다"),
    h("span", {class: "fc-esc"}, "Esc · f 또는 ✕ 로 닫기"));
  f.append(it.x, it.hint);
  // capture: before a chart deck's own Esc closes its open '선' menu (then this Esc only closes the menu)
  document.addEventListener("keydown", onKey, true);
  document.addEventListener("fullscreenchange", onFs);
  window.addEventListener("hashchange", onRoute);
  // the browser's real full screen on top (not on an iPhone, where only video may; the CSS layer is enough there)
  try { if (f.requestFullscreen && !document.fullscreenElement) f.requestFullscreen({navigationUI: "hide"}).catch(() => {}); } catch (e) { /* CSS only */ }
  if (it.o.onChange) { try { it.o.onChange(true); } catch (e) { /* the chart still fills the screen */ } }
  return true;
}

/** Put the big chart back (no-op when none is big). */
export function leave() {
  const it = cur;
  if (!it) return false;
  cur = null;
  document.removeEventListener("keydown", onKey, true);
  document.removeEventListener("fullscreenchange", onFs);
  window.removeEventListener("hashchange", onRoute);
  if (it.frame) it.frame.classList.remove("fc-on");
  document.documentElement.classList.remove("fc-lock");
  if (it.x) it.x.remove();
  if (it.hint) it.hint.remove();
  it.x = it.hint = null;
  if (it.btn) paintBtn(it, false);
  try { if (document.fullscreenElement && document.exitFullscreen) document.exitFullscreen().catch(() => {}); } catch (e) { /* not in full screen */ }
  if (it.o.onChange) { try { it.o.onChange(false); } catch (e) { /* back to normal anyway */ } }
  if (it.btn && document.contains(it.btn)) it.btn.focus({preventScroll: true});
  return true;
}
function onKey(e) {
  if (e.key !== "Escape" || !cur) return;
  // a menu open inside the big chart (the '선' menu) closes first; the next Esc puts the chart back
  if (cur.frame.querySelector(".cfx-menu:not([hidden])")) return;
  e.preventDefault();
  leave();
}
function onFs() { if (cur && !document.fullscreenElement) leave(); }        // the browser's own Esc / gesture left full screen
function onRoute() { leave(); }

/** The key "f" (core/navkeys.js): the big chart back to normal, else the chart under the mouse (or the biggest) big.
 *  False when this screen has no chart. */
export function toggleFull() {
  if (cur) return leave();
  const it = pick();
  return it ? enter(it) : false;
}
export const fullOn = () => !!cur;

/**
 * fullChart({ctx, label, onChange}) -> the '크게' button; call btn.bind(frame) once the frame exists (the button may sit
 * inside it). ctx.track() takes it off when the screen is left; onChange(big) after each switch.
 */
export function fullChart(o = {}) {
  const it = {o, frame: null, btn: null};
  it.btn = h("button", {type: "button", class: "fc-btn", "aria-pressed": "false", onclick: (e) => { e.stopPropagation(); if (cur === it) leave(); else enter(it); }});
  paintBtn(it, false);
  it.btn.bind = (frame) => {
    it.frame = frame;                         // (a frame no longer on the page is skipped by pick(); ctx.track removes it)
    frame.classList.add("fc-frame");
    const mark = () => { hover = it; };
    frame.addEventListener("pointerenter", mark);
    frame.addEventListener("focusin", mark);
    items.add(it);
    return it.btn;
  };
  if (o.ctx && o.ctx.track) o.ctx.track(() => { if (cur === it) leave(); items.delete(it); if (hover === it) hover = null; });
  return it.btn;
}

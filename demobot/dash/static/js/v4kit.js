// The rule bot's v4 look for the demo lab, as one kit (stage 1 of the restyle; stage 2 restyles the other screens with
// it). Copied and adapted from paperbot/dash/static/v4 (same repo, same owners): core/figure.js (the pixel people),
// core/motion.js (gentle one-shots, all off under prefers-reduced-motion), core/ui.js (miniSpark, rankDelta, liveNum),
// screens/home-shared.js (the group cards, the 상위 · 하위 rows) and screens/board-table.js (the dense sortable table).
// Nothing is imported from paperbot at run time. Every string goes into the page as a text node (dom.js h() / s());
// the look is static/v4kit.css (class names k4-…, plus the v4 component classes of components.css: plate, pp, stat,
// seg, fig, sfig, mspark, an-tf). HONESTY (v4 CONTRACT section 1): motion only follows a real change of real data,
// a comparison with the coin flips is always marked 참고, a small sample says so, a missing number is "준비 중".
import {h, s, put} from "./dom.js";
import * as fmt from "./fmt.js";
import {tfKo} from "./labels.js";

// ================================================================ motion (v4 core/motion.js, the parts the demo uses)
const RM = typeof matchMedia === "function" ? matchMedia("(prefers-reduced-motion: reduce)") : {matches: false};
/** True when the viewer asked the system for less motion (every helper here then does nothing). */
export const reduced = () => !!RM.matches;
/** True while the page is on screen (one-shots are skipped while it is hidden: nobody sees them). */
export const visible = () => typeof document === "undefined" || !document.hidden;
const still = () => reduced() || !visible();
const tokv = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const EASE = "cubic-bezier(.2, .7, .2, 1)";
export const COUNT_MS = 600;

/** One-shot animation class (removed when it ends); nothing under reduced motion. */
export function play(el, cls) {
  if (!el || reduced()) return el;
  el.classList.remove(cls); void el.offsetWidth; el.classList.add(cls);
  const end = (e) => { if (e.target !== el) return; el.classList.remove(cls); el.removeEventListener("animationend", end); };
  el.addEventListener("animationend", end);
  return el;
}
/** Tab / view content swap (~180 ms fade-slide). */
export const swap = (el) => play(el, "swap");

/** A gentle tint behind a value that REALLY changed (~900 ms). tone "up" | "down" | null (the accent). */
export function flash(el, tone) {
  if (!el || still() || typeof el.animate !== "function") return el;
  if (!el.isConnected) { requestAnimationFrame(() => { if (el.isConnected) flash(el, tone); }); return el; }
  try {
    if (el._flash) el._flash.cancel();
    const c = tokv(tone === "up" ? "--up-soft" : tone === "down" ? "--down-soft" : "--flash");
    el._flash = el.animate([{backgroundColor: c}, {backgroundColor: getComputedStyle(el).backgroundColor}], {duration: 900, easing: "ease-out"});
  } catch (e) { /* an old browser: no tint */ }
  return el;
}
/** A mark that newly appeared fades in and rises 3 px (360 ms). */
export function fadeIn(el, ms = 360) {
  if (!el || still() || typeof el.animate !== "function") return el;
  try { el.animate([{opacity: 0, transform: "translateY(3px)"}, {opacity: 1, transform: "none"}], {duration: ms, easing: EASE}); } catch (e) { /* no motion */ }
  return el;
}
/** A small chart that newly appeared draws itself left to right once (600 ms). */
export function drawIn(el, ms = 600) {
  if (!el || still() || typeof el.animate !== "function") return el;
  try { el.animate([{clipPath: "inset(0 100% 0 0)"}, {clipPath: "inset(0 0 0 0)"}], {duration: ms, easing: EASE}); } catch (e) { /* no motion */ }
  return el;
}
/** A price label whose value REALLY changed glows once in the direction of the move (~700 ms). */
export function flashPrice(el, tone) {
  if (!el || !tone || still() || typeof el.animate !== "function") return el;
  try {
    if (el._fp) el._fp.cancel();
    const glow = tokv(tone === "up" ? "--up-glow" : "--down-glow"), soft = tokv(tone === "up" ? "--up-soft" : "--down-soft");
    el._fp = el.animate([{textShadow: `0 0 10px ${glow}`, backgroundColor: soft}, {textShadow: "0 0 0 transparent", backgroundColor: getComputedStyle(el).backgroundColor}],
      {duration: 700, easing: "ease-out"});
  } catch (e) { /* no glow */ }
  return el;
}
/** Paint a live price and glow it when it REALLY moved: tickPrice(el, value, text, key) -> "up" | "down" | null.
 *  The first paint, an unchanged value and a label switched to another coin (key) never glow. */
export function tickPrice(el, value, text, key) {
  if (!el) return null;
  if (key != null && el.dataset.pk !== String(key)) { el.dataset.pk = String(key); delete el.dataset.pv; }
  const v = Number(value);
  const shown = text != null ? String(text) : Number.isFinite(v) ? String(value) : "—";
  if (el.textContent !== shown) el.textContent = shown;
  if (value == null || !Number.isFinite(v)) { delete el.dataset.pv; return null; }
  const had = el.dataset.pv != null && el.dataset.pv !== "";
  const prev = had ? Number(el.dataset.pv) : v;
  el.dataset.pv = String(v);
  if (!had || prev === v) return null;
  const tone = v > prev ? "up" : "down";
  flashPrice(el, tone);
  return tone;
}

/**
 * countTo(el, to, {format(v) -> text, tone, flash}) : a number that counts to its new value over ~600 ms when real
 * data changed. The first paint is instant (nothing counts up from zero on load), an unchanged value is left alone, a
 * hidden page or reduced motion paints at once. tone: adds up / down by the sign (of the shown text: "0.0%" gets none).
 */
export function countTo(el, to, o = {}) {
  if (!el) return;
  const f = o.format || ((v) => fmt.num(v, 2));
  const paint = (v) => {
    const t = f(v);
    el.textContent = t;
    if (o.tone) { const z = !/[1-9]/.test(t); el.classList.toggle("up", !z && v > 0); el.classList.toggle("down", !z && v < 0); }
  };
  if (to == null || !Number.isFinite(Number(to))) { el.textContent = "—"; delete el.dataset.v; el.classList.remove("up", "down"); return; }
  const had = el.dataset.v != null && el.dataset.v !== "";
  const from = had ? parseFloat(el.dataset.v) : Number(to);
  if (had && from === Number(to) && !el._raf) return;
  el.dataset.v = String(to);
  cancelAnimationFrame(el._raf || 0);
  el._raf = 0;
  if (had && from !== Number(to) && o.flash) flash(el, o.flash === "accent" ? null : Number(to) > from ? "up" : "down");
  if (!had || still() || from === Number(to)) { paint(Number(to)); return; }
  const t0 = performance.now();
  const step = (t) => {
    const k = Math.min(1, (t - t0) / COUNT_MS), e = 1 - Math.pow(1 - k, 3);
    paint(from + (Number(to) - from) * e);
    el._raf = k < 1 ? requestAnimationFrame(step) : 0;
  };
  el._raf = requestAnimationFrame(step);
}
/** liveNum(value, {format, tone, flash, cls, tag}) -> an element with .update(v) that counts to new values. */
export function liveNum(value, o = {}) {
  const el = h(o.tag || "b", {class: ["num", o.cls]});
  countTo(el, value, o);
  el.update = (v) => countTo(el, v, o);
  return el;
}
/** A signed percent for liveNum / countTo: 12.34 -> "+12.3%" (the demo's pnl_pct is already in percent). */
export const pctFmt = (dec = 1) => (v) => fmt.pct(v, true, dec);

// ================================================================ pixel people (v4 core/figure.js recipe)
const px = (x, y, w, hh, c) => s("rect", {x, y, width: w, height: hh, class: c});
/**
 * figure({hue, kind: "staff"|"spec"|"owner", size, breathe, i}) -> <svg class="fig"> (10 x 14 cells, aria-hidden: put
 * the name next to it). breathe: the 1 px idle motion (3 s, ambient only, off under reduced motion).
 */
export function figure(o = {}) {
  const kind = o.kind || "staff", size = o.size || 24;
  return s("svg", {class: ["fig", kind === "spec" ? "spec" : "", kind === "owner" ? "owner" : "", o.breathe ? "breathe" : "", o.cls],
    viewBox: "0 0 10 14", width: size, height: Math.round(size * 1.4), "shape-rendering": "crispEdges", "aria-hidden": "true",
    style: {"--h": o.hue ?? 210, "--i": o.i || 0}},
  kind === "spec" ? [px(2, 0, 6, 1, "pv"), px(1, 1, 8, 1, "pv")] : px(2, 0, 6, 2, "ph"),
  px(2, 2, 6, 3, "ps"), px(3, 3, 1, 1, "pe"), px(6, 3, 1, 1, "pe"),
  px(1, 5, 8, 5, kind === "owner" ? "po" : "pb"), kind === "owner" ? px(4, 5, 2, 3, "pt") : null,
  px(0, 6, 1, 3, "ps"), px(9, 6, 1, 3, "ps"),
  px(2, 10, 2, 3, "pl l1"), px(6, 10, 2, 3, "pl l2"), px(2, 13, 2, 1, "pf l1"), px(6, 13, 2, 1, "pf l2"));
}

const hash = (str) => { let x = 2166136261; for (const c of String(str)) { x ^= c.codePointAt(0); x = Math.imul(x, 16777619); } return x >>> 0; };
const HAIR = [
  () => [px(3, 1, 6, 2, "ah")],                                                                 // short
  () => [px(3, 1, 6, 2, "ah"), px(2, 2, 1, 4, "ah"), px(9, 2, 1, 4, "ah")],                     // long
  () => [px(4, 0, 1, 1, "ah"), px(6, 0, 1, 1, "ah"), px(8, 0, 1, 1, "ah"), px(3, 1, 6, 2, "ah")],   // spiky
  () => [px(5, 0, 2, 1, "ah"), px(3, 1, 6, 2, "ah"), px(3, 3, 1, 1, "ah")],                     // bun
];
const CAP = () => [px(2, 1, 8, 1, "ab"), px(3, 0, 6, 1, "ab"), px(9, 2, 2, 1, "ab")];
const VISOR = () => [px(3, 1, 6, 1, "ah"), px(2, 3, 8, 1, "av")];
/** Body hue of a demo account's strategy (S2 / N02 / N04; the private plug-ins their own): the same in both skins. */
export const STRAT_HUE = {S2: 42, N02: 185, N04: 300};
/**
 * acctFig(account, size) -> <svg class="sfig"> the account's pixel character (v4 stratFigure recipe, 12 x 12 cells,
 * head and shoulders, fixed per account): the body hue by strategy, the hair by the account id; 자동 교체 wears a cap
 * (it changes its setting), 친구 규칙 a visor, a coin flip has a coin for a head (grey: the baseline), a private
 * plug-in a hood. aria-hidden: the name goes next to it. No idle motion (lists stay still).
 */
export function acctFig(a, size = 20) {
  const kind = (a && a.kind) || "fixed", id = String((a && a.id) || ""), k = hash(id);
  const hue = kind === "flip" ? null : kind === "private" ? 230 : STRAT_HUE[a && a.short] ?? (k % 12) * 30;
  const kids = [px(0, 0, 12, 12, "abg")];
  if (kind === "flip") {
    kids.push(px(3, 1, 6, 6, "ac"), px(2, 2, 8, 4, "ac"), px(5, 2, 2, 4, "acs"), px(4, 3, 4, 2, "acs"), px(4, 7, 4, 1, "as"));
  } else {
    kids.push(px(3, 2, 6, 5, "as"), px(4, 4, 1, 1, "ae"), px(7, 4, 1, 1, "ae"), px(5, 6, 2, 1, "am"));
    if (kind === "adaptive") kids.push(...CAP());
    else if (kind === "friend") kids.push(...VISOR());
    else if (kind === "private") kids.push(px(2, 0, 8, 2, "ab"), px(2, 2, 1, 5, "ab"), px(9, 2, 1, 5, "ab"));
    else kids.push(...HAIR[k % HAIR.length]());
  }
  kids.push(px(2, 8, 8, 4, kind === "flip" ? "ag" : "ab2"), px(5, 8, 2, 1, "as"));
  return s("svg", {class: ["sfig", `k-${kind === "flip" ? "random" : kind}`], viewBox: "0 0 12 12", width: size, height: size,
    "shape-rendering": "crispEdges", "aria-hidden": "true", style: {"--h": hue == null ? 210 : hue}}, kids);
}

// ================================================================ small pieces
/** The ◆ label plate. */
export const plate = (text) => h("span", {class: "plate"}, text);
/** A pill (pp: "", good, bad, warn, accent, thin, ref). ref prints "참고" before its text. */
export const pill = (text, cls = "", title) => h("span", {class: ["pp", cls], title}, text);
/** The timeframe chip of a name ("15분"): never shrinks, the name after it is cut with … instead. */
export const tfChip = (tf) => h("span", {class: "an-tf"}, tfKo(tf));
/** An account's name without its " · 15분" ending (the timeframe chip says it): "S2 기본값 · 15분" -> "S2 기본값". */
export function shortName(a) {
  const n = String((a && (a.name || a.id)) || "—");
  const tail = a && a.tf ? ` · ${tfKo(a.tf)}` : null;
  return tail && n.endsWith(tail) && n.length > tail.length ? n.slice(0, -tail.length) : n;
}
/** An account's name for a list: the timeframe chip first, then the name (cut with … on a phone; the full name and the
 *  id in its tooltip). */
export function acctName(a) {
  return h("span", {class: "an", title: a ? `${a.name || a.id} · ${a.id}` : null}, a && a.tf ? tfChip(a.tf) : null,
    h("span", {class: "an-n"}, shortName(a)));
}
/** A stat card: k (small label), v (the big number: text or a node), sub (one small line). */
export function stat(k, v, sub, cls) {
  return h("div", {class: ["stat", cls]}, h("span", {class: "k"}, k), v instanceof Node ? v : h("b", null, v ?? "—"),
    sub != null ? (sub instanceof Node ? sub : h("span", {class: "s"}, sub)) : null);
}
/** "표본 적음" when n is below min (30 closed trades: the judge's own floor). */
export const smallSample = (n, min = 30) => (n != null && Number(n) < min
  ? h("span", {class: "pp thin", title: `닫힌 거래 ${min}건 미만: 우연일 수 있습니다`}, "표본 적음") : null);
/** The 참고 note under any comparison with the coin flips (never a pass or a fail). */
export const refNote = (extra) => h("p", {class: "refnote"}, h("b", null, "참고"),
  " · 동전 던지기와의 비교는 운과 견주어 보는 것일 뿐 판정이 아닙니다. 판정은 판정 화면의 우리 기준·친구 기준으로만 합니다.", extra ? ` ${extra}` : null);
/** median of the finite numbers (null when none). */
export function median(xs) {
  const v = (xs || []).map(Number).filter(Number.isFinite).sort((a, b) => a - b);
  if (!v.length) return null;
  const m = v.length >> 1;
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
}

/**
 * secRow(plateText, hint, ...acts) -> the "◆ 묶음 ◆  hint ............ [acts]" row above a block (v4 home-sec-row).
 */
export const secRow = (plateText, hint, ...acts) => h("div", {class: "k4-secrow"}, plate(plateText),
  hint ? h("span", {class: "k4-hint"}, hint) : null, acts.length ? h("span", {class: "grow"}) : null, ...acts);

/**
 * segSwitch(label, [{id, ko, title}], value, onPick, cls) -> the top bar's segmented control ("글자 크기 [보통|크게|아주 크게]",
 * base.css .skinsw): aria-pressed buttons; onPick(id) after a change; .set(id) marks one without calling onPick.
 */
export function segSwitch(label, options, value, onPick, cls) {
  const btns = options.map((x) => h("button", {type: "button", "aria-pressed": String(x.id === value), dataset: {id: x.id}, title: x.title,
    onclick: () => { if (b.dataset.v === x.id) return; b.set(x.id); if (onPick) onPick(x.id); }}, x.ko));
  const b = h("span", {class: ["skinsw", cls], role: "group", "aria-label": label}, label ? h("span", {class: "k"}, label) : null, btns);
  b.dataset.v = value;
  b.set = (id) => { b.dataset.v = id; for (const x of btns) x.setAttribute("aria-pressed", String(x.dataset.id === id)); };
  return b;
}
/** chipToggle(label, on, onChange, title) -> a small on / off chip with a square (v4 여러 차트 '선' chips). */
export function chipToggle(label, on, onChange, title) {
  const b = h("button", {type: "button", class: "k4-chip", "aria-pressed": String(!!on), title}, label);
  b.addEventListener("click", () => {
    const v = b.getAttribute("aria-pressed") !== "true";
    b.setAttribute("aria-pressed", String(v));
    if (onChange) onChange(v);
  });
  return b;
}
/** liveDot(text, state "ok"|"warn"|"bad"|"off") -> "● text" with .set(text, state): a status that only shows real state. */
export function liveDot(text, state = "off") {
  const t = h("span", null, text);
  const el = h("span", {class: "k4-live", dataset: {s: state}}, h("i", {"aria-hidden": "true"}), t);
  el.set = (x, st) => { t.textContent = x; el.dataset.s = st || "off"; };
  return el;
}

// ================================================================ charts: the small line, the rank arrow
/**
 * miniSpark(values, {w, h, base, tone, fluid, draw, label}) -> a fixed-size svg (w x h px, default 60 x 20): the line,
 * a dot at its end, an optional dashed base (the start). The colour follows the end against the base (or the first
 * value): up / down; tone overrides it. fluid: fills its box's width. draw: draws itself in once (a real new line).
 * Fewer than 2 real values give an empty box of the same size (no layout jump while loading).
 */
export function miniSpark(values, o = {}) {
  const w = o.w || 60, hh = o.h || 20;
  const box = o.fluid ? {width: "100%", height: hh + "px", display: "block"}
    : {width: w + "px", height: hh + "px", display: "inline-block", verticalAlign: "middle", flex: "none"};
  const vs = (values || []).map((v) => (v == null || !Number.isFinite(Number(v)) ? null : Number(v)));
  const real = vs.filter((v) => v != null);
  if (real.length < 2) return s("svg", {class: ["chart", "mspark", "none"], viewBox: `0 0 ${w} ${hh}`, style: box, "aria-hidden": "true"});
  let lo = Math.min(...real), hi = Math.max(...real);
  if (o.base != null && Number.isFinite(Number(o.base))) { lo = Math.min(lo, o.base); hi = Math.max(hi, o.base); }
  const span = hi - lo || Math.abs(hi) * 0.001 || 1;
  const pad = 2.5;
  const X = (i) => pad + (w - 2 * pad) * i / Math.max(1, vs.length - 1);
  const Y = (v) => hh - pad - (hh - 2 * pad) * (v - lo) / span;
  let d = "", pen = false, lastI = 0;
  vs.forEach((v, i) => { if (v == null) { pen = false; return; } d += `${pen ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`; pen = true; lastI = i; });
  const end = real[real.length - 1], ref = o.base != null ? o.base : real[0];
  const up = o.tone ? o.tone === "up" : end >= ref;
  const svg = s("svg", {class: ["chart", "mspark"], viewBox: `0 0 ${w} ${hh}`, style: box, role: "img", "aria-label": o.label || "흐름",
    preserveAspectRatio: o.fluid ? "none" : null},
  o.base != null ? s("line", {class: "base", x1: 0, x2: w, y1: Y(o.base).toFixed(1), y2: Y(o.base).toFixed(1)}) : null,
  s("path", {class: up ? "lu" : "ld", d}),
  o.fluid ? null : s("circle", {cx: X(lastI).toFixed(1), cy: Y(end).toFixed(1), r: 1.9, style: {fill: up ? "var(--up)" : "var(--down)"}}));
  if (o.draw) drawIn(svg);
  return svg;
}
/** rankDelta(delta, {title, fade}) -> "▲2" / "▼1" (delta = earlier rank − rank now: positive = moved up), null when it
 *  did not move or there is nothing to compare with. fade: fade it in (a real change). */
export function rankDelta(delta, o = {}) {
  const n = Number(delta);
  if (delta == null || !Number.isFinite(n) || n === 0) return null;
  const up = n > 0;
  const el = h("span", {class: ["k4-rkd", up ? "up" : "down"], title: o.title || null, "aria-label": `순위 ${fmt.int(Math.abs(n))}칸 ${up ? "오름" : "내림"}`},
    `${up ? "▲" : "▼"}${fmt.int(Math.abs(n))}`);
  if (o.fade) fadeIn(el);
  return el;
}
/** Ranks (1 = best) of keys by value, highest first: {key: rank} (a missing value has no rank). */
export function ranksOf(values) {
  const ks = Object.keys(values || {}).filter((k) => values[k] != null && Number.isFinite(Number(values[k])));
  ks.sort((a, b) => Number(values[b]) - Number(values[a]) || (a < b ? -1 : 1));
  return Object.fromEntries(ks.map((k, i) => [k, i + 1]));
}

// ================================================================ the group cards (v4 home-shared groupCards)
/**
 * groupCards({onPick, label}) -> a div with .update(cards, sel). cards: [{id, name, count, med (percent), vs (text or
 * node), ref (true: a 참고 chip after vs), foot, title}]. Built once and updated in place: the median counts to its new
 * value (real data only), focus stays where it was; the chosen card is outlined (aria-pressed).
 */
export function groupCards(o = {}) {
  const el = h("div", {class: "k4-groups", role: "group", "aria-label": o.label || "묶음 고르기"});
  const made = new Map();
  let order = "";
  function make(c) {
    const cnt = h("span", {class: "gc"}), vs = h("span", {class: "gs"}), foot = h("span", {class: "gb"});
    const med = liveNum(null, {format: pctFmt(1), tone: true, cls: "gm", flash: true});
    const name = h("span", {class: "gn"});
    const btn = h("button", {type: "button", class: "k4-gcard", "aria-pressed": "false", onclick: () => o.onPick && o.onPick(c.id)},
      name, cnt, h("span", {class: "gmw"}, med, h("small", null, "중앙값")), vs, foot);
    return {btn, name, cnt, med, vs, foot};
  }
  el.update = (cards, sel) => {
    for (const c of cards) {
      const x = made.get(c.id) || make(c);
      made.set(c.id, x);
      x.name.textContent = c.name;
      x.btn.title = c.title || "";
      x.btn.dataset.kind = c.id;
      x.cnt.textContent = c.count || "";
      x.med.update(c.med);
      put(x.vs, c.vs ?? "", c.ref ? [" ", pill("", "ref", "동전 던지기와의 비교: 참고 (판정 아님)")] : null);
      x.foot.textContent = c.foot || "";
      x.btn.setAttribute("aria-pressed", String(c.id === sel));
    }
    const sig = cards.map((c) => c.id).join();
    if (sig !== order) { order = sig; put(el, cards.map((c) => made.get(c.id).btn)); }
  };
  return el;
}

// ================================================================ the dense sortable table (v4 board-table)
/**
 * boardTable({cols, page, search: {placeholder, match(row, q)}, onRow, rowCls, note, empty}) -> {el, set(rows), sortBy(id, dir)}
 * cols: [{id, label, l (left), sort(row) -> number|string (no sort: not sortable), get(row) -> text|Node, cls, title,
 * dir (1 = small first is the natural order, -1 = big first; default -1 for numbers)}]. A click on a head sorts by it
 * (again: the other way); the search filters by match(); one page at a time (page rows, default 25). Rows are built
 * only for the page shown.
 */
export function boardTable(o) {
  const st = {rows: [], col: o.sort ? o.sort.id : null, dir: o.sort ? o.sort.dir : -1, page: 0, q: ""};
  const size = o.page || 25;
  const search = o.search ? h("input", {class: "search k4-tsearch", type: "search", placeholder: o.search.placeholder || "이름 찾기",
    "aria-label": o.search.placeholder || "표에서 찾기", autocomplete: "off"}) : null;
  const thead = h("thead");
  const tbody = h("tbody");
  const info = h("span", {class: "pinfo"});
  const prev = h("button", {class: "btn-line", type: "button"}, "이전");
  const next = h("button", {class: "btn-line", type: "button"}, "다음");
  const bar = h("div", {class: "pager"}, prev, info, next);
  const el = h("div", {class: "stack tight k4-twrap"}, search,
    h("div", {class: "tbl-wrap k4-tscroll"}, h("table", {class: ["tbl", "k4-table", o.cls]}, thead, tbody)), bar);
  if (search) search.addEventListener("input", () => { st.q = search.value.trim().toLowerCase(); st.page = 0; render(); });
  prev.addEventListener("click", () => { st.page--; render(); });
  next.addEventListener("click", () => { st.page++; render(); });
  const colOf = (id) => o.cols.find((c) => c.id === id);
  function head() {
    put(thead, h("tr", null, o.cols.map((c) => {
      const on = st.col === c.id;
      return h("th", {class: [c.l ? "l" : "", on ? "on" : "", c.hcls], scope: "col", title: c.title || null,
        "aria-sort": on ? (st.dir > 0 ? "ascending" : "descending") : null},
      c.sort ? h("button", {type: "button", class: "k4-th", title: `${c.label} 순으로 (한 번 더 누르면 거꾸로)`,
        onclick: () => { if (st.col === c.id) st.dir = -st.dir; else { st.col = c.id; st.dir = c.dir || (c.l ? 1 : -1); } st.page = 0; render(); }},
      c.label, on ? h("span", {"aria-hidden": "true"}, st.dir > 0 ? " ▴" : " ▾") : null) : c.label);
    })));
  }
  function sorted(rows) {
    const c = colOf(st.col);
    if (!c || !c.sort) return rows;
    return rows.map((r, i) => ({r, i, k: c.sort(r)})).sort((a, b) => {
      const na = a.k == null || (typeof a.k === "number" && !Number.isFinite(a.k)), nb = b.k == null || (typeof b.k === "number" && !Number.isFinite(b.k));
      if (na || nb) return na === nb ? a.i - b.i : na ? 1 : -1;                // missing values last, whatever the direction
      const x = typeof a.k === "string" ? a.k.localeCompare(b.k, "ko") : a.k - b.k;
      return x ? x * st.dir : a.i - b.i;
    }).map((x) => x.r);
  }
  function render() {
    head();
    let rows = st.q && o.search ? st.rows.filter((r) => o.search.match(r, st.q)) : st.rows;
    rows = sorted(rows);
    const pages = Math.max(1, Math.ceil(rows.length / size));
    st.page = Math.max(0, Math.min(st.page, pages - 1));
    const s0 = st.page * size, part = rows.slice(s0, s0 + size);
    put(tbody, part.length ? part.map((r) => {
      const tr = h("tr", {class: [o.onRow ? "click" : "", o.rowCls ? o.rowCls(r) : ""]},
        o.cols.map((c) => { const v = c.get(r); return h("td", {class: [c.l ? "l" : "", typeof c.cls === "function" ? c.cls(r) : c.cls]}, v instanceof Node ? v : v ?? "—"); }));
      if (o.onRow) {
        tr.tabIndex = 0;
        tr.addEventListener("click", (e) => { if (!(e.target && e.target.closest && e.target.closest("a, button"))) o.onRow(r); });
        tr.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target === tr) o.onRow(r); });
      }
      return tr;
    }) : h("tr", null, h("td", {colspan: String(o.cols.length), class: "l muted"}, o.empty || "맞는 줄이 없습니다")));
    info.textContent = rows.length ? `${fmt.int(s0 + 1)}–${fmt.int(s0 + part.length)} / ${fmt.int(rows.length)}` : "0 / 0";
    prev.disabled = st.page === 0; next.disabled = st.page >= pages - 1;
    bar.hidden = rows.length <= size;
  }
  render();
  return {el, set(rows, keepPage) { st.rows = rows || []; if (!keepPage) st.page = 0; render(); }, sortBy(id, dir) { st.col = id; st.dir = dir || -1; render(); }};
}

// ================================================================ CSV made in the page (no server round trip)
const cell = (v) => {
  const x = v == null ? "" : String(v);
  return /[",\r\n]/.test(x) || /^[=+\-@\t]/.test(x) && !/^-?\d/.test(x) ? `"${x.replace(/"/g, '""')}"` : x;
};
/** csvText([header...], [[...], ...]) -> the CSV text (commas, quotes doubled; a cell that starts like a formula is quoted). */
export const csvText = (header, rows) => [header, ...rows].map((r) => r.map(cell).join(",")).join("\r\n") + "\r\n";
/**
 * downloadCsv(name, header, rows): the CSV as a file the browser saves (UTF-8 with BOM, so Excel reads the Korean). Built
 * here from data the page already has (a Blob URL, released right after); nothing is sent anywhere.
 */
export function downloadCsv(name, header, rows) {
  const blob = new Blob(["\ufeff", csvText(header, rows)], {type: "text/csv;charset=utf-8"});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;                                  // a blob: address of this page's own data (h() keeps only site paths)
  a.download = name;
  a.hidden = true;
  document.body.append(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 1000);
}

// ================================================================ kind colours (one per account kind, every chart)
/** The chart colour token of each account kind (both skins; identity is never colour alone: every line is named). */
export const KIND_SERIES = {fixed: "--series-core", adaptive: "--series-ds", friend: "--series-m5", private: "--pick-4", flip: "--series-coin", all: "--ink"};

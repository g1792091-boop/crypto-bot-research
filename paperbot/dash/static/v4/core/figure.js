// Pixel figures (the old office.js ofFigure recipe: 10 x 14 cells, body in the team's hue, a specialist wears the
// one generic visor, an owner wears a dark suit and a yellow tie), the 대표실 window and real clocks (KST / UTC / NYC).
import {s, h} from "./dom.js";
import {DS_NAME_KO} from "./names.js";

const DS_IDS = Object.keys(DS_NAME_KO);             // the 44 in config order: the number on a DeepSeek cap

// one hue per roster team (agents/roster3.TEAMS): staff are coloured by the team they belong to
export const TEAM_HUE = {market: 205, plan: 268, risk: 2, ops: 150, dev: 185, lead: 42, review: 322, evolve: 95,
  compare: 230, timing: 24, safety: 58, specialist: 0, group: 280, owner: 45};

const px = (x, y, w, hh, c) => s("rect", {x, y, width: w, height: hh, class: c});

/**
 * figure({team, hue, kind: "staff"|"spec"|"owner", size: 24, i: 0, away, breathe, title})
 * -> <svg class="fig"> (aria-hidden: put the person's name in a label next to it).
 * breathe: ambient 1 px idle motion (3 s); off under reduced motion. Only for figures standing still.
 */
export function figure(o = {}) {
  const kind = o.kind || "staff", size = o.size || 24;
  const hue = o.hue != null ? o.hue : TEAM_HUE[o.team] ?? 210;
  const cls = ["fig", kind === "spec" ? "spec" : "", kind === "owner" ? "owner" : "", o.away ? "away" : "", o.breathe ? "breathe" : "", o.cls || ""];
  return s("svg", {class: cls, viewBox: "0 0 10 14", width: size, height: Math.round(size * 1.4), "shape-rendering": "crispEdges",
    "aria-hidden": "true", style: {"--h": hue, "--i": o.i || 0}},
    kind === "spec" ? [px(2, 0, 6, 1, "pv"), px(1, 1, 8, 1, "pv")] : px(2, 0, 6, 2, "ph"),
    px(2, 2, 6, 3, "ps"), px(3, 3, 1, 1, "pe"), px(6, 3, 1, 1, "pe"),
    px(1, 5, 8, 5, kind === "owner" ? "po" : "pb"),
    kind === "owner" ? px(4, 5, 2, 3, "pt") : null,
    px(0, 6, 1, 3, "ps"), px(9, 6, 1, 3, "ps"),
    px(2, 10, 2, 3, "pl l1"), px(6, 10, 2, 3, "pl l2"), px(2, 13, 2, 1, "pf l1"), px(6, 13, 2, 1, "pf l2"));
}

// ---------------------------------------------------------------- the 대표실 window follows Korea time (wave 2 ⑧)
/** The sky of the Korea-time hour: dawn 05-07 / day 07-17 / dusk 17-19 / night 19-05 (Korea has no summer time). */
export const PHASE_KO = {dawn: "새벽", day: "낮", dusk: "저녁", night: "밤"};
export function skyPhase(ms = Date.now()) {
  const hh = new Date(Number(ms) + 9 * 3.6e6).getUTCHours();
  return hh >= 5 && hh < 7 ? "dawn" : hh >= 7 && hh < 17 ? "day" : hh >= 17 && hh < 19 ? "dusk" : "night";
}
// the city's lit windows at dusk and night (fixed spots: the same skyline every time)
const LIT = [[4, 14], [6, 17], [10, 11], [11, 15], [10, 18], [15, 15], [18, 17], [22, 12], [23, 16], [27, 16]];
function drawWindow(svg, ph) {
  const sun = ph === "day" ? px(22, 4, 4, 4, "sn") : ph === "dawn" ? px(4, 7, 4, 3, "sn") : ph === "dusk" ? px(24, 7, 4, 3, "sn") : null;
  const night = ph === "night";
  svg.setAttribute("data-ph", ph);
  svg.replaceChildren(...[px(0, 0, 32, 22, "wf"), px(2, 2, 28, 18, "sk"), ph === "dawn" || ph === "dusk" ? px(2, 7, 28, 3, "hz") : null,
    night ? [px(4, 4, 1, 1, "st"), px(9, 3, 1, 1, "st"), px(12, 6, 1, 1, "st"), px(19, 4, 1, 1, "st"), px(6, 8, 1, 1, "st"),
      px(28, 7, 1, 1, "st"), px(22, 3, 4, 4, "mo"), px(24, 3, 2, 2, "sk")] : null,
    sun, px(3, 12, 5, 8, "ct"), px(9, 9, 4, 11, "ct"), px(14, 13, 6, 7, "ct"), px(21, 10, 4, 10, "ct"), px(26, 14, 3, 6, "ct"),
    ph === "dusk" || night ? LIT.slice(0, night ? LIT.length : 5).map(([x, y]) => px(x, y, 1, 1, "cl")) : null,
    px(15, 2, 2, 18, "wf"), px(2, 10, 28, 1, "wf")].flat().filter(Boolean));
}
const WINDOWS = new Set();
/** The 대표실 window: sky, sun or moon and stars, the city (lit windows after dark) for the Korea-time hour now; it
 *  changes with the real clock (checked with the clocks, every 15 s; never animated). windowArt("night") draws one
 *  fixed phase (the component sheet shows all four) and does not follow the clock. */
export function windowArt(ph) {
  const svg = s("svg", {class: "window", viewBox: "0 0 32 22", "shape-rendering": "crispEdges", "aria-hidden": "true"});
  const fixed = Object.prototype.hasOwnProperty.call(PHASE_KO, ph);
  drawWindow(svg, fixed ? ph : skyPhase());
  if (fixed) return svg;
  WINDOWS.add(svg);
  if (!clockTimer) clockTimer = setInterval(tickClocks, 15000);
  return svg;
}
function tickWindows() {
  const ph = skyPhase();
  for (const w of [...WINDOWS]) {
    if (!w.isConnected) { WINDOWS.delete(w); continue; }
    if (w.getAttribute("data-ph") !== ph) drawWindow(w, ph);
  }
}

// ---------------------------------------------------------------- one pixel character per strategy (wave 2 ⑦)
// The same id always draws the same person: body colour by family (the 36 by style, DeepSeek by its family, the reel
// magenta, coin flips grey), one of six hair / hat shapes from the id; DeepSeek wears a numbered cap (its place in the
// 44), the reel holds a phone, a coin flip has a coin for a head. Head-and-shoulders, 12 x 12 cells.
const hash = (str) => { let x = 2166136261; for (const c of String(str)) { x ^= c.codePointAt(0); x = Math.imul(x, 16777619); } return x >>> 0; };
// 3 x 5 pixel digits for the DeepSeek cap
const DIG = ["111101101101111", "010110010010111", "111001111100111", "111001111001111", "101101111001001", "111100111001111",
  "111100111101111", "111001001010010", "111101111101111", "111101111001111"];
function digit(d, x0, y0, c) {
  const out = [];
  DIG[d].split("").forEach((b, i) => { if (b === "1") out.push(px(x0 + (i % 3), y0 + Math.floor(i / 3), 1, 1, c)); });
  return out;
}
const HAIR = [
  () => [px(3, 1, 6, 2, "ah")],                                      // short
  () => [px(3, 1, 6, 2, "ah"), px(2, 2, 1, 4, "ah"), px(9, 2, 1, 4, "ah")],     // long
  () => [px(4, 0, 1, 1, "ah"), px(6, 0, 1, 1, "ah"), px(8, 0, 1, 1, "ah"), px(3, 1, 6, 2, "ah")],   // spiky
  () => [px(2, 1, 8, 1, "ab"), px(3, 0, 6, 1, "ab"), px(9, 2, 2, 1, "ab")],                    // cap
  () => [px(3, 1, 6, 1, "ah"), px(2, 3, 8, 1, "av")],                                           // visor
  () => [px(5, 0, 2, 1, "ah"), px(3, 1, 6, 2, "ah"), px(3, 3, 1, 1, "ah")],                     // bun
];
/** Body hue of a strategy (the --h of its character): the 36 by style, DeepSeek by family, the reel, coin flips. */
export function stratHue(strategy, kind) {
  const id = String(strategy || "");
  if (kind === "random" || id.startsWith("RANDOM_")) return null;              // grey: the baseline
  if (kind === "reel" || id.startsWith("REEL")) return 300;
  const f = /^F(\d+)_/.exec(id);
  if (f) return (Number(f[1]) * 47 + 170) % 360;                            // 17 DeepSeek families
  return (hash(id) % 12) * 30;                                              // the 36: twelve steady hues
}
/**
 * stratFigure({strategy, kind, n, size, title}) -> <svg class="sfig"> head and shoulders, fixed per strategy.
 * n: DeepSeek's number on the cap (1-44). aria-hidden: put the name next to it. No idle motion (lists stay still).
 */
export function stratFigure(o = {}) {
  const id = String(o.strategy || ""), kind = o.kind || (id.startsWith("RANDOM_") ? "random" : id.startsWith("REEL") ? "reel" : /^F\d+_/.test(id) ? "ds200" : "strategy");
  const size = o.size || 20, hue = stratHue(id, kind), k = hash(id);
  const coinHead = kind === "random";
  const kids = [px(0, 0, 12, 12, "abg")];
  if (coinHead) {
    kids.push(px(3, 1, 6, 6, "ac"), px(2, 2, 8, 4, "ac"), px(5, 2, 2, 4, "acs"), px(4, 3, 4, 2, "acs"), px(4, 7, 4, 1, "as"));
  } else {
    if (kind === "ds200") {
      // a tall cap with its number (3 x 5 digits), the face under it
      const n = Math.max(0, Math.min(99, Number(o.n) || DS_IDS.indexOf(id) + 1));
      kids.push(px(3, 5, 6, 3, "as"), px(4, 6, 1, 1, "ae"), px(7, 6, 1, 1, "ae"), px(2, 0, 9, 5, "ab"), px(1, 4, 11, 1, "ab"));
      if (n >= 10) kids.push(...digit(Math.floor(n / 10), 3, 0, "ad"), ...digit(n % 10, 7, 0, "ad"));
      else if (n) kids.push(...digit(n, 5, 0, "ad"));
    } else {
      kids.push(px(3, 2, 6, 5, "as"), px(4, 4, 1, 1, "ae"), px(7, 4, 1, 1, "ae"), px(5, 6, 2, 1, "am"));
      kids.push(...HAIR[k % HAIR.length]());
    }
  }
  kids.push(px(2, 8, 8, 4, coinHead ? "ag" : "ab2"), px(5, 8, 2, 1, "as"));
  if (kind === "reel") kids.push(px(8, 6, 3, 5, "ap"), px(9, 7, 1, 3, "aps"));
  const nm = o.title || null;
  return s("svg", {class: ["sfig", `k-${kind}`, o.cls || ""], viewBox: "0 0 12 12", width: size, height: size, "shape-rendering": "crispEdges",
    "aria-hidden": nm ? null : "true", role: nm ? "img" : null, "aria-label": nm, style: {"--h": hue == null ? 210 : hue}}, kids);
}

const CLOCKS = new Set();
let clockTimer = null;
function tickClocks() {
  const now = new Date();
  for (const c of [...CLOCKS]) {
    if (!c.isConnected) { CLOCKS.delete(c); continue; }
    let hh, mm;
    try {
      const parts = new Intl.DateTimeFormat("en-GB", {timeZone: c.dataset.tz, hour: "2-digit", minute: "2-digit", hourCycle: "h23"}).formatToParts(now);
      hh = +parts.find((x) => x.type === "hour").value % 24; mm = +parts.find((x) => x.type === "minute").value;
    } catch (e) { hh = now.getUTCHours(); mm = now.getUTCMinutes(); }
    c._hh.setAttribute("transform", `rotate(${(hh % 12) * 30 + mm * 0.5} 10 10)`);
    c._mh.setAttribute("transform", `rotate(${mm * 6} 10 10)`);
    c._ct.textContent = `${c.dataset.l} ${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
  }
  tickWindows();
  if (!CLOCKS.size && !WINDOWS.size && clockTimer) { clearInterval(clockTimer); clockTimer = null; }
}

/** A real clock: clock("KST", "Asia/Seoul"), clock("UTC", "UTC"), clock("NYC", "America/New_York"). Updates each minute. */
export function clock(label, tz) {
  const hh = s("line", {class: "hh", x1: 10, y1: 10, x2: 10, y2: 5.6});
  const mh = s("line", {class: "mh", x1: 10, y1: 10, x2: 10, y2: 3.6});
  const ct = h("span", {class: "ct"}, `${label} --:--`);
  const el = h("div", {class: "clock", dataset: {tz, l: label}, title: `${label} 시각`},
    s("svg", {viewBox: "0 0 20 20", "aria-hidden": "true"}, s("rect", {class: "face", x: 1, y: 1, width: 18, height: 18, rx: 2}),
      px(9.5, 2.5, 1, 2, "tick"), px(15.5, 9.5, 2, 1, "tick"), px(9.5, 15.5, 1, 2, "tick"), px(2.5, 9.5, 2, 1, "tick"),
      hh, mh, px(9.2, 9.2, 1.6, 1.6, "tick")), ct);
  el._hh = hh; el._mh = mh; el._ct = ct;
  CLOCKS.add(el);
  queueMicrotask(tickClocks);
  if (!clockTimer) clockTimer = setInterval(tickClocks, 15000);
  return el;
}

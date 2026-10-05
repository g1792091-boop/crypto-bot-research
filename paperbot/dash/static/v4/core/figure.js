// Pixel figures (the old office.js ofFigure recipe: 10 x 14 cells, body in the team's hue, a specialist wears the
// one generic visor, an owner wears a dark suit and a yellow tie), the 대표실 window and real clocks (KST / UTC / NYC).
import {s, h} from "./dom.js";

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

/** The 대표실 window (sky, sun, city). */
export function windowArt() {
  return s("svg", {class: "window", viewBox: "0 0 32 22", "shape-rendering": "crispEdges", "aria-hidden": "true"},
    px(0, 0, 32, 22, "wf"), px(2, 2, 28, 18, "sk"), px(22, 4, 4, 4, "sn"), px(3, 12, 5, 8, "ct"), px(9, 9, 4, 11, "ct"),
    px(14, 13, 6, 7, "ct"), px(21, 10, 4, 10, "ct"), px(26, 14, 3, 6, "ct"), px(15, 2, 2, 18, "wf"), px(2, 10, 28, 1, "wf"));
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
  if (!CLOCKS.size && clockTimer) { clearInterval(clockTimer); clockTimer = null; }
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

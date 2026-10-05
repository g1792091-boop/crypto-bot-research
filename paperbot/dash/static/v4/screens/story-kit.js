// 오늘의 하이라이트: what the story screen (story.js) and the top of 홈 share. storyRing(ctx) is the row of story rings
// for the home screen (the integrator places it; its look is story-kit.css, which home.css @imports): today first, then
// the run's earlier days, each ring cut into the story's seven pages and lit until this viewer opened that day (seen
// days are a per-viewer convenience in local storage, nothing more). Days are Korea-time calendar days of the run
// (summary.start); D+n is the checkpoint clock's day (the shell chip's number).
import {h, s, fmt, local, serverNow} from "../core/pb.js";

export const PAGES = 7;
const SEEN = "story-seen";
const DAY = 86400000;

/** The hash the story was opened from (closing goes back there instead of stacking history). */
export const nav = {from: null};

export function seenDays() {
  const v = local.get(SEEN, []);
  return Array.isArray(v) ? v.filter((x) => typeof x === "string") : [];
}
export const isSeen = (day) => seenDays().includes(day);
export function markSeen(day) {
  if (!day) return;
  const v = seenDays().filter((d) => d !== day);
  v.push(day);
  local.set(SEEN, v.slice(-90));
}

/** 00:00 KST of a 'YYYY-MM-DD' day (ms). */
export const dayStart = (day) => Date.parse(`${day}T00:00:00+09:00`);
/** D+n on the checkpoint clock (whole days since 00:00 UTC of the start day). */
export const dnOf = (start, ms) => Math.max(0, Math.floor((ms - (start - start % DAY)) / DAY));

/** The run's Korea-time days, newest first: [{day, n, dn}]. n = the Korea-time day number (1 = the start day), the
 *  same count as 흐름 'N일째', so 오늘 and 어제 always differ; dn = D+ on the checkpoint clock at the day's end (now for
 *  today), which moves at 09:00 KST (00:00 UTC). */
export function runDays(start, now = serverNow(), limit = 30) {
  if (!start) return [];
  const out = [];
  const first = dayStart(fmt.dayKey(start));
  for (let t = fmt.kstMidnight(now); t >= first && out.length < limit; t -= DAY) {
    out.push({day: fmt.dayKey(t + 3600000), n: Math.round((t - first) / DAY) + 1, dn: dnOf(start, Math.min(now, t + DAY - 1))});
  }
  return out;
}

/** "오늘" / "어제" / "10/03" */
export function dayWord(day, now = serverNow()) {
  const today = fmt.dayKey(now);
  if (day === today) return "오늘";
  if (day === fmt.dayKey(now - DAY)) return "어제";
  return fmt.mmdd(dayStart(day) + 12 * 3600000);
}

/** The story ring: PAGES arcs around a disc (lit = not opened yet on this device). */
export function ringSvg(o = {}) {
  const n = o.n || PAGES, size = o.size || 60, r = 27, c = 2 * Math.PI * r, gap = n > 1 ? 3.2 : 0;
  const seg = c / n - gap;
  return s("svg", {class: ["sk-svg", o.seen ? "seen" : "", o.cur ? "cur" : ""], viewBox: "0 0 60 60", width: size, height: size, "aria-hidden": "true"},
    Array.from({length: n}, (_, i) => s("circle", {class: "sk-arc", cx: 30, cy: 30, r, fill: "none",
      "stroke-dasharray": `${seg.toFixed(2)} ${(c - seg).toFixed(2)}`, "stroke-dashoffset": (-(i * c / n) + c / 4 - gap / 2).toFixed(2)})),
    s("circle", {class: "sk-disc", cx: 30, cy: 30, r: 23}));
}

/** One ring: a link to that day's story. */
export function ringItem(d, o = {}) {
  const word = dayWord(d.day);
  const seen = isSeen(d.day);
  const a = h("a", {class: ["sk-item", o.big ? "big" : "", seen ? "seen" : ""], href: o.href,
    "aria-label": `${word} 하이라이트 · ${d.n ?? "—"}일째${seen ? " · 본 날" : ""}`, role: "listitem",
    onclick: () => { nav.from = location.hash || "#/home"; }},
  h("span", {class: "sk-ava"}, ringSvg({seen, size: o.big ? 66 : 58}),
    h("span", {class: "sk-in"}, h("b", null, d.n == null ? "—" : String(d.n)), h("small", null, "일째"))),
  h("span", {class: "sk-lab"}, word));
  return a;
}

/**
 * storyRing(ctx) -> <section class="sk-ring"> for the top of 홈: today's ring and the run's earlier days (newest
 * first, two weeks; the story's own day picker has every day). Reads the shared summary (ctx.watch), no extra request.
 */
export function storyRing(ctx) {
  const row = h("div", {class: "sk-row", role: "list"});
  const el = h("section", {class: "sk-ring", "aria-label": "오늘의 하이라이트: 하루를 일곱 장으로"},
    h("div", {class: "sk-cap"}, h("b", null, "하이라이트"), h("span", null, "하루를 일곱 장으로 · 눌러서 넘기기")), row);
  let sig = "";
  const render = (sum) => {
    const start = sum && sum.start;
    const days = start ? runDays(start, serverNow(), 14) : [{day: fmt.dayKey(serverNow()), n: null, dn: (sum && sum.restart && sum.restart.day) || 0}];
    const seen = seenDays();
    const next = days.map((d) => d.day + d.n + (seen.includes(d.day) ? "s" : "")).join("|");
    if (next === sig) return;
    sig = next;
    row.replaceChildren(...days.map((d, i) => ringItem(d, {big: i === 0, href: ctx.href("story", i === 0 ? null : d.day)})));
  };
  render(null);
  // (홈 is mounted again when the viewer comes back from a story, so a day just seen is drawn dim then)
  if (ctx && typeof ctx.watch === "function") ctx.watch("summary", (v) => { if (v) render(v); });
  return el;
}

// ---------------------------------------------------------------- small pixel art (crispEdges SVG, token colours)
const R = (x, y, w, hh, c) => s("rect", {x, y, width: w, height: hh, class: c});
/** Pixel icons for the story pages: crown, up, down, shield, bolt, flag, cal, sprout. */
export function pixIcon(name, size = 28) {
  const P = {
    crown: [R(1, 4, 2, 2, "pa"), R(6, 2, 2, 2, "pa"), R(11, 4, 2, 2, "pa"), R(2, 6, 10, 1, "pa"), R(2, 7, 10, 4, "pa"), R(4, 8, 2, 2, "pd"), R(8, 8, 2, 2, "pd"), R(2, 11, 10, 2, "ph")],
    down: [R(5, 1, 4, 7, "pr"), R(2, 7, 10, 2, "pr"), R(3, 9, 8, 1, "pr"), R(4, 10, 6, 1, "pr"), R(5, 11, 4, 1, "pr"), R(6, 12, 2, 1, "pr")],
    up: [R(6, 1, 2, 1, "pg"), R(5, 2, 4, 1, "pg"), R(4, 3, 6, 1, "pg"), R(3, 4, 8, 1, "pg"), R(2, 5, 10, 2, "pg"), R(5, 7, 4, 6, "pg")],
    shield: [R(2, 1, 10, 2, "pl"), R(2, 3, 10, 5, "pl"), R(3, 8, 8, 2, "pl"), R(4, 10, 6, 1, "pl"), R(5, 11, 4, 1, "pl"), R(6, 12, 2, 1, "pl"),
      R(4, 5, 1, 1, "pg"), R(5, 6, 1, 1, "pg"), R(6, 7, 1, 1, "pg"), R(7, 6, 1, 1, "pg"), R(8, 5, 1, 1, "pg"), R(9, 4, 1, 1, "pg")],
    bolt: [R(7, 0, 4, 2, "pw"), R(6, 2, 4, 2, "pw"), R(5, 4, 4, 2, "pw"), R(3, 6, 8, 2, "pw"), R(6, 8, 3, 2, "pw"), R(5, 10, 3, 2, "pw"), R(4, 12, 2, 2, "pw")],
    flag: [R(2, 1, 1, 13, "ph"), R(3, 1, 3, 2, "pk"), R(6, 1, 3, 2, "pq"), R(9, 1, 3, 2, "pk"), R(3, 3, 3, 2, "pq"), R(6, 3, 3, 2, "pk"), R(9, 3, 3, 2, "pq"), R(3, 5, 3, 2, "pk"), R(6, 5, 3, 2, "pq"), R(9, 5, 3, 2, "pk")],
    cal: [R(1, 2, 12, 11, "pl"), R(1, 2, 12, 3, "pa"), R(3, 1, 2, 3, "pk"), R(9, 1, 2, 3, "pk"), R(3, 7, 2, 2, "pk"), R(6, 7, 2, 2, "pk"),
      R(9, 7, 2, 2, "pk"), R(3, 10, 2, 2, "pk"), R(6, 10, 2, 2, "pa")],
    sprout: [R(6, 6, 2, 7, "pg"), R(2, 3, 4, 2, "pg"), R(3, 5, 3, 1, "pg"), R(8, 2, 4, 2, "pg"), R(8, 4, 3, 1, "pg"), R(3, 12, 8, 2, "ph")],
  };
  return s("svg", {class: "pix", viewBox: "0 0 14 14", width: size, height: size, "shape-rendering": "crispEdges", "aria-hidden": "true"}, P[name] || P.flag);
}

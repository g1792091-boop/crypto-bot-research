// 터미널 kit: the panel frame, the ratio bar and the short ages every part of the terminal uses.
import {h, ui, fmt, motion, serverNow} from "../core/pb.js";

/** Every market-wide number on the terminal (movers, large orders, liquidations) carries this label: not our bots. */
export const MARKET_LABEL = "시장 전체 (우리 봇 아님)";

/** A short age for dense rows (term v2, the HelloQuant lists): "6s" / "4m" / "2h" / "3d" against the server clock. */
export const age = (ms, now = serverNow()) => {
  const s = Math.max(0, Math.floor((now - Number(ms)) / 1000));
  if (!Number.isFinite(s)) return "—";
  return s < 60 ? `${s}s` : s < 3600 ? `${Math.floor(s / 60)}m` : s < 86400 ? `${Math.floor(s / 3600)}h` : `${Math.floor(s / 86400)}d`;
};
/** An age cell that the 1 s clock tick repaints (ages() below): text only, never motion. */
export const ageCell = (ms) => h("span", {class: "term-age num", "data-t": String(ms), title: fmt.kst(ms)}, age(ms));
/** Repaint every age cell under ``root`` (the terminal's 1 s tick: a text change, no request). */
export function ages(root) {
  const now = serverNow();
  for (const el of root.querySelectorAll(".term-age[data-t]")) {
    const t = age(Number(el.dataset.t), now);
    if (el.textContent !== t) el.textContent = t;
  }
}

/** A terminal panel: a thin-edged box with a small head (title, a sub line, optional right side) and a body.
 *  o: {sub, lead: [el] (after the title), acts: [el], cls, label, scroll (the body scrolls inside the panel)}. */
export function panel(title, o = {}, ...kids) {
  const sub = h("span", {class: "term-phs"}, o.sub || "");
  // the head's thin accent underline: a light runs along it once when the panel really receives data (ping below)
  const head = h("div", {class: "term-ph"}, h("h2", null, title), ...(o.lead || []), sub, h("span", {class: "grow"}), ...(o.acts || []),
    h("i", {class: "term-uline", "aria-hidden": "true"}));
  const body = h("div", {class: ["term-pb", o.scroll ? "scroll" : ""]}, kids);
  const el = h("section", {class: ["term-p", o.cls || ""], "aria-label": o.label || title}, head, body);
  el.head = head; el.body = body; el.sub = sub;
  return el;
}

const PING_GAP_MS = 1200;
/** A panel REALLY received data (a new row, a real tick, a new answer that changed something): the light runs along
 *  its head's underline once (terminal.css, ~0.9 s), at most once per 1.2 s per panel so it reads as "data came",
 *  never a strobe. Skipped under reduced motion and while the page is hidden; never called from a timer. */
export function ping(el) {
  const u = el && el.head && el.head.querySelector(".term-uline");
  if (!u || motion.reduced() || !motion.visible()) return;
  const now = Date.now();
  if (now - (el._ping || 0) < PING_GAP_MS) return;
  el._ping = now;
  u.classList.remove("run"); void u.offsetWidth; u.classList.add("run");
}

/**
 * ratioBar([{key, label, tone}]) -> element with .set({key: n}): a segmented bar whose widths move to the new shares
 * (a CSS width transition, off under prefers-reduced-motion) and a legend with each share. Empty counts: a grey bar.
 */
export function ratioBar(parts, o = {}) {
  const segs = parts.map((p) => h("i", {class: ["term-rb-s", p.tone], style: {width: (100 / parts.length).toFixed(2) + "%"}}));
  const labs = parts.map((p) => h("span", {class: ["term-rb-l", p.tone]}, p.label, " ", h("b", {class: "num"}, "—")));
  const el = h("div", {class: ["term-rb", o.cls || ""], role: "img", "aria-label": o.label || "비율"},
    h("div", {class: "term-rb-t"}, segs), h("div", {class: "term-rb-k"}, labs));
  el.set = (counts, fmtFn) => {
    const tot = parts.reduce((s, p) => s + (Number(counts[p.key]) || 0), 0);
    el.classList.toggle("none", !tot);
    parts.forEach((p, i) => {
      const n = Number(counts[p.key]) || 0, sh = tot ? n / tot : 1 / parts.length;
      segs[i].style.width = (sh * 100).toFixed(2) + "%";
      labs[i].lastChild.textContent = tot ? (fmtFn ? fmtFn(n, sh) : fmt.pct(sh, 0, false)) : "—";
    });
    el.setAttribute("aria-label", `${o.label || "비율"}: ${parts.map((p, i) => `${p.label} ${labs[i].lastChild.textContent}`).join(", ")}`);
  };
  return el;
}

/**
 * Two panels that share one place on a short window (under 940 px tall, terminal.css): a small switch goes into both
 * heads and the column's data-<attr> says which one shows. items: [{id, label, panel}]; onPick(id) after a switch.
 * On a tall window both panels show and the switches are hidden (CSS).
 */
export function duoSwitch(col, attr, items, onPick) {
  let cur = items[0].id;
  col.dataset[attr] = cur;
  const segs = items.map((it) => {
    const sg = ui.seg(items.map((x) => ({id: x.id, label: x.label})), cur, (id) => {
      cur = id; col.dataset[attr] = id; segs.forEach((x) => x.set(id)); if (onPick) onPick(id);
    }, {label: `${items.map((x) => x.label).join("·")} 바꾸기`});
    sg.classList.add("term-duoseg");
    it.panel.head.append(sg);
    return sg;
  });
  return {get: () => cur};
}

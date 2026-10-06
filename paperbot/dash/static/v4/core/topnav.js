// The top bar's 5 groups (owners 10/06 13:27: the icon-only left rail was "불편", they want the top menu back, and
// still few clicks): each group is a button that opens a small dropdown listing ALL of that group's screens (icon +
// Korean name + its number key, the current one lit, 꺼짐 / news dots as on the tabs), so any screen is one click away
// without first switching group. The sub tabs of the current group stay under the bar as before (core/shell.js).
//   mouse     hovering a group opens its list (a short delay; leaving closes it); a click keeps it open, a second
//             click closes it
//   touch     a tap opens / closes it (no hover)
//   keyboard  Enter / Space open or close; ↓ / ↑ open and go to the first / last screen; inside: ↓ ↑ Home End move,
//             ← → go to the next group's list; Esc closes and returns to the group; Tab out closes
//   anywhere  a click outside or Esc closes it; choosing a screen closes it
// The pattern is a disclosure navigation (button aria-expanded + aria-controls, a list of links), not an ARIA menu.
// Drawn by core/shell.js on every route / feature / badge change; an open list and the keyboard focus survive the
// redraw. The bar shows from 900 px (base.css .groups); phones keep the bottom bar. Look: core/nav.css (.gmenu).
import {h, $} from "./dom.js";
import {GROUPS, SCREENS, href, icon, screenIcon, keyOf, menuScreens} from "./routes.js";
import {features} from "./features.js";

const st = {open: null, pinned: false, openT: 0, closeT: 0, wired: false, cur: null};
const OPEN_DELAY = 90, CLOSE_DELAY = 260;

const bar = () => $("#groups");
const wrapOf = (gid) => { const b = bar(); return b ? b.querySelector(`.gw[data-gw="${gid}"]`) : null; };
const btnOf = (gid) => { const w = wrapOf(gid); return w ? w.querySelector(".gbtn") : null; };
const linksOf = (gid) => { const w = wrapOf(gid); return w ? [...w.querySelectorAll(".gm-a")] : []; };
const clearTimers = () => { clearTimeout(st.openT); clearTimeout(st.closeT); st.openT = st.closeT = 0; };

/** Open one group's list (pinned: by a click / the keyboard, so leaving with the mouse does not close it). */
export function openGroupMenu(gid, pinned = false) {
  clearTimers();
  if (st.open === gid) { if (pinned) st.pinned = true; return; }
  if (st.open) closeGroupMenu();
  const w = wrapOf(gid);
  if (!w) return;
  st.open = gid;
  st.pinned = !!pinned;
  w.dataset.open = "1";
  w.querySelector(".gbtn").setAttribute("aria-expanded", "true");
  w.querySelector(".gmenu").hidden = false;
}
/** Close the open list (focusBtn: give the focus back to its group button, after Esc). */
export function closeGroupMenu(focusBtn = false) {
  clearTimers();
  const gid = st.open;
  st.open = null; st.pinned = false;
  if (!gid) return;
  const w = wrapOf(gid);
  if (!w) return;
  delete w.dataset.open;
  w.querySelector(".gbtn").setAttribute("aria-expanded", "false");
  w.querySelector(".gmenu").hidden = true;
  if (focusBtn) w.querySelector(".gbtn").focus({preventScroll: true});
}
export const groupMenuOpen = () => st.open;

function moveGroup(gid, dir, focusFirst) {
  const ids = GROUPS.map((g) => g.id);
  const next = ids[(ids.indexOf(gid) + dir + ids.length) % ids.length];
  const wasOpen = !!st.open;
  if (wasOpen || focusFirst) openGroupMenu(next, true);
  if (focusFirst) { const l = linksOf(next); if (l.length) { l[0].focus(); return; } }
  const b = btnOf(next);
  if (b) b.focus();
}

function onBtnKey(e, gid) {
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    openGroupMenu(gid, true);
    const l = linksOf(gid);
    if (l.length) l[e.key === "ArrowDown" ? 0 : l.length - 1].focus();
  } else if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
    e.preventDefault();
    moveGroup(gid, e.key === "ArrowRight" ? 1 : -1, false);
  }
}
function onLinkKey(e, gid) {
  const l = linksOf(gid), i = l.indexOf(document.activeElement);
  const to = (k) => { e.preventDefault(); if (l.length) l[(k + l.length) % l.length].focus(); };
  if (e.key === "ArrowDown") to(i + 1);
  else if (e.key === "ArrowUp") to(i - 1);
  else if (e.key === "Home") to(0);
  else if (e.key === "End") to(l.length - 1);
  else if (e.key === "ArrowRight" || e.key === "ArrowLeft") { e.preventDefault(); moveGroup(gid, e.key === "ArrowRight" ? 1 : -1, true); }
}

function wire() {
  if (st.wired) return;
  st.wired = true;
  // a press outside the open list (or its button) closes it
  document.addEventListener("pointerdown", (e) => {
    if (!st.open) return;
    const w = wrapOf(st.open);
    if (w && !w.contains(e.target)) closeGroupMenu();
  }, true);
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || !st.open) return;
    const w = wrapOf(st.open);
    closeGroupMenu(!!(w && w.contains(document.activeElement)));
  });
}

function menuLink(n, cur, badges) {
  const m = SCREENS[n], off = m.soft && !features[m.soft], k = keyOf(n);
  return h("li", null, h("a", {class: ["gm-a", off ? "off" : ""], href: href(n), "aria-current": n === cur ? "page" : null, dataset: {screen: n},
    "aria-label": `${m.ko}${off ? " (아직 켜지지 않음)" : ""}${badges[n] ? " · 새 소식" : ""}${k ? ` · 단축키 ${k}` : ""}`},
  h("span", {class: "gm-ic", "aria-hidden": "true"}, screenIcon(n)),
  h("span", {class: "gm-t"}, m.ko),
  off ? h("span", {class: "pp thin", "aria-hidden": "true"}, "꺼짐") : null,
  badges[n] ? h("i", {class: "ndot", "aria-hidden": "true"}) : null,
  k ? h("kbd", {"aria-hidden": "true", title: `단축키 ${k}`}, k) : null));
}

/**
 * renderGroups(current screen name, badges): draws #groups, the 5 group buttons with their lists. The current group's
 * button is lit (aria-current="true"); an open list and the focus inside the bar are kept across the redraw.
 */
export function renderGroups(cur, badges) {
  const nav = bar();
  if (!nav) return;
  wire();
  const gid = (SCREENS[cur] || SCREENS.home).group;
  const act = document.activeElement && nav.contains(document.activeElement) ? document.activeElement : null;
  const focusKey = act ? (act.dataset.screen ? `.gm-a[data-screen="${act.dataset.screen}"]` : act.dataset.group ? `.gbtn[data-group="${act.dataset.group}"]` : null) : null;
  // a redraw for a badge or a feature keeps the open list; a new screen closes it (number keys, swipe, a link)
  const open = st.cur === cur ? st.open : null, pinned = st.pinned;
  st.cur = cur;
  clearTimers();
  st.open = null; st.pinned = false;
  nav.replaceChildren(...GROUPS.map((g) => {
    const list = menuScreens(g, features);
    const btn = h("button", {type: "button", class: "gbtn", id: `gb-${g.id}`, "aria-expanded": "false", "aria-controls": `gm-${g.id}`,
      "aria-current": g.id === gid ? "true" : null, dataset: {group: g.id},
      "aria-label": `${g.ko} 묶음: 화면 ${list.length}개 펼치기${g.screens.some((n) => badges[n]) ? " · 새 소식" : ""}`,
      onclick: () => {
        if (st.open === g.id && st.pinned) closeGroupMenu();
        else openGroupMenu(g.id, true);
      },
      onkeydown: (e) => onBtnKey(e, g.id)},
    icon(g.id), h("span", null, g.ko),
    g.screens.some((n) => badges[n]) ? h("i", {class: "ndot", "aria-hidden": "true"}) : null,
    h("span", {class: "gcar", "aria-hidden": "true"}, "▾"));
    const menu = h("div", {class: "gmenu", id: `gm-${g.id}`, hidden: true, onkeydown: (e) => onLinkKey(e, g.id)},
      h("p", {class: "gm-h", "aria-hidden": "true"}, g.ko),
      h("ul", {"aria-label": `${g.ko} 화면`}, list.map((n) => menuLink(n, cur, badges))));
    // a chosen screen closes the list (also the current one, which changes no route)
    menu.addEventListener("click", (e) => { if (e.target.closest(".gm-a")) closeGroupMenu(); });
    const w = h("div", {class: "gw", dataset: {gw: g.id}}, btn, menu);
    w.addEventListener("pointerenter", (e) => {
      if (e.pointerType !== "mouse") return;
      clearTimeout(st.closeT);
      if (st.open === g.id) return;
      clearTimeout(st.openT);
      // another list already open: follow the mouse at once; else wait a moment (a pass across the bar opens nothing)
      st.openT = setTimeout(() => openGroupMenu(g.id, false), st.open ? 0 : OPEN_DELAY);
    });
    w.addEventListener("pointerleave", (e) => {
      if (e.pointerType !== "mouse") return;
      clearTimeout(st.openT);
      if (st.open === g.id && !st.pinned) st.closeT = setTimeout(() => { if (st.open === g.id && !st.pinned) closeGroupMenu(); }, CLOSE_DELAY);
    });
    w.addEventListener("focusout", (e) => {
      if (st.open === g.id && e.relatedTarget && !w.contains(e.relatedTarget)) closeGroupMenu();
    });
    return w;
  }));
  if (open && GROUPS.some((g) => g.id === open)) openGroupMenu(open, pinned);
  if (focusKey) { const el = nav.querySelector(focusKey); if (el) el.focus({preventScroll: true}); }
}

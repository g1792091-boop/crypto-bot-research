// Fewer clicks (owners 10/06), the keyboard and the thumb:
//   1-9  jump to 터미널 · 홈 · 포지션 · 매매법 · 순위표 · 회의실 · 차트 · 시장 · 서버 (routes.js KEYS; the rail's tooltips
//        show the number). Never while typing in a box, never with Ctrl / Alt / Cmd.
//   /    opens 찾기 (core/find.js).
//   ,    opens 설정 (core/settings.js: every per-device choice in one panel).
//   phone: a sideways swipe on the screen moves to the next / previous screen of the same group (the sub tabs' order).
//        Not on a chart, a table or a row that scrolls sideways itself, a form field, or a slider; never while this
//        device turned it off in 설정 (core/prefs.js swipeOn).
import {SCREENS, GROUPS, KEYS, href, parseHash} from "./routes.js";
import {features} from "./features.js";
import {toast} from "./ui.js";
import {openFind, findOpen} from "./find.js";
import {closePeek, peekOpen} from "./drawer.js";
import {openSettings, settingsOpen} from "./settings.js";
import {swipeOn} from "./prefs.js";

const typing = (el) => !!el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));

/** The screen a number key opens ("1" -> 터미널 ...), null for other keys. */
export const keyScreen = (k) => (/^[1-9]$/.test(k) ? KEYS[Number(k) - 1] || null : null);

function go(name) {
  closePeek(() => { const to = href(name); if (location.hash !== to) location.hash = to; });
}

/** The neighbour of the current screen inside its group (dir +1 / -1), null at either end. */
export function neighbour(cur, dir) {
  const m = SCREENS[cur];
  if (!m) return null;
  const g = GROUPS.find((x) => x.id === m.group);
  if (!g) return null;
  const list = g.screens.filter((n) => SCREENS[n] && !SCREENS[n].hidden && (!SCREENS[n].feature || features[SCREENS[n].feature]));
  const i = list.indexOf(cur);
  if (i < 0) return null;
  return list[i + dir] || null;
}

/** A touch that starts here belongs to the element (a chart, a sideways-scrolling table / tab row, a field). */
function ownsSideways(el) {
  for (let e = el; e && e !== document.body; e = e.parentElement) {
    if (e.nodeType !== 1) continue;
    if (typing(e) || e.tagName === "CANVAS" || e.tagName === "IFRAME" || e.matches("input[type=range], [data-noswipe], .tv-lightweight-charts")) return true;
    if (e.scrollWidth > e.clientWidth + 2) {
      const ox = getComputedStyle(e).overflowX;
      if (ox === "auto" || ox === "scroll") return true;
    }
  }
  return false;
}

function startSwipe() {
  const main = document.getElementById("screen");
  if (!main) return;
  let s = null;
  main.addEventListener("touchstart", (e) => {
    if (e.touches.length !== 1 || peekOpen() || findOpen() || settingsOpen() || !swipeOn()) { s = null; return; }
    const t = e.touches[0];
    s = ownsSideways(e.target) ? null : {x: t.clientX, y: t.clientY, at: Date.now()};
  }, {passive: true});
  main.addEventListener("touchend", (e) => {
    if (!s) return;
    const t = e.changedTouches[0];
    const dx = t.clientX - s.x, dy = t.clientY - s.y, dt = Date.now() - s.at;
    s = null;
    if (dt > 700 || Math.abs(dx) < 70 || Math.abs(dx) < 2 * Math.abs(dy)) return;
    if (window.getSelection && String(window.getSelection())) return;      // selecting text
    const cur = parseHash(location.hash).name;
    const next = neighbour(cur, dx < 0 ? 1 : -1);
    if (!next) { toast(dx < 0 ? "이 묶음의 마지막 화면입니다" : "이 묶음의 첫 화면입니다"); return; }
    go(next);
  }, {passive: true});
  main.addEventListener("touchcancel", () => { s = null; }, {passive: true});
}

export function startNavKeys() {
  document.addEventListener("keydown", (e) => {
    if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || e.isComposing || typing(e.target) || findOpen()) return;
    if (document.querySelector(".tour-card")) return;               // the first-visit tour has the keyboard
    if (settingsOpen()) return;                                      // the 설정 panel has the keyboard (Esc closes it)
    if (e.key === "/") { e.preventDefault(); openFind(); return; }
    if (e.key === ",") { e.preventDefault(); openSettings(); return; }
    const name = keyScreen(e.key);
    if (!name || e.repeat) return;
    e.preventDefault();
    go(name);
  });
  startSwipe();
}

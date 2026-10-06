// The menu strip (owners 10/06 ~14:00, with a photo of the old v3 tab bar: "저렇게 클릭해서 바로 들어갈수있는 버튼들을
// 많이 만들어줬으면", "왼쪽에 그림으로 되어있는데 너무 헷갈려", "바로 들어갈수있는 버튼들을 각각 만들면 어떨까"): every screen
// of the menu is its own plain text button in one row under the top bar, like v3. No icons, no group to open first, no
// dropdown. The groups (routes.js NAV: 거래 · 성적 · 매매법 · AI 직원 · 서버) are thin lines between the buttons (their
// names stay in the left rail's headings, the "묶음 › 화면" line and 찾기: a caption in the row read like one more button,
// "매매법 매매법"); a screen added to routes.js shows here by itself. The current screen is bold with an accent
// underline; a screen with news has a dot after its name ("에이전트 방 ●", the shell's badges); a feature that is off
// is grey with 꺼짐. Each button's tooltip names its number key (1-9 = the first nine buttons, core/navkeys.js).
//   PC (1200 px and up)  the buttons wrap: one row on a 1920 window at 보통, a tidy second row on a narrower window or
//                        with 크게 / 아주 크게 (a group never splits; the line before a group that starts a row goes)
//   below 1200 px        the same buttons as one row that scrolls sideways (swipe; a mouse wheel scrolls it too), the
//                        current one brought into view; on a phone 찾기 stays at its left edge; the phone's bottom bar
//                        stays as it was (core/shell.js)
// The row's real height goes to --sub-h on <html>, so the screens' sticky parts sit under it however many rows it has.
// Drawn into #subtabs by core/shell.js on every route / feature / badge change (the focus and the scroll survive).
// Look: core/nav.css (.strip, .sb). The left rail (core/rail.js) lists the same buttons when chosen (메뉴 위치 왼쪽).
import {h, $} from "./dom.js";
import {SCREENS, JOINED, href, keyOf, navGroups} from "./routes.js";
import {features} from "./features.js";
import {reduced} from "./motion.js";

const st = {cur: null, wired: false, ro: null};
const bar = () => $("#subtabs");
/** True while the strip scrolls sideways (below 1200 px) instead of wrapping. */
const scrolls = (nav) => getComputedStyle(nav).flexWrap === "nowrap";

/** One button: the screen's name (a hidden bold copy keeps its width, so lighting it moves nothing), 꺼짐, the dot. */
function button(it, cur, badges) {
  const m = SCREENS[it.to];
  const on = it.screens.includes(cur);
  const off = it.screens.every((n) => SCREENS[n].soft && !features[SCREENS[n].soft]);
  const news = it.screens.some((n) => badges[n]);
  const k = keyOf(it.to);
  const what = it.screens.length > 1 ? it.screens.map((n) => SCREENS[n].ko).join(" · ") : (m.title || m.ko);
  const tip = `${what}${off ? " (아직 켜지지 않음)" : ""}${k ? ` · 숫자 키 ${k}` : ""}`;
  return h("a", {class: ["sb", off ? "off" : ""], href: href(it.to), "aria-current": on ? "page" : null, title: tip,
    "aria-keyshortcuts": k, dataset: {sb: it.id}},
  h("span", {class: "sb-t", dataset: {t: it.ko}}, it.ko),
  off ? h("span", {class: "pp thin"}, "꺼짐") : null,
  news ? h("i", {class: "ndot", "aria-label": "새 소식"}) : null);
}

/** After a draw or a resize: the row's height to --sub-h, and the group lines at a row's start hidden. */
function measure() {
  const nav = bar();
  if (!nav) return;
  const px = nav.offsetHeight;
  const root = document.documentElement;
  if (root.style.getPropertyValue("--sub-h") !== `${px}px`) root.style.setProperty("--sub-h", `${px}px`);
  let top = null;
  for (const g of nav.querySelectorAll(".sg")) {
    const t = g.offsetTop;
    g.toggleAttribute("data-rowstart", top != null && t > top + 4);
    top = t;
  }
}

function wire(nav) {
  if (st.wired) return;
  st.wired = true;
  // a mouse wheel over the sideways row scrolls it (a window narrower than 1200 px with a mouse)
  nav.addEventListener("wheel", (e) => {
    if (e.ctrlKey || nav.scrollWidth <= nav.clientWidth + 1 || Math.abs(e.deltaX) >= Math.abs(e.deltaY)) return;
    const before = nav.scrollLeft;
    nav.scrollLeft += e.deltaMode === 1 ? e.deltaY * 16 : e.deltaMode === 2 ? e.deltaY * nav.clientWidth : e.deltaY;
    if (nav.scrollLeft !== before) e.preventDefault();            // at either end the page scrolls as usual
  }, {passive: false});
  if (typeof ResizeObserver === "function") st.ro = new ResizeObserver(() => measure());
  else window.addEventListener("resize", measure);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(measure, () => {});
}

/** Bring the current button into the middle of the sideways row (only that row: the page itself never scrolls). */
function center(nav, smooth) {
  const a = nav.querySelector('.sb[aria-current="page"]');
  if (!a || !scrolls(nav)) return;
  // the phone's 찾기 stays at the row's left edge (sticky): the middle of what is left of the row
  const stuck = [...nav.querySelectorAll(".findsub")].find((x) => x.offsetParent !== null);
  const r = a.getBoundingClientRect(), n = nav.getBoundingClientRect();
  const from = stuck ? stuck.getBoundingClientRect().right : n.left;
  if (r.left >= from + 24 && r.right <= n.right - 24 && !smooth) return;
  const left = nav.scrollLeft + (r.left + r.width / 2) - (from + n.right) / 2;
  nav.scrollTo({left: Math.max(0, left), behavior: smooth && !reduced() ? "smooth" : "auto"});
}

/**
 * renderStrip(current screen name, badges, {lead, tools}): draws #subtabs. lead: nodes before the buttons (the phone's
 * 글자 크기 and 찾기); tools: nodes after them, pushed to the row's end (글자 크기, 화면 색, 예전 화면, 메뉴 위치).
 */
export function renderStrip(cur, badges, {lead = [], tools = []} = {}) {
  const nav = bar();
  if (!nav) return;
  wire(nav);
  const act = document.activeElement && nav.contains(document.activeElement) ? document.activeElement : null;
  const focusId = act && act.dataset.sb ? act.dataset.sb : null;
  const first = st.cur == null, moved = st.cur !== cur;
  st.cur = cur;
  const groups = navGroups(features).map((g) => h("div", {class: "sg", role: "group", "aria-label": g.ko, title: g.ko, dataset: {group: g.group}},
    g.items.map((it) => button(it, cur, badges))));
  const keepX = nav.scrollLeft;
  nav.replaceChildren(...lead, ...groups, h("span", {class: "strip-tools"}, tools));
  nav.scrollLeft = keepX;                                          // a badge or a feature redraw keeps the row where it was
  if (st.ro) { st.ro.disconnect(); st.ro.observe(nav); for (const g of groups) st.ro.observe(g); }
  measure();
  if (moved) center(nav, !first);
  if (focusId) { const b = nav.querySelector(`.sb[data-sb="${focusId}"]`); if (b) b.focus({preventScroll: true}); }
}

/**
 * joinedTabs(screen) -> for a screen that shares one menu button with others (routes.js JOINED: 도움말 = 어떻게
 * 돌아가나 + 자주 묻는 질문), a small row of links to each of them, the current one lit, so every one is one click away
 * from the button; null for any other screen. The screen puts it right under its title.
 */
export function joinedTabs(name) {
  const j = JOINED.find((x) => x.screens.includes(name));
  if (!j) return null;
  return h("nav", {class: "jtabs", "aria-label": j.ko},
    h("span", {class: "jt-k"}, j.ko),
    j.screens.filter((n) => SCREENS[n] && !SCREENS[n].hidden).map((n) => h("a", {class: "jt-a", href: href(n),
      "aria-current": n === name ? "page" : null}, SCREENS[n].ko)));
}

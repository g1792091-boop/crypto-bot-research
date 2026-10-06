// The PC left rail (owners 10/06: "들어가는 클릭버튼이 너무 많다"): on a window at least 1200 px wide every screen of
// the 5 groups is ONE click away, as a slim column of pixel icons down the left edge (thin lines between the groups,
// the label in a tooltip on hover / keyboard focus, the current screen lit with the accent, the small dot of a screen
// with news). At its foot: 글자 크기, 화면 색 and 예전 화면 (they live at the end of the sub tabs below 1200 px, where the
// rail is hidden and the group bar + sub tabs stay as they were). Drawn by core/shell.js on every route / feature /
// badge change; base.css (.rail) places it, core/nav.css styles it.
import {h, $} from "./dom.js";
import {GROUPS, SCREENS, KEYS, href, screenIcon} from "./routes.js";
import {features} from "./features.js";
import {textCycle} from "./textsize.js";
import {skinCycle} from "./skin.js";

const keyOf = (n) => { const i = KEYS.indexOf(n); return i < 0 ? null : String(i + 1); };
/** The screens of a group the menu shows now (hidden ones out, PC-only / feature screens only while they run). */
export function visibleScreens(g) {
  return g.screens.filter((n) => SCREENS[n] && !SCREENS[n].hidden && (!SCREENS[n].feature || features[SCREENS[n].feature]));
}

let tip = null;
function showTip(a) {
  if (!tip) { tip = h("div", {class: "rail-tip", id: "railtip", role: "tooltip", hidden: true}); document.body.append(tip); }
  const r = a.getBoundingClientRect();
  tip.replaceChildren(h("span", {class: "rail-tip-g"}, a.dataset.group), h("b", null, a.dataset.tip),
    ...[a.dataset.off ? h("span", {class: "pp thin"}, "꺼짐") : null, a.dataset.key ? h("kbd", null, a.dataset.key) : null].filter(Boolean));
  tip.hidden = false;
  tip.style.top = `${Math.round(r.top + r.height / 2)}px`;
  tip.style.left = `${Math.round(r.right + 10)}px`;
  a.setAttribute("aria-describedby", "railtip");
}
function hideTip(a) {
  if (tip) tip.hidden = true;
  if (a) a.removeAttribute("aria-describedby");
}

/**
 * renderRail(current screen name, badges, onRedraw): draws #rail. onRedraw: after 글자 크기 / 화면 색 (the router draws
 * the screen again, so the charts measure their labels in the new size and colours).
 */
export function renderRail(cur, badges, onRedraw) {
  const nav = $("#rail");
  if (!nav) return;
  const curGroup = (SCREENS[cur] || SCREENS.home).group;
  const groups = GROUPS.map((g, gi) => {
    const links = visibleScreens(g).map((n) => {
      const m = SCREENS[n], off = m.soft && !features[m.soft], k = keyOf(n);
      return h("a", {class: ["rail-a", off ? "off" : ""], href: href(n), "aria-current": n === cur ? "page" : null,
        "aria-label": `${m.ko}${off ? " (아직 켜지지 않음)" : ""}${k ? ` · 단축키 ${k}` : ""}`, dataset: {screen: n, tip: m.ko, group: g.ko, key: k, off: off ? "1" : null},
        onmouseenter: (e) => showTip(e.currentTarget), onmouseleave: (e) => hideTip(e.currentTarget),
        onfocus: (e) => showTip(e.currentTarget), onblur: (e) => hideTip(e.currentTarget), onclick: () => hideTip()},
      screenIcon(n), badges[n] ? h("i", {class: "ndot", "aria-label": "새 소식"}) : null);
    });
    return [gi ? h("span", {class: "rail-sep", "aria-hidden": "true"}) : null,
      h("div", {class: ["rail-g", g.id === curGroup ? "cur" : ""], role: "group", "aria-label": g.ko}, links)];
  });
  const scroller = nav.querySelector(".rail-in");
  const keep = scroller ? scroller.scrollTop : 0;
  nav.replaceChildren(h("div", {class: "rail-in"}, groups),
    h("div", {class: "rail-foot"}, textCycle(onRedraw), skinCycle(onRedraw),
      h("a", {class: "rail-old", href: "/v3", title: "지금까지 쓰던 대시보드 (/v3, 같은 로그인)", "aria-label": "예전 화면 (/v3)"}, "v3")));
  if (keep) nav.querySelector(".rail-in").scrollTop = keep;
  hideTip();
}

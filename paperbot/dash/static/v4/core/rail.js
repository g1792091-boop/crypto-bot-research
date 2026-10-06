// The left rail, a CHOICE since 10/06 13:27 ("메뉴 위치: 위 / 왼쪽", core/navpos.js; the default is the top bar,
// core/topnav.js). The owners found the first icon-only rail hard to use ("클릭하는 버튼들이 다 왼쪽으로 바꼈네??"),
// so the rail now reads by itself: every screen of the 5 groups as a row with its pixel icon AND its Korean name, the
// group names as headings, the current screen lit with the accent (a bar on its left), the number key in grey at the
// row's end, the small dot of a screen with news, 꺼짐 on a feature that is off. One click to any screen. At its foot:
// 메뉴 위치, 글자 크기, 화면 색 and 예전 화면 (they live at the end of the sub tabs in the top layout). Shown only on a
// window at least 1200 px wide with data-nav="left" (core/nav.css); below that the top bar is the menu in both
// layouts. Drawn by core/shell.js on every route / feature / badge change.
import {h, $} from "./dom.js";
import {GROUPS, SCREENS, href, screenIcon, keyOf, menuScreens} from "./routes.js";
import {features} from "./features.js";
import {textCycle} from "./textsize.js";
import {skinCycle} from "./skin.js";
import {navPosSwitch} from "./navpos.js";

/** The screens of a group the menu shows now (hidden ones out, PC-only / feature screens only while they run). */
export function visibleScreens(g) {
  return menuScreens(g, features);
}

/**
 * renderRail(current screen name, badges, onRedraw): draws #rail. onRedraw: after 글자 크기 / 화면 색 (the router draws
 * the screen again, so the charts measure their labels in the new size and colours).
 */
export function renderRail(cur, badges, onRedraw) {
  const nav = $("#rail");
  if (!nav) return;
  const curGroup = (SCREENS[cur] || SCREENS.home).group;
  const groups = GROUPS.map((g) => {
    const links = visibleScreens(g).map((n) => {
      const m = SCREENS[n], off = m.soft && !features[m.soft], k = keyOf(n);
      return h("a", {class: ["rail-a", off ? "off" : ""], href: href(n), "aria-current": n === cur ? "page" : null,
        "aria-label": `${m.ko}${off ? " (아직 켜지지 않음)" : ""}${badges[n] ? " · 새 소식" : ""}${k ? ` · 단축키 ${k}` : ""}`, dataset: {screen: n}},
      h("span", {class: "rail-ic", "aria-hidden": "true"}, screenIcon(n)),
      h("span", {class: "rail-t", "aria-hidden": "true"}, m.ko),
      off ? h("span", {class: "pp thin", "aria-hidden": "true"}, "꺼짐") : null,
      badges[n] ? h("i", {class: "ndot", "aria-hidden": "true"}) : null,
      k ? h("kbd", {class: "rail-k", "aria-hidden": "true"}, k) : null);
    });
    return h("div", {class: ["rail-g", g.id === curGroup ? "cur" : ""], role: "group", "aria-labelledby": `rh-${g.id}`, dataset: {group: g.id}},
      h("p", {class: "rail-h", id: `rh-${g.id}`}, g.ko), links);
  });
  const scroller = nav.querySelector(".rail-in");
  const keep = scroller ? scroller.scrollTop : 0;
  nav.replaceChildren(h("div", {class: "rail-in"}, groups),
    h("div", {class: "rail-foot"}, navPosSwitch(),
      h("div", {class: "rail-tools"}, textCycle(onRedraw), skinCycle(onRedraw),
        h("a", {class: "rail-old", href: "/v3", title: "지금까지 쓰던 대시보드 (/v3, 같은 로그인)", "aria-label": "예전 화면 (/v3)"}, "v3"))));
  if (keep) nav.querySelector(".rail-in").scrollTop = keep;
}

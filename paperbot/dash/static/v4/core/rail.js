// The left rail, a CHOICE ("메뉴 위치: 위 / 왼쪽", core/navpos.js; the default is the menu strip on top,
// core/strip.js). The owners found the first icon-only rail hard to use ("클릭하는 버튼들이 다 왼쪽으로 바꼈네??",
// "왼쪽에 그림으로 되어있는데 너무 헷갈려"), so the rail reads by itself and lists the very buttons of the strip
// (routes.js navGroups: the same order, captions and the one 도움말 button): each a row with its pixel icon AND its
// Korean name, the group captions as headings, the current screen lit with the accent (a bar on its left), the number
// key in grey at the row's end, the small dot of a screen with news, 꺼짐 on a feature that is off. One click to any
// screen. At its foot: 메뉴 위치, 설정 (the gear, core/settings.js), 글자 크기, 화면 색 and 예전 화면 (they sit in the top bar
// in the top layout, the gear too).
// Shown only on a window at least 1200 px wide with data-nav="left" (core/nav.css); below that the strip is the menu
// in both layouts. Drawn by core/shell.js on every route / feature / badge change.
import {h, $} from "./dom.js";
import {SCREENS, href, screenIcon, keyOf, menuScreens, navGroups} from "./routes.js";
import {features} from "./features.js";
import {textCycle} from "./textsize.js";
import {skinCycle} from "./skin.js";
import {navPosSwitch} from "./navpos.js";
import {settingsRail} from "./settings.js";

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
  const groups = navGroups(features).map((g) => {
    const links = g.items.map((it) => {
      const k = keyOf(it.to);
      const off = it.screens.every((n) => SCREENS[n].soft && !features[SCREENS[n].soft]);
      const news = it.screens.some((n) => badges[n]);
      return h("a", {class: ["rail-a", off ? "off" : ""], href: href(it.to), "aria-current": it.screens.includes(cur) ? "page" : null,
        "aria-label": `${it.ko}${off ? " (아직 켜지지 않음)" : ""}${news ? " · 새 소식" : ""}${k ? ` · 단축키 ${k}` : ""}`,
        title: it.screens.length > 1 ? it.screens.map((n) => SCREENS[n].ko).join(" · ") : null, dataset: {screen: it.to}},
      h("span", {class: "rail-ic", "aria-hidden": "true"}, screenIcon(it.to)),
      h("span", {class: "rail-t", "aria-hidden": "true"}, it.ko),
      off ? h("span", {class: "pp thin", "aria-hidden": "true"}, "꺼짐") : null,
      news ? h("i", {class: "ndot", "aria-hidden": "true"}) : null,
      k ? h("kbd", {class: "rail-k", "aria-hidden": "true"}, k) : null);
    });
    return h("div", {class: ["rail-g", g.group === curGroup ? "cur" : ""], role: "group", "aria-labelledby": `rh-${g.group}`, dataset: {group: g.group}},
      h("p", {class: "rail-h", id: `rh-${g.group}`}, g.ko), links);
  });
  const scroller = nav.querySelector(".rail-in");
  const keep = scroller ? scroller.scrollTop : 0;
  nav.replaceChildren(h("div", {class: "rail-in"}, groups),
    h("div", {class: "rail-foot"}, navPosSwitch(),
      h("div", {class: "rail-tools"}, settingsRail(), textCycle(onRedraw), skinCycle(onRedraw),
        h("a", {class: "rail-old", href: "/v3", title: "지금까지 쓰던 대시보드 (/v3, 같은 로그인)", "aria-label": "예전 화면 (/v3)"}, "v3"))));
  if (keep) nav.querySelector(".rail-in").scrollTop = keep;
}

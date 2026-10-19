// The 실거래 site's shell (static/live/index.html; the rule bot's is static/v4/core/shell.js): the top bar (the brand, the
// "묶음 › 화면" line, 글자 크기 · 화면 색, the link to the rule bot's dashboard, the speaker, the gear, the 실거래 chip), the
// menu strip under it (core/strip.js: every 실거래 tab its own text button, in the four groups of core/routes.js
// LIVE_GROUPS) and the phone's bottom bar of those four groups. No D+n chip, no health dot, no critical banner, no bell:
// those read the rule bot's run (its stream, its alerts); every 실거래 tab shows the live bots' own state itself.
import {h, put, $} from "../v4/core/dom.js";
import {bus} from "../v4/core/api.js";
import {GROUPS, SCREENS, href, icon, parseHash, landing, navLabel, modeTag, menuScreens, screenIcon} from "../v4/core/routes.js";
import {features} from "../v4/core/features.js";
import {remount} from "../v4/core/router.js";
import {renderStrip} from "../v4/core/strip.js";
import {textCycle, textSwitch} from "../v4/core/textsize.js";
import {skinSwitch, skinCycle} from "../v4/core/skin.js";
import {settingsTab, gearButton} from "../v4/core/settings.js";
import {soundButton, startSound} from "../v4/core/sound.js";
import {openFind} from "../v4/core/find.js";
import {PAPER_PORT, siteUrl} from "../v4/core/site.js";

/** The rule bot's (paper) dashboard on this same host: its own login, its own cookie. */
const paperLink = () => {
  const url = siteUrl(PAPER_PORT);
  return url ? h("a", {class: "oldui paperlink", href: url, title: "규칙봇(모의) 대시보드: 같은 서버의 8080 포트 · 로그인 따로"}, "규칙봇", h("span", {"aria-hidden": "true"}, " ↗")) : null;
};
/** 찾기 at the start of the phone's menu strip (the top bar has no room for it under 460 px). */
const findTab = () => h("button", {type: "button", class: "findsub", "aria-label": "찾기: 실거래 화면", onclick: () => openFind()},
  screenIcon("analysis"), "찾기");

function renderNav() {
  const p = parseHash(location.hash);
  const name = SCREENS[p.name] ? p.name : landing();
  const meta = SCREENS[name];
  const gid = meta.group;
  const brand = $(".brand");
  if (brand) {
    const to = landing();
    brand.setAttribute("href", href(to));
    brand.setAttribute("aria-label", `실거래 첫 화면 (${SCREENS[to].ko})`);
    brand.title = `첫 화면: ${SCREENS[to].ko}`;
  }
  const crumb = $("#crumb");
  if (crumb) put(crumb, h("span", {class: "crumb-g"}, navLabel(gid)), h("span", {class: "crumb-s", "aria-hidden": "true"}, "›"), h("b", null, meta.ko));
  const tag = $(".mocktag");
  if (tag) {
    const m = modeTag(name);
    tag.textContent = m.text; tag.title = m.title; tag.classList.toggle("real", m.real);
  }
  // the phone's bottom bar: the four groups (a tap opens the group's first tab)
  put($("#botbar"), GROUPS.map((g) => {
    const first = menuScreens(g, features)[0] || g.screens[0];
    return h("a", {href: href(first), "aria-current": g.id === gid ? "page" : null, dataset: {group: g.id}}, icon(g.id), h("span", null, g.ko));
  }));
  renderStrip(name, {}, {
    lead: [findTab(), textCycle(() => remount())],
    tools: [textSwitch(() => remount()), skinSwitch(() => remount()), paperLink(), settingsTab()],
  });
  const tt = $("#toptools");
  if (tt) put(tt, h("span", {class: "tt-full"}, textSwitch(() => remount()), skinSwitch(() => remount())),
    h("span", {class: "tt-mini"}, textCycle(() => remount()), skinCycle(() => remount())), paperLink(), gearButton());
}

export function startLiveShell() {
  renderNav();
  bus.on("route", renderNav);
  bus.on("features", renderNav);
  // the speaker (core/sound.js): the live bots' 진입 · 익절 · 손절 · 멈춤 and the market's 바탕음; off until the first tap
  const tag = $(".mocktag");
  if (tag) tag.before(soundButton());
  startSound();
}

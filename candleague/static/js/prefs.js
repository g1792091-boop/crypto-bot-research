// The viewer's own settings, per device (dom.js `local`, try/catch inside; a private window or blocked storage simply
// gets the defaults): 글자 크기 (보통 / 크게 / 아주 크게: tokens.css scales every --t-* size under <html data-text>),
// 메뉴 위치 (위 / 왼쪽: <html data-nav>; the left menu only from 1000 px, a phone keeps the top strip) and 화면 색
// (AI / 클래식: <html data-skin>). skin-boot.js applies all three before the first paint; these are the switches.
import {h, local} from "./dom.js";

export const TEXT_SIZES = [{id: "md", ko: "보통"}, {id: "lg", ko: "크게"}, {id: "xl", ko: "아주 크게"}];
export const NAV_POS = [{id: "top", ko: "위"}, {id: "left", ko: "왼쪽"}];
export const SKINS = [{id: "ai", ko: "AI"}, {id: "classic", ko: "클래식"}];

const valid = (list, id) => list.some((x) => x.id === id);
export const textNow = () => (valid(TEXT_SIZES, document.documentElement.dataset.text) ? document.documentElement.dataset.text : "md");
export const navNow = () => (valid(NAV_POS, document.documentElement.dataset.nav) ? document.documentElement.dataset.nav : "top");
export const skinNow = () => (valid(SKINS, document.documentElement.dataset.skin) ? document.documentElement.dataset.skin : "ai");

export function applyText(id) { document.documentElement.dataset.text = valid(TEXT_SIZES, id) ? id : "md"; }
export function applyNav(id) { document.documentElement.dataset.nav = valid(NAV_POS, id) ? id : "top"; }
export function applySkin(id) {
  const root = document.documentElement;
  root.dataset.skin = valid(SKINS, id) ? id : "ai";
  const meta = document.querySelector('meta[name="theme-color"]');
  const bg = getComputedStyle(root).getPropertyValue("--bg").trim();
  if (meta && bg) meta.setAttribute("content", bg);
}

const NOW = {text: textNow, nav: navNow, skin: skinNow};
/** Every copy of the switches on the page (the top bar's, the menu row's, the 설정 panel's) shows what is applied now. */
export function syncSwitches() {
  for (const g of document.querySelectorAll(".skinsw[data-pref]")) {
    const now = NOW[g.dataset.pref] ? NOW[g.dataset.pref]() : null;
    for (const b of g.querySelectorAll("button[data-id]")) b.setAttribute("aria-pressed", String(b.dataset.id === now));
  }
  for (const b of document.querySelectorAll("[data-pref-cycle]")) if (b.repaint) b.repaint();
}
/** A small "이름 [a][b][c]" switch (aria-pressed; base.css .skinsw look). onPick(id) after the change is applied. */
function switcher(label, title, list, now, key, apply, onPick, cls) {
  const btns = list.map((x) => h("button", {type: "button", "aria-pressed": String(x.id === now()), dataset: {id: x.id},
    onclick: () => {
      if (now() === x.id) return;
      local.set(key, x.id);
      apply(x.id);
      syncSwitches();
      if (onPick) onPick(x.id);
    }}, x.ko));
  return h("span", {class: ["skinsw", cls], role: "group", "aria-label": label, title, dataset: {pref: key}}, h("span", {class: "k"}, label), btns);
}
/** One small button that steps through a setting (the v4 "가 보통" and the half-moon skin button): cycler(...) */
export function cycler(key, list, now, apply, onPick, o) {
  const ko = (id) => (list.find((x) => x.id === id) || list[0]).ko;
  const b = h("button", {type: "button", class: o.cls, title: o.title, dataset: {prefCycle: key}, onclick: () => {
    const i = list.findIndex((x) => x.id === now());
    const next = list[(i + 1) % list.length].id;
    local.set(key, next);
    apply(next);
    syncSwitches();
    if (onPick) onPick(next);
  }}, o.kids || null);
  b.repaint = () => {
    const id = now();
    b.dataset.v = id;
    b.setAttribute("aria-label", `${o.label}: ${ko(id)} (누르면 바뀝니다)`);
    if (o.paint) o.paint(b, id, ko(id));
  };
  b.repaint();
  return b;
}

export const textSwitch = (onPick) => switcher("글자 크기", "글자 크기: 이 기기에만 기억합니다", TEXT_SIZES, textNow, "text", applyText, onPick, "textsw");
export const navSwitch = (onPick) => switcher("메뉴 위치", "메뉴 위치: 이 기기에만 기억합니다 (휴대폰에서는 늘 위)", NAV_POS, navNow, "nav", applyNav, onPick, "navsw");
export const skinSwitch = (onPick) => switcher("화면 색", "화면 색: 이 기기에만 기억합니다", SKINS, skinNow, "skin", applySkin, onPick, "skinpick");
/** "가 보통": 보통 → 크게 → 아주 크게 → 보통 (v4 textCycle). */
export const textCycle = (onPick, cls) => cycler("text", TEXT_SIZES, textNow, applyText, onPick, {cls: ["textcyc", cls], label: "글자 크기",
  title: "글자 크기: 이 기기에만 기억합니다", kids: [h("span", {"aria-hidden": "true"}, "가"), h("small", {"aria-hidden": "true"})],
  paint: (b, id, ko) => { b.lastChild.textContent = ko; }});
/** The half-moon 화면 색 button: AI ↔ 클래식 (v4 skinCycle). */
export const skinCycle = (onPick, cls) => cycler("skin", SKINS, skinNow, applySkin, onPick, {cls: ["skincyc", cls], label: "화면 색",
  title: "화면 색: 이 기기에만 기억합니다", kids: [h("i", {"aria-hidden": "true"})]});

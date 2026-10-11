// 설정 한 곳 (the rule bot's core/settings.js, the parts the 후보 리그 has): ONE panel for every per-device choice — 화면 색,
// 글자 크기, 메뉴 위치, 첫 화면, 숫자 움직임 줄이기, 설치 뒤 진입만 (js/after.js; the same switch the list screens show) —
// plus 바로가기 and the keys. Opened by the gear (the top bar's on a PC
// with the menu on top, the menu row's end below 1200 px) and the key ",". Every row applies at once and writes the
// same storage key as the switch it mirrors (prefs.js; per device, dom.js `local`, try/catch inside). A phone gets a
// sheet from the bottom, a PC a panel on the right. Look: kit.css (.set-*, copied from core/settings.css).
import {h, s, local} from "./dom.js";
import {SKINS, TEXT_SIZES, NAV_POS, MOTIONS, skinNow, textNow, navNow, motionNow, applySkin, applyText, applyNav, applyMotion,
  syncSwitches, startPref} from "./prefs.js";
import * as fmt from "./fmt.js";
import {installMs, afterWanted, setAfter} from "./after.js";

const R = (x, y, w, hh) => s("rect", {x, y, width: w, height: hh});
/** The pixel gear (16 x 16, currentColor). */
export const gearIcon = () => s("svg", {viewBox: "0 0 16 16", width: "16", height: "16", fill: "currentColor", "shape-rendering": "crispEdges",
  "aria-hidden": "true"}, R(7, 0, 2, 3), R(7, 13, 2, 3), R(0, 7, 3, 2), R(13, 7, 3, 2), R(2, 2, 2, 2), R(12, 2, 2, 2), R(2, 12, 2, 2),
R(12, 12, 2, 2), R(4, 3, 8, 2), R(4, 11, 8, 2), R(3, 4, 2, 8), R(11, 4, 2, 8));

const st = {open: false, el: null, scrim: null, back: null, hooks: {}};
export const settingsOpen = () => st.open;
/** app.js: {screens: [{id, ko}], autoStart: () => id, remount: () => void, onNav: () => void}. */
export function setSettingsHooks(o) { st.hooks = o || {}; }

const gear = (cls, text) => h("button", {type: "button", class: ["tb-btn", cls], title: "설정 (단축키 ,)", "aria-label": "설정",
  "aria-haspopup": "dialog", "aria-keyshortcuts": ",", onclick: () => openSettings()}, gearIcon(), text ? h("span", {class: `${cls}-t`}, text) : null);
/** The top bar's gear (a PC with the menu on top) and the one at the menu row's end (below 1200 px). */
export const gearButton = () => gear("setbtn", "설정");
export const settingsTab = () => gear("setsub", "설정");

function choice(label, options, cur, fn) {
  const btns = options.map((x) => h("button", {type: "button", "aria-pressed": String(x.id === cur), dataset: {id: x.id},
    onclick: () => { for (const b of btns) b.setAttribute("aria-pressed", String(b.dataset.id === x.id)); fn(x.id); }}, x.ko));
  return h("div", {class: "seg set-seg", role: "group", "aria-label": label}, btns);
}
function row(name, sub, control, o = {}) {
  return h("div", {class: ["set-row", o.wide ? "wide" : "", o.dim ? "dim" : ""]},
    h("div", {class: "set-l"}, h("b", null, name), sub ? h("small", null, sub) : null), h("div", {class: "set-c"}, control));
}
function section(id, title, sub, ...rows) {
  return h("section", {class: "set-sec", "aria-labelledby": `set-s-${id}`},
    h("h3", {class: "set-sh", id: `set-s-${id}`}, title, sub ? h("small", null, sub) : null), rows);
}

function body() {
  const k = st.hooks;
  const again = () => { syncSwitches(); if (k.remount) k.remount(); };
  const skinRow = row("화면 색", "AI = 검은 바탕 · 청록 빛 / 클래식 = 남색 · 노랑", choice("화면 색", SKINS, skinNow(), (id) => {
    if (skinNow() === id) return;
    local.set("skin", id); applySkin(id); again();
  }));
  const textRow = row("글자 크기", "화면 전체의 글자가 함께 커집니다", choice("글자 크기", TEXT_SIZES, textNow(), (id) => {
    if (textNow() === id) return;
    local.set("text", id); applyText(id); again();
  }));
  const wide = typeof matchMedia === "function" && matchMedia("(min-width: 1000px)").matches;
  const navRow = row("메뉴 위치", wide ? "위 = 화면 버튼이 맨 위 한 줄 · 왼쪽 = 세로 목록" : "PC 창(1000 px 이상)에서만 달라집니다 · 지금 창에서는 위 줄",
    choice("메뉴 위치", NAV_POS, navNow(), (id) => {
      if (navNow() === id) return;
      local.set("nav", id); applyNav(id); syncSwitches(); if (k.onNav) k.onNav();
    }), {dim: !wide});
  const auto = k.autoStart ? k.autoStart() : "home";
  const nameOf = (id) => ((k.screens || []).find((x) => x.id === id) || {ko: id}).ko;
  const sel = h("select", {class: "select set-sel", "aria-label": "첫 화면", onchange: () => { local.set("start", sel.value); }},
    h("option", {value: ""}, `자동 (지금: ${nameOf(auto)})`), (k.screens || []).map((x) => h("option", {value: x.id}, x.ko)));
  sel.value = (k.screens || []).some((x) => x.id === startPref()) ? startPref() : "";
  const startRow = row("첫 화면", "주소만 열었을 때 처음 보이는 화면 · 자동 = 넓은 창은 터미널, 휴대폰은 요약", sel);
  const motionRow = row("숫자 움직임", "줄이기 = 숫자가 굴러가거나 반짝이지 않고 바로 바뀝니다 (기기 설정의 '동작 줄이기'도 같은 효과)",
    choice("숫자 움직임", MOTIONS, motionNow(), (id) => { local.set("motion", id); applyMotion(id); }));
  // 설치 뒤 진입만: only once the snapshot carries the install time (a change remounts the screen: app.js onAfterChange)
  const ims = installMs();
  const afterRow = ims == null ? null : row("설치 뒤 진입만",
    `보기만 바뀝니다: 켜면 요약·포지션·터미널·체결 기록·순위표·계좌·진입 차트의 열린 포지션과 체결 목록에 설치(${fmt.kst(ims)}) 뒤에 들어간 것만 보입니다 · 순위·잔고·점검은 10/01부터 전체 기록`,
    choice("설치 뒤 진입만", [{id: "off", ko: "끔"}, {id: "on", ko: "켬"}], afterWanted() ? "on" : "off", (id) => setAfter(id === "on")));
  const links = h("div", {class: "set-links"}, [["#/check", "점검 진행"], ["#/positions", "포지션"], ["#/status", "서버 상태"], ["#/howto", "읽는 법"]]
    .map(([href, ko]) => h("a", {class: "btn-line", href, onclick: () => closeSettings(true)}, ko)));
  const keys = h("p", {class: "set-keys"}, h("kbd", null, "/"), " 찾기 · ", h("kbd", null, ","), " 설정 · ", h("kbd", null, "Esc"), " 닫기");
  return [section("screen", "화면", "이 기기에만 기억합니다 (다른 기기·다른 분 화면은 그대로)", skinRow, textRow, navRow, startRow, motionRow, afterRow),
    section("go", "바로가기", null, links, keys),
    h("p", {class: "set-foot"}, "후보 리그는 모의 계좌입니다: 주문을 넣지 않고, 바이낸스 공개 시세로 계산합니다.")];
}

export function openSettings() {
  if (st.open) return;
  st.open = true;
  st.back = document.activeElement;
  const x = h("button", {type: "button", class: "set-x", "aria-label": "설정 닫기 (Esc)", onclick: () => closeSettings()}, "✕");
  st.el = h("div", {class: "set", role: "dialog", "aria-modal": "true", "aria-labelledby": "set-title", tabindex: "-1"},
    h("div", {class: "set-h"}, h("span", {class: "set-plate"}, "SETTINGS"), h("h2", {id: "set-title"}, "설정"),
      h("span", {class: "set-sub"}, "글자 크기 · 화면 색 · 메뉴 위치 · 첫 화면"), x),
    h("div", {class: "set-b"}, body()));
  st.scrim = h("div", {class: "set-scrim", onclick: () => closeSettings()});
  document.body.append(st.scrim, st.el);
  document.documentElement.classList.add("set-open");
  requestAnimationFrame(() => { if (st.el) { st.el.classList.add("in"); st.scrim.classList.add("in"); } });
  st.el.focus({preventScroll: true});
}
export function closeSettings(keepFocus) {
  if (!st.open) return;
  st.open = false;
  const el = st.el, sc = st.scrim;
  st.el = st.scrim = null;
  document.documentElement.classList.remove("set-open");
  if (el) el.remove();
  if (sc) sc.remove();
  if (!keepFocus && st.back && st.back.isConnected && st.back.focus) st.back.focus({preventScroll: true});
  st.back = null;
}

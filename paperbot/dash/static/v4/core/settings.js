// 설정 한 곳 (owners 10/06: "클릭이 너무 많다"): ONE panel for every per-device choice that used to be spread over the
// header (화면 색 · 글자 크기 · 메뉴 위치 · the speaker menu), the chart headers (조명 · 번쩍임 · '선' menu · 진입·청산 / 가격
// 알림 선 / GH Coin toggles), the phone swipe and the start screen. Opened by ONE gear per layout: in the top bar's
// #toptools on a PC with the menu on top, in the left rail's tools with the menu on the left, at the end of the menu
// strip below 1200 px (core/shell.js, core/rail.js); also by the key "," and the speaker menu's last line. Every row
// applies at once and writes the SAME storage key as the control it mirrors (nothing migrated, the old controls keep
// working):
//   skin "skin" (core/skin.js) · text "text" (core/textsize.js) · nav "nav" (core/navpos.js 메뉴 위치: the top bar's and
//   the rail's switch follow through the bus event "navpos", and this panel follows them) · start "start" + swipe
//   "swipe" (core/prefs.js, new)
//   chart-light (core/blink.js 차트 조명 깜박 / 계속 / 끄기) · chart-flash (core/flash.js / chartfx.js) · cfx-term /
//   cfx-chart / cfx-grid (the decks' '선' choices) · chart-show (the 차트 screen's three toggles) · charts-grid layout
//   (여러 차트, screens/charts.js)
//   sound "sound" {on, vol, density, night} · snd-kind · snd-wake · snd-hours (new) · snd-ev (new) (core/sound.js)
// A chart already on screen follows through core/prefs.js (setPref: 조명, 번쩍임, '선'); a skin or text size draws the screen again
// (router.remount) like the old switches. Per device only: local storage through dom.js `local` (try/catch inside).
// Look: core/settings.css (index.html). Phone: a sheet from the bottom; PC: a panel on the right in the terminal style.
import {h, s, put, local} from "./dom.js";
import {bus} from "./api.js";
import {features} from "./features.js";
import {SKINS, applySkin} from "./skin.js";
import {TEXT_SIZES, applyText} from "./textsize.js";
import {FLASH_MODES, modeOf} from "./flash.js";
import {LIGHT_MODES, lightModeOf} from "./blink.js";
import {NAV_POS, navPosNow, setNavPos} from "./navpos.js";
import {GROUP_KO, deckState, deckValue, FLASH_KEY, LIGHT_KEY} from "./chartfx.js";
import * as sound from "./sound.js";
import {tvSection} from "./tvmode.js";
import {GROUPS, SCREENS, mainLanding} from "./routes.js";
import {START_KEY, SWIPE_KEY, GRID_KEY, GRID_DECK, setPref, onPref, swipeOn} from "./prefs.js";
import {remount} from "./router.js";
import {reduced} from "./motion.js";
import {openAway} from "./since.js";
import {startTour} from "./tour.js";
import {toast} from "./ui.js";
import {leave as leaveFull} from "./fullchart.js";

// the chart decks the panel lists: [deck key, 이름, its '선' groups, the screen's own first choice (null: the deck's rule)]
export const DECKS = [
  ["term", "터미널 차트", ["pos", "risk", "sr", "smc", "ev", "vol"], null],
  ["chart", "차트 화면", ["pos", "risk", "sr", "smc", "ev", "vol"], null],
  [GRID_DECK.key, "여러 차트", GRID_DECK.groups, GRID_DECK.defaults],
];
// the 차트 screen's own toggles (screens/chart.js TOGGLES, "chart-show"): [key, label, default]
export const CHART_SHOW = [["mk", "진입·청산", true], ["al", "가격 알림 선", true], ["gh", "GH Coin 타점", false]];
const FLASH_SUB = {often: "큰 체결마다", normal: "고래·큰 청산·우리 체결만", off: "번쩍임 없음 (은은한 빛은 그대로)"};
const LIGHT_SUB = {blink: "실제 체결을 따라 깜박", steady: "예전처럼 은은하게 계속", off: "빛 없음 (번쩍임은 그대로)"};
const GRID_LAYOUTS = [{id: "2x2", ko: "2×2 (4개)"}, {id: "3x3", ko: "3×3 (9개)"}];

// 16 x 16 pixel icons (fill = currentColor)
const R = (x, y, w, hh) => s("rect", {x, y, width: w, height: hh});
const svg16 = (rects) => s("svg", {viewBox: "0 0 16 16", width: "16", height: "16", fill: "currentColor", "shape-rendering": "crispEdges", "aria-hidden": "true"}, rects);
export const gearIcon = () => svg16([R(7, 0, 2, 3), R(7, 13, 2, 3), R(0, 7, 3, 2), R(13, 7, 3, 2), R(2, 2, 2, 2), R(12, 2, 2, 2), R(2, 12, 2, 2),
  R(12, 12, 2, 2), R(4, 3, 8, 2), R(4, 11, 8, 2), R(3, 4, 2, 8), R(11, 4, 2, 8)]);

const st = {open: false, el: null, scrim: null, back: null, section: null, offs: []};
export const settingsOpen = () => st.open;

// ---------------------------------------------------------------- the open buttons
// One gear per layout (never two at once, never an id twice): the three are drawn by core/shell.js / core/rail.js on
// every route, and the CSS shows the one that belongs to the layout (core/nav.css: the top bar's #toptools only on a PC
// with the menu on top, the strip's end only below 1200 px, the rail only with the menu on the left). A real <button>
// (Tab reaches it, Enter / Space open the panel), the tooltip "설정", the key "," named for screen readers.
const gear = (cls, text) => h("button", {type: "button", class: cls, title: "설정", "aria-label": "설정", "aria-haspopup": "dialog", "aria-keyshortcuts": ",",
  onclick: () => openSettings()}, gearIcon(), text ? h("span", {class: cls + "-t"}, text) : null);
/** The top bar's gear (#toptools, a PC window with the menu on top: 1200 px and up). */
export const gearButton = () => gear("setbtn", "설정");
/** The gear at the end of the menu strip below 1200 px (core/shell.js). */
export const settingsTab = () => gear("setsub", "설정");
/** The left rail's tools (core/rail.js): a small round gear before 글자 크기 / 화면 색. */
export const settingsRail = () => gear("setcyc");

// ---------------------------------------------------------------- small controls
/** A two-state switch (role="switch"); fn(on) after a change. */
function toggle(label, on, fn, o = {}) {
  const b = h("button", {type: "button", class: "set-sw", role: "switch", "aria-checked": String(!!on), "aria-label": label, disabled: o.disabled || null,
    onclick: () => { const v = b.getAttribute("aria-checked") !== "true"; b.setAttribute("aria-checked", String(v)); fn(v); }},
  h("i", {"aria-hidden": "true"}));
  return b;
}
/** A row of choices (aria-pressed buttons, the speaker menu's look); fn(id). */
function choice(label, options, cur, fn) {
  const btns = options.map((x) => h("button", {type: "button", "aria-pressed": String(x.id === cur), dataset: {id: x.id}, title: x.title || null,
    onclick: () => { for (const b of btns) b.setAttribute("aria-pressed", String(b.dataset.id === x.id)); fn(x.id); }}, x.ko));
  return h("div", {class: "seg set-seg", role: "group", "aria-label": label}, btns);
}
/** One row: the name with a short plain line under it, the control at the right (stacked when `wide`). */
function row(name, sub, control, o = {}) {
  return h("div", {class: ["set-row", o.wide ? "wide" : "", o.dim ? "dim" : ""], dataset: o.id ? {set: o.id} : null},
    h("div", {class: "set-l"}, h("b", null, name), sub ? h("small", null, sub) : null), h("div", {class: "set-c"}, control));
}
function section(id, title, sub, ...rows) {
  return h("section", {class: "set-sec", dataset: {sec: id}, "aria-labelledby": `set-s-${id}`},
    h("h3", {class: "set-sh", id: `set-s-${id}`}, title, sub ? h("small", null, sub) : null), rows);
}

// ---------------------------------------------------------------- the sections
/** The automatic start screen of this window's size: the very rule routes.js landing() uses without a choice (the 터미널
 *  on a PC window, else the 차트 screen). */
const autoStart = () => SCREENS[mainLanding()].ko;
/** 메뉴 위치 only changes anything on a PC window (the left rail is a 1200 px and up layout, core/nav.css). */
const navWide = () => typeof matchMedia === "function" && matchMedia("(min-width: 1200px)").matches;
function screenSection() {
  const skinNow = document.documentElement.dataset.skin || "ai";
  const textNow = document.documentElement.dataset.text || "md";
  const skinRow = row("화면 색", "AI = 검은 바탕 · 청록 빛 / 클래식 = 남색 · 노랑", choice("화면 색", SKINS, skinNow, (id) => {
    if (document.documentElement.dataset.skin === id) return;
    local.set("skin", id); applySkin(id); remount(); repaint();
  }));
  const textRow = row("글자 크기", "화면 전체의 글자가 함께 커집니다", choice("글자 크기", TEXT_SIZES, textNow, (id) => {
    if (document.documentElement.dataset.text === id) return;
    local.set("text", id); applyText(id); remount(); repaint();
  }));
  // 메뉴 위치 (core/navpos.js): the same control as the top bar's and the rail's; setNavPos stores it and emits "navpos"
  // (the shell draws the menu and the screen again; this panel repaints from the same event, see openSettings)
  const wide = navWide();
  const navRow = row("메뉴 위치", wide ? "위 = 모든 화면이 글자 버튼 한 줄 · 왼쪽 = 그림과 이름이 세로로" : "위 · 왼쪽은 PC 창(1200 px 이상)에서만 달라집니다 · 지금 창에서는 위 줄",
    choice("메뉴 위치", NAV_POS, navPosNow(), (id) => setNavPos(id)), {dim: !wide});
  // 첫 화면: an empty address opens it (the brand mark too); a PC-only screen falls back on a phone
  const cur = local.get(START_KEY, "");
  const sel = h("select", {class: "select set-sel", "aria-label": "첫 화면",
    onchange: () => { setPref(START_KEY, sel.value); repaint(); }},
  h("option", {value: ""}, `자동 (지금: ${autoStart()})`),
  GROUPS.map((g) => h("optgroup", {label: g.ko}, g.screens.filter((n) => SCREENS[n] && !SCREENS[n].hidden).map((n) =>
    h("option", {value: n}, SCREENS[n].ko + (SCREENS[n].feature === "wide" ? " (PC 화면)" : ""))))));
  sel.value = typeof cur === "string" && SCREENS[cur] && !SCREENS[cur].hidden ? cur : "";
  const startRow = row("첫 화면", "주소만 열었을 때 처음 보이는 화면 · 자동 = 창 크기대로 · 'PC 화면'은 휴대폰에서 자동대로", sel);
  const swipeRow = row("휴대폰 옆으로 밀기", "화면을 옆으로 밀면 같은 묶음의 다음·이전 화면으로 (차트·표 위는 제외)",
    toggle("휴대폰 옆으로 밀기", swipeOn(), (on) => setPref(SWIPE_KEY, on)));
  return section("screen", "화면", null, skinRow, textRow, navRow, startRow, swipeRow);
}

function chartSection() {
  const ai = (document.documentElement.dataset.skin || "ai") !== "classic";
  const fNow = modeOf(local.get(FLASH_KEY, null)).id;
  const lNow = lightModeOf(local.get(LIGHT_KEY, null)).id;
  // 차트 조명 (core/blink.js, "chart-light"): the Premium / Discount light behind the candles; a chart on screen follows
  // at once (core/chartfx.js onPref) and its own 조명 menu shows the new mode
  const lightRow = row("차트 조명", ai ? "차트 뒤의 위 빨강 · 아래 하늘색 빛 · 깜박 = 실제 체결을 따라 (체결이 없으면 은은한 장식)" : "AI 화면 색에서만 빛납니다 (지금은 클래식)",
    choice("차트 조명", LIGHT_MODES.map((m) => ({id: m.id, ko: m.ko, title: LIGHT_SUB[m.id]})), lNow, (id) => setPref(LIGHT_KEY, id)), {dim: !ai, id: "light"});
  const flashRow = row("번쩍임", ai ? "큰 체결·청산·우리 체결 때 차트가 한 번 빛남 (실제 일만)" : "AI 화면 색에서만 빛납니다 (지금은 클래식)",
    choice("번쩍임", FLASH_MODES.map((m) => ({id: m.id, ko: m.ko, title: FLASH_SUB[m.id]})), fNow, (id) => setPref(FLASH_KEY, id)), {dim: !ai, id: "flash"});
  const decks = DECKS.map(([key, ko, groups, defaults]) => {
    const now = deckState(key, groups, defaults);
    const save = () => setPref("cfx-" + key, deckValue(now));
    const chips = groups.map((g) => h("button", {type: "button", class: "set-chip", "aria-pressed": String(!now.off.has(g)),
      onclick: (e) => { const on = now.off.has(g); if (on) now.off.delete(g); else now.off.add(g); e.currentTarget.setAttribute("aria-pressed", String(on)); save(); }},
    GROUP_KO[g] || g));
    if (key === "chart") {
      const show = local.get("chart-show", {}) || {};
      for (const [k, label, d] of CHART_SHOW) {
        if (k === "gh" && !features.ghcoin) continue;
        const on = typeof show[k] === "boolean" ? show[k] : d;
        chips.push(h("button", {type: "button", class: "set-chip", "aria-pressed": String(on),
          onclick: (e) => {
            const v = local.get("chart-show", {}) || {};
            const was = typeof v[k] === "boolean" ? v[k] : d;
            const next = {};
            for (const [k2, , d2] of CHART_SHOW) next[k2] = typeof v[k2] === "boolean" ? v[k2] : d2;
            next[k] = !was;
            e.currentTarget.setAttribute("aria-pressed", String(!was));
            setPref("chart-show", next);
          }}, label));
      }
    }
    const back = now.hide.size ? h("button", {type: "button", class: "btn-line set-back",
      onclick: (e) => { now.hide.clear(); save(); e.currentTarget.remove(); }}, `숨긴 선 ${now.hide.size}개 다시 보기`) : null;
    return row(ko, null, h("div", {class: "set-chips", role: "group", "aria-label": `${ko}에 보일 선`}, chips, back), {wide: true});
  });
  const g = local.get(GRID_KEY, null);
  const lay = g && g.layout === "3x3" ? "3x3" : "2x2";
  const gridRow = row("여러 차트 칸 수", "한 화면에 같이 볼 차트 수 (휴대폰은 한 줄씩)", choice("여러 차트 칸 수", GRID_LAYOUTS, lay, (id) => {
    const v = local.get(GRID_KEY, null);
    setPref(GRID_KEY, {...(v && typeof v === "object" ? v : {}), layout: id});
  }));
  return section("chart", "차트", "선 이름표를 눌러 숨긴 선은 '다시 보기'로 돌아옵니다", lightRow, flashRow,
    h("p", {class: "set-note"}, "차트에 보일 선 (켜진 것만 보입니다)"), decks, gridRow);
}

function soundSection() {
  const c = sound.cfg;
  const onRow = row("실시간 소리", c.on ? (sound.waiting() ? "켜짐 · 화면을 한 번 누르면 들립니다" : "켜짐 · 실제로 일이 생길 때만 소리") : "꺼짐",
    toggle("실시간 소리", c.on, (on) => { if (on) sound.startOnTap(); else sound.setCfg({on: false}); }));
  const kind = row("소리 종류", "영상 기계음 = 라이브 영상의 기계 소리 / 칩튠 = 이전 소리",
    choice("소리 종류", Object.entries(sound.ENGINES).map(([id, ko]) => ({id, ko})), sound.soundKind(), (id) => sound.setKind(id)));
  const volOut = h("output", {class: "set-vol num"}, `${c.vol}`);
  const vol = h("input", {type: "range", min: "0", max: "100", step: "5", value: String(c.vol), "aria-label": "소리 크기",
    oninput: () => { volOut.textContent = vol.value; sound.setCfg({vol: Number(vol.value)}); }});
  const volRow = row("크기", null, h("div", {class: "set-range"}, vol, volOut));
  const dens = row("빈도", "바탕음이 얼마나 자주 나는지", choice("소리 빈도", Object.entries(sound.DENSITY).map(([id, d]) => ({id, ko: d.ko})), c.density,
    (id) => sound.setCfg({density: id})));
  const hourSel = (which) => {
    const sel = h("select", {class: "select set-hour", "aria-label": which === "from" ? "밤 시작 시각" : "밤 끝 시각",
      onchange: () => { sound.setHours({[which]: Number(sel.value)}); paintNight(); }},
    Array.from({length: 24}, (_, i) => h("option", {value: String(i)}, `${String(i).padStart(2, "0")}시`)));
    sel.value = String(sound.hours[which]);
    return sel;
  };
  const nightNote = h("small", {class: "set-nightnote"});
  const paintNight = () => {
    const H = sound.hours;
    nightNote.textContent = H.from === H.to ? "시작과 끝이 같으면 밤 끄기가 없습니다" : `한국 시각 ${sound.hoursKo()} 동안 조용히 (${H.from > H.to ? "자정을 넘김" : "같은 날"})`;
  };
  paintNight();
  const night = row("밤에 끄기", "정한 시간에는 소리 없이 (켜 둔 경우만)", h("div", {class: "set-night"},
    toggle("밤에 끄기", c.night, (on) => sound.setCfg({night: on})), hourSel("from"), h("span", {"aria-hidden": "true"}, "~"), hourSel("to"), nightNote), {wide: true});
  const wake = row("화면 켜두기", sound.wakeSupported() ? "소리가 켜져 있는 동안 휴대폰 화면이 잠들지 않게" : "이 기기는 지원하지 않습니다",
    toggle("화면 켜두기", sound.wakeOn(), (on) => sound.setWake(on), {disabled: !sound.wakeSupported()}));
  const evRows = sound.EVENTS.map(([id, ko, why]) => row(ko, why, h("div", {class: "set-ev"},
    h("button", {type: "button", class: "btn-line set-try", "aria-label": `${ko} 소리 들어보기`,
      onclick: () => { if (!sound.preview(id)) toast("이 브라우저는 소리를 낼 수 없습니다"); }}, "들어보기"),
    toggle(`${ko} 소리`, sound.evOn(id), (on) => sound.setEv(id, on))), {id: "ev-" + id}));
  return section("sound", "소리", "소리는 실제 기록이 생길 때만 납니다 · '들어보기'는 누를 때 한 번", onRow, kind, volRow, dens, night, wake,
    h("p", {class: "set-note"}, "소리별 켜기·끄기"), evRows);
}

/** TV 자동 넘김 (conv-b, core/tvmode.js): its own controls (how long a screen stays, which screens, 시작 / 끝내기) inside
 *  the panel; 시작 closes the panel. It only changes which real screen is shown. */
const tvPanelSection = () => section("tv", "TV 자동 넘김", "사무실 TV에 켜 두면 고른 화면이 차례로 넘어갑니다 (t 키로도 켜고 끕니다)",
  h("div", {class: "set-tv"}, tvSection(() => closeSettings())));

function goSection() {
  return section("go", "바로가기", null,
    h("div", {class: "set-links"},
      h("button", {type: "button", class: "btn-line", onclick: () => { closeSettings(); openAway(); }}, "자는 동안 요약 보기"),
      h("a", {class: "btn-line", href: "#/charts", onclick: () => closeSettings()}, "여러 차트 한 번에"),
      h("button", {type: "button", class: "btn-line", onclick: () => { closeSettings(); startTour(); }}, "안내 다시 보기"),
      h("a", {class: "btn-line", href: "/v3", title: "지금까지 쓰던 대시보드 (/v3, 같은 로그인)"}, "예전 화면 ↗")),
    h("p", {class: "set-keys"}, h("kbd", null, "/"), " 찾기 · ", h("kbd", null, ","), " 설정 · ", h("kbd", null, "f"), " 차트 크게 (차트 위에서) · ",
      h("kbd", null, "t"), " TV 자동 넘김 · ", h("kbd", null, "Esc"), " 닫기 · ", h("kbd", null, "1"), "~", h("kbd", null, "9"), " 화면 이동"));
}

// ---------------------------------------------------------------- the panel
function body() {
  return [screenSection(), chartSection(), soundSection(), tvPanelSection(), goSection(),
    h("p", {class: "set-foot"}, "이 설정은 이 기기(이 브라우저)에만 기억됩니다. 다른 휴대폰·PC는 각자 따로입니다.")];
}
function repaint() {
  if (!st.open || !st.el) return;
  const b = st.el.querySelector(".set-b");
  const top = b.scrollTop;
  const focusKey = document.activeElement && st.el.contains(document.activeElement) ? keyOf(document.activeElement) : null;
  put(b, body());
  b.scrollTop = top;
  if (focusKey) { const f = findKey(b, focusKey); if (f) f.focus({preventScroll: true}); }
}
// keep the keyboard focus on "the same" control after a repaint: its row and its text / label
const keyOf = (el) => { const r = el.closest(".set-row, .set-sec"); return r ? [r.querySelector("b, h3") ? r.querySelector("b, h3").textContent : "", el.getAttribute("aria-label") || el.textContent] : null; };
function findKey(root, [rowT, t]) {
  for (const r of root.querySelectorAll(".set-row, .set-sec")) {
    const head = r.querySelector("b, h3");
    if (!head || head.textContent !== rowT) continue;
    for (const el of r.querySelectorAll("button, select, input, a")) if ((el.getAttribute("aria-label") || el.textContent) === t) return el;
  }
  return null;
}

/** Open the panel (section: "screen" | "chart" | "sound" | "tv" | "go" scrolls to it). */
export function openSettings(sectionId) {
  if (st.open) { if (sectionId) scrollTo(sectionId); return; }
  leaveFull();                // a chart in the browser's full screen would hide the panel: it goes back first
  st.open = true;
  st.back = document.activeElement;
  const phone = typeof matchMedia === "function" && !matchMedia("(min-width: 760px)").matches;
  const x = h("button", {class: "set-x", type: "button", "aria-label": "설정 닫기", onclick: () => closeSettings()}, "✕");
  st.scrim = h("div", {class: "set-scrim", onclick: () => closeSettings()});
  st.el = h("section", {class: "set bsheet", role: "dialog", "aria-modal": "true", "aria-labelledby": "set-title", tabindex: "-1"},
    h("div", {class: "set-h"},
      h("span", {class: "set-plate"}, "설정"),
      h("h2", {id: "set-title"}, "이 기기 설정"),
      h("span", {class: "set-sub"}, "바꾸면 바로 적용 · 이 기기에만 기억"),
      x),
    h("div", {class: "set-b"}, body()));
  document.body.append(st.scrim, st.el);
  document.documentElement.classList.add("set-open");
  document.addEventListener("keydown", onKey, true);
  window.addEventListener("hashchange", onRoute);
  // the rows that mirror a control elsewhere follow it while the panel is open: 메뉴 위치 changed in the top bar or the
  // rail (bus "navpos"), 차트 조명 / 번쩍임 changed in a chart's own 조명 menu
  st.offs = [bus.on("navpos", () => repaint()), onPref(LIGHT_KEY, () => repaint()), onPref(FLASH_KEY, () => repaint())];
  requestAnimationFrame(() => requestAnimationFrame(() => {
    if (!st.el) return;
    st.el.classList.add("in"); st.scrim.classList.add("in");
    if (sectionId) scrollTo(sectionId);
    (phone ? x : st.el.querySelector(".set-b button, .set-b select") || x).focus({preventScroll: true});
  }));
}
function scrollTo(id) {
  const sec = st.el && st.el.querySelector(`[data-sec="${id}"]`);
  if (sec) sec.scrollIntoView({block: "start", behavior: reduced() ? "auto" : "smooth"});
}
export function closeSettings() {
  if (!st.open) return;
  st.open = false;
  const el = st.el, scrim = st.scrim;
  st.el = null; st.scrim = null;
  document.removeEventListener("keydown", onKey, true);
  window.removeEventListener("hashchange", onRoute);
  for (const off of st.offs) off();
  st.offs = [];
  document.documentElement.classList.remove("set-open");
  const gone = () => { el.remove(); scrim.remove(); };
  if (reduced()) gone(); else { el.classList.remove("in"); scrim.classList.remove("in"); setTimeout(gone, 260); }
  const back = st.back;
  st.back = null;
  if (back && back.focus && document.contains(back)) back.focus({preventScroll: true});
}
function onKey(e) {
  if (!st.open) return;
  if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeSettings(); return; }
  if (e.key !== "Tab") return;
  // the focus stays inside the panel (a dialog)
  const f = [...st.el.querySelectorAll("button:not([disabled]), select, input, a[href]")].filter((x) => x.offsetParent !== null);
  if (!f.length) return;
  const first = f[0], last = f[f.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
}
const onRoute = () => closeSettings();

let started = false;
/** Boot (core/main.js): the speaker menu's link, a sound change elsewhere repaints the panel. (The gears themselves are
 *  drawn with the menu by core/shell.js and core/rail.js: one per layout.) */
export function startSettings() {
  if (started) return;
  started = true;
  bus.on("settings:open", (sec) => openSettings(typeof sec === "string" ? sec : undefined));
  bus.on("sound:cfg", () => { if (st.open) repaintSound(); });
}
/** A sound change from the speaker menu (or the panel itself): the sound rows only, so a slider being dragged keeps
 *  its place (the volume row is left alone while it has the focus). */
function repaintSound() {
  const old = st.el && st.el.querySelector('[data-sec="sound"]');
  if (!old || (document.activeElement && document.activeElement.type === "range" && old.contains(document.activeElement))) return;
  const focusKey = document.activeElement && old.contains(document.activeElement) ? keyOf(document.activeElement) : null;
  const fresh = soundSection();
  old.replaceWith(fresh);
  if (focusKey) { const f = findKey(fresh, focusKey); if (f) f.focus({preventScroll: true}); }
}

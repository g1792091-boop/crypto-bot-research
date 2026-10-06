// TV 자동 넘김 (owners 10/06, conv-b: "사무실 TV에 켜 두고 저절로 넘어가게"): a kiosk mode that shows the chosen screens one
// after another, every N seconds (15-120; default 터미널 → 홈 → 계좌 순위 → 회의실 → 조합 시너지).
//   start     the key "t" (also "ㅅ", the same key in 한글 mode), the TV button at the PC rail's foot, the 서버 group's
//             sub-tab row (phones / tablets), or the TV panel's 시작. The 설정 panel (core/settings.js, when it is on
//             this build) shows the same controls through tvSection().
//   while on  the rail is hidden (html[data-tv="on"], core/tvmode.css), a small dim strip at the bottom right says
//             what is on screen, what comes next and in how many seconds (a real countdown to a real page change);
//             any touch, click, wheel or key pauses it (the strip says so) and it resumes by itself after 60 s with no
//             touch; t / Esc / 끝내기 ends it. The screen is kept awake with the Wake Lock API when the browser allows
//             it (a refusal is fine: the strip says '화면 꺼짐 막기 안 됨'), asked again when the page is shown again.
//   memory    per device ("tv": {on, secs, screens}, dom.js `local`, try/catch inside): a TV that reloads (a deploy, a
//             power cut) comes back rotating.
// HONESTY: the rotation never invents activity: it only changes which real screen is shown; nothing on a screen
// moves because of it. A 터미널 stop is skipped on a window narrower than the PC screen it needs (features.wide).
import {h, local} from "./dom.js";
import {features} from "./features.js";
import {href, parseHash, SCREENS} from "./routes.js";
import {closePeek, peekOpen} from "./drawer.js";
import {toast} from "./ui.js";

export const TV_KEY = "tv";
export const TV_MIN = 15, TV_MAX = 120, TV_DEF = 30, TV_IDLE_MS = 60000;
/** The stops the panel offers: id = "<screen>" or "<screen>/<arg>" (the 조합 시너지 tab of 분석). */
export const TV_CHOICES = [
  {id: "terminal", ko: "터미널", wide: true},
  {id: "home", ko: "홈"},
  {id: "board", ko: "계좌 순위"},
  {id: "office", ko: "회의실"},
  {id: "analysis/synergy", ko: "조합 시너지"},
  {id: "positions", ko: "포지션"},
  {id: "flow", ko: "흐름"},
  {id: "chart", ko: "차트"},
  {id: "market", ko: "시장"},
  {id: "grid", ko: "한눈 지도"},
  {id: "strategies", ko: "매매법"},
  {id: "compare", ko: "매매법 비교"},
  {id: "digest", ko: "회의 요약"},
  {id: "server", ko: "서버·비용"},
];
export const TV_DEFAULT = ["terminal", "home", "board", "office", "analysis/synergy"];
const CHOICE = Object.fromEntries(TV_CHOICES.map((c) => [c.id, c]));

export const clampSecs = (n) => { const v = Math.round(Number(n)); return Number.isFinite(v) ? Math.max(TV_MIN, Math.min(TV_MAX, v)) : TV_DEF; };
/** The remembered settings from a stored value (unknown stops dropped; none left = the default five). */
export function readTv(raw) {
  const o = raw && typeof raw === "object" && !Array.isArray(raw) ? raw : {};
  let screens = Array.isArray(o.screens) ? o.screens.filter((x, i, a) => typeof x === "string" && CHOICE[x] && a.indexOf(x) === i) : [];
  if (!screens.length) screens = [...TV_DEFAULT];
  return {on: o.on === true, secs: clampSecs(o.secs ?? TV_DEF), screens};
}
/** The stop list this window can show (a 터미널 stop needs the PC width). */
export const playable = (screens, wideOk) => screens.filter((id) => CHOICE[id] && (!CHOICE[id].wide || wideOk));
/** The stop that matches the page now ("analysis/synergy" for #/analysis/synergy), else null. */
export function stopOf(p) {
  if (!p) return null;
  const full = p.arg ? `${p.name}/${p.arg}` : p.name;
  return CHOICE[full] ? full : CHOICE[p.name] && !p.arg ? p.name : null;
}
/** The next stop after the current one (the first when the page is not one of them). */
export function nextStop(list, cur) {
  if (!list.length) return null;
  const i = list.indexOf(cur);
  return list[(i + 1) % list.length];
}
export const stopKo = (id) => (CHOICE[id] ? CHOICE[id].ko : (SCREENS[id] || {}).ko || id);
const stopHref = (id) => { const [n, a] = id.split("/"); return href(n, a || null); };

// ---------------------------------------------------------------- the running state
const st = {cfg: null, timer: 0, tick: 0, idle: 0, due: 0, paused: false, lock: null, chip: null, next: null, panel: null, listening: false};
const cfg = () => st.cfg || (st.cfg = readTv(local.get(TV_KEY, null)));
const save = () => local.set(TV_KEY, cfg());
export const tvOn = () => cfg().on;

function list() { return playable(cfg().screens, !!features.wide); }

function schedule(ms) {
  clearTimeout(st.timer);
  st.due = Date.now() + ms;
  st.timer = setTimeout(advance, ms);
  paintChip();
}
function advance() {
  if (!cfg().on || st.paused) return;
  if (document.hidden) { schedule(5000); return; }          // nobody sees it: try again when shown
  const L = list();
  if (!L.length) { stopTv("이 창 크기에서 보여 줄 화면이 없어 TV 자동 넘김을 끝냈습니다"); return; }
  const to = nextStop(L, stopOf(parseHash(location.hash)));
  const go = () => { const want = stopHref(to); if (location.hash !== want) location.hash = want; };
  if (peekOpen()) closePeek(go); else go();
  schedule(cfg().secs * 1000);
}

// any touch / click / wheel / key pauses; 60 s with no input resumes
function onInput(e) {
  if (!cfg().on) return;
  if (st.chip && e.target instanceof Node && st.chip.contains(e.target)) return;      // the strip's own buttons
  if (st.panel && !st.panel.hidden && e.target instanceof Node && st.panel.contains(e.target)) return;
  pause(true);
}
function pause(byInput) {
  st.paused = true;
  clearTimeout(st.timer);
  clearTimeout(st.idle);
  if (byInput) st.idle = setTimeout(() => resume(), TV_IDLE_MS);
  st.due = byInput ? Date.now() + TV_IDLE_MS : 0;
  paintChip();
}
function resume() {
  clearTimeout(st.idle);
  if (!cfg().on) return;
  st.paused = false;
  schedule(cfg().secs * 1000);
}

// ---------------------------------------------------------------- keep the screen awake (tolerate a refusal)
async function wake() {
  if (!cfg().on || document.hidden) return;
  try {
    if (!navigator.wakeLock || typeof navigator.wakeLock.request !== "function") { st.lock = "none"; paintChip(); return; }
    if (st.lock && st.lock !== "none" && !st.lock.released) return;
    const l = await navigator.wakeLock.request("screen");
    if (!cfg().on) { try { await l.release(); } catch (e) { /* gone */ } return; }
    st.lock = l;
    l.addEventListener("release", () => { if (st.lock === l) { st.lock = null; paintChip(); } });
  } catch (e) { st.lock = "none"; }            // refused (battery saver, not allowed here): the rotation still runs
  paintChip();
}
function unwake() {
  const l = st.lock;
  st.lock = null;
  if (l && l !== "none") { try { l.release(); } catch (e) { /* gone */ } }
}

// ---------------------------------------------------------------- the strip (bottom right, dim)
function buildChip() {
  if (st.chip) return st.chip;
  const now = h("b", {class: "tvchip-now"});
  const next = h("span", {class: "tvchip-next num"});
  const awake = h("span", {class: "tvchip-wake"});
  const pauseBtn = h("button", {type: "button", class: "tvchip-b", onclick: () => (st.paused ? resume() : pause(false))}, "멈춤");
  const endBtn = h("button", {type: "button", class: "tvchip-b", onclick: () => stopTv()}, "끝내기");
  st.chip = h("div", {class: "tvchip", role: "status", "aria-live": "off", hidden: true},
    h("span", {class: "tvchip-tag", "aria-hidden": "true"}, "TV"), h("span", {class: "tvchip-t"}, now, next, awake), pauseBtn, endBtn);
  st.chip._now = now; st.chip._next = next; st.chip._wake = awake; st.chip._pause = pauseBtn;
  document.body.append(st.chip);
  return st.chip;
}
function paintChip() {
  if (typeof document === "undefined") return;
  const on = cfg().on;
  document.documentElement.dataset.tv = on ? "on" : "";
  if (!on) { if (st.chip) st.chip.hidden = true; return; }
  const c = buildChip();
  c.hidden = false;
  const L = list(), cur = stopOf(parseHash(location.hash));
  const nx = nextStop(L, cur);
  const left = Math.max(0, Math.ceil((st.due - Date.now()) / 1000));
  c._now.textContent = cur ? stopKo(cur) : (SCREENS[parseHash(location.hash).name] || {}).ko || "";
  c._next.textContent = st.paused
    ? (st.due ? ` · 멈춤 (손대지 않으면 ${left}초 뒤 다시)` : " · 멈춤")
    : nx ? ` → ${stopKo(nx)} ${left}초` : "";
  c._wake.textContent = st.lock === "none" ? " · 화면 꺼짐 막기 안 됨" : "";
  c._pause.textContent = st.paused ? "계속" : "멈춤";
  c.dataset.paused = st.paused ? "1" : "";
}

function listen() {
  if (st.listening) return;
  st.listening = true;
  for (const ev of ["pointerdown", "keydown", "wheel", "touchstart"]) document.addEventListener(ev, onInput, {capture: true, passive: true});
  document.addEventListener("visibilitychange", () => { if (!document.hidden && cfg().on) wake(); });
  window.addEventListener("hashchange", () => { if (cfg().on) paintChip(); });
}

/** Start (or restart with new settings) the rotation; the current screen stays for one full period first. */
export function startTv(o = {}) {
  const c = cfg();
  if (o.secs != null) c.secs = clampSecs(o.secs);
  if (Array.isArray(o.screens)) c.screens = readTv({screens: o.screens}).screens;
  if (!list().length) { toast("고른 화면이 이 창 크기에서는 없습니다 (터미널은 PC 화면)"); return false; }
  c.on = true;
  save();
  listen();
  st.paused = false;
  clearTimeout(st.idle);
  clearInterval(st.tick);
  st.tick = setInterval(paintChip, 1000);
  wake();
  schedule(c.secs * 1000);
  if (!o.quiet) toast(`TV 자동 넘김 시작 · ${c.secs}초마다 ${list().length}개 화면 · 만지면 멈춤 · t 키로 끝`);
  return true;
}
/** End the rotation (the rail comes back, the screen may sleep again). */
export function stopTv(msg) {
  const c = cfg();
  c.on = false;
  save();
  clearTimeout(st.timer); clearTimeout(st.idle); clearInterval(st.tick);
  st.paused = false;
  unwake();
  paintChip();
  toast(msg || "TV 자동 넘김을 끝냈습니다");
}
export const toggleTv = () => (cfg().on ? (stopTv(), false) : startTv());

/** Boot: a device that was rotating comes back rotating (core/main.js). */
export function startTvMode() {
  listen();
  if (cfg().on) startTv({quiet: true});
  else paintChip();
}

// ---------------------------------------------------------------- the controls (the TV panel and the 설정 section)
/** The controls: seconds slider, the stops (checkboxes, in the fixed order above), 시작 / 끝내기. */
export function tvSection(onDone) {
  const c = cfg();
  const val = h("b", {class: "num tvp-secs"}, `${c.secs}초`);
  const slider = h("input", {type: "range", min: String(TV_MIN), max: String(TV_MAX), step: "5", value: String(c.secs), class: "tvp-range",
    "aria-label": "한 화면에 머무는 시간 (초)", "data-noswipe": "1",
    oninput: () => { val.textContent = `${clampSecs(slider.value)}초`; },
    onchange: () => { c.secs = clampSecs(slider.value); save(); if (c.on) startTv({quiet: true}); }});
  const boxes = TV_CHOICES.map((x) => {
    const cb = h("input", {type: "checkbox", value: x.id, checked: c.screens.includes(x.id) || null,
      onchange: () => {
        const chosen = boxes.filter((b) => b.checked).map((b) => b.value);
        c.screens = chosen.length ? chosen : [...TV_DEFAULT];
        if (!chosen.length) for (const b of boxes) b.checked = TV_DEFAULT.includes(b.value);
        save();
        if (c.on) startTv({quiet: true});
      }});
    return cb;
  });
  const items = TV_CHOICES.map((x, i) => h("label", {class: ["tvp-stop", x.wide && !features.wide ? "dim" : ""]}, boxes[i], h("span", null, x.ko),
    x.wide ? h("small", null, "PC 화면") : null));
  const go = h("button", {type: "button", class: "btn-y", onclick: () => { if (startTv()) { if (onDone) onDone(); } }}, cfg().on ? "다시 시작" : "시작");
  const end = h("button", {type: "button", class: "btn-line", hidden: !cfg().on, onclick: () => { stopTv(); if (onDone) onDone(); }}, "끝내기");
  return h("section", {class: "tvp-sec", "aria-label": "TV 자동 넘김"},
    h("p", {class: "tvp-lead"}, "고른 화면을 차례로 보여 줍니다. 화면을 만지거나 키를 누르면 멈추고, 60초 동안 가만두면 다시 넘깁니다. 넘기는 동안 왼쪽 메뉴는 숨깁니다."),
    h("div", {class: "tvp-row"}, h("span", null, "한 화면에"), slider, val),
    h("fieldset", {class: "tvp-stops"}, h("legend", null, "보여 줄 화면 (이 순서대로 넘어감)"), items),
    h("p", {class: "tvp-note"}, "화면 꺼짐 막기: 브라우저가 허락하면 넘기는 동안 화면을 켜 둡니다. 이 기기에만 기억합니다."),
    h("div", {class: "tvp-acts"}, go, end));
}

/** The TV panel (a sheet on a phone, a small dialog on a PC). */
export function openTvPanel() {
  if (!st.panel) {
    st.panel = h("div", {class: "tvp", hidden: true, onclick: (e) => { if (e.target === st.panel) closeTvPanel(); }});
    st.panel.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); closeTvPanel(); } });
    document.body.append(st.panel);
  }
  st.panel.replaceChildren(h("div", {class: "tvp-box", role: "dialog", "aria-modal": "true", "aria-labelledby": "tvp-t"},
    h("div", {class: "tvp-head"}, h("h2", {id: "tvp-t"}, "TV 자동 넘김"), h("span", {class: "grow"}),
      h("button", {type: "button", class: "tvp-x", "aria-label": "닫기 (Esc)", onclick: () => closeTvPanel()}, "✕")),
    tvSection(() => closeTvPanel())));
  st.panel.hidden = false;
  const f = st.panel.querySelector(".tvp-x");
  if (f) f.focus({preventScroll: true});
}
export function closeTvPanel() { if (st.panel) st.panel.hidden = true; }
export const tvPanelOpen = () => !!(st.panel && !st.panel.hidden);

/** The small 'TV' button (the PC rail's foot) and the sub-tab row's 'TV 자동 넘김' (서버 group, phones / tablets). */
export const tvRailBtn = () => h("button", {type: "button", class: "tvbtn", title: "TV 자동 넘김 (t)", "aria-label": "TV 자동 넘김: 화면을 차례로 보여 주기 (단축키 t)",
  onclick: () => openTvPanel()}, "TV");
export const tvTab = () => h("button", {type: "button", class: "tvtab", onclick: () => openTvPanel()}, "TV 자동 넘김");

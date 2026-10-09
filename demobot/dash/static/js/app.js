// The shell: the grouped menu (plain Korean text buttons like the rule bot's, thin lines between the groups; on top or,
// by choice, as a left column from 1000 px), hash routes, the server state dot (/api/status every 30 s), the top bar's
// tools (topbar.js: D+n pill, 찾기, ★, 자는 동안, the bell, the sound), the viewer's settings (prefs.js: 글자 크기,
// 메뉴 위치, 화면 색), the "마지막 갱신" stamp, and each screen's polling (paused while the page is hidden).
// Screens: js/screens/<name>.js with mount(el, ctx) (returning an optional cleanup). A route is
// #/<screen>[/<arg>[/<arg2>]][?query], e.g. #/trade/<account id>/<trade key> (both parts URI-encoded). #/ opens the
// terminal when that screen exists, else 요약 (home).
import {h, put} from "./dom.js";
import {getJSON, isMissing} from "./api.js";
import {hms, dur} from "./fmt.js";
import {stamp, setPage} from "./ui.js";
import {applySkin, skinNow} from "./prefs.js";
import {initFind} from "./find.js";
import {initTopbar, onStatus, stripLead, stripTools} from "./topbar.js";

// Menu entries: {id, ko, group, also (routes that light this entry), end (last in its group)}. The groups' order is
// GROUPS; an entry without a group belongs to "main"; an unknown group goes to the last group.
const MENU = [
  {id: "terminal", ko: "터미널", group: "live"},
  {id: "positions", ko: "포지션", group: "live"},
  {id: "charts", ko: "여러 차트", group: "live"},
  {id: "market", ko: "시장", group: "live"},
  {id: "signals", ko: "신호", group: "live"},
  {id: "home", ko: "요약"},
  {id: "rank", ko: "설정 순위", group: "main"},
  {id: "judge", ko: "판정", group: "main"},
  {id: "path", ko: "졸업 길", group: "main"},
  {id: "ready", ko: "실전 준비", group: "main"},
  {id: "friend", ko: "친구 계획", group: "main"},
  {id: "leverage", ko: "레버리지 비교", group: "main"},
  {id: "glance", ko: "한눈 지도", group: "main"},
  {id: "accounts", ko: "순위표", group: "detail", also: ["account", "trade"]},
  {id: "flow", ko: "흐름", group: "detail"},
  {id: "compare", ko: "비교", group: "detail"},
  {id: "coins", ko: "코인별", group: "detail"},
  {id: "trades", ko: "거래 기록", group: "detail"},
  {id: "analysis", ko: "분석", group: "detail"},
  {id: "strategies", ko: "매매법", group: "detail"},
  {id: "vs5y", ko: "5년 대비", group: "detail"},
  {id: "whatif", ko: "만약 실험실", group: "detail"},
  {id: "map", ko: "설정 지도", group: "detail"},
  {id: "regime", ko: "시장 국면", group: "info"},
  {id: "costs", ko: "실제 비용", group: "info"},
  {id: "review", ko: "주간 회의록", group: "info"},
  {id: "views", ko: "관점 기록", group: "info"},
  {id: "telegram", ko: "알림 기록", group: "info"},
  {id: "status", ko: "서버 상태", group: "info"},
  {id: "dataq", ko: "데이터 점검", group: "info"},
  {id: "timeline", ko: "타임라인", group: "info"},
  {id: "howto", ko: "어떻게 돌아가나", group: "info", end: true},
];
const GROUPS = [{id: "live", ko: "실시간"}, {id: "main", ko: "요약 · 판정"}, {id: "detail", ko: "계좌 · 분석"}, {id: "info", ko: "기록 · 안내"}];
const MENU_TITLE = {home: "요약 (홈)", rank: "설정 순위 (모든 설정을 줄 세운 표)", accounts: "순위표 (계좌 × 배수, 묶음별)",
  flow: "흐름 (종류별 누적 손익 · 날마다 · 달력)", path: "졸업 길 (운 지도)", glance: "한눈 지도 (모든 계좌 × 배수)", whatif: "만약 실험실 (청산 14가지)"};
const SCREENS = {home: "home", rank: "rank", accounts: "accounts", account: "account", trades: "trades", judge: "judge",
  views: "views", status: "status", howto: "howto", trade: "trade", regime: "regime", costs: "costs", compare: "compare",
  glance: "glance", path: "path", analysis: "analysis", strategies: "strategies", vs5y: "vs5y", whatif: "whatif",
  friend: "friend", leverage: "leverage", ready: "ready", review: "review", telegram: "telegram", map: "map",
  coins: "coins", terminal: "terminal", positions: "positions", charts: "charts", market: "market",
  signals: "signals", dataq: "dataq", timeline: "timeline", flow: "flow"};
const TITLE = "데모 랩";
/** The start screen (#/ and any unknown route): the terminal when this build has it, else 요약 (home). */
const START = () => (SCREENS.terminal ? "terminal" : "home");

/** The menu's groups in order, each with its entries (only screens this build has; "end" entries last). */
function menuGroups() {
  const ids = GROUPS.map((g) => g.id);
  const gid = (m) => (ids.includes(m.group || "main") ? m.group || "main" : ids[ids.length - 1]);
  return GROUPS.map((g) => ({...g, items: MENU.filter((m) => SCREENS[m.id] && gid(m) === g.id)
    .map((m, i) => ({m, i})).sort((a, b) => (a.m.end ? 1 : 0) - (b.m.end ? 1 : 0) || a.i - b.i).map((x) => x.m)}))
    .filter((g) => g.items.length);
}
/** Every menu screen with its group's name (찾기, ★). */
const menuList = () => menuGroups().flatMap((g) => g.items.map((m) => ({id: m.id, ko: m.ko, title: MENU_TITLE[m.id] || "", groupKo: g.ko})));

// ---------------------------------------------------------------- the menu
const menu = document.getElementById("menu");
const links = {};
function buildMenu() {
  for (const k of Object.keys(links)) delete links[k];
  // one flat row: the groups' buttons with a thin line between groups (a long row wraps or scrolls without leaving
  // half-empty rows); the group names show only in the left column (메뉴 위치 왼쪽)
  const kids = [];
  menuGroups().forEach((g, gi) => {
    if (gi) kids.push(h("span", {class: "sg-sep", "aria-hidden": "true"}));
    kids.push(h("span", {class: "sg-k", "aria-hidden": "true", dataset: {group: g.id}}, g.ko));
    for (const m of g.items) {
      const a = h("a", {class: "sb", href: `#/${m.id}`, dataset: {screen: m.id, group: g.id}, title: MENU_TITLE[m.id] || null},
        h("span", {class: "sb-t", dataset: {t: m.ko}}, m.ko));
      links[m.id] = a;
      kids.push(a);
    }
  });
  put(menu, h("span", {class: "strip-lead"}, stripLead()), kids, h("span", {class: "strip-tools"}, stripTools()));
  if (cur) markMenu(cur.name);
  tidyMenu();
}
/** A group line that ends up at a row's end or start of the wrapped PC row is hidden (it would separate nothing). */
function tidyMenu() {
  for (const sep of menu.querySelectorAll(".sg-sep")) {
    const prev = sep.previousElementSibling;
    let next = sep.nextElementSibling;
    while (next && next.classList.contains("sg-k")) next = next.nextElementSibling;
    sep.style.visibility = prev && next && Math.abs(next.offsetTop - prev.offsetTop) > 4 ? "hidden" : "";
  }
}
if (typeof ResizeObserver === "function") new ResizeObserver(() => tidyMenu()).observe(menu);
if (document.fonts && document.fonts.ready) document.fonts.ready.then(tidyMenu, () => {});
function markMenu(name) {
  for (const m of MENU) {
    const a = links[m.id];
    if (!a) continue;
    const on = m.id === name || (m.also || []).includes(name);
    if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    if (on && menu.scrollWidth > menu.clientWidth + 1) {             // the phone's sideways row: bring it into view
      const r = a.getBoundingClientRect(), mr = menu.getBoundingClientRect();
      const lead = menu.querySelector(".strip-lead");               // 찾기 · ★ stay at the row's left edge on a phone
      const off = lead && getComputedStyle(lead).position === "sticky" ? lead.getBoundingClientRect().width : 0;
      if (r.left < mr.left + off || r.right > mr.right) menu.scrollLeft += r.left - mr.left - off - 16;
    }
  }
}

// ---------------------------------------------------------------- the "마지막 갱신" stamp
let lastOk = 0;
function touch() {
  lastOk = Date.now();
  stamp.textContent = `마지막 갱신 ${hms(lastOk)} KST`;
  stamp.title = "이 화면이 서버에서 자료를 마지막으로 받은 시각 (한국 시간)";
}

// ---------------------------------------------------------------- server state: the dot (every 30 s); the pill is topbar.js
const statusFns = new Set();
let statusNow = null;
const hdot = document.getElementById("hdot");
function levelOf(st) {
  if (!st || isMissing(st)) return {lv: "warn", ko: "엔진 상태 파일이 아직 없습니다"};
  const now = Date.now();
  if (st.phase === "stopped") return {lv: "bad", ko: "엔진이 멈춰 있습니다"};
  if (st.errors && st.errors.length) return {lv: "bad", ko: `오류 ${st.errors.length}건`};
  if (st.phase === "live" && st.last_tick_ms && now - st.last_tick_ms > 40 * 60000) return {lv: "bad", ko: `마지막 처리 ${dur((now - st.last_tick_ms) / 1000)} 전`};
  if (st.data_ok === false || (st.data_issues && st.data_issues.length)) return {lv: "warn", ko: "자료 문제가 있습니다"};
  if (st.phase === "warm") return {lv: "warn", ko: "과거 자료를 채우는 중"};
  return {lv: "ok", ko: "정상"};
}
function paintState(st) {
  const L = levelOf(st);
  hdot.dataset.level = L.lv;
  hdot.setAttribute("aria-label", `서버 상태: ${L.ko} (누르면 서버 상태 화면)`);
  hdot.title = `서버 상태: ${L.ko}`;
}
async function pollStatus() {
  try {
    statusNow = await getJSON("/api/status");
    touch();
  } catch (e) {
    if (e && e.status === 401) return;
    statusNow = statusNow || null;
  }
  paintState(statusNow);
  onStatus(statusNow);
  for (const fn of statusFns) { try { fn(statusNow); } catch (e) { console.error(e); } }
}
hdot.addEventListener("click", () => { location.hash = "#/status"; });

// ---------------------------------------------------------------- router
const main = document.getElementById("screen");
let cur = null;                // {name, cleanup, ctl, timers, el}

function parseHash() {
  const raw = (location.hash || "").replace(/^#\/?/, "");
  const [path, qs] = raw.split("?");
  const parts = path.split("/").filter(Boolean);
  const name = SCREENS[parts[0]] ? parts[0] : START();
  const query = Object.fromEntries(new URLSearchParams(qs || ""));
  const dec = (x) => { try { return decodeURIComponent(x); } catch (e) { return null; } };
  return {name, arg: parts[1] ? dec(parts[1]) : null, arg2: parts[2] ? dec(parts[2]) : null, query};
}

function makeCtx(el, params) {
  const ctl = new AbortController();
  const timers = [];
  const ctx = {
    params,
    signal: ctl.signal,
    alive: () => !ctl.signal.aborted,
    async api(path) { const d = await getJSON(path, ctl.signal); if (!ctl.signal.aborted) touch(); return d; },
    every(ms, fn) {
      const t = {ms, fn, id: null, busy: false};
      const tick = async () => {
        if (document.visibilityState === "hidden" || t.busy || ctl.signal.aborted) return;
        t.busy = true;
        try { await fn(); } catch (e) { if (!(e && e.name === "AbortError")) console.error(e); } finally { t.busy = false; }
      };
      t.tick = tick;
      t.id = setInterval(tick, ms);
      timers.push(t);
    },
    onStatus(fn) {
      statusFns.add(fn);
      ctl.signal.addEventListener("abort", () => statusFns.delete(fn));
      if (statusNow) fn(statusNow); else pollStatus();
    },
    setTitle(t) { document.title = t ? `${t} · ${TITLE}` : TITLE; },
    href: (name, arg, q, arg2) => `#/${name}${arg ? "/" + encodeURIComponent(arg) : ""}${arg2 ? "/" + encodeURIComponent(arg2) : ""}${q && Object.keys(q).length ? "?" + new URLSearchParams(q) : ""}`,
    /** change the hash's query without remounting (a filter the viewer can bookmark) */
    setQuery(q) {
      const hash = ctx.href(params.name, params.arg, q, params.arg2);
      if (location.hash !== hash) history.replaceState(null, "", hash);
    },
  };
  return {ctx, ctl, timers};
}

async function mountScreen() {
  const params = parseHash();
  if (cur) {
    cur.ctl.abort();
    cur.timers.forEach((t) => clearInterval(t.id));
    try { if (typeof cur.cleanup === "function") cur.cleanup(); } catch (e) { console.error(e); }
  }
  markMenu(params.name);
  const entry = MENU.find((m) => m.id === params.name);
  setPage(entry ? {id: entry.id, ko: entry.ko} : null);           // the ☆ next to a menu screen's title
  const el = h("div", {class: "scr", "data-screen": params.name});
  put(main, el);
  const {ctx, ctl, timers} = makeCtx(el, params);
  cur = {name: params.name, ctl, timers, el, cleanup: null};
  window.scrollTo(0, 0);
  try {
    const mod = await import(`./screens/${SCREENS[params.name]}.js`);
    if (ctl.signal.aborted) return;
    cur.cleanup = await mod.mount(el, ctx);
  } catch (e) {
    if (e && (e.name === "AbortError" || e.status === 401)) return;
    console.error(e);
    put(el, h("div", {class: "errbox"}, "이 화면을 열지 못했습니다. ", h("button", {class: "btn-line", type: "button", onclick: mountScreen}, "다시 시도")));
  }
}
function remount() { mountScreen(); }

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "visible") return;
  pollStatus();
  if (cur) cur.timers.forEach((t) => t.tick && t.tick());
});
window.addEventListener("hashchange", mountScreen);

applySkin(skinNow());
initTopbar({menu: menuList, onText: remount, onNav: () => { buildMenu(); remount(); }, onSkin: () => { applySkin(skinNow()); remount(); }});
initFind(menuList);
buildMenu();
pollStatus();
setInterval(() => { if (document.visibilityState !== "hidden") pollStatus(); }, 30000);
mountScreen();

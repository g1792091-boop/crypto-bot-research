// 후보 리그 dashboard shell, in the rule bot's v4 look (paperbot/dash/static/v4 core/shell.js, strip.js, find.js,
// settings.js; copied and adapted, nothing imported from it):
//   top bar   brand · 글자 크기 · 화면 색 · 메뉴 위치 · 설정 (a PC with the menu on top) · 찾기 / · the day pill
//             "D+10 · 1차 11/11 · 2차 12/11 · 3차 1/11 ▾" (days gone since 10/01 KST, counted like the rule bot's:
//             10/01 = D+0; the next checkpoint lit; its popover has the processed time) · the engine dot · 모의
//   menu      every screen its own plain text button, in groups with a thin line between them (거래 | 홈 | 매매법 | 안내),
//             on top (wraps from 1200 px, one sideways row below) or, by choice, a left column from 1000 px; a phone also
//             gets the bottom bar of the four groups
//   landing   an empty address opens the 터미널 on a window 1100 px and wider, 요약 on a phone (설정 › 첫 화면 changes it)
//   설치 뒤    the per-device view switch "설치 뒤 진입만" (js/after.js): the screens with lists of open positions and
//             closed trades show it and filter through it; a change remounts the screen (like 글자 크기), a new snapshot
//             repaints its label (the install time)
//   data      one shared copy of the engine's snapshot (/api/league every 30 s, paused while the page is hidden) that
//             every screen reads (ctx.onLeague); the live prices (js/live.js, ctx.onLive) and the open positions
//             (js/poskit.js, ctx.onPositions) are polled once for the page while a screen listens
// Screens: js/screens/<name>.js with mount(el, ctx) (returning an optional cleanup), registered in SCREENS (and MENU for a
// menu button). A module may also export `css` (a path under /static/, or a list: loaded before mount) and `wide = true`
// (the screen uses the window's full width, like the rule bot's 터미널). A route is #/<screen>[/<arg>][?query].
import {h, s, put} from "./dom.js";
import {getJSON} from "./api.js";
import * as fmt from "./fmt.js";
import * as ui from "./ui.js";
import {stamp, setPage} from "./ui.js";
import {applySkin, skinNow, textSwitch, skinSwitch, navSwitch, textCycle, skinCycle, startPref} from "./prefs.js";
import {setLeague, getMeta, leagueDay, calDay, dPlus, catchingUp, health} from "./lk.js";
import {onLive, serverNow} from "./live.js";
import {onPositions, kickPositions} from "./poskit.js";
import {openFind, closeFind, findOpen, setFindScreens, lensIcon} from "./find.js";
import {gearButton, settingsTab, openSettings, closeSettings, settingsOpen, setSettingsHooks} from "./settings.js";
import {onAfterChange, syncAfter} from "./after.js";

const GROUPS = [{id: "trade", ko: "거래"}, {id: "home", ko: "홈"}, {id: "method", ko: "매매법"}, {id: "info", ko: "안내"}];
const MENU = [
  {id: "terminal", ko: "터미널", group: "trade"},
  {id: "positions", ko: "포지션", group: "trade"},
  {id: "entries", ko: "진입 차트", group: "trade"},
  {id: "fills", ko: "체결 기록", group: "trade"},
  {id: "home", ko: "요약", group: "home"},
  {id: "rank", ko: "순위표", group: "home", also: ["account"]},
  {id: "check", ko: "점검 진행", group: "home"},
  {id: "compare", ko: "5계좌 비교", group: "home"},
  {id: "weekly", ko: "주간 흐름", group: "home"},
  {id: "strategies", ko: "매매법", group: "method"},
  {id: "custom", ko: "커스텀값", group: "method"},
  {id: "status", ko: "서버 상태", group: "info"},
  {id: "howto", ko: "읽는 법", group: "info"},
];
const MENU_TITLE = {terminal: "터미널 (차트 · 열린 포지션 · 체결 · 수익)", positions: "포지션 (모의 계좌의 열린 포지션, 실시간 손익)",
  entries: "진입 차트 (매매법마다 따로, 후보가 들어간 자리)", fills: "체결 기록 (모든 계좌의 닫힌 거래)", home: "요약",
  check: "점검 진행 (11/11 · 12/11 · 1/11 기준이 지금 어떤지)", rank: "순위표 (후보 38개와 비교 계좌 190개)",
  compare: "5계좌 비교 (후보 · 1/4 · 청산만 · 기본값 · 동전)", weekly: "주간 흐름 (주마다 후보 · 기본값 · 동전)",
  custom: "커스텀값 (기본값과 바뀐 숫자, 익절·손절)", strategies: "매매법 (16개 매매법 설명과 묶음 성적)",
  status: "서버 상태 (엔진 · 시세 · 처리 시각)", howto: "읽는 법 (계좌 5개, 점검 규칙, 낱말 뜻)"};
const SCREENS = {home: "home", check: "check", rank: "rank", compare: "compare", custom: "custom", strategies: "strategies",
  weekly: "weekly", terminal: "terminal", entries: "entries", positions: "positions", fills: "fills", status: "status", howto: "howto",
  account: "account"};
const TITLE = "후보 리그";
const WIDE_PX = 1100;                         // the rule bot opens its 터미널 on a PC window, 요약 here on a phone

/** The screen an empty address opens: 설정 › 첫 화면, else the 터미널 on a window 1100 px and wider, else 요약. */
const autoStart = () => (typeof innerWidth === "number" && innerWidth >= WIDE_PX ? "terminal" : "home");
function landing() {
  const p = startPref();
  return p && SCREENS[p] ? p : autoStart();
}
const groupKo = (id) => (GROUPS.find((g) => g.id === id) || {ko: ""}).ko;

// ---------------------------------------------------------------- the menu
const menu = document.getElementById("menu");
const bot = document.getElementById("botbar");
const links = {};
const findSub = () => h("button", {type: "button", class: "findsub", "aria-label": "찾기: 화면, 후보, 계좌", onclick: () => openFind()}, lensIcon(), "찾기");
function buildMenu() {
  const kids = [];
  GROUPS.forEach((g, gi) => {
    if (gi) kids.push(h("span", {class: "sg-sep", "aria-hidden": "true"}));
    kids.push(h("span", {class: "sg-k", "aria-hidden": "true", dataset: {group: g.id}}, g.ko));
    for (const m of MENU.filter((x) => x.group === g.id)) {
      const a = h("a", {class: "sb", href: `#/${m.id}`, dataset: {screen: m.id, group: g.id}, title: MENU_TITLE[m.id] || null},
        h("span", {class: "sb-t", dataset: {t: m.ko}}, m.ko));
      links[m.id] = a;
      kids.push(a);
    }
  });
  put(menu, h("span", {class: "strip-lead"}, findSub(), textCycle(remount)), kids,
    h("span", {class: "strip-tools"}, textSwitch(remount), skinSwitch(onSkin), navSwitch(onNav), settingsTab()));
  if (cur) markMenu(cur.name);
}
/** The phone's bottom bar: the four groups (a tap opens the group's first screen, or stays on the group's screen). */
const BOT_IC = {
  trade: [[1, 9, 3, 6], [6, 5, 3, 10], [11, 2, 3, 13]],
  home: [[7, 1, 2, 2], [5, 3, 6, 2], [3, 5, 10, 2], [3, 7, 2, 8], [11, 7, 2, 8], [7, 10, 2, 5], [3, 13, 10, 2]],
  method: [[2, 2, 12, 2], [2, 7, 12, 2], [2, 12, 8, 2]],
  info: [[7, 1, 2, 2], [6, 5, 3, 2], [7, 7, 2, 6], [5, 13, 6, 2]],
};
const botIcon = (id) => s("svg", {viewBox: "0 0 16 16", fill: "currentColor", "shape-rendering": "crispEdges", "aria-hidden": "true"},
  (BOT_IC[id] || []).map(([x, y, w, hh]) => s("rect", {x, y, width: w, height: hh})));
function buildBot(name) {
  if (!bot) return;
  const m = MENU.find((x) => x.id === name || (x.also || []).includes(name));
  const gid = m ? m.group : null;
  put(bot, GROUPS.map((g) => {
    const first = MENU.find((x) => x.group === g.id);
    return h("a", {href: `#/${g.id === gid ? m.id : first.id}`, "aria-current": g.id === gid ? "page" : null, dataset: {group: g.id},
      title: MENU.filter((x) => x.group === g.id).map((x) => x.ko).join(" · ")}, botIcon(g.id), h("span", null, g.ko));
  }));
}
function markMenu(name) {
  for (const m of MENU) {
    const a = links[m.id];
    if (!a) continue;
    const on = m.id === name || (m.also || []).includes(name);
    if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    if (on && getComputedStyle(menu).flexWrap === "nowrap" && menu.scrollWidth > menu.clientWidth + 1) {
      // the sideways row (below 1200 px): the current button in the middle of what the sticky 찾기 · 가 leave free
      const lead = menu.querySelector(".strip-lead");
      const r = a.getBoundingClientRect(), mr = menu.getBoundingClientRect();
      const from = lead && lead.offsetParent && getComputedStyle(lead).position === "sticky" ? lead.getBoundingClientRect().right : mr.left;
      if (r.left < from + 16 || r.right > mr.right - 16) menu.scrollLeft = Math.max(0, menu.scrollLeft + (r.left + r.width / 2) - (from + mr.right) / 2);
    }
  }
  buildBot(name);
}
function onSkin() { applySkin(skinNow()); remount(); }
function onNav() { buildMenu(); buildTop(); remount(); }

// ---------------------------------------------------------------- the top bar
const tools = document.getElementById("toptools");
const brand = document.querySelector(".brand");
function buildTop() {
  put(tools, h("span", {class: "tt-set cl-tt"}, h("span", {class: "tt-full"}, textSwitch(remount), skinSwitch(onSkin)),
    h("span", {class: "tt-mini"}, textCycle(remount), skinCycle(onSkin)), navSwitch(onNav), gearButton()));
  const to = landing();
  const ko = (MENU.find((m) => m.id === to) || {ko: "요약"}).ko;
  brand.setAttribute("aria-label", `후보 리그 첫 화면 (${ko})`);
}
const findBtn = document.getElementById("findbtn");
put(findBtn, lensIcon(), h("span", {class: "findbtn-t"}, "찾기"), h("kbd", null, "/"));
findBtn.addEventListener("click", () => openFind());

const pill = document.getElementById("livechip");
const hdot = document.getElementById("hdot");
let pop = null;
function closePop() { if (pop) { pop.remove(); pop = null; pill.setAttribute("aria-expanded", "false"); } }
pill.setAttribute("aria-haspopup", "dialog");
pill.setAttribute("aria-expanded", "false");
pill.addEventListener("click", () => {
  if (pop) { closePop(); return; }
  pop = h("div", {class: "tb-pop", role: "dialog", "aria-label": "후보 리그 일정"}, pillPanel());
  document.querySelector(".shell-top").append(pop);
  pill.setAttribute("aria-expanded", "true");
});
document.addEventListener("mousedown", (e) => { if (pop && !pop.contains(e.target) && !pill.contains(e.target)) closePop(); });
window.addEventListener("hashchange", closePop);

let doc = null;
const checkpoints = () => ((doc && doc.watch && doc.watch.checkpoints) || []);
const cpShort = (c) => `${String(c.ko || c.id).replace(" 점검", "")} ${fmt.mmdd(c.ms).replace(/^0/, "").replace("/0", "/")}`;
function nextCp(now = serverNow()) { return checkpoints().find((c) => c.ms > now) || null; }
function pillPanel() {
  const cps = checkpoints();
  const now = serverNow();
  const next = nextCp(now);
  const left = next ? Math.ceil((next.ms - now) / 86400000) : null;
  return h("div", {class: "tb-pin"},
    h("div", {class: "tb-ph"}, h("b", null, doc && doc.start_ms ? `D+${dPlus(doc, now)} · 10/01부터 ${calDay(doc, now)}일째` : "일정"), h("span", {class: "grow"}),
      h("button", {class: "btn-line tb-x", type: "button", onclick: closePop}, "닫기")),
    h("p", {class: "tb-lead"}, next ? `다음: ${next.ko} ${fmt.mmdd(next.ms)} (${left}일 남음)` : "점검 일정 준비 중"),
    h("ol", {class: "steps dl-steps", "aria-label": "점검 일정"},
      h("li", {class: "done"}, "10/01 다시 돌리기 시작"), h("li", {class: "done"}, "10/11 설치"),
      cps.map((c) => h("li", {class: c === next ? "now" : c.ms <= now ? "done" : "", "aria-current": c === next ? "step" : null},
        `${c.ko} ${fmt.mmdd(c.ms)}`))),
    next && next.what ? h("p", {class: "note"}, `${next.ko}: ${next.what}`) : null,
    h("dl", {class: "kv"},
      h("div", null, h("dt", null, "오늘"), h("dd", null, doc && doc.start_ms ? `10/01부터 ${calDay(doc, now)}일째 (한국 날짜)` : "—")),
      h("div", null, h("dt", null, "엔진이 계산한 시각"), h("dd", null, doc ? `${fmt.kst(doc.done_ms)} KST (${leagueDay(doc)}일째까지)` : "—")),
      h("div", null, h("dt", null, "기록 쓴 시각"), h("dd", null, doc ? `${fmt.kst(doc.generated_ms)} KST (${fmt.ago(doc.generated_ms, now)})` : "—"))),
    doc && catchingUp(doc) ? h("p", {class: "kp-banner warn"}, h("b", null, "10/01부터 다시 계산 중"),
      `지금 ${fmt.kst(doc.done_ms)}까지 · 다 따라잡으면 5분마다 이어서 계산합니다`) : null,
    h("p", {class: "note"}, "점검 날짜와 기준은 시작 전에 고정했습니다 (WATCH_PREREG). 엔진은 5분마다 이어서 계산합니다 (새 진입·청산은 몇 분 늦게 보임)."),
    h("div", {class: "row wrap"}, h("a", {class: "btn-line", href: "#/check"}, "점검 진행"), h("a", {class: "btn-line", href: "#/howto"}, "읽는 법"),
      h("a", {class: "btn-line", href: "#/status"}, "서버 상태")));
}
function paintTop() {
  const H = health(doc, serverNow());
  hdot.dataset.level = H.lv;
  hdot.setAttribute("aria-label", `엔진 상태: ${H.ko} (누르면 서버 상태 화면)`);
  hdot.title = `엔진 상태: ${H.ko}`;
  if (!doc || !doc.accounts) { put(pill, h("b", null, "준비 중")); paintStamp(); return; }
  const now = serverNow();
  const next = nextCp(now);
  const cps = checkpoints();
  const day = calDay(doc, now);
  put(pill, h("b", null, `D+${dPlus(doc, now)}`),
    cps.map((c) => h("span", {class: ["d-cp", c === next ? "next" : c.ms <= now ? "done" : "later"]},
      h("span", {class: "d-dot", "aria-hidden": "true"}, "·"), cpShort(c), c.ms <= now ? " ✓" : null)),
    h("span", {class: "car", "aria-hidden": "true"}, "▾"));
  pill.setAttribute("aria-label", `10월 1일부터 ${day}일째${next ? `, 다음 ${next.ko} ${fmt.mmdd(next.ms)}` : ""}. 누르면 일정`);
  pill.title = next ? `다음 ${next.ko} ${fmt.mmdd(next.ms)} (${Math.ceil((next.ms - now) / 86400000)}일 남음)` : "";
  paintStamp();
}
hdot.addEventListener("click", () => { location.hash = "#/status"; });

/** The screens' "엔진 기준 HH:MM (n분 전)" stamp (B3: what the numbers are as of, not when the browser asked). */
function paintStamp() {
  if (!doc || !doc.generated_ms) { stamp.textContent = "엔진 기록 준비 중"; stamp.classList.remove("warn"); return; }
  const now = serverNow();
  const age = Math.max(0, (now - doc.generated_ms) / 1000);
  stamp.textContent = catchingUp(doc) ? `10/01부터 다시 계산 중 · ${fmt.kst(doc.done_ms)}까지` : `엔진 기준 ${fmt.kst(doc.done_ms)} KST · ${fmt.ago(doc.generated_ms, now)} 씀`;
  stamp.title = "엔진은 5분마다 계산해 기록을 씁니다. 이 화면의 숫자는 그 기록 기준입니다 (한국 시간).";
  stamp.classList.toggle("warn", catchingUp(doc) || age > 12 * 60);
}

// ---------------------------------------------------------------- the shared snapshot
const fns = new Set();
async function pollLeague() {
  try {
    const d = await getJSON("/api/league");
    if (!doc || !d.accounts || d.generated_ms !== doc.generated_ms || d.done_ms !== doc.done_ms) {
      doc = d;
      setLeague(d);
      syncAfter();
      paintTop();
      kickPositions();
      for (const fn of fns) { try { fn(d); } catch (e) { console.error(e); } }
    } else {
      paintStamp();
    }
  } catch (e) {
    if (e && e.status === 401) return;
  }
}

// ---------------------------------------------------------------- router
const main = document.getElementById("screen");
let cur = null;
function parseHash() {
  const raw = (location.hash || "").replace(/^#\/?/, "");
  const [path, qs] = raw.split("?");
  const parts = path.split("/").filter(Boolean);
  const name = SCREENS[parts[0]] ? parts[0] : landing();
  const dec = (x) => { try { return decodeURIComponent(x); } catch (e) { return null; } };
  return {name, arg: parts[1] ? dec(parts[1]) : null, query: Object.fromEntries(new URLSearchParams(qs || ""))};
}
function makeCtx(params) {
  const ctl = new AbortController();
  const timers = [];
  // a subscription made after the screen closed (its mount was still awaiting) is dropped at once, never left running
  const until = (unsub) => { if (ctl.signal.aborted) unsub(); else ctl.signal.addEventListener("abort", unsub); return unsub; };
  const ctx = {
    params,
    signal: ctl.signal,
    alive: () => !ctl.signal.aborted,
    async api(path) { return getJSON(path, ctl.signal); },
    meta: () => getMeta(),
    /** fn(doc) now (when the snapshot is here) and after every new snapshot, until the screen closes. */
    onLeague(fn) {
      if (ctl.signal.aborted) return;
      fns.add(fn);
      ctl.signal.addEventListener("abort", () => fns.delete(fn));
      if (doc) fn(doc); else pollLeague();
    },
    /** fn(liveDoc) after every /api/live answer (5 s) until the screen closes (js/live.js). */
    onLive: (fn) => until(onLive((d) => { if (!ctl.signal.aborted) fn(d); })),
    /** fn(positionsDoc) after every /api/positions answer (30 s and on each new snapshot) until the screen closes. */
    onPositions: (fn) => until(onPositions((d) => { if (!ctl.signal.aborted) fn(d); })),
    /** This screen's own stylesheet (under /static/); a Promise, resolved once it is on the page. */
    css: (href) => ui.css(href),
    /** The screen uses the window's full width (the 터미널) until it closes. */
    wide(on = true) { if (on) main.dataset.layout = "wide"; else delete main.dataset.layout; },
    every(ms, fn) {
      if (ctl.signal.aborted) return;
      const t = {busy: false, id: null};
      const tick = async () => {
        if (document.visibilityState === "hidden" || t.busy || ctl.signal.aborted) return;
        t.busy = true;
        try { await fn(); } catch (e) { if (!(e && e.name === "AbortError")) console.error(e); } finally { t.busy = false; }
      };
      t.tick = tick;
      t.id = setInterval(tick, ms);
      timers.push(t);
    },
    setTitle(t) { document.title = t ? `${t} · ${TITLE}` : TITLE; },
    href: (name, arg, q) => `#/${name}${arg ? "/" + encodeURIComponent(arg) : ""}${q && Object.keys(q).length ? "?" + new URLSearchParams(q) : ""}`,
    setQuery(q) {
      const hash = ctx.href(params.name, params.arg, q);
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
  setPage(entry ? {id: entry.id, ko: entry.ko} : null);
  const el = h("div", {class: "scr", "data-screen": params.name});
  delete main.dataset.layout;
  main.dataset.screen = params.name;
  put(main, el);
  const {ctx, ctl, timers} = makeCtx(params);
  cur = {name: params.name, ctl, timers, el, cleanup: null};
  ctx.setTitle(entry ? entry.ko : null);
  window.scrollTo(0, 0);
  try {
    const mod = await import(`./screens/${SCREENS[params.name]}.js`);
    if (ctl.signal.aborted) return;
    if (mod.css) await Promise.all([].concat(mod.css).map((x) => ui.css(x)));
    if (ctl.signal.aborted) return;
    if (mod.wide === true) ctx.wide(true);
    const cleanup = await mod.mount(el, ctx);
    // the screen was left while its mount awaited: the old ``cur`` is already cleaned, so its cleanup runs now
    if (ctl.signal.aborted) { try { if (typeof cleanup === "function") cleanup(); } catch (e) { console.error(e); } }
    else cur.cleanup = cleanup;
  } catch (e) {
    if (e && (e.name === "AbortError" || e.status === 401)) return;
    console.error(e);
    put(el, h("div", {class: "errbox"}, "이 화면을 열지 못했습니다. ", h("button", {class: "btn-line", type: "button", onclick: mountScreen}, "다시 시도")));
  }
}
function remount() { mountScreen(); }

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "visible") return;
  pollLeague();
  if (cur) cur.timers.forEach((t) => t.tick && t.tick());
});
window.addEventListener("hashchange", mountScreen);

// keys: / 찾기, , 설정, Esc closes what is open (never while typing in a field)
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    if (findOpen()) closeFind(); else if (settingsOpen()) closeSettings(); else closePop();
    return;
  }
  if (e.ctrlKey || e.metaKey || e.altKey || e.isComposing) return;
  const t = e.target;
  if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
  if (e.key === "/" && !findOpen()) { e.preventDefault(); closeSettings(true); openFind(); }
  else if (e.key === "," && !settingsOpen() && !findOpen()) { e.preventDefault(); openSettings(); }
});

// a table wider than its box gets .cl-more (cl.css: on a phone its first column stays and a line says it scrolls)
let wideTimer = 0;
function markWide() {
  clearTimeout(wideTimer);
  wideTimer = setTimeout(() => {
    for (const w of main.querySelectorAll(".tbl-wrap")) w.classList.toggle("cl-more", w.scrollWidth > w.clientWidth + 2);
  }, 150);
}
new MutationObserver(markWide).observe(main, {childList: true, subtree: true});
window.addEventListener("resize", markWide);

setFindScreens(MENU.map((m) => ({id: m.id, ko: m.ko, group: m.group, groupKo: groupKo(m.group), title: MENU_TITLE[m.id]})));
setSettingsHooks({screens: MENU.map((m) => ({id: m.id, ko: m.ko})), autoStart, remount, onNav});
onAfterChange(() => remount());
applySkin(skinNow());
buildTop();
buildMenu();
paintTop();
pollLeague();
setInterval(() => { if (document.visibilityState !== "hidden") pollLeague(); }, 30000);
setInterval(() => { if (document.visibilityState !== "hidden") paintTop(); }, 60000);
mountScreen();

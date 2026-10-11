// 후보 리그 dashboard shell, in the rule bot's v4 look (the demo lab's shell, simplified): the grouped menu (plain Korean
// text buttons; on top or, by choice, a left column from 1000 px), hash routes, the top bar (글자 크기, 화면 색, 메뉴 위치,
// the D+n pill with the checkpoint dates, the engine dot), the "마지막 갱신" stamp, and one shared copy of the engine's
// snapshot (/api/league every 30 s, paused while the page is hidden) that every screen reads.
// Screens: js/screens/<name>.js with mount(el, ctx) (returning an optional cleanup). A route is #/<screen>[/<arg>][?query].
import {h, put} from "./dom.js";
import {getJSON} from "./api.js";
import * as fmt from "./fmt.js";
import {stamp, setPage} from "./ui.js";
import {applySkin, skinNow, textSwitch, skinSwitch, navSwitch} from "./prefs.js";
import {setLeague, getMeta, leagueDay, health} from "./lk.js";

const MENU = [
  {id: "home", ko: "요약", group: "main"},
  {id: "check", ko: "점검 진행", group: "main"},
  {id: "rank", ko: "순위표", group: "main", also: ["account"]},
  {id: "compare", ko: "5계좌 비교", group: "main"},
  {id: "custom", ko: "커스텀값", group: "detail"},
  {id: "strategies", ko: "매매법", group: "detail"},
  {id: "weekly", ko: "주간 흐름", group: "detail"},
  {id: "terminal", ko: "터미널", group: "live"},
  {id: "entries", ko: "진입 차트", group: "live"},
  {id: "positions", ko: "포지션", group: "live"},
  {id: "fills", ko: "체결 기록", group: "live"},
  {id: "status", ko: "서버 상태", group: "info"},
  {id: "howto", ko: "읽는 법", group: "info"},
];
const GROUPS = [{id: "main", ko: "요약 · 점검"}, {id: "detail", ko: "매매법 · 커스텀값"}, {id: "live", ko: "실시간"},
  {id: "info", ko: "상태 · 안내"}];
const MENU_TITLE = {home: "요약 (첫 화면)", check: "점검 진행 (11/11 · 12/11 · 1/11 기준이 지금 어떤지)",
  rank: "순위표 (후보 38개와 비교 계좌)", compare: "5계좌 비교 (후보 · 1/4 · 청산만 · 기본값 · 동전)",
  custom: "커스텀값 (기본값과 바뀐 숫자, 익절·손절)", strategies: "매매법 (16개 매매법 설명과 묶음 성적)",
  weekly: "주간 흐름 (주마다 후보 · 기본값 · 동전)", entries: "진입 차트 (매매법마다 따로, 후보가 들어간 자리)", howto: "읽는 법 (계좌 5개, 점검 규칙, 낱말 뜻)"};
const SCREENS = {home: "home", check: "check", rank: "rank", compare: "compare", custom: "custom", strategies: "strategies",
  weekly: "weekly", terminal: "terminal", entries: "entries", positions: "positions", fills: "fills", status: "status", howto: "howto",
  account: "account"};
const TITLE = "후보 리그";
const START = "home";

// ---------------------------------------------------------------- the menu
const menu = document.getElementById("menu");
const links = {};
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
  put(menu, kids, h("span", {class: "strip-tools cl-striptools"}, textSwitch(remount), skinSwitch(onSkin), navSwitch(() => { buildMenu(); remount(); })));
  if (cur) markMenu(cur.name);
}
function markMenu(name) {
  for (const m of MENU) {
    const a = links[m.id];
    if (!a) continue;
    const on = m.id === name || (m.also || []).includes(name);
    if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    if (on && menu.scrollWidth > menu.clientWidth + 1) {
      const r = a.getBoundingClientRect(), mr = menu.getBoundingClientRect();
      if (r.left < mr.left || r.right > mr.right) menu.scrollLeft += r.left - mr.left - 16;
    }
  }
}
function onSkin() { applySkin(skinNow()); remount(); }

// ---------------------------------------------------------------- the top bar
const tools = document.getElementById("toptools");
put(tools, h("span", {class: "tt-set cl-tt"}, textSwitch(remount), skinSwitch(onSkin), navSwitch(() => { buildMenu(); remount(); })));
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
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closePop(); });
window.addEventListener("hashchange", closePop);

let doc = null;
function pillPanel() {
  const w = doc && doc.watch;
  const cps = w ? w.checkpoints : [];
  const next = cps.find((c) => c.days_left > 0);
  return h("div", {class: "stack tight"},
    h("p", {class: "tb-lead"}, next ? `다음: ${next.ko} ${fmt.mmdd(next.ms)} (${Math.ceil(next.days_left)}일 남음)` : "점검 일정 준비 중"),
    h("ol", {class: "steps dl-steps", "aria-label": "점검 일정"},
      h("li", {class: "done"}, "10/01 다시 돌리기 시작"), h("li", {class: "done"}, "10/11 설치"),
      cps.map((c) => h("li", {class: c === next ? "now" : c.days_left <= 0 ? "done" : "", "aria-current": c === next ? "step" : null},
        `${c.ko} ${fmt.mmdd(c.ms)}`))),
    h("dl", {class: "kv"},
      h("div", null, h("dt", null, "처리한 시각"), h("dd", null, doc ? `${fmt.kst(doc.done_ms)} KST` : "—")),
      h("div", null, h("dt", null, "10/01부터"), h("dd", null, doc ? `${leagueDay(doc)}일째` : "—"))),
    h("p", {class: "note"}, "점검 날짜와 기준은 시작 전에 고정했습니다 (WATCH_PREREG). 엔진은 5분마다 이어서 계산합니다."),
    h("div", {class: "row wrap"}, h("a", {class: "btn-line", href: "#/check"}, "점검 진행"), h("a", {class: "btn-line", href: "#/howto"}, "읽는 법")));
}
function paintTop() {
  const H = health(doc);
  hdot.dataset.level = H.lv;
  hdot.setAttribute("aria-label", `엔진 상태: ${H.ko} (누르면 서버 상태 화면)`);
  hdot.title = `엔진 상태: ${H.ko}`;
  if (!doc || !doc.accounts) { put(pill, h("b", null, "준비 중")); return; }
  const cps = (doc.watch && doc.watch.checkpoints) || [];
  const next = cps.find((c) => c.days_left > 0);
  put(pill, h("b", null, `D+${leagueDay(doc)}`),
    next ? h("span", {class: "opt"}, ` · ${next.ko} ${fmt.mmdd(next.ms)}`) : null,
    next ? h("span", {class: "obs"}, ` · ${Math.ceil(next.days_left)}일 남음`) : null,
    h("span", {class: "car", "aria-hidden": "true"}, "▾"));
  pill.setAttribute("aria-label", `10월 1일부터 ${leagueDay(doc)}일째${next ? `, 다음 ${next.ko} ${fmt.mmdd(next.ms)}` : ""}. 누르면 일정`);
}
hdot.addEventListener("click", () => { location.hash = "#/status"; });

// ---------------------------------------------------------------- the shared snapshot
const fns = new Set();
function touch() { stamp.textContent = `마지막 갱신 ${fmt.hms(Date.now())} KST`; stamp.title = "이 화면이 서버에서 자료를 마지막으로 받은 시각 (한국 시간)"; }
async function pollLeague() {
  try {
    const d = await getJSON("/api/league");
    touch();
    if (!doc || !d.accounts || d.generated_ms !== doc.generated_ms || d.done_ms !== doc.done_ms) {
      doc = d;
      setLeague(d);
      paintTop();
      for (const fn of fns) { try { fn(d); } catch (e) { console.error(e); } }
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
  const name = SCREENS[parts[0]] ? parts[0] : START;
  const dec = (x) => { try { return decodeURIComponent(x); } catch (e) { return null; } };
  return {name, arg: parts[1] ? dec(parts[1]) : null, query: Object.fromEntries(new URLSearchParams(qs || ""))};
}
function makeCtx(params) {
  const ctl = new AbortController();
  const timers = [];
  const ctx = {
    params,
    signal: ctl.signal,
    alive: () => !ctl.signal.aborted,
    async api(path) { const d = await getJSON(path, ctl.signal); if (!ctl.signal.aborted) touch(); return d; },
    meta: () => getMeta(),
    /** fn(doc) now (when the snapshot is here) and after every new snapshot, until the screen closes. */
    onLeague(fn) {
      fns.add(fn);
      ctl.signal.addEventListener("abort", () => fns.delete(fn));
      if (doc) fn(doc); else pollLeague();
    },
    every(ms, fn) {
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
  put(main, el);
  const {ctx, ctl, timers} = makeCtx(params);
  cur = {name: params.name, ctl, timers, el, cleanup: null};
  ctx.setTitle(entry ? entry.ko : null);
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
  pollLeague();
  if (cur) cur.timers.forEach((t) => t.tick && t.tick());
});
window.addEventListener("hashchange", mountScreen);

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

applySkin(skinNow());
buildMenu();
paintTop();
pollLeague();
setInterval(() => { if (document.visibilityState !== "hidden") pollLeague(); }, 30000);
setInterval(() => { if (document.visibilityState !== "hidden") paintTop(); }, 60000);
mountScreen();

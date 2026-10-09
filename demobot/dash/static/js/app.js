// The shell: the top menu (plain Korean text buttons like the rule bot's), hash routes, the skin switch, the server
// state dot and chip (/api/status every 30 s), the "마지막 갱신" stamp, and each screen's polling (paused while the page
// is hidden). Screens: js/screens/<name>.js with mount(el, ctx) (returning an optional cleanup).
import {h, put, local} from "./dom.js";
import {getJSON, isMissing} from "./api.js";
import {hms, kst, dur} from "./fmt.js";
import {stamp} from "./ui.js";
import {PHASE_KO} from "./labels.js";

const MENU = [
  {id: "home", ko: "홈"},
  {id: "rank", ko: "순위표"},
  {id: "accounts", ko: "계좌", also: ["account"]},
  {id: "trades", ko: "거래 기록"},
  {id: "judge", ko: "판정"},
  {id: "views", ko: "관점 기록"},
  {id: "status", ko: "서버 상태"},
  {id: "howto", ko: "어떻게 돌아가나"},
];
const SCREENS = {home: "home", rank: "rank", accounts: "accounts", account: "account", trades: "trades", judge: "judge",
  views: "views", status: "status", howto: "howto"};
const TITLE = "데모 랩";

// ---------------------------------------------------------------- skin (two skins of tokens.css, per device)
const SKINS = [{id: "ai", ko: "AI"}, {id: "classic", ko: "클래식"}];
function applySkin(id) {
  const root = document.documentElement;
  root.dataset.skin = SKINS.some((x) => x.id === id) ? id : "ai";
  const meta = document.querySelector('meta[name="theme-color"]');
  const bg = getComputedStyle(root).getPropertyValue("--bg").trim();
  if (meta && bg) meta.setAttribute("content", bg);
}
function skinSwitch() {
  const cur = document.documentElement.dataset.skin || "ai";
  const btns = SKINS.map((x) => h("button", {type: "button", "aria-pressed": String(x.id === cur), dataset: {skin: x.id},
    onclick: () => {
      if (document.documentElement.dataset.skin === x.id) return;
      local.set("skin", x.id);
      applySkin(x.id);
      for (const b of btns) b.setAttribute("aria-pressed", String(b.dataset.skin === x.id));
      remount();                                  // charts read their colours when drawn
    }}, x.ko));
  return h("span", {class: "skinsw", role: "group", "aria-label": "화면 색 고르기", title: "화면 색: 이 기기에만 기억합니다"},
    h("span", {class: "k"}, "화면 색"), btns);
}

// ---------------------------------------------------------------- the menu
const menu = document.getElementById("menu");
const links = {};
function buildMenu() {
  const items = MENU.map((m) => {
    const a = h("a", {class: "sb", href: `#/${m.id}`, dataset: {screen: m.id}}, h("span", {class: "sb-t", dataset: {t: m.ko}}, m.ko));
    links[m.id] = a;
    return a;
  });
  put(menu, items, h("span", {class: "strip-tools"}, skinSwitch()));
}
function markMenu(name) {
  for (const m of MENU) {
    const on = m.id === name || (m.also || []).includes(name);
    if (on) links[m.id].setAttribute("aria-current", "page"); else links[m.id].removeAttribute("aria-current");
    if (on && links[m.id].scrollIntoView && menu.scrollWidth > menu.clientWidth) {
      const r = links[m.id].getBoundingClientRect(), mr = menu.getBoundingClientRect();
      if (r.left < mr.left || r.right > mr.right) menu.scrollLeft += r.left - mr.left - 16;
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

// ---------------------------------------------------------------- server state: the dot and the chip (every 30 s)
const statusFns = new Set();
let statusNow = null;
const hdot = document.getElementById("hdot");
const chip = document.getElementById("livechip");
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
  if (!st || isMissing(st)) { put(chip, h("b", null, "준비 중")); return; }
  if (st.phase === "live" && st.live_start_ms) {
    const days = (Date.now() - st.live_start_ms) / 86400000;
    put(chip, h("span", {class: "opt"}, "실시간"), h("b", null, `${Math.max(0, days).toFixed(1)}일째`));
    chip.title = `실시간 시작 ${kst(st.live_start_ms)} KST`;
  } else {
    put(chip, h("b", null, PHASE_KO[st.phase] || "—"));
    chip.title = "";
  }
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
  const name = SCREENS[parts[0]] ? parts[0] : "home";
  const query = Object.fromEntries(new URLSearchParams(qs || ""));
  return {name, arg: parts[1] ? decodeURIComponent(parts[1]) : null, query};
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
    href: (name, arg, q) => `#/${name}${arg ? "/" + encodeURIComponent(arg) : ""}${q && Object.keys(q).length ? "?" + new URLSearchParams(q) : ""}`,
    /** change the hash's query without remounting (a filter the viewer can bookmark) */
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

buildMenu();
applySkin(document.documentElement.dataset.skin || local.get("skin", "ai"));
pollStatus();
setInterval(() => { if (document.visibilityState !== "hidden") pollStatus(); }, 30000);
mountScreen();

// Hash router: #/<screen>/<arg>?k=v. Loads screens/<name>.js (ES module) and screens/<name>.css on first use, calls
// mount(el, ctx) / unmount(), or update(params) when only the argument changed and the screen exports update().
// ctx (CONTRACT.md) cleans up after the screen: its fetches are aborted, its watchers, bus handlers, polls removed.
import {h, clear, on as domOn} from "./dom.js";
import {api, post, bus, poll} from "./api.js";
import {store} from "./store.js";
import {features} from "./features.js";
import {SCREENS, DEFAULT, LANDING_MIN_PX, parseHash, href, landing} from "./routes.js";
import {swap, shimmer} from "./motion.js";
import {errorBox, toast} from "./ui.js";
import {peekGo} from "./drawer.js";

const cssLoaded = new Set();
export function loadCss(name) {
  if (cssLoaded.has(name)) return Promise.resolve();
  cssLoaded.add(name);
  return new Promise((ok) => {
    const l = document.createElement("link");
    // relative to this module: the page's own versioned folder (/static/v-<ver>/v4/, dash/assets.py), kept for a year
    l.rel = "stylesheet"; l.href = new URL(`../screens/${name}.css`, import.meta.url).href;
    l.onload = () => ok(); l.onerror = () => ok();         // a screen without its own css still works
    document.head.appendChild(l);
  });
}

const cur = {name: null, arg: null, mod: null, ctx: null, el: null, token: 0};

export function makeCtx(name, params) {
  const ac = new AbortController();
  const disposers = [];
  let alive = true;
  const track = (fn) => { if (typeof fn === "function") disposers.push(fn); return fn; };
  const ctx = {
    name, params,
    signal: ac.signal,
    alive: () => alive,
    go: (n, a, q) => { if (!peekGo(n, a, q)) location.hash = href(n, a, q); },
    href,
    api: (path) => api(path, {signal: ac.signal}),
    post: (path, body) => post(path, body, {signal: ac.signal}),
    store,
    features,
    watch: (key, fn) => track(store.watch(key, (v, k, err) => { if (alive) fn(v, k, err); })),
    on: (evt, fn) => track(bus.on(evt, (d) => { if (alive) fn(d); })),
    listen: (el, evt, fn, opts) => track(domOn(el, evt, fn, opts)),
    every: (ms, fn, opts) => track(poll(() => alive && fn(), ms, opts)),
    timeout: (fn, ms) => { const t = setTimeout(() => alive && fn(), ms); track(() => clearTimeout(t)); return t; },
    track,
    toast,
    setTitle: (t) => { document.title = t ? `${t} · Paper v4` : "Paper v4"; },
    _dispose() {
      alive = false;
      ac.abort();
      for (const fn of disposers.splice(0).reverse()) { try { fn(); } catch (e) { console.error(e); } }
    },
  };
  return ctx;
}

async function show(params) {
  let {name} = params;
  let meta = SCREENS[name];
  if (!meta) { name = DEFAULT; meta = SCREENS[name]; params = {...params, name, arg: null}; }
  if (meta.feature && (features.probed || meta.feature === "wide") && !features[meta.feature]) {
    // a PC screen on a narrow window goes to the start screen there (the 차트 screen: landing() never answers a
    // switched-off screen, so this cannot loop); any other switched-off screen to 홈
    const to = meta.feature === "wide" ? landing() : DEFAULT;
    toast(meta.feature === "wide" ? `${meta.ko}: PC 화면 (창이 좁아 ${SCREENS[to].ko} 화면으로 갑니다)` : `${meta.ko}: 아직 켜지지 않은 기능입니다`);
    location.replace(href(to));
    return;
  }
  // same screen, new argument: let the screen update in place when it can
  if (cur.name === name && cur.mod && typeof cur.mod.update === "function") {
    cur.ctx.params = params;
    try { await cur.mod.update(params); } catch (e) { console.error(e); }
    bus.emit("route", {name, params});
    return;
  }
  const token = ++cur.token;
  // leave the old screen
  if (cur.mod) {
    try { cur.mod.unmount && cur.mod.unmount(); } catch (e) { console.error(e); }
  }
  if (cur.ctx) cur.ctx._dispose();
  cur.mod = null; cur.ctx = null;
  const main = document.getElementById("screen");
  clear(main);
  const el = h("div", {class: "scr", "data-screen": name});
  main.append(el);
  el.append(shimmer(4, true));
  cur.name = name; cur.arg = params.arg; cur.el = el;
  document.title = `${meta.title || meta.ko} · Paper v4`;
  bus.emit("route", {name, params});
  window.scrollTo(0, 0);
  let imported = false;
  try {
    const [mod] = await Promise.all([import(`../screens/${name}.js`).then((m) => { imported = true; return m; }), loadCss(name)]);
    if (token !== cur.token) return;
    const ctx = makeCtx(name, params);
    cur.mod = mod; cur.ctx = ctx;
    clear(el);
    await mod.mount(el, ctx);
    if (token === cur.token) swap(el);
  } catch (e) {
    if (token !== cur.token) return;
    console.error(e);
    clear(el);
    // tries again by itself; one memo per screen, since every try draws a new screen element. A screen FILE that did
    // not arrive (the dashboard restarting for an update, the connection down) is remembered as failed by the browser
    // until the page loads again, so asking again would fail forever: that box loads the page again (the same
    // #/screen) once the server answers, never into a server that is down, and at most once per screen in 2 minutes
    el.append(fileFailed(e, imported) ? reloadBox(e, name) : errorBox(e, () => show(params), {id: "screen:" + name}));
  }
}
const RELOAD_KEY = "pb4-screen-reload:";
/** A dynamic import that failed to fetch (not a mistake in the screen's code, which a reload would not mend). */
const fileFailed = (e, imported) => !imported && e instanceof TypeError && /module|import/i.test(String(e.message));
function reloadBox(e, name) {
  let last = 0;
  try { last = Number(sessionStorage.getItem(RELOAD_KEY + name)) || 0; } catch (x) { /* no storage */ }
  if (Date.now() - last < 120000) return errorBox(e, () => location.reload());       // just tried: the button only
  return errorBox(e, () => api("/api/time").then(() => {
    try { sessionStorage.setItem(RELOAD_KEY + name, String(Date.now())); } catch (x) { /* no storage */ }
    location.reload();
  }), {id: "screen:" + name, auto: true});
}

export function startRouter() {
  const go = () => show(parseHash(location.hash));
  window.addEventListener("hashchange", go);
  // an address without a screen name (/ or #/) shows the start screen of the window's width (routes.js landing()): when
  // the window is resized across that width, the screen follows, so the menu never lights one screen while another is
  // on view (and a PC 터미널 never stays on a window too narrow for it)
  const startMoved = () => !String(location.hash).replace(/^#\/?/, "").split(/[/?]/)[0] && cur.name && cur.name !== landing();
  bus.on("features", () => {
    const p = parseHash(location.hash), meta = SCREENS[p.name];
    if ((meta && meta.feature && !features[meta.feature]) || startMoved()) go();
  });
  if (typeof matchMedia === "function") {
    const mq = matchMedia(`(min-width: ${LANDING_MIN_PX}px)`);
    if (mq.addEventListener) mq.addEventListener("change", () => { if (startMoved()) go(); });
  }
  go();
}
export const currentScreen = () => cur.name;
/** Draw the current screen again from scratch (a skin switch: charts read their colours from the tokens when drawn). */
export function remount() {
  cur.name = null;
  show(parseHash(location.hash));
}

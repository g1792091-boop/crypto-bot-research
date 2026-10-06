// The side panel (owners 10/06: "들어가서 보는게 귀찮다"): a click on an account, a strategy or a closed trade anywhere
// (순위표, 홈 lists, 포지션, the 터미널's tables, ...) opens its summary in a panel on the right (about 520 px on a PC, a
// full sheet on a phone) instead of leaving the page: summary, a small chart with its entries and exits, the open
// position, the last trades, and '전체 화면으로' to the full page. Esc, a click outside, ✕ and the browser / phone back
// button close it (the panel adds one history entry, so back closes the panel and never leaves the page).
// How a link becomes a panel: one capture-phase click listener for links "#/account/<id>", "#/strategies/<name>" and
// "#/replay/<trade id>" inside the screen (routes.js PEEKABLE), and ctx.go() of every screen (core/router.js asks
// peekGo first). A link to the screen that is already open keeps its normal meaning (the account page's own links).
// The panel's content: screens/account-peek.js (loaded on first use, with the account page's css).
// HONESTY (CONTRACT §1): the panel shows DeepSeek / coin-flip money only inside that group's own view (derive.countOnlyIn
// with the view the link was clicked in: the screen's ?g= filter, else a mixed list).
import {h, $} from "./dom.js";
import {parseHash, PEEKABLE} from "./routes.js";
import {makeCtx, loadCss} from "./router.js";
import {shimmer} from "./motion.js";
import {errorBox} from "./ui.js";

const st = {open: false, spec: null, ctx: null, opener: null, pending: null, gen: 0, hideT: null};
let ui = null;

const curName = () => parseHash(location.hash).name;
/** The group the current screen is filtered to ("all" when none): a link clicked there opens with that view. */
const viewNow = () => { const g = parseHash(location.hash).query.g; return g || "all"; };

/** {kind, id, full, view} for a route that opens in the panel, else null. fromPanel: links inside the panel always
 *  swap it (an account's strategy, a strategy's account); on the page, a link to the screen already open keeps its
 *  normal meaning. */
export function peekSpec(name, arg, query, fromPanel) {
  const kind = PEEKABLE[name];
  if (!kind || arg == null || arg === "") return null;
  if (kind === "trade" && !/^\d+$/.test(String(arg))) return null;
  if (!fromPanel && curName() === name) return null;
  const q = query && Object.keys(query).length ? "?" + new URLSearchParams(query).toString() : "";
  return {kind, id: String(arg), full: `#/${encodeURIComponent(name)}/${encodeURIComponent(arg)}${q}`, view: (st.open && st.spec && st.spec.view) || viewNow()};
}

function build() {
  if (ui) return ui;
  const title = h("h2", {id: "peek-t", class: "peek-title"}, "");
  const kind = h("span", {class: "peek-kind"});
  const sub = h("p", {class: "peek-sub"});
  const full = h("a", {class: "peek-full", href: "#/home", dataset: {full: "1"}}, "전체 화면으로", h("span", {"aria-hidden": "true"}, " ↗"));
  const x = h("button", {type: "button", class: "peek-x", "aria-label": "닫기 (Esc)", title: "닫기 (Esc)", onclick: () => closePeek()}, "✕");
  const pills = h("div", {class: "peek-pills"});
  const body = h("div", {class: "peek-b"});
  const panel = h("aside", {class: "peek", id: "peek", role: "dialog", "aria-modal": "true", "aria-labelledby": "peek-t", hidden: true, tabindex: "-1"},
    h("header", {class: "peek-h"}, h("div", {class: "peek-ht"}, kind, title, sub, pills), h("div", {class: "peek-acts"}, full, x)), body);
  const scrim = h("div", {class: "peek-scrim", hidden: true, "aria-hidden": "true", onclick: () => closePeek()});
  document.body.append(scrim, panel);
  panel.addEventListener("keydown", (e) => {
    if (e.key !== "Tab") return;                         // keep the keyboard inside the panel while it is open
    const f = [...panel.querySelectorAll('a[href], button:not([disabled]), select, input, textarea, [tabindex="0"]')].filter((n) => n.offsetParent !== null);
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });
  ui = {panel, scrim, title, kind, sub, pills, full, x, body};
  return ui;
}

const KIND_KO = {account: "계좌", strategy: "매매법", trade: "거래"};
/** The panel's head, set by the content module. */
function setHead(o = {}) {
  ui.title.textContent = o.title || "";
  ui.sub.textContent = o.sub || "";
  ui.pills.replaceChildren(...(o.pills || []).filter(Boolean));
  ui.kind.textContent = o.kind || KIND_KO[st.spec && st.spec.kind] || "";
}

function disposeCtx() {
  if (st.ctx) { try { st.ctx._dispose(); } catch (e) { console.error(e); } st.ctx = null; }
}

/** Open (or swap) the panel. o.history false: it was opened by the browser's own back / forward. */
export async function openPeek(spec, o = {}) {
  if (!spec || !spec.kind) return;
  build();
  if (st.open && st.spec && st.spec.kind === spec.kind && st.spec.id === spec.id) return;
  const was = st.open;
  if (!was) st.opener = document.activeElement;
  if (o.history !== false) {
    try {
      if (was && history.state && history.state.peek) history.replaceState({...history.state, peek: spec}, "");
      else history.pushState({...(history.state || {}), peek: spec}, "");
    } catch (e) { /* history blocked: the panel still opens, back simply leaves the page */ }
  }
  st.open = true; st.spec = spec;
  disposeCtx();
  clearTimeout(st.hideT);
  document.documentElement.classList.add("peek-open");
  ui.panel.hidden = false; ui.scrim.hidden = false;
  requestAnimationFrame(() => { ui.panel.classList.add("in"); ui.scrim.classList.add("in"); });
  ui.full.setAttribute("href", spec.full);
  setHead({title: spec.id});
  ui.body.replaceChildren(shimmer(5, true));
  ui.body.scrollTop = 0;
  if (!was) ui.x.focus({preventScroll: true});
  const gen = ++st.gen;
  let mod;
  try { [mod] = await Promise.all([import("../screens/account-peek.js"), loadCss("account")]); }
  catch (e) { if (gen === st.gen) ui.body.replaceChildren(errorBox(e)); return; }
  if (gen !== st.gen || !st.open) return;
  const ctx = makeCtx("peek", {name: "peek", arg: spec.id, query: {}});
  ctx.setTitle = () => {};                 // the page keeps its own title
  st.ctx = ctx;
  try { await mod.renderPeek(spec, ctx, {setHead, body: ui.body}); }
  catch (e) { if (gen === st.gen && !(e && e.name === "AbortError")) { console.error(e); ui.body.replaceChildren(errorBox(e)); } }
}

/** Hide the panel without touching the history (the history step is handled by the caller). */
function closeUI() {
  if (!st.open) return;
  st.open = false; st.spec = null; st.gen++;
  disposeCtx();
  document.documentElement.classList.remove("peek-open");
  ui.panel.classList.remove("in"); ui.scrim.classList.remove("in");
  st.hideT = setTimeout(() => { if (!st.open) { ui.panel.hidden = true; ui.scrim.hidden = true; ui.body.replaceChildren(); } }, 220);
  const back = st.opener;
  st.opener = null;
  if (back && back.isConnected && typeof back.focus === "function") back.focus({preventScroll: true});
}

/** Close the panel, then run then() (a navigation): the panel's history entry goes first, so the browser's back
 *  button afterwards returns to the page, never to a closed panel. */
export function closePeek(then) {
  if (!st.open) { if (then) then(); return; }
  closeUI();
  if (history.state && history.state.peek) {
    st.pending = then || (() => {});
    history.back();
    // a browser that never answers back() (no entry): run the navigation anyway
    setTimeout(() => { if (st.pending) { const f = st.pending; st.pending = null; f(); } }, 400);
  } else if (then) then();
}
export const peekOpen = () => st.open;

/** ctx.go(name, arg, query) of every screen asks here first: true = handled (panel opened / swapped, or the panel
 *  closed before leaving). */
export function peekGo(name, arg, query) {
  const spec = peekSpec(name, arg, query, st.open);
  if (spec) { openPeek(spec); return true; }
  if (st.open) { const to = `#/${encodeURIComponent(name)}${arg != null && arg !== "" ? "/" + encodeURIComponent(arg) : ""}${query && Object.keys(query).length ? "?" + new URLSearchParams(query).toString() : ""}`; closePeek(() => { location.hash = to; }); return true; }
  return false;
}

export function startDrawer() {
  document.addEventListener("click", (e) => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const a = e.target && e.target.closest ? e.target.closest("a[href]") : null;
    if (!a || (a.target && a.target !== "_self")) return;
    const raw = a.getAttribute("href") || "";
    if (!raw.startsWith("#/")) return;
    const inPanel = !!(ui && ui.panel.contains(a));
    const screen = $("#screen");
    if (!inPanel && !(screen && screen.contains(a))) return;
    const p = parseHash(raw);
    if (inPanel) {
      e.preventDefault(); e.stopPropagation();
      const spec = a.dataset.full ? null : peekSpec(p.name, p.arg, p.query, true);
      if (spec) openPeek(spec);
      else closePeek(() => { if (location.hash !== raw) location.hash = raw; });
      return;
    }
    const spec = peekSpec(p.name, p.arg, p.query, false);
    if (!spec) return;
    e.preventDefault(); e.stopPropagation();
    openPeek(spec);
  }, true);
  window.addEventListener("popstate", (e) => {
    const s = e.state && e.state.peek;
    if (st.pending) { const f = st.pending; st.pending = null; f(); return; }
    if (s && (!st.open || st.spec.kind !== s.kind || st.spec.id !== s.id)) openPeek(s, {history: false});
    else if (!s && st.open) closeUI();
  });
  // a route change while the panel is open (the address bar, a link outside it): the panel goes
  window.addEventListener("hashchange", () => { if (st.open && !(history.state && history.state.peek)) closeUI(); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && st.open && !e.defaultPrevented) { e.preventDefault(); closePeek(); }
  });
}

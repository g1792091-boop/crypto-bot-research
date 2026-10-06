// 찾기 (owners 10/06: fewer clicks): '/' (or the 찾기 button in the top bar) opens one search box that finds any screen,
// strategy or account by its Korean name, its code, or the first consonants of the Korean name (ㅅㅇㅍ → 순위표).
// Enter / a click opens it: a screen as usual, an account or a strategy in the side panel (core/drawer.js). ↑ ↓ move,
// Esc closes. With an empty box it lists the starred strategies / accounts / coins (★ 즐겨찾기, core/favs.js; on a phone
// this is the rail's ★ list) and then the number-key screens (1-9). Data: routes.js and the shared board (store);
// nothing is fetched here. An account found here opens in a mixed view, so a DeepSeek / coin-flip account is counted
// only (CONTRACT §1).
import {h, $} from "./dom.js";
import {SCREENS, GROUPS, KEYS, JOINED, href, screenIcon, navLabel} from "./routes.js";
import {features} from "./features.js";
import {store} from "./store.js";
import {acctName, stratKo, tfKo, GROUP_KO, groupOf} from "./fmt.js";
import {openPeek, closePeek} from "./drawer.js";
import {ALIAS, norm, rank} from "./search.js";
import {favs} from "./favs.js";
import {favItem} from "./favpop.js";

function screenItems() {
  const out = [];
  for (const g of GROUPS) {
    for (const n of g.screens) {
      const m = SCREENS[n];
      if (!m || m.hidden || (m.feature && !features[m.feature])) continue;
      const k = KEYS.indexOf(n);
      // the menu's group caption under the name (성적 for 요약 ...); a screen behind a shared button is found by its name too (도움말)
      const j = JOINED.find((x) => x.screens.includes(n));
      out.push({kind: "screen", id: n, label: m.ko, code: n, words: `${m.title || ""} ${ALIAS[n] || ""}${j ? " " + j.ko : ""}`, sub: navLabel(g.id),
        key: k < 0 ? null : String(k + 1)});
    }
  }
  return out;
}
const OWN = new Set(["strategy", "ds200", "reel"]);
function boardItems() {
  const b = store.get("board");
  const rows = (b && b.accounts) || [];
  const strat = new Map();
  for (const a of rows) if (OWN.has(a.kind) && !strat.has(a.strategy)) {
    strat.set(a.strategy, {kind: "strategy", id: a.strategy, label: stratKo(a.strategy), code: a.strategy, words: GROUP_KO[groupOf(a)] || "", sub: `매매법 · ${GROUP_KO[groupOf(a)] || ""}`});
  }
  const accts = rows.map((a) => ({kind: "account", id: a.account_id, label: acctName(a), code: a.account_id,
    words: `${GROUP_KO[groupOf(a)] || ""} ${tfKo(a.timeframe)}`, sub: `계좌 · ${GROUP_KO[groupOf(a)] || ""}`}));
  return {strats: [...strat.values()], accts};
}

/** Results for a query: screens, strategies and accounts, best first (at most 5 / 6 / 8). */
export function search(qRaw) {
  const q = norm(qRaw);
  const scr = screenItems();
  if (!q) return [...favItems(), ...scr.filter((x) => x.key).sort((x, y) => x.key - y.key)];
  const {strats, accts} = boardItems();
  return [...rank(q, scr, 5), ...rank(q, strats, 6), ...rank(q, accts, 8)];
}

// ---------------------------------------------------------------- the box
const st = {open: false, items: [], at: 0, opener: null};
let box = null, input = null, list = null;
const KIND_KO = {screen: "화면", strategy: "매매법", account: "계좌", coin: "코인"};
/** conv-b: with an empty box the starred strategies, accounts and coins come first (at most 8; core/favs.js). */
function favItems() {
  const f = favs(), board = store.get("board"), out = [];
  for (const kind of ["strategy", "account", "coin"]) {
    for (const id of f[kind]) {
      const it = favItem(kind, id, board);
      out.push({kind, id, label: it.label, code: id, sub: `★ ${it.sub}`, fav: true, href: it.href});
    }
  }
  return out.slice(0, 8);
}

function build() {
  if (box) return;
  input = h("input", {type: "search", class: "find-in", placeholder: "화면 · 매매법 · 계좌 찾기 (한글, 코드, 초성)", "aria-label": "찾기",
    role: "combobox", "aria-expanded": "true", "aria-controls": "find-list", "aria-autocomplete": "list", autocomplete: "off", spellcheck: "false"});
  list = h("ul", {class: "find-list", id: "find-list", role: "listbox", "aria-label": "찾은 것"});
  const foot = h("p", {class: "find-foot"}, "↑↓ 고르기 · Enter 열기 · 계좌와 매매법은 옆 창으로 · 숫자 1-9 = 자주 가는 화면");
  const panel = h("div", {class: "find-box", role: "dialog", "aria-modal": "true", "aria-label": "찾기"},
    h("div", {class: "find-top"}, h("span", {class: "find-ic", "aria-hidden": "true"}, screenIcon("analysis")), input,
      h("button", {type: "button", class: "find-esc", onclick: () => closeFind(), "aria-label": "닫기 (Esc)"}, "Esc")), list, foot);
  box = h("div", {class: "find", hidden: true, onclick: (e) => { if (e.target === box) closeFind(); }}, panel);
  document.body.append(box);
  input.addEventListener("input", () => { st.at = 0; paint(); });
  input.addEventListener("keydown", (e) => {
    if (e.isComposing) return;
    if (e.key === "ArrowDown") { e.preventDefault(); move(1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); move(-1); }
    else if (e.key === "Enter") { e.preventDefault(); pick(st.items[st.at]); }
    else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeFind(); }
    else if (e.key === "Tab") { e.preventDefault(); }
  });
}
function move(d) {
  if (!st.items.length) return;
  st.at = (st.at + d + st.items.length) % st.items.length;
  paint(true);
}
function paint(keepList) {
  if (!keepList) st.items = search(input.value);
  const q = norm(input.value);
  const opts = st.items.map((x, i) => h("li", {id: `find-o${i}`, role: "option", class: ["find-o", x.kind, x.fav ? "fav" : ""], "aria-selected": String(i === st.at),
    onmousedown: (e) => e.preventDefault(), onclick: () => pick(x), onmousemove: () => { if (st.at !== i) { st.at = i; paint(true); } }},
  h("span", {class: "find-k"}, x.kind === "screen" ? screenIcon(x.id) : KIND_KO[x.kind]),
  h("span", {class: "find-t"}, h("b", null, x.label), h("small", null, x.kind === "screen" ? x.sub : `${x.code} · ${x.sub}`)),
  x.key ? h("kbd", null, x.key) : null));
  if (!opts.length) opts.push(h("li", {class: "find-none", role: "option", "aria-disabled": "true"}, q ? "맞는 것이 없습니다" : ""));
  list.replaceChildren(...opts);
  input.setAttribute("aria-activedescendant", st.items.length ? `find-o${st.at}` : "");
  const cur = list.children[st.at];
  if (cur && cur.scrollIntoView) cur.scrollIntoView({block: "nearest"});
}
function pick(x) {
  if (!x) return;
  closeFind(true);
  if (x.kind === "screen") { closePeek(() => { location.hash = href(x.id); }); return; }
  if (x.kind === "coin") { closePeek(() => { location.hash = x.href; }); return; }      // a starred coin: 터미널 / 차트
  const name = x.kind === "account" ? "account" : "strategies";
  openPeek({kind: x.kind, id: x.id, full: href(name, x.id), view: "all"});
}

export function openFind() {
  build();
  if (st.open) { input.focus(); return; }
  st.open = true;
  st.opener = document.activeElement;
  box.hidden = false;
  input.value = "";
  st.at = 0;
  paint();
  input.focus();
  if (!store.get("board")) store.need("board", 120000).then(() => { if (st.open) paint(); }).catch(() => {});
}
export function closeFind(keepFocus) {
  if (!st.open) return;
  st.open = false;
  box.hidden = true;
  const back = st.opener;
  st.opener = null;
  if (!keepFocus && back && back.isConnected && back.focus) back.focus({preventScroll: true});
}
export const findOpen = () => st.open;

/** The 찾기 button in the top bar. */
export function startFind() {
  const b = $("#findbtn");
  if (b) b.addEventListener("click", () => openFind());
}

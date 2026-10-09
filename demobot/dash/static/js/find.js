// 찾기 (round 4, like the rule bot's v4 core/find.js): "/" anywhere (outside a text box) or the 찾기 button opens one
// search box that finds any screen or account by its Korean name, its id (fx-def-S2-15m), or the first consonants of the
// Korean name (ㅅㅇㅍ → 순위표). ↑ ↓ move, Enter or a click opens it, Esc closes. With an empty box it lists the
// starred screens and accounts (★, favs.js) and then the menu's screens. The accounts come from /api/accounts (asked
// once when the box first opens); nothing else is fetched. Text is set as text (h()), never parsed.
import {h, put} from "./dom.js";
import {getJSON, isMissing} from "./api.js";
import {favs} from "./favs.js";
import {KIND_KO, SUB_KO} from "./labels.js";

const CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ";
const norm = (x) => String(x || "").toLowerCase().replace(/[\s·_]+/g, "");
/** The first consonants of the Hangul syllables (others kept): "순위표" -> "ㅅㅇㅍ". */
export function cho(x) {
  let out = "";
  for (const ch of norm(x)) {
    const c = ch.charCodeAt(0);
    out += c >= 0xac00 && c <= 0xd7a3 ? CHO[Math.floor((c - 0xac00) / 588)] : ch;
  }
  return out;
}
const onlyCho = (q) => q.length > 0 && [...q].every((ch) => CHO.includes(ch));

/** Score of one item for a query (0 = no match). */
function score(q, it) {
  const lab = norm(it.label), code = norm(it.code), words = norm(it.words);
  if (lab === q || code === q) return 120;
  if (lab.startsWith(q)) return 100;
  if (lab.includes(q)) return 80;
  if (code.startsWith(q)) return 70;
  if (code.includes(q)) return 60;
  if (onlyCho(q) && cho(it.label).includes(q)) return 55;
  if (words.includes(q)) return 40;
  return 0;
}
function best(q, items, max) {
  return items.map((it, i) => ({it, i, sc: score(q, it)})).filter((x) => x.sc > 0)
    .sort((a, b) => b.sc - a.sc || a.i - b.i).slice(0, max).map((x) => x.it);
}

const st = {open: false, items: [], at: 0, opener: null, accts: null, loading: null, src: null};
let box = null, input = null, list = null;

function accountItems() {
  return (st.accts || []).map((a) => ({kind: "account", id: a.id, label: a.name || a.id, code: a.id, href: `#/account/${encodeURIComponent(a.id)}`,
    words: `${KIND_KO[a.kind] || ""} ${SUB_KO[a.sub] || ""} ${a.short || ""} ${a.tf || ""}`, sub: `계좌 · ${KIND_KO[a.kind] || a.kind || ""}`}));
}
function screenItems() {
  return (st.src ? st.src() : []).map((m) => ({kind: "screen", id: m.id, label: m.ko, code: m.id, href: `#/${m.id}`, words: m.title || "",
    sub: `화면 · ${m.groupKo || ""}`}));
}
/** Results: with an empty box the starred things then the screens; else the best screens and accounts. */
export function search(raw) {
  const q = norm(raw);
  const scr = screenItems(), acc = accountItems();
  if (!q) {
    const f = favs();
    const fav = [...f.page.map((id) => scr.find((x) => x.id === id)), ...f.account.map((id) => acc.find((x) => x.id === id)
      || {kind: "account", id, label: id, code: id, href: `#/account/${encodeURIComponent(id)}`, sub: "계좌"})].filter(Boolean)
      .map((x) => ({...x, fav: true}));
    return [...fav, ...scr.filter((x) => !fav.some((y) => y.kind === "screen" && y.id === x.id))];
  }
  return [...best(q, scr, 8), ...best(q, acc, 10)];
}

function build() {
  if (box) return;
  input = h("input", {type: "search", class: "find-in", placeholder: "화면 · 계좌 찾기 (한글, 이름, 초성)", "aria-label": "찾기",
    role: "combobox", "aria-expanded": "true", "aria-controls": "find-list", "aria-autocomplete": "list", autocomplete: "off", spellcheck: "false"});
  list = h("ul", {class: "find-list", id: "find-list", role: "listbox", "aria-label": "찾은 것"});
  const panel = h("div", {class: "find-box", role: "dialog", "aria-modal": "true", "aria-label": "찾기"},
    h("div", {class: "find-top"}, h("span", {class: "find-ic", "aria-hidden": "true"}, "⌕"), input,
      h("button", {type: "button", class: "find-esc", onclick: () => closeFind(), "aria-label": "닫기 (Esc)"}, "Esc")),
    list, h("p", {class: "find-foot"}, "↑↓ 고르기 · Enter 열기 · Esc 닫기 · 어디서든 / 를 누르면 열립니다"));
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
function paint(keep) {
  if (!keep) st.items = search(input.value);
  const opts = st.items.map((x, i) => h("li", {id: `find-o${i}`, role: "option", class: ["find-o", `k-${x.kind}`], "aria-selected": String(i === st.at),
    onmousedown: (e) => e.preventDefault(), onclick: () => pick(x), onmousemove: () => { if (st.at !== i) { st.at = i; paint(true); } }},
  h("span", {class: "find-k"}, x.fav ? "★" : x.kind === "screen" ? "화면" : "계좌"),
  h("span", {class: "find-t"}, h("b", null, x.label), h("small", null, x.kind === "screen" ? x.sub : `${x.code} · ${x.sub}`))));
  if (!opts.length) opts.push(h("li", {class: "find-none", role: "option", "aria-disabled": "true"},
    st.loading && !st.accts ? "계좌 목록을 읽는 중…" : "맞는 것이 없습니다"));
  put(list, opts);
  input.setAttribute("aria-activedescendant", st.items.length ? `find-o${st.at}` : "");
  const cur = list.children[st.at];
  if (cur && cur.scrollIntoView) cur.scrollIntoView({block: "nearest"});
}
function pick(x) {
  if (!x) return;
  closeFind(true);
  location.hash = x.href;
}

/** initFind(screens) -> wires "/" (screens: () => [{id, ko, groupKo, title}] of the menu). */
export function initFind(screens) {
  st.src = screens;
  document.addEventListener("keydown", (e) => {
    if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey || e.isComposing || st.open) return;
    const t = e.target;
    if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
    e.preventDefault();
    openFind();
  });
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
  if (!st.accts && !st.loading) {
    st.loading = getJSON("/api/accounts").then((d) => { st.accts = isMissing(d) ? [] : d.accounts || []; })
      .catch(() => {}).finally(() => { st.loading = null; if (st.open) paint(); });
  }
}
export function closeFind(keepFocus) {
  if (!st.open) return;
  st.open = false;
  box.hidden = true;
  const back = st.opener;
  st.opener = null;
  if (!keepFocus && back && back.isConnected && back.focus) back.focus({preventScroll: true});
}

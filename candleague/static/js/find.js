// 찾기 (the rule bot's core/find.js, for the 후보 리그): '/' or the 찾기 button opens one box that finds a screen, one of
// the 38 picks or any of the 190 accounts by its Korean name, its code, or the first consonants of the Korean name
// (ㅅㅇㅍ → 순위표). Enter / a click opens it: a screen as usual, a pick or an account on its 계좌 page (an account with
// an open position also offers its 터미널 line). ↑ ↓ move, Esc closes. With an empty box it lists the screens. Data: the
// menu (app.js gives it) and the shared snapshot and meta (lk.js); nothing is fetched here. Labels only: no money.
// Look: demo4b.css .find (the v4 box).
import {h, s} from "./dom.js";
import {league, metaNow, stratKo} from "./lk.js";
import {ROLE_SHORT, KIND_KO, tfKo, coinShort, sideKo} from "./labels.js";

const CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ";
/** "순위표" -> "ㅅㅇㅍ" (other characters as they are). */
export function initials(s) {
  let out = "";
  for (const c of String(s || "")) {
    const k = c.codePointAt(0) - 0xac00;
    out += k >= 0 && k <= 11171 ? CHO[Math.floor(k / 588)] : c;
  }
  return out;
}
export const norm = (s) => String(s || "").toLowerCase().replace(/[\s·_\-./]+/g, "");

/** Score of one item for a query (0 = no match): the name first, then its consonants, then its code and words. */
function score(q, it) {
  const label = norm(it.label), code = norm(it.code), words = norm(it.words);
  if (label.startsWith(q)) return 6;
  if (label.includes(q)) return 5;
  if (initials(label).startsWith(q)) return 4;
  if (initials(label).includes(q)) return 3;
  if (code.startsWith(q)) return 3;
  if (code.includes(q) || words.includes(q)) return 2;
  return 0;
}
export function rank(q, items, n) {
  return items.map((it, i) => ({it, s: score(q, it), i})).filter((x) => x.s > 0)
    .sort((a, b) => b.s - a.s || a.i - b.i).slice(0, n).map((x) => x.it);
}

let SCREENS = [];
/** app.js: the menu's screens [{id, ko, group, groupKo, title}]. */
export function setFindScreens(list) { SCREENS = list || []; }
/** Extra words that find a screen besides its name and title (메인 vs 대조 / 목표 진척도 / 청산 이유 of the exit-structure league). */
const SCREEN_WORDS = {
  versus: "메인 대조 비교 승률 손익비 거래당 순수익 동전 던지기 낙폭 versus",
  goal: "목표 진척도 승률 70 하루 진입 한 달 4배 낙폭 실전 후보 goal",
  reasons: "청산 이유 손절 익절 계단 잠금 규칙 청산 청산당함 강제청산 reasons",
  pairs: "짝 비교 같은 신호 메인 대조 빠른 손절 낫다 못하다 pairs",
  decision: "판정 결정 미리 정한 규칙 사전 등록 통과 실패 대기 표본 부족 우연 보정 홀름 28일 우위 없음 필터 동전 짝 decision",
  conditions: "조건별 성적 요일 시간대 방향 코인 봉 BTC 추세 변동성 보유시간 언제 잘 맞나 탐색 동전 짝 conditions",
  events: "발동 기록 빠른 손절 손절 좁힘 스위칭 구조 무너짐 events",
  judge: "구조 기준 매매법 자체 구조 무너짐 빠른 손절 스위칭 언제 judge",
};

/** The account kinds of the exit-structure league (the snapshot's ``kinds``): one row each, opening 메인 vs 대조. */
function kindItems(d) {
  return (Array.isArray(d && d.kinds) ? d.kinds : []).filter((k) => k && k.role).map((k) => {
    const group = k.group === "main" ? "메인" : k.group === "control" ? "대조" : "연구용";
    return {kind: "kind", id: k.role, href: "#/versus", label: String(k.label_ko || k.short_ko || k.role), code: `${k.suffix || ""} ${k.role}`,
      words: `${k.short_ko || ""} ${group} 종류 계좌`, sub: `종류 · ${group}${k.accounts ? ` · 계좌 ${k.accounts}개` : ""} · 메인 vs 대조에서 보기`};
  });
}

function items() {
  const d = league();
  const meta = metaNow();
  const accts = (d && d.accounts) || [];
  const picks = accts.filter((a) => a.role === "cand").map((a) => ({kind: "pick", id: a.id, href: `#/account/${encodeURIComponent(a.id)}`,
    label: `${stratKo(a.name, meta)} · ${tfKo(a.tf)}`, code: `${a.name} ${a.id}`,
    words: `${KIND_KO[a.kind] || ""} 후보`, sub: `후보 · ${KIND_KO[a.kind] || a.kind} · ${a.id}`}));
  const all = accts.map((a) => {
    const o = a.open;
    const pos = o ? ` · 열림 ${coinShort(o.symbol)} ${sideKo(o.side)}` : "";
    return {kind: "account", id: a.id, href: `#/account/${encodeURIComponent(a.id)}`,
      label: `${stratKo(a.name, meta)} · ${tfKo(a.tf)} · ${ROLE_SHORT[a.role] || a.role}`, code: a.id,
      words: `${KIND_KO[a.kind] || ""} ${ROLE_SHORT[a.role] || ""} ${a.name}`, sub: `계좌 · ${a.id}${pos}`,
      term: o ? `#/terminal?acct=${encodeURIComponent(a.id)}&coin=${encodeURIComponent(String(o.symbol || "").replace(/T$/, ""))}` : null};
  });
  return {picks, all, kinds: kindItems(d)};
}

export function search(raw) {
  const q = norm(raw);
  const scr = SCREENS.map((m) => ({kind: "screen", id: m.id, href: `#/${m.id}`, label: m.ko, code: m.id,
    words: `${m.groupKo || ""} ${m.title || ""} ${SCREEN_WORDS[m.id] || ""}`, sub: m.groupKo || ""}));
  if (!q) return scr;
  const {picks, all, kinds} = items();
  const acc = rank(q, all, 8);
  const out = [...rank(q, scr, 5), ...rank(q, kinds, 3), ...rank(q, picks, 6), ...acc];
  // an account with an open position: its 터미널 line right after it
  return out.flatMap((x) => (x.kind === "account" && x.term ? [x, {...x, kind: "term", href: x.term, sub: `터미널에서 이 포지션 보기 · ${x.id}`}] : [x]));
}

// ---------------------------------------------------------------- the box
const st = {open: false, items: [], at: 0, opener: null};
let box = null, input = null, list = null;
const KIND_LABEL = {screen: "화면", kind: "종류", pick: "후보", account: "계좌", term: "터미널"};
function build() {
  if (box) return;
  input = h("input", {type: "search", class: "find-in", placeholder: "화면 · 후보 · 계좌 찾기 (한글, 코드, 초성)", "aria-label": "찾기",
    role: "combobox", "aria-expanded": "true", "aria-controls": "cl-find-list", "aria-autocomplete": "list", autocomplete: "off", spellcheck: "false"});
  list = h("ul", {class: "find-list", id: "cl-find-list", role: "listbox", "aria-label": "찾은 것"});
  const panel = h("div", {class: "find-box", role: "dialog", "aria-modal": "true", "aria-label": "찾기"},
    h("div", {class: "find-top"}, h("span", {class: "find-ic", "aria-hidden": "true"}, "⌕"), input,
      h("button", {type: "button", class: "find-esc", onclick: () => closeFind(), "aria-label": "닫기 (Esc)"}, "Esc")), list,
    h("p", {class: "find-foot"}, "↑↓ 고르기 · Enter 열기 · 후보와 계좌는 계좌 화면으로 · / 키로 언제든 열기"));
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
  const opts = st.items.map((x, i) => h("li", {id: `cl-find-o${i}`, role: "option", class: ["find-o", `k-${x.kind}`], "aria-selected": String(i === st.at),
    onmousedown: (e) => e.preventDefault(), onclick: () => pick(x), onmousemove: () => { if (st.at !== i) { st.at = i; paint(true); } }},
  h("span", {class: "find-k"}, KIND_LABEL[x.kind] || ""),
  h("span", {class: "find-t"}, h("b", null, x.label), h("small", null, x.sub))));
  if (!opts.length) opts.push(h("li", {class: "find-none", role: "option", "aria-disabled": "true"}, "맞는 것이 없습니다"));
  list.replaceChildren(...opts);
  input.setAttribute("aria-activedescendant", st.items.length ? `cl-find-o${st.at}` : "");
  const cur = list.children[st.at];
  if (cur && cur.scrollIntoView) cur.scrollIntoView({block: "nearest"});
}
function pick(x) {
  if (!x) return;
  closeFind(true);
  location.hash = x.href;
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

/** The pixel lens of the 찾기 buttons (16 x 16, currentColor). */
export function lensIcon() {
  const R = (x, y, w, hh) => s("rect", {x, y, width: w, height: hh});
  return s("svg", {viewBox: "0 0 16 16", fill: "currentColor", "shape-rendering": "crispEdges", "aria-hidden": "true"},
    R(3, 1, 6, 2), R(1, 3, 2, 6), R(9, 3, 2, 6), R(3, 9, 6, 2), R(10, 10, 2, 2), R(12, 12, 3, 3));
}

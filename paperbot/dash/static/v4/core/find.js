// 찾기 (owners 10/06: fewer clicks): '/' (or the 찾기 button in the top bar) opens one search box that finds any screen,
// strategy or account by its Korean name, its code, or the first consonants of the Korean name (ㅅㅇㅍ → 순위표).
// Enter / a click opens it: a screen as usual, an account or a strategy in the side panel (core/drawer.js). ↑ ↓ move,
// Esc closes. With an empty box it lists the number-key screens (1-9). Data: routes.js and the shared board (store);
// nothing is fetched here. An account found here opens in a mixed view, so a DeepSeek / coin-flip account is counted
// only (CONTRACT §1).
import {h, $} from "./dom.js";
import {SCREENS, GROUPS, KEYS, href, screenIcon} from "./routes.js";
import {features} from "./features.js";
import {store} from "./store.js";
import {acctName, stratKo, tfKo, GROUP_KO, groupOf} from "./fmt.js";
import {openPeek, closePeek} from "./drawer.js";

/** Other words people use for a screen (Korean and English). */
const ALIAS = {
  home: "홈 요약 처음 home summary", board: "순위 랭킹 등수 ranking leaderboard board", flow: "흐름 추이 flow",
  checkpoint: "판정 합격 30일 verdict checkpoint", terminal: "터미널 한눈 pc terminal", positions: "포지션 보유 열린 position",
  chart: "차트 캔들 봉 chart candle", market: "시장 코인 시세 펀딩 market", strategies: "매매법 전략 strategy strategies",
  grid: "한눈 지도 격자 grid map", analysis: "분석 analysis", office: "회의실 회의 사무실 office meeting", rooms: "에이전트 방 채팅 room agent",
  digest: "회의 요약 digest", debate: "토론 debate", server: "서버 비용 cpu server cost", alerts: "알림 기록 alert",
  signals: "신호 signal", howto: "어떻게 설명 도움 howto help", faq: "자주 묻는 질문 faq 용어 help",
};
const CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ";
/** The first consonants of the Hangul syllables (other characters kept): "순위표" -> "ㅅㅇㅍ". */
export function chosung(s) {
  let out = "";
  for (const ch of String(s || "")) {
    const c = ch.charCodeAt(0) - 0xac00;
    out += c >= 0 && c < 11172 ? CHO[Math.floor(c / 588)] : ch;
  }
  return out;
}
export const norm = (s) => String(s || "").toLowerCase().replace(/[\s·_\-./@()]+/g, "");
const onlyCho = (q) => /^[ㄱ-ㅎ]+$/.test(q);

/** Score of one entry for a normalized query (0 = no match): name start > word start > anywhere; codes too. */
export function score(q, item) {
  if (!q) return 0;
  const name = norm(item.label), code = norm(item.code), extra = norm(item.words);
  if (onlyCho(q)) { const c = norm(chosung(item.label)); return c.startsWith(q) ? 60 : c.includes(q) ? 40 : 0; }
  if (name === q || code === q) return 100;
  if (name.startsWith(q)) return 80;
  if (code.startsWith(q)) return 75;
  if (name.includes(q)) return 60;
  if (code.includes(q)) return 50;
  if (extra.includes(q)) return 40;
  return 0;
}

function screenItems() {
  const out = [];
  for (const g of GROUPS) {
    for (const n of g.screens) {
      const m = SCREENS[n];
      if (!m || m.hidden || (m.feature && !features[m.feature])) continue;
      const k = KEYS.indexOf(n);
      out.push({kind: "screen", id: n, label: m.ko, code: n, words: `${m.title || ""} ${ALIAS[n] || ""}`, sub: g.ko, key: k < 0 ? null : String(k + 1)});
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
  if (!q) return scr.filter((x) => x.key).sort((x, y) => x.key - y.key);
  const {strats, accts} = boardItems();
  const top = (xs, n) => xs.map((x) => [score(q, x), x]).filter(([s]) => s > 0).sort((p, r) => r[0] - p[0] || p[1].label.localeCompare(r[1].label)).slice(0, n).map(([, x]) => x);
  return [...top(scr, 5), ...top(strats, 6), ...top(accts, 8)];
}

// ---------------------------------------------------------------- the box
const st = {open: false, items: [], at: 0, opener: null};
let box = null, input = null, list = null;
const KIND_KO = {screen: "화면", strategy: "매매법", account: "계좌"};

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
  const opts = st.items.map((x, i) => h("li", {id: `find-o${i}`, role: "option", class: ["find-o", x.kind], "aria-selected": String(i === st.at),
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

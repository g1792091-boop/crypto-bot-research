// ★ 즐겨찾기 list (conv-b): a ★ button opens a small list of the starred strategies, accounts and coins, each one click
// away (a strategy / an account opens its page, a coin the 터미널 on a PC or the 차트 elsewhere). The ★ beside each row
// takes it out again. Closes on a click outside, Esc, a pick or a route change. Data: core/favs.js (per device) and the
// shared board for the names; nothing is fetched here.
// One ★ button per layout (the menu strip, core/strip.js, replaced the group bar the first merge knew): in the left
// rail's foot (favRailBtn; the list opens beside the rail), in the top bar's #toptools on a PC with the menu on top
// (favTopBtn; the list drops down from it), at the end of the menu strip below 1200 px (favTab; the list drops down
// under the header). core/favs.css shows the one that belongs to the layout; all three count the stars live.
import {h, $$} from "./dom.js";
import {bus} from "./api.js";
import {store} from "./store.js";
import {features} from "./features.js";
import {href} from "./routes.js";
import {acctName, stratKo, coin, groupOf, GROUP_KO, tfKo} from "./fmt.js";
import {favs, favCount, starBtn, onFavs, FAV_KINDS, FAV_KO} from "./favs.js";

/** {label, sub, href} of one starred thing (names from the board when it has them). */
export function favItem(kind, id, board) {
  if (kind === "coin") return {label: coin(id), sub: "코인", href: href(features.wide ? "terminal" : "chart", id)};
  const rows = (board && board.accounts) || [];
  if (kind === "account") {
    const a = rows.find((x) => x.account_id === id);
    return {label: a ? acctName(a) : id, sub: a ? `${GROUP_KO[groupOf(a)] || "계좌"} · ${tfKo(a.timeframe)}` : "계좌 (지금 순위표에 없음)", href: href("account", id)};
  }
  const a = rows.find((x) => x.strategy === id);
  return {label: stratKo(id), sub: a ? `매매법 · ${GROUP_KO[groupOf(a)] || ""}` : "매매법", href: href("strategies", id)};
}

const st = {pop: null, btn: null, opener: null};

function paint() {
  const f = favs(), board = store.get("board");
  const n = favCount(f);
  const groups = FAV_KINDS.filter((k) => f[k].length).map((k) => h("div", {class: "favpop-g"},
    h("p", {class: "favpop-k"}, FAV_KO[k], h("span", {class: "num"}, ` ${f[k].length}`)),
    h("ul", {class: "favpop-list"}, f[k].map((id) => {
      const it = favItem(k, id, board);
      return h("li", {class: "favpop-row"}, h("a", {href: it.href, onclick: () => closeFavPop()}, h("b", null, it.label), h("small", null, it.sub)),
        starBtn(k, id, {label: it.label}));
    }))));
  st.pop.replaceChildren(h("div", {class: "favpop-head"}, h("b", null, "★ 즐겨찾기"), h("span", {class: "num muted"}, ` ${n}`), h("span", {class: "grow"}),
    h("button", {type: "button", class: "favpop-x", "aria-label": "닫기 (Esc)", onclick: () => closeFavPop(true)}, "✕")),
  n ? h("div", {class: "favpop-body"}, groups)
    : h("p", {class: "favpop-empty"}, "아직 즐겨찾기가 없습니다. 매매법·계좌 화면과 터미널·차트의 코인 옆 ☆를 누르면 여기에 모입니다."),
  h("p", {class: "favpop-foot"}, "이 기기에만 기억합니다 · 홈 맨 위에도 같은 목록"));
}

/** Where the list sits: beside the rail for the rail's ★ (its bottom edge at the button's), else dropped down from the
 *  button (right edges level on a PC; the full width of the window on a phone). */
function place(anchor) {
  const s = st.pop.style;
  s.left = s.right = s.top = s.bottom = "";
  if (!anchor) return;
  const r = anchor.getBoundingClientRect();
  if (anchor.closest(".rail")) {
    s.left = `${Math.round(r.right + 10)}px`;
    s.bottom = `${Math.max(8, Math.round(window.innerHeight - r.bottom))}px`;
  } else if (window.innerWidth < 600) {
    s.left = "8px"; s.right = "8px"; s.top = `${Math.round(r.bottom + 8)}px`;
  } else {
    s.right = `${Math.max(8, Math.round(window.innerWidth - r.right))}px`; s.top = `${Math.round(r.bottom + 8)}px`;
  }
}

export function openFavPop(anchor) {
  if (!st.pop) {
    st.pop = h("div", {class: "favpop", role: "dialog", "aria-label": "즐겨찾기", hidden: true});
    st.pop.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); closeFavPop(true); } });
    document.body.append(st.pop);
    document.addEventListener("pointerdown", (e) => {
      if (!st.pop.hidden && !st.pop.contains(e.target) && !(e.target.closest && e.target.closest(".favbtn"))) closeFavPop();
    }, true);
    bus.on("route", () => closeFavPop());
  }
  st.opener = anchor || null;
  paint();
  st.pop.hidden = false;
  place(anchor);
  const f = st.pop.querySelector("a, button");
  if (f) f.focus({preventScroll: true});
}
export function closeFavPop(focusBack) {
  if (!st.pop || st.pop.hidden) return;
  st.pop.hidden = true;
  if (focusBack && st.opener && st.opener.isConnected) st.opener.focus({preventScroll: true});
}

function paintBtn() {
  const n = favCount();
  for (const b of $$(".favbtn")) {
    const c = b.querySelector(".favrail-n");
    if (c) c.textContent = n ? String(n) : "";
    b.setAttribute("aria-label", `즐겨찾기 ${n}개 보기`);
  }
}
// a star added or taken anywhere: the rail's count (and the open list) follow at once, list opened or not
onFavs(() => { paintBtn(); if (st.pop && !st.pop.hidden) paint(); });

/** One ★ button (class `favbtn` + `cls`): the star, the count of starred things, the tooltip 즐겨찾기; it opens the
 *  list (and closes it again). Drawn again with the menu on every route (core/shell.js, core/rail.js). */
function favButton(cls, text) {
  const n = favCount();
  const b = h("button", {type: "button", class: ["favbtn", cls], title: "즐겨찾기", "aria-label": `즐겨찾기 ${n}개 보기`, "aria-haspopup": "dialog",
    onclick: (e) => { e.stopPropagation(); if (st.pop && !st.pop.hidden && st.opener === b) closeFavPop(); else openFavPop(b); }},
  h("span", {"aria-hidden": "true"}, "★"), text ? h("span", {class: "favbtn-t"}, text) : null, h("i", {class: "favrail-n num"}, n ? String(n) : ""));
  return b;
}
/** The rail's ★ (core/rail.js draws it on every redraw): a small round button in the rail's foot. */
export const favRailBtn = () => favButton("favrail");
/** The top bar's ★ (#toptools, a PC window with the menu on top: core/shell.js). */
export const favTopBtn = () => favButton("favrail favtop");
/** The ★ at the end of the menu strip below 1200 px (core/shell.js): a text button like the strip's other tools. */
export const favTab = () => favButton("favsub", "즐겨찾기");

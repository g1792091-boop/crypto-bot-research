// ★ 즐겨찾기 in the PC rail (conv-b): a ★ button at the rail's foot opens a small list next to the rail: the starred
// strategies, accounts and coins, each one click away (a strategy / an account opens its page, a coin the 터미널 on a
// PC or the 차트 elsewhere). The ★ beside each row takes it out again. Closes on a click outside, Esc, a pick or a
// route change. Data: core/favs.js (per device) and the shared board for the names; nothing is fetched here.
import {h, $} from "./dom.js";
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

export function openFavPop(anchor) {
  if (!st.pop) {
    st.pop = h("div", {class: "favpop", role: "dialog", "aria-label": "즐겨찾기", hidden: true});
    st.pop.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); closeFavPop(true); } });
    document.body.append(st.pop);
    document.addEventListener("pointerdown", (e) => {
      if (!st.pop.hidden && !st.pop.contains(e.target) && !(e.target.closest && e.target.closest(".favrail"))) closeFavPop();
    }, true);
    bus.on("route", () => closeFavPop());
  }
  st.opener = anchor || null;
  paint();
  st.pop.hidden = false;
  if (anchor) {
    const r = anchor.getBoundingClientRect();
    st.pop.style.left = `${Math.round(r.right + 10)}px`;
    st.pop.style.bottom = `${Math.max(8, Math.round(window.innerHeight - r.bottom))}px`;
  }
  const f = st.pop.querySelector("a, button");
  if (f) f.focus({preventScroll: true});
}
export function closeFavPop(focusBack) {
  if (!st.pop || st.pop.hidden) return;
  st.pop.hidden = true;
  if (focusBack && st.opener && st.opener.isConnected) st.opener.focus({preventScroll: true});
}

function paintBtn() {
  const b = $(".favrail");
  if (!b) return;
  const n = favCount();
  b.querySelector(".favrail-n").textContent = n ? String(n) : "";
  b.setAttribute("aria-label", `즐겨찾기 ${n}개 보기`);
}
// a star added or taken anywhere: the rail's count (and the open list) follow at once, list opened or not
onFavs(() => { paintBtn(); if (st.pop && !st.pop.hidden) paint(); });

/** The rail's ★ (core/rail.js draws it on every redraw). */
export function favRailBtn() {
  const n = favCount();
  const b = h("button", {type: "button", class: "favrail", title: "즐겨찾기", "aria-label": `즐겨찾기 ${n}개 보기`, "aria-haspopup": "dialog",
    onclick: (e) => { e.stopPropagation(); if (st.pop && !st.pop.hidden) closeFavPop(); else openFavPop(b); }},
  h("span", {"aria-hidden": "true"}, "★"), h("i", {class: "favrail-n num"}, n ? String(n) : ""));
  return b;
}

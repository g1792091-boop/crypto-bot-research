// 홈 › ★ 즐겨찾기 strip (conv-b): the starred strategies, accounts and coins in one row under the screen head (scrolls
// sideways inside itself on a phone). Each chip opens its own place: a strategy or an account in the side panel, a coin
// in the 터미널 (PC) or the 차트. Data: core/favs.js (per device), the shared board and ticker (no extra request).
// Numbers: a strategy = the sum of its own timeframe accounts (closed trades, the board's wallet), an account = its
// wallet, a coin = the ticker's price and 24 h change. HONESTY (D10/D11): a DeepSeek strategy / account or a coin flip
// is counted only on 홈 (trades, no money); a strategy or account with few trades carries 표본 적음.
import {h, put, ui, fmt, fav, derive, features} from "../core/pb.js";

const OWN = new Set(["strategy", "ds200", "reel"]);
const SMALL = 20;

/** The chip numbers of one starred strategy / account from the board: {name, sub, ret, trades, countOnly, missing}. */
export function favNumbers(kind, id, board) {
  const rows = (board && board.accounts) || [];
  const init = (board && board.initial) || 5000;
  if (kind === "account") {
    const a = rows.find((x) => x.account_id === id);
    if (!a) return {name: fmt.idName(id), missing: true};
    const co = derive.countOnlyIn(a, "all");
    return {name: fmt.acctName(a), sub: fmt.tfKo(a.timeframe), trades: a.trades || 0, countOnly: co, ret: co ? null : (a.wallet ?? init) / init - 1, a};
  }
  const mine = rows.filter((x) => x.strategy === id && OWN.has(x.kind));
  if (!mine.length) return {name: fmt.stratKo(id), missing: true};
  const co = mine.some((x) => derive.countOnlyIn(x, "all"));
  const wallet = mine.reduce((s, x) => s + (x.wallet ?? init), 0);
  return {name: fmt.stratKo(id), sub: `봉 ${mine.length}개 합`, trades: mine.reduce((s, x) => s + (x.trades || 0), 0), countOnly: co,
    ret: co ? null : wallet / (init * mine.length) - 1};
}

export function favStrip(ctx) {
  const row = h("div", {class: "hf-row", role: "list", "aria-label": "즐겨찾기", "data-noswipe": "1"});
  const count = h("span", {class: "hf-n num"});
  const el = h("section", {class: "hf", "aria-label": "즐겨찾기"},
    h("div", {class: "hf-head"}, h("span", {class: "hf-star", "aria-hidden": "true"}, "★"), h("b", null, "즐겨찾기"), count,
      h("span", {class: "hf-note"}, "이 기기에만 · 매매법·계좌·코인 옆 ☆로 넣고 빼기")), row);
  let board = null, tk = null;
  const chip = (kids, href, title) => h("a", {class: "hf-chip", role: "listitem", href, title}, kids);
  function render() {
    const f = fav.favs();
    const n = fav.favCount(f);
    count.textContent = n ? ` ${n}` : "";
    if (!n) {
      put(row, h("p", {class: "hf-empty"}, "아직 없습니다. 매매법·계좌 화면 머리나 옆 창의 ☆, 터미널·차트의 코인 옆 ☆를 누르면 여기에 모입니다."));
      return;
    }
    const kids = [];
    for (const id of f.strategy) {
      const x = favNumbers("strategy", id, board);
      kids.push(chip([h("span", {class: "hf-k"}, "매매법"), h("b", {class: "hf-nm"}, x.name),
        x.missing ? h("span", {class: "muted"}, "계좌 없음") : x.countOnly ? h("span", {class: "muted num"}, `거래 ${fmt.int(x.trades)}건`)
          : [h("span", {class: ["num hf-v", fmt.tone(x.ret, fmt.pct(x.ret))]}, fmt.pct(x.ret)), h("span", {class: "muted num"}, `${fmt.int(x.trades)}건`)],
        x.missing ? null : ui.smallSample(x.trades, SMALL)], ctx.href("strategies", id), `${x.name} · ${x.sub || ""}${x.countOnly ? " · 딥시크는 홈에서 개수만" : ""}`));
    }
    for (const id of f.account) {
      const x = favNumbers("account", id, board);
      kids.push(chip([h("span", {class: "hf-k"}, "계좌"), h("b", {class: "hf-nm"}, x.name),
        x.missing ? h("span", {class: "muted"}, "지금 없음") : x.countOnly ? h("span", {class: "muted num"}, `거래 ${fmt.int(x.trades)}건`)
          : [h("span", {class: ["num hf-v", fmt.tone(x.ret, fmt.pct(x.ret))]}, fmt.pct(x.ret)), h("span", {class: "muted num"}, `${fmt.int(x.trades)}건`)],
        x.a && x.a.position ? h("span", {class: "hf-pos"}, `● ${fmt.coin(x.a.position.symbol)}`) : null,
        x.missing ? null : ui.smallSample(x.trades, SMALL)], ctx.href("account", id), id));
    }
    for (const sym of f.coin) {
      const t = tk && tk[sym];
      const p = t ? (t.mark ?? t.c) : null;
      kids.push(chip([h("span", {class: "hf-k"}, "코인"), h("b", {class: "hf-nm"}, fmt.coin(sym)),
        h("span", {class: "num hf-v"}, p == null ? "—" : fmt.price(p)),
        t && t.p != null ? h("span", {class: ["num", fmt.tone(t.p, fmt.pctOf(t.p, 2, true))]}, fmt.pctOf(t.p, 2, true)) : null],
      ctx.href(features.wide ? "terminal" : "chart", sym), `${fmt.coin(sym)} ${features.wide ? "터미널" : "차트"} 열기`));
    }
    put(row, kids);
  }
  ctx.watch("board", (b) => { if (b) { board = b; render(); } });
  ctx.watch("ticker", (t) => {
    if (!t || typeof t !== "object") return;
    tk = t;
    if (fav.favs().coin.length) render();
  });
  ctx.track(fav.onFavs(render));
  render();
  return el;
}

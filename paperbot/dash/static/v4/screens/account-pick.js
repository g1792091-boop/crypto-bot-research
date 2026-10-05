// 계좌 helpers (fill-people): the account picker for #/account with no id, and the coin chart's zoom window and its
// marker labels (shorter when the markers are crowded, so '롱 30배' and '익절 잠금 +20%' never pile up).
// HONESTY: the picker shows names, groups, trade counts and whether a position is open: no money (a mixed list with
// DeepSeek and the coin flips, D10/D11).
import {h, ui, fmt, derive} from "../core/pb.js";
import {savedGroup, groupKo} from "./home-shared.js";

export const LEAD_BARS = 40;        // bars before the first trade on the coin
export const IDLE_BARS = 160;       // a coin without trades: the last bars only

/** The visible logical range {from, to} of the coin chart: the first trade on this coin minus LEAD_BARS through now;
 *  null = fit everything (a short series). data: candles ({time} in s, ascending); trades: this coin's trades. */
export function chartWindow(data, trades, step) {
  const n = (data || []).length;
  if (!n) return null;
  const firsts = (trades || []).map((t) => Math.floor(t.entry_time / 1000)).filter(Number.isFinite);
  if (!firsts.length) return n > IDLE_BARS ? {from: n - IDLE_BARS, to: n + 2} : null;
  const e0 = Math.min(...firsts);
  const e = e0 - (e0 % (step || 1));
  let i = data.findIndex((c) => c.time >= e);
  if (i < 0) i = n - 1;
  const from = Math.max(0, i - LEAD_BARS);
  return {from, to: n + 2};
}

/** Marker texts by crowding: full ('롱 30배' / '익절 잠금 +20%'), short ('롱30' / '+20%'), or bare (arrows without
 *  text, exits with the % only). n: trades on the coin; win: the visible window (null = all). */
export function markLabels(n, win) {
  const bars = win ? Math.max(1, win.to - win.from) : 400;
  const per = (n * 2) / bars;                 // markers per visible bar
  const level = n <= 6 && per < 0.12 ? "full" : n <= 16 && per < 0.3 ? "short" : "bare";
  return {
    level,
    entry: (t) => (level === "full" ? `${fmt.sideKo(t.side)} ${fmt.lev(t.leverage)}` : level === "short" ? `${fmt.sideKo(t.side)}${fmt.int(t.leverage)}` : ""),
    exit: (t) => (level === "full" ? `${fmt.reasonKo(t.exit_reason)} ${fmt.pct(t.roe, 0)}` : fmt.pct(t.roe, 0)),
  };
}

/** The default account: the last viewed one when it still exists, else the top of the saved group's ranking. */
export function defaultAccount(board, last) {
  const rows = (board && board.accounts) || [];
  if (last && rows.some((a) => a.account_id === last)) return last;
  const g = savedGroup("board-group");
  const ranked = derive.rankedOnly(board, g === "all" ? "core" : g).rows;
  return ranked.length ? ranked[0].account_id : rows.length ? rows[0].account_id : null;
}

export function accountPicker(ctx, board, o = {}) {
  const rows = [...((board && board.accounts) || [])].sort((x, y) => {
    const gx = ["core", "m5", "extra", "ds", "coin"].indexOf(fmt.groupOf(x)), gy = ["core", "m5", "extra", "ds", "coin"].indexOf(fmt.groupOf(y));
    return gx - gy || fmt.acctName(x).localeCompare(fmt.acctName(y));
  });
  const def = defaultAccount(board, o.last);
  const defRow = rows.find((a) => a.account_id === def);
  const row = (a) => h("a", {class: "lrow click acp-row", role: "listitem", href: ctx.href("account", a.account_id), title: a.account_id},
    h("span", {class: "lname"}, ui.acctLabel(a)),
    h("span", {class: "acp-g"}, groupKo(fmt.groupOf(a))),
    h("span", {class: "meta"}, h("span", null, `거래 ${fmt.int(a.trades || 0)}건`),
      a.position ? h("span", {class: "acp-pos"}, `● ${fmt.coin(a.position.symbol)} ${fmt.sideKo(a.position.side)}`) : h("span", {class: "muted"}, "대기"),
      a.bust ? ui.pill("파산", "bad") : null));
  const list = ui.searchList({size: 12, placeholder: "이름·코드 찾기 (예: V4.3, 돈치안, REEL)", row,
    match: (a, q) => fmt.acctName(a).toLowerCase().includes(q) || String(a.account_id).toLowerCase().includes(q), empty: "맞는 계좌가 없습니다"});
  list.set(rows, false);
  const quick = defRow ? ui.card({plate: o.last === def ? "지난번 본 계좌" : "저장된 묶음의 1위", cls: "acp-quick"},
    h("div", {class: "acp-qrow"}, h("b", null, ui.acctLabel(defRow)), h("span", {class: "muted"}, `${groupKo(fmt.groupOf(defRow))} · 거래 ${fmt.int(defRow.trades || 0)}건`),
      h("span", {class: "grow"}), h("a", {class: "btn-y", href: ctx.href("account", def)}, "이 계좌 열기"))) : null;
  return h("div", {class: "stack acp"}, quick,
    ui.card({plate: "계좌 고르기", sub: `${fmt.int(rows.length)}계좌 · 기존 36 → 5분봉 → 추가 → 딥시크 → 동전 봇 순`}, list.el,
      h("p", {class: "pos-note"}, "이 목록은 이름·거래 수·포지션만 보여 줍니다. 수익은 계좌를 열거나 순위표에서 보세요.")));
}

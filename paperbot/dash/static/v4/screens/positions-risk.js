// 포지션 › 위험 사다리 (거래 채우기): every open position ranked by how far the mark price is from its liquidation
// price and from its stop / lock line, as bars that move with the 5-second server mark. Distances only (no money), so
// DeepSeek and the coin flips stay in the list with their group label (counts and prices are not money: D10/D11).
// A row pulses only for danger: within 0.5 % of its liquidation, or of a stop that would close at a loss. A lock line
// (the stop already on the profit side: touching it closes the trade in profit) is drawn in the up colour as
// '잠금까지' and never pulses. Rows open the account.
import {h, ui, fmt} from "../core/pb.js";
import {nameNode, groupKo} from "./positions-kit.js";

export const LIQ_CAP = 0.10;       // a bar is empty at 10 % or more away from the liquidation price, full at 0
export const STOP_CAP = 0.05;      // the stop bar: full at 0, empty at 5 % or more
export const NEAR = 0.005;         // within 0.5 % of the liquidation or a losing stop: the row pulses
/** A lock line: the stop already sits on the profit side of the entry (touching it closes the trade in profit). */
export const isLock = (pos) => !!pos && pos.stop != null && pos.entry != null && Number(pos.side) * (pos.stop - pos.entry) > 0;
/** Whether a row is in danger: near the liquidation, or near a stop that is not a lock. */
export const danger = (x) => (x.dLiq != null && x.dLiq < NEAR) || (!isLock(x.pos) && x.dStop != null && x.dStop < NEAR);

/** Signed distance from the mark to a price the position must not reach, as a share of the mark: positive = still
 *  away, 0 or less = reached. side > 0 (long): the price falls toward it; side < 0 (short): it rises toward it. */
export function gap(side, mark, line) {
  const m = Number(mark), l = Number(line);
  if (!Number.isFinite(m) || !Number.isFinite(l) || m <= 0 || !l) return null;
  return Number(side) > 0 ? (m - l) / m : (l - m) / m;
}
/** How full a bar is: 1 at the line, 0 at cap or farther. */
export const closeness = (d, cap) => (d == null ? 0 : Math.max(0, Math.min(1, 1 - d / cap)));
/** The ranking: closest to liquidation first, unknown distances last. list: [{pos}], markOf(sym) -> mark. */
export function rankRisk(list, markOf) {
  return list.map((x) => {
    const m = markOf(x.pos.symbol);
    return {...x, dLiq: gap(x.pos.side, m, x.pos.liq), dStop: gap(x.pos.side, m, x.pos.stop)};
  }).sort((a, b) => (a.dLiq ?? 9) - (b.dLiq ?? 9));
}

export function riskLadder(ctx, o = {}) {
  const max = o.max || 12;
  const listEl = h("div", {class: "risk-list", role: "list", "aria-label": "청산까지 가까운 순"});
  const more = h("p", {class: "pos-note"});
  const el = ui.card({plate: "위험 사다리", sub: "청산가·손절선까지 남은 거리 · 가까운 순"},
    h("div", {class: "risk-key"}, h("span", null, h("i", {class: "liq"}), "청산가까지"), h("span", null, h("i", {class: "stop"}), "손절선까지"),
      h("span", null, h("i", {class: "lock"}), "잠금선까지 (닿으면 수익으로 끝남)"),
      h("span", {class: "muted"}, "막대가 찰수록 가까움 · 청산가나 손절선 0.5% 안이면 깜빡임")),
    listEl, more);
  const rows = new Map();          // account_id -> {row, parts}
  const rowOf = (x) => {
    const id = x.a.account_id;
    let r = rows.get(id);
    const key = [x.pos.symbol, x.pos.entry_time, x.pos.liq, x.pos.stop, x.pos.lock_roe].join("|");
    if (r && r.key === key) return r;
    const lock = isLock(x.pos);
    const liqFill = h("i", {class: "liq"}), stopFill = h("i", {class: lock ? "lock" : "stop"});
    const liqTxt = h("b", {class: "num"}, "—"), stopTxt = h("b", {class: "num"}, "—");
    const row = h("a", {class: "risk-row", role: "listitem", href: ctx.href("account", id), title: id},
      h("span", {class: "risk-h"}, ui.sideTag(x.pos.side), h("b", null, fmt.coin(x.pos.symbol)), h("span", {class: "muted"}, fmt.lev(x.pos.leverage)),
        h("span", {class: "risk-n"}, nameNode(x.a)), h("span", {class: "risk-g muted"}, groupKo(x.a))),
      h("span", {class: "risk-b"}, h("span", {class: "risk-bar"}, liqFill), h("span", {class: "risk-t"}, "청산 ", liqTxt)),
      h("span", {class: ["risk-b", lock ? "lock" : ""]}, h("span", {class: "risk-bar"}, stopFill), h("span", {class: "risk-t"}, lock ? "잠금까지 " : "손절 ", stopTxt)));
    r = {key, row, liqFill, stopFill, liqTxt, stopTxt};
    rows.set(id, r);
    return r;
  };
  const paintRow = (r, x) => {
    r.liqFill.style.width = `${(closeness(x.dLiq, LIQ_CAP) * 100).toFixed(1)}%`;
    r.stopFill.style.width = `${(closeness(x.dStop, STOP_CAP) * 100).toFixed(1)}%`;
    r.liqTxt.textContent = x.dLiq == null ? "—" : fmt.pct(x.dLiq, 2, false);
    r.stopTxt.textContent = x.dStop == null ? "—" : x.dStop <= 0 ? "닿음" : fmt.pct(x.dStop, 2, false);
    r.row.classList.toggle("near", danger(x));
  };
  let order = "";
  /** wait: () => node, while there is no board yet (불러오는 중 / 못 불러옴; never '열린 포지션이 없습니다') */
  const set = (list, markOf, wait) => {
    if (wait) { order = "\0wait"; listEl.replaceChildren(wait()); more.textContent = ""; return; }
    const ranked = rankRisk(list, markOf);
    const shown = ranked.slice(0, max);
    const ids = shown.map((x) => x.a.account_id).join(",");
    const rs = shown.map((x) => { const r = rowOf(x); paintRow(r, x); return r.row; });
    if (ids !== order) { order = ids; listEl.replaceChildren(...(rs.length ? rs : [ui.empty("열린 포지션이 없습니다")])); }
    for (const id of [...rows.keys()]) if (!list.some((x) => x.a.account_id === id)) rows.delete(id);
    more.textContent = (ranked.length > max ? `가까운 ${fmt.int(max)}개만 · 전체 ${fmt.int(ranked.length)}개 · ` : "") +
      "거리 = 지금 마크 가격에서 그 가격까지 (%) · 5초마다 서버 시세로 움직임. 누르면 그 계좌로.";
  };
  return {el, set};
}

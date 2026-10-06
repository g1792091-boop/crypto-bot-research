// Our open positions on one coin as chart-deck lines (core/chartfx.js setLines), shared by the terminal chart and the
// 차트 screen (owners 10/06: "선이 너무 크고 투박하다"): one 1 px entry line per price (positions within 0.05 % share
// it) with a compact pill at the left like the reference's 'Short 4 · −1947.39 (−28.27%) · TP · SL':
//   '숏 30배 · 3개 · −2.5% · 잠금 · 손절'
// (the % is the group's unrealized ROE at the mark price, before the exit fee). DeepSeek and coin-flip positions are
// counted on the line but add no money to it (CONTRACT §1, derive.countOnlyIn); a line of only those shows no %.
// Stops / locks are dashed lines of their own (group 손절·잠금), the nearest few to the price, tied to their entry
// line: hiding the entry pill hides them, and the pill's 잠금 / 손절 chips show or hide them.
import {fmt} from "../core/pb.js";
import {normPos, nameOf, countOnly} from "./positions-kit.js";

const NEAR = 0.0005;

/**
 * posLines(accounts, mark, {stops, exclude}) -> [line spec] for chartDeck.setLines
 *   accounts: board accounts whose position is on the coin shown; mark: the coin's mark price (null: no money yet)
 *   stops: how many stop / lock lines at most (the nearest to the price), 0 for none
 */
export function posLines(accounts, mark, o = {}) {
  const list = (accounts || []).map((a) => ({a, p: normPos(a.position)})).filter((x) => x.p && x.p.entry > 0)
    .sort((x, y) => x.p.entry - y.p.entry);
  const groups = [];
  for (const x of list) {
    const g = groups[groups.length - 1];
    if (g && Math.abs(x.p.entry - g.price) / g.price < NEAR) g.items.push(x); else groups.push({price: x.p.entry, items: [x]});
  }
  const out = [], stops = [];
  for (const g of groups) {
    const id = "e:" + g.items.map((x) => x.a.account_id).sort().join(",");
    const money = g.items.filter((x) => !countOnly(x.a, ""));
    const pnl = mark ? money.reduce((s, x) => s + x.p.side * x.p.qty * (mark - x.p.entry), 0) : 0;
    const mg = money.reduce((s, x) => s + (x.p.margin || 0), 0);
    const showM = !!mark && money.length > 0 && mg > 0;
    const L = g.items.filter((x) => x.p.side > 0).length, S = g.items.length - L;
    const levs = new Set(g.items.map((x) => x.p.leverage));
    const side = L && S ? `롱${L}·숏${S}` : L ? "롱" : "숏";
    const head = levs.size === 1 && g.items[0].p.leverage ? `${side} ${fmt.lev(g.items[0].p.leverage)}` : side;
    const n = g.items.length;
    const lockIds = [], stopIds = [];
    for (const x of g.items) {
      if (!x.p.stop) continue;
      const lock = x.p.lock_roe != null && !fmt.ownExits(x.a);
      const sid = `s:${lock ? "l" : "s"}:${x.a.account_id}`;
      stops.push({id: sid, parent: id, price: x.p.stop, lock, d: mark ? Math.abs(x.p.stop - mark) : 0});
      (lock ? lockIds : stopIds).push(sid);
    }
    const names = g.items.slice(0, 4).map((x) => nameOf(x.a)).join(", ") + (n > 4 ? ` 외 ${n - 4}개` : "");
    const ref = money.length < n ? ` · 딥시크·동전 봇 ${n - money.length}개는 개수만` : "";
    out.push({id, group: "pos", price: g.price, tone: showM ? (pnl >= 0 ? "up" : "down") : "flat", dash: 0, alpha: 0.7, axis: true,
      pill: {text: [head, n > 1 ? `${n}개` : null, showM ? fmt.pct(pnl / mg, 1) : null].filter(Boolean).join(" · "),
        short: `${side}${n > 1 ? " " + n + "개" : ""}`,
        title: `진입 ${fmt.price(g.price)} · ${names}${showM ? " · 미실현 ROE (마크 가격, 나갈 때 수수료 전)" : ""}${ref}`,
        chips: [lockIds.length ? {text: "잠금", ids: lockIds, title: "잠금선 보이기·숨기기"} : null,
          stopIds.length ? {text: "손절", ids: stopIds, title: "손절선 보이기·숨기기"} : null].filter(Boolean)}});
  }
  // the nearest stops / locks only (one line per price and kind)
  const keep = [];
  for (const s of stops.sort((a, b) => a.d - b.d)) {
    if (keep.length >= (o.stops ?? 6)) break;
    const same = keep.find((k) => k.lock === s.lock && Math.abs(k.price - s.price) / s.price < NEAR);
    if (same) { same.ids.push(s.id); continue; }
    keep.push({...s, ids: [s.id]});
  }
  for (const s of keep) {
    // a merged stop answers to every id it carries: the first is the line's own, the others are aliases the chips use
    // (count: how many stops this one line stands for, so its right-edge name reads "손절 ×2"; core/edgelabels.js)
    out.push({id: s.id, alias: s.ids.slice(1), parent: s.parent, group: "risk", price: s.price, tone: s.lock ? "up" : "down", dash: 1, alpha: 0.5,
      axis: false, label: s.lock ? "잠금" : "손절", count: s.ids.length});
  }
  return out;
}

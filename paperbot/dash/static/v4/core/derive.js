// Pure calculations on /api/board rows (no DOM, no fetch: tests/test_dash_v4.py runs them in node). One place, so
// 홈, 순위표 and every other screen show the same medians and counts.
import {groupOf} from "./fmt.js";

export function median(xs) {
  const v = xs.filter((x) => x != null && Number.isFinite(x)).sort((a, b) => a - b);
  if (!v.length) return null;
  const m = v.length >> 1;
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
}

const wal = (a, init) => (a.wallet == null ? init : a.wallet);

/**
 * groupStats(board) -> {initial, groups: {core|ds|m5|coin|extra: {n, bust, open, trades, medWallet, medRet,
 *   above, below, vsN, sumWallet, pnl}}, strat: {n, medWallet, medRet, above, below}, coin: {n, medWallet, medRet},
 *   total: {wallet, initial, n}, flipMedByTf}
 * above / below: accounts whose wallet is above / below the median coin flip OF THE SAME TIMEFRAME (참고 only, never a
 * verdict). Late-started extras are never compared (they did not start with the coin flips).
 */
export function groupStats(board) {
  const init = (board && board.initial) || 5000;
  const rows = (board && board.accounts) || [];
  const flipsByTf = {};
  for (const a of rows) if (a.kind === "random") (flipsByTf[a.timeframe] ||= []).push(wal(a, init));
  const flipMedByTf = Object.fromEntries(Object.entries(flipsByTf).map(([tf, ws]) => [tf, median(ws)]));
  const g = {};
  const blank = () => ({n: 0, bust: 0, open: 0, trades: 0, wallets: [], above: 0, below: 0, vsN: 0});
  const strat = blank(), coin = blank();
  let tw = 0, ti = 0;
  for (const a of rows) {
    const id = groupOf(a), w = wal(a, init);
    const x = (g[id] ||= blank());
    for (const t of [x, a.kind === "random" ? coin : id === "extra" ? null : strat]) {
      if (!t) continue;
      t.n++; t.wallets.push(w); t.trades += a.trades || 0;
      if (a.bust) t.bust++;
      if (a.position) t.open++;
      if (a.kind !== "random" && id !== "extra" && flipMedByTf[a.timeframe] != null) {
        t.vsN++;
        if (w > flipMedByTf[a.timeframe]) t.above++; else if (w < flipMedByTf[a.timeframe]) t.below++;
      }
    }
    tw += w; ti += init;
  }
  const fin = (t) => {
    const m = median(t.wallets);
    const sum = t.wallets.reduce((acc, w) => acc + w, 0);
    const out = {n: t.n, bust: t.bust, open: t.open, trades: t.trades, medWallet: m, medRet: m == null ? null : m / init - 1,
      above: t.above, below: t.below, vsN: t.vsN, sumWallet: sum, pnl: sum - t.n * init};
    return out;
  };
  return {initial: init, groups: Object.fromEntries(Object.entries(g).map(([k, v]) => [k, fin(v)])), strat: fin(strat),
    coin: fin(coin), total: {wallet: tw, initial: ti, n: rows.length}, flipMedByTf};
}

/** An account with no closed trade and no open position has no rank yet (day 0: every return is 0.0%, so a rank
 *  would only be the alphabet). It is left out of 상위/하위, 최고 계좌 and the rank memo, and shows "—". */
export const unranked = (a) => !!a && !((a.trades || 0) > 0) && !a.position;

/** Accounts of a group ("all" = every original account) sorted by wallet, best first; unranked ones last. */
export function ranked(board, group = "all") {
  const init = (board && board.initial) || 5000;
  const rows = ((board && board.accounts) || []).filter((a) => group === "all" ? groupOf(a) !== "extra" : groupOf(a) === group);
  return rows.map((a) => ({...a, ret: wal(a, init) / init - 1}))
    .sort((x, y) => (unranked(x) - unranked(y)) || y.ret - x.ret || String(x.account_id).localeCompare(String(y.account_id)));
}

/** The ranked accounts only, and how many have no rank yet: {rows, waiting}. */
export function rankedOnly(board, group = "all") {
  const all = ranked(board, group);
  const rows = all.filter((a) => !unranked(a));
  return {rows, waiting: all.length - rows.length};
}

/** The one muted line for the accounts without a rank yet ('' when none). */
export const waitingKo = (n) => (n > 0 ? `아직 거래 없는 계좌 ${n}개 · 첫 거래 뒤부터 순위` : "");

/** Unrealized P&L of a board position at a mark price: {pnl, roe} (before the exit fee, like the exchange app). */
export function livePnl(pos, mark) {
  if (!pos || !mark || !pos.margin) return null;
  const entry = pos.entry ?? pos.entry_price;
  const pnl = Number(pos.side) * Number(pos.qty) * (Number(mark) - Number(entry));
  return {pnl, roe: pnl / Number(pos.margin), mark: Number(mark)};
}

/** Distance from the entry price to the liquidation price at entry, as a ratio (the why-leverage line). */
export function liqDistance(pos) {
  if (!pos) return null;
  const entry = Number(pos.entry ?? pos.entry_price), liq = Number(pos.liq ?? pos.liq_price);
  if (!entry || !liq) return null;
  return Math.abs(liq - entry) / entry;
}

/** Distance from a mark price to a level as a ratio (stop / liquidation meters). */
export const distTo = (mark, level) => (mark && level ? Math.abs(Number(level) - Number(mark)) / Number(mark) : null);

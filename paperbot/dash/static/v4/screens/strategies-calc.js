// 매매법 (builder C): pure calculations on /api/board rows and /api/account trades (no DOM, no fetch). One strategy's
// live record is the sum of its own timeframe accounts (kind strategy / ds200 / reel; a copy carries its parent's name
// but follows another rule, so it is left out, as in the old strat.js).
import {fmt, bars} from "../core/pb.js";
import {DS_DEFS, REEL, OWN_KINDS} from "./strategies-defs.js";

export const TF_ORDER = fmt.TF_ORDER;
const tfRank = (tf) => { const i = TF_ORDER.indexOf(tf); return i < 0 ? 99 : i; };

/** "core" | "ds" | "m5" for a strategy id (by the board kind when known, else by the name). */
export function groupOfStrategy(name, kind) {
  if (kind === "ds200" || DS_DEFS[name]) return "ds";
  if (kind === "reel" || name === REEL.id) return "m5";
  return "core";
}

/** A strategy's Korean name: the 36 from the strategies list, else fmt.stratKo (board names, DeepSeek, the reel). */
export function nameKo(name, list36) {
  const x = (list36 || []).find((s) => s.strategy === name);
  return x && x.name_ko ? x.name_ko : fmt.stratKo(name);
}

/** The strategy's own timeframe accounts on the board, 5m → 4h. */
export function accountsOf(board, name) {
  return ((board && board.accounts) || []).filter((a) => a.strategy === name && OWN_KINDS.has(a.kind))
    .sort((x, y) => tfRank(x.timeframe) - tfRank(y.timeframe));
}

/** The live record of some accounts: trades, wins, losses, P&L, averages, payoff, break-even win rate. */
export function record(rows, initial = 5000) {
  const r = {n: rows.length, trades: 0, wins: 0, losses: 0, pnl: 0, gw: 0, gl: 0, bust: 0, open: 0, wallet: 0};
  for (const a of rows) {
    r.trades += a.trades || 0; r.wins += a.wins || 0; r.losses += a.losses || 0; r.pnl += a.pnl || 0;
    r.gw += a.gross_win || 0; r.gl += a.gross_loss || 0;
    if (a.bust) r.bust++;
    if (a.position) r.open++;
    r.wallet += a.wallet == null ? initial : a.wallet;
  }
  r.rate = r.trades ? r.wins / r.trades : null;
  r.avgW = r.wins ? r.gw / r.wins : null;
  r.avgL = r.losses ? r.gl / r.losses : null;
  r.ratio = r.avgW != null && r.avgL ? r.avgW / Math.abs(r.avgL) : null;
  // 본전 승률: the win rate at which this average win and loss come out even, |avg loss| / (avg win + |avg loss|)
  r.be = r.avgW != null && r.avgL ? Math.abs(r.avgL) / (r.avgW + Math.abs(r.avgL)) : null;
  r.ret = r.n ? r.wallet / (r.n * initial) - 1 : null;
  return r;
}

/** Every strategy of the run, from the board (+ the 36's styles from /api/strategies). */
export function strategyIndex(board, list36) {
  const by = new Map();
  for (const a of (board && board.accounts) || []) {
    if (!OWN_KINDS.has(a.kind)) continue;
    if (!by.has(a.strategy)) by.set(a.strategy, {id: a.strategy, kind: a.kind, rows: []});
    by.get(a.strategy).rows.push(a);
  }
  // the 36 come in /api/strategies order even before their accounts trade
  const order = (list36 || []).map((s) => s.strategy);
  for (const s of order) if (!by.has(s)) by.set(s, {id: s, kind: "strategy", rows: []});
  const init = (board && board.initial) || 5000;
  const out = [];
  for (const x of by.values()) {
    const meta = (list36 || []).find((s) => s.strategy === x.id) || {};
    const g = groupOfStrategy(x.id, x.kind);
    out.push({id: x.id, kind: x.kind, group: g, ko: nameKo(x.id, list36), fam: DS_DEFS[x.id] ? DS_DEFS[x.id].fam : null,
      style: meta.style || null, rare: !!meta.rare, hold: meta.hold || null,
      tfs: x.rows.map((a) => a.timeframe).sort((p, q) => tfRank(p) - tfRank(q)), rec: record(x.rows, init),
      order: g === "core" ? order.indexOf(x.id) : g === "ds" ? Object.keys(DS_DEFS).indexOf(x.id) : 0});
  }
  return out.sort((p, q) => p.order - q.order);
}

const SES_KO = {asia: "아시아장 09~16시", europe: "유럽장 16~22시", us: "미국장 22~05시", dawn: "새벽 05~09시"};
const SES_ORDER = ["asia", "europe", "us", "dawn"];

/**
 * Wins vs losses of closed trades split four ways: {coin, side, tf, session} -> [{key, ko, n, wins, losses, pnl, rate}].
 * trades: [{symbol, side, entry_time, pnl, _tf}] (the account's timeframe added as _tf). Session = Korea time at entry.
 */
export function splitTrades(trades) {
  const dims = {coin: new Map(), side: new Map(), tf: new Map(), session: new Map()};
  const add = (m, key, ko, t) => {
    if (!m.has(key)) m.set(key, {key, ko, n: 0, wins: 0, losses: 0, pnl: 0});
    const c = m.get(key);
    c.n++; c.pnl += t.pnl || 0;
    if (t.pnl > 0) c.wins++; else if (t.pnl < 0) c.losses++;
  };
  for (const t of trades || []) {
    add(dims.coin, t.symbol, fmt.coin(t.symbol), t);
    add(dims.side, String(t.side > 0 ? 1 : -1), fmt.sideKo(t.side), t);
    if (t._tf) add(dims.tf, t._tf, fmt.tfKo(t._tf), t);
    if (t.entry_time) { const s = bars.session(Number(t.entry_time)); add(dims.session, s.id, SES_KO[s.id], t); }
  }
  const fin = (m, order) => [...m.values()].map((c) => ({...c, rate: c.n ? c.wins / c.n : null}))
    .sort((a, b) => (order ? order(a) - order(b) : b.n - a.n));
  return {
    coin: fin(dims.coin, (c) => bars.TRADE_SYMS.indexOf(c.key)),
    side: fin(dims.side, (c) => -Number(c.key)),
    tf: fin(dims.tf, (c) => tfRank(c.key)),
    session: fin(dims.session, (c) => SES_ORDER.indexOf(c.key)),
    n: (trades || []).length,
  };
}

// 실거래 (#/livebots): the page's arithmetic, pure (no DOM, no imports: tests/test_dash_livebots.py runs it in node). Every
// function returns a plain number / object, or null when the data is not there: the page then shows '—' or omits the
// number, never one it does not have.
//
// ROE at the mark price (the mark is the dashboard's own ticker, Binance's mark price):
//   unrealized  side x qty x (mark - entry), before the exit fee (the terminal's rule: 미실현 = 마크 가격 기준, 나갈 때
//               수수료 전); ROE = that / the margin (the paper's initial margin, the live entry x qty / leverage)
//   paper net   leverage x (side x (mark / entry - 1) - round_trip - funding / notional): the paper engine's own ladder
//               formula (paperbot/ladder.py net_roe), the number its lock steps follow (순ROE 11% -> lock 10%)
//   ladder      the price where the paper's net ROE reaches r: entry x (1 + side x (r / leverage + round_trip + funding frac))

/** Unrealized P&L at a mark (before the exit fee); null without a mark or a position. */
export function unrealized(pos, mark) {
  if (!pos || !(Number(mark) > 0)) return null;
  const entry = Number(pos.entry), qty = Number(pos.qty), side = Number(pos.side);
  if (!(entry > 0) || !(qty > 0) || !side) return null;
  return side * qty * (Number(mark) - entry);
}

/** ROE at a mark (unrealized / margin, before the exit fee); null without a mark, a position or its margin. */
export function roeAt(pos, mark) {
  const u = unrealized(pos, mark);
  const m = pos ? Number(pos.margin) : 0;
  return u == null || !(m > 0) ? null : u / m;
}

/** The paper engine's net ROE at a mark price; null without a mark or a position. */
export function netRoe(pos, mark) {
  if (!pos || !(Number(mark) > 0)) return null;
  const entry = Number(pos.entry), lev = Number(pos.leverage), side = Number(pos.side);
  if (!(entry > 0) || !(lev > 0) || !side) return null;
  return lev * (side * (Number(mark) / entry - 1) - Number(pos.round_trip || 0) - Number(pos.funding_frac || 0));
}

/** The price at which the paper's net ROE reaches `roe` (paperbot/ladder.py roe_price): the ladder's lines. */
export function roePrice(side, entry, lev, roe, roundTrip = 0, fundFrac = 0) {
  if (!(entry > 0) || !(lev > 0) || !side || roe == null) return null;
  return entry * (1 + side * (roe / lev + roundTrip + fundFrac));
}

/** The distance from the mark to a price, as a share of the mark (0.004 = 0.4 %); null without both. */
export const distTo = (mark, price) => (Number(mark) > 0 && Number(price) > 0 ? Math.abs(Number(price) - Number(mark)) / Number(mark) : null);

/**
 * The light in words, from the server's light (dash/more/livebots.py `light`, the executor's own rule):
 * {tone: "good" | "bad" | "wait" | "off" | "unknown", head, short, line, next}. `n` closed paper trades are the basis;
 * under that every entry is followed.
 */
export function lightWords(l) {
  if (!l || !l.state || l.state === "unknown") return {tone: "unknown", head: "모름", short: "모름", line: (l && l.reason_ko) || "신호등을 계산하지 못했어요", next: null};
  const pc = (x) => `${Math.round(Number(x) * 100)}%`;
  if (l.state === "off") return {tone: "off", head: "꺼짐", short: "꺼짐", line: "신호등이 꺼져 있어요: 페이퍼의 모든 진입을 따라가요", next: null};
  const rule = `기준: 최근 ${l.n}번 중 ${pc(l.min_win)} 이상 (${l.need_wins}번 이상 이김)`;
  if (l.state === "building") {
    return {tone: "wait", head: "근거 쌓는 중", short: `근거 쌓는 중 ${l.have}/${l.n}`,
      line: `페이퍼 거래 ${l.have}/${l.n}번 · ${l.need_more}번 더 쌓여야 판단해요. 그동안은 모든 진입을 따라가요`, next: rule};
  }
  const now = `최근 ${l.n}번 중 ${l.wins}번 이김 (${pc(l.share)})`;
  if (l.state === "green") {
    return {tone: "good", head: "초록", short: `초록 ${l.wins}/${l.n}`, line: `${now} · 새 진입을 따라가요`,
      next: l.next_loss_red ? `${rule} · 다음 거래를 지면 빨강으로 바뀌어요` : rule};
  }
  return {tone: "bad", head: "빨강", short: `빨강 ${l.wins}/${l.n}`, line: `${now} · 새 진입을 따라가지 않아요 (페이퍼는 계속 거래)`,
    next: l.next_win_green ? `${rule} · 다음 거래를 이기면 다시 초록이에요` : rule};
}

/** The light's squares, oldest on the left: n cells, each true (won) / false (lost) / null (no trade yet). */
export function lightCells(l) {
  if (!l || !(l.n > 0)) return [];
  const got = (l.recent || []).slice(0, l.n).reverse();
  return [...Array(Math.max(0, l.n - got.length)).fill(null), ...got];
}

/** A win share's place (0-100 %) on the ruler that runs from `lo` to `hi`, clamped. */
export function rulerAt(v, lo = 0.6, hi = 1) {
  if (v == null || !Number.isFinite(Number(v))) return null;
  return Math.max(0, Math.min(100, (Number(v) - lo) / (hi - lo) * 100));
}

/** The record's sample note floor: 20 below 20 trades, then 40 (null from 40 on: no note). */
export const smallFloor = (n, floors = [20, 40]) => (n == null ? null : n < floors[0] ? floors[0] : n < floors[1] ? floors[1] : null);

/** The alert log for a filter: "all" or an executor id. */
export const eventsFor = (events, ex) => (events || []).filter((e) => !ex || ex === "all" || e.ex === ex);

/**
 * Each coin's open positions of the three accounts: {sym: [{id, side, u (unrealized at the mark or null)}]}, accounts in
 * the order given (페이퍼, 바이비트, MEXC). markOf(sym) -> the mark or null.
 */
export function coinCounts(accts, markOf) {
  const out = {};
  for (const a of accts || []) {
    const p = a && a.state === "ok" ? a.position : null;
    if (!p || !p.symbol) continue;
    (out[p.symbol] ||= []).push({id: a.id, side: Number(p.side) > 0 ? 1 : -1, u: unrealized(p, markOf ? markOf(p.symbol) : null)});
  }
  return out;
}

/** The open-position keys of one coin (a key that was not there before = a real new fill on that coin). */
export function posKeys(accts, sym) {
  const out = new Set();
  for (const a of accts || []) {
    const p = a && a.state === "ok" ? a.position : null;
    if (p && p.symbol === sym && p.key) out.add(`${a.id}|${p.key}`);
  }
  return out;
}

/** Today's realized money of the live accounts (KST day, the server's `today`): {pnl, trades, wins, losses, parts: [{id, pnl}]}
 *  over the accounts that could be read; null when none could. */
export function liveToday(accts) {
  const live = (accts || []).filter((a) => a && a.kind === "live" && a.state === "ok" && a.today);
  if (!live.length) return null;
  const sum = (k) => live.reduce((s, a) => s + (Number(a.today[k]) || 0), 0);
  return {pnl: sum("pnl"), trades: sum("trades"), wins: sum("wins"), losses: sum("losses"), parts: live.map((a) => ({id: a.id, pnl: Number(a.today.pnl) || 0}))};
}

/**
 * New fills since the last look, for the one-shot lights and sounds (honesty: the first look is the past, never new):
 * fresh(prevKeys, fills) -> {keys (all keys now), fresh: [fills not seen before]}; prevKeys null = the first look.
 */
export function freshFills(prevKeys, fills) {
  const keys = new Set((fills || []).map((f) => f.key));
  if (!prevKeys) return {keys, fresh: []};
  return {keys, fresh: (fills || []).filter((f) => !prevKeys.has(f.key))};
}

/** A fill's sound (core/sound.js live events): an entry, a profitable lock exit, a stop-out; null for other exits. */
export function fillSound(f) {
  if (!f) return null;
  if (f.kind === "entry") return "lv_entry";
  if (f.reason === "LOCK" || f.reason === "TP") return "lv_tp";
  if (f.reason === "SL" || f.reason === "LIQ") return "lv_sl";
  return null;
}

/** Light / halt changes between two answers, for the alert sound and the band's one-shot light: [{id, what: "red" | "halt"}].
 *  A light that turned red, or an executor that became halted, since the previous answer (the first answer is the past). */
export function alarms(prev, next) {
  if (!prev || !next) return [];
  const out = [];
  const before = new Map((prev.execs || []).map((x) => [x.id, x]));
  for (const x of next.execs || []) {
    const b = before.get(x.id);
    if (!b) continue;
    if (x.light && x.light.state === "red" && !(b.light && b.light.state === "red")) out.push({id: x.id, what: "red"});
    const h1 = x.record && x.record.state === "ok" && x.record.halted, h0 = b.record && b.record.state === "ok" && b.record.halted;
    if (h1 && h0 === false) out.push({id: x.id, what: "halt"});
  }
  return out;
}

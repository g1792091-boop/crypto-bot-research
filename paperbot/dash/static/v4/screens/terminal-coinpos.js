// 코인 목록의 '우리 포지션 몇 개' (term-plus, owners' review 10/06: "코인 줄에는 가격, 24시간 %, GH 신호만 있어서 어디서 일이 벌어지는지
// 보려면 코인을 하나씩 눌러야 한다"): under each coin of the strip a small second line  "롱 3 · 숏 1 ●"  = how many of OUR open
// positions are on that coin (롱 in the up colour, 숏 in the down colour: the terminal's side colours) and a dot for the sign of
// their unrealized P&L at the mark price (up colour = in profit, down = in loss, grey = none or not known).
// WHICH accounts: the same ones the terminal's table adds up (기존 36 · 5분봉 · 추가 계좌: their money is shown); DeepSeek and the
// coin flips are counted only in the tooltip ("딥시크 5 · 동전 봇 4개도 열림 (건수만)"), never in the dot.
// HONESTY: no board yet is "—" (불러오는 중), a failed board "—" (불러오지 못함), a coin without a position "포지션 없음": three
// different things. The row lights ONCE when a position of that coin really is new (a position key that was not in the previous
// board; the first board is the past: no light), never under reduced motion or on a hidden page (hit() skips it).
import {h, put, fmt, store} from "../core/pb.js";
import {normPos} from "./positions-kit.js";
import {hit} from "./terminal-live.js";

const MONEY = new Set(["core", "m5", "extra"]);                // terminal-table.js MONEY_G (not imported: that file imports this chain)

/** the second line of a coin button (filled by paintCoinPos) */
export const coinPosCell = () => h("span", {class: "term-wpos muted", "data-k": "empty"}, "—");

/** the per-coin numbers from a board: {sym: {L, S, ds, coin, pnl (null when a mark is missing), keys: Set}} */
export function countPositions(board, markOf = (s) => store.mark(s)) {
  const out = {};
  for (const a of (board && board.accounts) || []) {
    const p = a.position;
    if (!p || !p.symbol) continue;
    const g = fmt.groupOf(a);
    const o = (out[p.symbol] ||= {L: 0, S: 0, ds: 0, coin: 0, pnl: 0, known: 0, keys: new Set()});
    if (g === "ds") { o.ds++; continue; }
    if (g === "coin") { o.coin++; continue; }
    if (!MONEY.has(g)) continue;
    const n = normPos(p), mk = markOf(p.symbol);
    if (n.side > 0) o.L++; else o.S++;
    o.keys.add(`${a.account_id}|${n.entry_time || n.entry}`);
    if (mk && Number.isFinite(n.qty) && Number.isFinite(n.entry)) { o.pnl += n.side * n.qty * (mk - n.entry); o.known++; }
  }
  return out;
}

/**
 * coinMarks() -> {paint(rows, board, failed), }: paints every coin's second line from the board. rows: Map sym -> {b (the
 * button), pos (the cell)}. Remembers the previous position keys per coin to light a new one.
 */
export function coinMarks() {
  let prev = null;
  return {
    paint(rows, board, failed) {
      const cnt = board ? countPositions(board) : null;
      for (const [sym, r] of rows) {
        const c = cnt && (cnt[sym] || {L: 0, S: 0, ds: 0, coin: 0, pnl: 0, known: 0, keys: new Set()});
        if (!r.pos) continue;
        if (!c) {
          put(r.pos, "—"); r.pos.className = "term-wpos muted";
          r.pos.title = `${fmt.coin(sym)}: 우리 포지션 ${failed ? "불러오지 못함" : "불러오는 중"}`;
          continue;
        }
        const n = c.L + c.S, extra = c.ds || c.coin ? ` · 딥시크 ${fmt.int(c.ds)} · 동전 봇 ${fmt.int(c.coin)}개도 열림 (건수만)` : "";
        if (!n) {
          put(r.pos, sym === "XRPUSDT" ? "기록만" : "포지션 없음"); r.pos.className = "term-wpos muted";
          r.pos.title = (sym === "XRPUSDT" ? "XRP: 기록만 하고 매매하지 않는 코인" : `${fmt.coin(sym)}에 열린 포지션이 없습니다 (기존 36 · 5분봉 · 추가 계좌)`) + extra;
        } else {
          const tone = c.known === n ? (Math.abs(c.pnl) < 0.005 ? "flat" : c.pnl > 0 ? "up" : "down") : "flat";
          put(r.pos, c.L ? h("span", {class: "up"}, `롱 ${fmt.int(c.L)}`) : null, c.L && c.S ? " · " : null, c.S ? h("span", {class: "down"}, `숏 ${fmt.int(c.S)}`) : null,
            h("i", {class: ["term-wdot", tone], "aria-hidden": "true"}));
          r.pos.className = "term-wpos num";
          r.pos.title = `${fmt.coin(sym)}에 열린 우리 포지션 ${fmt.int(n)}개 (롱 ${fmt.int(c.L)} · 숏 ${fmt.int(c.S)}) · 점 = 미실현 손익 합계 `
            + (c.known === n ? `${fmt.money(c.pnl, true)} USDT (${tone === "up" ? "이익" : tone === "down" ? "손실" : "거의 0"}, 마크 가격 기준)` : "(마크 가격을 아직 못 받아 모름)")
            + ` · 기존 36 · 5분봉 · 추가 계좌만${extra}`;
        }
        // a position of this coin that was not in the previous board: our bot really opened one (the first board is the past)
        if (prev && c) for (const k of c.keys) if (!(prev[sym] && prev[sym].has(k))) { hit(r.b, "own"); break; }
      }
      if (cnt) prev = Object.fromEntries(Object.entries(cnt).map(([s, c]) => [s, c.keys]));
    },
  };
}

// Today's numbers per group (기존 36 / 딥시크 44 / 5분봉 / 동전 봇 / 추가 계좌) from the server's own count since
// 00:00 KST: /api/summary today.by_group (groups.group_of keys, read through fmt.SERVER_GROUP). Nothing is downloaded
// per trade (a busy day has thousands). The three 5m coin flips count in 동전 봇 here as everywhere (paperbot/groups.py,
// owners' decision); 5분봉 is the reel alone. Busts come from the board rows' own `group`.
import {fmt} from "../core/pb.js";

/** Row labels of the server's split. */
export const TODAY_KO = {core: "기존 36", ds: "딥시크 44", m5: "5분봉", coin: "동전 봇", extra: "추가 계좌"};
export const TODAY_ORDER = ["core", "ds", "m5", "coin", "extra"];

/**
 * todayStats(summary, board) -> {ready, byGroup, since, total: {trades, wins, pnl, liq, busts}, groups: {id: {...}}}
 * ready: the summary is there; byGroup: the server sent today.by_group (else only the all-group totals are known).
 */
export function todayStats(summary, board) {
  const t = summary && summary.today;
  if (!t) return {ready: false, byGroup: false, since: 0, total: null, groups: {}};
  const blank = () => ({trades: 0, wins: 0, pnl: 0, liq: 0, busts: 0});
  const groups = {};
  const total = blank();
  const bg = t.by_group && typeof t.by_group === "object" ? t.by_group : null;
  for (const [k, v] of Object.entries(bg || {})) {
    const id = fmt.SERVER_GROUP[k] || k;
    const x = (groups[id] ||= blank());
    x.trades += v.trades || 0; x.wins += v.wins || 0; x.pnl += v.pnl || 0; x.liq += v.liquidations || 0;
  }
  for (const a of (board && board.accounts) || []) {
    if (a.bust && a.last_exit && a.last_exit >= t.since) {
      const id = fmt.SERVER_GROUP[a.group] || fmt.groupOf(a);
      (groups[id] ||= blank()).busts++; total.busts++;
    }
  }
  // total.pnl leaves DeepSeek out (owners' D11: DeepSeek money only on the DeepSeek group screen); counts include it
  if (bg) for (const [id, x] of Object.entries(groups)) { total.trades += x.trades; total.wins += x.wins; if (id !== "ds") total.pnl += x.pnl; total.liq += x.liq; }
  else { total.trades = t.trades || 0; total.liq = t.liquidations || 0; }
  return {ready: true, byGroup: !!bg, since: t.since, total, groups};
}

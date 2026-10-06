// The numbers behind the terminal's '실험 잘 되고 있나' band: pure functions (no DOM, no imports: tests/test_dash_term_plus.py
// runs them in node). Each takes what the page already has (/api/summary, /api/board, /api/analysis/health, the live
// stream's heartbeat) and returns a plain number, or null when that data is not there: the band then shows "—", never a
// number it does not have.
//
// The rules are the same as 홈's (screens/home-shared.js expInfo / judgedProgress, derive.groupStats): D+n of 30 from the
// summary's restart banner; judged accounts = the locked strategies and the reel on their judged timeframes plus the
// DeepSeek definitions (counted only); 30 closed trades is the verdict's own floor (checkpoint.MIN_TRADES).

export const MIN_TRADES = 30;                                   // checkpoint.MIN_TRADES (tests tie it)
const JUDGED = {strategy: ["15m", "30m", "1h"], ds200: ["15m", "30m", "1h"], reel: ["5m"]};
const KIND_GROUP = {strategy: "core", ds200: "ds200", reel: "reel"};

/** {day, of, verdictTs, left} of the 30-day run, or null when the summary has no start yet. */
export function dayInfo(summary, now) {
  const s = summary;
  if (!s || s.start == null) return null;
  const rs = s.restart || {}, cp = s.next_checkpoint || {};
  const day = rs.ready ? rs.day : (s.day || 1) - 1;
  const of = rs.ready ? rs.of : s.period_days || 30;
  const verdictTs = rs.ready ? rs.verdict_ts : cp.ts;
  if (!Number.isFinite(Number(day)) || !Number.isFinite(Number(of))) return null;
  const left = verdictTs ? Math.max(0, Math.ceil((verdictTs - now) / 86400000)) : null;
  return {day: Number(day), of: Number(of), verdictTs: verdictTs || null, left};
}

/** The judged timeframes of a kind: the server's run shape when it sends them, else the house defaults. */
export function judgedTfs(board, kind) {
  const jb = board && board.run_shape && board.run_shape.judged_by_group;
  const v = jb && jb[KIND_GROUP[kind]];
  return Array.isArray(v) && v.length ? v : JUDGED[kind] || [];
}

/** {n, ready}: the accounts that will be judged (36 strategies x timeframes, DeepSeek, the reel) and how many of them
 *  have 30 closed trades or more. null without a board. */
export function judgedCounts(board) {
  const rows = board && Array.isArray(board.accounts) ? board.accounts : null;
  if (!rows) return null;
  let n = 0, ready = 0;
  for (const kind of Object.keys(JUDGED)) {
    const tfs = judgedTfs(board, kind);
    for (const a of rows) {
      if (a.kind !== kind || !tfs.includes(a.timeframe)) continue;
      n++;
      if ((a.trades || 0) >= MIN_TRADES) ready++;
    }
  }
  return n ? {n, ready} : null;
}

/** {medRet, coinRet, above, vsN, n}: the 36's median return, the coin flips' median return, and how many of the 36's
 *  accounts are above the median coin flip of their own timeframe (derive.groupStats' numbers). null without them. */
export function compareCounts(gs) {
  const g = gs && gs.groups && gs.groups.core;
  if (!g || !g.n) return null;
  return {medRet: g.medRet, coinRet: gs.coin && gs.coin.n ? gs.coin.medRet : null, above: g.above, below: g.below, vsN: g.vsN, n: g.n};
}

/** Closed trades today of the 36 (the summary's by_group.core, else its strategy count); null when the summary has none. */
export function todayTrades(summary) {
  const t = summary && summary.today;
  if (!t) return null;
  const g = t.by_group && t.by_group.core;
  if (g && Number.isFinite(Number(g.trades))) return {trades: Number(g.trades), wins: Number(g.wins) || 0};
  if (Number.isFinite(Number(t.strategy_trades))) return {trades: Number(t.strategy_trades), wins: Number(t.wins) || 0};
  return null;
}

/**
 * The status chip. in: {health (the /api/analysis/health card or null), healthFailed, hbAgeS (seconds since the bot's last
 * heartbeat from the live stream or the health card, or null), critical: [{kind, text}] (core/alerts.js criticalLines),
 * failedKeys: names of the page's own data that could not be read right now (["순위 자료", ...]), linkDown: this page's live
 * connection is not delivering (then a missing heartbeat is said as that, never as the bot's)}.
 * -> {level: "ok" | "warn" | "bad" | "unknown", text, detail}. "ok" ONLY when the health card was read, says ok, no
 * critical line stands, the heartbeat is known and fresh and nothing the page shows failed to load: anything less never
 * says 이상 없음.
 */
export function statusOf({health, healthFailed, hbAgeS, critical, failedKeys, linkDown = false}) {
  const lines = Array.isArray(critical) ? critical : [];
  if (lines.length) return {level: "bad", text: "문제 있음", detail: lines[0].text};
  if (!health) return {level: "unknown", text: healthFailed ? "상태 확인 못 함" : "확인 중", detail: healthFailed ? "불러오지 못함" : "불러오는 중"};
  const first = (health.problems || [])[0] || (health.warnings || [])[0] || null;
  if (health.level === "bad") return {level: "bad", text: "문제 있음", detail: first};
  if (health.level === "warn") return {level: "warn", text: "확인할 것 있음", detail: first};
  if (hbAgeS == null) {
    // no heartbeat to read: when this page's own live connection is down say THAT (it is not the bot that stopped)
    return linkDown ? {level: "unknown", text: "실시간 연결 확인 중", detail: "이 화면과 서버의 실시간 연결이 끊겨 있어 봇 생존 신호를 볼 수 없습니다 (봇이 멈췄다는 뜻이 아닙니다)"}
      : {level: "unknown", text: "봇 생존 신호 확인 중", detail: "봇 생존 신호를 아직 받지 못했습니다"};
  }
  if (hbAgeS > 120) return {level: "bad", text: "문제 있음", detail: "봇 생존 신호가 오래 없습니다"};
  const miss = Array.isArray(failedKeys) ? failedKeys : [];
  if (miss.length) return {level: "warn", text: "일부 자료를 못 받음", detail: `${miss.join(" · ")} 불러오지 못함 (봇 상태 카드는 정상)`};
  return {level: "ok", text: "이상 없음", detail: null};
}

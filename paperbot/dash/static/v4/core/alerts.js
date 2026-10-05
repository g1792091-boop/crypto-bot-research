// The engine and runner write alerts in English; the page shows them in Korean (same patterns as the old app.js
// alertKo and Telegram's notify.ko). Plus the rules that decide a CRITICAL banner line (bust, liquidation burst,
// feed stale): they read only real records (alerts, closed trades, the health card, the live stream's heartbeat).
import {idName, coin, tfKo, kst, hm, dur} from "./fmt.js";

export function alertKo(text) {
  const t = String(text ?? "");
  let m;
  if ((m = t.match(/^\[([^\]]+)\] drawdown ([\d.]+)% \(level (\d+)%\), equity ([\d.]+)/)))
    return `${idName(m[1])} 낙폭 ${m[2]}% (${m[3]}% 경고선), 잔고 ${m[4]} USDT`;
  if ((m = t.match(/^\[([^\]]+)\] BUST/))) return `${idName(m[1])} 파산 (잔고 10 USDT 미만, 계좌 정지)`;
  if ((m = t.match(/^\[([^\]]+)\] LIQUIDATED (\S+) (\d+)x lost margin ([\d.]+)/)))
    return `${idName(m[1])} 강제청산: ${coin(m[2])} ${m[3]}배, 증거금 ${m[4]} USDT 손실`;
  if ((m = t.match(/^signal workers did not answer within (\d+)s; signals skipped at (\d+) for (.+)/)))
    return `신호 계산 ${m[1]}초 초과로 ${kst(+m[2])} 봉 신호 건너뜀: ${m[3].split(", ").map(tfKo).join(", ")}`;
  // the v4 groups' frozen texts (paperbot/sigservice.py DS_TIMEOUT_TEXT and the rest): "[ds200] " / "[reel] " name a
  // GROUP, never an account (no "@"), so no account link and no account name lookup
  if ((m = t.match(/^\[ds200\] DeepSeek signal workers timed out after (\d+)s; DeepSeek signals skipped at (\d+) for (.+)/)))
    return `딥시크 그룹: 신호 계산 ${m[1]}초 초과로 ${kst(+m[2])} 봉 딥시크 신호 건너뜀: ${m[3].split(", ").map(tfKo).join(", ")}`;
  if ((m = t.match(/^\[ds200\] DeepSeek signal error (\S+) (\S+): (.*)/)))
    return `딥시크 그룹: ${tfKo(m[1])} ${coin(m[2])} 신호 계산 오류: ${m[3]}`;
  if ((m = t.match(/^\[ds200\] DeepSeek signals failed at (\d+) \((.*)\)/)))
    return `딥시크 그룹: ${kst(+m[1])} 봉 딥시크 신호 실패 (${m[2]}) · 다른 그룹은 그대로 돎`;
  if ((m = t.match(/^\[reel\] 5m signal error (\S+) (\S+): (.*)/)))
    return `5분봉 그룹: ${tfKo(m[1])} ${coin(m[2])} 신호 계산 오류: ${m[3]}`;
  if ((m = t.match(/^\[reel\] 5m signals \(reel and 5m coin flips\) failed at (\d+) \((.*)\)/)))
    return `5분봉 그룹: ${kst(+m[1])} 봉 5분 단타·5분 동전 신호 실패 (${m[2]}) · 다른 그룹은 그대로 돎`;
  if ((m = t.match(/^\[(ds200|reel)\] signal code refused[^:]*: (.*)/)))
    return `${m[1] === "ds200" ? "딥시크" : "5분봉"} 그룹: 신호 코드 거절, 이 그룹 신호 멈춤 (다른 그룹은 그대로 돎): ${m[2]}`;
  if ((m = t.match(/^data gap at (\d+): no bar for (.+)/))) return `데이터 누락 ${kst(+m[1])}: ${m[2]}`;
  if (/^no new closed bars/.test(t)) return "새 1분봉이 들어오지 않음: " + t;
  if (/^5m history incomplete/.test(t)) return "5분봉 기록 불완전으로 신호 계산 건너뜀";
  if (/^Binance blocked/.test(t)) return "바이낸스가 서버 접속을 막음: " + t;
  return t;
}

export const isBust = (a) => a && /\bBUST\b/.test(String(a.text || ""));
const BUST_WINDOW_MS = 6 * 3600 * 1000;
const LIQ_WINDOW_MS = 15 * 60 * 1000;
export const LIQ_BURST = 3;
// a liquidation burst counts the accounts whose every trade is announced (groups.TRADE_ALERT_GROUPS: core, reel,
// extra); the 171 DeepSeek accounts and the coin flips at 20-50x would light the red banner on every sharp wick
const ALERT_KINDS = new Set(["strategy", "reel", "copy", "newlab"]);
const ALERT_GROUPS = new Set(["core", "reel", "extra"]);
function alertWorthy(t, kindOf) {
  const k = t.kind || (kindOf ? kindOf(t.account_id) : null);
  if (k) return ALERT_KINDS.has(k);
  if (t.group) return ALERT_GROUPS.has(t.group);
  return true;                        // unknown (the board is not loaded yet): counted, never hidden
}
const bustAcct = (a) => { const m = String(a.text || "").match(/^\[([^\]]+)\]/); return m ? m[1] : String(a.text || ""); };
const HB_STALE_S = 120;
const DATA_STALE_S = 300;            // health.py: 1m data older than 5 minutes is not fresh

/**
 * Critical banner lines, from real records only:
 *   health: /api/analysis/health (polled each minute); alerts: recent alert rows [{ts, level, text}]; trades: recent
 *   closed trades; hb: the live stream's last heartbeat [ts, {last_step}] or null (newer than the health card, so it
 *   wins while the stream is open); streamOk: the stream is connected; now: ms; kindOf(account_id): its kind (the
 *   live stream's trades carry none).
 * -> [{id, kind: "stale"|"bust"|"liq", text, href, dismissable}]
 */
export function criticalLines({health, alerts, trades, hb, streamOk, now, kindOf}) {
  const out = [];
  const stale = [];
  const b = health && health.bot;
  const hbTs = hb && Number(hb[0]);
  const last = hb && hb[1] && Number(hb[1].last_step);
  if (streamOk && hbTs) {
    const age = (now - hbTs) / 1000;
    if (age > HB_STALE_S) stale.push(`봇 생존 신호가 ${dur(age)}째 없습니다`);
    if (last && (now - last) / 1000 > DATA_STALE_S) stale.push(`시세(1분봉)가 ${dur((now - last) / 1000)}째 들어오지 않습니다`);
  } else if (b && b.ready) {
    if (b.alive === false) stale.push(`봇 생존 신호가 ${dur(b.heartbeat_age_s)} 전에 멈췄습니다`);
    if (b.data_fresh === false && b.data_age_s != null) stale.push(`시세(1분봉)가 ${dur(b.data_age_s)}째 들어오지 않습니다`);
  }
  // one banner line for everything that stopped (a phone has no room for three red rows)
  if (stale.length) out.push({id: "stale", kind: "stale", text: stale.join(" · "), href: "#/server", dismissable: false});
  // every bust of the last 6 hours folds into ONE line (a crash that busts ten accounts must not fill the phone);
  // dismissing it holds until a newer bust arrives (the id is the newest one's time)
  const busts = (alerts || []).filter((a) => a.level === "CRITICAL" && isBust(a) && now - a.ts < BUST_WINDOW_MS)
    .sort((p, q) => q.ts - p.ts);
  if (busts.length) {
    const accts = new Set(busts.map(bustAcct));
    const top = busts[0];
    out.push({id: `bust-${top.ts}`, kind: "bust", href: "#/alerts", dismissable: true,
      text: `파산 ${accts.size}개 계좌 · 최근 ${idName(bustAcct(top))} ${hm(top.ts)}`});
  }
  const liq = (trades || []).filter((t) => t.exit_reason === "LIQ" && now - t.exit_time < LIQ_WINDOW_MS && alertWorthy(t, kindOf));
  if (liq.length >= LIQ_BURST) {
    const first = Math.min(...liq.map((t) => t.exit_time));
    out.push({id: `liq-${first}`, kind: "liq", text: `강제청산 ${liq.length}건이 15분 안에 몰렸습니다 (기존 36·5분봉·추가 계좌)`, href: "#/positions", dismissable: true});
  }
  return out;
}

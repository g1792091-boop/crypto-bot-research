// 서버 group kit (builder E): pieces shared by server, alerts, signals, howto and faq. Its css (server-kit.css) is
// @imported by each of those screens' css. Everything here reads REAL records; what the server does not send yet is
// ui.notYet() ('수집 전'), never a number made up here.
import {h, ui, fmt, motion, serverNow} from "../core/pb.js";

// ---------------------------------------------------------------- words
export const LEVEL_KO = {CRITICAL: "긴급", WARN: "주의", INFO: "정보"};
export const LEVEL_CLS = {CRITICAL: "bad", WARN: "warn", INFO: "thin"};
/** signal_log.status (old app.js STATUS_KO). */
export const SIG_KO = {SUBMITTED: "진입 요청", LATE: "늦음 (진입 안 함)", RECORD: "기록만", NO_PRICE: "가격 없음", NO_ATR: "ATR 없음"};
export const SIG_CLS = {SUBMITTED: "", LATE: "warn", RECORD: "thin", NO_PRICE: "bad", NO_ATR: "bad"};
export const TF_ORDER = ["5m", "15m", "30m", "1h", "4h", "1d"];
/** Signal limits: /api/status `limits` when the server sends them (sigservice.py 180 s, config.FIVE_M_MAX_DELAY_MS 60 s). */
export const LIMITS_FALLBACK = {max_delay_ms: 180000, max_delay_ms_5m: 60000, timeout_s: 120};
export const limitsOf = (status) => ({...LIMITS_FALLBACK, ...((status && status.limits) || {})});
export const limitFor = (tf, lim) => (tf === "5m" ? lim.max_delay_ms_5m : lim.max_delay_ms);
export const sec = (ms) => (ms == null ? "—" : `${fmt.num(ms / 1000, ms < 10000 ? 1 : 0)}초`);

/** "10/05 14:05 · 3분 전" (server clock). */
export const when = (ts) => (ts ? `${fmt.kst(ts)} · ${fmt.ago(ts, serverNow())}` : "—");

/** status.signals_24h [{timeframe, status, n, avg_delay}] -> [{tf, n, late, avg (ms, weighted), statuses: {s: n}}] */
export function sigByTf(rows) {
  const by = {};
  for (const r of rows || []) {
    if (!r || typeof r !== "object") continue;
    const x = (by[r.timeframe] ||= {tf: r.timeframe, n: 0, late: 0, dsum: 0, dn: 0, statuses: {}});
    const n = Number(r.n) || 0;
    x.n += n; x.statuses[r.status] = (x.statuses[r.status] || 0) + n;
    if (r.status === "LATE") x.late += n;
    if (r.avg_delay != null) { x.dsum += Number(r.avg_delay) * n; x.dn += n; }
  }
  return Object.values(by).map((x) => ({tf: x.tf, n: x.n, late: x.late, avg: x.dn ? x.dsum / x.dn : null, statuses: x.statuses}))
    .sort((a, b) => TF_ORDER.indexOf(a.tf) - TF_ORDER.indexOf(b.tf));
}

// ---------------------------------------------------------------- pieces
/** The three state colours, one line (mockup screen 08). */
export const states = () => h("div", {class: "server-states", "aria-label": "색의 뜻"},
  h("span", {class: "ok"}, h("i"), "초록 여유"), h("span", {class: "warn"}, h("i"), "주황 지켜볼 것"),
  h("span", {class: "bad"}, h("i"), "빨강 조치 필요"));

/** A plate heading for a group of gauges / tiles. */
export const secHead = (text, sub) => h("div", {class: "server-sech"}, ui.plate(text), sub ? h("span", {class: "muted"}, sub) : null);

/** A health tile: {k, v, s, st: ok|warn|bad|none}. */
export function tile(o) {
  return h("div", {class: ["server-tile", o.st || "none"], title: o.title},
    h("span", {class: "k"}, o.k), h("b", {class: "v"}, o.v ?? "—"), o.s ? h("span", {class: "s"}, o.s) : null);
}

/**
 * A gauge that keeps its DOM and updates in place, so the bar slides and the number counts to new REAL values
 * (used only by the 서버 screens, so it stays in this kit). set({value, cap, ratio, fmt, capText, state, mean, off, unit}):
 *   value null -> '수집 전' (no bar); off: text -> the feature is off (e.g. '꺼짐'), shows `value` without a bar.
 * Same classes as ui.gauge (components.css): green < 60 %, amber < 85 %, red above (or `state`).
 */
export function liveGauge(name) {
  const stEl = h("span", {class: "g-st"});
  const valEl = h("b", {class: "num"});
  const capEl = h("small");
  const barI = h("i");
  const bar = h("div", {class: "g-bar", role: "img"}, barI);
  const mean = h("p", {class: "g-mean"});
  const el = h("div", {class: "gauge none"}, h("div", {class: "g-top"}, h("span", {class: "g-name"}, name), stEl,
    h("span", {class: "g-val"}, valEl, capEl)), bar, mean);
  el.set = (o) => {
    const have = o.value != null && Number.isFinite(Number(o.value));
    const r = !have || o.off ? null : o.ratio != null ? o.ratio : o.cap ? Number(o.value) / Number(o.cap) : null;
    const st = o.off ? "none" : !have ? "none" : o.state || (r == null ? "ok" : r < 0.6 ? "ok" : r < 0.85 ? "warn" : "bad");
    el.className = `gauge ${st}${!have && !o.off ? " idle" : ""}`;
    el.title = !have && !o.off && typeof o.mean === "string" ? o.mean : "";
    stEl.textContent = o.off || (!have ? "수집 전" : {ok: "여유", warn: "지켜볼 것", bad: "조치 필요", none: "—"}[st]);
    if (have) motion.countTo(valEl, Number(o.value), {format: o.fmt || ((v) => fmt.int(v))});
    else { valEl.textContent = "—"; delete valEl.dataset.v; }
    capEl.textContent = have && o.capText ? ` ${o.capText}` : "";
    bar.hidden = r == null;
    if (r != null) {
      barI.style.setProperty("--v", `${Math.max(0, Math.min(1, r)) * 100}%`);
      bar.setAttribute("aria-label", `${name} ${fmt.pct(r, 0, false)}`);
    }
    mean.replaceChildren(...[].concat(o.mean || []));
    mean.hidden = !o.mean || (!have && !o.off);          // an idle (수집 전) gauge stays one compact line
    return el;
  };
  return el;
}

/** "4분 뒤" / "6시간 전" (the largest unit only: a row stays one line). */
export function rel(ts, now = serverNow()) {
  if (!ts) return "";
  const d = (ts - now) / 1000, a = Math.abs(d);
  const t = a < 60 ? "1분 안" : a < 3600 ? `${Math.round(a / 60)}분` : a < 86400 ? `${Math.floor(a / 3600)}시간` : `${Math.floor(a / 86400)}일`;
  return a < 60 ? (d >= 0 ? "곧" : "방금") : `${t} ${d >= 0 ? "뒤" : "전"}`;
}
/** "오늘 14:05" / "내일 09:20" / "10/03 09:20" (Korea time). */
export function dayTime(ts, now = serverNow()) {
  if (!ts) return "—";
  const dd = (fmt.kstMidnight(ts) - fmt.kstMidnight(now)) / 864e5;
  return `${dd === 0 ? "오늘" : dd === 1 ? "내일" : dd === -1 ? "어제" : fmt.mmdd(ts)} ${fmt.hm(ts)}`;
}

// ---------------------------------------------------------------- scheduled jobs (deploy/*.timer)
// The timers' own calendars, copied from deploy/paperbot-*.timer (a fact of the setup, not a guess). Whether a timer is
// switched on and when each one last ran is NOT sent by the server yet (NEEDS SERVER: /api/v4/jobs), except the few
// below that leave a record the dashboard already reads (`last`).
const H = 3600000, M = 60000, D = 86400000, KST = 9 * H;
export const JOBS = [
  {unit: "paperbot-daily3", ko: "매일 점검", what: "하루치 거래를 처음부터 다시 계산해 맞춰 보기", cal: {daily: [0, 20]}, last: "nightly", main: true},
  {unit: "paperbot-backup", ko: "DB 백업", what: "서버 안에 데이터베이스 사본 만들기", cal: {daily: [23, 40]}, main: true},
  {unit: "paperbot-offsite", ko: "바깥 백업", what: "백업 사본을 텔레그램 비공개 방으로 보내기", cal: {daily: [0, 15]}, main: true},
  {unit: "paperbot-obsidian", ko: "옵시디언 노트", what: "기록 노트(볼트) 새로 만들기", cal: {daily: [0, 50]}, main: true},
  {unit: "paperbot-shadow200", ko: "딥시크 200 그림자", what: "342개 설정 기록만 (계좌·주문 없음)", cal: {mins: [2, 17, 32, 47]}, main: true},
  {unit: "paperbot-agents", ko: "에이전트 점검", what: "회의가 필요한지 보고 회의 열기", cal: {every: 15}, last: "agents", main: true},
  {unit: "paperbot-checkpoint", ko: "체크포인트 판정", what: "판정 날에만 일함 (나머지 시간은 확인만)", cal: {hourly: 35}, last: "checkpoint", main: true},
  {unit: "paperbot-dscheck", ko: "딥시크 밤 재계산", what: "딥시크 계좌 재계산 확인", cal: {daily: [0, 30]}},
  {unit: "paperbot-evening", ko: "저녁 회의", what: "22:00 저녁 점검 회의", cal: {daily: [13, 0]}},
  {unit: "paperbot-rehearsal", ko: "판정 미리 연습", what: "매주 수요일, 진짜 판정에는 영향 없음", cal: {weekly: [3, 3, 30]}},
  {unit: "paperbot-labmonthly", ko: "매달 재검사", what: "매달 6일 새벽", cal: {monthly: [5, 18, 30]}},
];

/** The next time a timer calendar fires after `now` (ms, UTC calendars). */
export function nextRun(cal, now) {
  if (cal.every) { const st = cal.every * M; return now - (now % st) + st; }
  if (cal.hourly != null) { let t = now - (now % H) + cal.hourly * M; if (t <= now) t += H; return t; }
  if (cal.mins) {
    const h0 = now - (now % H);
    for (const k of [0, 1]) for (const m of cal.mins) { const t = h0 + k * H + m * M; if (t > now) return t; }
  }
  if (cal.daily) { let t = now - (now % D) + cal.daily[0] * H + cal.daily[1] * M; if (t <= now) t += D; return t; }
  if (cal.weekly) {
    const [wd, hh, mm] = cal.weekly;
    let t = now - (now % D) + hh * H + mm * M;
    for (let i = 0; i < 8; i++, t += D) if (new Date(t).getUTCDay() === wd && t > now) return t;
  }
  if (cal.monthly) {
    const [day, hh, mm] = cal.monthly, d = new Date(now);
    for (let k = 0; k < 2; k++) {
      const t = Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + k, day, hh, mm);
      if (t > now) return t;
    }
  }
  return null;
}
/** How a calendar reads in Korean (KST). */
export function calKo(cal) {
  const two = (n) => String(n).padStart(2, "0");
  const k = (hh, mm) => { const t = ((hh * 60 + mm) * M + KST) % D; return `${two(Math.floor(t / H))}:${two((t % H) / M)}`; };
  if (cal.every) return `${cal.every}분마다`;
  if (cal.hourly != null) return `매시 ${cal.hourly}분`;
  if (cal.mins) return "15분마다";
  if (cal.daily) return `매일 ${k(cal.daily[0], cal.daily[1])}`;
  if (cal.weekly) return `매주 수요일 ${k(cal.weekly[1], cal.weekly[2])}`;
  if (cal.monthly) return `매달 6일 ${k(cal.monthly[1], cal.monthly[2])}`;
  return "—";
}

/** A one-line note under a card (muted). */
export const note = ui.note;

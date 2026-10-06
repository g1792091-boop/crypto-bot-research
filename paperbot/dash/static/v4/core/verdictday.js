// 판정 날 시계 on the page (review 10/06 fix 1 + change 13): /api/summary carries the server's verdict-day clock
// (verdict_clock, dash/more/verdictday.py): the checkpoint the countdown points at stays the one shown until the
// checkpoint job has stored its verdict ("due"), so 09:00 on the verdict day never turns into "2번째 판정 · 30일
// 남음". Every screen writes the same sentence (line_ko: "30일 중 N일 지남 · 판정까지 M일 (11/04 09:00)").
//
// startVerdictBand(): once a verdict is stored, every screen shows one band "판정 결과가 나왔습니다 → 보기" once per
// device (local 'vband-seen' = the verdict date; a per-viewer convenience) and refreshes the shared checkpoint data
// right away (the summary is polled every 60 s for the whole session, so a verdict being computed is checked each
// minute). Not on 판정 itself (that page shows the result), not for a verdict stored more than 3 days ago.
import {h, local} from "./dom.js";
import {store} from "./store.js";
import {bus, serverNow} from "./api.js";
import {href, parseHash} from "./routes.js";
import {mmdd, hm, date as fdate, dur} from "./fmt.js";
import {reduced} from "./motion.js";

const DAY = 86400000;
const SEEN = "vband-seen";
const BAND_DAYS = 3;

/** The server's clock from a summary (null before the first account / from an older server). */
export function vclock(s) {
  const c = s && s.verdict_clock;
  return c && c.ready ? c : null;
}

/** The one sentence of every screen (the server's own words; a short fallback for an older server). */
export function lineKo(s) {
  const c = vclock(s);
  if (c && c.line_ko) return c.line_ko;
  const rs = (s && s.restart) || {};
  return rs.line_ko || (rs.ready ? `D+${rs.day} / ${rs.of} · 판정 ${rs.verdict_mmdd || "—"}` : "봇이 아직 첫 계좌를 만들지 않았습니다");
}

/** Exact time left to the checkpoint (ms, never below 0). */
export const msLeft = (c, now = serverNow()) => (c && c.ts ? Math.max(0, c.ts - now) : null);

/** "28일 18시간 59분" / "3시간 12분" / "12분": the exact time left in words. */
export function leftWords(ms) {
  if (ms == null) return "—";
  const d = Math.floor(ms / DAY), rest = (ms % DAY) / 1000;
  return d > 0 ? `${d}일 ${dur(rest)}` : dur(ms / 1000);
}

/** The big number: "29일" + "남음" (days to the verdict day as in line_ko), "오늘"/"내일" on the last day, else the
 *  due state's word ("계산 중", "확인 필요"). */
export function bigWords(c, now = serverNow()) {
  if (!c) return {big: "—", unit: ""};
  if (c.state === "ended") return {big: "끝", unit: "180일"};
  if (c.due) return {big: c.state === "failed" || c.state === "unknown" || c.late ? "확인 필요" : "계산 중", unit: ""};
  if (c.ts - now <= DAY) {
    const same = Math.floor((now + 9 * 3600000) / DAY) === Math.floor((c.ts + 9 * 3600000) / DAY);
    return {big: same ? "오늘" : "내일", unit: "09:00"};
  }
  return {big: `${c.left}일`, unit: "남음"};
}

/** systemd's word on the verdict job since the checkpoint (/api/v4/verdictday machine.job, on the server only):
 *  {rerun: a run after an error is computing now} or {dead: the last run ended badly, e.g. killed by the service's memory
 *  or time limit, which leaves no line in checkpoint.db}; null when systemd does not answer or has nothing to add. */
export const RESULT_KO = {"oom-kill": "메모리 한도로 멈춤", timeout: "시간 한도로 멈춤", signal: "강제로 멈춤", "core-dump": "비정상 종료",
  "exit-code": "오류로 끝남", watchdog: "응답 없어 멈춤", "start-limit-hit": "재시작 한도"};
export function jobSays(c, m) {
  const j = m && m.systemd ? m.job : null;
  if (!c || !c.due || !j || !j.last_ms || !c.ts || j.last_ms < c.ts) return null;
  if (j.running) return c.state === "failed" ? {rerun: true, since: j.last_ms} : null;
  if (j.ok === false && (c.state === "computing" || c.state === "waiting_job")) {
    return {dead: true, since: j.last_ms, result: j.result || null, ko: RESULT_KO[j.result] || "실패로 끝남"};
  }
  return null;
}

/** The due checkpoint's steps, in order: [{t, label, state: "done" | "now" | "wait" | "bad", note}]. Only what the
 *  databases say happened is marked done (CONTRACT 1.1: never an invented step). ``js``: jobSays() (optional). */
export function dueSteps(c, now = serverNow(), js = null) {
  if (!c || !c.due) return [];
  const saved = c.saved_ts, snap = c.snapshot_ts, failed = c.state === "failed", unknown = c.state === "unknown";
  const waitState = c.state === "waiting_state";
  const s1 = saved ? {state: "done", note: `봇이 저장함 (${hm(saved)})`} : unknown ? {state: "wait", note: "확인하지 못함"}
    : waitState && c.late ? {state: "bad", note: "아직 저장이 없음 · 봇이 도는지 서버 화면에서 확인"}
    : {state: waitState ? "now" : "wait", note: waitState ? "봇의 저장을 기다리는 중" : "기록 아직 없음"};
  const s2 = snap ? {state: "done", note: `저장본 잠금 (${hm(snap)})`}
    : unknown ? {state: "wait", note: "확인하지 못함"}
    : waitState ? {state: "wait", note: `판정 작업은 돌았고 봇의 저장을 기다림 (${c.next_try_ts ? `다음 실행 ${hm(c.next_try_ts)}` : "매시 35분"})`}
    : c.late ? {state: "bad", note: "판정 작업이 아직 돌지 않았습니다"}
    : now < c.job_ts ? {state: "wait", note: `${hm(c.job_ts)}에 시작`}
    : {state: "now", note: c.next_try_ts ? `다음 실행 ${hm(c.next_try_ts)}` : "곧 시작"};
  const s3 = js && js.rerun ? {state: "now", note: `앞선 실행은 오류${c.error_kind ? ` (${c.error_kind})` : ""} · ${hm(js.since)}부터 다시 계산 중`}
    : js && js.dead ? {state: "bad", note: `마지막 실행(${hm(js.since)} 시작)이 ${js.ko} · ${c.next_try_ts ? `${hm(c.next_try_ts)}에` : "매시 35분에"} 다시 시도`}
    : failed ? {state: "bad", note: `오류${c.error_kind ? ` (${c.error_kind})` : ""} · ${c.next_try_ts ? `${hm(c.next_try_ts)}에` : "매시 35분에"} 다시 시도`}
    : snap && c.late ? {state: "bad", note: `계산 중 · ${dur((now - snap) / 1000)}째 · 너무 오래 걸림`}
    : snap ? {state: "now", note: `계산 중 · ${dur((now - snap) / 1000)}째`}
    : {state: "wait", note: "저장본이 잠긴 뒤"};
  return [
    {t: "09:00", label: "모든 계좌 상태 저장 (사진)", ...s1},
    {t: "09:35", label: "판정 작업이 저장본을 잠금 (해시)", ...s2},
    {t: "", label: "동전 봇 비교 계산", ...s3},
    {t: "", label: "결과 저장 → 이 화면 · 텔레그램 · 총괄 판정 회의", state: "wait", note: "결과가 나오면 바로"},
  ];
}

/** "30일 판정 · 11월 4일 (수) 09:00" (k-th checkpoint's own words). */
export const whenKo = (c) => (c && c.ts ? `${c.k > 1 ? `${c.k}번째 판정` : "첫 판정"} · ${fdate(c.ts)} 09:00 (한국 시각)` : "—");

// ---------------------------------------------------------------- the one-time band
let band = null;          // its look: core/verdictday.css (index.html links it)
let dismissed = null;     // the verdict date closed in this tab (the 'vband-seen' mark can be blocked: a private window)
const onCheckpoint = () => parseHash(location.hash).name === "checkpoint";

function close(date) {
  if (date) { dismissed = date; local.set(SEEN, date); }
  if (!band) return;
  const el = band;
  band = null;
  if (reduced()) el.remove();
  else { el.classList.remove("in"); setTimeout(() => el.remove(), 260); }
}

function show(last) {
  if (band && band.dataset.date === last.date) return;
  close(null);
  const day = last.day || 30;
  const done = last.done_ts || last.stored_ts;      // when the verdict was really written (the row's ts is the run's start)
  const go = h("a", {class: "vband-go", href: href("checkpoint"), onclick: () => close(last.date)}, "보기 →");
  const x = h("button", {class: "vband-x", type: "button", "aria-label": "닫기", onclick: () => close(last.date)}, "✕");
  band = h("section", {class: "vband", role: "status", "aria-live": "polite", dataset: {date: last.date}},
    h("span", {class: "vband-ic", "aria-hidden": "true"}, "◆"),
    h("span", {class: "vband-t"}, h("b", null, `${day}일 판정 결과가 나왔습니다`),
      h("span", null, ` · ${mmdd(last.ts)} 판정${done ? ` · ${hm(done)}쯤 결과 저장` : ""}`)),
    go, x);
  document.body.append(band);
  requestAnimationFrame(() => requestAnimationFrame(() => band && band.classList.add("in")));
}

function check(s) {
  const c = vclock(s);
  const last = c && c.last;
  if (!last || !last.date) return;
  if (dismissed === last.date || local.get(SEEN, null) === last.date) return;
  if (serverNow() - (last.done_ts || last.stored_ts || 0) > BAND_DAYS * DAY) return;
  const ck = store.get("checkpoint");
  if (!ck || !ck.ready || ck.date !== last.date) store.refresh("checkpoint").catch(() => {});
  if (onCheckpoint()) { dismissed = last.date; local.set(SEEN, last.date); close(null); return; }
  show(last);
}

export function startVerdictBand() {
  store.watch("summary", (s) => { if (s) check(s); });
  bus.on("route", () => { if (band && onCheckpoint()) close(band.dataset.date); });
}

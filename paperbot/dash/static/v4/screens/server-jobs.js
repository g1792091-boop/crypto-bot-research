// 서버·비용 (builder E): the scheduled jobs (on / off, last run / next run / failure warning) and the run facts.
// Last run comes first from records the dashboard already reads: the nightly check's report (daily3.db), the agents
// tick (agents3.db), the checkpoint job log (checkpoint.db). Everything else, and whether a timer is switched on at
// all, comes from /api/v4/jobs (dash/more/jobs.py: systemd's own timer state, 60 s cache). Where that route is missing
// or systemctl cannot answer, the rows keep 수집 전 and the next run from the timer's calendar (deploy/).
import {h, ui, fmt, derive, serverNow, put} from "../core/pb.js";
import {JOBS, nextRun, calKo, rel, dayTime, note, limitsOf} from "./server-kit.js";

/** systemd's view of one timer (/api/v4/jobs), or null when the route / systemctl is not there. */
function sysOf(job, sj) {
  return sj && sj.available && sj.jobs ? sj.jobs[job.unit] || null : null;
}

function lastOf(job, hl, sys) {
  const fromSys = sys && sys.last_ms ? {ts: sys.last_ms, ok: sys.ok !== false} : null;
  if (!hl) return fromSys || (sys ? {none: sys.state === "on" ? "아직 안 돎" : "기록 없음"} : null);
  if (job.last === "nightly" && hl.nightly && hl.nightly.ready) return {ts: hl.nightly.ts, ok: !((hl.nightly.parity || {}).mismatched_accounts)};
  if (job.last === "agents" && hl.agents && hl.agents.last_tick && hl.agents.last_tick.ts) return {ts: hl.agents.last_tick.ts, ok: hl.agents.last_tick.ok !== false};
  if (job.last === "checkpoint") {
    const lj = hl.checkpoint && hl.checkpoint.last_job;
    return lj ? {ts: lj.ts, ok: true, text: lj.text} : fromSys || {none: "판정 전이라 기록 없음"};
  }
  if (fromSys) return fromSys;
  if (sys) return {none: sys.state === "on" ? "아직 안 돎" : "기록 없음"};     // systemd answered: never fired
  return null;
}

/** The right-hand mark: 꺼짐 / 설치 안 됨 (systemd), a failure warning, else the calendar. */
function sideMark(job, fail, sys, now) {
  if (sys && sys.state === "off") return ui.pill("꺼짐", "warn", "타이머가 꺼져 있어 이 작업이 돌지 않습니다 (systemd)");
  if (sys && sys.state === "missing") return ui.pill("설치 안 됨", "thin", "서버에 이 타이머가 없습니다 (systemd)");
  if (fail) return ui.pill(`실패 경고 ${String(fail.day).slice(5).replace("-", "/")}`, now - fail.ts < 864e5 ? "bad" : "thin",
    "systemd가 이 작업의 실패를 알린 날 (그날 첫 번만)");
  if (sys && sys.ok === false) return ui.pill("지난번 실패", "bad", `마지막 실행 결과: ${sys.result}`);
  if (sys && sys.running) return ui.pill("도는 중", "accent", "지금 실행 중 (systemd)");
  return h("span", {class: "server-cal"}, calKo(job.cal));
}

function jobRow(job, hl, now, sj) {
  const fail = ((hl && hl.job_failures) || []).find((f) => String(f.unit).replace(/\.service$/, "") === job.unit);
  const sys = sysOf(job, sj);
  const last = lastOf(job, hl, sys);
  const off = !!sys && sys.state !== "on";
  const nx = off ? null : (sys && sys.next_ms) || nextRun(job.cal, now);
  const lastNode = last && last.ts ? h("span", {class: last.ok ? "" : "down"}, `${dayTime(last.ts, now)} · ${rel(last.ts, now)}${last.ok ? "" : " · 실패"}`)
    : last && last.none ? h("span", null, last.none) : ui.notYet();
  return h("div", {class: ["server-row", "server-job", off ? "server-job-off" : ""], role: "listitem", "data-job": job.unit,
    "data-state": sys ? sys.state : "unknown"},
    h("div", {class: "body"}, h("b", null, job.ko), h("span", {class: "server-what"}, job.what)),
    h("div", {class: "side-r"}, sideMark(job, fail, sys, now)),
    h("div", {class: "meta"}, h("span", null, "마지막 ", lastNode),
      h("span", null, `다음 ${nx ? `${dayTime(nx, now)} · ${rel(nx, now)}` : off ? (sys.state === "missing" ? "— (설치 안 됨)" : "— (꺼짐)") : "—"}`)));
}

export function jobsCard() {
  const main = h("div", {role: "list"});
  const more = h("div", {role: "list"});
  const offLine = h("p", {class: "server-note server-jobs-off", hidden: true});
  const foot = note();
  const card = ui.card({plate: "예약 작업", sub: "백업·점검·노트가 제때 도는지"}, offLine, main,
    ui.disclosure(`다른 예약 작업 ${fmt.int(JOBS.filter((j) => !j.main).length)}개`, more), foot);
  let hl0 = null, sj0 = null;
  const paint = () => {
    const now = serverNow();
    put(main, JOBS.filter((j) => j.main).map((j) => jobRow(j, hl0, now, sj0)));
    put(more, JOBS.filter((j) => !j.main).map((j) => jobRow(j, hl0, now, sj0)));
    const live = !!(sj0 && sj0.available);
    const offs = live ? JOBS.filter((j) => { const x = sysOf(j, sj0); return x && x.state !== "on"; }) : [];
    offLine.hidden = !offs.length;
    offLine.textContent = offs.length ? `꺼졌거나 없는 예약 작업 ${fmt.int(offs.length)}개: ${offs.map((j) => j.ko).join(" · ")}` : "";
    foot.textContent = live
      ? `켜짐·꺼짐과 마지막·다음 실행은 서버의 타이머(systemd)에서 1분마다 읽습니다 · ${fmt.hm(sj0.ts)} 기준.`
      : sj0 && sj0.reason
        ? "서버가 타이머 상태를 읽지 못했습니다. 다음 = 서버 타이머 설정 시각, 기록이 없는 작업의 마지막 실행은 수집 전입니다."
        : "다음 = 서버 타이머 설정 시각입니다. 타이머가 켜져 있는지와 기록이 없는 작업의 마지막 실행은 서버가 아직 보내지 않습니다 (수집 전).";
    foot.title = sj0 && sj0.reason ? String(sj0.reason) : "";
  };
  card.update = (hl) => { hl0 = hl; paint(); };
  /** /api/v4/jobs (dash/more/jobs.py); null keeps the calendar-only rows. */
  card.setJobs = (sj) => { sj0 = sj && typeof sj === "object" ? sj : null; paint(); };
  return card;
}

/** Run facts (old 서버 상태 tiles): settings, start, accounts per group, starting wallet, fee, brackets, limits. */
export function factsCard() {
  const body = h("div", {class: "stack tight"});
  const card = ui.card({plate: "실행 정보", sub: "봇이 시작할 때 남긴 값"}, body, ui.assume());
  card.update = (status, board) => {
    const run = (status && status.run && status.run[1]) || {};
    const runTs = status && status.run ? status.run[0] : null;
    const lim = limitsOf(status);
    const gs = board ? derive.groupStats(board) : null;
    const groups = gs ? fmt.GROUPS.filter((g) => gs.groups[g.id]).map((g) => `${g.ko}: ${fmt.int(gs.groups[g.id].n)}개`) : [];
    const br = String(run.brackets || "");
    put(body, ui.kv([
      ["설정", run.settings || "—"],
      ["시작", runTs ? fmt.kst(runTs) : "—"],
      ["계좌", gs ? `${fmt.int(gs.total.n)}개` : run.accounts != null ? `${fmt.int(run.accounts)}개` : "—"],
      ["시작 잔고", board ? `${fmt.money(board.initial)} USDT씩` : run.initial_equity != null ? `${fmt.money(run.initial_equity)} USDT씩` : "—"],
      ["수수료 (한쪽)", run.taker_fee != null ? fmt.pct(run.taker_fee, 3, false) : "—"],
      ["레버리지 구간", br ? (br.includes("EXAMPLE") ? "예시 표" : "거래소 실제 값") : "—"],
      ["재시작", run.restored ? "재시작 후 복구됨" : runTs ? "새로 시작" : "—"],
      ["신호 한도", `${fmt.int(lim.max_delay_ms / 1000)}초 · 5분봉 ${fmt.int(lim.max_delay_ms_5m / 1000)}초`],
      ["계산 제한", `${fmt.int(lim.timeout_s)}초`],
    ]), groups.length ? h("p", {class: "server-note"}, groups.join(" · ")) : null);
  };
  return card;
}

// 서버·비용 (builder E): the scheduled jobs (last run / next run / failure warning) and the run facts.
// Last run comes only from records the dashboard already reads: the nightly check's report (daily3.db), the agents
// tick (agents3.db), the checkpoint job log (checkpoint.db). Backups, off-site, Obsidian and the DeepSeek-200 shadow
// leave nothing the server sends yet: 수집 전 (NEEDS SERVER /api/v4/jobs). Next run = the timer's calendar (deploy/).
import {h, ui, fmt, derive, serverNow, put} from "../core/pb.js";
import {JOBS, nextRun, calKo, rel, dayTime, note, limitsOf} from "./server-kit.js";

function lastOf(job, hl) {
  if (!hl) return null;
  if (job.last === "nightly" && hl.nightly && hl.nightly.ready) return {ts: hl.nightly.ts, ok: !((hl.nightly.parity || {}).mismatched_accounts)};
  if (job.last === "agents" && hl.agents && hl.agents.last_tick && hl.agents.last_tick.ts) return {ts: hl.agents.last_tick.ts, ok: hl.agents.last_tick.ok !== false};
  if (job.last === "checkpoint") {
    const lj = hl.checkpoint && hl.checkpoint.last_job;
    return lj ? {ts: lj.ts, ok: true, text: lj.text} : {none: "판정 전이라 기록 없음"};
  }
  return null;
}

function jobRow(job, hl, now) {
  const fail = ((hl && hl.job_failures) || []).find((f) => String(f.unit).replace(/\.service$/, "") === job.unit);
  const last = lastOf(job, hl);
  const nx = nextRun(job.cal, now);
  const lastNode = last && last.ts ? h("span", {class: last.ok ? "" : "down"}, `${dayTime(last.ts, now)} · ${rel(last.ts, now)}${last.ok ? "" : " · 실패"}`)
    : last && last.none ? h("span", null, last.none) : ui.notYet();
  return h("div", {class: "server-row server-job", role: "listitem"},
    h("div", {class: "body"}, h("b", null, job.ko), h("span", {class: "server-what"}, job.what)),
    h("div", {class: "side-r"}, fail ? ui.pill(`실패 경고 ${String(fail.day).slice(5).replace("-", "/")}`, now - fail.ts < 864e5 ? "bad" : "thin",
      "systemd가 이 작업의 실패를 알린 날 (그날 첫 번만)") : h("span", {class: "server-cal"}, calKo(job.cal))),
    h("div", {class: "meta"}, h("span", null, "마지막 ", lastNode), h("span", null, `다음 ${nx ? `${dayTime(nx, now)} · ${rel(nx, now)}` : "—"}`)));
}

export function jobsCard() {
  const main = h("div", {role: "list"});
  const more = h("div", {role: "list"});
  const card = ui.card({plate: "예약 작업", sub: "백업·점검·노트가 제때 도는지"}, main,
    ui.disclosure(`다른 예약 작업 ${fmt.int(JOBS.filter((j) => !j.main).length)}개`, more),
    note("다음 = 서버 타이머 설정 시각입니다. 타이머가 켜져 있는지와 백업·바깥 백업·옵시디언·그림자 시험의 마지막 실행은 서버가 아직 보내지 않습니다 (수집 전)."));
  card.update = (hl) => {
    const now = serverNow();
    put(main, JOBS.filter((j) => j.main).map((j) => jobRow(j, hl, now)));
    put(more, JOBS.filter((j) => !j.main).map((j) => jobRow(j, hl, now)));
  };
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

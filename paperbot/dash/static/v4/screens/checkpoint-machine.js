// 30일 판정 › 판정 기계 준비됐나 (review 10/06 addition 13): is the verdict machinery ready, in one small card. From
// /api/v4/verdictday machine (dash/more/verdictday.py): the weekly rehearsal (checkpoint_preview, Wednesdays 12:30:
// only whether it ran, failed or was skipped, when and how long; its numbers are never shown, it is not a verdict), the
// verdict job's timer (paperbot-checkpoint: on / off, the hourly :35 run, its last result) and the projected runtime of
// the real verdict (the rehearsal's runtime x 10,000 / 2,000 bots). systemd answers only on the server: elsewhere the
// rows say 수집 전 (never 'off').
import {h, put, ui, fmt} from "../core/pb.js";

const LEVEL = {ok: ["준비됨", "good"], warn: ["확인 필요", "warn"], bad: ["꺼짐", "bad"], unknown: ["서버에서만 확인", "thin"]};

function rehearsalLine(r, next) {
  const nx = next ? ` · 다음 ${fmt.date(next.ts)} ${fmt.hm(next.ts)}` : "";
  if (!r || r.state === "missing") return h("span", {class: "muted"}, `연습 기록이 아직 없습니다${nx}`);
  if (r.state === "error") return h("span", {class: "ck-bad"}, "연습 기록을 읽지 못했습니다 (없다는 뜻이 아님)");
  const last = r.last, run = r.last_run;
  const out = [];
  if (run) {
    const mins = run.runtime_s != null ? ` (${fmt.dur(run.runtime_s)})` : "";
    out.push(run.status === "ok" ? h("b", {class: "up"}, `${fmt.date(run.ts)} 정상 끝남${mins}`)
      : h("b", {class: "down"}, `${fmt.date(run.ts)} 실패${run.error_kind ? ` (${run.error_kind})` : ""}`));
  } else out.push(h("span", {class: "muted"}, `아직 한 번도 돌지 않았습니다${nx}`));
  if (last && last.status === "skipped") out.push(h("span", {class: "muted"}, ` · ${fmt.mmdd(last.ts)}는 판정 날이라 건너뜀`));
  if (r.n > 1) out.push(h("span", {class: "muted"}, ` · 최근 ${fmt.int(r.n)}번 중 정상 ${fmt.int(r.ok)}번${r.failed ? ` · 실패 ${fmt.int(r.failed)}번` : ""}`));
  return h("span", null, out);
}

function jobLine(m, unit) {
  if (!m.systemd) return ui.notYet("수집 전", m.systemd_reason ? `서버에서만 확인할 수 있습니다 (${m.systemd_reason})` : "서버에서만 확인할 수 있습니다");
  const j = unit === "job" ? m.job : m.rehearsal_timer;
  if (!j || j.state === "missing") return h("b", {class: "down"}, "설치 안 됨");
  if (j.state === "off") return h("b", {class: "down"}, unit === "job" ? "꺼짐 · 판정 날 결과가 나오지 않습니다" : "꺼짐");
  const parts = [h("b", {class: "up"}, unit === "job" ? "켜짐 · 매시 35분 (판정 날 09:35 시작)" : "켜짐 · 매주 수요일 12:30")];
  if (j.running) parts.push(h("span", null, " · 지금 도는 중"));
  else if (j.last_ms) parts.push(h("span", {class: "muted"}, ` · 마지막 ${fmt.kst(j.last_ms)} ${j.ok === false ? "오류로 끝남" : j.ok ? "정상" : ""}`));
  return h("span", null, parts);
}

/** machineCard() -> card with .update(vd): vd = /api/v4/verdictday (or {failed: true}). */
export function machineCard(ctx) {
  const pill = h("span");
  const body = h("div", {class: "stack tight"});
  const bots = h("span", null, "동전 봇");
  const card = ui.card({plate: "판정 기계", sub: "판정 날 전에 준비됐나", cls: "ckm", acts: [pill]}, body,
    h("p", {class: "muted home-small"}, "연습은 오늘 자료로 판정 과정 전체를 돌려 보는 것입니다 (", bots, "). 결과 숫자는 판정이 아니라서 보이지 않고, 돌았는지만 봅니다. ",
      h("a", {href: ctx.href("server")}, "서버 › 예약 작업 →")));
  card.update = (vd) => {
    if (!vd) { put(body, h("p", {class: "muted"}, "읽는 중…")); put(pill); return; }
    if (vd.machine && vd.machine.rehearsal_bots) bots.textContent = `동전 봇 ${fmt.int(vd.machine.rehearsal_bots)}개`;
    if (vd.failed || !vd.machine) {
      put(pill, ui.pill("확인 못 함", "warn"));
      put(body, h("p", {class: "ck-bad"}, "판정 기계 상태를 불러오지 못했습니다 (없다는 뜻이 아님) · 1분 뒤 다시 시도합니다"));
      return;
    }
    const m = vd.machine;
    const [lk, lc] = LEVEL[m.level] || LEVEL.unknown;
    put(pill, ui.pill(lk, lc));
    // the next Wednesday rehearsal from the road's milestones (deploy/paperbot-rehearsal.timer; skipped on a verdict day)
    const next = (vd.milestones || []).find((x) => x.kind === "rehearsal" && x.ts > (vd.now || 0) && !x.skip);
    put(body, ui.kv([
      ["판정 연습 (매주 수 12:30)", rehearsalLine(m.rehearsal, next)],
      ["판정 작업", jobLine(m, "job")],
      ["연습 타이머", jobLine(m, "rehearsal")],
      ["판정 계산 예상", m.projected_s ? `약 ${fmt.dur(m.projected_s)} (마지막 연습 기준, 동전 봇 ${fmt.int(m.n_bots)}개)` : h("span", {class: "muted"}, "연습 기록이 생기면 나옴")],
    ]));
  };
  card.update(null);
  return card;
}

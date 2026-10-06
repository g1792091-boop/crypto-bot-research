// 24시간 토론방 · the idea card (design step 6, the idea factory): the ONE lab idea the 심판 wrote in a factory or deep
// round, as /api/debate sends it (dash/analysis.py debate_idea: debate.db debate_lab_ideas after the code's check, the
// lab's code result written back by debate_factory.sync_lab). Two kinds of words, kept apart on the card:
//  - the AI's (the 심판's claim, 찬성's and 반대's strongest point, the check 반대 expects to fail): shown as quotes under
//    "AI가 쓴 말";
//  - the code's (what the lab would run: description_ko; the code check; the daily pick; the lab's one-line result and
//    the ①-⑥ checklist with its own numbers; which side was right): shown as plain lines under "코드".
// The stage chip walks 후보 → 오늘 시험 줄 → 연구실 대기 → 시험 중 → 통과 / 불통과, or says why it stopped (이미 시험함
// #n, 비슷한 실패 시험 있음, 문법 밖, 이번엔 안 뽑힘 …): the server's words (stage_ko), never a guess here.
// HONESTY: a pass during the observation period is NOT a proposal (the owners' click after the period, at that day's
// test count); one AI plays every seat, so "누가 맞았나" is a record of the code's sides, never a person's score.
import {h, ui, fmt, store} from "../core/pb.js";
import {sideChip} from "./rooms-kit.js";

/** The stage chip's colour by the server's tone (never a pass/fail colour this side picked). */
const TONE = new Set(["good", "bad", "warn", "accent", "thin"]);
export const stageChip = (idea) => ui.pill((idea && idea.stage_ko) || "—", TONE.has(idea && idea.tone) ? idea.tone : "thin");
/** The lab engine in a few words (labintake.ENGINE_KO, shortened for a list row). */
export const engineShort = (idea) => ({newlab: "새 매매법", labtest: "36개 고쳐 보기"})[idea && idea.engine] || "시험 못 함";

/** The observation period from /api/summary (the shell keeps it), for the pass line; null when unknown. */
function observeUntil() {
  const s = store.get("summary");
  return s && s.observing && s.observe_until ? s.observe_until : null;
}

/** What happens next / why it stopped, one plain line per stage (the server's queue / check words first). */
export function stageNote(idea) {
  const st = idea.stage;
  if (st === "candidate") return "다음 고르기(하루 몫 안에서 코드 점수가 가장 높은 것)에 들면 5년 시험으로 갑니다";
  if (st === "queued") return idea.queue_ko || "오늘 하루 몫으로 뽑힘 · 에이전트가 다음 차례에 5년 시험을 돌립니다";
  if (st === "lab_queued") return "연구실 시험 줄에 들어갔습니다 (에이전트가 회의 뒤 남는 시간에 돌림)";
  if (st === "running") return "5년 시험을 돌리는 중입니다";
  if (st === "passed") {
    const obs = observeUntil();
    return (obs ? `관찰 기간(${fmt.mmdd(obs - 1)}까지)이라 지금은 제안하지 않습니다. 기간 뒤 그때의 시험 수로 다시 판정해 ` : "제안은 그때의 시험 수로 다시 판정해 ")
      + "두 분께 올립니다 (두 분 확인 필요)";
  }
  if (st === "failed") return idea.lab && idea.lab.result_ko ? "" : "관문 미달";   // the lab's own line names the checks
  if (st === "not_picked") return idea.queue_ko || "그날 몫에 들지 못해 시험하지 않았습니다 (시험 수에 넣지 않음)";
  if (st === "duplicate" || st === "near_duplicate" || st === "repeat") return idea.check_ko || "";
  if (["bad_spec", "cannot_express", "refused", "missing"].includes(st)) return `${idea.check_ko || ""} · 시험하지 않았고 시험 수에도 넣지 않았습니다`;
  if (st === "expired") return "기한 안에 차례가 오지 않아 시험하지 않았습니다 (시험 수에 넣지 않음)";
  return idea.lab && idea.lab.status_ko ? `연구실: ${idea.lab.status_ko}` : "";
}

/** The ①-⑥ checklist of a 5-year result (the code's own checks and numbers). */
export function checkList(lab) {
  const cs = (lab && lab.checks) || [];
  if (!cs.length) return null;
  return h("ul", {class: "db-checks", "aria-label": "5년 시험 관문 ①~⑥"}, cs.map((c) => {
    const k = c.ok === true ? "ok" : c.ok === false ? "no" : "na";
    return h("li", {class: k},
      h("b", {class: "db-ck-m"}, c.mark),
      h("span", {class: "db-ck-i", title: k === "ok" ? "통과" : k === "no" ? "미달" : "보지 않음"}, k === "ok" ? "✓" : k === "no" ? "✗" : "–"),
      h("span", {class: "db-ck-n"}, c.name_ko || ""),
      c.num_ko ? h("small", null, c.num_ko) : null);
  }));
}

/** Which side the code's grading says was right (only once the lab really tested it). */
export function rightLine(idea) {
  if (!idea.settled_side) return null;
  const pro = idea.settled_side === "찬성";
  return h("div", {class: "db-right"},
    h("span", {class: "db-right-k"}, "누가 맞았나"), sideChip(idea.settled_side),
    h("span", null, pro ? "맞음 (5년 시험 통과)" : "맞음 (5년 시험 불통과)"),
    idea.con_check && idea.con_check_hit != null ? h("span", {class: "db-right-c"},
      `반대가 짚은 칸 ${idea.con_check}${idea.con_check_ko ? ` ${idea.con_check_ko}` : ""}: ${idea.con_check_hit ? "실제로 떨어짐 (맞힘)" : "그 칸은 넘음 (못 맞힘)"}`) : null);
}

function said(label, text, chip) {
  if (!text) return null;
  return h("div", {class: "db-said"}, h("span", {class: "db-said-k"}, chip || null, label), h("q", null, text));
}

/**
 * ideaCard(idea, {head}) -> the 심판's one idea: engine, stage, what the lab runs (code), the AI's words, the code
 * check, the lab's result with ①-⑥ and who was right. head false: no title line (the list row already has it).
 */
export function ideaCard(idea, o = {}) {
  if (!idea) return null;
  const lab = idea.lab || null;
  const where = lab ? [lab.trial_id ? `장부 #${fmt.int(lab.trial_id)}` : "",
    lab.test_number ? `새 매매법 시험 ${fmt.int(lab.test_number)}번째` : lab.n_trials ? `이 방 시험 ${fmt.int(lab.n_trials)}번째` : "",
    // the bar as the lab's own line writes it (two significant digits: 0.00088, 2.5e-05), never rounded to zero
    lab.threshold_ko ? `기준 p<${lab.threshold_ko}` : ""].filter(Boolean).join(" · ") : "";
  return h("div", {class: ["db-idcard", `st-${idea.stage || "other"}`]},
    o.head === false ? null : h("div", {class: "db-idhead"},
      h("b", null, o.title || "심판이 낸 5년 시험 아이디어"), ui.pill(idea.engine_ko || engineShort(idea), "thin"), stageChip(idea),
      idea.round_kind === "deep" ? ui.pill("깊은 토론", "accent") : null,
      h("span", {class: "db-idno"}, `#${fmt.int(idea.id)}`)),
    // the code's text: what the lab would really run (never the model's words)
    h("div", {class: "db-idwhat"}, h("span", {class: "db-k"}, "시험할 것 · 코드가 옮긴 글"),
      h("b", null, idea.description_ko || (idea.engine === "none" ? "시험으로 옮길 수 없다고 적음" : "옮기지 못함"))),
    (idea.claim_ko || idea.pro_ko || idea.con_ko) ? h("div", {class: "db-idai"},
      h("span", {class: "db-k"}, "AI가 쓴 말 (의견)"),
      said("심판의 주장", idea.claim_ko),
      said("가장 센 근거", idea.pro_ko, sideChip("찬성")),
      said("가장 센 반론", idea.con_ko, sideChip("반대")),
      idea.con_check ? h("p", {class: "db-small"}, `반대가 떨어질 거라 짚은 칸: ${idea.con_check}${idea.con_check_ko ? ` ${idea.con_check_ko}` : ""}`) : null) : null,
    h("div", {class: "db-idcode"},
      h("span", {class: "db-k"}, "코드"),
      // the code check at the time the idea was stored: an idea that passed it says so (not "후보" on a tested idea)
      h("p", {class: "db-small"}, idea.check_status === "ok" ? "검사: 통과 · 시험 후보가 됨" : `검사: ${idea.check_ko || "—"}`),
      stageNote(idea) ? h("p", {class: "db-small"}, stageNote(idea)) : null,
      lab && lab.result_ko ? h("p", {class: "db-labline"}, lab.result_ko) : null,
      lab ? checkList(lab) : null,
      where ? h("p", {class: "db-small"}, where) : null),
    rightLine(idea));
}

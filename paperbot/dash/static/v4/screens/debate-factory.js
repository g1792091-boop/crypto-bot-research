// 24시간 토론방 · the idea factory's cards (design step 6; /api/debate `factory`, dash/analysis.py debate_factory_view,
// read-only from debate.db):
//  - factoryCard: 아이디어 공장. Today (ideas handed to the lab's 5-year queue today against the daily share, the
//    candidates waiting, when the code picks next), the last 20 ideas (tap: the whole card, debate-idea.js), the record
//    (tested, passed, the lab's own base rate; which side was right next to what the lab's usual rates alone would give;
//    the check 반대 named), 왜 떨어졌나 (per check ①-⑥: this room's tested ideas next to the whole lab's share) and the
//    caution that one AI played every seat.
//  - deepBlock: 오늘의 깊은 토론, its own highlighted block: once a day the most important question, argued in THREE
//    separate calls to its own model (1 주장 → 2 반박 → 3 심판, each call reading the earlier ones), its own small
//    budget line inside the month's cap, today's state (due at, skipped by a cap, an error), the three parts side by
//    side on a wide screen and the 심판's idea.
// HONESTY: counts are the server's; nothing is computed into a score here; "맞음" counts stand next to the base rate
// (the lab rarely passes, so 반대 is right almost always by that alone); a small sample is said; text nodes only.
import {h, ui, fmt} from "../core/pb.js";
import {sideChip} from "./rooms-kit.js";
import {ideaCard, stageChip, engineShort} from "./debate-idea.js";
import {roundChat, partsOf, DEEP_PART_KO, castStrip, sidesLine} from "./debate-chat.js";

const MARKS = ["①", "②", "③", "④", "⑤", "⑥"];
const ENGINE_KO = {newlab: "새 매매법 5년 시험", labtest: "36개 고쳐 보기 5년 시험"};
const n2 = (x) => x == null || !Number.isFinite(Number(x)) ? "—" : fmt.num(x, Number(x) % 1 ? 1 : 0);
const usd4 = (x) => x == null || !Number.isFinite(Number(x)) ? "—" : `$${fmt.num(x, 4)}`;
const share = (x) => x == null || !Number.isFinite(Number(x)) ? "—" : fmt.pct(x, 0, false);

/** One list row: when · engine · what it tests (code) · stage; tap: the whole card. */
function ideaRow(it) {
  const region = h("div", {class: "db-fbody", hidden: true});
  const btn = h("button", {class: "db-frow", type: "button", "aria-expanded": "false"},
    h("time", {title: fmt.kst(it.ts)}, fmt.dayKey(it.ts) === fmt.dayKey(Date.now()) ? fmt.hm(it.ts) : fmt.mmdd(it.ts)),
    h("span", {class: "db-fmain"}, h("b", null, it.description_ko || it.check_ko || "시험으로 옮기지 못함"),
      h("small", null, [engineShort(it), it.question_kind_ko, it.round_kind === "deep" ? "깊은 토론" : ""].filter(Boolean).join(" · "))),
    stageChip(it), h("i", {class: "db-hchev", "aria-hidden": "true"}, "›"));
  btn.addEventListener("click", () => {
    const open = btn.getAttribute("aria-expanded") !== "true";
    if (open && !region.firstChild) region.append(ideaCard(it, {head: false}));
    btn.setAttribute("aria-expanded", String(open));
    region.hidden = !open;
  });
  return h("div", {class: "db-fitem", role: "listitem"}, btn, region);
}

/** The record: tested / passed with the lab's own pass rate; who was right next to the base rate; the named check. */
function recordBox(f) {
  const r = f.record || {}, lab = r.lab || {};
  const labLine = ["newlab", "labtest"].filter((e) => lab[e] && lab[e].tests).map((e) =>
    `${e === "newlab" ? "새 매매법" : "36개 고쳐 보기"} ${fmt.int(lab[e].passed)}/${fmt.int(lab[e].tests)} 통과(${share(lab[e].pass_rate)})`).join(" · ");
  const row = (side, right, exp, what) => h("div", {class: "db-rrow"}, sideChip(side),
    h("span", {class: "db-rwhat"}, what), h("b", {class: "num"}, `${fmt.int(right)}번 맞음`),
    h("small", null, r.base_known && exp != null ? `연구실 평소 비율로는 ${n2(exp)}번` : "연구실 평소 비율 수집 전"));
  return h("div", {class: "db-frec"},
    h("h4", null, "기록 · 누가 맞았나"),
    h("div", {class: "db-tiles"},
      h("div", {class: "db-tile"}, h("span", null, "5년 시험함"), h("b", {class: "num"}, fmt.int(r.tested || 0))),
      h("div", {class: "db-tile"}, h("span", null, "통과"), h("b", {class: "num"}, fmt.int(r.passed || 0))),
      h("div", {class: "db-tile"}, h("span", null, "아이디어 전체"), h("b", {class: "num"}, fmt.int(r.ideas || 0)))),
    h("p", {class: "db-small"}, `토론방 아이디어 5년 시험 ${fmt.int(r.tested || 0)}개 · 통과 ${fmt.int(r.passed || 0)}개`
      + (labLine ? ` · 연구실 전체 ${labLine}` : " · 연구실 전체 통과율 수집 전")),
    r.settled ? [row("찬성", r.pro_right, r.pro_expected, "통과에 건 편"), row("반대", r.con_right, r.con_expected, "불통과에 건 편")]
      : h("p", {class: "db-small"}, "아직 결론 난 5년 시험이 없습니다 (시험이 끝나면 코드가 편을 채점합니다)"),
    r.con_check_graded ? h("p", {class: "db-small"}, `반대가 짚은 칸 적중 ${fmt.int(r.con_check_hits)}/${fmt.int(r.con_check_graded)}`
      + (r.base_known && r.con_check_expected != null ? ` · 그 칸들의 평소 탈락률로는 ${n2(r.con_check_expected)}번` : "")) : null,
    r.settled && r.small !== false ? h("p", {class: "db-warn"}, h("b", null, "표본 적음 "),
      `결론 난 시험 ${fmt.int(r.settled)}개 · ${fmt.int(r.small_below || 10)}개 미만은 우연과 구별할 수 없습니다 · 동전 던지기 50%`) : null);
}

/** 왜 떨어졌나: per engine, how often each check failed among this room's tested ideas, next to the lab's share. */
function whyBox(f) {
  const w = f.why_fail || {};
  const engines = ["newlab", "labtest"].filter((e) => w[e] && (w[e].tests || w[e].lab_tests));
  if (!engines.length) return h("div", {class: "db-fwhy"}, h("h4", null, "왜 떨어졌나"),
    h("p", {class: "db-small"}, "아직 5년 시험 결과가 없습니다"));
  return h("div", {class: "db-fwhy"}, h("h4", null, "왜 떨어졌나", h("small", null, "칸마다 미달한 수 · 오른쪽은 연구실 전체 비율")),
    engines.map((e) => {
      const x = w[e], names = x.names_ko || {}, ls = x.lab_share || {};
      return h("div", {class: "db-wset"},
        h("p", {class: "db-wk"}, `${ENGINE_KO[e]} · 토론방 ${fmt.int(x.tests || 0)}개 · 연구실 ${x.lab_tests ? fmt.int(x.lab_tests) + "개" : "수집 전"}`),
        h("ul", {class: "db-wlist"}, MARKS.map((m) => {
          const k = (x.failed || {})[m] || 0, t = x.tests || 0;
          return h("li", null, h("b", null, m), h("span", {class: "db-wn"}, names[m] || ""),
            h("span", {class: "db-wbar", role: "img", "aria-label": t ? `토론방 ${k}/${t}` : "토론방 시험 없음"},
              h("i", {style: {"--w": `${t ? Math.round(100 * k / t) : 0}%`}})),
            h("span", {class: "num"}, t ? `${fmt.int(k)}/${fmt.int(t)}` : "—"),
            h("small", null, ls[m] != null ? `연구실 ${share(ls[m])}` : ""));
        })));
    }));
}

/** The 아이디어 공장 card: {el, render(factory)}. */
export function factoryCard() {
  const ideas = ui.pager({size: 5, empty: "아직 아이디어가 없습니다 (토론마다 심판이 하나씩 냅니다)", row: (x) => ideaRow(x)});
  const head = h("h3", null, "아이디어 공장", h("small", null, "토론마다 심판이 시험할 아이디어 하나 · 코드가 하루 몫만 5년 시험으로"));
  const goal = h("p", {class: "db-goal"});
  const today = h("div", {class: "db-ftoday"});
  const rec = h("div");
  const why = h("div");
  const caution = h("p", {class: "rk-note db-fcaution"});
  const el = h("section", {class: "db-sec db-factory", "aria-label": "아이디어 공장"}, head, goal, today,
    h("h4", null, "아이디어", h("small", null, "새것부터 · 누르면 전체")), ideas.el, rec, why, caution);
  let key = null;
  function render(f) {
    el.hidden = !f;
    if (!f) return;
    const on = f.mode === "factory";
    goal.textContent = `목표: ${f.goal || "많은 매매법을 시험해 결국 돈을 잃지 않는 매매법을 찾는다"}`;
    const t = f.today || {};
    today.replaceChildren(
      h("div", {class: "db-tile"}, h("span", null, "오늘 5년 시험 줄"), h("b", {class: "num"}, `${fmt.int(t.queued || 0)}/${fmt.int(t.cap || 0)}`)),
      h("div", {class: "db-tile"}, h("span", null, "기다리는 후보"), h("b", {class: "num"}, fmt.int(t.candidates || 0))),
      h("div", {class: "db-tile"}, h("span", null, "다음 고르기"), h("b", {class: "num"}, t.next_pick_ts ? fmt.hm(t.next_pick_ts) : "—")),
      h("p", {class: "db-small"}, !on ? `지금은 ${f.mode_ko || "예전 토론 방식"}으로 돌아 새 아이디어를 고르지 않습니다 (기록은 남음)`
        : t.cap ? `하루 ${fmt.int(t.cap)}개까지 코드 점수가 가장 높은 후보를 연구실 5년 시험 줄로 보냅니다 (09:00·21:00). 시험이 늘수록 통과 기준이 엄격해져 몫을 묶어 둡니다.`
          : "하루 몫이 0이라 연구실로 보내지 않습니다 (서버 설정 DEBATE_LAB_PER_DAY)"));
    // the list is redrawn only when the ideas changed (a poll must not fold a card being read)
    const k = (f.ideas || []).map((x) => `${x.id}:${x.stage}:${x.lab ? x.lab.status : ""}`).join(",");
    if (k !== key) { key = k; ideas.set(f.ideas || [], true); }
    rec.replaceChildren(recordBox(f));
    why.replaceChildren(whyBox(f));
    caution.textContent = f.caution || "AI 한 명이 다섯 자리를 맡아 편을 나눈 것이라 사람 성적이 아닙니다.";
  }
  return {el, render};
}

/** 오늘의 깊은 토론 · its own highlighted block: {el, render(factory)}; hidden while the deep debate is off and has
 *  never run. */
export function deepBlock() {
  const meta = h("p", {class: "db-dmeta"});
  const state = h("p", {class: "db-dstate"});
  const steps = h("div", {class: "db-dsteps"});
  const body = h("div", {class: "db-dbody"});
  const el = h("section", {class: "db-deep", "aria-label": "오늘의 깊은 토론"},
    h("div", {class: "db-dhead"}, h("span", {class: "db-dbadge"}, "하루 한 번"), h("h3", null, "오늘의 깊은 토론"),
      h("small", null, "가장 중요한 질문 하나 · 세 번 따로 부름 (주장 → 반박 → 심판)")),
    meta, state, steps, body);
  let shown = null;
  function stateLine(d) {
    const t = d.today || {}, last = t.last;
    if (last && last.status === "ok") return "";
    if (last && last.status === "skipped") return `오늘은 건너뜀: ${last.why || "한도"} · 비용 0`;
    if (last && (last.status === "error" || last.status === "aborted")) return `오늘 시도가 끝나지 못함: ${last.why || "오류"} · 오늘 안에 한 번 더 시도합니다`;
    if (last && last.status === "running") return "지금 깊은 토론 중 (세 번 부르는 중)";
    if (!d.on) return "깊은 토론이 꺼져 있습니다 (서버 설정 DEBATE_DEEP)";
    if (t.due_ts && t.due_ts > Date.now()) return `오늘은 ${fmt.hm(t.due_ts)}(한국 시간)부터 · 아직 전`;
    return "오늘 깊은 토론을 기다리는 중";
  }
  function render(f) {
    const d = (f && f.deep) || null;
    const r = d && d.round;
    el.hidden = !d || (!d.on && !r);
    if (el.hidden) return;
    meta.replaceChildren(...[
      d.model ? h("span", {class: "db-dmodel"}, d.model) : null,
      h("span", null, `깊은 토론 몫 이번 달 ${usd4(d.month)}${d.cap != null ? ` / ${fmt.usd(d.cap)}` : ""} (월 한도 안)`),
      r ? h("span", null, `${fmt.kst(r.ts)} · 발언 ${fmt.int((r.messages || []).filter((m) => m.part).length)}개 · ${usd4(r.cost_usd)}`) : null].filter(Boolean));
    const sl = stateLine(d);
    state.textContent = sl;
    state.hidden = !sl;
    if (!r) { steps.replaceChildren(); body.replaceChildren(h("p", {class: "db-none"}, h("b", null, "아직 끝난 깊은 토론이 없습니다"),
      h("span", null, `하루 한 번 ${d.at || "정해진 시각"}(한국 시간)부터, 그날 가장 중요한 질문을 세 번 따로 불러 토론합니다.`))); shown = null; return; }
    if (shown === r.round_id) return;               // the same stored round: leave it as the reader left it
    shown = r.round_id;
    const got = partsOf(r);
    steps.replaceChildren(ui.stepStrip(Object.keys(DEEP_PART_KO).map((p) => ({id: p, label: `${DEEP_PART_KO[p][0]} ${p}`})),
      {done: got, label: "깊은 토론 세 부분 (저장된 것만 켜짐)"}));
    body.replaceChildren(...[castStrip(r), sidesLine(r), roundChat(r)].filter(Boolean));
  }
  return {el, render};
}

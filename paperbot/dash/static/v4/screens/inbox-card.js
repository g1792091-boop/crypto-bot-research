// 결재함 · one proposal card (review addition 8): what a copy changes, the 5-year test per period (원본 vs 바꾼 것), the
// staff's for / against lines from the meeting that made it, the code gate, what approving does and what not clicking
// does, then 승인 / 거절 with a confirm step. The click goes to the EXISTING POST /api/proposals/<id>/decide (dash/app.py
// Rooms.decide re-checks everything: the gate, the gate judged again with the room's tests now, an earlier reject, a
// started account) and its own Korean answer is shown as is; nothing here decides or approves anything by itself.
// Data: /api/v4/approvals (dash/more/approvals.py). HONESTY: the table is the 5-year PAST test (참고, not the paper
// accounts), every line is a stored line, a missing table says so.
import {h, ui, fmt} from "../core/pb.js";
import {specKo, agentsState} from "./rooms-kit.js";

const RE_APPROVE = ["stale_ok", "owner_click_missing"];
const EXTRA_KO = {active: "도는 중", suspended: "멈춤(보류)", held: "정지(동결)"};
const TONE = {for: "good", against: "bad", neutral: "thin"};

/** When the agents tick applies a click (rooms-side.js decisionWhen: the same words). */
export function decisionWhen(st) {
  return ["stopped", "error", "new"].includes(st) ? "에이전트가 멈춰 있어 아직 반영되지 않습니다 (다시 돌기 시작하면 코드가 반영)"
    : "다음 차례(15분 안)에 코드가 반영합니다";
}

/** The one-line title of a proposal: a copy's changed rule ("첫 익절 잠금 +6%"), a new strategy's description. */
export function titleOf(c) {
  if (c.kind === "newlab") return c.title_ko || "새 매매법";
  return c.rule_ko || (c.test ? specKo(c.test).replace(/로$|부터$/, "") : "규칙 한 가지");
}

/** "이 방 4번째 시험 → 기준 p < 0.05 ÷ 4 = 0.0125" (the gate's own count; the count now when it grew). */
export function bar(c) {
  const g = c.gate || {}, gn = c.gate_now || {};
  const n = c.kind === "newlab" ? (g.n_tests != null ? g.n_tests + 1 : g.test_number) : (gn.n_trials || g.n_trials);
  if (!n) return null;
  return {n, alpha: 0.05 / n, where: c.kind === "newlab" ? `새 매매법 시험 ${fmt.int(n)}번째` : `이 방 ${fmt.int(n)}번째 시험`};
}

const pctOr = (x, d = 1) => (x == null ? "—" : fmt.pct(x, d));

function periodTable(c) {
  const rows = c.periods || [];
  if (!rows.length) return h("p", {class: "ibx-none"}, "이 제안의 시험 결과에 기간별 숫자가 없습니다 (아래 '판정 근거'에 코드가 적은 줄이 있습니다).");
  const body = [];
  for (const r of rows) {
    // the period on its own row ("1기간 · 2021-08~2024-06"), its arms under it: four columns fit a 390 px phone
    const [name, months] = String(r.label).split(" (");
    body.push(h("tr", {class: "ibx-prow"}, h("td", {class: "l", colspan: "4"}, h("b", null, name), months ? h("span", {class: "muted"}, ` · ${months.replace(/\)$/, "")}`) : null,
      r.available ? null : h("span", {class: "muted"}, ` · ${r.why || "자료 없음"}`))));
    if (!r.available) continue;
    for (const a of r.arms) body.push(h("tr", null,
      h("td", {class: ["l", a.label === "바꾼 것" || a.label === "새 매매법" ? "ibx-new" : ""]}, a.label),
      h("td", {class: "num"}, a.trades == null ? "—" : `${fmt.int(a.trades)}건`),
      h("td", {class: ["num", fmt.tone(a.mean_roe)]}, pctOr(a.mean_roe, 2)),
      h("td", {class: ["num", fmt.tone(a.pnl_equity)]}, pctOr(a.pnl_equity, 2))));
    if (r.diff != null && c.kind === "newlab") body.push(h("tr", null, h("td", {class: "l muted"}, r.diff_ko),
      h("td", {class: ["num", fmt.tone(r.diff)], colspan: "3"}, `${fmt.num(r.diff * 100, 2, true)}%p`)));
  }
  return h("div", {class: "tbl-wrap ibx-tw"}, h("table", {class: "tbl ibx-tbl"},
    h("thead", null, h("tr", null, h("th", {class: "l"}, c.kind === "newlab" ? "5년 시험" : "규칙"),
      h("th", null, "거래"), h("th", null, "거래당 ROE"), h("th", null, "자금 대비"))),
    h("tbody", null, body)));
}

function voiceList(c) {
  const vs = c.voices || [];
  if (!vs.length) return h("p", {class: "ibx-none"}, "이 제안을 만든 회의의 발언 기록을 찾지 못했습니다.");
  return h("ul", {class: "ibx-voices"}, vs.map((v) => h("li", null, ui.pill(v.stance, TONE[v.tone] || "thin"),
    h("b", null, v.name), h("span", null, v.text))));
}

/** What approving does / what not clicking does, in plain words from the proposal's own facts. */
export function effects(c, period) {
  const b = bar(c);
  const yes = c.kind === "newlab"
    ? ["새 매매법으로 새 모의 계좌 1개가 시작됩니다 (청산·크기·비용은 지금과 같음)", "원래 계좌들은 그대로입니다"]
    : [`원본 ${c.parent ? fmt.idName(c.parent) : "계좌"}에서 '${titleOf(c)}' 하나만 바꾼 새 모의 계좌 1개 (원본과 같은 시작 자금)`, "원본 계좌는 그대로입니다"];
  yes.push("그 계좌는 시작하고 30일이 지난 뒤의 판정 날에 따로 판정합니다");
  if (b && c.kind !== "newlab") yes.push(`${b.where}이라 통과 기준이 p < 0.05 ÷ ${fmt.int(b.n)} = ${fmt.num(b.alpha, 4)}였습니다 (여러 번 시험한 만큼 엄격하게)`);
  yes.push(c.runtime_ready ? "코드가 한 번 더 확인한 뒤 다음 봉 경계에 시작하고, 시작된 계좌는 거절로 멈출 수 없습니다"
    : "지금은 실행기의 추가 계좌 기능이 꺼져 있어 바로 시작되지 않습니다 (켜진 뒤 한 번 더 승인)");
  const no = ["대기로 남고 아무 계좌도 시작되지 않습니다", "기다리는 동안 복제 자리 하나를 차지합니다 (매매법마다 1개, 전체 10개)",
    "그 방에서 시험이 더 늘면 기준이 엄격해져 나중에는 승인할 수 없게 될 수 있습니다"];
  if (c.kind === "newlab") no.splice(1, 1, "기다리는 동안 새 매매법 자리 하나를 차지합니다 (전체 10개)");
  return {yes, no, okUntil: period && period.owner_ok_until};
}

/**
 * The card. c: a /api/v4/approvals proposal, o: {ctx, period, ov (rooms overview, for when a click is applied),
 * onDone(): reload the 결재함, open: start with the evidence unfolded}.
 */
export function proposalCard(c, o) {
  const {ctx} = o;
  const st = {confirm: null};
  const box = h("div", {class: "ibx-act"});
  const err = h("p", {class: "ibx-err", role: "alert", hidden: true});
  const g = c.gate || {}, gn = c.gate_now;
  const stale = !!(gn && gn.pass === false);
  const fx = effects(c, o.period);
  const od = c.owner_decision;

  function decideBox() {
    if (od && !od.applied) {
      return h("p", {class: "ibx-done"}, "두 분 결정: ", h("b", null, od.decision === "approve" ? "승인" : "거절"), ` · ${decisionWhen(agentsState(o.ov).st)}`);
    }
    if (st.confirm) {
      const ap = st.confirm.dec === "approve";
      const go = h("button", {class: ["btn-line", ap ? "ok" : "bad"], type: "button", dataset: {dec: st.confirm.dec}}, `${ap ? "승인" : "거절"} 확인`);
      go.addEventListener("click", async () => {
        go.disabled = true; err.hidden = true;
        try {
          const d = await ctx.post(`/api/proposals/${encodeURIComponent(c.id)}/decide`, {decision: st.confirm.dec, note: st.confirm.note || ""});
          const a = agentsState(o.ov);
          ctx.toast(["ok", "login"].includes(a.st) ? ((d && d.message) || "전달했습니다") : `저장했습니다. ${decisionWhen(a.st)}`);
          st.confirm = null;
          if (o.onDone) o.onDone();
        } catch (e) {
          go.disabled = false;
          err.hidden = false; err.textContent = (e && e.detail) || "보내지 못했습니다. 잠시 뒤 다시 시도해 주세요";
        }
      });
      return h("div", {class: "ibx-confirm"},
        h("p", null, ap ? (c.runtime_ready
          ? `정말 승인할까요? 승인하면 코드가 다시 확인한 뒤 다음 봉 경계에 새 모의 계좌가 시작됩니다 (${c.kind === "newlab" ? "다른 계좌들과" : "원본 계좌와"} 같은 시작 자금). 시작된 계좌는 거절로 멈출 수 없습니다.`
          : "정말 승인할까요? 계좌는 아직 만들어지지 않습니다 (실행기의 추가 계좌 기능이 켜지기 전). 기능이 켜진 뒤 한 번 더 승인을 눌러야 시작합니다.")
          : "정말 거절할까요? 거절한 제안은 다시 승인할 수 없습니다."),
        h("div", {class: "row wrap"}, go, h("button", {class: "btn-line", type: "button", onclick: () => { st.confirm = null; paint(); }}, "취소")));
    }
    const note = h("input", {class: "search ibx-note", type: "text", maxlength: 1000, placeholder: "메모 (선택)", "aria-label": "메모"});
    const ask = (dec) => { st.confirm = {dec, note: note.value}; paint(); };
    if (stale) return h("div", {class: "stack tight"}, h("p", {class: "ibx-warn"}, "이 방 시험이 늘어 지금 기준으로는 코드 관문을 통과하지 못합니다. 승인할 수 없고 거절만 할 수 있습니다."),
      h("div", {class: "row wrap"}, h("button", {class: "btn-line bad", type: "button", onclick: () => ask("reject")}, "거절")));
    return h("div", {class: "ibx-decide"}, note, h("div", {class: "row wrap"},
      h("button", {class: "btn-y", type: "button", onclick: () => ask("approve")}, "승인"),
      h("button", {class: "btn-line bad", type: "button", onclick: () => ask("reject")}, "거절")));
  }
  function paint() { box.replaceChildren(decideBox(), err); }
  paint();

  const b = bar(c);
  const run = c.account_running, ref = c.runtime_refusal;
  return h("article", {class: ["card", "ibx-card", od && !od.applied ? "done" : ""], id: `ibx-${c.id}`, "aria-label": `제안 #${c.id}`},
    h("div", {class: "ibx-head"},
      h("span", {class: "ibx-no"}, `제안 #${c.id}`),
      h("span", {class: "ibx-kind"}, c.kind === "newlab" ? "새 매매법 계좌" : "복제 계좌"),
      h("a", {class: "ibx-room", href: ctx.href("rooms", c.room_id)}, c.room_title || c.room_id, " →"),
      h("span", {class: "grow"}), h("time", {class: "muted"}, fmt.kst(c.ts))),
    h("p", {class: "ibx-title"}, c.kind === "newlab" ? "새 매매법: " : `${c.parent ? fmt.idName(c.parent) : c.strategy_ko || ""} · 바꾸는 한 가지 `,
      h("b", {class: "ibx-rule"}, titleOf(c))),
    c.why ? h("p", {class: "ibx-why"}, h("span", {class: "muted"}, "이유 "), c.why) : null,
    h("div", {class: "ibx-grid"},
      h("section", {class: "ibx-sec"}, h("h3", null, "5년 과거 시험 · 기간별"), periodTable(c),
        h("p", {class: "note"}, "거래당 ROE = 증거금 대비 · 자금 대비 = 거래 한 번이 계좌 자금을 몇 % 움직였나 · 지난 5년 자료의 시험이라 참고입니다 (지금 모의 계좌 성적 아님).")),
      h("section", {class: "ibx-sec"}, h("h3", null, "직원 의견 (이 제안을 만든 회의)"), voiceList(c),
        h("div", {class: "row wrap ibx-gate"}, "코드 관문 ", g.pass === true ? ui.pill("통과", "good") : ui.pill("불통과", "bad"),
          b ? h("span", {class: "muted"}, ` ${b.where} · 기준 p < ${fmt.num(b.alpha, 4)}`) : null,
          gn ? [" · 지금 다시 판정 ", gn.pass === true ? ui.pill("통과", "good") : ui.pill("불통과", "bad")] : null),
        (g.reasons || []).length ? ui.disclosure("판정 근거 (코드가 쓴 줄)", h("ul", {class: "ibx-reasons"}, g.reasons.map((x) => h("li", null, String(x))))) : null)),
    h("div", {class: "ibx-grid"},
      h("section", {class: "ibx-sec ibx-yes"}, h("h3", null, "승인하면"), h("ul", null, fx.yes.map((x) => h("li", null, x)))),
      h("section", {class: "ibx-sec ibx-no"}, h("h3", null, "안 누르면"), h("ul", null, fx.no.map((x) => h("li", null, x))))),
    run ? h("p", null, ui.pill("계좌 시작됨", "good"), ` ${run.label_ko || fmt.idName(run.account_id)}${run.extra_status && run.extra_status !== "active" ? ` · ${EXTRA_KO[run.extra_status] || run.extra_status}` : ""}`) : null,
    !run && ref ? h("p", {class: "muted"}, `실행기: ${ref.text_ko || ref.code}${RE_APPROVE.includes(ref.code) ? " (한 번 더 승인 필요)" : ""}`) : null,
    box);
}

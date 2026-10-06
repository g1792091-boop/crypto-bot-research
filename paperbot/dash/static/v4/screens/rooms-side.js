// 에이전트 방 · the info pane (builder D): proposals waiting for the owners (approve / reject with a note, a confirm
// step and the server's own Korean answer), when the room meets, members and duties, past proposals, notes, the
// hypothesis ledger and today's AI use (gauges against the caps). Old rooms.js renderRoomSide, item by item. Design
// 102 C: a strategy room's sides and disputes, the lab room's shared test queue (disputes-kit.js).
// The approve / reject click goes to POST /api/proposals/<id>/decide; the server re-checks everything and refuses with
// a Korean message that is shown as is.
import {h, ui, fmt, motion} from "../core/pb.js";
import {specKo, avatarFor, agentsState, keptHoursKo, scheduleOf} from "./rooms-kit.js";
import {roomSides, labIntake} from "./disputes-kit.js";
import {ownerRequests} from "./labreq-kit.js";

const PSTATUS_KO = {awaiting_owner: "두 분 확인 대기", approved: "승인됨", rejected: "거절됨", blocked_gate: "코드 관문에서 막힘", blocked_cap: "복제 한도로 막힘"};
const TRIAL_KIND_KO = {hypothesis: "가설", test: "5년 시험", copy_proposal: "복제 제안", newlab: "새 매매법 시험"};
const TRIAL_ST = {passed: ["통과", "good"], failed: ["불통과", "bad"], described: ["설명용", "thin"], no_data: ["자료 없음", "thin"], error: ["오류", "bad"]};
const NL_ST = {passed: ["통과 · 제안 대기", "good"], proposed: ["통과 · 두 분께 제안함", "good"], lapsed: ["통과했다가 기준 미달", "warn"], failed: ["불통과", "bad"]};
const RE_APPROVE = ["stale_ok", "owner_click_missing"];
const LAB_ROOM = "team:lab";
const NEWLAB_MAX_TESTS = 5000;       // newlab.max_passable_n() + 1 (old rooms.js)
const EXTRA_KO = {active: "도는 중", suspended: "멈춤(보류)", held: "정지(동결)"};

function decisionWhen(st) {
  return ["stopped", "error", "new"].includes(st) ? "에이전트가 멈춰 있어 아직 반영되지 않습니다 (다시 돌기 시작하면 코드가 반영)"
    : "다음 차례(15분 안)에 코드가 반영합니다";
}

export function makeSide(ctx, hooks) {
  const st = {id: null, room: null, side: null, confirm: null, req: 0, usage: null, labConfirm: {id: null, dec: null}};
  const back = h("button", {class: "btn-line rm-back", type: "button", onclick: () => hooks.pane("chat")}, "← 대화");
  const titleEl = h("b", {class: "rm-stitle"}, "방 정보");
  const body = h("div", {class: "rm-sbody"}, ui.empty("방을 고르면 정보가 나옵니다"));
  const el = h("aside", {class: "rm-side", "aria-label": "방 정보"}, h("div", {class: "rm-shead"}, back, titleEl), body);

  const sec = (title, ...kids) => h("section", {class: "rm-sec"}, h("h3", null, title), kids);

  // ---------------------------------------------------------------- proposals
  function decideBox(p, mode) {
    const a = agentsState(hooks.ov());
    if (st.confirm && st.confirm.id === p.id) {
      const ap = st.confirm.dec === "approve";
      const apText = p.runtime_ready
        ? "정말 승인할까요? 승인하면 코드가 다시 확인한 뒤 다음 5분 봉 경계에 새 모의 계좌가 시작됩니다 (원본 계좌와 같은 시작 자금). 시작된 계좌는 거절로 멈출 수 없습니다."
        : "정말 승인할까요? 계좌는 아직 만들어지지 않습니다 (실행기의 추가 계좌 기능이 켜지기 전). 기능이 켜진 뒤 한 번 더 승인을 눌러야 시작합니다.";
      const go = h("button", {class: ["btn-line", ap ? "ok" : "bad"], type: "button"}, `${ap ? "승인" : "거절"} 확인`);
      const err = h("p", {class: "rm-err", hidden: true, role: "alert"});
      go.addEventListener("click", async () => {
        go.disabled = true;
        try {
          const d = await ctx.post(`/api/proposals/${encodeURIComponent(p.id)}/decide`, {decision: st.confirm.dec, note: st.confirm.note || ""});
          ctx.toast(["ok", "login"].includes(a.st) ? ((d && d.message) || "전달했습니다") : `저장했습니다. ${decisionWhen(a.st)}`);
          st.confirm = null;
          load(); hooks.refreshOv();
        } catch (e) {
          go.disabled = false;
          err.hidden = false; err.textContent = (e && e.detail) || "보내지 못했습니다. 잠시 뒤 다시 시도해 주세요";
        }
      });
      return h("div", {class: "rm-confirm"}, h("p", null, ap ? apText : "정말 거절할까요? 거절한 제안은 다시 승인할 수 없습니다."),
        h("div", {class: "row wrap"}, go, h("button", {class: "btn-line", type: "button", onclick: () => { st.confirm = null; render(); }}, "취소")), err);
    }
    const ask = (dec, note) => { st.confirm = {id: p.id, dec, note: note ? note.value : ""}; render(); };
    if (mode === "again") return h("div", {class: "row wrap"}, h("button", {class: "btn-line ok", type: "button", onclick: () => ask("approve")}, "다시 승인"),
      h("button", {class: "btn-line bad", type: "button", onclick: () => ask("reject")}, "거절로 바꾸기"));
    if (mode === "reject-only") return h("div", {class: "row wrap"}, h("button", {class: "btn-line bad", type: "button", onclick: () => ask("reject")}, "거절로 바꾸기"));
    if (mode === "stale") return h("div", {class: "row wrap"}, h("button", {class: "btn-line bad", type: "button", onclick: () => ask("reject")}, "거절"));
    const note = h("input", {class: "search rm-note", type: "text", maxlength: 1000, placeholder: "메모 (선택)", "aria-label": "메모"});
    return h("div", {class: "rm-decide"}, note, h("div", {class: "row wrap"},
      h("button", {class: "btn-line ok", type: "button", onclick: () => ask("approve", note)}, "승인"),
      h("button", {class: "btn-line bad", type: "button", onclick: () => ask("reject", note)}, "거절")));
  }
  function propCard(p) {
    const ch = p.change || {}, g = p.gate || {}, od = p.owner_decision, gn = p.gate_now;
    const lab = p.kind === "newlab", run = p.account_running, ref = p.runtime_refusal;
    const stale = !!(gn && gn.pass === false && (p.status === "awaiting_owner" || p.status === "approved"));
    let acts = null;
    if (od && !od.applied) {
      acts = h("div", null, h("p", {class: "rm-done"}, "두 분 결정: ", h("b", null, od.decision === "approve" ? "승인" : "거절"), ` · ${decisionWhen(agentsState(hooks.ov()).st)}`),
        p.effective_status === "approved" && !run ? decideBox(p, "reject-only") : null);
    } else if (p.status === "awaiting_owner") acts = decideBox(p, stale ? "stale" : null);
    else if (p.status === "approved" && !run && ref && RE_APPROVE.includes(ref.code)) acts = decideBox(p, "again");
    const prop = (lab && ch.proposal) || {};
    const n = lab ? (g.n_tests != null ? g.n_tests + 1 : null) : g.n_trials;
    const nowN = gn && gn.n_trials != null ? (lab ? gn.n_trials + 1 : gn.n_trials) : null;
    const gatePill = (x) => x === true ? ui.pill("통과", "good") : ui.pill("불통과", "bad");
    return h("div", {class: "rm-prop"},
      h("div", {class: "rm-ptitle"}, lab ? `새 매매법 제안 #${p.id}${p.trial_id ? ` · 장부 #${p.trial_id}` : ""}` : `제안 #${p.id} · ${p.strategy_ko || p.strategy || ""}`),
      h("p", null, h("b", null, lab ? (prop.description_ko || (ch.account && ch.account.spec ? specKo(ch.account.spec) : "새 매매법")) : specKo(ch.test))),
      lab ? h("p", null, "같은 규칙(청산·크기·비용 그대로)의 새 모의 계좌로 새 자료에서 확인하자는 제안") : null,
      !lab && ch.account && ch.account.parent ? h("p", null, `원본 계좌 ${fmt.idName(ch.account.parent)}와 같고 이 규칙 하나만 바꾼 새 모의 계좌`) : null,
      ch.why ? h("p", null, `이유: ${ch.why}`) : null,
      ch.approver ? h("p", null, `자율 승인관: ${ch.approver.approve ? "승인" : "거부"} — ${ch.approver.reason || ""}`) : null,
      h("p", {class: "row wrap"}, `코드 관문${gn ? " (제안 때)" : ""}`, gatePill(g.pass === true),
        n ? h("span", {class: "muted"}, lab ? `새 매매법 시험 ${fmt.int(n)}번 기준` : `이 방 ${fmt.int(n)}번째 시험`) : null),
      gn ? h("p", {class: "row wrap"}, `지금 다시 판정 (${lab ? `새 매매법 시험 ${fmt.int(nowN)}번 기준` : `이 방 시험 ${fmt.int(gn.n_trials)}번 기준`})`, gatePill(gn.pass === true),
        gn.pass === false ? h("span", {class: "muted"}, "승인할 수 없음") : null) : null,
      stale && gn.n_trials && !lab ? h("p", {class: "muted"}, `이 방 시험이 ${fmt.int(gn.n_trials)}번으로 늘어 기준이 p < 0.05 ÷ ${fmt.int(gn.n_trials)}로 엄격해졌습니다. 위는 제안 때의 판정입니다.`) : null,
      (g.reasons || []).length ? ui.disclosure("판정 근거", h("ul", null, g.reasons.map((x) => h("li", null, String(x))))) : null,
      run ? h("p", null, ui.pill("계좌 시작됨", "good"), ` ${run.label_ko || fmt.idName(run.account_id)}${run.extra_status && run.extra_status !== "active" ? ` · ${EXTRA_KO[run.extra_status] || run.extra_status}` : ""} · 거절로 멈출 수 없음`) : null,
      !run && ref ? h("p", null, `실행기: ${ref.text_ko || ref.code}${RE_APPROVE.includes(ref.code) ? " (아래 '다시 승인')" : ""}`) : null,
      // the same proposal in the 결재함, with its 5-year table per period, the for / against lines and what approving does
      p.status === "awaiting_owner" ? h("a", {class: "rm-ibx", href: ctx.href("inbox", null, {p: p.id})}, "결재함에서 근거와 함께 보기 →") : null,
      acts);
  }
  const propTitle = (p) => {
    const ch = p.change || {};
    if (p.kind === "newlab") return `새 매매법 ${(ch.proposal && ch.proposal.description_ko) || (ch.account && ch.account.spec ? specKo(ch.account.spec) : "")}`;
    return specKo(ch.test);
  };

  // ---------------------------------------------------------------- ledger
  function ledgerRow(t) {
    const sp = t.spec || {};
    let label, pill = null;
    if (t.kind === "newlab") {
      const body = (t.result && t.result.result) || {}, s = t.result && t.result.status;
      label = `새 매매법 #${t.id}${body.test_number ? ` (시험 ${body.test_number}번째)` : ""} · ${body.description_ko || specKo(sp)}`;
      if (s) pill = ui.pill(...(NL_ST[s] || [s, "thin"]));
    } else if (t.kind === "copy_proposal") {
      const s = t.proposal_status;
      label = `${t.proposal_id != null ? `복제 제안 #${t.proposal_id}` : "복제 제안"} · ${specKo(sp.test)}${sp.from_trial != null ? ` (시험 #${sp.from_trial})` : ""}`;
      if (s) pill = ui.pill(PSTATUS_KO[s] || s, s === "approved" ? "good" : s === "awaiting_owner" ? "accent" : String(s).startsWith("blocked") || s === "rejected" ? "bad" : "thin");
    } else {
      label = `${t.kind === "test" ? `시험 #${t.id}` : `기록 #${t.id} ${TRIAL_KIND_KO[t.kind] || t.kind}`} · ${specKo(sp)}`;
      if (t.result) pill = ui.pill(...(TRIAL_ST[t.result.status] || [t.result.status, "thin"]));
    }
    return h("div", {class: "rm-trow"}, h("span", null, label), pill);
  }

  // ---------------------------------------------------------------- AI use
  function usageBlock(u) {
    if (!u) return null;
    const g = (name, v, cap, disp, capDisp) => ui.gauge({name, value: v, cap: cap || null, display: disp, capDisplay: capDisp});
    return sec("오늘 AI 사용",
      h("div", {class: "rm-gauges"},
        g("호출", u.calls, u.cap_calls, fmt.int(u.calls), fmt.int(u.cap_calls)),
        g("토큰", u.tokens, u.cap_tokens, fmt.compact(u.tokens), fmt.compact(u.cap_tokens)),
        ...(u.classes || []).map((c) => ui.gauge({name: c.class === "research" ? "새 매매법 연구" : c.name_ko, value: c.calls,
          cap: c.cap_calls || null, display: `${fmt.int(c.calls)}회 · ${fmt.compact(c.tokens || 0)}`, capDisplay: c.cap_calls ? `${fmt.int(c.cap_calls)}회` : null,
          ratio: Math.max(c.cap_calls ? (c.calls || 0) / c.cap_calls : 0, c.cap_tokens ? (c.tokens || 0) / c.cap_tokens : 0)})),
        u.week ? g("최근 7일 호출", u.week.calls, u.week.cap_calls, fmt.int(u.week.calls), fmt.int(u.week.cap_calls)) : null),
      h("p", {class: "rk-note"}, `두 분의 Claude 구독 사용량을 함께 씁니다 (돈이 더 들지 않음, 한도만). 한도에 닿으면 회의를 다음으로 미룹니다. 사고 점검과 ${keptHoursKo((hooks.ov() || {}).hours)} 회의 몫은 늘 남겨 둡니다.`));
  }

  // ---------------------------------------------------------------- render
  function render() {
    if (!st.id) return;
    const r = hooks.cur(), info = st.room;
    titleEl.textContent = `${(r || info || {}).title || st.id} 정보`;
    if (!st.side) { body.replaceChildren(motion.shimmer(3)); return; }
    const {notes = [], trials = null, props = [], intake = null, disputes = null} = st.side;
    const kids = [];
    const waiting = props.filter((p) => p.status === "awaiting_owner");
    const past = props.filter((p) => p.status !== "awaiting_owner").slice(0, 5);
    if (waiting.length) {
      const open = waiting.filter((p) => p.effective_status === "awaiting_owner").length;
      const ready = props.some((p) => p.runtime_ready);
      kids.push(h("section", {class: "rm-sec hl", id: "rm-props"}, h("h3", null, "두 분 확인이 필요한 제안 ", open ? ui.pill(fmt.int(open), "accent") : ui.pill("결정함 · 반영 대기", "thin")),
        waiting.map(propCard),
        h("p", {class: "rk-note"}, ready ? "승인하면 실행기가 코드로 다시 확인한 뒤 원본 계좌와 같은 시작 자금의 새 모의 계좌로 따로 시작합니다. 시작된 계좌는 거절로 멈출 수 없습니다."
          : "승인해도 아직 계좌가 만들어지지 않습니다 (실행기의 추가 계좌 기능이 켜지기 전). 그 전에 한 승인은 한 번 더 눌러야 합니다.",
        " 원본 계좌와 규칙은 그대로입니다. 코드 관문을 통과하지 못한 제안은 누구도 승인할 수 없습니다.")));
    }
    kids.push(sec("이 방은 언제 회의하나요", h("p", null, scheduleOf(st.id, info, r) || "—"),
      h("p", {class: "rk-note"}, "직원들이 스스로 회의를 열고 결정합니다. 두 분이 글을 남기면 다음 차례에 그 이야기도 다룹니다.")));
    if (info && info.members_info) kids.push(sec(`멤버 ${fmt.int(info.members_info.length)}명`, h("div", {class: "rm-mems"},
      info.members_info.map((m) => h("div", {class: "rm-mem"}, avatarFor(hooks.roles(), m.id, m.name), h("div", null, h("b", null, m.name), h("small", null, m.duty || "")))))));
    if (past.length) kids.push(sec("지난 제안", past.map((p) => h("div", {class: "rm-past"},
      h("div", {class: "rm-trow"}, h("span", null, `제안 #${p.id} ${propTitle(p)}`),
        ui.pill(PSTATUS_KO[p.effective_status] || p.effective_status, p.effective_status === "approved" ? "good" : String(p.effective_status).startsWith("blocked") ? "bad" : "thin"),
        p.account_running ? ui.pill("계좌 시작됨", "good") : null),
      p.status === "approved" && !p.account_running && p.runtime_refusal ? h("p", {class: "muted"}, `실행기: ${p.runtime_refusal.text_ko || p.runtime_refusal.code}`) : null,
      p.status === "approved" && !p.account_running && !(p.owner_decision && !p.owner_decision.applied)
        ? decideBox(p, p.runtime_refusal && RE_APPROVE.includes(p.runtime_refusal.code) ? "again" : "reject-only") : null))));
    const noteRow = (n) => h("div", {class: "rm-nrow"}, h("p", null, n.text), h("time", null, fmt.kst(n.ts)));
    kids.push(sec(`메모 ${fmt.int(notes.length)}`, notes.length ? [notes.slice(0, 5).map(noteRow),
      notes.length > 5 ? ui.disclosure(`나머지 ${fmt.int(notes.length - 5)}개`, notes.slice(5, 20).map(noteRow)) : null] : h("p", {class: "muted"}, "아직 메모가 없습니다")));
    if (trials) {
      const c = trials.counts || {}, lab = st.id === LAB_ROOM, nl = c.newlab || 0, rows = trials.trials || [];
      const passes = lab ? rows.filter((t) => t.kind === "newlab" && t.result && ["passed", "proposed", "lapsed"].includes(t.result.status)) : [];
      const sc = trials.scorecard && trials.scorecard.total;
      kids.push(sec(lab ? "가설 장부 · 새 매매법 연구실" : st.id.startsWith("team:") ? "가설 장부 · 전체 매매법" : "가설 장부",
        h("div", {class: "stats"}, lab ? [ui.stat("새 매매법 시험", fmt.int(nl)), ui.stat("통과", fmt.int(c.newlab_passed || 0)),
          ui.stat("통과 가능 남은 시험", fmt.int(Math.max(0, NEWLAB_MAX_TESTS - nl)))]
          : [ui.stat("가설", fmt.int(c.hypothesis || 0)), ui.stat("5년 시험", fmt.int(c.test || 0)), ui.stat("복제 제안", fmt.int(c.copy_proposal || 0))]),
        passes.length ? [h("p", {class: "rk-note"}, "관문을 통과한 새 매매법"), passes.map(ledgerRow)] : null,
        rows.filter((t) => !passes.includes(t)).slice(0, 5).map(ledgerRow),
        trials.research && trials.research.total ? h("p", {class: "rk-note"}, `연구에서 같은 5년 자료로 이미 한 시험 ${fmt.int(trials.research.total)}건: 효과가 확인된 것은 없습니다.`) : null,
        sc && sc.graded ? h("p", {class: "rk-note"}, `가설 채점: 맞음 ${fmt.int(sc.correct)} / 채점 ${fmt.int(sc.graded)} · 기다리는 중 ${fmt.int(sc.waiting)} `, ui.smallSample(sc.graded, 10)) : null,
        h("p", {class: "rk-note"}, lab ? `새 매매법 시험은 모든 방을 합쳐 셉니다. 시험이 늘수록 통과 기준이 엄격해지고 (p < 0.05 ÷ 시험 번호), ${fmt.int(NEWLAB_MAX_TESTS)}번째 뒤에는 어떤 시험도 통과할 수 없어 멈춥니다. 관찰 기간에는 제안하지 않습니다.`
          : "시험을 많이 할수록 통과 기준이 엄격해집니다 (우연 방지).")));
    }
    // design 102 C: a strategy room's sides and disputes; the lab room's shared test queue
    if (disputes) kids.push(roomSides({sides: disputes.seats, disputes: disputes.disputes, base_rates: disputes.base_rates}));
    if (st.id === LAB_ROOM) kids.push(labIntake(intake));
    // #103: the owners' own test requests, their translation and the 시험하기 / 그만두기 click (labreq-kit.js)
    if (st.id === LAB_ROOM) kids.push(ownerRequests(ctx, intake && intake.owner, {confirm: st.labConfirm,
      onDecided: (id, d) => { if (d) load(); else render(); }}));
    kids.push(usageBlock(st.usage));
    body.replaceChildren(...kids.filter(Boolean));
  }

  async function load() {
    const id = st.id;
    if (!id) return;
    const req = ++st.req;
    const strat = id.startsWith("strat:") ? id.slice(6) : "";
    const tq = id === LAB_ROOM ? `limit=30&room_id=${encodeURIComponent(id)}` : `limit=6${strat ? "&strategy=" + encodeURIComponent(strat) : ""}`;
    // the lab room's shared test queue (/api/lab/intake, agents/labintake.py): an older server without the route (a
    // 404) or a failed read shows 수집 전 (disputes-kit.js labIntake)
    const intakeOf = async () => { try { return await ctx.api("/api/lab/intake"); } catch (e) { return null; } };
    const [notes, trials, props, more] = await Promise.all([
      ctx.api(`/api/rooms/${encodeURIComponent(id)}/notes?limit=20`).catch(() => []),
      ctx.api(`/api/trials?${tq}`).catch(() => null),
      ctx.api(`/api/proposals?room_id=${encodeURIComponent(id)}&limit=20`).catch(() => []),
      id === LAB_ROOM ? intakeOf()
        : strat ? ctx.api(`/api/disputes?room=${encodeURIComponent(id)}&limit=20`).catch(() => null) : null]);
    if (req !== st.req || id !== st.id || !ctx.alive()) return;
    st.side = {notes: notes || [], trials, props: props || [], intake: id === LAB_ROOM ? more : null,
      disputes: strat ? more : null};
    render();
  }

  return {el, load, render,
    open(id, room) { if (id !== st.id) { st.id = id; st.side = null; st.confirm = null; } st.room = room || st.room; render(); load(); },
    setRoom(room) { st.room = room; render(); },
    setUsage(u) { st.usage = u; if (st.side) render(); },
    scrollToProps() { const p = el.querySelector("#rm-props"); if (p) { p.scrollIntoView({block: "start", behavior: motion.reduced() ? "auto" : "smooth"}); motion.play(p, "enter"); } }};
}

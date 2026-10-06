// 🧪 이 매매법 시험해줘 (owners' idea inbox #103, paperbot/agents/labintake.py): the lab room's guided form and the
// '두 분 시험 요청' cards of the room's info pane.
//   labRequestForm(ctx, {owner, onSent})  the form: 언제 들어가나 / 언제 나오나 / 시간봉 / 코인 / 롱·숏 + an optional link
//                                         (agents cannot open links). It posts through the owners' usual
//                                         POST /api/rooms/team:lab/say with {lab_request: true, fields}; the server
//                                         writes the text (fixed first line '🧪 시험 요청') and refuses while the
//                                         owners' test budget is 0 (off) or the day's requests are used up.
//   ownerRequests(ctx, owner, {onDecided}) the cards: 접수 → 옮김 → 확인 → 시험 → 결과 (only the steps that really
//                                         happened are lit), how it was translated (정확 / 근사 / 불가), what was kept and
//                                         lost (the translator's words, as a quote), the code's reasons, the house exits
//                                         note, the code's result line, and for an approximate one [시험하기] / [그만두기]
//                                         with a confirm step (POST /api/lab/intake/<id>/decide; the next agents pass
//                                         applies it).
// HONESTY: every status, reason and result is the server's code text; nothing here says a test passed before the
// server's result line does; a click is shown as '반영 대기' until the agents apply it.
import {h, ui, fmt} from "../core/pb.js";

const LAB = "team:lab";
const FIDELITY_CLS = {exact: "good", approx: "warn", none: "thin"};
const MAX = {entry: 350, exit: 200, coins: 60, link: 150, note: 120};
// the statuses whose code line says something (a result, or why nothing ran); a waiting row's line is only its status
const RESULT = new Set(["tested", "reused", "duplicate", "not_counted", "error", "expired", "declined", "refused", "bad_spec"]);

function field(label, input, hint) {
  return h("label", {class: "lq-f"}, h("span", {class: "lq-l"}, label), input, hint ? h("small", {class: "lq-h"}, hint) : null);
}

/** The guided form. ``owner``: /api/lab/intake's owner block (or null before it loaded / an older server). */
export function labRequestForm(ctx, o = {}) {
  const st = {owner: o.owner || null, busy: false};
  const ta = (name, rows, ph) => h("textarea", {class: "lq-in", name, rows, maxlength: MAX[name], placeholder: ph, "aria-label": ph});
  const entry = ta("entry", 2, "예: 1시간봉에서 RSI(14)가 30 아래로 갔다가 다시 위로 올라올 때 롱");
  const exit = ta("exit", 1, "예: 3% 익절, 1% 손절 (시험에는 쓰이지 않음)");
  const tf = h("select", {class: "lq-sel", name: "timeframe", "aria-label": "시간봉"},
    h("option", {value: ""}, "고르기 (선택)"), ...["15m", "30m", "1h", "4h", "모름"].map((v) => h("option", {value: v}, v === "모름" ? "모름" : fmt.tfKo ? fmt.tfKo(v) : v)));
  const coins = h("input", {class: "lq-in", name: "coins", type: "text", maxlength: MAX.coins, placeholder: "예: BTC (시험은 늘 6개 코인)", "aria-label": "코인"});
  let side = "";
  const sideSeg = ui.seg([{id: "롱만", label: "롱만"}, {id: "숏만", label: "숏만"}, {id: "둘 다", label: "둘 다"}, {id: "모름", label: "모름"}],
    null, (id) => { side = id; }, {label: "롱·숏"});
  const first = sideSeg.querySelector("button");
  if (first) first.tabIndex = 0;                  // nothing picked yet: the group still takes the keyboard
  const link = h("input", {class: "lq-in", name: "link", type: "url", maxlength: MAX.link, placeholder: "https:// (선택)", "aria-label": "참고 링크"});
  const note = ta("note", 1, "더 적을 것 (선택)");
  const err = h("p", {class: "rm-err", role: "alert", hidden: true});
  const send = h("button", {class: "btn-y", type: "submit"}, "시험 요청 보내기");
  const offNote = h("p", {class: "lq-off", hidden: true});
  const quota = h("p", {class: "lq-quota muted"});
  const form = h("form", {class: "lq-form"},
    h("p", {class: "lq-lead"}, "매매법을 글로 적어 주시면 연구원이 문법으로 옮기고, 코드가 5년 자료로 시험합니다. 무엇이 그대로이고 무엇이 빠졌는지 먼저 알려 드립니다."),
    field("언제 들어가나 (꼭)", entry, "들어가는 조건을 숫자와 함께 적어 주세요"),
    field("언제 나오나", exit, "청산은 시험되지 않습니다: 늘 2 ATR 손절·계단식 익절·20~50배 (지금 규칙)"),
    h("div", {class: "lq-row"}, field("시간봉", tf), field("코인", coins)),
    h("div", {class: "lq-f"}, h("span", {class: "lq-l"}, "롱·숏"), sideSeg),
    field("참고 링크 (선택)", link, "링크는 열 수 없어요(에이전트는 인터넷 없음), 규칙을 글로 적어 주세요"),
    field("더 적을 것 (선택)", note),
    quota, offNote, err,
    h("div", {class: "row wrap"}, send, h("button", {class: "btn-line", type: "button", onclick: () => close()}, "닫기")));
  const toggle = h("button", {class: "btn-line lq-toggle", type: "button", "aria-expanded": "false"}, "🧪 이 매매법 시험해줘");
  const panel = h("div", {class: "lq-panel", hidden: true}, form);
  const el = h("div", {class: "lq"}, toggle, panel);

  function close() { panel.hidden = true; toggle.setAttribute("aria-expanded", "false"); }
  toggle.addEventListener("click", () => {
    const open = panel.hidden;
    panel.hidden = !open; toggle.setAttribute("aria-expanded", String(open));
    if (open) entry.focus();
  });
  function render() {
    const w = st.owner;
    const on = !!(w && w.enabled);
    offNote.hidden = on;
    offNote.textContent = w ? (w.off_ko || "시험 요청은 아직 꺼져 있습니다") : "시험 요청 상태를 아직 읽지 못했습니다 (서버가 이 기능 전이면 보낼 수 없습니다)";
    send.disabled = !on || st.busy;
    quota.hidden = !on;
    if (on) quota.textContent = `오늘 요청 ${fmt.int(w.requests_today || 0)}/${fmt.int(w.requests_max || 0)}번 · 오늘 두 분 몫 5년 시험 ${fmt.int(w.tests_today || 0)}/${fmt.int(w.limit || 0)}개 (요청마다 AI 회의가 한 번 열립니다)`;
  }
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    err.hidden = true;
    if (!entry.value.trim()) { err.hidden = false; err.textContent = "'언제 들어가나'를 적어 주세요"; entry.focus(); return; }
    st.busy = true; render();
    const fields = {entry: entry.value, exit: exit.value, timeframe: tf.value, coins: coins.value, side, link: link.value, note: note.value};
    try {
      const d = await ctx.post(`/api/rooms/${encodeURIComponent(LAB)}/say`, {lab_request: true, fields});
      for (const x of [entry, exit, coins, link, note]) x.value = "";
      tf.value = "";                              // the 롱·숏 choice stays as picked (shown and sent the same)
      close();
      ctx.toast("시험 요청을 보냈습니다. 다음 차례에 연구원이 옮기고, 결과는 이 방과 방 정보의 '두 분 시험 요청'에 나옵니다");
      if (o.onSent) o.onSent(d);
    } catch (ex) {
      err.hidden = false; err.textContent = (ex && ex.detail) || "보내지 못했습니다. 잠시 뒤 다시 시도해 주세요";
    } finally { st.busy = false; render(); }
  });
  render();
  el.setOwner = (w) => { st.owner = w || null; render(); };
  return el;
}

function quoteList(label, xs) {
  return xs && xs.length ? h("p", {class: "lq-q"}, h("span", {class: "muted"}, `${label} `), xs.join(" / ")) : null;
}

/** One request card. */
function card(ctx, c, onDecided, confirm) {
  const steps = ui.stepStrip(c.steps || [], {done: (c.stage || {}).done || [], now: (c.stage || {}).now, label: "요청 단계"});
  const fid = c.fidelity ? ui.pill(c.fidelity_ko || c.fidelity, FIDELITY_CLS[c.fidelity] || "thin") : null;
  const chip = ui.pill(c.status_ko || c.status, c.status === "needs_owner_ok" ? "warn" : "thin");
  let acts = null;
  if (c.status === "needs_owner_ok") {
    if (c.decision) {
      acts = h("p", {class: "rm-done"}, "두 분 결정: ", h("b", null, c.decision.decision_ko), " · 다음 차례(15분 안)에 코드가 반영합니다");
    } else if (confirm.id === c.id) {
      const run = confirm.dec === "run";
      const err = h("p", {class: "rm-err", hidden: true, role: "alert"});
      const go = h("button", {class: ["btn-line", run ? "ok" : "bad"], type: "button"}, `${run ? "시험하기" : "그만두기"} 확인`);
      go.addEventListener("click", async () => {
        go.disabled = true;
        try {
          const d = await ctx.post(`/api/lab/intake/${encodeURIComponent(c.id)}/decide`, {decision: confirm.dec});
          ctx.toast((d && d.message) || "전달했습니다");
          confirm.id = null;
          onDecided(c.id, d);
        } catch (e) {
          go.disabled = false; err.hidden = false; err.textContent = (e && e.detail) || "보내지 못했습니다. 잠시 뒤 다시 시도해 주세요";
        }
      });
      acts = h("div", {class: "rm-confirm"},
        h("p", null, run ? "근사로 옮긴 그대로 5년 시험을 할까요? 시험하면 새 매매법 시험 수에 들어가 모든 시험의 통과 기준이 조금 엄격해집니다."
          : "이 요청을 그만둘까요? 시험하지 않고 시험 수에도 넣지 않습니다."),
        h("div", {class: "row wrap"}, go, h("button", {class: "btn-line", type: "button", onclick: () => { confirm.id = null; onDecided(null); }}, "취소")), err);
    } else {
      const ask = (dec) => { confirm.id = c.id; confirm.dec = dec; onDecided(null); };
      acts = h("div", {class: "row wrap"}, h("button", {class: "btn-line ok", type: "button", onclick: () => ask("run")}, "시험하기"),
        h("button", {class: "btn-line bad", type: "button", onclick: () => ask("decline")}, "그만두기"));
    }
  }
  // not tested at all (outside the grammar, refused): the code's reason once, never the same words three times
  const untested = ["refused", "bad_spec"].includes(c.status);
  const reasons = c.reasons_ko || [];
  const result = RESULT.has(c.status) && !(untested && reasons.length) ? c.result_ko : "";
  return h("div", {class: "lq-card", role: "listitem"},
    h("div", {class: "lq-ch"}, h("b", null, c.label_ko || `#${c.id}`), fid, chip, h("time", {class: "muted"}, fmt.kst(c.ts))),
    steps,
    c.description_ko && !untested ? h("p", {class: "lq-desc"}, c.description_ko) : null,
    c.idea_ko ? h("p", {class: "lq-q"}, h("span", {class: "muted"}, "요청 한 줄 "), `“${c.idea_ko}”`) : null,
    quoteList("번역가: 그대로", c.kept), quoteList("번역가: 빠짐·바뀜", c.lost),
    reasons.length ? h("ul", {class: "lq-why"}, reasons.map((x) => h("li", null, x))) : null,
    result ? h("p", {class: "lq-res"}, h("span", {class: "muted"}, "코드 결과 "), result) : null,
    untested ? h("p", {class: "lq-res"}, "시험하지 않았고 시험 수에도 넣지 않았습니다") : null,
    h("p", {class: "rk-note"}, c.exits_ko || ""),
    acts);
}

/** The info pane's '두 분 시험 요청' section; null before the server has the block (an older server). */
export function ownerRequests(ctx, owner, o = {}) {
  if (!owner) return null;
  const confirm = o.confirm || {id: null, dec: null};
  const cards = owner.cards || [];
  const redraw = (id, d) => { if (o.onDecided) o.onDecided(id, d); };
  const waiting = cards.filter((c) => c.status === "needs_owner_ok" && !c.decision).length;
  return h("section", {class: ["rm-sec", waiting ? "hl" : ""], id: "rm-labreq"},
    h("h3", null, "두 분 시험 요청 ", waiting ? ui.pill(`확인 ${fmt.int(waiting)}`, "accent") : null),
    owner.enabled ? h("p", {class: "muted"}, `오늘 요청 ${fmt.int(owner.requests_today || 0)}/${fmt.int(owner.requests_max || 0)}번 · 두 분 몫 5년 시험 ${fmt.int(owner.tests_today || 0)}/${fmt.int(owner.limit || 0)}개`)
      : h("p", {class: "muted"}, owner.off_ko || "시험 요청은 아직 꺼져 있습니다"),
    cards.length ? h("div", {class: "lq-list", role: "list"}, cards.slice(0, 5).map((c) => card(ctx, c, redraw, confirm)))
      : owner.enabled ? h("p", {class: "muted"}, "아직 보낸 시험 요청이 없습니다. 대화 아래 '🧪 이 매매법 시험해줘'로 보낼 수 있습니다.") : null,
    cards.length > 5 ? ui.disclosure(`나머지 ${fmt.int(cards.length - 5)}개`, h("div", {class: "lq-list", role: "list"}, cards.slice(5, 20).map((c) => card(ctx, c, redraw, confirm)))) : null,
    h("p", {class: "rk-note"}, "정확히 옮긴 요청은 코드가 하루 몫 안에서 바로 시험합니다. 근사로 옮긴 요청은 두 분이 [시험하기]를 눌러야 시험합니다. 옮길 수 없는 요청은 시험하지 않고 시험 수에도 넣지 않습니다. 통과해도 관찰 기간이 끝난 뒤 그때의 시험 수로 다시 판정해 제안하고, 두 분 확인이 필요합니다."));
}

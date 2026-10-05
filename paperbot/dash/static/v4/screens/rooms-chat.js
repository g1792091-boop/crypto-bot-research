// 에이전트 방 · the chat pane (builder D): one room's stored conversation as a messenger inside the console frame
// (mockup section 06). Staff messages: avatar, "> 이름 · 분석 14:31", a 2-line text with 더 보기, rule JSON as readable
// lines with the raw text folded, 동의 / 반대 / 보완 pills from the answer's responds_to, evidence folded. Code results
// as cards with the gate's result; decisions as cards; owner posts on the right (전달 대기 until the staff read them).
// Tap a [회의 시작] line: only that meeting. Composer: optional owner post with @mention (POST /api/rooms/<id>/say).
// HONESTY: no typing effect; "회의 중" only from /api/rooms `running` (a still line, no animated dots); new messages
// slide in only when they really arrived after the first paint. Every text is a text node.
import {h, ui, fmt, motion, clear} from "../core/pb.js";
import {KIND_KO, SPEAKING, VERDICT_KO, stanceOf, answerOf, dataOf, bodyLines, messageBody, avatarFor, roleName, hueFor,
  stripLead, roomAvatar, pendingHint, agentsState, keptHoursKo, scheduleOf} from "./rooms-kit.js";
import {recordBox, stratOf} from "./rooms-record.js";

const PAGE = 60;
const MAX_CHARS = 1000;

export function makeChat(ctx, hooks) {
  const st = {id: null, room: null, msgs: [], pending: [], lastId: 0, hasMore: false, filter: "all", meeting: null, req: 0, busy: false, again: false, ov: null, firstPaint: true};

  // ---------------------------------------------------------------- frame
  const back = h("button", {class: "btn-line rm-back", type: "button", onclick: () => hooks.pane("list")}, "← 방 목록");
  const infoBtn = h("button", {class: "btn-line rm-infobtn", type: "button", onclick: () => hooks.pane("info")}, "방 정보");
  const av = h("span", {class: "rm-hav"});
  const title = h("b"), sub = h("small");
  const state = h("span", {class: "rm-state"});
  const avs = h("span", {class: "rm-avs"});
  const head = h("div", {class: "rm-head"}, back, av, h("div", {class: "rm-ht"}, title, sub), state, avs, infoBtn);
  const waitBtn = h("button", {class: "rm-wait", type: "button", hidden: true, onclick: () => hooks.pane("info", true)});
  const seg = ui.seg([{id: "all", label: "전체"}, {id: "staff", label: "직원 발언"}, {id: "result", label: "결론·코드"}], "all",
    (id) => { st.filter = id; apply(true); }, {label: "대화 보기"});
  seg.classList.add("rm-seg");
  const fText = h("span");
  const fBar = h("div", {class: "con-filter", hidden: true}, fText, h("button", {type: "button", onclick: () => { st.meeting = null; apply(true); }}, "전체 보기"));
  const olderBtn = h("button", {class: "btn-line rm-older", type: "button", hidden: true, onclick: () => loadOlder()}, "이전 대화 더 보기");
  const list = h("div", {class: "rm-list", role: "log", "aria-live": "polite", "aria-label": "방 대화"});
  const runLine = h("p", {class: "rm-run", hidden: true});
  const scroller = h("div", {class: "rm-scroll"}, olderBtn, list, runLine);
  const newBtn = h("button", {class: "btn-y rm-new", type: "button", hidden: true, onclick: () => { toBottom(); newBtn.hidden = true; }}, "새 메시지 ↓");
  // composer (optional owner post)
  const input = h("textarea", {class: "rm-in", rows: 1, maxlength: MAX_CHARS, placeholder: "끼어들기 (선택) · @로 직원 지목", "aria-label": "방에 글 남기기"});
  const count = h("span", {class: "rm-count"}, `0/${fmt.int(MAX_CHARS)}`);
  const mention = h("div", {class: "rm-mention", role: "listbox", hidden: true});
  const send = h("button", {class: "btn-y rm-send", type: "submit"}, "보내기");
  const form = h("form", {class: "rm-compose"}, mention, input, h("div", {class: "rm-cfoot"}, count, h("span", {class: "grow"}), send));
  const foot = h("p", {class: "rm-foot"});
  const empty = h("div", {class: "rm-empty"}, ui.empty("왼쪽에서 방을 고르세요"));
  const body = h("div", {class: "rm-chatin", hidden: true}, head, waitBtn, seg, fBar, h("div", {class: "rm-scrollwrap"}, scroller, newBtn), form, foot);
  const el = h("section", {class: "rm-chat", "aria-label": "방 대화"}, empty, body);

  scroller.addEventListener("scroll", () => { if (nearBottom()) newBtn.hidden = true; });
  const nearBottom = () => scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 90;
  const toBottom = () => { scroller.scrollTop = scroller.scrollHeight; };

  // ---------------------------------------------------------------- messages
  const roles = () => hooks.roles();
  function timeEl(ts) { return h("time", null, fmt.hm(ts)); }
  function stanceLine(m) {
    const s = stanceOf(m);
    if (!s) return null;
    return h("div", {class: "rk-stance"}, ui.pill(s.ko, s.cls), h("span", null, `${roleName(roles(), s.to)}에게`), s.point ? h("span", {class: "rm-point"}, s.point) : null);
  }
  function staffNode(m) {
    const who = m.speaker_name || roleName(roles(), m.role);
    const a = answerOf(m);
    const verdict = m.kind === "challenge" && a.verdict ? (a.verdict_coerced ? "unreadable" : a.verdict) : null;
    const ev = Array.isArray(m.evidence) ? m.evidence : m.evidence ? [m.evidence] : [];
    return h("div", {class: "rm-msg"}, avatarFor(roles(), m.role, who),
      h("div", {class: "rm-mbody"},
        h("div", {class: "rm-mh"}, `> ${who} · ${KIND_KO[m.kind] || m.kind} `, timeEl(m.ts)),
        stanceLine(m),
        h("div", {class: "rm-bub", style: {"--h": hueFor(roles(), m.role)}}, messageBody(bodyLines(m), {lines: 2}),
          verdict ? h("div", {class: "rk-stance"}, ui.pill(`판정: ${VERDICT_KO[verdict] || verdict}`, verdict === "agree" ? "good" : verdict === "disagree" ? "bad" : "warn")) : null,
          ev.length ? ui.disclosure(`근거 ${fmt.int(ev.length)}곳`, h("ul", {class: "rm-ev"}, ev.map((x) => h("li", null, typeof x === "string" ? x : JSON.stringify(x))))) : null)));
  }
  function codeNode(m) {
    const d = dataOf(m), g = d.gate && typeof d.gate === "object" ? d.gate : null;
    const pill = g && g.pass === true ? ui.pill("관문 통과", "good") : g && g.pass === false ? ui.pill("관문 불통과", "bad")
      : d.status ? ui.pill(String(d.status), "thin") : null;
    const reasons = g && Array.isArray(g.reasons) ? g.reasons : [];
    let raw = "";
    try { raw = JSON.stringify(d, null, 1); } catch { raw = ""; }
    return h("div", {class: "rk-code rm-code"}, h("div", {class: "rk-code-h"}, h("b", null, "코드 계산 결과"), timeEl(m.ts), pill),
      messageBody(String(m.text || "").split("\n"), {lines: 3}),
      reasons.length ? h("ul", null, reasons.map((x) => h("li", null, String(x)))) : null,
      raw && raw !== "{}" ? ui.disclosure("원문 보기", h("pre", {class: "rk-raw"}, raw)) : null);
  }
  function ownerNode(m, pending) {
    const who = pending ? (m.author ? `두 분 (${m.author})` : "두 분") : (m.speaker_name || "두 분");
    const ov = st.ov, r = curOv();
    return h("div", {class: ["rm-msg", "owner", pending ? "pending" : ""]}, avatarFor(roles(), "owner"),
      h("div", {class: "rm-mbody"}, h("div", {class: "rm-mh"}, `${who} · `, timeEl(m.ts), pending ? h("span", {class: "pp warn"}, "전달 대기") : null),
        h("div", {class: "rm-bub"}, messageBody(String(m.text || "").split("\n"), {lines: 4})),
        pending ? h("p", {class: "rm-hint"}, pendingHint(agentsState(ov).st, (r || {}).owner_wait, (ov || {}).rounds_per_room_day, keptHoursKo((ov || {}).hours))) : null));
  }
  function nodeOf(m) {
    let n;
    if (m.kind === "trigger") {
      const key = m.round_id;
      n = h("div", {class: "cl ev rm-trig"}, h("button", {class: "go", type: "button", title: "이 회의만 보기",
        onclick: () => { st.meeting = key; fText.textContent = `이 회의만 보는 중 · ${stripLead(m.text)}`; apply(true); }},
      h("span", {class: "bl"}, "▪ "), "> ", h("span", {class: "lk"}, "[회의 시작]"), ` ${stripLead(m.text)} `, h("time", null, `(${fmt.hm(m.ts)})`)));
    } else if (m.kind === "system") {
      n = h("p", {class: "rm-sys"}, String(m.text || ""), " ", timeEl(m.ts));
    } else if (m.kind === "action") {
      n = h("div", {class: "cl ev rm-act"}, h("span", {class: "bl"}, "▪ "), `> [실행] ${stripLead(m.text)} `, h("time", null, `(${fmt.hm(m.ts)})`));
    } else if (m.kind === "decision") {
      n = h("div", {class: "rm-dec"}, h("div", {class: "rk-code-h"}, h("b", null, "회의 결론"), h("span", {class: "muted"}, "숫자는 코드가 정리"), timeEl(m.ts)),
        messageBody(stripLead(m.text).split("\n"), {lines: 3}));
    } else if (m.kind === "code_result") {
      n = codeNode(m);
    } else if (m.kind === "owner") {
      n = ownerNode(m, false);
    } else {
      n = staffNode(m);
    }
    n.dataset.id = String(m.id);
    n._m = m;
    return n;
  }
  const isStaff = (m) => SPEAKING.has(m.kind) || m.kind === "owner";
  const isResult = (m) => ["decision", "code_result", "action", "summary", "verdict"].includes(m.kind);
  function visible(m) {
    if (!m) return true;
    if (st.meeting != null && m.round_id !== st.meeting) return false;
    if (st.filter === "staff" && !isStaff(m)) return false;
    if (st.filter === "result" && !isResult(m)) return false;
    return true;
  }
  function apply(animate) {
    let lastDay = null;
    for (const n of list.children) {
      if (n.classList.contains("rm-day")) { n.hidden = false; lastDay = n; lastDay._any = false; continue; }
      const v = n._pending ? st.meeting == null && st.filter !== "result" : visible(n._m);
      n.hidden = !v;
      if (v && lastDay) lastDay._any = true;
    }
    for (const n of list.querySelectorAll(".rm-day")) n.hidden = !n._any;
    fBar.hidden = st.meeting == null;
    if (animate) motion.swap(list);
  }
  const dayNode = (ts) => { const n = h("div", {class: "rm-day"}, h("span", null, fmt.date(ts))); n._day = fmt.dayKey(ts); return n; };

  /** Draw every message (room change, older page). */
  function renderAll(stick) {
    clear(list);
    let day = null;
    for (const m of st.msgs) {
      const dk = fmt.dayKey(m.ts);
      if (dk !== day) { list.append(dayNode(m.ts)); day = dk; }
      list.append(nodeOf(m));
    }
    renderPending();
    if (!st.msgs.length && !st.pending.length) list.append(emptyRoom());
    olderBtn.hidden = !st.hasMore;
    apply(false);
    if (stick) requestAnimationFrame(toBottom);
  }
  function renderPending() {
    for (const n of [...list.querySelectorAll(".rm-pend")]) n.remove();
    for (const p of st.pending) {
      const n = ownerNode(p, true);
      n.classList.add("rm-pend"); n._pending = true;
      list.append(n);
    }
  }
  function emptyRoom() {
    const s = scheduleOf(st.id, st.room, curOv());
    return h("div", {class: "rm-emptyroom"}, h("b", null, "아직 이 방에서 열린 회의가 없습니다"), s ? h("p", null, s) : null,
      h("p", {class: "muted"}, "회의가 열리면 직원들의 대화가 여기에 올라옵니다. 궁금한 점을 아래에 남겨 두셔도 됩니다 (선택)."),
      // fill-people: a strategy room shows its strategy's own code record until the first meeting
      stratOf(st.id, st.room) ? recordBox(ctx, stratOf(st.id, st.room)) : null);
  }
  /** Append really new messages (after the first paint): they slide in. */
  function appendNew(add) {
    const stick = nearBottom();
    const ph = list.querySelector(".rm-emptyroom");
    if (ph) ph.remove();
    let lastDay = [...list.querySelectorAll(".rm-day")].pop();
    const firstPend = list.querySelector(".rm-pend");
    for (const m of add) {
      const dk = fmt.dayKey(m.ts);
      if (!lastDay || lastDay._day !== dk) { lastDay = dayNode(m.ts); list.insertBefore(lastDay, firstPend); }
      const n = nodeOf(m);
      list.insertBefore(n, firstPend);
      if (m.kind === "owner" || SPEAKING.has(m.kind)) motion.popBubble(n); else motion.slideIn(n);
    }
    renderPending();
    apply(false);
    if (stick) requestAnimationFrame(toBottom); else newBtn.hidden = false;
  }

  // ---------------------------------------------------------------- data
  const curOv = () => st.ov && (st.ov.rooms || []).find((r) => r.room_id === st.id);
  async function open(id) {
    const req = ++st.req;
    if (id !== st.id) {
      Object.assign(st, {id, room: null, msgs: [], pending: [], lastId: 0, hasMore: false, meeting: null});
      empty.hidden = true; body.hidden = false;
      clear(list); list.append(motion.shimmer(4));
      fBar.hidden = true; newBtn.hidden = true;
      input.value = ""; grow();
    }
    renderHead();
    let d;
    try { d = await ctx.api(`/api/rooms/${encodeURIComponent(id)}/messages?limit=${PAGE}`); } catch (e) {
      if (req === st.req && ctx.alive() && !(e && e.name === "AbortError")) { clear(list); list.append(ui.errorBox(e, () => open(id))); }
      return;
    }
    if (req !== st.req || !ctx.alive()) return;
    st.room = d.room || null; st.msgs = d.messages || []; st.pending = d.pending_owner || []; st.hasMore = !!d.has_more;
    if (hooks.roomInfo) hooks.roomInfo(st.room);
    st.lastId = st.msgs.length ? st.msgs[st.msgs.length - 1].id : 0;
    renderHead(); renderAll(true);
    hooks.seen(id, Math.max(st.lastId, (curOv() || {}).last_id || 0));
  }
  async function fetchNew() {
    if (!st.id || !st.room) return;
    if (st.busy) { st.again = true; return; }
    st.busy = true;
    const id = st.id;
    try {
      const d = await ctx.api(`/api/rooms/${encodeURIComponent(id)}/messages?after_id=${st.lastId}&limit=200`);
      if (id !== st.id || !ctx.alive()) return;
      const add = (d.messages || []).filter((m) => m.id > st.lastId);
      st.msgs = st.msgs.concat(add);
      if (add.length) st.lastId = add[add.length - 1].id;
      const pendChanged = JSON.stringify((d.pending_owner || []).map((p) => p.id)) !== JSON.stringify(st.pending.map((p) => p.id));
      st.pending = d.pending_owner || [];
      if (add.length) appendNew(add); else if (pendChanged) { renderPending(); apply(false); }
      hooks.seen(id, st.lastId);
      if (add.some((m) => ["decision", "action", "code_result", "verdict", "owner", "system"].includes(m.kind))) hooks.sideChanged();
    } catch { /* the next change retries */ } finally {
      st.busy = false;
      if (st.again && ctx.alive()) { st.again = false; fetchNew(); }
    }
  }
  async function loadOlder() {
    const first = st.msgs[0];
    if (!first || !st.id) return;
    const id = st.id;
    olderBtn.disabled = true;
    try {
      const d = await ctx.api(`/api/rooms/${encodeURIComponent(id)}/messages?before_id=${first.id}&limit=${PAGE}`);
      if (id !== st.id || !ctx.alive()) return;
      const h0 = scroller.scrollHeight, t0 = scroller.scrollTop;
      st.msgs = (d.messages || []).concat(st.msgs); st.hasMore = !!d.has_more;
      renderAll(false);
      scroller.scrollTop = scroller.scrollHeight - h0 + t0;
    } catch { ctx.toast("이전 대화를 불러오지 못했습니다"); } finally { olderBtn.disabled = false; }
  }

  function renderHead() {
    const r = curOv(), info = st.room;
    const base = r || info || {room_id: st.id, title: st.id, kind: String(st.id).startsWith("team:") ? "team" : "strategy"};
    av.replaceChildren(roomAvatar(base));
    title.textContent = base.title || st.id;
    const members = (info && info.members_info) || [];
    sub.textContent = `${base.kind === "team" ? "팀 방" : "매매법 전담 방"} · 멤버 ${fmt.int(members.length || ((r && r.members) || []).length)}명${r ? ` · 오늘 회의 ${fmt.int(r.rounds_today)}번` : ""}`;
    const a = agentsState(st.ov);
    state.replaceChildren(r && r.running ? ui.livePill("회의 중") : ["ok", "new"].includes(a.st)
      ? ui.pill("다음 회의 대기", "thin", "조건이 되면 직원들이 스스로 회의를 엽니다") : ui.pill("에이전트 멈춤", "bad"));
    avs.replaceChildren(...members.slice(0, 5).map((m) => ui.avatar(String(m.name || m.id).slice(0, 1), hueFor(roles(), m.id))));
    avs.title = members.map((m) => m.name).join(", ");
    const n = r ? r.open_proposals || 0 : 0;
    waitBtn.hidden = !n;
    waitBtn.replaceChildren("두 분 확인을 기다리는 제안 ", h("b", null, `${fmt.int(n)}건`), h("span", null, "승인·거절 →"));
    runLine.hidden = !(r && r.running);
    runLine.textContent = "직원들이 지금 이 방에서 회의 중입니다. 다음 발언이 기록되면 여기에 나옵니다.";
    foot.textContent = scheduleOf(st.id, info, r);
  }

  // ---------------------------------------------------------------- composer
  function grow() {
    input.style.height = "";
    if (input.value) input.style.height = Math.min(Math.max(input.scrollHeight + 2, input.offsetHeight), 150) + "px";
    count.textContent = `${fmt.int(input.value.length)}/${fmt.int(MAX_CHARS)}`;
  }
  function mentionList() {
    const m = /@([^\s@]*)$/.exec(input.value.slice(0, input.selectionStart || input.value.length));
    const people = ((st.room && st.room.members_info) || []).filter((x) => x.id !== "team_lead");
    const q = m ? m[1].replace(/[·\s]/g, "") : null;
    const hits = q == null ? [] : people.filter((x) => String(x.name || "").replace(/[·\s]/g, "").includes(q)).slice(0, 8);
    mention.hidden = !hits.length;
    mention.replaceChildren(...hits.map((x) => h("button", {type: "button", role: "option", onmousedown: (e) => {
      e.preventDefault();
      const pos = input.selectionStart || input.value.length, before = input.value.slice(0, pos).replace(/@[^\s@]*$/, "");
      input.value = `${before}@${x.name} ${input.value.slice(pos)}`;
      const at = before.length + String(x.name).length + 2;
      input.setSelectionRange(at, at); mention.hidden = true; grow(); input.focus();
    }}, `@${x.name}`, x.duty ? h("small", null, x.duty) : null)));
  }
  input.addEventListener("input", () => { grow(); mentionList(); });
  input.addEventListener("blur", () => setTimeout(() => { mention.hidden = true; }, 150));
  input.addEventListener("keydown", (e) => {        // Enter sends on a PC keyboard; never while Hangul is being composed
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing && e.keyCode !== 229 && !hooks.narrow()) { e.preventDefault(); form.requestSubmit(); }
  });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text || !st.id) return;
    const id = st.id;
    send.disabled = true;
    try {
      const d = await ctx.post(`/api/rooms/${encodeURIComponent(id)}/say`, {text});
      input.value = ""; grow();
      const a = agentsState(st.ov), hint = pendingHint(a.st, (curOv() || {}).owner_wait, (st.ov || {}).rounds_per_room_day, keptHoursKo((st.ov || {}).hours));
      ctx.toast(a.st === "ok" ? `전달했습니다. ${hint}` : `저장했습니다. ${hint}`);
      if (id === st.id && d) {
        st.pending.push(d);
        const ph = list.querySelector(".rm-emptyroom");
        if (ph) ph.remove();
        renderPending(); apply(false);
        const last = list.lastElementChild;
        if (last) motion.popBubble(last);
        requestAnimationFrame(toBottom);
      }
    } catch (err) { ctx.toast((err && err.detail) || "보내지 못했습니다. 잠시 뒤 다시 시도해 주세요"); } finally { send.disabled = false; }
  });

  return {el, open, fetchNew, renderHead, current: () => st.id,
    setOv(ov) { const was = !!(curOv() || {}).running; st.ov = ov; if (st.id) { renderHead(); if (was !== !!(curOv() || {}).running) renderPending(); } },
    clearRoom() { st.id = null; empty.hidden = false; body.hidden = true; }};
}

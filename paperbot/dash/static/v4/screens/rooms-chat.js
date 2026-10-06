// 에이전트 방 · the chat pane (builder D; agents-ui: messenger look): one room's stored conversation as a messenger
// inside the console frame. Staff messages: the office's pixel person in the role's colour, the name in that colour,
// type badges (결론 / 제안 / 가설 / 질문 / 데이터, agents-ui.js msgTypes: only what the stored message holds), the
// text with 더 보기, rule JSON as readable lines with the raw text folded, 동의 / 반대 / 보완 pills from the answer's
// responds_to, evidence folded, and small link cards for the strategies / accounts the message names. A speaker's
// next message within a few minutes of the same meeting is grouped under the first (no repeated avatar). Code results
// and decisions as cards; owner posts on the right (전달 대기 until the staff read them).
// Top of the room: the latest conclusion pinned (tap: jump to it). Filters 전체 / 결론만 / 두 분 메모 and a search box
// over the loaded messages. Days are separated ("오늘 · 10월 6일 (화)"). Tap a [회의 시작] line: only that meeting.
// HONESTY: no typing effect; "회의 중" only from /api/rooms `running` (a still line, no animated dots) and the progress
// line only from /api/office `running` (turns stored so far, the next speaker only when the meeting's order names it);
// new messages slide in and the list scrolls (smoothly) only when they really arrived after the first paint and the
// reader was already at the bottom. Every text is a text node.
import {h, ui, fmt, motion, clear, store} from "../core/pb.js";
import {KIND_KO, SPEAKING, VERDICT_KO, stanceOf, answerOf, dataOf, bodyLines, messageBody, roleName, hueFor,
  stripLead, roomAvatar, pendingHint, agentsState, keptHoursKo, scheduleOf} from "./rooms-kit.js";
import {recordBox, stratOf} from "./rooms-record.js";
import {typeBadges, msgTypes, forOwners, pixAvatar, refsOf, miniCards, dayLabel} from "./agents-ui.js";

const PAGE = 60;
const MAX_CHARS = 1000;
const GROUP_MS = 10 * 60000;          // a speaker's next message within this, same meeting: grouped under the first
const FILTERS = [{id: "all", label: "전체"}, {id: "result", label: "결론만"}, {id: "owner", label: "두 분 메모"}];

export function makeChat(ctx, hooks) {
  const st = {id: null, room: null, msgs: [], pending: [], lastId: 0, hasMore: false, filter: "all", q: "", meeting: null, req: 0,
    busy: false, again: false, ov: null};

  // ---------------------------------------------------------------- frame
  const back = h("button", {class: "btn-line rm-back", type: "button", onclick: () => hooks.pane("list")}, "← 방 목록");
  const infoBtn = h("button", {class: "btn-line rm-infobtn", type: "button", onclick: () => hooks.pane("info")}, "방 정보");
  const av = h("span", {class: "rm-hav"});
  const title = h("b"), sub = h("small");
  const state = h("span", {class: "rm-state"});
  const avs = h("span", {class: "rm-avs"});
  const head = h("div", {class: "rm-head"}, back, av, h("div", {class: "rm-ht"}, title, sub), state, avs, infoBtn);
  const waitBtn = h("button", {class: "rm-wait", type: "button", hidden: true, onclick: () => hooks.pane("info", true)});
  // the latest conclusion, pinned (a stored decision / lead summary of this room; tap jumps to it)
  const pinText = h("span", {class: "rm-pin-t"}), pinWhen = h("time"), pinSub = h("span", {class: "rm-pin-s"});
  const pin = h("button", {class: "rm-pin", type: "button", hidden: true, title: "이 결론으로 이동"},
    h("span", {class: "rm-pin-k"}, "최근 결론"), h("span", {class: "rm-pin-b"}, pinText, pinSub), pinWhen);
  // the meeting running now: its stored progress (from /api/office), never an animation
  const runLine = h("div", {class: "rm-run", hidden: true, role: "status"});
  const seg = ui.seg(FILTERS, "all", (id) => { st.filter = id; apply(true); }, {label: "대화 보기"});
  seg.classList.add("rm-seg");
  const search = h("input", {class: "search rm-q", type: "search", placeholder: "이 방 대화 찾기", "aria-label": "이 방 대화 찾기", autocomplete: "off"});
  const found = h("span", {class: "rm-found", "aria-live": "polite"});
  search.addEventListener("input", () => { st.q = search.value.trim().toLowerCase(); apply(false); });
  const tools = h("div", {class: "rm-tools"}, seg, h("div", {class: "rm-qbox"}, search, found));
  const fText = h("span");
  const fBar = h("div", {class: "con-filter", hidden: true}, fText, h("button", {type: "button", onclick: () => { st.meeting = null; apply(true); }}, "전체 보기"));
  const olderBtn = h("button", {class: "btn-line rm-older", type: "button", hidden: true, onclick: () => loadOlder()}, "이전 대화 더 보기");
  const list = h("div", {class: "rm-list", role: "log", "aria-live": "polite", "aria-label": "방 대화"});
  const none = h("p", {class: "rm-none", hidden: true});
  const scroller = h("div", {class: "rm-scroll"}, olderBtn, list, none);
  const newBtn = h("button", {class: "btn-y rm-new", type: "button", hidden: true, onclick: () => { toBottom(true); newBtn.hidden = true; }}, "새 메시지 ↓");
  // composer (optional owner post)
  const input = h("textarea", {class: "rm-in", rows: 1, maxlength: MAX_CHARS, placeholder: "끼어들기 (선택) · @로 직원 지목", "aria-label": "방에 글 남기기"});
  const count = h("span", {class: "rm-count"}, `0/${fmt.int(MAX_CHARS)}`);
  const mention = h("div", {class: "rm-mention", role: "listbox", hidden: true});
  const send = h("button", {class: "btn-y rm-send", type: "submit"}, "보내기");
  const form = h("form", {class: "rm-compose"}, mention, input, h("div", {class: "rm-cfoot"}, count, h("span", {class: "grow"}), send));
  const foot = h("p", {class: "rm-foot"});
  const empty = h("div", {class: "rm-empty"}, ui.empty("왼쪽에서 방을 고르세요"));
  const body = h("div", {class: "rm-chatin", hidden: true}, head, pin, waitBtn, runLine, tools, fBar,
    h("div", {class: "rm-scrollwrap"}, scroller, newBtn), form, foot);
  const el = h("section", {class: "rm-chat", "aria-label": "방 대화"}, empty, body);

  scroller.addEventListener("scroll", () => { if (nearBottom()) newBtn.hidden = true; });
  const nearBottom = () => scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 90;
  const toBottom = (smooth) => {
    if (smooth && !motion.reduced() && scroller.scrollTo) scroller.scrollTo({top: scroller.scrollHeight, behavior: "smooth"});
    else scroller.scrollTop = scroller.scrollHeight;
  };

  // ---------------------------------------------------------------- messages
  const roles = () => hooks.roles();
  const board = () => store.get("board");
  function timeEl(ts) { return h("time", {title: fmt.kst(ts)}, fmt.hm(ts)); }
  function stanceLine(m) {
    const s = stanceOf(m);
    if (!s) return null;
    return h("div", {class: "rk-stance"}, ui.pill(s.ko, s.cls), h("span", null, `${roleName(roles(), s.to)}에게`), s.point ? h("span", {class: "rm-point"}, s.point) : null);
  }
  const minis = (m) => miniCards(ctx, refsOf(m.text, board()), board());
  function staffNode(m, cont) {
    const who = m.speaker_name || roleName(roles(), m.role);
    const a = answerOf(m);
    const verdict = m.kind === "challenge" && a.verdict ? (a.verdict_coerced ? "unreadable" : a.verdict) : null;
    const ev = Array.isArray(m.evidence) ? m.evidence : m.evidence ? [m.evidence] : [];
    const hue = hueFor(roles(), m.role);
    const kindKo = KIND_KO[m.kind] || m.kind;
    return h("div", {class: ["rm-msg", cont ? "cont" : ""], style: {"--h": hue}},
      cont ? h("span", {class: "rm-avgap", "aria-hidden": "true"}) : pixAvatar(roles(), m.role),
      h("div", {class: "rm-mbody"},
        cont ? null : h("div", {class: "rm-mh"}, h("b", {class: "rm-who"}, who), h("span", {class: "rm-kind"}, kindKo), timeEl(m.ts), typeBadges(m)),
        h("div", {class: "rm-bub"},
          cont ? h("div", {class: "rm-bubh"}, typeBadges(m), h("span", {class: "rm-ctime"}, kindKo, " · ", timeEl(m.ts))) : null,
          stanceLine(m),
          messageBody(bodyLines(m), {lines: 3}),
          verdict ? h("div", {class: "rk-stance"}, ui.pill(`판정: ${VERDICT_KO[verdict] || verdict}`, verdict === "agree" ? "good" : verdict === "disagree" ? "bad" : "warn")) : null,
          minis(m),
          ev.length ? ui.disclosure(`근거 ${fmt.int(ev.length)}곳`, h("ul", {class: "rm-ev"}, ev.map((x) => h("li", null, typeof x === "string" ? x : JSON.stringify(x))))) : null)));
  }
  function codeNode(m) {
    const d = dataOf(m), g = d.gate && typeof d.gate === "object" ? d.gate : null;
    const pill = g && g.pass === true ? ui.pill("관문 통과", "good") : g && g.pass === false ? ui.pill("관문 불통과", "bad")
      : d.status ? ui.pill(String(d.status), "thin") : null;
    const reasons = g && Array.isArray(g.reasons) ? g.reasons : [];
    let raw = "";
    try { raw = JSON.stringify(d, null, 1); } catch { raw = ""; }
    return h("div", {class: "rk-code rm-code"}, h("div", {class: "rk-code-h"}, h("span", {class: "ag-av code sm", "aria-hidden": "true"}, h("b", null, "C")),
      h("b", null, "코드 계산 결과"), typeBadges(m), timeEl(m.ts), pill),
      messageBody(String(m.text || "").split("\n"), {lines: 3}),
      reasons.length ? h("ul", null, reasons.map((x) => h("li", null, String(x)))) : null,
      minis(m),
      raw && raw !== "{}" ? ui.disclosure("원문 보기", h("pre", {class: "rk-raw"}, raw)) : null);
  }
  function ownerNode(m, pending) {
    const who = pending ? (m.author ? `두 분 (${m.author})` : "두 분") : (m.speaker_name || "두 분");
    const ov = st.ov, r = curOv();
    return h("div", {class: ["rm-msg", "owner", pending ? "pending" : ""]}, pixAvatar(roles(), "owner"),
      h("div", {class: "rm-mbody"}, h("div", {class: "rm-mh"}, h("b", {class: "rm-who"}, who), timeEl(m.ts), typeBadges(m), pending ? h("span", {class: "pp warn"}, "전달 대기") : null),
        h("div", {class: "rm-bub"}, messageBody(String(m.text || "").split("\n"), {lines: 4}), minis(m)),
        pending ? h("p", {class: "rm-hint"}, pendingHint(agentsState(ov).st, (r || {}).owner_wait, (ov || {}).rounds_per_room_day, keptHoursKo((ov || {}).hours))) : null));
  }
  function nodeOf(m, prev) {
    let n;
    if (m.kind === "trigger") {
      const key = m.round_id;
      n = h("div", {class: "rm-trig"}, h("button", {class: "go", type: "button", title: "이 회의만 보기",
        onclick: () => { st.meeting = key; fText.textContent = `이 회의만 보는 중 · ${stripLead(m.text)}`; apply(true); }},
      h("span", {class: "rm-trig-k"}, "회의 시작"), h("span", {class: "rm-trig-t"}, stripLead(m.text)), timeEl(m.ts)));
    } else if (m.kind === "system") {
      n = h("p", {class: "rm-sys"}, String(m.text || ""), " ", timeEl(m.ts));
    } else if (m.kind === "action") {
      n = h("div", {class: "cl ev rm-act"}, h("span", {class: "bl"}, "▪ "), `> [실행] ${stripLead(m.text)} `, h("time", null, `(${fmt.hm(m.ts)})`));
    } else if (m.kind === "decision") {
      n = h("div", {class: "rm-dec"}, h("div", {class: "rk-code-h"}, h("b", null, "회의 결론"), typeBadges(m), h("span", {class: "muted"}, "숫자는 코드가 정리"), timeEl(m.ts)),
        messageBody(stripLead(m.text).split("\n"), {lines: 3}), minis(m));
    } else if (m.kind === "code_result") {
      n = codeNode(m);
    } else if (m.kind === "owner") {
      n = ownerNode(m, false);
    } else {
      const cont = !!prev && SPEAKING.has(prev.kind) && prev.role === m.role && prev.round_id === m.round_id && m.ts - prev.ts < GROUP_MS;
      n = staffNode(m, cont);
    }
    n.dataset.id = String(m.id);
    n._m = m;
    return n;
  }
  const isResult = (m) => msgTypes(m).includes("conclusion") || ["code_result", "action"].includes(m.kind);
  const hay = (m) => `${m.speaker_name || ""} ${roleName(roles(), m.role)} ${m.text || ""}`.toLowerCase();
  function visible(m, pending) {
    if (st.q && !hay(m).includes(st.q)) return false;
    if (pending) return st.meeting == null && st.filter !== "result";
    if (st.meeting != null && m.round_id !== st.meeting) return false;
    if (st.filter === "result" && !isResult(m)) return false;
    if (st.filter === "owner" && !forOwners(m)) return false;
    if (st.filter !== "all" && m.kind === "trigger") return false;
    return true;
  }
  function apply(animate) {
    let lastDay = null, shown = 0;
    for (const n of list.children) {
      if (n.classList.contains("rm-day")) { lastDay = n; lastDay._any = false; continue; }
      if (!n._m) continue;
      const v = visible(n._m, n._pending);
      n.hidden = !v;
      if (v) { shown++; if (lastDay) lastDay._any = true; }
    }
    for (const n of list.querySelectorAll(".rm-day")) n.hidden = !n._any;
    fBar.hidden = st.meeting == null;
    const filtered = st.q || st.filter !== "all" || st.meeting != null;
    found.textContent = st.q ? `${fmt.int(shown)}개 찾음` : "";
    none.hidden = !(filtered && !shown && (st.msgs.length || st.pending.length));
    none.textContent = st.q ? "찾는 대화가 불러온 기록 안에 없습니다" : st.filter === "owner" ? "두 분과 주고받은 글이 아직 없습니다" : "보여 줄 결론이 아직 없습니다";
    if (animate) motion.swap(list);
  }
  const dayNode = (ts) => { const n = h("div", {class: "rm-day"}, h("span", null, dayLabel(ts))); n._day = fmt.dayKey(ts); return n; };

  /** The latest conclusion of the loaded messages: the lead's summary (first line), else the code's decision line. */
  function renderPin() {
    let best = null;
    for (let i = st.msgs.length - 1; i >= 0 && !best; i--) {
      const m = st.msgs[i];
      if (m.kind === "summary" || m.kind === "decision") best = m;
    }
    if (!best) { pin.hidden = true; return; }
    const sameRound = st.msgs.filter((m) => m.round_id === best.round_id);
    const lead = sameRound.filter((m) => m.kind === "summary").pop();
    const dec = sameRound.filter((m) => m.kind === "decision").pop();
    const first = (m) => stripLead(m.text).split("\n").map((x) => x.replace(/^\s*\d+\.\s*/, "").trim()).find(Boolean) || "";
    const main = lead || dec;
    pinText.textContent = first(main);
    pinSub.textContent = lead && dec ? stripLead(dec.text).split("\n")[0] : "";
    pinSub.hidden = !pinSub.textContent;
    pinWhen.textContent = fmt.hm(main.ts);
    pin.hidden = false;
    pin.onclick = () => {
      const n = list.querySelector(`[data-id="${main.id}"]`);
      if (!n) return;
      if (n.hidden) { st.filter = "all"; st.q = ""; search.value = ""; st.meeting = null; seg.set("all"); apply(false); }
      n.scrollIntoView({block: "center", behavior: motion.reduced() ? "auto" : "smooth"});
      n.classList.remove("rm-flash"); void n.offsetWidth; n.classList.add("rm-flash");
    };
  }

  /** Draw every message (room change, older page). */
  function renderAll(stick) {
    clear(list);
    let day = null, prev = null;
    for (const m of st.msgs) {
      const dk = fmt.dayKey(m.ts);
      if (dk !== day) { list.append(dayNode(m.ts)); day = dk; prev = null; }
      list.append(nodeOf(m, prev));
      prev = m;
    }
    renderPending();
    if (!st.msgs.length && !st.pending.length) list.append(emptyRoom());
    olderBtn.hidden = !st.hasMore;
    renderPin();
    apply(false);
    if (stick) requestAnimationFrame(() => toBottom(false));
  }
  function renderPending() {
    for (const n of [...list.querySelectorAll(".rm-pend")]) n.remove();
    for (const p of st.pending) {
      const n = ownerNode(p, true);
      n.classList.add("rm-pend"); n._pending = true; n._m = p;
      list.append(n);
    }
  }
  function emptyRoom() {
    // (the room's schedule sentence is the line under the input box: not repeated here)
    return h("div", {class: "rm-emptyroom"}, h("b", null, "아직 이 방에서 열린 회의가 없습니다"),
      h("p", {class: "muted"}, "회의가 열리면 직원들의 대화가 여기에 올라옵니다. 궁금한 점을 아래에 남겨 두셔도 됩니다 (선택)."),
      // fill-people: a strategy room shows its strategy's own code record until the first meeting
      stratOf(st.id, st.room) ? recordBox(ctx, stratOf(st.id, st.room)) : null);
  }
  /** Append really new messages (after the first paint): they slide in; the list follows only a reader at the bottom. */
  function appendNew(add) {
    const stick = nearBottom();
    const ph = list.querySelector(".rm-emptyroom");
    if (ph) ph.remove();
    let lastDay = [...list.querySelectorAll(".rm-day")].pop();
    const firstPend = list.querySelector(".rm-pend");
    let prev = st.msgs[st.msgs.length - add.length - 1] || null;
    for (const m of add) {
      const dk = fmt.dayKey(m.ts);
      if (!lastDay || lastDay._day !== dk) { lastDay = dayNode(m.ts); list.insertBefore(lastDay, firstPend); prev = null; }
      const n = nodeOf(m, prev);
      list.insertBefore(n, firstPend);
      if (m.kind === "owner" || SPEAKING.has(m.kind)) motion.popBubble(n); else motion.slideIn(n);
      prev = m;
    }
    renderPending();
    renderPin();
    apply(false);
    if (stick) requestAnimationFrame(() => toBottom(true)); else newBtn.hidden = false;
  }

  // ---------------------------------------------------------------- data
  const curOv = () => st.ov && (st.ov.rooms || []).find((r) => r.room_id === st.id);
  async function open(id) {
    const req = ++st.req;
    if (id !== st.id) {
      Object.assign(st, {id, room: null, msgs: [], pending: [], lastId: 0, hasMore: false, meeting: null, q: ""});
      search.value = ""; found.textContent = "";
      empty.hidden = true; body.hidden = false; pin.hidden = true;
      clear(list); list.append(motion.shimmer(4));
      fBar.hidden = true; newBtn.hidden = true; none.hidden = true;
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
    st.drewBoard = !!board();
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

  /** The meeting running in this room now, from /api/office (its stored turns and the order's next speaker). */
  function renderRun() {
    const r = curOv();
    const o = store.get("office");
    const m = r && r.running && o ? (o.running || []).find((x) => x.room_id === st.id) : null;
    runLine.hidden = !(r && r.running);
    if (runLine.hidden) return;
    const turns = m ? (m.turns || []).length : 0, people = m ? (m.participants || []).length : 0;
    runLine.replaceChildren(ui.livePill("회의 중"),
      h("span", {class: "rm-run-t"}, m ? `${KIND_KO.trigger} ${fmt.hm(m.started_ts)} · 지금까지 발언 ${fmt.int(turns)}번` : "직원들이 지금 이 방에서 회의 중입니다"),
      m && people ? h("span", {class: "rm-run-p", title: "회의 순서에 이름이 오른 직원 수 (답에 따라 바뀔 수 있음)"}, `· 예정 인원 ${fmt.int(people)}명`) : null,
      m && m.next_role ? h("span", {class: "rm-run-n"}, `· 다음 차례 ${roleName(roles(), m.next_role)}`) : null,
      h("span", {class: "rm-run-h"}, "다음 발언이 기록되면 여기에 나옵니다 (실시간 타이핑 아님)"));
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
    avs.replaceChildren(...members.slice(0, 5).map((m) => pixAvatar(roles(), m.id, {size: 20})));
    avs.title = members.map((m) => m.name).join(", ");
    const n = r ? r.open_proposals || 0 : 0;
    waitBtn.hidden = !n;
    waitBtn.replaceChildren("두 분 확인을 기다리는 제안 ", h("b", null, `${fmt.int(n)}건`), h("span", null, "승인·거절 →"));
    renderRun();
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
        requestAnimationFrame(() => toBottom(true));
      }
    } catch (err) { ctx.toast((err && err.detail) || "보내지 못했습니다. 잠시 뒤 다시 시도해 주세요"); } finally { send.disabled = false; }
  });

  return {el, open, fetchNew, renderHead, current: () => st.id,
    setOv(ov) { const was = !!(curOv() || {}).running; st.ov = ov; if (st.id) { renderHead(); if (was !== !!(curOv() || {}).running) renderPending(); } },
    officeChanged() { if (st.id) renderRun(); },
    /** The board arrived after the room was drawn: draw again once so the strategy / account cards appear. */
    boardChanged() {
      if (!st.id || !st.room || st.drewBoard) return;
      st.drewBoard = true;
      const t0 = scroller.scrollTop, atEnd = nearBottom();
      renderAll(false);
      if (atEnd) toBottom(false); else scroller.scrollTop = t0;
    },
    clearRoom() { st.id = null; empty.hidden = false; body.hidden = true; }};
}

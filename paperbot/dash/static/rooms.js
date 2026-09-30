"use strict";
// 에이전트 방: the staff discuss, decide and resolve by themselves. Meetings start from code triggers
// (losses piling up, a bust, incidents, the daily schedule); nobody has to type. agents3.db is written
// by the agents tick and only read here. The owners may join in (optional) and approve or reject copy
// proposals; both go to inbox.db (this dashboard is its only writer) and the staff pick them up on
// their next turn. Everything shown here is text written by code or by the staff: always escaped.
// Uses helpers and state from app.js ($, api, esc, toast, chip, state, seg).
const KIND_KO = {analysis: "분석", challenge: "반론", expert: "전문가 의견", revision: "최종안", verdict: "판정",
  summary: "요약", action: "실행", code_result: "코드 계산", decision: "결정", owner: "두 분", system: "알림", trigger: "회의 시작"};
const TEAM_AV = {"team:market": "시장", "team:risk": "위험", "team:ops": "운영", "team:review": "복기", "team:lead": "총괄"};
// short avatar labels for the roles that speak in rooms (others: the first two letters of the name)
const ROLE_AV = {validator: "검증", approver: "승인", devils_advocate: "반론", entry_timing: "진입", exit_timing: "청산",
  whatif: "가정", strategist: "전략", team_lead: "팀장", chart_regime: "차트", derivs_flow: "파생", ops_auditor: "감사",
  pnl_reviewer: "복기", risk_officer: "위험", data_quality: "품질", code_reviewer: "코드", league_referee: "심판",
  rule_keeper: "규칙", performance: "성과"};
const PSTATUS_KO = {awaiting_owner: "두 분 확인 대기", approved: "승인됨", rejected: "거절됨",
  blocked_gate: "코드 관문에서 막힘", blocked_cap: "복제 한도로 막힘"};
const TRIAL_KIND_KO = {hypothesis: "가설", test: "5년 시험", copy_proposal: "복제 제안"};
const TRIAL_ST_KO = {passed: "통과", failed: "불통과", described: "설명용", no_data: "자료 없음", error: "오류"};
const rs = {ov: null, filter: "", q: "", cur: null, room: null, msgs: [], pending: [], lastId: 0, hasMore: false,
  seen: null, busy: false, again: false, side: {}, confirm: null, req: 0, sideReq: 0, agentSt: ""};

// ------------------------------------------------------------ helpers
function sget(k) { try { return JSON.parse(localStorage.getItem(k)); } catch (e) { return null; } }
function sset(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* storage blocked */ } }
async function apiPost(path, body) {
  const r = await fetch(path, {method: "POST", credentials: "same-origin",
    headers: {"content-type": "application/json"}, body: JSON.stringify(body)});
  if (r.status === 401) { location.href = "/login"; throw new Error("로그인이 필요합니다"); }
  let d = null;
  try { d = await r.json(); } catch (e) { /* no body */ }
  if (!r.ok) throw new Error((d && typeof d.detail === "string" && d.detail) || `오류 ${r.status}`);
  return d;
}
const narrow = () => window.matchMedia("(max-width: 1100px)").matches;
const oneLine = (t) => String(t || "").replace(/\s+/g, " ").trim();
const kfmt = (n) => n == null ? "—" : n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? Math.round(n / 1e3) + "k" : String(n);
function hm(ms) {
  if (!ms) return "";
  const d = new Date(ms), t = d.toLocaleTimeString("ko-KR", {hour: "2-digit", minute: "2-digit", hour12: false});
  return d.toDateString() === new Date().toDateString() ? t : `${d.getMonth() + 1}/${d.getDate()} ${t}`;
}
const dayKo = (ms) => new Date(ms).toLocaleDateString("ko-KR", {month: "long", day: "numeric", weekday: "short"});
function hue(s) { let h = 7; for (const ch of String(s)) h = (h * 31 + ch.charCodeAt(0)) % 360; return h; }
function roleAv(role, name) {
  if (role === "code") return '<span class="av code" title="코드(자동 계산)">⚙</span>';
  const n = ROLE_AV[role] || (String(role).startsWith("spec_") ? "전담" : oneLine(name || role).replace(/[·()\s]/g, "").slice(0, 2));
  return `<span class="av" style="--h:${hue(role)}">${esc(n)}</span>`;
}
function roomAv(r) {
  if (!r) return "";
  if (r.kind === "team") return `<span class="rav team">${esc(TEAM_AV[r.room_id] || String(r.title).slice(0, 2))}</span>`;
  return `<span class="rav">${esc(String(r.strategy || "").split("_")[0].slice(0, 4))}</span>`;
}
function testKo(t) {   // a trial spec / proposed change in one short Korean line
  if (!t) return "내용 없음";
  if (t.from_trial != null) return t.test ? `${testKo(t.test)} (시험 #${t.from_trial})` : `시험 #${t.from_trial} 결과로`;
  if (t.template === "stop_atr") return `손절 거리 ${t.k} ATR로`;
  if (t.template === "lock_start") return `첫 익절 잠금 +${Math.round((t.first_lock || 0) * 100)}%부터`;
  if (t.template === "skip_tag") return `'${t.tag}' 진입 건너뛰기`;
  if (t.template === "timeframe_only") return "봉별 성적 보기(설명용)";
  return t.text || t.template || "내용 없음";
}
const curOv = () => rs.ov && rs.ov.rooms.find((r) => r.room_id === rs.cur);
// Are the staff really running? The agents tick leaves its last sign of life in agents3.db (last_tick:
// {ts, ok, why}). "stopped": no sign for three ticks and no meeting running (timer off, server down);
// "login": the subscription login check refused the meetings (API key found, token expired); "error":
// the last pass crashed; "new": the agents have never run. Only "ok" may promise an answer soon.
function agentsState(ov) {
  if (!ov || !ov.ready) return {st: "new", age: null};
  const lt = ov.last_tick, running = (ov.rooms || []).some((r) => r.running);
  const age = lt && lt.ts ? Math.max(0, (ov.now || Date.now()) - lt.ts) : null;
  if (lt && lt.ok === false) return {st: lt.why === "login" ? "login" : "error", age};
  if (!running && (age == null || age > 3 * (ov.tick_every_ms || 900000))) return {st: "stopped", age};
  return {st: "ok", age};
}
const agoKo = (age) => age == null ? "점검 기록 없음" : `마지막 점검 ${Math.round(age / 60000)}분 전`;
function pendingHint(st) {
  if (st === "ok") return "직원들이 다음 차례에 읽고 답합니다";
  if (st === "new") return "에이전트가 돌기 시작하면 읽고 답합니다";
  return "에이전트가 멈춰 있어 아직 전달되지 않습니다";
}
const unread = (r) => r.last_id > ((rs.seen && rs.seen[r.room_id]) || 0);
const roomVisible = () => state.view === "rooms" && !!rs.cur && document.visibilityState === "visible" &&
  (!narrow() || $("rooms").dataset.pane === "chat");
function nearBottom() { const el = $("r-chat"); return el.scrollHeight - el.scrollTop - el.clientHeight < 90; }

// ------------------------------------------------------------ room list (overview)
async function loadOverview() {
  let ov;
  try { ov = await api("/api/rooms"); } catch (e) { return; }
  const wasRunning = !!(curOv() || {}).running;
  rs.ov = ov;
  if (!rs.seen) {
    rs.seen = sget("pb-room-seen");
    if (!rs.seen || typeof rs.seen !== "object") {   // first visit: nothing is "unread" yet
      rs.seen = {};
      ov.rooms.forEach((r) => { rs.seen[r.room_id] = r.last_id; });
      sset("pb-room-seen", rs.seen);
    }
  }
  const st = agentsState(ov).st, stChanged = st !== rs.agentSt;
  rs.agentSt = st;
  renderRoomList(); navDot(); aiChip();
  if (rs.cur) {
    renderHead();
    if (stChanged || wasRunning !== !!(curOv() || {}).running) renderChat(nearBottom());
  }
}
function aiChip() {
  const ov = rs.ov;
  if (!ov) return;
  const running = ov.rooms.filter((r) => r.running).length;
  const a = agentsState(ov), ago = agoKo(a.age);
  if (a.st === "new") chip("chip-ai", null, "에이전트 시작 전");
  else if (a.st === "login") chip("chip-ai", false, "에이전트 멈춤 (로그인 확인)");
  else if (a.st === "error") chip("chip-ai", false, `에이전트 멈춤 (오류, ${ago})`);
  else if (a.st === "stopped") chip("chip-ai", null, `에이전트 멈춤 (${ago})`);
  else chip("chip-ai", true, running ? `자동 토론 중 ${running}곳` : "자동 토론 대기");
  $("r-auto").classList.toggle("off", a.st !== "ok");
  $("r-auto").innerHTML = {
    ok: "<b>● 자동 토론</b> 손실이 쌓이거나 사고가 나거나 정해진 시간이 되면 직원들이 스스로 회의를 열고 결정합니다. 두 분이 글을 쓰지 않아도 됩니다.",
    new: "<b>○ 자동 토론 시작 전</b> 서버에서 에이전트 순번이 돌기 시작하면 직원들이 스스로 회의를 엽니다. 지금 남긴 글은 그때 읽습니다.",
    stopped: `<b>○ 자동 토론이 멈춰 있습니다 — 서버 확인 필요</b> 에이전트 순번이 돌지 않고 있습니다(${esc(ago)}). 타이머가 꺼졌거나 서버에 문제가 있을 수 있습니다. 남긴 글은 다시 돌기 시작하면 읽습니다.`,
    login: "<b>⚠ 로그인 확인에서 멈춤(API 키 감지 등): 회의가 열리지 않습니다</b> 서버에서 Claude 구독 로그인을 확인해 주세요(docs/agent-rooms.md의 설치 1번). 남긴 글은 그 뒤에 읽습니다.",
    error: `<b>⚠ 에이전트 실행 중 오류로 멈춤</b> 서버 기록(journalctl -u paperbot-agents)을 확인해 주세요(${esc(ago)}). 남긴 글은 다시 돌기 시작하면 읽습니다.`,
  }[a.st];
}
function navDot() {
  const n = rs.ov ? rs.ov.rooms.filter(unread).length : 0;
  const dot = document.querySelector("#nav-rooms .ndot");
  if (dot) dot.hidden = !n;
  $("nav-rooms").title = n ? `새 대화가 있는 방 ${n}곳` : "";
}
function renderRoomList() {
  const ov = rs.ov;
  if (!ov) return;
  const q = rs.q.trim().toLowerCase();
  const match = (r) => (!rs.filter || r.kind === rs.filter) &&
    (!q || String(r.title).toLowerCase().includes(q) || String(r.strategy || "").toLowerCase().includes(q));
  const team = ov.rooms.filter((r) => r.kind === "team" && match(r));
  const strat = ov.rooms.filter((r) => r.kind === "strategy" && match(r))
    .sort((a, b) => (b.running - a.running) || ((b.last_ts || 0) - (a.last_ts || 0)) || (b.last_id - a.last_id));
  const waiting = ov.rooms.reduce((s, r) => s + (r.open_proposals || 0), 0);
  const row = (r) => {
    const who = r.last_speaker && !["code", "system"].includes(r.last_role) ? r.last_speaker + ": " : "";
    const last = r.last_text ? esc(who + oneLine(r.last_text))
      : '<span class="muted">아직 회의 없음</span>';
    return `<div class="room ${r.room_id === rs.cur ? "sel" : ""} ${unread(r) ? "unread" : ""}" data-r="${esc(r.room_id)}" role="button" tabindex="0">
      ${roomAv(r)}<div class="rb"><div class="r1"><span class="nm">${esc(r.title)}</span><time>${hm(r.last_ts)}</time></div>
      <div class="r2"><span class="lt">${last}</span>${r.running ? '<span class="pill live">토론 중</span>' : ""}
      ${r.open_proposals ? `<span class="pill acc">승인 대기 ${esc(r.open_proposals)}</span>` : ""}${unread(r) ? '<i class="udot" title="새 대화"></i>' : ""}</div></div></div>`;
  };
  const html = (waiting ? `<button class="rwait" id="r-wait">두 분 확인을 기다리는 제안 <b>${waiting}건</b><span>보기 →</span></button>` : "") +
    (team.length ? `<div class="rsec">팀 방 <small>${team.length}</small></div>` + team.map(row).join("") : "") +
    (strat.length ? `<div class="rsec">매매법 방 <small>${strat.length}</small><span>최근 대화 순</span></div>` + strat.map(row).join("") : "");
  $("rlist").innerHTML = html || '<p class="empty">찾는 방이 없습니다</p>';
  document.querySelectorAll("#rlist .room").forEach((el) => {
    el.onclick = () => openRoom(el.dataset.r, "chat");
    el.onkeydown = (e) => { if (e.key === "Enter") openRoom(el.dataset.r, "chat"); };
  });
  if ($("r-wait")) $("r-wait").onclick = () => {
    const r = ov.rooms.find((x) => x.open_proposals);
    if (r) openRoom(r.room_id, narrow() ? "info" : "chat");
  };
}
seg("rl-filter", "f", (f) => { rs.filter = f; renderRoomList(); });
$("r-q").oninput = (e) => { rs.q = e.target.value; renderRoomList(); };

// ------------------------------------------------------------ one room
function setPane(p) {
  $("rooms").dataset.pane = p;
  if (p === "chat") { markSeen(); requestAnimationFrame(() => { const el = $("r-chat"); el.scrollTop = el.scrollHeight; }); }
}
$("r-back").onclick = () => setPane("list");
$("r-back2").onclick = () => setPane("chat");
$("r-info").onclick = () => setPane("info");
function markSeen() {
  if (!roomVisible()) return;
  const r = curOv();
  const top = Math.max(rs.lastId, r ? r.last_id : 0);
  if (!rs.seen || (rs.seen[rs.cur] || 0) >= top) return;
  rs.seen[rs.cur] = top;
  sset("pb-room-seen", rs.seen);
  renderRoomList(); navDot();
}
function defaultRoom() {
  const rooms = (rs.ov && rs.ov.rooms) || [];
  const best = rooms.reduce((b, r) => (!b || r.last_id > b.last_id ? r : b), null);
  return best && best.last_id ? best.room_id : "team:lead";
}
async function loadRooms() {
  await loadOverview();
  if (!rs.ov) return;
  if (!rs.cur) {
    const saved = sget("pb-room");
    const pick = saved && rs.ov.rooms.some((r) => r.room_id === saved) ? saved : defaultRoom();
    await openRoom(pick, narrow() ? "list" : "chat");
  } else {
    fetchNew(); loadSide();
    if ($("rooms").dataset.pane === "chat") markSeen();
  }
}
async function openRoom(id, pane) {
  const req = ++rs.req;
  if (id !== rs.cur) {
    rs.cur = id; rs.room = null; rs.msgs = []; rs.pending = []; rs.lastId = 0; rs.hasMore = false; rs.confirm = null;
    rs.side = {};
    $("r-chat").innerHTML = '<p class="empty">불러오는 중…</p>';
    $("r-side").innerHTML = "";
  }
  sset("pb-room", id);
  renderRoomList(); renderHead();
  setPane(pane || "chat");
  let d;
  try { d = await api(`/api/rooms/${encodeURIComponent(id)}/messages?limit=200`); } catch (e) {
    if (req === rs.req) $("r-chat").innerHTML = '<p class="empty">대화를 불러오지 못했습니다</p>';
    return;
  }
  if (req !== rs.req) return;
  rs.room = d.room; rs.msgs = d.messages; rs.pending = d.pending_owner; rs.hasMore = d.has_more;
  rs.lastId = rs.msgs.length ? rs.msgs[rs.msgs.length - 1].id : 0;
  renderHead(); renderChat(true); markSeen();
  loadSide();
}
async function fetchNew() {
  if (!rs.cur || !rs.room) return;
  if (rs.busy) { rs.again = true; return; }
  rs.busy = true;
  const id = rs.cur;
  try {
    const d = await api(`/api/rooms/${encodeURIComponent(id)}/messages?after_id=${rs.lastId}&limit=500`);
    if (id !== rs.cur) return;
    const stick = nearBottom();
    const add = d.messages.filter((m) => m.id > rs.lastId);
    rs.msgs = rs.msgs.concat(add);
    rs.pending = d.pending_owner;
    if (rs.msgs.length) rs.lastId = rs.msgs[rs.msgs.length - 1].id;
    renderChat(stick);
    if (add.length && !stick) $("r-new").hidden = false;
    markSeen();
    if (add.some((m) => ["decision", "action", "code_result", "verdict", "owner", "system"].includes(m.kind))) loadSide();
  } catch (e) { /* next event retries */ } finally {
    rs.busy = false;
    if (rs.again) { rs.again = false; fetchNew(); }
  }
}
async function loadOlder() {
  const first = rs.msgs[0];
  if (!first || !rs.cur) return;
  const id = rs.cur;
  const d = await api(`/api/rooms/${encodeURIComponent(id)}/messages?before_id=${first.id}&limit=200`).catch(() => null);
  if (!d || id !== rs.cur) return;
  const el = $("r-chat"), h0 = el.scrollHeight, t0 = el.scrollTop;
  rs.msgs = d.messages.concat(rs.msgs); rs.hasMore = d.has_more;
  renderChat(false);
  el.scrollTop = el.scrollHeight - h0 + t0;
}

// ------------------------------------------------------------ chat
function renderHead() {
  const r = curOv(), info = rs.room;
  if (!rs.cur) return;
  const base = r || info || {room_id: rs.cur, title: rs.cur, kind: rs.cur.startsWith("team:") ? "team" : "strategy"};
  $("r-av").innerHTML = roomAv(base);
  $("r-title").textContent = base.title;
  const members = ((info && info.members) || (r && r.members) || []).length;
  $("r-sub").textContent = `${base.kind === "team" ? "팀 방" : "매매법 전담 방"} · 멤버 ${members}명` +
    (r ? ` · 오늘 회의 ${r.rounds_today}번` : "");
  $("r-state").innerHTML = r && r.running ? '<span class="pill live">토론 중</span>'
    : ["ok", "new"].includes(agentsState(rs.ov).st)
      ? '<span class="pill" title="조건이 되면 직원들이 스스로 회의를 엽니다">다음 회의 대기</span>'
      : '<span class="pill bad" title="에이전트가 멈춰 있어 회의가 열리지 않습니다">에이전트 멈춤</span>';
  const n = r ? r.open_proposals : 0;
  $("r-banner").hidden = !n;
  if (n) $("r-banner").innerHTML = `두 분 확인을 기다리는 제안 <b>${n}건</b><span>승인·거절 →</span>`;
}
$("r-banner").onclick = () => {
  if (narrow()) setPane("info");
  const el = $("r-props");
  if (!el) return;
  el.scrollIntoView({block: "start", behavior: "smooth"});
  el.classList.add("flash"); setTimeout(() => el.classList.remove("flash"), 1400);
};
function evid(e) {
  if (e == null || e === "" || (Array.isArray(e) && !e.length)) return "";
  const list = Array.isArray(e) ? e : [e];
  return `<details class="ev"><summary>근거 ${list.length}곳</summary>${list.map((x) =>
    `<code>${esc(typeof x === "string" ? x : JSON.stringify(x))}</code>`).join("")}</details>`;
}
function gateBadge(d) {
  const g = d && d.gate;
  if (g && g.pass === true) return '<span class="pill ok">관문 통과</span>';
  if (g && g.pass === false) return '<span class="pill bad">관문 불통과</span>';
  if (d && d.status) return `<span class="pill">${esc(TRIAL_ST_KO[d.status] || d.status)}</span>`;
  return "";
}
function ownerHtml(m, pending) {
  const who = pending ? (m.author ? `두 분 (${m.author})` : "두 분") : (m.speaker_name || "두 분");
  return `<div class="m owner ${pending ? "pending" : ""}"><div class="bd"><div class="who"><time>${hm(m.ts)}</time><b>${esc(who)}</b>
    ${pending ? '<span class="kchip wait">전달 대기</span>' : ""}</div><div class="bub">${esc(m.text)}</div>
    ${pending ? `<div class="hint">${esc(pendingHint(agentsState(rs.ov).st))}</div>` : ""}</div></div>`;
}
function msgHtml(m) {
  const k = m.kind, who = m.speaker_name || m.role;
  if (k === "trigger") return `<div class="mtrig"><div class="tl">${m.round_id ? `회의 #${esc(m.round_id)}` : "회의"} · ${hm(m.ts)}</div>
    <div class="tx">${esc(m.text)}</div></div>`;
  if (k === "system") return `<div class="mline sys">${esc(m.text)}<time>${hm(m.ts)}</time></div>`;
  if (k === "owner") return ownerHtml(m, false);
  if (k === "code_result") return `<div class="mcard code"><div class="hd"><b>코드 계산 결과</b>${gateBadge(m.data)}
    <span class="grow"></span><time>${hm(m.ts)}</time></div><div class="tx">${esc(m.text)}</div></div>`;
  if (k === "decision") return `<div class="mcard decision"><div class="hd"><b>회의 결론</b><span class="muted">숫자는 코드가 정리</span>
    <span class="grow"></span><time>${hm(m.ts)}</time></div><div class="tx">${esc(m.text)}</div></div>`;
  if (k === "action") return `<div class="mact"><span>${esc(m.text)}</span><time>${hm(m.ts)}</time></div>`;
  return `<div class="m">${roleAv(m.role, who)}<div class="bd"><div class="who"><b>${esc(who)}</b>
    <span class="kchip ${esc(k)}">${esc(KIND_KO[k] || k)}</span><time>${hm(m.ts)}</time></div>
    <div class="bub">${esc(m.text)}</div>${evid(m.evidence)}</div></div>`;
}
function emptyRoom() {
  const s = (rs.room && rs.room.schedule_ko) || (curOv() || {}).schedule_ko || "";
  return `<div class="rempty"><div class="big">아직 이 방에서 열린 회의가 없습니다</div>
    <div>${esc(s)}</div><div class="muted">회의가 열리면 직원들의 대화가 여기에 실시간으로 올라옵니다.
    궁금한 점을 아래에 남겨 두셔도 됩니다(선택).</div></div>`;
}
function renderChat(stick) {
  const el = $("r-chat");
  if (!rs.cur) { el.innerHTML = '<p class="empty">왼쪽에서 방을 고르세요</p>'; return; }
  let html = rs.hasMore ? '<button class="rmore" id="r-more">이전 대화 더 보기</button>' : "";
  if (!rs.msgs.length && !rs.pending.length) html += emptyRoom();
  let day = "";
  for (const m of rs.msgs) {
    const dk = new Date(m.ts).toDateString();
    if (dk !== day) { html += `<div class="mday"><span>${esc(dayKo(m.ts))}</span></div>`; day = dk; }
    html += msgHtml(m);
  }
  html += rs.pending.map((p) => ownerHtml(p, true)).join("");
  if ((curOv() || {}).running) html += '<div class="typing"><span class="dots"><i></i><i></i><i></i></span>직원들이 토론하고 있습니다</div>';
  el.innerHTML = html;
  if (stick) { el.scrollTop = el.scrollHeight; $("r-new").hidden = true; }
  if ($("r-more")) $("r-more").onclick = loadOlder;
}
$("r-chat").addEventListener("scroll", () => { if (nearBottom()) $("r-new").hidden = true; });
$("r-new").onclick = () => { const el = $("r-chat"); el.scrollTop = el.scrollHeight; $("r-new").hidden = true; };

// ------------------------------------------------------------ owner input (optional)
const rin = $("r-in");
function growInput() {
  rin.style.height = "";
  if (rin.value) rin.style.height = Math.min(Math.max(rin.scrollHeight + 2, rin.offsetHeight), 150) + "px";
  $("r-count").textContent = `${rin.value.length}/1000`;
}
rin.addEventListener("input", growInput);
rin.addEventListener("keydown", (e) => {   // Enter sends on a keyboard; never while Hangul is being composed
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing && e.keyCode !== 229 && !narrow()) {
    e.preventDefault(); $("r-form").requestSubmit();
  }
});
$("r-form").onsubmit = async (e) => {
  e.preventDefault();
  const text = rin.value.trim();
  if (!text || !rs.cur) return;
  const id = rs.cur;
  $("r-send").disabled = true;
  try {
    const d = await apiPost(`/api/rooms/${encodeURIComponent(id)}/say`, {text});
    rin.value = ""; growInput();
    if (id === rs.cur) { rs.pending.push(d); renderChat(true); }
    const st = agentsState(rs.ov).st;
    toast(st === "ok" ? "전달했습니다. 직원들이 다음 차례에 읽고 답합니다" : `저장했습니다. ${pendingHint(st)}`);
  } catch (err) { toast(err.message); } finally { $("r-send").disabled = false; }
};

// ------------------------------------------------------------ right: members, proposals, notes, ledger, usage
async function loadSide() {
  const id = rs.cur;
  if (!id) return;
  const req = ++rs.sideReq;
  const strat = id.startsWith("strat:") ? id.slice(6) : "";
  const [notes, trials, props, usage] = await Promise.all([
    api(`/api/rooms/${encodeURIComponent(id)}/notes?limit=20`).catch(() => []),
    api(`/api/trials?limit=6${strat ? "&strategy=" + encodeURIComponent(strat) : ""}`).catch(() => null),
    api(`/api/proposals?room_id=${encodeURIComponent(id)}&limit=20`).catch(() => []),
    api("/api/agents/usage").catch(() => null)]);
  if (req !== rs.sideReq || id !== rs.cur) return;
  rs.side = {notes, trials, props, usage};
  renderSide();
}
function decideButtons(p, label) {
  if (rs.confirm && rs.confirm.id === p.id) {
    const ap = rs.confirm.dec === "approve";
    return `<div class="pconfirm">${ap ? "정말 승인할까요? 계좌는 지금 만들어지지 않고, 복제 계좌 기능이 생기면 시작됩니다."
      : "정말 거절할까요? 거절한 제안은 다시 승인할 수 없습니다."}
      <div class="pacts"><button class="${ap ? "okb" : "nob"}" data-go="${esc(p.id)}">${ap ? "승인" : "거절"} 확인</button><button data-cancel="1">취소</button></div></div>`;
  }
  if (label === "reject-only") return `<div class="pacts"><button class="nob sm" data-dec="reject" data-p="${esc(p.id)}">거절로 바꾸기</button></div>`;
  if (label === "stale") return `<div class="pacts"><button class="nob" data-dec="reject" data-p="${esc(p.id)}">거절</button></div>`;
  return `<div class="pacts"><input placeholder="메모(선택)" data-note="${esc(p.id)}" maxlength="1000" aria-label="메모">
    <button class="okb" data-dec="approve" data-p="${esc(p.id)}">승인</button><button class="nob" data-dec="reject" data-p="${esc(p.id)}">거절</button></div>`;
}
function propCard(p) {
  const ch = p.change || {}, g = p.gate || {}, od = p.owner_decision, gn = p.gate_now;
  // the tick re-judges open proposals with the room's current number of tests (Bonferroni)
  const stale = !!(gn && gn.pass === false && (p.status === "awaiting_owner" || p.status === "approved"));
  let acts = "";
  if (od && !od.applied) {
    acts = `<div class="pdone">두 분 결정: <b>${od.decision === "approve" ? "승인" : "거절"}</b> · 직원들이 다음 차례에 반영합니다</div>` +
      (p.effective_status === "approved" ? decideButtons(p, "reject-only") : "");
  } else if (p.status === "awaiting_owner") acts = stale ? decideButtons(p, "stale") : decideButtons(p);
  return `<div class="pcard"><div class="ttl">제안 #${esc(p.id)} · ${esc(p.strategy_ko || p.strategy || "")}</div>
    <div class="ln"><b>${esc(testKo(ch.test))}</b></div>
    ${ch.why ? `<div class="ln">이유: ${esc(ch.why)}</div>` : ""}
    ${ch.approver ? `<div class="ln">자율 승인관: ${ch.approver.approve ? "승인" : "거부"} — ${esc(ch.approver.reason || "")}</div>` : ""}
    <div class="ln">코드 관문${gn ? "(제안 때)" : ""}: ${g.pass === true ? '<span class="up">✓ 통과</span>' : '<span class="down">✕ 불통과</span>'}${p.trial_id ? ` · 시험 #${esc(p.trial_id)}` : ""}${g.n_trials ? ` · 이 방 ${esc(g.n_trials)}번째 시험` : ""}</div>
    ${gn ? `<div class="ln">지금 다시 판정(이 방 시험 ${esc(gn.n_trials)}번 기준): ${gn.pass === true ? '<span class="up">✓ 통과</span>' : '<span class="down">✕ 불통과 · 승인할 수 없음</span>'}</div>` : ""}
    ${(g.reasons || []).length ? `<ul class="reasons">${g.reasons.slice(0, 5).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
    ${acts}</div>`;
}
// One row of the hypothesis ledger. A copy proposal is named by its PROPOSAL number (the one the owners
// approve or reject, "제안 #N") with its status; the test it came from is "시험 #M"; other rows are "기록 #K".
function ledgerRow(t) {
  const sp = t.spec || {};
  if (t.kind === "copy_proposal") {
    const st = t.proposal_status;
    const cls = st === "approved" ? "ok" : st === "awaiting_owner" ? "acc"
      : (st && (st.startsWith("blocked") || st === "rejected")) ? "bad" : "";
    return `<div class="trow"><span>${t.proposal_id != null ? `복제 제안 #${esc(t.proposal_id)}` : "복제 제안"} · ${esc(testKo(sp.test))}${sp.from_trial != null ? ` (시험 #${esc(sp.from_trial)})` : ""}</span>
      ${st ? `<span class="pill ${cls}">${esc(PSTATUS_KO[st] || st)}</span>` : ""}</div>`;
  }
  const label = t.kind === "test" ? `시험 #${esc(t.id)}` : `기록 #${esc(t.id)} ${esc(TRIAL_KIND_KO[t.kind] || t.kind)}`;
  return `<div class="trow"><span>${label} · ${esc(testKo(sp))}</span>
    ${t.result ? `<span class="pill ${t.result.status === "passed" ? "ok" : t.result.status === "failed" ? "bad" : ""}">${esc(TRIAL_ST_KO[t.result.status] || t.result.status)}</span>` : ""}</div>`;
}
function bar(v, cap) {
  if (!cap) return "";
  const f = Math.min(1, (v || 0) / cap);
  return `<div class="ubar"><i style="width:${Math.round(f * 100)}%;${f >= 0.9 ? "background:var(--down)" : f >= 0.7 ? "background:var(--accent)" : ""}"></i></div>`;
}
function renderSide() {
  const {notes = [], trials = null, props = [], usage = null} = rs.side || {};
  const info = rs.room, r = curOv();
  $("r-side-title").textContent = (r || info) ? `${(r || info).title} 정보` : "방 정보";
  const waiting = props.filter((p) => p.status === "awaiting_owner");
  const past = props.filter((p) => p.status !== "awaiting_owner").slice(0, 5);
  let h = "";
  const open = waiting.filter((p) => p.effective_status === "awaiting_owner").length;
  if (waiting.length) h += `<div class="rsec2 hl" id="r-props"><h4>두 분 확인이 필요한 제안
    ${open ? `<span class="pill acc">${open}</span>` : '<span class="pill">결정함 · 반영 대기</span>'}</h4>
    ${waiting.map(propCard).join("")}<div class="hint">승인해도 지금은 계좌가 만들어지지 않습니다. 복제 계좌 기능이 생기면 새 $1,000 계좌로 따로 시작하고,
    원본 195개 계좌와 규칙은 그대로입니다. 코드 관문을 통과하지 못한 제안은 누구도 승인할 수 없습니다.</div></div>`;
  h += `<div class="rsec2"><h4>이 방은 언제 회의하나요</h4><div class="dim">${esc((info && info.schedule_ko) || (r && r.schedule_ko) || "")}</div>
    <div class="hint">직원들이 스스로 회의를 열고 결정합니다. 두 분이 글을 남기면 다음 차례에 그 이야기도 다룹니다.</div></div>`;
  if (info && info.members_info) h += `<div class="rsec2"><h4>멤버 <small>${info.members_info.length}명</small></h4>${info.members_info.map((m) =>
    `<div class="mem">${roleAv(m.id, m.name)}<div class="mb"><div class="nm">${esc(m.name)}</div><div class="du">${esc(m.duty)}</div></div></div>`).join("")}</div>`;
  if (past.length) h += `<div class="rsec2"><h4>지난 제안</h4>${past.map((p) => `<div class="prow"><span>제안 #${esc(p.id)} ${esc(testKo((p.change || {}).test))}</span>
    <span class="pill ${p.effective_status === "approved" ? "ok" : p.effective_status.startsWith("blocked") ? "bad" : ""}">${esc(PSTATUS_KO[p.effective_status] || p.effective_status)}</span>
    ${p.status === "approved" && !(p.owner_decision && !p.owner_decision.applied) ? decideButtons(p, "reject-only") : ""}</div>`).join("")}</div>`;
  h += `<div class="rsec2"><h4>메모 <small>${notes.length}</small></h4>${notes.length ? notes.slice(0, 8).map((n) =>
    `<div class="nrow"><div>${esc(n.text)}</div><time>${hm(n.ts)}</time></div>`).join("") : '<div class="muted">아직 메모가 없습니다</div>'}</div>`;
  if (trials) {
    const c = trials.counts || {};
    h += `<div class="rsec2"><h4>가설 장부 ${rs.cur.startsWith("team:") ? "<small>전체 매매법</small>" : ""}</h4>
      <div class="ledger"><div><b>${esc(c.hypothesis || 0)}</b><span>가설</span></div><div><b>${esc(c.test || 0)}</b><span>5년 시험</span></div>
      <div><b>${esc(c.copy_proposal || 0)}</b><span>복제 제안</span></div></div>
      ${(trials.trials || []).slice(0, 5).map(ledgerRow).join("")}
      <div class="hint">시험을 많이 할수록 통과 기준이 엄격해집니다(우연 방지).</div></div>`;
  }
  if (usage) {
    h += `<div class="rsec2"><h4>오늘 AI 사용</h4><div class="ubig"><b>${esc(usage.calls)}</b>${usage.cap_calls ? ` / ${esc(usage.cap_calls)}회` : "회"}
      <span class="muted">· 토큰 ${kfmt(usage.tokens)}${usage.cap_tokens ? " / " + kfmt(usage.cap_tokens) : ""}</span></div>${bar(usage.calls, usage.cap_calls)}
      ${usage.classes.map((c) => `<div class="urow"><span>${esc(c.name_ko)}</span><span class="mono">${esc(c.calls)}${c.cap_calls ? " / " + esc(c.cap_calls) : ""}</span></div>${bar(c.calls, c.cap_calls)}`).join("")}
      ${usage.week ? `<div class="urow"><span>최근 7일 합계</span><span class="mono">${esc(usage.week.calls)}${usage.week.cap_calls ? " / " + esc(usage.week.cap_calls) : ""}</span></div>${bar(usage.week.calls, usage.week.cap_calls)}` : ""}
      <div class="hint">두 분의 Claude 구독 사용량을 함께 씁니다. 한도에 닿으면 회의를 다음으로 미룹니다.</div></div>`;
  }
  $("r-side").innerHTML = h;
  document.querySelectorAll("#r-side [data-dec]").forEach((b) => b.onclick = () => {
    const pid = +b.dataset.p, inp = document.querySelector(`#r-side [data-note="${pid}"]`);
    rs.confirm = {id: pid, dec: b.dataset.dec, note: inp ? inp.value : ""};
    renderSide();
  });
  document.querySelectorAll("#r-side [data-cancel]").forEach((b) => b.onclick = () => { rs.confirm = null; renderSide(); });
  document.querySelectorAll("#r-side [data-go]").forEach((b) => b.onclick = async () => {
    const c = rs.confirm;
    if (!c) return;
    b.disabled = true;
    try {
      const d = await apiPost(`/api/proposals/${c.id}/decide`, {decision: c.dec, note: c.note});
      toast(d.message || "전달했습니다");
    } catch (err) { toast(err.message); }
    rs.confirm = null;
    loadSide(); loadOverview();
  });
}

// ------------------------------------------------------------ live updates (from app.js's /api/stream)
let roomsOvTimer = null;
function onRoomsStream(changed) {   // changed: {room_id: newest id}, or null after a (re)connect
  clearTimeout(roomsOvTimer);
  roomsOvTimer = setTimeout(loadOverview, 300);
  if (rs.cur && (!changed || (changed[rs.cur] || 0) > rs.lastId)) fetchNew();
}
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") markSeen(); });
setInterval(() => { if (state.view === "rooms") loadOverview(); }, 20000);   // "토론 중" also changes between messages
loadOverview();

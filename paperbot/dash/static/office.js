"use strict";
// 회의실: the agent rooms drawn as one office. Everything comes from /api/office (agents3.db, read-only):
// who really spoke in a meeting that is running now, in order, and the first sentence of each one's latest
// message (a bubble changes when that staff member's AI turn has finished and been written, never typed
// live), whose turn comes next when the meeting's own order says so ('💭 생각 중'), today's finished
// meetings and the fixed meeting hours the agents published. No invented lines: no meeting, no bubble.
// Uses helpers and state from app.js ($, api, esc, state, show) and rooms.js (openRoom, hm, ROLE_AV).
const OF_POLL_MS = 6000;
// one hue per roster team (roster3.TEAMS): staff are coloured by the team they belong to
const OF_TEAM_HUE = {market: 205, plan: 268, risk: 2, ops: 150, dev: 185, lead: 42, review: 322, evolve: 95,
  compare: 230, timing: 24, safety: 58, specialist: 0};
const OF_STATUS_KO = {done: "결정", no_action: "행동 없음", failed: "멈춤", stopped_budget: "한도로 멈춤", running: "회의 중"};
const OF_KIND_KO = {analysis: "분석", challenge: "반론", expert: "전문가 의견", revision: "최종안", verdict: "판정", summary: "요약"};
// where the staff stand in a zone (percent of the floor; the feet of the figure)
const OF_DESK_Y = 30, OF_TABLE = {x: 50, y: 70};
const OF_SEATS = [[-1, 0], [1, 0], [-0.45, -1], [0.45, -1], [-0.45, 1], [0.45, 1], [0, -1], [0, 1]];
const of = {d: null, busy: false, timer: null, err: false, seen: {}};

function ofRole(id) { return (of.d && of.d.roles && of.d.roles[id]) || {name: id, label: null, team: ""}; }
function ofShort(id) {
  const r = ofRole(id);
  if (r.label) return r.label;
  if (typeof ROLE_AV !== "undefined" && ROLE_AV[id]) return ROLE_AV[id];
  return String(r.name || id).replace(/[·()\s]/g, "").slice(0, 3);
}
// a small pixel figure: 10 x 14 cells. Body in the team's colour; a specialist wears the one generic look
// (a visor) and carries the strategy's Korean name as its label.
function ofFigure(spec) {
  const px = (x, y, w, h, c) => `<rect x="${x}" y="${y}" width="${w}" height="${h}" class="${c}"/>`;
  const svg = `<svg viewBox="0 0 10 14" width="20" height="28" shape-rendering="crispEdges" aria-hidden="true">
    ${spec ? px(2, 0, 6, 1, "pv") + px(1, 1, 8, 1, "pv") : px(2, 0, 6, 2, "ph")}
    ${px(2, 2, 6, 3, "ps")}${px(3, 3, 1, 1, "pe")}${px(6, 3, 1, 1, "pe")}
    ${px(1, 5, 8, 5, "pb")}${px(0, 6, 1, 3, "ps")}${px(9, 6, 1, 3, "ps")}
    ${px(2, 10, 2, 3, "pl l1")}${px(6, 10, 2, 3, "pl l2")}${px(2, 13, 2, 1, "pf l1")}${px(6, 13, 2, 1, "pf l2")}</svg>`;
  return svg;
}
function ofHue(id) { const r = ofRole(id); return OF_TEAM_HUE[r.team] ?? 210; }

// ------------------------------------------------------------ data
async function loadOffice() {
  if (of.busy) return;
  of.busy = true;
  try { of.d = await api("/api/office"); of.err = false; } catch (e) { of.err = true; }
  of.busy = false;
  renderOffice();
}
function ofVisible() { return state.view === "office" && document.visibilityState === "visible"; }
function ofTick() { if (ofVisible()) loadOffice(); }
setInterval(ofTick, OF_POLL_MS);
document.addEventListener("visibilitychange", ofTick);
let ofStreamT = null;
function onOfficeStream() {   // a room got a new message (app.js /api/stream): refresh soon while the view is open
  if (!ofVisible()) return;
  clearTimeout(ofStreamT);
  ofStreamT = setTimeout(loadOffice, 800);
}
function ofOpen(roomId) {
  if (!roomId || typeof openRoom !== "function") return;
  show("rooms");
  openRoom(roomId, "chat");
}

// ------------------------------------------------------------ the office floor
// zone -> {room_id, title, members, meeting|null}; the 36 strategy rooms share one zone
function ofZones(d) {
  const run = {};
  for (const m of d.running) if (!run[m.room_id]) run[m.room_id] = m;
  const zones = d.zones.map((z) => ({...z, meeting: run[z.room_id] || null, kind: "team"}));
  const sm = d.running.filter((m) => m.kind === "strategy");
  const s = sm[sm.length - 1] || null;
  zones.push({room_id: s ? s.room_id : null, kind: "strategy", meeting: s,
    title: s ? `매매법 방 · ${s.title}` : "매매법 방 36개 · 공용 회의실",
    members: s ? s.participants : ["spec_*", ...d.strategy_members], strat: s ? s.strategy : null});
  return zones;
}
// where each staff member of a zone stands: at the table when in this zone's meeting, else at the desk;
// busy: in a meeting in another room right now (drawn faded at the desk)
function ofPlaces(z, busy) {
  const out = [];
  const m = z.meeting;
  const at = m ? m.participants : [];
  const desk = z.members.filter((r) => !at.includes(r));
  const nd = Math.max(desk.length, 1);
  // with a meeting on, the ones not in it sit at the corner desks (the middle stays free for the thinking bubble)
  const CORNER = [11, 89, 23, 77, 35, 65];
  desk.forEach((r, i) => out.push({role: r, x: m ? CORNER[i % CORNER.length] : desk.length === 1 ? 50 : 12 + (76 * i) / (nd - 1 || 1),
    y: OF_DESK_Y, desk: true, away: busy.has(r) && !at.includes(r)}));
  at.forEach((r, i) => {
    const s = OF_SEATS[i % OF_SEATS.length], ring = Math.floor(i / OF_SEATS.length);
    out.push({role: r, x: OF_TABLE.x + s[0] * (27 + ring * 6), y: OF_TABLE.y + s[1] * 16, desk: false});
  });
  return out;
}
function ofPerson(z, p) {
  const m = z.meeting, role = p.role;
  const speaking = m && !p.desk && m.last_role === role;
  const thinking = m && !p.desk && m.next_role === role;
  const label = role === "spec_*" ? "전담 ×36" : ofShort(role);
  const name = role === "spec_*" ? "매매법마다 한 명씩 있는 전담 직원(36명)" : ofRole(role).name;
  const h = role === "spec_*" ? OF_TEAM_HUE.specialist : ofHue(role);
  const spec = role === "spec_*" || ofRole(role).team === "specialist";
  const cls = ["of-p", spec ? "spec" : "", speaking ? "talk" : "", thinking ? "think" : "", p.away ? "away" : "", p.desk ? "sit" : "meet"]
    .filter(Boolean).join(" ");
  const tip = name + (p.away ? " · 다른 방 회의 중" : speaking ? " · 방금 말함" : thinking ? " · 다음 차례" : "");
  return `<div class="${cls}" data-k="${esc(role)}" style="left:${p.x}%;top:${p.y}%;--h:${h}" title="${esc(tip)}">
    ${thinking ? '<span class="of-th">💭 생각 중</span>' : speaking ? '<span class="of-sp">💬</span>' : ""}
    ${p.desk ? '<i class="of-desk"></i>' : ""}${ofFigure(spec)}<span class="of-n">${esc(label)}</span></div>`;
}
function ofBubble(z) {
  const m = z.meeting;
  if (!m) return "";
  const who = m.last_role, t = who ? m.lines[who] : null;
  const places = ofPlaces(z, new Set());
  const at = (r) => { const p = places.find((q) => q.role === r); return p ? p.x : 50; };
  if (t && t.line) {
    return `<div class="of-say" style="--tx:${Math.min(Math.max(at(who), 8), 92)}%"><b>${esc(ofRole(who).label ? ofRole(who).label + " 전담" : ofRole(who).name)}</b>
      <span class="muted">${esc(OF_KIND_KO[t.kind] || "")} · ${esc(hm(t.ts))}</span><div class="of-l">${esc(t.line)}</div></div>`;
  }
  if (m.code && m.code.line) return `<div class="of-say code" style="--tx:50%"><b>⚙ 코드</b> <span class="muted">${esc(hm(m.code.ts))}</span><div class="of-l">${esc(m.code.line)}</div></div>`;
  return `<div class="of-say wait" style="--tx:50%">회의를 열었습니다. 첫 발언이 끝나면 여기에 나옵니다.</div>`;
}
function ofZone(z, d, busy, i) {
  const m = z.meeting;
  const n = z.kind === "strategy" ? Object.entries(d.today.by_room || {}).filter(([k]) => k.startsWith("strat:")).reduce((s, [, v]) => s + v, 0)
    : (d.today.by_room || {})[z.room_id] || 0;
  const people = ofPlaces(z, busy).map((p) => ofPerson(z, p)).join("");
  let foot = "";
  if (!m && z.kind === "strategy") {
    foot = d.latest_strategy.length ? `<div class="of-latest">${d.latest_strategy.map((r) =>
      `<button class="of-chip" data-room="${esc(r.room_id)}">${esc(r.title)} <span class="muted">${esc(hm(r.ended_ts || r.started_ts))} ${esc(r.trigger_ko)}</span></button>`).join("")}</div>`
      : '<div class="of-latest muted">아직 매매법 방 회의가 없습니다</div>';
  }
  return `<div class="of-z${m ? " live" : ""}${z.kind === "strategy" ? " of-sz" : ""}" data-zi="${i}"${z.room_id ? ` data-room="${esc(z.room_id)}"` : ""}>
    <div class="of-zh"><b>${esc(z.title)}</b><span class="grow"></span>${m ? `<span class="pill live">${esc(m.trigger_ko)}</span>` : ""}
      <span class="muted">오늘 ${n}회</span></div>
    <div class="of-floor"><i class="of-tbl"></i>${people}</div>${ofBubble(z)}${foot}</div>`;
}

// ------------------------------------------------------------ the cards under the floor
function ofTurns(m) {
  const rows = m.turns.map((t) => `<li><span class="of-dot" style="--h:${ofHue(t.role)}"></span><b>${esc(ofRole(t.role).name)}</b>
    <span class="muted">${esc(OF_KIND_KO[t.kind] || "")} · ${esc(hm(t.ts))}</span><div>${esc(t.line)}</div></li>`).join("");
  const next = m.next_role ? `<li class="of-next"><span class="of-dot" style="--h:${ofHue(m.next_role)}"></span><b>${esc(ofRole(m.next_role).name)}</b>
    <span class="muted">다음 차례</span><div>💭 생각 중</div></li>` : "";
  const code = m.code && m.code.line ? `<li class="of-code"><b>⚙ 코드</b> <span class="muted">${esc(hm(m.code.ts))}</span><div>${esc(m.code.line)}</div></li>` : "";
  return rows || next || code ? `<ol class="of-turns">${rows}${code}${next}</ol>` : '<p class="muted">아직 발언이 없습니다(첫 AI 차례가 끝나면 나옵니다).</p>';
}
function ofNow(d) {
  if (!d.running.length) return "";
  return d.running.map((m) => `<div class="card of-mt"><div class="ph"><span class="t"><span class="up">●</span> 지금 회의 · ${esc(m.title)}</span><span class="grow"></span>
      <button class="mini" data-room="${esc(m.room_id)}">방 열기</button></div>
    <div class="body"><div class="dim">${esc(m.trigger_ko)} · ${esc(hm(m.started_ts))} 시작${m.why ? " · " + esc(m.why) : ""}</div>${ofTurns(m)}</div></div>`).join("");
}
function ofRecent(d) {
  const rows = d.recent.map((r) => `<li class="click" data-room="${esc(r.room_id)}"><span class="mono muted">${esc(hm(r.ended_ts || r.started_ts))}</span>
      <b>${esc(r.title)}</b> <span class="muted">${esc(r.trigger_ko)} · ${esc(OF_STATUS_KO[r.status] || r.status)}</span>
      <div>${esc(r.decision || "(결정 줄 없음)")}</div>
      ${r.speakers.length ? `<div class="of-who">${r.speakers.map((s) => `<span class="of-dot" style="--h:${ofHue(s)}" title="${esc(ofRole(s).name)}"></span>`).join("")}
        <span class="muted">${r.speakers.map((s) => esc(ofShort(s))).join(" → ")}</span></div>` : ""}</li>`).join("");
  return `<div class="card"><div class="ph"><span class="t">오늘 끝난 회의 (최근 ${d.recent.length})</span></div>
    <div class="body">${rows ? `<ul class="of-rec">${rows}</ul>` : '<p class="muted">오늘(한국 0시 이후) 끝난 회의가 아직 없습니다.</p>'}</div></div>`;
}
function ofHead(d) {
  const nx = d.schedule && d.schedule.next;
  const next = nx ? `다음 정기 회의 ${nx.tomorrow ? "내일 " : ""}${esc(nx.hhmm)} · ${esc(nx.trigger_ko)} (${esc(nx.where)})` : "정해진 시각의 회의 없음";
  const line = d.running.length ? `<b class="up">● 지금 회의 ${d.running.length}개</b> · ${d.running.map((m) => esc(m.title) + " " + esc(m.trigger_ko)).join(", ")}`
    : `<b>지금 회의 없음</b> · ${next}`;
  const slots = (d.schedule && d.schedule.slots || []).map((s) => `${esc(s.hhmm)} ${esc(s.trigger_ko)}`).join(" · ");
  return `<div class="of-top"><div class="of-line">${line}</div>
    <div class="of-tiles"><span><b>${esc(d.today.meetings)}</b> 오늘 회의</span><span><b>${esc(d.today.ai_calls)}</b> 오늘 AI 호출</span>
      <span><b>${esc(d.running.length)}</b> 지금 회의</span></div>
    ${slots ? `<div class="of-slots muted">정기 회의(한국 시간): ${slots}. 손실·사고·두 분 글·연구 회의는 정해진 시각 없이 열립니다.</div>` : ""}</div>`;
}
const OF_NOTE = "말풍선은 회의 기록에 저장된 실제 마지막 발언(첫 문장)입니다. 직원 한 명의 AI 차례가 끝나 기록될 때마다 바뀌며, " +
  "실시간 타이핑이 아닙니다. '💭 생각 중'은 회의 순서상 다음 차례인 직원이고, 순서가 앞 사람의 답에 달려 있으면 표시하지 않습니다. " +
  "직원을 누르면 그 방 대화가 열립니다.";

function renderOffice() {
  const el = $("of-body");
  if (!el) return;
  const d = of.d;
  if (!d) { el.innerHTML = `<p class="empty">${of.err ? "회의실을 불러오지 못했습니다. 잠시 뒤 다시 시도합니다." : "불러오는 중…"}</p>`; return; }
  const busy = new Set();
  for (const m of d.running) for (const r of m.participants) busy.add(r);
  const zones = ofZones(d);
  const prev = {};
  el.querySelectorAll(".of-p[data-k]").forEach((p) => {
    const z = p.closest(".of-z");
    prev[(z ? z.dataset.zi : "") + "|" + p.dataset.k] = [p.style.left, p.style.top];
  });
  el.innerHTML = `${ofHead(d)}
    ${!d.ready ? '<p class="hint">에이전트 기록(agents3.db)이 아직 없습니다. 에이전트가 첫 회의를 하면 여기에 나옵니다.</p>' : ""}
    ${d.error ? `<p class="of-warn">${esc(d.error)}</p>` : ""}
    <div class="of-wrap"><div class="of-office">${zones.map((z, i) => ofZone(z, d, busy, i)).join("")}</div>
      <div class="of-side">${ofNow(d)}${ofRecent(d)}<p class="of-note muted">${esc(OF_NOTE)}</p></div></div>`;
  // staff who changed place walk there (from where they stood on the last draw)
  el.querySelectorAll(".of-p[data-k]").forEach((p) => {
    const z = p.closest(".of-z");
    const was = prev[(z ? z.dataset.zi : "") + "|" + p.dataset.k];
    if (!was || (was[0] === p.style.left && was[1] === p.style.top)) return;
    const to = [p.style.left, p.style.top];
    p.style.transition = "none"; p.style.left = was[0]; p.style.top = was[1];
    void p.offsetWidth;
    p.style.transition = ""; p.classList.add("walk");
    p.style.left = to[0]; p.style.top = to[1];
    setTimeout(() => p.classList.remove("walk"), 1400);
  });
  el.querySelectorAll("[data-room]").forEach((b) => b.onclick = (e) => { e.stopPropagation(); ofOpen(b.dataset.room); });
}

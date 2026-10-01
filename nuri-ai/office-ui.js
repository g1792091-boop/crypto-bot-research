// GH Nano 사무실 대시보드: 픽셀아트 사무실 + 회의 기록 패널
// 직원들이 자리에서 일하다가 회의가 열리면 회의실로 걸어가 말풍선으로 대화하고, 오른쪽 패널에 회의록이 쌓인다.
import { TEAMS, AGENTS, AGENDA, agentById, teamById, ask, stopMeeting, onOffice, loadLog, officeCfg, setOffice, officeUsage, officeState,
  startAutopilot, nextAutoIn, runAgendaNow, assignModels, clearLog, work, chatter, startChatter, setOfficeVisible, seen, nextChatIn, isChatting,
  startCycle, nextCycleIn, cycle, cycleState, computerOn } from "./office.js";
import { shortModel, provUse, settings, LAUNCHER } from "./engine.js";
import { BUILTIN_SKILLS } from "./agent.js";

/* ============ 사무실 배치 (가로 1000 × 세로 700 좌표) ============ */
const ZONES = {
  hq:    {x: 20,  y: 20,  w: 300, h: 190, label: "총괄실"},
  coin:  {x: 340, y: 20,  w: 290, h: 190, label: "코인팀"},
  stock: {x: 20,  y: 230, w: 300, h: 210, label: "주식팀"},
  fut:   {x: 340, y: 230, w: 290, h: 210, label: "선물·매크로팀"},
  arch:  {x: 20,  y: 460, w: 300, h: 220, label: "건축·부동산팀"},
  lab:   {x: 340, y: 460, w: 290, h: 220, label: "리서치·개발팀"},
  strat: {x: 650, y: 20,  w: 330, h: 190, label: "전략·리스크팀"},
  lounge:{x: 650, y: 230, w: 330, h: 170, label: "라운지"},
  meet:  {x: 650, y: 420, w: 330, h: 260, label: "회의실"},
  quant: {x: 1000, y: 20,  w: 370, h: 230, label: "퀀트 연구소"},
  data:  {x: 1000, y: 270, w: 370, h: 190, label: "데이터·SNS팀"},
  board: {x: 1000, y: 480, w: 370, h: 200, label: "모의투자 현황판"}
};
const W = 1390, H = 700;
const TEAM_COLOR = {hq: "#7c6cf0", coin: "#f0a020", stock: "#2f8fd8", fut: "#16a39a", arch: "#d9822b", strat: "#d0465a", lab: "#8a63d2", quant: "#2e9e6b", data: "#c2185b"};
// 직원 자리: 팀 구역 안에 책상을 나란히 놓고 그 앞 의자
const HOME = {}, DESKS = [];
for (const t of TEAMS){
  const z = ZONES[t.id], mem = AGENTS.filter(a => a.team === t.id);
  mem.forEach((a, i) => {
    const cx = t.id === "hq" ? z.x + z.w * 0.8 : z.x + z.w * (i + 1) / (mem.length + 1);
    DESKS.push({x: cx, y: z.y + 62, team: t.id});
    HOME[a.id] = {x: cx, y: z.y + 128};
  });
}
const SEATS = [0, 1, 2, 3].map(k => ({x: 702 + k * 76, y: 528})).concat([0, 1, 2, 3].map(k => ({x: 702 + k * 76, y: 640})));
const LOUNGE = [{x: 700, y: 330, say: "커피 한 잔 하고 올게요"}, {x: 790, y: 360, say: "잠깐 쉬는 중"}, {x: 900, y: 330, say: "차트 다시 보는 중"}, {x: 840, y: 300, say: "뉴스 훑어보는 중"}];
const IDLE = ["시세 확인 중", "자료 정리 중", "다음 회의 준비 중", "메모하는 중", "차트 보는 중", "보고서 쓰는 중"];

/* ============ 픽셀 캐릭터 ============ */
const LONG = new Set(["coin_spot", "us", "kfut", "arch", "devil", "research", "aide", "qb", "sns"]);
function sprite(a){
  const [hair, shirt] = a.look, skin = "#f2c8a0", pants = "#3b3f58", shoe = "#2a2a2a", eye = "#222";
  const long = LONG.has(a.id);
  const G = [
    "...HHHHHH...",
    "..HHHHHHHH..",
    "..HHSSSSHH..",
    long ? ".HHSESSESHH." : "..HSESSESH..",
    long ? ".HHSSSSSSHH." : "...SSSSSS...",
    long ? ".HH.SSSS.HH." : "....SSSS....",
    "..TTTTTTTT..",
    ".TTTTTTTTTT.",
    ".STTTTTTTTS.",
    ".STTTTTTTTS.",
    "..TTTTTTTT..",
    "..PPPPPPPP..",
    "..PPP..PPP..",
    "..PPP..PPP..",
    "..BBB..BBB.."];
  const C = {H: hair, S: skin, E: eye, T: shirt, P: pants, B: shoe};
  let r = "";
  G.forEach((row, y) => { let x = 0; while (x < row.length){ const ch = row[x]; let n = 1; while (row[x + n] === ch) n++; if (C[ch]) r += `<rect x="${x}" y="${y}" width="${n}" height="1" fill="${C[ch]}"/>`; x += n; } });
  return `<svg viewBox="0 0 12 15" shape-rendering="crispEdges" aria-hidden="true">${r}</svg>`;
}

let ctx = null, root = null, chan = "all", unsub = null, idleT = 0, statusT = 0, seatOf = {}, away = {};
const pos = {};
export function openOffice(opts){
  ctx = opts;
  if (!root){ root = build(); document.body.appendChild(root); }
  root.hidden = false; document.body.classList.add("office-open");
  fit(); loadLog().then(renderLog);
  startAutopilot(); try { localStorage.setItem("officeUsed", "1"); } catch(e){}
  setOfficeVisible(true); startChatter(); startCycle(); refreshBoard();
  // 사무실을 열면 30초 안에 첫 수다가 시작되게
  if (nextChatIn() === 0 || nextChatIn() > 30e3) localStorage.setItem("officeLastChat", String(Date.now() - officeCfg().chatEvery * 60e3 + 30e3));
  if (!unsub) unsub = onOffice(onEvent);
  clearInterval(idleT); idleT = setInterval(idle, 7000);
  clearInterval(statusT); statusT = setInterval(renderStatus, 5000); renderStatus();
  const s = officeState(); if (s.running) onEvent({kind: "start", meeting: s.running});
  setTimeout(() => root.querySelector("#ofIn")?.focus(), 50);
}
export function closeOffice(){
  if (!root) return; root.hidden = true; document.body.classList.remove("office-open"); clearInterval(idleT); clearInterval(statusT); setOfficeVisible(false);
  if (location.hash === "#office") history.replaceState(null, "", location.pathname + location.search);
}
export const officeOpen = () => root && !root.hidden;

function build(){
  const el = document.createElement("section");
  el.className = "office"; el.id = "office"; el.setAttribute("aria-label", "AI 팀 사무실");
  const zones = Object.entries(ZONES).map(([id, z]) => `<div class="of-zone z-${id}" style="left:${z.x}px;top:${z.y}px;width:${z.w}px;height:${z.h}px;${TEAM_COLOR[id] ? `--tc:${TEAM_COLOR[id]}` : ""}"><span class="of-zl">${z.label}</span></div>`).join("");
  const desks = DESKS.map(d => `<div class="of-desk" style="left:${d.x - 34}px;top:${d.y - 20}px"><i class="mon"></i><i class="mug"></i></div><div class="of-chair" style="left:${d.x - 11}px;top:${d.y + 22}px"></div>`).join("");
  const props = `
    <div class="of-board" style="left:34px;top:34px"><b>오늘의 안건</b><span id="ofBoard">자동 회의 대기 중</span></div>
    <div class="of-plant" style="left:296px;top:180px"></div><div class="of-plant" style="left:608px;top:410px"></div><div class="of-plant" style="left:296px;top:650px"></div>
    <div class="of-coffee" style="left:668px;top:250px"></div><div class="of-fridge" style="left:712px;top:246px"></div>
    <div class="of-sofa" style="left:760px;top:350px"></div><div class="of-lamp" style="left:950px;top:340px"></div>
    <div class="of-table" style="left:690px;top:556px"></div>
    ${SEATS.map(s => `<div class="of-seat" style="left:${s.x - 11}px;top:${s.y - 4}px"></div>`).join("")}
    <div class="of-tv" style="left:740px;top:432px"><i></i></div>
    <div class="of-shelf" style="left:668px;top:40px"></div>
    <div class="of-pboard" style="left:1016px;top:500px"><b>모의투자 현황판 <span id="ofPTot"></span></b><div id="ofPList">아직 운용 중인 전략이 없습니다</div></div>`;
  const agents = AGENTS.map(a => `<div class="of-ag" data-ag="${a.id}" tabindex="0" role="button" aria-label="${a.name} ${a.title}"><div class="of-bub" hidden></div><div class="of-spr">${sprite(a)}</div><div class="of-nm">${a.name}</div></div>`).join("");
  const agendaOpts = AGENDA.map(a => `<button data-agenda="${a.id}">#${a.title}</button>`).join("");
  el.innerHTML = `
  <div class="of-top">
    <span class="of-dots"><i></i><i></i><i></i></span>
    <span class="of-path">~/gh-nano/우리-사무실 · <b id="ofMode">대기</b></span>
    <span class="of-sp"></span>
    <label class="of-tg" title="사용자가 아무것도 하지 않아도 정해진 간격과 급변동 때 스스로 회의합니다"><input type="checkbox" id="ofAuto"> 자동 회의</label>
    <label class="of-tg" title="3분마다 사람처럼 한 가지 일(매매법 연구·SNS·경제 리서치·모의투자·컴퓨터 작업)을 스스로 합니다"><input type="checkbox" id="ofCycle"> 3분 주기 업무</label>
    <label class="of-tg" title="직원들이 수시로 본 차트·뉴스를 두고 잡담합니다 (한 번에 AI 1번)"><input type="checkbox" id="ofChat"> 수시 대화</label>
    <label class="of-tg" title="태민이 문서/GHNano 사무실 폴더 안에서만 파일을 만들고 스크립트를 실행합니다 (GHNano.exe에서만)"><input type="checkbox" id="ofComp"> 컴퓨터 작업</label>
    <label class="of-tg" title="Claude API 키가 있으면 팀장·전략·검증·리스크 자리에 Claude를 하루 한도 안에서 씁니다"><input type="checkbox" id="ofClaude"> Claude</label>
    <button class="of-btn" id="ofNow" title="다음 주기를 기다리지 않고 지금 한 가지 일을 시킵니다">지금 일 시키기</button>
    <select id="ofEvery" title="자동 회의 간격"><option value="15">15분마다</option><option value="30">30분마다</option><option value="60">1시간마다</option><option value="180">3시간마다</option></select>
    <span class="of-pick"><button class="of-btn" id="ofAgendaBtn">안건 열기 ▾</button><div class="of-menu" id="ofAgenda" hidden>${agendaOpts}</div></span>
    <button class="of-btn" id="ofTeam">팀 구성</button>
    <button class="of-btn" id="ofStop" hidden>회의 멈추기</button>
    <span class="of-rec" id="ofRec"><i></i> 녹화</span>
    <button class="of-x" id="ofClose" title="채팅으로 돌아가기" aria-label="닫기">✕</button>
  </div>
  <div class="of-body">
    <div class="of-stage" id="ofStage"><div class="of-floor" id="ofFloor">${zones}${desks}${props}${agents}</div></div>
    <aside class="of-side">
      <div class="of-head">
        <div class="of-h1"><i class="of-led" id="ofLed"></i><b id="ofTitle">대기 중</b><span class="of-sp"></span><span class="of-recl" id="ofRecL">녹화 중</span></div>
        <div class="of-h2" id="ofStatus"></div>
        <div class="of-chans" id="ofChans"><button data-ch="all" aria-pressed="true">#전체</button><button data-ch="work" aria-pressed="false" style="--tc:#c9a227">#업무(차트·뉴스)</button>${TEAMS.map(t => `<button data-ch="${t.id}" aria-pressed="false" style="--tc:${TEAM_COLOR[t.id]}">#${t.name}</button>`).join("")}</div>
      </div>
      <div class="of-log" id="ofLog" aria-live="polite"></div>
      <form class="of-form" id="ofForm"><input id="ofIn" placeholder="사무실에 메시지 보내기 (예: 비트코인 지금 롱 어때? / 60평 대지에 3층 주택 설계)" autocomplete="off"><button type="submit" aria-label="보내기">↵</button></form>
      <div class="of-foot" id="ofFoot"></div>
    </aside>
  </div>
  <div class="of-card" id="ofCard" hidden></div>`;
  // 처음 자리
  for (const a of AGENTS) pos[a.id] = {...HOME[a.id]};
  requestAnimationFrame(() => AGENTS.forEach(a => place(a.id, HOME[a.id], true)));
  wire(el);
  if ("ResizeObserver" in window) new ResizeObserver(fit).observe(el.querySelector("#ofStage")); else window.addEventListener("resize", fit);
  return el;
}
function fit(){
  if (!root) return;
  const st = root.querySelector("#ofStage"), fl = root.querySelector("#ofFloor");
  const s = Math.min(st.clientWidth / W, st.clientHeight / H) || 1;
  fl.style.transform = `scale(${s})`;
  fl.style.left = Math.max(0, (st.clientWidth - W * s) / 2) + "px"; fl.style.top = Math.max(0, (st.clientHeight - H * s) / 2) + "px";
}
const $o = s => root.querySelector(s);
function wire(el){
  const c = officeCfg();
  el.querySelector("#ofAuto").checked = !!c.auto;
  el.querySelector("#ofEvery").value = String(c.every);
  el.querySelector("#ofAuto").onchange = e => { setOffice({auto: e.target.checked}); ctx.toast(e.target.checked ? "자동 회의를 켰습니다. 팀이 스스로 시장을 점검합니다" : "자동 회의를 껐습니다"); renderStatus(); };
  el.querySelector("#ofEvery").onchange = e => { setOffice({every: +e.target.value}); renderStatus(); };
  el.querySelector("#ofCycle").onchange = e => { setOffice({cycle: e.target.checked}); renderStatus(); };
  el.querySelector("#ofComp").onchange = e => { setOffice({computer: e.target.checked}); if (e.target.checked && !LAUNCHER.on) ctx.toast("컴퓨터 작업은 GHNano.exe로 실행했을 때만 됩니다"); renderStatus(); };
  el.querySelector("#ofClaude").onchange = e => { setOffice({claude: e.target.checked}); if (e.target.checked && !settings.keys.anthropic) ctx.toast("설정 → AI 두뇌에 Claude API 키(sk-ant-…)를 넣으면 씁니다"); renderStatus(); };
  el.querySelector("#ofNow").onclick = async () => { ctx.toast("지금 한 가지 일을 시킵니다"); const ok = await cycle(true); if (!ok) ctx.toast("지금은 다른 일을 하는 중이거나 연결된 AI가 없습니다"); };
  el.querySelector("#ofChat").checked = c.chat !== false;
  el.querySelector("#ofChat").onchange = e => { setOffice({chat: e.target.checked}); if (e.target.checked){ localStorage.setItem("officeLastChat", "0"); } renderStatus(); };
  el.querySelector("#ofClose").onclick = closeOffice;
  el.querySelector("#ofStop").onclick = () => { stopMeeting(); ctx.toast("회의를 멈췄습니다"); };
  el.querySelector("#ofAgendaBtn").onclick = e => { e.stopPropagation(); const m = $o("#ofAgenda"); m.hidden = !m.hidden; };
  el.addEventListener("click", e => {
    const ag = e.target.closest("[data-agenda]");
    if (ag){ $o("#ofAgenda").hidden = true; runAgendaNow(ag.dataset.agenda); ctx.toast("회의를 엽니다"); return; }
    if (!e.target.closest(".of-pick")) $o("#ofAgenda").hidden = true;
    const ch = e.target.closest("[data-ch]");
    if (ch){ chan = ch.dataset.ch; el.querySelectorAll("[data-ch]").forEach(b => b.setAttribute("aria-pressed", b === ch)); renderLog(); $o("#ofIn").placeholder = !teamById(chan) || chan === "hq" ? "사무실에 메시지 보내기 (팀장이 담당자를 부릅니다)" : `#${teamById(chan).name}에 메시지 보내기`; return; }
    const a = e.target.closest("[data-ag]");
    if (a){ showCard(a.dataset.ag); return; }
    if (e.target.closest("#ofTeam")){ showTeam(); return; }
    if (e.target.closest("[data-more]")){ const m = e.target.closest(".of-msg"); m.classList.toggle("open"); return; }
    if (e.target.closest("#ofClear")){ clearLog(); return; }
    if (e.target.closest(".of-card .of-x")){ $o("#ofCard").hidden = true; return; }
    if (!e.target.closest(".of-card")) $o("#ofCard").hidden = true;
  });
  el.addEventListener("keydown", e => { if (e.key === "Escape"){ if (!$o("#ofCard").hidden) $o("#ofCard").hidden = true; else closeOffice(); } if ((e.key === "Enter" || e.key === " ") && e.target.matches("[data-ag]")){ e.preventDefault(); showCard(e.target.dataset.ag); } });
  el.querySelector("#ofForm").onsubmit = e => {
    e.preventDefault();
    const inp = $o("#ofIn"), text = inp.value.trim(); if (!text) return;
    inp.value = "";
    ask(text, {room: teamById(chan) ? chan : "hq"}).then(r => { if (r?.error) ctx.toast(r.error); });
  };
}
/* ============ 캐릭터 움직임 ============ */
function place(id, p, instant){
  const el = root.querySelector(`[data-ag="${id}"]`); if (!el) return;
  const from = pos[id] || p, dist = Math.hypot(p.x - from.x, p.y - from.y);
  el.style.transitionDuration = instant ? "0s" : Math.min(2.6, 0.3 + dist / 170) + "s";
  el.classList.toggle("flip", p.x < from.x - 2);
  if (!instant && dist > 4){ el.classList.add("walk"); clearTimeout(el._w); el._w = setTimeout(() => el.classList.remove("walk"), Math.min(2600, 300 + dist / 0.17)); }
  el.style.left = p.x + "px"; el.style.top = p.y + "px"; el.style.zIndex = Math.round(p.y);
  el.classList.toggle("edge-r", p.x > W - 140); el.classList.toggle("edge-l", p.x < 140);
  pos[id] = {x: p.x, y: p.y};
}
function bubble(id, text, ms){
  const el = root?.querySelector(`[data-ag="${id}"] .of-bub`); if (!el) return;
  clearTimeout(el._t);
  if (!text){ el.hidden = true; return; }
  el.textContent = text; el.hidden = false;
  if (ms) el._t = setTimeout(() => { el.hidden = true; }, ms);
}
const tail = (s, n = 120) => { const t = String(s).replace(/[#*_`>|]/g, "").replace(/\s+/g, " ").trim(); return t.length > n ? "…" + t.slice(-n) : t; };
const head = (s, n = 110) => { const t = String(s).replace(/[#*_`>|]/g, "").replace(/\s+/g, " ").trim(); const first = t.split(/(?<=[.!?。다요])\s/)[0]; return (first.length > n ? first.slice(0, n) + "…" : first) || t.slice(0, n); };
let huddle = new Set();
async function idle(){
  if (!root || root.hidden) return;
  const busy = new Set([...Object.keys(seatOf), ...huddle]);
  for (const id of Object.keys(away)) if (Date.now() > away[id]){ delete away[id]; if (!busy.has(id)) place(id, HOME[id]); }
  const free = AGENTS.filter(a => !busy.has(a.id) && !away[a.id]);
  if (!free.length) return;
  const a = free[Math.floor(Math.random() * free.length)];
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!still && Math.random() < 0.18){
    const spot = LOUNGE[Math.floor(Math.random() * LOUNGE.length)];
    place(a.id, {x: spot.x + (Math.random() * 30 - 15), y: spot.y}); bubble(a.id, "☕ " + spot.say, 3500); away[a.id] = Date.now() + 14000;
    return;
  }
  // 실제로 차트·뉴스를 확인하고 본 것을 말풍선으로
  bubble(a.id, "🔎 확인하는 중…", 0);
  const o = await work(a.id).catch(() => null);
  if (seatOf[a.id] !== undefined || huddle.has(a.id)) return;
  bubble(a.id, o ? `${o.icon} ${o.text}`.trim() : "", o ? 7000 : 1);
}
/* ============ 회의 이벤트 ============ */
let speaking = null;
function onEvent(ev){
  if (!root) return;
  const m = ev.meeting;
  if (ev.kind === "log"){ if (inChan(ev.entry)) appendEntry(ev.entry); return; }
  if (ev.kind === "cleared"){ renderLog(); return; }
  if (ev.kind === "cfg" || ev.kind === "usage"){ renderStatus(); return; }
  if (ev.kind === "start"){
    seatOf = {};
    [...new Set(m.order)].forEach((id, i) => { seatOf[id] = i; delete away[id]; setTimeout(() => { place(id, SEATS[i % SEATS.length]); bubble(id, i ? "회의 들어갑니다" : "회의 시작할게요", 2500); }, i * 250); });
    $o("#ofBoard").textContent = "#" + m.name;
  }
  if (ev.kind === "join"){ const i = Object.keys(seatOf).length; seatOf[ev.agent.id] = i; place(ev.agent.id, SEATS[i % SEATS.length]); bubble(ev.agent.id, "부르셨어요? 갑니다", 2500); }
  if (ev.kind === "turn"){ clearBubbles(ev.agent.id); speaking = ev.agent.id; if (!(ev.agent.id in seatOf)){ const i = Object.keys(seatOf).length; seatOf[ev.agent.id] = i; place(ev.agent.id, SEATS[i % SEATS.length]); } bubble(ev.agent.id, "💭 생각 정리하는 중…", 0); highlight(ev.agent.id); }
  if (ev.kind === "tool" || ev.kind === "delta"){ bubble(ev.agent.id, liveBubble(ev.entry), 0); updateEntry(ev.entry); }
  if (ev.kind === "huddle"){
    clearBubbles(); const host = HOME[ev.host] || pos[ev.host];
    ev.ids.forEach((id, i) => { huddle.add(id); delete away[id]; if (id !== ev.host) place(id, {x: host.x + (i % 2 ? 58 : -58) * Math.ceil(i / 2), y: host.y + 6}); else place(id, HOME[id]); });
  }
  if (ev.kind === "line"){ bubble(ev.agent.id, ev.entry.text.length > 150 ? ev.entry.text.slice(0, 150) + "…" : ev.entry.text, Math.min(9000, 2500 + ev.entry.text.length * 50)); highlight(ev.agent.id); setTimeout(() => highlight(null), 1800); }
  if (ev.kind === "huddle-end"){ ev.ids.forEach((id, i) => setTimeout(() => { huddle.delete(id); if (seatOf[id] === undefined) place(id, HOME[id]); }, 3000 + i * 300)); }
  if (ev.kind === "said"){ bubble(ev.agent.id, head(ev.entry.text), 6000); updateEntry(ev.entry); highlight(null); }
  if (ev.kind === "end"){
    const ids = Object.keys(seatOf); seatOf = {}; speaking = null; highlight(null);
    ids.forEach((id, i) => setTimeout(() => { bubble(id, ""); place(id, HOME[id]); }, 3500 + i * 200));
    $o("#ofBoard").textContent = "회의 끝 · 회의록은 오른쪽";
  }
  if (ev.kind === "cycle"){ $o("#ofBoard").textContent = "지금: " + (ev.label || "업무"); }
  if (ev.kind === "busy" || ev.kind === "bubble"){ if (seatOf[ev.agent.id] === undefined && !huddle.has(ev.agent.id)){ delete away[ev.agent.id]; place(ev.agent.id, HOME[ev.agent.id]); } bubble(ev.agent.id, ev.text, ev.kind === "busy" ? 0 : 7000); }
  if (ev.kind === "solo"){ bubble(ev.agent.id, "💭 생각 정리하는 중…", 0); highlight(ev.agent.id); }
  if (ev.kind === "trade"){ bubble(ev.agent.id, ev.text.length > 140 ? ev.text.slice(0, 140) + "…" : ev.text, 9000); refreshBoard(); }
  if (ev.kind === "paper") refreshBoard();
  if (ev.kind === "alert"){ ctx.toast(`팀 회의 결과 · #${m.name}: ${head(ev.text, 60)}`); if (document.hidden && "Notification" in window && Notification.permission === "granted") new Notification("GH Nano 팀 회의 · #" + m.name, {body: head(ev.text, 120)}); }
  renderStatus();
}
const TOOL_ICON = {market_analyze: "📈", market_quote: "💹", market_news: "📰", web_search: "🔎", web_fetch: "📄", econ_calendar: "🗓", calculate: "🧮", backtest: "🧪", nv_skill_search: "🟩", nv_skill_read: "🟩"};
// 말풍선: 말하는 중이면 말, 도구를 쓰는 중이면 무엇을 보는지, 아니면 속마음
function liveBubble(e){
  const st = e.steps?.at(-1);
  if (e.text) return "🗣 " + tail(e.text, 140);
  if (st && st.status === "running") return `${TOOL_ICON[st.name] || "🔧"} ${st.act} 하는 중…`;
  if (st && st.status === "done") return `${TOOL_ICON[st.name] || "✅"} ${st.act}${st.summary ? " → " + st.summary : ""}${st.sources?.[0] ? " · " + st.sources[0].title : ""}`.slice(0, 170);
  if (e.think) return "💭 " + tail(e.think, 130);
  return "💭 생각 정리하는 중…";
}
function clearBubbles(except){ root.querySelectorAll(".of-ag").forEach(el => { if (el.dataset.ag !== except) bubble(el.dataset.ag, ""); }); }
async function refreshBoard(){
  if (!root) return;
  const P = await import("./paper.js"), b = await P.loadBook();
  const act = b.strategies.filter(x => x.status === "active");
  const list = $o("#ofPList"), tot = $o("#ofPTot");
  if (!act.length){ list.textContent = "아직 운용 중인 전략이 없습니다 · 퀀트 연구소가 검증을 통과시키면 여기서 가상 운용합니다"; tot.textContent = ""; return; }
  const pct = s => (P.equityOf(s) / 10000 - 1) * 100;
  const sum = act.reduce((a, s) => a + P.equityOf(s), 0) / (act.length * 10000) * 100 - 100;
  tot.innerHTML = `<i class="${sum >= 0 ? "up" : "dn"}">${sum >= 0 ? "+" : ""}${sum.toFixed(2)}%</i>`;
  list.innerHTML = act.sort((x, y) => pct(y) - pct(x)).slice(0, 6).map(s => `<div><span>${ctx.esc(s.name).slice(0, 18)}</span><small>${ctx.esc(s.market.replace("USDT", ""))} ${s.pos ? (s.pos.side === "long" ? "롱" : "숏") : "대기"}</small><i class="${pct(s) >= 0 ? "up" : "dn"}">${pct(s) >= 0 ? "+" : ""}${pct(s).toFixed(2)}%</i></div>`).join("");
}
function highlight(id){ root.querySelectorAll(".of-ag.talk").forEach(e => e.classList.remove("talk")); if (id) root.querySelector(`[data-ag="${id}"]`)?.classList.add("talk"); }
function renderStatus(){
  if (!root) return;
  const s = officeState(), c = officeCfg(), u = officeUsage();
  const m = s.running;
  $o("#ofLed").className = "of-led" + (m ? " on" : "");
  $o("#ofTitle").textContent = m ? `회의 · #${m.name}` : "대기 중";
  $o("#ofRec").classList.toggle("on", !!m); $o("#ofRecL").textContent = m ? "녹화 중" : "기록됨";
  $o("#ofMode").textContent = m ? "회의 중" : c.auto ? "자동 운영" : "대기";
  $o("#ofStop").hidden = !m; $o("#ofAuto").checked = !!c.auto; $o("#ofEvery").value = String(c.every); $o("#ofChat").checked = c.chat !== false; $o("#ofCycle").checked = c.cycle !== false; $o("#ofComp").checked = c.computer !== false; $o("#ofClaude").checked = c.claude !== false;
  const next = nextAutoIn();
  $o("#ofStatus").innerHTML = m ? `<b class="ok">진행 중</b> · ${m.done.length}/${m.order.length} 발언${s.queued ? ` · 대기 회의 ${s.queued}개` : ""}`
    : c.auto ? (u.auto >= c.dailyMax ? `오늘 자동 회의 ${c.dailyMax}번을 다 했습니다 · 메시지를 보내면 바로 회의합니다` : `다음 자동 회의 ${next > 60e3 ? Math.round(next / 60e3) + "분 뒤" : "곧"} · 급변동 감시 중`) : "자동 회의 꺼짐 · 메시지를 보내면 바로 회의합니다";
  const nc = nextChatIn();
  const nx = nextCycleIn(), cs = cycleState(), cu = provUse().n.anthropic || 0, cap = (settings.provCap || {}).anthropic ?? 300;
  $o("#ofFoot").innerHTML = `${c.cycle !== false ? `3분 주기 ${cs.cycling ? "일하는 중" : `다음 ${nx > 60e3 ? Math.ceil(nx / 60e3) + "분" : "곧"}`} · ` : ""}${settings.keys.anthropic ? `Claude 오늘 ${cu}/${cap} · ` : ""}오늘 회의 ${u.meetings || 0}번 (자동 ${u.auto || 0}/${c.dailyMax}) · 수다 ${u.chats || 0}/${c.chatMax}${c.chat ? (isChatting() ? " (지금 대화 중)" : ` (다음 ${nc > 60e3 ? Math.round(nc / 60e3) + "분" : "곧"})`) : ""} · AI 호출 ${u.calls || 0}번 · <button id="ofClear" class="of-link">기록 지우기</button>`;
}
/* ============ 회의록 패널 ============ */
// #전체: 회의·수다·내 메시지 / #업무: 직원들이 본 차트·뉴스 / 팀 방: 그 팀의 모든 것
const inChan = e => chan === "all" ? e.kind !== "work" : chan === "work" ? e.kind === "work" : e.ch === chan;
async function renderLog(){
  const log = await loadLog(), box = $o("#ofLog");
  const list = log.filter(inChan).slice(-160);
  box.innerHTML = list.length ? "" : `<div class="of-empty"><b>아직 회의가 없습니다</b><p>아래에 무엇이든 보내면 팀장이 담당자를 불러 회의를 엽니다. 코인·코인 선물·해외주식·국내주식·해외선물·국내선물·건축·부동산·뉴스·코딩·일상 대화 모두 됩니다.</p><p>자동 회의를 켜 두면 팀이 정해진 간격과 급변동 때 스스로 회의합니다.</p></div>`;
  list.forEach(appendEntry);
}
const link = (url, label) => url ? `<a href="${ctx.esc(url)}" target="_blank" rel="noopener noreferrer">${ctx.esc(label)}</a>` : ctx.esc(label);
function stepsHTML(e){
  if (!e.steps?.length) return "";
  return `<ul class="of-steps">${e.steps.map(st => `<li class="${st.status}"><span>${TOOL_ICON[st.name] || "🔧"} ${ctx.esc(st.act || "")}</span>${st.status === "running" ? ` <em>하는 중…</em>` : st.status === "error" ? ` <em class="bad">실패: ${ctx.esc(st.err.slice(0, 60))}</em>` : st.summary ? ` <em>→ ${ctx.esc(st.summary)}</em>` : ""}${st.sources?.length ? `<div class="of-src">${st.sources.slice(0, 4).map(x => "📰 " + link(x.url, String(x.title || x.url).slice(0, 70))).join("<br>")}</div>` : ""}</li>`).join("")}</ul>`;
}
function entryHTML(e){
  if (e.kind === "divider") return `<div class="of-div${e.chat ? " chat" : ""}">— ${ctx.esc(e.text)} —</div>`;
  if (e.kind === "system") return `<div class="of-sys">${ctx.esc(e.text)}</div>`;
  const time = new Date(e.t).toLocaleTimeString("ko-KR", {hour: "2-digit", minute: "2-digit"});
  if (e.kind === "user") return `<div class="of-msg me"><div class="of-av me">나</div><div class="of-mb"><div class="of-who"><b>나</b><span>#${ctx.esc(teamById(e.ch)?.name || "")} · ${time}</span></div><div class="of-tx">${ctx.esc(e.text)}</div></div></div>`;
  const a = agentById(e.agent) || {name: "?", title: "", team: "hq", look: ["#999", "#999"]};
  if (e.kind === "trade") return `<div class="of-work of-trade"><b style="color:${TEAM_COLOR.quant}">현우</b> <span>${ctx.esc(e.text)}</span><time>${time}</time></div>`;
  if (e.kind === "bt"){
    const row = (k, x) => `<tr><th>${k}</th><td class="${x.ret >= 0 ? "up" : "dn"}">${x.ret >= 0 ? "+" : ""}${x.ret.toFixed(1)}%</td><td>${x.dd.toFixed(1)}%</td><td>${x.win.toFixed(0)}%</td><td>${x.pf.toFixed(2)}</td><td>${x.n}</td></tr>`;
    return `<div class="of-bt ${e.pass ? "pass" : "fail"}"><div class="of-bth"><b>${e.pass ? "✅ 검증 통과" : "❌ 불통과"} · ${ctx.esc(e.name)}</b><span>${ctx.esc(e.market)} ${e.tf === "60" ? "1시간" : e.tf === "240" ? "4시간" : e.tf}봉 · 개발 ${ctx.esc(e.author || "")} · 검증 다온 · ${time}</span></div>
      <table><tr><th></th><th>수익</th><th>최대낙폭</th><th>승률</th><th>손익비</th><th>거래</th></tr>${row("전체", e.all)}${row("개발 70%", e.is)}${row("검증 30%", e.oos)}</table>
      <div class="of-btr">${(e.reasons || []).map(r => "· " + ctx.esc(r)).join("<br>")}</div>
      <details><summary>전략 JSON</summary><pre>${ctx.esc(JSON.stringify(e.spec, null, 1)).slice(0, 4000)}</pre></details></div>`;
  }
  if (e.kind === "work") return `<div class="of-work"><b style="color:${TEAM_COLOR[a.team]}">${a.name}</b> <span>${ctx.esc(e.icon || "")} ${e.url ? link(e.url, e.text) : ctx.esc(e.text)}${e.src ? ` <small>· ${ctx.esc(e.src)}</small>` : ""}</span><time>${time}</time></div>`;
  if (e.chat) return `<div class="of-msg chat"><div class="of-av sm">${sprite(a)}</div><div class="of-mb"><div class="of-who"><b style="color:${TEAM_COLOR[a.team]}">${a.name}</b><span>${a.title}</span></div><div class="of-tx">${ctx.esc(e.text)}</div></div></div>`;
  const body = e.text ? ctx.md(e.text) : e.steps?.length || e.think ? "" : `<span class="of-typing">생각 정리하는 중<i>.</i><i>.</i><i>.</i></span>`;
  return `<div class="of-msg${e.live ? " of-live" : ""}" data-e="${e.id}"><div class="of-av">${sprite(a)}</div><div class="of-mb"><div class="of-who"><b style="color:${TEAM_COLOR[a.team]}">${a.name}</b><span>${a.title}${e.model ? " · " + ctx.esc(shortModel(e.model)) : ""} · ${time}</span></div>
    ${e.notes?.length ? `<div class="of-note">${e.notes.map(n => "↻ " + ctx.esc(n)).join("<br>")}</div>` : ""}
    ${e.think ? `<div class="of-think">💭 ${ctx.esc(e.think.length > 600 && !e.live ? e.think.slice(0, 600) + "…" : e.think)}</div>` : ""}
    ${stepsHTML(e)}
    ${body ? `<div class="of-tx md">${body}</div>` : ""}<button class="of-link" data-more>펼치기 · 접기</button></div></div>`;
}
function appendEntry(e){
  const box = $o("#ofLog"); if (!box) return;
  box.querySelector(".of-empty")?.remove();
  const near = box.scrollHeight - box.scrollTop - box.clientHeight < 120;
  box.insertAdjacentHTML("beforeend", entryHTML(e));
  if (near) box.scrollTop = box.scrollHeight;
}
function updateEntry(e){
  const box = $o("#ofLog"), el = box?.querySelector(`[data-e="${e.id}"]`);
  if (!el){ if (inChan(e)) appendEntry(e); return; }
  const near = box.scrollHeight - box.scrollTop - box.clientHeight < 160;
  el.outerHTML = entryHTML(e);
  if (near) box.scrollTop = box.scrollHeight;
}
/* ============ 직원 카드 · 팀 구성 ============ */
function showCard(id){
  const a = agentById(id), t = teamById(a.team), mdl = assignModels()[id];
  const sk = a.skills.map(s => BUILTIN_SKILLS.find(b => b.id === s)?.name || s);
  const c = $o("#ofCard");
  c.innerHTML = `<div class="of-cardh"><div class="of-av big">${sprite(a)}</div><div><b>${a.name}</b><span>${t.name} · ${a.title}</span></div><button class="of-x" aria-label="닫기">✕</button></div>
    <p>${ctx.esc(a.duty)}</p>
    <dl><dt>스킬</dt><dd>${sk.length ? sk.map(ctx.esc).join(", ") : "공통 도구(검색·계산·NVIDIA 스킬)"}</dd><dt>배정된 AI 모델</dt><dd>${mdl ? ctx.esc(mdl.model) + " · 막히면 다른 모델로 자동 전환" : "API 키를 넣으면 배정됩니다"}</dd><dt>부르는 법</dt><dd>메시지에 <code>@${a.name}</code></dd></dl>
    ${seen[id]?.length ? `<h4 class="of-h4">최근에 본 것</h4><ul class="of-seen">${seen[id].map(o => `<li>${ctx.esc(o.icon || "")} ${o.url ? link(o.url, o.text) : ctx.esc(o.text)} <small>${new Date(o.t).toLocaleTimeString("ko-KR", {hour: "2-digit", minute: "2-digit"})}</small></li>`).join("")}</ul>` : ""}`;
  c.hidden = false;
}
function showTeam(){
  const models = assignModels();
  const c = $o("#ofCard");
  c.innerHTML = `<div class="of-cardh"><div><b>팀 구성 · ${AGENTS.length}명</b><span>질문 내용으로 담당자가 자동으로 정해지고, 투자·실행 판단은 전략가 → 반론 검토관 → 리스크 책임자를 거쳐 팀장이 정리합니다</span></div><button class="of-x" aria-label="닫기">✕</button></div>
    <div class="of-teams">${TEAMS.map(t => `<div class="of-team" style="--tc:${TEAM_COLOR[t.id]}"><b>${t.name}</b><span>${t.desc}</span>${AGENTS.filter(a => a.team === t.id).map(a => `<div class="of-mem" data-ag="${a.id}"><div class="of-av">${sprite(a)}</div><div><b>${a.name}</b> <span>${a.title}</span><small>${models[a.id] ? ctx.esc(shortModel(models[a.id].model)) : "모델 미배정"}</small></div></div>`).join("")}</div>`).join("")}</div>
    <p class="of-flow">회의 순서(코드가 정함): 담당 분석가 → <b>전략가</b>(실행 계획) → <b>반론 검토관</b>(반대 근거 3개 + 판정) → <b>리스크 책임자</b>(승인·축소·거부) → <b>팀장</b>(최종 답). 일상 질문은 담당자 한 명이 바로 답합니다. 발언 속 @이름으로 동료를 부르면 그 사람이 회의에 들어옵니다.</p>`;
  c.hidden = false;
}

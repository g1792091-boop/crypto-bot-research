// GH Nano 사무실 대시보드: 픽셀아트 사무실 + 회의 기록 패널
// 직원들이 자리에서 일하다가 회의가 열리면 회의 장소(팀 구역·대회의실·라운지·발표 무대)로 걸어가 말풍선으로 대화하고,
// 오른쪽 패널에 회의록이 쌓인다. 배치는 TEAMS에서 자동으로 만든다(팀이 늘어도 깨지지 않게).
// office.js의 새 기능(listReports·backlog 등)은 있을 때만 쓴다 → import * as O 로 받아 typeof 검사.
import * as O from "./office.js";
import * as SD from "./selfdev.js";
import { shortModel, provUse, settings, saveSettings, LAUNCHER, provCapOf } from "./engine.js";
import { BUILTIN_SKILLS } from "./agent.js";

const TEAMS = O.TEAMS || [], AGENTS = O.AGENTS || [], AGENDA = O.AGENDA || [];
const agentById = id => (O.agentById ? O.agentById(id) : AGENTS.find(a => a.id === id));
const teamById = id => (O.teamById ? O.teamById(id) : TEAMS.find(t => t.id === id));
const has = name => typeof O[name] === "function";
const LEAD_OF = O.TEAM_LEAD || Object.fromEntries(TEAMS.map(t => [t.id, (AGENTS.find(a => a.team === t.id && a.lead) || AGENTS.find(a => a.team === t.id))?.id]));
const isLead = a => !!a && (a.lead ?? LEAD_OF[a.team] === a.id);
const CEO = LEAD_OF.hq || "lead";
const membersOf = tid => AGENTS.filter(a => a.team === tid).sort((x, y) => isLead(y) - isLead(x));

/* ============ 팀 색 ============ */
const TEAM_COLOR = {hq: "#7c6cf0", coin: "#f0a020", stock: "#2f8fd8", fut: "#16a39a", realestate: "#7a8f2a", arch: "#d9822b", quant: "#2e9e6b",
  strat: "#d0465a", data: "#c2185b", lab: "#8a63d2", venture: "#3f51b5"};
const tc = id => TEAM_COLOR[id] || "#9aa4b5";

/* ============ 사무실 배치: TEAMS로 자동 생성 ============ */
// 위: 팀 구역 격자(4열, 구역마다 책상 3개 × 줄) + 모의투자 현황판 / 맨 아래 줄: 대회의실(2칸) · 라운지 · 발표 무대
const M = 20, G = 16, ZW = 340, COLS = 4, BH = 270;
const DROWS = Math.max(1, Math.ceil(Math.max(3, ...TEAMS.map(t => membersOf(t.id).length)) / 3));
const ZH = 128 + (DROWS - 1) * 112 + 30;
const ZONES = {};
const SLOTS = [...TEAMS.map(t => t.id), "board"];
SLOTS.forEach((id, i) => {
  const col = i % COLS, row = Math.floor(i / COLS);
  ZONES[id] = {x: M + col * (ZW + G), y: M + row * (ZH + G), w: ZW, h: ZH, kind: id === "board" ? "board" : "team", label: id === "board" ? "모의투자 현황판" : teamById(id).name};
});
const ROWS = Math.ceil(SLOTS.length / COLS), Y0 = M + ROWS * (ZH + G);
ZONES.meet = {x: M, y: Y0, w: ZW * 2 + G, h: BH, kind: "meet", label: "대회의실"};
ZONES.lounge = {x: M + 2 * (ZW + G), y: Y0, w: ZW, h: BH, kind: "lounge", label: "라운지"};
ZONES.stage = {x: M + 3 * (ZW + G), y: Y0, w: ZW, h: BH, kind: "stage", label: "발표 무대"};
const W = M * 2 + COLS * ZW + (COLS - 1) * G, H = Y0 + BH + M;
const PLACE_KO = {meet: "대회의실", lounge: "라운지", stage: "발표 무대"};
const placeName = p => PLACE_KO[p] || (teamById(p)?.name || p) + " 구역";
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const inWorld = p => ({x: clamp(p.x, 30, W - 30), y: clamp(p.y, 72, H - 18)});

// 직원 자리: 팀 구역 안 책상(팀장이 첫 자리, 큰 책상) 앞
const HOME = {}, DESKS = [];
for (const t of TEAMS){
  const z = ZONES[t.id];
  membersOf(t.id).forEach((a, k) => {
    const cx = z.x + 60 + (k % 3) * 110, dy = z.y + 62 + Math.floor(k / 3) * 112;
    DESKS.push({x: cx, y: dy, team: t.id, lead: isLead(a), plate: t.id === "hq" && isLead(a) ? "CEO" : isLead(a) ? "팀장" : ""});
    HOME[a.id] = {x: cx, y: dy + 66};
  });
}
for (const a of AGENTS) if (!HOME[a.id]) HOME[a.id] = {x: ZONES.lounge.x + 170, y: ZONES.lounge.y + 200};

// 회의 자리: 장소마다 결정적인 자리 번호(i) → 좌표. 처음 10명은 앉고, 그 뒤는 둘러서기
const SPREAD = [0, 5, 2, 7, 4, 9, 1, 6, 3, 8];
const MT = (() => { const z = ZONES.meet, tw = 440, th = 52; return {x: z.x + (z.w - tw) / 2, y: z.y + 110, w: tw, h: th}; })();
const MEET_SEATS = [2, 1, 3, 0, 4].flatMap(k => [{x: MT.x + 44 + k * 88, y: MT.y + 6}, {x: MT.x + 44 + k * 88, y: MT.y + MT.h + 50}]);
const STG = (() => { const z = ZONES.stage; return {podium: {x: z.x + z.w / 2, y: z.y + 118}, seats: [0, 1].flatMap(r => [2, 1, 3, 0, 4].map(k => ({x: z.x + 50 + k * 60, y: z.y + 185 + r * 62})))}; })();
const ringCenter = place => { const z = ZONES[place]; return place === "lounge" ? {x: z.x + z.w / 2, y: z.y + 165, rx: 112, ry: 60} : {x: z.x + z.w / 2, y: z.y + 150, rx: 128, ry: 66}; };
function ring(place, i){
  const c = ringCenter(place), outer = i >= 10, k = SPREAD[i % 10] + (outer ? 0.5 : 0);
  const ang = -Math.PI / 2 + k / 10 * Math.PI * 2, s = outer ? 1.3 : 1;
  return {x: c.x + Math.cos(ang) * c.rx * s, y: c.y + Math.sin(ang) * c.ry * s};
}
function seatAt(place, i){
  let p;
  if (place === "meet"){
    if (i < 10) p = MEET_SEATS[i];
    else { const j = i - 10, side = j % 2, row = Math.floor(j / 2); p = {x: side ? MT.x + MT.w + 40 + Math.floor(row / 3) * 50 : MT.x - 40 - Math.floor(row / 3) * 50, y: MT.y + 20 + (row % 3) * 55}; }
  } else if (place === "stage"){
    if (i === 0) p = STG.podium;
    else if (i <= 10) p = STG.seats[i - 1];
    else { const j = i - 11, z = ZONES.stage; p = {x: j % 2 ? z.x + z.w - 22 : z.x + 22, y: z.y + 150 + Math.floor(j / 2) * 40}; }
  } else p = ring(ZONES[place] ? place : "meet", i);
  return inWorld(p);
}
const placeOf = p => p && ZONES[p] && ZONES[p].kind !== "board" ? p : "meet";
const LOUNGE = (() => { const z = ZONES.lounge; return [{x: z.x + 60, y: z.y + 112, say: "커피 한 잔 하고 올게요"}, {x: z.x + 240, y: z.y + 104, say: "잠깐 쉬는 중"}, {x: z.x + 96, y: z.y + 238, say: "차트 다시 보는 중"}, {x: z.x + 262, y: z.y + 240, say: "뉴스 훑어보는 중"}]; })();
const IDLE = ["시세 확인 중", "자료 정리 중", "다음 회의 준비 중", "메모하는 중", "보고서 쓰는 중"];
const IDLE_T = {hq: ["🗂 팀별 보고 모으는 중", "📝 발표 자료 정리 중"], coin: ["🪙 코인 차트 보는 중", "🐋 고래 체결 지켜보는 중"], stock: ["📊 실적 자료 읽는 중", "🗞 공시 확인 중"],
  fut: ["🗓 경제 일정 정리 중", "🛢 원자재 차트 보는 중"], realestate: ["🏘 정비구역 지도 보는 중", "📑 부동산 정책 자료 정리 중"], arch: ["📐 평면도 다듬는 중", "🧱 견적 다시 보는 중"],
  quant: ["🧪 백테스트 결과 보는 중", "🧠 모델 특징 고르는 중"], strat: ["⚖️ 포트폴리오 비중 점검 중", "🧯 최악의 시나리오 그려 보는 중"], data: ["📥 데이터 수집 점검 중", "📈 발표용 차트 그리는 중"],
  lab: ["💻 코드 리뷰 중", "🎓 학습 데이터 점검 중"], venture: ["🪙 토큰 분배표 고치는 중", "💼 사업계획서 쓰는 중"]};
const idleLine = a => { const l = IDLE_T[a.team] || IDLE.map(x => "💼 " + x); return l[Math.floor(Math.random() * l.length)]; };

/* ============ 픽셀 캐릭터 ============ */
const LONG = new Set(["coin_spot", "us", "kfut", "arch", "devil", "research", "aide", "qb", "sns", "alt", "techus", "etf", "fx", "redev", "retax", "render", "interior", "ml", "pm", "comp", "insta", "viz", "mlops", "token", "terminal", "brand"]);
function sprite(a){
  const [hair, shirt] = a.look || ["#333", "#888"], skin = "#f2c8a0", pants = "#3b3f58", shoe = "#2a2a2a", eye = "#222";
  const long = LONG.has(a.id);
  const Gr = [
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
  Gr.forEach((row, y) => { let x = 0; while (x < row.length){ const ch = row[x]; let n = 1; while (row[x + n] === ch) n++; if (C[ch]) r += `<rect x="${x}" y="${y}" width="${n}" height="1" fill="${C[ch]}"/>`; x += n; } });
  return `<svg viewBox="0 0 12 15" shape-rendering="crispEdges" aria-hidden="true">${r}</svg>`;
}

let ctx = null, root = null, chan = "all", unsub = null, idleT = 0, statusT = 0, seatOf = {}, away = {}, meetPlace = "meet", huddle = new Set(), speaking = null;
const onStage = new Set(), repCache = {};
let presentT = 0, scale = 1;
const pos = {};
export function openOffice(opts){
  ctx = opts;
  if (!root){ root = build(); document.body.appendChild(root); }
  root.hidden = false; document.body.classList.add("office-open");
  $o("#ofCoinHQ").hidden = typeof ctx.openCoinHQ !== "function"; $o("#ofTerm").hidden = typeof ctx.openTerminal !== "function"; $o("#ofLive").hidden = typeof ctx.openLive !== "function";
  fit(); O.loadLog().then(renderLog);
  O.startAutopilot(); try { localStorage.setItem("officeUsed", "1"); } catch(e){}
  O.setOfficeVisible(true); O.startChatter(); O.startCycle(); refreshBoard();
  // 사무실을 열면 30초 안에 첫 수다가 시작되게
  if (O.nextChatIn() === 0 || O.nextChatIn() > 30e3) localStorage.setItem("officeLastChat", String(Date.now() - O.officeCfg().chatEvery * 60e3 + 30e3));
  if (!unsub) unsub = O.onOffice(onEvent);
  clearInterval(idleT); idleT = setInterval(idle, 7000);
  clearInterval(statusT); statusT = setInterval(renderStatus, 5000); renderStatus();
  const s = O.officeState(); if (s.running) onEvent({kind: "start", meeting: s.running});
  setTimeout(() => root.querySelector("#ofIn")?.focus(), 50);
}
export function closeOffice(){
  if (!root) return; root.hidden = true; document.body.classList.remove("office-open"); clearInterval(idleT); clearInterval(statusT); O.setOfficeVisible(false);
  if (location.hash === "#office") history.replaceState(null, "", location.pathname + location.search);
}
export const officeOpen = () => !!root && !root.hidden;
if (typeof window !== "undefined") window.__officeUI = {onEvent: ev => onEvent(ev), openPres: x => openPres(x), layout: {W, H, ZONES, HOME}};

function build(){
  const el = document.createElement("section");
  el.className = "office"; el.id = "office"; el.setAttribute("aria-label", "AI 팀 사무실");
  const zones = Object.entries(ZONES).map(([id, z]) => `<div class="of-zone z-${z.kind} z-${id}" data-z="${id}" style="left:${z.x}px;top:${z.y}px;width:${z.w}px;height:${z.h}px;${TEAM_COLOR[id] ? `--tc:${TEAM_COLOR[id]}` : ""}"><span class="of-zl">${TEAM_COLOR[id] ? "<i></i>" : ""}${z.label}${z.kind === "team" ? `<small>${membersOf(id).length}명</small>` : ""}</span></div>`).join("");
  const desks = DESKS.map(d => `<div class="of-desk${d.lead ? " lead" : ""}" style="left:${d.x - (d.lead ? 42 : 34)}px;top:${d.y - 20}px;--tc:${tc(d.team)}"><i class="mon"></i><i class="mug"></i>${d.plate ? `<em>${d.plate}</em>` : ""}</div><div class="of-chair" style="left:${d.x - 11}px;top:${d.y + 22}px"></div>`).join("");
  // 팀 회의용 작은 테이블 (그 팀 구역에서 회의할 때만 보인다)
  const mtables = TEAMS.map(t => { const c = ringCenter(t.id); return `<div class="of-mtable" data-mt="${t.id}" style="left:${c.x - 34}px;top:${c.y - 16}px"></div>`; }).join("");
  const hq = ZONES.hq || ZONES[TEAMS[0]?.id], mz = ZONES.meet, lz = ZONES.lounge, sz = ZONES.stage, bz = ZONES.board;
  const props = `
    <div class="of-board" style="left:${hq.x + 20}px;top:${hq.y + 168}px"><b>오늘의 안건</b><span id="ofBoard">자동 회의 대기 중</span></div>
    <div class="of-plant" style="left:${hq.x + hq.w - 36}px;top:${hq.y + hq.h - 40}px"></div>
    <div class="of-tv" style="left:${mz.x + mz.w / 2 - 95}px;top:${mz.y + 30}px"><i></i></div>
    <div class="of-table" style="left:${MT.x}px;top:${MT.y}px;width:${MT.w}px;height:${MT.h}px"></div>
    ${MEET_SEATS.map(s => `<div class="of-seat" style="left:${s.x - 11}px;top:${s.y - 4}px"></div>`).join("")}
    <div class="of-plant" style="left:${mz.x + 14}px;top:${mz.y + 228}px"></div><div class="of-plant" style="left:${mz.x + mz.w - 34}px;top:${mz.y + 228}px"></div>
    <div class="of-coffee" style="left:${lz.x + 18}px;top:${lz.y + 30}px"></div><div class="of-fridge" style="left:${lz.x + 56}px;top:${lz.y + 26}px"></div>
    <div class="of-sofa" style="left:${lz.x + 180}px;top:${lz.y + 40}px"></div><div class="of-lamp" style="left:${lz.x + 306}px;top:${lz.y + 30}px"></div>
    <div class="of-ltable" style="left:${lz.x + lz.w / 2 - 36}px;top:${lz.y + 148}px"></div><div class="of-plant" style="left:${lz.x + 310}px;top:${lz.y + 228}px"></div>
    <div class="of-platform" style="left:${sz.x + 14}px;top:${sz.y + 30}px;width:${sz.w - 28}px"></div>
    <div class="of-scr" id="ofStageScr" style="left:${sz.x + sz.w / 2 - 110}px;top:${sz.y + 36}px"><b>📢 시간별 성과 발표</b><span>매시 정각 CEO가 팀별 성과를 발표합니다</span></div>
    <div class="of-podium" style="left:${STG.podium.x + 26}px;top:${STG.podium.y - 30}px"></div>
    ${STG.seats.map(s => `<div class="of-seat sm" style="left:${s.x - 9}px;top:${s.y - 2}px"></div>`).join("")}
    <div class="of-pboard" style="left:${bz.x + 14}px;top:${bz.y + 30}px;width:${bz.w - 28}px;height:${bz.h - 44}px"><b>모의투자 현황판 <span id="ofPTot"></span></b><div id="ofPList">아직 운용 중인 전략이 없습니다</div></div>`;
  const agents = AGENTS.map(a => `<div class="of-ag${isLead(a) ? " lead" : ""}" data-ag="${a.id}" style="--tc:${tc(a.team)}" tabindex="0" role="button" aria-label="${a.name} ${a.title}"><div class="of-bub" hidden></div><div class="of-spr">${sprite(a)}</div><div class="of-nm">${isLead(a) ? "<i>♛</i>" : ""}${a.name}</div></div>`).join("");
  const agendaOpts = AGENDA.map(a => `<button data-agenda="${a.id}">#${a.title}</button>`).join("");
  el.innerHTML = `
  <div class="of-top">
    <span class="of-dots"><i></i><i></i><i></i></span>
    <span class="of-path"><span class="of-pfx">~/gh-nano/우리-사무실 · </span><b id="ofMode">대기</b></span>
    <span class="of-sp"></span>
    <select id="ofSpeed" title="직원들이 스스로 한 가지 일(매매법 연구·SNS·경제 리서치·모의투자·컴퓨터 작업)을 하는 간격입니다. 짧을수록 AI 호출이 많아집니다"><option value="1">업무 1분(쉬지 않고)</option><option value="3">업무 3분</option><option value="5">업무 5분</option><option value="10">업무 10분</option></select>
    <select id="ofClaude" class="of-cl" title="Claude: 전원 — 직원 전원이 Claude로 일합니다(전략·리스크·검증·퀀트는 Opus, 분석은 Sonnet, 가벼운 일은 Haiku).&#10;Claude: 핵심 자리만 — 판단 책임이 큰 자리만 Claude, 나머지는 무료 모델이라 그 글을 GH Nano 학습에 쓸 수 있습니다.&#10;Claude: 안 씀 — 모두 무료 모델.&#10;Anthropic 약관에 따라 Claude가 쓴 글은 GH Nano 학습 데이터에서 제외됩니다. 하루 한도를 넘으면 무료 모델로 돌아갑니다."><option value="all">Claude: 전원</option><option value="key">Claude: 핵심 자리만 (나머지 무료 → GH Nano 학습 가능)</option><option value="off">Claude: 안 씀</option></select>
    <button class="of-btn" id="ofNow" title="다음 주기를 기다리지 않고 지금 한 가지 일을 시킵니다">지금 일 시키기</button>
    <span class="of-pick"><button class="of-btn" id="ofAgendaBtn" aria-haspopup="true">안건 열기 ▾</button><div class="of-menu" id="ofAgenda" hidden>${agendaOpts}</div></span>
    <button class="of-btn" id="ofPresBtn" title="매시 CEO의 팀별 성과 발표를 다시 봅니다">📢 발표</button><button class="of-btn" id="ofCoinHQ" title="GH Coin 코인 본부: 보조지표·매매법 개발·백테스트·데모·실거래·추세·타점·지지저항·익절손절·뉴스·상황판·패턴·커스텀 지표·코인별 팀 (23팀 × 11명)" hidden>🪙 코인 본부</button><button class="of-btn" id="ofDocsBtn" title="사업계획서·보고서·설계안·매매법 등 직원들이 만든 결과물">📁 결과물</button>
    <button class="of-btn" id="ofTeam">팀 구성</button>
    <button class="of-btn" id="ofTerm" hidden>📈 차트 터미널</button>
    <button class="of-btn" id="ofLive" hidden>💰 실거래</button>
    <span class="of-pick"><button class="of-btn" id="ofSetBtn" aria-haspopup="true">설정 ▾</button><div class="of-menu of-set" id="ofSet" hidden>
      <div class="of-row"><label class="of-tg" title="사용자가 아무것도 하지 않아도 정해진 간격과 급변동 때 스스로 회의합니다"><input type="checkbox" id="ofAuto"> 자동 회의</label>
        <select id="ofEvery" title="자동 회의 간격"><option value="15">15분마다</option><option value="30">30분마다</option><option value="60">1시간마다</option><option value="180">3시간마다</option></select></div>
      <div class="of-row" title="사무실이 하루에 AI를 부르는 최대 횟수. 다 쓰면 모의투자 갱신·차트·뉴스 확인(코드)만 계속합니다. 쉬지 않고 일하려면 크게 두세요(유료 API면 비용이 늘어납니다)">하루 AI 호출
        <select id="ofCallMax"><option value="600">600번</option><option value="1500">1,500번</option><option value="3000">3,000번</option><option value="10000">10,000번</option><option value="1000000">제한 없음</option></select></div>
      <label class="of-tg" title="정해진 간격마다 사람처럼 한 가지 일(매매법 연구·SNS·경제 리서치·모의투자·컴퓨터 작업)을 스스로 합니다"><input type="checkbox" id="ofCycle"> 주기 업무</label>
      <label class="of-tg" title="직원들이 수시로 본 차트·뉴스를 두고 잡담합니다 (한 번에 AI 1번)"><input type="checkbox" id="ofChat"> 수시 대화</label>
      <label class="of-tg" title="문서/GHNano 사무실 폴더 안에서만 파일을 만들고 스크립트를 실행합니다 (GHNano.exe에서만)"><input type="checkbox" id="ofComp"> 컴퓨터 작업</label>
      <label class="of-tg" title="직원들의 회의·분석·수다를 GH Nano 학습 데이터로 남깁니다 (Claude가 쓴 글은 약관에 따라 제외)"><input type="checkbox" id="ofTrain"> 학습에 쓰기</label>
    </div></span>
    <button class="of-btn" id="ofStop" hidden>회의 멈추기</button>
    <span class="of-rec" id="ofRec"><i></i> 녹화</span>
    <button class="of-x" id="ofClose" title="채팅으로 돌아가기" aria-label="닫기">✕</button>
  </div>
  <div class="of-body">
    <div class="of-stage" id="ofStage"><div class="of-floor" id="ofFloor" style="width:${W}px;height:${H}px">${zones}${desks}${mtables}${props}${agents}</div></div>
    <aside class="of-side">
      <div class="of-head">
        <div class="of-h1"><i class="of-led" id="ofLed"></i><b id="ofTitle">대기 중</b><span class="of-sp"></span><span class="of-recl" id="ofRecL">녹화 중</span></div>
        <div class="of-h2" id="ofStatus"></div>
        <div class="of-chans" id="ofChans"><button data-ch="all" aria-pressed="true">#전체</button><button data-ch="work" aria-pressed="false" style="--tc:#c9a227">#업무</button><button data-ch="growth" aria-pressed="false" style="--tc:#3ddc84">#성장 과제<span id="ofGrowN"></span></button>${TEAMS.map(t => `<button data-ch="${t.id}" aria-pressed="false" style="--tc:${tc(t.id)}">#${t.name}</button>`).join("")}</div>
      </div>
      <div class="of-log" id="ofLog" aria-live="polite"></div>
      <form class="of-form" id="ofForm"><input id="ofIn" placeholder="사무실에 메시지 보내기 (예: 비트코인 지금 롱 어때? / 60평 대지에 3층 주택 설계)" autocomplete="off"><button type="submit" aria-label="보내기">↵</button></form>
      <div class="of-foot" id="ofFoot"></div>
    </aside>
  </div>
  <div class="of-card" id="ofCard" hidden></div>
  <div class="of-pres" id="ofPres" hidden><div class="of-presbox" role="dialog" aria-modal="true" aria-label="시간별 성과 발표">
    <div class="of-presh"><b>📢 시간별 성과 발표</b><span id="ofPresSub"></span><button class="of-btn" id="ofPresNow" hidden title="정각을 기다리지 않고 CEO가 지금까지의 성과를 바로 발표합니다">지금 발표하기</button><button class="of-x" data-presclose aria-label="닫기">✕</button></div>
    <div class="of-presbody"><nav class="of-preslist" id="ofPresList"></nav><article class="of-presview" id="ofPresView"></article></div>
  </div></div>
  <div class="of-zoom" id="ofZoom" hidden><img alt="건축 이미지 크게 보기"></div>`;
  // 처음 자리
  for (const a of AGENTS) pos[a.id] = {...HOME[a.id]};
  root = el;
  requestAnimationFrame(() => AGENTS.forEach(a => place(a.id, HOME[a.id], true)));
  wire(el);
  if ("ResizeObserver" in window) new ResizeObserver(fit).observe(el.querySelector("#ofStage")); else window.addEventListener("resize", fit);
  return el;
}
// 끌어 보는 화면이면 회의·발표 장소가 보이게 스크롤
function showPlace(id){
  const st = root.querySelector("#ofStage"), z = ZONES[id]; if (!z || !st.classList.contains("pan")) return;
  const fl = root.querySelector("#ofFloor"), ox = parseFloat(fl.style.left) || 0, oy = parseFloat(fl.style.top) || 0;
  st.scrollTo({left: ox + (z.x + z.w / 2) * scale - st.clientWidth / 2, top: oy + (z.y + z.h / 2) * scale - st.clientHeight / 2, behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth"});
}
function fit(){
  if (!root) return;
  const st = root.querySelector("#ofStage"), fl = root.querySelector("#ofFloor");
  // 휴대폰처럼 좁으면 너무 작아지지 않게 0.4배까지만 줄이고, 사무실 안에서 손가락으로 끌어 본다(페이지는 넘치지 않음)
  const fitS = Math.min(st.clientWidth / W, st.clientHeight / H) || 1, pan = st.clientWidth < 640 && fitS < 0.4, s = pan ? 0.4 : fitS;
  scale = s; st.classList.toggle("pan", pan);
  fl.style.transform = `scale(${s})`;
  fl.style.left = Math.max(0, (st.clientWidth - W * s) / 2) + "px"; fl.style.top = Math.max(0, (st.clientHeight - H * s) / 2) + "px";
}
const $o = s => root.querySelector(s);
const E = s => ctx.esc(String(s ?? ""));
// 드롭다운은 위쪽 막대가 가로로 스크롤돼도 잘리지 않게 화면 기준(fixed)으로 띄운다
function toggleMenu(btn, menu){
  const open = menu.hidden;
  root.querySelectorAll(".of-menu").forEach(m => { m.hidden = true; });
  if (!open) return;
  menu.hidden = false; menu._at = Date.now();
  const r = btn.getBoundingClientRect(), mw = menu.offsetWidth;
  menu.style.left = Math.max(8, Math.min(r.left, innerWidth - mw - 8)) + "px"; menu.style.top = r.bottom + 4 + "px";
}
const claudeMode = c => c.claudeMode || (c.claude === false ? "off" : "all");
function wire(el){
  const c = O.officeCfg();
  el.querySelector("#ofAuto").checked = !!c.auto;
  el.querySelector("#ofEvery").value = String(c.every);
  el.querySelector("#ofAuto").onchange = e => { O.setOffice({auto: e.target.checked}); ctx.toast(e.target.checked ? "자동 회의를 켰습니다. 팀이 스스로 시장을 점검합니다" : "자동 회의를 껐습니다"); renderStatus(); };
  el.querySelector("#ofEvery").onchange = e => { O.setOffice({every: +e.target.value}); renderStatus(); };
  el.querySelector("#ofCallMax").value = String(c.callMax || 600);
  el.querySelector("#ofCallMax").onchange = e => { O.setOffice({callMax: +e.target.value}); renderStatus(); };
  el.querySelector("#ofCycle").onchange = e => { O.setOffice({cycle: e.target.checked}); renderStatus(); };
  el.querySelector("#ofSpeed").onchange = e => { const v = +e.target.value; O.setOffice({cycleMin: v}); ctx.toast(v <= 1 ? "직원들이 쉬지 않고(1분마다) 일합니다 · AI 호출이 많아집니다" : `직원들이 ${v}분마다 한 가지 일을 합니다`); renderStatus(); };
  el.querySelector("#ofComp").onchange = e => { O.setOffice({computer: e.target.checked}); if (e.target.checked && !LAUNCHER.on) ctx.toast("컴퓨터 작업은 GHNano.exe로 실행했을 때만 됩니다"); renderStatus(); };
  el.querySelector("#ofClaude").onchange = e => {
    const v = e.target.value; O.setOffice({claudeMode: v, claude: v !== "off"});
    if (v !== "off" && !settings.keys.anthropic) ctx.toast("설정 → AI 두뇌에 Claude API 키(sk-ant-…)를 넣으면 씁니다");
    else ctx.toast(v === "all" ? "직원 전원이 Claude로 일합니다 (Claude가 쓴 글은 학습 데이터에서 제외)" : v === "key" ? "핵심 자리만 Claude · 나머지 직원의 글은 GH Nano 학습에 쓸 수 있습니다" : "Claude를 쓰지 않습니다 · 모두 무료 모델");
    renderStatus();
  };
  el.querySelector("#ofTrain").onchange = e => { O.setOffice({train: e.target.checked}); ctx.toast(e.target.checked ? "직원들의 대화를 GH Nano 학습 데이터로 남깁니다" : "학습 데이터 기록을 멈췄습니다"); renderStatus(); };
  el.querySelector("#ofNow").onclick = async () => { ctx.toast("지금 한 가지 일을 시킵니다"); const ok = await O.cycle(true); if (!ok) ctx.toast("지금은 다른 일을 하는 중이거나 연결된 AI가 없습니다"); };
  el.querySelector("#ofChat").checked = c.chat !== false;
  el.querySelector("#ofChat").onchange = e => { O.setOffice({chat: e.target.checked}); if (e.target.checked){ localStorage.setItem("officeLastChat", "0"); } renderStatus(); };
  el.querySelector("#ofClose").onclick = closeOffice;
  el.addEventListener("change", e => {
    const sel = e.target.closest("[data-assign]"); if (!sel) return;
    O.setAssign(sel.dataset.assign, sel.value);
    const who = sel.dataset.assign === "all" ? "전원" : sel.dataset.assign.startsWith("team:") ? teamById(sel.dataset.assign.slice(5))?.name : agentById(sel.dataset.assign)?.name;
    ctx.toast(sel.value ? `${who}: ${shortModel(sel.value.split("|").slice(1).join("|"))} 로 일합니다` : `${who}: 자동 배정으로 돌아갑니다`);
  });
  el.querySelector("#ofStop").onclick = () => { O.stopMeeting(); ctx.toast("회의를 멈췄습니다"); };
  el.querySelector("#ofAgendaBtn").onclick = e => { e.stopPropagation(); toggleMenu(e.currentTarget, $o("#ofAgenda")); };
  el.querySelector("#ofSetBtn").onclick = e => { e.stopPropagation(); toggleMenu(e.currentTarget, $o("#ofSet")); };
  el.querySelector("#ofPresBtn").onclick = () => openPres(null);
  el.querySelector("#ofDocsBtn").onclick = () => openDocs();
  el.querySelector("#ofCoinHQ").onclick = () => { if (typeof ctx.openCoinHQ === "function") ctx.openCoinHQ(); };
  el.querySelector("#ofTerm").onclick = () => { if (typeof ctx.openTerminal === "function"){ closeOffice(); ctx.openTerminal(); } };
  el.querySelector("#ofLive").onclick = () => { if (typeof ctx.openLive === "function"){ closeOffice(); ctx.openLive(); } };
  el.querySelector(".of-top").addEventListener("scroll", () => root.querySelectorAll(".of-menu").forEach(m => { if (Date.now() - (m._at || 0) > 500) m.hidden = true; }), {passive: true});
  el.addEventListener("click", e => {
    if (e.target.closest("[data-docclose]") || e.target.id === "ofDocs"){ $o("#ofDocs").hidden = true; return; }
    const dv = e.target.closest("[data-docview]"); if (dv){ showDoc(dv.dataset.docview); return; }
    const dd = e.target.closest("[data-docdl]"); if (dd){ dlDoc(dd.dataset.docdl); return; }
    const dx = e.target.closest("[data-docdel]"); if (dx){ if (confirm("이 결과물을 앱 보관함에서 지울까요? (폴더의 파일은 그대로)")) O.deleteDoc(dx.dataset.docdel).then(() => openDocs(true)); return; }
    if (e.target.closest("[data-docfolder]")){ O.openFolder(e.target.closest("[data-docfolder]").dataset.docfolder || "").then(r => ctx.toast(r.ok ? "폴더를 열었습니다: " + (r.dir || "") : r.why)); return; }
    const df = e.target.closest("[data-docfilter]"); if (df){ docFilter = df.dataset.docfilter; openDocs(true); return; }
    const pa = e.target.closest("[data-papply]");
    if (pa){ if (!confirm("이 코드 수정을 적용하고 앱을 다시 불러올까요?\n(앱이 안 열리면 자동으로 되돌립니다)")) return; pa.disabled = true;
      SD.applyPatch(pa.dataset.papply).then(r => { if (r.ok){ ctx.toast("수정을 적용했습니다 · 앱을 다시 불러옵니다"); SD.reloadSoon(); } else { ctx.toast("적용하지 못했습니다: " + r.why); renderLog(); } }).catch(err => { ctx.toast("적용 실패: " + err.message); renderLog(); }); return; }
    const pr = e.target.closest("[data-prevert]");
    if (pr){ pr.disabled = true; SD.revertPatch(pr.dataset.prevert).then(r => { if (r.ok){ ctx.toast("수정을 되돌렸습니다 · 앱을 다시 불러옵니다"); SD.reloadSoon(); } else { ctx.toast(r.why); renderLog(); } }).catch(err => { ctx.toast("되돌리기 실패: " + err.message); renderLog(); }); return; }
    const pj = e.target.closest("[data-preject]");
    if (pj){ SD.rejectPatch(pj.dataset.preject); ctx.toast("수정안을 버렸습니다"); renderLog(); return; }
    const pd = e.target.closest("[data-pdl]");
    if (pd){ const p = SD.listPatches().find(x => x.id === pd.dataset.pdl); if (p){ const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([SD.patchText(p)], {type: "text/plain"})); a.download = `수정안-${p.file.replace(/\W+/g, "_")}.txt`; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000); } return; }
    const ag = e.target.closest("[data-agenda]");
    if (ag){ $o("#ofAgenda").hidden = true; O.runAgendaNow(ag.dataset.agenda); ctx.toast("회의를 엽니다"); return; }
    if (!e.target.closest(".of-pick")) root.querySelectorAll(".of-menu").forEach(m => { m.hidden = true; });
    if (e.target.closest("#ofZoom")){ $o("#ofZoom").hidden = true; return; }
    const zm = e.target.closest("[data-zoom]");
    if (zm){ const z = $o("#ofZoom"); z.querySelector("img").src = zm.getAttribute("src"); z.hidden = false; return; }
    if (e.target.closest("#ofPresNow")){ const b = e.target.closest("#ofPresNow"); b.disabled = true; ctx.toast("CEO가 발표를 준비합니다 · 팀장 보고를 모으는 중"); Promise.resolve(O.presentNow()).catch(() => null).then(r => { b.disabled = false; if (!r) ctx.toast("지금은 발표를 만들 수 없습니다 (이미 발표 중이거나 연결된 AI가 없음)"); }); return; }
    if (e.target.closest("[data-presclose]") || e.target.id === "ofPres"){ $o("#ofPres").hidden = true; return; }
    const rp = e.target.closest("[data-rep]");
    if (rp){ showReport(rp.dataset.rep); return; }
    const rep = e.target.closest("[data-report]");
    if (rep){ openPres(rep.dataset.report || null); return; }
    const bld = e.target.closest("[data-build]");
    if (bld){ O.loadLog().then(log => { const en = log.find(x => x.id === bld.dataset.build); if (en?.spec && typeof ctx.openBuilding === "function"){ closeOffice(); ctx.openBuilding(en.spec); } }); return; }
    const ch = e.target.closest("[data-ch]");
    if (ch){ chan = ch.dataset.ch; el.querySelectorAll("[data-ch]").forEach(b => b.setAttribute("aria-pressed", b === ch)); renderLog(); $o("#ofIn").placeholder = !teamById(chan) || chan === "hq" ? "사무실에 메시지 보내기 (팀장이 담당자를 부릅니다)" : `#${teamById(chan).name}에 메시지 보내기`; return; }
    const a = e.target.closest("[data-ag]");
    if (a){ showCard(a.dataset.ag); return; }
    if (e.target.closest("#ofTeam")){ showTeam(); return; }
    const rb = e.target.closest("[data-rate]");
    if (rb){ const id = rb.closest("[data-e]")?.dataset.e; if (id) O.rateEntry(id, +rb.dataset.rate).then(en => { if (en){ updateEntry(en); ctx.toast(en.rating < 0 ? "이 발언은 GH Nano 학습 데이터에서 뺐습니다" : en.rating > 0 ? "좋은 발언으로 표시했습니다 (학습에 우선 사용)" : "표시를 지웠습니다"); } }); return; }
    if (e.target.closest("[data-more]")){ const m = e.target.closest(".of-msg"); m.classList.toggle("open"); return; }
    if (e.target.closest("#ofClear")){ O.clearLog(); return; }
    if (e.target.closest("#ofCap")){
      const v = prompt(`Claude 하루 호출 한도 (번). 직원 ${AGENTS.length}명이 ${O.officeCfg().cycleMin}분마다 일하면 하루 수백~수천 번이 쓰일 수 있습니다.`, String(provCapOf("anthropic")));
      if (v != null && +v >= 0){ settings.provCap = {...(settings.provCap || {}), anthropic: Math.round(+v)}; saveSettings(); renderStatus(); ctx.toast(`Claude 하루 한도: ${Math.round(+v)}번`); }
      return;
    }
    if (e.target.closest("#ofCapKey")){ ctx.toast("설정 → AI 두뇌 · API 키에 Claude 키(sk-ant-…)를 붙여 넣으세요"); return; }
    if (e.target.closest(".of-card .of-x")){ $o("#ofCard").hidden = true; return; }
    if (!e.target.closest(".of-card")) $o("#ofCard").hidden = true;
  });
  el.addEventListener("keydown", e => { if ((e.key === "Enter" || e.key === " ") && e.target.matches("[data-ag]")){ e.preventDefault(); showCard(e.target.dataset.ag); } });
  // Escape: 크게 보기 → 발표 창 → 메뉴 → 카드 → 사무실 닫기 (포커스가 어디 있든)
  document.addEventListener("keydown", e => {
    if (e.key !== "Escape" || !officeOpen()) return;
    const menus = [...root.querySelectorAll(".of-menu")].filter(m => !m.hidden);
    if (!$o("#ofZoom").hidden) $o("#ofZoom").hidden = true;
    else if (!$o("#ofPres").hidden) $o("#ofPres").hidden = true;
    else if (menus.length) menus.forEach(m => { m.hidden = true; });
    else if (!$o("#ofCard").hidden) $o("#ofCard").hidden = true;
    else closeOffice();
  });
  el.querySelector("#ofForm").onsubmit = e => {
    e.preventDefault();
    const inp = $o("#ofIn"), text = inp.value.trim(); if (!text) return;
    inp.value = "";
    O.ask(text, {room: teamById(chan) ? chan : "hq"}).then(r => { if (r?.error) ctx.toast(r.error); });
  };
}
/* ============ 캐릭터 움직임 (CSS transition만, 매 프레임 JS 없음) ============ */
function place(id, p, instant){
  const el = root?.querySelector(`[data-ag="${id}"]`); if (!el || !p) return;
  const from = pos[id] || p, dist = Math.hypot(p.x - from.x, p.y - from.y);
  el.style.transitionDuration = instant ? "0s" : Math.min(3.2, 0.3 + dist / 190) + "s";
  el.classList.toggle("flip", p.x < from.x - 2);
  if (!instant && dist > 4){ el.classList.add("walk"); clearTimeout(el._w); el._w = setTimeout(() => el.classList.remove("walk"), Math.min(3200, 300 + dist / 0.19)); }
  el.style.left = p.x + "px"; el.style.top = p.y + "px"; el.style.zIndex = Math.round(p.y);
  el.classList.toggle("edge-r", p.x > W - 140); el.classList.toggle("edge-l", p.x < 140);
  pos[id] = {x: p.x, y: p.y};
}
function bubble(id, text, ms){
  const el = root?.querySelector(`[data-ag="${id}"] .of-bub`); if (!el) return;
  clearTimeout(el._t);
  el.classList.remove("big");
  if (!text){ el.hidden = true; return; }
  el.textContent = text; el.hidden = false;
  if (ms) el._t = setTimeout(() => { el.hidden = true; }, ms);
}
const tail = (s, n = 120) => { const t = String(s).replace(/[#*_`>|]/g, "").replace(/\s+/g, " ").trim(); return t.length > n ? "…" + t.slice(-n) : t; };
const head = (s, n = 110) => { const t = String(s).replace(/[#*_`>|]/g, "").replace(/\s+/g, " ").trim(); const first = t.split(/(?<=[.!?。다요])\s/)[0]; return (first.length > n ? first.slice(0, n) + "…" : first) || t.slice(0, n); };
const busyNow = id => seatOf[id] !== undefined || huddle.has(id) || onStage.has(id);
// 7초마다 한 명만 움직인다
async function idle(){
  if (!root || root.hidden) return;
  for (const id of Object.keys(away)) if (Date.now() > away[id]){ delete away[id]; if (!busyNow(id)) place(id, HOME[id]); }
  const free = AGENTS.filter(a => !busyNow(a.id) && !away[a.id]);
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
  const o = await O.work(a.id).catch(() => null);
  if (busyNow(a.id)) return;
  bubble(a.id, o ? `${o.icon} ${o.text}`.trim() : idleLine(a), o ? 7000 : 4000);
}
/* ============ 회의 · 발표 이벤트 ============ */
function setTable(place, on){
  root.querySelectorAll(".of-mtable.on").forEach(t => t.classList.remove("on"));
  root.querySelectorAll(".of-zone.meeting").forEach(z => z.classList.remove("meeting"));
  if (!on) return;
  root.querySelector(`[data-mt="${place}"]`)?.classList.add("on");
  root.querySelector(`[data-z="${place}"]`)?.classList.add("meeting");
}
function seatNew(id){ const i = Object.keys(seatOf).length; seatOf[id] = i; onStage.delete(id); delete away[id]; place(id, seatAt(meetPlace, i)); }
function onEvent(ev){
  if (!root) return;
  const m = ev.meeting;
  if (ev.kind === "log"){ if (inChan(ev.entry)) appendEntry(ev.entry); return; }
  if (ev.kind === "cleared"){ renderLog(); return; }
  if (ev.kind === "cfg" || ev.kind === "usage"){ renderStatus(); return; }
  if (ev.kind === "docs"){ const db = $o("#ofDocs"); if (db && !db.hidden) openDocs(true); }
  if (ev.kind === "growth" || (ev.kind === "log" && ev.entry?.kind === "patch")){ renderGrowthCount(); if (chan === "growth") renderLog(); if (ev.kind === "growth") return; }
  if (ev.kind === "present"){ present(ev.report); return; }
  if (ev.kind === "start"){
    seatOf = {}; meetPlace = placeOf(m.place);
    let ids = [...new Set(m.order)];
    if (meetPlace === "stage" && ids.includes(CEO)) ids = [CEO, ...ids.filter(x => x !== CEO)];
    ids.forEach((id, i) => { seatOf[id] = i; onStage.delete(id); delete away[id]; setTimeout(() => { place(id, seatAt(meetPlace, i)); bubble(id, i ? "회의 들어갑니다" : "회의 시작할게요", 2500); }, i * 250); });
    setTable(meetPlace, true); showPlace(meetPlace);
    $o("#ofBoard").textContent = `#${m.name} · ${placeName(meetPlace)}`;
  }
  if (ev.kind === "join"){ seatNew(ev.agent.id); bubble(ev.agent.id, "부르셨어요? 갑니다", 2500); }
  if (ev.kind === "turn"){ clearBubbles(ev.agent.id); speaking = ev.agent.id; if (!(ev.agent.id in seatOf)) seatNew(ev.agent.id); bubble(ev.agent.id, "💭 생각 중…", 0); highlight(ev.agent.id); }
  if (ev.kind === "tool" || ev.kind === "delta"){ bubble(ev.agent.id, liveBubble(ev.entry), 0); updateEntry(ev.entry); }
  if (ev.kind === "huddle"){
    clearBubbles(); const host = HOME[ev.host] || pos[ev.host];
    ev.ids.forEach((id, i) => { huddle.add(id); onStage.delete(id); delete away[id]; if (id !== ev.host) place(id, inWorld({x: host.x + (i % 2 ? 58 : -58) * Math.ceil(i / 2), y: host.y + 6})); else place(id, HOME[id]); });
  }
  if (ev.kind === "line"){ bubble(ev.agent.id, ev.entry.text.length > 150 ? ev.entry.text.slice(0, 150) + "…" : ev.entry.text, Math.min(9000, 2500 + ev.entry.text.length * 50)); highlight(ev.agent.id); setTimeout(() => highlight(null), 1800); }
  if (ev.kind === "huddle-end"){ ev.ids.forEach((id, i) => setTimeout(() => { huddle.delete(id); if (seatOf[id] === undefined && !onStage.has(id)) place(id, HOME[id]); }, 3000 + i * 300)); }
  if (ev.kind === "said"){ bubble(ev.agent.id, head(ev.entry.text), 6000); updateEntry(ev.entry); highlight(null); }
  if (ev.kind === "end"){
    const ids = Object.keys(seatOf); seatOf = {}; speaking = null; highlight(null);
    ids.forEach((id, i) => setTimeout(() => { if (seatOf[id] !== undefined || huddle.has(id) || onStage.has(id)) return; bubble(id, ""); place(id, HOME[id]); }, 3500 + i * 200));
    setTimeout(() => { if (!Object.keys(seatOf).length) setTable(null, false); }, 3500);
    $o("#ofBoard").textContent = "회의 끝 · 회의록은 오른쪽";
  }
  if (ev.kind === "cycle"){ curJob = ev.label || "업무"; $o("#ofBoard").textContent = "지금: " + curJob; renderStatus(); }
  if (ev.kind === "cycle-end"){ curJob = ""; renderStatus(); }
  if (ev.kind === "busy" || ev.kind === "bubble"){ if (!busyNow(ev.agent.id)){ delete away[ev.agent.id]; place(ev.agent.id, HOME[ev.agent.id]); } bubble(ev.agent.id, ev.text, ev.kind === "busy" ? 0 : 7000); }
  if (ev.kind === "solo"){ bubble(ev.agent.id, "💭 생각 중…", 0); highlight(ev.agent.id); }
  if (ev.kind === "trade"){ bubble(ev.agent.id, ev.text.length > 140 ? ev.text.slice(0, 140) + "…" : ev.text, 9000); refreshBoard(); }
  if (ev.kind === "paper") refreshBoard();
  if (ev.kind === "alert"){ ctx.toast(`팀 회의 결과 · #${m.name}: ${head(ev.text, 60)}`); if (document.hidden && "Notification" in window && Notification.permission === "granted") new Notification("GH Nano 팀 회의 · #" + m.name, {body: head(ev.text, 120)}); }
  renderStatus();
}
// 시간별 성과 발표: CEO가 무대로 나가고 팀장들이 객석에 모인다 (30초 뒤 자리로)
function present(r){
  if (!r) return;
  if (r.id) repCache[r.id] = r;
  const hr = new Date(r.t || Date.now()).getHours(), label = `📢 ${hr}시 성과 발표`;
  returnFromStage();
  clearTimeout(presentT);
  $o("#ofStageScr").innerHTML = `<b>${label}</b><span>${E(r.title || "")}</span>`;
  root.querySelector('[data-z="stage"]')?.classList.add("onair"); showPlace("stage");
  if (!busyNow(CEO)){ onStage.add(CEO); delete away[CEO]; place(CEO, STG.podium); }
  bubble(CEO, label, 20000); root.querySelector(`[data-ag="${CEO}"] .of-bub`)?.classList.add("big"); highlight(CEO);
  TEAMS.filter(t => t.id !== "hq").map(t => LEAD_OF[t.id]).filter(id => id && !busyNow(id)).forEach((id, i) => {
    onStage.add(id); delete away[id]; bubble(id, "");
    setTimeout(() => { if (onStage.has(id)) place(id, STG.seats[i] ? inWorld(STG.seats[i]) : seatAt("stage", i + 1)); }, 300 + i * 160);
  });
  ctx.toast(`${label} · ${r.title || ""}`);
  if (officeOpen()) openPres(r);
  presentT = setTimeout(() => { returnFromStage(); highlight(null); }, 30000);
}
function returnFromStage(){
  [...onStage].forEach((id, i) => { onStage.delete(id); if (!busyNow(id)) setTimeout(() => { if (!busyNow(id)) place(id, HOME[id]); }, i * 150); });
  root.querySelector('[data-z="stage"]')?.classList.remove("onair");
}
const TOOL_ICON = {market_analyze: "📈", market_quote: "💹", market_news: "📰", web_search: "🔎", web_fetch: "📄", econ_calendar: "🗓", calculate: "🧮", backtest: "🧪", nv_skill_search: "🟩", nv_skill_read: "🟩"};
// 말풍선: 말하는 중이면 말, 도구를 쓰는 중이면 무엇을 보는지, 아니면 속마음
function liveBubble(e){
  const st = e.steps?.at(-1);
  if (e.text) return "🗣 " + tail(e.text, 140);
  if (st && st.status === "running") return `${TOOL_ICON[st.name] || "🔧"} ${st.act} 하는 중…`;
  if (st && st.status === "done") return `${TOOL_ICON[st.name] || "✅"} ${st.act}${st.summary ? " → " + st.summary : ""}${st.sources?.[0] ? " · " + st.sources[0].title : ""}`.slice(0, 170);
  if (koT(e.think)) return "💭 " + koT(e.think);
  return "💭 생각 중…";
}
// 속마음은 한국어 한 줄만 (영어로 새어 나온 생각·옛 기록은 보여 주지 않음)
function koT(t){ t = String(t || "").replace(/\s+/g, " ").trim(); if (!t || !/[\uac00-\ud7a3]/.test(t)) return ""; const lat = (t.match(/[A-Za-z]/g) || []).length, han = (t.match(/[\uac00-\ud7a3]/g) || []).length; if (lat > 25 && han < lat * 0.15) return ""; return t.length > 120 ? t.slice(0, 118) + "…" : t; }
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
  list.innerHTML = act.sort((x, y) => pct(y) - pct(x)).slice(0, 8).map(s => `<div><span>${ctx.esc(s.name).slice(0, 18)}</span><small>${ctx.esc((s.mname || s.market).replace("USDT", "").slice(0, 10))} x${s.spec?.risk?.leverage ?? "?"} ${s.pos ? (s.pos.side === "long" ? "롱" : "숏") : "대기"}</small><i class="${pct(s) >= 0 ? "up" : "dn"}">${pct(s) >= 0 ? "+" : ""}${pct(s).toFixed(2)}%</i></div>`).join("");
}
function highlight(id){ root.querySelectorAll(".of-ag.talk").forEach(e => e.classList.remove("talk")); if (id) root.querySelector(`[data-ag="${id}"]`)?.classList.add("talk"); }
let curJob = "";
function renderStatus(){
  if (!root) return;
  const s = O.officeState(), c = O.officeCfg(), u = O.officeUsage();
  const m = s.running;
  $o("#ofLed").className = "of-led" + (m ? " on" : "");
  $o("#ofTitle").textContent = m ? `회의 · #${m.name}` : "대기 중";
  $o("#ofRec").classList.toggle("on", !!m); $o("#ofRecL").textContent = m ? `녹화 중 · ${placeName(placeOf(m.place))}` : "기록됨";
  $o("#ofMode").textContent = m ? "회의 중" : c.auto ? "자동 운영" : "대기";
  $o("#ofStop").hidden = !m; $o("#ofAuto").checked = !!c.auto; $o("#ofEvery").value = String(c.every); $o("#ofChat").checked = c.chat !== false; $o("#ofCycle").checked = c.cycle !== false; $o("#ofComp").checked = c.computer !== false; $o("#ofTrain").checked = c.train !== false;
  const sp = $o("#ofSpeed"), cm = String(c.cycleMin ?? 3);
  if (![...sp.options].some(o => o.value === cm)) sp.insertAdjacentHTML("beforeend", `<option value="${E(cm)}">업무 ${E(cm)}분</option>`);
  if (document.activeElement !== sp) sp.value = cm;
  if (document.activeElement !== $o("#ofClaude")) $o("#ofClaude").value = claudeMode(c);
  const next = O.nextAutoIn();
  const ps = O.officePaused?.() || 0;
  const jobNow = (ps ? `<span class="of-jobnow">⏸ AI 한도 때문에 ${Math.ceil(ps / 60e3)}분 쉬는 중 (질문은 받음)</span> · ` : "") + (curJob ? `<span class="of-jobnow">▶ 지금 하는 일: ${E(curJob)}</span> · ` : "");
  $o("#ofStatus").innerHTML = jobNow + (m ? `<b class="ok">진행 중</b> · ${placeName(placeOf(m.place))} · ${m.done.length}/${m.order.length} 발언${s.queued ? ` · 대기 회의 ${s.queued}개` : ""}`
    : c.auto ? (u.auto >= c.dailyMax ? `오늘 자동 회의 ${c.dailyMax}번을 다 했습니다 · 메시지를 보내면 바로 회의합니다` : `다음 자동 회의 ${next > 60e3 ? Math.round(next / 60e3) + "분 뒤" : "곧"} · 급변동 감시 중`) : "자동 회의 꺼짐 · 메시지를 보내면 바로 회의합니다");
  const nc = O.nextChatIn();
  const nx = O.nextCycleIn(), cs = O.cycleState(), cu = provUse().n.anthropic || 0, cap = provCapOf("anthropic");
  const cmode = claudeMode(c);
  $o("#ofFoot").innerHTML = `${c.cycle !== false ? `${c.cycleMin}분 주기 ${cs.cycling ? "일하는 중" : `다음 ${nx > 60e3 ? Math.ceil(nx / 60e3) + "분" : "곧"}`} · ` : ""}${settings.keys.anthropic ? `Claude(${cmode === "all" ? "전원" : cmode === "key" ? "핵심 자리" : "안 씀"}) 오늘 ${cu}/${cap}번 <button id="ofCap" class="of-link">한도 바꾸기</button> · ` : `<button id="ofCapKey" class="of-link">Claude 키 넣기</button> · `}${c.train !== false ? `오늘 학습 예시 +${u.trained || 0} · ` : ""}오늘 회의 ${u.meetings || 0}번 (자동 ${u.auto || 0}/${c.dailyMax}) · 수다 ${u.chats || 0}/${c.chatMax}${c.chat ? (O.isChatting() ? " (지금 대화 중)" : ` (다음 ${nc > 60e3 ? Math.round(nc / 60e3) + "분" : "곧"})`) : ""} · AI 호출 ${u.calls || 0}번 · <button id="ofClear" class="of-link">기록 지우기</button>`;
}
/* ============ 회의록 패널 ============ */
// #전체: 회의·수다·보고·내 메시지 / #업무: 직원들이 본 차트·뉴스 / #성장 과제: 과제 보드 / 팀 방: 그 팀의 모든 것
const inChan = e => chan === "all" ? e.kind !== "work" : chan === "work" ? e.kind === "work" : chan === "growth" ? false : e.ch === chan;
async function renderLog(){
  const box = $o("#ofLog");
  if (chan === "growth"){ box.innerHTML = growthHTML(); renderGrowthCount(); return; }
  const log = await O.loadLog();
  if (chan === "growth") return;
  const list = log.filter(inChan).slice(-160);
  box.innerHTML = list.length ? "" : `<div class="of-empty"><b>아직 회의가 없습니다</b><p>아래에 무엇이든 보내면 팀장이 담당자를 불러 회의를 엽니다. 코인·주식·선물·부동산·건축·퀀트·신사업·코딩·일상 대화 모두 됩니다.</p><p>자동 회의를 켜 두면 팀이 정해진 간격과 급변동 때 스스로 회의하고, 매시 CEO가 성과를 발표합니다.</p></div>`;
  list.forEach(appendEntry);
  renderGrowthCount();
}
const safeUrl = u => /^https?:\/\//i.test(String(u || "")) ? String(u) : "";
const link = (url, label) => safeUrl(url) ? `<a href="${ctx.esc(url)}" target="_blank" rel="noopener noreferrer">${ctx.esc(label)}</a>` : ctx.esc(label);
const num = v => v == null || v === "" ? "—" : Number.isFinite(+v) ? (+v).toLocaleString("ko-KR", {maximumFractionDigits: 2}) : E(v);
const pctOf = v => v == null || v === "" || !Number.isFinite(+v) ? null : Math.abs(+v) <= 1 ? +v * 100 : +v;
const pct = v => { const p = pctOf(v); return p == null ? "—" : p.toFixed(1) + "%"; };
const hm = t => new Date(t).toLocaleTimeString("ko-KR", {hour: "2-digit", minute: "2-digit"});
const when = t => { if (t == null || t === "") return ""; const d = typeof t === "number" ? new Date(t) : new Date(String(t)); return isNaN(d) ? String(t) : d.toLocaleString("ko-KR", {month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit"}); };
const who = a => `<b style="color:${tc(a.team)}">${isLead(a) ? "♛ " : ""}${E(a.name)}</b>`;
const kcard = (a, title, time, body, cls = "") => `<div class="of-kc ${cls}" style="--tc:${tc(a.team)}"><div class="of-kch"><b>${title}</b><span>${a.id ? `${E(a.name)} · ${E(a.title)} · ` : ""}${time}</span></div>${body}</div>`;
const officePath = p => `<code title="문서/GHNano 사무실/${E(p)}">${E(p)}</code>`;
function stepsHTML(e){
  if (!e.steps?.length) return "";
  return `<ul class="of-steps">${e.steps.map(st => `<li class="${st.status}"><span>${TOOL_ICON[st.name] || "🔧"} ${ctx.esc(st.act || "")}</span>${st.status === "running" ? ` <em>하는 중…</em>` : st.status === "error" ? ` <em class="bad">실패: ${ctx.esc(String(st.err || "").slice(0, 60))}</em>` : st.summary ? ` <em>→ ${ctx.esc(st.summary)}</em>` : ""}${st.sources?.length ? `<div class="of-src">${st.sources.slice(0, 4).map(x => "📰 " + link(x.url, String(x.title || x.url).slice(0, 70))).join("<br>")}</div>` : ""}</li>`).join("")}</ul>`;
}
const STATUS_KO = {todo: "등록", doing: "시작", done: "완료"};
function entryHTML(e){
  if (e.kind === "divider") return `<div class="of-div${e.chat ? " chat" : ""}">— ${ctx.esc(e.text)} —</div>`;
  if (e.kind === "system") return `<div class="of-sys">${ctx.esc(e.text)}</div>`;
  const time = hm(e.t);
  if (e.kind === "user") return `<div class="of-msg me"><div class="of-av me">나</div><div class="of-mb"><div class="of-who"><b>나</b><span>#${ctx.esc(teamById(e.ch)?.name || "")} · ${time}</span></div><div class="of-tx">${ctx.esc(e.text)}</div></div></div>`;
  const a = agentById(e.agent) || {name: "", title: "", team: e.ch || "hq", look: ["#999", "#999"]};
  if (e.kind === "trade") return `<div class="of-work of-trade"><b style="color:${tc("quant")}">${E(agentById("trader")?.name || "트레이더")}</b> <span>${ctx.esc(e.text)}</span><time>${time}</time></div>`;
  if (e.kind === "bt"){
    const row = (k, x) => `<tr><th>${k}</th><td class="${x.ret >= 0 ? "up" : "dn"}">${x.ret >= 0 ? "+" : ""}${x.ret.toFixed(1)}%</td><td>${x.dd.toFixed(1)}%</td><td>${x.win.toFixed(0)}%</td><td>${x.pf == null ? "—" : x.pf.toFixed(2)}</td><td>${x.n}</td></tr>`;
    return `<div class="of-bt ${e.pass ? "pass" : "fail"}"><div class="of-bth"><b>${e.pass ? "✅ 검증 통과" : "❌ 불통과"} · ${ctx.esc(e.name)}</b><span>${ctx.esc(e.mname || e.market)} ${e.tf === "60" ? "1시간" : e.tf === "240" ? "4시간" : e.tf === "D" ? "일" : e.tf}봉${e.lev ? ` · 레버리지 ${e.lev}배` : ""} · 개발 ${ctx.esc(e.author || "")} · 검증 ${E(agentById("val")?.name || "검증관")} · ${time}</span>${e.hist ? `<span>과거 데이터: ${ctx.esc(e.hist)}</span>` : ""}</div>
      <table><tr><th></th><th>수익</th><th>최대낙폭</th><th>승률</th><th>손익비</th><th>거래</th></tr>${row("전체", e.all)}${row("개발 70%", e.is)}${row("검증 30%", e.oos)}</table>
      <div class="of-btr">${(e.reasons || []).map(r => "· " + ctx.esc(r)).join("<br>")}</div>
      ${e.scen ? `<details open><summary>시나리오 (모든 레버리지 · 장세 · 연도 · 스트레스)</summary><pre>${ctx.esc(e.scen)}</pre></details>` : ""}
      <details><summary>전략 JSON</summary><pre>${ctx.esc(JSON.stringify(e.spec, null, 1)).slice(0, 4000)}</pre></details></div>`;
  }
  if (e.kind === "work") return `<div class="of-work"><b style="color:${tc(a.team)}">${E(a.name)}</b> <span>${ctx.esc(e.icon || "")} ${e.url ? link(e.url, e.text) : ctx.esc(e.text)}${e.src ? ` <small>· ${ctx.esc(e.src)}</small>` : ""}</span><time>${time}</time></div>`;
  // ---- 새 기록 종류 ----
  if (e.kind === "report"){
    const lines = String(e.text || "").split("\n").filter(l => l.trim()).slice(0, 6).join("\n");
    const ceo = agentById(CEO);
    return `<div class="of-kc of-rep" style="--tc:${tc("hq")}" data-e="${e.id}"><div class="of-kch"><b>📢 시간별 성과 발표 · ${E(e.title)}</b><span>CEO ${E(ceo?.name || "")} · ${time}</span></div>${lines ? `<div class="of-kmd md">${ctx.md(lines)}</div>` : ""}<button class="of-btn2" data-report="${E(e.reportId || "")}">발표 전체 보기</button></div>`;
  }
  if (e.kind === "re"){
    const rows = (e.items || []).map(it => `<tr><td><b>${E(it.area)}</b>${it.region && it.region !== e.region ? `<small>${E(it.region)}</small>` : ""}</td><td>${E(it.project_type)}</td><td>${E(it.stage)}</td><td class="num"><b>${num(it.score)}</b><small>${num(it.certainty)} · ${num(it.upside)}</small></td><td>${(it.sources || []).slice(0, 2).map((s, k) => link(s.url, String(s.title || "근거 " + (k + 1)).slice(0, 26))).join("<br>") || "—"}</td></tr>`).join("");
    return kcard(a, `🏘 재개발 후보 · ${E(e.region)}`, time, `<div class="of-tw"><table class="of-kt"><tr><th>구역</th><th>사업</th><th>단계</th><th>점수<small>확실성 · 상승여력</small></th><th>근거</th></tr>${rows || `<tr><td colspan="5">후보 없음</td></tr>`}</table></div>`);
  }
  if (e.kind === "ml"){
    const ac = pctOf(e.acc), bs = pctOf(e.base), edge = ac != null && bs != null ? ac - bs : null;
    return kcard(a, `🧠 머신러닝 · ${E(e.market)} ${E(e.tf)} · ${E(e.model)}`, time, `<div class="of-kstats"><div><small>정확도</small><b class="${edge == null ? "" : edge > 0 ? "up" : "dn"}">${pct(e.acc)}</b></div><div><small>기준(동전)</small><b>${pct(e.base)}</b></div>${edge != null ? `<div><small>차이</small><b class="${edge > 0 ? "up" : "dn"}">${edge > 0 ? "+" : ""}${edge.toFixed(1)}%p</b></div>` : ""}<div><small>AUC</small><b>${e.auc == null || !Number.isFinite(+e.auc) ? "—" : (+e.auc).toFixed(3)}</b></div></div>${e.text ? `<pre class="of-kpre">${E(e.text)}</pre>` : ""}`);
  }
  if (e.kind === "macro"){
    const rows = (e.rows || []).map(r => { const ch = +r.change; return `<tr><td><b>${E(r.name)}</b>${r.date ? `<small>${E(r.date)}</small>` : ""}</td><td class="num">${num(r.latest)}${r.unit ? ` <small>${E(r.unit)}</small>` : ""}</td><td class="num ${Number.isFinite(ch) && ch ? ch > 0 ? "up" : "dn" : ""}">${Number.isFinite(ch) && ch > 0 ? "+" : ""}${num(r.change)}</td><td class="num"><b>${num(r.forecast)}</b></td><td class="num">${num(r.lo)} ~ ${num(r.hi)}</td></tr>`; }).join("");
    return kcard(a, "📊 경제지표 · 다음 예측(80% 구간)", time, `<div class="of-tw"><table class="of-kt"><tr><th>지표</th><th>최근</th><th>변화</th><th>예측</th><th>80% 구간</th></tr>${rows || `<tr><td colspan="5">데이터 없음</td></tr>`}</table></div>`);
  }
  if (e.kind === "forecast"){
    const AR = {up: ["▲", "up", "상승"], down: ["▼", "dn", "하락"], flat: ["■", "flat", "보합"]};
    const li = (e.items || []).map(it => { const d = AR[it.dir] || AR.flat; return `<li><i class="${d[1]}" title="${d[2]}">${d[0]}</i><b>${E(it.asset)}</b><span>${d[2]} ${pct(it.prob)}</span><small>${it.horizon ? E(it.horizon) + " · " : ""}${it.due ? "마감 " + E(when(it.due)) : ""}</small>${it.result === "hit" ? `<em class="hit">적중</em>` : it.result === "miss" ? `<em class="miss">빗나감</em>` : `<em>대기</em>`}</li>`; }).join("");
    const sc = e.score, rate = sc && sc.n ? (sc.hit / sc.n * 100).toFixed(0) : null;
    return kcard(a, "🔮 예측", time, `<ul class="of-fc">${li || "<li>예측 없음</li>"}</ul>${sc ? `<div class="of-kfoot">채점 ${num(sc.n)}건 · 적중 ${num(sc.hit)}${rate != null ? ` (${rate}%)` : ""}${sc.brier != null ? ` · Brier ${num(sc.brier)}` : ""}</div>` : ""}`);
  }
  if (e.kind === "arch"){
    const img = /^data:image\//.test(String(e.image || "")) || safeUrl(e.image) ? String(e.image) : "";
    const mt = e.metrics || {}, KO = {"대지_㎡": "대지", "건축면적_㎡": "건축면적", "연면적_㎡": "연면적", "건폐율%": "건폐율", "용적률%": "용적률", "층수": "층수"};
    const unit = k => /㎡/.test(k) ? "㎡" : /%/.test(k) ? "%" : k === "층수" ? "층" : "";
    const dl = Object.entries(mt).map(([k, v]) => `<div><small>${E(KO[k] || k)}</small><b>${num(v)}${unit(k)}</b></div>`).join("");
    const btn = e.spec && typeof ctx.openBuilding === "function" ? `<button class="of-btn2" data-build="${E(e.id)}">3D로 보기</button>` : "";
    return kcard(a, `🏗 설계안 · ${E(e.name)}`, time, `<div class="of-arch">${img ? `<img class="of-thumb" data-zoom src="${E(img)}" alt="${E(e.name)} 이미지">` : ""}<div>${dl ? `<div class="of-kstats">${dl}</div>` : ""}${e.files?.length ? `<div class="of-kfiles">💾 ${e.files.map(officePath).join(" ")}</div>` : ""}${btn}</div></div>`);
  }
  if (e.kind === "files") return `<div class="of-work of-files"><b style="color:${tc(a.team)}">${E(a.name)}</b> <span>💾 ${E(e.title || "파일 저장")}: ${(e.files || []).map(officePath).join(" ")}${e.note ? ` <small>· ${E(e.note)}</small>` : ""} <small>(문서/GHNano 사무실)</small></span><time>${time}</time></div>`;
  if (e.kind === "task") return `<div class="of-work of-task ${E(e.status)}"><b style="color:${tc(a.team)}">${E(a.name)}</b> <span>🌱 과제 ${E(STATUS_KO[e.status] || e.status || "")}: ${E(e.title)}${e.result ? ` — ${E(e.result)}` : ""}</span><time>${time}</time></div>`;
  if (e.kind === "biz"){
    const s = e.sim || {};
    const cell = (k, v) => `<div><small>${k}</small><b>${v}</b></div>`;
    const prof = +s.profit;
    return kcard(a, `💼 사업 시뮬레이션 · ${E(e.name)}`, time, `<div class="of-kstats">${cell("기간", s.months != null ? num(s.months) + "개월" : "—")}${cell("매출", num(s.revenue))}<div><small>이익</small><b class="${Number.isFinite(prof) ? prof >= 0 ? "up" : "dn" : ""}">${num(s.profit)}</b></div>${cell("손익분기", s.breakeven_month != null ? num(s.breakeven_month) + "개월차" : "도달 못 함")}${cell("런웨이", s.runway != null ? num(s.runway) + "개월" : "—")}${s.irr != null ? cell("IRR", pct(s.irr)) : ""}</div>${e.verdict ? `<p class="of-kv">${E(e.verdict)}</p>` : ""}${e.plan ? `<div class="of-kfoot">📝 사업계획서 작성됨</div>` : ""}`);
  }
  if (e.kind === "patch") return `<div class="of-work of-patch ${E(e.status || "")}"><b style="color:${tc(a.team)}">${E(a.name)}</b> <span>🛠 ${E(e.file || "")} ${e.status === "proposed" ? "수정안 준비됨 · 대표님 승인 대기" : e.status === "applied" ? "수정 적용됨" : "수정 못 함"}${e.why ? ` — ${E(e.why)}` : ""}</span> <button class="of-btn2" data-ch="growth">코드 개선 보기</button><time>${time}</time></div>`;
  if (e.kind === "live") return `<div class="of-real ${e.level === "warn" ? "warn" : "info"}">💰 실거래 · ${E(e.text)}<time>${time}</time></div>`;
  if (e.chat) return `<div class="of-msg chat"><div class="of-av sm">${sprite(a)}</div><div class="of-mb"><div class="of-who">${who(a)}<span>${E(a.title)}</span></div><div class="of-tx">${ctx.esc(e.text)}</div></div></div>`;
  if (e.kind && e.kind !== "agent" && !e.text) return `<div class="of-sys">${E(e.kind)} 기록</div>`;
  const body = e.text ? ctx.md(e.text) : e.steps?.length ? "" : e.live ? `<span class="of-typing">생각 중<i>.</i><i>.</i><i>.</i></span>` : "";
  return `<div class="of-msg${e.live ? " of-live" : ""}" data-e="${e.id}"><div class="of-av">${sprite(a)}</div><div class="of-mb"><div class="of-who">${who(a)}<span>${E(a.title)}${e.model ? " · " + ctx.esc(shortModel(e.model)) : ""} · ${time}</span></div>
    ${e.notes?.length ? `<div class="of-note">${e.notes.map(n => "↻ " + ctx.esc(n)).join("<br>")}</div>` : ""}
    ${koT(e.think) ? `<div class="of-think">💭 ${ctx.esc(koT(e.think))}</div>` : ""}
    ${stepsHTML(e)}
    ${body ? `<div class="of-tx md">${body}</div>` : ""}<div class="of-acts"><button class="of-link" data-more>펼치기 · 접기</button>${!e.live && e.text ? `<button class="of-rate${e.rating > 0 ? " on" : ""}" data-rate="1" title="좋은 발언 · GH Nano 학습에 우선 사용">👍</button><button class="of-rate${e.rating < 0 ? " on" : ""}" data-rate="-1" title="나쁜 발언 · 학습 데이터에서 뺌">👎</button>${e.trainIds?.length ? `<span class="of-trn" title="이 발언으로 GH Nano 학습 예시를 만들었습니다">🎓 학습 예시</span>` : ""}` : ""}</div></div></div>`;
}
function appendEntry(e){
  const box = $o("#ofLog"); if (!box || chan === "growth") return;
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
/* ============ 📁 결과물 보관함 ============ */
let docList = [], docFilter = "all", docSel = null;
const DOC_KIND = [["all", "전체"], ["business", "사업계획서"], ["reports", "보고서"], ["strategies", "매매법"], ["designs", "설계안"], ["realestate", "부동산"], ["ventures", "신사업 파일"], ["etc", "기타"]];
const kindOfDoc = d => { const p = String(d.path || "").replace(/^ghcoin\//, ""); const k = p.split("/")[0]; return DOC_KIND.some(x => x[0] === k) ? k : "etc"; };
async function openDocs(keep){
  let box = $o("#ofDocs");
  if (!box){ root.insertAdjacentHTML("beforeend", `<div class="of-docs" id="ofDocs" hidden><div class="of-docsbox"><div class="of-docsh"><b>📁 결과물 보관함</b><span id="ofDocsSub"></span><span class="of-sp"></span><button class="of-btn2" data-docfolder="">📂 폴더 열기</button><button class="of-x" data-docclose aria-label="닫기">✕</button></div><div class="of-docsf" id="ofDocsF"></div><div class="of-docsb"><div class="of-docsl" id="ofDocsL"></div><div class="of-docsv" id="ofDocsV"></div></div></div></div>`); box = $o("#ofDocs"); }
  box.hidden = false;
  docList = await (O.listDocs ? O.listDocs() : []);
  const n = k => k === "all" ? docList.length : docList.filter(d => kindOfDoc(d) === k).length;
  $o("#ofDocsSub").textContent = `${docList.length}개 · ${LAUNCHER.on ? "앱 안 보관 + 문서/GHNano 사무실" + (O.TEAMS?.length > 20 ? "/ghcoin" : "") + " 폴더" : "앱 안에 보관 (웹 버전)"}`;
  $o("#ofDocsF").innerHTML = DOC_KIND.filter(([k]) => k === "all" || n(k)).map(([k, l]) => `<button data-docfilter="${k}" aria-pressed="${k === docFilter}">${l} <small>${n(k)}</small></button>`).join("");
  const list = docList.filter(d => docFilter === "all" || kindOfDoc(d) === docFilter);
  $o("#ofDocsL").innerHTML = list.map(d => `<button class="of-doci" data-docview="${E(d.id)}" aria-pressed="${d.id === docSel}"><b>${E(d.title)}</b><small>${E(d.path || "")} · ${E(when(d.t))} · ${(d.size / 1024).toFixed(1)}KB</small></button>`).join("")
    || `<div class="of-empty"><b>아직 결과물이 없습니다</b><p>사업계획서·시간별 보고서·검증 통과한 매매법·설계안·직원이 만든 파일이 생기면 여기에 쌓입니다.</p></div>`;
  if (!keep || !list.some(d => d.id === docSel)) docSel = list[0]?.id || null;
  if (docSel) showDoc(docSel); else $o("#ofDocsV").innerHTML = "";
}
function showDoc(id){
  docSel = id; root.querySelectorAll("#ofDocsL [data-docview]").forEach(b => b.setAttribute("aria-pressed", b.dataset.docview === id));
  const d = docList.find(x => x.id === id), v = $o("#ofDocsV"); if (!d){ v.innerHTML = ""; return; }
  const body = /markdown/.test(d.mime) ? `<div class="md">${ctx.md(d.content || "")}</div>` : `<pre>${E(String(d.content || "").slice(0, 200000))}</pre>`;
  const dir = String(d.path || "").split("/").slice(0, -1).join("/");
  v.innerHTML = `<div class="of-docvh"><b>${E(d.title)}</b><span>${E(d.path || "")}</span><div class="of-pbtn"><button class="of-btn2" data-docdl="${E(d.id)}">⬇ 내려받기</button>${LAUNCHER.on && dir ? `<button class="of-btn2" data-docfolder="${E(dir)}">📂 이 폴더 열기</button>` : ""}<button class="of-btn2" data-docdel="${E(d.id)}">지우기</button></div></div>${body}`;
  v.scrollTop = 0;
}
function dlDoc(id){
  const d = docList.find(x => x.id === id); if (!d) return;
  const name = String(d.path || d.title).split("/").pop() || "결과물.md", bom = /csv/.test(d.mime) ? "\ufeff" : "";
  const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([bom + (d.content || "")], {type: (d.mime || "text/plain") + ";charset=utf-8"})); a.download = /\.\w+$/.test(name) ? name : name + ".md";
  a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 3000); ctx.toast("내려받았습니다: " + a.download);
}
/* ============ 성장 과제 보드 ============ */
const backlogItems = () => { if (!has("backlog")) return []; try { return O.backlog() || []; } catch(e){ return []; } };
function renderGrowthCount(){
  const n = backlogItems().filter(x => x.status !== "done").length, el = $o("#ofGrowN");
  if (el) el.textContent = n ? ` ${n}` : "";
}
// 🛠 코드 개선: AI·개발팀이 만든 수정안 → 대표 승인 → 적용 (되돌리기 가능)
const PST = {proposed: ["승인 대기", "wait"], applied: ["적용됨", "ok"], rejected: ["버림", "off"], reverted: ["되돌림", "off"], invalid: ["검사 탈락", "bad"]};
function codeHTML(){
  const pats = SD.listPatches().slice().sort((x, y) => (y.t || 0) - (x.t || 0)), errs = SD.recentErrors(8);
  const show = pats.filter(p => p.status !== "invalid").slice(0, 12), bad = pats.filter(p => p.status === "invalid").slice(0, 8);
  const clip = (t, n = 20) => { const l = String(t || "").split("\n"); return E(l.slice(0, n).join("\n")) + (l.length > n ? `\n… (${l.length - n}줄 더)` : ""); };
  const one = p => `<div class="of-gi of-pt" style="--tc:#5b8cff"><div class="of-gih"><b>🛠 ${E(p.file)}</b><span class="of-pst ${PST[p.status]?.[1] || ""}">${E(PST[p.status]?.[0] || p.status)}${p.auto ? " · 자동" : ""}</span><span>${E(when(p.t))}</span></div>
    ${p.why ? `<p>${E(p.why)}</p>` : ""}${p.error?.msg ? `<p class="of-dim">고치려는 오류: ${E(p.error.msg)} (${p.error.count || 1}번)</p>` : ""}
    ${p.find ? `<pre class="of-diff"><del>${clip(p.find)}</del><ins>${clip(p.replace)}</ins></pre>` : ""}<p class="of-dim">${E(p.check?.msg || "")}</p>
    <div class="of-pbtn">${p.status === "proposed" && p.check?.ok ? (LAUNCHER.on ? `<button class="of-btn2" data-papply="${E(p.id)}">적용</button>` : `<button class="of-btn2" data-pdl="${E(p.id)}">수정안 내려받기</button><small>웹 버전에서는 적용할 수 없습니다 (GHNano.exe)</small>`) : ""}${p.status === "proposed" ? `<button class="of-btn2" data-preject="${E(p.id)}">버리기</button>` : ""}${p.status === "applied" && LAUNCHER.on ? `<button class="of-btn2" data-prevert="${E(p.id)}">되돌리기</button>` : ""}</div></div>`;
  return `<section class="g-code"><h4>🛠 코드 개선 <span>${pats.filter(p => p.status === "proposed").length}</span></h4>
    <p class="of-dim">AI·개발팀이 앱에서 난 오류를 찾아 고치는 수정안입니다. 실거래·키·안전장치 파일은 고치지 않고, 대표님이 [적용]을 눌러야 반영됩니다. 적용 뒤 앱이 안 열리면 자동으로 되돌립니다.</p>
    ${show.map(one).join("") || `<p class="of-dim">아직 수정안이 없습니다${errs.length ? "" : " · 최근 오류도 없습니다"}</p>`}
    ${bad.length ? `<details><summary>검사에서 탈락한 수정안 ${bad.length}개</summary>${bad.map(one).join("")}</details>` : ""}
    ${errs.length ? `<details><summary>최근 오류 ${errs.length}개</summary>${errs.map(x => `<p class="of-dim">· ${E(x.file)}${x.line ? ":" + x.line : ""} — ${E(x.msg)} (${x.count}번)</p>`).join("")}</details>` : ""}</section>`;
}
function growthHTML(){
  return codeHTML() + taskHTML();
}
function taskHTML(){
  const items = backlogItems();
  if (!items.length) return `<div class="of-empty"><b>아직 성장 과제가 없습니다</b><p>직원들이 일하다가 '더 잘하려면 무엇이 필요한지'를 과제로 올리고, 하나씩 맡아 해결합니다. 진행 상황이 여기에 쌓입니다.</p></div>`;
  const GR = [["doing", "🔨 진행 중"], ["todo", "📋 할 일"], ["done", "✅ 완료"]];
  return `<div class="of-grow">${GR.map(([k, label]) => {
    const list = items.filter(x => (x.status || "todo") === k).sort((x, y) => (y.t || 0) - (x.t || 0)).slice(0, k === "done" ? 30 : 60);
    return `<section class="g-${k}"><h4>${label} <span>${items.filter(x => (x.status || "todo") === k).length}</span></h4>${list.map(it => {
      const o = agentById(it.owner), team = it.team || o?.team;
      return `<div class="of-gi" style="--tc:${tc(team)}"><div class="of-gih"><b>${E(it.title)}</b><span>${E(teamById(team)?.name || team || "")}${o ? ` · ${isLead(o) ? "♛ " : ""}${E(o.name)}` : it.owner ? ` · ${E(it.owner)}` : ""}${it.t ? ` · ${E(when(it.t))}` : ""}</span></div>${it.why ? `<p>${E(it.why)}</p>` : ""}${k === "done" && it.result ? `<p class="res">→ ${E(it.result)}</p>` : ""}</div>`;
    }).join("") || `<p class="of-dim">없음</p>`}</section>`;
  }).join("")}</div>`;
}
/* ============ 시간별 성과 발표 창 ============ */
let presSel = null, presList = [];
async function openPres(want){
  const box = $o("#ofPres"); box.hidden = false;
  if (want && typeof want === "object" && want.id) repCache[want.id] = want;
  let list = [];
  if (has("listReports")){ try { list = (await O.listReports()) || []; } catch(e){ list = []; } }
  for (const r of Object.values(repCache)) if (!list.some(x => x.id === r.id)) list.push(r);
  if (typeof want === "string" && !list.some(x => x.id === want)){
    const en = (await O.loadLog()).find(x => x.kind === "report" && x.reportId === want);
    if (en) list.push({id: want, t: en.t, title: en.title, text: en.text, sections: []});
  }
  presList = list.sort((x, y) => (y.t || 0) - (x.t || 0));
  presSel = (want && typeof want === "object" ? want.id : want) || presList[0]?.id || null;
  $o("#ofPresNow").hidden = !has("presentNow");
  $o("#ofPresSub").textContent = presList.length ? `지난 발표 ${presList.length}개` : "";
  $o("#ofPresList").innerHTML = presList.map(r => `<button data-rep="${E(r.id)}" aria-pressed="${r.id === presSel}"><b>${E(when(r.t))}</b><span>${E(r.title || "성과 발표")}</span></button>`).join("");
  $o("#ofPresList").hidden = presList.length < 2;
  showReport(presSel);
}
function showReport(id){
  presSel = id;
  root.querySelectorAll("#ofPresList [data-rep]").forEach(b => b.setAttribute("aria-pressed", b.dataset.rep === id));
  const r = presList.find(x => x.id === id), v = $o("#ofPresView");
  v.innerHTML = r ? reportHTML(r) : `<div class="of-pempty"><b>아직 발표가 없습니다</b><p>매시 정각에 CEO가 팀장들의 보고를 모아 '이번 시간에 무엇을 했고 다음에 무엇을 할지' 발표합니다.</p></div>`;
  v.scrollTop = 0;
}
function reportHTML(r){
  const ceo = agentById(CEO), secs = r.sections || [];
  const cards = secs.map(s => {
    const t = teamById(s.team), ld = agentById(s.lead) || AGENTS.find(a => a.name === s.lead) || agentById(LEAD_OF[s.team]), items = s.items || [], next = s.next || [];
    return `<section class="of-rsec" style="--tc:${tc(s.team)}"><h4>${E(s.name || t?.name || s.team)}<span>♛ ${E(ld?.name || s.lead || "팀장")}${ld ? ` · ${E(ld.title)}` : ""}</span></h4>
      ${items.length ? `<b>이번 시간 성과</b><ul>${items.map(x => `<li>${E(x)}</li>`).join("")}</ul>` : `<p class="of-dim">이번 시간 보고된 성과 없음</p>`}
      ${next.length ? `<b>다음 할 일</b><ul class="nx">${next.map(x => `<li>${E(x)}</li>`).join("")}</ul>` : ""}</section>`;
  }).join("");
  return `<header class="of-rh"><h3>${E(r.title || "성과 발표")}</h3><span>${E(when(r.t))} · CEO ${E(ceo?.name || "")} 발표${secs.length ? ` · ${secs.length}개 팀` : ""}</span></header>
    ${cards ? `<div class="of-rsecs">${cards}</div>` : ""}
    ${r.text ? `<details class="of-rfull"${cards ? "" : " open"}><summary>발표문 전체</summary><div class="of-rtx md">${ctx.md(r.text)}</div></details>` : ""}`;
}
/* ============ 직원 카드 · 팀 구성 ============ */
// AI 모델 고르기 (직원·팀·전원). 비워 두면 자동: 연결된 모델 중 빠르고 큰 모델을 골고루 나눠 배정
function modelSelect(key, cur, label = "자동 (추천)"){
  const ch = typeof O.modelChoices === "function" ? O.modelChoices() : [];
  if (!ch.length) return `<span class="of-dim">먼저 AI 키를 연결하세요</span>`;
  const groups = {}; for (const m of ch) (groups[m.name] ||= []).push(m);
  return `<select class="of-msel" data-assign="${E(key)}"><option value="">${E(label)}</option>${Object.entries(groups).map(([g, ms]) => `<optgroup label="${E(g)}">${ms.map(m => { const v = m.id + "|" + m.model; return `<option value="${E(v)}"${v === cur ? " selected" : ""}>${E(shortModel(m.model))}</option>`; }).join("")}</optgroup>`).join("")}</select>`;
}
function showCard(id){
  const a = agentById(id), t = teamById(a.team), mdl = O.assignModels()[id];
  const sk = (a.skills || []).map(s => BUILTIN_SKILLS.find(b => b.id === s)?.name || s);
  const c = $o("#ofCard");
  c.innerHTML = `<div class="of-cardh"><div class="of-av big">${sprite(a)}</div><div><b>${isLead(a) ? "♛ " : ""}${E(a.name)}${isLead(a) ? ` <em class="of-leadtag">${a.team === "hq" ? "CEO" : "팀장"}</em>` : ""}</b><span>${E(t?.name)} · ${E(a.title)}</span></div><button class="of-x" aria-label="닫기">✕</button></div>
    <p>${E(a.duty)}</p>
    <dl><dt>스킬</dt><dd>${sk.length ? sk.map(ctx.esc).join(", ") : "공통 도구(검색·계산·NVIDIA 스킬)"}</dd><dt>AI 직접 고르기</dt><dd>${modelSelect(a.id, (O.getAssign?.() || {})[a.id], "자동 · 팀 설정 따름")} <small class="of-dim">팀 전체는 [팀 구성]에서</small></dd><dt>배정된 AI 모델</dt><dd>${mdl ? ctx.esc(mdl.model) + " · 막히면 다른 모델로 자동 전환" : "API 키를 넣으면 배정됩니다"}</dd><dt>부르는 법</dt><dd>메시지에 <code>@${E(a.name)}</code></dd></dl>
    ${O.seen?.[id]?.length ? `<h4 class="of-h4">최근에 본 것</h4><ul class="of-seen">${O.seen[id].map(o => `<li>${ctx.esc(o.icon || "")} ${o.url ? link(o.url, o.text) : ctx.esc(o.text)} <small>${hm(o.t)}</small></li>`).join("")}</ul>` : ""}`;
  c.hidden = false;
}
function showTeam(){
  const models = O.assignModels(), asg = O.getAssign?.() || {};
  const c = $o("#ofCard");
  c.innerHTML = `<div class="of-cardh"><div><b>팀 구성 · ${TEAMS.length}개 조직 · ${AGENTS.length}명</b><span>CEO와 분야별 팀장이 팀을 이끕니다. 질문 내용으로 담당자가 자동으로 정해지고, 투자·실행 판단은 전략가 → 반론 검토관 → 리스크 책임자를 거쳐 CEO가 정리합니다. 매시 CEO가 팀별 성과를 발표합니다.</span></div><button class="of-x" aria-label="닫기">✕</button></div>
    <div class="of-assign-all">전원 AI: ${modelSelect("all", asg.all, "자동 (추천)")} <small class="of-dim">팀·직원에 따로 고른 것이 우선합니다. Claude 를 고르면 그 직원의 글은 학습 데이터에서 빠집니다.</small></div><div class="of-teams">${TEAMS.map(t => `<div class="of-team" style="--tc:${tc(t.id)}"><b>${E(t.name)} <small>${membersOf(t.id).length}명</small></b><span>${E(t.desc || "")}</span><div class="of-tassign">팀 AI: ${modelSelect("team:" + t.id, asg["team:" + t.id], "자동 · 전원 설정 따름")}</div>${membersOf(t.id).map(a => `<div class="of-mem${isLead(a) ? " lead" : ""}" data-ag="${a.id}"><div class="of-av">${sprite(a)}</div><div><b>${isLead(a) ? "♛ " : ""}${E(a.name)}</b>${isLead(a) ? ` <em class="of-leadtag">${t.id === "hq" ? "CEO" : "팀장"}</em>` : ""} <span>${E(a.title)}</span><small>${models[a.id] ? ctx.esc(shortModel(models[a.id].model)) : "모델 미배정"}</small></div></div>`).join("")}</div>`).join("")}</div>
    <p class="of-flow">회의 순서(코드가 정함): 담당 분석가 → <b>전략가</b>(실행 계획) → <b>반론 검토관</b>(반대 근거 3개 + 판정) → <b>리스크 책임자</b>(승인·축소·거부) → <b>CEO</b>(최종 답). 회의는 팀 구역·대회의실·라운지·발표 무대 어디서든 열립니다. 발언 속 @이름으로 동료를 부르면 그 사람이 회의에 들어옵니다.</p>`;
  c.hidden = false;
}

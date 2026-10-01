// GH Nano 사무실: 앱에 연결된 AI 모델과 스킬로 만든 자유 대화형 에이전트 팀
// - 팀·방·직원은 코드로 정해 두고, 누가 어떤 순서로 말할지도 코드가 정한다(AI는 말만 한다).
//   흐름: 담당 분석가 → (투자·실행 판단이면) 전략가 → 반론 검토관 → 리스크 책임자 → 팀장 정리
// - 사용자가 아무것도 치지 않아도 정해진 안건과 급변동 감시로 스스로 회의를 연다(자동 회의).
import { settings, saveSettings, idb, uid } from "./engine.js";
import { runAgent, activeSkills, TOOLS } from "./agent.js";
import { fusionSources } from "./train.js";

/* ============ 팀과 직원 ============ */
export const TEAMS = [
  {id: "hq", name: "총괄실", desc: "팀장 · 질문을 받아 담당자를 부르고 마지막에 정리"},
  {id: "coin", name: "코인팀", desc: "코인 현물 · 코인 선물"},
  {id: "stock", name: "주식팀", desc: "해외주식 · 국내주식"},
  {id: "fut", name: "선물·매크로팀", desc: "해외선물 · 국내선물 · 거시경제·뉴스"},
  {id: "arch", name: "건축·부동산팀", desc: "건축 설계·견적 · 부동산·토지·법규"},
  {id: "strat", name: "전략·리스크팀", desc: "전략가 · 반론 검토관 · 리스크 책임자"},
  {id: "lab", name: "리서치·개발팀", desc: "리서치 · 개발 · 일상 비서"}
];
// look: 머리색·옷색 (픽셀 캐릭터), role: 모델 고르는 기준
export const AGENTS = [
  {id: "lead", name: "한결", team: "hq", title: "팀장", role: "general", skills: [], look: ["#2b2b3a", "#4a6cf7"],
    duty: "사용자의 질문을 받아 팀원 발언을 종합해 최종 답을 준다. 결론 → 근거(누가 무엇을 확인했는지) → 반론·리스크 → 다음에 할 일 순서로, 사용자에게 바로 쓸 수 있는 답을 쓴다."},
  {id: "coin_spot", name: "코코", team: "coin", title: "코인 현물 분석가", role: "general", skills: ["crypto_spot"], look: ["#f5c542", "#f08a24"],
    duty: "업비트·바이낸스 현물 차트(추세·지지저항·거래량·김치 프리미엄)를 실제 도구로 확인해 해석한다."},
  {id: "coin_fut", name: "레오", team: "coin", title: "코인 선물 분석가", role: "general", skills: ["crypto_futures"], look: ["#3a2a1a", "#e2483d"],
    duty: "바이낸스 무기한 선물의 펀딩비·미결제약정·롱숏비율·청산가로 과열과 쏠림을 해석한다."},
  {id: "us", name: "엠마", team: "stock", title: "해외주식 분석가", role: "general", skills: ["us_stocks"], look: ["#c46a2b", "#2e9e6a"],
    duty: "미국 주식·ETF의 차트와 실적·금리·섹터 흐름을 연결해 해석한다."},
  {id: "kr", name: "서준", team: "stock", title: "국내주식 분석가", role: "general", skills: ["kr_stocks"], look: ["#1f1f1f", "#3c7dd9"],
    duty: "코스피·코스닥 종목의 차트와 외국인·기관 수급, 업종 흐름, 환율 영향을 해석한다."},
  {id: "gfut", name: "올리버", team: "fut", title: "해외선물 분석가", role: "general", skills: ["global_futures"], look: ["#8a5a2b", "#5a5f73"],
    duty: "원유·금·지수 선물·국채 선물의 수급 요인과 만기·증거금 같은 선물 특성을 해석한다."},
  {id: "kfut", name: "지우", team: "fut", title: "국내선물 분석가", role: "general", skills: ["kr_futures"], look: ["#2a1d14", "#9a4fd6"],
    duty: "코스피200 선물·미니 선물·야간선물을 기초지수, 외국인 선물 수급, 베이시스, 만기일과 연결해 해석한다."},
  {id: "macro", name: "노바", team: "fut", title: "거시경제·뉴스 분석가", role: "general", skills: ["macro", "news"], look: ["#d9d9d9", "#1aa3a3"],
    duty: "경제 일정(금리·물가·고용)과 최신 뉴스를 찾아 시장에 주는 영향을 말로 해설한다. 기사 제목을 나열하지 않는다."},
  {id: "arch", name: "하린", team: "arch", title: "건축 설계사", role: "general", skills: ["arch"], look: ["#5b3a29", "#e7a33c"],
    duty: "대지 조건으로 배치·층수·평면을 설계하고 공사비를 추정한다. 설계는 자유로운 설명으로 풀어 쓴다."},
  {id: "land", name: "도윤", team: "arch", title: "부동산·법규 전문가", role: "general", skills: ["land"], look: ["#222", "#6b8e23"],
    duty: "용도지역·건폐율·용적률·재개발·경매·세금 같은 부동산 제도와 위험을 설명한다."},
  {id: "strat", name: "민재", team: "strat", title: "전략가(퀀트)", role: "reason", skills: ["backtest"], look: ["#3b2f2f", "#334e9e"],
    duty: "분석가들의 의견으로 실행 계획(진입 조건·손절·목표·기간)이나 전략 초안을 만들고, 필요하면 백테스트로 확인한다."},
  {id: "devil", name: "수아", team: "strat", title: "반론 검토관", role: "reason", skills: [], look: ["#7a1f2b", "#444"],
    duty: "앞의 의견과 계획에 대한 반대 근거를 최소 3개 든다. 마지막 줄에 '판정: 동의' / '판정: 반대' / '판정: 추가 확인 필요' 중 하나만 쓴다."},
  {id: "risk", name: "태오", team: "strat", title: "리스크 책임자", role: "reason", skills: [], look: ["#111", "#b8860b"],
    duty: "손실 한도·비중·레버리지·최악의 시나리오를 숫자로 점검한다. 계획을 승인·축소·거부할 수 있지만 키우지는 않는다. 마지막 줄에 '리스크 판정: 승인' / '축소' / '거부' 중 하나를 쓴다."},
  {id: "research", name: "리아", team: "lab", title: "리서처", role: "general", skills: ["research"], look: ["#e8b04b", "#5c6bc0"],
    duty: "인터넷과 NVIDIA 스킬 문서에서 자료를 찾아 출처와 함께 정리한다."},
  {id: "dev", name: "코디", team: "lab", title: "개발자", role: "code", skills: ["coding"], look: ["#333", "#2d2d2d"],
    duty: "코드·자동화·데이터 처리 질문에 동작하는 코드와 설명을 준다."},
  {id: "aide", name: "하루", team: "lab", title: "비서(일상·글쓰기·번역)", role: "general", skills: [], look: ["#6d4c41", "#ef6c9a"],
    duty: "일상 대화, 글쓰기, 번역, 요약, 계획 세우기를 친절하게 돕는다."}
];
export const agentById = id => AGENTS.find(a => a.id === id);
export const teamById = id => TEAMS.find(t => t.id === id);
const SKILL_AGENT = {crypto_spot: "coin_spot", crypto_futures: "coin_fut", us_stocks: "us", kr_stocks: "kr", global_futures: "gfut", kr_futures: "kfut",
  macro: "macro", news: "macro", backtest: "strat", arch: "arch", land: "land", research: "research", coding: "dev"};
const MARKET = new Set(["coin_spot", "coin_fut", "us", "kr", "gfut", "kfut", "strat"]);
const DECIDE = /사도|살까|팔까|매수|매도|진입|청산|롱|숏|레버리지|포지션|투자|전략|백테스트|들어가|비중|손절|익절|전망|어때|괜찮|해도 될까|할까/;
const RESEARCH = /검색|찾아|조사|자료|논문|출처|리서치|비교해|후기|리뷰|최신 정보/;
const BUILD = /설계|짓|건축|신축|리모델링|매입|매매|경매|계약|투자|분양|재개발|공사비|견적/;

/* ============ 직원마다 다른 AI 모델 배정 ============ */
// 연결된 모든 대화 모델 중에서, 역할에 맞는 종류를 우선해 서로 다른 모델을 고르게 나눠 준다
export function assignModels(){
  const pool = fusionSources();
  const kindOf = m => /r1|reason|think|qwq|nemotron.*(super|ultra)|o\d|magistral/i.test(m) ? "reason" : /coder|code|devstral|starcoder/i.test(m) ? "code" : "general";
  const used = new Map(), out = {};
  for (const a of AGENTS){
    const fit = pool.filter(t => kindOf(t.model) === a.role);
    const list = (fit.length ? fit : pool).slice().sort((x, y) => (used.get(x.model) || 0) - (used.get(y.model) || 0));
    const pick = list[0];
    if (pick){ out[a.id] = pick; used.set(pick.model, (used.get(pick.model) || 0) + 1); }
  }
  return out;
}

/* ============ 기록 (방 대화) ============ */
let LOG = null;
const LOG_KEY = "office:log";
export async function loadLog(){ if (!LOG){ const v = await idb.all(LOG_KEY).catch(() => []); LOG = Array.isArray(v[0]) ? v[0] : []; LOG.forEach(e => { e.live = false; }); } return LOG; }
let saveT = 0;
function saveLog(){ clearTimeout(saveT); saveT = setTimeout(() => idb.put(LOG_KEY, LOG.slice(-600)), 400); }
function post(entry){ const e = {id: uid(), t: Date.now(), ...entry}; LOG.push(e); if (LOG.length > 800) LOG.splice(0, LOG.length - 600); saveLog(); fire({kind: "log", entry: e}); return e; }
export async function clearLog(){ LOG = []; await idb.put(LOG_KEY, []); fire({kind: "cleared"}); }

/* ============ 이벤트 ============ */
const subs = new Set();
export const onOffice = fn => (subs.add(fn), () => subs.delete(fn));
const fire = ev => { for (const f of subs){ try { f(ev); } catch(e){ console.error(e); } } };

/* ============ 설정·한도 ============ */
export function officeCfg(){
  settings.office = Object.assign({auto: true, every: 30, dailyMax: 12, alert: true}, settings.office || {});
  return settings.office;
}
export function setOffice(patch){ Object.assign(officeCfg(), patch); saveSettings(); fire({kind: "cfg"}); }
const today = () => new Date().toLocaleDateString("sv-SE");
function usage(){ const u = JSON.parse(localStorage.getItem("officeUsage") || "{}"); return u.day === today() ? u : {day: today(), meetings: 0, calls: 0, auto: 0}; }
function bump(k, n = 1){ const u = usage(); u[k] = (u[k] || 0) + n; try { localStorage.setItem("officeUsage", JSON.stringify(u)); } catch(e){} fire({kind: "usage", usage: u}); }
export const officeUsage = usage;

/* ============ 누가 말할지 (코드가 정함) ============ */
export function planMeeting(text, room = "hq", fixed){
  const t = String(text || "");
  let lead = fixed ? [...fixed] : [];
  if (!fixed){
    // @이름으로 부른 직원
    for (const a of AGENTS) if (a.id !== "lead" && (t.includes("@" + a.name) || t.includes("@" + a.title))) lead.push(a.id);
    // 질문에 맞는 스킬 → 담당 분석가
    for (const s of activeSkills(t)){
      // 리서치 스킬은 '오늘·요즘' 같은 흔한 말에도 켜지므로, 자료를 찾아 달라는 말이 있을 때만 리서처를 부른다
      if (s.id === "research" && !RESEARCH.test(t)) continue;
      const id = SKILL_AGENT[s.id]; if (id && !lead.includes(id)) lead.push(id);
    }
    // 팀 방에서 말하면 그 팀이 먼저 답한다
    if (room !== "hq"){
      const mem = AGENTS.filter(a => a.team === room && !["devil", "risk"].includes(a.id)).map(a => a.id);
      const inTeam = lead.filter(id => mem.includes(id));
      lead = inTeam.length ? [...inTeam, ...lead.filter(id => !inTeam.includes(id))] : [mem[0], ...lead].filter(Boolean);
    }
    if (!lead.length) lead = [RESEARCH.test(t) || /엔비디아|nvidia/i.test(t) ? "research" : "aide"];
  }
  lead = [...new Set(lead)].filter(id => !["lead", "devil", "risk"].includes(id)).slice(0, 3);
  const order = [...lead];
  const market = lead.some(id => MARKET.has(id)), build = lead.some(id => id === "arch" || id === "land");
  if (market && DECIDE.test(t)){
    if (!order.includes("strat") && /전략|백테스트|진입|계획|매수|매도|롱|숏|포지션/.test(t)) order.push("strat");
    order.push("devil", "risk");
  } else if (build && BUILD.test(t)) order.push("devil");
  else if (fixed) order.push("devil");
  if (order.length > 1) order.push("lead");
  return order;
}

/* ============ 회의 ============ */
const queue = [];
let running = null;          // 지금 회의
export const officeState = () => ({running, queued: queue.length});
export async function ask(text, {room = "hq"} = {}){
  await loadLog();
  post({ch: room, kind: "user", text});
  return enqueue({topic: text, room, trigger: "user"});
}
export function stopMeeting(){ running?.ctl.abort(); queue.length = 0; }
function enqueue(m){
  return new Promise(res => { queue.push({...m, res}); pump(); });
}
async function pump(){
  if (running || !queue.length) return;
  const job = queue.shift();
  const ctl = new AbortController();
  const order = planMeeting(job.topic, job.room, job.agents);
  const models = assignModels();
  const room = teamById(job.room) || TEAMS[0];
  const name = job.title || (job.trigger === "user" ? "질문 · " + job.topic.replace(/\s+/g, " ").slice(0, 18) : job.topic.slice(0, 20));
  const m = running = {id: uid(), room: job.room, name, trigger: job.trigger, topic: job.topic, order, done: [], ctl, t: Date.now(), models};
  bump("meetings"); if (job.trigger !== "user") bump("auto");
  post({ch: job.room, kind: "divider", text: `회의 · #${name} · ${new Set(order).size}명 참석`, meeting: m.id});
  fire({kind: "start", meeting: m});
  const turns = [];
  try {
    for (let i = 0; i < m.order.length && i < 8; i++){
      if (ctl.signal.aborted) break;
      const a = agentById(m.order[i]);
      const turn = await speak(a, m, turns, models[a.id], ctl.signal);
      if (!turn) continue;
      turns.push(turn); m.done.push(a.id);
      // 발언 속 @이름 → 아직 말하지 않은 동료를 팀장 정리 전에 부른다 (회의당 최대 2명 추가)
      const extra = AGENTS.filter(x => x.id !== a.id && !m.order.includes(x.id) && (turn.text.includes("@" + x.name) || turn.text.includes("@" + x.title)));
      for (const x of extra.slice(0, 2)){
        if (m.order.length >= 8) break;
        const at = m.order.includes("lead") ? m.order.lastIndexOf("lead") : m.order.length;
        m.order.splice(at, 0, x.id);
        if (!m.order.includes("lead")) m.order.push("lead");
        post({ch: m.room, kind: "system", text: `${a.name}님이 ${x.name}(${x.title})님을 불렀습니다`, meeting: m.id});
        fire({kind: "join", meeting: m, agent: x});
      }
    }
    const last = turns[turns.length - 1];
    if (job.trigger !== "user" && officeCfg().alert && last) fire({kind: "alert", meeting: m, text: last.text});
    job.res?.({meeting: m, turns, answer: last?.text || ""});
  } catch (e){
    post({ch: m.room, kind: "system", text: "회의 중단: " + (e.message || e), meeting: m.id});
    job.res?.({meeting: m, turns, error: e.message});
  } finally {
    running = null; fire({kind: "end", meeting: m});
    setTimeout(pump, 300);
  }
}
function transcript(m, turns){
  return turns.map(t => `[${t.agent.name} · ${t.agent.title}]\n${t.text.slice(0, 2500)}`).join("\n\n");
}
async function speak(a, m, turns, target, signal){
  const team = teamById(a.team);
  const mates = AGENTS.filter(x => x.id !== a.id && x.id !== "lead").map(x => `@${x.name}(${x.title})`).join(", ");
  const isLead = a.id === "lead";
  const persona = `[GH Nano 사무실 · 에이전트 팀 회의]
너는 GH Nano 사무실 ${team.name}의 '${a.name}'(${a.title})다. 지금 동료들과 회의 중이다.
- 네 역할: ${a.duty}
- 앞사람 발언을 읽고 같은 말은 반복하지 말고, 네 전문 분야 관점만 더한다. 다른 전문가가 꼭 필요하면 @이름 으로 한 명만 부른다(동료: ${mates}).
- 동료에게 말하듯 자연스러운 한국어로 핵심부터 말한다. 숫자 나열이 아니라 해설로 말한다. 수치는 도구로 확인한 것만 쓰고 지어내지 않는다.
- ${isLead ? "너는 마지막 정리 담당이다. 사용자에게 주는 최종 답을 완결된 글로 쓴다(필요하면 소제목·표)." : "길이는 6~12문장 정도. 사용자에게 주는 최종 답은 팀장이 정리하니, 너는 네 판단과 근거에 집중한다."}`;
  const ask = `${m.trigger === "user" ? "사용자 질문" : "회의 안건"}: ${m.topic}\n\n${turns.length ? "지금까지 회의 내용:\n" + transcript(m, turns) + "\n\n" : ""}이제 ${a.name}(${a.title}) 차례입니다.`;
  const msg = {role: "assistant", parts: [], mode: "chat", ts: Date.now()};
  const entry = post({ch: m.room, kind: "agent", agent: a.id, text: "", meeting: m.id, live: true, model: target?.model || ""});
  fire({kind: "turn", meeting: m, agent: a, entry});
  let last = 0;
  const onUpdate = () => {
    const text = partsText(msg);
    if (text !== entry.text){ entry.text = text; if (Date.now() - last > 120){ last = Date.now(); fire({kind: "delta", meeting: m, agent: a, entry}); } }
    const tool = msg.parts.filter(p => p.type === "tool").at(-1);
    if (tool && tool.status === "running" && entry.tool !== tool.act){ entry.tool = tool.act; fire({kind: "tool", meeting: m, agent: a, entry, text: tool.act}); }
  };
  try {
    bump("calls");
    await runAgent({mode: "chat", history: [{role: "user", content: ask}], msg, signal, onUpdate, think: false, workspace: "", persona, forceSkills: a.skills, target,
      maxSteps: isLead || a.id === "devil" ? 2 : 5, openArtifact: async () => null, askPermission: async () => false});
  } catch (e){
    if (signal.aborted) throw e;
    entry.text = `(${a.name}: 답하지 못했습니다 — ${e.message || e})`;
  }
  entry.text = partsText(msg) || entry.text || "(빈 답)";
  entry.tools = msg.parts.filter(p => p.type === "tool").map(p => p.label || p.name);
  entry.model = msg.route?.model || entry.model; entry.live = false;
  saveLog(); fire({kind: "said", meeting: m, agent: a, entry});
  return {agent: a, text: entry.text, entry};
}
function partsText(msg){ return msg.parts.filter(p => p.type === "text").map(p => p.text).join("\n\n").trim(); }

/* ============ 자동 회의 ============ */
export const AGENDA = [
  {id: "coin", room: "coin", title: "코인-브리핑", topic: "지금 비트코인·이더리움의 현물과 선물 상황을 점검하고, 오늘 주목할 점과 대응 방법을 이야기해 주세요.", agents: ["coin_spot", "coin_fut"]},
  {id: "us", room: "stock", title: "미국증시-점검", topic: "나스닥·S&P500과 엔비디아 같은 주요 종목 흐름을 점검하고 이번 주 주목할 점을 이야기해 주세요.", agents: ["us", "macro"]},
  {id: "kr", room: "stock", title: "국내증시-국내선물", topic: "코스피·코스닥과 코스피200 선물 흐름, 외국인 수급과 환율을 점검해 주세요.", agents: ["kr", "kfut"]},
  {id: "fut", room: "fut", title: "해외선물-매크로", topic: "원유·금·나스닥 선물과 이번 주 경제 일정을 점검하고 시장에 줄 영향을 해설해 주세요.", agents: ["gfut", "macro"]},
  {id: "news", room: "fut", title: "오늘의-뉴스", topic: "오늘 코인·주식 시장의 주요 뉴스를 찾아 큰 줄기로 묶어 해설해 주세요.", agents: ["macro", "research"]},
  {id: "arch", room: "arch", title: "건축-부동산-동향", topic: "최근 금리·부동산 정책·건축비 흐름이 집을 짓거나 사려는 사람에게 어떤 의미인지 이야기해 주세요.", agents: ["land", "arch"]},
  {id: "strat", room: "strat", title: "주간-전략회의", topic: "지금 시장에서 쓸 만한 매매 전략 하나를 골라 조건·손절·목표를 정하고 위험을 따져 주세요.", agents: ["strat", "coin_spot"]}
];
// 급변동 감시 (코드만 씀, AI 호출 없음)
const WATCH = [{q: "비트코인", label: "비트코인", room: "coin", agents: ["coin_spot", "coin_fut"], th: 4}, {q: "^IXIC", label: "나스닥", room: "stock", agents: ["us", "macro"], th: 2}, {q: "^KS11", label: "코스피", room: "stock", agents: ["kr", "kfut"], th: 2}];
let timer = 0, lastWatch = 0;
export function startAutopilot(){
  if (timer) return; officeCfg();
  // 처음 켤 때는 2분 뒤에 첫 자동 회의
  if (!localStorage.getItem("officeLastAuto")) localStorage.setItem("officeLastAuto", String(Date.now() - officeCfg().every * 60e3 + 120e3));
  timer = setInterval(tick, 60e3); setTimeout(tick, 4000);
}
export function stopAutopilot(){ clearInterval(timer); timer = 0; }
export function nextAutoIn(){
  const c = officeCfg(), last = +localStorage.getItem("officeLastAuto") || 0;
  return Math.max(0, last + c.every * 60e3 - Date.now());
}
async function tick(){
  const c = officeCfg();
  if (!c.auto || running || queue.length || !fusionSources().length) return;
  const u = usage();
  if (u.auto >= c.dailyMax) return;
  await loadLog();
  // 1) 급변동이면 바로 긴급 회의
  if (Date.now() - lastWatch > 10 * 60e3){
    lastWatch = Date.now();
    try {
      const r = await TOOLS.market_quote.run({symbols: WATCH.map(w => w.q)});
      const rows = JSON.parse(r.text || "[]"), seen = JSON.parse(localStorage.getItem("officeWatch") || "{}");
      for (const w of WATCH){
        const row = rows.find(x => String(x.종목 || "").includes(w.q) || String(x.종목 || "").includes(w.label));
        const chg = row && +row["변동%"]; if (!Number.isFinite(chg)) continue;
        const band = Math.trunc(chg / w.th), key = w.q + "|" + today();
        if (band !== 0 && seen[key] !== band){
          seen[key] = band; localStorage.setItem("officeWatch", JSON.stringify(seen));
          post({ch: w.room, kind: "system", text: `급변동 감지: ${w.label} ${chg > 0 ? "+" : ""}${chg}% → 긴급 회의를 엽니다`});
          enqueue({topic: `${w.label}가 하루 ${chg > 0 ? "+" : ""}${chg}% 움직였습니다. 원인과 지금 대응 방법을 점검해 주세요.`, room: w.room, trigger: "event", title: `긴급-${w.label}`, agents: w.agents});
          localStorage.setItem("officeLastAuto", String(Date.now()));
          return;
        }
      }
    } catch(e){}
  }
  // 2) 정해진 간격마다 안건을 돌아가며
  if (nextAutoIn() > 0) return;
  const i = (+localStorage.getItem("officeAgenda") || 0) % AGENDA.length, ag = AGENDA[i];
  localStorage.setItem("officeAgenda", String(i + 1)); localStorage.setItem("officeLastAuto", String(Date.now()));
  enqueue({topic: ag.topic, room: ag.room, trigger: "auto", title: ag.title, agents: ag.agents});
}
export async function runAgendaNow(id){
  await loadLog();
  const ag = AGENDA.find(a => a.id === id) || AGENDA[0];
  localStorage.setItem("officeLastAuto", String(Date.now()));
  return enqueue({topic: ag.topic, room: ag.room, trigger: "auto", title: ag.title, agents: ag.agents});
}

// GH Nano 사무실: 앱에 연결된 AI 모델과 스킬로 만든 자유 대화형 에이전트 팀
// - 팀·방·직원은 코드로 정해 두고, 누가 어떤 순서로 말할지도 코드가 정한다(AI는 말만 한다).
//   흐름: 담당 분석가 → (투자·실행 판단이면) 전략가 → 반론 검토관 → 리스크 책임자 → 팀장 정리
// - 사용자가 아무것도 치지 않아도 정해진 안건과 급변동 감시로 스스로 회의를 연다(자동 회의).
import { settings, saveSettings, idb, uid, brainStream, splitThink, overCap, provUse, LAUNCHER } from "./engine.js";
import { runAgent, activeSkills, TOOLS, marketNews, candlesFor, visibleText, snapText, toModelMessages } from "./agent.js";
import { fusionSources, TRAIN_SYS } from "./train.js";

/* ============ 팀과 직원 ============ */
export const TEAMS = [
  {id: "hq", name: "총괄실", desc: "팀장 · 질문을 받아 담당자를 부르고 마지막에 정리"},
  {id: "coin", name: "코인팀", desc: "코인 현물 · 코인 선물"},
  {id: "stock", name: "주식팀", desc: "해외주식 · 국내주식"},
  {id: "fut", name: "선물·매크로팀", desc: "해외선물 · 국내선물 · 거시경제·뉴스"},
  {id: "arch", name: "건축·부동산팀", desc: "건축 설계·견적 · 부동산·토지·법규"},
  {id: "strat", name: "전략·리스크팀", desc: "전략가 · 반론 검토관 · 리스크 책임자"},
  {id: "lab", name: "리서치·개발팀", desc: "리서치 · 개발 · 일상 비서"},
  {id: "quant", name: "퀀트 연구소", desc: "보조지표 29종으로 매매법 개발 · 백테스트 검증 · 모의투자"},
  {id: "data", name: "데이터·SNS팀", desc: "SNS 여론 · 컴퓨터 작업(보고서·스크립트)"}
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
    duty: "일상 대화, 글쓰기, 번역, 요약, 계획 세우기를 친절하게 돕는다."},
  {id: "qa", name: "준호", team: "quant", title: "퀀트 연구원(추세)", role: "reason", skills: ["backtest", "crypto_futures"], look: ["#1d1d2b", "#2f9e6b"],
    duty: "보조지표 29종(indicator_all)과 연구 카드를 보고 추세추종 매매법을 만들고 strategy_backtest로 직접 시험한다."},
  {id: "qb", name: "세라", team: "quant", title: "퀀트 연구원(역추세·변동성)", role: "reason", skills: ["backtest", "crypto_spot"], look: ["#a0522d", "#c2185b"],
    duty: "과매수·과매도, 밴드 이탈, 변동성 수축·확장을 노리는 매매법을 만들고 직접 백테스트한다."},
  {id: "val", name: "다온", team: "quant", title: "백테스트 검증관", role: "reason", skills: ["backtest"], look: ["#444", "#607d8b"],
    duty: "백테스트 결과의 과최적화 위험을 따진다(검증 구간 성과, 거래 수, 낙폭, 수수료). 코드 판정을 쉬운 말로 설명하고 통과·불통과를 뒤집지 않는다."},
  {id: "trader", name: "현우", team: "quant", title: "모의투자 트레이더", role: "general", skills: ["crypto_futures"], look: ["#2e2e2e", "#f57c00"],
    duty: "모의투자 장부(paper_status)를 보고 운용 중인 전략의 포지션·손익과 다음 대응을 보고한다. 실제 주문은 하지 않는다."},
  {id: "sns", name: "유나", team: "data", title: "SNS·여론 분석가", role: "general", skills: ["news"], look: ["#d4a017", "#8e24aa"],
    duty: "레딧·스톡트윗·공포탐욕지수(sns_buzz)로 사람들의 분위기와 쏠림을 읽고, 뉴스와 비교해 과열·공포를 해설한다."},
  {id: "eng", name: "태민", team: "data", title: "데이터 엔지니어(컴퓨터 작업)", role: "code", skills: ["coding"], look: ["#3e2723", "#455a64"], computer: true,
    duty: "사무실 전용 폴더(문서/GHNano 사무실)에서 보고서·데이터 파일을 만들고 파이썬 스크립트를 짜서 실행한다(office_write, office_run)."}
];
export const agentById = id => AGENTS.find(a => a.id === id);
const hasAI = () => fusionSources().length > 0 || !!settings.keys.anthropic;
export const teamById = id => TEAMS.find(t => t.id === id);
const SKILL_AGENT = {crypto_spot: "coin_spot", crypto_futures: "coin_fut", us_stocks: "us", kr_stocks: "kr", global_futures: "gfut", kr_futures: "kfut",
  macro: "macro", news: "macro", backtest: "strat", arch: "arch", land: "land", research: "research", coding: "dev"};
const MARKET = new Set(["coin_spot", "coin_fut", "us", "kr", "gfut", "kfut", "strat", "qa", "qb", "trader"]);
const DECIDE = /사도|살까|팔까|매수|매도|진입|청산|롱|숏|레버리지|포지션|투자|전략|백테스트|들어가|비중|손절|익절|전망|어때|괜찮|해도 될까|할까/;
const RESEARCH = /검색|찾아|조사|자료|논문|출처|리서치|비교해|후기|리뷰|최신 정보/;
const BUILD = /설계|짓|건축|신축|리모델링|매입|매매|경매|계약|투자|분양|재개발|공사비|견적/;

/* ============ 직원마다 다른 AI 모델 배정 ============ */
// 연결된 모든 대화 모델 중에서, 역할에 맞는 종류를 우선해 서로 다른 모델을 고르게 나눠 준다
// 빈 답·오류가 난 모델은 오늘 하루 배정에서 뺀다
const badModels = () => { try { const o = JSON.parse(localStorage.getItem("officeBad") || "{}"); return o.day === today() ? o.m || {} : {}; } catch(e){ return {}; } };
function markBad(model){ if (!model) return; const m = badModels(); m[model] = (m[model] || 0) + 1; try { localStorage.setItem("officeBad", JSON.stringify({day: today(), m})); } catch(e){} }
export function assignModels(){
  const bad = badModels(), all = fusionSources(), ok = all.filter(t => !bad[t.model]);
  const pool = ok.length ? ok : all;
  const kindOf = m => /r1|reason|think|qwq|nemotron.*(super|ultra)|o\d|magistral/i.test(m) ? "reason" : /coder|code|devstral|starcoder/i.test(m) ? "code" : "general";
  const used = new Map(), out = {};
  for (const a of AGENTS){
    const fit = pool.filter(t => kindOf(t.model) === a.role);
    const list = (fit.length ? fit : pool).slice().sort((x, y) => (used.get(x.model) || 0) - (used.get(y.model) || 0));
    const pick = list[0];
    if (pick){ out[a.id] = pick; used.set(pick.model, (used.get(pick.model) || 0) + 1); }
  }
  // Claude가 연결돼 있고 오늘 한도가 남아 있으면 판단이 중요한 자리에 쓴다 (팀장은 Opus, 전략·검증·리스크는 Sonnet)
  if (settings.keys.anthropic && !overCap("anthropic") && officeCfg().claude !== false){
    const ms = settings.provModels.anthropic?.length ? settings.provModels.anthropic : ["claude-opus-5-5", "claude-sonnet-5-5"];
    const opus = ms.find(m => /opus/.test(m)), sonnet = ms.find(m => /sonnet/.test(m)) || opus;
    if (opus && !bad[opus]) out.lead = {id: "anthropic", model: opus};
    for (const id of CLAUDE_ROLES) if (sonnet && !bad[sonnet]) out[id] = {id: "anthropic", model: sonnet};
  }
  return out;
}
const CLAUDE_ROLES = ["strat", "risk", "devil", "qa", "qb", "val"];

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
  settings.office = Object.assign({auto: true, every: 30, dailyMax: 12, alert: true, chat: true, chatEvery: 3, chatMax: 80, cycle: true, cycleMin: 3, callMax: 600, computer: true, claude: true, train: true}, settings.office || {});
  return settings.office;
}
export function setOffice(patch){ Object.assign(officeCfg(), patch); saveSettings(); fire({kind: "cfg"}); }
const today = () => new Date().toLocaleDateString("sv-SE");
function usage(){ let u = {}; try { u = JSON.parse(localStorage.getItem("officeUsage") || "{}"); } catch(e){} return u.day === today() ? u : {day: today(), meetings: 0, calls: 0, auto: 0, chats: 0}; }
function bump(k, n = 1){ const u = usage(); u[k] = (u[k] || 0) + n; try { localStorage.setItem("officeUsage", JSON.stringify(u)); } catch(e){} fire({kind: "usage", usage: u}); }
export const officeUsage = usage;

/* ============ 직원들의 대화를 GH Nano 학습 데이터로 남기기 ============ */
// - 회의: 질문 → <think>팀원들의 분석·반론·리스크</think> + 팀장 결론 (작은 모델이 혼자서도 '팀 토론'을 거쳐 답하게)
// - 첫 분석가의 실제 도구 사용 과정, 자료를 읽고 해설한 일(SNS·경제·모의투자 보고), 검증을 통과한 매매법, 동료 수다
// Claude가 쓴 글은 약관에 따라 넣지 않는다. 회의록에서 👎를 누르면 그 예시는 지운다.
const isClaude = m => /claude/i.test(String(m || ""));
const goodText = t => !!t && t.length >= 30 && !/^\(.{0,20}(답하지 못했|빈 답)/.test(t);
const clip = (t, n) => { t = String(t || ""); return t.length > n ? t.slice(0, n) + "…" : t; };
const noMind = t => String(t || "").replace(/^\s*💭[^\n]*\n?/gm, "").trim();
async function keep(kind, messages, meta = {}){
  if (officeCfg().train === false) return null;
  const minLen = meta.minLen || 30; delete meta.minLen;
  if (!messages.length || messages.at(-1).role !== "assistant" || messages.some(x => x.role === "assistant" && (String(x.content || "").length < minLen || /답하지 못했|빈 답\)/.test(x.content)))) return null;
  const id = uid();
  await idb.put("train:" + id, {id, t: Date.now(), src: "office", kind, messages: [{role: "system", content: TRAIN_SYS("chat")}, ...messages], ...meta});
  bump("trained");
  return id;
}
export async function rateEntry(entryId, v){
  await loadLog();
  const e = LOG.find(x => x.id === entryId); if (!e) return null;
  e.rating = e.rating === v ? 0 : v;
  for (const id of e.trainIds || []){
    const all = await idb.all("train:" + id); const rec = all[0];
    if (!rec) continue;
    if (e.rating < 0){ await idb.del("train:" + id); }
    else { rec.rating = e.rating; if (e.rating > 0) rec.score = 5; await idb.put("train:" + id, rec); }
  }
  if (e.rating < 0) e.trainIds = [];
  saveLog(); fire({kind: "rated", entry: e});
  return e;
}

/* ============ 누가 말할지 (코드가 정함) ============ */
export function planMeeting(text, room = "hq", fixed){
  const t = String(text || "");
  let lead = fixed ? [...fixed] : [];
  if (!fixed){
    // @이름으로 부른 직원
    for (const a of AGENTS) if (a.id !== "lead" && (t.includes("@" + a.name) || t.includes("@" + a.title))) lead.push(a.id);
    // 퀀트·SNS·컴퓨터 작업 담당
    if (/매매법|전략 (개발|만들)|백테스트|보조지표|지표 (조합|전부)|퀀트/.test(t)) lead.push("qa", "qb");
    if (/모의투자|페이퍼|가상 (계좌|매매)|포지션 현황/.test(t)) lead.push("trader");
    if (/sns|SNS|레딧|트위터|스톡트윗|여론|커뮤니티|공포.?탐욕|심리|분위기/.test(t)) lead.push("sns");
    if (/파일|폴더|스크립트|보고서 (저장|만들)|엑셀|csv|컴퓨터|자동화/i.test(t)) lead.push("eng");
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
  if (lead.some(id => id === "qa" || id === "qb") && !order.includes("val")) order.push("val");
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
  if (chatting){ setTimeout(pump, 1500); return; }
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
    // 회의 전체 → '팀 토론을 머릿속으로 거친 답' 학습 예시
    if (turns.length >= 2 && last.agent.id === "lead" && goodText(last.text) && !isClaude(last.entry.model)){
      const inner = turns.slice(0, -1).filter(t => goodText(t.text) && !isClaude(t.entry.model));
      let think = "", room = 1800;
      for (const t of inner){ const piece = `[${t.agent.title}] ${clip(t.text.replace(/\s+/g, " "), Math.min(520, room))}`; if (room < 120) break; think += (think ? "\n\n" : "") + piece; room -= piece.length; }
      if (think){
        const id = await keep("office-meeting", [{role: "user", content: m.topic}, {role: "assistant", content: `<think>\n${think}\n</think>\n\n${last.text}`}], {meeting: m.id, speakers: inner.map(t => t.agent.id)}).catch(() => null);
        if (id){ last.entry.trainIds = [...(last.entry.trainIds || []), id]; saveLog(); }
      }
    }
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
  const prev = turns.at(-1)?.agent;
  const persona = `[GH Nano 사무실 · 에이전트 팀 회의]
너는 GH Nano 사무실 ${team.name}의 '${a.name}'(${a.title})다. 지금 동료들과 자유롭게 토론하는 회의 중이다.
- 네 역할: ${a.duty}
- 답의 첫 줄은 반드시 '💭 '로 시작하는 한 문장 속마음이다(무엇을 확인하고 어떻게 판단하려는지). 그다음 줄부터 말한다.
- ${prev ? `앞사람(${prev.name})의 말에 이름을 불러 반응하며 시작한다(동의·보충·반박). ` : ""}같은 말은 반복하지 말고 네 전문 분야 관점을 더한다. 다른 전문가가 꼭 필요하면 @이름 으로 한 명만 부른다(동료: ${mates}).
- 회사 동료와 대화하듯 자연스러운 한국어로 말한다. 숫자 나열이 아니라 해설로 말한다. 수치는 도구로 확인한 것만 쓰고 지어내지 않는다. 차트·뉴스를 봤다면 무엇을 봤는지 말한다.
- ${isLead ? "너는 마지막 정리 담당이다. 사용자에게 주는 최종 답을 완결된 글로 쓴다(필요하면 소제목·표)." : "길이는 5~10문장 정도. 사용자에게 주는 최종 답은 팀장이 정리하니, 너는 네 판단과 근거에 집중한다."}`;
  const ask = `${m.trigger === "user" ? "사용자 질문" : "회의 안건"}: ${m.topic}\n\n${turns.length ? "지금까지 회의 내용:\n" + transcript(m, turns) + "\n\n" : ""}이제 ${a.name}(${a.title}) 차례입니다.`;
  const entry = post({ch: m.room, kind: "agent", agent: a.id, text: "", think: "", steps: [], meeting: m.id, live: true, model: target?.model || ""});
  fire({kind: "turn", meeting: m, agent: a, entry});
  // 배정 모델 → (빈 답이면) 다른 모델 → 자동 선택 순서로 다시 시도
  const alt = fusionSources().find(t => t.model !== target?.model && !badModels()[t.model] && !/r1|reason|think|gpt-oss|qwq/i.test(t.model));
  const tries = [target, alt, null].filter((t, i, arr) => i === arr.length - 1 || (t && arr.findIndex(x => x && x.model === t.model) === i));
  let lastMsg = null;
  for (const tg of tries){
    const msg = lastMsg = {role: "assistant", parts: [], mode: "chat", ts: Date.now()};
    let last = 0, lastTool = "";
    const onUpdate = () => {
      read(msg, entry);
      const tool = entry.steps.at(-1), sig = tool ? tool.act + tool.status : "";
      if (sig !== lastTool){ lastTool = sig; fire({kind: "tool", meeting: m, agent: a, entry, step: tool}); }
      if (Date.now() - last > 150){ last = Date.now(); fire({kind: "delta", meeting: m, agent: a, entry}); }
    };
    let err = null;
    try {
      bump("calls");
      await runAgent({mode: "chat", history: [{role: "user", content: ask}], msg, signal, onUpdate, think: false, workspace: "", persona, forceSkills: a.skills, target: tg || undefined,
        maxSteps: isLead || a.id === "devil" ? 2 : 6, openArtifact: async () => null, askPermission: officePermission,
        office: true, officeTools: a.computer && computerOn() ? ["office_ls", "office_read", "office_write", "office_run"] : []});
    } catch (e){ if (signal.aborted) throw e; err = e; }
    read(msg, entry);
    entry.model = msg.route?.model || tg?.model || entry.model;
    if (entry.text) break;
    markBad(tg?.model || msg.route?.model);
    const why = err ? (err.message || String(err)).slice(0, 80) : entry.think ? "생각만 하고 답을 내지 못함" : "빈 답";
    entry.notes = [...(entry.notes || []), `${shortName(entry.model)}: ${why} → 다른 모델로 다시`];
    fire({kind: "delta", meeting: m, agent: a, entry});
  }
  if (!entry.text) entry.text = `(${a.name}: 연결된 모델들이 이번에는 답하지 못했습니다)`;
  entry.tools = entry.steps.map(x => x.act);
  // 첫 분석가가 실제 도구를 쓴 과정은 '도구 사용' 학습 예시로 (앞사람 발언에 기대지 않는 차례만)
  if (!turns.length && lastMsg && entry.steps.some(x => x.status === "done") && goodText(entry.text) && !isClaude(entry.model) && !lastMsg.parts.some(p => p.type === "tool" && p.status === "error")){
    const conv = toModelMessages([{role: "user", content: m.topic}, lastMsg], 1e9, 3000).map(x => x.role === "assistant" ? {...x, content: noMind(x.content)} : x).filter(x => x.content);
    const id = await keep("office-tool", conv, {agent: a.id, model: entry.model}).catch(() => null);
    if (id) entry.trainIds = [id];
  }
  entry.live = false;
  saveLog(); fire({kind: "said", meeting: m, agent: a, entry});
  return {agent: a, text: entry.text, entry};
}
// runAgent가 붙이는 안내 문구(빈 답·길이 한도)는 답이 아니다
// 사무실 직원은 사무실 전용 폴더 작업만 스스로 허락한다 (그 밖의 쓰기·실행은 거절)
export const computerOn = () => LAUNCHER.on && officeCfg().computer !== false;
const officePermission = async tp => computerOn() && /^office_/.test(tp.name);
const EMPTY_MARK = /\*\((모델이 빈 답을 보냈습니다|답변 길이 한도에 닿아 끊겼습니다|알 수 없는 도구)[^)]*\)\*/g;
const shortName = m => String(m || "모델").split("/").pop();
// 메시지 조각 → 말(text) · 속마음(think) · 한 일(steps)
function read(msg, entry){
  const texts = msg.parts.filter(p => p.type === "text");
  let raw = texts.map(p => p.text).join("\n\n").replace(EMPTY_MARK, "").trim();
  let think = texts.map(p => p.think || "").join("\n").trim();
  const mm = raw.match(/^💭\s*([^\n]*)\n?/);
  if (mm){ think = (think ? think + "\n" : "") + mm[1].trim(); raw = raw.slice(mm[0].length).trim(); }
  raw = raw.replace(/^\s*💭[^\n]*\n/gm, "").trim();
  entry.text = raw; entry.think = think;
  entry.steps = msg.parts.filter(p => p.type === "tool").map(p => ({act: p.act || p.label, name: p.name, status: p.status, summary: p.summary || "", err: p.error || "", sources: (p.sources || []).slice(0, 5)}));
}
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
  if (!c.auto || running || queue.length || !hasAI()) return;
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

/* ============ 업무: 직원이 실제로 보는 차트·뉴스 (코드만 씀, AI 호출 없음) ============ */
const WATCH_OF = {
  coin_spot: [{q: "비트코인"}, {q: "이더리움"}, {q: "리플"}, {q: "솔라나"}, {news: "crypto"}],
  coin_fut: [{q: "BTCUSDT", ex: "binancef"}, {q: "ETHUSDT", ex: "binancef"}, {q: "SOLUSDT", ex: "binancef"}, {news: "futures"}],
  us: [{q: "NVDA"}, {q: "AAPL"}, {q: "TSLA"}, {q: "^IXIC"}, {q: "^GSPC"}, {news: "us"}],
  kr: [{q: "삼성전자"}, {q: "SK하이닉스"}, {q: "^KS11"}, {q: "^KQ11"}, {news: "kr"}],
  gfut: [{q: "CL=F"}, {q: "GC=F"}, {q: "NQ=F"}, {q: "SI=F"}, {news: "global_futures"}],
  kfut: [{q: "^KS200"}, {q: "KRW=X"}, {q: "^KS11"}, {news: "kr"}],
  macro: [{news: "macro"}, {q: "DX-Y.NYB"}, {q: "^TNX"}, {news: "macro"}],
  arch: [{news: "realestate"}], land: [{news: "realestate"}, {news: "realestate"}],
  strat: [{q: "비트코인"}, {q: "^IXIC"}, {q: "^VIX"}], risk: [{q: "^VIX"}, {q: "비트코인"}], devil: [{news: "macro"}, {q: "^VIX"}],
  research: [{news: "macro"}, {news: "us"}, {news: "crypto"}], lead: [{q: "비트코인"}, {q: "^KS11"}, {q: "^IXIC"}]
};
const IDLE_WORK = {dev: ["💻 코드 리뷰 중", "🧪 테스트 돌리는 중", "🛠 대시보드 고치는 중"], aide: ["📝 오늘 일정 정리 중", "✉️ 메일 정리 중", "🗂 회의록 정리 중"]};
export const seen = {};   // 직원 → 최근에 본 것 [{icon, text, url, t}]
const newsCache = {};
export async function observe(id){
  const list = WATCH_OF[id];
  if (!list){ const w = IDLE_WORK[id]; return w ? {icon: "", text: w[Math.floor(Math.random() * w.length)], kind: "work", t: Date.now()} : null; }
  const pick = list[Math.floor(Math.random() * list.length)];
  let o = null;
  try {
    if (pick.news){
      const c = newsCache[pick.news];
      const items = c && Date.now() - c.t < 15 * 60e3 ? c.items : (newsCache[pick.news] = {t: Date.now(), items: await marketNews(pick.news)}).items;
      const it = items[Math.floor(Math.random() * Math.min(6, items.length))];
      if (it) o = {icon: "📰", kind: "news", text: String(it.title).replace(/\s+/g, " ").slice(0, 110), url: it.url, src: (() => { try { return new URL(it.url).hostname.replace(/^www\./, ""); } catch(e){ return ""; } })()};
    } else {
      const r = await TOOLS.market_quote.run({symbols: [pick.q], exchange: pick.ex || ""});
      const row = JSON.parse(r.text || "[]").find(x => x.현재가 != null);
      if (row){
        const chg = row["변동%"], raw = String(row.종목).split(" (")[0];
        const nm = /[가-힣]/.test(raw) ? raw : /[가-힣]/.test(pick.q) ? pick.q : raw;
        const where = /업비트/.test(row.시장) ? "업비트 " : /바이낸스.*선물|binancef/i.test(row.시장 + pick.ex) ? "바이낸스 선물 " : /바이낸스/.test(row.시장) ? "바이낸스 " : "";
        const price = Number(row.현재가).toLocaleString("ko-KR", {maximumFractionDigits: 2});
        o = {icon: chg == null ? "📈" : chg >= 0 ? "📈" : "📉", kind: "chart", chg, text: `${where}${nm} ${price}${row.통화 && row.통화 !== "KRW" ? " " + row.통화 : /업비트/.test(row.시장) ? "원" : ""}${chg != null ? ` (${chg >= 0 ? "+" : ""}${chg}%)` : ""} 차트 보는 중`};
      }
    }
  } catch(e){}
  if (!o) return null;
  o.t = Date.now();
  (seen[id] ||= []).unshift(o); seen[id].length = Math.min(seen[id].length, 8);
  return o;
}
// 업무 기록: 같은 직원은 3분에 한 번만 회의록 패널에 남긴다 (말풍선은 매번)
const lastWorkLog = {};
export async function work(id){
  const o = await observe(id); if (!o) return null;
  if (o.kind !== "work" && Date.now() - (lastWorkLog[id] || 0) > 180e3){
    lastWorkLog[id] = Date.now(); await loadLog();
    post({ch: agentById(id).team, kind: "work", agent: id, icon: o.icon, text: o.text, url: o.url || "", src: o.src || ""});
  }
  return o;
}

/* ============ 수시 대화: 동료끼리 방금 본 것을 두고 나누는 잡담·업무 대화 ============ */
const RELATED = {coin_spot: ["coin_fut", "strat", "macro"], coin_fut: ["coin_spot", "risk", "strat"], us: ["macro", "kr", "strat"], kr: ["kfut", "us", "macro"],
  gfut: ["macro", "kfut", "us"], kfut: ["kr", "gfut", "risk"], macro: ["us", "gfut", "research"], arch: ["land", "aide"], land: ["arch", "macro"],
  strat: ["devil", "coin_spot", "risk"], risk: ["strat", "coin_fut"], devil: ["strat", "risk"], research: ["macro", "dev"], dev: ["research", "aide"], aide: ["lead", "dev"], lead: ["aide", "strat"]};
let chatting = false, visible = false, chatTimer = 0;
export const setOfficeVisible = v => { visible = v; };
export const isChatting = () => chatting;
const sleep = ms => new Promise(r => setTimeout(r, ms));
function chatUsage(){ return usage().chats || 0; }
export async function chatter(force){
  const c = officeCfg();
  if (chatting || running || queue.length || !hasAI()) return false;
  if (!force && (!c.chat || chatUsage() >= c.chatMax)) return false;
  chatting = true;
  try {
    await loadLog();
    // 말을 꺼낼 사람: 방금 무언가를 본 직원 (없으면 지금 보게 한다)
    const fresh = AGENTS.filter(a => seen[a.id]?.[0] && Date.now() - seen[a.id][0].t < 10 * 60e3 && seen[a.id][0].kind !== "work");
    const starter = fresh.length ? fresh[Math.floor(Math.random() * fresh.length)] : AGENTS.filter(a => WATCH_OF[a.id])[Math.floor(Math.random() * 12)];
    const obs = seen[starter.id]?.[0]?.kind !== "work" && seen[starter.id]?.[0] || await observe(starter.id);
    if (!obs) return false;
    const rel = RELATED[starter.id] || [];
    const partners = rel.slice().sort(() => Math.random() - .5).slice(0, Math.random() < 0.5 ? 1 : 2).map(agentById);
    const people = [starter, ...partners];
    const sys = `[잡담] 너는 GH Nano 사무실 직원들의 대화를 쓰는 작가다. 회사 동료들이 자리에서 일하다 나누는 자연스러운 한국어 대화를 쓴다.
참여자: ${people.map(p => `${p.name}(${p.title})`).join(", ")}
규칙: 4~7줄. 각 줄은 '이름: 대사' 형식(참여자 이름만). 대사는 1~2문장. ${starter.name}가 방금 본 것을 꺼내며 시작한다. 각자 자기 전문 분야 관점으로 반응하고, 가벼운 농담이나 생활 이야기가 섞여도 좋다.
방금 본 것 외의 숫자·사실은 지어내지 말고, 모르면 '확인해 볼게요'라고 한다. 투자 권유처럼 단정하지 않는다. 팀 회의가 꼭 필요할 만큼 중요하면 마지막 줄에 누군가 '회의 한번 하죠'라고 말한다.`;
    const user = `${starter.name}가 방금 본 것: ${obs.icon} ${obs.text}${obs.src ? ` (출처: ${obs.src})` : ""}`;
    let out = "";
    bump("calls"); bump("chats");
    const route = await brainStream({messages: [{role: "system", content: sys}, {role: "user", content: user}], role: "general", maxTokens: 600, temperature: 0.9, exclude: fusionSources().length ? ["anthropic"] : [], onContent: d => out += d});
    const body = splitThink(out).body;
    const lines = body.split(/\n+/).map(l => l.replace(/^[\s*\-•]+/, "").replace(/\*\*/g, "").trim()).map(l => {
      const mm = l.match(/^([^:：]{1,12})\s*[:：]\s*(.+)$/); if (!mm) return null;
      const who = people.find(p => mm[1].includes(p.name)); return who ? {who, text: mm[2].trim()} : null;
    }).filter(Boolean).slice(0, 8);
    if (lines.length < 2) return false;
    const ch = starter.team;
    post({ch, kind: "divider", chat: true, text: `수다 · ${people.map(p => p.name).join(", ")}${route?.model ? " · " + shortName(route.model) : ""}`});
    post({ch, kind: "work", agent: starter.id, icon: obs.icon, text: obs.text, url: obs.url || "", src: obs.src || ""});
    fire({kind: "huddle", ids: people.map(p => p.id), host: starter.id});
    await sleep(1800);
    for (const l of lines){
      const e = post({ch, kind: "agent", chat: true, agent: l.who.id, text: l.text});
      fire({kind: "line", agent: l.who, entry: e});
      await sleep(Math.min(6500, 1600 + l.text.length * 45));
    }
    fire({kind: "huddle-end", ids: people.map(p => p.id)});
    // 동료 수다 → 자연스러운 대화 흐름 예시 (말을 주고받는 순서대로 사용자·어시스턴트를 번갈아)
    if (!isClaude(route?.model)){
      const conv = lines.map((l, i) => ({role: i % 2 ? "assistant" : "user", content: l.text}));
      if (conv.at(-1).role === "user") conv.pop();
      if (conv.length >= 2) await keep("office-chat", conv, {speakers: people.map(p => p.id), model: route?.model || "", minLen: 4}).catch(() => null);
    }
    // 잡담에서 회의하자는 말이 나오면 진짜 회의를 연다
    if (/회의\s*(한번|한 번)?\s*(하죠|합시다|해요|하자|열|해보|잡)/.test(lines.at(-1).text) && usage().auto < c.dailyMax){
      enqueue({topic: `잡담에서 나온 이야기입니다. ${starter.name}가 본 것: ${obs.text}. 의미와 대응을 팀으로 점검해 주세요.`, room: ch, trigger: "auto", title: `잡담에서-${starter.name}`, agents: [starter.id, ...partners.map(p => p.id)].slice(0, 3)});
    }
    return true;
  } catch(e){ return false; }
  finally { chatting = false; setTimeout(pump, 200); }
}
export function nextChatIn(){ const c = officeCfg(), last = +localStorage.getItem("officeLastChat") || 0; return Math.max(0, last + c.chatEvery * 60e3 - Date.now()); }
export function startChatter(){
  if (chatTimer) return;
  chatTimer = setInterval(async () => {
    const c = officeCfg();
    if (!visible || !c.chat || nextChatIn() > 0) return;
    localStorage.setItem("officeLastChat", String(Date.now()));
    await chatter();
  }, 15e3);
}

/* ============ 3분 주기: 사람처럼 알아서 일하기 ============ */
// 매 주기 ① 모의투자 장부를 실제 시세로 갱신(코드, AI 없음) ② 그때그때 한 가지 일을 고른다:
// 매매법 연구 · SNS 여론 · 경제 리서치 · 동료 수다 · 컴퓨터 작업 · 모의투자 보고 (하루 AI 호출 한도 안에서)
const JOBS = ["research", "sns", "economy", "research", "paper", "chat", "computer", "economy", "research", "sns"];
const JOB_KO = {research: "매매법 연구", sns: "SNS 여론 확인", economy: "경제 리서치", paper: "모의투자 점검", chat: "동료 수다", computer: "컴퓨터 작업"};
let cycleTimer = 0, cycling = false, lastJob = "";
export const cycleState = () => ({cycling, lastJob});
export function nextCycleIn(){ const c = officeCfg(), last = +localStorage.getItem("officeLastCycle") || 0; return Math.max(0, last + c.cycleMin * 60e3 - Date.now()); }
export function startCycle(){
  if (cycleTimer) return;
  if (!localStorage.getItem("officeLastCycle")) localStorage.setItem("officeLastCycle", String(Date.now() - officeCfg().cycleMin * 60e3 + 45e3));
  cycleTimer = setInterval(() => cycle().catch(e => console.warn(e)), 20e3);
}
export async function cycle(force, onlyJob){
  const c = officeCfg();
  if (cycling || (!force && (!c.cycle || nextCycleIn() > 0))) return false;
  if (!hasAI()) return false;
  cycling = true; localStorage.setItem("officeLastCycle", String(Date.now()));
  try {
    await loadLog();
    await paperStep();
    if (running || chatting || queue.length) return true;
    if (usage().calls >= c.callMax){ if (!usage().capNoted){ bump("capNoted"); post({ch: "hq", kind: "system", text: `오늘 사무실 AI 호출 한도(${c.callMax}번)를 다 썼습니다. 모의투자 갱신과 차트·뉴스 확인은 계속합니다.`}); } return true; }
    let job = onlyJob;
    if (!job){ const i = +localStorage.getItem("officeJob") || 0; job = JOBS[i % JOBS.length]; localStorage.setItem("officeJob", String(i + 1)); }
    if (job === "paper" && !(await paperActive())) job = "research";
    if (job === "computer" && !computerOn()) job = "economy";
    lastJob = job; fire({kind: "cycle", job, label: JOB_KO[job]});
    if (job === "research") await research();
    else if (job === "sns") await snsCheck();
    else if (job === "economy") await economyCheck();
    else if (job === "paper") await paperReport();
    else if (job === "chat") await chatter(true);
    else if (job === "computer") await computerWork();
    return true;
  } catch(e){ post({ch: "hq", kind: "system", text: `${JOB_KO[lastJob] || "일"} 중 문제: ${String(e.message || e).slice(0, 120)}`}); return false; }
  finally { cycling = false; fire({kind: "cycle-end"}); setTimeout(pump, 200); }
}

// 혼자 하는 일 한 번: 배정 모델로 생각·말을 실시간으로 보여 주고, 빈 답이면 다른 모델로
async function solo(a, {room, sys, user, maxTokens = 900, temperature = 0.6, extra = {}, train = ""}){
  const models = assignModels();
  const target = models[a.id];
  const alt = fusionSources().find(t => t.model !== target?.model && !badModels()[t.model] && !/r1|reason|think|gpt-oss|qwq/i.test(t.model));
  const entry = post({ch: room || a.team, kind: "agent", agent: a.id, text: "", think: "", steps: [], live: true, model: target?.model || "", ...extra});
  fire({kind: "solo", agent: a, entry});
  let finalRaw = "";
  for (const tg of [target, alt, null].filter((t, i, arr) => i === arr.length - 1 || (t && arr.findIndex(x => x && x.model === t.model) === i))){
    let raw = "", think = "", last = 0;
    const show = () => { const mm = raw.match(/^💭\s*([^\n]*)\n?/); entry.think = (think + (mm ? "\n" + mm[1] : "")).trim(); entry.text = visibleText((mm ? raw.slice(mm[0].length) : raw).replace(/<think>[\s\S]*?(<\/think>|$)/g, "")).replace(/^\s*💭[^\n]*\n?/gm, "").trim();
      if (Date.now() - last > 150){ last = Date.now(); fire({kind: "delta", agent: a, entry}); } };
    try {
      bump("calls");
      const route = await brainStream({messages: [{role: "system", content: sys}, {role: "user", content: user}], role: a.role === "code" ? "code" : a.role === "reason" ? "reason" : "general",
        maxTokens, temperature, target: tg || undefined, fallback: true, onContent: d => { raw += d; show(); }, onThink: d => { think += d; show(); }});
      raw = splitThink(raw).body; show(); finalRaw = raw;
      entry.model = route?.model || tg?.model || entry.model;
    } catch(e){ entry.notes = [...(entry.notes || []), `${shortName(tg?.model)}: ${String(e.message || e).slice(0, 60)} → 다른 모델로`]; }
    if (entry.text || /```json|\{\s*"name"/.test(finalRaw)) break;
    markBad(tg?.model);
  }
  if (!entry.text && !finalRaw) entry.text = `(${a.name}: 이번에는 답하지 못했습니다)`;
  if (!entry.text && finalRaw) entry.text = (finalRaw.replace(/^\s*💭[^\n]*\n?/gm, "").replace(/```(?:json)?[\s\S]*?(```|$)/g, "").trim() || "전략을 만들었습니다") + "\n\n*(전략 JSON은 아래 백테스트 카드에 있습니다)*";
  // 자료를 읽고 해설한 일은 '자료 해설' 학습 예시로
  if (train && goodText(entry.text) && !isClaude(entry.model)){
    const id = await keep("office-solo", [{role: "user", content: `${train}\n\n${clip(user, 3500)}`}, {role: "assistant", content: noMind(entry.text)}], {agent: a.id, model: entry.model}).catch(() => null);
    if (id) entry.trainIds = [id];
  }
  entry.live = false; saveLog(); fire({kind: "said", agent: a, entry});
  return {...entry, raw: finalRaw};
}
const personaOf = (a, extra = "") => `너는 GH Nano 사무실 ${teamById(a.team).name}의 '${a.name}'(${a.title})다. 역할: ${a.duty}
이번 일에서는 도구를 부를 수 없으니 주어진 자료로만 말한다. 첫 줄은 '💭 '로 시작하는 한 문장 속마음(무엇을 보고 어떻게 판단하는지)이다. 그다음 동료에게 말하듯 자연스러운 한국어로 말한다. 데이터에 없는 숫자는 지어내지 않는다. ${extra}`;

/* ---- 모의투자 (코드) ---- */
async function paperActive(){ const P = await import("./paper.js"); const b = await P.loadBook(); return b.strategies.some(s => s.status === "active"); }
async function paperStep(){
  const P = await import("./paper.js");
  const fmt = n => Number(n).toLocaleString("ko-KR", {maximumFractionDigits: 2});
  await P.step(ev => {
    const s = ev.s, side = k => k === "long" ? "롱" : "숏";
    let text = "";
    if (ev.kind === "open") text = `📗 [${s.name}] ${s.market} ${side(ev.pos.side)} 진입 ${fmt(ev.pos.entry)} (x${ev.pos.lev}${ev.pos.sl ? `, 손절 ${fmt(ev.pos.sl)}` : ""}${ev.pos.tp ? `, 익절 ${fmt(ev.pos.tp)}` : ""})${ev.why ? " — " + ev.why : ""}`;
    else if (ev.kind === "close") text = `${ev.trade.pnl >= 0 ? "💰" : "📕"} [${s.name}] ${s.market} ${side(ev.trade.side)} 청산 ${fmt(ev.trade.exitP)} · ${ev.trade.pnl >= 0 ? "+" : ""}${fmt(ev.trade.pnl)} USDT (ROE ${ev.trade.roe.toFixed(1)}%) · ${ev.trade.reason}`;
    else if (ev.kind === "bust") text = `💥 [${s.name}] 가상 계좌가 파산해 운용을 멈췄습니다`;
    else return;
    post({ch: "quant", kind: "trade", agent: "trader", text});
    fire({kind: "trade", agent: agentById("trader"), text});
  });
  fire({kind: "paper"});
}
async function paperReport(){
  const P = await import("./paper.js"), a = agentById("trader");
  const book = await P.bookText();
  await solo(a, {room: "quant", sys: personaOf(a, "모의투자 현황을 팀에 3~5문장으로 보고한다. 잘 되는 전략과 안 되는 전략, 지금 포지션의 위험을 짚는다. 실제 주문이 아닌 가상 운용임을 잊지 않는다."), user: `모의투자 장부:\n${book}`, train: "아래 모의투자 장부를 보고 잘 되는 전략과 안 되는 전략, 지금 포지션의 위험을 3~5문장으로 해설해 줘."});
}

/* ---- 매매법 연구: 지표 29종 + 연구 카드 → 전략 JSON → 백테스트 · 과최적화 검사 → 통과하면 모의투자 ---- */
const MARKETS = [{market: "BTCUSDT", exchange: "binancef"}, {market: "ETHUSDT", exchange: "binancef"}, {market: "SOLUSDT", exchange: "binancef"}, {market: "XRPUSDT", exchange: "binancef"}];
function researchLog(){ try { return JSON.parse(localStorage.getItem("officeResearch") || "[]"); } catch(e){ return []; } }
function addResearch(r){ const l = researchLog(); l.push(r); try { localStorage.setItem("officeResearch", JSON.stringify(l.slice(-60))); } catch(e){} }
export const researchHistory = researchLog;
function pickJSON(t){
  const m = t.match(/```(?:json)?\s*([\s\S]*?)```/) || [null, (t.match(/\{[\s\S]*\}/) || [""])[0]];
  try { return JSON.parse(m[1]); } catch(e){ return null; }
}
async function research(){
  const Q = await import("./quant.js"), P = await import("./paper.js");
  const n = researchLog().length, a = agentById(n % 2 ? "qb" : "qa"), mk = MARKETS[Math.floor(n / 2) % MARKETS.length], tf = n % 3 === 2 ? "240" : "60";
  fire({kind: "busy", agent: a, text: `🧪 ${mk.market} ${tf === "60" ? "1시간" : "4시간"}봉 매매법 구상 중`});
  const {cs} = await candlesFor({market: mk.market, exchange: mk.exchange, timeframe: tf}, 1500);
  const snap = Q.snapshot(cs), cards = await Q.loadCards().catch(() => []);
  const tried = researchLog().slice(-8).map(r => `- ${r.name} (${r.market} ${r.tf}): ${r.pass ? "통과" : "불통과"}, 검증 구간 ${r.oos?.toFixed?.(1)}%`).join("\n");
  const sys = personaOf(a, "이번 일은 새 매매법 개발이다. 아래 형식 설명을 따라 전략 JSON 하나를 ```json 블록으로 쓰고, 블록 뒤에 왜 이 전략인지 2~3문장으로 말한다.") + "\n\n" + Q.STRATEGY_PROMPT + (cards.length ? "\n\n## 지금까지의 백테스트 연구 카드(참고)\n" + Q.cardsText(cards, 14) : "");
  const user = `시장: ${mk.market} (${mk.exchange === "binancef" ? "바이낸스 선물" : mk.exchange}) · ${tf === "60" ? "1시간" : "4시간"}봉 · 캔들 ${cs.length}개\n지금 차트(보조지표 29종):\n${snapText(snap)}\n${JSON.stringify(snap.ind || {}).slice(0, 2500)}\n\n최근 우리 팀이 시험한 전략(겹치지 않게):\n${tried || "(아직 없음)"}\n\n${a.id === "qa" ? "추세추종" : "역추세·변동성"} 계열로 새 전략 하나를 만들어 주세요. symbol은 ${mk.market}, interval은 ${tf === "60" ? "1h" : "4h"}.`;
  const e = await solo(a, {room: "quant", sys, user, maxTokens: 1600, temperature: 0.8});
  let spec = pickJSON(e.raw || e.text);
  if (!spec){ post({ch: "quant", kind: "system", text: `${a.name}의 답에서 전략 JSON을 찾지 못했습니다`}); addResearch({name: "(형식 오류)", market: mk.market, tf, pass: false, t: Date.now()}); return; }
  try { spec = Q.normalizeSpec({...spec, symbol: mk.market, interval: tf === "60" ? "1h" : "4h"}); }
  catch(err){ post({ch: "quant", kind: "system", text: `전략 형식 오류(${a.name}): ${err.message}`}); addResearch({name: spec.name || "(형식 오류)", market: mk.market, tf, pass: false, t: Date.now()}); return; }
  const v = agentById("val");
  fire({kind: "busy", agent: v, text: `🧮 ${spec.name} 백테스트 · 과최적화 검사 중`});
  const bt = Q.backtest(spec, cs), wf = Q.walkForward(spec, cs);
  const st = x => ({ret: +(x?.return_pct ?? 0), dd: +(x?.max_dd_pct ?? 0), win: +(x?.win_rate ?? 0), pf: x?.profit_factor == null ? null : +x.profit_factor, n: x?.n_trades ?? 0});
  post({ch: "quant", kind: "bt", agent: "val", name: spec.name, market: mk.market, tf, all: st(bt.stats), is: st(wf.is), oos: st(wf.oos), pass: wf.pass, reasons: wf.reasons, author: a.name, spec});
  addResearch({name: spec.name, market: mk.market, tf, pass: wf.pass, oos: +(wf.oos?.return_pct ?? 0), t: Date.now()});
  fire({kind: "bubble", agent: v, text: `${wf.pass ? "✅ 통과" : "❌ 불통과"}: ${spec.name} — ${wf.reasons.slice(0, 2).join(", ")}`});
  if (wf.pass && !isClaude(e.model)){
    // 검증을 통과한 매매법은 '전략 설계' 학습 예시로 (결과 숫자를 함께 적어 둔다)
    const ans = `${noMind(e.raw || "").replace(/```(?:json)?[\s\S]*?```/, "```json\n" + JSON.stringify(spec, null, 1) + "\n```")}\n\n백테스트(검증 구간): 수익 ${st(wf.oos).ret}% · 손익비 ${st(wf.oos).pf ?? "-"} · 거래 ${st(wf.oos).n}회`;
    await keep("office-strategy", [{role: "user", content: clip(user, 3000)}, {role: "assistant", content: ans}], {agent: a.id, model: e.model}).catch(() => null);
  }
  if (wf.pass){
    const s = await P.addStrategy({spec, market: mk.market, exchange: mk.exchange, tf, author: a.name, wf: {is: st(wf.is), oos: st(wf.oos)}});
    post({ch: "quant", kind: "system", text: `📈 모의투자 시작: ${s.name} (${mk.market} ${tf === "60" ? "1시간" : "4시간"}봉, ${a.name} 개발 · 다온 검증 통과) · 가상 10,000 USDT`});
    fire({kind: "trade", agent: agentById("trader"), text: `📈 ${s.name} 모의투자 시작합니다`});
  }
}

/* ---- SNS 여론 ---- */
const SNS_TOPICS = ["crypto", "us", "macro", "crypto"];
async function snsCheck(){
  const a = agentById("sns"), i = +localStorage.getItem("officeSns") || 0, topic = SNS_TOPICS[i % SNS_TOPICS.length];
  localStorage.setItem("officeSns", String(i + 1));
  fire({kind: "busy", agent: a, text: `📱 ${topic === "crypto" ? "코인" : topic === "us" ? "미국 주식" : "경제"} SNS 둘러보는 중`});
  const r = await TOOLS.sns_buzz.run({topic});
  for (const src of (r.sources || []).slice(0, 4)) post({ch: "data", kind: "work", agent: "sns", icon: "📱", text: src.title, url: src.url});
  await solo(a, {room: "data", sys: personaOf(a, "SNS에서 본 분위기를 3~5문장으로 해설한다. 사람들이 무엇에 흥분하거나 겁먹는지, 쏠림이 지나친지(역발상 신호인지) 말한다. SNS 글은 의견일 뿐이라는 점을 잊지 않는다."), user: r.text.slice(0, 5000), train: "아래 SNS 글과 공포·탐욕 지수를 보고 지금 사람들의 분위기와 쏠림을 해설해 줘. SNS 글은 의견이라는 점도 짚어 줘."});
  const fg = (r.text.match(/공포·탐욕 지수\] 오늘 (\d+)/) || [])[1];
  if (fg && (+fg <= 15 || +fg >= 85) && usage().auto < officeCfg().dailyMax)
    enqueue({topic: `코인 공포·탐욕 지수가 ${fg}로 극단입니다. SNS 분위기와 시장을 함께 점검해 주세요.`, room: "data", trigger: "event", title: `여론-극단-${fg}`, agents: ["sns", "coin_spot", "coin_fut"]});
}

/* ---- 경제 리서치 ---- */
const ECON_Q = ["오늘 미국 경제 뉴스 연준 금리 물가", "global economy outlook this week markets", "한국 경제 환율 수출 금리 뉴스", "oil price OPEC dollar news today", "중국 경기 부양책 뉴스", "부동산 시장 금리 대출 규제 뉴스", "AI 반도체 수요 실적 뉴스"];
async function economyCheck(){
  const i = +localStorage.getItem("officeEcon") || 0, q = ECON_Q[i % ECON_Q.length], a = agentById(i % 2 ? "research" : "macro");
  localStorage.setItem("officeEcon", String(i + 1));
  fire({kind: "busy", agent: a, text: `🔎 '${q}' 찾아보는 중`});
  const r = await TOOLS.web_search.run({query: q, n: 6});
  for (const src of (r.sources || []).slice(0, 3)) post({ch: a.team, kind: "work", agent: a.id, icon: "📰", text: src.title, url: src.url});
  await solo(a, {room: a.team, sys: personaOf(a, "검색 결과로 '지금 경제가 어떻게 돌아가는지'를 4~6문장으로 해설한다. 기사 제목을 나열하지 말고 흐름으로 묶고, 코인·주식·부동산에 주는 의미를 한 줄 덧붙인다. 근거 문장 끝에 [번호]."), user: `검색어: ${q}\n\n${String(r.text || "").slice(0, 6000)}`, train: "아래 검색 결과로 지금 경제가 어떻게 돌아가는지 흐름으로 해설하고, 코인·주식·부동산에 주는 의미를 덧붙여 줘. 근거 문장 끝에 [번호]."});
}

/* ---- 컴퓨터 작업 (문서/GHNano 사무실 폴더) ---- */
async function computerWork(){
  const {codeCall} = await import("./engine.js"), P = await import("./paper.js");
  const a = agentById("eng"), day = today();
  fire({kind: "busy", agent: a, text: "💻 사무실 폴더에 보고서 정리 중"});
  const book = await P.loadBook();
  const res = researchLog().slice(-20);
  const log = (await loadLog()).filter(e => e.kind === "agent" && !e.chat && e.text && Date.now() - e.t < 864e5).slice(-12);
  const md = `# GH Nano 사무실 일일 보고서 · ${day}\n\n## 모의투자\n${await P.bookText()}\n\n## 매매법 연구 (최근 ${res.length}건)\n${res.map(r => `- ${r.pass ? "✅" : "❌"} ${r.name} · ${r.market} ${r.tf} · 검증 구간 ${(+r.oos || 0).toFixed(1)}%`).join("\n") || "- 없음"}\n\n## 오늘 팀 발언 요약\n${log.map(e => `- **${agentById(e.agent)?.name}**: ${e.text.replace(/\s+/g, " ").slice(0, 200)}`).join("\n")}\n`;
  const csv = "strategy,market,side,entry_time,entry,exit_time,exit,pnl_usdt,roe_pct,reason\n" + book.strategies.flatMap(s => s.trades.map(t => [s.name, s.market, t.side, new Date(t.entryT).toISOString(), t.entryP, new Date(t.exitT).toISOString(), t.exitP, t.pnl.toFixed(2), t.roe.toFixed(2), t.reason].map(x => `"${String(x).replace(/"/g, '""')}"`).join(","))).join("\n");
  await codeCall("write", {ws: "office", path: `reports/${day}.md`, content: md});
  await codeCall("write", {ws: "office", path: "data/trades.csv", content: csv});
  for (const s of book.strategies.filter(x => x.status === "active")) await codeCall("write", {ws: "office", path: `strategies/${s.name.replace(/[\\/:*?"<>|]/g, "_")}.json`, content: JSON.stringify(s.spec, null, 2)});
  post({ch: "data", kind: "work", agent: "eng", icon: "💾", text: `문서/GHNano 사무실에 저장: reports/${day}.md · data/trades.csv · strategies/*.json`});
  // 세 번에 한 번은 직접 파이썬 분석 스크립트를 짜서 돌려 본다
  const k = +localStorage.getItem("officeComp") || 0; localStorage.setItem("officeComp", String(k + 1));
  if (k % 3 !== 2 || !book.strategies.some(s => s.trades.length)) return;
  const m = {id: uid(), room: "data", name: "데이터-분석", trigger: "auto", topic: "data/trades.csv(모의투자 거래 기록)를 분석하는 파이썬 스크립트 analysis/summary.py를 사무실 폴더에 만들고 실행해서, 전략별 승률·평균 손익·최대 연속 손실을 보고해 주세요. 파이썬이 없으면 그 사실만 보고합니다.", order: ["eng"], done: [], ctl: new AbortController(), t: Date.now(), models: assignModels()};
  await speak(a, m, [], m.models.eng, m.ctl.signal);
}

// GH Coin 엔진: 코인 전문 AI 에이전트 회사 (GH Coin 엔진에서 갈라져 나옴 — GH Nano 와 저장소를 섞지 않는다)
// 파이프라인(코드가 판정): 매매법 개발 → 백테스트(앞 70%/뒤 30% 검증) → 데모거래 → 관문 통과 시 실거래 후보 → 대표 승인 시 실거래
// 커스텀 지표 라인도 같은 단계를 따로 밟는다. 분석 팀(추세·타점·지지저항·익절손절·패턴·뉴스·상황판·ML·코인별)은 코드 계산 + AI 해설.
import { settings, saveSettings, idb, uid, brainStream, splitThink, overCap, provUse, LAUNCHER, providerCooling, deadModels, coolingInfo, PROVIDERS, modelKind, ollamaModels } from "../nuri-ai/engine.js";
import { runAgent, activeSkills, TOOLS, marketNews, candlesFor, visibleText, snapText, toModelMessages } from "../nuri-ai/agent.js";
import { fusionSources, TRAIN_SYS } from "../nuri-ai/train.js";

/* ============ 팀과 직원 (coin-org.js) ============ */
import { TEAMS, AGENTS, TEAM_LEAD, agentById, teamById, SKILL_AGENT, MARKET, TOPIC_LEAD, AGENDA as COIN_AGENDA, WATCH as COIN_WATCH,
  WATCH_OF as COIN_WATCH_OF, RELATED as COIN_RELATED, CLAUDE_TIER as COIN_TIER, COINS, coinById, TEAM_COLOR } from "./coin-org.js";
export { TEAMS, AGENTS, TEAM_LEAD, agentById, teamById, COINS, TEAM_COLOR };
// 사무실 일에 쓸 수 있는 모든 대화 모델 (연결된 모든 회사 · Gemini 포함). 학습 데이터 제외는 keep() 에서 따로 한다(isClaude)
let olCache = [];   // 내 PC Ollama 설치 모델 캐시 (cycle 에서 비차단 갱신)
export async function refreshOllama(){ try { olCache = await ollamaModels(); } catch (e) { olCache = []; } return olCache; }
export const teamLocal = () => localStorage.getItem("coinTeamLocal") === "1";   // 직원 전원 로컬(Ollama) 전용 모드 (뉴럴 데스크도 공유)
export function setTeamLocal(on){ localStorage.setItem("coinTeamLocal", on ? "1" : "0"); if (on) refreshOllama(); }
export const ollamaCache = () => olCache.slice();
// 클라우드(NVIDIA·SambaNova 등) 키 완전 삭제 — 완전 로컬 전환용. anthropic 은 별도라 남겨둔다(원하면 설정에서 삭제).
export function removeCloudKeys(){
  const removed = [];
  for (const id of Object.keys(PROVIDERS)){ if (id === "anthropic") continue; if (settings.keys[id]){ removed.push(id); delete settings.keys[id]; delete settings.provModels[id]; delete settings.pinModel[id]; } }
  if (settings.brain && PROVIDERS[settings.brain] && settings.brain !== "anthropic") settings.brain = "ollama";
  saveSettings(); fire({kind: "cfg"});
  return removed;
}
export function officeSources(){
  const out = [], seen = new Set();
  const ols = olCache.length ? olCache : (settings.olModel && settings.olOk ? [settings.olModel] : []);
  // 🖥 전원 로컬 전용: 설치된 Ollama 모델만으로 직원을 꾸린다 (무료·오프라인, API 한도 없음)
  if (teamLocal() && ols.length) return ols.map(m => ({ id: "ollama", model: m }));
  for (const id of Object.keys(PROVIDERS)){
    if (!settings.keys[id] || id === "anthropic" || overCap(id)) continue;
    const ms = settings.provModels[id]?.length ? settings.provModels[id] : PROVIDERS[id].defaults || [];
    for (const m of ms){ if (seen.has(m) || !["chat", "code", "reason"].includes(modelKind(m))) continue; seen.add(m); out.push({id, model: m}); }
  }
  // 내 PC Ollama 로컬 모델들도 직원으로 (오프라인·무료).
  for (const m of ols){ if (seen.has(m)) continue; seen.add(m); out.push({id: "ollama", model: m}); }
  return out;
}
const hasAI = () => officeSources().length > 0 || !!settings.keys.anthropic;
const DECIDE = /사도|살까|팔까|매수|매도|진입|청산|롱|숏|레버리지|포지션|투자|전략|백테스트|들어가|비중|손절|익절|전망|어때|괜찮|해도 될까|할까/;
const RESEARCH = /검색|찾아|조사|자료|논문|출처|리서치|비교해|후기|리뷰|최신 정보/;
const BUILD = /$^/;
// 장부도 GH Nano 와 따로
import("../nuri-ai/paper.js").then(P => P.setBookKey?.("coin:paper", 16)).catch(() => {});

/* ============ 직원마다 다른 AI 모델 배정 ============ */
// 연결된 모든 대화 모델 중에서, 역할에 맞는 종류를 우선해 서로 다른 모델을 고르게 나눠 준다
// 빈 답·오류가 난 모델은 오늘 하루 배정에서 뺀다
const badModels = () => { try { const o = JSON.parse(localStorage.getItem("coinBad") || "{}"); return o.day === today() ? o.m || {} : {}; } catch(e){ return {}; } };
function markBad(model){ if (!model) return; const m = badModels(); m[model] = (m[model] || 0) + 1; try { localStorage.setItem("coinBad", JSON.stringify({day: today(), m})); } catch(e){} }
// 사무실에 맞는 모델 점수: 크고 빠른 대화 모델 우선 · 영어로 길게 생각하는 추론 모델과 아주 작은 모델은 뒤로
// 직원·팀에 AI 모델 직접 배정 (key: 직원 id · "team:팀id" · "all", val: "회사id|모델" · 빈 값이면 자동)
export function setAssign(key, val){ const c = officeCfg(); c.assign = {...(c.assign || {})}; if (val) c.assign[key] = val; else delete c.assign[key]; saveSettings(); fire({kind: "cfg"}); }
export const getAssign = () => ({...(officeCfg().assign || {})});
// 고를 수 있는 모델 목록 (회사별, 사무실에 맞는 순)
export function modelChoices(){
  const list = officeSources().map(t => ({...t, name: PROVIDERS[t.id]?.name || (t.id === "ollama" ? "Ollama(내 컴퓨터)" : t.id)}));
  if (settings.keys.anthropic) for (const m of (settings.provModels.anthropic?.length ? settings.provModels.anthropic : PROVIDERS.anthropic?.defaults || [])) if (modelKind(m) === "chat" || /claude/.test(m)) list.push({id: "anthropic", model: m, name: "Claude"});
  return list.filter(x => modelScore(x.model) > -40).sort((a, b) => a.name.localeCompare(b.name) || modelScore(b.model) - modelScore(a.model));
}
export function modelScore(m){
  m = String(m || "").toLowerCase(); let s = 50;
  if (/(^|[^0-9.])(0\.5|1|1\.5|2|3|4|e2|e4)b\b|mini|nano|tiny|-small|lite/.test(m)) s -= 30;
  if (/70b|72b|90b|120b|123b|235b|253b|405b|480b|671b|large|kimi-k2|deepseek-v3|deepseek-v4|maverick|scout|glm-4\.[5-9]|qwen3-coder|mistral-medium|llama-3\.3-70|command-a/.test(m)) s += 25;
  if (/r1|qwq|think|reason|magistral|nemotron.*(super|ultra)|o[1-9]-/.test(m)) s -= 20;
  if (/gpt-oss/.test(m)) s -= 15;   // 사무실은 한국어 답이 중요 — gpt-oss는 영어로 길게 '생각만' 하는 경향이 있어 한 단계 뒤로(폴백으로는 남김)
  // 옛 세대·지원 끝나 가는 모델은 크기와 상관없이 뒤로 (llama2·codellama·chatqa·mixtral·gemma2·qwen1~2 등)
  if (/llama-?2|codellama|code-?llama|chatqa|mixtral|mistral-7b|gemma-?2|gemma-7b|qwen1|qwen-?2(?!\.5)|qwen2\.5-(?!coder-32)|yi-|falcon|baichuan|dbrx|arctic|jamba|phi-?3|nemotron-4|llama-?3-|llama3-|llama-?3\.1-(?!nemotron-ultra)|solar|granite-3\.0|deepseek-coder|starcoder/.test(m)) s -= 45;
  if (/guard|safety|embed|rerank|reward|parse|ocr|-vl|vision|audio|tts|whisper/.test(m)) s -= 100;
  const h = modelHealth()[m]; if (h) s -= Math.min(40, (h.slow || 0) * 8 + (h.fail || 0) * 6);
  return s;
}
// 모델 성적표 (스스로 배우기): 느림·실패가 쌓인 모델은 점점 덜 쓴다 (7일 지나면 잊음)
const HEALTH_KEY = "coinModelHealth";
export function modelHealth(){ try { const o = JSON.parse(localStorage.getItem(HEALTH_KEY) || "{}"); for (const k in o) if (Date.now() - (o[k].t || 0) > 7 * 864e5) delete o[k]; return o; } catch(e){ return {}; } }
function noteModel(model, what){ if (!model) return; const o = modelHealth(), k = String(model).toLowerCase(); const h = o[k] || {ok: 0, slow: 0, fail: 0}; h[what] = (h[what] || 0) + 1; if (what === "ok" && h.ok % 5 === 0){ h.slow = Math.max(0, h.slow - 1); h.fail = Math.max(0, h.fail - 1); } h.t = Date.now(); o[k] = h; try { localStorage.setItem(HEALTH_KEY, JSON.stringify(o)); } catch(e){} }
export function assignModels(){
  const dead = deadModels();
  // 없어진 모델 · 지금 한도에 걸려 쉬는 회사는 빼고 (다 빠지면 원래 목록)
  const live0 = officeSources().filter(t => !dead[t.model]), live = live0.filter(t => !providerCooling(t.id));
  const bad = badModels(), all = live.length >= 2 ? live : live0.length >= 2 ? live0 : officeSources(), ok = all.filter(t => !bad[t.model]);
  // Groq 무료는 분당 토큰이 아주 적어 도구가 붙는 긴 회의 프롬프트에 금방 막힌다 → 사무실에서는 뒤로
  const ranked = (ok.length >= 2 ? ok : all).map(t => ({t, sc: modelScore(t.model) - (t.id === "groq" ? 25 : 0)})).filter(x => x.sc > -40).sort((x, y) => y.sc - x.sc);
  // 상위 모델을 골고루 나눠 쓴다 — 점수 차가 크더라도 여러 모델을 풀에 넣어 직원마다 다른 모델을 쓰게 한다(다양성)
  const top = ranked.slice(0, Math.max(3, Math.min(6, ranked.length))).map(x => x.t);
  const pool = top.length ? top : ranked.map(x => x.t);
  const used = new Map(), out = {};
  for (const a of AGENTS){
    const fit = a.role === "code" ? pool.filter(t => /coder|code|devstral|kimi|qwen3/i.test(t.model)) : [];
    const list = (fit.length ? fit : pool).slice().sort((x, y) => (used.get(x.model) || 0) - (used.get(y.model) || 0));
    const pick = list[0];
    if (pick){ out[a.id] = pick; used.set(pick.model, (used.get(pick.model) || 0) + 1); }
  }
  // Claude 모드: 키가 있고 오늘 한도가 남아 있으면 직원 전원을 Claude로 (무료 API 한도 문제 해결)
  // 판단 책임이 큰 자리는 Opus, 반복 분석은 Sonnet, 가벼운 일은 Haiku (에이전트팀 세션과 같은 기준). 한도를 넘으면 무료 모델로 돌아간다.
  const cm = claudeModels();
  // '핵심 자리만' 모드: 판단 책임이 큰 자리와 팀장만 Claude, 나머지는 무료 모델 → 그 대화는 GH Nano 학습에 쓸 수 있다
  if (cm) for (const a of AGENTS){ if (claudeMode() === "key" && !(CLAUDE_TIER[a.id] === "opus" || a.lead)) continue; const m = cm[CLAUDE_TIER[a.id] || "sonnet"]; if (m && !bad[m]) out[a.id] = {id: "anthropic", model: m}; }
  // 대표가 직접 정한 배정이 가장 우선: 직원 → 팀 → 전원 순서 (그 회사 키가 있고 없어진 모델이 아닐 때)
  const asg = officeCfg().assign || {};
  for (const a of AGENTS){
    const v = asg[a.id] || asg["team:" + a.team] || asg.all; if (!v) continue;
    const i = v.indexOf("|"), id = v.slice(0, i), model = v.slice(i + 1);
    if ((settings.keys[id] || id === "ollama") && !dead[model]) out[a.id] = {id, model, pinned: true};
  }
  return out;
}
export const claudeMode = () => officeCfg().claudeMode || (officeCfg().claude === false ? "off" : "all");
export const CLAUDE_TIER = COIN_TIER; const _OLD_TIER = {strat: "opus", risk: "opus", val: "opus", qa: "opus", qb: "opus", lead: "sonnet", devil: "sonnet", aide: "haiku", dev: "sonnet", eng: "sonnet"};
export function claudeModels(){
  if (!settings.keys.anthropic || overCap("anthropic") || claudeMode() === "off") return null;
  const ms = settings.provModels.anthropic?.length ? settings.provModels.anthropic : [];
  const pick = (want, re) => ms.includes(want) ? want : ms.filter(m => re.test(m)).sort().reverse()[0] || want;
  return {opus: pick("claude-opus-5-5", /opus/), sonnet: pick("claude-sonnet-5-5", /sonnet/), haiku: pick("claude-haiku-4-5-20251001", /haiku/)};
}
// 모델 전체 켜기·초기화: 연결된 회사마다 '사용 모델'을 전체 기본 목록으로 되돌리고, 그동안 쌓인
// '없어진 모델·나쁜 모델·고정·전원배정' 기록을 싹 지워 다시 직원마다 서로 다른 모델이 배정되게 한다.
// → "모델이 자꾸 사라지거나 하나만 쓰여요" 를 한 번에 해결.
export function resetModels(){
  try { for (const k of ["deadModels", "coinBad", "coinModelHealth"]) localStorage.removeItem(k); } catch(e){}
  settings.provModels = settings.provModels || {};
  for (const id of Object.keys(PROVIDERS)) if (settings.keys[id] && PROVIDERS[id].defaults?.length) settings.provModels[id] = [...PROVIDERS[id].defaults];
  settings.pinModel = {}; settings.brain = "auto";
  const asg = {...(officeCfg().assign || {})}; for (const k of Object.keys(asg)) setAssign(k, "");
  saveSettings(); fire({kind: "cfg"});
  const models = [...new Set(Object.values(assignModels()).map(m => m.model))];
  return {models, count: models.length};
}

/* ============ 기록 (방 대화) ============ */
let LOG = null;
const LOG_KEY = "coin:log";
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
  if (settings.coinOffice && settings.coinOffice.v !== 2){ const o = settings.coinOffice; o.every = Math.max(o.every || 0, 60); o.chatEvery = Math.max(o.chatEvery || 0, 12); o.chatMax = Math.min(o.chatMax || 40, 40); o.callMax = Math.max(o.callMax || 0, 3000); o.v = 2; try { saveSettings(); } catch(e){} }   // 수다·시황 회의가 GPU를 독차지하지 않게(개발 업무 우선)
  settings.coinOffice = Object.assign({auto: true, every: 60, dailyMax: 10, alert: true, chat: true, chatEvery: 12, chatMax: 40, cycle: true, cycleMin: 3, callMax: 3000, computer: true, claude: true, train: true}, settings.coinOffice || {});
  return settings.coinOffice;
}
export function setOffice(patch){ Object.assign(officeCfg(), patch); saveSettings(); fire({kind: "cfg"}); }
const today = () => new Date().toLocaleDateString("sv-SE");
function usage(){ let u = {}; try { u = JSON.parse(localStorage.getItem("coinUsage") || "{}"); } catch(e){} return u.day === today() ? u : {day: today(), meetings: 0, calls: 0, auto: 0, chats: 0}; }
function bump(k, n = 1){ const u = usage(); u[k] = (u[k] || 0) + n; try { localStorage.setItem("coinUsage", JSON.stringify(u)); } catch(e){} fire({kind: "usage", usage: u}); }
export const officeUsage = usage;

/* ============ 직원들의 대화를 GH Nano 학습 데이터로 남기기 ============ */
// - 회의: 질문 → <think>팀원들의 분석·반론·리스크</think> + 팀장 결론 (작은 모델이 혼자서도 '팀 토론'을 거쳐 답하게)
// - 첫 분석가의 실제 도구 사용 과정, 자료를 읽고 해설한 일(SNS·경제·모의투자 보고), 검증을 통과한 매매법, 동료 수다
// Claude가 쓴 글은 약관에 따라 넣지 않는다. 회의록에서 👎를 누르면 그 예시는 지운다.
// 약관상 GH Nano 학습에 쓰면 안 되는 모델(Claude·Gemini·OpenAI 유료)의 글은 학습 데이터에서 뺀다
const isClaude = m => /claude|gemini|(^|\/)(gpt-(?!oss)|o[1-9](-|$)|chatgpt)/i.test(String(m || ""));
const goodText = t => !!t && t.length >= 30 && !/^\(.{0,20}(답하지 못했|빈 답)/.test(t);
const clip = (t, n) => { t = String(t || ""); return t.length > n ? t.slice(0, n) + "…" : t; };
const noMind = t => String(t || "").replace(/^\s*💭[^\n]*\n?/gm, "").trim();
async function keep(kind, messages, meta = {}){
  if (officeCfg().train === false) return null;
  const minLen = meta.minLen || 30; delete meta.minLen;
  if (!messages.length || messages.at(-1).role !== "assistant" || messages.some(x => x.role === "assistant" && (String(x.content || "").length < minLen || /답하지 못했|빈 답\)/.test(x.content)))) return null;
  const id = uid();
  await idb.put("train:" + id, {id, t: Date.now(), src: "office", kind, app: "ghcoin", messages: [{role: "system", content: TRAIN_SYS("chat")}, ...messages], ...meta});
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
    // 질문 단어 → 담당 팀장 (코인 이름이면 그 코인 팀장)
    for (const [re, id] of TOPIC_LEAD) if (re.test(t) && !lead.includes(id)) lead.push(id);
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
// 말로 시킨 '일'은 회의만 하지 않고 실제 업무를 바로 돌린다 (결과 카드는 그 팀 방에)
const ACTIONS = [
  {job: "cdev", re: /커스텀.*(지표|매매법|전략).*(만들|찾|개발|짜|연구|백테스트)/, say: "커스텀 지표 개발팀이 지금 바로 수식 지표로 매매법을 만들어 커스텀 백테스트팀이 검증합니다"},
  {job: "dev", re: /(매매법|전략|지표).*(만들|찾|개발|짜|연구|발굴|백테스트)|(만들|찾|개발|짜).*(매매법|전략)|백테스트\s*(해|돌려)/, say: "매매법 개발팀이 지금 바로 모든 보조지표로 매매법을 만들어 백테스트팀이 검증합니다"},
  {job: "plan", re: /플래너|리서치\s*계획|할\s*일\s*목록|todolist|투두|계획\s*세워|다음\s*할\s*일|리서치\s*보드/i, say: "리서치 플래너가 지금 바로 상태를 보고 할 일 목록(todolist)을 만들고 최우선 리서치를 워커에게 배정합니다"},
  {job: "sent", re: /감정|심리|센티먼트|sentiment|여론\s*분위기|시장\s*분위기|공포.{0,2}탐욕/i, say: "뉴스·경제지표팀이 지금 바로 자체 감정 엔진으로 뉴스·여론의 시장 심리(0~100)를 분석합니다"},
  {job: "pos", re: /단타|스윙|스캘핑|포지션\s*(추천|알려|잡아|줘|어때|봐)|포지션\s*추천|지금\s*(사|팔|들어가)/i, say: "진입 타점팀이 지금 바로 자체 AI + ATR 로 단타·스윙 포지션(방향·진입·손절·익절·손익비)을 추천합니다"},
  {job: "contest", re: /콘테스트|대회|리더보드|전략\s*순위|전략\s*경쟁|어느\s*전략.{0,6}(좋|나)|best\s*strategy/i, say: "데모거래팀이 지금 바로 전략 콘테스트를 열어 데모 전략들을 성과로 겨뤄 순위를 매깁니다"},
  {job: "ensemble", re: /앙상블\s*포트|포트폴리오|분산\s*(투자|운용|배분)|비중\s*(배분|분배|나눠)|여러\s*전략.{0,6}(묶|섞|합)|자본\s*배분/i, say: "데모거래팀이 신뢰점수 상위 전략들을 묶어 분산 포트폴리오(전략별 자본 비중)를 제안합니다"},
  {job: "reality", re: /1\s*억|얼마.{0,4}(벌|버|먹|불)|부자|대박|떡상|목표\s*수익|돈.{0,4}벌어|며칠.{0,6}얼마|현실\s*점검|가능\s*하냐|될\s*수\s*있/i, say: "CEO실이 '정직한 현실 점검'으로 목표 수익의 실제 도달·파산 확률을 몬테카를로로 솔직히 보여줍니다 (희망 회로 금지)"},
  {job: "preset", re: /프리셋|준비된\s*매매법|기본\s*전략|고전\s*전략|rsi.{0,4}macd|RSI.{0,4}MACD|프리\s*셋|전략\s*비교/i, say: "준비된 매매법 프리셋(RSI·MACD·볼린저·스토캐스틱·EMA 등)을 AI 없이 바로 백테스트해 수익률·신뢰점수로 비교합니다 (io-uty 아이디어)"},
  {job: "rtentry", re: /실시간\s*진입|지금\s*(진입|들어가|롱|숏)|손\s*매매|시장가\s*진입|어디서\s*(들어가|진입)|진입\s*(자리|추천|알려)/i, say: "진입 타점팀과 뉴럴 데스크가 지금 바로 모든 코인의 실시간 진입 자리(손절·익절·유사상황 승률)를 계산하고 토론합니다"},
  {job: "evo", re: /매매법\s*.{0,6}(조합|섞|합쳐|개선|수정|진화|변형)|(조합|섞어|합쳐).{0,6}(매매법|전략)|전략\s*.{0,4}(조합|합치)/i, say: "매매법 개발팀이 지금 바로 매매법 개선(손익비·보유)·수정(필터)·조합(A+B)을 백테스트로 실험합니다 (검증 통과만 채택)"},
  {job: "survival", re: /생존|다윈|진화|해고|도태|번식|자연\s*선택|개발자.{0,4}(성과|평가|kpi|KPI)|KPI/i, say: "생존 경쟁 — 개발자 KPI(성과 못 내면 경고·재교육)와 다윈 전략 진화(잘하는 전략을 변이시켜 부모보다 나은 후손만 데모로 번식)를 돌립니다 (가상자금)"},
  {job: "track", re: /적중률|캘리브레이션|승률|예측.{0,6}(맞|정확|적중)|얼마나\s*맞|확신도\s*(검증|맞)/i, say: "CEO실에서 QA가 지금까지의 예측을 채점해 적중률과 확신도 캘리브레이션을 보고합니다"},
  {job: "report", re: /대시보드|성과\s*(보여|요약|대시|정리|보고|어때)|전체\s*수익|실적\s*(보|요약)|얼마.{0,3}벌/i, say: "CEO가 지금 바로 성과 대시보드(총 손익·전략별 기여·적중률·심리)를 한눈에 정리합니다"},
  {job: "selfai", re: /자체\s*ai|자체\s*인공지능|앙상블|트레이딩\s*데스크|자체\s*모델|ghcoinai|확신도\s*순위|ai\s*데스크/i, say: "자체 AI 데스크가 지금 바로 외부 키 없이 앙상블(기술 평점·멀티 시간대·ML·알파)로 코인 방향·확신도 순위를 냅니다"},
  {job: "botopt", re: /(자동매매\s*봇|선물\s*봇|트레이딩\s*봇|봇)\s*.{0,6}(자동\s*)?(개선|다듬|최적화|하이퍼옵트)|(보조지표|지표)\s*.{0,6}(자동\s*)?(개선|최적화|튜닝)/i, say: "선물 자동매매봇팀이 지금 바로 데모 봇의 보조지표·위험값을 하이퍼옵트로 자동 개선하고 검증 구간·견고성까지 확인합니다"},
  {job: "bot", re: /자동매매\s*봇|선물\s*봇|트레이딩\s*봇|그리드\s*봇|dca\s*봇|봇\s*(만들|돌려|전략|추가)|passivbot|jesse|octobot/i, say: "선물 자동매매봇팀이 지금 바로 봇 전략을 만들어 백테스트하고 통과하면 데모에 올립니다"},
  {job: "ic", re: /투자위원회|강세.{0,6}약세.{0,6}토론|살지.{0,4}팔지|(매수|매도).{0,6}결정/, say: "투자위원회가 지금 바로 애널리스트 보고 → 강세·약세 토론 → 리스크 토론 → 위원장 결정을 합니다"},
  {job: "qrisk", re: /(var|cvar|변동성|상관|베타|스트레스|리스크).{0,10}(계산|분석|봐|점검|알려)|결정표|주문 전 점검/i, say: "퀀트 리스크팀이 지금 바로 VaR·상관·스트레스·주문 전 점검을 계산합니다"},
  {job: "data", re: /거래소.{0,6}(비교|차이|가격차)|김치\s*프리미엄|데이터.{0,4}(품질|점검)|감사 기록/, say: "데이터 플랫폼팀이 지금 바로 8개 거래소 시세·펀딩과 데이터 품질을 비교합니다"},
  {job: "opt", re: /하이퍼옵트|최적화|파라미터.{0,6}(찾|튜닝|다듬)|hyperopt/i, say: "전략 최적화팀이 지금 바로 데모 전략을 하이퍼옵트하고 검증 구간·견고성까지 확인합니다"},
  {job: "patscan", re: /(쌍봉|쌍바닥|헤드앤숄더|삼각수렴|쐐기|깃발|vcp|채널|패턴).{0,8}(스캔|찾아|전부|모든)/i, say: "차트·캔들 패턴팀이 지금 바로 6개 코인 × 2개 시간대 패턴을 스캔합니다"},
  {job: "feeds", re: /경제\s*(캘린더|일정)|오늘.{0,4}(일정|발표)|dvol|sofr/i, say: "뉴스·경제지표팀이 지금 바로 경제 캘린더·금리·코인 변동성 지수를 받습니다"},
  {job: "drift", re: /성과.{0,6}(악화|이동|떨어|감지)|런\s*차트/, say: "데모거래팀이 지금 바로 전략 성과 이동을 런 차트로 감지합니다"},
  {job: "alpha", re: /알파\s*팩터|팩터.{0,4}(순위|랭킹)/, say: "머신러닝·딥러닝팀이 지금 바로 알파 팩터 순위를 계산합니다"},
  {job: "combo", re: /(종합|모든|전체|실시간).{0,8}(지표|보조지표).*(타점|추세|분석|봐|알려|잡아)|실시간.{0,6}(타점|추세)|지표.{0,4}(조합|종합)/, say: "실시간 종합 지표 타점팀이 지금 바로 모든 보조지표를 4개 시간대로 계산해 추세와 타점을 잡습니다"},
  {job: "trend", re: /추세.*(분석|봐|알려|어때)/, say: "추세 분석팀이 지금 바로 다중 시간대 추세를 봅니다"},
  {job: "entry", re: /(타점|진입).*(분석|봐|알려|어디|잡아)/, say: "진입 타점팀이 지금 바로 진입 자리를 계산합니다"},
  {job: "sr", re: /(지지|저항|매물대).*(분석|봐|알려|어디)/, say: "지지·저항팀이 지금 바로 가격대를 계산합니다"},
  {job: "tpsl", re: /(손절|익절).*(관리|점검|봐|알려)/, say: "익절·손절 관리팀이 지금 바로 포지션을 점검합니다"},
  {job: "pattern", re: /(패턴|캔들).*(분석|봐|찾|알려)/, say: "차트·캔들 패턴팀이 지금 바로 패턴을 찾습니다"},
  {job: "situ", re: /(상황판|전체 코인|코인 상황|시장 상황)/, say: "코인 상황판팀이 지금 바로 전체 코인 상황을 정리합니다"},
  {job: "ind", re: /보조지표.*(분석|봐|알려|해석)/, say: "보조지표 분석팀이 지금 바로 지표를 계산합니다"},
  {job: "ml", re: /(머신러닝|딥러닝).*(해|돌려|분석|예측)/, say: "머신러닝·딥러닝팀이 지금 바로 모델을 학습합니다"},
  {job: "news", re: /(뉴스|기사|경제지표).*(분석|봐|알려|찾)/, say: "뉴스·경제지표팀이 지금 바로 찾아 봅니다"},
  {job: "forecast", re: /(방향|예측|전망).*(토론|예측해|맞춰)/, say: "진입 타점팀이 지금 바로 방향 예측 토론을 엽니다"},
  {job: "promote", re: /(데모|실거래).*(심사|승격|관문)/, say: "데모거래팀이 지금 바로 실거래 관문을 심사합니다"},
  {job: "selfdev", re: /(코드|오류|버그|에러).*(고쳐|수정|찾)/, say: "CTO가 지금 바로 오류를 찾아 코드 수정안을 만듭니다"},
];
let userNote = "";
async function runJobNow(job, note){
  userNote = note;
  try { await (JOB_FN()[job] || (() => research("std")))(); }
  catch(e){ post({ch: JOB_TEAM[job] || "hq", kind: "system", text: `${JOB_KO[job]} 중 문제: ${String(e.message || e).slice(0, 120)}`}); }
  finally { userNote = ""; }
}
export async function ask(text, {room = "hq"} = {}){
  await loadLog();
  post({ch: room, kind: "user", text});
  const act = ACTIONS.find(x => x.re.test(text));
  if (act){ post({ch: JOB_TEAM[act.job] || room, kind: "system", text: `▶ ${act.say} (결과는 #${teamById(JOB_TEAM[act.job])?.name || "업무"} 방 카드로)`}); fire({kind: "cycle", job: act.job, label: JOB_KO[act.job]}); runJobNow(act.job, text).finally(() => fire({kind: "cycle-end"})); }
  // 대표님(사용자) 질문이 먼저: 진행 중인 자동 회의는 잠시 멈췄다가 답한 뒤 다시 하고, 질문은 대기열 맨 앞에 넣는다
  if (running && running.trigger !== "user"){
    const r = running; r.preempted = true;
    post({ch: room, kind: "system", text: `질문 먼저 답합니다 · '${r.name}' 회의는 잠시 멈췄다가 이어서 합니다`});
    r.ctl.abort();
  } else if (running || queue.length) post({ch: room, kind: "system", text: "질문을 받았습니다 · 앞 질문 다음에 바로 답합니다"});
  return new Promise(res => { const at = queue.findIndex(j => j.trigger !== "user"); queue.splice(at < 0 ? queue.length : at, 0, {topic: text, room, trigger: "user", res}); pump(); });
}
export function stopMeeting(){ running?.ctl.abort(); queue.length = 0; }
function enqueue(m){
  return new Promise(res => { queue.push({...m, res}); pump(); });
}
async function pump(){
  if (running || !queue.length) return;
  if (chatting && queue[0].trigger !== "user"){ setTimeout(pump, 1500); return; }
  const job = queue.shift();
  const ctl = new AbortController();
  let order = planMeeting(job.topic, job.room, job.agents);
  // 대표님 질문은 빨리: 분석가 최대 2명 + (리스크) + 팀장 정리
  if (job.trigger === "user" && order.length > 4){
    const rest = order.filter(x => x !== "lead"), keep = [...new Set([...rest.filter(x => !["devil", "risk", "val"].includes(x)).slice(0, 2), ...(rest.includes("risk") ? ["risk"] : [])])];
    order = keep.length > 1 || order.includes("lead") ? [...keep, "lead"] : keep;
  }
  const models = assignModels();
  const room = teamById(job.room) || TEAMS[0];
  const name = job.title || (job.trigger === "user" ? "질문 · " + job.topic.replace(/\s+/g, " ").slice(0, 18) : job.topic.slice(0, 20));
  // 회의 장소: 한 팀끼리면 그 팀 자리에서, 여러 팀이면 대회의실, CEO가 부른 전사 회의도 대회의실
  const teamsIn = [...new Set(order.map(id => agentById(id)?.team).filter(Boolean))];
  const place = job.place || (teamsIn.length === 1 ? teamsIn[0] : teamsIn.length === 2 && teamsIn.includes(job.room) && !order.includes("lead") ? job.room : "meet");
  const m = running = {id: uid(), room: job.room, name, trigger: job.trigger, topic: job.topic, order, done: [], ctl, t: Date.now(), models, place, deadline: Date.now() + (job.trigger === "user" ? 6 * 60e3 : 10 * 60e3)};
  bump("meetings"); if (job.trigger !== "user") bump("auto");
  post({ch: job.room, kind: "divider", text: `회의 · #${name} · ${new Set(order).size}명 참석`, meeting: m.id});
  if (job.trigger === "user") post({ch: job.room, kind: "system", text: `${[...new Set(order)].map(id => agentById(id)?.name).filter(Boolean).join(" → ")} 순서로 답합니다 · 보통 1~3분 (최대 6분)`, meeting: m.id});
  fire({kind: "start", meeting: m});
  const turns = [];
  try {
    for (let i = 0; i < m.order.length && i < 8; i++){
      if (ctl.signal.aborted) break;
      // 회의 시간 한도를 넘기면 남은 사람은 건너뛰고 팀장이 지금까지 내용으로 정리
      if (Date.now() > m.deadline && m.order[i] !== "lead" && m.order.includes("lead") && turns.length){ if (!m.cut){ m.cut = true; post({ch: m.room, kind: "system", text: "시간이 길어져 팀장이 지금까지 내용으로 정리합니다", meeting: m.id}); } continue; }
      if (Date.now() > m.deadline + 120e3) break;
      if (officePaused() && job.trigger !== "user" && turns.length){ post({ch: m.room, kind: "system", text: "AI 한도 때문에 이 회의는 여기서 줄입니다", meeting: m.id}); break; }
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
    if (m.preempted) queue.push(job);   // 사용자 질문 때문에 멈춘 회의는 질문에 답한 뒤 다시
    else {
      post({ch: m.room, kind: "system", text: "회의 중단: " + (e.message || e), meeting: m.id});
      job.res?.({meeting: m, turns, error: e.message});
    }
  } finally {
    running = null; fire({kind: "end", meeting: m});
    setTimeout(pump, 300);
  }
}
// 대표님이 '뭐 하고 있어?' 같은 걸 물으면 답할 수 있게: 지금 사무실 상황 요약 (코드가 만든 사실)
function statusText(){
  const recent = (LOG || []).filter(e => ["work", "bt", "re", "arch", "ml", "macro", "forecast", "biz", "files", "task", "report"].includes(e.kind)).slice(-8)
    .map(e => `- ${new Date(e.t).toLocaleTimeString("ko-KR", {hour: "2-digit", minute: "2-digit"})} ${agentById(e.agent)?.name || ""} ${e.kind === "bt" ? `매매법 '${e.name}' ${e.pass ? "통과" : "불통과"}` : e.kind === "re" ? `재개발 후보 ${e.items?.length || 0}곳` : e.kind === "arch" ? `설계안 '${e.name}'` : e.kind === "biz" ? `사업 '${e.name}' ${String(e.verdict || "").split(" — ")[0]}` : e.kind === "task" ? `과제 '${e.title}' ${e.status}` : String(e.text || e.title || e.name || e.kind).slice(0, 60)}`).join("\n");
  const open = backlog().filter(x => x.status !== "done").slice(0, 4).map(x => `- ${teamById(x.team)?.name}: ${x.title}`).join("\n");
  return `[지금 사무실 상황 · 코드가 확인한 사실]\n진행 중인 회의: ${running && running.trigger !== "user" ? running.name : "없음"} · 지금 하는 업무: ${cycling ? JOB_KO[lastJob] || lastJob : "없음"} · 다음 업무: ${JOB_KO[JOBS[(+localStorage.getItem("coinJob") || 0) % JOBS.length]]}\n최근에 한 일:\n${recent || "- (아직 없음)"}\n남은 성장 과제:\n${open || "- (없음)"}${comboText() ? "\n" + comboText() : ""}`;
}
// 같은 이유가 반복되면 한 줄로 묶는다 ("… → 다른 모델로 (3번)")
function addNote2(entry, text){
  const key = text.replace(/^[^:]+:\s*/, ""), list = entry.notes || (entry.notes = []);
  const i = list.findIndex(n => n.replace(/^[^:]+:\s*/, "").replace(/ → 다른 모델로.*$/, "") === key);
  if (i >= 0){ const n = (+(list[i].match(/\((\d+)번\)$/) || [])[1] || 1) + 1; list[i] = list[i].replace(/ → 다른 모델로.*$/, "") + ` → 다른 모델로 (${n}번)`; }
  else list.push(text + " → 다른 모델로");
}
function transcript(m, turns){
  return turns.map(t => `[${t.agent.name} · ${t.agent.title}]\n${t.text.slice(0, 2500)}`).join("\n\n");
}
async function speak(a, m, turns, target, signal){
  const team = teamById(a.team);
  const mates = AGENTS.filter(x => x.id !== a.id && x.id !== "lead" && (x.team === a.team || x.lead)).map(x => `@${x.name}(${x.title})`).join(", ");
  const isLead = a.id === "lead";
  const prev = turns.at(-1)?.agent;
  const persona = `[GH Coin · 에이전트 팀 회의]
너는 GH Coin ${team.name}의 '${a.name}'(${a.title})다. 지금 동료들과 자유롭게 토론하는 회의 중이다.
- 네 역할: ${a.duty}
- 답의 첫 줄은 반드시 '💭 '로 시작하는 한 문장 속마음이다(무엇을 확인하고 어떻게 판단하려는지). 그다음 줄부터 말한다.
- ${prev ? `앞사람(${prev.name})의 말에 이름을 불러 반응하며 시작한다(동의·보충·반박). ` : ""}같은 말은 반복하지 말고 네 전문 분야 관점을 더한다. 다른 전문가가 꼭 필요하면 @이름 으로 한 명만 부른다(동료: ${mates}).
- 반드시 한국어로만 쓴다. 영어로 생각하거나 '어떻게 답할지' 계획을 쓰지 말고 바로 말한다.
- 회사 동료와 대화하듯 자연스러운 한국어로 말한다. 숫자 나열이 아니라 해설로 말한다. 수치는 도구로 확인한 것만 쓰고 지어내지 않는다. 차트·뉴스를 봤다면 무엇을 봤는지 말한다.
${notesText(a.team)}- ${isLead ? "너는 마지막 정리 담당이다. 사용자에게 주는 최종 답을 결론부터 짧고 쉽게 쓴다(5~8줄, 꼭 필요할 때만 표)." : "3~5문장으로 짧게. 사용자에게 주는 최종 답은 팀장이 정리하니, 너는 네 판단과 근거 한두 개에 집중한다."}`;
  const ask = `${m.trigger === "user" ? "사용자 질문" : "회의 안건"}: ${m.topic}\n\n${m.trigger === "user" ? statusText() + "\n\n" : ""}${turns.length ? "지금까지 회의 내용:\n" + transcript(m, turns) + "\n\n" : ""}이제 ${a.name}(${a.title}) 차례입니다.`;
  const entry = post({ch: m.room, kind: "agent", agent: a.id, text: "", think: "", steps: [], meeting: m.id, live: true, model: target?.model || ""});
  fire({kind: "turn", meeting: m, agent: a, entry});
  // 배정 모델 → (빈 답이면) 다른 모델 → 자동 선택 순서로 다시 시도
  const cm = claudeModels();
  const alt = cm && target?.model !== cm.sonnet ? {id: "anthropic", model: cm.sonnet} : officeSources().filter(t => t.model !== target?.model && !badModels()[t.model]).sort((x, y) => modelScore(y.model) - modelScore(x.model))[0];
  const tries = [target, alt, null].filter((t, i, arr) => i === arr.length - 1 || (t && arr.findIndex(x => x && x.model === t.model) === i));
  let lastMsg = null;
  const turnEnd = Math.min(m.deadline || Infinity, Date.now() + (m.trigger === "user" ? 200e3 : 360e3) * (officeSources().every(x => x.id === "ollama") ? 2 : 1));   // 로컬 전용이면 차례 시간 2배   // 한 사람 차례 전체 시간 한도 (모델을 바꿔 다시 해도)
  for (const tg of tries){
    if (Date.now() > turnEnd - 15e3) break;
    const msg = lastMsg = {role: "assistant", parts: [], mode: "chat", ts: Date.now()};
    let last = 0, lastTool = "";
    const onUpdate = () => {
      read(msg, entry);
      const tool = entry.steps.at(-1), sig = tool ? tool.act + tool.status : "";
      if (sig !== lastTool){ lastTool = sig; fire({kind: "tool", meeting: m, agent: a, entry, step: tool}); }
      if (Date.now() - last > 150){ last = Date.now(); fire({kind: "delta", meeting: m, agent: a, entry}); }
    };
    let err = null;
    // 느린 모델은 끊고 다음 모델로: 도구도 안 쓰고 75초 동안 말이 없거나, 전체 4분을 넘기면
    const tctl = new AbortController(), t0 = Date.now(); let slow = false;
    const relay = () => tctl.abort(); signal.addEventListener("abort", relay, {once: true});
    const userQ = m.trigger === "user", locT = !tg || tg.id === "ollama", firstMs = locT ? 200e3 : userQ ? 60e3 : 75e3, totalMs = locT ? 420e3 : userQ ? 150e3 : 240e3;   // 로컬 모델은 긴 프롬프트를 읽는 데 오래 걸림
    const watch = setInterval(() => { const el = Date.now() - t0; if ((!entry.text && !entry.steps.length && el > firstMs) || el > totalMs || Date.now() > turnEnd){ slow = true; tctl.abort(); } }, 2000);
    // 도구(백테스트 등)가 중단 신호를 무시해도 시간이 되면 무조건 다음으로 넘어간다
    const hardStop = new Promise((_, rej) => tctl.signal.addEventListener("abort", () => rej(Object.assign(new Error("중단"), {name: "AbortError"})), {once: true}));
    hardStop.catch(() => {});
    try {
      bump("calls");
      await Promise.race([runAgent({mode: "chat", history: [{role: "user", content: ask}], msg, signal: tctl.signal, onUpdate, think: false, workspace: "", persona, forceSkills: a.skills, target: tg || undefined,
        maxSteps: isLead || a.id === "devil" ? 2 : m.trigger === "user" ? 3 : 5, openArtifact: async () => null, askPermission: officePermission,
        office: true, officeTools: a.computer && computerOn() ? ["office_ls", "office_read", "office_write", "office_run"] : []}), hardStop]);
    } catch (e){ if (signal.aborted) throw e; err = slow ? new Error("응답이 너무 느림") : e; }
    finally { clearInterval(watch); signal.removeEventListener("abort", relay); }
    entry.thinking = false;
    read(msg, entry);
    entry.model = msg.route?.model || tg?.model || entry.model;
    noteModel(entry.model, entry.text && !slow ? "ok" : slow ? "slow" : "fail");
    if (entry.text) break;
    markBad(tg?.model || msg.route?.model);
    const why = err ? (err.message || String(err)).slice(0, 80) : msg.parts.some(p => p.think || englishy(p.text || "")) ? "생각만 하고 한국어 답을 내지 못함" : "빈 답";
    if (err && isLimit(why)) noteLimit();
    addNote2(entry, `${shortName(entry.model)}: ${why}`);
    fire({kind: "delta", meeting: m, agent: a, entry});
    if (err && isLimit(why) && officeSources().every(t => providerCooling(t.id))) break;   // 다 막혔으면 더 두드리지 않는다
  }
  if (!entry.text){
    // 마지막 수단: 모델이 한국어 최종 답을 못 냈어도 생각(영어 추론)이 있으면 그대로 옮겨 보여 준다(죽은 답 대신). 정상 경로엔 영향 없음.
    const sv = (lastMsg?.parts || []).map(p => p.text || p.think || "").join(" ").replace(/<think>[\s\S]*?<\/think>/g, "").replace(/\s+/g, " ").trim();
    entry.text = (entry.notes || []).some(n => isLimit(n)) ? `(${a.name}: 무료 AI 한도에 걸려 이번에는 쉬었습니다 · 잠시 뒤 다시 합니다)`
      : sv.length > 20 ? `${sv.slice(0, 600)}\n\n*(모델이 한국어 최종 답을 못 내 생각을 그대로 옮겼습니다)*`
      : `(${a.name}: 연결된 모델들이 이번에는 답하지 못했습니다)`;
  }
  entry.tools = entry.steps.map(x => x.act);
  captureFiles(entry, a.team).catch(() => {});
  // 첫 분석가가 실제 도구를 쓴 과정은 '도구 사용' 학습 예시로 (앞사람 발언에 기대지 않는 차례만)
  if (!turns.length && lastMsg && entry.steps.some(x => x.status === "done") && goodText(entry.text) && !isClaude(entry.model) && !lastMsg.parts.some(p => p.type === "tool" && p.status === "error")){
    const conv = toModelMessages([{role: "user", content: m.topic}, lastMsg], 1e9, 3000).map(x => x.role === "assistant" ? {...x, content: noMind(x.content)} : x).filter(x => x.content);
    const id = await keep("office-tool", conv, {agent: a.id, model: entry.model}).catch(() => null);
    if (id) entry.trainIds = [id];
  } else if (!turns.length && m.order.length === 1 && m.trigger === "auto" && goodText(entry.text) && !isClaude(entry.model)){
    // 혼자 맡은 과제(성장 과제·신사업 개발)는 도구를 안 썼어도 '과제 → 결과' 학습 예시로
    const id = await keep("office-task", [{role: "user", content: m.topic}, {role: "assistant", content: noMind(entry.text)}], {agent: a.id, model: entry.model}).catch(() => null);
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
/* ============ 결과물 보관함: 사업계획서·보고서·설계안·매매법·직원이 만든 파일 ============ */
// 앱 안(IndexedDB)에 항상 보관 → [📁 결과물]에서 보기·내려받기. GHNano.exe 면 문서/GHNano 사무실 폴더에도 같은 파일이 저장된다.
const DOC_PREFIX = "coindoc:";
const docKey = path => DOC_PREFIX + String(path || uid()).replace(/[^\w가-힣./-]+/g, "_").slice(0, 160);
export async function saveDoc({title, path = "", content = "", team = "hq", agent = "", mime = ""}){
  const t = String(content ?? ""), d = {id: docKey(path).slice(DOC_PREFIX.length), t: Date.now(), title: String(title || path || "문서").slice(0, 120), path, team, agent,
    mime: mime || (/\.csv$/i.test(path) ? "text/csv" : /\.json$/i.test(path) ? "application/json" : /\.html?$/i.test(path) ? "text/html" : /\.(py|js|sol|txt)$/i.test(path) ? "text/plain" : "text/markdown"), size: t.length, content: t.slice(0, 2e6)};
  try { await idb.put(docKey(path), d); fire({kind: "docs", doc: {...d, content: ""}}); } catch(e){}
  return d;
}
export async function listDocs(){ return (await idb.all(DOC_PREFIX).catch(() => [])).filter(d => d && d.title).sort((a, b) => b.t - a.t); }
export async function deleteDoc(id){ await idb.del(DOC_PREFIX + id); fire({kind: "docs"}); }
export async function openFolder(sub = ""){
  if (!LAUNCHER.on) return {ok: false, why: "웹 버전에서는 폴더를 열 수 없습니다 (GHNano.exe 에서 됩니다)"};
  const r = await fetch("/__nuri/openfolder" + (sub ? "?sub=" + encodeURIComponent(sub) : ""), {method: "POST", headers: {"X-Nuri-Token": window.__NURI_TOKEN || ""}}).catch(() => null);
  return r?.ok ? await r.json() : {ok: false, why: "폴더를 열지 못했습니다"};
}
// 직원이 office_write 로 만든 파일도 보관함에 넣는다
async function captureFiles(entry, team){
  for (const st of (entry.steps || []).filter(x => x.name === "office_write" && x.status === "done" && x.summary)){
    try { const {codeCall} = await import("../nuri-ai/engine.js"); const r = await codeCall("raw", {path: st.summary, ws: "office"}); if (r?.content != null) await saveDoc({title: st.summary.split("/").pop(), path: st.summary, content: r.content, team, agent: entry.agent}); } catch(e){}
  }
}

/* ============ 한국어로만, 간단하게 ============ */
// 일부 모델(추론형)은 '어떻게 답할지' 영어 계획을 답 앞에 길게 쓴다. 그 부분은 걷어 내고 한국어 답만 보여 준다.
const HANGUL = /[\uac00-\ud7a3]/g;
const PLAN_RE = /^\s*(💭\s*)?(we need|we should|we must|we can|we have|need |must |let'?s|let me|the user|user (wants|asks|requested)|i need|i should|i will|i'll|ok(ay)?[,. ]|so (we|i)|now (we|i)|also[, ]|maybe |but |given |thus|therefore|first line|then |could |however|probably|done\.|alright)/i;
const englishy = t => { const latin = (t.match(/[A-Za-z]/g) || []).length, han = (t.match(HANGUL) || []).length; return latin > 25 && han < latin * 0.15; };
export function koOnly(text){
  const s = String(text || ""); if (!s.trim()) return "";
  const out = []; let started = false;
  for (const piece of s.split(/(```[\s\S]*?(?:```|$))/)){
    if (piece.startsWith("```")){ out.push(piece); started = true; continue; }
    const keep = [];
    for (const para of piece.split(/\n{2,}/)){
      const t = para.trim(); if (!t) continue;
      if (englishy(t) && (!started || PLAN_RE.test(t))) continue;   // 앞부분의 영어 생각 · 중간의 영어 계획 문단
      keep.push(para.replace(/^\n+|\n+$/g, "")); started = true;
    }
    if (keep.length) out.push(keep.join("\n\n"));
  }
  return out.join("\n").trim();
}
// 속마음은 한국어 한 문장만 (영어 생각은 보여 주지 않는다)
const koThink = line => { const t = String(line || "").replace(/\s+/g, " ").trim(); if (!t || !(t.match(HANGUL) || []).length || englishy(t)) return ""; const one = t.split(/(?<=[.!?。])\s/)[0]; return one.length > 120 ? one.slice(0, 118) + "…" : one; };
// 메시지 조각 → 말(text) · 속마음(think) · 한 일(steps)
function read(msg, entry){
  const texts = msg.parts.filter(p => p.type === "text");
  let raw = texts.map(p => p.text).join("\n\n").replace(EMPTY_MARK, "").trim();
  let think = "";
  const mm = raw.match(/^💭\s*([^\n]*)\n?/);
  if (mm){ think = koThink(mm[1]); raw = raw.slice(mm[0].length).trim(); }
  raw = koOnly(raw.replace(/^\s*💭[^\n]*\n/gm, "")).trim();
  entry.thinking = !raw && texts.some(p => p.think);   // 모델이 아직 생각 중 (내용은 보여 주지 않음)
  entry.text = raw; entry.think = think;
  entry.steps = msg.parts.filter(p => p.type === "tool").map(p => ({act: p.act || p.label, name: p.name, status: p.status, summary: p.summary || "", err: p.error || "", sources: (p.sources || []).slice(0, 5)}));
}
/* ============ 자동 회의 ============ */
export const AGENDA = COIN_AGENDA;
// 급변동 감시 (코드만 씀, AI 호출 없음)
const WATCH = COIN_WATCH;
let timer = 0, lastWatch = 0;
export function startAutopilot(){
  if (timer) return; officeCfg();
  // 처음 켤 때는 2분 뒤에 첫 자동 회의
  if (!localStorage.getItem("coinLastAuto")) localStorage.setItem("coinLastAuto", String(Date.now() - officeCfg().every * 60e3 + 120e3));
  timer = setInterval(tick, 60e3); setTimeout(tick, 4000);
}
export function stopAutopilot(){ clearInterval(timer); timer = 0; }
export function nextAutoIn(){
  const c = officeCfg(), last = +localStorage.getItem("coinLastAuto") || 0;
  return Math.max(0, last + c.every * 60e3 - Date.now());
}
/* ============ 무료 API 한도에 걸리면 잠깐 쉬기 ============ */
// 한도 오류가 연달아 나면 자동 회의·주기 업무·수다를 몇 분 멈춘다 (대표님 질문은 계속 받는다). 계속 두드리면 한도가 더 늦게 풀린다.
let limitHits = [], pauseUntil = 0;
const isLimit = msg => /사용 한도|rate.?limit|429|too many requests|quota/i.test(String(msg || ""));
export const officePaused = () => Math.max(0, pauseUntil - Date.now());
function noteLimit(){
  const now = Date.now(); limitHits = limitHits.filter(t => now - t < 120e3); limitHits.push(now);
  if (limitHits.length >= 3 && now > pauseUntil){
    pauseUntil = now + 180e3; limitHits = [];
    const cool = Object.keys(coolingInfo()).map(id => ({groq: "Groq", nvidia: "NVIDIA", cerebras: "Cerebras", openrouter: "OpenRouter", gemini: "Gemini", hf: "Hugging Face", mistral: "Mistral", sambanova: "SambaNova", together: "Together", deepseek: "DeepSeek", anthropic: "Claude"})[id] || id);
    post({ch: "hq", kind: "system", text: `무료 AI 한도에 걸렸습니다${cool.length ? " (" + cool.join(", ") + ")" : ""} · 3분 쉬었다가 다시 일합니다. 질문은 계속 받습니다. 한도를 늘리려면 다른 무료 키를 더 넣거나 Claude 키를 넣으세요.`});
    fire({kind: "cfg"});
  }
}
async function tick(){
  const c = officeCfg();
  if (!c.auto || running || queue.length || !hasAI() || officePaused()) return;
  const u = usage();
  if (u.auto >= c.dailyMax) return;
  await loadLog();
  // 1) 급변동이면 바로 긴급 회의
  if (Date.now() - lastWatch > 10 * 60e3){
    lastWatch = Date.now();
    try {
      const r = await TOOLS.market_quote.run({symbols: WATCH.map(w => w.q)});
      const rows = JSON.parse(r.text || "[]"), seen = JSON.parse(localStorage.getItem("coinWatch") || "{}");
      for (const w of WATCH){
        const row = rows.find(x => String(x.종목 || "").includes(w.q) || String(x.종목 || "").includes(w.label));
        const chg = row && +row["변동%"]; if (!Number.isFinite(chg)) continue;
        const band = Math.trunc(chg / w.th), key = w.q + "|" + today();
        if (band !== 0 && seen[key] !== band){
          seen[key] = band; localStorage.setItem("coinWatch", JSON.stringify(seen));
          post({ch: w.room, kind: "system", text: `급변동 감지: ${w.label} ${chg > 0 ? "+" : ""}${chg}% → 긴급 회의를 엽니다`});
          enqueue({topic: `${w.label}가 하루 ${chg > 0 ? "+" : ""}${chg}% 움직였습니다. 원인과 지금 대응 방법을 점검해 주세요.`, room: w.room, trigger: "event", title: `긴급-${w.label}`, agents: w.agents});
          localStorage.setItem("coinLastAuto", String(Date.now()));
          return;
        }
      }
    } catch(e){}
  }
  // 2) 정해진 간격마다 안건을 돌아가며
  if (nextAutoIn() > 0) return;
  const i = (+localStorage.getItem("coinAgenda") || 0) % AGENDA.length, ag = AGENDA[i];
  localStorage.setItem("coinAgenda", String(i + 1)); localStorage.setItem("coinLastAuto", String(Date.now()));
  enqueue({topic: ag.topic, room: ag.room, trigger: "auto", title: ag.title, agents: ag.agents});
}
export async function runAgendaNow(id){
  await loadLog();
  const ag = AGENDA.find(a => a.id === id) || AGENDA[0];
  localStorage.setItem("coinLastAuto", String(Date.now()));
  return enqueue({topic: ag.topic, room: ag.room, trigger: "auto", title: ag.title, agents: ag.agents});
}

/* ============ 업무: 직원이 실제로 보는 차트·뉴스 (코드만 씀, AI 호출 없음) ============ */
const WATCH_OF = COIN_WATCH_OF;
const IDLE_WORK = {dev: ["💻 코드 리뷰 중", "🧪 테스트 돌리는 중", "🛠 대시보드 고치는 중"], aide: ["📝 오늘 일정 정리 중", "✉️ 메일 정리 중", "🗂 회의록 정리 중"]};
export const seen = {};   // 직원 → 최근에 본 것 [{icon, text, url, t}]
const newsCache = {};
export async function observe(id){
  const list = WATCH_OF[id];
  if (!list){ const w = IDLE_WORK[id]; return w ? {icon: "", text: w[Math.floor(Math.random() * w.length)], kind: "work", t: Date.now()} : null; }
  const pick = list[Math.floor(Math.random() * list.length)];
  let o = null;
  try {
    if (pick.flow){
      const F = await import("../nuri-ai/flow.js");
      const r = pick.flow === "whale" ? await F.whaleTrades({symbol: pick.sym}) : pick.flow === "book" ? await F.orderBook({symbol: pick.sym}) : await F.futuresFlow({symbol: pick.sym});
      if (r?.summary) o = {icon: pick.flow === "whale" ? "🐋" : pick.flow === "book" ? "📚" : "🌊", kind: "flow", text: `${pick.sym.replace("USDT", "")} ${r.summary}`.slice(0, 120)};
    } else if (pick.news){
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
const RELATED = COIN_RELATED;
let chatting = false, visible = false, chatTimer = 0;
export const setOfficeVisible = v => { visible = v; };
export const isChatting = () => chatting;
const sleep = ms => new Promise(r => setTimeout(r, ms));
function chatUsage(){ return usage().chats || 0; }
export async function chatter(force){
  const c = officeCfg();
  if (chatting || running || queue.length || !hasAI() || officePaused()) return false;
  if (!force && (!c.chat || chatUsage() >= c.chatMax)) return false;
  chatting = true;
  try {
    await loadLog();
    // 말을 꺼낼 사람: 방금 무언가를 본 직원 (없으면 지금 보게 한다)
    // 업무 우선: 최근 45분 안에 동료가 낸 '실제 작업 결과'(백테스트 카드·봇·최적화·데모 체결)를 두고 개선 토론 → 마지막에 다음 할 일(백로그)로
    const WORK_CH = /^(dev|cdev|bot|opt|bt|cbt|demo|cdemo|val)$/;
    const work = (LOG || []).filter(e => e.agent && agentById(e.agent) && WORK_CH.test(e.ch || "") && ["bt", "table", "trade", "work", "system"].includes(e.kind) && Date.now() - e.t < 45 * 60e3)
      .map(e => ({e, text: String(e.title || e.text || (e.name ? `${e.name} 백테스트 · 검증 수익 ${e.oos?.ret ?? "?"}% · 손익비 ${e.oos?.pf ?? "?"}` : "")).replace(/\s+/g, " ").slice(0, 220)})).filter(x => x.text.length > 8).slice(-15);
    const isWork = work.length > 0 && Math.random() < 0.85;
    let starter, obs;
    if (isWork){ const w = work[Math.floor(Math.random() * work.length)]; starter = agentById(w.e.agent); obs = {icon: "🛠", text: w.text, kind: "work", t: w.e.t}; }
    else {
      const fresh = AGENTS.filter(a => seen[a.id]?.[0] && Date.now() - seen[a.id][0].t < 10 * 60e3 && seen[a.id][0].kind !== "work");
      starter = fresh.length ? fresh[Math.floor(Math.random() * fresh.length)] : (arr => arr[Math.floor(Math.random() * arr.length)])(AGENTS.filter(a => WATCH_OF[a.id]));
      obs = seen[starter.id]?.[0]?.kind !== "work" && seen[starter.id]?.[0] || await observe(starter.id);
    }
    if (!obs || !starter) return false;
    const rel = RELATED[starter.id] || [];
    const partners = rel.slice().sort(() => Math.random() - .5).slice(0, Math.random() < 0.5 ? 1 : 2).map(agentById);
    const people = [starter, ...partners];
    const sys = `[잡담] 너는 GH Coin 직원들의 대화를 쓰는 작가다. 회사 동료들이 자리에서 일하다 나누는 자연스러운 한국어 대화를 쓴다.
참여자: ${people.map(p => `${p.name}(${p.title})`).join(", ")}
규칙: 4~7줄. 각 줄은 '이름: 대사' 형식(참여자 이름만). 대사는 1~2문장. ${starter.name}가 방금 본 것을 꺼내며 시작한다. 각자 자기 전문 분야 관점으로 반응하고, 가벼운 농담이나 생활 이야기가 섞여도 좋다.
방금 본 것 외의 숫자·사실은 지어내지 말고, 모르면 '확인해 볼게요'라고 한다. 투자 권유처럼 단정하지 않는다. 팀 회의가 꼭 필요할 만큼 중요하면 마지막 줄에 누군가 '회의 한번 하죠'라고 말한다.`;
    const sysW = isWork ? sys + `
[이번 대화는 업무 토론] ${starter.name}가 방금 낸 작업 결과를 두고, 각자 전문 분야로 어떻게 고치면 수익이 나아질지 구체적으로 말한다(지표·진입조건·손절·익절·시간봉·국면 필터 중 하나를 정확히). 마지막 줄은 반드시 '다음 할 일: (한 문장, 누가 무엇을)' 형식.` : sys;
    const user = `${starter.name}가 방금 ${isWork ? "낸 작업 결과" : "본 것"}: ${obs.icon} ${obs.text}${obs.src ? ` (출처: ${obs.src})` : ""}`;
    let out = "";
    bump("calls"); bump("chats");
    const cmods = claudeModels();
    const route = await brainStream({messages: [{role: "system", content: sysW}, {role: "user", content: user}], role: "general", maxTokens: 600, temperature: 0.9, noThink: true,
      ...(cmods ? {target: {id: "anthropic", model: cmods.haiku}, fallback: true} : {exclude: officeSources().length ? ["anthropic"] : []}), onContent: d => out += d});
    const body = splitThink(out).body;
    const nextTodo = (body.match(/다음\s*할\s*일\s*[:：]\s*([^\n]+)/) || [])[1];
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
    // 업무 토론의 결론 → 백로그 과제(‘개선 과제 수행’ 업무가 실제로 처리)
    if (isWork && nextTodo && nextTodo.length > 6){ addTask({team: starter.team, title: nextTodo.replace(/["*]/g, "").slice(0, 70), why: `동료 업무 토론(${obs.text.slice(0, 60)})에서 나온 개선안`, owner: starter.name}); post({ch, kind: "system", text: `📝 개선 과제 등록: ${nextTodo.slice(0, 80)}`}); }
    // 잡담에서 회의하자는 말이 나오면 진짜 회의를 연다
    if (/회의\s*(한번|한 번)?\s*(하죠|합시다|해요|하자|열|해보|잡)/.test(lines.at(-1).text) && usage().auto < c.dailyMax){
      enqueue({topic: `잡담에서 나온 이야기입니다. ${starter.name}가 본 것: ${obs.text}. 의미와 대응을 팀으로 점검해 주세요.`, room: ch, trigger: "auto", title: `잡담에서-${starter.name}`, agents: [starter.id, ...partners.map(p => p.id)].slice(0, 3)});
    }
    return true;
  } catch(e){ return false; }
  finally { chatting = false; setTimeout(pump, 200); }
}
export function nextChatIn(){ const c = officeCfg(), last = +localStorage.getItem("coinLastChat") || 0; return Math.max(0, last + c.chatEvery * 60e3 - Date.now()); }
export function startChatter(){
  if (chatTimer) return;
  chatTimer = setInterval(async () => {
    const c = officeCfg();
    if (!visible || !c.chat || nextChatIn() > 0) return;
    localStorage.setItem("coinLastChat", String(Date.now()));
    await chatter();
  }, 15e3);
}

/* ============ 3분 주기: 사람처럼 알아서 일하기 ============ */
// 매 주기 ① 모의투자 장부를 실제 시세로 갱신(코드, AI 없음) ② 그때그때 한 가지 일을 고른다:
// 매매법 연구 · SNS 여론 · 경제 리서치 · 동료 수다 · 컴퓨터 작업 · 모의투자 보고 (하루 AI 호출 한도 안에서)
// 쉬지 않고 돌아가는 업무 순환표: 팀마다 고르게 돌아가도록 섞어 두었다 (모듈이 없으면 경제 리서치로 대신)
// 🔗 에이전트 팀 ↔ 자체 뇌(옵시디언) 브리지: 팀의 데모 거래 결과를 뇌에 넣고(ingest) → 뇌가 이득 날만하게 정제(refine) → 문서(옵시디언)로 저장하고 설계팀에 인계. 뉴럴 데스크 AI 모델들도 같은 뇌를 읽고 씀 → 한 뇌로 모두 학습.
async function brainSyncJob(){
  const P = await import("../nuri-ai/paper.js"); let BRAIN;
  try { BRAIN = await import("./brain.js"); } catch(e){ return; }
  const book = await P.loadBook();
  let seen = {}; try { seen = JSON.parse(localStorage.getItem("coinBrainSeen") || "{}"); } catch(e){}
  let ingested = 0;
  for (const s of book.strategies || []){
    const key = s.id || s.name, from = seen[key] || 0, tr = s.trades || [];
    for (let i = from; i < tr.length; i++){ const t = tr[i];
      const coin = String(s.market || "").replace(/USDT$/, ""), dir = (t.side === "long" || t.side === 1 || t.side > 0) ? 1 : -1;
      const roe = +t.roe || 0, win = (t.pnl || 0) >= 0;
      BRAIN.ingest({ coin, regime: "", type: win ? "패턴" : "교훈", model: "에이전트팀", text: `${coin} ${dir > 0 ? "롱" : "숏"} ${win ? "+" : ""}${roe.toFixed(1)}% (${s.name}${t.reason ? " · " + t.reason : ""})` });
      ingested++;
    }
    seen[key] = tr.length;
  }
  try { localStorage.setItem("coinBrainSeen", JSON.stringify(seen)); } catch(e){}
  const coins = [...new Set((book.strategies || []).map(s => String(s.market || "").replace(/USDT$/, "")).filter(Boolean))].slice(0, 6);
  const refs = coins.map(c => BRAIN.refineForProfit(c, "")).filter(Boolean);
  const iq = (BRAIN.iqScore && BRAIN.iqScore()) || { score: 0, acc: 0, n: 0 };
  const md = `# 🧠 자체 뇌가 정제한 매매 규칙 · ${today()}\n\n뇌 지능 ${iq.score}/100 (정확도 ${iq.acc}% · ${iq.n}판 학습) · 이번에 팀 거래 ${ingested}건 반영\n\n${refs.map(r => `## ${r.coin}\n- ${r.text}\n- 핵심 지표: ${r.keyFeatures.join(", ") || "표본 부족"}\n- 뇌 기억: ${r.memory || "없음"}`).join("\n\n") || "- 아직 표본 부족"}\n\n> 이 규칙은 뉴럴 데스크 AI 모델과 설계팀이 함께 읽는 자체 뇌에서 자동 정제됩니다. 손절 패턴은 회피 대상으로 학습됩니다.\n`;
  await saveDoc({ title: `자체 뇌 정제 규칙 ${today()}`, path: `ghcoin/brain/refined-rules.md`, content: md, team: "hq", agent: "eng" });
  post({ ch: "hq", kind: "work", agent: "eng", icon: "🧠", text: `자체 뇌 동기화: 팀 거래 ${ingested}건 학습 → 지능 ${iq.score}/100. 정제 규칙을 ghcoin/brain/refined-rules.md 에 저장하고 설계팀·모델에 인계.` });
}
const JOBS = ["dev", "cdev", "evo", "bot", "opt", "dev", "botopt", "cdev", "survival", "patscan", "dev", "ml", "preset", "cdev", "combo", "dev", "evo", "bot", "contest", "ensemble", "brainsync", "dev", "cdev", "opt", "plan", "ic", "drift", "dev", "botopt", "alpha", "selfai", "retro", "task", "promote", "qrisk", "feeds", "news", "situ", "sent", "data", "selfdev", "task"];   // 개발·개선 우선(약 60%) · 판정이 진입 관문에 쓰이는 위원회·리스크·심리는 유지 · 시황은 소수
const JOB_KO = {plan: "리서치 플래너(할 일 목록 → 워커 배정)", sent: "시장 심리(자체 감정 엔진)", pos: "단타·스윙 포지션 추천", contest: "전략 콘테스트(데모 성과 리더보드)", ensemble: "앙상블 포트폴리오(신뢰점수로 비중 배분)", reality: "정직한 현실 점검(목표 수익 도달·파산 확률)", preset: "준비된 매매법 프리셋 비교(io-uty RSI·MACD + 지표 146종)", survival: "생존 경쟁(개발자 KPI + 다윈 전략 진화)", track: "예측 적중률·캘리브레이션", report: "성과 대시보드", bot: "자동매매봇 전략 만들기", botopt: "자동매매봇 자동 개선(보조지표·위험값 하이퍼옵트)", selfai: "자체 AI 데스크(앙상블 방향·확신도 순위)", ic: "투자위원회(강세·약세 토론 → 결정)", qrisk: "퀀트 리스크(VaR·결정표·주문 전 점검)", data: "거래소 비교·데이터 품질", opt: "하이퍼옵트로 전략 다듬기", patscan: "패턴 스캐너", drift: "데모 성과 이동 감지(런 차트)", feeds: "경제 캘린더·금리·변동성 지수", alpha: "알파 팩터 순위", combo: "실시간 종합 지표 타점", dev: "매매법 개발 → 백테스트", cdev: "커스텀 지표 개발 → 백테스트", ind: "보조지표 분석", trend: "다중 시간대 추세 분석", entry: "진입 타점 분석", sr: "지지·저항 분석",
  tpsl: "익절·손절 관리", news: "뉴스·기사 분석", macro: "경제지표 예측", situ: "코인 상황판", pattern: "차트·캔들 패턴 분석", coin: "코인팀 회의", ml: "머신러닝·딥러닝 실험",
  promote: "데모 → 실거래 관문 심사", live: "실거래 데스크 점검", paper: "데모거래 보고", forecast: "방향 예측 토론", sns: "SNS 여론 확인", chat: "동료 수다", computer: "컴퓨터 작업",
  retro: "팀 회고·부족한 점 찾기", task: "개선 과제 수행", selfdev: "우리 앱 오류 찾아 코드 고치기", economy: "경제 리서치", brainsync: "자체 뇌 동기화(팀 결과→뇌 학습→정제 규칙 인계)", evo: "매매법 진화(개선·수정·조합)", rtentry: "⚡ 실시간 진입(손매매용 · 팀↔뉴럴 토론)"};
const JOB_TEAM = {plan: "hq", sent: "news", pos: "entry", contest: "demo", ensemble: "demo", reality: "hq", preset: "demo", survival: "demo", track: "hq", report: "hq", bot: "bot", botopt: "bot", selfai: "selfai", ic: "ic", qrisk: "qrisk", data: "data", opt: "opt", patscan: "pattern", drift: "demo", feeds: "news", alpha: "ml", combo: "combo", dev: "dev", cdev: "cdev", ind: "ind", trend: "trend", entry: "entry", sr: "sr", tpsl: "tpsl", news: "news", macro: "news", situ: "situ", pattern: "pattern", coin: "btc", ml: "ml",
  promote: "demo", live: "live", paper: "demo", forecast: "entry", sns: "news", chat: "hq", computer: "hq", retro: "hq", task: "hq", selfdev: "hq", economy: "news", brainsync: "hq", evo: "dev", rtentry: "entry"};
const JOB_FN = () => ({plan: plannerJob, sent: sentimentJob, pos: posJob, contest: contestJob, ensemble: ensembleJob, reality: realityJob, preset: presetJob, survival: survivalJob, track: trackJob, report: dashboardJob, bot: botJob, botopt: botImproveJob, selfai: selfaiJob, ic: icJob, qrisk: qriskJob, data: dataJob, opt: optJob, patscan: patternScanJob, drift: driftJob, feeds: openFeedsJob, alpha: alphaJob, combo: comboJob, dev: () => research("std"), cdev: () => research("custom"), ind: indJob, trend: trendJob, entry: entryJob, sr: srJob, tpsl: tpslJob, news: economyCheck, macro: macroJob,
  situ: situJob, pattern: patternJob, coin: coinJob, ml: mlJob, promote: promoteJob, live: liveDeskJob, paper: paperReport, forecast: forecastJob, sns: snsCheck, chat: () => chatter(true),
  computer: computerWork, retro, task: doTask, selfdev: selfdevJob, economy: economyCheck, brainsync: brainSyncJob, evo: evoJob, rtentry: rtEntryJob});
let cycleTimer = 0, cycling = false, lastJob = "";
export const cycleState = () => ({cycling, lastJob});
export function nextCycleIn(){ const c = officeCfg(), last = +localStorage.getItem("coinLastCycle") || 0; return Math.max(0, last + c.cycleMin * 60e3 - Date.now()); }
export function startCycle(){
  startReports();
  refreshOllama();   // 내 PC Ollama 설치 모델을 직원 후보로 올림
  import("./neural.js").then(N => N.startAuto?.()).catch(() => {});   // 뉴럴 데스크·자체 뇌도 앱이 켜지면 상시 실행(패널 열 필요 없음)
  import("./neutron.js").then(M => M.startNeutron?.()).catch(() => {});
  // ⚡ 실시간 진입: 3분마다 자동 분석(토론은 유력·보통 후보만, 같은 자리 10분에 한 번)
  if (!startCycle._rt){ startCycle._rt = setInterval(() => runLiveEntry({debate: hasAI()}).catch(() => {}), 3 * 60e3); setTimeout(() => runLiveEntry({debate: hasAI()}).catch(() => {}), 40e3); }   // 🧠 뉴트론: 뇌를 MCP·옵시디언 볼트로 내보내고 Claude Code·Claudian 제안을 받음 (exe 에서만)
  if (cycleTimer) return;
  if (!localStorage.getItem("coinLastCycle")) localStorage.setItem("coinLastCycle", String(Date.now() - officeCfg().cycleMin * 60e3 + 45e3));
  cycleTimer = setInterval(() => cycle().catch(e => console.warn(e)), 20e3);
}
export async function cycle(force, onlyJob){
  const c = officeCfg();
  if (cycling || (!force && (!c.cycle || nextCycleIn() > 0 || officePaused()))) return false;
  const ai = hasAI();
  cycling = true; localStorage.setItem("coinLastCycle", String(Date.now()));
  try {
    if ((+localStorage.getItem("coinCyc") || 0) % 10 === 0) refreshOllama();   // 가끔 Ollama 설치 목록 갱신
    localStorage.setItem("coinCyc", String((+localStorage.getItem("coinCyc") || 0) + 1));
    await loadLog();
    await paperStep();
    // 회의가 열려 있어도 주기 업무는 따로 계속한다 (사람처럼 각자 일함). 단, 질문에 답하는 중에는 잡담만 쉰다
    if (usage().calls >= c.callMax){ if (!usage().capNoted){ bump("capNoted"); post({ch: "hq", kind: "system", text: `오늘 사무실 AI 호출 한도(${c.callMax}번)를 다 썼습니다. 모의투자 갱신과 차트·뉴스 확인은 계속합니다.`}); } return true; }
    let job = onlyJob;
    if (!job){ const i = +localStorage.getItem("coinJob") || 0; job = JOBS[i % JOBS.length]; localStorage.setItem("coinJob", String(i + 1)); }
    if (job === "paper" && !(await paperActive())) job = "dev";
    if (job === "computer" && !computerOn()) job = "economy";
    if (job === "task" && !backlog().some(t => t.status !== "done")) job = "retro";
    if (job === "chat" && (running || chatting)) job = "economy";
    // AI 연결이 없어도 코드만으로 결정하는 업무(프리셋·진화·하이퍼옵트·봇개선·이동감지·리스크표·승격 심사)는 계속 돈다
    const NOLLM = ["preset", "survival", "opt", "botopt", "drift", "qrisk", "promote", "contest", "ensemble", "evo", "patscan", "data", "feeds"];
    if (!ai && !NOLLM.includes(job)){ job = NOLLM[(+localStorage.getItem("coinNoAI") || 0) % NOLLM.length]; localStorage.setItem("coinNoAI", String((+localStorage.getItem("coinNoAI") || 0) + 1)); }
    lastJob = job; fire({kind: "cycle", job, label: JOB_KO[job]});
    post({ch: JOB_TEAM[job] || "hq", kind: "work", agent: TEAM_LEAD[JOB_TEAM[job]] || "lead", icon: "▶", text: `${JOB_KO[job]} 시작`});
    const fn = JOB_FN()[job] || (() => research("std"));
    try { await fn(); }
    catch(e){
      // 실패를 숨기고 뉴스로 때우지 않는다: 진짜 오류를 알리고(자가수정 대상으로 기록) 그 주기는 매매법 개발로 대신한다
      const msg = String(e.message || e);
      post({ch: "hq", kind: "system", text: `⚠ ${JOB_KO[job]} 실패: ${msg.slice(0, 140)} → 이번 주기는 매매법 개발로 대신합니다`});
      import("../nuri-ai/selfdev.js").then(S => S.recordError({msg, stack: e.stack || "", src: "job:" + job})).catch(() => {});
      if (job !== "dev" && ai){ lastJob = "dev"; await research("std"); } else if (job === "dev") throw e;
    }
    return true;
  } catch(e){
    post({ch: "hq", kind: "system", text: `${JOB_KO[lastJob] || "일"} 중 문제: ${String(e.message || e).slice(0, 120)}`});
    import("../nuri-ai/selfdev.js").then(S => S.recordError({msg: String(e.message || e), stack: e.stack || "", src: "job:" + lastJob})).catch(() => {});
    return false;
  }
  finally { cycling = false; fire({kind: "cycle-end"}); setTimeout(pump, 200); }
}

// 혼자 하는 일 한 번: 배정 모델로 생각·말을 실시간으로 보여 주고, 빈 답이면 다른 모델로
// LLM 응답 캐시: 키에 질문(sys+user) 전체가 들어가므로, 상태가 글자 하나까지 같을 때만 적중한다
// → 같은 자료로 같은 보고를 반복 요청할 때 모델을 다시 부르지 않아 비용을 아낀다(오래된 분석을 주지 않음)
const _soloCache = new Map();
function _hash(s){ let h = 5381; for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0; return h.toString(36); }
// 로컬(Ollama) 모델용 간결 전략 규격: 원문 STRATEGY_PROMPT의 형식·규칙·엔진 동작 부분은 그대로, 긴 지표표만 한 줄로
function compactSpecPrompt(Q){
  const p = Q.STRATEGY_PROMPT, cut = p.indexOf("지표 표 (");
  return (cut > 0 ? p.slice(0, cut) : p.slice(0, 3200)) + "지표(type: 출력): sma·ema·wma·hma·rsi·roc·cci·mfi·willr·atr·obv·vwap·volume_sma·highest·lowest: value · macd: line,signal,hist · bb: upper,middle,lower,width · stoch·stochrsi: k,d · adx: adx,plus_di,minus_di · supertrend·psar·atr_stop: line(psar는 value),trend(±1) · donchian·keltner: upper,middle,lower · ichimoku: tenkan,kijun,span_a,span_b · ICT: bos(value,trend)·fvg·ob·sweep·disp(±1)·premium(0~1)·session(start,end) · custom(expr). 파라미터는 length(기본 14~20)·mult 등. 차트 터미널 지표도 type \"tv_이름\" 으로 쓸 수 있다.\n";
}
async function solo(a, {room, sys, user, maxTokens = 900, temperature = 0.6, extra = {}, train = "", trainRaw = false, role = null, cache = 0, json = false}){
  const models = assignModels();
  const target = models[a.id];
  const cm = claudeModels();
  const alt = cm && target?.model !== cm.sonnet ? {id: "anthropic", model: cm.sonnet} : officeSources().filter(t => t.model !== target?.model && !badModels()[t.model]).sort((x, y) => modelScore(y.model) - modelScore(x.model))[0];
  const entry = post({ch: room || a.team, kind: "agent", agent: a.id, text: "", think: "", steps: [], live: true, model: target?.model || "", ...extra});
  fire({kind: "solo", agent: a, entry});
  const ckey = cache ? a.id + "|" + (role || "") + "|" + _hash(sys + "\u0000" + user) : null;
  if (ckey){ const h = _soloCache.get(ckey); if (h && Date.now() - h.at < cache){ entry.text = h.text; entry.model = (h.model || "") + " · 캐시"; entry.live = false; saveLog(); fire({kind: "said", agent: a, entry}); return {...entry, raw: h.raw, cached: true}; } }
  let finalRaw = "";
  for (const tg of [target, alt, null].filter((t, i, arr) => i === arr.length - 1 || (t && arr.findIndex(x => x && x.model === t.model) === i))){
    let raw = "", think = "", last = 0;
    const show = () => { const mm = raw.match(/^💭\s*([^\n]*)\n?/); entry.think = mm ? koThink(mm[1]) : ""; entry.text = koOnly(visibleText((mm ? raw.slice(mm[0].length) : raw).replace(/<think>[\s\S]*?(<\/think>|$)/g, "")).replace(/^\s*💭[^\n]*\n?/gm, "")).trim();
      entry.thinking = !entry.text && !!think;
      if (Date.now() - last > 150){ last = Date.now(); fire({kind: "delta", agent: a, entry}); } };
    // 느린 모델은 끊고 다음 모델로: 60초 동안 한 글자도 없거나 전체 3분을 넘기면
    const ctl = new AbortController(), t0 = Date.now(); let slow = false;
    const watch = setInterval(() => { const el = Date.now() - t0; const loc = !tg || tg.id === "ollama"; if ((!raw && el > (loc ? 240e3 : 60e3)) || el > (loc ? 480e3 : 180e3)){ slow = true; ctl.abort(); } }, 2000);
    try {
      bump("calls");
      const route = await brainStream({messages: [{role: "system", content: sys}, {role: "user", content: user}], role: role || (a.role === "code" ? "code" : "general"), signal: ctl.signal, noThink: true,
        maxTokens, temperature, target: tg || undefined, fallback: true, json, onContent: d => { raw += d; show(); }, onThink: d => { think += d; show(); }});   // json: 작은 로컬 모델도 전략 JSON을 확실히 내게(강제 JSON)
      raw = splitThink(raw).body; show(); finalRaw = raw;
      entry.model = route?.model || tg?.model || entry.model;
    } catch(e){ if (slow && raw){ raw = splitThink(raw).body; show(); finalRaw = raw; } if (!slow && isLimit(e.message)) noteLimit(); addNote2(entry, `${shortName(tg?.model)}: ${slow ? "응답이 너무 느림" : String(e.message || e).slice(0, 60)}`); }
    finally { clearInterval(watch); }
    entry.thinking = false;
    noteModel(entry.model || tg?.model, (entry.text || finalRaw) && !slow ? "ok" : slow ? "slow" : "fail");
    if (entry.text || /```json|^\s*[\[{]\s*"?[\w{]/m.test(finalRaw)) break;
    markBad(tg?.model);
  }
  if (!entry.text && !finalRaw) entry.text = `(${a.name}: 이번에는 답하지 못했습니다)`;
  if (!entry.text && finalRaw) entry.text = (finalRaw.replace(/^\s*💭[^\n]*\n?/gm, "").replace(/```(?:json)?[\s\S]*?(```|$)/g, "").trim() || "전략을 만들었습니다") + "\n\n*(전략 JSON은 아래 백테스트 카드에 있습니다)*";
  // 자료를 읽고 해설한 일은 '자료 해설' 학습 예시로
  if (train && (goodText(entry.text) || trainRaw && finalRaw.length > 40) && !isClaude(entry.model)){
    // trainRaw: 설계안·사업안·후보 추출처럼 JSON 이 결과물인 일은 JSON 까지 그대로 학습
    const ans = trainRaw ? noMind(finalRaw.replace(/^\s*💭[^\n]*\n?/gm, "").replace(/<think>[\s\S]*?<\/think>/g, "").trim()) : noMind(entry.text);
    const id = await keep("office-solo", [{role: "user", content: `${train}\n\n${clip(user, 3500)}`}, {role: "assistant", content: ans}], {agent: a.id, model: entry.model, job: room}).catch(() => null);
    if (id) entry.trainIds = [id];
  }
  entry.live = false; saveLog(); fire({kind: "said", agent: a, entry});
  if (ckey && goodText(entry.text)){ _soloCache.set(ckey, {at: Date.now(), text: entry.text, raw: finalRaw, model: entry.model}); if (_soloCache.size > 60){ const old = [..._soloCache.entries()].sort((x, y) => x[1].at - y[1].at)[0]; if (old) _soloCache.delete(old[0]); } }
  return {...entry, raw: finalRaw};
}
// agency-agents-ko 방식 역할 정의: 팀마다 '핵심 원칙 + 성공 지표'를 프롬프트에 넣어 각자 자기 일의 기준으로 판단하게 한다
const PRINCIPLES = {
  dev: "핵심 원칙: 가설→규칙→백테스트 순서, 지표는 2~4개로 단순하게, 손절은 구조(스윙·ATR) 기반. 성공 지표: 표본외(OOS) 수익·순열검정 p≤0.1·다른 코인 일반화",
  cdev: "핵심 원칙: 기존 지표를 베끼지 말고 수식으로 새 신호를 만든다, 미래 데이터 금지. 성공 지표: 커스텀 지표가 진입 핵심 조건이면서 OOS 통과",
  bt: "핵심 원칙: 수수료·슬리피지 포함, 표본내/외 분리, 거래 수 30 미만은 결론 보류. 성공 지표: 과최적화 의심을 먼저 찾아낸 건수", cbt: "핵심 원칙: 표본내/외 분리·수수료 포함·과최적화부터 의심. 성공 지표: 걸러낸 가짜 우위",
  demo: "핵심 원칙: 데모 성적만 믿고 검증 안 된 건 승격하지 않는다, 낙폭 먼저 본다. 성공 지표: 관문 통과 전략의 실전 유지율", cdemo: "핵심 원칙: 낙폭 먼저·관문 엄수. 성공 지표: 승격 후 유지율",
  qrisk: "핵심 원칙: 수익보다 생존, VaR·낙폭·쏠림을 숫자로. 성공 지표: 큰 손실 회피", tpsl: "핵심 원칙: 손절은 청산거리의 40% 이하, 손익비 1.5 이상. 성공 지표: 평균 손실 대비 평균 수익",
  ic: "핵심 원칙: 반대 근거를 먼저 말하고 합의도로 결정, 확률로 말함. 성공 지표: 결정 후 적중률", entry: "핵심 원칙: 상위 시간대 추세 방향만, 근거 2개 이상 겹칠 때만. 성공 지표: 진입 후 1R 도달률",
  opt: "핵심 원칙: 파라미터는 넓은 평탄 구간에서 고르고 뾰족한 최고점은 버린다. 성공 지표: 개선 후 OOS 유지", bot: "핵심 원칙: 물타기 제한·지갑 노출 한도·하드 손절. 성공 지표: 청산 0회",
  ml: "핵심 원칙: 기준선(항상 다수 클래스)보다 나아야 의미, 누수 금지. 성공 지표: 기준선 대비 정확도 향상", news: "핵심 원칙: 사실과 해석 구분, 고영향 일정 전후 진입 경계. 성공 지표: 위험 일정 사전 경고",
};
const personaOf = (a, extra = "") => `너는 세계적인 기업 수준의 GH Coin ${teamById(a.team).name}의 '${a.name}'(${a.title})다. 역할: ${a.duty}
${PRINCIPLES[a.team] || "핵심 원칙: 자료에 있는 숫자로만 말하고, 확률로 말하며, 자기 역할의 일을 끝까지 한다. 성공 지표: 다른 팀이 바로 쓸 수 있는 결론"}
${notesText(a.team)}${skillsText()}
반드시 한국어로만 쓰고, 영어 생각이나 답 계획은 쓰지 않는다. 이번 일에서는 도구를 부를 수 없으니 주어진 자료로만 말한다. 첫 줄은 '💭 '로 시작하는 한 문장 속마음(무엇을 보고 어떻게 판단하는지)이다. 그다음 동료에게 말하듯 자연스러운 한국어로 말한다. 데이터에 없는 숫자는 지어내지 않는다. ${extra}`;

/* ---- 모의투자 (코드) ---- */
async function paperActive(){ const P = await import("../nuri-ai/paper.js"); const b = await P.loadBook(); return b.strategies.some(s => s.status === "active"); }
// 🚦 진입 관문 — 각 팀의 판정이 데모(→연결된 실거래) 진입을 실제로 막거나 줄인다 (표시만 하던 기능을 의사결정에 연결)
const _fundCache = {};
async function fundingRegimeOf(sym){   // Vibe-Trading 펀딩 상태(7일 평균 + 최근 3회) — 바이낸스 펀딩 이력으로 계산(30분 캐시)
  const c0 = _fundCache[sym]; if (c0 && Date.now() - c0.t < 30 * 60e3) return c0.r;
  try { const {webGet} = await import("../nuri-ai/engine.js"), X = await lib("exchanges");
    const j = await webGet(`https://fapi.binance.com/fapi/v1/fundingRate?symbol=${sym}&limit=21`, "json");
    const v = (Array.isArray(j) ? j : []).map(x => +x.fundingRate * 100).filter(Number.isFinite); if (!v.length) return null;
    const r = X.fundingRegime(v.reduce((x, y) => x + y, 0) / v.length, v.slice(-3)); _fundCache[sym] = {t: Date.now(), r}; return r;
  } catch(e){ return null; }
}
const _fsCache = {};
async function fundScanOf(sym){ const c0 = _fsCache[sym]; if (c0 && Date.now() - c0.t < 15 * 60e3) return c0.r;
  const F = await lib("fundscan"), {webGet} = await import("../nuri-ai/engine.js"); const r = await F.fundingScan(sym, u => webGet(u, "json")); _fsCache[sym] = {t: Date.now(), r}; return r; }
// 🚦 진입 관문 — 각 팀·각 오픈소스의 판정이 데모(→연결된 실거래) 진입을 실제로 막거나 크기를 바꾼다
async function coinGate({s, side, price, cs}){
  const c = COINS.find(x => x.sym === s.market); if (!c) return {ok: true, mul: 1};
  // ⓪ 데이터 품질 제약 (Legend 모델 제약 방식): 값이 비정상이거나 봉이 끊기거나 마지막 봉이 오래됐으면 그 데이터로는 진입 금지
  if (Array.isArray(cs) && cs.length > 3){
    const tail = cs.slice(-50), step = tail[1].t - tail[0].t, last = tail.at(-1);
    if (tail.some(b => !(b.h >= b.l && b.l > 0 && b.c > 0 && Number.isFinite(+b.v)))) return {ok: false, why: "데이터 품질 제약 위반(비정상 봉)"};
    if (tail.some((b, i) => i && b.t - tail[i - 1].t > step * 1.5)) return {ok: false, why: "데이터 품질 제약 위반(봉 누락)"};
    if (step > 0 && Date.now() - last.t > step * 3) return {ok: false, why: "데이터 품질 제약 위반(시세 지연)"};
  }
  const now = Date.now(), dir = side === "long" ? 1 : -1, why = [], fresh = (o, h) => o && now - o.t < h * 3600e3; let mul = 1;
  const cut = (k, w) => { mul *= k; why.push(w); };
  // ① 퀀트 리스크 결정표 (gs-quant VaR·낙폭 + jdmn 결정표)
  const rv = (readJ("coinRiskVerdict", {}) || {})[c.id];
  if (fresh(rv, 26)){ if (rv.act === "거래 정지" || rv.act === "신규 진입 보류") return {ok: false, why: `리스크 결정표 '${rv.act}' (${rv.why})`}; if (rv.act === "비중 절반") cut(0.5, "결정표 비중 절반"); }
  // ② 투자위원회 (TradingAgents 토론 + ai-hedge-fund 페르소나 합의도)
  const ic = icLedger().filter(d => d.coin === c.id && now - d.t < 20 * 3600e3).at(-1);
  if (ic){ const v = {매수: 1, 비중확대: 1, 매도: -1, 비중축소: -1}[ic.rating] || 0, agree = ic.cons?.agree ?? 100;
    if (v === -dir && agree >= 67) return {ok: false, why: `투자위원회 '${ic.rating}'(합의 ${agree}%) — 반대 방향 진입 금지`}; if (v === dir) why.push(`위원회 '${ic.rating}' 일치`); }
  // ③ 뉴스 위험 (뉴럴 데스크 뉴스 점검) · ④ 경제 캘린더 고영향 일정 ±30분 (OpenBB 공급원)
  try { const nw = JSON.parse(localStorage.getItem("coin:neural") || "{}").news;
    if (nw){ if ((nw.blockUntil || 0) > now) return {ok: false, why: `📰 주요 일정·뉴스 위험 (${nw.reason || ""})`}; if (now - nw.t < 3600e3 && nw.score * dir <= -1) cut(0.5, `뉴스 심리 ${nw.score}`); } } catch(e){}
  const ev = (readJ("coinCalendar", {})?.events || []).find(e => Math.abs(e.t - now) < 30 * 60e3);
  if (ev) return {ok: false, why: `🗓 미국 고영향 일정 ±30분: ${ev.name}`};
  // ⑤ 시장 심리 극단 (day_trading_bot 감정 엔진 + KOME 어휘)
  const se = readJ("coinSentiment", null);
  if (fresh(se, 6)){ if (se.score >= 85 && dir > 0) cut(0.5, `심리 과열 ${se.score}`); if (se.score <= 15 && dir < 0) cut(0.5, `심리 공포 ${se.score}`); }
  // ⑥ 자체 AI 앙상블 (claude-cookbooks 앙상블 + bitoracle 확률 0.6 규칙): 반대 방향 확신 60%+ 면 차단
  const sa = (readJ("coinSelfAI", {}) || {})[c.id];
  if (fresh(sa, 6) && sa.conf >= 60){ if (sa.dir === -dir) return {ok: false, why: `자체 AI 앙상블 반대(${sa.conf}%)`}; if (sa.dir === dir) why.push(`자체 AI 일치 ${sa.conf}%`); }
  // ⑦ ML 예측 (ml-ko 방법론, 기준선보다 나은 모델만): 반대 확률 60%+ → 0.7배
  const ml = (readJ("coinML", {}) || {})[c.id];
  if (fresh(ml, 12) && ml.edge === "edge" && ml.prob != null && ((dir > 0 && ml.prob <= 0.4) || (dir < 0 && ml.prob >= 0.6))) cut(0.7, `ML 반대 ${(ml.prob * 100).toFixed(0)}%`);
  // ⑧ 트레이딩뷰식 종합 평점 (tradingview-mcp) ⑨ 차트 패턴 (stock-pattern·chart_patterns) ⑩ 알파 순위 (vnpy Alpha158)
  const tr = (readJ("coinTARating", {}) || {})[c.id];
  if (fresh(tr, 6) && tr.all != null && tr.all * dir <= -0.5) cut(0.6, `TA 평점 반대(${tr.label})`);
  const pt = (readJ("coinPatterns", {}) || {})[c.id];
  if (fresh(pt, 6) && pt.dir === -dir) cut(0.7, `차트 패턴 반대(${(pt.names || []).join(",")})`);
  const al = (readJ("coinAlpha", {}) || {})[c.id];
  if (fresh(al, 12) && al.n >= 4){ if (dir > 0 && al.rank > al.n * 2 / 3) cut(0.75, `알파 하위 ${al.rank}/${al.n}`); if (dir < 0 && al.rank <= al.n / 3) cut(0.75, `알파 상위 ${al.rank}/${al.n}`); }
  // ⑪ 펀딩 과열 (Vibe-Trading fundingRegime + ccxt 거래소 비교의 김치 프리미엄)
  const fr = await fundingRegimeOf(c.sym);
  if (fr?.key === "hotLong" && dir > 0) cut(0.5, "펀딩 롱 과열"); if (fr?.key === "hotShort" && dir < 0) cut(0.5, "펀딩 숏 과열");
  try { const FS = await fundScanOf(c.sym); if (FS?.key === "hotLong" && dir > 0) cut(0.7, `전 거래소 롱 과열(평균 ${FS.avg}%)`); if (FS?.key === "hotShort" && dir < 0) cut(0.7, `전 거래소 숏 과열(평균 ${FS.avg}%)`); } catch(e){}   // Sharpe식 거래소 간 펀딩 스캔
  // 🐋 고래 카피 신호(casatrickdev 감지→필터→리스크→신호): 승인된 고래 흐름이 진입과 반대면 0.6배 — 뉴럴 데스크가 학습한 적중률이 낮으면 무시
  try { const N = await import("./neural.js"), WC = await lib("whalecopy"), F = await import("../nuri-ai/flow.js");
    const k = "_wh" + c.sym, c0 = coinGate[k]; let sg = c0 && Date.now() - c0.t < 90e3 ? c0.s : null;
    if (!sg){ const r = await F.whaleTrades({symbol: c.sym, exchange: "binancef", minUsd: c.sym === "BTCUSDT" ? 300000 : 100000}); sg = WC.pipeline(c.sym, r?.data, N.whaleTrust?.()); coinGate[k] = {t: Date.now(), s: sg}; }
    if (sg.status === "approved" && sg.dir === -dir) cut(0.6, `고래 반대(순 ${sg.netPct}%)`); else if (sg.status === "approved" && sg.dir === dir) why.push(`고래 동행 ${sg.netPct}%`); } catch(e){}
  const dx = (readJ("coinDataV", {}) || {})[c.id]; if (fresh(dx, 12) && dx.kimchi != null && dx.kimchi > 5 && dir > 0) cut(0.7, `김치 프리미엄 ${dx.kimchi.toFixed(1)}%`);
  // ⑫ 노출 한도 (passivbot wallet exposure) ⑬ 재고 위험 (SolTrade·Guéant 마켓메이킹) ⑭ 포트폴리오 히트·켈리·손익비 (ai-trader-team rigor)
  try { const P = await import("../nuri-ai/paper.js"), book = await P.loadBook(), R = await import("./lib/rigor.js");
    const open = book.strategies.filter(x => x.status === "active" && x.pos);
    if (open.filter(x => x.market === s.market && (x.pos.side === "long" ? 1 : -1) === dir).length >= 2) return {ok: false, why: `같은 코인·방향 노출 한도(passivbot) — 이미 ${s.market} ${side} 2개`};
    const net = open.reduce((a2, x) => a2 + (x.pos.side === "long" ? 1 : -1), 0);
    if (Math.abs(net + dir) > 4) cut(0.5, `재고 위험(전체 순 ${net > 0 ? "롱" : "숏"} ${Math.abs(net)}개 쏠림)`);
    const heat = open.map(x => { const r0 = x.spec?.risk || {}, sl = (+r0.stop_loss_pct || 3) / 100; return Math.max(0, (x.pos.margin * x.pos.lev * sl) / Math.max(1, x.cash) * 100); });
    if (heat.length && R.portfolioHeat(heat, 6).over_limit) return {ok: false, why: `포트폴리오 히트 6% 초과(rigor)`};
    const tr2 = (s.trades || []).slice(-30);
    if (tr2.length >= 10){ const w = tr2.filter(t => t.pnl > 0), l = tr2.filter(t => t.pnl <= 0);
      if (w.length && l.length){ const k = R.kellyCriterion(w.length / tr2.length * 100, w.reduce((x, t) => x + t.pnl, 0) / w.length, Math.abs(l.reduce((x, t) => x + t.pnl, 0) / l.length));
        if (!k.has_edge) cut(0.5, `켈리 우위 없음(${k.full_kelly_pct}%)`); else if (k.full_kelly_pct > 20) { mul *= 1.2; why.push(`켈리 ${k.full_kelly_pct}%`); } } }
    const r1 = s.spec?.risk || {}; if (r1.stop_loss_pct && r1.take_profit_pct && price){ const sl = price * (1 - dir * r1.stop_loss_pct / 100), tp = price * (1 + dir * r1.take_profit_pct / 100);
      if (R.riskReward(price, sl, tp).risk_reward_ratio < 1.2) cut(0.6, `손익비 ${R.riskReward(price, sl, tp).risk_reward_ratio} < 1.2`); }
  } catch(e){}
  return {ok: true, mul: Math.max(0.1, Math.min(1.5, mul)), why: why.join(" · ")};
}
export const _coinGate = coinGate;   // 검증용
async function paperStep(){
  const P = await import("../nuri-ai/paper.js");
  const fmt = n => Number(n).toLocaleString("ko-KR", {maximumFractionDigits: 2});
  P.setEntryGate?.(coinGate);
  await P.step(ev => {
    if (ev.kind === "blocked"){   // 관문이 막은 진입을 보이게(전략당 1시간에 한 번)
      const k = "coinBlk:" + ev.s.id; if (Date.now() - (+localStorage.getItem(k) || 0) > 3600e3){ localStorage.setItem(k, String(Date.now()));
        post({ch: (LANES[ev.s.lane] || LANES.std).demo, kind: "system", text: `🚦 [${ev.s.name}] ${ev.side === "long" ? "롱" : "숏"} 진입 차단 — ${ev.why}`}); }
      return; }
    // 실거래 연결: 사용자가 켜고 연결한 전략만, 안전 한도·승인을 거쳐 코드가 주문한다 (AI는 주문하지 않음). 승인 대기가 길 수 있어 기다리지 않는다
    if (ev.kind === "open" || ev.kind === "close") import("../nuri-ai/live.js").then(L => L.onPaperEvent(ev)).then(r => {
      if (r && (r.order || r.blocked || r.error) && !r.ignored) post({ch: ev.s.lane === "custom" ? "clive" : "live", kind: "live", level: r.error || r.blocked ? "warn" : "info", text: r.order ? `🔐 실거래 주문 체결: ${ev.s.market} ${ev.kind === "open" ? "진입" : "청산"}` : r.blocked ? `🔐 실거래 차단: ${(r.reasons || []).join(", ")}` : `🔐 실거래 오류: ${r.error}`});
    }).catch(() => {});
    const s = ev.s, side = k => k === "long" ? "롱" : "숏";
    let text = "";
    if (ev.kind === "open") text = `📗 [${s.name}] ${s.market} ${side(ev.pos.side)} 진입 ${fmt(ev.pos.entry)} (x${ev.pos.lev}${ev.pos.sl ? `, 손절 ${fmt(ev.pos.sl)}` : ""}${ev.pos.tp ? `, 익절 ${fmt(ev.pos.tp)}` : ""})${ev.why ? " — " + ev.why : ""}`;
    else if (ev.kind === "close") text = `${ev.trade.pnl >= 0 ? "💰" : "📕"} [${s.name}] ${s.market} ${side(ev.trade.side)} 청산 ${fmt(ev.trade.exitP)} · ${ev.trade.pnl >= 0 ? "+" : ""}${fmt(ev.trade.pnl)} (ROE ${ev.trade.roe.toFixed(1)}%) · ${ev.trade.reason}`;
    else if (ev.kind === "bust") text = `💥 [${s.name}] 가상 계좌가 파산해 운용을 멈췄습니다`;
    else return;
    const dl = (LANES[s.lane] || LANES.std).demoLead;
    post({ch: (LANES[s.lane] || LANES.std).demo, kind: "trade", agent: dl, text});
    fire({kind: "trade", agent: agentById(dl), text});
  });
  fire({kind: "paper"});
}
async function paperReport(){
  const P = await import("../nuri-ai/paper.js"), a = agentById("trader");
  const book = await P.bookText();
  await solo(a, {room: "demo", cache: 300000, sys: personaOf(a, "데모거래(모의) 현황을 팀에 3~5문장으로 보고한다. 잘 되는 전략과 안 되는 전략, 지금 포지션의 위험을 짚는다. 실제 주문이 아닌 가상 운용임을 잊지 않는다."), user: `모의투자 장부:\n${book}`, train: "아래 모의투자 장부를 보고 잘 되는 전략과 안 되는 전략, 지금 포지션의 위험을 3~5문장으로 해설해 줘."});
}

/* ---- 매매법 연구: 지표 29종 + 연구 카드 → 전략 JSON → 백테스트 · 과최적화 검사 → 통과하면 모의투자 ---- */
// 코인 선물 · 미국 주식 · 국내 주식 · 해외선물 · 국내 지수(국내선물 기초)를 돌아가며 연구한다
export const MARKETS = COINS.flatMap(c => [{market: c.sym, exchange: "binancef", tf: "240", cls: "crypto", name: `${c.ko} 선물`, coin: c.id}, {market: c.sym, exchange: "binancef", tf: "60", cls: "crypto", name: `${c.ko} 선물`, coin: c.id}]);
// 모든 코인에서 백테스트 — 한 코인에만 맞는(과최적화) 전략인지, 여러 코인에 일반화되는지 확인
async function crossCoinTest(spec, tf, excludeSym){
  const Q = await import("../nuri-ai/quant.js"), out = [];
  for (const c of COINS){
    if (c.sym === excludeSym) continue;
    try { const cs = await kl(c.sym, tf, 1500); const s = Q.backtest(Q.normalizeSpec({...spec, symbol: c.sym}), cs).stats;
      out.push({ko: c.ko, ret: +(s.return_pct ?? 0).toFixed(1), n: s.n_trades ?? 0, pf: s.profit_factor == null ? null : +s.profit_factor.toFixed(2)}); } catch(e){}
  }
  return {results: out, profitable: out.filter(x => x.ret > 0).length, total: out.length};
}
// 자산마다 수수료·슬리피지·펀딩 (주식·선물은 펀딩 없음)
export const COSTS = {crypto: {fee_pct: 0.04, slippage_pct: 0.01, funding_rate_8h_pct: 0.01}, us_stock: {fee_pct: 0.015, slippage_pct: 0.02, funding_rate_8h_pct: 0},
  kr_stock: {fee_pct: 0.1, slippage_pct: 0.03, funding_rate_8h_pct: 0}, futures: {fee_pct: 0.01, slippage_pct: 0.01, funding_rate_8h_pct: 0}, index: {fee_pct: 0.01, slippage_pct: 0.01, funding_rate_8h_pct: 0}};
const IV_NAME = {"15": "15m", "60": "1h", "240": "4h", "D": "1d"}, TF_KO = {"15": "15분", "60": "1시간", "240": "4시간", "D": "일"};
// 두 라인: 일반(모든 보조지표) · 커스텀(직접 만든 수식 지표 중심) — 개발 → 백테스트 → 데모 팀이 각각 다르다
export const LANES = {std: {dev: "dev", bt: "bt", demo: "demo", live: "live", authors: ["qa", "qb", "dev_2", "dev_3", "dev_4"], checker: "val", demoLead: "trader", label: "일반"},
  custom: {dev: "cdev", bt: "cbt", demo: "cdemo", live: "clive", authors: ["cind", "cdev_1", "cdev_2", "cdev_4", "cdev_7"], checker: "cbt_lead", demoLead: "cdemo_lead", label: "커스텀 지표"}};
function researchLog(lane){ try { const l = JSON.parse(localStorage.getItem("coinResearch") || "[]"); return lane ? l.filter(r => (r.lane || "std") === lane) : l; } catch(e){ return []; } }
function addResearch(r){ const l = researchLog(); l.push(r); try { localStorage.setItem("coinResearch", JSON.stringify(l.slice(-200))); } catch(e){} }
export const researchHistory = researchLog;
// LLM 답에서 JSON 뽑기 — 여러 후보를 시도하고, 꼬리 콤마·주석·홑따옴표·잘린 응답(truncation)까지 자동 복구한다.
// 열린 문자열/괄호를 '올바른 중첩 순서'로 닫는다 (잘린 응답 복구)
function _closeOpen(str){
  let inStr = false, esc = false; const st = [];
  for (const ch of str){
    if (inStr){ if (esc) esc = false; else if (ch === "\\") esc = true; else if (ch === '"') inStr = false; continue; }
    if (ch === '"') inStr = true; else if (ch === "{" || ch === "[") st.push(ch); else if (ch === "}" || ch === "]") st.pop();
  }
  let out = str; if (inStr) out += '"';
  out = out.replace(/[,:]\s*$/, "");                 // 값이 끊긴 꼬리 콤마/콜론
  for (let i = st.length - 1; i >= 0; i--) out += st[i] === "{" ? "}" : "]";
  return out;
}
function _repairJSON(s){
  let x = String(s);
  x = x.replace(/\/\/[^\n\r]*/g, "");                 // // 주석
  x = x.replace(/\/\*[\s\S]*?\*\//g, "");              // /* */ 주석
  x = x.replace(/,\s*([}\]])/g, "$1");                 // 꼬리 콤마
  x = x.replace(/'([^'\n\r]*?)'(\s*[:,}\]])/g, '"$1"$2');   // 홑따옴표 값/키 → 쌍따옴표
  return _closeOpen(x);
}
// 깊게 잘린 응답: 미완성 꼬리를 조금씩 잘라내며 닫아 보고, 파싱되면 그걸 쓴다
function _trimClose(s){
  let x = String(s).replace(/\/\/[^\n\r]*/g, "").replace(/\/\*[\s\S]*?\*\//g, "");
  for (let k = 0; k < 60; k++){
    const v = _closeOpen(x.replace(/,\s*([}\]])/g, "$1"));
    try { const o = JSON.parse(v); if (o && typeof o === "object") return v; } catch(e){}
    const cut = Math.max(x.lastIndexOf(","), x.lastIndexOf("{"), x.lastIndexOf("["));   // 미완성 꼬리 제거
    if (cut <= 0) break; x = x.slice(0, cut);
  }
  return null;
}
function _balancedBrace(t){
  const i = t.indexOf("{"); if (i < 0) return null;
  let d = 0, inStr = false, esc = false;
  for (let j = i; j < t.length; j++){
    const ch = t[j];
    if (inStr){ if (esc) esc = false; else if (ch === "\\") esc = true; else if (ch === '"') inStr = false; continue; }
    if (ch === '"') inStr = true; else if (ch === "{") d++; else if (ch === "}" && --d === 0) return t.slice(i, j + 1);
  }
  return null;
}
function pickJSON(t){
  t = String(t || "");
  const cands = [], re = /```(?:json)?\s*([\s\S]*?)```/gi; let m;
  while ((m = re.exec(t))) cands.push(m[1]);                 // 닫힌 코드블록들
  const open = t.match(/```(?:json)?\s*([\s\S]*)$/i); if (open && !open[1].includes("```")) cands.push(open[1]);   // 안 닫힌 블록(잘림)
  const bb = _balancedBrace(t); if (bb) cands.push(bb);      // 균형 잡힌 첫 {...}
  const greedy = t.match(/\{[\s\S]*\}/); if (greedy) cands.push(greedy[0]);   // 최후: 첫 { ~ 마지막 }
  for (let c of cands){
    c = String(c).replace(/^```(?:json)?/i, "").replace(/```\s*$/, "").trim();
    for (const v of [c, _repairJSON(c), _trimClose(c)]){ if (v == null) continue; try { const o = JSON.parse(v); if (o && typeof o === "object") return o; } catch(e){} }
  }
  return null;
}
const fmtDay = t => t ? new Date(t).toISOString().slice(0, 10) : "?";
async function research(lane = "std"){
  const L = LANES[lane] || LANES.std;
  const Q = await import("../nuri-ai/quant.js"), P = await import("../nuri-ai/paper.js");
  const n = researchLog(lane).length, a = agentById(L.authors[n % L.authors.length]), mk = MARKETS[(n * 5 + (lane === "custom" ? 3 : 0)) % MARKETS.length], tf = mk.tf, iv = IV_NAME[tf];
  fire({kind: "busy", agent: a, text: `🧪 ${mk.name} ${TF_KO[tf]}봉 매매법 구상 중 (가장 오래된 과거부터)`});
  // ① 가능한 가장 긴 과거 캔들 (없으면 최근 1,500봉)
  let cs = null, hist = "";
  try { const H = await import("../nuri-ai/history.js"); const h = await Promise.race([H.historyCandles({market: mk.market, exchange: mk.exchange, interval: iv, maxBars: tf === "D" ? 30000 : 20000}), new Promise((_, rej) => setTimeout(() => rej(new Error("전체 과거 받기 90초 초과 — 최근 캔들로 대신")), 90e3))]); cs = h.candles; hist = h.note && /\d{4}-\d{2}-\d{2}/.test(h.note) ? h.note : `${fmtDay(h.from)}~${fmtDay(h.to)} · ${cs.length.toLocaleString()}봉${h.note ? " · " + h.note : ""}`; } catch(e){ hist = ""; }
  if (!cs || cs.length < 300){ cs = (await candlesFor({market: mk.market, exchange: mk.exchange, timeframe: tf}, 1500)).cs; hist = `최근 ${cs.length.toLocaleString()}봉 (${fmtDay(cs[0]?.t)}~)`; }
  // ② 코인이면 호가·고래·선물 흐름과 펀딩 이력도 함께
  let flowText = "", deriv = null;
  if (mk.cls === "crypto"){
    try { const F = await import("../nuri-ai/flow.js"); const [fs, dh] = await Promise.all([F.flowSnapshot({symbol: mk.market}).catch(() => null), F.derivHistory({symbol: mk.market, days: 30}).catch(() => null)]); flowText = fs?.text || ""; deriv = dh?.deriv || null; } catch(e){}
  }
  const snap = Q.snapshot(cs), cards = await Q.loadCards().catch(() => []);
  const tried = researchLog().slice(-8).map(r => `- ${r.name} (${r.market} ${r.tf}): ${r.pass ? "통과" : "불통과"}, 검증 구간 ${r.oos?.toFixed?.(1)}%`).join("\n");
  const levHint = {crypto: "코인 선물은 1~125배", us_stock: "주식은 보통 1~4배", kr_stock: "주식은 보통 1~2.5배", futures: "선물은 보통 5~20배", index: "지수 선물은 보통 5~20배"}[mk.cls];
  const tgt0 = assignModels()[a.id], local = !tgt0 || tgt0.id === "ollama";   // 로컬 모델은 1만 토큰 프롬프트를 읽다가 끊겼음 → 간결 프롬프트
  const sys = personaOf(a, (lane === "custom" ? "이번 일은 새 매매법 개발(커스텀 지표 라인)이다. 진입·청산의 핵심 조건은 반드시 직접 만든 custom 수식 지표로 하고, 기본 지표는 필터로만 쓴다. " : "이번 일은 모든 보조지표를 조합하는 새 매매법 개발이다. 기본 29종과 tv_ 지표에서 서로 다른 성격(추세·모멘텀·변동성·거래량) 3개 이상을 쓴다. ") + " 아래 형식 설명을 따라 전략 JSON 하나를 ```json 블록으로 쓰고, 블록 뒤에 왜 이 전략인지 2~3문장으로 말한다.") + "\n\n" + (local ? compactSpecPrompt(Q) : Q.STRATEGY_PROMPT)
    + (mk.cls === "crypto" ? `\n\n## 레버리지 — 청산 공식 역산 프레임워크 (필수)\n코인 선물은 최소 20배. 청산거리≈1/레버리지, 손절(stop_loss_pct)은 청산거리의 40% 이하: 20x→손절≤2% · 50x→≤0.8% · 100x→≤0.4% · 200x→≤0.2% (비트 최대 200배·알트 100배). 1회 손실은 자본의 0.5~1%, 물타기 금지, 익절은 손절의 1.5~2.5배(손익비). 수수료(왕복 약 0.08%) 때문에 5·15분봉 초단타는 불리 — 1시간봉 이상 + 상위 추세 필터를 우선. 코드가 레버리지를 손절폭에서 다시 계산한다.` : `\n\n## 레버리지\n레버리지는 1~200배 중 자유롭게 정한다(${levHint}가 일반적). 정한 뒤 코드가 모든 레버리지(1~200배)·상승장·하락장·횡보·폭락·수수료 2~3배·진입 지연 시나리오로 다시 시험한다.`)
    + (lane === "custom" || researchLog().length % 2 ? "\n\n## 이번 과제: 커스텀 지표\n거래소 기본 보조지표만 쓰지 말고 {\"type\":\"custom\",\"expr\":\"수식\"} 지표를 최소 1개 직접 발명해서 조건에 쓴다(예: 거래량 가중 모멘텀, 변동성 대비 이격, 여러 지표의 합성 점수). 수식 문법은 위 설명의 custom 항목을 따른다. 수식 안에서 ind(\"tv_이름\", {파라미터}, \"value|p1~p4\")로 아래 차트 터미널 지표도 쓸 수 있다." : "")
    + (local ? "" : "\n\n## 더 쓸 수 있는 지표\n" + Q.tvCatalogText())
    + "\n\n## ICT/SMC·세션 지표 (네이티브, 신호형은 조건에 ==1 또는 == -1)\nbos(구조돌파 BOS/MSS ±1) · fvg(Fair Value Gap ±1) · ob(오더블록 리테스트 ±1) · sweep(유동성 스윕 반전 ±1) · disp(변위 ±1) · premium(0~1, <0.3 디스카운트=매수존·>0.7 프리미엄=매도존) · session(start,end: UTC 시각 킬존 0/1, 런던 7~10·뉴욕 13~16). 스캘핑/스윙 어디든 추세필터와 조합 가능."
    + (userNote ? `\n\n## 대표님 지시 (최우선)\n${userNote}\n지시에 맞춰 만든다. 커스텀 수식 지표를 반드시 1개 이상 쓰고, 여러 보조지표(기본 29종 + tv_ 지표)를 조합한다.` : "")
    + (cards.length ? "\n\n## 지금까지의 백테스트 연구 카드(참고)\n" + Q.cardsText(cards, local ? 4 : 14) : "");
  const user = `시장: ${mk.name} (${mk.market}, ${mk.exchange === "binancef" ? "바이낸스 선물" : mk.exchange === "yahoo" ? "야후 파이낸스" : mk.exchange}) · ${TF_KO[tf]}봉\n시험할 과거: ${hist}\n지금 차트(보조지표 29종):\n${snapText(snap)}\n${JSON.stringify(snap.ind || {}).slice(0, 2200)}${flowText ? "\n\n호가·고래·선물 흐름(지금):\n" + flowText.slice(0, 1500) : ""}\n\n최근 우리 팀이 시험한 전략(겹치지 않게):\n${tried || "(아직 없음)"}\n\n${a.id === "qa" ? "추세추종" : "역추세·변동성"} 계열로 새 전략 하나를 만들어 주세요. symbol은 ${mk.market}, interval은 ${iv}.${deriv ? " funding·oi·oi_change_pct·long_short 피연산자도 쓸 수 있습니다." : ""}`;
  const e = await solo(a, {room: L.dev, sys, user, maxTokens: 2200, temperature: 0.8, role: "code", json: true});   // 전략 JSON은 코드·구조화 잘하는 모델로 라우팅 + 토큰 넉넉히(잘림 방지)
  let spec = pickJSON(e.raw || e.text);
  if (!spec){ post({ch: L.dev, kind: "system", text: `${a.name}의 답에서 전략 JSON을 찾지 못했습니다`}); addResearch({lane, name: "(형식 오류)", market: mk.market, tf, pass: false, t: Date.now()}); return; }
  const norm0 = x => Q.normalizeSpec({...x, symbol: mk.market, interval: iv, risk: {...(x.risk || {}), ...COSTS[mk.cls]}});
  // 모르는 지표: 수식(expr)이 있으면 custom 으로, 없으면 그 지표와 그 지표를 쓰는 조건만 빼고 나머지로 시험 (작은 모델 오타 구제)
  const known = t => { t = String(t || "").toLowerCase(); return t === "custom" || !!Q.IND_REGISTRY[t] || !!Q.IND_REGISTRY[(Q.IND_ALIAS || {})[t]]; };
  const norm = x => { try { return norm0(x); } catch(e0){
    const bad = (x.indicators || []).filter(i => !known(i.type) && !i.expr).map(i => String(i.id || i.type)); if (!bad.length && !(x.indicators || []).some(i => !known(i.type))) throw e0;
    const y = JSON.parse(JSON.stringify(x)), uses = v => bad.some(b => new RegExp("(^|[^\\w])" + b.replace(/\W/g, "") + "(?![\\w])").test(String(v ?? "")));
    y.indicators = (y.indicators || []).filter(i => !bad.includes(String(i.id || i.type))).map(i => !known(i.type) && i.expr ? {...i, type: "custom"} : i);
    for (const g of ["long_entry", "short_entry", "long_exit", "short_exit"]){ const G = y[g]; const arr = Array.isArray(G) ? G : G?.conditions; if (!Array.isArray(arr)) continue;
      const kept = arr.filter(c => typeof c === "string" ? !uses(c) : !(uses(c?.left) || uses(c?.right))); if (Array.isArray(G)) y[g] = kept; else G.conditions = kept; }
    return norm0(y); } };
  try { spec = norm(spec); }
  catch(err0){   // 형식 오류는 버리지 않고 오류 내용을 돌려줘 고치게 한다: 1차 본인, 그래도 안 되면 같은 팀 다른 모델 동료가 한 번 더 (짧은 프롬프트라 로컬 모델도 빠름)
    const FIXSYS = "너는 전략 JSON 수리기다. 오류를 고친 JSON 하나만 출력한다. 지원 지표만 쓴다: " + Object.keys(Q.IND_REGISTRY || {}).filter(k => !k.startsWith("tv_")).join(", ") + " + custom 수식."
      + ' 형식: {"name":"..","indicators":[{"id":"r","type":"rsi","length":14},{"id":"e","type":"ema","length":50}],"long_entry":{"logic":"all","conditions":[{"left":"r","op":"crosses_above","right":"30"},{"left":"close","op":">","right":"e"}]},"short_entry":{"logic":"all","conditions":[{"left":"r","op":"crosses_below","right":"70"},{"left":"close","op":"<","right":"e"}]},"long_exit":{"logic":"any","conditions":[{"left":"r","op":">","right":"65"}]},"short_exit":{"logic":"any","conditions":[{"left":"r","op":"<","right":"35"}]},"risk":{"leverage":25,"stop_loss_pct":1.5,"take_profit_pct":3}}'
      + " · op 는 > < >= <= crosses_above crosses_below 만 · left/right 는 indicators 의 id(여러 출력이면 id.출력명, 예 m.line) 또는 숫자 또는 close/open/high/low/volume · long_entry 와 short_entry 를 반드시 2~4개 조건으로 채운다(비우면 실패).";
    const mate = AGENTS.find(x => x.team === a.team && x.id !== a.id && !x.lead) || AGENTS.find(x => x.team === a.team && x.id !== a.id);
    let lastErr = err0, fixed = null;
    for (const fixer of [a, mate].filter(Boolean)){
      try {
        post({ch: L.dev, kind: "system", text: `${fixer.name}: 형식 오류 → ${fixer === a ? "자가 수정" : "동료 수정"} (${String(lastErr.message).slice(0, 80)})`});
        const fx = await solo(fixer, {room: L.dev, sys: FIXSYS, user: `오류: ${lastErr.message}\n\nJSON:\n${JSON.stringify(spec).slice(0, 3500)}`, maxTokens: 1600, temperature: 0.2, role: "code", json: true});
        fixed = norm(pickJSON(fx.raw || fx.text) || {}); break;
      } catch(e){ lastErr = e; }
    }
    if (!fixed){ post({ch: L.dev, kind: "system", text: `전략 형식 오류(${a.name}, 수정 2회 실패 → 이번 건 건너뜀): ${String(lastErr.message).slice(0, 160)}`}); addResearch({lane, name: spec.name || "(형식 오류)", market: mk.market, tf, pass: false, t: Date.now()}); return; }
    spec = fixed;
  }
  if (spec.warnings?.length) post({ch: L.dev, kind: "system", text: `${a.name}: 못 쓰는 조건 ${spec.warnings.length}개는 빼고 나머지로 시험 (${spec.warnings[0].slice(0, 90)})`});
  // 청산 공식 역산 강제(코인 선물): 손절≤2%(20x 기준)로 묶고, 레버리지 = floor(40/손절%) · 최소 20배 · 비트 200·알트 100 상한
  if (mk.cls === "crypto" && spec.risk){ const sl = Math.min(2, Math.max(0.25, +spec.risk.stop_loss_pct || 2)), cap = mk.market === "BTCUSDT" ? 200 : 100;
    spec.risk.stop_loss_pct = sl; spec.risk.leverage = Math.max(20, Math.min(cap, Math.floor(40 / sl)));
    if (!(+spec.risk.take_profit_pct > sl)) spec.risk.take_profit_pct = +(sl * 2).toFixed(2); }
  // 데이터 모델 제약 검사 (Legend 방식): Error 는 백테스트 전에 돌려보냄, Warn 은 표시만
  const SD = await lib("sdlc"), vchk = SD.validate("Strategy", spec);
  if (!vchk.ok){ post({ch: L.dev, kind: "system", text: `전략 제약 위반(${a.name}): ${vchk.fails.filter(f => f.level === "Error").map(f => f.text).join(", ")} → 다시 만듭니다`}); addResearch({lane, name: spec.name, market: mk.market, tf, pass: false, t: Date.now()}); return; }
  const v = agentById(L.checker);
  fire({kind: "busy", agent: v, text: `🧮 ${spec.name} · ${cs.length.toLocaleString()}봉 백테스트 · 시나리오 검사 중`});
  const bt = Q.backtest(spec, cs, {deriv}), wf = Q.walkForward(spec, cs, {deriv});
  let scen = "", scenObj = null;
  try { const S = await import("../nuri-ai/scenarios.js"); scenObj = S.runScenarios(spec, cs, {deriv}); scen = S.scenarioText(scenObj); } catch(err){ scen = ""; }
  const st = x => ({ret: +(x?.return_pct ?? 0), dd: +(x?.max_dd_pct ?? 0), win: +(x?.win_rate ?? 0), pf: x?.profit_factor == null ? null : +x.profit_factor, n: x?.n_trades ?? 0});
  post({ch: L.bt, kind: "bt", agent: L.checker, lane, name: spec.name, market: mk.market, mname: mk.name, tf, hist, all: st(bt.stats), is: st(wf.is), oos: st(wf.oos), pass: wf.pass, reasons: wf.reasons, author: a.name, spec, scen, lev: spec.risk?.leverage});
  addResearch({lane, name: spec.name, market: mk.market, tf, pass: wf.pass, oos: +(wf.oos?.return_pct ?? 0), t: Date.now()});
  // 검증 보강 + 과최적화 관문: 워크포워드(70/30)에 더해 견고성(순열 검정·5구간 일관성·위생·최소 거래수)까지 통과해야 데모에 올린다
  let robust = {ok: true, why: ""};
  try {
    const H = await lib("hyperopt"), RB = await lib("robust"), tfMin = {"15": 15, "60": 60, "240": 240, "D": 1440}[tf] || 60;
    const an = H.analyzers(bt.equity, bt.trades, {perYear: 365 * 24 * 60 / tfMin}), pt = RB.permutationTest(bt.trades.map(t => t.pnl)), bs = RB.bootstrapSharpe(bt.trades.map(t => t.pnl)), mw = RB.multiWindow(Q, spec, cs, 5), hy = RB.hygiene(bt);
    // 과최적화 걸러내기: 운일 확률 p ≤ 0.1 · 5구간 중 60% 이상 이익 · 위생 통과 · 거래 8회 이상 (못 재면 통과)
    const nTr = (wf.oos?.n_trades ?? bt.stats?.n_trades ?? 0);
    const pOK = pt.p == null || pt.p <= 0.1, mwOK = mw.total < 3 || mw.positive >= Math.ceil(mw.total * 0.6), hyOK = hy.ok !== false, nOK = nTr >= 8;
    robust = {ok: pOK && mwOK && hyOK && nOK, why: [!pOK && `운일확률 ${pt.p?.toFixed(2)}`, !mwOK && `구간일관성 ${mw.positive}/${mw.total}`, !hyOK && (hy.fails || []).join(","), !nOK && `거래 ${nTr}회(8 미만)`].filter(Boolean).join(" · "),
      p: pt.p ?? null, mwPos: mw.positive ?? null, mwTotal: mw.total ?? null, sqn: Number.isFinite(an.sqn) ? +an.sqn.toFixed(2) : null};
    const days = Math.max(1, (cs.at(-1).t - cs[0].t) / 864e5), f2 = x => x == null || !Number.isFinite(x) ? "—" : (+x).toFixed(2);
    table(L.bt, L.checker, `🔬 ${spec.name} 검증 보강`, ["항목", "값", "뜻"], [["SQN", `${f2(an.sqn)} (${an.sqnGrade})`, "√거래수 × 평균/표준편차 — 2 이상 보통, 3 이상 좋음"], ["VWR", f2(an.vwr), "일정한 성장선에서 덜 흔들릴수록 높음"], ["최장 물림", `${an.maxddLen}봉`, "고점 회복까지 걸린 가장 긴 기간"], ["연승/연패", `${an.streakWon}/${an.streakLost}`, ""],
      ["운일 확률 p", f2(pt.p), pt.p == null ? "거래 부족" : pt.p <= 0.05 ? "운으로 보기 어려움" : "운일 가능성 큼(주의)"], ["부트스트랩 샤프 90% 구간", bs ? `${f2(bs.lo)} ~ ${f2(bs.hi)}` : "—", "0 아래가 넓으면 불안정"], ["5구간 이익", `${mw.positive}/${mw.total}`, "기간별로 고르게 버는지"],
      ["손실함수 Sharpe/Sortino/Calmar", `${f2(-H.LOSSES.SharpeDaily.f(bt.trades, 10000, days))} / ${f2(-H.LOSSES.SortinoDaily.f(bt.trades, 10000, days))} / ${f2(-H.LOSSES.Calmar.f(bt.trades, 10000, days))}`, "freqtrade 하이퍼옵트 기준값"], ["위생", hy.ok ? (hy.warns.join(", ") || "이상 없음") : hy.fails.join(", "), ""], ...(vchk.fails.length ? [["제약 경고", vchk.fails.map(f => f.text).join(", "), "Warn"]] : [])],
      "참고 지표 · 통과 판정은 위 코드 관문(70/30 워크포워드)이 함");
    if (wf.pass){ const rv = SD.propose(spec, {author: a.name, why: "백테스트 통과"}); SD.decide(spec.name, rv.id, true, {who: v.name, why: "코드 관문 통과"}); }
    journal("audit", "backtest", spec.name, {pass: wf.pass, oos: st(wf.oos), p: pt.p, sqn: an.sqn}, v.id, "백테스트");
  } catch(err){}
  fire({kind: "bubble", agent: v, text: `${wf.pass ? "✅ 통과" : "❌ 불통과"}: ${spec.name} — ${wf.reasons.slice(0, 2).join(", ")}`});
  // 검증관이 시나리오 결과를 말로 설명 (통과했거나 시나리오가 있을 때)
  if (scen) await solo(v, {room: L.bt, sys: personaOf(v, "코드가 낸 백테스트·시나리오 결과를 3~5문장으로 설명한다. 어느 레버리지까지 견디는지, 어떤 장세에서 약한지, 최악의 해와 낙폭을 짚고, 통과·불통과 판정은 코드 판정을 따른다."),
    user: `전략: ${spec.name} (${mk.name} ${TF_KO[tf]}봉, 레버리지 ${spec.risk?.leverage}배)\n과거: ${hist}\n판정: ${wf.pass ? "통과" : "불통과"} — ${wf.reasons.join(", ")}\n\n시나리오:\n${scen}`,
    train: "아래 백테스트·시나리오 결과를 보고 이 전략이 어느 레버리지까지 견디는지, 어떤 장세에서 약한지, 최악의 구간을 쉬운 말로 설명해 줘."});
  if (wf.pass && !isClaude(e.model)){
    const ans = `${noMind(e.raw || "").replace(/```(?:json)?[\s\S]*?```/, "```json\n" + JSON.stringify(spec, null, 1) + "\n```")}\n\n백테스트(검증 구간): 수익 ${st(wf.oos).ret}% · 손익비 ${st(wf.oos).pf ?? "-"} · 거래 ${st(wf.oos).n}회`;
    await keep("office-strategy", [{role: "user", content: clip(user, 3000)}, {role: "assistant", content: ans}], {agent: a.id, model: e.model}).catch(() => null);
  }
  // 아깝게 탈락한 전략(검증 거래 6+ · 검증 수익 > -3%)은 '개선 후보'로 보관 → 하이퍼옵트·봇개선이 다듬어 통과시키기를 시도
  if (!(wf.pass && robust.ok)){ const o = wf.oos || {}; if ((o.n_trades ?? 0) >= 6 && (o.return_pct ?? -99) > -3){
    const NM = readJ("coinNearMiss", []).filter(x => x.name !== spec.name); NM.push({name: spec.name, spec, market: mk.market, exchange: mk.exchange, tf, lane, score: +(o.return_pct || 0), why: robust.ok ? "워크포워드 미달" : robust.why, t: Date.now()});
    writeJ("coinNearMiss", NM.sort((a, b) => b.score - a.score).slice(0, 12)); } }
  if (wf.pass && !robust.ok){   // 워크포워드는 통과했지만 견고성(과최적화) 관문 미달 → 데모 보류
    post({ch: L.bt, kind: "system", text: `⚠ ${spec.name}: 워크포워드는 통과했지만 과최적화 의심으로 데모 보류 (${robust.why}) · 더 견고한 전략만 모의투자에 올립니다`});
    addResearch({lane, name: spec.name + " (견고성 미달)", market: mk.market, tf, pass: false, oos: +(wf.oos?.return_pct ?? 0), t: Date.now()});
  }
  if (wf.pass && robust.ok){
    saveDoc({title: `매매법 · ${spec.name} (${mk.name} ${TF_KO[tf]}봉) 검증 통과`, path: `ghcoin/strategies/${String(spec.name).replace(/[\\/:*?"<>|\s]+/g, "_").slice(0, 50)}.json`, content: JSON.stringify({spec, backtest: {all: st(bt.stats), is: st(wf.is), oos: st(wf.oos), reasons: wf.reasons}, scenarios: scen || ""}, null, 2), team: L.bt, agent: a.id});
    // 데모 등록 전에 교차검증(모든 코인)을 먼저 돌려 그 결과를 전략에 함께 저장 → 콘테스트 신뢰점수에 반영
    let cc = null;
    try {
      cc = await crossCoinTest(spec, tf, mk.market);
      if (cc.total){
        table(L.bt, a.id, `🌐 ${spec.name} — 모든 코인 일반화 (개발: ${mk.name})`, ["코인", "수익%", "거래", "손익비"], cc.results.map(r => [r.ko, pc(r.ret), String(r.n), r.pf ?? "—"]), `개발 코인 외 ${cc.total}개 중 ${cc.profitable}개에서 수익${cc.profitable <= 1 ? " ⚠️ 한 코인에만 맞는 과최적화 의심" : " — 여러 코인에 통하므로 견고"}`);
        addNote(L.bt, `${spec.name} 일반화: ${cc.total}개 중 ${cc.profitable}개 수익`, "교차검증");
      }
    } catch(e){}
    // Erfaniaa(멀티코인 백테스터) 규칙: 다른 코인 3개 이상 시험해 1개 이하만 수익이면 '그 코인에만 맞춘' 과최적화 → 데모 투입 안 함(개선 후보로만 보관)
    if (cc && cc.total >= 3 && cc.profitable <= 1){
      post({ch: L.demo, kind: "system", text: `⛔ ${spec.name}: 다른 코인 ${cc.total}개 중 ${cc.profitable}개만 수익 — 과최적화로 판단해 데모 투입 보류 (개선 후보로 보관)`});
      try { const nm = readJ("coinNearMiss", []); nm.push({name: spec.name, spec, market: mk.market, exchange: mk.exchange, tf, cls: mk.cls, lane, why: `교차코인 ${cc.profitable}/${cc.total}`, t: Date.now()}); writeJ("coinNearMiss", nm.slice(-20)); } catch(e){}
      addResearch({lane, name: spec.name, market: mk.market, tf, pass: false, t: Date.now()});
      return;
    }
    const s = await P.addStrategy({spec, market: mk.market, exchange: mk.exchange, tf, author: a.name, wf: {is: st(wf.is), oos: st(wf.oos)}, cls: mk.cls, mname: mk.name, lane,
      robust: {ok: robust.ok, p: robust.p ?? null, mwPos: robust.mwPos ?? null, mwTotal: robust.mwTotal ?? null, sqn: robust.sqn ?? null}, crossCoin: cc ? {profitable: cc.profitable, total: cc.total} : null});
    post({ch: L.demo, kind: "system", text: `📈 데모거래 시작: ${s.name} (${mk.name} ${TF_KO[tf]}봉 · 레버리지 ${spec.risk?.leverage}배 · ${a.name} 개발 · ${v.name} 검증 통과·견고성 OK) · 가상 10,000`});
    fire({kind: "trade", agent: agentById(L.demoLead), text: `📈 ${s.name} 모의투자 시작합니다`});
    journal("record", "strategy", s.id, {author: a.name, phash: specHash(spec)}, a.id, "개발 → 데모 투입");   // 승격 때 전략이 바뀌지 않았는지 대조
    if (cc && cc.total && cc.profitable <= 1) post({ch: L.demo, kind: "system", text: `⚠️ ${s.name}: 개발한 ${mk.name} 외 다른 코인에선 거의 안 통함 — 과최적화 가능성, 실거래 승격은 신중히`});
  }
}

/* ---- SNS 여론 ---- */
const SNS_TOPICS = ["crypto", "crypto", "macro", "crypto"];
async function snsCheck(){
  const a = agentById("sns"), i = +localStorage.getItem("coinSns") || 0, topic = SNS_TOPICS[i % SNS_TOPICS.length];
  localStorage.setItem("coinSns", String(i + 1));
  fire({kind: "busy", agent: a, text: `📱 ${topic === "crypto" ? "코인" : topic === "us" ? "미국 주식" : "경제"} SNS 둘러보는 중`});
  const r = await TOOLS.sns_buzz.run({topic});
  for (const src of (r.sources || []).slice(0, 4)) post({ch: "news", kind: "work", agent: "sns", icon: "📱", text: src.title, url: src.url});
  await solo(a, {room: "news", sys: personaOf(a, "SNS에서 본 분위기를 3~5문장으로 해설한다. 사람들이 무엇에 흥분하거나 겁먹는지, 쏠림이 지나친지(역발상 신호인지) 말한다. SNS 글은 의견일 뿐이라는 점을 잊지 않는다."), user: r.text.slice(0, 5000), train: "아래 SNS 글과 공포·탐욕 지수를 보고 지금 사람들의 분위기와 쏠림을 해설해 줘. SNS 글은 의견이라는 점도 짚어 줘."});
  const fg = (r.text.match(/공포·탐욕 지수\] 오늘 (\d+)/) || [])[1];
  // 여론 밴드 (TradingAgents 감성 분석 규칙): 90/10 이상 쏠림은 역발상 경고, 70/30 은 완만한 쏠림, 표본이 적으면 확신 낮음
  if (fg){ const v = +fg, band = v >= 90 ? "극단적 탐욕(역발상 경고)" : v >= 70 ? "탐욕(완만한 강세 쏠림)" : v > 55 ? "약한 탐욕" : v >= 45 ? "중립·불확실" : v > 30 ? "약한 공포" : v > 10 ? "공포(완만한 약세 쏠림)" : "극단적 공포(역발상 경고)";
    post({ch: "news", kind: "work", agent: "sns", icon: "🌡", text: `여론 밴드: 공포·탐욕 ${v} → ${band} · 점수 ${(v / 10).toFixed(1)}/10 · 확신 ${(r.sources || []).length >= 20 ? "보통" : "낮음(표본 적음)"}`}); }
  if (fg && (+fg <= 15 || +fg >= 85) && usage().auto < officeCfg().dailyMax)
    enqueue({topic: `코인 공포·탐욕 지수가 ${fg}로 극단입니다. SNS 분위기와 시장을 함께 점검해 주세요.`, room: "news", trigger: "event", title: `여론-극단-${fg}`, agents: ["sns", "coin_spot", "coin_fut"]});
}

/* ---- 경제 리서치 ---- */
const ECON_Q = ["오늘 비트코인 뉴스 ETF 규제", "crypto market news today bitcoin ethereum", "코인 거래소 공지 상장 해킹", "fed rate decision crypto impact this week", "알트코인 뉴스 솔라나 리플 도지", "stablecoin regulation news"]; const _OLD_ECON = ["오늘 미국 경제 뉴스 연준 금리 물가", "global economy outlook this week markets", "한국 경제 환율 수출 금리 뉴스", "oil price OPEC dollar news today", "중국 경기 부양책 뉴스", "부동산 시장 금리 대출 규제 뉴스", "AI 반도체 수요 실적 뉴스"];
async function economyCheck(){
  const i = +localStorage.getItem("coinEcon") || 0, q = ECON_Q[i % ECON_Q.length], a = agentById(["macro", "research", "news_4", "news_5", "news_6"][i % 5]);
  localStorage.setItem("coinEcon", String(i + 1));
  fire({kind: "busy", agent: a, text: `🔎 '${q}' 찾아보는 중`});
  const r = await TOOLS.web_search.run({query: q, n: 6});
  for (const src of (r.sources || []).slice(0, 3)) post({ch: a.team, kind: "work", agent: a.id, icon: "📰", text: src.title, url: src.url});
  await solo(a, {room: a.team, sys: personaOf(a, "검색 결과(뉴스·기사)로 지금 코인 시장에 무슨 일이 있는지 4~6문장으로 해설한다. 기사 제목을 나열하지 말고 흐름으로 묶고, 코인 가격에 주는 의미를 한 줄 덧붙인다. 근거 문장 끝에 [번호]."), user: `검색어: ${q}\n\n${String(r.text || "").slice(0, 6000)}`, train: "아래 검색 결과로 지금 경제가 어떻게 돌아가는지 흐름으로 해설하고, 코인·주식·부동산에 주는 의미를 덧붙여 줘. 근거 문장 끝에 [번호]."});
}

/* ---- 컴퓨터 작업 (문서/GHNano 사무실 폴더) ---- */
async function computerWork(){
  const {codeCall} = await import("../nuri-ai/engine.js"), P = await import("../nuri-ai/paper.js");
  const a = agentById("eng"), day = today();
  fire({kind: "busy", agent: a, text: "💻 사무실 폴더에 보고서 정리 중"});
  const book = await P.loadBook();
  const res = researchLog().slice(-20);
  const log = (await loadLog()).filter(e => e.kind === "agent" && !e.chat && e.text && Date.now() - e.t < 864e5).slice(-12);
  const md = `# GH Coin 일일 보고서 · ${day}\n\n## 모의투자\n${await P.bookText()}\n\n## 매매법 연구 (최근 ${res.length}건)\n${res.map(r => `- ${r.pass ? "✅" : "❌"} ${r.name} · ${r.market} ${r.tf} · 검증 구간 ${(+r.oos || 0).toFixed(1)}%`).join("\n") || "- 없음"}\n\n## 오늘 팀 발언 요약\n${log.map(e => `- **${agentById(e.agent)?.name}**: ${e.text.replace(/\s+/g, " ").slice(0, 200)}`).join("\n")}\n`;
  const csv = "strategy,market,side,entry_time,entry,exit_time,exit,pnl_usdt,roe_pct,reason\n" + book.strategies.flatMap(s => s.trades.map(t => [s.name, s.market, t.side, new Date(t.entryT).toISOString(), t.entryP, new Date(t.exitT).toISOString(), t.exitP, t.pnl.toFixed(2), t.roe.toFixed(2), t.reason].map(x => `"${String(x).replace(/"/g, '""')}"`).join(","))).join("\n");
  await codeCall("write", {ws: "office", path: `ghcoin/reports/${day}.md`, content: md});
  await saveDoc({title: `일일 보고서 ${day}`, path: `ghcoin/reports/${day}.md`, content: md, team: "hq", agent: "eng"});
  await codeCall("write", {ws: "office", path: "ghcoin/data/trades.csv", content: csv});
  for (const s of book.strategies.filter(x => x.status === "active")) await codeCall("write", {ws: "office", path: `ghcoin/strategies/${s.name.replace(/[\\/:*?"<>|]/g, "_")}.json`, content: JSON.stringify(s.spec, null, 2)});
  post({ch: "hq", kind: "work", agent: "eng", icon: "💾", text: `문서/GHNano 사무실/ghcoin 에 저장: reports/${day}.md · data/trades.csv · strategies/*.json`});
  // 세 번에 한 번은 직접 파이썬 분석 스크립트를 짜서 돌려 본다
  const k = +localStorage.getItem("coinComp") || 0; localStorage.setItem("coinComp", String(k + 1));
  if (k % 3 !== 2 || !book.strategies.some(s => s.trades.length)) return;
  const m = {id: uid(), room: "hq", name: "데이터-분석", trigger: "auto", topic: "ghcoin/data/trades.csv(데모거래 거래 기록)를 분석하는 파이썬 스크립트 ghcoin/analysis/summary.py를 사무실 폴더에 만들고 실행해서, 전략별 승률·평균 손익·최대 연속 손실을 보고해 주세요. 파이썬이 없으면 그 사실만 보고합니다.", order: ["eng"], done: [], ctl: new AbortController(), t: Date.now(), models: assignModels()};
  await speak(a, m, [], m.models.eng, m.ctl.signal);
}

/* ============ 스스로 성장: 팀 노트(배운 것) · 성장 과제 · 회고 ============ */
// 팀마다 배운 것을 쌓아 두고 다음 일할 때 지시문에 넣는다. 회고에서 부족한 점을 찾아 과제를 만들고, 다음 주기에 담당자가 직접 해낸다.
const NOTES_KEY = "coinNotes", BL_KEY = "coinBacklog";
const readJ = (k, d) => { try { return JSON.parse(localStorage.getItem(k) || "") ?? d; } catch(e){ return d; } };
const writeJ = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch(e){} };
export function teamNotes(team){ return (readJ(NOTES_KEY, {})[team] || []); }
export function addNote(team, text, src = ""){
  const all = readJ(NOTES_KEY, {}), list = all[team] || [];
  const t = String(text || "").replace(/\s+/g, " ").trim().slice(0, 240); if (!t || list.some(n => n.text === t)) return;
  list.push({t: Date.now(), text: t, src}); all[team] = list.slice(-40); writeJ(NOTES_KEY, all);
}
function notesText(team){
  const n = teamNotes(team).slice(-6);
  return n.length ? `- 우리 팀이 지금까지 배운 것(반영할 것): ${n.map(x => x.text).join(" / ")}\n` : "";
}
export function backlog(){ return readJ(BL_KEY, []); }
function saveBacklog(list){ writeJ(BL_KEY, list.slice(-200)); fire({kind: "growth"}); }
export function addTask({team, title, why = "", owner = ""}){
  const list = backlog(); const t = String(title || "").trim().slice(0, 160);
  if (!t || list.some(x => x.title === t && x.status !== "done")) return null;
  const own = AGENTS.find(a => a.team === team && (a.name === owner || a.id === owner)) || AGENTS.find(a => a.team === team && !a.lead) || agentById(TEAM_LEAD[team]);
  const item = {id: uid(), team, title: t, why: String(why).slice(0, 200), status: "todo", owner: own?.id || "", t: Date.now(), result: ""};
  list.push(item); saveBacklog(list);
  post({ch: team, kind: "task", agent: item.owner, title: item.title, status: "todo", result: item.why});
  return item;
}
function updateTask(id, patch){ const list = backlog(), it = list.find(x => x.id === id); if (!it) return null; Object.assign(it, patch); saveBacklog(list); return it; }

// 회고: 팀장이 최근 기록·실패·과제를 보고 '배운 것'과 '부족한 점 → 새 과제'를 정한다 (팀 자리에서 짧은 팀 회의)
const RETRO_ORDER = TEAMS.filter(t => t.id !== "hq").map(t => t.id);
async function retro(){
  const i = +localStorage.getItem("coinRetro") || 0, team = RETRO_ORDER[i % RETRO_ORDER.length]; localStorage.setItem("coinRetro", String(i + 1));
  const lead = agentById(TEAM_LEAD[team]), mem = AGENTS.filter(a => a.team === team);
  fire({kind: "huddle", ids: mem.map(a => a.id), host: lead.id});
  const recent = (await loadLog()).filter(e => e.ch === team && Date.now() - e.t < 6 * 3600e3).slice(-25)
    .map(e => `- [${e.kind}] ${agentById(e.agent)?.name || ""}: ${String(e.text || e.title || e.name || "").replace(/\s+/g, " ").slice(0, 160)}${e.kind === "bt" ? ` (${e.pass ? "통과" : "불통과"})` : ""}`).join("\n");
  const open = backlog().filter(x => x.team === team && x.status !== "done").map(x => `- ${x.title}`).join("\n");
  const e = await solo(lead, {room: team, sys: personaOf(lead, `지금은 ${teamById(team).name} 회고·성장 회의다. 최근 기록을 보고 ① 배운 것(다음에 반드시 반영할 교훈) 2~4개 ② 우리 팀에 부족한 점을 메울 구체적인 새 과제 1~3개(누가 맡을지 팀원 이름 포함)를 정한다. 세계적인 기업 수준의 기준으로 냉정하게. 답 마지막에 \`\`\`json {"lessons":["..."],"tasks":[{"title":"...","why":"...","owner":"팀원 이름"}]}\`\`\` 를 붙인다.`),
    user: `팀원: ${mem.map(a => `${a.name}(${a.title})`).join(", ")}\n최근 기록:\n${recent || "(기록 없음 — 첫 회고)"}\n\n아직 안 끝난 과제:\n${open || "(없음)"}`, json: true, maxTokens: 1200, trainRaw: true, role: "code", train: "팀의 최근 업무 기록을 보고 회고해 줘: 배운 것과 부족한 점을 메울 새 과제를 JSON으로."});
  fire({kind: "huddle-end", ids: mem.map(a => a.id)});
  const j = pickJSON(e.raw || e.text) || {};
  for (const l of (j.lessons || []).slice(0, 4)) addNote(team, l, "회고");
  for (const t of (j.tasks || []).slice(0, 3)) addTask({team, title: t.title, why: t.why, owner: t.owner});
}
// 과제 실행: 가장 오래된 과제를 담당자가 도구를 써서 직접 해낸다
async function doTask(){
  const it = backlog().find(x => x.status === "todo"); if (!it) return retro();
  const a = agentById(it.owner) || agentById(TEAM_LEAD[it.team]);
  updateTask(it.id, {status: "doing"}); post({ch: it.team, kind: "task", agent: a.id, title: it.title, status: "doing", result: ""});
  // 개발형 과제는 말로 끝내지 않고 실제 파이프라인(개발→백테스트→관문→데모)으로 실행한다
  const tx = `${it.title} ${it.why || ""}`;
  const route = /커스텀|수식\s*지표|지표.{0,8}(만들|개발|발명|설계)/.test(tx) ? "cdev" : /봇/.test(tx) ? "bot" : /하이퍼옵트|최적화|파라미터|ROI|추적손절|보호장치/.test(tx) ? "opt"
    : /매매법|전략|진입|조건|백테스트|필터|시간봉|손절|익절|손익비/.test(tx) ? "dev" : null;
  if (route){
    post({ch: it.team, kind: "system", text: `🛠 과제를 실제 업무로 실행: ${JOB_KO[route]} ← "${it.title.slice(0, 60)}"`});
    await runJobNow(route, `팀 과제(최우선 반영): ${it.title}${it.why ? ` — 이유: ${it.why}` : ""}`);
    const res = `${JOB_KO[route]} 업무로 실행함 (결과 카드는 #${teamById(JOB_TEAM[route])?.name || route} 방)`;
    updateTask(it.id, {status: "done", result: res, done: Date.now()}); post({ch: it.team, kind: "task", agent: a.id, title: it.title, status: "done", result: res}); return;
  }
  const m = {id: uid(), room: it.team, name: "과제-" + it.title.slice(0, 12), trigger: "auto", topic: `성장 과제: ${it.title}\n왜: ${it.why}\n도구(검색·차트·백테스트·사무실 파일 등)를 써서 실제로 해내고, 결과물과 배운 점을 보고해 주세요. 못 한 부분은 솔직히 말합니다.`, order: [a.id], done: [], ctl: new AbortController(), t: Date.now(), models: assignModels(), place: it.team};
  const turn = await speak(a, m, [], m.models[a.id], m.ctl.signal);
  const res = String(turn?.text || "").replace(/\s+/g, " ").slice(0, 300);
  updateTask(it.id, {status: "done", result: res, done: Date.now()});
  post({ch: it.team, kind: "task", agent: a.id, title: it.title, status: "done", result: res});
  addNote(it.team, `과제 '${it.title.slice(0, 50)}' 결과: ${res.slice(0, 140)}`, "과제");
}

/* ============ 1시간마다 성과 발표 ============ */
export async function listReports(){ const v = await idb.all("coinreport:").catch(() => []); return v.sort((a, b) => b.t - a.t); }
let reportTimer = 0, reporting = false;
export function startReports(){ if (!reportTimer) reportTimer = setInterval(() => maybeReport().catch(e => console.warn(e)), 60e3); }
async function maybeReport(force){
  const last = +localStorage.getItem("coinLastReport") || 0;
  if (reporting || (!force && Date.now() - last < 3600e3)) return null;
  if (!last && !force){ localStorage.setItem("coinLastReport", String(Date.now())); return null; }   // 처음 켰을 때부터 1시간 뒤 첫 발표
  reporting = true;
  try { return await makeReport(last || Date.now() - 3600e3); } finally { reporting = false; }
}
export const presentNow = () => maybeReport(true);
async function makeReport(since){
  await loadLog();
  const ents = LOG.filter(e => e.t >= since);
  const sections = [];
  for (const t of TEAMS.filter(x => x.id !== "hq")){
    const es = ents.filter(e => e.ch === t.id), items = [];
    const said = es.filter(e => e.kind === "agent" && !e.chat).length; if (said) items.push(`발언·분석 ${said}건`);
    const bts = es.filter(e => e.kind === "bt"); if (bts.length) items.push(`매매법 ${bts.length}개 검증 (통과 ${bts.filter(b => b.pass).length}: ${bts.filter(b => b.pass).map(b => b.name).join(", ") || "-"})`);
    const tr = es.filter(e => e.kind === "trade"); if (tr.length) items.push(`모의 거래 ${tr.length}건`);
    for (const e of es.filter(e => e.kind === "re")) items.push(`재개발 후보 ${e.items?.length || 0}곳 발굴 (${e.region}) · 1위 ${e.items?.[0]?.area || "-"} ${e.items?.[0]?.score ?? ""}점`);
    for (const e of es.filter(e => e.kind === "arch")) items.push(`설계안 '${e.name}' 연면적 ${e.metrics?.["연면적_㎡"] ?? "?"}㎡${e.image ? " · 렌더링 완료" : ""}`);
    for (const e of es.filter(e => e.kind === "ml")) items.push(`머신러닝 ${e.market} 정확도 ${e.acc}% (기준 ${e.base}%)`);
    for (const e of es.filter(e => e.kind === "macro")) items.push(`경제지표 ${e.rows?.length || 0}개 예측`);
    for (const e of es.filter(e => e.kind === "forecast")) items.push(`방향 예측 ${e.items?.length || 0}건${e.score ? ` · 적중 ${e.score.hit}/${e.score.n}` : ""}`);
    for (const e of es.filter(e => e.kind === "biz")) items.push(`사업 시뮬레이션 '${e.name}' — ${e.verdict}`);
    for (const e of es.filter(e => e.kind === "files")) items.push(`파일 저장: ${e.title}`);
    for (const e of es.filter(e => e.kind === "task" && e.status === "done")) items.push(`성장 과제 완료: ${e.title}`);
    const next = backlog().filter(x => x.team === t.id && x.status !== "done").slice(0, 2).map(x => x.title);
    if (items.length || next.length) sections.push({team: t.id, name: t.name, lead: agentById(TEAM_LEAD[t.id])?.name, items, next});
  }
  const P = await import("../nuri-ai/paper.js"); const book = await P.bookText().catch(() => "");
  const ceo = agentById("lead"), hour = new Date().getHours();
  const facts = sections.map(s => `## ${s.name} (팀장 ${s.lead})\n${s.items.map(x => "- " + x).join("\n") || "- (이번 시간 기록 없음)"}${s.next.length ? "\n다음: " + s.next.join(" / ") : ""}`).join("\n\n");
  const e = await solo(ceo, {room: "hq", sys: personaOf(ceo, "지금은 매시간 하는 전사 성과 발표다. 아래 사실만으로 대표(사용자)에게 짧게 발표한다: 핵심 성과 3줄 → 기록이 있는 팀만 한 줄씩(해낸 것 · 다음 할 일) → 도움이 필요한 것 1줄. 전체 15줄 이내, 한국어, 마크다운 목록. 기록이 없는 팀은 쓰지 않고, 지어내지 않는다."),
    user: `${hour}시 발표 · 지난 ${Math.round((Date.now() - since) / 60e3)}분\n\n${facts || "(이번 시간 기록 없음)"}\n\n모의투자:\n${book.slice(0, 1500)}`, maxTokens: 1600, train: "아래 팀별 업무 기록으로 대표에게 하는 시간별 성과 발표문을 써 줘."});
  const report = {id: uid(), t: Date.now(), since, title: `${hour}시 성과 발표`, text: noMind(e.text), sections};
  await idb.put("coinreport:" + report.id, report);
  localStorage.setItem("coinLastReport", String(Date.now()));
  post({ch: "hq", kind: "report", title: report.title, text: report.text, reportId: report.id});
  { const d = new Date(), stamp = `${d.toISOString().slice(0, 10)}-${String(hour).padStart(2, "0")}`; saveDoc({title: `${report.title} (${d.toISOString().slice(0, 10)})`, path: `ghcoin/reports/hourly/${stamp}.md`, content: `# ${report.title}\n\n${report.text}\n\n---\n${facts}\n`, team: "hq", agent: "lead"}); }
  fire({kind: "present", report});
  if (computerOn()){ try { const {codeCall} = await import("../nuri-ai/engine.js"); const d = new Date(), stamp = `${d.toISOString().slice(0, 10)}-${String(hour).padStart(2, "0")}`; await codeCall("write", {ws: "office", path: `reports/hourly/${stamp}.md`, content: `# ${report.title}\n\n${report.text}\n\n---\n${facts}\n`}); } catch(err){} }
  try { if (typeof document !== "undefined" && document.hidden && "Notification" in window && Notification.permission === "granted") new Notification("GH Coin · " + report.title, {body: report.text.replace(/[#*]/g, "").slice(0, 140)}); } catch(err){}
  return report;
}

/* ============ 방향 예측 토론 → 예측 장부 → 시간이 지나면 코드가 채점 (모의 검증) ============ */
const FC_KEY = "coinForecasts";
const FC_ASSETS = COINS.slice(0, 5).map(c => ({asset: c.ko, q: c.sym, ex: "binancef", team: c.id}));
async function priceOf(a){ const r = await TOOLS.market_quote.run({symbols: [a.q], exchange: a.ex === "binancef" ? "binancef" : ""}); const row = JSON.parse(r.text || "[]").find(x => x.현재가 != null); return row ? +row.현재가 : null; }
async function scoreForecasts(){
  const list = readJ(FC_KEY, []), due = list.filter(f => !f.result && Date.now() >= f.due);
  if (!due.length) return;
  for (const f of due){
    const now = await priceOf(FC_ASSETS.find(x => x.asset === f.asset) || {q: f.q, ex: f.ex}).catch(() => null); if (now == null) continue;
    const ret = (now / f.p0 - 1) * 100, dir = Math.abs(ret) < 0.2 ? "flat" : ret > 0 ? "up" : "down";
    f.result = f.dir === dir || (f.dir === "flat" && Math.abs(ret) < 0.5) ? "hit" : "miss"; f.ret = +ret.toFixed(2); f.p1 = now;
    f.paper = +((f.dir === "up" ? 1 : f.dir === "down" ? -1 : 0) * ret).toFixed(2);   // 예측대로 1배 모의 매매했다면 수익률
  }
  writeJ(FC_KEY, list.slice(-300));
  const done = list.filter(f => f.result), n = done.length, hit = done.filter(f => f.result === "hit").length;
  const brier = n ? done.reduce((s, f) => s + Math.pow(f.prob / 100 - (f.result === "hit" ? 1 : 0), 2), 0) / n : null;
  post({ch: "entry", kind: "forecast", agent: "strat", items: due.map(f => ({asset: f.asset, dir: f.dir, prob: f.prob, horizon: f.horizon, due: f.due, result: f.result, ret: f.ret, by: f.by})), score: {n, hit, brier: brier == null ? null : +brier.toFixed(3), paper: +done.reduce((s, f) => s + (f.paper || 0), 0).toFixed(2)}});
  for (const f of due) addNote(agentById(f.by)?.team || "entry", `${f.asset} ${f.horizon} 예측(${f.dir} ${f.prob}%) → ${f.result === "hit" ? "적중" : "빗나감"}(${f.ret}%)`, "예측");
}
async function forecastJob(){
  await scoreForecasts();
  const r = await enqueue({topic: `향후 24시간 방향 예측 토론: ${FC_ASSETS.map(a => a.asset).join(", ")}. 각자 차트·호가·뉴스를 확인하고 반드시 '예측: 자산이름 상승|하락|횡보 확률%' 형식의 줄을 남겨 주세요. 반대 의견도 환영합니다. 팀장이 최종 예측을 정리합니다.`, room: "entry", trigger: "auto", title: "24시간-방향-예측", agents: ["trend_lead", "strat", "coin_fut", "devil"]});
  const list = readJ(FC_KEY, []), now = Date.now(), seen = new Set();
  for (const t of r?.turns || []){
    for (const mm of String(t.text).matchAll(/예측\s*[:：]\s*([^\n:：]+?)\s+(상승|하락|횡보)\s*(?:확률)?\s*(\d{1,3})\s*%/g)){
      const a = FC_ASSETS.find(x => mm[1].includes(x.asset) || x.asset.includes(mm[1].trim())); if (!a || seen.has(t.agent.id + a.asset)) continue;
      seen.add(t.agent.id + a.asset);
      const p0 = await priceOf(a).catch(() => null); if (p0 == null) continue;
      list.push({id: uid(), t: now, due: now + 24 * 3600e3, horizon: "24시간", asset: a.asset, q: a.q, ex: a.ex, dir: {상승: "up", 하락: "down", 횡보: "flat"}[mm[2]], prob: Math.min(99, +mm[3]), p0, by: t.agent.id});
    }
  }
  writeJ(FC_KEY, list.slice(-300));
  const mine = list.filter(f => f.t === now);
  if (mine.length) post({ch: "entry", kind: "forecast", agent: "strat", items: mine.map(f => ({asset: f.asset, dir: f.dir, prob: f.prob, horizon: f.horizon, due: f.due, by: agentById(f.by)?.name}))});
}

/* ============ 머신러닝·딥러닝 연구 ============ */
async function mlJob(){
  const ML = await import("../nuri-ai/ml.js"), Q = await import("../nuri-ai/quant.js");
  const i = +localStorage.getItem("coinML") || 0; localStorage.setItem("coinML", String(i + 1));
  const mk = COINS.map(c => ({market: c.sym, exchange: "binancef", tf: "60"}))[i % COINS.length];
  const model = ["mlp", "logreg", "gbs"][i % 3], a = agentById("ml");
  fire({kind: "busy", agent: a, text: `🧠 ${mk.market} ${{mlp: "신경망", logreg: "로지스틱 회귀", gbs: "부스팅 트리"}[model]} 학습 중`});
  let cs; try { const H = await import("../nuri-ai/history.js"); cs = (await Promise.race([H.historyCandles({market: mk.market, exchange: mk.exchange, interval: IV_NAME[mk.tf], maxBars: 6000}), new Promise((_, rej) => setTimeout(() => rej(new Error("긴 과거 받기 30초 초과")), 30e3))])).candles; if (!(cs?.length > 300)) throw new Error("과거 데이터 부족"); } catch(e){ cs = (await candlesFor({market: mk.market, exchange: mk.exchange, timeframe: mk.tf}, 1500)).cs; }
  const res = ML.walkForwardML(cs, {model, horizon: 1, seed: 7 + i}), mt = res.metrics || {};
  const acc = +((mt.accuracy ?? 0) * 100).toFixed(1), base = +((mt.baseline ?? 0.5) * 100).toFixed(1);
  post({ch: "ml", kind: "ml", agent: a.id, market: mk.market, tf: TF_KO[mk.tf], model: {mlp: "신경망(MLP)", logreg: "로지스틱 회귀", gbs: "부스팅 트리"}[model], acc, base, auc: mt.auc ?? null, edge: res.edge, text: ML.mlText(res)});
  const edge = res.edge === "edge";
  { const M0 = readJ("coinML", {}), cid = COINS.find(x => x.sym === mk.market)?.id; if (cid) { M0[cid] = {edge: res.edge, acc, base, prob: res.prob?.at(-1) ?? null, model, t: Date.now()}; writeJ("coinML", M0); } }   // ml-ko 방법론 ML 예측 → 진입 관문
  addNote("ml", `${mk.market} ${model}: 정확도 ${acc}% vs 기준 ${base}% → ${{edge: "통계적 우위", weak: "약한 신호(우위 아님)", none: "우위 없음"}[res.edge] || res.edge}`, "머신러닝");
  if (!edge) return;
  // 우위가 보이면 예측 확률을 커스텀 지표로 써서 전략을 만들고 그대로 백테스트·검증
  const extra = ML.mlSeries(res);
  const spec = Q.normalizeSpec({name: `ML ${model} ${mk.market}`, symbol: mk.market, interval: IV_NAME[mk.tf], indicators: [{id: "mlp", type: "custom", expr: "ml_prob"}],
    // 확률 밴드 (bitoracle-ai-server 규칙): p ≥ 0.60 진입, 0.40~0.60 은 그대로(무거래 구간), 손절 −3% · 익절 +5%
    long_entry: {logic: "all", conditions: [{left: "mlp", op: ">=", right: "0.60"}]}, long_exit: {logic: "any", conditions: [{left: "mlp", op: "<=", right: "0.40"}]},
    short_entry: {logic: "all", conditions: [{left: "mlp", op: "<=", right: "0.40"}]}, short_exit: {logic: "any", conditions: [{left: "mlp", op: ">=", right: "0.60"}]},
    risk: {leverage: 2, position_pct: 20, stop_loss_pct: 3, take_profit_pct: 5, ...COSTS[mk.exchange === "binancef" ? "crypto" : "us_stock"]}});
  const deriv = {extra};
  const bt = Q.backtest(spec, cs, {deriv}), wf = Q.walkForward(spec, cs, {deriv});
  const st = x => ({ret: +(x?.return_pct ?? 0), dd: +(x?.max_dd_pct ?? 0), win: +(x?.win_rate ?? 0), pf: x?.profit_factor == null ? null : +x.profit_factor, n: x?.n_trades ?? 0});
  post({ch: "cbt", kind: "bt", agent: "cbt_lead", lane: "custom", name: spec.name, market: mk.market, mname: mk.market, tf: mk.tf, hist: `머신러닝 예측 확률 전략 · ${cs.length}봉`, all: st(bt.stats), is: st(wf.is), oos: st(wf.oos), pass: wf.pass, reasons: wf.reasons, author: a.name, spec, lev: 2});
}

/* ============ 경제지표 예측 ============ */
async function macroJob(){
  const MA = await import("../nuri-ai/macro.js"), a = agentById("econfc");
  fire({kind: "busy", agent: a, text: "📊 FRED 경제지표 받아서 다음 발표 예측 중"});
  const dash = await MA.macroDashboard({});
  const rows = (dash.rows || []).map(r => ({name: r.name, latest: r.latest, change: r.change, trend: r.trend, forecast: r.forecast, lo: r.lo, hi: r.hi, unit: r.unit, date: r.date, id: r.id, next: r.next, model: r.model, base: r.base}));
  if (!rows.length){ post({ch: "news", kind: "system", text: "FRED 경제지표를 받지 못했습니다" + (dash.errors?.length ? ` (${dash.errors[0].error})` : "")}); return; }
  post({ch: "news", kind: "macro", agent: a.id, rows});
  // 예측 장부: 다음에 새 값이 나오면 채점
  const led = readJ("coinMacroFc", []), now = Date.now();
  for (const r of rows) if (r.forecast != null && !led.some(x => x.id === r.id && x.date === r.date)) led.push({id: r.id, name: r.name, date: r.date, forecast: r.forecast, lo: r.lo, hi: r.hi, base: r.base, t: now});
  for (const x of led.filter(x => x.result == null)){ const r = rows.find(y => y.id === x.id); if (r && r.date && r.date !== x.date){ const s = MA.scoreForecast({forecast: x.forecast, lo: x.lo, hi: x.hi, last: x.base}, r.latest); x.result = s; addNote("news", `${x.name} 예측 ${x.forecast} → 실제 ${r.latest} (${s.inside ? "80% 구간 안" : "구간 밖"}${s.dirHit != null ? s.dirHit ? " · 방향 적중" : " · 방향 틀림" : ""})`, "경제지표"); } }
  writeJ("coinMacroFc", led.slice(-200));
  await solo(a, {room: "news", sys: personaOf(a, "경제지표 최신값과 모델 예측(80% 구간)을 보고 다음 발표가 어떻게 나올지, 시장(금리·주식·코인)에 어떤 의미인지 4~6문장으로 해설한다. 모델 예측의 한계도 짚는다."), user: MA.macroText(dash), train: "아래 경제지표와 예측을 보고 다음 발표 전망과 시장에 주는 의미를 해설해 줘."});
}

/* ============ 스스로 코드 고치기 (AI·개발팀) ============ */
// 앱에서 난 오류를 모아 두었다가, 개발팀이 원인 코드를 읽고 최소한의 수정안을 만든다.
// 수정안은 코드가 문법·보호 파일(실거래·키·안전장치) 검사를 하고, 대표님이 [적용]을 눌러야 반영된다 (문제가 생기면 자동으로 되돌림).
async function selfdevJob(){
  const S = await import("../nuri-ai/selfdev.js");
  const errs = S.recentErrors(5).filter(e => !(S.listPatches() || []).some(p => p.error?.msg === e.msg && ["proposed", "applied", "rejected"].includes(p.status)));
  const a = agentById("dev"), q = agentById("qae") || a;
  if (!errs.length){
    // 고칠 오류가 없으면 테스트 담당이 최근 기록에서 이상한 점을 찾아 과제로 남긴다
    const sys = personaOf(q, "앱 품질 담당으로서 최근 사무실 기록(실패·빈 답·느린 모델)을 보고 고칠 만한 문제 하나를 짧게 말한다. 없으면 '지금은 고칠 오류가 없습니다'라고 한 줄만.");
    const fails = (LOG || []).filter(e => e.kind === "system" && /문제|실패|못했|중단/.test(e.text || "")).slice(-8).map(e => "- " + e.text).join("\n");
    const slow = Object.entries(modelHealth()).filter(([, h]) => (h.slow || 0) + (h.fail || 0) >= 2).map(([m, h]) => `- ${m}: 느림 ${h.slow || 0} · 실패 ${h.fail || 0}`).join("\n");
    if (!fails && !slow){ post({ch: "hq", kind: "work", agent: q.id, icon: "✅", text: "앱 오류 없음 · 모델 상태 양호"}); return; }
    await solo(q, {room: "hq", sys, user: `최근 실패:\n${fails || "(없음)"}\n\n자주 느리거나 실패한 모델(자동으로 덜 쓰게 바뀜):\n${slow || "(없음)"}`, maxTokens: 500});
    return;
  }
  const err = errs[0];
  fire({kind: "busy", agent: a, text: `🛠 ${err.file || "앱"} 오류 원인 찾는 중`});
  const ask = async (sys, user) => { const e = await solo(a, {room: "hq", sys: personaOf(a, sys), user, maxTokens: 1800, temperature: 0.2}); return e.raw || e.text || ""; };
  const p = await S.proposeFix(err, {ask});
  post({ch: "hq", kind: "patch", agent: a.id, file: p.file || err.file, why: p.why || p.check?.msg || "", status: p.status, patchId: p.id});
  // 독립 QA 검토 (my-cc-harness 규칙): 만든 사람과 다른 직원·다른 모델이 100점 기준으로 채점 — 기능 40 · 품질 25 · 군더더기 없음 20 · 사용성·보안 15
  //   85↑ 통과 · 65~84 조건부 · 65↓ 불합격 · 치명적(CRITICAL) 문제 하나면 불합격. 증거(문법 검사 결과) 없이 '완료'라고 하지 않는다.
  if (p.status === "proposed" && hasAI()){
    const diff = (S.patchText?.(p) || "").slice(0, 3500);
    const e2 = await solo(q, {room: "hq", sys: personaOf(q, "독립 QA 검토자: 다른 직원이 만든 코드 수정안을 채점한다. 점검: 경계값·비동기 경쟁·null, XSS·비밀키, 함수 50줄·중첩 4단계 이하, 최소 변경·근본 원인. 마지막 줄을 정확히 '점수: 숫자/100 · 판정: 통과|조건부|불합격 · 치명적: 있음|없음'."),
      user: `파일: ${p.file}\n오류: ${String(err.msg).slice(0, 200)}\n수정 이유: ${p.why || ""}\n자동 검사: ${p.check?.msg || "문법 통과"}\n\n수정안:\n${diff}`, maxTokens: 700});
    const sc = +((String(e2.text).match(/점수\s*[:：]\s*(\d{1,3})/) || [])[1] || 0), crit = /치명적\s*[:：]\s*있음/.test(e2.text);
    const verdict = crit ? "불합격(치명적)" : sc >= 85 ? "통과" : sc >= 65 ? "조건부" : "불합격";
    post({ch: "hq", kind: "work", agent: q.id, icon: verdict === "통과" ? "✅" : "⚠", text: `독립 QA 채점 ${sc}/100 → ${verdict}${/불합격/.test(verdict) ? " — 수정안 자동 반려(대표 승인 목록에 올리지 않음)" : " (적용은 대표님 승인 후)"}`});
    addNote("hq", `수정안 ${p.file}: QA ${sc}점 ${verdict}`, "QA");
    if (/불합격/.test(verdict)){ S.rejectPatch(p.id); p.status = "rejected"; }
  }
  if (p.status === "proposed") addTask({team: "hq", title: `코드 수정안 검토: ${p.file}`, why: `${String(err.msg).slice(0, 80)} (${err.count || 1}번)`, owner: q.name});
  addNote("hq", `${p.file || err.file} 오류 '${String(err.msg).slice(0, 50)}' → 수정안 ${p.status === "proposed" ? "준비됨(대표 승인 대기)" : "실패: " + (p.check?.msg || p.status)}`, "코드");
  fire({kind: "growth"});
}
// 앱 전체의 오류를 모으기 시작 (사무실 모듈은 앱 시작 때 불러와진다)
if (typeof window !== "undefined") import("../nuri-ai/selfdev.js").then(S => S.captureErrors()).catch(() => {});

/* ================================================================
   GH Coin 분석 팀 업무 — 숫자는 코드가 계산하고(표), 팀장이 한 번만 말로 해설한다(AI 호출 1번)
   ================================================================ */
const rot = (k, n) => { const i = +localStorage.getItem(k) || 0; localStorage.setItem(k, String(i + 1)); return i % n; };
const fx = (v, d = 2) => v == null || !Number.isFinite(+v) ? "—" : (+v).toLocaleString("ko-KR", {maximumFractionDigits: Math.abs(+v) >= 1000 ? 0 : Math.abs(+v) >= 1 ? d : 6});
const pc = v => v == null || !Number.isFinite(+v) ? "—" : (v >= 0 ? "+" : "") + (+v).toFixed(2) + "%";
async function kl(sym, tf, n = 600){ return (await candlesFor({market: sym, exchange: "binancef", timeframe: tf}, n)).cs; }
const lastOf = arr => { for (let i = (arr || []).length - 1; i >= 0; i--) if (arr[i] != null && Number.isFinite(+arr[i])) return +arr[i]; return null; };
function table(ch, agent, title, cols, rows, note = ""){ return post({ch, kind: "table", agent, title, cols, rows, note}); }
async function explain(agentId, room, task, facts, train){
  const a = agentById(agentId);
  if (!hasAI()) return {text: ""};   // AI 없어도 판정·표·데모 반영(실제 결정)은 이미 끝났으니 해설만 건너뛴다
  return solo(a, {room, sys: personaOf(a, task + " 3~5문장. 숫자는 아래 표·자료에 있는 것만 쓰고, 확률·가능성으로 말한다(단정 금지)."), user: facts, maxTokens: 700, train});
}
const tableText = (cols, rows) => [cols.join(" | "), ...rows.map(r => r.join(" | "))].join("\n");
let _TVI = null;
async function tvInd(){ if (!_TVI) _TVI = (await import("../nuri-ai/terminal/ind.js")).INDICATORS; return _TVI; }
const toBars = cs => cs.map(b => ({time: Math.floor(b.t / 1000), open: b.o, high: b.h, low: b.l, close: b.c, volume: b.v}));

/* ---- 보조지표 분석팀: 29종 + 차트 지표 → 해석 ---- */
async function indJob(){
  const c = COINS[rot("coinInd", COINS.length)], tf = ["60", "240", "15"][rot("coinIndTf", 3)], Q = await import("../nuri-ai/quant.js");
  const lead = agentById("ind_lead"); fire({kind: "busy", agent: lead, text: `📊 ${c.ko} ${TF_KO[tf]}봉 보조지표 계산 중`});
  const k = await kl(c.sym, tf, 600), s = Q.snapshot(k), I = s.ind || {};
  const g = (n, o = "value") => I[n]?.[o];
  const sig = (v, lo, hi) => v == null ? "—" : v >= hi ? "과열" : v <= lo ? "침체" : "중립";
  const rows = [
    ["RSI(14)", fx(g("rsi"), 1), sig(g("rsi"), 30, 70)], ["스토캐스틱 K/D", `${fx(g("stoch", "k"), 1)} / ${fx(g("stoch", "d"), 1)}`, sig(g("stoch", "k"), 20, 80)],
    ["MACD 히스토그램", fx(g("macd", "hist"), 4), g("macd", "hist") > 0 ? "상승 쪽" : "하락 쪽"], ["볼린저 폭(%)", fx(g("bb", "width"), 2), s.price > g("bb", "upper") ? "상단 돌파" : s.price < g("bb", "lower") ? "하단 이탈" : "밴드 안"],
    ["ADX / +DI / -DI", `${fx(g("adx", "adx"), 1)} / ${fx(g("adx", "plus_di"), 1)} / ${fx(g("adx", "minus_di"), 1)}`, g("adx", "adx") > 25 ? (g("adx", "plus_di") > g("adx", "minus_di") ? "상승 추세 강함" : "하락 추세 강함") : "추세 약함"],
    ["슈퍼트렌드", fx(g("supertrend", "line")), g("supertrend", "trend") > 0 ? "상승" : "하락"], ["EMA20 / SMA20", `${fx(g("ema"))} / ${fx(g("sma"))}`, s.price > g("ema") ? "가격 위" : "가격 아래"],
    ["CCI / MFI", `${fx(g("cci"), 0)} / ${fx(g("mfi"), 0)}`, sig(g("mfi"), 20, 80)], ["일목 전환/기준", `${fx(g("ichimoku", "tenkan"))} / ${fx(g("ichimoku", "kijun"))}`, g("ichimoku", "tenkan") > g("ichimoku", "kijun") ? "전환선 위" : "전환선 아래"],
    ["VWAP", fx(g("vwap")), s.price > g("vwap") ? "VWAP 위" : "VWAP 아래"], ["OBV / CMF", `${fx(g("obv"), 0)} / ${fx(g("cmf"), 3)}`, g("cmf") > 0 ? "자금 유입" : "자금 유출"],
    ["아룬 업/다운", `${fx(g("aroon", "up"), 0)} / ${fx(g("aroon", "down"), 0)}`, g("aroon", "up") > g("aroon", "down") ? "상승 우위" : "하락 우위"],
    ["스퀴즈 모멘텀", fx(g("tv_squeeze"), 4), g("tv_squeeze") > 0 ? "상승 압력" : "하락 압력"], ["웨이브트렌드", fx(g("tv_wavetrend"), 1), sig(g("tv_wavetrend"), -53, 53)],
    ["허스트 지수", fx(g("tv_hurst"), 2), g("tv_hurst") > 0.5 ? "추세 지속형" : "되돌림형"], ["초피니스", fx(g("tv_chop"), 1), g("tv_chop") > 61.8 ? "횡보" : g("tv_chop") < 38.2 ? "추세" : "중간"]
  ];
  const up = rows.filter(r => /상승|위|유입|우위|침체/.test(r[2])).length, dn = rows.filter(r => /하락|아래|유출|과열/.test(r[2])).length;
  table("ind", lead.id, `📊 ${c.ko} ${TF_KO[tf]}봉 보조지표 (현재가 ${fx(s.price)})`, ["지표", "값", "해석"], rows, `상승 쪽 ${up}개 · 하락 쪽 ${dn}개 · 기본 29종 + 차트 지표 136종 계산`);
  await explain(lead.id, "ind", `${c.ko} ${TF_KO[tf]}봉 보조지표 표를 보고, 지표들이 한쪽으로 모이는지 엇갈리는지와 가장 믿을 만한 신호를 해설한다.`, tableText(["지표", "값", "해석"], rows), "아래 코인 보조지표 표를 보고 지표들이 무엇을 말하는지 해설해 줘.");
}

/* ---- 추세 분석팀: 15분·1시간·4시간·일봉 ---- */
async function trendJob(){
  const c = COINS[rot("coinTrend", COINS.length)], Q = await import("../nuri-ai/quant.js"), lead = agentById("trend_lead");
  fire({kind: "busy", agent: lead, text: `📈 ${c.ko} 다중 시간대 추세 판정 중`});
  const rows = [];
  for (const tf of ["15", "60", "240", "D"]){
    try {
      const k = await kl(c.sym, tf, 400), p = k.at(-1).c;
      const e20 = lastOf(Q.computeInd(k, "ema", {length: 20}).value), e50 = lastOf(Q.computeInd(k, "ema", {length: 50}).value), e200 = lastOf(Q.computeInd(k, "ema", {length: 200}).value);
      const adx = Q.computeInd(k, "adx", {length: 14}), st = Q.computeInd(k, "supertrend", {});
      const a = lastOf(adx.adx), dir = lastOf(st.trend);
      const score = (p > e20) + (e20 > e50) + (e50 > (e200 ?? e50)) + (dir > 0) - (p < e20) - (e20 < e50) - (e50 < (e200 ?? e50)) - (dir < 0);
      rows.push([TF_KO[tf], fx(p), `${fx(e20)} / ${fx(e50)} / ${fx(e200)}`, fx(a, 1), dir > 0 ? "상승" : "하락", score >= 3 ? "강한 상승" : score >= 1 ? "약한 상승" : score <= -3 ? "강한 하락" : score <= -1 ? "약한 하락" : "횡보"]);
    } catch(e){ rows.push([TF_KO[tf], "—", "—", "—", "—", "자료 없음"]); }
  }
  const agree = new Set(rows.map(r => r[5].replace(/강한 |약한 /, ""))).size === 1;
  table("trend", lead.id, `📈 ${c.ko} 다중 시간대 추세`, ["봉", "가격", "EMA20/50/200", "ADX", "슈퍼트렌드", "판정"], rows, agree ? "모든 시간대 방향 일치" : "시간대끼리 방향이 엇갈림");
  addNote("trend", `${c.ko}: ${rows.map(r => r[0] + " " + r[5]).join(", ")}`, "추세");
  pubTo(c.sym, "trend", {team: "trend", title: agree ? "모든 시간대 방향 일치" : "시간대끼리 엇갈림", text: rows.map(r => `${r[0]} ${r[5]}`).join(" · "), rows: rows.map(r => [r[0], r[5], `ADX ${r[3]}`, `ST ${r[4]}`])});
  await explain(lead.id, "trend", `${c.ko}의 시간대별 추세 표를 보고, 큰 추세와 작은 추세가 맞는지, 어느 시간대를 기준으로 매매해야 하는지 해설한다.`, tableText(["봉", "가격", "EMA", "ADX", "ST", "판정"], rows), "아래 다중 시간대 추세 표를 보고 추세를 해설해 줘.");
}

/* ---- 지지·저항팀 ---- */
async function levelsOf(c){
  const Q = await import("../nuri-ai/quant.js");
  const k1 = await kl(c.sym, "60", 500), kd = await kl(c.sym, "D", 120), p = k1.at(-1).c;
  const piv = Q.computeInd(kd, "tv_pivots", {}), lv = [];
  [["피봇 P", "value"], ["R1", "p1"], ["R2", "p2"], ["S1", "p3"], ["S2", "p4"]].forEach(([n, o]) => { const v = lastOf(piv[o]); if (v) lv.push({name: "일봉 " + n, price: v}); });
  // 스윙 고저 (1시간봉 좌우 5봉)
  for (let i = k1.length - 6; i >= 5 && lv.length < 14; i--){
    const w = k1.slice(i - 5, i + 6);
    if (k1[i].h === Math.max(...w.map(b => b.h))) lv.push({name: "스윙 고점", price: k1[i].h});
    else if (k1[i].l === Math.min(...w.map(b => b.l))) lv.push({name: "스윙 저점", price: k1[i].l});
  }
  // 매물대(가격대별 거래량 최대 구간)
  const lo = Math.min(...k1.map(b => b.l)), hi = Math.max(...k1.map(b => b.h)), N = 24, hist = Array(N).fill(0);
  for (const b of k1){ const j = Math.min(N - 1, Math.floor(((b.h + b.l) / 2 - lo) / ((hi - lo) / N || 1))); hist[j] += b.v; }
  const jmax = hist.indexOf(Math.max(...hist)); lv.push({name: "매물대 중심(POC)", price: lo + (jmax + 0.5) * (hi - lo) / N});
  // 라운드 넘버
  const mag = Math.pow(10, Math.floor(Math.log10(p)) - 1) * 5; lv.push({name: "라운드 넘버", price: Math.round(p / mag) * mag});
  // 호가 벽
  try { const F = await import("../nuri-ai/flow.js"); const ob = await F.orderBook({symbol: c.sym}); for (const w of [...(ob.data?.bidWalls || []).slice(0, 2).map(x => ({...x, side: "bid"})), ...(ob.data?.askWalls || []).slice(0, 2).map(x => ({...x, side: "ask"}))]) if (w.price) lv.push({name: `호가 벽(${w.side === "bid" || w.side === "buy" ? "매수" : "매도"})`, price: +w.price}); } catch(e){}
  return {p, lv: lv.filter(x => Number.isFinite(x.price)).sort((a, b) => b.price - a.price)};
}
async function srJob(){
  const c = COINS[rot("coinSR", COINS.length)], lead = agentById("sr_lead");
  fire({kind: "busy", agent: lead, text: `📏 ${c.ko} 지지·저항 계산 중`});
  const {p, lv} = await levelsOf(c);
  const rows = lv.slice(0, 14).map(x => [x.price > p ? "저항" : "지지", x.name, fx(x.price), pc((x.price / p - 1) * 100)]);
  pubTo(c.sym, "sr", {team: "sr", title: "지지·저항", text: "피봇 · 스윙 고저 · 매물대 · 라운드 넘버 · 호가 벽", lines: lv.slice(0, 14).map(x => ({price: x.price, label: x.name, color: x.price > p ? "#ff9800" : "#2962ff", style: 3}))});
  table("sr", lead.id, `📏 ${c.ko} 지지·저항 (현재가 ${fx(p)})`, ["구분", "근거", "가격", "현재가 대비"], rows, "피봇 · 스윙 고저 · 매물대 · 라운드 넘버 · 호가 벽");
  await explain(lead.id, "sr", `${c.ko}의 지지·저항 표를 보고 가장 가까운 지지와 저항, 여러 근거가 겹쳐 강한 가격대, 돌파·이탈 시 다음 목표를 해설한다.`, tableText(["구분", "근거", "가격", "대비"], rows), "아래 지지·저항 표를 보고 중요한 가격대를 해설해 줘.");
}

/* ---- 진입 타점팀 ---- */
async function entryJob(){
  const c = COINS[rot("coinEntry", COINS.length)], Q = await import("../nuri-ai/quant.js"), lead = agentById("strat");
  fire({kind: "busy", agent: lead, text: `🎯 ${c.ko} 진입 자리 계산 중`});
  const k = await kl(c.sym, "60", 400), p = k.at(-1).c, atr = lastOf(Q.computeInd(k, "atr", {length: 14}).value), rsi = lastOf(Q.computeInd(k, "rsi", {length: 14}).value);
  const {lv} = await levelsOf(c);
  const sup = lv.filter(x => x.price < p).sort((a, b) => b.price - a.price)[0], res = lv.filter(x => x.price > p).sort((a, b) => a.price - b.price)[0];
  const P = await import("../nuri-ai/paper.js"), book = await P.loadBook();
  const sigs = book.strategies.filter(s => s.status === "active" && s.market === c.sym).map(s => `${s.name}: ${s.lastSignal?.action || "신호 없음"}`).slice(0, 4);
  const longE = sup ? sup.price + atr * 0.2 : p - atr, longSL = longE - atr * 1.5, longTP = res ? res.price : p + atr * 3;
  const shortE = res ? res.price - atr * 0.2 : p + atr, shortSL = shortE + atr * 1.5, shortTP = sup ? sup.price : p - atr * 3;
  const rr = (e, sl, tp) => fx(Math.abs(tp - e) / Math.abs(e - sl), 2);
  // 고정 위험 크기 (nautilus 사이저 · freqtrade Edge 방식): 1,000 USDT 의 1% 위험, 주문당 50 USDT 상한
  const E = await lib("execution"), sz = (e, sl) => { const q = E.fixedRiskQty({equity: 1000, riskPct: 1, entry: e, stop: sl, maxNotional: 50}); return `${fx(q * e)} USDT`; };
  const rows = [["롱 (지지 근처 눌림)", fx(longE), fx(longSL), fx(longTP), rr(longE, longSL, longTP), sz(longE, longSL)], ["숏 (저항 근처 반락)", fx(shortE), fx(shortSL), fx(shortTP), rr(shortE, shortSL, shortTP), sz(shortE, shortSL)]];
  pubTo(c.sym, "entry", {team: "entry", title: "진입 자리 후보 (1시간봉)", text: `ATR ${fx(atr)} · RSI ${fx(rsi, 1)}`, lines: [{price: longE, label: "롱 진입 후보", color: "#26a69a"}, {price: longSL, label: "롱 손절", color: "#f23645", style: 2}, {price: shortE, label: "숏 진입 후보", color: "#ef5350"}, {price: shortSL, label: "숏 손절", color: "#f23645", style: 2}]});
  table("entry", lead.id, `🎯 ${c.ko} 진입 자리 후보 (현재가 ${fx(p)} · ATR ${fx(atr)} · RSI ${fx(rsi, 1)})`, ["시나리오", "진입", "손절", "익절", "손익비", "1% 위험 크기"], rows, (sigs.join(" · ") || "데모 중인 전략 신호 없음") + " · 계산값일 뿐 매매 권유 아님");
  await explain(lead.id, "entry", `${c.ko}의 진입 후보 표(지지·저항·ATR 기반)와 데모 전략 신호를 보고, 지금 바로 들어갈지 기다릴지, 어떤 조건이 맞으면 들어갈지 해설한다.`, tableText(["시나리오", "진입", "손절", "익절", "손익비"], rows) + "\n데모 전략 신호: " + (sigs.join(", ") || "없음"), "아래 진입 자리 계산을 보고 진입 계획을 세워 줘.");
}

/* ---- ⚡ 실시간 진입 (손매매용): 코드 분석 → 에이전트 팀 ↔ 뉴럴 데스크 토론 → 시장가 진입 후보·손절·익절·승률 ----
   분석은 liveentry.js (트리플 배리어 승률·지지저항 군집·호가 벽 유지 추적·다중 시간대 추세·모멘텀·고래·펀딩·팀 판정).
   토론에서 바꾼 손절·익절은 같은 방식으로 다시 시뮬레이션해 기대값이 좋아질 때만 채택. 주문은 하지 않는다(알림·표·차트 선만). */
let rtBusy = false, rtDebateAt = {};
export async function runLiveEntry({coins = COINS, debate = true, by = "auto"} = {}){
  if (rtBusy) return readJ("coinLiveEntry", null); rtBusy = true;
  try { await loadLog(); } catch(e){}
  try {
    const L = await import("./liveentry.js"); let N = null; try { N = await import("./neural.js"); } catch(e){}
    const lead = agentById("strat") || agentById("qa"), list = [];
    const V = k => readJ(k, {}) || {};
    for (const c of coins){
      try {
        const ctx = {verdicts: {ta: V("coinTARating")[c.id], selfAI: V("coinSelfAI")[c.id], ml: V("coinML")[c.id]}};
        try { ctx.whale = N?.whaleFor ? await N.whaleFor(c.sym) : null; } catch(e){}
        try { ctx.libSignal = N?.recentSignal ? N.recentSignal(c.sym) : null; } catch(e){}
        try { ctx.funding = await fundScanOf(c.sym); } catch(e){}
        const r = await L.analyzeCoin(c.sym, ctx); r.ctx = {whale: ctx.whale?.status === "approved" ? ctx.whale : null, funding: ctx.funding ? {key: ctx.funding.key, ko: ctx.funding.ko, avg: ctx.funding.avg} : null};
        list.push(r);
      } catch(e){ list.push({sym: c.sym, ko: c.ko, err: String(e.message || e).slice(0, 60)}); }
    }
    const ok = list.filter(r => r.best).sort((a, b) => L.gradeRank(b.best.grade) - L.gradeRank(a.best.grade) || b.best.exp - a.best.exp);
    // 토론: 유력·보통 후보 상위 2개만 (같은 코인·방향은 10분에 한 번)
    if (debate && hasAI()){
      for (const r of ok.filter(x => ["유력", "보통"].includes(x.best.grade)).slice(0, 2)){
        const b = r.best, key = r.sym + b.side; if (Date.now() - (rtDebateAt[key] || 0) < 10 * 60e3 && by === "auto"){ b.debate = readJ("coinLiveEntry", null)?.list?.find(x => x.sym === r.sym)?.best?.debate || null; continue; }
        rtDebateAt[key] = Date.now();
        const facts = L.setupText(r, b) + `\n근거: ${b.why.join(" · ")}\n주의: ${b.warn.join(" · ") || "없음"}\n손절 근거 레벨: ${b.slLevel ? L.fmtPx(b.slLevel.price) + " (" + b.slLevel.src.join("+") + ")" : "ATR"} · 익절 근거: ${b.tpLevels.map(l => L.fmtPx(l.price) + "(" + l.src.join("+") + ")").join(", ") || "R배수"}`;
        let team = null;
        try {
          const e = await solo(lead, {room: "entry", sys: personaOf(lead, '실시간 진입 토론의 에이전트 팀 대표다. 코드가 계산한 진입 계획을 검토해 찬성/반대하고, 손절·익절이 지지·저항·호가 벽 기준으로 더 나은 자리가 있으면 숫자로 제안한다(없으면 비움). 반드시 JSON 한 줄: {"stance":"찬성"|"반대","sl":숫자|null,"tp1":숫자|null,"tp2":숫자|null,"reason":"한 문장"}'), user: facts, maxTokens: 260, json: true});
          const j = pickJSON(e.raw || e.text) || {}; team = {who: lead.name, stance: /반대/.test(j.stance || "") ? "반대" : /찬성/.test(j.stance || "") ? "찬성" : "기권", reason: String(j.reason || e.text || "").replace(/\s+/g, " ").slice(0, 100), adj: {sl: +j.sl || null, tp1: +j.tp1 || null, tp2: +j.tp2 || null}};
        } catch(e){ team = {who: lead.name, stance: "기권", reason: "응답 실패"}; }
        // 제안된 손절·익절은 같은 시뮬레이션으로 재검증 → 기대값이 나아질 때만 채택 (방향·범위 틀리면 버림)
        const a = team.adj || {}, side = b.side, e0 = b.entry, okSl = a.sl && (e0 - a.sl) * side > 0 && Math.abs(e0 - a.sl) / e0 >= 0.003 && Math.abs(e0 - a.sl) / e0 <= 0.02, okTp = t => t && (t - e0) * side > 0;
        if (okSl || okTp(a.tp1) || okTp(a.tp2)){
          try { const r2 = await L.analyzeCoin(r.sym, {override: {side, sl: okSl ? a.sl : null, tp1: okTp(a.tp1) ? a.tp1 : null, tp2: okTp(a.tp2) ? a.tp2 : null}}); const b2 = r2.sides.find(x => x.side === side);
            if (b2 && b2.exp > b.exp + 0.02 && b2.rr1 >= 1){ team.applied = `제안 채택: 기대값 ${b.exp}R → ${b2.exp}R`; Object.assign(b, {sl: b2.sl, tp1: b2.tp1, tp2: b2.tp2, slPct: b2.slPct, tp1Pct: b2.tp1Pct, tp2Pct: b2.tp2Pct, rr: b2.rr, rr1: b2.rr1, wr: b2.wr, exp: b2.exp, n: b2.n, lev: b2.lev, liq: b2.liq}); }
            else team.applied = `제안 기각: 재검증 기대값 ${b2 ? b2.exp : "?"}R (기존 ${b.exp}R보다 낫지 않음)`; } catch(e){}
        }
        const neural = N?.debateReply ? await N.debateReply(L.setupText(r, b), `${team.stance}: ${team.reason}`).catch(() => null) : null;
        const votes = [team?.stance, neural?.stance].filter(x => x === "찬성" || x === "반대");
        const pro = votes.filter(x => x === "찬성").length, con = votes.filter(x => x === "반대").length;
        b.debate = {team, neural, verdict: pro === 2 ? "합의: 찬성" : con === 2 ? "합의: 반대" : votes.length ? "의견 갈림" : "토론 없음", t: Date.now()};
        if (con === 2) b.grade = b.grade === "유력" ? "보통" : "관망";   // 둘 다 반대하면 한 단계 내림 (찬성은 등급을 올리지 않음 — 등급은 데이터가 정함)
        post({ch: "entry", kind: "work", agent: lead.id, icon: "⚖", text: `⚡ ${r.ko} ${side > 0 ? "롱" : "숏"} 토론 — 팀(${team.who}) ${team.stance}: ${team.reason}${team.applied ? " · " + team.applied : ""} / 뉴럴(${neural?.model || "—"}) ${neural?.stance || "—"}: ${neural?.reason || ""} → ${b.debate.verdict}`});
      }
    }
    const slim = list.map(r => r.err ? r : ({sym: r.sym, ko: r.ko, t: r.t, price: r.price, trend: r.trend, tr: r.tr, adx1h: r.adx1h, rsi15: r.rsi15, ctx: r.ctx,
      book: r.book ? {imb1: r.book.imb1, spreadBps: r.book.spreadBps, bidWalls: r.book.bidWalls.slice(0, 3), askWalls: r.book.askWalls.slice(0, 3), snapshots: r.book.snapshots} : null,
      levels: r.levels.filter(l => Math.abs(l.price / r.price - 1) < 0.06).map(l => ({price: l.price, src: l.src, strength: l.strength})), sides: r.sides, best: r.best}));
    const prev = readJ("coinLiveEntry", null), out = {t: Date.now(), by, list: slim};
    writeJ("coinLiveEntry", out);
    // 표 + 차트 선 + 새 '유력' 알림
    const rows = ok.map(r => { const b = r.best; return [r.ko, b.grade, b.side > 0 ? "롱" : "숏", fx(b.entry), `${fx(b.sl)} (−${b.slPct}%)`, `${fx(b.tp1)} / ${fx(b.tp2)}`, `${b.rr1}R / ${b.rr}R`, `${b.wr}% (${b.n})`, `${b.exp >= 0 ? "+" : ""}${b.exp}R`, `${b.score}`, `≤${b.lev}x`, b.debate?.verdict || "—"]; });
    table("entry", lead.id, `⚡ 실시간 진입 (손매매용 · 시장가 기준 · ${new Date().toLocaleTimeString("ko-KR")})`, ["코인", "등급", "방향", "시장가", "손절", "익절1 / 익절2", "손익비", "익절1 도달률(표본)", "계획 기대값", "합류", "권장 레버", "토론"], rows,
      "등급: 유력 = 워크포워드 검증 매매법 신호가 지금 같은 방향 + 추세 2/3↑ + 손익비 1.5↑ · 보통 = 3개 시간대 추세 일치 + ADX 25↑(2개월 표본외 ≈0R, 우위 미확인) · 그 외 관망 · 스냅샷 지표 조합만으로는 표본외 우위가 없었음 · 15분 유효 · 주문은 직접");
    for (const r of ok.slice(0, 6)){ const b = r.best; if (b.grade === "관망") continue;
      pubTo(r.sym, "rtentry", {team: "entry", title: `⚡ 실시간 진입: ${b.side > 0 ? "롱" : "숏"} [${b.grade}]`, text: `익절1 도달률 ${b.wr}% · 기대값 ${b.exp}R · ${b.why.slice(0, 2).join(" · ")}`,
        lines: [{price: b.entry, label: "시장가 진입", color: "#ffb300"}, {price: b.sl, label: `손절 −${b.slPct}%`, color: "#f23645", style: 2}, {price: b.tp1, label: `익절1 ${b.rr1}R`, color: "#26a69a", style: 2}, {price: b.tp2, label: `익절2 ${b.rr}R`, color: "#26a69a", style: 1},
          ...r.levels.filter(l => Math.abs(l.price / r.price - 1) < 0.03).slice(0, 8).map(l => ({price: l.price, label: l.src.join("+") + ` (${l.strength})`, color: l.price > r.price ? "#ff9800" : "#2962ff", style: 3}))]}); }
    const prevKeys = new Set((prev?.list || []).filter(x => x.best?.grade === "유력").map(x => x.sym + x.best.side));
    for (const r of ok.filter(x => x.best.grade === "유력" && !prevKeys.has(x.sym + x.best.side))){
      const msg = L.setupText(r, r.best); post({ch: "hq", kind: "system", text: "🔔 " + msg}); addNote("entry", msg.slice(0, 120), "실시간진입");
      try { if (typeof Notification !== "undefined" && Notification.permission === "granted") new Notification("⚡ GH Coin 실시간 진입", {body: msg.slice(0, 180)}); } catch(e){}
    }
    fire({kind: "liveentry"});
    return out;
  } finally { rtBusy = false; }
}
// ⚡ 시장가 버튼: 한 코인을 지금 바로 분석 → 에이전트 팀 의견 → 뉴트론(뉴럴 데스크) 반박 → 팀 최종 답 → 시장가 추천 (손매매용, 주문 안 함)
//   롱·숏 둘 다 계산해 '덜 불리한/더 유리한 쪽'을 고르되, 검증된 근거가 없으면 '비권장'이라고 분명히 말한다.
export async function marketEntryNow({sym = "BTCUSDT", by = "user", onStep = () => {}} = {}){
  try { await loadLog(); } catch(e){}
  sym = String(sym).toUpperCase().replace(/^KRW-(\w+)$/, "$1USDT"); if (!/USDT$/.test(sym)) sym += "USDT";
  const L = await import("./liveentry.js"); let N = null; try { N = await import("./neural.js"); } catch(e){}
  const c = COINS.find(x => x.sym === sym) || {sym, ko: sym.replace("USDT", ""), id: sym.replace("USDT", "").toLowerCase()};
  const lead = agentById("strat") || agentById("qa"), V = k => readJ(k, {}) || {};
  onStep("📊 지지·저항 · 매수벽/매도벽 · 15분/1시간/4시간 추세 · 내 차트 지표 · 고래 · 펀딩 분석 중");
  const ctx = {verdicts: {ta: V("coinTARating")[c.id], selfAI: V("coinSelfAI")[c.id], ml: V("coinML")[c.id]}};
  try { ctx.whale = N?.whaleFor ? await N.whaleFor(sym) : null; } catch(e){}
  try { ctx.libSignal = N?.recentSignal ? N.recentSignal(sym) : null; } catch(e){}
  try { ctx.funding = await fundScanOf(sym); } catch(e){}
  const r = await L.analyzeCoin(sym, ctx);
  // 고르기: 검증 매매법 신호(유력)가 있으면 그쪽, 아니면 '유사상황 기대값'과 '내 지표 같은 상태 기대값'의 평균이 높은 쪽
  const ce = x => x.grade === "유력" ? 9 + (x.sig?.mean || 0) : (x.exp + (x.my ? x.my.exp : x.exp)) / 2;
  const [A, B] = [...r.sides].sort((a, b) => ce(b) - ce(a)), pick = A;
  const ok = (pick.grade === "유력" || pick.grade === "보통") && ce(pick) > 0;
  const sideTxt = x => `${x.side > 0 ? "롱" : "숏"}: 시장가 ${L.fmtPx(x.entry)} · 손절 ${L.fmtPx(x.sl)}(−${x.slPct}%) · 익절1 ${L.fmtPx(x.tp1)}(${x.rr1}R) · 익절2 ${L.fmtPx(x.tp2)}(${x.rr}R) · 유사상황 익절1 ${x.wr}%·기대값 ${x.exp}R${x.my ? ` · 내 지표 같은 상태 ${x.my.wr}%·${x.my.exp}R(${x.my.n}표본, ${x.side > 0 ? "롱" : "숏"} 쪽 지표 15분 ${x.my.v15}/${x.my.total}·1시간 ${x.my.v1h}/${x.my.total})` : ""} · 등급 ${x.grade} · ${x.evidence}`;
  const facts = `${c.ko} 현재가 ${L.fmtPx(r.price)} · 추세 15분 ${r.tr["15"]} / 1시간 ${r.tr["60"]} / 4시간 ${r.tr["240"]} · ADX(1h) ${r.adx1h?.toFixed(0)} · RSI(15m) ${r.rsi15?.toFixed(0)}
지지·저항: ${r.levels.filter(l => Math.abs(l.price / r.price - 1) < 0.03).map(l => `${L.fmtPx(l.price)}(${l.src.join("+")}, 강도 ${l.strength})`).join(", ")}
호가: ±1% 불균형 ${r.book ? (r.book.imb1 * 100).toFixed(0) + "%" : "—"} · 매수벽 ${r.book?.bidWalls.filter(w => w.stable).slice(0, 2).map(w => L.fmtPx(w.price) + "×" + (w.xAvg || 0).toFixed(1)).join(", ") || "—"} · 매도벽 ${r.book?.askWalls.filter(w => w.stable).slice(0, 2).map(w => L.fmtPx(w.price) + "×" + (w.xAvg || 0).toFixed(1)).join(", ") || "—"}
내 차트 지표(15분): ${(r.myInd || []).map(x => x.name + (x.d15 > 0 ? "↑" : x.d15 < 0 ? "↓" : "·")).join(" ") || "없음"}
${sideTxt(A)}
${sideTxt(B)}
코드 추천: ${A.side > 0 ? "롱" : "숏"} (${ok ? "진입 가능" : "우위 근거 부족 — 비권장"})`;
  let team = {who: lead.name, stance: "기권", reason: "AI 없음"}, neural = null, final = null;
  if (hasAI()){
    onStep(`⚖ 에이전트 팀(${lead.name}) 의견`);
    try {
      const e = await solo(lead, {room: "entry", sys: personaOf(lead, '손매매 고객이 [시장가] 버튼을 눌렀다. 아래 롱·숏 계산을 보고 지금 시장가로 들어간다면 어느 쪽인지 고르고(또는 관망), 손절·익절이 지지·저항·호가 벽 기준으로 더 나은 자리가 있으면 숫자로 제안한다. 확률로 말하고 과장 금지. 반드시 JSON 한 줄: {"pick":"롱"|"숏"|"관망","sl":숫자|null,"tp1":숫자|null,"tp2":숫자|null,"reason":"한 문장"}'), user: facts, maxTokens: 300, json: true});
      const j = pickJSON(e.raw || e.text) || {};
      team = {who: lead.name, pick: /숏/.test(j.pick || "") ? "숏" : /롱/.test(j.pick || "") ? "롱" : "관망", reason: String(j.reason || e.text || "").replace(/\s+/g, " ").slice(0, 120), adj: {sl: +j.sl || null, tp1: +j.tp1 || null, tp2: +j.tp2 || null}};
      team.stance = team.pick === (A.side > 0 ? "롱" : "숏") ? "찬성" : "반대";
    } catch(e){ team = {who: lead.name, stance: "기권", reason: "응답 실패"}; }
    // 팀이 고른 쪽의 손절·익절 제안 → 같은 시뮬레이션으로 재검증, 기대값이 나아질 때만 채택
    const tgt = team.pick === "롱" ? r.sides.find(x => x.side > 0) : team.pick === "숏" ? r.sides.find(x => x.side < 0) : null, a = team.adj || {};
    if (tgt && (a.sl || a.tp1 || a.tp2)){
      const e0 = tgt.entry, sd = tgt.side, okSl = a.sl && (e0 - a.sl) * sd > 0 && Math.abs(e0 - a.sl) / e0 >= 0.003 && Math.abs(e0 - a.sl) / e0 <= 0.02, okTp = t => t && (t - e0) * sd > 0;
      if (okSl || okTp(a.tp1) || okTp(a.tp2)) try { const r2 = await L.analyzeCoin(sym, {...ctx, override: {side: sd, sl: okSl ? a.sl : null, tp1: okTp(a.tp1) ? a.tp1 : null, tp2: okTp(a.tp2) ? a.tp2 : null}}); const b2 = r2.sides.find(x => x.side === sd);
        if (b2 && b2.exp > tgt.exp + 0.02 && b2.rr1 >= 1){ team.applied = `제안 채택(기대값 ${tgt.exp}R → ${b2.exp}R)`; Object.assign(tgt, {sl: b2.sl, tp1: b2.tp1, tp2: b2.tp2, slPct: b2.slPct, tp1Pct: b2.tp1Pct, tp2Pct: b2.tp2Pct, rr: b2.rr, rr1: b2.rr1, wr: b2.wr, exp: b2.exp, lev: b2.lev, liq: b2.liq}); }
        else team.applied = `제안 기각(재검증 기대값 ${b2 ? b2.exp : "?"}R ≤ 기존 ${tgt.exp}R)`; } catch(e){}
    }
    onStep("🧠 뉴트론(뉴럴 데스크) 반박");
    neural = N?.debateReply ? await N.debateReply(sideTxt(A), `${team.pick || "?"} 선택 — ${team.reason}`).catch(() => null) : null;
    if (neural && neural.stance === "반대" && team.stance !== "기권"){
      onStep(`⚖ ${lead.name} 최종 답변`);
      try { const e = await solo(lead, {room: "entry", sys: personaOf(lead, '뉴트론의 반박을 듣고 내 선택을 유지할지 철회할지 한 문장으로 답한다. 반드시 JSON 한 줄: {"final":"유지"|"철회","reason":"한 문장"}'), user: `내 선택: ${team.pick} — ${team.reason}\n뉴트론 반박: ${neural.reason}\n계산: ${sideTxt(A)}`, maxTokens: 160, json: true});
        const j = pickJSON(e.raw || e.text) || {}; final = {keep: !/철회/.test(j.final || ""), reason: String(j.reason || e.text || "").replace(/\s+/g, " ").slice(0, 100)}; } catch(e){}
    }
  }
  // 결론: 데이터가 정한 등급이 기준. 토론은 '둘 다 반대면 한 단계 낮춤'만 (찬성으로 올리지 않음)
  const votes = [team.stance, neural?.stance].filter(x => x === "찬성" || x === "반대"), con = votes.filter(x => x === "반대").length;
  let grade = pick.grade; if (con === 2 || (final && !final.keep && neural?.stance === "반대")) grade = grade === "유력" ? "보통" : "관망";
  // 2개월·6코인 표본외: 지표·지지저항·호가·내 지표 조합으로 '더 나은 쪽'을 골라도 평균 −0.03~−0.12R → '진입 가능'은 검증 매매법 신호(유력)일 때만
  const go = grade === "유력";
  const decision = {side: pick.side, grade, go, label: go ? `${pick.side > 0 ? "롱" : "숏"} 시장가 진입 가능 [유력 · 검증 매매법 신호]` : `진입 비권장 — 지금은 검증된 우위 없음 · 굳이 들어간다면 ${pick.side > 0 ? "롱" : "숏"} 쪽이 계산상 덜 불리`};
  pick.debate = {team, neural, final, verdict: votes.length === 2 ? (con === 0 ? "합의: 찬성" : con === 2 ? "합의: 반대" : "의견 갈림") : votes.length ? "한쪽만 응답" : "토론 없음", t: Date.now()};
  const res = {t: Date.now(), by, sym, ko: c.ko, price: r.price, tr: r.tr, adx1h: r.adx1h, rsi15: r.rsi15, myInd: r.myInd, book: r.book ? {imb1: r.book.imb1, bidWalls: r.book.bidWalls.slice(0, 3), askWalls: r.book.askWalls.slice(0, 3)} : null,
    levels: r.levels.filter(l => Math.abs(l.price / r.price - 1) < 0.04).map(l => ({price: l.price, src: l.src, strength: l.strength})), sides: r.sides, best: pick, other: B, decision};
  writeJ("coinMarketEntry", res);
  // 실시간 진입 목록에도 이 코인을 갱신 → 뉴럴 데스크 카드·MCP 에 바로 보임
  try { const cur = readJ("coinLiveEntry", null) || {t: Date.now(), list: []}; const i = cur.list.findIndex(x => x.sym === sym), row = {sym, ko: c.ko, t: res.t, price: r.price, trend: r.trend, tr: r.tr, adx1h: r.adx1h, rsi15: r.rsi15, book: res.book, levels: res.levels, sides: r.sides, best: {...pick, grade}, market: decision};
    if (i >= 0) cur.list[i] = row; else cur.list.push(row); cur.t = Date.now(); writeJ("coinLiveEntry", cur); } catch(e){}
  pubTo(sym, "rtentry", {team: "entry", title: `⚡ 시장가: ${decision.label}`, text: `${pick.evidence} · 유사상황 익절1 ${pick.wr}% · 기대값 ${pick.exp}R${pick.my ? ` · 내 지표 같은 상태 ${pick.my.wr}%` : ""}`,
    lines: [{price: pick.entry, label: "시장가", color: "#ffb300"}, {price: pick.sl, label: `손절 −${pick.slPct}%`, color: "#f23645", style: 2}, {price: pick.tp1, label: `익절1 ${pick.rr1}R`, color: "#26a69a", style: 2}, {price: pick.tp2, label: `익절2 ${pick.rr}R`, color: "#26a69a", style: 1},
      ...res.levels.slice(0, 10).map(l => ({price: l.price, label: l.src.join("+") + ` (${l.strength})`, color: l.price > r.price ? "#ff9800" : "#2962ff", style: 3}))]});
  post({ch: "entry", kind: "work", agent: lead.id, icon: "⚡", text: `[시장가] ${c.ko} → ${decision.label} · ${L.setupText(r, pick)} · 토론: 팀 ${team.pick || team.stance}(${team.reason})${team.applied ? " · " + team.applied : ""} / 뉴트론 ${neural?.stance || "—"}(${neural?.reason || ""})${final ? ` / 팀 최종 ${final.keep ? "유지" : "철회"}(${final.reason})` : ""}`});
  fire({kind: "liveentry"});
  return res;
}
async function rtEntryJob(){ await runLiveEntry({debate: hasAI(), by: "office"}); }

/* ---- 익절·손절 관리팀: 데모 포지션 점검 ---- */
async function tpslJob(){
  const P = await import("../nuri-ai/paper.js"), Q = await import("../nuri-ai/quant.js"), book = await P.loadBook(), lead = agentById("risk");
  const open = book.strategies.filter(s => s.status === "active" && s.pos);
  if (!open.length){ post({ch: "tpsl", kind: "work", agent: lead.id, icon: "🛑", text: "열린 데모 포지션 없음 · 새 진입을 기다리는 중"}); return; }
  const rows = [];
  for (const s of open.slice(0, 8)){
    const k = await kl(s.market, s.tf === "D" ? "D" : s.tf, 200).catch(() => null); if (!k) continue;
    const p = k.at(-1).c, atr = lastOf(Q.computeInd(k, "atr", {length: 14}).value), x = s.pos, long = x.side === "long", d = long ? 1 : -1;
    const pnl = d * (p - x.entry) / x.entry * 100 * x.lev, toSL = x.sl ? Math.abs(p - x.sl) / p * 100 : null, toLiq = Math.abs(p - x.liq) / p * 100;
    const trail = long ? Math.max(x.sl || 0, p - atr * 2) : Math.min(x.sl || Infinity, p + atr * 2);
    const tip = toLiq < 3 ? "⚠ 청산가 근접 — 비중 축소" : pnl > 15 ? "본전 이상으로 손절 올리기·일부 익절" : !x.sl ? "손절 없음 — ATR 2배 손절 권장" : "유지";
    rows.push([s.name.slice(0, 18), `${s.mname || s.market} ${long ? "롱" : "숏"} x${x.lev}`, fx(x.entry), fx(p), pc(pnl), toSL == null ? "없음" : pc(-toSL), pc(-toLiq), fx(trail), tip]);
  }
  table("tpsl", lead.id, "🛑 데모 포지션 익절·손절 점검", ["전략", "포지션", "진입", "현재", "수익(레버리지)", "손절까지", "청산까지", "추적손절 제안", "조치"], rows, "데모(모의) 포지션 · 실제 주문 아님");
  await explain(lead.id, "tpsl", "데모 포지션 점검표를 보고 가장 위험한 포지션과 바로 할 조치(손절 이동·일부 익절·비중 축소)를 해설한다.", tableText(["전략", "포지션", "진입", "현재", "수익", "손절까지", "청산까지", "추적손절", "조치"], rows), "아래 포지션 점검표를 보고 손절·익절 관리 조언을 해 줘.");
}

/* ---- 차트·캔들 패턴팀 ---- */
async function patternJob(){
  const c = COINS[rot("coinPat", COINS.length)], tf = ["60", "240"][rot("coinPatTf", 2)], lead = agentById("pat_lead"), IND = await tvInd();
  fire({kind: "busy", agent: lead, text: `🕯 ${c.ko} ${TF_KO[tf]}봉 패턴 찾는 중`});
  const k = await kl(c.sym, tf, 400), bars = toBars(k), rows = [];
  for (const id of ["candles", "chartpat", "structure", "fvg", "td_seq", "sweeps", "rsi_div"]){
    const d = IND[id]; if (!d) continue;
    try {
      const r = d.compute(bars, {...(d.params || {})}, {}) || {};
      for (const pl of r.plots || []) if (pl.type === "signals" && Array.isArray(pl.data)) for (let i = pl.data.length - 1, n = 0; i >= Math.max(0, pl.data.length - 40) && n < 3; i--){ const v = pl.data[i]; if (v && typeof v === "object"){ rows.push([d.name.split(" (")[0], v.text || "", v.dir > 0 ? "상승" : v.dir < 0 ? "하락" : "중립", `${pl.data.length - 1 - i}봉 전`]); n++; } }
    } catch(e){}
  }
  rows.sort((a, b) => parseInt(a[3]) - parseInt(b[3]));
  table("pattern", lead.id, `🕯 ${c.ko} ${TF_KO[tf]}봉 차트·캔들 패턴 (최근 40봉)`, ["종류", "패턴", "방향", "언제"], rows.slice(0, 14), rows.length ? "패턴은 확률일 뿐 — 지지·저항·거래량과 함께 볼 것" : "최근 40봉에 뚜렷한 패턴 없음");
  if (rows.length) await explain(lead.id, "pattern", `${c.ko} ${TF_KO[tf]}봉에서 찾은 패턴 목록을 보고 가장 의미 있는 패턴과 신뢰도, 무효화 조건을 해설한다.`, tableText(["종류", "패턴", "방향", "언제"], rows.slice(0, 14)), "아래 차트·캔들 패턴 목록을 해설해 줘.");
}

/* ---- 코인 상황판팀: 모든 코인 한 판 ---- */
async function situJob(){
  const lead = agentById("situ_lead"); fire({kind: "busy", agent: lead, text: "🖥 코인 상황판 갱신 중"});
  const rows = [];
  let F = null; try { F = await import("../nuri-ai/flow.js"); } catch(e){}
  for (const c of COINS){
    try {
      const r = await TOOLS.market_quote.run({symbols: [c.sym], exchange: "binancef"}), row = JSON.parse(r.text || "[]")[0] || {};
      let fs = null; try { fs = F ? (await F.flowSnapshot({symbol: c.sym})).data : null; } catch(e){}
      const fund = fs?.futures?.funding ?? fs?.funding?.rate ?? fs?.fundingRate, oi = fs?.futures?.oiChangePct ?? fs?.oi?.changePct, score = fs?.score ?? fs?.flowScore;
      rows.push([c.ko, fx(row.현재가), pc(row["변동%"]), fund != null ? (+fund * (Math.abs(fund) < 0.01 ? 100 : 1)).toFixed(4) + "%" : "—", oi != null ? pc(oi) : "—", score != null ? (score > 0 ? "+" : "") + Math.round(score) : "—"]);
    } catch(e){ rows.push([c.ko, "—", "—", "—", "—", "—"]); }
  }
  table("situ", lead.id, "🖥 코인 상황판", ["코인", "가격(USDT)", "24시간", "펀딩비", "미결제약정 변화", "흐름 점수"], rows, "흐름 점수: 호가·고래·체결·선물 종합 (-100 매도 ~ +100 매수 압력)");
  await explain(lead.id, "situ", "코인 상황판을 보고 가장 강한 코인과 약한 코인, 펀딩·미결제약정으로 본 과열·쏠림, 지금 주목할 이상 신호를 해설한다.", tableText(["코인", "가격", "24h", "펀딩", "OI", "흐름"], rows), "아래 코인 상황판을 보고 시장을 해설해 줘.");
}

/* ---- 코인팀 회의: 코인별 팀이 돌아가며 ---- */
async function coinJob(){
  const c = COINS[rot("coinTeam", COINS.length)], lead = TEAM_LEAD[c.id], mem = AGENTS.filter(a => a.team === c.id && !a.lead);
  const pick = [mem[rot("coinTeamA" + c.id, mem.length)], mem[(rot("coinTeamB" + c.id, mem.length) + 4) % mem.length]].filter(Boolean).map(a => a.id);
  await enqueue({topic: `${c.ko}(${c.sym}) 팀 회의: 현물·선물(펀딩·미결제약정)·고래·뉴스·차트를 실제 도구로 확인하고, 오늘 ${c.ko}를 어떻게 대응할지(관망·롱·숏, 자리와 손절) 정해 주세요.`,
    room: c.id, trigger: "auto", title: `${c.ko}-팀-회의`, agents: [...new Set([...pick, lead])]});
}

/* ---- 파이프라인 관문: 데모 → 실거래 후보 (코드 판정, 사람 승인 전에는 절대 실거래 안 함) ---- */
const PROMO_KEY = "coinPromoted";
// 승격 결정표 (jdmn 적중 정책 PRIORITY: 거부 > 검토 > 데모 더 > 승인)
export const PROMO_TABLE = {name: "실거래 후보 승격", hit: "P", default: {act: "데모 더", why: "관문 미통과"},
  inputs: [{key: "gate", label: "코드 관문"}, {key: "p", label: "운일 확률 p"}, {key: "decay", label: "런 차트 악화"}, {key: "trades", label: "거래 수"}],
  outputs: [{key: "act", label: "결정", values: ["거부", "검토", "데모 더", "승인"]}, {key: "why", label: "이유"}],
  rules: [
    {when: ["-", "-", "true", "-"], then: ["거부", "최근 9거래 이상 중앙값 아래로 지속 이동(성과 악화)"]},
    {when: ["true", ">0.2", "-", "-"], then: ["검토", "관문은 통과했지만 운일 확률이 큼"]},
    {when: ["true", "(0.05..0.2]", "-", "<40"], then: ["데모 더", "거래가 더 쌓여야 운인지 가릴 수 있음"]},
    {when: ["false", "-", "-", "-"], then: ["데모 더", "코드 관문 미통과"]},
    {when: ["true", "-", "false", "-"], then: ["승인", "관문 통과 · 운으로 보기 어려움 · 악화 없음"]}
  ]};
export async function pipeline(){
  const P = await import("../nuri-ai/paper.js"), book = await P.loadBook(), log = researchLog();
  let L = null; try { L = await import("../nuri-ai/live.js"); } catch(e){}
  const linked = L?.liveCfg?.().linked || {}, promo = readJ(PROMO_KEY, {});
  const out = {};
  for (const lane of ["std", "custom"]){
    const r = log.filter(x => (x.lane || "std") === lane), st = book.strategies.filter(s => (s.lane || "std") === lane);
    const act = st.filter(s => s.status === "active");
    out[lane] = {dev: r.length, pass: r.filter(x => x.pass).length, fail: r.filter(x => !x.pass).length,
      demo: act.map(s => ({id: s.id, name: s.name, market: s.mname || s.market, tf: s.tf, eq: P.equityOf(s), trades: s.trades.length, days: Math.floor((Date.now() - s.created) / 864e5), cand: !!promo[s.id], live: !!linked[s.id]?.on})),
      cand: act.filter(s => promo[s.id] && !linked[s.id]?.on).length, live: act.filter(s => linked[s.id]?.on).length, retired: st.filter(s => s.status !== "active").length,
      recent: r.slice(-6).reverse()};
  }
  return out;
}
async function promoteJob(){
  const P = await import("../nuri-ai/paper.js"), book = await P.loadBook();
  let L = null; try { L = await import("../nuri-ai/live.js"); } catch(e){}
  if (!L?.gateFor){ post({ch: "demo", kind: "system", text: "실거래 모듈을 불러오지 못해 관문 심사를 건너뜁니다"}); return; }
  const promo = readJ(PROMO_KEY, {}), rows = [], D = await lib("dmn"), RB = await lib("robust"), RC = await lib("runchart"), JL = await lib("journal");
  const chain = (() => { try { return JL.verify(); } catch(e){ return {ok: true}; } })();
  if (!chain.ok) post({ch: "demo", kind: "system", text: `⛔ 감사 기록 해시 사슬이 ${chain.at}번째 행에서 끊김 — 기록을 믿을 수 없어 이번 승격 심사를 모두 보류`});
  for (const s of book.strategies.filter(x => x.status === "active")){
    const g0 = L.gateFor(s), lane = LANES[s.lane] || LANES.std;
    // reladomo(이중 시간 감사) 대조: 데모 시작 때 기록된 전략 해시 ≠ 지금 전략 → 데모 성적이 지금 전략의 성적이 아님 → 승격 불가
    const recs = (() => { try { return JL.history("strategy", s.id).filter(r => r.data?.phash); } catch(e){ return []; } })(), ph = specHash(s.spec);
    if (!recs.length) journal("record", "strategy", s.id, {phash: ph}, "trader", "승격 심사 기준 해시");
    const tampered = recs.length && recs.at(-1).data.phash !== ph;
    const g = (!chain.ok || tampered) ? {...g0, eligible: false, checks: [...(g0.checks || []), {name: !chain.ok ? "감사 사슬" : "전략 변경됨(감사 기록 불일치)", ok: false}]} : g0;
    const fails = (g.checks || []).filter(c => !c.ok).map(c => c.name);
    // 결정표(jdmn PRIORITY): 코드 관문 + 런 차트 악화 + 순열 검정 p — 하나라도 막히면 승격하지 않음 (관문보다 더 엄격하게만 작동)
    const pnl = s.trades.map(t => +t.pnl || 0), pt = RB.permutationTest(pnl), dn = RC.runChart(s.trades.map(t => +t.roe || 0), {direction: "below"});
    const dm = D.evaluate(PROMO_TABLE, {gate: g.eligible, p: pt.p ?? 1, decay: !!(dn.last && dn.last.to >= s.trades.length - 9), trades: s.trades.length});
    rows.push([lane.label, s.name.slice(0, 20), s.mname || s.market, `${s.trades.length}회`, `${Math.floor((Date.now() - s.created) / 864e5)}일`, g.eligible ? "✅ 통과" : "⏳ " + fails.slice(0, 2).join(", "), `${dm.result.act} (규칙 ${dm.matched.map(m => m.row).join(",") || "기본"})`]);
    if (g.eligible && dm.result.act === "승인" && !promo[s.id]){
      promo[s.id] = Date.now();
      post({ch: lane.live, kind: "promo", agent: TEAM_LEAD[lane.live], sid: s.id, name: s.name, market: s.mname || s.market, lane: s.lane || "std",
        text: `🎓 실거래 후보 승격: ${s.name} (${s.mname || s.market}) — 데모 관문(14일 · 20거래 · 손익비 1.2 · 수익 + · 낙폭 25% 미만) 통과. 대표님이 [실거래] 화면에서 연결해야만 실거래합니다.`});
      addNote(lane.live, `${s.name} 실거래 후보 (데모 관문 통과)`, "관문");
    }
  }
  writeJ(PROMO_KEY, promo);
  table("demo", "trader", "🎓 데모 → 실거래 관문 심사 (코드 판정 + 결정표)", ["라인", "전략", "코인", "거래", "기간", "관문", "결정표"], rows, rows.length ? "관문: 14일 이상 · 거래 20회 이상 · 손익비 1.2 이상 · 수익 + · 최대 낙폭 25% 미만" : "데모 중인 전략 없음");
  fire({kind: "pipeline"});
}
/* ---- 실거래 데스크: 상태만 보고 (주문은 live.js 가 한도·승인 안에서만) ---- */
async function liveDeskJob(){
  let L = null; try { L = await import("../nuri-ai/live.js"); } catch(e){}
  const lead = agentById("live_lead");
  if (!L?.status){ post({ch: "live", kind: "system", text: "실거래 모듈 없음"}); return; }
  const st = await Promise.resolve(L.status()).catch(() => null), cfg = L.liveCfg?.() || {};
  const linked = Object.entries(cfg.linked || {}).filter(([, v]) => v?.on).length;
  try { const E = await lib("execution"), dp = L.dayPnl?.(), st2 = E.tradingState({halted: L.isHalted?.(), dayLoss: Math.max(0, -(dp?.usdt || 0)), dayLossCap: cfg.limits?.dailyLoss ?? 20});
    const plan = E.twapPlan({qty: 50, horizonSec: 300, intervalSec: 60});
    post({ch: "live", kind: "work", agent: lead.id, icon: "🛡", text: `거래 상태(nautilus 방식): ${E.STATES[st2]} · 50 USDT를 5분 TWAP 으로 나누면 ${plan.map(x => x.qty.toFixed(0)).join("/")} USDT (계획일 뿐, 주문은 live.js 한도·승인)`}); } catch(e){}
  post({ch: "live", kind: "work", agent: lead.id, icon: "🔐", text: `실거래 ${cfg.enabled ? "켜짐" : "꺼짐"} · ${cfg.env === "mainnet" ? "실거래(메인넷)" : "테스트넷"} · ${cfg.mode === "auto" ? "자동" : "승인"} 모드 · 연결 전략 ${linked}개${st?.todayPnl != null ? ` · 오늘 실현 ${fx(st.todayPnl)} USDT` : ""}`});
  fire({kind: "pipeline"});
}

/* ================================================================
   실시간 종합 지표 타점팀 — 차트 터미널의 모든 보조지표(136종)를 5분·15분·1시간·4시간에 계산해 조합
   ① 실시간 루프(기본 60초, AI 없음): 6개 코인 타점판 갱신 · 타점이 새로 잡히면 기록장에 남기고 카드로 알림
   ② 타점 기록장: 잡은 타점이 익절1·손절·24시간 만료 중 무엇이 됐는지 코드가 채점 (적중률 = 이 팀의 성적표)
   ③ 업무 순환(combo): 코인 하나를 골라 지표 묶음별 표 + 시간대표 + 타점표를 올리고 팀장이 한 번 해설
   실제 주문은 하지 않는다. 실거래는 기존 관문(데모 → 대표 승인)만 쓴다.
   ================================================================ */
const CB_CALLS = "coinComboCalls";
const CB = {coins: {}, t: 0, running: false, err: ""};
const cbCache = {};      // `${sym}:${tf}` → {at, cs, res}
const CB_TTL = {"5": 0, "15": 50e3, "60": 170e3, "240": 590e3};
let cbTimer = 0, cbLastTalk = {};
const comboCfgOn = () => officeCfg().combo !== false;
export const comboCalls = () => readJ(CB_CALLS, []);
export function comboBoard(){ return {...CB, calls: comboCalls()}; }
async function cbTF(c, tf, force){
  const key = c.sym + ":" + tf, hit = cbCache[key], C = await import("./combo.js");
  if (hit && !force && Date.now() - hit.at < CB_TTL[tf]) return hit;
  const cs = await kl(c.sym, tf, 500);
  const res = await C.analyzeTF(cs);
  return (cbCache[key] = {at: Date.now(), cs, res});
}
// 코인 하나 실시간 분석 → 타점판 한 줄
export async function comboScan(c, force){
  const C = await import("./combo.js"), tf = {}, raw = {};
  for (const k of C.TF_LIST){ try { const h = await cbTF(c, k, force); tf[k] = h.res; raw[k] = h.cs; } catch(e){ /* 그 시간대만 빠짐 */ } }
  if (!tf["15"] && !tf["5"]) throw new Error(`${c.ko} 시세를 받지 못했습니다`);
  // 동기화 편차: 여러 시간대가 '같은 시점'의 봉으로 계산됐는지. 마지막 봉 시각 퍼짐이 가장 작은 봉 주기의 10%를 넘으면 경고.
  const TF_SEC_MS = {"1": 60e3, "5": 300e3, "15": 900e3, "60": 3600e3, "240": 144e5, "D": 864e5};
  const stamps = Object.entries(raw).map(([k, cs]) => cs?.at(-1)?.t).filter(Boolean);
  let sync = null;
  if (stamps.length >= 2){
    const spread = Math.max(...stamps) - Math.min(...stamps), minBar = Math.min(...Object.keys(raw).map(k => TF_SEC_MS[k] || 36e5));
    sync = {bars: stamps.length, spread_ms: spread, max_lag_ms: Math.max(...Object.values(raw).map(cs => Date.now() - (cs?.at(-1)?.t || Date.now()))), warn: spread > minBar * 0.1};
  }
  const plan = C.planOf(tf), prev = CB.coins[c.id];
  let tv = {}; try { const T = await lib("ta_rating"); for (const k of ["60", "240"]) if (raw[k]){ const r = T.rating(raw[k]); if (r) tv[k] = {all: r.all, label: r.label, ma: r.ma, osc: r.osc}; } } catch(e){}
  try { const TR0 = readJ("coinTARating", {}); TR0[c.id] = {all: tv["60"]?.all ?? null, label: tv["60"]?.label || "", all4: tv["240"]?.all ?? null, t: Date.now()}; writeJ("coinTARating", TR0); } catch(e){}   // tradingview-mcp 종합평점 → 진입 관문
  const row = {id: c.id, ko: c.ko, sym: c.sym, t: Date.now(), plan, sync, tf: Object.fromEntries(Object.entries(tf).map(([k, r]) => [k, {score: r.score, up: r.up, dn: r.dn, flat: r.flat, total: r.total, ob: r.ob, os: r.os, oscN: r.oscN, regime: r.regime.label, fresh: r.fresh.slice(0, 4), groups: r.groups}])), n: C.comboIds().length, tv};
  CB.coins[c.id] = row;
  { const lines = [], K = {long: "롱 타점", short: "숏 타점", longWait: "롱 대기", shortWait: "숏 대기", wait: "관망"};
    if (plan.entry) lines.push({price: plan.entry, label: `${plan.state.includes("Wait") ? "대기 진입" : "진입"}`, color: plan.side > 0 ? "#26a69a" : "#ef5350", style: 0}, {price: plan.sl, label: "손절", color: "#f23645", style: 2}, {price: plan.tp1, label: "익절1 (1.5R)", color: "#089981", style: 2}, {price: plan.tp2, label: "익절2", color: "#089981", style: 1});
    if (plan.sup) lines.push({price: plan.sup.price, label: `지지 (${plan.sup.names.slice(0, 2).join("·")})`, color: "#2962ff", style: 3});
    if (plan.res) lines.push({price: plan.res.price, label: `저항 (${plan.res.names.slice(0, 2).join("·")})`, color: "#ff9800", style: 3});
    pubTo(c.sym, "combo", {team: "combo", title: `${K[plan.state]} · 확신 ${plan.conf}%`, text: `${plan.why} · 큰 추세 ${Math.round(plan.big * 100)} · 타이밍 ${Math.round(plan.small * 100)}${row.sync?.warn ? " · ⚠ 시간대 봉 비동기(편차 " + (row.sync.spread_ms / 1000).toFixed(0) + "초)" : ""}`, lines,
      rows: Object.entries(row.tf).map(([k, r]) => [{"5": "5분", "15": "15분", "60": "1시간", "240": "4시간"}[k], Math.round(r.score * 100), `${r.up}▲ ${r.dn}▼`, r.regime, row.tv?.[k]?.label || ""])}); }
  // 기록장 채점 (5분봉으로)
  const calls = comboCalls(); let changed = false;
  const cs5 = raw["5"] || raw["15"];
  for (let i = 0; i < calls.length; i++) if (!calls[i].result && calls[i].coin === c.id && cs5){ const g = C.gradeCall(calls[i], cs5); if (g.result){ calls[i] = g; changed = true; post({ch: "combo", kind: "work", agent: "combo_9", icon: g.result === "win" ? "✅" : g.result === "loss" ? "❌" : "⌛", text: `타점 채점: ${c.ko} ${g.side > 0 ? "롱" : "숏"} ${fx(g.entry)} → ${g.result === "win" ? "익절1 도달 (+1.5R)" : g.result === "loss" ? "손절 (-1R)" : `24시간 만료 (${g.r}R)`}`}); } }
  // 새 타점: 관망·대기 → 롱/숏 타점으로 바뀐 순간만 기록 (같은 방향 열린 타점이 있으면 중복 기록 안 함)
  const isCall = s => s === "long" || s === "short";
  if (isCall(plan.state) && (!prev || prev.plan.state !== plan.state) && !calls.some(x => x.coin === c.id && !x.result && x.side === plan.side)){
    const call = {id: uid(), coin: c.id, ko: c.ko, side: plan.side, entry: plan.entry, sl: plan.sl, tp1: plan.tp1, tp2: plan.tp2, conf: plan.conf, why: plan.why, big: plan.big, small: plan.small, t: (raw["5"] || raw["15"]).at(-1).t};
    // 같은 코인의 반대 방향 열린 타점은 '반대 신호'로 그 자리에서 마감
    for (let i = 0; i < calls.length; i++) if (calls[i].coin === c.id && !calls[i].result && calls[i].side === -plan.side){ const x = calls[i]; calls[i] = {...x, result: "flip", r: Math.round(x.side * (plan.price - x.entry) / Math.abs(x.entry - x.sl) * 100) / 100, end: call.t}; }
    calls.push(call); changed = true;
    onNewCall(c, row, call).catch(e => console.warn(e));
  }
  if (changed) writeJ(CB_CALLS, calls.slice(-300));
  if (changed || !prev) pubTo(c.sym, "calls", {team: "combo", title: "타점 기록장", text: "잡힌 타점과 채점 결과", markers: calls.filter(x => x.coin === c.id).slice(-40).map(x => ({t: x.t, dir: x.side, text: `${x.side > 0 ? "롱" : "숏"}${x.result ? (x.result === "win" ? " ✅" : x.result === "loss" ? " ❌" : " ⌛") : ""}`, color: x.side > 0 ? "#26a69a" : "#ef5350"}))});
  return row;
}
async function onNewCall(c, row, call){
  const C = await import("./combo.js"), p = row.plan;
  table("combo", "combo_lead", `${C.STATE_KO[p.state]} · ${c.ko} (현재가 ${fx(p.price)} · 확신 ${p.conf}%)`, ["시간대", "점수", "판정", "상승/하락/중립", "장세", "새 신호"],
    C.TF_LIST.filter(k => row.tf[k]).map(k => [C.TF_NAME[k], C.pct(row.tf[k].score), C.verdict(row.tf[k].score), `${row.tf[k].up}/${row.tf[k].dn}/${row.tf[k].flat}`, row.tf[k].regime, row.tf[k].fresh.map(f => f.name + (f.dir > 0 ? "▲" : "▼")).join(", ") || "—"]),
    `진입 ${fx(call.entry)} · 손절 ${fx(call.sl)} · 익절1 ${fx(call.tp1)} · 익절2 ${fx(call.tp2)} · 손익비 ${fx(p.rr, 2)} — ${p.why} · 기록장에 남겨 자동 채점 · 매매 권유 아님`);
  addNote("combo", `${c.ko} ${call.side > 0 ? "롱" : "숏"} 타점 ${fx(call.entry)} (손절 ${fx(call.sl)}, 확신 ${call.conf}%)`, "타점");
  fire({kind: "combo-call", call});
  // 팀장 해설은 AI 가 있을 때만, 코인당 20분에 한 번
  if (!hasAI() || officePaused() || Date.now() - (cbLastTalk[c.id] || 0) < 20 * 60e3 || usage().calls >= officeCfg().callMax) return;
  cbLastTalk[c.id] = Date.now();
  await explain("combo_lead", "combo", `${c.ko}에서 방금 잡힌 ${call.side > 0 ? "롱" : "숏"} 타점을 해설한다: 왜 지금인지(큰 추세·작은 봉 타이밍·새 신호), 손절 자리의 근거, 무효가 되는 조건.`, comboFacts(row), "아래 실시간 종합 지표 결과를 보고 타점을 해설해 줘.");
}
function comboFacts(row){
  const p = row.plan, T = {"5": "5분", "15": "15분", "60": "1시간", "240": "4시간"};
  const lines = Object.entries(row.tf).map(([k, r]) => `${T[k]}: 점수 ${Math.round(r.score * 100)} (상승 ${r.up}·하락 ${r.dn}·중립 ${r.flat}) · ${r.regime} · 과매수 ${r.ob}/${r.oscN} 과매도 ${r.os}/${r.oscN}${r.fresh.length ? " · 새 신호 " + r.fresh.map(f => f.tag.replace(/^.*새 신호 /, f.name + " ")).join(", ") : ""}`);
  return `${row.ko} 현재가 ${fx(p.price)} · ATR(15분) ${fx(p.atr)} · 계산한 지표 ${row.n}종\n${lines.join("\n")}\n큰 추세 점수 ${Math.round(p.big * 100)} · 타이밍 점수 ${Math.round(p.small * 100)} · 판정 ${p.state} (${p.why})\n` +
    (p.entry ? `진입 ${fx(p.entry)} · 손절 ${fx(p.sl)} · 익절1 ${fx(p.tp1)} · 익절2 ${fx(p.tp2)} · 손익비 ${fx(p.rr, 2)}\n` : "") +
    (row.tv && Object.keys(row.tv).length ? `트레이딩뷰식 요약: ${Object.entries(row.tv).map(([k, v]) => `${T[k]} ${v.label}(${v.all.toFixed(2)}, 이평 ${v.ma.toFixed(2)} · 오실레이터 ${v.osc.toFixed(2)})`).join(" · ")}\n` : "") +
    `가까운 지지 ${p.sup ? fx(p.sup.price) + " (" + p.sup.names.join("·") + ")" : "—"} · 가까운 저항 ${p.res ? fx(p.res.price) + " (" + p.res.names.join("·") + ")" : "—"}`;
}
// 회의·대표 질문 때 붙는 한 줄 요약
export function comboText(){
  const rows = Object.values(CB.coins); if (!rows.length) return "";
  const K = {long: "롱 타점", short: "숏 타점", longWait: "롱 대기", shortWait: "숏 대기", wait: "관망"};
  const st = (() => { const done = comboCalls().filter(x => x.result), w = done.filter(x => (x.r || 0) > 0).length; return done.length ? ` · 기록장 적중 ${w}/${done.length}` : ""; })();
  return `[실시간 종합 지표 타점판 · ${new Date(CB.t).toLocaleTimeString("ko-KR", {hour: "2-digit", minute: "2-digit"})} 기준${st}]\n` + rows.map(r => `- ${r.ko} ${fx(r.plan.price)}: ${K[r.plan.state]} (큰 추세 ${Math.round(r.plan.big * 100)}, 타이밍 ${Math.round(r.plan.small * 100)}${r.plan.entry ? `, 진입 ${fx(r.plan.entry)} 손절 ${fx(r.plan.sl)} 익절 ${fx(r.plan.tp1)}` : ""})`).join("\n");
}
export async function comboTick(force){
  if (CB.running || (!force && !comboCfgOn())) return;
  CB.running = true; fire({kind: "combo"});
  try {
    for (const c of COINS){ try { await comboScan(c); } catch(e){ CB.err = String(e.message || e).slice(0, 100); } }
    CB.t = Date.now(); if (Object.keys(CB.coins).length) CB.err = "";
  } finally { CB.running = false; fire({kind: "combo"}); }
}
export function startCombo(){
  if (cbTimer) return;
  const sec = Math.max(30, +officeCfg().comboSec || 60);
  cbTimer = setInterval(() => comboTick().catch(e => console.warn(e)), sec * 1e3);
  setTimeout(() => comboTick().catch(e => console.warn(e)), 2500);
}
export function stopCombo(){ clearInterval(cbTimer); cbTimer = 0; }
// 업무 순환·말로 시킨 일: 코인 하나를 깊게 (지표 묶음별 표 + 시간대표 + 타점) → 팀장 해설
async function comboJob(){
  const C = await import("./combo.js"), lead = agentById("combo_lead");
  const named = userNote && COINS.find(c => new RegExp(`${c.ko}|${c.sym.replace("USDT", "")}`, "i").test(userNote));
  const c = named || COINS[rot("coinCombo", COINS.length)];
  fire({kind: "busy", agent: lead, text: `⚡ ${c.ko} 보조지표 ${C.comboIds().length}종 × 4개 시간대 계산 중`});
  const row = await comboScan(c, true), p = row.plan;
  const G = {};
  for (const r of Object.values(row.tf)) for (const [g, v] of Object.entries(r.groups)){ const x = G[g] ||= {up: 0, dn: 0, flat: 0}; x.up += v.up; x.dn += v.dn; x.flat += v.flat; }
  const gRows = Object.entries(G).map(([g, v]) => [g, String(v.up), String(v.dn), String(v.flat), v.up > v.dn * 1.5 ? "상승 우세" : v.dn > v.up * 1.5 ? "하락 우세" : "엇갈림"]);
  const tRows = C.TF_LIST.filter(k => row.tf[k]).map(k => { const r = row.tf[k]; return [C.TF_NAME[k], C.pct(r.score), C.verdict(r.score), `${r.up}/${r.dn}/${r.flat}`, r.regime, `${r.ob}/${r.os}`, r.fresh.map(f => f.name + (f.dir > 0 ? "▲" : "▼")).join(", ") || "—"]; });
  table("combo", lead.id, `⚡ ${c.ko} 종합 지표 — 지표 묶음별 (4개 시간대 합계)`, ["묶음", "상승", "하락", "중립", "판정"], gRows, `차트 터미널 지표 ${row.n}종 중 장세 판별용(ATR·초피니스·허스트 등)은 필터로, 레벨형(피봇·피보나치 등)은 지지·저항으로 사용`);
  const syncNote = row.sync ? ` · 동기화 ${(row.sync.spread_ms / 1000).toFixed(0)}초 편차·지연 ${(row.sync.max_lag_ms / 1000).toFixed(0)}초${row.sync.warn ? " ⚠ 시간대 봉 어긋남(같은 시점 아님) — 타점 신뢰도 낮춤" : " ✓ 같은 시점"}` : "";
  table("combo", lead.id, `⚡ ${c.ko} 시간대별 점수 (현재가 ${fx(p.price)})`, ["시간대", "점수", "판정", "상승/하락/중립", "장세", "과매수/과매도", "새 신호"], tRows, `큰 추세(4시간 60% + 1시간 40%) ${Math.round(p.big * 100)} · 타이밍(15분 60% + 5분 40%) ${Math.round(p.small * 100)}${syncNote}`);
  const st = C.callStats(comboCalls().filter(x => x.coin === c.id));
  table("combo", lead.id, `🎯 ${c.ko} 타점: ${C.STATE_KO[p.state]} (확신 ${p.conf}%)`, ["항목", "값"], [["판단 이유", p.why], ["진입", fx(p.entry)], ["손절", fx(p.sl)], ["익절1 (1.5R)", fx(p.tp1)], ["익절2", fx(p.tp2)], ["손익비", fx(p.rr, 2)],
    ["가까운 지지", p.sup ? `${fx(p.sup.price)} (${p.sup.names.join("·")})` : "—"], ["가까운 저항", p.res ? `${fx(p.res.price)} (${p.res.names.join("·")})` : "—"], ["이 코인 기록장", st.done ? `적중 ${st.win}/${st.done} (${Math.round(st.rate * 100)}%) · 누적 ${st.sumR}R` : `채점된 타점 없음 (열린 ${st.open})`]],
    "계산값일 뿐 매매 권유 아님 · 실제 주문 없음");
  addNote("combo", `${c.ko}: 큰 추세 ${Math.round(p.big * 100)} · 타이밍 ${Math.round(p.small * 100)} → ${C.STATE_KO[p.state]}`, "종합");
  await explain(lead.id, "combo", `${c.ko}의 모든 보조지표 종합 결과를 보고 ① 큰 추세 ② 지금 타이밍 ③ 타점(들어갈지·기다릴지·어디서) ④ 무효 조건을 해설한다. 지표들이 엇갈리면 엇갈린다고 말한다.`, comboFacts(row) + "\n지표 묶음별: " + gRows.map(r => `${r[0]} 상승${r[1]}/하락${r[2]}`).join(", "), "아래 모든 보조지표를 조합한 결과로 추세와 타점을 판단해 줘.");
}

/* ================================================================
   오픈소스 분석으로 들여온 기능 — 부서별 업무 (출처는 각 lib/*.js 머리말, '📚 도입 기술' 탭에 정리)
   ================================================================ */
const lib = name => import(`./lib/${name}.js`);
// 분석 결과를 차트 터미널로 (nuri-ai/analysisbus.js — 터미널 '🤖 AI 팀' 탭이 선·표시로 그림)
const pubTo = (sym, section, data) => import("../nuri-ai/analysisbus.js").then(B => B.publish(sym, section, data)).catch(() => {});
const toPrice = v => { if (v == null) return null; const s = String(v).trim(); if (/%|~|–|-\s*\d|N\/?A|없음/i.test(s.replace(/^-/, ""))) return null; const x = Number(s.replace(/[,$\s]|USDT/g, "")); return Number.isFinite(x) && x > 0 ? x : null; };
// 장부·결정을 이중 시간 감사 기록에 (reladomo 방식)
const journal = (kind, entity, id, data, who = "", why = "") => lib("journal").then(J => kind === "audit" ? J.audit(entity, id, data, {who, why}) : J.record(entity, id, data, {who, why})).catch(() => null);

/* ---- 🏛 투자위원회 (TradingAgents 흐름) ----
   애널리스트 4명 보고(코드 자료) → 강세·약세 토론(1라운드 = 발언 2번) → 리서치 매니저 5단계 등급 → 트레이더 매수·관망·매도 + 진입·손절(절대 가격)
   → 공격·보수·중립 리스크 토론(1라운드 = 발언 3번) → 위원장 최종 5단계 등급. 해석 못 하면 REVIEW(절대 거래 안 함).
   5봉(기본 4시간봉 × 5 = 20시간) 뒤 결과를 채점(비트코인 대비 초과수익)하고 위원장이 2~4문장 교훈을 남긴다. 교훈은 '최종 결정자'에게만 준다(같은 코인 5개 + 다른 코인 3개, 결정 시점 이전에 확정된 것만). */
const IC_KEY = "coinICLedger", RATINGS = ["매수", "비중확대", "관망", "비중축소", "매도"], RATING_EN = {buy: "매수", overweight: "비중확대", hold: "관망", underweight: "비중축소", sell: "매도"};
function parseRating(t){
  const s = String(t || ""), m = s.match(/(?:최종\s*)?(?:등급|결정|판단|rating)\s*[:：]\s*\**\s*(매수|비중\s*확대|관망|비중\s*축소|매도|buy|overweight|hold|underweight|sell)/i);
  if (!m) return "REVIEW";
  const k = m[1].replace(/\s/g, "").toLowerCase(); return RATING_EN[k] || k;
}
export const icLedger = () => readJ(IC_KEY, []);
async function icSettle(){
  const L = icLedger(), now = Date.now(); let changed = false;
  for (const d of L.filter(x => x.status === "pending" && now >= x.due)){
    try {
      const c = COINS.find(x => x.id === d.coin), k = await kl(c.sym, "240", 60), kb = d.coin === "btc" ? k : await kl("BTCUSDT", "240", 60);
      const at = arr => arr.filter(b => b.t <= d.due).at(-1)?.c, p1 = at(k), b0 = d.btc0, b1 = at(kb); if (!p1) continue;
      const raw = (p1 / d.p0 - 1) * 100, alpha = raw - (b0 && b1 ? (b1 / b0 - 1) * 100 : 0), dir = {매수: 1, 비중확대: 0.5, 관망: 0, 비중축소: -0.5, 매도: -1}[d.rating] ?? 0;
      d.status = "resolved"; d.resolved = now; d.raw = +raw.toFixed(2); d.alpha = +alpha.toFixed(2); d.hit = dir === 0 ? Math.abs(raw) < 2 : Math.sign(raw) === Math.sign(dir); changed = true;
      const lead = agentById("ic_lead");
      if (hasAI() && !officePaused()){
        const e = await solo(lead, {room: "ic", sys: personaOf(lead, "지난 위원회 결정의 결과를 2~4문장으로 복기한다: 초과수익(알파) 숫자를 인용하고, 어떤 논리가 맞았고 틀렸는지, 다음에 쓸 교훈 하나를 마지막 문장에 '교훈:'으로 쓴다."), user: `코인 ${d.ko} · 결정 ${d.rating} (${new Date(d.t).toLocaleString("ko-KR")}) · 결정가 ${fx(d.p0)} → ${fx(p1)} · 수익 ${pc(raw)} · 비트코인 대비 알파 ${pc(alpha)}\n결정 근거: ${clip(d.why, 600)}`, maxTokens: 400, train: "아래 투자 결정과 실제 결과를 보고 복기와 교훈을 써 줘."});
        d.lesson = (String(e.text).match(/교훈\s*[:：]\s*(.+)/) || [])[1]?.slice(0, 200) || clip(e.text, 200);
      } else d.lesson = `${d.rating} → 알파 ${pc(alpha)} (${d.hit ? "적중" : "빗나감"})`;
      journal("audit", "ic-outcome", d.id, {rating: d.rating, raw: d.raw, alpha: d.alpha, hit: d.hit}, "ic_lead", "결과 채점");
      addNote("ic", `${d.ko} ${d.rating} → 알파 ${pc(alpha)} · ${d.lesson}`, "복기");
    } catch(e){}
  }
  if (changed) writeJ(IC_KEY, L.slice(-200));
}
// TradingAgents 식 메모리 검색: 지금 '상황(situation)'과 비슷한 과거 복기를 우선해 꺼낸다 (토큰 겹침 + 같은 코인·최근 보정).
// situation 이 없으면 기존처럼 최근 것 위주로.
function icLessons(coin, asOf = Date.now(), situation = ""){
  const done = icLedger().filter(d => d.status === "resolved" && d.resolved <= asOf && d.lesson);
  if (!done.length) return "";
  const tok = s => (String(s).toLowerCase().match(/[a-z0-9]{2,}|[가-힣]{2,}/g) || []).flatMap(w => /[가-힣]/.test(w) && w.length > 2 ? [w, ...Array.from({length: w.length - 1}, (_, i) => w.slice(i, i + 2))] : [w]);
  const q = new Set(tok(situation));
  const scored = done.map(d => {
    const lt = tok(`${d.lesson} ${d.why || ""}`); let ov = 0; for (const w of lt) if (q.has(w)) ov++;
    const rec = Math.max(0, 1 - (asOf - d.resolved) / (30 * 864e5));   // 30일 내 최근일수록 가중
    return {d, s: (q.size ? ov : 0) + (d.coin === coin ? 2 : 0) + rec * 2};
  }).sort((a, b) => b.s - a.s).slice(0, 6);
  return scored.map(({d}) => `- ${d.ko} ${d.rating} → 알파 ${pc(d.alpha)}: ${d.lesson}`).join("\n");
}
// 투자 대가 페르소나 (virattt/ai-hedge-fund 방식) — 강세·약세 리서처가 매번 다른 투자 철학으로 토론해 관점이 다양해진다.
const IC_PERSONAS = [
  {name: "가치투자파", style: "버핏식 가치투자", lean: "내재가치·안전마진·장기 보유를 중시한다. 단기 변동엔 흔들리지 않되, 영구적 가치훼손(규제·해킹·토큰노믹스 붕괴)은 치명적으로 본다."},
  {name: "역발상파", style: "하워드 막스식 역발상", lean: "군중이 공포일 때 기회, 탐욕일 때 경계. 공포·탐욕·쏠림 지표를 반대로 읽는다."},
  {name: "모멘텀파", style: "리버모어식 추세·모멘텀", lean: "추세는 친구. 신고가·거래량 동반 돌파를 좋아하고, 추세가 꺾이면 바로 빠진다."},
  {name: "매크로파", style: "소로스·달리오식 매크로", lean: "금리·유동성·달러·ETF 자금 같은 큰 흐름이 방향을 정한다고 본다. 과열/과냉(재귀성)을 경계한다."},
  {name: "퀀트파", style: "데이터·확률 중심", lean: "서사보다 숫자. 변동성·상관·기대값·손익비로만 판단하고 크기는 켈리로 정한다."},
  {name: "리스크패리티파", style: "브리지워터식 생존 우선", lean: "수익보다 생존. 포지션 크기·상관·꼬리위험을 먼저 보고 청산 가능성을 0에 가깝게 둔다."},
  {name: "성장주파", style: "캐시 우드·필립 피셔식 혁신 성장", lean: "판을 바꾸는 기술·채택 곡선·네트워크 효과를 본다. 단기 밸류에이션보다 장기 성장 궤적."},
  {name: "저평가방어파", style: "찰리 멍거식 '멍청한 짓 안 하기'", lean: "확실히 아는 것만. 역방향 체크리스트로 치명적 실수(과최적화·과레버리지·사기 토큰)를 먼저 걸러낸다."},
  {name: "현장파", style: "피터 린치식 '아는 것에 투자'", lean: "실제 쓰임·거래량·온체인 활동 같은 눈에 보이는 수요를 중시. 복잡한 서사보다 단순한 수급."},
  {name: "공매도파", style: "짐 차노스·마이클 버리식 회의론", lean: "거품·레버리지·펀딩 과열·청산 연쇄를 찾아 약세 시나리오를 날카롭게 제시한다. 반대편 리스크 담당."},
  {name: "이벤트파", style: "폴슨식 이벤트 드리븐", lean: "ETF·반감기·상장/상폐·규제 결정 같은 촉매와 그 전후 수급 변화를 노린다."},
  {name: "시스템파", style: "사이먼스·르네상스식 통계 차익", lean: "서사 완전 배제. 평균회귀·통계적 엣지·체결비용만. 작은 엣지를 많이, 리스크는 기계적으로."}
];
// 멀티에이전트 토론 합의 (LynchzDEV/ai-auto-trader-ahh): 페르소나 투표를 집계해 합의 강도를 낸다
function icConsensus(votes){
  const n = votes.length || 1, buy = votes.filter(v => v === "매수").length, sell = votes.filter(v => v === "매도").length, hold = n - buy - sell;
  const net = (buy - sell) / n, dir = net > 0.2 ? "매수" : net < -0.2 ? "매도" : "관망";
  return {dir, buy, sell, hold, agree: Math.round(Math.max(buy, sell, hold) / n * 100)};
}
async function icJob(){
  await icSettle();
  const named = userNote && COINS.find(c => new RegExp(`${c.ko}|${c.sym.replace("USDT", "")}`, "i").test(userNote));
  const c = named || COINS[rot("coinIC", COINS.length)], A = id => agentById(id), lead = A("ic_lead");
  fire({kind: "busy", agent: lead, text: `🏛 ${c.ko} 투자위원회 안건 준비 중`});
  // ① 애널리스트 4명 보고 — 숫자는 모두 코드가 만든 한 장의 '검증된 자료'(TradingAgents: 하나의 스냅샷이 유일한 출처)
  const row = await comboScan(c).catch(() => null), T = await lib("ta_rating"), k4 = await kl(c.sym, "240", 400), k1 = await kl(c.sym, "60", 400);
  const tv4 = T.rating(k4), tv1 = T.rating(k1), cdl = T.candles(k1);
  let flow = "", fund = null; try { const F = await import("../nuri-ai/flow.js"); const fs = await F.flowSnapshot({symbol: c.sym}); flow = String(fs.text || "").slice(0, 900); fund = fs.data?.futures?.funding ?? null; } catch(e){}
  let news = ""; try { const r = await TOOLS.market_news.run({category: "crypto"}); news = String(r.text || "").slice(0, 1200); } catch(e){}
  let fg = ""; try { const r = await TOOLS.sns_buzz.run({topic: "crypto"}); fg = (String(r.text || "").match(/공포·탐욕 지수[^\n]*/) || [""])[0]; } catch(e){}
  const price = k1.at(-1).c;
  const reports = {
    market: `현재가 ${fx(price)} · 실시간 종합판: ${row ? `큰 추세 ${Math.round(row.plan.big * 100)} · 타이밍 ${Math.round(row.plan.small * 100)} · ${row.plan.state} (${row.plan.why})` : "없음"} · 트레이딩뷰식 요약 4시간 ${tv4?.label} (${tv4?.all.toFixed(2)}) / 1시간 ${tv1?.label} (${tv1?.all.toFixed(2)}) · 캔들 ${cdl.map(x => x.name).join(", ") || "특이 없음"}`,
    social: fg || "공포·탐욕 자료 없음",
    news: news || "뉴스 자료 없음",
    fundamentals: flow || "선물·고래 흐름 자료 없음"
  };
  table("ic", lead.id, `🏛 ${c.ko} 투자위원회 — 애널리스트 보고 (코드 자료)`, ["애널리스트", "보고"], [["시장·기술", reports.market], ["여론·소셜", reports.social], ["뉴스·펀더멘털", clip(reports.news, 300)], ["선물·온체인 흐름", clip(reports.fundamentals, 300)]], "모든 숫자는 이 표에서만 인용 · 충돌은 평균 내지 말고 지적");
  const facts = `[${c.ko} ${c.sym} 위원회 자료 — 여기 숫자만 인용]\n시장·기술: ${reports.market}\n여론: ${reports.social}\n뉴스: ${clip(reports.news, 900)}\n선물·흐름: ${clip(reports.fundamentals, 900)}`;
  if (!hasAI()) return;
  const say = async (id, role, ask, extra = "") => (await solo(A(id), {room: "ic", sys: personaOf(A(id), role), user: `${facts}${extra}\n\n${ask}`, maxTokens: 650, train: "아래 코인 자료로 투자위원회 역할에 맞게 의견을 말해 줘."})).text || "";
  // ② 강세·약세 토론 (1라운드 = 2발언) — 매번 다른 투자 대가 철학으로 (ai-hedge-fund 방식)
  const pB = IC_PERSONAS[rot("icPersBull", IC_PERSONAS.length)], pR = IC_PERSONAS[(rot("icPersBear", IC_PERSONAS.length) + 1) % IC_PERSONAS.length];
  post({ch: "ic", kind: "system", text: `🏛 오늘 ${c.ko} 토론 관점 — 강세: ${pB.name}(${pB.style}) · 약세: ${pR.name}(${pR.style})`});
  const bull = await say("ic_4", `강세 리서처 — 투자 철학은 '${pB.name}(${pB.style})': ${pB.lean} 이 철학의 눈으로 자료에서 오를 근거만 모아 가장 강한 매수 논리를 3~5문장으로. 약세 논리의 약점도 하나 짚는다.`, "강세 논리를 말해 주세요.");
  const bear = await say("ic_5", `약세 리서처 — 투자 철학은 '${pR.name}(${pR.style})': ${pR.lean} 이 철학의 눈으로 자료에서 내릴 근거만 모아 가장 강한 매도 논리를 3~5문장으로. 방금 강세 논리의 약점을 반박한다.`, "약세 논리로 반박해 주세요.", `\n\n강세 리서처(${pB.name}): ${clip(bull, 700)}`);
  // ③ 리서치 매니저: '의견 충돌은 관망 사유가 아니다' — 더 강한 쪽에 확신 크기만큼
  const rm = await say("ic_6", "리서치 매니저: 강세·약세 토론을 심판한다. 의견이 엇갈린다는 것만으로 관망하지 않는다 — 근거가 더 강한 쪽을 고르고 그 차이만큼 등급을 정한다. 근거가 정말 비슷하거나 부족할 때만 관망. 마지막 줄은 반드시 '등급: 매수|비중확대|관망|비중축소|매도' 중 하나.", "투자 계획과 등급을 정해 주세요.", `\n\n강세: ${clip(bull, 600)}\n약세: ${clip(bear, 600)}`);
  // ④ 트레이더: 진입·손절은 절대 가격만 (%, 범위, N/A 는 무효)
  const tr = await say("ic_7", "트레이더: 리서치 매니저 계획을 실제 거래안으로 바꾼다. 마지막 세 줄을 정확히 '결정: 매수|관망|매도' '진입: 숫자' '손절: 숫자' 형식으로 (가격은 절대값 숫자만, % 나 범위 금지).", "거래안을 내 주세요.", `\n\n리서치 매니저: ${clip(rm, 600)}`);
  const entry = toPrice((tr.match(/진입\s*[:：]\s*([^\n]+)/) || [])[1]), stop = toPrice((tr.match(/손절\s*[:：]\s*([^\n]+)/) || [])[1]);
  // ⑤ 리스크 토론 (1라운드 = 3발언)
  const ctxR = `\n\n트레이더 안: ${clip(tr, 500)}${entry ? ` (진입 ${fx(entry)}, 손절 ${stop ? fx(stop) : "없음"})` : ""}`;
  const agg = await say("ic_8", "공격형 리스크 토론자: 기회를 놓치는 위험을 강조하며 더 과감한 크기·진입을 주장한다(근거는 자료에서).", "공격적 관점을 말해 주세요.", ctxR);
  const con = await say("ic_10", "보수형 리스크 토론자: 손실·청산·쏠림 위험을 강조하며 크기 축소나 관망을 주장한다(근거는 자료에서).", "보수적 관점을 말해 주세요.", ctxR + `\n공격형: ${clip(agg, 400)}`);
  const neu = await say("ic_9", "중립형 리스크 토론자: 두 주장을 저울질해 균형 잡힌 크기·조건을 제안한다.", "중립 관점을 말해 주세요.", ctxR + `\n공격형: ${clip(agg, 400)}\n보수형: ${clip(con, 400)}`);
  // ⑥ 위원장 최종 결정 — 지난 결정의 교훈은 여기에만
  const lessons = icLessons(c.id, Date.now(), `${reports.market} ${reports.social} ${clip(reports.fundamentals, 200)}`);   // 지금 상황과 비슷한 과거 교훈을 우선 (TradingAgents 메모리 방식)
  const pm = (await solo(lead, {room: "ic", sys: personaOf(lead, "투자위원장(포트폴리오 매니저): 리스크 토론을 심판해 최종 결정한다. 의견 충돌만으로 관망하지 않는다. 지난 교훈을 참고한다. 3~6문장, 마지막 줄은 반드시 '최종 등급: 매수|비중확대|관망|비중축소|매도'. 실제 주문은 코드 관문과 대표 승인으로만 나간다는 것을 안다."),
    user: `${facts}\n\n리서치 매니저: ${clip(rm, 500)}\n트레이더: ${clip(tr, 400)}\n공격형: ${clip(agg, 350)}\n보수형: ${clip(con, 350)}\n중립형: ${clip(neu, 350)}\n\n지난 결정의 교훈(결정 시점 이전에 확정된 것만):\n${lessons || "(아직 없음)"}\n\n최종 결정을 내려 주세요.`, maxTokens: 700, train: "아래 투자위원회 토론을 보고 최종 결정을 내려 줘."})).text || "";
  const toVote = r => ({매수: "매수", 비중확대: "매수", 매도: "매도", 비중축소: "매도"}[r] || "관망");
  const trDec = ((tr.match(/결정\s*[:：]\s*(매수|관망|매도)/) || [])[1]) || "관망";
  const rating = parseRating(pm), rmRating = parseRating(rm), cons = icConsensus([toVote(rating), toVote(rmRating), trDec]), b0 = (await kl("BTCUSDT", "240", 5).catch(() => null))?.at(-1)?.c;
  const d = {id: uid(), coin: c.id, ko: c.ko, t: Date.now(), due: Date.now() + 5 * 4 * 3600e3, p0: price, btc0: b0, rating, rmRating, cons, entry, stop, why: clip(pm, 700), status: rating === "REVIEW" ? "review" : "pending"};
  const L = icLedger(); L.push(d); writeJ(IC_KEY, L.slice(-200));
  pubTo(c.sym, "ic", {team: "ic", title: `투자위원회 최종: ${rating}`, text: clip(pm, 400), lines: [entry ? {price: entry, label: "위원회 진입", color: "#ab47bc"} : null, stop ? {price: stop, label: "위원회 손절", color: "#f23645", style: 2} : null].filter(Boolean),
    markers: L.filter(x => x.coin === c.id).slice(-20).map(x => ({t: x.t, dir: {매수: 1, 비중확대: 1, 매도: -1, 비중축소: -1}[x.rating] || 0, text: `위원회 ${x.rating}${x.status === "resolved" ? (x.hit ? " ✅" : " ❌") : ""}`, color: "#ab47bc"}))});
  journal("audit", "ic-decision", d.id, {coin: c.id, rating, entry, stop}, "ic_lead", "투자위원회 결정");
  table("ic", lead.id, `🏛 ${c.ko} 투자위원회 결정: ${rating === "REVIEW" ? "⚠ REVIEW (등급을 읽지 못함 — 거래 금지)" : rating}`, ["단계", "결과"], [["리서치 매니저", rmRating], ["트레이더", `${(tr.match(/결정\s*[:：]\s*(매수|관망|매도)/) || [])[1] || "?"} · 진입 ${entry ? fx(entry) : "무효"} · 손절 ${stop ? fx(stop) : "무효"}`], ["최종(위원장)", rating], ["채점", "5봉(4시간봉) 뒤 비트코인 대비 초과수익으로 자동 채점 → 교훈으로 기억"]], "결정은 기록일 뿐 — 실제 주문은 데모 관문 + 대표 승인으로만");
  addNote("ic", `${c.ko} 최종 ${rating}${entry ? ` (진입 ${fx(entry)})` : ""}`, "위원회");
}

/* ---- 📐 퀀트 리스크팀 (gs-quant 시계열 · nautilus/vnpy 리스크 엔진 · jdmn 결정표) ---- */
export const RISK_TABLE = {name: "리스크 판정", hit: "P", default: {act: "유지", why: "규칙에 해당 없음"},
  inputs: [{key: "var95", label: "1일 VaR95 %"}, {key: "dd", label: "30일 낙폭 %"}, {key: "vol", label: "연율 변동성 %"}, {key: "corr", label: "BTC 상관"}],
  outputs: [{key: "act", label: "조치", values: ["거래 정지", "비중 절반", "신규 진입 보류", "유지"]}, {key: "why", label: "이유"}],
  rules: [
    {when: [">=12", "-", "-", "-"], then: ["거래 정지", "하루 최악 손실이 12% 이상"], note: "꼬리 위험 극단"},
    {when: ["-", "<=-35", "-", "-"], then: ["거래 정지", "30일 낙폭 35% 이상"], note: "폭락장"},
    {when: ["[7..12)", "-", "-", "-"], then: ["비중 절반", "VaR 7~12%"], note: ""},
    {when: ["-", "-", ">=110", "-"], then: ["비중 절반", "변동성 연 110% 이상"], note: ""},
    {when: ["-", "(-35..-20]", "-", "-"], then: ["신규 진입 보류", "낙폭 20~35%"], note: ""},
    {when: ["-", "-", "-", ">=0.9"], then: ["신규 진입 보류", "BTC와 거의 같이 움직임(분산 효과 없음)"], note: "동시 포지션 주의"}
  ]};
async function qriskJob(){
  const R = await lib("riskq"), D = await lib("dmn"), E = await lib("execution"), lead = agentById("qrisk_lead");
  fire({kind: "busy", agent: lead, text: "📐 6개 코인 VaR·상관·베타 계산 중"});
  const day = {}; for (const c of COINS){ try { day[c.id] = (await kl(c.sym, "D", 400)).map(b => b.c); } catch(e){} }
  const btc = day.btc || [], rows = [], verdicts = [];
  for (const c of COINS){
    const px = day[c.id]; if (!px?.length) { rows.push([c.ko, "—", "—", "—", "—", "—", "—", "자료 없음"]); continue; }
    const v = R.volatility(px, {w: 30}), ev = R.ewmaVol(px), hv = R.historicalVaR(px, {conf: 0.95, w: 365}), dd = R.currentDrawdown(px, {w: 30}), corr = c.id === "btc" ? 1 : R.correlation(px, btc, {w: 90}), beta = c.id === "btc" ? 1 : R.beta(px, btc, {w: 90});
    const ctx = {var95: hv?.var, dd, vol: v, corr: c.id === "btc" ? null : corr}, ev2 = D.evaluate(RISK_TABLE, ctx);   // 비트코인 자신과의 상관(1)은 판정에 쓰지 않음
    verdicts.push({c, res: ev2});
    pubTo(c.sym, "qrisk", {team: "qrisk", title: `리스크 판정: ${ev2.result.act}`, text: `변동성 ${v.toFixed(0)}% · VaR95 ${hv ? hv.var.toFixed(1) + "%" : "—"} · 30일 낙폭 ${dd.toFixed(1)}% · BTC 상관 ${corr == null ? "—" : corr.toFixed(2)} · ${ev2.result.why}`,
      lines: hv ? [{price: px.at(-1) * (1 - hv.var / 100), label: "하루 VaR95 하단", color: "#9c27b0", style: 2}, {price: px.at(-1) * (1 + hv.var / 100), label: "하루 VaR95 상단", color: "#9c27b0", style: 2}] : []});
    rows.push([c.ko, `${v.toFixed(0)}%`, `${ev.toFixed(0)}%`, hv ? `${hv.var.toFixed(1)}% / ${hv.cvar.toFixed(1)}%` : "—", `${dd.toFixed(1)}%`, corr == null ? "—" : corr.toFixed(2), beta == null ? "—" : beta.toFixed(2), `${ev2.result.act}${ev2.matched.length ? ` (규칙 ${ev2.matched.map(m => m.row).join(",")})` : ""}`]);
  }
  table("qrisk", lead.id, "📐 코인별 위험 (일봉 · gs-quant 방식, 코인은 365일 연환산)", ["코인", "변동성 30일", "EWMA 변동성", "VaR95 / CVaR95 (1일)", "30일 낙폭", "BTC 상관 90일", "베타", "결정표 판정"], rows, "결정표 적중 정책 PRIORITY: 거래 정지 > 비중 절반 > 신규 진입 보류 > 유지 · 판정은 코드가 함");
  // 데모 포지션 포트폴리오 VaR (분산-공분산) + 스트레스(BTC −30%, 알트는 베타만큼)
  let pv = null, stress = [];
  try {
    const P = await import("../nuri-ai/paper.js"), book = await P.loadBook(), w = {};
    for (const s of book.strategies.filter(x => x.status === "active" && x.pos)){ const c = COINS.find(x => x.sym === s.market); if (!c) continue; const exp = s.pos.side === "long" ? 1 : -1; w[c.id] = (w[c.id] || 0) + exp * (s.pos.margin || 0) * (s.pos.lev || 1); }
    if (Object.keys(w).length){
      pv = R.portfolioVaR(day, w, {conf: 0.95});
      for (const [id, expo] of Object.entries(w)){ const b = id === "btc" ? 1 : R.beta(day[id], btc, {w: 90}) ?? 1; stress.push([COINS.find(x => x.id === id).ko, fx(expo), `${(-30 * b).toFixed(1)}%`, fx(expo * -0.30 * b)]); }
      table("qrisk", lead.id, `🧨 스트레스 시험: 비트코인 −30% (알트는 베타만큼) · 데모 포지션 포트폴리오 VaR95 ${pv == null ? "—" : fx(pv)} USDT`, ["코인", "노출(USDT, 롱+/숏−)", "충격", "예상 손익(USDT)"], stress, "gs-quant 시나리오(충격 비례 전파) 방식 · 데모(모의) 포지션 기준");
    }
  } catch(e){}
  // 주문 전 점검 예시 (nautilus RiskEngine + vnpy 리스크 매니저) — 지금 한도에서 BTC 50 USDT 주문이 통과하는지
  let live = null; try { const Lm = await import("../nuri-ai/live.js"); live = Lm.liveCfg?.(); } catch(e){}
  const st = E.tradingState({halted: !!live?.halted, dayLoss: 0}), p = btc.at(-1) || 0;
  const chk = E.preTradeCheck({side: 1, qty: +(45 / (p || 1)).toFixed(3), price: p}, {state: st, rules: {step: 0.001, minNotional: 5}, limits: {maxNotional: 50, maxPositions: 2, openPositions: 0}});
  table("qrisk", lead.id, `🛡 주문 전 점검표 (예: BTC 약 45 USDT 롱) — ${chk.ok ? "통과" : "막힘: " + chk.text}`, ["점검", "결과", "기준"], chk.checks.map(x => [x.id, x.ok ? "✅" : "❌", x.text]), `거래 상태: ${E.STATES[st]} · 실제 주문은 live.js 의 한도·승인이 최종 결정`);
  const bad = verdicts.filter(v => v.res.result.act !== "유지");
  if (bad.length) addNote("qrisk", bad.map(v => `${v.c.ko}: ${v.res.result.act} (${v.res.result.why})`).join(" · "), "결정표");
  journal("audit", "risk-verdict", today(), Object.fromEntries(verdicts.map(v => [v.c.id, v.res.result.act])), "qrisk_lead", "결정표 판정");
  writeJ("coinRiskVerdict", Object.fromEntries(verdicts.map(v => [v.c.id, {act: v.res.result.act, why: v.res.result.why, t: Date.now()}])));   // ← 데모·실거래 진입 관문이 실제로 읽는다
  await explain(lead.id, "qrisk", "코인별 위험표·결정표 판정·스트레스 시험·주문 전 점검을 보고 지금 가장 위험한 곳과 바로 할 조치를 해설한다.", tableText(["코인", "변동성", "EWMA", "VaR/CVaR", "낙폭", "상관", "베타", "판정"], rows) + (pv != null ? `\n포트폴리오 VaR95 ${fx(pv)} USDT` : "") + `\n주문 전 점검: ${chk.text}`, "아래 위험표를 보고 위험을 해설해 줘.");
}

/* ---- 🗄 데이터 플랫폼팀 (ccxt 멀티 거래소 · OpenBB 무료 데이터 · Legend 데이터 품질 · obevo 이전 · reladomo 감사) ---- */
async function dataJob(){
  const X = await lib("exchanges"), S = await lib("sdlc"), J = await lib("journal"), M = await lib("migrate"), {webGet} = await import("../nuri-ai/engine.js"), lead = agentById("data_lead");
  const c = COINS[rot("coinData", COINS.length)], base = c.sym.replace("USDT", "");
  fire({kind: "busy", agent: lead, text: `🔌 ${c.ko} 8개 거래소 시세 맞춰 보는 중`});
  const cmp = await X.compare(u => webGet(u, "json"), base);
  { const D0 = readJ("coinDataV", {}), bin = (cmp.rows || []).find(r => /바이낸스/.test(r.ko || "") && r.funding8h != null) || (cmp.rows || []).find(r => r.funding8h != null); D0[c.id] = {kimchi: cmp.kimchi ?? null, funding8h: bin?.funding8h ?? null, fundSpread: cmp.fundSpread ?? null, t: Date.now()}; writeJ("coinDataV", D0); }   // ccxt 거래소 비교 → 진입 관문
  pubTo(c.sym, "data", {team: "data", title: "거래소 비교", text: `김치 프리미엄 ${cmp.kimchi == null ? "—" : pc(cmp.kimchi)} · 최대 가격차 ${cmp.maxGap == null ? "—" : cmp.maxGap.toFixed(3) + "%"} · 펀딩 최대차 ${cmp.fundSpread == null ? "—" : cmp.fundSpread.toFixed(4) + "%p"}`, rows: cmp.rows.filter(r => r.last).map(r => [r.ko, `${fx(r.last)} ${r.quote}`, r.spreadPct == null ? "—" : pc(r.spreadPct), r.funding8h == null ? "—" : r.funding8h.toFixed(4) + "%"])});
  table("data", lead.id, `🔌 ${c.ko} 거래소 비교 (ccxt 방식 통일 · 기준 바이낸스 선물)`, ["거래소", "가격", "기준 대비", "24시간", "펀딩(8시간 환산)", "미결제약정(코인)", "비고"],
    cmp.rows.map(r => [r.ko, r.last ? `${fx(r.last)} ${r.quote}` : "—", r.spreadPct == null ? "—" : pc(r.spreadPct), r.chg24 == null ? "—" : pc(r.chg24), r.funding8h == null ? "—" : r.funding8h.toFixed(4) + "%", r.oiCoin == null ? "—" : fx(r.oiCoin, 0), r.err ? "받기 실패: " + r.err : (r.note || "")]),
    `김치 프리미엄 ${cmp.kimchi == null ? "—" : pc(cmp.kimchi)} · 거래소 간 최대 가격차 ${cmp.maxGap == null ? "—" : cmp.maxGap.toFixed(3) + "%"} · 펀딩 최대차 ${cmp.fundSpread == null ? "—" : cmp.fundSpread.toFixed(4) + "%p"}`);
  // 데이터 품질 (Legend 제약 방식): 1시간봉 OHLC 위반·빈 봉·이상 급등락·지연
  const q = []; for (const cc of COINS){ try { const k = await kl(cc.sym, "60", 500), r = S.candleQuality(k, 3600e3); q.push([cc.ko, String(r.n), String(r.bad), String(r.gaps), String(r.spikes), r.stale ? "지연" : "정상", r.ok ? "✅" : "⚠"]); } catch(e){ q.push([cc.ko, "—", "—", "—", "—", "받기 실패", "❌"]); } }
  table("data", lead.id, "🧪 시세 데이터 품질 (1시간봉 500개)", ["코인", "봉", "OHLC 위반", "빈 봉", "±25% 급변", "최신성", "판정"], q, "모델 제약: 고가 ≥ 시가·종가 ≥ 저가 > 0, 거래량 ≥ 0");
  const v = J.verify(), dl = M.deployLog(), projs = S.projects();
  table("data", lead.id, "🗄 저장소·감사 상태", ["항목", "상태"], [["감사 기록(이중 시간) 해시 사슬", v.ok ? `정상 · ${v.n}행` : `⚠ ${v.at}번째 행에서 끊김`], ["저장소 이전(마이그레이션)", dl.length ? dl.slice(-3).map(x => `${x.name}: ${x.status}`).join(" · ") : "기록 없음"], ["전략 버전 관리", `${projs.length}개 전략 · 버전 ${projs.reduce((s, p) => s + p.versions.length, 0)}개 · 검토 대기 ${projs.reduce((s, p) => s + p.reviews.filter(r => r.status === "review").length, 0)}건`]], "obevo · reladomo · Legend SDLC 방식");
  await explain(lead.id, "data", "거래소 비교(가격차·김치 프리미엄·펀딩 차이)와 데이터 품질·감사 상태를 보고 이상한 점과 그 의미(차익·쏠림·데이터 오류)를 해설한다.", `${c.ko}: 김치 ${cmp.kimchi == null ? "—" : pc(cmp.kimchi)}, 최대 가격차 ${cmp.maxGap?.toFixed(3)}%, 펀딩 최대차 ${cmp.fundSpread?.toFixed(4)}%p\n` + cmp.rows.map(r => `${r.ko}: ${r.last ?? "실패"} ${r.funding8h != null ? "펀딩 " + r.funding8h.toFixed(4) : ""}`).join("\n") + "\n품질: " + q.map(r => `${r[0]} ${r[6]}`).join(", "), "아래 거래소 비교와 데이터 품질을 해설해 줘.");
}
// 경제 캘린더·금리·변동성 지수 (OpenBB 의 무료 공급원 주소) → 뉴스·경제지표팀
async function openFeedsJob(){
  const {webGet} = await import("../nuri-ai/engine.js"), a = agentById("econfc") || agentById("macro"), rows = [];
  fire({kind: "busy", agent: a, text: "🗓 경제 캘린더·금리·변동성 지수 받는 중"});
  const d = new Date().toISOString().slice(0, 10);
  try { const r = await webGet(`https://api.nasdaq.com/api/calendar/economicevents?date=${d}`, "json"); for (const e of (r?.data?.rows || []).filter(x => /United States|Euro|China|Japan|Korea/i.test(x.country || "")).slice(0, 10)) rows.push(["캘린더", `${e.gmt || ""} ${e.country}`, e.eventName, `예상 ${e.consensus || "—"} · 이전 ${e.previous || "—"} · 실제 ${e.actual || "—"}`]); } catch(e){ rows.push(["캘린더", "Nasdaq", "받기 실패", String(e.message).slice(0, 40)]); }
  try { const r = await webGet(`https://api.nasdaq.com/api/calendar/economicevents?date=${d}`, "json"), HI = /CPI|FOMC|Fed|Interest Rate|Nonfarm|Payroll|GDP|PCE|Unemployment|Powell|Inflation/i;
    const ev = (r?.data?.rows || []).filter(x => /United States/i.test(x.country || "") && HI.test(x.eventName || "")).map(x => { const m = String(x.gmt || "").match(/(\d{1,2}):(\d{2})/); return m ? {t: Date.parse(`${d}T${m[1].padStart(2, "0")}:${m[2]}:00Z`), name: x.eventName} : null; }).filter(Boolean);
    writeJ("coinCalendar", {events: ev, t: Date.now()}); } catch(e){}   // OpenBB 공급원 경제 캘린더 → 고영향 일정 ±30분 진입 중지
  try { const r = await webGet("https://markets.newyorkfed.org/api/rates/secured/sofr/last/1.json", "json"); const x = r?.refRates?.[0]; if (x) rows.push(["금리", "뉴욕 연준", "SOFR", `${x.percentRate}% (${x.effectiveDate})`]); } catch(e){}
  try { const now = Date.now(), r = await webGet(`https://www.deribit.com/api/v2/public/get_volatility_index_data?currency=BTC&start_timestamp=${now - 3 * 864e5}&end_timestamp=${now}&resolution=3600`, "json"); const v = r?.result?.data?.at(-1); if (v) rows.push(["변동성", "Deribit", "BTC DVOL(내재변동성)", `${(+v[4]).toFixed(1)} (3일 전 ${(+r.result.data[0][4]).toFixed(1)})`]); } catch(e){}
  try { const t = await webGet("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10", "text"); const last = t.trim().split("\n").filter(l => /,\d/.test(l)).at(-1); if (last) rows.push(["금리", "FRED", "미 10년물", last.replace(",", " → ") + "%"]); } catch(e){}
  table("news", a.id, `🗓 오늘 경제 캘린더 · 금리 · 코인 변동성 (OpenBB 공급원 방식, 키 없이)`, ["종류", "출처", "항목", "값"], rows.length ? rows : [["—", "—", "받은 자료 없음", "실행기(GHCoin.exe)로 실행해야 인터넷 자료를 받습니다"]], "Nasdaq 경제 캘린더 · 뉴욕 연준 SOFR · Deribit DVOL · FRED");
  if (rows.length > 1) await explain(a.id, "news", "오늘 경제 일정과 금리·코인 내재변동성을 보고 코인 시장에 영향이 클 시간과 이유를 해설한다.", tableText(["종류", "출처", "항목", "값"], rows), "아래 경제 일정과 지표를 보고 코인 시장 영향을 해설해 줘.");
}

/* ---- 🎛 전략 최적화팀 (freqtrade 하이퍼옵트·ROI·보호장치 · backtrader 분석기 · Vibe-Trading 견고성 · Legend SDLC 버전) ---- */
const OPT_LOSS = ["SharpeDaily", "SortinoDaily", "Calmar", "ProfitDrawDown", "MultiMetric", "ShortTradeDur"];
// 개선 후보(아깝게 탈락) → 하이퍼옵트 대상 객체
function nearMissCands(){ return readJ("coinNearMiss", []).map((x, i) => ({id: "nm" + i, name: x.name, spec: x.spec, market: x.market, exchange: x.exchange || "binancef", tf: x.tf, lane: x.lane || "std", nearMiss: true})); }
function dropNearMiss(name){ writeJ("coinNearMiss", readJ("coinNearMiss", []).filter(x => x.name !== name)); }
async function optJob(){
  const Q = await import("../nuri-ai/quant.js"), P = await import("../nuri-ai/paper.js"), H = await lib("hyperopt"), RB = await lib("robust"), S = await lib("sdlc"), lead = agentById("opt_lead");
  const book = await P.loadBook(); let cands = book.strategies.filter(s => s.status === "active" && s.spec);
  if (!cands.length){ cands = nearMissCands();
    if (!cands.length){ post({ch: "opt", kind: "work", agent: lead.id, icon: "🎛", text: "다듬을 데모 전략·개선 후보가 아직 없습니다 · 매매법 개발이 결과를 내면 바로 하이퍼옵트합니다"}); return; }
    post({ch: "opt", kind: "work", agent: lead.id, icon: "🎛", text: `데모 전략이 없어 아깝게 탈락한 후보 ${cands.length}개 중 하나를 하이퍼옵트로 고쳐 통과시켜 봅니다`}); }
  const s = cands[rot("coinOpt", cands.length)], loss = OPT_LOSS[rot("coinOptLoss", OPT_LOSS.length)], tf = s.tf, tfMin = {"15": 15, "60": 60, "240": 240, "D": 1440}[tf] || 60;
  fire({kind: "busy", agent: lead, text: `🎛 ${s.name} 하이퍼옵트 (${H.LOSSES[loss].ko})`});
  const cs = (await candlesFor({market: s.market, exchange: s.exchange || "binancef", timeframe: tf}, 1500)).cs;
  H.setSeed(Date.now() % 100000);
  const res = await H.hyperopt(Q, s.spec, cs, {epochs: 60, loss, space: ["buy", "roi", "stoploss", "trailing", "protection"], tfMin, onProgress: (e, n) => fire({kind: "busy", agent: lead, text: `🎛 하이퍼옵트 ${e}/${n}`})});
  const b0 = Q.backtest(s.spec, cs), b1 = Q.backtest(res.best.spec, cs), A0 = H.analyzers(b0.equity, b0.trades, {perYear: 365 * 24 * 60 / tfMin}), A1 = H.analyzers(b1.equity, b1.trades, {perYear: 365 * 24 * 60 / tfMin});
  const r0 = RB.permutationTest(b0.trades.map(t => t.pnl)), r1 = RB.permutationTest(b1.trades.map(t => t.pnl)), mw = RB.multiWindow(Q, res.best.spec, cs, 5), hy = RB.hygiene(b1);
  const f = (x, d = 2) => x == null || !Number.isFinite(x) ? "—" : (+x).toFixed(d);
  table("opt", lead.id, `🎛 ${s.name} 하이퍼옵트 결과 (${res.lossKo} · ${res.epochs}회 · 앞 70%에서만 탐색)`, ["지표", "지금 전략", "최적화 후"], [
    ["손실함수 값(작을수록 좋음)", f(res.base.loss, 3), f(res.best.loss, 3)], ["검증 구간(뒤 30%) 순손익", f(res.base.wf.oos.net_pnl), f(res.best.wf.oos.net_pnl)], ["관문 통과", res.base.wf.pass ? "✅" : "❌", res.best.wf.pass ? "✅" : "❌"],
    ["SQN (backtrader)", `${f(A0.sqn)} ${A0.sqnGrade}`, `${f(A1.sqn)} ${A1.sqnGrade}`], ["VWR (변동성 가중 수익)", f(A0.vwr, 1), f(A1.vwr, 1)], ["최대 낙폭 % / 최장 물림(봉)", `${f(A0.maxdd, 1)} / ${A0.maxddLen}`, `${f(A1.maxdd, 1)} / ${A1.maxddLen}`],
    ["연승 / 연패", `${A0.streakWon} / ${A0.streakLost}`, `${A1.streakWon} / ${A1.streakLost}`], ["운일 확률 p (순열 1000회)", f(r0.p, 3), f(r1.p, 3)], ["5구간 중 이익 구간", "—", `${mw.positive}/${mw.total}`],
    ["ROI 표 / 보호장치 잠금", "—", `${JSON.stringify(res.best.risk.minimal_roi || {})} / ${b1.stats.protection_locks}회`]],
    res.improved ? "✅ 검증 구간에서도 좋아짐 → 새 버전으로 데모 투입" : res.overfit ? "⚠ 학습 구간만 좋아짐(과최적화) → 채택 안 함" : "변화 없음/불통과 → 지금 전략 유지");
  // SDLC: 검토 요청 → (코드 관문 통과 + 견고성 p ≤ 0.05 + 위생) 이면 승인 → 새 버전
  const rv = S.propose(res.best.spec, {author: lead.name, why: `하이퍼옵트(${loss})`});
  const ok = (!s.nearMiss || res.best.wf?.pass) && rv.status === "review" && res.improved && r1.p != null && r1.p <= 0.05 && hy.ok && mw.positive >= Math.ceil(mw.total * 0.6);
  S.decide(res.best.spec.name, rv.id, ok, {who: "코드 관문", why: ok ? "검증·견고성 통과" : `미채택: ${!res.improved ? "검증 개선 없음" : r1.p > 0.05 ? "운일 확률 높음" : !hy.ok ? hy.fails.join(",") : "구간 일관성 부족"}`});
  if (ok && s.nearMiss) dropNearMiss(s.name);
  if (ok){
    const ns = await P.addStrategy({spec: {...res.best.spec, name: `${s.name} v${S.latest(res.best.spec.name)?.semver || "+"}`}, market: s.market, exchange: s.exchange, tf, author: lead.name, wf: {is: res.best.wf.is, oos: res.best.wf.oos}, cls: s.cls, mname: s.mname, lane: s.lane});
    post({ch: (LANES[s.lane] || LANES.std).demo, kind: "system", text: `🎛 최적화 버전 데모 투입: ${ns.name} (원본 ${s.name}은 그대로 비교 운용)`});
    journal("record", "strategy", ns.id, {from: s.id, loss, semver: S.latest(res.best.spec.name)?.semver, phash: specHash(res.best.spec)}, "opt_lead", "하이퍼옵트 버전");
  }
  pubTo(s.market, "opt", {team: "opt", title: `하이퍼옵트: ${ok ? "새 버전 채택" : "유지"}`, text: `${s.name} · ${res.lossKo} · 검증 순손익 ${f(res.base.wf.oos.net_pnl)} → ${f(res.best.wf.oos.net_pnl)} · 운일 확률 ${f(r1.p, 3)}`, spec: res.best.spec, baseSpec: s.spec});
  addNote("opt", `${s.name}: ${res.lossKo} → ${ok ? "새 버전 투입" : "유지"} (검증 순손익 ${f(res.base.wf.oos.net_pnl)} → ${f(res.best.wf.oos.net_pnl)}, p=${f(r1.p, 3)})`, "하이퍼옵트");
  await explain(lead.id, "opt", "하이퍼옵트 결과표를 보고 무엇이 바뀌었는지, 검증 구간(한 번도 안 본 데이터)에서도 좋아졌는지, 과최적화·운일 가능성은 어떤지 해설한다. 채택 여부는 코드 판정을 따른다.", `전략 ${s.name} · 손실함수 ${res.lossKo}\n검증 순손익 ${f(res.base.wf.oos.net_pnl)} → ${f(res.best.wf.oos.net_pnl)} · 관문 ${res.best.wf.pass ? "통과" : "불통과"} · SQN ${f(A0.sqn)} → ${f(A1.sqn)} · 운일 확률 ${f(r1.p, 3)} · 5구간 이익 ${mw.positive}/${mw.total} · 판정 ${ok ? "채택" : "미채택"}`, "아래 하이퍼옵트 결과를 해설해 줘.");
}

/* ---- 🔧 자동 개선 (선물 자동매매봇팀) — 올라간 🤖 봇 전략의 보조지표 길이·문턱값(buy)과 ROI·손절·추적손절·보호장치를
       하이퍼옵트로 다듬는다. 앞 70%에서만 탐색하고, 뒤 30%(검증) + 견고성(순열·다구간·위생)을 통과해야 새 버전 채택.
       실거래 관문(14일·20거래…)은 그대로라 자동 개선이 실거래를 건너뛰지 않는다. ---- */
async function botImproveJob(){
  const Q = await import("../nuri-ai/quant.js"), P = await import("../nuri-ai/paper.js"), H = await lib("hyperopt"), RB = await lib("robust"), S = await lib("sdlc"), lead = agentById("bot_lead");
  const book = await P.loadBook(); let bots = book.strategies.filter(s => s.status === "active" && s.spec && /^🤖/.test(s.name));
  if (!bots.length && nearMissCands().length){ bots = nearMissCands(); post({ch: "bot", kind: "work", agent: lead.id, icon: "🔧", text: `데모 봇이 없어 아깝게 탈락한 후보 ${bots.length}개를 보조지표·위험값 최적화로 고쳐 봅니다`}); }
  if (!bots.length){ post({ch: "bot", kind: "work", agent: lead.id, icon: "🔧", text: "자동 개선할 데모 봇이 없습니다 · 봇 전략이 백테스트를 통과해 데모에 올라가면 보조지표·위험값을 자동으로 다듬습니다"}); return; }
  const s = bots[rot("coinBotOpt", bots.length)], loss = OPT_LOSS[rot("coinBotOptLoss", OPT_LOSS.length)], tf = s.tf, tfMin = {"15": 15, "60": 60, "240": 240, "D": 1440}[tf] || 60;
  fire({kind: "busy", agent: lead, text: `🔧 ${s.name} 자동 개선(보조지표·위험값 하이퍼옵트 · ${H.LOSSES[loss].ko})`});
  const cs = (await candlesFor({market: s.market, exchange: s.exchange || "binancef", timeframe: tf}, 1500)).cs;
  H.setSeed(Date.now() % 100000);
  const res = await H.hyperopt(Q, s.spec, cs, {epochs: 60, loss, space: ["buy", "roi", "stoploss", "trailing", "protection"], tfMin, onProgress: (e, n) => fire({kind: "busy", agent: lead, text: `🔧 자동 개선 ${e}/${n}`})});
  const b1 = Q.backtest(res.best.spec, cs), r1 = RB.permutationTest(b1.trades.map(t => t.pnl)), mw = RB.multiWindow(Q, res.best.spec, cs, 5), hy = RB.hygiene(b1);
  const f = (x, d = 2) => x == null || !Number.isFinite(x) ? "—" : (+x).toFixed(d);
  // 지표 길이·문턱값이 실제로 어떻게 바뀌었는지 사람이 읽게
  const indBefore = (s.spec.indicators || []).map(i => `${i.type}${i.length ?? i.fast ?? ""}`).join(", ");
  const indAfter = (res.best.spec.indicators || []).map(i => `${i.type}${i.length ?? i.fast ?? ""}`).join(", ");
  const rv = S.propose(res.best.spec, {author: lead.name, why: `봇 자동개선(${loss})`});
  const ok = (!s.nearMiss || res.best.wf?.pass) && rv.status === "review" && res.improved && r1.p != null && r1.p <= 0.05 && hy.ok && mw.positive >= Math.ceil(mw.total * 0.6);
  S.decide(res.best.spec.name, rv.id, ok, {who: "코드 관문", why: ok ? "검증·견고성 통과" : `미채택: ${!res.improved ? "검증 개선 없음" : r1.p > 0.05 ? "운일 확률 높음" : !hy.ok ? hy.fails.join(",") : "구간 일관성 부족"}`});
  table("bot", lead.id, `🔧 ${s.name} 자동 개선 (${res.lossKo} · ${res.epochs}회 · 앞 70%에서만 탐색)`, ["항목", "지금", "개선안"], [
    ["보조지표", indBefore || "—", indAfter || "—"],
    ["검증(뒤 30%) 순손익", f(res.base.wf.oos.net_pnl), f(res.best.wf.oos.net_pnl)],
    ["관문 통과", res.base.wf.pass ? "✅" : "❌", res.best.wf.pass ? "✅" : "❌"],
    ["운일 확률 p(순열 1000회)", "—", f(r1.p, 3)], ["5구간 중 이익 구간", "—", `${mw.positive}/${mw.total}`],
    ["채택", "", ok ? "✅ 새 버전 데모 투입" : "❌ 지금 버전 유지"]],
    ok ? "검증 구간·견고성까지 통과 → 새 버전을 데모에 올려 원본과 비교 운용합니다" : res.overfit ? "⚠ 학습 구간만 좋아짐(과최적화) → 채택 안 함" : "개선 없음/불통과 → 지금 버전 유지 (실거래 관문은 그대로)");
  if (ok && s.nearMiss) dropNearMiss(s.name);
  if (ok){
    const ns = await P.addStrategy({spec: {...res.best.spec, name: `${s.name} v${S.latest(res.best.spec.name)?.semver || "+"}`}, market: s.market, exchange: s.exchange, tf, author: lead.name, wf: {is: res.best.wf.is, oos: res.best.wf.oos}, cls: s.cls, mname: s.mname, lane: s.lane});
    post({ch: "demo", kind: "system", text: `🔧 봇 자동개선 버전 데모 투입: ${ns.name} (원본 ${s.name}은 그대로 비교 운용 · 보조지표·위험값 하이퍼옵트)`});
    journal("record", "strategy", ns.id, {from: s.id, loss, bot: true, semver: S.latest(res.best.spec.name)?.semver, phash: specHash(res.best.spec)}, "bot_lead", "봇 자동개선 버전");
    await learnSkill(`${s.name} ${res.lossKo} 자동개선으로 검증 성과 개선 → 채택`, {job: "botopt"});
  }
  pubTo(s.market, "bot", {team: "bot", title: `봇 자동개선: ${ok ? "새 버전 채택" : "유지"}`, text: `${s.name} · ${res.lossKo} · 검증 순손익 ${f(res.base.wf.oos.net_pnl)} → ${f(res.best.wf.oos.net_pnl)} · 운일 확률 ${f(r1.p, 3)}`, spec: res.best.spec, baseSpec: s.spec});
  addNote("bot", `${s.name} 자동개선: ${res.lossKo} → ${ok ? "새 버전 투입" : "유지"} (검증 순손익 ${f(res.base.wf.oos.net_pnl)} → ${f(res.best.wf.oos.net_pnl)}, p=${f(r1.p, 3)})`, "봇자동개선");
  await explain(lead.id, "bot", "봇 자동개선 결과표를 보고 보조지표 길이·문턱값과 위험값(ROI·손절·추적손절·보호장치)이 어떻게 바뀌었는지, 검증 구간에서도 좋아졌는지, 과최적화·운일 가능성은 어떤지 해설한다. 채택 여부는 코드 판정을 따르고, 실거래는 기존 관문·승인을 그대로 거친다.", `봇 ${s.name} · 손실함수 ${res.lossKo}\n보조지표 ${indBefore} → ${indAfter}\n검증 순손익 ${f(res.base.wf.oos.net_pnl)} → ${f(res.best.wf.oos.net_pnl)} · 관문 ${res.best.wf.pass ? "통과" : "불통과"} · 운일 확률 ${f(r1.p, 3)} · 5구간 이익 ${mw.positive}/${mw.total} · 판정 ${ok ? "채택" : "미채택"}`, "아래 자동매매봇 자동개선(하이퍼옵트) 결과를 해설해 줘.");
}

/* ---- 📉 데모 성과 이동 감지 (runcharter 런 차트: 기준 13거래 중앙값, 9연속이면 이동) → 데모거래팀 ---- */
async function driftJob(){
  const RC = await lib("runchart"), P = await import("../nuri-ai/paper.js"), book = await P.loadBook(), rows = [], lead = agentById("trader");
  for (const s of book.strategies.filter(x => x.status === "active")){
    const v = (s.trades || []).map(t => +t.roe || +t.pnl || 0);
    const up = RC.runChart(v, {direction: "above"}), dn = RC.runChart(v, {direction: "below"});
    if (!up.enough){ rows.push([s.name.slice(0, 22), String(v.length), "—", `자료 부족 (${22 - v.length}거래 더)`]); continue; }
    const last = [...up.shifts, ...dn.shifts].sort((a, b) => b.to - a.to)[0];
    rows.push([s.name.slice(0, 22), String(v.length), last ? `${last.oldMedian.toFixed(2)} → ${last.newMedian.toFixed(2)}` : up.median.toFixed(2), last ? `${last.dir} (${last.to + 1}번째 거래)` : "이동 없음"]);
    if (last && last.side > 0 && (s.sizeMul ?? 1) < 1) await P.setMeta(s.id, {sizeMul: 1, sizeWhy: ""}).catch(() => {});   // 회복 이동 → 원래 크기
    if (last && last.side < 0 && last.to >= v.length - 3){ await P.setMeta(s.id, {sizeMul: 0.5, sizeWhy: "런차트 하락 이동"}).catch(() => {}); addTask({team: "demo", title: `성과 악화 감지: ${s.name}`, why: `런 차트 9연속 중앙값 아래 (${last.oldMedian.toFixed(2)} → ${last.newMedian.toFixed(2)}) · 비중 축소·은퇴 검토`, owner: lead.name}); journal("audit", "drift", s.id, {dir: "down", from: last.oldMedian, to: last.newMedian}, "trader", "런 차트 악화"); }
  }
  table("demo", lead.id, "📉 데모 전략 성과 이동 감지 (런 차트: 처음 13거래 중앙값 기준, 9연속 위·아래면 지속 이동)", ["전략", "거래 수", "중앙값", "판정"], rows.length ? rows : [["—", "0", "—", "데모 중인 전략 없음"]], "중앙값과 같은 값은 건너뜀 · 이동이 확인되면 그 9개로 새 중앙값");
  await adaptiveRetrain(P, book, lead);
}
// 적응형 재학습: 데모를 돌면서 신뢰점수가 떨어진 전략을 자동으로 멈추고(은퇴), 매매법 개발팀에 교체 전략 개발을 맡긴다
async function adaptiveRetrain(P, book, lead){
  let linked = {}; try { const L = await import("../nuri-ai/live.js"); linked = L.liveCfg?.().linked || {}; } catch(e){}
  const rows = [], retired = [];
  for (const s of book.strategies.filter(x => x.status === "active" && x.spec)){
    const tr = s.trades || [], n = tr.length, wins = tr.filter(t => (t.pnl ?? t.roe ?? 0) > 0).length;
    const ret = (P.equityOf(s) / 10000 - 1) * 100, wr = n ? wins / n * 100 : 0, pf = s.wf?.oos?.pf ?? null;
    const trust = trustScore({ret, wr, pf, n, robust: s.robust, crossCoin: s.crossCoin});
    const live = !!linked[s.id]?.on;
    // 표본이 충분(10거래 이상)하고 신뢰점수가 30 미만이면 과최적화·성과붕괴로 보고 자동 멈춤. 단 실거래 연결된 건 사람이 결정하도록 멈추지 않고 경고만.
    let act = "유지";
    if (n >= 10 && trust < 30){
      if (live){ act = "⚠ 실거래 중 — 수동 점검"; addTask({team: "demo", title: `실거래 저신뢰 전략 점검: ${s.name}`, why: `신뢰점수 ${trust}로 하락(데모수익 ${pc(ret)}) · 실거래 연결 상태라 자동 중지 대신 사람이 해제 판단`, owner: lead.name}); }
      else {
        s.retiredWhy = `적응형 재학습: 신뢰점수 ${trust}로 하락(데모수익 ${pc(ret)}·${n}거래)`;   // setStatus 저장 전에 설정해야 함께 저장됨
        await P.setStatus(s.id, "retired").catch(() => {});
        act = "🛑 자동 은퇴"; retired.push({s, trust, ret});
        // 같은 시장·결에 맞는 교체 전략을 개발팀에 요청(재학습)
        addTask({team: "dev", title: `교체 전략 개발: ${s.mname || s.market}`, why: `${s.name}가 신뢰점수 ${trust}로 은퇴 — 같은 시장에서 더 견고한 새 전략 필요`, owner: agentById("qa")?.name || lead.name});
      }
    }
    rows.push([s.name.slice(0, 22), String(n), String(trust), live ? "🟢실거래" : "데모", act]);
  }
  if (rows.length) table("demo", lead.id, "🔁 적응형 재학습 — 신뢰점수 기반 자동 점검", ["전략", "거래", "신뢰점수", "구분", "조치"], rows,
    "표본 10거래 이상 + 신뢰점수 30 미만이면 자동 은퇴하고 개발팀에 교체 전략을 요청합니다(실거래 연결분은 자동 중지 대신 수동 점검) · 신뢰점수는 성과+견고성+일반화+표본 종합");
  if (retired.length){ post({ch: "demo", kind: "system", text: `🔁 적응형 재학습: ${retired.map(r => `${r.s.name}(신뢰 ${r.trust})`).join(", ")} 자동 은퇴 → 개발팀에 교체 전략 요청`}); journal("audit", "retrain", retired.map(r => r.s.id).join(","), {count: retired.length}, "trader", "적응형 재학습"); }
}

/* ---- 🏆 전략 콘테스트 (FinStep-AI/ContestTrade 식 내부 경쟁) — 데모 전략을 성과로 겨뤄 순위 → 상위에 비중·실거래 우선권, 하위는 은퇴 검토 ---- */
// 신뢰 점수(0~100): 데모 성과 35 + 견고성 30 + 코인 일반화 20 + 표본 15 을 합쳐 '믿고 돈을 맡길 만한가'를 하나로 매긴다
// 수익만 높고 과최적화(운일확률↑·한 코인만·구간 들쭉날쭉)인 전략은 점수가 깎여 하위로 밀린다
export function trustScore({ret = 0, wr = 0, pf = null, n = 0, robust = null, crossCoin = null}){
  const cl = (lo, hi, v) => Math.max(lo, Math.min(hi, v));
  // A. 데모 성과 (0~35)
  const retN = cl(0, 1, (ret + 10) / 30), wrN = cl(0, 1, (wr - 40) / 30), pfN = pf == null ? 0.4 : cl(0, 1, (pf - 0.8) / 1.7);
  const A = 35 * (0.5 * retN + 0.25 * wrN + 0.25 * pfN);
  // B. 견고성 (0~30) — 저장된 로버스트 지표. 없으면(옛 전략) 중립 12점
  let B;
  if (!robust) B = 12;
  else {
    const pN = robust.p == null ? 0.5 : cl(0, 1, (0.2 - robust.p) / 0.2);
    const mwN = robust.mwTotal ? cl(0, 1, robust.mwPos / robust.mwTotal) : 0.5;
    const sqnN = robust.sqn == null ? 0.4 : cl(0, 1, robust.sqn / 3);
    B = 30 * (robust.ok === false ? 0.5 : 1) * (0.4 * pN + 0.35 * mwN + 0.25 * sqnN);
  }
  // C. 코인 일반화 (0~20) — 개발 코인 외 몇 개 코인에서 수익? 없으면 중립 8점
  const C = !crossCoin || !crossCoin.total ? 8 : 20 * cl(0, 1, crossCoin.profitable / crossCoin.total);
  // D. 표본 신뢰도 (0~15) — 거래가 적으면 운일 수 있어 점수 유보
  const D = 15 * cl(0, 1, n / 25);
  return Math.round(A + B + C + D);
}
const trustGrade = t => t >= 75 ? "A 매우 신뢰" : t >= 60 ? "B 신뢰" : t >= 45 ? "C 보통" : t >= 30 ? "D 주의" : "E 위험";
async function contestJob(){
  const P = await import("../nuri-ai/paper.js"), book = await P.loadBook(), lead = agentById("trader");
  let linked = {}; try { const L = await import("../nuri-ai/live.js"); linked = L.liveCfg?.().linked || {}; } catch(e){}
  const active = book.strategies.filter(s => s.status === "active" && s.spec);
  if (active.length < 2){ post({ch: "demo", kind: "work", agent: lead.id, icon: "🏆", text: `콘테스트하려면 데모 전략이 2개 이상 필요합니다 (지금 ${active.length}개) · 매매법 개발팀이 전략을 더 만들면 열립니다`}); return; }
  const scored = active.map(s => {
    const tr = s.trades || [], n = tr.length, wins = tr.filter(t => (t.pnl ?? t.roe ?? 0) > 0).length;
    const ret = (P.equityOf(s) / 10000 - 1) * 100, wr = n ? wins / n * 100 : 0, pf = s.wf?.oos?.pf ?? null;
    const trust = trustScore({ret, wr, pf, n, robust: s.robust, crossCoin: s.crossCoin});
    const gen = s.crossCoin && s.crossCoin.total ? `${s.crossCoin.profitable}/${s.crossCoin.total}` : "—";
    const rob = s.robust ? (s.robust.mwTotal ? `${s.robust.mwPos}/${s.robust.mwTotal}` : "—") + (s.robust.p != null ? ` p${(+s.robust.p).toFixed(2)}` : "") : "—";
    return {s, ret: +ret.toFixed(2), wr: +wr.toFixed(1), n, pf, trust, gen, rob, live: !!linked[s.id]?.on};
  }).sort((a, b) => b.trust - a.trust);
  const rows = scored.slice(0, 12).map((x, i) => [String(i + 1), x.s.name.slice(0, 24), pc(x.ret), x.wr + "%", String(x.n), x.rob, x.gen, `${x.trust} (${trustGrade(x.trust).split(" ")[0]})`, x.live ? "🟢실거래" : x.trust >= 60 && i === 0 ? "🏆 승격후보" : x.trust < 30 ? "⚠ 은퇴검토" : ""]);
  table("demo", lead.id, `🏆 전략 콘테스트 — 신뢰 점수 리더보드 (${scored.length}개 경쟁)`, ["순위", "전략", "데모수익", "승률", "거래", "견고성", "일반화", "신뢰점수", "상태"], rows,
    "신뢰점수 = 데모성과 35 + 견고성 30 + 코인일반화 20 + 표본 15. 수익만 높고 과최적화면 점수가 깎입니다 · 상위가 실거래 우선권, 30점 미만은 은퇴 검토 · 과거 성과가 미래를 보장하지 않습니다");
  const top = scored[0], weak = scored.filter(x => x.trust < 30 && x.n >= 8);
  addNote("demo", `콘테스트 1위 ${top.s.name} (신뢰 ${top.trust}·${trustGrade(top.trust)}) · 신뢰점수 기준 순위`, "콘테스트");
  // 은퇴 검토: 수익이 나도 신뢰점수가 낮으면(운·과최적화 의심) 후보에 올린다
  for (const w of weak.slice(0, 2)) addTask({team: "demo", title: `콘테스트 저신뢰 전략 은퇴 검토: ${w.s.name}`, why: `신뢰점수 ${w.trust}(${trustGrade(w.trust)}) · 데모수익 ${pc(w.ret)}·일반화 ${w.gen}·견고성 ${w.rob} — 수익이 나도 운·과최적화 의심`, owner: lead.name});
  if (top.trust >= 60 && !top.live) addTask({team: "demo", title: `콘테스트 1위 실거래 승격 검토: ${top.s.name}`, why: `신뢰점수 ${top.trust}(${trustGrade(top.trust)}) · 데모수익 ${pc(top.ret)}·일반화 ${top.gen} — 상위 신뢰 전략에 실거래 우선권`, owner: lead.name});
  await learnSkill(`전략 콘테스트 1위: ${top.s.name} (신뢰 ${top.trust}·${trustGrade(top.trust)})`, {job: "contest"});
  if (hasAI()) await explain(lead.id, "demo", "전략 콘테스트 신뢰점수 리더보드를 보고, 신뢰점수가 무엇을 뜻하는지(성과만이 아니라 견고성·여러 코인 일반화·표본까지 합친 값), 지금 가장 믿을 만한/위험한 전략, 수익은 나도 신뢰점수가 낮아 주의할 전략, 실거래로 올릴 후보를 해설한다. 과거 성과가 미래를 보장하지 않는다는 점을 밝힌다.", tableText(["순위", "전략", "수익", "승률", "거래", "견고성", "일반화", "신뢰점수"], rows.map(r => r.slice(0, 8))), "아래 신뢰점수 리더보드를 해설해 줘.");
}

/* ---- 🧺 앙상블 포트폴리오 — 신뢰점수 상위 전략들을 묶어 '자본을 어떻게 나눌지' 제안(분산 운용) ---- */
async function ensembleJob(){
  const P = await import("../nuri-ai/paper.js"), book = await P.loadBook(), lead = agentById("trader");
  let linked = {}; try { const L = await import("../nuri-ai/live.js"); linked = L.liveCfg?.().linked || {}; } catch(e){}
  const active = book.strategies.filter(s => s.status === "active" && s.spec);
  const scored = active.map(s => {
    const tr = s.trades || [], n = tr.length, wins = tr.filter(t => (t.pnl ?? t.roe ?? 0) > 0).length;
    const ret = (P.equityOf(s) / 10000 - 1) * 100, wr = n ? wins / n * 100 : 0, pf = s.wf?.oos?.pf ?? null;
    const trust = trustScore({ret, wr, pf, n, robust: s.robust, crossCoin: s.crossCoin});
    return {s, market: s.mname || s.market, coin: s.market, ret: +ret.toFixed(2), n, trust, live: !!linked[s.id]?.on};
  });
  const cands = scored.filter(x => x.trust >= 45 && x.n >= 5).sort((a, b) => b.trust - a.trust).slice(0, 8);
  if (cands.length < 2){ post({ch: "demo", kind: "work", agent: lead.id, icon: "🧺", text: `앙상블 포트폴리오를 짜려면 신뢰점수 45 이상·거래 5회 이상 전략이 2개 이상 필요합니다 (지금 ${cands.length}개) · 콘테스트로 전략을 더 키우면 열립니다`}); return; }
  // 신뢰점수 비례로 자본 배분 → 한 전략 쏠림 방지 상한(최대 40%, 전략 수가 적으면 균등배분선까지 완화) → 재정규화
  const CAP = Math.max(0.40, 1 / cands.length + 1e-6);
  let w = cands.map(x => x.trust); const sum = w.reduce((a, b) => a + b, 0) || 1; w = w.map(v => v / sum);
  for (let it = 0; it < 5; it++){
    if (!w.some(v => v > CAP + 1e-9)) break;
    let excess = 0, freeSum = 0;
    w = w.map(v => { if (v > CAP){ excess += v - CAP; return CAP; } freeSum += v; return v; });
    if (freeSum <= 0) break;
    w = w.map(v => v >= CAP ? v : v + excess * (v / freeSum));
  }
  const alloc = cands.map((x, i) => ({...x, weight: w[i]}));
  // 앙상블 비중을 전략에 저장 → 다음 진입 증거금에 곱해진다(균등 대비 0.25~1.5배). 후보에서 빠진 활성 전략은 0.6배
  for (const x of alloc) await P.setMeta(x.s.id, {weightMul: +Math.max(0.25, Math.min(1.5, x.weight * alloc.length)).toFixed(2)}).catch(() => {});
  for (const x of scored.filter(y => !alloc.some(a => a.s.id === y.s.id))) await P.setMeta(x.s.id, {weightMul: 0.6}).catch(() => {});
  const coins = new Set(alloc.map(a => a.coin)), wRet = alloc.reduce((a, x) => a + x.weight * x.ret, 0);
  const rows = alloc.map((x, i) => [String(i + 1), x.s.name.slice(0, 22), x.market, String(x.trust), pc(x.ret), (x.weight * 100).toFixed(0) + "%", x.live ? "🟢실거래" : ""]);
  table("demo", lead.id, `🧺 앙상블 포트폴리오 — 신뢰점수 비례 분산 (${alloc.length}개 전략 · ${coins.size}개 코인)`, ["비중순", "전략", "시장", "신뢰점수", "데모수익", "제안비중", "상태"], rows,
    `신뢰점수가 높을수록 자본을 더 배분(한 전략 최대 ${(CAP * 100).toFixed(0)}%) · 가중 평균 데모수익 ${pc(+wRet.toFixed(2))} · ${coins.size}개 코인 분산${coins.size < alloc.length ? " (같은 코인 중복 있음 — 코인은 함께 움직여 분산 효과 제한)" : ""} · 실거래는 총노출 한도와 함께 쓰세요 · 계산값일 뿐 미래 보장 아님`);
  addNote("demo", `앙상블 포트폴리오: ${alloc.slice(0, 3).map(a => `${a.s.name.slice(0, 12)} ${(a.weight * 100).toFixed(0)}%`).join(", ")}${alloc.length > 3 ? " …" : ""}`, "앙상블");
  if (hasAI()) await explain(lead.id, "demo", "앙상블 포트폴리오 표를 보고, 왜 이렇게 비중을 나눴는지(신뢰점수 비례, 한 전략 쏠림 방지 상한), 코인 분산이 충분한지(코인은 같이 움직이는 경향이 있어 분산 효과가 제한됨), 실거래에 쓸 때 총노출 한도와 어떻게 맞출지 해설한다. 계산값일 뿐 미래를 보장하지 않는다는 점을 밝힌다.", tableText(["비중순", "전략", "시장", "신뢰점수", "데모수익", "제안비중"], rows.map(r => r.slice(0, 6))), "아래 앙상블 포트폴리오 배분을 해설해 줘.");
}

/* ---- 🧮 정직한 현실 점검 — 목표 수익의 실제 도달·파산 확률을 몬테카를로로 솔직히 (희망 회로 금지) ---- */
async function realityJob(text = ""){
  const G = await lib("growth"), lead = agentById("trader");
  // 목표·기간 파싱 (예: "1억", "30일"). 기본 10만원 → 1억 / 30일
  const start = 100000; let target = 100000000, days = 30;
  const mt = String(text).match(/(\d[\d,]*)\s*(억|천만|백만|만원|만|원)/);
  if (mt){ const n = +mt[1].replace(/,/g, ""); const u = mt[2]; target = u === "억" ? n * 1e8 : u === "천만" ? n * 1e7 : u === "백만" ? n * 1e6 : u.startsWith("만") ? n * 1e4 : n; }
  const md = String(text).match(/(\d+)\s*(일|주|달|개월)/);
  if (md){ const n = +md[1], u = md[2]; days = u === "일" ? n : u === "주" ? n * 7 : n * 30; }
  if (!(target > start) || !(days >= 1)){ target = 100000000; days = 30; }
  const base = G.honestGrowth({start, target, days});
  const rows = [2, 10, 25, 50].map(r => { const g = G.honestGrowth({start, target, days, winRate: 0.55, rr: 1.5, tradesPerDay: 3, riskPct: r});
    return [`1회 ${r}%`, `${g.pReach}%`, `${g.pBust >= 30 ? "⚠ " : ""}${g.pBust}%`, "₩" + g.median.toLocaleString(), "₩" + g.p10.toLocaleString() + " ~ ₩" + g.p90.toLocaleString()]; });
  table("hq", lead.id, `🧮 정직한 현실 점검 — ₩${start.toLocaleString()} → ₩${target.toLocaleString()} / ${days}일`,
    ["1회 베팅(위험)", "목표 도달", "파산", "중간 결과", "하위10%~상위10%"], rows,
    `목표까지 매일 복리 ${base.needDaily.toFixed(1)}% 필요 · 좋은 전략(승률 55%·손익비 1.5·1회 기대값 +0.38R)을 가정한 ${base.sims.toLocaleString()}회 시뮬레이션. ` +
    `안전하게(2%) 걸면 목표에 거의 못 가고, 1억 쫓아 크게(50%) 걸면 대부분 파산합니다. ` +
    `자동매매는 돈을 벌어주지 않습니다 — 과최적화를 걸러 '덜 잃게' 돕는 도구일 뿐. 잃어도 되는 돈만, 데모·소액 테스트넷부터.`);
  addNote("hq", `현실 점검: ₩${target.toLocaleString()}/${days}일 — 안전하면 도달 희박, 무리하면 파산 급등`, "정직");
  post({ch: "hq", kind: "system", text: `⚠️ 정직하게: 이 앱은 자동으로 돈 벌어주는 기계가 아닙니다. 과최적화·운 좋은 가짜 전략을 신뢰점수·게이트로 걸러 손실 확률을 낮추는 연구·검증 도구입니다.`});
  if (hasAI()) await explain(lead.id, "hq", "정직한 현실 점검 표를 보고, 왜 '적게 걸면 목표 못 가고 많이 걸면 파산'인지(복리·레버리지·변동성), 자동매매가 돈을 벌어주지 않는다는 점, 잃어도 되는 돈만·데모·소액 테스트넷부터 해야 하는 이유를 솔직하고 단호하게 3~5문장으로 설명한다. 희망적인 말로 포장하지 않는다.", tableText(["1회 베팅", "도달", "파산", "중간"], rows.map(r => r.slice(0, 4))), "아래 현실 점검 결과를 솔직하게 해설해 줘.");
}

/* ---- 🧩 준비된 매매법 프리셋 비교 (io-uty RSI·MACD 아이디어 + 우리 지표 146종) — AI 없이 바로 돌려 비교·승격 ---- */
async function presetJob(){
  const Q = await import("../nuri-ai/quant.js"), P = await import("../nuri-ai/paper.js"), lead = agentById("trader");
  let PRE; try { PRE = (await lib("presets")).PRESETS; } catch(e){ post({ch: "demo", kind: "system", text: "프리셋을 불러오지 못했습니다"}); return; }
  const mk = MARKETS[0];   // 비트코인 선물 4시간봉 (io-uty 는 업비트 1분봉 — 여기선 우리 코인·지표로 일반화)
  let cs; try { cs = await kl(mk.market, mk.tf, 1500); } catch(e){ post({ch: "demo", kind: "system", text: "캔들을 못 받아 프리셋 비교를 건너뜁니다"}); return; }
  const RB = await lib("robust").catch(() => null);
  const st = x => ({ret: +(x?.return_pct ?? 0), dd: +(x?.max_dd_pct ?? 0), win: +(x?.win_rate ?? 0), pf: x?.profit_factor == null ? null : +x.profit_factor, n: x?.n_trades ?? 0});
  const rows = [], results = [];
  for (const pr of PRE){
    try {
      const spec = Q.normalizeSpec({...pr.spec, symbol: mk.market, interval: IV_NAME[mk.tf] || "4h", risk: {...(pr.spec.risk || {}), ...COSTS[mk.cls]}});
      const bt = Q.backtest(spec, cs), wf = Q.walkForward(spec, cs);
      let robust = null;
      if (RB){ const pt = RB.permutationTest(bt.trades.map(t => t.pnl)), mw = RB.multiWindow(Q, spec, cs, 5); robust = {ok: (pt.p == null || pt.p <= 0.1) && (mw.total < 3 || mw.positive >= Math.ceil(mw.total * 0.6)), p: pt.p ?? null, mwPos: mw.positive, mwTotal: mw.total, sqn: null}; }
      const oos = wf.oos || {}, trust = trustScore({ret: +(oos.return_pct ?? 0), wr: +(oos.win_rate ?? 0), pf: oos.profit_factor ?? null, n: oos.n_trades ?? 0, robust});
      results.push({pr, spec, wf, trust, robust});
      rows.push([pr.name, pc(+(bt.stats.return_pct ?? 0)), String(bt.stats.n_trades ?? 0), bt.stats.profit_factor ?? "—", wf.pass ? "✅" : "—", `${trust} ${trustGrade(trust).split(" ")[0]}`]);
    } catch(e){ rows.push([pr.name, "오류", "-", "-", "-", "-"]); }
  }
  results.sort((a, b) => b.trust - a.trust);
  rows.sort((a, b) => (parseInt(b[5]) || 0) - (parseInt(a[5]) || 0));
  table("demo", lead.id, `🧩 준비된 매매법 프리셋 비교 — ${mk.name} ${TF_KO[mk.tf]}봉 (io-uty RSI·MACD 아이디어 + 우리 지표 146종)`,
    ["전략", "수익%", "거래", "손익비", "검증", "신뢰점수"], rows,
    "AI 없이 바로 돌려본 고전 전략. 검증(70/30) 통과 + 신뢰점수 높은 것만 데모로 올립니다 · 전략 조건에 차트 터미널 지표 146종 전부 사용 가능 · 과거 성과가 미래를 보장하지 않음");
  let promoted = 0;
  for (const r of results){
    if (promoted >= 2) break;
    if (r.wf.pass && (!r.robust || r.robust.ok)){
      if ((await P.loadBook()).strategies.some(x => x.status === "active" && x.name === r.spec.name && x.market === mk.market)) continue;   // 이미 데모 중인 프리셋은 다시 올리지 않음
      const s = await P.addStrategy({spec: r.spec, market: mk.market, exchange: mk.exchange, tf: mk.tf, author: "프리셋(io-uty)", wf: {is: st(r.wf.is), oos: st(r.wf.oos)}, cls: mk.cls, mname: mk.name, robust: r.robust, crossCoin: null});
      post({ch: "demo", kind: "system", text: `📈 프리셋 데모 시작: ${s.name} (${mk.name} · 신뢰 ${r.trust} ${trustGrade(r.trust)})`});
      promoted++;
    }
  }
  addNote("demo", `프리셋 비교 ${PRE.length}개 · 데모 승격 ${promoted}개 (1위 ${results[0]?.pr.name} 신뢰 ${results[0]?.trust})`, "프리셋");
}

/* ---- 🧬 생존 경쟁 — 개발자 KPI(성과 못 내면 경고) + 다윈 전략 진화(잘하는 전략 변이→부모보다 나은 후손만 생존) ----
   아이디어: cubexch/ai-fund(KPI 해고) · 0xSanei/darwinia·atlas-gic(다윈 진화). 전부 데모(가상)에서만 — 실자금·실지갑 없음. */
function _stratTrust(P, s){
  const tr = s.trades || [], n = tr.length, wins = tr.filter(t => (t.pnl ?? t.roe ?? 0) > 0).length;
  const ret = (P.equityOf(s) / 10000 - 1) * 100, wr = n ? wins / n * 100 : 0, pf = s.wf?.oos?.pf ?? null;
  return {ret, n, trust: trustScore({ret, wr, pf, n, robust: s.robust, crossCoin: s.crossCoin})};
}
/* ---- 🧬 매매법 진화 (개선 · 수정 · 조합) — 매매법 개발팀 ----
   ① 뉴럴 데스크 매매법(실행 규칙 21종)을 손익비·보유기간 조정 / 필터 추가 / A+B 확인 조합으로 변형 → 앞 70% 선택 + 뒤 30% 검증 통과만 채택
   ② 에이전트 팀 데모 전략(JSON)을 필터 추가 / 손익비 조정 / 두 전략 진입조건 AND 조합 → 워크포워드 통과 + 부모보다 나은 표본외 + 순열검정 p≤0.1 이면 데모 투입
   ③ AI 직원이 결과를 보고 다음 실험(조합·필터)을 제안 → 다음 자체 백테스트에서 검증 */
async function evoJob(){
  const Q = await import("../nuri-ai/quant.js"), P = await import("../nuri-ai/paper.js"), EV = await lib("evolve"), RB = await lib("robust"), lead = agentById("qa") || agentById("dev");
  let N = null; try { N = await import("./neural.js"); } catch(e){}
  fire({kind: "busy", agent: lead, text: "🧬 매매법 개선·수정·조합 실험 중"});
  // ① 뉴럴 매매법 진화
  let nr = null;
  if (N?.evolveNow){ try { nr = await N.evolveNow(); } catch(e){ post({ch: "dev", kind: "system", text: `뉴럴 매매법 진화 실패: ${String(e.message || e).slice(0, 60)}`}); } }
  if (nr) table("dev", lead.id, `🧬 뉴럴 매매법 진화 — 변형 ${nr.tested}개 시험 → 학습구간 통과 ${nr.passedIS} → 채택 ${nr.added.length}`, ["종류", "변형", "원본", "학습(70%)", "검증(30%)"],
    nr.added.length ? nr.added.map(a => [a.gene.src || "변형", a.gene.with ? `${a.gene.base} × ${a.gene.with}` : a.gene.base + (a.gene.filters?.length ? " +" + a.gene.filters.join("+") : "") + (a.gene.rr ? ` 손익비${a.gene.rr}` : ""), a.base.mean + "R", `${a.is.mean}R (${a.is.n})`, `${a.oos.mean}R (${a.oos.n})`]) : [["—", "이번 세대 채택 없음", "", "", ""]],
    `원본 상위: ${(nr.top || []).join(" · ")} · 채택돼도 실전은 최근 20건 기대값 +0.1R 넘어야(워크포워드 선별)`);
  // ② 데모 전략 진화: 수정(필터) · 개선(손익비) · 조합(AND)
  const book = await P.loadBook(), st = x => ({ret: +(x?.return_pct ?? 0), dd: +(x?.max_dd_pct ?? 0), win: +(x?.win_rate ?? 0), pf: x?.profit_factor == null ? null : +x.profit_factor, n: x?.n_trades ?? 0});
  const parents = [...book.strategies.filter(x => x.status === "active" && x.spec).map(x => ({x, t: _stratTrust(P, x).trust})).sort((a, b) => b.t - a.t).slice(0, 3).map(o => o.x), ...nearMissCands().slice(-2)];
  const rows = []; let bred = 0;
  for (const par of parents){
    let cs; try { cs = await kl(par.market, par.tf, 1500); } catch(e){ continue; }
    const oosRet = sp => { try { const w = Q.walkForward(sp, cs); return {w, r: +(w.oos?.return_pct ?? -999)}; } catch(e){ return {w: null, r: -999}; } };
    const base = oosRet(par.spec), kids = [];
    for (const k of Object.keys(EV.SPEC_FILTERS)) kids.push(["수정", EV.addFilter(par.spec, k)]);
    kids.push(["개선", EV.tweakRR(par.spec, 1.5, 1)], ["개선", EV.tweakRR(par.spec, 1, 0.75)]);
    for (const other of parents.filter(o => o !== par && o.spec).slice(0, 3)) kids.push(["조합", EV.combine(par.spec, other.spec)]);
    let best = null;
    for (const [kind, k0] of kids){ if (!k0) continue;
      let child; try { child = Q.normalizeSpec({...k0, symbol: par.market, interval: par.spec.interval}); } catch(e){ continue; }
      const {w, r} = oosRet(child); if (!w?.pass || r <= base.r) continue;
      let bt; try { bt = Q.backtest(child, cs); } catch(e){ continue; }
      const pt = RB.permutationTest(bt.trades.map(t => t.pnl)); if ((pt.p ?? 1) > 0.1) continue;
      if (!best || r > best.r) best = {kind, child, w, r, p: pt.p};
    }
    if (best && bred < 2){
      const ns = await P.addStrategy({spec: best.child, market: par.market, exchange: par.exchange || "binancef", tf: par.tf, author: `진화·${best.kind}(${lead.name})`, wf: {is: st(best.w.is), oos: st(best.w.oos)}, cls: par.cls || "crypto", mname: par.mname || par.market, lane: par.lane || "std", robust: {ok: true, p: best.p}});
      journal("record", "strategy", ns.id, {from: par.id, kind: best.kind, phash: specHash(best.child)}, lead.id, "매매법 진화 → 데모");
      if (par.nearMiss) dropNearMiss(par.name);
      bred++; rows.push([best.kind, String(par.name).slice(0, 22), best.child.name.slice(0, 30), pc(base.r), pc(best.r), "✅ 데모 투입"]);
      post({ch: "demo", kind: "system", text: `🧬 매매법 ${best.kind}: ${best.child.name} — 표본외 ${pc(base.r)} → ${pc(best.r)} · 순열검정 p=${best.p} (데모 시작)`});
    } else rows.push(["—", String(par.name).slice(0, 22), best ? best.child.name.slice(0, 30) : "—", pc(base.r), best ? pc(best.r) : "—", best ? "대기(이번 투입 한도)" : "부모 유지(이긴 변형 없음)"]);
  }
  if (rows.length) table("dev", lead.id, "🧬 데모 전략 개선·수정·조합 — 부모보다 표본외 수익이 높고 검증 통과한 변형만 데모로", ["종류", "부모", "변형", "부모 표본외", "변형 표본외", "결과"], rows,
    "수정 = 필터(ADX·EMA200·거래량·슈퍼트렌드·RSI) 추가 · 개선 = 익절 1.5배 또는 손절 0.75배(20x+ 레버 재역산) · 조합 = 두 전략 진입조건 AND · 워크포워드 통과 + 순열검정 p≤0.1");
  else post({ch: "dev", kind: "work", agent: lead.id, icon: "🧬", text: "진화시킬 데모 전략·근접 후보가 아직 없음 — 뉴럴 매매법 진화만 진행"});
  // ③ AI 직원이 다음 실험 제안 (다음 자체 백테스트에서 검증)
  if (hasAI() && N?.proposeEvo){
    try { const S0 = N.state(), keys = (await import("./strategies.js")).LIB.filter(r => r.tf !== "240").map(r => r.key), FK = Object.keys((await import("./strategies.js")).FILTERS);
      const top = (S0.engine || []).slice(0, 8).map(e => `${e.vkey} ${e.mean}R/${e.n}건`).join(", ");
      const e = await solo(lead, {room: "dev", sys: personaOf(lead, "뉴럴 매매법 성적을 보고 다음에 시험할 조합 또는 필터 추가 실험 2개를 고른다. 이유 한 줄과 JSON 을 쓴다."),
        user: `성적: ${top}
매매법 키: ${keys.join(", ")}
필터: ${FK.join(", ")}
JSON: {"try":[{"base":"키","with":"키(조합일 때)","filters":["필터"]}]}`, maxTokens: 400, json: true});
      const j = pickJSON(e.raw || e.text) || {}; let n = 0;
      for (const g of (j.try || []).slice(0, 2)) if (N.proposeEvo({base: g.base, ...(keys.includes(g.with) && g.with !== g.base ? {with: g.with, win: 3} : {}), ...(Array.isArray(g.filters) ? {filters: g.filters.filter(f => FK.includes(f)).slice(0, 2)} : {})})) n++;
      if (n) post({ch: "dev", kind: "work", agent: lead.id, icon: "🧪", text: `다음 실험 ${n}개 제안 → 다음 자체 백테스트에서 검증(통과해야 채택)`});
    } catch(e){}
  }
  addNote("dev", `매매법 진화: 뉴럴 채택 ${nr?.added?.length ?? 0} · 데모 변형 투입 ${bred}`, "진화");
  fire({kind: "growth"});
}
async function survivalJob(){
  const Q = await import("../nuri-ai/quant.js"), P = await import("../nuri-ai/paper.js"), book = await P.loadBook(), lead = agentById("trader");
  const EV = await lib("evolve");
  const act = book.strategies.filter(s => s.spec);
  // 1) 개발자 KPI (ai-fund 식 성과표)
  const by = {};
  for (const s of act){ const a = s.author || "?", o = by[a] || (by[a] = {author: a, n: 0, live: 0, dead: 0, ts: 0, pnl: 0, pass: 0});
    const t = _stratTrust(P, s); o.n++; o.ts += t.trust; o.pnl += P.equityOf(s) - 10000; if (s.status === "active") o.live++; else o.dead++; if ((s.robust?.ok) !== false && t.trust >= 45) o.pass++; }
  const devs = Object.values(by).map(o => ({...o, avg: o.n ? Math.round(o.ts / o.n) : 0})).sort((a, b) => b.avg - a.avg || b.pnl - a.pnl);
  if (devs.length){
    table("demo", lead.id, "🧬 개발자 KPI — 생존 경쟁 (성과 못 내면 경고·재교육)", ["순위", "개발자", "전략수", "평균 신뢰", "합격(45+)", "데모손익", "상태"],
      devs.map((d, i) => [String(i + 1), d.author, `${d.n}(운용 ${d.live})`, String(d.avg), `${d.pass}/${d.n}`, "₩" + Math.round(d.pnl).toLocaleString(), d.avg >= 55 ? "🏆 우수" : d.avg < 35 ? "⚠ 성과경고" : ""]),
      "평균 신뢰점수·합격률·데모손익 종합. 35 미만은 '성과 경고'(해고 대신 재교육: 더 견고한 전략을 만들도록 과제) · 전부 가상자금 기준");
    for (const d of devs.filter(x => x.avg < 35 && x.n >= 3)) addTask({team: "dev", title: `성과 경고 — ${d.author} 재교육`, why: `담당 전략 평균 신뢰 ${d.avg} · 합격 ${d.pass}/${d.n} — 더 견고한(과최적화 아닌) 전략을 만들도록`, owner: agentById("qa")?.name || lead.name});
  }
  // 2) 다윈 전략 진화 — 상위 전략을 변이시켜 백테스트, 검증 통과 + 부모보다 나은 후손만 데모로 '번식'
  const live = act.filter(s => s.status === "active").map(s => ({s, ..._stratTrust(P, s)})).sort((a, b) => b.trust - a.trust);
  const rows = [], st = x => ({ret: +(x?.return_pct ?? 0), dd: +(x?.max_dd_pct ?? 0), win: +(x?.win_rate ?? 0), pf: x?.profit_factor == null ? null : +x.profit_factor, n: x?.n_trades ?? 0});
  let bred = 0;
  for (const par of live.slice(0, 3)){
    let cs; try { cs = await kl(par.s.market, par.s.tf, 1500); } catch(e){ continue; }
    let win = null;
    for (let i = 0; i < 6; i++){
      let child; try { child = Q.normalizeSpec(EV.mutate(par.s.spec, Date.now() + i * 7919)); } catch(e){ continue; }
      const wf = Q.walkForward(child, cs), bt = Q.backtest(child, cs);
      const ct = trustScore({ret: +(wf.oos?.return_pct ?? 0), wr: +(wf.oos?.win_rate ?? 0), pf: wf.oos?.profit_factor ?? null, n: wf.oos?.n_trades ?? 0, robust: par.s.robust});
      if (wf.pass && ct > par.trust && (!win || ct > win.ct)){ win = {child, wf, bt, ct}; }
    }
    if (win && bred < 2){
      const s = await P.addStrategy({spec: win.child, market: par.s.market, exchange: par.s.exchange, tf: par.s.tf, author: `진화(${par.s.author || "?"})`, wf: {is: st(win.wf.is), oos: st(win.wf.oos)}, cls: par.s.cls, mname: par.s.mname, robust: par.s.robust, crossCoin: par.s.crossCoin});
      post({ch: "demo", kind: "system", text: `🧬 진화 성공: ${s.name} — 부모 신뢰 ${par.trust} → 후손 ${win.ct} (데모 시작)`});
      rows.push([par.s.name.slice(0, 20), String(par.trust), win.child.name.slice(0, 20), String(win.ct), "✅ 번식"]); bred++;
    } else rows.push([par.s.name.slice(0, 20), String(par.trust), "—", "—", "부모 유지(이긴 후손 없음)"]);
  }
  if (rows.length) table("demo", lead.id, "🧬 다윈 전략 진화 — 변이 후손이 부모보다 나으면 번식", ["부모 전략", "부모 신뢰", "후손", "후손 신뢰", "결과"], rows,
    "상위 전략을 지표 기간·위험값·조건을 흔들어 변이시키고, 검증(70/30) 통과 + 부모보다 신뢰 높은 후손만 데모에 올립니다(약자 도태는 적응형 재학습이 담당) · 가상자금 기준");
  addNote("demo", `생존 경쟁: 개발자 ${devs.length}명 · 진화 번식 ${bred}개`, "생존");
}

/* ---- 🕯 패턴 스캐너 (stock-pattern · chart_patterns 규칙) → 차트·캔들 패턴팀 ---- */
async function patternScanJob(){
  const PT = await lib("patterns"), T = await lib("ta_rating"), lead = agentById("pat_lead"), rows = [];
  fire({kind: "busy", agent: lead, text: "🕯 6개 코인 × 1시간·4시간 패턴 스캔 중"});
  for (const c of COINS) for (const tf of ["60", "240"]){
    try {
      const k = (await kl(c.sym, tf, 400)).slice(0, -1);   // 진행 중인 봉 제외 (마감 봉만)
      const found = PT.scan(k);
      { const P0 = readJ("coinPatterns", {}), net = found.reduce((a, p) => a + (p.dir || 0), 0), prev = P0[c.id]; if (tf === "60" || !prev || prev.tf !== "60" || Date.now() - prev.t > 3600e3) { P0[c.id] = {dir: Math.sign(net), net, names: found.map(p => p.name).slice(0, 3), tf, t: Date.now()}; writeJ("coinPatterns", P0); } }   // stock-pattern·chart_patterns → 진입 관문
      if (tf === "60" || found.length) pubTo(c.sym, "pattern" + (tf === "60" ? "" : "4h"), {team: "pattern", title: `차트 패턴 (${TF_KO[tf]}봉)`, text: found.map(p => `${p.name} ${PT.STATE_KO[p.state] || p.state}`).join(" · ") || "뚜렷한 패턴 없음",
        segs: found.flatMap(p => (p.lines || []).map(l => ({a: {t: l.from.t, p: l.from.p}, b: {t: l.to.t, p: l.to.p}, color: p.dir > 0 ? "#26a69a" : p.dir < 0 ? "#ef5350" : "#b2b5be", label: `${p.name} ${l.name}`}))),
        markers: found.flatMap(p => Object.entries(p.points || {}).map(([nm, q]) => ({t: q.t, price: q.p, text: `${p.name.slice(0, 6)} ${nm}`, dir: p.dir || 0, color: "#ffb300"}))),
        lines: found.filter(p => p.trigger).flatMap(p => [{price: p.trigger, label: `${p.name} 돌파 기준`, color: "#ffb300", style: 2}, ...(p.target ? [{price: p.target, label: `${p.name} 목표`, color: "#ffd54f", style: 1}] : [])])});
      for (const p of found) rows.push([c.ko, TF_KO[tf], p.name, p.dir > 0 ? "상승" : p.dir < 0 ? "하락" : "중립", PT.STATE_KO[p.state] || p.state, p.trigger ? fx(p.trigger) : "—", p.target ? fx(p.target) : "—", p.invalid ? fx(p.invalid) : "—", p.why]);
      for (const cd of T.candles(k).filter(x => x.strength >= 0.5 && x.dir)) rows.push([c.ko, TF_KO[tf], "캔들: " + cd.name, cd.dir > 0 ? "상승" : "하락", "마지막 봉", "—", "—", "—", `강도 ${cd.strength.toFixed(2)} · 직전 5봉 추세 ${cd.trend > 0 ? "상승" : cd.trend < 0 ? "하락" : "횡보"}`]);
    } catch(e){}
  }
  table("pattern", lead.id, "🕯 패턴 스캐너 (마감 봉만 · 피벗 좌우 6봉 · 허용오차 = 봉 길이 중앙값)", ["코인", "봉", "패턴", "방향", "상태", "돌파 기준", "목표", "무효", "근거"], rows.slice(0, 30), rows.length ? "형성 중 → 돌파 → 목표/실패 · 패턴은 확률일 뿐" : "지금 뚜렷한 패턴 없음");
  const hot = rows.filter(r => /돌파|목표/.test(r[4]));
  if (hot.length) addNote("pattern", hot.slice(0, 4).map(r => `${r[0]} ${r[1]} ${r[2]} ${r[4]}`).join(" · "), "스캐너");
  if (rows.length) await explain(lead.id, "pattern", "패턴 스캐너 결과에서 가장 의미 있는 패턴(특히 막 돌파한 것)과 목표·무효 가격, 신뢰도를 해설한다.", tableText(["코인", "봉", "패턴", "방향", "상태", "돌파", "목표", "무효", "근거"], rows.slice(0, 16)), "아래 차트 패턴 스캔 결과를 해설해 줘.");
}

/* ---- 🧠 알파 팩터 순위 (vnpy Alpha158 계열 · 횡단면 견고 z점수) → 머신러닝·딥러닝팀 ---- */
async function alphaJob(){
  const AL = await lib("alpha"), a = agentById("ml"), by = {}, raw = {};
  fire({kind: "busy", agent: a, text: "🧠 6개 코인 알파 팩터 계산 중"});
  for (const c of COINS){ try { const k = await kl(c.sym, "60", 200); by[c.id] = AL.factors(k); raw[c.id] = k; } catch(e){} }
  const z = AL.crossRank(by), rows = Object.keys(by).map(id => { const c = COINS.find(x => x.id === id), zz = z[id] || {}, f = by[id]; return {c, score: AL.composite(zz), zz, f}; }).sort((x, y) => y.score - x.score);
  writeJ("coinAlpha", Object.fromEntries(rows.map((r, i) => [r.c.id, {score: +r.score.toFixed(3), rank: i + 1, n: rows.length, t: Date.now()}])));   // vnpy Alpha158 순위 → 진입 관문
  table("ml", a.id, "🧠 알파 팩터 순위 (1시간봉 · vnpy Alpha158 계열 · 코인끼리 견고 z점수)", ["순위", "코인", "합성 점수", "5봉 모멘텀", "20봉 기울기", "RSV20", "변동성20", "거래량-가격 상관20"],
    rows.map((r, i) => [String(i + 1), r.c.ko, r.score.toFixed(2), pc((1 / r.f.ROC5 - 1) * 100), (r.f.BETA20 * 100).toFixed(3) + "%/봉", r.f.RSV20.toFixed(2), (r.f.STD20 * 100).toFixed(2) + "%", r.f.CORR20.toFixed(2)]), "합성 = 모멘텀 + 기울기 + RSV − 변동성 (순위는 상대 비교일 뿐, 예측 보장 아님)");
  addNote("ml", `알파 순위: ${rows.map(r => r.c.ko).join(" > ")}`, "알파");
}

/* ---- 🧠 자체 AI 데스크 (GHCoinAI) — 외부 키 없이 앱 안에서 도는 앙상블로 코인 방향·확신도 순위.
       아이디어: TLSRUF/ai-trader-team(합의) · jnMetaCode/agency-agents-ko(역할) · anthropics/claude-cookbooks(앙상블)
       · anthropics/financial-services(리스크·확신도) · continuedev/continue(여러 모델 합치기). 판단만 하고 주문은 live.js 만 낸다. ---- */
async function selfaiJob(){
  const AL = await lib("alpha"), SELF = await lib("selfai"), lead = agentById("selfai_lead");
  fire({kind: "busy", agent: lead, text: "🧠 자체 AI 앙상블 — 6개 코인 방향·확신도 계산 중"});
  const byCoin = {}, cand = {};
  for (const c of COINS){ try { const k = await kl(c.sym, "60", 260); cand[c.id] = k; byCoin[c.id] = AL.factors(k); } catch(e){} }
  const z = AL.crossRank(byCoin);   // 코인끼리 비교한 알파 z점수 (횡단면)
  const rows = [];
  for (const c of COINS){
    const k60 = cand[c.id]; if (!k60) continue;
    let k240 = null; try { k240 = await kl(c.sym, "240", 260); } catch(e){}
    const alpha = AL.composite(z[c.id] || {});
    const j = await SELF.analyze(k240 ? {"60": k60, "240": k240} : {"60": k60}, {alpha});
    rows.push({c, j, k60});
  }
  if (!rows.length){ post({ch: "selfai", kind: "work", agent: lead.id, icon: "🧠", text: "시세를 받지 못해 자체 AI 판단을 내지 못했습니다 (잠시 뒤 다시 시도)"}); return; }
  rows.sort((a, b) => b.j.confidence - a.j.confidence || Math.abs(b.j.score) - Math.abs(a.j.score));
  writeJ("coinSelfAI", Object.fromEntries(rows.map(r => [r.c.id, {dir: r.j.dir, conf: r.j.confidence, score: +(+r.j.score).toFixed(2), t: Date.now()}])));   // 자체 AI 앙상블(claude-cookbooks·bitoracle 0.6 기준) → 진입 관문
  // 1위 코인은 ML(walk-forward) + (설정 시) 외부 LLM API 의견까지 더해 정밀 재판단
  const top = rows[0];
  let deep = null, aiOp = null, plan = null;
  try {
    const ML = await import("../nuri-ai/ml.js");
    const res = ML.walkForwardML(top.k60, {model: "logreg", horizon: 1, trainBars: 800, testBars: 150, maxFolds: 4});
    const prob = res.prob?.at(-1);
    if (prob != null){ top.j = SELF.fuse({...top.j.inputs, ml: {prob, edge: res.edge}}); top.ml = {prob, edge: res.edge}; deep = {coin: top.c, edge: res.edge}; }
  } catch(e){}
  // 외부 AI 연동: 키가 연결되고(끄지 않았으면) LLM 에게 방향·확신도 의견을 받아 한 표로 반영
  if (selfaiExternalOn()){
    aiOp = await aiOpinion(top.c, top.j).catch(() => null);
    if (aiOp) top.j = SELF.fuse({...top.j.inputs, ai: {score: aiOp.score, confidence: aiOp.confidence}});
  }
  // 자체 감정(시장 심리)도 한 표로
  const sent = marketSentiment();
  if (sent) top.j = SELF.fuse({...top.j.inputs, sent: {polarity: sent.polarity, score: sent.score}});
  // 이식한 trading_rigor(ai-trader-team)로 예시 계획(손절 1.5×ATR·목표 3R·계좌 10,000 1% 리스크) 계산
  try {
    const R = await lib("rigor"), CB = await import("./combo.js"), a = await CB.analyzeTF(top.k60);
    if (top.j.dir !== 0 && a.price > 0 && a.atr > 0){
      const entry = a.price, stop = top.j.dir > 0 ? entry - 1.5 * a.atr : entry + 1.5 * a.atr, target = top.j.dir > 0 ? entry + 4.5 * a.atr : entry - 4.5 * a.atr;
      const rr = R.riskReward(entry, stop, target), ps = R.positionSize(10000, 1, entry, stop);
      plan = `예시 계획(${top.c.ko} ${top.j.dir > 0 ? "롱" : "숏"} · 계좌 10,000·1% 리스크): 진입 ${fx(entry)} · 손절 ${fx(stop)}(1.5×ATR) · 목표 ${fx(target)} · 손익비 ${rr.risk_reward_ratio} · 수량 ${ps.shares}(명목 ${ps.position_value})`;
    }
  } catch(e){}
  table("selfai", lead.id, "🧠 자체 AI 데스크 — 방향·확신도 순위 (앙상블: 기술 평점·멀티 시간대·ML·알파" + (aiOp ? "·외부 AI" : "") + ")", ["순위", "코인", "방향", "점수", "확신도", "합의", "근거(신호별)"],
    rows.map((r, i) => [String(i + 1), r.c.ko, r.j.label, (r.j.score >= 0 ? "+" : "") + r.j.score.toFixed(2), r.j.confidence + "%", Math.round(r.j.agree * 100) + "%", r.j.parts.map(p => `${p.name} ${p.v >= 0 ? "+" : ""}${p.v.toFixed(2)}`).join(" · ") || "—"]),
    `확신도는 신호 크기 + 신호 간 합의로 매긴 0~95 참고값입니다. 자체 AI 는 판단만 하고, 실제 주문은 사용자가 켠 전략만 실거래 화면의 한도·승인 안에서 냅니다.${deep ? ` · 1위는 ML(${deep.edge === "edge" ? "우위 있음" : deep.edge === "weak" ? "약함" : "우위 없음"})` : ""}${aiOp ? ` · 외부 AI 의견 반영(확신 ${aiOp.confidence}%)` : " · 외부 AI 꺼짐(설정에서 켜면 LLM 의견도 한 표로 반영)"}${plan ? "\n" + plan : ""}`);
  addNote("selfai", `자체 AI 1위 ${top.c.ko} ${top.j.label} (확신도 ${top.j.confidence}%) · 순위 ${rows.map(r => r.c.ko).join(" > ")}${aiOp ? " · 외부 AI 반영" : ""}`, "자체AI");
  // 예측 기록(24시간 뒤 자동 채점) — 적중률·캘리브레이션에 쌓인다
  try { const T = await trackerOf(); await T.settle(trackPrice); for (const r of rows) T.record({source: "selfai", coin: r.c.id, ko: r.c.ko, dir: r.j.dir, confidence: r.j.confidence, price: r.k60.at(-1)?.c, horizonMs: 24 * 3600e3}); } catch(e){}
  await learnSkill(`${top.c.ko} 자체 AI ${top.j.label} (확신 ${top.j.confidence}%): ${top.j.reasons[0] || ""}`, {job: "selfai"});
  pubTo(top.c.sym, "selfai", {team: "selfai", title: `자체 AI: ${top.c.ko} ${top.j.label} (${top.j.confidence}%)`, text: SELF.summary(top.j)});
  await explain(lead.id, "selfai", "자체 AI 앙상블 순위표를 보고 확신도가 높은 코인과 어떤 신호(기술 평점·멀티 시간대·ML·알파)가 합의했는지, 신호가 엇갈려 중립인 코인은 왜 그런지 해설한다. 확신도는 참고값이고 주문은 승인·한도 안에서만 나간다는 점을 밝힌다.", tableText(["순위", "코인", "방향", "점수", "확신도", "근거"], rows.map((r, i) => [String(i + 1), r.c.ko, r.j.label, r.j.score.toFixed(2), r.j.confidence + "%", r.j.reasons.join(" / ")])), "아래 자체 AI 앙상블 순위를 해설해 줘.");
}
// 한 코인의 자체 AI 판단 (봇 조종판·차트 터미널이 호출) — window.ghCoinSelfAI 로도 노출
export async function selfAIFor(sym, {tfs = ["60", "240"]} = {}){
  const SELF = await lib("selfai"), by = {};
  for (const tf of tfs){ try { by[tf] = await kl(sym, tf, 260); } catch(e){} }
  return SELF.analyze(by, {});
}
// 단타/스윙 포지션 추천 — 매매법을 안 정해도 바로 쓸 참고 포지션. 자체 AI 방향·확신 + ATR 손절·익절 + 손익비(rigor).
//   style "scalp"(단타, 5·15분 · 손절 1.2×ATR · 1.5R) / "swing"(스윙, 4시간·일 · 손절 1.8×ATR · 3R)
export async function positionFor(sym, style = "swing"){
  const SELF = await lib("selfai"), R = await lib("rigor"), CB = await import("./combo.js");
  const tfs = style === "scalp" ? ["5", "15"] : ["240", "D"], by = {};
  for (const tf of tfs){ try { by[tf] = await kl(sym, tf, 260); } catch(e){} }
  const prim = by[tfs[0]]; if (!prim?.length) return null;
  const j = await SELF.analyze(by, {});
  let price = prim.at(-1).c, atr = 0;
  try { const a = await CB.analyzeTF(prim); if (a.price > 0) price = a.price; atr = a.atr || 0; } catch(e){}
  const base = {style, styleKo: style === "scalp" ? "단타" : "스윙", dir: j.dir, label: j.label, confidence: j.confidence, why: j.reasons.join(" / "), tfs, price};
  if (j.dir === 0 || !(atr > 0)) return base;
  const slM = style === "scalp" ? 1.2 : 1.8, rM = style === "scalp" ? 1.5 : 3;
  const entry = price, sl = j.dir > 0 ? entry - slM * atr : entry + slM * atr, tp = j.dir > 0 ? entry + slM * rM * atr : entry - slM * rM * atr;
  let rr = rM; try { rr = R.riskReward(entry, sl, tp).risk_reward_ratio; } catch(e){}
  return {...base, entry, sl, tp, rr, atr};
}
// 두 스타일 다 (코인 AI 봇·UI·window 에서 호출)
export async function positionsFor(sym){ return {scalp: await positionFor(sym, "scalp").catch(() => null), swing: await positionFor(sym, "swing").catch(() => null)}; }
// 진입 타점팀: 코인 하나의 단타·스윙 포지션을 표로
async function posJob(){
  const lead = agentById("strat"), named = userNote && COINS.find(c => new RegExp(`${c.ko}|${c.sym.replace("USDT", "")}`, "i").test(userNote));
  const c = named || COINS[rot("coinPos", COINS.length)];
  fire({kind: "busy", agent: lead, text: `🎯 ${c.ko} 단타·스윙 포지션 계산 중`});
  const {scalp, swing} = await positionsFor(c.sym);
  const dirKo = p => !p ? "자료없음" : p.dir > 0 ? "롱" : p.dir < 0 ? "숏" : "관망";
  const row = (p, nm) => p && p.dir !== 0 ? [nm, dirKo(p), fx(p.entry), fx(p.sl), fx(p.tp), String(p.rr), p.confidence + "%"] : [nm, dirKo(p), "-", "-", "-", "-", p ? p.confidence + "%" : "-"];
  table("entry", lead.id, `🎯 ${c.ko} 포지션 추천 (자체 AI 방향 + ATR 손절·익절)`, ["구분", "방향", "진입", "손절", "익절", "손익비", "확신"],
    [row(scalp, "단타 (5·15분)"), row(swing, "스윙 (4시간·일)")],
    "매매법을 안 정해도 바로 쓸 참고 포지션입니다 · 계산값일 뿐 매매 권유 아님 · 실제 주문은 사용자 승인·한도 안에서만 나갑니다");
  addNote("entry", `${c.ko} 단타 ${dirKo(scalp)} · 스윙 ${dirKo(swing)}`, "포지션");
  // 예측 기록 (단타 6시간·스윙 3일 뒤 자동 채점)
  try { const T = await trackerOf(); for (const [p, h] of [[scalp, 6 * 3600e3], [swing, 3 * 864e5]]) if (p && p.dir !== 0 && p.price > 0) T.record({source: p.styleKo, coin: c.id, ko: c.ko, dir: p.dir, confidence: p.confidence, price: p.price, horizonMs: h}); } catch(e){}
  await learnSkill(`${c.ko} 포지션: 단타 ${dirKo(scalp)}(확신 ${scalp?.confidence ?? "?"}%) · 스윙 ${dirKo(swing)}(확신 ${swing?.confidence ?? "?"}%)`, {job: "pos"});
  if (hasAI()) await explain(lead.id, "entry", "단타·스윙 포지션 추천 표를 보고, 지금 단타가 나은지 스윙이 나은지, 두 시간대 방향이 엇갈리면 어떻게 봐야 하는지, 손절·익절·손익비를 어떻게 지킬지 해설한다. 참고용이고 주문은 승인·한도 안에서만 나간다는 점을 밝힌다.",
    `${c.ko} 현재가 ${fx(scalp?.price || swing?.price)}\n단타(5·15분): ${dirKo(scalp)} 확신 ${scalp?.confidence ?? "?"}%${scalp?.entry ? ` · 진입 ${fx(scalp.entry)} 손절 ${fx(scalp.sl)} 익절 ${fx(scalp.tp)} (손익비 ${scalp.rr})` : ""} · ${scalp?.why || ""}\n스윙(4시간·일): ${dirKo(swing)} 확신 ${swing?.confidence ?? "?"}%${swing?.entry ? ` · 진입 ${fx(swing.entry)} 손절 ${fx(swing.sl)} 익절 ${fx(swing.tp)} (손익비 ${swing.rr})` : ""} · ${swing?.why || ""}`, "아래 단타·스윙 포지션 추천을 해설해 줘.");
}
// 외부 AI 연동 on/off — 키가 연결돼 있고 사용자가 끄지 않았으면 켜짐(기본). 설정에서 토글.
const hasAIKey = () => Object.keys(PROVIDERS).some(id => settings.keys?.[id]) || settings.brain === "local" || settings.brain === "ollama";
export const selfaiExternalOn = () => hasAIKey() && officeCfg().selfaiExternal !== false;
export function setSelfaiExternal(on){ setOffice({selfaiExternal: !!on}); return selfaiExternalOn(); }
// 외부 LLM API 에게 한 코인의 방향·확신도 의견을 받아 자체 AI 앙상블의 '한 표'로 쓴다 (엄격 JSON)
async function aiOpinion(coin, j){
  const sys = "너는 단기 코인 선물 트레이더다. 아래 자체 지표 요약만 참고해 다음 수 시간~하루 방향을 판단한다. 반드시 JSON 한 줄만 출력: {\"direction\":\"long|short|neutral\",\"confidence\":0-100,\"reason\":\"25자 이내\"}. 다른 말 금지.";
  const user = `코인: ${coin.ko}(${coin.sym})\n자체 신호 요약: ${j.reasons.join(" / ")}\n현재 자체 점수 ${j.score} 확신도 ${j.confidence}%`;
  const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), 25000);
  let raw = "";
  try { await brainStream({messages: [{role: "system", content: sys}, {role: "user", content: user}], role: "general", maxTokens: 120, temperature: 0.2, noThink: true, signal: ctl.signal, onContent: d => raw += d}); }
  finally { clearTimeout(t); }
  const m = splitThink(raw).body.match(/\{[\s\S]*\}/); if (!m) return null;
  let o; try { o = JSON.parse(m[0]); } catch(e){ return null; }
  const dir = /long|롱|매수|상승/i.test(o.direction) ? 1 : /short|숏|매도|하락/i.test(o.direction) ? -1 : 0;
  const conf = Math.max(0, Math.min(100, Number(o.confidence) || 0));
  return {score: dir * (0.4 + 0.6 * conf / 100), confidence: conf, direction: o.direction, reason: String(o.reason || "").slice(0, 40)};
}

/* ---- 🧭 리서치 플래너 (ARTEX 의 planner/worker + 공유 todolist/보드 설계를 '공격 기능 없이' 트레이딩 리서치에 이식) ----
   planner 가 상태(코인·전략·관문·경보·최근 보드)를 보고 '지금 할 일 목록'을 만들고, 선행조건을 지켜 최우선 의도 하나를
   골라 기존 job(워커)으로 실행한 뒤, 결과를 공유 보드에 기록한다. 정찰·침투·공격 요소는 전혀 없다. ---- */
const lsStore = () => ({get: (k, d) => readJ(k, d), set: (k, v) => writeJ(k, v)});
// 예측 적중률 추적 (lib/track.js) — 자체 AI·단타/스윙 예측을 기록하고 horizon 뒤 현재가로 자동 채점
const trackerOf = async () => (await lib("track")).makeTracker(lsStore());
const trackPrice = async coin => { const c = COINS.find(x => x.id === coin || x.sym === coin); if (!c) return null; try { return (await kl(c.sym, "60", 3)).at(-1).c; } catch(e){ return null; } };
export async function predictionStats(source){ try { return (await trackerOf()).stats(source); } catch(e){ return null; } }
// 성과 대시보드 데이터 — 데모 전략 손익·승률·전략별 기여 + 예측 적중률 + 시장 심리 + 실거래 연결 (한눈에)
export async function performanceDashboard(){
  const P = await import("../nuri-ai/paper.js"), book = await P.loadBook().catch(() => ({strategies: []})), active = (book.strategies || []).filter(s => s.status === "active");
  const perStrat = active.map(s => {
    const tr = s.trades || [], n = tr.length, wins = tr.filter(t => (t.pnl ?? t.roe ?? 0) > 0).length, eq = P.equityOf(s);
    const ret = +((eq / 10000 - 1) * 100).toFixed(2), wr = n ? +(wins / n * 100).toFixed(1) : 0;
    return {id: s.id, name: s.name, market: s.mname || s.market, tf: s.tf, ret, pnl: +(eq - 10000).toFixed(0), n, wr, days: Math.floor((Date.now() - (s.created || Date.now())) / 864e5), bot: /^🤖/.test(s.name),
      trust: trustScore({ret, wr, pf: s.wf?.oos?.pf ?? null, n, robust: s.robust, crossCoin: s.crossCoin})};
  }).sort((a, b) => b.ret - a.ret);
  const totalPnl = perStrat.reduce((s, x) => s + x.pnl, 0), base = active.length * 10000;
  const allTr = active.flatMap(s => s.trades || []), allWins = allTr.filter(t => (t.pnl ?? t.roe ?? 0) > 0).length;
  let acc = null; try { acc = (await trackerOf()).stats(); } catch(e){}
  let live = 0; try { const L = await import("../nuri-ai/live.js"); live = Object.values(L.liveCfg?.().linked || {}).filter(v => v?.on).length; } catch(e){}
  const sent = marketSentiment();
  return {nActive: active.length, totalPnl: +totalPnl.toFixed(0), totalRetPct: base ? +(totalPnl / base * 100).toFixed(2) : 0, trades: allTr.length, winRate: allTr.length ? +(allWins / allTr.length * 100).toFixed(1) : 0,
    best: perStrat[0] || null, worst: perStrat.at(-1) || null, perStrat, accuracy: acc && acc.n ? {n: acc.n, winRate: acc.winRate} : null, sentiment: sent ? {score: sent.score, verdict: sent.verdict} : null, liveLinked: live};
}
async function dashboardJob(){
  const d = await performanceDashboard(), lead = agentById("lead");
  if (!d.nActive){ post({ch: "hq", kind: "work", agent: lead.id, icon: "📊", text: "아직 데모 전략이 없어 성과 대시보드가 비어 있습니다 · 매매법 개발팀이 전략을 만들면 채워집니다"}); return; }
  table("hq", lead.id, `📊 성과 대시보드 — 데모 전략 ${d.nActive}개 (가상 10,000/전략)`, ["항목", "값"], [
    ["총 가상손익", `${d.totalPnl >= 0 ? "+" : ""}${d.totalPnl.toLocaleString("ko-KR")} USDT (${pc(d.totalRetPct)})`],
    ["전체 거래·승률", `${d.trades}건 · ${d.winRate}%`],
    ["최고 전략", d.best ? `${d.best.name} (${pc(d.best.ret)})` : "-"],
    ["최저 전략", d.worst ? `${d.worst.name} (${pc(d.worst.ret)})` : "-"],
    ["예측 적중률", d.accuracy ? `${d.accuracy.winRate}% (${d.accuracy.n}건 채점)` : "아직 채점 전(열린 예측 쌓이는 중)"],
    ["시장 심리", d.sentiment ? `${d.sentiment.score}/100 (${d.sentiment.verdict})` : "-"],
    ["실거래 연결", `${d.liveLinked}개`]], "과거 성과가 미래 수익을 보장하지 않습니다 · 실제 주문은 승인·한도 안에서만");
  table("hq", lead.id, "📊 전략별 성과 (데모 수익순)", ["순위", "전략", "시장", "데모수익", "승률", "거래", "신뢰점수", "운용일"], d.perStrat.slice(0, 12).map((x, i) => [String(i + 1), x.name.slice(0, 24), x.market, pc(x.ret), x.wr + "%", String(x.n), String(x.trust ?? "—"), x.days + "일"]), "데모수익순 · 신뢰점수는 성과+견고성+일반화+표본을 합친 값(콘테스트 리더보드와 동일) · 상위·고신뢰가 실거래 우선권");
  addNote("hq", `성과 대시보드: 총 ${pc(d.totalRetPct)} · 승률 ${d.winRate}% · 전략 ${d.nActive}개 · 적중률 ${d.accuracy ? d.accuracy.winRate + "%" : "집계중"}`, "대시보드");
  await learnSkill(`성과: 데모 총 ${pc(d.totalRetPct)}·승률 ${d.winRate}% · 최고 ${d.best?.name}(${pc(d.best?.ret)})`, {job: "report"});
}
// 예측 적중률·캘리브레이션 (CEO실에서 QA가 보고) — 확신도가 실제 적중과 얼마나 맞는지
async function trackJob(){
  const T = await trackerOf(), lead = agentById("qae") || agentById("lead");
  await T.settle(trackPrice);
  const overall = T.stats(), srcs = T.bySource();
  if (!overall.n){ post({ch: "hq", kind: "work", agent: lead.id, icon: "🎯", text: `아직 채점된 예측이 없습니다 · 열린 예측 ${overall.open}개 (horizon 지나면 자동 채점됩니다)`}); return; }
  table("hq", lead.id, `🎯 예측 적중률·캘리브레이션 (채점 ${overall.n}건 · 전체 승률 ${overall.winRate}%)`, ["확신도 구간", "예측 수", "평균 확신", "실제 적중"],
    overall.bands.filter(b => b.n).map(b => [b.band, b.n + "건", b.avgConf + "%", b.rate + "%"]), "'평균 확신'과 '실제 적중'이 가까울수록 잘 보정된 예측입니다 · 과거 성과가 미래를 보장하지 않습니다");
  if (srcs.length) table("hq", lead.id, "🎯 예측 소스별 승률 (뭐가 더 맞나)", ["소스", "채점", "승률"], srcs.map(s => [s.source, s.n + "건", s.winRate + "%"]), "자체 AI·단타·스윙 중 실제로 잘 맞는 것을 신뢰에 반영");
  addNote("hq", `예측 적중률 전체 ${overall.winRate}% (${overall.n}건 채점) · ${srcs.map(s => `${s.source} ${s.winRate}%`).join(" · ")}`, "적중률");
  await learnSkill(`예측 적중률: 전체 ${overall.winRate}% · ${srcs.map(s => `${s.source} ${s.winRate}%`).join(", ")}`, {job: "track"});
}
// 전략 파라미터 해시 (감사 로그용): 같은 전략이라도 지표 길이·문턱값·위험값이 바뀌면 해시가 바뀐다 → 어느 버전이 낸 신호인지 추적
const specHash = o => { try { const s = JSON.stringify(o); let h = 5381; for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) >>> 0; return h.toString(36); } catch(e){ return ""; } };
// hermes-agent 식 경험 학습 루프: 리서치하며 배운 교훈을 쌓고(강화), 모든 에이전트 프롬프트에 넣어 재사용한다 (lib/lessons.js)
async function learnSkill(text, {job = "", ok = true} = {}){ try { const M = await lib("lessons"); return M.makeLessons(lsStore()).learn(text, {job, ok}); } catch(e){ return null; } }
function topSkills(n = 6){ const l = readJ("coinLessons", []); if (!Array.isArray(l) || !l.length) return []; return [...l].sort((a, b) => (b.uses * (0.5 + 0.5 * (b.conf || 0))) - (a.uses * (0.5 + 0.5 * (a.conf || 0)))).slice(0, n); }
const skillsText = () => { const t = topSkills(5); return t.length ? `우리 팀이 경험에서 배운 것(반복될수록 강화됨 · 참고): ${t.map(x => x.text).join(" / ")}\n` : ""; };
export async function learnedSkills(n = 20){ try { const M = await lib("lessons"); return M.makeLessons(lsStore()).top(n); } catch(e){ return []; } }
async function plannerJob(){
  const P = await lib("planner"), B = await lib("board"), PB = await import("../nuri-ai/paper.js"), board = B.makeBoard(lsStore());
  let book = {strategies: []}; try { book = await PB.loadBook(); } catch(e){}
  let L = null; try { L = await import("../nuri-ai/live.js"); } catch(e){}
  const cfg = L?.liveCfg?.() || {linked: {}};
  const strategies = (book.strategies || []).map(s => ({id: s.id, name: s.name, status: s.status, isBot: /^🤖/.test(s.name), gateEligible: L?.gateFor ? L.gateFor(s).eligible : false, live: !!cfg.linked?.[s.id]?.on, days: Math.floor((Date.now() - (s.created || Date.now())) / 864e5), trades: (s.trades || []).length}));
  const alerts = backlog().filter(t => t.status !== "done" && /악화|이동|감지/.test(t.title)).slice(0, 3).map(t => ({target: t.title, targetName: t.title, kind: "성과 악화"}));
  const state = {coins: COINS.map(c => ({id: c.id, ko: c.ko, sym: c.sym})), strategies, alerts, recent: board.recentIntents()};
  const todo = P.planTodolist(state);
  table("hq", "lead", "🧭 리서치 플래너 — 지금 할 일 목록 (todolist · 우선순위순)", ["#", "의도", "대상", "선행조건", "근거", "우선"],
    todo.slice(0, 8).map((it, i) => [String(i + 1), JOB_KO[it.job] || it.job, it.targetName || "전체", (it.deps || []).length ? it.deps.join(",") : "—", it.why, String(it.prio)]),
    "ARTEX 의 planner/worker 설계를 공격 기능 없이 트레이딩 리서치에만 적용 · 선행조건을 지키고 중복을 피해 다음 할 일을 고릅니다");
  const pick = P.pickNext(state);
  if (!pick){ post({ch: "hq", kind: "system", text: "플래너: 지금 실행할 리서치 의도가 없습니다"}); return; }
  userNote = pick.target ? (COINS.find(c => c.sym === pick.target)?.ko || "") : "";
  post({ch: JOB_TEAM[pick.job] || "hq", kind: "work", agent: TEAM_LEAD[JOB_TEAM[pick.job]] || "lead", icon: "🧭", text: `플래너가 '${JOB_KO[pick.job] || pick.job}'${pick.targetName ? ` · ${pick.targetName}` : ""} 를 워커에게 배정`});
  const fn = JOB_FN()[pick.job];
  try { if (fn) await fn(); } catch(e){ post({ch: "hq", kind: "system", text: `플래너 워커 오류: ${String(e.message || e).slice(0, 100)}`}); }
  const note = teamNotes(JOB_TEAM[pick.job] || "hq").slice(-1)[0];
  board.add({intent: pick.id, job: pick.job, target: pick.target, targetName: pick.targetName, kind: "발견", text: note?.text || `${JOB_KO[pick.job] || pick.job} 수행`});
  if (note?.text) await learnSkill(`${pick.targetName || JOB_KO[pick.job] || pick.job}: ${note.text}`, {job: pick.job});
  addNote("hq", `플래너: ${JOB_KO[pick.job] || pick.job}${pick.targetName ? ` · ${pick.targetName}` : ""} 실행 · 공유 보드 ${board.count()}건 · 배운 것 ${(await learnedSkills(999)).length}건`, "플래너");
}
// 공유 보드 읽기 (코인 AI 봇·UI 가 씀)
export async function researchBoard(n = 12){ const B = await lib("board"); return B.makeBoard(lsStore()).recent(n); }

/* ---- 🫧 자체 감정(시장 심리) — jjs523/day_trading_bot 의 뉴스 감정→심리점수 방식을 사전 기반으로 오프라인 이식.
       어휘는 금융·코인어 + jaehong-k/Moral_Emotion_Dataset(KOME) 데이터 추출어. 뉴스팀이 돌리고, 자체 AI 에 한 표로 들어간다. ---- */
async function sentimentJob(){
  const S = await lib("sentiment"), lead = agentById("macro");
  let texts = [];
  try { texts = texts.concat((teamNotes("news") || []).slice(-12).map(n => n.text)); } catch(e){}
  try { const log = await loadLog(); texts = texts.concat((log || []).filter(e => e.ch === "news" && (e.text || e.msg)).slice(-14).map(e => e.text || e.msg)); } catch(e){}
  try { const B = await lib("board"); texts = texts.concat(B.makeBoard(lsStore()).recent(8).map(f => f.text)); } catch(e){}
  texts = texts.filter(Boolean);
  const a = S.analyzeNews(texts);
  writeJ("coinSentiment", {score: a.score, polarity: a.polarity, verdict: a.verdict, n: a.n, t: Date.now()});
  table("news", lead.id, `🫧 시장 심리 (자체 감정 엔진) — ${a.score}/100 · ${a.verdict}`, ["항목", "값"],
    [["종합 심리점수", `${a.score}/100`], ["판정", a.verdict], ["분석한 뉴스·여론", `${a.n}건 (긍정 ${a.dist.pos}·부정 ${a.dist.neg}·중립 ${a.dist.neu})`], ["영향 큰 단어", a.top.map(x => `${x.w}(${x.v > 0 ? "+" : ""}${x.v})`).join(" · ") || "—"]],
    "외부 모델 없이 오프라인으로 도는 자체 감정 엔진(day_trading_bot 방식 · KOME 데이터 유래 어휘) · 가격과 함께 봐야 함 · 참고용");
  addNote("news", `시장 심리 ${a.score}/100 (${a.verdict}) · 긍정 ${a.dist.pos}/부정 ${a.dist.neg}`, "감정");
  await learnSkill(`시장 심리 ${a.verdict}(${a.score}/100): ${a.top.slice(0, 3).map(x => x.w).join(",")}`, {job: "sent"});
  await explain(lead.id, "news", "자체 감정 엔진이 낸 시장 심리 점수를 보고 지금 뉴스·여론 분위기가 긍정인지 부정인지, 어떤 단어가 그렇게 만들었는지 해설한다. 심리는 참고일 뿐이고 가격·추세와 함께 봐야 한다는 점을 밝힌다.", `종합 심리 ${a.score}/100 ${a.verdict} · 긍정 ${a.dist.pos}/부정 ${a.dist.neg}/중립 ${a.dist.neu} · 단어 ${a.top.map(x => x.w).join(",")}`, "아래 시장 심리 분석을 해설해 줘.");
}
// 최근(12시간 내) 시장 심리 — 자체 AI·코인 AI 봇이 읽음
export function marketSentiment(){ const s = readJ("coinSentiment", null); return s && Date.now() - s.t <= 12 * 3600e3 ? s : null; }

/* ---- 🗄 저장소 이전 (obevo 방식): 앱이 켜질 때 한 번 — 이미 한 변경은 건너뛰고, 실패하면 백업으로 되돌림 ---- */
export function runMigrations(){
  return lib("migrate").then(M => M.migrate([
    {name: "2026-10-ic-ledger", checksum: "2", rerunnable: true, keys: ["coinICLedger"], up: () => { if (!Array.isArray(JSON.parse(localStorage.getItem("coinICLedger") || "null"))) localStorage.setItem("coinICLedger", "[]"); }, note: "투자위원회 결정 장부"},
    {name: "2026-10-journal-genesis", checksum: "1", keys: ["coinJournal"], up: () => { if (!localStorage.getItem("coinJournal")) localStorage.setItem("coinJournal", "[]"); }, note: "이중 시간 감사 기록 시작"},
    {name: "2026-10-combo-calls-trim", checksum: "1", keys: ["coinComboCalls"], up: () => { const v = JSON.parse(localStorage.getItem("coinComboCalls") || "[]"); localStorage.setItem("coinComboCalls", JSON.stringify(v.slice(-300))); }, note: "타점 기록장 300건 제한"},
    {name: "2026-10-sdlc-store", checksum: "1", keys: ["coinSDLC"], up: () => { if (!localStorage.getItem("coinSDLC")) localStorage.setItem("coinSDLC", "{}"); }, note: "전략 버전 저장소"}
  ])).catch(() => []);
}
if (typeof window !== "undefined") runMigrations();

/* ================================================================
   🤖 선물 자동매매봇팀 — 유명 트레이딩 봇(passivbot·jesse·OctoBot·freqtrade·Binance 선물봇)의 봇 전략을
   우리 전략 JSON으로 다시 만들어(코드 복사 없음) 기존 백테스트→데모→실거래 파이프라인에 올린다.
   · 배포되는 봇(실거래 가능): 단일 포지션 전략 — 추세추종·돌파·평균회귀·슈퍼트렌드 플립·추세 캐리.
     주문은 기존 안전 경로(paper→live.js)로만: AI는 주문 안 함, 코드가 한도·사용자 승인·긴급정지 안에서만.
   · 그리드·DCA 봇: 무한 물타기 청산 위험 때문에 '백테스트 연구용'으로만 보여 준다(lib/botsim.js). 실거래로 내보내지 않는다.
   · 자동 개선: 올라간 봇 전략도 기존 하이퍼옵트(전략 최적화팀)가 데모 성과를 보고 다듬는다.
   ================================================================ */
const BOT_LEV = 3;   // 봇 배포 전략 레버리지: 실거래 한도(maxLeverage 3)에 맞춰 바로 연결 가능하게
// 배포 가능한 단일 포지션 봇 전략 (출처는 tech.js). coin: COINS 항목, tf 문자열
const BOT_TEMPLATES = [
  {id: "trend", name: "추세추종 봇", repo: "jesse · Binance 선물봇", build: (c, tf) => ({
    name: `🤖 추세추종 봇 · ${c.ko} ${TF_KO[tf]}`, indicators: [{id: "ef", type: "ema", length: 20}, {id: "es", type: "ema", length: 50}, {id: "adx", type: "adx", length: 14}],
    long_entry: {logic: "all", conditions: [{left: "ef", op: "crosses_above", right: "es"}, {left: "adx.adx", op: ">", right: "20"}]},
    short_entry: {logic: "all", conditions: [{left: "ef", op: "crosses_below", right: "es"}, {left: "adx.adx", op: ">", right: "20"}]},
    long_exit: {logic: "any", conditions: [{left: "ef", op: "crosses_below", right: "es"}]}, short_exit: {logic: "any", conditions: [{left: "ef", op: "crosses_above", right: "es"}]},
    risk: {leverage: BOT_LEV, position_pct: 20, atr_stop_mult: 2.5, trailing_stop_pct: 3}})},
  {id: "break", name: "돌파 봇", repo: "OctoBot · Binance 선물봇", build: (c, tf) => ({
    name: `🤖 돌파 봇 · ${c.ko} ${TF_KO[tf]}`, indicators: [{id: "hi", type: "highest", length: 20, source: "high"}, {id: "lo", type: "lowest", length: 20, source: "low"}, {id: "ef", type: "ema", length: 100}],
    long_entry: {logic: "all", conditions: [{left: "close", op: "crosses_above", right: "hi[1]"}, {left: "close", op: ">", right: "ef"}]},
    short_entry: {logic: "all", conditions: [{left: "close", op: "crosses_below", right: "lo[1]"}, {left: "close", op: "<", right: "ef"}]},
    long_exit: {logic: "any", conditions: [{left: "close", op: "crosses_below", right: "lo[1]"}]}, short_exit: {logic: "any", conditions: [{left: "close", op: "crosses_above", right: "hi[1]"}]},
    risk: {leverage: BOT_LEV, position_pct: 20, atr_stop_mult: 2, take_profit_pct: 6}})},
  {id: "revert", name: "평균회귀 봇", repo: "jesse · Erfaniaa", build: (c, tf) => ({
    name: `🤖 평균회귀 봇 · ${c.ko} ${TF_KO[tf]}`, indicators: [{id: "rsi", type: "rsi", length: 14}, {id: "bb", type: "bb", length: 20, mult: 2}, {id: "ef", type: "ema", length: 200}],
    long_entry: {logic: "all", conditions: [{left: "rsi", op: "<", right: "30"}, {left: "close", op: "<", right: "bb.lower"}, {left: "close", op: ">", right: "ef"}]},
    short_entry: {logic: "all", conditions: [{left: "rsi", op: ">", right: "70"}, {left: "close", op: ">", right: "bb.upper"}, {left: "close", op: "<", right: "ef"}]},
    long_exit: {logic: "any", conditions: [{left: "rsi", op: ">", right: "55"}]}, short_exit: {logic: "any", conditions: [{left: "rsi", op: "<", right: "45"}]},
    risk: {leverage: BOT_LEV, position_pct: 20, stop_loss_pct: 3, take_profit_pct: 4, allow_reverse: false}})},
  {id: "super", name: "슈퍼트렌드 플립 봇", repo: "OctoBot · jesse", build: (c, tf) => ({
    name: `🤖 슈퍼트렌드 봇 · ${c.ko} ${TF_KO[tf]}`, indicators: [{id: "st", type: "supertrend", length: 10, mult: 3}, {id: "ef", type: "ema", length: 200}],
    long_entry: {logic: "all", conditions: [{left: "st.trend", op: "crosses_above", right: "0"}, {left: "close", op: ">", right: "ef"}]},
    short_entry: {logic: "all", conditions: [{left: "st.trend", op: "crosses_below", right: "0"}, {left: "close", op: "<", right: "ef"}]},
    long_exit: {logic: "any", conditions: [{left: "st.trend", op: "crosses_below", right: "0"}]}, short_exit: {logic: "any", conditions: [{left: "st.trend", op: "crosses_above", right: "0"}]},
    risk: {leverage: BOT_LEV, position_pct: 20, atr_stop_mult: 3, trailing_stop_pct: 4}})},
  {id: "carry", name: "추세 캐리 봇", repo: "passivbot(추세형) · freqtrade", build: (c, tf) => ({
    name: `🤖 추세 캐리 봇 · ${c.ko} ${TF_KO[tf]}`, indicators: [{id: "ef", type: "ema", length: 50}, {id: "es", type: "ema", length: 200}, {id: "adx", type: "adx", length: 14}],
    long_entry: {logic: "all", conditions: [{left: "ef", op: ">", right: "es"}, {left: "close", op: ">", right: "ef"}, {left: "adx.plus_di", op: ">", right: "adx.minus_di"}]},
    short_entry: {logic: "all", conditions: [{left: "ef", op: "<", right: "es"}, {left: "close", op: "<", right: "ef"}, {left: "adx.minus_di", op: ">", right: "adx.plus_di"}]},
    long_exit: {logic: "any", conditions: [{left: "close", op: "crosses_below", right: "ef"}]}, short_exit: {logic: "any", conditions: [{left: "close", op: "crosses_above", right: "ef"}]},
    risk: {leverage: BOT_LEV, position_pct: 20, atr_stop_mult: 3, minimal_roi: {"0": 10, "240": 5, "960": 2, "2880": 0}}})},
  {id: "macd", name: "MACD 추세 봇", repo: "freqtrade · jesse", build: (c, tf) => ({
    name: `🤖 MACD 추세 봇 · ${c.ko} ${TF_KO[tf]}`, indicators: [{id: "m", type: "macd", fast: 12, slow: 26, signal: 9}, {id: "ef", type: "ema", length: 200}, {id: "adx", type: "adx", length: 14}],
    long_entry: {logic: "all", conditions: [{left: "m.line", op: "crosses_above", right: "m.signal"}, {left: "m.line", op: "<", right: "0"}, {left: "close", op: ">", right: "ef"}, {left: "adx.adx", op: ">", right: "18"}]},
    short_entry: {logic: "all", conditions: [{left: "m.line", op: "crosses_below", right: "m.signal"}, {left: "m.line", op: ">", right: "0"}, {left: "close", op: "<", right: "ef"}, {left: "adx.adx", op: ">", right: "18"}]},
    long_exit: {logic: "any", conditions: [{left: "m.line", op: "crosses_below", right: "m.signal"}]}, short_exit: {logic: "any", conditions: [{left: "m.line", op: "crosses_above", right: "m.signal"}]},
    risk: {leverage: BOT_LEV, position_pct: 20, atr_stop_mult: 2.5, trailing_stop_pct: 3}})},
  {id: "keltner", name: "켈트너 추세 봇", repo: "OctoBot · freqtrade", build: (c, tf) => ({
    name: `🤖 켈트너 추세 봇 · ${c.ko} ${TF_KO[tf]}`, indicators: [{id: "kc", type: "keltner", length: 20, mult: 2}, {id: "ef", type: "ema", length: 200}, {id: "adx", type: "adx", length: 14}],
    long_entry: {logic: "all", conditions: [{left: "close", op: "crosses_above", right: "kc.upper"}, {left: "close", op: ">", right: "ef"}, {left: "adx.adx", op: ">", right: "20"}]},
    short_entry: {logic: "all", conditions: [{left: "close", op: "crosses_below", right: "kc.lower"}, {left: "close", op: "<", right: "ef"}, {left: "adx.adx", op: ">", right: "20"}]},
    long_exit: {logic: "any", conditions: [{left: "close", op: "crosses_below", right: "kc.middle"}]}, short_exit: {logic: "any", conditions: [{left: "close", op: "crosses_above", right: "kc.middle"}]},
    risk: {leverage: BOT_LEV, position_pct: 20, atr_stop_mult: 2, trailing_stop_pct: 3.5}})},
  {id: "srsi", name: "스토캐스틱RSI 되돌림 봇", repo: "jesse · Erfaniaa", build: (c, tf) => ({
    name: `🤖 스토캐스틱RSI 되돌림 봇 · ${c.ko} ${TF_KO[tf]}`, indicators: [{id: "sr", type: "stochrsi", length: 14, k_smooth: 3, d_smooth: 3}, {id: "ef", type: "ema", length: 200}],
    long_entry: {logic: "all", conditions: [{left: "sr.k", op: "crosses_above", right: "sr.d"}, {left: "sr.k", op: "<", right: "25"}, {left: "close", op: ">", right: "ef"}]},
    short_entry: {logic: "all", conditions: [{left: "sr.k", op: "crosses_below", right: "sr.d"}, {left: "sr.k", op: ">", right: "75"}, {left: "close", op: "<", right: "ef"}]},
    long_exit: {logic: "any", conditions: [{left: "sr.k", op: ">", right: "80"}]}, short_exit: {logic: "any", conditions: [{left: "sr.k", op: "<", right: "20"}]},
    risk: {leverage: BOT_LEV, position_pct: 20, stop_loss_pct: 2.5, take_profit_pct: 4, allow_reverse: false}})},
  {id: "donch", name: "변동성 돌파 봇", repo: "passivbot · freqtrade", build: (c, tf) => ({
    name: `🤖 변동성 돌파 봇 · ${c.ko} ${TF_KO[tf]}`, indicators: [{id: "dc", type: "donchian", length: 20}, {id: "ef", type: "ema", length: 100}, {id: "adx", type: "adx", length: 14}],
    long_entry: {logic: "all", conditions: [{left: "close", op: "crosses_above", right: "dc.upper[1]"}, {left: "close", op: ">", right: "ef"}, {left: "adx.adx", op: ">", right: "22"}]},
    short_entry: {logic: "all", conditions: [{left: "close", op: "crosses_below", right: "dc.lower[1]"}, {left: "close", op: "<", right: "ef"}, {left: "adx.adx", op: ">", right: "22"}]},
    long_exit: {logic: "any", conditions: [{left: "close", op: "crosses_below", right: "dc.middle"}]}, short_exit: {logic: "any", conditions: [{left: "close", op: "crosses_above", right: "dc.middle"}]},
    risk: {leverage: BOT_LEV, position_pct: 20, atr_stop_mult: 2.5, trailing_stop_pct: 4}})},
  // conor19w/Binance-Futures-Trading-Bot 의 tripleEMAStochasticRSIATR: EMA 8>14>50 정배열 + 스토RSI 교차, ATR 손절
  {id: "tema_srsi", name: "삼중 EMA + 스토RSI 봇", repo: "conor19w Binance 선물봇", build: (c, tf) => ({
    name: `🤖 삼중 EMA + 스토RSI 봇 · ${c.ko} ${TF_KO[tf]}`, indicators: [{id: "e8", type: "ema", length: 8}, {id: "e14", type: "ema", length: 14}, {id: "e50", type: "ema", length: 50}, {id: "sr", type: "stochrsi", length: 14, k_smooth: 3, d_smooth: 3}],
    long_entry: {logic: "all", conditions: [{left: "e8", op: ">", right: "e14"}, {left: "e14", op: ">", right: "e50"}, {left: "sr.k", op: "crosses_above", right: "sr.d"}]},
    short_entry: {logic: "all", conditions: [{left: "e8", op: "<", right: "e14"}, {left: "e14", op: "<", right: "e50"}, {left: "sr.k", op: "crosses_below", right: "sr.d"}]},
    long_exit: {logic: "any", conditions: [{left: "e8", op: "crosses_below", right: "e14"}]}, short_exit: {logic: "any", conditions: [{left: "e8", op: "crosses_above", right: "e14"}]},
    risk: {leverage: BOT_LEV, position_pct: 20, atr_stop_mult: 2, take_profit_pct: 3}})}
];
// 그리드·DCA 연구용 프리셋 (실거래로 안 나감) — passivbot 방식
const BOT_SIM_PRESETS = [
  {id: "grid_safe", name: "그리드 봇 (보수)", repo: "passivbot", p: {side: "long", spacingPct: 1.5, qtyMult: 1.0, maxRungs: 5, walletExpo: 0.4, tpMarkupPct: 1.2, leverage: 2}},
  {id: "grid_mid", name: "그리드 봇 (보통)", repo: "passivbot", p: {side: "long", spacingPct: 1.2, qtyMult: 1.3, maxRungs: 6, walletExpo: 0.6, tpMarkupPct: 1.0, leverage: 3}},
  {id: "dca_capped", name: "DCA 봇 (한도형)", repo: "passivbot · OctoBot", p: {side: "long", spacingPct: 2.0, qtyMult: 1.5, maxRungs: 5, walletExpo: 0.5, tpMarkupPct: 1.5, leverage: 2}}
];
export const botTemplates = () => BOT_TEMPLATES.map(t => ({id: t.id, name: t.name, repo: t.repo}));
export const botSimPresets = () => BOT_SIM_PRESETS;

// 봇 전략 하나를 만들어 백테스트·검증 → 통과하면 데모에 올림(기존 파이프라인) · 그리드/DCA 차례면 연구용 시뮬만 보여 줌
async function botJob(){
  const Q = await import("../nuri-ai/quant.js"), P = await import("../nuri-ai/paper.js"), RB = await lib("robust"), lead = agentById("bot_lead");
  const named = userNote && COINS.find(c => new RegExp(`${c.ko}|${c.sym.replace("USDT", "")}`, "i").test(userNote));
  const wantGrid = userNote && /그리드|grid|dca|물타기/i.test(userNote);
  const c = named || COINS[rot("botCoin", COINS.length)], tf = ["60", "240"][rot("botTf", 2)];
  // 그리드/DCA 연구 (주기적으로, 또는 말로 그리드 요청 시)
  if (wantGrid || rot("botGridEvery", 4) === 0){
    const B = await lib("botsim"), preset = BOT_SIM_PRESETS[rot("botPreset", BOT_SIM_PRESETS.length)];
    fire({kind: "busy", agent: lead, text: `🤖 ${c.ko} ${preset.name} 백테스트(연구용)`});
    const cs = (await candlesFor({market: c.sym, exchange: "binancef", timeframe: tf}, 1500)).cs;
    const r = B.simGrid(cs, preset.p), risk = B.botRisk(preset.p), s = r.stats;
    table("bot", lead.id, `🤖 ${c.ko} ${TF_KO[tf]}봉 · ${preset.name} (연구용 백테스트)`, ["항목", "값"], [["수익률", pc(s.return_pct)], ["최대 낙폭", s.max_drawdown_pct + "%"], ["청산 횟수", String(s.liquidations)], ["최다 물타기", s.worst_rungs + "회"], ["최대 증거금 사용", s.max_margin_pct + "%"], ["익절 거래", String(s.trades)], ["위험도", risk.level]],
      `⚠ 그리드·DCA는 추세장에서 끝까지 물리면 청산됩니다(위 청산 횟수) · 지갑 노출 ${Math.round(preset.p.walletExpo * 100)}%·물타기 ${preset.p.maxRungs}회로 막음 · 연구용일 뿐 실거래로 내보내지 않습니다${risk.warn.length ? " · " + risk.warn[0] : ""}`);
    addNote("bot", `${c.ko} ${preset.name}: 수익 ${pc(s.return_pct)} · 청산 ${s.liquidations} · ${risk.level}`, "그리드연구");
    await explain(lead.id, "bot", `${c.ko} ${preset.name}의 백테스트 결과를 보고 어떤 장세에서 벌고 어디서 위험한지, 왜 그리드·DCA를 실거래로 바로 돌리면 안 되는지 설명한다.`, `${preset.name}: 수익 ${pc(s.return_pct)} · 최대낙폭 ${s.max_drawdown_pct}% · 청산 ${s.liquidations}회 · 최다 물타기 ${s.worst_rungs} · 위험도 ${risk.level}`, "아래 그리드/DCA 봇 백테스트를 보고 장단점과 위험을 설명해 줘.");
    return;
  }
  // 배포 가능한 단일 포지션 봇 전략
  const T = BOT_TEMPLATES[rot("botTpl", BOT_TEMPLATES.length)];
  fire({kind: "busy", agent: lead, text: `🤖 ${T.name} · ${c.ko} ${TF_KO[tf]}봉 백테스트`});
  let spec; try { spec = Q.normalizeSpec({...T.build(c, tf), symbol: c.sym, interval: IV_NAME[tf], risk: {...T.build(c, tf).risk, ...COSTS.crypto}}); }
  catch(e){ post({ch: "bot", kind: "system", text: `${T.name} 전략 형식 오류: ${e.message}`}); return; }
  let cs; try { const H = await import("../nuri-ai/history.js"); cs = (await Promise.race([H.historyCandles({market: c.sym, exchange: "binancef", interval: IV_NAME[tf], maxBars: 20000}), new Promise((_, rej) => setTimeout(() => rej(0), 60e3))])).candles; if (!(cs?.length > 300)) throw 0; } catch(e){ cs = (await candlesFor({market: c.sym, exchange: "binancef", timeframe: tf}, 1500)).cs; }
  const bt = Q.backtest(spec, cs), wf = Q.walkForward(spec, cs), pt = RB.permutationTest(bt.trades.map(t => t.pnl)), st = x => ({ret: +(x?.return_pct ?? 0), dd: +(x?.max_dd_pct ?? 0), win: +(x?.win_rate ?? 0), pf: x?.profit_factor == null ? null : +x.profit_factor, n: x?.n_trades ?? 0});
  post({ch: "bt", kind: "bt", agent: "val", lane: "std", name: spec.name, market: c.sym, mname: `${c.ko} 선물`, tf, hist: `봇 전략 · ${cs.length.toLocaleString()}봉 · ${T.repo}`, all: st(bt.stats), is: st(wf.is), oos: st(wf.oos), pass: wf.pass, reasons: wf.reasons, author: lead.name, spec, lev: BOT_LEV});
  table("bot", lead.id, `🤖 ${T.name} 백테스트 (${c.ko} ${TF_KO[tf]}봉 · ${T.repo})`, ["항목", "값"], [["검증(뒤30%) 수익", pc(st(wf.oos).ret)], ["손익비", st(wf.oos).pf ?? "—"], ["거래", String(st(wf.oos).n)], ["관문", wf.pass ? "✅ 통과 → 데모 투입" : "❌ 불통과"], ["운일 확률 p", pt.p == null ? "—" : pt.p.toFixed(3)]], wf.pass ? "데모거래로 올라가 14일·20거래·손익비 1.2 등 관문을 거쳐야 실거래 후보가 됩니다 · 자동 개선은 전략 최적화팀이 맡습니다" : "검증 불통과 — 데모로 올리지 않습니다");
  pubTo(c.sym, "bot", {team: "bot", title: `${T.name} · ${wf.pass ? "데모 투입" : "불통과"}`, text: `검증 수익 ${pc(st(wf.oos).ret)} · 손익비 ${st(wf.oos).pf ?? "—"} · ${T.repo}`, spec, baseSpec: spec});
  // 견고성 관문(Vibe-Trading): 운일확률 p≤0.1 · 5구간 60% 이상 이익 · 위생 — 봇도 매매법과 똑같이 통과해야 데모에 오른다
  let rbOk = true, rbWhy = "";
  try { const mw = RB.multiWindow(Q, spec, cs, 5), hy = RB.hygiene(bt);
    const pOK = pt.p == null || pt.p <= 0.1, mwOK = mw.total < 3 || mw.positive >= Math.ceil(mw.total * 0.6), hyOK = hy.ok !== false;
    rbOk = pOK && mwOK && hyOK; rbWhy = [!pOK && `운일확률 ${pt.p?.toFixed(2)}`, !mwOK && `구간일관성 ${mw.positive}/${mw.total}`, !hyOK && (hy.fails || []).join(",")].filter(Boolean).join(" · "); } catch(e){}
  if (wf.pass && !rbOk) post({ch: "bot", kind: "system", text: `🧪 ${T.name}(${c.ko}) 워크포워드는 통과했지만 견고성 미달(${rbWhy}) → 데모 보류`});
  if (wf.pass && rbOk){
    const s = await P.addStrategy({spec, market: c.sym, exchange: "binancef", tf, author: lead.name, wf: {is: st(wf.is), oos: st(wf.oos)}, cls: "crypto", mname: `${c.ko} 선물`, lane: "std"});
    post({ch: "demo", kind: "system", text: `🤖 봇 데모 투입: ${s.name} (${c.ko} ${TF_KO[tf]}봉 · 레버리지 ${BOT_LEV}배 · ${T.repo} 방식) · 가상 10,000`});
    journal("record", "strategy", s.id, {bot: T.id, repo: T.repo, phash: specHash(spec)}, "bot_lead", "봇 전략 데모 투입");
  }
  addNote("bot", `${T.name} ${c.ko}: 검증 ${pc(st(wf.oos).ret)} → ${wf.pass ? "데모 투입" : "유지"}`, "봇");
  await explain(lead.id, "bot", `${T.name}(${c.ko})의 백테스트·검증 결과를 보고 어떤 장세에 맞는 봇인지, 실거래로 켜기 전에 데모에서 무엇을 확인해야 하는지 설명한다.`, `${T.name} ${c.ko} ${TF_KO[tf]}봉 · 검증 수익 ${pc(st(wf.oos).ret)} · 손익비 ${st(wf.oos).pf ?? "—"} · 거래 ${st(wf.oos).n} · 관문 ${wf.pass ? "통과" : "불통과"}`, "아래 자동매매봇 전략 백테스트를 보고 설명해 줘.");
}
// 봇 조종판 자료 (UI 가 읽음): 데모·실거래 중인 봇 전략 + 실거래 연결 상태 — 주문은 live.js 가, 연결은 사용자가 [실거래] 화면에서
export async function botBoard(){
  const P = await import("../nuri-ai/paper.js"), book = await P.loadBook().catch(() => ({strategies: []}));
  let L = null, cfg = {}; try { L = await import("../nuri-ai/live.js"); cfg = L.liveCfg?.() || {}; } catch(e){}
  const bots = book.strategies.filter(s => /^🤖/.test(s.name));
  const rows = bots.map(s => {
    const g = L?.gateFor ? L.gateFor(s) : {eligible: false, checks: []}, linked = cfg.linked?.[s.id]?.on, eq = P.equityOf(s);
    return {id: s.id, name: s.name, market: s.mname || s.market, tf: s.tf, status: s.status, eq, trades: (s.trades || []).length, days: Math.floor((Date.now() - s.created) / 864e5),
      gate: g.eligible, gateFail: (g.checks || []).filter(c => !c.ok).map(c => c.name), live: !!linked};
  });
  return {rows, live: {enabled: !!cfg.enabled, env: cfg.env || "testnet", mode: cfg.mode || "approve", linked: Object.values(cfg.linked || {}).filter(v => v?.on).length, halted: L?.isHalted?.() || false,
    limits: cfg.limits || {}}, templates: botTemplates(), sim: botSimPresets(), supported: !!L};
}

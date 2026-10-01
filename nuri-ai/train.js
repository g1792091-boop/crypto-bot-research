// 학습: 대화·합성 데이터를 모아 작은 오픈모델을 직접 미세조정(LoRA)하고, 결과 모델을 앱에 다시 넣는다
// 합성 데이터는 NVIDIA data-designer 스킬과 같은 방식(조건 샘플링 → 질문 생성 → 모범 답안 → AI 채점)으로 만든다.
import { idb, uid, brainStream, splitThink, settings, routeCandidates, PROVIDERS, modelKind } from "./engine.js";
import { toModelMessages, BUILTIN_SKILLS, runAgent, TOOLS } from "./agent.js";
import { nvIndex, nvSkill } from "./nvskills.js";

/* ============ 바탕 모델 (RTX 3050 노트북 기준으로 고름) ============ */
export const BASES = [
  {id: "Qwen/Qwen3.5-2B", name: "Qwen3.5 2B", lic: "Apache-2.0", gguf: "약 1.3GB", fit: "추천 · 3050(4GB)에서 빠르게 실행 · Colab·로컬 모두 학습 가능", local: true},
  {id: "Qwen/Qwen3.5-0.8B", name: "Qwen3.5 0.8B", lic: "Apache-2.0", gguf: "약 0.6GB", fit: "가장 가벼움 · 3050 로컬 학습이 가장 쉬움", local: true},
  {id: "Qwen/Qwen3.5-4B", name: "Qwen3.5 4B", lic: "Apache-2.0", gguf: "약 2.7GB", fit: "가장 똑똑 · Colab에서 학습, 3050에서는 Ollama로 실행", local: false},
  {id: "unsloth/gemma-4-E2B-it", name: "Gemma 4 E2B", lic: "Gemma 약관", gguf: "약 3GB", fit: "Google · 다국어 · Colab 학습 권장", local: false},
  {id: "LGAI-EXAONE/EXAONE-4.0-1.2B", name: "EXAONE 4.0 1.2B", lic: "비상업(연구·교육·개인)", gguf: "약 0.8GB", fit: "LG · 한국어 강함 · 3050 로컬 학습 가능", local: true}
];

/* ============ 학습 데이터 ============ */
const NAME = () => settings.aiName || "GH Nano";
export const TRAIN_SYS = mode => mode === "code"
  ? `너는 '${NAME()} 코드'다. 사용자의 작업 폴더에서 코드를 읽고 고치고 실행하는 숙련된 엔지니어다. 도구는 <tool name="도구">{json}</tool> 형식으로 하나씩 쓰고 <tool_result>를 받아 이어서 일한다.`
  : `너는 '${NAME()}'라는 이름의 한국어 AI 어시스턴트다. 사용자가 직접 만든 자체 AI다. 핵심 결론부터 말하고 전문가가 설명하듯 자연스러운 문장으로 해설한다. 필요하면 <tool name=\"도구\">{json}</tool> 형식으로 도구를 하나씩 쓰고 <tool_result>를 받아 이어서 답한다. 모르는 것은 지어내지 않는다.`;
const visibleOf = m => (m.parts || [{type: "text", text: m.content || ""}]).filter(p => p.type === "text").map(p => splitThink(p.text).body).join("\n\n").trim();
function shrink(msgs){ return msgs.map(m => m.role === "user" && m.content.startsWith("<tool_result") && m.content.length > 3000 ? {...m, content: m.content.slice(0, 2980) + "…</tool_result>"} : m); }
// 대화 → 학습 예시. onlyGood: 👍 받은 답만, tools: 도구 사용 과정까지 가르칠지
export function samplesFromChats(chats, {onlyGood = true, tools = true} = {}){
  const out = [];
  for (const c of chats){
    const ms = c.messages || [];
    const bad = ms.findIndex(m => m.role === "assistant" && m.rating < 0);
    const usable = bad >= 0 ? ms.slice(0, Math.max(0, bad - 1)) : ms;   // 👎 받은 답과 그 질문부터는 버린다
    const ends = [];
    usable.forEach((m, i) => { if (m.role === "assistant" && !m.error && !m.streaming && visibleOf(m) && (!onlyGood || m.rating > 0)) ends.push(i); });
    const pick = onlyGood ? ends : ends.slice(-1);   // 전체 모드는 대화당 하나(앞 내용 포함)
    for (const i of pick){
      const hist = usable.slice(0, i + 1);
      let conv;
      if (tools) conv = shrink(toModelMessages(hist, 1e9));
      else conv = hist.map(m => m.role === "user" ? {role: "user", content: m.content + (m.attach ? m.attach.map(a => `\n\n[첨부: ${a.name}]\n${a.text.slice(0, 4000)}`).join("") : "")} : {role: "assistant", content: visibleOf(m)}).filter(m => m.content);
      if (conv.length < 2 || conv[conv.length - 1].role !== "assistant") continue;
      out.push({messages: [{role: "system", content: TRAIN_SYS(c.mode)}, ...conv], src: "chat"});
    }
  }
  return out;
}
export const loadSynth = async () => (await idb.all("train:")).sort((a, b) => a.t - b.t);
export const removeSynth = id => idb.del("train:" + id);
export async function clearSynth(){ for (const s of await loadSynth()) await idb.del("train:" + s.id); }
export function toJSONL(samples){ return samples.map(s => JSON.stringify({messages: s.messages})).join("\n") + "\n"; }
// DPO(선호 학습)용: 여러 모델 중 가장 좋은 답(chosen) vs 가장 나쁜 답(rejected)
export function toDPOJSONL(samples){
  return samples.filter(s => s.rejected && s.messages?.length >= 3).map(s => JSON.stringify({prompt: s.messages.slice(0, -1), chosen: [s.messages.at(-1)], rejected: [{role: "assistant", content: s.rejected}]})).join("\n") + "\n";
}
// 지금까지 융합에 실제로 참여한 모델
export function fusionStats(samples){
  const used = new Map();
  for (const s of samples) for (const m of s.sources || []) used.set(m, (used.get(m) || 0) + 1);
  return {used, pairs: samples.filter(s => s.rejected).length};
}

/* ============ 합성 데이터: GH Nano 만들기 ============ */
// 1) 조건 샘플링(NVIDIA data-designer 방식)으로 질문을 만들고
// 2) 연결된 모든 AI 모델이 같은 질문에 답하고 순위를 매겨 가장 좋은 답(SFT)과 좋은 답 vs 나쁜 답(DPO)을 고르거나(모델 융합),
//    실제 도구(시세·설계·뉴스)를 쓰는 과정까지 그대로 기록하고(에이전트 기록),
//    NVIDIA 공식 스킬 문서를 근거로 문답을 만든 뒤
// 3) AI 채점으로 좋은 것만 남긴다. 이렇게 모은 데이터로 작은 모델을 학습시키면 '모델 + 스킬'이 하나로 합쳐진 GH Nano가 된다.
export const TOPICS = [
  {id: "crypto_spot", name: "코인 현물", skill: "crypto_spot", agent: true, seeds: ["비트코인 지금 분석", "이더리움 추세", "알트코인 매수 판단", "김치 프리미엄", "거래량 급증 코인", "리플 지지선", "솔라나 전망"]},
  {id: "crypto_futures", name: "코인 선물", skill: "crypto_futures", agent: true, seeds: ["비트코인 선물 펀딩비 해석", "레버리지 청산가 계산", "롱숏비율 쏠림", "미결제약정 증가 의미", "선물 포지션 크기", "이더리움 선물 숏 판단"]},
  {id: "us_stocks", name: "해외주식", skill: "us_stocks", agent: true, seeds: ["엔비디아 일봉 분석", "테슬라 실적 이후", "애플 주가 흐름", "반도체 ETF", "빅테크 비교", "팔란티어 변동성"]},
  {id: "kr_stocks", name: "국내주식", skill: "kr_stocks", agent: true, seeds: ["삼성전자 분석", "SK하이닉스 추세", "코스피 외국인 수급", "현대차 배당", "2차전지 업종"]},
  {id: "global_futures", name: "해외선물", skill: "global_futures", agent: true, seeds: ["WTI 원유 선물 분석", "금 선물 전망", "나스닥100 선물", "천연가스 변동성", "미 국채 선물과 금리", "구리 선물과 경기"]},
  {id: "news", name: "뉴스 해설", skill: "news", agent: true, seeds: ["오늘 코인 시장 뉴스", "미국 증시 마감 뉴스", "국제유가 뉴스", "연준 금리 뉴스", "국내 증시 시황"]},
  {id: "macro", name: "경제 지표·거시경제", skill: "macro", agent: true, seeds: ["이번 주 경제 발표", "CPI 발표 해석", "FOMC와 금리", "고용지표", "달러 인덱스", "한국은행 기준금리"]},
  {id: "backtest", name: "퀀트 전략·백테스트", skill: "backtest", agent: true, seeds: ["비트코인 이동평균 전략 백테스트", "이더리움 RSI 전략", "볼린저 전략 비교", "과최적화", "손절 넣은 전략", "최대낙폭 관리"]},
  {id: "arch", name: "건축 설계·견적·렌더링", skill: "arch", agent: true, seeds: ["60평 대지 3층 주택 설계", "상가주택 설계", "카페 건물 설계", "공사비 견적", "인테리어 견적", "건폐율·용적률 계산", "CAD·Revit·SketchUp 사용"]},
  {id: "land", name: "부동산·토지·법규", skill: "land", agent: true, seeds: ["재개발 가능성", "용도지역별 건축 제한", "모아타운", "법원경매 절차", "양도소득세", "전세 계약 주의"]},
  {id: "research", name: "인터넷 리서치·자료 조사", skill: "research", agent: true, seeds: ["최신 AI 반도체 동향 조사", "전기차 보조금 정책 찾아보기", "어떤 회사 평판 조사", "논문 내용 정리", "제품 비교 리서치", "여행지 최신 정보"]},
  {id: "daily", name: "일상 대화·글쓰기·번역", skill: null, seeds: ["이메일 작성", "보고서 요약", "자기소개서", "영어 번역", "고민 상담", "여행 계획", "공부 방법"]},
  {id: "code", name: "코딩", skill: "coding", seeds: ["파이썬 기초", "자바스크립트 웹페이지", "엑셀 자동화", "API 호출", "버그 찾기", "SQL 쿼리"]},
  {id: "nvidia", name: "NVIDIA 스킬 지식", skill: null, nv: true, seeds: []}
];
const PERSONAS = ["코인을 막 시작한 직장인", "10년 차 주식 투자자", "선물 단타 트레이더", "건축사무소를 운영하는 건축사", "집을 짓고 싶은 40대 부부", "부동산 경매에 관심 있는 자영업자", "재개발 구역의 집주인", "경제학과 대학생", "개발을 배우는 취준생", "AI 엔지니어", "은퇴를 준비하는 50대"];
const LEVELS = ["쉬움(기초 개념)", "보통(실전 상황)", "어려움(여러 조건을 따지는 판단)"];
const STYLES = ["짧고 구어체로", "상황을 자세히 설명하며", "숫자와 조건을 넣어서", "비교를 요청하며"];
const pickOne = a => a[Math.floor(Math.random() * a.length)];
async function ask(messages, {signal, maxTokens = 1500, temperature = 0.7, target} = {}){
  let out = "";
  const route = await brainStream({messages, maxTokens, temperature, signal, role: "general", target, onContent: d => out += d});
  return {text: splitThink(out).body.trim(), route: route || target};
}
function parseJSONArray(t){
  const m = t.match(/\[[\s\S]*\]/); if (!m) return [];
  try { return JSON.parse(m[0]).map(x => typeof x === "string" ? x : x.question || x.q || "").filter(Boolean); } catch(e){ return []; }
}
// 선생으로 쓸 서로 다른 AI (회사·모델이 겹치지 않게, 최대 3개)
export function teachers(){
  const seen = new Set(), out = [];
  for (const role of ["general", "reason", "code"]) for (const c of routeCandidates(role)){
    const k = c.id + "|" + c.model;
    if (c.id === "local" || seen.has(k)) continue;
    seen.add(k); out.push(c); if (out.length >= 3) return out;
  }
  return out;
}
async function judgeScore(q, a, signal){
  const j = await ask([{role: "system", content: "[채점] 너는 엄격한 심사위원이다. 질문에 대한 답이 정확하고, 도움이 되고, 한국어가 자연스럽고, 수치를 지어내지 않았고, 숫자 나열이 아닌 해설로 설명했는지 1~5점으로 평가한다. 첫 줄에 '점수: N'만 쓴다."},
    {role: "user", content: `질문:\n${q}\n\n답:\n${String(a).slice(0, 6000)}`}], {signal, maxTokens: 60, temperature: 0});
  return +((j.text.match(/점수\s*[:：]?\s*([1-5])/) || j.text.match(/\b([1-5])\b/) || [])[1] || 0);
}
const answerSys = skill => `너는 '${NAME()}'라는 한국어 AI 어시스턴트다. 이 답은 학습 데이터용 모범 답안이므로 정확하고 구체적이며 친절해야 한다.
핵심 결론부터 말하고, 이유와 맥락을 전문가가 말로 설명하듯 자연스러운 문장으로 풀어 쓴다(표는 꼭 필요할 때만). 실시간 가격·시세·최신 법령처럼 지금 확인해야 하는 수치는 지어내지 말고 '확인 방법'과 '해석하는 법'을 알려준다. 투자·법률·세무는 일반 정보이며 전문가 확인이 필요하다고 짧게 덧붙인다.${skill ? "\n\n참고할 전문가 지침(지금은 도구를 쓸 수 없으니 도구 이름은 언급하지 말고 원칙과 방법으로 답한다):\n" + skill.prompt : ""}`;
/* ============ 모델 융합: 연결된 모든 AI 모델 → GH Nano 하나 ============ */
// 구조가 다른 모델(Llama·DeepSeek·Mistral·Qwen·Nemotron…)은 가중치를 직접 더할 수 없으므로,
// FuseChat-3.0과 같은 '암묵적 모델 융합'을 쓴다: 같은 질문에 여러 원본 모델이 답하고 → 순위를 매겨
// 가장 좋은 답으로 SFT, 가장 좋은 답 vs 가장 나쁜 답으로 DPO 학습 → 모든 모델의 장점이 GH Nano 하나에 녹아든다.
const FUSE_SKIP = /guard|safety|reward|embed|rerank|retriev|parse|tts|asr|whisper|riva|ocr|clip|nv-?dino|detect|segment|flux|stable-?diff|sdxl|cosmos|audio|speech/i;
const TOOL_LEAK = /<\/?tool\b|<tool_call>|DSML|tool▁call|\[TOOL_CALLS\]/;
const fuseBad = new Map();
const mkey = t => t.id + "|" + t.model;
// 융합에 참여하는 원본 모델: API 키를 넣은 모든 회사의 대화·코딩·추론 모델 전부
export function fusionSources(){
  const out = [], seen = new Set();
  for (const id of Object.keys(PROVIDERS).filter(id => settings.keys[id])){
    const ms = settings.provModels[id]?.length ? settings.provModels[id] : PROVIDERS[id].defaults;
    for (const m of ms){
      if (!["chat", "code", "reason", "vision"].includes(modelKind(m)) || FUSE_SKIP.test(m)) continue;
      const t = {id, model: m}; if (seen.has(mkey(t))) continue; seen.add(mkey(t)); out.push(t);
    }
  }
  return out;
}
// 모든 모델이 돌아가며 참여하도록 순서대로 고른다 (막힌 모델은 뺀다)
function pickSources(k){
  const all = fusionSources().filter(t => (fuseBad.get(mkey(t)) || 0) < 2); if (!all.length) return [];
  let c = 0; try { c = +localStorage.getItem("fuseCursor") || 0; } catch(e){}
  const out = []; for (let i = 0; i < Math.min(k, all.length); i++) out.push(all[(c + i) % all.length]);
  try { localStorage.setItem("fuseCursor", String((c + out.length) % 1e9)); } catch(e){}
  return out;
}
// 같은 질문에 여러 모델이 답하고, 심사로 순위를 매겨 최고(chosen)·최저(rejected)를 고른다
async function fuseAnswer(q, sys, signal, log, k = 4){
  const anchor = teachers()[0], rot = pickSources(k);
  const srcs = [anchor, ...rot.filter(t => !anchor || mkey(t) !== mkey(anchor))].filter(Boolean).slice(0, Math.max(2, k));
  const bad = t => fuseBad.set(mkey(t), (fuseBad.get(mkey(t)) || 0) + 1);
  const outs = (await Promise.all(srcs.map(t => ask([{role: "system", content: sys}, {role: "user", content: q}], {signal, maxTokens: 1600, temperature: 0.6, target: t})
    .then(a => a.text && a.text.length > 40 && !TOOL_LEAK.test(a.text) ? {t, text: a.text} : (bad(t), null)).catch(() => (bad(t), null))))).filter(Boolean);
  if (!outs.length) return null;
  if (signal?.aborted) throw new Error("멈춤");
  let scores;
  if (outs.length >= 2){
    log?.(`모델 ${outs.length}개 답 순위 매기는 중`);
    const j = await ask([{role: "system", content: "[순위] 너는 엄격한 심사위원이다. 같은 질문에 대한 여러 답을 정확성·유용성·자연스러운 한국어·수치를 지어내지 않음·해설의 깊이로 각각 1~10점 평가한다. 답 순서대로 점수만 JSON 배열로 출력한다. 예: [8,5,7]"},
      {role: "user", content: `질문:\n${q}\n\n${outs.map((o, i) => `### 답 ${i + 1}\n${o.text.slice(0, 3500)}`).join("\n\n")}`}], {signal, maxTokens: 80, temperature: 0});
    try { const arr = JSON.parse((j.text.match(/\[[\d\s.,]+\]/) || ["[]"])[0]).map(Number); if (arr.length === outs.length && arr.every(x => x >= 0 && x <= 10)) scores = arr; } catch(e){}
  }
  const ranked_ok = !!scores;   // 순위를 못 매기면 비교(DPO) 쌍은 만들지 않는다
  if (!scores) scores = [(await judgeScore(q, outs[0].text, signal)) * 2, ...outs.slice(1).map(() => 0)];
  const ranked = outs.map((o, i) => ({...o, s: scores[i]})).sort((a, b) => b.s - a.s);
  const best = ranked[0], worst = ranked[ranked.length - 1];
  return {text: best.text, teacher: best.t.model, score: Math.round(best.s / 2), fscore: best.s,
    rejected: ranked_ok && ranked.length >= 2 && best.s - worst.s >= 2 ? worst.text : null, sources: outs.map(o => o.t.model)};
}
// 실제 도구를 쓰는 과정까지 기록 (GH Nano가 시세·설계·뉴스 도구를 직접 쓰도록 배우게)
async function agentTrace(q, signal){
  const msg = {role: "assistant", parts: [], mode: "chat", ts: Date.now()};
  const user = {role: "user", content: q};
  try {
    await runAgent({mode: "chat", history: [user], msg, signal: signal || new AbortController().signal, onUpdate(){}, think: false, workspace: "",
      openArtifact: async () => null, askPermission: async () => false});
  } catch(e){ if (signal?.aborted) throw e; return null; }   // 실패하면 일반 문답으로 대신 만든다
  const final = visibleOf(msg);
  if (!final || final.length < 60 || msg.parts.some(p => p.type === "tool" && p.status === "error")) return null;
  return {conv: shrink(toModelMessages([user, msg], 1e9)), final, teacher: msg.route?.model || "", tools: msg.parts.filter(p => p.type === "tool").length};
}
// NVIDIA 공식 스킬 문서를 근거로 문답 만들기
async function nvSample(signal, log, name){
  const idx = await nvIndex(), s = (name && idx.skills.find(x => x.n === name)) || pickOne(idx.skills), sk = await nvSkill(s.n);
  const doc = String(sk.files["SKILL.md"] || "").replace(/^---[\s\S]*?\n---\s*/, "").slice(0, 5000);
  log?.(`NVIDIA 스킬 '${s.n}' 문서로 문답 만드는 중`);
  const g = await ask([{role: "system", content: "[질문 생성] 아래 기술 문서를 읽은 사용자가 실제로 물어볼 만한 한국어 질문 2개를 JSON 배열로만 출력한다."}, {role: "user", content: `문서(${s.n}):\n${doc}`}], {signal, maxTokens: 400, temperature: 0.9});
  const q = parseJSONArray(g.text)[0]; if (!q) return null;
  // 여러 모델이 같은 문서로 답하고 가장 좋은 답을 고른다(모델 융합)
  const a = await fuseAnswer(q, `너는 '${NAME()}'라는 한국어 AI 어시스턴트다. 아래 NVIDIA 공식 스킬 문서만 근거로, 절차와 이유를 친절한 한국어로 설명한다. 명령어·설정 이름은 원문 그대로 쓴다. 문서에 없는 내용은 지어내지 않는다. 도구 호출 형식은 쓰지 않는다.\n\n문서(${s.n}):\n${doc}`, signal, log, 3);
  if (!a || !a.text || TOOL_LEAK.test(a.text)) return null;   // 도구 호출이 섞인 답은 버린다
  return a.text.length > 60 ? {q, text: a.text, teacher: a.teacher, score: a.score, rejected: a.rejected, sources: a.sources, skill: s.n} : null;
}
// 같은 질문을 'NVIDIA 스킬을 찾아 읽고 답하는 과정'으로도 기록 (실제 도구 결과를 그대로 넣는다)
async function nvToolConv(q, name, answer){
  const conv = [{role: "user", content: q}], call = (tool, args, out) => conv.push({role: "assistant", content: `<tool name="${tool}">${JSON.stringify(args)}</tool>`}, {role: "user", content: `<tool_result name="${tool}">${out}</tool_result>`});
  const query = name.replace(/[-_]+/g, " ");
  const sr = await TOOLS.nv_skill_search.run({query});
  if (sr.text.includes(name)) call("nv_skill_search", {query}, sr.text);
  const rd = await TOOLS.nv_skill_read.run({name});
  call("nv_skill_read", {name}, rd.text.length > 1500 ? rd.text.slice(0, 1500) + "…(줄임)" : rd.text);
  conv.push({role: "assistant", content: answer});
  return conv;
}
// onEvent({kind:"sample"|"log", ...})
export async function generateSynth({topics, count, judge = true, ensemble = false, agent = false, signal, onEvent}){
  const sel = TOPICS.filter(t => topics.includes(t.id)); if (!sel.length) throw new Error("주제를 하나 이상 고르세요");
  const log = text => onEvent?.({kind: "log", text});
  const save = async s => { await idb.put("train:" + s.id, s); made++; onEvent?.({kind: "sample", sample: s, made, count}); };
  let made = 0, tries = 0;
  while (made < count && tries < count * 3){
    if (signal?.aborted) break;
    const topic = sel[tries % sel.length]; tries++;
    try {
      if (topic.nv){
        const r = await nvSample(signal, log); if (!r) continue;
        const score = r.score ?? (judge ? await judgeScore(r.q, r.text, signal) : null);
        if (score && score < 4){ log(`품질 ${score}점이라 버림`); continue; }
        await save({id: uid(), t: Date.now(), src: "synth", kind: "nvidia", topic: topic.id, score, teacher: r.teacher, skill: r.skill, sources: r.sources, rejected: r.rejected || undefined, messages: [{role: "system", content: TRAIN_SYS("chat")}, {role: "user", content: r.q}, {role: "assistant", content: r.text}]});
        continue;
      }
      const persona = pickOne(PERSONAS), level = pickOne(LEVELS), style = pickOne(STYLES), seed = pickOne(topic.seeds);
      const g = await ask([{role: "system", content: "[질문 생성] 너는 AI 학습 데이터를 설계하는 전문가다. 지시한 조건에 맞는 자연스러운 한국어 사용자 질문을 만든다. JSON 배열만 출력한다."},
        {role: "user", content: `주제: ${topic.name} / 세부: ${seed}\n질문자: ${persona}\n난이도: ${level}\n말투: ${style}\n서로 다른 질문 3개를 ["질문1","질문2","질문3"] 형식의 JSON 배열로만 출력해.`}], {signal, maxTokens: 700, temperature: 0.95});
      const qs = parseJSONArray(g.text).slice(0, 3);
      if (!qs.length){ log("질문을 만들지 못해 다시 시도합니다"); continue; }
      const skill = BUILTIN_SKILLS.find(s => s.id === topic.skill);
      for (const q of qs){
        if (made >= count || signal?.aborted) break;
        // 도구를 쓰는 분야는 실제 도구 사용 과정까지 기록
        if (agent && topic.agent){
          log(`도구 사용 기록: ${q.slice(0, 50)}`);
          const tr = await agentTrace(q, signal);
          if (tr){
            const score = judge ? await judgeScore(q, tr.final, signal) : null;
            if (score && score < 4){ log(`품질 ${score}점이라 버림`); continue; }
            await save({id: uid(), t: Date.now(), src: "synth", kind: "agent", topic: topic.id, persona, level, score, teacher: tr.teacher, tools: tr.tools, messages: [{role: "system", content: TRAIN_SYS("chat")}, ...tr.conv]});
            continue;
          }
        }
        log(`${ensemble ? "여러 모델 융합: " : "답안 작성: "}${q.slice(0, 50)}`);
        const a = ensemble ? await fuseAnswer(q, answerSys(skill), signal, log) : await ask([{role: "system", content: answerSys(skill)}, {role: "user", content: q}], {signal, maxTokens: 1800, temperature: 0.5}).then(x => ({text: x.text, teacher: x.route?.model || ""}));
        if (!a || !a.text || a.text.length < 40 || TOOL_LEAK.test(a.text)) continue;
        const score = a.score ?? (judge ? await judgeScore(q, a.text, signal) : null);
        if (score && score < 4){ log(`품질 ${score}점이라 버림`); continue; }
        await save({id: uid(), t: Date.now(), src: "synth", kind: ensemble ? "fusion" : "single", topic: topic.id, persona, level, score, teacher: a.teacher, sources: a.sources, rejected: a.rejected || undefined, messages: [{role: "system", content: TRAIN_SYS("chat")}, {role: "user", content: q}, {role: "assistant", content: a.text}]});
      }
    } catch (e){ if (signal?.aborted) break; log("건너뜀: " + (e.message || e).slice(0, 80)); }
  }
  return made;
}

/* ============ 모든 스킬을 빠짐없이 GH Nano에 넣기 ============ */
// 작은 모델이 스킬 문서 5천여 개를 통째로 외울 수는 없으므로, 스킬마다
//  ① 그 스킬의 핵심을 설명하는 문답(지식)과 ② nv_skill_search → nv_skill_read로 원문을 찾아 읽고 답하는 과정(사용법)을 학습시킨다.
// 원문은 앱(GHNano.exe)에 모두 들어 있어, 학습된 GH Nano가 필요할 때 직접 꺼내 읽는다. 이미 넣은 스킬은 건너뛰므로 멈췄다 이어서 할 수 있다.
export const BUILTIN_TARGET = 6;
export async function skillCoverage(){
  const syn = await loadSynth(), idx = await nvIndex();
  const nv = new Map(), per = {};
  for (const s of syn){
    if (s.skill) nv.set(s.skill, (nv.get(s.skill) || 0) + 1);
    const t = TOPICS.find(x => x.id === s.topic); if (t?.skill) per[t.skill] = (per[t.skill] || 0) + 1;
  }
  const builtin = BUILTIN_SKILLS.map(b => ({id: b.id, name: b.name, n: per[b.id] || 0, topic: TOPICS.find(t => t.skill === b.id)?.id}));
  const nvLeft = idx.skills.map(x => x.n).filter(n => (nv.get(n) || 0) < 2);
  return {nvTotal: idx.skills.length, nvDone: idx.skills.length - nvLeft.length, nvLeft, builtin, builtinDone: builtin.filter(b => b.n >= BUILTIN_TARGET).length};
}
// onEvent({kind:"log"|"progress", ...}). 동시에 conc개씩 만든다
export async function generateAllSkills({signal, onEvent, judge = true, ensemble = true, agent = true, conc = 3}){
  const log = text => onEvent?.({kind: "log", text});
  const cov = await skillCoverage();
  let made = 0, done = 0;
  let total = cov.builtin.filter(b => b.n < BUILTIN_TARGET).length + cov.nvLeft.length;
  const step = label => { done++; onEvent?.({kind: "progress", done, total, made, label}); };
  // 1) 기본 스킬 12개: 분야마다 BUILTIN_TARGET개 이상 (실제 도구 사용 기록 포함)
  for (const b of cov.builtin){
    if (signal?.aborted) return made;
    if (b.n >= BUILTIN_TARGET || !b.topic) continue;
    log(`기본 스킬 '${b.name}' ${BUILTIN_TARGET - b.n}개 만드는 중`);
    made += await generateSynth({topics: [b.topic], count: BUILTIN_TARGET - b.n, judge, ensemble, agent, signal, onEvent: ev => { if (ev.kind === "log") onEvent?.(ev); }});
    step(b.name);
  }
  // 2) NVIDIA 스킬 전부: 스킬마다 지식 문답 + 찾아 읽고 답하는 과정 (실패한 스킬은 최대 3번까지 다시)
  const queue = [];
  const worker = async () => {
    while (queue.length && !signal?.aborted){
      const name = queue.shift();
      try {
        const r = await nvSample(signal, null, name);
        if (!r){ log(`'${name}' 질문을 못 만들어 다음에 다시 합니다`); step(name); continue; }
        const score = r.score ?? (judge ? await judgeScore(r.q, r.text, signal) : null);
        if (score && score < 4){ log(`'${name}' 품질 ${score}점이라 다음에 다시 합니다`); step(name); continue; }
        const base = {src: "synth", topic: "nvidia", score, teacher: r.teacher, skill: name, sources: r.sources};
        await idb.put("train:" + (base.id = uid()), {...base, t: Date.now(), kind: "nvidia", rejected: r.rejected || undefined, messages: [{role: "system", content: TRAIN_SYS("chat")}, {role: "user", content: r.q}, {role: "assistant", content: r.text}]});
        const conv = await nvToolConv(r.q, name, r.text);
        const id2 = uid(); await idb.put("train:" + id2, {...base, id: id2, t: Date.now(), kind: "nvtool", messages: [{role: "system", content: TRAIN_SYS("chat")}, ...conv]});
        made += 2; log(`✓ ${name}`); step(name);
      } catch (e){ if (signal?.aborted) return; log(`'${name}' 건너뜀: ${String(e.message || e).slice(0, 60)}`); step(name); }
    }
  };
  for (let pass = 0; pass < 3 && !signal?.aborted; pass++){
    const left = pass ? (await skillCoverage()).nvLeft : cov.nvLeft;
    if (!left.length) break;
    if (pass){ total = done + left.length; log(`못 넣은 스킬 ${left.length}개를 다시 시도합니다`); }
    queue.push(...left);
    await Promise.all(Array.from({length: Math.max(1, conc)}, worker));
  }
  return made;
}

/* ============ 학습 키트: Colab 노트북 · 로컬 스크립트 ============ */
const pyHeader = ({base, epochs, maxLen, batch, accum, name}) => `BASE = "${base}"   # 바탕 모델 (다른 후보: ${BASES.map(b => b.id).filter(x => x !== base).join(", ")})
EPOCHS = ${epochs}          # 데이터를 몇 번 반복해서 배울지 (샘플이 적으면 3, 많으면 1~2)
MAX_LEN = ${maxLen}       # 한 예시의 최대 길이(토큰)
BATCH = ${batch}
ACCUM = ${accum}
OUT = "${name}"   # 결과 모델 이름
DATA = "nuri-train.jsonl"`;
const pyLoad = `try:
    from unsloth import FastModel as Loader          # 최신 Unsloth (멀티모달 포함)
except ImportError:
    from unsloth import FastLanguageModel as Loader
model, tokenizer = Loader.from_pretrained(model_name=BASE, max_seq_length=MAX_LEN, load_in_4bit=True)
peft = dict(r=16, lora_alpha=16, lora_dropout=0, bias="none", use_gradient_checkpointing="unsloth", random_state=3407)
try:
    model = Loader.get_peft_model(model, finetune_vision_layers=False, finetune_language_layers=True, **peft)
except TypeError:
    model = Loader.get_peft_model(model, target_modules=["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"], **peft)
tok = getattr(tokenizer, "tokenizer", tokenizer)   # 글자용 토크나이저`;
const pyData = `from datasets import load_dataset
ds = load_dataset("json", data_files=DATA, split="train")
def to_text(ex):
    return {"text": tok.apply_chat_template(ex["messages"], tokenize=False)}
ds = ds.map(to_text, remove_columns=ds.column_names)
print("학습 예시", len(ds), "개")
print(ds[0]["text"][:600])`;
const pyTrain = `from trl import SFTTrainer, SFTConfig
cfg = dict(dataset_text_field="text", per_device_train_batch_size=BATCH, gradient_accumulation_steps=ACCUM,
           num_train_epochs=EPOCHS, learning_rate=2e-4, warmup_steps=5, logging_steps=5, optim="adamw_8bit",
           weight_decay=0.01, lr_scheduler_type="linear", seed=3407, output_dir="outputs", report_to="none")
try:
    args = SFTConfig(max_seq_length=MAX_LEN, **cfg)
except TypeError:
    args = SFTConfig(max_length=MAX_LEN, **cfg)
try:
    trainer = SFTTrainer(model=model, tokenizer=tok, train_dataset=ds, args=args)
except TypeError:
    trainer = SFTTrainer(model=model, processing_class=tok, train_dataset=ds, args=args)
stats = trainer.train()
print("학습 끝:", stats)`;
const pyTest = `msgs = [{"role": "system", "content": ${JSON.stringify(TRAIN_SYS("chat"))}},
        {"role": "user", "content": "비트코인 RSI가 25면 어떻게 해석해?"}]
ids = tok.apply_chat_template(msgs, add_generation_prompt=True, return_tensors="pt").to(model.device)
out = model.generate(input_ids=ids, max_new_tokens=300, temperature=0.7, do_sample=True)
print(tok.decode(out[0][ids.shape[-1]:], skip_special_tokens=True))`;
// 모델 융합 2단계: 여러 모델 중 좋은 답(chosen) vs 나쁜 답(rejected)으로 DPO
const pyDPO = `DPO_N = 0
if DATA and DPO_DATA:
    try:
        try:
            from unsloth import PatchDPOTrainer
            PatchDPOTrainer()
        except Exception as e:
            print("PatchDPOTrainer 없이 진행:", e)
        from datasets import load_dataset
        from trl import DPOTrainer, DPOConfig
        pairs = load_dataset("json", data_files=DPO_DATA, split="train")
        def to_pair(ex):
            return {"prompt": tok.apply_chat_template(ex["prompt"], tokenize=False, add_generation_prompt=True),
                    "chosen": ex["chosen"][0]["content"] + tok.eos_token, "rejected": ex["rejected"][0]["content"] + tok.eos_token}
        pairs = pairs.map(to_pair, remove_columns=pairs.column_names)
        DPO_N = len(pairs)
        print("DPO 비교 쌍", DPO_N, "개")
        dcfg = DPOConfig(output_dir="dpo_out", per_device_train_batch_size=1, gradient_accumulation_steps=8, learning_rate=5e-6,
                         num_train_epochs=1, beta=0.1, max_length=MAX_LEN, max_prompt_length=MAX_LEN // 2, logging_steps=5,
                         optim="adamw_8bit", warmup_ratio=0.1, report_to="none", seed=3407)
        kw = dict(model=model, ref_model=None, args=dcfg, train_dataset=pairs)
        try:
            dpo = DPOTrainer(processing_class=tok, **kw)
        except TypeError:
            dpo = DPOTrainer(tokenizer=tok, **kw)
        print("DPO 끝:", dpo.train())
    except Exception as e:
        DPO_N = 0
        print("DPO 단계를 건너뜁니다(SFT 결과는 그대로 씁니다):", e)
else:
    print("DPO 데이터가 없어 건너뜁니다.")`;
const pyGGUF = `import glob, os
model.save_pretrained_gguf(OUT, tokenizer, quantization_method="q4_k_m")   # 앱·llama.cpp가 읽는 GGUF로 변환
files = sorted(glob.glob(OUT + "*/*.gguf") + glob.glob(OUT + "*.gguf") + glob.glob("*.gguf"), key=os.path.getsize)
files = [f for f in files if "q4" in f.lower()] or files
print("만든 파일:", files)
GGUF = files[-1] if files else None
# 앱(브라우저) 안에서 돌리려면 파일 하나가 2GB 이하여야 해서, 크면 1.9GB씩 나눈다
PARTS = [GGUF] if GGUF else []
if GGUF and os.path.getsize(GGUF) > 1.95e9:
    import subprocess
    tool = (glob.glob("llama.cpp/**/llama-gguf-split", recursive=True) + glob.glob(os.path.expanduser("~/.unsloth/llama.cpp/**/llama-gguf-split"), recursive=True) + glob.glob("/root/.unsloth/**/llama-gguf-split", recursive=True))
    if tool:
        prefix = GGUF[:-5] + "-split"
        subprocess.run([tool[0], "--split", "--split-max-size", "1900M", GGUF, prefix], check=True)
        PARTS = sorted(glob.glob(prefix + "-*-of-*.gguf"))
        print("2GB가 넘어 나눴습니다:", PARTS)
    else:
        print("나누기 도구를 찾지 못했습니다. 이 파일은 Ollama로 쓰거나 더 작은 바탕 모델을 고르세요.")`;
// 모델 카드 + Modelfile: 학습 데이터 구성(대화·융합·도구 기록·NVIDIA 스킬)을 세어 기록한다
const pyCard = o => `import json, collections, datetime
kinds = collections.Counter()
with open(DATA, encoding="utf-8") as fh:
    for line in fh:
        ms = json.loads(line)["messages"]
        kinds["도구 사용 기록" if any("<tool name=" in m["content"] for m in ms if m["role"] == "assistant") else "문답"] += 1
card = f"""# ${NAME()}

사용자가 직접 만든 자체 AI 모델입니다. 여러 오픈모델의 답을 하나로 합친 모범답안, 기본·NVIDIA 스킬 지식, 실제 도구(시세·설계·뉴스) 사용 과정을 학습했습니다.

- 바탕 모델: ${o.baseName} ({BASE}) · 라이선스: ${o.lic}
- 학습 방식: LoRA(QLoRA 4비트) {EPOCHS}회 · 최대 길이 {MAX_LEN}
- 학습 예시: {sum(kinds.values())}개 ({dict(kinds)})
- 만든 날: {datetime.date.today()}
- 실행: GH Nano 앱 → 설정 → 학습 · 내 모델 → 내 모델 등록 (GGUF)
"""
open("README.md", "w", encoding="utf-8").write(card)
system = ${JSON.stringify(TRAIN_SYS("chat"))}
open("Modelfile", "w", encoding="utf-8").write(f'FROM ./{os.path.basename(GGUF or "model.gguf")}\\nSYSTEM """{system}"""\\nPARAMETER temperature 0.6\\n')
print(card)`;
export function notebookJSON(o){
  const md = s => ({cell_type: "markdown", metadata: {}, source: s.split(/(?<=\n)/)});
  const code = s => ({cell_type: "code", metadata: {}, execution_count: null, outputs: [], source: s.split(/(?<=\n)/)});
  const cells = [
    md(`# 내 AI 직접 학습 (LoRA 미세조정)\n\n**순서**: 위쪽 메뉴 **런타임 → 런타임 유형 변경 → T4 GPU** 를 고른 뒤 **런타임 → 모두 실행**.\n두 번째 칸에서 앱이 내보낸 \`nuri-train.jsonl\` 파일을 올리라고 나오면 올리세요.\n\n- 바탕 모델: **${o.baseName}** (\`${o.base}\`, 라이선스 ${o.lic})\n- 끝나면 \`${o.name}\`…\`.gguf\` 파일이 내려받아집니다. 앱 → 설정 → 학습 · 내 모델 → **내 모델 등록**에서 그 파일(나뉘었으면 모두)을 고르세요.\n- 무료 Colab은 하루 사용 시간이 정해져 있습니다. 예시 수백 개는 보통 10~30분이면 끝납니다.`),
    code(`%%capture\n!pip install -q unsloth\n!pip install -q --upgrade datasets trl`),
    code(`${pyHeader(o)}\nfrom google.colab import files\nimport os\nif not os.path.exists(DATA):\n    up = files.upload()            # nuri-train.jsonl 올리기\n    DATA = list(up.keys())[0]`),
    md("## 1. 바탕 모델 불러오기 (4비트 QLoRA)"), code(pyLoad),
    md("## 2. 학습 데이터 준비"), code(pyData),
    md("## 3. 학습"), code(pyTrain),
    md("## 4. 시험해 보기"), code(pyTest),
    md("## 5. GGUF로 변환해서 내려받기"), code(`${pyGGUF}\nfor f in PARTS:\n    files.download(f)`),
    md(`## 6. ${NAME()} 모델 카드\n학습 데이터 구성과 사용법을 적은 카드(README.md)와, Ollama를 쓰는 경우를 위한 Modelfile(이름·지시문 포함)을 만듭니다.`),
    code(`${pyCard(o)}\nfiles.download("README.md")\nfiles.download("Modelfile")`)
  ];
  return JSON.stringify({nbformat: 4, nbformat_minor: 5, metadata: {accelerator: "GPU", colab: {provenance: [], gpuType: "T4"}, kernelspec: {name: "python3", display_name: "Python 3"}, language_info: {name: "python"}}, cells}, null, 1);
}
/* ============ GH Nano: 여러 모델을 실제로 합친(머지) 하나의 모델 ============ */
// 같은 뼈대(Qwen2, 28층·1536차원·어휘 151,936)인 공개 모델끼리 TIES 방식으로 가중치를 섞는다.
// 공통 조상(Qwen2.5 1.5B)과의 차이(각 모델이 따로 배운 능력)만 골라 더하므로 서로의 장점이 한 모델에 남는다.
export const NANO_MERGE = {
  name: "GH Nano 1.5B", base: "Qwen/Qwen2.5-1.5B", tokenizer: "Qwen/Qwen2.5-1.5B-Instruct", size: "약 1GB (Q4)",
  models: [
    {id: "Qwen/Qwen2.5-1.5B-Instruct", role: "대화·지시 따르기", weight: 0.4, density: 0.6, lic: "Apache-2.0"},
    {id: "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B", role: "딥시크 R1 추론", weight: 0.3, density: 0.5, lic: "MIT"},
    {id: "Qwen/Qwen2.5-Coder-1.5B-Instruct", role: "코딩", weight: 0.2, density: 0.5, lic: "Apache-2.0"},
    {id: "Qwen/Qwen2.5-Math-1.5B-Instruct", role: "수학·계산", weight: 0.1, density: 0.5, lic: "Apache-2.0"}
  ]
};
export function mergeYAML(p = NANO_MERGE){
  return `# ${p.name}: 여러 모델을 하나로 합치는 설정 (mergekit)
merge_method: ties
base_model: ${p.base}
models:
${p.models.map(m => `  - model: ${m.id}   # ${m.role}\n    parameters:\n      weight: ${m.weight}\n      density: ${m.density}`).join("\n")}
parameters:
  normalize: true
  int8_mask: true
dtype: bfloat16
tokenizer_source: ${p.tokenizer}
`;
}
const indent = c => c.split("\n").map(l => l ? "    " + l : l).join("\n");
export function nanoNotebookJSON(o){
  const p = NANO_MERGE, name = o.name || "gh-nano", srcs = o.sources || [];
  const md = s => ({cell_type: "markdown", metadata: {}, source: s.split(/(?<=\n)/)});
  const code = s => ({cell_type: "code", metadata: {}, execution_count: null, outputs: [], source: s.split(/(?<=\n)/)});
  const header = `BASE = "/content/gh-nano-merged"   # 합친 모델
EPOCHS = ${o.epochs || 2}
MAX_LEN = 2048
BATCH = 2
ACCUM = 4
OUT = "${name}"`;
  const card = `import json, collections, datetime, os, re
kinds = collections.Counter()
nv_skills = set()
if DATA:
    with open(DATA, encoding="utf-8") as fh:
        for line in fh:
            ms = json.loads(line)["messages"]
            kinds["도구 사용 기록" if any("<tool name=" in m["content"] for m in ms if m["role"] == "assistant") else "문답"] += 1
            for m in ms:
                if m["role"] == "assistant":
                    nv_skills.update(re.findall(r'<tool name="nv_skill_read">\{"name":"([^"]+)"', m["content"]))
merged = ${JSON.stringify(p.models.map(m => `${m.id} (${m.role}, 비중 ${m.weight})`))}
fused = ${JSON.stringify(srcs.map(([m, n]) => `${m} (답 ${n}개)`))}
card = f"""# ${NAME()}

연결된 모든 AI 모델과 모든 스킬을 하나로 융합한 자체 AI 모델입니다.

## 융합한 AI 모델 ({len(fused)}개)
같은 질문에 여러 모델이 답하고 순위를 매겨, 가장 좋은 답으로 SFT · 좋은 답 vs 나쁜 답으로 DPO 학습했습니다 (FuseChat-3.0 방식).
""" + ("\\n".join("- " + m for m in fused) or "- (아직 없음)") + f"""

## 몸체 (같은 구조의 오픈모델 가중치를 TIES로 합침, 공통 바탕: ${p.base})
""" + "\\n".join("- " + m for m in merged) + f"""

## 학습
- 1단계 SFT: LoRA(QLoRA 4비트) {EPOCHS}회 · 학습 예시 {sum(kinds.values())}개 {dict(kinds) if kinds else '(학습 데이터 없이 합치기만 함)'}
- 2단계 DPO(모델 간 선호 학습): {DPO_N}쌍
- 데이터: 여러 AI 중 가장 좋은 답, 기본·NVIDIA 스킬 지식, 실제 도구(시세·설계·뉴스) 사용 기록
- NVIDIA 스킬: {len(nv_skills)}개를 찾아 읽고 답하는 법을 학습 (스킬 원문은 GH Nano 앱에 모두 들어 있음)

## 사용법
GH Nano 앱 → 설정 → 학습 · 내 모델 → 내 모델 등록에서 GGUF 파일을 고르세요. 만든 날: {datetime.date.today()}
라이선스: 몸체는 Apache-2.0·MIT입니다. 융합에 답을 쓴 모델들의 이용 약관(예: Llama 라이선스의 표기 의무, 각 API 약관)도 함께 따르세요.
"""
open("README.md", "w", encoding="utf-8").write(card)
system = ${JSON.stringify(TRAIN_SYS("chat"))}
open("Modelfile", "w", encoding="utf-8").write(f'FROM ./{os.path.basename(GGUF or "model.gguf")}\\nSYSTEM """{system}"""\\nPARAMETER temperature 0.6\\n')
print(card)`;
  const cells = [
    md(`# ${NAME()} 만들기 — 모든 AI 모델 + 모든 스킬을 하나의 모델로\n\n**순서**: 위쪽 메뉴 **런타임 → 런타임 유형 변경 → T4 GPU** → **런타임 → 모두 실행**. 파일을 올리라고 나오면 앱에서 받은 \`nuri-train.jsonl\`과 \`nuri-dpo.jsonl\`을 함께 고르세요.\n\n**융합하는 AI 모델 ${srcs.length}개**: ${srcs.length ? srcs.slice(0, 60).map(([m]) => "\`" + m + "\`").join(", ") + (srcs.length > 60 ? " 외 " + (srcs.length - 60) + "개" : "") : "(앱에서 데이터를 먼저 만드세요)"}\n\n구조가 다른 모델(Llama·DeepSeek·Mistral·Qwen·Nemotron…)은 가중치를 그대로 더할 수 없어서, FuseChat-3.0과 같은 **암묵적 모델 융합**을 씁니다: 같은 질문에 여러 모델이 답한 것 중 **가장 좋은 답으로 SFT**, **가장 좋은 답 vs 가장 나쁜 답으로 DPO** 학습해 모든 모델의 장점을 하나에 담습니다.\n\n**몸체**: 같은 Qwen2 구조인 ${p.models.map(m => m.id.split("/")[1]).join(" + ")}를 mergekit TIES로 먼저 합친 ${p.name}.\n\n1) 몸체 합치기 → 2) SFT → 3) DPO → 4) GGUF(${p.size}) 내려받기. 보통 40~90분 걸립니다.`),
    code(`%%capture\n!pip install -q unsloth\n!pip install -q --upgrade datasets trl\n# 합치기 도구(mergekit)는 학습 도구와 버전이 부딪히지 않게 따로 설치\n!python -m venv /content/mkenv\n!/content/mkenv/bin/pip -q install --upgrade pip\n!/content/mkenv/bin/pip -q install torch --index-url https://download.pytorch.org/whl/cpu\n!/content/mkenv/bin/pip -q install mergekit`),
    md("## 1. 몸체 만들기 — 같은 구조 모델 가중치 합치기 (mergekit · TIES)"),
    code(`CONFIG = """${mergeYAML(p)}"""\nopen("gh-nano-merge.yml", "w").write(CONFIG)\nprint(CONFIG)`),
    code(`!/content/mkenv/bin/mergekit-yaml gh-nano-merge.yml /content/gh-nano-merged --lazy-unpickle --copy-tokenizer --out-shard-size 1B\n!ls -la /content/gh-nano-merged`),
    md("## 2. 학습 데이터 올리기 (선택)"),
    code(`${header}\nfrom google.colab import files\nimport os\nDATA = "nuri-train.jsonl" if os.path.exists("nuri-train.jsonl") else None\nDPO_DATA = "nuri-dpo.jsonl" if os.path.exists("nuri-dpo.jsonl") else None\nif not DATA:\n    print("앱에서 받은 nuri-train.jsonl과 nuri-dpo.jsonl을 함께 고르세요(여러 개 선택). 없으면 취소 → 몸체만 만듭니다.")\n    try:\n        up = files.upload() or {}\n        for k in up:\n            if "dpo" in k: DPO_DATA = k\n            elif k.endswith(".jsonl"): DATA = k\n    except Exception as e:\n        print("올리기 건너뜀:", e)\nprint("SFT 데이터:", DATA, "/ DPO 데이터:", DPO_DATA)`),
    md("## 3. 합친 모델 불러오기 (4비트 QLoRA)"), code(pyLoad),
    md("## 4. 모델 융합 1단계 — SFT (모든 AI의 가장 좋은 답 + 스킬 + 도구 사용법)"),
    code(`if DATA:\n${indent(pyData)}\n${indent(pyTrain)}\nelse:\n    print("학습 데이터가 없어 합친 모델 그대로 변환합니다.")`),
    md("## 5. 모델 융합 2단계 — DPO (여러 모델 중 좋은 답을 고르는 감각 학습)"), code(pyDPO),
    md("## 6. 시험해 보기"), code(pyTest),
    md("## 7. GGUF로 변환해서 내려받기"), code(`${pyGGUF}\nfor f in PARTS:\n    files.download(f)`),
    md("## 8. 모델 카드"), code(`${card}\nfiles.download("README.md")\nfiles.download("Modelfile")`)
  ];
  return JSON.stringify({nbformat: 4, nbformat_minor: 5, metadata: {accelerator: "GPU", colab: {provenance: [], gpuType: "T4"}, kernelspec: {name: "python3", display_name: "Python 3"}, language_info: {name: "python"}}, cells}, null, 1);
}
export function localScript(o){
  return `# 내 AI 직접 학습 - 내 노트북(RTX 3050) 버전
# 준비(한 번만): WSL2 Ubuntu 또는 Windows에 Python 3.11과 NVIDIA 드라이버를 설치한 뒤
#   pip install unsloth
#   pip install --upgrade datasets trl
# 실행: 이 파일과 nuri-train.jsonl 을 같은 폴더에 두고  python nuri_train_local.py
# 4GB 그래픽카드는 0.8B~2B 모델, MAX_LEN 1024 이하를 권합니다. 메모리 부족(OOM)이 나면 MAX_LEN을 768로 줄이세요.
# 노트북은 충전기를 꽂고, 학습 중에는 다른 무거운 프로그램을 닫으세요.

${pyHeader(o)}

${pyLoad}

${pyData}

${pyTrain}

${pyTest}

${pyGGUF}
print("완료! 앱 → 설정 → 학습 · 내 모델 → 내 모델 등록에서 다음 파일을 고르세요:", PARTS)
`;
}

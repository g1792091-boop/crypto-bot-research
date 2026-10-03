// 🤖 GH Coin 코인 AI 봇 — '완전 자체' 코인 도우미.
// Dify·Flowise·AnythingLLM 의 핵심(내 지식으로 답하는 RAG + 어디에나 띄우는 채팅 위젯 + 오프라인 동작)을
// 코드 복사 없이 GH Coin 에 맞게 다시 만든 것. 이 앱이 아는 것(전략·백테스트·분석 노트·자체 AI 판단·앱 설명)을
// 지식으로 삼아, 외부 키가 없으면 '추출 답변(자체)'으로, 키가 있으면 그 지식에 근거한 LLM 답변으로 답한다.
// 중요: 이 봇은 설명·판단만 한다. 주문은 절대 내지 않는다(실거래는 live.js 의 한도·승인·긴급정지만).
import { buildIndex, search, contextOf } from "./lib/ragstore.js";
// anythingllm-embed 의 원본 파일을 '그대로' import (vendor/, MIT). CHAT_UI_REOPEN 은 위젯 열림 상태 기억용 키.
import { CHAT_UI_REOPEN } from "./vendor/anythingllm-embed/constants.js";

let ctx = {esc: s => String(s ?? ""), toast: m => console.log(m)};
const esc = s => ctx.esc(s);

/* ---------- 세션/대화기록 보존 (Mintplex-Labs/anythingllm-embed useSessionId.js·useChatHistory 방식 이식, MIT) ----------
   원본: embedId별 localStorage 키 'allm_<embedId>_session_id' 에 uuid 저장→재개, 세션별 기록 보존.
   GH Coin: 브라우저 로컬에만 저장, 서버 없이 동작. 키 접두사만 'ghcoin_coinai_' 로 바꿨다. */
const uuid = () => (crypto?.randomUUID ? crypto.randomUUID() : "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, c => { const r = Math.random() * 16 | 0; return (c === "x" ? r : (r & 0x3 | 0x8)).toString(16); }));
const SID_KEY = "ghcoin_coinai_session_id";
function sessionId(){ try { let id = localStorage.getItem(SID_KEY); if (!id){ id = uuid(); localStorage.setItem(SID_KEY, id); } return id; } catch(e){ return "nostore"; } }
const HIST_KEY = () => `ghcoin_coinai_history_${sessionId()}`;
function loadHistory(){ try { return JSON.parse(localStorage.getItem(HIST_KEY()) || "[]"); } catch(e){ return []; } }
function saveHistory(msgs){ try { localStorage.setItem(HIST_KEY(), JSON.stringify(msgs.slice(-40))); } catch(e){} }
function resetSession(){ try { localStorage.removeItem(HIST_KEY()); localStorage.setItem(SID_KEY, uuid()); } catch(e){} }
let history = [];

/* ---------- 앱 자체 지식 (고정 사실) ---------- */
const APP_KB = [
  {id: "kb-about", title: "GH Coin 이란", text: "GH Coin 은 코인 전문 AI 에이전트 회사 앱이다. 보조지표 분석 → 매매법 개발 → 백테스트 → 데모거래 → 실거래 파이프라인을 팀들이 돌린다. 모든 숫자는 코드가 계산하고, AI 직원은 해설·판단만 한다."},
  {id: "kb-selfai", title: "자체 AI 데스크", text: "외부 LLM 키 없이 앱 안에서 도는 앙상블. 기술 평점(트레이딩뷰식) + 멀티 시간대 종합 + ML 확률(walk-forward) + 알파 팩터를 합쳐 방향과 확신도(0~95)를 낸다. 확신도는 신호 크기와 신호 간 합의로 매긴 참고값이다. 판단만 하고 주문은 내지 않는다."},
  {id: "kb-live", title: "실거래 안전장치", text: "실거래는 기본 꺼짐. 테스트넷 먼저. 전략은 모의투자 14일·청산 20거래·손익비 1.2·수익 0% 초과·낙폭 25% 미만 관문을 통과해야 연결된다. 승인 모드가 기본(주문마다 60초 확인). 한도: 1회 금액·레버리지·동시 포지션·하루 손실·허용 종목. 격리 마진 권장. '모두 정지·청산'은 미체결 취소 + 포지션 시장가 청산 + 실거래 끔."},
  {id: "kb-lev", title: "레버리지·마진 설정", text: "실거래 화면 한도에서 최대 레버리지를 정한다. 레버리지가 높을수록 반대로 조금만 움직여도 청산에 가깝다(대략 100/레버리지 %). 격리 마진은 손실을 그 포지션 증거금으로 한정하고, 교차는 계좌 잔고 전체가 증거금이라 더 위험하다."},
  {id: "kb-bots", title: "선물 자동매매봇", text: "단일 포지션 봇: 추세추종·돌파·평균회귀·슈퍼트렌드·추세 캐리·MACD 추세·켈트너 추세·스토캐스틱RSI 되돌림·변동성(돈치언) 돌파. passivbot·jesse·OctoBot·freqtrade·Binance 선물봇 방식을 규칙만 재구현했다. 모두 백테스트·70/30 검증을 통과해야 데모에 올라간다."},
  {id: "kb-botopt", title: "봇 자동개선", text: "선물 자동매매봇팀이 데모 봇의 보조지표 길이·문턱값과 ROI·손절·추적손절·보호장치를 하이퍼옵트로 다듬는다. 앞 70%에서만 탐색하고 뒤 30% 검증 + 견고성(순열검정·5구간·위생) + 버전관리를 통과한 개선안만 새 버전으로 채택한다."},
  {id: "kb-grid", title: "그리드·DCA 봇", text: "그리드와 DCA(물타기)는 무한 물타기로 청산될 수 있어 연구용 백테스트 전용이다. 실거래로 내보내지 않는다. 지갑 노출 한도와 물타기 횟수 한도로 막고 위험을 백테스트로 보여 준다."},
  {id: "kb-wallet", title: "내 지갑 보기", text: "공개 지갑 주소만 붙여 넣어 목록으로 보관하고 잔액은 블록 익스플로러에서 본다. 개인키·시드문구는 입력하면 막고 저장하지 않는다. 송금·출금·서명 기능은 없다. EVM·BTC·트론·리플·도지·솔라나 주소를 알아본다."},
  {id: "kb-guide", title: "실전 연결 안내", text: "순서: ①테스트넷(가짜 돈) ②거래 전용 키(출금 끄기·IP 제한) ③관문 통과 전략 ④한도·레버리지·마진 ⑤전략 연결 ⑥승인 모드로 실거래 ⑦메인넷 전환(확인 문구) ⑧문제 시 모두 정지·청산."},
  {id: "kb-safe", title: "안전상 넣지 않은 것", text: "남의 개인키·시드로 지갑을 여는 도구(절도)와, 배포 실행 파일에 채굴 기능을 넣어 한 지갑으로 자동 송금하는 악성 형태는 넣지 않았다. 본인 PC에서 합법 채굴 프로그램을 본인 지갑으로 직접 돌리는 것은 자유다. 이 앱에는 자금 보관·출금 기능이 없다."},
  {id: "kb-combo", title: "실시간 종합 지표 타점", text: "차트 터미널의 보조지표 136종을 5·15·60·240분에 실시간 계산해 상승·하락 표와 시간대 점수를 내고, 큰 추세와 작은 타이밍이 맞는 자리에서만 타점(진입·손절·익절)을 잡아 기록장에 남겨 적중률을 검증한다."},
  {id: "kb-nano", title: "학습 데이터(GH Nano)", text: "직원들의 검증된 분석·매매 해설이 학습 예시로 쌓여 자체 소형 모델(GH Nano) 학습 데이터가 된다. Claude·Gemini·GPT 유료 모델이 쓴 글은 약관 때문에 제외한다. 설정에서 .jsonl 로 내려받을 수 있다."},
  {id: "kb-att", title: "ai-trader-team 백테스트", text: "ai-trader-team 의 backtest.py 를 그대로 이식한 백테스터(lib/attbacktest.js): SMA20 상향 돌파 진입·고정 5% 손절·목표 2R·최대 60일 보유·왕복비용 0.1%. 여러 거래를 한 계좌로 묶어 거래당 1% 리스크로 복리 수익률을 낸다. '에이아이 트레이더 백테스트 비트코인'처럼 물으면 일봉으로 돌려 승률·복리수익을 보여 준다."},
  {id: "kb-rigor", title: "리스크 계산기(trading rigor)", text: "ai-trader-team 에서 이식한 결정론적 계산기(lib/rigor.js): 포지션 크기(계좌·리스크%·진입·손절), 손익비(R:R), 실현·미실현 손익을 1R 대비 R-멀티플로, 켈리 기준(full/half/quarter), 포트폴리오 히트(동시 손절 시 계좌 손실률, 기본 한도 6%), 상관계수. 규칙: 트레이드당 계좌의 1% 내외만 리스크로, 손익비는 최소 1.5~2 이상, 모든 포지션 리스크 합(히트)은 6% 이내로 관리한다."},
  {id: "kb-ext", title: "외부 AI 연동", text: "자체 AI 데스크는 외부 키 없이도 돌지만, API 키를 연결하면 외부 LLM 의 방향·확신도 의견을 앙상블의 '한 표'로 더한다(확신도만큼 가중, 과신 방지 상한). 설정에서 끄고 켤 수 있다. 코인 AI 봇도 키가 있으면 더 자연스럽게 답한다."},
  {id: "kb-research", title: "투자 리서치 원칙", text: "agency-agents-ko 투자 리서처 원칙 반영: 강세·약세 케이스를 똑같이 엄격하게 본다. 모든 판단에는 수치화된 근거·반증 조건(무효화 트리거)·투자 기간·확신 수준을 명시한다. 하방 리스크를 수치로. 과거 성과가 미래를 보장하지 않는다. 밸류에이션만으로 사지 않는다(가치 함정 주의)."},
];
const RIGOR_RE = /포지션\s*(크기|사이징)|손익비|리스크\s*리워드|r:?r|켈리|kelly|포트폴리오\s*히트|상관계수|상관관계/i;
async function tryRigor(question){
  if (!RIGOR_RE.test(question)) return null;
  const nums = (question.match(/-?\d+(?:\.\d+)?/g) || []).map(Number);
  try {
    const R = await import("./lib/rigor.js");
    if (/켈리|kelly/i.test(question) && nums.length >= 3){ const k = R.kellyCriterion(nums[0], nums[1], nums[2]); return `켈리 기준 — 승률 ${k.win_rate_pct}%, 손익비 ${k.payoff_ratio}: full ${k.full_kelly_pct}% · half ${k.half_kelly_pct}% · quarter ${k.quarter_kelly_pct}% ${k.has_edge ? "(우위 있음 — 보통 half/quarter 권장)" : "(우위 없음 → 베팅 비추천)"}`; }
    if (/(포지션|사이징)/i.test(question) && nums.length >= 4){ const p = R.positionSize(nums[0], nums[1], nums[2], nums[3]); return `포지션 크기 — 계좌 ${nums[0]}·리스크 ${nums[1]}%·진입 ${nums[2]}·손절 ${nums[3]}: 수량 ${p.shares} · 명목 ${p.position_value} · 리스크 금액 ${p.risk_amount} · 계좌 대비 ${p.position_pct_of_account}%`; }
    if (/(손익비|리스크\s*리워드|r:?r)/i.test(question) && nums.length >= 3){ const rr = R.riskReward(nums[0], nums[1], nums[2]); return `손익비 — 진입 ${nums[0]}·손절 ${nums[1]}·목표 ${nums[2]}: ${rr.direction} · 리스크 ${rr.risk} · 보상 ${rr.reward} · R:R ${rr.risk_reward_ratio}`; }
    if (/(포트폴리오\s*히트)/i.test(question) && nums.length >= 1){ const h = R.portfolioHeat(nums, 6); return `포트폴리오 히트 — 포지션 ${h.n_positions}개 리스크 합 ${h.total_risk_pct}% / 한도 ${h.max_heat_pct}% ${h.over_limit ? "⚠ 초과!" : "(이내)"}`; }
  } catch(e){ return "계산에 필요한 숫자가 부족해요. 예: '포지션 크기 계좌 10000 리스크 1 진입 100 손절 95', '켈리 승률 55 평균승 200 평균손 100'"; }
  return null;
}

let index = null, builtAt = 0, building = null;
async function gatherDocs(){
  const docs = [...APP_KB];
  try {
    const O = await import("./coin-office.js");
    try { const log = await O.loadLog(); for (const e of (log || []).slice(-220)){
      if (e.kind === "table" && e.title){ const body = (e.rows || []).slice(0, 8).map(r => (r || []).join(" ")).join(" · "); docs.push({id: "log-" + e.id, title: e.title, text: `${e.title}. ${body}. ${e.note || ""}`, meta: {kind: "분석"}}); }
      else if ((e.kind === "note" || e.kind === "work") && (e.text || e.result)) docs.push({id: "log-" + e.id, title: e.title || "메모", text: `${e.title || ""} ${e.text || e.result || ""}`, meta: {kind: "메모"}});
    } } catch(err){}
    try { for (const t of (O.TEAMS || [])){ for (const n of (O.teamNotes?.(t.id) || [])) docs.push({id: "note-" + t.id + "-" + n.t, title: `${t.name} 노트`, text: `${t.name}: ${n.text}`, meta: {kind: "노트", team: t.id}}); } } catch(err){}
    try { const board = await (O.researchBoard ? O.researchBoard(16) : []); for (const f of board) docs.push({id: "board-" + f.id, title: `리서치 보드 · ${f.targetName || f.job}`, text: `${f.kind}: ${f.text} (의도 ${f.intent})`, meta: {kind: "리서치보드"}}); } catch(err){}
    try { const skills = await (O.learnedSkills ? O.learnedSkills(20) : []); for (const s of skills) docs.push({id: "skill-" + s.id, title: "배운 것(경험)", text: `${s.text} (${s.uses}회 반복, 신뢰 ${Math.round((s.conf || 0) * 100)}%)`, meta: {kind: "학습"}}); } catch(err){}
    try { const sent = O.marketSentiment ? O.marketSentiment() : null; if (sent) docs.push({id: "sent-latest", title: "시장 심리(자체 감정)", text: `지금 시장 심리 ${sent.score}/100 (${sent.verdict}) — 뉴스·여론 ${sent.n}건 분석`, meta: {kind: "감정"}}); } catch(err){}
  } catch(err){}
  try {
    const P = await import("../nuri-ai/paper.js"), book = await P.loadBook();
    for (const s of (book.strategies || [])){
      const st = s.wf?.oos || {}, tr = (s.trades || []).length;
      docs.push({id: "strat-" + s.id, title: s.name, text: `${s.name} (${s.mname || s.market} ${s.tf}봉). 상태 ${s.status === "active" ? "데모 운용" : s.status || ""}. 거래 ${tr}건. 검증 수익 ${st.ret ?? "?"}% 손익비 ${st.pf ?? "?"}.`, meta: {kind: "전략"}});
    }
  } catch(err){}
  return docs;
}
export async function rebuildKnowledge(){ const docs = await gatherDocs(); index = buildIndex(docs); builtAt = Date.now(); return index.items.length; }
async function ensureIndex(){ if (building) return building; if (!index || Date.now() - builtAt > 60000){ building = rebuildKnowledge().finally(() => building = null); await building; } return index; }

/* ---------- ai-trader-team 백테스트 (이식한 lib/attbacktest.js) ---------- */
const BT_RE = /(ai[- ]?trader|에이아이\s*트레이더).*(백테스트|backtest)|(백테스트|backtest).*(ai[- ]?trader|트레이더\s*팀)/i;
/* ---------- 단타/스윙 포지션 추천 ---------- */
const POS_RE = /단타|스윙|스캘핑|포지션|지금\s*(사|팔|들어가|진입)/i;
async function tryPosition(question){
  if (!POS_RE.test(question)) return null;
  try {
    const O = await import("./coin-office.js"), COINS = O.COINS || [];
    const hit = COINS.find(c => new RegExp(`${c.ko}|${c.sym}|${c.sym.replace("USDT", "")}`, "i").test(question)) || COINS[0];
    if (!O.positionsFor) return null;
    const {scalp, swing} = await O.positionsFor(hit.sym);
    const fx = n => n == null ? "-" : (+n).toLocaleString("ko-KR", {maximumFractionDigits: 8});
    const line = (p, nm) => !p ? `${nm}: 자료 없음` : p.dir === 0 ? `${nm}: 관망 (확신 ${p.confidence}%) — ${p.why}` :
      `${nm}: ${p.dir > 0 ? "롱" : "숏"} (확신 ${p.confidence}%) · 진입 ${fx(p.entry)} · 손절 ${fx(p.sl)} · 익절 ${fx(p.tp)} · 손익비 ${p.rr}`;
    return `🎯 ${hit.ko} 포지션 추천 (자체 AI 방향 + ATR 손절·익절)\n${line(scalp, "단타(5·15분)")}\n${line(swing, "스윙(4시간·일)")}\n※ 매매법을 안 정해도 바로 쓸 참고용입니다. 계산값일 뿐 매매 권유 아니고, 주문은 실거래 화면 승인·한도 안에서만 나갑니다.`;
  } catch(e){ return "포지션을 계산하지 못했어요: " + (e.message || e); }
}
async function tryAttBacktest(question){
  if (!BT_RE.test(question)) return null;
  try {
    const O = await import("./coin-office.js"), COINS = O.COINS || [];
    const hit = COINS.find(c => new RegExp(`${c.ko}|${c.sym}|${c.sym.replace("USDT", "")}`, "i").test(question)) || COINS[0];
    const AT = await import("./lib/attbacktest.js");
    const H = await import("../nuri-ai/history.js").catch(() => null);
    let candles = null;
    try { candles = (await (H ? H.historyCandles({market: hit.sym, exchange: "binancef", interval: "1d", maxBars: 700}) : null))?.candles; } catch(e){}
    if (!candles || !candles.length) return `${hit.ko} 일봉 데이터를 받지 못했어요. 잠시 뒤 다시 시도해 주세요.`;
    const closes = candles.map(b => ({date: new Date(b.t).toISOString().slice(0, 10), close: (b.c ?? b.close)}));
    const trades = AT.simulateTrendStrategy(closes, {sma_window: 20, stop_pct: 5, target_r_multiple: 2, max_hold_days: 60, friction_pct: 0.1});
    const agg = AT.aggregateResults({[hit.sym]: trades}, {risk_pct_per_trade: 1});
    return `ai-trader-team 백테스트 — ${hit.ko} 일봉 ${closes.length}개 · SMA20 돌파 진입·손절 5%·목표 2R(왕복비용 0.1%)\n` +
      `거래 ${agg.n_trades}건 · 승 ${agg.wins} (승률 ${agg.win_rate_pct}%) · 계좌 복리 수익 ${agg.total_return_pct}% (거래당 1% 리스크)\n` +
      `※ ai-trader-team 의 backtest.py 를 그대로 이식한 계산입니다. 참고용이며 주문과 무관합니다.`;
  } catch(e){ return "백테스트를 돌리지 못했어요: " + (e.message || e); }
}

/* ---------- 코인 언급 감지 → 자체 AI 실시간 판단 ---------- */
async function coinSelfAI(question){
  try {
    const O = await import("./coin-office.js"), COINS = O.COINS || [];
    const hit = COINS.find(c => new RegExp(`${c.ko}|${c.sym}|${c.sym.replace("USDT", "")}`, "i").test(question));
    if (!hit) return null;
    const j = await O.selfAIFor(hit.sym);
    return {coin: hit, j};
  } catch(e){ return null; }
}

/* ---------- 답하기 ---------- */
export async function answer(question, {onToken, signal} = {}){
  // 단타/스윙 포지션 추천 명령
  const pos = await tryPosition(question);
  if (pos){ onToken?.(pos); return {text: pos, sources: [{title: "포지션 추천(자체 AI + ATR)", kind: "포지션", score: 1}], selfai: null}; }
  // ai-trader-team 백테스트 명령
  const bt = await tryAttBacktest(question);
  if (bt){ onToken?.(bt); return {text: bt, sources: [{title: "ai-trader-team 백테스트", kind: "백테스트", score: 1}], selfai: null}; }
  // 계산 질문(포지션 크기·손익비·켈리·히트)은 이식한 rigor 로 결정론적으로 먼저 답한다
  const calc = await tryRigor(question);
  if (calc){ onToken?.(calc); return {text: calc, sources: [{title: "리스크 계산기(trading rigor)", kind: "계산", score: 1}], selfai: null}; }
  await ensureIndex();
  const hits = search(index, question, 6);
  const sa = await coinSelfAI(question);
  const saLine = sa ? `[자체 AI 실시간] ${sa.coin.ko}: ${sa.j.label} · 확신도 ${sa.j.confidence}% (${sa.j.reasons.join(" / ")})` : "";
  const context = [saLine, contextOf(hits)].filter(Boolean).join("\n");

  // LLM 이 연결돼 있으면 지식에 근거해 답하고, 없으면 추출 답변(완전 자체)
  let text = "";
  try {
    const E = await import("../nuri-ai/engine.js");
    const sys = "너는 GH Coin 앱의 코인 AI 도우미다. 한국어로 3~6문장, 쉽게 답한다. 아래 '자료'에 있는 내용만 근거로 쓰고, 없으면 모른다고 말한다. 숫자는 자료에 있는 것만. 너는 설명·판단만 하고 주문은 내지 않는다는 점을 필요하면 밝힌다. 투자 조언이 아니라 참고임을 염두에 둔다.";
    const user = `질문: ${question}\n\n자료:\n${context || "(관련 자료를 찾지 못함)"}`;
    await E.brainStream({messages: [{role: "system", content: sys}, {role: "user", content: user}], role: "general", maxTokens: 600, temperature: 0.4, noThink: true, signal,
      onContent: d => { text += d; onToken?.(d); }});
    text = E.splitThink(text).body || text;
  } catch(e){
    // 외부 AI 없음/실패 → 자체 추출 답변
    text = extractive(question, hits, sa);
    onToken?.(text);
  }
  if (!text.trim()) text = extractive(question, hits, sa);
  return {text: text.trim(), sources: hits.map(h => ({title: h.title, kind: h.meta?.kind || "", score: +h.score.toFixed(2)})), selfai: sa};
}

function extractive(question, hits, sa){
  const lines = [];
  if (sa) lines.push(`• 자체 AI 판단 — ${sa.coin.ko}: ${sa.j.label} (확신도 ${sa.j.confidence}%). ${sa.j.reasons.join(" / ")}`);
  if (hits.length){
    lines.push("• 앱 지식에서 찾은 내용:");
    for (const h of hits.slice(0, 3)) lines.push(`  - ${h.title ? h.title + ": " : ""}${(h.text || "").replace(/\s+/g, " ").trim().slice(0, 180)}`);
  }
  if (!sa && !hits.length) return "관련 내용을 앱 지식에서 찾지 못했어요. 더 구체적으로(예: '레버리지 설정', '자체 AI 확신도', '비트코인 방향') 물어봐 주세요. (외부 AI 키를 연결하면 더 자연스럽게 답합니다.)";
  lines.push("\n※ 외부 AI 키가 없어 앱 지식에서 뽑아 요약했어요(완전 자체 모드). 참고용이며 주문은 실거래 화면 승인·한도 안에서만 나갑니다.");
  return lines.join("\n");
}

/* ---------- 떠다니는 채팅 위젯 (어디서나) ---------- */
let root = null, busy = false;
function cssOnce(){ if (document.querySelector("link[data-coinai-css]")) return; const l = document.createElement("link"); l.rel = "stylesheet"; l.href = new URL("./coinai.css", import.meta.url).href; l.dataset.coinaiCss = "1"; document.head.appendChild(l); }

export function mountLauncher(c){
  if (c) ctx = {...ctx, ...c};
  cssOnce();
  if (document.getElementById("caiLauncher")) return;
  const b = document.createElement("button"); b.id = "caiLauncher"; b.className = "cai-fab"; b.title = "코인 AI 봇에게 물어보기"; b.innerHTML = "💬<span>코인 AI</span>";
  b.onclick = () => openCoinAI();
  document.body.appendChild(b);
  try { if (localStorage.getItem(CHAT_UI_REOPEN)) openCoinAI(); } catch(e){}   // anythingllm-embed 방식: 새로고침 전 열려 있었으면 다시 연다
}

export function openCoinAI(c){
  if (c) ctx = {...ctx, ...c};
  cssOnce();
  if (!root){
    root = document.createElement("div"); root.id = "caiPanel"; root.className = "cai-panel"; document.body.appendChild(root);
    root.innerHTML = `<div class="cai-h"><b>🤖 코인 AI 봇</b><span class="cai-badge" id="caiMode">자체(오프라인)</span><span class="cai-sp"></span><button class="cai-mini" data-cai-reset title="대화 초기화(새 세션)">↻</button><button class="cai-x" data-cai-x aria-label="닫기">✕</button></div>
      <div class="cai-body" id="caiBody"></div>
      <div class="cai-in"><input id="caiIn" placeholder="코인·전략·사용법·리스크 계산을 물어보세요" autocomplete="off"><button class="cai-send" data-cai-send>보내기</button></div>`;
    root.addEventListener("click", e => { if (e.target.closest("[data-cai-x]")){ root.hidden = true; try { localStorage.removeItem(CHAT_UI_REOPEN); } catch(err){} } if (e.target.closest("[data-cai-send]")) send(); if (e.target.closest("[data-cai-reset]")){ resetSession(); history = []; renderHistory(); } });
    root.addEventListener("keydown", e => { if (e.key === "Enter" && e.target.id === "caiIn") send(); if (e.key === "Escape") root.hidden = true; });
  }
  root.hidden = false;
  try { localStorage.setItem(CHAT_UI_REOPEN, "1"); } catch(e){}   // anythingllm-embed 방식: 다시 열림 상태 기억
  history = loadHistory();
  renderHistory();
  detectMode();
  setTimeout(() => document.getElementById("caiIn")?.focus(), 50);
}

async function detectMode(){
  try { const E = await import("../nuri-ai/engine.js"); const on = Object.keys(E.PROVIDERS).some(id => E.settings.keys[id]) || E.settings.brain === "local" || E.settings.brain === "ollama";
    const el = document.getElementById("caiMode"); if (el){ el.textContent = on ? "AI 연결됨" : "자체(오프라인)"; el.classList.toggle("on", on); } } catch(e){}
}

function bubble(who, html){ const b = document.getElementById("caiBody"); const d = document.createElement("div"); d.className = "cai-msg " + who; d.innerHTML = `<div class="cai-bub">${html}</div>`; b.appendChild(d); b.scrollTop = b.scrollHeight; return d.querySelector(".cai-bub"); }
const GREETING = '안녕하세요! GH Coin 코인 AI 예요. 이 앱이 아는 것(전략·백테스트·분석·자체 AI 판단·사용법)으로 답해요. 예: <i>"비트코인 지금 방향?"</i>, <i>"레버리지 어떻게 설정해?"</i>, <i>"포지션 크기 계좌 10000 리스크 1 진입 100 손절 95"</i><br><small>참고용이며, 주문은 실거래 화면의 승인·한도 안에서만 나갑니다.</small>';
function renderHistory(){
  const b = document.getElementById("caiBody"); if (!b) return; b.innerHTML = "";
  bubble("bot", GREETING);
  for (const m of history){ const bub = bubble(m.role === "user" ? "me" : "bot", esc(m.text).replace(/\n/g, "<br>")); if (m.role === "bot" && m.sources?.length) bub.insertAdjacentHTML("beforeend", srcHtml(m.sources)); }
}
const srcHtml = sources => `<div class="cai-src">${sources.slice(0, 4).map(s => `<span title="${esc(s.kind || "")} · 관련도 ${s.score}">${esc(s.title || "자료")}</span>`).join("")}</div>`;

async function send(){
  if (busy) return;
  const inp = document.getElementById("caiIn"); const q = (inp.value || "").trim(); if (!q) return;
  inp.value = ""; bubble("me", esc(q));
  history.push({role: "user", text: q}); saveHistory(history);
  const bub = bubble("bot", '<span class="cai-dots"><i></i><i></i><i></i></span>');
  busy = true;
  try {
    let acc = "";
    const r = await answer(q, {onToken: d => { acc += d; bub.innerHTML = esc(acc).replace(/\n/g, "<br>"); document.getElementById("caiBody").scrollTop = 1e9; }});
    bub.innerHTML = esc(r.text).replace(/\n/g, "<br>");
    if (r.sources?.length) bub.insertAdjacentHTML("beforeend", srcHtml(r.sources));
    history.push({role: "bot", text: r.text, sources: r.sources || []}); saveHistory(history);
  } catch(e){ bub.innerHTML = "답하지 못했어요: " + esc(e.message || String(e)); }
  finally { busy = false; }
}

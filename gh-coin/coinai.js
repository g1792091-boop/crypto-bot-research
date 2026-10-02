// 🤖 GH Coin 코인 AI 봇 — '완전 자체' 코인 도우미.
// Dify·Flowise·AnythingLLM 의 핵심(내 지식으로 답하는 RAG + 어디에나 띄우는 채팅 위젯 + 오프라인 동작)을
// 코드 복사 없이 GH Coin 에 맞게 다시 만든 것. 이 앱이 아는 것(전략·백테스트·분석 노트·자체 AI 판단·앱 설명)을
// 지식으로 삼아, 외부 키가 없으면 '추출 답변(자체)'으로, 키가 있으면 그 지식에 근거한 LLM 답변으로 답한다.
// 중요: 이 봇은 설명·판단만 한다. 주문은 절대 내지 않는다(실거래는 live.js 의 한도·승인·긴급정지만).
import { buildIndex, search, contextOf } from "./lib/ragstore.js";

let ctx = {esc: s => String(s ?? ""), toast: m => console.log(m)};
const esc = s => ctx.esc(s);

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
  {id: "kb-safe", title: "안전상 넣지 않은 것", text: "코인 지갑 헌터(남의 개인키·시드로 지갑 열기=절도)와 앱 내장 채굴기+한 지갑 자동 입금(배포 시 크립토재킹 모양)은 넣지 않았다. 본인 PC에서 본인 지갑으로 xmrig 를 직접 돌리는 것은 자유다. 이 앱에는 자금 보관·출금 기능이 없다."},
  {id: "kb-combo", title: "실시간 종합 지표 타점", text: "차트 터미널의 보조지표 136종을 5·15·60·240분에 실시간 계산해 상승·하락 표와 시간대 점수를 내고, 큰 추세와 작은 타이밍이 맞는 자리에서만 타점(진입·손절·익절)을 잡아 기록장에 남겨 적중률을 검증한다."},
  {id: "kb-nano", title: "학습 데이터(GH Nano)", text: "직원들의 검증된 분석·매매 해설이 학습 예시로 쌓여 자체 소형 모델(GH Nano) 학습 데이터가 된다. Claude·Gemini·GPT 유료 모델이 쓴 글은 약관 때문에 제외한다. 설정에서 .jsonl 로 내려받을 수 있다."},
];

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
}

export function openCoinAI(c){
  if (c) ctx = {...ctx, ...c};
  cssOnce();
  if (!root){
    root = document.createElement("div"); root.id = "caiPanel"; root.className = "cai-panel"; document.body.appendChild(root);
    root.innerHTML = `<div class="cai-h"><b>🤖 코인 AI 봇</b><span class="cai-badge" id="caiMode">자체(오프라인)</span><span class="cai-sp"></span><button class="cai-x" data-cai-x aria-label="닫기">✕</button></div>
      <div class="cai-body" id="caiBody"><div class="cai-msg bot"><div class="cai-bub">안녕하세요! GH Coin 코인 AI 예요. 이 앱이 아는 것(전략·백테스트·분석·자체 AI 판단·사용법)으로 답해요. 예: <i>"비트코인 지금 방향?"</i>, <i>"레버리지 어떻게 설정해?"</i>, <i>"봇 자동개선이 뭐야?"</i><br><small>참고용이며, 주문은 실거래 화면의 승인·한도 안에서만 나갑니다.</small></div></div></div>
      <div class="cai-in"><input id="caiIn" placeholder="코인·전략·사용법을 물어보세요" autocomplete="off"><button class="cai-send" data-cai-send>보내기</button></div>`;
    root.addEventListener("click", e => { if (e.target.closest("[data-cai-x]")) root.hidden = true; if (e.target.closest("[data-cai-send]")) send(); });
    root.addEventListener("keydown", e => { if (e.key === "Enter" && e.target.id === "caiIn") send(); if (e.key === "Escape") root.hidden = true; });
  }
  root.hidden = false;
  detectMode();
  setTimeout(() => document.getElementById("caiIn")?.focus(), 50);
}

async function detectMode(){
  try { const E = await import("../nuri-ai/engine.js"); const on = Object.keys(E.PROVIDERS).some(id => E.settings.keys[id]) || E.settings.brain === "local" || E.settings.brain === "ollama";
    const el = document.getElementById("caiMode"); if (el){ el.textContent = on ? "AI 연결됨" : "자체(오프라인)"; el.classList.toggle("on", on); } } catch(e){}
}

function bubble(who, html){ const b = document.getElementById("caiBody"); const d = document.createElement("div"); d.className = "cai-msg " + who; d.innerHTML = `<div class="cai-bub">${html}</div>`; b.appendChild(d); b.scrollTop = b.scrollHeight; return d.querySelector(".cai-bub"); }

async function send(){
  if (busy) return;
  const inp = document.getElementById("caiIn"); const q = (inp.value || "").trim(); if (!q) return;
  inp.value = ""; bubble("me", esc(q));
  const bub = bubble("bot", '<span class="cai-dots"><i></i><i></i><i></i></span>');
  busy = true;
  try {
    let acc = "";
    const r = await answer(q, {onToken: d => { acc += d; bub.innerHTML = esc(acc).replace(/\n/g, "<br>"); document.getElementById("caiBody").scrollTop = 1e9; }});
    bub.innerHTML = esc(r.text).replace(/\n/g, "<br>");
    if (r.sources?.length) bub.insertAdjacentHTML("beforeend", `<div class="cai-src">${r.sources.slice(0, 4).map(s => `<span title="${esc(s.kind)} · 관련도 ${s.score}">${esc(s.title || "자료")}</span>`).join("")}</div>`);
  } catch(e){ bub.innerHTML = "답하지 못했어요: " + esc(e.message || String(e)); }
  finally { busy = false; }
}

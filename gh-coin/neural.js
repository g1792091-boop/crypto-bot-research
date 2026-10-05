// 🧠 뉴럴 데스크 — 연결된 AI 모델(+피처 뉴런)이 "직접" 데모 매매하고, 결과로 채점받아 가중치를 스스로 올리고 내린다.
// 에이전트 '팀 회의'가 아니라, 신호 뉴런들의 온라인 학습(퍼셉트론식)으로 돌아가는 자율 데모 트레이더.
// 전부 가상자금(데모)만 — 실주문·실자금·실지갑 없음.
import { candlesFor, TOOLS } from "../nuri-ai/agent.js";
import { brainStream, settings, saveSettings, PROVIDERS, modelKind, ollamaModels, ollamaPull, webSearch } from "../nuri-ai/engine.js";
import * as BRAIN from "./brain.js";
import { onLeader } from "./leader.js";   // 👑 매매 엔진은 한 창에서만
import * as ENG from "./strategies.js";
import * as CL from "./chartlab.js";
import * as HR from "./lib/holdrules.js";   // 🧘 관망 규칙집(스스로 고치고 검증해 유지/되돌림)
import * as OS from "./lib/olschema.js";    // 🧾 로컬 모델 JSON 스키마 강제

// 📚 코인 선물 매매법 지식베이스 — 뇌에 '매매법·지식·대응'을 처음부터 깔아둔다(교훈 외에 실제 매매법 지식).
const STRATEGY_KB = [
  ["매매법", "RSI 과매수>70 매도·과매도<30 매수 반전 — 추세 역행 금지, 추세장엔 50선 돌파로"],
  ["매매법", "스토캐스틱 %K>%D 골든크로스 매수·80/20 반전 — 횡보장에 유효"],
  ["매매법", "볼린저 스퀴즈 후 확장 돌파 — 거래량 동반 시 추세 방향 진입"],
  ["매매법", "200EMA+Supertrend 스윙 — 200EMA 방향으로만, 전환봉에서 진입"],
  ["매매법", "EMA20 스캘핑 — 20EMA 이탈 후 첫 반대봉 복귀, 손절은 직전 스윙"],
  ["매매법", "VWAP 위 롱·아래 숏 — 세션 VWAP 기준 추세 추종 스캘핑"],
  ["매매법", "Donchian 채널 돌파 추세추종 — ADX>25 필터로 횡보 제외"],
  ["매매법", "피보 38.2~61.8% 되돌림 매수 — 임펄스 후 조정 끝에서"],
  ["매매법", "ICT FVG 되돌림 — 불균형 갭을 채우며 추세 방향 진입"],
  ["매매법", "ICT 오더블록 리테스트 — 변위 전 마지막 반대봉 존 재진입"],
  ["매매법", "유동성 스윕 반전 — 스윙 고/저 쓸고 복귀 시 반대 방향"],
  ["매매법", "MSS 구조전환+변위 진입 — BOS + 큰 몸통봉 동시"],
  ["매매법", "킬존(런던 7~10·뉴욕 13~16 UTC) 모멘텀 — 세션 안에서만 추세방향"],
  ["매매법", "Z-score 평균회귀 — (close-sma)/변동성 ±2 역진입, 0 부근 청산"],
  ["매매법", "다중 MA 정렬(9>50>200) 추세순응 + 9EMA 터치 진입"],
  ["지식", "레버리지 높을수록 청산 빠름 — 변동성 크면 낮게 잡아라"],
  ["지식", "손익비 1:2 이상·단일거래 리스크 1~2%로 자본 보호"],
  ["지식", "추세장=추세추종, 횡보장=역추세/평균회귀 — 국면 구분이 핵심"],
  ["지식", "거래량 없는 돌파는 가짜 돌파가 많다 — 거래량 확인 필수"],
  ["지식", "뉴스·지표 발표 직후 급변동엔 관망하거나 소액, 방향 확정 뒤 진입"],
  ["지식", "연속 손절 시 쿨다운 — 일정 봉 동안 재진입 금지"],
  ["지식", "장 마감·주말 전 오버나이트 리스크 축소"],
];

// 내 PC Ollama 에 설치된 무료 모델 캐시 (주기적으로 갱신 — connectedModels 는 동기라 캐시를 읽는다)
let olCache = [], olInit = false;
export async function refreshOllama() {
  try { olCache = await ollamaModels(); } catch (e) { olCache = []; }
  // 설치된 모델로 엔진 기본 모델을 맞춘다 → 대상 없이 부르는 AI 호출(사무실·리서치)도 로컬 전용에서 실패하지 않게
  if (olCache.length && (!settings.olOk || !olCache.includes(settings.olModel))) { settings.olModel = [...olCache].sort((a, b) => olPref(a) - olPref(b))[0]; settings.olOk = true; try { saveSettings(); } catch (e) {} }
  return olCache;
}

// GH Coin(코인 선물 데모 판단)에 쓸 만한 추천 무료 로컬 모델 — 작고 빠르고 지시·JSON 잘 따르고 한국어 가능한 것 위주.
// 저사양(4GB 그래픽/8GB RAM)은 3b, 여유 있으면 7b 까지. 전부 Ollama 공개 레지스트리 모델.
export const RECOMMENDED_OLLAMA = [
  { model: "qwen2.5:3b", size: "약 2GB", desc: "빠르고 지시·JSON 잘 따름 · 한국어 OK (추천)" },
  { model: "llama3.2:3b", size: "약 2GB", desc: "가볍고 빠른 범용" },
  { model: "qwen2.5:7b", size: "약 4.7GB", desc: "더 똑똑한 판단 (조금 느림, RAM 16GB+ 권장)" }
];
// 추천 모델을 알아서 내려받고(이미 있으면 건너뜀) 끝나면 바로 트레이더·직원으로 쓰이게 한다.
export async function installRecommended(onProgress = () => {}, which = null) {
  const have = new Set(await refreshOllama());
  const list = (which || RECOMMENDED_OLLAMA.map(r => r.model));
  const done = [], failed = [];
  for (const m of list) {
    if (have.has(m) || have.has(m + ":latest")) { onProgress({ model: m, status: "이미 있음", pct: 100 }); done.push(m); continue; }
    try {
      onProgress({ model: m, status: "받는 중", pct: 0 });
      await ollamaPull(m, p => onProgress({ model: m, status: "받는 중", pct: p.total ? Math.round((p.completed || 0) / p.total * 100) : null, raw: p.status }));
      onProgress({ model: m, status: "완료", pct: 100 }); done.push(m);
    } catch (e) { onProgress({ model: m, status: "실패: " + (e?.message || e), pct: null }); failed.push(m); }
  }
  await refreshOllama();                 // 새로 받은 모델을 즉시 트레이더 후보로
  if (done.length) { settings.olOk = true; if (!settings.olModel && done[0]) settings.olModel = done[0]; try { (await import("../nuri-ai/engine.js")).saveSettings?.(); } catch (e) {} }
  return { done, failed, installed: [...new Set([...have, ...done])] };
}

export const localOnly = () => { try { return localStorage.getItem("coinTeamLocal") === "1"; } catch (e) { return false; } };   // 사무실 토글과 공유: 전원 로컬(Ollama) 전용
export const setLocalOnly = (on) => { try { localStorage.setItem("coinTeamLocal", on ? "1" : "0"); } catch (e) {} };
// 트레이더가 될 무료 AI 모델: ① 키 넣은 회사(클라우드) 모델 + ② 내 PC Ollama 로컬 모델(공짜라 한도와 무관하게 추가)
export function connectedModels(maxN = 16) {
  // 로컬: 판단이 약한 초소형(1b~1.5b)보다 지시·추론 되는 3~8b를 우선(4b 근처). 4GB GPU라 최대 6개만.
  const sized = [...olCache].sort((a, b) => olPref(a) - olPref(b)).slice(0, 12).map(m => ({ id: "ollama", model: m }));   // 설치된 Ollama 모델 전부(한 번에 하나씩 호출하므로 4GB GPU 도 순서대로 처리)
  if (localOnly() && sized.length) return sized;
  const out = [];
  for (const id of Object.keys(PROVIDERS || {})) {
    if (!settings?.keys?.[id]) continue;
    const ms = settings.provModels?.[id]?.length ? settings.provModels[id] : (PROVIDERS[id].defaults || []);
    for (const m of ms) { if (["chat", "code", "reason"].includes(modelKind(m))) out.push({ id, model: m }); }
  }
  const cloud = out.slice(0, maxN);
  for (const m of sized) cloud.push(m);   // 로컬도 함께(혼합 모드)
  return cloud;
}
function olSize(name) { const m = String(name).match(/(\d+(?:\.\d+)?)\s*b/i); return m ? +m[1] : 7; }   // 모델명에서 파라미터 수(b) 추정, 없으면 7b
function olPref(name) { const s = olSize(name); return s < 2 ? 100 + (2 - s) : Math.abs(s - 4); }   // 2b 미만은 뒤로, 4b 근처 우선(판단 품질↔속도 균형)

export const COINS = [["BTC", "BTCUSDT"], ["ETH", "ETHUSDT"], ["SOL", "SOLUSDT"], ["XRP", "XRPUSDT"], ["DOGE", "DOGEUSDT"], ["BNB", "BNBUSDT"]];

// 📚 매매법 스타일 로테이션 — 단타·스윙·추세·역추세·돌파·평균회귀·다지표 컨플루언스를 돌아가며 설계한다.
// 차트 터미널 보조지표 146종 전부를 쓰되, 스타일별로 적합한 시간대·접근을 모델에게 안내한다.
// (ICT/SMC·엘리엇파동·세션·아비트라지 계열은 지표가 아니라 가격구조·시간 개념이라 자동 백테스트 대상이 아니다 → 모델의 라이브 판단 지식으로만 활용)
export const STYLES = [
  { k: "scalp_rsi", cls: "단타", tf: "15", iv: "15m", hint: "1분봉 RSI 과매수(>70)/과매도(<30) 반전 스캘핑. 빠른 손절(0.5~1%)·작은 익절. 추세 필터 EMA로 역행 방지." },
  { k: "scalp_bb", cls: "단타", tf: "15", iv: "15m", hint: "1분봉 볼린저밴드 하단 터치 후 밴드 내 복귀=매수, 상단은 반대. tv_bb 사용." },
  { k: "scalp_vwap", cls: "단타", tf: "5", iv: "5m", hint: "VWAP 위면 롱만·아래면 숏만(추세 스캘핑). tv_vwap + 거래량." },
  { k: "scalp_ema", cls: "단타", tf: "5", iv: "5m", hint: "EMA20 잠깐 이탈 후 첫 반대봉 복귀 진입. 손절은 직전 스윙, 익절 1.5R." },
  { k: "scalp_momo", cls: "단타", tf: "5", iv: "5m", hint: "모멘텀 스캘핑: EMA9 + ROC(모멘텀) + 거래량 급증 동시 확인." },
  { k: "swing_st", cls: "스윙", tf: "240", iv: "4h", hint: "200EMA 방향 + Supertrend 전환 동시 확인 스윙. tv_supertrend + tv_ema(200)." },
  { k: "swing_pull", cls: "스윙", tf: "60", iv: "1h", hint: "상승추세에서 EMA20/50 지지 + RSI 40 반등 눌림목 매수(추세 조정)." },
  { k: "swing_brk", cls: "스윙", tf: "60", iv: "1h", hint: "저항(Donchian 상단) 돌파 + 거래량 1.5배 확인 돌파 스윙." },
  { k: "swing_squeeze", cls: "스윙", tf: "60", iv: "1h", hint: "볼린저 스퀴즈(밴드 폭 축소) 후 확장 시 추세 방향 진입." },
  { k: "swing_macross", cls: "스윙", tf: "240", iv: "4h", hint: "10/20 SMA 골든/데드크로스 스윙 + ADX로 추세 강도 필터." },
  { k: "swing_fib", cls: "스윙", tf: "60", iv: "1h", hint: "임펄스 후 되돌림 매수. custom 지표로 (close-최근저점)/(최근고점-최근저점) 비율 활용." },
  { k: "trend_mafan", cls: "추세", tf: "60", iv: "1h", hint: "다중 MA 정렬(EMA9>50>200) 완전 정렬 시 추세 순응 진입." },
  { k: "trend_donchian", cls: "추세", tf: "240", iv: "4h", hint: "Donchian 채널 돌파 추세추종 + ADX>25 필터." },
  { k: "trend_macd", cls: "추세", tf: "60", iv: "1h", hint: "MACD 0선/시그널 교차 추세 + ADX 필터로 횡보 제외." },
  { k: "rev_bb", cls: "역추세", tf: "15", iv: "15m", hint: "볼린저 밴드 외부 종가 후 내부 복귀=평균회귀 반전." },
  { k: "rev_stoch", cls: "역추세", tf: "15", iv: "15m", hint: "스토캐스틱 80 이상 하락전환/20 이하 상승전환 반전." },
  { k: "rev_z", cls: "역추세", tf: "15", iv: "15m", hint: "Z-score 평균회귀: custom expr (close-sma)/변동성 이 -2 이하 롱, +2 이상 숏." },
  { k: "rev_cci", cls: "역추세", tf: "60", iv: "1h", hint: "CCI -100 하향 돌파 후 회복 매수 / +100 반대." },
  { k: "conf_multi", cls: "다지표", tf: "60", iv: "1h", hint: "컨플루언스: RSI+MACD+EMA기울기+거래량을 custom 수식으로 가중 합산한 스코어로 2개 이상 동시 확인." },
  // ICT/SMC · 세션 (새 네이티브 지표 bos/fvg/ob/sweep/disp/premium/session 사용)
  { k: "ict_ob", cls: "ICT", tf: "15", iv: "15m", hint: "오더블록 리테스트 롱: ob==1 (상승 OB 존 되돌림) + premium<0.4 (디스카운트존) + bos 상승. 지표: ob, premium, bos" },
  { k: "ict_fvg", cls: "ICT", tf: "15", iv: "15m", hint: "FVG 되돌림: fvg==1 (상승 불균형) 생성 후 추세방향 진입, ema50 위에서만. 지표: fvg, ema" },
  { k: "ict_sweep", cls: "ICT", tf: "15", iv: "15m", hint: "유동성 스윕 반전: sweep==1 (스윙저점 쓸고 복귀=롱) + bos 확인. 손절은 스윕 꼬리 아래. 지표: sweep, bos" },
  { k: "ict_mss", cls: "ICT", tf: "60", iv: "1h", hint: "MSS 진입: disp(큰 변위봉) + bos(구조 돌파) 동시 = 시장구조전환. 추세방향 진입. 지표: disp, bos" },
  { k: "session_kz", cls: "세션", tf: "15", iv: "15m", hint: "킬존 모멘텀: session(start,end)로 활성 세션(런던 7~10·뉴욕 13~16 UTC)만 + 추세방향(ema/bos) 진입. 지표: session, ema, bos" },
];
let dRot = 0;

// 모델이 이해하기 쉬운 '사람 말' 시장 요약 — 추세·RSI 과매수/과매도·모멘텀을 구체 수치로. (작은 로컬 모델이 타점을 잡게)
export function marketBrief(cs) {
  const c = cs.map(b => b.c), hi = cs.map(b => b.h), lo = cs.map(b => b.l), n = c.length; if (n < 55) return { text: "데이터 부족", rsi: 50, trend: "횡보" };
  const emaAt = (p, end = n) => { const k = 2 / (p + 1); let e = c[Math.max(0, end - 3 * p)]; for (let i = Math.max(1, end - 3 * p + 1); i < end; i++) e = c[i] * k + e * (1 - k); return e; };
  const ema50 = emaAt(50), ema20 = emaAt(20), ema12 = emaAt(12), ema26 = emaAt(26);
  const rsiV = (() => { let g = 0, l = 0; for (let i = n - 14; i < n; i++) { const d = c[i] - c[i - 1]; if (d > 0) g += d; else l -= d; } const rs = l === 0 ? 99 : g / l; return 100 - 100 / (1 + rs); })();
  const last = c[n - 1], emaPct = (last / ema50 - 1) * 100, mom5 = (last / c[n - 6] - 1) * 100, mom20 = (last / c[n - 21] - 1) * 100;
  // MACD(12,26,9) 히스토그램 방향
  const macd = ema12 - ema26; let sig = 0; { const k = 2 / 10; let e = (emaAt(12, n - 8) - emaAt(26, n - 8)); for (let j = n - 8; j <= n; j++) { const mv = emaAt(12, j) - emaAt(26, j); e = mv * k + e * (1 - k); } sig = e; } const macdHist = macd - sig;
  // 볼린저(20,2) %b: 밴드 내 위치(0 하단~1 상단)
  let m20 = 0; for (let i = n - 20; i < n; i++) m20 += c[i]; m20 /= 20; let sd = 0; for (let i = n - 20; i < n; i++) sd += (c[i] - m20) ** 2; sd = Math.sqrt(sd / 20);
  const bbUp = m20 + 2 * sd, bbLo = m20 - 2 * sd, pctB = bbUp > bbLo ? (last - bbLo) / (bbUp - bbLo) : 0.5;
  // 스토캐스틱 %K(14)
  let hh = -Infinity, ll = Infinity; for (let i = n - 14; i < n; i++) { if (hi[i] > hh) hh = hi[i]; if (lo[i] < ll) ll = lo[i]; } const stoK = hh > ll ? (last - ll) / (hh - ll) * 100 : 50;
  // ADX 비슷한 추세강도(최근 변동의 방향 일관성)
  let dir = 0, tot = 0; for (let i = n - 14; i < n; i++) { const ch = c[i] - c[i - 1]; dir += ch; tot += Math.abs(ch); } const adx = tot ? Math.abs(dir) / tot * 100 : 0;
  // 급변동(뉴스성) 감지: 최근 봉 범위가 평소의 2배 넘으면 '이벤트/뉴스 반응' 구간으로 본다
  let rsum = 0; for (let i = n - 20; i < n - 1; i++) rsum += (hi[i] - lo[i]); const avgRange = rsum / 19, lastRange = hi[n - 1] - lo[n - 1]; const spike = avgRange > 0 && lastRange > avgRange * 2;
  const trend = emaPct > 0.3 ? "상승추세" : emaPct < -0.3 ? "하락추세" : "횡보";
  const ob = rsiV >= 72 ? "과매수" : rsiV <= 28 ? "과매도" : rsiV >= 56 ? "약강세" : rsiV <= 44 ? "약약세" : "중립";
  const strong = adx >= 45 ? "강함" : adx >= 25 ? "보통" : "약함(횡보성)";
  return { rsi: Math.round(rsiV), trend, ob, spike, emaPct: +emaPct.toFixed(2), mom5: +mom5.toFixed(2), macdHist: +macdHist.toFixed(2), pctB: +pctB.toFixed(2), stoK: Math.round(stoK), adx: Math.round(adx),
    text: `추세 ${trend}(EMA50 ${emaPct >= 0 ? "+" : ""}${emaPct.toFixed(2)}%, EMA20${last >= ema20 ? "위" : "아래"}) · 추세강도 ${strong}(ADX ${Math.round(adx)}) · RSI ${Math.round(rsiV)}(${ob}) · MACD ${macdHist >= 0 ? "상승" : "하락"} · 볼린저 ${pctB >= 0.8 ? "상단(과열)" : pctB <= 0.2 ? "하단(눌림)" : "중앙"} · 스토캐 ${Math.round(stoK)} · 모멘텀 5분 ${mom5 >= 0 ? "+" : ""}${mom5.toFixed(2)}%` };
}

const KEY = "coin:neural";
const BANKROLL = 1000;        // 💵 전체 가상자금 $1000로 시작 (사용자만 초기화)
const LR = 0.06;              // 피처 뉴런 학습률 (시각화·뇌 학습용)
const FW = ENG.FW;            // 청산 공식 역산 프레임워크 (20x 이상)
const TFMIN = { "1": 1, "5": 5, "15": 15, "60": 60, "240": 240 };
const HTF_OF = { "5": "60", "15": "60", "60": "240", "240": null };
// 워크포워드 선별 규칙 — 실제 데이터 검증: 1시간봉+4H 필터에서 '최근 20건 기대값 > +0.1R' 선별 시 +0.06R/거래(258건)
const SEL = { K: 20, minN: 8, thr: 0.1, lowTfThr: 0.15, lowTfMinN: 15 };
const cl = (v, lo = -1, hi = 1) => Math.max(lo, Math.min(hi, v));

// ── 피처 뉴런: 캔들에서 각자 [-1,1] 신호 (뉴럴 셸 시각화 + 뇌 지능 학습용 — 진입 결정은 전략 엔진이 한다) ──
export const NEURONS = ["모멘텀", "추세(EMA)", "RSI", "거래흐름", "호가압력", "변동성"];
export function featuresOf(cs) {
  const c = cs.map(b => b.c), n = c.length, last = c[n - 1];
  if (n < 55) return Object.fromEntries(NEURONS.map(k => [k, 0]));
  const ema = (p) => { const k = 2 / (p + 1); let e = c[n - 3 * p] ?? c[0]; for (let i = Math.max(1, n - 3 * p + 1); i < n; i++) e = c[i] * k + e * (1 - k); return e; };
  const rsi = (p = 14) => { let g = 0, l = 0; for (let i = n - p; i < n; i++) { const d = c[i] - c[i - 1]; if (d > 0) g += d; else l -= d; } const rs = l === 0 ? 99 : g / l; return 100 - 100 / (1 + rs); };
  const mom = (p) => last / c[n - 1 - p] - 1;
  let vol = 0; for (let i = n - 20; i < n; i++) vol += Math.abs(c[i] / c[i - 1] - 1); vol /= 20;
  let up = 0, dn = 0; for (let i = n - 12; i < n; i++) { if (cs[i].c >= cs[i].o) up += cs[i].v; else dn += cs[i].v; }
  const flow = (up - dn) / (up + dn || 1);
  let bp = 0; for (let i = n - 6; i < n; i++) { const rng = cs[i].h - cs[i].l || 1; bp += ((cs[i].c - cs[i].l) / rng - 0.5) * 2; } bp /= 6;
  return { "모멘텀": cl(mom(5) * 35 + mom(20) * 8), "추세(EMA)": cl((last / ema(50) - 1) * 45), "RSI": cl((rsi() - 50) / 28), "거래흐름": cl(flow * 2), "호가압력": cl(bp * 1.4), "변동성": cl(1 - vol * 55) };
}

// ── 상태 ──
function blank() {
  return { ver: 2, pnl: 0, peak: BANKROLL, fills: 0, wins: 0,
    w: Object.fromEntries(NEURONS.map(k => [k, 1])), hit: Object.fromEntries(NEURONS.map(k => [k, { ok: 0, n: 0 }])),
    models: {}, pos: {}, feat: {}, dec: {}, regime: {}, trades: [], feed: [], epoch: 0, t0: Date.now(),
    eng: { stats: {}, paused: {}, rr: {}, calibAt: 0, calib: null, lastBar: {}, custom: [], evo: [], evoSeeds: [], evoLog: [], chart: [] },
    queue: [], cool: {}, day: { d: "", pnl: 0, eq0: BANKROLL }, news: null, review: null, designs: [] };
}
let S = null;
export function load() {
  if (!S) {
    try { S = JSON.parse(localStorage.getItem(KEY)) || blank(); } catch (e) { S = blank(); }
    const b = blank();
    for (const k of Object.keys(b)) if (S[k] === undefined) S[k] = b[k];
    for (const k of Object.keys(b.eng)) if (S.eng[k] === undefined) S.eng[k] = b.eng[k];
    for (const k of NEURONS) { S.w[k] ??= 1; S.hit[k] ??= { ok: 0, n: 0 }; }
    if (!Number.isFinite(S.pnl)) S.pnl = 0; if (!Number.isFinite(S.peak)) S.peak = BANKROLL;
    for (const n in (S.models || {})) { const m = S.models[n]; if (!Number.isFinite(m.pnl)) m.pnl = 0; m.fills = +m.fills || 0; m.wins = +m.wins || 0; m.pos = {}; }
    // 엔진 v1 → v2: 예전 포지션(근거 없는 진입)은 다음 시세에서 정리(손익 반영)하고, 거래 기록은 보존한다. 자본 초기화는 사용자만.
    if (S.ver !== 2) { S.legacy = Object.values(S.pos || {}); S.pos = {}; S.ver = 2; S.queue = []; }
    if (Array.isArray(S.eng.ensW) && S.eng.ensW.length === 6) ENG.ENS.w = S.eng.ensW;   // 최적화된 앙상블 가중치 복원
    S.hold = HR.normBook(S.hold);
  }
  return S;
}
function save() { try { localStorage.setItem(KEY, JSON.stringify({ ...S, trades: S.trades.slice(0, 80), feed: S.feed.slice(0, 40) })); } catch (e) {} }
export function reset() { const keep = S?.eng?.stats, hb = S?.hold; S = blank(); if (keep) S.eng.stats = keep; S.hold = HR.normBook(hb); save(); return S; }   // 자본만 초기화(전략 검증 기록은 유지)
const feed = (t) => { S.feed.unshift({ t: Date.now(), text: t }); if (S.feed.length > 40) S.feed.pop(); };

// 💵 자금·낙폭 방어
export function equity() { return +(BANKROLL + (S?.pnl || 0)).toFixed(2); }
function riskFactor() { const eq = equity(), peak = Math.max(S?.peak || BANKROLL, eq); if (eq < BANKROLL * 0.9) return 0.5; if (eq < peak * 0.93) return 0.5; return 1; }
function bumpPeak() { if (S) S.peak = Math.max(S.peak || BANKROLL, equity()); }
export const riskMode = () => riskFactor() < 1 ? "방어(리스크 절반)" : "정상";
export const LEV_CAP = ENG.levCapOf;
const today = () => new Date().toISOString().slice(0, 10);
function dayGate() { const d = today(); if (S.day.d !== d) S.day = { d, pnl: 0, eq0: equity() }; return S.day.pnl > -FW.dailyStop * S.day.eq0; }

// ── 🎭 데스크 감정 상태 — 모델이 스스로 '느낌'을 지어내지 않게, 코드가 성적·낙폭·시장 지수로 계산한다(FenixAI·ffrdm 의 감정/피로 개념) ──
//   효과는 실측된 것만: 피로(연속 손실) → 관망 규칙집의 휴식 · 공포(낙폭) → 리스크 절반(riskFactor) · 낙폭 30% → 24시간 신규 진입 중지.
//   탐욕(연속 이익)은 비중을 줄이지 않는다 — 1년 실측에서 연속 3이익 뒤 거래가 오히려 평균 +0.23R 이었다.
const closedSeq = () => [...(S.trades || [])].reverse().map(t => ({ R: t.R, t1: t.t }));   // 시간순 청산 기록
function streaks() { let L = 0, W = 0; for (const t of S.trades || []) { if (t.R < 0) L++; else break; } for (const t of S.trades || []) { if (t.R > 0) W++; else break; } return { L, W }; }
export function mood() {
  load(); const { L, W } = streaks(), eq = equity(), peak = Math.max(S.peak || BANKROLL, eq), dd = peak > 0 ? (peak - eq) / peak * 100 : 0, now = Date.now();
  const f = S.fng && now - S.fng.t < 30 * 3600e3 ? S.fng : null, rest = HR.restUntil(S.hold, closedSeq());
  const fear = Math.min(10, Math.round(dd / 3 + (f ? (f.v < 25 ? 3 : f.v < 45 ? 1 : 0) : 0) + ((S.news?.score ?? 0) <= -1 && now - (S.news?.t || 0) < 3 * 3600e3 ? 1 : 0)));
  const greed = Math.min(10, Math.round(W * 2.5 + (f ? (f.v > 75 ? 3 : f.v > 55 ? 1 : 0) : 0))), fatigue = Math.min(10, L * 3);
  const act = variants().filter(isActive).length, conf = Math.max(0, Math.min(10, Math.round(4 + Math.min(3, act) - fear / 2 - fatigue / 3)));
  const notes = [];
  if ((S.halt || 0) > now) notes.push(`낙폭 서킷브레이커 — ${Math.ceil((S.halt - now) / 3600e3)}시간 신규 진입 중지`);
  if (rest > now) notes.push(`${L}연속 손실 → 휴식 ${Math.ceil((rest - now) / 3600e3)}시간 남음`);
  if (riskFactor() < 1) notes.push("낙폭 방어 — 리스크 절반");
  if (W >= 3) notes.push(`${W}연속 이익 — 비중 유지(축소는 실측상 손해)`);
  return { fear, greed, fatigue, conf, L, W, dd: +dd.toFixed(1), act, rest: rest > now ? rest : 0, halt: (S.halt || 0) > now ? S.halt : 0, fng: f, notes };
}
export const moodText = () => { const m = mood(); return `데스크 감정(코드 계산): 공포 ${m.fear}/10 · 탐욕 ${m.greed}/10 · 피로 ${m.fatigue}/10(${m.L}연패) · 확신 ${m.conf}/10${m.notes.length ? " · " + m.notes.join(" · ") : ""}`; };
// 😱 공포탐욕지수(alternative.me, 하루 1번 갱신) + 어제 대비 변화·급변 표시(FenixAI 형식 "20 (어제 27, −7)")
//   1년 실측에서 극단값 관망 규칙은 성적을 올리지 못했다 → 기본은 '정보'로만(AI 판단 자료·감정 상태). 관망 규칙집의 fng 규칙은 데이터가 지지하면 진화가 켠다.
const fngKo = v => v < 25 ? "극단적 공포" : v < 45 ? "공포" : v <= 55 ? "중립" : v <= 75 ? "탐욕" : "극단적 탐욕";
let fngAt = 0, fngHist = null;
export async function fngCheck(force = false) {
  load(); if (!force && Date.now() - fngAt < 30 * 60e3) return S.fng; fngAt = Date.now();
  try { const { webGet } = await import("../nuri-ai/engine.js"), j = await webGet("https://api.alternative.me/fng/?limit=90&format=json", "json"), d = j?.data || [];
    const v = +d[0]?.value, y = +d[1]?.value; if (!Number.isFinite(v)) return S.fng;
    fngHist = Object.fromEntries(d.map(x => [new Date(+x.timestamp * 1000).toISOString().slice(0, 10), +x.value]));
    const ch = Number.isFinite(y) ? v - y : 0, sev = Math.abs(ch) > 10 ? "급변" : Math.abs(ch) > 5 ? "큰 변화" : "";
    const was = S.fng; S.fng = { v, y: Number.isFinite(y) ? y : null, ch, sev, label: fngKo(v), t: Date.now() };
    if (!was || was.v !== v) feed(`😱 공포탐욕지수 ${v}(${S.fng.label}) · 어제 ${S.fng.y ?? "?"} → ${ch > 0 ? "+" : ""}${ch}${sev ? " · " + sev : ""}`);
    save(); } catch (e) {}
  return S.fng;
}
export const fngText = () => S?.fng ? `공포탐욕지수 ${S.fng.v}(${S.fng.label} · 어제 ${S.fng.y ?? "?"}, ${S.fng.ch > 0 ? "+" : ""}${S.fng.ch}${S.fng.sev ? " · " + S.fng.sev : ""})` : "공포탐욕지수 없음";
// 👻 관망한 신호도 채점: 막은 신호를 실제 봉으로 따라가 '손절 먼저(관망이 옳았음) / 익절 먼저(관망이 손해)'를 기록
function shadowAdd(x) {
  const L = (S.shadow ||= []); if (L.some(y => y.sym === x.sym && y.side === x.side && Date.now() - y.t < 3600e3)) return;
  const rD = Math.abs(x.px - x.sl); if (!(rD > 0)) return;
  L.unshift({ ...x, tp: x.px + x.side * rD * x.rr, t: Date.now() }); S.shadow = L.slice(0, 150);
}
let shAt = 0;
async function scoreShadow() {
  if (Date.now() - shAt < 120e3) return; shAt = Date.now();
  for (const x of (S.shadow || []).filter(y => !y.res).slice(0, 6)) {
    let cs; try { cs = (await candlesFor({ market: x.sym, exchange: "binancef", timeframe: "15" }, 300)).cs; } catch (e) { continue; }
    let res = null;
    for (const b of cs || []) { if (b.t + 900e3 <= x.t) continue; if (x.side > 0 ? b.l <= x.sl : b.h >= x.sl) { res = "손절"; break; } if (x.side > 0 ? b.h >= x.tp : b.l <= x.tp) { res = "익절"; break; } }
    if (!res && Date.now() - x.t > 48 * 3600e3) res = "무승부"; if (!res) continue;
    x.res = res; x.R = res === "손절" ? -1 : res === "익절" ? x.rr : 0;
    const H = ((S.holdScore ||= {})[x.rule] ||= { n: 0, right: 0, R: 0 }); if (res !== "무승부") { H.n++; if (res === "손절") H.right++; H.R = +(H.R + x.R).toFixed(2); }
    feed(`👻 관망 채점: ${x.ko} ${x.side > 0 ? "롱" : "숏"}(${x.name}) → ${res === "손절" ? "손절 먼저 — 관망이 옳았음" : res === "익절" ? `익절 먼저 — 관망이 ${x.rr}R 놓침` : "48시간 무승부"}`);
  }
  save();
}
export function holdState() { load(); return { book: S.hold, rules: HR.RULES.map(r => ({ id: r.id, label: r.label, on: !!S.hold.rules[r.id]?.on, text: HR.ruleText(r.id, S.hold.rules[r.id]?.p), score: S.holdScore?.[r.id] || null })),
  eval: S.holdEval || null, prop: S.holdProp || null, log: (S.hold.log || []).slice(0, 12), shadow: (S.shadow || []).slice(0, 8) }; }

// ── 전략 변형(매매법 × 시간봉) 목록: 사용자 목록 규칙 + AI가 개발해 검증 통과한 매매법 ──
let Q = null; const quant = async () => (Q ||= await import("../nuri-ai/quant.js"));
function variants() {
  const out = [];
  for (const r of ENG.LIB) { out.push({ ...r, vkey: `${r.key}@${r.tf}` }); if (r.tf === "5" || r.tf === "15") out.push({ ...r, tf: "60", hold: 48, vkey: `${r.key}@60` }); }
  out.push({ key: "aichart", vkey: "aichart@15", tf: "15", name: "🤖 AI 내 지표 실험", cat: "단타", mode: "trend", rr: 2, hold: 32, regimes: null, sig: () => null, exp: true });
  for (const g of S.eng.chart || []) { const r = CL.chartRule(g); out.push({ ...r, prep: r.prep, sig: r.sig, exit: r.exit, vkey: `${r.key}@${r.tf}` }); }   // 📈 내 차트 지표 매매법(연구소에서 데모 투입)
  for (const e of S.eng.evo || []) { const r = ENG.buildEvo(e.gene); if (r) out.push({ ...r, vkey: `${r.key}@60`, tf: "60" }); }   // 🧬 진화 변형(개선·수정·조합)
  if (Q) for (const c of S.eng.custom || []) { const rr = ENG.specRule(Q, c); out.push({ ...rr, prep: rr.prep, sig: rr.sig, exit: rr.exit, vkey: `${c.key}@${c.tf}` }); }
  return out;
}
const VMAP = () => Object.fromEntries(variants().map(v => [v.vkey, v]));
function vstat(vkey) {
  const st = S.eng.stats[vkey]; if (!st || !st.tr?.length) return { n: 0, mean: 0, wr: 0, live: 0, bt: 0 };
  const last = st.tr.slice(-SEL.K), n = last.length, mean = n ? last.reduce((a, t) => a + t.R, 0) / n : 0;
  return { n, mean: +mean.toFixed(3), wr: n ? Math.round(last.filter(t => t.R > 0).length / n * 100) : 0, live: st.tr.filter(t => t.src === "live").length, bt: st.tr.filter(t => t.src === "bt").length, all: st.tr.length };
}
// 활성 = 최근 성과로 검증됨(워크포워드). 5·15분봉 스캘핑은 수수료 비중이 커서 더 높은 기준(검증상 마이너스 경향)
function isActive(v) {
  if ((S.eng.paused[v.vkey] || 0) > Date.now()) return false;
  const s = vstat(v.vkey), low = v.tf === "5" || v.tf === "15";
  return low ? (s.n >= SEL.lowTfMinN && s.mean > SEL.lowTfThr) : (s.n >= SEL.minN && s.mean > SEL.thr);
}
function riskFor(v, side) {
  const s = vstat(v.vkey); let r = s.n >= 15 && s.mean > 0.25 ? FW.maxRisk : FW.baseRisk;
  r *= riskFactor();
  const nw = S.news; if (nw && Date.now() - nw.t < 3600e3) { if (side > 0 && nw.score <= -1) r *= 0.5; if (side < 0 && nw.score >= 1) r *= 0.5; }
  const th = BRAIN.timeAdvice(new Date().getHours()); if (th && th.n >= 8 && !th.good) r *= 0.5;   // 학습상 안 되는 시간대
  return Math.max(0.0025, r);
}
const rrFor = v => Math.max(1.3, Math.min(3, S.eng.rr[v.vkey] ?? v.rr));

// ── 시세 캐시 (메모리) ──
const MK = {};   // `${sym}|${tf}` → {cs, I, at}
async function getTF(sym, tf, n = 420) {
  const k = sym + "|" + tf; let cs;
  try { cs = (await candlesFor({ market: sym, exchange: "binancef", timeframe: tf }, n)).cs; } catch (e) { return MK[k] || null; }
  if (!cs || cs.length < 220) return MK[k] || null;
  const last = cs.at(-1).t;
  if (MK[k] && MK[k].last === last && MK[k].len === cs.length && MK[k].lc === cs.at(-1).c) return MK[k];
  const q = await quant();
  MK[k] = { cs, I: ENG.prepare(q, cs), last, len: cs.length, lc: cs.at(-1).c, H: null };
  return MK[k];
}

// ── 포지션 (코인당 1개 · 원웨이 모드 · 물타기 금지) ──
function markPos(P, price) { const proe = (price - P.entry) / P.entry * P.side * 100; P.proe = +proe.toFixed(3); P.roe = +(proe * P.lev).toFixed(2); P.price = price; return proe; }
// siropkin/robinhood-ai-trading-bot 의 제약(포트폴리오 상한·제외 종목·최소/최대 금액·PDT 제한)을 선물용으로:
//   동시 포지션 상한 · 제외 코인 · 하루 최대 진입 수(과매매 방지 = PDT 대응) · 청산 후 같은 코인 재진입 쿨다운
const CFG0 = { maxPos: 4, exclude: [], dailyMax: 12, coolMin: 30 };
export const cfg = () => ({ ...CFG0, ...(load().cfg || {}) });
export function setCfg(patch = {}) { load(); const c = { ...cfg(), ...patch };
  c.maxPos = Math.max(1, Math.min(6, Math.round(+c.maxPos || 4))); c.dailyMax = Math.max(1, Math.min(50, Math.round(+c.dailyMax || 12))); c.coolMin = Math.max(0, Math.min(240, Math.round(+c.coolMin || 0)));
  c.exclude = (Array.isArray(c.exclude) ? c.exclude : String(c.exclude || "").split(/[,\s]+/)).map(x => String(x).toUpperCase().replace(/USDT$/, "")).filter(x => COINS.some(([ko]) => ko === x));
  S.cfg = c; save(); return c; }
function heat() { let r = 0; for (const P of Object.values(S.pos)) r += P.be ? 0 : (P.risk || 0); return r; }
// 🏢 에이전트 팀 판정도 뉴럴 진입에 실제 반영: 리스크 결정표·경제 캘린더·자체 AI 앙상블·TA 평점·재고(쏠림) 위험(SolTrade·Guéant)
function teamCheck(it) {
  const J = k => { try { return JSON.parse(localStorage.getItem(k) || "null"); } catch (e) { return null; } };
  const id = it.sym.replace(/USDT$/, "").toLowerCase(), now = Date.now(), fresh = (o, h) => o && now - o.t < h * 3600e3; let mul = 1; const why = [];
  const rv = J("coinRiskVerdict")?.[id]; if (fresh(rv, 26) && /거래 정지|신규 진입 보류/.test(rv.act || "")) return { block: `리스크 결정표 '${rv.act}'` };
  if (fresh(rv, 26) && rv.act === "비중 절반") { mul *= 0.5; why.push("결정표 비중 절반"); }
  const ev = (J("coinCalendar")?.events || []).find(e => Math.abs(e.t - now) < 30 * 60e3); if (ev) return { block: `고영향 일정 ±30분(${ev.name})` };
  const sa = J("coinSelfAI")?.[id]; if (fresh(sa, 6) && sa.conf >= 60 && sa.dir === -it.side) return { block: `자체 AI 앙상블 반대 ${sa.conf}%` };
  const tr = J("coinTARating")?.[id]; if (fresh(tr, 6) && tr.all != null && tr.all * it.side <= -0.5) { mul *= 0.6; why.push(`TA 평점 반대(${tr.label})`); }
  const same = Object.values(S.pos).filter(p => p.side === it.side).length; if (same >= 3) { mul *= 0.5; why.push(`재고 쏠림(같은 방향 ${same}개)`); }
  return { mul, why: why.join(" · ") };
}
function openFrom(it, trader, riskOverride, note) {
  const price = S.dec[it.sym]?.price; if (!price || S.pos[it.sym]) return false;
  const tc = teamCheck(it); if (tc.block) { feed(`🚦 ${it.ko} ${it.name} 차단 — 에이전트 팀 판정: ${tc.block}`); return false; }
  // 🧠 뇌 점검: 과거 손절 함정과 닮은 자리면 차단, 핵심 '조심' 규칙이면 리스크 절반
  { const f0 = S.feat[it.sym] || {}, bg = BRAIN.gateCheck(f0, BRAIN.regimeOf(f0), it.side);
    if (bg.block) { feed(`🧠 ${it.ko} ${it.name} 차단 — ${bg.why}`); return false; }
    if (bg.mul < 1) { tc.mul = (tc.mul ?? 1) * bg.mul; tc.why = (tc.why ? tc.why + " · " : "") + bg.why; } }
  // 📅 일봉 추세 역행이면 리스크 절반 (4년·6코인 검증에서 우위가 확인된 건 일봉 추세 방향뿐 — lib/swing.js)
  { let dt = null; try { dt = JSON.parse(localStorage.getItem("coinDailyTrend") || "{}")[String(it.ko).toLowerCase()]; } catch (e) {}
    if (dt?.dir && dt.dir === -it.side && Date.now() - (dt.t || 0) < 3 * 864e5) { tc.mul = (tc.mul ?? 1) * 0.5; tc.why = (tc.why ? tc.why + " · " : "") + `일봉 추세(${dt.label}) 역행 → 리스크 절반`; } }
  // 📋 주문 미리보기(review → confirm → place, kevin1chun/robinhood-for-agents): 가격 칼라 + 포트폴리오 한도를 코드로 확인한 뒤에만 체결
  const C = cfg(), rD = Math.abs((it.px0 || price) - it.sl), moved = it.px0 ? (price - it.px0) * it.side : 0;
  if (it.px0 && rD > 0 && moved > 0.35 * rD) { feed(`📋 ${it.ko} ${it.name} 취소 — 가격 칼라: 신호 후 이미 ${(moved / rD).toFixed(2)}R 진행(추격 금지)`); return false; }
  if (it.px0 && rD > 0 && moved < -0.5 * rD) { feed(`📋 ${it.ko} ${it.name} 취소 — 가격 칼라: 손절 쪽으로 ${(-moved / rD).toFixed(2)}R 밀림`); return false; }
  if (Object.keys(S.pos).length >= C.maxPos) { feed(`📋 ${it.ko} 보류 — 동시 포지션 상한 ${C.maxPos}개`); return false; }
  dayGate(); if ((S.day.n || 0) >= C.dailyMax) { feed(`📋 ${it.ko} 보류 — 오늘 진입 ${S.day.n}회 = 하루 상한(과매매 방지)`); return false; }
  if (C.exclude.includes(it.ko)) return false;
  // 🐋 고래 카피 신호(casatrickdev 감지→필터→리스크→신호): 승인된 고래 흐름이 반대면 리스크 절반, 같은 방향이면 근거로 기록
  if (it.whale?.status === "approved" && it.whale.dir) { if (it.whale.dir === -it.side) { tc.mul *= 0.5; tc.why = (tc.why ? tc.why + " · " : "") + `고래 반대(순 ${it.whale.netPct}%)`; } else tc.why = (tc.why ? tc.why + " · " : "") + `고래 동행(순 ${it.whale.netPct}%)`; }
  if ((it.side > 0 && price <= it.sl) || (it.side < 0 && price >= it.sl)) { feed(`${it.ko} ${it.name} 신호 무효 — 가격이 이미 손절선 너머`); return false; }
  const v = VMAP()[it.vkey]; if (!v) return false;
  const r = it.exp ? 0.0025 : Math.max(0.0025, (riskOverride ?? riskFor(v, it.side)) * tc.mul); if (tc.why) note = (note ? note + " · " : "") + "팀: " + tc.why;
  const plan = ENG.frameworkPlan({ sym: it.sym, entry: price, side: it.side, slPrice: it.sl, cat: v.cat, rr: rrFor(v), riskPct: r, equity: equity() });
  if (!plan || plan.skip) { feed(`${it.ko} ${it.name} 보류 — ${plan?.skip || "계획 실패"}`); return false; }
  if (heat() + plan.risk > FW.maxHeat * equity()) { feed(`${it.ko} 보류 — 동시 보유 리스크 한도(자본 ${FW.maxHeat * 100}%)`); return false; }
  const feat = S.feat[it.sym] || {};
  S.pos[it.sym] = { sym: it.sym, ko: it.ko, side: it.side, entry: price, price, sl: plan.sl, tp: plan.tp, liq: plan.liq, lev: plan.lev, margin: plan.margin, notional: plan.notional,
    risk: plan.risk, riskPct: plan.riskPct, rr: plan.rr, slPct: plan.slPct, tpPct: plan.tpPct, rDist: Math.abs(price - plan.sl), be: false, roe: 0, proe: 0, seed: +(plan.margin / equity() * 100).toFixed(1),
    vkey: it.vkey, name: it.name, cat: v.cat, tf: v.tf, why: it.why, regime: it.regime, regKey: it.regKey, trader, t: Date.now(), deadline: Date.now() + v.hold * TFMIN[v.tf] * 60e3,
    hour: new Date().getHours(), spike: !!S.brief?.[it.sym]?.spike, feat: { ...feat }, bReg: BRAIN.regimeOf(feat) };
  if (trader !== "자체 엔진") { const M = model(trader); M.opened = (M.opened || 0) + 1; }
  S.day.n = (S.day.n || 0) + 1;
  feed(`${trader === "자체 엔진" ? "" : "[" + shortMd(trader) + "] "}${it.ko} ${it.side > 0 ? "▲롱" : "▼숏"} ${plan.lev}x @ ${fmt(price)} · ${it.name} · SL ${plan.slPct}% / TP ${plan.tpPct}%(손익비 1:${plan.rr}) · 리스크 $${plan.risk}(${plan.riskPct}%)${note ? " · " + note : ""}`);
  return true;
}
function closeP(sym, px, why, at) {
  const P = S.pos[sym]; if (!P) return;
  const base = String(why).replace(/\(.*\)$/, "");   // "익절(놓친 봉 반영)" → "익절"
  const pret = (px - P.entry) / P.entry * P.side - FW.fee;
  let pnl = base === "청산" ? -P.margin : Math.max(-P.margin, P.notional * pret); if (!Number.isFinite(pnl)) pnl = 0;
  const R = P.risk ? pnl / P.risk : 0, roe = P.margin ? pnl / P.margin * 100 : 0;
  S.pnl += pnl; S.fills++; if (pnl > 0) S.wins++; bumpPeak(); dayGate(); S.day.pnl += pnl;
  if (P.trader !== "자체 엔진") { const M = model(P.trader); M.pnl += pnl; M.fills++; if (pnl > 0) M.wins++; }
  // 전략 성적(실전) 기록 → 워크포워드 선별에 즉시 반영
  const st = (S.eng.stats[P.vkey] ||= { tr: [] }); st.tr.push({ R: +R.toFixed(3), t1: Date.now(), src: "live", reg: P.regKey }); if (st.tr.length > 60) st.tr.splice(0, st.tr.length - 60);
  if (base === "손절" || base === "청산") S.cool[sym] = Date.now() + 2 * TFMIN[P.tf || "60"] * 60e3;
  S.cool[sym] = Math.max(S.cool[sym] || 0, Date.now() + cfg().coolMin * 60e3);   // 어떤 청산이든 설정한 분만큼 같은 코인 재진입 금지   // 쿨다운: 손절 후 2봉 재진입 금지
  S.trades.unshift({ ko: P.ko, side: P.side, entry: P.entry, exit: px, lev: P.lev, margin: Math.round(P.margin), roe: +roe.toFixed(2), pnl: +pnl.toFixed(2), R: +R.toFixed(2), why, name: P.name, model: P.trader !== "자체 엔진" ? P.trader : null, at: at || null, t: Date.now() });
  if (S.trades.length > 80) S.trades.pop();
  // 학습: 뉴런(시각화) · 뇌 지능 · 시간대 · 급변동 · 교훈/패턴
  const good = pret > 0 ? 1 : -1;
  for (const k of NEURONS) { const sig = P.feat?.[k] || 0; if (Math.abs(sig) < 0.08) continue; const correct = (Math.sign(sig) === P.side ? 1 : -1) === good; S.hit[k].n++; if (correct) S.hit[k].ok++; S.w[k] = cl(S.w[k] + LR * (correct ? 1 : -1) * Math.abs(sig), 0.05, 3); }
  BRAIN.learnOutcome({ coin: P.ko, regime: P.bReg, feat: P.feat, dir: P.side, pnl: pret });
  if (P.hour != null) BRAIN.learnTime(P.hour, pnl); BRAIN.learnEvent(!!P.spike, pnl);
  const who = P.trader === "자체 엔진" ? "엔진" : shortMd(P.trader), bReg = P.bReg || P.regime || "";
  if (R <= -0.3) { BRAIN.learnLoss({ coin: P.ko, regime: bReg, feat: P.feat || {}, dir: P.side, roe });
    BRAIN.learn({ type: "교훈", coin: P.ko, regime: bReg, text: `[${P.name}] ${bReg} ${P.side > 0 ? "롱" : "숏"} ${base} ${R.toFixed(1)}R — 이 국면에선 신호 질 확인`, model: who, w: 1.5 }); }
  if (R >= 1) BRAIN.learn({ type: "패턴", coin: P.ko, regime: bReg, text: `[${P.name}] ${bReg} ${P.side > 0 ? "롱" : "숏"} +${R.toFixed(1)}R ${base}`, model: who, w: 1.5 });
  if (P.adj?.length) { (S.adjQ ||= []).push({ sym, ko: P.ko, tf: P.tf, side: P.side, entry: P.entry, rDist: P.rDist, notional: P.notional, margin: P.margin, risk: P.risk, R: +R.toFixed(3), t1: Date.now(), adj: P.adj }); if (S.adjQ.length > 40) S.adjQ.shift(); }
  feed(`${P.trader === "자체 엔진" ? "" : "[" + shortMd(P.trader) + "] "}${P.ko} 청산(${why}) ${R >= 0 ? "+" : ""}${R.toFixed(2)}R · ${pnl >= 0 ? "+" : "−"}$${Math.abs(pnl).toFixed(2)} · ROE ${roe.toFixed(1)}%(${P.lev}x) · ${P.name}`);
  delete S.pos[sym];
}
// 시세로 포지션 관리: 손절·익절·+1R 본절 이동·시간손절 (1분봉 고저로 꼬리까지 판정, 진입 이전 구간 제외)
// 포지션 관리: 마지막으로 확인한 시각(P.chk) 이후의 봉을 '시간 순서대로 전부' 다시 본다.
//   앱이 닫혀 있거나 멈춰 있던 동안 익절·손절·본절·시간청산에 닿은 것도 놓치지 않는다(같은 봉에서 손절·익절이 둘 다 닿으면 보수적으로 손절).
function manage(sym, price, bars) {
  const P = S.pos[sym]; if (!P) return;
  const from = Math.max(P.t, P.chk || 0) - 60e3, seq = (bars || []).filter(b => b.t + (b.dur || 60e3) > from).sort((a, b) => a.t - b.t);
  for (const b of seq) {
    if (b.t > P.deadline) { const late = Date.now() - P.deadline > 120e3; return closeP(sym, late ? b.o : price, "시간손절" + (late ? "(지연 반영)" : ""), b.t); }
    const late = Date.now() - b.t > 180e3, tag = late ? "(놓친 봉 반영)" : "";
    if (P.side > 0 ? b.l <= P.liq : b.h >= P.liq) return closeP(sym, P.liq, "청산", b.t);
    if (P.side > 0 ? b.l <= P.sl : b.h >= P.sl) return closeP(sym, P.sl, (P.run ? "추적 손절" : P.be ? "본절" : "손절") + tag, b.t);
    if (P.tp != null && (P.side > 0 ? b.h >= P.tp : b.l <= P.tp)) return closeP(sym, P.tp, "익절" + tag, b.t);
    const fav = P.side > 0 ? b.h - P.entry : P.entry - b.l;
    if (!P.be && fav >= P.rDist) { P.sl = P.side > 0 ? P.entry * (1 + FW.fee) : P.entry * (1 - FW.fee); P.be = true; P.beAt = Date.now(); feed(`${P.ko} +1R 도달 → 손절을 본절로 이동(손실 제거)${tag}`); }
    P.chk = Math.max(P.chk || 0, b.t);
  }
  markPos(P, price);
  if (Date.now() > P.deadline) return closeP(sym, price, "시간손절");
}

// ── 한 스텝: 코인별 시세 → 포지션 관리 → 국면 판정 → 검증된 전략 신호 → 승인 대기열 ──
export async function step() {
  load();
  // ⛔ 낙폭 서킷브레이커(ffrdm·FenixAI): 고점 대비 30% 이상 잃으면 24시간 신규 진입 중지(같은 고점에서는 한 번만 — 영구 정지 방지)
  { const eq = equity(), pk = Math.max(S.peak || BANKROLL, eq); if ((pk - eq) / pk >= 0.3 && S.haltPk !== pk) { S.halt = Date.now() + 24 * 3600e3; S.haltPk = pk; feed(`⛔ 고점 대비 낙폭 ${((pk - eq) / pk * 100).toFixed(1)}% → 24시간 신규 진입 중지(보유 포지션 관리는 계속)`); } }
  if (!olInit || S.epoch % 20 === 0) { olInit = true; refreshOllama(); }
  const q = await quant(), V = variants(), tfs = [...new Set(V.map(v => v.tf))];
  for (const [ko, sym] of COINS) {
    let cs1; try { cs1 = (await candlesFor({ market: sym, exchange: "binancef", timeframe: "1" }, 300)).cs; } catch (e) { continue; }
    if (!cs1 || cs1.length < 60) continue;
    const price = cs1.at(-1).c, feat = featuresOf(cs1);
    S.feat[sym] = feat; (S.brief ||= {})[sym] = marketBrief(cs1);
    // 엔진 교체 전 포지션 정리
    if (S.legacy?.length) for (const L of S.legacy.filter(x => x.sym === sym || x.ko === ko)) { const pr = (price - L.entry) / L.entry * L.side - FW.fee, m = L.margin || 0, pnl = Math.max(-m, (L.notional || m * (L.lev || 1)) * pr); if (Number.isFinite(pnl)) { S.pnl += pnl; feed(`${ko} 예전 엔진 포지션 정리 ${pnl >= 0 ? "+" : "−"}$${Math.abs(pnl).toFixed(2)}`); } S.legacy = S.legacy.filter(x => x !== L); }
    // 놓친 구간이 1분봉 300개(5시간)보다 길면 5분봉으로 메운다
    { const P0 = S.pos[sym]; let bars = cs1;
      if (P0 && Date.now() - Math.max(P0.t, P0.chk || 0) > 4.5 * 3600e3) { try { const c5 = (await candlesFor({ market: sym, exchange: "binancef", timeframe: "5" }, 1000)).cs; bars = [...c5.filter(b => b.t < cs1[0].t).map(b => ({ ...b, dur: 300e3 })), ...cs1]; feed(`${ko} 마지막 확인 이후 ${Math.round((Date.now() - Math.max(P0.t, P0.chk || 0)) / 3600e3)}시간을 5분봉으로 되짚어 익절·손절 확인`); } catch (e) {} }
      manage(sym, price, bars); }
    // 국면(1시간봉) + 상위 추세(4시간봉)
    const m60 = await getTF(sym, "60"), m240 = await getTF(sym, "240", 400);
    if (m60) { const i = m60.I.n - 2, rg = ENG.regimeAt(m60.I, i); const hb = m240 ? ENG.htfBiasAt(m240.H ||= ENG.prepareHTF(q, m240.cs), Date.now()) : { bias: 0 };
      S.regime[sym] = { key: rg.key, label: rg.label, adx: rg.adx ? Math.round(rg.adx) : null, htf: hb.bias }; }
    S.dec[sym] = { price, dir: S.regime[sym]?.htf || 0, conf: S.regime[sym]?.adx ?? 0, regime: S.regime[sym]?.label || "판단중" };
    // 새로 마감된 봉이 있는 시간봉만 신호 판단
    for (const tf of tfs) {
      const mk = tf === "60" ? m60 : tf === "240" ? m240 : await getTF(sym, tf); if (!mk) continue;
      const i = mk.I.n - 2, barT = mk.cs[i].t, lk = sym + "|" + tf; if (S.eng.lastBar[lk] === barT) continue; S.eng.lastBar[lk] = barT;
      const htfMk = HTF_OF[tf] ? (HTF_OF[tf] === "60" ? m60 : m240) : null; const H = htfMk ? (htfMk.H ||= ENG.prepareHTF(q, htfMk.cs)) : null;
      const reg = ENG.regimeAt(mk.I, i), hb = H ? ENG.htfBiasAt(H, mk.cs[i].t + TFMIN[tf] * 60e3) : null;
      // 보유 중인 포지션의 전략 청산신호
      const P = S.pos[sym]; if (P && P.tf === tf) { P.atr = mk.I.atr[i] || P.atr;
        // 🏃 익절을 푼 포지션: 마감봉 종가에서 ATR×3 뒤로 손절을 따라 올림(올리기만, 내리지 않음 — 백테스트와 같은 방식)
        if (P.run && mk.I.atr[i]) { const n = mk.cs[i].c - P.side * 3 * mk.I.atr[i]; if ((n - P.sl) * P.side > 0) P.sl = n; }
        const v = V.find(x => x.vkey === P.vkey); if (v?.exit) { v.prep?.(mk.cs); if (v.exit(mk.I, i, P.side)) closeP(sym, price, "청산신호"); } }
      if (S.pos[sym] || (S.cool[sym] || 0) > Date.now() || S.queue.some(x => x.sym === sym) || cfg().exclude.includes(ko)) continue;
      const cands = [];
      for (const v of V.filter(x => x.tf === tf && isActive(x))) {
        v.prep?.(mk.cs); const s = v.sig(mk.I, i); if (!s) continue;
        if (v.regimes && !v.regimes.includes(reg.key)) continue;
        if (H && !ENG.htfAllows(v, s.side, hb)) continue;
        const rs = regStat(v.vkey, reg.key); if (rs.n >= 8 && rs.mean < 0) continue;   // 학습된 승률: 이 국면에서 손실이 검증된 매매법은 건너뜀
        s.sl = ENG.atrFloorSL(v, mk.I, i, s.side, s.sl, 1.0);
        cands.push({ v, s, st: vstat(v.vkey) });
      }
      if (!cands.length) continue;
      cands.sort((a, b) => b.st.mean - a.st.mean); const { v, s, st } = cands[0];
      if (!dayGate()) { feed(`${ko} 신호(${v.name}) 무시 — 오늘 손실 한도 ${FW.dailyStop * 100}% 도달`); continue; }
      if (S.news?.blockUntil > Date.now()) { feed(`${ko} 신호(${v.name}) 보류 — 📰 주요 일정/뉴스 위험 구간`); continue; }
      // 🧘 관망 규칙집(실데이터로 검증된 것만 켜짐 · 스스로 고침) + 피로(연속 손실 휴식) + 낙폭 서킷브레이커. 막은 신호도 따라가 채점한다.
      { const ctx = HR.ctxAt(ENG, mk.I, i, H, s.side, barT + TFMIN[tf] * 60e3, { fng: S.fng?.v ?? null }), hk = HR.check(S.hold, ctx), rest = HR.restUntil(S.hold, closedSeq()), now = Date.now();
        const rule = (S.halt || 0) > now ? "halt" : rest > now ? "streak" : hk?.block, why = rule === "halt" ? "낙폭 서킷브레이커(24시간 신규 진입 중지)" : rule === "streak" ? `${HR.ruleText("streak", S.hold.rules.streak.p)} — ${Math.ceil((rest - now) / 3600e3)}시간 남음` : hk?.why;
        if (rule) { shadowAdd({ sym, ko, side: s.side, sl: s.sl, rr: rrFor(v), px: price, name: v.name, rule }); feed(`🧘 ${ko} ${s.side > 0 ? "롱" : "숏"} 신호(${v.name}) 관망 — ${why}`); continue; } }
      const wh = await whaleSignal(sym).catch(() => null);
      (S.sigLog ||= []).push({ sym, side: s.side, sl: s.sl, rr: rrFor(v), vkey: v.vkey, name: v.name, tf, mean: st.mean, n: st.n, wr: st.wr, t: Date.now(), px: price }); if (S.sigLog.length > 60) S.sigLog.splice(0, S.sigLog.length - 60);
      S.queue.push({ sym, ko, vkey: v.vkey, name: v.name, side: s.side, sl: s.sl, why: s.why, regime: reg.label, regKey: reg.key, htf: hb?.bias ?? 0, st, t: Date.now(), px0: price, whale: wh });
      S.scan = { model: "전략 엔진", ko, sym, regime: `${reg.label} · ${v.name} ${s.side > 0 ? "롱" : "숏"} 신호`, t: Date.now() };
      feed(`🎯 ${ko} ${s.side > 0 ? "롱" : "숏"} 신호: ${v.name}(${tf === "60" ? "1시간" : tf === "240" ? "4시간" : tf + "분"}봉) — ${s.why} · 최근 ${st.n}건 기대값 ${st.mean >= 0 ? "+" : ""}${st.mean}R`);
    }
  }
  const cm = connectedModels();
  // 🏃 +1R 을 찍은 포지션: 코드 초안(익절 풀고 ATR×3 추적, 실측 우위)을 AI 가 15분 안에 다르게 정하지 않으면 자체 엔진이 적용.
  //   AI 모델이 없거나, AI 의 익절·손절 조정이 원래 계획보다 손해로 채점돼 꺼져 있으면 바로 적용.
  for (const P of Object.values(S.pos)) if (P.be && !P.run && (!P.keep || (S.adjOff || 0) > Date.now()) && (!cm.length || (S.adjOff || 0) > Date.now() || Date.now() - (P.beAt || P.t) > 15 * 60e3)) applyAdj(P, "run", "자체 엔진", null, "코드 초안 자동 적용");
  // 대기열: AI 모델이 승인하거나, 모델이 없거나 20초 안에 응답이 없으면 자체 엔진이 집행
  S.queue = S.queue.filter(it => { if (Date.now() - it.t > 240e3) return false; if (!cm.length || Date.now() - it.t > 90e3) { openFrom(it, "자체 엔진"); return false; } return true; });   // 1시간봉 신호라 90초 대기는 무해
  S.epoch++;
  if (Date.now() - (S.eng.calibAt || 0) > 2 * 3600e3 && !calibrating) calibrate().catch(e => { calibrating = false; feed("🔬 자체 백테스트 오류: " + (e?.message || e)); });
  save();
  return state();
}

// ── 🔬 자체 백테스트(보정): 모든 매매법×시간봉을 최근 실제 데이터로 프레임워크 그대로 시험 → 성적을 선별에 반영 (2시간마다) ──
let calibrating = false;
// 🧬 매매법 진화: 기존 매매법을 개선(손익비·보유)·수정(필터)·조합(A+B 확인)해 보고, 앞 70% 선택 + 뒤 30% 검증을 둘 다 통과한 변형만 채택.
//   채택돼도 실전 투입은 다른 매매법과 똑같이 워크포워드 선별(최근 20건 기대값)을 통과해야 한다. 최대 16개 유지(부진한 것부터 퇴출).
function evolveFrom(ALL) {
  const sets = ALL.filter(x => x.D["60"]).map(x => ({ sym: x.sym, I: x.D["60"].I, cs: x.D["60"].cs, H: x.H["240"] }));
  const seeds = (S.eng.evoSeeds || []).splice(0, 6), keep = (S.eng.evo || []).map(e => e.gene);
  const r = ENG.evolve(sets, { seeds, keep });
  const now = Date.now(), added = [];
  for (const a of r.adopted) { const id = ENG.geneId(a.gene); if ((S.eng.evo || []).some(e => ENG.geneId(e.gene) === id)) continue;
    S.eng.evo.push({ gene: a.gene, is: a.is, oos: a.oos, base: a.base, at: now, src: a.gene.src || "" }); added.push(a);
    BRAIN.learn({ type: "지식", text: `${ENG.geneName(a.gene)}: 원본 ${a.base.mean}R → 학습구간 ${a.is.mean}R · 검증구간 ${a.oos.mean}R`, model: "매매법 진화", w: 1.5 }); }
  // 퇴출: 16개 초과 시 (실전·백테스트 최근 성적이 가장 나쁜 것부터, 보유 중인 건 제외)
  const held = new Set(Object.values(S.pos).map(p => p.vkey));
  while (S.eng.evo.length > 16) { const sc = S.eng.evo.map((e, k) => ({ k, m: vstat(ENG.buildEvo(e.gene)?.key + "@60").mean, held: held.has(ENG.buildEvo(e.gene)?.key + "@60") })).filter(x => !x.held).sort((a, b) => a.m - b.m)[0];
    if (!sc) break; const gone = S.eng.evo.splice(sc.k, 1)[0]; feed(`🧬 퇴출: ${ENG.geneName(gone.gene)} (최근 ${sc.m}R)`); }
  S.eng.evoLog = [{ t: now, tested: r.tested, passedIS: r.passedIS, adopted: added.map(a => ({ name: ENG.geneName(a.gene), src: a.gene.src, base: a.base.mean, is: a.is.mean, oos: a.oos.mean, n: a.oos.n })), seeds: seeds.length }, ...(S.eng.evoLog || [])].slice(0, 12);
  feed(`🧬 매매법 진화: 변형 ${r.tested}개 시험(개선·수정·조합${seeds.length ? "·AI 제안 " + seeds.length : ""}) → 학습구간 통과 ${r.passedIS} → 검증구간까지 통과 ${added.length}개 채택${added.length ? ": " + added.map(a => `${ENG.geneName(a.gene)} (${a.base.mean}R→${a.oos.mean}R)`).join(" · ") : ""}`);
  return { ...r, added };
}
export async function evolveNow() {   // 사무실(에이전트 팀) '매매법 진화' 업무에서 호출: 데이터 받아 즉시 한 세대 진화
  load(); const q = await quant(), ALL = [];
  for (const [ko, sym] of COINS) { try { const cs = (await candlesFor({ market: sym, exchange: "binancef", timeframe: "60" }, 1500)).cs, c4 = (await candlesFor({ market: sym, exchange: "binancef", timeframe: "240" }, 800)).cs;
    if (cs?.length > 300) ALL.push({ ko, sym, D: { "60": { cs, I: ENG.prepare(q, cs) } }, H: { "240": c4?.length > 250 ? ENG.prepareHTF(q, c4) : null } }); } catch (e) {} }
  const r = evolveFrom(ALL); save(); return r;
}
export const proposeEvo = g => { load(); if (g && ENG.LIB_BY_KEY[g.base]) { (S.eng.evoSeeds ||= []).push(g); save(); return true; } return false; };
// 🧘 관망 규칙집 진화(ATLAS: 한 번에 하나만 고치고, 데스크처럼 다시 돌려 좋아질 때만 남김 · 전 버전 기록)
//   AI 제안(전략 회의의 hold)을 먼저 시험하고, 없거나 탈락하면 코드가 한 걸음 이웃(켜기/끄기·값 한 칸)을 전부 시험해 가장 좋은 하나만 채택.
//   채택은 12시간에 한 번까지(AI 제안은 예외) — 매 점검마다 규칙이 흔들리지 않게.
function holdEvolve(HT) {
  const prop = S.holdProp || null; S.holdProp = null;
  const lastAdopt = (S.hold.log || []).find(x => x.kind === "채택"), cool = lastAdopt && Date.now() - lastAdopt.t < 12 * 3600e3;
  const ev = HR.evolve(HT, S.hold, { proposal: prop?.e || null, maxPos: cfg().maxPos }); if (!ev.base) return;
  const log = x => { S.hold.log = [{ t: Date.now(), ver: S.hold.ver, ...x }, ...(S.hold.log || [])].slice(0, 30); };
  const ai = ev.tried.find(x => x.src === "AI"), pick = ev.adopted && (ev.adopted.src === "AI" || !cool) ? ev.adopted : null;
  if (prop && !(pick && pick.src === "AI")) { log({ kind: "기각", src: `AI(${prop.by})`, e: HR.editText(prop.e), why: ai?.why || "범위 밖", reason: prop.reason || "" }); feed(`🧘 AI(${prop.by}) 관망 규칙 제안 기각: ${HR.editText(prop.e)} — ${ai?.why || "범위 밖"}`); }
  if (pick) { const keepLog = S.hold.log; S.hold = { ...pick.book, ver: (S.hold.ver || 1) + 1, log: keepLog };
    log({ kind: "채택", src: pick.src === "AI" ? `AI(${prop.by})` : "코드", e: HR.editText(pick.e), why: pick.why, reason: pick.src === "AI" ? prop.reason || "" : "" });
    feed(`🧘 관망 규칙 v${S.hold.ver} 채택(${pick.src === "AI" ? "AI 제안 " + prop.by : "코드 탐색"}): ${HR.editText(pick.e)} — ${pick.why}`);
    BRAIN.learn({ type: "지식", text: `관망 규칙 v${S.hold.ver}: ${HR.editText(pick.e)} (${pick.why})`, model: "관망 규칙 진화", w: 2, key: "hold:" + pick.e.id }); }
  const top = ev.tried.filter(x => x.sc).sort((a, b) => (b.d ?? -9) - (a.d ?? -9)).slice(0, 5);
  S.holdEval = { t: Date.now(), n: HT.length, base: ev.base, cool: !!(ev.adopted && !pick), top: top.map(x => ({ e: HR.editText(x.e), src: x.src, ok: x.ok, why: x.why })) };
  feed(`🧘 관망 규칙 점검: 지금 규칙집으로 데스크 재연 ${ev.base.all.n}건 평균 ${ev.base.all.mean}R(승률 ${ev.base.all.wr}%) · 전반 ${ev.base.h1.mean} / 후반 ${ev.base.h2.mean} · 수정 후보 ${ev.tried.length}개${pick ? "" : ev.adopted ? " → 더 나은 수정 있음(12시간 대기)" : " → 유지"}`);
}
export async function calibrate() {
  if (calibrating) return; calibrating = true; load();
  try { await fngCheck(); } catch (e) {}
  const q = await quant(); let V = variants(); const N = { "5": 1500, "15": 1500, "60": 1500, "240": 800 };
  feed(`🔬 자체 백테스트 시작 — 매매법 ${V.length}개 변형 × ${COINS.length}코인 (청산공식 20x+·수수료·본절 규칙 그대로)`);
  const pool = {}, ALL = [], HT = [];   // HT: 관망 규칙집 검증용(거래 + 진입 직전 봉의 맥락)
  for (const [ko, sym] of COINS) {
    const D = {};
    for (const tf of ["5", "15", "60", "240"]) { try { const cs = (await candlesFor({ market: sym, exchange: "binancef", timeframe: tf }, N[tf])).cs; if (cs?.length > 300) D[tf] = { cs, I: ENG.prepare(q, cs) }; } catch (e) {} }
    const H = { "60": D["60"] ? ENG.prepareHTF(q, D["60"].cs) : null, "240": D["240"] ? ENG.prepareHTF(q, D["240"].cs) : null };
    ALL.push({ ko, sym, D, H });
  }
  // bigpie 6전략 앙상블 가중치를 전 코인 1시간봉으로 최적화(앞 70% 선택 → 뒤 30% 검증 통과 시에만 채택)
  try { const tn = ENG.tuneEnsemble(ALL.filter(x => x.D["60"]).map(x => ({ sym: x.sym, I: x.D["60"].I, cs: x.D["60"].cs, H: x.H["240"] })));
    if (tn) { S.eng.ensW = tn.w; feed(`⚖ 6전략 앙상블 가중치 ${tn.adopted ? "채택" : "균등 유지"}: [${tn.w.join(",")}] · 학습구간 ${tn.is}R → 검증구간 ${tn.oos}R`); } } catch (e) {}
  try { evolveFrom(ALL); V = variants(); } catch (e) { feed(`🧬 매매법 진화 실패(${String(e?.message || e).slice(0, 40)})`); }
  for (const { ko, sym, D, H } of ALL) {
    for (const v of V) { const d = D[v.tf]; if (!d) continue;
      const r = ENG.simulate(v, d.I, d.cs, { sym, H: HTF_OF[v.tf] ? H[HTF_OF[v.tf]] : null, atrK: 1, be: 1 });
      (pool[v.vkey] ||= []).push(...r.trades.map(t => ({ R: +t.R.toFixed(3), t1: t.t1, src: "bt", reg: t.reg })));
      if (!v.exp) { const idx = d.idx ||= new Map(d.cs.map((b, k) => [b.t, k])), Hh = HTF_OF[v.tf] ? H[HTF_OF[v.tf]] : null, ms = TFMIN[v.tf] * 60e3;
        for (const t of r.trades) { const ie = idx.get(t.t0); if (ie == null || ie < 1) continue; HT.push({ s: sym, t: t.t0, t1: t.t1, R: t.R, ...HR.ctxAt(ENG, d.I, ie - 1, Hh, t.side, d.cs[ie - 1].t + ms, { fng: fngHist?.[new Date(t.t0).toISOString().slice(0, 10)] ?? null }) }); } }
      await new Promise(r => { try { const ch = new MessageChannel(); ch.port1.onmessage = () => { ch.port1.close(); r(); }; ch.port2.postMessage(0); } catch (e) { setTimeout(r, 0); } }); }
    feed(`🔬 ${ko} 백테스트 완료`);
  }
  for (const v of V) { const bt = (pool[v.vkey] || []).sort((a, b) => a.t1 - b.t1).slice(-40), live = (S.eng.stats[v.vkey]?.tr || []).filter(t => t.src === "live");
    S.eng.stats[v.vkey] = { tr: [...bt, ...live].slice(-60) }; }
  try { holdEvolve(HT); } catch (e) { feed(`🧘 관망 규칙 점검 실패(${String(e?.message || e).slice(0, 40)})`); }
  const act = V.filter(isActive), summ = V.map(v => ({ v, s: vstat(v.vkey) })).filter(x => x.s.n).sort((a, b) => b.s.mean - a.s.mean);
  S.eng.calibAt = Date.now(); S.eng.calib = { at: Date.now(), active: act.map(v => v.vkey), top: summ.slice(0, 5).map(x => `${x.v.name}@${x.v.tf}: ${x.s.mean >= 0 ? "+" : ""}${x.s.mean}R(${x.s.n}건 승률${x.s.wr}%)`) };
  feed(`🔬 자체 백테스트 끝 — 지금 실전 투입(검증 통과) ${act.length}개: ${act.map(v => v.name + "@" + v.tf).join(", ") || "없음 → 기다림(억지 진입 안 함)"}`);
  calibrating = false; save();
}

// ══ 📈 내 차트 지표 데스크: 사용자가 터미널에 띄운 보조지표로 ① 값 튜닝 ② 보조지표 추천 ③ AI 모델이 매매법 설계 → 검증 → 데모 ④ AI 실험 진입 ══
//   차트에 적용하는 건 사용자가 직접 한다(여기서는 값과 근거만 제안). 주문은 없다(데모).
function termCell() { try { const st = JSON.parse(localStorage.getItem("nuri:term:state") || "null"); const c = (st?.cells || [])[0] || null; let sym = String(c?.symbol || "BTCUSDT").toUpperCase(); const m = sym.match(/^KRW-(\w+)$/); if (m) sym = m[1] + "USDT"; if (!/USDT$/.test(sym)) sym += "USDT"; return { sym, interval: c?.interval || "15m", n: (st?.inds || []).length }; } catch (e) { return { sym: "BTCUSDT", interval: "15m", n: 0 }; } }
function aiChartExperiment({ name, ko, sym, bias, conf, note, price, myRead, rg }) {
  const now = Date.now(), X = (S.aiExp ||= { day: "", n: 0, pausedUntil: 0 });
  if (X.day !== today()) { X.day = today(); X.n = 0; }
  const st = vstat("aichart@15"); if (st.live >= 10 && st.mean < 0 && !X.pausedUntil) { X.pausedUntil = now + 24 * 3600e3; feed(`🤖 AI 내 지표 실험 24시간 중지 — 실전 ${st.live}건 평균 ${st.mean}R`); }
  if (X.pausedUntil > now || !bias || conf < 75 || !myRead?.["15"]?.length || X.n >= 4 || S.pos[sym] || S.queue.some(q => q.sym === sym)) return;
  const xs = myRead["15"], agree = xs.filter(x => x.dir === bias).length / xs.length; if (agree < 0.6) return;
  if ((rg?.htf || 0) === -bias) return;
  const m15 = MK[sym + "|15"], atr = m15?.I?.atr?.[m15.I.n - 2]; if (!atr) return;
  X.n++;
  S.queue.push({ sym, ko, vkey: "aichart@15", name: `🤖 AI 내 지표 실험(${shortMd(name)})`, side: bias, sl: price - bias * atr * 1.5, why: `${shortMd(name)} 확신 ${conf}% · 내 지표 15분 ${Math.round(agree * 100)}% ${bias > 0 ? "롱" : "숏"} · ${note}`, regime: rg?.label || "", regKey: rg?.key, htf: rg?.htf || 0, st, t: now, px0: price, exp: true });
  feed(`🤖 [${shortMd(name)}] ${ko} 내 지표로 ${bias > 0 ? "롱" : "숏"} 실험 진입 대기 (확신 ${conf}% · 지표 동조 ${Math.round(agree * 100)}% · 리스크 0.25%)`);
}
let cdBusy = false;
export async function chartDesk(force = false) {
  load(); const c = termCell(), D = S.chartDesk || {};
  if (cdBusy || !c.n || (!force && D.t && Date.now() - D.t < 30 * 60e3 && D.sym === c.sym && D.interval === c.interval)) return D; cdBusy = true;
  try {
    const RDm = await import("../nuri-ai/terminal/readings.js"), specs = RDm.userInds(), tf = CL.engTf(c.interval); if (specs.length < 1) return D;
    const cs = (await candlesFor({ market: c.sym, exchange: "binancef", timeframe: tf }, 1500)).cs;
    const T = await CL.tune(specs, cs), R = await CL.recommend({ sym: c.sym, tf, specs: T.tuned }).catch(() => null), now = await CL.readNow(c.sym, ["5", "15", "60"], specs).catch(() => ({}));
    S.chartDesk = { ...D, t: Date.now(), sym: c.sym, interval: c.interval, tf, rows: T.rows, tuned: T.tuned, recs: R ? { base: R.base, top: R.top.map(x => ({ name: x.name, key: x.key, params: x.params, why: x.why, delta: x.delta, crossDelta: x.crossDelta, own: x.own, test: x.test })), weak: (R.weak || []).map(x => ({ name: x.name, delta: x.delta, crossDelta: x.crossDelta })) } : null, now };
    feed(`📈 내 차트 지표 점검(${c.sym.replace("USDT", "")} ${c.interval}): 값 바꿀 만한 지표 ${T.rows.filter(x => x.changed).length}개 · 추천 보조지표 ${R?.top?.length || 0}개 — 차트 적용은 직접`);
    save();
    await aiDesignChart(specs, T, R, c, tf, now).catch(e => feed(`📈 AI 내 지표 매매법 설계 실패: ${String(e?.message || e).slice(0, 50)}`));
    return S.chartDesk;
  } finally { cdBusy = false; }
}
let cdRot = 0;
async function aiDesignChart(specs, T, R, c, tf, now) {
  const cm = connectedModels(); if (!cm.length) return;
  const tgt = cm[cdRot++ % cm.length], items = T.tuned.map((s, i) => `${i}: ${String(s.key).replace(/^[qxc]:/, "")} ${JSON.stringify(s.params)}`);
  const recs = (R?.top || []).map((x, i) => `r${i}: ${x.name} ${JSON.stringify(x.params)} (넣으면 처음 보는 구간 ${x.delta >= 0 ? "+" : ""}${x.delta}R)`);
  let raw = "";
  await brainStream({ messages: [
    { role: "system", content: '너는 코인 선물 매매법 설계자다. 사용자가 차트에 띄운 보조지표(번호)와 추천 지표(r번호)로 \'N개 중 K개가 막 같은 방향이 되면 진입\' 매매법을 설계한다. 지표는 2~6개, K 는 2~N. 반드시 JSON 한 줄: {"use":[0,1],"add":["r0"],"k":2,"rr":2,"atrK":1.5,"exitFlip":true,"reason":"한 문장"}' },
    { role: "user", content: `코인 ${c.sym} · ${tf === "60" ? "1시간" : tf + "분"}봉\n내 지표(튜닝 반영):\n${items.join("\n")}\n추천 지표:\n${recs.join("\n") || "없음"}\n지금 방향: ${Object.entries(now || {}).map(([k, xs]) => k + ": " + xs.map(x => x.name + (x.dir > 0 ? "↑" : x.dir < 0 ? "↓" : "·")).join(" ")).join(" / ")}\nJSON만:` }],
    role: "fast", target: tgt, fallback: true, json: true, maxTokens: 220, temperature: 0.5, noThink: true, onContent: d => raw += d, onThink: () => {} });
  let j = {}; try { j = JSON.parse((raw.match(/\{[\s\S]*\}/) || ["{}"])[0]); } catch (e) {}
  const use = [...new Set((Array.isArray(j.use) ? j.use : []).map(Number).filter(i => i >= 0 && i < T.tuned.length))];
  const add = (Array.isArray(j.add) ? j.add : []).map(x => +String(x).replace(/\D/g, "")).filter(i => R?.top?.[i]).map(i => ({ key: R.top[i].key, params: R.top[i].params }));
  const gs = [...use.map(i => T.tuned[i]), ...add].slice(0, 6); if (gs.length < 2) { feed(`📈 [${shortMd(tgt.model)}] 매매법 설계 형식 오류 → 건너뜀`); return; }
  const g = { id: "ai" + Date.now().toString(36), tf, specs: gs, k: Math.max(2, Math.min(gs.length, Math.round(+j.k || 2))), rr: Math.max(1.5, Math.min(3, +j.rr || 2)), atrK: Math.max(1, Math.min(2.5, +j.atrK || 1.5)), exitFlip: j.exitFlip !== false, from: c.sym, label: `AI ${shortMd(tgt.model)}` };
  const V = await CL.validate(g, c.sym), att = { t: Date.now(), model: shortMd(tgt.model), reason: String(j.reason || "").slice(0, 80), k: g.k, n: gs.length, rr: g.rr, test: V.test, crossPos: V.crossPos, pass: V.pass, verdict: V.verdict, names: gs.map(s => String(s.key).replace(/^q:|^x:/, "")) };
  (S.chartDesk.attempts ||= []).unshift(att); S.chartDesk.attempts = S.chartDesk.attempts.slice(0, 10);
  if (!V.pass) BRAIN.learn({ type: "교훈", coin: c.sym.replace("USDT", ""), text: `내 지표 ${att.names.join("+")} ${g.k}/${gs.length} 조합은 처음 보는 구간 ${V.test.mean}R(${V.test.n}) · 다른 코인 ${V.crossPos}/5 — ${V.verdict || "검증 탈락"}`, model: "내지표설계", w: 1.2, key: "chartfail:" + c.sym + "|" + att.names.slice().sort().join("+") + "|" + g.k });
  if (V.pass) { addChartStrategy(g, { by: att.model, test: V.test, crossPos: V.crossPos, pass: true }); BRAIN.learn({ type: "매매법", coin: c.sym.replace("USDT", ""), text: `AI(${att.model}) 내 지표 매매법 ${att.names.join("+")} ${g.k}/${gs.length} 처음 보는 구간 ${V.test.mean}R · 다른 코인 ${V.crossPos}/5`, model: "내지표설계", w: 1.5 }); }
  feed(`📈 [${att.model}] 내 지표 매매법 설계: ${att.names.join("+")} ${g.k}/${gs.length} · 손익비 ${g.rr} → 처음 보는 구간 ${V.test.mean}R(${V.test.n}) · 다른 코인 ${V.crossPos}/5 → ${V.pass ? "✅ 데모 투입" : "❌ " + V.verdict}`);
  save();
}

// ══ 🐋 고래 카피 신호 (casatrickdev copyTrading: 감지 → 필터 → 리스크 → 신호 · 실행 없음) + 적중률 학습(WalletIntelligence 대응) ══
import * as WC from "./lib/whalecopy.js";
const _whC = {};
// ⚡ 실시간 진입용: 이 코인에서 최근(기본 75분) 나온 '워크포워드 검증 통과' 매매법 신호 — 손매매 추천의 유일한 검증된 근거
export function recentSignal(sym, maxMin = 75) { load(); return [...(S.sigLog || [])].reverse().find(x => x.sym === sym && Date.now() - x.t < maxMin * 60e3 && x.mean > SEL.thr) || null; }
export async function whaleFor(sym) { load(); return whaleSignal(sym); }
// ⚡ 실시간 진입 토론: 에이전트 팀의 주장에 뉴럴 데스크 모델이 반박·동의 (모델은 순번대로)
let dbRot = 0;
export async function debateReply(setup, teamArg) {
  load(); const cm = connectedModels(); if (!cm.length) return null;
  const tgt = cm[dbRot++ % cm.length]; let raw = "", route;
  try {
    route = await brainStream({ messages: [
      { role: "system", content: '너는 뉴럴 데스크의 트레이더다. 에이전트 팀이 낸 실시간 진입 의견을 독립적으로 검토한다. 팀 문장을 반복하지 말고, 팀이 말하지 않은 근거(위험 요인·손절 위치·반대 시나리오·국면·다른 모델의 시장 읽기)로 판단한다. 코인 선물 이야기다. 숫자는 주어진 것만 쓴다. 반드시 JSON 한 줄: {"stance":"찬성"|"반대","reason":"한국어 한 문장"}' },
      { role: "user", content: `진입 계획: ${setup}
에이전트 팀 의견: ${teamArg}
뉴럴 데스크 자료: 국면 ${Object.entries(S.regime || {}).map(([k, r]) => k.replace("USDT", "") + " " + r.label).join(", ")} · 다른 모델 시장 읽기: ${Object.values(S.scans || {}).slice(-6).map(v => v.ko + (v.bias > 0 ? "▲" : v.bias < 0 ? "▼" : "·") + v.conf).join(" ")}
JSON만:` }],
      role: "fast", target: tgt, fallback: true, json: true, maxTokens: 160, temperature: 0.2, noThink: true, onContent: d => raw += d, onThink: () => {} });
  } catch (e) { return { model: shortMd(tgt.model), stance: "기권", reason: String(e?.message || e).slice(0, 40) }; }
  let j = {}; try { j = JSON.parse((raw.match(/\{[\s\S]*\}/) || ["{}"])[0]); } catch (e) {}
  const st = /반대|disagree|no/i.test(j.stance || "") ? "반대" : /찬성|agree|yes/i.test(j.stance || "") ? "찬성" : "기권";
  const reason = String(j.reason || raw).replace(/\s+/g, " ").slice(0, 90);
  // 팀 문장을 거의 그대로 반복하면(작은 모델의 앵무새 답) 독립 의견이 아니므로 기권 처리
  const bi = t => { const a = String(t).replace(/\s/g, ""), o = new Set(); for (let i = 0; i < a.length - 1; i++) o.add(a.slice(i, i + 2)); return o; };
  const A = bi(reason), B = bi(teamArg), inter = [...A].filter(x => B.has(x)).length, sim = A.size ? inter / Math.min(A.size, B.size || 1) : 0;
  if (sim > 0.7) return { model: shortMd(route?.model || tgt.model), stance: "기권", reason: "팀 의견을 반복(독립 근거 없음)" };
  return { model: shortMd(route?.model || tgt.model), stance: st, reason };
}
// 🔬 내 지표 연구소 → 뉴럴 데모 거래 투입 (다른 매매법과 똑같이 자체 백테스트 + 워크포워드 선별을 거쳐야 실제 진입)
export function addChartStrategy(gene, meta = {}) { load(); (S.eng.chart ||= []); S.eng.chart = S.eng.chart.filter(x => x.id !== gene.id).slice(-7); S.eng.chart.push({ ...gene, meta, added: Date.now() }); S.eng.calibAt = 0; save(); feed(`📈 내 지표 매매법 데모 투입: ${CL.chartRule(gene).name} (${gene.from || ""} ${gene.tf}봉) — 다음 자체 백테스트에서 6개 코인 검증 후 통과하면 실전(데모) 진입`); return true; }
export function chartGenes() { load(); return (S.eng.chart || []).map(g => ({ ...g, active: isActive({ ...CL.chartRule(g), vkey: `${CL.chartRule(g).key}@${g.tf}` }) })); }
export function removeChartStrategy(id) { load(); S.eng.chart = (S.eng.chart || []).filter(x => x.id !== id); save(); }
export function chartStrategies() { load(); return (S.eng.chart || []).map(g => { const r = CL.chartRule(g), vk = `${r.key}@${r.tf}`; return { id: g.id, name: r.name, tf: g.tf, from: g.from, k: g.k, n: g.specs.length, rr: g.rr, meta: g.meta, added: g.added, stat: vstat(vk), active: isActive({ ...r, vkey: vk }) }; }); }
export function whaleTrust() { load(); return WC.score(S.whaleLog || [], sym => S.dec[sym]?.price, 30); }
async function whaleSignal(sym) {
  const c0 = _whC[sym]; if (c0 && Date.now() - c0.t < 90e3) return c0.s;
  const F = await import("../nuri-ai/flow.js"); const r = await F.whaleTrades({ symbol: sym, exchange: "binancef", minUsd: sym === "BTCUSDT" ? 300000 : 100000 });
  const sg = WC.pipeline(sym, r?.data, whaleTrust()); _whC[sym] = { t: Date.now(), s: sg };
  if (sg.status === "approved" && S.dec[sym]?.price) { (S.whaleLog ||= []).push({ sym, dir: sg.dir, price: S.dec[sym].price, t: Date.now() }); if (S.whaleLog.length > 400) S.whaleLog.splice(0, S.whaleLog.length - 400); }
  return sg;
}
// ══ 📑 코인 리서치 카드 (kevin1chun research 스킬의 출력 구조를 코인 선물용으로): 1년 범위·위치·7/30일 수익·펀딩 ══
async function coinResearch(sym) {
  const R = (S.research ||= {}), c0 = R[sym]; if (c0 && Date.now() - c0.t < 3600e3) return c0;
  const cs = (await candlesFor({ market: sym, exchange: "binancef", timeframe: "D" }, 365)).cs; if (!cs?.length) return null;
  const hi = Math.max(...cs.map(b => b.h)), lo = Math.min(...cs.map(b => b.l)), c = cs.at(-1).c, ret = n => cs.length > n ? +((c / cs.at(-1 - n).c - 1) * 100).toFixed(1) : null;
  let fund = null; try { const FS = await import("./lib/fundscan.js"), { webGet } = await import("../nuri-ai/engine.js"); const f = await FS.fundingScan(sym, u => webGet(u, "json")); fund = { avg: f.avg, key: f.key, ko: f.ko }; } catch (e) {}
  R[sym] = { t: Date.now(), hi, lo, pos: +((c - lo) / Math.max(1e-9, hi - lo) * 100).toFixed(0), r7: ret(7), r30: ret(30), r365: ret(cs.length - 1), fund };
  return R[sym];
}
function researchText(sym) { const r = S.research?.[sym]; if (!r) return ""; return `1년 범위 ${fmt(r.lo)}~${fmt(r.hi)} 중 ${r.pos}% 위치 · 7일 ${r.r7}% · 30일 ${r.r30}% · 1년 ${r.r365}%${r.fund ? ` · 거래소 펀딩 평균 ${r.fund.avg}%(${r.fund.ko})` : ""}`; }
// ══ 🗂 포지션 관리 — 익절가·손절가를 AI 가 스스로 바꾸되, 코드가 초안을 내고 범위를 검증하고 결과를 채점한다 ══
//   하이브리드(DeepSeek 정리 문서 · Yaass1ne/mt5-ftmo-trader 의 'LLM 은 거부·조정만, 숫자는 코드' · finagent 의 가격 부등호 명시 · siropkin 의 환각 필터):
//   ① 코드 초안: +1R 을 찍었으면 '익절 풀고 ATR×3 추적'(6코인 1년 실측 평균 −0.046R → −0.002R, 전·후반 모두 개선)
//   ② AI 결정: hold / close / breakeven / run / trail(손절 올리기) / tp(익절가 바꾸기) — 로컬 모델은 JSON 스키마로 보유 코인·결정만 쓰게 강제
//   ③ 코드 검증: 손절을 넓히는 것 금지 · 롱은 손절<현재가<익절(숏은 반대) · 손절 올리기는 +1R 이후·현재가에서 ATR×1.5 이상 · 익절 연장은 상위 추세 같은 방향+ADX 25 이상
//   ④ 채점: 청산 뒤 '조정하지 않았다면'(원래 계획 그대로)을 같은 봉으로 다시 돌려 차이(ΔR)를 기록. AI 조정이 10건 이상 누적 손해면 3일간 코드 초안만 쓴다(ATLAS 의 유지/되돌림).
let prRot = 0, prAt = 0;
const Rnow = p => ((p.price - p.entry) * p.side) / (p.rDist || 1);
const posAtr = p => p.atr || (() => { const m = MK[p.sym + "|" + p.tf]; return m ? m.I.atr[m.I.n - 2] : null; })();
function draftOf(p) {
  if (p.be && !p.run) return { kind: "run", why: "+1R 도달 → 익절 풀고 ATR×3 추적(실측 우위)" };
  return { kind: "hold", why: p.run ? "추적 중" : "아직 +1R 전" };
}
function applyAdj(p, kind, by, price, why) {
  const prev = { sl: p.sl, tp: p.tp, be: p.be, run: !!p.run, deadline: p.deadline }, side = p.side, atr = posAtr(p), r = Rnow(p), v = VMAP()[p.vkey];
  const fail = m => ({ ok: false, why: `${p.ko}: ${m}` });
  if (kind === "run") { if (!p.be || p.run) return fail("추적 조건 아님(+1R 전이거나 이미 추적 중)");
    p.run = true; p.tp = null; p.deadline = Math.max(p.deadline, p.t + (v?.hold || 48) * 4 * TFMIN[p.tf || "60"] * 60e3); }
  else if (kind === "trail") { const x = +price; if (!p.be) return fail("손절 올리기는 +1R 이후만"); if (!Number.isFinite(x)) return fail("가격 없음");
    if ((x - p.sl) * side <= 0) return fail(`손절을 넓히는 변경 금지(${fmt(p.sl)}→${fmt(x)})`);
    if (!atr || (p.price - x) * side < 1.5 * atr) return fail(`현재가와 너무 가까움(ATR×1.5=${atr ? fmt(1.5 * atr) : "?"} 필요)`);
    p.sl = x; }
  else if (kind === "tp") { const x = +price; if (!Number.isFinite(x)) return fail("가격 없음");
    const R = (x - p.entry) * side / p.rDist; if ((x - p.price) * side <= 0) return fail("익절가가 현재가 반대편"); if (R < 1 || R > 4) return fail(`익절 ${R.toFixed(2)}R — 1~4R 범위 밖`);
    const old = p.tp != null ? (p.tp - p.entry) * side / p.rDist : p.rr || 2, hb = S.regime[p.sym] || {};
    if (R > old + 0.05 && !(hb.htf === side && (hb.adx || 0) >= 25)) return fail(`익절 연장은 상위 추세 같은 방향·ADX 25↑ 일 때만(지금 추세 ${hb.htf || 0}, ADX ${hb.adx ?? "?"})`);
    p.tp = x; }
  else if (kind === "breakeven") { if (p.be || r < 0.5) return fail("본절 조건 미충족(+0.5R 이상)"); p.sl = side > 0 ? p.entry * (1 + FW.fee) : p.entry * (1 - FW.fee); p.be = true; p.beAt = Date.now(); }
  else if (kind === "close") { const against = (S.regime[p.sym]?.htf || 0) === -side; if (!(r >= 0.5 || (r <= -0.3 && against))) return fail(`정리 조건 미충족(${r.toFixed(2)}R)`); }
  else if (kind !== "keep") return fail(`모르는 결정 '${kind}'`);
  (p.adj ||= []).push({ t: Date.now(), kind, by, why: String(why || "").slice(0, 60), prev, alt: kind === "keep" ? { ...prev, tp: null, run: true, deadline: Math.max(prev.deadline, p.t + (v?.hold || 48) * 4 * TFMIN[p.tf || "60"] * 60e3) } : null, R0: +r.toFixed(2) });
  if (kind === "close") closeP(p.sym, p.price, by === "자체 엔진" ? "정리" : "AI 정리");
  else if (kind !== "keep") feed(`🗂 ${by === "자체 엔진" ? "" : "[" + shortMd(by) + "] "}${p.ko} ${kind === "run" ? "익절 풀고 ATR×3 추적 시작" : kind === "trail" ? `손절 ${fmt(prev.sl)}→${fmt(p.sl)}` : kind === "tp" ? `익절 ${prev.tp != null ? fmt(prev.tp) : "없음"}→${fmt(p.tp)}` : "손절 본전 이동"} (${r.toFixed(2)}R · ${why || ""})`);
  return { ok: true };
}
async function reviewPositions(cm) {
  const P = Object.values(S.pos); if (!P.length || !cm.length || Date.now() - prAt < 5 * 60e3) return; prAt = Date.now();
  const tgt = cm[prRot++ % cm.length], off = (S.adjOff || 0) > Date.now();
  const rows = P.map(p => { const d = draftOf(p), rg = S.regime[p.sym] || {}, a = posAtr(p); return { symbol: p.ko, side: p.side > 0 ? "long" : "short", entry: p.entry, price: p.price, R: +Rnow(p).toFixed(2), sl: p.sl, tp: p.tp ?? "없음(추적 중)",
    breakeven: p.be, running: !!p.run, atr: a ? +(+a).toPrecision(4) : null, strategy: p.name, regime: rg.label, htf: rg.htf, adx: rg.adx, minutes: Math.round((Date.now() - p.t) / 60e3), draft: d.kind, draft_why: d.why }; });
  const sys = `<role>
너는 코인 선물 포지션 관리자다. 보유 포지션마다 결정 하나를 고른다. 숫자 계산과 최종 검증은 코드가 한다.
</role>
<decisions>
hold: 지금은 바꾸지 않는다(draft 가 run 이면 15분 뒤 코드가 적용한다).
keep_tp: draft 의 run 을 거부하고 고정 익절을 유지한다. reason 에 <positions> 의 숫자 근거가 꼭 있어야 한다.
close: 지금 정리. 이익 +0.5R 이상이거나, -0.3R 이하인데 상위 추세(htf)가 반대일 때만.
breakeven: 손절을 본전으로. +0.5R 이상일 때.
run: 익절가를 풀고 손절을 ATR×3 뒤에서 따라간다. breakeven 이 true(+1R 을 찍음)일 때만. 6개 코인 1년 실측에서 고정 익절보다 나았다.${off ? "\n(지금은 AI 의 손절·익절 가격 조정이 채점 결과 손해라 잠시 꺼져 있다 — trail·tp 는 쓰지 않는다.)" : `
trail: 손절을 price 로 올린다. breakeven 이 true 일 때만, 현재가에서 ATR×1.5 이상 떨어진 곳. 손절을 넓히는(불리한 쪽으로 옮기는) 것은 금지.
tp: 익절가를 price 로 바꾼다. 진입가에서 1R~4R. 원래보다 멀리 늘리는 건 htf 가 포지션 방향과 같고 adx 25 이상일 때만.`}
</decisions>
<rules>
- 롱: 손절 < 현재가 < 익절 · 숏: 익절 < 현재가 < 손절.
- draft 는 코드가 실측 근거로 낸 초안이다. 초안과 다르게 하려면 reason 에 <positions> 의 숫자 하나를 근거로 쓴다.
- 데스크 상태: ${moodText()} · ${fngText()}
</rules>
<output>
JSON: {"decisions":[{"symbol":"BTC","decision":"hold","price":0,"reason":"한 문장"}]}
</output>`;
  let raw = "", route = null, sch = false;
  try { const r = await OS.askJSON(brainStream, { target: tgt, messages: [{ role: "system", content: sys }, { role: "user", content: `<positions>\n${JSON.stringify(rows)}\n</positions>\nJSON만:` }], schema: OS.posSchema(P.map(p => p.ko)), maxTokens: 380, temperature: 0.2 }); raw = r.raw; route = r.route; sch = r.schema; }
  catch (e) { return; }
  let arr = []; try { const o = JSON.parse((raw.match(/\{[\s\S]*\}|\[[\s\S]*\]/) || ["{}"])[0]); arr = Array.isArray(o) ? o : Array.isArray(o.decisions) ? o.decisions : [o]; } catch (e) {}
  // 환각 필터: 보유 종목과 정확히 일치(퍼지 매칭 금지) · 허용 결정만 · 코드 조건 충족만
  const by = route?.model || tgt.model, done = [], dropped = [];
  for (const d of (Array.isArray(arr) ? arr : []).slice(0, 8)) {
    const sym0 = String(d?.symbol || "").toUpperCase().replace(/USDT$/, ""), p = P.find(x => x.ko === sym0), dec = String(d?.decision || "").toLowerCase(), why = String(d?.reason || "").slice(0, 60);
    if (!p || !S.pos[p.sym]) { dropped.push(`${sym0 || "?"}: 보유하지 않은 종목`); continue; }
    if (off && (dec === "trail" || dec === "tp")) { dropped.push(`${p.ko}: 가격 조정 일시 중지 중`); continue; }
    const dr = draftOf(p);
    if (dec === "hold") continue;   // '안 바꿈' = 이의 없음. 작은 모델은 거의 항상 hold 라고 답해서, 이것을 거부로 치면 실측 우위가 있는 초안이 늘 막힌다(2026-10-06 qwen2.5:3b 5/5 hold)
    if (dec === "keep_tp") { if (dr.kind !== "run" || p.keep || off) continue; if (!/\d/.test(why)) { dropped.push(`${p.ko}: 초안 거부에 숫자 근거 없음`); continue; }
      p.keep = { by, t: Date.now() }; applyAdj(p, "keep", by, null, why); done.push(`${p.ko} 고정 익절 유지(초안 거부: ${why})`); continue; }
    const r = applyAdj(p, dec, by, d?.price, why); (r.ok ? done : dropped).push(r.ok ? `${p.ko} ${dec}(${why})` : r.why);
  }
  S.review2 = { t: Date.now(), by: shortMd(by), done, dropped, schema: sch };
  feed(`🗂 [${shortMd(by)}] 포지션 관리${sch ? "(스키마)" : ""}: ${done.length ? done.join(" · ") : "모두 유지"}${dropped.length ? ` · 검증 탈락 ${dropped.length}건(${dropped.slice(0, 2).join(" / ")})` : ""}`);
  save();
}
// 조정 채점: 같은 시간봉으로 '조정 전 계획 그대로였다면'을 다시 돌려 실제 결과와의 차이(ΔR)를 기록
function cfExit(q, st, cs, I, from) {
  let sl = st.sl, be = st.be; const tp = st.tp, run = st.run, step = cs.length > 1 ? cs[1].t - cs[0].t : 3600e3;
  for (let i = 0; i < cs.length; i++) { const b = cs[i]; if (b.t + step <= from) continue;
    if (b.t > st.deadline) return { px: b.o, done: true };
    if (q.side > 0 ? b.l <= sl : b.h >= sl) return { px: sl, done: true };
    if (tp != null && (q.side > 0 ? b.h >= tp : b.l <= tp)) return { px: tp, done: true };
    const fav = q.side > 0 ? b.h - q.entry : q.entry - b.l;
    if (!be && fav >= q.rDist) { sl = q.side > 0 ? q.entry * (1 + FW.fee) : q.entry * (1 - FW.fee); be = true; }
    if (run && I.atr[i]) { const n = b.c - q.side * 3 * I.atr[i]; if ((n - sl) * q.side > 0) sl = n; } }
  return { px: cs.at(-1).c, done: false };
}
let adjAt = 0;
export async function scoreAdj(force = false) {
  if ((!force && Date.now() - adjAt < 120e3) || !(S.adjQ || []).length) return; adjAt = Date.now();
  for (const q of S.adjQ.splice(0, 4)) {
    const mk = await getTF(q.sym, q.tf || "60").catch(() => null); if (!mk) continue;
    for (const a of q.adj) { const st = a.kind === "keep" ? a.alt : a.prev; if (!st) continue;
      const cf = cfExit(q, st, mk.cs, mk.I, a.t), pret = (cf.px - q.entry) / q.entry * q.side - FW.fee, cfR = Math.max(-q.margin, q.notional * pret) / (q.risk || 1), dR = +(q.R - cfR).toFixed(2);
      const who = a.by === "자체 엔진" ? "자체 엔진" : "AI", A = ((S.adjStat ||= {})[who] ||= { n: 0, dR: 0, plus: 0 }), K = ((S.adjKind ||= {})[a.kind] ||= { n: 0, dR: 0 });
      A.n++; A.dR = +(A.dR + dR).toFixed(2); if (dR > 0) A.plus++; K.n++; K.dR = +(K.dR + dR).toFixed(2);
      (S.adjLog ||= []).unshift({ t: Date.now(), ko: q.ko, kind: a.kind, by: a.by === "자체 엔진" ? a.by : shortMd(a.by), R: q.R, cfR: +cfR.toFixed(2), dR, open: !cf.done }); S.adjLog = S.adjLog.slice(0, 20);
      feed(`🧮 조정 채점: ${q.ko} ${a.kind}(${a.by === "자체 엔진" ? "엔진" : shortMd(a.by)}) → 실제 ${q.R}R vs 그대로였다면 ${cfR.toFixed(2)}R = ${dR >= 0 ? "+" : ""}${dR}R`);
      if (Math.abs(dR) >= 0.5) BRAIN.learn({ type: dR > 0 ? "패턴" : "교훈", coin: q.ko, text: `포지션 ${a.kind} 조정(${a.by === "자체 엔진" ? "엔진" : shortMd(a.by)}) ${dR > 0 ? "+" : ""}${dR}R ${dR > 0 ? "이득" : "손해"} — ${a.why || ""}`, model: "조정 채점", w: 1.3, key: `adj:${a.kind}:${dR > 0 ? "+" : "-"}` }); }
    const A = S.adjStat?.AI; if (A && A.n >= 10 && A.dR < 0 && !((S.adjOff || 0) > Date.now())) { S.adjOff = Date.now() + 3 * 864e5; S.adjStat.AI = { n: 0, dR: 0, plus: 0, prev: A }; feed(`🗂 AI 익절·손절 가격 조정이 원래 계획보다 누적 ${A.dR}R 손해(${A.n}건) → 3일간 코드 초안만 적용(되돌림)`); BRAIN.learn({ type: "교훈", text: `AI 의 익절·손절 가격 조정 ${A.n}건 누적 ${A.dR}R — 3일 중지`, model: "조정 채점", w: 2 }); }
  }
  save();
}
export function adjState() { load(); return { stat: S.adjStat || {}, kind: S.adjKind || {}, log: (S.adjLog || []).slice(0, 8), off: (S.adjOff || 0) > Date.now() ? S.adjOff : 0, pending: (S.adjQ || []).length, schema: OS.schemaStats() }; }

// ── AI 모델 = 승인 담당: 검증된 신호를 뉴스·지식·성적 맥락으로 승인/거절하고 리스크(0.5~1%)를 정한다 ──
function model(name) { return S.models[name] || (S.models[name] = { prov: "", pnl: 0, fills: 0, wins: 0, opened: 0, approved: 0, rejected: 0, lessons: [] }); }
let mRot = 0, mBackoff = 0, mFails = 0, mBusy = false;
export async function modelStep() {
  load(); const cm = connectedModels(); if (mBusy || !cm.length || Date.now() < mBackoff) return;
  scoreScans(); whaleTrust();
  if (!S.queue.length && Object.keys(S.pos).length && Date.now() - prAt >= 5 * 60e3) { mBusy = true; try { await reviewPositions(cm); } finally { mBusy = false; } return; }
  if (!S.queue.length) { if (Date.now() - lastScan < 30e3) return; lastScan = Date.now(); mBusy = true; try { await scanStep(cm); } finally { mBusy = false; } return; }
  mBusy = true; try { await approveNext(cm); } finally { mBusy = false; }
}
// 🔍 모델 순환 스캔: 신호가 없을 때 연결된 모든 모델이 차례로(한 번에 하나 — 4GB GPU) 코인 하나씩 읽고 방향 의견을 낸다.
//   의견은 1시간 뒤 실제 가격으로 채점 → 모델별 '시장 읽기 적중률'을 학습하고, 승인 검토 때 다른 모델들의 최근 의견으로 함께 쓴다.
let lastScan = 0, sRot = 0, cRot = 0;
async function scanStep(cm) {
  const tgt = cm[sRot++ % cm.length], [ko, sym] = COINS[cRot++ % COINS.length], price = S.dec[sym]?.price; if (!price) return;
  const rg = S.regime[sym] || {}, br = S.brief?.[sym]?.text || "";
  try { await coinResearch(sym); } catch (e) {} try { await whaleSignal(sym); } catch (e) {}
  let myRead = null; try { myRead = await CL.readNow(sym, ["5", "15", "60"]); } catch (e) {}
  const myTxt = myRead && Object.keys(myRead).length ? Object.entries(myRead).map(([tf, xs]) => `${tf === "60" ? "1시간" : tf + "분"}: ${xs.map(x => x.name + (x.dir > 0 ? "↑" : x.dir < 0 ? "↓" : "·")).join(" ")}`).join(" / ") : "";
  const brainTxt = [...BRAIN.recallType("핵심", 2, ko), ...BRAIN.recallType("교훈", 2, ko)].join(" / ").slice(0, 260);
  S.scan = { model: shortMd(tgt.model), ko, sym, regime: `${rg.label || "판단중"} · 시장 읽기`, t: Date.now() };
  let raw = "", route;
  try {
    ({ raw, route } = await OS.askJSON(brainStream, { target: tgt, fallback: false, schema: OS.SCAN_SCHEMA, maxTokens: 120, temperature: 0.2, messages: [
      { role: "system", content: '너는 코인 선물 시장 분석가다. 주어진 자료만 보고 앞으로 1시간 방향을 판단한다. 반드시 JSON 한 줄: {"bias":1|0|-1,"conf":0~100,"note":"한국어 한 문장"}' },
      { role: "user", content: `${ko} 현재가 ${price} · 1시간봉 국면: ${rg.label || "?"} (ADX ${rg.adx ?? "?"}) · 4시간 추세: ${rg.htf > 0 ? "상승" : rg.htf < 0 ? "하락" : "중립"}
시장 요약: ${br}
피처: ${Object.entries(S.feat[sym] || {}).map(([k, v]) => k + " " + (+v).toFixed(2)).join(", ")}\n리서치: ${researchText(sym)} · ${fngText()}\n${_whC[sym] ? WC.explain(_whC[sym].s) : ""}${myTxt ? "\n사용자 차트 터미널 보조지표 현재 방향: " + myTxt : ""}${brainTxt ? "\n과거에서 배운 것(참고): " + brainTxt : ""}
JSON만:` }] }));
  } catch (e) { (S.scans ||= {})[tgt.model] = { ko, sym, err: String(e?.message || e).slice(0, 40), t: Date.now() }; return; }
  let j = {}; try { j = JSON.parse((raw.match(/\{[\s\S]*\}/) || ["{}"])[0]); } catch (e) {}
  const bias = Math.sign(+j.bias || 0), conf = Math.max(0, Math.min(100, Math.round(+j.conf || 0))), note = String(j.note || "").slice(0, 70);
  const name = route?.model || tgt.model, M = model(name); M.prov = route?.id || tgt.id; M.scans = (M.scans || 0) + 1;
  (S.scans ||= {})[name] = { ko, sym, bias, conf, note, price, t: Date.now() };
  { const f0 = S.feat[sym] || {}; (S.scanLog ||= []).push({ m: name, sym, ko, bias, conf, price, t: Date.now(), feat: { ...f0 }, reg: BRAIN.regimeOf(f0) }); } if (S.scanLog.length > 300) S.scanLog.splice(0, S.scanLog.length - 300);
  feed(`🔍 [${shortMd(name)}] ${ko} 시장 읽기: ${bias > 0 ? "▲상승" : bias < 0 ? "▼하락" : "· 중립"} ${conf}% — ${note || "근거 없음"}`);
  if (conf >= 70 && note) BRAIN.learn({ type: "관찰", coin: ko, regime: rg.key || "", text: note, model: "스캔:" + shortMd(name), w: 0.8 });
  // 🤖 AI 내 지표 실험 진입: 확신 75%↑ + 내 차트 지표(15분) 60%↑ 같은 방향 + 4시간 추세 역행 아님 → 리스크 0.25% 데모 진입 (실전 성적이 나쁘면 자동 중지)
  try { aiChartExperiment({ name, ko, sym, bias, conf, note, price, myRead, rg }); } catch (e) {}
  save();
}
function scoreScans() {   // 1시간 지난 스캔 의견을 실제 가격으로 채점
  const now = Date.now(); for (const x of S.scanLog || []) { if (x.done || now - x.t < 3600e3) continue; const p = S.dec[x.sym]?.price; if (!p) continue;
    x.done = true; if (!x.bias) continue; const M = model(x.m), hit = Math.sign(p - x.price) === x.bias; M.scanN = (M.scanN || 0) + 1; if (hit) M.scanHit = (M.scanHit || 0) + 1;
    const mv = (p - x.price) / x.price * x.bias;
    if (x.feat) BRAIN.learnOutcome({ coin: x.ko || "", regime: x.reg || "", feat: x.feat, dir: x.bias, pnl: mv });   // 결과 채점 → 국면별 가중치 교정
    if (!hit && x.conf >= 75 && mv <= -0.004) { const d = x.bias > 0 ? "롱" : "숏", k = `scan:${shortMd(x.m)}|${x.reg || "일반"}|${d}`, ex = (S.scanMiss ||= {})[k] = (S.scanMiss[k] || 0) + 1;
      BRAIN.learn({ type: "교훈", coin: x.ko || "", regime: x.reg || "", text: `[${shortMd(x.m)}] ${x.reg || "일반"}에서 ${d} 읽기 과신 — 확신 ${x.conf}%인데 1시간 뒤 ${(mv * 100).toFixed(1)}% (누적 ${ex}회)`, model: "스캔 채점", w: 1.2, key: k }); } }
}
function peerViews(sym) {   // 승인 검토용: 다른 모델들의 최근(2시간) 같은 코인 의견 + 그 모델 적중률
  return Object.entries(S.scans || {}).filter(([, v]) => v.sym === sym && v.bias != null && Date.now() - v.t < 2 * 3600e3)
    .map(([m, v]) => { const M = S.models[m] || {}; return `${shortMd(m)} ${v.bias > 0 ? "상승" : v.bias < 0 ? "하락" : "중립"} ${v.conf}%${M.scanN >= 5 ? `(적중 ${Math.round((M.scanHit || 0) / M.scanN * 100)}%)` : ""}`; }).join(", ");
}
// 📡 에이전트 팀 스킬(도구)을 뉴럴 데스크에서도 실제로 실행: 선물 수급(OI·펀딩·상위계정)·호가창·고래 체결 → 승인 판단의 실제 입력
async function flowFacts(sym) {
  const jobs = [["거래소펀딩", "funding_scan", { symbol: sym }], ["선물수급", "futures_flow", { symbol: sym, period: "1h" }], ["호가창", "orderbook", { symbol: sym, exchange: "binancef" }], ["고래체결", "whale_trades", { symbol: sym, minUsd: sym === "BTCUSDT" ? 300000 : 100000 }]];
  const res = await Promise.all(jobs.map(async ([label, t, a]) => {
    try { const r = await Promise.race([TOOLS[t].run(a), new Promise((_, rej) => setTimeout(() => rej(new Error("시간초과")), 6000))]);
      const txt = String(r?.text || r || ""), lines = txt.split("\n");
      const interp = lines.filter(l => l.startsWith("해석:")).join(" ");
      const key = lines.filter(l => /펀딩|미결제|상위 포지션|비율|순 |시장가/.test(l)).slice(0, 2).join(" · ");
      return `${label}: ${(interp || key || lines[1] || "").replace(/\s+/g, " ").slice(0, 230)}${interp && key ? " (" + key.slice(0, 160) + ")" : ""}`;
    } catch (e) { return `${label}: 조회 실패(${String(e.message || e).slice(0, 30)})`; } }));
  return res;
}
function pickApprover(cm) {
  const k = mRot++, acc = c => { const M = S.models[c.model]; return M && M.scanN >= 8 ? (M.scanHit || 0) / M.scanN : 0; };
  const best = [...cm].sort((a, b) => acc(b) - acc(a))[0];
  return (k % 3 !== 2 && best && acc(best) >= 0.55) ? best : cm[k % cm.length];
}
// 승인 지시문(사용자 제공 프롬프트 가이드 3-6 적용: XML 로 역할·규칙·예시·출력 분리 + 이유 설명 + 서로 다른 입출력 예시 2개)
//   이전 지시문은 '거절 사유 예' 목록을 한 줄로 나열해, 작은 모델이 그 목록을 통째로 베껴 거절하는 일이 잦았다(앵무새 답).
export const APPROVE_SYS = `<role>
너는 코인 선물 데스크의 진입 승인 담당이다. 규칙 기반 전략이 낸 신호 하나를 <facts> 의 맥락으로 검토해 승인 또는 거절한다.
</role>

<context>
레버리지·손절·포지션 크기는 코드가 이미 계산했다(20배 이상, 손절은 청산거리의 40% 이하, 1회 손실 0.5~1%). 신호 자체도 과거 검증을 통과한 전략에서 나왔다.
그래서 기본은 승인이고, <facts> 에 신호와 강하게 반대되는 '구체적인 사실'이 있을 때만 거절한다.
</context>

<rules>
- reason 에는 <facts> 에 실제로 적힌 사실 한 가지를 숫자와 함께 쓴다. 일반론이나 여러 사유의 나열은 쓰지 않는다(근거가 없는 거절은 검증된 신호를 버리는 손실이기 때문이다).
- 거절할 만한 경우: 4시간 추세가 신호와 반대 / 뉴스 심리 점수가 신호와 반대로 ±2 이상 / 고래·호가·펀딩이 신호와 강하게 반대 / 직전에 이미 크게 움직여 추격인 경우.
- risk 는 0.5 가 기본, 근거가 아주 뚜렷할 때만 1.
- 아래 예시 문장을 그대로 쓰지 않는다. 지금 <facts> 의 숫자로 새로 쓴다.
</rules>

<examples>
<example>
<facts>BTC 롱 신호 · 4시간 추세 상승 · 뉴스 심리 +1 · 고래 순매수 62%</facts>
<output>{"approve":true,"risk":0.5,"reason":"4시간 추세가 상승이고 고래 순매수 62%로 신호 방향과 같음"}</output>
</example>
<example>
<facts>SOL 롱 신호 · 4시간 추세 하락 · 펀딩 +0.06%(롱 과열)</facts>
<output>{"approve":false,"risk":0.5,"reason":"4시간 추세가 하락인데 펀딩 +0.06%로 롱이 과열"}</output>
</example>
</examples>

<output_format>
JSON 한 줄만: {"approve":true|false,"risk":0.5|1,"reason":"한국어 한 문장"}
</output_format>`;
// 앵무새 답 감지: 예전 지시문의 사유 목록이나 예시 문장을 그대로 베낀 reason
const echoReason = r => { const t = String(r || ""); return (t.match(/상위 추세 역행|뉴스 위험|횡보장에서 추세전략|직전 급등락 추격|실시간 수급/g) || []).length >= 2 || /고래 순매수 62%|펀딩 \+0\.06%/.test(t); };
async function approveNext(cm) {
  const it = S.queue[0], tgt = pickApprover(cm), v = VMAP()[it.vkey]; if (!v) { S.queue.shift(); return; }
  const plan = ENG.frameworkPlan({ sym: it.sym, entry: S.dec[it.sym]?.price, side: it.side, slPrice: it.sl, cat: v.cat, rr: rrFor(v), riskPct: riskFor(v, it.side), equity: equity() });
  if (!plan || plan.skip) { S.queue.shift(); feed(`${it.ko} ${it.name} 보류 — ${plan?.skip || "계획 실패"}`); return; }
  S.scan = { model: shortMd(tgt.model), ko: it.ko, sym: it.sym, regime: `${it.regime} · ${it.name} 승인 검토`, t: Date.now() };
  const nw = S.news && Date.now() - S.news.t < 3600e3 ? `뉴스 심리 ${S.news.score > 0 ? "+" : ""}${S.news.score}(${S.news.reason || ""})` : "뉴스 정보 없음";
  const kn = [...BRAIN.recallType("핵심", 2, it.ko), ...BRAIN.recallType("교훈", 2, it.ko), ...BRAIN.recallType("매매법", 2), ...BRAIN.recallType("지식", 1)].join(" / ");
  const th = BRAIN.timeAdvice(new Date().getHours());
  const flow = await flowFacts(it.sym);
  feed(`📡 ${it.ko} 수급 확인 — ${flow.map(f => f.slice(0, 70)).join(" | ")}`);
  let raw = "", route;
  try {
    ({ raw, route } = await OS.askJSON(brainStream, { target: tgt, fallback: true, schema: OS.APPROVE_SCHEMA, maxTokens: 140, temperature: 0.2, messages: [
      { role: "system", content: APPROVE_SYS },
      { role: "user", content: `<facts>
${it.ko} ${it.side > 0 ? "롱" : "숏"} 신호 · 전략: ${it.name} · 근거: ${it.why}
국면(1H): ${it.regime} · 상위추세(4H): ${it.htf > 0 ? "상승" : it.htf < 0 ? "하락" : "중립"} · 시장: ${S.brief?.[it.sym]?.text || ""}
이 전략 최근 성적: ${it.st.n}건 승률 ${it.st.wr}% 기대값 ${it.st.mean >= 0 ? "+" : ""}${it.st.mean}R (자체백테스트 ${it.st.bt}·실전 ${it.st.live})
계획: ${plan.lev}x · 손절 ${plan.slPct}% · 익절 ${plan.tpPct}% (1:${plan.rr}) · 청산거리 ${plan.liqPct}% · 리스크 $${plan.risk}
${nw} · ${fngText()} · 지금 시간대 성적: ${th ? `승률 ${th.wr}%` : "데이터 적음"}
${moodText()}
다른 AI 모델들의 최근 시장 읽기: ${peerViews(it.sym) || "없음"}
코인 리서치: ${researchText(it.sym) || "없음"}
${it.whale ? WC.explain(it.whale) : "고래 신호 없음"}
실시간 수급(팀 도구로 방금 조회):
${flow.join(" / ")}
참고 지식: ${kn || "없음"}
</facts>

JSON 한 줄만:` }] }));
  } catch (e) {
    mFails++; if (e?.status === 429 || /한도/.test(e?.message || "")) mBackoff = Date.now() + Math.min(90e3, 15e3 * mFails);
    feed(`[${shortMd(tgt.model)}] 승인 검토 실패(${String(e?.message || e).slice(0, 40)}) → 자체 엔진이 집행`); return;
  }
  mFails = 0;
  const name = route?.model || tgt.model, M = model(name); M.prov = route?.id || tgt.id;
  if (!S.queue.includes(it)) return;   // 그 사이 자체 엔진이 집행
  S.queue = S.queue.filter(x => x !== it);
  let j = {}; try { j = JSON.parse((raw.match(/\{[\s\S]*\}/) || ["{}"])[0]); } catch (e) {}
  const approve = j.approve === true || /"approve"\s*:\s*true/i.test(raw) || (j.approve == null && /승인/.test(raw) && !/거절/.test(raw));
  const reason = String(j.reason || "").slice(0, 60);
  // 사유 목록·예시를 그대로 베낀 거절은 판단이 아니므로 버리고, 검증된 신호를 기본 리스크로 집행한다
  if (!approve && echoReason(j.reason)) { M.echo = (M.echo || 0) + 1; feed(`[${shortMd(name)}] ${it.ko} ${it.name} 거절 사유가 지시문을 그대로 베낀 답 → 무시하고 자체 엔진이 기본 리스크로 집행`); openFrom(it, "자체 엔진"); save(); return; }
  if (!approve) { M.rejected++; feed(`[${shortMd(name)}] ${it.ko} ${it.name} 거절 — ${reason || "근거 부족"}`); return; }
  M.approved++;
  const risk = (+j.risk >= 1 && it.st.mean > 0.2) ? FW.maxRisk * riskFactor() : undefined;
  openFrom(it, name, risk, reason ? `승인: ${reason}` : "AI 승인");
  save();
}

// ── 🧠 AI 전략 회의(복기·개선): 성적표를 보고 무엇을 멈추고 무엇을 키울지 스스로 결정(범위 제한 후 적용) ──
let rRot = 0;
export async function reflect() {
  load(); const cm = connectedModels(), V = variants();
  const rows = V.map(v => ({ v, s: vstat(v.vkey) })).filter(x => x.s.n >= 5).sort((a, b) => b.s.mean - a.s.mean);
  const recent = S.trades.slice(0, 30), byWhy = recent.reduce((m, t) => (m[t.why] = (m[t.why] || 0) + 1, m), {});
  const facts = `자본 $${equity()} (시작 $${BANKROLL}) · 최근 30거래 청산사유 ${JSON.stringify(byWhy)} · 평균 ${recent.length ? (recent.reduce((a, t) => a + (t.R || 0), 0) / recent.length).toFixed(2) : 0}R
전략 성적(최근 20건 기대값): ${rows.slice(0, 14).map(x => `${x.v.vkey}=${x.s.mean >= 0 ? "+" : ""}${x.s.mean}R/${x.s.n}건/승${x.s.wr}%${isActive(x.v) ? "(실전)" : ""}`).join(" · ")}
코인 국면: ${COINS.map(([ko, sym]) => `${ko} ${S.regime[sym]?.label || "?"}`).join(" · ")}
뉴스: ${S.news ? `${S.news.score} ${S.news.reason || ""}` : "없음"} · ${fngText()}
${moodText()}
관망 규칙(v${S.hold.ver}): ${HR.RULES.map(r => `${r.id}=${S.hold.rules[r.id].on ? "켜짐 " + HR.ruleText(r.id, S.hold.rules[r.id].p) : "꺼짐"}`).join(" · ")}
관망한 신호 채점(손절 먼저=관망 정답): ${Object.entries(S.holdScore || {}).map(([k, h]) => `${k} ${h.right}/${h.n}`).join(" · ") || "아직 없음"}${S.holdEval ? `
지난 규칙 점검: 데스크 재연 평균 ${S.holdEval.base.all.mean}R · 가장 나은 후보 ${S.holdEval.top[0]?.e || "-"}(${S.holdEval.top[0]?.why || ""})` : ""}`;
  // 결정론적 개선(항상): 실전에서 최근 5건 합 ≤ −3R 이면 4시간 쉬게 함
  for (const x of rows) { const live = (S.eng.stats[x.v.vkey]?.tr || []).filter(t => t.src === "live").slice(-5); if (live.length >= 5 && live.reduce((a, t) => a + t.R, 0) <= -3) { S.eng.paused[x.v.vkey] = Date.now() + 4 * 3600e3; feed(`🧠 ${x.v.name}@${x.v.tf} 실전 5연속 부진 → 4시간 정지`); } }
  if (!cm.length) { S.review = { t: Date.now(), text: "AI 모델 없음 — 통계 규칙만 적용", facts }; save(); return; }
  const tgt = cm[rRot++ % cm.length]; let raw = "";
  try {
    await brainStream({ messages: [
      { role: "system", content: `너는 코인 선물 데스크의 수석 전략가다. 아래 성적표를 보고 수익을 내려면 무엇을 바꿀지 결정한다. 할 수 있는 조치: pause(최대 3개, 부진 전략 2시간 정지), rr(전략별 손익비 1.3~3.0 조정), note(팀에 남길 한 줄 교훈). 근거 없는 변경 금지.
또 try 로 매매법 개선·수정·조합 실험을 제안할 수 있다(다음 자체 백테스트에서 검증, 통과해야만 채택): base·with 는 아래 매매법 키, filters 는 ${Object.keys(ENG.FILTERS).join("/")} 중.
또 hold 로 '관망 규칙' 하나를 고치자고 제안할 수 있다(다음 자체 백테스트에서 데스크처럼 다시 돌려 평균이 표준오차(최소 0.02R) 이상 좋아지고 전·후반 둘 다 나빠지지 않아야 채택): rule 은 ${HR.RULES.map(r => r.id).join("/")} 중 하나, on 은 true/false, p 는 값(streak 은 {"L":연속손실수,"h":휴식시간}).
매매법 키: ${ENG.LIB.filter(r => r.tf !== "240").map(r => r.key).join(", ")}
반드시 JSON 한 줄: {"pause":["전략키"],"rr":{"전략키":2.0},"try":[{"base":"키","with":"키","filters":["adx"],"rr":2.5}],"hold":{"rule":"adx","on":true,"p":20},"note":"한 문장"}` },
      { role: "user", content: facts }],
      role: "fast", target: tgt, fallback: true, json: true, maxTokens: 420, temperature: 0.3, noThink: true, onContent: d => raw += d, onThink: () => {} });
  } catch (e) { feed(`🧠 전략 회의 실패(${String(e?.message || e).slice(0, 40)})`); return; }
  let j = {}; try { j = JSON.parse((raw.match(/\{[\s\S]*\}/) || ["{}"])[0]); } catch (e) {}
  const VK = new Set(V.map(v => v.vkey)), done = [];
  for (const k of (Array.isArray(j.pause) ? j.pause : []).slice(0, 3)) if (VK.has(k) && vstat(k).mean < 0) { S.eng.paused[k] = Date.now() + 2 * 3600e3; done.push(`${k} 정지`); }
  for (const [k, val] of Object.entries(j.rr || {})) if (VK.has(k) && Number.isFinite(+val)) { S.eng.rr[k] = Math.max(1.3, Math.min(3, +val)); done.push(`${k} 손익비 1:${S.eng.rr[k]}`); }
  for (const g of (Array.isArray(j.try) ? j.try : []).slice(0, 3)) { if (!ENG.LIB_BY_KEY[g?.base]) continue;
    const gene = { base: g.base, ...(ENG.LIB_BY_KEY[g.with] ? { with: g.with, win: 3 } : {}), ...(Array.isArray(g.filters) ? { filters: g.filters.filter(f => ENG.FILTERS[f]).slice(0, 3) } : {}), ...(Number.isFinite(+g.rr) ? { rr: Math.max(1.3, Math.min(3, +g.rr)) } : {}) };
    (S.eng.evoSeeds ||= []).push(gene); done.push(`실험 제안: ${ENG.geneName(gene)}`); }
  const note = String(j.note || "").slice(0, 80);
  if (j.hold && HR.RULE_BY[j.hold.rule]) { const e = { id: j.hold.rule, ...(typeof j.hold.on === "boolean" ? { on: j.hold.on } : {}), ...(j.hold.p != null && j.hold.p !== "" ? { p: j.hold.p } : {}) };
    if ((e.on != null || e.p != null) && HR.applyEdit(S.hold, e)) { S.holdProp = { e, by: shortMd(tgt.model), reason: note, t: Date.now() }; done.push(`관망 규칙 제안: ${HR.editText(e)} → 다음 자체 백테스트에서 검증`); } }
  if (note) BRAIN.learn({ type: "지식", text: note, model: "전략회의:" + shortMd(tgt.model), w: 1.8 });
  S.review = { t: Date.now(), by: shortMd(tgt.model), text: note || "변경 없음", actions: done, facts };
  feed(`🧠 AI 전략 회의(${shortMd(tgt.model)}): ${note || "변경 없음"}${done.length ? " · 적용: " + done.join(", ") : ""}`);
  save();
}

// 매매법 설계: 성과 좋은 모델이 차트 터미널 지표(146종)를 직접 조합해 매매법 + 커스텀 수식 지표를 만들고,
// 자동 백테스트 → 통과하면 사무실(에이전트 팀) 데모 장부로 인계한다. (HKUDS/AI-Trader·Ai-trader-pro·FinRL_DeepSeek 개념)
export async function designStrategy() {
  load(); const cm = connectedModels(); if (!cm.length) return;
  const ranked = cm.map(t => ({ t, m: model(t.model) })).sort((a, b) => b.m.pnl - a.m.pnl);
  const { t: tgt, m: M } = ranked[0];
  const Q = await import("../nuri-ai/quant.js");
  const style = STYLES[dRot % STYLES.length];               // 스타일 로테이션(단타·스윙·추세·역추세·돌파·평균회귀·다지표)
  const [ko, sym] = COINS[(dRot++ / STYLES.length | 0) % 3]; // BTC/ETH/SOL 돌아가며
  const mname = ko + " 선물";
  const catalog = Q.tvCatalogText ? Q.tvCatalogText() : "tv_rsi tv_macd tv_bb tv_ema tv_sma tv_adx tv_stoch tv_supertrend tv_cci tv_atr tv_donchian";
  let raw = "";
  try {
    await brainStream({ messages: [
      { role: "system", content: `너는 코인 선물 퀀트다. 목표는 '잃지 않는 것' — 승률 55%+·낙폭(MDD) 작게·타이트한 손절로 자본을 지킨다.
이번 과제: [${style.cls}] 스타일로 ${ko} ${style.iv}봉 매매법 하나를 설계. 접근: ${style.hint}
설계 원칙: ① 추세 필터로 역행 진입 방지 ② 과매수/과매도로 타점 ③ 보조지표 2개 이상 동시 확인(컨플루언스) ④ 손절은 익절보다 타이트. 반드시 custom 수식 지표 1개 이상 포함.
아래 JSON 스키마로만 출력(설명·코드블록 금지):\n{"name":"이름","indicators":[{"id":"r","type":"tv_rsi","length":14},{"id":"vm","type":"custom","expr":"수식"}],"long_entry":{"conditions":[{"left":"r","op":"<","right":40}]},"long_exit":{"conditions":[{"left":"r","op":">","right":65}]},"short_entry":{"conditions":[...]},"risk":{"leverage":2,"stop_loss_pct":${style.cls === "단타" ? 1 : 3},"take_profit_pct":${style.cls === "단타" ? 2 : 6}}}\n쓸 수 있는 보조지표(차트 터미널 ${Q.TV_TYPES ? Q.TV_TYPES.length : 146}종 전부 + custom 수식): ${catalog}\n추가 ICT/SMC·세션 지표(네이티브, 신호형은 조건에 ==1 또는 == -1 로): bos(구조돌파 ±1) fvg(FVG ±1) ob(오더블록 리테스트 ±1) sweep(유동성스윕 반전 ±1) disp(변위 ±1) premium(0~1, <0.3 디스카운트/>0.7 프리미엄) session(start,end 킬존 0/1).\ncustom expr 피연산자: close open high low volume · 지표 id · id.p1~p4.${BRAIN.recallType("매매법", 4).length ? "\n뇌가 아는 매매법(참고): " + BRAIN.recallType("매매법", 4).join(" / ") : ""}${BRAIN.recallType("지식", 2).length ? "\n지식: " + BRAIN.recallType("지식", 2).join(" / ") : ""}${M.lessons.length ? "\n내 교훈: " + M.lessons.join(" / ") : ""} 뇌가 이득난 규칙: ${BRAIN.refineForProfit(ko, "").text}` },
      { role: "user", content: `[${style.cls}] ${ko} 매매법 JSON 하나만:` }],
      role: "code", target: tgt, fallback: true, json: true, maxTokens: 800, temperature: 0.6, noThink: true, onContent: d => raw += d, onThink: () => {} });
  } catch (e) { feed(`[${shortMd(tgt.model)}] ${style.cls} 설계 응답 실패`); return; }
  let spec; try { spec = JSON.parse((raw.match(/\{[\s\S]*\}/) || [])[0]); } catch (e) { feed(`[${shortMd(tgt.model)}] 매매법 JSON 형식 오류`); return; }
  if (!spec || !spec.indicators) return;
  let norm; try { norm = Q.normalizeSpec({ ...spec, symbol: sym, interval: style.iv }); }
  catch (e) { feed(`[${shortMd(tgt.model)}] ${style.cls} 규격 미달: ${String(e.message || e).slice(0, 36)}`); return; }
  const bars = style.cls === "단타" ? 2000 : 1500;
  let cs; try { cs = (await candlesFor({ market: sym, exchange: "binancef", timeframe: style.tf }, bars)).cs; } catch (e) { return; }
  const bt = Q.backtest(norm, cs), wf = Q.walkForward(norm, cs);
  M.designs = (M.designs || 0) + 1;
  const winR = Math.round((bt.stats.win_rate ?? bt.stats.winrate ?? 0) * (bt.stats.win_rate <= 1 ? 100 : 1)) || null;
  const mdd = bt.stats.max_drawdown_pct ?? bt.stats.mdd ?? bt.stats.max_dd ?? null;
  S.designs = S.designs || []; S.designs.unshift({ model: shortMd(tgt.model), name: norm.name, cls: style.cls, tf: style.iv, coin: ko, ret: +(bt.stats.return_pct ?? 0).toFixed(1), pf: bt.stats.profit_factor ?? null, win: winR, mdd: mdd != null ? +(+mdd).toFixed(1) : null, pass: wf.pass, handed: false, t: Date.now() });
  S.designs = S.designs.slice(0, 20);
  feed(`[${shortMd(tgt.model)}] [${style.cls}] ${ko} "${norm.name}" → 수익 ${(bt.stats.return_pct ?? 0).toFixed(1)}%${winR ? " 승률 " + winR + "%" : ""}${mdd != null ? " 낙폭 " + (+mdd).toFixed(0) + "%" : ""} · ${wf.pass ? "✅ 통과 → 사무실 인계" : "불통과(계속 개선)"}`);
  // 견고성 관문(사무실 매매법과 동일): 운일확률 p≤0.1 · 5구간 60% 이상 이익 · 위생 — 통과해야 데모·실전 후보
  let rbOk = true;
  if (wf.pass) { try { const RB = await import("./lib/robust.js"), pt = RB.permutationTest(bt.trades.map(t => t.pnl)), mw = RB.multiWindow(Q, norm, cs, 5), hy = RB.hygiene(bt);
      rbOk = (pt.p == null || pt.p <= 0.1) && (mw.total < 3 || mw.positive >= Math.ceil(mw.total * 0.6)) && hy.ok !== false;
      if (!rbOk) { S.designs[0].pass = false; feed(`[${shortMd(tgt.model)}] "${norm.name}" 워크포워드 통과했지만 견고성 미달(운일확률 ${pt.p?.toFixed(2)} · 구간 ${mw.positive}/${mw.total}) → 보류`); } } catch (e) {} }
  if (wf.pass && rbOk) {
    try { const P = await import("../nuri-ai/paper.js");
      await P.addStrategy({ spec: norm, market: sym, exchange: "binancef", tf: style.tf, author: `뉴럴(${shortMd(tgt.model)})`,
        wf: { is: {}, oos: { ret: +(wf.oos?.return_pct ?? 0), pf: wf.oos?.profit_factor ?? null, n: wf.oos?.n_trades ?? 0 } }, cls: "crypto", mname });
      S.designs[0].handed = true;
    } catch (e) {}
    // 뉴럴 데스크 실전 후보에도 추가 → 다음 자체 백테스트에서 성적이 검증되면 실제로 매매에 쓰인다
    S.eng.custom = [...(S.eng.custom || []).filter(c => c.name !== norm.name), { key: "ai_" + Date.now().toString(36), name: norm.name, spec: norm, tf: style.tf === "1" ? "15" : style.tf }].slice(-8);
    S.eng.calibAt = 0;
    BRAIN.learn({ type: "전략", coin: ko, regime: "", text: `[${style.cls}] ${norm.name} 검증통과(${(wf.oos?.return_pct ?? 0).toFixed(0)}%) — ${(norm.indicators || []).map(i => i.type).slice(0, 4).join("+")}`, model: shortMd(tgt.model) });
  }
  save();
}


function shortMd(m) { return String(m).split("/").pop().replace(/-instruct|-chat|-\d{6,}/gi, "").slice(0, 16); }
// 연구·뉴스·회의용 AI 대상: 반드시 '설치/연결된' 모델을 지정해서 부른다 (지정 없이 부르면 로컬 전용 모드에서 조용히 실패했음)
let aRot = 0;
function aiTarget() { const cm = connectedModels(); return cm.length ? cm[aRot++ % cm.length] : null; }

// 뇌 상태·그래프·자체학습 공개 (UI용)
export const brainState = () => BRAIN.brainState();
export const brainGraph = () => BRAIN.graph(80);
export const brainThink = () => BRAIN.consolidate();
export const brainCanvas = () => BRAIN.toCanvas(120);
export const brainIQ = () => BRAIN.iqScore();
export const brainRefine = (coin, regime) => BRAIN.refineForProfit(coin, regime);
export const brainIngest = (note) => BRAIN.ingest(note);
export const brainRisk = () => BRAIN.riskState();
export function seedKnowledge() {
  try { if (localStorage.getItem("coin:kb-seeded") === "3") return; } catch (e) {}
  for (const [type, text] of STRATEGY_KB) BRAIN.learn({ type, text, model: "지식베이스", w: 2.2 });
  BRAIN.learn({ type: "지식", text: "청산거리≈1/레버리지, 손절은 청산거리 40% 이하: 20x≤2%·50x≤0.8%·100x≤0.4%·200x≤0.2%", model: "지식베이스", w: 3 });
  BRAIN.learn({ type: "지식", text: "1회 손실 0.5~1%, 명목=자본×리스크/손절폭, 물타기 금지, +1R 본절", model: "지식베이스", w: 3 });
  BRAIN.learn({ type: "지식", text: "검증: 5·15분봉 20x+ 스캘핑은 수수료가 엣지를 먹음 → 1시간봉+4H 추세필터가 유리", model: "자체백테스트", w: 3 });
  try { localStorage.setItem("coin:kb-seeded", "3"); } catch (e) {}
}

// 🌐 인터넷·뉴스·SNS 리서치: 매매법·보조지표 사용법·추세 보는 법·진입 타점·리스크 관리를 찾아 뇌에 저장 (결과·실패 모두 피드에 표시)
let wRot = 0;
const WEB_TOPICS = ["비트코인 선물 추세 판단 방법 ADX 이동평균", "코인 선물 진입 타점 잡는 법 지지 저항", "ICT 유동성 스윕 OTE 진입 방법", "볼린저밴드 스퀴즈 돌파 매매 사용법",
  "RSI 다이버전스 사용법 코인", "코인 선물 손익비 손절 기준 레버리지 관리", "crypto futures trend following strategy 1h", "bitcoin funding rate open interest trading signal",
  "코인 선물 횡보장 대응 매매법", "비트코인 커뮤니티 트위터 심리 오늘", "MACD 시그널 교차 매매법 실전", "crypto scalping fees risk reward"];
export async function researchStrategies() {
  load(); const q = WEB_TOPICS[wRot++ % WEB_TOPICS.length];
  let res; try { res = await webSearch(q, 6); } catch (e) { feed(`🌐 웹검색 실패("${q.slice(0, 18)}…"): ${String(e?.message || e).slice(0, 50)}`); save(); return; }
  const items = (res?.results || []).slice(0, 6);
  const text = items.map(r => `${r.title || ""}: ${(r.snippet || r.content || "").replace(/\s+/g, " ").slice(0, 240)}`).join("\n").slice(0, 2400);
  if (text.length < 60) { feed(`🌐 웹검색 결과 없음("${q.slice(0, 18)}…", ${res?.engine || "?"})`); save(); return; }
  const tgt = aiTarget(); if (!tgt) { feed("🌐 검색은 됐지만 요약할 AI 모델이 없음 — 로컬 모델 설치 필요"); save(); return; }
  let raw = "";
  try {
    await brainStream({ messages: [
      { role: "system", content: "다음 검색결과에서 코인 선물에 바로 쓸 수 있는 '매매법'(진입·손절·익절 규칙)과 '지식'(추세 판단법·지표 사용법·리스크 관리·대응법)을 각각 한 줄(45자 이내)로 3~5개만 뽑아라. 각 줄은 `매매법|내용` 또는 `지식|내용`. 출처에 없는 내용 지어내기 금지. 다른 말 금지." },
      { role: "user", content: text }],
      role: "fast", target: tgt, fallback: true, maxTokens: 320, temperature: 0.2, noThink: true, onContent: d => raw += d, onThink: () => {} });
  } catch (e) { feed(`🌐 검색 요약 실패: ${String(e?.message || e).slice(0, 50)}`); save(); return; }
  let added = 0;
  for (const line of raw.split("\n")) { const m = line.match(/^\s*[-*\d.)]*\s*(매매법|지식|대응)\s*[|:：]\s*(.+)$/); if (m) { BRAIN.learn({ type: m[1] === "대응" ? "지식" : m[1], text: m[2].replace(/["`*]/g, "").slice(0, 90), model: "웹:" + (res.engine || "검색"), w: 1.6 }); added++; } }
  feed(added ? `🌐 웹(${res.engine}) "${q.slice(0, 22)}…" → 매매법·지식 ${added}개 뇌에 저장` : `🌐 웹 검색은 됐으나 쓸만한 규칙 없음("${q.slice(0, 18)}…")`);
  save();
}
// 📰 뉴스·일정 위험 점검: 심리 점수(−2~+2) + 주요 발표(FOMC·CPI 등) 임박이면 신규 진입 45분 중지
let nRot = 0;
const NEWS_Q = ["bitcoin news today", "비트코인 뉴스 오늘", "crypto market news FOMC CPI this week", "이더리움 솔라나 뉴스 오늘"];
export async function newsCheck() {
  load(); const q = NEWS_Q[nRot++ % NEWS_Q.length];
  let res; try { res = await webSearch(q, 8); } catch (e) { feed(`📰 뉴스 검색 실패: ${String(e?.message || e).slice(0, 50)}`); save(); return; }
  const items = (res?.results || []).slice(0, 8); if (!items.length) { feed("📰 뉴스 결과 없음"); save(); return; }
  const tgt = aiTarget(); if (!tgt) return;
  const text = items.map(r => `- ${r.title}${r.date ? " (" + r.date + ")" : ""}: ${(r.snippet || "").slice(0, 160)}`).join("\n").slice(0, 2400);
  let raw = "";
  try {
    ({ raw } = await OS.askJSON(brainStream, { target: tgt, fallback: true, schema: OS.NEWS_SCHEMA, maxTokens: 160, temperature: 0.1, messages: [
      { role: "system", content: "너는 코인 시장 뉴스 분석가다. 헤드라인을 보고 ① 비트코인 단기 심리 score(-2 매우부정 ~ +2 매우긍정) ② 지금부터 몇 시간 안에 시장을 흔들 주요 일정/사건(FOMC·CPI·고용지표·대형 해킹·규제 발표 등)이 임박했는지 event(true/false) ③ 한 문장 reason. 확실하지 않으면 score 0, event false. JSON 한 줄만: {\"score\":0,\"event\":false,\"reason\":\"...\"}" },
      { role: "user", content: text + "\n" + fngText() }] }));
  } catch (e) { feed(`📰 뉴스 분석 실패: ${String(e?.message || e).slice(0, 50)}`); save(); return; }
  let j = {}; try { j = JSON.parse((raw.match(/\{[\s\S]*\}/) || ["{}"])[0]); } catch (e) {}
  const score = Math.max(-2, Math.min(2, Math.round(+j.score || 0))), event = j.event === true;
  S.news = { t: Date.now(), score, event, reason: String(j.reason || "").slice(0, 80), engine: res.engine, heads: items.slice(0, 4).map(r => r.title), blockUntil: event ? Date.now() + 45 * 60e3 : (S.news?.blockUntil || 0) };
  if (S.news.reason) BRAIN.learn({ type: "관찰", coin: "BTC", text: `뉴스 ${score > 0 ? "+" : ""}${score}: ${S.news.reason}`, model: "뉴스", w: 0.8 });
  feed(`📰 뉴스(${res.engine}) 심리 ${score > 0 ? "+" : ""}${score}${event ? " · ⚠ 주요 일정 임박 → 45분 신규 진입 중지" : ""} · ${S.news.reason}`);
  save();
}
export function resetBrain() { BRAIN.reset(); }

// ⚡ 손매매 추천 채점: 시장가 버튼·실시간 진입이 낸 추천을 실제 봉으로 따라가 '익절1 먼저 / 손절 먼저 / 24시간 무승부'를 기록 → 뇌가 교훈·패턴·함정으로 학습
export function trackCall(c = {}) {
  load(); if (!c.sym || !c.side || !c.entry || !c.sl || !c.tp1) return false;
  const L = (S.calls ||= []); if (L.some(x => !x.res && x.sym === c.sym && x.side === c.side && Date.now() - x.t < 30 * 60e3)) return false;
  const f0 = S.feat[c.sym] || {};
  L.unshift({ id: Date.now().toString(36), sym: c.sym, ko: c.ko || c.sym.replace("USDT", ""), side: c.side, entry: +c.entry, sl: +c.sl, tp1: +c.tp1, grade: c.grade || "", src: c.src || "시장가", t: Date.now(), feat: { ...f0 }, reg: BRAIN.regimeOf(f0), judges: Array.isArray(c.judges) ? c.judges.filter(j => j && j.who && (j.stance === "찬성" || j.stance === "반대")).slice(0, 4) : [] });
  S.calls = L.slice(0, 120); save(); return true;
}
let callAt = 0;
async function scoreCalls() {
  if (Date.now() - callAt < 120e3) return; callAt = Date.now();
  for (const c of (S.calls || []).filter(x => !x.res).slice(0, 6)) {
    let cs; try { cs = (await candlesFor({ market: c.sym, exchange: "binancef", timeframe: "5" }, 300)).cs; } catch (e) { continue; }
    let res = null, at = 0;
    for (const b of cs || []) { if (b.t + 300e3 <= c.t) continue; const hitSl = c.side > 0 ? b.l <= c.sl : b.h >= c.sl, hitTp = c.side > 0 ? b.h >= c.tp1 : b.l <= c.tp1;
      if (hitSl) { res = "손절"; at = b.t; break; } if (hitTp) { res = "익절1"; at = b.t; break; } }
    if (!res && Date.now() - c.t > 24 * 3600e3) { res = "무승부"; at = Date.now(); }
    if (!res) continue;
    const rD = Math.abs(c.entry - c.sl), px = res === "손절" ? c.sl : res === "익절1" ? c.tp1 : (S.dec[c.sym]?.price || c.entry), R = rD ? +(((px - c.entry) * c.side) / rD).toFixed(2) : 0;
    Object.assign(c, { res, at, R }); const d = c.side > 0 ? "롱" : "숏";
    // 🧑‍⚖️ 메타 심판(Actor → Judge → Meta-Judge · arXiv:2509.09751 의 3역할 폐루프 개념): 토론에서 찬성/반대한 심판을 실제 결과로 채점 → 다음 토론에서 그 심판의 반대에 주는 무게가 달라진다
    if (res !== "무승부") for (const j of c.judges || []) { const J = (S.judge ||= {})[j.who] ||= { n: 0, ok: 0 }; J.n++; if ((j.stance === "찬성") === (res === "익절1")) J.ok++; }
    if (res === "손절") { BRAIN.learnLoss({ coin: c.ko, regime: c.reg, feat: c.feat || {}, dir: c.side, roe: (px / c.entry - 1) * 100 * c.side });
      BRAIN.learn({ type: "교훈", coin: c.ko, regime: c.reg, text: `[${c.src}${c.grade ? " " + c.grade : ""}] ${c.reg} ${d} 추천이 손절 먼저 — 같은 자리 다시 나오면 관망`, model: "추천 채점", w: 1.6 }); }
    else if (res === "익절1") BRAIN.learn({ type: "패턴", coin: c.ko, regime: c.reg, text: `[${c.src}${c.grade ? " " + c.grade : ""}] ${c.reg} ${d} 추천 익절1 먼저 +${R}R`, model: "추천 채점", w: 1.6 });
    if (c.feat) BRAIN.learnOutcome({ coin: c.ko, regime: c.reg, feat: c.feat, dir: c.side, pnl: (px - c.entry) / c.entry * c.side });
    feed(`⚡ 추천 채점: ${c.ko} ${d} [${c.src}${c.grade ? "·" + c.grade : ""}] → ${res} ${R >= 0 ? "+" : ""}${R}R (${Math.round((at - c.t) / 60e3)}분)`);
  }
  save();
}
export function judgeStats() { load(); return Object.fromEntries(Object.entries(S.judge || {}).map(([k, v]) => [k, { n: v.n, ok: v.ok, acc: v.n ? Math.round(v.ok / v.n * 100) : null }])); }
// 심판의 '반대'에 줄 무게: 채점 8건 미만 = 1(보통) · 적중 45% 미만 = 0(무시) · 55% 이상 = 2(혼자서도 한 단계 내림)
export function judgeWeight(who) { load(); const j = (S.judge || {})[who]; if (!j || j.n < 8) return 1; const a = j.ok / j.n; return a < 0.45 ? 0 : a >= 0.55 ? 2 : 1; }
export function callStats() { load(); const L = S.calls || [], done = L.filter(x => x.res && x.res !== "무승부"), w = done.filter(x => x.res === "익절1").length;
  const byGrade = {}; for (const x of done) { const g = byGrade[x.grade || "기타"] ||= { n: 0, w: 0, R: 0 }; g.n++; if (x.res === "익절1") g.w++; g.R = +(g.R + (x.R || 0)).toFixed(2); }
  return { n: L.length, open: L.filter(x => !x.res).length, done: done.length, wins: w, wr: done.length ? Math.round(w / done.length * 100) : null, sumR: +done.reduce((a, x) => a + (x.R || 0), 0).toFixed(2), byGrade, judges: judgeStats(), list: L.slice(0, 8).map(({ feat, ...x }) => x) }; }

// ⏱ 상시 자동 실행(패널을 닫아도 돈다): 시세·포지션·신호(6초) · AI 승인 · 뇌 정리(1분) · 웹 리서치(3분) · 뉴스 위험(5분) · 매매법 개발(8분) · 전략 회의(10분)
let autoTimer = 0, autoK = 0, ticking = false;
export async function tick() {
  if (ticking) return state(); ticking = true;
  try {
    await step(); modelStep().catch(() => {}); autoK++;
    if (autoK % 10 === 5) { try { BRAIN.consolidate(); } catch (e) {} }
    if (autoK % 20 === 7) scoreCalls().catch(() => {});
    if (autoK % 20 === 13) { scoreShadow().catch(() => {}); scoreAdj().catch(() => {}); }
    if (autoK % 300 === 2) fngCheck().catch(() => {});
    if (autoK % 30 === 3) researchStrategies().catch(() => {});
    if (autoK % 50 === 8) newsCheck().catch(() => {});
    if (autoK % 80 === 40) designStrategy().catch(() => {});
    if (autoK % 100 === 60) reflect().catch(() => {});
    if (autoK % 150 === 20) chartDesk().catch(() => {});
  } finally { ticking = false; }
  return state();
}
export function startAuto() { onLeader(_startAuto); }
function _startAuto() { if (autoTimer) return; try { seedKnowledge(); } catch (e) {} autoTimer = setInterval(() => tick().catch(() => {}), 6000); tick().catch(() => {}); }
export function stopAuto() { clearInterval(autoTimer); autoTimer = 0; }
export const autoRunning = () => !!autoTimer;

export function state() {
  load();
  const wr = S.fills ? Math.round(S.wins / S.fills * 100) : 0;
  const neurons = NEURONS.map(k => ({ name: k, w: +S.w[k].toFixed(2), hit: S.hit[k].n ? Math.round(S.hit[k].ok / S.hit[k].n * 100) : null, n: S.hit[k].n })).sort((a, b) => b.w - a.w);
  const allPos = Object.values(S.pos);
  const traders = [{ name: "자체 엔진", prov: "self", pnl: +selfPnl().toFixed(2), hit: null, fills: 0, lessons: 0, pos: allPos.filter(P => P.trader === "자체 엔진").length }];
  for (const [name, m] of Object.entries(S.models))
    traders.push({ name: shortMd(name), full: name, prov: m.prov, pnl: +m.pnl.toFixed(2), hit: m.fills ? Math.round(m.wins / m.fills * 100) : null, fills: m.fills, wins: m.wins, lessons: 0,
      approved: m.approved || 0, rejected: m.rejected || 0, pos: allPos.filter(P => P.trader === name), scans: m.scans || 0, scanAcc: m.scanN >= 5 ? Math.round((m.scanHit || 0) / m.scanN * 100) : null, last: S.scans?.[name] || null });
  // 연결된 모델은 아직 승인한 신호가 없어도 리더보드에 항상 표시 (엔진 v2 이후 '승인해야 생기는' 문제 수정)
  for (const c of connectedModels()) if (!S.models[c.model]) traders.push({ name: shortMd(c.model), full: c.model, prov: c.id, pnl: 0, hit: null, fills: 0, wins: 0, lessons: 0, approved: 0, rejected: 0, pos: [], idle: true, scans: 0, scanAcc: null, last: null });
  traders.sort((a, b) => b.pnl - a.pnl || (b.approved + b.rejected) - (a.approved + a.rejected));
  const eq = equity(), peak = Math.max(S.peak || BANKROLL, eq), dd = peak > 0 ? +((peak - eq) / peak * 100).toFixed(1) : 0;
  const avgLev = allPos.length ? +(allPos.reduce((s, p) => s + (p.lev || 0), 0) / allPos.length).toFixed(1) : null;
  const avgSeed = allPos.length ? +(allPos.reduce((s, p) => s + (p.seed || 0), 0) / allPos.length).toFixed(1) : null;
  const V = variants(), engine = V.map(v => ({ vkey: v.vkey, name: v.name, cat: v.cat, tf: v.tf, active: isActive(v), paused: (S.eng.paused[v.vkey] || 0) > Date.now(), ...vstat(v.vkey), rr: rrFor(v) }))
    .filter(x => x.n > 0).sort((a, b) => (b.active - a.active) || (b.mean - a.mean));
  return { pnl: +S.pnl.toFixed(2), bankroll: BANKROLL, equity: eq, peak: +peak.toFixed(2), drawdown: dd, riskMode: riskMode(), avgLev, avgSeed, openN: allPos.length,
    fills: S.fills, winRate: wr, epoch: S.epoch, since: S.t0, nModels: connectedModels().length,
    neurons, traders, designs: (S.designs || []).slice(0, 10), nDesigns: (S.designs || []).length, handed: (S.designs || []).filter(d => d.handed).length,
    brain: BRAIN.brainState(), calls: callStats(), scan: S.scan || null, regime: S.regime, news: S.news, review: S.review, calib: S.eng.calib, calibrating,
    chartDesk: S.chartDesk || null, aiExp: { ...(S.aiExp || {}), stat: vstat("aichart@15") }, chartStrats: chartStrategies(),
    cfg: cfg(), dayN: S.day?.n || 0, mood: mood(), fng: S.fng || null, hold: holdState(), adj: adjState(), whale: { trust: whaleTrust(), last: Object.values(_whC).map(x => x.s).filter(x => x.status === "approved").slice(-6) }, review2: S.review2 || null, research: S.research || {},
    engine, nActive: engine.filter(x => x.active).length, setups: setups(engine), winrates: learnedWinrates(V), evo: { n: (S.eng.evo || []).length, seeds: (S.eng.evoSeeds || []).length, log: (S.eng.evoLog || []).slice(0, 3) }, queue: S.queue.length, heat: +(heat() / Math.max(1, eq) * 100).toFixed(2), dayPnl: +(S.day?.pnl || 0).toFixed(2),
    fw: { minLev: FW.minLev, risk: FW.baseRisk * 100, maxRisk: FW.maxRisk * 100, daily: FW.dailyStop * 100, heat: FW.maxHeat * 100, fee: FW.fee * 100 },
    pos: allPos.filter(P => P.trader === "자체 엔진"), dec: S.dec, feat: S.feat, trades: S.trades.slice(0, 64), feed: S.feed.slice(0, 24) };
}
// ocean-agent 개념: 검증된 셋업 순위 = 기대값 × 승률 × 신뢰도(표본 수) — 실측 성적으로만 계산
function regStat(vkey, reg) { let n = 0, r = 0; for (const t of S.eng.stats[vkey]?.tr || []) if (t.reg === reg) { n++; r += t.R; } return { n, mean: n ? r / n : 0 }; }
function setups(engine) {
  return engine.filter(e => e.n >= 8 && e.mean > 0).map(e => ({ vkey: e.vkey, name: e.name, tf: e.tf, mean: e.mean, wr: e.wr, n: e.n, active: e.active,
    score: +(e.mean * (e.wr / 100) * Math.min(1, e.n / 20) * 100).toFixed(1) })).sort((a, b) => b.score - a.score).slice(0, 12);
}
// 학습된 승률: 매매법 × 시장 국면별 실측(백테스트+실전) — 어떤 장에서 통하는지
function learnedWinrates(V) {
  const out = [];
  for (const v of V) { const tr = S.eng.stats[v.vkey]?.tr || [], by = {};
    for (const t of tr) if (t.reg) { const b = by[t.reg] ||= { n: 0, w: 0, r: 0 }; b.n++; if (t.R > 0) b.w++; b.r += t.R; }
    for (const [reg, b] of Object.entries(by)) if (b.n >= 5) out.push({ vkey: v.vkey, name: v.name, regime: reg, n: b.n, wr: Math.round(b.w / b.n * 100), mean: +(b.r / b.n).toFixed(3) }); }
  return out.sort((a, b) => b.mean - a.mean).slice(0, 40);
}
function selfPnl() { let m = 0; for (const n in S.models) m += S.models[n].pnl; return S.pnl - m; }
function fmt(v) { return v >= 1000 ? Math.round(v).toLocaleString() : v >= 1 ? v.toFixed(2) : v.toPrecision(4); }

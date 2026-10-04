// 🧠 뉴럴 데스크 — 연결된 AI 모델(+피처 뉴런)이 "직접" 데모 매매하고, 결과로 채점받아 가중치를 스스로 올리고 내린다.
// 에이전트 '팀 회의'가 아니라, 신호 뉴런들의 온라인 학습(퍼셉트론식)으로 돌아가는 자율 데모 트레이더.
// 전부 가상자금(데모)만 — 실주문·실자금·실지갑 없음.
import { candlesFor } from "../nuri-ai/agent.js";
import { brainStream, settings, PROVIDERS, modelKind, ollamaModels, ollamaPull } from "../nuri-ai/engine.js";
import * as BRAIN from "./brain.js";

// 내 PC Ollama 에 설치된 무료 모델 캐시 (주기적으로 갱신 — connectedModels 는 동기라 캐시를 읽는다)
let olCache = [], olInit = false;
export async function refreshOllama() { try { olCache = await ollamaModels(); } catch (e) { olCache = []; } return olCache; }

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
  const sized = [...olCache].sort((a, b) => olPref(a) - olPref(b)).slice(0, 6).map(m => ({ id: "ollama", model: m }));
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
  { k: "scalp_rsi", cls: "단타", tf: "1", iv: "1m", hint: "1분봉 RSI 과매수(>70)/과매도(<30) 반전 스캘핑. 빠른 손절(0.5~1%)·작은 익절. 추세 필터 EMA로 역행 방지." },
  { k: "scalp_bb", cls: "단타", tf: "1", iv: "1m", hint: "1분봉 볼린저밴드 하단 터치 후 밴드 내 복귀=매수, 상단은 반대. tv_bb 사용." },
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
];
let dRot = 0;
const KEY = "coin:neural";
const START = 10000;          // (구) 코인별 가상 증거금 — 아래 BANKROLL 기반 사이징으로 대체
const BANKROLL = 1000;        // 💵 전체 가상자금 $1000로 시작 (사용자만 초기화)
const LR = 0.06;              // 학습률 (맞으면 가중치↑ 틀리면↓)
const FEE = 0.0006;           // 왕복 수수료+슬리피지 가정
const MAXHOLD = 8 * 60 * 1000; // 최대 보유 8분 → 시간청산(짧은 세션에도 체결·학습이 쌓이게)
const cl = (v, lo = -1, hi = 1) => Math.max(lo, Math.min(hi, v));

// ── 피처 뉴런: 캔들에서 각자 [-1,1] 신호를 낸다 ──
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
  let bp = 0; for (let i = n - 6; i < n; i++) { const rng = cs[i].h - cs[i].l || 1; bp += ((cs[i].c - cs[i].l) / rng - 0.5) * 2; } bp /= 6;   // 종가가 봉 상단이면 매수압력
  return {
    "모멘텀": cl(mom(5) * 35 + mom(20) * 8),
    "추세(EMA)": cl((last / ema(50) - 1) * 45),
    "RSI": cl((rsi() - 50) / 28),
    "거래흐름": cl(flow * 2),
    "호가압력": cl(bp * 1.4),
    "변동성": cl(1 - vol * 55),   // 변동성 낮을수록 진입 우호(+), 급변동이면 리스크오프(−)
  };
}

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
  const trend = emaPct > 0.3 ? "상승추세" : emaPct < -0.3 ? "하락추세" : "횡보";
  const ob = rsiV >= 72 ? "과매수" : rsiV <= 28 ? "과매도" : rsiV >= 56 ? "약강세" : rsiV <= 44 ? "약약세" : "중립";
  const strong = adx >= 45 ? "강함" : adx >= 25 ? "보통" : "약함(횡보성)";
  return { rsi: Math.round(rsiV), trend, ob, emaPct: +emaPct.toFixed(2), mom5: +mom5.toFixed(2), macdHist: +macdHist.toFixed(2), pctB: +pctB.toFixed(2), stoK: Math.round(stoK), adx: Math.round(adx),
    text: `추세 ${trend}(EMA50 ${emaPct >= 0 ? "+" : ""}${emaPct.toFixed(2)}%, EMA20${last >= ema20 ? "위" : "아래"}) · 추세강도 ${strong}(ADX ${Math.round(adx)}) · RSI ${Math.round(rsiV)}(${ob}) · MACD ${macdHist >= 0 ? "상승" : "하락"} · 볼린저 ${pctB >= 0.8 ? "상단(과열)" : pctB <= 0.2 ? "하단(눌림)" : "중앙"} · 스토캐 ${Math.round(stoK)} · 모멘텀 5분 ${mom5 >= 0 ? "+" : ""}${mom5.toFixed(2)}%` };
}

// ── 상태 ──
function blank() {
  return { pnl: 0, peak: BANKROLL, fills: 0, wins: 0,
    w: Object.fromEntries(NEURONS.map(k => [k, 1])),              // 뉴런 가중치(학습으로 변함)
    hit: Object.fromEntries(NEURONS.map(k => [k, { ok: 0, n: 0 }])), // 뉴런별 적중
    models: {},                                                   // 연결된 LLM 모델 기여(이름→{ok,n,w})
    pos: {}, feat: {}, dec: {}, trades: [], feed: [], epoch: 0, t0: Date.now() };
}
let S = null;
// 💵 자금·낙폭 방어: $1000 기준 자본. 낙폭이 커지면 자동으로 작게·엄격하게 매매해 '천달러가 떨어지지 않게' 지킨다.
export function equity() { return +(BANKROLL + (S?.pnl || 0)).toFixed(2); }
function riskFactor() { const eq = equity(), peak = Math.max(S?.peak || BANKROLL, eq);
  if (eq < BANKROLL * 0.9) return 0.2;        // -10% 이하: 아주 보수적
  if (eq < peak * 0.93) return 0.5;           // 고점 대비 -7%: 절반 축소
  return 1; }
function posSize() { return Math.max(20, +(equity() * 0.5 * riskFactor()).toFixed(2)); }   // 포지션 명목 = 자본의 50% × 위험계수
function bumpPeak() { if (S) S.peak = Math.max(S.peak || BANKROLL, equity()); }
export const riskMode = () => riskFactor() < 0.5 ? "방어(최소)" : riskFactor() < 1 ? "방어(축소)" : "정상";
export function load() { if (!S) { try { S = JSON.parse(localStorage.getItem(KEY)) || blank(); } catch (e) { S = blank(); } for (const k of NEURONS) { S.w[k] ??= 1; S.hit[k] ??= { ok: 0, n: 0 }; } } return S; }
function save() { try { localStorage.setItem(KEY, JSON.stringify({ ...S, trades: S.trades.slice(-60), feed: S.feed.slice(-40) })); } catch (e) {} }
export function reset() { S = blank(); save(); return S; }
const feed = (t) => { S.feed.unshift({ t: Date.now(), text: t }); if (S.feed.length > 40) S.feed.pop(); };

// ── 결정: 가중 뉴런 합의 (+연결 모델 보팅은 addModelVote 로) ──
export function decide(feat) {
  let num = 0, den = 0; const parts = {};
  for (const k of NEURONS) { const w = Math.max(0.05, S.w[k]); parts[k] = feat[k] * w; num += parts[k]; den += w; }
  const score = den ? num / den : 0;                 // -1..1
  const dir = score > 0.12 ? 1 : score < -0.12 ? -1 : 0;
  return { score: +score.toFixed(3), dir, conf: Math.round(cl(Math.abs(score) * 1.6) * 100), parts };
}

// ── 한 스텝: 코인별로 피처→결정→데모 포지션→정산→학습 ──
export async function step() {
  load();
  if (!olInit || S.epoch % 20 === 0) { olInit = true; refreshOllama(); }   // 내 PC Ollama 설치 모델 목록 갱신(비차단)
  for (const [ko, sym] of COINS) {
    let cs; try { cs = (await candlesFor({ market: sym, exchange: "binancef", timeframe: "1" }, 300)).cs; } catch (e) { continue; }
    if (!cs || cs.length < 60) continue;
    const price = cs.at(-1).c, feat = featuresOf(cs); let d = decide(feat);
    (S.brief ||= {})[sym] = marketBrief(cs);   // 모델용 '사람 말' 시장 요약(추세·RSI·모멘텀)
    const regime = BRAIN.regimeOf(feat), bp = BRAIN.predict(feat, regime);   // 🧠 뇌의 지능(학습된 예측)을 결정에 섞는다
    if (bp.dir && bp.trust > 0) {
      const blend = d.score * 0.6 + bp.s * 0.4 * (0.5 + bp.trust * 0.5);
      d = { ...d, score: +blend.toFixed(3), dir: blend > 0.12 ? 1 : blend < -0.12 ? -1 : 0, conf: Math.min(99, Math.round((Math.abs(blend) * 1.6 * 100 + bp.conf) / 2)), brain: bp.dir };
    }
    S.feat[sym] = feat; S.dec[sym] = { ...d, price };
    markModels(sym, price);
    const p = S.pos[sym];
    // 보유 중이면 마크 + 청산 판단(반대 신호 또는 손절/익절)
    if (p) {
      const roe = (price - p.entry) / p.entry * p.side * 100;
      p.roe = +roe.toFixed(2); p.price = price;
      const flip = d.dir !== 0 && d.dir !== p.side, hardSL = roe < -2, hardTP = roe > 3, timeout = Date.now() - p.t > MAXHOLD;
      if (flip || hardSL || hardTP || timeout) closePos(sym, price, flip ? "반대신호" : hardSL ? "손절" : hardTP ? "익절" : "시간청산");
    }
    // 무포지션 + 신호 있으면 진입 — 낙폭 방어 모드면 더 엄격(자본 지키기) + 과거 손절 닮은 자리 회피
    const minConf = riskFactor() < 1 ? 45 : 25;
    if (!S.pos[sym] && d.dir !== 0 && d.conf >= minConf) {
      const risk = BRAIN.trapRisk(feat, regime, d.dir);
      const bf = S.brief?.[sym], against = bf && ((d.dir === 1 && bf.trend === "하락추세") || (d.dir === -1 && bf.trend === "상승추세"));
      if (risk >= 0.75) feed(`${ko} ${d.dir > 0 ? "롱" : "숏"} 보류 — 과거 손절 패턴과 ${Math.round(risk * 100)}% 유사 (뇌 회피)`);
      else if (riskFactor() < 1 && against) feed(`${ko} 방어 모드 — 추세 역행 진입 안 함`);
      else openPos(sym, ko, d.dir, price, feat);
    }
  }
  S.epoch++;
  save();
  return state();
}
function openPos(sym, ko, side, price, feat) {
  S.pos[sym] = { ko, side, entry: price, price, size: posSize(), roe: 0, t: Date.now(), feat: { ...feat } };
  feed(`${ko} ${side > 0 ? "▲ 롱" : "▼ 숏"} 진입 @ ${fmt(price)} (확신 ${S.dec[sym]?.conf}%)`);
}
function closePos(sym, price, why) {
  const p = S.pos[sym]; if (!p) return;
  const ret = (price - p.entry) / p.entry * p.side - FEE;      // 수수료 반영
  const pnl = p.size * ret;
  S.pnl += pnl; S.fills++; if (pnl > 0) S.wins++; bumpPeak();
  S.trades.unshift({ ko: p.ko, side: p.side, entry: p.entry, exit: price, roe: +(ret * 100).toFixed(2), pnl: +pnl.toFixed(2), why, t: Date.now() });
  if (S.trades.length > 60) S.trades.pop();
  // ── 학습: 이 거래가 맞았나? 각 뉴런의 진입 당시 신호가 결과와 같은 방향이었는지로 가중치 업데이트 ──
  const good = ret > 0 ? 1 : -1;
  for (const k of NEURONS) {
    const sig = p.feat[k] || 0; if (Math.abs(sig) < 0.08) continue;
    const agreed = Math.sign(sig) === p.side ? 1 : -1;        // 이 뉴런이 이 방향에 동의했나
    const correct = agreed === good;                           // 동의가 옳았나
    S.hit[k].n++; if (correct) S.hit[k].ok++;
    S.w[k] = cl(S.w[k] + LR * (correct ? 1 : -1) * Math.abs(sig), 0.05, 3);   // 맞으면↑ 틀리면↓
  }
  // 🧠 뇌 지능에도 결과 학습(국면별 가중치 교정) + 손절이면 '왜 났는지' 함정으로 기억
  const regime = BRAIN.regimeOf(p.feat || {});
  BRAIN.learnOutcome({ coin: p.ko, regime, feat: p.feat, dir: p.side, pnl: ret });
  if (why === "손절" || ret < -0.015) BRAIN.learnLoss({ coin: p.ko, regime, feat: p.feat, dir: p.side, roe: ret * 100 });
  feed(`${p.ko} 청산 @ ${fmt(price)} · ${ret >= 0 ? "+" : ""}${(ret * 100).toFixed(2)}% (${why}) → 뉴런·뇌 학습 반영`);
  delete S.pos[sym];
}
// ── 모델 트레이더: 연결된 AI 모델 각각이 직접 데모 포지션을 운용한다 ──
function model(name) { return S.models[name] || (S.models[name] = { prov: "", pnl: 0, ok: 0, n: 0, w: 1, fills: 0, wins: 0, pos: {}, lessons: [], losers: [] }); }
// 보유 포지션 마크 + 하드 손절/익절 (모델 질의 사이에도 포지션이 스스로 정리됨)
function markModels(sym, price) {
  for (const name in S.models) { const M = S.models[name], p = M.pos[sym]; if (!p) continue;
    p.roe = +((price - p.entry) / p.entry * p.side * 100).toFixed(2); p.price = price;
    if (p.roe < -2 || p.roe > 3 || Date.now() - p.t > MAXHOLD) closeModelPos(name, sym, price, p.roe < -2 ? "손절" : p.roe > 3 ? "익절" : "시간청산"); }
}
function closeModelPos(name, sym, price, why) {
  const M = model(name), p = M.pos[sym]; if (!p) return;
  const ret = (price - p.entry) / p.entry * p.side - FEE, pnl = p.size * ret;
  M.pnl += pnl; M.fills++; if (pnl > 0) M.wins++; M.n++; if (ret > 0) M.ok++;
  M.w = cl(M.w + LR * (ret > 0 ? 1 : -1), 0.05, 3);
  const regime = BRAIN.regimeOf(p.feat || {});
  BRAIN.reinforce(p.ko, regime, ret > 0);                                   // 이 상황의 기억 강화/약화
  BRAIN.learnOutcome({ coin: p.ko, regime, feat: p.feat, dir: p.side, pnl: ret });   // 🧠 뇌 지능 학습
  if (ret > 0.02) BRAIN.learn({ type: "패턴", coin: p.ko, regime, text: `${regime}에서 ${p.side > 0 ? "롱" : "숏"} +${(ret * 100).toFixed(1)}% (${strongFeat(p.feat)})`, model: shortMd(name) });   // 큰 이익 = 패턴 기억
  if (ret < 0) {
    M.losers.unshift({ ko: p.ko, side: p.side, roe: +(ret * 100).toFixed(1), feat: p.feat }); M.losers = M.losers.slice(0, 5);
    if (why === "손절" || ret < -0.012) {   // 🛑 손절: 뇌 함정 기록 + 모델에게 '다시는 이 자리서 진입 말라' 교훈 주입
      BRAIN.learnLoss({ coin: p.ko, regime, feat: p.feat, dir: p.side, roe: ret * 100 });
      const lesson = `${regime}에서 ${p.side > 0 ? "롱" : "숏"} 손절(${(ret * 100).toFixed(1)}%): ${strongFeat(p.feat)}일 땐 진입 금지`;
      M.lessons = [...new Set([lesson, ...M.lessons])].slice(0, 6);
    }
  }
  S.pnl += pnl; S.fills++; if (pnl > 0) S.wins++; bumpPeak();
  S.trades.unshift({ model: name, ko: p.ko, side: p.side, roe: +(ret * 100).toFixed(2), pnl: +pnl.toFixed(2), why, t: Date.now() });
  if (S.trades.length > 80) S.trades.pop();
  feed(`[${shortMd(name)}] ${p.ko} 청산 ${ret >= 0 ? "+" : ""}${(ret * 100).toFixed(2)}% (${why})`);
  delete M.pos[sym];
}
// 모델 응답에서 방향·확신 추출 — JSON 우선, 안 되면 키워드(롱/숏/관망)로 폴백 (파싱 실패로 거래 안 되는 걸 방지)
function parseDecision(raw) {
  let dir = null, conf = null;
  const jm = raw.match(/"?dir"?\s*[:=]\s*(-?[01])/); if (jm) dir = +jm[1];
  const cm2 = raw.match(/"?conf(?:idence)?"?\s*[:=]\s*(\d+)/i); if (cm2) conf = Math.min(100, +cm2[1]);
  if (dir === null) {
    const t = raw.toLowerCase();
    if (/(숏|매도|하락|short|sell|bear|down)/.test(t)) dir = -1;
    else if (/(롱|매수|상승|long|buy|bull|\bup\b)/.test(t)) dir = 1;
    else if (/(관망|보류|중립|hold|flat|neutral|wait)/.test(t)) dir = 0;
  }
  return { dir, conf: conf ?? 60 };
}
// 모델 한 명이 코인 하나를 직접 판단 → 포지션 갱신
let mRot = 0, mBackoff = 0, mFails = 0;
export async function modelStep() {
  load(); const cm = connectedModels(); if (!cm.length) return;
  if (Date.now() < mBackoff) return;   // 직전에 전원 실패(한도)면 잠시 쉬었다가 재개 — 429 폭주 방지
  const tgt = cm[mRot % cm.length], [ko, sym] = COINS[((mRot++ / cm.length) | 0) % COINS.length];
  const feat = S.feat[sym], price = S.dec[sym]?.price; if (!feat || !price) return;
  S.scan = { model: shortMd(tgt.model), ko, sym, regime: BRAIN.regimeOf(feat), t: Date.now() };   // 지금 스캔 중: 어느 모델이 어느 코인을
  const tM = model(tgt.model);
  const regime = BRAIN.regimeOf(feat), mem = BRAIN.recallText(ko, regime, 3);
  const les = tM.lessons.length ? `\n내가 복기로 배운 교훈(꼭 지켜라): ${tM.lessons.join(" / ")}` : "";
  const brainLine = mem ? `\n자체 뇌의 집단 기억(${regime} 국면): ${mem}` : "";
  // 🧠 뇌의 지능(학습된 예측) + 정제 규칙 + 손절함정 경고를 모델에게 준다
  const bp = BRAIN.predict(feat, regime), ref = BRAIN.refineForProfit(ko, regime);
  const riskL = BRAIN.trapRisk(feat, regime, 1), riskS = BRAIN.trapRisk(feat, regime, -1);
  const iqLine = `\n${ref.text}` + (bp.dir ? `\n뇌 예측: ${bp.dir > 0 ? "롱" : "숏"} 우세(신뢰 ${Math.round(bp.trust * 100)}%)` : "");
  const trapLine = (riskL >= 0.7 || riskS >= 0.7) ? `\n⚠ 손절 위험: ${riskL >= 0.7 ? `롱 ${Math.round(riskL * 100)}%` : ""}${riskS >= 0.7 ? ` 숏 ${Math.round(riskS * 100)}%` : ""} 과거 손절과 유사 → 그 방향 피하라` : "";
  let raw = "", route;
  try {
    // fallback:true → 핀한 모델이 한도/쿨다운/오류면 '응답하는 다른 모델'로 넘어가 반드시 한 번은 거래가 일어난다. 결과는 '실제 응답한 모델'에 귀속.
    const brief = S.brief?.[sym] || { text: "", trend: regime };
    route = await brainStream({ messages: [
      { role: "system", content: `너는 ${ko} 코인 선물 1분봉 단타 트레이더다. 추세와 진입 타점을 보고 지금 롱/숏/관망을 정한다.
[진입 규칙 — 꼭 지켜라]
1) 추세 방향으로만 진입: 상승추세면 롱 위주, 하락추세면 숏 위주, 횡보면 웬만하면 관망(0).
2) 타점: 상승추세라도 RSI>70(과매수)면 롱 금지 → 눌림(RSI 45~60) 기다려 롱. 하락추세라도 RSI<30(과매도)면 숏 금지 → 반등에 숏.
3) 신호가 약하거나 애매하거나 변동성이 크면 관망(0). 추격매수/추격매도 금지.
4) 손절 -2%, 익절 +3%는 자동 적용된다. 승률 높은 자리만 골라라.
반드시 JSON 한 줄만: {"dir":1,"conf":70} — dir 1=롱 -1=숏 0=관망, conf 0~100(자신있을 때만 높게). 설명 금지.${brainLine}${les}${iqLine}${trapLine}` },
      { role: "user", content: `${ko} 시장: ${brief.text}. 거래흐름 ${(feat["거래흐름"] || 0) >= 0 ? "매수우위" : "매도우위"}, 현재가 ${price}.\n규칙대로 판단해 JSON만:` }],
      role: "fast", target: tgt, fallback: true, json: true, maxTokens: 160, temperature: 0.2, noThink: true, onContent: d => raw += d, onThink: () => {} });
  } catch (e) {
    mFails++; const rl = e?.status === 429 || /한도/.test(e?.message || "");
    if (rl) { mBackoff = Date.now() + Math.min(90e3, 15e3 * Math.min(6, mFails)); feed(`무료 AI 한도 — ${Math.round((mBackoff - Date.now()) / 1000)}초 쉬었다 재개 (연결된 모든 회사가 사용량 초과)`); }
    else feed(`[${shortMd(tgt.model)}] ${e?.message || "응답 실패"} — 다음 차례`);
    save(); return;
  }
  mFails = 0;
  const name = route?.model || tgt.model, M = model(name); M.prov = route?.id || tgt.id; M.calls = (M.calls || 0) + 1;
  let { dir, conf } = parseDecision(raw);
  if (dir === null) { feed(`[${shortMd(name)}] ${ko} 판단 형식 못 읽음`); save(); return; }
  const p = M.pos[sym];
  if (p && dir !== 0 && dir !== p.side) closeModelPos(name, sym, price, "반대신호");
  // 🚫 타점 가드: 추세 역행 + 과매수/과매도 추격 진입을 거른다 (약한 모델이 방향을 잘못 잡아도 코드가 보호)
  const bf = S.brief?.[sym];
  if (!p && bf && dir !== 0) {
    const against = (dir === 1 && bf.trend === "하락추세" && (bf.mom5 ?? 0) <= 0) || (dir === -1 && bf.trend === "상승추세" && (bf.mom5 ?? 0) >= 0);
    const chase = (dir === 1 && bf.rsi >= 76) || (dir === -1 && bf.rsi <= 24);
    if (against) { feed(`[${shortMd(name)}] ${ko} ${dir > 0 ? "롱" : "숏"} 보류 — ${bf.trend} 역행 금지`); dir = 0; }
    else if (chase) { feed(`[${shortMd(name)}] ${ko} ${dir > 0 ? "롱" : "숏"} 보류 — RSI ${bf.rsi} 추격 금지`); dir = 0; }
  }
  const risk = dir !== 0 ? BRAIN.trapRisk(feat, regime, dir) : 0;
  if (!M.pos[sym] && dir !== 0 && risk >= 0.8) feed(`[${shortMd(name)}] ${ko} ${dir > 0 ? "롱" : "숏"} 보류 — 과거 손절과 ${Math.round(risk * 100)}% 유사(뇌 회피)`);   // 🛑 반복 손절 차단
  else if (!M.pos[sym] && dir !== 0) { M.pos[sym] = { ko, side: dir, entry: price, price, size: posSize(), roe: 0, t: Date.now(), feat: { ...feat } }; feed(`[${shortMd(name)}] ${ko} ${dir > 0 ? "▲롱" : "▼숏"} 진입 @ ${fmt(price)} (${conf}%)`); }
  else if (dir === 0 && !p) feed(`[${shortMd(name)}] ${ko} 관망`);
  save();
}
// 복기: 손실 많은 모델이 자기 손실 거래를 되돌아보고 교훈 한 줄을 스스로 뽑아 기억 → 다음 판단에 주입(성능 향상)
export async function reflect() {
  load(); const cm = connectedModels(); if (!cm.length) return;
  const withLoss = cm.filter(t => (model(t.model).losers || []).length >= 2).sort((a, b) => model(a.model).pnl - model(b.model).pnl);
  const tgt = withLoss[0]; if (!tgt) return; const M = model(tgt.model);
  let raw = "";
  try {
    await brainStream({ messages: [
      { role: "system", content: "너는 코인 트레이더다. 아래 네 최근 손실 거래를 복기해, 다음에 안 틀리게 할 교훈을 한국어 한 문장(35자 이내)으로만 써라. 교훈 문장만." },
      { role: "user", content: M.losers.map(l => `${l.ko} ${l.side > 0 ? "롱" : "숏"} ${l.roe}% · 신호 ${Object.entries(l.feat || {}).slice(0, 3).map(([k, v]) => k + (+v).toFixed(1)).join(",")}`).join("\n") }],
      role: "fast", target: tgt, fallback: true, maxTokens: 70, temperature: 0.5, noThink: true, onContent: d => raw += d, onThink: () => {} });
  } catch (e) { return; }
  const lesson = raw.replace(/["\n]/g, " ").replace(/^교훈[:\s]*/,"").trim().slice(0, 40);
  if (lesson.length > 4) {
    const l0 = M.losers[0] || {}, regime = BRAIN.regimeOf(l0.feat || {});
    BRAIN.learn({ type: "교훈", coin: l0.ko || "", regime, text: lesson, model: shortMd(tgt.model) });   // 집단 뇌에 공유 → 모든 모델이 다음부터 참고
    M.lessons.unshift(lesson); M.lessons = [...new Set(M.lessons)].slice(0, 4); M.losers = [];
    feed(`[${shortMd(tgt.model)}] 복기 → 교훈 "${lesson}" (자체 뇌에 저장)`); save();
  }
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
아래 JSON 스키마로만 출력(설명·코드블록 금지):\n{"name":"이름","indicators":[{"id":"r","type":"tv_rsi","length":14},{"id":"vm","type":"custom","expr":"수식"}],"long_entry":{"conditions":[{"left":"r","op":"<","right":40}]},"long_exit":{"conditions":[{"left":"r","op":">","right":65}]},"short_entry":{"conditions":[...]},"risk":{"leverage":2,"stop_loss_pct":${style.cls === "단타" ? 1 : 3},"take_profit_pct":${style.cls === "단타" ? 2 : 6}}}\n쓸 수 있는 보조지표(차트 터미널 ${Q.TV_TYPES ? Q.TV_TYPES.length : 146}종 전부 + custom 수식): ${catalog}\ncustom expr 피연산자: close open high low volume · 지표 id · id.p1~p4.${M.lessons.length ? " 내 교훈: " + M.lessons.join(" / ") : ""}${BRAIN.recallText(ko, "", 3) ? " 뇌 패턴: " + BRAIN.recallText(ko, "", 3) : ""} 뇌가 이득난 규칙: ${BRAIN.refineForProfit(ko, "").text}` },
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
  if (wf.pass) {
    try { const P = await import("../nuri-ai/paper.js");
      await P.addStrategy({ spec: norm, market: sym, exchange: "binancef", tf: style.tf, author: `뉴럴(${shortMd(tgt.model)})`,
        wf: { is: {}, oos: { ret: +(wf.oos?.return_pct ?? 0), pf: wf.oos?.profit_factor ?? null, n: wf.oos?.n_trades ?? 0 } }, cls: "crypto", mname });
      S.designs[0].handed = true;
    } catch (e) {}
    BRAIN.learn({ type: "전략", coin: ko, regime: "", text: `[${style.cls}] ${norm.name} 검증통과(${(wf.oos?.return_pct ?? 0).toFixed(0)}%) — ${(norm.indicators || []).map(i => i.type).slice(0, 4).join("+")}`, model: shortMd(tgt.model) });
  }
  save();
}

function shortMd(m) { return String(m).split("/").pop().replace(/-instruct|-chat|-\d{6,}/gi, "").slice(0, 16); }
function strongFeat(feat = {}) { return Object.entries(feat).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1])).slice(0, 2).map(([k, v]) => k + (v >= 0 ? "+" : "") + (+v).toFixed(1)).join(",") || "—"; }
// 뇌 상태·그래프·자체학습 공개 (UI용)
export const brainState = () => BRAIN.brainState();
export const brainGraph = () => BRAIN.graph(80);
export const brainThink = () => BRAIN.consolidate();   // 뇌 자체 학습(망각·규칙 합성)
export const brainCanvas = () => BRAIN.toCanvas(120);  // JSON Canvas(.canvas) 내보내기 — Obsidian에서 열기
export const brainIQ = () => BRAIN.iqScore();           // 뇌 지능 점수(자가학습 정확도)
export const brainRefine = (coin, regime) => BRAIN.refineForProfit(coin, regime);
export const brainIngest = (note) => BRAIN.ingest(note);   // 에이전트 팀/외부(.canvas)가 결과를 뇌에 넣음
export function resetBrain() { BRAIN.reset(); }

export function state() {
  load();
  const wr = S.fills ? Math.round(S.wins / S.fills * 100) : 0;
  const neurons = NEURONS.map(k => ({ name: k, w: +S.w[k].toFixed(2), hit: S.hit[k].n ? Math.round(S.hit[k].ok / S.hit[k].n * 100) : null, n: S.hit[k].n }))
    .sort((a, b) => b.w - a.w);
  // 트레이더 = 자체 신호(뉴런 합의) + 연결된 AI 모델 각각. PnL 순 리더보드.
  const traders = [{ name: "자체 신호(뉴런)", prov: "self", pnl: +selfPnl().toFixed(2), hit: null, fills: 0, lessons: 0, pos: Object.values(S.pos).length }];
  for (const [name, m] of Object.entries(S.models))
    traders.push({ name: shortMd(name), full: name, prov: m.prov, pnl: +m.pnl.toFixed(2), hit: m.n ? Math.round(m.ok / m.n * 100) : null, w: +m.w.toFixed(2), fills: m.fills, wins: m.wins, lessons: (m.lessons || []).length, lessonList: m.lessons || [], pos: Object.values(m.pos) });
  traders.sort((a, b) => b.pnl - a.pnl);
  const eq = equity(), peak = Math.max(S.peak || BANKROLL, eq), dd = peak > 0 ? +((peak - eq) / peak * 100).toFixed(1) : 0;
  return { pnl: +S.pnl.toFixed(2), bankroll: BANKROLL, equity: eq, peak: +peak.toFixed(2), drawdown: dd, riskMode: riskMode(),
    fills: S.fills, winRate: wr, epoch: S.epoch, since: S.t0, nModels: connectedModels().length,
    neurons, traders, designs: (S.designs || []).slice(0, 10), nDesigns: (S.designs || []).length, handed: (S.designs || []).filter(d => d.handed).length,
    brain: BRAIN.brainState(), scan: S.scan || null,
    pos: Object.values(S.pos), dec: S.dec, feat: S.feat, trades: S.trades.slice(0, 22), feed: S.feed.slice(0, 24) };
}
// 자체 신호 트레이더의 PnL = 전체 - 모델들 합 (모델 손익은 모델 트레이더로 분리 표시)
function selfPnl() { let m = 0; for (const n in S.models) m += S.models[n].pnl; return S.pnl - m; }
function fmt(v) { return v >= 1000 ? Math.round(v).toLocaleString() : v >= 1 ? v.toFixed(2) : v.toPrecision(4); }

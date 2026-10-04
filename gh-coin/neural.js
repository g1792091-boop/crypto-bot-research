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
  // 로컬 전용 모드: 설치된 Ollama 모델만 트레이더로 (작고 빠른 것 우선 최대 6개)
  const sized = [...olCache].sort((a, b) => olSize(a) - olSize(b)).slice(0, 6).map(m => ({ id: "ollama", model: m }));
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
function olSize(name) { const m = String(name).match(/(\d+(?:\.\d+)?)\s*b/i); return m ? +m[1] : 7; }   // 모델명에서 파라미터 수(b) 추정, 없으면 7b로 간주

export const COINS = [["BTC", "BTCUSDT"], ["ETH", "ETHUSDT"], ["SOL", "SOLUSDT"], ["XRP", "XRPUSDT"], ["DOGE", "DOGEUSDT"], ["BNB", "BNBUSDT"]];
const KEY = "coin:neural";
const START = 10000;          // 코인별 가상 증거금
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
  const c = cs.map(b => b.c), n = c.length; if (n < 55) return { text: "데이터 부족", rsi: 50, trend: "횡보" };
  const ema50 = (() => { const p = 50, k = 2 / (p + 1); let e = c[n - 3 * p] ?? c[0]; for (let i = Math.max(1, n - 3 * p + 1); i < n; i++) e = c[i] * k + e * (1 - k); return e; })();
  const rsiV = (() => { let g = 0, l = 0; for (let i = n - 14; i < n; i++) { const d = c[i] - c[i - 1]; if (d > 0) g += d; else l -= d; } const rs = l === 0 ? 99 : g / l; return 100 - 100 / (1 + rs); })();
  const last = c[n - 1], emaPct = (last / ema50 - 1) * 100, mom5 = (last / c[n - 6] - 1) * 100, mom20 = (last / c[n - 21] - 1) * 100;
  const trend = emaPct > 0.3 ? "상승추세" : emaPct < -0.3 ? "하락추세" : "횡보";
  const ob = rsiV >= 72 ? "과매수" : rsiV <= 28 ? "과매도" : rsiV >= 56 ? "약강세" : rsiV <= 44 ? "약약세" : "중립";
  return { rsi: Math.round(rsiV), trend, ob, emaPct: +emaPct.toFixed(2), mom5: +mom5.toFixed(2),
    text: `추세 ${trend}(EMA50 대비 ${emaPct >= 0 ? "+" : ""}${emaPct.toFixed(2)}%) · RSI ${Math.round(rsiV)}(${ob}) · 모멘텀 5분 ${mom5 >= 0 ? "+" : ""}${mom5.toFixed(2)}%·20분 ${mom20 >= 0 ? "+" : ""}${mom20.toFixed(2)}%` };
}

// ── 상태 ──
function blank() {
  return { pnl: 0, cash: START * COINS.length, fills: 0, wins: 0,
    w: Object.fromEntries(NEURONS.map(k => [k, 1])),              // 뉴런 가중치(학습으로 변함)
    hit: Object.fromEntries(NEURONS.map(k => [k, { ok: 0, n: 0 }])), // 뉴런별 적중
    models: {},                                                   // 연결된 LLM 모델 기여(이름→{ok,n,w})
    pos: {}, feat: {}, dec: {}, trades: [], feed: [], epoch: 0, t0: Date.now() };
}
let S = null;
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
    // 무포지션 + 신호 있으면 진입 — 단, 과거 손절과 닮은 자리면 뇌가 회피(반복 손절 줄이기)
    if (!S.pos[sym] && d.dir !== 0 && d.conf >= 25) {
      const risk = BRAIN.trapRisk(feat, regime, d.dir);
      if (risk >= 0.75) feed(`${ko} ${d.dir > 0 ? "롱" : "숏"} 보류 — 과거 손절 패턴과 ${Math.round(risk * 100)}% 유사 (뇌 회피)`);
      else openPos(sym, ko, d.dir, price, feat);
    }
  }
  S.epoch++;
  save();
  return state();
}
function openPos(sym, ko, side, price, feat) {
  S.pos[sym] = { ko, side, entry: price, price, size: START * 0.2, roe: 0, t: Date.now(), feat: { ...feat } };
  feed(`${ko} ${side > 0 ? "▲ 롱" : "▼ 숏"} 진입 @ ${fmt(price)} (확신 ${S.dec[sym]?.conf}%)`);
}
function closePos(sym, price, why) {
  const p = S.pos[sym]; if (!p) return;
  const ret = (price - p.entry) / p.entry * p.side - FEE;      // 수수료 반영
  const pnl = p.size * ret;
  S.pnl += pnl; S.fills++; if (pnl > 0) S.wins++;
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
  S.pnl += pnl; S.fills++; if (pnl > 0) S.wins++;
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
      role: "fast", target: tgt, fallback: true, maxTokens: 160, temperature: 0.2, noThink: true, onContent: d => raw += d, onThink: () => {} });
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
  // 🚫 최악의 타점 차단: 극단 과매수에서 추격 롱, 극단 과매도에서 추격 숏 (모델이 타점을 몰라도 코드가 거른다)
  const bf = S.brief?.[sym];
  if (!p && bf && dir === 1 && bf.rsi >= 78) { feed(`[${shortMd(name)}] ${ko} 롱 보류 — RSI ${bf.rsi} 과매수 추격 금지`); dir = 0; }
  else if (!p && bf && dir === -1 && bf.rsi <= 22) { feed(`[${shortMd(name)}] ${ko} 숏 보류 — RSI ${bf.rsi} 과매도 추격 금지`); dir = 0; }
  const risk = dir !== 0 ? BRAIN.trapRisk(feat, regime, dir) : 0;
  if (!M.pos[sym] && dir !== 0 && risk >= 0.8) feed(`[${shortMd(name)}] ${ko} ${dir > 0 ? "롱" : "숏"} 보류 — 과거 손절과 ${Math.round(risk * 100)}% 유사(뇌 회피)`);   // 🛑 반복 손절 차단
  else if (!M.pos[sym] && dir !== 0) { M.pos[sym] = { ko, side: dir, entry: price, price, size: START * 0.2, roe: 0, t: Date.now(), feat: { ...feat } }; feed(`[${shortMd(name)}] ${ko} ${dir > 0 ? "▲롱" : "▼숏"} 진입 @ ${fmt(price)} (${conf}%)`); }
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
  const catalog = "tv_rsi(length) tv_macd tv_bb(length) tv_ema(length) tv_sma(length) tv_adx(length) tv_stoch tv_supertrend tv_cci(length) tv_atr(length) tv_donchian(length) ema sma rsi · 그리고 custom(expr): 수식으로 나만의 지표. 피연산자는 close/open/high/low/volume·지표 id·id.p1~p4";
  let raw = "";
  try {
    await brainStream({ messages: [
      { role: "system", content: `너는 코인 선물 퀀트다. 아래 보조지표들을 조합해 BTCUSDT 1시간봉 매매법 하나를 설계한다. 반드시 custom 수식 지표를 1개 이상 포함(예: {"id":"vm","type":"custom","expr":"rsi*0.5+close/sma-1"}). 아래 JSON 스키마로만 출력(설명·코드블록 금지):\n{"name":"이름","indicators":[{"id":"r","type":"tv_rsi","length":14},{"id":"vm","type":"custom","expr":"수식"}],"long_entry":{"conditions":[{"left":"r","op":"<","right":35}]},"long_exit":{"conditions":[{"left":"r","op":">","right":65}]},"risk":{"leverage":2,"stop_loss_pct":4,"take_profit_pct":8}}\n쓸 수 있는 지표: ${catalog}.${M.lessons.length ? " 내 교훈: " + M.lessons.join(" / ") : ""}${BRAIN.recallText("BTC", "", 4) ? " 자체 뇌 패턴: " + BRAIN.recallText("BTC", "", 4) : ""} 뇌가 이득났던 규칙(반영해 설계): ${BRAIN.refineForProfit("BTC", "").text}` },
      { role: "user", content: "매매법 JSON 하나만 출력:" }],
      role: "code", target: tgt, fallback: true, maxTokens: 700, temperature: 0.6, noThink: true, onContent: d => raw += d, onThink: () => {} });
  } catch (e) { feed(`[${shortMd(tgt.model)}] 매매법 설계 응답 실패`); return; }
  let spec; try { spec = JSON.parse((raw.match(/\{[\s\S]*\}/) || [])[0]); } catch (e) { feed(`[${shortMd(tgt.model)}] 매매법 JSON 형식 오류`); return; }
  if (!spec || !spec.indicators) return;
  let norm; try { norm = Q.normalizeSpec({ ...spec, symbol: "BTCUSDT", interval: "1h" }); }
  catch (e) { feed(`[${shortMd(tgt.model)}] 매매법 규격 미달: ${String(e.message || e).slice(0, 36)}`); return; }
  let cs; try { cs = (await candlesFor({ market: "BTCUSDT", exchange: "binancef", timeframe: "60" }, 1500)).cs; } catch (e) { return; }
  const bt = Q.backtest(norm, cs), wf = Q.walkForward(norm, cs);
  M.designs = (M.designs || 0) + 1;
  S.designs = S.designs || []; S.designs.unshift({ model: shortMd(tgt.model), name: norm.name, ret: +(bt.stats.return_pct ?? 0).toFixed(1), pf: bt.stats.profit_factor ?? null, pass: wf.pass, handed: false, t: Date.now() });
  S.designs = S.designs.slice(0, 20);
  feed(`[${shortMd(tgt.model)}] 매매법 설계 "${norm.name}" → 백테스트 ${(bt.stats.return_pct ?? 0).toFixed(1)}% · ${wf.pass ? "✅ 검증통과 → 사무실 인계" : "불통과"}`);
  if (wf.pass) {
    try { const P = await import("../nuri-ai/paper.js");
      await P.addStrategy({ spec: norm, market: "BTCUSDT", exchange: "binancef", tf: "60", author: `뉴럴(${shortMd(tgt.model)})`,
        wf: { is: {}, oos: { ret: +(wf.oos?.return_pct ?? 0), pf: wf.oos?.profit_factor ?? null, n: wf.oos?.n_trades ?? 0 } }, cls: "crypto", mname: "비트코인 선물" });
      S.designs[0].handed = true;
    } catch (e) {}
    BRAIN.learn({ type: "전략", coin: "BTC", regime: "", text: `${norm.name} 검증통과(${(wf.oos?.return_pct ?? 0).toFixed(0)}%) — ${(norm.indicators || []).map(i => i.type).slice(0, 4).join("+")}`, model: shortMd(tgt.model) });
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
  return { pnl: +S.pnl.toFixed(2), fills: S.fills, winRate: wr, epoch: S.epoch, since: S.t0, nModels: connectedModels().length,
    neurons, traders, designs: (S.designs || []).slice(0, 10), nDesigns: (S.designs || []).length, handed: (S.designs || []).filter(d => d.handed).length,
    brain: BRAIN.brainState(), scan: S.scan || null,
    pos: Object.values(S.pos), dec: S.dec, feat: S.feat, trades: S.trades.slice(0, 22), feed: S.feed.slice(0, 24) };
}
// 자체 신호 트레이더의 PnL = 전체 - 모델들 합 (모델 손익은 모델 트레이더로 분리 표시)
function selfPnl() { let m = 0; for (const n in S.models) m += S.models[n].pnl; return S.pnl - m; }
function fmt(v) { return v >= 1000 ? Math.round(v).toLocaleString() : v >= 1 ? v.toFixed(2) : v.toPrecision(4); }

// 🧠 뉴럴 데스크 — 연결된 AI 모델(+피처 뉴런)이 "직접" 데모 매매하고, 결과로 채점받아 가중치를 스스로 올리고 내린다.
// 에이전트 '팀 회의'가 아니라, 신호 뉴런들의 온라인 학습(퍼셉트론식)으로 돌아가는 자율 데모 트레이더.
// 전부 가상자금(데모)만 — 실주문·실자금·실지갑 없음.
import { candlesFor } from "../nuri-ai/agent.js";
import { brainStream, settings, PROVIDERS, modelKind } from "../nuri-ai/engine.js";

// 연결된(키가 있는) 회사의 무료 AI 모델 목록 — 각 모델이 트레이더가 된다. 비용상 최대 maxN
export function connectedModels(maxN = 8) {
  const out = [];
  for (const id of Object.keys(PROVIDERS || {})) {
    if (!settings?.keys?.[id]) continue;
    const ms = settings.provModels?.[id]?.length ? settings.provModels[id] : (PROVIDERS[id].defaults || []);
    for (const m of ms) { if (["chat", "code", "reason"].includes(modelKind(m))) out.push({ id, model: m }); }
  }
  return out.slice(0, maxN);
}

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
  for (const [ko, sym] of COINS) {
    let cs; try { cs = (await candlesFor({ market: sym, exchange: "binancef", timeframe: "1" }, 300)).cs; } catch (e) { continue; }
    if (!cs || cs.length < 60) continue;
    const price = cs.at(-1).c, feat = featuresOf(cs), d = decide(feat);
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
    // 무포지션 + 신호 있으면 진입
    if (!S.pos[sym] && d.dir !== 0 && d.conf >= 25) openPos(sym, ko, d.dir, price, feat);
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
  feed(`${p.ko} 청산 @ ${fmt(price)} · ${ret >= 0 ? "+" : ""}${(ret * 100).toFixed(2)}% (${why}) → 학습 반영`);
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
  if (ret < 0) { M.losers.unshift({ ko: p.ko, side: p.side, roe: +(ret * 100).toFixed(1), feat: p.feat }); M.losers = M.losers.slice(0, 5); }
  S.pnl += pnl; S.fills++; if (pnl > 0) S.wins++;
  S.trades.unshift({ model: name, ko: p.ko, side: p.side, roe: +(ret * 100).toFixed(2), pnl: +pnl.toFixed(2), why, t: Date.now() });
  if (S.trades.length > 80) S.trades.pop();
  feed(`[${shortMd(name)}] ${p.ko} 청산 ${ret >= 0 ? "+" : ""}${(ret * 100).toFixed(2)}% (${why})`);
  delete M.pos[sym];
}
// 모델 한 명이 코인 하나를 직접 판단 → 포지션 갱신 (호출측에서 throttle; 비용 분산)
let mRot = 0;
export async function modelStep() {
  load(); const cm = connectedModels(); if (!cm.length) return;
  const tgt = cm[mRot % cm.length], [ko, sym] = COINS[((mRot++ / cm.length) | 0) % COINS.length];
  const feat = S.feat[sym], price = S.dec[sym]?.price; if (!feat || !price) return;
  const M = model(tgt.model); M.prov = tgt.id;
  const les = M.lessons.length ? `\n내가 복기로 배운 교훈(지켜라): ${M.lessons.join(" / ")}` : "";
  let raw = "";
  try {
    await brainStream({ messages: [
      { role: "system", content: `너는 ${ko} 코인 선물 데모 트레이더다. 신호를 보고 방향을 정한다. JSON 한 줄만: {"dir":1|0|-1,"conf":0~100} (1=롱 -1=숏 0=관망).${les}` },
      { role: "user", content: `${ko} 지금 신호(−1~+1): ${Object.entries(feat).map(([k, v]) => k + " " + (+v).toFixed(2)).join(", ")} · 현재가 ${price}` }],
      role: "fast", target: tgt, fallback: false, maxTokens: 50, temperature: 0.4, noThink: true, onContent: d => raw += d });
  } catch (e) { return; }
  const md = raw.match(/"?dir"?\s*[:=]\s*(-?[01])/); if (!md) return;
  const dir = +md[1], cf = raw.match(/"?conf"?\s*[:=]\s*(\d+)/), conf = cf ? Math.min(100, +cf[1]) : 50;
  const p = M.pos[sym];
  if (p && dir !== 0 && dir !== p.side) closeModelPos(tgt.model, sym, price, "반대신호");
  if (!M.pos[sym] && dir !== 0 && conf >= 25) { M.pos[sym] = { ko, side: dir, entry: price, price, size: START * 0.2, roe: 0, t: Date.now(), feat: { ...feat } }; feed(`[${shortMd(tgt.model)}] ${ko} ${dir > 0 ? "▲롱" : "▼숏"} 진입 @ ${fmt(price)} (${conf}%)`); }
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
      role: "fast", target: tgt, fallback: false, maxTokens: 60, temperature: 0.5, noThink: true, onContent: d => raw += d });
  } catch (e) { return; }
  const lesson = raw.replace(/["\n]/g, " ").replace(/^교훈[:\s]*/,"").trim().slice(0, 40);
  if (lesson.length > 4) { M.lessons.unshift(lesson); M.lessons = [...new Set(M.lessons)].slice(0, 4); M.losers = []; feed(`[${shortMd(tgt.model)}] 복기 완료 → 교훈: ${lesson}`); save(); }
}
function shortMd(m) { return String(m).split("/").pop().replace(/-instruct|-chat|-\d{6,}/gi, "").slice(0, 16); }

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
    neurons, traders, pos: Object.values(S.pos), dec: S.dec, feat: S.feat, trades: S.trades.slice(0, 22), feed: S.feed.slice(0, 24) };
}
// 자체 신호 트레이더의 PnL = 전체 - 모델들 합 (모델 손익은 모델 트레이더로 분리 표시)
function selfPnl() { let m = 0; for (const n in S.models) m += S.models[n].pnl; return S.pnl - m; }
function fmt(v) { return v >= 1000 ? Math.round(v).toLocaleString() : v >= 1 ? v.toFixed(2) : v.toPrecision(4); }

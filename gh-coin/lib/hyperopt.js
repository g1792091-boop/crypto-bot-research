// 전략 최적화팀 엔진 — freqtrade 하이퍼옵트(손실함수·ROI/손절/추적손절 탐색 공간)와 backtrader 성과 분석기(SQN·VWR·Returns·DrawDown·TradeAnalyzer)를
// 우리 백테스터(nuri-ai/quant.js)에 맞게 다시 만든 것. 두 프로젝트 모두 GPL-3.0 이라 코드는 옮기지 않고 공식만 재구현했다.
// 과최적화를 막기 위해: 앞 70%(학습)에서만 찾고 → 뒤 30%(검증) 성적과 기존 관문(walkForward)을 다시 통과해야 채택한다.

/* ================= 손실함수 (작을수록 좋음) ================= */
// trades: quant.js 백테스트 거래 [{pnl, pnlPct, entryT, exitT}] · B: 시작 자금 · days: 기간 일수
const sum = a => a.reduce((s, x) => s + x, 0);
const pstd = a => { if (!a.length) return 0; const m = sum(a) / a.length; return Math.sqrt(sum(a.map(x => (x - m) ** 2)) / a.length); };
function ddOf(trades, B){ let eq = B, peak = B, absDD = 0, relDD = 0; for (const t of trades){ eq += t.pnl; peak = Math.max(peak, eq); absDD = Math.max(absDD, peak - eq); relDD = Math.max(relDD, peak > 0 ? (peak - eq) / peak : 1); } return {absDD, relDD}; }
function daily(trades){ const m = {}; for (const t of trades){ const d = Math.floor(t.exitT / 864e5); m[d] = (m[d] || 0) + t.pnlPct / 100 - 0.0005; } const ks = Object.keys(m).map(Number); if (!ks.length) return []; const out = []; for (let d = Math.min(...ks); d <= Math.max(...ks); d++) out.push(m[d] || 0); return out; }
export const LOSSES = {
  ShortTradeDur: {ko: "짧은 보유·많은 거래·수익 (freqtrade 기본)", f: (T, B, D) => { const N = T.length, Pr = sum(T.map(t => t.pnlPct / 100)), dur = N ? sum(T.map(t => (t.exitT - t.entryT) / 60000)) / N : 0; return (1 - 0.25 * Math.exp(-((N - 600) ** 2) / 10 ** 5.8)) + Math.max(0, 1 - Pr / 3) + 0.4 * Math.min(dur / 300, 1); }},
  OnlyProfit: {ko: "수익만", f: T => -sum(T.map(t => t.pnl))},
  Sharpe: {ko: "샤프(거래 기준)", f: (T, B, D) => { const r = T.map(t => t.pnl / B), s = pstd(r); return s ? -(sum(r) / D) / s * Math.sqrt(365) : 100; }},
  SharpeDaily: {ko: "샤프(일 기준)", f: T => { const d = daily(T), s = pstd(d); return s ? -(sum(d) / d.length) / s * Math.sqrt(365) : 20; }},
  Sortino: {ko: "소르티노(손실 거래만 변동성)", f: (T, B, D) => { const r = T.map(t => t.pnl / B), s = pstd(r.filter(x => x < 0)); return s ? -(sum(r) / D) / s * Math.sqrt(365) : (sum(r) > 0 ? -100 : 100); }},
  SortinoDaily: {ko: "소르티노(일 기준)", f: T => { const d = daily(T), sd = Math.sqrt(sum(d.map(x => Math.min(x, 0) ** 2)) / (d.length || 1)); return sd ? -(sum(d) / d.length) / sd * Math.sqrt(365) : 20; }},
  Calmar: {ko: "칼마(수익 ÷ 낙폭)", f: (T, B, D) => { const {relDD} = ddOf(T, B), mean = sum(T.map(t => t.pnl)) / B / D * 100; return relDD ? -(mean / relDD * Math.sqrt(365)) : 0; }},
  MaxDrawDown: {ko: "수익 ÷ 최대 낙폭", f: (T, B) => { const P = sum(T.map(t => t.pnl)), {absDD} = ddOf(T, B); return absDD ? -P / absDD : -P; }},
  ProfitDrawDown: {ko: "수익 − 낙폭 벌점", f: (T, B) => { const P = sum(T.map(t => t.pnl)), {relDD} = ddOf(T, B); return -(P - relDD * P * (1 - 0.075)); }},
  MultiMetric: {ko: "종합(수익·손익비·기대값·승률·거래수)", f: (T, B) => { const N = T.length; if (!N) return 0; const P = sum(T.map(t => t.pnl)), W = T.filter(t => t.pnl > 0), L = T.filter(t => t.pnl <= 0), ws = sum(W.map(t => t.pnl)), ls = sum(L.map(t => t.pnl));
    const PF = ws / (Math.abs(ls) + 1e-6), WR = W.length / N, Er = L.length && W.length ? (1 + (ws / W.length) / Math.abs(ls / L.length)) * WR - 1 : 100, {relDD} = ddOf(T, B), pen = N < 50 ? Math.max(1 - Math.abs(N - 50) / 50, 0.1) : 1;
    return -(P - relDD * P * (1 - 0.055)) * Math.log(PF + 1) * Math.log(Math.min(10, Math.max(Er, -1.9)) + 2) * Math.log(WR + 1.2) * pen; }}
};

/* ================= backtrader 성과 분석기 ================= */
// equity: [{t, v}] (봉마다), trades, perYear: 1년 봉 수
export function analyzers(equity, trades, {perYear = 365 * 24} = {}){
  const V0 = equity[0]?.v, Vn = equity.at(-1)?.v, n = equity.length - 1;
  const out = {};
  if (V0 > 0 && Vn > 0 && n > 0){
    const rtot = Math.log(Vn / V0), ravg = rtot / n;
    out.rtot = rtot; out.rnorm100 = (Math.exp(ravg * perYear) - 1) * 100;      // Returns 분석기: 연환산 수익 %
    // VWR(변동성 가중 수익): 이상적 일정 성장선에서 벗어난 정도로 벌점 — tau 0.2, sdev_max 2.0 (코드 기본값), 의도한 식 V_k/(V_0·e^{ravg·k})−1 사용
    const dev = equity.map((p, k) => p.v / (V0 * Math.exp(ravg * k)) - 1), m = sum(dev) / dev.length, sd = Math.sqrt(sum(dev.map(x => (x - m) ** 2)) / Math.max(1, dev.length - 1));
    out.vwr = out.rnorm100 * (1 - Math.pow(Math.min(sd / 2.0, 1), 0.2));
  }
  // DrawDown: 최대 낙폭 %, 가장 긴 물린 기간(봉)
  let peak = -Infinity, len = 0, maxLen = 0, mdd = 0;
  for (const p of equity){ if (p.v >= peak){ peak = p.v; len = 0; } else { len++; maxLen = Math.max(maxLen, len); mdd = Math.max(mdd, (peak - p.v) / peak * 100); } }
  out.maxdd = mdd; out.maxddLen = maxLen;
  // TradeAnalyzer: 연승·연패, 평균 보유
  let cw = 0, cl = 0, bw = 0, bl = 0;
  for (const t of trades){ if (t.pnl >= 0){ cw++; cl = 0; bw = Math.max(bw, cw); } else { cl++; cw = 0; bl = Math.max(bl, cl); } }   // 본전은 승리로 (backtrader 규칙)
  out.streakWon = bw; out.streakLost = bl;
  out.avgHoldHours = trades.length ? sum(trades.map(t => (t.exitT - t.entryT))) / trades.length / 36e5 : 0;
  const a = trades.map(t => t.pnl), N = a.length, mm = N ? sum(a) / N : 0, ps = pstd(a);
  out.sqn = N > 1 && ps ? Math.sqrt(N) * mm / ps : null;
  out.sqnGrade = out.sqn == null ? "—" : out.sqn < 1.6 ? "나쁨" : out.sqn < 2 ? "보통 이하" : out.sqn < 2.5 ? "보통" : out.sqn < 3 ? "좋음" : out.sqn < 5.1 ? "매우 좋음" : out.sqn < 7 ? "탁월" : "의심(과최적화?)";
  return out;
}

/* ================= 탐색 공간 (freqtrade 규칙) ================= */
let seed = 12345; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
export const setSeed = s => { seed = Math.max(1, s | 0) % 2147483647 || 1; };
const U = (a, b) => a + (b - a) * rnd(), I = (a, b) => Math.round(U(a, b));
// ROI 표: 6개 값 → 4단계 {0: p1+p2+p3, t3: p1+p2, t3+t2: p1, t3+t2+t1: 0} — 봉 길이에 따라 범위가 늘어난다 (값은 증거금 수익 비율)
export function sampleROI(tfMin){
  const ts = tfMin / 5, ps = Math.log(1 + tfMin) / Math.log(6);
  const t1 = I(10 * ts, 120 * ts), t2 = I(10 * ts, 60 * ts), t3 = I(10 * ts, 40 * ts), p1 = U(0.01, 0.04) * ps, p2 = U(0.01, 0.07) * ps, p3 = U(0.01, 0.20) * ps;
  const r3 = x => Math.round(x * 1000) / 10;   // 비율 → % (소수 1자리)
  return {"0": r3(p1 + p2 + p3), [t3]: r3(p1 + p2), [t3 + t2]: r3(p1), [t3 + t2 + t1]: 0};
}
// 손절: 증거금 대비 −2% ~ −35% → 가격 % 로 바꿈(÷레버리지) · 추적손절: 거리 1~35%, 오프셋 = 거리 + 0.1~10%
export function sampleRisk(lev, space){
  const r = {};
  if (space.includes("stoploss")) r.stop_loss_pct = Math.round(U(0.02, 0.35) / lev * 10000) / 100;
  if (space.includes("trailing")){ const tsp = U(0.01, 0.35); r.trailing_stop_positive_pct = Math.round(tsp / lev * 10000) / 100; r.trailing_stop_positive_offset_pct = Math.round((tsp + U(0.001, 0.1)) / lev * 10000) / 100; }
  if (space.includes("protection")) r.protections = [{method: "StoplossGuard", lookback_candles: I(2, 48), stop_candles: I(1, 24), trade_limit: I(2, 6)}, {method: "CooldownPeriod", stop_candles: I(0, 6) || 1}, {method: "MaxDrawdown", lookback_candles: I(12, 96), stop_candles: I(4, 48), trade_limit: I(2, 10), max_allowed_drawdown_pct: Math.round(U(5, 25))}];
  return r;
}
// 매수·매도 공간: 지표 길이(정수)와 조건의 숫자 문턱값을 ±50% 범위에서
export function paramsOf(spec){
  const P = [];
  (spec.indicators || []).forEach((ind, k) => { for (const key of ["length", "fast", "slow", "signal", "k_smooth", "d_smooth"]) if (Number.isFinite(+ind[key]) && ind.type !== "custom") P.push({kind: "ind", k, key, v: +ind[key], int: true}); if (Number.isFinite(+ind.mult)) P.push({kind: "ind", k, key: "mult", v: +ind.mult}); });
  for (const g of ["long_entry", "short_entry", "long_exit", "short_exit"]) (spec[g]?.conditions || []).forEach((c, j) => { if (Number.isFinite(+c.right) && String(c.right).trim() !== "" && !/rising|falling/.test(c.op)) P.push({kind: "cond", g, j, v: +c.right}); });
  return P;
}
function applyParams(spec, P, vals){
  const s = JSON.parse(JSON.stringify(spec));
  P.forEach((p, i) => { const v = vals[i]; if (p.kind === "ind") s.indicators[p.k][p.key] = p.int ? Math.max(2, Math.round(v)) : Math.round(v * 100) / 100; else s[p.g].conditions[p.j].right = String(Math.round(v * 100) / 100); });
  return s;
}
const sampleParam = (p, around) => { const base = around ?? p.v, lo = p.v * 0.5, hi = p.v * 1.5 || 1; const x = around == null ? U(Math.min(lo, hi), Math.max(lo, hi)) : base + (U(-0.15, 0.15) * Math.abs(p.v || 1)); return p.int ? Math.max(2, Math.round(x)) : x; };

/* ================= 하이퍼옵트 ================= */
// Q: quant.js 모듈 · spec: 정규화 전략 · cs: 캔들 · opts: {epochs, loss, space:["buy","roi","stoploss","trailing","protection"], tfMin, onProgress}
// 표본추출: 처음 30개는 무작위(freqtrade 의 초기 점 30 과 같음), 그 뒤는 상위 5개 주변을 좁혀 찾는다(간단한 진화 탐색 — NSGA-III 대신)
export async function hyperopt(Q, spec, cs, {epochs = 60, loss = "SharpeDaily", space = ["buy", "roi", "stoploss", "trailing"], tfMin = 60, onProgress} = {}){
  const L = LOSSES[loss] || LOSSES.SharpeDaily, split = Math.floor(cs.length * 0.7), train = cs.slice(0, split), B = 10000;
  const days = Math.max(1, (train.at(-1).t - train[0].t) / 864e5), P = space.includes("buy") ? paramsOf(spec) : [], lev = spec.risk?.leverage || 3;
  const score = s => { try { const r = Q.backtest(s, train, {initialEquity: B}); if (r.trades.length < 5) return {loss: 1e9, r}; return {loss: L.f(r.trades, B, days), r}; } catch(e){ return {loss: 1e9, err: e.message}; } };
  const base = score(spec), tried = [{spec, ...base, vals: P.map(p => p.v), risk: {}}];
  for (let e = 0; e < epochs; e++){
    const top = [...tried].sort((a, b) => a.loss - b.loss).slice(0, 5), parent = e >= 30 ? top[Math.floor(rnd() * top.length)] : null;
    const vals = P.map((p, i) => sampleParam(p, parent ? parent.vals[i] : null));
    let s = applyParams(spec, P, vals);
    const risk = {...sampleRisk(lev, space)}; if (space.includes("roi")) risk.minimal_roi = sampleROI(tfMin);
    if (parent && rnd() < 0.5) Object.assign(risk, parent.risk);   // 부모의 위험 설정을 절반 확률로 물려받음
    s = {...s, risk: {...s.risk, ...risk}};
    try { s = Q.normalizeSpec(s); } catch(err){ continue; }
    tried.push({spec: s, ...score(s), vals, risk});
    if (e % 6 === 5){ onProgress?.(e + 1, epochs); await new Promise(r => { try { const ch = new MessageChannel(); ch.port1.onmessage = () => { ch.port1.close(); r(); }; ch.port2.postMessage(0); } catch (e) { setTimeout(r, 0); } }); }   // 화면이 멈추지 않게
  }
  const ranked = [...tried].sort((a, b) => a.loss - b.loss), best = ranked[0], valid = tried.filter(x => x.loss < 1e9).length;
  // 검증: 전체 데이터로 walk-forward (뒤 30% = 하이퍼옵트가 한 번도 못 본 구간)
  const wfBase = Q.walkForward(spec, cs), wfBest = Q.walkForward(best.spec, cs);
  return {loss, lossKo: L.ko, epochs: tried.length - 1, valid, top: ranked.slice(0, 5).map(x => +x.loss.toFixed(3)), base: {loss: base.loss, wf: wfBase}, best: {loss: best.loss, spec: best.spec, wf: wfBest, risk: best.risk},
    improved: wfBest.pass && (wfBest.oos.net_pnl > wfBase.oos.net_pnl), overfit: best.loss < base.loss && wfBest.oos.net_pnl <= wfBase.oos.net_pnl};
}

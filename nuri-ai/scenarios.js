// 시나리오 분석: 같은 전략을 '모든 레버리지 · 모든 시장 국면 · 모든 기간 · 비용·지연·손절 변화'로 다시 돌려 본다.
// - 순수 함수 (네트워크·저장소 없음). quant.js 의 normalizeSpec · signals · Simulator · backtest 를 그대로 쓴다.
// - 신호는 한 번만 계산하고 (레버리지·비용·손절은 신호에 영향 없음) Simulator 만 바꿔 돌린다 → 백테스트 총 16회 정도.
// - 레버리지: normalizeSpec 은 125배 초과를 거절하지만 Simulator 자체엔 상한이 없다.
//   그래서 신호는 125배로 줄인 spec 으로 만들고, 시뮬레이터에는 원래 레버리지(최대 200배)를 넣는다.
//   주의: 엔진의 유지증거금률이 0.5% 라 청산가 = 진입가 × (1 ∓ (1/레버리지 − 0.005)).
//   200배면 1/200 = 0.005 → 청산가 = 진입가 → 진입하자마자 강제청산된다 (바이낸스도 최대 125배).
import { normalizeSpec, signals, Simulator, backtest, INTERVAL_SECONDS, pyRound } from "./quant.js";

export const LEVERAGES = [1, 2, 3, 5, 10, 20, 50, 100, 125, 200];
const MAX_LEV = 200, SPEC_MAX_LEV = 125;
const DAY = 86400000, YEAR = 365.25 * DAY;
const r2 = v => v === null || v === undefined || !Number.isFinite(v) ? v ?? null : pyRound(v, 2);
const iso = t => t === null || t === undefined ? null : new Date(t).toISOString().slice(0, 10);
const sg = v => v === null || v === undefined ? "?" : (v >= 0 ? "+" : "") + Number(v).toFixed(1) + "%";
const money = v => v === null || v === undefined ? "?" : (v >= 0 ? "+" : "") + Number(v).toLocaleString("en-US", {maximumFractionDigits: Math.abs(v) >= 100 ? 0 : 2});

// 캔들 정규화 ({t,o,h,l,c,v} · {time,open,…} · [t,o,h,l,c,v]).
// 초/밀리초는 배열 전체로 판단한다 (가장 큰 |t| 가 1e11 미만이면 초). quant.js 는 봉마다 t < 1e12 면 초로 보므로
// 2001-09-09 이전(1927년 S&P 등) 밀리초 시각을 1000배로 잘못 바꾼다 → quantInput() 으로 ISO 문자열을 넘겨 피한다.
function prepCandles(cs){
  if (!Array.isArray(cs) || !cs.length) throw new Error("캔들 배열이 필요합니다");
  const raw = cs.map(b => Array.isArray(b) ? b[0] : (b.t ?? b.time));
  const nums = raw.filter(t => typeof t !== "string" || /^\s*-?\d+(\.\d+)?\s*$/.test(t)).map(Number);
  const secs = nums.length && Math.max(...nums.map(Math.abs)) < 1e11;
  const ms = t => typeof t === "string" && !/^\s*-?\d+(\.\d+)?\s*$/.test(t) ? Date.parse(t) : secs ? +t * 1000 : +t;
  return cs.map((b, i) => Array.isArray(b) ? {t: ms(b[0]), o: +b[1], h: +b[2], l: +b[3], c: +b[4], v: +(b[5] ?? 0)}
    : {t: ms(raw[i]), o: +(b.o ?? b.open), h: +(b.h ?? b.high), l: +(b.l ?? b.low), c: +(b.c ?? b.close), v: +(b.v ?? b.volume ?? 0)});
}
// quant.js 에 넘길 캔들: 2001-09-09(1e12 ms) 이전 봉이 있으면 시각을 ISO 문자열로 (quant.js 가 Date.parse 로 정확히 읽는다)
const quantInput = c => c[0].t < 1e12 ? c.map(b => ({...b, t: new Date(b.t).toISOString()})) : c;
// 캔들의 실제 봉 간격(초): 시각 차이의 중앙값
function medianStepSec(c){
  const d = [];
  for (let i = 1; i < c.length && d.length < 2000; i++) d.push(c[i].t - c[i - 1].t);
  d.sort((a, b) => a - b);
  return d.length ? d[d.length >> 1] / 1000 : 3600;
}

/* ============ 시뮬레이션 1회 (backtest 루프와 같은 순서) ============ */
// risk 는 이미 정규화된 값 (레버리지 상한 없음). sig 는 signals() 결과 (또는 지연시킨 것)
function simulateRaw(c, sig, risk, bs, init){
  const sim = new Simulator(risk, init, bs);
  for (let i = 0; i < c.length; i++){ sim.step(c[i], sig, i); if (sim.blown) break; }
  if (sim.position){
    const last = c[c.length - 1];
    sim.close(last.c, last.t, "end_of_test");
    sim.equityCurve[sim.equityCurve.length - 1].v = pyRound(sim.cash, 4);
  }
  return sim;
}
function simulate(c, sig, risk, bs, init, bustPct){
  const sim = simulateRaw(c, sig, risk, bs, init);
  return summarize(sim.trades, sim.equityCurve, init, sim.blown, bustPct);
}
// 백테스트 결과 요약: 수익률·최대낙폭·강제청산·파산(에쿼티가 초기의 bustPct% 이하) 및 파산 시각
function summarize(trades, eq, init, blown, bustPct = 1){
  let peak = init, mdd = 0, minV = init, ruinT = null;
  const floor = init * bustPct / 100;
  for (const p of eq){
    if (p.v > peak) peak = p.v;
    mdd = Math.max(mdd, peak > 0 ? (peak - p.v) / peak * 100 : 100);
    if (p.v < minV) minV = p.v;
    if (ruinT === null && p.v <= floor) ruinT = p.t;
  }
  const fin = eq.length ? eq[eq.length - 1].v : init, n = trades.length;
  const wins = trades.filter(t => t.pnl > 0), gw = wins.reduce((s, t) => s + t.pnl, 0);
  const gl = -trades.filter(t => t.pnl <= 0).reduce((s, t) => s + t.pnl, 0);
  const bust = !!blown || ruinT !== null;
  return {return_pct: r2((fin / init - 1) * 100), max_dd_pct: r2(Math.min(100, mdd)), final_equity: r2(fin), min_equity: r2(minV),
    n_trades: n, win_rate: n ? pyRound(wins.length / n * 100, 1) : null, profit_factor: gl > 0 ? r2(gw / gl) : null,
    liquidations: trades.filter(t => t.reason === "liquidation").length,
    fees: r2(trades.reduce((s, t) => s + t.fees, 0)), funding: r2(trades.reduce((s, t) => s + t.funding, 0)),
    bust, ruin_t: bust ? (ruinT ?? eq[eq.length - 1]?.t ?? null) : null};
}
// 신호 전체를 k봉 늦춘다 (봉 i 마감 신호 → 봉 i+k 마감에 판단 → 봉 i+k+1 시가 체결). ATR 은 그대로
function delaySignals(sig, k = 1){
  const sh = a => a.map((_, i) => i >= k ? a[i - k] : false);
  return {...sig, longEntry: sh(sig.longEntry), shortEntry: sh(sig.shortEntry), longExit: sh(sig.longExit), shortExit: sh(sig.shortExit)};
}

/* ============ 시장 국면 ============ */
// 봉마다 국면 하나 (우선순위 순). 창 길이는 '일' 기준을 봉 수로 환산 (일봉: 200/50/20봉, 1시간봉: 4800/1200/480봉).
// 데이터가 짧으면 L = max(20, n/5) 로 줄인다.
//   1) 폭락 crash : 종가가 최근 C봉(20일) 최고가 대비 crashPct(기본 20)% 이상 아래
//   2) 하락장 bear(고점 기준) : 종가 < SMA L(200일) 이고 최근 L봉 최고가 대비 bearDD(기본 20)% 이상 아래 — 흔히 말하는 '고점 대비 -20% = 약세장'.
//      (200일선은 늦게 꺾이므로 큰 상승 뒤 하락 초기를 잡으려고 둔다. 약세장은 변동성도 크므로 고변동보다 먼저 본다)
//   3) 고변동 highvol : ATR14/종가 가 전체 기간 분포의 상위 (100 − volPct)% (기본 상위 20%) — 서술용이라 전체 분포를 쓴다
//   4) 상승장 bull : 종가 > SMA L 이고 SMA 기울기 강도 z ≥ zMin(0.25)
//   5) 하락장 bear : 종가 < SMA L 이고 z ≤ −zMin
//   6) 횡보 sideways : 그 밖 (가격과 200일선 방향이 엇갈리거나 200일선이 평평함)
//   z = (SMA[i] / SMA[i−S] − 1) / (봉 수익률 표준편차(S봉) × √S)  — S봉(50일) 동안 200일선이 변동성 대비 얼마나 움직였나
//   워밍업(SMA 없음) 구간은 unknown. 합성 시세 검증: 상승 구간 68%·하락 44%·횡보 49% 일치 (일봉, 200일선 지연 탓에 전환 초기는 어긋남)
export const REGIMES = {bull: "상승장", bear: "하락장", sideways: "횡보", crash: "폭락", highvol: "고변동", unknown: "판단불가(초기)"};
export function classifyRegimes(candles, opts = {}){
  const c = prepCandles(candles), n = c.length;
  const bs = opts.barSeconds || medianStepSec(c), perDay = Math.max(1 / 31, 86400 / bs);
  let L = Math.round((opts.trendDays ?? 200) * perDay), S = Math.round((opts.slopeDays ?? 50) * perDay), C = Math.round((opts.crashDays ?? 20) * perDay);
  if (n < L * 2.5){ L = Math.max(20, Math.floor(n / 5)); S = Math.max(5, Math.floor(L / 4)); C = Math.max(5, Math.floor(L / 10)); }
  S = Math.max(2, S); C = Math.max(2, C);
  const crashPct = opts.crashPct ?? 20, volPct = opts.volPct ?? 80, zMin = opts.zMin ?? 0.25, bearDD = opts.bearDD ?? 20;
  // SMA L
  const sma = new Array(n).fill(null); let s = 0;
  for (let i = 0; i < n; i++){ s += c[i].c; if (i >= L) s -= c[i - L].c; if (i >= L - 1) sma[i] = s / L; }
  // 봉 수익률의 S봉 이동 표준편차
  const ret = c.map((b, i) => i ? b.c / c[i - 1].c - 1 : 0), sd = new Array(n).fill(null);
  let a1 = 0, a2 = 0;
  for (let i = 1; i < n; i++){
    a1 += ret[i]; a2 += ret[i] * ret[i];
    if (i > S){ a1 -= ret[i - S]; a2 -= ret[i - S] * ret[i - S]; }
    if (i >= S){ const m = a1 / S; sd[i] = Math.sqrt(Math.max(0, a2 / S - m * m)); }
  }
  // ATR14 (Wilder) / 종가
  const atrp = new Array(n).fill(null); let atr = null, trs = 0;
  for (let i = 0; i < n; i++){
    const b = c[i], tr = i ? Math.max(b.h - b.l, Math.abs(b.h - c[i - 1].c), Math.abs(b.l - c[i - 1].c)) : b.h - b.l;
    if (i < 14){ trs += tr; if (i === 13) atr = trs / 14; } else atr = (atr * 13 + tr) / 14;
    if (atr !== null && b.c > 0) atrp[i] = atr / b.c;
  }
  const sorted = atrp.filter(v => v !== null).sort((x, y) => x - y);
  const volCut = sorted.length ? sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * volPct / 100))] : Infinity;
  // 최근 W봉 최고가 (단조 덱, O(n))
  const rollHigh = W => {
    const dq = [], out = new Array(n); let head = 0;
    for (let i = 0; i < n; i++){
      while (dq.length > head && c[dq[dq.length - 1]].h <= c[i].h) dq.pop();
      dq.push(i);
      while (dq[head] <= i - W) head++;
      out[i] = c[dq[head]].h;
    }
    return out;
  };
  const hiC = rollHigh(C), hiL = rollHigh(L);
  const labels = new Array(n);
  for (let i = 0; i < n; i++){
    const b = c[i];
    if (i >= C - 1 && b.c <= hiC[i] * (1 - crashPct / 100)){ labels[i] = "crash"; continue; }
    if (sma[i] !== null && b.c < sma[i] && b.c <= hiL[i] * (1 - bearDD / 100)){ labels[i] = "bear"; continue; }
    if (atrp[i] !== null && atrp[i] >= volCut && sorted.length > 50){ labels[i] = "highvol"; continue; }
    if (sma[i] === null || i < S || sma[i - S] === null || sd[i] === null){ labels[i] = "unknown"; continue; }
    const z = sd[i] > 0 ? (sma[i] / sma[i - S] - 1) / (sd[i] * Math.sqrt(S)) : 0;
    labels[i] = b.c > sma[i] && z >= zMin ? "bull" : b.c < sma[i] && z <= -zMin ? "bear" : "sideways";
  }
  return {labels, windows: {trend_bars: L, slope_bars: S, crash_bars: C, crash_pct: crashPct, vol_pct: volPct, z_min: zMin, bear_dd_pct: bearDD}};
}
// 거래를 진입 직전 봉(신호를 낸 봉)의 국면에 귀속시켜 국면별 성적
function regimeStats(c, labels, trades, warnings = []){
  const idx = new Map(c.map((b, i) => [b.t, i])), out = {};
  let unmatched = 0;
  for (const k of Object.keys(REGIMES)) out[k] = {regime: k, ko: REGIMES[k], bars: 0, mkt: 1, trades: 0, wins: 0, total_pnl: 0, pnl_pct_sum: 0};
  for (let i = 0; i < c.length; i++){ const o = out[labels[i]]; o.bars++; if (i) o.mkt *= c[i].c / c[i - 1].c; }
  for (const t of trades){
    const i = idx.get(t.entryT);
    if (i === undefined) unmatched++;
    const k = i === undefined ? "unknown" : labels[Math.max(0, i - 1)], o = out[k];
    o.trades++; if (t.pnl > 0) o.wins++; o.total_pnl += t.pnl; o.pnl_pct_sum += t.pnlPct;
  }
  if (unmatched) warnings.push(`진입 시각을 캔들에서 못 찾은 거래 ${unmatched}건은 '판단불가'로 셈`);
  return Object.values(out).filter(o => o.bars || o.trades).map(o => ({regime: o.regime, ko: o.ko, bars: o.bars, bar_share_pct: r2(o.bars / c.length * 100),
    market_return_pct: r2((o.mkt - 1) * 100), trades: o.trades, win_rate: o.trades ? pyRound(o.wins / o.trades * 100, 1) : null,
    avg_pnl: o.trades ? r2(o.total_pnl / o.trades) : null, avg_pnl_pct: o.trades ? r2(o.pnl_pct_sum / o.trades) : null, total_pnl: r2(o.total_pnl)}));
}

/* ============ 기간별 성적 ============ */
// 에쿼티 곡선을 UTC 연도(또는 10년) 단위로 나눠: 수익률(직전 구간 마지막 값 기준) · 구간 최대낙폭 · 거래 수 · 시장 등락
function periodStats(c, eq, trades, init, keyOf){
  const groups = new Map();
  for (const p of eq){ const k = keyOf(p.t); if (!groups.has(k)) groups.set(k, []); groups.get(k).push(p); }
  const firstClose = new Map(), lastClose = new Map();
  for (const b of c){ const k = keyOf(b.t); if (!firstClose.has(k)) firstClose.set(k, b); lastClose.set(k, b); }
  const out = []; let startV = init, prevClose = null;
  for (const [k, pts] of groups){
    let peak = startV, mdd = 0;
    for (const p of pts){ peak = Math.max(peak, p.v); mdd = Math.max(mdd, peak > 0 ? (peak - p.v) / peak * 100 : 100); }
    const endV = pts[pts.length - 1].v, fc = firstClose.get(k), lc = lastClose.get(k);
    const base = prevClose ?? fc?.o ?? fc?.c;
    out.push({period: k, from: iso(pts[0].t), to: iso(pts[pts.length - 1].t), return_pct: r2(startV > 0 ? (endV / startV - 1) * 100 : -100),
      max_dd_pct: r2(Math.min(100, mdd)), trades: trades.filter(t => keyOf(t.entryT) === k).length,
      market_return_pct: base && lc ? r2((lc.c / base - 1) * 100) : null});
    startV = endV; prevClose = lc?.c ?? prevClose;
  }
  return out;
}
// 낙폭 구간: 고점 → 저점 → 회복(고점 재돌파). 깊은 순 top k
function drawdownEpisodes(eq, init, k = 3){
  const eps = []; let peak = init, peakT = eq[0]?.t ?? null, cur = null;
  for (const p of eq){
    if (p.v >= peak){
      if (cur){ cur.recover_t = p.t; eps.push(cur); cur = null; }
      peak = p.v; peakT = p.t; continue;
    }
    const dd = (peak - p.v) / peak * 100;
    if (!cur) cur = {peak_t: peakT, trough_t: p.t, depth_pct: dd, recover_t: null};
    else if (dd > cur.depth_pct){ cur.depth_pct = dd; cur.trough_t = p.t; }
  }
  if (cur) eps.push(cur);
  return eps.sort((a, b) => b.depth_pct - a.depth_pct).slice(0, k).map(e => ({depth_pct: r2(Math.min(100, e.depth_pct)), peak: iso(e.peak_t), trough: iso(e.trough_t),
    recovered: iso(e.recover_t), days_to_recover: e.recover_t ? Math.round((e.recover_t - e.peak_t) / DAY) : null}));
}
// 가장 긴 연속 손실 거래
function losingStreak(trades){
  let best = null, run = null;
  for (const t of trades){
    if (t.pnl <= 0){ run = run ? {...run, n: run.n + 1, to: t.exitT, pnl: run.pnl + t.pnl} : {n: 1, from: t.entryT, to: t.exitT, pnl: t.pnl}; if (!best || run.n > best.n) best = run; }
    else run = null;
  }
  return best ? {trades: best.n, from: iso(best.from), to: iso(best.to), total_pnl: r2(best.pnl)} : {trades: 0, from: null, to: null, total_pnl: 0};
}

/* ============ 진입점 ============ */
// runScenarios(spec, candles, opts) — 동기 · 순수
// opts: {initialEquity=10000, deriv, leverages=LEVERAGES(최대 200), costs:{fee_pct, slippage_pct, funding_rate_8h_pct}(spec.risk 덮어씀),
//        barSeconds(기본: spec.interval, 캔들 간격과 다르면 캔들 간격), bustPct=1(에쿼티가 초기의 1% 이하면 파산), regime:{classifyRegimes 옵션}}
export function runScenarios(spec, candles, opts = {}){
  const raw = typeof spec === "string" ? JSON.parse(spec) : spec;
  const wantLev = Number(raw?.risk?.leverage ?? 3);
  if (!(wantLev > 0 && wantLev <= MAX_LEV)) throw new Error(`레버리지는 0~${MAX_LEV} 사이여야 합니다 (${raw?.risk?.leverage})`);
  // 125배 초과는 125로 줄여 검증한 뒤 정규화된 객체에 원래 값을 되돌려 넣는다
  const clampSpec = {...raw, risk: {...(raw.risk || {}), ...(opts.costs || {}), leverage: Math.min(wantLev, SPEC_MAX_LEV)}};
  const S = normalizeSpec(clampSpec);
  const baseRisk = {...S.risk, leverage: wantLev};
  const c = prepCandles(candles);
  if (c.length < 50) throw new Error(`봉이 너무 적습니다 (${c.length}개)`);
  const init = opts.initialEquity ?? 10000, bustPct = opts.bustPct ?? 1;
  const specSec = INTERVAL_SECONDS[S.interval], realSec = medianStepSec(c);
  // 캔들 간격이 spec.interval 과 다르면 (예: 1h 전략을 일봉으로 돌림) 펀딩·샤프 계산용 간격은 캔들 기준
  const bs = opts.barSeconds || (Math.abs(realSec / specSec - 1) > 0.5 ? realSec : specSec);
  const warnings = [];
  if (bs !== specSec) warnings.push(`캔들 간격(${Math.round(realSec / 60)}분)이 전략 간격 ${S.interval} 과 달라 캔들 간격 기준으로 계산`);
  const qc = quantInput(c);
  const sig = signals(S, qc, opts.deriv);
  const run = risk => simulate(c, sig, risk, bs, init, bustPct);
  let runs = 0;

  // 기본 실행: 125배 이하면 quant.js backtest 그대로 (거래·에쿼티가 필요), 초과면 Simulator 직접
  let baseTrades, baseEq, base;
  if (wantLev <= SPEC_MAX_LEV){
    const bt = backtest(S, qc, {deriv: opts.deriv, initialEquity: init, barSeconds: bs}); runs++;
    baseTrades = bt.trades; baseEq = bt.equity;
    base = {...summarize(bt.trades, bt.equity, init, bt.stats.blown_up, bustPct), sharpe: bt.stats.sharpe, buy_and_hold_pct: bt.stats.buy_and_hold_pct};
  } else {
    const sim = simulateRaw(c, sig, baseRisk, bs, init); runs++;
    baseTrades = sim.trades; baseEq = sim.equityCurve;
    base = {...summarize(sim.trades, sim.equityCurve, init, sim.blown, bustPct), sharpe: null, buy_and_hold_pct: r2((c[c.length - 1].c / c[0].c - 1) * 100)};
  }
  base.leverage = wantLev;

  // 1) 레버리지 스윕
  const levs = [...new Set((opts.leverages || LEVERAGES).map(Number).filter(x => x > 0 && x <= MAX_LEV))].sort((a, b) => a - b);
  const leverage = levs.map(L => { runs++; const r = run({...baseRisk, leverage: L}); return {leverage: L, ...r, ruin: iso(r.ruin_t)}; });

  // 2) 국면
  const reg = classifyRegimes(c, {barSeconds: bs, ...(opts.regime || {})});
  const regimes = regimeStats(c, reg.labels, baseTrades, warnings);

  // 3) 기간
  const spanY = (c[c.length - 1].t - c[0].t) / YEAR;
  const yearly = periodStats(c, baseEq, baseTrades, init, t => String(new Date(t).getUTCFullYear()));
  const decades = spanY > 15 ? periodStats(c, baseEq, baseTrades, init, t => Math.floor(new Date(t).getUTCFullYear() / 10) * 10 + "s") : null;
  const byRet = [...yearly].sort((a, b) => a.return_pct - b.return_pct);
  const periods = {yearly, decades, worst_year: byRet[0] || null, best_year: byRet[byRet.length - 1] || null,
    positive_years: yearly.filter(y => y.return_pct > 0).length, losing_streak: losingStreak(baseTrades), drawdowns: drawdownEpisodes(baseEq, init, 3)};

  // 4) 스트레스·가정 바꾸기 (모두 기본 레버리지)
  const stress = [];
  for (const k of [2, 3]){
    runs++;
    stress.push({key: `cost_x${k}`, ko: `수수료·슬리피지 ×${k}`, ...run({...baseRisk, fee_pct: baseRisk.fee_pct * k, slippage_pct: baseRisk.slippage_pct * k})});
  }
  // 1봉 지연: 신호 배열 4개를 1봉 뒤로 민다 (진입·청산 모두 한 봉 늦게 체결). quant.js API 로는 체결 시점을 못 바꾸므로 신호를 옮긴다
  runs++;
  stress.push({key: "delay_1", ko: "신호 1봉 지연", ...simulate(c, delaySignals(sig, 1), baseRisk, bs, init, bustPct)});
  // 손절 거리 ×0.5 / ×1.5 (stop_loss_pct · atr_stop_mult · trailing_stop_pct 중 있는 것 모두)
  const stopKeys = ["stop_loss_pct", "atr_stop_mult", "trailing_stop_pct"].filter(k => baseRisk[k]);
  if (stopKeys.length) for (const k of [0.5, 1.5]){
    const risk = {...baseRisk}; for (const s of stopKeys) risk[s] = baseRisk[s] * k;
    runs++;
    stress.push({key: `stop_x${k}`, ko: `손절폭 ×${k}`, ...run(risk)});
  }
  for (const s of stress) s.ruin = iso(s.ruin_t);

  const result = {spec: {name: S.name, symbol: S.symbol, interval: S.interval, leverage: wantLev, position_pct: S.risk.position_pct,
      fee_pct: S.risk.fee_pct, slippage_pct: S.risk.slippage_pct, funding_rate_8h_pct: S.risk.funding_rate_8h_pct, stops: stopKeys},
    data: {bars: c.length, from: iso(c[0].t), to: iso(c[c.length - 1].t), years: r2(spanY), bar_seconds: bs},
    base, leverage, regimes, regime_rules: reg.windows, periods, stress, runs, warnings};
  result.verdict = verdict(result);
  result.text = scenarioText(result);
  return result;
}

/* ============ 견고성 판정 (코드 규칙) ============ */
// 점검 항목 (각각 통과/미달, 거래 0건이면 판정 보류):
//   a) 기본 설정 수익 > 0
//   b) 레버리지: 강제청산 없는 최대 레버리지 ≥ 전략 레버리지  ("X배까지는 견딤, Y배부터 강제청산 n회", 파산이면 날짜)
//   c) 비용 ×2 에서도 수익 > 0  ("수수료 2배면 손익분기 아래")
//   d) 신호 1봉 지연에도 수익 > 0
//   e) 이익 연도 비율 ≥ 60% (연도 2개 이상일 때)
//   f) 국면 분산: 거래 3건 이상인 국면 중 이익 국면이 2개 이상 ("하락장에서만 손실" · "상승장에서만 이익" 등)
//   g) 손절폭 ×0.5·×1.5 모두 수익 > 0 (손절이 있을 때만)
//   등급: 통과 비율 ≥ 80% 견고 · ≥ 50% 보통 · 그 밖 취약. 기본 수익 ≤ 0 이면 무조건 취약
export function verdict(r){
  const pts = [], checks = [], b = r.base;
  if (!b.n_trades) return {grade: "판정 보류", score: null, points: ["거래가 한 건도 없어 판단할 수 없습니다"], checks};
  checks.push(["base", b.return_pct > 0]);
  if (b.return_pct <= 0) pts.push(`기본 설정(${r.spec.leverage}배)에서 손실 ${sg(b.return_pct)}`);
  // 레버리지
  const L = r.leverage, safe = L.filter(x => !x.liquidations && !x.bust), firstLiq = L.find(x => x.liquidations > 0), firstBust = L.find(x => x.bust);
  const maxSafe = safe.length ? Math.max(...safe.map(x => x.leverage)) : null;
  let lt = maxSafe === null ? "1배에서도 강제청산 발생" : `레버리지 ${maxSafe}배까지는 강제청산 없음`;
  if (firstLiq) lt += `, ${firstLiq.leverage}배부터 강제청산 ${firstLiq.liquidations}회`;
  if (firstBust) lt += ` · ${firstBust.leverage}배는 파산${firstBust.ruin ? ` (${firstBust.ruin})` : ""}`;
  if (L.some(x => x.leverage >= 200)) lt += " · 200배는 유지증거금률(0.5%)과 같아 진입 즉시 청산";
  pts.push(lt);
  checks.push(["leverage", maxSafe !== null && maxSafe >= r.spec.leverage]);
  const bestLev = [...L].sort((x, y) => y.return_pct - x.return_pct)[0];
  if (bestLev) pts.push(`수익이 가장 큰 레버리지 ${bestLev.leverage}배 (${sg(bestLev.return_pct)}, 최대낙폭 ${bestLev.max_dd_pct}%)`);
  // 비용
  const S = k => r.stress.find(s => s.key === k);
  const c2 = S("cost_x2"), c3 = S("cost_x3"), d1 = S("delay_1");
  if (b.return_pct > 0){
    if (c2.return_pct <= 0) pts.push(`수수료·슬리피지 2배면 손익분기 아래 (${sg(c2.return_pct)}) — 비용에 민감`);
    else if (c3.return_pct <= 0) pts.push(`비용 2배는 견디나 3배면 손실 (${sg(c3.return_pct)})`);
    else pts.push(`비용 3배에도 이익 유지 (${sg(c3.return_pct)})`);
  }
  checks.push(["cost", c2.return_pct > 0]);
  // 지연
  if (b.return_pct > 0 && d1.return_pct <= 0) pts.push(`신호 1봉 지연 시 손실 전환 (${sg(d1.return_pct)}) — 체결 타이밍에 민감`);
  else if (b.return_pct > 0 && d1.return_pct < b.return_pct * 0.5) pts.push(`신호 1봉 지연 시 수익 절반 이하 (${sg(b.return_pct)} → ${sg(d1.return_pct)})`);
  else if (b.return_pct > 0) pts.push(`신호 1봉 지연에도 성과 유지 (${sg(d1.return_pct)})`);
  checks.push(["delay", d1.return_pct > 0]);
  // 연도
  const Y = r.periods.yearly;
  if (Y.length >= 2){
    const w = r.periods.worst_year;
    pts.push(`${Y.length}년 중 ${r.periods.positive_years}년 이익 · 최악 ${w.period}년 ${sg(w.return_pct)}`);
    checks.push(["years", r.periods.positive_years / Y.length >= 0.6]);
  }
  // 국면
  const R = r.regimes.filter(x => x.trades >= 3 && x.regime !== "unknown");
  if (R.length){
    const win = R.filter(x => x.total_pnl > 0), lose = R.filter(x => x.total_pnl <= 0), ko = a => a.map(x => x.ko).join("·");
    if (!lose.length) pts.push(`모든 국면(${ko(R)})에서 이익`);
    else if (!win.length) pts.push(`모든 국면(${ko(R)})에서 손실`);
    else if (lose.length === 1) pts.push(`${lose[0].ko}에서만 손실 (${money(lose[0].total_pnl)})`);
    else if (win.length === 1) pts.push(`${win[0].ko}에서만 이익 (${money(win[0].total_pnl)}) — 특정 국면 의존`);
    else pts.push(`이익 국면: ${ko(win)} / 손실 국면: ${ko(lose)}`);
    checks.push(["regimes", win.length >= 2 || (win.length === R.length && R.length >= 1)]);
  }
  // 손절
  const s05 = S("stop_x0.5"), s15 = S("stop_x1.5");
  if (s05 && s15){
    const ok = s05.return_pct > 0 && s15.return_pct > 0;
    pts.push(ok ? `손절폭 ±50% 바꿔도 이익 (${sg(s05.return_pct)} / ${sg(s15.return_pct)})` : `손절폭에 민감 (×0.5 ${sg(s05.return_pct)} · ×1.5 ${sg(s15.return_pct)})`);
    checks.push(["stops", ok]);
  }
  // 바이앤홀드 비교
  if (b.buy_and_hold_pct !== null) pts.push(`같은 기간 보유만 했을 때 ${sg(b.buy_and_hold_pct)} (전략 ${sg(b.return_pct)})`);
  const pass = checks.filter(x => x[1]).length, score = checks.length ? pass / checks.length : 0;
  const grade = b.return_pct <= 0 ? "취약" : score >= 0.8 ? "견고" : score >= 0.5 ? "보통" : "취약";
  return {grade, score: r2(score * 100), passed: pass, total: checks.length, points: pts, checks: Object.fromEntries(checks)};
}

/* ============ LLM 프롬프트용 요약 (2500자 미만) ============ */
export function scenarioText(r){
  const b = r.base, P = r.periods, L = [];
  L.push(`[시나리오 분석] ${r.spec.name} · ${r.spec.symbol} ${r.spec.interval} · ${r.data.from}~${r.data.to} (${r.data.bars.toLocaleString("en-US")}봉, ${r.data.years}년)`);
  L.push(`기본(${r.spec.leverage}배·비중 ${r.spec.position_pct}%·수수료 ${r.spec.fee_pct}%): 수익 ${sg(b.return_pct)} · 최대낙폭 ${b.max_dd_pct}% · 거래 ${b.n_trades} · 승률 ${b.win_rate ?? "-"}% · 강제청산 ${b.liquidations} · 보유만 ${sg(b.buy_and_hold_pct)}`);
  L.push("레버리지: " + r.leverage.map(x => `${x.leverage}x ${x.bust ? "파산" + (x.ruin ? "(" + x.ruin + ")" : "") : sg(x.return_pct)}/DD${Math.round(x.max_dd_pct)}%/청산${x.liquidations}`).join(" | "));
  L.push("국면(진입 기준): " + r.regimes.filter(x => x.trades || x.bar_share_pct >= 5).map(x => `${x.ko} ${x.bar_share_pct}%봉 거래${x.trades}${x.trades ? ` 승률${x.win_rate}% 손익${money(x.total_pnl)}` : ""}`).join(" | "));
  const Y = P.yearly;
  if (P.decades) L.push("10년 단위: " + P.decades.map(d => `${d.period} ${sg(d.return_pct)}(DD${Math.round(d.max_dd_pct)}%)`).join(" · "));
  if (Y.length <= 12) L.push("연도: " + Y.map(y => `${y.period} ${sg(y.return_pct)}`).join(" · "));
  else {
    const s = [...Y].sort((a, b) => a.return_pct - b.return_pct);
    L.push(`연도(${Y.length}년, 이익 ${P.positive_years}년): 최악 ${s.slice(0, 3).map(y => `${y.period} ${sg(y.return_pct)}`).join(" · ")} / 최고 ${s.slice(-3).reverse().map(y => `${y.period} ${sg(y.return_pct)}`).join(" · ")}`);
  }
  if (P.drawdowns.length) L.push("최대 낙폭 구간: " + P.drawdowns.map(d => `-${d.depth_pct}% (${d.peak}→${d.trough}, ${d.recovered ? "회복 " + d.recovered : "미회복"})`).join(" · "));
  if (P.losing_streak.trades) L.push(`최장 연속 손실: ${P.losing_streak.trades}회 (${P.losing_streak.from}~${P.losing_streak.to}, ${money(P.losing_streak.total_pnl)})`);
  L.push("스트레스: " + r.stress.map(s => `${s.ko} ${s.bust ? "파산" : sg(s.return_pct)}`).join(" · "));
  if (r.verdict) L.push(`판정: ${r.verdict.grade}${r.verdict.total ? ` (${r.verdict.passed}/${r.verdict.total} 통과)` : ""} — ${r.verdict.points.join("; ")}`);
  if (r.warnings?.length) L.push("주의: " + r.warnings.join("; "));
  let t = L.join("\n");
  if (t.length >= 2500) t = t.slice(0, 2496) + "…";
  return t;
}

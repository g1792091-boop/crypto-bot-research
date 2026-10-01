// 누리 ML: 캔들 → 특징(quant.js 지표) → 로지스틱 회귀 · MLP · 그래디언트 부스팅 스텀프 → 롤링 재학습(walk-forward) 확률
// - 순수 JS (외부 라이브러리 없음). 시드 고정 난수 → 같은 입력이면 같은 결과. 브라우저와 Node 22 에서 import 로 쓴다.
// - 룩어헤드 방지: 봉 i 의 특징은 i 까지의 데이터만 쓴다. 라벨은 i+horizon 종가 방향.
//   학습 행은 예측 시점에 라벨이 이미 확정된 것만 (i + horizon ≤ 시험 시작 봉), 표준화(평균·표준편차)도 학습 구간에서만 맞춘다.
// - 결과 확률은 mlSeries() 로 {ml_prob, ml_signal} 시리즈가 되어 custom 지표 수식에서 쓸 수 있다 (예: "ml_prob > 0.6").
import { computeInd } from "./quant.js";

const isNil = v => v === null || v === undefined;
const nulls = n => new Array(n).fill(null);
const fin = v => typeof v === "number" && Number.isFinite(v) ? v : null;
const now = () => (globalThis.performance?.now?.() ?? Date.now());
const sig = z => z >= 0 ? 1 / (1 + Math.exp(-z)) : Math.exp(z) / (1 + Math.exp(z));
const r4 = v => v === null || v === undefined || !Number.isFinite(v) ? null : Math.round(v * 1e4) / 1e4;

/* ============ 난수 (시드 고정) ============ */
export function rng(seed = 1){
  let a = (seed >>> 0) || 1;
  return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
function gauss(r){ let u = 0; while (!u) u = r(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * r()); }
function shuffle(a, r){ for (let i = a.length - 1; i > 0; i--){ const j = Math.floor(r() * (i + 1)); const t = a[i]; a[i] = a[j]; a[j] = t; } return a; }

/* ============ 특징 ============ */
export const FEATURE_KO = {
  ret_1: "1봉 수익률", ret_3: "3봉 수익률", ret_6: "6봉 수익률", ret_12: "12봉 수익률", ret_24: "24봉 수익률",
  rsi: "RSI(14)", macd_hist: "MACD 히스토그램/ATR", bb_pctb: "볼린저 %B", bb_width: "볼린저 밴드폭", atr_pct: "ATR 변동성 %",
  adx: "ADX 추세강도", di_spread: "+DI − −DI", stoch_k: "스토캐스틱 K", cci: "CCI", mfi: "MFI 자금흐름", obv_slope: "OBV 10봉 기울기",
  vol_z: "거래량 Z점수", dist_ema20: "EMA20 이격도", dist_ema50: "EMA50 이격도", dist_ema200: "EMA200 이격도",
  st_trend: "슈퍼트렌드 방향", cloud_pos: "일목 구름 대비 위치", hour_sin: "시각(sin)", hour_cos: "시각(cos)", dow_sin: "요일(sin)", dow_cos: "요일(cos)",
};
// 캔들 형식 통일 ({t: ms, o,h,l,c,v}). 초/밀리초는 마지막 봉 시각으로 판단 (quant.js 와 같은 기준)
function normCandles(cs){
  if (!Array.isArray(cs)) throw new Error("캔들 배열이 필요합니다");
  const lastT = cs.length ? (Array.isArray(cs.at(-1)) ? cs.at(-1)[0] : (cs.at(-1).t ?? cs.at(-1).time)) : 0;
  const secs = Math.abs(+lastT) < 1e11;
  return cs.map(b => {
    const r = Array.isArray(b) ? {t: b[0], o: b[1], h: b[2], l: b[3], c: b[4], v: b[5]} : {t: b.t ?? b.time, o: b.o ?? b.open, h: b.h ?? b.high, l: b.l ?? b.low, c: b.c ?? b.close, v: b.v ?? b.volume};
    return {t: secs ? +r.t * 1000 : +r.t, o: +r.o, h: +r.h, l: +r.l, c: +r.c, v: +(r.v ?? 0)};
  });
}
// 외부 시리즈: 숫자 배열(봉 순서) 또는 [{t, value}] (시각 기준 forward-fill)
function alignSeries(arr, c){
  if (!Array.isArray(arr)) return nulls(c.length);
  const first = arr.find(v => !isNil(v));
  if (first && typeof first === "object"){
    const pts = arr.map(p => ({t: +(p.t ?? p.time), v: p.value ?? p.v})).map(p => ({t: Math.abs(p.t) < 1e11 ? p.t * 1000 : p.t, v: p.v})).sort((a, b) => a.t - b.t);
    let j = 0, last = null;
    return c.map(b => { while (j < pts.length && pts[j].t <= b.t){ last = isNil(pts[j].v) ? null : fin(+pts[j].v); j++; } return last; });
  }
  return c.map((_, i) => i < arr.length && !isNil(arr[i]) ? fin(+arr[i]) : null);
}
function rollZ(x, n){   // 창 n 의 z점수 (창 안 null 이면 null, 표준편차 0 이면 0)
  const out = nulls(x.length);
  for (let i = n - 1; i < x.length; i++){
    let s = 0, ss = 0, ok = true;
    for (let j = i - n + 1; j <= i; j++){ const v = x[j]; if (v === null){ ok = false; break; } s += v; ss += v * v; }
    if (!ok) continue;
    const m = s / n, sd = Math.sqrt(Math.max(0, ss / n - m * m));
    out[i] = sd > 1e-12 ? (x[i] - m) / sd : 0;
  }
  return out;
}

// 특징 행렬. X[i] = Float64Array (모든 특징이 있는 봉만, 아니면 null) · y[i] = 1(상승)/0 · fwd[i] = 로그수익률 %(회귀 목표)
// opts: {horizon=1, extraSeries: {이름: 시리즈}} — 외부 시리즈는 특징 "x_<이름>" 으로 붙는다 (봉 i 값은 i 시점에 알려진 것이어야 한다)
export function makeFeatures(candles, {horizon = 1, extraSeries = null} = {}){
  const c = normCandles(candles), n = c.length, h = Math.max(1, Math.trunc(horizon));
  const cl = c.map(b => b.c), ind = (type, p = {}) => computeInd(c, type, p);
  const cols = {};
  const lr = k => cl.map((v, i) => i >= k && v > 0 && cl[i - k] > 0 ? Math.log(v / cl[i - k]) * 100 : null);
  for (const k of [1, 3, 6, 12, 24]) cols["ret_" + k] = lr(k);
  const atr = ind("atr").value;
  cols.rsi = ind("rsi").value.map(v => v === null ? null : (v - 50) / 50);
  cols.macd_hist = ind("macd").hist.map((v, i) => v === null || !atr[i] ? null : v / atr[i]);
  const bb = ind("bb");
  cols.bb_pctb = cl.map((v, i) => bb.upper[i] === null || bb.upper[i] === bb.lower[i] ? null : (v - bb.lower[i]) / (bb.upper[i] - bb.lower[i]) - 0.5);
  cols.bb_width = bb.width.map(v => v === null || v <= 0 ? null : Math.log(v));
  cols.atr_pct = atr.map((v, i) => v === null || !cl[i] ? null : v / cl[i] * 100);
  const adx = ind("adx");
  cols.adx = adx.adx.map(v => v === null ? null : v / 100);
  cols.di_spread = adx.plus_di.map((v, i) => v === null || adx.minus_di[i] === null ? null : (v - adx.minus_di[i]) / 100);
  cols.stoch_k = ind("stoch").k.map(v => v === null ? null : (v - 50) / 50);
  cols.cci = ind("cci").value.map(v => v === null ? null : Math.max(-5, Math.min(5, v / 100)));
  cols.mfi = ind("mfi").value.map(v => v === null ? null : (v - 50) / 50);
  const obv = ind("obv").value;
  cols.obv_slope = obv.map((v, i) => { if (i < 10) return null; let s = 0; for (let j = i - 9; j <= i; j++) s += c[j].v; return s > 0 ? (v - obv[i - 10]) / s : 0; });
  cols.vol_z = rollZ(c.map(b => Math.log(1 + Math.max(0, b.v))), 50);
  for (const L of [20, 50, 200]){ const e = ind("ema", {length: L}).value; cols["dist_ema" + L] = cl.map((v, i) => e[i] ? (v / e[i] - 1) * 100 : null); }
  cols.st_trend = ind("supertrend").trend;
  const ich = ind("ichimoku");
  cols.cloud_pos = cl.map((v, i) => ich.span_a[i] === null || ich.span_b[i] === null || !atr[i] ? null : Math.max(-10, Math.min(10, (v - (ich.span_a[i] + ich.span_b[i]) / 2) / atr[i])));
  // 하루보다 짧은 봉이면 시각·요일 (UTC)
  const gaps = c.slice(1, 200).map((b, i) => b.t - c[i].t).filter(x => x > 0).sort((a, b) => a - b);
  const step = gaps.length ? gaps[gaps.length >> 1] : 0;
  if (step > 0 && step < 86400e3){
    const hr = c.map(b => { const d = new Date(b.t); return (d.getUTCHours() + d.getUTCMinutes() / 60) / 24 * 2 * Math.PI; });
    const dw = c.map(b => new Date(b.t).getUTCDay() / 7 * 2 * Math.PI);
    cols.hour_sin = hr.map(Math.sin); cols.hour_cos = hr.map(Math.cos); cols.dow_sin = dw.map(Math.sin); cols.dow_cos = dw.map(Math.cos);
  }
  const ko = {...FEATURE_KO};
  for (const [k, arr] of Object.entries(extraSeries || {})){
    if (!/^[A-Za-z_]\w*$/.test(k)) continue;
    cols["x_" + k] = alignSeries(arr, c); ko["x_" + k] = "외부: " + k;
  }
  const names = Object.keys(cols), d = names.length, A = names.map(k => cols[k]);
  const X = nulls(n);
  let start = -1;
  for (let i = 0; i < n; i++){
    const row = new Float64Array(d);
    let ok = true;
    for (let f = 0; f < d; f++){ const v = A[f][i]; if (v === null || v === undefined || !Number.isFinite(v)){ ok = false; break; } row[f] = v; }
    if (ok){ X[i] = row; if (start < 0) start = i; }
  }
  const fwd = cl.map((v, i) => i + h < n && v > 0 && cl[i + h] > 0 ? Math.log(cl[i + h] / v) * 100 : null);
  const y = fwd.map(v => v === null ? null : v > 0 ? 1 : 0);
  return {n, d, names, ko: names.map(k => ko[k] || k), X, y, fwd, t: c.map(b => b.t), close: cl, horizon: h, start};
}

// 표준화: 학습 행(rows)으로만 평균·표준편차를 맞추고 apply 로 새 행을 만든다
export function fitScaler(X, rows){
  const d = X[rows[0]].length, m = new Float64Array(d), s = new Float64Array(d);
  for (const i of rows){ const x = X[i]; for (let f = 0; f < d; f++) m[f] += x[f]; }
  for (let f = 0; f < d; f++) m[f] /= rows.length;
  for (const i of rows){ const x = X[i]; for (let f = 0; f < d; f++) s[f] += (x[f] - m[f]) ** 2; }
  for (let f = 0; f < d; f++){ s[f] = Math.sqrt(s[f] / rows.length); if (!(s[f] > 1e-12)) s[f] = 1; }
  return {mean: m, sd: s, apply: x => { const o = new Float64Array(d); for (let f = 0; f < d; f++) o[f] = Math.max(-8, Math.min(8, (x[f] - m[f]) / s[f])); return o; }};
}

/* ============ 모델 ============ */
// Adam 최적화 (파라미터 배열 여러 개를 한 번에)
class Adam {
  constructor(params, lr = 0.003, b1 = 0.9, b2 = 0.999){ this.p = params; this.lr = lr; this.b1 = b1; this.b2 = b2; this.t = 0; this.m = params.map(a => new Float64Array(a.length)); this.v = params.map(a => new Float64Array(a.length)); }
  step(grads, scale){
    this.t++;
    const {b1, b2} = this, c1 = 1 - b1 ** this.t, c2 = 1 - b2 ** this.t;
    for (let k = 0; k < this.p.length; k++){
      const p = this.p[k], g = grads[k], m = this.m[k], v = this.v[k];
      for (let i = 0; i < p.length; i++){
        const gi = g[i] * scale;
        m[i] = b1 * m[i] + (1 - b1) * gi; v[i] = b2 * v[i] + (1 - b2) * gi * gi;
        p[i] -= this.lr * (m[i] / c1) / (Math.sqrt(v[i] / c2) + 1e-8);
      }
    }
  }
}
const logloss = (p, y) => { const q = Math.min(1 - 1e-7, Math.max(1e-7, p)); return y ? -Math.log(q) : -Math.log(1 - q); };

// 로지스틱 회귀 (L2, 미니배치 Adam)
export class LogisticRegression {
  constructor(o = {}){ this.o = {l2: 1e-3, lr: 0.01, epochs: 30, batch: 64, seed: 1, ...o}; this.w = null; this.b = null; }
  fit(X, y){
    const {l2, lr, epochs, batch, seed} = this.o, d = X[0].length, r = rng(seed);
    const w = this.w = new Float64Array(d), b = this.b = new Float64Array(1), gw = new Float64Array(d), gb = new Float64Array(1);
    const opt = new Adam([w, b], lr), idx = [...X.keys()];
    for (let ep = 0; ep < epochs; ep++){
      shuffle(idx, r);
      for (let s = 0; s < idx.length; s += batch){
        gw.fill(0); gb[0] = 0;
        const e = Math.min(idx.length, s + batch);
        for (let k = s; k < e; k++){
          const x = X[idx[k]]; let z = b[0]; for (let f = 0; f < d; f++) z += w[f] * x[f];
          const g = sig(z) - y[idx[k]]; for (let f = 0; f < d; f++) gw[f] += g * x[f]; gb[0] += g;
        }
        const m = e - s; for (let f = 0; f < d; f++) gw[f] += l2 * w[f] * m;
        opt.step([gw, gb], 1 / m);
      }
    }
    return this;
  }
  predict(x){ let z = this.b[0]; for (let f = 0; f < x.length; f++) z += this.w[f] * x[f]; return sig(z); }
}

// MLP (은닉 1~2층, ReLU/tanh, 드롭아웃, Adam, 검증 손실 조기 종료 → 가장 좋았던 가중치로 복원)
export class MLP {
  constructor(o = {}){ this.o = {hidden: [16], act: "relu", dropout: 0.1, lr: 0.003, epochs: 40, batch: 32, l2: 1e-4, patience: 6, valFrac: 0.2, seed: 1, ...o}; this.epochsRun = 0; }
  _init(d){
    const r = rng(this.o.seed), H = (this.o.hidden || [16]).slice(0, 2).map(x => Math.max(1, Math.trunc(x)));
    this.sizes = [d, ...H, 1];
    this.W = []; this.B = [];
    for (let l = 0; l + 1 < this.sizes.length; l++){
      const fi = this.sizes[l], fo = this.sizes[l + 1], sc = Math.sqrt((this.o.act === "tanh" ? 1 : 2) / fi);
      this.W.push(Float64Array.from({length: fo * fi}, () => gauss(r) * sc)); this.B.push(new Float64Array(fo));
    }
    this.a = this.sizes.map(s => new Float64Array(s)); this.z = this.sizes.map(s => new Float64Array(s));
    this.mask = this.sizes.map(s => new Float64Array(s).fill(1)); this.delta = this.sizes.map(s => new Float64Array(s));
  }
  // 순전파 (train 이면 드롭아웃 마스크 적용). 반환: 확률
  _fwd(x, r){
    const L = this.W.length, tanh = this.o.act === "tanh", pd = r ? this.o.dropout : 0;
    this.a[0].set(x);
    for (let l = 0; l < L; l++){
      const W = this.W[l], B = this.B[l], ai = this.a[l], zo = this.z[l + 1], ao = this.a[l + 1], fi = this.sizes[l], fo = this.sizes[l + 1], last = l === L - 1;
      for (let j = 0; j < fo; j++){
        let s = B[j]; const off = j * fi; for (let k = 0; k < fi; k++) s += W[off + k] * ai[k];
        zo[j] = s;
        if (last) ao[j] = sig(s);
        else {
          let v = tanh ? Math.tanh(s) : (s > 0 ? s : 0);
          const mk = pd > 0 ? (r() < pd ? 0 : 1 / (1 - pd)) : 1;
          this.mask[l + 1][j] = mk; ao[j] = v * mk;
        }
      }
    }
    return this.a[L][0];
  }
  _bwd(y, gW, gB){
    const L = this.W.length, tanh = this.o.act === "tanh";
    this.delta[L][0] = this.a[L][0] - y;
    for (let l = L - 1; l >= 0; l--){
      const W = this.W[l], fi = this.sizes[l], fo = this.sizes[l + 1], dn = this.delta[l + 1], ai = this.a[l], G = gW[l], GB = gB[l];
      for (let j = 0; j < fo; j++){ const dj = dn[j]; if (!dj) continue; GB[j] += dj; const off = j * fi; for (let k = 0; k < fi; k++) G[off + k] += dj * ai[k]; }
      if (l === 0) break;
      const dl = this.delta[l], zl = this.z[l], ml = this.mask[l];
      for (let k = 0; k < fi; k++){
        let s = 0; for (let j = 0; j < fo; j++) s += W[j * fi + k] * dn[j];
        const dz = tanh ? 1 - Math.tanh(zl[k]) ** 2 : (zl[k] > 0 ? 1 : 0);
        dl[k] = s * dz * ml[k];
      }
    }
  }
  // X, y: 학습 행. val: {X, y} 를 주지 않으면 뒤쪽 valFrac 를 검증으로 떼어 쓴다 (시간 순서 유지)
  fit(X, y, val = null){
    let Xv = val?.X, yv = val?.y;
    if (!Xv){ const nv = Math.floor(X.length * this.o.valFrac); if (nv >= 20){ Xv = X.slice(-nv); yv = y.slice(-nv); X = X.slice(0, -nv); y = y.slice(0, -nv); } }
    this._init(X[0].length);
    const r = rng(this.o.seed + 101), {epochs, batch, l2, patience} = this.o;
    const gW = this.W.map(w => new Float64Array(w.length)), gB = this.B.map(b => new Float64Array(b.length));
    const opt = new Adam([...this.W, ...this.B], this.o.lr), idx = [...X.keys()];
    let best = Infinity, bestW = null, bad = 0;
    for (let ep = 0; ep < epochs; ep++){
      shuffle(idx, r);
      for (let s = 0; s < idx.length; s += batch){
        for (const g of gW) g.fill(0); for (const g of gB) g.fill(0);
        const e = Math.min(idx.length, s + batch);
        for (let k = s; k < e; k++){ this._fwd(X[idx[k]], r); this._bwd(y[idx[k]], gW, gB); }
        const m = e - s;
        for (let l = 0; l < gW.length; l++){ const G = gW[l], W = this.W[l]; for (let i = 0; i < G.length; i++) G[i] += l2 * W[i] * m; }
        opt.step([...gW, ...gB], 1 / m);
      }
      this.epochsRun = ep + 1;
      if (Xv && Xv.length){
        let vl = 0; for (let i = 0; i < Xv.length; i++) vl += logloss(this.predict(Xv[i]), yv[i]); vl /= Xv.length;
        if (vl < best - 1e-5){ best = vl; bestW = [...this.W, ...this.B].map(a => a.slice()); bad = 0; }
        else if (++bad >= patience) break;
      }
    }
    if (bestW){ const all = [...this.W, ...this.B]; all.forEach((a, i) => a.set(bestW[i])); }
    this.valLoss = Number.isFinite(best) ? best : null;
    return this;
  }
  predict(x){ return this._fwd(x, null); }
}

// 그래디언트 부스팅 스텀프 (로지스틱 손실, 깊이 1 트리, 분위수 구간 히스토그램 → 싸다)
export class GradientBoostedStumps {
  constructor(o = {}){ this.o = {rounds: 60, lr: 0.1, bins: 16, lambda: 1, minLeaf: 20, ...o}; }
  fit(X, y){
    const {rounds, lr, bins, lambda, minLeaf} = this.o, N = X.length, d = X[0].length;
    // 특징별 경계값 (분위수) → 구간 번호
    this.thr = [];
    const Bn = [];
    for (let f = 0; f < d; f++){
      const col = X.map(x => x[f]).sort((a, b) => a - b), t = [];
      for (let q = 1; q < bins; q++){ const v = col[Math.floor(q / bins * (N - 1))]; if (!t.length || v > t[t.length - 1]) t.push(v); }
      this.thr.push(t);
      const b = new Uint8Array(N);
      for (let i = 0; i < N; i++){ let k = 0; const v = X[i][f]; while (k < t.length && t[k] < v) k++; b[i] = k; }
      Bn.push(b);
    }
    let pm = 0; for (const v of y) pm += v; pm = Math.min(0.99, Math.max(0.01, pm / N));
    this.base = Math.log(pm / (1 - pm)); this.stumps = [];
    const F = new Float64Array(N).fill(this.base), g = new Float64Array(N), h = new Float64Array(N);
    for (let r = 0; r < rounds; r++){
      let Gt = 0, Ht = 0;
      for (let i = 0; i < N; i++){ const p = sig(F[i]); g[i] = p - y[i]; h[i] = Math.max(1e-6, p * (1 - p)); Gt += g[i]; Ht += h[i]; }
      let best = null;
      for (let f = 0; f < d; f++){
        const nb = this.thr[f].length + 1, G = new Float64Array(nb), H = new Float64Array(nb), C = new Int32Array(nb), b = Bn[f];
        for (let i = 0; i < N; i++){ G[b[i]] += g[i]; H[b[i]] += h[i]; C[b[i]]++; }
        let GL = 0, HL = 0, CL = 0;
        for (let k = 0; k < nb - 1; k++){
          GL += G[k]; HL += H[k]; CL += C[k];
          if (CL < minLeaf || N - CL < minLeaf) continue;
          const GR = Gt - GL, HR = Ht - HL, gain = GL * GL / (HL + lambda) + GR * GR / (HR + lambda) - Gt * Gt / (Ht + lambda);
          if (!best || gain > best.gain) best = {gain, f, k, l: -GL / (HL + lambda), r: -GR / (HR + lambda)};
        }
      }
      if (!best || best.gain <= 1e-9) break;
      const st = {f: best.f, t: this.thr[best.f][best.k], l: lr * best.l, r: lr * best.r};
      this.stumps.push(st);
      const b = Bn[best.f];
      for (let i = 0; i < N; i++) F[i] += b[i] <= best.k ? st.l : st.r;
    }
    return this;
  }
  predict(x){ let s = this.base; for (const st of this.stumps) s += x[st.f] <= st.t ? st.l : st.r; return sig(s); }
}

export function makeModel(name, o = {}){
  if (name === "mlp") return new MLP(o);
  if (name === "gbs" || name === "boost") return new GradientBoostedStumps(o);
  if (name === "logreg" || name === "logistic") return new LogisticRegression(o);
  throw new Error(`알 수 없는 모델: ${name} (logreg / mlp / gbs)`);
}
const MODEL_KO = {logreg: "로지스틱 회귀", logistic: "로지스틱 회귀", mlp: "MLP 신경망", gbs: "부스팅 스텀프", boost: "부스팅 스텀프"};

/* ============ 평가 ============ */
// AUC (순위 기반, 동점은 평균 순위)
export function auc(p, y){
  const idx = [...p.keys()].sort((a, b) => p[a] - p[b]);
  let n1 = 0, rs = 0;
  for (let i = 0; i < idx.length;){
    let j = i; while (j + 1 < idx.length && p[idx[j + 1]] === p[idx[i]]) j++;
    const rank = (i + j) / 2 + 1;
    for (let k = i; k <= j; k++) if (y[idx[k]]) { n1++; rs += rank; }
    i = j + 1;
  }
  const n0 = idx.length - n1;
  return n1 && n0 ? (rs - n1 * (n1 + 1) / 2) / (n1 * n0) : null;
}
function classMetrics(p, y, hi, lo){
  const N = p.length;
  let ok = 0, ones = 0, ll = 0;
  for (let i = 0; i < N; i++){ ok += (p[i] >= 0.5 ? 1 : 0) === y[i] ? 1 : 0; ones += y[i]; ll += logloss(p[i], y[i]); }
  const rate = ones / N, base = Math.max(rate, 1 - rate), acc = ok / N, A = auc(p, y);
  const n1 = ones, n0 = N - ones;
  let aucSE = null;
  if (A !== null){ const q1 = A / (2 - A), q2 = 2 * A * A / (1 + A); aucSE = Math.sqrt((A * (1 - A) + (n1 - 1) * (q1 - A * A) + (n0 - 1) * (q2 - A * A)) / (n1 * n0)); }
  let bl = 0; for (let i = 0; i < N; i++) bl += logloss(rate, y[i]);
  const hiR = p.map((v, i) => [v, y[i]]).filter(([v]) => v > hi), loR = p.map((v, i) => [v, y[i]]).filter(([v]) => v < lo);
  const edges = [0, 0.4, 0.45, 0.5, 0.55, 0.6, 1.0001];
  const calibration = edges.slice(0, -1).map((a, k) => {
    const b = edges[k + 1], s = p.map((v, i) => [v, y[i]]).filter(([v]) => v >= a && v < b);
    return {lo: a, hi: Math.min(1, b), n: s.length, meanP: s.length ? r4(s.reduce((q, [v]) => q + v, 0) / s.length) : null, rate: s.length ? r4(s.reduce((q, [, t]) => q + t, 0) / s.length) : null};
  });
  return {N, accuracy: r4(acc), baseline: r4(base), upRate: r4(rate), z: r4(N ? (acc - base) / Math.sqrt(Math.max(1e-12, base * (1 - base) / N)) : 0),
    auc: r4(A), aucSE: r4(aucSE), logloss: r4(ll / N), coinLogloss: r4(Math.LN2), baseLogloss: r4(bl / N),
    hitHigh: {n: hiR.length, rate: hiR.length ? r4(hiR.filter(([, t]) => t === 1).length / hiR.length) : null},
    hitLow: {n: loR.length, rate: loR.length ? r4(loR.filter(([, t]) => t === 0).length / loR.length) : null}, calibration};
}

/* ============ 롤링 재학습 (walk-forward) ============ */
// opts: {model:"logreg"|"mlp"|"gbs", horizon=1, trainBars=1500, testBars=250, step=testBars, epochs, seed=7,
//        hi=0.55, lo=0.45, fee_pct=0.04, maxFolds=20, hidden, dropout, extraSeries, importance=true, budget}
// 큰 입력은 자동으로 줄인다: 학습 창 ≤ 3000봉, 재학습 ≤ maxFolds 회, 연산량이 예산을 넘으면 epoch 축소 (capped 에 기록).
export function walkForwardML(candles, opts = {}){
  const T0 = now();
  const o = {model: "logreg", horizon: 1, trainBars: 1500, testBars: 250, seed: 7, hi: 0.55, lo: 0.45, fee_pct: 0.04, maxFolds: 20, importance: true, budget: 1.2e9, ...opts};
  const h = Math.max(1, Math.min(100, Math.trunc(o.horizon)));
  const F = makeFeatures(candles, {horizon: h, extraSeries: o.extraSeries});
  const {n, X, y} = F, capped = [];
  if (F.start < 0 || n - F.start < 300) throw new Error(`봉이 너무 적습니다: 특징(EMA200 등) 계산 뒤 300봉 이상 필요 (전체 ${n}봉)`);
  let trainBars = Math.max(150, Math.min(Math.trunc(o.trainBars), 3000, Math.floor((n - F.start) * 0.6)));
  if (trainBars < o.trainBars) capped.push(`학습 창 ${trainBars}봉으로 축소`);
  const first = F.start + trainBars + h;
  let testBars = Math.max(1, Math.trunc(o.testBars)), step = Math.max(1, Math.trunc(o.step ?? testBars));
  if (Math.ceil((n - first) / step) > o.maxFolds){ step = Math.ceil((n - first) / o.maxFolds); testBars = Math.max(testBars, step); capped.push(`재학습 ${o.maxFolds}회로 제한 (시험 창 ${testBars}봉)`); }
  const folds = Math.max(0, Math.ceil((n - first) / step));
  // 연산량 예산 → epoch
  const H = (o.hidden || [16]).slice(0, 2);
  const per = o.model === "mlp" ? 3 * (F.d * H[0] + (H[1] ? H[0] * H[1] + H[1] : H[0])) : o.model === "gbs" ? F.d * 2 : 3 * F.d;
  let epochs = o.epochs ?? (o.model === "mlp" ? 40 : o.model === "gbs" ? 60 : 25);
  const est = folds * trainBars * epochs * per;
  if (est > o.budget){ const e2 = Math.max(o.model === "gbs" ? 15 : 5, Math.floor(epochs * o.budget / est)); if (e2 < epochs){ capped.push(`epoch ${epochs}→${e2} (연산량 제한)`); epochs = e2; } }

  const prob = nulls(n), foldInfo = [], store = [];
  let k = 0;
  for (let s = first; s < n; s += step, k++){
    const tr = [];
    for (let i = Math.max(F.start, s - h - trainBars + 1); i <= s - h; i++) if (X[i] && y[i] !== null) tr.push(i);   // 라벨 확정: i + h ≤ s
    if (tr.length < 100) continue;
    const sc = fitScaler(X, tr), Xtr = tr.map(i => sc.apply(X[i])), ytr = tr.map(i => y[i]);
    const mo = {...o, seed: o.seed + k * 7919, epochs, rounds: epochs};
    const model = makeModel(o.model, mo);
    if (o.model === "mlp"){
      // 검증(조기 종료)은 학습 창의 뒤 20%, 앞부분과 horizon 만큼 띄워 라벨 겹침을 막는다
      const nv = Math.max(20, Math.floor(tr.length * 0.2)), cut = tr.length - nv;
      model.fit(Xtr.slice(0, Math.max(1, cut - h)), ytr.slice(0, Math.max(1, cut - h)), {X: Xtr.slice(cut), y: ytr.slice(cut)});
    } else model.fit(Xtr, ytr);
    const te = [], Xte = [];
    for (let j = s; j < Math.min(n, s + testBars); j++){ if (!X[j]) continue; const xs = sc.apply(X[j]); te.push(j); Xte.push(xs); prob[j] = model.predict(xs); }
    store.push({model, te, Xte});
    foldInfo.push({start: F.t[s], train: tr.length, test: te.length, epochs: model.epochsRun ?? epochs});
  }
  // 평가: 라벨이 있는 표본 외 봉
  const ev = [];
  for (let j = 0; j < n; j++) if (prob[j] !== null && y[j] !== null) ev.push(j);
  if (!ev.length) throw new Error("표본 외 예측이 없습니다 (봉 수·학습 창을 확인하세요)");
  const P = ev.map(j => prob[j]), Y = ev.map(j => y[j]);
  const metrics = classMetrics(P, Y, o.hi, o.lo);
  // 단순 매매: p>hi 롱 · p<lo 숏 · 그 사이 관망. 봉 i 종가 판단 → i→i+1 수익, 포지션 바뀔 때 수수료(편도 fee_pct × 변화량)
  const firstP = prob.findIndex(v => v !== null), cl = F.close, eq = [];
  let v = 1, pos = 0, trades = 0, peak = 1, mdd = 0, inMkt = 0;
  for (let j = firstP; j >= 0 && j < n - 1; j++){
    const p = prob[j], want = p === null ? 0 : p > o.hi ? 1 : p < o.lo ? -1 : 0;
    if (want !== pos){ v *= 1 - Math.abs(want - pos) * o.fee_pct / 100; if (want) trades++; pos = want; }
    v *= 1 + pos * (cl[j + 1] / cl[j] - 1);
    if (pos) inMkt++;
    peak = Math.max(peak, v); mdd = Math.max(mdd, (peak - v) / peak * 100);
    eq.push({t: F.t[j + 1], v: r4(v)});
  }
  const span = Math.max(1, n - 1 - firstP);
  const trading = {return_pct: r4((v - 1) * 100), bh_pct: firstP >= 0 ? r4((cl[n - 1] / cl[firstP] - 1) * 100) : null, trades, max_dd_pct: r4(mdd), exposure_pct: r4(inMkt / span * 100), fee_pct: o.fee_pct};
  // 순열 중요도: 특징 하나를 시험 구간 안에서 섞었을 때 AUC 가 얼마나 떨어지나
  let importance = [];
  if (o.importance && metrics.auc !== null){
    const r = rng(o.seed + 999), lab = new Map(ev.map(j => [j, y[j]]));
    const drops = [];
    for (let f = 0; f < F.d; f++){
      const pp = [], yy = [];
      for (const st of store){
        const perm = shuffle([...st.Xte.keys()], r);
        for (let q = 0; q < st.te.length; q++){
          const j = st.te[q]; if (!lab.has(j)) continue;
          const x = st.Xte[q].slice(); x[f] = st.Xte[perm[q]][f];
          pp.push(st.model.predict(x)); yy.push(lab.get(j));
        }
      }
      drops.push({key: F.names[f], ko: F.ko[f], drop: r4(metrics.auc - auc(pp, yy))});
    }
    importance = drops.sort((a, b) => b.drop - a.drop).slice(0, 10);
  }
  // 판정: 정확도가 다수 클래스 기준선보다 2σ 이상 높고 AUC 도 0.5 보다 2σ 이상 높아야 '우위'
  const aucZ = metrics.aucSE ? (metrics.auc - 0.5) / metrics.aucSE : 0;
  const edge = metrics.z >= 2 && aucZ >= 2 ? "edge" : (metrics.z >= 2 || aucZ >= 2) ? "weak" : "none";
  return {model: o.model, horizon: h, n, folds: foldInfo.length, foldInfo, prob, y, t: F.t, features: F.names,
    metrics: {...metrics, aucZ: r4(aucZ)}, trading, equity: eq, importance, edge,
    params: {trainBars, testBars, step, epochs, hi: o.hi, lo: o.lo, seed: o.seed}, capped, elapsedMs: Math.round(now() - T0)};
}

// custom 지표·quant 백테스트용 외부 시리즈 (캔들과 같은 길이, 예측 없는 봉은 null)
export function mlSeries(res, {hi = res?.params?.hi ?? 0.55, lo = res?.params?.lo ?? 0.45} = {}){
  const p = res.prob || [];
  return {ml_prob: p.map(v => v === null ? null : r4(v)), ml_signal: p.map(v => v === null ? null : v > hi ? 1 : v < lo ? -1 : 0)};
}

// 프롬프트용 요약 (1500자 이내, 우위가 없으면 없다고 말한다)
export function mlText(res){
  const m = res.metrics, tr = res.trading, pct = v => v === null || v === undefined ? "?" : (v * 100).toFixed(1) + "%";
  const sg = v => v === null ? "?" : (v >= 0 ? "+" : "") + v.toFixed(1) + "%";
  const f2 = v => v === null || v === undefined ? "?" : v.toFixed(1), f3 = v => v === null || v === undefined ? "?" : v.toFixed(3);
  const verdict = res.edge === "edge" ? "판정: 기준선 대비 통계적으로 의미 있는 예측력 (정확도·AUC 모두 2σ 이상). 비용 반영 매매 성과는 따로 확인할 것."
    : res.edge === "weak" ? "판정: 약한 신호 — 정확도·AUC 중 하나만 유의. 표본 수·기간을 늘려 재확인 전에는 우위로 보지 말 것."
    : "판정: 우위 없음 — 동전 던지기(다수 클래스 기준선)와 통계적으로 구분되지 않는다. 이 확률로 매매하지 말 것.";
  const cal = m.calibration.filter(b => b.n).map(b => `${b.lo}~${b.hi}: 예측 ${pct(b.meanP)}/실제 ${pct(b.rate)} (${b.n})`).join(" · ");
  const lines = [
    `ML 예측 (${MODEL_KO[res.model] || res.model}, ${res.horizon}봉 뒤 방향 · 롤링 재학습 ${res.folds}회 · 표본 외 ${m.N}봉)`,
    `정확도 ${pct(m.accuracy)} vs 기준선(다수 클래스) ${pct(m.baseline)} (z=${f2(m.z)}) · AUC ${f3(m.auc)} (±${f3(m.aucSE)}) · 로그손실 ${f3(m.logloss)} (동전 ${f3(m.coinLogloss)}, 상수 확률 ${f3(m.baseLogloss)})`,
    `확신 구간: p>${res.params.hi} 적중 ${pct(m.hitHigh.rate)} (${m.hitHigh.n}봉) · p<${res.params.lo} 적중 ${pct(m.hitLow.rate)} (${m.hitLow.n}봉)`,
    `보정: ${cal}`,
    `단순 매매(편도 수수료 ${tr.fee_pct}%): ${sg(tr.return_pct)} vs 보유 ${sg(tr.bh_pct)} · 진입 ${tr.trades}회 · 최대낙폭 ${f2(tr.max_dd_pct)}% · 노출 ${f2(tr.exposure_pct)}%`,
  ];
  if (res.importance.length) lines.push(`중요 특징(AUC 하락): ${res.importance.slice(0, 6).map(x => `${x.ko} ${f3(x.drop)}`).join(", ")}`);
  if (res.capped.length) lines.push(`축소: ${res.capped.join(", ")}`);
  lines.push(verdict);
  let s = lines.join("\n");
  if (s.length > 1500) s = s.slice(0, 1497) + "...";
  return s;
}

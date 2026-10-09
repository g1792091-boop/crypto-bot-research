// 🧪 보조지표 조합 연구소 — 슈퍼트렌드+ROC · 슈퍼트렌드+클링거 · VWMA+MACD · 슈퍼트렌드+KST
// 순수 함수만(브라우저·노드 공용). 앱(combolab.js)과 도구(tools/combo-opt.mjs)가 같은 계산을 쓴다 → 백테스트와 실시간 데모가 같은 규칙.
//
// 신호: 두 지표의 방향(+1/−1)이 '같아지는 첫 마감봉'에서 그 방향으로 다음 봉 진입(이미 같은 방향이던 동안에는 다시 안 들어감).
// 청산: 손절(ATR×k) · 익절(순 손익비 rr) · +1R 본절 · 시간(48봉) · 선택: 반대 신호(ex=1) 또는 추세 지표 전환(ex=2).
// 레버리지: 고정 배수 L 에서 손절 ≤ 청산거리의 40% = 0.4/L (20x 2% · 30x 1.33% · 40x 1% · 50x 0.8%).
//   ATR×k 손절이 이 상한보다 넓으면 '이 레버리지로는 노이즈를 못 버팀' → 그 신호는 건너뛴다(손절을 억지로 좁히지 않음).
export const FEE = 0.0008, SL_FLOOR = 0.0025, HOLD = 48, RISK = 0.005, LANE_EQ = 1000;
export const TFS = ["15", "30", "60"];
export const TF_KO = { "15": "15분", "30": "30분", "60": "1시간" };
export const TF_MS = { "15": 900e3, "30": 1800e3, "60": 3600e3 };
export const LEVS = { "15": [30, 40, 50], "30": [30, 40, 50], "60": [20, 30, 40, 50] };
export const slCapOf = lev => 0.4 / lev;
export const COINS = [["BTC", "BTCUSDT"], ["ETH", "ETHUSDT"], ["SOL", "SOLUSDT"], ["XRP", "XRPUSDT"], ["DOGE", "DOGEUSDT"], ["BNB", "BNBUSDT"]];

// ── 조합 4개와 지표 값 그리드(순서 있는 축 → 이웃 평균으로 '튀는 값' 거르기) ──
const ST_GRID = { len: [7, 10, 14], mult: [2, 2.5, 3, 3.5, 4] };
export const COMBOS = [
  { key: "st_roc", ko: "슈퍼트렌드 + ROC", a: "슈퍼트렌드", b: "ROC", grid: { ...ST_GRID, roc: [5, 9, 14, 21] } },
  { key: "st_kvo", ko: "슈퍼트렌드 + 클링거", a: "슈퍼트렌드", b: "클링거", grid: { ...ST_GRID, kvo: [0.6, 0.8, 1, 1.5] } },
  { key: "vwma_macd", ko: "VWMA + MACD", a: "VWMA", b: "MACD", grid: { vwma: [10, 20, 50, 100, 200], macd: [0.66, 1, 1.5, 2] } },
  { key: "st_kst", ko: "슈퍼트렌드 + KST", a: "슈퍼트렌드", b: "KST", grid: { ...ST_GRID, kst: [0.5, 0.75, 1, 1.5] } },
];
export const COMBO_BY = Object.fromEntries(COMBOS.map(c => [c.key, c]));
// 손절·익절·청산 그리드 (레버리지마다 따로 고름)
export const EXIT_GRID = { k: [1, 1.5, 2, 2.5], rr: [1, 1.5, 2, 2.5, 3], ex: [0, 1, 2] };
export const EX_KO = ["손절·익절·시간만", "반대 신호에 청산", "추세 지표 전환에 청산"];

export function paramText(combo, p) {
  if (!p) return "";
  const st = p.len ? `ST(${p.len},${p.mult})` : "";
  if (combo === "st_roc") return `${st} · ROC(${p.roc})`;
  if (combo === "st_kvo") { const k = kvoLens(p.kvo); return `${st} · 클링거(${k.f},${k.s},${k.g})`; }
  if (combo === "st_kst") { const k = kstLens(p.kst); return `${st} · KST(${k.r.join("/")}·${k.m.join("/")}·${k.g})`; }
  if (combo === "vwma_macd") { const m = macdLens(p.macd); return `VWMA(${p.vwma}) · MACD(${m.f},${m.s},${m.g})`; }
  return JSON.stringify(p);
}
export const exitText = x => x ? `손절 ATR×${x.k} · 손익비 1:${x.rr} · ${EX_KO[x.ex]}` : "";
const kvoLens = s => ({ f: Math.round(34 * s), s: Math.round(55 * s), g: Math.max(3, Math.round(13 * s)) });
const kstLens = s => ({ r: [10, 15, 20, 30].map(x => Math.max(2, Math.round(x * s))), m: [10, 10, 10, 15].map(x => Math.max(2, Math.round(x * s))), g: Math.max(3, Math.round(9 * s)) });
const macdLens = s => ({ f: Math.max(2, Math.round(12 * s)), s: Math.max(4, Math.round(26 * s)), g: Math.max(3, Math.round(9 * s)) });

// ── 기본 계산 (NaN = 아직 값 없음) ──
const F = n => new Float64Array(n).fill(NaN);
function sma(x, n) { const o = F(x.length); let s = 0, c = 0;
  for (let i = 0; i < x.length; i++) { const v = x[i]; if (Number.isFinite(v)) { s += v; c++; } else { s = 0; c = 0; continue; }
    if (c > n) { s -= x[i - n]; c = n; } if (c === n) o[i] = s / n; }
  return o; }
function emaS(x, n, k) { const o = F(x.length); let e = NaN, s = 0, c = 0;
  for (let i = 0; i < x.length; i++) { const v = x[i]; if (!Number.isFinite(v)) continue;
    if (Number.isNaN(e)) { s += v; c++; if (c === n) { e = s / n; o[i] = e; } } else { e = v * k + e * (1 - k); o[i] = e; } }
  return o; }
const ema = (x, n) => emaS(x, n, 2 / (n + 1)), rma = (x, n) => emaS(x, n, 1 / n);
export function atr(D, n = 14) { const { h, l, c } = D, tr = F(c.length);
  for (let i = 0; i < c.length; i++) tr[i] = i ? Math.max(h[i] - l[i], Math.abs(h[i] - c[i - 1]), Math.abs(l[i] - c[i - 1])) : h[i] - l[i];
  return rma(tr, n); }
// 슈퍼트렌드(트레이딩뷰 ta.supertrend 와 같은 밴드 고정 규칙) → 방향 +1 상승 / −1 하락
export function supertrend(D, n, mult) {
  const { h, l, c } = D, a = atr(D, n), L = c.length, dir = new Int8Array(L); let up = NaN, dn = NaN, d = 0;
  for (let i = 0; i < L; i++) {
    if (!Number.isFinite(a[i])) continue;
    const m = (h[i] + l[i]) / 2; let u = m - mult * a[i], w = m + mult * a[i];
    if (Number.isFinite(up) && c[i - 1] > up) u = Math.max(u, up);
    if (Number.isFinite(dn) && c[i - 1] < dn) w = Math.min(w, dn);
    if (!d) d = c[i] > w ? 1 : -1; else if (d > 0) d = c[i] < u ? -1 : 1; else d = c[i] > w ? 1 : -1;
    up = u; dn = w; dir[i] = d;
  }
  return dir;
}
const sgn = (x, y) => { const o = new Int8Array(x.length); for (let i = 0; i < x.length; i++) { const d = x[i] - (y ? y[i] : 0); o[i] = Number.isFinite(d) ? (d > 0 ? 1 : d < 0 ? -1 : 0) : 0; } return o; };
function roc(c, n) { const o = F(c.length); for (let i = n; i < c.length; i++) o[i] = (c[i] - c[i - n]) / c[i - n] * 100; return o; }
// 클링거(트레이딩뷰 내장식): 거래량에 hlc3 변화 부호를 붙여 EMA 빠른−느린, 신호선 EMA
function klinger(D, s) { const { h, l, c, v } = D, k = kvoLens(s), sv = F(c.length);
  for (let i = 1; i < c.length; i++) sv[i] = (h[i] + l[i] + c[i]) - (h[i - 1] + l[i - 1] + c[i - 1]) >= 0 ? v[i] : -v[i];
  const f = ema(sv, k.f), sl = ema(sv, k.s), kvo = F(c.length); for (let i = 0; i < c.length; i++) kvo[i] = f[i] - sl[i];
  return { kvo, sig: ema(kvo, k.g) }; }
// KST(Know Sure Thing): ROC 4개를 각각 이동평균 → 1·2·3·4 가중 합, 신호선 SMA
function kst(c, s) { const k = kstLens(s), o = F(c.length), parts = k.r.map((r, j) => sma(roc(c, r), k.m[j]));
  for (let i = 0; i < c.length; i++) o[i] = parts[0][i] + 2 * parts[1][i] + 3 * parts[2][i] + 4 * parts[3][i];
  return { kst: o, sig: sma(o, k.g) }; }
function vwma(D, n) { const { c, v } = D, pv = F(c.length); for (let i = 0; i < c.length; i++) pv[i] = c[i] * v[i]; const a = sma(pv, n), b = sma(Float64Array.from(v), n), o = F(c.length); for (let i = 0; i < c.length; i++) o[i] = b[i] > 0 ? a[i] / b[i] : NaN; return o; }
function macd(c, s) { const m = macdLens(s), f = ema(c, m.f), sl = ema(c, m.s), line = F(c.length); for (let i = 0; i < c.length; i++) line[i] = f[i] - sl[i]; return { line, sig: ema(line, m.g) }; }

// 캔들 배열 → 계산용 열 묶음
export function cols(cs) { const n = cs.length, D = { n, t: new Float64Array(n), o: new Float64Array(n), h: new Float64Array(n), l: new Float64Array(n), c: new Float64Array(n), v: new Float64Array(n) };
  for (let i = 0; i < n; i++) { const b = cs[i]; D.t[i] = +b.t; D.o[i] = +b.o; D.h[i] = +b.h; D.l[i] = +b.l; D.c[i] = +b.c; D.v[i] = +b.v; }
  D.atr = atr(D, 14); return D; }
// 15분봉 → 30분봉(정각·30분 경계에 맞춰 2개씩 묶음, 마지막 미완성 묶음은 버림)
export function agg30(cs) { const out = [];
  for (let i = 0; i < cs.length; i++) { const b = cs[i]; if (b.t % 1800e3 !== 0) continue; const b2 = cs[i + 1]; if (!b2 || b2.t !== b.t + 900e3) continue;
    out.push({ t: b.t, o: b.o, h: Math.max(b.h, b2.h), l: Math.min(b.l, b2.l), c: b2.c, v: b.v + b2.v }); i++; }
  return out; }

// 조합 신호 방향 배열: dir[i] = 두 지표가 같은 방향이면 그 방향, 아니면 0 · A[i] = 추세 쪽 지표(슈퍼트렌드/VWMA) 방향
const _stC = new WeakMap();
function stOf(D, len, mult) { let m = _stC.get(D); if (!m) _stC.set(D, m = new Map()); const k = len + ":" + mult; if (!m.has(k)) m.set(k, supertrend(D, len, mult)); return m.get(k); }
export function comboDir(D, combo, p) {
  let A, B;
  if (combo === "vwma_macd") { A = sgn(D.c, vwma(D, p.vwma)); const m = macd(D.c, p.macd); B = sgn(m.line, m.sig); }
  else { A = stOf(D, p.len, p.mult);
    if (combo === "st_roc") B = sgn(roc(D.c, p.roc));
    else if (combo === "st_kvo") { const k = klinger(D, p.kvo); B = sgn(k.kvo, k.sig); }
    else { const k = kst(D.c, p.kst); B = sgn(k.kst, k.sig); } }
  const dir = new Int8Array(D.n); for (let i = 0; i < D.n; i++) dir[i] = A[i] && A[i] === B[i] ? A[i] : 0;
  return { dir, A };
}
export const isEntry = (dir, i) => i > 0 && dir[i] !== 0 && dir[i] !== dir[i - 1];
function entriesOf(dir) { const out = []; for (let i = 1; i < dir.length; i++) if (isEntry(dir, i)) out.push(i); return Int32Array.from(out); }

// 손절 거리(분수) — ATR×k, 하한 0.25%, 레버리지 상한 넘으면 null(진입 안 함)
export function slFrac(D, i, k, lev) { const a = D.atr[i]; if (!(a > 0)) return null; let s = k * a / D.c[i]; if (s > slCapOf(lev)) return null; return Math.max(SL_FLOOR, s); }
export const tpFrac = (s, rr) => rr * (s + FEE) + FEE;   // 순 손익비 rr (수수료 포함) — 앱 프레임워크와 같은 식

// ── 백테스트(다음 봉 시가 진입 · 같은 봉에 손절·익절 둘 다면 손절 먼저 · +1R 본절 · 수수료) ──
// 반환: 거래 [{i, j, t, side, R, why}]  (R = 손익 ÷ 위험금액, 손절 −1 · 익절 +rr)
export function simulate(D, sig, x, lev, from = 1, to = D.n) {
  const { o, h, l, c } = D, { dir, A } = sig, T = [], ent = sig.ent || (sig.ent = entriesOf(dir)); to = Math.min(to, D.n);
  let free = Math.max(1, from);
  for (let q = 0; q < ent.length; q++) {
    const i = ent[q]; if (i < free) continue; if (i >= to - 1) break;
    const side = dir[i], s = slFrac(D, i, x.k, lev); if (s == null) continue;
    const e = o[i + 1], tp = e * (1 + side * tpFrac(s, x.rr)); let sl = e * (1 - side * s), be = false, j = i + 1, px = null, why = "";
    for (; j < to; j++) {
      if (side > 0 ? l[j] <= sl : h[j] >= sl) { px = sl; why = be ? "본절" : "손절"; break; }
      if (side > 0 ? h[j] >= tp : l[j] <= tp) { px = tp; why = "익절"; break; }
      if (x.ex === 1 && dir[j] === -side) { px = c[j]; why = "반대신호"; break; }
      if (x.ex === 2 && A[j] === -side) { px = c[j]; why = "추세전환"; break; }
      if (j - i >= HOLD) { px = c[j]; why = "시간"; break; }
      if (!be && (side > 0 ? h[j] - e : e - l[j]) >= e * s) { be = true; sl = e * (1 + side * FEE); }
    }
    if (px == null) break;
    T.push({ i: i + 1, j, t: D.t[i + 1], side, R: ((px - e) / e * side - FEE) / (s + FEE), why });
    free = j;   // 청산한 봉의 마감 신호부터 다시 진입 가능(반대 신호 청산이면 바로 뒤집기)
  }
  return T;
}

// ── 채점: 연도(구간)별 평균 R → '꾸준함' 점수 = 구간 평균의 평균 − 0.5×구간 간 편차 (구간 표본이 적으면 0 쪽으로 줄임) ──
export function foldStats(T, bounds) { const f = bounds.slice(0, -1).map(() => ({ n: 0, s: 0, w: 0 }));
  for (const t of T) { let k = -1; for (let q = 0; q < f.length; q++) if (t.t >= bounds[q] && t.t < bounds[q + 1]) { k = q; break; } if (k < 0) continue; f[k].n++; f[k].s += t.R; if (t.R > 0) f[k].w++; }
  return f.map(x => ({ n: x.n, mean: x.n ? x.s / x.n : 0, wr: x.n ? x.w / x.n : 0 })); }
export function robust(folds, minN = 30) {
  const n = folds.reduce((a, f) => a + f.n, 0); if (n < minN) return { score: -9, n, mean: 0 };
  const m = folds.map(f => f.mean * f.n / (f.n + 20)), mu = m.reduce((a, b) => a + b, 0) / m.length, sd = Math.sqrt(m.reduce((a, b) => a + (b - mu) ** 2, 0) / m.length);
  const mean = folds.reduce((a, f) => a + f.mean * f.n, 0) / n;
  return { score: mu - 0.5 * sd, n, mean, pos: folds.filter(f => f.n >= 5 && f.mean > 0).length };
}
export const stat = T => { const n = T.length, s = T.reduce((a, t) => a + t.R, 0), w = T.filter(t => t.R > 0).length, sd = n > 1 ? Math.sqrt(T.reduce((a, t) => a + (t.R - s / n) ** 2, 0) / (n - 1)) : 0;
  return { n, mean: n ? +(s / n).toFixed(3) : 0, sum: +s.toFixed(1), wr: n ? Math.round(w / n * 100) : null, sd: +sd.toFixed(3) }; };

// 그리드 전부 나열 · 이웃(한 축만 한 칸 차이) 찾기
export function gridList(grid) { const ks = Object.keys(grid); let out = [{}];
  for (const k of ks) out = out.flatMap(p => grid[k].map(v => ({ ...p, [k]: v }))); return out; }
export function neighbors(grid, p) { const out = [];
  for (const k of Object.keys(grid)) { const a = grid[k], j = a.indexOf(p[k]); for (const d of [-1, 1]) if (a[j + d] !== undefined) out.push({ ...p, [k]: a[j + d] }); }
  return out; }
export const pkey = p => Object.keys(p).sort().map(k => k + "=" + p[k]).join(",");
// 이웃 평균(자기 2배 가중) — 한 점만 튀는 값(우연)보다 주변까지 좋은 '평평한 고원'을 고른다
export function plateau(grid, scores) { const out = new Map();
  for (const [k, v] of scores) { const p = v.p, nb = neighbors(grid, p).map(q => scores.get(pkey(q))?.score ?? -1);
    out.set(k, (2 * v.score + nb.reduce((a, b) => a + b, 0)) / (2 + nb.length)); }
  return out; }

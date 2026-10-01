// 누리 매크로: FRED 경제지표 CSV (API 키 없음) → 변환(전년比 · 전월比 · 수준) → 예측
// - 예측 모델: AR(p) (최소제곱, p 는 AIC 로 ≤12) · 차분 AR · 나이브 · 계절 나이브 · 드리프트.
//   롤링 원점 백테스트(과거 여러 시점에서 그때까지 데이터로만 예측) MAE 가 가장 작은 모델을 고르고,
//   80% 구간은 그 백테스트 오차의 10%·90% 분위수로 만든다.
// - 네트워크는 주입 가능한 fetchText(url) → 텍스트 (기본: engine.js webGet 을 필요할 때만 불러옴). Node 테스트에서는 직접 넣는다.
// - 의존성 없음. 브라우저와 Node 22 에서 import 로 쓴다.

const isNil = v => v === null || v === undefined;
const r4 = v => isNil(v) || !Number.isFinite(v) ? null : Math.round(v * 1e4) / 1e4;

export const FRED_CSV = id => `https://fred.stlouisfed.org/graph/fredgraph.csv?id=${encodeURIComponent(id)}`;
// 주요 지표: 이름 · 단위(변환 후) · 빈도(M 월 · Q 분기 · D 일) · 변환 (yoy 전년比% · mom 전기比% · diff 전기 대비 증감 · ann 전기比 연율% · level 수준)
export const MACRO_SET = {
  CPIAUCSL: {name: "소비자물가(CPI)", unit: "% 전년比", freq: "M", tf: "yoy"},
  CPILFESL: {name: "근원 CPI", unit: "% 전년比", freq: "M", tf: "yoy"},
  UNRATE: {name: "실업률", unit: "%", freq: "M", tf: "level"},
  PAYEMS: {name: "비농업 고용", unit: "천 명 전월 대비", freq: "M", tf: "diff"},
  FEDFUNDS: {name: "연방기금금리", unit: "%", freq: "M", tf: "level"},
  DGS10: {name: "미 국채 10년", unit: "%", freq: "D", tf: "level"},
  DGS2: {name: "미 국채 2년", unit: "%", freq: "D", tf: "level"},
  T10Y2Y: {name: "10년-2년 금리차", unit: "%p", freq: "D", tf: "level"},
  GDPC1: {name: "실질 GDP", unit: "% 전기比 연율", freq: "Q", tf: "ann"},
  INDPRO: {name: "산업생산", unit: "% 전년比", freq: "M", tf: "yoy"},
  RSAFS: {name: "소매판매", unit: "% 전월比", freq: "M", tf: "mom"},
  UMCSENT: {name: "미시간 소비자심리", unit: "지수", freq: "M", tf: "level"},
  DCOILWTICO: {name: "WTI 유가", unit: "$/배럴", freq: "D", tf: "level"},
  DTWEXBGS: {name: "달러지수(광의)", unit: "지수", freq: "D", tf: "level"},
  M2SL: {name: "M2 통화량", unit: "% 전년比", freq: "M", tf: "yoy"},
};
// 흔한 오타·옛 이름 → FRED id (소매판매 RSAFE → RSAFS)
export const MACRO_ALIAS = {RSAFE: "RSAFS"};
const PERIOD = {M: 12, Q: 4, W: 52, D: 0};
const NEXT_KO = {M: "다음 달", Q: "다음 분기", D: "다음 달 평균", W: "다음 달 평균"};

/* ============ FRED CSV ============ */
// "DATE,ID" 또는 "observation_date,ID" 헤더. 값 '.' 또는 빈칸 = 결측 (건너뜀)
export function parseFredCsv(text){
  const lines = String(text || "").replace(/^﻿/, "").split(/\r?\n/).filter(l => l.trim());
  if (!lines.length) throw new Error("FRED CSV 가 비었습니다");
  const head = lines[0].split(",").map(s => s.trim().replace(/^"|"$/g, ""));
  if (!/^(date|observation_date)$/i.test(head[0]) || head.length < 2) throw new Error("FRED CSV 형식이 아닙니다: " + lines[0].slice(0, 60));
  const points = [];
  let missing = 0;
  for (const l of lines.slice(1)){
    const [d, v] = l.split(",").map(s => s.trim().replace(/^"|"$/g, ""));
    if (!/^\d{4}-\d{2}-\d{2}$/.test(d || "")) continue;
    if (isNil(v) || v === "" || v === "." || !Number.isFinite(+v)){ missing++; continue; }
    points.push({date: d, value: +v});
  }
  return {id: head[1], points, missing};
}
// FRED 시리즈 내려받기. opts.fetchText(url) → 텍스트 (기본: engine.js webGet)
export async function fredSeries(id, {fetchText = null} = {}){
  id = String(id || "").trim().toUpperCase();
  id = MACRO_ALIAS[id] || id;
  if (!/^[A-Z0-9_]{1,40}$/.test(id)) throw new Error(`FRED id 형식 오류: ${id}`);
  const get = fetchText || (async url => (await import("./engine.js")).webGet(url));
  const text = await get(FRED_CSV(id));
  const r = parseFredCsv(text);
  if (!r.points.length) throw new Error(`${id}: 값이 없습니다`);
  return {id, meta: MACRO_SET[id] || null, points: r.points, missing: r.missing};
}

/* ============ 변환 ============ */
// 일·주간 자료 → 월평균 (날짜 = 그 달 1일)
export function toMonthly(points){
  const m = new Map();
  for (const p of points){ const k = p.date.slice(0, 7); const a = m.get(k) || [0, 0]; a[0] += p.value; a[1]++; m.set(k, a); }
  return [...m.entries()].sort((a, b) => a[0] < b[0] ? -1 : 1).map(([k, [s, c]]) => ({date: k + "-01", value: s / c, n: c}));
}
export function transform(points, tf, period = 12){
  const v = points.map(p => p.value), out = [];
  for (let i = 0; i < v.length; i++){
    let x;
    if (tf === "yoy") x = i >= period && v[i - period] ? (v[i] / v[i - period] - 1) * 100 : null;
    else if (tf === "mom") x = i >= 1 && v[i - 1] ? (v[i] / v[i - 1] - 1) * 100 : null;
    else if (tf === "diff") x = i >= 1 ? v[i] - v[i - 1] : null;
    else if (tf === "ann") x = i >= 1 && v[i - 1] > 0 && v[i] > 0 ? ((v[i] / v[i - 1]) ** 4 - 1) * 100 : null;
    else x = v[i];
    if (x !== null && Number.isFinite(x)) out.push({date: points[i].date, value: x});
  }
  return out;
}

/* ============ AR(p) ============ */
// 가우스 소거 (부분 피벗). A: n×n (배열의 배열), b: n → 해
function solve(A, b){
  const n = b.length, M = A.map((r, i) => [...r, b[i]]);
  for (let c = 0; c < n; c++){
    let piv = c; for (let r = c + 1; r < n; r++) if (Math.abs(M[r][c]) > Math.abs(M[piv][c])) piv = r;
    if (Math.abs(M[piv][c]) < 1e-12) return null;
    [M[c], M[piv]] = [M[piv], M[c]];
    for (let r = c + 1; r < n; r++){ const f = M[r][c] / M[c][c]; if (f) for (let k = c; k <= n; k++) M[r][k] -= f * M[c][k]; }
  }
  const x = new Array(n).fill(0);
  for (let r = n - 1; r >= 0; r--){ let s = M[r][n]; for (let k = r + 1; k < n; k++) s -= M[r][k] * x[k]; x[r] = s / M[r][r]; }
  return x;
}
// AR 적합: y_t = c + Σ φ_k y_{t-k}. maxP 까지의 공통 표본(t ≥ maxP)으로 p = 0..maxP 를 AIC 로 비교 → 최소 AIC 의 p
// (공통 표본이라 X'X 를 한 번만 만들고 앞쪽 부분행렬로 각 p 를 푼다). p 를 정해 주면(opts.p) 그 차수만.
export function fitAR(y, {maxP = 12, p = null} = {}){
  const N = y.length;
  maxP = Math.max(0, Math.min(p ?? maxP, Math.floor((N - 2) / 3)));
  const m = N - maxP;
  if (m < 3) return null;
  const K = maxP + 1, XtX = Array.from({length: K}, () => new Array(K).fill(0)), Xty = new Array(K).fill(0);
  let yy = 0;
  const row = new Array(K);
  for (let t = maxP; t < N; t++){
    row[0] = 1; for (let k = 1; k <= maxP; k++) row[k] = y[t - k];
    for (let a = 0; a < K; a++){ Xty[a] += row[a] * y[t]; for (let b = a; b < K; b++) XtX[a][b] += row[a] * row[b]; }
    yy += y[t] * y[t];
  }
  for (let a = 0; a < K; a++) for (let b = 0; b < a; b++) XtX[a][b] = XtX[b][a];
  let best = null;
  for (let q = p === null ? 0 : maxP; q <= maxP; q++){
    const A = XtX.slice(0, q + 1).map(r => r.slice(0, q + 1)), beta = solve(A, Xty.slice(0, q + 1));
    if (!beta) continue;
    let sse = yy; for (let a = 0; a <= q; a++) sse -= beta[a] * Xty[a];   // SSE = y'y - β'X'y
    sse = Math.max(sse, 1e-12 * (yy || 1));
    const aic = m * Math.log(sse / m) + 2 * (q + 1);
    if (!best || aic < best.aic) best = {p: q, c: beta[0], phi: beta.slice(1), sigma2: sse / Math.max(1, m - q - 1), aic, n: m};
  }
  return best;
}
// AR 반복 예측 h 단계
function arPath(y, fit, H){
  const hist = y.slice(-Math.max(1, fit.p)), out = [];
  for (let k = 0; k < H; k++){
    let v = fit.c; for (let j = 0; j < fit.p; j++) v += fit.phi[j] * hist[hist.length - 1 - j];
    out.push(v); hist.push(v);
  }
  return out;
}

/* ============ 예측 ============ */
// 모델: y(과거 값 배열) → H 단계 예측 배열
const MODELS = {
  naive: (y, H) => new Array(H).fill(y[y.length - 1]),
  drift: (y, H) => { const d = y.length > 1 ? (y[y.length - 1] - y[0]) / (y.length - 1) : 0; return Array.from({length: H}, (_, k) => y[y.length - 1] + d * (k + 1)); },
  snaive: (y, H, o) => Array.from({length: H}, (_, k) => y[y.length - o.season + (k % o.season)]),
  ar: (y, H, o) => { const f = fitAR(y, {maxP: o.maxP}); o._fit = f; return f ? arPath(y, f, H) : null; },
  // 차분 AR: 1차 차분에 AR → 누적해서 수준으로
  ar_diff: (y, H, o) => {
    const d = y.slice(1).map((v, i) => v - y[i]), f = fitAR(d, {maxP: o.maxP});
    o._fit = f; if (!f) return null;
    let last = y[y.length - 1]; return arPath(d, f, H).map(x => (last += x));
  },
};
const MODEL_KO = {naive: "나이브(직전 값)", drift: "드리프트", snaive: "계절 나이브", ar: "AR", ar_diff: "차분 AR"};
const quant = (a, q) => { const s = [...a].sort((x, y) => x - y), i = (s.length - 1) * q, lo = Math.floor(i); return s[lo] + (s[Math.ceil(i)] - s[lo]) * (i - lo); };

// series: 숫자 배열 또는 [{date, value}]. opts: {horizon=1(1~6), method:"auto"|모델 이름, season(0=없음), maxP=12, origins=36, window=360}
// 반환: {method, point[], lo[], hi[] (80%), forecast(=마지막 단계), mae, naiveMae, skill(1 - mae/naiveMae), models[], p, coefs}
export function forecast(series, opts = {}){
  const o = {horizon: 1, method: "auto", season: 0, maxP: 12, origins: 36, window: 360, ...opts};
  const H = Math.max(1, Math.min(6, Math.trunc(o.horizon)));
  let y = (series || []).map(p => typeof p === "number" ? p : p?.value).filter(v => typeof v === "number" && Number.isFinite(v));
  if (y.length > o.window) y = y.slice(-o.window);
  const N = y.length;
  if (N < 8) throw new Error(`예측에 값이 너무 적습니다 (${N}개)`);
  const season = o.season > 1 && N >= 3 * o.season ? Math.trunc(o.season) : 0;
  const names = o.method === "auto" ? ["naive", "drift", "ar", "ar_diff", ...(season ? ["snaive"] : [])] : [o.method];
  if (!names.every(m => Object.hasOwn(MODELS, m))) throw new Error(`알 수 없는 예측 방법: ${o.method} (auto/${Object.keys(MODELS).join("/")})`);
  if (!names.includes("naive")) names.push("naive");
  const ctx = {maxP: o.maxP, season};
  // 롤링 원점 백테스트: 원점 t 에서 y[0..t) 로만 적합 → y[t..t+H) 와 비교
  const minTrain = Math.max(12, 3 * Math.min(o.maxP, 6), season * 2);
  const origins = [];
  for (let t = N - 1; t >= minTrain && origins.length < o.origins; t--) origins.push(t);
  const res = {};
  for (const m of names){
    const err = Array.from({length: H}, () => []);
    for (const t of origins){
      const f = MODELS[m](y.slice(0, t), H, {...ctx});
      if (!f) continue;
      for (let k = 0; k < H && t + k < N; k++) err[k].push(y[t + k] - f[k]);
    }
    const all = err.flat();
    res[m] = {err, mae: all.length ? all.reduce((s, e) => s + Math.abs(e), 0) / all.length : Infinity, n: all.length};
  }
  const win = names.filter(m => Number.isFinite(res[m].mae)).sort((a, b) => res[a].mae - res[b].mae)[0] || "naive";
  const fc = {...ctx}, point = MODELS[win](y, H, fc) || MODELS.naive(y, H);
  // 80% 구간: 단계별 백테스트 오차의 10%·90% 분위수 (표본이 적으면 정규 근사)
  const lo = [], hi = [];
  for (let k = 0; k < H; k++){
    const e = res[win].err[k];
    if (e.length >= 8){ lo.push(point[k] + quant(e, 0.1)); hi.push(point[k] + quant(e, 0.9)); }
    else { const e1 = res[win].err[0], sd = e1.length > 1 ? Math.sqrt(e1.reduce((s, x) => s + x * x, 0) / e1.length) : Math.abs(point[k]) * 0.05 || 1; lo.push(point[k] - 1.2816 * sd * Math.sqrt(k + 1)); hi.push(point[k] + 1.2816 * sd * Math.sqrt(k + 1)); }
  }
  const naiveMae = res.naive.mae;
  return {method: win, label: MODEL_KO[win] + (fc._fit ? `(${fc._fit.p})` : ""), horizon: H, last: y[N - 1],
    point: point.map(r4), lo: lo.map(r4), hi: hi.map(r4), forecast: r4(point[H - 1]),
    mae: r4(res[win].mae), naiveMae: r4(naiveMae), skill: Number.isFinite(naiveMae) && naiveMae > 0 ? r4(1 - res[win].mae / naiveMae) : null,
    models: names.map(m => ({name: m, mae: r4(res[m].mae), n: res[m].n})).sort((a, b) => (a.mae ?? 1e99) - (b.mae ?? 1e99)),
    p: fc._fit?.p ?? null, coefs: fc._fit ? {c: r4(fc._fit.c), phi: fc._fit.phi.map(r4)} : null, nTest: origins.length};
}

// 예측 채점: pred {forecast|point, lo, hi, last(예측 당시 최근값)} · actual 숫자 → {absError, inside(구간 안), dirHit(방향 적중)}
export function scoreForecast(pred, actual){
  const f = typeof pred === "number" ? pred : Array.isArray(pred?.point) ? pred.point[0] : pred?.forecast;
  if (!Number.isFinite(f) || !Number.isFinite(actual)) return {absError: null, inside: null, dirHit: null};
  const lo = pred?.lo?.[0] ?? pred?.lo, hi = pred?.hi?.[0] ?? pred?.hi, base = pred?.last ?? pred?.base;
  return {absError: r4(Math.abs(actual - f)),
    inside: Number.isFinite(lo) && Number.isFinite(hi) ? actual >= lo && actual <= hi : null,
    dirHit: Number.isFinite(base) ? Math.sign(f - base) === Math.sign(actual - base) : null};
}

/* ============ 대시보드 ============ */
// 여러 지표를 내려받아 최근값 · 변화 · 추세 · 다음 기간 예측. opts: {ids, fetchText, horizon=1}
export async function macroDashboard({ids = Object.keys(MACRO_SET), fetchText = null, horizon = 1} = {}){
  const got = await Promise.allSettled(ids.map(id => fredSeries(id, {fetchText})));
  const rows = [], errors = [];
  got.forEach((g, i) => {
    if (g.status !== "fulfilled"){ errors.push({id: ids[i], error: g.reason?.message || String(g.reason)}); return; }
    try { rows.push(macroRow(g.value, horizon)); } catch(e){ errors.push({id: ids[i], error: e.message}); }
  });
  return {asOf: new Date().toISOString().slice(0, 10), rows, errors};
}
// 시리즈 하나 → 대시보드 행 {id, name, latest, date, change, trend, forecast, lo, hi, unit, ...}
export function macroRow({id, points, meta = null}, horizon = 1){
  meta = meta || MACRO_SET[id] || {name: id, unit: "", freq: guessFreq(points), tf: "level"};
  const daily = meta.freq === "D" || meta.freq === "W";
  const base = daily ? toMonthly(points) : points, per = PERIOD[meta.freq] || 12;
  const s = transform(base, meta.tf, daily ? 12 : per);
  if (s.length < 8) throw new Error(`${id}: 값이 너무 적습니다`);
  let latest, date, change;
  if (daily){   // 일간: 마지막 관측값, 변화는 약 한 달 전 관측값 대비
    const last = points[points.length - 1], ago = new Date(Date.parse(last.date) - 30 * 86400e3).toISOString().slice(0, 10);
    const prev = [...points].reverse().find(p => p.date <= ago);
    latest = last.value; date = last.date; change = prev ? last.value - prev.value : null;
  } else { latest = s[s.length - 1].value; date = s[s.length - 1].date.slice(0, meta.freq === "Q" ? 10 : 7); change = s[s.length - 1].value - s[s.length - 2].value; }
  // 추세: 최근 3기간 변화가 평소 1기간 변동(표준편차 × √3)의 1/4 보다 크면 상승/하락
  const v = s.map(p => p.value), d = v.slice(1).map((x, i) => x - v[i]);
  const sd = Math.sqrt(d.slice(-60).reduce((a, x) => a + x * x, 0) / Math.max(1, Math.min(60, d.length)));
  const d3 = v[v.length - 1] - v[v.length - 4];
  const trend = !Number.isFinite(d3) ? "?" : Math.abs(d3) < 0.25 * sd * Math.sqrt(3) ? "보합" : d3 > 0 ? "상승" : "하락";
  const f = forecast(s, {horizon, season: meta.season || 0});   // FRED 주요 지표는 계절조정 값이라 기본은 계절 모델 없음
  return {id, name: meta.name, unit: meta.unit, freq: meta.freq, latest: r4(latest), date, change: r4(change), trend,
    forecast: f.forecast, lo: f.lo[f.lo.length - 1], hi: f.hi[f.hi.length - 1], next: NEXT_KO[meta.freq] || "다음 기간",
    model: f.label, skill: f.skill, mae: f.mae, base: r4(v[v.length - 1])};
}
function guessFreq(points){
  if (points.length < 3) return "M";
  const g = (Date.parse(points[points.length - 1].date) - Date.parse(points[0].date)) / (points.length - 1) / 86400e3;
  return g < 10 ? "D" : g < 40 ? "M" : "Q";
}

// 프롬프트용 요약 (2000자 이내)
export function macroText(dash){
  const f = v => isNil(v) ? "?" : Math.abs(v) >= 1000 ? v.toFixed(0) : Math.abs(v) >= 100 ? v.toFixed(1) : v.toFixed(2);
  const sg = v => isNil(v) ? "?" : (v >= 0 ? "+" : "") + f(v);
  const lines = [`미국 매크로 (FRED, ${dash.asOf} 기준 · 예측 = 롤링 백테스트로 고른 모델, [80% 구간], 숙련도 = 나이브 대비 오차 감소율)`];
  for (const r of dash.rows){
    lines.push(`- ${r.name} ${f(r.latest)}${r.unit ? " " + r.unit : ""} (${r.date}, 변화 ${sg(r.change)}, ${r.trend}) → ${r.next} ${f(r.forecast)} [${f(r.lo)}~${f(r.hi)}] ${r.model}`
      + (r.skill === null ? "" : ` 숙련도 ${(r.skill * 100).toFixed(0)}%`));
  }
  if (dash.errors?.length) lines.push(`가져오기 실패: ${dash.errors.map(e => e.id).join(", ")}`);
  lines.push("주의: 매크로 예측 오차는 크다. 숙련도가 0 이하면 '직전 값 유지'보다 나을 게 없다는 뜻.");
  let s = lines.join("\n");
  if (s.length > 2000) s = s.slice(0, 1997) + "...";
  return s;
}

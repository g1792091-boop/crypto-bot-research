// 누리 퀀트: 백엔드 퀀트 도구(indicators.py · strategy.py · engine.py · backtest.py · improve.py 관문)의 브라우저 이식판
// - 의존성 없음. 브라우저와 Node 22 에서 import 로 쓴다.
// - 입력 캔들: [{t: ms, o, h, l, c, v}] (오래된 것 먼저). {time, open, high, low, close, volume} 이나 [t,o,h,l,c,v] 배열도 받는다.
// - 지표 공식은 TradingView(Pine ta.*)와 같다. 워밍업 구간은 null.
//   ta.ema / ta.rma: 첫 값은 SMA 시드 · ta.rsi / ta.atr: RMA(Wilder) · BB 표준편차: 모집단
// - 백엔드와 같은 캔들이면 지표·신호·거래·통계가 같게 나온다 (Python round 도 똑같이 흉내 냄).
// - type "custom" (사용자 수식 지표)은 customind.js 가 계산한다. customind.js 는 이 파일을 import 하지 않고,
//   아래 setIndProvider 로 computeInd 를 넘겨받는다 (한쪽 방향 import → 순환 없음).
import { parseExpr, evalExpr, setIndProvider } from "./customind.js";
import { INDICATORS as TV_IND } from "./terminal/ind.js";   // 차트 터미널 지표 146종 (tv_이름)

/* ============ 공용 ============ */
const isNil = v => v === null || v === undefined;
const nulls = n => new Array(n).fill(null);
const truthy = v => !isNil(v) && v !== 0 && !Number.isNaN(v);   // 파이썬 `if x:` (숫자)

// 파이썬 round(x, n): 정확한 2진 값 기준 반올림, 정확히 반이면 짝수 쪽 (toFixed 는 반이면 위쪽)
export function pyRound(x, nd = 0){
  if (isNil(x) || !Number.isFinite(x) || Math.abs(x) >= 1e21) return x;
  const s = Math.abs(x).toFixed(100);
  const [ip, fp] = s.split(".");
  if (/^50*$/.test(fp.slice(nd))){                      // 정확히 반
    const last = nd ? fp[nd - 1] : ip[ip.length - 1];
    if (+last % 2 === 0) return Number((x < 0 ? "-" : "") + ip + (nd ? "." + fp.slice(0, nd) : ""));
  }
  return Number(x.toFixed(nd));
}

// 봉 간격 → 초 (data/synthetic.py INTERVAL_SECONDS)
export const INTERVAL_SECONDS = {"1m":60,"3m":180,"5m":300,"15m":900,"30m":1800,"1h":3600,"2h":7200,"4h":14400,"6h":21600,"8h":28800,
  "12h":43200,"1d":86400,"3d":259200,"1w":604800,"1M":2592000,"1y":31536000};
// 전략에 쓸 수 있는 봉 간격 (strategy.py INTERVALS)
export const INTERVALS = ["1m","3m","5m","15m","30m","1h","2h","4h","6h","12h","1d","3d","1w","1M"];
// 내부 tf 표기(분·D·W)나 변형을 표준 간격으로 바꿔 받는다 — AI 가 interval:"60" 처럼 줘도 통과
const IV_ALIAS = {"1":"1m","3":"3m","5":"5m","15":"15m","30":"30m","60":"1h","120":"2h","240":"4h","360":"6h","720":"12h","1440":"1d","d":"1d","w":"1w","m":"1M","60m":"1h","120m":"2h","240m":"4h","1min":"1m","5min":"5m","15min":"15m","1hour":"1h","4hour":"4h","daily":"1d","day":"1d","weekly":"1w"};

// 초/밀리초 판단: secs를 주면 그대로 따르고, 아니면 값 크기로 (|t| < 1e11 이면 초 — 2001년 이전 ms 값을 초로 오해하지 않게 배열 단위로 판단)
const toMs = (t, secs) => {
  if (typeof t === "string" && !/^\s*-?\d+(\.\d+)?\s*$/.test(t)) return Date.parse(t);
  t = +t; return (secs ?? Math.abs(t) < 1e11) ? t * 1000 : t;
};
const rawT = b => Array.isArray(b) ? b[0] : (b?.t ?? b?.time);
// 배열의 가장 최근 시각으로 단위를 정한다 (지금 시각은 초 ≈ 1.8e9, ms ≈ 1.8e12)
const secsOf = arr => { const last = arr.length ? rawT(arr[arr.length - 1]) : null; if (last == null || (typeof last === "string" && !/^\s*-?\d+(\.\d+)?\s*$/.test(last))) return undefined; return Math.abs(+last) < 1e11; };
const _prepped = new WeakSet();
// 캔들 정규화 (숫자 변환·형식 통일). 이미 정규화한 배열은 그대로.
function prep(cs){
  if (!Array.isArray(cs)) throw new Error("캔들 배열이 필요합니다 ([{t,o,h,l,c,v}, ...])");
  if (_prepped.has(cs)) return cs;
  const secs = secsOf(cs);
  const out = cs.map(b => Array.isArray(b)
    ? {t: toMs(b[0], secs), o: +b[1], h: +b[2], l: +b[3], c: +b[4], v: +(b[5] ?? 0)}
    : {t: toMs(b.t ?? b.time, secs), o: +(b.o ?? b.open), h: +(b.h ?? b.high), l: +(b.l ?? b.low), c: +(b.c ?? b.close), v: +(b.v ?? b.volume ?? 0)});
  _prepped.add(out);
  return out;
}

/* ============ 지표 (indicators.py) ============ */
function srcOf(c, s){
  switch (s){
    case "hl2": return c.map(b => (b.h + b.l) / 2);
    case "hlc3": return c.map(b => (b.h + b.l + b.c) / 3);
    case "ohlc4": return c.map(b => (b.o + b.h + b.l + b.c) / 4);
    case "open": return c.map(b => b.o);
    case "high": return c.map(b => b.h);
    case "low": return c.map(b => b.l);
    case "close": return c.map(b => b.c);
    case "volume": return c.map(b => b.v);
  }
  throw new Error(`알 수 없는 가격 소스: ${s} (close/open/high/low/hl2/hlc3/ohlc4)`);
}

// SMA: null 을 만나면 창을 비우고 다시 쌓는다
function sma(x, n){
  const out = nulls(x.length), w = [];
  let s = 0, cnt = 0, head = 0;
  for (let i = 0; i < x.length; i++){
    const v = x[i];
    if (isNil(v)){ w.length = 0; head = 0; s = 0; cnt = 0; continue; }
    w.push(v); s += v; cnt++;
    if (cnt > n){ s -= w[head++]; cnt--; }
    if (cnt === n) out[i] = s / n;
  }
  return out;
}
// EMA/RMA 공통: null 은 건너뛰고, 처음 n개 평균으로 시드
function smoothed(x, n, alpha){
  const out = nulls(x.length), seed = [];
  let prev = null;
  for (let i = 0; i < x.length; i++){
    const v = x[i];
    if (isNil(v)) continue;
    if (prev === null){
      seed.push(v);
      if (seed.length === n){ let s = 0; for (const q of seed) s += q; prev = s / n; out[i] = prev; }
      continue;
    }
    prev = alpha * v + (1 - alpha) * prev;
    out[i] = prev;
  }
  return out;
}
const ema = (x, n) => smoothed(x, n, 2 / (n + 1));
const rma = (x, n) => smoothed(x, n, 1 / n);
function stdev(x, n){
  const m = sma(x, n), out = nulls(x.length);
  for (let i = 0; i < x.length; i++){
    if (m[i] === null) continue;
    let s = 0;
    for (let j = i - n + 1; j <= i; j++){ const d = x[j] - m[i]; s += d * d; }
    out[i] = Math.sqrt(s / n);
  }
  return out;
}
function rsi(x, n = 14){
  const L = x.length, up = nulls(L), dn = nulls(L);
  for (let i = 1; i < L; i++){ up[i] = Math.max(x[i] - x[i - 1], 0); dn[i] = Math.max(x[i - 1] - x[i], 0); }
  const au = rma(up, n), ad = rma(dn, n), out = nulls(L);
  for (let i = 0; i < L; i++){
    if (au[i] === null || ad[i] === null) continue;
    out[i] = ad[i] === 0 ? 100 : (au[i] === 0 ? 0 : 100 - 100 / (1 + au[i] / ad[i]));
  }
  return out;
}
function trueRange(c){
  return c.map((b, i) => {
    if (i === 0) return b.h - b.l;
    const pc = c[i - 1].c;
    return Math.max(b.h - b.l, Math.abs(b.h - pc), Math.abs(b.l - pc));
  });
}
const atr = (c, n = 14) => rma(trueRange(c), n);
const zipNN = (a, b, f) => a.map((p, i) => p !== null && b[i] !== null ? f(p, b[i]) : null);
function macd(x, fast = 12, slow = 26, signal = 9){
  const line = zipNN(ema(x, fast), ema(x, slow), (a, b) => a - b);
  const sig = ema(line, signal);
  return {line, signal: sig, hist: zipNN(line, sig, (a, b) => a - b)};
}
function bbands(x, n = 20, mult = 2){
  const m = sma(x, n), sd = stdev(x, n);
  const up = m.map((a, i) => a !== null ? a + mult * sd[i] : null);
  const lo = m.map((a, i) => a !== null ? a - mult * sd[i] : null);
  const width = m.map((a, i) => truthy(a) ? (up[i] - lo[i]) / a * 100 : null);
  return {upper: up, middle: m, lower: lo, width};
}
function highest(x, n){
  return x.map((_, i) => { if (i < n - 1) return null; let m = -Infinity; for (let j = i - n + 1; j <= i; j++) if (x[j] > m) m = x[j]; return m; });
}
function lowest(x, n){
  return x.map((_, i) => { if (i < n - 1) return null; let m = Infinity; for (let j = i - n + 1; j <= i; j++) if (x[j] < m) m = x[j]; return m; });
}
function stoch(c, n = 14, kS = 3, dS = 3){
  const hi = highest(c.map(b => b.h), n), lo = lowest(c.map(b => b.l), n);
  const raw = c.map((b, i) => { if (hi[i] === null) return null; const r = hi[i] - lo[i]; return r ? 100 * (b.c - lo[i]) / r : 50; });
  const k = sma(raw, kS);
  return {k, d: sma(k, dS)};
}
// ta.supertrend: direction -1 = 상승추세(라인이 가격 아래), +1 = 하락추세 (Pine 규약). trend = -direction
function supertrend(c, n = 10, mult = 3){
  const a = atr(c, n), L = c.length, line = nulls(L), direction = nulls(L);
  let pu = null, pd = null, ps = null;
  for (let i = 0; i < L; i++){
    if (a[i] === null) continue;
    const b = c[i], hl2 = (b.h + b.l) / 2;
    let up = hl2 - mult * a[i], dn = hl2 + mult * a[i];
    const pc = c[(i - 1 + L) % L].c;                  // 파이썬 c[i-1] (i=0 이면 마지막 봉 — 쓰이지 않음)
    if (pu !== null && pc >= pu) up = Math.max(up, pu);
    if (pd !== null && pc <= pd) dn = Math.min(dn, pd);
    let d;
    if (ps === null) d = 1;
    else if (ps === pd) d = b.c > dn ? -1 : 1;
    else d = b.c < up ? 1 : -1;
    const st = d === -1 ? up : dn;
    line[i] = st; direction[i] = d;
    pu = up; pd = dn; ps = st;
  }
  return {line, direction, trend: direction.map(d => d === null ? null : -d)};
}
function adx(c, n = 14){
  const pdm = [null], mdm = [null];
  for (let i = 1; i < c.length; i++){
    const up = c[i].h - c[i - 1].h, dn = c[i - 1].l - c[i].l;
    pdm.push(up > dn && up > 0 ? up : 0);
    mdm.push(dn > up && dn > 0 ? dn : 0);
  }
  const tr = [null, ...rma(trueRange(c).slice(1), n)];
  const p = rma(pdm, n), m = rma(mdm, n);
  const pdi = p.map((a, i) => a !== null && truthy(tr[i]) ? 100 * a / tr[i] : null);
  const mdi = m.map((a, i) => a !== null && truthy(tr[i]) ? 100 * a / tr[i] : null);
  const dx = pdi.map((a, i) => { const b = mdi[i]; if (a === null || b === null) return null; return (a + b) ? 100 * Math.abs(a - b) / (a + b) : 0; });
  return {adx: rma(dx, n), plus_di: pdi, minus_di: mdi};
}
function cci(c, n = 20){
  const tp = srcOf(c, "hlc3"), m = sma(tp, n), out = nulls(c.length);
  for (let i = 0; i < c.length; i++){
    if (m[i] === null) continue;
    let dev = 0; for (let j = i - n + 1; j <= i; j++) dev += Math.abs(tp[j] - m[i]);
    dev /= n;
    out[i] = dev ? (tp[i] - m[i]) / (0.015 * dev) : 0;
  }
  return out;
}
// UTC 일봉 기준으로 리셋되는 세션 VWAP
function vwap(c){
  let day = null, pv = 0, vol = 0;
  return c.map(b => {
    const d = Math.floor(b.t / 86400000);
    if (d !== day){ day = d; pv = 0; vol = 0; }
    const tp = (b.h + b.l + b.c) / 3;
    pv += tp * b.v; vol += b.v;
    return vol ? pv / vol : tp;
  });
}
function obv(c){
  let acc = 0;
  return c.map((b, i) => { if (i){ if (b.c > c[i - 1].c) acc += b.v; else if (b.c < c[i - 1].c) acc -= b.v; } return acc; });
}
function wma(x, n){
  const d = n * (n + 1) / 2, out = nulls(x.length);
  for (let i = n - 1; i < x.length; i++){
    let s = 0, ok = true;
    for (let k = 0; k < n; k++){ const v = x[i - n + 1 + k]; if (isNil(v)){ ok = false; break; } s += v * (k + 1); }
    if (ok) out[i] = s / d;
  }
  return out;
}
function hma(x, n){
  const h = Math.max(1, pyRound(n / 2)), s = Math.max(1, pyRound(n ** 0.5));
  return wma(zipNN(wma(x, h), wma(x, n), (p, q) => 2 * p - q), s);
}
function vwma(c, x, n){
  const pv = sma(x.map((v, i) => isNil(v) ? null : v * c[i].v), n), vv = sma(c.map(b => b.v), n);
  return pv.map((p, i) => p !== null && truthy(vv[i]) ? p / vv[i] : null);
}
function mfi(c, n = 14){
  const tp = srcOf(c, "hlc3"), out = nulls(c.length);
  for (let i = n; i < c.length; i++){
    let pos = 0, neg = 0;
    for (let j = i - n + 1; j <= i; j++){ if (tp[j] > tp[j - 1]) pos += tp[j] * c[j].v; }
    for (let j = i - n + 1; j <= i; j++){ if (tp[j] < tp[j - 1]) neg += tp[j] * c[j].v; }
    out[i] = neg === 0 ? 100 : 100 - 100 / (1 + pos / neg);
  }
  return out;
}
function willr(c, n = 14){
  const hi = highest(c.map(b => b.h), n), lo = lowest(c.map(b => b.l), n);
  return c.map((b, i) => hi[i] === null ? null : (hi[i] !== lo[i] ? -100 * (hi[i] - b.c) / (hi[i] - lo[i]) : -50));
}
function roc(x, n = 9){
  return x.map((v, i) => i >= n && !isNil(v) && truthy(x[i - n]) ? (v / x[i - n] - 1) * 100 : null);
}
function psar(c, start = 0.02, inc = 0.02, mx = 0.2){
  const L = c.length, out = nulls(L), trend = nulls(L);
  if (L < 3) return {value: out, trend};
  let up = c[1].c >= c[0].c, af = start, ep = up ? c[1].h : c[1].l, sar = up ? c[0].l : c[0].h;
  for (let i = 2; i < L; i++){
    sar = sar + af * (ep - sar);
    if (up){
      sar = Math.min(sar, c[i - 1].l, c[i - 2].l);
      if (c[i].l < sar){ up = false; sar = ep; ep = c[i].l; af = start; }
      else if (c[i].h > ep){ ep = c[i].h; af = Math.min(af + inc, mx); }
    } else {
      sar = Math.max(sar, c[i - 1].h, c[i - 2].h);
      if (c[i].h > sar){ up = true; sar = ep; ep = c[i].h; af = start; }
      else if (c[i].l < ep){ ep = c[i].l; af = Math.min(af + inc, mx); }
    }
    out[i] = sar; trend[i] = up ? 1 : -1;
  }
  return {value: out, trend};
}
function donchian(c, n = 20){
  const hi = highest(c.map(b => b.h), n), lo = lowest(c.map(b => b.l), n);
  return {upper: hi, lower: lo, middle: hi.map((a, i) => a !== null ? (a + lo[i]) / 2 : null)};
}
function keltner(c, n = 20, mult = 2){
  const m = ema(srcOf(c, "close"), n), a = atr(c, n);
  return {upper: zipNN(m, a, (p, q) => p + mult * q), middle: m, lower: zipNN(m, a, (p, q) => p - mult * q)};
}
function stochrsi(x, n = 14, kS = 3, dS = 3){
  const r = rsi(x, n), raw = nulls(x.length);
  for (let i = 0; i < x.length; i++){
    if (i < n - 1) continue;
    let h = -Infinity, lo = Infinity, ok = true;
    for (let j = Math.max(0, i - n + 1); j <= i; j++){ const v = r[j]; if (v === null){ ok = false; break; } if (v > h) h = v; if (v < lo) lo = v; }
    if (!ok) continue;
    raw[i] = h !== lo ? 100 * (r[i] - lo) / (h - lo) : 50;
  }
  const k = sma(raw, kS);
  return {k, d: sma(k, dS)};
}
// 일목: span_a/b 는 base-1 봉 앞으로 민 값 (= 지금 봉 위치의 구름)
function ichimoku(c, conv = 9, base = 26, span = 52){
  const H = c.map(b => b.h), Lw = c.map(b => b.l);
  const mid = n => { const h = highest(H, n), l = lowest(Lw, n); return h.map((a, i) => a !== null ? (a + l[i]) / 2 : null); };
  const t = mid(conv), k = mid(base), sb = mid(span);
  const sa = zipNN(t, k, (a, b) => (a + b) / 2);
  const sh = x => x.map((_, i) => i >= base - 1 ? x[i - (base - 1)] : null);
  return {tenkan: t, kijun: k, span_a: sh(sa), span_b: sh(sb)};
}
function cmf(c, n = 20){
  const mfv = c.map(b => b.h !== b.l ? ((b.c - b.l) - (b.h - b.c)) / (b.h - b.l) * b.v : 0);
  const a = sma(mfv, n), v = sma(c.map(b => b.v), n);
  return a.map((p, i) => p !== null && truthy(v[i]) ? p / v[i] : null);
}
function aroon(c, n = 25){
  const up = nulls(c.length), dn = nulls(c.length);
  for (let i = n; i < c.length; i++){
    let hi = 0, lo = 0;
    for (let k = 0; k <= n; k++){ const b = c[i - n + k]; if (b.h >= c[i - n + hi].h) hi = k; if (b.l <= c[i - n + lo].l) lo = k; }   // 같으면 최근 봉
    up[i] = 100 * hi / n; dn[i] = 100 * lo / n;
  }
  return {up, down: dn};
}
// ATR 추적 손절선 (UT Bot 계열). trend: +1 롱 구간 / -1 숏 구간
function atrStop(c, n = 14, mult = 3){
  const a = atr(c, n), line = nulls(c.length), trend = nulls(c.length);
  let prev = null, d = 1;
  for (let i = 0; i < c.length; i++){
    if (a[i] === null) continue;
    const b = c[i], lo = b.c - mult * a[i], hi = b.c + mult * a[i];
    if (prev === null) prev = lo;
    else if (d === 1){ if (b.c < prev){ d = -1; prev = hi; } else prev = Math.max(prev, lo); }
    else if (b.c > prev){ d = 1; prev = lo; }
    else prev = Math.min(prev, hi);
    line[i] = prev; trend[i] = d;
  }
  return {line, trend};
}

// 전략 DSL 지표 레지스트리: type → 출력 · 기본 파라미터 · 설명
// 출력이 여러 개면 조건식에서 "<id>.<출력>" 으로 참조 (예: "macd.hist", "bb.upper")
export const IND_REGISTRY = {
  sma: {outputs: ["value"], defaults: {length: 20, source: "close"}, desc: "단순이동평균"},
  ema: {outputs: ["value"], defaults: {length: 20, source: "close"}, desc: "지수이동평균"},
  rsi: {outputs: ["value"], defaults: {length: 14, source: "close"}, desc: "RSI (0~100, Wilder)"},
  macd: {outputs: ["line", "signal", "hist"], defaults: {fast: 12, slow: 26, signal: 9, source: "close"}, desc: "MACD"},
  bb: {outputs: ["upper", "middle", "lower", "width"], defaults: {length: 20, mult: 2.0, source: "close"}, desc: "볼린저밴드 (width = 밴드폭 %)"},
  atr: {outputs: ["value"], defaults: {length: 14}, desc: "ATR"},
  stoch: {outputs: ["k", "d"], defaults: {length: 14, k_smooth: 3, d_smooth: 3}, desc: "스토캐스틱"},
  supertrend: {outputs: ["line", "trend"], defaults: {length: 10, mult: 3.0}, desc: "슈퍼트렌드 (trend: +1 상승, -1 하락)"},
  adx: {outputs: ["adx", "plus_di", "minus_di"], defaults: {length: 14}, desc: "ADX/DMI"},
  cci: {outputs: ["value"], defaults: {length: 20}, desc: "CCI"},
  vwap: {outputs: ["value"], defaults: {}, desc: "세션 VWAP (UTC 리셋)"},
  obv: {outputs: ["value"], defaults: {}, desc: "OBV"},
  highest: {outputs: ["value"], defaults: {length: 20, source: "high"}, desc: "N봉 최고값 (돈치안 상단)"},
  lowest: {outputs: ["value"], defaults: {length: 20, source: "low"}, desc: "N봉 최저값 (돈치안 하단)"},
  volume_sma: {outputs: ["value"], defaults: {length: 20}, desc: "거래량 이동평균"},
  wma: {outputs: ["value"], defaults: {length: 20, source: "close"}, desc: "가중이동평균"},
  hma: {outputs: ["value"], defaults: {length: 55, source: "close"}, desc: "헐 이동평균"},
  vwma: {outputs: ["value"], defaults: {length: 20, source: "close"}, desc: "거래량 가중 이동평균"},
  mfi: {outputs: ["value"], defaults: {length: 14}, desc: "MFI (자금 흐름)"},
  willr: {outputs: ["value"], defaults: {length: 14}, desc: "윌리엄스 %R (-100~0)"},
  roc: {outputs: ["value"], defaults: {length: 9, source: "close"}, desc: "ROC 변화율 %"},
  psar: {outputs: ["value", "trend"], defaults: {}, desc: "파라볼릭 SAR (trend: +1 상승, -1 하락)"},
  donchian: {outputs: ["upper", "middle", "lower"], defaults: {length: 20}, desc: "돈치안 채널"},
  keltner: {outputs: ["upper", "middle", "lower"], defaults: {length: 20, mult: 2.0}, desc: "켈트너 채널"},
  stochrsi: {outputs: ["k", "d"], defaults: {length: 14, k_smooth: 3, d_smooth: 3, source: "close"}, desc: "스토캐스틱 RSI"},
  ichimoku: {outputs: ["tenkan", "kijun", "span_a", "span_b"], defaults: {fast: 9, slow: 26, length: 52}, desc: "일목균형표 (fast=전환선, slow=기준선, length=선행스팬B · span_a/b = 지금 봉 위치의 구름)"},
  cmf: {outputs: ["value"], defaults: {length: 20}, desc: "차이킨 자금 흐름"},
  aroon: {outputs: ["up", "down"], defaults: {length: 25}, desc: "아룬 (0~100)"},
  atr_stop: {outputs: ["line", "trend"], defaults: {length: 14, mult: 3.0}, desc: "ATR 추적 손절선 (UT Bot 계열, trend ±1)"},
  // ── ICT/SMC · 세션 프리미티브 (가격구조·시간 기반, 신호형 ±1/값) ──
  bos: {outputs: ["value", "trend"], defaults: {length: 20}, desc: "구조 돌파 BOS/MSS (value +1=상승 구조돌파·-1=하락, trend=최근 구조 방향 ±1). close 가 직전 N봉 스윙고/저 돌파"},
  fvg: {outputs: ["value"], defaults: {}, desc: "Fair Value Gap (value +1=상승 FVG 생성봉·-1=하락 FVG, 0=없음). 3봉 가격 불균형"},
  ob: {outputs: ["value"], defaults: {length: 14, mult: 1.2}, desc: "Order Block 리테스트 (value +1=상승 OB 존 되돌림·-1=하락 OB). 변위 전 마지막 반대봉 존 재진입"},
  sweep: {outputs: ["value"], defaults: {length: 10}, desc: "유동성 스윕/스탑헌트 반전 (value +1=스윙저점 쓸고 복귀=롱·-1=스윙고점 쓸고 복귀=숏)"},
  disp: {outputs: ["value"], defaults: {length: 14, mult: 1.2}, desc: "변위 Displacement (value +1=큰 양봉(몸통≥mult×ATR)·-1=큰 음봉·0=보통)"},
  premium: {outputs: ["value"], defaults: {length: 50}, desc: "프리미엄/디스카운트 (value 0~1, 최근 N봉 스윙범위 내 close 위치. <0.3 디스카운트=매수존, >0.7 프리미엄=매도존)"},
  session: {outputs: ["value"], defaults: {start: 13, end: 16}, desc: "세션/킬존 필터 (value +1=봉의 UTC시각이 [start,end) 안·0=밖). 런던 7~10, 뉴욕AM 13~16, 아시아 0~3 (UTC)"},
  // 사용자 수식 지표 (customind.js): {"id":"x","type":"custom","expr":"(close - ema(close,20)) / ind(\"atr\",{length:14})"}
  custom: {outputs: ["value"], defaults: {}, desc: "사용자 수식 지표 (expr 에 수식 — 문법은 customind.js CUSTOM_DOC)"},
};
// custom 수식에서 데이터가 없어도 되는 외부 시리즈 이름 (없으면 null 시리즈): 파생 필드 · ml_* · ext_*
// 허용 외부/파생 변수: ml_*·ext_* · 알려진 파생필드 · funding/oi/taker/long_short/basis/premium/cvd 계열(백테스트 null)
const EXT_NAME = name => DERIV_FIELDS.includes(name) || /^(?:ml|ext)_\w+$/.test(name) || /^(?:funding|oi|taker|long_short|basis|premium|cvd)\w*$/.test(name);

// 지표 계산. 항상 {출력이름: 시리즈} 형태 (indicators.compute)
// 차트 터미널 지표(terminal/ind.js)를 전략·수식에서도: type "tv_<id>" · 출력 value(첫 선) p1~p4(다음 선) · 신호형은 +1/-1
// 외부 데이터가 필요한 것(OI·펀딩·청산·BTC 대비 등)과 화면 전용(볼륨 프로파일)은 뺀다
// 차트 터미널 지표 전부를 전략에서 쓸 수 있게 한다. 외부/파생 데이터(펀딩·OI·롱숏·청산·거래소프리미엄 등)가
// 필요한 지표는 데이터가 없으면 tvCompute 가 조용히 null 을 돌려주고, 그 조건은 normalizeSpec 뒤처리에서 자동으로 빠진다.
const TV_SKIP = new Set();
const TV_OUTS = ["value", "p1", "p2", "p3", "p4"];
for (const [id, d] of Object.entries(TV_IND)) if (!TV_SKIP.has(id)) IND_REGISTRY["tv_" + id] = {outputs: TV_OUTS, defaults: {...(d.params || {})}, desc: d.name, tv: id};
export const TV_TYPES = Object.keys(IND_REGISTRY).filter(k => k.startsWith("tv_"));
function tvCompute(c, id, p){
  const bars = c.map(b => ({time: Math.floor(b.t / 1000), open: b.o, high: b.h, low: b.l, close: b.c, volume: b.v,
    ...(b.taker_buy != null ? {taker_buy: b.taker_buy} : {}), ...(b.funding != null ? {funding: b.funding} : {}), ...(b.oi != null ? {oi: b.oi} : {})}));
  let r = {};
  try { r = TV_IND[id].compute(bars, p, {}) || {}; } catch(e){ r = {}; }   // 외부 데이터 없는 지표는 조용히 빈 결과 → 조건 자동 드롭(하드 오류 방지)
  const plots = (r.plots || []).filter(x => Array.isArray(x.data) && x.data.length === c.length && x.type !== "boxes");
  const out = {};
  TV_OUTS.forEach((k, i) => { const pl = plots[i]; out[k] = pl ? pl.data.map(v => v == null ? null : typeof v === "object" ? (Number.isFinite(+v.dir) ? +v.dir : Number.isFinite(+v.value) ? +v.value : null) : Number.isFinite(+v) ? +v : null) : c.map(() => null); });
  return out;
}
export function tvCatalogText(){
  return "차트 터미널 지표 " + TV_TYPES.length + "종 (type \"tv_이름\", 출력 value=첫 선 · p1~p4=다음 선, 신호형은 +1 매수/-1 매도, 파라미터 이름은 아래 괄호): " +
    TV_TYPES.map(k => `${k}(${Object.keys(IND_REGISTRY[k].defaults).join(",")})`).join(" ");
}
// ── ICT/SMC · 세션 프리미티브 계산 (OHLCV·시각만으로) ──
function bos(c, n){
  const val = nulls(c.length), tr = nulls(c.length); let dir = 0;
  for (let i = 0; i < c.length; i++){
    if (i < n){ val[i] = 0; tr[i] = dir; continue; }
    let hh = -Infinity, ll = Infinity;
    for (let j = i - n; j < i; j++){ if (c[j].h > hh) hh = c[j].h; if (c[j].l < ll) ll = c[j].l; }
    let v = 0;
    if (c[i].c > hh){ v = 1; dir = 1; } else if (c[i].c < ll){ v = -1; dir = -1; }
    val[i] = v; tr[i] = dir;
  }
  return {value: val, trend: tr};
}
function fvg(c){
  const val = nulls(c.length);
  for (let i = 0; i < c.length; i++){
    if (i < 2){ val[i] = 0; continue; }
    if (c[i].l > c[i - 2].h) val[i] = 1; else if (c[i].h < c[i - 2].l) val[i] = -1; else val[i] = 0;
  }
  return val;
}
function displacement(c, n, mult){
  const a = atr(c, n), val = nulls(c.length);
  for (let i = 0; i < c.length; i++){
    const body = Math.abs(c[i].c - c[i].o), th = (a[i] || 0) * mult;
    val[i] = (th > 0 && body >= th) ? (c[i].c >= c[i].o ? 1 : -1) : 0;
  }
  return val;
}
function orderBlock(c, n, mult){
  const disp = displacement(c, n, mult), val = nulls(c.length); let bull = null, bear = null;
  for (let i = 0; i < c.length; i++){
    val[i] = 0;
    if (bull && c[i].l <= bull.hi && c[i].c >= bull.lo) val[i] = 1;
    if (bear && c[i].h >= bear.lo && c[i].c <= bear.hi) val[i] = -1;
    if (disp[i] === 1 && i >= 1){ const p = c[i - 1]; bull = {lo: Math.min(p.o, p.c, p.l), hi: Math.max(p.o, p.c, p.h)}; }
    else if (disp[i] === -1 && i >= 1){ const p = c[i - 1]; bear = {lo: Math.min(p.o, p.c, p.l), hi: Math.max(p.o, p.c, p.h)}; }
  }
  return val;
}
function sweep(c, n){
  const val = nulls(c.length);
  for (let i = 0; i < c.length; i++){
    if (i < n){ val[i] = 0; continue; }
    let hh = -Infinity, ll = Infinity;
    for (let j = i - n; j < i; j++){ if (c[j].h > hh) hh = c[j].h; if (c[j].l < ll) ll = c[j].l; }
    if (c[i].l < ll && c[i].c > ll) val[i] = 1; else if (c[i].h > hh && c[i].c < hh) val[i] = -1; else val[i] = 0;
  }
  return val;
}
function premium(c, n){
  const val = nulls(c.length);
  for (let i = 0; i < c.length; i++){
    if (i < n){ val[i] = 0.5; continue; }
    let hh = -Infinity, ll = Infinity;
    for (let j = i - n; j <= i; j++){ if (c[j].h > hh) hh = c[j].h; if (c[j].l < ll) ll = c[j].l; }
    val[i] = hh > ll ? (c[i].c - ll) / (hh - ll) : 0.5;
  }
  return val;
}
function session(c, start, end){
  const val = nulls(c.length);
  for (let i = 0; i < c.length; i++){
    const h = new Date(c[i].t).getUTCHours(), inw = start <= end ? (h >= start && h < end) : (h >= start || h < end);
    val[i] = inw ? 1 : 0;
  }
  return val;
}
export function computeInd(candles, type, params = {}){
  const R = IND_REGISTRY[type];
  if (!R) throw new Error(`지원하지 않는 지표: ${type}`);
  const c = prep(candles);
  const p = {...R.defaults};
  for (const [k, v] of Object.entries(params || {})) if (!isNil(v) && k !== "id" && k !== "type") p[k] = v;
  if (R.tv) return tvCompute(c, R.tv, p);
  // source: 가격 필드면 그 시리즈, 다른 지표 출력이면 buildSeries 가 넘겨준 _srcSeries, 해석 불가면 close 로 폴백(오류 없음)
  let src = null;
  if (Array.isArray(p._srcSeries)) src = p._srcSeries;
  else if ("source" in p){ try { src = srcOf(c, String(p.source).toLowerCase()); } catch(e){ src = srcOf(c, "close"); } }
  const n = Math.trunc(Number(p.length ?? 14)), I = k => Math.trunc(Number(p[k])), F = k => Number(p[k]);
  switch (type){
    case "sma": return {value: sma(src, n)};
    case "ema": return {value: ema(src, n)};
    case "rsi": return {value: rsi(src, n)};
    case "macd": return macd(src, I("fast"), I("slow"), I("signal"));
    case "bb": return bbands(src, n, F("mult"));
    case "atr": return {value: atr(c, n)};
    case "stoch": return stoch(c, n, I("k_smooth"), I("d_smooth"));
    case "supertrend": { const st = supertrend(c, n, F("mult")); return {line: st.line, trend: st.trend}; }
    case "adx": return adx(c, n);
    case "cci": return {value: cci(c, n)};
    case "vwap": return {value: vwap(c)};
    case "obv": return {value: obv(c)};
    case "highest": return {value: highest(src, n)};
    case "lowest": return {value: lowest(src, n)};
    case "volume_sma": return {value: sma(c.map(b => b.v), n)};
    case "wma": return {value: wma(src, n)};
    case "hma": return {value: hma(src, n)};
    case "vwma": return {value: vwma(c, src, n)};
    case "mfi": return {value: mfi(c, n)};
    case "willr": return {value: willr(c, n)};
    case "roc": return {value: roc(src, n)};
    case "psar": return psar(c);
    case "donchian": return donchian(c, n);
    case "keltner": return keltner(c, n, F("mult"));
    case "stochrsi": return stochrsi(src, n, I("k_smooth"), I("d_smooth"));
    case "ichimoku": return ichimoku(c, I("fast"), I("slow"), n);
    case "cmf": return {value: cmf(c, n)};
    case "aroon": return aroon(c, n);
    case "atr_stop": return atrStop(c, n, F("mult"));
    case "bos": return bos(c, n);
    case "fvg": return {value: fvg(c)};
    case "ob": return {value: orderBlock(c, n, F("mult"))};
    case "sweep": return {value: sweep(c, n)};
    case "disp": return {value: displacement(c, n, F("mult"))};
    case "premium": return {value: premium(c, n)};
    case "session": return {value: session(c, I("start"), I("end"))};
    case "custom": try { return {value: evalExpr(String(p.expr ?? ""), c, p.extra || {}, {allow: EXT_NAME, computeInd})}; } catch(e){ return {value: nulls(c.length)}; }   // 수식 오류여도 백테스트 멈추지 않게 null
  }
}
setIndProvider({computeInd, registry: IND_REGISTRY});   // customind.js 의 ind() 가 쓰는 연결

/* ============ 전략 DSL (strategy.py) ============ */
// 피연산자(left/right) 문법:
//   가격/거래량: open, high, low, close, volume, hl2, hlc3, ohlc4
//   지표: "<id>" (출력 1개 · value · line 이 있는 지표) 또는 "<id>.<출력>" (예: "macd.hist", "bb.lower", "st.trend")
//   파생 데이터: funding (펀딩비 %), oi, oi_change_pct (직전 봉 대비 OI %), long_short — deriv 없으면 null → 조건 거짓
//   과거 값: 뒤에 [n] (예: "close[1]") · 숫자: "30" · 배수: "<참조>*<숫자>" (예: "vol_ma*2")
const REF = /^([A-Za-z_][\w.]*)(?:\[(\d+)\])?$/;
const PRICE_FIELDS = ["open", "high", "low", "close", "volume", "hl2", "hlc3", "ohlc4"];
// 파생/시장 필드(백테스트에선 데이터가 없어 null 로 채워짐 — 전략이 실패하지 않고 그 조건만 안 걸림). AI 가 자주 쓰는 변형 이름도 포함.
const DERIV_FIELDS = ["funding", "funding_rate", "funding_rate_pct", "funding_rate_8h_pct", "funding_8h", "funding_8h_pct", "oi", "oi_change_pct", "oi_change", "oi_delta", "long_short", "long_short_ratio", "taker_ratio", "taker_buy_ratio", "basis", "premium", "cvd"];
const OPS = [">", "<", ">=", "<=", "==", "!=", "crosses_above", "crosses_below", "rising", "falling"];
const OP_ALIAS = {"crossover": "crosses_above", "cross_above": "crosses_above", "crosses_over": "crosses_above", "cross_up": "crosses_above",
  "crossunder": "crosses_below", "cross_below": "crosses_below", "crosses_under": "crosses_below", "cross_down": "crosses_below",
  "gt": ">", "lt": "<", "gte": ">=", "lte": "<=", "=>": ">=", "=<": "<=", "≥": ">=", "≤": "<=",
  "==": "==", "=": "==", "eq": "==", "equals": "==", "is": "==", "!=": "!=", "<>": "!=", "ne": "!=", "neq": "!=", "≠": "!="};
const INT_PARAMS = ["length", "fast", "slow", "signal", "k_smooth", "d_smooth"];
const SOURCES = ["close", "open", "high", "low", "hl2", "hlc3", "ohlc4", "volume"];
const IND_ALIAS = {bollinger: "bb", bbands: "bb", vol_sma: "volume_sma", volume_ma: "volume_sma", williams: "willr", williams_r: "willr",
  stochastic: "stoch", stoch_rsi: "stochrsi", ichi: "ichimoku", parabolic_sar: "psar", sar: "psar", ut_bot: "atr_stop", dmi: "adx", st: "supertrend", super_trend: "supertrend"};
// 차트 터미널 지표(tv_*)를 '맨 이름'으로도 쓸 수 있게 별칭 등록: 예) qqe → tv_qqe. 단, 네이티브 지표(ema·rsi·macd 등)는 덮어쓰지 않는다.
// → AI 가 만든 전략이 터미널 지표를 prefix 없이 써도 백테스트에서 바로 인식된다(차트 터미널 보조지표 전부 사용 가능).
{
  const NATIVE = new Set(Object.keys(IND_REGISTRY).filter(k => !k.startsWith("tv_")));
  for (const k of TV_TYPES){ const bare = k.slice(3); if (!NATIVE.has(bare) && !(bare in IND_ALIAS)) IND_ALIAS[bare] = k; }
}

// 파이썬 float(x) 로 읽히는 문자열인가
const NUM_RE = /^[+-]?(?:(?:\d(?:_?\d)*)(?:\.(?:\d(?:_?\d)*)?)?|\.\d(?:_?\d)*)(?:[eE][+-]?\d(?:_?\d)*)?$/;
const SPECIAL_RE = /^[+-]?(?:inf|infinity|nan)$/i;
const isNum = x => { const s = String(x).trim(); return NUM_RE.test(s) || SPECIAL_RE.test(s); };
const toNum = x => { const s = String(x).trim().replace(/_/g, ""); if (SPECIAL_RE.test(s)){ const m = s.toLowerCase().replace(/^[+-]/, ""); return m === "nan" ? NaN : (s[0] === "-" ? -Infinity : Infinity); } return Number(s); };

export const RISK_DEFAULTS = {
  leverage: 3,               // 레버리지 배수
  position_pct: 20,          // 진입 시 증거금으로 쓰는 자본 비율 %
  stop_loss_pct: null,       // 진입가 대비 손절 % (가격 기준)
  take_profit_pct: null,     // 진입가 대비 익절 %
  atr_stop_mult: null,       // ATR(14) x 배수 손절
  atr_tp_mult: null,         // ATR(14) x 배수 익절
  trailing_stop_pct: null,   // 고점(저점) 대비 추적 손절 %
  fee_pct: 0.04,             // 편도 수수료 % (바이낸스 테이커)
  slippage_pct: 0.01,        // 편도 슬리피지 %
  funding_rate_8h_pct: 0.01, // 8시간당 가정 펀딩비 % (롱 지불, 숏 수령)
  allow_reverse: true,       // 반대 신호 시 즉시 스위칭
  // ↓ freqtrade 방식 (규칙만 재구현, 코드 복사 없음)
  minimal_roi: null,         // 시간별 목표 수익표 {"0": 6, "60": 3, "240": 1, "720": 0} = 보유 N분 이상이면 증거금 대비 수익 % (레버리지·수수료 포함)가 값을 넘을 때 익절
  trailing_stop_positive_pct: null,         // 수익이 오프셋을 넘은 뒤에 쓸 추적손절 거리 % (가격 기준)
  trailing_stop_positive_offset_pct: null,  // 이 % (가격 기준) 이상 유리해지면 위 거리로 추적 시작
  protections: null,         // 보호장치 목록 [{method:"StoplossGuard"|"MaxDrawdown"|"CooldownPeriod"|"LowProfitPairs", lookback_candles, stop_candles, trade_limit, required_profit_pct, max_allowed_drawdown_pct}]
};
const PROT_METHODS = ["StoplossGuard", "MaxDrawdown", "CooldownPeriod", "LowProfitPairs"];

// 전략에서 실제로 만들어지는 시리즈 이름들 (build_series 와 같은 규칙)
function seriesNames(spec){
  const names = new Set([...PRICE_FIELDS, ...DERIV_FIELDS]);
  for (const ind of spec.indicators){
    const outs = IND_REGISTRY[ind.type].outputs;
    for (const o of outs) names.add(`${ind.id}.${o}`);
    if (outs.length === 1 || outs.includes("value") || outs.includes("line")) names.add(ind.id);
  }
  return names;
}
// 피연산자 문법 검사 (문제 문자열 또는 null)
function checkOperand(tok, names){
  tok = String(tok).trim();
  if (!tok) return "빈 피연산자";
  if (isNum(tok)) return null;
  if (tok.includes("*")){
    const at = tok.lastIndexOf("*"), ref = tok.slice(0, at), k = tok.slice(at + 1);
    if (!isNum(k)) return `배수는 숫자여야 합니다: ${tok} (예: "vol_ma*2")`;
    return checkOperand(ref, names);
  }
  const m = REF.exec(tok);
  if (!m) return `해석할 수 없는 피연산자: ${tok}`;
  if (!names.has(m[1])){
    const base = m[1].split(".")[0];
    if (EXT_NAME(m[1]) || EXT_NAME(base)) return null;   // 파생/외부(funding·oi 등) 변수는 허용(백테스트 데이터 없으면 null)
    return `조건식이 정의되지 않은 시리즈를 참조합니다: ${m[1]}` + (names.has(base + ".value") || [...names].some(x => x.startsWith(base + "."))
      ? ` (출력 이름을 붙이세요: ${[...names].filter(x => x.startsWith(base + ".")).join(", ")})` : "");
  }
  return null;
}
function normGroup(g, label, problems){
  if (isNil(g) || g === false || g === "") return null;
  let logic = "all", conds = g;
  if (!Array.isArray(g)){
    if (typeof g !== "object"){ problems.push(`${label}: 조건 그룹 형식 오류`); return null; }
    logic = String(g.logic ?? "all").toLowerCase();
    logic = {and: "all", or: "any"}[logic] || logic;
    if (logic !== "all" && logic !== "any"){ problems.push(`${label}: logic 은 all 또는 any 여야 합니다 (${g.logic})`); logic = "all"; }
    conds = g.conditions ?? [];
  }
  if (!Array.isArray(conds)){ problems.push(`${label}: conditions 는 배열이어야 합니다`); return null; }
  // 형식이 어긋난 개별 조건은 전략 전체를 실패시키지 않고 '건너뛴다'(드롭). 한 그룹의 조건이 전부 못 쓰면 그때만 오류.
  const out = []; let dropped = 0;
  conds.forEach((c, i) => {
    if (typeof c === "string"){                     // "rsi < 30" 같은 문자열도 받는다
      const parts = c.trim().split(/\s+/);
      if (parts.length !== 3){ dropped++; return; }
      c = {left: parts[0], op: parts[1], right: parts[2]};
    }
    if (!c || typeof c !== "object"){ dropped++; return; }
    let op = String(c.op ?? "").trim();
    op = OP_ALIAS[op.toLowerCase()] || op.toLowerCase();
    if (!OPS.includes(op)){ dropped++; return; }
    if (isNil(c.left) || isNil(c.right)){ dropped++; return; }   // left/right 누락 조건은 버리고 나머지로 계속
    out.push({left: String(c.left).trim(), op, right: String(c.right).trim()});
  });
  if (!out.length && conds.length){ problems.push(`${label}: 쓸 수 있는 조건이 없습니다 (${conds.length}개 모두 형식 오류)`); return null; }
  return out.length ? {logic, conditions: out} : null;
}

// 전략 JSON 검증·정규화 (기본값 채움). 문제가 있으면 한국어 메시지로 throw (err.problems 에 목록)
export function normalizeSpec(spec){
  if (typeof spec === "string"){
    try { spec = JSON.parse(spec); } catch(e){ throw new Error("전략 JSON 을 읽을 수 없습니다: " + e.message); }
  }
  if (!spec || typeof spec !== "object" || Array.isArray(spec)) throw new Error("전략은 JSON 객체여야 합니다");
  const problems = [];
  let interval = String(spec.interval ?? "1h").trim();
  interval = IV_ALIAS[interval] || IV_ALIAS[interval.toLowerCase()] || interval;   // "60"→"1h" 등 자동 교정
  if (!INTERVALS.includes(interval) && INTERVALS.includes(interval.toLowerCase())) interval = interval.toLowerCase();
  if (!INTERVALS.includes(interval)){ interval = "1h"; }   // 그래도 모르는 간격이면 1시간으로 (전략 실패 대신)
  const out = {name: String(spec.name ?? "전략"), description: String(spec.description ?? ""),
    symbol: String(spec.symbol ?? "BTCUSDT").toUpperCase(), interval, indicators: []};
  const inds = Array.isArray(spec.indicators) ? spec.indicators : (isNil(spec.indicators) ? [] : (problems.push("indicators 는 배열이어야 합니다"), []));
  const ids = new Set(), renamed = {}, dropped = new Set();
  inds.forEach((raw, i) => {
    if (!raw || typeof raw !== "object"){ problems.push(`indicators[${i}] 형식 오류`); return; }
    const r = {...(raw.params || {}), ...raw};
    let type = String(r.type ?? "").trim().toLowerCase();
    type = IND_ALIAS[type] || type;
    if (!IND_REGISTRY[type]){ problems.push(`지원하지 않는 지표: ${r.type} (가능: ${Object.keys(IND_REGISTRY).filter(k => !k.startsWith("tv_")).join(", ")} + 차트 터미널 tv_* ${TV_TYPES.length}종)`); return; }
    let id = String(r.id ?? type).trim();
    if (!/^[A-Za-z_]\w*$/.test(id)) id = "ind" + i;   // 잘못된 id → 안전한 이름
    if (PRICE_FIELDS.includes(id) || DERIV_FIELDS.includes(id) || ids.has(id)){   // 가격·파생 필드와 겹치거나 중복 → 자동 개명(조건도 뒤에서 함께 바꿈)
      const base = id.replace(/\d+$/, "") || "ind"; let n, k = 2;
      do { n = `${base}_i${k++}`; } while (PRICE_FIELDS.includes(n) || DERIV_FIELDS.includes(n) || ids.has(n));
      renamed[id] = n; id = n;
    }
    ids.add(id);
    const o = {id, type};
    for (const k of INT_PARAMS){
      if (isNil(r[k]) || r[k] === "") continue;
      const v = Math.round(Number(r[k]));
      if (!Number.isFinite(v) || v < 1) problems.push(`${id}.${k} 는 1 이상의 정수여야 합니다 (${r[k]})`); else o[k] = v;
    }
    if (!isNil(r.mult) && r.mult !== ""){
      const v = Number(r.mult);
      if (!Number.isFinite(v)) problems.push(`${id}.mult 는 숫자여야 합니다 (${r.mult})`); else o.mult = v;
    }
    if (!isNil(r.source) && r.source !== ""){
      const s = String(r.source).toLowerCase(), raw = String(r.source).trim();
      if (SOURCES.includes(s)) o.source = s;
      else if (/^[A-Za-z_]\w*(?:\.\w+)?$/.test(raw)) o.source = raw;   // 다른 지표 출력(예: rsi, bb.width)을 소스로 — buildSeries 에서 해석, 못 찾으면 close 로 폴백 (오류 없음)
    }
    if (IND_REGISTRY[type].tv) for (const [k, d] of Object.entries(IND_REGISTRY[type].defaults)){   // 터미널 지표 고유 파라미터
      if (isNil(r[k]) || r[k] === "" || k in o) continue;
      const v = typeof d === "number" ? Number(r[k]) : r[k];
      if (typeof d === "number" && !Number.isFinite(v)) problems.push(`${id}.${k} 는 숫자여야 합니다 (${r[k]})`); else o[k] = v;
    }
    if (type === "custom"){   // 수식 검사: 가격 · 앞에서 선언한 지표 · 파생/외부(ml_*, ext_*) 시리즈만 참조 가능
      const expr = typeof r.expr === "string" ? r.expr.trim() : "", known = seriesNames({indicators: out.indicators});
      let okExpr = false;
      if (expr){ try { parseExpr(expr, {vars: nm => known.has(nm) || EXT_NAME(nm)}); o.expr = expr; okExpr = true; } catch(e){} }
      if (!okExpr){ dropped.add(id); return; }   // 수식 없음/오류(예: 알 수 없는 함수) → 이 custom 지표만 버림(전략은 유지), 참조 조건은 뒤에서 제거
    }
    out.indicators.push(o);
  });
  for (const g of ["long_entry", "short_entry", "long_exit", "short_exit"]) out[g] = normGroup(spec[g], g, problems);
  // 자동 교정 반영: 이름이 바뀐 지표는 조건 피연산자도 바꾸고, 버려진 custom 지표를 참조하는 조건은 뺀다
  if (Object.keys(renamed).length || dropped.size){
    const baseId = t => (/^([A-Za-z_]\w*)/.exec(String(t)) || [, ""])[1];
    const fix = t => { const b = baseId(t); return b && renamed[b] ? renamed[b] + String(t).slice(b.length) : t; };
    for (const g of ["long_entry", "short_entry", "long_exit", "short_exit"]){
      if (!out[g]) continue;
      out[g].conditions = out[g].conditions.filter(c => !dropped.has(baseId(c.left)) && !dropped.has(baseId(c.right))).map(c => ({...c, left: fix(c.left), right: fix(c.right)}));
      if (!out[g].conditions.length) out[g] = null;
    }
  }
  if (!out.long_entry && !out.short_entry) problems.push("롱 또는 숏 진입 조건이 최소 1개 필요합니다.");
  const names = seriesNames(out);
  for (const g of ["long_entry", "short_entry", "long_exit", "short_exit"]){
    for (const c of out[g]?.conditions || []){
      const e1 = checkOperand(c.left, names); if (e1) problems.push(`${g}: ${e1}`);
      if (c.op === "rising" || c.op === "falling"){ if (!isNum(c.right)) problems.push(`${g}: ${c.op} 의 right 는 봉 개수(숫자)여야 합니다: ${c.right}`); }
      else { const e2 = checkOperand(c.right, names); if (e2) problems.push(`${g}: ${e2}`); }
    }
  }
  const r = {...RISK_DEFAULTS}, rin = spec.risk && typeof spec.risk === "object" ? spec.risk : {};
  for (const k of Object.keys(RISK_DEFAULTS)){
    const v = rin[k];
    if (isNil(v) || v === "") continue;
    if (k === "minimal_roi"){   // {분: 증거금 수익 %}
      if (typeof v !== "object" || Array.isArray(v)){ problems.push("risk.minimal_roi 는 {\"분\": 수익%} 객체여야 합니다"); continue; }
      const o = {}; for (const [m, x] of Object.entries(v)){ const mm = Number(m), xx = Number(x); if (!(mm >= 0) || !Number.isFinite(xx)) problems.push(`risk.minimal_roi 항목 오류: ${m}: ${x}`); else o[String(Math.trunc(mm))] = xx; }
      if (Object.keys(o).length) r[k] = o; continue;
    }
    if (k === "protections"){
      if (!Array.isArray(v)){ problems.push("risk.protections 는 배열이어야 합니다"); continue; }
      r[k] = v.filter(x => x && PROT_METHODS.includes(x.method)).map(x => ({method: x.method, lookback_candles: Math.max(1, Math.trunc(+x.lookback_candles || 0)) || null, stop_candles: Math.max(1, Math.trunc(+x.stop_candles || 0)) || null,
        trade_limit: Math.max(1, Math.trunc(+x.trade_limit || (x.method === "StoplossGuard" ? 10 : 1))), required_profit_pct: +x.required_profit_pct || 0, max_allowed_drawdown_pct: +x.max_allowed_drawdown_pct || 0}));
      if (!r[k].length) r[k] = null; continue;
    }
    if (k === "allow_reverse"){ r[k] = typeof v === "string" ? !/^(false|0|no|off|아니오)$/i.test(v.trim()) : !!v; continue; }
    const x = Number(v);
    if (!Number.isFinite(x)) problems.push(`risk.${k} 는 숫자여야 합니다 (${v})`); else r[k] = x;
  }
  if (!(r.leverage > 0 && r.leverage <= 200)) problems.push("레버리지는 0~200 사이여야 합니다.");
  if (!(r.position_pct > 0 && r.position_pct <= 100)) problems.push("position_pct 는 0~100 사이여야 합니다.");
  out.risk = r;
  if (problems.length){ const e = new Error("전략 오류: " + problems.join("; ")); e.problems = problems; throw e; }
  return out;
}
// throw 하지 않고 문제 목록만 (빈 배열이면 OK)
export function specProblems(spec){
  try { normalizeSpec(spec); return []; } catch(e){ return e.problems || [e.message]; }
}

// 시간 순 (t, value) 포인트를 캔들 시간축에 forward-fill
function align(c, points){
  const pts = points.map(p => ({t: toMs(p.t ?? p.time), v: p.value ?? p.v})).sort((a, b) => a.t - b.t);
  let j = 0, last = null;
  return c.map(b => { while (j < pts.length && pts[j].t <= b.t){ last = isNil(pts[j].v) ? null : +pts[j].v; j++; } return last; });
}

// 전략이 쓰는 모든 시리즈. deriv: {funding:[{t,value}], long_short:[...], open_interest:[...]} (선택)
export function buildSeries(spec, candles, deriv = null){
  spec = normalizeSpec(spec);
  const c = prep(candles), s = {};
  for (const f of PRICE_FIELDS) s[f] = srcOf(c, f);
  for (const ind of spec.indicators){
    const {id, type, ...params} = ind;
    // source 가 다른 지표 출력(예: "rsi", "bb.width")을 가리키면 그 시리즈를 넘겨 '지표의 이동평균' 같은 걸 실제로 계산
    let srcSeries = null;
    if (params.source && !PRICE_FIELDS.includes(String(params.source).toLowerCase())){
      const sn = String(params.source).trim();
      const key = sn in s ? sn : (`${sn}.value` in s ? `${sn}.value` : (`${sn}.line` in s ? `${sn}.line` : null));
      if (key) srcSeries = s[key];
    }
    const res = type === "custom" ? computeInd(c, type, {...params, extra: customExtra(c, s, deriv)}) : computeInd(c, type, srcSeries ? {...params, _srcSeries: srcSeries} : params), keys = Object.keys(res);
    for (const k of keys) s[`${id}.${k}`] = res[k];
    if (keys.length === 1 || "value" in res) s[id] = res.value ?? res[keys[0]];
    else if ("line" in res) s[id] = res.line;
  }
  s.__atr14 = atr(c, 14);
  Object.assign(s, derivAligned(c, deriv));
  // 파생 데이터가 없으면 null 시리즈 → 해당 조건은 항상 거짓
  for (const f of DERIV_FIELDS) if (!s[f]) s[f] = nulls(c.length);
  return s;
}
// 파생 데이터를 캔들 시간축에 맞춘 것 {funding, long_short, oi, oi_change_pct} (있는 것만)
function derivAligned(c, deriv){
  deriv = deriv || {};
  const s = {};
  if (deriv.funding?.length) s.funding = align(c, deriv.funding);
  if (deriv.long_short?.length) s.long_short = align(c, deriv.long_short);
  const oiPts = deriv.open_interest || deriv.oi;
  if (oiPts?.length){
    const oi = align(c, oiPts);
    s.oi = oi;
    s.oi_change_pct = oi.map((v, i) => i && v !== null && truthy(oi[i - 1]) ? (v - oi[i - 1]) / oi[i - 1] * 100 : null);
  }
  return s;
}
// custom 수식이 이름으로 쓸 수 있는 시리즈: 파생 · deriv.extra (예: {ml_prob: [...]}) · 앞서 계산한 지표
function customExtra(c, s, deriv){
  const ex = {...derivAligned(c, deriv), ...(deriv?.extra || {})};
  for (const [k, v] of Object.entries(s)) if (!PRICE_FIELDS.includes(k) && !k.startsWith("__")) ex[k] = v;
  return ex;
}
// opts.extra 를 deriv.extra 에 합친다 (custom 지표용 외부 시리즈)
const withExtra = (deriv, extra) => extra ? {...(deriv || {}), extra: {...(deriv?.extra || {}), ...extra}} : deriv;

function operand(series, tok, n){
  tok = String(tok).trim();
  if (isNum(tok)) return new Array(n).fill(toNum(tok));
  if (tok.includes("*")){
    const at = tok.lastIndexOf("*"), k = toNum(tok.slice(at + 1));
    return operand(series, tok.slice(0, at), n).map(v => v === null ? null : v * k);
  }
  const m = REF.exec(tok);
  if (!m) throw new Error(`해석할 수 없는 피연산자: ${tok}`);
  const name = m[1], shift = +(m[2] || 0);
  if (!(name in series)){
    if (EXT_NAME(name) || EXT_NAME(name.split(".")[0])) return new Array(n).fill(null);   // 데이터 없는 파생/외부 변수는 null 시리즈로(전략 실패 대신 그 조건만 안 걸림)
    throw new Error(`알 수 없는 시리즈: ${name}`);
  }
  const base = series[name];
  return shift ? base.map((_, i) => i >= shift ? base[i - shift] : null) : base;
}
function evalCondition(series, c, n){
  const a = operand(series, c.left, n), out = new Array(n).fill(false);
  if (c.op === "rising" || c.op === "falling"){
    const k = Math.max(1, Math.trunc(toNum(c.right)));
    for (let i = k; i < n; i++){
      let ok = true;
      for (let j = i - k; j <= i; j++) if (a[j] === null){ ok = false; break; }
      if (!ok) continue;
      let all = true;
      for (let j = i - k + 1; j <= i; j++) if (c.op === "rising" ? !(a[j] > a[j - 1]) : !(a[j] < a[j - 1])){ all = false; break; }
      out[i] = all;
    }
    return out;
  }
  const b = operand(series, c.right, n);
  for (let i = 0; i < n; i++){
    const x = a[i], y = b[i];
    if (x === null || y === null) continue;
    switch (c.op){
      case ">": out[i] = x > y; break;
      case "<": out[i] = x < y; break;
      case ">=": out[i] = x >= y; break;
      case "<=": out[i] = x <= y; break;
      case "==": out[i] = Math.abs(x - y) < 1e-6 || Math.abs(x - y) <= Math.abs(y) * 1e-4; break;   // 근사 같음(이산 지표용)
      case "!=": out[i] = !(Math.abs(x - y) < 1e-6 || Math.abs(x - y) <= Math.abs(y) * 1e-4); break;
      default:
        if (i > 0 && a[i - 1] !== null && b[i - 1] !== null){
          if (c.op === "crosses_above") out[i] = x > y && a[i - 1] <= b[i - 1];
          else if (c.op === "crosses_below") out[i] = x < y && a[i - 1] >= b[i - 1];
        }
    }
  }
  return out;
}
function evalGroup(series, g, n){
  if (!g || !g.conditions.length) return new Array(n).fill(false);
  const parts = g.conditions.map(c => evalCondition(series, c, n));
  return parts[0].map((_, i) => g.logic === "any" ? parts.some(p => p[i]) : parts.every(p => p[i]));
}

// 봉별 신호 {longEntry, shortEntry, longExit, shortExit} (불리언 배열) + atr(14)
export function signals(spec, candles, deriv = null){
  spec = normalizeSpec(spec);
  const c = prep(candles), n = c.length, series = buildSeries(spec, c, deriv);
  return {
    longEntry: evalGroup(series, spec.long_entry, n), shortEntry: evalGroup(series, spec.short_entry, n),
    longExit: evalGroup(series, spec.long_exit, n), shortExit: evalGroup(series, spec.short_exit, n),
    atr: series.__atr14, series,
  };
}

/* ============ 선물 포지션 시뮬레이터 (engine.py) ============ */
// 체결 규칙 (룩어헤드 방지):
//  - 신호는 봉 마감(close)에 판단 → 다음 봉 시가(open)에 체결
//  - 손절/익절/추적손절/청산은 봉 고가·저가로 판정. 같은 봉에서 손절·익절 모두 닿으면 손절 먼저
//  - 격리 마진, 유지증거금률 0.5% 로 청산가 계산
//  - 펀딩비: 보유 시간에 비례해 가정 펀딩비 부과 (롱 지불 / 숏 수령)
const MAINT_MARGIN_RATE = 0.005;

export class Simulator {
  constructor(risk, initialEquity = 10000, barSeconds = 3600){
    this.risk = {...RISK_DEFAULTS, ...risk};
    this.initialEquity = initialEquity; this.barSeconds = barSeconds;
    this.cash = initialEquity; this.position = null; this.pending = null; this.pendingReason = "";
    this.trades = []; this.equityCurve = []; this.blown = false;
    this.lockedUntil = 0; this.locks = [];   // 보호장치 잠금 (freqtrade protections)
  }
  // 보호장치: 청산 직후 최근 창(lookback)의 거래를 보고 새 진입을 잠근다. 잠금 끝 = 창 안 마지막 청산 + 잠금 길이
  protect(t){
    const P = this.risk.protections; if (!P || !P.length) return;
    const bar = this.barSeconds * 1000, defN = Math.max(1, Math.ceil(3600 / this.barSeconds));
    for (const pr of P){
      const look = (pr.lookback_candles || defN) * bar, stop = (pr.stop_candles || defN) * bar;
      const win = this.trades.filter(x => x.exitT > t - look && x.exitT <= t); if (!win.length) continue;
      const ratio = x => x.pnlPct / 100;
      let hit = false, why = "";
      if (pr.method === "StoplossGuard"){ const n = win.filter(x => /stop|liquidation/.test(x.reason) && ratio(x) < pr.required_profit_pct / 100).length; hit = n >= pr.trade_limit; why = `손절 ${n}회`; }
      else if (pr.method === "MaxDrawdown"){ if (win.length >= pr.trade_limit){ let cum = 0, peak = 0, dd = 0; for (const x of win){ cum += ratio(x); peak = Math.max(peak, cum); dd = Math.max(dd, peak - cum); } hit = dd * 100 > pr.max_allowed_drawdown_pct; why = `창 안 낙폭 ${pyRound(dd * 100, 1)}%`; } }
      else if (pr.method === "CooldownPeriod"){ hit = true; why = "청산 직후 쉬기"; }
      else if (pr.method === "LowProfitPairs"){ if (win.length >= pr.trade_limit){ const sum = win.reduce((a, x) => a + ratio(x), 0); hit = sum < pr.required_profit_pct / 100; why = `창 안 수익 ${pyRound(sum * 100, 1)}%`; } }
      if (hit){ const until = Math.max(...win.map(x => x.exitT)) + stop; if (until > this.lockedUntil){ this.lockedUntil = until; this.locks.push({method: pr.method, from: t, until, why}); } }
    }
  }
  slip(price, side){ return price * (1 + side * this.risk.slippage_pct / 100); }
  unrealized(p, price){ return p.side * p.qty * (price - p.entryPrice); }
  open(side, price, t, atrV = null, reason = ""){
    if (this.position || this.blown || this.cash <= 0) return null;
    if (t < this.lockedUntil) return null;   // 보호장치 잠금 중
    const r = this.risk, lev = r.leverage;
    const margin = Math.min(this.cash * r.position_pct / 100, this.cash);
    if (margin <= 0) return null;
    const fill = this.slip(price, side), qty = margin * lev / fill, fee = qty * fill * r.fee_pct / 100;
    this.cash -= fee;
    const p = {side, entryPrice: fill, qty, margin, leverage: lev, entryT: t, stop: null, take: null, extreme: fill, fundingPaid: 0, entryFee: fee, reason};
    p.liq = fill * (1 - side * (1 / lev - MAINT_MARGIN_RATE));
    const stops = [], takes = [];
    if (truthy(r.stop_loss_pct)) stops.push(fill * (1 - side * r.stop_loss_pct / 100));
    if (truthy(r.atr_stop_mult) && truthy(atrV)) stops.push(fill - side * atrV * r.atr_stop_mult);
    if (truthy(r.take_profit_pct)) takes.push(fill * (1 + side * r.take_profit_pct / 100));
    if (truthy(r.atr_tp_mult) && truthy(atrV)) takes.push(fill + side * atrV * r.atr_tp_mult);
    // 손절 기준이 여럿이면 진입가에 더 가까운(타이트한) 쪽
    if (stops.length) p.stop = side === 1 ? Math.max(...stops) : Math.min(...stops);
    if (takes.length) p.take = side === 1 ? Math.min(...takes) : Math.max(...takes);
    return this.position = p;
  }
  close(price, t, reason, slip = true){
    const p = this.position;
    if (!p) return null;
    const fill = slip ? this.slip(price, -p.side) : price;
    let gross = this.unrealized(p, fill);
    const fee = p.qty * fill * this.risk.fee_pct / 100;
    if (reason === "liquidation") gross = -p.margin;   // 격리 마진 전액 손실
    this.cash += gross - fee;
    const net = gross - fee - p.entryFee - p.fundingPaid;
    const tr = {side: p.side === 1 ? "long" : "short", entryT: p.entryT, entryP: p.entryPrice, exitT: t, exitP: fill,
      pnlPct: p.margin ? net / p.margin * 100 : 0, pnl: net, qty: p.qty, leverage: p.leverage,
      fees: fee + p.entryFee, funding: p.fundingPaid, entryReason: p.reason, reason};
    this.trades.push(tr);
    this.position = null;
    if (this.cash <= 0) this.blown = true;
    this.protect(t);
    return tr;
  }
  executePending(price, t, atrV = null){
    const action = this.pending, reason = this.pendingReason;
    this.pending = null; this.pendingReason = "";
    if (!action) return;
    const want = {long: 1, short: -1}[action];
    if (this.position && (action === "close" || (want && want !== this.position.side))) this.close(price, t, reason || "signal_exit");
    if (want && !this.position) this.open(want, price, t, atrV, action + "_entry");
  }
  // 봉 내부 가격으로 청산/손절/익절/추적손절 판정. bar: {t,o,h,l,c}
  checkStops(bar){
    const p = this.position;
    if (!p) return null;
    const r = this.risk, long = p.side === 1;
    let stop = p.stop;
    if (truthy(r.trailing_stop_pct)){
      const trail = p.extreme * (1 - p.side * r.trailing_stop_pct / 100);
      stop = stop === null ? trail : (long ? Math.max(stop, trail) : Math.min(stop, trail));
    }
    // 수익 오프셋 이후 추적손절 (freqtrade trailing_stop_positive + offset): 지난 봉까지의 최고(저)점 기준이라 같은 봉 낙관 없음
    if (truthy(r.trailing_stop_positive_pct) && truthy(r.trailing_stop_positive_offset_pct) && p.side * (p.extreme / p.entryPrice - 1) * 100 >= r.trailing_stop_positive_offset_pct){
      const trail = p.extreme * (1 - p.side * r.trailing_stop_positive_pct / 100);
      stop = stop === null ? trail : (long ? Math.max(stop, trail) : Math.min(stop, trail));
    }
    const adverse = long ? bar.l : bar.h, favorable = long ? bar.h : bar.l;
    const hit = lv => lv !== null && (long ? adverse <= lv : adverse >= lv);
    // 청산가가 손절가보다 먼저 닿는 경우 → 강제청산
    const liqFirst = stop === null || (long ? p.liq >= stop : p.liq <= stop);
    if (hit(p.liq) && liqFirst) return this.close(p.liq, bar.t, "liquidation", false);
    if (hit(stop)){
      const px = long ? Math.min(stop, bar.o) : Math.max(stop, bar.o);   // 갭이면 시가 체결
      return this.close(px, bar.t, stop !== p.stop ? "trailing_stop" : "stop_loss");
    }
    // 시간별 목표 수익표 (freqtrade minimal_roi): 보유 분 이하 가장 큰 키의 값(증거금 수익 %, 수수료 포함)을 넘으면 그 가격에 익절
    if (r.minimal_roi){
      const age = Math.floor((bar.t - p.entryT) / 60000), keys = Object.keys(r.minimal_roi).map(Number).filter(k => k <= age);
      if (keys.length){
        const need = r.minimal_roi[String(Math.max(...keys))] / 100, fees = 2 * r.fee_pct / 100 * p.leverage;
        const px = p.entryPrice * (1 + p.side * (need + fees) / p.leverage);
        if (long ? bar.o >= px : bar.o <= px) return this.close(bar.o, bar.t, "roi", false);
        if (long ? favorable >= px : favorable <= px) return this.close(px, bar.t, "roi", false);
      }
    }
    if (p.take !== null && (long ? favorable >= p.take : favorable <= p.take)){
      const px = long ? Math.max(p.take, bar.o) : Math.min(p.take, bar.o);
      return this.close(px, bar.t, "take_profit", false);
    }
    p.extreme = long ? Math.max(p.extreme, bar.h) : Math.min(p.extreme, bar.l);
    return null;
  }
  accrueFunding(price){
    const p = this.position;
    if (!p || !truthy(this.risk.funding_rate_8h_pct)) return;
    const cost = p.side * p.qty * price * this.risk.funding_rate_8h_pct / 100 * this.barSeconds / 28800;
    p.fundingPaid += cost; this.cash -= cost;
  }
  equity(price){ return this.cash + (this.position ? this.unrealized(this.position, price) : 0); }
  // 봉 i 마감 시점의 신호로 다음 봉에 실행할 주문 예약
  decide(sig, i){
    const p = this.position, le = sig.longEntry[i], se = sig.shortEntry[i], lx = sig.longExit[i], sx = sig.shortExit[i];
    if (!p){ if (le && !se) this.pending = "long"; else if (se && !le) this.pending = "short"; }
    else if (p.side === 1){
      if (se && this.risk.allow_reverse){ this.pending = "short"; this.pendingReason = "reverse_signal"; }
      else if (lx || se){ this.pending = "close"; this.pendingReason = "exit_signal"; }
    } else {
      if (le && this.risk.allow_reverse){ this.pending = "long"; this.pendingReason = "reverse_signal"; }
      else if (sx || le){ this.pending = "close"; this.pendingReason = "exit_signal"; }
    }
  }
  // 백테스트 1봉: 시가 체결 → 봉중 손절/익절 → 펀딩 → 종가 신호 판단 → 에쿼티 기록
  step(bar, sig, i){
    this.executePending(bar.o, bar.t, i > 0 ? sig.atr[i - 1] : null);
    this.checkStops(bar);
    this.accrueFunding(bar.c);
    if (!this.blown) this.decide(sig, i);
    this.equityCurve.push({t: bar.t, v: pyRound(this.equity(bar.c), 4)});
  }
}

// 성과 지표 (engine.metrics) + 이 앱용 별칭(return_pct · max_dd_pct · win_rate · n_trades · avg_trade_pct)
function metrics(sim, barSeconds){
  const eq = sim.equityCurve.map(p => p.v), trades = sim.trades;
  if (!eq.length) return {};
  let peak = eq[0], mdd = 0;
  for (const v of eq){ peak = Math.max(peak, v); mdd = Math.max(mdd, peak > 0 ? (peak - v) / peak * 100 : 100); }
  const rets = [];
  for (let i = 1; i < eq.length; i++) if (eq[i - 1] > 0) rets.push((eq[i] - eq[i - 1]) / eq[i - 1]);
  let sharpe = null;
  if (rets.length > 2){
    let mu = 0; for (const r of rets) mu += r; mu /= rets.length;
    let ss = 0; for (const r of rets) ss += (r - mu) ** 2;
    const sd = Math.sqrt(ss / (rets.length - 1));
    if (sd > 0) sharpe = mu / sd * Math.sqrt(365 * 86400 / barSeconds);
  }
  const sum = a => a.reduce((s, x) => s + x, 0);
  const wins = trades.filter(t => t.pnl > 0), losses = trades.filter(t => t.pnl <= 0);
  const gw = sum(wins.map(t => t.pnl)), gl = -sum(losses.map(t => t.pnl));
  const inMarket = sum(trades.map(t => t.exitT - t.entryT));
  const span = (sim.equityCurve[sim.equityCurve.length - 1].t - sim.equityCurve[0].t) || 1;
  const n = trades.length;
  const m = {
    initial_equity: sim.initialEquity,
    final_equity: pyRound(eq[eq.length - 1], 2),
    total_return_pct: pyRound((eq[eq.length - 1] / sim.initialEquity - 1) * 100, 2),
    max_drawdown_pct: pyRound(mdd, 2),
    sharpe: sharpe !== null ? pyRound(sharpe, 2) : null,
    trades: n,
    win_rate_pct: n ? pyRound(wins.length / n * 100, 1) : null,
    profit_factor: gl > 0 ? pyRound(gw / gl, 2) : null,
    avg_trade_pnl: n ? pyRound(sum(trades.map(t => t.pnl)) / n, 2) : null,
    long_trades: trades.filter(t => t.side === "long").length,
    short_trades: trades.filter(t => t.side === "short").length,
    liquidations: trades.filter(t => t.reason === "liquidation").length,
    fees_paid: pyRound(sum(trades.map(t => t.fees)), 2),
    funding_paid: pyRound(sum(trades.map(t => t.funding)), 2),
    exposure_pct: pyRound(inMarket / span * 100, 1),
    // backtrader SQN = √n × 평균 / 모표준편차 (30거래 이상일 때 의미) · freqtrade 기대값 비율 = (1 + 평균이익/평균손실) × 승률 − 1
    sqn: n > 1 ? (() => { const a = trades.map(t => t.pnl), m = sum(a) / n, sdv = Math.sqrt(sum(a.map(x => (x - m) ** 2)) / n); return sdv > 0 ? pyRound(Math.sqrt(n) * m / sdv, 2) : null; })() : null,
    expectancy_ratio: wins.length && losses.length ? pyRound((1 + (gw / wins.length) / (gl / losses.length)) * (wins.length / n) - 1, 3) : null,
    roi_exits: trades.filter(t => t.reason === "roi").length,
    protection_locks: (sim.locks || []).length,
    blown_up: sim.blown,
  };
  return Object.assign(m, {return_pct: m.total_return_pct, max_dd_pct: m.max_drawdown_pct, win_rate: m.win_rate_pct, n_trades: n,
    avg_trade_pct: n ? pyRound(sum(trades.map(t => t.pnlPct)) / n, 2) : null});
}

const barSecondsOf = (spec, opts) => opts.barSeconds || INTERVAL_SECONDS[spec.interval] || 3600;

// 백테스트 (backtest.run). opts: {deriv, extra({이름: 시리즈}, custom 지표용), initialEquity=10000, barSeconds(기본: spec.interval)}
// 캔들 간격과 spec.interval 이 같아야 펀딩·샤프가 맞다.
export function backtest(spec, candles, opts = {}){
  spec = normalizeSpec(spec);
  const c = prep(candles);
  if (!c.length) throw new Error("캔들이 없습니다");
  const bs = barSecondsOf(spec, opts);
  const sig = signals(spec, c, withExtra(opts.deriv, opts.extra));
  const sim = new Simulator(spec.risk, opts.initialEquity ?? 10000, bs);
  for (let i = 0; i < c.length; i++){ sim.step(c[i], sig, i); if (sim.blown) break; }
  if (sim.position){   // 마지막 봉 종가로 정리
    const last = c[c.length - 1];
    sim.close(last.c, last.t, "end_of_test");
    sim.equityCurve[sim.equityCurve.length - 1].v = pyRound(sim.cash, 4);
  }
  const stats = metrics(sim, bs);
  stats.buy_and_hold_pct = pyRound((c[c.length - 1].c / c[0].c - 1) * 100, 2);
  return {spec, trades: sim.trades, equity: sim.equityCurve, stats};
}

/* ============ 검증 관문 (improve.py · team/engine.py · autopilot.py) ============ */
// 백엔드와 같이 백테스트는 전체 구간을 한 번 돌리고, 거래를 진입 시각으로 나눠 구간 성적을 낸다.
// 기본 관문 (team/engine.py _gate_from_backtest, "코드 관문"):
//   학습 = 앞 70% (improve.TRAIN_SHARE), 검증(OOS) = 뒤 30%
//   통과 = 검증 거래 20건 이상 · 검증 손익비 1.2 이상 · 검증 순손익 > 0 · 학습 순손익 > 0
//   (손익비는 손실 거래가 없으면 null → 0 으로 보아 미달, 백엔드와 같음)
// 보조 관문 gate3 (autopilot.py GATE, 오토파일럿 3구간):
//   앞 60% 학습(거래 20·손익비 1.1) → 다음 20% 검증(8·1.15) → 마지막 20% 최종(8·1.1), 각 구간 순손익 > 0,
//   그리고 전체 최대낙폭 < 35%. (손익비는 손실 없으면 99)
export const GATE = {train_share: 0.7, min_test_trades: 20, min_test_pf: 1.2};
export const GATE3 = {train: {trades: 20, pf: 1.1}, valid: {trades: 8, pf: 1.15}, hold: {trades: 8, pf: 1.1}, max_dd_pct: 35};

// improve._score
function score(trades){
  const n = trades.length, pnl = trades.reduce((s, t) => s + t.pnl, 0);
  const wins = trades.filter(t => t.pnl > 0);
  const gw = wins.reduce((s, t) => s + t.pnl, 0), gl = -trades.filter(t => t.pnl <= 0).reduce((s, t) => s + t.pnl, 0);
  return {trades: n, net_pnl: pyRound(pnl, 2), win_rate: n ? pyRound(wins.length / n * 100, 1) : null,
    profit_factor: gl > 0 ? pyRound(gw / gl, 2) : null};
}
// autopilot._seg (t = 거래 손익 평균의 t값)
function seg(trades){
  const n = trades.length, pnl = trades.map(t => t.pnl);
  const gw = pnl.filter(x => x > 0).reduce((s, x) => s + x, 0), gl = -pnl.filter(x => x <= 0).reduce((s, x) => s + x, 0);
  const tot = pnl.reduce((s, x) => s + x, 0), mean = n ? tot / n : 0;
  const sd = n > 1 ? Math.sqrt(pnl.reduce((s, x) => s + (x - mean) ** 2, 0) / (n - 1)) : 0;
  return {trades: n, net: pyRound(tot, 2), pf: gl > 0 ? pyRound(gw / gl, 3) : (gw > 0 ? 99.0 : null),
    win_rate: n ? pyRound(pnl.filter(x => x > 0).length / n * 100, 1) : null, t: n > 1 && sd > 0 ? pyRound(mean / (sd / Math.sqrt(n)), 3) : 0};
}
const segOk = (s, g) => s.trades >= g.trades && (s.pf || 0) >= g.pf && s.net > 0;
// 에쿼티 곡선 구간의 수익률·최대낙폭
function eqStats(points, startV){
  if (!points.length) return {return_pct: 0, max_dd_pct: 0};
  let peak = startV, mdd = 0;
  for (const p of points){ peak = Math.max(peak, p.v); mdd = Math.max(mdd, peak > 0 ? (peak - p.v) / peak * 100 : 100); }
  return {return_pct: pyRound((points[points.length - 1].v / startV - 1) * 100, 2), max_dd_pct: pyRound(mdd, 2)};
}
function segStats(trades, points, startV){
  const s = score(trades), q = seg(trades), e = eqStats(points, startV), n = trades.length;
  return {...s, n_trades: n, win_rate_pct: s.win_rate, t: q.t, ...e,
    avg_trade_pct: n ? pyRound(trades.reduce((a, t) => a + t.pnlPct, 0) / n, 2) : null};
}

// walk-forward 검증. opts: {deriv, initialEquity, barSeconds, split(0.7), gate:{min_test_trades, min_test_pf}}
export function walkForward(spec, candles, opts = {}){
  const c = prep(candles);
  if (c.length < 50) throw new Error(`봉이 너무 적습니다 (${c.length}개)`);
  const res = backtest(spec, c, opts), G = {...GATE, ...(opts.gate || {})};
  const split = opts.split ?? G.train_share;
  const splitT = c[Math.floor(c.length * split)].t;
  const trIS = res.trades.filter(t => t.entryT < splitT), trOOS = res.trades.filter(t => t.entryT >= splitT);
  const eqIS = res.equity.filter(p => p.t < splitT), eqOOS = res.equity.filter(p => p.t >= splitT);
  const init = opts.initialEquity ?? 10000, mid = eqIS.length ? eqIS[eqIS.length - 1].v : init;
  const is = segStats(trIS, eqIS, init), oos = segStats(trOOS, eqOOS, mid);
  const fmt = v => v === null ? "없음" : v;
  const checks = [
    [oos.trades >= G.min_test_trades, `검증 구간(뒤 ${pyRound((1 - split) * 100)}%) 거래 ${oos.trades}건 (기준 ${G.min_test_trades}건 이상)`],
    [(oos.profit_factor || 0) >= G.min_test_pf, `검증 구간 손익비 ${fmt(oos.profit_factor)} (기준 ${G.min_test_pf} 이상)`],
    [oos.net_pnl > 0, `검증 구간 순손익 ${oos.net_pnl} (기준 0 초과)`],
    [is.net_pnl > 0, `학습 구간 순손익 ${is.net_pnl} (기준 0 초과)`],
  ];
  const pass = checks.every(x => x[0]);
  const reasons = checks.map(([ok, txt]) => (ok ? "통과: " : "미달: ") + txt);
  if (!pass && is.net_pnl > 0 && oos.net_pnl <= 0) reasons.push("학습 구간에서만 이익 → 과최적화 가능성이 큽니다");
  // 3구간 관문 (오토파일럿)
  const t1 = c[Math.floor(c.length * 0.6)].t, t2 = c[Math.floor(c.length * 0.8)].t;
  const s3 = {train: seg(res.trades.filter(t => t.entryT < t1)), valid: seg(res.trades.filter(t => t.entryT >= t1 && t.entryT < t2)),
    hold: seg(res.trades.filter(t => t.entryT >= t2))};
  const stage = !segOk(s3.train, GATE3.train) ? "train_fail" : !segOk(s3.valid, GATE3.valid) ? "valid_fail"
    : !(segOk(s3.hold, GATE3.hold) && (res.stats.max_drawdown_pct || 0) < GATE3.max_dd_pct) ? "hold_fail" : "pass";
  return {is, oos, pass, reasons, split_t: splitT, full: res.stats,
    rule: `검증 구간(뒤 ${pyRound((1 - split) * 100)}%) 거래 ${G.min_test_trades}건 이상 · 손익비 ${G.min_test_pf} 이상 · 두 구간 모두 이익`,
    gate3: {pass: stage === "pass", stage, seg: s3, periods: {from: c[0].t, train_to: t1, valid_to: t2, hold_to: c[c.length - 1].t}}};
}

/* ============ 실시간 신호 ============ */
const OP_KO = {">": ">", "<": "<", ">=": "≥", "<=": "≤", crosses_above: "상향 돌파", crosses_below: "하향 돌파"};
const fmtV = v => v === null || v === undefined ? "없음" : Number.isNaN(v) ? "NaN" : Math.abs(v) >= 1000 ? v.toFixed(1) : Math.abs(v) >= 1 ? v.toFixed(3).replace(/\.?0+$/, "") : String(+v.toPrecision(4));
function condText(series, c, n, i){
  if (c.op === "rising" || c.op === "falling") return `${c.left}(${fmtV(operand(series, c.left, n)[i])}) ${Math.max(1, Math.trunc(toNum(c.right)))}봉 연속 ${c.op === "rising" ? "상승" : "하락"}`;
  const L = isNum(c.left) ? c.left : `${c.left}(${fmtV(operand(series, c.left, n)[i])})`;
  const R = isNum(c.right) ? c.right : `${c.right}(${fmtV(operand(series, c.right, n)[i])})`;
  return `${L} ${OP_KO[c.op]} ${R}`;
}
const GROUP_KO = {long_entry: "롱 진입", short_entry: "숏 진입", long_exit: "롱 청산", short_exit: "숏 청산"};

// 마지막 '마감된' 봉 기준 신호 (paper.py 와 같은 규칙: t + 봉길이 <= now 인 봉만 마감으로 본다).
// 실행은 엔진처럼 다음 봉 시가(지금 가격). opts: {now=Date.now(), assumeClosed, position:"long"|"short"|null, deriv, barSeconds}
// position 을 주면 엔진 decide() 와 같이 판단 (반대 신호면 allow_reverse 에 따라 스위칭/청산).
export function liveSignal(spec, candles, opts = {}){
  spec = normalizeSpec(spec);
  const all = prep(candles), step = barSecondsOf(spec, opts) * 1000, now = opts.now ?? Date.now();
  const c = opts.assumeClosed ? all : all.filter(b => b.t + step <= now);
  if (!c.length) return {action: "hold", price: all.at(-1)?.c ?? null, t: all.at(-1)?.t ?? null, why: "마감된 봉이 없습니다"};
  const n = c.length, i = n - 1, series = buildSeries(spec, c, withExtra(opts.deriv, opts.extra));
  const fired = {}, detail = {};
  for (const g of ["long_entry", "short_entry", "long_exit", "short_exit"]){
    const grp = spec[g];
    if (!grp){ fired[g] = false; continue; }
    const res = grp.conditions.map(cd => ({ok: evalCondition(series, cd, n)[i], txt: condText(series, cd, n, i)}));
    fired[g] = grp.logic === "any" ? res.some(r => r.ok) : res.every(r => r.ok);
    detail[g] = {logic: grp.logic, res};
  }
  const desc = g => { const d = detail[g]; if (!d) return ""; const ok = d.res.filter(r => r.ok);
    return `${GROUP_KO[g]}(${d.logic === "any" ? "하나 이상" : "모두"}) 충족: ${ok.map(r => r.txt).join(", ")}`; };
  const le = fired.long_entry, se = fired.short_entry, lx = fired.long_exit, sx = fired.short_exit, pos = opts.position || null;
  let action = "hold", why = "";
  if (pos === "long"){
    if (se && spec.risk.allow_reverse){ action = "short"; why = desc("short_entry") + " → 롱 청산 후 숏 전환"; }
    else if (lx || se){ action = "exit_long"; why = lx ? desc("long_exit") : desc("short_entry") + " → 롱 청산 (스위칭 꺼짐)"; }
  } else if (pos === "short"){
    if (le && spec.risk.allow_reverse){ action = "long"; why = desc("long_entry") + " → 숏 청산 후 롱 전환"; }
    else if (sx || le){ action = "exit_short"; why = sx ? desc("short_exit") : desc("long_entry") + " → 숏 청산 (스위칭 꺼짐)"; }
  } else {
    if (le && !se){ action = "long"; why = desc("long_entry"); }
    else if (se && !le){ action = "short"; why = desc("short_entry"); }
    else if (le && se) why = "롱·숏 진입 조건이 동시에 충족 → 엔진 규칙상 관망";
    else if (lx){ action = "exit_long"; why = desc("long_exit") + " (롱 보유 중이면 청산)"; }
    else if (sx){ action = "exit_short"; why = desc("short_exit") + " (숏 보유 중이면 청산)"; }
  }
  if (action === "hold" && !why){
    const gs = pos === "long" ? ["long_exit", "short_entry"] : pos === "short" ? ["short_exit", "long_entry"] : ["long_entry", "short_entry"];
    const near = gs.filter(g => detail[g]).map(g => {
      const d = detail[g], k = d.res.filter(r => r.ok).length, miss = d.res.filter(r => !r.ok).map(r => r.txt);
      return `${GROUP_KO[g]} ${k}/${d.res.length} 충족` + (miss.length ? ` (미충족: ${miss.slice(0, 3).join(", ")})` : "");
    });
    why = (pos ? `${pos === "long" ? "롱" : "숏"} 보유 유지 — ` : "신호 없음 — ") + (near.join(" · ") || "청산 조건 없음 (손절·익절·반대 신호로만 청산)");
  }
  const bar = c[i];
  return {action, price: bar.c, t: bar.t, why, closed: c.length === all.length ? (opts.assumeClosed ? "assumed" : true) : "excluded_last",
    fired: {longEntry: le, shortEntry: se, longExit: lx, shortExit: sx}, atr: series.__atr14[i],
    note: "봉 마감 신호 → 다음 봉 시가(현재가) 체결"};
}

/* ============ 차트 스냅샷 ============ */
const r6 = v => v === null || v === undefined || !Number.isFinite(v) ? (v ?? null) : +v.toPrecision(6);
// 29개 지표(기본값)의 마지막 봉 값 + 묶음별 한 줄 요약 (에이전트가 '차트가 뭐라 하는지' 읽는 용도)
// 마지막 봉이 진행 중이면 그 값 기준이다 (마감 봉만 보려면 마지막 봉을 빼고 넘긴다).
export function snapshot(candles){
  const c = prep(candles), n = c.length;
  if (!n) return {bars: 0, ind: {}, text: {}};
  const i = n - 1, b = c[i], ind = {}, full = {};
  for (const type of Object.keys(IND_REGISTRY)){
    if (type === "custom") continue;   // 수식이 없으면 계산할 것이 없다
    const res = computeInd(c, type, {});
    full[type] = res; ind[type] = {};
    for (const [k, arr] of Object.entries(res)) ind[type][k] = r6(arr[i]);
  }
  const g = (t, k = "value") => ind[t]?.[k] ?? null, px = b.c;
  const fx = (v, d = 1) => v === null ? "?" : (Math.abs(v) < 0.5 * 10 ** -d ? 0 : v).toFixed(d);
  const dev = a => a === null || !a ? null : (px - a) / a * 100;   // 가격이 기준선에서 떨어진 %
  const sg = v => v === null ? "?" : (v >= 0 ? "+" : "") + v.toFixed(2) + "%";
  const ago = (t, k, d) => { const a = full[t][k]; return i - d >= 0 ? a[i - d] : null; };
  // 추세
  const maAbove = ["sma", "ema", "wma", "vwma", "hma"].filter(t => g(t) !== null);
  const above = maAbove.filter(t => px > g(t)).length;
  const dir = v => v === null ? "?" : v > 0 ? "상승" : "하락";
  const adxV = g("adx", "adx"), pdi = g("adx", "plus_di"), mdi = g("adx", "minus_di");
  const cloud = g("ichimoku", "span_a") !== null && g("ichimoku", "span_b") !== null
    ? (px > Math.max(g("ichimoku", "span_a"), g("ichimoku", "span_b")) ? "구름 위" : px < Math.min(g("ichimoku", "span_a"), g("ichimoku", "span_b")) ? "구름 아래" : "구름 안") : "구름 ?";
  const trendVotes = [g("supertrend", "trend"), g("psar", "trend"), g("atr_stop", "trend")].filter(v => v !== null);
  const upVotes = trendVotes.filter(v => v > 0).length;
  const trend = `추세: 가격이 이평 ${maAbove.length}개 중 ${above}개 위 (EMA20 대비 ${sg(dev(g("ema")))}) · `
    + `슈퍼트렌드 ${dir(g("supertrend", "trend"))} · PSAR ${dir(g("psar", "trend"))} · ATR추적 ${dir(g("atr_stop", "trend"))} (${upVotes}/${trendVotes.length} 상승) · `
    + `ADX ${fx(adxV)}${adxV === null ? "" : adxV >= 25 ? " 추세 뚜렷" : adxV < 18 ? " 방향성 약함" : " 보통"}`
    + `${pdi !== null && mdi !== null ? ` (+DI ${pdi > mdi ? ">" : "<"} -DI)` : ""} · 일목 ${cloud} · 아룬 상${g("aroon", "up") ?? "?"}/하${g("aroon", "down") ?? "?"}`;
  // 모멘텀
  const rsiV = g("rsi"), zone = (v, lo, hi) => v === null ? "" : v >= hi ? " 과매수" : v <= lo ? " 과매도" : "";
  const mh = g("macd", "hist"), mhPrev = ago("macd", "hist", 1);
  const momentum = `모멘텀: RSI ${fx(rsiV)}${zone(rsiV, 30, 70)} · 스토캐스틱 K ${fx(g("stoch", "k"))}${zone(g("stoch", "k"), 20, 80)}`
    + ` · 스토RSI K ${fx(g("stochrsi", "k"))} · CCI ${fx(g("cci"), 0)} · %R ${fx(g("willr"))} · ROC9 ${sg(g("roc"))}`
    + ` · MACD 히스토 ${mh === null ? "?" : (mh >= 0 ? "양(+)" : "음(-)") + (mhPrev !== null ? (Math.abs(mh) > Math.abs(mhPrev) ? " 확대" : " 축소") : "")}`;
  // 변동성
  const bu = g("bb", "upper"), bl = g("bb", "lower");
  const pctB = bu !== null && bl !== null && bu !== bl ? (px - bl) / (bu - bl) * 100 : null;
  const widths = full.bb.width.filter(v => v !== null), bw = g("bb", "width");
  const wRank = bw !== null && widths.length ? widths.filter(v => v <= bw).length / widths.length * 100 : null;
  const ku = g("keltner", "upper"), kl = g("keltner", "lower");
  const volatility = `변동성: ATR14 ${g("atr") === null ? "?" : (g("atr") / px * 100).toFixed(2) + "%"} · 볼린저 폭 ${fx(bw, 2)}%`
    + `${wRank === null ? "" : ` (과거 대비 하위 ${wRank.toFixed(0)}%${wRank <= 15 ? ", 수축 — 큰 움직임 대기" : wRank >= 85 ? ", 과열" : ""})`}`
    + ` · %B ${fx(pctB, 0)}` + ` · 켈트너 ${ku === null ? "?" : px > ku ? "상단 돌파" : px < kl ? "하단 이탈" : "안"}`
    + ` · 돈치안20 ${g("donchian", "upper") === null ? "?" : px >= g("donchian", "upper") ? "신고가" : px <= g("donchian", "lower") ? "신저가" : "범위 안"}`;
  // 거래량
  const vs = g("volume_sma"), obvNow = g("obv"), obvAgo = ago("obv", "value", 20);
  const volume = `거래량: 평균의 ${vs ? (b.v / vs).toFixed(2) : "?"}배 · OBV 20봉 ${obvAgo === null ? "?" : obvNow > obvAgo ? "증가" : "감소"}`
    + ` · CMF ${fx(g("cmf"), 3)}${g("cmf") === null ? "" : g("cmf") > 0.05 ? " 매수 우위" : g("cmf") < -0.05 ? " 매도 우위" : " 중립"}`
    + ` · MFI ${fx(g("mfi"))}${zone(g("mfi"), 20, 80)} · VWAP ${g("vwap") === null ? "?" : px >= g("vwap") ? "위" : "아래"} (${sg(dev(g("vwap")))})`;
  return {t: b.t, price: px, bars: n, ind, text: {trend, momentum, volatility, volume}};
}

/* ============ 전략 작성 프롬프트 (nl_strategy.py SYSTEM_PROMPT) ============ */
const IND_TABLE = Object.entries(IND_REGISTRY)
  .map(([k, v]) => `- ${k}: ${v.outputs.join(", ")} / ${JSON.stringify(v.defaults)} — ${v.desc}`).join("\n");
const RISK_TABLE = [
  ["leverage", "레버리지 배수 (1~200, 제한 없이 시험 가능 · 높을수록 강제청산 위험)"], ["position_pct", "진입 시 증거금으로 쓰는 자본 비율 % (0~100)"],
  ["stop_loss_pct", "진입가 대비 손절 % (가격 기준)"], ["take_profit_pct", "진입가 대비 익절 % (가격 기준)"],
  ["atr_stop_mult", "ATR(14) x 배수 손절"], ["atr_tp_mult", "ATR(14) x 배수 익절"],
  ["trailing_stop_pct", "고점(저점) 대비 추적 손절 %"], ["fee_pct", "편도 수수료 % (바이낸스 테이커 0.04)"],
  ["slippage_pct", "편도 슬리피지 %"], ["funding_rate_8h_pct", "8시간당 가정 펀딩비 % (롱 지불, 숏 수령)"],
  ["allow_reverse", "반대 신호 시 즉시 스위칭 (true/false)"],
].map(([k, d]) => `- ${k} (기본 ${JSON.stringify(RISK_DEFAULTS[k])}): ${d}`).join("\n");
const EX1 = {name: "EMA 20/50 크로스 + ATR 손절", description: "1시간봉 EMA20이 EMA50을 상향 돌파하면 롱, 하향 돌파하면 숏. ADX 20 이상 추세장만. ATR 2배 손절·3배 익절.",
  symbol: "BTCUSDT", interval: "1h",
  indicators: [{id: "ema_fast", type: "ema", length: 20}, {id: "ema_slow", type: "ema", length: 50}, {id: "adx", type: "adx", length: 14}],
  long_entry: {logic: "all", conditions: [{left: "ema_fast", op: "crosses_above", right: "ema_slow"}, {left: "adx.adx", op: ">=", right: "20"}]},
  short_entry: {logic: "all", conditions: [{left: "ema_fast", op: "crosses_below", right: "ema_slow"}, {left: "adx.adx", op: ">=", right: "20"}]},
  long_exit: null, short_exit: null,
  risk: {leverage: 3, position_pct: 20, atr_stop_mult: 2, atr_tp_mult: 3, allow_reverse: true}};
const EX2 = {name: "볼린저 하단 + RSI 과매도 롱", description: "4시간봉 종가가 볼린저 하단 아래이고 RSI 30 미만이며 거래량이 평균 1.5배 이상이면 롱. RSI 55 상향 돌파 시 청산. 손절 2% 익절 4%. 롱만.",
  symbol: "ETHUSDT", interval: "4h",
  indicators: [{id: "bb", type: "bb", length: 20, mult: 2}, {id: "rsi", type: "rsi", length: 14}, {id: "vol_ma", type: "volume_sma", length: 20}],
  long_entry: {logic: "all", conditions: [{left: "close", op: "<", right: "bb.lower"}, {left: "rsi", op: "<", right: "30"}, {left: "volume", op: ">", right: "vol_ma*1.5"}]},
  short_entry: null,
  long_exit: {logic: "any", conditions: [{left: "rsi", op: "crosses_above", right: "55"}, {left: "close", op: ">", right: "bb.middle"}]},
  short_exit: null,
  risk: {leverage: 2, position_pct: 20, stop_loss_pct: 2, take_profit_pct: 4}};

export const STRATEGY_PROMPT = `당신은 코인 선물 퀀트 전략 엔지니어다. 사용자가 말로 설명한 진입/청산 기준을
백테스트 엔진이 실행할 수 있는 StrategySpec JSON 으로 정확히 옮긴다. 출력은 JSON 객체 하나만 (설명·코드펜스 없이).

형식
{"name": 전략 이름, "description": 가정·설명(한국어), "symbol": "BTCUSDT", "interval": "1h",
 "indicators": [{"id": 참조 이름, "type": 지표 종류, 파라미터...}],
 "long_entry": 조건그룹|null, "short_entry": 조건그룹|null, "long_exit": 조건그룹|null, "short_exit": 조건그룹|null,
 "risk": {리스크 필드}}
- 조건그룹 = {"logic": "all"|"any", "conditions": [{"left": 문자열, "op": 연산자, "right": 문자열}, ...]}
- 지표 파라미터: length, fast, slow, signal, k_smooth, d_smooth (정수), mult (실수), source (close/open/high/low/hl2/hlc3/ohlc4). 빠지면 기본값.
- id 는 영문 소문자/숫자/_ (예: ema_fast, rsi, macd). 가격 필드 이름(close 등)이나 funding 등은 id 로 쓰지 않는다.

규칙
- indicators 에 필요한 지표를 선언하고, 조건식의 left/right 는 아래 문법만 쓴다.
  * 가격: open, high, low, close, volume, hl2, hlc3, ohlc4
  * 지표: "<id>" 또는 "<id>.<출력>" (출력 이름은 아래 표 참고). "<id>" 만 쓰는 것은 출력이 하나이거나 value/line 출력이 있는 지표만 (macd → line, supertrend/atr_stop → line). bb·stoch·adx 등은 반드시 "<id>.<출력>".
  * 파생 데이터: funding(펀딩비 %, 0.01 = 0.01%), oi(미결제약정 USD), oi_change_pct(직전 봉 대비 OI 변화 %), long_short(롱/숏 계정비율) — 데이터가 없으면 그 조건은 항상 거짓
  * 과거 값: "close[1]", "rsi[2]" 처럼 [n]
  * 숫자는 문자열로: "30"
  * 배수: "vol_ma*2", "bb.upper*1.005" 처럼 참조*숫자
- op: >, <, >=, <=, crosses_above, crosses_below, rising, falling (rising/falling 은 right 에 봉 수: left 가 N봉 연속 상승/하락)
- 같은 그룹 안의 조건은 logic 이 all(AND) 또는 any(OR). 그룹 중첩은 없다.
- 사용자가 방향을 한쪽만 말하면 그 방향만 채우고 나머지는 null.
  "양방향", "반대로 숏" 같은 표현이 있으면 대칭 조건으로 숏도 만든다.
- 손절/익절/레버리지/비중이 언급되면 risk 에 반영. 언급 없으면 기본값 유지
  (leverage 3, position_pct 20, fee_pct 0.04). 퍼센트는 가격 기준 %.
- symbol 은 바이낸스 USDT 무기한 심볼(BTCUSDT 등), interval 은 ${INTERVALS.join(",")} 중 하나.
- 모호한 부분은 가장 일반적인 트레이더 해석을 택하고 description 에 가정을 한국어로 적는다.
- MACD 골든크로스 = macd.line crosses_above macd.signal. 슈퍼트렌드 상승전환 = st.trend crosses_above 0.
- 표에 없는 지표·복합 공식은 type "custom" 으로 직접 만든다: {"id": "vmom", "type": "custom", "expr": "(close - close[20]) / ind(\"atr\",{length:14})"}
  수식에는 가격, 앞서 선언한 지표 id, sma/ema/zscore/slope/corr/crossover/barssince 등 함수, ind("지표",{파라미터},"출력"),
  외부 시리즈(ml_prob 등)를 쓸 수 있다 (전체 문법: CUSTOM_DOC). 결과는 시리즈 하나 → 조건식에서 "vmom" 으로 참조, 참/거짓 수식은 1/0.

엔진 동작 (조건을 짤 때 참고)
- 신호는 봉 마감에 판단 → 다음 봉 시가에 체결. 손절·익절·추적손절·강제청산은 봉 고가·저가로 판정, 같은 봉에서 둘 다 닿으면 손절 먼저.
- 포지션이 없을 때 롱·숏 진입이 동시에 참이면 진입하지 않는다.
- 롱 보유 중 숏 진입 신호: allow_reverse 면 바로 숏 전환, 아니면 청산만. 청산 조건(long_exit/short_exit)은 없어도 된다.
- 손절이 여러 개(stop_loss_pct, atr_stop_mult)면 진입가에 더 가까운 쪽, 익절도 더 가까운 쪽이 적용된다.
- 검증 관문: 앞 70% 학습 / 뒤 30% 검증으로 나눠, 검증 구간 거래 ${GATE.min_test_trades}건 이상 · 손익비 ${GATE.min_test_pf} 이상 · 두 구간 모두 이익이어야 통과. 거래가 너무 드문 조건은 통과하지 못한다.

지표 표 (type: 출력들 / 파라미터 기본값 — 설명)
${IND_TABLE}

리스크 필드 (risk)
${RISK_TABLE}

예시 1 (양방향 추세추종)
${JSON.stringify(EX1)}

예시 2 (롱 전용 역추세)
${JSON.stringify(EX2)}
`;

/* ============ 연구 카드 (knowledge/cards.json) ============ */
const STATUS_KO = {validated: "검증", rejected: "기각", hypothesis: "가설"};
export const CARDS_HEADLINE = "연구 결과 요약: 5분~1일봉에서 약 3,500개 셋업(지표·주문흐름·호가·펀딩·시간대·유명 매매법)을 백테스트했지만 "
  + "확인 구간(out-of-sample)을 통과한 것은 0개였다. 단기봉은 왕복 비용 약 0.14% 가 기대값을 지배하고, "
  + "고레버리지는 수학적으로 불리하다. 그러니 확신을 과장하지 말고, 비용·레버리지·표본 수를 먼저 따진다.";
let _cards = null;
// ./quant-cards.json 읽기 (브라우저는 fetch, Node 의 file: URL 은 fs)
export async function loadCards(){
  if (_cards) return _cards;
  const url = new URL("./quant-cards.json", import.meta.url);
  try {
    if (url.protocol === "file:"){
      const fs = await import("node:" + "fs/promises");
      _cards = JSON.parse(await fs.readFile(url, "utf8"));
    } else {
      const r = await fetch(url);
      if (!r.ok) throw new Error("HTTP " + r.status);
      _cards = await r.json();
    }
  } catch(e){ console.warn("연구 카드 읽기 실패:", e.message); return []; }
  return _cards;
}
const cmpStr = (a, b) => a < b ? -1 : a > b ? 1 : 0;
// 해당 코인·봉에 맞는 카드부터 (검증 → 기각 → 가설). knowledge.relevant 와 같은 몫 배분
export function relevantCards(cards, n = 14, {symbol = null, interval = null} = {}){
  const order = {validated: 0, rejected: 1, hypothesis: 2}, o = c => order[c.status] ?? 3;
  const base = symbol ? String(symbol).toUpperCase().replace(/USDT$/, "").replace(/USDC$/, "") : null;
  const applies = c => {
    const a = c.applies || {}, tf = a.timeframes, sy = a.symbols;
    if (interval && Array.isArray(tf) && !tf.includes(interval)) return false;
    if (base && Array.isArray(sy) && !sy.includes(base)) return false;
    return true;
  };
  const cs = [...(cards || [])].sort((a, b) => o(a) - o(b) || cmpStr(a.id, b.id));
  const hit = cs.filter(applies);
  hit.push(...cs.filter(c => !hit.includes(c) && (c.applies || {}).timeframes === "all"));
  const quota = {validated: pyRound(n * .62), rejected: pyRound(n * .28), hypothesis: 1};
  let out = [];
  for (const [st, q] of Object.entries(quota)) out.push(...hit.filter(c => c.status === st).slice(0, q));
  out.push(...hit.filter(c => !out.includes(c)));
  return out.slice(0, n).sort((a, b) => o(a) - o(b) || cmpStr(a.id, b.id));
}
// 프롬프트용 짧은 요약 (knowledge.brief). opts: {symbol, interval, headline=true}
export function cardsText(cards, n = 14, opts = {}){
  const rows = relevantCards(cards, n, opts).map(c => `- [${c.id}·${STATUS_KO[c.status] || c.status}·${c.topic}] ${c.rule}`);
  if (!rows.length) return "";
  return (opts.headline === false ? "" : CARDS_HEADLINE + "\n") + rows.join("\n");
}

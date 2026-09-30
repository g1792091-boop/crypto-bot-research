// 자체 보조지표 라이브러리 (브라우저에서 계산 — 개수 제한 없음)
// 공식은 TradingView Pine ta.* 와 같게 맞춤 (EMA/RMA SMA 시드, RSI/ATR Wilder 등)

const N = (x) => x == null || Number.isNaN(x) ? null : x;
export const src = (c, s = "close") => c.map((b) => s === "hlc3" ? (b.high + b.low + b.close) / 3 : s === "hl2" ? (b.high + b.low) / 2
  : s === "ohlc4" ? (b.open + b.high + b.low + b.close) / 4 : b[s]);

export function sma(x, n) {
  const o = Array(x.length).fill(null); let s = 0, k = 0;
  for (let i = 0; i < x.length; i++) {
    if (x[i] == null) { s = 0; k = 0; continue; }
    s += x[i]; k++;
    if (k > n) { s -= x[i - n]; k--; }
    if (k === n) o[i] = s / n;
  }
  return o;
}
function smooth(x, n, a) {
  const o = Array(x.length).fill(null); let prev = null, seed = [];
  for (let i = 0; i < x.length; i++) {
    const v = x[i]; if (v == null) continue;
    if (prev == null) { seed.push(v); if (seed.length === n) { prev = seed.reduce((p, q) => p + q, 0) / n; o[i] = prev; } continue; }
    prev = a * v + (1 - a) * prev; o[i] = prev;
  }
  return o;
}
export const ema = (x, n) => smooth(x, n, 2 / (n + 1));
export const rma = (x, n) => smooth(x, n, 1 / n);
export function wma(x, n) {
  const o = Array(x.length).fill(null), d = n * (n + 1) / 2;
  for (let i = n - 1; i < x.length; i++) {
    let s = 0, ok = true;
    for (let j = 0; j < n; j++) { const v = x[i - j]; if (v == null) { ok = false; break; } s += v * (n - j); }
    if (ok) o[i] = s / d;
  }
  return o;
}
export function stdev(x, n) {
  const m = sma(x, n);
  return x.map((_, i) => { if (m[i] == null) return null; let s = 0; for (let j = i - n + 1; j <= i; j++) s += (x[j] - m[i]) ** 2; return Math.sqrt(s / n); });
}
export const highest = (x, n) => x.map((_, i) => i < n - 1 ? null : Math.max(...x.slice(i - n + 1, i + 1)));
export const lowest = (x, n) => x.map((_, i) => i < n - 1 ? null : Math.min(...x.slice(i - n + 1, i + 1)));
export const tr = (c) => c.map((b, i) => i ? Math.max(b.high - b.low, Math.abs(b.high - c[i - 1].close), Math.abs(b.low - c[i - 1].close)) : b.high - b.low);
export const atr = (c, n = 14) => rma(tr(c), n);
const sub = (a, b) => a.map((v, i) => v == null || b[i] == null ? null : v - b[i]);
const change = (x, n = 1) => x.map((v, i) => i < n || v == null || x[i - n] == null ? null : v - x[i - n]);
export function rsi(x, n = 14) {
  const up = [null], dn = [null];
  for (let i = 1; i < x.length; i++) { const d = x[i] - x[i - 1]; up.push(Math.max(d, 0)); dn.push(Math.max(-d, 0)); }
  const u = rma(up, n), d = rma(dn, n);
  return x.map((_, i) => u[i] == null || d[i] == null ? null : d[i] === 0 ? 100 : u[i] === 0 ? 0 : 100 - 100 / (1 + u[i] / d[i]));
}
function linreg(x, n) {
  return x.map((_, i) => {
    if (i < n - 1) return null;
    let sx = 0, sy = 0, sxy = 0, sxx = 0;
    for (let j = 0; j < n; j++) { const y = x[i - n + 1 + j]; if (y == null) return null; sx += j; sy += y; sxy += j * y; sxx += j * j; }
    const slope = (n * sxy - sx * sy) / (n * sxx - sx * sx), icpt = (sy - slope * sx) / n;
    return icpt + slope * (n - 1);
  });
}
function stochK(c, x, n) {
  const hi = highest(c.map((b) => b.high), n), lo = lowest(c.map((b) => b.low), n);
  return x.map((v, i) => hi[i] == null ? null : hi[i] === lo[i] ? 50 : 100 * (v - lo[i]) / (hi[i] - lo[i]));
}
function stochOf(x, n) {
  return x.map((v, i) => {
    if (i < n - 1 || v == null) return null;
    const w = x.slice(i - n + 1, i + 1); if (w.some((q) => q == null)) return null;
    const h = Math.max(...w), l = Math.min(...w); return h === l ? 50 : 100 * (v - l) / (h - l);
  });
}
function dmi(c, n = 14) {
  const pdm = [null], mdm = [null];
  for (let i = 1; i < c.length; i++) {
    const up = c[i].high - c[i - 1].high, dn = c[i - 1].low - c[i].low;
    pdm.push(up > dn && up > 0 ? up : 0); mdm.push(dn > up && dn > 0 ? dn : 0);
  }
  const t = [null, ...rma(tr(c).slice(1), n)], p = rma(pdm, n), m = rma(mdm, n);
  const pdi = p.map((v, i) => v == null || !t[i] ? null : 100 * v / t[i]), mdi = m.map((v, i) => v == null || !t[i] ? null : 100 * v / t[i]);
  const dx = pdi.map((v, i) => v == null || mdi[i] == null ? null : v + mdi[i] === 0 ? 0 : 100 * Math.abs(v - mdi[i]) / (v + mdi[i]));
  return { adx: rma(dx, n), pdi, mdi };
}
function supertrend(c, n = 10, mult = 3) {
  const a = atr(c, n), line = Array(c.length).fill(null), dir = Array(c.length).fill(null);
  let pu = null, pd = null, ps = null;
  for (let i = 0; i < c.length; i++) {
    if (a[i] == null) continue;
    const hl2 = (c[i].high + c[i].low) / 2; let up = hl2 - mult * a[i], dn = hl2 + mult * a[i]; const pc = c[i - 1]?.close;
    if (pu != null && pc >= pu) up = Math.max(up, pu);
    if (pd != null && pc <= pd) dn = Math.min(dn, pd);
    let d; if (ps == null) d = 1; else if (ps === pd) d = c[i].close > dn ? -1 : 1; else d = c[i].close < up ? 1 : -1;
    const st = d === -1 ? up : dn; line[i] = st; dir[i] = -d; pu = up; pd = dn; ps = st;
  }
  return { line, dir };
}

// ---------------------------------------------------------------- 레지스트리
// pane: "main" = 가격 위에 겹침, "sub" = 아래 별도 창, remote = 서버에서 받아오는 데이터
// compute(c, p, ext) → { plots: [{name, type: line|hist|dots, data: number[] (캔들과 같은 길이), color, colors?}], levels: [] }
const C = { a: "#f5a524", b: "#3987e5", c: "#d55181", d: "#199e70", e: "#9085e9", f: "#e66767", g: "#a4acb6", up: "#22b07d", dn: "#e5484d" };
const line = (name, data, color, extra = {}) => ({ name, type: "line", data, color, ...extra });
const hist = (name, data, colors) => ({ name, type: "hist", data, colors });
const signColors = (x) => x.map((v, i) => v == null ? null : v >= 0 ? (v >= (x[i - 1] ?? -Infinity) ? "rgba(34,176,125,.9)" : "rgba(34,176,125,.45)")
  : (v <= (x[i - 1] ?? Infinity) ? "rgba(229,72,77,.9)" : "rgba(229,72,77,.45)"));

export const INDICATORS = {
  // ---------- 추세 (가격 위)
  ema: { name: "EMA", group: "추세", pane: "main", params: { length: 20 }, compute: (c, p) => ({ plots: [line(`EMA ${p.length}`, ema(src(c), p.length), C.a)] }) },
  sma: { name: "SMA", group: "추세", pane: "main", params: { length: 50 }, compute: (c, p) => ({ plots: [line(`SMA ${p.length}`, sma(src(c), p.length), C.b)] }) },
  wma: { name: "WMA", group: "추세", pane: "main", params: { length: 20 }, compute: (c, p) => ({ plots: [line(`WMA ${p.length}`, wma(src(c), p.length), C.e)] }) },
  hma: { name: "HMA (헐 이동평균)", group: "추세", pane: "main", params: { length: 55 }, compute: (c, p) => {
    const x = src(c), h = Math.round(p.length / 2), s = Math.round(Math.sqrt(p.length));
    return { plots: [line(`HMA ${p.length}`, wma(sub(wma(x, h).map((v) => v == null ? null : 2 * v), wma(x, p.length)), s), C.c)] };
  } },
  vwma: { name: "VWMA (거래량 가중)", group: "추세", pane: "main", params: { length: 20 }, compute: (c, p) => {
    const pv = sma(c.map((b) => b.close * b.volume), p.length), v = sma(c.map((b) => b.volume), p.length);
    return { plots: [line(`VWMA ${p.length}`, pv.map((x, i) => x == null || !v[i] ? null : x / v[i]), C.d)] };
  } },
  ema_ribbon: { name: "EMA 리본 (20/50/100/200)", group: "추세", pane: "main", params: {}, compute: (c) => {
    const x = src(c); return { plots: [[20, C.a], [50, C.b], [100, C.e], [200, C.c]].map(([n, col]) => line(`EMA ${n}`, ema(x, n), col, { lineWidth: 1 })) };
  } },
  supertrend: { name: "슈퍼트렌드", group: "추세", pane: "main", params: { length: 10, mult: 3 }, compute: (c, p) => {
    const s = supertrend(c, p.length, p.mult);
    return { plots: [line("상승", s.line.map((v, i) => s.dir[i] === 1 ? v : null), C.up, { lineWidth: 2 }),
      line("하락", s.line.map((v, i) => s.dir[i] === -1 ? v : null), C.dn, { lineWidth: 2 })] };
  } },
  psar: { name: "파라볼릭 SAR", group: "추세", pane: "main", params: { start: 0.02, inc: 0.02, max: 0.2 }, compute: (c, p) => {
    const o = Array(c.length).fill(null); if (c.length < 3) return { plots: [] };
    let up = c[1].close >= c[0].close, af = p.start, ep = up ? c[1].high : c[1].low, sar = up ? c[0].low : c[0].high;
    for (let i = 2; i < c.length; i++) {
      sar = sar + af * (ep - sar);
      if (up) { sar = Math.min(sar, c[i - 1].low, c[i - 2].low); if (c[i].low < sar) { up = false; sar = ep; ep = c[i].low; af = p.start; } else if (c[i].high > ep) { ep = c[i].high; af = Math.min(af + p.inc, p.max); } }
      else { sar = Math.max(sar, c[i - 1].high, c[i - 2].high); if (c[i].high > sar) { up = true; sar = ep; ep = c[i].high; af = p.start; } else if (c[i].low < ep) { ep = c[i].low; af = Math.min(af + p.inc, p.max); } }
      o[i] = sar;
    }
    return { plots: [{ name: "SAR", type: "dots", data: o, color: C.g }] };
  } },
  ichimoku: { name: "일목균형표", group: "추세", pane: "main", params: { conv: 9, base: 26, span: 52 }, compute: (c, p) => {
    const mid = (n) => { const h = highest(c.map((b) => b.high), n), l = lowest(c.map((b) => b.low), n); return h.map((v, i) => v == null ? null : (v + l[i]) / 2); };
    const t = mid(p.conv), k = mid(p.base), sb = mid(p.span), sa = t.map((v, i) => v == null || k[i] == null ? null : (v + k[i]) / 2);
    const shift = (x, n) => x.map((_, i) => i - n + 1 >= 0 ? x[i - n + 1] : null);
    return { plots: [line("전환선", t, C.b, { lineWidth: 1 }), line("기준선", k, C.f, { lineWidth: 1 }),
      line("선행스팬1", shift(sa, p.base), "rgba(34,176,125,.7)", { lineWidth: 1 }), line("선행스팬2", shift(sb, p.base), "rgba(229,72,77,.7)", { lineWidth: 1 }),
      line("후행스팬", c.map((_, i) => c[i + p.base - 1]?.close ?? null), "rgba(164,172,182,.6)", { lineWidth: 1 })] };
  } },
  vwap: { name: "VWAP (일간)", group: "추세", pane: "main", params: {}, compute: (c) => {
    let day = null, pv = 0, v = 0;
    return { plots: [line("VWAP", c.map((b) => { const d = Math.floor(b.time / 86400); if (d !== day) { day = d; pv = 0; v = 0; } const tp = (b.high + b.low + b.close) / 3; pv += tp * b.volume; v += b.volume; return v ? pv / v : tp; }), C.c, { lineWidth: 2 })] };
  } },
  pivots: { name: "피봇 포인트 (일간 클래식)", group: "추세", pane: "main", params: {}, compute: (c) => {
    const days = {}; c.forEach((b) => { const d = Math.floor(b.time / 86400); const x = days[d] ||= { h: -Infinity, l: Infinity, c: 0 }; x.h = Math.max(x.h, b.high); x.l = Math.min(x.l, b.low); x.c = b.close; });
    const lv = { P: [], R1: [], S1: [], R2: [], S2: [] };
    c.forEach((b) => { const y = days[Math.floor(b.time / 86400) - 1]; if (!y) { Object.values(lv).forEach((a) => a.push(null)); return; }
      const P = (y.h + y.l + y.c) / 3; lv.P.push(P); lv.R1.push(2 * P - y.l); lv.S1.push(2 * P - y.h); lv.R2.push(P + y.h - y.l); lv.S2.push(P - (y.h - y.l)); });
    return { plots: [line("P", lv.P, C.a, { lineWidth: 1 }), line("R1", lv.R1, C.dn, { lineWidth: 1 }), line("R2", lv.R2, C.dn, { lineWidth: 1, lineStyle: 2 }),
      line("S1", lv.S1, C.up, { lineWidth: 1 }), line("S2", lv.S2, C.up, { lineWidth: 1, lineStyle: 2 })] };
  } },
  // ---------- 변동성 (가격 위)
  bb: { name: "볼린저 밴드", group: "변동성", pane: "main", params: { length: 20, mult: 2 }, compute: (c, p) => {
    const x = src(c), m = sma(x, p.length), sd = stdev(x, p.length);
    return { plots: [line("상단", m.map((v, i) => v == null ? null : v + p.mult * sd[i]), C.b, { lineWidth: 1 }), line("중심", m, "rgba(245,165,36,.7)", { lineWidth: 1 }),
      line("하단", m.map((v, i) => v == null ? null : v - p.mult * sd[i]), C.b, { lineWidth: 1 })] };
  } },
  keltner: { name: "켈트너 채널", group: "변동성", pane: "main", params: { length: 20, mult: 2 }, compute: (c, p) => {
    const m = ema(src(c), p.length), a = atr(c, 10);
    return { plots: [line("상단", m.map((v, i) => v == null || a[i] == null ? null : v + p.mult * a[i]), C.e, { lineWidth: 1 }), line("중심", m, "rgba(144,133,233,.6)", { lineWidth: 1 }),
      line("하단", m.map((v, i) => v == null || a[i] == null ? null : v - p.mult * a[i]), C.e, { lineWidth: 1 })] };
  } },
  donchian: { name: "돈치안 채널", group: "변동성", pane: "main", params: { length: 20 }, compute: (c, p) => {
    const h = highest(c.map((b) => b.high), p.length), l = lowest(c.map((b) => b.low), p.length);
    return { plots: [line("상단", h, C.d, { lineWidth: 1 }), line("중간", h.map((v, i) => v == null ? null : (v + l[i]) / 2), "rgba(25,158,112,.5)", { lineWidth: 1, lineStyle: 2 }), line("하단", l, C.d, { lineWidth: 1 })] };
  } },
  envelope: { name: "엔벨로프", group: "변동성", pane: "main", params: { length: 20, pct: 3 }, compute: (c, p) => {
    const m = sma(src(c), p.length);
    return { plots: [line("상단", m.map((v) => v == null ? null : v * (1 + p.pct / 100)), C.g, { lineWidth: 1 }), line("하단", m.map((v) => v == null ? null : v * (1 - p.pct / 100)), C.g, { lineWidth: 1 })] };
  } },
  // ---------- 오실레이터 (아래 창)
  rsi: { name: "RSI", group: "오실레이터", pane: "sub", params: { length: 14 }, compute: (c, p) => ({ plots: [line(`RSI ${p.length}`, rsi(src(c), p.length), C.e)], levels: [30, 50, 70] }) },
  stochrsi: { name: "스토캐스틱 RSI", group: "오실레이터", pane: "sub", params: { rsi: 14, stoch: 14, k: 3, d: 3 }, compute: (c, p) => {
    const k = sma(stochOf(rsi(src(c), p.rsi), p.stoch), p.k); return { plots: [line("%K", k, C.b), line("%D", sma(k, p.d), C.a)], levels: [20, 80] };
  } },
  stoch: { name: "스토캐스틱", group: "오실레이터", pane: "sub", params: { length: 14, k: 3, d: 3 }, compute: (c, p) => {
    const k = sma(stochK(c, src(c), p.length), p.k); return { plots: [line("%K", k, C.b), line("%D", sma(k, p.d), C.a)], levels: [20, 80] };
  } },
  macd: { name: "MACD", group: "오실레이터", pane: "sub", params: { fast: 12, slow: 26, signal: 9 }, compute: (c, p) => {
    const m = sub(ema(src(c), p.fast), ema(src(c), p.slow)), s = ema(m, p.signal), h = sub(m, s);
    return { plots: [hist("히스토그램", h, signColors(h)), line("MACD", m, C.b), line("시그널", s, C.a)], levels: [0] };
  } },
  cci: { name: "CCI", group: "오실레이터", pane: "sub", params: { length: 20 }, compute: (c, p) => {
    const tp = src(c, "hlc3"), m = sma(tp, p.length);
    return { plots: [line("CCI", tp.map((v, i) => { if (m[i] == null) return null; let d = 0; for (let j = i - p.length + 1; j <= i; j++) d += Math.abs(tp[j] - m[i]); d /= p.length; return d ? (v - m[i]) / (0.015 * d) : 0; }), C.d)], levels: [-100, 0, 100] };
  } },
  willr: { name: "윌리엄스 %R", group: "오실레이터", pane: "sub", params: { length: 14 }, compute: (c, p) => ({ plots: [line("%R", stochK(c, src(c), p.length).map((v) => v == null ? null : v - 100), C.c)], levels: [-80, -20] }) },
  mfi: { name: "MFI (자금 흐름)", group: "오실레이터", pane: "sub", params: { length: 14 }, compute: (c, p) => {
    const tp = src(c, "hlc3"), pos = [null], neg = [null];
    for (let i = 1; i < c.length; i++) { const f = tp[i] * c[i].volume; pos.push(tp[i] > tp[i - 1] ? f : 0); neg.push(tp[i] < tp[i - 1] ? f : 0); }
    const sp = sma(pos, p.length), sn = sma(neg, p.length);
    return { plots: [line("MFI", sp.map((v, i) => v == null ? null : sn[i] === 0 ? 100 : 100 - 100 / (1 + v / sn[i])), C.d)], levels: [20, 80] };
  } },
  adx: { name: "ADX / DMI", group: "오실레이터", pane: "sub", params: { length: 14 }, compute: (c, p) => {
    const d = dmi(c, p.length); return { plots: [line("ADX", d.adx, C.a, { lineWidth: 2 }), line("+DI", d.pdi, C.up, { lineWidth: 1 }), line("-DI", d.mdi, C.dn, { lineWidth: 1 })], levels: [20, 25] };
  } },
  atr: { name: "ATR", group: "변동성", pane: "sub", params: { length: 14 }, compute: (c, p) => ({ plots: [line(`ATR ${p.length}`, atr(c, p.length), C.f)] }) },
  bbw: { name: "볼린저 밴드 폭 (%)", group: "변동성", pane: "sub", params: { length: 20, mult: 2 }, compute: (c, p) => {
    const x = src(c), m = sma(x, p.length), sd = stdev(x, p.length); return { plots: [line("BBW", m.map((v, i) => v ? 2 * p.mult * sd[i] / v * 100 : null), C.b)] };
  } },
  chop: { name: "초피니스 지수 (횡보 판별)", group: "변동성", pane: "sub", params: { length: 14 }, compute: (c, p) => {
    const t = tr(c), h = highest(c.map((b) => b.high), p.length), l = lowest(c.map((b) => b.low), p.length);
    return { plots: [line("CHOP", c.map((_, i) => { if (h[i] == null || i < p.length) return null; let s = 0; for (let j = i - p.length + 1; j <= i; j++) s += t[j]; return h[i] > l[i] ? 100 * Math.log10(s / (h[i] - l[i])) / Math.log10(p.length) : null; }), C.a)], levels: [38.2, 61.8] };
  } },
  squeeze: { name: "스퀴즈 모멘텀 (LazyBear)", group: "오실레이터", pane: "sub", params: { length: 20, bb: 2, kc: 1.5 }, compute: (c, p) => {
    const x = src(c), n = p.length, h = highest(c.map((b) => b.high), n), l = lowest(c.map((b) => b.low), n), m = sma(x, n);
    const val = linreg(x.map((v, i) => h[i] == null || m[i] == null ? null : v - ((h[i] + l[i]) / 2 + m[i]) / 2), n);
    return { plots: [hist("모멘텀", val, signColors(val))], levels: [0] };
  } },
  wavetrend: { name: "웨이브트렌드 (LazyBear)", group: "오실레이터", pane: "sub", params: { n1: 10, n2: 21 }, compute: (c, p) => {
    const ap = src(c, "hlc3"), esa = ema(ap, p.n1), d = ema(ap.map((v, i) => esa[i] == null ? null : Math.abs(v - esa[i])), p.n1);
    const wt1 = ema(ap.map((v, i) => esa[i] == null || !d[i] ? null : (v - esa[i]) / (0.015 * d[i])), p.n2), wt2 = sma(wt1, 4);
    return { plots: [line("WT1", wt1, C.up), line("WT2", wt2, C.dn), hist("차이", sub(wt1, wt2), sub(wt1, wt2).map((v) => v == null ? null : "rgba(59,130,246,.35)"))], levels: [-60, -53, 0, 53, 60] };
  } },
  ao: { name: "어썸 오실레이터", group: "오실레이터", pane: "sub", params: {}, compute: (c) => { const m = src(c, "hl2"), a = sub(sma(m, 5), sma(m, 34)); return { plots: [hist("AO", a, signColors(a))], levels: [0] }; } },
  roc: { name: "ROC (변화율 %)", group: "오실레이터", pane: "sub", params: { length: 9 }, compute: (c, p) => { const x = src(c); return { plots: [line("ROC", x.map((v, i) => i < p.length ? null : (v / x[i - p.length] - 1) * 100), C.b)], levels: [0] }; } },
  trix: { name: "TRIX", group: "오실레이터", pane: "sub", params: { length: 18 }, compute: (c, p) => { const t = ema(ema(ema(src(c).map(Math.log), p.length), p.length), p.length); return { plots: [line("TRIX", change(t).map((v) => v == null ? null : v * 10000), C.c)], levels: [0] }; } },
  aroon: { name: "아룬", group: "오실레이터", pane: "sub", params: { length: 14 }, compute: (c, p) => {
    const n = p.length, up = [], dn = [];
    c.forEach((_, i) => { if (i < n) { up.push(null); dn.push(null); return; } let hi = i, lo = i; for (let j = i - n; j <= i; j++) { if (c[j].high >= c[hi].high) hi = j; if (c[j].low <= c[lo].low) lo = j; } up.push(100 * (n - (i - hi)) / n); dn.push(100 * (n - (i - lo)) / n); });
    return { plots: [line("Up", up, C.up), line("Down", dn, C.dn)], levels: [30, 70] };
  } },
  // ---------- 거래량
  volume: { name: "거래량", group: "거래량", pane: "volume", params: { ma: 20 }, compute: (c, p) => ({
    plots: [hist("거래량", c.map((b) => b.volume), c.map((b) => b.close >= b.open ? "rgba(34,176,125,.45)" : "rgba(229,72,77,.45)")),
      line(`MA ${p.ma}`, sma(c.map((b) => b.volume), p.ma), "rgba(245,165,36,.8)", { lineWidth: 1 })] }) },
  obv: { name: "OBV", group: "거래량", pane: "sub", params: {}, compute: (c) => { let s = 0; return { plots: [line("OBV", c.map((b, i) => { if (i) s += b.close > c[i - 1].close ? b.volume : b.close < c[i - 1].close ? -b.volume : 0; return s; }), C.b)] }; } },
  cmf: { name: "CMF (차이킨 자금 흐름)", group: "거래량", pane: "sub", params: { length: 20 }, compute: (c, p) => {
    const mfv = c.map((b) => b.high === b.low ? 0 : ((b.close - b.low) - (b.high - b.close)) / (b.high - b.low) * b.volume);
    const a = sma(mfv, p.length), v = sma(c.map((b) => b.volume), p.length); return { plots: [line("CMF", a.map((x, i) => x == null || !v[i] ? null : x / v[i]), C.d)], levels: [0] };
  } },
  cvd: { name: "CVD (누적 체결 강도)", group: "거래량", pane: "sub", params: {}, compute: (c) => {
    let s = 0; return { plots: [line("CVD", c.map((b) => { const buy = b.taker_buy ?? b.volume / 2; s += buy - (b.volume - buy); return s; }), C.a, { lineWidth: 2 })] };
  } },
  delta: { name: "매수-매도 체결량 (델타)", group: "거래량", pane: "sub", params: {}, compute: (c) => {
    const d = c.map((b) => { const buy = b.taker_buy ?? b.volume / 2; return buy - (b.volume - buy); }); return { plots: [hist("델타", d, signColors(d))], levels: [0] };
  } },
  // ---------- 파생 · 코인글라스 (서버 데이터)
  oi: { name: "미결제약정 (OI)", group: "파생 · 코인글라스", pane: "sub", remote: "derivatives", params: {}, compute: (c, p, ext) => ({ plots: [line("OI", align(c, ext?.open_interest), C.b, { lineWidth: 2 })] }) },
  oi_delta: { name: "OI 변화량", group: "파생 · 코인글라스", pane: "sub", remote: "derivatives", params: {}, compute: (c, p, ext) => { const o = change(align(c, ext?.open_interest)); return { plots: [hist("OI 변화", o, signColors(o))], levels: [0] }; } },
  funding: { name: "펀딩비 (%)", group: "파생 · 코인글라스", pane: "sub", remote: "derivatives", params: {}, compute: (c, p, ext) => { const f = align(c, ext?.funding); return { plots: [hist("펀딩비", f, f.map((v) => v == null ? null : v >= 0 ? "rgba(34,176,125,.7)" : "rgba(229,72,77,.7)"))], levels: [0, 0.01] }; } },
  long_short: { name: "롱/숏 계정 비율", group: "파생 · 코인글라스", pane: "sub", remote: "derivatives", params: {}, compute: (c, p, ext) => ({ plots: [line("롱/숏", align(c, ext?.long_short), C.d, { lineWidth: 2 })], levels: [1] }) },
  taker: { name: "테이커 매수/매도 비율", group: "파생 · 코인글라스", pane: "sub", remote: "derivatives", params: {}, compute: (c, p, ext) => ({ plots: [line("매수/매도", align(c, ext?.taker), C.a)], levels: [1] }) },
  liq: { name: "청산량 (롱/숏, CoinGlass)", group: "파생 · 코인글라스", pane: "sub", remote: "derivatives", params: {}, compute: (c, p, ext) => {
    const L = align(c, (ext?.liquidations || []).map((x) => ({ time: x.time, value: x.long_usd })), false), S = align(c, (ext?.liquidations || []).map((x) => ({ time: x.time, value: -x.short_usd })), false);
    return { plots: [hist("롱 청산", L, L.map(() => "rgba(229,72,77,.8)")), hist("숏 청산", S, S.map(() => "rgba(34,176,125,.8)"))], levels: [0], note: ext?.liquidations?.length ? "" : "CoinGlass 키 필요" };
  } },
  cb_premium: { name: "코인베이스 프리미엄 (%)", group: "파생 · 코인글라스", pane: "sub", remote: "cbp", params: {}, compute: (c, p, ext) => { const v = align(c, ext?.series); return { plots: [hist("프리미엄", v, v.map((x) => x == null ? null : x >= 0 ? "rgba(34,176,125,.7)" : "rgba(229,72,77,.7)"))], levels: [0] }; } },
};

// 서버 시계열 (time, value) → 캔들 시간축 (forward-fill)
export function align(c, pts, ffill = true) {
  const out = Array(c.length).fill(null);
  if (!pts?.length) return out;
  const s = [...pts].sort((a, b) => a.time - b.time);
  let j = 0, last = null;
  for (let i = 0; i < c.length; i++) {
    let hit = null;
    while (j < s.length && s[j].time <= c[i].time) { last = s[j].value; if (s[j].time >= (c[i - 1]?.time ?? -Infinity) + 1) hit = s[j].value; j++; }
    out[i] = ffill ? last : hit;
  }
  return out;
}

export const DEFAULT_INDICATORS = [
  { key: "volume", params: { ma: 20 } }, { key: "ema", params: { length: 20 } }, { key: "ema", params: { length: 50 } },
  { key: "rsi", params: { length: 14 } }, { key: "macd", params: { fast: 12, slow: 26, signal: 9 } },
];
export { N };

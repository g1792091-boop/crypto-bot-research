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
    // 스퀴즈 상태: 볼린저 밴드가 켈트너 채널 안으로 들어가면 (빨간 점) 변동성 압축 → 곧 큰 움직임
    const sd = stdev(x, n), rg = sma(tr(c), n);
    const on = m.map((v, i) => v == null || sd[i] == null || rg[i] == null ? null : v - p.bb * sd[i] > v - p.kc * rg[i] && v + p.bb * sd[i] < v + p.kc * rg[i]);
    return { plots: [hist("모멘텀", val, signColors(val)), { name: "스퀴즈", type: "dots", legend: false, data: on.map((o) => o == null ? null : 0), color: C.g,
      colors: on.map((o) => o == null ? null : o ? "#e5484d" : "#6b7785") }], levels: [0] };
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

// ---------------------------------------------------------------- 추가 지표용 도구
const add = (a, b) => a.map((v, i) => v == null || b[i] == null ? null : v + b[i]);
const mul = (a, k) => a.map((v) => v == null ? null : v * k);
const ratio = (a, b) => a.map((v, i) => v == null || b[i] == null || b[i] === 0 ? null : v / b[i]);
const sum = (x, n) => mul(sma(x, n), n);
const shift = (x, n) => x.map((_, i) => i - n >= 0 ? x[i - n] : null);
const roc = (x, n) => x.map((v, i) => i < n || v == null || !x[i - n] ? null : (v / x[i - n] - 1) * 100);
const cum = (x) => { let s = 0; return x.map((v) => (s += v ?? 0)); };
const swma = (x) => x.map((v, i) => i < 3 || [v, x[i - 1], x[i - 2], x[i - 3]].some((q) => q == null) ? null : (x[i - 3] + 2 * x[i - 2] + 2 * x[i - 1] + v) / 6);
const prevClose = (c) => c.map((b, i) => i ? c[i - 1].close : null);
const upDown = (x, n) => {   // n봉 동안 오른 폭 합, 내린 폭 합
  const ch = change(x);
  return [sum(ch.map((v) => v == null ? null : Math.max(v, 0)), n), sum(ch.map((v) => v == null ? null : Math.max(-v, 0)), n)];
};
function dema(x, n) { const e = ema(x, n), e2 = ema(e, n); return e.map((v, i) => e2[i] == null ? null : 2 * v - e2[i]); }
function tema(x, n) { const e = ema(x, n), e2 = ema(e, n), e3 = ema(e2, n); return e.map((v, i) => e3[i] == null ? null : 3 * (v - e2[i]) + e3[i]); }
function alma(x, n, off, sig) {
  const m = off * (n - 1), s = n / sig, w = Array.from({ length: n }, (_, j) => Math.exp(-((j - m) ** 2) / (2 * s * s))), ws = w.reduce((a, b) => a + b, 0);
  return x.map((_, i) => { if (i < n - 1) return null; let t = 0; for (let j = 0; j < n; j++) { const v = x[i - n + 1 + j]; if (v == null) return null; t += v * w[j]; } return t / ws; });
}
function kama(x, n, fast, slow) {
  const o = Array(x.length).fill(null), fs = 2 / (fast + 1), ss = 2 / (slow + 1);
  for (let i = n; i < x.length; i++) {
    let vol = 0; for (let j = i - n + 1; j <= i; j++) vol += Math.abs(x[j] - x[j - 1]);
    const er = vol ? Math.abs(x[i] - x[i - n]) / vol : 0, sc = (er * (fs - ss) + ss) ** 2, prev = o[i - 1] ?? x[i - 1];
    o[i] = prev + sc * (x[i] - prev);
  }
  return o;
}
function mcginley(x, n) {
  const e = ema(x, n); let mg = null;
  return x.map((v, i) => { if (mg == null) return (mg = e[i]); mg += (v - mg) / (n * (v / mg) ** 4); return mg; });
}
function pivots(x, left, right, high) {   // 좌우 left/right 봉보다 높은(낮은) 점. right 봉 뒤에 확정된다
  const o = [];
  for (let i = left; i < x.length - right; i++) {
    let ok = x[i] != null;
    for (let j = i - left; ok && j <= i + right; j++) if (j !== i && (x[j] == null || (high ? (j < i ? x[j] >= x[i] : x[j] > x[i]) : (j < i ? x[j] <= x[i] : x[j] < x[i])))) ok = false;
    if (ok) o.push(i);
  }
  return o;
}
function percentrank(x, n) {
  return x.map((v, i) => { if (i < n || v == null) return null; let k = 0; for (let j = i - n; j < i; j++) { if (x[j] == null) return null; if (x[j] <= v) k++; } return 100 * k / n; });
}
const sig = (n) => Array(n).fill(null);
const crossSignals = (a, b, up, dn) => a.map((v, i) => i && v != null && b[i] != null && a[i - 1] != null && b[i - 1] != null
  ? (a[i - 1] <= b[i - 1] && v > b[i] ? { dir: 1, text: up } : a[i - 1] >= b[i - 1] && v < b[i] ? { dir: -1, text: dn } : null) : null);
const MA = { 1: sma, 2: ema, 3: wma, 4: rma };   // 이평 종류 파라미터: 1=SMA 2=EMA 3=WMA 4=RMA

// 볼륨 프로파일 (차트가 보이는 구간의 캔들로 계산해서 그린다)
export function volumeProfile(c, rows = 24, vaPct = 70) {
  if (!c.length) return null;
  let lo = Infinity, hi = -Infinity;
  for (const b of c) { lo = Math.min(lo, b.low); hi = Math.max(hi, b.high); }
  if (!(hi > lo)) return null;
  const step = (hi - lo) / rows, bins = Array.from({ length: rows }, (_, k) => ({ lo: lo + k * step, hi: lo + (k + 1) * step, buy: 0, sell: 0 }));
  for (const b of c) {
    const a = Math.max(0, Math.floor((b.low - lo) / step)), z = Math.min(rows - 1, Math.floor((b.high - lo) / step));
    const buy = b.taker_buy ?? b.volume / 2, part = 1 / (z - a + 1);
    for (let k = a; k <= z; k++) { bins[k].buy += buy * part; bins[k].sell += (b.volume - buy) * part; }
  }
  const tot = bins.map((x) => x.buy + x.sell), all = tot.reduce((p, q) => p + q, 0);
  let poc = tot.indexOf(Math.max(...tot)), a = poc, z = poc, acc = tot[poc];
  while (acc < all * vaPct / 100 && (a > 0 || z < rows - 1)) {
    const up = z < rows - 1 ? tot[z + 1] : -1, dn = a > 0 ? tot[a - 1] : -1;
    if (up >= dn) acc += tot[++z]; else acc += tot[--a];
  }
  bins.forEach((x, k) => { x.total = tot[k]; x.va = k >= a && k <= z; });
  return { bins, max: Math.max(...tot), poc: (bins[poc].lo + bins[poc].hi) / 2, vah: bins[z].hi, val: bins[a].lo };
}

// type: "signals" = 차트에 화살표/글자 표시 (data[i] = null | {dir: 1|-1, text, shape, color})
Object.assign(INDICATORS, {
  // ---------- 추세 (추가)
  dema: { name: "DEMA (이중 지수)", group: "추세", pane: "main", params: { length: 21 }, compute: (c, p) => ({ plots: [line(`DEMA ${p.length}`, dema(src(c), p.length), C.d)] }) },
  tema: { name: "TEMA (삼중 지수)", group: "추세", pane: "main", params: { length: 21 }, compute: (c, p) => ({ plots: [line(`TEMA ${p.length}`, tema(src(c), p.length), C.c)] }) },
  alma: { name: "ALMA (아르노 르구)", group: "추세", pane: "main", params: { length: 9, offset: 0.85, sigma: 6 }, compute: (c, p) => ({ plots: [line(`ALMA ${p.length}`, alma(src(c), p.length, p.offset, p.sigma), C.b)] }) },
  kama: { name: "KAMA (카우프만 적응형)", group: "추세", pane: "main", desc: "추세가 강하면 빠르게, 횡보면 느리게 따라가는 이평", params: { length: 10, fast: 2, slow: 30 }, compute: (c, p) => ({ plots: [line(`KAMA ${p.length}`, kama(src(c), p.length, p.fast, p.slow), C.e, { lineWidth: 2 })] }) },
  zlema: { name: "ZLEMA (제로 래그)", group: "추세", pane: "main", params: { length: 21 }, compute: (c, p) => {
    const x = src(c), lag = Math.floor((p.length - 1) / 2); return { plots: [line(`ZLEMA ${p.length}`, ema(x.map((v, i) => i < lag ? null : 2 * v - x[i - lag]), p.length), C.f)] };
  } },
  mcginley: { name: "맥긴리 다이내믹", group: "추세", pane: "main", params: { length: 14 }, compute: (c, p) => ({ plots: [line(`McGinley ${p.length}`, mcginley(src(c), p.length), C.a, { lineWidth: 2 })] }) },
  lsma: { name: "LSMA (선형회귀 이평)", group: "추세", pane: "main", params: { length: 25 }, compute: (c, p) => ({ plots: [line(`LSMA ${p.length}`, linreg(src(c), p.length), C.g)] }) },
  rma: { name: "RMA / SMMA (평활 이평)", group: "추세", pane: "main", params: { length: 20 }, compute: (c, p) => ({ plots: [line(`RMA ${p.length}`, rma(src(c), p.length), C.d)] }) },
  ssl: { name: "SSL 채널", group: "추세", pane: "main", desc: "고가·저가 이평 교차로 추세 전환", params: { length: 10 }, compute: (c, p) => {
    const sh = sma(c.map((b) => b.high), p.length), sl = sma(c.map((b) => b.low), p.length), up = [], dn = []; let hlv = 0;
    c.forEach((b, i) => { if (sh[i] == null) { up.push(null); dn.push(null); return; } hlv = b.close > sh[i] ? 1 : b.close < sl[i] ? -1 : hlv; up.push(hlv < 0 ? sl[i] : sh[i]); dn.push(hlv < 0 ? sh[i] : sl[i]); });
    return { plots: [line("SSL 상승", up, C.up), line("SSL 하락", dn, C.dn), { name: "신호", type: "signals", data: crossSignals(up, dn, "SSL↑", "SSL↓") }] };
  } },
  // ---------- 신호 · 패턴
  ma_cross: { name: "이평선 골든/데드 크로스", group: "신호 · 패턴", pane: "main", desc: "빠른 이평이 느린 이평을 넘을 때 표시. type 1=SMA 2=EMA 3=WMA 4=RMA", params: { fast: 9, slow: 21, type: 2 }, compute: (c, p) => {
    const f = (MA[p.type] || ema)(src(c), p.fast), s = (MA[p.type] || ema)(src(c), p.slow);
    return { plots: [line(`빠른 ${p.fast}`, f, C.a, { lineWidth: 1 }), line(`느린 ${p.slow}`, s, C.b, { lineWidth: 1 }), { name: "신호", type: "signals", data: crossSignals(f, s, "골든", "데드") }] };
  } },
  divergence: { name: "다이버전스 (RSI/MACD)", group: "신호 · 패턴", pane: "main", desc: "가격과 오실레이터가 반대로 움직여 추세가 약해질 때 표시(추세 전환 경고). osc 1=RSI 2=MACD히스토그램 · left/right=피벗 좌우 봉수", params: { osc: 1, length: 14, left: 5, right: 5 }, compute: (c, p) => {
    const close = src(c), n = c.length;
    let o;
    if (p.osc === 2) { const macd = sub(ema(close, 12), ema(close, 26)); o = sub(macd, ema(macd, 9)); }   // MACD 히스토그램
    else o = rsi(close, p.length || 14);
    const L = Math.max(1, (p.left | 0) || 5), R = Math.max(1, (p.right | 0) || 5), data = sig(n);
    const isPH = (i) => { if (i < L || i >= n - R) return false; for (let j = 1; j <= L; j++) if (!(close[i] > close[i - j])) return false; for (let j = 1; j <= R; j++) if (!(close[i] >= close[i + j])) return false; return true; };
    const isPL = (i) => { if (i < L || i >= n - R) return false; for (let j = 1; j <= L; j++) if (!(close[i] < close[i - j])) return false; for (let j = 1; j <= R; j++) if (!(close[i] <= close[i + j])) return false; return true; };
    let ph = null, pl = null;
    for (let i = 0; i < n; i++) {
      if (o[i] == null) continue;
      if (isPH(i)) { if (ph && close[i] > close[ph.i] && o[i] < ph.o) data[i] = { dir: -1, text: "약세 다이버전스" }; ph = { i, o: o[i] }; }
      if (isPL(i)) { if (pl && close[i] < close[pl.i] && o[i] > pl.o) data[i] = { dir: 1, text: "강세 다이버전스" }; pl = { i, o: o[i] }; }
    }
    return { plots: [{ name: p.osc === 2 ? "MACD 다이버전스" : "RSI 다이버전스", type: "signals", data }] };
  } },
  ut_bot: { name: "UT Bot 알림", group: "신호 · 패턴", pane: "main", desc: "ATR 추적 손절선 돌파로 매수/매도 신호", params: { key: 1, atr: 10 }, compute: (c, p) => {
    const a = atr(c, p.atr), x = src(c), stop = Array(c.length).fill(null), s = sig(c.length), col = Array(c.length).fill(null); let prev = 0;
    for (let i = 1; i < c.length; i++) {
      if (a[i] == null) continue;
      const nl = p.key * a[i], v = x[i], v1 = x[i - 1];
      const st = v > prev && v1 > prev ? Math.max(prev, v - nl) : v < prev && v1 < prev ? Math.min(prev, v + nl) : v > prev ? v - nl : v + nl;
      if (stop[i - 1] != null) { if (v > st && v1 <= stop[i - 1]) s[i] = { dir: 1, text: "매수" }; else if (v < st && v1 >= stop[i - 1]) s[i] = { dir: -1, text: "매도" }; }
      stop[i] = st; col[i] = v > st ? C.up : C.dn; prev = st;
    }
    return { plots: [line("추적선", stop, C.g, { lineWidth: 1, colors: col }), { name: "신호", type: "signals", data: s }] };
  } },
  chandelier: { name: "샹들리에 엑시트", group: "신호 · 패턴", pane: "main", desc: "ATR 기반 추적 손절선. 방향 전환 시 신호", params: { length: 22, mult: 3 }, compute: (c, p) => {
    const a = atr(c, p.length), cl = src(c), hh = highest(cl, p.length), ll = lowest(cl, p.length), L = Array(c.length).fill(null), S = Array(c.length).fill(null), s = sig(c.length);
    let ls = null, ss = null, dir = 1;
    for (let i = 1; i < c.length; i++) {
      if (a[i] == null || hh[i] == null) continue;
      let l = hh[i] - p.mult * a[i], sh = ll[i] + p.mult * a[i]; const lp = ls ?? l, sp = ss ?? sh;
      l = cl[i - 1] > lp ? Math.max(l, lp) : l; sh = cl[i - 1] < sp ? Math.min(sh, sp) : sh;
      const nd = cl[i] > sp ? 1 : cl[i] < lp ? -1 : dir;
      if (nd !== dir && ls != null) s[i] = { dir: nd, text: nd > 0 ? "롱" : "숏" };
      dir = nd; ls = l; ss = sh;
      if (dir === 1) L[i] = l; else S[i] = sh;
    }
    return { plots: [line("롱 손절", L, C.up, { lineWidth: 1 }), line("숏 손절", S, C.dn, { lineWidth: 1 }), { name: "신호", type: "signals", data: s }] };
  } },
  fractals: { name: "윌리엄스 프랙탈", group: "신호 · 패턴", pane: "main", desc: "좌우 n봉보다 높은 고점/낮은 저점 (n봉 뒤 확정)", params: { n: 2 }, compute: (c, p) => {
    const s = sig(c.length);
    pivots(c.map((b) => b.high), p.n, p.n, true).forEach((i) => (s[i] = { dir: -1, shape: "arrowDown", color: "rgba(229,72,77,.7)", size: 0.5 }));
    pivots(c.map((b) => b.low), p.n, p.n, false).forEach((i) => (s[i] = { dir: 1, shape: "arrowUp", color: "rgba(34,176,125,.7)", size: 0.5 }));
    return { plots: [{ name: "프랙탈", type: "signals", data: s }] };
  } },
  zigzag: { name: "지그재그 (HH·HL·LH·LL)", group: "신호 · 패턴", pane: "main", desc: "dev% 이상 되돌린 고점·저점을 이어 파동 구조를 표시. 마지막 선은 진행 중이라 바뀔 수 있음", params: { dev: 5 }, compute: (c, p) => {
    const d = p.dev / 100, pts = [], out = Array(c.length).fill(null), s = sig(c.length);
    if (c.length < 2) return { plots: [] };
    let trend = 0, ei = 0, ep = c[0].close;
    for (let i = 1; i < c.length; i++) {
      const h = c[i].high, l = c[i].low;
      if (trend === 0) { if (h >= ep * (1 + d)) { pts.push([0, c[0].low]); trend = 1; ei = i; ep = h; } else if (l <= ep * (1 - d)) { pts.push([0, c[0].high]); trend = -1; ei = i; ep = l; } }
      else if (trend === 1) { if (h > ep) { ei = i; ep = h; } else if (l <= ep * (1 - d)) { pts.push([ei, ep]); trend = -1; ei = i; ep = l; } }
      else if (l < ep) { ei = i; ep = l; } else if (h >= ep * (1 + d)) { pts.push([ei, ep]); trend = 1; ei = i; ep = h; }
    }
    if (trend) pts.push([ei, ep]);
    for (let k = 0; k + 1 < pts.length; k++) {
      const [i0, p0] = pts[k], [i1, p1] = pts[k + 1];
      for (let i = i0; i <= i1; i++) out[i] = p0 + (p1 - p0) * (i1 === i0 ? 0 : (i - i0) / (i1 - i0));
    }
    for (let k = 1; k < pts.length; k++) {
      const [i, v] = pts[k], prevSame = pts[k - 2], isHigh = v > pts[k - 1][1];
      const tag = prevSame ? (isHigh ? (v > prevSame[1] ? "HH" : "LH") : (v < prevSame[1] ? "LL" : "HL")) : "";
      s[i] = { dir: isHigh ? -1 : 1, shape: "circle", text: tag, color: isHigh ? C.dn : C.up, size: 0.3 };
    }
    return { plots: [line("지그재그", out, C.a, { lineWidth: 1 }), { name: "파동", type: "signals", data: s }] };
  } },
  rsi_div: { name: "RSI 다이버전스", group: "신호 · 패턴", pane: "sub", desc: "가격은 저점을 낮추는데 RSI는 높이면 강세(반대면 약세). hidden=1 이면 히든 다이버전스도 표시", params: { length: 14, left: 5, right: 5, hidden: 0 }, compute: (c, p) => {
    const r = rsi(src(c), p.length), s = sig(c.length), lows = c.map((b) => b.low), highs = c.map((b) => b.high);
    const scan = (idx, bull) => {
      for (let k = 1; k < idx.length; k++) {
        const i = idx[k], j = idx[k - 1], gap = i - j;
        if (gap < 5 || gap > 60) continue;
        if (bull) {
          if (r[i] > r[j] && lows[i] < lows[j]) s[i] = { dir: 1, text: "강세 다이버" };
          else if (p.hidden && r[i] < r[j] && lows[i] > lows[j]) s[i] = { dir: 1, text: "히든 강세", color: "rgba(34,176,125,.6)" };
        } else if (r[i] < r[j] && highs[i] > highs[j]) s[i] = { dir: -1, text: "약세 다이버" };
        else if (p.hidden && r[i] > r[j] && highs[i] < highs[j]) s[i] = { dir: -1, text: "히든 약세", color: "rgba(229,72,77,.6)" };
      }
    };
    scan(pivots(r, p.left, p.right, false), true); scan(pivots(r, p.left, p.right, true), false);
    return { plots: [line(`RSI ${p.length}`, r, C.e), { name: "다이버전스", type: "signals", data: s }], levels: [30, 50, 70] };
  } },
  // ---------- 레벨 · 프로파일
  vp: { name: "볼륨 프로파일 (보이는 구간)", group: "레벨 · 프로파일", pane: "main", profile: true, desc: "화면에 보이는 봉들의 가격대별 거래량. 주황선 = POC(최다 거래 가격), 밝은 구간 = 가치 영역", params: { rows: 30, va: 70, width: 28 },
    compute: () => ({ plots: [] }) },
  fib: { name: "자동 피보나치 되돌림", group: "레벨 · 프로파일", pane: "main", desc: "최근 n봉의 최고·최저로 되돌림 레벨을 자동으로 그림", params: { lookback: 144 }, compute: (c, p) => {
    const n = Math.min(p.lookback, c.length), st = c.length - n; let hi = -Infinity, lo = Infinity, hiI = 0, loI = 0;
    for (let i = st; i < c.length; i++) { if (c[i].high > hi) { hi = c[i].high; hiI = i; } if (c[i].low < lo) { lo = c[i].low; loI = i; } }
    const up = loI < hiI, cols = ["#a4acb6", "#e5484d", "#f5a524", "#22b07d", "#3987e5", "#9085e9", "#a4acb6"];
    return { plots: [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1].map((lv, k) => {
      const v = up ? hi - (hi - lo) * lv : lo + (hi - lo) * lv;
      return line(`${lv}`, c.map((_, i) => i >= st ? v : null), cols[k], { lineWidth: 1, lineStyle: lv === 0 || lv === 1 ? 0 : 2 });
    }), note: up ? "상승 구간 되돌림" : "하락 구간 되돌림" };
  } },
  pdhl: { name: "전일·전주 고가/저가", group: "레벨 · 프로파일", pane: "main", desc: "PDH/PDL · PWH/PWL (UTC 기준)", params: {}, compute: (c) => {
    const prev = (key) => { let cur = null, h, l, ph = null, pl = null; const H = [], L = [];
      c.forEach((b) => { const k = key(b.time); if (k !== cur) { if (cur != null) { ph = h; pl = l; } cur = k; h = b.high; l = b.low; } else { h = Math.max(h, b.high); l = Math.min(l, b.low); } H.push(ph); L.push(pl); });
      return [H, L]; };
    const [dh, dl] = prev((t) => Math.floor(t / 86400)), [wh, wl] = prev((t) => Math.floor((t / 86400 + 3) / 7));
    return { plots: [line("전일 고가", dh, C.dn, { lineWidth: 1 }), line("전일 저가", dl, C.up, { lineWidth: 1 }),
      line("전주 고가", wh, "rgba(229,72,77,.6)", { lineWidth: 1, lineStyle: 2 }), line("전주 저가", wl, "rgba(34,176,125,.6)", { lineWidth: 1, lineStyle: 2 })] };
  } },
  vwap_bands: { name: "VWAP 밴드 (표준편차)", group: "레벨 · 프로파일", pane: "main", desc: "anchor 1=매일 7=매주 초기화 (UTC)", params: { anchor: 1, m1: 1, m2: 2 }, compute: (c, p) => {
    let key = null, sv = 0, spv = 0, spv2 = 0; const vw = [], sd = [];
    c.forEach((b) => { const d = Math.floor(b.time / 86400), k = p.anchor === 7 ? Math.floor((d + 3) / 7) : Math.floor(d / Math.max(1, p.anchor));
      if (k !== key) { key = k; sv = spv = spv2 = 0; }
      const tp = (b.high + b.low + b.close) / 3; sv += b.volume; spv += tp * b.volume; spv2 += tp * tp * b.volume;
      const m = sv ? spv / sv : tp; vw.push(m); sd.push(sv ? Math.sqrt(Math.max(0, spv2 / sv - m * m)) : 0); });
    const band = (k) => vw.map((v, i) => v + k * sd[i]);
    return { plots: [line("VWAP", vw, C.c, { lineWidth: 2 }), line(`+${p.m1}σ`, band(p.m1), "rgba(213,81,129,.6)", { lineWidth: 1 }), line(`-${p.m1}σ`, band(-p.m1), "rgba(213,81,129,.6)", { lineWidth: 1 }),
      line(`+${p.m2}σ`, band(p.m2), "rgba(213,81,129,.35)", { lineWidth: 1, lineStyle: 2 }), line(`-${p.m2}σ`, band(-p.m2), "rgba(213,81,129,.35)", { lineWidth: 1, lineStyle: 2 })] };
  } },
  linreg_ch: { name: "선형회귀 채널", group: "레벨 · 프로파일", pane: "main", desc: "최근 n봉 회귀선 ± 표준편차", params: { length: 100, dev: 2 }, compute: (c, p) => {
    const n = Math.min(p.length, c.length), st = c.length - n, y = c.slice(st).map((b) => b.close);
    let sx = 0, sy = 0, sxy = 0, sxx = 0; y.forEach((v, j) => { sx += j; sy += v; sxy += j * v; sxx += j * j; });
    const den = n * sxx - sx * sx, slope = den ? (n * sxy - sx * sy) / den : 0, ic = (sy - slope * sx) / n;
    const sd = Math.sqrt(y.reduce((a, v, j) => a + (v - (ic + slope * j)) ** 2, 0) / Math.max(1, n));
    const at = (k) => c.map((_, i) => i >= st ? ic + slope * (i - st) + k * sd : null);
    return { plots: [line("회귀선", at(0), C.b, { lineWidth: 1 }), line("상단", at(p.dev), "rgba(57,135,229,.6)", { lineWidth: 1, lineStyle: 2 }), line("하단", at(-p.dev), "rgba(57,135,229,.6)", { lineWidth: 1, lineStyle: 2 })],
      note: `기울기 ${slope >= 0 ? "+" : ""}${(slope / (y.at(-1) || 1) * 100).toFixed(3)}%/봉` };
  } },
  // ---------- 변동성 (추가)
  bb_pctb: { name: "볼린저 %B", group: "변동성", pane: "sub", desc: "1 이상 = 상단 돌파, 0 이하 = 하단 이탈", params: { length: 20, mult: 2 }, compute: (c, p) => {
    const x = src(c), m = sma(x, p.length), sd = stdev(x, p.length);
    return { plots: [line("%B", x.map((v, i) => m[i] == null || !sd[i] ? null : (v - (m[i] - p.mult * sd[i])) / (2 * p.mult * sd[i])), C.b)], levels: [0, 0.5, 1] };
  } },
  stdev: { name: "표준편차", group: "변동성", pane: "sub", params: { length: 20 }, compute: (c, p) => ({ plots: [line("StdDev", stdev(src(c), p.length), C.f)] }) },
  zscore: { name: "Z-스코어", group: "변동성", pane: "sub", desc: "평균에서 표준편차 몇 배 벗어났는지. ±2 이상은 과열", params: { length: 20 }, compute: (c, p) => {
    const x = src(c), m = sma(x, p.length), sd = stdev(x, p.length);
    return { plots: [line("Z", x.map((v, i) => m[i] == null || !sd[i] ? null : (v - m[i]) / sd[i]), C.c)], levels: [-2, 0, 2] };
  } },
  hv: { name: "역사적 변동성 (연율 %)", group: "변동성", pane: "sub", params: { length: 10 }, compute: (c, p) => {
    const lr = c.map((b, i) => i ? Math.log(b.close / c[i - 1].close) : null), step = c.length > 1 ? c.at(-1).time - c.at(-2).time : 86400;
    return { plots: [line("HV", mul(stdev(lr, p.length), 100 * Math.sqrt(365 * 86400 / step)), C.a)] };
  } },
  mass: { name: "매스 인덱스", group: "변동성", pane: "sub", desc: "27 위로 갔다가 26.5 아래로 내려오면 반전 가능성", params: { fast: 9, length: 25 }, compute: (c, p) => {
    const hl = c.map((b) => b.high - b.low), e1 = ema(hl, p.fast), e2 = ema(e1, p.fast);
    return { plots: [line("Mass", sum(ratio(e1, e2), p.length), C.e)], levels: [26.5, 27] };
  } },
  // ---------- 오실레이터 (추가)
  mom: { name: "모멘텀", group: "오실레이터", pane: "sub", params: { length: 10 }, compute: (c, p) => ({ plots: [line("MOM", change(src(c), p.length), C.b)], levels: [0] }) },
  ppo: { name: "PPO (% 가격 오실레이터)", group: "오실레이터", pane: "sub", params: { fast: 12, slow: 26, signal: 9 }, compute: (c, p) => {
    const x = src(c), f = ema(x, p.fast), s = ema(x, p.slow), v = f.map((a, i) => a == null || !s[i] ? null : (a - s[i]) / s[i] * 100), sg = ema(v, p.signal), h = sub(v, sg);
    return { plots: [hist("히스토그램", h, signColors(h)), line("PPO", v, C.b), line("시그널", sg, C.a)], levels: [0] };
  } },
  dpo: { name: "DPO (추세 제거)", group: "오실레이터", pane: "sub", params: { length: 21 }, compute: (c, p) => {
    const x = src(c), m = shift(sma(x, p.length), Math.floor(p.length / 2) + 1); return { plots: [line("DPO", sub(x, m), C.d)], levels: [0] };
  } },
  uo: { name: "얼티밋 오실레이터", group: "오실레이터", pane: "sub", params: { fast: 7, mid: 14, slow: 28 }, compute: (c, p) => {
    const pc = prevClose(c), bp = c.map((b, i) => pc[i] == null ? null : b.close - Math.min(b.low, pc[i])), t = c.map((b, i) => pc[i] == null ? null : Math.max(b.high, pc[i]) - Math.min(b.low, pc[i]));
    const av = (n) => ratio(sum(bp, n), sum(t, n)), a = av(p.fast), b = av(p.mid), d = av(p.slow);
    return { plots: [line("UO", a.map((v, i) => v == null || b[i] == null || d[i] == null ? null : 100 * (4 * v + 2 * b[i] + d[i]) / 7), C.c)], levels: [30, 50, 70] };
  } },
  kst: { name: "KST (노우 슈어 싱)", group: "오실레이터", pane: "sub", params: { signal: 9 }, compute: (c, p) => {
    const x = src(c), r = [[10, 10], [15, 10], [20, 10], [30, 15]].map(([a, b]) => sma(roc(x, a), b));
    const k = r[0].map((v, i) => r.some((q) => q[i] == null) ? null : r[0][i] + 2 * r[1][i] + 3 * r[2][i] + 4 * r[3][i]);
    return { plots: [line("KST", k, C.up), line("시그널", sma(k, p.signal), C.dn)], levels: [0] };
  } },
  tsi: { name: "TSI (트루 스트렝스)", group: "오실레이터", pane: "sub", params: { long: 25, short: 13, signal: 13 }, compute: (c, p) => {
    const m = change(src(c)), a = ema(ema(m, p.long), p.short), b = ema(ema(m.map((v) => v == null ? null : Math.abs(v)), p.long), p.short), t = mul(ratio(a, b), 100);
    return { plots: [line("TSI", t, C.b), line("시그널", ema(t, p.signal), C.a)], levels: [-25, 0, 25] };
  } },
  cmo: { name: "CMO (챈드 모멘텀)", group: "오실레이터", pane: "sub", params: { length: 9 }, compute: (c, p) => {
    const [u, d] = upDown(src(c), p.length); return { plots: [line("CMO", u.map((v, i) => v == null || d[i] == null || v + d[i] === 0 ? null : 100 * (v - d[i]) / (v + d[i])), C.e)], levels: [-50, 0, 50] };
  } },
  crsi: { name: "코너스 RSI", group: "오실레이터", pane: "sub", desc: "단기 되돌림 매매용 (10 이하 과매도 · 90 이상 과매수)", params: { rsi: 3, streak: 2, rank: 100 }, compute: (c, p) => {
    const x = src(c), st = [0];
    for (let i = 1; i < x.length; i++) st.push(x[i] > x[i - 1] ? Math.max(st[i - 1], 0) + 1 : x[i] < x[i - 1] ? Math.min(st[i - 1], 0) - 1 : 0);
    const a = rsi(x, p.rsi), b = rsi(st, p.streak), r = percentrank(roc(x, 1), p.rank);
    return { plots: [line("CRSI", a.map((v, i) => v == null || b[i] == null || r[i] == null ? null : (v + b[i] + r[i]) / 3), C.c)], levels: [10, 50, 90] };
  } },
  fisher: { name: "피셔 트랜스폼", group: "오실레이터", pane: "sub", params: { length: 9 }, compute: (c, p) => {
    const hl = src(c, "hl2"), h = highest(hl, p.length), l = lowest(hl, p.length), f = Array(c.length).fill(null), t = Array(c.length).fill(null); let v = 0, fi = 0;
    for (let i = 0; i < c.length; i++) {
      if (h[i] == null) continue;
      v = 0.66 * (h[i] === l[i] ? 0 : (hl[i] - l[i]) / (h[i] - l[i]) - 0.5) + 0.67 * v; v = Math.max(-0.999, Math.min(0.999, v));
      t[i] = f[i - 1] ?? null; fi = 0.5 * Math.log((1 + v) / (1 - v)) + 0.5 * fi; f[i] = fi;
    }
    return { plots: [line("Fisher", f, C.b), line("트리거", t, C.a, { lineWidth: 1 })], levels: [-1.5, 0, 1.5] };
  } },
  elder: { name: "엘더 레이 (강세/약세 파워)", group: "오실레이터", pane: "sub", params: { length: 13 }, compute: (c, p) => {
    const e = ema(src(c), p.length), bu = c.map((b, i) => e[i] == null ? null : b.high - e[i]), be = c.map((b, i) => e[i] == null ? null : b.low - e[i]);
    return { plots: [hist("강세 파워", bu, bu.map(() => "rgba(34,176,125,.6)")), hist("약세 파워", be, be.map(() => "rgba(229,72,77,.6)"))], levels: [0] };
  } },
  coppock: { name: "코폭 커브", group: "오실레이터", pane: "sub", params: { wma: 10, long: 14, short: 11 }, compute: (c, p) => {
    const x = src(c), v = wma(add(roc(x, p.long), roc(x, p.short)), p.wma); return { plots: [hist("Coppock", v, signColors(v))], levels: [0] };
  } },
  vortex: { name: "보텍스 (VI+/VI-)", group: "오실레이터", pane: "sub", params: { length: 14 }, compute: (c, p) => {
    const t = sum(tr(c), p.length), vp = c.map((b, i) => i ? Math.abs(b.high - c[i - 1].low) : null), vm = c.map((b, i) => i ? Math.abs(b.low - c[i - 1].high) : null);
    return { plots: [line("VI+", ratio(sum(vp, p.length), t), C.up), line("VI-", ratio(sum(vm, p.length), t), C.dn)], levels: [1] };
  } },
  rvi: { name: "RVI (상대 활력)", group: "오실레이터", pane: "sub", params: { length: 10 }, compute: (c, p) => {
    const v = ratio(sum(swma(c.map((b) => b.close - b.open)), p.length), sum(swma(c.map((b) => b.high - b.low)), p.length));
    return { plots: [line("RVI", v, C.up), line("시그널", swma(v), C.dn)], levels: [0] };
  } },
  stc: { name: "샤프 트렌드 사이클", group: "오실레이터", pane: "sub", desc: "MACD를 스토캐스틱으로 두 번 다듬은 빠른 추세 지표 (25/75)", params: { fast: 23, slow: 50, cycle: 10 }, compute: (c, p) => {
    const m = sub(ema(src(c), p.fast), ema(src(c), p.slow)), n = p.cycle, out = Array(c.length).fill(null), pf = Array(c.length).fill(null);
    let f1 = 0, f2 = 0, pv = null, ppv = null;
    for (let i = 0; i < c.length; i++) {
      if (m[i] == null) continue;
      const w = m.slice(Math.max(0, i - n + 1), i + 1).filter((q) => q != null), lo = Math.min(...w), rg = Math.max(...w) - lo;
      f1 = rg > 0 ? (m[i] - lo) / rg * 100 : f1; pv = pv == null ? f1 : pv + 0.5 * (f1 - pv); pf[i] = pv;
      const w2 = pf.slice(Math.max(0, i - n + 1), i + 1).filter((q) => q != null), lo2 = Math.min(...w2), rg2 = Math.max(...w2) - lo2;
      f2 = rg2 > 0 ? (pv - lo2) / rg2 * 100 : f2; ppv = ppv == null ? f2 : ppv + 0.5 * (f2 - ppv); out[i] = ppv;
    }
    return { plots: [line("STC", out, C.a, { lineWidth: 2 })], levels: [25, 75] };
  } },
  qqe: { name: "QQE", group: "오실레이터", pane: "sub", desc: "RSI 평활선과 변동성 추적선의 교차로 추세 판단", params: { rsi: 14, smooth: 5, factor: 4.238 }, compute: (c, p) => {
    const rm = ema(rsi(src(c), p.rsi), p.smooth), wp = p.rsi * 2 - 1, ar = rm.map((v, i) => i && v != null && rm[i - 1] != null ? Math.abs(rm[i - 1] - v) : null);
    const dar = mul(ema(ema(ar, wp), wp), p.factor), tl = Array(c.length).fill(null); let lb = null, sb = null, trend = 1;
    for (let i = 1; i < c.length; i++) {
      if (dar[i] == null || rm[i] == null) continue;
      const r = rm[i], r1 = rm[i - 1], nl = r - dar[i], ns = r + dar[i];
      const lb1 = lb, sb1 = sb;
      lb = lb1 != null && r1 > lb1 && r > lb1 ? Math.max(lb1, nl) : nl;
      sb = sb1 != null && r1 < sb1 && r < sb1 ? Math.min(sb1, ns) : ns;
      if (sb1 != null && r1 <= sb1 && r > sb1) trend = 1; else if (lb1 != null && r1 >= lb1 && r < lb1) trend = -1;
      tl[i] = trend === 1 ? lb : sb;
    }
    return { plots: [line("RSI 평활", rm, C.b, { lineWidth: 2 }), line("추적선", tl, C.a, { lineWidth: 1 })], levels: [30, 50, 70] };
  } },
  laguerre: { name: "라게르 RSI", group: "오실레이터", pane: "sub", params: { gamma: 0.5 }, compute: (c, p) => {
    const g = p.gamma; let l0 = 0, l1 = 0, l2 = 0, l3 = 0;
    return { plots: [line("LRSI", src(c).map((x, i) => {
      const p0 = l0, p1 = l1, p2 = l2;
      l0 = (1 - g) * x + g * l0; l1 = -g * l0 + p0 + g * l1; l2 = -g * l1 + p1 + g * l2; l3 = -g * l2 + p2 + g * l3;
      const cu = Math.max(l0 - l1, 0) + Math.max(l1 - l2, 0) + Math.max(l2 - l3, 0), cd = Math.max(l1 - l0, 0) + Math.max(l2 - l1, 0) + Math.max(l3 - l2, 0);
      return i < 4 ? null : cu + cd ? 100 * cu / (cu + cd) : 0;
    }), C.e)], levels: [20, 80] };
  } },
  bop: { name: "BOP (매수·매도 힘 균형)", group: "오실레이터", pane: "sub", params: { length: 14 }, compute: (c, p) => {
    const v = sma(c.map((b) => b.high === b.low ? 0 : (b.close - b.open) / (b.high - b.low)), p.length); return { plots: [hist("BOP", v, signColors(v))], levels: [0] };
  } },
  ac: { name: "가속 오실레이터 (AC)", group: "오실레이터", pane: "sub", params: {}, compute: (c) => {
    const m = src(c, "hl2"), a = sub(sma(m, 5), sma(m, 34)), v = sub(a, sma(a, 5)); return { plots: [hist("AC", v, signColors(v))], levels: [0] };
  } },
  // ---------- 거래량 (추가)
  rvol: { name: "상대 거래량 (RVOL)", group: "거래량", pane: "sub", desc: "평소(n봉 평균) 대비 몇 배. 2 이상 = 거래량 급증", params: { length: 20 }, compute: (c, p) => {
    const v = c.map((b) => b.volume), r = ratio(v, shift(sma(v, p.length), 1));
    return { plots: [hist("RVOL", r, r.map((x, i) => x == null ? null : x >= 2 ? (c[i].close >= c[i].open ? "rgba(34,176,125,.9)" : "rgba(229,72,77,.9)") : "rgba(164,172,182,.45)"))], levels: [1, 2] };
  } },
  buy_ratio: { name: "시장가 매수 비율 (%)", group: "거래량", pane: "sub", desc: "거래량 중 시장가 매수(테이커 매수) 비중. 50 이상 = 매수 우위", params: { smooth: 14 }, compute: (c, p) => {
    const r = c.map((b) => b.volume ? 100 * (b.taker_buy ?? b.volume / 2) / b.volume : 50);
    return { plots: [line("매수 비율", r, "rgba(164,172,182,.5)", { lineWidth: 1 }), line(`평균 ${p.smooth}`, sma(r, p.smooth), C.a, { lineWidth: 2 })], levels: [50] };
  } },
  adl: { name: "A/D 라인 (누적 분산)", group: "거래량", pane: "sub", params: {}, compute: (c) => ({ plots: [line("A/D", cum(c.map((b) => b.high === b.low ? 0 : ((b.close - b.low) - (b.high - b.close)) / (b.high - b.low) * b.volume)), C.d)] }) },
  chaikin_osc: { name: "차이킨 오실레이터", group: "거래량", pane: "sub", params: { fast: 3, slow: 10 }, compute: (c, p) => {
    const ad = cum(c.map((b) => b.high === b.low ? 0 : ((b.close - b.low) - (b.high - b.close)) / (b.high - b.low) * b.volume)), v = sub(ema(ad, p.fast), ema(ad, p.slow));
    return { plots: [hist("Chaikin", v, signColors(v))], levels: [0] };
  } },
  pvt: { name: "PVT (가격·거래량 추세)", group: "거래량", pane: "sub", params: {}, compute: (c) => ({ plots: [line("PVT", cum(c.map((b, i) => i ? (b.close / c[i - 1].close - 1) * b.volume : 0)), C.b)] }) },
  klinger: { name: "클링거 오실레이터", group: "거래량", pane: "sub", params: { fast: 34, slow: 55, signal: 13 }, compute: (c, p) => {
    const tp = src(c, "hlc3"), sv = c.map((b, i) => i ? (tp[i] - tp[i - 1] >= 0 ? b.volume : -b.volume) : null), k = sub(ema(sv, p.fast), ema(sv, p.slow));
    return { plots: [line("KVO", k, C.b), line("시그널", ema(k, p.signal), C.a)], levels: [0] };
  } },
  force: { name: "포스 인덱스", group: "거래량", pane: "sub", params: { length: 13 }, compute: (c, p) => {
    const v = ema(c.map((b, i) => i ? (b.close - c[i - 1].close) * b.volume : null), p.length); return { plots: [hist("Force", v, signColors(v))], levels: [0] };
  } },
  eom: { name: "EOM (이동 용이성)", group: "거래량", pane: "sub", params: { length: 14 }, compute: (c, p) => {
    const hl = src(c, "hl2"); return { plots: [line("EOM", sma(c.map((b, i) => i && b.volume ? 10000 * (hl[i] - hl[i - 1]) * (b.high - b.low) / b.volume : i ? 0 : null), p.length), C.d)], levels: [0] };
  } },
  vol_osc: { name: "거래량 오실레이터 (%)", group: "거래량", pane: "sub", params: { fast: 5, slow: 10 }, compute: (c, p) => {
    const v = c.map((b) => b.volume), f = ema(v, p.fast), s = ema(v, p.slow); return { plots: [line("VO", f.map((a, i) => a == null || !s[i] ? null : 100 * (a - s[i]) / s[i]), C.c)], levels: [0] };
  } },
});

// ---------------------------------------------------------------- 추가 지표 2: 필터 · 스마트머니 · 통계 · BTC 대비
// type: "boxes" = 가격 구간 상자 (FVG·오더블록). boxes: [{i0, i1(null=오른쪽 끝까지), top, bottom, color, label}]
const boxesPlot = (name, boxes) => ({ name, type: "boxes", data: Array(boxes.n).fill(null), boxes: boxes.list });
const barsPerYear = (c) => (c.length > 1 ? 365 * 86400 / Math.max(60, c.at(-1).time - c.at(-2).time) : 365);
function kalman(x, resp) {
  let est = null, p = 1;
  return x.map((v) => { if (v == null) return est; if (est == null) return (est = v); p += resp; const k = p / (p + 1); est += k * (v - est); p *= 1 - k; return est; });
}
function superSmoother(x, n) {
  const a = Math.exp(-1.414 * Math.PI / n), b = 2 * a * Math.cos(1.414 * Math.PI / n), c2 = b, c3 = -a * a, c1 = 1 - c2 - c3, o = [];
  x.forEach((v, i) => o.push(i < 2 ? v : c1 * (v + x[i - 1]) / 2 + c2 * o[i - 1] + c3 * o[i - 2]));
  return o;
}
function btcAligned(c, ext) {
  const m = new Map((ext?.btc || []).map((b) => [b.time, b.close]));
  return c.map((b) => m.get(b.time) ?? null);
}
function rollCorr(a, b, n) {
  return a.map((_, i) => {
    if (i < n) return null;
    let sa = 0, sb = 0, k = 0; const xs = [], ys = [];
    for (let j = i - n + 1; j <= i; j++) { if (a[j] == null || b[j] == null) continue; xs.push(a[j]); ys.push(b[j]); sa += a[j]; sb += b[j]; k++; }
    if (k < n * 0.8) return null;
    const ma = sa / k, mb = sb / k; let cov = 0, va = 0, vb = 0;
    for (let j = 0; j < k; j++) { cov += (xs[j] - ma) * (ys[j] - mb); va += (xs[j] - ma) ** 2; vb += (ys[j] - mb) ** 2; }
    return va && vb ? { corr: cov / Math.sqrt(va * vb), beta: cov / vb } : null;
  });
}
const rets = (x) => x.map((v, i) => i && v != null && x[i - 1] ? v / x[i - 1] - 1 : null);
function structure(c, len) {   // 스윙 고점·저점 돌파 → BOS(추세 지속) / CHoCH(추세 전환)
  const hs = pivots(c.map((b) => b.high), len, len, true), ls = pivots(c.map((b) => b.low), len, len, false);
  const confirmH = new Map(hs.map((i) => [i + len, i])), confirmL = new Map(ls.map((i) => [i + len, i]));
  const s = sig(c.length), H = Array(c.length).fill(null), Lw = Array(c.length).fill(null);
  let hi = null, lo = null, trend = 0;
  c.forEach((b, i) => {
    if (confirmH.has(i)) hi = { v: c[confirmH.get(i)].high, used: false };
    if (confirmL.has(i)) lo = { v: c[confirmL.get(i)].low, used: false };
    if (hi && !hi.used && b.close > hi.v) { s[i] = { dir: 1, text: trend === -1 ? "CHoCH" : "BOS", shape: trend === -1 ? "arrowUp" : "circle", size: 0.6 }; trend = 1; hi.used = true; }
    if (lo && !lo.used && b.close < lo.v) { s[i] = { dir: -1, text: trend === 1 ? "CHoCH" : "BOS", shape: trend === 1 ? "arrowDown" : "circle", size: 0.6 }; trend = -1; lo.used = true; }
    H[i] = hi && !hi.used ? hi.v : null; Lw[i] = lo && !lo.used ? lo.v : null;
  });
  return { s, H, L: Lw };
}

Object.assign(INDICATORS, {
  // ---------- 추세 · 필터
  kalman: { name: "칼만 필터", group: "추세", pane: "main", desc: "노이즈를 걸러낸 가격 추정선. resp 가 클수록 빠르게 따라감", params: { resp: 0.05 }, compute: (c, p) => ({ plots: [line("Kalman", kalman(src(c), p.resp), C.b, { lineWidth: 2 })] }) },
  super_smoother: { name: "슈퍼 스무더 (Ehlers)", group: "추세", pane: "main", params: { length: 20 }, compute: (c, p) => ({ plots: [line(`SS ${p.length}`, superSmoother(src(c), p.length), C.c, { lineWidth: 2 })] }) },
  itrend: { name: "순간 추세선 (Ehlers)", group: "추세", pane: "main", desc: "추세선(굵은 선)과 트리거가 교차하면 추세 전환", params: { alpha: 0.07 }, compute: (c, p) => {
    const x = src(c, "hl2"), a = p.alpha, it = [];
    x.forEach((v, i) => it.push(i < 7 ? (v + 2 * (x[i - 1] ?? v) + (x[i - 2] ?? v)) / 4
      : (a - a * a / 4) * v + 0.5 * a * a * x[i - 1] - (a - 0.75 * a * a) * x[i - 2] + 2 * (1 - a) * it[i - 1] - (1 - a) ** 2 * it[i - 2]));
    const tr = it.map((v, i) => i < 2 ? null : 2 * v - it[i - 2]);
    return { plots: [line("추세선", it, C.a, { lineWidth: 2 }), line("트리거", tr, C.b, { lineWidth: 1 }), { name: "신호", type: "signals", data: crossSignals(tr, it, "↑", "↓") }] };
  } },
  frama: { name: "FRAMA (프랙탈 적응 이평)", group: "추세", pane: "main", params: { length: 16 }, compute: (c, p) => {
    const N = Math.max(4, Math.round(p.length / 2) * 2), h = N / 2, x = src(c), o = Array(c.length).fill(null); let f = null, D = 1.5;
    const rng = (a, b) => { let hi = -Infinity, lo = Infinity; for (let j = a; j <= b; j++) { hi = Math.max(hi, c[j].high); lo = Math.min(lo, c[j].low); } return hi - lo; };
    for (let i = N - 1; i < c.length; i++) {
      const n1 = rng(i - h + 1, i) / h, n2 = rng(i - N + 1, i - h) / h, n3 = rng(i - N + 1, i) / N;
      if (n1 > 0 && n2 > 0 && n3 > 0) D = (Math.log(n1 + n2) - Math.log(n3)) / Math.LN2;
      const al = Math.min(1, Math.max(0.01, Math.exp(-4.6 * (D - 1))));
      f = f == null ? x[i] : al * x[i] + (1 - al) * f; o[i] = f;
    }
    return { plots: [line(`FRAMA ${N}`, o, C.e, { lineWidth: 2 })] };
  } },
  vidya: { name: "VIDYA (가변 지수 이평)", group: "추세", pane: "main", params: { length: 14, cmo: 9 }, compute: (c, p) => {
    const x = src(c), [u, d] = upDown(x, p.cmo), a = 2 / (p.length + 1); let v = null;
    return { plots: [line(`VIDYA ${p.length}`, x.map((q, i) => { if (u[i] == null) return v; const k = Math.abs(u[i] - d[i]) / ((u[i] + d[i]) || 1); v = v == null ? q : a * k * q + (1 - a * k) * v; return v; }), C.f, { lineWidth: 2 })] };
  } },
  t3: { name: "T3 (틸슨)", group: "추세", pane: "main", params: { length: 5, vfactor: 0.7 }, compute: (c, p) => {
    const v = p.vfactor, e = [ema(src(c), p.length)]; for (let k = 1; k < 6; k++) e.push(ema(e[k - 1], p.length));
    const c1 = -(v ** 3), c2 = 3 * v * v + 3 * v ** 3, c3 = -6 * v * v - 3 * v - 3 * v ** 3, c4 = 1 + 3 * v + v ** 3 + 3 * v * v;
    return { plots: [line(`T3 ${p.length}`, e[5].map((q, i) => q == null ? null : c1 * q + c2 * e[4][i] + c3 * e[3][i] + c4 * e[2][i]), C.d, { lineWidth: 2 })] };
  } },
  gmma: { name: "GMMA (구피 다중 이평)", group: "추세", pane: "main", desc: "단기 6개(초록)·장기 6개(빨강) 이평 묶음. 두 묶음이 벌어지면 추세 강함", params: {}, compute: (c) => {
    const x = src(c);
    return { plots: [[3, 5, 8, 10, 12, 15].map((n) => line(`단기 ${n}`, ema(x, n), "rgba(34,176,125,.6)", { lineWidth: 1 })),
      [30, 35, 40, 45, 50, 60].map((n) => line(`장기 ${n}`, ema(x, n), "rgba(229,72,77,.55)", { lineWidth: 1 }))].flat() };
  } },
  range_filter: { name: "레인지 필터", group: "신호 · 패턴", pane: "main", desc: "잔파동을 걸러낸 추세선. 방향 전환 시 매수·매도 신호 (DonovanWall 방식)", params: { period: 100, mult: 3 }, compute: (c, p) => {
    const x = src(c), ch = x.map((v, i) => i ? Math.abs(v - x[i - 1]) : null), r = mul(ema(ema(ch, p.period), p.period * 2 - 1), p.mult);
    const f = Array(c.length).fill(null), hb = [...f], lb = [...f], col = [...f], s = sig(c.length); let up = 0, dn = 0, cond = 0;
    for (let i = 1; i < c.length; i++) {
      if (r[i] == null) continue;
      const pf = f[i - 1] ?? x[i], v = x[i];
      f[i] = v > pf ? (v - r[i] < pf ? pf : v - r[i]) : (v + r[i] > pf ? pf : v + r[i]);
      up = f[i] > pf ? up + 1 : f[i] < pf ? 0 : up; dn = f[i] < pf ? dn + 1 : f[i] > pf ? 0 : dn;
      hb[i] = f[i] + r[i]; lb[i] = f[i] - r[i]; col[i] = up > 0 ? C.up : dn > 0 ? C.dn : C.a;
      const lc = v > f[i] && up > 0, sc = v < f[i] && dn > 0, prev = cond;
      cond = lc ? 1 : sc ? -1 : cond;
      if (lc && prev === -1) s[i] = { dir: 1, text: "매수" }; else if (sc && prev === 1) s[i] = { dir: -1, text: "매도" };
    }
    return { plots: [line("필터", f, C.a, { lineWidth: 2, colors: col }), line("상단", hb, "rgba(164,172,182,.35)", { lineWidth: 1 }), line("하단", lb, "rgba(164,172,182,.35)", { lineWidth: 1 }), { name: "신호", type: "signals", data: s }] };
  } },
  nwe: { name: "나다라야-왓슨 엔벨로프", group: "신호 · 패턴", pane: "main", desc: "커널 회귀 중심선 ± 평균 오차 밴드. 과거 값만 쓰는 방식이라 다시 그려지지 않음. 밴드 밖으로 나갔다 들어오면 신호", params: { bandwidth: 8, mult: 3, window: 100 }, compute: (c, p) => {
    const x = src(c), W = Math.min(p.window, 300), w = Array.from({ length: W }, (_, j) => Math.exp(-(j * j) / (2 * p.bandwidth ** 2))), y = Array(c.length).fill(null);
    for (let i = W - 1; i < c.length; i++) { let sw = 0, sx = 0; for (let j = 0; j < W; j++) { sw += w[j]; sx += w[j] * x[i - j]; } y[i] = sx / sw; }
    const mae = mul(sma(x.map((v, i) => y[i] == null ? null : Math.abs(v - y[i])), W), p.mult), s = sig(c.length);
    const up = y.map((v, i) => v == null || mae[i] == null ? null : v + mae[i]), dn = y.map((v, i) => v == null || mae[i] == null ? null : v - mae[i]);
    for (let i = 1; i < c.length; i++) {
      if (up[i] == null || up[i - 1] == null) continue;
      if (x[i - 1] > up[i - 1] && x[i] <= up[i]) s[i] = { dir: -1, text: "▼" }; else if (x[i - 1] < dn[i - 1] && x[i] >= dn[i]) s[i] = { dir: 1, text: "▲" };
    }
    return { plots: [line("중심", y, "rgba(245,165,36,.8)", { lineWidth: 1 }), line("상단", up, C.dn, { lineWidth: 1 }), line("하단", dn, C.up, { lineWidth: 1 }), { name: "신호", type: "signals", data: s }] };
  } },
  td_seq: { name: "TD 시퀀셜 (9 카운트)", group: "신호 · 패턴", pane: "main", desc: "4봉 전보다 9번 연속 높게(낮게) 마감하면 추세 소진 가능성", params: {}, compute: (c) => {
    const s = sig(c.length); let up = 0, dn = 0;
    c.forEach((b, i) => {
      if (i < 4) return;
      up = b.close > c[i - 4].close ? up + 1 : 0; dn = b.close < c[i - 4].close ? dn + 1 : 0;
      if (up === 9) s[i] = { dir: -1, text: "9", shape: "arrowDown", color: C.dn };
      if (dn === 9) s[i] = { dir: 1, text: "9", shape: "arrowUp", color: C.up };
    });
    return { plots: [{ name: "TD", type: "signals", data: s }] };
  } },
  candles: { name: "캔들 패턴", group: "신호 · 패턴", pane: "main", desc: "장악형·망치형·유성형·샛별형·석별형 (몸통이 ATR 절반 이상일 때만)", params: { min_body_atr: 0.5 }, compute: (c, p) => {
    const a = atr(c, 14), e = ema(src(c), 20), s = sig(c.length);
    for (let i = 2; i < c.length; i++) {
      const b = c[i], q = c[i - 1], r = c[i - 2]; if (a[i] == null || e[i] == null) continue;
      const body = Math.abs(b.close - b.open), rng = b.high - b.low || 1e-12, up = b.high - Math.max(b.open, b.close), lw = Math.min(b.open, b.close) - b.low;
      const big = body >= p.min_body_atr * a[i];
      if (big && b.close > b.open && q.close < q.open && b.close >= q.open && b.open <= q.close) s[i] = { dir: 1, text: "장악형" };
      else if (big && b.close < b.open && q.close > q.open && b.close <= q.open && b.open >= q.close) s[i] = { dir: -1, text: "장악형" };
      else if (lw >= 2 * body && up <= 0.3 * rng && rng >= a[i] && b.close < e[i]) s[i] = { dir: 1, text: "망치형" };
      else if (up >= 2 * body && lw <= 0.3 * rng && rng >= a[i] && b.close > e[i]) s[i] = { dir: -1, text: "유성형" };
      else if (r.close < r.open && Math.abs(r.close - r.open) >= a[i] * 0.8 && Math.abs(q.close - q.open) <= a[i] * 0.3 && b.close > b.open && b.close > (r.open + r.close) / 2) s[i] = { dir: 1, text: "샛별형" };
      else if (r.close > r.open && Math.abs(r.close - r.open) >= a[i] * 0.8 && Math.abs(q.close - q.open) <= a[i] * 0.3 && b.close < b.open && b.close < (r.open + r.close) / 2) s[i] = { dir: -1, text: "석별형" };
    }
    return { plots: [{ name: "패턴", type: "signals", data: s }] };
  } },
  // ---------- 스마트머니 (SMC)
  structure: { name: "시장 구조 (BOS · CHoCH)", group: "스마트머니 (SMC)", pane: "main", desc: "스윙 고점·저점을 종가로 돌파하면 BOS(추세 지속), 반대 방향 첫 돌파는 CHoCH(추세 전환). 점선 = 아직 안 깨진 스윙 레벨", params: { length: 5 }, compute: (c, p) => {
    const r = structure(c, p.length);
    return { plots: [line("스윙 고점", r.H, "rgba(229,72,77,.6)", { lineWidth: 1, lineStyle: 2 }), line("스윙 저점", r.L, "rgba(34,176,125,.6)", { lineWidth: 1, lineStyle: 2 }), { name: "구조", type: "signals", data: r.s }] };
  } },
  fvg: { name: "FVG (공정가치 갭)", group: "스마트머니 (SMC)", pane: "main", desc: "세 봉 사이에 생긴 가격 빈 구간. 가격이 다시 채우러 오는 경우가 많음. 다 채워지면 상자가 끝남", params: { min_pct: 0.1, keep: 20 }, compute: (c, p) => {
    const list = [];
    for (let i = 2; i < c.length; i++) {
      const b = c[i], a = c[i - 2];
      if (b.low > a.high && (b.low - a.high) / b.close * 100 >= p.min_pct) list.push({ i0: i - 1, i1: null, top: b.low, bottom: a.high, bull: true });
      else if (b.high < a.low && (a.low - b.high) / b.close * 100 >= p.min_pct) list.push({ i0: i - 1, i1: null, top: a.low, bottom: b.high, bull: false });
      else continue;
      const g = list.at(-1);
      for (let j = i + 1; j < c.length; j++) if (g.bull ? c[j].low <= g.bottom : c[j].high >= g.top) { g.i1 = j; break; }
    }
    const shown = [...list.filter((g) => g.i1 == null).slice(-p.keep), ...list.filter((g) => g.i1 != null).slice(-Math.ceil(p.keep / 2))]
      .map((g) => ({ ...g, color: g.bull ? (g.i1 == null ? "rgba(34,176,125,.22)" : "rgba(34,176,125,.08)") : (g.i1 == null ? "rgba(229,72,77,.22)" : "rgba(229,72,77,.08)"), label: g.i1 == null ? "FVG" : "" }));
    return { plots: [boxesPlot("FVG", { n: c.length, list: shown })], note: `미체결 ${list.filter((g) => g.i1 == null).length}개` };
  } },
  order_blocks: { name: "오더블록", group: "스마트머니 (SMC)", pane: "main", desc: "강한 장대봉(ATR의 mult배)이 구조를 깨기 직전의 마지막 반대색 캔들 구간. 종가로 뚫리면 무효", params: { mult: 1.5, keep: 8 }, compute: (c, p) => {
    const a = atr(c, 14), list = [];
    for (let i = 12; i < c.length; i++) {
      const b = c[i]; if (a[i] == null || Math.abs(b.close - b.open) < p.mult * a[i]) continue;
      const bull = b.close > b.open, prevHi = Math.max(...c.slice(i - 10, i).map((q) => q.high)), prevLo = Math.min(...c.slice(i - 10, i).map((q) => q.low));
      if (bull ? b.close <= prevHi : b.close >= prevLo) continue;
      let k = i - 1; while (k > i - 6 && (bull ? c[k].close >= c[k].open : c[k].close <= c[k].open)) k--;
      if (k <= i - 6) continue;
      const ob = { i0: k, i1: null, top: c[k].high, bottom: c[k].low, bull };
      for (let j = i + 1; j < c.length; j++) if (bull ? c[j].close < ob.bottom : c[j].close > ob.top) { ob.i1 = j; break; }
      if (!list.some((o) => o.i0 === ob.i0)) list.push(ob);
    }
    const shown = list.filter((o) => o.i1 == null).slice(-p.keep).map((o) => ({ ...o, color: o.bull ? "rgba(57,135,229,.2)" : "rgba(213,81,129,.2)", label: o.bull ? "매수 OB" : "매도 OB" }));
    return { plots: [boxesPlot("OB", { n: c.length, list: shown })], note: `유효 ${shown.length}개` };
  } },
  sweeps: { name: "유동성 스윕", group: "스마트머니 (SMC)", pane: "main", desc: "직전 스윙 고점(저점)을 꼬리로만 넘었다가 안쪽으로 마감 — 손절 물량을 쓸고 반대로 가는 경우", params: { length: 5 }, compute: (c, p) => {
    const hs = pivots(c.map((b) => b.high), p.length, p.length, true), ls = pivots(c.map((b) => b.low), p.length, p.length, false), s = sig(c.length);
    let hi = null, lo = null; const ch = new Map(hs.map((i) => [i + p.length, i])), cl = new Map(ls.map((i) => [i + p.length, i]));
    c.forEach((b, i) => {
      if (ch.has(i)) hi = c[ch.get(i)].high; if (cl.has(i)) lo = c[cl.get(i)].low;
      if (hi != null && b.high > hi && b.close < hi) { s[i] = { dir: -1, text: "스윕" }; hi = null; } else if (hi != null && b.close > hi) hi = null;
      if (lo != null && b.low < lo && b.close > lo) { s[i] = { dir: 1, text: "스윕" }; lo = null; } else if (lo != null && b.close < lo) lo = null;
    });
    return { plots: [{ name: "스윕", type: "signals", data: s }] };
  } },
  avwap: { name: "앵커드 VWAP (최근 고점·저점)", group: "레벨 · 프로파일", pane: "main", desc: "최근 n봉의 최고점·최저점부터 누적한 VWAP — 그 뒤 들어온 매수자·매도자의 평균 단가", params: { lookback: 150 }, compute: (c, p) => {
    const n = Math.min(p.lookback, c.length), st = c.length - n; let hi = st, lo = st;
    for (let i = st; i < c.length; i++) { if (c[i].high > c[hi].high) hi = i; if (c[i].low < c[lo].low) lo = i; }
    const from = (a) => { let pv = 0, v = 0; return c.map((b, i) => { if (i < a) return null; const tp = (b.high + b.low + b.close) / 3; pv += tp * b.volume; v += b.volume; return v ? pv / v : tp; }); };
    return { plots: [line("고점 기준", from(hi), C.dn, { lineWidth: 2 }), line("저점 기준", from(lo), C.up, { lineWidth: 2 })] };
  } },
  // ---------- 오실레이터 (추가 2)
  cyber_cycle: { name: "사이버 사이클 (Ehlers)", group: "오실레이터", pane: "sub", params: { alpha: 0.07 }, compute: (c, p) => {
    const x = src(c, "hl2"), a = p.alpha, sm = x.map((v, i) => i < 3 ? v : (v + 2 * x[i - 1] + 2 * x[i - 2] + x[i - 3]) / 6), cy = [];
    x.forEach((v, i) => cy.push(i < 7 ? (i < 2 ? 0 : (v - 2 * x[i - 1] + x[i - 2]) / 4)
      : (1 - 0.5 * a) ** 2 * (sm[i] - 2 * sm[i - 1] + sm[i - 2]) + 2 * (1 - a) * cy[i - 1] - (1 - a) ** 2 * cy[i - 2]));
    return { plots: [line("Cycle", cy, C.b), line("트리거", cy.map((_, i) => i ? cy[i - 1] : null), C.a, { lineWidth: 1 })], levels: [0] };
  } },
  smi: { name: "SMI (스토캐스틱 모멘텀)", group: "오실레이터", pane: "sub", params: { length: 10, smooth: 3, signal: 3 }, compute: (c, p) => {
    const hh = highest(c.map((b) => b.high), p.length), ll = lowest(c.map((b) => b.low), p.length);
    const d = c.map((b, i) => hh[i] == null ? null : b.close - (hh[i] + ll[i]) / 2), r = hh.map((v, i) => v == null ? null : v - ll[i]);
    const v = ratio(mul(ema(ema(d, p.smooth), p.smooth), 100), mul(ema(ema(r, p.smooth), p.smooth), 0.5));
    return { plots: [line("SMI", v, C.b), line("시그널", ema(v, p.signal), C.a)], levels: [-40, 0, 40] };
  } },
  // ---------- 통계 · 퀀트
  hurst: { name: "허스트 지수", group: "통계 · 퀀트", pane: "sub", desc: "0.5 위 = 추세가 이어지는 장(추세추종 유리), 0.5 아래 = 되돌리는 장(역추세 유리)", params: { window: 100 }, compute: (c, p) => {
    const r = rets(src(c)), W = Math.max(32, p.window), sizes = [8, 16, 32, 64].filter((s) => s <= W / 2);
    return { plots: [line("H", r.map((_, i) => {
      if (i < W) return null;
      const xs = [], ys = [];
      for (const sz of sizes) {
        let acc = 0, k = 0;
        for (let st = i - W + 1; st + sz - 1 <= i; st += sz) {
          const seg = r.slice(st, st + sz); if (seg.some((v) => v == null)) continue;
          const m = seg.reduce((a, b) => a + b, 0) / sz; let cum = 0, mx = -Infinity, mn = Infinity, ss = 0;
          for (const v of seg) { cum += v - m; mx = Math.max(mx, cum); mn = Math.min(mn, cum); ss += (v - m) ** 2; }
          const sd = Math.sqrt(ss / sz); if (sd > 0) { acc += (mx - mn) / sd; k++; }
        }
        if (k) { xs.push(Math.log(sz)); ys.push(Math.log(acc / k)); }
      }
      if (xs.length < 2) return null;
      const mx = xs.reduce((a, b) => a + b, 0) / xs.length, my = ys.reduce((a, b) => a + b, 0) / ys.length;
      let num = 0, den = 0; xs.forEach((x, j) => { num += (x - mx) * (ys[j] - my); den += (x - mx) ** 2; });
      return den ? num / den : null;
    }), C.e, { lineWidth: 2 })], levels: [0.5] };
  } },
  fdi: { name: "프랙탈 차원 (FDI)", group: "통계 · 퀀트", pane: "sub", desc: "1.5 아래 = 추세, 1.5 위 = 잡음·횡보", params: { length: 30 }, compute: (c, p) => {
    const x = src(c), n = p.length;
    return { plots: [line("FDI", x.map((_, i) => {
      if (i < n - 1) return null;
      let hi = -Infinity, lo = Infinity; for (let j = i - n + 1; j <= i; j++) { hi = Math.max(hi, x[j]); lo = Math.min(lo, x[j]); }
      if (hi === lo) return 1;
      let L = 0; for (let j = i - n + 2; j <= i; j++) { const dy = (x[j] - x[j - 1]) / (hi - lo), dx = 1 / (n - 1); L += Math.sqrt(dx * dx + dy * dy); }
      return 1 + (Math.log(L) + Math.LN2) / Math.log(2 * (n - 1));
    }), C.c)], levels: [1.5] };
  } },
  vol_est: { name: "실현 변동성 (파킨슨 · 가먼-클라스, 연율 %)", group: "통계 · 퀀트", pane: "sub", params: { length: 20 }, compute: (c, p) => {
    const k = Math.sqrt(barsPerYear(c)) * 100;
    const pk = sma(c.map((b) => Math.log(b.high / b.low) ** 2), p.length).map((v) => v == null ? null : Math.sqrt(v / (4 * Math.LN2)) * k);
    const gk = sma(c.map((b) => 0.5 * Math.log(b.high / b.low) ** 2 - (2 * Math.LN2 - 1) * Math.log(b.close / b.open) ** 2), p.length).map((v) => v == null ? null : Math.sqrt(Math.max(0, v)) * k);
    return { plots: [line("Parkinson", pk, C.a), line("Garman-Klass", gk, C.b)] };
  } },
  vol_rank: { name: "변동성 백분위", group: "통계 · 퀀트", pane: "sub", desc: "지금 변동성이 최근 n봉 중 몇 % 수준인지. 10 아래 = 압축(곧 큰 움직임), 90 위 = 과열", params: { length: 20, rank: 250 }, compute: (c, p) => {
    const sd = stdev(rets(src(c)), p.length); return { plots: [line("Vol %", percentrank(sd, p.rank), C.f)], levels: [10, 50, 90] };
  } },
  skew_kurt: { name: "왜도 · 첨도 (수익률)", group: "통계 · 퀀트", pane: "sub", desc: "왜도 < 0 = 급락 꼬리, 첨도가 크면 극단적 움직임이 잦음", params: { length: 50 }, compute: (c, p) => {
    const r = rets(src(c)), n = p.length, sk = Array(c.length).fill(null), ku = [...sk];
    for (let i = n; i < c.length; i++) {
      const w = r.slice(i - n + 1, i + 1); if (w.some((v) => v == null)) continue;
      const m = w.reduce((a, b) => a + b, 0) / n, v2 = w.reduce((a, b) => a + (b - m) ** 2, 0) / n; if (!v2) continue;
      sk[i] = w.reduce((a, b) => a + (b - m) ** 3, 0) / n / v2 ** 1.5; ku[i] = w.reduce((a, b) => a + (b - m) ** 4, 0) / n / v2 ** 2 - 3;
    }
    return { plots: [line("왜도", sk, C.b), line("첨도", ku, C.a, { lineWidth: 1 })], levels: [0] };
  } },
  autocorr: { name: "자기상관 (추세 지속성)", group: "통계 · 퀀트", pane: "sub", desc: "+ = 오른 뒤 또 오르는 경향(모멘텀), − = 오른 뒤 내리는 경향(평균회귀)", params: { length: 50 }, compute: (c, p) => {
    const r = rets(src(c)), cr = rollCorr(r, shift(r, 1), p.length); return { plots: [hist("AC(1)", cr.map((v) => v?.corr ?? null), cr.map((v) => v == null ? null : v.corr >= 0 ? "rgba(34,176,125,.7)" : "rgba(229,72,77,.7)"))], levels: [0] };
  } },
  rs_btc: { name: "BTC 대비 상대강도", group: "통계 · 퀀트", pane: "sub", remote: "btc", desc: "이 코인 ÷ BTC (시작 = 100). 오르면 비트코인보다 강함", params: { ema: 20 }, compute: (c, p, ext) => {
    const b = btcAligned(c, ext), r = c.map((q, i) => b[i] ? q.close / b[i] : null), f = r.find((v) => v != null);
    const v = r.map((x) => x == null || !f ? null : x / f * 100);
    return { plots: [line("RS", v, C.a, { lineWidth: 2 }), line(`EMA ${p.ema}`, ema(v, p.ema), C.b, { lineWidth: 1 })], levels: [100], note: ext?.btc ? "" : "BTC 데이터 불러오는 중" };
  } },
  corr_btc: { name: "BTC 상관 · 베타", group: "통계 · 퀀트", pane: "sub", remote: "btc", desc: "상관 1 = BTC 와 똑같이 움직임. 베타 1.5 = BTC 가 1% 움직일 때 1.5% 움직임", params: { length: 30 }, compute: (c, p, ext) => {
    const cr = rollCorr(rets(src(c)), rets(btcAligned(c, ext)), p.length);
    return { plots: [line("상관", cr.map((v) => v?.corr ?? null), C.b, { lineWidth: 2 }), line("베타", cr.map((v) => v?.beta ?? null), C.a, { lineWidth: 1 })], levels: [0, 1] };
  } },
  // ---------- 거래량 (추가 2)
  tmf: { name: "트위그스 머니 플로우", group: "거래량", pane: "sub", params: { length: 21 }, compute: (c, p) => {
    const ad = c.map((b, i) => { const pc = i ? c[i - 1].close : b.open, th = Math.max(b.high, pc), tl = Math.min(b.low, pc); return th === tl ? 0 : b.volume * ((b.close - tl) - (th - b.close)) / (th - tl); });
    const v = ratio(rma(ad, p.length), rma(c.map((b) => b.volume), p.length)); return { plots: [hist("TMF", v, signColors(v))], levels: [0] };
  } },
});

// ---------------------------------------------------------------- 세션 볼륨 프로파일
// type: "profiles" = 세션마다 가격대별 거래량 막대 (차트가 직접 그림)
function sessionKey(t, mode, step) {
  if (step >= 14400) return Math.floor((t / 86400 + 3) / 7);            // 4시간봉 이상은 주 단위
  const d = Math.floor(t / 86400);
  if (mode !== 2) return d;
  const h = (t % 86400) / 3600;
  return d * 3 + (h < 8 ? 0 : h < 13.5 ? 1 : 2);                        // 아시아 · 유럽 · 미국 (UTC)
}
const SESSION_NAME = ["아시아", "유럽", "미국"];
Object.assign(INDICATORS, {
  session_vp: { name: "세션 볼륨 프로파일", group: "레벨 · 프로파일", pane: "main",
    desc: "하루(또는 아시아·유럽·미국 세션)마다 가격대별 거래량. 주황 = POC(가장 많이 거래된 가격), 점선 = 가치영역(70%). 아직 다시 안 닿은 POC(nPOC)는 오른쪽으로 이어 그림 — 가격이 되돌아와 닿는 경우가 많음. mode 1=일별 2=세션별",
    params: { mode: 1, sessions: 8, rows: 24, va: 70 }, compute: (c, p) => {
      if (c.length < 2) return { plots: [] };
      const step = c.at(-1).time - c.at(-2).time, groups = [];
      c.forEach((b, i) => { const k = sessionKey(b.time, p.mode, step); if (!groups.length || groups.at(-1).k !== k) groups.push({ k, i0: i, i1: i }); else groups.at(-1).i1 = i; });
      const shown = groups.slice(-Math.max(1, p.sessions));
      const sessions = shown.map((g) => {
        const vp = volumeProfile(c.slice(g.i0, g.i1 + 1), Math.max(6, p.rows), p.va);
        if (!vp) return null;
        let naked = true;
        for (let j = g.i1 + 1; j < c.length && naked; j++) if (c[j].low <= vp.poc && c[j].high >= vp.poc) naked = false;
        const t0 = c[g.i0].time, name = p.mode === 2 && step < 14400 ? SESSION_NAME[((g.k % 3) + 3) % 3] : "";
        return { i0: g.i0, i1: g.i1, ...vp, naked: naked && g !== groups.at(-1), current: g === groups.at(-1), name, t0 };
      }).filter(Boolean);
      // 현재 세션의 진행 중 POC · 직전 세션 POC/VAH/VAL 을 선으로 (값 확인용)
      const cur = groups.at(-1), prev = groups.length > 1 ? groups.at(-2) : null;
      const dpoc = Array(c.length).fill(null), pp = [...dpoc], pvah = [...dpoc], pval = [...dpoc];
      for (let i = cur.i0; i < c.length; i++) dpoc[i] = volumeProfile(c.slice(cur.i0, i + 1), Math.max(6, p.rows), p.va)?.poc ?? null;
      if (prev) { const v = volumeProfile(c.slice(prev.i0, prev.i1 + 1), Math.max(6, p.rows), p.va); if (v) for (let i = cur.i0; i < c.length; i++) { pp[i] = v.poc; pvah[i] = v.vah; pval[i] = v.val; } }
      return { plots: [
        line("진행 중 POC", dpoc, "rgba(245,165,36,.9)", { lineWidth: 1, lineStyle: 1 }),
        line("직전 POC", pp, "rgba(245,165,36,.5)", { lineWidth: 1, lineStyle: 2 }),
        line("직전 VAH", pvah, "rgba(164,172,182,.45)", { lineWidth: 1, lineStyle: 2 }),
        line("직전 VAL", pval, "rgba(164,172,182,.45)", { lineWidth: 1, lineStyle: 2 }),
        { name: "세션", type: "profiles", data: Array(c.length).fill(null), sessions },
      ], note: step >= 14400 ? "4시간봉 이상은 주 단위" : p.mode === 2 ? "아시아 00–08 · 유럽 08–13:30 · 미국 13:30–24 (UTC)" : "하루 = UTC 0시 기준" };
    } },
});

// ---------------------------------------------------------------- 추가 지표 3: 빌 윌리엄스 · 변동성 · 레벨 · 세션
const shiftR = (x, n) => x.map((_, i) => i - n >= 0 ? x[i - n] : null);          // 오른쪽으로 n봉 밀기
const sumN = (x, n) => x.map((_, i) => { if (i < n - 1) return null; let s = 0; for (let j = i - n + 1; j <= i; j++) { if (x[j] == null) return null; s += x[j]; } return s; });
const growColors = (x, up = "rgba(34,176,125,.85)", dn = "rgba(229,72,77,.85)") => x.map((v, i) => v == null ? null : Math.abs(v) >= Math.abs(x[i - 1] ?? 0) ? up : dn);
const intraday = (c) => c.length > 1 && c.at(-1).time - c.at(-2).time < 14400;
function prevPeriodHLC(c, key) {   // 봉마다 '직전 기간'의 고가·저가·종가
  let cur = null, h, l, cl, ph = null, pl = null, pc = null; const H = [], L = [], Cc = [];
  c.forEach((b) => { const k = key(b.time); if (k !== cur) { if (cur != null) { ph = h; pl = l; pc = cl; } cur = k; h = b.high; l = b.low; } else { h = Math.max(h, b.high); l = Math.min(l, b.low); } cl = b.close; H.push(ph); L.push(pl); Cc.push(pc); });
  return [H, L, Cc];
}
const monthKey = (t) => { const d = new Date(t * 1000); return d.getUTCFullYear() * 12 + d.getUTCMonth(); };
const periodKey = (n) => n === 30 ? monthKey : n === 7 ? (t) => Math.floor((t / 86400 + 3) / 7) : (t) => Math.floor(t / 86400);

Object.assign(INDICATORS, {
  alligator: { name: "윌리엄스 앨리게이터", group: "추세", pane: "main", desc: "턱(파랑)·이빨(빨강)·입술(초록) 세 이평이 벌어지면 추세, 엉켜 있으면 잠자는 구간",
    params: { jaw: 13, teeth: 8, lips: 5 }, compute: (c, p) => {
      const x = src(c, "hl2");
      return { plots: [line("턱", shiftR(rma(x, p.jaw), 8), C.b, { lineWidth: 1 }), line("이빨", shiftR(rma(x, p.teeth), 5), C.f, { lineWidth: 1 }), line("입술", shiftR(rma(x, p.lips), 3), C.up, { lineWidth: 1 })] };
    } },
  gator: { name: "게이터 오실레이터", group: "오실레이터", pane: "sub", desc: "앨리게이터 선들의 벌어짐. 위아래 막대가 모두 커지면(초록) 추세가 먹는 중", params: {}, compute: (c) => {
    const x = src(c, "hl2"), jaw = shiftR(rma(x, 13), 8), teeth = shiftR(rma(x, 8), 5), lips = shiftR(rma(x, 5), 3);
    const u = jaw.map((v, i) => v == null || teeth[i] == null ? null : Math.abs(v - teeth[i])), d = teeth.map((v, i) => v == null || lips[i] == null ? null : -Math.abs(v - lips[i]));
    return { plots: [hist("위", u, growColors(u)), hist("아래", d, growColors(d))], levels: [0] };
  } },
  ewo: { name: "엘리엇 웨이브 오실레이터", group: "오실레이터", pane: "sub", desc: "SMA5 − SMA35 (가격 대비 %). 파동 3에서 가장 크게 튐", params: { fast: 5, slow: 35 }, compute: (c, p) => {
    const x = src(c, "hl2"), f = sma(x, p.fast), s = sma(x, p.slow), v = f.map((a, i) => a == null || s[i] == null ? null : (a - s[i]) / c[i].close * 100);
    return { plots: [hist("EWO %", v, signColors(v))], levels: [0] };
  } },
  vix_fix: { name: "윌리엄스 VIX 픽스 (바닥 탐지)", group: "변동성", pane: "sub", desc: "공포 지수를 가격으로 흉내. 초록 막대 = 공포가 극단 → 바닥권일 가능성", params: { length: 22, bb: 20, mult: 2, lookback: 50 }, compute: (c, p) => {
    const cl = c.map((b) => b.close), hc = highest(cl, p.length), w = c.map((b, i) => hc[i] == null ? null : (hc[i] - b.low) / hc[i] * 100);
    const m = sma(w, p.bb), sd = stdev(w, p.bb), rh = highest(w.map((v) => v ?? 0), p.lookback);
    const col = w.map((v, i) => v == null ? null : (m[i] != null && v >= m[i] + p.mult * sd[i]) || (rh[i] != null && v >= rh[i] * 0.85) ? "rgba(34,176,125,.9)" : "rgba(164,172,182,.35)");
    return { plots: [hist("WVF", w, col)] };
  } },
  ulcer: { name: "얼서 인덱스 (낙폭 고통)", group: "변동성", pane: "sub", desc: "최근 고점 대비 낙폭의 깊이·기간. 높을수록 보유가 괴로운 구간", params: { length: 14 }, compute: (c, p) => {
    const cl = c.map((b) => b.close), hc = highest(cl, p.length), dd2 = cl.map((v, i) => hc[i] == null ? null : (100 * (v - hc[i]) / hc[i]) ** 2);
    return { plots: [line("Ulcer", sma(dd2, p.length).map((v) => v == null ? null : Math.sqrt(v)), C.f)] };
  } },
  rvix: { name: "상대 변동성 지수 (도시 RVI)", group: "변동성", pane: "sub", desc: "오르는 날의 변동성 비중. 50 위 = 상승 쪽 변동성 우세 (다른 지표 확인용)", params: { length: 10, smooth: 14 }, compute: (c, p) => {
    const cl = c.map((b) => b.close), sd = stdev(cl, p.length);
    const u = cl.map((v, i) => sd[i] == null || !i ? null : v > cl[i - 1] ? sd[i] : 0), d = cl.map((v, i) => sd[i] == null || !i ? null : v < cl[i - 1] ? sd[i] : 0);
    const eu = ema(u, p.smooth), ed = ema(d, p.smooth);
    return { plots: [line("RVI", eu.map((v, i) => v == null || ed[i] == null || v + ed[i] === 0 ? null : 100 * v / (v + ed[i])), C.e)], levels: [30, 50, 70] };
  } },
  chaikin_vol: { name: "차이킨 변동성", group: "변동성", pane: "sub", desc: "고가−저가 폭의 EMA 가 n봉 전보다 몇 % 커졌나. 급등 = 변동성 폭발", params: { length: 10, roc: 10 }, compute: (c, p) => {
    const e = ema(c.map((b) => b.high - b.low), p.length), v = e.map((x, i) => x == null || e[i - p.roc] == null || !e[i - p.roc] ? null : (x / e[i - p.roc] - 1) * 100);
    return { plots: [line("CV %", v, C.a)], levels: [0] };
  } },
  vhf: { name: "VHF (추세/횡보 판별)", group: "변동성", pane: "sub", desc: "값이 높으면 추세장, 낮으면 횡보장 (0.35 부근이 경계인 경우가 많음)", params: { length: 28 }, compute: (c, p) => {
    const cl = c.map((b) => b.close), h = highest(cl, p.length), l = lowest(cl, p.length), s = sumN(cl.map((v, i) => i ? Math.abs(v - cl[i - 1]) : null), p.length);
    return { plots: [line("VHF", h.map((v, i) => v == null || !s[i] ? null : (v - l[i]) / s[i]), C.b)], levels: [0.35] };
  } },
  qstick: { name: "Q스틱 (몸통 평균)", group: "오실레이터", pane: "sub", desc: "최근 캔들 몸통(종가−시가)의 평균. 0 위 = 양봉 우세", params: { length: 8 }, compute: (c, p) => {
    const v = sma(c.map((b) => b.close - b.open), p.length); return { plots: [hist("Qstick", v, signColors(v))], levels: [0] };
  } },
  nvi_pvi: { name: "NVI · PVI (스마트/대중 자금)", group: "거래량", pane: "sub", desc: "NVI = 거래량이 줄어든 날의 움직임(조용한 스마트머니), PVI = 거래량이 늘어난 날(대중). 선이 자기 EMA 위면 그쪽이 강세", params: { signal: 255 }, compute: (c, p) => {
    let n = 1000, q = 1000; const N1 = [], P1 = [];
    c.forEach((b, i) => { if (i) { const r = b.close / c[i - 1].close - 1; if (b.volume < c[i - 1].volume) n *= 1 + r; else if (b.volume > c[i - 1].volume) q *= 1 + r; } N1.push(n); P1.push(q); });
    return { plots: [line("NVI", N1, C.a), line("NVI EMA", ema(N1, Math.min(p.signal, Math.max(2, c.length - 1))), "rgba(245,165,36,.45)", { lineWidth: 1 }),
      line("PVI", P1, C.b), line("PVI EMA", ema(P1, Math.min(p.signal, Math.max(2, c.length - 1))), "rgba(57,135,229,.45)", { lineWidth: 1 })] };
  } },
  cog: { name: "무게중심 오실레이터 (COG)", group: "오실레이터", pane: "sub", desc: "Ehlers. 선이 신호선을 위로 뚫으면 단기 반등", params: { length: 10 }, compute: (c, p) => {
    const x = src(c, "hl2"), v = x.map((_, i) => { if (i < p.length - 1) return null; let num = 0, den = 0; for (let k = 0; k < p.length; k++) { num += (k + 1) * x[i - k]; den += x[i - k]; } return den ? -num / den + (p.length + 1) / 2 : null; });
    const s = shiftR(v, 1);
    return { plots: [line("COG", v, C.c), line("신호", s, C.g, { lineWidth: 1 }), { name: "교차", type: "signals", data: crossSignals(v, s, "", "").map((x) => x && { ...x, size: 0.4 }) }] };
  } },
  linreg_slope: { name: "선형회귀 기울기 (%)", group: "통계 · 퀀트", pane: "sub", desc: "최근 n봉 회귀선이 n봉 동안 몇 % 오르내리는 기울기인가", params: { length: 50 }, compute: (c, p) => {
    const x = src(c), v = x.map((_, i) => { if (i < p.length - 1) return null; let sx = 0, sy = 0, sxy = 0, sxx = 0; const n = p.length;
      for (let j = 0; j < n; j++) { const y = x[i - n + 1 + j]; sx += j; sy += y; sxy += j * y; sxx += j * j; }
      const b = (n * sxy - sx * sy) / (n * sxx - sx * sx); return b * n / (sy / n) * 100; });
    return { plots: [hist("기울기 %", v, signColors(v))], levels: [0] };
  } },
  r2: { name: "결정계수 R² (추세 신뢰도)", group: "통계 · 퀀트", pane: "sub", desc: "가격이 직선 추세에 얼마나 잘 맞나 (0~1). 0.7 이상이면 깔끔한 추세", params: { length: 50 }, compute: (c, p) => {
    const x = src(c), n = p.length, idx = Array.from({ length: n }, (_, j) => j);
    const v = x.map((_, i) => { if (i < n - 1) return null; const y = x.slice(i - n + 1, i + 1), my = y.reduce((a, b) => a + b, 0) / n, mx = (n - 1) / 2;
      let sxy = 0, sxx = 0, syy = 0; idx.forEach((j) => { sxy += (j - mx) * (y[j] - my); sxx += (j - mx) ** 2; syy += (y[j] - my) ** 2; }); return syy ? sxy * sxy / (sxx * syy) : null; });
    return { plots: [line("R²", v, C.d)], levels: [0.3, 0.7] };
  } },
  atr_stop: { name: "ATR 트레일링 스톱", group: "신호 · 패턴", pane: "main", desc: "종가에서 ATR×배수 만큼 떨어져 따라오는 손절선. 뚫리면 방향 전환", params: { length: 14, mult: 3 }, compute: (c, p) => {
    const a = atr(c, p.length), st = Array(c.length).fill(null), s = sig(c.length); let dir = 1, prev = null;
    c.forEach((b, i) => {
      if (a[i] == null) return;
      const lo = b.close - p.mult * a[i], hi = b.close + p.mult * a[i];
      if (prev == null) prev = lo;
      else if (dir === 1) { if (b.close < prev) { dir = -1; prev = hi; s[i] = { dir: -1, text: "ATR 숏" }; } else prev = Math.max(prev, lo); }
      else if (b.close > prev) { dir = 1; prev = lo; s[i] = { dir: 1, text: "ATR 롱" }; } else prev = Math.min(prev, hi);
      st[i] = prev * dir;
    });
    return { plots: [line("롱 스톱", st.map((v) => v != null && v > 0 ? v : null), C.up, { lineWidth: 1 }), line("숏 스톱", st.map((v) => v != null && v < 0 ? -v : null), C.dn, { lineWidth: 1 }), { name: "전환", type: "signals", data: s }] };
  } },
  ha_trend: { name: "하이킨아시 추세 전환", group: "신호 · 패턴", pane: "main", desc: "하이킨아시 캔들 색이 min 봉 이상 이어지다 바뀌면 표시 (노이즈를 줄인 추세 전환)", params: { min: 4 }, compute: (c, p) => {
    const s = sig(c.length); let ho = null, hc = null, run = 0, prevUp = null;
    c.forEach((b, i) => {
      const nc = (b.open + b.high + b.low + b.close) / 4, no = ho == null ? (b.open + b.close) / 2 : (ho + hc) / 2; ho = no; hc = nc;
      const up = nc >= no;
      if (prevUp != null && up !== prevUp) { if (run >= p.min) s[i] = { dir: up ? 1 : -1, text: up ? "HA 상승" : "HA 하락", size: 0.6 }; run = 1; } else run++;
      prevUp = up;
    });
    return { plots: [{ name: "HA", type: "signals", data: s }] };
  } },
  camarilla: { name: "카마릴라 피봇", group: "레벨 · 프로파일", pane: "main", desc: "전일 범위로 만든 단타 레벨. R3/S3 = 되돌림(역추세) 자리, R4/S4 돌파 = 추세 추종", params: { period: 1 }, compute: (c, p) => {
    const [H, L, Cc] = prevPeriodHLC(c, periodKey(p.period)), f = (k) => H.map((h, i) => h == null ? null : Cc[i] + k * (h - L[i]) * 1.1);
    return { plots: [line("R4", f(1 / 2), C.dn, { lineWidth: 1 }), line("R3", f(1 / 4), "rgba(229,72,77,.6)", { lineWidth: 1, lineStyle: 2 }),
      line("S3", f(-1 / 4), "rgba(34,176,125,.6)", { lineWidth: 1, lineStyle: 2 }), line("S4", f(-1 / 2), C.up, { lineWidth: 1 })], note: p.period === 7 ? "전주 기준" : p.period === 30 ? "전월 기준" : "전일 기준" };
  } },
  fib_pivots: { name: "피보나치 피봇", group: "레벨 · 프로파일", pane: "main", desc: "P ± 전일 범위 × 0.382 / 0.618 / 1. period 1=일 7=주 30=월", params: { period: 1 }, compute: (c, p) => {
    const [H, L, Cc] = prevPeriodHLC(c, periodKey(p.period)), P = H.map((h, i) => h == null ? null : (h + L[i] + Cc[i]) / 3), f = (k) => P.map((v, i) => v == null ? null : v + k * (H[i] - L[i]));
    return { plots: [line("P", P, C.a, { lineWidth: 1 }), ...[[1, "R3"], [0.618, "R2"], [0.382, "R1"]].map(([k, n]) => line(n, f(k), k === 1 ? C.dn : "rgba(229,72,77,.6)", { lineWidth: 1, lineStyle: k === 1 ? 0 : 2 })),
      ...[[-0.382, "S1"], [-0.618, "S2"], [-1, "S3"]].map(([k, n]) => line(n, f(k), k === -1 ? C.up : "rgba(34,176,125,.6)", { lineWidth: 1, lineStyle: k === -1 ? 0 : 2 }))] };
  } },
  pmhl: { name: "전월 고가/저가 · 월 시가", group: "레벨 · 프로파일", pane: "main", desc: "PMH/PML 과 이번 달 시가 (UTC)", params: {}, compute: (c) => {
    const [H, L] = prevPeriodHLC(c, monthKey); let k = null, o = null;
    const mo = c.map((b) => { const m = monthKey(b.time); if (m !== k) { k = m; o = b.open; } return o; });
    return { plots: [line("전월 고가", H, C.dn, { lineWidth: 2 }), line("전월 저가", L, C.up, { lineWidth: 2 }), line("월 시가", mo, C.a, { lineWidth: 1, lineStyle: 1 })] };
  } },
  round_numbers: { name: "라운드 넘버 (심리 가격)", group: "레벨 · 프로파일", pane: "main", desc: "60,000 · 3,000 · 1.00 처럼 딱 떨어지는 가격. 주문이 몰려 지지·저항이 되기 쉬움", params: { lines: 10 }, compute: (c, p) => {
    if (!c.length) return { plots: [] };
    const last = c.at(-1).close, rng = c.slice(-300), hi = Math.max(...rng.map((b) => b.high)), lo = Math.min(...rng.map((b) => b.low));
    let step = 10 ** Math.floor(Math.log10(last));
    for (const m of [0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1]) { step = 10 ** Math.floor(Math.log10(last)) * m; if ((hi - lo) / step <= p.lines) break; }
    const out = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi && out.length < 16; v += step) out.push(+v.toPrecision(12));
    const major = (v) => Math.abs(v / (step * 10) - Math.round(v / (step * 10))) < 1e-9 || step >= 10 ** Math.floor(Math.log10(last));
    return { plots: out.map((v) => line(px0(v), c.map(() => v), major(v) ? "rgba(245,165,36,.75)" : "rgba(164,172,182,.4)", { lineWidth: 1, lineStyle: major(v) ? 0 : 2, legend: false })), note: `간격 ${step}` };
  } },
  sessions_hl: { name: "세션 고저 (아시아·런던·뉴욕)", group: "레벨 · 프로파일", pane: "main", desc: "UTC 아시아 00–08 · 런던 07–16 · 뉴욕 13–21 구간의 고가·저가 상자. 세션 고저 사냥(스윕) 후 되돌림을 볼 때 사용 (일광절약시간 미반영)", params: { days: 5 }, compute: (c, p) => {
    if (!intraday(c)) return { plots: [boxesPlot("세션", { n: c.length, list: [] })], note: "4시간봉 미만에서만" };
    const S = [["아시아", 0, 8, "57,135,229"], ["런던", 7, 16, "201,133,0"], ["뉴욕", 13, 21, "213,81,129"]], list = [], lastDay = Math.floor(c.at(-1).time / 86400);
    for (let d = lastDay - p.days + 1; d <= lastDay; d++) for (const [nm, h0, h1, rgb] of S) {
      let i0 = -1, i1 = -1, hi = -Infinity, lo = Infinity;
      c.forEach((b, i) => { const h = (b.time - d * 86400) / 3600; if (h >= h0 && h < h1) { if (i0 < 0) i0 = i; i1 = i; hi = Math.max(hi, b.high); lo = Math.min(lo, b.low); } });
      if (i0 >= 0) list.push({ i0, i1, top: hi, bottom: lo, color: `rgba(${rgb},.1)`, label: nm });
    }
    return { plots: [boxesPlot("세션", { n: c.length, list })] };
  } },
  orb: { name: "오프닝 레인지 돌파 (ORB)", group: "신호 · 패턴", pane: "main", desc: "하루 시작 후 minutes 분의 고가·저가. 종가가 그 밖으로 나가면 돌파 신호. session 0=UTC 0시 1=뉴욕 개장 13:30", params: { minutes: 60, session: 0 }, compute: (c, p) => {
    const H = Array(c.length).fill(null), L = [...H], s = sig(c.length);
    if (!intraday(c)) return { plots: [line("OR 고가", H, C.dn), line("OR 저가", L, C.up)], note: "4시간봉 미만에서만" };
    const off = p.session ? 13.5 * 3600 : 0; let key = null, hi, lo, done, fired;
    c.forEach((b, i) => {
      const t = b.time - off, k = Math.floor(t / 86400), m = (t - k * 86400) / 60;
      if (k !== key) { key = k; hi = -Infinity; lo = Infinity; done = false; fired = 0; }
      if (m < p.minutes) { hi = Math.max(hi, b.high); lo = Math.min(lo, b.low); return; }
      done = hi > -Infinity; if (!done) return;
      H[i] = hi; L[i] = lo;
      if (!fired && b.close > hi) { s[i] = { dir: 1, text: "ORB 롱" }; fired = 1; } else if (!fired && b.close < lo) { s[i] = { dir: -1, text: "ORB 숏" }; fired = 1; }
    });
    return { plots: [line("OR 고가", H, C.dn, { lineWidth: 1 }), line("OR 저가", L, C.up, { lineWidth: 1 }), { name: "돌파", type: "signals", data: s }] };
  } },
  adr: { name: "ADR 목표 (평균 일간 범위)", group: "레벨 · 프로파일", pane: "main", desc: "오늘 저가 + 평균 하루 변동폭 = 위쪽 도달 예상, 오늘 고가 − 평균폭 = 아래쪽. 이미 평균폭을 다 썼으면 추가 확장이 어렵다는 참고", params: { days: 14 }, compute: (c, p) => {
    const days = []; let k = null;
    c.forEach((b) => { const d = Math.floor(b.time / 86400); if (d !== k) { k = d; days.push({ d, h: b.high, l: b.low }); } else { const x = days.at(-1); x.h = Math.max(x.h, b.high); x.l = Math.min(x.l, b.low); } });
    const adr = new Map(); days.forEach((x, j) => { if (j >= p.days) adr.set(x.d, days.slice(j - p.days, j).reduce((s, y) => s + y.h - y.l, 0) / p.days); });
    const U = [], D = []; let dh = null, dl = null; k = null;
    c.forEach((b) => { const d = Math.floor(b.time / 86400); if (d !== k) { k = d; dh = b.high; dl = b.low; } else { dh = Math.max(dh, b.high); dl = Math.min(dl, b.low); } const a = adr.get(d); U.push(a ? dl + a : null); D.push(a ? dh - a : null); });
    const a = adr.get(k), used = a ? (dh - dl) / a * 100 : null;
    return { plots: [line("ADR 상단", U, "rgba(229,72,77,.7)", { lineWidth: 1, lineStyle: 2 }), line("ADR 하단", D, "rgba(34,176,125,.7)", { lineWidth: 1, lineStyle: 2 })], note: used != null ? `오늘 평균폭의 ${used.toFixed(0)}% 사용` : "" };
  } },
});
const px0 = (v) => v.toLocaleString("en-US", { maximumFractionDigits: 8 });

// ---------------------------------------------------------------- 차트 패턴 자동 인식
// 스윙 고점·저점(좌우 len 봉)을 번갈아 이어 놓고, 최근 3~5개 점의 모양으로 패턴을 판정한다.
// 헤드앤숄더 · 역헤드앤숄더 · 쌍봉/쌍바닥 · 삼중천정/삼중바닥 · 깃발 · 삼각형(상승/하락/대칭) · 쐐기 · 채널 · 박스권 · 확장형
// type "patterns": 차트가 선·이름·목표가를 직접 그림
function swingSeq(c, len) {
  const hs = pivots(c.map((b) => b.high), len, len, true).map((i) => ({ i, p: c[i].high, h: true }));
  const ls = pivots(c.map((b) => b.low), len, len, false).map((i) => ({ i, p: c[i].low, h: false }));
  const seq = [];
  for (const x of [...hs, ...ls].sort((a, b) => a.i - b.i || (a.h ? -1 : 1))) {
    const l = seq.at(-1);
    if (l && l.h === x.h) { if (x.h ? x.p > l.p : x.p < l.p) seq[seq.length - 1] = x; } else seq.push(x);
  }
  return seq;
}
function fitLn(pts) {   // 최소제곱 직선 + 최대 잔차
  const n = pts.length, mx = pts.reduce((s, q) => s + q.i, 0) / n, my = pts.reduce((s, q) => s + q.p, 0) / n;
  let sxy = 0, sxx = 0; pts.forEach((q) => { sxy += (q.i - mx) * (q.p - my); sxx += (q.i - mx) ** 2; });
  const b = sxx ? sxy / sxx : 0, a = my - b * mx;
  return { a, b, at: (i) => a + b * i, err: Math.max(...pts.map((q) => Math.abs(q.p - (a + b * q.i)))) };
}
export function detectPatterns(c, p = {}) {
  const len = p.len ?? 5, tolK = p.tol ?? 0.6, out = [];
  if (c.length < len * 6) return out;
  const A = atr(c, 14), atrAt = (i) => A[i] ?? (c[i].high - c[i].low), tol = (i) => atrAt(i) * tolK;
  const seq = swingSeq(c, len), last = c.length - 1;
  // 마지막 점 이후 봉을 따라가며 돌파/실패를 판정
  const follow = (e, wait, upAt, dnAt) => {
    for (let j = e + 1; j <= Math.min(last, e + wait); j++) {
      const cl = c[j].close;
      if (upAt && cl > upAt(j)) return { st: "up", j };
      if (dnAt && cl < dnAt(j)) return { st: "down", j };
    }
    return e + wait < last ? { st: "expired" } : { st: "forming", j: last };
  };
  let from = 0;
  for (let k = 2; k < seq.length; k++) {
    if (k - 3 < from) continue;
    const q = (o) => seq[k - o], e = q(0).i, found = [];
    // --- 5점 패턴
    if (k - 4 >= from) {
      const [a1, b1, a2, b2, a3] = [q(4), q(3), q(2), q(1), q(0)], T = tol(a2.i), top = a3.h;
      const sgn = top ? 1 : -1, hi = (x) => sgn * x.p;   // 천정형은 그대로, 바닥형은 뒤집어서 같은 규칙
      const span = a3.i - a1.i;
      if (span >= len * 4 && span <= 250) {
        const neck = fitLn([b1, b2]), neckAt = (i) => neck.at(i);
        const shoulders = Math.abs(a1.p - a3.p) <= 1.5 * T && Math.min(hi(a1), hi(a3)) > Math.max(hi(b1), hi(b2)) + T;
        const ratio = (a2.i - a1.i) / Math.max(1, a3.i - a2.i);
        if (shoulders && hi(a2) > Math.max(hi(a1), hi(a3)) + T && ratio > 0.33 && ratio < 3 && Math.abs(b1.p - b2.p) <= 3 * T) {
          const r = top ? follow(e, span, (j) => a2.p, neckAt) : follow(e, span, neckAt, (j) => a2.p), brk = top ? "down" : "up";
          const height = Math.abs(a2.p - neckAt(a2.i));
          found.push({ key: top ? "hs" : "ihs", name: top ? "헤드앤숄더" : "역헤드앤숄더", dir: top ? -1 : 1, pts: [a1, b1, a2, b2, a3], r, brk,
            lines: [[a1.i, neckAt(a1.i), (r.j ?? last), neckAt(r.j ?? last), "넥라인"]], height, level: neckAt });
        } else if ([a1, a2, a3].every((x) => Math.abs(x.p - (a1.p + a2.p + a3.p) / 3) <= T) && Math.min(hi(a1), hi(a2), hi(a3)) > Math.max(hi(b1), hi(b2)) + 2 * T) {
          const nk = top ? Math.min(b1.p, b2.p) : Math.max(b1.p, b2.p), ext = top ? Math.max(a1.p, a2.p, a3.p) : Math.min(a1.p, a2.p, a3.p);
          const r = top ? follow(e, span, () => ext + T * 0.5, () => nk) : follow(e, span, () => nk, () => ext - T * 0.5);
          found.push({ key: top ? "tt" : "tb", name: top ? "삼중천정" : "삼중바닥", dir: top ? -1 : 1, pts: [a1, b1, a2, b2, a3], r, brk: top ? "down" : "up",
            lines: [[a1.i, nk, r.j ?? last, nk, "넥라인"]], height: Math.abs(ext - nk), level: () => nk });
        }
      }
      // 깃발: 짧고 강한 깃대(b1→a2 가 아니라 q4→q3) 뒤 작은 역방향 조정
      if (!found.length) {
        const [p0, p1, f1, f2, f3] = [q(4), q(3), q(2), q(1), q(0)], pole = p1.p - p0.p, bull = pole > 0, P = Math.abs(pole);
        const poleBars = p1.i - p0.i, flagBars = f3.i - p1.i;
        if (P >= 4 * atrAt(p1.i) && poleBars <= 15 && flagBars <= poleBars * 3 + 10 && flagBars >= len * 2) {
          const pts = [p1, f1, f2, f3], hiPts = pts.filter((x) => x.h), loPts = pts.filter((x) => !x.h);
          const inRange = pts.every((x) => bull ? x.p >= p1.p - 0.5 * P && x.p <= p1.p + tol(p1.i) : x.p <= p1.p + 0.5 * P && x.p >= p1.p - tol(p1.i));
          if (inRange && hiPts.length >= 2 && loPts.length >= 2) {
            const U = fitLn(hiPts), D = fitLn(loPts), counter = bull ? U.b <= 0.1 * atrAt(e) / len : U.b >= -0.1 * atrAt(e) / len;
            if (counter) {
              const r = bull ? follow(e, flagBars + 10, U.at, (j) => Math.min(...loPts.map((x) => x.p)) - tol(e)) : follow(e, flagBars + 10, (j) => Math.max(...hiPts.map((x) => x.p)) + tol(e), D.at);
              found.push({ key: bull ? "bflag" : "sflag", name: bull ? "상승 깃발" : "하락 깃발", dir: bull ? 1 : -1, pts: [p0, p1], r, brk: bull ? "up" : "down",
                lines: [[hiPts[0].i, U.at(hiPts[0].i), r.j ?? last, U.at(r.j ?? last), ""], [loPts[0].i, D.at(loPts[0].i), r.j ?? last, D.at(r.j ?? last), ""]],
                height: P, level: (i, d) => d === "up" ? U.at(i) : D.at(i), poly: true });
            }
          }
        }
      }
      // 삼각형 · 쐐기 · 채널 · 박스권 · 확장형 (마지막 5점)
      if (!found.length) {
        const pts = [q(4), q(3), q(2), q(1), q(0)], U = fitLn(pts.filter((x) => x.h)), D = fitLn(pts.filter((x) => !x.h)), s = pts[0].i, span = e - s, T = tol(e);
        const w0 = U.at(s) - D.at(s), w1 = U.at(e) - D.at(e);
        if (span >= len * 4 && span <= 250 && w0 > 2 * T && w1 > T && U.err <= T && D.err <= T) {
          const su = (U.at(e) - U.at(s)) / w0, sl = (D.at(e) - D.at(s)) / w0, flat = 0.2, conv = w1 / w0;
          let key = null, name = "", dir = 0;
          if (conv < 0.75) {
            if (Math.abs(su) < flat && sl > flat) [key, name, dir] = ["asc", "상승 삼각형", 1];
            else if (su < -flat && Math.abs(sl) < flat) [key, name, dir] = ["desc", "하락 삼각형", -1];
            else if (su < -flat && sl > flat) [key, name, dir] = ["sym", "대칭 삼각형", 0];
            else if (su > flat && sl > flat) [key, name, dir] = ["rwedge", "상승 쐐기", -1];
            else if (su < -flat && sl < -flat) [key, name, dir] = ["fwedge", "하락 쐐기", 1];
          } else if (conv <= 1.33) {
            if (Math.abs(su) < flat && Math.abs(sl) < flat) [key, name, dir] = ["rect", "박스권 (직사각형)", 0];
            else if (su > flat && sl > flat) [key, name, dir] = ["upch", "상승 채널", 0];
            else if (su < -flat && sl < -flat) [key, name, dir] = ["dnch", "하락 채널", 0];
          } else if (su > flat && sl < -flat) [key, name, dir] = ["broad", "확장형 (메가폰)", 0];
          if (key) {
            // 삼각형·쐐기는 두 선이 만나는 곳(꼭짓점)까지, 나머지는 패턴 길이만큼 기다린다
            const apex = U.b !== D.b ? (D.a - U.a) / (U.b - D.b) : Infinity, wait = conv < 0.75 && apex > e ? Math.min(span, Math.round(apex - e)) : span;
            const r = follow(e, Math.max(len, wait), U.at, D.at), j = r.j ?? last;
            found.push({ key, name, dir, pts, r, brk: dir > 0 ? "up" : dir < 0 ? "down" : null, lines: [[s, U.at(s), j, U.at(j), ""], [s, D.at(s), j, D.at(j), ""]], height: w0, level: (i, d) => d === "up" ? U.at(i) : D.at(i), poly: true });
          }
        }
      }
    }
    // --- 3점: 쌍봉 · 쌍바닥
    if (!found.length && k - 3 >= from) {
      const [p0, a1, b, a2] = [q(3), q(2), q(1), q(0)], T = tol(a2.i), top = a2.h, span = a2.i - a1.i;
      const depth = top ? Math.min(a1.p, a2.p) - b.p : b.p - Math.max(a1.p, a2.p);
      const trendIn = top ? p0.p < b.p : p0.p > b.p;   // 쌍봉은 오르막 끝, 쌍바닥은 내리막 끝에서
      if (span >= len * 2 && span <= 150 && Math.abs(a1.p - a2.p) <= T && depth >= 3 * T && trendIn) {
        const ext = top ? Math.max(a1.p, a2.p) : Math.min(a1.p, a2.p);
        const r = top ? follow(e, span, () => ext + T * 0.5, () => b.p) : follow(e, span, () => b.p, () => ext - T * 0.5);
        found.push({ key: top ? "dt" : "db", name: top ? "쌍봉 (M)" : "쌍바닥 (W)", dir: top ? -1 : 1, pts: [p0, a1, b, a2], r, brk: top ? "down" : "up",
          lines: [[a1.i, b.p, r.j ?? last, b.p, "넥라인"]], height: Math.abs(ext - b.p), level: () => b.p });
      }
    }
    const f = found.find((x) => x.r.st !== "expired");
    if (!f) continue;
    const { st, j } = f.r, broke = st === "up" || st === "down";
    const ok = broke && (!f.brk || st === f.brk);
    const status = st === "forming" ? "형성 중" : ok ? `돌파 ${st === "up" ? "↑" : "↓"}` : `실패 (반대 ${st === "up" ? "↑" : "↓"})`;
    let target = null;
    if (broke) { const lv = f.level(j, st); target = st === "up" ? lv + f.height : lv - f.height; }
    else if (f.brk || f.dir) { const d = f.brk === "up" || f.dir > 0 ? 1 : -1, lv = f.level(last, d > 0 ? "up" : "down"); target = lv + d * f.height; }
    // 직전 패턴이 실패로 끝났고 이번 패턴이 그 점들을 다시 쓰면(예: 실패한 쌍봉 → 상승 삼각형) 직전 것을 버린다
    const k0 = k - (f.pts.length === 2 ? 4 : f.pts.length - 1), prev = out.at(-1);
    if (prev && !prev.ok && prev.st !== "forming" && k0 < prev.k) out.pop();
    out.push({ key: f.key, name: f.name, dir: f.dir, status, st, ok, k, i0: f.pts[0].i, i1: e, j: j ?? last, target, pts: f.pts.map((x) => [x.i, x.p]), lines: f.lines, poly: !!f.poly,
      reached: broke && target != null ? c.slice(j + 1).some((b) => st === "up" ? b.high >= target : b.low <= target) : false });
    if (ok || st === "forming") from = k;   // 겹치지 않게 다음 패턴은 이 패턴의 끝 점부터 (실패한 패턴의 점은 다시 쓸 수 있음)
  }
  return out;
}

Object.assign(INDICATORS, {
  chartpat: { name: "차트 패턴 자동 인식", group: "신호 · 패턴", pane: "main",
    desc: "헤드앤숄더 · 쌍봉/쌍바닥 · 삼중천정/바닥 · 삼각형 · 쐐기 · 깃발 · 채널 · 박스권 · 확장형을 스윙 고점·저점으로 자동으로 찾아 선과 목표가(측정 이동)를 그림. len = 스윙 판정 봉 수(클수록 큰 패턴), tol = 허용 오차(ATR 배수), show = 표시할 최근 패턴 수",
    params: { len: 5, tol: 0.6, show: 6 }, compute: (c, p) => {
      const all = detectPatterns(c, p), shown = all.slice(-Math.max(1, p.show)), s = sig(c.length);
      shown.forEach((x) => { if (x.st === "up" || x.st === "down") s[x.j] = { dir: x.st === "up" ? 1 : -1, text: `${x.name.split(" (")[0]} ${x.ok ? "돌파" : "실패"}`, color: x.ok ? undefined : "rgba(164,172,182,.8)" }; });
      const cur = shown.filter((x) => x.st === "forming" || x.j >= c.length - 30).at(-1);
      return { plots: [{ name: "패턴", type: "patterns", data: Array(c.length).fill(null), patterns: shown }, { name: "돌파", type: "signals", data: s }],
        note: cur ? `${cur.name} ${cur.status}${cur.target ? ` · 목표 ${px0(+cur.target.toPrecision(6))}` : ""}` : all.length ? `최근 패턴 ${all.length}개` : "패턴 없음" };
    } },
});

// 선택 창에 보이는 그룹 순서
export const GROUPS = ["추세", "신호 · 패턴", "스마트머니 (SMC)", "레벨 · 프로파일", "변동성", "오실레이터", "통계 · 퀀트", "거래량", "파생 · 코인글라스"];

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

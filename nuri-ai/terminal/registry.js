// 누리 차트 터미널 — 지표 목록 하나로 합치기
//  q:<type>  quant.js IND_REGISTRY (전략 엔진·백테스트와 같은 공식, 29종)
//  x:<key>   ind.js 확장 지표 (차트 전용: 신호·패턴·SMC·볼륨 프로파일 등, quant 와 겹치거나 서버 데이터가 필요한 것은 뺌)
//  c:expr    커스텀 지표 (../customind.js 의 evalExpr 가 있을 때만)
// compute(c, params, ctx) → {plots: [{name, type: line|hist|dots|signals|boxes|profiles|patterns|fill, data, color, colors}], levels, note}
import { IND_REGISTRY, computeInd } from "../quant.js";
import { INDICATORS as X, GROUPS as XG } from "./ind.js";
import { toQuant } from "./data.js";

export const PALETTE = ["#2962ff", "#ff9800", "#e91e63", "#00bcd4", "#9c27b0", "#4caf50", "#ffeb3b", "#f23645", "#089981", "#e0e3eb"];
const K = { blue: "#2962ff", orange: "#ff9800", green: "#089981", red: "#f23645", purple: "#9c27b0", teal: "#00bcd4", gray: "#787b86", pink: "#e91e63", maroon: "#b71c1c" };
const UP = "#089981", DN = "#f23645";

// quant.js 지표 → 화면 설정 (pane: main=가격 위 · sub=아래 창)
const Q = {
  sma: { name: "SMA 단순이동평균", group: "이동평균", pane: "main" },
  ema: { name: "EMA 지수이동평균", group: "이동평균", pane: "main" },
  wma: { name: "WMA 가중이동평균", group: "이동평균", pane: "main" },
  hma: { name: "HMA 헐 이동평균", group: "이동평균", pane: "main" },
  vwma: { name: "VWMA 거래량 가중 이평", group: "이동평균", pane: "main" },
  vwap: { name: "VWAP (일간, UTC 리셋)", group: "이동평균", pane: "main" },
  bb: { name: "볼린저 밴드", group: "채널 · 밴드", pane: "main", out: { upper: K.blue, middle: K.orange, lower: K.blue }, fill: ["upper", "lower", "rgba(41,98,255,.07)"] },
  keltner: { name: "켈트너 채널", group: "채널 · 밴드", pane: "main", out: { upper: K.teal, middle: K.gray, lower: K.teal }, fill: ["upper", "lower", "rgba(0,188,212,.06)"] },
  donchian: { name: "돈치안 채널", group: "채널 · 밴드", pane: "main", out: { upper: K.green, middle: K.gray, lower: K.red }, fill: ["upper", "lower", "rgba(120,123,134,.06)"] },
  highest: { name: "N봉 최고값", group: "채널 · 밴드", pane: "main" },
  lowest: { name: "N봉 최저값", group: "채널 · 밴드", pane: "main" },
  ichimoku: { name: "일목균형표", group: "추세", pane: "main", out: { tenkan: K.blue, kijun: K.maroon, span_a: "rgba(8,153,129,.75)", span_b: "rgba(242,54,69,.75)" }, cloud: ["span_a", "span_b"] },
  supertrend: { name: "슈퍼트렌드", group: "추세", pane: "main", trend: true },
  atr_stop: { name: "ATR 추적 손절 (UT Bot)", group: "추세", pane: "main", trend: true },
  psar: { name: "파라볼릭 SAR", group: "추세", pane: "main", dots: true },
  rsi: { name: "RSI", group: "오실레이터", pane: "sub", levels: [30, 50, 70] },
  macd: { name: "MACD", group: "오실레이터", pane: "sub", out: { line: K.blue, signal: K.orange }, hist: "hist", levels: [0] },
  stoch: { name: "스토캐스틱", group: "오실레이터", pane: "sub", out: { k: K.blue, d: K.orange }, levels: [20, 80] },
  stochrsi: { name: "스토캐스틱 RSI", group: "오실레이터", pane: "sub", out: { k: K.blue, d: K.orange }, levels: [20, 80] },
  adx: { name: "ADX / DMI", group: "오실레이터", pane: "sub", out: { adx: K.orange, plus_di: UP, minus_di: DN }, levels: [25] },
  cci: { name: "CCI", group: "오실레이터", pane: "sub", levels: [-100, 0, 100] },
  mfi: { name: "MFI 자금 흐름", group: "오실레이터", pane: "sub", levels: [20, 80] },
  willr: { name: "윌리엄스 %R", group: "오실레이터", pane: "sub", levels: [-80, -20] },
  roc: { name: "ROC 변화율 %", group: "오실레이터", pane: "sub", levels: [0] },
  aroon: { name: "아룬", group: "오실레이터", pane: "sub", out: { up: K.orange, down: K.blue } },
  atr: { name: "ATR", group: "거래량 · 변동성", pane: "sub" },
  obv: { name: "OBV", group: "거래량 · 변동성", pane: "sub" },
  cmf: { name: "CMF 차이킨 자금 흐름", group: "거래량 · 변동성", pane: "sub", levels: [0] },
  volume_sma: { name: "거래량 + 이동평균", group: "거래량 · 변동성", pane: "sub", vol: true },
};
export const Q_GROUPS = ["이동평균", "채널 · 밴드", "추세", "오실레이터", "거래량 · 변동성"];

const qcCache = new WeakMap();
const qc = (c) => { let v = qcCache.get(c); if (!v) { v = toQuant(c); qcCache.set(c, v); } return v; };
const signColors = (x) => x.map((v, i) => v == null ? null : v >= 0 ? (v >= (x[i - 1] ?? -Infinity) ? "rgba(8,153,129,.9)" : "rgba(8,153,129,.45)") : (v <= (x[i - 1] ?? Infinity) ? "rgba(242,54,69,.9)" : "rgba(242,54,69,.45)"));

function qCompute(type, meta) {
  return (c, p, ctx = {}) => {
    const r = computeInd(qc(c), type, p), plots = [], color = ctx.color || K.blue;
    if (meta.trend) {
      const line = r.line, tr = r.trend;
      plots.push({ name: "상승", type: "line", data: line.map((v, i) => tr[i] === 1 ? v : null), color: UP, lineWidth: 2 });
      plots.push({ name: "하락", type: "line", data: line.map((v, i) => tr[i] === -1 ? v : null), color: DN, lineWidth: 2 });
      plots.push({ name: "신호", type: "signals", data: tr.map((v, i) => i && tr[i - 1] != null && v != null && v !== tr[i - 1] ? { dir: v, text: v > 0 ? "매수" : "매도", size: 0.7 } : null) });
    } else if (meta.dots) {
      plots.push({ name: "SAR", type: "dots", data: r.value, colors: r.trend.map((t) => t === 1 ? UP : t === -1 ? DN : null), color });
    } else if (meta.vol) {
      plots.push({ name: "거래량", type: "hist", data: c.map((b) => b.volume), colors: c.map((b) => b.close >= b.open ? "rgba(8,153,129,.5)" : "rgba(242,54,69,.5)") });
      plots.push({ name: `MA ${p.length}`, type: "line", data: r.value, color: ctx.color || K.orange, lineWidth: 1 });
    } else if (meta.out) {
      for (const [k, col] of Object.entries(meta.out)) if (r[k]) plots.push({ name: k, type: "line", data: r[k], color: col, lineWidth: k === "middle" ? 1 : 1.5 });
      if (meta.hist && r[meta.hist]) plots.push({ name: meta.hist, type: "hist", data: r[meta.hist], colors: signColors(r[meta.hist]) });
      if (meta.fill) plots.push({ name: "fill", type: "fill", a: r[meta.fill[0]], b: r[meta.fill[1]], color: meta.fill[2], data: [] });
      if (meta.cloud) plots.push({ name: "구름", type: "fill", a: r[meta.cloud[0]], b: r[meta.cloud[1]], up: "rgba(8,153,129,.13)", dn: "rgba(242,54,69,.13)", data: [] });
    } else {
      const k = Object.keys(r)[0];
      plots.push({ name: type.toUpperCase(), type: "line", data: r.value ?? r[k], color, lineWidth: 2 });
    }
    return { plots, levels: meta.levels };
  };
}

export const DEFS = {};
for (const [type, R] of Object.entries(IND_REGISTRY)) {
  if (type === "custom") continue;                       // 수식 지표는 아래 c:expr 로
  const meta = Q[type] || { name: R.desc || type, group: "오실레이터", pane: "sub" };
  DEFS["q:" + type] = { src: "q", type, name: meta.name, group: meta.group, pane: meta.pane, params: { ...R.defaults }, desc: R.desc, single: !meta.out && !meta.trend && !meta.vol, compute: qCompute(type, meta) };
}
// ind.js: quant 와 겹치는 키 · 서버 데이터(remote) 필요한 지표는 뺀다
for (const [k, d] of Object.entries(X)) {
  if (d.remote || IND_REGISTRY[k]) continue;
  DEFS["x:" + k] = { src: "x", type: k, name: d.name, group: d.group, pane: d.pane, params: { ...d.params }, desc: d.desc || "", profile: !!d.profile, compute: (c, p, ctx = {}) => d.compute(c, p, ctx.ext || {}) };
}
export const X_GROUPS = XG.filter((g) => Object.values(DEFS).some((d) => d.src === "x" && d.group === g));

// ------------------------------------------------------------ 커스텀 지표 (../customind.js)
let CUST;   // undefined = 아직 안 봄 · null = 없음 · 모듈
export async function loadCustom() {
  if (CUST !== undefined) return CUST;
  try {
    const url = new URL("../customind.js", import.meta.url).href;
    const head = await fetch(url, { method: "GET", cache: "no-cache" }).catch(() => null);
    if (!head || !head.ok || !/javascript|ecmascript|text\/plain/.test(head.headers.get("content-type") || "javascript")) { CUST = null; return CUST; }
    const m = await import(url);
    CUST = typeof m.evalExpr === "function" ? m : null;
  } catch (e) { CUST = null; }
  return CUST;
}
export const customReady = () => !!CUST;
// evalExpr 결과를 선 목록으로 (배열 · {value|values|series} · {이름: 배열} · {plots} 모두 받음)
function toPlots(res, n, color) {
  const arr = (a) => Array.isArray(a) && a.length ? (a.length === n ? a : [...Array(Math.max(0, n - a.length)).fill(null), ...a.slice(-n)]).map((v) => v == null || !Number.isFinite(+v) ? null : +v) : null;
  if (res == null) return { plots: [], note: "결과 없음" };
  if (res.error) return { plots: [], note: String(res.error) };
  if (Array.isArray(res) && (typeof res[0] !== "object" || res[0] === null)) return { plots: [{ name: "값", type: "line", data: arr(res), color, lineWidth: 2 }] };
  if (Array.isArray(res.plots)) return { plots: res.plots.map((p, i) => ({ type: "line", color: PALETTE[i % PALETTE.length], ...p, data: arr(p.data || p.values) || [] })), levels: res.levels, note: res.note };
  const one = arr(res.values ?? res.value ?? res.series ?? res.data);
  if (one) return { plots: [{ name: res.name || "값", type: "line", data: one, color, lineWidth: 2 }], levels: res.levels, note: res.note };
  const plots = Object.entries(res).map(([k, v], i) => arr(v) && { name: k, type: "line", data: arr(v), color: i ? PALETTE[(i + 1) % PALETTE.length] : color, lineWidth: 1.5 }).filter(Boolean);
  return plots.length ? { plots } : { plots: [], note: "결과 형식을 알 수 없습니다" };
}
const custCache = new Map();
DEFS["c:expr"] = {
  src: "c", type: "expr", name: "커스텀 지표", group: "커스텀", pane: "sub", params: { expr: "", overlay: 0 }, desc: "수식을 직접 입력 (customind.js)",
  compute: (c, p, ctx = {}) => {
    if (!CUST) return { plots: [], note: CUST === null ? "customind.js 없음 — 커스텀 지표를 쓸 수 없습니다" : "불러오는 중…" };
    const key = `${p.expr}|${c.length}|${c.at(-1)?.time}|${c.at(-1)?.close}`, hit = custCache.get(ctx.id);
    if (hit && hit.key === key && hit.res) return hit.res;
    let out;
    try { out = CUST.evalExpr(String(p.expr || ""), qc(c), {}, { computeInd }); } catch (e) { return { plots: [], note: "수식 오류: " + (e.message || e) }; }
    if (out && typeof out.then === "function") {
      custCache.set(ctx.id, { key, res: hit?.res || { plots: [], note: "계산 중…" } });
      out.then((r) => { custCache.set(ctx.id, { key, res: toPlots(r, c.length, ctx.color) }); ctx.onAsync?.(); },
        (e) => { custCache.set(ctx.id, { key, res: { plots: [], note: "수식 오류: " + (e.message || e) } }); ctx.onAsync?.(); });
      return custCache.get(ctx.id).res;
    }
    const res = toPlots(out, c.length, ctx.color);
    custCache.set(ctx.id, { key, res });
    return res;
  },
};

// 지표 인스턴스의 실제 창 (커스텀은 overlay 파라미터로)
export const paneOf = (spec) => { const d = DEFS[spec.key]; if (!d) return "sub"; if (d.src === "c") return +spec.params?.overlay ? "main" : "sub"; return d.pane; };
export const labelOf = (spec) => {
  const d = DEFS[spec.key];
  if (!d) return spec.key;
  if (d.src === "c") return spec.params?.name || (spec.params?.expr ? "ƒ " + String(spec.params.expr).slice(0, 28) : "커스텀");
  return d.name;
};

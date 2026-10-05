// 📖 차트 읽기 — "내 차트를 읽고 알려줘"를 코드가 정확한 숫자로 답한다 (화면 없이도 동작: 터미널 패널 · 뉴트론 MCP · 에이전트 팀이 같이 씀)
// 사용자 제공 프롬프트 묶음(TradingView MCP 용 3-1 차트 읽기 · 3-2 구조화 JSON 리포트 · 3-3 멀티 심볼 비교)을 우리 차트 터미널에 맞게 구현.
//   chart_get_state → readChart() · data_get_study_values → indicators[].values · data_get_pine_lines → levels(내가 그린 선 + AI 팀 선) · capture_screenshot → 터미널 스크린샷
// 값은 모두 봉 데이터에서 계산한다(이미지 판독 아님) → 숫자를 지어낼 수 없다. AI 는 이 결과를 받아 해설만 한다.
import { DEFS, labelOf, paneOf } from "./registry.js";
import * as D from "./data.js";

const TERM_KEY = "nuri:term:state";
const num = v => (v != null && Number.isFinite(+v)) ? +v : null;
const sig = (v, d = 6) => v == null ? null : +(+v).toPrecision(d);
const ls = k => { try { return JSON.parse(localStorage.getItem(k) || "null"); } catch (e) { return null; } };
export function termCell() { const s = ls(TERM_KEY) || {}, c = (s.cells || [])[0] || {}; return { exchange: c.exchange || "binancef", symbol: c.symbol || "BTCUSDT", interval: c.interval || "1h", inds: Array.isArray(s.inds) ? s.inds.filter(x => x && DEFS[x.key]) : [], ctype: s.ctype || "candles" }; }

// ── 기본 계산 ──
function rsi(c, n = 14) { let g = 0, l = 0, out = null; for (let i = 1; i < c.length; i++) { const d = c[i].close - c[i - 1].close, u = Math.max(d, 0), dn = Math.max(-d, 0); if (i <= n) { g += u / n; l += dn / n; } else { g = (g * (n - 1) + u) / n; l = (l * (n - 1) + dn) / n; } if (i >= n) out = l ? 100 - 100 / (1 + g / l) : 100; } return out; }
function atrSeries(c, n = 14) { const o = new Array(c.length).fill(null); let a = 0; for (let i = 1; i < c.length; i++) { const tr = Math.max(c[i].high - c[i].low, Math.abs(c[i].high - c[i - 1].close), Math.abs(c[i].low - c[i - 1].close)); a = i <= n ? a + tr / n : (a * (n - 1) + tr) / n; if (i >= n) o[i] = a; } return o; }
function adx(c, n = 14) { let trS = 0, pS = 0, mS = 0, dxS = 0, out = null, k = 0; for (let i = 1; i < c.length; i++) { const up = c[i].high - c[i - 1].high, dn = c[i - 1].low - c[i].low, tr = Math.max(c[i].high - c[i].low, Math.abs(c[i].high - c[i - 1].close), Math.abs(c[i].low - c[i - 1].close)), p = up > dn && up > 0 ? up : 0, m = dn > up && dn > 0 ? dn : 0;
  if (i <= n) { trS += tr; pS += p; mS += m; } else { trS = trS - trS / n + tr; pS = pS - pS / n + p; mS = mS - mS / n + m; }
  if (i >= n) { const pdi = trS ? 100 * pS / trS : 0, mdi = trS ? 100 * mS / trS : 0, dx = pdi + mdi ? 100 * Math.abs(pdi - mdi) / (pdi + mdi) : 0; k++; if (k <= n) { dxS += dx / n; if (k === n) out = dxS; } else out = (out * (n - 1) + dx) / n; } } return out; }
// 시장 레짐(3-4 운영 규칙 1): HIGH_VOL = ATR% 가 최근 200봉 중 상위 15% · TREND = ADX 25↑ · 그 외 RANGE
export function regimeOf(c) {
  const a = atrSeries(c), n = c.length, cur = a[n - 1] && c[n - 1].close ? a[n - 1] / c[n - 1].close * 100 : null, hist = [];
  for (let i = Math.max(15, n - 200); i < n; i++) if (a[i]) hist.push(a[i] / c[i].close * 100);
  const pct = cur != null && hist.length ? hist.filter(x => x <= cur).length / hist.length : null, ad = adx(c);
  const key = pct != null && pct >= 0.85 ? "HIGH_VOL" : ad != null && ad >= 25 ? "TREND" : "RANGE";
  return { key, ko: { HIGH_VOL: "고변동성", TREND: "추세", RANGE: "횡보" }[key], adx: ad == null ? null : +ad.toFixed(1), atrPct: cur == null ? null : +cur.toFixed(2), atrRank: pct == null ? null : Math.round(pct * 100), atr: a[n - 1] || null };
}
// 최근 가격 흐름 한 줄(코드가 만든 사실 요약)
export function priceAction(c) {
  const n = c.length; if (n < 25) return "봉이 부족합니다";
  const last = c[n - 1], w = c.slice(-20), hi = Math.max(...w.map(b => b.high)), lo = Math.min(...w.map(b => b.low)), chg = (last.close / c[n - 21].close - 1) * 100, pos = hi > lo ? (last.close - lo) / (hi - lo) * 100 : 50;
  let run = 0; for (let i = n - 1; i > 0; i--) { const d = Math.sign(c[i].close - c[i - 1].close); if (!run) run = d; else if (Math.sign(run) === d) run += d; else break; }
  const vAvg = w.reduce((s, b) => s + (b.volume || 0), 0) / 20, v5 = c.slice(-5).reduce((s, b) => s + (b.volume || 0), 0) / 5, a = atrSeries(c)[n - 1] || 1, body = Math.abs(last.close - last.open) / a;
  const hh = last.high >= hi * 0.9995, ll = last.low <= lo * 1.0005;
  return `최근 20봉 ${chg >= 0 ? "+" : ""}${chg.toFixed(2)}% · 20봉 범위(고가 ${sig(hi, 7)} · 저가 ${sig(lo, 7)})의 ${pos.toFixed(0)}% 위치${hh ? "(고점 갱신 중)" : ll ? "(저점 갱신 중)" : ""} · ${Math.abs(run)}봉 연속 ${run > 0 ? "상승" : run < 0 ? "하락" : "보합"} 마감 · 거래량 최근 5봉이 20봉 평균의 ${(vAvg ? v5 / vAvg : 1).toFixed(2)}배 · 마지막 봉 ${last.close >= last.open ? "양봉" : "음봉"}(몸통 ${body.toFixed(1)} ATR)`;
}
// ── 지표 실시간 값 ──
function indValues(c, specs, extra) {
  const out = [], i = c.length - 1;
  for (const s of specs) {
    const d = DEFS[s.key]; if (!d) continue; let res;
    try { res = d.compute(c, { ...d.params, ...(s.params || {}) }, { color: s.color, id: s.id, ext: {}, extra, onAsync: () => {} }); } catch (e) { out.push({ name: labelOf(s), key: s.key, params: s.params || {}, pane: paneOf(s), error: String(e.message || e).slice(0, 60) }); continue; }
    if (!res || typeof res.then === "function") { out.push({ name: labelOf(s), key: s.key, params: s.params || {}, pane: paneOf(s), note: "불러오는 중(서버 데이터)" }); continue; }
    const values = {}, signals = [];
    for (const pl of res.plots || []) {
      if (!Array.isArray(pl.data)) continue;
      if (pl.type === "signals") { for (let j = Math.min(i, pl.data.length - 1); j >= Math.max(0, i - 12); j--) { const g = pl.data[j]; if (g && (g.dir || g.text)) { signals.push({ bars_ago: i - j, dir: g.dir > 0 ? "up" : g.dir < 0 ? "down" : "", text: g.text || "", ...(g.stat ? { stat: g.stat } : {}) }); break; } } continue; }
      if (!["line", "hist", "dots", "area"].includes(pl.type || "line")) continue;
      let v = null; for (let j = Math.min(i, pl.data.length - 1); j >= Math.max(0, i - 3) && v == null; j--) { const x = pl.data[j]; v = num(typeof x === "object" && x ? (x.value ?? x.v) : x); }
      if (v != null) values[pl.name || "value"] = sig(v);
    }
    out.push({ name: labelOf(s), key: s.key, params: s.params || {}, pane: paneOf(s), values, ...(signals.length ? { signal: signals[0] } : {}) });
  }
  return out;
}
// ── 레벨: 내가 그린 선(수평선·레이·추세선의 지금 값·피보나치·롱/숏 포지션 도구) + AI 팀이 차트에 올린 선 ──
const FIB = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];
function levelsOf(exchange, symbol, nowSec, price) {
  const out = [], items = ls(`nuri:term:draw:${exchange}:${symbol}`) || [];
  const lineP = (a, b, t) => b.t === a.t ? a.p : a.p + (b.p - a.p) * (t - a.t) / (b.t - a.t);
  for (const d of Array.isArray(items) ? items : []) { if (!d || d.hidden || !Array.isArray(d.pts) || !d.pts.length) continue; const p = d.pts, tag = d.text ? ` "${String(d.text).slice(0, 20)}"` : "";
    if (d.type === "hline" || d.type === "hray") out.push({ price: p[0].p, label: (d.type === "hline" ? "수평선" : "수평 레이") + tag, src: "내 그림" });
    else if ((d.type === "trend" || d.type === "ray" || d.type === "extended") && p[1]) { const within = d.type !== "trend" || (nowSec >= Math.min(p[0].t, p[1].t) && nowSec <= Math.max(p[0].t, p[1].t)); if (within) out.push({ price: lineP(p[0], p[1], nowSec), label: "추세선(지금 위치)" + tag, src: "내 그림" }); }
    else if (d.type === "fib" && p[1]) for (const r of FIB) out.push({ price: p[1].p + (p[0].p - p[1].p) * r, label: `피보나치 ${r}`, src: "내 그림" });
    else if ((d.type === "long" || d.type === "short") && p[2]) { out.push({ price: p[0].p, label: `${d.type === "long" ? "롱" : "숏"} 포지션 진입`, src: "내 그림" }, { price: p[1].p, label: "손절", src: "내 그림" }, { price: p[2].p, label: "익절", src: "내 그림" }); }
    else if (d.type === "rect" && p[1]) out.push({ price: Math.max(p[0].p, p[1].p), label: "사각형 상단" + tag, src: "내 그림" }, { price: Math.min(p[0].p, p[1].p), label: "사각형 하단" + tag, src: "내 그림" });
  }
  const sym = String(symbol).toUpperCase().replace(/^KRW-(\w+)$/, "$1USDT"), A = ls("ghAnalysis:" + sym) || {};
  for (const [sec, v] of Object.entries(A)) { if (!v || Date.now() - (v.t || 0) > 6 * 3600e3) continue; for (const l of v.lines || []) if (num(l.price) != null) out.push({ price: +l.price, label: String(l.label || sec).slice(0, 40), src: "AI 팀·" + (v.title ? String(v.title).slice(0, 18) : sec) }); }
  const seen = new Set();
  return out.filter(l => num(l.price) != null && l.price > 0).map(l => ({ ...l, price: sig(l.price, 7), dist_pct: price ? +((l.price / price - 1) * 100).toFixed(2) : null }))
    .filter(l => { const k = l.price + "|" + l.label; if (seen.has(k)) return false; seen.add(k); return true; }).sort((a, b) => b.price - a.price);
}
/** 내 차트 읽기(3-1). opts: {exchange, symbol, interval, candles(터미널 형식), inds, ctype} — 안 주면 터미널에 저장된 화면 그대로 */
export async function readChart(opts = {}) {
  const cell = termCell(), exchange = opts.exchange || cell.exchange, symbol = opts.symbol || cell.symbol, interval = opts.interval || cell.interval, specs = opts.inds || cell.inds;
  let c = opts.candles; if (!c?.length) c = (await D.loadCandles({ exchange, symbol, interval })).candles;
  const n = c.length, last = c[n - 1], ref = c[Math.max(0, n - 101)], prev = c[n - 2] || last;
  const R = { symbol, exchange, exchange_ko: D.EX_SHORT[exchange] || exchange, timeframe: interval, timeframe_ko: D.IV_LABEL[interval] || interval, chart_type: opts.ctype || cell.ctype, bars: n, bar_time: new Date(last.time * 1000).toISOString(),
    last_price: sig(last.close, 8), change_pct_bar: +((last.close / prev.close - 1) * 100).toFixed(2), change_pct_100_bars: +((last.close / ref.close - 1) * 100).toFixed(2),
    ohlc: { open: last.open, high: last.high, low: last.low, close: last.close, volume: last.volume }, rsi14: (() => { const r = rsi(c); return r == null ? null : +r.toFixed(1); })(), regime: regimeOf(c),
    active_indicators: indValues(c, specs, { symbol, exchange, interval }), key_levels: levelsOf(exchange, symbol, last.time, last.close), price_action: priceAction(c), t: Date.now() };
  const dirs = { up: 0, down: 0 }; for (const it of R.active_indicators) if (it.signal?.dir) dirs[it.signal.dir]++;
  return R;
}
/** 구조화 JSON 리포트(3-2) — 저널·티켓·파이프라인에 그대로 붙일 수 있는 고정 키 */
export function reportJSON(R, screenshot_path = null) {
  return { symbol: R.symbol, timeframe: R.timeframe, chart_type: R.chart_type, last_price: R.last_price, change_pct_100_bars: R.change_pct_100_bars,
    key_levels_from_pine: R.key_levels.map(l => ({ price: l.price, label: l.label, source: l.src })),
    active_indicators: R.active_indicators.map(i => ({ name: i.name, params: i.params, values: i.values || {}, ...(i.signal ? { signal: i.signal } : {}) })),
    regime: R.regime.key, rsi_14: R.rsi14, price_action: R.price_action, screenshot_path, generated_at: new Date(R.t).toISOString(), source: "GH Coin 차트 터미널(봉 데이터에서 계산)" };
}
/** 사람이 읽는 차트 읽기 글(3-1 의 네 항목 순서 그대로) */
export function readText(R) {
  const f = v => v == null ? "—" : (Math.abs(v) >= 1000 ? (+v).toLocaleString("en-US", { maximumFractionDigits: 2 }) : String(v));
  const inds = R.active_indicators.length ? R.active_indicators.map(i => `- ${i.name}: ${i.error ? "계산 오류" : i.note || (Object.entries(i.values || {}).map(([k, v]) => `${k} ${f(v)}`).join(" · ") || "값 없음")}${i.signal ? ` · 신호 ${i.signal.text || ""}${i.signal.dir === "up" ? "▲" : i.signal.dir === "down" ? "▼" : ""}(${i.signal.bars_ago}봉 전${i.signal.stat ? ` · 과거 적중 ${i.signal.stat.hit}% vs 기준 ${i.signal.stat.base}% = ${i.signal.stat.grade}` : ""})` : ""}`).join("\n") : "- (차트에 띄운 지표 없음)";
  const lv = R.key_levels.length ? R.key_levels.map(l => `- ${f(l.price)} (${l.dist_pct >= 0 ? "+" : ""}${l.dist_pct}%) ${l.label} · ${l.src}`).join("\n") : "- (그린 선·AI 팀 선 없음)";
  return `1. 현재 가격·타임프레임: ${R.symbol} ${f(R.last_price)} · ${R.timeframe_ko}봉 · ${R.exchange_ko} (직전 봉 대비 ${R.change_pct_bar >= 0 ? "+" : ""}${R.change_pct_bar}% · 100봉 대비 ${R.change_pct_100_bars >= 0 ? "+" : ""}${R.change_pct_100_bars}%)\n2. 표시된 지표와 실시간 값:\n${inds}\n3. 차트의 선·라벨 레벨(높은 순):\n${lv}\n4. 최근 가격 흐름: ${R.price_action} · 레짐 ${R.regime.ko}(ADX ${R.regime.adx ?? "—"} · ATR ${R.regime.atrPct ?? "—"}%)`;
}
/** 멀티 심볼 비교(3-3): 심볼마다 마지막 가격 · 100봉 변화율 · RSI(14) · 거래량 확인 */
export async function compare(symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"], interval = "1h", exchange = "binancef") {
  const rows = await Promise.all(symbols.map(async symbol => { try {
    const c = (await D.loadCandles({ exchange, symbol, interval })).candles, n = c.length, last = c[n - 1], ref = c[Math.max(0, n - 101)];
    const v20 = c.slice(-21, -1).reduce((s, b) => s + (b.volume || 0), 0) / 20, v5 = c.slice(-6, -1).reduce((s, b) => s + (b.volume || 0), 0) / 5, vr = v20 ? v5 / v20 : null, chg = (last.close / ref.close - 1) * 100, r = rsi(c), rg = regimeOf(c);
    return { symbol, last_price: sig(last.close, 8), change_pct_100_bars: +chg.toFixed(2), rsi14: r == null ? null : +r.toFixed(1), volume_ratio: vr == null ? null : +vr.toFixed(2), volume_confirmed: vr != null && vr >= 1.1, regime: rg.key, regime_ko: rg.ko, adx: rg.adx };
  } catch (e) { return { symbol, error: String(e.message || e).slice(0, 60) }; } }));
  const ok = rows.filter(r => !r.error), strongest = [...ok].sort((a, b) => b.change_pct_100_bars - a.change_pct_100_bars)[0];
  return { interval, exchange, rows, strongest: strongest?.symbol || null, note: "거래량 확인 = 최근 5봉(마감) 평균이 20봉 평균의 1.1배 이상", t: Date.now() };
}

// 🔬 내 지표 연구소 — 차트 터미널에 띄운 보조지표로 ① 노이즈 적은 값 찾기 ② 매매법 만들기 ③ 검증 ④ 데모 투입 ⑤ 지금 포지션 알려주기
// 원칙: 앞 70% 로 고르고 뒤 30%(처음 보는 구간) + 다른 코인으로 확인. 처음 보는 구간에서 나아지지 않으면 원래 값을 그대로 둔다(과최적화 방지).
// 노이즈 = 방향이 바뀐 뒤 3봉 안에 다시 뒤집히는 '가짜 신호' 비율(휩쏘) · 품질 = 방향 전환 뒤 12봉 동안 그 방향으로 간 거리(ATR 단위).
import { candlesFor } from "../nuri-ai/agent.js";
import * as RD from "../nuri-ai/terminal/readings.js";
import { DEFS, labelOf } from "../nuri-ai/terminal/registry.js";
import * as ENG from "./strategies.js";

export const COINS6 = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "BNBUSDT"];
// 터미널 봉 간격 → 엔진 시간봉 (뉴럴 데스크가 지원하는 5·15·60·240)
export const engTf = iv => ({ "1m": "5", "3m": "5", "5m": "5", "6m": "5", "8m": "5", "10m": "15", "15m": "15", "30m": "15", "1h": "60", "2h": "60", "4h": "240", "1d": "240", "1w": "240" })[String(iv)] || (["5", "15", "60", "240"].includes(String(iv)) ? String(iv) : "60");
const TFKO = { "5": "5분", "15": "15분", "60": "1시간", "240": "4시간" };
const Q_ = () => import("../nuri-ai/quant.js");
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));

async function load(sym, tf, n = 1500) { const r = await candlesFor({ market: sym, exchange: "binancef", timeframe: tf }, n); if (!(r?.cs?.length > 400)) throw new Error(`${sym} ${TFKO[tf]} 캔들 부족`); return r.cs; }
async function atrOf(cs) { const Q = await Q_(); return Q.computeInd(cs, "atr", { length: 14 }).value; }

// ── ① 노이즈 측정 ──
export function noiseStats(series, cs, atr, from, to, H = 12) {
  let flips = 0, whip = 0, qs = 0, hit = 0, nq = 0, prev = 0, bars = 0;
  for (let i = Math.max(1, from); i < Math.min(to, cs.length - 1); i++) {
    bars++; const d = series[i]; if (!d) continue;
    if (prev && d !== prev) {
      flips++;
      let back = false; for (let j = i + 1; j <= Math.min(i + 3, cs.length - 1); j++) if (series[j] === prev) { back = true; break; }   // 3봉 안에 되돌림 = 가짜 신호
      if (back) whip++;
      if (i + H < cs.length && atr[i]) { const m = clamp((cs[i + H].c - cs[i].c) * d / atr[i], -4, 4); qs += m; nq++; if (m > 0) hit++; }
    }
    prev = d;
  }
  return { flips, per100: +(flips / Math.max(1, bars) * 100).toFixed(1), whip: flips ? +(whip / flips * 100).toFixed(1) : 0, q: nq ? +(qs / nq).toFixed(3) : 0, hit: nq ? +(hit / nq * 100).toFixed(1) : 0, n: nq };
}
const J = s => s.q - 0.004 * s.whip;   // 목적: 전환 뒤 그 방향 이동 − 가짜 신호 벌점

function candidates(spec) {
  const d = DEFS[spec.key]; if (!d) return [];
  const p0 = { ...d.params, ...(spec.params || {}) };
  const keys = Object.keys(p0).filter(k => typeof p0[k] === "number" && p0[k] > 0 && !["overlay"].includes(k)).slice(0, 2);
  if (!keys.length) return [p0];
  const mul = [0.5, 0.75, 1, 1.33, 1.75, 2.5], vals = k => [...new Set(mul.map(m => { const v = p0[k] * m; return Number.isInteger(p0[k]) ? Math.max(2, Math.round(v)) : +v.toFixed(2); }))];
  let out = [{}]; for (const k of keys) out = out.flatMap(o => vals(k).map(v => ({ ...o, [k]: v })));
  return out.slice(0, 36).map(o => ({ ...p0, ...o }));
}
export async function tune(specs, cs, onStep = () => {}) {
  const T = RD.toTerm(cs), atr = await atrOf(cs), cut = Math.floor(cs.length * 0.7), rows = [], tuned = [];
  for (const s of specs) {
    const d = DEFS[s.key]; if (!d) continue;
    const base = RD.readings(T, [s]).items[0]; if (!base) { tuned.push(s); continue; }   // 방향이 없는 지표(거래량 등)는 그대로
    onStep(`🔧 ${labelOf(s)} 값 시험 중`);
    const p0 = { ...d.params, ...(s.params || {}) }, o = { tr: noiseStats(base.series, cs, atr, 210, cut), te: noiseStats(base.series, cs, atr, cut, cs.length) };
    let best = { p: p0, tr: o.tr, te: o.te };
    for (const p of candidates(s)) {
      const it = RD.readings(T, [{ ...s, params: p }]).items[0]; if (!it) continue;
      const tr = noiseStats(it.series, cs, atr, 210, cut); if (tr.n < 8) continue;
      if (J(tr) > J(best.tr) + 1e-9) best = { p, tr, te: noiseStats(it.series, cs, atr, cut, cs.length) };
    }
    const better = best.p !== p0 && J(best.te) > J(o.te);   // 처음 보는 구간에서도 나아야 채택
    const fin = better ? best : { p: p0, tr: o.tr, te: o.te };
    const changed = Object.keys(p0).filter(k => fin.p[k] !== p0[k]).map(k => `${k} ${p0[k]}→${fin.p[k]}`).join(", ");
    const imp = []; if (fin.te.whip < o.te.whip) imp.push(`가짜 신호 ${o.te.whip}%→${fin.te.whip}%`); if (fin.te.hit > o.te.hit) imp.push(`방향 적중 ${o.te.hit}%→${fin.te.hit}%`); if (fin.te.q > o.te.q) imp.push(`전환 뒤 이동 ${o.te.q}→${fin.te.q}ATR`);
    const pv = d.params?.length != null ? ` ${p0.length}` : "";
    rows.push({ name: labelOf(s) + pv, changed: better ? changed : "", kept: !better, before: o.te, after: fin.te, beforeTr: o.tr, afterTr: fin.tr, reason: better ? `처음 보는 구간에서 개선: ${imp.join(" · ")}` : best.p !== p0 ? "학습 구간에선 나았지만 처음 보는 구간에서 나빠짐 → 원래 값 유지" : "원래 값이 가장 좋음" });
    tuned.push({ ...s, params: { ...(s.params || {}), ...fin.p } });
  }
  return { rows, tuned };
}

// ── ② 매매법: N개 지표 중 K개가 '막' 같은 방향이 되는 순간 진입 (이미 다 같은 방향일 때 추격 X) ──
const lowest = (a, f, t) => { let m = Infinity; for (let j = Math.max(0, f); j <= t; j++) if (a[j] < m) m = a[j]; return m; };
const highest = (a, f, t) => { let m = -Infinity; for (let j = Math.max(0, f); j <= t; j++) if (a[j] > m) m = a[j]; return m; };
export function chartRule(g) {
  const tf = g.tf, key = "chart_" + g.id;
  return { key, name: `📈 내 지표 합의 ${g.k}/${g.specs.length}${g.label ? " · " + g.label : ""}`, cat: "추세", mode: "trend", tf, rr: g.rr, hold: tf === "5" ? 96 : tf === "15" ? 64 : tf === "240" ? 30 : 48, gene: g,
    _ck: "", _v: null,
    prep(cs) { const k = cs.length + "|" + cs.at(-1)?.t; if (this._ck === k) return; this._ck = k;
      try { const R = RD.readings(RD.toTerm(cs), g.specs); const n = cs.length; this._v = new Int16Array(n); for (const it of R.items) for (let i = 0; i < n; i++) this._v[i] += it.series[i]; this._m = R.items.length; } catch (e) { this._v = null; } },
    sig(I, i) { const v = this._v; if (!v || i < 2 || !I.atr[i]) return null; const k = Math.min(g.k, this._m || g.k);
      if (v[i] >= k && v[i - 1] < k) return { side: 1, sl: Math.min(lowest(I.l, i - 5, i), I.c[i] - g.atrK * I.atr[i]), why: `내 지표 ${v[i]}/${this._m} 롱 쪽으로 막 합의` };
      if (v[i] <= -k && v[i - 1] > -k) return { side: -1, sl: Math.max(highest(I.h, i - 5, i), I.c[i] + g.atrK * I.atr[i]), why: `내 지표 ${-v[i]}/${this._m} 숏 쪽으로 막 합의` };
      return null; },
    exit(I, i, side) { const v = this._v; return g.exitFlip !== false && v && v[i] * side <= 0; } };
}
const stat = trades => { const n = trades.length, R = trades.map(t => t.R), m = n ? R.reduce((a, b) => a + b, 0) / n : 0; return { n, mean: +m.toFixed(3), wr: n ? Math.round(trades.filter(t => t.R > 0).length / n * 100) : 0, sum: +R.reduce((a, b) => a + b, 0).toFixed(2) }; };
async function simOn(g, sym, tf, cs, part) {
  const Q = await Q_(), I = ENG.prepare(Q, cs), cut = Math.floor(cs.length * 0.7), rule = chartRule(g);
  const r = ENG.simulate(rule, I, cs, { sym, from: part === "test" ? cut : 210, to: part === "train" ? cut : null, atrK: 1, be: 1 });
  return stat(r.trades);
}
export async function build({ sym, tf, specs }, onStep = () => {}) {
  const cs = await load(sym, tf), N = specs.length; if (N < 2) throw new Error("차트에 방향을 가진 보조지표가 2개 이상 있어야 합니다");
  const grid = [];
  for (let k = Math.max(2, Math.ceil(N * 0.5)); k <= N; k++) for (const rr of [1.5, 2, 2.5]) for (const atrK of [1, 1.5, 2]) for (const exitFlip of [true, false]) grid.push({ k, rr, atrK, exitFlip });
  onStep(`🧪 매매법 조합 ${grid.length}개 학습 구간(앞 70%) 백테스트`);
  let best = null;
  for (const p of grid) { const g = { id: "tmp", tf, specs, ...p }, s = await simOn(g, sym, tf, cs, "train"); if (s.n >= 12 && (!best || s.mean > best.train.mean)) best = { p, train: s }; }
  if (!best) return { ok: false, reason: "학습 구간에서 거래가 12번 이상 나오는 조합이 없음(신호가 너무 드묾)" };
  const g = { id: Date.now().toString(36), tf, specs, ...best.p, from: sym };
  onStep("🔍 처음 보는 구간(뒤 30%) 검증");
  const test = await simOn(g, sym, tf, cs, "test");
  onStep("🌐 다른 코인 5개에서 같은 값 그대로 확인");
  const cross = [];
  for (const s2 of COINS6.filter(x => x !== sym)) { try { const c2 = await load(s2, tf); cross.push({ sym: s2, ...(await simOn(g, s2, tf, c2, "all")) }); } catch (e) {} }
  const crossPos = cross.filter(x => x.n >= 5 && x.mean > 0).length;
  const pass = test.n >= 8 && test.mean > 0 && crossPos >= 3;
  return { ok: true, gene: g, train: best.train, test, cross, crossPos, pass,
    verdict: pass ? "검증 통과 — 처음 보는 구간 플러스 + 다른 코인 과반 플러스" : test.mean > 0 ? "처음 보는 구간은 플러스지만 다른 코인에서 약함(그 코인 전용일 가능성)" : "처음 보는 구간에서 마이너스 — 과최적화 가능성" };
}

// ── ⑤ 지금 포지션 ──
export async function position(g, sym) {
  const cs = await load(sym, g.tf, 600), Q = await Q_(), I = ENG.prepare(Q, cs), rule = chartRule(g); rule.prep(cs);
  const i = cs.length - 2, v = rule._v, m = rule._m || g.specs.length, price = cs.at(-1).c;   // 마지막 '마감된' 봉 기준
  let sig = null, ago = 0; for (let j = i; j >= i - 3 && !sig; j--) { const s = rule.sig(I, j); if (s) { sig = s; ago = i - j; } }
  const vote = v ? v[i] : 0, lean = vote > 0 ? 1 : vote < 0 ? -1 : 0;
  const plan = sig ? ENG.frameworkPlan({ sym, entry: price, side: sig.side, slPrice: sig.sl, cat: "추세", rr: g.rr, riskPct: 0.01, equity: 1000 }) : null;
  return { sym, tf: g.tf, price, vote, m, t: Date.now(),
    state: sig ? (plan?.skip ? `${sig.side > 0 ? "롱" : "숏"} 신호(${ago}봉 전) — 손절이 너무 멀어 시장가 부적합` : `${sig.side > 0 ? "롱" : "숏"} 진입 신호 (${ago ? ago + "봉 전" : "방금 마감 봉"})`) : lean ? `${lean > 0 ? "롱" : "숏"} 쪽 ${Math.abs(vote)}/${m} — 진입 타이밍 지남(추격 금지), 다음 합의 대기` : "중립 — 신호 대기",
    side: sig?.side || 0, sl: plan && !plan.skip ? plan.sl : null, tp: plan && !plan.skip ? plan.tp : null, lev: plan && !plan.skip ? plan.lev : null, slPct: plan?.slPct ?? null, tpPct: plan?.tpPct ?? null, why: sig?.why || "" };
}

// ── 고정된 값(AI 가 설계한 매매법) 검증: 최적화 없이 학습·처음 보는 구간·다른 코인 5개 ──
export async function validate(g, sym) {
  const cs = await load(sym, g.tf), train = await simOn(g, sym, g.tf, cs, "train"), test = await simOn(g, sym, g.tf, cs, "test"), cross = [];
  for (const s2 of COINS6.filter(x => x !== sym)) { try { const c2 = await load(s2, g.tf); cross.push({ sym: s2, ...(await simOn(g, s2, g.tf, c2, "all")) }); } catch (e) {} }
  const crossPos = cross.filter(x => x.n >= 5 && x.mean > 0).length, pass = test.n >= 8 && test.mean > 0 && crossPos >= 3;
  return { train, test, cross, crossPos, pass, verdict: pass ? "검증 통과" : test.mean > 0 ? "처음 보는 구간 플러스·다른 코인 약함" : "처음 보는 구간 마이너스" };
}

// ── 지금 차트에 없는 보조지표 추천: 후보마다 ① 자기 노이즈(처음 보는 구간) ② 내 지표 합의 매매법에 넣었을 때 처음 보는 구간 성적 변화 ──
export const CANDIDATES = [
  ["q:supertrend", {}, "추세 방향·추적 손절"], ["q:adx", {}, "추세 강도(DMI 방향)"], ["q:ichimoku", {}, "구름대 추세"], ["q:psar", {}, "추세 반전 점"], ["q:atr_stop", {}, "UT봇 추적 손절"],
  ["q:macd", {}, "모멘텀 전환"], ["q:rsi", { length: 14 }, "모멘텀 50선"], ["q:stochrsi", {}, "단기 과열·전환"], ["q:cci", {}, "평균 이탈"], ["q:mfi", {}, "거래량 반영 모멘텀"],
  ["q:obv", {}, "거래량 누적 흐름"], ["q:cmf", {}, "자금 흐름"], ["q:aroon", {}, "신고가·신저가 추세"], ["q:bb", {}, "볼린저 중심선"], ["q:keltner", {}, "켈트너 중심선"],
  ["q:donchian", {}, "돈치안 중심선"], ["q:vwap", {}, "당일 평균가"], ["q:hma", { length: 21 }, "빠른 헐 이평"], ["q:ema", { length: 200, source: "close" }, "장기 추세선 EMA200"]];
export async function recommend({ sym, tf, specs }, onStep = () => {}) {
  const cs = await load(sym, tf), T = RD.toTerm(cs), atr = await atrOf(cs), cut = Math.floor(cs.length * 0.7), have = new Set(specs.map(s => s.key + JSON.stringify(s.params?.length ?? "")));
  const N = specs.length, fixed = n => ({ k: Math.max(2, Math.ceil(n * 0.6)), rr: 2, atrK: 1.5, exitFlip: true });
  const baseG = { id: "rb", tf, specs, ...fixed(N) }, base = N >= 2 ? await simOn(baseG, sym, tf, cs, "test") : { n: 0, mean: 0 };
  const out = [];
  for (const [key, params, why] of CANDIDATES) {
    if (!DEFS[key] || have.has(key + JSON.stringify(params.length ?? DEFS[key].params?.length ?? ""))) continue;
    onStep(`💡 ${labelOf({ key })} 넣어 보기`);
    const T1 = await tune([{ key, params: { ...DEFS[key].params, ...params } }], cs); const spec = T1.tuned[0]; if (!spec) continue;
    const it = RD.readings(T, [spec]).items[0]; if (!it) continue;
    const own = noiseStats(it.series, cs, atr, cut, cs.length);
    const g = { id: "rc", tf, specs: [...specs, spec], ...fixed(N + 1) }, withIt = await simOn(g, sym, tf, cs, "test");
    out.push({ key, name: labelOf(spec), params: spec.params, why, own, delta: +(withIt.mean - base.mean).toFixed(3), test: withIt, base, tuned: T1.rows[0]?.changed || "" });
  }
  // 추천 = 처음 보는 구간에서 매매법 성적을 올리고(+0.03R↑, 거래 8번↑) 자기 노이즈도 괜찮은 지표
  const good = out.filter(x => x.delta >= 0.03 && x.test.n >= 8 && x.own.whip <= 50).sort((a, b) => b.delta - a.delta || J(b.own) - J(a.own)).slice(0, 5);
  // 한 코인 우연 방지: 다른 코인 2개에서도 넣었을 때 처음 보는 구간 성적이 오르는지 확인
  const others = COINS6.filter(x => x !== sym).slice(0, 2), oc = {};
  for (const s2 of others) { try { const c2 = await load(s2, tf); oc[s2] = { cs: c2, base: N >= 2 ? await simOn(baseG, s2, tf, c2, "test") : { mean: 0 } }; } catch (e) {} }
  for (const x of good) { onStep(`🌐 ${x.name} 다른 코인 확인`); const ds = [];
    for (const [s2, o] of Object.entries(oc)) { const w = await simOn({ id: "rc2", tf, specs: [...specs, { key: x.key, params: x.params }], ...fixed(N + 1) }, s2, tf, o.cs, "test"); ds.push(+(w.mean - o.base.mean).toFixed(3)); }
    x.crossDelta = ds; x.crossOk = ds.length ? ds.filter(d => d > 0).length >= Math.ceil(ds.length / 2) : false; }
  return { base, list: out.sort((a, b) => b.delta - a.delta), top: good.filter(x => x.crossOk).slice(0, 3), weak: good.filter(x => !x.crossOk).slice(0, 3) };
}
// 지금 상태(봉별 방향) 요약 — 뉴럴 스캔·UI 용
export async function readNow(sym, tfs = ["5", "15", "60"], specs = RD.userInds()) {
  const out = {}; for (const tf of tfs) { try { const cs = await load(sym, tf, 500), R = RD.readings(RD.toTerm(cs), specs); out[tf] = R.items.map(x => ({ name: x.name, dir: x.series[cs.length - 2] })); } catch (e) {} }
  return out;
}

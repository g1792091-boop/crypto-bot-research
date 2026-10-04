// ⚡ 실시간 진입 엔진 (손매매용) — 지금 시장가로 들어갈 만한 자리인지 코드로 계산하고, 손절·익절·승률을 정한다. 주문은 하지 않는다.
// 적용한 공개 방법(코드 복사 없이 재구현):
//  · 트리플 배리어 (López de Prado, Advances in Financial ML · mlfinlab/finmlkit TBM): 과거 비슷한 상황에서 '익절선 먼저 vs 손절선 먼저 vs 시간 만료'를 세어 승률을 낸다.
//  · 지지·저항: 스윙 피벗 군집(pkg-support-resistance 의 클러스터링) + 커널 밀도식 터치 강도(TradingView 'Support & Resistance KDE') + 거래량 프로파일 POC/VAH/VAL.
//  · 호가 벽: 0.1% 버킷 명목금액 × 평균 대비 배수 + 스냅샷 간 '벽 유지' 추적(가짜 벽·스푸핑 걸러내기, Order Book Ultimate 의 wall stability) + ±1% 불균형(quant-order-book).
//  · 다중 시간대 추세(15분·1시간·4시간 EMA·슈퍼트렌드·ADX), 모멘텀(RSI·MACD·스토캐스틱·볼린저·VWAP), 고래 흐름·펀딩·팀 판정.
import { candlesFor } from "../nuri-ai/agent.js";

const Q_ = () => import("../nuri-ai/quant.js");
const last = a => { for (let i = (a || []).length - 1; i >= 0; i--) if (a[i] != null && Number.isFinite(+a[i])) return +a[i]; return null; };
const at = (a, i) => (a && a[i] != null && Number.isFinite(+a[i])) ? +a[i] : null;
export const FEE = 0.0008;   // 왕복 수수료+슬리피지 (시장가 진입·청산 가정)

// ── 지지·저항: 피벗 군집 + 터치 강도 + 거래량 프로파일 ──
function pivots(cs, L = 3) {
  const out = [];
  for (let i = L; i < cs.length - L; i++) {
    let hi = true, lo = true;
    for (let j = i - L; j <= i + L; j++) { if (j === i) continue; if (cs[j].h >= cs[i].h) hi = false; if (cs[j].l <= cs[i].l) lo = false; }
    if (hi) out.push({ price: cs[i].h, kind: "high", i }); if (lo) out.push({ price: cs[i].l, kind: "low", i });
  }
  return out;
}
function cluster(points, tol) {   // 가까운 가격끼리 묶어 가중 평균 (단일 연결 군집)
  const P = [...points].sort((a, b) => a.price - b.price), out = [];
  for (const p of P) { const g = out.at(-1); if (g && p.price - g.max <= tol) { g.items.push(p); g.max = p.price; } else out.push({ items: [p], max: p.price }); }
  return out.map(g => { const w = g.items.reduce((s, x) => s + (x.w || 1), 0); return { price: g.items.reduce((s, x) => s + x.price * (x.w || 1), 0) / w, n: g.items.length, w, src: [...new Set(g.items.map(x => x.src))] }; });
}
function touches(cs, price, tol) { let n = 0; for (const b of cs) if (b.l - tol <= price && price <= b.h + tol) n++; return n; }
function volumeProfile(cs, bins = 48) {
  const lo = Math.min(...cs.map(b => b.l)), hi = Math.max(...cs.map(b => b.h)), w = (hi - lo) / bins || 1, h = Array(bins).fill(0);
  for (const b of cs) { const a = Math.max(0, Math.floor((b.l - lo) / w)), z = Math.min(bins - 1, Math.floor((b.h - lo) / w)); for (let j = a; j <= z; j++) h[j] += b.v / (z - a + 1); }
  const poc = h.indexOf(Math.max(...h)), tot = h.reduce((s, x) => s + x, 0); let vol = h[poc], L = poc, R = poc;
  while (vol < tot * 0.7 && (L > 0 || R < bins - 1)) { if (R >= bins - 1 || (L > 0 && h[L - 1] >= h[R + 1])) vol += h[--L]; else vol += h[++R]; }
  const mid = j => lo + (j + 0.5) * w;
  return { poc: mid(poc), vah: mid(R), val: mid(L) };
}
export function levels({ k1h, k4h, atr1h, book }) {
  const tol = Math.max(atr1h * 0.35, k1h.at(-1).c * 0.0015), pts = [];
  for (const p of pivots(k1h.slice(-300), 3)) pts.push({ price: p.price, w: 1, src: "1시간 스윙" });
  for (const p of pivots(k4h.slice(-200), 2)) pts.push({ price: p.price, w: 2, src: "4시간 스윙" });
  const vp = volumeProfile(k1h.slice(-300));
  pts.push({ price: vp.poc, w: 3, src: "매물대 POC" }, { price: vp.vah, w: 1.5, src: "매물대 VAH" }, { price: vp.val, w: 1.5, src: "매물대 VAL" });
  for (const w of book?.bidWalls || []) if (w.stable) pts.push({ price: w.price, w: 1 + Math.min(3, (w.xAvg || 1) / 3), src: "매수벽" });
  for (const w of book?.askWalls || []) if (w.stable) pts.push({ price: w.price, w: 1 + Math.min(3, (w.xAvg || 1) / 3), src: "매도벽" });
  const p = k1h.at(-1).c, mag = Math.pow(10, Math.floor(Math.log10(p)) - 1) * 5; pts.push({ price: Math.round(p / mag) * mag, w: 0.5, src: "라운드 넘버" });
  const recent = k1h.slice(-300);
  return cluster(pts, tol).map(g => ({ ...g, touches: touches(recent, g.price, tol * 0.5) }))
    .map(g => ({ ...g, strength: +(g.w + Math.min(6, g.touches / 4)).toFixed(1) })).filter(g => g.strength >= 2).sort((a, b) => a.price - b.price);
}

// ── 호가 벽 + 유지 추적 (스냅샷마다 비슷한 가격에 벽이 남아 있으면 stable) ──
const BOOKS = {};
export async function bookWithWalls(sym) {
  const F = await import("../nuri-ai/flow.js"), r = await F.orderBook({ symbol: sym, exchange: "binancef", depth: 1000 }), d = r.data;
  const hist = (BOOKS[sym] ||= []); hist.push({ t: Date.now(), bid: d.bidWalls.map(w => w.price), ask: d.askWalls.map(w => w.price) }); while (hist.length > 6) hist.shift();
  const seen = (price, side) => hist.slice(0, -1).filter(h => h[side].some(p => Math.abs(p / price - 1) < 0.0015)).length;
  const mark = (ws, side) => ws.filter(w => (w.xAvg || 0) >= 3).map(w => { const k = seen(w.price, side); return { ...w, seen: k, stable: hist.length < 2 ? (w.xAvg || 0) >= 6 : k >= Math.min(2, hist.length - 1) }; });
  return { mid: d.mid, spreadBps: d.spreadBps, imb1: d.bands?.[1]?.imbalance ?? 0, imb2: d.bands?.[2]?.imbalance ?? 0, bidWalls: mark(d.bidWalls, "bid"), askWalls: mark(d.askWalls, "ask"), snapshots: hist.length };
}

// ── 트리플 배리어 승률: 비슷한 상황(같은 방향 추세·RSI 구간)에서 같은 손절%/익절%로 진입했다면 ──
// 손매매 실전 계획 그대로 시뮬레이션: 익절1 에서 절반 익절 → 남은 절반은 손절을 본전으로 올리고 익절2 까지. (tp1Pct 없으면 단일 익절)
//   승 = 손절보다 익절1 이 먼저 · 기대값 = 계획 전체의 R(수수료 포함). 같은 봉에서 손절·익절이 둘 다 닿으면 보수적으로 손절.
export function tripleBarrier(cs, I, { side, slPct, tpPct, tp1Pct, H, cond }) {
  let win = 0, loss = 0, tout = 0, sumR = 0, n = 0, full = 0;
  const t1 = tp1Pct || tpPct, rr1 = t1 / slPct, rr2 = tpPct / slPct, split = !!tp1Pct && tp1Pct < tpPct;
  for (let i = 210; i < cs.length - 2; i++) {
    if (cond && !cond(i)) continue;
    if (i + H >= cs.length) break;   // 미래가 다 안 보이는 표본은 제외
    const e = cs[i].c, sl = e * (1 - side * slPct), p1 = e * (1 + side * t1), p2 = e * (1 + side * tpPct), end = i + H;
    let r = null, half = false;
    for (let j = i + 1; j <= end; j++) {
      const lo = cs[j].l, hi = cs[j].h, stop = half ? e : sl;
      const hitStop = side > 0 ? lo <= stop : hi >= stop, hit1 = side > 0 ? hi >= p1 : lo <= p1, hit2 = side > 0 ? hi >= p2 : lo <= p2;
      if (!half) {
        if (hitStop) { r = -1; break; }
        if (hit1) { if (!split || hit2) { r = split ? 0.5 * rr1 + 0.5 * rr2 : rr1; full++; break; } half = true; continue; }
      } else {
        if (hitStop) { r = 0.5 * rr1; break; }          // 남은 절반 본전 청산
        if (hit2) { r = 0.5 * rr1 + 0.5 * rr2; full++; break; }
      }
    }
    if (r == null) { const m = ((cs[end].c - e) / e * side) / slPct; r = half ? 0.5 * rr1 + 0.5 * Math.max(0, m) : m; }
    n++; if (r < 0 && !half) loss++; else if (half || r >= rr1 - 1e-9) win++; else tout++;
    sumR += r - FEE / slPct;
    i += 2;   // 겹치는 표본 줄이기(표본 독립성)
  }
  const decided = win + loss;
  return { n, win, loss, tout, full, wr: +(decided ? win / decided * 100 : 0).toFixed(1), exp: +(n ? sumR / n : 0).toFixed(3) };
}

// ── 메인: 한 코인 분석 ──
export async function analyzeCoin(sym, ctx = {}) {
  const Q = await Q_();
  const [k5, k15, k1h, k4h] = ctx.candles ? [ctx.candles["5"] || null, ctx.candles["15"], ctx.candles["60"], ctx.candles["240"]]   // 검증용: 과거 시점까지 자른 캔들
    : await Promise.all([["5", 1000], ["15", 1000], ["60", 1000], ["240", 500]].map(([tf, n]) => candlesFor({ market: sym, exchange: "binancef", timeframe: tf }, n).then(r => r.cs).catch(() => null)));
  const has5 = k5?.length > 300;
  if (!(k15?.length > 300 && k1h?.length > 300 && k4h?.length > 200)) throw new Error("캔들 부족");
  const ind = (cs, t, p) => Q.computeInd(cs, t, p);
  const mk = cs => ({ e20: ind(cs, "ema", { length: 20 }).value, e50: ind(cs, "ema", { length: 50 }).value, e200: ind(cs, "ema", { length: 200 }).value, st: ind(cs, "supertrend", {}).trend, adx: ind(cs, "adx", {}).adx,
    rsi: ind(cs, "rsi", { length: 14 }).value, macd: ind(cs, "macd", {}), atr: ind(cs, "atr", { length: 14 }).value, bb: ind(cs, "bb", {}), sto: ind(cs, "stoch", {}), vwap: ind(cs, "vwap", {}).value });
  const A = { "15": mk(k15), "60": mk(k1h), "240": mk(k4h), ...(has5 ? { "5": mk(k5) } : {}) }, CS = { "15": k15, "60": k1h, "240": k4h, ...(has5 ? { "5": k5 } : {}) };
  const price = has5 ? k5.at(-1).c : k15.at(-1).c, atr15 = last(A["15"].atr), atr1h = last(A["60"].atr);
  // 추세 (봉마다 −1..+1)
  const trendAt = (tf, i) => { const a = A[tf], c = CS[tf][i]?.c; if (!c || at(a.e200, i) == null) return 0; let s = 0;
    s += at(a.e20, i) > at(a.e50, i) ? 1 : -1; s += c > at(a.e200, i) ? 1 : -1; s += (at(a.st, i) || 0) > 0 ? 1 : -1; return s / 3; };
  const tr = { "5": has5 ? trendAt("5", k5.length - 1) : null, "15": trendAt("15", k15.length - 1), "60": trendAt("60", k1h.length - 1), "240": trendAt("240", k4h.length - 1) };
  const trend = +(has5 ? tr["5"] * 0.1 + tr["15"] * 0.2 + tr["60"] * 0.4 + tr["240"] * 0.3 : tr["15"] * 0.25 + tr["60"] * 0.4 + tr["240"] * 0.35).toFixed(2), adx1h = last(A["60"].adx);
  const rsi5 = has5 ? last(A["5"].rsi) : null;
  // 호가·레벨
  let book = null; if (!ctx.candles) try { book = await bookWithWalls(sym); } catch (e) {}
  const lv = levels({ k1h, k4h, atr1h, book });
  const sup = lv.filter(l => l.price < price * 0.9995).sort((a, b) => b.price - a.price), res = lv.filter(l => l.price > price * 1.0005).sort((a, b) => a.price - b.price);
  // 모멘텀
  const m15 = A["15"], i15 = k15.length - 1, rsi15 = last(m15.rsi), rsi1h = last(A["60"].rsi), hist15 = m15.macd.hist, sk = last(m15.sto.k);
  const macdUp = at(hist15, i15) > at(hist15, i15 - 1), bbU = last(m15.bb.upper), bbL = last(m15.bb.lower), vwap = last(m15.vwap);
  // 📈 내 차트 터미널 보조지표: 15분·1시간봉에서 지금 방향 + '지금과 같은 상태(80%↑ 일치)'였던 과거 봉 찾기
  let MY = null;
  if (ctx.myInds !== false) { try { const RD = await import("../nuri-ai/terminal/readings.js"), specs = ctx.specs || RD.userInds();
    if (specs.length) { const r15 = RD.readings(RD.toTerm(k15), specs), r1h = RD.readings(RD.toTerm(k1h), specs), r5 = has5 ? RD.readings(RD.toTerm(k5), specs) : null;
      if (r15.items.length) MY = { r5, r15, r1h, names: r15.items.map(x => x.name), now5: r5 ? r5.items.map(x => x.dir) : [], now15: r15.items.map(x => x.dir), now1h: r1h.items.map(x => x.dir), agree: RD.agree }; } } catch (e) {} }
  const out = { sym, ko: sym.replace("USDT", ""), t: Date.now(), price, atr15, atr1h, trend, tr, adx1h, rsi5, rsi15, rsi1h, book, levels: lv, sides: [],
    myInd: MY ? MY.r15.items.map((x, k) => ({ name: x.name, d5: MY.r5?.items[k]?.dir ?? 0, d15: x.dir, d1h: MY.r1h.items[k]?.dir ?? 0 })) : null };
  for (const side of [1, -1]) {
    const S = side > 0 ? sup : res, R = side > 0 ? res : sup, why = [], warn = [];
    // 손절: 가장 가까운 구조 레벨 너머 + 0.25 ATR(15분) · 최소 0.3% · 최대 2%
    let slLv = S.find(l => Math.abs(price - l.price) / price >= 0.002) || null;
    let slPx = slLv ? slLv.price - side * atr15 * 0.25 : price - side * atr15 * 1.5;
    let slPct = Math.abs(price - slPx) / price;
    if (slPct < 0.003) { slPct = 0.003; slPx = price * (1 - side * slPct); }
    const tooFar = slPct > 0.02;
    // 익절: 반대편 레벨(벽) 바로 앞 — TP1 = 첫 레벨, TP2 = 그 다음 (최소 1R / 1.8R 확보)
    const tgt = R.filter(l => Math.abs(l.price - price) / price > slPct * 0.9);
    let tp1 = tgt[0] ? tgt[0].price - side * atr15 * 0.15 : price * (1 + side * slPct * 1.5);
    let tp2 = tgt[1] ? tgt[1].price - side * atr15 * 0.15 : price * (1 + side * slPct * 2.5);
    if (Math.abs(tp1 - price) / price < slPct) tp1 = price * (1 + side * slPct * 1.0);
    if (Math.abs(tp2 - price) / price < slPct * 1.8) tp2 = price * (1 + side * slPct * 1.8);
    // 검증된 매매법 신호가 이 방향으로 막 나왔으면, 그 매매법이 워크포워드로 검증된 계획(손절·손익비·+1R 본절)을 그대로 쓴다
    const sig = ctx.libSignal && ctx.libSignal.side === side ? ctx.libSignal : null;
    if (sig && sig.sl && (price - sig.sl) * side > 0) { slPx = sig.sl; slPct = Math.max(0.003, Math.abs(price - slPx) / price); slPx = price * (1 - side * slPct); tp1 = price * (1 + side * slPct * 1.0); tp2 = price * (1 + side * slPct * Math.max(1.5, sig.rr || 2)); }
    const ov = ctx.override?.side === side ? ctx.override : null;   // 토론에서 제안된 손절·익절 (검증용 재계산)
    if (ov) { if (+ov.sl > 0) { slPx = +ov.sl; slPct = Math.abs(price - slPx) / price; } if (+ov.tp1 > 0) tp1 = +ov.tp1; if (+ov.tp2 > 0) tp2 = +ov.tp2; if ((tp2 - tp1) * side < 0) [tp1, tp2] = [tp2, tp1]; }
    const tp1Pct = Math.abs(tp1 - price) / price, tp2Pct = Math.abs(tp2 - price) / price;
    // 트리플 배리어: 15분봉(시간 만료 48봉=12시간) + 1시간봉(12봉) 합산, 같은 방향 추세·비슷한 RSI 조건
    const rsiNow15 = rsi15, condTrend15 = i => Math.sign(trendAt("15", i) || 0) === Math.sign(tr["15"] || side) && Math.abs((at(m15.rsi, i) ?? 50) - rsiNow15) <= 12;
    const plan = { side, slPct, tpPct: tp2Pct, tp1Pct };
    let tb15 = tripleBarrier(k15, m15, { ...plan, H: 48, cond: condTrend15 });
    if (tb15.n < 30) tb15 = tripleBarrier(k15, m15, { ...plan, H: 48, cond: i => Math.sign(trendAt("15", i) || 0) === Math.sign(tr["15"] || side) });
    const condTrend1h = i => Math.sign(trendAt("60", i) || 0) === Math.sign(tr["60"] || side);
    const tb1h = tripleBarrier(k1h, A["60"], { ...plan, H: 12, cond: condTrend1h });
    const tbTP1 = tripleBarrier(k15, m15, { side, slPct, tpPct: tp2Pct, H: 48, cond: condTrend15 });   // 참고: 끝까지 익절2 만 노렸을 때
    // 5분봉(시간 만료 96봉 = 8시간): 같은 방향 5분 추세에서 같은 계획
    const tb5 = has5 ? tripleBarrier(k5, A["5"], { ...plan, H: 96, cond: i => Math.sign(trendAt("5", i) || 0) === Math.sign(tr["5"] || side) }) : { n: 0, wr: 0, exp: 0 };
    // 내 지표가 지금과 같은 상태였던 과거(15분 + 1시간)에서 같은 계획의 결과
    let my = null;
    if (MY) { const L15 = k15.length - 1, L1 = k1h.length - 1;
      const a = tripleBarrier(k15, m15, { ...plan, H: 48, cond: i => MY.agree(MY.r15, L15, i) >= 0.8 }), b2 = tripleBarrier(k1h, A["60"], { ...plan, H: 12, cond: i => MY.agree(MY.r1h, L1, i) >= 0.8 });
      const c5 = MY.r5 ? tripleBarrier(k5, A["5"], { ...plan, H: 96, cond: i => MY.agree(MY.r5, k5.length - 1, i) >= 0.8 }) : { n: 0, wr: 0, exp: 0 };
      const nn = a.n + b2.n + c5.n, base0 = tripleBarrier(k15, m15, { ...plan, H: 48 }), N1 = 150;
      const wr0 = nn ? (a.wr * a.n + b2.wr * b2.n + c5.wr * c5.n) / nn : 0, ex0 = nn ? (a.exp * a.n + b2.exp * b2.n + c5.exp * c5.n) / nn : 0;
      const v5 = MY.now5.filter(x => x === side).length, o5 = MY.now5.filter(x => x === -side).length;
      const v15 = MY.now15.filter(x => x === side).length, o15 = MY.now15.filter(x => x === -side).length, v1h = MY.now1h.filter(x => x === side).length, o1h = MY.now1h.filter(x => x === -side).length;
      my = { n: nn, wrRaw: +wr0.toFixed(1), wr: +((wr0 * nn + base0.wr * N1) / (nn + N1)).toFixed(1), exp: +((ex0 * nn + base0.exp * N1) / (nn + N1)).toFixed(3), v5, o5, v15, o15, v1h, o1h, total: MY.now15.length }; }
    const nT = tb5.n + tb15.n + tb1h.n, wrRaw = nT ? (tb5.wr * tb5.n + tb15.wr * tb15.n + tb1h.wr * tb1h.n) / nT : 0, expRaw = nT ? (tb5.exp * tb5.n + tb15.exp * tb15.n + tb1h.exp * tb1h.n) / nT : 0;
    // 과신 보정(베이지안 축소): 같은 계획을 '조건 없이' 아무 때나 했을 때의 기준값 쪽으로 당긴다. 표본외 검증에서 날것의 통계는 익절1 도달률을 3~9%p 과대평가했음.
    const base = tripleBarrier(k15, m15, { ...plan, H: 48 }), N0 = 250;
    const wr = +((wrRaw * nT + base.wr * N0) / (nT + N0)).toFixed(1), exp = +((expRaw * nT + base.exp * N0) / (nT + N0)).toFixed(3);
    // 합류 점수 (0~100)
    let sc = 0;
    const tAlign = (tr["15"] * side > 0 ? 1 : 0) + (tr["60"] * side > 0 ? 1 : 0) + (tr["240"] * side > 0 ? 1 : 0);
    sc += tAlign / 3 * 25; why.push(`추세 ${tAlign}/3 일치(${has5 ? `5분 ${tr["5"] > 0 ? "↑" : tr["5"] < 0 ? "↓" : "→"}·` : ""}15분 ${tr["15"] > 0 ? "↑" : tr["15"] < 0 ? "↓" : "→"}·1시간 ${tr["60"] > 0 ? "↑" : tr["60"] < 0 ? "↓" : "→"}·4시간 ${tr["240"] > 0 ? "↑" : tr["240"] < 0 ? "↓" : "→"})`);
    const distS = slLv ? Math.abs(price - slLv.price) / atr15 : 9;
    if (slLv && distS <= 1.5) { sc += 15; why.push(`${side > 0 ? "지지" : "저항"} ${fmt(slLv.price)} 바로 앞(${distS.toFixed(1)}ATR · ${slLv.src.join("+")} · 강도 ${slLv.strength})`); } else if (slLv && distS <= 3) sc += 7;
    const room = tgt[0] ? Math.abs(tgt[0].price - price) / Math.abs(price - slPx) : 3;
    if (room >= 2) { sc += 10; why.push(`다음 ${side > 0 ? "저항" : "지지"}까지 ${room.toFixed(1)}R 여유`); } else if (room < 1.2) warn.push(`바로 앞 ${side > 0 ? "저항" : "지지"}(${fmt(tgt[0]?.price)})까지 ${room.toFixed(1)}R뿐`);
    if (book) { const imb = book.imb1 * side; if (imb > 0.15) { sc += 8; why.push(`±1% 호가 ${side > 0 ? "매수" : "매도"} 우위 ${(book.imb1 * 100).toFixed(0)}%`); } else if (imb < -0.25) warn.push(`호가가 반대 우위 ${(book.imb1 * 100).toFixed(0)}%`);
      const wallBehind = (side > 0 ? book.bidWalls : book.askWalls).find(w => w.stable && Math.abs(w.distPct) < 1 && (w.price - slPx) * side > 0);
      const wallFront = (side > 0 ? book.askWalls : book.bidWalls).find(w => w.stable && Math.abs(w.distPct) < Math.abs((tp1 - price) / price * 100));
      if (wallBehind) { sc += 7; why.push(`${side > 0 ? "매수벽" : "매도벽"} ${fmt(wallBehind.price)} 이 손절 앞을 받침(평균 ×${(wallBehind.xAvg || 0).toFixed(1)}, 유지 ${wallBehind.seen}회)`); }
      if (wallFront) warn.push(`${side > 0 ? "매도벽" : "매수벽"} ${fmt(wallFront.price)} 이 익절1 전에 있음(×${(wallFront.xAvg || 0).toFixed(1)})`); }
    if (side > 0 ? rsi15 >= 68 : rsi15 <= 32) warn.push(`15분 RSI ${rsi15?.toFixed(0)} ${side > 0 ? "과매수(추격 위험)" : "과매도(추격 위험)"}`);
    else if (side > 0 ? rsi15 <= 35 : rsi15 >= 65) warn.push(`15분 RSI ${rsi15?.toFixed(0)} — 단기 모멘텀이 반대`);
    else sc += 4;
    if ((macdUp ? 1 : -1) === side) { sc += 4; why.push(`15분 MACD 히스토그램 ${side > 0 ? "상승" : "하락"} 전환`); }
    if (side > 0 ? sk < 80 : sk > 20) sc += 2;
    if (vwap && (price - vwap) * side > 0) { sc += 3; why.push(`VWAP ${side > 0 ? "위" : "아래"}`); }
    if (bbU && bbL && (side > 0 ? price > bbU : price < bbL)) warn.push("볼린저 밖(추격 위험)");
    if (adx1h >= 20 && tAlign >= 2) { sc += 5; why.push(`1시간 ADX ${adx1h.toFixed(0)}(추세 있음)`); }
    const wh = ctx.whale; if (wh?.status === "approved") { if (wh.dir === side) { sc += 6; why.push(`고래 ${side > 0 ? "순매수" : "순매도"} ${Math.abs(wh.netPct)}%`); } else warn.push(`고래 반대 흐름 ${wh.netPct}%`); }
    const fd = ctx.funding; if (fd?.key === (side > 0 ? "hotLong" : "hotShort")) { sc -= 6; warn.push(`펀딩 ${side > 0 ? "롱" : "숏"} 과열`); }
    const V = ctx.verdicts || {}; let vt = 0;
    if (V.ta?.all != null) { vt += Math.sign(V.ta.all) === side ? 1 : V.ta.all * side < -0.3 ? -1 : 0; }
    if (V.selfAI?.conf >= 55) vt += V.selfAI.dir === side ? 1 : V.selfAI.dir === -side ? -1 : 0;
    if (V.ml?.prob != null) vt += (side > 0 ? V.ml.prob >= 0.55 : V.ml.prob <= 0.45) ? 1 : 0;
    if (ctx.libSignal && ctx.libSignal.side === side) { vt += 1; why.push(`검증 매매법 신호: ${ctx.libSignal.name}`); }
    sc += Math.max(-6, Math.min(12, vt * 4)); if (vt > 0) why.push(`팀 판정 ${vt}개 일치`); if (vt < 0) warn.push("팀 판정 반대");
    if (my && my.total) { const f = (my.v15 + my.v1h) / Math.max(1, my.v15 + my.v1h + my.o15 + my.o1h);
      (f >= 0.6 ? why : f <= 0.4 ? warn : why).push(`내 차트 지표 ${side > 0 ? "롱" : "숏"} 쪽 ${MY.r5 ? `5분 ${my.v5}/${my.total} · ` : ""}15분 ${my.v15}/${my.total} · 1시간 ${my.v1h}/${my.total}`);
      // 2개월 표본외: 지표가 80%↑ 같은 방향일 때 그 방향 시장가 진입 = 평균 −0.15R(가장 나쁨, 이미 움직인 뒤 추격) → 점수 가산 대신 경고
      if (f >= 0.8) { warn.push("지표가 거의 다 같은 방향 = 이미 움직인 뒤일 가능성(표본외 평균 −0.15R) — 추격 주의"); sc -= 5; } else sc += Math.round((f - 0.5) * 8); }
    sc = Math.max(0, Math.min(100, Math.round(sc)));
    const rr = +(tp2Pct / slPct).toFixed(2), rr1 = +(tp1Pct / slPct).toFixed(2);
    // 등급 (2개월·6코인 표본외 검증 결과로 다시 정함): 스냅샷 지표·지지저항·호가 조합만으로는 표본외 우위가 없었다(전체 −0.12R, 최선 조합도 ≈0R).
    //  유력 = 워크포워드 검증을 통과한 매매법 신호가 지금 같은 방향으로 나옴 + 추세 2/3↑ + 손익비 1.5↑ (그 매매법의 최근 실적이 근거)
    //  보통 = 3개 시간대 추세 일치 + 1시간 ADX 25↑ + 손익비 1.5↑ (표본외 ≈ 0R — 우위 미확인, 추세 동행일 뿐)
    const grade = tooFar && !sig ? "대기" : (sig && tAlign >= 2 && rr >= 1.5) ? "유력" : (tAlign === 3 && adx1h >= 25 && rr >= 1.5) ? "보통" : "관망";
    const evidence = sig ? `검증 매매법 '${sig.name}'(${sig.tf === "60" ? "1시간" : sig.tf === "240" ? "4시간" : sig.tf + "분"}봉) 신호 ${Math.round((Date.now() - sig.t) / 60000)}분 전 · 최근 ${sig.n}건 기대값 ${sig.mean >= 0 ? "+" : ""}${sig.mean}R · 승률 ${sig.wr}%`
      : grade === "보통" ? "추세 동행(3개 시간대 일치·ADX 25↑) — 2개월 표본외 검증 ≈ 0R, 통계적 우위 미확인" : "검증된 근거 없음 — 관망 권장";
    const lev = Math.max(1, Math.min(sym === "BTCUSDT" ? 100 : 50, Math.floor(0.4 / slPct)));   // 청산공식: 손절 = 청산거리 40% 이하 (상한 BTC 100x·알트 50x)
    out.sides.push({ side, grade, score: sc, entry: price, sl: +slPx.toPrecision(7), tp1: +tp1.toPrecision(7), tp2: +tp2.toPrecision(7), slPct: +(slPct * 100).toFixed(2), tp1Pct: +(tp1Pct * 100).toFixed(2), tp2Pct: +(tp2Pct * 100).toFixed(2),
      rr, rr1, wr, exp, n: nT, evidence, my, sig: sig ? { name: sig.name, tf: sig.tf, mean: sig.mean, n: sig.n, wr: sig.wr, t: sig.t } : null, wrRaw: +wrRaw.toFixed(1), expRaw: +expRaw.toFixed(3), base: { wr: base.wr, exp: base.exp }, wrTP2only: tbTP1.wr, expTP2only: tbTP1.exp, tb: { m5: tb5, m15: tb15, h1: tb1h }, lev, liq: +(price * (1 - side * 0.95 / lev)).toPrecision(7), slLevel: slLv ? { price: slLv.price, src: slLv.src, strength: slLv.strength } : null,
      tpLevels: tgt.slice(0, 2).map(l => ({ price: l.price, src: l.src, strength: l.strength })), why, warn,
      limitAlt: tooFar && slLv ? { entry: +(slLv.price + side * atr15 * 0.2).toPrecision(7), note: `구조 손절이 ${(slPct * 100).toFixed(1)}%로 멀어 시장가 부적합 → ${fmt(slLv.price)} 근처 지정가 대기` } : null,
      validUntil: Date.now() + 15 * 60e3, invalidPx: +(price + side * Math.abs(price - slPx) * 0.3).toPrecision(7) });
  }
  out.best = [...out.sides].sort((a, b) => gradeRank(b.grade) - gradeRank(a.grade) || (b.sig?.mean ?? -9) - (a.sig?.mean ?? -9) || b.score - a.score)[0];
  return out;
}
export const gradeRank = g => ({ "유력": 3, "보통": 2, "대기": 1, "관망": 0 }[g] ?? 0);
function fmt(v) { if (v == null || !Number.isFinite(+v)) return "—"; v = +v; return v >= 1000 ? Math.round(v).toLocaleString() : v >= 1 ? v.toFixed(2) : v.toPrecision(4); }
export const fmtPx = fmt;
export function setupText(r, s) {
  return `${r.ko} ${s.side > 0 ? "롱" : "숏"} [${s.grade}] 시장가 ${fmt(s.entry)} · 손절 ${fmt(s.sl)}(−${s.slPct}%) · 익절1 ${fmt(s.tp1)}(+${s.tp1Pct}%, ${s.rr1}R) · 익절2 ${fmt(s.tp2)}(+${s.tp2Pct}%, ${s.rr}R) · 유사상황 익절1 도달률 ${s.wr}% (${s.n}표본 · 절반익절+본절 계획 기대값 ${s.exp >= 0 ? "+" : ""}${s.exp}R) · 합류 ${s.score}/100 · 권장 레버 ≤${s.lev}x${s.evidence ? " · 근거: " + s.evidence : ""}`;
}

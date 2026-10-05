// ⚙️ 뉴럴 데스크 전략 엔진 — 사용자가 준 매매법 목록을 "실행 가능한 규칙"으로 + 청산 공식 역산 프레임워크(20배 이상).
// 순수 함수만 (브라우저/노드 공용) → 실제 캔들로 자체 백테스트·보정이 가능하다.
//
// 청산 공식 역산(격리, USDT 무기한):  청산 거리 ≈ 1/레버리지
//   손절 거리는 청산 거리의 40% 이하:  20x→SL≤2% · 50x→≤0.8% · 100x→≤0.4% · 200x→≤0.2%
//   → 레버리지 = floor(0.4 / 손절거리), 최소 20x (사용자 지시), 코인별 상한(비트 200·알트 100)
//   → 1회 손실 = 자본의 0.5~1% (명목 = 자본×리스크%/손절거리, 증거금 = 명목/레버리지)
//   → 물타기 금지 · 손익비는 수수료 반영 후 순 R:R 기준 · +1R 도달 시 본절 이동
export const FW = {
  minLev: 20,
  slShareOfLiq: 0.4,        // 손절 = 청산거리의 40%
  fee: 0.0008,              // 왕복 수수료+슬리피지 (바이낸스 선물 테이커 기준 현실치)
  slFloor: 0.0025,          // 손절 최소 0.25% (이보다 좁으면 수수료가 리스크를 잡아먹음)
  slCapByCat: { "단타": 0.015, "ICT": 0.02, "스윙": 0.02, "추세": 0.02, "돌파": 0.02, "역추세": 0.02, "AI개발": 0.02 },   // 20x 기준 표(스캘핑 1.5%·그 외 2%)
  baseRisk: 0.005,          // 1회 손실 0.5%
  maxRisk: 0.01,            // 검증된 전략은 1%까지
  maxNotionalX: 3,          // 명목 상한 = 자본 × 3 (표의 100x 스캘핑 166%보다 여유)
  maxHeat: 0.04,            // 동시 보유 리스크 합 ≤ 자본 4%
  dailyStop: 0.03,          // 일일 손실 3% 도달 시 그날 신규 진입 중지
};
export const levCapOf = sym => sym === "BTCUSDT" ? 200 : 100;

// 손절거리(분수) → 프레임워크 레버리지. 손절이 너무 넓어 20x에서도 규칙 위반이면 null(진입 금지).
// levMode "min": 레버리지를 최소 20배로 고정(손절이 청산거리의 40% 이하일 때). 1회 손실 금액·명목은 그대로이고 증거금만 커져
//   ROE 출렁임(손절 시 −40% 안팎 → −15% 안팎)이 작아지고 청산가가 더 멀어진다. 기본 "fw" = 손절폭에서 역산(사용자 프레임워크).
export function frameworkPlan({ sym, entry, side, slPrice, cat, rr, riskPct, equity, levMode = "fw" }) {
  let s = Math.abs(entry - slPrice) / entry;
  if (!(s > 0)) return null;
  const cap = FW.slCapByCat[cat] ?? 0.02;
  if (s > cap) return { skip: `손절폭 ${(s * 100).toFixed(2)}% > ${cat} 상한 ${(cap * 100).toFixed(1)}% (20x 규칙 위반 → 진입 금지)` };
  if (s < FW.slFloor) { s = FW.slFloor; slPrice = side > 0 ? entry * (1 - s) : entry * (1 + s); }
  const levFw = Math.max(FW.minLev, Math.min(levCapOf(sym), Math.floor(FW.slShareOfLiq / s)));
  const lev = levMode === "min" && s <= FW.slShareOfLiq * 0.95 / FW.minLev ? FW.minLev : levFw;
  const liqDist = 0.95 / lev;
  const r = Math.min(FW.maxRisk, Math.max(0.0025, riskPct ?? FW.baseRisk));
  let notional = equity * r / (s + FW.fee);                 // 손절 시 손실(수수료 포함) = 자본×r
  notional = Math.min(notional, equity * FW.maxNotionalX);
  const margin = notional / lev;
  const tpDist = rr * (s + FW.fee) + FW.fee;                 // 순 손익비 = rr
  const tpPrice = side > 0 ? entry * (1 + tpDist) : entry * (1 - tpDist);
  const liq = side > 0 ? entry * (1 - liqDist) : entry * (1 + liqDist);
  return { lev, sl: slPrice, tp: tpPrice, liq, slPct: +(s * 100).toFixed(3), tpPct: +(tpDist * 100).toFixed(3), liqPct: +(liqDist * 100).toFixed(2),
    notional: +notional.toFixed(2), margin: +margin.toFixed(2), risk: +(equity * r).toFixed(2), riskPct: +(r * 100).toFixed(2), rr };
}

// ── 지표 준비 (quant.js computeInd 재사용 — 검증된 구현) ──
export function prepare(Q, cs) {
  const ci = (t, p) => Q.computeInd(cs, t, p);
  const n = cs.length;
  const o = cs.map(b => +b.o), h = cs.map(b => +b.h), l = cs.map(b => +b.l), c = cs.map(b => +b.c), v = cs.map(b => +b.v);
  const bb = ci("bb", { length: 20, mult: 2 }), macd = ci("macd", { fast: 12, slow: 26, signal: 9 }), adx = ci("adx", { length: 14 });
  const st = ci("supertrend", { length: 10, mult: 3 }), sto = ci("stoch", { length: 14, k_smooth: 3, d_smooth: 3 });
  const I = {
    n, o, h, l, c, v, t: cs.map(b => +b.t),
    ema9: ci("ema", { length: 9 }).value, ema20: ci("ema", { length: 20 }).value, ema50: ci("ema", { length: 50 }).value, ema200: ci("ema", { length: 200 }).value,
    sma10: ci("sma", { length: 10 }).value, sma20: ci("sma", { length: 20 }).value,
    rsi: ci("rsi", { length: 14 }).value, atr: ci("atr", { length: 14 }).value, roc: ci("roc", { length: 9 }).value,
    bbU: bb.upper, bbM: bb.middle, bbL: bb.lower, bbW: bb.width,
    macd: macd.line, macdS: macd.signal, adx: adx.adx, pdi: adx.plus_di, mdi: adx.minus_di,
    stTrend: st.trend, stLine: st.line, stoK: sto.k, stoD: sto.d,
    vwap: ci("vwap", {}).value, volMa: ci("volume_sma", { length: 20 }).value,
    hh20: ci("highest", { length: 20, source: "high" }).value, ll20: ci("lowest", { length: 20, source: "low" }).value,
    sma5: ci("sma", { length: 5 }).value, roc5: ci("roc", { length: 5 }).value,
  };
  { const sr = ci("stochrsi", { length: 14, k_smooth: 3, d_smooth: 3 }), ps = ci("psar", {}); I.srK = sr.k; I.srD = sr.d; I.psar = ps.value; I.psarT = ps.trend; }
  // 다우 이론 스윙(좌우 3봉 피벗) — i 시점에 '확정된' 직전 두 고점·저점 (미래 봉을 쓰지 않도록 3봉 지연 확정)
  { const P = 3, sh = [], sl = []; I.swH = new Array(n).fill(null); I.swL = new Array(n).fill(null);
    for (let i = 0; i < n; i++) { const k = i - P;
      if (k >= P) { let isH = true, isL = true; for (let j = k - P; j <= k + P; j++) { if (j === k) continue; if (h[j] >= h[k]) isH = false; if (l[j] <= l[k]) isL = false; } if (isH) sh.push(h[k]); if (isL) sl.push(l[k]); }
      I.swH[i] = sh.length >= 2 ? [sh.at(-2), sh.at(-1)] : null; I.swL[i] = sl.length >= 2 ? [sl.at(-2), sl.at(-1)] : null; } }
  // 볼린저 폭 백분위(최근 100봉) — 스퀴즈 판정
  I.bbWPct = I.bbW.map((w, i) => { if (w == null || i < 100) return null; let k = 0, m = 0; for (let j = i - 100; j < i; j++) if (I.bbW[j] != null) { m++; if (I.bbW[j] < w) k++; } return m ? k / m : null; });
  return I;
}
const ok = (...xs) => xs.every(x => x != null && Number.isFinite(x));
const lowest = (a, from, to) => { let m = Infinity; for (let j = Math.max(0, from); j <= to; j++) if (a[j] < m) m = a[j]; return m; };
const highest = (a, from, to) => { let m = -Infinity; for (let j = Math.max(0, from); j <= to; j++) if (a[j] > m) m = a[j]; return m; };

// ── 상위 시간대(1H) 추세 바이어스: 추세추종은 상위 추세 방향으로만, 역추세는 강한 상위 추세에 역행 금지 ──
export function prepareHTF(Q, cs) {
  const e50 = Q.computeInd(cs, "ema", { length: 50 }).value, e200 = Q.computeInd(cs, "ema", { length: 200 }).value, adx = Q.computeInd(cs, "adx", { length: 14 }).adx;
  return { t: cs.map(b => +b.t), c: cs.map(b => +b.c), e50, e200, adx, step: cs.length > 1 ? cs[1].t - cs[0].t : 3600000 };
}
export function htfBiasAt(H, t) {
  if (!H) return { bias: 0, adx: null };
  let lo = 0, hi = H.t.length - 1, k = -1;
  while (lo <= hi) { const m = (lo + hi) >> 1; if (H.t[m] + H.step <= t) { k = m; lo = m + 1; } else hi = m - 1; }   // t 이전에 '마감된' 상위봉
  if (k < 0 || !ok(H.e50[k], H.e200[k])) return { bias: 0, adx: null };
  const c = H.c[k], bias = c > H.e200[k] && H.e50[k] > H.e200[k] ? 1 : c < H.e200[k] && H.e50[k] < H.e200[k] ? -1 : 0;
  return { bias, adx: H.adx[k] };
}
export function htfAllows(rule, side, hb) {
  if (!hb) return true;
  if (rule.mode === "counter") return !(hb.bias === -side && (hb.adx ?? 0) > 25);   // 강한 상위 추세에 역행하는 역추세 금지
  return hb.bias === side;                                                           // 추세·돌파·단타 = 상위 추세 방향만
}
// 노이즈 꼬리에 털리지 않게: 손절거리 최소 = ATR × k (시간봉 변동성 반영)
export function atrFloorSL(rule, I, i, side, sl, k = 1.0) {
  const a = I.atr[i]; if (!ok(a)) return sl;
  const minD = a * k, d = Math.abs(I.c[i] - sl);
  return d >= minD ? sl : (side > 0 ? I.c[i] - minD : I.c[i] + minD);
}

// ── 시장 국면: 추세장(상승/하락) · 횡보장 · 수축(돌파대기) · 전환 ──
export function regimeAt(I, i) {
  const adx = I.adx[i], e20 = I.ema20[i], e50 = I.ema50[i], e50p = I.ema50[i - 10], c = I.c[i], wp = I.bbWPct[i];
  if (!ok(adx, e20, e50, e50p)) return { key: "전환", label: "판단중" };
  const slope = (e50 - e50p) / e50p;
  if (adx >= 23 && e20 > e50 && c > e50 && slope > 0) return { key: "상승추세", label: "상승 추세장", adx };
  if (adx >= 23 && e20 < e50 && c < e50 && slope < 0) return { key: "하락추세", label: "하락 추세장", adx };
  if (wp != null && wp < 0.2) return { key: "수축", label: "변동성 수축(돌파 대기)", adx };
  if (adx < 20) return { key: "횡보", label: "횡보장", adx };
  return { key: "전환", label: "전환 구간", adx };
}

// ── 매매법 라이브러리 (사용자 목록 → 실행 규칙). 각 규칙은 마감봉 i 에서 판단, 다음 봉에 진입. ──
// 반환: {side, sl(가격), why} 또는 null. 손절은 구조(스윙 저점/고점·밴드·ATR) 기반 → 프레임워크가 레버리지를 역산.
const buf = (I, i) => (I.atr[i] || 0) * 0.15;
export const LIB = [
  { key: "macd_scalp", mode: "trend", name: "MACD 0선 위 크로스 스캘핑", cat: "단타", tf: "5", rr: 1.5, regimes: ["상승추세", "하락추세", "전환"], hold: 36,
    sig(I, i) { const a = I.macd, s = I.macdS; if (!ok(a[i], s[i], a[i - 1], s[i - 1])) return null;
      if (a[i - 1] <= s[i - 1] && a[i] > s[i] && a[i] > 0 && s[i] > 0 && I.c[i] > I.ema50[i]) return { side: 1, sl: lowest(I.l, i - 8, i) - buf(I, i), why: "MACD 빠른선이 느린선 상향돌파 + 둘 다 0축 위" };
      if (a[i - 1] >= s[i - 1] && a[i] < s[i] && a[i] < 0 && s[i] < 0 && I.c[i] < I.ema50[i]) return { side: -1, sl: highest(I.h, i - 8, i) + buf(I, i), why: "MACD 하향돌파 + 둘 다 0축 아래" };
      return null; },
    exit(I, i, side) { return side > 0 ? (I.macd[i] < I.macdS[i] && I.macd[i - 1] >= I.macdS[i - 1]) : (I.macd[i] > I.macdS[i] && I.macd[i - 1] <= I.macdS[i - 1]); } },
  { key: "ema_pullback", mode: "trend", name: "EMA20 눌림목(추세 조정 매수)", cat: "추세", tf: "15", rr: 2, regimes: ["상승추세", "하락추세"], hold: 32,
    sig(I, i) { if (!ok(I.ema20[i], I.ema50[i], I.atr[i])) return null;
      if (I.ema20[i] > I.ema50[i] && I.l[i] <= I.ema20[i] && I.c[i] > I.ema20[i] && I.c[i] > I.o[i] && I.rsi[i] > 40 && I.rsi[i] < 65) return { side: 1, sl: Math.min(I.l[i], I.l[i - 1]) - buf(I, i), why: "상승추세에서 EMA20 터치 후 양봉 복귀" };
      if (I.ema20[i] < I.ema50[i] && I.h[i] >= I.ema20[i] && I.c[i] < I.ema20[i] && I.c[i] < I.o[i] && I.rsi[i] < 60 && I.rsi[i] > 35) return { side: -1, sl: Math.max(I.h[i], I.h[i - 1]) + buf(I, i), why: "하락추세에서 EMA20 되돌림 후 음봉 복귀" };
      return null; } },
  { key: "bb_squeeze", mode: "trend", name: "볼린저 스퀴즈 돌파(거래량 확인)", cat: "돌파", tf: "15", rr: 2, regimes: ["수축", "전환", "상승추세", "하락추세"], hold: 32,
    sig(I, i) { const wp = I.bbWPct[i - 1]; if (!ok(wp, I.bbU[i], I.bbL[i], I.volMa[i]) || wp > 0.25) return null;
      if (I.c[i] > I.bbU[i] && I.v[i] > I.volMa[i] * 1.5) return { side: 1, sl: I.bbM[i], why: `밴드폭 하위 ${Math.round(wp * 100)}% 수축 후 상단 돌파 + 거래량 ${(I.v[i] / I.volMa[i]).toFixed(1)}배` };
      if (I.c[i] < I.bbL[i] && I.v[i] > I.volMa[i] * 1.5) return { side: -1, sl: I.bbM[i], why: `수축 후 하단 이탈 + 거래량 ${(I.v[i] / I.volMa[i]).toFixed(1)}배` };
      return null; } },
  { key: "rsi_range", mode: "counter", name: "RSI 30/70 레인지 반전", cat: "역추세", tf: "5", rr: 1.5, regimes: ["횡보", "수축"], hold: 36,
    sig(I, i) { const r = I.rsi; if (!ok(r[i], r[i - 1])) return null;
      if (r[i - 1] < 30 && r[i] >= 30) return { side: 1, sl: lowest(I.l, i - 10, i) - buf(I, i), why: "횡보장 RSI 30 상향 복귀" };
      if (r[i - 1] > 70 && r[i] <= 70) return { side: -1, sl: highest(I.h, i - 10, i) + buf(I, i), why: "횡보장 RSI 70 하향 복귀" };
      return null; } },
  { key: "bb_reentry", mode: "counter", name: "볼린저 외부→내부 복귀", cat: "역추세", tf: "15", rr: 1.5, regimes: ["횡보", "전환"], hold: 32,
    sig(I, i) { if (!ok(I.bbL[i], I.bbL[i - 1], I.bbU[i])) return null;
      if (I.c[i - 1] < I.bbL[i - 1] && I.c[i] > I.bbL[i]) return { side: 1, sl: Math.min(I.l[i], I.l[i - 1]) - buf(I, i), why: "하단 밴드 밖 종가 후 안으로 복귀" };
      if (I.c[i - 1] > I.bbU[i - 1] && I.c[i] < I.bbU[i]) return { side: -1, sl: Math.max(I.h[i], I.h[i - 1]) + buf(I, i), why: "상단 밴드 밖 종가 후 안으로 복귀" };
      return null; } },
  { key: "donchian_adx", mode: "trend", name: "돈치안 20 돌파 + ADX>25", cat: "추세", tf: "15", rr: 2.5, regimes: ["상승추세", "하락추세", "전환"], hold: 40,
    sig(I, i) { if (!ok(I.hh20[i - 1], I.ll20[i - 1], I.adx[i], I.atr[i]) || I.adx[i] < 25) return null;
      if (I.c[i] > I.hh20[i - 1]) return { side: 1, sl: I.c[i] - I.atr[i] * 1.5, why: `20봉 고점 돌파 + ADX ${I.adx[i].toFixed(0)}` };
      if (I.c[i] < I.ll20[i - 1]) return { side: -1, sl: I.c[i] + I.atr[i] * 1.5, why: `20봉 저점 이탈 + ADX ${I.adx[i].toFixed(0)}` };
      return null; } },
  { key: "st_ema200", mode: "trend", name: "슈퍼트렌드 전환 + 200EMA", cat: "추세", tf: "15", rr: 2, regimes: ["상승추세", "하락추세", "전환"], hold: 40,
    sig(I, i) { if (!ok(I.stTrend[i], I.stTrend[i - 1], I.ema200[i], I.stLine[i])) return null;
      if (I.stTrend[i - 1] < 0 && I.stTrend[i] > 0 && I.c[i] > I.ema200[i]) return { side: 1, sl: I.stLine[i] - buf(I, i), why: "슈퍼트렌드 상승 전환 + 200EMA 위" };
      if (I.stTrend[i - 1] > 0 && I.stTrend[i] < 0 && I.c[i] < I.ema200[i]) return { side: -1, sl: I.stLine[i] + buf(I, i), why: "슈퍼트렌드 하락 전환 + 200EMA 아래" };
      return null; },
    exit(I, i, side) { return side > 0 ? I.stTrend[i] < 0 : I.stTrend[i] > 0; } },
  { key: "ict_sweep", mode: "counter", name: "ICT 유동성 스윕(터틀수프)", cat: "ICT", tf: "15", rr: 1.8, regimes: ["횡보", "전환", "상승추세", "하락추세", "수축"], hold: 32,
    sig(I, i) { const lv = lowest(I.l, i - 21, i - 1), hv = highest(I.h, i - 21, i - 1); if (!ok(lv, hv, I.atr[i])) return null;
      const body = Math.abs(I.c[i] - I.o[i]), rng = I.h[i] - I.l[i] || 1;
      if (I.l[i] < lv && I.c[i] > lv && I.c[i] > I.o[i] && body / rng > 0.45) return { side: 1, sl: I.l[i] - buf(I, i), why: "20봉 저점 유동성 스윕 후 강한 양봉 회복" };
      if (I.h[i] > hv && I.c[i] < hv && I.c[i] < I.o[i] && body / rng > 0.45) return { side: -1, sl: I.h[i] + buf(I, i), why: "20봉 고점 유동성 스윕 후 강한 음봉 회복" };
      return null; } },
  { key: "ict_ote", mode: "trend", name: "ICT OTE 되돌림(61.8~78.6%)", cat: "ICT", tf: "15", rr: 1.8, regimes: ["상승추세", "하락추세", "전환"], hold: 32,
    sig(I, i) { if (i < 40 || !ok(I.atr[i])) return null;
      // 직전 30봉 임펄스(스윙 저점→고점, 고점이 뒤) + 구조돌파 후, 61.8~78.6% 되돌림 구간에서 반등봉
      let lo = Infinity, lo_i = -1, hi = -Infinity, hi_i = -1;
      for (let j = i - 30; j < i - 2; j++) { if (I.l[j] < lo) { lo = I.l[j]; lo_i = j; } if (I.h[j] > hi) { hi = I.h[j]; hi_i = j; } }
      const leg = hi - lo; if (!(leg > I.atr[i] * 4)) return null;
      if (hi_i > lo_i) { const z1 = hi - leg * 0.618, z2 = hi - leg * 0.786;
        if (I.l[i] <= z1 && I.l[i] >= z2 - I.atr[i] * 0.2 && I.c[i] > I.o[i] && I.c[i] > z1 * 0.999) return { side: 1, sl: z2 - I.atr[i] * 0.4, why: "상승 임펄스 후 OTE(61.8~78.6%) 되돌림 반등" }; }
      if (lo_i > hi_i) { const z1 = lo + leg * 0.618, z2 = lo + leg * 0.786;
        if (I.h[i] >= z1 && I.h[i] <= z2 + I.atr[i] * 0.2 && I.c[i] < I.o[i] && I.c[i] < z1 * 1.001) return { side: -1, sl: z2 + I.atr[i] * 0.4, why: "하락 임펄스 후 OTE 되돌림 반락" }; }
      return null; } },
  { key: "vwap_trend", mode: "trend", name: "VWAP 추세 스캘핑", cat: "단타", tf: "5", rr: 1.8, regimes: ["상승추세", "하락추세"], hold: 36,
    sig(I, i) { const w = I.vwap; if (!ok(w[i], w[i - 6])) return null;
      if (I.c[i] > w[i] && w[i] > w[i - 6] && I.l[i] <= w[i] * 1.0008 && I.c[i] > I.o[i]) return { side: 1, sl: Math.min(I.l[i], w[i]) - buf(I, i) * 2, why: "VWAP 위·상승 중 VWAP 터치 후 양봉" };
      if (I.c[i] < w[i] && w[i] < w[i - 6] && I.h[i] >= w[i] * 0.9992 && I.c[i] < I.o[i]) return { side: -1, sl: Math.max(I.h[i], w[i]) + buf(I, i) * 2, why: "VWAP 아래·하락 중 VWAP 터치 후 음봉" };
      return null; } },
  { key: "zscore_mr", mode: "counter", name: "Z-score 평균회귀(±2)", cat: "역추세", tf: "15", rr: 1.5, regimes: ["횡보"], hold: 32,
    sig(I, i) { const z = (k) => { const m = I.sma20[k], sd = (I.bbU[k] - I.bbM[k]) / 2; return ok(m, sd) && sd > 0 ? (I.c[k] - m) / sd : null; };
      const z0 = z(i - 1), z1 = z(i); if (!ok(z0, z1, I.atr[i])) return null;
      if (z0 < -2 && z1 >= -2) return { side: 1, sl: lowest(I.l, i - 3, i) - I.atr[i] * 0.3, why: `Z ${z0.toFixed(1)}→${z1.toFixed(1)} 평균 쪽 복귀` };
      if (z0 > 2 && z1 <= 2) return { side: -1, sl: highest(I.h, i - 3, i) + I.atr[i] * 0.3, why: `Z +${z0.toFixed(1)}→${z1.toFixed(1)} 평균 쪽 복귀` };
      return null; } },
  { key: "stoch_rev", mode: "counter", name: "스토캐스틱 20/80 교차 반전", cat: "역추세", tf: "15", rr: 1.5, regimes: ["횡보", "수축"], hold: 32,
    sig(I, i) { const k = I.stoK, d = I.stoD; if (!ok(k[i], d[i], k[i - 1], d[i - 1])) return null;
      if (k[i - 1] <= d[i - 1] && k[i] > d[i] && k[i] < 25) return { side: 1, sl: lowest(I.l, i - 8, i) - buf(I, i), why: "%K가 %D 상향교차(20 이하)" };
      if (k[i - 1] >= d[i - 1] && k[i] < d[i] && k[i] > 75) return { side: -1, sl: highest(I.h, i - 8, i) + buf(I, i), why: "%K가 %D 하향교차(80 이상)" };
      return null; } },
  { key: "ema_fan", mode: "trend", name: "EMA 9>50>200 정렬 + 9EMA 터치", cat: "추세", tf: "5", rr: 2, regimes: ["상승추세", "하락추세"], hold: 36,
    sig(I, i) { if (!ok(I.ema9[i], I.ema50[i], I.ema200[i])) return null;
      if (I.ema9[i] > I.ema50[i] && I.ema50[i] > I.ema200[i] && I.l[i] <= I.ema9[i] && I.c[i] > I.ema9[i] && I.c[i] > I.o[i]) return { side: 1, sl: Math.min(I.l[i], I.ema50[i]) - buf(I, i), why: "EMA 정배열 + 9EMA 터치 반등" };
      if (I.ema9[i] < I.ema50[i] && I.ema50[i] < I.ema200[i] && I.h[i] >= I.ema9[i] && I.c[i] < I.ema9[i] && I.c[i] < I.o[i]) return { side: -1, sl: Math.max(I.h[i], I.ema50[i]) + buf(I, i), why: "EMA 역배열 + 9EMA 터치 반락" };
      return null; } },
  { key: "momo_vol", mode: "trend", name: "모멘텀 + 거래량 급증 돌파", cat: "돌파", tf: "5", rr: 1.8, regimes: ["상승추세", "하락추세", "전환", "수축"], hold: 30,
    sig(I, i) { if (!ok(I.hh20[i - 1], I.ll20[i - 1], I.volMa[i], I.roc[i])) return null; const rng = I.h[i] - I.l[i] || 1, pos = (I.c[i] - I.l[i]) / rng;
      if (I.c[i] > I.hh20[i - 1] && I.v[i] > I.volMa[i] * 2 && pos > 0.7 && I.roc[i] > 0) return { side: 1, sl: I.l[i] - buf(I, i), why: `20봉 고점 돌파 + 거래량 ${(I.v[i] / I.volMa[i]).toFixed(1)}배` };
      if (I.c[i] < I.ll20[i - 1] && I.v[i] > I.volMa[i] * 2 && pos < 0.3 && I.roc[i] < 0) return { side: -1, sl: I.h[i] + buf(I, i), why: `20봉 저점 이탈 + 거래량 ${(I.v[i] / I.volMa[i]).toFixed(1)}배` };
      return null; } },
  { key: "swing_st4h", mode: "trend", name: "4H 스윙: 슈퍼트렌드 + 200EMA", cat: "스윙", tf: "240", rr: 2, regimes: ["상승추세", "하락추세", "전환"], hold: 30,
    sig(I, i) { if (!ok(I.stTrend[i], I.stTrend[i - 1], I.ema200[i], I.stLine[i])) return null;
      if (I.stTrend[i - 1] < 0 && I.stTrend[i] > 0 && I.c[i] > I.ema200[i]) return { side: 1, sl: I.stLine[i] - buf(I, i), why: "4시간 슈퍼트렌드 상승 전환 + 200EMA 위" };
      if (I.stTrend[i - 1] > 0 && I.stTrend[i] < 0 && I.c[i] < I.ema200[i]) return { side: -1, sl: I.stLine[i] + buf(I, i), why: "4시간 슈퍼트렌드 하락 전환 + 200EMA 아래" };
      return null; } },
  { key: "macross_4h", mode: "trend", name: "4H 스윙: 10/20 SMA 교차 + ADX", cat: "스윙", tf: "240", rr: 2, regimes: ["상승추세", "하락추세", "전환"], hold: 30,
    sig(I, i) { const a = I.sma10, b = I.sma20; if (!ok(a[i], b[i], a[i - 1], b[i - 1], I.adx[i], I.atr[i]) || I.adx[i] < 20) return null;
      if (a[i - 1] <= b[i - 1] && a[i] > b[i]) return { side: 1, sl: lowest(I.l, i - 6, i) - buf(I, i), why: "10/20 SMA 골든크로스 + ADX>20" };
      if (a[i - 1] >= b[i - 1] && a[i] < b[i]) return { side: -1, sl: highest(I.h, i - 6, i) + buf(I, i), why: "10/20 SMA 데드크로스 + ADX>20" };
      return null; } },
  // ── robobytes/Ultimate-Crypto-Trading-Bot: 스토캐스틱 RSI 교차 · 파라볼릭 SAR 반전 · 다우 이론 HH/HL ──
  { key: "stochrsi_x", mode: "trend", name: "스토RSI 과매도/과매수 교차(추세 방향)", cat: "추세", tf: "60", rr: 2, regimes: ["상승추세", "하락추세", "전환"], hold: 36,
    sig(I, i) { const k = I.srK, d = I.srD; if (!ok(k[i], d[i], k[i - 1], d[i - 1], I.ema50[i])) return null;
      if (k[i - 1] <= d[i - 1] && k[i] > d[i] && k[i - 1] < 20 && I.c[i] > I.ema50[i]) return { side: 1, sl: lowest(I.l, i - 6, i) - buf(I, i), why: `스토RSI K가 20 아래에서 D 상향교차(${k[i].toFixed(0)}) + EMA50 위` };
      if (k[i - 1] >= d[i - 1] && k[i] < d[i] && k[i - 1] > 80 && I.c[i] < I.ema50[i]) return { side: -1, sl: highest(I.h, i - 6, i) + buf(I, i), why: `스토RSI K가 80 위에서 D 하향교차(${k[i].toFixed(0)}) + EMA50 아래` };
      return null; } },
  { key: "psar_flip", mode: "trend", name: "파라볼릭 SAR 반전 + EMA50·ADX", cat: "추세", tf: "60", rr: 2, regimes: ["상승추세", "하락추세", "전환"], hold: 40,
    sig(I, i) { const t = I.psarT; if (!ok(t[i], t[i - 1], I.psar[i], I.ema50[i], I.adx[i]) || I.adx[i] < 18) return null;
      if (t[i - 1] < 0 && t[i] > 0 && I.c[i] > I.ema50[i]) return { side: 1, sl: I.psar[i] - buf(I, i), why: "SAR 점이 가격 아래로 뒤집힘(상승 전환) + EMA50 위" };
      if (t[i - 1] > 0 && t[i] < 0 && I.c[i] < I.ema50[i]) return { side: -1, sl: I.psar[i] + buf(I, i), why: "SAR 점이 가격 위로 뒤집힘(하락 전환) + EMA50 아래" };
      return null; },
    exit(I, i, side) { return ok(I.psarT[i]) && I.psarT[i] === -side; } },
  { key: "dow_hhhl", mode: "trend", name: "다우 이론: 고점·저점 상승(HH/HL) 후 직전 고점 돌파", cat: "추세", tf: "60", rr: 2, regimes: ["상승추세", "하락추세", "전환"], hold: 40,
    sig(I, i) { const H = I.swH[i], L = I.swL[i]; if (!H || !L || !ok(I.atr[i])) return null;
      if (H[1] > H[0] && L[1] > L[0] && I.c[i - 1] <= H[1] && I.c[i] > H[1]) return { side: 1, sl: L[1] - buf(I, i), why: `고점 ${H[0].toFixed(2)}→${H[1].toFixed(2)}·저점 상승 확인 후 직전 고점 종가 돌파` };
      if (H[1] < H[0] && L[1] < L[0] && I.c[i - 1] >= L[1] && I.c[i] < L[1]) return { side: -1, sl: H[1] + buf(I, i), why: `고점·저점 하락(LH/LL) 후 직전 저점 종가 이탈` };
      return null; } },
  // ── beenchangseo/binance-futures-grid-bot: ATR 간격 그리드를 '단일 포지션 + 하드 손절'로 — 횡보장에서 중심선 이탈 1.5칸이면 중심 복귀 노림 ──
  { key: "atr_grid_mr", mode: "counter", name: "ATR 그리드 평균회귀(횡보장·단일 포지션)", cat: "역추세", tf: "60", rr: 1.5, regimes: ["횡보", "수축"], hold: 24,
    sig(I, i) { const m = I.sma20[i], a = I.atr[i]; if (!ok(m, a, I.adx[i]) || I.adx[i] > 22) return null;
      const lv = (I.c[i] - m) / a, lv0 = (I.c[i - 1] - m) / a;
      if (lv0 <= -1.5 && lv > lv0 && I.c[i] > I.o[i]) return { side: 1, sl: I.c[i] - a * 1.2, why: `중심(SMA20)에서 ${(-lv0).toFixed(1)}ATR 아래 그리드 칸 → 반등 양봉` };
      if (lv0 >= 1.5 && lv < lv0 && I.c[i] < I.o[i]) return { side: -1, sl: I.c[i] + a * 1.2, why: `중심에서 ${lv0.toFixed(1)}ATR 위 그리드 칸 → 반락 음봉` };
      return null; },
    exit(I, i, side) { return ok(I.sma20[i]) && (side > 0 ? I.c[i] >= I.sma20[i] : I.c[i] <= I.sma20[i]); } },
  // ── bigpie1367/bitcoin_autotrading_system: 6전략(추세·모멘텀·MA5/20 스윙·0.1% 스캘핑·데이·가격행동 돌파) 가중 투표 앙상블. 가중치는 자체 백테스트(calibrate)에서 최적화 ──
  { key: "bigpie_ens", mode: "trend", name: "6전략 가중 앙상블(가중치 자동 최적화)", cat: "추세", tf: "60", rr: 2, regimes: ["상승추세", "하락추세", "전환", "수축"], hold: 36,
    sig(I, i) { const sc = ensScore(I, i), sp = ensScore(I, i - 1); if (sc == null || sp == null) return null;
      if (sp < ENS.th && sc >= ENS.th) return { side: 1, sl: lowest(I.l, i - 8, i) - buf(I, i), why: `앙상블 점수 ${sc.toFixed(2)} ≥ ${ENS.th} (가중 ${ENS.w.join("/")})` };
      if (sp > -ENS.th && sc <= -ENS.th) return { side: -1, sl: highest(I.h, i - 8, i) + buf(I, i), why: `앙상블 점수 ${sc.toFixed(2)} ≤ -${ENS.th}` };
      return null; } },
];
// 앙상블 구성 6표: [추세, 모멘텀5, MA5/20 스윙, 0.1% 스캘핑, 데이(VWAP), 가격행동 돌파] — 각 ±1, 가중 평균
export const ENS = { w: [1, 1, 1, 1, 1, 1], th: 0.5 };
function ensScore(I, i) {
  if (i < 1 || !ok(I.ema20[i], I.ema50[i], I.ema200[i], I.roc5[i], I.sma5[i], I.sma20[i], I.vwap[i], I.hh20[i - 1], I.ll20[i - 1])) return null;
  const sg = x => x > 0 ? 1 : x < 0 ? -1 : 0, c = I.c[i];
  const v = [sg((I.ema20[i] > I.ema50[i]) + (c > I.ema200[i]) - 1), sg(I.roc5[i]), sg(I.sma5[i] - I.sma20[i]),
    Math.abs(c / I.c[i - 1] - 1) >= 0.001 ? sg(c - I.c[i - 1]) : 0, sg(c - I.vwap[i]), c > I.hh20[i - 1] ? 1 : c < I.ll20[i - 1] ? -1 : 0];
  const W = ENS.w.reduce((a, b) => a + b, 0) || 1; return v.reduce((a, x, k) => a + x * ENS.w[k], 0) / W;
}
// 가중치 최적화: 앞 70%로 후보 가중치를 고르고 뒤 30%(보지 않은 구간)에서도 평균R>0 일 때만 채택 — 아니면 균등 유지
export function tuneEnsemble(sets) {
  const rule = LIB.find(r => r.key === "bigpie_ens"); if (!rule || !sets?.length) return null;
  const C = [[1, 1, 1, 1, 1, 1], [2, 1, 1, 0, 1, 1], [2, 2, 1, 0, 0, 1], [1, 2, 2, 0, 1, 1], [2, 1, 0, 0, 1, 2], [1, 1, 2, 1, 0, 2], [3, 1, 1, 0, 1, 1], [1, 1, 1, 0, 2, 2]];
  const run = (w, part) => { const save = ENS.w; ENS.w = w; const R = [];
    for (const d of sets) { const cut = Math.floor(d.I.n * 0.7); const r = simulate(rule, d.I, d.cs, { sym: d.sym, H: d.H, from: part ? cut : 210, to: part ? null : cut }); R.push(...r.trades.map(t => t.R)); }
    ENS.w = save; return { n: R.length, mean: R.length ? R.reduce((a, b) => a + b, 0) / R.length : -9 }; };
  const scored = C.map(w => ({ w, ...run(w, 0) })).filter(x => x.n >= 8).sort((a, b) => b.mean - a.mean);
  const best = scored[0]; if (!best) return null;
  const oos = run(best.w, 1);
  ENS.w = oos.n >= 4 && oos.mean > 0 ? best.w : [1, 1, 1, 1, 1, 1];
  return { w: ENS.w, is: +best.mean.toFixed(3), oos: +oos.mean.toFixed(3), n: best.n, adopted: ENS.w === best.w };
}
export const LIB_BY_KEY = Object.fromEntries(LIB.map(s => [s.key, s]));

// ══ 🧬 매매법 진화: 개선(손익비·보유기간 조정) · 수정(필터 추가) · 조합(A 신호 + B 확인) ══
// 변형은 직렬화 가능한 '유전자'(gene)로 저장 → buildEvo 가 실행 규칙으로 만든다. 채택은 앞 70% 선택 + 뒤 30%(안 본 구간) 검증 둘 다 통과해야.
export const FILTERS = {
  vol: { ko: "거래량 1.2배↑", f: (I, i) => ok(I.volMa[i]) && I.v[i] > I.volMa[i] * 1.2 },
  adx: { ko: "ADX≥20 추세 확인", f: (I, i) => ok(I.adx[i]) && I.adx[i] >= 20 },
  calm: { ko: "ADX<25 횡보 확인", f: (I, i) => ok(I.adx[i]) && I.adx[i] < 25 },
  rsi: { ko: "RSI 과열 회피", f: (I, i, sd) => ok(I.rsi[i]) && (sd > 0 ? I.rsi[i] < 68 : I.rsi[i] > 32) },
  ema200: { ko: "EMA200 방향 일치", f: (I, i, sd) => ok(I.ema200[i]) && (sd > 0 ? I.c[i] > I.ema200[i] : I.c[i] < I.ema200[i]) },
  st: { ko: "슈퍼트렌드 일치", f: (I, i, sd) => ok(I.stTrend[i]) && Math.sign(I.stTrend[i]) === sd },
  macd: { ko: "MACD 방향 일치", f: (I, i, sd) => ok(I.macd[i], I.macdS[i]) && (sd > 0 ? I.macd[i] > I.macdS[i] : I.macd[i] < I.macdS[i]) },
  vwap: { ko: "VWAP 방향 일치", f: (I, i, sd) => ok(I.vwap[i]) && (sd > 0 ? I.c[i] > I.vwap[i] : I.c[i] < I.vwap[i]) },
  session: { ko: "저유동 시간(UTC 21~01시) 제외", f: (I, i) => { const h = new Date(I.t[i]).getUTCHours(); return !(h >= 21 || h < 1); } },
  bbw: { ko: "스퀴즈(밴드폭 하위 20%) 제외", f: (I, i) => I.bbWPct[i] == null || I.bbWPct[i] > 0.2 },
};
export const geneId = g => [g.base, g.with || "", (g.filters || []).slice().sort().join("+"), g.rr ?? "", g.hold ?? "", g.win ?? ""].join("|");
export function geneName(g) {
  const A = LIB_BY_KEY[g.base], B = g.with ? LIB_BY_KEY[g.with] : null; if (!A) return g.base;
  const tags = [];
  if (B) tags.push(`조합: ${B.name} 확인 ${g.win ?? 3}봉 내`);
  if (g.filters?.length) tags.push("수정: +" + g.filters.map(f => FILTERS[f]?.ko || f).join(" +"));
  if (g.rr != null || g.hold != null) tags.push(`개선: ${g.rr != null ? "손익비 " + g.rr : ""}${g.rr != null && g.hold != null ? "·" : ""}${g.hold != null ? "보유 " + g.hold + "봉" : ""}`);
  return `🧬 ${A.name} [${tags.join(" / ")}]`;
}
export function buildEvo(g) {
  const A = LIB_BY_KEY[g.base], B = g.with ? LIB_BY_KEY[g.with] : null; if (!A || (g.with && !B)) return null;
  const F = (g.filters || []).map(k => FILTERS[k]).filter(Boolean), win = g.win ?? 3;
  return { key: "evo_" + geneId(g).replace(/[^a-z0-9_]+/gi, "_"), name: geneName(g), cat: A.cat, tf: g.tf || "60", mode: A.mode, regimes: A.regimes, exit: A.exit, evo: g,
    rr: g.rr ?? A.rr, hold: g.hold ?? (A.tf === "60" ? A.hold : 48),
    sig(I, i) { const s = A.sig(I, i); if (!s) return null;
      for (const f of F) if (!f.f(I, i, s.side)) return null;
      if (B) { let hit = null; for (let j = i; j >= i - win && !hit; j--) { const b = B.sig(I, j); if (b && b.side === s.side) hit = b; } if (!hit) return null;
        return { ...s, why: `${s.why} + ${B.name} 확인` }; }
      return s; } };
}
const pick = a => a[Math.floor(Math.random() * a.length)];
// sets: [{sym, I, cs, H}] (1시간봉) · seeds: AI가 제안한 유전자 · keep: 이미 채택된 유전자(더 진화시킴)
export function evolve(sets, { seeds = [], keep = [], maxAdopt = 4, budget = 48 } = {}) {
  if (!sets?.length) return { adopted: [], tested: 0 };
  const run = (rule, part) => { const R = [];
    for (const d of sets) { const cut = Math.floor(d.I.n * 0.7); const r = simulate(rule, d.I, d.cs, { sym: d.sym, H: d.H, from: part ? cut : 210, to: part ? null : cut }); for (const t of r.trades) R.push(t.R); }
    return { n: R.length, mean: R.length ? +(R.reduce((a, b) => a + b, 0) / R.length).toFixed(3) : -9 }; };
  const bases = LIB.filter(r => r.tf !== "240");
  const bstat = Object.fromEntries(bases.map(r => [r.key, run(buildEvo({ base: r.key }), 0)]));
  const top = bases.filter(r => bstat[r.key].n >= 10).sort((a, b) => bstat[b.key].mean - bstat[a.key].mean).slice(0, 6).map(r => r.key);
  const FK = Object.keys(FILTERS), seen = new Set(keep.map(geneId)), C = [];
  const add = g0 => { const g = { ...g0 }, A = LIB_BY_KEY[g.base]; if (!A) return;
    if (g.rr === A.rr) delete g.rr; if (g.hold === (A.tf === "60" ? A.hold : 48)) delete g.hold; if (g.filters && !g.filters.length) delete g.filters;   // 부모와 같은 값은 변형이 아님
    if (g.rr == null && g.hold == null && !g.filters && !g.with) return;
    const id = geneId(g); if (!seen.has(id) && LIB_BY_KEY[g.base] && (!g.with || (LIB_BY_KEY[g.with] && g.with !== g.base))) { seen.add(id); C.push(g); } };
  for (const g of seeds) add({ ...g, src: "AI 제안" });
  for (const k of top) {
    add({ base: k, rr: pick([1.5, 2, 2.5, 3].filter(x => x !== LIB_BY_KEY[k].rr)), src: "개선" });
    add({ base: k, hold: pick([24, 36, 48, 72]), rr: pick([1.5, 2, 2.5]), src: "개선" });
    add({ base: k, filters: [pick(FK)], src: "수정" }); add({ base: k, filters: [pick(FK)], src: "수정" });
    { const f1 = pick(FK); add({ base: k, filters: [f1, pick(FK.filter(x => x !== f1))], src: "수정" }); }
  }
  for (let t = 0; t < 10 && top.length > 1; t++) { const a = pick(top), b = pick(bases.map(r => r.key).filter(x => x !== a)); add({ base: a, with: b, win: pick([2, 3, 5]), src: "조합" }); }
  for (const g of keep.slice(0, 4)) {   // 이미 채택된 변형을 한 단계 더: 필터 추가 또는 손익비 조정
    add({ ...g, filters: [...new Set([...(g.filters || []), pick(FK)])], src: "재진화" }); add({ ...g, rr: pick([1.5, 2, 2.5, 3]), src: "재진화" }); }
  const scored = [], sig = x => x.n + ":" + x.mean, sigs = new Set(keep.map(g => { const r = buildEvo(g); return r ? sig(run(r, 0)) : ""; }));
  for (const g of C.slice(0, budget)) { const rule = buildEvo(g); if (!rule) continue; const is = run(rule, 0), b0 = bstat[g.base] || { mean: 0 };
    if (sigs.has(sig(is))) continue;   // 결과가 기존 채택본과 똑같으면(필터가 아무것도 안 거름) 같은 전략 — 제외
    if (is.n >= 15 && is.mean > 0 && is.mean >= b0.mean + 0.03) { sigs.add(sig(is)); scored.push({ g, is }); } }
  scored.sort((a, b) => b.is.mean - a.is.mean);
  const adopted = [];
  for (const x of scored.slice(0, 10)) { if (adopted.length >= maxAdopt) break;
    const oos = run(buildEvo(x.g), 1); if (oos.n >= 8 && oos.mean > 0.05) adopted.push({ gene: { ...x.g, tf: "60" }, is: x.is, oos, base: bstat[x.g.base] }); }
  return { adopted, tested: Math.min(C.length, budget), passedIS: scored.length, top: top.map(k => `${LIB_BY_KEY[k].name} ${bstat[k].mean}R`) };
}

// AI가 개발해 검증 통과한 매매법(spec) → 라이브 규칙으로 변환 (quant.signals 배열 사용, 손절은 1.2ATR 구조)
export function specRule(Q, d) {
  return { key: d.key, name: d.name, cat: "AI개발", tf: d.tf, rr: 1.8, regimes: ["상승추세", "하락추세", "횡보", "수축", "전환"], hold: d.tf === "240" ? 30 : 36, spec: d.spec,
    _cache: null,
    prep(cs) { try { this._cache = Q.signals(this.spec, cs); } catch (e) { this._cache = null; } },
    sig(I, i) { const s = this._cache; if (!s || !ok(I.atr[i])) return null;
      if (s.longEntry[i] && !s.shortEntry[i]) return { side: 1, sl: I.c[i] - I.atr[i] * 1.2, why: `AI 개발 매매법 '${d.name}' 롱 조건 충족` };
      if (s.shortEntry[i] && !s.longEntry[i]) return { side: -1, sl: I.c[i] + I.atr[i] * 1.2, why: `AI 개발 매매법 '${d.name}' 숏 조건 충족` };
      return null; },
    exit(I, i, side) { const s = this._cache; if (!s) return false; return side > 0 ? !!s.longExit[i] : !!s.shortExit[i]; } };
}

// ── 프레임워크 그대로 돌리는 자체 백테스트 (진입=다음봉 시가, 같은 봉에 SL·TP 모두 닿으면 SL 먼저, +1R 본절, 시간손절, 수수료) ──
export function simulate(rule, I, cs, { sym = "BTCUSDT", equity0 = 1000, from = 210, rr = null, H = null, atrK = 1.0, be = 1.0, useExit = true, to = null } = {}) {
  if (rule.prep) rule.prep(cs);
  let eq = equity0, peak = eq, mdd = 0; const trades = [];
  let pos = null;
  const end = Math.min(to ?? I.n - 1, I.n - 1);
  for (let i = from; i < end; i++) {
    if (pos) {
      const hi = I.h[i], lo = I.l[i]; let exitPx = null, why = "";
      const hitSL = pos.side > 0 ? lo <= pos.sl : hi >= pos.sl, hitTP = pos.side > 0 ? hi >= pos.tp : lo <= pos.tp;
      if (hitSL) { exitPx = pos.sl; why = pos.be ? "본절" : "손절"; }
      else if (hitTP) { exitPx = pos.tp; why = "익절"; }
      else if (useExit && rule.exit && rule.exit(I, i, pos.side)) { exitPx = I.c[i]; why = "청산신호"; }
      else if (i - pos.i >= rule.hold) { exitPx = I.c[i]; why = "시간손절"; }
      if (exitPx == null) {   // +1R 도달 → 본절(수수료 포함) 이동
        const fav = pos.side > 0 ? (hi - pos.entry) : (pos.entry - lo);
        if (be && !pos.be && fav >= pos.rDist * be) { pos.sl = pos.side > 0 ? pos.entry * (1 + FW.fee) : pos.entry * (1 - FW.fee); pos.be = true; }
        pos.mfe = Math.max(pos.mfe, fav / pos.rDist);
      } else {
        const pret = (exitPx - pos.entry) / pos.entry * pos.side - FW.fee;
        const pnl = Math.max(-pos.margin, pos.notional * pret);
        eq += pnl; peak = Math.max(peak, eq); mdd = Math.max(mdd, (peak - eq) / peak);
        trades.push({ pnl, R: pnl / pos.risk, why, mfe: +pos.mfe.toFixed(2), t0: cs[pos.i]?.t, t1: cs[i]?.t, side: pos.side, reg: pos.reg });
        pos = null;
      }
      continue;
    }
    const s = rule.sig(I, i); if (!s) continue;
    const reg = regimeAt(I, i); if (rule.regimes && !rule.regimes.includes(reg.key)) continue;
    if (H && !htfAllows(rule, s.side, htfBiasAt(H, cs[i].t))) continue;
    if (atrK) s.sl = atrFloorSL(rule, I, i, s.side, s.sl, atrK);
    const entry = I.o[i + 1]; if (!ok(entry)) continue;
    const plan = frameworkPlan({ sym, entry, side: s.side, slPrice: s.sl, cat: rule.cat, rr: rr ?? rule.rr, riskPct: FW.baseRisk, equity: eq });
    if (!plan || plan.skip) continue;
    pos = { reg: reg.key, side: s.side, entry, sl: plan.sl, tp: plan.tp, margin: plan.margin, notional: plan.notional, risk: plan.risk, rDist: Math.abs(entry - plan.sl), be: false, mfe: 0, i: i + 1 };
  }
  const n = trades.length, wins = trades.filter(t => t.pnl > 0).length, sumR = trades.reduce((a, t) => a + t.R, 0);
  const gp = trades.filter(t => t.pnl > 0).reduce((a, t) => a + t.pnl, 0), gl = -trades.filter(t => t.pnl < 0).reduce((a, t) => a + t.pnl, 0);
  return { n, wins, winRate: n ? Math.round(wins / n * 100) : 0, expR: n ? +(sumR / n).toFixed(3) : 0, pf: gl ? +(gp / gl).toFixed(2) : (gp ? 99 : 0),
    trades, ret: +((eq / equity0 - 1) * 100).toFixed(2), mdd: +(mdd * 100).toFixed(2), byWhy: trades.reduce((m, t) => (m[t.why] = (m[t.why] || 0) + 1, m), {}) };
}

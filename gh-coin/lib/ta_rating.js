// 트레이딩뷰식 '기술적 분석 요약' 점수(Recommend.All/MA/Other)를 우리 캔들로 직접 계산 — 규칙은 MIT 라이브러리 python-tradingview-ta
// (트레이딩뷰 technicals.js 를 옮긴 것)의 판정을 다시 만든 것. tradingview-mcp 는 이 점수를 계산하지 않아 차트 조회 아이디어만 참고.
//   이동평균 15표: EMA·SMA 10/20/30/50/100/200 · 일목 기준선(9,26,52) · VWMA20 · HMA9 — 이평 < 종가면 매수, > 종가면 매도
//   오실레이터 11표: RSI14 · 스토캐스틱(14,3,3) · CCI20 · ADX14 · AO · 모멘텀10 · MACD(12,26,9) · 스토RSI(3,3,14,14) · %R14 · 강세/약세 파워 · UO(7,14,28)
//   그룹 점수 = (매수 − 매도) / 계산된 수 · 종합 = 두 그룹 평균 · 라벨: <−0.5 강한 매도 · <−0.1 매도 · ≤0.1 중립 · ≤0.5 매수 · 그 위 강한 매수
// 그리고 17가지 캔들 패턴(직전 5봉 추세 ±0.5% 기준)도 함께 본다.
const sma = (x, n) => x.map((_, i) => { if (i < n - 1) return null; let s = 0; for (let j = i - n + 1; j <= i; j++){ if (x[j] == null) return null; s += x[j]; } return s / n; });
const ema = (x, n) => { const a = 2 / (n + 1), o = []; let p = null; x.forEach((v, i) => { if (v == null){ o.push(p); return; } p = p == null ? v : a * v + (1 - a) * p; o.push(i < n - 1 ? null : p); }); return o; };
const wma = (x, n) => x.map((_, i) => { if (i < n - 1) return null; let s = 0, w = 0; for (let k = 0; k < n; k++){ const v = x[i - k]; if (v == null) return null; s += v * (n - k); w += n - k; } return s / w; });
const hma = (x, n) => { const h = wma(x, Math.round(n / 2)), f = wma(x, n); return wma(h.map((v, i) => v == null || f[i] == null ? null : 2 * v - f[i]), Math.round(Math.sqrt(n))); };
const rma = (x, n) => { const o = []; let p = null, k = 0, s = 0; x.forEach(v => { if (v == null){ o.push(p); return; } if (p == null){ s += v; k++; if (k === n){ p = s / n; } o.push(p); } else { p = (p * (n - 1) + v) / n; o.push(p); } }); return o; };
const hi = (x, n, i) => Math.max(...x.slice(Math.max(0, i - n + 1), i + 1)), lo = (x, n, i) => Math.min(...x.slice(Math.max(0, i - n + 1), i + 1));
function rsi(c, n = 14){ const g = [null], l = [null]; for (let i = 1; i < c.length; i++){ const d = c[i] - c[i - 1]; g.push(Math.max(d, 0)); l.push(Math.max(-d, 0)); } const ag = rma(g.slice(1), n), al = rma(l.slice(1), n); return [null, ...ag.map((v, i) => v == null || al[i] == null ? null : al[i] === 0 ? 100 : 100 - 100 / (1 + v / al[i]))]; }

export function rating(cs){
  const n = cs.length, i = n - 1; if (n < 210) return null;
  const C = cs.map(b => b.c), H = cs.map(b => b.h), L = cs.map(b => b.l), V = cs.map(b => b.v || 0), close = C[i];
  const ma = [], osc = [], vote = (arr, name, v, val) => arr.push({name, v, val});
  // 이동평균 그룹
  for (const p of [10, 20, 30, 50, 100, 200]){ const e = ema(C, p)[i], s = sma(C, p)[i]; vote(ma, `EMA${p}`, e == null ? null : e < close ? 1 : e > close ? -1 : 0, e); vote(ma, `SMA${p}`, s == null ? null : s < close ? 1 : s > close ? -1 : 0, s); }
  const kijun = (hi(H, 26, i) + lo(L, 26, i)) / 2, tenkanNow = (hi(H, 9, i) + lo(L, 9, i)) / 2, tenkanPrev = (hi(H, 9, i - 1) + lo(L, 9, i - 1)) / 2;
  const spanA = (((hi(H, 9, i - 26) + lo(L, 9, i - 26)) / 2) + ((hi(H, 26, i - 26) + lo(L, 26, i - 26)) / 2)) / 2, spanB = (hi(H, 52, i - 26) + lo(L, 52, i - 26)) / 2;
  // 트레이딩뷰 문서 규칙 그대로: 매수 = 기준선 < 가격 · 전환선이 가격을 아래→위로 교차 · 선행1 > 가격 · 선행1 > 선행2 (매도는 반대)
  const ichi = kijun < close && tenkanPrev < C[i - 1] && tenkanNow > close && spanA > close && spanA > spanB ? 1
             : kijun > close && tenkanPrev > C[i - 1] && tenkanNow < close && spanA < close && spanA < spanB ? -1 : 0;
  vote(ma, "일목 기준선", ichi, kijun);
  const vw = (() => { let s = 0, w = 0; for (let k = i - 19; k <= i; k++){ s += C[k] * V[k]; w += V[k]; } return w ? s / w : null; })(); vote(ma, "VWMA20", vw == null ? null : vw < close ? 1 : vw > close ? -1 : 0, vw);
  const h9 = hma(C, 9)[i]; vote(ma, "HMA9", h9 == null ? null : h9 < close ? 1 : h9 > close ? -1 : 0, h9);
  // 오실레이터 그룹
  const R = rsi(C, 14); vote(osc, "RSI14", R[i] < 30 && R[i - 1] < R[i] ? 1 : R[i] > 70 && R[i - 1] > R[i] ? -1 : 0, R[i]);
  const kRaw = C.map((c, k) => k < 13 ? null : (hi(H, 14, k) - lo(L, 14, k)) ? (c - lo(L, 14, k)) / (hi(H, 14, k) - lo(L, 14, k)) * 100 : 50), K = sma(kRaw, 3), D = sma(K, 3);
  vote(osc, "스토캐스틱", K[i] < 20 && D[i] < 20 && K[i] > D[i] && K[i - 1] < D[i - 1] ? 1 : K[i] > 80 && D[i] > 80 && K[i] < D[i] && K[i - 1] > D[i - 1] ? -1 : 0, K[i]);
  const tp = cs.map(b => (b.h + b.l + b.c) / 3), tpS = sma(tp, 20), cci = tp.map((v, k) => { if (tpS[k] == null) return null; let md = 0; for (let j = k - 19; j <= k; j++) md += Math.abs(tp[j] - tpS[k]); md /= 20; return md ? (v - tpS[k]) / (0.015 * md) : 0; });
  vote(osc, "CCI20", cci[i] < -100 && cci[i] > cci[i - 1] ? 1 : cci[i] > 100 && cci[i] < cci[i - 1] ? -1 : 0, cci[i]);
  const trr = cs.map((b, k) => k ? Math.max(b.h - b.l, Math.abs(b.h - C[k - 1]), Math.abs(b.l - C[k - 1])) : b.h - b.l), pdm = cs.map((b, k) => { if (!k) return 0; const u = b.h - H[k - 1], d = L[k - 1] - b.l; return u > d && u > 0 ? u : 0; }), mdm = cs.map((b, k) => { if (!k) return 0; const u = b.h - H[k - 1], d = L[k - 1] - b.l; return d > u && d > 0 ? d : 0; });
  const at = rma(trr, 14), pdi = rma(pdm, 14).map((v, k) => at[k] ? 100 * v / at[k] : null), mdi = rma(mdm, 14).map((v, k) => at[k] ? 100 * v / at[k] : null), adx = rma(pdi.map((p, k) => p == null || mdi[k] == null || p + mdi[k] === 0 ? 0 : 100 * Math.abs(p - mdi[k]) / (p + mdi[k])), 14);
  vote(osc, "ADX14", adx[i] > 20 && pdi[i - 1] < mdi[i - 1] && pdi[i] > mdi[i] ? 1 : adx[i] > 20 && pdi[i - 1] > mdi[i - 1] && pdi[i] < mdi[i] ? -1 : 0, adx[i]);
  const mid = cs.map(b => (b.h + b.l) / 2), ao = sma(mid, 5).map((v, k) => v == null || sma(mid, 34)[k] == null ? null : v - sma(mid, 34)[k]);
  const a0 = ao[i], a1 = ao[i - 1], a2 = ao[i - 2];
  vote(osc, "AO", (a0 > 0 && a1 < 0) || (a0 > 0 && a1 > 0 && a0 > a1 && a2 > a1) ? 1 : (a0 < 0 && a1 > 0) || (a0 < 0 && a1 < 0 && a0 < a1 && a2 < a1) ? -1 : 0, a0);
  const mom = C.map((c, k) => k >= 10 ? c - C[k - 10] : null); vote(osc, "모멘텀10", mom[i] > mom[i - 1] ? 1 : mom[i] < mom[i - 1] ? -1 : 0, mom[i]);
  const macd = ema(C, 12).map((v, k) => v == null || ema(C, 26)[k] == null ? null : v - ema(C, 26)[k]), sig = ema(macd, 9); vote(osc, "MACD", macd[i] > sig[i] ? 1 : macd[i] < sig[i] ? -1 : 0, macd[i]);
  const srRaw = R.map((v, k) => { if (k < 27 || v == null) return null; const w = R.slice(k - 13, k + 1).filter(x => x != null); const h = Math.max(...w), l = Math.min(...w); return h === l ? 50 : (v - l) / (h - l) * 100; }), sK = sma(srRaw, 3), sD = sma(sK, 3);
  const trendUp = C[i] > sma(C, 50)[i], trendDn = C[i] < sma(C, 50)[i];   // 원본은 추세 정의를 공개하지 않음 → SMA50 위·아래로 대신
  vote(osc, "스토RSI", trendDn && sK[i] < 20 && sD[i] < 20 && sK[i] > sD[i] && sK[i - 1] < sD[i - 1] ? 1 : trendUp && sK[i] > 80 && sD[i] > 80 && sK[i] < sD[i] && sK[i - 1] > sD[i - 1] ? -1 : 0, sK[i]);
  const wr = C.map((c, k) => k < 13 ? null : (hi(H, 14, k) - lo(L, 14, k)) ? (hi(H, 14, k) - c) / (hi(H, 14, k) - lo(L, 14, k)) * -100 : -50);
  vote(osc, "윌리엄스 %R", wr[i] < -80 && wr[i] > wr[i - 1] ? 1 : wr[i] > -20 && wr[i] < wr[i - 1] ? -1 : 0, wr[i]);
  const e13 = ema(C, 13), bull = H.map((h, k) => e13[k] == null ? null : h - e13[k]), bear = L.map((l, k) => e13[k] == null ? null : l - e13[k]);
  vote(osc, "강세·약세 파워", trendUp && bear[i] < 0 && bear[i] > bear[i - 1] ? 1 : trendDn && bull[i] > 0 && bull[i] < bull[i - 1] ? -1 : 0, bull[i] + bear[i]);
  const bp = cs.map((b, k) => k ? b.c - Math.min(b.l, C[k - 1]) : 0), trU = cs.map((b, k) => k ? Math.max(b.h, C[k - 1]) - Math.min(b.l, C[k - 1]) : b.h - b.l);
  const avg = p => { let s1 = 0, s2 = 0; for (let k = i - p + 1; k <= i; k++){ s1 += bp[k]; s2 += trU[k]; } return s2 ? s1 / s2 : 0; };
  const uo = 100 * (4 * avg(7) + 2 * avg(14) + avg(28)) / 7; vote(osc, "UO", uo > 70 ? 1 : uo < 30 ? -1 : 0, uo);
  const grp = arr => { const ok = arr.filter(x => x.v != null); return ok.length ? (ok.filter(x => x.v > 0).length - ok.filter(x => x.v < 0).length) / ok.length : 0; };
  const MA = grp(ma), OS = grp(osc), ALL = (MA + OS) / 2;
  return {all: ALL, ma: MA, osc: OS, label: label(ALL), maLabel: label(MA), oscLabel: label(OS), votes: {ma, osc},
    counts: {buy: [...ma, ...osc].filter(x => x.v > 0).length, sell: [...ma, ...osc].filter(x => x.v < 0).length, neutral: [...ma, ...osc].filter(x => x.v === 0).length}};
}
export function label(v){ return v < -0.5 ? "강한 매도" : v < -0.1 ? "매도" : v <= 0.1 ? "중립" : v <= 0.5 ? "매수" : "강한 매수"; }

/* ---- 캔들 패턴 17종 (직전 5봉 추세 ±0.5%, 강도 0~1) ---- */
export function candles(cs){
  const n = cs.length, out = []; if (n < 8) return out;
  const b = k => cs[n - 1 - k], body = x => Math.abs(x.c - x.o), rng = x => x.h - x.l || 1e-12, up = x => x.c > x.o;
  const trend = (() => { const a = cs[n - 7].c, z = cs[n - 2].c, d = z / a - 1; return d > 0.005 ? 1 : d < -0.005 ? -1 : 0; })();
  const x = b(0), p = b(1), q = b(2), br = body(x) / rng(x), uw = (x.h - Math.max(x.o, x.c)) / rng(x), lw = (Math.min(x.o, x.c) - x.l) / rng(x);
  const add = (name, dir, s) => out.push({name, dir, strength: Math.max(0, Math.min(1, s))});
  if (br <= 0.1) add("도지", 0, 1 - br * 10);
  if (br <= 0.35 && lw >= 2 * br && uw <= 0.1){ if (trend < 0) add("망치형", 1, lw); else if (trend > 0) add("교수형", -1, lw); }
  if (br <= 0.35 && uw >= 2 * br && lw <= 0.1){ if (trend < 0) add("역망치형", 1, uw); else if (trend > 0) add("유성형", -1, uw); }
  if (br >= 0.95) add(up(x) ? "강세 장대봉(마루보주)" : "약세 장대봉(마루보주)", up(x) ? 1 : -1, br);
  if (br > 0.1 && br <= 0.3 && uw >= 0.25 && lw >= 0.25) add("팽이형", 0, 0.5);
  if (up(x) !== up(p) && body(x) > body(p) && Math.max(x.o, x.c) >= Math.max(p.o, p.c) && Math.min(x.o, x.c) <= Math.min(p.o, p.c)) add(up(x) ? "상승 장악형" : "하락 장악형", up(x) ? 1 : -1, Math.min(1, body(x) / (body(p) || 1e-12) / 3));
  if (body(p) / rng(p) >= 0.4 && up(x) !== up(p) && Math.max(x.o, x.c) <= Math.max(p.o, p.c) && Math.min(x.o, x.c) >= Math.min(p.o, p.c)) add(up(x) ? "상승 잉태형" : "하락 잉태형", up(x) ? 1 : -1, 1 - body(x) / (body(p) || 1));
  const pm = (p.o + p.c) / 2;
  if (!up(p) && up(x) && x.o < p.l && x.c > pm && x.c < p.o) add("관통형", 1, (x.c - pm) / (body(p) || 1) * 2);
  if (up(p) && !up(x) && x.o > p.h && x.c < pm && x.c > p.o) add("먹구름형", -1, (pm - x.c) / (body(p) || 1) * 2);
  const qm = (q.o + q.c) / 2;
  if (body(q) / rng(q) >= 0.5 && body(p) / rng(p) <= 0.35){
    if (!up(q) && up(x) && x.c > qm) add("샛별형", 1, 0.8);
    if (up(q) && !up(x) && x.c < qm) add("석별형", -1, 0.8);
  }
  const three = [q, p, x];
  if (three.every(k => up(k) && body(k) / rng(k) >= 0.5) && p.o > Math.min(q.o, q.c) && p.o < Math.max(q.o, q.c) && x.o > Math.min(p.o, p.c) && x.o < Math.max(p.o, p.c)) add("적삼병", 1, 0.9);
  if (three.every(k => !up(k) && body(k) / rng(k) >= 0.5) && p.o > Math.min(q.o, q.c) && p.o < Math.max(q.o, q.c) && x.o > Math.min(p.o, p.c) && x.o < Math.max(p.o, p.c)) add("흑삼병", -1, 0.9);
  return out.map(o => ({...o, trend}));
}

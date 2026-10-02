// 퀀트 리스크 시계열 — gs-quant(goldmansachs) timeseries 라이브러리의 계산 방식을 코인(365일 연속 거래)에 맞게 다시 만든 것.
//   returns(simple|logarithmic) · volatility(연율 %, 창 w) · correlation · beta · zscores · max_drawdown · 역사적 VaR/CVaR · 샤프
// 모든 함수는 숫자 배열을 받는다. 창(window)이 데이터보다 길면 가능한 만큼만 쓴다.
const mean = a => a.reduce((s, x) => s + x, 0) / (a.length || 1);
const sd = a => { if (a.length < 2) return 0; const m = mean(a); return Math.sqrt(a.reduce((s, x) => s + (x - m) ** 2, 0) / (a.length - 1)); };
export function returns(px, type = "simple"){ const r = []; for (let i = 1; i < px.length; i++) if (px[i - 1] > 0 && px[i] > 0) r.push(type === "logarithmic" ? Math.log(px[i] / px[i - 1]) : px[i] / px[i - 1] - 1); return r; }
// 연율 변동성 % — 표준편차 × √(연간 관측 수) × 100 (코인: 일봉 365, 1시간봉 365×24)
export function volatility(px, {w = 30, perYear = 365, type = "logarithmic"} = {}){ const r = returns(px.slice(-(w + 1)), type); return sd(r) * Math.sqrt(perYear) * 100; }
// 지수 가중 변동성 (RiskMetrics 식, λ=0.94)
export function ewmaVol(px, {lambda = 0.94, perYear = 365} = {}){ const r = returns(px, "logarithmic"); let v = r.length ? r[0] ** 2 : 0; for (const x of r) v = lambda * v + (1 - lambda) * x * x; return Math.sqrt(v * perYear) * 100; }
export function correlation(a, b, {w = 30} = {}){ const n = Math.min(a.length, b.length); const ra = returns(a.slice(n - Math.min(n, w + 1))), rb = returns(b.slice(n - Math.min(n, w + 1))); const k = Math.min(ra.length, rb.length); if (k < 3) return null; const x = ra.slice(-k), y = rb.slice(-k), mx = mean(x), my = mean(y); let c = 0, vx = 0, vy = 0; for (let i = 0; i < k; i++){ c += (x[i] - mx) * (y[i] - my); vx += (x[i] - mx) ** 2; vy += (y[i] - my) ** 2; } return vx && vy ? c / Math.sqrt(vx * vy) : null; }
// 베타 = cov(자산, 기준) / var(기준)  (기준 = 비트코인)
export function beta(asset, bench, {w = 30} = {}){ const n = Math.min(asset.length, bench.length); const ra = returns(asset.slice(n - Math.min(n, w + 1))), rb = returns(bench.slice(n - Math.min(n, w + 1))); const k = Math.min(ra.length, rb.length); if (k < 3) return null; const x = ra.slice(-k), y = rb.slice(-k), mx = mean(x), my = mean(y); let c = 0, v = 0; for (let i = 0; i < k; i++){ c += (x[i] - mx) * (y[i] - my); v += (y[i] - my) ** 2; } return v ? c / v : null; }
export function zscore(px, {w = 30} = {}){ const s = px.slice(-w); const d = sd(s); return d ? (s.at(-1) - mean(s)) / d : 0; }
// 최대 낙폭 % (창 안의 고점 대비 최저)
export function maxDrawdown(px, {w = px.length} = {}){ let peak = -Infinity, dd = 0; for (const v of px.slice(-w)){ peak = Math.max(peak, v); dd = Math.min(dd, v / peak - 1); } return dd * 100; }
export function currentDrawdown(px, {w = px.length} = {}){ const s = px.slice(-w); return (s.at(-1) / Math.max(...s) - 1) * 100; }
// 역사적 VaR / CVaR(기대 손실) % — 수익률 분포의 하위 (1-신뢰수준) 분위수
export function historicalVaR(px, {conf = 0.95, w = 365} = {}){ const r = returns(px.slice(-(w + 1))).sort((a, b) => a - b); if (r.length < 20) return null; const i = Math.floor((1 - conf) * r.length); const tail = r.slice(0, Math.max(1, i + 1)); return {var: -r[i] * 100, cvar: -mean(tail) * 100, n: r.length}; }
// 모수(정규) VaR — 평균·표준편차 기반
export function parametricVaR(px, {conf = 0.95, w = 365} = {}){ const r = returns(px.slice(-(w + 1))); if (r.length < 20) return null; const z = conf >= 0.99 ? 2.326 : conf >= 0.975 ? 1.96 : 1.645; return -(mean(r) - z * sd(r)) * 100; }
export function sharpe(px, {perYear = 365, rf = 0} = {}){ const r = returns(px); const s = sd(r); return s ? (mean(r) - rf / perYear) / s * Math.sqrt(perYear) : null; }
// 포트폴리오 VaR (분산-공분산): 비중 w_i(노출 USDT), 각 자산 일간 수익률
export function portfolioVaR(series, weights, {conf = 0.95, w = 90} = {}){
  const keys = Object.keys(weights).filter(k => series[k]); if (!keys.length) return null;
  const R = Object.fromEntries(keys.map(k => [k, returns(series[k].slice(-(w + 1)))])), n = Math.min(...keys.map(k => R[k].length)); if (n < 10) return null;
  let varP = 0;
  for (const a of keys) for (const b of keys){ const x = R[a].slice(-n), y = R[b].slice(-n), mx = mean(x), my = mean(y); let c = 0; for (let i = 0; i < n; i++) c += (x[i] - mx) * (y[i] - my); varP += weights[a] * weights[b] * c / (n - 1); }
  const z = conf >= 0.99 ? 2.326 : 1.645; return z * Math.sqrt(Math.max(0, varP));   // USDT
}

// 견고성 검사 — Vibe-Trading(MIT) 의 검증 단계(거래 순서 뒤섞기 순열 검정 · 부트스트랩 샤프 구간 · 여러 구간 워크포워드)를 다시 만든 것.
// "이 성과가 운인가?"를 숫자로: 거래 손익의 부호를 무작위로 뒤집어(무작위 방향 귀무가설) 1000번 다시 만든 샤프가
// 실제 샤프 이상인 비율 = p값. p > 0.05 면 '운일 가능성이 크다'로 본다.
let s = 987654321; const rnd = () => (s = (s * 16807) % 2147483647) / 2147483647;
const sharpeOf = a => { const n = a.length; if (n < 2) return 0; const m = a.reduce((x, y) => x + y, 0) / n, sd = Math.sqrt(a.reduce((x, y) => x + (y - m) ** 2, 0) / (n - 1)); return sd ? m / sd * Math.sqrt(n) : 0; };
export function permutationTest(pnls, {iters = 1000, seed = 7} = {}){
  s = seed; const actual = sharpeOf(pnls); if (pnls.length < 5) return {p: null, actual, n: pnls.length};
  let ge = 0; for (let k = 0; k < iters; k++){ const sh = sharpeOf(pnls.map(x => rnd() < 0.5 ? -x : x)); if (sh >= actual) ge++; }
  return {p: ge / iters, actual, n: pnls.length, luck: ge / iters > 0.05};
}
export function bootstrapSharpe(pnls, {iters = 1000, seed = 11} = {}){
  s = seed; const n = pnls.length; if (n < 5) return null; const v = [];
  for (let k = 0; k < iters; k++){ const b = []; for (let j = 0; j < n; j++) b.push(pnls[Math.floor(rnd() * n)]); v.push(sharpeOf(b)); }
  v.sort((a, b) => a - b); return {lo: v[Math.floor(iters * 0.05)], mid: v[Math.floor(iters * 0.5)], hi: v[Math.floor(iters * 0.95)]};
}
// 여러 구간 워크포워드: 데이터를 k 조각으로 나눠 각 조각이 이익인지 (Q: quant.js)
export function multiWindow(Q, spec, cs, k = 5){
  const out = [], len = Math.floor(cs.length / k);
  for (let j = 0; j < k; j++){ const part = cs.slice(j * len, (j + 1) * len); if (part.length < 60) continue; try { const r = Q.backtest(spec, part).stats; out.push({j: j + 1, ret: r.total_return_pct, n: r.trades, pf: r.profit_factor}); } catch(e){ out.push({j: j + 1, err: e.message}); } }
  return {windows: out, positive: out.filter(x => x.ret > 0).length, total: out.length};
}
// 블록 부트스트랩 몬테카를로(개념: tradeblocks monte-carlo · cubexch backtester 관문 — 코드 복사 없음):
//   거래 순서를 블록(길이 ≈ ∛N, 연속 손익의 뭉침을 보존)째 무작위로 이어 붙여 1000번 다시 굴린다 → 자본이 50% 아래로 떨어질 확률(pRuin) · 낙폭 95백분위.
//   관문(hygiene): pRuin > 50% 탈락 · > 5% 경고 · 낙폭 95백분위 > 30% 경고. 거래 손익은 '그 거래 직전 자본 대비 비율'로 바꿔 복리로 굴린다.
export function ruinMC(bt, {iters = 1000, seed = 13, ruin = 0.5} = {}){
  const T = bt?.trades || [], n = T.length; if (n < 10) return null;
  let eq = bt.equity?.[0]?.v || 1000; const r = []; for (const t of T){ r.push(eq > 0 ? (+t.pnl || 0) / eq : 0); eq += +t.pnl || 0; }
  s = seed; const L = Math.max(1, Math.round(Math.cbrt(n))), dds = []; let ruined = 0;
  for (let k = 0; k < iters; k++){ let e = 1, pk = 1, mdd = 0, hit = false, m = 0;
    while (m < n){ const st = Math.floor(rnd() * n); for (let j = 0; j < L && m < n; j++, m++){ e = Math.max(0, e * (1 + r[(st + j) % n])); pk = Math.max(pk, e); mdd = Math.max(mdd, pk > 0 ? 1 - e / pk : 1); if (e <= ruin) hit = true; } }
    if (hit) ruined++; dds.push(mdd); }
  dds.sort((a, b) => a - b); return {n, block: L, pRuin: ruined / iters, dd95: +(dds[Math.floor(iters * 0.95)] * 100).toFixed(1)};
}
// 운 보정 기준선(개념: tradeblocks parameter-study-selection — K개 중 '가장 좋은 것'을 고르면 운만으로도 기대 최댓값이 0보다 크다):
//   E[max of K 표준정규] ≈ (1−γ)Φ⁻¹(1−1/K) + γΦ⁻¹(1−1/(Ke)), γ=0.5772. 평균 R 이 (표준편차/√n)×이 값 보다 낮으면 '운 범위'.
const invN = p => { const a = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.357751867269, -30.66479806614716, 2.506628277459239], b = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572], c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783], d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416];
  const q = p < 0.02425 ? Math.sqrt(-2 * Math.log(p)) : p > 1 - 0.02425 ? Math.sqrt(-2 * Math.log(1 - p)) : null;
  if (p < 0.02425) return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
  if (p > 1 - 0.02425) return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
  const x = p - 0.5, r2 = x * x; return (((((a[0] * r2 + a[1]) * r2 + a[2]) * r2 + a[3]) * r2 + a[4]) * r2 + a[5]) * x / (((((b[0] * r2 + b[1]) * r2 + b[2]) * r2 + b[3]) * r2 + b[4]) * r2 + 1); };
export function expMaxZ(K){ if (K < 2) return 0; const g = 0.5772156649; return (1 - g) * invN(1 - 1 / K) + g * invN(1 - 1 / (K * Math.E)); }
export const luckBar = (K, sd, n) => n > 1 ? sd / Math.sqrt(n) * expMaxZ(K) : Infinity;
// runs 검정(Wald–Wolfowitz, 개념: tradeblocks streak-analysis): 이익/손실 순서에서 '같은 결과가 이어지는 묶음' 수가 무작위보다 적으면(z<0) 연속이 뭉친다
export function runsTest(seq){ const n = seq.length, n1 = seq.filter(Boolean).length, n2 = n - n1; if (n < 20 || !n1 || !n2) return null;
  let runs = 1; for (let k = 1; k < n; k++) if (seq[k] !== seq[k - 1]) runs++;
  const mu = 2 * n1 * n2 / n + 1, v = (mu - 1) * (mu - 2) / (n - 1), z = v > 0 ? (runs - mu) / Math.sqrt(v) : 0;
  let l = 0, ll = 0; for (let k = 1; k < n; k++) if (!seq[k - 1]) { l++; if (!seq[k]) ll++; }
  return {n, runs, expected: +mu.toFixed(1), z: +z.toFixed(2), lossRate: +(n2 / n * 100).toFixed(1), lossAfterLoss: l ? +(ll / l * 100).toFixed(1) : null}; }
// 생성 전략 위생 검사 (Vibe-Trading 하드 관문): 거래 0건·NaN 자산 금지, 첫 거래가 너무 늦음·자본 사용 적음·끝까지 열린 포지션 경고
export function hygiene(bt){
  const w = [], f = [];
  if (!bt.trades.length) f.push("거래 0건");
  if (bt.equity.some(p => !Number.isFinite(p.v))) f.push("자산 곡선에 NaN");
  if (bt.trades.length && bt.equity.length && bt.trades[0].entryT - bt.equity[0].t > 2 * 365 * 864e5) w.push("첫 거래가 2년 넘게 지나서 나옴");
  if ((bt.stats.exposure_pct ?? 100) < 5) w.push(`시장 노출 ${bt.stats.exposure_pct}% (거의 안 들어감)`);
  if (bt.trades.at(-1)?.reason === "end_of_test") w.push("마지막 포지션이 시험 끝까지 열려 있었음");
  let mc = null; try { mc = ruinMC(bt); } catch(e){}
  // 실거래 기준(cubexch)은 5% 이하지만, 팀 매매법은 20배 이상 프레임워크라 이익 난 백테스트도 12~22% 가 나온다(2026-10-06 뼈대 48개 중 5% 이하 3개).
  //   → 데모 관문은 '절반 넘는 확률로 반토막'만 탈락, 5% 초과는 경고로 보여 준다.
  if (mc && mc.pRuin > 0.5) f.push(`몬테카를로 파산 확률 ${(mc.pRuin * 100).toFixed(0)}%(자본 50% 아래, 거래 순서 1000번 섞기)`);
  else if (mc && mc.pRuin > 0.05) w.push(`몬테카를로 파산 확률 ${(mc.pRuin * 100).toFixed(0)}% — 실거래 기준(5%) 초과`);
  if (mc && mc.dd95 > 30) w.push(`몬테카를로 낙폭 95백분위 ${mc.dd95}%`);
  return {ok: !f.length, fails: f, warns: w, mc};
}

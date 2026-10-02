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
// 생성 전략 위생 검사 (Vibe-Trading 하드 관문): 거래 0건·NaN 자산 금지, 첫 거래가 너무 늦음·자본 사용 적음·끝까지 열린 포지션 경고
export function hygiene(bt){
  const w = [], f = [];
  if (!bt.trades.length) f.push("거래 0건");
  if (bt.equity.some(p => !Number.isFinite(p.v))) f.push("자산 곡선에 NaN");
  if (bt.trades.length && bt.equity.length && bt.trades[0].entryT - bt.equity[0].t > 2 * 365 * 864e5) w.push("첫 거래가 2년 넘게 지나서 나옴");
  if ((bt.stats.exposure_pct ?? 100) < 5) w.push(`시장 노출 ${bt.stats.exposure_pct}% (거의 안 들어감)`);
  if (bt.trades.at(-1)?.reason === "end_of_test") w.push("마지막 포지션이 시험 끝까지 열려 있었음");
  return {ok: !f.length, fails: f, warns: w};
}

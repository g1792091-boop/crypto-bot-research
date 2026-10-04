// 다윈주의 전략 진화 — 잘하는 전략을 '변이'시켜 후손을 만들고, 백테스트로 부모보다 나은 후손만 살린다.
// 아이디어 출처(코드 복사 없이 개념만 재구현): 0xSanei/darwinia(적대적 자기대국·약자도태),
//   chrisworsey55/atlas-gic(샤프 기반 프롬프트 변이·자기개선 루프), cubexch/ai-fund(KPI 해고).
// 전부 가상(데모) 자금 위에서만 동작 — 실자금·실지갑·실주문과 무관.

// 전략 스펙을 조금 흔든다(지표 기간·위험값·조건 임계값). 시드로 재현 가능.
export function mutate(spec, seed = Date.now()) {
  let r = (seed >>> 0) || 1;
  const rnd = () => { r = (r * 1664525 + 1013904223) >>> 0; return r / 4294967296; };
  const jig = (v, lo, hi, amt = 0.25) => Math.max(lo, Math.min(hi, v * (1 - amt + rnd() * amt * 2)));
  const m = JSON.parse(JSON.stringify(spec));
  m.name = String(spec.name || "전략").replace(/\s·진화\d*$/, "") + " ·진화" + (1 + Math.floor(rnd() * 9));
  for (const ind of m.indicators || []) {
    if (Number.isFinite(ind.length)) ind.length = Math.max(2, Math.round(jig(ind.length, 2, 400)));
    if (Number.isFinite(ind.mult)) ind.mult = +jig(ind.mult, 0.2, 10).toFixed(2);
  }
  const rk = m.risk || (m.risk = {});
  if (Number.isFinite(rk.leverage)) rk.leverage = Math.max(1, Math.min(20, Math.round(jig(rk.leverage, 1, 20))));
  for (const k of ["stop_loss_pct", "take_profit_pct", "trailing_stop_pct"]) if (Number.isFinite(rk[k])) rk[k] = +jig(rk[k], 0.3, 50).toFixed(1);
  for (const g of ["long_entry", "short_entry", "long_exit", "short_exit"])
    for (const c of (m[g]?.conditions || [])) if (typeof c.right === "number") c.right = +jig(c.right, c.right * 0.5, c.right * 1.5, 0.2).toFixed(2);
  return m;
}

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
  const lev20 = Number.isFinite(rk.leverage) && rk.leverage >= 20;   // 청산공식 20x+ 프레임워크 전략은 레버리지를 손절에서 다시 역산
  if (Number.isFinite(rk.leverage) && !lev20) rk.leverage = Math.max(1, Math.min(20, Math.round(jig(rk.leverage, 1, 20))));
  for (const k of ["stop_loss_pct", "take_profit_pct", "trailing_stop_pct"]) if (Number.isFinite(rk[k])) rk[k] = +jig(rk[k], 0.3, 50).toFixed(1);
  if (lev20 && rk.stop_loss_pct > 0){ rk.stop_loss_pct = Math.min(2, rk.stop_loss_pct); rk.leverage = Math.min(100, Math.max(20, Math.floor(40 / rk.stop_loss_pct))); }
  for (const g of ["long_entry", "short_entry", "long_exit", "short_exit"])
    for (const c of (m[g]?.conditions || [])) if (typeof c.right === "number") c.right = +jig(c.right, c.right * 0.5, c.right * 1.5, 0.2).toFixed(2);
  return m;
}

// ── 수정: 검증된 필터를 진입 조건에 덧붙인다 (진입 logic 이 all 일 때만 — any 면 의미가 바뀌므로 하지 않음) ──
export const SPEC_FILTERS = {
  adx: {ko: "ADX>20 추세 확인", ind: {id: "fx_adx", type: "adx", length: 14}, long: {left: "fx_adx.adx", op: ">", right: "20"}, short: {left: "fx_adx.adx", op: ">", right: "20"}},
  ema200: {ko: "EMA200 방향 일치", ind: {id: "fx_e200", type: "ema", length: 200}, long: {left: "close", op: ">", right: "fx_e200"}, short: {left: "close", op: "<", right: "fx_e200"}},
  vol: {ko: "거래량 1.2배↑", ind: {id: "fx_vma", type: "volume_sma", length: 20}, long: {left: "volume", op: ">", right: "fx_vma*1.2"}, short: {left: "volume", op: ">", right: "fx_vma*1.2"}},
  st: {ko: "슈퍼트렌드 일치", ind: {id: "fx_st", type: "supertrend", length: 10, mult: 3}, long: {left: "close", op: ">", right: "fx_st.line"}, short: {left: "close", op: "<", right: "fx_st.line"}},
  rsi: {ko: "RSI 과열 회피", ind: {id: "fx_rsi", type: "rsi", length: 14}, long: {left: "fx_rsi", op: "<", right: "68"}, short: {left: "fx_rsi", op: ">", right: "32"}},
};
const isAll = g => g && (String(g.logic ?? "all").toLowerCase() === "all" || g.logic === "and");
export function addFilter(spec, key){
  const F = SPEC_FILTERS[key]; if (!F) return null;
  const m = JSON.parse(JSON.stringify(spec));
  if ((m.indicators || []).some(i => i.id === F.ind.id)) return null;
  let touched = 0;
  for (const [g, c] of [["long_entry", F.long], ["short_entry", F.short]]) if (m[g]?.conditions?.length && isAll(m[g])){ m[g].conditions.push({...c}); touched++; }
  if (!touched) return null;
  m.indicators = [...(m.indicators || []), {...F.ind}];
  m.name = `${String(spec.name || "전략").slice(0, 40)} +${F.ko}`;
  return m;
}
// ── 개선: 손익비 조정 (익절을 늘리거나 손절을 좁힘. 20x+ 전략은 레버리지 재역산) ──
export function tweakRR(spec, kTp = 1.5, kSl = 1){
  const m = JSON.parse(JSON.stringify(spec)), rk = m.risk || (m.risk = {});
  if (!(rk.take_profit_pct > 0) && !(rk.stop_loss_pct > 0)) return null;
  if (rk.take_profit_pct > 0) rk.take_profit_pct = +(rk.take_profit_pct * kTp).toFixed(2);
  if (rk.stop_loss_pct > 0) rk.stop_loss_pct = +(rk.stop_loss_pct * kSl).toFixed(2);
  if (rk.leverage >= 20 && rk.stop_loss_pct > 0) rk.leverage = Math.min(100, Math.max(20, Math.floor(40 / rk.stop_loss_pct)));
  m.name = `${String(spec.name || "전략").slice(0, 40)} ·손익비조정`;
  return m;
}
// ── 조합: 두 매매법의 진입 조건을 모두 만족할 때만 진입(AND). B 의 지표 id 는 b_ 접두사로 바꿔 충돌 방지. 청산·리스크는 A 것을 쓴다 ──
export function combine(a, b){
  if (!a || !b) return null;
  const A = JSON.parse(JSON.stringify(a)), B = JSON.parse(JSON.stringify(b));
  const ids = (B.indicators || []).map(i => i.id).filter(Boolean).sort((x, y) => y.length - x.length);
  if (ids.some(id => !/^\w+$/.test(id))) return null;   // 단순 id 만 안전하게 바꿀 수 있음
  const ren = v => typeof v !== "string" ? v : ids.reduce((s, id) => s.replace(new RegExp("(^|[^\\w.])" + id + "(?!\\w)", "g"), "$1b_" + id), v);
  for (const ind of B.indicators || []){ ind.id = "b_" + ind.id; if (typeof ind.expr === "string") ind.expr = ren(ind.expr); }
  let joined = 0;
  for (const g of ["long_entry", "short_entry"]){
    const ca = A[g], cb = B[g];
    if (ca?.conditions?.length && cb?.conditions?.length && isAll(ca) && isAll(cb)){ ca.conditions.push(...cb.conditions.map(c => ({...c, left: ren(c.left), right: ren(c.right)}))); joined++; }
    else if (ca?.conditions?.length && cb?.conditions?.length) delete A[g];   // 한쪽이 any 면 합칠 수 없으니 그 방향은 쉰다
  }
  if (!joined) return null;
  A.indicators = [...(A.indicators || []), ...(B.indicators || [])];
  A.name = `${String(a.name || "A").slice(0, 26)} × ${String(b.name || "B").slice(0, 26)}`;
  return A;
}

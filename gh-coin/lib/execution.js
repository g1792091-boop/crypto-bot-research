// 주문 전 점검·체결 계획 — nautilus_trader(LGPL, 규칙만 재구현) 의 RiskEngine·TWAP·고정위험 사이저와
// vnpy(MIT) 리스크 매니저(주문 흐름·크기·일일 거래·활성 주문·취소 한도)를 '점검표'로 다시 만든 것.
// ⚠ 실제 주문은 여전히 nuri-ai/live.js(보호 파일)의 한도·승인 안에서만 나간다. 여기는 그 앞에서 '왜 안 되는지'를 미리 보여 주는 점검·계획용이다.
export const STATES = {ACTIVE: "정상(모든 주문)", REDUCING: "축소만(포지션 줄이는 주문만)", HALTED: "정지(취소만)"};
// 상태 결정: 하루 손실 한도 넘음 → REDUCING (보호 손절은 계속), 긴급 정지 → HALTED
export function tradingState({halted = false, dayLoss = 0, dayLossCap = 20} = {}){ return halted ? "HALTED" : dayLoss >= dayLossCap ? "REDUCING" : "ACTIVE"; }
const win = {submit: [], trades: []};
// order: {side:+1|-1, qty, price, notional, reduceOnly, symbol}, ctx: {state, position(+/-qty), rules:{tick, step, minQty, maxQty, minNotional}, limits:{maxNotional, maxPositions, openPositions, maxSubmitPerSec, maxTradesPerDay, tradesToday}}
export function preTradeCheck(order, ctx = {}){
  const L = {maxNotional: 50, maxPositions: 2, maxSubmitPerSec: 10, maxTradesPerDay: 30, ...(ctx.limits || {})}, R = ctx.rules || {}, st = ctx.state || "ACTIVE", pos = +ctx.position || 0;
  const checks = [], add = (id, ok, text) => checks.push({id, ok, text});
  const reduces = pos !== 0 && Math.sign(order.side) === -Math.sign(pos) && Math.abs(order.qty) <= Math.abs(pos);
  add("reduce_only", !order.reduceOnly || reduces, "축소 전용 주문이 포지션을 늘리지 않음");
  add("price_positive", !(order.price <= 0), "가격 > 0");
  if (R.tick) add("price_precision", Math.abs(order.price / R.tick - Math.round(order.price / R.tick)) < 1e-6, `가격 단위 ${R.tick}`);
  if (R.step) add("qty_precision", Math.abs(order.qty / R.step - Math.round(order.qty / R.step)) < 1e-6, `수량 단위 ${R.step}`);
  if (R.minQty) add("min_qty", order.qty >= R.minQty, `최소 수량 ${R.minQty}`);
  if (R.maxQty) add("max_qty", order.qty <= R.maxQty, `최대 수량 ${R.maxQty}`);
  const notional = order.notional ?? order.qty * order.price;
  add("max_notional", notional <= L.maxNotional + 1e-9, `주문당 최대 ${L.maxNotional} USDT (지금 ${notional.toFixed(2)})`);
  if (R.minNotional) add("min_notional", notional >= R.minNotional, `거래소 최소 주문 ${R.minNotional} USDT`);
  add("positions", reduces || (L.openPositions ?? 0) < L.maxPositions, `동시 포지션 ${L.maxPositions}개까지`);
  add("trading_state", st === "ACTIVE" || (st === "REDUCING" && reduces), `거래 상태: ${STATES[st]}`);
  const now = Date.now(); win.submit = win.submit.filter(t => now - t < 1000);
  add("submit_rate", win.submit.length < L.maxSubmitPerSec, `초당 주문 ${L.maxSubmitPerSec}건 이하 (vnpy 주문 흐름 한도)`);
  add("trades_today", (L.tradesToday ?? 0) < L.maxTradesPerDay, `하루 거래 ${L.maxTradesPerDay}건 이하`);
  const fail = checks.find(c => !c.ok);
  if (!fail) win.submit.push(now);
  return {ok: !fail, reason: fail ? fail.id : null, text: fail ? fail.text : "통과", checks, state: st};
}
// 고정 위험 사이저: 수량 = 자본 × 위험% × (1 − 2×수수료) / |진입 − 손절|, 수량 단위로 내림, 상한 적용
export function fixedRiskQty({equity, riskPct = 1, entry, stop, feePct = 0.04, step = 0, maxNotional = Infinity}){
  const d = Math.abs(entry - stop); if (!(d > 0)) return 0;
  let q = equity * riskPct / 100 * (1 - 2 * feePct / 100) / d;
  q = Math.min(q, maxNotional / entry);
  return step ? Math.floor(q / step + 1e-9) * step : q;
}
// TWAP 계획: 기간/간격 = 조각 수, 조각은 수량 단위로 자르고 마지막 조각은 남은 전부. 조각이 최소 수량보다 작으면 한 번에.
export function twapPlan({qty, horizonSec = 600, intervalSec = 60, step = 0, minQty = 0, start = Date.now()}){
  const n = Math.max(1, Math.floor(horizonSec / intervalSec)), slice = step ? Math.floor(qty / n / step) * step : qty / n;
  if (!(slice > 0) || slice < minQty) return [{at: start, qty}];
  const out = []; let left = qty;
  for (let k = 0; k < n; k++){ const q = k === n - 1 ? left : slice; out.push({at: start + k * intervalSec * 1000, qty: +q.toFixed(8)}); left -= q; }
  return out;
}
// 아이스버그 계획 (vnpy): 보이는 크기만 내고, 체결되면 다음 조각
export function icebergPlan({qty, display}){ const out = []; let left = qty; while (left > 1e-12){ const q = Math.min(display, left); out.push(+q.toFixed(8)); left -= q; } return out; }

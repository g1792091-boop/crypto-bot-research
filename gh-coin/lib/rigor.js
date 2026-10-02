// 트레이딩 리거(trading rigor) — 결정론적 포지션 사이징·리스크 계산기.
// TLSRUF/ai-trader-team 의 tools/trading_rigor.py (MIT) 를 GH Coin 브라우저(바닐라 JS)로 '실제 이식'한 것.
// 원본은 Python 표준 라이브러리(decimal)만 썼고, 여기서는 같은 공식·반올림(ROUND_HALF_EVEN)·검증 규칙을 그대로 옮겼다.
// LLM 서술과 계산을 분리해 단위 혼동·부동소수 오차로 인한 실수를 막는 것이 목적이다. (출처: THIRD_PARTY.md)

// 소수 자릿수 반올림 — Python Decimal.quantize 기본값(ROUND_HALF_EVEN, 은행가 반올림)과 맞춘다.
function q(v, dp){
  if (!Number.isFinite(v)) return v;
  const f = 10 ** dp, x = v * f, r = Math.round(x);
  const out = (Math.abs(x - Math.trunc(x) - 0.5) < 1e-9) ? (Math.floor(x) % 2 === 0 ? Math.floor(x) : Math.ceil(x)) : r;
  return out / f;
}
const num = v => { const n = Number(v); if (!Number.isFinite(n)) throw new Error(`'${v}'을(를) 숫자로 변환할 수 없습니다.`); return n; };

// 여러 출처 값 교차검증 — 중위수 대비 1% 초과 편차를 경고
export function crossValidate(field, values){
  const ents = Object.entries(values || {}).map(([k, v]) => [k, num(v)]);
  if (ents.length < 2) throw new Error("교차검증에는 최소 2개 이상의 독립 출처가 필요합니다.");
  const sorted = ents.map(e => e[1]).sort((a, b) => a - b), n = sorted.length, mid = n >> 1;
  const median = n % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
  const sources = {}, warnings = [];
  for (const [src, val] of ents){
    const dev = median === 0 ? (val === 0 ? 0 : 999.99) : Math.abs((val - median) / median) * 100;
    sources[src] = {value: val, deviation_pct: q(dev, 2)};
    if (dev > 1) warnings.push(`⚠️ ${src}: ${field} 값이 중위수 대비 ${q(dev, 2)}% 벗어남 (값=${val})`);
  }
  return {field, median, sources, warnings};
}

// 포지션 크기: 계좌·허용 리스크%·진입·손절 → 리스크 금액/손절폭/수량/명목가/계좌 대비 %
export function positionSize(account, riskPct, entry, stop){
  const a = num(account), r = num(riskPct), e = num(entry), s = num(stop);
  if (e === s) throw new Error("진입가와 손절가가 같으면 손절 폭이 0이 되어 계산할 수 없습니다.");
  if (a <= 0) throw new Error("계좌 규모는 0보다 커야 합니다.");
  if (r <= 0) throw new Error("허용 리스크 비율은 0보다 커야 합니다.");
  const riskAmount = a * (r / 100), stopDistance = Math.abs(e - s), shares = riskAmount / stopDistance, positionValue = shares * e;
  return {risk_amount: q(riskAmount, 2), stop_distance: stopDistance, shares: q(shares, 4), position_value: q(positionValue, 2), position_pct_of_account: q(positionValue / a * 100, 2)};
}

// 켈리 기준: 승률·평균승리·평균손실 → full/half/quarter 켈리 %, 우위 여부
export function kellyCriterion(winRatePct, avgWin, avgLoss){
  const wr = num(winRatePct), aw = num(avgWin), al = num(avgLoss);
  if (!(wr > 0 && wr < 100)) throw new Error("승률은 0%보다 크고 100%보다 작아야 합니다.");
  if (aw <= 0 || al <= 0) throw new Error("평균 승리 금액과 평균 손실 금액은 모두 0보다 커야 합니다 (손실은 절댓값으로 입력).");
  const p = wr / 100, qq = 1 - p, b = aw / al, full = p - qq / b, warnings = [], hasEdge = full > 0;
  if (!hasEdge) warnings.push(`⚠️ 켈리 비율이 ${q(full * 100, 2)}%로 0 이하입니다 — 이 승률/손익비 조합에는 통계적 우위가 없어 베팅하지 않는 것이 최적입니다.`);
  return {win_rate_pct: wr, payoff_ratio: q(b, 2), full_kelly_pct: q(full * 100, 2), half_kelly_pct: q(full * 100 / 2, 2), quarter_kelly_pct: q(full * 100 / 4, 2), has_edge: hasEdge, warnings};
}

// 리스크·리워드 비율 (진입 전 계획)
export function riskReward(entry, stop, target){
  const e = num(entry), s = num(stop), t = num(target), risk = Math.abs(e - s), reward = Math.abs(t - e);
  if (risk === 0) throw new Error("진입가와 손절가가 같으면 리스크가 0이 되어 비율을 계산할 수 없습니다.");
  return {direction: t > e ? "long" : "short", risk, reward, risk_reward_ratio: q(reward / risk, 2)};
}

// 실현 손익 (청산가 기준, 계획 1R 대비 R-멀티플)
export function realizedPnl(entry, stop, target, exitPrice){
  const e = num(entry), s = num(stop), t = num(target), x = num(exitPrice);
  if (e === 0) throw new Error("진입가가 0이면 실현 수익률(%)을 계산할 수 없습니다.");
  const risk = Math.abs(e - s);
  if (risk === 0) throw new Error("진입가와 손절가가 같으면 리스크(1R)가 0이 되어 계산할 수 없습니다.");
  const direction = t > e ? "long" : "short", plannedR = Math.abs(t - e) / risk;
  const move = direction === "long" ? x - e : e - x, retPct = move / e * 100, rMult = move / risk;
  return {direction, risk, planned_r_multiple: q(plannedR, 2), realized_return_pct: q(retPct, 2), realized_r_multiple: q(rMult, 2), outcome: rMult > 0 ? "win" : rMult < 0 ? "loss" : "breakeven"};
}
// 미실현 손익 (보유 중, 현재가 기준) — 로직은 realizedPnl 과 동일, 표기만 profit/loss
export function unrealizedPnl(entry, stop, target, current){
  const r = realizedPnl(entry, stop, target, current);
  return {direction: r.direction, risk: r.risk, planned_r_multiple: r.planned_r_multiple, unrealized_return_pct: r.realized_return_pct, unrealized_r_multiple: r.realized_r_multiple, status: {win: "profit", loss: "loss", breakeven: "breakeven"}[r.outcome]};
}

// 포트폴리오 히트: 모든 포지션 리스크% 합 (동시 손절 시 계좌 손실률)
export function portfolioHeat(riskPcts, maxHeatPct = 6, allowEmpty = false){
  const vals = (riskPcts || []).map(num);
  if (!vals.length && !allowEmpty) throw new Error("최소 1개 이상의 포지션 리스크%가 필요합니다.");
  if (vals.some(v => v < 0)) throw new Error("리스크%는 음수일 수 없습니다.");
  const total = vals.reduce((s, v) => s + v, 0), maxHeat = num(maxHeatPct), over = total > maxHeat, warnings = [];
  if (over) warnings.push(`⚠️ 포트폴리오 히트 ${q(total, 4)}%가 한도 ${maxHeat}%를 초과했습니다 — 모든 포지션이 동시에 손절되면 계좌의 ${q(total, 4)}%를 잃습니다.`);
  return {n_positions: vals.length, total_risk_pct: q(total, 4), max_heat_pct: maxHeat, over_limit: over, warnings};
}

// 피어슨 상관계수 (분산 효과 확인용)
export function correlation(seriesA, seriesB){
  const a = (seriesA || []).map(num), b = (seriesB || []).map(num);
  if (a.length !== b.length) throw new Error("두 시계열의 길이가 같아야 합니다.");
  const n = a.length;
  if (n < 3) throw new Error("상관관계 계산에는 최소 3개 이상의 데이터 포인트가 필요합니다.");
  const ma = a.reduce((s, v) => s + v, 0) / n, mb = b.reduce((s, v) => s + v, 0) / n;
  let cov = 0, va = 0, vb = 0;
  for (let i = 0; i < n; i++){ cov += (a[i] - ma) * (b[i] - mb); va += (a[i] - ma) ** 2; vb += (b[i] - mb) ** 2; }
  if (va === 0 || vb === 0) throw new Error("한쪽 시계열의 분산이 0이라 상관계수를 계산할 수 없습니다 (값이 모두 동일함).");
  let r = cov / Math.sqrt(va * vb); r = Math.max(-1, Math.min(1, r));
  const abs = Math.abs(r);
  return {n, correlation: q(r, 4), level: abs >= 0.7 ? "높음" : abs >= 0.3 ? "중간" : "낮음"};
}

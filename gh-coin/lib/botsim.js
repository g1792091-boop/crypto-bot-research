// 그리드 · DCA(물타기) 봇 백테스트 시뮬레이터 — passivbot(그리드·재진입·물타기)와 jesse·OctoBot 의 봇 방식을 '연구용'으로 다시 만든 것.
// ⚠ 이 시뮬레이터는 화면에서 '그리드/DCA 봇이 어떻게 움직이는지' 보여 주는 백테스트 전용이다.
//    실거래는 이 경로로 나가지 않는다 — 실거래는 기존 단일 포지션 안전 경로(paper→live.js, 한도·승인·긴급정지)만 쓴다.
//    그리드·DCA의 가장 큰 위험은 '무한 물타기 → 청산'이다. 그래서 반드시 지갑 노출 한도(walletExpo)·최대 물타기 횟수(maxRungs)로 막는다.
// 단일 심볼, 봉 단위. 체결은 봉 고가·저가로 판정(물타기·익절), 진입은 지정가가 봉 범위 안에 들어오면 체결.
const num = v => Number.isFinite(+v) ? +v : 0;

export const BOT_DEFAULTS = {
  side: "long",            // long · short (그리드 방향)
  initialQtyPct: 8,        // 첫 진입에 쓰는 증거금 비율 % (equity 대비)
  spacingPct: 1.2,         // 한 칸(물타기) 간격 % (평단 대비 역방향으로 이만큼 움직이면 다음 물타기)
  qtyMult: 1.5,            // 물타기마다 수량 배수 (passivbot ddown_factor) — 1이면 균등, 클수록 공격적(위험)
  maxRungs: 6,             // 최대 물타기 횟수 (첫 진입 포함 안 함) — 무한 물타기 금지
  walletExpo: 0.6,         // 지갑 노출 한도: 포지션 명목가 ≤ equity × 레버리지 × 이 값 (passivbot wallet_exposure_limit)
  tpMarkupPct: 1.0,        // 평단 대비 이 % 유리해지면 전량 익절 (passivbot min_markup)
  leverage: 3,
  fee: 0.04, slippage: 0.01, fundingPerBar: 0
};
export const clampBot = p => {
  const o = {...BOT_DEFAULTS, ...(p || {})};
  o.leverage = Math.min(10, Math.max(1, num(o.leverage) || 3));     // 봇 레버리지 상한 10 (안전)
  o.maxRungs = Math.min(12, Math.max(0, Math.round(num(o.maxRungs))));
  o.qtyMult = Math.min(2, Math.max(1, num(o.qtyMult) || 1));
  o.walletExpo = Math.min(1, Math.max(0.05, num(o.walletExpo) || 0.6));
  o.spacingPct = Math.max(0.1, num(o.spacingPct) || 1.2);
  o.tpMarkupPct = Math.max(0.1, num(o.tpMarkupPct) || 1);
  o.initialQtyPct = Math.min(50, Math.max(1, num(o.initialQtyPct) || 8));
  o.side = o.side === "short" ? "short" : "long";
  return o;
};

// cs: [{t,o,h,l,c,v}] · 반환: {equity:[{t,v}], trades, stats, worstRungs, liquidations}
export function simGrid(cs, params = {}, initialEquity = 10000){
  const P = clampBot(params), long = P.side === "long", dir = long ? 1 : -1;
  const feeR = P.fee / 100, slipR = P.slippage / 100;
  let cash = initialEquity, qty = 0, notional0 = 0, avg = 0, rungs = 0, nextAdd = null;
  const trades = [], equity = [{t: cs[0]?.t, v: initialEquity}];
  let worstRungs = 0, liquidations = 0, maxMargin = 0;
  const equityNow = px => cash + (qty ? dir * qty * (px - avg) : 0);
  const marginUsed = () => notional0 / P.leverage;
  const openInitial = (px, t) => {
    const fill = px * (1 + dir * slipR), eq = equityNow(px), margin = eq * P.initialQtyPct / 100;
    const q = margin * P.leverage / fill; if (!(q > 0)) return;
    const fee = q * fill * feeR; cash -= fee;
    qty = q; avg = fill; notional0 = q * fill; rungs = 0;
    nextAdd = fill * (1 - dir * P.spacingPct / 100);
  };
  const addRung = (px, t) => {
    const fill = px * (1 + dir * slipR), eq = equityNow(px);
    const maxNot = eq * P.leverage * P.walletExpo;                 // 지갑 노출 한도
    let addQty = qty * (P.qtyMult - 1); if (P.qtyMult === 1) addQty = notional0 / avg / (rungs + 1);
    if ((notional0 + addQty * fill) > maxNot){ addQty = Math.max(0, (maxNot - notional0) / fill); }   // 한도까지만
    if (!(addQty > 0)){ nextAdd = null; return; }                  // 한도 도달 → 더 물타지 않음 (무한 물타기 금지)
    const fee = addQty * fill * feeR; cash -= fee;
    avg = (avg * qty + fill * addQty) / (qty + addQty); qty += addQty; notional0 = qty * avg; rungs++;
    worstRungs = Math.max(worstRungs, rungs);
    nextAdd = rungs < P.maxRungs ? fill * (1 - dir * P.spacingPct / 100) : null;
  };
  const closeAll = (px, t, reason) => {
    const fill = px * (1 - dir * slipR), pnl = dir * qty * (fill - avg) - qty * fill * feeR;
    cash += pnl; trades.push({side: P.side, entryP: avg, exitP: fill, qty, pnl, pnlPct: marginUsed() ? pnl / Math.max(1e-9, marginUsed()) * 100 : 0, rungs, reason, exitT: t, entryT: t});
    qty = 0; notional0 = 0; avg = 0; rungs = 0; nextAdd = null;
  };
  for (let i = 0; i < cs.length; i++){
    const b = cs[i];
    if (!qty){ openInitial(b.o, b.t); }
    else {
      // 청산가(격리, 유지증거금 0.5%) 먼저
      const liq = avg * (1 - dir * (1 / P.leverage - 0.005));
      if (long ? b.l <= liq : b.h >= liq){ cash = Math.max(0, cash - marginUsed()); liquidations++; closeAll(liq, b.t, "liquidation"); if (cash <= 0) break; continue; }
      // 물타기 (역방향으로 간격만큼 가면)
      let guard = 0;
      while (nextAdd != null && (long ? b.l <= nextAdd : b.h >= nextAdd) && guard++ < 12) addRung(nextAdd, b.t);
      // 익절 (평단 대비 유리)
      const tp = avg * (1 + dir * P.tpMarkupPct / 100);
      if (long ? b.h >= tp : b.l <= tp) closeAll(tp, b.t, "take_profit");
    }
    maxMargin = Math.max(maxMargin, marginUsed());
    equity.push({t: b.t, v: +equityNow(b.c).toFixed(4)});
    if (equityNow(b.c) <= 0){ cash = 0; break; }
  }
  if (qty) closeAll(cs.at(-1).c, cs.at(-1).t, "end");
  // 성과
  const v = equity.map(p => p.v); let peak = v[0], mdd = 0; for (const x of v){ peak = Math.max(peak, x); mdd = Math.max(mdd, peak > 0 ? (peak - x) / peak * 100 : 100); }
  const wins = trades.filter(t => t.pnl > 0);
  const stats = {return_pct: +((v.at(-1) / initialEquity - 1) * 100).toFixed(2), max_drawdown_pct: +mdd.toFixed(2), trades: trades.length, win_rate_pct: trades.length ? +(wins.length / trades.length * 100).toFixed(1) : null,
    liquidations, worst_rungs: worstRungs, max_margin_pct: +(maxMargin / initialEquity * 100).toFixed(1), final_equity: +v.at(-1).toFixed(2), blown: v.at(-1) <= initialEquity * 0.02};
  return {equity, trades, stats, params: P};
}
// 사람이 읽는 경고: 이 설정이 얼마나 공격적인지
export function botRisk(params){
  const P = clampBot(params), warn = [];
  if (P.qtyMult > 1.3) warn.push(`물타기 배수 ${P.qtyMult} — 평단이 빠르게 끌려가 청산 위험 큼`);
  if (P.leverage > 3) warn.push(`레버리지 ${P.leverage}배 — 작은 역방향에도 청산 가까움`);
  if (P.walletExpo > 0.7) warn.push(`지갑 노출 ${Math.round(P.walletExpo * 100)}% — 여유 자금이 적음`);
  if (P.maxRungs >= 10) warn.push(`물타기 ${P.maxRungs}회 — 추세장에서 끝까지 물리면 큰 손실`);
  return {level: warn.length >= 3 ? "매우 공격적" : warn.length === 2 ? "공격적" : warn.length === 1 ? "보통" : "보수적", warn};
}

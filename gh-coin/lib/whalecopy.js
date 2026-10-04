// 🐋 고래 카피 파이프라인 — casatrickdev/robinhood-trading-tools 의 copyTrading(감지 → 필터 → 리스크 → 신호, 실행 없음)과
//   WalletIntelligence(지갑 성향 학습)를 코인 선물용으로 재구현(코드 복사 없음).
//   온체인 지갑 대신 바이낸스 선물 '대형 시장가 체결(고래)' 흐름을 감지하고, 그 흐름이 실제로 맞았는지 채점해 신뢰도를 학습한다.
//   이 모듈은 신호만 만든다 — 주문하지 않는다. 뉴럴 데스크·에이전트 팀이 '확인/반대' 근거로만 쓴다.

export const DEFAULT_FILTER = { minCount: 3, minNetPct: 30, maxAgeSec: 300, minShare: 0.05 };

// ① 감지: whaleTrades().data → 후보
export function detect(data) {
  const w = data?.whale; if (!w) return null;
  const dir = w.netUsd > 0 ? 1 : w.netUsd < 0 ? -1 : 0;
  return { dir, netUsd: Math.round(w.netUsd || 0), netPct: +(w.netPct || 0).toFixed(1), count: w.count || 0, buyCount: w.buyCount || 0, sellCount: w.sellCount || 0,
    share: w.shareOfVolume ?? null, ageSec: data.to ? Math.round((Date.now() - data.to) / 1000) : null, windowMin: data.windowMin ?? null };
}
// ② 필터: 표본 수·쏠림 정도·신선도·거래대금 비중 (균형이면 워시/의미 없음으로 거절)
export function filter(c, cfg = DEFAULT_FILTER) {
  const reasons = []; let ok = true;
  if (!c) return { approved: false, reasons: ["자료 없음"] };
  if (c.count < cfg.minCount) { ok = false; reasons.push(`고래 체결 ${c.count}건 < ${cfg.minCount}`); } else reasons.push(`고래 ${c.count}건`);
  if (Math.abs(c.netPct) < cfg.minNetPct) { ok = false; reasons.push(`매수·매도 균형(순 ${c.netPct}%) — 방향 없음`); } else reasons.push(`순 ${c.netPct > 0 ? "매수" : "매도"} ${Math.abs(c.netPct)}%`);
  if (c.ageSec != null && c.ageSec > cfg.maxAgeSec) { ok = false; reasons.push(`신호가 ${c.ageSec}초 지남`); }
  if (c.share != null && c.share < cfg.minShare * 100 && c.share < cfg.minShare) { /* 비중 정보는 참고만 */ }
  return { approved: ok, reasons };
}
// ③ 리스크: 학습된 신뢰도가 낮으면 쓰지 않음 (지갑 성향 학습 = 고래 흐름 적중률)
export function risk(c, trust) {
  const reasons = []; let ok = true;
  if (trust && trust.n >= 20 && trust.acc < 0.45) { ok = false; reasons.push(`학습상 고래 흐름 적중 ${Math.round(trust.acc * 100)}% (${trust.n}회) — 신뢰 낮음`); }
  else reasons.push(trust?.n ? `고래 흐름 적중 ${Math.round(trust.acc * 100)}% (${trust.n}회)` : "적중률 학습 중");
  return { approved: ok, reasons };
}
// ④ 신호
export function build(sym, c, f, r) {
  const approved = !!(c && c.dir && f.approved && r.approved);
  return { sym, t: Date.now(), dir: c?.dir || 0, netUsd: c?.netUsd || 0, netPct: c?.netPct || 0, count: c?.count || 0, status: approved ? "approved" : "rejected", reasons: [...f.reasons, ...r.reasons] };
}
export const explain = s => `🐋 ${s.sym} 고래 ${s.status === "approved" ? (s.dir > 0 ? "순매수 신호" : "순매도 신호") : "신호 없음"} · ${s.reasons.join(" · ")}`;

// 한 번에: flow.whaleTrades 결과 → 신호
export function pipeline(sym, data, trust, cfg) { const c = detect(data), f = filter(c, cfg), r = risk(c, trust); return build(sym, c, f, r); }

// 채점: 신호 후 horizonMin 분 뒤 가격이 신호 방향으로 움직였나
export function score(log, priceOf, horizonMin = 30) {
  let n = 0, hit = 0; const now = Date.now();
  for (const x of log) {
    if (!x.done && now - x.t >= horizonMin * 60e3) { const p = priceOf(x.sym); if (p) { x.done = true; x.hit = Math.sign(p - x.price) === x.dir; } }
    if (x.done && x.hit != null) { n++; if (x.hit) hit++; }
  }
  return { n, acc: n ? hit / n : 0 };
}

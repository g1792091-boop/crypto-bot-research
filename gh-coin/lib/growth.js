// 정직한 성장 검증 — "작은 돈 → 큰 목표"의 실제 도달/파산 확률을 몬테카를로로 솔직히 보여준다.
// 희망 회로가 아니라 현실. 좋은 전략(양의 기대값)을 가정해도 레버리지·복리·변동성 때문에 대부분 실패함을 드러낸다.
// 어떤 외부 의존도 없는 순수 계산.

export function honestGrowth({ start = 100000, target = 100000000, days = 30,
  winRate = 0.5, rr = 1.5, tradesPerDay = 3, riskPct = 2, sims = 5000, seed = 7 } = {}) {
  const nTrades = Math.max(1, Math.round(days * tradesPerDay));
  const needTotal = target / start;
  const needDaily = (Math.pow(needTotal, 1 / days) - 1) * 100;          // 하루 복리 몇 %가 필요한가
  const edgeR = winRate * rr - (1 - winRate);                           // 1회 기대값(R) — 양수여야 '좋은 전략'
  let rng = (seed >>> 0) || 1;
  const rnd = () => { rng = (rng * 1664525 + 1013904223) >>> 0; return rng / 4294967296; };
  let reach = 0, bust = 0; const finals = [];
  for (let s = 0; s < sims; s++) {
    let eq = start, done = false;
    for (let i = 0; i < nTrades && !done; i++) {
      const risk = eq * riskPct / 100;
      eq += (rnd() < winRate ? risk * rr : -risk);
      if (eq <= start * 0.05) { bust++; done = true; }                  // 원금 95% 소실 = 사실상 파산
      else if (eq >= target) { reach++; done = true; }
    }
    finals.push(eq);
  }
  finals.sort((a, b) => a - b);
  const q = p => finals[Math.min(sims - 1, Math.max(0, Math.floor(sims * p)))];
  return {
    start, target, days, nTrades, needTotal, needDaily, edgeR,
    winRate: winRate * 100, rr, riskPct, sims,
    pReach: +(reach / sims * 100).toFixed(2),
    pBust: +(bust / sims * 100).toFixed(1),
    median: Math.round(q(0.5)), p10: Math.round(q(0.10)), p90: Math.round(q(0.90)),
  };
}

// 한 줄 정직한 판정 문구
export function honestVerdict(g) {
  const lose = g.median < g.start;
  return `목표까지 매일 복리 ${g.needDaily.toFixed(1)}% 필요. 좋은 전략(승률 ${g.winRate}%·손익비 ${g.rr}·1회 기대값 ${g.edgeR.toFixed(2)}R)을 가정해도 `
    + `${g.days}일 뒤 목표 도달 확률 ${g.pReach}% · 파산 확률 ${g.pBust}% · 중간값 ${Math.round(g.median).toLocaleString()}원`
    + `(${lose ? "원금보다 적음" : "원금보다 많음"}). 레버리지·복리는 적게 틀려도 크게 날립니다 — 잃어도 되는 돈만.`;
}

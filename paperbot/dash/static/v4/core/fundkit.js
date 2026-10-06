// One funding-rate rule for every screen (review 10/06, "플러스 펀딩이 손실 색(분홍)으로 나옵니다"): a funding rate is not a gain or a
// loss, so it is printed in the ordinary ink; only a rate 5 times the usual 0.01 % or more (a crowded side) gets the caution colour.
// WHO pays is said in words (a tooltip here, the short label "(롱이 냄)" on the terminal). Pure (no DOM): the terminal's top row, 차트,
// 시장 and the coin head on 포지션 all read it, so they cannot disagree again.

export const FUND_HOT = 0.0005;                    // 0.05 % per 8 hours

/** the colour class of a funding rate: "" (ordinary ink) or "warn-t" (the caution colour) at 0.05 % or more, either way. */
export function fundTone(r) {
  const v = Number(r);
  return r != null && r !== "" && Number.isFinite(v) && Math.abs(v) >= FUND_HOT ? "warn-t" : "";
}

/** who pays, in plain words ("펀딩이 플러스라 롱이 숏에게 냅니다 (8시간마다)"), for a tooltip */
export function fundWho(r) {
  const v = Number(r);
  if (r == null || r === "" || !Number.isFinite(v)) return "펀딩: 이 코인의 펀딩을 받지 못했습니다 (불러오지 못함)";
  if (v === 0) return "펀딩 0: 서로 주고받는 돈이 없습니다";
  return `펀딩이 ${v > 0 ? "플러스라 롱이 숏에게" : "마이너스라 숏이 롱에게"} 냅니다 (8시간마다) · 보통은 +0.0100% · 0.05% 이상 쏠리면 주의 색`;
}

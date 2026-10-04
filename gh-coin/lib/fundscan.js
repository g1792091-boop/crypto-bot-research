// 거래소 간 펀딩비 스캔 — Sharpe MCP 의 get_funding_rates / arbitrage_cross_exchange 개념을 무료 공개 API 로 재구현(코드 복사 없음).
// 바이낸스·바이빗·OKX·비트겟 선물의 현재 펀딩비를 모아 쏠림(전 거래소 동시 과열)과 거래소 간 차이(차익 후보)를 판정한다.
// get(url) → JSON 을 돌려주는 함수를 주입받는다 (브라우저: webGet 프록시 · Node: fetch). 주문 기능 없음.

const SRC = [
  { ex: "바이낸스", url: s => `https://fapi.binance.com/fapi/v1/premiumIndex?symbol=${s}`, pick: j => ({ rate: +j.lastFundingRate, next: +j.nextFundingTime || null, mark: +j.markPrice }) },
  { ex: "바이빗", url: s => `https://api.bybit.com/v5/market/tickers?category=linear&symbol=${s}`, pick: j => { const r = j?.result?.list?.[0] || {}; return { rate: +r.fundingRate, next: +r.nextFundingTime || null, mark: +r.markPrice, oiUsd: +r.openInterestValue || null }; } },
  { ex: "OKX", url: s => `https://www.okx.com/api/v5/public/funding-rate?instId=${s.replace(/USDT$/, "")}-USDT-SWAP`, pick: j => { const r = j?.data?.[0] || {}; return { rate: +r.fundingRate, next: +r.nextFundingTime || null }; } },
  { ex: "비트겟", url: s => `https://api.bitget.com/api/v2/mix/market/current-fund-rate?symbol=${s}&productType=usdt-futures`, pick: j => { const r = j?.data?.[0] || {}; return { rate: +r.fundingRate, next: +r.nextUpdate || null }; } },
];

// 결과: rows(거래소별 % 단위), avg, spread(최대-최소, %p), 판정 key: hotLong|hotShort|split|neutral, 차익 후보
export async function fundingScan(sym = "BTCUSDT", get) {
  const rows = (await Promise.all(SRC.map(async S => {
    try { const r = S.pick(await get(S.url(sym))); return Number.isFinite(r.rate) ? { ex: S.ex, ...r, pct: +(r.rate * 100).toFixed(4) } : null; } catch (e) { return null; }
  }))).filter(Boolean);
  if (!rows.length) return { sym, rows, key: "na", ko: "자료 없음" };
  const v = rows.map(r => r.pct), avg = v.reduce((a, b) => a + b, 0) / v.length, hi = rows.reduce((a, b) => b.pct > a.pct ? b : a), lo = rows.reduce((a, b) => b.pct < a.pct ? b : a);
  const spread = +(hi.pct - lo.pct).toFixed(4), allPos = v.every(x => x > 0.03), allNeg = v.every(x => x < -0.02);
  const key = allPos && rows.length >= 2 ? "hotLong" : allNeg && rows.length >= 2 ? "hotShort" : spread >= 0.05 ? "split" : "neutral";
  const ko = { hotLong: "전 거래소 롱 과열(펀딩 +)", hotShort: "전 거래소 숏 과열(펀딩 −)", split: "거래소 간 펀딩 차이 큼", neutral: "중립" }[key];
  // 차익 후보(정보용): 펀딩 높은 곳 숏 + 낮은 곳 롱 = 정산 1회당 spread %p (수수료·가격차 위험 별도)
  const arb = spread >= 0.03 ? { short: hi.ex, long: lo.ex, perSettle: spread, annual: +(spread * 3 * 365).toFixed(1) } : null;
  return { sym, rows, avg: +avg.toFixed(4), spread, key, ko, arb, t: Date.now() };
}

export function fundingText(r) {
  if (!r?.rows?.length) return `${r?.sym || ""} 펀딩: 조회 실패`;
  return `${r.sym} 거래소별 펀딩(정산 1회 %): ${r.rows.map(x => `${x.ex} ${x.pct >= 0 ? "+" : ""}${x.pct}`).join(" · ")}\n평균 ${r.avg} · 차이 ${r.spread}%p → ${r.ko}`
    + (r.arb ? `\n차익 후보(정보용): ${r.arb.short} 숏 + ${r.arb.long} 롱 = 정산당 ${r.arb.perSettle}%p (연 ${r.arb.annual}% 환산, 수수료·가격차 위험 별도)` : "");
}

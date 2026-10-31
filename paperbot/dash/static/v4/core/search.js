// 찾기's matching (core/find.js), kept free of the page so tests run it in node: Korean names, codes, other words, and
// the first consonants of a Korean name (ㅅㅇㅍ → 순위표).

/** Other words people use for a screen (Korean and English). */
export const ALIAS = {
  home: "홈 요약 처음 home summary", board: "순위 랭킹 등수 ranking leaderboard board", flow: "흐름 추이 flow",
  checkpoint: "판정 합격 30일 verdict checkpoint", terminal: "터미널 한눈 pc terminal", positions: "포지션 보유 열린 position",
  chart: "차트 캔들 봉 chart candle", market: "시장 코인 시세 펀딩 market", strategies: "매매법 전략 strategy strategies",
  grid: "한눈 지도 격자 grid map", analysis: "분석 analysis", compare: "매매법 비교 나란히 견주기 compare versus", combo: "조합 성과 합치기 섞기 포트폴리오 상관 combo portfolio", office: "회의실 회의 사무실 office meeting", rooms: "에이전트 방 채팅 room agent",
  league: "그림자 리그 그림자 계좌 가상 거래 구경 영상 매매법 릴스 매물대 shadow league", digest: "회의 요약 digest", debate: "토론 debate", server: "서버 비용 cpu server cost", alerts: "알림 기록 alert",
  signals: "신호 signal", howto: "어떻게 설명 도움 howto help", faq: "자주 묻는 질문 faq 용어 help",
};
/** The 실거래 site's tabs (core/routes.js LIVE_SCREENS; the rule bot's page no longer lists 실거래: it moved to its own site). */
export const LIVE_ALIAS = {
  // 봇별 (owners 10/26): one screen per bot
  trendbot: "추세판단 봇 봇별 바이비트 WOO X Pro 페이퍼 trend bot", rangebot: "레인지 봇 봇별 WOO X Pro 레인지 필터 되돌림 슈퍼트렌드 range bot", vwapbot: "VWAP 개선판 봇별 페이퍼 vwap bot",
  mixbot: "친구 30분 봇 친구 15분 봇 믹스 봇별 WOO X Pro 2 두 번째 계정 OBV AC MACD 추세 3개 일치 EMA RSI mixchop mix bot",
  trend: "관제 추세 판단 되돌림 감독 지금 control trend", tchart: "추세 차트 흐름 판단 기록 히트맵 신호 띠 heatmap trend chart", hq: "한눈에 지갑 빛 실행기 계좌", pos: "포지션 진입가 익절가 손절가 최대 position", summary: "요약 터미널 terminal", chart: "차트 선 chart",
  risk: "위험 청산 손절 risk", health: "봇 상태 살아 있나 실행기 health", trades: "거래 체결 기록 trades", replay: "다시보기 재생 replay",
  journal: "일지 그동안 있었던 일 자리 비운 동안 기록 피드 타임라인 journal feed timeline",
  signals: "신호 왜 안 들어갔지 signal", missed: "못 탄 신호 놓친 missed",
  review: "검토 2주 검토 추세판단 봇 동전 새 규칙 도왔나 가상 review",
  expect: "재현 비교 재현 가상 다시 돌린 기대 비용 수수료 미끄러짐 본전 replay expect", perf: "성적 승률 performance", goal: "목표 goal",
  rank: "순위 매매법 진입 가능성 rank", judge: "규칙 점검 빠른 손절 추격 동전 쌍둥이", map: "지도 기대 범위 map", cost: "비용 미끄러짐 수수료 cost",
  cal: "일정 경제 발표 주말 calendar", safety: "안전 멈춤 경고 safety", settings: "설정 규칙 settings", team: "분석팀 AI team",
  shadows: "그림자 봇 shadow",
  mix: "믹스 30분 봇 관제 WOO X Pro 2 두 번째 계정 모의 신호 계단 mixchop mix", mixperf: "믹스 성적 승률 백테스트 거래 mixchop mix",
  // the 바이비트 봇 (owners 10-29) and the friend's trend per coin
  bybitbot: "바이비트 봇 봇별 친구 추세 OBV 스톡RSI 실거래 모의 bybit bot", bybit: "바이비트 관제 바이비트 봇 OBV 스톡RSI 신호 계단 bybit",
  bybitperf: "바이비트 성적 실거래 모의 비교 승률 거래 bybit", ftrend: "친구 추세판 추세 지표 투표 찹존 슈퍼트렌드 EMA RSI OBV 스톡RSI friend trend",
};
const CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ";
/** The first consonants of the Hangul syllables (other characters kept): "순위표" -> "ㅅㅇㅍ". */
export function chosung(s) {
  let out = "";
  for (const ch of String(s || "")) {
    const c = ch.charCodeAt(0) - 0xac00;
    out += c >= 0 && c < 11172 ? CHO[Math.floor(c / 588)] : ch;
  }
  return out;
}
export const norm = (s) => String(s || "").toLowerCase().replace(/[\s·_\-./@()]+/g, "");
export const onlyCho = (q) => /^[ㄱ-ㅎ]+$/.test(q);

/** Score of one entry for a normalized query (0 = no match): name start > word start > anywhere; codes too. */
export function score(q, item) {
  if (!q) return 0;
  const name = norm(item.label), code = norm(item.code), extra = norm(item.words);
  if (onlyCho(q)) { const c = norm(chosung(item.label)); return c.startsWith(q) ? 60 : c.includes(q) ? 40 : 0; }
  if (name === q || code === q) return 100;
  if (name.startsWith(q)) return 80;
  if (code.startsWith(q)) return 75;
  if (name.includes(q)) return 60;
  if (code.includes(q)) return 50;
  if (extra.includes(q)) return 40;
  return 0;
}

/** The n best entries for a normalized query, best first (ties by name). */
export function rank(q, items, n) {
  return items.map((x) => [score(q, x), x]).filter(([v]) => v > 0)
    .sort((p, r) => r[0] - p[0] || String(p[1].label).localeCompare(String(r[1].label))).slice(0, n).map(([, x]) => x);
}

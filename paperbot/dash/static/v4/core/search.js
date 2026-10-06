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

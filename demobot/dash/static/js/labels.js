// Korean names of the demo lab's things (demobot/CONTRACT.md sections 1-2). The settings grid itself (exits, coins,
// windows, the marked settings) comes from the server's /api/grid (demobot/grid.py is its one source).

export const LEVS = [20, 30, 40, 50];
export const COINS = ["BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD", "XRPUSD"];
export const TF_KO = {"15m": "15분", "30m": "30분"};
export const tfKo = (tf) => TF_KO[tf] || String(tf ?? "—");
export const STRAT_SHORT = {S2_ST_ROC: "S2", N02_ST_KST: "N02", N04_ST_KLINGER: "N04"};
export const STRAT_KO = {S2: "슈퍼트렌드 + ROC", N02: "슈퍼트렌드 + KST", N04: "슈퍼트렌드 + 클링거"};
export const shortOf = (s) => STRAT_SHORT[s] || String(s ?? "—");
export const WINDOW_KO = {live: "실시간", "26w": "최근 26주", "4w": "최근 4주"};
export const WINDOW_SUB = {live: "실시간 시작부터", "26w": "과거 채운 기간 포함", "4w": "최근 4주만"};

export const KINDS = [
  {id: "fixed", ko: "고정", desc: "설정을 바꾸지 않고 그대로 돌립니다"},
  {id: "adaptive", ko: "자동 교체", desc: "설정 순위를 보고 스스로 설정을 바꿉니다"},
  {id: "friend", ko: "친구 규칙", desc: "매주 친구 방식으로 설정과 청산을 고릅니다"},
  {id: "flip", ko: "동전 던지기", desc: "아무 때나 아무 방향: 운과 비교하는 기준"},
  {id: "private", ko: "비공개 매매법", desc: "서버에만 있는 매매법 (공개 저장소에 없음) · 판정은 같은 봉 동전 던지기와 비교"},
];
export const KIND_KO = Object.fromEntries(KINDS.map((k) => [k.id, k.ko]));
export const SUB_KO = {default: "기본값", friend: "친구 값", pick: "5년 1등 값", r26: "5거래마다 · 26주", r4: "5거래마다 · 4주",
  r26c: "코인별 · 26주", wk: "매주 · 26주", rule: "친구 규칙", flip: "동전"};
/** The kind of an account id (fx- / ad- / fr- / cf-), when the row does not say it. */
export function kindOfId(id) {
  const p = String(id || "").split("-")[0];
  return {fx: "fixed", ad: "adaptive", fr: "friend", cf: "flip", pv: "private"}[p] || "other";
}

export const REASON_KO = {stop: "손절", lock: "익절 잠금", liq: "강제청산", tp: "익절", open: "열림", time: "시간 청산"};
export const reasonKo = (x) => REASON_KO[x] || String(x ?? "—");
export const sideKo = (x) => (Number(x) > 0 ? "롱" : "숏");
export const PHASE_KO = {warm: "과거 채우는 중", live: "실시간", stopped: "멈춤"};

export const SORT_KO = {plateau: "주변 평균(점수)", mean_R: "평균 R (수수료 후)", win_rate: "승률", n: "거래 수",
  mdd_R: "낙폭(R)", whip: "흔들림", mean_G: "수수료 전 R"};
export const SCOPE_KO = (sc) => (sc === "ALL" ? "전체 코인" : String(sc).replace(/USD$/, ""));

// ---------------------------------------------------------------- round 3 (CONTRACT section 8)
export const TREND_KO = {up: "상승 추세", down: "하락 추세", range: "횡보"};
export const VOL_KO = {high: "변동 큼", normal: "보통", low: "변동 작음"};
export const TRENDS = ["up", "down", "range"];
export const VOLS = ["high", "normal", "low"];
export const trendKo = (x) => TREND_KO[x] || "기록 없음";
export const volKo = (x) => VOL_KO[x] || "기록 없음";
export const CONFIRM_KO = {confirming: "확인 중", confirmed: "실전 후보", failed: "확인 실패"};
export const CONFIRM_CLS = {confirming: "accent", confirmed: "good", failed: "bad"};
export const STOP_WHAT_KO = {halt: "계좌 −20%: 새 진입 영구 정지", day: "하루 −5%: 그날 새 진입 정지", streak: "5연패: 24시간 새 진입 쉼"};
export const STOP_WHAT_SHORT = {halt: "영구 정지", day: "하루 정지", streak: "연패 쉼"};
export const TG_KIND_KO = {tick: "거래 알림", switch: "설정 교체", daily: "하루 요약", warn: "경고", warn_clear: "정상 복귀",
  pass: "기준 통과", confirm_done: "확인 기간 끝", start: "시작", view_ack: "관점 받음", view_err: "관점 이해 못 함",
  view_cancel: "관점 취소", view_list: "관점 목록", view_help: "관점 도움말", view_done: "관점 끝", weekly: "주간 회의록",
  backup: "백업"};
export const tgKindKo = (k) => TG_KIND_KO[k] || String(k ?? "—");
export const TG_STATUS_KO = {sent: "보냄", queued: "보낼 차례", error: "보내기 실패"};
export const WATCH_KO = {dead: "엔진이 살아 있나", rank: "설정 순위가 도나", backup: "백업이 되나"};
/** The take-profit of a fixed pair "익절 xR · 손절 yATR" (CONTRACT 8.6), or null for any other exit. */
export function targetR(exitKo) {
  const m = /^익절\s*([0-9.]+)R\s*·\s*손절\s*[0-9.]+\s*ATR$/.exec(String(exitKo || "").trim());
  return m ? Number(m[1]) : null;
}

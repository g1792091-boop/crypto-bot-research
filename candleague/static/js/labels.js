// Korean names of the 후보 리그's things (candleague/CONTRACT.md, research/fullgrid/WATCH_PREREG.md). The strategies'
// names, entry rules and parameter meanings come from /api/meta (candleague/data/strategies_ko.json).

export const COINS = ["BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD"];
export const TFS = ["15m", "30m", "1h", "4h"];
export const TF_KO = {"15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간"};
export const TF_MS = {"15m": 900e3, "30m": 1800e3, "1h": 3600e3, "4h": 14400e3};
export const tfKo = (tf) => TF_KO[tf] || String(tf ?? "—");

// the five accounts of a pick (WATCH_PREREG 1), in the order every screen shows them
export const ROLES = ["cand", "quarter", "exitonly", "base", "flip"];
export const ROLE_KO = {cand: "후보", quarter: "1/4 크기", exitonly: "청산만 바꾼 기본값", base: "기본값", flip: "동전 던지기"};
export const ROLE_SHORT = {cand: "후보", quarter: "1/4", exitonly: "청산만", base: "기본값", flip: "동전"};
export const ROLE_DESC = {
  cand: "커스텀값 + 커스텀 익절·손절 · 규칙봇과 같은 크기",
  quarter: "후보와 똑같이, 증거금만 1/4: 크기를 줄이면 덜 흔들리나",
  exitonly: "숫자는 기본값, 익절·손절만 후보 것: 좋아진 게 숫자 덕인가 청산 덕인가",
  base: "기본값 + 지금 규칙봇 청산(계단 잠금, 2 ATR 손절): 규칙봇과 같은 조건",
  flip: "후보와 같은 시각에 들어가되 방향만 동전: 방향을 맞힌 건가 운인가",
};
/** The account id of a pick's role (candleague/candidates.py accounts()). */
export function roleId(cand, role) {
  if (role === "cand") return cand.id;
  if (role === "quarter") return `${cand.id}-q`;
  if (role === "exitonly") return `${cand.id}-x`;
  if (role === "flip") return `${cand.id}-flip`;
  return `base-${cand.kind}-${cand.name}-${cand.tf}`;
}

export const KIND_KO = {core: "기존 36", ds: "딥시크"};
export const KIND_LONG = {core: "규칙봇 기존 36 매매법", ds: "딥시크 매매법"};
export const STYLE_KO = {trend: "추세 따라가기", mixed: "섞임", reversal: "되돌림·박스"};
export const STYLE_DESC = {trend: "들어간 방향이 직전 20봉 움직임과 같은 비율 0.6 이상", mixed: "0.4~0.6",
  reversal: "0.4 이하: 횡보장·가짜 돌파를 노림"};

export const VERDICT_KO = {early: "아직 (30번 전)", ok: "기준 통과", not_yet: "기준 미달"};
export const VERDICT_CLS = {early: "thin", ok: "good", not_yet: "bad"};

export const REASON_KO = {SL: "손절", TP: "익절", LOCK: "계단 잠금", LIQ: "강제청산"};
export const reasonKo = (x) => REASON_KO[x] || String(x ?? "—");
export const sideKo = (x) => (Number(x) > 0 ? "롱" : "숏");
export const coinOf = (sym) => String(sym || "").replace(/T$/, "");
export const coinShort = (c) => String(c ?? "—").replace(/USDT?$/, "");

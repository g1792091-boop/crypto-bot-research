// Korean names of the 후보 리그's things (candleague/CONTRACT.md, research/fullgrid/WATCH_PREREG.md). The strategies'
// names, entry rules and parameter meanings come from /api/meta (candleague/data/strategies_ko.json).

export const COINS = ["BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD"];
export const TFS = ["15m", "30m", "1h", "4h"];
export const TF_KO = {"15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간"};
export const TF_MS = {"15m": 900e3, "30m": 1800e3, "1h": 3600e3, "4h": 14400e3};
export const tfKo = (tf) => TF_KO[tf] || String(tf ?? "—");

// the five accounts of a pick (WATCH_PREREG 1), in the order every screen shows them. The owner-exit league (owners 10/12,
// "익절기준이랑 손절기준을 좀 바꾸고 싶어서") has its own accounts per pick: the snapshot's ``lineup`` (dash: league.json) names
// them and applyLineup() puts them in these same arrays and maps, in place, so every screen that lists a pick's accounts
// lists those instead (ROLES, ROLE_KO, ROLE_SHORT, ROLE_DESC and roleId stay the one source).
export const ROLES = ["cand", "quarter", "exitonly", "base", "flip"];
export const ROLE_KO = {cand: "후보", quarter: "1/4 크기", exitonly: "청산만 바꾼 기본값", base: "기본값", flip: "동전 던지기"};
export const ROLE_SHORT = {cand: "후보", quarter: "1/4", exitonly: "청산만", base: "기본값", flip: "동전"};
export const ROLE_DESC = {
  cand: "커스텀값 + 커스텀 익절·손절 · 규칙봇과 같은 크기",
  quarter: "후보와 같은 신호, 증거금 비율만 1/4 (배수는 같은 규칙으로 다시 골라, 작은 포지션엔 더 높은 배수가 허용되기도 함): 크기를 줄이면 덜 흔들리나",
  exitonly: "숫자는 기본값, 익절·손절만 후보 것: 좋아진 게 숫자 덕인가 청산 덕인가",
  base: "기본값 + 지금 규칙봇 청산(계단 잠금, 2 ATR 손절): 규칙봇과 같은 조건",
  flip: "후보와 같은 시각에 들어가되 방향만 동전: 방향을 맞힌 건가 운인가",
};
/** The account id of a pick's role (candleague/candidates.py accounts(); in the owner-exit league <pick><suffix>,
 *  candleague/rulex.py owner_accounts). */
export function roleId(cand, role) {
  if (LINEUP && SUFFIX[role] != null) return `${(cand && cand.pick) || cand.id}${SUFFIX[role]}`;
  if (role === "cand") return cand.id;
  if (role === "quarter") return `${cand.id}-q`;
  if (role === "exitonly") return `${cand.id}-x`;
  if (role === "flip") return `${cand.id}-flip`;
  return `base-${cand.kind}-${cand.name}-${cand.tf}`;
}

// ---------------------------------------------------------------- the owner-exit league's accounts (applyLineup)
const DEFAULT = {roles: ROLES.slice(), ko: {...ROLE_KO}, short: {...ROLE_SHORT}, desc: {...ROLE_DESC}};
const SUFFIX = {};
/** The snapshot's lineup while the owner-exit league runs ([{role, suffix, label_ko, short_ko, desc_ko, why_ko, kind, rule, tp,
 *  weekend_off, size, accounts}]), else null. */
export let LINEUP = null;
/** What each of its accounts changes, for the "계좌가 뭔가요" tables (rulekit roleRule): {role: {nums, exit, size, dir, why}}. */
export const ROLE_INFO = {};
const hooks = new Set();
let lineKey = "";
/** fn(lineup or null) whenever the league's accounts change kind (a screen module that keeps its own role list); at once
 *  when a lineup is already in place (a screen module loaded after the first snapshot). */
export function onLineup(fn) {
  hooks.add(fn);
  if (LINEUP) { try { fn(LINEUP); } catch (e) { console.error(e); } }
  return () => hooks.delete(fn);
}
export const lineupOn = () => !!LINEUP;
const reset = (obj, def) => { for (const k of Object.keys(obj)) delete obj[k]; Object.assign(obj, def); };
/** Put the snapshot's lineup (or none: the candidate league's five accounts) into ROLES and the role maps, in place. */
export function applyLineup(lu) {
  const list = Array.isArray(lu) && lu.length ? lu.filter((x) => x && x.role && x.suffix) : [];
  const key = JSON.stringify(list.map((x) => [x.role, x.suffix, x.label_ko, x.short_ko, x.desc_ko, x.why_ko, x.size]));
  if (key === lineKey) return;
  lineKey = key;
  LINEUP = list.length ? list : null;
  reset(ROLE_KO, DEFAULT.ko); reset(ROLE_SHORT, DEFAULT.short); reset(ROLE_DESC, DEFAULT.desc);
  for (const k of Object.keys(SUFFIX)) delete SUFFIX[k];
  for (const k of Object.keys(ROLE_INFO)) delete ROLE_INFO[k];
  ROLES.splice(0, ROLES.length, ...(LINEUP ? LINEUP.map((x) => x.role) : DEFAULT.roles));
  for (const x of LINEUP || []) {
    ROLE_KO[x.role] = String(x.label_ko || x.role);
    ROLE_SHORT[x.role] = String(x.short_ko || x.label_ko || x.role);
    ROLE_DESC[x.role] = `${x.desc_ko || ""}${x.why_ko ? `: ${x.why_ko}` : ""}`;
    SUFFIX[x.role] = x.suffix;
    const size = Number(x.size ?? 1);
    ROLE_INFO[x.role] = {nums: "커스텀값 (후보와 같은 신호)", exit: String(x.desc_ko || "—"),
      size: size === 1 ? "규칙봇과 같음 (증거금 = 배수%)" : `증거금 × ${size}`, dir: "신호대로",
      why: String(x.why_ko || "—")};
  }
  for (const fn of hooks) { try { fn(LINEUP); } catch (e) { console.error(e); } }
}

export const KIND_KO = {core: "기존 36", ds: "딥시크"};
export const KIND_LONG = {core: "규칙봇 기존 36 매매법", ds: "딥시크 매매법"};
export const STYLE_KO = {trend: "추세 따라가기", mixed: "섞임", reversal: "되돌림·박스"};
export const STYLE_DESC = {trend: "들어간 방향이 직전 20봉 움직임과 같은 비율 0.6 이상", mixed: "0.4~0.6",
  reversal: "0.4 이하: 횡보장·가짜 돌파를 노림"};

export const VERDICT_KO = {early: "아직 (30번 전)", ok: "기준 통과", not_yet: "기준 미달", na: "판정 없음"};
export const VERDICT_CLS = {early: "thin", ok: "good", not_yet: "bad", na: "thin"};

export const REASON_KO = {SL: "손절", TP: "익절", LOCK: "계단 잠금", LIQ: "강제청산", RULE: "규칙 청산"};
export const reasonKo = (x) => REASON_KO[x] || String(x ?? "—");
export const sideKo = (x) => (Number(x) > 0 ? "롱" : "숏");
export const coinOf = (sym) => String(sym || "").replace(/T$/, "");
export const coinShort = (c) => String(c ?? "—").replace(/USDT?$/, "");

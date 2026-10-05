// ONE number format everywhere (owners' item): grouping "1,234.56", the true minus sign "−", signs only where a change
// is meant, percentages from ratios, prices with decimals by size, Korea time. Plus the account and timeframe names.
// Screens never call toFixed / toLocaleString themselves for what they show.

import {DS_FAMILY_KO, DS_NAME_KO, REEL, dsFamilyOf} from "./names.js";

export const MINUS = "−";
const KST_MS = 9 * 3600 * 1000;

function group(abs, dec) {
  return abs.toLocaleString("en-US", {minimumFractionDigits: dec, maximumFractionDigits: dec});
}
function bad(x) { return x == null || typeof x === "boolean" || Number.isNaN(Number(x)) || !Number.isFinite(Number(x)); }

/** 1234.5 -> "1,234.50"; {sign:true} -> "+1,234.50" / "−1,234.50"; null -> "—". */
export function num(x, dec = 2, sign = false) {
  if (bad(x)) return "—";
  const v = Number(x), s = group(Math.abs(v), dec);
  const zero = /^[0.,]+$/.test(s);
  return (v < 0 && !zero ? MINUS : sign && v > 0 && !zero ? "+" : "") + s;
}
/** Money in USDT, 2 decimals: "1,234.56" (the unit goes in the label or the caption). */
export const money = (x, sign = false) => num(x, 2, sign);
/** Money with its unit: "1,234.56 USDT". */
export const usdt = (x, sign = false) => bad(x) ? "—" : num(x, 2, sign) + " USDT";
/** Whole numbers: "1,234". */
export const int = (x) => num(x, 0, false);
/** A ratio as percent: 0.0153 -> "+1.5%". */
export function pct(ratio, dec = 1, sign = true) {
  if (bad(ratio)) return "—";
  return num(Number(ratio) * 100, dec, sign) + "%";
}
/** A value already in percent: 12.3 -> "12.3%". */
export const pctOf = (x, dec = 1, sign = false) => bad(x) ? "—" : num(x, dec, sign) + "%";
/** A price with decimals by size (BTC 62,410.5 · DOGE 0.11320). */
export function price(x) {
  if (bad(x)) return "—";
  const a = Math.abs(Number(x));
  return num(x, a < 1 ? 5 : a < 10 ? 4 : a < 1000 ? 2 : 1);
}
/** 1234567 -> "1.2M", 260661 -> "261k" (token counts). */
export function compact(x) {
  if (bad(x)) return "—";
  const a = Math.abs(Number(x));
  if (a >= 1e9) return num(x / 1e9, 1) + "B";
  if (a >= 1e6) return num(x / 1e6, 1) + "M";
  if (a >= 1e3) return num(x / 1e3, 0) + "k";
  return num(x, 0);
}
/** Real dollars (API spend, the server rental), never paper money: "$12.40". */
export const usd = (x) => bad(x) ? "—" : "$" + num(x, 2);
export const lev = (x) => bad(x) ? "—" : `${num(x, 0)}배`;
/** Sign class for a value: "up" / "down" / "". shown: the text it is shown as (a value that rounds to zero there,
 *  "0.0%", gets no colour). */
export const tone = (x, shown) => bad(x) || Number(x) === 0 || (shown != null && !/[1-9]/.test(String(shown))) ? "" : Number(x) > 0 ? "up" : "down";

// ---------------------------------------------------------------- time (always Korea time, whatever the device says)
function kparts(ms) {
  const d = new Date(Number(ms) + KST_MS);
  return {y: d.getUTCFullYear(), mo: d.getUTCMonth() + 1, d: d.getUTCDate(), h: d.getUTCHours(), mi: d.getUTCMinutes(), wd: d.getUTCDay()};
}
const two = (n) => String(n).padStart(2, "0");
const WD = ["일", "월", "화", "수", "목", "금", "토"];
/** "14:05" */
export const hm = (ms) => bad(ms) || !ms ? "—" : (({h, mi}) => `${two(h)}:${two(mi)}`)(kparts(ms));
/** "10/05 14:05" */
export const kst = (ms) => bad(ms) || !ms ? "—" : (({mo, d, h, mi}) => `${two(mo)}/${two(d)} ${two(h)}:${two(mi)}`)(kparts(ms));
/** "10/28" */
export const mmdd = (ms) => bad(ms) || !ms ? "—" : (({mo, d}) => `${two(mo)}/${two(d)}`)(kparts(ms));
/** "10월 5일 (일)" */
export const date = (ms) => bad(ms) || !ms ? "—" : (({mo, d, wd}) => `${mo}월 ${d}일 (${WD[wd]})`)(kparts(ms));
/** "2026-10-05" (a KST day key) */
export const dayKey = (ms) => (({y, mo, d}) => `${y}-${two(mo)}-${two(d)}`)(kparts(ms));
/** Today's 00:00 KST in ms. */
export const kstMidnight = (ms = Date.now()) => Math.floor((ms + KST_MS) / 86400000) * 86400000 - KST_MS;
/** Seconds -> "3분" / "2시간 5분" / "4일". */
export function dur(sec) {
  if (bad(sec)) return "—";
  const s = Math.max(0, Math.round(Number(sec)));
  if (s < 60) return `${s}초`;
  if (s < 3600) return `${Math.floor(s / 60)}분`;
  if (s < 86400) { const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60); return m ? `${h}시간 ${m}분` : `${h}시간`; }
  return `${Math.floor(s / 86400)}일`;
}
/** ms timestamp -> "3분 전" (against the server-corrected clock when given). */
export const ago = (ms, now = Date.now()) => bad(ms) || !ms ? "—" : `${dur((now - Number(ms)) / 1000)} 전`;

// ---------------------------------------------------------------- names
export const TF_KO = {"1m": "1분", "3m": "3분", "5m": "5분", "15m": "15분", "30m": "30분", "1h": "1시간", "2h": "2시간", "4h": "4시간",
  "6h": "6시간", "8h": "8시간", "12h": "12시간", "1d": "일봉", "3d": "3일봉", "1w": "주봉", "1M": "월봉"};
/** The traded timeframes, shortest first. */
export const TF_ORDER = ["5m", "15m", "30m", "1h", "4h"];
export const tfKo = (tf) => TF_KO[tf] || String(tf ?? "—");
export const coin = (sym) => String(sym ?? "").replace(/USDT$/, "");
export const REASON_KO = {SL: "손절", LOCK: "익절 잠금", LIQ: "강제청산", TP: "익절", HALT: "정지", MANUAL: "수동", END: "종료", TIME: "시간 청산", BAND: "윗밴드 익절"};
export const reasonKo = (r) => REASON_KO[r] || String(r ?? "—");
export const sideKo = (s) => Number(s) > 0 ? "롱" : "숏";

/** The board's groups (owners' cards): 기존 36 / 딥시크 44 / 5분봉 (the reel) / 동전 봇 (all 15 coin flips, the three 5m
 *  ones included: paperbot/groups.py is the single source, owners' decision) / 추가 계좌. The 5분봉 card shows its three
 *  5m coin flips inside it as its labelled comparison only; they are counted in 동전 봇. */
export const GROUPS = [
  {id: "core", ko: "기존 36", desc: "36개 매매법 × 15분·30분·1시간·4시간"},
  {id: "ds", ko: "딥시크 44", desc: "딥시크 44개 정의 (39개 × 4개 봉 + 5개 × 3개 봉)"},
  {id: "m5", ko: "5분봉", desc: "5분봉 매매법 1개(자기 청산 규칙). 비교: 같은 청산으로 롱만 하는 5분봉 동전 봇 3개 (동전 봇에서 셈)"},
  {id: "coin", ko: "동전 봇", desc: "봉마다 동전 던지기 3개 (5분봉 3개 포함): 비교 기준"},
  {id: "extra", ko: "추가 계좌", desc: "복제·새 매매법 계좌 (나중에 시작, 따로 셈)"},
];
export const GROUP_KO = Object.fromEntries(GROUPS.map((g) => [g.id, g.ko]));
/** The server's group keys (paperbot/groups.py: /api/board rows' `group`, /api/summary today.by_group) -> this page's.
 *  The three 5m coin flips are "flip" there and 동전 봇 here too. */
export const SERVER_GROUP = {core: "core", ds200: "ds", reel: "m5", flip: "coin", extra: "extra"};
/** A board row's group: the server's own `group` when the row carries one (paperbot/groups.py), else by kind. */
export function groupOf(a) {
  if (a && a.group && SERVER_GROUP[a.group]) return SERVER_GROUP[a.group];
  const k = a && a.kind;
  if (k === "strategy") return "core";
  if (k === "ds200") return "ds";
  if (k === "reel") return "m5";
  if (k === "random") return "coin";
  if (k === "copy" || k === "newlab") return "extra";
  return "other";
}
/** A 5m coin flip (long only, the reel's own exits): counted in 동전 봇, shown in the 5분봉 card as its comparison. */
export const isFlip5 = (a) => !!a && a.kind === "random" && a.timeframe === "5m";
/** An account on the reel's own exits (the reel and the 5m coin flips): the server's `exits` when sent, else by kind. */
export const ownExits = (a) => !!a && (a.exits ? a.exits === "reel" : a.kind === "reel" || isFlip5(a));
export const isFlip = (a) => a && a.kind === "random";

let STRAT_KO = {};
/** core/store.js fills the strategies' Korean names from /api/board. */
export function setStrategyNames(map) { if (map && typeof map === "object") STRAT_KO = map; }
/** A strategy code in Korean: the 36 from /api/board, DeepSeek and the reel from core/names.js (the plain-Korean
 *  short names win over the server's long "딥시크 F15_OPEN0930 (세션 레인지·시가 편향)" labels, which a phone cuts before
 *  the timeframe), coin flips numbered. */
export const stratKo = (s) => {
  const str = String(s ?? "");
  if (str.startsWith("RANDOM_")) return "동전 봇 " + str.slice(7);
  if (DS_NAME_KO[str]) return DS_NAME_KO[str];
  if (str === REEL.id) return REEL.short;
  if (STRAT_KO[str]) return STRAT_KO[str];
  return str;
};
/** DeepSeek family name of an account or a code ("구조 돌파·공급수요"), else null. */
export function familyKo(a) {
  if (!a) return null;
  if (typeof a === "string") { const f = dsFamilyOf(a); return f ? DS_FAMILY_KO[f] : null; }
  if (a.kind !== "ds200") return null;
  const f = (a.data && a.data.family) || a.family || dsFamilyOf(a.strategy);
  return f ? DS_FAMILY_KO[f] || f : null;
}
// kinds whose names come from core/names.js (short, plain Korean); the server's name_ko is kept for the account page
const OWN_NAMES = new Set(["ds200", "reel", "random"]);
/** {name, tf} of an account: "뉴욕 개장 1시간 방향" + "15분". Copies and new-lab accounts keep the server's name. */
export function acctParts(a) {
  if (!a) return {name: "—", tf: ""};
  const name = OWN_NAMES.has(a.kind) ? stratKo(a.strategy) : a.name_ko || (a.data && a.data.name_ko) || stratKo(a.strategy);
  return {name, tf: a.timeframe ? tfKo(a.timeframe) : ""};
}
/** "슈퍼트렌드·EMA · 1시간" / "RSI 다이버전스 · 15분" / "동전 봇 2 · 5분" (ui.acctLabel draws the timeframe first, in its
 *  own box that never shrinks, for lists a phone cuts). */
export function acctName(a) {
  if (!a) return "—";
  if (a.label_ko) return a.label_ko;
  const p = acctParts(a);
  return p.tf ? `${p.name} · ${p.tf}` : p.name;
}
/** "S5_DONCHIAN_MFI@15m" -> a name, without the board (best effort). */
export function idName(id) {
  const i = String(id ?? "").lastIndexOf("@");
  if (i < 0) return String(id ?? "—");
  return `${stratKo(id.slice(0, i))} · ${tfKo(id.slice(i + 1))}`;
}

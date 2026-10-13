// The plain-Korean "why" of one trade, shared by 진입 차트 (screens/entries.js) and 거래 다시보기 (screens/replay.js): why a position
// was opened (the strategy's own entry rule, the bar, the leverage), why it was closed (what the exit means), and the R marks of a
// closed trade (R = |entry - first stop|). Moved out of entries.js unchanged; it reads the trade record only, nothing is computed
// from a price the server did not send.
import {h} from "./dom.js";
import * as fmt from "./fmt.js";
import * as LK from "./lk.js";
import {ROLE_DESC, tfKo, sideKo} from "./labels.js";

export const R_TITLE = "R = 진입가와 처음 손절 사이 거리 (−1R = 처음 손절에 닿음 · 수수료 빼기 전 가격 기준)";
/** The address of one trade's 거래 다시보기: the account and the entry time (ms) name it. */
export const replayHref = (acct, at) => `#/replay?acct=${encodeURIComponent(acct)}&at=${encodeURIComponent(at)}`;
export const rTxt = (x) => `${fmt.num(x, 1, true)}R`;

/** A closed trade in R (|entry - first stop|): how far it went its way (best) and against it (worst) while open, and
 *  where it closed; null when a price is hidden or missing. summary.r_marks's rule. */
export function rMarks(t) {
  const ks = ["entry_price", "stop_initial", "mfe_price", "mae_price", "exit_price"];
  if (ks.some((k) => t[k] == null || fmt.bad(t[k]))) return null;
  const e = Number(t.entry_price), r = Math.abs(e - Number(t.stop_initial)), d = t.side > 0 ? 1 : -1;
  if (!(r > 0)) return null;
  return {best: Math.max(0, d * (Number(t.mfe_price) - e) / r), worst: Math.max(0, d * (e - Number(t.mae_price)) / r),
    end: d * (Number(t.exit_price) - e) / r};
}

/** Why this position was opened: the strategy's own entry rule (the side taken), the bar it fired on and the leverage it got. The rule is what
 *  the signal had to satisfy; the trade record does not keep the indicator values of that bar.
 *  o: {c: the pick (name, tf), acct: the account, meta, judge}. */
export function whyIn(it, o) {
  const {c, acct, meta, judge} = o;
  const sm = LK.stratMeta(c.name, meta) || {}, j = (judge && judge[c.name]) || {};
  const rule = (it.side > 0 ? sm.long : sm.short) || j.bet_ko || null;
  const forced = /^(fq|ld)(40|50)$/.test(String(acct.role || ""));          // the leverage-comparison accounts: one leverage for every entry
  const lev = it.leverage ? Number(it.leverage) : null;
  const tier = lev == null ? null : forced ? `이 계좌는 모든 진입을 ${fmt.int(lev)}배로 합니다` : lev >= 40 ? `신호 품질 좋은 자리 → ${fmt.int(lev)}배` : `신호 품질 보통 자리 → ${fmt.int(lev)}배`;
  return h("div", {class: "cl-ewhy"}, h("b", null, "왜 들어갔나"),
    h("span", null, rule ? `${rule}` : "이 매매법의 진입 조건"), h("span", {class: "muted"}, `${tfKo(c.tf)} 봉이 마감할 때 맞아서 ${sideKo(it.side)} 신호${tier ? ` · ${tier}` : ""}`));
}

/** Why a closed position was closed: the plain meaning of the exit; for a rule exit the account kind's rule and, where the kind waits for the
 *  strategy's own structure to break, that strategy's own conditions (the record does not say which of them fired).
 *  o: {c, acct, judge}. */
export function whyOut(it, o) {
  if (it.open) return null;
  const {c, acct, judge} = o;
  const j = (judge && judge[c.name]) || {};
  const role = String(acct.role || "");
  const own = /^(fq|nv|tg|fqt|fqv|fq40|fq50)$/.test(role) ? (it.side > 0 ? j.long_broken_ko : j.short_broken_ko) : null;
  const base = {SL: "처음 손절선(또는 좁힌 손절선)에 닿았습니다", TP: "익절 가격에 닿았습니다", LOCK: "계단 잠금선에 닿았습니다 (수익이 났다가 잠근 선까지 되돌아옴)",
    LIQ: "강제청산 가격에 닿았습니다"}[it.exit_reason];
  if (it.exit_reason !== "RULE") return base ? h("div", {class: "cl-ewhy"}, h("b", null, "왜 청산했나"), h("span", null, base)) : null;
  return h("div", {class: "cl-ewhy"}, h("b", null, "왜 청산했나"), h("span", null, ROLE_DESC[role] || "이 계좌의 규칙으로 청산"),
    own ? h("span", {class: "muted"}, `이 매매법의 구조가 무너졌다고 보는 조건: ${own}`) : null);
}

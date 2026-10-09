// Small shared pieces of the round 4 part B screens (한눈 지도, 졸업 길, 분석, 매매법, 5년 대비, 만약 실험실, 친구 계획,
// 레버리지 비교, 실전 준비): the line's stage on the way to 실전 후보, a diverging bar for a signed number, nice axis ticks,
// the "표본이 적으면" note, and the accounts in the order of their kinds. DOM through h() / s() only.
import {h} from "./dom.js";
import * as fmt from "./fmt.js";
import {KINDS, kindOfId} from "./labels.js";

export const FEW = 30;                      // fewer closed trades than this: "표본이 적으면 우연일 수 있음"
export const fewNote = (n) => (Number(n) < FEW ? h("span", {class: "g4-few", title: "거래가 30건보다 적으면 우연일 수 있습니다"}, "표본 적음") : null);
export const FEW_KO = "표본이 적으면 우연일 수 있음: 거래가 30건보다 적은 칸은 흐리게 보이고 '표본 적음'이 붙습니다.";

/** Accounts grouped by kind, in the kinds' order (an unknown kind last, as "기타"). */
export function byKind(accts) {
  const known = new Set(KINDS.map((k) => k.id));
  const kindOf = (a) => (known.has(a.kind || kindOfId(a.id)) ? a.kind || kindOfId(a.id) : "__other");
  const out = KINDS.map((k) => ({...k, rows: accts.filter((a) => kindOf(a) === k.id)}));
  const other = accts.filter((a) => kindOf(a) === "__other");
  if (other.length) out.push({id: "__other", ko: "기타", desc: "이 화면이 아직 모르는 종류", rows: other});
  return out.filter((k) => k.rows.length);
}

// ---------------------------------------------------------------- the stage of a line (judge.json rows)
export const STAGE_KO = ["기준 확인 중", "우리 기준 통과", "확인 기간", "실전 후보"];
/** {stage 0..3, ok, of, progress, conf, failed} of one judge row (conf = its judge.json confirm item, if any). */
export function stageOf(row, confItem) {
  const checks = (row.ours && row.ours.checks) || [];
  const ok = checks.filter((c) => c.ok).length, of = checks.length || 5;
  const st = row.confirm && row.confirm.status;
  let stage = 0;
  if (st === "confirmed") stage = 3;
  else if (st === "confirming") stage = 2;
  else if (row.ours && row.ours.pass) stage = 1;
  const progress = stage === 2 && confItem ? Number(confItem.progress) || 0 : stage === 3 ? 1 : 0;
  return {stage, ok, of, progress, conf: confItem || null, failed: st === "failed"};
}
/** Closeness for sorting: stage, then confirmation progress, then checks passed, then mean R over the luck limit. */
export function closeness(row, sg) {
  const edge = row.mean_R != null && row.luck_lim != null ? Number(row.mean_R) - Number(row.luck_lim) : -9;
  return sg.stage * 1000 + sg.progress * 100 + sg.ok * 10 + Math.max(-5, Math.min(5, edge));
}

// ---------------------------------------------------------------- numbers drawn
/** A diverging bar for a signed number (0 in the middle; full = ±max): colour AND side carry the sign. */
export function divBar(v, max, text, bare = false) {
  const x = Number(v);
  const ok = v != null && Number.isFinite(x) && max > 0;
  const w = ok ? Math.min(50, Math.abs(x) / max * 50) : 0;
  return h("span", {class: ["g4-div", bare ? "bare" : ""], title: text || null},
    h("span", {class: "g4-divt", "aria-hidden": "true"}, h("i", {class: ["g4-divb", x >= 0 ? "pos" : "neg"], style: ok ? {"--w": `${w.toFixed(1)}%`} : null})),
    bare ? null : h("b", {class: ["num", ok ? fmt.tone(x, text) : ""]}, text ?? "—"));
}
/** A plain bar 0..max (e.g. the number of trades). */
export function barN(v, max) {
  const x = Number(v) || 0;
  return h("span", {class: "g4-bn"}, h("i", {style: {"--w": `${max > 0 ? Math.min(100, x / max * 100).toFixed(1) : 0}%`}}), h("span", {class: "num"}, fmt.int(x)));
}
/** Nice ticks between lo and hi (about n of them). */
export function ticks(lo, hi, n = 5) {
  if (!(hi > lo)) return [lo];
  const raw = (hi - lo) / n, mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((x) => x >= raw) || raw;
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(Math.round(v / step) * step);
  return out;
}
/** CONTRACT 9.10 "버티는 수익인가", compact (졸업 길): the first / second half mean R pair and the warning flags as
 *  chips; null when the judge row has no robust block yet. */
export function robustLine(rb) {
  if (!rb || typeof rb !== "object") return null;
  const hf = rb.half || {};
  const flags = Array.isArray(rb.flags_ko) ? rb.flags_ko : [];
  return h("div", {class: "g4-rob"},
    h("span", {class: "g4-half", title: `닫힌 거래를 시간 순서로 반으로 나눠 평균 R: 앞 ${fmt.int(hf.first_n)}건 / 뒤 ${fmt.int(hf.second_n)}건`},
      h("span", {class: "muted"}, "앞 절반 "), h("b", {class: ["num", fmt.tone(hf.first_R, fmt.r(hf.first_R))]}, fmt.r(hf.first_R)),
      h("span", {class: "muted"}, " → 뒤 절반 "), h("b", {class: ["num", fmt.tone(hf.second_R, fmt.r(hf.second_R))]}, fmt.r(hf.second_R))),
    flags.map((f) => h("span", {class: "pp warn g4-flag"}, `⚠ ${f}`)));
}

/** A colour mix in % (14..84) for a value against a scale (the 설정 지도 look). */
export const mixOf = (v, max) => Math.round(14 + 70 * Math.min(1, Math.abs(Number(v)) / (max || 1)));

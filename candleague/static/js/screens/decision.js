// #/decision 판정 (owners 10/13): the pre-registered decision protocol. After weeks of paper trading the owners must not pick the luckiest of
// ~25 account kinds, so the rule for "who won" is fixed BEFORE the numbers are looked at: a pair-by-pair comparison on the same signals, whole
// days resampled as one lump, ONE correction over only FOUR pre-registered tests (Holm), one decision on day 28 (day 14 is a first look) and
// three more conditions (300+ pairs, both halves of the period positive, a positive mean). Every other comparison is "탐색" (reference only,
// never a ground to decide). If nothing passes, the answer is "우위 없음" and the new structures are not used for real money.
// Top to bottom: the rule box (always, even before the data exists), the one-sentence answer with a bar to the decision day, the four rows that
// decide ("이것으로만 판정합니다"), then the reference rows ("참고용") as 메인 vs 대조 / 필터 / 동전 짝 (tables; cards on a phone), each with a
// verdict WORD and colour, and a word list for beginners.
// Data: the snapshot's ``decision`` (candleague/summary.py decision_views, written next to ``kinds`` / ``pairs`` in the owner-exit league).
// HONESTY: a verdict word never rests on colour alone; every number may be null and then reads "—", never 0; the sentence comes from the
// server (counts only). DeepSeek money is left out of the figures unless the money switch is on (the server does that; a note says so).
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {hasLineup, notReady, oldLeagueBox} from "./pairs.js";
import {kindName, ppTxt, startTxt} from "./versus.js";

export const css = "scr/kinds.css";

export const DEFAULTS = {observe_day: 14, decide_day: 28, min_pairs: 300, alpha: 0.05, ci_level: 0.9, family_size: 4};
/** The seven rules as the server writes them (candleague/summary.decision_rules_ko, same order and words); used when the snapshot has none. */
export const RULES_DEFAULT = [
  "거래당 순수익 차이: 같은 신호로 들어간 거래 한 쌍씩, 새 방식의 순수익(ROE)에서 비교 대상의 순수익을 뺀 값의 평균을 봅니다.",
  "같은 날 거래는 묶어서 계산: 같은 날 끝난 거래는 같은 시장을 겪어 서로 닮았으므로, 하루를 한 덩어리로 보고 우연을 계산합니다.",
  "판정에 쓰는 것은 4개뿐: ① 빠른 손절 vs 대조, ② 빠른 손절 vs 동전 짝, ③ 대조 vs 동전 짝, ④ BTC 추세 필터가 남긴 신호 vs 버린 신호. "
  + "나머지 종류는 참고용(탐색)이라 통과 · 실패를 매기지 않고, 그것만으로는 결정하지 않습니다.",
  `우연 보정: 이 ${DEFAULTS.family_size}개를 함께 시험하므로 운 좋은 하나가 나오기 쉬워서(홀름 보정) p를 키워서 봅니다. 보정 후 p가 ${DEFAULTS.alpha}보다 작아야 합니다.`,
  `${DEFAULTS.decide_day}일째 한 번만 판정: ${DEFAULTS.observe_day}일째에는 숫자만 보고 아무것도 바꾸지 않습니다. 판정은 ${DEFAULTS.decide_day}일째에 딱 한 번입니다.`,
  `앞 절반과 뒤 절반이 같은 방향: 쌍이 ${DEFAULTS.min_pairs}개 이상이고, 기간의 앞 절반과 뒤 절반 모두 평균 차이가 플러스여야 통과입니다.`,
  "하나도 통과 못 하면 '우위 없음'이 결론: 새 구조는 실전에 쓰지 않습니다. 숫자를 본 뒤에 기준을 바꾸지 않습니다.",
];

/** verdict -> {ko (the word), cls (pill tone), help}. A colour always comes with its word. */
export const VERDICT = {
  pass: {ko: "통과", cls: "good", help: "모든 조건을 넘었습니다 (판정일 이후에만 나옵니다)"},
  fail: {ko: "실패", cls: "bad", help: "판정일에 조건 하나라도 못 넘었습니다"},
  wait: {ko: "대기", cls: "warn", help: "판정일 전이라 미리보기입니다"},
  few: {ko: "표본 부족", cls: "thin", help: "쌍이 모자라 판단하지 않습니다"},
  explore: {ko: "탐색", cls: "", help: "참고용 숫자입니다: 판정에 쓰지 않고, 이것만으로 결정하지 않습니다"},
};
export const TESTS = [
  {id: "main_vs_control", plate: "메인 vs 대조", sub: "새 청산 방법이 같은 신호에서 원래 방식(대조)보다 나은가",
    how: "같은 신호로 들어간 거래 한 쌍씩 비교합니다. 차이 = 메인 순수익 − 대조 순수익 (플러스면 메인이 낫습니다).",
    none: "비교할 메인 계좌 종류가 아직 없습니다"},
  {id: "filter_kept_vs_dropped", plate: "필터", sub: "필터가 남긴 신호가 걸러낸 신호보다 나은가",
    how: "필터 없는 계좌의 거래를, 필터 계좌도 들어간 것(남김)과 들어가지 않은 것(버림)으로 나눠 비교합니다. 차이 = 남긴 거래 평균 − 버린 거래 평균 (플러스면 필터가 쓸모 있습니다). 필터 계좌가 다른 때 포지션 중이어서 건너뛴 신호도 ‘버림’에 섞이는 근사 비교입니다.",
    none: "필터 계좌 종류가 아직 없습니다"},
  {id: "vs_coin", plate: "동전 짝", sub: "진입 방향에 실력이 있나: 실제 계좌 vs 방향을 동전으로 정한 짝",
    how: "같은 신호 시각에 롱/숏을 동전으로 정한 짝 계좌와 비교합니다 (방향은 달라도 같은 신호 시각끼리 묶음). 차이 = 실제 − 동전 (플러스면 ‘진입 방향에 실력이 있다’).",
    none: "동전 던지기 짝 계좌가 아직 없습니다"},
];

const num = (x) => (fmt.bad(x) ? null : Number(x));
const cnt = (n) => `${fmt.int(n)}건`;

// ---------------------------------------------------------------- the snapshot's ``decision``
/** The decision block with every missing number filled by the pre-registered default; null when it is absent or malformed. */
export function normDecision(x) {
  if (!x || typeof x !== "object" || Array.isArray(x) || !Array.isArray(x.rows)) return null;
  const cp = x.checkpoints && typeof x.checkpoints === "object" ? x.checkpoints : {};
  const c = x.counts && typeof x.counts === "object" ? x.counts : {};
  return {
    phase: x.phase === "decide" ? "decide" : "observe", days: Math.max(0, num(x.days) ?? 0),
    observe: num(cp.observe_day) ?? DEFAULTS.observe_day, decide: num(cp.decide_day) ?? DEFAULTS.decide_day,
    min: num(x.min_pairs) ?? DEFAULTS.min_pairs, alpha: num(x.alpha) ?? DEFAULTS.alpha, ci: num(x.ci_level) ?? DEFAULTS.ci_level,
    family: num(x.family_size) ?? DEFAULTS.family_size,
    observe_ms: num(x.observe_ms), decide_ms: num(x.decide_ms), dsIn: x.ds_in_stats === true,
    summary: typeof x.summary_ko === "string" ? x.summary_ko : "",
    rules: Array.isArray(x.rules_ko) && x.rules_ko.length ? x.rules_ko.map(String) : null,
    counts: {pass: num(c.pass) ?? 0, fail: num(c.fail) ?? 0, wait: num(c.wait) ?? 0, few: num(c.few) ?? 0},
    rows: x.rows.filter((r) => r && typeof r === "object").map((r) => ({...r, primary: r.primary === true})),
  };
}
/**
 * What the screen can show: {state, D}.  wait  no snapshot yet   old  the old league (no lineup, no decision): this screen is for the new one
 * prep  the new league, the engine has not written ``decision`` yet   ok  the decision is here
 */
export function gate(d) {
  if (!d || !d.accounts) return {state: "wait", D: null};
  const D = normDecision(d.decision);
  if (D) return {state: "ok", D};
  return {state: hasLineup(d) ? "prep" : "old", D: null};
}

// ---------------------------------------------------------------- number words
/** A p value: "0.031"; under 0.001 "0.001 미만"; null "—". */
export const pTxt = (p) => (num(p) == null ? "—" : Number(p) < 0.001 ? "0.001 미만" : fmt.num(Number(p), 3));
/** The interval "−0.3 ~ +2.7%p" (percentage points of ROE); "—" when unknown. */
export function ciTxt(lo, hi) {
  if (num(lo) == null || num(hi) == null) return "—";
  return `${ppTxt(lo).replace("%p", "")} ~ ${ppTxt(hi)}`;
}
/** ▲ / ▼ + the difference in %p, coloured by sign (the sign is also in the text). */
function diffEl(m, big) {
  const v = num(m);
  if (v == null) return h("span", {class: "muted"}, "—");
  const t = ppTxt(v), zero = !/[1-9]/.test(t);
  return h("span", {class: ["kd-v", zero ? "" : v > 0 ? "up" : "down"], style: big ? {fontSize: "var(--t-xl)", fontWeight: "800"} : null},
    `${zero ? "＝" : v > 0 ? "▲" : "▼"} ${t}`);
}
/** The verdict as a word in a coloured pill (never colour alone). */
function verdictPill(r, big) {
  const v = VERDICT[r.verdict] || {ko: "—", cls: "thin", help: ""};
  return h("span", {class: ["pp", v.cls, "kd-verdict"], title: v.help, dataset: {verdict: r.verdict || ""},
    style: big ? {fontSize: "var(--t-md)", fontWeight: "800", padding: "2px 12px"} : {fontWeight: "800"}}, v.ko);
}
const halvesTxt = (r) => (num(r.half1) == null && num(r.half2) == null ? "—" : `앞 절반 ${ppTxt(r.half1)} · 뒤 절반 ${ppTxt(r.half2)}`);
const vsText = (r) => {
  const sfx = r.vs_suffix ? ` (${r.vs_suffix})` : "";
  if (r.test === "filter_kept_vs_dropped") return `필터 없는 ${r.vs_ko || r.vs_suffix || "계좌"}${sfx}와 비교`;
  if (r.test === "vs_coin") return `동전 던지기 짝${sfx}과 비교`;
  return `대조${sfx}와 비교`;
};
/** The sample cell: "212쌍" (+ how many are still missing), or for a filter the kept / dropped counts. */
function sampleEl(r, D) {
  const n = num(r.n) ?? 0;
  const short = n < D.min ? h("small", {class: "muted"}, `${fmt.int(D.min)}${r.test === "filter_kept_vs_dropped" ? "건" : "쌍"} 필요`) : null;
  if (r.test === "filter_kept_vs_dropped") {
    return h("span", null, h("span", {class: "kd-v"}, `남김 ${cnt(num(r.n_kept) ?? 0)}`), h("small", {class: "muted"}, `버림 ${cnt(num(r.n_dropped) ?? 0)}`),
      h("small", {class: "muted"}, `적은 쪽 ${fmt.int(n)}건`), short);
  }
  return h("span", null, h("span", {class: "kd-v"}, `${fmt.int(n)}쌍`), short);
}
const reasonOf = (r) => String(r.reason_ko || "");

// ---------------------------------------------------------------- the boxes
function ruleBox(D) {
  const rules = (D && D.rules) || RULES_DEFAULT;
  return ui.card({plate: "무엇으로 이기고 지는지 미리 정한 규칙", sub: "숫자를 보기 전에 정했고, 보고 나서 바꾸지 않습니다", cls: "kd-rule"},
    h("ol", {class: "kd-list kd-rules"}, rules.map((t) => {
      const i = t.indexOf(": ");
      return h("li", null, i > 0 ? [h("b", null, t.slice(0, i)), `: ${t.slice(i + 2)}`] : t);
    })));
}
function whenLine(D) {
  const at = (ms) => (ms != null ? ` (${fmt.mmdd(ms)})` : "");
  if (D.phase === "decide") return `판정일(${D.decide}일째)이 지났습니다. 이 표의 통과 · 실패가 최종 판정입니다.`;
  if (D.days >= D.observe) return `중간 확인(${D.observe}일째${at(D.observe_ms)})은 지났습니다. 지금 숫자는 미리보기이고 아무것도 바꾸지 않습니다. 판정은 ${D.decide}일째${at(D.decide_ms)}에 한 번만 합니다.`;
  return `중간 확인은 ${D.observe}일째${at(D.observe_ms)}, 판정은 ${D.decide}일째${at(D.decide_ms)}에 한 번만 합니다. 그 전에는 아무것도 바꾸지 않습니다.`;
}
function hero(D) {
  const won = D.counts.pass > 0;
  const chips = ["pass", "fail", "wait", "few"].filter((k) => D.counts[k] > 0)
    .map((k) => h("span", {class: ["pp", VERDICT[k].cls], style: {fontSize: "var(--t-sm)"}}, `${VERDICT[k].ko} ${fmt.int(D.counts[k])}개`));
  return h("section", {class: "card hero dl-verdict s2a-hero kd-hero", "aria-label": "한 줄 결론"},
    h("div", {class: "s2a-hrow"}, ui.plate("한 줄 결론")),
    h("p", {class: ["dl-vbig", D.phase === "decide" && won ? "ok" : "warn"]}, D.summary || (D.phase === "decide" ? "판정 결과를 계산 중입니다" : `아직 판정 시점이 아닙니다 (${fmt.int(D.days)}일째, ${D.decide}일째에 판정)`)),
    ui.progress(D.days / D.decide, `${fmt.int(D.days)}일째 / ${fmt.int(D.decide)}일째에 판정`, D.phase === "decide" ? "ok" : ""),
    h("p", {class: "dl-vline"}, whenLine(D)),
    chips.length ? h("div", {class: "row wrap", style: {gap: "6px 8px"}}, chips) : null,
    h("p", {class: "note"}, "모의 거래 기록입니다. 앞으로를 약속하는 숫자가 아닙니다. 통과하기 전에는 실전에 쓰지 않습니다."));
}

// ---------------------------------------------------------------- rows: a table (or cards on a phone)
const TEST_BY_ID = Object.fromEntries(TESTS.map((t) => [t.id, t]));
/** The p of a row: the corrected one for a deciding row, the raw one for a reference row (which is not corrected). */
const pOf = (r) => (r.primary ? r.p_holm : r.p_one_sided);
const pHead = (primary) => (primary ? "p (보정 후)" : "p (보정 전)");
const pTitle = (primary) => (primary
  ? "작을수록 우연일 가능성이 낮음. 4개를 함께 시험한 것을 감안해 보정한 값"
  : "참고용이라 보정하지 않은 값입니다. 비교가 많아 작게 나와도 우연일 수 있습니다");
function nameCell(r) {
  const t = TEST_BY_ID[r.test];
  return h("td", {class: "l kd-nm"}, h("div", {class: "kd-nmh"}, h("b", null, kindName(r)), r.suffix === "-fq" ? ui.pill("실전 후보", "accent") : null),
    h("small", {class: "muted"}, `${t ? `${t.plate} · ` : ""}${r.suffix} · ${vsText(r)}`));
}
function tableView(rows, D, primary) {
  const body = [];
  for (const r of rows) {
    body.push(h("tr", {class: ["kd-row", `kd-v-${r.verdict}`], dataset: {verdict: r.verdict, suffix: r.suffix, test: r.test, primary: r.primary ? "1" : "0"}},
      nameCell(r),
      h("td", null, verdictPill(r, true)),
      h("td", {class: "num"}, sampleEl(r, D)),
      h("td", {class: "num"}, diffEl(r.mean_diff)),
      h("td", {class: "num"}, h("span", {class: "kd-v"}, ciTxt(r.ci_lo, r.ci_hi))),
      h("td", {class: "num"}, h("span", {class: ["kd-v", r.primary && num(r.p_holm) != null && r.p_holm < D.alpha ? "up" : ""]}, pTxt(pOf(r))))));
    body.push(h("tr", {class: "kd-reason"}, h("td", {class: "l", colspan: "6", style: {color: "var(--ink-2)", fontSize: "var(--t-xs)", lineHeight: "1.6", whiteSpace: "normal"}},
      num(r.half1) == null && num(r.half2) == null ? null : h("span", {class: "muted"}, `${halvesTxt(r)} · `), reasonOf(r))));
  }
  const th = (label, title) => h("th", {scope: "col", title}, label);
  return h("div", {class: "tbl-wrap"}, h("table", {class: "tbl kd-tbl"}, h("caption", {class: "sr"}, primary ? "판정에 쓰는 4개의 표" : "참고용 표"),
    h("thead", null, h("tr", null, h("th", {class: "l", scope: "col"}, "종류"), th("판정", "통과 · 실패 · 대기 · 표본 부족 · 탐색"), th("표본", "비교한 쌍(거래) 수"),
      th("평균 차이", "거래 하나당 순수익 차이(%p, 비교 대상보다 얼마나 나은가)"), th(`구간 (${Math.round(D.ci * 100)}%)`, "우연을 감안한 범위: 0을 포함하면 이겼다고 말하기 어렵습니다"),
      th(pHead(primary), pTitle(primary)))),
    h("tbody", null, body)));
}
function cardView(rows, D, primary) {
  return h("div", {class: "kd-cards"}, rows.map((r) => h("article", {class: ["kd-kcard", `kd-v-${r.verdict}`], "aria-label": kindName(r),
    dataset: {verdict: r.verdict, suffix: r.suffix, test: r.test, primary: r.primary ? "1" : "0"}},
  h("div", {class: "kd-kh"}, verdictPill(r, true), h("b", null, kindName(r)), r.suffix === "-fq" ? ui.pill("실전 후보", "accent") : null,
    h("small", {class: "muted"}, `${(TEST_BY_ID[r.test] || {plate: ""}).plate} · ${r.suffix} · ${vsText(r)}`)),
  h("div", {class: "kd-kbig"}, h("span", {class: "kd-kl"}, "평균 차이 (거래 하나당)"), h("b", {class: "num"}, diffEl(r.mean_diff, true))),
  h("dl", {class: "kd-kgrid"},
    h("div", null, h("dt", null, "표본"), h("dd", {class: "num"}, sampleEl(r, D))),
    h("div", null, h("dt", null, `구간 (${Math.round(D.ci * 100)}%)`), h("dd", {class: "num"}, ciTxt(r.ci_lo, r.ci_hi))),
    h("div", null, h("dt", null, pHead(primary)), h("dd", {class: "num"}, pTxt(pOf(r)))),
    h("div", null, h("dt", null, "앞 · 뒤 절반"), h("dd", {class: "num"}, halvesTxt(r).replace("앞 절반", "앞").replace("뒤 절반", "뒤")))),
  h("p", {class: "note"}, reasonOf(r)))));
}
const rowsView = (rows, D, view, primary) => (view === "card" ? cardView(rows, D, primary) : tableView(rows, D, primary));

/** The four rows that decide, first. */
function primaryCard(rows, D, view) {
  return ui.card({plate: `이것으로만 판정합니다 (${fmt.int(rows.length || D.family)}개)`, sub: "미리 정한 4가지 비교 · 통과 · 실패는 여기서만 매깁니다", cls: "kd-tcard kd-primary", id: "dc-primary"},
    h("p", {class: "note"}, `이 ${fmt.int(D.family)}개를 함께 시험하므로 운 좋은 하나가 나오는 것을 막으려고 p를 보정해서 봅니다. 아래 ‘참고용’ 비교는 판정에 쓰지 않습니다.`),
    rows.length ? rowsView(rows, D, view, true) : ui.none("판정에 쓰는 비교가 아직 없습니다"),
    ui.disclosure("세 가지 비교 방법 보기", h("div", {class: "stack tight"}, TESTS.map((t) => h("p", {class: "note"}, h("b", null, `${t.plate}: `), t.how)))));
}
/** The rest, for reference only. */
function referenceCards(rows, D, view) {
  const known = new Set(TESTS.map((t) => t.id));
  const head = ui.card({plate: "참고용 (판정에 쓰지 않음)", sub: `${fmt.int(rows.length)}개 · 탐색`, cls: "kd-ref", id: "dc-reference"},
    h("p", {class: "note"}, "아래 비교는 궁금해서 같이 보는 숫자입니다. 통과 · 실패를 매기지 않고, 비교가 많아 우연히 좋아 보이는 것이 섞여 있으므로 이것만으로는 실전 결정의 근거가 되지 않습니다."),
    rows.length ? null : ui.none("참고용 비교가 아직 없습니다"));
  const groups = [...TESTS.map((t) => [t, rows.filter((r) => r.test === t.id)]), [{id: "other", plate: "그 밖의 비교", sub: "", how: ""}, rows.filter((r) => !known.has(r.test))]];
  return [head, groups.filter(([, rs]) => rs.length).map(([t, rs]) => ui.card({plate: `${t.plate} (참고용)`, sub: t.sub, cls: "kd-tcard", id: `dc-${t.id}`},
    t.how ? h("p", {class: "note"}, t.how) : null, rowsView(rs, D, view, false)))];
}

function legend(D) {
  const dt = (r) => h("dt", null, verdictPill({verdict: r}, false));
  return ui.card({plate: "낱말 뜻", sub: "처음 보는 분을 위한 설명"},
    h("dl", {class: "kd-legend"},
      h("div", null, dt("pass"), h("dd", null, `${D.decide}일째 이후에만 나옵니다. 쌍 ${fmt.int(D.min)}개 이상, 우연 보정 후 p가 ${D.alpha}보다 작음, 평균 차이가 플러스, 앞 절반과 뒤 절반 모두 플러스 (이 넷 전부).`)),
      h("div", null, dt("fail"), h("dd", null, `${D.decide}일째 이후에 위 조건 중 하나라도 못 넘은 것입니다. 이유 줄에 어느 조건인지 씁니다.`)),
      h("div", null, dt("wait"), h("dd", null, `${D.decide}일째 전입니다. 지금은 미리보기이고 통과 · 실패를 말하지 않습니다.`)),
      h("div", null, dt("few"), h("dd", null, `비교할 쌍(거래)이 ${fmt.int(D.min)}개보다 적습니다. 적은 표본은 운일 수 있어 판단하지 않습니다.`)),
      h("div", null, dt("explore"), h("dd", null, "판정에 쓰지 않는 참고 숫자입니다. 통과 · 실패를 매기지 않고, 이것만으로는 결정하지 않습니다.")),
      h("div", null, h("dt", null, "평균 차이"), h("dd", null, "거래 하나당 순수익(증거금 대비)의 평균 차이입니다. %p는 퍼센트 포인트. 플러스면 앞에 적은 쪽이 낫습니다.")),
      h("div", null, h("dt", null, "구간"), h("dd", null, `우연을 감안했을 때 평균 차이가 ${Math.round(D.ci * 100)}% 확률로 들어 있는 범위입니다. 0을 포함하면 이겼다고 말하기 어렵습니다.`)),
      h("div", null, h("dt", null, "p (보정 후)"), h("dd", null, "‘실제로는 차이가 없는데 이런 숫자가 우연히 나올’ 가능성입니다. 작을수록 우연이 아닙니다. 판정에 쓰는 4개를 함께 시험하므로 그만큼 크게 고쳐서(홀름 보정) 보여 줍니다.")),
      h("div", null, h("dt", null, "p (보정 전)"), h("dd", null, "참고용 비교의 p입니다. 보정하지 않았으니 작게 나와도 우연일 수 있습니다."))));
}
function closing(D, d) {
  const wallet = Number(d && d.equity0) > 0 ? `모든 계좌는 ${startTxt(d)}에서 시작하는 모의 계좌입니다 (가상 돈). ` : "모의 계좌입니다 (가상 돈). ";
  return [
    h("p", {class: "note"}, D.dsIn ? "이 판정에는 딥시크 계좌도 들어 있습니다." : "이 판정은 딥시크를 뺀 후보만으로 계산했습니다 (딥시크 금액은 숨김 설정이라 판정에도 쓰지 않습니다)."),
    h("p", {class: "assume"}, `${wallet}종류끼리는 같은 신호를 나눠 쓰므로 서로 완전히 따로가 아닙니다. ${D.decide}일은 짧아서 통과해도 운일 수 있습니다. 실제 주문은 넣지 않습니다.`),
  ];
}

function missingBox(g, d) {
  if (g.state === "old") return oldLeagueBox(d, "판정 화면은 아직 없습니다.");
  if (g.state === "prep") {
    return ui.card({plate: "데이터 준비 중"},
      h("p", {class: "dl-vline"}, "판정 기록은 아직 없습니다. 위 규칙은 그대로 적용됩니다."),
      h("p", {class: "note"}, "엔진이 판정 기록을 쓰면 (5분마다) 저절로 나타납니다. 쌍이 쌓이는 데 며칠 걸립니다."));
  }
  return notReady("후보 리그 기록이 아직 없습니다.");
}

export async function mount(el, ctx) {
  el.classList.add("kd");
  const root = h("div", {class: "kd-root"});
  const saved = local.get("decision-view", null);
  const st = {view: saved === "card" || saved === "table" ? saved : (typeof innerWidth === "number" && innerWidth < 760 ? "card" : "table"), d: null};
  const seg = ui.seg([{id: "table", label: "표"}, {id: "card", label: "카드"}], st.view, (v) => { st.view = v; local.set("decision-view", v); paint(); }, {label: "보기"});
  const head = ui.screenHead("판정", "미리 정한 규칙으로 승자를 가리는 화면");
  el.append(head, root);
  put(root, ruleBox(null), ui.missing("판정 기록"));

  function paint() {
    const d = st.d, g = gate(d);
    if (g.state !== "ok") { put(root, ruleBox(null), missingBox(g, d)); return; }
    const D = g.D;
    seg.set(st.view);
    put(root, ruleBox(D), hero(D),
      h("div", {class: "row wrap", style: {justifyContent: "flex-end"}}, seg),
      primaryCard(D.rows.filter((r) => r.primary), D, st.view),
      referenceCards(D.rows.filter((r) => !r.primary), D, st.view),
      legend(D), closing(D, d));
  }
  ctx.onLeague((d) => { st.d = d; paint(); });
}

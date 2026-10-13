// #/versus 메인 vs 대조 (owners 10/13): the headline screen of the exit-structure league. The snapshot's ``kinds`` (one row per
// account kind, in the lineup's order: 메인 = the new exit structures the owners want to try for real, 대조 = the original
// fixed-stop ladder accounts, 연구용 = the rest) are compared on what the owners care about: 승률, 평균 이익 / 손실, 손익비,
// 거래당 순수익 (ROE per closed trade), 하루 진입 수, 보유 시간, 낙폭, 잔고 수익률. Top: one sentence from the data (how many
// 메인 kinds beat the 대조 -ld on 거래당 순수익; "아직 판정하기엔 거래가 적습니다" until every compared kind has 300 closed
// trades, with a bar), then a short reading guide, the table (or cards on a phone) with the best 메인 per column starred
// and the difference to the 대조 shown as ▲ ▼ words, the coin-flip row (방향 실력 확인용) and the decision rule.
// HONESTY: the counts of kinds, accounts and picks are read from the snapshot, never written here (a kind may exist for
// only some of the picks); every ROE / money field may be null (DeepSeek money hidden) and then reads "—", never 0; the
// rates of a kind with no closed trade read "—". Nothing here is a promise; a small sample says so.
// The other two screens of this set (goal.js, reasons.js) import the helpers exported below.
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as LK from "../lk.js";

export const css = "scr/kinds.css";

export const MIN_TRADES = 300;           // the decision needs this many closed trades in every compared kind
export const SMALL_N = 100;              // below this a figure is called a small sample
export const EARLY_N = 30;               // below this nothing is judged (the league's rule everywhere)
export const GROUP_ORDER = ["main", "control", "research"];
export const GROUP_KO = {main: "메인", control: "대조", research: "연구용"};
export const GROUP_HELP = {
  main: "새로 시험하는 청산 구조 (두 분이 실제로 써 보려는 것)",
  control: "원래 방식 (고정 손절 계단) 계좌 · 메인과 비교하는 기준",
  research: "궁금해서 같이 돌리는 계좌 · 결정에는 쓰지 않음",
};
export const CONTROL_ROLE = "ld";        // 대조 = the original main (suffix -ld); doc.pairs.control names it too
export const COIN_ROLE = "ldc";          // its twin with the entry direction set by a coin flip
export const LIVE_ROLE = "fq";           // the 실전 후보

// ---------------------------------------------------------------- the kinds of a snapshot
const num = (x) => (fmt.bad(x) ? null : Number(x));
export const val = num;

/** "main" | "control" | "research" (the snapshot's ``group``, else by the Korean label's first word). */
export function groupOf(k) {
  if (k && GROUP_KO[k.group]) return k.group;
  const l = String((k && k.label_ko) || "");
  return l.startsWith("메인") ? "main" : l.startsWith("대조") ? "control" : "research";
}
/** The short Korean name of a kind: the snapshot's ``short_ko``, else the label without its group word. */
export function kindName(k) {
  const s = String((k && k.short_ko) || "").trim();
  if (s) return s;
  return String((k && (k.label_ko || k.role)) || "").replace(/^(메인|대조|연구)\s*·\s*/, "").replace(/\s*\(실전 후보\)\s*$/, "") || String((k && k.role) || "—");
}
function normKind(k) {
  const n = Number(k.trades);
  return {...k, group: groupOf(k), n: Number.isFinite(n) && n > 0 ? n : 0, name: kindName(k), suffix: k.suffix || `-${k.role}`};
}
/**
 * What a kinds screen can show for a snapshot: {state, kinds}.
 *   wait  no snapshot yet                         old   the old league (no lineup, no kinds): this screen is for the new one
 *   prep  the new league, the engine has not yet written ``kinds``                                   ok    kinds are here
 */
export function gate(d) {
  if (!d || !d.accounts) return {state: "wait", kinds: []};
  const raw = Array.isArray(d.kinds) ? d.kinds.filter((k) => k && typeof k === "object" && k.role) : [];
  if (raw.length) return {state: "ok", kinds: raw.map(normKind)};
  if (!(Array.isArray(d.lineup) && d.lineup.length)) return {state: "old", kinds: []};
  return {state: "prep", kinds: []};
}
/** The card a screen shows instead of its body when the gate is not ``ok``. */
export function gateNode(g) {
  if (g.state === "old") {
    return ui.card({plate: "새 리그용 화면"},
      h("p", {class: "dl-vline"}, "이 화면은 새 리그 (메인 vs 대조 청산 비교)용입니다."),
      h("p", {class: "note"}, "지금 보고 있는 리그에는 이 숫자가 없어서 비워 둡니다. 순위표와 5계좌 비교는 그대로 쓸 수 있습니다."),
      h("div", {class: "row wrap"}, h("a", {class: "btn-line", href: "#/rank"}, "순위표"), h("a", {class: "btn-line", href: "#/compare"}, "5계좌 비교")));
  }
  if (g.state === "prep") {
    return ui.card({plate: "데이터 준비 중"},
      h("p", {class: "dl-vline"}, "데이터 준비 중입니다. 아직 거래가 없습니다."),
      h("p", {class: "note"}, "엔진이 종류별 숫자를 기록에 쓰면 (5분마다) 저절로 나타납니다."));
  }
  return ui.missing("종류별 숫자");
}
/**
 * The lineup's kinds by group, in the lineup's order (요약's hero): [{group, ko, kinds: [{role, suffix, name, live}]}], an empty group left
 * out. Same group rule and same short name as the table (groupOf, kindName); a name that two kinds share (every 동전 짝 is "동전", three
 * 대조 are "계단") takes the label without its group word, so no two chips read alike.
 */
export function lineupGroups(d) {
  const lu = Array.isArray(d && d.lineup) ? d.lineup.filter((k) => k && typeof k === "object" && k.role) : [];
  const seen = {};
  for (const k of lu) { const n = kindName(k); seen[n] = (seen[n] || 0) + 1; }
  const named = (k) => {
    const n = kindName(k);
    if (seen[n] < 2) return n;
    return String(k.label_ko || "").replace(/^(메인|대조|연구|필터)\s*·\s*/, "").replace(/\s*\(실전 후보\)\s*$/, "").trim() || n;
  };
  return GROUP_ORDER.map((g) => ({group: g, ko: GROUP_KO[g],
    kinds: lu.filter((k) => groupOf(k) === g).map((k) => ({role: k.role, suffix: k.suffix, name: named(k), live: k.role === LIVE_ROLE}))}))
    .filter((x) => x.kinds.length);
}
/** The start wallet in words from the snapshot itself ("$1,000"); without ``equity0`` no dollar figure is made up. */
export const startTxt = (d) => (d && Number(d.equity0) > 0 ? LK.usd0(Number(d.equity0)) : "시작 잔고");
/** The 대조 kind of the snapshot (``pairs.control`` names its suffix) and the coin-flip twin. */
export function controlOf(kinds, d) {
  const sfx = d && d.pairs && typeof d.pairs.control === "string" ? d.pairs.control : `-${CONTROL_ROLE}`;
  return kinds.find((k) => k.suffix === sfx) || kinds.find((k) => k.role === CONTROL_ROLE) || null;
}
export const coinOf = (kinds) => kinds.find((k) => k.role === COIN_ROLE || k.suffix === `-${COIN_ROLE}`) || null;
export const roleOf = (kinds, role) => kinds.find((k) => k.role === role) || null;
/** The kinds' trades summed (a "no trade at all" test). */
export const totalTrades = (kinds) => kinds.reduce((a, k) => a + k.n, 0);

// ---------------------------------------------------------------- number words
/** A fraction as a percent: 0.0834 -> "8.3%" / "+8.3%"; null -> "—". */
export function pc(f, sign = false, dec) {
  const v = num(f);
  if (v == null) return "—";
  const x = v * 100;
  return fmt.pct(x, sign, dec ?? (x !== 0 && Math.abs(x) < 1 ? 2 : 1));
}
const smart = (x, dec, sign) => {
  let t = fmt.num(x, dec, sign);
  if (x !== 0 && !/[1-9]/.test(t)) t = fmt.num(x, dec + 1, sign);
  return t;
};
/** A difference of two fractions in percentage points: "+2.1%p". */
export const ppTxt = (f) => (num(f) == null ? "—" : `${smart(Number(f) * 100, 1, true)}%p`);
export const cnt = (n) => `${fmt.int(n)}건`;
export const tone = (x) => fmt.tone(x);
/** "거래 N건뿐이라 …" for a small sample (null from 100 on). */
export function sampleNote(n) {
  if (n >= SMALL_N) return null;
  if (n < EARLY_N) return `거래가 ${fmt.int(n)}건뿐이라 아직 믿기 어렵습니다 (${EARLY_N}건 전에는 판단하지 않습니다)`;
  return `거래가 ${fmt.int(n)}건뿐이라 운일 수 있습니다 (${SMALL_N}건부터 참고, ${MIN_TRADES}건부터 판단)`;
}
export const groupChip = (g) => ui.pill(GROUP_KO[g], g === "main" ? "accent" : g === "control" ? "" : "thin");

// ---------------------------------------------------------------- the columns
// good: "high" (a higher number is better) / "low" / null (just a fact). diff: how the gap to the 대조 is written.
const COLS = [
  {key: "trades", label: "거래", help: "닫힌 거래 수", get: (k) => k.n, show: (v) => cnt(v)},
  {key: "win_rate", label: "승률", help: "이긴 거래의 비율", get: (k) => (k.n ? num(k.win_rate) : null), show: (v) => pc(v, false, 1),
    good: "high", diff: {mul: 100, unit: "%p", dec: 1}},
  {key: "avg_win_roe", label: "평균 이익", help: "이긴 거래의 평균 ROE (증거금 대비)", get: (k) => (k.n ? num(k.avg_win_roe) : null), show: (v) => pc(v, true),
    good: "high", diff: {mul: 100, unit: "%p", dec: 1}},
  {key: "avg_loss_roe", label: "평균 손실", help: "진 거래의 평균 ROE (0에 가까울수록 좋음)", get: (k) => (k.n ? num(k.avg_loss_roe) : null), show: (v) => pc(v, true),
    good: "high", diff: {mul: 100, unit: "%p", dec: 1}},
  {key: "payoff", label: "손익비", help: "평균 이익 ÷ 평균 손실 (1보다 크면 이길 때 더 크게 이김)", get: (k) => (k.n ? num(k.payoff) : null), show: (v) => fmt.num(v, 2),
    good: "high", diff: {mul: 1, unit: "", dec: 2}},
  {key: "mean_roe", label: "거래당 순수익", help: "거래 한 번이 증거금 대비 평균 얼마 남겼나 (수수료 뺀 뒤)", get: (k) => (k.n ? num(k.mean_roe) : null), show: (v) => pc(v, true),
    good: "high", diff: {mul: 100, unit: "%p", dec: 1}, big: true},
  {key: "trades_per_day", label: "하루 진입", help: "하루에 평균 몇 번 들어가나 (이 종류 전체)", get: (k) => num(k.trades_per_day), show: (v) => `${fmt.num(v, 1)}건`,
    good: "high", diff: {mul: 1, unit: "건", dec: 1}},
  {key: "median_hold_h", label: "보유 중앙", help: "거래 한 번을 들고 있는 시간의 중앙값", get: (k) => (k.n ? num(k.median_hold_h) : null), show: (v) => `${fmt.num(v, 1)}시간`,
    diff: {mul: 1, unit: "시간", dec: 1}},
  {key: "max_dd_mean", label: "낙폭", help: "잔고가 고점에서 가장 많이 빠진 정도의 평균 (작을수록 좋음)", get: (k) => num(k.max_dd_mean), show: (v) => pc(v, false, 1),
    good: "low", diff: {mul: 100, unit: "%p", dec: 1}},
  // wallet_return_pct is a fraction too (the kind's accounts' mean of wallet / start wallet - 1)
  {key: "wallet_return_pct", label: "잔고 수익률", sub: true, help: "시작 잔고 대비 지금 잔고, 계좌들의 평균 (닫힌 거래까지)", get: (k) => num(k.wallet_return_pct), show: (v) => pc(v, true, 1),
    good: "high", diff: {mul: 100, unit: "%p", dec: 1}, tone: true},
];
const colLabel = (c, d) => (c.sub ? [c.label, h("small", {class: "kd-thsub"}, `${startTxt(d)} 대비`)] : c.label);

/** The best 메인 kind per column: {column key: Set of roles}. Needs two 메인 kinds with a number; all equal = nobody. */
export function bestMain(kinds) {
  const main = kinds.filter((k) => k.group === "main" && k.n > 0);
  const out = {};
  for (const c of COLS) {
    if (!c.good) continue;
    const vs = main.map((k) => [k, c.get(k)]).filter(([, v]) => v != null);
    if (vs.length < 2) continue;
    const top = c.good === "low" ? Math.min(...vs.map((x) => x[1])) : Math.max(...vs.map((x) => x[1]));
    const win = vs.filter(([, v]) => v === top);
    if (win.length === vs.length) continue;
    out[c.key] = new Set(win.map(([k]) => k.role));
  }
  return out;
}
/** The gap of a kind to the 대조 in a column: {arrow, text, word, tone, good} or null (no number on either side). */
export function diffOf(c, k, ctl) {
  if (!c.diff || !ctl || k === ctl || k.n <= 0 || ctl.n <= 0) return null;
  const a = c.get(k), b = c.get(ctl);
  if (a == null || b == null) return null;
  const x = (a - b) * c.diff.mul;
  const t = smart(x, c.diff.dec, true);
  const zero = !/[1-9]/.test(t);
  const better = c.good == null || zero ? null : c.good === "high" ? x > 0 : x < 0;
  return {zero, arrow: zero ? "＝" : x > 0 ? "▲" : "▼", text: zero ? "" : `${t}${c.diff.unit}`, word: zero ? "같음" : x > 0 ? "높음" : "낮음",
    tone: better == null ? "" : better ? "up" : "down", good: better};
}

// ---------------------------------------------------------------- the verdict
/** Everything the headline needs: the 대조, the coin twin, the 메인 kinds, how many beat the 대조, the smallest trade count. */
export function sumOf(kinds, d) {
  const ctl = controlOf(kinds, d);
  const main = kinds.filter((k) => k.group === "main");
  const cm = ctl && ctl.n > 0 ? num(ctl.mean_roe) : null;
  const cmp = cm == null ? [] : main.filter((k) => k.n > 0 && num(k.mean_roe) != null);
  const up = cmp.filter((k) => Number(k.mean_roe) > cm);
  const need = [...main, ...(ctl ? [ctl] : [])];
  const minK = need.reduce((m, k) => (m == null || k.n < m.n ? k : m), null);
  const minN = minK ? minK.n : 0;
  const best = cmp.reduce((m, k) => (m == null || Number(k.mean_roe) > Number(m.mean_roe) ? k : m), null);
  return {ctl, coin: coinOf(kinds), main, cmp, up, best, minK, minN, enough: need.length > 0 && minN >= MIN_TRADES, allZero: totalTrades(kinds) === 0, kinds, d};
}

function hero(S) {
  const {main, ctl, cmp, up, best, minK, minN, enough, allZero} = S;
  const need = h("small", {class: "kd-need"}, `(종류마다 ${MIN_TRADES}건 필요, 지금 ${fmt.int(minN)}건)`);
  const ref = ctl && cmp.length
    ? `메인 ${main.length}개 중 ${up.length}개가 대조보다 거래당 순수익이 높습니다${cmp.length < main.length ? ` (거래가 있는 ${cmp.length}개 기준)` : ""}`
    : null;
  let big;
  if (!main.length) big = h("p", {class: "dl-vbig warn"}, "메인 계좌 종류가 아직 없습니다");
  else if (!enough) big = h("p", {class: "dl-vbig warn"}, allZero ? "아직 거래가 없습니다 " : "아직 판정하기엔 거래가 적습니다 ", need);
  else if (ref) big = h("p", {class: ["dl-vbig", up.length ? "ok" : "warn"]}, ref);
  else big = h("p", {class: "dl-vbig warn"}, "대조와 비교할 거래가 아직 없습니다");
  const lines = [];
  if (!enough && main.length) {
    lines.push(ref ? h("p", {class: "dl-vline"}, `참고로 지금까지는 ${ref}.`)
      : h("p", {class: "dl-vline"}, "대조 계좌에 아직 거래가 없어 비교할 수 없습니다."));
  } else if (enough && best && ctl) {
    lines.push(h("p", {class: "dl-vline"}, `가장 높은 메인은 ‘${best.name}’ ${pc(best.mean_roe, true)} (대조 ${pc(ctl.mean_roe, true)}, ${ppTxt(Number(best.mean_roe) - Number(ctl.mean_roe))}).`));
  }
  if (S.coin && S.ctl) lines.push(h("p", {class: "dl-vline"}, coinSentence(S)));
  return h("section", {class: "card hero dl-verdict s2a-hero kd-hero", "aria-label": "한 줄 결론"},
    h("div", {class: "s2a-hrow"}, ui.plate("한 줄 결론")),
    big,
    main.length ? ui.progress(minN / MIN_TRADES, `${fmt.int(minN)} / ${fmt.int(MIN_TRADES)}건${minK ? ` · 가장 적은 종류: ${minK.name}` : ""}`, enough ? "ok" : "") : null,
    lines,
    h("p", {class: "note"}, `모의 거래 기록입니다. 앞으로를 약속하는 숫자가 아닙니다. 거래가 ${fmt.int(MIN_TRADES)}건이 되기 전에는 운일 수 있습니다.`),
    h("div", {class: "row wrap"}, h("a", {class: "btn-line", href: "#/goal"}, "목표 진척도"), h("a", {class: "btn-line", href: "#/reasons"}, "청산 이유"),
      h("a", {class: "btn-line", href: "#/pairs"}, "같은 신호 짝 비교")));
}
/** The coin twin against the 대조: does the entry direction beat a coin flip? (one sentence, "" when unknown) */
export function coinSentence(S) {
  const {ctl, coin} = S;
  if (!ctl || !coin) return "";
  const a = ctl.n > 0 ? num(ctl.mean_roe) : null, b = coin.n > 0 ? num(coin.mean_roe) : null;
  if (a == null || b == null) return `방향 실력 확인: 대조 ${cnt(ctl.n)} · 동전 ${cnt(coin.n)}, 아직 비교할 거래가 없습니다.`;
  const small = Math.min(ctl.n, coin.n) < SMALL_N ? ` (거래가 ${cnt(Math.min(ctl.n, coin.n))}뿐이라 운일 수 있습니다)` : "";
  return a > b
    ? `방향 실력 확인: 대조(${pc(a, true)})가 동전 던지기(${pc(b, true)})보다 거래당 ${ppTxt(a - b)} 높습니다. 진입 방향에 실력이 있을 수 있습니다${small}.`
    : `방향 실력 확인: 대조(${pc(a, true)})가 동전 던지기(${pc(b, true)})를 이기지 못했습니다. 이대로면 진입 방향에 실력이 없을 수 있고, 그러면 청산을 바꿔도 의미가 작습니다${small}.`;
}

// ---------------------------------------------------------------- the boxes
function readGuide() {
  return ui.card({plate: "이렇게 읽으세요", cls: "kd-read"},
    h("ul", {class: "kd-list"},
      h("li", null, h("b", null, "거래당 순수익"), "이 가장 중요합니다. 거래 한 번에 증거금 대비 평균 얼마가 남았는지입니다. 승률이 높아도 이익이 작고 손실이 크면 마이너스입니다."),
      h("li", null, h("b", null, "손익비"), " = 평균 이익 ÷ 평균 손실. 1보다 크면 이길 때 더 크게 이기는 것입니다."),
      h("li", null, h("b", null, "▲ ▼ 숫자"), "는 대조와의 차이입니다 (%p = 퍼센트 포인트). 초록은 대조보다 좋음, 빨강은 나쁨입니다. 글자(높음·낮음)도 같이 봅니다."),
      h("li", null, h("b", null, "★"), "는 메인 종류들 중 그 칸이 가장 좋다는 표시입니다. 낙폭은 작을수록 좋습니다.")));
}
function ruleBox() {
  return ui.card({plate: "어떻게 고르나요", sub: "미리 정한 규칙 · 숫자를 본 뒤에 바꾸지 않습니다", cls: "kd-rule"},
    h("ol", {class: "kd-list"},
      h("li", null, h("b", null, "고르는 것은 판정 화면의 규칙으로만"), " 합니다. 14일째에는 숫자만 보고 아무것도 바꾸지 않고, 판정은 28일째에 한 번만 합니다 (",
        h("a", {href: "#/decision"}, "판정 화면"), ")."),
      h("li", null, "이 화면의 ★ · 높고 낮음은 ", h("b", null, "참고"), "입니다. 종류가 많아서 가장 높은 것은 운이 좋았을 뿐일 수 있습니다. 판정은 같은 신호끼리 한 쌍씩 비교하고, 하나도 통과하지 못하면 ‘우위 없음’입니다."),
      h("li", null, "승률만 보고 고르지 않습니다. 승률이 높아도 거래당 순수익이 낮으면 소용없습니다."),
      h("li", null, "동전 던지기 짝을 못 이기면 진입 방향에 실력이 없을 수 있습니다. 그때는 청산을 바꿔도 의미가 작습니다.")));
}
function coinBox(S) {
  if (!S.coin) return null;
  const small = sampleNote(Math.min(S.ctl ? S.ctl.n : 0, S.coin.n));
  return ui.card({plate: "방향 실력 확인", sub: `${S.coin.suffix} · 방향 실력 확인용: 진입 방향을 동전으로 정한 짝`, cls: "kd-coin"},
    h("p", {class: "dl-vline"}, coinSentence(S) || "아직 비교할 거래가 없습니다."),
    h("p", {class: "note"}, "동전 던지기 계좌는 대조와 같은 시각에 같은 청산으로 들어가되 롱/숏만 동전으로 정합니다. 대조가 이 계좌를 이기지 못하면 방향을 맞힌 것이 아니라 운일 수 있습니다."),
    small ? h("p", {class: "note"}, small) : null);
}
function picksNote(S) {
  const c = S.ctl;
  if (!c) return null;
  const fewer = S.main.filter((k) => num(k.accounts) != null && num(c.accounts) != null && Number(k.accounts) < Number(c.accounts));
  if (!fewer.length) return null;
  return h("p", {class: "refnote"}, h("b", null, "같은 후보끼리가 아닙니다"),
    ` · ${fewer.map((k) => `‘${k.name}’은 ${fmt.int(k.accounts)}개`).join(" · ")} 후보에만 계좌가 있고(그 매매법에 자체 구조 · 가격 코드가 있는 후보만), 대조는 ${fmt.int(c.accounts)}개 후보 전부에 있습니다. `,
    "숫자 차이에는 매매법 구성의 차이가 섞여 있습니다. 같은 신호끼리 정확히 비교하려면 ", h("a", {href: "#/pairs"}, "짝 비교"), "를 보세요.");
}

// ---------------------------------------------------------------- the table and the cards
function nameCell(k, S) {
  return h("td", {class: "l kd-nm"},
    h("div", {class: "kd-nmh"}, h("b", null, k.name), k.role === LIVE_ROLE ? ui.pill("실전 후보", "accent") : null, k === S.ctl ? ui.pill("기준", "") : null),
    h("small", {class: "muted"}, `${k.suffix}${num(k.accounts) != null ? ` · ${fmt.int(k.accounts)}개 후보` : ""}${k.open_now ? ` · 열린 ${fmt.int(k.open_now)}` : ""}`),
    k.role === COIN_ROLE ? h("small", {class: "kd-coinnote"}, "방향 실력 확인용: 진입 방향을 동전으로 정한 짝") : null);
}
function diffEl(dd, long) {
  const core = dd.zero ? `${dd.arrow} ${dd.word}` : `${dd.arrow} ${dd.text} ${dd.word}`;
  const verdict = dd.good == null ? "" : dd.good ? " · 더 좋음" : " · 더 나쁨";
  return h("small", {class: ["kd-d", dd.tone], title: `대조(-${CONTROL_ROLE})와 비교한 차이`}, long ? `대조보다 ${core}${verdict}` : core);
}
function valueEl(c, k, best) {
  const v = c.get(k);
  if (v == null) return h("span", {class: "muted"}, k.n === 0 && c.key !== "trades" && c.key !== "trades_per_day" ? "거래 없음" : "—");
  const star = best[c.key] && best[c.key].has(k.role);
  return h("span", {class: ["kd-v", c.big || c.tone ? tone(v) : ""]}, star ? h("span", {class: "kd-star", title: "메인 종류들 중 가장 좋음"}, "★ ") : null, c.show(v));
}
function tableView(S, best) {
  const rows = [];
  for (const g of GROUP_ORDER) {
    const ks = S.kinds.filter((k) => k.group === g);
    if (!ks.length) continue;
    rows.push(h("tr", {class: "kd-grp"}, h("th", {class: "l", colspan: String(COLS.length + 1)}, GROUP_KO[g], h("small", null, ` · ${GROUP_HELP[g]}`))));
    for (const k of ks) {
      rows.push(h("tr", {class: ["kd-row", `kd-${k.group}`, k.role === LIVE_ROLE ? "kd-live" : "", k.role === COIN_ROLE ? "kd-coin" : ""]}, nameCell(k, S),
        COLS.map((c) => {
          const dd = c.key === "trades" ? null : diffOf(c, k, S.ctl);
          const star = c.get(k) != null && best[c.key] && best[c.key].has(k.role);
          return h("td", {class: ["num", star ? "kd-best" : ""]}, valueEl(c, k, best), dd ? diffEl(dd, false) : null,
            c.key === "trades" && k.n > 0 && k.n < SMALL_N ? h("small", {class: "muted"}, "표본 적음") : null);
        })));
    }
  }
  return h("div", {class: "tbl-wrap"}, h("table", {class: "tbl kd-tbl"}, h("caption", {class: "sr"}, "메인 · 대조 · 연구용 계좌 종류별 성적"),
    h("thead", null, h("tr", null, h("th", {class: "l", scope: "col"}, "종류"), COLS.map((c) => h("th", {scope: "col", title: c.help}, colLabel(c, S.d))))),
    h("tbody", null, rows)));
}
function kindCard(k, S, best) {
  const mean = COLS.find((c) => c.key === "mean_roe");
  const dd = diffOf(mean, k, S.ctl);
  const small = k.n > 0 ? sampleNote(k.n) : null;
  return h("article", {class: ["kd-kcard", `kd-${k.group}`, k.role === LIVE_ROLE ? "kd-live" : ""], "aria-label": k.name},
    h("div", {class: "kd-kh"}, groupChip(k.group), k.role === LIVE_ROLE ? ui.pill("실전 후보", "accent") : null, h("b", null, k.name),
      h("small", {class: "muted"}, `${k.suffix}${num(k.accounts) != null ? ` · ${fmt.int(k.accounts)}개 후보` : ""}`)),
    k.role === COIN_ROLE ? h("p", {class: "note"}, "방향 실력 확인용: 진입 방향을 동전으로 정한 짝") : null,
    h("div", {class: "kd-kbig"}, h("span", {class: "kd-kl"}, "거래당 순수익"), h("b", {class: "num"}, valueEl(mean, k, best)),
      dd ? diffEl(dd, true) : k === S.ctl ? h("small", {class: "muted"}, "비교 기준") : null),
    h("dl", {class: "kd-kgrid"}, COLS.filter((c) => c.key !== "mean_roe").map((c) => {
      const d2 = c.key === "trades" ? null : diffOf(c, k, S.ctl);
      return h("div", {class: best[c.key] && c.get(k) != null && best[c.key].has(k.role) ? "kd-best" : ""}, h("dt", {title: c.help}, colLabel(c, S.d)),
        h("dd", {class: "num"}, valueEl(c, k, best), d2 ? diffEl(d2, false) : null));
    })),
    small ? h("p", {class: "note"}, small) : null);
}
function cardView(S, best) {
  return h("div", {class: "kd-cardsec"}, GROUP_ORDER.map((g) => {
    const ks = S.kinds.filter((k) => k.group === g);
    if (!ks.length) return null;
    const grid = h("div", {class: "kd-cards"}, ks.map((k) => kindCard(k, S, best)));
    return h("div", {class: "kd-gsec"}, h("h3", {class: "kd-gh"}, GROUP_KO[g], h("small", null, ` · ${GROUP_HELP[g]}`)),
      g === "research" ? ui.disclosure(`연구용 ${ks.length}개 보기`, grid) : grid);
  }));
}

export async function mount(el, ctx) {
  el.classList.add("kd");
  const root = h("div", {class: "kd-root"});
  const saved = local.get("versus-view", null);
  const st = {view: saved === "card" || saved === "table" ? saved : (typeof innerWidth === "number" && innerWidth < 760 ? "card" : "table"), d: null};
  const seg = ui.seg([{id: "table", label: "표"}, {id: "card", label: "카드"}], st.view, (v) => { st.view = v; local.set("versus-view", v); paint(); }, {label: "보기"});
  const head = ui.screenHead("메인 vs 대조", "새 청산 방법이 원래 방식(대조)보다 나은지");
  const sub = head.querySelector(".sub");
  el.append(head, root);
  put(root, ui.missing("종류별 숫자"));

  function paint() {
    const d = st.d;
    const g = gate(d);
    if (g.state !== "ok") { put(root, gateNode(g)); return; }
    seg.set(st.view);
    const S = sumOf(g.kinds, d);
    const best = bestMain(g.kinds);
    const accounts = g.kinds.reduce((a, k) => a + (num(k.accounts) || 0), 0);
    sub.textContent = `계좌 종류 ${fmt.int(g.kinds.length)}가지${accounts ? ` · 계좌 ${fmt.int(accounts)}개` : ""} · 새 청산 방법이 원래 방식(대조)보다 나은지`;
    const dsIn = g.kinds.some((k) => k.ds_in_roe === true), dsOut = g.kinds.some((k) => k.ds_in_roe === false);
    put(root, hero(S), readGuide(),
      ui.card({plate: "종류별 성적", sub: `${GROUP_KO.main} · ${GROUP_KO.control} · ${GROUP_KO.research} · ★ = 메인 중 가장 좋음 · ▲▼ = 대조와의 차이`, acts: seg, cls: "kd-tcard"},
        picksNote(S), st.view === "card" ? cardView(S, best) : tableView(S, best),
        h("p", {class: "note"}, `거래당 순수익 · 평균 이익 · 평균 손실은 거래 한 번의 ROE(증거금 대비)입니다. 잔고 수익률은 ${startTxt(d)}에서 시작한 잔고의 변화입니다 (닫힌 거래까지, 금액이 보이는 계좌만).`),
        dsIn ? h("p", {class: "note"}, "ROE 숫자에는 딥시크 거래도 들어 있습니다.") : null,
        dsOut ? h("p", {class: "note"}, "평균 이익 · 평균 손실 · 거래당 순수익 · 낙폭 · 잔고 수익률은 딥시크를 뺀 숫자입니다 (딥시크 금액은 숨김 설정). 거래 수와 승률에는 딥시크도 들어갑니다.") : null),
      coinBox(S), ruleBox(),
      h("p", {class: "assume"}, "모의 계좌입니다 (가상 돈). 실제 시세로 계산하고 수수료 · 슬리피지 · 펀딩을 뺍니다. 주문은 넣지 않습니다."));
  }
  ctx.onLeague((d) => { st.d = d; paint(); });
}

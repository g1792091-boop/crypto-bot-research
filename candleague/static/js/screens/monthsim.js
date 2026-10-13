// #/monthsim 한 달 시뮬 (owners 10/13): the owners' "luck calculator". "If the record so far went on for a month, what could $1,000 become,
// and does a coin flip get as far?" The goal is x4 a month and the 5-year studies found no direction skill, so this screen's job is to make
// luck and skill VISIBLE and honest: it never promises anything and decides nothing (the pass / fail verdict lives on the 판정 screen).
// Top to bottom: the rule box (what this is and is not, always, even before the data exists), one sentence from the server (counts and the
// median only), for 실전 후보 and 대조 a range bar from 5% to 95% with the median marked, a tick at x1 and at the x4 goal and the coin twin's
// bar under each in a neutral colour (every number also written), the small table (2배 · 4배 · 반토막 · 손실 shares; cards on a phone), the
// "단일 후보 하나는 이만큼 갈린다" line, a word list for beginners and the honest limits.
// Data: the snapshot's ``monthsim`` (candleague/monthsim.py monthsim_views, written next to ``decision`` in the owner-exit league).
// HONESTY: a status "few" kind shows the "아직 자료가 모자랍니다 (N일, M건 · 7일 · 30건부터)" box and no number of a range; every number may be
// null and then reads "—", never 0; colour is never the only sign (each bar has its words and numbers, the coin bars are hatched); dollars
// come from the snapshot's equity0 (no start wallet is written here). DeepSeek money is left out by the server unless the money switch is on.
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {hasLineup, notReady, oldLeagueBox} from "./pairs.js";
import {kindName, startTxt} from "./versus.js";

export const css = ["scr/kinds.css", "scr/monthsim.css"];

export const DEFAULTS = {horizon: 30, boot: 2000, goal: 4, minDays: 7, minTrades: 30, ci: 0.9};
export const PAIR_ORDER = ["live", "control"];
export const PAIR_KO = {live: "실전 후보", control: "대조"};
const PAIR_OF_SUFFIX = {"-fq": "live", "-fqc": "live", "-ld": "control", "-ldc": "control"};
/** The server's honest limits (candleague/monthsim.notes_ko, same order and words); used when the snapshot has none. */
export const NOTES_DEFAULT = [
  "하루하루가 서로 독립이라고 보고 섞습니다. 실제 시장은 며칠씩 한 방향으로 이어지므로, 실제로 나올 범위는 여기 보이는 범위보다 넓을 수 있습니다.",
  "계좌 여러 개를 같은 비중으로 섞은 값이라, 계좌(후보) 하나만 쓸 때보다 범위가 좁습니다. ‘단일 후보’ 줄은 후보마다 지금 성적이 서로 얼마나 다른지 보여 줍니다 (앞으로의 운은 들어 있지 않습니다).",
  "닫힌 거래만 셉니다. 아직 열려 있는 포지션과 오늘(진행 중인 날)은 넣지 않았습니다.",
  `날 수가 적으면 범위가 매우 넓고 쉽게 틀립니다. 거래가 있던 날이 ${DEFAULTS.minDays}일보다 적거나 거래가 ${DEFAULTS.minTrades}건보다 적으면 계산하지 않습니다.`,
  "지금까지의 날들을 무작위로 다시 섞어 본 결과이지, 앞으로의 약속이나 예측이 아닙니다.",
];

const num = (x) => (fmt.bad(x) ? null : Number(x));
const cnt = (n) => `${fmt.int(n)}건`;

// ---------------------------------------------------------------- number words
/** A multiple of the start wallet: 1.2 -> "1.20배", 12.34 -> "12.3배", 1234 -> "1,234배"; null -> "—". */
export function mult(x, sign = false) {
  const v = num(x);
  if (v == null) return "—";
  const a = Math.abs(v);
  return `${fmt.num(v, a < 9.995 ? 2 : a < 99.95 ? 1 : 0, sign)}배`;
}
/** What a multiple of the snapshot's start wallet is in dollars ("$1,200"); null without a wallet (no figure is made up). */
export function usd(m, e0) {
  const v = num(m), w = num(e0);
  if (v == null || w == null || w <= 0) return null;
  const x = v * w;
  return x < 10 ? `$${fmt.num(x, 2)}` : `$${fmt.int(x)}`;
}
/** A share of the simulated months: 0.123 -> "12%"; under 1% "1% 미만", over 99% "99% 넘음" (2,000 draws cannot say 0 or 100); null -> "—". */
export function share(p) {
  const v = num(p);
  if (v == null) return "—";
  return v < 0.01 ? "1% 미만" : v > 0.99 ? "99% 넘음" : `${Math.round(v * 100)}%`;
}
/** The same as a count out of 100, ending the sentence: "100번 중 63번입니다". */
export function outOf100(p) {
  const v = num(p);
  if (v == null) return "—";
  return v < 0.01 ? "100번 중 1번도 안 됩니다" : v > 0.99 ? "100번 중 99번이 넘습니다" : `100번 중 ${Math.round(v * 100)}번입니다`;
}

// ---------------------------------------------------------------- the snapshot's ``monthsim``
function normKind(k) {
  const P = k.percentiles && typeof k.percentiles === "object" ? k.percentiles : null;
  const p = P ? {p05: num(P.p05), p25: num(P.p25), p50: num(P.p50), p75: num(P.p75), p95: num(P.p95)} : null;
  const usable = p && p.p05 != null && p.p50 != null && p.p95 != null;
  const S = k.single_account && typeof k.single_account === "object" ? k.single_account : null;
  const E = k.edge_vs_coin && typeof k.edge_vs_coin === "object" ? k.edge_vs_coin : null;
  const edge = E && E.status === "ok" && num(E.diff) != null ? {diff: num(E.diff), lo: num(E.lo), hi: num(E.hi), real: num(E.real_median), coin: num(E.coin_median),
    zero: E.zero_in_interval === true, reach: num(E.coin_reaches_real_median), beats: num(E.p_real_beats_coin), ci: num(E.ci_level) ?? DEFAULTS.ci} : null;
  return {
    suffix: k.suffix, role: k.role, label_ko: k.label_ko, short_ko: k.short_ko, name: kindName(k),
    pair: PAIR_ORDER.includes(k.pair) ? k.pair : PAIR_OF_SUFFIX[k.suffix] || "control", isCoin: k.is_coin === true, twin: k.twin || null,
    status: k.status === "none" ? "none" : k.status === "ok" && usable ? "ok" : "few",
    days: Math.max(0, num(k.days) ?? 0), n: Math.max(0, num(k.n_trades) ?? 0), accounts: Math.max(0, num(k.n_accounts) ?? 0),
    few: typeof k.few_ko === "string" && k.few_ko ? k.few_ko : null, obs: num(k.observed_multiple), linear: num(k.linear_multiple),
    p: usable ? p : null, x2: num(k.p_x2), x4: num(k.p_x4), half: num(k.p_below_half), loss: num(k.p_loss),
    single: S && num(S.n) != null && num(S.p50) != null ? {n: num(S.n), p05: num(S.p05), p50: num(S.p50), p95: num(S.p95), min: num(S.min), max: num(S.max)} : null,
    edge,
  };
}
/** The monthsim block with every missing number filled by the default; null when it is absent or malformed. */
export function normMonth(x) {
  if (!x || typeof x !== "object" || Array.isArray(x) || !Array.isArray(x.kinds)) return null;
  const kinds = x.kinds.filter((k) => k && typeof k === "object" && typeof k.suffix === "string" && k.suffix).map(normKind);
  if (!kinds.length) return null;
  return {
    horizon: num(x.horizon_days) ?? DEFAULTS.horizon, boot: num(x.boot) ?? DEFAULTS.boot, goal: num(x.goal_multiple) ?? DEFAULTS.goal,
    minDays: num(x.min_days) ?? DEFAULTS.minDays, minTrades: num(x.min_trades) ?? DEFAULTS.minTrades, ci: num(x.ci_level) ?? DEFAULTS.ci,
    equity0: num(x.equity0), windowDays: Math.max(0, num(x.window_days) ?? 0), dsIn: x.ds_in_stats === true,
    headline: typeof x.headline_ko === "string" ? x.headline_ko : "",
    notes: Array.isArray(x.note_ko) && x.note_ko.length ? x.note_ko.map(String) : null, kinds,
  };
}
/** What the screen can show: {state, M}.  wait  no snapshot yet   old  the old league (no lineup): this screen is for the new one
 *  prep  the new league, the engine has not written ``monthsim`` yet   ok  it is here */
export function gate(d) {
  if (!d || !d.accounts) return {state: "wait", M: null};
  const M = normMonth(d.monthsim);
  if (M) return {state: "ok", M};
  return {state: hasLineup(d) ? "prep" : "old", M: null};
}
const e0Of = (M, d) => (num(d && d.equity0) != null && Number(d.equity0) > 0 ? Number(d.equity0) : M && M.equity0);
const kindsOf = (M, pid) => ({real: M.kinds.find((k) => k.pair === pid && !k.isCoin) || null, coin: M.kinds.find((k) => k.pair === pid && k.isCoin) || null});
const fewText = (k, M) => k.few || `아직 자료가 모자랍니다 (${fmt.int(k.days)}일, ${fmt.int(k.n)}건 · ${fmt.int(M.minDays)}일 · ${fmt.int(M.minTrades)}건부터)`;

// ---------------------------------------------------------------- the shared log axis of the bars
/** A log scale over every bar of the screen: {lo, hi, ticks: [{m, at (percent), label, cls}]}. x1 (본전) and the x4 goal are always on it. */
export function makeScale(kinds, goal) {
  const v = [];
  for (const k of kinds) if (k.status === "ok") v.push(k.p.p05, k.p.p95);
  const lo = Math.max(0.05, Math.min(0.5, (v.length ? Math.min(...v) : 1) * 0.85));
  const hi = Math.min(1000, Math.max(goal * 1.15, (v.length ? Math.max(...v) : goal) * 1.15));
  const sc = {lo, hi, ticks: []};
  const at = (m) => pos(sc, m);
  const want = [[1, "1배", "one"], [goal, `${fmt.num(goal, 0)}배 목표`, "goal"], [2, "2배", ""], [0.5, "0.5배", ""], [10, "10배", ""], [0.25, "0.25배", ""], [0.1, "0.1배", ""], [100, "100배", ""]];
  for (const [m, label, cls] of want) {
    if (m < lo || m > hi || sc.ticks.some((t) => Math.abs(t.at - at(m)) < 17 || t.m === m)) continue;
    sc.ticks.push({m, at: at(m), label, cls});
  }
  return sc;
}
/** The place (percent from the left) of a multiple on the scale; a value off the scale sits at its edge. */
export function pos(sc, m) {
  const v = Math.max(Number(m) || 0, sc.lo);
  return Math.max(0, Math.min(100, (100 * (Math.log(v) - Math.log(sc.lo))) / (Math.log(sc.hi) - Math.log(sc.lo))));
}
const pc1 = (x) => `${x.toFixed(2)}%`;

// ---------------------------------------------------------------- the boxes
function ruleBox(M) {
  const boot = fmt.int(M ? M.boot : DEFAULTS.boot), days = M ? M.horizon : DEFAULTS.horizon;
  const items = [
    ["이 화면은", `지금까지 하루하루의 성적을 무작위로 섞어서, ‘이 성적이 한 달(${days}일) 이어진다면’ 결과를 ${boot}번 만들어 봅니다. 그 가운데 90%가 들어가는 범위(5% ~ 95%)와 중앙값을 보여 줍니다.`],
    ["동전 짝도 같이", "방향을 동전 던지기로 정한 짝 계좌도 똑같이 계산합니다. 동전도 비슷하게 나오면 실력이 아니라 운일 수 있습니다."],
    ["이 화면이 아닌 것", "예측도 약속도 아닙니다. 통과 · 실패를 매기는 판정에도 쓰지 않는 참고용입니다 (판정은 판정 화면에서 28일째 한 번)."],
    ["믿기 전에", `하루하루가 서로 무관하다고 섞은 값이고 열린 포지션은 뺐습니다. 거래가 있던 날이 ${fmt.int(M ? M.minDays : DEFAULTS.minDays)}일 · 거래가 ${fmt.int(M ? M.minTrades : DEFAULTS.minTrades)}건보다 적으면 계산하지 않습니다. 한계는 맨 아래에 있습니다.`],
  ];
  return ui.card({plate: "이 화면은 무엇인가요", sub: "운 계산기 · 약속이 아닙니다", cls: "kd-rule ms-rule"},
    h("ol", {class: "kd-list kd-rules ms-rules"}, items.map(([a, b]) => h("li", null, h("b", null, a), `: ${b}`))));
}
function hero(M, d) {
  const live = kindsOf(M, "live").real, first = live && live.status !== "none" ? live : kindsOf(M, "control").real;
  const ok = !!first && first.status === "ok", e0 = e0Of(M, d);
  const line = ok && first.x4 != null && first.loss != null
    ? `${fmt.int(M.boot)}번 중 ${fmt.num(M.goal, 0)}배 이상은 ${share(first.x4)}, 1배 미만(손실)은 ${share(first.loss)}입니다${usd(M.goal, e0) ? ` (목표 ${fmt.num(M.goal, 0)}배 = ${usd(M.goal, e0)})` : ""}.`
    : null;
  return h("section", {class: "card hero dl-verdict s2a-hero kd-hero ms-hero", "aria-label": "한 줄 결론"},
    h("div", {class: "s2a-hrow"}, ui.plate("한 줄 결론")),
    h("p", {class: ["dl-vbig", ok ? "" : "warn"]}, M.headline || "아직 자료가 없습니다."),
    line ? h("p", {class: "dl-vline"}, `${first === live ? PAIR_KO.live : PAIR_KO.control}: ${line}`) : null,
    M.windowDays ? h("p", {class: "note"}, `리그 시작부터 ${fmt.int(M.windowDays)}일치 · 오늘 진행 중인 날은 뺐습니다.`) : null,
    h("p", {class: "note"}, "모의 거래 기록을 섞어 본 것입니다. 앞으로를 약속하는 숫자가 아닙니다."));
}

// ---------------------------------------------------------------- the range bars
const swatch = (cls) => h("i", {class: ["ms-sw", cls], "aria-hidden": "true"});
function barLegend(M) {
  return h("ul", {class: "ms-legend", "aria-label": "막대 읽는 법"},
    h("li", null, swatch("range"), "막대 = 5% ~ 95%"), h("li", null, swatch("med"), "표시 = 중앙값"),
    h("li", null, swatch("one"), "본전(1배)"), h("li", null, swatch("goal"), `목표(${fmt.num(M.goal, 0)}배)`), h("li", null, swatch("coin"), "빗금 = 동전 짝"));
}
function bar(k, sc, cls) {
  const p = k.p, lo = pos(sc, p.p05), hi = pos(sc, p.p95), med = pos(sc, p.p50);
  const t1 = sc.ticks.find((t) => t.m === 1), tg = sc.ticks.find((t) => t.cls === "goal");
  const label = `${k.isCoin ? "동전 짝" : PAIR_KO[k.pair]}: 5% ${mult(p.p05)}, 중앙값 ${mult(p.p50)}, 95% ${mult(p.p95)}`;
  return h("div", {class: ["ms-bar", cls], role: "img", "aria-label": label, dataset: {suffix: k.suffix, p05: p.p05, p50: p.p50, p95: p.p95}},
    h("div", {class: "ms-track"},
      t1 ? h("i", {class: "ms-tick one", style: {"--at": pc1(t1.at)}}) : null, tg ? h("i", {class: "ms-tick goal", style: {"--at": pc1(tg.at)}}) : null,
      h("i", {class: ["ms-range", lo <= 0.01 ? "clip-l" : "", hi >= 99.99 ? "clip-r" : ""], style: {"--l": pc1(lo), "--w": pc1(Math.max(hi - lo, 0.4))}}),
      h("i", {class: "ms-med", style: {"--at": pc1(med)}})));
}
function numCell(label, at, m, e0, strong) {
  const d = usd(m, e0);
  return h("div", {class: strong ? "ms-n strong" : "ms-n"}, h("dt", null, `${label} `, h("small", null, at)), h("dd", null, h("b", null, mult(m)), d ? h("small", null, d) : null));
}
function reality(k, M) {
  if (k.obs == null) return null;
  const now = `지금까지 실제로는 ${mult(k.obs)} (${fmt.int(M.windowDays)}일)`;
  return h("p", {class: "ms-real-line"}, k.linear != null ? `${now} · 지금 속도 그대로 ${M.horizon}일 직선으로 늘리면 ${mult(k.linear)}` : now);
}
function krow(k, sc, M, e0) {
  const real = !k.isCoin;
  const head = h("div", {class: "ms-kh"}, h("b", null, real ? k.name : "동전 짝"), k.isCoin ? ui.pill("방향을 동전으로", "thin") : null,
    h("small", {class: "muted"}, `${fmt.int(k.days)}일 · ${cnt(k.n)}`));
  if (k.status === "none") return h("div", {class: ["ms-krow", "ms-none", real ? "ms-real" : "ms-coin"], dataset: {suffix: k.suffix, status: "none"}}, head,
    h("p", {class: "note"}, "이 종류의 계좌가 이 리그에 없습니다."));
  if (k.status !== "ok") return h("div", {class: ["ms-krow", "ms-few", real ? "ms-real" : "ms-coin"], dataset: {suffix: k.suffix, status: "few"}}, head,
    h("p", {class: "ms-fewt"}, fewText(k, M)), k.obs != null ? h("p", {class: "ms-real-line"}, `지금까지 실제로는 ${mult(k.obs)} (${fmt.int(M.windowDays)}일)`) : null);
  return h("div", {class: ["ms-krow", real ? "ms-real" : "ms-coin"], dataset: {suffix: k.suffix, status: "ok"}}, head,
    bar(k, sc, `${real ? "ms-b-" + k.pair : "ms-b-coin"}`),
    h("dl", {class: "ms-nums"}, numCell("나쁜 쪽", "5%", k.p.p05, e0), numCell("중앙값", "50%", k.p.p50, e0, true), numCell("좋은 쪽", "95%", k.p.p95, e0)),
    reality(k, M));
}
function axisEl(sc) {
  return h("div", {class: "ms-axis", "aria-hidden": "true"}, sc.ticks.map((t) => h("span", {class: ["ms-at", t.cls], style: {"--at": pc1(t.at)}}, t.label)));
}
/** The comparison with the coin twin in words: the difference of the medians, its interval, and how often the coin gets as far. */
function edgeBox(real, coin, M) {
  if (!real || real.status === "none" || !coin || coin.status === "none") return null;
  const e = real.edge;
  if (!e) return h("p", {class: "ms-edge note"}, "동전 짝과의 비교는 두 쪽 모두 자료가 쌓이면 나옵니다.");
  const word = e.lo == null || e.hi == null || e.zero ? ["구분 안 됨", "thin"] : e.lo > 0 ? ["동전보다 위", "good"] : ["동전보다 아래", "bad"];
  const why = word[0] === "구분 안 됨" ? "구간에 0이 들어 있어, 이 자료만으로는 동전과 다르다고 말하기 어렵습니다 (운일 수 있습니다)."
    : word[0] === "동전보다 위" ? "구간이 모두 0보다 크지만 참고용입니다: 날 수가 적고 하루하루를 독립으로 본 계산입니다."
      : "구간이 모두 0보다 작아, 이 자료에서는 동전보다 못합니다.";
  return h("div", {class: "ms-edge", dataset: {pair: real.pair, edge: word[0]}},
    h("p", {class: "ms-edge-h"}, ui.pill(word[0], word[1]), h("b", null, `동전 짝과 중앙값 차이 ${mult(e.diff, true)}`),
      e.lo != null && e.hi != null ? h("small", {class: "muted"}, `${Math.round(e.ci * 100)}% 구간 ${mult(e.lo, true)} ~ ${mult(e.hi, true)}`) : null),
    h("p", {class: "note"}, why),
    e.reach != null ? h("p", {class: "note"}, `동전 짝의 달 중 ${PAIR_KO[real.pair]}의 중앙값(${mult(e.real)}) 이상 나온 것은 ${outOf100(e.reach)}.`) : null);
}
function groupEl(M, pid, sc, e0) {
  const {real, coin} = kindsOf(M, pid);
  if (!real) return null;
  return h("section", {class: ["ms-grp", `ms-g-${pid}`], dataset: {pair: pid}, "aria-label": PAIR_KO[pid]},
    h("div", {class: "ms-gh"}, h("b", null, PAIR_KO[pid]), h("small", {class: "muted"}, `${real.name} ${real.suffix}${coin ? ` · 동전 짝 ${coin.suffix}` : ""}`)),
    krow(real, sc, M, e0), coin ? krow(coin, sc, M, e0) : null, real.status === "ok" || (coin && coin.status === "ok") ? axisEl(sc) : null, edgeBox(real, coin, M));
}
function barsCard(M, d) {
  const sc = makeScale(M.kinds, M.goal), e0 = e0Of(M, d);
  const groups = PAIR_ORDER.map((p) => groupEl(M, p, sc, e0)).filter(Boolean);
  return ui.card({plate: `한 달(${M.horizon}일) 뒤 범위`, sub: `${usd(1, e0) ? usd(1, e0) + "에서 시작하면" : "시작 잔고 기준 배수"} · ${fmt.int(M.boot)}번 중 가운데 90%`, cls: "kd-tcard ms-bars", id: "ms-bars"},
    barLegend(M), h("div", {class: "ms-chart"}, groups.length ? groups : ui.none("비교할 종류가 아직 없습니다")));
}

// ---------------------------------------------------------------- the small table (or cards on a phone)
const COLS = [
  {id: "x2", label: "2배 이상", help: "시뮬레이션 달 중 2배 이상으로 끝난 몫", get: (k) => k.x2},
  {id: "x4", label: "4배 이상", sub: "목표", help: "시뮬레이션 달 중 4배 이상(목표)으로 끝난 몫", get: (k) => k.x4},
  {id: "half", label: "반토막 이하", help: "시뮬레이션 달 중 0.5배보다 적게 끝난 몫", get: (k) => k.half},
  {id: "loss", label: "손실", sub: "1배 미만", help: "시뮬레이션 달 중 1배보다 적게(손실로) 끝난 몫", get: (k) => k.loss},
];
const nameOf = (k) => (k.isCoin ? "동전 짝" : k.name);
function nameCell(k) {
  return h("td", {class: "l kd-nm"}, h("div", {class: "kd-nmh"}, h("b", null, nameOf(k)), !k.isCoin && k.pair === "live" ? ui.pill("실전 후보", "accent") : null),
    h("small", {class: "muted"}, `${PAIR_KO[k.pair]}${k.isCoin ? " · 방향을 동전으로" : ""} · ${k.suffix}`));
}
function tableView(M) {
  const th = (c) => h("th", {scope: "col", title: c.help}, c.label, c.sub ? h("small", {class: "kd-thsub"}, c.sub) : null);
  const rows = M.kinds.map((k) => h("tr", {class: ["kd-row", "ms-row", k.isCoin ? "kd-coin" : ""], dataset: {suffix: k.suffix, status: k.status, pair: k.pair}},
    nameCell(k), h("td", {class: "num"}, h("span", {class: "kd-v"}, `${fmt.int(k.days)}일`), h("small", {class: "muted"}, cnt(k.n))),
    k.status === "ok"
      ? [h("td", {class: "num"}, h("span", {class: "kd-v"}, mult(k.p.p50))), COLS.map((c) => h("td", {class: "num"}, h("span", {class: "kd-v"}, share(c.get(k)))))]
      : h("td", {class: "l ms-fewcell", colspan: String(COLS.length + 1)}, k.status === "none" ? "이 종류의 계좌가 이 리그에 없습니다" : fewText(k, M))));
  return h("div", {class: "tbl-wrap"}, h("table", {class: "tbl kd-tbl ms-tbl"}, h("caption", {class: "sr"}, "한 달 시뮬 표"),
    h("thead", null, h("tr", null, h("th", {class: "l", scope: "col"}, "종류"), h("th", {scope: "col", title: "거래가 있던 날 수와 닫힌 거래 수"}, "자료"),
      h("th", {scope: "col", title: "시뮬레이션 달의 가운데 결과"}, "중앙값"), COLS.map(th))),
    h("tbody", null, rows)));
}
function cardView(M, d) {
  const e0 = e0Of(M, d);
  return h("div", {class: "kd-cards ms-cards"}, M.kinds.map((k) => h("article", {class: ["kd-kcard", "ms-kcard", k.isCoin ? "kd-coin" : ""], "aria-label": `${PAIR_KO[k.pair]} ${nameOf(k)}`,
    dataset: {suffix: k.suffix, status: k.status, pair: k.pair}},
  h("div", {class: "kd-kh"}, h("b", null, nameOf(k)), !k.isCoin && k.pair === "live" ? ui.pill("실전 후보", "accent") : null, k.isCoin ? ui.pill("방향을 동전으로", "thin") : null,
    h("small", {class: "muted"}, `${PAIR_KO[k.pair]} · ${k.suffix} · ${fmt.int(k.days)}일 · ${cnt(k.n)}`)),
  k.status === "ok"
    ? [h("div", {class: "kd-kbig"}, h("span", {class: "kd-kl"}, "중앙값"), h("b", {class: "num"}, mult(k.p.p50)), usd(k.p.p50, e0) ? h("small", {class: "muted"}, usd(k.p.p50, e0)) : null),
      h("dl", {class: "kd-kgrid"}, COLS.map((c) => h("div", null, h("dt", null, c.sub ? `${c.label} (${c.sub})` : c.label), h("dd", {class: "num"}, share(c.get(k))))))]
    : h("p", {class: "ms-fewt"}, k.status === "none" ? "이 종류의 계좌가 이 리그에 없습니다" : fewText(k, M)))));
}
function tableCard(M, d, view, seg) {
  return ui.card({plate: "몫으로 보면", sub: `시뮬레이션 ${fmt.int(M.boot)}번 중 몇 %인가`, acts: seg, cls: "kd-tcard ms-table", id: "ms-table"},
    view === "card" ? cardView(M, d) : tableView(M),
    h("p", {class: "note"}, "동전 짝의 몫이 실전 후보와 비슷하면, 그 성적은 실력보다 운일 가능성이 큽니다. 몫은 ‘그럴 가능성’이지 확률 약속이 아닙니다."));
}

// ---------------------------------------------------------------- single picks
function singleCard(M) {
  const rows = M.kinds.filter((k) => k.status === "ok" && k.single);
  return ui.card({plate: "단일 후보 하나는 이만큼 갈린다", sub: "후보 하나씩 따로 본 성적을 30일로 늘린 값", cls: "kd-tcard ms-single", id: "ms-single"},
    h("p", {class: "note"}, "위 막대는 계좌 여러 개를 평균한 값입니다. 여기는 계좌(후보) 하나씩 지금까지 성적을 30일로 늘려 놓고 서로 얼마나 다른지 본 것입니다. 시뮬레이션이 아니라서 앞으로의 운은 들어 있지 않고, 후보 하나가 실제로 겪을 범위는 이보다 더 넓습니다."),
    rows.length ? h("ul", {class: "ms-slist"}, rows.map((k) => h("li", {class: ["ms-srow", k.isCoin ? "ms-coin" : ""], dataset: {suffix: k.suffix}},
      h("b", null, k.isCoin ? `동전 짝 (${PAIR_KO[k.pair]})` : `${PAIR_KO[k.pair]} · ${k.name}`), h("small", {class: "muted"}, `계좌 ${fmt.int(k.single.n)}개 중`),
      h("span", {class: "ms-sline"}, `나쁜 쪽 5% ${mult(k.single.p05)} · 가운데 ${mult(k.single.p50)} · 좋은 쪽 95% ${mult(k.single.p95)}`)))) : ui.none("자료가 쌓이면 나옵니다"));
}

// ---------------------------------------------------------------- words, limits, closing
function legend(M) {
  const dt = (t) => h("dt", null, t);
  return ui.card({plate: "낱말 뜻", sub: "처음 보는 분을 위한 설명"},
    h("dl", {class: "kd-legend"},
      h("div", null, dt("배수 (1.2배)"), h("dd", null, "시작 잔고의 몇 배가 되었나. 1배는 본전, 2배는 두 배, 0.5배는 반토막입니다. 예: 100달러가 120달러가 되면 1.2배.")),
      h("div", null, dt("중앙값"), h("dd", null, `${fmt.int(M.boot)}번의 결과를 줄 세웠을 때 정확히 가운데 값. 절반은 이보다 좋고 절반은 나쁩니다. 평균이 아닙니다.`)),
      h("div", null, dt("5% ~ 95% 범위"), h("dd", null, "가장 나쁜 쪽 5%와 가장 좋은 쪽 5%를 뺀 가운데 90%가 들어가는 범위. 이 밖의 결과도 나올 수 있습니다.")),
      h("div", null, dt("동전 짝"), h("dd", null, "같은 신호 시각에 롱/숏을 동전 던지기로 정한 계좌. 방향에 실력이 없을 때 어디까지 나오는지 보여 주는 기준선입니다.")),
      h("div", null, dt("2배 · 4배 이상"), h("dd", null, `${fmt.int(M.boot)}번 중 그만큼 이상으로 끝난 몫. 4배가 두 분의 한 달 목표입니다.`)),
      h("div", null, dt("반토막 · 손실"), h("dd", null, "0.5배보다 적게 끝난 몫, 1배보다 적게(돈을 잃고) 끝난 몫.")),
      h("div", null, dt(`구간 (${Math.round(M.ci * 100)}%)`), h("dd", null, "자료가 이만큼뿐일 때 동전과의 중앙값 차이가 흔들리는 범위. 0이 들어 있으면 동전과 다르다고 말하기 어렵습니다.")),
      h("div", null, dt("단일 후보"), h("dd", null, "계좌(후보) 하나만 따로 본 것. 여러 개를 섞은 막대보다 하나는 훨씬 크게 갈립니다.")),
      h("div", null, dt("하루"), h("dd", null, "UTC 날짜 기준이라 한국 시각으로는 오전 9시에 바뀝니다. 날 수는 거래가 끝난 날을 셉니다."))));
}
function limits(M) {
  return ui.card({plate: "솔직한 한계", sub: "이 숫자를 믿기 전에"}, h("ul", {class: "kd-list ms-limits"}, (M.notes || NOTES_DEFAULT).map((t) => h("li", null, t))));
}
function closing(M, d) {
  const wallet = Number(d && d.equity0) > 0 ? `모든 계좌는 ${startTxt(d)}에서 시작하는 모의 계좌입니다 (가상 돈). ` : "모의 계좌입니다 (가상 돈). ";
  return [
    h("p", {class: "note"}, M.dsIn ? "이 계산에는 딥시크 계좌도 들어 있습니다." : "이 계산은 딥시크를 뺀 후보만으로 했습니다 (딥시크 금액은 숨김 설정이라 쓰지 않습니다)."),
    h("p", {class: "assume"}, `${wallet}실제 주문은 넣지 않습니다.`),
  ];
}
function missingBox(g, d) {
  if (g.state === "old") return oldLeagueBox(d, "한 달 시뮬 화면은 아직 없습니다.");
  if (g.state === "prep") {
    return ui.card({plate: "데이터 준비 중"},
      h("p", {class: "dl-vline"}, "한 달 시뮬 기록은 아직 없습니다. 위 설명은 그대로 적용됩니다."),
      h("p", {class: "note"}, "엔진이 기록을 쓰면 (5분마다) 저절로 나타납니다. 거래가 있던 날이 7일은 쌓여야 숫자가 나옵니다."));
  }
  return notReady("후보 리그 기록이 아직 없습니다.");
}

export async function mount(el, ctx) {
  el.classList.add("kd", "ms");
  const root = h("div", {class: "kd-root"});
  const saved = local.get("monthsim-view", null);
  const st = {view: saved === "card" || saved === "table" ? saved : (typeof innerWidth === "number" && innerWidth < 760 ? "card" : "table"), d: null};
  const seg = ui.seg([{id: "table", label: "표"}, {id: "card", label: "카드"}], st.view, (v) => { st.view = v; local.set("monthsim-view", v); paint(); }, {label: "보기"});
  const head = ui.screenHead("한 달 시뮬", "지금 성적이 한 달 이어진다면? 동전과 비교하는 운 계산기");
  el.append(head, root);
  put(root, ruleBox(null), ui.missing("한 달 시뮬 기록"));

  function paint() {
    const d = st.d, g = gate(d);
    if (g.state !== "ok") { put(root, ruleBox(null), missingBox(g, d)); return; }
    const M = g.M;
    seg.set(st.view);
    put(root, ruleBox(M), hero(M, d), barsCard(M, d), tableCard(M, d, st.view, seg), singleCard(M), legend(M), limits(M), closing(M, d));
  }
  ctx.onLeague((d) => { st.d = d; paint(); });
}

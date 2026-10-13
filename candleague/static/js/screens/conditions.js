// #/conditions 조건별 성적 (owners 10/13): WHERE does a structure work, and where not? An EXPLORATORY look, never a verdict. The five-year studies
// found no direction skill, so this league only learns where an edge might hide (which weekday, hour, side, coin, chart, BTC trend, volatility)
// without adding accounts. For the 실전 후보 (-fq) and the 대조 (-ld) it sets each condition's mean net ROE per trade against the same kind's
// coin-flip twin (side chosen by a coin at the same signal times) in the SAME bucket. With this many cells some always look good by luck, so
// nothing here passes or fails; it only helps choose what the NEXT pre-registered test (#/decision) should look at.
// Top to bottom: the one-sentence headline with the exploratory caveat (and the reading rules, folded), the two switches (which structure,
// table or cards), then one compact card per dimension: rows = buckets, columns = the structure's mean, the coin twin's mean, the difference
// (▲ / ▼ with the number, a tiny bar) and the trade counts. A bucket with fewer than 30 trades shows "적음" and no mean.
// Data: the snapshot's ``conditions`` (candleague/summary.py conditions_views, written next to ``decision`` in the owner-exit league).
// HONESTY: a sign never rests on colour alone; every number may be null and then reads "—", never 0; the sentences come from the server
// (counts only); DeepSeek money is left out of the figures unless the money switch is on (the server does that; a note says so).
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {hasLineup, notReady, oldLeagueBox} from "./pairs.js";
import {pc, ppTxt, startTxt} from "./versus.js";

export const css = ["scr/kinds.css", "scr/conditions.css"];

export const DEFAULTS = {min_n: 30, ci_level: 0.9};
export const NOTE_DEFAULT = "탐색용입니다. 칸이 많아서 우연히 좋아 보이는 칸이 저절로 생깁니다. 판정에는 쓰지 않고, 다음에 따로 미리 정해서 시험할 것을 고르는 데만 씁니다.";
/** The reading rules (short): shown folded under the headline, open while the data is not there yet. */
export const RULES = [
  ["탐색용", "통과 · 실패를 매기지 않고, 실전에 쓸지 정하는 근거로도 쓰지 않습니다. 판정은 판정 화면의 미리 정한 규칙으로만 합니다."],
  ["무엇을 비교하나", "같은 신호에서 방향을 동전으로 정한 짝 계좌와, 조건별로 나눠 거래당 순수익(ROE) 평균을 비교합니다. 차이 = 실제 평균 − 동전 평균 (플러스면 실제가 낫습니다)."],
  ["칸이 많으면", "아무 실력이 없어도 칸 20개 중 1개쯤은 우연히 좋아 보입니다. 거래가 30건 미만인 칸은 평균을 보이지 않습니다."],
  ["어디에 쓰나", "좋아 보이는 칸이 있으면 그것은 결론이 아니라, 다음에 따로 시험해 볼 후보일 뿐입니다."],
];
const PAIR_HELP = {"-fq": "새로 시험하는 빠른 손절 구조 (실전 후보)", "-ld": "원래 방식인 고정 손절 계단 (대조)"};

const num = (x) => (fmt.bad(x) ? null : Number(x));
const obj = (x) => (x && typeof x === "object" && !Array.isArray(x) ? x : {});

// ---------------------------------------------------------------- the snapshot's ``conditions``
/** The conditions block with every missing piece defaulted; null when it is absent or malformed (no ``dims`` list). */
export function normConditions(x) {
  if (!x || typeof x !== "object" || Array.isArray(x) || !Array.isArray(x.dims)) return null;
  const dims = x.dims.filter((d) => d && typeof d === "object" && Array.isArray(d.buckets)).map((d) => ({
    id: String(d.id ?? ""), ko: String(d.ko ?? d.id ?? ""), hint: typeof d.hint_ko === "string" ? d.hint_ko : "", after: d.after_entry === true,
    buckets: d.buckets.filter((b) => b && typeof b === "object").map((b) => ({id: String(b.id ?? ""), ko: String(b.ko ?? b.id ?? ""),
      hint: typeof b.hint_ko === "string" ? b.hint_ko : "", unknown: b.unknown === true, kinds: obj(b.kinds), diffs: obj(b.diffs)})),
  }));
  const pairs = (Array.isArray(x.pairs) ? x.pairs : []).filter((p) => p && typeof p.real === "string" && typeof p.twin === "string")
    .map((p) => ({real: p.real, twin: p.twin, realKo: String(p.real_ko ?? p.real), twinKo: String(p.twin_ko ?? "동전")}));
  return {
    dims, pairs, minN: num(x.min_n) ?? DEFAULTS.min_n, ci: num(x.ci_level) ?? DEFAULTS.ci_level, days: Math.max(0, num(x.days) ?? 0),
    nDays: num(x.n_days) ?? 0, dsIn: x.ds_in_stats === true, cells: num(x.n_cells) ?? 0, good: num(x.n_good) ?? 0, bad: num(x.n_bad) ?? 0,
    lucky: num(x.expected_lucky) ?? 0, headline: typeof x.headline_ko === "string" ? x.headline_ko : "",
    note: typeof x.note_ko === "string" && x.note_ko ? x.note_ko : NOTE_DEFAULT, trades: obj(x.n_trades),
    kinds: (Array.isArray(x.kinds) ? x.kinds : []).filter((k) => k && typeof k.suffix === "string"),
  };
}
/**
 * What the screen can show: {state, C}.  wait  no snapshot yet   old  the old league (no lineup): this screen is for the new one
 * prep  the new league, the engine has not written ``conditions`` yet   ok  it is here
 */
export function gate(d) {
  if (!d || !d.accounts) return {state: "wait", C: null};
  const C = normConditions(d.conditions);
  if (C) return {state: "ok", C};
  return {state: hasLineup(d) ? "prep" : "old", C: null};
}

// ---------------------------------------------------------------- cells
/** The pair being shown: the chosen real kind if the snapshot has it, else the first (the 실전 후보 comes first). */
export function pickPair(C, want) {
  return C.pairs.find((p) => p.real === want) || C.pairs[0] || null;
}
/** The mean of one kind in one bucket: "+1.2%" (+ the win rate small), or "적음" when the bucket holds fewer than the minimum. */
function meanEl(c, minN) {
  if (!c || num(c.n) == null) return h("span", {class: "muted"}, "—");
  if (c.few === true || num(c.mean) == null) {
    return h("span", {class: "cn-few", title: `거래가 ${fmt.int(c.n)}건뿐이라 평균을 보이지 않습니다 (${fmt.int(minN)}건 이상 필요)`}, "적음");
  }
  const t = pc(c.mean, true);
  return h("span", {class: "cn-m"}, h("span", {class: ["kd-v", fmt.tone(c.mean, t)]}, t),
    num(c.win_rate) == null ? null : h("small", {class: "muted"}, `승률 ${fmt.num(Number(c.win_rate) * 100, 0)}%`));
}
/** ▲ / ▼ + the difference in %p, coloured by sign (the sign is also in the text). */
function diffEl(v) {
  if (num(v) == null) return h("span", {class: "muted"}, "—");
  const t = ppTxt(v), zero = !/[1-9]/.test(t);
  return h("span", {class: ["kd-v", zero ? "" : Number(v) > 0 ? "up" : "down"]}, `${zero ? "＝" : Number(v) > 0 ? "▲" : "▼"} ${t}`);
}
/** The tiny bar: grows right (green) for a plus and left (red) for a minus from the middle, 100% = the biggest difference on the page. */
function barEl(v, max) {
  if (num(v) == null || !(max > 0)) return null;
  const w = Math.min(50, (Math.abs(Number(v)) / max) * 50);
  return h("span", {class: ["cn-bar", Number(v) < 0 ? "neg" : "pos"], "aria-hidden": "true"}, h("i", {style: {"--w": `${w.toFixed(1)}%`}}));
}
const FLAG = {good: {ko: "구간이 0 위", cls: "good", help: "우연을 감안한 범위가 전부 0보다 위입니다 (그래도 칸이 많아 우연일 수 있습니다)"},
  bad: {ko: "구간이 0 아래", cls: "bad", help: "우연을 감안한 범위가 전부 0보다 아래입니다"}};
const flagEl = (f) => (FLAG[f] ? h("span", {class: ["pp", FLAG[f].cls, "cn-flag"], title: FLAG[f].help}, FLAG[f].ko) : null);
const rangeTxt = (d) => (num(d.lo) == null || num(d.hi) == null ? null : `범위 ${ppTxt(d.lo).replace("%p", "")} ~ ${ppTxt(d.hi)}`);
/** The difference cell: ▲ / ▼ number, the bar, the range, the word for an interval clear of zero; "비교 불가" when a side has too few trades. */
function diffCell(d, max, minN) {
  if (!d) return h("span", {class: "muted"}, "—");
  if (d.few === true || num(d.diff) == null) {
    return h("span", {class: "cn-few", title: `양쪽 모두 ${fmt.int(minN)}건 이상이어야 비교합니다`}, "비교 불가");
  }
  return h("span", {class: "cn-d"}, diffEl(d.diff), barEl(d.diff, max), rangeTxt(d) ? h("small", {class: "muted"}, rangeTxt(d)) : null, flagEl(d.flag));
}
/** The trade counts: the structure's, then the coin twin's. */
const countsTxt = (d, k, t) => `${fmt.int(num(d && d.n) ?? num(k && k.n) ?? 0)} · ${fmt.int(num(d && d.n_twin) ?? num(t && t.n) ?? 0)}`;
/** The largest |difference| among the cells shown for the pair (the bar's scale). */
function maxDiff(C, pair) {
  let m = 0;
  for (const dim of C.dims) for (const b of dim.buckets) {
    const d = b.diffs[pair.real];
    if (d && num(d.diff) != null && !b.unknown) m = Math.max(m, Math.abs(Number(d.diff)));
  }
  return m;
}
const bucketCls = (b, d) => ["cn-row", b.unknown ? "cn-unk" : "", d && d.flag ? `cn-${d.flag}` : ""];
const bucketData = (dim, b, d) => ({dim: dim.id, bucket: b.id, flag: (d && d.flag) || "", few: !d || d.few === true || num(d.diff) == null ? "1" : "0", unknown: b.unknown ? "1" : "0"});
const bucketName = (b) => h("span", {class: "cn-nm"}, h("b", null, b.ko), b.hint ? h("small", {class: "muted"}, b.hint) : null);

// ---------------------------------------------------------------- one dimension: a table (or cards on a phone)
function tableView(dim, pair, C, max) {
  const th = (label, title) => h("th", {scope: "col", title}, label);
  const rows = dim.buckets.map((b) => {
    const d = b.diffs[pair.real], k = b.kinds[pair.real], t = b.kinds[pair.twin];
    return h("tr", {class: bucketCls(b, d), dataset: bucketData(dim, b, d)},
      h("td", {class: "l kd-nm"}, bucketName(b)),
      h("td", {class: "num"}, meanEl(k, C.minN)),
      h("td", {class: "num"}, meanEl(t, C.minN)),
      h("td", {class: "num cn-dc"}, diffCell(d, max, C.minN)),
      h("td", {class: "num"}, h("span", {class: "kd-v"}, countsTxt(d, k, t))));
  });
  return h("div", {class: "tbl-wrap"}, h("table", {class: "tbl kd-tbl cn-tbl"}, h("caption", {class: "sr"}, `${dim.ko}별 성적 표`),
    h("thead", null, h("tr", null, h("th", {class: "l", scope: "col"}, dim.ko), th(`${pair.realKo} 평균`, "거래 하나당 순수익(증거금 대비)의 평균"),
      th(`${pair.twinKo} 평균`, "같은 신호 시각에 방향을 동전으로 정한 짝 계좌의 평균"),
      th("차이", `${pair.realKo} 평균 − ${pair.twinKo} 평균 (플러스면 ${pair.realKo}이 낫습니다)`),
      th("거래 수", `${pair.realKo} · ${pair.twinKo}`))),
    h("tbody", null, rows)));
}
function cardView(dim, pair, C, max) {
  return h("div", {class: "cn-cards"}, dim.buckets.map((b) => {
    const d = b.diffs[pair.real], k = b.kinds[pair.real], t = b.kinds[pair.twin];
    const shown = d && d.few !== true && num(d.diff) != null;
    return h("article", {class: ["cn-card", ...bucketCls(b, d).slice(1)], "aria-label": `${dim.ko} ${b.ko}`, dataset: bucketData(dim, b, d)},
      h("div", {class: "cn-ch"}, bucketName(b),
        shown ? h("span", {class: "cn-dv"}, diffEl(d.diff)) : h("span", {class: "cn-few", title: `양쪽 모두 ${fmt.int(C.minN)}건 이상이어야 비교합니다`}, d ? "비교 불가" : "—")),
      shown ? h("div", {class: "cn-cb"}, barEl(d.diff, max), h("div", {class: "cn-cr"}, rangeTxt(d) ? h("small", {class: "muted"}, rangeTxt(d)) : null, flagEl(d.flag))) : null,
      h("dl", {class: "cn-cg"},
        h("div", null, h("dt", null, `${pair.realKo} 평균`), h("dd", {class: "num"}, meanEl(k, C.minN))),
        h("div", null, h("dt", null, `${pair.twinKo} 평균`), h("dd", {class: "num"}, meanEl(t, C.minN))),
        h("div", null, h("dt", null, "거래 수"), h("dd", {class: "num"}, countsTxt(d, k, t)))));
  }));
}
function dimCard(dim, pair, C, view, max) {
  const onlyUnknown = dim.buckets.length > 0 && dim.buckets.every((b) => b.unknown);
  return ui.card({plate: dim.ko, sub: dim.hint || undefined, cls: "kd-tcard cn-dim", id: `cn-${dim.id}`},
    dim.after ? h("p", {class: "note"}, ui.pill("끝난 뒤에 아는 값", "warn"), " 들어갈 때는 알 수 없는 값이라, 조건으로 쓸 수 없고 참고만 합니다.") : null,
    onlyUnknown ? h("p", {class: "note"}, "이 기록은 아직 없습니다. 이 기록을 남기기 전에 들어간 거래는 ‘모름’으로 셉니다.") : null,
    view === "card" ? cardView(dim, pair, C, max) : tableView(dim, pair, C, max));
}

// ---------------------------------------------------------------- the boxes
function rulesList() {
  return h("ol", {class: "kd-list cn-rules"}, RULES.map(([head, body]) => h("li", null, h("b", null, head), `: ${body}`)));
}
function hero(C) {
  return h("section", {class: "card hero dl-verdict s2a-hero kd-hero cn-hero", "aria-label": "한 줄 요약"},
    h("div", {class: "s2a-hrow"}, ui.plate("한 줄 요약"), ui.pill("탐색용", "warn", "통과 · 실패를 매기지 않는 참고 화면입니다")),
    h("p", {class: "cn-head"}, C.headline || "비교할 거래가 아직 없습니다"),
    h("p", {class: "note cn-note"}, C.note),
    ui.disclosure("읽는 법 보기", rulesList()));
}
function missingBox(g, d) {
  if (g.state === "old") return oldLeagueBox(d, "조건별 성적 화면은 아직 없습니다.");
  if (g.state === "prep") {
    return ui.card({plate: "데이터 준비 중"},
      h("p", {class: "dl-vline"}, "조건별 기록은 아직 없습니다."),
      h("p", {class: "note"}, "엔진이 조건별 기록을 쓰면 (5분마다) 저절로 나타납니다. 거래가 쌓이는 데 며칠 걸립니다."));
  }
  return notReady("후보 리그 기록이 아직 없습니다.");
}
function explain() {
  return ui.card({plate: "이 화면은 탐색용입니다", sub: "조건별로 어디서 잘 맞는지 보는 참고 화면", cls: "cn-rulebox"}, rulesList());
}
/** The line under the switches: which two kinds are compared and how many trades each has (all picks together). */
function pairLine(C, pair) {
  const n = (s) => fmt.int(num(C.trades[s]) ?? 0);
  return h("p", {class: "note cn-pairline"}, `${pair.realKo}(${pair.real}) 거래 ${n(pair.real)}건 · ${pair.twinKo}(${pair.twin}) 거래 ${n(pair.twin)}건, 모든 후보를 합친 수입니다. ${PAIR_HELP[pair.real] || ""}`);
}
function closing(C, d) {
  const wallet = Number(d && d.equity0) > 0 ? `모든 계좌는 ${startTxt(d)}에서 시작하는 모의 계좌입니다 (가상 돈). ` : "모의 계좌입니다 (가상 돈). ";
  return [
    h("p", {class: "note"}, C.dsIn ? "이 숫자에는 딥시크 계좌도 들어 있습니다." : "이 숫자는 딥시크를 뺀 후보만으로 계산했습니다 (딥시크 금액은 숨김 설정이라 여기에도 쓰지 않습니다)."),
    h("p", {class: "assume"}, `${wallet}같은 신호를 나눠 쓰는 계좌들이라 칸끼리도, 두 구조끼리도 완전히 따로가 아닙니다. 실제 주문은 넣지 않습니다.`),
  ];
}

export async function mount(el, ctx) {
  el.classList.add("kd", "cn");
  const root = h("div", {class: "kd-root"});
  const saved = local.get("conditions-view", null), savedPair = local.get("conditions-pair", null);
  const st = {view: saved === "card" || saved === "table" ? saved : (typeof innerWidth === "number" && innerWidth < 760 ? "card" : "table"),
    pair: typeof savedPair === "string" ? savedPair : "-fq", d: null, pairSeg: null, pairKey: ""};
  const viewSeg = ui.seg([{id: "table", label: "표"}, {id: "card", label: "카드"}], st.view, (v) => { st.view = v; local.set("conditions-view", v); paint(); }, {label: "보기"});
  el.append(ui.screenHead("조건별 성적", "언제 잘 맞고 언제 안 맞나 (탐색용)"), root);
  put(root, explain(), ui.missing("조건별 기록"));

  /** The switch between the two structures: built once (so the keyboard focus stays), rebuilt only when the snapshot's pairs change. */
  function pairSeg(C, pair) {
    const key = C.pairs.map((p) => `${p.real}/${p.realKo}`).join("|");
    if (!st.pairSeg || st.pairKey !== key) {
      st.pairKey = key;
      st.pairSeg = ui.seg(C.pairs.map((p) => ({id: p.real, label: p.realKo, title: PAIR_HELP[p.real] || p.realKo})), pair.real,
        (v) => { st.pair = v; local.set("conditions-pair", v); paint(); }, {label: "어느 구조를 볼까"});
    }
    st.pairSeg.set(pair.real);
    return st.pairSeg;
  }

  function paint() {
    const d = st.d, g = gate(d);
    if (g.state !== "ok") { put(root, explain(), missingBox(g, d)); return; }
    const C = g.C, pair = pickPair(C, st.pair);
    viewSeg.set(st.view);
    if (!pair || !C.dims.length) {
      put(root, hero(C), ui.card({plate: "조건별 성적"}, ui.none("비교할 계좌 종류가 아직 없습니다")), closing(C, d));
      return;
    }
    const max = maxDiff(C, pair);
    put(root, hero(C),
      h("div", {class: "row wrap cn-ctl", style: {justifyContent: "space-between", gap: "8px 12px"}}, pairSeg(C, pair), viewSeg),
      pairLine(C, pair),
      h("div", {class: "cn-grid"}, C.dims.map((dim) => dimCard(dim, pair, C, st.view, max))),
      closing(C, d));
  }
  ctx.onLeague((d) => { st.d = d; paint(); });
}

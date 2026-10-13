// #/coins 코인별: in which coin does each account kind earn or lose? For the 실전 후보 and the 대조 and their coin-flip twins (동전 던지기 짝), per coin:
// closed trades, win rate, mean net return per trade, long / short, the coin's share of the kind's profit, and (real kinds) the difference to the twin in
// the SAME coin. Numbers only: no interval, no pass / fail, no advice. A coin with fewer than 30 trades is marked 적음 (a WORD, never colour alone).
// Top to bottom: what this screen is (always), one sentence from the server (counts only), a table (cards on a phone) per kind, words, limits.
// Data: the snapshot's ``coins`` (candleague/coinview.py coin_views). Every number may be null and then reads "—", never 0; money is only ever the
// snapshot's own figures (equity0 is named in the server's note), DeepSeek money is left out by the server unless the money switch is on.
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {hasLineup, notReady, oldLeagueBox} from "./pairs.js";
import {pc} from "./versus.js";

export const css = ["scr/kinds.css", "scr/coins.css"];

export const MIN_N = 30;
/** The rules as the server writes them (candleague/coinview.coin_rules_ko); used when the snapshot has none. */
export const RULES_DEFAULT = [
  "무엇을 보여 주나: 코인마다 닫힌 거래의 수 · 이긴 비율 · 거래당 평균 수익률 · 롱과 숏 개수 · 손익 비중을 보여 주고, 같은 코인에서 동전 던지기 짝과의 평균 차이를 붙입니다.",
  `거래가 ${MIN_N}건 미만이면 ‘적음’으로 표시합니다. 적은 숫자는 우연일 수 있어 그 코인의 차이는 믿지 않는 편이 좋습니다.`,
  "거래당 평균 수익률은 수수료를 뺀 값(ROE)의 평균입니다. 모든 후보의 거래를 한데 모아 셉니다.",
  "차이는 두 평균의 뺄셈일 뿐입니다 (거래를 하나씩 짝지은 판정이 아닙니다). 신뢰구간이나 통과 · 실패는 없고, 무엇을 하라는 말도 없습니다.",
];

const num = (x) => (fmt.bad(x) ? null : Number(x));
const obj = (x) => (x && typeof x === "object" && !Array.isArray(x) ? x : {});
const cnt = (n, unit = "") => (num(n) == null ? "—" : `${fmt.int(n)}${unit}`);
/** A difference of two returns, in percentage points: 0.0123 -> "+1.2%p"; null -> "—". */
export const pp = (f) => (num(f) == null ? "—" : `${pc(f, true)}p`);

// ---------------------------------------------------------------- the snapshot's ``coins``
export function normCoins(x) {
  if (!x || typeof x !== "object" || Array.isArray(x) || !Array.isArray(x.kinds)) return null;
  return {
    minN: num(x.min_n) ?? MIN_N, dsIn: x.ds_in_stats === true, headline: typeof x.headline_ko === "string" ? x.headline_ko : "",
    rules: Array.isArray(x.rules_ko) && x.rules_ko.length ? x.rules_ko.map(String) : null,
    notes: Array.isArray(x.note_ko) ? x.note_ko.map(String) : [],
    kinds: x.kinds.filter((k) => k && typeof k === "object").map((k) => ({...k, total: obj(k.total), rows: Array.isArray(k.rows) ? k.rows.filter((r) => r && typeof r === "object") : []})),
  };
}
/** {state, C}: wait (no snapshot) | old (the old league) | prep (new league, no block yet) | ok */
export function gate(d) {
  if (!d || !d.accounts) return {state: "wait", C: null};
  const C = normCoins(d.coins);
  if (C && C.kinds.length) return {state: "ok", C};
  return {state: hasLineup(d) ? "prep" : "old", C: null};
}

// ---------------------------------------------------------------- pieces
const nameOf = (k) => String(k.name_ko || k.label_ko || k.role || "—");
const fewPill = (C) => ui.pill("적음", "thin", `거래가 ${C.minN}건 미만이라 우연일 수 있습니다`);
const livePill = (k) => (k.live === true ? ui.pill("실전 후보", "accent") : null);
const twinPill = (k) => (k.is_twin === true ? ui.pill("동전 던지기 짝", "thin", "방향을 동전으로 정한 같은 신호의 계좌. 우연이 만드는 정도를 보는 기준입니다") : null);
const tone = (x) => (num(x) == null ? "" : fmt.tone(x, pc(x, true)));
const diffTxt = (r) => (num(r.diff) == null ? "—" : pp(r.diff));

/** The cells of one coin row: [{key, label, value, sub, help}] (the same for the table and the card). */
export function rowCells(r, k, C) {
  const few = r.few === true;
  const none = !(num(r.n) > 0);
  const cells = [
    {key: "n", label: "거래", value: cnt(r.n, "건"), help: "닫힌 거래 수"},
    {key: "win", label: "이긴 비율", value: none ? "—" : pc(r.win_rate, false, 0), sub: none ? "" : `${cnt(r.wins, "건")} 이김`, help: "이익으로 끝난 거래의 비율"},
    {key: "mean", label: "거래당 평균", value: none ? "—" : pc(r.mean_roe, true), tone: tone(r.mean_roe), help: "거래 한 건당 수수료를 뺀 수익률(ROE)의 평균"},
    {key: "side", label: "롱 · 숏", value: none ? "—" : `${cnt(r.long)} · ${cnt(r.short)}`, help: "롱과 숏으로 들어간 거래 수"},
    {key: "share", label: "손익 비중", value: num(r.share) == null ? "—" : pc(r.share, false, 0), sub: num(r.pnl) == null ? "" : fmt.money(r.pnl, true),
      help: "이 코인 손익 ÷ 이 종류 전체 손익. 전체가 플러스일 때만 계산합니다"},
  ];
  if (k.twin) {
    const t = obj(r.twin);
    cells.push({key: "diff", label: "동전 짝과 차이", value: diffTxt(r), tone: r.diff_few ? "" : tone(r.diff),
      sub: num(t.n) == null ? "" : `짝 ${cnt(t.n, "건")} · 평균 ${num(t.mean_roe) == null ? "—" : pc(t.mean_roe, true)}`, few: r.diff_few === true,
      help: "같은 코인에서 이 종류의 거래당 평균 − 동전 짝의 거래당 평균 (두 평균의 뺄셈, 거래를 짝지은 것은 아님)"});
  }
  return cells.map((c) => ({...c, few: c.few ?? (few && (c.key === "win" || c.key === "mean"))}));
}

function kindTable(k, C) {
  const heads = rowCells({}, k, C);
  const body = k.rows.map((r) => h("tr", {class: "kd-row", dataset: {coin: r.coin, few: r.few === true ? "1" : "0"}},
    h("td", {class: "l kd-nm"}, h("b", null, String(r.coin ?? "—")), r.few === true ? h("span", {class: "cn-few"}, fewPill(C)) : null),
    rowCells(r, k, C).map((c) => h("td", {class: "num", dataset: {cell: c.key}}, h("span", {class: ["kd-v", c.tone || ""]}, c.value),
      c.few && c.key === "diff" ? h("small", {class: "cn-s"}, "적음") : null, c.sub ? h("small", {class: "cn-s"}, c.sub) : null))));
  return h("div", {class: "tbl-wrap"}, h("table", {class: "tbl kd-tbl cn-tbl"}, h("caption", {class: "sr"}, `${nameOf(k)} 코인별 성적`),
    h("thead", null, h("tr", null, h("th", {class: "l", scope: "col"}, "코인"), heads.map((c) => h("th", {scope: "col", title: c.help}, c.label)))),
    h("tbody", null, body)));
}
function kindCards(k, C) {
  return h("div", {class: "kd-cards"}, k.rows.map((r) => h("article", {class: ["kd-kcard", r.few === true ? "cn-thin" : ""], "aria-label": `${nameOf(k)} ${r.coin}`,
    dataset: {coin: r.coin, few: r.few === true ? "1" : "0"}},
  h("div", {class: "kd-kh"}, h("b", null, String(r.coin ?? "—")), r.few === true ? fewPill(C) : null, h("small", {class: "muted"}, `닫힌 거래 ${cnt(r.n, "건")}`)),
  h("dl", {class: "kd-kgrid cn-facts"}, rowCells(r, k, C).filter((c) => c.key !== "n").map((c) => h("div", {dataset: {cell: c.key}}, h("dt", {title: c.help}, c.label),
    h("dd", {class: "num"}, h("span", {class: c.tone || ""}, c.value), c.key === "diff" && c.few ? h("small", {class: "cn-s"}, "적음") : null, c.sub ? h("small", {class: "cn-s"}, c.sub) : null)))))));
}
function kindCard(k, C, view) {
  const t = k.total;
  const sub = `${cnt(k.accounts, "개")} 계좌 · 닫힌 거래 ${cnt(t.n, "건")}${num(t.mean_roe) == null ? "" : ` · 거래당 평균 ${pc(t.mean_roe, true)}`}${k.skipped > 0 ? ` · 숫자가 빠진 ${cnt(k.skipped, "건")}은 뺌` : ""}`;
  return ui.card({plate: nameOf(k), sub, cls: "kd-tcard cn-card", id: `cn-${String(k.suffix || k.role).replace(/^-/, "")}`},
    h("div", {class: "cn-tags"}, livePill(k), twinPill(k)),
    k.rows.length ? (view === "card" ? kindCards(k, C) : kindTable(k, C)) : ui.empty("이 종류는 아직 닫힌 거래가 없습니다"));
}

function ruleBox(C) {
  const rules = (C && C.rules) || RULES_DEFAULT;
  return ui.card({plate: "이 화면은 무엇인가요", sub: "숫자만 보여 줍니다 · 권유하지 않습니다", cls: "kd-rule", id: "cn-rules"},
    h("ol", {class: "kd-list kd-rules"}, rules.map((t) => {
      const i = t.indexOf(": ");
      return h("li", null, i > 0 ? [h("b", null, t.slice(0, i)), `: ${t.slice(i + 2)}`] : t);
    })));
}
function hero(C) {
  return h("section", {class: "card hero dl-verdict s2a-hero kd-hero cn-hero", "aria-label": "한 줄 결론"},
    h("div", {class: "s2a-hrow"}, ui.plate("한 줄 결론")),
    h("p", {class: "dl-vbig"}, C.headline || "코인별 성적을 계산 중입니다"),
    h("p", {class: "dl-vline"}, `보는 종류 ${cnt(C.kinds.length, "가지")} · 코인 ${cnt(C.kinds[0] && C.kinds[0].rows.length, "개")}`),
    h("p", {class: "note"}, "모의 거래 기록입니다. 앞으로를 약속하는 숫자가 아닙니다. 어떤 행동도 권하지 않습니다."));
}
function legend() {
  const row = (t, d) => h("div", null, h("dt", null, t), h("dd", null, d));
  return ui.card({plate: "낱말 뜻", sub: "처음 보는 분을 위한 설명", id: "cn-words"},
    h("dl", {class: "kd-legend"},
      row("거래당 평균", "거래 한 건이 끝날 때마다 남은 수익률(수수료 뺀 ROE)의 평균입니다. 이긴 비율이 높아도 지는 거래가 크면 평균은 낮을 수 있습니다."),
      row("손익 비중", "이 코인에서 번 돈이 그 종류 전체 이익에서 차지하는 몫입니다. 전체가 손해이면 계산하지 않습니다."),
      row("동전 던지기 짝", "같은 신호에서 방향만 동전으로 정해 들어간 계좌입니다. 실제 계좌가 이 짝보다 나은지 못한지로 ‘신호가 아니라 운’인지를 가늠합니다."),
      row("차이", "같은 코인에서 실제 종류의 평균 − 동전 짝의 평균입니다. 거래가 적은 코인은 ‘적음’으로 표시합니다."),
      row("롱 · 숏", "롱은 오를 때 이기는 쪽, 숏은 내릴 때 이기는 쪽입니다.")));
}
function closing(C) {
  return [
    C.notes.length ? ui.card({plate: "이 숫자의 한계", sub: "읽기 전에 한 번", id: "cn-limits"}, h("ul", {class: "kd-list"}, C.notes.map((t) => h("li", null, t)))) : null,
    h("p", {class: "note"}, C.dsIn ? "이 숫자에는 딥시크 계좌도 들어 있습니다." : "이 숫자는 딥시크를 뺀 후보만으로 계산했습니다 (딥시크 금액은 숨김 설정이라 쓰지 않습니다)."),
    h("p", {class: "assume"}, "모의 계좌입니다 (가상 돈). 실제 주문은 넣지 않습니다."),
  ];
}
function missingBox(g, d) {
  if (g.state === "old") return oldLeagueBox(d, "코인별 화면은 아직 없습니다.");
  if (g.state === "prep") {
    return ui.card({plate: "데이터 준비 중"}, h("p", {class: "dl-vline"}, "코인별 기록은 아직 없습니다. 위 규칙은 그대로 적용됩니다."),
      h("p", {class: "note"}, "엔진이 기록을 쓰면 (5분마다) 저절로 나타납니다. 닫힌 거래가 있어야 숫자가 생깁니다."));
  }
  return notReady("후보 리그 기록이 아직 없습니다.");
}

export async function mount(el, ctx) {
  el.classList.add("kd");
  const root = h("div", {class: "kd-root"});
  const saved = local.get("coins-view", null);
  const st = {view: saved === "card" || saved === "table" ? saved : (typeof innerWidth === "number" && innerWidth < 760 ? "card" : "table"), d: null};
  const seg = ui.seg([{id: "table", label: "표"}, {id: "card", label: "카드"}], st.view, (v) => { st.view = v; local.set("coins-view", v); paint(); }, {label: "보기"});
  el.append(ui.screenHead("코인별", "어느 코인에서 벌고 잃었는지"), root);
  put(root, ruleBox(null), ui.missing("코인별 기록"));

  function paint() {
    const d = st.d, g = gate(d);
    if (g.state !== "ok") { put(root, ruleBox(null), missingBox(g, d)); return; }
    const C = g.C;
    seg.set(st.view);
    put(root, ruleBox(C), hero(C), h("div", {class: "row wrap", style: {justifyContent: "flex-end"}}, seg),
      C.kinds.map((k) => kindCard(k, C, st.view)), legend(), closing(C));
  }
  ctx.onLeague((d) => { st.d = d; paint(); });
}

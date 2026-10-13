// The shared pieces of the four small "numbers only" screens 실제 비용 / 시장 국면 / 신호 / 알림 기록 (same look and states as 위험 점검, risk.js):
// the rule box that is always there, the one-sentence answer, the 표 / 카드 switch (cards on a phone), the states (데이터 준비 중 / 새 리그 전용 / 준비 중) and the
// closing notes. Nothing here reads a number out of a text and nothing writes markup from a string: every string goes in as a text node.
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {hasLineup, notReady, oldLeagueBox} from "./pairs.js";
import {startTxt} from "./versus.js";

export const num = (x) => (fmt.bad(x) ? null : Number(x));
export const obj = (x) => (x && typeof x === "object" && !Array.isArray(x) ? x : {});
export const cnt = (n, unit = "") => (num(n) == null ? "—" : `${fmt.int(n)}${unit}`);
/** A fraction as a percent: 0.0182 -> "1.82%" (dec digits), null -> "—". */
export const pctx = (f, dec = 1, sign = false) => (num(f) == null ? "—" : fmt.pct(Number(f) * 100, sign, dec));
export const nameOf = (k) => String(k.name_ko || k.short_ko || k.label_ko || k.role || "—");
export const livePill = (k) => (k.live === true ? ui.pill("실전 후보", "accent") : null);
export const poolPill = (k, what = "여러 종류를 합친 숫자입니다. 같은 신호가 종류마다 반복되어 들어 있습니다") => (k.pooled === true ? ui.pill("모두 합침", "thin", what) : null);
export const subName = (k) => (k.pooled === true ? `합계 · 계좌 ${cnt(k.accounts, "개")}` : `${k.suffix || ""} · 계좌 ${cnt(k.accounts, "개")}`);
export const strs = (x) => (Array.isArray(x) ? x.map(String) : []);

/** The common head of a doc block: {state, B}.  wait  no snapshot yet   old  the old league (no lineup)   prep  the new league, the block is not there yet   ok */
export function gate(d, norm) {
  if (!d || !d.accounts) return {state: "wait", B: null};
  const B = norm(d);
  if (B) return {state: "ok", B};
  return {state: hasLineup(d) ? "prep" : "old", B: null};
}

export function ruleBox(rules, fallback, sub = "숫자만 보여 줍니다 · 권유하지 않습니다") {
  const list = rules && rules.length ? rules : fallback;
  return ui.card({plate: "이 화면은 무엇인가요", sub, cls: "kd-rule", id: "s4-rules"},
    h("ol", {class: "kd-list kd-rules"}, list.map((t) => {
      const i = t.indexOf(": ");
      return h("li", null, i > 0 ? [h("b", null, t.slice(0, i)), `: ${t.slice(i + 2)}`] : t);
    })));
}
export function hero(big, line, note, warn = false) {
  return h("section", {class: "card hero dl-verdict s2a-hero kd-hero s4-hero", "aria-label": "한 줄 결론"},
    h("div", {class: "s2a-hrow"}, ui.plate("한 줄 결론")),
    h("p", {class: ["dl-vbig", warn ? "warn" : ""]}, big),
    line ? h("p", {class: "dl-vline"}, line) : null,
    h("p", {class: "note"}, note || "모의 거래 기록입니다. 앞으로를 약속하는 숫자가 아닙니다. 어떤 행동도 권하지 않습니다."));
}
export function legend(rows) {
  return ui.card({plate: "낱말 뜻", sub: "처음 보는 분을 위한 설명", id: "s4-words"},
    h("dl", {class: "kd-legend"}, rows.map(([t, d]) => h("div", null, h("dt", null, t), h("dd", null, d)))));
}
export function closing(B, d, extra) {
  const wallet = Number(d && d.equity0) > 0 ? `모든 계좌는 ${startTxt(d)}에서 시작하는 모의 계좌입니다 (가상 돈). ` : "모의 계좌입니다 (가상 돈). ";
  return [
    B.notes && B.notes.length ? ui.card({plate: "이 숫자의 한계", sub: "읽기 전에 한 번", id: "s4-limits"}, h("ul", {class: "kd-list"}, B.notes.map((t) => h("li", null, t)))) : null,
    typeof B.dsIn === "boolean" ? h("p", {class: "note"}, B.dsIn ? "이 숫자에는 딥시크 계좌도 들어 있습니다." : "이 숫자는 딥시크를 뺀 후보만으로 계산했습니다 (딥시크 금액은 숨김 설정이라 쓰지 않습니다).") : null,
    extra || null,
    h("p", {class: "assume"}, `${wallet}실제 주문은 넣지 않습니다.`),
  ];
}
/** The states of a doc-block screen. ``what``: the old-league sentence; ``prep``: [first line, second line]. */
export function missingBox(g, d, what, prep) {
  if (g.state === "old") return oldLeagueBox(d, what);
  if (g.state === "prep") return ui.card({plate: "데이터 준비 중"}, h("p", {class: "dl-vline"}, prep[0]), h("p", {class: "note"}, prep[1]));
  return notReady("후보 리그 기록이 아직 없습니다.");
}

/** A per-kind view: a table (kd-tbl) or a card per kind (kd-kcard). cols: [{key, label, help, cell(k) -> {v, sub, cls}}]. */
export function kindView(kinds, cols, view, caption) {
  const cells = (k) => cols.map((c) => ({c, x: c.cell(k)}));
  const head = (k) => [h("b", null, nameOf(k)), livePill(k), poolPill(k)];
  if (view === "card") {
    return h("div", {class: "kd-cards"}, kinds.map((k) => h("article", {class: ["kd-kcard", k.live === true ? "kd-live" : ""], "aria-label": nameOf(k), dataset: {suffix: k.suffix || k.role, pooled: k.pooled === true ? "1" : "0"}},
      h("div", {class: "kd-kh"}, head(k), h("small", {class: "muted"}, subName(k))),
      h("dl", {class: "kd-kgrid s4-facts"}, cells(k).map(({c, x}) => h("div", {dataset: {cell: c.key}}, h("dt", {title: c.help}, c.label),
        h("dd", {class: ["num", x.cls]}, x.v, x.sub ? h("small", {class: "s4-cs"}, x.sub) : null)))))));
  }
  const rows = kinds.map((k) => h("tr", {class: "kd-row", dataset: {suffix: k.suffix || k.role, pooled: k.pooled === true ? "1" : "0"}},
    h("td", {class: "l kd-nm"}, h("div", {class: "kd-nmh"}, head(k)), h("small", {class: "muted"}, subName(k))),
    cells(k).map(({x}) => h("td", {class: ["num", x.cls]}, h("span", {class: "kd-v"}, x.v), x.sub ? h("small", {class: "s4-cs"}, x.sub) : null))));
  return h("div", {class: "tbl-wrap"}, h("table", {class: "tbl kd-tbl s4-tbl"}, h("caption", {class: "sr"}, caption),
    h("thead", null, h("tr", null, h("th", {class: "l", scope: "col"}, "종류"), cols.map((c) => h("th", {scope: "col", title: c.help}, c.label)))),
    h("tbody", null, rows)));
}

/** The shared mount of a doc-block screen.
 *  cfg: {id, title, sub, rules (fallback), norm(d) -> B|null, what, prep, hero(B) -> node, body(B, view, d) -> nodes, words() -> node, seg (bool), viewKey} */
export async function mountBlock(el, ctx, cfg) {
  el.classList.add("kd");
  const root = h("div", {class: "kd-root"});
  const saved = cfg.seg ? local.get(cfg.viewKey, null) : null;
  const st = {view: saved === "card" || saved === "table" ? saved : (typeof innerWidth === "number" && innerWidth < 760 ? "card" : "table"), d: null};
  const seg = cfg.seg ? ui.seg([{id: "table", label: "표"}, {id: "card", label: "카드"}], st.view, (v) => { st.view = v; local.set(cfg.viewKey, v); paint(); }, {label: "보기"}) : null;
  el.append(ui.screenHead(cfg.title, cfg.sub), root);
  put(root, ruleBox(null, cfg.rules), ui.missing(`${cfg.title} 기록`));
  function paint() {
    const d = st.d, g = gate(d, cfg.norm);
    if (g.state !== "ok") { put(root, ruleBox(null, cfg.rules), missingBox(g, d, cfg.what, cfg.prep)); return; }
    const B = g.B;
    if (seg) seg.set(st.view);
    put(root, ruleBox(B.rules, cfg.rules), cfg.hero(B), seg ? h("div", {class: "row wrap", style: {justifyContent: "flex-end"}}, seg) : null,
      cfg.body(B, st.view, d), cfg.words ? cfg.words() : null, closing(B, d));
  }
  ctx.onLeague((d) => { st.d = d; paint(); });
}

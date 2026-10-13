// #/missed 놓친 신호: of the signals the league was offered, how many did each account kind actually enter, how many did it skip because a position
// was already open, and how many were rejected? And which picks rarely enter?
// Data: the snapshot's ``accounts`` rows, each with ``counts`` {offered, entered, skipped, rejected, closed} (offered = entered + skipped while holding
// + rejected; candleague/runner.day_counts). Summed here per kind (``role``) and per pick; no new block, nothing written back.
// HONESTY: the snapshot records COUNTS only, not the reason of a rejection, so the screen says so and never splits rejects by reason; a missing number
// reads "—", never 0; a kind with fewer than 30 signals reads 표본 적음; an older snapshot without ``counts`` reads 준비 중 / 새 리그 전용.
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {tfKo} from "../labels.js";
import {hasLineup, lineupOf, notReady, oldLeagueBox} from "./pairs.js";

export const css = ["scr/kinds.css", "scr/missed.css"];

export const MIN_SIGNALS = 30;
export const MIN_PICK = 20;
export const PICK_ROWS = 10;
const PICKS = [{id: "k2", label: "핵심 2개"}, {id: "all", label: "전체"}];
const CORE = ["fq", "ld"];

const num = (x) => (fmt.bad(x) ? null : Number(x));
const obj = (x) => (x && typeof x === "object" && !Array.isArray(x) ? x : {});
const arr = (x) => (Array.isArray(x) ? x.filter((v) => v && typeof v === "object") : []);
const FIELDS = ["offered", "entered", "skipped", "rejected"];
const share = (a, b) => (a == null || !(b > 0) ? null : a / b);
const SH = (f) => (f == null ? "—" : fmt.pct(f * 100, false, 1));
const CNT = (n) => (n == null ? "—" : fmt.int(n));

/** The counts of one account row, or null when it has none (an older record, an account without a rule). */
const countsOf = (r) => {
  const c = obj(r.counts);
  const v = FIELDS.map((k) => num(c[k]));
  return v.some((x) => x == null) ? null : Object.fromEntries(FIELDS.map((k, i) => [k, v[i]]));
};

/** Per kind in the lineup's order: [{role, name, accounts, offered, entered, skipped, rejected, small}] for the kinds that have at least one counted account. */
export function perKind(d) {
  const by = new Map();
  for (const r of arr(d && d.accounts)) {
    const c = countsOf(r);
    if (!c || !r.role) continue;
    const t = by.get(r.role) || {accounts: 0, offered: 0, entered: 0, skipped: 0, rejected: 0};
    t.accounts += 1;
    for (const k of FIELDS) t[k] += c[k];
    by.set(r.role, t);
  }
  return lineupOf(d).filter((k) => by.has(k.role)).map((k) => {
    const t = by.get(k.role);
    return {role: k.role, name: String(k.short_ko || k.label_ko || k.role), ...t, small: t.offered < MIN_SIGNALS};
  });
}
/** The kinds a picker choice shows: the core two (빠른 손절 + 원래 방식, else the first two) or all. */
export function pickKinds(list, pick) {
  if (pick === "all") return list;
  const core = list.filter((k) => CORE.includes(k.role));
  return core.length ? core : list.slice(0, 2);
}
/** The picks that rarely enter: over the given roles, offered >= MIN_PICK, lowest entered share first, PICK_ROWS of them. */
export function rarePicks(d, roles) {
  const by = new Map();
  for (const r of arr(d && d.accounts)) {
    const c = countsOf(r);
    if (!c || !roles.includes(r.role) || !r.pick) continue;
    const t = by.get(r.pick) || {pick: r.pick, name: r.name, tf: r.tf, offered: 0, entered: 0, skipped: 0, rejected: 0};
    for (const k of FIELDS) t[k] += c[k];
    by.set(r.pick, t);
  }
  return [...by.values()].filter((t) => t.offered >= MIN_PICK).map((t) => ({...t, rate: t.entered / t.offered}))
    .sort((a, b) => a.rate - b.rate || b.offered - a.offered || String(a.pick).localeCompare(String(b.pick))).slice(0, PICK_ROWS);
}

/** What the screen can show: {state, list}.  wait  no snapshot   old  no lineup   prep  the new league without counts   ok */
export function gate(d) {
  if (!d || !d.accounts) return {state: "wait", list: []};
  if (!hasLineup(d)) return {state: "old", list: []};
  const list = perKind(d);
  return {state: list.length ? "ok" : "prep", list};
}
/** The one-line answer for 한눈 지도: the core kinds together. */
export function headline(d) {
  try {
    const g = gate(d);
    if (g.state !== "ok") return null;
    const shown = pickKinds(g.list, "k2");
    const t = Object.fromEntries(FIELDS.map((k) => [k, shown.reduce((a, x) => a + x[k], 0)]));
    if (!(t.offered > 0)) return null;
    return `${shown.map((k) => k.name).join(" · ")}에 들어온 신호 ${fmt.int(t.offered)}개 중 진입 ${SH(share(t.entered, t.offered))}, 이미 포지션이 있어 건너뜀 ${SH(share(t.skipped, t.offered))}, 거절 ${SH(share(t.rejected, t.offered))}`;
  } catch (e) { return null; }
}

// ---------------------------------------------------------------- the pieces
const cell = (n, of) => h("td", {class: "num"}, CNT(n), h("small", {class: "ms-s"}, ` ${SH(share(n, of))}`));
function bar(k) {
  const seg = (key, cls, label) => {
    const f = share(k[key], k.offered);
    return f == null || f <= 0 ? null : h("span", {class: ["ms-seg", cls], style: {width: `${(f * 100).toFixed(2)}%`}, title: `${label} ${SH(f)}`});
  };
  return h("div", {class: "ms-bar", role: "img", "aria-label": `진입 ${SH(share(k.entered, k.offered))} · 건너뜀 ${SH(share(k.skipped, k.offered))} · 거절 ${SH(share(k.rejected, k.offered))}`},
    seg("entered", "ms-in", "진입"), seg("skipped", "ms-skip", "건너뜀"), seg("rejected", "ms-rej", "거절"));
}
function kindTable(shown) {
  return h("div", {class: "tbl-wrap"}, h("table", {class: "tbl ms-tbl", dataset: {tbl: "kinds"}},
    h("caption", {class: "sr"}, "계좌 종류마다 들어온 신호와 진입 · 건너뜀 · 거절"),
    h("thead", null, h("tr", null, h("th", {class: "l", scope: "col"}, "종류"), h("th", {scope: "col"}, "신호"), h("th", {scope: "col"}, "진입"), h("th", {scope: "col"}, "건너뜀"),
      h("th", {scope: "col"}, "거절"), h("th", {scope: "col"}, "구성"))),
    h("tbody", null, shown.map((k) => h("tr", {dataset: {role: k.role}},
      h("td", {class: "l"}, k.name, k.small ? h("span", {class: "ms-pill"}, ui.pill("표본 적음", "thin", `신호가 ${MIN_SIGNALS}개 미만입니다. 우연일 수 있어 결론을 내지 않습니다`)) : null,
        h("small", {class: "ms-s ms-blk"}, `계좌 ${fmt.int(k.accounts)}개`)),
      h("td", {class: "num", dataset: {c: "offered"}}, CNT(k.offered)),
      cell(k.entered, k.offered), cell(k.skipped, k.offered), cell(k.rejected, k.offered), h("td", {class: "ms-bc"}, bar(k)))))));
}
function rareTable(rows) {
  if (!rows.length) return h("p", {class: "empty"}, `신호가 ${MIN_PICK}개 이상 들어온 매매법이 아직 없습니다`);
  return h("div", {class: "tbl-wrap"}, h("table", {class: "tbl ms-tbl", dataset: {tbl: "picks"}},
    h("caption", {class: "sr"}, "진입 비율이 낮은 매매법 10개"),
    h("thead", null, h("tr", null, h("th", {class: "l", scope: "col"}, "매매법"), h("th", {scope: "col"}, "신호"), h("th", {scope: "col"}, "진입"), h("th", {scope: "col"}, "건너뜀"),
      h("th", {scope: "col"}, "거절"), h("th", {scope: "col"}, "진입 비율"))),
    h("tbody", null, rows.map((t) => h("tr", {dataset: {pick: t.pick}},
      h("td", {class: "l"}, t.name ? `${t.name} · ${tfKo(t.tf)}` : String(t.pick)),
      h("td", {class: "num"}, CNT(t.offered)), cell(t.entered, t.offered), cell(t.skipped, t.offered), cell(t.rejected, t.offered),
      h("td", {class: "num", dataset: {c: "rate"}}, SH(t.rate)))))));
}

function ruleBox() {
  return ui.card({plate: "이 화면은 무엇인가요", sub: "숫자와 설명만 보여 줍니다 · 권유하지 않습니다", cls: "kd-rule", id: "ms-rules"},
    h("ol", {class: "kd-list kd-rules"},
      h("li", null, h("b", null, "신호"), ": 매매법이 \"지금 들어갈 자리\"라고 낸 횟수입니다. 계좌마다 따로 셉니다."),
      h("li", null, h("b", null, "진입"), ": 실제로 포지션을 연 것."),
      h("li", null, h("b", null, "건너뜀"), ": 그 계좌가 이미 포지션을 들고 있어서 새 신호를 못 받은 것."),
      h("li", null, h("b", null, "거절"), ": 포지션이 없는데도 들어가지 않은 것 (규칙에 맞지 않아서).")),
    ui.disclosure("거절은 왜 생기나요", h("div", {class: "ms-why"},
      h("p", null, "이 리그의 배수 단계는 50배 · 40배 · 30배뿐이고 20배는 쓰지 않습니다. 그래서 다음 경우에는 신호가 들어와도 진입하지 않습니다."),
      h("ul", {class: "kd-list"},
        h("li", null, "손절폭이 너무 넓어서 30배로도 손실이 지갑의 15% 한도 안에 들어오지 않는 신호."),
        h("li", null, "거래소의 강제청산 거리 검사를 통과하지 못하는 신호.")),
      h("p", {class: "note"}, "이유별 건수는 기록하지 않습니다. 이 화면은 거절된 횟수만 보여 줍니다."))));
}
function missingBox(g, d) {
  if (g.state === "old") return oldLeagueBox(d, "놓친 신호 화면은 아직 없습니다.");
  if (g.state === "prep") return ui.card({plate: "준비 중"}, h("p", {class: "dl-vline"}, "신호 횟수 기록이 아직 없습니다. 위 설명은 그대로 적용됩니다."),
    h("p", {class: "note"}, "엔진이 기록을 쓰면 (5분마다) 저절로 나타납니다."));
  return notReady("후보 리그 기록이 아직 없습니다.");
}

export async function mount(el, ctx) {
  el.classList.add("kd");
  const root = h("div", {class: "kd-root"});
  const saved = local.get("missed-pick", null);
  const st = {pick: PICKS.some((p) => p.id === saved) ? saved : "k2", d: null};
  const seg = ui.seg(PICKS, st.pick, (v) => { st.pick = v; local.set("missed-pick", v); paint(); }, {label: "보는 종류"});
  el.append(ui.screenHead("놓친 신호", "들어온 신호 중 진입 · 건너뜀 · 거절이 얼마나 되는지"), root);
  put(root, ruleBox(), ui.missing("신호 횟수 기록"));

  function paint() {
    const d = st.d, g = gate(d);
    if (g.state !== "ok") { put(root, ruleBox(), missingBox(g, d)); return; }
    seg.set(st.pick);
    const shown = pickKinds(g.list, st.pick);
    const rare = rarePicks(d, shown.map((k) => k.role));
    put(root, ruleBox(),
      h("div", {class: "row wrap", style: {justifyContent: "flex-end"}}, seg),
      ui.card({plate: "종류마다", sub: `보는 종류: ${shown.map((k) => k.name).join(" · ") || "없음"}`, cls: "ms-card", id: "ms-kinds"}, kindTable(shown),
        h("p", {class: "note"}, "이유별 건수는 기록하지 않습니다. 거절은 횟수만 보여 줍니다. 퍼센트는 신호 대비 비율입니다.")),
      ui.card({plate: "진입이 드문 매매법", sub: `신호 ${MIN_PICK}개 이상인 것 중 진입 비율이 낮은 ${PICK_ROWS}개 (위에서 고른 종류를 합침)`, cls: "ms-card", id: "ms-picks"}, rareTable(rare),
        h("p", {class: "note"}, "진입 비율이 낮다고 나쁜 매매법은 아닙니다. 이미 포지션이 있었거나 규칙에 맞지 않아 들어가지 않은 신호가 많다는 뜻일 뿐입니다.")),
      h("p", {class: "assume"}, "모든 계좌는 모의 계좌입니다 (가상 돈). 실제 주문은 넣지 않습니다."));
  }
  ctx.onLeague((d) => { st.d = d; paint(); });
}

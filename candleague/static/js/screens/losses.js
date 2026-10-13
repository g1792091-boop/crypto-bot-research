// #/losses 손실 해부: what kind of loss was it, where and when did the losses pile up, which were the biggest? The rule bot's loss cards come from AI
// meetings; this screen is the league's own deterministic version, built from the CLOSED trades with a negative ROE (candleague/lossview.py).
// It only DESCRIBES: no advice, no pass / fail. Top to bottom: what this screen is, the server's one sentence, a kind picker (핵심 2개 = 빠른 손절 +
// 원래 방식 by default, 모든 종류 합계, 종류 전부), then one card per kind: the counts, the stacked bar of loss types (each type's plain words under
// a disclosure), five small breakdown tables (코인 · 방향 · 배수 · 시간대 KST · 요일), the loss streak and the same-signal pile-ups, and the 10 biggest
// losses with a 다시보기 link to #/replay?acct=<id>&at=<entry_time>.
// Data: the snapshot's ``losses`` (candleague/lossview.py loss_views, next to ``risk`` in the owner-exit league).
// HONESTY: every number carries its n; fewer than 30 losses reads 표본 적음 (never a verdict); a missing number reads "—", never 0; an older snapshot
// without the block reads 준비 중; DeepSeek money is left out of every figure unless the money switch is on (the server does that, a note says so).
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {replayHref} from "../why.js";
import {hasLineup, notReady, oldLeagueBox} from "./pairs.js";
import {pc} from "./versus.js";

export const css = ["scr/kinds.css", "scr/losses.css"];

export const MIN_LOSSES = 30;
/** The loss types as the server writes them (candleague/lossview.LOSS_TYPES, same order and words); used when the snapshot has none. */
export const TYPES_DEFAULT = [
  {id: "liq", ko: "강제청산", explain_ko: "증거금이 모자라 거래소가 강제로 닫은 거래입니다."},
  {id: "gave_back", ko: "벌었다가 놓침", explain_ko: "한때 손절폭(R)의 1배 이상 이익이었는데 되돌아와서 결국 손실로 끝났습니다."},
  {id: "gave_back_small", ko: "조금 벌었다가 놓침", explain_ko: "한때 손절폭의 0.3배 ~ 1배 이익이었다가 되돌아와서 손실로 끝났습니다."},
  {id: "rule_exit", ko: "규칙 청산으로 잃음", explain_ko: "손절선에 닿기 전에 구조 · 스위칭 · 매매법 판단으로 나갔는데 손실이었습니다."},
  {id: "gap", ko: "손절보다 크게 잃음", explain_ko: "손절폭보다 1.15배 넘게 잃었습니다. 미끄러짐이나 가격 갭 때문입니다."},
  {id: "slow", ko: "오래 끌다 잃음", explain_ko: "12시간을 넘게 들고 있다가 손실로 끝났습니다."},
  {id: "direct", ko: "처음부터 불리하게 감", explain_ko: "들어가자마자 반대로 가서 손절선에 닿았습니다 (손절 직행)."},
  {id: "unknown", ko: "분류 못 함", explain_ko: "가격이나 손절선, 시간 기록이 빠져 있어 유형을 나누지 못했습니다."},
];
const REASON_KO = {SL: "손절", LOCK: "잠금", RULE: "규칙", TP: "익절", LIQ: "강제청산"};
const SIDE_KO = {1: "롱", "-1": "숏"};
const PICKS = [{id: "k2", label: "핵심 2개"}, {id: "all", label: "모든 종류 합계"}, {id: "each", label: "종류 전부"}];

const num = (x) => (fmt.bad(x) ? null : Number(x));
const obj = (x) => (x && typeof x === "object" && !Array.isArray(x) ? x : {});
const arr = (x) => (Array.isArray(x) ? x.filter((v) => v && typeof v === "object") : []);
const cnt = (n, unit) => (num(n) == null ? "—" : `${fmt.int(n)}${unit}`);
const P = (f, sign = false) => (num(f) == null ? "—" : pc(f, sign));
const P0 = (f) => (num(f) == null ? "—" : pc(f, false, 0));

// ---------------------------------------------------------------- the snapshot's ``losses``
/** The losses block with every missing part empty; null when it is absent or malformed. */
export function normLosses(x) {
  if (!x || typeof x !== "object" || Array.isArray(x) || !Array.isArray(x.kinds)) return null;
  const types = arr(x.types).filter((t) => typeof t.id === "string");
  return {
    dsIn: x.ds_in_stats === true, min: num(x.min_losses) ?? MIN_LOSSES,
    headline: typeof x.headline_ko === "string" ? x.headline_ko : "",
    types: types.length ? types.map((t) => ({id: t.id, ko: String(t.ko ?? t.id), explain: String(t.explain_ko ?? "")})) : TYPES_DEFAULT.map((t) => ({id: t.id, ko: t.ko, explain: t.explain_ko})),
    notes: Array.isArray(x.note_ko) ? x.note_ko.map(String) : [],
    kinds: arr(x.kinds).map((k) => ({...k, types: arr(k.types), cluster: obj(k.cluster), streak: obj(k.streak), worst: arr(k.worst),
      by: {coin: arr(k.by_coin), side: arr(k.by_side), lev: arr(k.by_lev), hour: arr(k.by_hour), week: arr(k.by_week)}})),
  };
}
/** What the screen can show: {state, L}.  wait  no snapshot yet   old  the old league (no lineup)   prep  the new league without ``losses``   ok  here */
export function gate(d) {
  if (!d || !d.accounts) return {state: "wait", L: null};
  const L = normLosses(d.losses);
  if (L && L.kinds.length) return {state: "ok", L};
  return {state: hasLineup(d) ? "prep" : "old", L: null};
}
const nameOf = (k) => String(k.name_ko || k.short_ko || k.label_ko || k.role || "—");
const isCore = (k) => k.pooled !== true && (k.role === "fq" || k.role === "ld" || k.suffix === "-fq" || k.suffix === "-ld");
/** The kinds a picker choice shows: 핵심 2개 (빠른 손절 + 원래 방식; the first two kinds when the lineup has neither), the pooled one, or every kind. */
export function pickKinds(L, pick) {
  const single = L.kinds.filter((k) => k.pooled !== true);
  if (pick === "all") return L.kinds.some((k) => k.pooled === true) ? L.kinds.filter((k) => k.pooled === true) : L.kinds;
  if (pick === "each") return single.length ? single : L.kinds;
  const core = single.filter(isCore);
  return core.length ? core : single.slice(0, 2);
}

// ---------------------------------------------------------------- one kind
const smallPill = (k, L) => (k.small === true || (num(k.losses) ?? 0) < L.min ? ui.pill("표본 적음", "thin", `진 거래가 ${fmt.int(L.min)}건 미만입니다. 우연일 수 있어서 결론을 내지 않습니다`) : null);
const livePill = (k) => (k.live === true ? ui.pill("실전 후보", "accent") : null);
const poolPill = (k) => (k.pooled === true ? ui.pill("모두 합침", "thin", "모든 종류를 합친 숫자입니다. 같은 신호가 종류마다 반복되어 들어 있습니다") : null);

/** The facts of a kind: [{key, label, value, sub, help}]. */
export function facts(k) {
  const none = !(num(k.losses) > 0);
  const money = num(k.loss_money);
  return [
    {key: "trades", label: "닫힌 거래", value: cnt(k.trades, "건"), sub: `계좌 ${cnt(k.accounts, "개")}`, help: "이 종류 계좌들이 지금까지 닫은 거래 수"},
    {key: "losses", label: "진 거래", value: cnt(k.losses, "건"), sub: num(k.loss_share) == null ? "" : `전체의 ${P(k.loss_share)}`, help: "수익률(ROE)이 0보다 작게 끝난 거래"},
    {key: "mean", label: "진 거래의 평균 ROE", value: none ? "—" : P(k.mean_loss_roe, true), sub: "", help: "진 거래만의 평균 수익률"},
    {key: "worst", label: "가장 크게 진 거래", value: none ? "—" : P(k.worst_loss_roe, true), sub: "", help: "진 거래 중 ROE가 가장 낮은 것"},
    {key: "money", label: "진 거래의 손실 합계", value: none || money == null ? "—" : fmt.money(money, true), sub: "모의 금액", help: "진 거래의 손익(금액)을 모두 더한 값"},
  ];
}
function factsList(k) {
  return h("dl", {class: "kd-kgrid lv-facts"}, facts(k).map((f) => h("div", {dataset: {fact: f.key}}, h("dt", {title: f.help}, f.label),
    h("dd", {class: "num"}, f.value, f.sub ? h("small", {class: "lv-cs"}, f.sub) : null))));
}

function typeBar(k, L) {
  const total = num(k.losses) ?? 0;
  const by = new Map(k.types.map((t) => [t.id, t]));
  const rows = L.types.map((t) => ({...t, n: num(by.get(t.id)?.n) ?? 0, share: num(by.get(t.id)?.share), mean: num(by.get(t.id)?.mean_roe)}));
  if (!(total > 0)) return h("p", {class: "empty"}, "아직 진 거래가 없습니다");
  const segs = rows.filter((r) => r.n > 0);
  const label = segs.map((r) => `${r.ko} ${fmt.int(r.n)}건 (${P0(r.n / total)})`).join(", ");
  const bar = h("div", {class: "kd-rbar lv-bar", role: "img", "aria-label": `진 거래의 유형: ${label}`}, segs.map((r) => {
    const share = (r.n / total) * 100;
    return h("span", {class: ["kd-seg", `lv-t-${r.id}`], style: {"--w": `${share.toFixed(2)}%`}, title: `${r.ko} ${fmt.int(r.n)}건 (${Math.round(share)}%)`},
      share >= 14 ? `${r.ko} ${fmt.int(r.n)}` : share >= 7 ? fmt.int(r.n) : null);
  }));
  const legend = h("div", {class: "kd-rleg lv-leg"}, rows.map((r) => h("div", {class: ["kd-rc", `lv-t-${r.id}`, r.n === 0 ? "zero" : ""], dataset: {type: r.id}},
    h("span", {class: "kd-rn"}, h("i", {class: "kd-sw", "aria-hidden": "true"}), r.ko),
    h("b", {class: "num"}, cnt(r.n, "건")), h("small", null, r.n === 0 ? "—" : P0(r.share ?? r.n / total)),
    h("span", {class: ["kd-rm", "num", r.mean == null ? "" : fmt.tone(r.mean)]}, r.mean == null ? "평균 —" : `평균 ${P(r.mean, true)}`))));
  return [bar, legend];
}
function typeWords(L) {
  return ui.disclosure("이 유형들은 무슨 뜻인가요", h("dl", {class: "kd-legend"}, L.types.map((t, i) => h("div", {dataset: {typeword: t.id}},
    h("dt", null, h("i", {class: ["kd-sw", `lv-t-${t.id}`], "aria-hidden": "true"}), `${i + 1}. ${t.ko}`), h("dd", null, t.explain)))));
}

/** One breakdown table: rows [{label_ko, n, share, mean_roe}]; the title says what is split. */
function breakdown(title, rows, id) {
  const body = rows.length ? rows.map((r) => h("tr", {class: "kd-row", dataset: {key: String(r.key)}},
    h("td", {class: "l"}, String(r.label_ko ?? r.key ?? "—")), h("td", {class: "num"}, cnt(r.n, "건")), h("td", {class: "num"}, P0(r.share)),
    h("td", {class: ["num", num(r.mean_roe) == null ? "" : fmt.tone(r.mean_roe)]}, P(r.mean_roe, true))))
    : [h("tr", null, h("td", {class: "l muted", colspan: "4"}, "기록 없음"))];
  return h("div", {class: "lv-bd", dataset: {bd: id}}, h("div", {class: "tbl-wrap"}, h("table", {class: "tbl kd-tbl lv-tbl"}, h("caption", null, title),
    h("thead", null, h("tr", null, h("th", {class: "l", scope: "col"}, "구분"), h("th", {scope: "col"}, "진 거래"), h("th", {scope: "col", title: "이 종류의 진 거래 중 몫"}, "몫"),
      h("th", {scope: "col", title: "그 구분에서 진 거래의 평균 ROE"}, "평균 ROE"))), h("tbody", null, body))));
}
function breakdowns(k, moreCoins) {
  return h("div", {class: "lv-bds"}, breakdown("코인별", k.by.coin, "coin"), breakdown("롱 · 숏", k.by.side, "side"), breakdown("배수", k.by.lev, "lev"),
    breakdown("들어간 시간대 (한국 시간)", k.by.hour, "hour"), breakdown("평일 · 주말 (한국 시간)", k.by.week, "week"),
    moreCoins ? h("p", {class: "note"}, "코인은 진 거래가 많은 순서로 위쪽만 보여 줍니다.") : null);
}

function streakLine(k) {
  const s = k.streak, c = k.cluster;
  const bits = [];
  bits.push(num(s.max) == null ? "연속으로 진 최다: —" : `연속으로 진 최다: ${fmt.int(s.max)}번${s.account ? ` (${s.account})` : ""}`);
  if (num(c.signals) == null) bits.push("같은 신호에 함께 진 기록: —");
  else {
    bits.push(`진 신호 ${fmt.int(c.signals)}개 중 여러 계좌가 한꺼번에 진 신호 ${cnt(c.multi, "개")}`);
    if (num(c.biggest) > 1) bits.push(`가장 큰 신호는 계좌 ${fmt.int(c.biggest)}개가 함께 진 것`);
    bits.push(num(c.multi_share) == null ? "여러 계좌가 함께 진 비율 —" : `진 거래의 ${P0(c.multi_share)}가 여러 계좌가 함께 진 신호에서 나왔습니다`);
  }
  return h("ul", {class: "kd-list lv-streak"}, bits.map((t) => h("li", null, t)));
}

function worstRows(k, L) {
  const tk = new Map(L.types.map((t) => [t.id, t.ko]));
  if (!k.worst.length) return h("p", {class: "empty"}, "아직 진 거래가 없습니다");
  const body = k.worst.map((w) => h("tr", {class: "kd-row", dataset: {account: String(w.account ?? ""), type: String(w.type_id ?? "")}},
    h("td", {class: "l kd-nm"}, h("b", null, String(w.pick ?? w.account ?? "—")), h("small", {class: "muted"}, [w.name, w.tf].filter(Boolean).join(" · "))),
    h("td", {class: "l"}, [String(w.symbol ?? "—").replace(/USDT?$/, ""), SIDE_KO[String(w.side)] || null, num(w.leverage) == null ? null : `${fmt.num(w.leverage, 0)}배`].filter(Boolean).join(" · ")),
    h("td", {class: "num down"}, P(w.roe, true)),
    h("td", {class: "l"}, tk.get(w.type_id) || "—", h("small", {class: "lv-cs"}, REASON_KO[w.exit_reason] || String(w.exit_reason ?? "—"))),
    h("td", {class: "num"}, fmt.kst(w.entry_time)),
    h("td", null, num(w.at) != null && w.account ? h("a", {class: "btn-line sm", href: replayHref(w.account, w.at), title: "이 거래를 봉 하나씩 다시 보기"}, "다시보기") : h("span", {class: "muted"}, "—"))));
  return h("div", {class: "tbl-wrap"}, h("table", {class: "tbl kd-tbl lv-tbl lv-worst"}, h("caption", {class: "sr"}, "가장 크게 진 거래 10개"),
    h("thead", null, h("tr", null, h("th", {class: "l", scope: "col"}, "계좌"), h("th", {class: "l", scope: "col"}, "코인 · 방향 · 배수"), h("th", {scope: "col"}, "ROE"),
      h("th", {class: "l", scope: "col"}, "유형 · 끝난 이유"), h("th", {scope: "col"}, "들어간 때 (한국)"), h("th", {scope: "col"}, "차트"))), h("tbody", null, body)));
}

export function kindCard(k, L) {
  const moreCoins = k.by.coin.length >= 12;
  return ui.card({plate: nameOf(k), sub: `${k.pooled === true ? "모든 종류 합계" : k.suffix || ""} · 진 거래 ${cnt(k.losses, "건")}`, cls: "kd-tcard lv-card", id: `lv-${k.role}`,
    acts: h("span", {class: "row wrap"}, livePill(k), poolPill(k), smallPill(k, L))},
  factsList(k),
  h("h3", {class: "lv-h"}, "진 거래의 유형"), typeBar(k, L), typeWords(L),
  h("h3", {class: "lv-h"}, "어디서 · 언제 졌나"), breakdowns(k, moreCoins),
  h("h3", {class: "lv-h"}, "연속으로 지거나 함께 진 기록"), streakLine(k),
  h("h3", {class: "lv-h"}, "가장 크게 진 거래 10개"), worstRows(k, L));
}

// ---------------------------------------------------------------- the boxes
function ruleBox() {
  return ui.card({plate: "이 화면은 무엇인가요", sub: "숫자와 설명만 보여 줍니다 · 권유하지 않습니다", cls: "kd-rule", id: "lv-rules"},
    h("ol", {class: "kd-list kd-rules"},
      h("li", null, h("b", null, "무엇을 보여 주나"), ": 닫힌 거래 중 진 거래만 모아 어떤 식으로 졌는지, 어떤 코인 · 시간대에 몰렸는지, 가장 크게 진 거래가 무엇이었는지 보여 줍니다."),
      h("li", null, h("b", null, "유형"), ": 거래 기록(손절선 · 가장 유리했던 가격 · 끝난 이유)만으로 붙인 이름입니다. 위에서부터 먼저 맞는 하나만 붙입니다."),
      h("li", null, h("b", null, "표본 적음"), ": 진 거래가 30건 미만이면 우연일 수 있어 결론을 내지 않습니다."),
      h("li", null, h("b", null, "다시보기"), ": 거래마다 있는 링크로 그 거래를 봉 하나씩 다시 볼 수 있습니다.")));
}
function hero(L, shown) {
  return h("section", {class: "card hero dl-verdict s2a-hero kd-hero lv-hero", "aria-label": "한 줄 결론"},
    h("div", {class: "s2a-hrow"}, ui.plate("한 줄 결론")),
    h("p", {class: "dl-vbig"}, L.headline || "진 거래를 계산 중입니다"),
    h("p", {class: "dl-vline"}, `아래에 보는 종류: ${shown.length ? shown.map(nameOf).join(" · ") : "없음"}`),
    h("p", {class: "note"}, "모의 거래 기록입니다. 앞으로를 약속하는 숫자가 아닙니다. 어떤 행동도 권하지 않습니다."));
}
function closing(L) {
  return [
    L.notes.length ? ui.card({plate: "이 숫자의 한계", sub: "읽기 전에 한 번", id: "lv-limits"}, h("ul", {class: "kd-list"}, L.notes.map((t) => h("li", null, t)))) : null,
    h("p", {class: "note"}, L.dsIn ? "이 숫자에는 딥시크 계좌도 들어 있습니다." : "이 숫자는 딥시크를 뺀 후보만으로 계산했습니다 (딥시크 금액은 숨김 설정이라 쓰지 않습니다)."),
    h("p", {class: "assume"}, "모든 계좌는 모의 계좌입니다 (가상 돈). 실제 주문은 넣지 않습니다."),
  ];
}
function missingBox(g, d) {
  if (g.state === "old") return oldLeagueBox(d, "손실 해부 화면은 아직 없습니다.");
  if (g.state === "prep") {
    return ui.card({plate: "준비 중"},
      h("p", {class: "dl-vline"}, "손실 해부 기록은 아직 없습니다. 위 설명은 그대로 적용됩니다."),
      h("p", {class: "note"}, "엔진이 기록을 쓰면 (5분마다) 저절로 나타납니다. 닫힌 거래가 있어야 숫자가 생깁니다."));
  }
  return notReady("후보 리그 기록이 아직 없습니다.");
}

export async function mount(el, ctx) {
  el.classList.add("kd");
  const root = h("div", {class: "kd-root"});
  const saved = local.get("losses-pick", null);
  const st = {pick: PICKS.some((p) => p.id === saved) ? saved : "k2", d: null};
  const seg = ui.seg(PICKS, st.pick, (v) => { st.pick = v; local.set("losses-pick", v); paint(); }, {label: "보는 종류"});
  el.append(ui.screenHead("손실 해부", "어떤 식으로 졌는지, 어디서 언제 몰렸는지, 가장 크게 진 거래"), root);
  put(root, ruleBox(), ui.missing("손실 해부 기록"));

  function paint() {
    const d = st.d, g = gate(d);
    if (g.state !== "ok") { put(root, ruleBox(), missingBox(g, d)); return; }
    const L = g.L;
    seg.set(st.pick);
    const shown = pickKinds(L, st.pick);
    put(root, ruleBox(), hero(L, shown),
      h("div", {class: "row wrap", style: {justifyContent: "flex-end"}}, seg),
      shown.map((k) => kindCard(k, L)), closing(L));
  }
  ctx.onLeague((d) => { st.d = d; paint(); });
}

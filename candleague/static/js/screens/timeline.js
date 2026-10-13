// #/timeline 타임라인: the league's milestones in time order, newest first: the start, the 14일째 확인 and 28일째 판정 days (passed or coming), the first
// closed trade of each of the four watched kinds, the biggest single win and loss of 실전 후보 and 대조, forced liquidations and busts. Each row: the
// time (KST), one plain sentence and a link to the account it is about. At most 60 rows. Numbers and dates only, no advice.
// Data: the snapshot's ``timeline`` (candleague/timeline.py timeline_views). A time may be null (then "—" and the row goes last); a coming day is marked
// 예정 and a passed one 지남 (words, never colour alone). Engine restarts are not recorded with a time, so they are not here (the server's note says so).
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {hasLineup, notReady, oldLeagueBox} from "./pairs.js";

export const css = ["scr/kinds.css", "scr/timeline.css"];

export const RULES_DEFAULT = [
  "무엇을 보여 주나: 리그에서 있었던 큰 일을 시간 순서로, 가장 최근 것이 위에 오게 보여 줍니다. 14일째 확인과 28일째 판정 날짜는 아직 안 왔어도 ‘예정’으로 들어 있습니다.",
  "어떤 일이 들어 있나: 시작 · 14일째 확인 · 28일째 판정 · 실전 후보, 대조와 그 동전 짝의 첫 거래 · 실전 후보와 대조의 가장 큰 이익과 손실 · 강제청산 · 파산.",
  "시간은 한국 시간(KST)입니다. 맨 오른쪽 계좌 이름을 누르면 그 계좌 화면으로 갑니다.",
  "무엇을 하라는 말은 없습니다. 일어난 일을 적은 목록일 뿐입니다.",
];

const num = (x) => (fmt.bad(x) ? null : Number(x));
const TAGS = {install: "", start: "", observe: "", decide: "", first: "", best: "up", worst: "down", liq: "bad", bust: "bad"};

export function normTimeline(x) {
  if (!x || typeof x !== "object" || Array.isArray(x) || !Array.isArray(x.rows)) return null;
  return {
    cap: num(x.cap) ?? 60, more: num(x.more) ?? 0, headline: typeof x.headline_ko === "string" ? x.headline_ko : "",
    notes: Array.isArray(x.note_ko) ? x.note_ko.map(String) : [], undated: Array.isArray(x.undated_ko) ? x.undated_ko.map(String) : [],
    rows: x.rows.filter((r) => r && typeof r === "object"),
  };
}
export function gate(d) {
  if (!d || !d.accounts) return {state: "wait", T: null};
  const T = normTimeline(d.timeline);
  if (T) return {state: "ok", T};
  return {state: hasLineup(d) ? "prep" : "old", T: null};
}

const timeTxt = (r) => (num(r.ms) == null ? "—" : `${fmt.kst(r.ms)}${r.approx === true ? " (대략)" : ""}`);
const dayTxt = (r) => (num(r.ms) == null ? "" : fmt.date(r.ms));
const stateTxt = (r) => (r.state === "coming" ? "예정" : r.state === "done" ? "지남" : "");
function tagPill(r) {
  const cls = TAGS[r.kind] || "";
  return ui.pill(String(r.tag_ko || r.kind || "—"), cls === "bad" ? "bad" : cls === "up" ? "good" : cls === "down" ? "warn" : r.kind === "observe" || r.kind === "decide" ? "accent" : "thin");
}
const statePill = (r) => (r.state ? ui.pill(stateTxt(r), r.state === "coming" ? "warn" : "thin") : null);
const acctLink = (r) => (r.account ? h("a", {class: "tl-acct", href: `#/account/${encodeURIComponent(r.account)}`, title: "이 계좌 보기"}, String(r.account)) : h("span", {class: "muted"}, "—"));

function table(T) {
  const body = T.rows.map((r) => h("tr", {class: ["kd-row", r.state === "coming" ? "tl-coming" : ""], dataset: {kind: r.kind, state: r.state || "", account: r.account || ""}},
    h("td", {class: "l tl-t"}, h("b", {class: "num"}, timeTxt(r)), dayTxt(r) ? h("small", {class: "tl-s"}, dayTxt(r)) : null),
    h("td", {class: "l"}, h("span", {class: "tl-tags"}, tagPill(r), statePill(r))),
    h("td", {class: "l tl-x"}, String(r.text_ko || "—")),
    h("td", {class: "l"}, acctLink(r))));
  return h("div", {class: "tbl-wrap"}, h("table", {class: "tbl kd-tbl tl-tbl"}, h("caption", {class: "sr"}, "리그의 일들 (가장 최근 순)"),
    h("thead", null, h("tr", null, h("th", {class: "l", scope: "col"}, "시각 (KST)"), h("th", {class: "l", scope: "col"}, "무슨 일"), h("th", {class: "l", scope: "col"}, "내용"),
      h("th", {class: "l", scope: "col"}, "계좌"))),
    h("tbody", null, body)));
}
function cards(T) {
  return h("ol", {class: "kd-cards tl-list"}, T.rows.map((r) => h("li", {class: ["kd-kcard", "tl-item", r.state === "coming" ? "tl-coming" : ""],
    dataset: {kind: r.kind, state: r.state || "", account: r.account || ""}},
  h("div", {class: "kd-kh"}, h("b", {class: "num"}, timeTxt(r)), tagPill(r), statePill(r)),
  h("p", {class: "kd-rtext"}, String(r.text_ko || "—")), h("p", {class: "tl-a"}, acctLink(r)))));
}

function ruleBox() {
  return ui.card({plate: "이 화면은 무엇인가요", sub: "일어난 일을 적은 목록입니다 · 권유하지 않습니다", cls: "kd-rule", id: "tl-rules"},
    h("ol", {class: "kd-list kd-rules"}, RULES_DEFAULT.map((t) => {
      const i = t.indexOf(": ");
      return h("li", null, i > 0 ? [h("b", null, t.slice(0, i)), `: ${t.slice(i + 2)}`] : t);
    })));
}
function hero(T) {
  const coming = T.rows.filter((r) => r.state === "coming").length;
  return h("section", {class: "card hero dl-verdict s2a-hero kd-hero tl-hero", "aria-label": "한 줄 결론"},
    h("div", {class: "s2a-hrow"}, ui.plate("한 줄 결론")),
    h("p", {class: "dl-vbig"}, T.headline || "리그의 일들을 모으는 중입니다"),
    h("p", {class: "dl-vline"}, `${fmt.int(T.rows.length)}개 줄${coming ? ` · 아직 안 온 날 ${fmt.int(coming)}개` : ""}${T.more > 0 ? ` · 줄여서 빠진 일 ${fmt.int(T.more)}개` : ""}`),
    h("p", {class: "note"}, "모의 거래 기록입니다. 어떤 행동도 권하지 않습니다."));
}
function closing(T) {
  return [
    T.undated.length ? ui.card({plate: "시각이 없는 기록", sub: "엔진 메모 · 언제였는지는 기록에 없습니다", id: "tl-undated"}, h("ul", {class: "kd-list"}, T.undated.map((t) => h("li", null, t)))) : null,
    T.notes.length ? ui.card({plate: "이 목록의 한계", sub: "읽기 전에 한 번", id: "tl-limits"}, h("ul", {class: "kd-list"}, T.notes.map((t) => h("li", null, t)))) : null,
    h("p", {class: "assume"}, "모의 계좌입니다 (가상 돈). 실제 주문은 넣지 않습니다."),
  ];
}
function missingBox(g, d) {
  if (g.state === "old") return oldLeagueBox(d, "타임라인 화면은 아직 없습니다.");
  if (g.state === "prep") {
    return ui.card({plate: "데이터 준비 중"}, h("p", {class: "dl-vline"}, "타임라인 기록은 아직 없습니다."),
      h("p", {class: "note"}, "엔진이 기록을 쓰면 (5분마다) 저절로 나타납니다."));
  }
  return notReady("후보 리그 기록이 아직 없습니다.");
}

export async function mount(el, ctx) {
  el.classList.add("kd");
  const root = h("div", {class: "kd-root"});
  const saved = local.get("timeline-view", null);
  const st = {view: saved === "card" || saved === "table" ? saved : (typeof innerWidth === "number" && innerWidth < 760 ? "card" : "table"), d: null};
  const seg = ui.seg([{id: "table", label: "표"}, {id: "card", label: "카드"}], st.view, (v) => { st.view = v; local.set("timeline-view", v); paint(); }, {label: "보기"});
  el.append(ui.screenHead("타임라인", "리그에서 있었던 일을 시간 순서로"), root);
  put(root, ruleBox(), ui.missing("타임라인 기록"));

  function paint() {
    const d = st.d, g = gate(d);
    if (g.state !== "ok") { put(root, ruleBox(), missingBox(g, d)); return; }
    const T = g.T;
    seg.set(st.view);
    put(root, ruleBox(), hero(T), h("div", {class: "row wrap", style: {justifyContent: "flex-end"}}, seg),
      ui.card({plate: "일어난 일", sub: "가장 최근이 위 · 한국 시간", cls: "kd-tcard tl-card", id: "tl-rows"},
        T.rows.length ? (st.view === "card" ? cards(T) : table(T)) : ui.empty("아직 적을 일이 없습니다")),
      closing(T));
  }
  ctx.onLeague((d) => { st.d = d; paint(); });
}

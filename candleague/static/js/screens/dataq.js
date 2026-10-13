// #/dataq 데이터 점검: is the engine and its data healthy? One status word and sentence (정상 / 늦음 / 확인 필요) with the reason, a short checklist
// (what was checked, the value, a WORD for the result: never colour alone), and what a beginner should do (usually: nothing, or send this screen to the
// developer). It claims only what the snapshot can show; the rest says 확인 못 함 (for example the last price of each coin is not in the snapshot).
// Data: the snapshot's ``dataq`` (candleague/dataq.py dataq_views), written with the snapshot. The age of the snapshot AFTER it was written is added
// here from the clock (lk.js health, the same limits as the header dot), so a stopped engine can never read 정상 under a stale page.
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as LK from "../lk.js";
import {serverNow} from "../live.js";
import {hasLineup, notReady, oldLeagueBox} from "./pairs.js";

export const css = ["scr/kinds.css", "scr/dataq.css"];

export const RULES_DEFAULT = [
  "무엇을 보여 주나: 엔진이 제때 계산하고 있는지, 기록에 빠지거나 이상한 것이 없는지를 한 문장과 점검표로 보여 줍니다.",
  "무엇을 근거로 하나: 엔진이 이미 써 둔 기록(계산한 시각 · 늦은 정도 · 오류 표시 · 계좌와 거래 숫자)만 씁니다. 기록에 없는 것은 ‘확인 못 함’이라고 씁니다.",
  "‘정상’은 데이터에 이상이 없다는 뜻이지, 수익이나 전략이 좋다는 뜻이 아닙니다.",
];
/** What to do, by status (used when the screen's own clock turns the status worse than the server's). */
export const TODO_DEFAULT = {
  ok: ["지금은 아무것도 하지 않아도 됩니다.", "이 화면은 5분마다 저절로 새로 고쳐집니다."],
  late: ["10~20분만 기다린 뒤 이 화면을 다시 보세요. 따라잡는 중이면 저절로 좋아집니다.", "1시간이 지나도 ‘늦음’이면 이 화면 전체를 캡처해 개발자에게 보내 주세요.", "설정이나 파일은 건드리지 않아도 됩니다."],
  check: ["이 화면 전체를 캡처해 개발자에게 보내 주세요 (아래 ‘확인 필요’ 줄이 보이게).", "‘확인 필요’가 아닌 줄은 참고용입니다. 직접 고치려고 하지 않아도 됩니다.",
    "그동안 이 리그의 숫자는 믿지 말고 보기만 하세요. 모의 거래라 실제 돈은 움직이지 않습니다."],
};
const WORD = {ok: "정상", warn: "주의", bad: "확인 필요", unknown: "확인 못 함"};
const PILL = {ok: "good", warn: "warn", bad: "bad", unknown: "thin"};
const STATUS_KO = {ok: "정상", late: "늦음", check: "확인 필요"};
const STATUS_PILL = {ok: "good", late: "warn", check: "bad"};

const num = (x) => (fmt.bad(x) ? null : Number(x));

export function normDataq(x) {
  if (!x || typeof x !== "object" || Array.isArray(x) || !Array.isArray(x.checks)) return null;
  return {
    status: STATUS_KO[x.status] ? x.status : "check", headline: typeof x.headline_ko === "string" ? x.headline_ko : "", reason: typeof x.reason_ko === "string" ? x.reason_ko : "",
    todo: Array.isArray(x.todo_ko) ? x.todo_ko.map(String) : null, notes: Array.isArray(x.note_ko) ? x.note_ko.map(String) : [],
    engineNotes: Array.isArray(x.engine_notes) ? x.engine_notes.map(String) : [],
    errors: Array.isArray(x.errors) ? x.errors.filter((e) => e && typeof e === "object") : [],
    checks: x.checks.filter((c) => c && typeof c === "object").map((c) => ({...c, level: WORD[c.level] ? c.level : "unknown"})),
  };
}
export function gate(d) {
  if (!d || !d.accounts) return {state: "wait", Q: null};
  const Q = normDataq(d.dataq);
  if (Q) return {state: "ok", Q};
  return {state: hasLineup(d) ? "prep" : "old", Q: null};
}
/** The final status: the server's, made worse by the clock when the record has gone stale since it was written (lk.js health: warn -> 늦음, bad -> 확인 필요). */
export function finalStatus(Q, d) {
  const H = LK.health(d);
  let status = Q.status, why = null;
  if (H.lv === "bad") { status = "check"; why = H.ko; }
  else if (H.lv === "warn" && status === "ok") { status = "late"; why = H.ko; }
  return {status, why, H};
}
/** The checklist with the screen's own row on top: how long ago the engine wrote the record. */
export function allChecks(Q, d, F) {
  const since = num(d && d.generated_ms) == null ? null : Math.max(0, (serverNow() - d.generated_ms) / 1000);
  const lvl = since == null ? "unknown" : since > LK.WRITE_OLD_S ? "bad" : since > LK.WRITE_WARN_S ? "warn" : "ok";
  const mine = {id: "written", label_ko: "엔진이 기록을 쓴 지", value_ko: since == null ? "—" : `${fmt.dur(since)} 전`, level: lvl, core: true,
    detail_ko: since == null ? "이 스냅샷에 쓴 시각이 없습니다" : "5분마다 쓰는 기록이 12분을 넘기면 주의, 15분을 넘기면 멈춘 것으로 봅니다"};
  return [mine, ...Q.checks];
}

// ---------------------------------------------------------------- pieces
const wordPill = (c) => ui.pill(WORD[c.level] || WORD.unknown, PILL[c.level] || "thin", c.detail_ko || undefined);
function table(rows) {
  return h("div", {class: "tbl-wrap"}, h("table", {class: "tbl kd-tbl dq-tbl"}, h("caption", {class: "sr"}, "점검표"),
    h("thead", null, h("tr", null, h("th", {class: "l", scope: "col"}, "무엇을 봤나"), h("th", {class: "l", scope: "col"}, "값"), h("th", {class: "l", scope: "col"}, "결과"),
      h("th", {class: "l", scope: "col"}, "설명"))),
    h("tbody", null, rows.map((c) => h("tr", {class: "kd-row", dataset: {check: c.id, level: c.level}},
      h("td", {class: "l kd-nm"}, h("b", null, String(c.label_ko || c.id || "—"))), h("td", {class: "l num"}, String(c.value_ko ?? "—")),
      h("td", {class: "l"}, wordPill(c)), h("td", {class: "l dq-d"}, c.detail_ko ? String(c.detail_ko) : h("span", {class: "muted"}, "—")))))));
}
function cards(rows) {
  return h("div", {class: "kd-cards"}, rows.map((c) => h("article", {class: ["kd-kcard", c.level === "bad" ? "dq-bad" : ""], dataset: {check: c.id, level: c.level}, "aria-label": String(c.label_ko || c.id)},
    h("div", {class: "kd-kh"}, h("b", null, String(c.label_ko || c.id || "—")), wordPill(c)),
    h("p", {class: "kd-kbig"}, h("b", {class: "num"}, String(c.value_ko ?? "—"))),
    c.detail_ko ? h("p", {class: "note"}, String(c.detail_ko)) : null)));
}

function ruleBox() {
  return ui.card({plate: "이 화면은 무엇인가요", sub: "엔진과 데이터가 건강한지 · 권유하지 않습니다", cls: "kd-rule", id: "dq-rules"},
    h("ol", {class: "kd-list kd-rules"}, RULES_DEFAULT.map((t) => {
      const i = t.indexOf(": ");
      return h("li", null, i > 0 ? [h("b", null, t.slice(0, i)), `: ${t.slice(i + 2)}`] : t);
    })));
}
function hero(Q, F, rows) {
  const n = {ok: 0, warn: 0, bad: 0, unknown: 0};
  for (const c of rows) n[c.level] += 1;
  const sentence = F.why ? `${STATUS_KO[F.status]}: ${F.why}` : Q.headline || STATUS_KO[F.status];
  return h("section", {class: ["card hero dl-verdict s2a-hero kd-hero dq-hero", `dq-${F.status}`], "aria-label": "한 줄 결론", dataset: {status: F.status}},
    h("div", {class: "s2a-hrow"}, ui.plate("한 줄 결론"), ui.pill(STATUS_KO[F.status], STATUS_PILL[F.status])),
    h("p", {class: ["dl-vbig", F.status === "ok" ? "" : "warn"]}, sentence),
    h("p", {class: "dl-vline"}, `점검 ${fmt.int(rows.length)}개 · 정상 ${fmt.int(n.ok)} · 주의 ${fmt.int(n.warn)} · 확인 필요 ${fmt.int(n.bad)} · 확인 못 함 ${fmt.int(n.unknown)}`),
    h("p", {class: "note"}, "모의 거래 기록의 점검입니다. 수익이 좋은지는 알려 주지 않습니다."));
}
function todoCard(Q, F) {
  const todo = F.status === Q.status && Q.todo && Q.todo.length ? Q.todo : TODO_DEFAULT[F.status];
  return ui.card({plate: "어떻게 하면 되나요", sub: F.status === "ok" ? "지금은 할 일이 없습니다" : "처음 보는 분을 위한 안내", cls: "kd-tcard dq-todo", id: "dq-todo"},
    h("ol", {class: "kd-list"}, todo.map((t) => h("li", null, t))));
}
function checkCard(rows, view) {
  return ui.card({plate: "점검표", sub: "무엇을 봤고, 값이 얼마이고, 결과가 어떤지", cls: "kd-tcard dq-card", id: "dq-checks"}, view === "card" ? cards(rows) : table(rows));
}
function extras(Q) {
  return [
    Q.errors.length ? ui.card({plate: "계산 중 난 오류", sub: "이 화면의 일부 기록을 만들지 못했습니다 · 개발자에게 보여 주세요", id: "dq-errors"},
      h("ul", {class: "kd-list"}, Q.errors.map((e) => h("li", null, h("b", null, String(e.key ?? "—")), `: ${String(e.text ?? "")}`)))) : null,
    Q.engineNotes.length ? ui.card({plate: "엔진 메모", sub: "신호를 계산하다 생긴 일 (최근 것)", id: "dq-notes"}, h("ul", {class: "kd-list"}, Q.engineNotes.map((t) => h("li", null, t)))) : null,
    Q.notes.length ? ui.card({plate: "이 점검의 한계", sub: "읽기 전에 한 번", id: "dq-limits"}, h("ul", {class: "kd-list"}, Q.notes.map((t) => h("li", null, t)))) : null,
    h("p", {class: "assume"}, "모의 계좌입니다 (가상 돈). 실제 주문은 넣지 않습니다."),
  ];
}
function missingBox(g, d) {
  if (g.state === "old") return oldLeagueBox(d, "데이터 점검 화면은 아직 없습니다.");
  if (g.state === "prep") {
    return ui.card({plate: "데이터 준비 중"}, h("p", {class: "dl-vline"}, "점검 기록은 아직 없습니다."),
      h("p", {class: "note"}, "엔진이 기록을 쓰면 (5분마다) 저절로 나타납니다. 다른 화면의 ‘서버 상태’에서 엔진 상태를 먼저 볼 수 있습니다."));
  }
  return notReady("후보 리그 기록이 아직 없습니다.");
}

export async function mount(el, ctx) {
  el.classList.add("kd");
  const root = h("div", {class: "kd-root"});
  const saved = local.get("dataq-view", null);
  const st = {view: saved === "card" || saved === "table" ? saved : (typeof innerWidth === "number" && innerWidth < 760 ? "card" : "table"), d: null};
  const seg = ui.seg([{id: "table", label: "표"}, {id: "card", label: "카드"}], st.view, (v) => { st.view = v; local.set("dataq-view", v); paint(); }, {label: "보기"});
  el.append(ui.screenHead("데이터 점검", "엔진과 데이터가 건강한지"), root);
  put(root, ruleBox(), ui.missing("데이터 점검 기록"));

  function paint() {
    const d = st.d, g = gate(d);
    if (g.state !== "ok") { put(root, ruleBox(), missingBox(g, d)); return; }
    const Q = g.Q, F = finalStatus(Q, d), rows = allChecks(Q, d, F);
    seg.set(st.view);
    put(root, hero(Q, F, rows), todoCard(Q, F), h("div", {class: "row wrap", style: {justifyContent: "flex-end"}}, seg), checkCard(rows, st.view), extras(Q), ruleBox());
  }
  ctx.onLeague((d) => { st.d = d; paint(); });
}

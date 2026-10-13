// #/events 발동 기록: 메인 계좌의 규칙이 실제로 거래를 건드린 때를 새 것부터 쉬운 말 한 줄씩 보여 준다.
// 세 가지: 빠른 청산 (구조가 무너져 청산), 손절 좁힘 (청산하지 않고 손절선만 좁힘), 스위칭 (반대 신호로 청산하고 반대로 진입).
// 한 줄 = "15분 DOGE 롱 · 구조가 무너져 빠른 손절 · 손실 −17% · 대조는 −38%" (대조 = 같은 신호에서 원래 방식으로 나온 계좌).
// Data: the shared snapshot's ``events`` ([{time, account, pick, role, name, tf, kind, side, symbol, event, roe, hold_h, control_roe}],
// newest first) and ``lineup``. ROE fractions; null = unknown: "—", never 0. An older snapshot (no lineup) gets a short note.
// Every string reaches the page as a text node.
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as LK from "../lk.js";
import {tfKo} from "../labels.js";
import {hasLineup, lineupOf, kindOf, kindName, loadJudge, nameKo, notReady, oldLeagueBox, bigLine, pc, diffWord, WORD_CLS, sideWord, coinOf, accountId, SAME_EPS} from "./pairs.js";

export const EVENT_KO = {rule_exit: "빠른 청산", narrowed: "손절 좁힘", switch: "스위칭"};
const EVENT_ICON = {rule_exit: "×", narrowed: "↘", switch: "⇄"};
const EVENT_CLS = {rule_exit: "warn", narrowed: "thin", switch: "accent"};
const EVENT_WHAT = {
  rule_exit: "구조가 무너져 청산",
  narrowed: "청산하지 않고 손절선만 좁힘",
  switch: "반대 신호로 청산하고 같은 분에 반대로 진입",
};
const ok = (x) => !fmt.bad(x);

/** Why it fired, in plain words, by the kind of account (the event's role) and the type. */
export function reasonText(d, e) {
  if (e.event === "narrowed") return "구조가 무너져 손절을 좁힘";
  if (e.event === "switch") return "반대 신호가 나와 청산하고 반대로 갈아탐";
  const k = kindOf(d, e.role), suffix = k ? k.suffix : "";
  if (e.role === "fq" || suffix === "-fq") return "구조가 무너져 빠른 손절";
  if (e.role === "nv" || suffix === "-nv") return "매매법이 구조가 무너졌다고 보고 청산";
  if (e.role === "sw" || suffix === "-sw") return "반대 신호가 나와 청산";
  return `${kindName(d, e.role)} 규칙으로 청산`;
}
/** "손실 −17%" / "수익 +5.0%" / "손익 —". */
export function resultText(roe) {
  if (!ok(roe)) return "손익 —";
  const v = Number(roe);
  return Math.abs(v) < SAME_EPS ? `본전 ${pc(v)}` : v < 0 ? `손실 ${pc(v)}` : `수익 ${pc(v, true)}`;
}
/** The sentence of one event: "15분 DOGE 롱 · 구조가 무너져 빠른 손절 · 손실 −17% · 대조는 −38%". */
export function eventLine(d, e) {
  return [`${tfKo(e.tf)} ${coinOf(e.symbol)} ${sideWord(e.side)}`, reasonText(d, e), resultText(e.roe),
    `대조는 ${ok(e.control_roe) ? pc(e.control_roe, true) : "—"}`].join(" · ");
}
const known = (e) => e && typeof e === "object" && EVENT_KO[e.event];

/** How many events of each type, and how they came out against the control (both ROEs known only). */
export function tally(events) {
  const t = {n: events.length, by: {rule_exit: 0, narrowed: 0, switch: 0}, better: 0, worse: 0, same: 0};
  for (const e of events) {
    t.by[e.event] += 1;
    const w = ok(e.roe) && ok(e.control_roe) ? diffWord(Number(e.roe) - Number(e.control_roe)) : null;
    if (w === "낫다") t.better += 1; else if (w === "못하다") t.worse += 1; else if (w === "같다") t.same += 1;
  }
  return t;
}

export async function mount(el, ctx) {
  try { await ctx.meta(); } catch (e) { /* names fall back to the codes */ }
  const q = ctx.params.query || {};
  const st = {kind: q.kind || "all", key: ""};
  const hero = h("section", {class: "card hero", "aria-label": "발동 요약"});
  const chips = h("div"), countLine = h("p", {class: "note"});
  const pg = ui.pager({size: 15, empty: "이 종류의 발동은 아직 없습니다", render: (part) => feed(part)});
  const feedCard = ui.card({plate: "발동한 거래", sub: "새 것부터 · 한 줄에 한 번"}, chips, countLine, pg.el);
  feedCard.hidden = true;
  const legend = h("div");
  el.append(ui.screenHead("발동 기록", "메인 계좌의 규칙이 실제로 거래를 건드린 때"), hero, feedCard, legend);

  let doc = null, rows = [];
  const save = () => ctx.setQuery(st.kind === "all" ? {} : {kind: st.kind});
  const shown = () => (st.kind === "all" ? rows : rows.filter((e) => e.role === st.kind));

  function feed(part) {
    return h("div", {class: "cl-exits", role: "list"}, part.map((e) => {
      const id = e.account || accountId(doc, e.pick, e.role);
      const line = eventLine(doc, e);
      const diff = ok(e.roe) && ok(e.control_roe) ? diffWord(Number(e.roe) - Number(e.control_roe)) : null;
      const hold = ok(e.hold_h) ? ` · 보유 ${fmt.dur(Number(e.hold_h) * 3600)}` : "";
      const text = h("span", {style: {flex: "1 1 16em", minWidth: "0", fontWeight: "700"}, class: "ev-line"}, line);
      return h("div", {role: "listitem", dataset: {event: e.event, role: e.role}},
        ui.pill(`${EVENT_ICON[e.event]} ${EVENT_KO[e.event]}`, EVENT_CLS[e.event], EVENT_WHAT[e.event]),
        id ? h("a", {class: "cl-plain", href: `#/account/${encodeURIComponent(id)}`, title: "이 계좌 자세히", style: {flex: "1 1 16em", minWidth: "0"}}, text) : text,
        diff ? ui.pill(diff === "같다" ? "대조와 같다" : `대조보다 ${diff}`, WORD_CLS[diff], `이 거래의 ROE가 같은 신호에서 대조 계좌가 낸 ROE보다 ${diff === "같다" ? "다르지 않다" : diff}`) : null,
        h("small", {class: "muted", style: {flexBasis: "100%"}}, `${nameKo(e.name)} · ${kindName(doc, e.role)} · ${fmt.kst(e.time)}${hold}`));
    }));
  }
  function countText() {
    const n = shown().length;
    countLine.textContent = `${fmt.int(n)}번 보는 중${st.kind === "all" ? "" : ` (${kindName(doc, st.kind)})`} · 전체 ${fmt.int(rows.length)}번 · 새 것부터`;
  }

  const legendCard = () => ui.card({plate: "읽는 법", sub: "발동 = 메인 계좌의 규칙이 실제로 일한 때"},
    h("div", {class: "stack tight"},
      h("dl", {class: "kv", style: {gridTemplateColumns: "minmax(0, 1fr)"}},
        Object.keys(EVENT_KO).map((k) => h("div", null, h("dt", null, ui.pill(`${EVENT_ICON[k]} ${EVENT_KO[k]}`, EVENT_CLS[k])), h("dd", null, EVENT_WHAT[k])))),
      h("p", {class: "note"}, `손실 · 수익은 그 거래가 끝난 결과(ROE, 증거금 대비 수익률)입니다. 손절 좁힘은 구조가 무너져 손절선을 좁힌 거래의 최종 결과입니다. “대조는”은 같은 신호에서 원래 방식(계단 익절 · 손절 최대 2 ATR)으로 나온 대조 계좌의 ROE이고, “—”이면 아직 모르거나 숨긴 값입니다. 모든 계좌는 ${LK.startUsd()}에서 시작합니다.`)));

  function off(card) { card.hidden = true; }
  function paint(d) {
    doc = d;
    LK.setEquity(d && d.equity0);                    // the start wallet in the text below ($1,000 or $5,000) is this snapshot's
    put(legend, legendCard());
    if (!d || !d.accounts) { put(hero, ui.plate("발동 기록"), notReady("후보 리그 기록이 아직 없습니다.")); off(feedCard); return; }
    if (!hasLineup(d)) { put(hero, ui.plate("발동 기록"), oldLeagueBox(d, "메인 계좌의 발동 기록은 아직 없습니다.")); off(feedCard); return; }
    if (!Array.isArray(d.events)) { put(hero, ui.plate("발동 기록"), notReady("발동 기록이 아직 없습니다.")); off(feedCard); return; }
    rows = d.events.filter(known).slice().sort((a, b) => (Number(b.time) || 0) - (Number(a.time) || 0));
    if (!rows.length) {
      put(hero, ui.plate("발동 기록"), bigLine("아직 발동한 적 없음 (구조가 확실히 무너진 거래가 아직 없습니다)"),
        h("p", {class: "note"}, "구조가 확실히 무너진 거래가 생기면 여기에 한 줄씩 쌓입니다."));
      off(feedCard);
      return;
    }
    const t = tally(rows);
    const parts = Object.keys(EVENT_KO).filter((k) => t.by[k]).map((k) => `${EVENT_KO[k]} ${fmt.int(t.by[k])}`);
    const cmp = t.better + t.worse + t.same;
    put(hero, ui.plate("한 줄 결론"), bigLine(`규칙이 ${fmt.int(t.n)}번 발동했습니다 (${parts.join(" · ")})`),
      h("p", {class: "note"}, cmp ? `대조 결과를 아는 ${fmt.int(cmp)}번 중 대조보다 낫다 ${fmt.int(t.better)}번 · 못하다 ${fmt.int(t.worse)}번 · 같다 ${fmt.int(t.same)}번 (한두 번으로는 알 수 없고, 많이 쌓여야 믿을 수 있습니다)`
        : "대조 결과는 같은 신호의 대조 거래가 끝나면 함께 나옵니다."));
    const present = lineupOf(d).map((k) => k.role).filter((r) => rows.some((e) => e.role === r));
    rows.forEach((e) => { if (!present.includes(e.role)) present.push(e.role); });
    if (st.kind !== "all" && !present.includes(st.kind)) st.kind = "all";
    const key = JSON.stringify([present, st.kind]);
    if (key !== st.key) {
      st.key = key;
      put(chips, present.length > 1 ? h("div", {class: "dl-fields"}, ui.field("종류", ui.seg(
        [{id: "all", label: `전체 ${fmt.int(rows.length)}`}, ...present.map((r) => ({id: r, label: `${kindName(d, r)} ${fmt.int(rows.filter((e) => e.role === r).length)}`}))],
        st.kind, (v) => { st.kind = v; st.key = ""; save(); pg.set(shown(), false); countText(); }, {label: "종류"}))) : null);
    }
    pg.set(shown(), true);
    countText();
    feedCard.hidden = false;
  }
  ctx.onLeague(paint);
  loadJudge(ctx).then(() => { if (ctx.alive() && doc) paint(doc); }).catch(() => { /* codes stay */ });
}

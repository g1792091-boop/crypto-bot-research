// #/judge 매매법별 구조 기준: 빠른 손절 · 손절 좁힘 · 매매법 판단 계좌는 "그 매매법 자체가 구조가 무너졌다고 볼 때"만 움직인다.
// 맨 위에 두 상자 (빠른 손절은 언제 나가나? · 스위칭은 언제 하나?), 아래에 매매법마다 카드: 무엇에 거는 매매법인가, 자체 구조 기준
// (롱 구조가 무너졌다 · 숏 구조가 무너졌다), 쓰는 봉, 지금까지 발동한 횟수. 리그의 27개 매매법 모두 자체 구조 기준이 있다
// (11개는 리그가 새로 정했다). 기준이 없는 매매법이 생기면 그 카드에는 빠른 손절 · 손절 좁힘 · 매매법 판단 계좌가 없다.
// Data: GET /api/judge (candleague/data/native_ko.json, from research/exitflex/native.py, native_ds.py, README_KO.md) and the shared
// snapshot (the picks' strategies and timeframes from ``accounts``, the counts from ``events``, the kinds from ``lineup``).
// A failed or empty /api/judge leaves the top boxes and the list of strategies, with a note. Every string is a text node.
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as LK from "../lk.js";
import {TFS, tfKo} from "../labels.js";
import {hasLineup, lineupOf, isResearch, loadJudge, nameKo, notReady, oldLeagueBox, bigLine} from "./pairs.js";
import {EVENT_KO} from "./events.js";

/** The strategies of the snapshot's picks: {name, kind, tfs (in the order of the bars), picks}; one per strategy. */
export function strategiesOf(d) {
  const by = new Map(), seen = new Set();
  for (const a of (d && Array.isArray(d.accounts) ? d.accounts : [])) {
    const pid = a.pick || (a.role === "cand" ? a.id : null);
    if (!pid || !a.name || seen.has(pid)) continue;
    seen.add(pid);
    if (!by.has(a.name)) by.set(a.name, {name: a.name, kind: a.kind, tfs: new Set(), picks: 0});
    const s = by.get(a.name);
    s.tfs.add(a.tf);
    s.picks += 1;
  }
  return [...by.values()].map((s) => ({...s, tfs: [...s.tfs].sort((x, y) => TFS.indexOf(x) - TFS.indexOf(y))}));
}
/** How many events of each type each strategy has produced so far ({name: {rule_exit, narrowed, switch}}), null when the snapshot
 *  carries no ``events`` list. */
export function eventCounts(d) {
  if (!d || !Array.isArray(d.events)) return null;
  const out = {};
  for (const e of d.events) {
    if (!e || !e.name || !EVENT_KO[e.event]) continue;
    const c = out[e.name] || (out[e.name] = {rule_exit: 0, narrowed: 0, switch: 0});
    c[e.event] += 1;
  }
  return out;
}

export async function mount(el, ctx) {
  try { await ctx.meta(); } catch (e) { /* names fall back to the codes */ }
  const q = ctx.params.query || {};
  const st = {own: q.own || "all"};
  const top = h("div", {class: "stack"});
  const note = h("div");
  const list = h("div");
  const chips = h("div");
  const listCard = ui.card({plate: "매매법마다", sub: "무엇에 거는지 · 자체 구조 기준 · 쓰는 봉 · 지금까지 발동"}, note, chips, list);
  el.append(ui.screenHead("매매법별 구조 기준", "빠른 손절이 “구조가 무너졌다”를 매매법마다 어떻게 보나"), top, listCard);

  let doc = null, J = null, state = "loading", err = null;      // state: loading | ok | empty | fail
  const save = () => ctx.setQuery(st.own === "all" ? {} : {own: st.own});
  async function load(force) {
    state = "loading"; err = null;
    try {
      J = await loadJudge(ctx, force);
      state = J ? "ok" : "empty";
    } catch (e) {
      if (!ctx.alive()) return;
      J = null; state = "fail"; err = e;
    }
    if (ctx.alive() && doc) paint(doc);
  }

  function topBoxes(d) {
    const none = J ? Object.values(J).filter((x) => x && x.native === false).length : 0;
    const research = lineupOf(d).filter(isResearch);
    return [
      ui.card({plate: "빠른 손절은 언제 나가나?", sub: "두 가지가 모두 맞을 때만 · 봉이 마감할 때만 확인", hero: true},
        bigLine("자체 구조가 무너졌고 손실이 손절 거리의 절반을 넘었을 때만 나갑니다."),
        h("ol", null,
          h("li", null, h("b", null, "그 매매법 자체 구조 기준이 무너졌고"), " (롱이면 롱 구조, 숏이면 숏 구조)"),
          h("li", null, h("b", null, "그때 손실이 손절 거리의 절반을 넘었을 때"), " (예: 손절선이 −60%면 손실이 약 −30%보다 깊을 때)")),
        h("p", null, h("b", null, "둘 중 하나만으로는 나가지 않습니다.")),
        h("p", {class: "note"}, "구조가 무너졌는지는 봉이 마감할 때만 봅니다. 그래서 봉 한가운데의 잠깐 흔들림에는 나가지 않습니다. 손절선(최대 2 ATR)은 안전장치로 그대로 있습니다."),
        h("p", null, h("b", null, "손절 좁힘"), "과 ", h("b", null, "매매법 판단"), "도 같은 구조 기준을 씁니다. 손절 좁힘은 구조가 무너지면 청산하지 않고 손절선만 처음 거리의 절반으로 좁히고, ",
          "매매법 판단은 구조가 무너지면 손실이든 이익이든 청산합니다."),
        h("p", {class: "cl-caveat"}, `빠른 손절과 손절 좁힘은 그 매매법 자체 구조 기준만 씁니다. ${none || !J ? `그래서 자체 구조 코드가 없는 ${none ? `${fmt.int(none)}개 ` : ""}매매법에는 이 계좌들이 없습니다 (아래 “자체 구조 기준 없음” 카드).` : "이 리그의 매매법은 모두 자체 구조 기준이 있어서 모든 후보에 이 계좌들이 있습니다."}`),
        research.length ? h("p", {class: "note"}, `비교용으로 “${research.map((k) => String(k.label_ko).replace(/^연구\s*·\s*/, "")).join(" · ")}” 계좌가 따로 있습니다. `
          + "모든 매매법에 똑같이 최근 확인된 스윙 3봉 구조를 쓰는 연구용이고, 실전 후보가 아닙니다.") : null,
        h("p", {class: "note"}, "아래 조건의 숫자(평균선 길이, 기준값 등)는 후보마다 커스텀값을 씁니다.")),
      ui.card({plate: "스위칭은 언제 하나?", sub: "반대 방향 신호가 나올 때만"},
        h("ol", null,
          h("li", null, h("b", null, "그 매매법이 스스로 반대 방향 진입 신호를 낼 때"), "만 합니다."),
          h("li", null, "그때 지금 포지션을 청산하고 ", h("b", null, "같은 분에 반대 방향으로 진입"), "합니다.")),
        h("p", {class: "note"}, "반대 신호가 나오지 않으면 아무것도 하지 않고, 계단 익절 · 손절만 그대로 일합니다. 스위칭은 반대 방향 신호만 있으면 되므로 모든 후보에 계좌가 있습니다.")),
    ];
  }

  function card(s, j, counts, on) {
    const own = j ? j.native === true : null;
    const name = nameKo(s.name);
    const c = counts ? counts[s.name] || {rule_exit: 0, narrowed: 0, switch: 0} : null;
    const total = c ? c.rule_exit + c.narrowed + c.switch : 0;
    const parts = c ? Object.keys(EVENT_KO).filter((k) => c[k]).map((k) => `${EVENT_KO[k]} ${fmt.int(c[k])}번`) : [];
    return h("div", {class: "cl-ecard", id: `j-${s.name}`, dataset: {strategy: s.name, own: own == null ? "unknown" : String(own)}},
      h("div", {class: "cl-ehead"}, (s.kind || (j && j.kind)) ? LK.kindChip(s.kind || j.kind) : null, h("b", null, name), name !== s.name ? h("small", {class: "cl-code"}, s.name) : null,
        h("span", {class: "grow"}),
        own == null ? null : ui.pill(own ? "자체 구조 기준 있음" : "자체 구조 기준 없음", own ? "good" : "thin",
          own ? "이 매매법은 자기 구조가 무너졌는지 스스로 판단하는 코드가 있습니다" : "자체 구조 청산 코드가 없는 매매법입니다")),
      s.tfs.length ? h("p", {class: "note"}, "쓰는 봉: ", s.tfs.map((t) => tfKo(t)).join(" · "), ` (후보 ${fmt.int(s.picks)}개)`) : null,
      j ? h("p", null, h("b", null, "무엇에 거나? "), j.bet_ko) : h("p", {class: "note"}, "이 매매법의 설명 자료가 아직 없습니다."),
      j && own ? h("div", {class: "stack tight"},
        h("h3", {class: "cl-h3"}, "자체 구조 기준"),
        h("div", null, h("span", {class: "side long"}, "롱 구조가 무너졌다"), h("p", {style: {margin: "4px 0 0"}}, j.long_broken_ko || "—")),
        h("div", null, h("span", {class: "side short"}, "숏 구조가 무너졌다"), h("p", {style: {margin: "4px 0 0"}}, j.short_broken_ko || "—")))
        : j ? h("p", null, h("b", null, "자체 구조 기준: 없음. "), "롱 · 숏 구조가 무너졌다는 기준이 없어 빠른 손절 · 손절 좁힘 · 매매법 판단 계좌가 이 매매법에는 없습니다.") : null,
      j && j.notes_ko ? h("p", {class: "note"}, j.notes_ko) : null,
      c ? h("p", {class: "note"}, h("b", null, "메인 규칙 발동: "), total ? `${fmt.int(total)}번 (${parts.join(" · ")})` : "아직 없음") : null);
  }

  function paint(d) {
    doc = d;
    LK.setEquity(d && d.equity0);
    put(top, topBoxes(d));
    const strat = strategiesOf(d);
    if (!strat.length && J) for (const [n, j] of Object.entries(J)) strat.push({name: n, kind: j.kind, tfs: [], picks: 0});   // no snapshot yet: the file's names
    const hasD = !!(d && d.accounts);
    put(note,
      hasD && !hasLineup(d) ? oldLeagueBox(d, "메인 계좌의 발동 횟수는 아직 없고, 아래 설명은 새 리그의 규칙입니다.") : null,
      state === "loading" ? h("p", {class: "note"}, "매매법 설명을 불러오는 중입니다") : null,
      state === "fail" ? ui.errorBox(err, () => load(true)) : null,
      state === "empty" ? notReady("매매법별 설명 자료가 아직 없습니다.") : null,
      state !== "ok" && !strat.length && hasD ? h("p", {class: "empty"}, "후보가 아직 없습니다") : null);
    if (!strat.length) { put(chips, null); put(list, null); chips.dataset.key = ""; return; }
    const withJ = strat.map((s) => ({s, j: J ? J[s.name] || null : null}));
    const nOwn = withJ.filter((x) => x.j && x.j.native === true).length, nNone = withJ.filter((x) => x.j && x.j.native === false).length;
    const key = `${nOwn}|${nNone}|${st.own}`;
    if (chips.dataset.key !== key) {
      chips.dataset.key = key;
      put(chips, J ? h("div", {class: "dl-fields"}, ui.field("자체 구조", ui.seg(
        [{id: "all", label: `전체 ${fmt.int(withJ.length)}`}, {id: "own", label: `기준 있음 ${fmt.int(nOwn)}`}, {id: "none", label: `기준 없음 ${fmt.int(nNone)}`}],
        st.own, (v) => { st.own = v; chips.dataset.key = ""; save(); paint(doc); }, {label: "자체 구조 기준"}))) : null);
    }
    const counts = hasLineup(d) ? eventCounts(d) : null;
    const rank = (x) => (x.j ? (x.j.native ? 0 : 2) : 1) * 2 + (x.s.kind === "ds" ? 1 : 0);
    const rows = withJ.filter((x) => st.own === "all" || !x.j || (st.own === "own" ? x.j.native === true : x.j.native === false))
      .sort((a, b) => rank(a) - rank(b) || nameKo(a.s.name).localeCompare(nameKo(b.s.name), "ko"));
    put(list, rows.length ? h("div", {class: "cl-egrid"}, rows.map((x) => card(x.s, x.j, counts))) : ui.empty("맞는 매매법이 없습니다"));
  }
  ctx.onLeague(paint);
  await load(false);
  if (!doc && ctx.alive()) paint(null);                    // no snapshot yet: the rules and the file's own list
}

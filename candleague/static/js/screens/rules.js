// #/rules 익절·손절·배수 (owners 2026-10-12: "커스텀봇 각 매매법마다 익절구조 손절구조를 어떻게 잡았는지 대시보드에 표시한
// 부분이 있어? 지금 돌아가고 있는 커스텀봇 레버리지는 어떻게 적용되는거고 언제부터 봇 돌리기 시작한거야?"): the short answers
// first (the exits of the 38 picks, the leverage rule, the start), then the leverage rule with its steps and checks,
// what the five accounts of a pick do differently, every pick's take-profit and stop in one list (종류 · 봉 · 매매법
// filters) and the chosen pick's rule card (익절, 손절, 본전 승률, 배수, 지금 이 숫자면: the six coins today, the five
// accounts' exits and the leverages they used). ?pick=<id> chooses a pick, ?s=<strategy> filters to one strategy.
// Data: /api/rules (dash.py rules_doc) and the shared snapshot. Every string reaches the page as a text node.
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as LK from "../lk.js";
import * as RK from "../rulekit.js";
import {TFS, tfKo} from "../labels.js";
import {serverNow} from "../live.js";

export async function mount(el, ctx) {
  let meta = null;
  try { meta = await ctx.meta(); } catch (e) { /* codes */ }
  const q = ctx.params.query || {};
  const st = {kind: q.kind || "all", tf: q.tf || "all", strat: q.s || "all", pick: q.pick || null};
  const save = () => ctx.setQuery(Object.fromEntries(Object.entries({kind: st.kind, tf: st.tf, s: st.strat, pick: st.pick})
    .filter(([, v]) => v && v !== "all")));
  const answers = h("div"), rule = h("div"), list = h("div"), card = h("div", {id: "rl-pick"}), stratSel = h("span");
  el.append(
    ui.screenHead("익절·손절·배수", "후보마다 익절·손절을 어떻게 잡았고, 배수(레버리지)와 증거금은 어떻게 정하나"),
    ui.card({plate: "짧은 답", cls: "rl-answers"}, answers),
    ui.card({plate: "배수(레버리지) 규칙", sub: "다섯 계좌 모두 같은 규칙 · 규칙봇과 같은 엔진 (paperbot)"}, rule),
    ui.card({plate: "계좌 5개는 무엇이 다른가", sub: "같은 후보에서 갈라진 다섯 계좌 · 같은 시세 · 같은 기간"}, RK.rolesTable()),
    ui.card({plate: "후보마다 익절 · 손절", sub: "누르면 아래에 그 후보의 카드"},
      h("div", {class: "dl-fields"},
        ui.field("종류", ui.seg([{id: "all", label: "전체"}, {id: "core", label: "기존 36"}, {id: "ds", label: "딥시크"}], st.kind, (v) => { st.kind = v; st.strat = "all"; save(); paint(); }, {label: "종류"})),
        ui.field("봉", ui.seg([{id: "all", label: "전체"}, ...TFS.map((t) => ({id: t, label: tfKo(t)}))], st.tf, (v) => { st.tf = v; save(); paint(); }, {label: "봉"})),
        ui.field("매매법", stratSel)),
      list),
    card);

  let R = null;
  function pickRows(d) {
    const ix = LK.index(d);
    return ix.cands.filter((c) => (st.kind === "all" || c.kind === st.kind) && (st.tf === "all" || c.tf === st.tf) && (st.strat === "all" || c.name === st.strat))
      .sort((a, b) => (a.kind === b.kind ? 0 : a.kind === "core" ? -1 : 1) || LK.stratKo(a.name, meta).localeCompare(LK.stratKo(b.name, meta), "ko")
        || TFS.indexOf(a.tf) - TFS.indexOf(b.tf));
  }
  function paint() {
    const d = LK.league();
    if (!d || !d.accounts) { put(list, ui.none("준비 중")); return; }
    const ix = LK.index(d);
    put(answers, answersBody(d, R));
    put(rule, R ? RK.levRuleBody(R) : ui.none("규칙 숫자를 불러오는 중"));
    const names = [...new Set(ix.cands.filter((c) => st.kind === "all" || c.kind === st.kind).map((c) => c.name))]
      .sort((a, b) => LK.stratKo(a, meta).localeCompare(LK.stratKo(b, meta), "ko"));
    put(stratSel, ui.select([{id: "all", label: `전체 (${names.length}개)`}, ...names.map((n) => ({id: n, label: `${LK.stratKo(n, meta)} (${n})`}))],
      st.strat, (v) => { st.strat = v; save(); paint(); }, "매매법"));
    const rows = pickRows(d);
    if (!st.pick || !ix.byId[st.pick]) st.pick = rows.length ? rows[0].id : null;
    put(list, rows.length ? h("div", {class: "rl-list"}, rows.map((c) => pickRow(c, R, st.pick === c.id, () => {
      st.pick = c.id; save(); paint();
      const t = document.getElementById("rl-pick");
      if (t && t.scrollIntoView) requestAnimationFrame(() => t.scrollIntoView({block: "start", behavior: "smooth"}));
    }))) : ui.empty("맞는 후보가 없습니다"));
    const c = st.pick ? ix.byId[st.pick] : null;
    const p = c && R && R.picks ? R.picks[c.id] : null;
    put(card, c ? ui.card({plate: `${LK.stratKo(c.name, meta)} · ${tfKo(c.tf)}`, sub: `${c.name} · ${c.exit_ko}`, cls: "rl-pickcard",
      acts: h("span", {class: "row wrap"}, LK.kindChip(c.kind), p ? h("span", {class: ["pp", "thin", p.best_ok ? "accent" : ""]}, p.best_ok ? "좋은 자리 가능" : "늘 보통 자리") : null)},
    p ? RK.pickRuleBody(p, R) : ui.none(R ? "이 후보의 규칙을 찾지 못했습니다" : "불러오는 중")) : null);
  }
  ctx.onLeague(paint);
  try {
    await RK.loadRules(ctx, (doc) => { R = doc; paint(); });
  } catch (e) {
    if (!ctx.alive()) return;
    put(rule, ui.errorBox(e, () => RK.loadRules(ctx, (doc) => { R = doc; paint(); })));
  }
  if (q.pick) {
    const t = document.getElementById("rl-pick");
    if (t && t.scrollIntoView) requestAnimationFrame(() => t.scrollIntoView({block: "start"}));
  }
}

/** One pick in the list: the timeframe, the name, the exit split in 익절 / 손절, the break-even, the leverage steps and
 *  what its 후보 account used. A button (keyboard too). */
export function pickRow(c, R, on, onPick) {
  const p = R && R.picks ? R.picks[c.id] : null;
  return h("button", {type: "button", class: ["rl-row", on ? "on" : ""], "aria-pressed": String(!!on), onclick: onPick,
    title: `${c.name} · ${c.id}`},
  h("span", {class: "rl-rn"}, h("span", {class: "an-tf"}, tfKo(c.tf)), h("b", null, LK.stratKo(c.name)), c.source && c.source.rank > 1 ? h("small", {class: "cl-code"}, `${c.source.rank}순위`) : null),
  h("span", {class: "rl-rx", dataset: {k: "익절"}}, p ? RK.tpShort(p.tp) : c.exit_ko),
  h("span", {class: "rl-rx", dataset: {k: "손절"}}, p ? `${fmt.num(p.stop_atr, p.stop_atr % 1 ? 1 : 0)} ATR` : "—"),
  h("span", {class: "rl-rx num", dataset: {k: "본전"}}, p && p.breakeven != null ? RK.share(p.breakeven, 0) : p && p.tp.kind === "roe" ? "배수따라" : "—"),
  h("span", {class: "rl-rx", dataset: {k: "배수"}}, p ? (p.best_ok ? "50→20배" : "30→20배") : "—"),
  h("span", {class: "rl-rx rl-ru", dataset: {k: "실제"}}, p ? RK.usedChips(((p.roles || {}).cand || {}).used) : "—"));
}

/** The owners' three questions answered from the data: the exits, the leverage, the start. */
export function answersBody(d, R) {
  const ix = LK.index(d);
  const n = ix.cands.length;
  const ex = {};
  for (const c of ix.cands) ex[c.exit_ko] = (ex[c.exit_ko] || 0) + 1;
  const tpCount = {};
  const stopCount = {};
  for (const c of ix.cands) {
    const [tp, sl] = String(c.exit_ko || "").split(" · ");
    tpCount[tp] = (tpCount[tp] || 0) + 1;
    stopCount[sl] = (stopCount[sl] || 0) + 1;
  }
  const list = (o) => Object.entries(o).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${k} ${fmt.int(v)}개`).join(" · ");
  const used = R && R.used_all ? R.used_all.cand || {} : null;
  const usedN = used ? Object.values(used).reduce((s, v) => s + v, 0) : 0;
  return h("dl", {class: "rl-qa"},
    h("div", null, h("dt", null, "익절·손절은 어떻게?"), h("dd", null,
      `후보 ${fmt.int(n)}개 모두 5년 탐색(84가지 청산 중)에서 각자 고른 `, h("b", null, "고정 익절"), "과 ", h("b", null, "ATR 손절"), "을 씁니다. 계단 잠금을 쓰는 후보는 없습니다. ",
      h("br"), h("span", {class: "muted"}, `익절: ${list(tpCount)}`), h("br"), h("span", {class: "muted"}, `손절: ${list(stopCount)}`),
      h("br"), "R = 진입가에서 손절까지의 거리. 3R 익절이면 손절 거리의 3배 가면 익절하고, 4번 중 1번만 이겨도 본전(비용 전)입니다. 기본값 계좌만 규칙봇의 지금 청산(계단 잠금 10%부터 · 손절 2 ATR)을 씁니다.")),
    h("div", null, h("dt", null, "배수(레버리지)는?"), h("dd", null,
      "규칙봇과 같은 규칙입니다. 좋은 자리(기존 36 매매법의 진입 강도 점수 상위)는 50배 → 40배, 보통 자리는 30배 → 20배 순서로 시도하고, ",
      "손절선이 청산가 안쪽에 1 ATR 이상 여유가 있고 손절 손실이 잔고의 15% 이하인 첫 배수로 들어갑니다. 증거금은 잔고의 배수% (30배면 30%). ",
      "손절이 넓을수록 배수가 내려가고, 어느 배수도 안 되면 들어가지 않습니다. 딥시크는 늘 보통 자리입니다.",
      used ? [h("br"), h("span", {class: "muted"}, usedN ? "후보 계좌가 지금까지 쓴 배수: " : "후보 계좌는 아직 닫힌 거래가 없습니다"), usedN ? RK.usedChips(used) : null] : null)),
    h("div", null, h("dt", null, "언제부터?"), h("dd", null,
      d.start_ms ? [h("b", null, `${LK.startKo(d)} KST`), " (설치한 때)부터입니다. 모든 계좌가 그때 $5,000으로 시작했고, 거래·잔고·날짜(시작한 날 = D+0)는 모두 그때부터 셉니다. ",
        `오늘은 D+${LK.dPlus(d, serverNow())} (${LK.calDay(d, serverNow())}일째)입니다.`] : "엔진이 첫 기록을 쓰면 나옵니다.")));
}

// #/custom 커스텀값: for every pick, what changed against the strategy's defaults (each parameter in Korean, the default,
// the custom value, the multiple), the exit (the pick's against the rule bot's live exit), where it came from (the
// study's rank, its test-period trades and, for core picks, its test mean and forward band), its character (trend ratio,
// win rates by market state on 2021-2026-09) and its five accounts now. Filters: 종류, 매매법, 봉.
// HONESTY: the study's numbers are the selection's own (chosen after seeing them): only the league's days after 09/30 can
// check them. Committed files carry no DeepSeek backtest money (its test mean is not in the repository).
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as LK from "../lk.js";
import {TFS, tfKo, STYLE_KO, STYLE_DESC} from "../labels.js";

const LIVE_EXIT_KO = "계단 잠금 10%부터 · 손절 2 ATR";
const STATE_ORDER = ["추세장", "횡보장", "급변장", "보통"];

/** The parameter table of a pick: Korean name, meaning kind, default, custom, multiple. */
export function paramTable(c, base, meta) {
  const sm = LK.stratMeta(c.name, meta);
  const params = sm ? sm.params : Object.keys(c.combo || {}).map((k) => ({name: k, ko: k, default: base && base.combo ? base.combo[k] : null}));
  const val = (v) => (Array.isArray(v) ? v.join(" / ") : v == null ? "—" : String(v));
  const edges = (LK.pickMeta(c.id, meta) || {}).edges || {};
  const edgeMark = (name) => (edges[name] ? h("span", {class: "pp thin warn cl-edge", title: edges[name] === "low"
    ? "5년 탐색에서 시도한 가장 작은 값입니다. 더 작은 값이 더 나았을 수도, 우연히 끝에 걸렸을 수도 있습니다"
    : "5년 탐색에서 시도한 가장 큰 값입니다. 더 큰 값이 더 나았을 수도, 우연히 끝에 걸렸을 수도 있습니다"},
  edges[name] === "low" ? "범위 끝 ↓" : "범위 끝 ↑") : null);
  return h("div", {class: "tbl-wrap"}, h("table", {class: "tbl cl-params"},
    h("thead", null, h("tr", null, ["조절 값", "기본값", "커스텀값", "배수"].map((t, i) => h("th", {class: i === 0 ? "l" : "", scope: "col"}, t)))),
    h("tbody", null, params.map((p) => {
      const dv = base && base.combo && p.name in base.combo ? base.combo[p.name] : p.default;
      const cv = c.combo ? c.combo[p.name] : null;
      const same = JSON.stringify(dv) === JSON.stringify(cv);
      const mult = typeof dv === "number" && typeof cv === "number" && dv !== 0 ? cv / dv : null;
      return h("tr", {class: same ? "cl-same" : "cl-changed"},
        h("td", {class: "l"}, h("b", null, p.ko), h("small", {class: "cl-code"}, p.name), edgeMark(p.name) ? [" ", edgeMark(p.name)] : null),
        h("td", {class: "num"}, val(dv)),
        h("td", {class: "num"}, h("b", {class: same ? "" : "accent"}, val(cv))),
        h("td", {class: "num"}, same ? h("span", {class: "muted"}, "그대로") : mult != null ? h("span", {class: mult > 1 ? "cl-up" : "cl-dn"}, `×${fmt.num(mult, 2)}`) : "바뀜"));
    }))),
  sm && sm.note ? h("p", {class: "note"}, sm.note) : null);
}

/** Where the pick came from and what kind of pick it is. */
export function originBox(c, meta) {
  const src = c.source || {};
  const pm = LK.pickMeta(c.id, meta) || {};
  const states = pm.states || {};
  return h("div", {class: "cl-origin"},
    h("dl", {class: "kv"},
      h("div", null, h("dt", null, "고른 곳"), h("dd", null, `5년 전체 탐색 · 그 칸 ${fmt.int(src.rank || 1)}순위 (통과 못 한 관찰용)`)),
      h("div", null, h("dt", null, "고르는 기간 거래"), h("dd", null, src.select_n != null ? `${fmt.int(src.select_n)}번` : "—")),
      h("div", null, h("dt", null, "시험 기간 거래"), h("dd", null, src.test_n != null ? `${fmt.int(src.test_n)}번` : "—")),
      h("div", null, h("dt", null, "시험 기간 한 번 평균"), h("dd", null, src.test_mean != null ? LK.ret(src.test_mean)
        : h("span", {class: "muted"}, c.kind === "ds" ? "저장소에 없음 (딥시크 백테스트 금액은 파일에 안 넣음)" : "—"))),
      src.band ? h("div", null, h("dt", null, "경고등 기준 (100번)"), h("dd", null, "하위 5% ", LK.ret(src.band["100"] && src.band["100"].p5))) : null,
      h("div", null, h("dt", null, "성격"), h("dd", null, LK.styleChip(pm.style), pm.trend_ratio != null ? h("span", {class: "muted"},
        ` 추세 비율 ${fmt.num(pm.trend_ratio, 2)} (${STYLE_DESC[pm.style] || ""})`) : null))),
    h("p", {class: "note cl-caveat"}, "위 백테스트 숫자는 이 후보를 고를 때 이미 본 기간의 것이라 실제보다 좋게 나옵니다. 맞는지는 후보 리그를 켠 뒤(설치한 때부터)의 성적으로만 확인합니다."),
    Object.keys(states).length ? h("div", {class: "cl-states"}, h("span", {class: "muted"}, "장세별 승률 (2021~2026-09, 고를 때 쓴 기간 포함, 참고): "),
      STATE_ORDER.filter((k) => states[k] && states[k].n).map((k) => h("span", {class: "pp thin", title: `${k} ${states[k].n}번${states[k].mean != null ? ` · 한 번 평균 ${LK.retTxt(states[k].mean)}` : ""}`},
        `${k} ${states[k].n ? fmt.pct(states[k].win * 100, false, 0) : "—"} (${fmt.int(states[k].n)}번)`))) : null);
}

export async function mount(el, ctx) {
  let meta = null;
  try { meta = await ctx.meta(); } catch (e) { /* codes */ }
  const q = ctx.params.query || {};
  const st = {kind: q.kind || "all", strat: q.s || "all", tf: q.tf || "all"};
  const save = () => ctx.setQuery(Object.fromEntries(Object.entries({kind: st.kind, s: st.strat, tf: st.tf}).filter(([, v]) => v !== "all")));
  const list = h("div", {class: "stack"});
  const stratSel = h("span");
  el.append(
    ui.screenHead("커스텀값", "후보마다 기본값에서 바뀐 숫자와 익절·손절 · 5년 탐색에서 고른 값"),
    h("div", {class: "dl-fields"},
      ui.field("종류", ui.seg([{id: "all", label: "전체"}, {id: "core", label: "기존 36"}, {id: "ds", label: "딥시크"}], st.kind, (v) => { st.kind = v; st.strat = "all"; save(); paint(); }, {label: "종류"})),
      ui.field("봉", ui.seg([{id: "all", label: "전체"}, ...TFS.map((t) => ({id: t, label: tfKo(t)}))], st.tf, (v) => { st.tf = v; save(); paint(); }, {label: "봉"})),
      ui.field("매매법", stratSel)),
    h("p", {class: "note"}, "기본값 = 규칙봇이 지금 쓰는 숫자. 커스텀값 = 5년 탐색(기본의 ⅓배~3배, 9단계)에서 고른 숫자. 색 글씨(커스텀값 칸)가 바뀐 값, 배수는 노랑 = 키움 · 파랑 = 줄임, '범위 끝' = 5년 탐색이 시도한 가장 작은(↓)·큰(↑) 값. ",
      "익절·손절도 후보마다 84가지 중에서 골랐고, 기본값 계좌는 지금 규칙봇 청산(", LIVE_EXIT_KO, ")을 씁니다."),
    list);

  function paint() {
    const d = LK.league();
    if (!d || !d.accounts) { put(list, ui.none("준비 중")); return; }
    const ix = LK.index(d);
    const names = [...new Set(ix.cands.filter((c) => st.kind === "all" || c.kind === st.kind).map((c) => c.name))]
      .sort((a, b) => LK.stratKo(a, meta).localeCompare(LK.stratKo(b, meta), "ko"));
    put(stratSel, ui.select([{id: "all", label: `전체 (${names.length}개)`}, ...names.map((n) => ({id: n, label: `${LK.stratKo(n, meta)} (${n})`}))],
      st.strat, (v) => { st.strat = v; save(); paint(); }, "매매법"));
    const picks = ix.cands.filter((c) => (st.kind === "all" || c.kind === st.kind) && (st.strat === "all" || c.name === st.strat)
      && (st.tf === "all" || c.tf === st.tf))
      .sort((a, b) => LK.stratKo(a.name, meta).localeCompare(LK.stratKo(b.name, meta), "ko") || TFS.indexOf(a.tf) - TFS.indexOf(b.tf));
    if (!picks.length) { put(list, ui.empty("맞는 후보가 없습니다")); return; }
    put(list, picks.map((c) => {
      const set = ix.sets[c.id];
      const pm = LK.pickMeta(c.id, meta) || {};
      const changed = Object.keys(c.combo || {}).filter((k) => set.base && set.base.combo && JSON.stringify(set.base.combo[k]) !== JSON.stringify(c.combo[k])).length;
      return ui.card({plate: `${LK.stratKo(c.name, meta)} · ${tfKo(c.tf)}`, sub: `${c.name} · 바뀐 값 ${changed}개`, cls: "cl-pickcard",
        acts: h("span", {class: "row wrap"}, LK.kindChip(c.kind), LK.styleChip(pm.style),
          h("a", {class: "btn-line", href: `#/entries?s=${encodeURIComponent(c.name)}`}, "진입 차트"),
          h("a", {class: "btn-line", href: `#/account/${encodeURIComponent(c.id)}`}, "계좌 자세히"))},
      h("div", {class: "cl-pickgrid"},
        h("div", {class: "stack tight"}, h("h3", {class: "cl-h3"}, "숫자"), paramTable(c, set.base, meta),
          h("h3", {class: "cl-h3"}, "익절 · 손절"),
          h("div", {class: "cl-exits"}, h("div", null, LK.roleChip("cand"), h("b", null, c.exit_ko)),
            h("div", null, LK.roleChip("base"), h("span", null, set.base ? set.base.exit_ko : LIVE_EXIT_KO)))),
        h("div", {class: "stack tight"}, h("h3", {class: "cl-h3"}, "어디서 왔나 · 성격"), originBox(c, meta),
          h("h3", {class: "cl-h3"}, "지금 계좌 5개"), LK.fiveRows(set),
          LK.pairedBox((((LK.league() || {}).watch || {}).picks || {})[c.id]?.paired, {hidden: LK.dsHidden(c)}))));
    }));
  }
  ctx.onLeague(paint);
}

export {STYLE_KO};

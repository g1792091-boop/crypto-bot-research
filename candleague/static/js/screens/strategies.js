// #/strategies 매매법: the 16 strategies of the watch list, one card each: the Korean name and family, the entry rule
// (long / short, from docs/aibot/STRATEGY_CATALOG_KO.md), the adjustable numbers with their meanings and defaults, its
// picks (timeframe, character, exit) and its pooled league numbers (WATCH_PREREG 3.5: all of its picks' trades, against
// its own 기본값 and 동전 accounts). ?s=<name> scrolls to one. Data: /api/meta + the shared snapshot.
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as LK from "../lk.js";
import {TFS, tfKo} from "../labels.js";

export async function mount(el, ctx) {
  let meta = null;
  try { meta = await ctx.meta(); } catch (e) { /* codes */ }
  const q = ctx.params.query || {};
  const st = {kind: q.kind || "all"};
  const list = h("div", {class: "stack"});
  el.append(
    ui.screenHead("매매법", "후보 리그의 매매법 16개: 어떻게 들어가나, 무엇을 조절하나, 지금 묶음 성적"),
    h("div", {class: "dl-fields"}, ui.field("종류", ui.seg([{id: "all", label: "전체"}, {id: "core", label: "기존 36 (8개)"}, {id: "ds", label: "딥시크 (8개)"}],
      st.kind, (v) => { st.kind = v; ctx.setQuery(v === "all" ? {} : {kind: v}); paint(); }, {label: "종류"}))),
    list);
  let scrolled = false;
  function paint() {
    const d = LK.league();
    const ix = d && d.accounts ? LK.index(d) : {cands: [], sets: {}};
    const ws = (d && d.watch && d.watch.strategies) || {};
    const names = Object.keys((meta && meta.strategies) || {}).filter((n) => st.kind === "all" || meta.strategies[n].kind === st.kind)
      .sort((a, b) => (meta.strategies[a].kind === meta.strategies[b].kind ? meta.strategies[a].ko.localeCompare(meta.strategies[b].ko, "ko")
        : meta.strategies[a].kind === "core" ? -1 : 1));
    if (!names.length) { put(list, ui.none("매매법 자료 준비 중")); return; }
    put(list, names.map((n) => {
      const sm = meta.strategies[n];
      const picks = ix.cands.filter((c) => c.name === n).sort((a, b) => TFS.indexOf(a.tf) - TFS.indexOf(b.tf));
      const w = ws[n];
      return ui.card({plate: sm.ko, sub: `${n} · ${sm.family}`, id: `s-${n}`, cls: "cl-stratcard",
        acts: h("span", {class: "row wrap"}, LK.kindChip(sm.kind), h("a", {class: "btn-line", href: `#/custom?s=${encodeURIComponent(n)}`}, "커스텀값 보기"),
          h("a", {class: "btn-line", href: `#/entries?s=${encodeURIComponent(n)}`}, "진입 차트"),
          h("a", {class: "btn-line", href: `#/rules?s=${encodeURIComponent(n)}`}, "익절·손절·배수"))},
      h("div", {class: "cl-pickgrid"},
        h("div", {class: "stack tight"},
          h("h3", {class: "cl-h3"}, "어떻게 들어가나"),
          h("dl", {class: "kv cl-entry"}, h("div", null, h("dt", null, h("span", {class: "side long"}, "롱")), h("dd", null, sm.long)),
            h("div", null, h("dt", null, h("span", {class: "side short"}, "숏")), h("dd", null, sm.short))),
          sm.note ? h("p", {class: "note"}, sm.note) : null,
          h("h3", {class: "cl-h3"}, "조절하는 숫자 (기본값)"),
          h("ul", {class: "cl-plist"}, sm.params.map((p) => h("li", null, h("b", null, p.ko), h("span", {class: "muted"}, ` · ${p.kind_ko} · 기본 `),
            h("span", {class: "num"}, Array.isArray(p.default) ? p.default.join("/") : String(p.default)), h("small", {class: "cl-code"}, p.name))))),
        h("div", {class: "stack tight"},
          h("h3", {class: "cl-h3"}, `후보 ${picks.length}개`, h("small", {class: "muted"}, " · 봉 · 성격 · 익절·손절 · 거래 · 한 번 평균")),
          picks.length ? h("div", {class: "cl-plist2"}, picks.map((c) => {
            const pm = LK.pickMeta(c.id, meta) || {};
            return h("a", {class: "cl-pickrow", href: `#/account/${encodeURIComponent(c.id)}`},
              h("span", {class: "an-tf"}, tfKo(c.tf)), LK.styleChip(pm.style), h("span", {class: "cl-exit"}, c.exit_ko),
              h("span", {class: "grow"}), h("span", {class: "num muted"}, `${fmt.int(c.trades)}번`), LK.ret(c.mean_ret, {hiddenIf: LK.dsHidden(c)}));
          })) : ui.empty("후보 없음"),
          h("h3", {class: "cl-h3"}, "지금 묶음 성적 (이 매매법 후보 모두)"),
          w ? h("div", {class: "stack tight"},
            h("div", {class: "stats cl-stats3"},
              ui.stat("후보 거래", `${fmt.int(w.n)}번`, w.n ? `승률 ${fmt.pct((100 * w.wins) / w.n, false, 0)}` : "아직 없음"),
              ui.stat("한 번 평균", w.mean != null ? LK.ret(w.mean) : sm.kind === "ds" && w.n ? "숨김" : "—", "지갑 대비"),
              ui.stat("기본값 · 동전", w.base_mean != null ? h("span", null, LK.ret(w.base_mean), " · ", LK.ret(w.flip_mean))
                : sm.kind === "ds" && w.base_n && !(LK.league() || {}).ds_money ? "숨김" : "—",
                `기본값 ${fmt.int(w.base_n)}번 · 동전 ${fmt.int(w.flip_n)}번`)),
            h("div", {class: "row wrap cl-marks"}, LK.vsMark(w.positive, "0보다"), LK.vsMark(w.beats_base, "기본값보다"), LK.vsMark(w.beats_flip, "동전보다")))
            : ui.none("준비 중"))));
    }));
    if (!scrolled && q.s) {
      scrolled = true;
      const t = document.getElementById(`s-${q.s}`);
      if (t) requestAnimationFrame(() => t.scrollIntoView({block: "start"}));
    }
  }
  ctx.onLeague(paint);
  if (!LK.league()) paint();
}

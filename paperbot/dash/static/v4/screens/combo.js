// 조합 성과 (#/combo/<tab>?u=..&w=..&p=..): "매매법끼리 합쳤을 때 성과가 어떻게 되나" from the paper v4 records
// (dash/more/combo.py, read-only). Four tabs:
//   내 조합 만들기 build  pick 2-8 units (a strategy = its 4 timeframe accounts summed, or one strategy@timeframe
//                         account), a weighting, and see the combined curve, its numbers, each member's part and what the
//                         combination would be without it, the correlation inside it, 'same bet' pairs, the
//                         diversification ratio (combo-build.js). The pick lives in the address (a link opens the same
//                         combination) and is remembered per device.
//   전체 상관 지도 map    the 36 x 36 daily correlation, the together / opposite pairs, the 계좌 겹침 table (combo-map.js)
//   합친 규칙 실험 rules  merged rules measured as one rule on recorded entries (combo-rules.js)
//   5년 기준 y5          the 5-year backtest view of another builder (./combo-5y.js, render5y(ctx, el)); until that file
//                         exists: '5년 백테스트 결과 준비 중'
// HONESTY: descriptive only ('설명용, 판정 아님'); DeepSeek is not in it (one line says why: its money only on its own
// group screens); coin-flip lines are 참고 with refNote; small samples say "거래 N건 · 아직 판단하기 이릅니다".
import {h, put, ui, motion, local} from "../core/pb.js";
import {buildTab} from "./combo-build.js";
import {mapTab} from "./combo-map.js";
import {rulesTab} from "./combo-rules.js";

const TABS = [
  {id: "build", label: "내 조합 만들기", desc: "매매법이나 봉 계좌를 2~8개 골라 같이 돌렸다면의 곡선과 숫자"},
  {id: "map", label: "전체 상관 지도", desc: "36개 매매법이 하루하루 같이 움직였나, 반대로 움직였나"},
  {id: "rules", label: "합친 규칙 실험", desc: "두 매매법이 같이 신호 줄 때만 들어갔다면 (기록된 진입으로 계산한 근사)"},
  {id: "y5", label: "5년 기준", desc: "같은 조합을 5년 과거 시험 기록으로 보면"},
];
const okTab = (t) => (TABS.some((x) => x.id === t) ? t : "build");
const DS_LINE = "딥시크 171개 계좌는 돈 숫자를 딥시크 묶음 화면에서만 보여 드리기로 해서(D10·D11) 조합에 넣지 않습니다.";
let current = null;

export async function mount(el, ctx) {
  ctx.setTitle("조합 성과");
  const st = {tab: okTab(ctx.params.arg || local.get("combo-tab", "build")), view: null, gen: 0};
  const segSlot = h("div", {class: "cb-tabs"});
  const desc = h("p", {class: "cb-desc"});
  const body = h("div", {class: "stack cb-body"});
  el.append(ui.screenHead("조합 성과", "매매법끼리 합쳤을 때 성과가 어떻게 되나 · 모의 기록 · 설명용, 판정 아님"),
    h("p", {class: "cb-dsline"}, ui.pill("딥시크 제외", "ref"), " ", DS_LINE), segSlot, desc, body);
  ctx.store.need("summary", 120000).catch(() => null);      // the verdict time for refNote

  const env = {
    ctx,
    query: () => (ctx.params && ctx.params.query) || {},
    /** Put the state in the address without a new history entry (a link to it opens the same view). */
    setQuery(q) {
      const clean = Object.fromEntries(Object.entries(q || {}).filter(([, v]) => v != null && v !== ""));
      ctx.params = {...ctx.params, name: "combo", arg: st.tab, query: clean};
      try { window.history.replaceState(null, "", ctx.href("combo", st.tab, clean)); } catch { /* keep the hash */ }
    },
    go: (tab, q) => ctx.go("combo", tab, q),
  };

  function renderSeg() {
    put(segSlot, ui.seg(TABS.map((t) => ({id: t.id, label: t.label})), st.tab, (id) => show(id, null), {label: "조합 성과 보기", scroll: true}));
  }

  async function show(tab, query) {
    tab = okTab(tab);
    const g = ++st.gen;
    if (st.view && st.view.dispose) { try { st.view.dispose(); } catch (e) { console.error(e); } }
    st.view = null;
    st.tab = tab;
    local.set("combo-tab", tab);
    renderSeg();
    const t = TABS.find((x) => x.id === tab);
    desc.textContent = t.desc;
    if (query) ctx.params = {...ctx.params, arg: tab, query};
    else env.setQuery(tab === "build" ? pickQuery() : {});
    put(body, motion.shimmer(4, true));
    if (tab === "y5") { await five(g); return; }
    const make = tab === "map" ? mapTab : tab === "rules" ? rulesTab : buildTab;
    let view;
    try { view = make(env); } catch (e) {
      console.error(e);
      put(body, ui.card({plate: t.label}, ui.errorBox(e, () => show(tab, null))));
      return;
    }
    if (g !== st.gen) { if (view.dispose) view.dispose(); return; }
    st.view = view;
    put(body, view.el);
    motion.swap(body);
  }

  // the build tab's last pick (per device) when the address has none
  function pickQuery() {
    const last = local.get("combo-pick", null);
    return last && last.u ? {u: last.u, w: last.w, p: last.p} : {};
  }

  // 5년 기준: another builder's module (./combo-5y.js exports render5y(ctx, el)); missing until that build lands
  async function five(g) {
    const slot = h("div", {class: "stack cb-5y"});
    let mod = null;
    try { mod = await import("./combo-5y.js"); } catch { mod = null; }
    if (g !== st.gen || !ctx.alive()) return;
    put(body, slot);
    if (mod && typeof mod.render5y === "function") {
      try { await mod.render5y(ctx, slot); motion.swap(body); return; } catch (e) { console.error(e); }
    }
    put(slot, ui.card({plate: "5년 기준", cls: "cb-5y-wait"},
      h("p", {class: "cb-5y-t"}, "5년 백테스트 결과 준비 중"),
      h("p", {class: "muted"}, "같은 조합을 5년 과거 시험 기록으로 계산한 화면이 이 자리에 들어옵니다. 지금 모의 기록으로 본 조합은 '내 조합 만들기'에 있습니다."),
      h("div", {class: "cb-acts"}, h("button", {class: "btn-line", type: "button", onclick: () => show("build", null)}, "내 조합 만들기로"))));
    motion.swap(body);
  }

  current = {
    update(params) {
      const tab = okTab(params.arg || st.tab);
      if (tab !== st.tab || !st.view || !st.view.update) { show(tab, params.query || {}); return; }
      ctx.params = {...ctx.params, ...params};
      st.view.update(params.query || {});
    },
    dispose() { if (st.view && st.view.dispose) st.view.dispose(); },
  };
  await show(st.tab, ctx.params.arg ? ctx.params.query || {} : null);
}

export function update(params) { if (current) current.update(params); }
export function unmount() { if (current) current.dispose(); current = null; }

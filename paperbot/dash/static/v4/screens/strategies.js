// 매매법 (builder C, CONTRACT.md section 4, INVENTORY section 5). #/strategies[?g=core|ds|m5] is the browser (기존 36 /
// 딥시크 44 by family / 5분봉), #/strategies/<name>[?tf=1h&sym=BTCUSDT] one strategy (strategies-detail.js). update()
// switches between them in place. Data: the shared board (store), /api/strategies (the 36's styles), the summary
// (first verdict date for the 참고 note); the detail fetches its own chart, accounts' trades, signals, profile, cards.
import {h, put, ui, derive, motion} from "../core/pb.js";
import {listView} from "./strategies-list.js";
import {detailView} from "./strategies-detail.js";
import {nameKo} from "./strategies-calc.js";

let current = null;

export async function mount(el, ctx) {
  ctx.setTitle("매매법");
  const st = {board: null, gs: null, list36: [], summary: null};
  const head = ui.screenHead("매매법", "어떤 규칙으로 사고파는지, 지금 어떻게 되고 있는지");
  const slot = h("div", {class: "strat-slot"});
  el.append(head, slot);
  let view = null, list = null, shownArg;

  function show(params, animate) {
    const arg = params.arg || null;
    if (arg === shownArg && view) {
      if (!arg && list) list.setGroup((params.query || {}).g, (params.query || {}).fam);
      return;
    }
    shownArg = arg;
    if (view && view !== list) view.dispose();
    if (!arg) {
      head.hidden = false;
      if (!list) { list = listView(ctx, st); list.set(); } else { list.setGroup((params.query || {}).g, (params.query || {}).fam); list.refresh(); }
      view = list;
      ctx.setTitle("매매법");
    } else {
      head.hidden = true;
      view = detailView(ctx, st, arg);
      ctx.setTitle(nameKo(arg, st.list36));
    }
    put(slot, view.el);
    if (view.start) view.start();
    window.scrollTo(0, 0);
    if (animate) motion.swap(slot);
  }
  current = (params) => show(params, true);
  ctx.track(() => { if (view && view !== list) view.dispose(); current = null; });

  const [b0, l0, s0] = await Promise.all([ctx.store.need("board", 60000).catch((e) => e),
    ctx.api("/api/strategies").catch(() => []), ctx.store.need("summary", 60000).catch(() => null)]);
  if (!ctx.alive()) return;
  if (b0 instanceof Error) { el.append(ui.errorBox(b0, () => ctx.store.refresh("board").catch(() => {}))); return; }
  st.board = b0; st.gs = derive.groupStats(b0); st.list36 = Array.isArray(l0) ? l0 : []; st.summary = s0;
  show(ctx.params, false);
  ctx.watch("board", (b) => {
    if (!b || b === st.board) return;
    st.board = b; st.gs = derive.groupStats(b);
    if (view && view.refresh) view.refresh();
  });
  ctx.watch("summary", (s) => { if (s) st.summary = s; });
}

export function update(params) { if (current) current(params); }

export function unmount() { current = null; }

// #/livebots[/<tab>] — 실거래 (owners 10/19, the live start day: 바이비트 $100 + MEXC $100). The two live order executors
// (real money) and the paper account both follow (A+C 합본, COMBO@mix), read-only: dash/more/livebots.py reads the paper
// bot's database, both executors' databases and their configs (never the key file).
//   요약   the 실거래 터미널 (screens/livebots-term.js: the rule bot's terminal frame and parts, fed with the live records)
//   차트   the open positions on the price chart, big, with their lines in words (screens/livebots-chart.js)
//   거래   the closed trades of each account, 10 a page, one opened in place (screens/livebots-trades.js, its own endpoint)
//   신호   "왜 안 들어갔지?": the combined bot's signals and what became of each (screens/livebots-signals.js)
//   성적   rolling 20 / 40 win share, the 40-trade checkpoint, breakdowns, the coin-flip twin (screens/livebots-perf.js)
// Each tab is its own mount: a tab change re-mounts the screen (no update()), so every timer, stream listener and chart of
// the tab before is disposed by the router (ctx), never left running behind another tab.
// HONESTY: a file or table that is not there yet = 수집 전; one that cannot be read = 못 읽음 + why, never a zero; a refresh
// that fails keeps the last answer on screen, dimmed, with its age (ui.staleNote); nothing here changes anything (no order
// buttons, only view switches).
import {h, put, ui, serverNow} from "../core/pb.js";
import {termView} from "./livebots-term.js";
import {chartView} from "./livebots-chart.js";
import {tradesView} from "./livebots-trades.js";
import {signalsView} from "./livebots-signals.js";
import {perfView} from "./livebots-perf.js";

export const API = "/api/v4/livebots";
const REFRESH_MS = 5 * 1000;               // the server caches 5 s; the executors write every loop, the paper every minute
export const TABS = [
  {id: "summary", label: "요약", make: (ctx, hub) => termView(ctx, hub)},
  {id: "chart", label: "차트", make: (ctx, hub) => chartView(ctx, hub)},
  {id: "trades", label: "거래", make: (ctx) => tradesView(ctx), own: true},
  {id: "signals", label: "신호", make: (ctx) => signalsView(ctx), own: true},
  {id: "perf", label: "성적", make: (ctx) => perfView(ctx), own: true},
];
const tabOf = (arg) => (TABS.some((t) => t.id === arg) ? arg : "summary");

export async function mount(el, ctx) {
  ctx.setTitle("실거래");
  const st = {tab: tabOf(ctx.params.arg), d: null, state: "loading", okAt: 0, busy: false};
  const seg = ui.seg(TABS.map((t) => ({id: t.id, label: t.label})), st.tab, (id) => { if (id !== st.tab) ctx.go("livebots", id); },
    {label: "실거래 보기", scroll: true});
  const head = h("div", {class: "lb-head"},
    h("h1", null, "실거래"), h("span", {class: "sub"}, "바이비트 · MEXC 실행기와 그 둘이 따라가는 페이퍼 · 보기만 하는 화면 (주문 버튼 없음)"), seg);
  const staleSlot = h("div", {class: "lb-slot"});
  const body = h("div", {class: "lb-body"});
  el.classList.add("lb-scr", "lb-tab-" + st.tab);
  el.append(head, staleSlot, body);

  const hub = {state: () => st.state, at: () => st.okAt, retry: () => load().catch(() => {}), get: () => st.d};
  const view = TABS.find((t) => t.id === st.tab).make(ctx, hub);
  put(body, view.el);

  async function load() {
    if (st.busy) return;
    st.busy = true;
    let d;
    try { d = await ctx.api(API); }
    catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      // a refresh that fails after a good answer keeps the page, dimmed, and says how old it is (never silently stale)
      st.state = "failed";
      if (st.d) { put(staleSlot, ui.staleNote(e, st.okAt, () => load())); ui.dim(body, true); }
      else put(staleSlot, ui.errorBox(e, () => load()));
      view.set(null, "failed");
      throw e;
    } finally { st.busy = false; }
    if (!ctx.alive()) return;
    put(staleSlot);
    ui.dim(body, false);
    st.d = d; st.state = "ok"; st.okAt = serverNow();
    view.set(d, "ok");
  }
  if (TABS.find((t) => t.id === st.tab).own) return;      // (this tab reads its own endpoint)
  try { await load(); } catch (e) { /* the box and the parts say so; the poll asks again */ }
  ctx.every(REFRESH_MS, () => load().catch(() => {}), {now: false});
}

export function unmount() {}

// #/livebots[/<tab>] — 실거래 (owners 10/19, the live start day: 바이비트 $100 + MEXC $100). The two live order executors
// (real money) and the paper account both follow (A+C 합본, COMBO@mix), read-only: dash/more/livebots.py reads the paper
// bot's database, both executors' databases and their configs (never the key file).
//   요약   the 실거래 터미널 (screens/livebots-term.js: the rule bot's terminal frame and parts, fed with the live records)
//   차트   the open positions on the price chart, big, with their lines in words (screens/livebots-chart.js)
//   거래   the closed trades of each account, 10 a page, one opened in place (screens/livebots-trades.js, its own endpoint)
//   신호   "왜 안 들어갔지?": the combined bot's signals and what became of each (screens/livebots-signals.js)
//   성적   rolling 20 / 40 win share, the 40-trade checkpoint, breakdowns, the coin-flip twin (screens/livebots-perf.js)
//   안전   per executor: halt, the limits its config has, the kill file, the light and its history, the WARN / CRITICAL log
//   그림자 the shadow paper bots next to the live paper bot from the same start; 설정: the fixed rules and every setting
// Each tab is its own mount: a tab change re-mounts the screen (no update()), so every timer, stream listener and chart of
// the tab before is disposed by the router (ctx), never left running behind another tab.
// HONESTY: a file or table that is not there yet = 수집 전; one that cannot be read = 못 읽음 + why, never a zero; a refresh
// that fails keeps the last answer on screen, dimmed, with its age (ui.staleNote); nothing here changes anything (no order
// buttons, only view switches).
import {h, put, ui, serverNow, sound} from "../core/pb.js";
import {liveEvents} from "./livebots-calc.js";
import {realLine} from "./livebots-kit.js";
import {termView} from "./livebots-term.js";
import {chartView} from "./livebots-chart.js";
import {tradesView} from "./livebots-trades.js";
import {signalsView} from "./livebots-signals.js";
import {perfView} from "./livebots-perf.js";
import {safetyView} from "./livebots-safety.js";
import {shadowsView, settingsView} from "./livebots-more.js";

export const API = "/api/v4/livebots";
const REFRESH_MS = 5 * 1000;               // the server caches 5 s; the executors write every loop, the paper every minute
export const TABS = [
  {id: "summary", label: "요약", make: (ctx, hub) => termView(ctx, hub)},
  {id: "chart", label: "차트", make: (ctx, hub) => chartView(ctx, hub)},
  {id: "trades", label: "거래", make: (ctx) => tradesView(ctx), own: true},
  {id: "signals", label: "신호", make: (ctx) => signalsView(ctx), own: true},
  {id: "perf", label: "성적", make: (ctx) => perfView(ctx), own: true},
  {id: "safety", label: "안전", make: (ctx) => safetyView(ctx), own: true},
  {id: "shadows", label: "그림자", make: (ctx) => shadowsView(ctx), own: true},
  {id: "settings", label: "설정", make: (ctx) => settingsView(ctx), own: true},
];
const tabOf = (arg) => (TABS.some((t) => t.id === arg) ? arg : "summary");
// what the page already heard (module level: a tab change re-mounts the screen, the same record must not sound again);
// seen null = the next answer is the baseline (the first look, and the first look after the page was hidden)
const heard = {state: null};

export async function mount(el, ctx) {
  ctx.setTitle("실거래");
  const st = {tab: tabOf(ctx.params.arg), d: null, state: "loading", okAt: 0, busy: false};
  const seg = ui.seg(TABS.map((t) => ({id: t.id, label: t.label})), st.tab, (id) => { if (id !== st.tab) ctx.go("livebots", id); },
    {label: "실거래 보기", scroll: true});
  // the real-money strip on every tab (owners 10/19: never taken for the rule bot's paper screens), from the summary answer
  const real = h("div", {class: "lb-real", role: "note", "aria-label": "진짜 돈 화면"}, realLine(null));
  const head = h("div", {class: "lb-head"},
    h("h1", null, "실거래"), h("span", {class: "sub"}, "바이비트 · MEXC 실행기와 그 둘이 따라가는 페이퍼(연습)"), seg);
  const staleSlot = h("div", {class: "lb-slot"});
  const body = h("div", {class: "lb-body"});
  el.classList.add("lb-scr", "lb-tab-" + st.tab);
  el.append(real, head, staleSlot, body);

  const hub = {state: () => st.state, at: () => st.okAt, retry: () => load().catch(() => {}), get: () => st.d};
  const view = TABS.find((t) => t.id === st.tab).make(ctx, hub);
  const own = !!TABS.find((t) => t.id === st.tab).own;
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
      if (own) { /* a tab with its own endpoint says its own failures; the summary poll only feeds the sounds here */ }
      else if (st.d) { put(staleSlot, ui.staleNote(e, st.okAt, () => load())); ui.dim(body, true); }
      else put(staleSlot, ui.errorBox(e, () => load()));
      if (view.set) view.set(null, "failed");
      throw e;
    } finally { st.busy = false; }
    if (!ctx.alive()) return;
    put(staleSlot);
    ui.dim(body, false);
    st.d = d; st.state = "ok"; st.okAt = serverNow();
    put(real, realLine(d));
    view.set(d, "ok");
    // 소리 · 빛: only what really arrived since the last answer (core/sound.js playLive; its gate, cooldown and switches)
    const ev = liveEvents(heard.state, d, serverNow());
    heard.state = ev.state;
    if (ev.names.length) sound.playLive(ev.names);
    if (ev.alarms.length && view.alarm) view.alarm(ev.alarms);
  }
  ctx.listen(document, "visibilitychange", () => { if (!document.hidden && heard.state) heard.state = {...heard.state, seen: null}; });
  // every tab reads the summary too (5 s, cached by the server): the sounds and the alarms follow the live bots on every tab
  try { await load(); } catch (e) { /* the box and the parts say so; the poll asks again */ }
  ctx.every(REFRESH_MS, () => load().catch(() => {}), {now: false});
}

export function unmount() {}

// 실거래 (owners 10/19, the live start day: 바이비트 $100 + MEXC $100). The two live order executors (real money) and the
// paper account both follow (COMBO@mix), read-only: dash/more/livebots.py reads the paper bot's database, both executors'
// databases and their configs (never the key file).
// Where it lives (owners 10/19 "대시보드가 지금 규칙봇 안에 있잖아 제거하고 따로 실거래용 봇 대시보드 사이트를 따로"): the
// separate 실거래 site (paperbot/livedash, port 8093, core/site.js LIVE), where every tab below is a menu item (#/<tab>,
// core/routes.js LIVE_SCREENS: 지금 · 기록 · 성적 · 운영) and the head shows the tabs of the item's group. On the rule bot's
// dashboard (port 8080) #/livebots only says where it moved, with the link built from this very host.
//   관제   the control room (screens/livebots-hq.js, owners 10/19 "간지나게"): the two real wallets, the open position's gauge,
//          "왜 지금 진입 안 하나", the day's pause dial, the light rings and the strategies at work, at a glance
//   포지션 each account's open position as a Binance-style card: 진입가 · 손절가 · 익절가 (the next ladder step) and the whole
//          ladder, 최대 +% / 최대 −% since the entry, the fast-stop state, the paper-vs-live entry gap (screens/livebots-pos.js,
//          /api/v4/livebots/positions)
//   요약   the 실거래 터미널 (screens/livebots-term.js: the rule bot's terminal frame and parts, fed with the live records)
//   차트   the open positions on the price chart, big, with their lines in words (screens/livebots-chart.js)
//   위험 · 봇 상태 · 목표 · 규칙 점검   part B's tabs (screens/livebots-risk.js, livebots-health.js, livebots-goal.js,
//          livebots-judge.js; their routes in dash/more/liveinsight.py)
//   거래  the closed trades of each account, 10 a page, one opened in place, 최대 +% / 최대 −% per trade
//          (screens/livebots-trades.js, its own endpoint and /api/v4/livebots/positions/excursions)
//   다시보기 one closed trade replayed on its 1m bars (screens/livebots-replay.js)
//   신호   "왜 안 들어갔지?": the combined bot's signals and what became of each (screens/livebots-signals.js)
//   못 탄 신호 the virtual results of the signals the bot did not take (screens/livebots-missed.js)
//   성적   rolling 20 / 40 win share, the 40-trade checkpoint, breakdowns, the coin-flip twin (screens/livebots-perf.js)
//   순위   매매법 순위표: the strategies as cards and a list (screens/livebots-rank.js, /api/v4/livebots/rank)
//   지도   기대 범위 띠 and the record by regime, coin, KST block and side next to 5 years (screens/livebots-map.js)
//   비용   how far the live trades fall behind the paper trades they followed, and the ones not followed (livebots-cost.js)
//   일정   US macro releases and the weekend: when the bots pause, whether an entry may be made now (livebots-cal.js)
//   안전   per executor: halt, the limits its config has, the kill file, the WARN / CRITICAL log
//   설정   the fixed rules and every setting; 분석팀 the 실거래 분석 팀 (screens/livebots-team.js); 그림자 the shadow paper bots
// Each tab is its own mount: a tab change re-mounts the screen (no update()), so every timer, stream listener and chart of
// the tab before is disposed by the router (ctx), never left running behind another tab.
// HONESTY: a file or table that is not there yet = 수집 전; one that cannot be read = 못 읽음 + why, never a zero; a refresh
// that fails keeps the last answer on screen, dimmed, with its age (ui.staleNote); nothing here changes anything (no order
// buttons, only view switches).
import {h, put, ui, serverNow, sound, LIVE, LIVE_PORT, siteUrl, GROUPS} from "../core/pb.js";
import {liveEvents} from "./livebots-calc.js";
import {realLine, setPapers} from "./livebots-kit.js";
import {termView} from "./livebots-term.js";
import {chartView} from "./livebots-chart.js";
import {tradesView} from "./livebots-trades.js";
import {signalsView} from "./livebots-signals.js";
import {perfView} from "./livebots-perf.js";
import {safetyView} from "./livebots-safety.js";
import {shadowsView, settingsView} from "./livebots-more.js";
import {hqView} from "./livebots-hq.js";
import {rankView} from "./livebots-rank.js";
import {mapView} from "./livebots-map.js";
import {costView} from "./livebots-cost.js";
import {calView} from "./livebots-cal.js";
import {teamView} from "./livebots-team.js";
import {missedView} from "./livebots-missed.js";
import {replayView} from "./livebots-replay.js";
import {posView} from "./livebots-pos.js";
import {riskView} from "./livebots-risk.js";
import {healthView} from "./livebots-health.js";
import {goalView} from "./livebots-goal.js";
import {judgeView} from "./livebots-judge.js";

export const API = "/api/v4/livebots";
const REFRESH_MS = 5 * 1000;               // the server caches 5 s; the executors write every loop, the paper every minute
// in the 실거래 site's menu order (core/routes.js LIVE_GROUPS: 지금 · 기록 · 성적 · 운영)
export const TABS = [
  {id: "hq", label: "관제", make: (ctx, hub) => hqView(ctx, hub)},
  {id: "pos", label: "포지션", make: (ctx, hub) => posView(ctx, hub), own: true},
  {id: "summary", label: "요약", make: (ctx, hub) => termView(ctx, hub)},
  {id: "chart", label: "차트", make: (ctx, hub) => chartView(ctx, hub)},
  {id: "risk", label: "위험", make: (ctx) => riskView(ctx), own: true},
  {id: "health", label: "봇 상태", make: (ctx) => healthView(ctx), own: true},
  {id: "trades", label: "거래", make: (ctx) => tradesView(ctx), own: true},
  {id: "replay", label: "다시보기", make: (ctx) => replayView(ctx), own: true},
  {id: "signals", label: "신호", make: (ctx) => signalsView(ctx), own: true},
  {id: "missed", label: "못 탄 신호", make: (ctx) => missedView(ctx), own: true},
  {id: "perf", label: "성적", make: (ctx) => perfView(ctx), own: true},
  {id: "goal", label: "목표", make: (ctx) => goalView(ctx), own: true},
  {id: "rank", label: "순위", make: (ctx) => rankView(ctx), own: true},
  {id: "judge", label: "규칙 점검", make: (ctx) => judgeView(ctx), own: true},
  {id: "map", label: "지도", make: (ctx) => mapView(ctx), own: true},
  {id: "cost", label: "비용", make: (ctx) => costView(ctx), own: true},
  {id: "cal", label: "일정", make: (ctx) => calView(ctx), own: true},
  {id: "safety", label: "안전", make: (ctx) => safetyView(ctx), own: true},
  {id: "settings", label: "설정", make: (ctx) => settingsView(ctx), own: true},
  {id: "team", label: "분석팀", make: (ctx) => teamView(ctx), own: true},
  {id: "shadows", label: "그림자", make: (ctx) => shadowsView(ctx), own: true},
];
const tabOf = (arg) => (TABS.some((t) => t.id === arg) ? arg : "hq");
// what the page already heard (module level: a tab change re-mounts the screen, the same record must not sound again);
// seen null = the next answer is the baseline (the first look, and the first look after the page was hidden)
const heard = {state: null};

/** The rule bot's dashboard (port 8080): the 실거래 screens moved to their own site; this card says where (the link is
 *  this same host on the 실거래 port, the tab kept), nothing else is read or polled here. */
function movedCard(ctx) {
  const tab = ctx.params.arg && TABS.some((t) => t.id === ctx.params.arg) ? ctx.params.arg : "";
  const url = siteUrl(LIVE_PORT, tab ? `#/${tab}` : "");
  return ui.card({title: "실거래 화면은 따로 옮겼어요", cls: "lb-moved"},
    h("p", {class: "lb-moved-p"}, "바이비트 · MEXC 실거래 봇과 그 둘이 따라가는 페이퍼(연습) 화면은 이제 따로 된 실거래 사이트에서 봐요. 같은 비밀번호로 들어가요."),
    url ? h("a", {class: "btn-line lb-moved-a", href: url}, `${url} →`) : h("p", {class: "note"}, `같은 서버 주소의 ${LIVE_PORT} 포트로 들어가세요`),
    ui.note("이 규칙봇(모의) 대시보드에는 실거래 메뉴가 없어요 · 실거래 사이트는 보기만 해요 (주문 버튼 없음)"));
}

export async function mount(el, ctx) {
  if (!LIVE) {
    ctx.setTitle("실거래 (옮김)");
    el.append(movedCard(ctx));
    return;
  }
  const st = {tab: tabOf(ctx.params.arg), d: null, state: "loading", okAt: 0, busy: false};
  const tab = TABS.find((t) => t.id === st.tab);
  ctx.setTitle(tab.label);
  // the head's tabs: the tabs of this item's menu group (the site's menu lists them all), each a link to its own item
  const group = GROUPS.find((g) => g.screens.includes(st.tab));
  const mine = TABS.filter((t) => !group || group.screens.includes(t.id));
  const seg = ui.seg(mine.map((t) => ({id: t.id, label: t.label})), st.tab, (id) => { if (id !== st.tab) ctx.go("livebots", id); },
    {label: group ? `${group.ko} 보기` : "실거래 보기", scroll: true});
  // the real-money strip on every tab (owners 10/19: never taken for the rule bot's paper screens), from the summary answer
  const real = h("div", {class: "lb-real", role: "note", "aria-label": "진짜 돈 화면"}, realLine(null));
  const head = h("div", {class: "lb-head"},
    h("h1", null, tab.label), h("span", {class: "sub"}, "바이비트 · MEXC 실행기와 그 둘이 따라가는 페이퍼(연습)"), mine.length > 1 ? seg : null);
  const staleSlot = h("div", {class: "lb-slot"});
  const body = h("div", {class: "lb-body"});
  el.classList.add("lb-scr", "lb-tab-" + st.tab);
  el.append(real, head, staleSlot, body);

  const hub = {state: () => st.state, at: () => st.okAt, retry: () => load().catch(() => {}), get: () => st.d};
  const view = tab.make(ctx, hub);
  const own = !!tab.own;
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
    setPapers(d.papers);                 // two paper bots: their labels everywhere (null with one: the usual names)
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

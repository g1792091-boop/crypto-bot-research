// 실거래 (owners 10/19, the live start day: 바이비트 $100 + MEXC $100). The two live order executors (real money) and the
// paper account both follow (COMBO@mix), read-only: dash/more/livebots.py reads the paper bot's database, both executors'
// databases and their configs (never the key file).
// Where it lives (owners 10/19 "대시보드가 지금 규칙봇 안에 있잖아 제거하고 따로 실거래용 봇 대시보드 사이트를 따로"): the
// separate 실거래 site (paperbot/livedash, port 8093, core/site.js LIVE), where every tab below is a menu item (#/<tab>,
// core/routes.js LIVE_SCREENS: 봇별 · 지금 · 기록 · 성적 · 운영) and the head shows the tabs of the item's group. On the rule
// bot's dashboard (port 8080) #/livebots only says where it moved, with the link built from this very host.
//   봇별   one screen per bot (owners 10/26 "대시보드에 추가화면으로 안헷갈리게 추세판단봇 화면 따로, vwap 개선판 봇 화면 따로,
//          친구 30분 봇 화면 따로, v3.9 화면 따로"; BOT_TAB), each with only the executors that follow it, in its head and in
//          the real-money strip: 추세판단 봇 (the 관제 screen with 바이비트 · WOO X Pro only), VWAP 개선판 (VWAP 관제: its paper
//          bot and 딥코인), 친구 30분 봇 (믹스 관제: the 믹스 30분 봇 on the second WOO X Pro account and its paper twin), V3.9
//          투비트 (screens/livebots-v39.js, /api/v4/livebots/v39: the rule bot's V3.9 1-hour paper account and the 투비트
//          executor; 아직 꺼져 있어요 until its database is there), and since 10/26 레인지 봇 (screens/livebots-range.js,
//          /api/v4/livebots/range: the 레인지 봇 paper bot and the executors that follow it, now WOO X Pro). Each leaves an empty <section class="lb-goalres"> at its foot
//          for the 목표 연구 part (screens/livebots-goalres.js goalResSection: the bot's goal arithmetic and research)
//   관제   추세판단 봇's control room (screens/livebots-trend.js, /api/v4/livebots/trend; owners 10/21 "대시보드 다시
//          만들어야겠네 야무지게 필요한부분들 전부다 포함해서"), the site's first screen: what the bot is doing now, the wallets,
//          the open position and its supervisor, every coin's 1h / 4h judgment, the pullback waits, the pauses, today's signal
//          flow, the ten entry strategies, the new bot's record, the supervisor's exits, the rules
//   추세 차트 the 추세판단 봇's judgments over time (screens/livebots-tchart.js, /api/v4/livebots/trendchart; owners 10/21
//          "대시보드 화면들 더 멋있게 모든 필요한 화면 부분들 다 추가로 만들어줘"): 72 hours of every coin's 1h / 4h judgment as a
//          heatmap with the paper entries and the supervisor's exits, and the chosen coin's candles with the judgment band
//          the bot read, its signals by what became of them, the paper trades and the wait's pullback level
//   한눈에 the executors at a glance (screens/livebots-hq.js, owners 10/19 "간지나게"; 관제 until 10/21): the two real
//          wallets, the open position's gauge, "왜 지금 진입 안 하나", the day's pause dial, the light rings
//   포지션 each account's open position as a Binance-style card: 진입가 · 손절가 · 익절가 (the next ladder step) and the whole
//          ladder, 최대 +% / 최대 −% since the entry, the fast-stop state, the paper-vs-live entry gap (screens/livebots-pos.js,
//          /api/v4/livebots/positions)
//   요약   the 실거래 터미널 (screens/livebots-term.js: the rule bot's terminal frame and parts, fed with the live records)
//   차트   the open positions on the price chart, big, with their lines in words (screens/livebots-chart.js)
//   위험 · 봇 상태 · 목표 · 규칙 점검   part B's tabs (screens/livebots-risk.js, livebots-health.js, livebots-goal.js,
//          livebots-judge.js; their routes in dash/more/liveinsight.py)
//   일지   what the 추세판단 봇 and the executors did while the owners were away, one feed newest first (screens/livebots-journal.js)
//   거래  the closed trades of each account, 10 a page, one opened in place, 최대 +% / 최대 −% per trade
//          (screens/livebots-trades.js, its own endpoint and /api/v4/livebots/positions/excursions)
//   다시보기 one closed trade replayed on its 1m bars (screens/livebots-replay.js)
//   신호   "왜 안 들어갔지?": the combined bot's signals and what became of each (screens/livebots-signals.js)
//   못 탄 신호 the virtual results of the signals the bot did not take (screens/livebots-missed.js)
//   검토   추세판단 봇's 2-week review (screens/livebots-review.js, /api/v4/livebots/trendreview): real vs coin flip, day by
//          day, did each new rule help (가상), the record split, what to look at on the review day
//   재현 비교 추세판단 봇's 7/1~10/20 replay (data/trend_replay_0701_1020.json) against its live record since the start
//          (screens/livebots-expect.js, /api/v4/livebots/replayref): entries a weekday, the funnel, the results, the
//          costs split (before costs → slippage → fees → net), by member / coin / side, the cumulative line, with the
//          band the replay leaves for each
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
import {realLine, setPapers, setExecs, execIds, execsKo, followLine, countKo, followersOf} from "./livebots-kit.js";
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
import {journalView} from "./livebots-journal.js";
import {replayView} from "./livebots-replay.js";
import {posView} from "./livebots-pos.js";
import {riskView} from "./livebots-risk.js";
import {healthView} from "./livebots-health.js";
import {goalView} from "./livebots-goal.js";
import {reviewView} from "./livebots-review.js";
import {expectView} from "./livebots-expect.js";
import {judgeView} from "./livebots-judge.js";
import {trendView} from "./livebots-trend.js";
import {tchartView} from "./livebots-tchart.js";
// VWAP 봇 (owners 10/23: the 'VWAP 개선판' paper bot and its executor; menu group "vwap"): 관제 · 성적 · 막은 신호
import {vwapView, vwperfView, vwblockView} from "./livebots-vwap.js";
// 믹스 봇 (owners 10/25 night: the '믹스 30분 봇' on the second WOO X Pro account and its paper twin; menu group "mix"):
// 관제 · 성적
import {mixView, mixperfView, BYBIT_UI} from "./livebots-mix.js";
// 바이비트 봇 (owners 10-29: the friend's trend + OBV / Stoch RSI entries on the Bybit account; menu group "bybit"): 관제 ·
// 성적 (the mix screens on its own answers) · 친구 추세판
import {ftrendView} from "./livebots-ftrend.js";
// 봇별 › V3.9 투비트 (owners 10/26: the rule bot's V3.9 1-hour paper account and the 투비트 executor that follows it)
import {v39View} from "./livebots-v39.js";
// 봇별 › 레인지 봇 (owners 10/26: the 레인지 봇 paper bot and the executors that follow it; docs/range-bot-ko.md)
import {rangeView} from "./livebots-range.js";
// 봇별 화면마다 맨 아래 목표 연구 (owners 10/26 "필요한 연구 부분들 각 봇마다 … 대시보드 화면에 추가해줘"; dash/more/livegoalres.py)
import {goalResSection} from "./livebots-goalres.js";

export const API = "/api/v4/livebots";
const REFRESH_MS = 5 * 1000;               // the server caches 5 s; the executors write every loop, the paper every minute
// in the 실거래 site's menu order (core/routes.js LIVE_GROUPS: 봇별 · 지금 · 기록 · 성적 · 운영)
export const TABS = [
  // 봇별 (owners 10/26): one bot each, its own executors only (BOT_TAB)
  {id: "bybitbot", label: "바이비트 봇", make: (ctx) => mixView(ctx, BYBIT_UI), own: true},
  {id: "rangebot", label: "레인지 봇", make: (ctx) => rangeView(ctx), own: true},
  {id: "vwapbot", label: "VWAP 개선판", make: (ctx, hub) => vwapView(ctx, hub), own: true},
  {id: "mixbot", label: "친구 15분 봇", make: (ctx) => mixView(ctx), own: true},
  {id: "v39", label: "V3.9 투비트", make: (ctx) => v39View(ctx), own: true},
  // owners 10-29: the 추세판단 봇 switched off, its record kept (last of 봇별)
  {id: "trendbot", label: "추세판단 봇", make: (ctx, hub) => trendView(ctx, hub, {only: (a, s) => followersOf(s, "paper").includes(a.id)}), own: true},
  {id: "trend", label: "관제", make: (ctx, hub) => trendView(ctx, hub), own: true},
  {id: "tchart", label: "추세 차트", make: (ctx, hub) => tchartView(ctx, hub), own: true},
  {id: "hq", label: "한눈에", make: (ctx, hub) => hqView(ctx, hub)},
  {id: "pos", label: "포지션", make: (ctx, hub) => posView(ctx, hub), own: true},
  {id: "summary", label: "요약", make: (ctx, hub) => termView(ctx, hub)},
  {id: "chart", label: "차트", make: (ctx, hub) => chartView(ctx, hub)},
  {id: "risk", label: "위험", make: (ctx) => riskView(ctx), own: true},
  {id: "health", label: "봇 상태", make: (ctx) => healthView(ctx), own: true},
  {id: "journal", label: "일지", make: (ctx) => journalView(ctx), own: true},
  {id: "trades", label: "거래", make: (ctx) => tradesView(ctx), own: true},
  {id: "replay", label: "다시보기", make: (ctx) => replayView(ctx), own: true},
  {id: "signals", label: "신호", make: (ctx) => signalsView(ctx), own: true},
  {id: "missed", label: "못 탄 신호", make: (ctx) => missedView(ctx), own: true},
  {id: "review", label: "검토", make: (ctx, hub) => reviewView(ctx, hub), own: true},
  {id: "expect", label: "재현 비교", make: (ctx, hub) => expectView(ctx, hub), own: true},
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
  {id: "vwap", label: "VWAP 관제", make: (ctx, hub) => vwapView(ctx, hub), own: true},
  {id: "vwperf", label: "VWAP 성적", make: (ctx) => vwperfView(ctx), own: true},
  {id: "vwblock", label: "VWAP 막은 신호", make: (ctx) => vwblockView(ctx), own: true},
  {id: "mix", label: "믹스 관제", make: (ctx) => mixView(ctx), own: true},
  {id: "mixperf", label: "믹스 성적", make: (ctx) => mixperfView(ctx), own: true},
  {id: "bybit", label: "바이비트 관제", make: (ctx) => mixView(ctx, BYBIT_UI), own: true},
  {id: "bybitperf", label: "바이비트 성적", make: (ctx) => mixperfView(ctx, BYBIT_UI), own: true},
  {id: "ftrend", label: "친구 추세판", make: (ctx) => ftrendView(ctx), own: true},
];
/** The head line of a menu group that is one bot's own screens (owners 10-29: the 바이비트 봇's). */
const GROUP_SUB = {bybit: "바이비트 봇 · 바이비트 계정 실거래와 모의 쌍둥이 (친구 추세 + OBV 진한색 · 스톡RSI 50선) · 다른 봇은 이 화면에 없어요"};
const tabOf = (arg) => (TABS.some((t) => t.id === arg) ? arg : "hq");
const hasExec = (d, id) => !!(d && Array.isArray(d.execs) && d.execs.some((x) => x && x.id === id));
const botHead = (name, ids) => `${name} 페이퍼(연습)와 ${ids.length ? `그 봇을 따라가는 ${execsKo(ids)} 실행기(진짜 돈)` : "따라가는 실행기 없음"} · 다른 봇은 이 화면에 없어요`;
/** The 봇별 screens (owners 10/26): bot (the 목표 연구 part's id), the head's line, the strip's executors (that bot's only;
 *  none: what its real money is instead). */
export const BOT_TAB = {
  bybitbot: {bot: "bybit", sub: "바이비트 봇 · 바이비트 계정 실거래와 모의 쌍둥이 (친구 추세 + OBV 진한색 · 스톡RSI 50선) · 다른 봇은 이 화면에 없어요",
    head: null, only: () => [], none: "바이비트 봇은 바이비트 계정에서 스스로 거래해요 · 잔고는 아래 실거래 칸"},
  trendbot: {bot: "trend", sub: "추세판단 봇 페이퍼(연습)와 그 봇을 따라가던 실행기 · 두 분 결정(10/29)으로 꺼 두는 봇 · 지난 기록 보관용이에요",
    head: (d) => botHead("추세판단 봇", followersOf(d, "paper")), only: (d) => followersOf(d, "paper"), none: "추세판단 봇을 따라가는 실행기가 지금 없어요"},
  rangebot: {bot: "range", sub: "레인지 봇 페이퍼(연습)와 그 봇을 따라가는 실행기(진짜 돈) · 다른 봇은 이 화면에 없어요",
    head: (d) => botHead("레인지 봇", followersOf(d, "range")), only: (d) => followersOf(d, "range"),
    none: "레인지 봇을 따라가는 실행기가 아직 없어요 (페이퍼만)"},
  vwapbot: {bot: "vwap", sub: "VWAP 개선판 페이퍼(연습)와 그 봇을 따라가는 실행기(진짜 돈) · 다른 봇은 이 화면에 없어요",
    head: (d) => botHead("VWAP 개선판", followersOf(d, "paper2")), only: (d) => followersOf(d, "paper2"),
    none: "VWAP 개선판을 따라가는 실행기가 아직 없어요 (페이퍼만)"},
  // owners 10-30: the friend bot runs ROC / OBV 50 on 15m bars (paperbot/mixchop.py, deploy/mixchop.live.json)
  mixbot: {bot: "mix", sub: "친구 15분 봇(OBV 진한색 · 추세 3개 일치) · WOO X Pro 두 번째 계정 실거래와 모의 쌍둥이 · 다른 봇은 이 화면에 없어요",
    head: null, only: () => [], none: "친구 15분 봇은 WOO X Pro 두 번째 계정에서 거래해요 · 잔고는 아래 실거래 칸"},
  v39: {bot: "v39", sub: "규칙봇 V3.9 1시간 페이퍼(연습) V39_ALL@1h와 그 계좌를 따라가는 투비트 실행기(진짜 돈) · 다른 봇은 이 화면에 없어요",
    head: null, only: (d) => (hasExec(d, "toobit") ? ["toobit"] : []), none: "투비트 실행기는 아직 꺼져 있어요"},
};
/** The foot of a 봇별 screen: the 목표 연구 part (owners 10/26: "각 봇마다 내 목표 수익률(한 달 ×6)을 위해 필요한 분석·연구
 *  부분들"; screens/livebots-goalres.js, its own answer /api/v4/livebots/goalres?bot=). */
function goalResSlot(bot) {
  return h("section", {class: "lb-goalres", "data-goalres-bot": bot});
}
function goalResMount(el, bot, ctx) {
  try { put(el, goalResSection(ctx, bot)); } catch (e) { /* the screen stands without it */ }
}
// what the page already heard (module level: a tab change re-mounts the screen, the same record must not sound again);
// seen null = the next answer is the baseline (the first look, and the first look after the page was hidden)
const heard = {state: null};

/** The rule bot's dashboard (port 8080): the 실거래 screens moved to their own site; this card says where (the link is
 *  this same host on the 실거래 port, the tab kept), nothing else is read or polled here. */
function movedCard(ctx) {
  const tab = ctx.params.arg && TABS.some((t) => t.id === ctx.params.arg) ? ctx.params.arg : "";
  const url = siteUrl(LIVE_PORT, tab ? `#/${tab}` : "");
  return ui.card({title: "실거래 화면은 따로 옮겼어요", cls: "lb-moved"},
    h("p", {class: "lb-moved-p"}, "바이비트 · WOO X Pro 실거래 봇과 그 봇들이 따라가는 페이퍼(연습) 화면은 이제 따로 된 실거래 사이트에서 봐요. 같은 비밀번호로 들어가요."),
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
  const bt = BOT_TAB[st.tab] || null;            // a 봇별 screen: that bot's executors only (head, strip)
  ctx.setTitle(tab.label);
  // the head's tabs: the tabs of this item's menu group (the site's menu lists them all), each a link to its own item
  const group = GROUPS.find((g) => g.screens.includes(st.tab));
  const mine = TABS.filter((t) => !group || group.screens.includes(t.id));
  const seg = ui.seg(mine.map((t) => ({id: t.id, label: t.label})), st.tab, (id) => { if (id !== st.tab) ctx.go("livebots", id); },
    {label: group ? `${group.ko} 보기` : "실거래 보기", scroll: true});
  // the real-money strip on every tab (owners 10/19: never taken for the rule bot's paper screens), from the summary answer
  const real = h("div", {class: "lb-real", role: "note", "aria-label": "진짜 돈 화면"}, bt ? realLine(null, {only: [], none: "불러오는 중"}) : realLine(null));
  // two paper bots (owners 10/23): who follows which, from the summary (followLine); one: the usual line
  const HEAD_SUB = "바이비트 · WOO X Pro 실행기와 그 둘이 따라가는 페이퍼(연습)";
  const gsub = group ? GROUP_SUB[group.id] || null : null;      // a group of one bot's own screens: that bot's words
  const sub = h("span", {class: "sub"}, bt ? bt.sub : gsub || HEAD_SUB);
  const head = h("div", {class: "lb-head"}, h("h1", null, tab.label), sub, mine.length > 1 ? seg : null);
  const staleSlot = h("div", {class: "lb-slot"});
  const body = h("div", {class: "lb-body"});
  const goal = bt ? goalResSlot(bt.bot) : null;
  el.classList.add("lb-scr", "lb-tab-" + st.tab);
  el.append(real, head, staleSlot, body);
  if (goal) el.append(goal);              // a 봇별 screen's foot: the 목표 연구 part's place

  const hub = {state: () => st.state, at: () => st.okAt, retry: () => load().catch(() => {}), get: () => st.d};
  const view = tab.make(ctx, hub);
  const own = !!tab.own;
  put(body, view.el);
  if (goal) goalResMount(goal, bt.bot, ctx);

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
    setExecs(d.execs);                   // the third executor (딥코인) everywhere while the server has it (else the two)
    const two = followLine(d.papers), n = execIds(d).length, three = n > 2;
    // owners 10-29: an account a mix bot took (the summary's ``replaced``) is said after who follows which
    const took = (d.replaced || []).map((r) => `${r.account_ko} → ${r.name_ko}(스스로 매매)`).join(" · ");
    const head = bt ? (bt.head ? bt.head(d) : bt.sub) : gsub ? gsub : `${two ? `실행기 ${countKo(n)} 개 · ${two}`
      : three ? `${execsKo(execIds(d))} 실행기와 그 ${n > 3 ? "넷" : "셋"}이 따라가는 페이퍼(연습)` : HEAD_SUB}${took ? ` · ${took}` : ""}`;
    if (sub.textContent !== head) sub.textContent = head;
    if (bt) put(real, realLine(d, {only: bt.only(d), none: bt.none}));   // a 봇별 screen: that bot's executors only
    else put(real, realLine(d));
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

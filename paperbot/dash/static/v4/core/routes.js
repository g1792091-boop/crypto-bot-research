// The screens and their 5 groups (거래 · 성적 · 매매법 · AI 직원 · 서버). A screen is screens/<name>.js +
// screens/<name>.css (CONTRACT.md). `feature`: shown only while that feature really runs (core/features.js); `soft`:
// always a button, greyed with a '꺼짐' pill while that feature is off (the 토론방: the owners should see it exists; its
// screen says plainly that it has not started); `hidden`: not in the menu (reached by links, e.g. one account). The
// 터미널 is a PC screen: its `feature: "wide"` (a window at least 760 px wide, core/features.js) keeps it off the
// phone's menu. A screen added to a group's `screens` list shows in the menu by itself (core/strip.js: one text button
// per screen, owners 10/06 ~14:00; NAV below sets the groups' order and captions). The start screen (owners 10/06
// 13:27: "들어가면 요약화면이 아니라 차트화면부터"): an empty hash opens this device's 첫 화면 (the 설정 panel,
// core/settings.js) when it has one, else the 터미널 on a PC window (900 px and up, where the terminal fits without
// sideways scrolling), else the 차트 screen (a phone or a tablet held upright); 홈 (요약) stays one click away (#/home,
// its button, its number key (6 since 여러 차트)).
// The 실거래 site (paperbot/livedash, port 8093, owners 10/19 "실거래용 봇 대시보드 사이트를 따로"; core/site.js LIVE): the
// same router over its own menu (LIVE_GROUPS / LIVE_SCREENS below, put in place of the rule bot's before anything reads
// them): every 실거래 tab is a menu item whose module is screens/livebots.js (`mod`), opened at #/<tab> (an old
// #/livebots/<tab> link still lands on it). On the rule bot's page #/livebots is hidden and only says where it moved.
import {s, local} from "./dom.js";
import {START_KEY} from "./prefs.js";
import {LIVE} from "./site.js";

export const GROUPS = [
  {id: "home", ko: "홈", screens: ["home", "board", "flow", "checkpoint"]},
  {id: "trade", ko: "거래", screens: ["terminal", "positions", "chart", "charts", "market"]},
  {id: "strat", ko: "매매법", screens: ["strategies", "grid", "analysis", "compare", "path", "combo", "combo5y", "whatif", "league"]},
  {id: "agents", ko: "에이전트", screens: ["office", "rooms", "digest", "debate"]},
  {id: "server", ko: "서버", screens: ["server", "alerts", "signals", "howto", "faq"]},
];

export const SCREENS = {
  home: {ko: "요약", group: "home", title: "홈"},
  board: {ko: "순위표", group: "home", title: "순위표"},
  flow: {ko: "흐름", group: "home", title: "흐름"},
  story: {ko: "하이라이트", group: "home", title: "오늘의 하이라이트", hidden: true},
  checkpoint: {ko: "판정", group: "home", title: "30일 판정"},
  account: {ko: "계좌", group: "home", title: "계좌", hidden: true},
  livebots: {ko: "실거래", group: "home", title: "실거래", hidden: true},
  terminal: {ko: "터미널", group: "trade", title: "터미널", feature: "wide"},
  positions: {ko: "포지션", group: "trade", title: "포지션"},
  chart: {ko: "차트", group: "trade", title: "차트"},
  charts: {ko: "여러 차트", group: "trade", title: "여러 차트"},
  market: {ko: "시장", group: "trade", title: "시장"},
  strategies: {ko: "매매법", group: "strat", title: "매매법"},
  grid: {ko: "한눈 지도", group: "strat", title: "한눈 지도"},
  replay: {ko: "다시보기", group: "strat", title: "거래 다시보기", hidden: true},
  analysis: {ko: "분석", group: "strat", title: "분석"},
  compare: {ko: "비교", group: "strat", title: "매매법 비교"},
  path: {ko: "졸업 길", group: "strat", title: "졸업 길"},
  combo: {ko: "조합 성과", group: "strat", title: "조합 성과"},
  combo5y: {ko: "5년 조합", group: "strat", title: "5년 조합 시험"},
  whatif: {ko: "만약 실험실", group: "strat", title: "만약 실험실"},
  league: {ko: "그림자 리그", group: "strat", title: "그림자 리그"},
  nextver: {ko: "다음 버전", group: "strat", title: "다음 버전 후보", hidden: true},
  office: {ko: "회의실", group: "agents", title: "회의실"},
  rooms: {ko: "에이전트 방", group: "agents", title: "에이전트 방"},
  digest: {ko: "회의 요약", group: "agents", title: "회의 요약"},
  inbox: {ko: "결재함", group: "agents", title: "결재함", hidden: true},
  debate: {ko: "토론방", group: "agents", title: "24시간 토론방", soft: "debate"},
  server: {ko: "서버·비용", group: "server", title: "서버·비용"},
  alerts: {ko: "알림 기록", group: "server", title: "알림 기록"},
  signals: {ko: "신호", group: "server", title: "신호"},
  howto: {ko: "어떻게 돌아가나", group: "server", title: "어떻게 돌아가나"},
  faq: {ko: "자주 묻는 질문", group: "server", title: "자주 묻는 질문"},
  _kit: {ko: "부품", group: "server", title: "부품 견본", hidden: true},
};

export const DEFAULT = "home";          // an unknown screen name falls back here (never the terminal: no loop)
/** 첫 화면 chosen in the 설정 panel (core/settings.js, per device; "" = automatic), when it can open here: a known,
 *  listed screen, and a PC-only one (`feature: "wide"`) only on a window at least 760 px wide; else null. */
export function startScreen() {
  const v = local.get(START_KEY, "");
  const m = typeof v === "string" && Object.hasOwn(SCREENS, v) ? SCREENS[v] : null;
  if (!m || m.hidden || v.startsWith("_")) return null;
  if (m.feature === "wide" && typeof matchMedia === "function" && !matchMedia("(min-width: 760px)").matches) return null;
  return v;
}
/** The start screen's width: a PC window, where the 터미널 fits (it exists from 760 px, core/features.js `wide`, but
 *  scrolls sideways below about 900 px) and the phone's bottom bar is gone (base.css .botbar, 900 px). */
export const LANDING_MIN_PX = 900;
/** The main rule: the 터미널 on a PC window, else the 차트 screen (a phone, a tablet held upright). Never a
 *  switched-off screen (900 > 760), so the router may also send a PC-only screen opened on a phone here (no loop).
 *  The 설정 panel's automatic 첫 화면 shows this same screen (core/settings.js autoStart). */
export function mainLanding() {
  if (LIVE) return LIVE_START;          // the 실거래 site opens on 관제 (owners 10/19; 추세판단 봇's since 10/21)
  const wide = typeof matchMedia !== "function" || matchMedia(`(min-width: ${LANDING_MIN_PX}px)`).matches;
  return wide ? "terminal" : "chart";
}
/** The screen an empty hash (and the brand mark) opens: this device's 첫 화면 (startScreen) when it has one, else
 *  the main rule (mainLanding). */
export function landing() {
  return startScreen() || mainLanding();
}

/** "#/rooms/strat:S5?x=1" -> {name, arg, query}. */
export function parseHash(hash) {
  const raw = String(hash || "").replace(/^#\/?/, "");
  const [path, qs] = raw.split("?");
  const parts = (path || "").split("/");
  const name = decodeURIComponent(parts[0] || "") || landing();
  const arg = parts.length > 1 ? decodeURIComponent(parts.slice(1).join("/")) : null;
  const query = {};
  if (qs) for (const [k, v] of new URLSearchParams(qs)) query[k] = v;
  // the 실거래 site: #/livebots/<tab> (the 실거래 screens' own links, an old bookmark) is the tab's menu item
  if (LIVE && name === "livebots") return {name: arg && Object.hasOwn(SCREENS, arg) ? arg : LIVE_START, arg: null, query};
  return {name, arg, query};
}
export function href(name, arg, query) {
  if (LIVE && name === "livebots") { name = arg || LIVE_START; arg = null; }   // (the 실거래 site: #/<tab>)
  let out = "#/" + encodeURIComponent(name);
  if (arg != null && arg !== "") out += "/" + encodeURIComponent(arg);
  const q = query && Object.entries(query).filter(([, v]) => v != null && v !== "");
  if (q && q.length) out += "?" + new URLSearchParams(q).toString();
  return out;
}

// 16 x 16 pixel icons for the groups (fill = currentColor)
const R = (x, y, w, hh) => s("rect", {x, y, width: w, height: hh});
const ICON = {
  home: () => [R(7, 1, 2, 1), R(5, 2, 6, 1), R(3, 3, 10, 1), R(1, 4, 14, 2), R(2, 6, 12, 1), R(3, 7, 2, 8), R(11, 7, 2, 8), R(5, 13, 6, 2), R(7, 9, 2, 4)],
  trade: () => [R(2, 3, 1, 11), R(1, 5, 3, 6), R(7, 1, 1, 13), R(6, 3, 3, 5), R(12, 4, 1, 11), R(11, 7, 3, 6)],
  strat: () => [R(2, 1, 10, 1), R(2, 1, 1, 14), R(2, 14, 11, 1), R(12, 1, 1, 14), R(5, 4, 5, 1), R(5, 7, 5, 1), R(5, 10, 3, 1), R(13, 3, 1, 12)],
  agents: () => [R(5, 1, 6, 2), R(5, 3, 6, 4), R(3, 8, 10, 5), R(1, 9, 2, 3), R(13, 9, 2, 3), R(5, 13, 2, 2), R(9, 13, 2, 2)],
  server: () => [1, 6, 11].flatMap((y) => [R(2, y, 12, 1), R(2, y + 3, 12, 1), R(2, y, 1, 4), R(13, y, 1, 4), R(10, y + 1, 2, 2), R(4, y + 1, 4, 1)]),
  // 봇별 (LIVE_GROUPS "bots", owners 10/26): four small robot heads, one per bot
  bots: () => [[0, 0], [9, 0], [0, 9], [9, 9]].flatMap(([x, y]) => [R(x + 3, y, 1, 1), R(x, y + 1, 7, 1), R(x, y + 6, 7, 1), R(x, y + 1, 1, 6),
    R(x + 6, y + 1, 1, 6), R(x + 2, y + 3, 1, 2), R(x + 4, y + 3, 1, 2)]),
  // the 실거래 site's four groups (LIVE_GROUPS): 지금 a radar dot in a ring, 기록 a ruled page, 성적 three bars, 운영 a gear
  now: () => [R(5, 1, 6, 1), R(3, 2, 2, 1), R(11, 2, 2, 1), R(2, 3, 1, 2), R(13, 3, 1, 2), R(1, 5, 1, 6), R(14, 5, 1, 6), R(2, 11, 1, 2),
    R(13, 11, 1, 2), R(3, 13, 2, 1), R(11, 13, 2, 1), R(5, 14, 6, 1), R(7, 4, 2, 5), R(9, 7, 3, 2)],
  rec: () => [R(2, 1, 12, 1), R(2, 1, 1, 14), R(13, 1, 1, 14), R(2, 14, 12, 1), R(5, 4, 6, 1), R(5, 7, 6, 1), R(5, 10, 4, 1)],
  perf: () => [R(1, 14, 14, 1), R(2, 9, 3, 5), R(7, 5, 3, 9), R(12, 2, 3, 12)],
  ops: () => [R(7, 0, 2, 3), R(7, 13, 2, 3), R(0, 7, 3, 2), R(13, 7, 3, 2), R(2, 2, 2, 2), R(12, 2, 2, 2), R(2, 12, 2, 2),
    R(12, 12, 2, 2), R(4, 3, 8, 2), R(4, 11, 8, 2), R(3, 4, 2, 8), R(11, 4, 2, 8)],
  // VWAP 봇: a candle crossing its average line (the VWAP)
  vwap: () => [R(1, 11, 3, 1), R(4, 10, 3, 1), R(7, 9, 2, 1), R(9, 8, 3, 1), R(12, 7, 3, 1), R(7, 2, 2, 13), R(6, 4, 4, 7)],
  // 믹스 봇: the indicator's line turning colour (a falling run, then a rising one) over the 30-minute candles' row
  mix: () => [R(1, 4, 2, 2), R(3, 6, 2, 2), R(5, 8, 2, 2), R(7, 7, 2, 2), R(9, 5, 2, 2), R(11, 3, 2, 2), R(13, 1, 2, 2),
    R(2, 12, 2, 3), R(6, 11, 2, 4), R(10, 12, 2, 3), R(13, 10, 2, 5)],
  // 바이비트 봇 (owners 10-29): the OBV histogram turning dark (three light bars, then a full one) under the trend's arrow
  bybit: () => [R(1, 11, 2, 4), R(4, 10, 2, 5), R(7, 9, 2, 6), R(10, 5, 3, 10), R(2, 3, 9, 1), R(10, 1, 1, 5), R(11, 2, 1, 3),
    R(12, 3, 1, 1)],
};
export const icon =(group) => s("svg", {viewBox: "0 0 16 16", fill: "currentColor", "shape-rendering": "crispEdges", "aria-hidden": "true"},
  (ICON[group] || ICON.home)());

// one 16 x 16 pixel icon per screen: the left rail (core/rail.js) and 찾기 (the menu strip itself is text only)
const SICON = {
  home: ICON.home,
  board: () => [R(1, 9, 4, 6), R(6, 4, 4, 11), R(11, 11, 4, 4), R(7, 1, 2, 2)],
  flow: () => [R(1, 14, 14, 1), R(1, 11, 2, 2), R(3, 9, 2, 2), R(5, 10, 2, 2), R(7, 7, 2, 2), R(9, 8, 2, 2), R(11, 5, 2, 2), R(13, 2, 2, 2)],
  checkpoint: () => [R(3, 1, 2, 14), R(5, 2, 9, 1), R(5, 3, 7, 3), R(5, 6, 9, 1), R(1, 14, 6, 1)],
  // 실거래: a coin (the money) with a live signal light above it
  livebots: () => [R(6, 1, 4, 3), R(5, 6, 6, 1), R(3, 7, 10, 1), R(2, 8, 12, 5), R(3, 13, 10, 1), R(5, 14, 6, 1), R(7, 9, 2, 3)],
  terminal: () => [R(1, 2, 14, 1), R(1, 2, 1, 10), R(14, 2, 1, 10), R(1, 11, 14, 1), R(3, 5, 1, 1), R(4, 6, 1, 1), R(3, 7, 1, 1),
    R(6, 8, 4, 1), R(7, 12, 2, 2), R(4, 14, 8, 1)],
  positions: () => [R(6, 2, 4, 1), R(5, 3, 1, 2), R(10, 3, 1, 2), R(1, 5, 14, 1), R(1, 5, 1, 9), R(14, 5, 1, 9), R(1, 13, 14, 1),
    R(1, 8, 14, 1), R(7, 7, 2, 3)],
  chart: ICON.trade,
  // 여러 차트: four small chart panes, a candle in each
  charts: () => [[1, 1], [9, 1], [1, 9], [9, 9]].flatMap(([x, y]) => [R(x, y, 6, 1), R(x, y + 5, 6, 1), R(x, y, 1, 6), R(x + 5, y, 1, 6), R(x + 2, y + 2, 2, 2)]),
  market: () => [R(5, 1, 6, 1), R(3, 2, 2, 1), R(11, 2, 2, 1), R(2, 3, 1, 2), R(13, 3, 1, 2), R(1, 5, 1, 6), R(14, 5, 1, 6), R(2, 11, 1, 2),
    R(13, 11, 1, 2), R(3, 13, 2, 1), R(11, 13, 2, 1), R(5, 14, 6, 1), R(1, 7, 14, 1), R(7, 1, 2, 14)],
  strategies: ICON.strat,
  grid: () => [0, 1, 2].flatMap((i) => [0, 1, 2].map((j) => R(1 + 5 * i, 1 + 5 * j, 4, 4))),
  analysis: () => [R(3, 1, 6, 2), R(1, 3, 2, 6), R(9, 3, 2, 6), R(3, 9, 6, 2), R(10, 10, 2, 2), R(12, 12, 3, 3)],
  // 매매법 비교: two lines side by side (one solid, one dotted)
  compare: () => [R(1, 9, 2, 2), R(3, 7, 2, 2), R(5, 8, 2, 2), R(7, 5, 2, 2), R(9, 6, 2, 2), R(11, 3, 2, 2), R(13, 1, 2, 2),
    R(1, 14, 2, 1), R(4, 13, 2, 1), R(7, 14, 2, 1), R(10, 12, 2, 1), R(13, 11, 2, 1)],
  path: () => [R(1, 1, 14, 2), R(2, 3, 12, 2), R(4, 5, 8, 2), R(5, 7, 6, 2), R(6, 9, 4, 2), R(7, 11, 2, 4)],
  combo: () => [R(1, 2, 5, 5), R(10, 2, 5, 5), R(6, 10, 5, 5), R(6, 4, 4, 1), R(3, 7, 1, 3), R(3, 10, 3, 1), R(12, 7, 1, 3), R(11, 10, 2, 1)],
  // 5년 조합: two linked blocks (a combination) over a row of bars
  combo5y: () => [R(1, 2, 6, 6), R(9, 2, 6, 6), R(7, 4, 2, 2), R(3, 4, 2, 2), R(11, 4, 2, 2), R(1, 11, 14, 1), R(1, 13, 3, 2), R(6, 12, 3, 3), R(11, 13, 4, 2)],
  // 만약 실험실: two slider tracks with their knobs (settings to try)
  whatif: () => [R(1, 4, 14, 1), R(4, 2, 3, 5), R(1, 11, 14, 1), R(9, 9, 3, 5)],
  // 그림자 리그: a small solid figure and, beside it, its shadow drawn as an empty outline (watched, not traded)
  league: () => [R(3, 2, 3, 3), R(2, 6, 5, 6), R(3, 12, 1, 3), R(5, 12, 1, 3), R(9, 5, 5, 1), R(9, 13, 5, 1), R(9, 5, 1, 9), R(13, 5, 1, 9), R(11, 8, 1, 1)],
  office: () => [R(3, 2, 3, 3), R(10, 2, 3, 3), R(1, 6, 14, 3), R(3, 9, 1, 5), R(12, 9, 1, 5)],
  rooms: () => [R(4, 1, 8, 1), R(4, 1, 1, 13), R(11, 1, 1, 13), R(2, 14, 12, 1), R(9, 7, 1, 2)],
  digest: () => [R(1, 2, 14, 1), R(1, 2, 1, 9), R(14, 2, 1, 9), R(1, 10, 14, 1), R(3, 11, 2, 3), R(4, 5, 8, 1), R(4, 7, 5, 1)],
  debate: () => [R(1, 1, 9, 5), R(2, 6, 2, 2), R(6, 8, 9, 5), R(12, 13, 2, 2)],
  server: ICON.server,
  alerts: () => [R(7, 1, 2, 1), R(5, 2, 6, 1), R(4, 3, 8, 6), R(3, 9, 10, 2), R(2, 11, 12, 1), R(7, 13, 2, 2)],
  signals: () => [R(1, 8, 4, 1), R(5, 6, 1, 2), R(6, 2, 1, 4), R(7, 6, 1, 6), R(8, 12, 1, 2), R(9, 7, 1, 5), R(10, 8, 5, 1)],
  howto: () => [R(7, 1, 2, 2), R(7, 13, 2, 2), R(1, 7, 2, 2), R(13, 7, 2, 2), R(5, 3, 6, 2), R(5, 11, 6, 2), R(3, 5, 2, 6), R(11, 5, 2, 6),
    R(3, 3, 2, 2), R(11, 3, 2, 2), R(3, 11, 2, 2), R(11, 11, 2, 2)],
  faq: () => [R(5, 1, 6, 2), R(3, 3, 3, 3), R(10, 3, 3, 4), R(8, 7, 3, 2), R(7, 9, 2, 2), R(7, 12, 2, 2)],
  // the 실거래 site's tabs (LIVE_SCREENS, 찾기): the nearest drawing of a rule-bot screen
  // 봇별 (owners 10/26): each bot's own drawing (추세판단 봇 the coin of 관제, VWAP and 믹스 their groups', V3.9 candles)
  trendbot: () => SICON.livebots(),
  // 레인지 봇: a price line held inside its band (the range filter) and the pullback dot under it
  rangebot: () => [R(1, 3, 14, 1), R(1, 12, 14, 1), R(2, 9, 2, 2), R(4, 7, 2, 2), R(6, 8, 2, 2), R(8, 6, 2, 2), R(10, 5, 2, 2), R(12, 4, 2, 2),
    R(9, 9, 2, 2)],
  vwapbot: ICON.vwap,
  mixbot: ICON.mix,
  v39: ICON.trade,
  trend: () => SICON.livebots(),
  // 추세 차트: two rows of judgment cells (the heatmap) over three candles
  tchart: () => [R(1, 1, 4, 3), R(6, 1, 3, 3), R(10, 1, 5, 3), R(1, 5, 6, 3), R(8, 5, 7, 3), R(3, 9, 1, 6), R(2, 10, 3, 3),
    R(8, 10, 1, 5), R(7, 11, 3, 2), R(13, 9, 1, 6), R(12, 10, 3, 3)],
  hq: () => SICON.grid(),
  pos: () => SICON.positions(),
  summary: () => SICON.terminal(),
  risk: () => SICON.alerts(),
  health: ICON.server,
  // 일지: a line of three dots, each with its line of words
  journal: () => [R(3, 1, 1, 14), R(2, 2, 3, 3), R(6, 3, 9, 1), R(2, 7, 3, 3), R(6, 8, 7, 1), R(2, 12, 3, 3), R(6, 13, 8, 1)],
  trades: () => SICON.digest(),
  replay: () => SICON.flow(),
  missed: () => SICON.signals(),
  review: () => SICON.checkpoint(),
  expect: () => SICON.compare(),
  perf: () => SICON.board(),
  goal: () => SICON.checkpoint(),
  rank: () => SICON.board(),
  judge: () => SICON.howto(),
  map: () => SICON.grid(),
  cost: () => SICON.market(),
  cal: () => SICON.digest(),
  safety: () => SICON.alerts(),
  settings: ICON.ops,
  team: () => SICON.office(),
  shadows: () => SICON.league(),
  // VWAP 봇 (LIVE_GROUPS "vwap"): 관제 the group's drawing, 성적 the board's bars, 막은 신호 a bar crossed out
  vwap: ICON.vwap,
  vwperf: () => SICON.board(),
  vwblock: () => [R(1, 9, 4, 6), R(6, 4, 4, 11), R(11, 11, 4, 4), R(1, 1, 2, 2), R(3, 3, 2, 2), R(5, 5, 2, 2), R(7, 7, 2, 2), R(9, 9, 2, 2),
    R(11, 11, 2, 2), R(13, 13, 2, 2)],
  // 믹스 봇 (LIVE_GROUPS "mix"): 관제 the group's drawing, 성적 the board's bars
  mix: ICON.mix,
  mixperf: () => SICON.board(),
  // 바이비트 봇 (LIVE_GROUPS "bybit", 봇별 › 바이비트 봇): the group's drawing, 성적 the board's bars, 친구 추세판 four votes
  bybitbot: ICON.bybit,
  bybit: ICON.bybit,
  bybitperf: () => SICON.board(),
  ftrend: () => [R(1, 3, 3, 3), R(5, 3, 3, 3), R(9, 3, 3, 3), R(13, 4, 2, 1), R(1, 9, 3, 3), R(5, 9, 3, 3), R(9, 10, 3, 1),
    R(13, 9, 2, 3)],
};
export const screenIcon = (name) => s("svg", {viewBox: "0 0 16 16", fill: "currentColor", "shape-rendering": "crispEdges", "aria-hidden": "true"},
  (SICON[name] || ICON[(SCREENS[name] || {}).group] || ICON.home)());

/** The screens of a group the menu lists now (feats = core/features.js; true = every feature on): hidden ones out, a
 *  `feature` screen only while it runs (the PC 터미널 only on a wide window); a `soft` one stays (greyed with 꺼짐). */
export function menuScreens(g, feats) {
  return g.screens.filter((n) => SCREENS[n] && !SCREENS[n].hidden
    && (!SCREENS[n].feature || feats === true || !!(feats && feats[SCREENS[n].feature])));
}

/** The menu (core/strip.js; owners 10/06 ~14:00 with a photo of the v3 tab bar: "클릭해서 바로 들어갈수있는 버튼들을
 *  많이 만들어줬으면", "왼쪽에 그림으로 되어있는데 너무 헷갈려"): every screen its own text button, the groups in this order,
 *  each with its caption. A group of GROUPS missing here comes last under its own name. The phone's bottom bar keeps
 *  GROUPS' order and names (홈 · 거래 · 매매법 · 에이전트 · 서버). */
export const NAV = [
  {group: "trade", ko: "거래"},
  {group: "home", ko: "성적"},
  {group: "strat", ko: "매매법"},
  {group: "agents", ko: "AI 직원"},
  {group: "server", ko: "서버"},
];
/** One button for several screens of one group: it opens the first and is lit on each; every one of them shows a
 *  small switch to the others at its top (core/strip.js joinedTabs), so each stays one click away. */
export const JOINED = [{id: "help", ko: "도움말", screens: ["howto", "faq"]}];
/** A group's caption in the menu ("성적" for 홈's screens). */
export const navLabel = (gid) => (NAV.find((x) => x.group === gid) || GROUPS.find((x) => x.id === gid) || {ko: ""}).ko;

/**
 * navGroups(feats) -> the menu's buttons now: [{group, ko, items: [{id, ko, to, screens}]}] in NAV order. `to` is the
 * screen a button opens, `screens` the ones it is lit on (one, or a JOINED set). feats as in menuScreens.
 */
export function navGroups(feats) {
  const order = [...NAV.filter((x) => GROUPS.some((g) => g.id === x.group)),
    ...GROUPS.filter((g) => !NAV.some((x) => x.group === g.id)).map((g) => ({group: g.id, ko: g.ko}))];
  return order.map((x) => {
    const shown = menuScreens(GROUPS.find((g) => g.id === x.group), feats);
    const items = [];
    for (const n of shown) {
      const j = JOINED.find((y) => y.screens.includes(n));
      const set = j ? j.screens.filter((m) => shown.includes(m)) : [n];
      if (set.length < 2) items.push({id: n, ko: SCREENS[n].ko, to: n, screens: [n]});
      else if (!items.some((it) => it.id === j.id)) items.push({id: j.id, ko: j.ko, to: set[0], screens: set});
    }
    return items.length ? {group: x.group, ko: x.ko, items} : null;
  }).filter(Boolean);
}

// ---------------------------------------------------------------- the 실거래 site (paperbot/livedash, core/site.js LIVE)
// Owners 10/19: "실거래용 봇 대시보드 사이트를 따로 … 지금 실거래봇 대시보드 형식으로 똑같이": the 실거래 tabs are this site's
// menu, in four groups (the strip's thin lines, the phone's bottom bar). Every item opens screens/livebots.js on its tab
// (`mod`; the router hands it {name: "livebots", arg: <tab>}), so the screens, their css scope ([data-screen="livebots"])
// and their own links (#/livebots/<tab>, parseHash / href above) are the very ones of the rule bot's page before the move.
// owners 10-29 (the 추세판단 봇 switched off, the 바이비트 봇 on the Bybit account): the site opens on 한눈에 (every real-money
// account), never on a bot that no longer trades
export const LIVE_START = "hq";
const LIVE_GROUPS = [
  // 봇별 (owners 10/26 "대시보드에 추가화면으로 안헷갈리게 추세판단봇 화면 따로, vwap 개선판 봇 화면 따로, 친구 30분 봇 화면
  // 따로, v3.9 화면 따로"): one screen per bot, first in the menu, each with only the executors that follow it
  // (screens/livebots.js BOT_TABS); the screens of the groups below stay as they were
  // owners 10-29: the 바이비트 봇 first, the 추세판단 봇 (switched off, its record kept) last
  {id: "bots", ko: "봇별", screens: ["bybitbot", "rangebot", "vwapbot", "mixbot", "v39", "trendbot"]},
  {id: "now", ko: "지금", screens: ["trend", "tchart", "hq", "pos", "summary", "chart", "risk", "health"]},
  {id: "rec", ko: "기록", screens: ["journal", "trades", "replay", "signals", "missed"]},
  {id: "perf", ko: "성적", screens: ["review", "expect", "perf", "goal", "rank", "judge", "map", "cost"]},
  {id: "ops", ko: "운영", screens: ["cal", "safety", "settings", "team", "shadows"]},
  // the second paper bot 'VWAP 개선판' and the executor that will follow it (owners 10/23, docs/vwap-bot-ko.md): its own
  // group, last (the number keys of the four groups stay); each tab says 꺼짐 until the bot runs (screens/livebots-vwap.js)
  {id: "vwap", ko: "VWAP 봇", screens: ["vwap", "vwperf", "vwblock"]},
  // the '믹스 30분 봇' on the second WOO X Pro account (real money) and its paper twin (owners 10/25 night,
  // docs/mixchop-ko.md): its own group, last; each column says 꺼짐 until its bot runs (screens/livebots-mix.js)
  {id: "mix", ko: "믹스 봇", screens: ["mix", "mixperf"]},
  // the 바이비트 봇 (owners 10-29, docs/mixbybit-ko.md: the friend's trend + OBV / Stoch RSI entries on the Bybit account,
  // real money, and its paper twin) and the friend's trend per coin (dash/more/liveftrend.py): its own group, last
  {id: "bybit", ko: "바이비트 봇", screens: ["bybit", "bybitperf", "ftrend"]},
];
const LIVE_SCREENS = {
  bybitbot: {ko: "바이비트 봇", group: "bots", title: "바이비트 봇 (친구 추세 + OBV · 스톡RSI · 바이비트 실거래와 모의)"},
  trendbot: {ko: "추세판단 봇", group: "bots", title: "추세판단 봇 (10/29부터 꺼 둠 · 지난 기록)"},
  rangebot: {ko: "레인지 봇", group: "bots", title: "레인지 봇 (페이퍼와 그 봇을 따라가는 WOO X Pro)"},
  vwapbot: {ko: "VWAP 개선판", group: "bots", title: "VWAP 개선판 (페이퍼와 그 봇을 따라가는 딥코인)"},
  mixbot: {ko: "친구 30분 봇", group: "bots", title: "친구 30분 봇 (믹스 30분 봇 · WOO X Pro 2 실거래와 모의)"},
  v39: {ko: "V3.9 투비트", group: "bots", title: "V3.9 투비트 (규칙봇 V3.9 1시간 페이퍼와 투비트 실행기)"},
  trend: {ko: "관제", group: "now", title: "관제 (추세판단 봇 · 10/29부터 꺼 둠)"},
  tchart: {ko: "추세 차트", group: "now", title: "추세 차트 (판단 기록과 신호)"},
  hq: {ko: "한눈에", group: "now", title: "한눈에 (실거래 계좌 모두)"},
  pos: {ko: "포지션", group: "now", title: "포지션"},
  summary: {ko: "요약", group: "now", title: "요약 (실거래 터미널)"},
  chart: {ko: "차트", group: "now", title: "차트"},
  risk: {ko: "위험", group: "now", title: "위험"},
  health: {ko: "봇 상태", group: "now", title: "봇 상태"},
  journal: {ko: "일지", group: "rec", title: "일지 (자리 비운 동안 있었던 일)"},
  trades: {ko: "거래", group: "rec", title: "거래"},
  replay: {ko: "다시보기", group: "rec", title: "거래 다시보기"},
  signals: {ko: "신호", group: "rec", title: "신호"},
  missed: {ko: "못 탄 신호", group: "rec", title: "못 탄 신호"},
  review: {ko: "검토", group: "perf", title: "2주 검토 (추세판단 봇)"},
  expect: {ko: "재현 비교", group: "perf", title: "재현 비교 (7/1~10/20 가상 vs 실제)"},
  perf: {ko: "성적", group: "perf", title: "성적"},
  goal: {ko: "목표", group: "perf", title: "목표"},
  rank: {ko: "순위", group: "perf", title: "매매법 순위"},
  judge: {ko: "규칙 점검", group: "perf", title: "규칙 점검"},
  map: {ko: "지도", group: "perf", title: "지도"},
  cost: {ko: "비용", group: "perf", title: "비용"},
  cal: {ko: "일정", group: "ops", title: "일정"},
  safety: {ko: "안전", group: "ops", title: "안전"},
  settings: {ko: "설정", group: "ops", title: "봇 설정"},
  team: {ko: "분석팀", group: "ops", title: "분석팀"},
  shadows: {ko: "그림자", group: "ops", title: "그림자 봇"},
  vwap: {ko: "VWAP 관제", group: "vwap", title: "VWAP 관제 (VWAP 개선판)"},
  vwperf: {ko: "VWAP 성적", group: "vwap", title: "VWAP 성적 (페이퍼 · 동전 쌍둥이 · 실거래)"},
  vwblock: {ko: "VWAP 막은 신호", group: "vwap", title: "VWAP 막은 신호 (막지 않았다면)"},
  mix: {ko: "믹스 관제", group: "mix", title: "믹스 관제 (믹스 30분 봇 · 실거래와 모의)"},
  mixperf: {ko: "믹스 성적", group: "mix", title: "믹스 성적 (실거래 · 모의 · 설계서 5년)"},
  bybit: {ko: "바이비트 관제", group: "bybit", title: "바이비트 관제 (바이비트 봇 · 실거래와 모의)"},
  bybitperf: {ko: "바이비트 성적", group: "bybit", title: "바이비트 성적 (실거래 vs 모의)"},
  ftrend: {ko: "친구 추세판", group: "bybit", title: "친구 추세판 (코인별 30분 · 1시간 추세 투표와 OBV · 스톡RSI)"},
};
if (LIVE) {
  // put in place (the same objects every module already imported): the menu, the screens, the strip's groups
  GROUPS.splice(0, GROUPS.length, ...LIVE_GROUPS);
  for (const k of Object.keys(SCREENS)) delete SCREENS[k];
  for (const [k, v] of Object.entries(LIVE_SCREENS)) SCREENS[k] = {...v, mod: "livebots"};
  NAV.splice(0, NAV.length, ...LIVE_GROUPS.map((g) => ({group: g.id, ko: g.ko})));
  JOINED.length = 0;
}

/** The number keys 1-9 (core/navkeys.js): the menu's first nine buttons, in its order (owners 10/06 ~14:00). */
export const KEYS = navGroups(true).flatMap((g) => g.items.map((it) => it.to)).slice(0, 9);
/** A screen's number key ("1" ... "9"), null when it has none. */
export const keyOf = (name) => { const i = KEYS.indexOf(name); return i < 0 ? null : String(i + 1); };
/** Links that open in the side panel instead of leaving the page (core/drawer.js): route name -> panel kind. */
export const PEEKABLE = {account: "account", strategies: "strategy", replay: "trade"};
if (LIVE) for (const k of Object.keys(PEEKABLE)) delete PEEKABLE[k];       // (the 실거래 site: no side panel; its 다시보기 is a tab)
/** The screens about real money (owners 10/19: the 실거래 screen must never be taken for the rule bot's paper screens). */
export const REAL_SCREENS = ["livebots"];
/** The top bar's mode chip for a screen (core/shell.js): 실거래 in the real-money colour (--warn, base.css .mocktag.real)
 *  on a real-money screen, 모의 on every other one; every screen of the 실거래 site is one. */
export function modeTag(name) {
  return LIVE || REAL_SCREENS.includes(name)
    ? {text: "실거래", real: true, title: "진짜 돈: 바이비트 · WOO X Pro 실행기와 각 실행기가 따라가는 페이퍼(연습) · 이 화면은 보기만 해요 (주문 버튼 없음)"}
    : {text: "모의", real: false, title: "모든 계좌는 모의(가상 돈)입니다"};
}

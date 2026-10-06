// The navigation: 5 groups (홈 · 거래 · 매매법 · 에이전트 · 서버), each with its screens (sub tabs). A screen is
// screens/<name>.js + screens/<name>.css (CONTRACT.md). `feature`: shown only while that feature really runs
// (core/features.js); `soft`: always a tab, greyed with a '꺼짐' pill while that feature is off (the 토론방: the owners
// should see it exists; its screen says plainly that it has not started); `hidden`: not a tab (reached by links, e.g. one account). The 터미널 is a PC screen: its
// `feature: "wide"` (a window at least 760 px wide, core/features.js) keeps it off the phone's menu, and it is the
// landing screen (an empty hash) only on a window at least 1200 px wide; phones and narrow windows land on 홈.
import {s, local} from "./dom.js";
import {START_KEY} from "./prefs.js";

export const GROUPS = [
  {id: "home", ko: "홈", screens: ["home", "board", "flow", "checkpoint"]},
  {id: "trade", ko: "거래", screens: ["terminal", "positions", "chart", "market"]},
  {id: "strat", ko: "매매법", screens: ["strategies", "grid", "analysis"]},
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
  terminal: {ko: "터미널", group: "trade", title: "터미널", feature: "wide"},
  positions: {ko: "포지션", group: "trade", title: "포지션"},
  chart: {ko: "차트", group: "trade", title: "차트"},
  market: {ko: "시장", group: "trade", title: "시장"},
  strategies: {ko: "매매법", group: "strat", title: "매매법"},
  grid: {ko: "한눈 지도", group: "strat", title: "한눈 지도"},
  replay: {ko: "다시보기", group: "strat", title: "거래 다시보기", hidden: true},
  analysis: {ko: "분석", group: "strat", title: "분석"},
  office: {ko: "회의실", group: "agents", title: "회의실"},
  rooms: {ko: "에이전트 방", group: "agents", title: "에이전트 방"},
  digest: {ko: "회의 요약", group: "agents", title: "회의 요약"},
  debate: {ko: "토론방", group: "agents", title: "24시간 토론방", soft: "debate"},
  server: {ko: "서버·비용", group: "server", title: "서버·비용"},
  alerts: {ko: "알림 기록", group: "server", title: "알림 기록"},
  signals: {ko: "신호", group: "server", title: "신호"},
  howto: {ko: "어떻게 돌아가나", group: "server", title: "어떻게 돌아가나"},
  faq: {ko: "자주 묻는 질문", group: "server", title: "자주 묻는 질문"},
  _kit: {ko: "부품", group: "server", title: "부품 견본", hidden: true},
};

export const DEFAULT = "home";          // unknown or switched-off screens fall back here (never the terminal: no loop)
/** 첫 화면 chosen in the 설정 panel (core/settings.js, per device; "" = automatic), when it can open here: a known,
 *  listed screen, and a PC-only one (`feature: "wide"`) only on a window at least 760 px wide; else null. */
export function startScreen() {
  const v = local.get(START_KEY, "");
  const m = typeof v === "string" && Object.hasOwn(SCREENS, v) ? SCREENS[v] : null;
  if (!m || m.hidden || v.startsWith("_")) return null;
  if (m.feature === "wide" && typeof matchMedia === "function" && !matchMedia("(min-width: 760px)").matches) return null;
  return v;
}
/** The screen an empty hash opens: this device's 첫 화면 (startScreen) when it has one, else the 터미널 on a window at
 *  least 1200 px wide, else 홈 (phones keep 홈). */
export const LANDING_MIN_PX = 1200;
export function landing() {
  const pick = startScreen();
  if (pick) return pick;
  const wide = typeof matchMedia === "function" && matchMedia(`(min-width: ${LANDING_MIN_PX}px)`).matches;
  return wide ? "terminal" : DEFAULT;
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
  return {name, arg, query};
}
export function href(name, arg, query) {
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
};
export const icon = (group) => s("svg", {viewBox: "0 0 16 16", fill: "currentColor", "shape-rendering": "crispEdges", "aria-hidden": "true"},
  (ICON[group] || ICON.home)());

// one 16 x 16 pixel icon per screen for the PC left rail (core/rail.js)
const SICON = {
  home: ICON.home,
  board: () => [R(1, 9, 4, 6), R(6, 4, 4, 11), R(11, 11, 4, 4), R(7, 1, 2, 2)],
  flow: () => [R(1, 14, 14, 1), R(1, 11, 2, 2), R(3, 9, 2, 2), R(5, 10, 2, 2), R(7, 7, 2, 2), R(9, 8, 2, 2), R(11, 5, 2, 2), R(13, 2, 2, 2)],
  checkpoint: () => [R(3, 1, 2, 14), R(5, 2, 9, 1), R(5, 3, 7, 3), R(5, 6, 9, 1), R(1, 14, 6, 1)],
  terminal: () => [R(1, 2, 14, 1), R(1, 2, 1, 10), R(14, 2, 1, 10), R(1, 11, 14, 1), R(3, 5, 1, 1), R(4, 6, 1, 1), R(3, 7, 1, 1),
    R(6, 8, 4, 1), R(7, 12, 2, 2), R(4, 14, 8, 1)],
  positions: () => [R(6, 2, 4, 1), R(5, 3, 1, 2), R(10, 3, 1, 2), R(1, 5, 14, 1), R(1, 5, 1, 9), R(14, 5, 1, 9), R(1, 13, 14, 1),
    R(1, 8, 14, 1), R(7, 7, 2, 3)],
  chart: ICON.trade,
  market: () => [R(5, 1, 6, 1), R(3, 2, 2, 1), R(11, 2, 2, 1), R(2, 3, 1, 2), R(13, 3, 1, 2), R(1, 5, 1, 6), R(14, 5, 1, 6), R(2, 11, 1, 2),
    R(13, 11, 1, 2), R(3, 13, 2, 1), R(11, 13, 2, 1), R(5, 14, 6, 1), R(1, 7, 14, 1), R(7, 1, 2, 14)],
  strategies: ICON.strat,
  grid: () => [0, 1, 2].flatMap((i) => [0, 1, 2].map((j) => R(1 + 5 * i, 1 + 5 * j, 4, 4))),
  analysis: () => [R(3, 1, 6, 2), R(1, 3, 2, 6), R(9, 3, 2, 6), R(3, 9, 6, 2), R(10, 10, 2, 2), R(12, 12, 3, 3)],
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
};
export const screenIcon = (name) => s("svg", {viewBox: "0 0 16 16", fill: "currentColor", "shape-rendering": "crispEdges", "aria-hidden": "true"},
  (SICON[name] || ICON[(SCREENS[name] || {}).group] || ICON.home)());

/** The number keys 1-9 (core/navkeys.js): the screens opened most, in this order (owners 10/06). */
export const KEYS = ["terminal", "home", "positions", "strategies", "board", "office", "chart", "market", "server"];
/** Links that open in the side panel instead of leaving the page (core/drawer.js): route name -> panel kind. */
export const PEEKABLE = {account: "account", strategies: "strategy", replay: "trade"};

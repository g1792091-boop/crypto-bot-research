// The navigation: 5 groups (홈 · 거래 · 매매법 · 에이전트 · 서버), each with its screens (sub tabs). A screen is
// screens/<name>.js + screens/<name>.css (CONTRACT.md). `feature`: shown only while that feature really runs
// (core/features.js); `soft`: always a tab, greyed with a '꺼짐' pill while that feature is off (the 토론방: the owners
// should see it exists; its screen says plainly that it has not started); `hidden`: not a tab (reached by links, e.g. one account). The 터미널 is a PC screen: its
// `feature: "wide"` (a window at least 760 px wide, core/features.js) keeps it off the phone's menu, and it is the
// landing screen (an empty hash) only on a window at least 1200 px wide; phones and narrow windows land on 홈.
import {s} from "./dom.js";

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
/** The screen an empty hash opens: the 터미널 on a window at least 1200 px wide, else 홈 (phones keep 홈). */
export const LANDING_MIN_PX = 1200;
export function landing() {
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

// 실거래 › 순위 (#/livebots/rank, owners 10/19 "간지나게, 멋있게"): 매매법 순위표 of the combined bot both executors follow
// (A+C 합본). /api/v4/livebots/rank (dash/more/livebots.py rank()) sends, per strategy of the config the bot runs: its
// settings in words, the paper account's closed trades and open position, each executor's followed trades, its signals of
// the last 7 Korea-time days, its 5-year numbers (deploy/combo.live-ac.expected.json) and the 성적표 status word. Nothing is
// ranked on the server: this page sorts (exported pure functions below, tested in node).
//   머리      매매법 · 세팅 수, 이번 주 신호를 낸 매매법, 페이퍼 거래가 있는 매매법, 지금 포지션; 선수단: every strategy as its
//             pixel figure (lit = a signal this week, ringed = holding the position now), a tap opens its line below
//   상위 5 · 하위 5  선수 카드: jersey rank, figure, name, type, timeframes, one big number for the chosen order, bars of
//             5년 승률 (맞춘 숫자) · 처음 보는 기간 · 지금 (paper, only with trades) against 본전, this week's signals, chips
//   전체 목록  every strategy, 10 a page, searchable; a line opens in place (rowDetail): 왜 이 매매법인가 (its 5-year line and
//             its rule lines from strategies-defs.js, for the codes that have them), its settings, the 5-year numbers, the
//             paper and live records, its signals. A tap on a card or a 선수단 figure opens its line there.
// Default order: 페이퍼 손익 once any strategy has a paper trade, before that 5년 기여도 (and the page says so); a chosen order
// is remembered on this device (local), and an order with nothing to rank yet falls back to 5년 기여도, saying why.
// HONESTY: a number nobody has yet is '—' / 거래 전, never 0 (a strategy without trades has no rank in 손익 · 승률); a source
// not there is 수집 전, one not read 못 읽음 + why (livebots-kit sourceState); fit numbers are named 맞춘 숫자, the realistic
// reference is 처음 보는 기간; under 20 trades 표본 적음; with few trades a ranking is mostly luck (the foot says so); paper
// money is 연습 money (모의 caption), live money its own caption. Glow only for a real state (the open position), three
// pulses then steady; nothing moves under prefers-reduced-motion.
// 추세판단 봇 (the answer's trend_bot, owners 10/21): no 5-year number anywhere (기준 없음 + the server's reason, no 5-year order
// in the select, no 5년 / 처음 보는 bars, the line's 백테스트 says 기준 없음), records from its start, the role on every card and
// line, ordered by 페이퍼 손익 once traded and 이번 주 신호 before (pickSort -> pickTrend), 읽는 법 in its own words.
// Two views behind one switch on top (owners 10/19): 진입 가능성 (screens/livebots-likely.js: which strategy is most likely to
// enter next, /api/v4/livebots/likely; the default) | 성적 순위 (boardView below). The choice is remembered on this device
// (local: localStorage inside try/catch); each view is built when first shown and polls only while it is the one shown.
import {h, put, ui, fmt, local, motion, stratFigure, stratHue} from "../core/pb.js";
import {sourceState, mainFollowKo, acctKo, EXEC_SLOTS, execIds, execsNow, execsKo, allFollowKo} from "./livebots-kit.js";

/** Who follows the ranked paper bot, in words: "두 실행기가 따라가는" with one paper bot; with two (owners 10/23) only its own
 *  followers ("바이비트가 따라가는"). */
const followKo = () => mainFollowKo() || allFollowKo();
/** With two paper bots the live rows are only each executor's trades on this bot (the server's rank: paper first). */
const liveOnlyKo = () => (mainFollowKo() ? " (각 실행기가 이 봇을 따라간 거래만)" : "");
import {likelyView} from "./livebots-likely.js";
import {toneOf} from "./livebots-score.js";
import {DS_DEFS} from "./strategies-defs.js";

export const API = "/api/v4/livebots/rank";
const REFRESH_MS = 30 * 1000;
const SORT_KEY = "lb-rank-sort";
export const TOP_N = 5;
/** The orders: id, the select's words, the big number's label, the deck's one line. */
export const SORTS = [
  {id: "pnl", label: "페이퍼 손익", big: "페이퍼 손익", desc: "페이퍼 닫힌 거래 순손익이 큰 순"},
  {id: "win", label: "승률", big: "지금 승률", desc: "페이퍼 닫힌 거래 승률이 높은 순 (같으면 거래가 많은 쪽)"},
  {id: "trades", label: "거래 수", big: "페이퍼 거래", desc: "페이퍼 닫힌 거래가 많은 순"},
  {id: "signals", label: "이번 주 신호", big: "이번 주 신호", desc: "최근 7일(한국 시간) 신호가 많은 순"},
  {id: "contrib", label: "5년 기여도", big: "5년 기여도", desc: "5년 시험에서 전체가 불어난 몫 중 이 매매법 몫이 큰 순"},
  {id: "fit", label: "5년 승률", big: "5년 승률", desc: "5년 전부에 맞춘 승률이 높은 순 (좋게 나오는 숫자)"},
  {id: "honest", label: "처음 보는 기간 승률", big: "처음 보는 기간", desc: "2020-24에만 맞추고 2025-26에 처음 돌린 승률이 높은 순"},
];
const SORT_BY = Object.fromEntries(SORTS.map((x) => [x.id, x]));
/** The five styles of the 5-year table (type badge colours: livebots-rank.css .lbr-type[data-t]). */
export const TYPE_ID = {"추세": "trend", "되돌림": "pull", "돌파": "brk", "반전": "rev", "박스권": "box"};
const STAGE_KO = [["entered", "진입"], ["filtered", "걸러짐"], ["waiting", "가격 기다림"], ["skipped", "밀림"], ["rejected", "거절"]];

// ---------------------------------------------------------------- pure functions (node tests: tests/test_dash_livebots_rank.py)
const numOr = (x) => (x == null || x === "" || typeof x === "boolean" || !Number.isFinite(Number(x)) ? null : Number(x));
const cmpStr = (a, b) => (String(a) < String(b) ? -1 : String(a) > String(b) ? 1 : 0);
const inCfg = (r) => r && r.in_config !== false;
/** The word for a source that did not answer: 수집 전 (not there yet) or 못 읽음 (could not be read). */
export const missWord = (src) => (!src || src.state === "missing" || src.state === "none" ? "수집 전" : "못 읽음");

/** Which parts of the answer were read: paper (trades, position), signals, ref (the 5-year table), card (성적표). */
export function sources(d) {
  const ok = (x) => !!x && x.state === "ok";
  return {paper: ok(d && d.paper), signals: ok(d && d.signals), ref: ok(d && d.ref), card: ok(d && d.scorecard)};
}

/** This week's signal count of a row (0 is real only when the signal log was read: the caller checks sources). */
export const weekSignals = (r) => Number((r && r.sig && r.sig.week && r.sig.week.signals) || 0);
/** The paper record's closed trades (0 is real only when the paper database was read). */
export const paperN = (r) => Number((r && r.paper && r.paper.n) || 0);

/**
 * A row's number for an order, or null when it has none: no closed trade yet (손익 · 승률), a source that was not read, no
 * line in the 5-year table. Never a 0 for what is unknown.
 */
export function valueOf(r, sort, ok) {
  const p = (r && r.paper) || {}, bt = (r && r.bt) || {};
  const traded = !!ok.paper && paperN(r) > 0;
  switch (sort) {
    case "pnl": return traded ? numOr(p.pnl) : null;
    case "win": return traded ? numOr(p.win_rate) : null;
    case "trades": return ok.paper ? paperN(r) : null;
    case "signals": return ok.signals ? weekSignals(r) : null;
    case "contrib": return numOr(bt.contrib);
    case "fit": return numOr(bt.win);
    case "honest": return numOr(bt.honest_win);
    default: return null;
  }
}
/** A value that says something for ranking: counts of 0 for everyone rank nothing. */
const telling = (v, sort) => v != null && (sort === "trades" || sort === "signals" ? v > 0 : true);

/** Same value: the bigger 5-year contribution first (bt_rank 1 = the biggest), then the code. */
function tie(a, b) {
  return (a.bt_rank ?? 1e9) - (b.bt_rank ?? 1e9) || cmpStr(a.strategy, b.strategy);
}

/**
 * The order of the rows: {ranked: [{r, v, rank}], unranked: [{r, v: null, rank: null}], out: [...]}. ranked = the
 * strategies of the config the bot runs with a value, highest first (rank 1, 2, ...); unranked = those without one (no
 * trade yet, by 5-year contribution); out = strategies traded under an earlier config ("지금 설정 밖", never ranked).
 */
export function rankRows(rows, sort, ok) {
  const all = rows || [];
  const cur = all.filter(inCfg).map((r) => ({r, v: valueOf(r, sort, ok)}));
  const ranked = cur.filter((x) => x.v != null).sort((a, b) => b.v - a.v
    || (sort === "win" ? paperN(b.r) - paperN(a.r) : 0) || tie(a.r, b.r));
  ranked.forEach((x, i) => { x.rank = i + 1; });
  const unranked = cur.filter((x) => x.v == null).sort((a, b) => tie(a.r, b.r)).map((x) => ({...x, rank: null}));
  const out = all.filter((r) => !inCfg(r)).map((r) => ({r, v: valueOf(r, sort, ok), rank: null}))
    .sort((a, b) => (b.v ?? -Infinity) - (a.v ?? -Infinity) || cmpStr(a.r.strategy, b.r.strategy));
  return {ranked, unranked, out};
}

/** The full list's order: ranked, then those without a value, then the ones outside the config. */
export const listOrder = (res) => [...res.ranked, ...res.unranked, ...res.out];

/** The decks: top and bottom k of the ranked rows, or all of them in one deck when there are 2k or fewer. */
export function decks(ranked, k = TOP_N) {
  const xs = ranked || [];
  if (xs.length <= 2 * k) return {all: xs, top: null, bottom: null};
  return {all: null, top: xs.slice(0, k), bottom: xs.slice(-k)};
}

/** Any strategy of the config with a paper trade (the paper database read)? */
export const anyTrades = (d) => sources(d).paper && ((d && d.rows) || []).some((r) => inCfg(r) && paperN(r) > 0);

/**
 * The order to show: the viewer's choice (remembered) or, without one, 페이퍼 손익 once there are paper trades and 5년 기여도
 * before. An order with nothing to rank (no trades yet, no signal this week, a source not read) falls back to 5년 기여도.
 * -> {sort, chosen, fallback, traded, note}: note is the one line that says why the order is the 5-year one (or null).
 */
export function pickSort(choice, d) {
  if (d && d.trend_bot) return pickTrend(choice, d);
  const ok = sources(d), rows = ((d && d.rows) || []).filter(inCfg);
  const has = (s) => rows.some((r) => telling(valueOf(r, s, ok), s));
  const traded = anyTrades(d);
  const chosen = SORT_BY[choice] ? choice : traded ? "pnl" : "contrib";
  const sort = has(chosen) ? chosen : has("contrib") ? "contrib" : chosen;
  const paperWhy = !ok.paper ? (missWord(d && d.paper) === "수집 전" ? "페이퍼 기록이 아직 없어서" : "페이퍼 기록을 못 읽어서") : null;
  let note = null;
  if (sort !== chosen) {
    const what = SORT_BY[chosen].label;
    note = chosen === "pnl" || chosen === "win" || chosen === "trades" ? (paperWhy ? `${paperWhy} 5년 시험 순서예요` : `아직 거래 전이라 5년 시험 순서예요 (${what} 순서는 거래가 생기면)`)
      : chosen === "signals" ? (ok.signals ? "이번 주 신호가 아직 없어서 5년 시험 순서예요" : "신호 기록을 못 읽어서 5년 시험 순서예요")
        : `${what} 숫자가 없어서 5년 시험 순서예요`;
  } else if (sort === "contrib" && !SORT_BY[choice] && !traded) {
    note = paperWhy ? `${paperWhy} 5년 시험 순서예요` : "아직 거래 전이라 5년 시험 순서예요";
  }
  return {sort, chosen, fallback: sort !== chosen, traded, note};
}

/** The trend bot's entry bar -> the closed bar its trend is judged on. */
const TREND_HTF_KO = {"30m": "끝난 1시간봉 추세로 판단", "1h": "끝난 4시간봉 추세로 판단", "4h": "끝난 일봉 추세로 판단"};
/** The orders the trend bot can be ranked by (no 5-year ones: a new rule set has no backtest). */
export const TREND_SORTS = SORTS.filter((x) => ["pnl", "win", "trades", "signals"].includes(x.id));
const TREND_SORT = new Set(TREND_SORTS.map((x) => x.id));
/** The orders a view offers for this answer. */
export const sortsOf = (d) => (d && d.trend_bot ? TREND_SORTS : SORTS);

/** pickSort for the trend bot: 페이퍼 손익 once it has paper trades, 이번 주 신호 before (never a 5-year order); a choice
 *  with nothing to rank falls back to 이번 주 신호, saying why. */
function pickTrend(choice, d) {
  const ok = sources(d), rows = ((d && d.rows) || []).filter(inCfg);
  const has = (s) => rows.some((r) => telling(valueOf(r, s, ok), s));
  const traded = anyTrades(d);
  const chosen = TREND_SORT.has(choice) ? choice : traded ? "pnl" : "signals";
  const sort = has(chosen) ? chosen : has("signals") ? "signals" : chosen;
  const paperWhy = !ok.paper ? (missWord(d && d.paper) === "수집 전" ? "페이퍼 기록이 아직 없어서" : "페이퍼 기록을 못 읽어서") : null;
  let note = null;
  if (sort !== chosen) {
    note = chosen === "signals" ? null : paperWhy ? `${paperWhy} 이번 주 신호 순서예요` : `아직 거래 전이라 이번 주 신호 순서예요 (${SORT_BY[chosen].label} 순서는 거래가 생기면)`;
  } else if (sort === "signals" && !TREND_SORT.has(choice) && !traded) {
    note = paperWhy ? `${paperWhy} 이번 주 신호 순서예요` : "아직 거래 전이라 이번 주 신호 순서예요";
  }
  if (!has(sort)) note = ok.signals ? "이번 주 신호도 거래도 아직 없어서 순위를 낼 수 없어요" : "신호 기록을 못 읽어서 순위를 낼 수 없어요";
  return {sort, chosen, fallback: sort !== chosen, traded, note};
}

/** A ratio as a bar width in percent (0..100, one decimal), or null. */
export function barPct(x) {
  const v = numOr(x);
  return v == null ? null : Math.round(Math.max(0, Math.min(1, v)) * 1000) / 10;
}

/** The card's bars: 5년 승률 (맞춘 숫자), 처음 보는 기간, and 지금 (paper) only when it has trades. */
export function barsOf(r, ok, trend = false) {
  const bt = (r && r.bt) || {}, p = (r && r.paper) || {};
  const out = trend ? [] : [{id: "fit", label: "5년", tip: "5년 승률 (5년 전부에 맞춘 숫자: 좋게 나와요)", v: numOr(bt.win)},
    {id: "honest", label: "처음 보는", tip: "처음 보는 기간 승률 (2020-24에만 맞추고 2025-26에 처음 돌린 숫자: 현실에 가까운 기준)", v: numOr(bt.honest_win)}];
  if (ok.paper && paperN(r) > 0) out.push({id: "now", label: "지금", tip: `지금 승률 (페이퍼 닫힌 거래 ${paperN(r)}번)`, v: numOr(p.win_rate)});
  return out.map((b) => ({...b, w: barPct(b.v)}));
}

/** The head's counts: strategies, settings, how many signalled this week / have paper trades (null when not read). */
export function counts(d) {
  const ok = sources(d), rows = (d && d.rows) || [], cur = rows.filter(inCfg);
  const pw = cur.map((r) => numOr(r.bt && r.bt.per_week)).filter((v) => v != null);
  return {strategies: numOr(d && d.n_strategies) ?? cur.length, settings: numOr(d && d.n_settings),
    signaled: ok.signals ? cur.filter((r) => weekSignals(r) > 0).length : null,
    traded: ok.paper ? cur.filter((r) => paperN(r) > 0).length : null,
    out: rows.filter((r) => !inCfg(r)).length,
    perWeek: pw.length ? pw.reduce((a, b) => a + b, 0) / pw.length : null};
}

/** Search: the code, the Korean name (fmt.stratKo, passed in), the 5-year type. q is lower case. */
export function matches(r, q, ko) {
  const name = String((ko ? ko(r.strategy) : r.strategy) || "").toLowerCase();
  return String(r.strategy || "").toLowerCase().includes(q) || name.includes(q) || String((r.bt && r.bt.type_ko) || "").includes(q);
}

/** The answer without its clock: the same records again draw nothing (an opened line stays open). */
export const sameKey = (d) => (d ? JSON.stringify({...d, now_ms: 0}) : "");

/** A setting's switched-off buckets grouped by kind: [{k: "시각", v: ["06시", "10시"]}, ...] (the server's words, in order). */
export function offGroups(off) {
  const out = [], at = new Map();
  for (const o of off || []) {
    const k = String((o && o.dim_ko) || "").trim(), ko = String((o && o.ko) || "");
    const v = k && ko.startsWith(k + ":") ? ko.slice(k.length + 1).trim() : ko;
    if (!at.has(k)) { at.set(k, {k, v: []}); out.push(at.get(k)); }
    at.get(k).v.push(v);
  }
  return out;
}

/** '왜 이 매매법인가' in one line from the 5-year table (never a guess: parts without a number are left out), or null. */
export function whyLine(r) {
  const bt = r && r.bt;
  if (!bt) return null;
  const parts = [];
  if (bt.type_ko) parts.push(`${bt.type_ko}형`);
  if (numOr(bt.trades) != null) parts.push(`5년 시험 ${fmt.int(bt.trades)}번${numOr(bt.per_week) != null ? ` (1주 ${fmt.num(bt.per_week, 1)}번꼴)` : ""}`);
  if (numOr(bt.contrib) != null) parts.push(`전체가 불어난 몫의 ${fmt.pct(bt.contrib, 1, false)}${r.bt_rank ? ` (${fmt.int(r.bt_rank)}위)` : ""}`);
  if (numOr(bt.honest_win) != null) parts.push(`처음 보는 기간 승률 ${fmt.pct(bt.honest_win, 0, false)}`);
  if (numOr(bt.hours_to_win_median) != null) parts.push(`이길 때는 보통 ${fmt.dur(bt.hours_to_win_median * 3600)} 안에`);
  return parts.length ? parts.join(" · ") : null;
}

/**
 * The big number of a card / the value of a line for an order: {text, unit, tone, sub, fmt: {format, dec, sign} | null}.
 * miss: the words for a source not read ("못 읽음" / "수집 전").
 */
export function bigOf(r, sort, ok, miss = "못 읽음") {
  const v = valueOf(r, sort, ok), p = (r && r.paper) || {}, bt = (r && r.bt) || {}, n = paperN(r);
  const rec = `${fmt.int(n)}번 ${fmt.int(p.wins || 0)}승`;
  switch (sort) {
    case "pnl": {
      if (v == null) return {text: "—", unit: "", tone: "", sub: ok.paper ? "거래 전" : miss, f: null};
      const text = fmt.money(v, true);
      return {text, unit: "USDT", tone: fmt.tone(v, text), sub: rec, f: {dec: 2, sign: true, tone: true}};
    }
    case "win":
      if (v == null) return {text: "—", unit: "", tone: "", sub: ok.paper ? "거래 전" : miss, f: null};
      return {text: fmt.pct(v, 0, false), unit: "", tone: "", sub: `${fmt.int(p.wins || 0)}/${fmt.int(n)}승`, f: {format: "pct", dec: 0, sign: false}};
    case "trades":
      if (v == null) return {text: "—", unit: "", tone: "", sub: miss, f: null};
      return {text: fmt.int(v), unit: "번", tone: "", sub: n ? `${fmt.int(p.wins || 0)}승 ${fmt.int(p.losses || 0)}패` : "거래 전", f: {format: "int"}};
    case "signals": {
      if (v == null) return {text: "—", unit: "", tone: "", sub: miss, f: null};
      const w = (r.sig && r.sig.week) || {};
      return {text: fmt.int(v), unit: "개", tone: "", sub: v ? `진입 ${fmt.int(w.entered || 0)} · 걸러짐 ${fmt.int(w.filtered || 0)}` : "최근 7일 없음", f: {format: "int"}};
    }
    case "contrib":
      if (v == null) return {text: "—", unit: "", tone: "", sub: "5년 줄 없음", f: null};
      return {text: fmt.pct(v, 1, false), unit: "", tone: "", sub: r.bt_rank ? `5년 기여 ${fmt.int(r.bt_rank)}위` : "5년 몫", f: {format: "pct", dec: 1, sign: false}};
    case "fit":
      if (v == null) return {text: "—", unit: "", tone: "", sub: "5년 줄 없음", f: null};
      return {text: fmt.pct(v, 0, false), unit: "", tone: "", sub: `맞춘 숫자 · ${fmt.int(bt.trades)}번`, f: {format: "pct", dec: 0, sign: false}};
    case "honest":
      if (v == null) return {text: "—", unit: "", tone: "", sub: bt.type_ko ? "처음 보는 기간 줄 없음" : "5년 줄 없음", f: null};
      return {text: fmt.pct(v, 0, false), unit: "", tone: "", sub: `2025-26 ${fmt.int(bt.honest_n)}번`, f: {format: "pct", dec: 0, sign: false}};
    default:
      return {text: "—", unit: "", tone: "", sub: "", f: null};
  }
}

// ---------------------------------------------------------------- the view
const pc0 = (x) => (numOr(x) == null ? "—" : fmt.pct(x, 0, false));

function typeBadge(ko, small) {
  if (!ko) return null;
  return h("span", {class: ["lbr-type", small ? "sm" : ""], dataset: {t: TYPE_ID[ko] || "other"}, title: `5년 시험의 유형: ${ko}`}, ko);
}

/** A line opened (rowDetail(row, answer, href)): 왜 이 매매법인가 (the 5-year line and the rule lines when strategies-defs.js has
 *  them), its settings, the 5-year numbers, the paper and live records, its signals. href(name, arg) -> a screen link. */
export function rowDetail(r, d, href) {
  const ok = sources(d), bt = r.bt, code = r.strategy, tb = d && d.trend_bot;
  const sec = (title, ...kids) => h("section", {class: "lbr-dsec"}, h("h4", null, title), ...kids);
  const parts = [];
  const def = DS_DEFS[code], why = tb ? null : whyLine(r);
  const lines = def && def.lines && def.lines.length ? def.lines : null;
  if (lines || why) {
    parts.push(h("section", {class: "lbr-dsec lbr-why"}, h("h4", null, "왜 이 매매법인가"),
      why ? h("p", {class: "lbr-whyl"}, why) : null,
      lines ? h("ul", {class: "lbr-rules", "aria-label": "규칙"}, lines.map((t) => h("li", null, t)))
        : code !== "DOGE" && r.in_config !== false ? h("p", {class: "lbr-ml muted"}, "규칙 글: 매매법 화면 (아래 링크)") : null));
  }
  // settings
  const ms = r.members || [];
  const mrow = (m) => h("li", {class: "lbr-m"},
    h("div", {class: "lbr-mh"}, h("b", {class: "num"}, `#${fmt.int(m.order)}`), h("span", {class: "lbr-tf"}, m.tf_ko || fmt.tfKo(m.tf)),
      h("span", null, tb ? (tb.pullback_wait === false ? "바로 진입" : "되돌림 진입") : m.entry_ko || "즉시"), m.invert ? ui.pill("방향 반대", "warn", "신호와 반대 방향으로 들어가요") : null,
      m.no_chase ? ui.pill("추격 진입 막기", "thin", m.no_chase_ko || "") : null,
      tb ? (m.role ? h("span", {class: "lbr-mbt"}, `역할 ${m.role} · ${TREND_HTF_KO[m.tf] || "상위 봉 추세로 판단"}`) : null)
        : h("span", {class: "lbr-mbt num"}, m.bt && m.bt.trades != null ? `5년 ${fmt.int(m.bt.trades)}번 · ${pc0(m.bt.win)}` : "5년 —")),
    h("p", {class: "lbr-ml"}, h("span", {class: "muted"}, "손절 "), (m.stop && m.stop.ko) || "—"),
    (m.filter || []).length || m.disp ? h("p", {class: "lbr-ml"}, h("span", {class: "muted"}, "조건 "), [...(m.filter || []).map((f) => f.ko), m.disp].filter(Boolean).join(" · ")) : null,
    (m.off || []).length ? h("p", {class: "lbr-ml"}, h("span", {class: "muted"}, "끈 구간 "),
      offGroups(m.off).map((g, i) => [i ? h("span", {class: "muted"}, " / ") : null, g.k ? h("b", null, `${g.k} `) : null, g.v.join("·")])) : null);
  if (ms.length) {
    const first = ms.slice(0, 5), rest = ms.slice(5);
    parts.push(sec(`세팅 ${fmt.int(ms.length)}개`, h("ul", {class: "lbr-ms"}, first.map(mrow)),
      rest.length ? ui.disclosure(`나머지 ${fmt.int(rest.length)}개 보기`, h("ul", {class: "lbr-ms"}, rest.map(mrow))) : null));
  } else if (r.in_config === false) {
    parts.push(sec("세팅", ui.note("지금 설정에는 이 매매법이 없어요: 예전 설정에서 거래한 기록이에요 (순위 밖)")));
  }
  // 5 years (the trend bot: none, said once)
  if (tb) {
    parts.push(sec("백테스트", h("p", {class: "lbr-ml"}, ui.pill("기준 없음", "thin"), ` ${tb.no_ref_ko || "새 규칙이라 비교할 백테스트 기준이 없어요 · 2주 뒤 검토"}`)));
  } else if (bt) {
    const kv = [["유형", bt.type_ko || "—"], ["5년 거래", bt.trades != null ? `${fmt.int(bt.trades)}번 (1주 ${fmt.num(bt.per_week, 1)}번꼴)` : "—"],
      ["5년 승률 (맞춘 숫자)", pc0(bt.win)], ["2025-26 승률", bt.recent_n ? `${pc0(bt.recent_win)} (${fmt.int(bt.recent_n)}번)` : "—"],
      ["처음 보는 기간", bt.honest_n ? `${pc0(bt.honest_win)} (${fmt.int(bt.honest_n)}번)` : "—"],
      ["5년 기여도", bt.contrib != null ? `${fmt.pct(bt.contrib, 1, false)}${r.bt_rank ? ` · ${fmt.int(r.bt_rank)}위` : ""}` : "—"],
      ["이긴 거래 평균 ROE", bt.win_roe_mean != null ? fmt.pct(bt.win_roe_mean, 1) : "—"], ["진 거래 ROE 중간값", bt.loss_roe_median != null ? fmt.pct(bt.loss_roe_median, 1) : "—"],
      ["이기기까지 (중간값)", bt.hours_to_win_median != null ? fmt.dur(bt.hours_to_win_median * 3600) : "—"],
      ["손절까지 (중간값)", bt.hours_to_stop_median != null ? fmt.dur(bt.hours_to_stop_median * 3600) : "—"],
      ["롱 비율", bt.long_share != null ? fmt.pct(bt.long_share, 0, false) : "—"]];
    parts.push(sec("5년 시험", ui.kv(kv)));
  } else {
    parts.push(sec("5년 시험", ok.ref ? ui.note("5년 기준표에 이 매매법 줄이 없어요") : sourceState(d.ref, "5년 기준표")));
  }
  // paper
  const p = r.paper || {};
  const pk = !ok.paper ? [sourceState(d.paper, "페이퍼 DB")] : !paperN(r) ? [ui.note("페이퍼 닫힌 거래가 아직 없어요")]
    : [ui.kv([["닫힌 거래", `${fmt.int(p.n)}번 · ${fmt.int(p.wins)}승 ${fmt.int(p.losses)}패`], ["승률", pc0(p.win_rate)],
      ["순손익", h("b", {class: ["num", fmt.tone(p.pnl, fmt.money(p.pnl))]}, `${fmt.money(p.pnl, true)} USDT`)],
      ["평균 순ROE", p.roe_avg != null ? fmt.pct(p.roe_avg, 1) : "—"], ["마지막 청산", fmt.kst(p.last_exit_ms)]])];
  if (r.open) {
    const o = r.open, roe = numOr(o.last_mark_roe_net);
    pk.push(h("p", {class: "lbr-openl"}, h("i", {"aria-hidden": "true"}), h("b", null, "지금 들고 있음 "), `${fmt.coin(o.symbol)} `, ui.sideTag(o.side),
      ` ${fmt.lev(o.leverage)} · ${fmt.tfKo(o.timeframe)} · ${fmt.kst(o.entry_time)} 진입`,
      roe != null ? h("span", null, " · 마지막 순ROE ", h("b", {class: ["num", fmt.tone(roe, fmt.pct(roe, 1))]}, fmt.pct(roe, 1))) : null,
      o.locked ? " · 잠금" : ""));
  }
  parts.push(sec("페이퍼 (연습 돈)", ...pk));
  // live
  const ex = (d.execs || []);
  parts.push(sec("실거래 (진짜 돈)", ex.length ? h("ul", {class: "lbr-livel"}, ex.map((x) => {
    const rec = (r.live || {})[x.id];
    const name = h("b", null, x.name_ko || x.id);
    if (x.state !== "ok" || !rec) return h("li", null, name, h("span", {class: "muted"}, ` ${missWord(x)}`));
    if (!rec.n) return h("li", null, name, h("span", {class: "muted"}, " 따라간 거래 없음"));
    return h("li", null, name, ` ${fmt.int(rec.n)}번 ${fmt.int(rec.wins)}승 · 손익 `,
      h("b", {class: ["num", fmt.tone(rec.pnl, fmt.money(rec.pnl))]}, `${fmt.money(rec.pnl, true)} USDT`),
      rec.last_exit_ms ? h("span", {class: "muted"}, ` · 마지막 ${fmt.kst(rec.last_exit_ms)}`) : null);
  })) : ui.note("실행기 기록을 받지 못했어요")));
  // signals
  if (!ok.signals) parts.push(sec("신호", sourceState(d.signals, "신호 기록")));
  else {
    const w = (r.sig && r.sig.week) || {}, t = (r.sig && r.sig.today) || {};
    const by = STAGE_KO.filter(([k]) => w[k]).map(([k, ko]) => `${ko} ${fmt.int(w[k])}`).join(" · ");
    parts.push(sec("신호", ui.kv([["최근 7일", `${fmt.int(w.signals || 0)}개${by ? ` (${by})` : ""}`], ["오늘", `${fmt.int(t.signals || 0)}개`],
      ["마지막 신호", r.sig && r.sig.last_ms ? `${fmt.kst(r.sig.last_ms)} · ${r.sig.last_ko || "—"}` : "최근 7일 없음"]])));
  }
  const link = code !== "DOGE" && r.in_config !== false ? h("a", {class: "lbr-more", href: href("strategies", code)}, "매매법 화면에서 차트 · 조건 보기 →") : null;
  return h("div", {class: "lbr-dgrid"}, parts, link);
}

// ---------------------------------------------------------------- 그룹별 성적 (owners 10/19 night: 규칙봇 15's A and B)
// /api/v4/livebots/groups (dash/more/liveinsight.py groups()): per account, group A (the 11 without the chase block) and
// B (the 4 with it) since the 규칙봇 15 start, and 예전 매매법 (settings no longer in the config, their whole record); a
// live trade takes its paper partner's group (짝 페이퍼 없음 when it has none). Shown on 성적 and 순위 (성적 순위).
// The 추세판단 봇 (the answer's kind "trend", liveinsight trend_groups): its roles (눌림 · 자리 · 돌파 · 횡보 · 추세) and entry
// bars (30분 · 1시간 · 4시간 진입) since its own start, in the server's order, each row with its members; the card's words follow the bot.
export const GROUPS_API = "/api/v4/livebots/groups";
const GROUP_KEY = "lbrg-acct";
/** The accounts of the card's switch: the paper, then the executors (execIds: the third, 플립스터, while the server has it). */
const groupAccts = (d) => [{id: "paper", label: "페이퍼"}, ...(d ? execIds(d) : execsNow()).map((id) => ({id, label: acctKo(id)}))];

/** The rows of one account: A, B, 예전 매매법, and 짝 페이퍼 없음 only when it has trades: [{id, ko, sub, n_members, rec}].
 *  The trend bot (d.kind "trend"): the server's order (roles 눌림 · 자리 · 돌파 · 횡보 · 추세, then its entry bars), each row with
 *  its cut (role / tf) and members, then 짝 페이퍼 없음 / 다른 페이퍼 봇 only when they have trades. */
export function groupRows(d, acct) {
  const a = d && d.accts && d.accts[acct];
  if (!a || a.state !== "ok") return [];
  const defs = Object.fromEntries(((d && d.defs) || []).map((g) => [g.id, g]));
  const extra = ["none", ...(d.kind === "trend" ? ["other"] : [])].filter((id) => a.groups[id] && a.groups[id].n);
  const ids = d.kind === "trend" && Array.isArray(d.order) ? [...d.order, ...extra] : ["A", "B", "old", ...extra];
  return ids.map((id) => ({id, ko: (defs[id] || {}).ko || (id === "none" ? "짝 페이퍼 없음" : id), sub: (defs[id] || {}).sub_ko || "",
    n_members: (defs[id] || {}).n_members, cut: (defs[id] || {}).cut || null, members: (defs[id] || {}).members || [],
    rec: a.groups[id] || {n: 0}}));
}

/** A ui.card's subtitle element (its head's span.sub), to change the words in place; null without one. */
export function cardSub(card) {
  const head = card && card.firstChild;
  return head ? Array.from(head.childNodes).find((n) => String(n.className || "") === "sub") || null : null;
}

/** The card's words for the bot running: {sub, note, start}. */
export function groupWords(d) {
  const s = (d && d.start) || {};
  if (d && d.kind === "trend") {
    return {sub: d.title_sub_ko || "역할별 · 진입 봉별", note: d.note_ko || "",
      start: s.ms != null ? `${s.name || "추세판단 봇"} 시작 ${fmt.kst(s.ms)}부터 · ${s.how_ko || ""}` : s.how_ko || "시작 시각 모름"};
  }
  return {sub: "A 그룹 · B 그룹(추격 진입 막기) · 예전 매매법",
    note: "A·B는 규칙봇 15 시작부터, 예전 매매법은 지금 설정에 없는 매매법의 기록 전체예요 · 실거래는 짝 페이퍼 거래의 그룹을 따라요 · 20번 미만은 대부분 운이에요",
    start: s.ms != null ? `${s.name || "규칙봇 15"} 시작 ${fmt.kst(s.ms)}부터 · ${s.how_ko || ""}` : s.how_ko || "시작 시각 모름"};
}

/** groupBlock(ctx, {poll}) -> {el, set(), refresh()}: the card on its own endpoint, the account remembered on this device.
 *  poll (default true): asked every 60 s through ctx.every; false: only when the owner calls refresh() (순위 asks it again
 *  when its own records changed, so the hidden switch view polls nothing extra). */
export function groupBlock(ctx, o = {}) {
  const st = {d: null, okAt: 0, acct: local.get(GROUP_KEY, "paper")};
  if (!["paper", ...EXEC_SLOTS].includes(st.acct)) st.acct = "paper";
  const segOf = (accts) => ui.seg(accts, accts.some((x) => x.id === st.acct) ? st.acct : "paper",
    (id) => { st.acct = id; local.set(GROUP_KEY, id); draw(); }, {label: "계좌 고르기"});
  let segKey = groupAccts(null).map((x) => x.id).join(), seg = segOf(groupAccts(null));
  const stateSlot = h("div", {class: "lb-slot"});
  const head = h("p", {class: "lbrg-start"});
  const rows = h("div", {class: "lbrg-rows", role: "list"});
  const note = ui.note(groupWords(null).note);
  const el = ui.card({title: "그룹별 성적", sub: groupWords(null).sub, cls: "lbrg-card", acts: [seg]}, stateSlot, head, rows, note);
  const sub = cardSub(el);
  const pc = (x) => (numOr(x) == null ? "—" : fmt.pct(x, 1, false));
  function row(g, small) {
    const r = g.rec || {};
    const live = st.acct !== "paper";
    const who = g.members && g.members.length ? g.members.map((m) => `${fmt.stratKo(m.strategy)}${g.cut === "role" ? ` ${fmt.tfKo(m.tf)}` : ""}`).join(" · ") : "";
    return h("div", {class: ["lbrg-row", "g-" + g.id, g.cut ? "c-" + g.cut : ""], role: "listitem"},
      h("span", {class: "lbrg-name"}, h("b", null, g.ko), h("small", null, g.sub + (g.n_members ? ` · ${fmt.int(g.n_members)}개` : "")),
        who ? h("small", {class: "lbrg-who"}, who) : null),
      h("span", {class: "lbrg-v"}, h("small", null, "거래"), h("b", {class: "num"}, `${fmt.int(r.n || 0)}번`)),
      h("span", {class: "lbrg-v"}, h("small", null, "이김"), h("b", {class: "num"}, fmt.int(r.wins || 0))),
      h("span", {class: "lbrg-v"}, h("small", null, "승률"), h("b", {class: "num"}, r.n ? pc(r.win_rate) : "—")),
      h("span", {class: "lbrg-v"}, h("small", null, "순ROE 합"), h("b", {class: ["num", fmt.tone(r.roe_sum, fmt.pct(r.roe_sum, 1))]}, r.n ? fmt.pct(r.roe_sum, 1) : "—")),
      h("span", {class: "lbrg-v"}, h("small", null, live ? "손익 (진짜 돈)" : "손익 (연습)"),
        h("b", {class: ["num", fmt.tone(r.pnl, fmt.money(r.pnl))]}, r.n ? `${fmt.money(r.pnl, true)}` : "—")),
      r.n ? ui.smallSample(r.n, small) : h("span"));
  }
  function draw() {
    const d = st.d;
    const accts = groupAccts(d);
    if (accts.map((x) => x.id).join() !== segKey) {     // the third executor came (or went): its choice too
      segKey = accts.map((x) => x.id).join();
      const nx = segOf(accts);
      seg.replaceWith(nx);
      seg = nx;
    }
    seg.set(st.acct);
    if (!d) { put(rows, motion.shimmer(3)); return; }
    const words = groupWords(d);
    if (sub && sub.textContent !== words.sub) sub.textContent = words.sub;
    put(note, words.note);
    put(head, words.start);
    const a = (d.accts || {})[st.acct];
    if (!a || a.state !== "ok") { put(rows, sourceState(a, st.acct === "paper" ? "페이퍼 DB" : "실행기 DB")); return; }
    put(rows, groupRows(d, st.acct).map((g) => row(g, numOr(d.small_n) || 20)));
  }
  async function load() {
    let d;
    try { d = await ctx.api(GROUPS_API); }
    catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      put(stateSlot, st.d ? ui.staleNote(e, st.okAt, () => load()) : ui.errorBox(e, () => load()));
      ui.dim(rows, !!st.d);
      throw e;
    }
    if (!ctx.alive()) return;
    st.okAt = Date.now();
    put(stateSlot);
    ui.dim(rows, false);
    st.d = d;
    draw();
  }
  draw();
  load().catch(() => {});
  if (o.poll !== false) ctx.every(60 * 1000, () => load().catch(() => {}), {now: false});
  return {el, set() {}, refresh: () => load().catch(() => {})};
}

// ---------------------------------------------------------------- the switch: 진입 가능성 | 성적 순위
export const RANK_MODES = [{id: "likely", label: "진입 가능성"}, {id: "rank", label: "성적 순위"}];
const MODE_KEY = "lb-rank-mode";
const MODE_HINT = {likely: "다음 진입은 어느 매매법일까: 신호가 얼마나 자주 나오는지 (이길 확률 아님)",
  rank: "매매법끼리 성적 비교: 페이퍼 손익 · 승률 · 신호 (5년 숫자는 기준표가 있을 때만)"};
/** A remembered mode, or the default 진입 가능성. */
export const modeOf = (v) => (RANK_MODES.some((m) => m.id === v) ? v : "likely");

/** rankView(ctx) -> {el, set(), show(mode)}: the 순위 tab: the switch, then 진입 가능성 (likelyView) or 성적 순위 (boardView).
 *  show(mode) is what a tap on the switch does (remembered on this device). */
export function rankView(ctx) {
  const st = {mode: modeOf(local.get(MODE_KEY, null)), views: {}, polls: {likely: [], rank: []}};
  const box = h("div", {class: "lbl-modebox"});
  const hint = h("span", {class: "lbl-modehint"});
  const seg = ui.seg(RANK_MODES, st.mode, (id) => show(id, true), {label: "순위 보기"});
  const el = h("div", {class: "lbl-modes stack"}, h("div", {class: "lbl-modebar"}, seg, hint), box);
  // a view's own ctx: its polls run only while it is shown (they are asked once again when it is shown again)
  const sub = (id) => ({...ctx, every: (ms, fn, o) => { st.polls[id].push(fn); return ctx.every(ms, () => (st.mode === id ? fn() : undefined), o); }});
  function show(id, user) {
    st.mode = modeOf(id);
    if (user) local.set(MODE_KEY, st.mode);
    seg.set(st.mode);
    hint.textContent = MODE_HINT[st.mode];
    let v = st.views[st.mode];
    const fresh = !v;
    if (!v) v = st.views[st.mode] = st.mode === "likely" ? likelyView(sub("likely")) : boardView(sub("rank"));
    put(box, v.el);
    if (!fresh) for (const fn of st.polls[st.mode]) { try { const r = fn(); if (r && typeof r.catch === "function") r.catch(() => {}); } catch (e) { /* the view says so */ } }
    if (user) motion.swap(box);
  }
  show(st.mode, false);
  return {el, set() {}, show: (id) => show(id, true)};
}

/** boardView(ctx) -> {el, set()}: 성적 순위, the strategies' record as cards and a list (its own endpoint, every 30 s). */
export function boardView(ctx) {
  const st = {choice: local.get(SORT_KEY, null), d: null, okAt: 0, key: "", names: "", open: new Set(), seen: false, prev: new Map()};
  if (!SORT_BY[st.choice]) st.choice = null;
  const stateSlot = h("div", {class: "lb-slot"});
  const noteSlot = h("div", {class: "lbr-notes"});
  const tiles = h("div", {class: "lbr-tiles"});
  const roster = h("div", {class: "lbr-roster", role: "list", "aria-label": "선수단"});
  const rosterKey = h("p", {class: "lbr-rkey"});
  const hsub = h("span", {class: "lbr-hsub"}, "A+C 합본 · 두 실행기가 따라가는 페이퍼(연습)의 매매법들");
  let selKind = "old";
  const sel = h("select", {class: "select lbr-sel", "aria-label": "순서 고르기"}, SORTS.map((x) => h("option", {value: x.id}, x.label)));
  sel.addEventListener("change", () => { st.choice = sel.value; local.set(SORT_KEY, sel.value); draw(true); });
  const sortNote = h("p", {class: "lbr-snote"});
  const arena = h("div", {class: "lbr-arena-body"});
  const list = ui.searchList({items: undefined, size: 10, placeholder: "매매법 찾기 (이름 · 코드 · 유형)",
    row: (x) => listRow(x), match: (x, q) => matches(x.r, q, fmt.stratKo), empty: "맞는 매매법이 없어요"});
  const listCount = h("span", {class: "lbr-lcount"});
  const foot = h("div", {class: "lbr-foot"});
  const grp = groupBlock(ctx, {poll: false});              // asked again only when this view's records change (load)
  const listCard = ui.card({title: "전체 목록", sub: "줄을 누르면 세팅 · 5년 숫자 · 실거래 · 신호가 펼쳐져요", cls: "lbr-listcard", acts: [listCount]}, list.el);
  const body = h("div", {class: "lbr-body stack"},
    h("section", {class: "lbr-hero", "aria-label": "매매법 순위 요약"},
      h("div", {class: "lbr-hhead"}, ui.plate("매매법 순위"), hsub),
      noteSlot, tiles,
      h("div", {class: "lbr-rhead"}, h("b", null, "선수단"), rosterKey), roster),
    h("section", {class: "lbr-arena", "aria-label": "상위 · 하위"},
      h("div", {class: "lbr-ahead"}, h("div", {class: "lbr-atitle"}, h("h2", null, "순위"), sortNote),
        h("label", {class: "lbr-sort"}, h("span", null, "순서"), sel)),
      arena),
    grp.el,
    listCard,
    foot);
  const el = h("div", {class: "lbr stack"}, stateSlot, body);
  const listSub = cardSub(listCard);

  /** The words that depend on the bot running: the hero line, the list's subtitle, the orders offered. */
  function botWords(d) {
    const tb = d && d.trend_bot;
    const hs = tb ? `${tb.name || "추세판단 봇"} · ${followKo()} 페이퍼(연습)의 매매법 · ${fmt.kst(tb.since)} 시작부터`
      : `A+C 합본 · ${followKo()} 페이퍼(연습)의 매매법들`;
    if (hsub.textContent !== hs) hsub.textContent = hs;
    const ls = tb ? "줄을 누르면 세팅 · 역할 · 실거래 · 신호가 펼쳐져요" : "줄을 누르면 세팅 · 5년 숫자 · 실거래 · 신호가 펼쳐져요";
    if (listSub && listSub.textContent !== ls) listSub.textContent = ls;
    const kind = tb ? "trend" : "old";
    if (kind !== selKind) {
      selKind = kind;
      sel.replaceChildren(...sortsOf(d).map((x) => h("option", {value: x.id}, x.label)));
    }
  }

  // ---------------------------------------------------------------- pieces
  function tile(k, v, sub, cls) {
    return h("div", {class: ["lbr-tile", cls]}, h("span", {class: "lbr-tk"}, k), v instanceof Node ? v : h("b", {class: "lbr-tv num"}, v), sub ? h("span", {class: "lbr-ts"}, sub) : null);
  }
  function frac(n, of) {
    return h("b", {class: "lbr-tv num"}, fmt.int(n), h("small", null, ` / ${fmt.int(of)}`));
  }
  function posTile(d, ok, by) {
    if (!ok.paper) return tile("지금 포지션", missWord(d.paper), "페이퍼 DB", "lbr-tpos");
    const o = d.open;
    if (!o) return tile("지금 포지션", "없음", "들고 있는 포지션이 없어요 · 신호를 기다려요", "lbr-tpos");
    const r = by[o.strategy_id] || {}, ro = r.open || {}, ko = fmt.stratKo(o.strategy_id);
    const roe = numOr(ro.last_mark_roe_net);
    return h("button", {type: "button", class: "lbr-tile lbr-tpos on", style: {"--h": stratHue(o.strategy_id) ?? 210}, onclick: () => jump(o.strategy_id),
      title: `${ko} (${o.strategy_id}) 줄 펼치기`},
    h("span", {class: "lbr-tk"}, h("i", {class: "lbr-live", "aria-hidden": "true"}), "지금 포지션"),
    h("span", {class: "lbr-tpm"}, stratFigure({strategy: o.strategy_id, size: 34, cls: "lbr-tfig"}),
      h("span", {class: "lbr-tpn"}, h("b", null, ko),
        h("span", {class: "lbr-tpl"}, h("b", null, fmt.coin(o.symbol)), " ", ui.sideTag(o.side), ` ${fmt.tfKo(o.timeframe)}`,
          ro.leverage ? ` · ${fmt.lev(ro.leverage)}` : ""))),
    h("span", {class: "lbr-ts"}, `${fmt.kst(o.entry_time)} 진입`,
      roe != null ? h("span", null, " · 마지막 순ROE ", h("b", {class: ["num", fmt.tone(roe, fmt.pct(roe, 1))]}, fmt.pct(roe, 1))) : null,
      ro.locked ? h("span", null, " · 잠금") : null));
  }
  function statusChip(r, d, ok, n) {
    const s = r.status && r.status.status;
    if (!ok.card || !s || !n) return null;
    const words = (d.scorecard && d.scorecard.words) || [];
    if (s === words[0] && n < smallMin(d)) return null;            // 표본 작음: the 표본 적음 chip says it already
    return ui.pill(s, toneOf(words, s), "성적 탭 매매법 성적표의 상태 말 (5년 기준과 비교)");
  }
  const smallMin = (d) => numOr(((d && d.small) || [])[0]) || 20;
  function chips(r, d, ok, o = {}) {
    const n = paperN(r);
    return [
      r.in_config === false ? ui.pill("지금 설정 밖", "thin", "예전 설정에서 거래했어요: 지금 봇은 이 매매법을 쓰지 않아요 (순위 밖)") : null,
      r.open ? h("span", {class: "lbr-holdchip", title: "페이퍼가 지금 이 매매법으로 포지션을 들고 있어요"}, h("i", {"aria-hidden": "true"}),
        `지금 들고 있음 · ${fmt.coin(r.open.symbol)} ${fmt.sideKo(r.open.side)}`) : null,
      o.status === false ? null : statusChip(r, d, ok, n),
      ok.paper && !n ? ui.pill("거래 전", "thin", "페이퍼 닫힌 거래가 아직 없어요") : null,
      ok.paper && n ? ui.smallSample(n, smallMin(d)) : null,
    ];
  }
  function bigNum(x, sort, ok, d, cls) {
    const r = x.r, b = bigOf(r, sort, ok, missWord(sort === "signals" ? d.signals : d.paper));
    const key = `${sort}|${r.strategy}`, v = valueOf(r, sort, ok);
    let n;
    if (b.f && v != null) {
      n = ui.numFrom(st.prev.has(key) ? st.prev.get(key) : null, v, {...b.f, cls});
    } else n = h("b", {class: ["num", cls]}, b.text);
    st.prev.set(key, v);
    return {n, b};
  }

  /** One 선수 카드. */
  function playerCard(x, sort, ok, d, i, enter) {
    const r = x.r, code = r.strategy, ko = fmt.stratKo(code), bt = r.bt || {};
    const {n: big, b} = bigNum(x, sort, ok, d, "lbr-bigv");
    const sg = ok.signals ? weekSignals(r) : null;
    const be = numOr(d.ref && d.ref.break_even);
    const tb = d.trend_bot;
    const bars = barsOf(r, ok, !!tb);
    const card = h("div", {class: ["lbr-card", r.open ? "lbr-hold" : "", enter ? "lbr-enter" : "", x.rank <= 3 ? "lbr-podium" : ""], role: "button", tabindex: "0",
      style: {"--h": stratHue(code) ?? 210, "--i": i}, dataset: {code, t: TYPE_ID[bt.type_ko] || "other"},
      "aria-label": `${fmt.int(x.rank)}위 ${ko} · ${SORT_BY[sort].big} ${b.text}${b.unit ? " " + b.unit : ""}${r.open ? " · 지금 포지션을 들고 있음" : ""} · 눌러서 목록에서 펼치기`,
      onclick: () => jump(code), onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); jump(code); } }},
    h("div", {class: "lbr-ctop"},
      h("span", {class: "lbr-jersey num", "aria-hidden": "true"}, fmt.int(x.rank), h("small", null, "위")),
      h("span", {class: "lbr-ctags"}, tb ? (r.role ? ui.pill(r.role, "thin", "추세판단 봇에서 이 매매법의 역할") : null) : typeBadge(bt.type_ko),
        statusChip(r, d, ok, paperN(r)))),
    h("div", {class: "lbr-figwrap", "aria-hidden": "true"}, h("span", {class: "lbr-ring"}), stratFigure({strategy: code, size: 56, cls: "lbr-fig"})),
    h("div", {class: "lbr-cname"}, h("b", {title: ko}, ko), ko !== code ? h("code", null, code) : null),
    h("div", {class: "lbr-tfs"}, (r.tfs || []).map((tf) => h("span", {class: "lbr-tf"}, fmt.tfKo(tf))),
      r.n_settings ? h("span", {class: "lbr-nset"}, `세팅 ${fmt.int(r.n_settings)}`) : null),
    h("div", {class: "lbr-big"}, h("span", {class: "lbr-bigk"}, SORT_BY[sort].big),
      h("span", {class: "lbr-bigrow"}, big, b.unit ? h("small", {class: "lbr-bigu"}, b.unit) : null), h("span", {class: "lbr-bigs"}, b.sub)),
    tb && !bars.length ? h("p", {class: "lbr-nobar"}, "닫힌 거래가 생기면 승률 막대가 그려져요") : null,
    bars.length ? h("div", {class: "lbr-bars", "aria-label": "승률 막대 (0~100%)"}, bars.map((bar) =>
      h("div", {class: ["lbr-bar", bar.id], title: bar.tip, "aria-label": `${bar.tip}: ${pc0(bar.v)}`},
        h("span", {class: "lbr-barl"}, bar.label),
        h("span", {class: "lbr-bart"}, bar.w != null ? h("i", {style: {width: bar.w + "%"}}) : null,
          be != null ? h("em", {class: "lbr-be", style: {left: barPct(be) + "%"}, "aria-hidden": "true"}) : null),
        h("b", {class: "lbr-barv num"}, pc0(bar.v))))) : null,
    h("div", {class: "lbr-cfoot"},
      h("span", {class: "lbr-sig", title: "최근 7일(한국 시간) 이 매매법이 낸 신호"}, "이번 주 신호 ", h("b", {class: "num"}, sg == null ? "—" : fmt.int(sg))),
      sort !== "pnl" && ok.paper && paperN(r) ? h("span", {class: "lbr-sig"}, "손익 ", h("b", {class: ["num", fmt.tone(r.paper.pnl, fmt.money(r.paper.pnl))]}, fmt.money(r.paper.pnl, true))) : null,
      tb ? null
        : sort === "pnl" || !ok.paper || !paperN(r) ? h("span", {class: "lbr-sig"}, "5년 ", h("b", {class: "num"}, bt.trades != null ? `${fmt.int(bt.trades)}번` : "—")) : null),
    h("div", {class: "lbr-chips"}, chips(r, d, ok, {status: false})));
    return card;
  }

  function deckEl(title, sub, xs, sort, ok, d, enter, cls) {
    return h("div", {class: ["lbr-deckw", cls]},
      h("div", {class: "lbr-dhead"}, h("b", null, title), h("span", null, sub)),
      h("div", {class: "lbr-deck", role: "list"}, xs.map((x, i) => h("div", {role: "listitem", class: "lbr-slotc"}, playerCard(x, sort, ok, d, i, enter)))));
  }

  /** One line of the full list (a button that opens its detail in place). */
  function listRow(x) {
    const d = st.d, ok = sources(d), r = x.r, code = r.strategy, ko = fmt.stratKo(code), sort = st.sort;
    const open = st.open.has(code);
    const b = bigOf(r, sort, ok, missWord(sort === "signals" ? d.signals : d.paper));
    const n = paperN(r), p = r.paper || {};
    const words = [];
    if (r.tfs && r.tfs.length) words.push(r.tfs.map(fmt.tfKo).join("·"));
    if (r.n_settings) words.push(`세팅 ${fmt.int(r.n_settings)}`);
    if (ok.paper) words.push(n ? `페이퍼 ${fmt.int(n)}번 ${fmt.int(p.wins || 0)}승` : "페이퍼 거래 전");
    if (ok.signals) words.push(`이번 주 신호 ${fmt.int(weekSignals(r))}`);
    const region = h("div", {class: "lbr-detail", hidden: !open}, open ? detail(r) : null);
    const head = h("button", {type: "button", class: "lbr-lhead", "aria-expanded": String(open), onclick: () => {
      const on = !st.open.has(code);
      if (on) st.open.add(code); else st.open.delete(code);
      head.setAttribute("aria-expanded", String(on));
      if (on && !region.childNodes.length) put(region, detail(r));
      motion.expand(region, on);
    }},
    h("span", {class: "lbr-lrk num"}, x.rank == null ? "—" : fmt.int(x.rank)),
    stratFigure({strategy: code, size: 28, cls: "lbr-lfig"}),
    h("span", {class: "lbr-lname"}, h("b", null, ko), ko !== code ? h("code", null, code) : null,
      d.trend_bot ? (r.role ? ui.pill(r.role, "thin", "추세판단 봇에서 이 매매법의 역할") : null) : typeBadge(r.bt && r.bt.type_ko, true)),
    h("span", {class: "lbr-lval"}, h("b", {class: ["num", b.tone]}, b.text, b.unit ? h("small", null, ` ${b.unit}`) : null), h("small", {class: "lbr-lvk"}, SORT_BY[sort].big)),
    h("span", {class: "lbr-lmeta"}, words.map((w, i) => h("span", {class: ["lbr-lw", i === words.length - 1 ? "end" : ""]}, w)), chips(r, d, ok)),
    h("span", {class: "lbr-chev", "aria-hidden": "true"}, "▾"));
    return h("div", {class: ["lbr-lrow", r.in_config === false ? "lbr-out" : "", r.open ? "lbr-hold" : ""], role: "listitem", dataset: {code}}, head, region);
  }

  const detail = (r) => rowDetail(r, st.d, (n, x) => ctx.href(n, x));

  function jump(code) {
    st.open.add(code);
    list.input.value = code;
    list.input.dispatchEvent(new Event("input"));
    requestAnimationFrame(() => {
      const row = list.el.querySelector(`[data-code="${code.replace(/[^A-Za-z0-9_]/g, "")}"]`);
      if (row && row.scrollIntoView) row.scrollIntoView({behavior: motion.reduced() ? "auto" : "smooth", block: "start"});
      const b = row && row.querySelector(".lbr-lhead");
      if (b) b.focus({preventScroll: true});
    });
  }

  // ---------------------------------------------------------------- drawing
  function drawLoading() {
    put(tiles, motion.shimmer(2, true));
    put(roster);
    put(arena, motion.shimmer(4, true));            // the list shimmers by itself until its first set()
  }
  function draw(user) {
    const d = st.d;
    if (!d) { drawLoading(); return; }
    botWords(d);
    if (!d.combo || d.combo.state !== "ok") {
      put(noteSlot, sourceState(d.combo, "합친 봇 설정"));
      put(tiles); put(roster); put(rosterKey); put(sortNote);
      put(arena, ui.empty("합친 봇 설정을 읽어야 매매법 순위를 만들 수 있어요"));
      list.set([]); put(listCount); put(foot, footEls(d));
      return;
    }
    const ok = sources(d), pick = pickSort(st.choice, d);
    st.sort = pick.sort;
    sel.value = pick.sort;
    const res = rankRows(d.rows, pick.sort, ok);
    const by = Object.fromEntries((d.rows || []).map((r) => [r.strategy, r]));
    const c = counts(d);
    // notes: the sources not read, the scorecard's own problems
    const tb = d.trend_bot;
    put(noteSlot, !ok.paper ? sourceState(d.paper, "페이퍼 DB (거래 · 포지션)") : null, !ok.signals ? sourceState(d.signals, "신호 기록") : null,
      tb ? h("p", {class: "lbr-noref"}, ui.pill("기준 없음", "thin"), ` ${tb.no_ref_ko || "새 규칙이라 비교할 백테스트 기준이 없어요 · 2주 뒤 검토"}`,
        h("span", {class: "muted"}, ` · 숫자는 모두 ${fmt.kst(tb.since)} 시작부터의 이 봇 거래예요`))
        : !ok.ref ? sourceState(d.ref, "5년 기준표") : null,
      ...((ok.card && d.scorecard.problems) || []).map((t) => h("p", {class: "lb-warn"}, t)),
      d.paper && d.paper.stale ? h("p", {class: "lb-warn"}, `페이퍼 봇 기록이 멈춰 있어요 (마지막 ${fmt.kst(d.paper.as_of_ms)})`) : null);
    put(tiles,
      tile("매매법 · 세팅", h("b", {class: "lbr-tv num"}, fmt.int(c.strategies), h("small", null, ` · 세팅 ${c.settings == null ? "—" : fmt.int(c.settings)}`)),
        c.perWeek != null ? `한 매매법이 1주 ${fmt.num(c.perWeek, 1)}번꼴 (5년 평균)` : "합친 봇이 지금 쓰는 설정"),
      tile("이번 주 신호를 낸 매매법", c.signaled == null ? missWord(d.signals) : frac(c.signaled, c.strategies), "최근 7일 · 한국 시간"),
      tile("페이퍼 거래가 있는 매매법", c.traded == null ? missWord(d.paper) : frac(c.traded, c.strategies),
        c.out ? `지금 설정 밖 ${fmt.int(c.out)}개는 따로` : c.traded === 0 ? "아직 거래 전" : "닫힌 거래 기준"),
      posTile(d, ok, by));
    // roster: everyone in the config in the order shown
    const order = [...res.ranked, ...res.unranked];
    put(roster, order.map((x) => {
      const r = x.r, lit = ok.signals && weekSignals(r) > 0, ko = fmt.stratKo(r.strategy);
      return h("button", {type: "button", role: "listitem", class: ["lbr-player", lit ? "lit" : "", r.open ? "hold" : ""],
        style: {"--h": stratHue(r.strategy) ?? 210}, dataset: {t: TYPE_ID[(r.bt || {}).type_ko] || "other"}, onclick: () => jump(r.strategy),
        title: `${x.rank ? fmt.int(x.rank) + "위 · " : ""}${ko} · 이번 주 신호 ${ok.signals ? fmt.int(weekSignals(r)) : "—"}${r.open ? " · 지금 포지션" : ""}`,
        "aria-label": `${ko} 줄 펼치기`},
      stratFigure({strategy: r.strategy, size: 26, cls: "lbr-pfig"}));
    }));
    put(rosterKey, h("span", null, h("i", {class: "k lit"}), "이번 주 신호를 냄"), h("span", null, h("i", {class: "k"}), "신호 없음"),
      h("span", null, h("i", {class: "k hold"}), "지금 포지션"), h("span", {class: "muted"}, "· 누르면 아래 목록에서 펼쳐져요"));
    // decks
    put(sortNote, pick.note ? h("b", {class: "lbr-fall"}, pick.note) : null, h("span", null, SORT_BY[pick.sort].desc));
    const dk = decks(res.ranked);
    const enter = !st.seen;
    st.seen = true;
    const waiting = res.unranked.length ? h("p", {class: "lbr-wait"}, `${SORT_BY[pick.sort].label} 숫자가 없는 매매법 ${fmt.int(res.unranked.length)}개는 순위 밖 (아래 목록 끝에)`) : null;
    if (!res.ranked.length) put(arena, ui.empty("순위를 낼 숫자가 아직 없어요"), waiting);
    else if (dk.all) put(arena, deckEl(`전체 ${fmt.int(dk.all.length)}개`, SORT_BY[pick.sort].label + " 순", dk.all, pick.sort, ok, d, enter, "lbr-all"), waiting);
    else {
      put(arena, deckEl("상위 5", `${fmt.int(res.ranked.length)}개 중`, dk.top, pick.sort, ok, d, enter, "lbr-top"),
        deckEl("하위 5", `${fmt.int(res.ranked.length - TOP_N + 1)}~${fmt.int(res.ranked.length)}위`, dk.bottom, pick.sort, ok, d, enter, "lbr-bottom"), waiting);
    }
    if (user) motion.swap(arena);
    const items = listOrder(res);
    list.set(items, !user);
    put(listCount, `${fmt.int(res.ranked.length + res.unranked.length)}개${res.out.length ? ` + 설정 밖 ${fmt.int(res.out.length)}개` : ""}`);
    put(foot, footEls(d, c));
    st.names = namesKey(d);
  }
  function footEls(d, c) {
    const be = numOr(d && d.ref && d.ref.break_even);
    const tb = d && d.trend_bot;
    if (tb) {
      return [ui.card({title: "읽는 법", cls: "lbr-how"},
        h("ul", {class: "lbr-howl"},
          h("li", null, h("b", null, "백테스트 숫자가 없어요."), ` ${tb.no_ref_ko || "새 규칙이라 비교할 백테스트 기준이 없어요 · 2주 뒤 검토"}. 순위는 이 봇이 ${fmt.kst(tb.since)}에 켜진 뒤의 기록으로만 매겨요.`),
          h("li", null, h("b", null, "거래가 적으면 순위는 대부분 운이에요."),
            ` 추세 판단·진입 전 검사${tb.pullback_wait === false ? "를" : "·되돌림을"} 다 통과해야 들어가서 거래가 드물어요. 닫힌 거래 ${fmt.int(smallMin(d))}번 미만은 '표본 적음'이에요.`),
          h("li", null, h("b", null, "역할"), " = 눌림 · 자리 · 돌파 · 횡보 · 추세 (두 분이 정한 이름). 30분 진입은 끝난 1시간봉, 1시간 진입은 끝난 4시간봉, 4시간 진입은 끝난 일봉 추세를 따라요."
            + (tb.hold_entry ? " 보류여도 반대 방향만 아니면 들어가요." : "")),
          h("li", null, h("b", null, "페이퍼 = 연습 돈, 실거래 = 진짜 돈."), ` 순위는 ${followKo()} 페이퍼(모의) 거래로 매겨요. ${execsKo()} 기록은 줄을 펼치면 보여요${liveOnlyKo()}.`),
          h("li", null, "막대: ", h("span", {class: "lbr-key now"}), "지금 승률(페이퍼, 거래가 있을 때) · 0~100%"))),
      h("div", {class: "lb-foot"}, ui.assumeLine(["closed", "open"], "페이퍼(연습 돈) 손익 · 순ROE"), ui.assumeLive(`${execsKo()} (펼친 줄의 실거래)`))];
    }
    return [ui.card({title: "읽는 법", cls: "lbr-how"},
      h("ul", {class: "lbr-howl"},
        h("li", null, h("b", null, "5년 승률은 맞춘 숫자예요."), " 5년 전부에 맞춰 고른 숫자라 실제보다 좋게 나와요. 현실에 가까운 기준은 ",
          h("b", null, "처음 보는 기간"), " 승률이에요 (2020-24에만 맞추고 2025-26에 처음 돌려 본 숫자)."),
        h("li", null, h("b", null, "거래가 적으면 순위는 대부분 운이에요."),
          ` 매매법이 ${c ? fmt.int(c.strategies) : "여러"}개라 하나가 1주에 ${c && c.perWeek != null ? fmt.num(c.perWeek, 1) + "번꼴" : "1번도 안 되게"} 거래해요 (5년 평균). 닫힌 거래 ${fmt.int(smallMin(d))}번 미만은 '표본 적음'이에요.`),
        h("li", null, h("b", null, "페이퍼 = 연습 돈, 실거래 = 진짜 돈."), ` 순위는 ${followKo()} 페이퍼(모의) 거래로 매겨요. ${execsKo()} 기록은 줄을 펼치면 보여요${liveOnlyKo()}.`),
        h("li", null, "5년 기여도 = 5년 시험에서 전체가 불어난 몫 중 이 매매법이 낸 몫. 같은 숫자면 5년 기여도가 큰 쪽이 먼저예요."),
        h("li", null, "막대: ", h("span", {class: "lbr-key fit"}), "5년(맞춘 숫자) · ", h("span", {class: "lbr-key honest"}), "처음 보는 기간 · ",
          h("span", {class: "lbr-key now"}), "지금(페이퍼, 거래가 있을 때) · 0~100%", be != null ? `, 세로 줄 = 본전 승률 약 ${fmt.pct(be, 0, false)}` : ""),
        d && sources(d).card ? h("li", null, "상태 말(표본 작음 · 기대 안 · 주의 · 확실히 나쁨)은 성적 탭의 매매법 성적표와 같은 계산이에요.") : null)),
    h("div", {class: "lb-foot"}, ui.assumeLine(["closed", "open"], "페이퍼(연습 돈) 손익 · 순ROE"), ui.assumeLive(`${execsKo()} (펼친 줄의 실거래)`))];
  }
  const namesKey = (d) => ((d && d.rows) || []).map((r) => fmt.stratKo(r.strategy)).join("|");

  async function load() {
    let d;
    try { d = await ctx.api(API); }
    catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      put(stateSlot, st.d ? ui.staleNote(e, st.okAt, () => load()) : ui.errorBox(e, () => load()));
      ui.dim(body, !!st.d);
      if (!st.d) body.hidden = true;
      throw e;
    }
    if (!ctx.alive()) return;
    put(stateSlot);
    ui.dim(body, false);
    body.hidden = false;
    st.okAt = Date.now();
    const key = sameKey(d);
    if (key === st.key) return;                             // the same records again: nothing redrawn (an open line stays open)
    const first = !st.key;
    st.key = key; st.d = d;
    draw(false);
    if (!first) grp.refresh();                              // new records: the groups' numbers too (the first read is its own)
  }
  draw(false);
  load().catch(() => {});
  ctx.every(REFRESH_MS, () => load().catch(() => {}), {now: false});
  // the strategies' Korean names come with the board (core/store.js): draw again once they arrive or change
  if (ctx.watch) ctx.watch("board", () => { if (st.d && namesKey(st.d) !== st.names) draw(false); });
  return {el, set() {}};
}

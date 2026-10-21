// 실거래 › 일정 (#/livebots/cal; owners 10/19: "경제뉴스 뜨는거나 예정 이런것도 중요할꺼 같은데"). When the combined bot
// (the paper bot both executors follow) takes no new entry by its own two rules, and the US macro releases behind them:
//   지금      entries allowed now or not, a live countdown (every second, on the server's clock) to the end of the pause
//             or to the next one, the rules in plain words (an open position keeps running, the exchange stop guards it)
//   7일 띠    one row per Korea-time day: a 24 h bar with the pause blocks (weekend striped, a release amber) and now
//   발표 카드  the releases of the next 21 days (the last 3 days dimmed): time, what it is, D-day, its pause, the official page
//   등록 범위  the release file (data/macro_events.csv, the same file the bot reads) must be filled ahead: an amber warning
//   시장 숫자  /api/market's fear & greed, dominance, market cap and US indexes (outside data; a failure says so, never 0)
// /api/v4/livebots/calendar (dash/more/livebots.py calendar), every 60 s; the countdown ticks every second in between.
// HONESTY: the bots' own two rules only (a signal, the light and an open position decide the rest, the page says so);
// there is no news feed (the page says so, nothing outside is fetched from the browser); the page changes nothing.
import {h, s, put, ui, fmt, motion, serverNow} from "../core/pb.js";
import {sourceState} from "./livebots-kit.js";

export const API = "/api/v4/livebots/calendar";
const MARKET = "/api/market";
const REFRESH_MS = 60 * 1000;
const MARKET_MS = 5 * 60 * 1000;           // the server keeps the outside numbers 5 minutes (fear & greed 30)
const TICK_MS = 1000;
const MIN = 60 * 1000, HOUR = 60 * MIN, DAY = 24 * HOUR, KST = 9 * HOUR;
const SKEW_MS = 15 * 1000;                  // an answer this far from the page's server clock comes from another clock
const MAX_CARDS = 20;
const WD = ["일", "월", "화", "수", "목", "금", "토"];
export const NEWS_KO = "뉴스는 아직 연결하지 않았어요 · 봇은 뉴스를 보지 않고 위 일정만 지켜요";

// ---------------------------------------------------------------- pure: time words (Korea time), no DOM
const ok = (x) => x != null && x !== "" && typeof x !== "boolean" && Number.isFinite(Number(x));
const two = (n) => String(n).padStart(2, "0");
const round4 = (x) => Math.round(Number(x) * 10000) / 10000;     // a share for a CSS custom property
const kday = (ms) => Math.floor((Number(ms) + KST) / DAY);
function kparts(ms) {
  const d = new Date(Number(ms) + KST);
  return {y: d.getUTCFullYear(), mo: d.getUTCMonth() + 1, d: d.getUTCDate(), wd: d.getUTCDay()};
}
/** "월" (the Korea-time weekday). */
export const wdKo = (ms) => WD[kparts(ms).wd];
/** "10/29 (목)". */
export const dayKo = (ms) => (ok(ms) ? `${fmt.mmdd(ms)} (${wdKo(ms)})` : "—");
/** Saturday or Sunday in Korea time (the bot's weekend). */
export const isWeekendDay = (ms) => { const w = kparts(ms).wd; return w === 0 || w === 6; };
/** "10/29 (목) 02:30~03:30" in one day, "10/24 (토) 00:00 ~ 10/26 (월) 00:00" across days. */
export function rangeKo(from, to) {
  if (!ok(from) || !ok(to)) return "—";
  return kday(from) === kday(to) ? `${dayKo(from)} ${fmt.hm(from)}~${fmt.hm(to)}`
    : `${dayKo(from)} ${fmt.hm(from)} ~ ${dayKo(to)} ${fmt.hm(to)}`;
}
/** A countdown's parts, whole seconds rounded up (00:00:00 only when it is over): {d, h, m, s}. */
export function clockParts(ms) {
  const t = Math.max(0, Math.ceil(Number(ms) / 1000)) || 0;
  return {d: Math.floor(t / 86400), h: Math.floor((t % 86400) / 3600), m: Math.floor((t % 3600) / 60), s: t % 60};
}
/** "1일 03:12:05" / "03:12:05" (a countdown, seconds rounded up). */
export function clockKo(ms) {
  if (!ok(ms)) return "—";
  const p = clockParts(ms);
  return `${p.d ? `${p.d}일 ` : ""}${two(p.h)}:${two(p.m)}:${two(p.s)}`;
}
/** A length of time in words, minutes rounded up: "4일 9시간" / "3시간 12분" / "12분" / "40초". */
export function durKo(ms) {
  if (!ok(ms)) return "—";
  const v = Math.max(0, Number(ms));
  if (v < MIN) return `${Math.max(1, Math.ceil(v / 1000))}초`;
  const m = Math.ceil(v / MIN);
  if (m < 60) return `${m}분`;
  const d = Math.floor(m / 1440), hh = Math.floor((m % 1440) / 60), mm = m % 60;
  if (d) return hh ? `${d}일 ${hh}시간` : `${d}일`;
  return mm ? `${hh}시간 ${mm}분` : `${hh}시간`;
}
/** A release's countdown: "12분 뒤" / "3시간 12분 뒤" within a day, then "D-3" (Korea-time days), "지남" once past. */
export function untilKo(ts, now) {
  const dt = Number(ts) - Number(now);
  if (!ok(ts) || !ok(now)) return "—";
  if (dt <= 0) return "지남";
  if (dt < DAY) return `${durKo(dt)} 뒤`;
  return `D-${kday(ts) - kday(now)}`;
}
/** "오늘" / "내일" / "모레" / null (a release's day against today, Korea time). */
export function relDay(ts, now) {
  const n = kday(ts) - kday(now);
  return n === 0 ? "오늘" : n === 1 ? "내일" : n === 2 ? "모레" : n === -1 ? "어제" : null;
}
/** Where a release is now (the server's `when`, worked out again for the ticking page): past / now / soon / later. */
export function whenAt(it, now) {
  const a = ok(it.pause_from) ? Number(it.pause_from) : Number(it.ts), b = ok(it.pause_to) ? Number(it.pause_to) : Number(it.ts);
  if (b < now) return "past";
  if (a <= now) return "now";
  return Number(it.ts) <= now + DAY ? "soon" : "later";
}
/** A release's pause in words: "21:00~22:00 진입 쉼" / "주말이라 원래 쉼" / no window in the config. */
export function pauseKo(it, rules) {
  if (rules && rules.no_weekend && it.weekend) return "주말이라 원래 쉼";
  if (!ok(it.pause_from) || !ok(it.pause_to)) return "발표 앞뒤에 쉬지 않음 (봇 설정)";
  return `${fmt.hm(it.pause_from)}~${fmt.hm(it.pause_to)} 진입 쉼`;
}

// ---------------------------------------------------------------- pure: pause windows
/** Pause windows merged where they overlap or touch: [{from, to, parts: [span...]}], earliest first. */
export function mergeSpans(spans) {
  const xs = (spans || []).filter((x) => x && ok(x.from) && ok(x.to) && Number(x.to) > Number(x.from))
    .slice().sort((a, b) => a.from - b.from || a.to - b.to);
  const out = [];
  for (const x of xs) {
    const m = out[out.length - 1];
    if (m && x.from <= m.to) { m.to = Math.max(m.to, x.to); m.parts.push(x); } else out.push({from: x.from, to: x.to, parts: [x]});
  }
  return out;
}
/** One pause window in words. long: the hero's reason ("CPI 발표(21:30) 앞뒤 30분"), else short ("주말"). */
export function partKo(p, d, long = false) {
  if (p.why === "weekend") return long ? "주말(토요일 0시 ~ 월요일 0시, 한국 시간)" : "주말";
  const mins = d && d.rules ? d.rules.macro_blackout_min : null;
  const it = ((d && d.items) || []).find((x) => x.kind === p.kind && x.pause_from === p.from);
  const name = it ? it.kind_ko : p.kind || "경제 발표";
  if (!it || !mins) return p.ko || `${name} 발표 앞뒤`;
  return long ? `${name} 발표(${fmt.hm(it.ts)}) 앞뒤 ${mins}분` : `${name} 발표 앞뒤 ${mins}분`;
}
const partsKo = (parts, d, long) => [...new Set((parts || []).map((p) => partKo(p, d, long)))].join(" · ");
/** When the last pause ended before now (the start of the open stretch now), or null when not known. */
export function lastPauseEnd(d, now) {
  const xs = [];
  for (const it of (d && d.items) || []) if (ok(it.pause_to) && it.pause_to <= now) xs.push(Number(it.pause_to));
  for (const sp of (d && d.spans) || []) if (ok(sp.to) && sp.to <= now) xs.push(Number(sp.to));
  const wk = d && d.weekend, r = (d && d.rules) || {};
  if (r.no_weekend && wk && ok(wk.from) && ok(wk.to)) {
    const prev = wk.from > now ? wk.to - 7 * DAY : wk.to;
    if (prev <= now) xs.push(prev);
  }
  return xs.length ? Math.max(...xs) : null;
}
/**
 * Entries now by the bot's rules, worked out from the answer's pause windows at any moment (the page ticks between two
 * answers): {paused, from, until, here (windows now), after (windows that follow without a gap), ko (why, in words),
 * progress (0..1 of the pause, or of the open stretch to the next pause; null unknown), next {from, to, parts, ko}}.
 * A pause runs on while windows touch (a release right after the weekend): `until` is where the last one ends.
 */
export function stateAt(d, now) {
  const merged = mergeSpans(d && d.spans);
  const cur = merged.find((m) => m.from <= now && now < m.to) || null;
  let st;
  if (cur) {
    const here = cur.parts.filter((p) => p.from <= now && now < p.to);
    st = {paused: true, from: cur.from, until: cur.to, here, after: cur.parts.filter((p) => p.from > now), ko: partsKo(here, d, true)};
  } else if (d && d.now && d.now.paused && ok(d.now.pause_until) && now < d.now.pause_until) {
    st = {paused: true, from: null, until: Number(d.now.pause_until), here: [], after: [], ko: null, said: d.now.pause_ko || null};
  } else {
    st = {paused: false, from: lastPauseEnd(d, now), until: null, here: [], after: [], ko: null};
  }
  const nx = merged.find((m) => m.from > now);
  const sn = d && d.now && d.now.next;
  st.next = nx ? {from: nx.from, to: nx.to, parts: nx.parts, ko: partsKo(nx.parts, d, false)}
    : sn && ok(sn.from) && sn.from > now && !(d.spans || []).length ? {from: sn.from, to: sn.to, parts: [sn], ko: partKo(sn, d, false)} : null;
  const a = st.from, b = st.paused ? st.until : st.next && st.next.from;
  st.progress = ok(a) && ok(b) && b > a ? Math.max(0, Math.min(1, (now - a) / (b - a))) : null;
  return st;
}

// ---------------------------------------------------------------- pure: the 7-day ribbon
/** A pause window cut to one day [a, b): {from, to, why, kind, ko, l, w (shares of the day), cutL, cutR, src} or null. */
export function clipSpan(x, a, b) {
  const f = Math.max(Number(x.from), a), t = Math.min(Number(x.to), b);
  if (!(t > f)) return null;
  return {from: f, to: t, why: x.why, kind: x.kind || null, ko: x.ko, l: (f - a) / (b - a), w: (t - f) / (b - a),
    cutL: x.from < a, cutR: x.to > b, src: x};
}
/** The release labels over a day's bar: each macro block gets a lane (0, 1, ...) so two close labels never overlap. */
export function laneTags(blocks, gap = 0.17) {
  const last = [];
  for (const b of blocks.filter((x) => x.why === "macro").sort((p, q) => p.from - q.from)) {
    const c = b.l + b.w / 2;
    let k = 0;
    while (last[k] != null && c - last[k] < gap) k++;
    last[k] = c; b.lane = k; b.c = c;
  }
  return blocks;
}
/**
 * The ribbon's rows: one per Korea-time day from today, `days` of them. Each: {a, b, key, label ("10/29 (목)"), rel
 * (오늘 / 내일), weekend, blocks (weekend first, a release drawn over it), lanes, pauseMs (the day's paused time, overlaps
 * counted once), full, kinds, nowAt (share of the day passed, today only)}.
 */
export function dayRows(spans, now, days = 7) {
  const start = fmt.kstMidnight(now);
  const xs = (spans || []).filter((x) => x && ok(x.from) && ok(x.to));
  return Array.from({length: days}, (_, i) => {
    const a = start + i * DAY, b = a + DAY;
    const blocks = laneTags(xs.map((x) => clipSpan(x, a, b)).filter(Boolean)
      .sort((p, q) => (p.why === "weekend" ? 0 : 1) - (q.why === "weekend" ? 0 : 1) || p.from - q.from));
    const pauseMs = mergeSpans(blocks).reduce((t, m) => t + (m.to - m.from), 0);
    return {a, b, key: fmt.dayKey(a), label: dayKo(a), rel: i === 0 ? "오늘" : i === 1 ? "내일" : null, weekend: isWeekendDay(a), blocks,
      lanes: Math.max(0, ...blocks.map((x) => (x.lane != null ? x.lane + 1 : 0))), pauseMs, full: pauseMs >= DAY,
      kinds: [...new Set(blocks.filter((x) => x.why === "macro").map((x) => x.kind))], nowAt: now >= a && now < b ? (now - a) / DAY : null};
  });
}
/** A day row in words: "하루 종일 쉼" / "1시간 쉼 · FOMC" / "쉬는 시간 없음". */
export function rowKo(r) {
  if (r.full) return "하루 종일 쉼";
  if (!r.pauseMs) return "쉬는 시간 없음";
  const n = r.blocks.filter((b) => b.why === "macro").length;
  return `${durKo(r.pauseMs)} 쉼${n > 1 ? ` · ${fmt.int(n)}번` : ""}`;
}
/** The next `days` days from now in numbers: {spanMs, pauseMs (overlaps once), share, weekendMs, macroN, macroMs, usN, usMs
 *  (the Nasdaq-open windows)}. */
export function weekSummary(spans, now, days = 7) {
  const a = Number(now), b = a + days * DAY;
  const parts = (spans || []).filter((x) => x && ok(x.from) && ok(x.to)).map((x) => clipSpan(x, a, b)).filter(Boolean);
  const len = (xs) => mergeSpans(xs).reduce((t, m) => t + (m.to - m.from), 0);
  const mac = parts.filter((x) => x.why === "macro");
  const us = parts.filter((x) => x.why === "usopen");
  const pauseMs = len(parts);
  return {spanMs: b - a, pauseMs, share: pauseMs / (b - a), weekendMs: len(parts.filter((x) => x.why === "weekend")), macroN: mac.length, macroMs: len(mac),
    usN: us.length, usMs: len(us)};
}

// ---------------------------------------------------------------- pure: the file's coverage and the market tiles
/** The amber line when the release file runs out soon (events.low), else null. "내년" when the dates needed are next year's. */
export function coverageKo(ev, now) {
  if (!ev || ev.state !== "ok" || !ev.low) return null;
  if (!ok(ev.last_ms)) return "등록된 경제 발표 일정이 없어요 · 일정을 넣어야 해요";
  const which = kparts(now + (Number(ev.low_days) || 45) * DAY).y > kparts(ev.last_ms).y ? "내년" : "다음";
  return `등록된 일정이 ${fmt.date(ev.last_ms)}까지예요 · ${which} 일정을 넣어야 해요`;
}
const bigUsd = (x) => (!ok(x) ? "—" : x >= 1e12 ? `${fmt.num(x / 1e12, 2)}조 달러` : x >= 1e9 ? `${fmt.num(x / 1e9, 1)}B 달러` : `${fmt.num(x, 0)} 달러`);
/**
 * /api/market as tiles: [{id, k (name), v (shown value), unit, sub, tone, gauge (0..1, fear & greed), points, stale}] or,
 * for a source the server could not read, {id, k, miss: true, err} ('못 받음', never a zero).
 */
export function marketTiles(m) {
  if (!m || typeof m !== "object") return [];
  const out = [];
  const miss = (id, k, x) => ({id, k, miss: true, err: (x && x.error) || null});
  const f = m.fng || {}, fn = f.now;
  out.push(fn && ok(fn.value) ? {id: "fng", k: "공포·탐욕", v: fmt.int(fn.value), unit: "/100", sub: fn.label_ko || fn.label || "",
    tone: fn.value < 45 ? "down" : fn.value > 55 ? "up" : "", gauge: Math.max(0, Math.min(1, fn.value / 100)), stale: !!f.stale} : miss("fng", "공포·탐욕", f));
  const g = m.global || {};
  out.push(ok(g.btc_dom) ? {id: "dom", k: "비트코인 도미넌스", v: fmt.pctOf(g.btc_dom, 1), sub: ok(g.eth_dom) ? `이더리움 ${fmt.pctOf(g.eth_dom, 1)}` : "",
    tone: "", stale: !!g.stale} : miss("dom", "비트코인 도미넌스", g));
  if (ok(g.total_mcap)) {
    const sub = ok(g.mcap_chg_24h) ? fmt.pctOf(g.mcap_chg_24h, 2, true) : "";
    out.push({id: "mcap", k: "코인 시가총액", v: bigUsd(Number(g.total_mcap)), sub: sub ? `24시간 ${sub}` : "", tone: fmt.tone(g.mcap_chg_24h, sub), stale: !!g.stale});
  } else out.push(miss("mcap", "코인 시가총액", g));
  for (const x of m.indexes || []) {
    const k = x.name || x.symbol || "지수", id = "ix:" + (x.symbol || k);
    if (!ok(x.price)) { out.push(miss(id, k, x)); continue; }
    const sub = ok(x.chg) ? fmt.pct(x.chg, 2) : "";
    out.push({id, k, v: x.symbol === "^TNX" ? fmt.pctOf(x.price, 3) : fmt.num(x.price, 2), sub, tone: fmt.tone(x.chg, sub),
      points: (x.points || []).map((p) => (Array.isArray(p) ? p[1] : null)).filter(ok), stale: !!x.stale});
  }
  return out;
}
/** Why a request failed, in a few words for a muted line: " (서버 오류 500)" / " (연결 끊김)" / "". */
export const whyKo = (e) => (e && e.kind === "timeout" ? " (서버가 제때 답하지 않음)" : e && e.kind === "network" ? " (연결 끊김)"
  : e && e.status ? ` (서버 오류 ${e.status})` : "");
const hostOf = (u) => { try { return new URL(String(u)).hostname.replace(/^www\./, ""); } catch (e) { return ""; } };
const KIND_SHORT = {CPI: "CPI", FOMC: "FOMC", NFP: "NFP", PCE: "PCE"};

// ---------------------------------------------------------------- the view
/** calView(ctx) -> {el, set()}: its own endpoint every 60 s, the countdown every second (both ctx.every: the router stops them). */
export function calView(ctx) {
  const st = {d: null, okAt: 0, shift: 0, busy: false, m: null, mErr: null, mOkAt: 0, day: null, cardsKey: "", paused: null, kickAt: 0};
  // the page's clock: the server's (serverNow); an answer whose now_ms is far from it (a clock the page could not sync)
  // is followed instead, so the countdown, the ribbon and the cards always agree with the answer they draw
  const now = () => serverNow() + st.shift;

  // ---- 지금 (the hero)
  const arc = s("circle", {class: "lbc-ring-fg", cx: 60, cy: 60, r: 52, pathLength: 100, transform: "rotate(-90 60 60)"});
  const glyph = h("span", {class: "lbc-glyph", "aria-hidden": "true"});
  const orb = h("div", {class: "lbc-orb"}, s("svg", {class: "lbc-ring", viewBox: "0 0 120 120", "aria-hidden": "true"},
    s("circle", {class: "lbc-ring-bg", cx: 60, cy: 60, r: 52}), arc), glyph);
  const clock = h("b", {class: "lbc-clock num"});
  const head = h("h2", {class: "lbc-head"});
  const why = h("p", {class: "lbc-why"});
  const cdk = h("span", {class: "lbc-cdk"});
  const cdD = h("b", {class: "lbc-cdd"}), cdDu = h("small", {class: "lbc-cddu"}, "일"), cdT = h("b", {class: "lbc-cdt"});
  const cdEnd = h("span", {class: "lbc-cdend"});
  const cdBox = h("div", {class: "lbc-cd", role: "timer", "aria-live": "off"}, cdk, h("div", {class: "lbc-digits num"}, cdD, cdDu, cdT), cdEnd);
  const nextLine = h("p", {class: "lbc-next"});
  const rules = h("div", {class: "lbc-rules"});
  const heroNotes = h("div", {class: "lbc-hnotes"});
  const hero = h("section", {class: "lbc-hero load", "aria-label": "지금 진입할 수 있나"},
    orb, h("div", {class: "lbc-main"}, h("p", {class: "lbc-kick"}, h("span", {class: "lbc-kdot", "aria-hidden": "true"}), "지금 · ", clock, h("span", {class: "lbc-ktz"}, " 한국 시간")),
      head, why), cdBox, nextLine, rules, heroNotes);
  put(head, motion.shimmer(1));

  // ---- the rest
  const stateSlot = h("div", {class: "lb-slot"});
  const cover = h("div", {class: "lbc-cover-slot"});
  const ribbon = h("div", {class: "lbc-ribbon"}, motion.shimmer(4));
  const legUs = h("span", {hidden: true}, h("i", {class: "lbc-sw usopen"}), "나스닥 개장 앞뒤");
  const legend = h("div", {class: "lbc-legend", "aria-hidden": "true"},
    h("span", null, h("i", {class: "lbc-sw weekend"}), "주말"), h("span", null, h("i", {class: "lbc-sw macro"}), "경제 발표 앞뒤"),
    legUs, h("span", null, h("i", {class: "lbc-sw now"}), "지금"));
  const weekBox = h("div", {class: "lbc-week"});
  const tlCard = ui.card({title: "앞으로 7일 · 진입 쉬는 시간", sub: "한국 시간 · 하루 한 줄", cls: "lbc-tlcard", acts: [legend]}, ribbon, weekBox);
  const relBox = h("div", {class: "lbc-rels"}, motion.shimmer(3, true));
  const relCard = ui.card({title: "미국 경제 발표", sub: "앞으로 21일 · 지난 3일은 흐리게 · 한국 시간", cls: "lbc-relcard"}, relBox);
  const tiles = h("div", {class: "lbc-tiles", role: "list"}, motion.shimmer(2, true));
  const mkNote = h("div", {class: "lbc-mknote"});
  const mkCard = ui.card({title: "시장 숫자", sub: "바깥 공개 자료 · 참고용 · 봇의 진입 판단에는 쓰지 않아요", cls: "lbc-mkcard"}, mkNote, tiles,
    h("p", {class: "lbc-news"}, h("span", {class: "lbc-news-i", "aria-hidden": "true"}), NEWS_KO));
  const main = h("div", {class: "lbc-body"}, hero, cover, h("div", {class: "lbc-grid"}, tlCard, mkCard, relCard));
  const el = h("div", {class: "lbc stack"}, stateSlot, main,
    ui.note("시간은 모두 한국 시간 · 일정: data/macro_events.csv (봇이 보는 같은 파일, 공식 발표 일정에서 옮겨 적음) · 1분마다 새로 읽고 남은 시간은 1초마다 줄어요 · 보기만 하는 화면"));

  // ---------------------------------------------------------------- draw (on every answer)
  function rulesEl(d) {
    const r = d.rules || {};
    const mins = Number(r.macro_blackout_min) || 0;
    return [h("div", {class: "lbc-chips"},
      h("span", {class: ["lbc-chip", r.no_weekend ? "" : "off"]}, h("i", {class: "lbc-sw weekend", "aria-hidden": "true"}),
        r.no_weekend ? "주말 진입 안 함 · 토 0시 ~ 월 0시" : "주말에도 진입 (봇 설정)"),
      h("span", {class: ["lbc-chip", mins ? "" : "off"]}, h("i", {class: "lbc-sw macro", "aria-hidden": "true"}),
        mins ? `경제 발표 앞뒤 ${fmt.int(mins)}분 진입 안 함 · CPI·FOMC·NFP·PCE` : "경제 발표 때도 진입 (봇 설정)"),
      usChip(d)),
    h("p", {class: "lbc-rule"}, h("b", null, "봇이 스스로 지키는 규칙이에요. "),
      "쉬는 동안에도 이미 열린 포지션은 그대로 가고, 거래소에 걸어 둔 손절 주문이 지켜요. ",
      "진입할 수 있는 시간이어도 신호가 와야 들어가요 (신호등이 빨강이거나 포지션이 이미 있으면 안 들어가요).")];
  }
  // the Nasdaq open (when the running config has it): its Korea-time window moves with US summer time
  function usChip(d) {
    const r = d.rules || {};
    if (!r.us_open_pause_min && !r.us_open_pre_min) return null;
    const sp = (d.spans || []).find((x) => x && x.why === "usopen");
    return h("span", {class: "lbc-chip"}, h("i", {class: "lbc-sw usopen", "aria-hidden": "true"}),
      `${sp ? sp.ko : "나스닥 개장 앞뒤"} 진입 안 함` + (sp ? ` · 평일 ${fmt.hm(sp.from)}~${fmt.hm(sp.to)} (한국 시간, 미국 서머타임 따라 움직임)` : ""));
  }
  function heroNotesEl(d) {
    const out = [];
    const c = d.combo || {};
    if (c.state && c.state !== "ok") {
      out.push(sourceState(c, "합친 봇 설정"), ui.note("그래서 기본 규칙(발표 앞뒤 30분 · 주말 쉼)으로 그렸어요"));
    }
    const ev = d.events || {};
    if (ev.state === "error") {
      out.push(sourceState(ev, "경제 발표 일정"), ui.note("봇도 같은 파일을 봐요: 발표 앞뒤 쉬는 시간이 빠져 있을 수 있어요"));
    }
    return out;
  }
  function coverEl(d, t) {
    const ev = d.events || {};
    const line = coverageKo(ev, t);
    const probs = (ev.problems || []).filter(Boolean);
    if (!line && !probs.length) return null;
    return h("div", {class: ["lbc-cover", line ? "low" : "probs"], role: "status"},
      h("span", {class: "lbc-cover-i", "aria-hidden": "true"}, "!"),
      h("div", {class: "lbc-cover-t"},
        line ? h("b", null, line) : null,
        line ? h("p", null, ok(ev.last_ms) ? `앞으로 ${fmt.int(Math.max(0, Math.floor(Number(ev.days_left) || 0)))}일치만 남았어요 (${fmt.int(ev.low_days || 45)}일보다 적으면 알려 드려요). ` : "",
          "일정이 없는 날은 봇이 발표 앞뒤로 쉬지 못해요 · 파일: data/macro_events.csv (봇도 같은 파일을 봐요)") : null,
        probs.length ? h("div", {class: "lbc-probs"}, h("b", null, `일정 파일에서 건너뛴 줄 ${fmt.int(probs.length)}개 · 봇도 이 줄은 모르는 일정이에요`),
          h("ul", null, probs.slice(0, 8).map((p) => h("li", null, String(p))))) : null));
  }

  let nowMark = null, nowRow = null;
  function drawRibbon(d, t) {
    const rows = dayRows(d.spans, t, 7);
    st.day = kday(t);
    nowMark = null; nowRow = null;
    const axis = h("div", {class: "lbc-axis", "aria-hidden": "true"}, h("span", {class: "lbc-ax0"}),
      h("div", {class: "lbc-ticks"}, [0, 6, 12, 18, 24].map((x) => h("span", {style: {"--x": x / 24}}, `${x}시`))), h("span", {class: "lbc-ax0"}));
    put(ribbon, axis, rows.map((r) => {
      const aria = `${r.label}${r.rel ? ` ${r.rel}` : ""}: ${r.blocks.length ? r.blocks.map((b) => `${fmt.hm(b.from)}~${b.cutR ? "24:00" : fmt.hm(b.to)} ${b.why === "weekend" ? "주말" : partKo(b.src, d, false)}`).join(", ") + " 진입 쉼" : "쉬는 시간 없음"}`;
      const tags = r.blocks.filter((b) => b.why === "macro").map((b) => {
        const ts = (Number(b.src.from) + Number(b.src.to)) / 2;
        return h("span", {class: ["lbc-tag", b.c < 0.07 ? "at-l" : b.c > 0.93 ? "at-r" : ""], style: {"--x": round4(b.c), "--lane": b.lane}},
          KIND_SHORT[b.kind] || b.kind || "발표", h("small", null, ` ${fmt.hm(ts)}`));
      });
      const blocks = r.blocks.map((b) => h("i", {class: ["lbc-blk", b.why, b.cutL ? "cl" : "", b.cutR ? "cr" : ""], style: {"--l": round4(b.l), "--w": round4(b.w)},
        title: `${b.why === "weekend" ? "주말" : partKo(b.src, d, true)} · ${rangeKo(b.src.from, b.src.to)} 진입 쉼`},
        b.why === "weekend" && b.w > 0.3 ? h("span", null, "주말 쉼") : null));
      const bar = h("div", {class: "lbc-bar", role: "img", "aria-label": aria}, blocks,
        r.nowAt != null ? h("i", {class: "lbc-past", style: {"--x": round4(r.nowAt)}}) : null);
      if (r.nowAt != null) {
        nowMark = h("i", {class: "lbc-now", style: {"--x": round4(r.nowAt)}}, h("b", {class: "num"}, `지금 ${fmt.hm(t)}`));
        bar.append(nowMark);
      }
      const row = h("div", {class: ["lbc-row", r.weekend ? "wk" : "", r.nowAt != null ? "today" : "", r.full ? "full" : ""], style: {"--lanes": r.lanes}},
        h("div", {class: "lbc-day"}, h("b", null, r.label), r.rel ? h("span", {class: "lbc-relday"}, r.rel) : null),
        h("div", {class: "lbc-track"}, tags.length ? h("div", {class: "lbc-tags", "aria-hidden": "true"}, tags) : null, bar),
        h("span", {class: ["lbc-sum", r.pauseMs ? "" : "none"]}, rowKo(r)));
      if (r.nowAt != null) nowRow = {row, bar, a: r.a};
      return row;
    }));
    const w = weekSummary(d.spans, t, 7);
    const r = d.rules || {};
    put(weekBox,
      h("div", {class: "lbc-wk main"}, h("span", null, "앞으로 7일 중 진입 쉼"), h("b", {class: "num"}, w.pauseMs ? durKo(w.pauseMs) : "없음"),
        h("span", {class: "lbc-wbar", role: "img", "aria-label": `7일의 ${fmt.pct(w.share, 0, false)}`}, h("i", {style: {"--v": round4(w.share)}})),
        h("small", {class: "num"}, `7일의 ${fmt.pct(w.share, 0, false)}`)),
      h("div", {class: "lbc-wk"}, h("span", null, h("i", {class: "lbc-sw weekend", "aria-hidden": "true"}), "주말"),
        h("b", {class: "num"}, r.no_weekend ? (w.weekendMs ? durKo(w.weekendMs) : "없음") : "쉬지 않음")),
      h("div", {class: "lbc-wk"}, h("span", null, h("i", {class: "lbc-sw macro", "aria-hidden": "true"}), "경제 발표 앞뒤"),
        h("b", {class: "num"}, r.macro_blackout_min ? (w.macroN ? `${fmt.int(w.macroN)}번 · ${durKo(w.macroMs)}` : "없음") : "쉬지 않음")),
      r.us_open_pause_min || r.us_open_pre_min ? h("div", {class: "lbc-wk"}, h("span", null, h("i", {class: "lbc-sw usopen", "aria-hidden": "true"}), "나스닥 개장 앞뒤"),
        h("b", {class: "num"}, w.usN ? `${fmt.int(w.usN)}번 · ${durKo(w.usMs)}` : "없음")) : null);
    legUs.hidden = !(r.us_open_pause_min || r.us_open_pre_min);
    weekBox.classList.toggle("four", !legUs.hidden);
  }

  let cdEls = [];
  function relEl(it, d, t) {
    const w = whenAt(it, t), p = kparts(it.ts);
    const cd = h("span", {class: ["lbc-rcd", w]});
    const extra = h("span", {class: "lbc-rin"});
    cdEls.push({el: cd, it, extra});
    const rel = relDay(it.ts, t);
    const src = it.url ? h("a", {class: "lbc-src", href: it.url, target: "_blank", rel: "noopener", title: `공식 발표 일정 (${it.url})`},
      "공식 일정", hostOf(it.url) ? h("span", {class: "lbc-host"}, hostOf(it.url)) : null, h("span", {"aria-hidden": "true"}, "↗")) : null;
    return h("article", {class: ["lbc-rel", "w-" + w, "k-" + String(it.kind || "x").toLowerCase(), it.weekend ? "wk" : ""],
      "aria-label": `${it.kind_ko} ${dayKo(it.ts)} ${fmt.hm(it.ts)}`},
      h("div", {class: "lbc-rdate", "aria-hidden": "true"}, h("span", {class: "lbc-rmo"}, `${p.mo}월`), h("b", {class: "lbc-rday num"}, String(p.d)),
        h("span", {class: "lbc-rwd"}, WD[p.wd])),
      h("div", {class: "lbc-rbody"},
        h("div", {class: "lbc-rtop"}, h("span", {class: "lbc-kind"}, KIND_SHORT[it.kind] || it.kind || "발표"), h("b", {class: "lbc-rname"}, it.kind_ko || it.kind), cd),
        h("p", {class: "lbc-rtime"}, h("b", {class: "num"}, fmt.hm(it.ts)), " 발표", extra, rel ? ` · ${rel}` : "", ` · ${dayKo(it.ts)}`),
        it.info_ko ? h("p", {class: "lbc-rinfo"}, it.info_ko) : null,
        h("div", {class: "lbc-rfoot"}, h("span", {class: ["lbc-rpause", it.weekend && (d.rules || {}).no_weekend ? "wk" : ""]},
          h("i", {class: "lbc-pz", "aria-hidden": "true"}), pauseKo(it, d.rules)), src)));
  }
  function cdText(it, t) {
    const w = whenAt(it, t);
    if (w === "past") return `지남 · ${fmt.ago(it.ts, t)}`;
    if (w === "now") return "지금 쉬는 중";
    return untilKo(it.ts, t);
  }
  // while its pause runs, the time line says how far the release itself is ("03:00 발표 (10분 뒤)")
  const extraText = (it, t) => (whenAt(it, t) !== "now" ? "" : Number(it.ts) > t ? ` (${durKo(it.ts - t)} 뒤)` : " (지남)");
  function drawCards(d, t) {
    const items = (d.items || []).filter((it) => it && ok(it.ts));
    const up = items.filter((it) => whenAt(it, t) !== "past").sort((a, b) => a.ts - b.ts).slice(0, MAX_CARDS);
    const past = items.filter((it) => whenAt(it, t) === "past").sort((a, b) => a.ts - b.ts).slice(-6);
    st.cardsKey = items.map((it) => `${it.ts}:${it.kind}:${whenAt(it, t)}`).join("|");
    cdEls = [];
    const ev = d.events || {};
    const none = ev.state === "error" ? sourceState(ev, "경제 발표 일정")
      : ui.empty(ok(ev.last_ms) ? "앞으로 21일 안에 등록된 발표가 없어요" : "등록된 경제 발표 일정이 없어요");
    put(relBox, up.length ? h("div", {class: "lbc-rgrid"}, up.map((it) => relEl(it, d, t))) : none,
      past.length ? [h("p", {class: "lbc-psep"}, `지난 3일 · ${fmt.int(past.length)}개`), h("div", {class: ["lbc-rgrid", "past"]}, past.map((it) => relEl(it, d, t)))] : null);
  }

  function draw() {
    const d = st.d;
    if (!d) return;
    const t = now();
    put(rules, rulesEl(d));
    put(heroNotes, heroNotesEl(d));
    put(cover, coverEl(d, t));
    drawRibbon(d, t);
    drawCards(d, t);
    tick();
  }

  // ---------------------------------------------------------------- every second: the hero, the now mark, the card countdowns
  function tick() {
    const d = st.d;
    if (!d) return;
    const t = now();
    const x = stateAt(d, t);
    hero.classList.remove("load");
    hero.classList.toggle("paused", x.paused);
    hero.classList.toggle("open", !x.paused);
    if (st.paused != null && st.paused !== x.paused) motion.play(hero, "lbc-flip");           // a real change only
    st.paused = x.paused;
    const p = kparts(t), tt = new Date(t + KST);
    clock.textContent = `${two(p.mo)}/${two(p.d)} (${WD[p.wd]}) ${two(tt.getUTCHours())}:${two(tt.getUTCMinutes())}:${two(tt.getUTCSeconds())}`;
    glyph.className = ["lbc-glyph", x.paused ? "pause" : "go"].join(" ");
    arc.setAttribute("stroke-dasharray", `${((x.progress == null ? 1 : x.progress) * 100).toFixed(2)} 100`);
    head.textContent = x.paused ? "진입 쉬는 중" : "지금은 진입할 수 있는 시간";
    why.textContent = !x.paused ? "봇의 규칙으로는 지금 새 진입을 막는 시간이 아니에요" : x.said ? x.said
      : `${x.ko || "봇의 규칙"}이라 새 진입을 쉬어요${x.after.length ? ` · 이어서 ${partsKo(x.after, d, false)}까지 쉬어요` : ""}`;
    const target = x.paused ? x.until : x.next ? x.next.from : null;
    cdk.textContent = x.paused ? "다시 진입할 수 있을 때까지" : "다음 쉬는 시간까지";
    if (ok(target)) {
      const cp = clockParts(target - t);
      cdD.textContent = cp.d ? String(cp.d) : ""; cdD.hidden = !cp.d; cdDu.hidden = !cp.d;
      cdT.textContent = `${two(cp.h)}:${two(cp.m)}:${two(cp.s)}`;
      cdEnd.textContent = x.paused ? `${dayKo(target)} ${fmt.hm(target)}에 다시 열려요` : `${dayKo(target)} ${fmt.hm(target)}부터 쉬어요`;
      cdBox.setAttribute("aria-label", `${cdk.textContent} ${clockKo(target - t)}`);
    } else {
      cdD.hidden = true; cdDu.hidden = true; cdT.textContent = "—";
      cdEnd.textContent = x.paused ? "끝나는 때를 모름" : "앞으로 7일 안에 쉬는 시간이 없어요";
    }
    put(nextLine, x.next ? [h("span", {class: "lbc-nk"}, "다음 쉬는 시간"), " ",
      h("b", null, x.next.ko), ` ${rangeKo(x.next.from, x.next.to)} `, h("span", {class: "lbc-nin"}, `(${durKo(x.next.from - t)} 뒤)`)]
      : [h("span", {class: "lbc-nk"}, "다음 쉬는 시간"), " 앞으로 7일 안에는 없어요"]);
    // the ribbon: a new Korea-time day draws it again; else only the now mark moves
    if (st.day !== kday(t)) drawRibbon(d, t);
    else if (nowMark && nowRow) {
      const at = round4((t - nowRow.a) / DAY);
      nowMark.style.setProperty("--x", String(at));
      nowMark.classList.toggle("at-l", at < 0.06); nowMark.classList.toggle("at-r", at > 0.94);
      nowMark.firstChild.textContent = `지금 ${fmt.hm(t)}`;
      const past = nowRow.bar.querySelector(".lbc-past");
      if (past) past.style.setProperty("--x", String(at));
    }
    // the cards: a release that moved on (곧 → 지금 → 지남) draws them again; else only the countdown words change
    const key = (d.items || []).filter((it) => it && ok(it.ts)).map((it) => `${it.ts}:${it.kind}:${whenAt(it, t)}`).join("|");
    if (key !== st.cardsKey) drawCards(d, t);
    for (const c of cdEls) { c.el.textContent = cdText(c.it, t); c.extra.textContent = extraText(c.it, t); }
    // the answer said otherwise a moment ago (a pause began or ended): ask the server again, at most every 15 s
    if (d.now && !!d.now.paused !== x.paused && Date.now() - st.kickAt > 15000 && Date.now() - st.okAt > 5000) {
      st.kickAt = Date.now();
      load().catch(() => {});
    }
  }

  // ---------------------------------------------------------------- loads
  async function load() {
    if (st.busy) return;
    st.busy = true;
    let d;
    try { d = await ctx.api(API); }
    catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      // a refresh that fails after a good answer keeps it, dimmed, with its age; the countdown goes on from it
      if (st.d) { put(stateSlot, ui.staleNote(e, st.okAt, () => load().catch(() => {}))); ui.dim(main, true); }
      else { put(stateSlot, ui.errorBox(e, () => load())); main.hidden = true; }
      throw e;
    } finally { st.busy = false; }
    if (!ctx.alive()) return;
    put(stateSlot); ui.dim(main, false); main.hidden = false;
    const skew = ok(d && d.now_ms) ? Number(d.now_ms) - serverNow() : 0;
    st.shift = Math.abs(skew) > SKEW_MS ? skew : 0;
    st.d = d; st.okAt = Date.now();
    draw();
  }
  function drawMarket() {
    const m = st.m;
    if (!m) {
      put(tiles, st.mErr ? null : motion.shimmer(2, true));
      put(mkNote, st.mErr ? h("p", {class: "lbc-mkfail"}, `시장 숫자를 못 읽었어요${whyKo(st.mErr)} · 5분 뒤 다시 읽어요`) : null);
      tiles.hidden = !!st.mErr;
      return;
    }
    tiles.hidden = false;
    const ts = marketTiles(m);
    put(tiles, ts.length ? ts.map(tileEl) : ui.empty("시장 숫자가 비어 있어요"));
    put(mkNote, st.mErr ? h("p", {class: "lbc-mkfail"}, `새로 못 읽었어요${whyKo(st.mErr)} · ${fmt.ago(st.mOkAt)} 숫자예요`) : null);
    ui.dim(tiles, !!st.mErr);
  }
  function tileEl(t) {
    if (t.miss) {
      return h("div", {class: "lbc-tile miss", role: "listitem"}, h("span", {class: "lbc-tk"}, t.k), h("b", {class: "lbc-tv"}, "못 받음"),
        h("span", {class: "lbc-ts"}, t.err ? `바깥 자료 오류 (${t.err})` : "바깥 자료가 비었어요"));
    }
    return h("div", {class: ["lbc-tile", "t-" + t.id.replace(/[^a-z0-9]+/gi, "")], role: "listitem"},
      h("span", {class: "lbc-tk"}, t.k, t.stale ? ui.pill("예전 값", "thin", "새 값을 받지 못해 마지막 값을 보여 줘요") : null),
      h("b", {class: ["lbc-tv", "num", t.id === "fng" ? t.tone : ""]}, t.v, t.unit ? h("small", null, t.unit) : null),
      t.sub ? h("span", {class: ["lbc-ts", "num", t.id === "fng" ? "" : t.tone]}, t.sub) : null,
      t.gauge != null ? h("span", {class: "lbc-fg", role: "img", "aria-label": `공포·탐욕 ${t.v}/100`}, h("i", {style: {"--v": round4(t.gauge)}})) : null,
      t.points && t.points.length > 1 ? ui.miniSpark(t.points, {w: 120, h: 22, fluid: true, label: `${t.k} 5일 흐름`}) : null);
  }
  async function loadMarket() {
    try { st.m = await ctx.api(MARKET); st.mErr = null; st.mOkAt = Date.now(); }
    catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      st.mErr = e;
    }
    if (ctx.alive()) drawMarket();
  }

  load().catch(() => {});
  loadMarket();
  ctx.every(REFRESH_MS, () => load().catch(() => {}), {now: false});
  ctx.every(TICK_MS, tick, {now: false});
  ctx.every(MARKET_MS, loadMarket, {now: false});
  return {el, set() {}};
}

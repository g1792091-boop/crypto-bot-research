// The shared kit of the live-position views (포지션 · 터미널 · 순위표), so they all read and show open positions the same
// way. Screens import these; they never copy them.
//   onPositions(fn) -> unsubscribe   /api/positions every 30 s while somebody listens (and right after every new engine
//                                    snapshot: app.js calls kickPositions), fn(doc) now when there is an answer
//   livePnl(p, mark)                 {mark, pnl, roe, liqGap, stopGap, tpGap} of one position at the mark (USDT, before the
//                                    exit fee), null when hidden (D11), without a size or without a price (never a guess)
//   gap(side, mark, line)            share of the mark the price still has to move to reach the line (> 0: not reached)
//   liveAllowed(doc)                 false while the engine replays from 10/01 or its snapshot is over 15 minutes old:
//                                    the positions are then "그때 기준" and no live P&L is shown (B2 / B8)
//   pricesLive() / liveOk(doc)       the prices are live (or under a minute old); liveOk = liveAllowed and pricesLive:
//                                    every live P&L, ROE and distance on 포지션, 터미널 and 순위표 asks this one
//   waitKo(doc)                      why live numbers are hidden ("엔진이 따라잡는 중", "시세가 3분 전 값", ...), "" when not
//   staleBanner(doc), freshLine(doc) the banner and the "엔진 기준 HH:MM (n분 전) · 시세 n초 전" line (B3)
//   posPill(x)                       "● BTC 롱 30배 +0.1%" (live ROE; a league account with .open or a position); .update()
//   crowd({long, short})             {on, side, share, n}: 5 or more positions, 80 % or more one way (the rule bot's rule)
//   sums(list, markFn)               the totals of the shown (non-hidden) positions at the mark
//   POS_GROUPS, inGroup(p, id)       the 묶음 choices every view offers (전체 · 후보 · 1/4 · 청산만 · 기본값 · 동전 · 기존 36 · 딥시크)
// Numbers: P&L = side x qty x (mark - entry); ROE = P&L / margin (= side x lev x (mark/entry - 1)); the margin, size and
// liquidation price are the server's rebuild "진입 때 기준" (candleague/dash.py rebuild_open).
import {h, put} from "./dom.js";
import {getJSON} from "./api.js";
import * as fmt from "./fmt.js";
import {markOf, liveState, serverNow} from "./live.js";
import {ROLE_SHORT, KIND_KO, sideKo, coinShort} from "./labels.js";

export const POS_MS = 30000;
export const SNAP_WARN_S = 12 * 60;                // older than this: the freshness line turns orange
export const SNAP_OLD_S = 15 * 60;                 // the server's ``old``: the banner and no live P&L

// ---------------------------------------------------------------- the shared poll
const st = {doc: null, at: 0, subs: new Set(), timer: null, busy: false};
async function poll() {
  if (st.busy || (typeof document !== "undefined" && document.visibilityState === "hidden")) return;
  st.busy = true;
  try {
    const d = await getJSON("/api/positions");
    st.doc = d;
    st.at = Date.now();
    for (const fn of [...st.subs]) { try { fn(d); } catch (e) { console.error(e); } }
  } catch (e) {
    /* keep the last answer */
  } finally {
    st.busy = false;
  }
}
if (typeof document !== "undefined") {
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible" && st.subs.size) poll(); });
}
/** fn(doc) with the last answer (if any) and after every new one; returns the unsubscribe. */
export function onPositions(fn) {
  st.subs.add(fn);
  if (st.doc) { try { fn(st.doc); } catch (e) { console.error(e); } }
  if (!st.timer) st.timer = setInterval(poll, POS_MS);
  if (!st.doc || Date.now() - st.at > POS_MS) poll();
  return () => {
    st.subs.delete(fn);
    if (!st.subs.size && st.timer) { clearInterval(st.timer); st.timer = null; }
  };
}
export const positionsDoc = () => st.doc;
/** A new engine snapshot arrived (app.js): ask again now if anybody listens. */
export function kickPositions() { if (st.subs.size) poll(); }

// ---------------------------------------------------------------- numbers
const fin = (x) => (x == null || x === "" || !Number.isFinite(Number(x)) ? null : Number(x));
/** Share of the mark the price still has to move to reach the line; > 0 while it is not reached (null without data). */
export function gap(side, mark, line) {
  const m = fin(mark), l = fin(line);
  if (m == null || l == null || !m) return null;
  return Number(side) > 0 ? (m - l) / m : (l - m) / m;
}
/** The live numbers of one /api/positions entry at ``mark`` (default: the coin's mark now). */
export function livePnl(p, mark) {
  if (!p || p.hidden || fin(p.qty) == null || fin(p.entry) == null) return null;
  const m = fin(mark === undefined ? markOf(p.coin) : mark);
  if (m == null) return null;
  const pnl = Number(p.side) * Number(p.qty) * (m - Number(p.entry));
  const margin = fin(p.margin);
  return {mark: m, pnl, roe: margin ? pnl / margin : null, liqGap: gap(p.side, m, p.liq),
    stopGap: p.stop_is_lock ? null : gap(p.side, m, p.stop), lockGap: p.stop_is_lock ? gap(p.side, m, p.stop) : null,
    tpGap: p.tp == null ? null : -gap(p.side, m, p.tp)};
}
/** ROE (a fraction) of a position from its leverage alone: side x lev x (mark/entry - 1); needs no size. */
export function roeOf(side, lev, entry, mark) {
  const e = fin(entry), m = fin(mark), L = fin(lev);
  if (e == null || m == null || L == null || !e) return null;
  return Number(side) * L * (m / e - 1);
}
/** True when live P&L may be shown for this snapshot (not replaying from 10/01, not over 15 minutes old). */
export const liveAllowed = (doc) => !!doc && !doc.status && !doc.catching_up && !doc.old;
export const PX_GRACE_S = 60;                      // the last good prices count as live for this long (a short hiccup)
/** True while the page's prices may carry live P&L: fresh (or test) prices, or the last good ones for at most a minute
 *  while Binance does not answer. Past that the numbers would look live but be old (live.py keeps the last good values
 *  with no time limit), so every live P&L, ROE and distance is hidden instead. */
export function pricesLive(ls = liveState()) {
  if (ls.state === "ok" || ls.state === "fake") return true;
  return ls.state === "stale" && ls.age_s != null && ls.age_s <= PX_GRACE_S;
}
/** Live P&L may be shown: the snapshot is "now" (liveAllowed) and the prices are live (pricesLive). */
export const liveOk = (doc) => liveAllowed(doc) && pricesLive();
/** Why live numbers are hidden, in the screens' words; "" when they are shown. */
export function waitKo(doc) {
  if (!doc || doc.status) return "엔진 기록 준비 중";
  if (doc.catching_up) return "엔진이 따라잡는 중";
  if (doc.old) return "엔진 기록이 멈춤";
  const ls = liveState();
  if (pricesLive(ls)) return "";
  if (ls.state === "stale") return `시세가 ${ageKo(ls.age_s)} 값`;
  if (ls.state === "wait") return "시세 기다리는 중";
  if (ls.state === "off") return "시세 꺼짐";
  return "시세 끊김";
}

/** Totals of the shown positions (hidden DeepSeek ones are only counted): {n, long, short, hidden, pnl, margin,
 *  pricedMargin, roe, winning, losing, priced, unpriced}. ``margin`` is every shown position's margin (묶인 증거금);
 *  ``roe`` = pnl / pricedMargin, the margin of the positions that have a price (a coin without a price is left out of
 *  both sides, never counted as zero). markFn(coin) -> mark (default: the live mark). */
export function sums(list, markFn = markOf) {
  const out = {n: 0, long: 0, short: 0, hidden: 0, pnl: 0, margin: 0, pricedMargin: 0, roe: null, winning: 0, losing: 0, priced: 0,
    unpriced: 0, coins: new Set()};
  for (const p of list || []) {
    out.n += 1;
    out[Number(p.side) > 0 ? "long" : "short"] += 1;
    out.coins.add(p.coin);
    if (p.hidden) { out.hidden += 1; continue; }
    const mg = fin(p.margin);
    if (mg != null) out.margin += mg;
    const u = livePnl(p, markFn(p.coin));
    if (!u) { out.unpriced += 1; continue; }
    out.priced += 1;
    out.pnl += u.pnl;
    if (mg != null) out.pricedMargin += mg;
    if (u.pnl > 0) out.winning += 1; else if (u.pnl < 0) out.losing += 1;
  }
  out.roe = out.pricedMargin > 0 && out.priced ? out.pnl / out.pricedMargin : null;
  return out;
}
/** The rule bot's "한 방향 몰림": 5 or more positions and 80 % or more of them on one side. */
export function crowd(c) {
  const L = Number((c && c.long) || 0), S = Number((c && c.short) || 0), n = L + S;
  const share = n ? Math.max(L, S) / n : 0;
  return {on: n >= 5 && share >= 0.8, side: L === S ? 0 : L > S ? 1 : -1, share, n};
}

// ---------------------------------------------------------------- the 묶음 choices
export const POS_GROUPS = [
  {id: "all", ko: "전체"}, {id: "cand", ko: "후보"}, {id: "quarter", ko: "1/4"}, {id: "exitonly", ko: "청산만"},
  {id: "base", ko: "기본값"}, {id: "flip", ko: "동전"}, {id: "core", ko: KIND_KO.core}, {id: "ds", ko: KIND_KO.ds},
];
export function inGroup(p, id) {
  if (!id || id === "all") return true;
  if (id === "core" || id === "ds") return p.kind === id;
  return p.role === id;
}

// ---------------------------------------------------------------- pieces
const ageKo = (s) => (s == null ? "—" : s < 60 ? `${Math.round(s)}초 전` : `${fmt.dur(s)} 전`);
/** "시세 4초 전" / "시세 4초 전 (시험용)" / the feed's own words when the prices are not live: the price part of the
 *  freshness line, shared by every screen that shows the price age (freshLine, the 순위표's live dot). */
export function pxAgeKo(ls = liveState()) {
  return ls.state === "ok" || ls.state === "fake" ? `시세 ${ageKo(ls.age_s)}${ls.state === "fake" ? " (시험용)" : ""}`
    : ls.state === "stale" && ls.age_s != null ? `시세 지난 값 (${ageKo(ls.age_s)})` : ls.ko;
}
/** Seconds since the engine wrote the snapshot, by the server's clock (null without one). */
export function snapAge(doc) {
  if (!doc || !doc.generated_ms) return null;
  return Math.max(0, (serverNow() - doc.generated_ms) / 1000);
}

/** "엔진 기준 10/10 09:00 KST (3분 전) · 시세 4초 전": what the positions and the prices are as of. Orange when the
 *  snapshot is over 12 minutes old or the prices are not live. el.update(doc) repaints (call it from onLive too).
 *  o.only = "px": the price part alone (a screen whose head already shows the engine time). */
export function freshLine(doc, o = {}) {
  const pxOnly = o.only === "px";
  const eng = h("span", {class: "kp-fe"}), px = h("span", {class: "kp-fp"});
  const el = h("p", {class: ["kp-fresh", o.cls], role: "status", "aria-live": "off",
    title: pxOnly ? "시세는 대시보드 서버가 5초마다 바이낸스 공개 시세를 받아 보여 줍니다."
      : "엔진은 5분마다 계산해 기록을 씁니다 (그래서 새 진입·청산은 몇 분 늦게 보입니다). 시세는 5초마다 다시 받습니다."},
  pxOnly ? null : [eng, " · "], px);
  el.update = (d) => {
    if (d !== undefined) el._doc = d;
    const x = el._doc;
    const age = snapAge(x);
    const ls = liveState();
    if (!x || x.status) eng.textContent = "엔진 기록 준비 중";
    else eng.textContent = `엔진 기준 ${fmt.kst(x.done_ms)} KST (${ageKo(age)} 씀)`;
    px.textContent = pxAgeKo(ls);
    const pxWarn = !(ls.state === "ok" || ls.state === "fake");
    const warn = pxOnly ? pxWarn : !x || x.status || x.catching_up || (age != null && age > SNAP_WARN_S) || pxWarn;
    el.classList.toggle("warn", !!warn);
  };
  el.update(doc);
  return el;
}

/** The banner of a snapshot whose positions are not "now": the engine replaying from 10/01 (B2) or stopped (B8); null
 *  when all is well. */
export function staleBanner(doc) {
  if (!doc || doc.status) return null;
  if (doc.catching_up) {
    return h("div", {class: "kp-banner warn", role: "status"}, h("b", null, "10/01부터 다시 계산 중"),
      h("span", null, ` · 지금 ${fmt.kst(doc.done_ms)} KST까지 계산함 · 아래 포지션은 그 시각의 것이라 실시간 손익·거리는 감춥니다 (따라잡으면 저절로 보임)`));
  }
  if (doc.old) {
    const age = snapAge(doc);
    return h("div", {class: "kp-banner bad", role: "status"}, h("b", null, `엔진 기록이 ${age == null ? "오래" : fmt.dur(age)} 전에 멈춤`),
      h("span", null, " · 아래 포지션은 그때 기준이라 이미 닫혔을 수 있습니다 · 실시간 손익은 감춥니다 (서버 상태 화면에서 확인)"));
  }
  return null;
}

/** "● BTC 롱 30배 +0.1%" for a league account (a.open: {symbol, side, entry, lev}) or an /api/positions entry. The ROE
 *  is live (mark now, before the exit fee) when allowed and known; a hidden DeepSeek position shows coin and side only.
 *  o.hidden: true counts it as hidden whatever the object carries (the caller's money rule; the pill then reads only
 *  the coin and the side, so a number the snapshot should not have carried never shows). el.update(o) repaints
 *  (o.allowed: false hides the ROE). */
export function posPill(x, o = {}) {
  const raw = x && x.open !== undefined ? x.open : x;
  if (!raw) return null;
  const hidden = !!(o.hidden || x.hidden || (x.kind === "ds" && x.open !== undefined && raw.entry == null));
  const pos = hidden ? {coin: raw.coin, symbol: raw.symbol, side: raw.side, since: raw.since} : raw;
  const coin = coinShort(pos.coin || pos.symbol);
  const lev = fin(pos.lev);
  const roeEl = h("b", {class: "kp-roe num"});
  const el = h("span", {class: ["kp-pill", hidden ? "hid" : ""],
    title: hidden ? "열린 포지션 (딥시크 금액 숨김: 개수와 방향만)" : "열린 포지션 · 지금 마크 가격 기준 ROE (나갈 때 수수료 전)"},
  h("i", {"aria-hidden": "true"}), `${coin} ${sideKo(pos.side)}${lev && !hidden ? ` ${fmt.lev(lev)}` : ""}`, hidden ? null : roeEl);
  el.update = (oo = o) => {
    const allowed = oo.allowed !== false;
    const r = hidden || !allowed ? null : roeOf(pos.side, lev, pos.entry, markOf(pos.coin || pos.symbol));
    const t = r == null ? "" : fmt.pct(r * 100, true, 1);
    if (roeEl.textContent !== t) {
      roeEl.textContent = t;
      if (t && !oo.still) { el.classList.remove("tick"); void el.offsetWidth; el.classList.add("tick"); }
    }
    el.classList.toggle("up", r != null && r > 0);
    el.classList.toggle("down", r != null && r < 0);
  };
  el.update({...o, still: true});
  return el;
}

/** "롱 12 · 숏 7" with the crowding dot. */
export function sideCount(c) {
  const k = crowd(c);
  return h("span", {class: "kp-sides"}, h("span", {class: "up"}, `롱 ${fmt.int((c && c.long) || 0)}`), " · ",
    h("span", {class: "down"}, `숏 ${fmt.int((c && c.short) || 0)}`),
    k.on ? h("i", {class: "kp-crowd", title: `한 방향 몰림: ${k.n}개 중 ${Math.round(k.share * 100)}%가 ${k.side > 0 ? "롱" : "숏"}`, "aria-label": "한 방향 몰림"}) : null);
}

/** The role chip text of a position's account ("1/4", "동전", ...). */
export const roleShort = (p) => ROLE_SHORT[p && p.role] || "";

/** Fill a container with a fresh banner (or empty it): put(slot, staleBanner(doc)). */
export function paintBanner(slot, doc) { put(slot, staleBanner(doc)); }

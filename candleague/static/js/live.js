// The live market feed for the whole page: ONE /api/live poll every 5 s while somebody listens and the page is on
// screen (the 터미널, 포지션 and 순위표 share it; the old per-screen polls are not needed). The server answers from its own
// short cache (candleague/live.py: Binance public prices, nothing from the browser to Binance). Every helper here only
// reads the last answer; nothing is invented when a coin has no price (null, the screens show "—").
//   onLive(fn) -> unsubscribe        fn(doc) now (if there is an answer) and after every new answer
//   liveRow(coin) / markOf(coin) / priceOf(coin)      coin as "BTCUSD", "BTCUSDT" or "BTC"
//   liveState() -> {state: "ok"|"stale"|"unavailable"|"off"|"fake"|"wait", age_s, generated_ms, ko}
//   serverNow() -> the dashboard server's clock now (ms), so ages never depend on the device's clock
import {getJSON} from "./api.js";

export const LIVE_MS = 5000;
export const LIVE_OLD_S = 30;                 // prices older than this are "지난 값"
const st = {doc: null, at: 0, subs: new Set(), timer: null, busy: false, skew: 0};

const key = (coin) => {
  const c = String(coin || "").toUpperCase().replace(/USDT$/, "USD");
  return c.endsWith("USD") ? c : `${c}USD`;
};

async function poll() {
  if (st.busy || typeof document !== "undefined" && document.visibilityState === "hidden") return;
  st.busy = true;
  try {
    const d = await getJSON("/api/live");
    st.doc = d;
    st.at = Date.now();
    if (d && d.server_ms) st.skew = d.server_ms - st.at;
    for (const fn of [...st.subs]) { try { fn(d); } catch (e) { console.error(e); } }
  } catch (e) {
    /* keep the last answer: liveState() turns it to 지난 값 as it ages */
  } finally {
    st.busy = false;
  }
}
function start() {
  if (st.timer) return;
  st.timer = setInterval(poll, LIVE_MS);
  poll();
}
function stop() {
  if (st.subs.size || !st.timer) return;
  clearInterval(st.timer);
  st.timer = null;
}
if (typeof document !== "undefined") {
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible" && st.subs.size) poll(); });
}

/** fn(doc) with the last answer (if any) and after every new one; returns the unsubscribe. */
export function onLive(fn) {
  st.subs.add(fn);
  if (st.doc && Date.now() - st.at < LIVE_MS * 2) { try { fn(st.doc); } catch (e) { console.error(e); } }
  start();
  return () => { st.subs.delete(fn); stop(); };
}
export const liveDoc = () => st.doc;
/** The dashboard server's clock now (ms); the device's clock until the first answer. */
export const serverNow = () => Date.now() + st.skew;
/** Ask again now (after a screen opens). */
export const liveRefresh = () => poll();

/** The coin's row of the last answer ({coin, price, mark, change_pct, funding_rate, next_funding_ms, ...}) or null. */
export function liveRow(coin) {
  const k = key(coin);
  const rows = (st.doc && st.doc.coins) || [];
  return rows.find((r) => r.coin === k) || null;
}
const fin = (x) => (x == null || !Number.isFinite(Number(x)) ? null : Number(x));
/** The mark price (what the engine liquidates on), else the last trade price; null without a price. */
export function markOf(coin) {
  const r = liveRow(coin);
  if (!r || r.ok === false) return null;
  return fin(r.mark) ?? fin(r.price);
}
export function priceOf(coin) {
  const r = liveRow(coin);
  return r && r.ok !== false ? fin(r.price) : null;
}

/** How fresh the prices are: ok (under 30 s), stale (Binance not answering: the last good values), unavailable (none
 *  yet), off (CANDLEAGUE_DASH_LIVE=off), fake (test prices), wait (no answer yet). */
export function liveState() {
  const d = st.doc;
  if (!d) return {state: "wait", age_s: null, generated_ms: null, ko: "시세 기다리는 중"};
  if (d.off) return {state: "off", age_s: null, generated_ms: null, ko: "시세 꺼짐 (설정)"};
  if (d.unavailable) return {state: "unavailable", age_s: null, generated_ms: d.generated_ms || null, ko: "시세 없음 · 바이낸스 연결 확인 중"};
  const age = d.generated_ms ? Math.max(0, (serverNow() - d.generated_ms) / 1000) : null;
  if (d.stale || (age != null && age > LIVE_OLD_S)) return {state: "stale", age_s: age, generated_ms: d.generated_ms, ko: "시세 지난 값 · 바이낸스 연결 확인 중"};
  if (d.source === "fake") return {state: "fake", age_s: age, generated_ms: d.generated_ms, ko: "시험용 가짜 시세"};
  return {state: "ok", age_s: age, generated_ms: d.generated_ms, ko: "실시간 시세"};
}

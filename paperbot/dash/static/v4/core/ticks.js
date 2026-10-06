// The page's ONE subscription to the server's market-trade relay (/api/v4/ticks, dash/more/ticks.py: one Binance
// aggTrade socket on the server shared by every page, at most ~2 events a second, plus the whole market's large orders).
// Everything on the page that follows real market trades listens here, so a page holds at most one EventSource however
// many parts listen (the server counts listeners per answer and keeps its Binance socket only while one listens):
//   - the sound's continuous layer (core/sound.js, while the sound is on),
//   - the 터미널 / 차트 screens' live lights and 실시간 큰 체결 (screens/terminal-live.js tickStream),
//   - the chart's blinking Premium / Discount light (core/chartfx.js + core/blink.js, even with the sound off).
// The connection is open only while at least one part listens AND the page is visible: hidden -> closed (the server's
// socket closes a minute after the last page left), shown again -> opened again; the last listener leaving closes it.
// A refused answer (401 / 404 / 5xx: readyState 2) is asked again after 30 s, then a growing wait up to 5 minutes; a
// dropped one the browser reconnects by itself. Every message goes to every listener as {state, ev, big?, first}:
// `first` marks the first message of an answer (its `big` list is the past: drawn without motion). A part that starts
// listening while the answer is already running gets one catch-up message {state, ev: [], big: <the kept large
// orders>, first: true} (real past orders with their own times) so its list does not wait for the next order.
// HONESTY: this only passes on what the server sent; it never makes an event.
export const TICKS_URL = "/api/v4/ticks";
export const RETRY_MS = 30000;
export const RETRY_MAX_MS = 300000;
export const BIG_MEM = 40;

export const hub = {es: null, state: "off", first: true, got: false, retryT: null, retryMs: RETRY_MS, subs: new Set(), big: null, vis: false};
const hidden = () => typeof document !== "undefined" && !!document.hidden;
const bigKey = (r) => `${r.t}:${r.s}:${r.side}:${r.usd}`;

function tell(m, only) {
  for (const s of only ? [only] : [...hub.subs]) {
    if (!hub.subs.has(s)) continue;
    try { s.fn(m); } catch (e) { /* one part failing never stops the others */ }
  }
}
/** Keep the large orders the server sent on this answer (newest first, at most BIG_MEM) and its latest sums. */
function keepBig(d) {
  const b = d.big;
  if (!b || typeof b !== "object") return;
  const was = d.first || !hub.big ? {rows: []} : hub.big;
  const rows = was.rows.slice(), seen = new Set(rows.map(bigKey));
  for (const r of Array.isArray(b.rows) ? b.rows : []) if (r && typeof r === "object" && !seen.has(bigKey(r))) { seen.add(bigKey(r)); rows.push(r); }
  rows.sort((x, y) => (Number(y.t) || 0) - (Number(x.t) || 0));
  hub.big = {...was, ...b, rows: rows.slice(0, BIG_MEM)};
}
function watchVis() {
  if (hub.vis || typeof document === "undefined" || typeof document.addEventListener !== "function") return;
  hub.vis = true;
  document.addEventListener("visibilitychange", () => { if (hidden()) close(); else open(); });
}
function open() {
  watchVis();
  const ES = globalThis.EventSource;
  if (hub.es || hub.retryT || !hub.subs.size || hidden()) return;
  if (typeof ES !== "function") { hub.state = "down"; return; }
  let es;
  try { es = new ES(TICKS_URL); } catch (e) { hub.state = "down"; return; }
  hub.es = es; hub.state = "connecting"; hub.first = true; hub.got = false;
  es.onmessage = (ev) => {
    if (hub.es !== es) return;
    let d;
    try { d = JSON.parse(ev.data); } catch (e) { return; }
    if (!d || typeof d !== "object") return;
    hub.retryMs = RETRY_MS;
    hub.state = typeof d.state === "string" ? d.state : "down";
    d.first = hub.first; hub.first = false; hub.got = true;
    keepBig(d);
    tell(d);
  };
  es.onerror = () => {
    if (hub.es !== es) return;
    hub.state = "down"; hub.first = true; hub.got = false;
    tell({state: "down", ev: []});
    if (es.readyState === 2) {                        // refused for good: again later (readyState 0: the browser retries)
      hub.es = null;
      hub.retryT = setTimeout(() => { hub.retryT = null; open(); }, hub.retryMs);
      hub.retryMs = Math.min(RETRY_MAX_MS, hub.retryMs * 2);
    }
  };
}
function close() {
  clearTimeout(hub.retryT); hub.retryT = null;
  if (hub.es) { try { hub.es.close(); } catch (e) { /* already closed */ } hub.es = null; }
  hub.state = "off"; hub.first = true; hub.got = false;
}

/**
 * listenTicks(fn) -> off(): fn(msg) gets every relay message while the page is visible ({state, ev, big?, first}; a
 * dropped connection is told as {state: "down", ev: []}). The first listener opens the page's one connection, the last
 * off() closes it.
 */
export function listenTicks(fn) {
  const s = {fn};
  hub.subs.add(s);
  if (hub.es && hub.got) {                            // the answer is already running: one catch-up message
    const m = {state: hub.state, ev: [], first: true, ...(hub.big ? {big: {...hub.big, rows: hub.big.rows.slice()}} : {})};
    queueMicrotask(() => tell(m, s));
  }
  open();
  return () => {
    if (!hub.subs.delete(s)) return;
    if (!hub.subs.size) close();
  };
}
/** "off" | "connecting" | "live" | "down" */
export const ticksState = () => hub.state;

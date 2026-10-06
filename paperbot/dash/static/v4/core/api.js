// Server access: the same session cookie as the old UI (credentials "same-origin"; a 401 sends the page to /login),
// the old UI's single live stream /api/stream (server-sent events, reused, one connection for every screen), polling
// that pauses while the page is hidden, the server clock, and a tiny event bus.
// Reliability (review 10/06): every request has a time limit (15 s, the heavy reads 30 s): a request that never answers
// (a half-open connection after PC sleep, a Wi-Fi change) fails like any other error, so the next poll asks again
// instead of the number freezing forever. The live stream has a watchdog: the server writes every 3 s, so 12 s of
// silence means the connection is dead even when the browser still calls it open; the page then connects again (also
// at once when the screen is shown again or the network comes back). A tab hidden for 2 minutes lets its stream go
// (Chrome keeps only 6 connections per server over http://) and picks it up when shown again.

export class ApiError extends Error {
  /** kind: "http" (the server answered with an error), "timeout" (no answer in time), "network" (no connection). */
  constructor(path, status, detail, kind = "http") {
    super(detail || `${path} ${status}`);
    this.path = path; this.status = status; this.detail = detail; this.kind = kind;
  }
}

let loginRedirect = false;
function toLogin() {
  if (loginRedirect) return;
  loginRedirect = true;
  // come back to the same v4 screen after logging in (login.html honours ?next=)
  location.href = "/login?next=" + encodeURIComponent(location.pathname + location.hash);
}

// ---------------------------------------------------------------- time limits
export const TIMEOUT_MS = 15000;
export const SLOW_TIMEOUT_MS = 30000;
// the reads the server computes (analysis views, the v4 additions, a strategy's chart, one account's record)
const SLOW_RE = /^\/api\/(analysis\/|v4\/|overlap|breakdown|cards|strategy\/|account\/|levels|trades)/;
/** The time limit of a request to this path (ms). */
export const timeoutFor = (path) => (SLOW_RE.test(String(path)) ? SLOW_TIMEOUT_MS : TIMEOUT_MS);

/** fetch with the time limit and the caller's signal; read(r) turns the answer into the result inside the limit (a
 *  body that stops halfway is a timeout too). A caller's abort stays an AbortError (screens ignore those); a timeout or
 *  a lost connection is an ApiError (screens show it and the next poll asks again). */
async function call(path, init, opts, read) {
  const ms = opts.timeout ?? timeoutFor(path);
  const ac = new AbortController();
  const up = opts.signal;
  const onUp = () => ac.abort();
  if (up) { if (up.aborted) ac.abort(); else up.addEventListener("abort", onUp, {once: true}); }
  let timedOut = false;
  const t = setTimeout(() => { timedOut = true; ac.abort(); }, ms);
  try {
    const r = await fetch(path, {...init, credentials: "same-origin", signal: ac.signal});
    return await read(r);
  } catch (e) {
    if (e instanceof ApiError) throw e;
    if (timedOut) throw new ApiError(path, 0, `응답이 없습니다 (${Math.round(ms / 1000)}초)`, "timeout");
    if ((up && up.aborted) || (e && e.name === "AbortError")) throw e;
    throw new ApiError(path, 0, null, "network");
  } finally {
    clearTimeout(t);
    if (up) up.removeEventListener("abort", onUp);
  }
}

/** GET JSON. opts.signal: AbortSignal (ctx.api passes the screen's own, so a left screen stops waiting); opts.timeout. */
export function api(path, opts = {}) {
  return call(path, {headers: {accept: "application/json"}}, opts, async (r) => {
    if (r.status === 401) { toLogin(); throw new ApiError(path, 401, "로그인이 필요합니다"); }
    if (!r.ok) {
      let d = null;
      try { d = await r.json(); } catch (e) { /* no body */ }
      throw new ApiError(path, r.status, d && typeof d.detail === "string" ? d.detail : null);
    }
    return r.json();
  });
}

/** GET text (the rules documents under /api/doc/<name> are plain text). */
export function apiText(path, opts = {}) {
  return call(path, {}, opts, async (r) => {
    if (r.status === 401) { toLogin(); throw new ApiError(path, 401, "로그인이 필요합니다"); }
    if (!r.ok) throw new ApiError(path, r.status, null);
    return r.text();
  });
}

/** POST JSON (owner writes: room posts, approve/reject, price alerts). Same-origin by construction. A write that gets no
 *  answer in 30 s may still have been saved: the message says to look before trying again. */
export function post(path, body, opts = {}) {
  return call(path, {method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify(body ?? {})},
    {timeout: SLOW_TIMEOUT_MS, ...opts}, async (r) => {
      if (r.status === 401) { toLogin(); throw new ApiError(path, 401, "로그인이 필요합니다"); }
      let d = null;
      try { d = await r.json(); } catch (e) { /* no body */ }
      if (!r.ok) throw new ApiError(path, r.status, (d && typeof d.detail === "string" && d.detail) || `오류 ${r.status}`);
      return d;
    }).catch((e) => {
    if (e instanceof ApiError && e.kind === "timeout") e.detail = "서버가 30초 동안 답하지 않았습니다. 저장됐을 수 있으니 목록을 다시 보고 해 주세요.";
    if (e instanceof ApiError && e.kind === "network") e.detail = "서버에 닿지 못했습니다 (연결 끊김). 연결이 돌아오면 다시 해 주세요.";
    throw e;
  });
}

// ---------------------------------------------------------------- event bus
const handlers = new Map();
export const bus = {
  on(evt, fn) {
    if (!handlers.has(evt)) handlers.set(evt, new Set());
    handlers.get(evt).add(fn);
    return () => handlers.get(evt) && handlers.get(evt).delete(fn);
  },
  emit(evt, data) {
    const set = handlers.get(evt);
    if (!set) return;
    for (const fn of [...set]) {
      try { fn(data); } catch (e) { console.error(`bus ${evt}`, e); }
    }
  },
};

// ---------------------------------------------------------------- the live stream (one per page)
// /api/stream sends every 3 s: {ts, changed: {account_id: [wallet, trades, bust, position]}, trades: [...new closed],
// alerts: [...new], heartbeat: [ts, {...}], room_msg, rooms: {room_id: newest id}, cursor: [trade id, alert row]}. The
// first event after a connect carries every account in `changed`. bus events: "stream" (raw), "stream:state" (below),
// "board:changed" (changed map, when not empty), "trades" (array, when not empty), "alerts" (array, when not empty),
// "rooms" (map, when not empty), "heartbeat" ([ts, data]).
// stream.state: "idle" (not started) | "connecting" | "open" (an event within STREAM_SILENT_MS) | "error" (the browser
// is retrying) | "reconnecting" (the watchdog dropped a silent connection) | "paused" (a hidden tab let it go).
// stream.since: when that state began. "stream:state" is sent on every change, and once more LINK_GRACE_MS into a
// trouble state (the shell shows '대시보드 연결 다시 잡는 중' only after that grace: a 1-second blip stays quiet).
export const STREAM_SILENT_MS = 12000;
export const HIDDEN_CLOSE_MS = 120000;
export const LINK_GRACE_MS = 5000;
const RESUME_MS = 120000;           // a gap shorter than this picks the trades and alerts up where they stopped
const WATCH_MS = 3000;
export const stream = {state: "idle", since: 0, lastEventAt: 0, heartbeat: null, es: null, cursor: null, roomMsg: 0, reconnects: 0,
  /** LIVE means really live: the stream is connected AND the bot's heartbeat is fresh (< 90 s). */
  live() { return this.state === "open" && !!this.heartbeat && Date.now() - Number(this.heartbeat[0]) < 90000; },
  /** The page's own connection to the dashboard is up (an event in the last 12 s). */
  fresh() { return this.state === "open" && Date.now() - this.lastEventAt < STREAM_SILENT_MS; }};
let retryMs = 5000, retryT = null, watchT = null, hiddenAt = null;
function setState(s) {
  if (stream.state === s) return;
  stream.state = s; stream.since = Date.now();
  bus.emit("stream:state", s);
  if (s !== "open" && s !== "paused" && s !== "idle") {
    const at = stream.since;
    setTimeout(() => { if (stream.state === s && stream.since === at) bus.emit("stream:state", s); }, LINK_GRACE_MS + 50);
  }
}
/** The address of a new connection: the cursors of the last one when the gap was short (the trades and alerts in
 *  between arrive in its first event), the room cursor always (the badges of rooms with new messages). */
export function streamUrl(cursor, roomMsg, gapMs) {
  const q = [];
  if (cursor && gapMs != null && gapMs < RESUME_MS) q.push(`trade_id=${Number(cursor[0]) || 0}`, `alert_row=${Number(cursor[1]) || 0}`);
  if (roomMsg) q.push(`room_msg=${Number(roomMsg) || 0}`);
  return "/api/stream" + (q.length ? "?" + q.join("&") : "");
}
function closeStream(next) {
  const es = stream.es;
  stream.es = null;
  if (es) { es.onopen = es.onerror = es.onmessage = null; try { es.close(); } catch (e) { /* closed */ } }
  setState(next);
}
export function startStream() {
  if (stream.es || typeof EventSource === "undefined") return;
  clearTimeout(retryT);
  startWatch();
  const gap = stream.lastEventAt ? Date.now() - stream.lastEventAt : null;
  const es = new EventSource(streamUrl(stream.cursor, stream.roomMsg, gap));
  stream.es = es;
  stream.openAt = Date.now();
  if (stream.state !== "reconnecting" && stream.state !== "error") setState("connecting");
  es.onopen = () => { if (stream.es !== es) return; retryMs = 5000; stream.lastEventAt = Date.now(); setState("open"); };
  es.onerror = () => {
    if (stream.es !== es) return;
    setState("error");
    // the browser retries a dropped connection by itself (readyState 0); a refused one (401, 5xx: readyState 2) is
    // closed for good, so it is restarted here with a growing wait (5 s up to 60 s), after a cheap call that sends an
    // expired session to the login page
    if (es.readyState === 2) {
      stream.es = null;
      clearTimeout(retryT);
      retryT = setTimeout(() => { api("/api/time").catch(() => {}).finally(() => { if (!loginRedirect && !stream.es) startStream(); }); }, retryMs);
      retryMs = Math.min(60000, retryMs * 2);
    }
  };
  es.onmessage = (ev) => {
    if (stream.es !== es) return;
    let d;
    try { d = JSON.parse(ev.data); } catch (e) { return; }
    stream.lastEventAt = Date.now();
    if (Array.isArray(d.cursor)) stream.cursor = d.cursor;
    if (d.room_msg != null) stream.roomMsg = d.room_msg;
    if (stream.state !== "open") setState("open");
    bus.emit("stream", d);
    if (d.heartbeat) { stream.heartbeat = d.heartbeat; bus.emit("heartbeat", d.heartbeat); }
    if (d.changed && Object.keys(d.changed).length) bus.emit("board:changed", d.changed);
    if (Array.isArray(d.trades) && d.trades.length) bus.emit("trades", d.trades);
    if (Array.isArray(d.alerts) && d.alerts.length) bus.emit("alerts", d.alerts);
    if (d.rooms && Object.keys(d.rooms).length) bus.emit("rooms", d.rooms);
  };
}
/** Drop the current connection and open a new one now (the watchdog, the screen shown again, the network back). */
export function reconnectStream() {
  if (loginRedirect) return;
  stream.reconnects++;
  closeStream("reconnecting");
  startStream();
}
/** One look: a hidden tab lets its stream go after HIDDEN_CLOSE_MS; a shown one gets it back, and a connection that
 *  has been silent for STREAM_SILENT_MS (or never opened in that time) is replaced. */
export function checkStream(now = Date.now()) {
  if (loginRedirect || stream.state === "idle") return;
  if (document.visibilityState === "hidden") {
    if (hiddenAt == null) hiddenAt = now;
    if (stream.es && now - hiddenAt >= HIDDEN_CLOSE_MS) { clearTimeout(retryT); closeStream("paused"); }
    return;
  }
  hiddenAt = null;
  if (!stream.es) { if (stream.state === "paused") startStream(); return; }      // (a refused one waits for its retry)
  const last = Math.max(stream.lastEventAt || 0, stream.openAt || 0);
  if (now - last >= STREAM_SILENT_MS) reconnectStream();
}
function startWatch() {
  if (watchT) return;
  watchT = setInterval(() => checkStream(), WATCH_MS);
  document.addEventListener("visibilitychange", () => checkStream());
  window.addEventListener("online", () => { if (document.visibilityState !== "hidden" && stream.es && !stream.fresh()) reconnectStream(); else checkStream(); });
  // a laptop waking up: timers jump; the next look sees the silence at once
  window.addEventListener("pageshow", () => checkStream());
}

// ---------------------------------------------------------------- polling (pauses while the page is hidden)
/** Calls fn now (unless opts.now === false) and every ms while the page is visible; returns a stopper. */
export function poll(fn, ms, opts = {}) {
  let timer = null, stopped = false, busy = false;
  const run = async () => {
    if (stopped || busy) return;
    if (document.visibilityState === "hidden" && opts.hidden !== true) return;
    busy = true;
    try { await fn(); } catch (e) { if (!(e && e.name === "AbortError")) console.warn("poll", e); }
    busy = false;
  };
  const vis = () => { if (document.visibilityState === "visible") run(); };
  if (opts.now !== false) run();
  timer = setInterval(run, ms);
  document.addEventListener("visibilitychange", vis);
  return () => { stopped = true; clearInterval(timer); document.removeEventListener("visibilitychange", vis); };
}

// ---------------------------------------------------------------- the server clock (and the page's version)
let skew = 0;
/** Now in ms by the server's clock (a phone whose clock is off still counts bars right). */
export const serverNow = () => Date.now() + skew;
/** The server's clock, and the fingerprint of the page's code on the server (bus "version", core/version.js). */
export async function syncClock() {
  const t0 = Date.now();
  try {
    const d = await api("/api/time");
    const t1 = Date.now();
    if (d && typeof d.now === "number" && t1 - t0 < 5000) skew = d.now - (t0 + t1) / 2;
    if (d && typeof d.ver === "string") bus.emit("version", d.ver);
  } catch (e) { /* keep the device clock */ }
}

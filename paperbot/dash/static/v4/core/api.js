// Server access: the same session cookie as the old UI (credentials "same-origin"; a 401 sends the page to /login),
// the old UI's single live stream /api/stream (server-sent events, reused, one connection for every screen), polling
// that pauses while the page is hidden, the server clock, and a tiny event bus.

export class ApiError extends Error {
  constructor(path, status, detail) {
    super(detail || `${path} ${status}`);
    this.path = path; this.status = status; this.detail = detail;
  }
}

let loginRedirect = false;
function toLogin() {
  if (loginRedirect) return;
  loginRedirect = true;
  // come back to the same v4 screen after logging in (login.html honours ?next= once the server side lands:
  // NEEDS SERVER, CONTRACT section 6 #8; until then the login page simply ignores it)
  location.href = "/login?next=" + encodeURIComponent(location.pathname + location.hash);
}

/** GET JSON. opts.signal: AbortSignal (ctx.api passes the screen's own, so a left screen stops waiting). */
export async function api(path, opts = {}) {
  const r = await fetch(path, {credentials: "same-origin", signal: opts.signal, headers: {accept: "application/json"}});
  if (r.status === 401) { toLogin(); throw new ApiError(path, 401, "로그인이 필요합니다"); }
  if (!r.ok) {
    let d = null;
    try { d = await r.json(); } catch (e) { /* no body */ }
    throw new ApiError(path, r.status, d && typeof d.detail === "string" ? d.detail : null);
  }
  return r.json();
}

/** GET text (the rules documents under /api/doc/<name> are plain text). */
export async function apiText(path, opts = {}) {
  const r = await fetch(path, {credentials: "same-origin", signal: opts.signal});
  if (r.status === 401) { toLogin(); throw new ApiError(path, 401, "로그인이 필요합니다"); }
  if (!r.ok) throw new ApiError(path, r.status, null);
  return r.text();
}

/** POST JSON (owner writes: room posts, approve/reject, price alerts). Same-origin by construction. */
export async function post(path, body, opts = {}) {
  const r = await fetch(path, {method: "POST", credentials: "same-origin", signal: opts.signal,
    headers: {"content-type": "application/json"}, body: JSON.stringify(body ?? {})});
  if (r.status === 401) { toLogin(); throw new ApiError(path, 401, "로그인이 필요합니다"); }
  let d = null;
  try { d = await r.json(); } catch (e) { /* no body */ }
  if (!r.ok) throw new ApiError(path, r.status, (d && typeof d.detail === "string" && d.detail) || `오류 ${r.status}`);
  return d;
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
// alerts: [...new], heartbeat: [ts, {...}], room_msg, rooms: {room_id: newest id}}. The first event after a connect
// carries every account in `changed`. bus events: "stream" (raw), "stream:state" ("open" | "error"),
// "board:changed" (changed map, when not empty), "trades" (array, when not empty), "alerts" (array, when not empty),
// "rooms" (map, when not empty), "heartbeat" ([ts, data]).
export const stream = {state: "idle", lastEventAt: 0, heartbeat: null, es: null,
  /** LIVE means really live: the stream is connected AND the bot's heartbeat is fresh (< 90 s). */
  live() { return this.state === "open" && !!this.heartbeat && Date.now() - Number(this.heartbeat[0]) < 90000; }};
let retryMs = 5000, retryT = null;
export function startStream() {
  if (stream.es || typeof EventSource === "undefined") return;
  clearTimeout(retryT);
  const es = new EventSource("/api/stream");
  stream.es = es;
  es.onopen = () => { stream.state = "open"; retryMs = 5000; bus.emit("stream:state", "open"); };
  es.onerror = () => {
    stream.state = "error"; bus.emit("stream:state", "error");
    // the browser retries a dropped connection by itself (readyState 0); a refused one (401, 5xx: readyState 2) is
    // closed for good, so it is restarted here with a growing wait (5 s up to 60 s), after a cheap call that sends an
    // expired session to the login page
    if (es.readyState === 2 && stream.es === es) {
      stream.es = null;
      clearTimeout(retryT);
      retryT = setTimeout(() => { api("/api/time").catch(() => {}).finally(() => { if (!loginRedirect) startStream(); }); }, retryMs);
      retryMs = Math.min(60000, retryMs * 2);
    }
  };
  es.onmessage = (ev) => {
    let d;
    try { d = JSON.parse(ev.data); } catch (e) { return; }
    stream.lastEventAt = Date.now();
    if (stream.state !== "open") { stream.state = "open"; bus.emit("stream:state", "open"); }
    bus.emit("stream", d);
    if (d.heartbeat) { stream.heartbeat = d.heartbeat; bus.emit("heartbeat", d.heartbeat); }
    if (d.changed && Object.keys(d.changed).length) bus.emit("board:changed", d.changed);
    if (Array.isArray(d.trades) && d.trades.length) bus.emit("trades", d.trades);
    if (Array.isArray(d.alerts) && d.alerts.length) bus.emit("alerts", d.alerts);
    if (d.rooms && Object.keys(d.rooms).length) bus.emit("rooms", d.rooms);
  };
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

// ---------------------------------------------------------------- the server clock
let skew = 0;
/** Now in ms by the server's clock (a phone whose clock is off still counts bars right). */
export const serverNow = () => Date.now() + skew;
export async function syncClock() {
  const t0 = Date.now();
  try {
    const d = await api("/api/time");
    const t1 = Date.now();
    if (d && typeof d.now === "number" && t1 - t0 < 5000) skew = d.now - (t0 + t1) / 2;
  } catch (e) { /* keep the device clock */ }
}

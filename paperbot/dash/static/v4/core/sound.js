// Live sound (wave 2, owners 10/05 22:45: "v6 chiptune" approved): 8-bit square / 25 %-pulse beeps, ported unchanged
// from the owners' picker (scratchpad/sounds/sound_picker.html: pulse25(), CHIP, chip(), chipRun(), the six motifs
// c_entry / c_tp / c_sl / c_meet / c_liq / c_ms and the continuous layer of single beeps with a third of them short
// runs), through ONE shared output gain (the volume).
// HONESTY: every sound answers one real record. The continuous layer = real Binance USD-M market trades of the 7 coins
// (/api/v4/ticks, dash/more/ticks.py: one server socket for every page, at most ~2 events a second: buy = the upper
// notes, sell = the lower notes, louder for a bigger burst); while that relay is not live (no socket on the server,
// blocked, refused) it falls back by itself to a real price change of a coin in /api/ticker (the store's 5 s poll: one
// beep per coin that moved, up = the upper notes, down = the lower notes, nothing when no price moved); plus the
// DeepSeek / coin-flip accounts' real fills and exits from the live stream; the motifs = our
// own accounts' (기존 36 · 5분봉 · 추가 계좌) real entries (a position that appeared in the stream) and exits (the
// stream's closed trades: profit -> 익절, loss -> 손절, LIQ -> 강제청산), a meeting that really ended with a
// conclusion (/api/rooms: a room's newest message became a new 'decision'), and the D+10 / D+20 / 판정 day of the run
// (/api/summary, once per device). No timer ever makes a sound by itself: the queue's timer only spaces out real
// changes that already arrived (at most ~2 a second) and drops what is too old to mean "now".
// Controls (the speaker button in the header, core/shell.js): off until the first tap (browsers allow sound only
// after a tap); ONE tap on the speaker turns it on and opens the menu (startOnTap), then remembered per device
// (dom.js local): on / off, volume, density (잔잔 / 보통 / 활발) and the night mute 00-07 KST (off by default: the
// owners watch at night; one tick turns it on). The page going hidden suspends the audio and drops the queue; the
// first ticker after it comes back is a new baseline (minutes of drift are not "a tick").
import {bus} from "./api.js";
import {store} from "./store.js";
import {h, local} from "./dom.js";

// ---------------------------------------------------------------- settings (per device)
const KEY = "sound";
export const DENSITY = {
  calm: {ko: "잔잔", gap: 2600},     // ~0.4 beeps / s at most
  normal: {ko: "보통", gap: 1333},   // ~0.75 / s (the picker's mix)
  busy: {ko: "활발", gap: 700},      // ~1.4 / s
};
export const MIN_GAP_MS = 500;       // never more than 2 beeps a second, whatever the density
export const MAX_AGE_MS = 6000;      // a change older than this is not "now" any more: dropped, never played late
export const QUEUE_CAP = 8;
const DEFAULTS = {on: false, vol: 60, density: "normal", night: false};
export const cfg = {...DEFAULTS, ...sanitize(local.get(KEY, {}))};
function sanitize(o) {
  const x = o && typeof o === "object" ? o : {};
  const out = {};
  if (typeof x.on === "boolean") out.on = x.on;
  if (Number.isFinite(Number(x.vol))) out.vol = Math.min(100, Math.max(0, Math.round(Number(x.vol))));
  if (DENSITY[x.density]) out.density = x.density;
  if (typeof x.night === "boolean") out.night = x.night;
  return out;
}
export function setCfg(patch) {
  Object.assign(cfg, sanitize(patch));
  local.set(KEY, {on: cfg.on, vol: cfg.vol, density: cfg.density, night: cfg.night});
  if (master && ctx) master.gain.setTargetAtTime(gainOf(), ctx.currentTime, 0.05);
  applyFeeds();
  bus.emit("sound:cfg", {...cfg});
}
const gainOf = () => Math.pow(cfg.vol / 100, 1.6);           // a gentler slider at the low end
/** 00:00-06:59 KST (UTC+9, no daylight saving). */
export const nightKst = (now) => new Date(Number(now) + 9 * 3600e3).getUTCHours() < 7;

// ---------------------------------------------------------------- the engine (picker v6, unchanged)
let ctx = null, master = null, unlocked = false;
const AC = () => (typeof window !== "undefined" && (window.AudioContext || window.webkitAudioContext)) || null;
const hidden = () => typeof document !== "undefined" && document.hidden;
function ac() {
  if (!ctx) {
    const A = AC();
    if (!A) return null;
    ctx = new A();
    master = ctx.createGain();                               // the ONE output bus: every beep and motif goes here
    master.gain.value = gainOf();
    master.connect(ctx.destination);
  }
  if (ctx.state === "suspended" && !hidden()) ctx.resume().catch(() => {});
  return ctx;
}
let PULSE25 = null;
export function pulse25(c) {
  if (PULSE25) return PULSE25;
  const n = 48, re = new Float32Array(n), im = new Float32Array(n);
  for (let k = 1; k < n; k++) im[k] = (2 / (k * Math.PI)) * Math.sin(k * Math.PI * 0.25);
  PULSE25 = c.createPeriodicWave(re, im); return PULSE25;
}
export const CHIP = [369.99, 440.0, 493.88, 554.37, 659.26, 739.99, 830.61, 987.77];
function chip(f, v, t, bus_, kind) {
  const c = ac(), dest = bus_ || master, o = c.createOscillator(), g = c.createGain(), lp = c.createBiquadFilter();
  if (kind === "pulse") o.setPeriodicWave(pulse25(c)); else o.type = "square";
  o.frequency.value = f; lp.type = "lowpass"; lp.frequency.value = 9000;
  const len = 0.09 + Math.random() * 0.06, peak = Math.max(v * 0.16, 0.0002);
  g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(peak, t + 0.002);
  g.gain.setValueAtTime(peak, t + 0.018); g.gain.exponentialRampToValueAtTime(0.0001, t + len);
  o.connect(lp).connect(g).connect(dest); o.start(t); o.stop(t + len + 0.02);
}
function chipRun(fs, gaps, v, bus_) { const c = ac(); let t = c.currentTime + 0.01; fs.forEach((f, i) => { chip(f, v, t, bus_, i % 2 ? "pulse" : "square"); t += gaps[i] || 0.1; }); }
/** The owners' six event sounds (picker S.c_*), note for note. */
export const MOTIFS = {
  c_entry: [[987.77], [], 0.9],                                                       // 진입: one bright ting
  c_tp: [[493.88, 659.26, 987.77], [0.08, 0.08], 0.9],                                // 익절: rising 띠-리-링
  c_sl: [[659.26, 440.0], [0.12], 0.8],                                               // 손절: falling 띠-링
  c_liq: [[987.77, 830.61, 659.26, 493.88, 369.99], [0.055, 0.055, 0.055, 0.055], 0.9], // 강제청산: fast fall
  c_meet: [[554.37, 739.99], [0.14], 0.75],                                           // 회의 결론: soft 띠-링
  c_ms: [[493.88, 622.25, 739.99, 987.77, 1244.5], [0.07, 0.07, 0.07, 0.07], 0.85],   // 기념
};
const up = (f, st) => f * Math.pow(2, st / 12);

/** The real sound output: sink("beep", {f, v, pulse}) one chip, sink("run", {fs, gaps, v}) a chipRun. Tests swap it
 *  through _test.setSink (node has no AudioContext). */
let sink = (kind, a) => {
  const c = ac();
  if (!c) return;
  if (kind === "beep") chip(a.f, a.v, c.currentTime + 0.01, master, a.pulse ? "pulse" : "square");
  else chipRun(a.fs, a.gaps, a.v, master);
};

// ---------------------------------------------------------------- the gate: may a real event sound right now?
export function canPlay(now = Date.now()) {
  return cfg.on && unlocked && !hidden() && !(cfg.night && nightKst(now));
}

// ---------------------------------------------------------------- the continuous layer (real changes only)
/**
 * A queue that spaces real changes out: push({key, dir, size, at}) -> one entry per key (a coin moving again
 * replaces its waiting entry); next(now) -> {item} to play now, {wait} ms until the next may play, or null (empty).
 * The biggest waiting move goes first; anything older than MAX_AGE_MS is dropped.
 */
export function makeLayer(gapFn = () => DENSITY[cfg.density].gap) {
  const q = new Map();
  let last = -Infinity, nextGap = 0;
  return {
    push(it) {
      q.delete(it.key);
      q.set(it.key, it);
      if (q.size > QUEUE_CAP) {                                 // drop the smallest waiting move
        let lo = null;
        for (const x of q.values()) if (!lo || x.size < lo.size) lo = x;
        q.delete(lo.key);
      }
    },
    next(now) {
      for (const [k, x] of q) if (now - x.at > MAX_AGE_MS) q.delete(k);
      if (!q.size) return null;
      if (now - last < nextGap) return {wait: nextGap - (now - last)};
      let best = null;
      for (const x of q.values()) if (!best || x.size > best.size) best = x;
      q.delete(best.key);
      last = now;
      nextGap = Math.max(MIN_GAP_MS, gapFn() * (0.6 + Math.random() * 0.8));   // the picker's uneven spacing
      return {item: best};
    },
    clear() { q.clear(); },
    get size() { return q.size; },
  };
}
const layer = makeLayer();
let layerT = null;
function pump() {
  clearTimeout(layerT); layerT = null;
  const now = Date.now();
  if (!canPlay(now)) { layer.clear(); return; }
  const r = layer.next(now);
  if (!r) return;                                               // empty: no timer left running
  if (r.item) { const b = beepOf(r.item); sink(b.fs ? "run" : "beep", {...b, src: r.item.src, key: r.item.key}); layerT = setTimeout(pump, MIN_GAP_MS); return; }
  layerT = setTimeout(pump, Math.max(30, r.wait));
}
/** A layer item -> the notes. dir > 0: the upper four CHIP notes, dir < 0: the lower four; the coin picks the note
 *  (each coin keeps its own voice); a big move (size >= 1.5 x its usual move) plays a short run of 2-4 notes that
 *  climbs for up and falls for down; louder for a bigger move. */
export function beepOf(it) {
  const region = it.dir > 0 ? CHIP.slice(4) : CHIP.slice(0, 4);
  const f = region[Math.abs(it.voice | 0) % 4];
  const v = 0.55 + 0.35 * Math.min(1, (it.size || 1) / 3);
  const k = it.size >= 4 ? 4 : it.size >= 2.5 ? 3 : it.size >= 1.5 ? 2 : 1;
  if (k === 1) return {f, v, pulse: !!it.pulse};
  const fs = [f], gaps = [];
  for (let i = 1; i < k; i++) { fs.push(up(fs[i - 1], Math.sign(it.dir) * [3, 4, 5, 7][Math.floor(Math.random() * 4)])); gaps.push(0.07 + Math.random() * 0.11); }
  return {fs: fs.map((x) => Math.min(Math.max(x, 330), 1100)), gaps, v};
}

// ---------------------------------------------------------------- prices -> the layer
const px = {base: null, ema: {}};
/**
 * One ticker answer {SYM: {c, mark, ...}} -> the coins whose price really moved since the previous answer, as layer
 * items. The first answer (and the first after the page was hidden) is only a baseline. size = the move over the
 * coin's usual move (an average of its recent moves), so a quiet coin and a jumpy one both have a 1 = "normal".
 */
export function priceMoves(tk, now = Date.now(), state = px) {
  const out = [];
  if (!tk || typeof tk !== "object") return out;
  const syms = Object.keys(tk).sort();
  const cur = {};
  for (const s of syms) {
    const t = tk[s];
    const p = t ? Number(t.c ?? t.mark) : NaN;
    if (Number.isFinite(p) && p > 0) cur[s] = p;
  }
  const prev = state.base;
  state.base = cur;
  if (!prev) return out;
  syms.forEach((s, i) => {
    const a = prev[s], b = cur[s];
    if (a == null || b == null || a === b) return;              // nothing changed: no sound
    const r = Math.abs(b / a - 1);
    const e = state.ema[s];
    const size = e && e.n >= 3 && e.v > 0 ? r / e.v : 1;
    state.ema[s] = e ? {v: e.v * 0.8 + r * 0.2, n: e.n + 1} : {v: r, n: 1};
    out.push({key: "px:" + s, dir: b > a ? 1 : -1, size, voice: i, at: now, src: "price"});
  });
  return out;
}

// ---------------------------------------------------------------- market trades -> the layer (server relay)
// /api/v4/ticks (dash/more/ticks.py): ONE Binance aggTrade socket on the server shared by every page, at most ~2 events
// a second, each {s, side, b, usd, n, p, t}: the coin whose traded notional ran furthest above its usual in that half
// second, its side (more taker buys or sells) and size bucket b 1-4. Opened only while the sound is on, unlocked, the
// page visible and not in the night mute (the server closes its socket a minute after the last page left). While it is live the layer
// follows these trades (the same queue, spacing and density as before); when it is not (state "connecting" / "down",
// a refused or dropped answer, nothing heard for 15 s) the /api/ticker price changes above feed the layer again.
export const TICK_SYMS = ["BCHUSDT", "BTCUSDT", "DOGEUSDT", "ETHUSDT", "LTCUSDT", "SOLUSDT", "XRPUSDT"];  // sorted: each coin keeps priceMoves' voice
/** size bucket -> layer size (beepOf): 1-2 one beep (2 louder), 3 a two-note run, 4 a three-note run, the loudest. */
export const BUCKET_SIZE = {1: 1, 2: 1.3, 3: 1.6, 4: 3};
export const TICK_FRESH_MS = 15000;
export const ticks = {es: null, state: "off", at: 0, retryMs: 30000, retryT: null};
/** Are real market trades feeding the layer right now (else the ticker price changes do)? */
export const tradesLive = (now = Date.now()) => ticks.state === "live" && now - ticks.at < TICK_FRESH_MS;
/** Relay events -> layer items (buy: dir 1 = the upper notes, sell: dir -1 = the lower). Unknown coins / sides: none. */
export function tickItems(evs, now = Date.now()) {
  const out = [];
  for (const e of Array.isArray(evs) ? evs : []) {
    if (!e || typeof e !== "object") continue;
    const voice = TICK_SYMS.indexOf(e.s);
    if (voice < 0 || (e.side !== "buy" && e.side !== "sell")) continue;
    out.push({key: "tk:" + e.s, dir: e.side === "buy" ? 1 : -1, size: BUCKET_SIZE[e.b] || 1, voice, at: now, src: "trade"});
  }
  return out;
}
/** One relay message {state, ev}: remembers the state and feeds the layer while it is live. */
export function onTicks(msg, now = Date.now()) {
  if (!msg || typeof msg !== "object") return [];
  ticks.state = typeof msg.state === "string" ? msg.state : "down";
  ticks.at = now;
  if (ticks.state !== "live") return [];
  const items = tickItems(msg.ev, now);
  feed(items);
  return items;
}
function ticksOpen() {
  const ES = globalThis.EventSource;
  if (ticks.es || ticks.retryT || !cfg.on || !unlocked || hidden() || (cfg.night && nightKst(Date.now())) || typeof ES !== "function") return;
  let es;
  try { es = new ES("/api/v4/ticks"); } catch (e) { ticks.state = "down"; return; }
  ticks.es = es; ticks.state = "connecting";
  es.onmessage = (ev) => {
    let d;
    try { d = JSON.parse(ev.data); } catch (e) { return; }
    if (ticks.es !== es) return;
    ticks.retryMs = 30000;
    onTicks(d);
  };
  es.onerror = () => {
    if (ticks.es !== es) return;
    ticks.state = "down";                         // the ticker layer takes over until the relay says "live" again
    if (es.readyState === 2) {                     // refused for good (401, 404, 5xx): again later, with a growing wait
      ticks.es = null;
      ticks.retryT = setTimeout(() => { ticks.retryT = null; ticksOpen(); }, ticks.retryMs);
      ticks.retryMs = Math.min(300000, ticks.retryMs * 2);
    }                                              // (readyState 0: the browser reconnects by itself)
  };
}
function ticksClose() {
  clearTimeout(ticks.retryT); ticks.retryT = null;
  if (ticks.es) { try { ticks.es.close(); } catch (e) { /* already closed */ } ticks.es = null; }
  ticks.state = "off";
}
/** The night mute (00-07 KST, when ticked) closes the stream too: nothing is heard, so the server's socket may close.
 *  Checked with every ticker poll (5 s) and every setting change, so it opens again by itself at 07:00. */
function ticksSync(now = Date.now()) {
  if (cfg.night && nightKst(now)) { if (ticks.es || ticks.retryT) ticksClose(); }
  else ticksOpen();
}

// ---------------------------------------------------------------- stream records -> motifs / layer
const MOTIF_KINDS = new Set(["strategy", "reel", "copy", "newlab"]);       // 기존 36 · 5분봉 · 추가 계좌
const MOTIF_GROUPS = new Set(["core", "reel", "extra"]);
let kinds = {b: null, m: new Map()};          // account_id -> kind, rebuilt when the board object changes
function kindOf(id) {
  const b = store.get("board");
  if (b && b !== kinds.b && Array.isArray(b.accounts)) kinds = {b, m: new Map(b.accounts.map((x) => [x.account_id, x.kind]))};
  return kinds.m.get(id) || null;
}
/** Is this account's event a motif (ours) or a layer beep (DeepSeek, coin flips, unknown)? */
export function ours(row) {
  const k = row.kind || kindOf(row.account_id);
  if (k) return MOTIF_KINDS.has(k);
  return !!row.group && MOTIF_GROUPS.has(row.group);
}
/** A closed trade -> "c_liq" | "c_tp" | "c_sl". */
export function exitMotif(t) {
  if (t.exit_reason === "LIQ") return "c_liq";
  return Number(t.pnl) > 0 ? "c_tp" : "c_sl";
}
const ORDER = ["c_liq", "c_ms", "c_meet", "c_tp", "c_sl", "c_entry"];
const MOTIF_COOLDOWN_MS = 1200;
const lastMotif = {};
/** A batch of real events (one stream message): at most two different motifs, the rarest first, 450 ms apart, and
 *  the same motif at most once per 1.2 s (a burst of fills is one sound, not twenty). */
export function playMotifs(names, now = Date.now()) {
  if (!canPlay(now)) return [];
  const pick = ORDER.filter((n) => names.includes(n) && !(now - (lastMotif[n] || -Infinity) < MOTIF_COOLDOWN_MS)).slice(0, 2);
  pick.forEach((n, i) => {
    lastMotif[n] = now;
    const [fs, gaps, v] = MOTIFS[n];
    const go = () => { if (canPlay()) sink("run", {fs, gaps, v, name: n}); };
    if (i === 0) go(); else setTimeout(go, 450 * i);
  });
  return pick;
}
function feed(items) {
  if (!items.length) return;
  if (!canPlay()) { layer.clear(); return; }
  for (const it of items) layer.push(it);
  if (!layerT) pump();
}

/** Closed trades from the stream. */
const tradeSeen = new Set();          // trade ids already heard (the stream and the terminal's onFill never double)
export function onTrades(rows, now = Date.now()) {
  const motifs = [], beeps = [];
  for (const t of Array.isArray(rows) ? rows : []) {
    if (!t || !t.account_id) continue;
    if (t.id != null) {
      if (tradeSeen.has(t.id)) continue;
      tradeSeen.add(t.id);
      if (tradeSeen.size > 600) tradeSeen.delete(tradeSeen.values().next().value);
    }
    if (ours(t)) motifs.push(exitMotif(t));
    else beeps.push({key: "acct:" + t.account_id, dir: t.exit_reason !== "LIQ" && Number(t.pnl) > 0 ? 1 : -1, size: 1,
      voice: hashVoice(t.account_id), pulse: true, at: now, src: "fill"});
  }
  feed(beeps);
  return playMotifs(motifs, now);
}
const hashVoice = (s) => { let x = 0; for (const ch of String(s)) x = (x * 31 + ch.charCodeAt(0)) | 0; return Math.abs(x); };

// entries: a position that appears in the stream's changed rows (the first sighting of an account is the baseline)
const posSeen = new Map();            // account_id -> entry key ("" = flat)
const posKey = (p) => (p ? String(p.entry_time ?? p.entry ?? 1) + ":" + (p.symbol || "") : "");
export function onBoardChanged(ch, now = Date.now()) {
  const motifs = [], beeps = [];
  if (!ch || typeof ch !== "object") return [];
  for (const [id, x] of Object.entries(ch)) {
    if (!Array.isArray(x)) continue;
    const pos = x[3] || null, k = posKey(pos);
    const had = posSeen.has(id), before = posSeen.get(id);
    posSeen.set(id, k);
    if (!had || !k || k === before) continue;                   // baseline, flat, or the same position
    if (ours({account_id: id})) motifs.push("c_entry");
    else beeps.push({key: "acct:" + id, dir: Number(pos.side) > 0 ? 1 : -1, size: 1, voice: hashVoice(id), pulse: true, at: now, src: "fill"});
  }
  feed(beeps);
  return playMotifs(motifs, now);
}
function seedPositions(b) {
  if (!b || !Array.isArray(b.accounts)) return;
  for (const a of b.accounts) if (!posSeen.has(a.account_id)) posSeen.set(a.account_id, posKey(a.position));
}

// meetings: a room whose newest message is a new 'decision' (the first look at the rooms is the baseline)
const roomSeen = new Map();
export function onRooms(ov, now = Date.now()) {
  const rooms = ov && Array.isArray(ov.rooms) ? ov.rooms : [];
  let hit = false;
  for (const r of rooms) {
    const had = roomSeen.has(r.room_id), before = roomSeen.get(r.room_id);
    roomSeen.set(r.room_id, Number(r.last_id) || 0);
    if (had && Number(r.last_id) > before && r.last_kind === "decision") hit = true;
  }
  return hit ? playMotifs(["c_meet"], now) : [];
}

// milestones: D+10, D+20 and the verdict day (summary.restart), each once per device
export const MILESTONES = [10, 20];
export function milestoneOf(s) {
  const rs = s && s.restart;
  if (!rs || !rs.ready || !Number.isFinite(Number(rs.day))) return null;
  const d = Number(rs.day), of = Number(rs.of) || 30;
  if (d === of) return `verdict-${rs.verdict_ts || of}`;
  return MILESTONES.includes(d) ? `d${d}-${rs.verdict_ts || ""}` : null;
}
export function onSummary(s, now = Date.now()) {
  const m = milestoneOf(s);
  if (!m || !canPlay(now)) return [];
  const done = local.get("sound-ms", []);
  if (Array.isArray(done) && done.includes(m)) return [];
  local.set("sound-ms", [...(Array.isArray(done) ? done : []), m].slice(-10));
  return playMotifs(["c_ms"], now);
}

// ---------------------------------------------------------------- wiring
let feeds = null, roomsT = null;
function applyFeeds() {
  if (cfg.on && !feeds) {
    feeds = [
      // polled every 5 s while the sound is on; heard only while the market-trade relay is not live (the fallback),
      // and always read so the baseline stays fresh for the moment it takes over
      store.watch("ticker", (tk) => { ticksSync(); if (!tk) return; const mv = priceMoves(tk); if (!tradesLive()) feed(mv); }),
      bus.on("trades", (rows) => onTrades(rows)),
      bus.on("board:changed", (ch) => onBoardChanged(ch)),
      bus.on("rooms", () => {                                  // a room has new messages: look once (debounced)
        clearTimeout(roomsT);
        roomsT = setTimeout(() => store.refresh("rooms").then((v) => onRooms(v)).catch(() => {}), 1200);
      }),
      store.watch("summary", (s) => { if (s) onSummary(s); }),
    ];
    seedPositions(store.get("board"));
    store.need("rooms", 60000).then((v) => onRooms(v)).catch(() => {});     // the baseline of the rooms
    ticksSync();
  } else if (!cfg.on && feeds) {
    for (const off of feeds) off();
    feeds = null;
    ticksClose();
    clearTimeout(roomsT);
    layer.clear(); px.base = null;
  } else if (cfg.on) ticksSync();                               // the night mute ticked / unticked
}
function unlock() {
  if (!cfg.on) return;
  if (ac()) { unlocked = true; ticksOpen(); bus.emit("sound:cfg", {...cfg}); }
}
let started = false;
export function startSound() {
  if (started || typeof document === "undefined") return;
  started = true;
  // browsers start audio only from a tap: a remembered "on" waits for the first tap anywhere on the page
  const first = () => { unlock(); if (unlocked) { document.removeEventListener("pointerdown", first, true); document.removeEventListener("keydown", first, true); } };
  document.addEventListener("pointerdown", first, true);
  document.addEventListener("keydown", first, true);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) { clearTimeout(layerT); layerT = null; layer.clear(); px.base = null; ticksClose(); if (ctx) ctx.suspend().catch(() => {}); }
    else if (cfg.on) { if (ctx) ctx.resume().catch(() => {}); ticksOpen(); }
  });
  applyFeeds();
}
/** Is the sound waiting for the first tap (on, but the browser has not allowed audio yet)? */
export const waiting = () => cfg.on && !unlocked;
/** The 🔊 tap that opens the menu: an off sound turns on and is unlocked by this very tap (true when it switched on).
 *  An on sound is left as it is (no second unlock, no change). */
export function startOnTap() {
  if (cfg.on) return false;
  setCfg({on: true});
  unlock();
  return true;
}

// ---------------------------------------------------------------- 화면 켜두기 (Screen Wake Lock)
// A phone that locks its screen stops the page and its sound. With this ticked (off by default; a per-device choice
// on this device) the page asks the browser to keep the screen on while the sound is on, and asks again when the page
// comes back to the front (the browser drops the lock whenever the page is hidden). No API, no option.
const wake = {on: local.get("snd-wake", false) === true, lock: null, asking: false};
export const wakeSupported = () => typeof navigator !== "undefined" && !!navigator.wakeLock && typeof navigator.wakeLock.request === "function";
const wakeFree = (l) => { try { l.release().catch(() => {}); } catch (e) { /* already gone */ } };
async function wakeGet() {
  // one request at a time (a tick and the page coming back can ask together: two locks, one never released)
  if (!wake.on || !cfg.on || wake.lock || wake.asking || !wakeSupported() || (typeof document !== "undefined" && document.hidden)) return;
  wake.asking = true;
  let l = null;
  try { l = await navigator.wakeLock.request("screen"); } catch (e) { l = null; }
  wake.asking = false;
  if (!l) return;
  if (!wake.on || !cfg.on || wake.lock) { wakeFree(l); return; }      // turned off while the browser was asking
  wake.lock = l;
  try { l.addEventListener("release", () => { if (wake.lock === l) wake.lock = null; }); } catch (e) { /* no event: fine */ }
}
function wakeDrop() {
  const l = wake.lock;
  wake.lock = null;
  if (l) wakeFree(l);
}
const wakeSync = () => { if (wake.on && cfg.on) wakeGet(); else wakeDrop(); };
/** Turn 화면 켜두기 on / off (remembered on this device only). */
export function setWake(on) { wake.on = !!on; local.set("snd-wake", wake.on); wakeSync(); }
export const wakeOn = () => wake.on;
if (typeof document !== "undefined") document.addEventListener("visibilitychange", () => { if (!document.hidden) wakeGet(); });

// ---------------------------------------------------------------- the header button + popover
export function soundButton() {
  const icon = h("span", {class: "snd-ic", "aria-hidden": "true"});
  const btn = h("button", {class: "snd-btn", id: "sndbtn", type: "button", "aria-haspopup": "dialog", "aria-expanded": "false",
    "aria-controls": "sndpop"}, icon);
  const onBox = h("input", {type: "checkbox", id: "snd-on"});
  const vol = h("input", {type: "range", min: "0", max: "100", step: "5", id: "snd-vol", "aria-label": "소리 크기"});
  const dens = h("div", {class: "seg", role: "group", "aria-label": "소리 빈도"},
    Object.entries(DENSITY).map(([id, d]) => h("button", {type: "button", dataset: {d: id}, onclick: () => setCfg({density: id})}, d.ko)));
  const night = h("input", {type: "checkbox", id: "snd-night"});
  const wakeBox = h("input", {type: "checkbox", id: "snd-wake", disabled: !wakeSupported()});
  const why = h("p", {class: "note snd-why"});
  const pop = h("div", {class: "snd-pop", id: "sndpop", role: "dialog", "aria-label": "실시간 소리", hidden: true},
    h("label", {class: "snd-row snd-main"}, onBox, h("b", null, "실시간 소리")),
    h("label", {class: "snd-row"}, h("span", {class: "k"}, "크기"), vol),
    h("div", {class: "snd-row"}, h("span", {class: "k"}, "빈도"), dens),
    h("label", {class: "snd-row"}, night, h("span", null, "밤 00~07시(한국)엔 끄기")),
    h("label", {class: "snd-row"}, wakeBox, h("span", null, wakeSupported() ? "화면 켜두기 (휴대폰이 잠들면 소리도 멈춤)" : "화면 켜두기 · 이 기기는 지원 안 함")),
    why,
    h("p", {class: "note"}, "바탕음 = 바이낸스에서 실제로 체결된 거래 (사는 쪽이 많으면 높은 음, 파는 쪽이 많으면 낮은 음, 크게 몰리면 더 크게). 연결이 안 되면 코인 가격이 움직일 때 한 번씩. 우리 계좌의 진입·익절·손절·강제청산, 회의 결론, D+10·D+20·판정 날엔 정해 둔 소리. 꾸민 소리는 없습니다."));
  const wrap = h("div", {class: "snd"}, btn, pop);
  const paint = () => {
    const on = cfg.on, wait = waiting(), mute = on && cfg.night && nightKst(Date.now());
    btn.dataset.state = !on ? "off" : wait ? "wait" : mute ? "night" : "on";
    const t = !on ? "실시간 소리 꺼짐" : wait ? "실시간 소리 켜짐 · 화면을 한 번 누르면 들립니다" : mute ? "실시간 소리 · 밤이라 쉬는 중 (07시부터)" : "실시간 소리 켜짐";
    btn.title = t; btn.setAttribute("aria-label", t + (on ? ". 누르면 설정" : ". 누르면 켜지고 설정이 열립니다"));
    onBox.checked = on; vol.value = String(cfg.vol); night.checked = cfg.night; wakeBox.checked = wake.on;
    for (const b of dens.children) b.setAttribute("aria-pressed", String(b.dataset.d === cfg.density));
    why.textContent = !on ? "꺼져 있습니다." : mute ? "지금은 밤이라 쉬는 중입니다 (07시부터 다시)." : wait ? "화면을 한 번 누르면 소리가 시작됩니다." : "켜져 있습니다. 실제로 일이 생길 때만 소리가 납니다.";
  };
  const setOpen = (open) => {
    pop.hidden = !open; btn.setAttribute("aria-expanded", String(open));
    if (open) paint();
  };
  // one tap starts it (gap batch B, owners were told "🔊 한 번 누르면 시작"): a tap that OPENS the menu while the sound
  // is off turns it on (the tap itself lets the browser play) and the menu shows it ticked; a tap that closes the menu
  // only closes it, so an owner who just unticked it there keeps the quiet.
  btn.addEventListener("click", () => {
    const opening = pop.hidden;
    if (opening) startOnTap();
    setOpen(opening);
  });
  onBox.addEventListener("change", () => { setCfg({on: onBox.checked}); if (onBox.checked) unlock(); });
  vol.addEventListener("input", () => setCfg({vol: Number(vol.value)}));
  night.addEventListener("change", () => setCfg({night: night.checked}));
  wakeBox.addEventListener("change", () => setWake(wakeBox.checked));
  document.addEventListener("pointerdown", (e) => { if (!pop.hidden && !wrap.contains(e.target)) setOpen(false); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !pop.hidden) { setOpen(false); btn.focus(); } });
  bus.on("sound:cfg", () => { paint(); wakeSync(); });
  bus.on("route", () => setOpen(false));
  wakeSync();
  paint();
  setInterval(paint, 60000);           // the night mute starts / ends on the clock (the label only, no sound)
  return wrap;
}

// ---------------------------------------------------------------- for the terminal screen and tests
/** The terminal (builder A) may call this for a fill it shows: the same rules as the stream (ours -> motif, others ->
 *  one layer beep). Only for a REAL fill record. */
export function onFill(row) {
  if (!row || !row.account_id) return [];
  if (row.exit_time) return onTrades([row]);
  const pos = row.position || row;
  if (!posSeen.has(row.account_id)) posSeen.set(row.account_id, "");      // the caller says it is new: not a baseline
  return onBoardChanged({[row.account_id]: [null, null, null, pos]});
}
export const _test = {
  setSink(fn) { sink = fn; },
  setKinds(obj) { kinds = {b: kinds.b, m: new Map(Object.entries(obj))}; },
  unlock(v = true) { unlocked = v; },
  layer, px, posSeen, roomSeen, lastMotif, ticks, ticksOpen, ticksClose, ticksSync,
  reset() { ticksClose(); ticks.retryMs = 30000; tradeSeen.clear(); layer.clear(); px.base = null; px.ema = {}; posSeen.clear(); roomSeen.clear(); for (const k of Object.keys(lastMotif)) delete lastMotif[k]; clearTimeout(layerT); layerT = null; },
};

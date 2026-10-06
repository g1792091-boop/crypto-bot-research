// Shared server data, fetched once for every screen that watches it. A key is polled only while someone watches it
// (and never while the page is hidden); the live stream refreshes the board and the rooms as soon as they change.
// store.watch(key, fn) -> unwatch; fn(value, key) runs now when a value is cached and after every refresh.
import {api, bus, poll} from "./api.js";
import {setStrategyNames} from "./fmt.js";

// key -> [path, poll every ms]
const SOURCES = {
  board: ["/api/board", 60000],
  summary: ["/api/summary", 60000],
  health: ["/api/analysis/health", 60000],
  status: ["/api/status", 60000],
  ticker: ["/api/ticker", 5000],
  office: ["/api/office", 6000],
  rooms: ["/api/rooms", 20000],
  usage: ["/api/agents/usage", 60000],
  checkpoint: ["/api/checkpoint", 600000],
  debate: ["/api/debate", 300000],
  levwhy: ["/api/levwhy", 30000],
};

const cache = {};          // key -> {v, at, okAt, err}: at = the last try, okAt = the last good answer
const subs = {};           // key -> Set(fn)
const stops = {};          // key -> poll stopper
const inflight = {};

async function load(key) {
  const src = SOURCES[key];
  if (!src) throw new Error("unknown store key " + key);
  if (inflight[key]) return inflight[key];
  inflight[key] = (async () => {
    try {
      const v = await api(src[0]);
      // the 36 names + the server labels for DeepSeek and the reel (names_ko = groups.label_ko, the Telegram names)
      if (key === "board" && v && (v.strategy_ko || v.names_ko)) setStrategyNames({...(v.strategy_ko || {}), ...(v.names_ko || {})});
      cache[key] = {v, at: Date.now(), okAt: Date.now(), err: null};
      notify(key);
      return v;
    } catch (e) {
      cache[key] = {...(cache[key] || {}), err: e, at: Date.now()};
      notify(key);
      throw e;
    } finally {
      delete inflight[key];
    }
  })();
  return inflight[key];
}
function notify(key) {
  for (const fn of [...(subs[key] || [])]) {
    try { fn(cache[key] && cache[key].v, key, cache[key] && cache[key].err); } catch (e) { console.error("store " + key, e); }
  }
}

export const store = {
  /** The cached value (or undefined). */
  get: (key) => cache[key] && cache[key].v,
  /** {v, at (the last try, ms), okAt (the last good answer, ms), err (the last try's error, null after a good one)}:
   *  a screen tells 불러오는 중 (no v, no err) from 못 불러옴 (err) from a real empty answer (v) with it (ui.loadState). */
  meta: (key) => cache[key] || {},
  /** Fetch now (returns the value; throws on error). */
  refresh: (key) => load(key),
  /** Watch a key: fn(value, key, err). Starts its polling while watched. Returns the unwatch function. */
  watch(key, fn) {
    if (!SOURCES[key]) throw new Error(`store.watch: unknown key "${key}" (core/store.js SOURCES)`);
    (subs[key] ||= new Set()).add(fn);
    if (cache[key] && cache[key].v !== undefined) { try { fn(cache[key].v, key, cache[key].err); } catch (e) { console.error(e); } }
    if (!stops[key]) {
      const [, ms] = SOURCES[key];
      const stale = !cache[key] || Date.now() - (cache[key].at || 0) > ms;
      stops[key] = poll(() => load(key).catch(() => {}), ms, {now: stale});
    }
    return () => {
      subs[key] && subs[key].delete(fn);
      if (subs[key] && !subs[key].size && stops[key] && !KEEP.has(key)) { stops[key](); delete stops[key]; }
    };
  },
  /** Promise of a value: cached when fresh enough (maxAgeMs), else fetched. */
  async need(key, maxAgeMs = 30000) {
    const c = cache[key];
    if (c && c.v !== undefined && Date.now() - (c.okAt || 0) < maxAgeMs) return c.v;
    return load(key);
  },
  /** The current mark price of a coin (from the ticker key; null when unknown). */
  mark(sym) {
    const t = cache.ticker && cache.ticker.v && cache.ticker.v[sym];
    return t ? (t.mark ?? t.c ?? null) : null;
  },
};

// the shell keeps these polled for the whole session (top chip, health dot, banner, board totals)
const KEEP = new Set(["board", "summary", "health", "status"]);

// The live stream's `changed` map carries exactly the four fields that move between polls ({account_id: [wallet,
// trades, bust, position]}), so the cached board is patched in place from it instead of downloading the whole board
// (about 220 KB for 331 accounts) on every 3-second event; the rest of a row (win rate, drawdown, P&L) comes with the
// 60 s poll. An account the board does not have yet (a new extra) brings one full fetch, at most every 15 s.
const BOARD_MIN_GAP = 15000;
let boardT = null, roomsT = null;
function boardSoon() {
  if (document.visibilityState === "hidden" || boardT) return;      // the poll refreshes when the page is shown again
  const age = Date.now() - ((cache.board && cache.board.at) || 0);
  boardT = setTimeout(() => { boardT = null; load("board").catch(() => {}); }, Math.max(400, BOARD_MIN_GAP - age));
}
const samePos = (p, q) => p === q || (p && q && JSON.stringify(p) === JSON.stringify(q));
bus.on("board:changed", (ch) => {
  const c = cache.board;
  if (!c || !c.v || !Array.isArray(c.v.accounts) || !ch) return;
  let n = 0;
  const seen = new Set();
  const accounts = c.v.accounts.map((a) => {
    seen.add(a.account_id);
    const x = ch[a.account_id];
    if (!Array.isArray(x)) return a;
    const [wallet, trades, bust, position] = x;
    if (a.wallet === wallet && a.trades === trades && !!a.bust === !!bust && samePos(a.position, position)) return a;
    n++;
    return {...a, wallet, trades, bust: !!bust, position: position || null};
  });
  if (Object.keys(ch).some((id) => !seen.has(id))) boardSoon();
  if (!n) return;
  cache.board = {...c, v: {...c.v, accounts}};       // `at` stays the full fetch's time
  notify("board");
});
bus.on("rooms", () => {
  clearTimeout(roomsT);
  roomsT = setTimeout(() => {
    for (const k of ["rooms", "office"]) if (subs[k] && subs[k].size) load(k).catch(() => {});
  }, 800);
});
bus.on("alerts", () => { load("status").catch(() => {}); });
// The page's own connection back (core/api.js stream:state "open", e.g. after a sleep or a dashboard restart): every
// polled key whose last try failed is asked again at once, so the self-retrying boxes ({key}) and the '불러오지 못함 ·
// n분 전 자료' notes clear within seconds of the server being back, not at the next poll (up to 10 minutes away)
bus.on("stream:state", (s) => {
  if (s !== "open") return;
  for (const k of Object.keys(stops)) if (cache[k] && cache[k].err && !inflight[k]) load(k).catch(() => {});
});

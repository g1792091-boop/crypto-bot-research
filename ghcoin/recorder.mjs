// GH Coin call recorder (docs/ghcoin-recorder.md).
//
// Runs GH Coin's own code, unchanged, from a pinned checkout of the branch claude/eloquent-johnson-nnt7gh
// (GHCOIN_DIR, default /opt/ghcoin): gh-coin/combo.js (analyzeTF on 5m/15m/1h/4h, planOf), gh-coin/lib/patterns.js
// (scan) and gh-coin/lib/ta_rating.js (rating). Every 5 minutes, on CLOSED Binance USD-M bars only, it applies
// GH Coin's call-book rules (coin-office.js comboScan):
//   - a call opens when the plan state turns 'long' or 'short' (from any other state) and no call of that side is
//     open for the coin; entry = plan.entry (the last 5m close), SL and TP1 (1.5R) from planOf;
//   - graded on later 5m bars like combo.gradeCall: SL first when both are touched in one bar, TP1 = +1.5R,
//     24 h expiry at the bar close, an opposite call closes it at the plan price ("flip").
// Each call also has a MIRROR (the other side, same entry, SL and TP distances): averaging a call with its mirror
// is what a coin flip would make at the same times, so the reader can test GH Coin's sides against chance.
// Costs: taker fee + slippage on both sides, in R: cost_r = 2 * (FEE + SLIP) * entry / |entry - sl|.
//
// No key, no order, no Telegram: public market data in, three files out (OUT dir):
//   calls.jsonl  one line per event ({"ev":"open"} / {"ev":"close"}), append-only
//   board.json   latest plan, scores, rating and patterns per coin + heartbeat (rewritten each pass)
//   state.json   open calls and the last graded bar per coin (restart safety)
//   patterns.jsonl  one line per coin and 1h / 4h bar: GH Coin's pattern scan and TA rating on that closed bar,
//                append-only (2026-10-03: the live pattern history for the later pattern / trendline study;
//                board.json alone keeps only the latest)
import fs from "fs";
import path from "path";
import { pathToFileURL } from "url";

export const SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT"];
export const TFS = ["5", "15", "60", "240"];
export const TF_MS = {"5": 300e3, "15": 900e3, "60": 3600e3, "240": 14400e3};
const TF_API = {"5": "5m", "15": "15m", "60": "1h", "240": "4h"};
export const FEE = 0.0005, SLIP = 0.0002, EXPIRE_MS = 24 * 3600e3, BARS = 500;
const API = process.env.GHCOIN_API || "https://fapi.binance.com";

export async function loadGh(dir){
  const u = f => pathToFileURL(path.join(dir, f)).href;
  return {C: await import(u("gh-coin/combo.js")), P: await import(u("gh-coin/lib/patterns.js")),
          T: await import(u("gh-coin/lib/ta_rating.js"))};
}

export const costR = (entry, sl) => 2 * (FEE + SLIP) * entry / Math.abs(entry - sl);
const round = (x, k = 4) => x == null ? null : Math.round(x * 10 ** k) / 10 ** k;

export function newState(){ return {v: 1, last: {}, prev: {}, open: [], seq: 0}; }

// grade open calls (and mirrors) of one coin on one closed 5m bar {t, o, h, l, c}; returns the closed ones
export function gradeBar(st, sym, bar){
  const end = bar.t + TF_MS["5"], done = [];
  st.open = st.open.filter(c => {
    if (c.sym !== sym || bar.t < c.t) return true;
    const hitSL = c.side > 0 ? bar.l <= c.sl : bar.h >= c.sl, hitTP = c.side > 0 ? bar.h >= c.tp1 : bar.l <= c.tp1;
    let res = null, r = null;
    if (hitSL){ res = "loss"; r = -1; }
    else if (hitTP){ res = "win"; r = 1.5; }
    else if (end - c.t > EXPIRE_MS){ res = "expire"; r = c.side * (bar.c - c.entry) / Math.abs(c.entry - c.sl); }
    if (res == null) return true;
    done.push({...c, result: res, r: round(r), net_r: round(r - c.cost_r), end});
    return false;
  });
  return done;
}

// a new plan for one coin at decision time T (close of the last 5m bar): opens a call (+ mirror) when GH Coin would
export function onPlan(st, sym, plan, T){
  const out = {opened: [], closed: []}, prev = st.prev[sym];
  st.prev[sym] = plan.state;
  const isCall = s => s === "long" || s === "short";
  if (!isCall(plan.state) || prev === plan.state || !plan.entry || !plan.sl) return out;
  if (st.open.some(x => x.sym === sym && !x.mirror && x.side === plan.side)) return out;
  // the opposite open call (and its mirror, if still open) close at the plan price: "flip"
  const flipped = new Set(st.open.filter(x => x.sym === sym && !x.mirror && x.side === -plan.side).map(x => x.id));
  st.open = st.open.filter(x => {
    if (!flipped.has(x.mirror ? x.of : x.id)) return true;
    const r = x.side * (plan.price - x.entry) / Math.abs(x.entry - x.sl);
    out.closed.push({...x, result: "flip", r: round(r), net_r: round(r - x.cost_r), end: T});
    return false;
  });
  const id = `${sym}-${T}-${++st.seq}`, d = Math.abs(plan.entry - plan.sl), cr = round(costR(plan.entry, plan.sl), 5);
  const call = {id, sym, side: plan.side, entry: plan.entry, sl: plan.sl, tp1: plan.tp1, tp2: plan.tp2, t: T, cost_r: cr,
                conf: plan.conf, why: plan.why, big: round(plan.big), small: round(plan.small)};
  const mirror = {id: id + "-m", of: id, mirror: true, sym, side: -plan.side, entry: plan.entry,
                  sl: plan.entry + plan.side * d, tp1: plan.entry - plan.side * 1.5 * d, t: T, cost_r: cr};
  st.open.push(call, mirror);
  out.opened.push(call, mirror);
  return out;
}

// one coin, one pass: closed bars per timeframe (ascending, each {t, o, h, l, c, v}) -> events + board row
export async function passCoin(st, gh, sym, bars, cache = {}){
  const b5 = bars["5"], ev = [];
  if (!b5 || b5.length < BARS) throw new Error(`${sym}: ${b5 ? b5.length : 0} closed 5m bars`);
  const last = st.last[sym] ?? (b5[b5.length - 2]?.t ?? 0);
  for (const b of b5) if (b.t > last) for (const x of gradeBar(st, sym, b)) ev.push({ev: "close", ...x});
  const lastBar = b5[b5.length - 1], T = lastBar.t + TF_MS["5"];
  st.last[sym] = lastBar.t;
  const tf = {};
  for (const k of TFS){
    const arr = bars[k]; if (!arr || arr.length < BARS) continue;
    const key = `${sym}:${k}`, lt = arr[arr.length - 1].t;
    if (!cache[key] || cache[key].lt !== lt) cache[key] = {lt, res: await gh.C.analyzeTF(arr.slice(-BARS), {yieldEvery: 1e9})};
    tf[k] = cache[key].res;
  }
  const plan = gh.C.planOf(tf), o = onPlan(st, sym, plan, T);
  for (const x of o.closed) ev.push({ev: "close", ...x});
  for (const x of o.opened) ev.push({ev: "open", ...x});
  const pats = {}, rating = {};
  for (const k of ["60", "240"]) if (bars[k]){
    try { pats[k] = gh.P.scan(bars[k]).map(p => ({code: p.code, name: p.name, dir: p.dir, state: p.state})); } catch(e){ pats[k] = []; }
    try { const r = gh.T.rating(bars[k]); if (r) rating[k] = {all: round(r.all, 3), label: r.label}; } catch(e){}
  }
  const row = {t: T, price: plan.price, state: plan.state, side: plan.side, why: plan.why, conf: plan.conf,
               entry: plan.entry, sl: plan.sl, tp1: plan.tp1, tp2: plan.tp2, big: round(plan.big), small: round(plan.small),
               scores: Object.fromEntries(Object.entries(tf).map(([k, r]) => [k, round(r.score, 3)])),
               regime: plan.regime?.label ?? null, rating, patterns: pats};
  return {events: ev, row};
}

// ------------------------------------------------------------------------- I/O (the service)
const kline = a => ({t: +a[0], o: +a[1], h: +a[2], l: +a[3], c: +a[4], v: +a[5], ct: +a[6]});
export async function fetchClosed(sym, tf, now = Date.now()){
  const url = `${API}/fapi/v1/klines?symbol=${sym}&interval=${TF_API[tf]}&limit=${BARS + 1}`;
  const ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), 15000);
  try {
    const r = await fetch(url, {signal: ctl.signal});
    if (!r.ok) throw new Error(`${sym} ${tf}: HTTP ${r.status}`);
    return (await r.json()).map(kline).filter(b => b.ct < now);          // the forming bar is dropped
  } finally { clearTimeout(timer); }
}

function writeAtomic(file, text){ const tmp = file + ".tmp"; fs.writeFileSync(tmp, text); fs.renameSync(tmp, file); }

export async function runOnce(out, gh, st, cache, commit, now = Date.now(), fetcher = fetchClosed){
  const board = {v: 1, ts: now, commit, coins: {}, errors: {}};
  const lines = [], patLines = [];
  st.pat = st.pat || {};
  for (const sym of SYMBOLS){
    try {
      const bars = {};
      for (const k of TFS) bars[k] = await fetcher(sym, k, now);
      const {events, row} = await passCoin(st, gh, sym, bars, cache);
      board.coins[sym] = row;
      for (const e of events) lines.push(JSON.stringify(e));
      for (const k of ["60", "240"]){                     // once per closed 1h / 4h bar and coin
        const arr = bars[k], lt = arr && arr.length ? arr[arr.length - 1].t : null, key = `${sym}:${k}`;
        if (lt == null || st.pat[key] === lt) continue;
        st.pat[key] = lt;
        patLines.push(JSON.stringify({t: lt + TF_MS[k], sym, tf: k, close: arr[arr.length - 1].c,
                                      patterns: row.patterns[k] || [], rating: row.rating[k] || null}));
      }
    } catch(e){ board.errors[sym] = String(e && e.message || e).slice(0, 200); }
  }
  if (lines.length) fs.appendFileSync(path.join(out, "calls.jsonl"), lines.join("\n") + "\n");
  if (patLines.length) fs.appendFileSync(path.join(out, "patterns.jsonl"), patLines.join("\n") + "\n");
  writeAtomic(path.join(out, "state.json"), JSON.stringify(st));
  writeAtomic(path.join(out, "board.json"), JSON.stringify(board));
  return board;
}

async function main(){
  const args = process.argv.slice(2), arg = (k, d) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : d; };
  const out = arg("--out", "/var/lib/paperbot/ghcoin"), dir = arg("--gh", process.env.GHCOIN_DIR || "/opt/ghcoin");
  fs.mkdirSync(out, {recursive: true});
  const gh = await loadGh(dir);
  let commit = null; try { commit = fs.readFileSync(path.join(dir, "COMMIT"), "utf8").trim(); } catch(e){}
  let st = newState(); try { st = JSON.parse(fs.readFileSync(path.join(out, "state.json"), "utf8")); } catch(e){}
  const cache = {};
  let stop = false; process.on("SIGTERM", () => { stop = true; });
  for (;;){
    const now = Date.now(), next = Math.floor(now / TF_MS["5"]) * TF_MS["5"] + TF_MS["5"] + 8000;   // 8 s after each 5m close
    await new Promise(r => setTimeout(r, Math.max(0, next - now)));
    if (stop) break;
    try { const b = await runOnce(out, gh, st, cache, commit);
          const errs = Object.keys(b.errors); if (errs.length) console.error("errors:", JSON.stringify(b.errors)); }
    catch(e){ console.error("pass failed:", e && e.stack || e); }
    if (stop || args.includes("--once")) break;
  }
}

if (import.meta.url === pathToFileURL(process.argv[1] || "").href) main();

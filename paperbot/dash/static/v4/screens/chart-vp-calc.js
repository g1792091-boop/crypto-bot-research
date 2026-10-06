// 매물대 (volume-by-price profile) math for the 차트 screen and the 터미널 chart: pure functions, no DOM, no imports
// (tests/test_dash_vp_chart.py imports this file in node). The drawing is screens/chart-vp.js.
//
// What is computed (owners 10/06: "매수 물량 구간, 매도 물량 구간들도 중요하게 생각하는데"):
//   * the bars' volume is spread EVENLY across each bar's high-low range (a bar from 100 to 102 with volume 20 puts 10
//     in the 100-101 row and 10 in the 101-102 row; a bar without range puts it all in its row). This is an
//     approximation made from the candles, NOT the real traded volume at each price: APPROX says so in the legend;
//   * each row is split into 매수 (taker buy volume, the candle's "buy" key) and 매도 (volume - buy). When a bar has
//     no "buy" (an older server) the whole profile is a single total and says so (split: false): never a made-up split;
//   * POC = the middle of the fullest row (the first / lowest one on a tie, like the bot's research/entry_study/sr.py);
//   * value area = the rows that hold VA_SHARE (70 %) of all volume, grown from the POC row outwards one row at a time:
//     the next row above or below, whichever holds more (a tie takes the upper one; a side that has run out is
//     skipped), until the rows taken hold at least 70 %: VAH = top edge of the highest row taken, VAL = bottom edge
//     of the lowest (the bot's rule too, so its own 매물대 lines compare fairly with the drawn profile).
export const VA_SHARE = 0.7;
export const ROW_PX = 7;                 // a row is about this many pixels tall (6 px of colour + a 1 px gap)
export const ROWS_MIN = 10;
export const ROWS_MAX = 150;
export const MIN_GAP_MS = 1000;          // live bar changes recompute the whole profile at most this often
export const RANGES = [{id: "view", ko: "보이는 구간"}, {id: "today", ko: "오늘"}, {id: "week", ko: "최근 7일"}];
export const RANGE_KO = Object.fromEntries(RANGES.map((r) => [r.id, r.ko]));
export const APPROX = "봉 자료로 나눈 근사치: 실제 체결 가격별 물량과 다를 수 있음";
export const LEVEL_TFS = ["15m", "30m", "1h", "4h"];      // the bot's traded timeframes (its 매물대 exists there only)

const fin = (x) => (typeof x === "number" && Number.isFinite(x) ? x : null);

/** How many rows fit a pane of ``paneH`` px (bucket count adapts to the pane height): about one per ROW_PX over the part
 *  of the pane the price range fills (the price scale keeps 8 % + 16 % margins). */
export function rowCount(paneH) {
  const h = fin(paneH);
  if (h == null || h <= 0) return 40;
  return Math.max(ROWS_MIN, Math.min(ROWS_MAX, Math.round((h * 0.84) / ROW_PX)));
}

/** Whether the 매물대 starts on: the 차트 screen on a PC window, never on a phone and never on the 터미널 (the declutter). */
export function defaultOn(key, narrow) { return key === "chart" && !narrow; }

/** Korea time midnight (00:00 KST) of the day that contains ``nowSec`` (seconds). */
export function kstDayStart(nowSec) { return Math.floor((nowSec + 32400) / 86400) * 86400 - 32400; }

/** The candles a chosen range needs from the server: 오늘 = 5-minute bars since 00:00 Korea time, 최근 7일 = 15-minute
 *  bars of the last 7 days; null for 보이는 구간 (the chart's own bars). */
export function rangeSpec(mode, nowSec) {
  if (mode === "today") return {mode, interval: "5m", limit: 300, from: kstDayStart(nowSec)};
  if (mode === "week") return {mode, interval: "15m", limit: 700, from: nowSec - 7 * 86400};
  return null;
}

/** The first and last index of the bars that show on a chart: lightweight-charts' visible logical range {from, to} (bar i's
 *  centre is at i, so bar i shows when from - 0.5 <= i <= to + 0.5); null when none show. */
export function visibleIdx(data, range) {
  if (!Array.isArray(data) || !data.length || !range || !Number.isFinite(range.from) || !Number.isFinite(range.to)) return null;
  const i0 = Math.max(0, Math.ceil(range.from - 0.5)), i1 = Math.min(data.length - 1, Math.floor(range.to + 0.5));
  return i1 >= i0 ? [i0, i1] : null;
}
/** The bars of visibleIdx. */
export function sliceVisible(data, range) {
  const ix = visibleIdx(data, range);
  return ix ? data.slice(ix[0], ix[1] + 1) : [];
}

/**
 * buildProfile(bars, {n, lo, hi}) -> {ok: true, n, lo, hi, step, tot[], buy[], sell[], total, buyTotal, sellTotal,
 *   split, bars (carrying volume), max, poc (row index), pocPrice, vaLo / vaHi (row indices), val, vah, buyRatio}
 *   or {ok: false, why: "nobars" | "novol" | "flat"}.
 * bars: [{high, low, volume, buy?}]; n rows over [lo, hi] (default: the lowest low .. highest high of the bars).
 */
export function buildProfile(bars, o = {}) {
  const rows = [];
  let lo = Infinity, hi = -Infinity;
  for (const b of Array.isArray(bars) ? bars : []) {
    const h = fin(b && b.high), l = fin(b && b.low);
    if (h == null || l == null || h < l) continue;
    if (l < lo) lo = l;
    if (h > hi) hi = h;
    rows.push({h, l, v: fin(b.volume), b: fin(b.buy)});
  }
  if (!rows.length) return {ok: false, why: "nobars"};
  if (fin(o.lo) != null) lo = o.lo;
  if (fin(o.hi) != null) hi = o.hi;
  const n = Math.max(1, Math.floor(o.n || 40));
  const carry = rows.filter((r) => r.v != null && r.v > 0);
  if (!carry.length) return {ok: false, why: "novol"};
  if (!(hi > lo)) return {ok: false, why: "flat"};
  const step = (hi - lo) / n;
  const tot = new Array(n).fill(0), buy = new Array(n).fill(0);
  const at = (p) => Math.max(0, Math.min(n - 1, Math.floor((p - lo) / step)));
  let split = true;
  for (const r of carry) {
    if (r.b == null) split = false;
    const bu = r.b == null ? 0 : Math.max(0, Math.min(r.v, r.b));
    const span = r.h - r.l;
    if (span <= 0) {
      const i = at(r.l);
      tot[i] += r.v; buy[i] += bu;
      continue;
    }
    const i0 = at(r.l), i1 = at(r.h);
    for (let i = i0; i <= i1; i++) {
      const w = (Math.min(r.h, lo + (i + 1) * step) - Math.max(r.l, lo + i * step)) / span;
      if (!(w > 0)) continue;
      tot[i] += r.v * w; buy[i] += bu * w;
    }
  }
  const sell = tot.map((t, i) => Math.max(0, t - buy[i]));
  const total = tot.reduce((s, x) => s + x, 0);
  let poc = 0;
  for (let i = 1; i < n; i++) if (tot[i] > tot[poc]) poc = i;            // the first (lowest) fullest row wins a tie
  const va = valueArea(tot, poc, VA_SHARE);
  const buyTotal = buy.reduce((s, x) => s + x, 0);
  return {ok: true, n, lo, hi, step, tot, buy: split ? buy : null, sell: split ? sell : null, total,
    buyTotal: split ? buyTotal : null, sellTotal: split ? Math.max(0, total - buyTotal) : null, split, bars: carry.length, max: tot[poc],
    poc, pocPrice: lo + (poc + 0.5) * step, vaLo: va.lo, vaHi: va.hi, val: lo + va.lo * step, vah: lo + (va.hi + 1) * step,
    buyRatio: split && total > 0 ? buyTotal / total : null};
}

/** The value area's first and last row: from the POC row outwards, one row at a time, the side holding more volume (a
 *  tie goes up; an exhausted side is skipped), until the rows taken hold at least ``share`` of the total. */
export function valueArea(tot, poc, share = VA_SHARE) {
  const n = tot.length, total = tot.reduce((s, x) => s + x, 0);
  let lo = poc, hi = poc, acc = tot[poc];
  const target = share * total * (1 - 1e-12);                 // (the bot's sr.py: a share met only up to rounding counts)
  while (acc < target && (lo > 0 || hi < n - 1)) {
    const up = hi < n - 1 ? tot[hi + 1] : -1, dn = lo > 0 ? tot[lo - 1] : -1;
    if (up >= dn && hi < n - 1) { hi++; acc += up; } else { lo--; acc += dn; }
  }
  return {lo, hi};
}

/** One row's numbers: {a, b (its price edges), tot, buy, sell, ratio (매수 비율, 0..1, null without a split or volume)}. */
export function rowInfo(p, i) {
  const a = p.lo + i * p.step, b = a + p.step, tot = p.tot[i] || 0;
  return {a, b, tot, buy: p.split ? p.buy[i] : null, sell: p.split ? p.sell[i] : null, ratio: p.split && tot > 0 ? p.buy[i] / tot : null};
}

/** The hover text of a row: '가격 a~b · 매수 x · 매도 y · 매수 비율 z%' (f: {price, vol} formatters). Without a split it says
 *  so; a row nothing traded in says that. */
export function rowText(p, i, f = {}) {
  const price = f.price || ((x) => String(x)), vol = f.vol || ((x) => String(x));
  const r = rowInfo(p, i), head = `가격 ${price(r.a)}~${price(r.b)}`;
  if (!r.tot) return `${head} · 거래 없음`;
  if (!p.split) return `${head} · 거래량 ${vol(r.tot)} · 매수·매도 구분 자료 없음`;
  return `${head} · 매수 ${vol(r.buy)} · 매도 ${vol(r.sell)} · 매수 비율 ${Math.round(r.ratio * 100)}%`;
}

/** The row under a price (clamped into the profile), or -1 when the price is outside it. */
export function rowAt(p, price) {
  if (!p || !p.ok || !Number.isFinite(price) || price < p.lo || price > p.hi) return -1;
  return Math.max(0, Math.min(p.n - 1, Math.floor((price - p.lo) / p.step)));
}

/**
 * throttle(fn, gapMs, clock) -> {poke, cancel, flush, runs, pending}: poke() runs fn at once when the last run is at least
 * gapMs ago, else once more when the gap is up (many pokes in between are one): fn never runs twice within gapMs.
 * clock: {now, set, clear} (default Date.now / setTimeout / clearTimeout; a test passes a fake one).
 */
export function throttle(fn, gapMs = MIN_GAP_MS, clock = {}) {
  const now = clock.now || (() => Date.now()), set = clock.set || ((f, ms) => setTimeout(f, ms)), clear = clock.clear || ((t) => clearTimeout(t));
  let last = -Infinity, timer = null, runs = 0;
  const run = () => { timer = null; last = now(); runs++; fn(); };
  const cancel = () => { if (timer != null) { clear(timer); timer = null; } };
  return {
    poke() { if (timer != null) return; const wait = last + gapMs - now(); if (wait <= 0) run(); else timer = set(run, wait); },
    cancel,
    flush() { cancel(); run(); },
    get runs() { return runs; },
    get pending() { return timer != null; },
  };
}

/** Label heights that keep every label at least ``H`` px from the next inside [lo, hi]: items [{y}] -> the same items
 *  with ``ly`` (nothing is dropped: a handful of labels always fit a chart). */
export function placeLabels(items, H, lo, hi) {
  const list = items.slice().sort((a, b) => a.y - b.y);
  let prev = lo + H / 2 - H;
  for (const it of list) { it.ly = Math.max(it.y, prev + H, lo + H / 2); prev = it.ly; }
  let next = hi - H / 2 + H;
  for (let k = list.length - 1; k >= 0; k--) { list[k].ly = Math.min(list[k].ly, next - H); next = list[k].ly; }
  let p2 = -Infinity;
  for (const it of list) { it.ly = Math.max(it.ly, p2 + H, lo + H / 2); p2 = it.ly; }
  return list;
}

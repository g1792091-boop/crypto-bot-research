// 차트 위 얹기 (chart-plus): the arithmetic of the three additions, pure (no DOM, no imports: tests run it in node).
//   liquidations  bubble size, the price-bucket bars over the visible bars, the colour rule
//   our map       where our open positions' stops and liquidation prices are, and "이 가격이면" for a price
//   lower panes   the buy-minus-sell volume (CVD) from the candles, and Binance's series put on the candles' own times
// HONESTY: a value that is missing is null (a gap in the line), never 0 and never carried over a long hole.

/** The bar widths of /api/candles in seconds (the same table as screens/chart.js). */
export const TF_S = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "8h": 28800,
  "12h": 43200, "1d": 86400, "3d": 259200, "1w": 604800, "1M": 2592000};

/** Which side of the market a forced order closed -> the up / down colour token. The terminal's 시장 강제청산 list
 *  (terminal-feed.js: `lg ? "up" : "down"`) is the rule: a LONG liquidation takes the up colour, a SHORT the down one. */
export const LIQ_TONE = {long: "up", short: "down"};

/** The smallest bubble: the sum of one side's forced orders in one bar, in USDT (BTC $50k, every other coin $10k). */
export const minLiqUsd = (sym) => (sym === "BTCUSDT" ? 50000 : 10000);

/** Bubble radius in px, by the log of the amount: the minimum is 4 px, every ten times as much adds about 4 px (24 px max). */
export function liqRadius(usd, minUsd) {
  if (!(usd > 0) || !(minUsd > 0)) return 0;
  return Math.max(4, Math.min(24, 4 + 4.2 * Math.log10(Math.max(1, usd / minUsd))));
}

/** The bars of /api/v4/chartplus/liq that become bubbles (>= minUsd), the biggest first (so the small ones draw on top). */
export function bubbles(bars, minUsd) {
  return (Array.isArray(bars) ? bars : []).filter((b) => b && b.usd >= minUsd && Number.isFinite(b.px) && b.px > 0 && Number.isFinite(b.t))
    .sort((a, b) => b.usd - a.usd);
}

/**
 * The price-bucket bars over the bars on screen: cells [bar index, price bucket, long USDT, short USDT] of the bars
 * a..z (bar index = (open time - t0) / step), the bucket's price = (bucket + 0.5) * tick, moved to the screen by
 * ``yOf(price)`` (null when off the pane) and added into rows of ``rowPx`` pixels. -> {rows: [{y, long, short}], max}
 */
export function priceRows(cells, tick, a, z, yOf, rowPx, height) {
  const sums = new Map();
  if (!(tick > 0)) return {rows: [], max: 0};
  for (const c of Array.isArray(cells) ? cells : []) {
    const b = c[0];
    if (b < a || b > z) continue;
    const y = yOf((c[1] + 0.5) * tick);
    if (y == null || !Number.isFinite(y) || y < 0 || y > height) continue;
    const k = Math.floor(y / rowPx);
    const r = sums.get(k) || {y: k * rowPx + rowPx / 2, long: 0, short: 0};
    r.long += c[2] || 0; r.short += c[3] || 0;
    sums.set(k, r);
  }
  const rows = [...sums.values()].sort((p, q) => p.y - q.y);
  return {rows, max: rows.reduce((m, r) => Math.max(m, r.long + r.short), 0)};
}

// ---------------------------------------------------------------- our stops and liquidation prices ("우리 손절·청산 지도")
/**
 * What a price means for our open positions on the coin. ``items``: [{side: 1 | -1, entry, qty, margin, stop, lock, liq, money}]
 * (``lock``: the stop is a profit lock; ``money``: its money may be shown, false for DeepSeek and the coin flips: counted
 * only, CONTRACT D10 / D11). ``mark``: the price now. The price path runs from the mark to ``P``; a position's stop or
 * liquidation price on that path is reached, the nearer one to the mark first (that one closes it, the other never
 * happens). A stopped position books side * qty * (stop - entry), a liquidated one loses its whole margin, the others
 * are valued at P. Marks only, before the exit fee and slippage: arithmetic on the open positions, not a forecast.
 * -> {n, stops, locks, liqs, open, countOnly (positions that are counted without money), pnl (money ones), nMoney}
 */
export function whatIf(items, mark, P) {
  const out = {n: 0, stops: 0, locks: 0, liqs: 0, open: 0, countOnly: 0, pnl: 0, nMoney: 0};
  if (!(mark > 0) || !(P > 0)) return out;
  const lo = Math.min(mark, P), hi = Math.max(mark, P);
  const on = (x) => x != null && Number.isFinite(x) && x >= lo && x <= hi && x !== mark;
  for (const it of Array.isArray(items) ? items : []) {
    if (!it || !(it.entry > 0)) continue;
    out.n++;
    // only the adverse side of the mark can be a stop / liquidation: a long's lie below the price, a short's above
    const adverse = (x) => x != null && (it.side > 0 ? x < mark : x > mark);
    const sHit = adverse(it.stop) && on(it.stop), lHit = adverse(it.liq) && on(it.liq);
    let kind = "open", at = P;
    if (sHit && lHit) kind = Math.abs(it.stop - mark) <= Math.abs(it.liq - mark) ? "stop" : "liq";
    else if (sHit) kind = "stop";
    else if (lHit) kind = "liq";
    if (kind === "stop") { out.stops++; if (it.lock) out.locks++; at = it.stop; }
    else if (kind === "liq") out.liqs++;
    else out.open++;
    if (!it.money) { out.countOnly++; continue; }
    out.nMoney++;
    out.pnl += kind === "liq" ? -(it.margin || 0) : it.side * (it.qty || 0) * (at - it.entry);
  }
  return out;
}

/** The levels the strip draws: [{price, kind: "stop" | "liq", n}] (equal prices within 0.02 % are one level), sorted by price. */
export function stopLevels(items) {
  const raw = [];
  for (const it of Array.isArray(items) ? items : []) {
    if (!it) continue;
    if (it.stop > 0) raw.push({price: it.stop, kind: "stop"});
    if (it.liq > 0) raw.push({price: it.liq, kind: "liq"});
  }
  raw.sort((p, q) => p.price - q.price);
  const out = [];
  for (const r of raw) {
    const g = out.find((x) => x.kind === r.kind && Math.abs(x.price - r.price) / r.price < 0.0002);
    if (g) g.n++; else out.push({price: r.price, kind: r.kind, n: 1});
  }
  return out.sort((p, q) => p.price - q.price);
}

// ---------------------------------------------------------------- CVD from the candles' taker-buy volume
/**
 * Buy minus sell volume per bar from the candles ({volume, taker_buy}, base asset): delta = taker_buy - (volume -
 * taker_buy). A bar without a usable pair (no taker_buy, a negative or larger-than-volume buy) has delta null and is
 * counted in ``missing``; it is never read as 0. ``cum`` is the running sum of the bars a..z (the bars on screen), 0 at
 * the bar before ``a``, continued left and right of that window from the same zero; null where a delta is missing
 * (the sum keeps going over it, only the point is left out).
 */
export function cvd(candles, a = 0, z = Infinity) {
  const n = Array.isArray(candles) ? candles.length : 0;
  const delta = new Array(n).fill(null);
  let missing = 0;
  for (let i = 0; i < n; i++) {
    const c = candles[i], v = Number(c && c.volume), tb = c && c.taker_buy != null ? Number(c.taker_buy) : NaN;
    if (Number.isFinite(v) && Number.isFinite(tb) && tb >= 0 && tb <= v * 1.0001 + 1e-9) delta[i] = 2 * tb - v;
    else missing++;
  }
  const lo = Math.max(0, Math.min(n, Math.floor(a))), hi = Math.min(n - 1, Math.floor(z));
  let base = 0;
  for (let i = 0; i < lo; i++) if (delta[i] != null) base += delta[i];
  const cum = new Array(n).fill(null);
  let run = 0;
  for (let i = 0; i < n; i++) {
    if (delta[i] != null) run += delta[i];
    cum[i] = delta[i] == null ? null : run - base;
  }
  let missingVisible = 0;
  for (let i = lo; i <= hi; i++) if (delta[i] == null) missingVisible++;
  return {delta, cum, missing, missingVisible, from: lo, to: Math.max(lo - 1, hi)};
}

// ---------------------------------------------------------------- Binance series on the candles' own times
/**
 * Put a step series on the candles: ``points`` [[ts ms, value, ...]] oldest first; ``times`` the candles' open times (s);
 * ``step`` the candle width (s); ``periodS`` the series' own period (s). A candle takes the LAST point inside it; a candle
 * with no point inside takes the value of the last point before it only while that point is at most 1.5 periods old (a
 * longer hole stays empty); a candle before the first point is empty. -> [{v, ts, carried} | null] per candle (index = candle).
 */
export function alignSeries(points, times, step, periodS) {
  const out = new Array(times.length).fill(null);
  const pts = Array.isArray(points) ? points : [];
  let j = 0, prev = null;
  for (let i = 0; i < times.length; i++) {
    const t0 = times[i] * 1000, t1 = t0 + step * 1000;
    let inside = null;
    while (j < pts.length && pts[j][0] < t1) {
      if (pts[j][0] >= t0) inside = pts[j];
      prev = pts[j];
      j++;
    }
    if (inside) out[i] = {v: inside[1], x: inside[2], ts: inside[0], carried: false};
    else if (prev && t0 - prev[0] <= periodS * 1500) out[i] = {v: prev[1], x: prev[2], ts: prev[0], carried: true};
  }
  return out;
}

/** The funding settlements on the candles: each candle's SUM of the rates settled inside it (null when none: nothing is carried). */
export function alignFunding(points, times, step) {
  const out = new Array(times.length).fill(null);
  const pts = Array.isArray(points) ? points : [];
  let j = 0;
  for (let i = 0; i < times.length; i++) {
    const t0 = times[i] * 1000, t1 = t0 + step * 1000;
    while (j < pts.length && pts[j][0] < t0) j++;
    let k = j, sum = 0, n = 0;
    while (k < pts.length && pts[k][0] < t1) { sum += pts[k][1]; n++; k++; }
    if (n) out[i] = {v: sum, n, ts: pts[k - 1][0]};
  }
  return out;
}

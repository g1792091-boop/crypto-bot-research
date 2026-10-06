// 프리미엄 지표 (owners 10/06, the reference terminal's "SMC" look): pure computation from the real candles on screen,
// no network, no randomness. Drawn by core/chartfx.js when the viewer turns it on; it is an INDICATOR (labelled so on
// the chart), never a signal any bot trades. Node-tested on synthetic candles (tests/test_dash_glow.py).
//   swings      pivot highs / lows (a bar higher / lower than k bars on each side; known only k bars later)
//   zigzag      the alternating major swings (a move smaller than ``minMove`` x the average bar range is noise)
//   structure   BoS (a break of the last swing in the trend's own direction) / CHoCH (the first break against it)
//   obs         order blocks: the last opposite candle before a break, kept while price has not closed through it
//   fvgs        fair value gaps: a 3-candle gap, kept until price fills it
//   liq         BSL / SSL: swing highs / lows no later price has taken (the resting stops above / below)
//   range       the dealing range of the last major leg: premium / discount around the equilibrium, OTE 0.62-0.79
//   trend       lines through the last two major highs and the last two major lows
//   legs        % move of the last major legs (↓1.87%)
// Every list is cut to the most recent few so the chart stays readable.

export const LIMITS = {structure: 3, obs: 1, fvgs: 2, liq: 2, legs: 5};

const avgRange = (bars) => {
  let s = 0, n = 0;
  for (const b of bars) { const r = b.high - b.low; if (r > 0) { s += r; n++; } }
  return n ? s / n : 0;
};

/** Pivot highs / lows: [{i, t, price, kind: "H" | "L"}] in time order (a pivot needs k bars on both sides). */
export function swings(bars, k = 3) {
  const out = [];
  for (let i = k; i < bars.length - k; i++) {
    let hi = true, lo = true;
    for (let j = i - k; j <= i + k && (hi || lo); j++) {
      if (j === i) continue;
      // ties: the first bar of a flat top counts (>= on the left would drop both)
      if (j < i ? bars[j].high >= bars[i].high : bars[j].high > bars[i].high) hi = false;
      if (j < i ? bars[j].low <= bars[i].low : bars[j].low < bars[i].low) lo = false;
    }
    if (hi) out.push({i, t: bars[i].time, price: bars[i].high, kind: "H"});
    if (lo) out.push({i, t: bars[i].time, price: bars[i].low, kind: "L"});
  }
  return out;
}

/** Alternating major swings: same-kind pivots keep the more extreme; an opposite pivot closer than minMove is skipped. */
export function zigzag(piv, minMove = 0) {
  const z = [];
  for (const p of piv) {
    const last = z[z.length - 1];
    if (!last) { z.push(p); continue; }
    if (p.kind === last.kind) {
      if ((p.kind === "H" && p.price > last.price) || (p.kind === "L" && p.price < last.price)) z[z.length - 1] = p;
      continue;
    }
    if (Math.abs(p.price - last.price) < minMove) continue;
    z.push(p);
  }
  return z;
}

/** BoS / CHoCH: [{kind, dir: 1 | -1, from: pivot index, to: break bar index, price}] in time order. */
export function structure(bars, piv, k = 3) {
  const out = [];
  let hi = null, lo = null, trend = 0, p = 0;
  for (let j = 0; j < bars.length; j++) {
    while (p < piv.length && piv[p].i + k <= j) {                 // a pivot is known k bars after it
      if (piv[p].kind === "H") hi = {...piv[p], broken: false}; else lo = {...piv[p], broken: false};
      p++;
    }
    const c = bars[j].close;
    if (hi && !hi.broken && c > hi.price) {
      out.push({kind: trend === -1 ? "CHoCH" : "BoS", dir: 1, from: hi.i, to: j, price: hi.price});
      hi.broken = true; trend = 1;
    } else if (lo && !lo.broken && c < lo.price) {
      out.push({kind: trend === 1 ? "CHoCH" : "BoS", dir: -1, from: lo.i, to: j, price: lo.price});
      lo.broken = true; trend = -1;
    }
  }
  return out;
}

/** Order blocks of the given breaks: the last opposite candle before each break's move, alive until closed through. */
export function orderBlocks(bars, breaks, piv) {
  const out = [];
  for (const b of breaks) {
    // the swing the move started from: the last opposite pivot before the break
    const startKind = b.dir > 0 ? "L" : "H";
    let s = null;
    for (const p of piv) if (p.kind === startKind && p.i < b.to) s = p;
    if (!s) continue;
    let ob = -1;
    for (let i = Math.min(b.to, s.i + 2); i >= Math.max(0, s.i - 5); i--) {
      const x = bars[i];
      if (b.dir > 0 ? x.close < x.open : x.close > x.open) { ob = i; break; }
    }
    if (ob < 0) ob = s.i;
    const z = {dir: b.dir, i: ob, top: bars[ob].high, bot: bars[ob].low, from: b.to, alive: true};
    for (let j = b.to + 1; j < bars.length; j++) {
      if (b.dir > 0 ? bars[j].close < z.bot : bars[j].close > z.top) { z.alive = false; break; }
    }
    if (!out.some((o) => o.i === z.i && o.dir === z.dir)) out.push(z);
  }
  return out;
}

/** Fair value gaps still open: [{dir, i (middle bar), top, bot}] (a gap smaller than minGap is ignored). */
export function fairValueGaps(bars, minGap = 0) {
  const out = [];
  for (let i = 2; i < bars.length; i++) {
    const a = bars[i - 2], c = bars[i];
    let z = null;
    if (c.low > a.high && c.low - a.high > minGap) z = {dir: 1, i: i - 1, top: c.low, bot: a.high};
    else if (c.high < a.low && a.low - c.high > minGap) z = {dir: -1, i: i - 1, top: a.low, bot: c.high};
    if (!z) continue;
    let open = true;
    for (let j = i + 1; j < bars.length && open; j++) {
      if (z.dir > 0 ? bars[j].low <= z.bot : bars[j].high >= z.top) open = false;
    }
    if (open) out.push(z);
  }
  return out;
}

/** Untaken swing highs (BSL) / lows (SSL): no later bar reached them. */
export function liquidity(bars, piv) {
  const out = [];
  for (const p of piv) {
    let taken = false;
    for (let j = p.i + 1; j < bars.length && !taken; j++) taken = p.kind === "H" ? bars[j].high > p.price : bars[j].low < p.price;
    if (!taken) out.push({kind: p.kind === "H" ? "BSL" : "SSL", i: p.i, price: p.price});
  }
  return out;
}

/** The dealing range of the last major leg a -> b: equilibrium, premium / discount, OTE 0.62 / 0.79 retracement. */
export function dealingRange(z) {
  if (z.length < 2) return null;
  const a = z[z.length - 2], b = z[z.length - 1];
  const hi = Math.max(a.price, b.price), lo = Math.min(a.price, b.price), r = hi - lo;
  if (!(r > 0)) return null;
  const up = b.kind === "H";                                    // the last leg went up: OTE is a pullback down into it
  const lv = (f) => (up ? hi - f * r : lo + f * r);
  return {from: Math.min(a.i, b.i), i: b.i, hi, lo, eq: (hi + lo) / 2, up, ote: [lv(0.62), lv(0.79)]};
}

/** Lines through the last two major highs and the last two major lows: [{kind, i1, p1, i2, p2}]. */
export function trendlines(z) {
  const out = [];
  for (const kind of ["H", "L"]) {
    const s = z.filter((p) => p.kind === kind).slice(-2);
    if (s.length === 2 && s[1].i > s[0].i) out.push({kind, i1: s[0].i, p1: s[0].price, i2: s[1].i, p2: s[1].price});
  }
  return out;
}

/** % move of the last major legs: [{i1, i2, p1, p2, pct}] (pct is a ratio). */
export function legs(z) {
  const out = [];
  for (let n = 1; n < z.length; n++) out.push({i1: z[n - 1].i, i2: z[n].i, p1: z[n - 1].price, p2: z[n].price, pct: (z[n].price - z[n - 1].price) / z[n - 1].price});
  return out;
}

/**
 * smcAll(bars, {k, minMoveX, lim}) -> everything above for the CLOSED candles (the forming bar is left out by the
 * caller), each list cut to the most recent ``lim`` items. Empty lists for fewer than 30 bars.
 */
export function smcAll(bars, o = {}) {
  const k = o.k || 3, lim = {...LIMITS, ...(o.lim || {})};
  const empty = {pivots: [], zz: [], structure: [], obs: [], fvgs: [], liq: [], range: null, trend: [], legs: []};
  const b = (bars || []).filter((x) => x && [x.open, x.high, x.low, x.close].every(Number.isFinite));
  if (b.length < 30) return empty;
  const ar = avgRange(b);
  const piv = swings(b, k);
  const zz = zigzag(swings(b, k + 2), ar * (o.minMoveX ?? 3));
  const br = structure(b, piv, k);
  const obs = orderBlocks(b, br, piv).filter((x) => x.alive);
  const fv = fairValueGaps(b, ar * 0.25);
  const liq = liquidity(b, zz);
  const last = (arr, n) => arr.slice(Math.max(0, arr.length - n));
  return {
    pivots: piv, zz,
    structure: last(br, lim.structure),
    obs: [...last(obs.filter((x) => x.dir > 0), lim.obs), ...last(obs.filter((x) => x.dir < 0), lim.obs)],
    fvgs: last(fv, lim.fvgs),
    liq: [...last(liq.filter((x) => x.kind === "BSL"), lim.liq), ...last(liq.filter((x) => x.kind === "SSL"), lim.liq)],
    range: dealingRange(zz),
    trend: trendlines(zz),
    legs: last(legs(zz), lim.legs),
  };
}

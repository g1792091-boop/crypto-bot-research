// The numbers behind the terminal's 수익 차트: pure functions (no DOM, no imports: tests/test_dash_term_plus.py runs them in node).
// Input: /api/v4/termpnl's hours [[hour END ms, realized P&L, trades, wins, losses], ...] (only hours in which something closed) and the
// season's start / now. Output: the cumulative line, its buckets, wins and losses and the deepest fall of the line.
//
// Why: the old line had one point per KST day (the start, then each day's end), so on day 1 it was ONE slanted line from "10/06"
// to "10/06" that looked like a crash. Now the first 3 days are drawn per HOUR, up to 14 days per 4 hours, then per day; the time
// ticks say hours ("09:00 · 15:00 · 지금") while the run is young.
// Honest by construction: an hour without a closed trade is simply flat (nothing closed), the window's line starts at 0, the
// last point is "now", and nothing is drawn without data (the caller shows 불러오는 중 / 불러오지 못함 / 아직 닫힌 거래 없음).

export const H = 3600000;
export const D = 24 * H;
export const KST = 9 * H;

/** The bucket size for a span: 1 hour up to 3 days, 4 hours up to 14 days, then 1 day. */
export const pickStep = (spanMs) => (spanMs <= 3 * D ? H : spanMs <= 14 * D ? 4 * H : D);
/** The END of the KST-aligned bucket of ``step`` ms that holds the instant ``t`` (an hour end at exactly 13:00 holds 12:00-13:00). */
export const bucketEnd = (t, step) => Math.ceil((t - 1 + KST) / step) * step - KST;

/** The windows the page offers, each only when it is shorter than what there is to show (else it would equal 전체). */
export const WINDOWS = [{id: "24h", ko: "24시간", ms: D}, {id: "7d", ko: "7일", ms: 7 * D}, {id: "30d", ko: "30일", ms: 30 * D}, {id: "all", ko: "전체", ms: null}];
export function windowsFor(spanMs) {
  return WINDOWS.filter((w) => w.ms == null || spanMs > w.ms * 1.15);
}

/**
 * series(d, windowMs) -> {x0, x1, step, pts: [[t, cum]], bars: [{t0, t1, pnl, n, w, l, cum}], trades, wins, losses, total, mdd, lo, hi, empty}
 *   d: the /api/v4/termpnl answer {start, now, from, hours}; windowMs: null for the whole season.
 *   total / cum: realized P&L since the window start (0 at x0); mdd: the deepest fall of the hourly cumulative line from its
 *   highest earlier point (the window's start counts as a point at 0), in USDT, 0 or more.
 */
export function series(d, windowMs = null) {
  const now = Number(d.now), hours = Array.isArray(d.hours) ? d.hours : [];
  const seasonStart = Math.max(Number(d.start) || 0, Number(d.from) || 0);
  // a window starts on a whole hour (the hourly rows are whole hours: no trade of the hour before it is counted in)
  const x0 = windowMs ? Math.max(seasonStart, Math.floor((now - windowMs) / H) * H) : seasonStart || (hours.length ? hours[0][0] - H : now - H);
  const x1 = now;
  const step = pickStep(x1 - x0);
  // the hourly rows inside the window (their END is after x0)
  let trades = 0, wins = 0, losses = 0, total = 0;
  const rows = [];
  for (const r of hours) {
    const t = Number(r[0]);
    if (!(t > x0)) continue;
    rows.push({t, pnl: Number(r[1]) || 0, n: Number(r[2]) || 0, w: Number(r[3]) || 0, l: Number(r[4]) || 0});
  }
  // buckets (a bucket's end is capped at now: the last one is still running)
  const map = new Map();
  for (const r of rows) {
    const e = Math.min(bucketEnd(r.t, step), x1);
    const b = map.get(e) || {t1: e, pnl: 0, n: 0, w: 0, l: 0};
    b.pnl += r.pnl; b.n += r.n; b.w += r.w; b.l += r.l;
    map.set(e, b);
    trades += r.n; wins += r.w; losses += r.l; total += r.pnl;
  }
  const bars = [...map.values()].sort((a, b) => a.t1 - b.t1);
  let cum = 0;
  const pts = [[x0, 0]];
  for (const b of bars) { b.t0 = Math.max(x0, b.t1 - step); cum += b.pnl; b.cum = cum; pts.push([b.t1, cum]); }
  if (pts[pts.length - 1][0] < x1) pts.push([x1, cum]);                    // flat to now: nothing closed since
  // the deepest fall, on the hourly line
  let c = 0, peak = 0, mdd = 0;
  for (const r of rows.sort((a, b) => a.t - b.t)) { c += r.pnl; if (c > peak) peak = c; if (peak - c > mdd) mdd = peak - c; }
  let lo = 0, hi = 0;
  for (const p of pts) { if (p[1] < lo) lo = p[1]; if (p[1] > hi) hi = p[1]; }
  return {x0, x1, step, pts, bars, trades, wins, losses, total, mdd, lo, hi, empty: !rows.length};
}

/** Time ticks for the x axis: [{t, label}] strictly inside (x0, x1): hours while the span is short, days after. ``max`` ticks at most. */
export function timeTicks(x0, x1, max, fmtHm, fmtMd) {
  const span = x1 - x0, out = [];
  if (!(span > 0) || max < 1) return out;
  const steps = span <= 3 * D ? [3 * H, 6 * H, 12 * H, D] : [D, 2 * D, 3 * D, 7 * D, 14 * D];
  const st = steps.find((s) => span / s <= max) || steps[steps.length - 1];
  const margin = span * 0.07;
  for (let t = Math.ceil((x0 + margin + KST) / st) * st - KST; t < x1 - margin * 2.4; t += st) {
    const midnight = (t + KST) % D === 0;
    out.push({t, label: span > 3 * D || midnight ? fmtMd(t) : fmtHm(t)});
  }
  return out;
}

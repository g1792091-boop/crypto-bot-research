// 프리미엄 지표 drawing (core/smc.js computes, core/chartfx.js picks what is on, this draws): a lightweight-charts v4.2
// series primitive. Zones (order blocks, fair value gaps, premium / discount, OTE) are thin translucent bands under the
// candles that extend to the right edge; lines (the equilibrium, BSL / SSL liquidity, BoS / CHoCH, trendlines) and the
// % labels of the last legs are 1 px and drawn over them. The zones' names (OB+ / OB− / FVG) are NOT drawn here: the
// deck places every right-edge name in one collision-free column next to the price axis (core/edgelabels.js, owners
// 10/06 ~14:00). Colours are tokens (read by chartfx.js colours()), text the --t-2xs size.
// Nothing here is excluded from or added to the autoscale: the candles alone set the price range.
import {num} from "./fmt.js";

/**
 * smcPrimitive({chart, series, get, col}) -> primitive with .request()
 *   get() -> what to draw, or null (off): the deck's view of the smcAll() result (chartfx.js smcView):
 *     {range, eq, ote, words (bool: the parts that are on), zones: [{kind: "ob" | "fvg", i, top, bot, dir}],
 *      liq, structure, trend, legs (the lists to draw; empty when that part is off)}
 *   col() -> the deck's resolved colours
 */
export function smcPrimitive(o) {
  let api = null;
  const v = {z: [], l: [], t: []};             // zones, lines, texts in media coordinates
  const fontOf = (col, vr, w = 600) => `${w} ${col.fs * vr}px ${col.font}`;

  function zoneR() {
    return {
      draw() {},
      drawBackground(target) {
        if (!v.z.length) return;
        target.useBitmapCoordinateSpace(({context: c, horizontalPixelRatio: hr, verticalPixelRatio: vr}) => {
          c.save();
          for (const z of v.z) {
            const x = Math.round(z.x1 * hr), w = Math.max(1, Math.round((z.x2 - z.x1) * hr));
            const y = Math.round(Math.min(z.y1, z.y2) * vr), hh = Math.max(1, Math.round(Math.abs(z.y2 - z.y1) * vr));
            c.globalAlpha = z.a; c.fillStyle = z.c;
            c.fillRect(x, y, w, hh);
            if (z.edge) {
              c.globalAlpha = z.edge; c.fillRect(x, y, w, Math.max(1, Math.round(vr))); c.fillRect(x, y + hh - Math.max(1, Math.round(vr)), w, Math.max(1, Math.round(vr)));
            }
          }
          c.restore();
        });
      },
    };
  }
  function lineR() {
    return {
      draw(target) {
        if (!v.l.length && !v.t.length) return;
        target.useBitmapCoordinateSpace(({context: c, horizontalPixelRatio: hr, verticalPixelRatio: vr}) => {
          const col = o.col();
          c.save();
          c.lineWidth = Math.max(1, Math.round(hr));
          for (const L of v.l) {
            c.setLineDash(L.dash ? [4 * hr, 3 * hr] : []);
            c.globalAlpha = L.a; c.strokeStyle = L.c;
            c.beginPath(); c.moveTo(Math.round(L.x1 * hr) + 0.5, Math.round(L.y1 * vr) + 0.5); c.lineTo(Math.round(L.x2 * hr) + 0.5, Math.round(L.y2 * vr) + 0.5); c.stroke();
          }
          c.setLineDash([]);
          for (const T of v.t) {
            c.font = fontOf(col, vr, T.w || 600);
            c.textAlign = T.align || "left"; c.textBaseline = T.base || "middle";
            c.globalAlpha = 1; c.shadowColor = col.bg; c.shadowBlur = 3 * hr;          // a dark halo keeps it readable
            c.fillStyle = T.c;
            c.fillText(T.s, Math.round(T.x * hr), Math.round(T.y * vr));
          }
          c.restore();
        });
      },
    };
  }
  const zr = zoneR(), lr = lineR();

  function compute() {
    v.z = []; v.l = []; v.t = [];
    const d = o.get();
    if (!api || !d) return;
    const col = o.col(), ts = o.chart.timeScale();
    const X = (i) => ts.logicalToCoordinate(i), Y = (p) => o.series.priceToCoordinate(p);
    let W = 0;
    try { W = ts.width(); } catch (e) { return; }
    const zone = (i, top, bot, c, a, edge) => {
      const x1 = X(i), y1 = Y(top), y2 = Y(bot);
      if (x1 == null || y1 == null || y2 == null || x1 > W) return;
      v.z.push({x1: Math.max(0, x1), x2: W, y1, y2, c, a, edge});
    };
    // dealing range: the equilibrium line, premium / discount tints and words (the AI skin's light already washes the
    // halves: there only the words), the OTE band with its 0.62 / 0.79 labels
    const rg = d.range;
    if (rg) {
      const xf = Math.max(0, X(rg.from) ?? 0), yh = Y(rg.hi), yl = Y(rg.lo), ye = Y(rg.eq);
      if (d.words) {
        if (d.tint) {
          zone(rg.from, rg.hi, rg.eq, col.prem, 0.035);
          zone(rg.from, rg.eq, rg.lo, col.disc, 0.035);
        }
        if (yh != null) v.t.push({s: "Premium", x: xf + 6, y: yh + 9, c: col.prem, p: 6});
        if (yl != null) v.t.push({s: "Discount", x: xf + 6, y: yl - 9, c: col.disc, p: 6});
      }
      if (d.eq && ye != null) v.l.push({x1: xf, y1: ye, x2: W, y2: ye, c: col.trend, a: 0.35, dash: true});      // its name: on hover
      if (d.ote) {
        const [a, b] = rg.ote;
        zone(rg.i, Math.max(a, b), Math.min(a, b), col.ote, 0.09, 0.4);
        const ya = Y(a), yb = Y(b), xo = X(rg.i);
        if (ya != null && yb != null && xo != null && xo < W) {
          const xl = Math.max(0, xo) + 4;                         // at the zone's start: the right edge is for the names
          v.t.push({s: "0.62", x: xl, y: ya, c: col.ote, p: 4});
          v.t.push({s: "0.79", x: xl, y: yb, c: col.ote, p: 4});
          v.t.push({s: "OTE", x: xl + 34, y: (ya + yb) / 2, c: col.ote, p: 4});
        }
      }
    }
    for (const z of d.zones || []) zone(z.i, z.top, z.bot, z.kind === "ob" ? col.ob : col.fvg, z.kind === "ob" ? 0.13 : 0.1, z.kind === "ob" ? 0.5 : 0.3);
    // liquidity resting above / below: a dashed line from the swing to the right edge
    for (const q of d.liq || []) {
      const x = X(q.i), y = Y(q.price);
      if (x == null || y == null || x > W) continue;
      v.l.push({x1: Math.max(0, x), y1: y, x2: W, y2: y, c: col.liq, a: 0.55, dash: true});
      v.t.push({s: q.kind, x: Math.max(0, x) + 4, y: q.kind === "BSL" ? y - 8 : y + 9, c: col.liq, p: 2});
    }
    // structure breaks: the broken swing's level from the swing to the breaking bar, a small label in the middle
    for (const s of d.structure || []) {
      const x1 = X(s.from), x2 = X(s.to), y = Y(s.price);
      if (x1 == null || x2 == null || y == null) continue;
      const c = s.kind === "CHoCH" ? col.choch : col.bos;
      v.l.push({x1, y1: y, x2, y2: y, c, a: 0.75});
      v.t.push({s: s.kind, x: (x1 + x2) / 2, y: s.dir > 0 ? y - 8 : y + 9, c, align: "center", p: 3});
    }
    // trendlines through the last two major highs / lows, extended to the right edge
    for (const t of d.trend || []) {
      const x1 = X(t.i1), x2 = X(t.i2), y1 = Y(t.p1), y2 = Y(t.p2);
      if ([x1, x2, y1, y2].some((q) => q == null) || x2 === x1) continue;
      const m = (y2 - y1) / (x2 - x1);
      v.l.push({x1, y1, x2: W, y2: y1 + m * (W - x1), c: col.trend, a: 0.45});
    }
    // % of the last major legs, at each leg's middle
    for (const g of d.legs || []) {
      const x1 = X(g.i1), x2 = X(g.i2), y1 = Y(g.p1), y2 = Y(g.p2);
      if ([x1, x2, y1, y2].some((q) => q == null)) continue;
      v.l.push({x1, y1, x2, y2, c: col.trend, a: 0.22});
      const up = g.pct >= 0;
      v.t.push({s: `${up ? "↑" : "↓"}${num(Math.abs(g.pct * 100), 2)}%`, x: (x1 + x2) / 2 + 6, y: (y1 + y2) / 2, c: up ? col.disc : col.prem, w: 700, p: 5});
    }
  }

  /** No two labels overlap: placed by priority (liquidity, structure, OTE, leg %, the range words), each tried at its
   *  own height, then 14 px below / above; one that still collides is left out (the line or zone it names is still
   *  drawn). The same word right next to itself shows once. */
  function spread() {
    const fs = o.col().fs || 12, placed = [], keep = [];
    const box = (t, dy) => {
      const w = t.s.length * fs * 0.62 + 4, x0 = t.align === "right" ? t.x - w : t.align === "center" ? t.x - w / 2 : t.x;
      return {x0, x1: x0 + w, y0: t.y + dy - fs / 2 - 1, y1: t.y + dy + fs / 2 + 1};
    };
    const hits = (b) => placed.some((q) => b.x0 < q.x1 && q.x0 < b.x1 && b.y0 < q.y1 && q.y0 < b.y1);
    for (const t of v.t.slice().sort((x, y) => (x.p || 9) - (y.p || 9))) {
      if (keep.some((k) => k.s === t.s && Math.abs(k.x - t.x) < 40 && Math.abs(k.y - t.y) < 14)) continue;
      for (const dy of [0, 14, -14]) {
        const bx = box(t, dy);
        if (hits(bx)) continue;
        placed.push(bx); t.y += dy; keep.push(t);
        break;
      }
    }
    v.t = keep;
  }

  return {
    attached(p) { api = p; },
    detached() { api = null; },
    paneViews: () => [{zOrder: () => "bottom", renderer: () => zr}, {zOrder: () => "normal", renderer: () => lr}],
    updateAllViews() { compute(); spread(); },
    request() { if (api) api.requestUpdate(); },
  };
}

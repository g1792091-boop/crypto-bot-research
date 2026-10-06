// 차트 위 시장 강제청산 (chart-plus, addition 4): bubbles on the candles and price-bucket bars beside the price axis.
//   bubbles  per candle and side one circle at the USDT-weighted price of that side's forced orders in the bar, sized by
//            the amount (log scale, a legend in the note under the chart), coloured by LIQ_TONE (the terminal's 시장
//            강제청산 list: a LONG liquidation takes the up colour, a SHORT the down colour). Hover / tap: the side, the
//            sum, the count and the biggest single order with its price.
//   bars     a thin column of bars beside the price axis (its own strip, never over the right-edge names): the liquidation
//            USDT by price bucket over the candles on screen, long and short stacked.
//   honesty  the data are Binance's whole market as OUR recorder heard it (liq.db): nothing before the recorder started
//            (a veil with its words), the recorder's own disconnected spans (a hatched band), Binance's one-per-coin-per-
//            second limit (said in the note); a failed load is its own note, never "no liquidations".
// Data: /api/v4/chartplus/liq (dash/more/chartplus.py, 20 s cache), asked every 20 s while this is on and the page is visible.
import {h, fmt} from "../core/pb.js";
import {LIQ_TONE, TF_S, minLiqUsd, liqRadius, bubbles, priceRows} from "./chart-plus-calc.js";
import {koUsdt, WORDS, tipBox, palette} from "./chart-plus-kit.js";

const ROW_PX = 3;
const isAi = () => document.documentElement.dataset.skin !== "classic";

/**
 * liqMap({ctx, chart, series, wrap, deck, strip, sym, tf, report}) -> {setOn(on), reload(), onData(how), paint(), tip}
 *   strip: the div this part owns beside the price axis (it draws its bars in a canvas inside it)
 *   report(view): view = {kind: "off" | "loading" | "ready" | "empty" | "nofile" | "failed" | "unsupported", ...} for the note
 */
export function liqMap(o) {
  const {ctx, chart, series, wrap, deck, strip} = o;
  const cv = h("canvas", {class: "cfxp-cv", "aria-hidden": "true"});
  strip.append(cv);
  strip.title = "보이는 봉 동안 가격대별로 쌓인 시장 강제청산 금액 (롱 · 숏). 바이낸스 전체, 우리 기록기가 들은 것만.";
  const tip = tipBox(wrap);
  let on = false, data = null, err = null, busy = false, lay = {items: [], veil: null, gaps: []}, rows = {rows: [], max: 0}, hover = null;

  const col = () => palette();
  const toneOf = (side) => LIQ_TONE[side] === "up" ? "up" : "down";

  // ---------------------------------------------------------------- data
  function view() {
    if (!on) return {kind: "off"};
    if (!data && err) return {kind: "failed", err};
    if (!data) return {kind: "loading"};
    if (!data.ready) return data.failed ? {kind: "failed", err: {message: data.why}} : {kind: "nofile", why: data.why};
    return {kind: data.n ? "ready" : "empty", data, refreshFailed: !!err};
  }
  const report = () => { if (o.report) o.report(view()); };
  async function load() {
    if (!on || busy) return;
    const d = deck.data();
    const sym = o.sym(), tf = o.tf();
    if (!d.length) return;
    if (!TF_S[tf] || tf === "1M") { report(); return; }
    const t0 = d[0].time;
    busy = true;
    let r = null, e = null;
    try { r = await ctx.api(`/api/v4/chartplus/liq?symbol=${encodeURIComponent(sym)}&tf=${tf}&t0=${t0}`); }
    catch (x) { e = x; }
    busy = false;
    if (!ctx.alive() || !on) return;
    const d2 = deck.data();
    if (sym !== o.sym() || tf !== o.tf() || !d2.length || d2[0].time !== t0) { load(); return; }       // the chart moved on: ask again
    if (e && e.name === "AbortError") return;
    if (r) { data = r; err = null; } else err = e || new Error("no answer");
    relay(); report();
  }
  function relay() { layout(); paint(); if (api) api.requestUpdate(); }

  // ---------------------------------------------------------------- the candles' overlay (a series primitive)
  let api = null;
  function layout() {
    lay = {items: [], veil: null, gaps: []};
    const d = deck.data();
    if (!on || !data || !data.ready || !d.length || data.t0 !== d[0].time) return;
    const ts = chart.timeScale(), step = data.step_s, minU = minLiqUsd(o.sym());
    for (const b of bubbles(data.bars, minU)) {
      const x = ts.timeToCoordinate(b.t), y = series.priceToCoordinate(b.px);
      if (x == null || y == null) continue;
      lay.items.push({x, y, r: liqRadius(b.usd, minU), b});
    }
    const bx = (ms) => {
      const s = Math.floor(ms / 1000), k = Math.max(0, Math.floor((s - data.t0) / step));
      return ts.timeToCoordinate(data.t0 + k * step);
    };
    const half = (ts.options().barSpacing || 6) / 2;
    if (data.since_ts && data.since_ts / 1000 > data.t0) {            // nothing was recorded before this: not "no liquidations"
      const x1 = bx(data.since_ts);
      if (x1 != null) lay.veil = {x1: x1 - half};
    }
    for (const g of data.gaps || []) {
      const a = bx(g[0]), z = bx(g[1]);
      if (a != null && z != null && z > a) lay.gaps.push({x0: a - half, x1: z + half});
    }
  }
  const under = {
    draw() {},
    drawBackground(target) {
      if (!lay.veil && !lay.gaps.length) return;
      target.useMediaCoordinateSpace(({context: c, mediaSize}) => {
        const p = col();
        c.save();
        if (lay.veil && lay.veil.x1 > 0) {
          c.globalAlpha = 0.5; c.fillStyle = p.surface2;
          c.fillRect(0, 0, Math.min(lay.veil.x1, mediaSize.width), mediaSize.height);
          c.globalAlpha = 0.9; c.fillStyle = p.muted; c.font = `600 ${p.fs}px ${p.font}`; c.textBaseline = "top";
          const x = Math.min(lay.veil.x1, mediaSize.width);
          const word = "기록기가 켜지기 전 (이 앞은 모름)";
          c.strokeStyle = p.muted; c.globalAlpha = 0.5; c.setLineDash([3, 3]);
          c.beginPath(); c.moveTo(x, 0); c.lineTo(x, mediaSize.height); c.stroke(); c.setLineDash([]);
          c.globalAlpha = 0.9;
          const w = c.measureText(word).width;
          if (x > w + 14) { c.textAlign = "right"; c.fillText(word, x - 8, mediaSize.height - p.fs - 30); }
        }
        for (const g of lay.gaps) {
          const x0 = Math.max(0, g.x0), x1 = Math.min(mediaSize.width, g.x1);
          if (x1 <= x0) continue;
          c.globalAlpha = 0.1; c.fillStyle = p.warn; c.fillRect(x0, 0, x1 - x0, mediaSize.height);
          c.globalAlpha = 0.35; c.strokeStyle = p.warn; c.lineWidth = 1; c.beginPath();
          for (let x = x0 - mediaSize.height; x < x1; x += 7) { c.moveTo(Math.max(x0, x), Math.max(0, x0 - x)); c.lineTo(Math.min(x1, x + mediaSize.height), Math.min(mediaSize.height, x1 - x)); }
          c.stroke();
          if (x1 - x0 > 28) { c.globalAlpha = 0.85; c.fillStyle = p.warn; c.font = `600 ${p.fs}px ${p.font}`; c.textBaseline = "top"; c.textAlign = "left"; c.fillText("끊김", x0 + 3, 3); }
        }
        c.restore();
      });
    },
  };
  const top = {
    draw(target) {
      if (!lay.items.length) return;
      target.useMediaCoordinateSpace(({context: c, mediaSize}) => {
        const p = col(), ai = isAi();
        c.save();
        for (const it of lay.items) {
          if (it.x < -30 || it.x > mediaSize.width + 30 || it.y < -30 || it.y > mediaSize.height + 30) continue;
          const tone = toneOf(it.b.side), color = p[tone], hot = hover === it;
          c.beginPath(); c.arc(it.x, it.y, it.r, 0, Math.PI * 2);
          c.globalAlpha = hot ? 0.42 : 0.24; c.fillStyle = color; c.fill();
          if (ai) { c.shadowColor = p[tone + "Glow"]; c.shadowBlur = hot ? 14 : 8; }
          c.globalAlpha = hot ? 1 : 0.85; c.lineWidth = hot ? 2 : 1.25; c.strokeStyle = color; c.stroke();
          c.shadowBlur = 0;
        }
        c.restore();
      });
    },
  };
  series.attachPrimitive({
    attached(p) { api = p; },
    detached() { api = null; },
    paneViews: () => [{zOrder: () => "bottom", renderer: () => under}, {zOrder: () => "top", renderer: () => top}],
    updateAllViews() { layout(); paintSoon(); },
  });

  // ---------------------------------------------------------------- the strip: price buckets over the bars on screen
  let raf = 0;
  const paintSoon = () => { if (!raf) raf = requestAnimationFrame(() => { raf = 0; paint(); }); };
  ctx.track(() => { if (raf) cancelAnimationFrame(raf); });
  function paint() {
    const W = strip.clientWidth, H = strip.clientHeight;
    if (!W || !H) return;
    const dpr = window.devicePixelRatio || 1;
    if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) {
      cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); cv.style.width = W + "px"; cv.style.height = H + "px";
    }
    const c = cv.getContext("2d");
    c.setTransform(dpr, 0, 0, dpr, 0, 0);
    c.clearRect(0, 0, W, H);
    rows = {rows: [], max: 0};
    if (!on) return;
    const p = col();
    c.font = `600 ${p.fs}px ${p.font}`; c.textBaseline = "top"; c.textAlign = "left";
    const d = deck.data(), r = chart.timeScale().getVisibleLogicalRange();
    if (data && data.ready && data.tick && r && d.length && data.t0 === d[0].time) {
      const a = Math.max(0, Math.ceil(r.from)), z = Math.min(d.length - 1, Math.floor(r.to));
      rows = priceRows(data.cells, data.tick, a, z, (price) => series.priceToCoordinate(price), ROW_PX, H);
      const room = W - 8;
      for (const row of rows.rows) {
        const lw = (row.long / rows.max) * room, sw = (row.short / rows.max) * room;
        let x = 3;
        for (const [w, tone] of [[lw, toneOf("long")], [sw, toneOf("short")]]) {          // long first, then short, each in its own colour
          if (w <= 0) continue;
          const ww = Math.max(1.5, w);
          c.globalAlpha = 0.8; c.fillStyle = p[tone]; c.fillRect(x, Math.round(row.y - ROW_PX / 2), ww, ROW_PX - 0.5);
          x += ww;
        }
      }
    }
    c.globalAlpha = 0.9; c.fillStyle = p.surface; c.fillRect(0, 0, W, 2 * (p.fs + 2) + 4);       // the header sits on a plate over the bars
    c.globalAlpha = 1; c.fillStyle = p.muted; c.fillText("시장", 4, 3); c.fillText("청산", 4, 3 + p.fs + 2);
  }

  // ---------------------------------------------------------------- hover / tap
  const side = (s) => (s === "long" ? "롱" : "숏");
  chart.subscribeCrosshairMove((p) => bubbleTip(p && p.point ? p.point : null));
  chart.subscribeClick((p) => bubbleTip(p && p.point ? p.point : null));
  function bubbleTip(pt) {
    const was = hover;
    hover = null;
    if (on && pt && lay.items.length) {
      let best = Infinity;
      for (const it of lay.items) {
        const d = Math.hypot(it.x - pt.x, it.y - pt.y);
        if (d <= it.r + 3 && d < best) { best = d; hover = it; }
      }
    }
    if (!hover) { tip.hide(); if (was && api) api.requestUpdate(); return; }
    const b = hover.b, big = b.big || {};
    tip.show([h("b", {class: toneOf(b.side)}, `${side(b.side)} 청산 ${koUsdt(b.usd)} · ${fmt.int(b.n)}건`),
      `가장 큰 건 ${koUsdt(big.usd)} @ ${fmt.price(big.px)}`,
      h("small", {class: "muted"}, `${fmt.kst(b.t * 1000)} 봉 · 바이낸스 전체 (우리 봇 아님)`)], hover.x, hover.y, strip.parentElement.offsetLeft);
    if (hover !== was && api) api.requestUpdate();
  }
  strip.addEventListener("pointermove", (e) => {
    const r = strip.getBoundingClientRect(), y = e.clientY - r.top;
    const row = rows.rows.reduce((best, x) => (Math.abs(x.y - y) <= 6 && (!best || Math.abs(x.y - y) < Math.abs(best.y - y)) ? x : best), null);
    if (!row) { tip.hide(); return; }
    const price = series.coordinateToPrice(row.y), wr = wrap.getBoundingClientRect();
    tip.show([h("b", null, `${price == null ? "" : fmt.price(price) + " 근처"}`),
      h("span", {class: toneOf("long")}, row.long > 0 ? `롱 청산 ${koUsdt(row.long)}` : "롱 청산 기록 없음"),
      h("span", {class: toneOf("short")}, row.short > 0 ? `숏 청산 ${koUsdt(row.short)}` : "숏 청산 기록 없음"),
      h("small", {class: "muted"}, "보이는 봉 동안의 합계 · 바이낸스 전체 (우리 봇 아님)")], e.clientX - wr.left, e.clientY - wr.top, strip.parentElement.offsetLeft);
  });
  strip.addEventListener("pointerleave", () => tip.hide());

  return {
    tip,
    setOn(v) {
      on = !!v;
      if (!on) { data = null; err = null; lay = {items: [], veil: null, gaps: []}; tip.hide(); }
      paint(); if (api) api.requestUpdate(); report();
      if (on) load();
    },
    reload() { if (on) load(); },
    /** the candles were replaced ("set": a new coin or bar width) or a bar changed: a new window asks again, a live bar only repaints */
    onData(how) {
      if (!on) return;
      if (how === "set") { data = null; err = null; lay = {items: [], veil: null, gaps: []}; report(); paint(); if (api) api.requestUpdate(); load(); }
    },
    paint, view,
  };
}
